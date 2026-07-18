"""Compose local snapshot evidence into non-authoritative screener rows."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from etf_cockpit.application.screening import ScreenQuery, records_checksum
from etf_cockpit.data.fundamentals import assess_fundamental_row, latest_fundamental_rows


_FACTOR_FIELDS = (
    "score",
    "expected_return",
    "confidence",
    "coverage",
    "risk_friction",
    "momentum",
    "trend",
    "volatility",
    "drawdown",
    "valuation",
    "profitability",
    "leverage",
    "growth",
    "shareholder_return",
    "quality",
    "liquidity",
    "portfolio_impact",
)


def build_screen_rows(snapshot: Any, fundamentals: pd.DataFrame) -> pd.DataFrame:
    """Join only evidence already present in the local application snapshot."""

    fundamentals = fundamentals.copy() if isinstance(fundamentals, pd.DataFrame) else pd.DataFrame()
    if "instrument_id" in fundamentals.columns:
        fundamentals = latest_fundamental_rows(fundamentals).set_index("instrument_id")
    else:
        fundamentals = pd.DataFrame()
    signals = {str(signal.etf_id): signal for signal in getattr(snapshot, "signals", ())}
    model_status = getattr(snapshot, "model_status", {}) or {}
    rows: list[dict[str, object]] = []
    for instrument in snapshot.config.universe.etfs:
        instrument_id = str(instrument.id)
        signal = signals.get(instrument_id)
        metrics = getattr(signal, "supporting_metrics", {}) if signal is not None else {}
        fundamental = fundamentals.loc[instrument_id] if instrument_id in fundamentals.index else pd.Series(dtype=object)
        fundamental_eligible = _fundamental_score_eligible(fundamental, assessment_date=_as_of_date(snapshot))
        blocked = tuple(getattr(signal, "blocked_by", ()) or ())
        warnings = tuple(getattr(signal, "warnings", ()) or ())
        as_of = fundamental.get("as_of_date", fundamental.get("as_of", _as_of(snapshot)))
        freshness, freshness_days = _freshness(as_of, _as_of(snapshot))
        rows.append(
            {
                "instrument_id": instrument_id,
                "name": instrument.name,
                "asset_type": instrument.instrument_type,
                "asset_class": instrument.asset_class,
                "region": instrument.region or "unavailable",
                "sector": instrument.sector or "unavailable",
                "theme": instrument.theme or "unavailable",
                "analysis_tier": instrument.analysis_tier,
                "eligibility": fundamental.get("eligibility", "unavailable"),
                "source": fundamental.get("source", fundamental.get("source_authority", "unavailable")),
                "as_of": as_of,
                "freshness": freshness,
                "freshness_days": freshness_days,
                "score": _metric(metrics, "canonical_attractiveness_10"),
                "expected_return": _metric(metrics, "canonical_expected_return_10"),
                "confidence": _metric(metrics, "canonical_evidence_confidence_10", getattr(signal, "confidence", None)),
                "coverage": _metric(metrics, "canonical_coverage"),
                "risk_friction": _metric(metrics, "canonical_risk_implementation_10"),
                "momentum": _metric(metrics, "momentum_60d"),
                "trend": _metric(metrics, "trend_200"),
                "volatility": _metric(metrics, "vol_60d_ann"),
                "drawdown": _metric(metrics, "drawdown_current"),
                "valuation": fundamental.get("valuation") if fundamental_eligible else None,
                "profitability": fundamental.get("profitability") if fundamental_eligible else None,
                "leverage": fundamental.get("leverage") if fundamental_eligible else None,
                "growth": fundamental.get("growth") if fundamental_eligible else None,
                "shareholder_return": fundamental.get("shareholder_return") if fundamental_eligible else None,
                "quality": _quality(fundamental) if fundamental_eligible else None,
                "liquidity": _metric(metrics, "capacity_eur"),
                "portfolio_impact": _metric(metrics, "drift_percent"),
                "model_availability": _model_availability(model_status),
                "news_conflict": "unavailable",
                "backtest_trust": _metric(metrics, "backtest_trust", "unavailable"),
                "sector_relative_status": fundamental.get("sector_relative_status", "unavailable"),
                "sector_relative_value": fundamental.get("sector_relative_value"),
                "blocked_by": "|".join(str(item) for item in blocked) or "none",
                "warnings": "|".join(str(item) for item in warnings) or fundamental.get("warnings", "none"),
                "formula_version": _metric(metrics, "formula_version", "unavailable"),
                "execution_allowed": False,
            }
        )
    frame = pd.DataFrame(rows)
    for field in _FACTOR_FIELDS:
        if field not in frame.columns:
            continue
        values = pd.to_numeric(frame[field], errors="coerce")
        frame[f"{field}_percentile"] = values.rank(method="average", pct=True) * 100
    return frame


def query_for_snapshot(snapshot: Any, frame: pd.DataFrame, **kwargs: object) -> ScreenQuery:
    """Create a query carrying deterministic local lineage for replay."""

    input_checksum = records_checksum(frame)
    formulas = sorted(
        {
            str(signal.supporting_metrics.get("formula_version"))
            for signal in getattr(snapshot, "signals", ())
            if signal.supporting_metrics.get("formula_version")
        }
    )
    formula_checksums = sorted(
        {
            str(signal.supporting_metrics.get("formula_checksum"))
            for signal in getattr(snapshot, "signals", ())
            if signal.supporting_metrics.get("formula_checksum")
        }
    )
    return ScreenQuery(
        as_of=_as_of(snapshot),
        universe_revision=str(getattr(snapshot, "universe_revision", "") or "unavailable"),
        formula_version="|".join(formulas) or "unavailable",
        formula_checksum="|".join(formula_checksums) or "unavailable",
        dataset_checksums=(("local_screen_rows", input_checksum),),
        input_checksum=input_checksum,
        **kwargs,  # type: ignore[arg-type]
    )


def _metric(metrics: dict[str, object], key: str, fallback: object = None) -> object:
    value = metrics.get(key, fallback)
    return value if _present(value) else fallback


def _quality(fundamental: pd.Series) -> float | None:
    values = pd.to_numeric(
        pd.Series([fundamental.get("profitability"), fundamental.get("growth"), fundamental.get("shareholder_return")]),
        errors="coerce",
    ).dropna()
    return float(values.mean()) if not values.empty else None


def _fundamental_score_eligible(fundamental: pd.Series, *, assessment_date: date | None = None) -> bool:
    if fundamental.empty or assessment_date is None:
        return False
    return assess_fundamental_row(fundamental, today=assessment_date).score_eligible


def _model_availability(status: dict[str, bool]) -> str:
    available = sorted(str(key) for key, value in status.items() if value)
    return "|".join(available) if available else "baseline_only"


def _as_of(snapshot: Any) -> str:
    value = getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    return str(value or "unavailable")


def _as_of_date(snapshot: Any) -> date | None:
    try:
        value = pd.Timestamp(_as_of(snapshot))
    except (TypeError, ValueError, OverflowError):
        return None
    return value.date() if not pd.isna(value) else None


def _freshness(value: object, snapshot_as_of: str) -> tuple[str, int | None]:
    try:
        observed = pd.Timestamp(value).normalize()
        current = pd.Timestamp(snapshot_as_of).normalize()
    except (TypeError, ValueError, OverflowError):
        return "unavailable", None
    if pd.isna(observed) or pd.isna(current):
        return "unavailable", None
    days = max(0, int((current - observed).days))
    return ("as_of_snapshot" if days == 0 else "aged"), days


def _present(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return False
    try:
        return not bool(pd.isna(value))
    except (TypeError, ValueError):
        return True


__all__ = ["build_screen_rows", "query_for_snapshot"]
