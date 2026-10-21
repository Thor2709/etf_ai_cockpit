"""Historical score backfill: the canonical score recomputed as of past sessions, point-in-time (application; ADR-0002).

For each historical session the real score engine runs on the data known at that session (prices up to the session,
FX known by its close, stock fundamentals through their own known-at gate). The score is written to the separate backfill
store (``data/derived/score_history_backfill.parquet``), never to the live published history, with full snapshot lineage and
a ``historical_backfill`` provenance label. Any term that has no point-in-time source is unavailable with its reason (the
engine's own fail-closed behaviour), never zero-filled, reweighted or read as of today.

Withheld on purpose (no known-at in the stores): forecasts and their calibration, the stored backtest trust, the cash-curve
comparison, ETF holdings, PRIIPS KIDs, configured ETF product-quality metadata, stored news counts and the trade-candidate
report. The universe is today's configured list: delisted names are absent (survivorship bias, reported with the results).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.application.reference_context import (
    _benchmark_reference_snapshot_inputs,
    _reference_context_from_inputs,
)
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.versioning import build_version_registry
from etf_cockpit.data.duckdb_store import load_prices
from etf_cockpit.data.fx_data import fx_rates_for_prices
from etf_cockpit.data.score_history_backfill import (
    BACKFILL_PROVENANCE,
    load_backfill_eligibility,
    load_backfill_score_history,
    write_backfill_store,
)
from etf_cockpit.data.trust_artifacts import build_score_history_frame
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.features.crowding import build_correlation_clusters
from etf_cockpit.features.feature_pipeline import eur_basis_prices, latest_features
from etf_cockpit.features.regime import build_benchmark_attribution_lookup, build_market_regime, build_portfolio_fit_lookup
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.signals.signal_pipeline import generate_signals
from etf_cockpit.signals.simple_scores import (
    AsOfScoreSources,
    SimpleInstrumentScore,
    build_universe_simple_scores,
    rank_and_finalize_scores,
    simple_scoreboard_frame,
)

PIT_POLICY_VERSION = "pit_score_backfill.v1"
CALENDAR_INSTRUMENT_ID = "VWCE"  # the benchmark calendar defines the sessions (as in the paper bots)
DEFAULT_EVERY_SESSIONS = 5  # weekly
CHECKPOINT_RUNS = 20  # persist the store after this many newly scored sessions
MIN_HISTORY_ROWS = 252  # eligibility: at least this many price rows before the date (the engine's own history gate)
MAX_STALE_BUSINESS_DAYS = 5  # eligibility: a price within the last 5 trading days (the engine's staleness gate, tightened)
# Replay-universe liquidity gate for stocks and equity certificates (not ETFs: single-venue ETF volume understates their liquidity).
# The score engine has a liquidity score ladder but no hard gate, so this is the only gate; thresholds are the owner-set defaults.
LIQUIDITY_WINDOW_SESSIONS = 63
LIQUIDITY_MIN_MEDIAN_VALUE_EUR = 20_000.0
LIQUIDITY_MAX_ZERO_VOLUME_SHARE = 0.30
LIQUIDITY_GATED_TYPES = frozenset({"stock", "equity_certificate"})
WITHHELD_SOURCES = (
    "forecasts_and_calibration",
    "stored_backtest_trust",
    "cash_curve_comparison",
    "etf_holdings_exposure",
    "priips_kid_records",
    "etf_product_quality_metadata",
    "stored_news_inventory",
    "trade_candidate_report",
    "etf_structure_confidence_caps",
)
SURVIVORSHIP_CAVEAT = (
    "SURVIVORSHIP: the universe is today's configured list; instruments delisted or removed during the period are absent, "
    "so historical results are biased upward."
)
_BASE_HISTORY_EXTRA = (
    "analysis_status",
    "research_promotion_allowed",
    "legacy_action",
    "gate_policy_version",
    "gate_policy_checksum",
)


@dataclass
class BackfillResult:
    status: str
    path: Path | None
    sessions_requested: int = 0
    runs_written: int = 0
    runs_kept: int = 0
    unavailable_dates: dict[str, str] = field(default_factory=dict)
    eligibility: pd.DataFrame = field(default_factory=pd.DataFrame)
    reason: str | None = None


def session_dates(prices: pd.DataFrame, start: date, end: date, *, every: int = DEFAULT_EVERY_SESSIONS, calendar_id: str = CALENDAR_INSTRUMENT_ID) -> list[date]:
    """Every ``every``-th benchmark-calendar session in ``[start, end]`` (the first session on or after ``start`` is the first)."""

    if every < 1:
        raise ValueError("every must be at least 1 session")
    if prices.empty or not {"etf_id", "date"}.issubset(prices.columns):
        return []
    dates = sorted({value for value in _as_dates(prices.loc[prices["etf_id"].astype(str).eq(calendar_id), "date"]) if start <= value <= end})
    return dates[::every]


def backfill_score_history(
    root: Path,
    start: date,
    end: date,
    *,
    every: int = DEFAULT_EVERY_SESSIONS,
    config: AppConfig | None = None,
    prices: pd.DataFrame | None = None,
    fx_rates: pd.DataFrame | None = None,
    force: bool = False,
    excluded: Mapping[str, str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> BackfillResult:
    """Compute and store the canonical score for each selected historical session; resumable (stored runs are kept).

    ``excluded`` maps instrument ids to the reason they are removed from the replay universe (identity or data defects): they
    are dropped before scoring, logged as ineligible with that reason and influence no peer, correlation or rank.
    FX follows the canonical availability rule only (rows carry ``available_at``; ``EurRateBook`` and the FX snapshot gate on it).
    """

    root = Path(root)
    say = progress or (lambda _message: None)
    config = config or load_config()
    frame = load_prices(config=config) if prices is None else prices.copy()
    if frame.empty or not {"etf_id", "date", "adjusted_close"}.issubset(frame.columns):
        return BackfillResult("unavailable", None, reason="No stored price history to score.")
    frame["date"] = _as_dates(frame["date"])
    frame = frame[frame["etf_id"].astype(str).isin(set(config.universe.enabled_ids))].copy()
    sessions = session_dates(frame, start, end, every=every)
    if not sessions:
        return BackfillResult("unavailable", None, reason=f"No {CALENDAR_INSTRUMENT_ID} session between {start} and {end}.")
    fx = fx_rates if fx_rates is not None else _load_fx(frame)
    registry_signature = str(build_version_registry().get("registry_signature", "unavailable"))

    existing = load_backfill_score_history(root)
    existing_eligibility = load_backfill_eligibility(root)
    done = set() if existing.empty or force else set(existing["as_of_date"].astype(str))
    new_histories: list[pd.DataFrame] = []
    new_eligibility: list[pd.DataFrame] = []
    unavailable: dict[str, str] = {}

    def persist() -> BackfillResult:
        replaced = {session.isoformat() for session in sessions} if force else {
            str(value) for part in new_histories for value in part["as_of_date"].unique()
        } | set(unavailable)
        kept = existing.loc[~existing["as_of_date"].astype(str).isin(replaced)] if not existing.empty else existing
        history = _concat([kept, *new_histories])
        kept_eligibility = (
            existing_eligibility.loc[~existing_eligibility["as_of_date"].astype(str).isin(replaced)]
            if not existing_eligibility.empty
            else existing_eligibility
        )
        eligibility_log = _concat([kept_eligibility, *new_eligibility])
        if history.empty:
            return BackfillResult("unavailable", None, len(sessions), unavailable_dates=unavailable, eligibility=eligibility_log, reason="No session could be scored.")
        history = history.sort_values(["as_of_date", "rank", "instrument_id"], kind="stable").reset_index(drop=True)
        manifest = {
            "schema_version": "score_history_backfill.v1",
            "provenance": BACKFILL_PROVENANCE,
            "pit_policy_version": PIT_POLICY_VERSION,
            "withheld_sources": list(WITHHELD_SOURCES),
            "survivorship_caveat": SURVIVORSHIP_CAVEAT,
            "calendar_instrument_id": CALENDAR_INSTRUMENT_ID,
            "every_sessions": every,
            "min_history_rows": MIN_HISTORY_ROWS,
                "excluded_instruments": dict(excluded or {}),
            "liquidity_gate": {
                "types": sorted(LIQUIDITY_GATED_TYPES), "window_sessions": LIQUIDITY_WINDOW_SESSIONS,
                "min_median_traded_value_eur": LIQUIDITY_MIN_MEDIAN_VALUE_EUR, "max_zero_volume_share": LIQUIDITY_MAX_ZERO_VOLUME_SHARE,
            },
            "max_stale_business_days": MAX_STALE_BUSINESS_DAYS,
            "runs": int(history["run_id"].nunique()),
            "first_as_of": str(history["as_of_date"].min()),
            "last_as_of": str(history["as_of_date"].max()),
            "unavailable_dates": unavailable,
            "execution_allowed": False,
        }
        path = write_backfill_store(root, history, eligibility_log, manifest)
        return BackfillResult(
            "available", path, len(sessions), runs_written=len(new_histories),
            runs_kept=int(kept["run_id"].nunique()) if not kept.empty else 0,
            unavailable_dates=unavailable, eligibility=eligibility_log,
        )

    for index, session in enumerate(sessions, start=1):
        if session.isoformat() in done:
            continue
        say(f"[{index}/{len(sessions)}] scoring as of {session}")
        try:
            run, eligibility = score_as_of(
                config, frame, session, fx_rates=fx, version_registry_signature=registry_signature, excluded=excluded
            )
        except Exception as exc:  # fail closed per session: one broken date never writes a partial or guessed run
            unavailable[session.isoformat()] = f"{type(exc).__name__}: {str(exc)[:200]}"
            say(f"  unavailable: {unavailable[session.isoformat()]}")
            continue
        new_eligibility.append(eligibility)
        if run is None:
            unavailable[session.isoformat()] = "no eligible scored instrument"
            continue
        new_histories.append(run)
        if len(new_histories) % CHECKPOINT_RUNS == 0:
            persist()  # a long backfill survives an interruption: stored runs are resumable

    return persist()


def score_as_of(
    config: AppConfig,
    prices: pd.DataFrame,
    as_of: date,
    *,
    fx_rates: pd.DataFrame | None = None,
    version_registry_signature: str = "unavailable",
    excluded: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame | None, pd.DataFrame]:
    """The canonical score history run for one session plus its eligibility log; only data known at ``as_of`` is read."""

    excluded = dict(excluded or {})
    known = prices.loc[(_as_dates(prices["date"]) <= as_of) & ~prices["etf_id"].astype(str).isin(excluded)].copy()
    known["date"] = _as_dates(known["date"])
    decision_time = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, tzinfo=timezone.utc)
    created_at = decision_time.isoformat()
    inputs_hash = _inputs_hash(config, known, fx_rates, as_of)
    run_id = f"backfill_{as_of:%Y%m%d}_{inputs_hash[:8]}"

    reference_inputs = _benchmark_reference_snapshot_inputs(config, as_of, None)
    context = _reference_context_from_inputs(reference_inputs, purpose="comparison", analysis_id=f"backfill:{as_of.isoformat()}")
    features = FeatureService(config, reference_context=context, fx_rates=fx_rates if fx_rates is not None else pd.DataFrame()).compute_features(
        as_of, known, publish=False
    )
    latest = latest_features(features, as_of)
    report = validate_prices(known, as_of_date=as_of, min_history_days=MIN_HISTORY_ROWS, block_stale_business_days=MAX_STALE_BUSINESS_DAYS)
    signals = (
        []
        if latest.empty
        else generate_signals(
            config,
            latest,
            _flat_holdings(config, as_of),
            report,
            as_of_date=as_of,
            run_id=run_id,
            decision_timestamp=pd.Timestamp(decision_time),
            publish=False,
        )
    )
    metadata: dict[str, object] = {
        item.id: {"sector": item.sector, "theme": item.theme} for item in config.universe.etfs if item.id in config.universe.enabled_ids
    }
    benchmark_args = dict(
        benchmark_id=context.benchmark_data_id,
        benchmark_reference=context.projection,
        benchmark_registry=context.registry,
        peer_member_ids=context.peer_member_ids,
    )
    scores = build_universe_simple_scores(
        config,
        signals,
        pd.DataFrame(),
        known,
        as_of_sources=AsOfScoreSources(decision_time=decision_time),
        fx_rates=fx_rates if fx_rates is not None else pd.DataFrame(),
        calibration_by_id={},
        regime=build_market_regime(known, pd.DataFrame(), **benchmark_args),
        portfolio_fit=build_portfolio_fit_lookup(known, **benchmark_args),
        benchmark_attribution=build_benchmark_attribution_lookup(known, metadata=metadata, **benchmark_args),
        cash_comparison_lookup={},
        crowding=build_correlation_clusters(known, metadata, as_of=as_of),
        backtest_trust={},
    )
    no_lineage = {score.display_id for score in scores if score.canonical_score is None}
    eligibility = _eligibility_log(config, as_of, known, report, features, scores, excluded, fx_rates, no_lineage)
    eligible_ids = set(eligibility.loc[eligibility["eligible"], "instrument_id"])
    ranked = rank_and_finalize_scores([score for score in scores if score.display_id in eligible_ids], known, metadata, news_inventory={})
    if not ranked:
        return None, eligibility
    return _history_run(ranked, run_id, created_at, as_of, inputs_hash, eligibility, version_registry_signature), eligibility


def _eligibility_log(
    config: AppConfig,
    as_of: date,
    known: pd.DataFrame,
    report: DataQualityReport,
    features: pd.DataFrame,
    scores: Sequence[SimpleInstrumentScore],
    excluded: Mapping[str, str],
    fx_rates: pd.DataFrame | None,
    no_lineage: set[str],
) -> pd.DataFrame:
    """Per configured instrument at ``as_of``: eligible or the reason not.

    The engine's data-quality gate (history, staleness, price integrity), the FX path to EUR, a produced score, the explicit
    replay exclusions, a canonical v3 score with formula lineage (a run with a lineage-less row cannot be replayed)
    and, for stocks and equity certificates, the trailing liquidity gate.
    """

    blocking: dict[str, list[str]] = {}
    for issue in report.issues:
        if getattr(issue, "severity", "") == "block":
            blocking.setdefault(str(issue.etf_id), []).append(str(issue.code))
    fx_unavailable = dict(features.attrs.get("fx_unavailable", {}) or {})
    rows_by_id = known.groupby(known["etf_id"].astype(str)).size().to_dict() if not known.empty else {}
    score_by_id = {score.display_id: score for score in scores}
    identities = config.universe.by_id()
    liquidity = _liquidity_gate(config, known, fx_rates, as_of)
    rows: list[dict[str, object]] = []
    for instrument_id in config.universe.enabled_ids:
        identity = identities.get(instrument_id)
        score = score_by_id.get(instrument_id)
        asset_type = score.asset_type if score is not None else str(getattr(identity, "instrument_type", "") or "")
        reasons: list[str] = []
        if instrument_id in excluded:
            reasons.append(f"excluded: {excluded[instrument_id]}")
        elif not rows_by_id.get(instrument_id):
            reasons.append("no_price_history_yet")  # unknown pre-listing = absent
        else:
            reasons.extend(f"data_quality:{code}" for code in sorted(set(blocking.get(instrument_id, []))))
            if instrument_id in fx_unavailable:
                reasons.append(f"fx_unavailable: {str(fx_unavailable[instrument_id])[:120]}")
            if score is None:
                reasons.append("no_score_produced")
            elif score.final_score_10 is None:
                reasons.append(f"score_unavailable: {str(score.one_line_reason)[:120]}")
            if instrument_id in no_lineage and score is not None and score.final_score_10 is not None:
                reasons.append("no_canonical_score: no v3 snapshot lineage (native Sparebank scorecard pending); not replayable")
            if instrument_id in liquidity:
                reasons.append(liquidity[instrument_id])
        rows.append(
            {
                "as_of_date": as_of.isoformat(),
                "instrument_id": instrument_id,
                "asset_type": asset_type,
                "price_rows": int(rows_by_id.get(instrument_id, 0)),
                "eligible": not reasons,
                "reasons": "; ".join(reasons),
            }
        )
    return pd.DataFrame(rows)


def _liquidity_gate(config: AppConfig, known: pd.DataFrame, fx_rates: pd.DataFrame | None, as_of: date) -> dict[str, str]:
    """Instruments of the gated types that fail the trailing liquidity gate at ``as_of`` (id -> reason).

    Median traded value (raw close x volume, converted with the same point-in-time EUR rate as the score features) over the
    last 63 sessions known at ``as_of`` must be at least EUR 20,000 and at most 30% of those sessions may have zero volume.
    A window that cannot be converted to EUR fails the gate (never assumed liquid).
    """

    gated = {item.id for item in config.universe.etfs if item.instrument_type in LIQUIDITY_GATED_TYPES and item.id in config.universe.enabled_ids}
    window = known.loc[known["etf_id"].astype(str).isin(gated)]
    if window.empty:
        return {}
    window = window.sort_values(["etf_id", "date"], kind="stable").groupby("etf_id", sort=False).tail(LIQUIDITY_WINDOW_SESSIONS)
    eur = eur_basis_prices(
        window, fx_rates, configured_currency={item.id: str(item.currency or "EUR") for item in config.universe.etfs},
        known_by=datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, tzinfo=timezone.utc),
    ).frame
    local = pd.to_numeric(eur["adjusted_close_local"], errors="coerce")
    rate = pd.to_numeric(eur["adjusted_close"], errors="coerce") / local
    volume = pd.to_numeric(eur["volume"], errors="coerce")
    value = pd.to_numeric(eur["close"], errors="coerce") * volume * rate
    failures: dict[str, str] = {}
    for instrument_id, index in eur.groupby(eur["etf_id"].astype(str)).groups.items():
        if len(index) < LIQUIDITY_WINDOW_SESSIONS:
            continue  # too short a history is reported by the engine's history gate
        zero_share = float((volume.loc[index].fillna(0.0) <= 0).mean())
        usable = value.loc[index].dropna()
        if len(usable) < len(index):
            failures[instrument_id] = f"liquidity_gate_unavailable: {len(index) - len(usable)} of {len(index)} sessions cannot be valued in EUR"
        elif float(usable.median()) < LIQUIDITY_MIN_MEDIAN_VALUE_EUR:
            failures[instrument_id] = (
                f"liquidity_gate: median traded value EUR {float(usable.median()):,.0f} over {LIQUIDITY_WINDOW_SESSIONS} sessions "
                f"< EUR {LIQUIDITY_MIN_MEDIAN_VALUE_EUR:,.0f}"
            )
        elif zero_share > LIQUIDITY_MAX_ZERO_VOLUME_SHARE:
            failures[instrument_id] = f"liquidity_gate: zero-volume sessions {zero_share:.0%} > {LIQUIDITY_MAX_ZERO_VOLUME_SHARE:.0%}"
    return failures


def _history_run(
    ranked: Sequence[SimpleInstrumentScore],
    run_id: str,
    created_at: str,
    as_of: date,
    inputs_hash: str,
    eligibility: pd.DataFrame,
    version_registry_signature: str,
) -> pd.DataFrame:
    frame = build_score_history_frame(ranked, run_id=run_id, created_at=created_at, version_registry_signature=version_registry_signature)
    board = simple_scoreboard_frame(list(ranked)).set_index("instrument_id")
    for column in _BASE_HISTORY_EXTRA:
        frame[column] = frame["instrument_id"].map(board[column])
    frame["research_promotion_allowed"] = frame["research_promotion_allowed"].map(lambda value: value is True)
    unavailable_terms = {
        score.display_id: sorted(
            component.key for component in score.components if component.score_10 is None or str(component.status).casefold() != "ok"
        )
        for score in ranked
    }
    frame["provenance"] = BACKFILL_PROVENANCE
    frame["as_of_date"] = as_of.isoformat()
    frame["as_of_inputs_hash"] = inputs_hash
    frame["pit_policy_version"] = PIT_POLICY_VERSION
    frame["pit_terms_unavailable"] = frame["instrument_id"].map(lambda key: "|".join(unavailable_terms.get(key, [])))
    frame["pit_coverage"] = json.dumps(_pit_coverage(ranked, eligibility), sort_keys=True)
    frame["survivorship_caveat"] = SURVIVORSHIP_CAVEAT
    frame["snapshot_hash"] = ""
    frame["snapshot_hash"] = _content_hash(frame)
    return frame


def _pit_coverage(ranked: Sequence[SimpleInstrumentScore], eligibility: pd.DataFrame) -> dict[str, object]:
    """Which score terms were available or unavailable (with the commonest reasons) in this run, and what was withheld."""

    terms: dict[str, dict[str, Any]] = {}
    for score in ranked:
        for component in score.components:
            entry = terms.setdefault(component.key, {"available": 0, "unavailable": 0, "reasons": Counter()})
            if component.score_10 is not None and str(component.status).casefold() == "ok":
                entry["available"] += 1
            else:
                entry["unavailable"] += 1
                entry["reasons"][str(component.why or component.explanation)[:140]] += 1
    summary = {
        key: {"available": value["available"], "unavailable": value["unavailable"], "reasons": dict(value["reasons"].most_common(3))}
        for key, value in sorted(terms.items())
    }
    return {
        "policy": PIT_POLICY_VERSION,
        "scored_instruments": len(ranked),
        "eligible_instruments": int(eligibility["eligible"].sum()) if not eligibility.empty else 0,
        "configured_instruments": int(len(eligibility)),
        "withheld_sources": list(WITHHELD_SOURCES),
        "terms": summary,
    }


def _flat_holdings(config: AppConfig, as_of: date) -> pd.DataFrame:
    """No portfolio: the score never depends on today's holdings (not point-in-time)."""

    return pd.DataFrame(
        [
            {
                "as_of_date": as_of, "etf_id": etf_id, "units": 0.0, "market_price": 1.0, "market_value_eur": 0.0,
                "current_weight": 0.0, "average_cost_eur": 1.0, "unrealised_gain_eur": 0.0, "unrealised_gain_pct": 0.0,
                "source": "backfill",
            }
            for etf_id in config.universe.enabled_ids
        ]
    )


