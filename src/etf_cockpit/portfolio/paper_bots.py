"""Forward-only, decision-only paper bot recorder.

This module freezes targets from the published scoreboard and its matching
score-history publication. It never creates proposals, orders, fills or marks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
)
from etf_cockpit.signals.simple_scores import load_simple_scoreboard


PAPER_BOTS_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "paper_bots_v1.yaml"
DECISION_ENTITY_TYPE = "paper_bot_decision"
MONTH_SLOT_ENTITY_TYPE = "paper_bot_month_slot"
BASELINE_ENTITY_TYPE = "paper_bot_score_baseline"
PUBLICATION_BINDING_ENTITY_TYPE = "scoreboard_publication_binding"
EXECUTION_ALLOWED = False
NETWORK_ACCESS_ALLOWED = False
_UNAVAILABLE_TEXT = {"", "none", "null", "nan", "unavailable", "unknown"}
_ACCEPTED_FRESHNESS = {"ok", "fresh"}


@dataclass(frozen=True)
class PaperBotRunResult:
    status: str
    as_of: str | None
    snapshot_hash: str | None
    records: tuple[dict[str, Any], ...]
    reason: str | None = None
    appended: int = 0


@dataclass(frozen=True)
class _PublishedGroup:
    run_id: str
    known_at: datetime
    score_completed_at: datetime
    snapshot_hash: str
    score_version: str
    lineage_hash: str
    lineage_material: dict[str, Any]
    rows: tuple[dict[str, Any], ...]

    @property
    def lineage_version(self) -> str:
        return f"{self.score_version}@{self.lineage_hash}"


def run_paper_bots(
    as_of: datetime | date | str,
    *,
    root: Path | None = None,
    config_path: Path | None = None,
) -> PaperBotRunResult:
    """Record this month's first eligible published decision for each bot."""

    project_root = Path(root or ROOT).resolve()
    try:
        cutoff = _as_of_timestamp(as_of)
    except (TypeError, ValueError) as exc:
        return PaperBotRunResult("unavailable", None, None, (), f"Invalid as_of: {exc}")

    now = datetime.now(timezone.utc)
    if cutoff.date() != now.date() or cutoff > now + timedelta(minutes=5):
        return PaperBotRunResult(
            "unavailable",
            _time_text(cutoff),
            None,
            (),
            "Forward recorder accepts only the current UTC calendar day; historical replay is not mixed into forward records.",
        )

    selected_config_path = Path(
        config_path or (project_root / "configs" / "paper_bots_v1.yaml")
    )
    try:
        config_bytes, config = _load_config(selected_config_path)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return PaperBotRunResult("unavailable", _time_text(cutoff), None, (), f"Bot specification unavailable: {type(exc).__name__}.")

    config_hash = hashlib.sha256(config_bytes).hexdigest()
    month = cutoff.strftime("%Y-%m")
    try:
        history = _load_published_score_history(project_root)
    except Exception as exc:
        return _persist_unavailable(
            project_root,
            cutoff,
            month,
            config,
            config_hash,
            f"Published score history unavailable: {type(exc).__name__}.",
        )

    try:
        groups, group_error = _published_groups(history, cutoff)
    except (TypeError, ValueError, KeyError) as exc:
        groups, group_error = (), f"Published score history is unverifiable: {type(exc).__name__}."
    if group_error:
        return _persist_unavailable(project_root, cutoff, month, config, config_hash, group_error)

    scoreboard_path = project_root / "data" / "derived" / "scoreboard.parquet"
    scoreboard_digest = None
    try:
        scoreboard_bytes = scoreboard_path.read_bytes()
        scoreboard_digest = hashlib.sha256(scoreboard_bytes).hexdigest()
        scoreboard = load_simple_scoreboard(
            scoreboard_path, root=project_root, scoreboard_bytes=scoreboard_bytes
        )
        if not isinstance(scoreboard, pd.DataFrame):
            scoreboard = pd.DataFrame()
    except Exception:
        scoreboard = pd.DataFrame()

    try:
        with TransactionalStore(project_root, read_only=True) as binding_store:
            bindings = tuple(record.payload for record in binding_store.list(PUBLICATION_BINDING_ENTITY_TYPE))
    except Exception:
        bindings = ()
    groups = _bind_publication_groups(groups, bindings, scoreboard_digest, cutoff)
    current_month_groups = [group for group in groups if group.known_at.strftime("%Y-%m") == month]
    if not current_month_groups:
        return _persist_unavailable(
            project_root,
            cutoff,
            month,
            config,
            config_hash,
            "No scoreboard publication with matching immutable bytes is known in the current UTC month.",
        )

    try:
        with TransactionalStore(project_root) as store:
            baseline_id = _baseline_id(config_hash, str(config["baseline_score_version"]))
            baseline_record = store.get(BASELINE_ENTITY_TYPE, baseline_id)
            stored_baseline = baseline_record.payload if baseline_record is not None else None
            baseline_error = None
            stored_baseline_usable = False
            if isinstance(stored_baseline, Mapping):
                stored_known_at = _parse_timestamp(stored_baseline.get("known_at"))
                if stored_known_at is None:
                    baseline_error = "Pinned baseline known_at is unverifiable."
                elif stored_known_at <= cutoff:
                    stored_baseline_usable = bool(
                        stored_baseline.get("config_hash") == config_hash
                        and stored_baseline.get("baseline_score_version") == str(config["baseline_score_version"])
                        and _is_sha256(_real_text(stored_baseline.get("lineage_hash")))
                        and _is_sha256(_real_text(stored_baseline.get("source_snapshot_hash")))
                        and stored_baseline.get("score_lineage_version")
                        == f"{stored_baseline.get('baseline_score_version')}@{stored_baseline.get('lineage_hash')}"
                        and stored_baseline.get("execution_allowed") is False
                    )
                    if not stored_baseline_usable:
                        baseline_error = "Pinned baseline evidence is malformed or conflicting."
            ordered_groups = sorted(
                current_month_groups,
                key=lambda item: (item.known_at, item.score_version, item.lineage_hash),
            )
            baseline_history = sorted(
                (
                    group for group in groups
                    if group.score_version == str(config["baseline_score_version"])
                ),
                key=lambda item: (item.known_at, item.lineage_hash),
            )
            baseline_source = None
            if stored_baseline_usable:
                baseline_lineage_hash = str(stored_baseline["lineage_hash"])
                baseline_source = next(
                    (group for group in groups if group.lineage_hash == baseline_lineage_hash),
                    None,
                )
            else:
                baseline_source = baseline_history[0] if baseline_history else None
                baseline_lineage_hash = baseline_source.lineage_hash if baseline_source is not None else None
            baseline_payload_to_store = (
                {
                    "baseline_score_version": baseline_source.score_version,
                    "score_lineage_version": baseline_source.lineage_version,
                    "lineage_hash": baseline_source.lineage_hash,
                    "lineage_material": baseline_source.lineage_material,
                    "source_snapshot_hash": baseline_source.snapshot_hash,
                    "known_at": _time_text(baseline_source.known_at),
                    "config_hash": config_hash,
                    "execution_allowed": False,
                }
                if baseline_source is not None
                else None
            )
            tasks: list[tuple[dict[str, Any], tuple[_PublishedGroup, ...], str | None, str]] = []

            benchmark_spec = next(item for item in config["bots"] if item["family_id"] == "B0")
            benchmark_id = _bot_identity(benchmark_spec, config_hash, None)
            tasks.append((benchmark_spec, tuple(ordered_groups), None, benchmark_id))

            baseline_groups = [
                group for group in ordered_groups
                if group.score_version == str(config["baseline_score_version"])
                and group.lineage_hash == baseline_lineage_hash
            ]
            for family in ("B1", "B2"):
                spec = next(item for item in config["bots"] if item["family_id"] == family)
                bot_id = _bot_identity(spec, config_hash, baseline_lineage_hash)
                tasks.append((spec, tuple(baseline_groups), baseline_lineage_hash, bot_id))

            challenger_groups: dict[str, list[_PublishedGroup]] = {}
            for group in ordered_groups:
                if group.lineage_hash == baseline_lineage_hash:
                    continue
                challenger_groups.setdefault(group.lineage_hash, []).append(group)
            for lineage_hash, candidates in sorted(
                challenger_groups.items(), key=lambda item: (item[1][0].known_at, item[0])
            ):
                first_candidate = candidates[0]
                for strategy_family in ("B1", "B2"):
                    source_spec = next(item for item in config["bots"] if item["family_id"] == strategy_family)
                    challenger_spec = dict(source_spec)
                    challenger_spec["family_id"] = f"B3-{strategy_family.lower()}"
                    challenger_spec["name"] = f"Challenger {first_candidate.score_version}: {source_spec['name']}"
                    bot_id = _bot_identity(challenger_spec, config_hash, lineage_hash)
                    tasks.append((challenger_spec, tuple(candidates), lineage_hash, bot_id))

            results: list[dict[str, Any]] = []
            appended = 0
            snapshot_hashes: set[str] = set()
            for spec, candidates, expected_lineage_hash, bot_id in tasks:
                slot_id = _month_slot_id(bot_id, month)
                existing_slot = store.get(MONTH_SLOT_ENTITY_TYPE, slot_id)
                if existing_slot is not None:
                    existing = store.get(DECISION_ENTITY_TYPE, str(existing_slot.payload.get("decision_id", "")))
                    slot_known_at = _parse_timestamp(existing_slot.payload.get("known_at"))
                    saved_as_of = _parse_timestamp(existing.payload.get("as_of")) if existing is not None else None
                    saved_known_at = _parse_timestamp(existing.payload.get("known_at")) if existing is not None else None
                    if (
                        existing is None
                        or slot_known_at is None
                        or saved_as_of is None
                        or saved_known_at is None
                        or slot_known_at > cutoff
                        or saved_as_of > cutoff
                        or saved_known_at > cutoff
                        or slot_known_at != saved_known_at
                        or existing.payload.get("bot_id") != bot_id
                        or existing.payload.get("decision_month") != month
                        or existing.payload.get("status") != "available"
                        or existing.payload.get("execution_allowed") is not False
                        or existing_slot.payload.get("decision_id") != existing.entity_id
                        or existing_slot.payload.get("snapshot_hash") != existing.payload.get("snapshot_hash")
                    ):
                        results.append(_unavailable_record(
                            spec, bot_id, config_hash, config, cutoff, month,
                            "Monthly decision slot is missing, malformed, or newer than as_of.",
                        ))
                    else:
                        results.append(dict(existing.payload))
                        if existing.payload.get("status") == "available":
                            snapshot_hashes.add(str(existing.payload.get("snapshot_hash") or ""))
                    continue

                decision = None
                group = None
                failure = baseline_error if spec.get("family_id") in {"B1", "B2"} else None
                last_group = candidates[-1] if candidates else None
                if failure is None and not candidates:
                    failure = (
                        "Pinned baseline score lineage is not present in a published snapshot known at as_of."
                        if expected_lineage_hash is not None
                        else "No complete score snapshot is bound to the scoreboard known at as_of."
                    )
                for candidate in (() if failure else candidates):
                    if candidate.known_at > cutoff:
                        failure = "Published scoreboard is newer than as_of."
                        continue
                    age = cutoff - candidate.known_at
                    if age > timedelta(hours=float(config["max_snapshot_age_hours"])):
                        age_limit = float(config["max_snapshot_age_hours"])
                        failure = f"Published score snapshot is stale for the configured {age_limit:g}-hour forward window."
                        continue
                    if expected_lineage_hash is not None and candidate.lineage_hash != expected_lineage_hash:
                        failure = "Published score lineage conflicts with the bot's pinned lineage."
                        continue
                    matched_rows = _matched_score_rows(candidate, scoreboard)
                    if matched_rows is None:
                        failure = "Published scoreboard does not match the selected score-history snapshot."
                        continue
                    candidate_decision, candidate_failure = _build_decision(
                        spec, bot_id, config_hash, config, cutoff, month, candidate, matched_rows
                    )
                    if candidate_failure:
                        failure = candidate_failure
                        continue
                    decision, group = candidate_decision, candidate
                    break

                if decision is None or group is None:
                    decision = _unavailable_record(
                        spec, bot_id, config_hash, config, cutoff, month,
                        failure or "No eligible published snapshot is available.",
                        snapshot_hash=last_group.snapshot_hash if last_group else None,
                        known_at=_time_text(last_group.known_at) if last_group else None,
                        lineage_version=last_group.lineage_version if last_group else None,
                    )
                    _append_unavailable(store, decision)
                    results.append(decision)
                    continue

                decision_id = _decision_id(bot_id, month, group.snapshot_hash)
                decision["decision_id"] = decision_id
                slot = {
                    "bot_id": bot_id,
                    "decision_month": month,
                    "decision_id": decision_id,
                    "snapshot_hash": group.snapshot_hash,
                    "known_at": _time_text(group.known_at),
                    "execution_allowed": False,
                }
                writes: list[tuple[str, str, Mapping[str, Any]]] = [
                    (DECISION_ENTITY_TYPE, decision_id, decision),
                    (MONTH_SLOT_ENTITY_TYPE, slot_id, slot),
                ]
                if (
                    baseline_payload_to_store is not None
                    and group.lineage_hash == baseline_payload_to_store.get("lineage_hash")
                    and store.get(BASELINE_ENTITY_TYPE, baseline_id) is None
                ):
                    writes.append((BASELINE_ENTITY_TYPE, baseline_id, baseline_payload_to_store))
                try:
                    store.put_many(writes, immutable=True)
                    appended += 1
                    stored_decision = decision
                except StorageRevisionConflict:
                    current_slot = store.get(MONTH_SLOT_ENTITY_TYPE, slot_id)
                    if current_slot is None:
                        raise
                    current_decision = store.get(
                        DECISION_ENTITY_TYPE,
                        str(current_slot.payload.get("decision_id", "")),
                    )
                    if current_decision is None:
                        raise StorageRevisionConflict("monthly decision slot lost its immutable decision record")
                    winner_as_of = _parse_timestamp(current_decision.payload.get("as_of"))
                    winner_known_at = _parse_timestamp(current_decision.payload.get("known_at"))
                    if (
                        winner_as_of is None
                        or winner_known_at is None
                        or winner_as_of > cutoff
                        or winner_known_at > cutoff
                    ):
                        stored_decision = _unavailable_record(
                            spec, bot_id, config_hash, config, cutoff, month,
                            "Concurrent monthly decision was recorded after as_of.",
                        )
                    else:
                        stored_decision = dict(current_decision.payload)
                results.append(dict(stored_decision))
                snapshot_hashes.add(str(stored_decision.get("snapshot_hash") or ""))

            available_count = sum(item.get("status") == "available" for item in results)
            unavailable_count = sum(item.get("status") == "unavailable" for item in results)
            status = (
                "unavailable" if not available_count
                else "partial" if unavailable_count
                else "available"
            )
            result_snapshot = next(iter(snapshot_hashes)) if len(snapshot_hashes) == 1 else None
            reason = None if status == "available" else (
                "Some bot decisions are unavailable; inspect each immutable record reason."
                if status == "partial"
                else "No bot decision could be recorded from a verified published snapshot."
            )
            return PaperBotRunResult(status, _time_text(cutoff), result_snapshot, tuple(results), reason, appended)
    except (OSError, ValueError, KeyError, StorageSchemaError, StorageRevisionConflict) as exc:
        return PaperBotRunResult(
            "unavailable",
            _time_text(cutoff),
            None,
            (),
            f"Paper bot recorder unavailable: {type(exc).__name__}.",
        )


