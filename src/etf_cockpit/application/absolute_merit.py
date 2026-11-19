"""Absolute-merit evidence for the decision shadow (INT-09).

Builds the source records that ``analysis/decision/opportunity.py`` checks. A block that cannot be
established is unavailable or absent, so the consumer fails closed; nothing here grants execution.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import dataclasses
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.analysis.decision.opportunity import _opportunity_benchmark_anchor, load_opportunity_policy
from etf_cockpit.analysis.decision.shadow_run import _config_hashes, _decision_timestamp
from etf_cockpit.application.portfolio_sandbox import _temporal_claims
from etf_cockpit.core.config import AppConfig
from etf_cockpit.models.calibration import calibrate_forecast_distribution, log_to_simple_return, realised_horizon_return
from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.data.provenance import metadata_from_frame
from etf_cockpit.portfolio.benchmark_reference import (
    VWCE_BENCHMARK_ID, validate_vwce_reference_series, vwce_series_source_hash,
)
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkDefinition, BenchmarkReferenceError, CanonicalBenchmarkRegistry,
    load_canonical_benchmark_registry, local_benchmark_registry_path,
)
from etf_cockpit.portfolio.costs import estimated_cost_bps

HORIZON = "60_sessions"  # the stored forecasts are at PRIMARY_MODEL_HORIZON_DAYS
HORIZON_DAYS = 60
ORDER_VALUE_EUR = 10_000.0  # the cost/capacity preview order size


def build_absolute_merit(
    distributions: Mapping[str, Mapping[str, object]],
    history: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    config: AppConfig,
    decision_time: date,
    prior: Mapping[str, object] | None = None,
    positions: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, dict[str, object]]:
    """Return ``{instrument: {"absolute_merit_evidence": ..., "forecast_calibrated": bool}}``.

    ``distributions`` are the 60-session ``forecast_return_distributions``; each is calibrated here
    point-in-time on ``history`` and ``prices``. The expected return is the calibrated q50 as a simple
    return (D2); the VWCE expected return comes from the same calibrated distribution (D20).
    """

    policy = load_opportunity_policy()
    decision = _decision_timestamp(decision_time)  # the consumer's cut-off
    stamp = _iso(decision)
    calibrated = {
        name: calibrate_forecast_distribution(
            history, prices, distribution, instrument_id=name, decision_time=decision, settings=config.models.calibration
        )
        for name, distribution in distributions.items()
    }
    by_id = config.universe.by_id()
    margins: dict[frozenset[str], float | None] = {}
    forecasts: dict[str, tuple[dict[str, object], bool]] = {}
    for name, distribution in calibrated.items():
        models = frozenset(str(entry.get("model_id")) for entry in _members(distribution))
        if models not in margins:
            margins[models] = _uncertainty_margin(
                history, prices, models, decision, policy.uncertainty_margin_quantile,
                config.models.calibration.minimum_matured_samples,
            )
        forecasts[name] = _forecast(distribution, margins[models], by_id[name].currency if name in by_id else None)

    benchmark = None
    anchor = _opportunity_benchmark_anchor(policy, decision=decision)
    vwce = forecasts.get(policy.benchmark_instrument_id)
    if anchor is not None and vwce is not None and vwce[1] and vwce[0]["status"] == "available":
        series_hash = vwce_anchor_series_hash(prices, anchor)
        if series_hash in anchor.source_hashes:
            benchmark = _record({
                "status": "available", "instrument_id": policy.benchmark_instrument_id,
                "benchmark_id": anchor.benchmark_id, "benchmark_version": anchor.version,
                "benchmark_digest": anchor.digest(), "total_return": vwce[0]["expected_total_return"],
                "unit": "decimal_fraction", "horizon": HORIZON, "currency": policy.base_currency,
            }, str(vwce[0]["effective_at"]), source_hash=series_hash)

    benchmark_cost = estimated_cost_bps(config, policy.benchmark_instrument_id, ORDER_VALUE_EUR) / 1e4
    output: dict[str, dict[str, object]] = {}
    for name, (forecast, forecast_calibrated) in forecasts.items():
        candidate_cost = estimated_cost_bps(config, name, ORDER_VALUE_EUR) / 1e4 if name in by_id else None
        costs_valid = candidate_cost is not None and all(0.0 <= value < 1.0 for value in (candidate_cost, benchmark_cost))
        evidence: dict[str, object] = {
            "forecast": forecast,
            "cost_model": _record({
                "status": "available" if costs_valid else "unavailable",
                "candidate_acquisition_cost": candidate_cost, "benchmark_acquisition_cost": benchmark_cost,
                "order_value_eur": ORDER_VALUE_EUR, "unit": "decimal_fraction",
                "currency": policy.base_currency, "horizon": HORIZON,
            }, stamp),
        }
        if benchmark is not None:
            evidence["benchmark_reference"] = benchmark
        previous = _previous_decision(prior, name, decision, policy.maximum_evidence_age_days)
        if previous is not None:
            evidence["previous_decision"] = {**previous, "config_hash": policy.checksum}
        if positions is not None and name in positions:
            evidence["position"] = positions[name]
        output[name] = {"absolute_merit_evidence": evidence, "forecast_calibrated": forecast_calibrated}
    return output


def vwce_anchor_series_hash(prices: pd.DataFrame, anchor: BenchmarkDefinition) -> str | None:
    """Hash the VWCE (date, close, adjusted close) rows dated before the anchor was known.

    Those rows are the snapshot the anchor records, so the hash stays stable while new prices arrive."""

    if not {"etf_id", "date", "close", "adjusted_close"}.issubset(prices.columns):
        return None
    known = pd.Timestamp(anchor.known_at).tz_convert("UTC").tz_localize(None).normalize()
    frame = prices.loc[prices["etf_id"].astype(str).eq("VWCE"), ["date", "close", "adjusted_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.loc[frame["date"].lt(known)].sort_values("date", kind="stable")
    if frame.empty:
        return None
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    return vwce_series_source_hash(frame.reset_index(drop=True))


def import_vwce_anchor(prices: pd.DataFrame, *, known_at: datetime | None = None, path: Path | None = None) -> Path:
    """Write a registry whose VWCE anchor is source-backed by the local price rows dated before ``known_at``.

    ``known_at`` is the import instant. The series must pass the VWCE reference contract, else nothing is written."""

    known = (known_at or datetime.now(timezone.utc))
    if known.tzinfo is None:
        raise BenchmarkReferenceError("known_at must be timezone-aware")
    known = known.astimezone(timezone.utc)
    packaged = load_canonical_benchmark_registry(packaged_only=True)
    base = next(item for item in packaged.benchmarks if item.benchmark_id == VWCE_BENCHMARK_ID)
    stamp = known.isoformat()
    probe = dataclasses.replace(base, known_at=stamp, effective_at=stamp, content_hash="")
    series_hash = vwce_anchor_series_hash(prices, probe)
    if series_hash is None:
        raise BenchmarkReferenceError("VWCE price series unavailable before known_at")
    frame = prices.loc[prices["etf_id"].astype(str).eq("VWCE")]
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any():
        raise BenchmarkReferenceError("VWCE series failed the reference contract: invalid_dates")
    frame = frame.loc[dates.lt(pd.Timestamp(known.date()))].reset_index(drop=True)
    metadata = dataclasses.replace(
        metadata_from_frame(frame, source_name="yfinance", source_type="prices", as_of_date=None, currency="EUR"),
        ingested_at=known,
    )
    check = validate_vwce_reference_series(frame, known_at=stamp, provider_metadata=metadata)
    if check.status != "available":
        raise BenchmarkReferenceError("VWCE series failed the reference contract: " + ",".join(check.reasons))
    anchor = dataclasses.replace(
        probe, status="available", opportunity_anchor=True, source_hashes=(series_hash,), version="1.1.0",
        methodology="Source-backed: yfinance VWCE.DE adjusted close (ISIN IE00BK5BQT80), EUR, rows before known_at.",
    )
    registry = CanonicalBenchmarkRegistry(
        benchmarks=tuple(anchor if item.benchmark_id == VWCE_BENCHMARK_ID else item for item in packaged.benchmarks),
        cash_proxies=packaged.cash_proxies, peer_sets=packaged.peer_sets,
        reference_portfolios=packaged.reference_portfolios, vwce_anchors=packaged.vwce_anchors,
    )
    destination = path or local_benchmark_registry_path()
    atomic_write_json(destination, registry.as_payload())
    return destination


def latest_prior_decision(directory: Path, decision_time: date) -> dict[str, object] | None:
    """The newest decision-shadow artefact for an earlier decision, written before this cut-off, with its file hash.

    The file time is its publication time, so a later replay never feeds an earlier decision."""

    cutoff = _decision_timestamp(decision_time)
    config_hash = _config_hashes()["decision_opportunity_v1"]
    for path in sorted(Path(directory).glob("decision_opportunity_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        before = path.stat().st_mtime
        content = path.read_bytes()
        if path.stat().st_mtime != before:
            continue
        published = datetime.fromtimestamp(before, tz=timezone.utc)
        if published > cutoff:
            continue
        try:
            payload = json.loads(content)
            made = datetime.fromisoformat(str(payload["decision_time"]).replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError):
            continue
        if made < cutoff:
            same_policy = isinstance(payload.get("config_hashes"), Mapping) and payload["config_hashes"].get("decision_opportunity_v1") == config_hash
            return {**payload, "source_hash": hashlib.sha256(content).hexdigest(), "same_policy": same_policy, "published_at": _iso(published)}
    return None


_KNOWLEDGE_COLUMNS = ("known_at", "imported_at", "available_at")


def positions_from_holdings(holdings: pd.DataFrame, instruments: Iterable[str], *, decision_time: date) -> dict[str, dict[str, object]]:
    """Held/not-held records from the newest holdings snapshot known at ``decision_time``.

    A snapshot counts only when it is dated by the decision and every one of its rows is known by the cut-off
    (``known_at``, ``imported_at``, ``available_at``, when present); otherwise there is no position evidence.
    The holdings carry no cost basis, so a held position stays fail-closed in the consumer."""

    if holdings.empty or holdings.attrs.get("status") == "unavailable":
        return {}
    cutoff = _decision_timestamp(decision_time)
    dated = pd.to_datetime(holdings["as_of_date"], errors="coerce", utc=True, format="mixed").dt.normalize()
    if dated.isna().any():  # an unparseable snapshot date is unknown evidence, never an absent row
        return {}
    claims = [pd.to_datetime(_temporal_claims(holdings[name]), errors="coerce", utc=True) for name in _KNOWLEDGE_COLUMNS if name in holdings]
    row_known = pd.concat(claims, axis=1).max(axis=1, skipna=False) if claims else None  # a malformed claim is NaT: unknown
    usable = dated.le(pd.Timestamp(cutoff.date(), tz="UTC"))
    if row_known is not None:
        usable &= row_known.le(cutoff)
    complete = usable.groupby(dated).all()
    if not complete.any():
        return {}
    as_of = complete[complete].index.max()
    latest = holdings.loc[dated.eq(as_of)]
    numbers = pd.to_numeric(latest["units"], errors="coerce")
    names = latest["etf_id"].astype(str)
    units = numbers.groupby(names).sum()
    invalid = set(names[~np.isfinite(numbers)]) | set(units.index[~np.isfinite(units)])
    stamp = _iso(as_of.to_pydatetime())
    known_stamp = _iso(row_known.loc[latest.index].max().to_pydatetime()) if row_known is not None else None  # real knowledge time
    return {
        name: _record({"status": "unavailable" if name in invalid else "available", "held": bool(units.get(name, 0.0) > 0.0),
                       "currency": "EUR", "friction_unit": "decimal_fraction"}, stamp, known_at=known_stamp)
        for name in instruments
    }


def _forecast(distribution: Mapping[str, object], margin: float | None, currency: str | None) -> tuple[dict[str, object], bool]:
    calibration = distribution.get("conformal_calibration")
    calibration_status = calibration.get("status") if isinstance(calibration, Mapping) else None
    calibrated = distribution.get("status") == "available" and calibration_status == "calibrated"
    expected = log_to_simple_return(distribution.get("q50_return"))
    dates = [pd.to_datetime(entry.get("forecast_date"), errors="coerce", utc=True) for entry in _members(distribution)]
    effective = None if not dates or any(pd.isna(item) for item in dates) else _iso(min(dates).to_pydatetime())
    available = calibrated and expected is not None and margin is not None and effective is not None and currency is not None
    return _record({
        "status": "available" if available else "unavailable", "calibration_status": calibration_status,
        "expected_total_return": expected, "method": "q50_log_to_simple", "uncertainty_margin": margin,
        "unit": "decimal_fraction", "horizon": HORIZON, "currency": currency,
    }, effective or ""), calibrated


def _uncertainty_margin(
    history: pd.DataFrame, prices: pd.DataFrame, models: frozenset[str], decision: datetime, quantile: float, minimum: int
) -> float | None:
    """Empirical quantile of |realised - expected| (simple returns) over matured out-of-fold forecasts
    of the same models at this horizon, pooled across instruments (D3 deferred)."""

    needed = {"etf_id", "model_id", "forecast_date", "horizon_days", "q50_return", "status", "model_allowed_in_score", "out_of_fold"}
    if history.empty or not needed.issubset(history.columns):
        return None
    rows = history.loc[
        history["model_id"].astype(str).isin(models)
        & pd.to_numeric(history["horizon_days"], errors="coerce").eq(HORIZON_DAYS)
        & history["status"].astype(str).str.lower().eq("ok")
        & history["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
        & history["out_of_fold"].astype(str).str.lower().isin({"true", "1", "yes"})
    ]
    known_columns = [column for column in ("created_at", "known_at") if column in rows]
    if not known_columns:
        return None
    for column in known_columns:  # known by the decision and by the end of the origin session (as calibration)
        known = pd.to_datetime(rows[column], errors="coerce", utc=True, format="mixed")
        origin_end = pd.to_datetime(rows["forecast_date"], errors="coerce", utc=True, format="mixed").dt.normalize() + pd.Timedelta(days=1)
        rows = rows.loc[known.le(decision) & known.lt(origin_end)]
    closes = prices.assign(date=pd.to_datetime(prices["date"], errors="coerce"))
    closes = closes.loc[closes["date"].lt(pd.Timestamp(decision.date()))]
    residuals = []
    for name, group in rows.groupby(rows["etf_id"].astype(str)):
        series = closes.loc[closes["etf_id"].astype(str).eq(name)].set_index("date")["adjusted_close"]
        for origin, predicted in zip(pd.to_datetime(group["forecast_date"], errors="coerce", format="mixed"), group["q50_return"]):
            actual = realised_horizon_return(series, origin.tz_localize(None) if origin.tzinfo else origin, HORIZON_DAYS)
            expected = log_to_simple_return(predicted)
            if actual is not None and expected is not None:
                residuals.append(abs(math.expm1(actual) - expected))
    return float(np.quantile(residuals, quantile)) if len(residuals) >= minimum else None


def _previous_decision(prior: Mapping[str, object] | None, name: str, decision: datetime, maximum_age_days: float) -> dict[str, object] | None:
    """The prior state for one instrument, only when the consumer can accept it (else it would void the decision)."""

    if not prior or prior.get("same_policy") is not True:
        return None
    made = datetime.fromisoformat(str(prior["decision_time"]).replace("Z", "+00:00"))
    if decision - made > timedelta(days=maximum_age_days):
        return None
    results = prior.get("results")
    for row in results if isinstance(results, list) else ():
        if isinstance(row, Mapping) and row.get("instrument") == name and row.get("absolute_horizon") == HORIZON:
            return {"status": "available", "state": row.get("decision_state"), "instrument_id": name, "horizon": HORIZON,
                    "effective_at": prior["decision_time"], "known_at": prior["published_at"],
                    "source_hash": prior["source_hash"], "execution_allowed": False}
    return None


def _members(distribution: Mapping[str, object]) -> list[Mapping[str, object]]:
    members = distribution.get("per_model_distributions")
    if isinstance(members, (list, tuple)) and members:
        return [item for item in members if isinstance(item, Mapping)]
    return [distribution]


def _record(block: Mapping[str, object], stamp: str, *, source_hash: str | None = None, known_at: str | None = None) -> dict[str, object]:
    record = {**block, "effective_at": stamp, "known_at": known_at or stamp, "execution_allowed": False}
    content = json.dumps(record, sort_keys=True, default=str).encode("utf-8")
    return {**record, "source_hash": source_hash or hashlib.sha256(content).hexdigest()}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