def _inputs_hash(config: AppConfig, known: pd.DataFrame, fx: pd.DataFrame | None, as_of: date) -> str:
    """Identity of the as-of inputs: the price rows known at the date, the FX rows dated by then, the universe and the date."""

    digest = hashlib.sha256()
    digest.update(as_of.isoformat().encode())
    digest.update(",".join(sorted(config.universe.enabled_ids)).encode())
    columns = [column for column in ("etf_id", "date", "close", "adjusted_close", "volume", "currency") if column in known.columns]
    if not known.empty:
        ordered = known[columns].astype({"date": str}).sort_values(["etf_id", "date"], kind="stable")
        digest.update(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes())
    if fx is not None and not fx.empty:
        fx_known = fx
        if "available_at" in fx.columns:
            fx_known = fx.loc[pd.to_datetime(fx["available_at"], errors="coerce", utc=True) < pd.Timestamp(as_of + timedelta(days=1), tz="UTC")]
        elif "as_of_date" in fx.columns:
            fx_known = fx.loc[pd.to_datetime(fx["as_of_date"], errors="coerce").dt.date <= as_of]
        digest.update(pd.util.hash_pandas_object(fx_known.astype(str), index=False).to_numpy().tobytes())
    return digest.hexdigest()


def _content_hash(frame: pd.DataFrame) -> str:
    canonical = frame.drop(columns=["snapshot_hash"], errors="ignore").sort_values("instrument_id", kind="stable")
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    return hashlib.sha256(canonical.to_json(orient="records", date_format="iso", default_handler=str).encode("utf-8")).hexdigest()


