"""Local-first portfolio performance and decision attribution.

The functions in this module decompose observed adjusted-price returns and
explicit user-supplied evidence.  They do not infer broker fills, taxes or
foreign-exchange returns when those records are absent, and never create
execution authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import math

import numpy as np
import pandas as pd

from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkReferenceError,
    unavailable_reference_projection,
)
from etf_cockpit.application.benchmark_reference import validate_benchmark_reference
from etf_cockpit.application.benchmark_reference import clip_to_decision_window

ATTRIBUTION_MODEL_VERSION = "portfolio-attribution.v1"


def build_performance_attribution(
    prices: pd.DataFrame | None,
    allocation: pd.DataFrame | None,
    *,
    benchmark_returns: pd.DataFrame | None = None,
    factor_returns: pd.DataFrame | None = None,
    factor_exposures: pd.DataFrame | None = None,
    cashflows: pd.DataFrame | None = None,
    costs: pd.DataFrame | None = None,
    decisions: pd.DataFrame | None = None,
    reference_context: object | None = None,
) -> dict[str, object]:
    """Build gross/net, factor, currency and decision attribution evidence.

    ``allocation`` is a dated snapshot only when it has no date column; the
    returned report says so through its coverage fields.  Price observations
    are adjusted-price rows and missing observations are excluded from that
    day while remaining visible in coverage.  Asset contributions are linked
    through portfolio wealth, so their sum plus the explicit cash component
    reconciles to the gross time-weighted return.
    """

    empty = _empty_report(
        _unavailable_reference_projection()
        if reference_context is None
        else _reference_projection(reference_context),
    )
    returns = _return_matrix(_clip_to_declared_window(prices, reference_context))
    weights = _weights(allocation)
    if returns.empty or weights.empty:
        empty["message"] = "Adjusted-price returns or portfolio weights are unavailable."
        empty["coverage"] = {"status": "unavailable", "return_observations": int(len(returns)), "instrument_count": int(len(weights))}
        return empty

    common = [instrument for instrument in weights.index if instrument in returns.columns]
    if not common:
        empty["message"] = "No portfolio instruments have usable adjusted-price history."
        empty["coverage"] = {"status": "unavailable", "return_observations": int(len(returns)), "instrument_count": 0}
        return empty

    observed = returns[common]
    portfolio_weights = weights.reindex(common).fillna(0.0)
    cash_weight = float(1.0 - portfolio_weights.sum())
    daily, asset_rows, wealth = _linked_contributions(observed, portfolio_weights, cash_weight)
    asset_contributions = pd.DataFrame(asset_rows, columns=["date", "instrument_id", "contribution", "return", "coverage"])
    total_return = float(wealth.iloc[-1] - 1.0) if not wealth.empty else None
    asset_summary = _asset_summary(asset_contributions)
    asset_sum = float(asset_summary["contribution"].sum()) if not asset_summary.empty else 0.0
    cash_contribution = float((daily["cash_contribution"]).sum()) if not daily.empty else 0.0
    identity_residual = float((total_return or 0.0) - asset_sum - cash_contribution)

    factor_attribution = _factor_attribution(daily, wealth, factor_returns, factor_exposures)
    currency_attribution = _currency_attribution(asset_summary, allocation)
    bounded_costs, cost_evidence_status = _costs_in_declared_window(costs, reference_context)
    cost_attribution, cost_total, tax_total = _cost_attribution(bounded_costs)
    if bounded_costs is not None and not bounded_costs.empty and (cost_total is None or tax_total is None):
        cost_evidence_status = "invalid"
    benchmark = _benchmark_attribution(
        total_return,
        _canonical_benchmark_returns(returns, reference_context),
        daily.index,
        portfolio_returns=daily.get("portfolio_return"),
    )
    bounded_cashflows, cashflow_evidence_status = _cashflows_in_declared_window(cashflows, reference_context)
    if cashflow_evidence_status in {"invalid", "excluded_outside_window"}:
        money_weighted, money_status = None, "unavailable_invalid_or_outside_canonical_window"
    else:
        money_weighted, money_status = _money_weighted_return(wealth, daily.index, bounded_cashflows)
    decision_attribution = _decision_attribution(decisions, observed, portfolio_weights)
    warnings = _warnings(
        observed,
        allocation,
        factor_attribution,
        currency_attribution,
        bounded_costs,
        bounded_cashflows,
        decisions,
    )
    if cost_evidence_status == "invalid":
        warnings.append("explicit_costs_invalid_for_canonical_window")
    elif cost_evidence_status == "excluded_outside_window":
        warnings.append("explicit_costs_outside_canonical_window_excluded")
    if cashflow_evidence_status == "invalid":
        warnings.append("external_cashflows_invalid_for_canonical_window")
    elif cashflow_evidence_status == "excluded_outside_window":
        warnings.append("external_cashflows_outside_canonical_window_excluded")
    reference_projection = (
        _unavailable_reference_projection()
        if reference_context is None
        else _reference_projection(reference_context)
    )
    if reference_projection.get("status") != "available":
        warnings.append("canonical_benchmark_cash_resolution_unavailable")
    net_return = (
        None
        if total_return is None or cost_evidence_status == "invalid" or cost_total is None or tax_total is None
        else float(total_return - cost_total - tax_total)
    )

    return {
        "status": "available" if not warnings else "partial",
        "message": "Observed local attribution evidence; execution_allowed=false.",
        "model_version": ATTRIBUTION_MODEL_VERSION,
        "execution_allowed": False,
        "time_weighted_return": total_return,
        "money_weighted_return": money_weighted,
        "money_weighted_status": money_status,
        "net_return_after_explicit_costs": net_return,
        "cash_weight": cash_weight,
        "cash_contribution": cash_contribution,
        "identity_residual": identity_residual,
        "daily": daily.reset_index().rename(columns={"index": "date"}),
        "asset_contributions": asset_summary,
        "factor_attribution": factor_attribution,
        "currency_attribution": currency_attribution,
        "cost_attribution": cost_attribution,
        "decision_attribution": decision_attribution,
        "benchmark_attribution": benchmark,
        "benchmark_reference": reference_projection,
        "coverage": {
            "status": "partial" if warnings else "available",
            "return_observations": int(len(observed)),
            "instrument_count": int(len(common)),
            "missing_return_cells": int(observed.isna().sum().sum()),
            "allocation_is_dated": bool(allocation is not None and "date" in allocation.columns),
            "factor_status": _frame_status(factor_attribution),
            "currency_status": _frame_status(currency_attribution),
            "cost_status": cost_evidence_status,
            "tax_status": "available" if bounded_costs is not None and "tax" in bounded_costs.columns else "unavailable",
            "decision_status": _frame_status(decision_attribution),
            "benchmark_status": _frame_status(benchmark),
            "benchmark_reference_status": str(reference_projection.get("status", "unavailable")),
        },
        "diagnostics": {
            "gross_identity": "portfolio_return = asset_contributions + cash_contribution",
            "factor_residual": _factor_residual(total_return, factor_attribution),
            "explicit_cost_total": cost_total,
            "explicit_tax_total": tax_total,
            "cash_return_assumption": "0.0; supply a cash series for cash performance attribution",
        },
        "warnings": warnings,
    }


def _reference_projection(reference_context: object) -> dict[str, object]:
    registry = getattr(reference_context, "registry", None)
    resolution = getattr(reference_context, "resolution", None)
    if callable(getattr(registry, "ui_projection", None)) and resolution is not None:
        try:
            projection = dict(registry.ui_projection(resolution))  # type: ignore[union-attr]
            projection["status"] = "available" if not resolution.blockers else "unavailable"
            benchmark_data_id = getattr(reference_context, "benchmark_data_id", None)
            projection["benchmark_data_id"] = benchmark_data_id if isinstance(benchmark_data_id, str) else None
            declaration = resolution.declaration
            projection["analysis"] = {
                "instrument_id": declaration.instrument_id,
                "currency": declaration.currency,
                "horizon_years": declaration.horizon_years,
                "start_date": declaration.start_date,
                "end_date": declaration.end_date,
                "decision_time": declaration.decision_time,
            }
            _assert_execution_disabled(projection)
            return projection
        except (BenchmarkReferenceError, TypeError, ValueError, KeyError):
            pass
    return _unavailable_reference_projection()


def _unavailable_reference_projection() -> dict[str, object]:
    return unavailable_reference_projection()


def _canonical_benchmark_returns(
    returns: pd.DataFrame,
    reference_context: object | None,
) -> pd.DataFrame | None:
    """Derive benchmark returns only from a resolved canonical data identity."""

    if reference_context is None:
        return None
    resolution = getattr(reference_context, "resolution", None)
    benchmark_selection = getattr(resolution, "benchmark", None)
    cash_selection = getattr(resolution, "cash", None)
    if (
        benchmark_selection is None
        or cash_selection is None
        or getattr(benchmark_selection, "status", None) != "available"
        or getattr(cash_selection, "status", None) != "available"
    ):
        return None
    benchmark_id = getattr(reference_context, "benchmark_data_id", None)
    try:
        projection = _reference_projection(reference_context)
    except (BenchmarkReferenceError, TypeError, ValueError, KeyError):
        return None
    if (
        validate_benchmark_reference(
            projection,
            benchmark_id,
            registry=getattr(reference_context, "registry", None),
        )
        is None
        or benchmark_id not in returns.columns
    ):
        return None
    series = returns[benchmark_id].dropna()
    if series.empty:
        return None
    return pd.DataFrame({
        "date": series.index,
        "benchmark": benchmark_id,
        "return": series.to_numpy(float),
    })


def _clip_to_declared_window(
    prices: pd.DataFrame | None,
    reference_context: object | None,
) -> pd.DataFrame | None:
    """Prevent a relative result from using observations outside its declaration."""

    if not isinstance(prices, pd.DataFrame) or reference_context is None:
        return prices
    resolution = getattr(reference_context, "resolution", None)
    declaration = getattr(resolution, "declaration", None)
    start = getattr(declaration, "start_date", None)
    end = getattr(declaration, "end_date", None)
    decision_time = getattr(declaration, "decision_time", None)
    if (
        not isinstance(start, str)
        or not isinstance(end, str)
        or not isinstance(decision_time, str)
        or "date" not in prices.columns
    ):
        return pd.DataFrame()
    return clip_to_decision_window(
        prices,
        start_date=start,
        end_date=end,
        decision_time=decision_time,
    )


def _assert_execution_disabled(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "execution_allowed" and item is not False:
                raise BenchmarkReferenceError("serialized evidence cannot grant execution authority")
            _assert_execution_disabled(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_execution_disabled(item)


def _empty_report(reference_projection: dict[str, object] | None = None) -> dict[str, object]:
    empty_frame = pd.DataFrame()
    return {
        "status": "unavailable",
        "message": "Attribution evidence is unavailable.",
        "model_version": ATTRIBUTION_MODEL_VERSION,
        "execution_allowed": False,
        "time_weighted_return": None,
        "money_weighted_return": None,
        "money_weighted_status": "unavailable",
        "net_return_after_explicit_costs": None,
        "cash_weight": None,
        "cash_contribution": None,
        "identity_residual": None,
        "daily": empty_frame,
        "asset_contributions": empty_frame,
        "factor_attribution": empty_frame,
        "currency_attribution": empty_frame,
        "cost_attribution": empty_frame,
        "decision_attribution": empty_frame,
        "benchmark_attribution": empty_frame,
        "benchmark_reference": reference_projection or _unavailable_reference_projection(),
        "coverage": {"status": "unavailable"},
        "diagnostics": {},
        "warnings": ["attribution_inputs_unavailable"],
    }


def _return_matrix(prices: pd.DataFrame | None) -> pd.DataFrame:
    required = {"date", "etf_id", "adjusted_close"}
    if prices is None or prices.empty or not required.issubset(prices.columns):
        return pd.DataFrame()
    frame = prices[list(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["etf_id"] = frame["etf_id"].astype(str).str.strip()
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna(subset=["date", "adjusted_close"])
    frame = frame[(frame["etf_id"] != "") & frame["adjusted_close"].gt(0)]
    pivot = frame.pivot_table(index="date", columns="etf_id", values="adjusted_close", aggfunc="last").sort_index()
    return pivot.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).iloc[1:]


def _weights(allocation: pd.DataFrame | None) -> pd.Series:
    if allocation is None or allocation.empty or "etf_id" not in allocation.columns:
        return pd.Series(dtype=float)
    column = "current_weight" if "current_weight" in allocation.columns else "target_weight" if "target_weight" in allocation.columns else None
    if column is None:
        return pd.Series(dtype=float)
    frame = allocation[["etf_id", column]].copy()
    frame["etf_id"] = frame["etf_id"].astype(str).str.strip()
    frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[(frame["etf_id"] != "") & frame[column].notna() & np.isfinite(frame[column]) & frame[column].ge(0)]
    return frame.groupby("etf_id", sort=True)[column].sum().astype(float)


def _linked_contributions(returns: pd.DataFrame, weights: pd.Series, cash_weight: float) -> tuple[pd.DataFrame, list[dict[str, object]], pd.Series]:
    wealth = 1.0
    daily_rows: list[dict[str, object]] = []
    asset_rows: list[dict[str, object]] = []
    wealth_values: list[float] = []
    for date, row in returns.iterrows():
        previous = wealth
        valid = row.notna()
        contributions = previous * weights.where(valid, 0.0) * row.fillna(0.0)
        cash_contribution = previous * cash_weight * 0.0
        portfolio_pnl = float(contributions.sum() + cash_contribution)
        wealth += portfolio_pnl
        wealth_values.append(wealth)
        daily_rows.append(
            {
                "date": pd.Timestamp(date),
                "portfolio_return": portfolio_pnl / previous if previous else None,
                "gross_pnl": portfolio_pnl,
                "wealth": wealth,
                "cash_contribution": cash_contribution,
                "observed_instrument_count": int(valid.sum()),
            }
        )
        for instrument_id, value in contributions.items():
            asset_rows.append({"date": pd.Timestamp(date), "instrument_id": str(instrument_id), "contribution": float(value), "return": _finite(value / previous / weights[instrument_id]) if previous and weights[instrument_id] else None, "coverage": float(valid.get(instrument_id, False))})
    daily = pd.DataFrame(daily_rows).set_index("date") if daily_rows else pd.DataFrame(columns=["portfolio_return", "gross_pnl", "wealth", "cash_contribution", "observed_instrument_count"])
    return daily, asset_rows, pd.Series(wealth_values, index=daily.index, dtype=float)


def _asset_summary(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["instrument_id", "contribution", "observations", "mean_return", "coverage"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    grouped = frame.groupby("instrument_id", sort=True)
    result = grouped.agg(contribution=("contribution", "sum"), observations=("date", "size"), mean_return=("return", "mean"), coverage=("coverage", "mean")).reset_index()
    return result[columns]


def _factor_attribution(daily: pd.DataFrame, wealth: pd.Series, factor_returns: pd.DataFrame | None, factor_exposures: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["factor", "contribution", "share", "observations", "status"]
    if daily.empty or factor_returns is None or factor_returns.empty or factor_exposures is None or factor_exposures.empty:
        return pd.DataFrame(columns=columns)
    exposure = factor_exposures.copy()
    exposure.index = exposure.index.astype(str)
    factors = sorted(set(exposure.columns.astype(str)) & set(factor_returns.get("factor", pd.Series(dtype=str)).astype(str)))
    if not factors or "date" not in factor_returns.columns or "factor_return" not in factor_returns.columns:
        return pd.DataFrame(columns=columns)
    weighted = exposure.reindex(columns=factors).apply(pd.to_numeric, errors="coerce").fillna(0.0)
    factor_rows: list[dict[str, object]] = []
    factor_frame = factor_returns.copy()
    factor_frame["date"] = pd.to_datetime(factor_frame["date"], errors="coerce")
    factor_frame["factor"] = factor_frame["factor"].astype(str)
    factor_frame["factor_return"] = pd.to_numeric(factor_frame["factor_return"], errors="coerce")
    factor_frame = factor_frame.dropna(subset=["date", "factor_return"])
    for factor in factors:
        series = factor_frame.loc[factor_frame["factor"].eq(factor)].set_index("date")["factor_return"]
        joined = pd.concat([series, daily["wealth"].shift(1)], axis=1, join="inner").dropna()
        exposure_value = float(weighted[factor].mean())
        contribution = float((joined.iloc[:, 0] * joined.iloc[:, 1] * exposure_value).sum()) if not joined.empty else 0.0
        factor_rows.append({"factor": factor, "contribution": contribution, "share": None, "observations": int(len(joined)), "status": "available" if len(joined) >= 3 else "partial"})
    result = pd.DataFrame(factor_rows, columns=columns)
    total = float(result["contribution"].sum()) if not result.empty else 0.0
    if total:
        result["share"] = result["contribution"] / total
    return result


def _currency_attribution(asset_summary: pd.DataFrame, allocation: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["currency", "contribution", "share", "status"]
    if asset_summary.empty or allocation is None or "currency" not in allocation.columns:
        return pd.DataFrame(columns=columns)
    mapping = allocation[["etf_id", "currency"]].copy()
    mapping["etf_id"] = mapping["etf_id"].astype(str).str.strip()
    mapping["currency"] = mapping["currency"].fillna("").astype(str).str.strip()
    joined = asset_summary.merge(mapping, left_on="instrument_id", right_on="etf_id", how="left")
    joined["currency"] = joined["currency"].where(joined["currency"].ne(""), "unavailable")
    result = joined.groupby("currency", sort=True, as_index=False)["contribution"].sum()
    total = float(result["contribution"].sum()) if not result.empty else 0.0
    result["share"] = result["contribution"] / total if total else np.nan
    result["status"] = "instrument_bucket_proxy"
    return result[columns]


def _cost_attribution(costs: pd.DataFrame | None) -> tuple[pd.DataFrame, float | None, float | None]:
    columns = ["category", "amount", "status"]
    if costs is None or costs.empty:
        return pd.DataFrame(columns=columns), 0.0, 0.0
    frame = costs.copy()
    category = next((name for name in ("category", "cost_type", "type") if name in frame.columns), None)
    amount = next((name for name in ("amount", "cost", "cost_eur") if name in frame.columns), None)
    if category is None or amount is None:
        return pd.DataFrame(columns=columns), None, None
    frame["category"] = frame[category].fillna("unclassified").astype(str).str.strip().replace("", "unclassified")
    raw_amounts = frame[amount]
    if raw_amounts.map(lambda value: isinstance(value, (bool, np.bool_))).any():
        return pd.DataFrame(columns=columns), None, None
    numeric_amounts = pd.to_numeric(raw_amounts, errors="coerce")
    if numeric_amounts.isna().any() or not np.isfinite(numeric_amounts).all():
        return pd.DataFrame(columns=columns), None, None
    frame["amount"] = numeric_amounts.abs()
    result = frame.groupby("category", sort=True, as_index=False)["amount"].sum()
    result["status"] = "explicit"
    tax_total = float(result.loc[result["category"].str.casefold().str.contains("tax"), "amount"].sum())
    return result[columns], float(result["amount"].sum()), tax_total


def _costs_in_declared_window(
    costs: pd.DataFrame | None,
    reference_context: object | None,
) -> tuple[pd.DataFrame | None, str]:
    """Validate every populated cost chronology field against one canonical window."""

    if costs is None or costs.empty:
        return costs, "unavailable"
    resolution = getattr(reference_context, "resolution", None)
    declaration = getattr(resolution, "declaration", None)
    if declaration is None:
        return costs, "available"
    try:
        start = pd.Timestamp(declaration.start_date, tz="UTC")
        end = pd.Timestamp(declaration.end_date, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        decision = pd.Timestamp(declaration.decision_time)
        if decision.tzinfo is None:
            return None, "invalid"
        decision = decision.tz_convert("UTC")
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None, "invalid"
    if start > end or decision < start:
        return None, "invalid"

    effective_fields = ("effective_at", "date", "as_of", "as_of_date", "trade_date", "transaction_date")
    knowledge_fields = ("known_at", "available_at", "retrieved_at", "imported_at", "published_at")
    selected: list[object] = []
    for index, row in costs.iterrows():
        effective, effective_valid = _cost_chronology(row, effective_fields, aliases_must_match=True)
        known_at, knowledge_valid = _cost_chronology(
            row,
            knowledge_fields,
            aliases_must_match=True,
        )
        if effective is None or not effective_valid or not knowledge_valid:
            return None, "invalid"
        if effective < start or effective > end or effective > decision:
            continue
        if known_at is not None and known_at > decision:
            continue
        selected.append(index)
    if not selected:
        return costs.iloc[0:0].copy(), "excluded_outside_window"
    return costs.loc[selected].copy(), "available"


def _cashflows_in_declared_window(
    cashflows: pd.DataFrame | None,
    reference_context: object | None,
) -> tuple[pd.DataFrame | None, str]:
    """Validate every populated cashflow chronology field against the canonical window."""

    if cashflows is None or cashflows.empty:
        return cashflows, "unavailable"
    resolution = getattr(reference_context, "resolution", None)
    declaration = getattr(resolution, "declaration", None)
    if declaration is None:
        return cashflows, "available"
    try:
        start = pd.Timestamp(declaration.start_date, tz="UTC")
        end = pd.Timestamp(declaration.end_date, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        decision = pd.Timestamp(declaration.decision_time)
        if decision.tzinfo is None:
            return None, "invalid"
        decision = decision.tz_convert("UTC")
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None, "invalid"
    if start > end or decision < start:
        return None, "invalid"

    effective_fields = ("effective_at", "date", "as_of", "as_of_date", "trade_date", "transaction_date")
    knowledge_fields = ("known_at", "available_at", "retrieved_at", "imported_at", "published_at")
    selected: list[object] = []
    excluded = False
    for index, row in cashflows.iterrows():
        effective, effective_valid = _cost_chronology(row, effective_fields, aliases_must_match=True)
        known_at, knowledge_valid = _cost_chronology(
            row,
            knowledge_fields,
            aliases_must_match=True,
        )
        if effective is None or not effective_valid or not knowledge_valid:
            return None, "invalid"
        if effective < start or effective > end or effective > decision or (known_at is not None and known_at > decision):
            excluded = True
            continue
        selected.append(index)
    if excluded:
        return cashflows.loc[selected].copy(), "excluded_outside_window"
    return cashflows.loc[selected].copy(), "available"


def _cost_chronology(
    row: pd.Series,
    fields: tuple[str, ...],
    *,
    aliases_must_match: bool = False,
) -> tuple[pd.Timestamp | None, bool]:
    populated: list[object] = []
    for field in fields:
        if field not in row:
            continue
        value = row.get(field)
        try:
            missing = pd.isna(value)
        except (TypeError, ValueError):
            return None, False
        if not isinstance(missing, (bool, np.bool_)):
            return None, False
        if bool(missing):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        populated.append(value)
    if not populated:
        return None, True
    parsed_values: list[pd.Timestamp] = []
    for value in populated:
        if isinstance(value, (bool, int, float, np.number)):
            return None, False
        text = str(value).strip()
        try:
            parsed = pd.Timestamp(value)
            if pd.isna(parsed):
                return None, False
            if parsed.tzinfo is None:
                parsed = parsed.tz_localize("UTC")
            parsed = parsed.tz_convert("UTC")
            if len(text) == 10 and text[4] == "-" and text[7] == "-":
                parsed = parsed.normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        except (TypeError, ValueError, OverflowError):
            return None, False
        parsed_values.append(parsed)
    if aliases_must_match and len(set(parsed_values)) != 1:
        return None, False
    return max(parsed_values), True


def _benchmark_attribution(
    total_return: float | None,
    benchmark: pd.DataFrame | None,
    dates: Iterable[object],
    *,
    portfolio_returns: pd.Series | None = None,
) -> pd.DataFrame:
    columns = ["benchmark", "return", "active_return", "observations", "status"]
    if benchmark is None or benchmark.empty:
        return pd.DataFrame(columns=columns)
    frame = benchmark.copy()
    name = next((column for column in ("benchmark", "benchmark_id", "id") if column in frame.columns), None)
    value = next((column for column in ("return", "benchmark_return") if column in frame.columns), None)
    if value is None:
        return pd.DataFrame(columns=columns)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True) if "date" in frame.columns else pd.NaT
    frame[value] = pd.to_numeric(frame[value], errors="coerce")
    if portfolio_returns is not None:
        portfolio = pd.to_numeric(portfolio_returns, errors="coerce")
        portfolio.index = pd.to_datetime(portfolio.index, errors="coerce", utc=True)
        portfolio = portfolio.rename("portfolio_return").dropna()
    else:
        portfolio = pd.Series(dtype=float, name="portfolio_return")
    result_rows: list[dict[str, object]] = []
    for label, group in frame.assign(_label=frame[name].fillna("benchmark") if name else "benchmark").groupby("_label", sort=True):
        benchmark_frame = group.set_index("date")[[value]].rename(columns={value: "benchmark_return"})
        joined = pd.concat([portfolio, benchmark_frame], axis=1, join="inner").dropna()
        if len(joined) < 2:
            result_rows.append(
                {
                    "benchmark": str(label),
                    "return": None,
                    "active_return": None,
                    "observations": int(len(joined)),
                    "status": "N/A",
                }
            )
            continue
        portfolio_window_return = float((1.0 + joined["portfolio_return"]).prod() - 1.0)
        benchmark_return = float((1.0 + joined["benchmark_return"]).prod() - 1.0)
        result_rows.append(
            {
                "benchmark": str(label),
                "return": benchmark_return,
                "active_return": float(portfolio_window_return - benchmark_return),
                "observations": int(len(joined)),
                "status": "available",
            }
        )
    return pd.DataFrame(result_rows, columns=columns)


def _money_weighted_return(wealth: pd.Series, dates: Iterable[object], cashflows: pd.DataFrame | None) -> tuple[float | None, str]:
    if cashflows is None or cashflows.empty or wealth.empty or "amount" not in cashflows.columns:
        return None, "unavailable_without_external_cashflows"
    flow = cashflows.copy()
    if "date" not in flow.columns:
        return None, "unavailable_without_dated_cashflows"
    if flow["amount"].map(lambda value: isinstance(value, (bool, np.bool_))).any():
        return None, "unavailable_without_valid_cashflows"
    flow["date"] = pd.to_datetime(flow["date"], errors="coerce", utc=True)
    flow["amount"] = pd.to_numeric(flow["amount"], errors="coerce")
    if flow[["date", "amount"]].isna().any().any() or not np.isfinite(flow["amount"]).all():
        return None, "unavailable_without_valid_cashflows"
    start = pd.Timestamp(next(iter(dates)))
    end = pd.Timestamp(wealth.index[-1])
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    dated = [(start, 0.0)] + [(pd.Timestamp(row.date), -float(row.amount)) for row in flow.itertuples()] + [(end, float(wealth.iloc[-1]))]
    dated = sorted(dated, key=lambda row: row[0])
    return _xirr(dated), "available" if len(dated) >= 3 else "partial"


def _xirr(cashflows: list[tuple[pd.Timestamp, float]]) -> float | None:
    if not cashflows or not any(value < 0 for _, value in cashflows) or not any(value > 0 for _, value in cashflows):
        return None
    origin = cashflows[0][0]

    def npv(rate: float) -> float:
        return sum(value / (1.0 + rate) ** ((date - origin).days / 365.25) for date, value in cashflows)

    low, high = -0.9999, 10.0
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(100):
        middle = (low + high) / 2.0
        value = npv(middle)
        if abs(value) < 1e-10:
            return float(middle)
        if npv(low) * value <= 0:
            high = middle
        else:
            low = middle
    return float((low + high) / 2.0)


def _decision_attribution(decisions: pd.DataFrame | None, returns: pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    columns = ["instrument_id", "model_effect", "approval_effect", "execution_effect", "status"]
    if decisions is None or decisions.empty or "instrument_id" not in decisions.columns:
        return pd.DataFrame(columns=columns)
    frame = decisions.copy()
    frame["instrument_id"] = frame["instrument_id"].astype(str).str.strip()
    mean_returns = returns.mean(axis=0)
    rows: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        instrument = str(row.get("instrument_id", ""))
        realised = _finite(row.get("realised_weight"))
        approved = _finite(row.get("approved_weight"))
        model = _finite(row.get("model_weight"))
        if not instrument or realised is None or approved is None or model is None:
            continue
        return_value = float(mean_returns.get(instrument, 0.0))
        rows.append({"instrument_id": instrument, "model_effect": (approved - model) * return_value, "approval_effect": (realised - approved) * return_value, "execution_effect": (weights.get(instrument, 0.0) - realised) * return_value, "status": "descriptive_proxy"})
    return pd.DataFrame(rows, columns=columns)


def _warnings(returns: pd.DataFrame, allocation: pd.DataFrame | None, factors: pd.DataFrame, currencies: pd.DataFrame, costs: pd.DataFrame | None, cashflows: pd.DataFrame | None, decisions: pd.DataFrame | None) -> list[str]:
    warnings: list[str] = []
    if returns.isna().any().any():
        warnings.append("missing_adjusted_price_cells_excluded")
    if allocation is None or "date" not in allocation.columns:
        warnings.append("allocation_snapshot_not_dated")
    if factors.empty:
        warnings.append("factor_attribution_unavailable")
    if currencies.empty:
        warnings.append("currency_attribution_unavailable")
    elif (currencies["status"] == "instrument_bucket_proxy").any():
        warnings.append("currency_is_instrument_bucket_proxy_without_fx_series")
    if costs is None or costs.empty:
        warnings.append("explicit_costs_unavailable")
    if cashflows is None or cashflows.empty:
        warnings.append("external_cashflows_unavailable_for_money_weighted_return")
    if decisions is None or decisions.empty:
        warnings.append("decision_journal_link_unavailable")
    return warnings


def _factor_residual(total_return: float | None, factors: pd.DataFrame) -> float | None:
    if total_return is None or factors.empty:
        return None
    return float(total_return - pd.to_numeric(factors["contribution"], errors="coerce").sum())


def _frame_status(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "unavailable"
    if "status" in frame.columns and frame["status"].astype(str).eq("partial").any():
        return "partial"
    return "available"


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = ["ATTRIBUTION_MODEL_VERSION", "build_performance_attribution"]