def _load_config(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    payload = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "paper_bots.v1":
        raise ValueError("unsupported paper bot specification")
    bots = payload.get("bots")
    if not isinstance(bots, list) or {str(item.get("family_id")) for item in bots if isinstance(item, dict)} != {"B0", "B1", "B2"}:
        raise ValueError("paper bot specification must define B0, B1 and B2 exactly once")
    if len({str(item["family_id"]) for item in bots}) != 3:
        raise ValueError("paper bot family IDs must be unique")
    for key in ("initial_virtual_cash_eur", "monthly_contribution_eur", "max_snapshot_age_hours"):
        number = _finite_number(payload.get(key))
        if number is None or number < 0 or (key == "initial_virtual_cash_eur" and number <= 0):
            raise ValueError(f"invalid paper bot setting: {key}")
        payload[key] = number
    if not isinstance(payload.get("benchmark"), dict):
        raise ValueError("paper bot benchmark is missing")
    baseline_version = _real_text(payload.get("baseline_score_version"))
    if baseline_version is None:
        raise ValueError("baseline score version is unavailable")
    eligibility = payload.get("eligibility")
    if not isinstance(eligibility, dict) or eligibility.get("gate") != "research_promotion_allowed":
        raise ValueError("paper bot gate must use the published research_promotion_allowed status")
    if eligibility.get("required_analysis_status") != "complete":
        raise ValueError("paper bot analysis status must be complete")
    for item in bots:
        if not isinstance(item, dict) or item.get("strategy") not in {"benchmark", "top_n", "core_sleeve"}:
            raise ValueError("unsupported paper bot strategy")
        if item["strategy"] == "top_n":
            if _positive_int(item.get("top_n")) is None:
                raise ValueError("top_n strategy requires a positive integer top_n")
            asset_types = item.get("asset_types")
            if (
                not isinstance(asset_types, list)
                or not asset_types
                or any(str(value).strip().upper() not in {"ETF", "STOCK"} for value in asset_types)
            ):
                raise ValueError("top_n asset_types must be a non-empty ETF/STOCK list")
        if item["strategy"] == "core_sleeve":
            core = _finite_number(item.get("core_weight"))
            sleeve = _finite_number(item.get("sleeve_weight"))
            sleeve_n = _positive_int(item.get("sleeve_top_n"))
            if (
                core is None or sleeve is None or sleeve_n is None
                or core < 0 or sleeve < 0
                or not math.isclose(core + sleeve, 1.0, rel_tol=0.0, abs_tol=1e-12)
            ):
                raise ValueError("core_sleeve weights must be finite, non-negative, sum to one, and use a positive sleeve_top_n")
            if _real_text(item.get("sleeve_action")) is None:
                raise ValueError("core_sleeve requires a known sleeve_action")
    return raw, payload


def _load_published_score_history(root: Path) -> pd.DataFrame:
    """Read the persisted publication without projecting later classifications onto it."""

    path = root / "data" / "derived" / "score_history.parquet"
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _bind_publication_groups(
    groups: tuple[_PublishedGroup, ...],
    bindings: tuple[Mapping[str, Any], ...],
    scoreboard_digest: str | None,
    cutoff: datetime,
) -> tuple[_PublishedGroup, ...]:
    if scoreboard_digest is None:
        return ()
    by_publication: dict[tuple[str, str], list[tuple[datetime, datetime]]] = {}
    for binding in bindings:
        if (
            binding.get("schema_version") != "scoreboard_publication_binding.v1"
            or binding.get("scoreboard_sha256") != scoreboard_digest
            or binding.get("execution_allowed") is not False
        ):
            continue
        run_id = _real_text(binding.get("run_id"))
        snapshot_hash = _real_text(binding.get("score_snapshot_hash"))
        published_at = _parse_timestamp(binding.get("known_at"))
        score_completed_at = _parse_timestamp(binding.get("score_completed_at"))
        if (
            run_id is None
            or not _is_sha256(snapshot_hash)
            or published_at is None
            or score_completed_at is None
            or published_at < score_completed_at
            or published_at > cutoff
        ):
            continue
        by_publication.setdefault((run_id, snapshot_hash), []).append((published_at, score_completed_at))

    verified: list[_PublishedGroup] = []
    for group in groups:
        publication_times = [
            published_at
            for published_at, score_completed_at in by_publication.get((group.run_id, group.snapshot_hash), [])
            if score_completed_at == group.score_completed_at
        ]
        if not publication_times:
            continue
        verified.append(replace(group, known_at=min(publication_times)))
    return tuple(sorted(verified, key=lambda item: (item.known_at, item.run_id, item.score_version, item.lineage_hash)))


def _published_groups(history: pd.DataFrame, cutoff: datetime) -> tuple[tuple[_PublishedGroup, ...], str | None]:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return (), None
    required = {"run_id", "run_completed_at", "snapshot_hash", "instrument_id", "formula_version", "formula_checksum"}
    if not required.issubset(set(history.columns)):
        return (), "Published score history is missing required snapshot lineage fields."

    rows = history.to_dict(orient="records")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        run_id = _real_text(raw.get("run_id"))
        if run_id is None:
            return (), "Published score history contains a row with no run identity."
        known_at = _parse_timestamp(raw.get("run_completed_at"))
        if known_at is None:
            return (), "Published score history contains a row with unverifiable known_at."
        if known_at > cutoff:
            continue
        prepared = dict(raw)
        prepared["_known_at"] = known_at
        grouped.setdefault(run_id, []).append(prepared)

    output: list[_PublishedGroup] = []
    for run_id, run_rows in grouped.items():
        instrument_ids = [_real_text(row.get("instrument_id")) for row in run_rows]
        if None in instrument_ids or len(set(instrument_ids)) != len(instrument_ids):
            return (), f"Published score run {run_id} has missing or duplicate instrument identities."
        known_times = {row["_known_at"] for row in run_rows}
        hashes = {_real_text(row.get("snapshot_hash")) for row in run_rows}
        if len(known_times) != 1 or len(hashes) != 1 or None in hashes:
            return (), f"Published score run {run_id} has conflicting time or snapshot hash."
        snapshot_hash = next(iter(hashes))
        if not _is_sha256(snapshot_hash):
            return (), f"Published score run {run_id} has an invalid snapshot hash."
        by_version: dict[str, list[dict[str, Any]]] = {}
        for row in run_rows:
            version = _real_text(row.get("formula_version"))
            checksum = _real_text(row.get("formula_checksum"))
            if version is None or checksum is None or not _is_sha256(checksum):
                return (), f"Published score run {run_id} has unverifiable formula lineage."
            by_version.setdefault(version, []).append(row)
        if len(by_version) != 1:
            return (), f"Published score run {run_id} has conflicting formula versions."
        for version, version_rows in by_version.items():
            lineage_material = _lineage_material(version_rows)
            if lineage_material is None:
                return (), f"Published score run {run_id} has incomplete lineage evidence."
            lineage_hash = _sha256_json(lineage_material)
            output.append(
                _PublishedGroup(
                    run_id=run_id,
                    known_at=next(iter(known_times)),
                    score_completed_at=next(iter(known_times)),
                    snapshot_hash=snapshot_hash,
                    score_version=version,
                    lineage_hash=lineage_hash,
                    lineage_material=lineage_material,
                    rows=tuple(version_rows),
                )
            )
    output.sort(key=lambda item: (item.known_at, item.run_id, item.score_version, item.lineage_hash))
    return tuple(output), None


def _lineage_material(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    required = ("formula_version", "formula_checksum", "score_schema_version", "gate_policy_version", "gate_policy_checksum")
    for row in rows:
        if any(_real_text(row.get(field)) is None for field in required):
            return None
        if any(not _is_sha256(_real_text(row.get(field))) for field in ("formula_checksum", "gate_policy_checksum")):
            return None
    formula_versions = sorted({_real_text(row.get("formula_version")) for row in rows} - {None})
    formula_checksums = sorted({_real_text(row.get("formula_checksum")) for row in rows} - {None})
    schema_versions = sorted({_real_text(row.get("score_schema_version")) for row in rows} - {None})
    gate_versions = sorted({_real_text(row.get("gate_policy_version")) for row in rows} - {None})
    gate_checksums = sorted({_real_text(row.get("gate_policy_checksum")) for row in rows} - {None})
    if any(not values for values in (formula_versions, formula_checksums, schema_versions, gate_versions, gate_checksums)):
        return None
    if any(any(value.casefold() in _UNAVAILABLE_TEXT for value in values) for values in (formula_versions, formula_checksums, schema_versions, gate_versions, gate_checksums)):
        return None
    if len(formula_versions) != 1:
        return None
    return {
        "formula_version": formula_versions[0],
        "formula_checksums": formula_checksums,
        "score_schema_versions": schema_versions,
        "gate_policy_versions": gate_versions,
        "gate_policy_checksums": gate_checksums,
    }


def _matched_score_rows(
    group: _PublishedGroup,
    scoreboard: pd.DataFrame,
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]] | None:
    if scoreboard.empty or "instrument_id" not in scoreboard.columns:
        return None
    board_rows: dict[str, dict[str, Any]] = {}
    for row in scoreboard.to_dict(orient="records"):
        instrument_id = _real_text(row.get("instrument_id"))
        if instrument_id is None or instrument_id in board_rows:
            return None
        board_rows[instrument_id] = row

    matched: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    history_ids = {
        _real_text(history_row.get("instrument_id"))
        for history_row in group.rows
    }
    if None in history_ids or history_ids != set(board_rows):
        return None
    for history_row in group.rows:
        instrument_id = _real_text(history_row.get("instrument_id"))
        if instrument_id is None:
            return None
        board_row = board_rows.get(instrument_id)
        if board_row is None or not _history_row_matches_board(history_row, board_row):
            return None
        matched[instrument_id] = (history_row, board_row)
    return matched


def _history_row_matches_board(history_row: Mapping[str, Any], board_row: Mapping[str, Any]) -> bool:
    field_pairs = (
        ("asset_type", "asset_type"),
        ("price_as_of_date", "latest_price_date"),
        ("final_combined_score_10", "final_combined_score_10"),
        ("final_label", "final_label"),
        ("final_action", "legacy_action"),
        ("formula_version", "formula_version"),
        ("formula_checksum", "formula_checksum"),
        ("score_schema_version", "score_schema_version"),
        ("source_vintage_hash", "source_vintage_hash"),
        ("classification_version_id", "classification_version_id"),
        ("classification_invalidation_hash", "classification_invalidation_hash"),
        ("classification_dependency_status", "classification_dependency_status"),
        ("gate_policy_version", "gate_policy_version"),
        ("gate_policy_checksum", "gate_policy_checksum"),
        ("analysis_status", "analysis_status"),
        ("execution_allowed", "execution_allowed"),
    )
    for history_key, board_key in field_pairs:
        if board_key not in board_row or not _same_value(history_row.get(history_key), board_row.get(board_key)):
            return False
    if "rank" in board_row and not _same_value(history_row.get("rank"), board_row.get("rank")):
        return False
    return _same_value(board_row.get("execution_allowed"), False)


def _build_decision(
    spec: Mapping[str, Any],
    bot_id: str,
    config_hash: str,
    config: Mapping[str, Any],
    cutoff: datetime,
    month: str,
    group: _PublishedGroup,
    matched: Mapping[str, tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[dict[str, Any], str | None]:
    def unavailable(reason: str) -> tuple[dict[str, Any], str]:
        return _unavailable_record(
            spec, bot_id, config_hash, config, cutoff, month, reason,
            snapshot_hash=group.snapshot_hash,
            known_at=_time_text(group.known_at),
            lineage_version=group.lineage_version,
        ), reason

    benchmark_spec = config["benchmark"]
    benchmark_row = next(
        (
            pair
            for _instrument_id, pair in matched.items()
            if str(pair[1].get("symbol") or "").strip() == str(benchmark_spec["yahoo_symbol"])
            and str(pair[0].get("instrument_id") or "").strip() == str(benchmark_spec["instrument_id"])
        ),
        None,
    )
    if benchmark_row is None:
        return unavailable("Verified VWCE.DE benchmark price is missing from the published snapshot.")

    benchmark_price, benchmark_reason = _price_evidence(benchmark_row[0], benchmark_row[1], cutoff, group.snapshot_hash)
    if benchmark_reason:
        return unavailable(f"VWCE.DE benchmark price unavailable: {benchmark_reason}.")
    if benchmark_price["currency"].upper() != "EUR":
        return unavailable("VWCE.DE benchmark price is not quoted in EUR.")

    skipped: list[dict[str, str]] = []
    targets: dict[str, float] = {}
    selected_ids: list[str] = []
    strategy = str(spec.get("strategy"))
    if strategy == "benchmark":
        targets[str(benchmark_spec["instrument_id"])] = 1.0
        selected_ids = [str(benchmark_spec["instrument_id"])]
    else:
        eligible: list[tuple[int, str, dict[str, Any], dict[str, Any]]] = []
        asset_types = set(str(item).upper() for item in spec.get("asset_types", ("ETF", "STOCK")))
        for instrument_id, (history_row, board_row) in matched.items():
            asset_type_value = _real_text(history_row.get("asset_type"))
            if asset_type_value is None:
                return unavailable(f"Instrument {instrument_id} asset type is unverifiable.")
            asset_type = asset_type_value.upper()
            if asset_type not in asset_types:
                skipped.append({"instrument_id": instrument_id, "reason": "asset_type_not_in_strategy_universe"})
                continue
            gate = _strict_bool(board_row.get("research_promotion_allowed"))
            if gate is None:
                return unavailable(f"Instrument {instrument_id} research promotion gate is unverifiable.")
            if not gate:
                skipped.append({"instrument_id": instrument_id, "reason": "research_promotion_not_allowed"})
                continue
            analysis_status = _real_text(board_row.get("analysis_status"))
            if analysis_status is None:
                return unavailable(f"Instrument {instrument_id} analysis status is unverifiable.")
            if analysis_status.casefold() != str(config["eligibility"]["required_analysis_status"]).casefold():
                skipped.append({"instrument_id": instrument_id, "reason": "analysis_incomplete"})
                continue
            freshness = _real_text(history_row.get("freshness_status"))
            if freshness is None or freshness.casefold() not in _ACCEPTED_FRESHNESS:
                return unavailable(f"Instrument {instrument_id} freshness is stale or unverifiable.")
            rank = _positive_int(history_row.get("rank"))
            if rank is None:
                return unavailable(f"Instrument {instrument_id} canonical rank is unverifiable.")
            if strategy == "core_sleeve" and _real_text(board_row.get("legacy_action")) is None:
                return unavailable(f"Instrument {instrument_id} action is unverifiable for the candidate sleeve.")
            eligible.append((rank, instrument_id, history_row, board_row))

        eligible.sort(key=lambda item: (item[0], item[1]))
        ranks = [item[0] for item in eligible]
        if len(ranks) != len(set(ranks)):
            return unavailable("Canonical rank contains duplicate positions.")

        if strategy == "top_n":
            chosen = eligible[: int(spec["top_n"])]
        elif strategy == "core_sleeve":
            chosen = [
                item for item in eligible
                if str(item[3].get("legacy_action") or "").strip() == str(spec["sleeve_action"])
            ][: int(spec["sleeve_top_n"])]
            chosen_ids = {item[1] for item in chosen}
            for item in eligible:
                if item[1] in chosen_ids:
                    continue
                reason = (
                    "rank_below_sleeve_top_n"
                    if str(item[3].get("legacy_action") or "").strip() == str(spec["sleeve_action"])
                    else "candidate_buy_not_present"
                )
                skipped.append({"instrument_id": item[1], "reason": reason})
            targets[str(benchmark_spec["instrument_id"])] = float(spec["core_weight"])
            if chosen:
                sleeve_weight = float(spec["sleeve_weight"])
                per_instrument = sleeve_weight / len(chosen)
                for item in chosen:
                    targets[item[1]] = targets.get(item[1], 0.0) + per_instrument
                selected_ids = [str(benchmark_spec["instrument_id"]), *(item[1] for item in chosen)]
            else:
                targets["cash_weight"] = float(spec["sleeve_weight"])
                selected_ids = [str(benchmark_spec["instrument_id"])]
        else:
            return unavailable("Unsupported strategy in bot specification.")

        if strategy == "top_n":
            if chosen:
                per_instrument = 1.0 / len(chosen)
                targets = {item[1]: per_instrument for item in chosen}
                selected_ids = [item[1] for item in chosen]
            else:
                targets = {"cash_weight": 1.0}
            for item in eligible[len(chosen):]:
                skipped.append({"instrument_id": item[1], "reason": "rank_below_top_n"})

    prices_used: dict[str, dict[str, Any]] = {
        str(benchmark_spec["instrument_id"]): benchmark_price
    }
    for instrument_id in selected_ids:
        if instrument_id == str(benchmark_spec["instrument_id"]):
            continue
        pair = matched.get(instrument_id)
        if pair is None:
            return unavailable(f"Selected instrument {instrument_id} is absent from the matched scoreboard.")
        price, reason = _price_evidence(pair[0], pair[1], cutoff, group.snapshot_hash)
        if reason:
            return unavailable(f"Selected instrument {instrument_id} price unavailable: {reason}.")
        prices_used[instrument_id] = price

    record = {
        "schema_version": "paper_bot_decision.v1",
        "decision_id": "",
        "bot_id": bot_id,
        "bot_family": str(spec["family_id"]),
        "bot_name": str(spec["name"]),
        "strategy": strategy,
        "status": "available",
        "reason": None,
        "spec_hash": _sha256_json({"config_hash": config_hash, "spec": dict(spec)}),
        "config_hash": config_hash,
        "score_lineage_version": group.lineage_version if strategy != "benchmark" else "not_applicable:benchmark_independent",
        "score_lineage_hash": group.lineage_hash if strategy != "benchmark" else None,
        "score_version": group.score_version if strategy != "benchmark" else None,
        "source_snapshot_hash": group.snapshot_hash,
        "snapshot_hash": group.snapshot_hash,
        "known_at": _time_text(group.known_at),
        "as_of": _time_text(cutoff),
        "decision_month": month,
        "initial_virtual_cash_eur": float(config["initial_virtual_cash_eur"]),
        "monthly_contribution_eur": float(config["monthly_contribution_eur"]),
        "currency": "EUR",
        "targets": targets,
        "prices_used": prices_used,
        "skipped_instruments": sorted(skipped, key=lambda item: (item["instrument_id"], item["reason"])),
        "authority_stage": "paper",
        "strategy_authority": "strategy:paper_portfolio",
        "execution_allowed": False,
    }
    return record, None


def _price_evidence(
    history_row: Mapping[str, Any],
    board_row: Mapping[str, Any],
    cutoff: datetime,
    snapshot_hash: str,
) -> tuple[dict[str, Any] | None, str | None]:
    symbol = _real_text(board_row.get("symbol"))
    currency = _real_text(board_row.get("instrument_currency"))
    price = _finite_number(board_row.get("current_price"))
    price_date = _date_text(board_row.get("latest_price_date"))
    freshness = _real_text(history_row.get("freshness_status"))
    if symbol is None or currency is None or price is None or price <= 0:
        return None, "price, symbol, or currency is missing"
    if price_date is None:
        return None, "price date is missing"
    if price_date > cutoff.date().isoformat():
        return None, "price date is later than as_of"
    if freshness is None or freshness.casefold() not in _ACCEPTED_FRESHNESS:
        return None, "price freshness is stale or unverifiable"
    material = {
        "instrument_id": str(history_row.get("instrument_id")),
        "symbol": symbol,
        "price": price,
        "currency": currency,
        "price_as_of": price_date,
        "source_snapshot_hash": snapshot_hash,
    }
    return {
        "symbol": symbol,
        "price": price,
        "currency": currency,
        "price_as_of": price_date,
        "source_snapshot_hash": snapshot_hash,
        "price_evidence_hash": _sha256_json(material),
    }, None


def _persist_unavailable(
    root: Path,
    cutoff: datetime,
    month: str,
    config: Mapping[str, Any],
    config_hash: str,
    reason: str,
) -> PaperBotRunResult:
    records: list[dict[str, Any]] = []
    try:
        with TransactionalStore(root) as store:
            for spec in config["bots"]:
                lineage = None
                bot_id = _bot_identity(spec, config_hash, lineage)
                record = _unavailable_record(spec, bot_id, config_hash, config, cutoff, month, reason)
                _append_unavailable(store, record)
                records.append(record)
    except (OSError, ValueError, StorageSchemaError, StorageRevisionConflict):
        return PaperBotRunResult("unavailable", _time_text(cutoff), None, (), reason)
    return PaperBotRunResult("unavailable", _time_text(cutoff), None, tuple(records), reason, len(records))


def _unavailable_record(
    spec: Mapping[str, Any],
    bot_id: str,
    config_hash: str,
    config: Mapping[str, Any],
    cutoff: datetime,
    month: str,
    reason: str,
    *,
    snapshot_hash: str | None = None,
    known_at: str | None = None,
    lineage_version: str | None = None,
) -> dict[str, Any]:
    record = {
        "schema_version": "paper_bot_decision.v1",
        "bot_id": bot_id,
        "bot_family": str(spec["family_id"]),
        "bot_name": str(spec["name"]),
        "strategy": str(spec["strategy"]),
        "status": "unavailable",
        "reason": reason,
        "spec_hash": _sha256_json({"config_hash": config_hash, "spec": dict(spec)}),
        "config_hash": config_hash,
        "score_lineage_version": lineage_version or "unavailable",
        "score_lineage_hash": None,
        "score_version": None,
        "source_snapshot_hash": snapshot_hash,
        "snapshot_hash": snapshot_hash,
        "known_at": known_at,
        "as_of": _time_text(cutoff),
        "decision_month": month,
        "initial_virtual_cash_eur": float(config["initial_virtual_cash_eur"]),
        "monthly_contribution_eur": float(config["monthly_contribution_eur"]),
        "currency": "EUR",
        "targets": {},
        "prices_used": {},
        "skipped_instruments": [],
        "authority_stage": "paper",
        "strategy_authority": "strategy:paper_portfolio",
        "execution_allowed": False,
    }
    record["decision_id"] = _unavailable_id(bot_id, _time_text(cutoff), snapshot_hash, reason)
    return record


def _append_unavailable(store: TransactionalStore, record: Mapping[str, Any]) -> None:
    store.put_many(
        [(DECISION_ENTITY_TYPE, str(record["decision_id"]), record)],
        immutable=True,
    )


def _baseline_id(config_hash: str, score_version: str) -> str:
    return _sha256_json({"config_hash": config_hash, "baseline_score_version": score_version})


def _bot_identity(spec: Mapping[str, Any], config_hash: str, lineage_hash: str | None) -> str:
    identity = _sha256_json(
        {
            "config_hash": config_hash,
            "spec": dict(spec),
            "lineage_hash": lineage_hash,
        }
    )
    return f"{spec['family_id']}-{identity}"


def _month_slot_id(bot_id: str, month: str) -> str:
    return _sha256_json({"bot_id": bot_id, "decision_month": month})


def _decision_id(bot_id: str, month: str, snapshot_hash: str) -> str:
    return _sha256_json({"bot_id": bot_id, "decision_month": month, "snapshot_hash": snapshot_hash})


def _unavailable_id(bot_id: str, as_of: str, snapshot_hash: str | None, reason: str) -> str:
    return _sha256_json(
        {"bot_id": bot_id, "as_of": as_of, "snapshot_hash": snapshot_hash, "reason": reason}
    )


def _as_of_timestamp(value: datetime | date | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.max, tzinfo=timezone.utc)
    else:
        raw = str(value).strip()
        if not raw:
            raise ValueError("as_of is empty")
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            parsed = datetime.combine(parsed_date, time.max, tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _real_text(value)
        if text is None:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = pd.Timestamp(text).to_pydatetime()
            except (TypeError, ValueError, OverflowError):
                return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _date_text(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _real_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        parsed = _parse_timestamp(text)
        return parsed.date().isoformat() if parsed is not None else None


def _real_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return None if text.casefold() in _UNAVAILABLE_TEXT else text


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _strict_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) or value is None:
        return None
    number = _finite_number(value)
    if number in (0.0, 1.0):
        return bool(number)
    return None


def _positive_int(value: object) -> int | None:
    number = _finite_number(value)
    if number is None or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _same_value(left: object, right: object) -> bool:
    if left is None or right is None:
        return _real_text(left) is None and _real_text(right) is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, (bool, int)) and isinstance(right, (bool, int)) and bool(left) == bool(right)
    left_number = _finite_number(left)
    right_number = _finite_number(right)
    if left_number is not None and right_number is not None:
        return math.isclose(left_number, right_number, rel_tol=0.0, abs_tol=1e-10)
    return _real_text(left) == _real_text(right)


def _is_sha256(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(character in "0123456789abcdef" for character in value.casefold())


def _sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["PaperBotRunResult", "run_paper_bots"]