def _as_dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def _concat(parts: Sequence[pd.DataFrame]) -> pd.DataFrame:
    usable = [part for part in parts if part is not None and not part.empty]
    return pd.concat(usable, ignore_index=True, sort=False) if usable else pd.DataFrame()


def _load_fx(prices: pd.DataFrame) -> pd.DataFrame:
    try:
        return fx_rates_for_prices(prices)
    except Exception:
        return pd.DataFrame()


def eligible_counts_by_year(eligibility: pd.DataFrame) -> pd.DataFrame:
    """Eligible instruments per year (the last session of each year) by asset type, from the eligibility log."""

    if eligibility.empty:
        return pd.DataFrame()
    frame = eligibility.copy()
    frame["year"] = frame["as_of_date"].astype(str).str[:4]
    last = frame.groupby("year")["as_of_date"].transform("max")
    final = frame.loc[frame["as_of_date"].eq(last) & frame["eligible"]]
    return final.groupby(["year", "asset_type"]).size().unstack(fill_value=0)


FUNDAMENTAL_TERMS = ("stock_value", "stock_quality", "analyst_revision", "etf_exposure", "etf_product_quality")
SMOKE_TEST_LABEL = "SMOKE TEST - price/partial data, not an assessment"


def term_coverage_by_year(history: pd.DataFrame) -> pd.DataFrame:
    """Share of scored instruments with each score term available, averaged over the runs of each year."""

    if history.empty or "pit_coverage" not in history.columns:
        return pd.DataFrame()
    rows = []
    for run_id, group in history.groupby("run_id", sort=False):
        coverage = json.loads(str(group["pit_coverage"].iloc[0]))
        for term, entry in coverage.get("terms", {}).items():
            total = entry["available"] + entry["unavailable"]
            if total:
                rows.append({"year": str(group["as_of_date"].iloc[0])[:4], "term": term, "share": entry["available"] / total})
    return pd.DataFrame(rows).groupby(["year", "term"])["share"].mean().unstack("year").round(3) if rows else pd.DataFrame()


