"""Optional historical replay of the paper bots: "conditional historical simulation".

The same frozen bot rules (``paper_bots._build_decision``) run over the stored score history and the stored price
history, and the resulting decisions go through the same next-session paper execution. The output is stored in its own
store and ledger root with its own entity types and is always labelled: fundamentals are not point-in-time and the
universe is not survivor-free (Part 4 stop rule 2), so it only debugs the rules and is never forward evidence.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any, Literal, Mapping

import pandas as pd

from etf_cockpit.data.replay_membership import (
    ListingHistory, MembershipPriceBook, STRICT_MODE, SURVIVORSHIP_MODES, SURVIVORSHIP_UNVERIFIED_BANNER,
    delisting_unverified_in_history, replay_preflight, unverified_instruments,
)
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import StorageRevisionConflict, TransactionalStore
from etf_cockpit.data.score_history_backfill import load_backfill_eligibility, load_backfill_score_history
from etf_cockpit.portfolio import paper_bots_readiness as data_readiness
from etf_cockpit.portfolio import paper_bots as bots
from etf_cockpit.portfolio import paper_bots_execution as execution

_REQUIRED_HISTORY_COLUMNS = {"run_id", "run_completed_at", "snapshot_hash", "instrument_id", "formula_version", "formula_checksum"}


def run_historical_replay(
    as_of: datetime | date | str,
    *,
    root: Path | None = None,
    history: pd.DataFrame | None = None,
    price_book: execution.PriceBook | None = None,
    config_path: Path | None = None,
    execution_config_path: Path | None = None,
    now: datetime | None = None,
    history_source: Literal["published", "backfill"] = "published",
    survivorship_mode: str = STRICT_MODE,
) -> execution.ExecutionRunResult:
    """Replay every stored score run known at ``as_of`` into the separate replay record.

    ``history_source`` "published" (default) reads the live published score history. "backfill" reads the separate
    historical-backfill store (``historical_backfill`` provenance); the replay record, ledger root and label are the same.
    An explicit ``history`` frame overrides both.

    ``survivorship_mode`` "strict" (default) fails closed on instruments without verified listing history. "unverified-delistings"
    also admits instruments whose listing is derived from their first price date; the delisting stays unverified and every
    decision and the result carry ``survivorship_unverified``.
    """

    project_root = Path(root or ROOT).resolve()
    try:
        cutoff = bots._as_of_timestamp(as_of)
        _bytes, config = execution.load_execution_config(
            execution_config_path or execution._config_file(project_root, "paper_bots_execution_v1.yaml", execution.EXECUTION_CONFIG_PATH)
        )
    except (OSError, TypeError, ValueError) as exc:
        return execution.ExecutionRunResult("unavailable", "replay", None, reason=f"Invalid replay request: {exc}")
    if survivorship_mode not in SURVIVORSHIP_MODES:
        return execution.ExecutionRunResult("unavailable", "replay", None, reason=f"Invalid replay request: unknown survivorship_mode {survivorship_mode!r}.")
    if history_source not in ("published", "backfill"):
        return execution.ExecutionRunResult("unavailable", "replay", None, reason=f"Invalid replay request: unknown history_source {history_source!r}.")
    clock = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    track = execution.replay_track(project_root, config)
    if cutoff > clock + timedelta(minutes=5):
        return execution.ExecutionRunResult("unavailable", "replay", bots._time_text(cutoff), reason="as_of is in the future.", label=track.label)

    try:
        frame = history if history is not None else (
            load_backfill_score_history(project_root) if history_source == "backfill"
            else bots._load_published_score_history(project_root)
        )
        readiness_days = []
        if isinstance(frame, pd.DataFrame) and "as_of_date" in frame.columns:
            readiness_days = [
                value for value in pd.to_datetime(frame["as_of_date"], errors="coerce").dropna().dt.date
                if value <= cutoff.date()
            ]
        readiness_start = min(readiness_days) if readiness_days else cutoff.date()
        readiness_end = max(readiness_days) if readiness_days else cutoff.date()
        readiness_failure = data_readiness.paper_bot_readiness_failure(
            project_root, readiness_start, readiness_end
        )
        if readiness_failure is not None:
            return execution.ExecutionRunResult(
                "unavailable", "replay", bots._time_text(cutoff),
                reason=f"Paper bot data readiness blocked:\n{readiness_failure}", label=track.label,
            )
        membership = ListingHistory.from_root(project_root)
        book = price_book if price_book is not None else execution.PriceBook.from_root(project_root)
        if survivorship_mode != STRICT_MODE:
            membership = membership.with_price_history(book.first_price_dates(), survivorship_mode)
        failure = replay_preflight(frame, membership, book, cutoff)
        flagged = [] if failure else delisting_unverified_in_history(frame, membership, cutoff)
        unknown = unverified_instruments(load_backfill_eligibility(project_root)) if history_source == "backfill" else []
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        return execution.ExecutionRunResult("unavailable", "replay", bots._time_text(cutoff), reason=f"Membership preflight unavailable: {type(exc).__name__}.", label=track.label)
    if failure:
        return execution.ExecutionRunResult("unavailable", "replay", bots._time_text(cutoff), reason=failure, label=track.label)
    price_book = MembershipPriceBook(book, membership)
    label = {"survivorship_unverified": True, "survivorship_unverified_ids": flagged, "survivorship_banner": SURVIVORSHIP_UNVERIFIED_BANNER} if flagged else {}

    def prepare(store: TransactionalStore, bots_config: Mapping[str, Any], config_hash: str, book: execution.PriceBook, warnings: list[str]) -> None:
        if flagged:
            warnings.append(SURVIVORSHIP_UNVERIFIED_BANNER + " Admitted: " + ", ".join(flagged))
        if unknown:
            warnings.append("survivorship-unverified: " + ", ".join(unknown))
        if history_source == "backfill":
            warnings.append("Historical score backfill with point-in-time listing membership; conditional simulation, never forward evidence.")
        _write_replay_decisions(store, track, bots_config, config_hash, book, frame, cutoff, warnings, label)

    result = execution._run(track, project_root, cutoff, config_path, execution_config_path, price_book, prepare)
    return replace(result, survivorship_unverified=True) if flagged else result


def _write_replay_decisions(
    store: TransactionalStore, track: execution.Track, config: Mapping[str, Any], config_hash: str, book: execution.PriceBook,
    history: pd.DataFrame, cutoff: datetime, warnings: list[str], label: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(history, pd.DataFrame) or history.empty:
        warnings.append("No stored score history to replay.")
        return
    if not _REQUIRED_HISTORY_COLUMNS.issubset(history.columns):
        warnings.append("Stored score history lacks the snapshot lineage fields; nothing can be replayed.")
        return
    grouped: dict[str, list[dict[str, Any]]] = {}
    history_rows = history.to_dict(orient="records")
    snapshot_run_ids = bots._snapshot_run_identities(history_rows, cutoff)
    for row in history_rows:
        run_id = bots._real_text(row.get("run_id"))
        if run_id is not None:
            grouped.setdefault(run_id, []).append(row)
    groups: list[bots._PublishedGroup] = []
    skipped = 0
    for run_id, rows in grouped.items():
        group, error = bots._validate_run(run_id, rows, cutoff, snapshot_run_ids=snapshot_run_ids)
        if group is None:
            skipped += 1 if error else 0
            continue
        groups.append(group)
    groups.sort(key=lambda item: (item.known_at, item.run_id))
    if skipped:
        warnings.append(f"Skipped {skipped} stored score runs without verifiable lineage.")
    if not groups:
        warnings.append("No stored score run is usable for the replay.")
        return

    baseline_version = str(config["baseline_score_version"])
    baseline = next((group for group in groups if group.score_version == baseline_version), None)
    specs = {item["family_id"]: item for item in config["bots"]}
    plan: list[tuple[Mapping[str, Any], str | None, list[bots._PublishedGroup]]] = [(specs["B0"], None, groups)]
    if baseline is None:
        warnings.append(f"No stored score run carries the baseline score version {baseline_version}; B1/B2/B3 are not replayed.")
    else:
        pinned = [group for group in groups if group.lineage_hash == baseline.lineage_hash]
        plan += [(specs[family], baseline.lineage_hash, pinned) for family in bots._CADENCE_FAMILIES]
    by_lineage: dict[str, list[bots._PublishedGroup]] = {}
    for group in groups:
        if baseline is None or group.lineage_hash != baseline.lineage_hash:
            by_lineage.setdefault(group.lineage_hash, []).append(group)
    for lineage_hash, candidates in sorted(by_lineage.items(), key=lambda pair: (pair[1][0].known_at, pair[0])):
        for family in ("B1", "B2"):
            plan.append((bots._challenger_spec(specs[family], family, candidates[0].score_version), lineage_hash, candidates))

    unavailable = 0
    for spec, lineage_hash, candidates in plan:
        bot_id = bots._bot_identity(spec, config_hash, lineage_hash)
        months: dict[str, list[bots._PublishedGroup]] = {}
        for group in candidates:
            months.setdefault(group.known_at.strftime("%Y-%m"), []).append(group)
        first_month: str | None = None  # the cadence is counted from the first month with a verifiable decision
        for month, month_candidates in sorted(months.items()):
            if not bots._cadence_due(spec, month, first_month):
                continue  # not a rebalance month for this bot (B0 decides once): no new target
            decision, group, failure = bots._first_successful_candidate(
                spec, bot_id, config_hash, config, cutoff, month, month_candidates, lineage_hash,
                lambda candidate: _matched_rows(candidate, book), historical=True,
            )
            if decision is None or group is None:
                unavailable += 1
                continue
            first_month = first_month or month
            decision_id = bots._decision_id(bot_id, month, group.snapshot_hash)
            decision.update(
                decision_id=decision_id, track="replay", label=track.label, caveat=track.caveat, **(label or {}),
            )
            if store.get(track.decision_type, decision_id) is not None:
                continue
            try:
                store.put_many([(track.decision_type, decision_id, decision)], immutable=True)
            except StorageRevisionConflict:
                warnings.append(f"Replay decision {decision_id[:12]} already exists with different content; the first one is kept.")
    if unavailable:
        warnings.append(f"{unavailable} replay bot-months had no verifiable inputs (price, gate, rank or freshness) and are not replayed.")


def _matched_rows(group: bots._PublishedGroup, book: execution.PriceBook) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Pair each stored score row with the board fields the live rules read, taken from the stored price history."""

    matched: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row in group.rows:
        instrument = str(row.get("instrument_id"))
        price_date = bots._date_text(row.get("price_as_of_date"))
        bar = book.last_bar(instrument, date.fromisoformat(price_date)) if price_date else None
        board = {
            "symbol": row.get("yahoo_ticker"),
            "instrument_currency": None if bar is None else bar.get("currency"),
            "current_price": None if bar is None else bar.get("close"),
            "latest_price_date": None if bar is None else bar["date"].date().isoformat(),
            "research_promotion_allowed": row.get("research_promotion_allowed"),
            "analysis_status": row.get("analysis_status"),
            "legacy_action": row.get("legacy_action") if bots._real_text(row.get("legacy_action")) else row.get("final_action"),
        }
        matched[instrument] = (dict(row), board)
    return matched


__all__ = ["run_historical_replay"]
