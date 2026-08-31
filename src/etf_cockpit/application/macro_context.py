"""Bind local macro producers to one point-in-time application snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    scenario = _scenario_payload(observations, decision_time, currency, horizon_days)
    return MacroContextBinding(
        decision_time=decision_time,
        summary=dict(summary),
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
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    return frame.loc[dates <= pd.Timestamp(decision_time)].copy()


def _portfolio_currency(snapshot: object) -> str:
    configured = getattr(snapshot, "benchmark_reference_currency", None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip().upper()
    costs = getattr(getattr(snapshot, "config", None), "costs", None)
    currency = getattr(costs, "base_currency", None)
    return str(currency or "EUR").strip().upper() or "EUR"


def _instruments(snapshot: object) -> object:
    universe = getattr(getattr(snapshot, "config", None), "universe", None)
    return getattr(universe, "etfs", ())


def _scenario_horizon_days(snapshot: object) -> int:
    raw = getattr(snapshot, "benchmark_reference_horizon_years", None)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.25
    return max(1, round(value * 365))


def _scenario_payload(
    observations: tuple[MacroObservation, ...],
    decision_time: str,
    currency: str,
    horizon_days: int,
) -> dict[str, object]:
    evidence: list[MacroEvidence] = []
    links: list[MacroScenarioLink] = []
    for row in observations:
        driver = _driver(row.series_id, row.dataset_kind)
        evidence_id = row.observation_id
        country = str(row.country or "")
        row_currency = str(row.currency or "")
        effective_time = f"{row.period_start}T00:00:00+00:00"
        authority = (
            MacroAuthority.OFFICIAL_PUBLIC_FILE
            if row.source_authority in {"official_regulator", "official_public_file"}
            else MacroAuthority.LOCAL_USER_IMPORT
        )
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
                limitations=(row.source_terms,) if row.source_terms else (),
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
                rationale="Local warehouse observation linked for descriptive scenario context.",
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
    text = f"{series_id} {dataset_kind}".lower()
    if any(term in text for term in ("inflation", "cpi", "pce")):
        return "inflation"
    if any(term in text for term in ("rate", "yield", "policy", "sofr")):
        return "rates"
    return dataset_kind or "macro"


def _unavailable_binding(
    reason: str,
    decision_time: str | None,
    currency: str,
    horizon_days: int,
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
    currency: str,
    horizon_days: int,
) -> dict[str, object]:
    return {
        "contract": "macro-scenario-context.v1",
        "status": "unavailable",
        "decision_time": decision_time,
        "portfolio_currency": currency,
        "horizon_days": horizon_days,
        "rows": [],
        "limitations": [reason],
        "context_only": True,
        "score_eligible": False,
        "forecast_authority": False,
        "execution_allowed": False,
        "context_hash": "unavailable",
    }


__all__ = ["MacroContextBinding", "build_macro_context_binding"]