def run_label(history: pd.DataFrame) -> str:
    """"SMOKE TEST" unless every fundamentals/holdings term had point-in-time data somewhere in the store."""

    coverage = term_coverage_by_year(history)
    missing = [term for term in FUNDAMENTAL_TERMS if term not in coverage.index or float(coverage.loc[term].max()) <= 0.0]
    if missing:
        return f"{SMOKE_TEST_LABEL} (no point-in-time data for: {', '.join(missing)})"
    return "full pipeline (point-in-time fundamentals and holdings present)"


def never_eligible(eligibility: pd.DataFrame) -> pd.DataFrame:
    """Instruments never eligible at any scored session, with their commonest reason."""

    if eligibility.empty:
        return pd.DataFrame(columns=["instrument_id", "reason"])
    rows = []
    for instrument_id, group in eligibility.groupby("instrument_id"):
        if group["eligible"].any():
            continue
        reason = Counter(group["reasons"]).most_common(1)[0][0]
        rows.append({"instrument_id": instrument_id, "asset_type": group["asset_type"].iloc[0], "reason": reason})
    return pd.DataFrame(rows)


__all__ = [
    "BackfillResult",
    "DEFAULT_EVERY_SESSIONS",
    "LIQUIDITY_MIN_MEDIAN_VALUE_EUR",
    "PIT_POLICY_VERSION",
    "SMOKE_TEST_LABEL",
    "SURVIVORSHIP_CAVEAT",
    "backfill_score_history",
    "eligible_counts_by_year",
    "never_eligible",
    "run_label",
    "score_as_of",
    "session_dates",
    "term_coverage_by_year",
]
