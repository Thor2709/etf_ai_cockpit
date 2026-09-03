"""Bind local macro producers to one point-in-time application snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from numbers import Real
from pathlib import Path
from typing import Mapping

import pandas as pd

from etf_cockpit.analysis.macro_regime_scenarios import (
    MacroAuthority,
    MacroEvidence,
    MacroScenarioContext,
    MacroScenarioLink,
    MacroScenarioError,
    build_macro_scenario_context,
    macro_scenario_payload,
)
from etf_cockpit.data.macro_warehouse import (
    MacroObservation,
    MacroWarehouse,
)
from etf_cockpit.features.macro import build_macro_context


@dataclass(frozen=True)
class MacroContextBinding:
    """All macro page evidence selected using the same snapshot cutoff."""

    decision_time: str | None
    summary: dict[str, object]
    observations: tuple[MacroObservation, ...]
    curve_coverage: dict[str, object]
    context: dict[str, object]
    scenario: dict[str, object]
    error: str | None = None


def build_macro_context_binding(
    snapshot: object,
    *,
    warehouse: MacroWarehouse,
    root: Path,
    benchmark_data_id: str | None = None,
    benchmark_reference: Mapping[str, object] | None = None,
    benchmark_registry: object | None = None,
) -> MacroContextBinding:
    """Build page evidence from local producers at the snapshot decision time.

    The caller's decision time is mandatory.  No wall-clock or synthetic
    future cutoff is used when the snapshot does not carry one.
    """

    decision_time, cutoff_error = _snapshot_decision_time(snapshot)
    currency = _portfolio_currency(snapshot)
    horizon_days = _scenario_horizon_days(snapshot)
    if cutoff_error is not None:
        return _unavailable_binding(cutoff_error, decision_time, currency, horizon_days)

    try:
        summary = warehouse.summary(root=root, decision_time=decision_time)
        observations = tuple(
            warehouse.observations_as_of(root=root, decision_time=decision_time)
        )
        curve_coverage = warehouse.curve_benchmark_coverage(
            root=root, decision_time=decision_time
        )
    except (ValueError, OSError) as exc:
        return _unavailable_binding(
            f"local macro warehouse could not be read ({type(exc).__name__})",
            decision_time,
            currency,
            horizon_days,
        )

    prices = _prices_as_of(getattr(snapshot, "prices", None), decision_time)
    context = build_macro_context(
        prices,
        _instruments(snapshot),
        observations,
        benchmark_data_id=benchmark_data_id,
        benchmark_reference=benchmark_reference,
        benchmark_registry=benchmark_registry,
    )
    # The feature producer uses the latest price timestamp as its observation
    # cutoff.  The application contract is the snapshot decision cutoff for
    # every producer, including macro observations.
    context = dict(context)
    context["decision_time"] = decision_time
    context["inflation_rates"] = _macro_observation_summary(
        observations, decision_time=decision_time
    )
    scenario = _scenario_payload(observations, decision_time, currency, horizon_days)
    return MacroContextBinding(
        decision_time=decision_time,
        summary=_selected_summary(summary, observations, decision_time),
        observations=observations,
        curve_coverage=dict(curve_coverage),
        context=context,
        scenario=scenario,
    )


def _snapshot_decision_time(snapshot: object) -> tuple[str | None, str | None]:
    raw = getattr(snapshot, "benchmark_reference_decision_time", None)
    if not isinstance(raw, str) or not raw.strip():
        return None, "snapshot decision time is unavailable"
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None, "snapshot decision time is invalid"
    if parsed.tzinfo is None:
        return None, "snapshot decision time must be timezone-aware"
    return parsed.astimezone(timezone.utc).isoformat(), None


def _prices_as_of(prices: object, decision_time: str) -> pd.DataFrame:
    if not isinstance(prices, pd.DataFrame) or prices.empty or "date" not in prices:
        return pd.DataFrame()
    frame = prices.copy()
    raw_dates = frame["date"]
    dates = pd.to_datetime(raw_dates, errors="coerce", utc=True, format="mixed")
    effective_dates = dates.copy()
    date_only = raw_dates.map(_is_date_only)
    effective_dates.loc[date_only] = (
        dates.loc[date_only].dt.normalize()
        + pd.Timedelta(days=1)
        - pd.Timedelta(nanoseconds=1)
    )
    cutoff = pd.Timestamp(decision_time)
    return frame.loc[dates.notna() & (effective_dates <= cutoff)].copy()


def _is_date_only(value: object) -> bool:
    if isinstance(value, pd.Timestamp):
        return value.tzinfo is None and value == value.normalize()
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return (
            getattr(value, "hour", 0) == 0
            and getattr(value, "minute", 0) == 0
            and getattr(value, "second", 0) == 0
            and getattr(value, "microsecond", 0) == 0
        )
    text = str(value).strip()
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _portfolio_currency(snapshot: object) -> str | None:
    configured = getattr(snapshot, "benchmark_reference_currency", None)
    if not isinstance(configured, str):
        return None
    currency = configured.strip().upper()
    return currency if len(currency) == 3 and currency.isalpha() else None


def _instruments(snapshot: object) -> object:
    universe = getattr(getattr(snapshot, "config", None), "universe", None)
    return getattr(universe, "etfs", ())


def _scenario_horizon_days(snapshot: object) -> int | None:
    raw = getattr(snapshot, "benchmark_reference_horizon_years", None)
    if isinstance(raw, bool) or not isinstance(raw, Real):
        return None
    try:
        value = float(raw)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    days = value * 365
    if not math.isfinite(days):
        return None
    return max(1, round(days))


def _scenario_payload(
    observations: tuple[MacroObservation, ...],
    decision_time: str,
    currency: str | None,
    horizon_days: int | None,
) -> dict[str, object]:
    if currency is None or horizon_days is None:
        return _unavailable_scenario(
            "snapshot portfolio currency or horizon is unavailable",
            decision_time,
            currency,
            horizon_days,
        )
    evidence: list[MacroEvidence] = []
    links: list[MacroScenarioLink] = []
    for row in observations:
        driver = _driver(row.series_id, row.dataset_kind)
        evidence_id = row.observation_id
        country = str(row.country or "")
        row_currency = str(row.currency or "")
        effective_time = f"{row.period_start}T00:00:00+00:00"
        authority = _scenario_authority(row.source_authority)
        limitations = []
        if row.source_terms:
            limitations.append(row.source_terms)
        if row.timezone_confidence != "exact":
            limitations.append("assumed_time")
        if row.availability_confidence != "exact":
            limitations.append("source_limitations")
        evidence.append(
            MacroEvidence(
                evidence_id=evidence_id,
                driver=driver,
                series_id=row.series_id,
                country=country,
                currency=row_currency,
                unit=row.unit,
                value=row.value,
                observation_time=row.observed_at,
                effective_time=effective_time,
                available_at=row.available_at,
                revision=max(0, row.revision - 1),
                source_id=row.source_id,
                source_sha256=row.source_checksum.lower(),
                authority=authority,
                limitations=tuple(limitations),
            )
        )
        links.append(
            MacroScenarioLink(
                link_id=f"warehouse:{evidence_id}",
                scenario=f"{driver} context",
                driver=driver,
                series_id=row.series_id,
                country=country,
                currency=row_currency,
                unit=row.unit,
                horizon_days=horizon_days,
                rationale="Derived warehouse observation has no explicit user-authored scenario link.",
                user_authored=False,
            )
        )
    try:
        context: MacroScenarioContext = build_macro_scenario_context(
            evidence,
            links,
            decision_time=decision_time,
            portfolio_currency=currency,
            horizon_days=horizon_days,
        )
        return macro_scenario_payload(context)
    except (MacroScenarioError, ValueError, TypeError) as exc:
        return _unavailable_scenario(
            f"local macro scenario context is unavailable ({type(exc).__name__})",
            decision_time,
            currency,
            horizon_days,
        )


def _driver(series_id: str, dataset_kind: str) -> str:
    # A warehouse observation does not carry an authorized scenario driver.
    # Never infer one from a series name (for example, unemployment_rate).
    return "unavailable"


def _scenario_authority(value: object) -> MacroAuthority | str | None:
    if value == "official_public_file":
        return MacroAuthority.OFFICIAL_PUBLIC_FILE
    if value == "local_user_import":
        return MacroAuthority.LOCAL_USER_IMPORT
    # Preserve unsupported and missing authority for the scenario validator to
    # reject explicitly; never infer local user authorship.
    return value if isinstance(value, str) and value.strip() else None


def _selected_summary(
    supplied: Mapping[str, object],
    observations: tuple[MacroObservation, ...],
    decision_time: str,
) -> dict[str, object]:
    """Project summary fields from the exact rows selected at the cutoff."""

    summary = dict(supplied)
    # Raw history size includes observations not known at this cutoff.
    summary.pop("total_row_count", None)
    summary.update(
        {
            "status": "available" if observations else "unavailable",
            "row_count": len(observations),
            "dataset_ids": sorted({row.dataset_id for row in observations}),
            "dataset_kinds": sorted({row.dataset_kind for row in observations}),
            "latest_observed_at": max(
                (row.observed_at for row in observations), default=None
            ),
            "missing_country_or_currency_count": sum(
                not row.country or not row.currency for row in observations
            ),
            "decision_time": decision_time,
            "execution_allowed": False,
        }
    )
    if observations:
        summary.pop("reason", None)
    return summary


def _macro_observation_summary(
    observations: tuple[MacroObservation, ...], *, decision_time: str
) -> dict[str, object]:
    cutoff = pd.Timestamp(decision_time)
    rows: list[dict[str, object]] = []
    for observation in observations:
        available_at = pd.to_datetime(observation.available_at, errors="coerce", utc=True)
        if pd.isna(available_at) or available_at > cutoff:
            continue
        if observation.timezone_confidence not in {"exact", "assumed"}:
            continue
        if observation.availability_confidence not in {"exact", "assumed"}:
            continue
        series_id = observation.series_id.lower()
        if not any(
            term in series_id
            for term in ("inflation", "cpi", "pce", "rate", "yield", "sofr", "policy")
        ):
            continue
        rows.append(
            {
                "series_id": observation.series_id,
                "value": observation.value,
                "unit": observation.unit,
                "source": observation.source_id or "local macro warehouse",
                "provenance": "local macro warehouse bitemporal as_of selection",
                "source_authority": observation.source_authority,
                "source_checksum": observation.source_checksum,
                "source_observation_ids": list(observation.source_observation_ids),
                "published_at": observation.published_at,
                "observed_at": observation.observed_at,
                "available_at": observation.available_at,
                "revised_at": observation.revised_at,
                "ingested_at": observation.ingested_at,
                "revision": observation.revision,
                "freshness_status": "fresh"
                if (cutoff - available_at).days <= 7
                else "stale",
                "reason_codes": [
                    reason
                    for reason, enabled in (
                        ("assumed_time", observation.timezone_confidence == "assumed"),
                        ("source_limitations", observation.availability_confidence == "assumed"),
                    )
                    if enabled
                ],
            }
        )
    return {
        "status": "available" if rows else "unavailable",
        "rows": rows[-12:],
        "reason": None if rows else "No local inflation or rates observations matched.",
    }


def _unavailable_binding(
    reason: str,
    decision_time: str | None,
    currency: str | None,
    horizon_days: int | None,
) -> MacroContextBinding:
    return MacroContextBinding(
        decision_time=decision_time,
        summary={"status": "unavailable", "row_count": 0, "reason": reason},
        observations=(),
        curve_coverage={
            "status": "unavailable",
            "issuer_credit": "unavailable",
            "source_ids": [],
            "methodologies": [],
            "decision_time": decision_time or "unavailable",
        },
        context={
            "status": "unavailable",
            "reason": reason,
            "as_of": None,
            "freshness_status": "unavailable",
            "provenance": "local adjusted_close price snapshot",
            "proxy_rows": [],
            "inflation_rates": {"status": "unavailable", "rows": []},
            "breadth": {"status": "unavailable"},
            "volatility": {"status": "unavailable"},
            "regime": {"label": "Regime unavailable"},
            "context_only": True,
            "score_eligible": False,
            "execution_allowed": False,
        },
        scenario=_unavailable_scenario(
            reason, decision_time or "unavailable", currency, horizon_days
        ),
        error=reason,
    )


def _unavailable_scenario(
    reason: str,
    decision_time: str,
    currency: str | None,
    horizon_days: int | None,
) -> dict[str, object]:
    return {
        "contract": "macro-scenario-context.v1",
        "status": "unavailable",
        "decision_time": decision_time,
        "portfolio_currency": currency or "unavailable",
        "horizon_days": horizon_days if horizon_days is not None else "unavailable",
        "rows": [],
        "limitations": [reason],
        "context_only": True,
        "score_eligible": False,
        "forecast_authority": False,
        "execution_allowed": False,
        "context_hash": "unavailable",
    }


__all__ = ["MacroContextBinding", "build_macro_context_binding"]
