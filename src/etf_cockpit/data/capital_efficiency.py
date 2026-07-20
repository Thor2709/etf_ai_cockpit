"""Capital-efficiency research derived from canonical statement evidence.

Reported and optional intangible-adjusted measures are separate by contract.
The module produces evidence and assumption exports, never a score or action.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import math

import pandas as pd

from etf_cockpit.data.statement_normalisation import statement_coverage, statement_view


CAPITAL_EFFICIENCY_SCHEMA_VERSION = "capital_efficiency.v1"
_SPECIAL_SECTORS = frozenset(
    {"bank", "banks", "insurance", "insurer", "financial", "financials"}
)
_MINIMUM_INCREMENTAL_PERIODS = 3
_MINIMUM_CAPITAL_CHANGE = 0.01
_FORMULAS = {
    "invested_capital": "equity + debt - cash",
    "nopat": "operating_income * (1 - tax_rate)",
    "roic": "NOPAT / invested_capital",
    "incremental_roic": "change in NOPAT / change in invested_capital",
    "reinvestment_rate": "change in invested_capital / current NOPAT",
    "sales_to_capital": "revenue / invested_capital",
    "asset_turns": "revenue / assets",
    "economic_profit_spread": "ROIC - cost_of_capital",
}
_ALIASES = {
    "revenue": ("revenue", "sales"),
    "operating_income": ("operating_income", "operating_profit", "ebit"),
    "assets": ("assets", "total_assets"),
    "equity": ("equity", "shareholders_equity", "stockholders_equity"),
    "debt": ("debt", "total_debt"),
    "cash": ("cash", "cash_and_equivalents"),
    "research_and_development": (
        "research_and_development",
        "research_expense",
        "rd_expense",
    ),
    "advertising_expense": ("advertising_expense",),
}


def capital_efficiency_analysis(
    statements: pd.DataFrame,
    *,
    instrument_id: str | None = None,
    sector: str = "",
    peer_frame: pd.DataFrame | None = None,
    tax_rate: float | None = None,
    cost_of_capital: float | None = None,
    intangible_assumptions: Mapping[str, object] | None = None,
    as_known_at: str | date | None = None,
) -> dict[str, object]:
    """Calculate source-linked reported and optional adjusted evidence."""

    frame = _canonical_frame(statements, instrument_id, as_known_at)
    inferred_tax = _reported_tax_rate(frame)
    tax = _rate(tax_rate if tax_rate is not None else inferred_tax)
    capital_cost = _rate(cost_of_capital)
    periods = _period_records(frame, tax)
    special_sector = sector.casefold() in _SPECIAL_SECTORS
    reported = _section(frame, periods, capital_cost, special_sector=special_sector)
    adjusted, sensitivity = _adjusted_evidence(
        frame,
        periods,
        tax,
        capital_cost,
        intangible_assumptions,
        special_sector=special_sector,
    )
    return {
        "schema_version": CAPITAL_EFFICIENCY_SCHEMA_VERSION,
        "instrument_id": instrument_id or "",
        "sector": sector or "unclassified",
        "reported": reported,
        "adjusted": adjusted,
        "assumption_sensitivity": sensitivity,
        "calculation_inputs": {
            "tax_rate": tax,
            "tax_rate_basis": "explicit_assumption"
            if tax_rate is not None
            else "reported_effective_rate"
            if inferred_tax is not None
            else "unavailable",
            "cost_of_capital": capital_cost,
            "cost_of_capital_basis": "explicit_assumption"
            if cost_of_capital is not None
            else "unavailable",
        },
        "sector_relative": _peer_context(peer_frame, tax, reported),
        "business_quality_proxies": _quality_proxies(frame, reported["history"]),
        "proxy_authority": "descriptive_only",
        "authority_constraints": {
            "can_override_valuation": False,
            "can_override_risk": False,
            "unsupported_qualitative_labels_allowed": False,
        },
        "source_lineage": _lineage(frame),
        "execution_allowed": False,
    }


def _canonical_frame(
    frame: pd.DataFrame, instrument_id: str | None, as_known_at: str | date | None
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    view = "as_known_at" if as_known_at is not None else "latest_restated"
    result = statement_view(frame, view, as_known_at=as_known_at)
    if instrument_id and "instrument_id" in result.columns:
        result = result[result["instrument_id"].astype(str).eq(str(instrument_id))]
    result = result.reset_index(drop=True)
    result.attrs["statement_view"] = view
    if as_known_at is not None:
        result.attrs["as_known_at"] = pd.Timestamp(as_known_at).date().isoformat()
    return result


def _period_records(
    frame: pd.DataFrame, tax_rate: float | None
) -> list[dict[str, object]]:
    if frame.empty or not {"canonical_metric", "value"} <= set(frame.columns):
        return []
    work = frame.copy()
    for column, default in (
        ("period_type", "unknown"),
        ("period_key", ""),
        ("period_end", ""),
        ("source_id", ""),
    ):
        if column not in work:
            work[column] = default
    work["__sort_end"] = pd.to_datetime(work["period_end"], errors="coerce")
    work = work.sort_values(
        ["__sort_end", "period_key", "canonical_metric", "source_id"],
        kind="stable",
        na_position="last",
    )
    grouped = list(
        work.groupby(
            ["period_type", "period_key", "period_end"], sort=False, dropna=False
        )
    )
    annual = [
        item
        for item in grouped
        if str(item[0][0]).casefold() in {"annual", "fy", "year"}
    ]
    records: list[dict[str, object]] = []
    for (period_type, period_key, period_end), rows in annual or grouped:
        raw: dict[str, float] = {}
        sources: dict[str, tuple[str, ...]] = {}
        for metric, metric_rows in rows.groupby(
            "canonical_metric", sort=False, dropna=True
        ):
            numeric = metric_rows.assign(
                __numeric=pd.to_numeric(metric_rows["value"], errors="coerce")
            ).dropna(subset=["__numeric"])
            if numeric.empty:
                continue
            name = str(metric)
            raw[name] = float(numeric.iloc[-1]["__numeric"])
            sources[name] = tuple(
                sorted(
                    {
                        str(value)
                        for value in numeric["source_id"].dropna()
                        if str(value)
                    }
                )
            )
        values = {
            name: _alias_value(raw, aliases) for name, aliases in _ALIASES.items()
        }
        invested_capital = _sum(
            values["equity"],
            values["debt"],
            -values["cash"] if values["cash"] is not None else None,
        )
        nopat = (
            None
            if values["operating_income"] is None or tax_rate is None
            else values["operating_income"] * (1.0 - tax_rate)
        )
        records.append(
            {
                "period_type": str(period_type),
                "period_key": str(period_key),
                "period_end": str(period_end),
                **values,
                "raw": raw,
                "raw_sources": sources,
                "source_ids": tuple(
                    sorted({source for items in sources.values() for source in items})
                ),
                "invested_capital": invested_capital,
                "nopat": nopat,
                "roic": _divide(nopat, invested_capital),
                "sales_to_capital": _divide(values["revenue"], invested_capital),
                "asset_turns": _divide(values["revenue"], values["assets"]),
            }
        )
    return records


def _section(
    frame: pd.DataFrame,
    history: list[dict[str, object]],
    cost_of_capital: float | None,
    *,
    special_sector: bool,
) -> dict[str, object]:
    applicability = "not_applicable" if special_sector else "applicable"
    sector_limitation = "Special-sector adapter required; industrial capital-efficiency formulas are not applicable."
    latest = history[-1] if history else {}
    metrics: dict[str, dict[str, object]] = {}
    source_metrics = {
        "invested_capital": "equity",
        "nopat": "operating_income",
        "roic": "operating_income",
        "sales_to_capital": "revenue",
        "asset_turns": "assets",
    }
    for name in (
        "invested_capital",
        "nopat",
        "roic",
        "sales_to_capital",
        "asset_turns",
    ):
        value = None if special_sector else _float(latest.get(name))
        limitation = (
            sector_limitation
            if special_sector
            else "Explicit tax evidence or an exported tax-rate assumption is required."
            if name in {"nopat", "roic"} and value is None
            else ""
        )
        metrics[name] = _metric(
            name,
            value,
            _FORMULAS[name],
            frame,
            source_metric=source_metrics[name],
            applicability=applicability,
            limitation=limitation,
        )
    metrics["incremental_roic"], metrics["reinvestment_rate"] = _incremental_metrics(
        frame, history, special_sector
    )
    spread = (
        None
        if special_sector or latest.get("roic") is None or cost_of_capital is None
        else float(latest["roic"] - cost_of_capital)
    )
    metrics["economic_profit_spread"] = _metric(
        "economic_profit_spread",
        spread,
        _FORMULAS["economic_profit_spread"],
        frame,
        applicability=applicability,
        limitation=sector_limitation
        if special_sector
        else "An explicit cost-of-capital assumption is required."
        if cost_of_capital is None
        else "",
    )
    public_history = (
        []
        if special_sector
        else [
            {
                key: value
                for key, value in item.items()
                if key not in {"raw", "raw_sources"}
            }
            for item in history
        ]
    )
    return {
        "status": "not_applicable"
        if special_sector
        else "available"
        if any(metric["value"] is not None for metric in metrics.values())
        else "unavailable",
        "metrics": metrics,
        "history": public_history,
        "minimum_history_periods": _MINIMUM_INCREMENTAL_PERIODS,
        "stable_denominator_threshold": _MINIMUM_CAPITAL_CHANGE,
    }


def _incremental_metrics(
    frame: pd.DataFrame, history: list[dict[str, object]], special_sector: bool
) -> tuple[dict[str, object], dict[str, object]]:
    extra = {
        "minimum_periods": _MINIMUM_INCREMENTAL_PERIODS,
        "observed_periods": len(history),
    }
    if special_sector:
        status, limitation = "not_applicable", "Special-sector adapter required."
        values = (None, None)
    elif len(history) < _MINIMUM_INCREMENTAL_PERIODS:
        status, limitation = (
            "insufficient_history",
            "At least three complete comparable annual periods are required.",
        )
        values = (None, None)
    else:
        previous, latest = history[-2:]
        prior_capital = _float(previous.get("invested_capital"))
        current_capital = _float(latest.get("invested_capital"))
        delta_capital = (
            None
            if prior_capital is None or current_capital is None
            else current_capital - prior_capital
        )
        threshold = (
            None
            if prior_capital is None
            else _MINIMUM_CAPITAL_CHANGE * abs(prior_capital)
        )
        unstable = (
            delta_capital is not None
            and threshold is not None
            and (
                abs(delta_capital) < threshold
                or threshold == 0
                and abs(delta_capital) <= 1e-12
            )
        )
        if unstable:
            status, limitation = (
                "unstable_denominator",
                "The invested-capital change is below 1% of prior invested capital.",
            )
            values = (None, None)
        else:
            prior_nopat, current_nopat = (
                _float(previous.get("nopat")),
                _float(latest.get("nopat")),
            )
            delta_nopat = (
                None
                if prior_nopat is None or current_nopat is None
                else current_nopat - prior_nopat
            )
            values = (
                _divide(delta_nopat, delta_capital),
                _divide(delta_capital, current_nopat),
            )
            status, limitation = (
                "available",
                "Requires comparable NOPAT and invested-capital evidence.",
            )
    incremental = (
        _metric(
            "incremental_roic",
            values[0],
            _FORMULAS["incremental_roic"],
            frame,
            source_metric="operating_income",
            status=status,
            limitation=limitation,
        )
        | extra
    )
    reinvestment = (
        _metric(
            "reinvestment_rate",
            values[1],
            _FORMULAS["reinvestment_rate"],
            frame,
            source_metric="equity",
            status=status,
            limitation=limitation,
        )
        | extra
    )
    if status == "available":
        incremental["status"] = (
            "missing"
            if values[0] is None
            else "negative"
            if values[0] < 0
            else "available"
        )
        reinvestment["status"] = (
            "missing"
            if values[1] is None
            else "negative"
            if values[1] < 0
            else "available"
        )
    return incremental, reinvestment


def _adjusted_evidence(
    frame: pd.DataFrame,
    reported_history: list[dict[str, object]],
    tax_rate: float | None,
    cost_of_capital: float | None,
    assumptions: Mapping[str, object] | None,
    *,
    special_sector: bool,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    normalised, errors = _normalise_assumptions(assumptions)
    base = {
        "assumptions": normalised,
        "metrics": {},
        "history": [],
        "execution_allowed": False,
    }
    if not normalised["enabled"]:
        return base | {
            "status": "disabled",
            "reason": "Optional intangible capitalisation is disabled.",
        }, []
    if errors:
        return base | {"status": "invalid_assumptions", "reason": "; ".join(errors)}, []
    if special_sector:
        return base | {
            "status": "not_applicable",
            "reason": "Special-sector adapter required.",
        }, []
    adjusted_history = _adjusted_history(reported_history, tax_rate, normalised)
    if not adjusted_history or all(
        item["intangible_asset"] == 0 for item in adjusted_history
    ):
        return base | {
            "status": "unavailable",
            "reason": "No disclosed research or advertising expense evidence is available.",
        }, []
    section = _section(frame, adjusted_history, cost_of_capital, special_sector=False)
    latest = adjusted_history[-1]
    section.update(
        {
            "status": "available",
            "assumptions": normalised,
            "latest_bridge": {
                key: latest[key]
                for key in (
                    "reported_operating_income",
                    "capitalised_expense",
                    "amortisation",
                    "adjusted_operating_income",
                    "intangible_asset",
                    "reported_invested_capital",
                    "adjusted_invested_capital",
                )
            },
            "execution_allowed": False,
        }
    )
    scenarios = {
        "selected": normalised,
        "shorter_life": normalised
        | {
            "research_years": max(1, int(normalised["research_years"]) - 1),
            "advertising_years": max(1, int(normalised["advertising_years"]) - 1),
        },
        "lower_capitalisation": normalised
        | {
            "research_capitalisation_rate": float(
                normalised["research_capitalisation_rate"]
            )
            * 0.5,
            "advertising_capitalisation_rate": float(
                normalised["advertising_capitalisation_rate"]
            )
            * 0.5,
        },
    }
    sensitivity = []
    for name, scenario in scenarios.items():
        history = _adjusted_history(reported_history, tax_rate, scenario)
        latest_scenario = history[-1] if history else {}
        sensitivity.append(
            {
                "scenario": name,
                "assumptions": scenario,
                "adjusted_roic": latest_scenario.get("roic"),
                "intangible_asset": latest_scenario.get("intangible_asset"),
                "execution_allowed": False,
            }
        )
    return section, sensitivity


def _normalise_assumptions(
    assumptions: Mapping[str, object] | None,
) -> tuple[dict[str, object], list[str]]:
    source = assumptions or {}
    research_years, advertising_years = (
        _float(source.get("research_years")),
        _float(source.get("advertising_years")),
    )
    research_rate, advertising_rate = (
        _float(source.get("research_capitalisation_rate")),
        _float(source.get("advertising_capitalisation_rate")),
    )
    values: dict[str, object] = {
        "enabled": _truthy(source.get("enabled", False)),
        "method": "straight_line",
        "research_years": int(research_years) if research_years is not None else 3,
        "advertising_years": int(advertising_years)
        if advertising_years is not None
        else 2,
        "research_capitalisation_rate": research_rate
        if "research_capitalisation_rate" in source
        else 1.0,
        "advertising_capitalisation_rate": advertising_rate
        if "advertising_capitalisation_rate" in source
        else 0.0,
    }
    errors = []
    for key, parsed in (
        ("research_years", research_years),
        ("advertising_years", advertising_years),
    ):
        if key in source and (parsed is None or not parsed.is_integer()):
            errors.append(f"{key} must be a whole number")
        if not 1 <= int(values[key]) <= 10:
            errors.append(f"{key} must be between 1 and 10")
    for key in ("research_capitalisation_rate", "advertising_capitalisation_rate"):
        value = values[key]
        if value is None or not 0.0 <= float(value) <= 1.0:
            errors.append(f"{key} must be between 0 and 1")
    return values, errors


def _adjusted_history(
    reported: list[dict[str, object]],
    tax_rate: float | None,
    assumptions: Mapping[str, object],
) -> list[dict[str, object]]:
    adjusted = []
    for index, period in enumerate(reported):
        capitalised_expense = amortisation = intangible_asset = 0.0
        for metric, years_key, rate_key in (
            (
                "research_and_development",
                "research_years",
                "research_capitalisation_rate",
            ),
            (
                "advertising_expense",
                "advertising_years",
                "advertising_capitalisation_rate",
            ),
        ):
            life, rate = int(assumptions[years_key]), float(assumptions[rate_key])
            current = _float(period.get(metric)) or 0.0
            capitalised_expense += current * rate
            for cohort_index in range(max(0, index - life + 1), index + 1):
                cohort = (_float(reported[cohort_index].get(metric)) or 0.0) * rate
                age = index - cohort_index
                if age:
                    amortisation += cohort / life
                intangible_asset += cohort * max(0.0, 1.0 - age / life)
        reported_income, reported_capital = (
            _float(period.get("operating_income")),
            _float(period.get("invested_capital")),
        )
        adjusted_income = (
            None
            if reported_income is None
            else reported_income + capitalised_expense - amortisation
        )
        adjusted_capital = (
            None if reported_capital is None else reported_capital + intangible_asset
        )
        nopat = (
            None
            if adjusted_income is None or tax_rate is None
            else adjusted_income * (1.0 - tax_rate)
        )
        adjusted.append(
            period
            | {
                "reported_operating_income": reported_income,
                "capitalised_expense": capitalised_expense,
                "amortisation": amortisation,
                "adjusted_operating_income": adjusted_income,
                "operating_income": adjusted_income,
                "intangible_asset": intangible_asset,
                "reported_invested_capital": reported_capital,
                "adjusted_invested_capital": adjusted_capital,
                "invested_capital": adjusted_capital,
                "nopat": nopat,
                "roic": _divide(nopat, adjusted_capital),
                "sales_to_capital": _divide(
                    _float(period.get("revenue")), adjusted_capital
                ),
            }
        )
    return adjusted


def _quality_proxies(frame: pd.DataFrame, history: object) -> dict[str, object]:
    latest = _latest(frame)
    recurring_share = _divide(latest.get("recurring_revenue"), latest.get("revenue"))
    recurring_invalid = (
        recurring_share is not None and not 0.0 <= recurring_share <= 1.0
    )
    proxies = {
        "recurring_revenue_share": _metric(
            "recurring_revenue_share",
            None if recurring_invalid else recurring_share,
            "disclosed recurring_revenue / revenue",
            frame,
            source_metric="recurring_revenue",
            status="invalid"
            if recurring_invalid
            else "unavailable"
            if recurring_share is None
            else None,
            limitation="Available only from explicit structured disclosure evidence.",
        ),
        "customer_concentration": _disclosure_metric(
            frame, latest, "customer_concentration"
        ),
        "supplier_concentration": _disclosure_metric(
            frame, latest, "supplier_concentration"
        ),
    }
    rows = history if isinstance(history, list) else []
    observed = [
        _float(item.get("roic"))
        for item in rows
        if isinstance(item, Mapping) and _float(item.get("roic")) is not None
    ]
    persistence = _metric(
        "capital_return_persistence",
        None
        if len(observed) < 3
        else sum(value > 0 for value in observed) / len(observed),
        "positive reported ROIC periods / observed comparable periods",
        frame,
        source_metric="operating_income",
        status="insufficient_history" if len(observed) < 3 else None,
        limitation="At least three comparable reported ROIC periods are required.",
    )
    persistence["coverage"] = {
        "observed_periods": len(observed),
        "minimum_periods": 3,
        "positive_periods": sum(value > 0 for value in observed),
    }
    persistence["dispersion"] = (
        None if len(observed) < 3 else float(pd.Series(observed).std(ddof=0))
    )
    proxies["capital_return_persistence"] = persistence
    return proxies


def _disclosure_metric(
    frame: pd.DataFrame, latest: Mapping[str, float], name: str
) -> dict[str, object]:
    value = latest.get(name)
    invalid = value is not None and not 0.0 <= value <= 1.0
    return _metric(
        name,
        None if invalid else value,
        f"reported {name} share",
        frame,
        source_metric=name,
        status="invalid" if invalid else "unavailable" if value is None else None,
        limitation="Available only from explicit structured disclosure evidence; values must be between 0 and 1.",
    )


def _peer_context(
    peer_frame: pd.DataFrame | None,
    tax_rate: float | None,
    reported: Mapping[str, object],
) -> dict[str, object]:
    if peer_frame is None or peer_frame.empty or "instrument_id" not in peer_frame:
        return {
            "status": "unavailable",
            "reason": "No explicit sector peer cohort was supplied.",
            "percentiles": {},
            "peer_count": 0,
        }
    peer_values = {name: [] for name in ("roic", "sales_to_capital", "asset_turns")}
    for _, group in peer_frame.groupby("instrument_id", sort=True):
        periods = _period_records(_canonical_frame(group, None, None), tax_rate)
        if periods:
            for name in peer_values:
                value = _float(periods[-1].get(name))
                if value is not None:
                    peer_values[name].append(value)
    metrics = reported.get("metrics", {})
    percentiles = {}
    for name, values in peer_values.items():
        item = metrics.get(name, {}) if isinstance(metrics, Mapping) else {}
        value = _float(item.get("value")) if isinstance(item, Mapping) else None
        if value is not None and values:
            percentiles[name] = (
                100.0 * sum(peer <= value for peer in values) / len(values)
            )
    return {
        "status": "available" if percentiles else "unavailable",
        "percentiles": percentiles,
        "peer_count": int(peer_frame["instrument_id"].nunique()),
        "authority": "descriptive_only",
    }


def _metric(
    name: str,
    value: float | None,
    formula: str,
    frame: pd.DataFrame,
    *,
    source_metric: str | None = None,
    status: str | None = None,
    applicability: str = "applicable",
    limitation: str = "",
) -> dict[str, object]:
    sources = _source_ids(frame, source_metric or name)
    period = _period_label(frame)
    resolved_status = status or (
        "not_applicable"
        if applicability != "applicable"
        else "missing"
        if value is None
        else "negative"
        if value < 0
        else "available"
    )
    return {
        "name": name,
        "value": value,
        "status": resolved_status,
        "formula": formula,
        "period": period,
        "source_ids": sources,
        "coverage": {"source_count": len(sources), "period": period},
        "confidence": "high" if value is not None and sources else "low",
        "applicability": applicability,
        "limitation": limitation,
    }


def _latest(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty or "canonical_metric" not in frame:
        return {}
    ordered = frame.copy()
    for column in ("period_end", "filed", "period_key"):
        if column not in ordered:
            ordered[column] = ""
    ordered = ordered.sort_values(
        ["canonical_metric", "period_end", "filed", "period_key"],
        kind="stable",
        na_position="last",
    )
    result = {}
    for name, rows in ordered.groupby("canonical_metric", dropna=True):
        values = pd.to_numeric(rows["value"], errors="coerce").dropna()
        if not values.empty:
            result[str(name)] = float(values.iloc[-1])
    return result


def _reported_tax_rate(frame: pd.DataFrame) -> float | None:
    latest = _latest(frame)
    return _divide(latest.get("tax_expense"), latest.get("income_before_tax"))


def _source_ids(frame: pd.DataFrame, metric: str) -> tuple[str, ...]:
    if frame.empty or not {"canonical_metric", "source_id"} <= set(frame.columns):
        return ()
    return tuple(
        sorted(
            {
                str(value)
                for value in frame.loc[
                    frame["canonical_metric"].astype(str).eq(metric), "source_id"
                ].dropna()
                if str(value)
            }
        )
    )


def _period_label(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "unavailable"
    for column in ("period_end", "period_key", "fiscal_year"):
        if column in frame and frame[column].notna().any():
            return str(frame[column].dropna().iloc[-1])
    return "unavailable"


def _lineage(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "statement_view": frame.attrs.get("statement_view", "latest_restated"),
        "coverage": statement_coverage(frame),
        "source_ids": sorted(
            {
                str(value)
                for value in frame.get("source_id", pd.Series(dtype="object")).dropna()
                if str(value)
            }
        ),
        "as_known_at": frame.attrs.get("as_known_at"),
        "execution_allowed": False,
    }


def _alias_value(
    values: Mapping[str, object], aliases: tuple[str, ...]
) -> float | None:
    return next(
        (
            _float(values.get(name))
            for name in aliases
            if _float(values.get(name)) is not None
        ),
        None,
    )


def _float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(value: object) -> float | None:
    result = _float(value)
    return result if result is not None and 0.0 <= result <= 1.0 else None


def _divide(numerator: object, denominator: object) -> float | None:
    top, bottom = _float(numerator), _float(denominator)
    return None if top is None or bottom in (None, 0.0) else top / bottom


def _sum(*values: float | None) -> float | None:
    return None if any(value is None for value in values) else float(sum(values))


def _truthy(value: object) -> bool:
    return value is True or str(value).strip().casefold() in {"1", "true", "yes", "on"}


__all__ = ["CAPITAL_EFFICIENCY_SCHEMA_VERSION", "capital_efficiency_analysis"]
