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
    returns = _return_matrix(prices)
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
    cost_attribution, cost_total, tax_total = _cost_attribution(costs)
    benchmark = _benchmark_attribution(
        total_return,
        _canonical_benchmark_returns(returns, reference_context),
        daily.index,
    )
    money_weighted, money_status = _money_weighted_return(wealth, daily.index, cashflows)
    decision_attribution = _decision_attribution(decisions, observed, portfolio_weights)
    warnings = _warnings(observed, allocation, factor_attribution, currency_attribution, costs, cashflows, decisions)
    reference_projection = (
        _unavailable_reference_projection()
        if reference_context is None
        else _reference_projection(reference_context)
    )
    if reference_projection.get("status") != "available":
        warnings.append("canonical_benchmark_cash_resolution_unavailable")
    net_return = None if total_return is None else float(total_return - cost_total - tax_total)

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
            "cost_status": "available" if costs is not None and not costs.empty else "unavailable",
            "tax_status": "available" if costs is not None and "tax" in costs.columns else "unavailable",
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
    projection = getattr(reference_context, "projection", None)
    if isinstance(projection, Mapping):
        return dict(projection)
    return _unavailable_reference_projection()


def _unavailable_reference_projection() -> dict[str, object]:
    return {
        "contract": "benchmark-reference-contract.v1",
        "status": "unavailable",
        "benchmark": {"id": None, "version": None, "status": "unavailable", "display": "N/A"},
        "cash": {"id": None, "version": None, "status": "unavailable", "display": "N/A"},
        "blockers": ["reference_resolution_unavailable"],
        "execution_allowed": False,
    }


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
    if not isinstance(benchmark_id, str) or benchmark_id not in returns.columns:
        return None
    series = returns[benchmark_id].dropna()
    if series.empty:
        return None
    return pd.DataFrame({
        "date": series.index,
        "benchmark": benchmark_id,
        "return": series.to_numpy(float),
    })


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


def _cost_attribution(costs: pd.DataFrame | None) -> tuple[pd.DataFrame, float, float]:
    columns = ["category", "amount", "status"]
    if costs is None or costs.empty:
        return pd.DataFrame(columns=columns), 0.0, 0.0
    frame = costs.copy()
    category = next((name for name in ("category", "cost_type", "type") if name in frame.columns), None)
    amount = next((name for name in ("amount", "cost", "cost_eur") if name in frame.columns), None)
    if category is None or amount is None:
        return pd.DataFrame(columns=columns), 0.0, 0.0
    frame["category"] = frame[category].fillna("unclassified").astype(str).str.strip().replace("", "unclassified")
    frame["amount"] = pd.to_numeric(frame[amount], errors="coerce").fillna(0.0).abs()
    result = frame.groupby("category", sort=True, as_index=False)["amount"].sum()
    result["status"] = "explicit"
    tax_total = float(result.loc[result["category"].str.casefold().str.contains("tax"), "amount"].sum())
    return result[columns], float(result["amount"].sum()), tax_total


def _benchmark_attribution(total_return: float | None, benchmark: pd.DataFrame | None, dates: Iterable[object]) -> pd.DataFrame:
    columns = ["benchmark", "return", "active_return", "observations", "status"]
    if benchmark is None or benchmark.empty:
        return pd.DataFrame(columns=columns)
    frame = benchmark.copy()
    name = next((column for column in ("benchmark", "benchmark_id", "id") if column in frame.columns), None)
    value = next((column for column in ("return", "benchmark_return") if column in frame.columns), None)
    if value is None:
        return pd.DataFrame(columns=columns)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce") if "date" in frame.columns else pd.NaT
    frame[value] = pd.to_numeric(frame[value], errors="coerce")
    result_rows: list[dict[str, object]] = []
    for label, group in frame.assign(_label=frame[name].fillna("benchmark") if name else "benchmark").groupby("_label", sort=True):
        values = group[value].dropna()
        benchmark_return = float((1.0 + values).prod() - 1.0) if not values.empty else None
        result_rows.append({"benchmark": str(label), "return": benchmark_return, "active_return": None if total_return is None or benchmark_return is None else float(total_return - benchmark_return), "observations": int(len(values)), "status": "available" if len(values) >= 2 else "partial"})
    return pd.DataFrame(result_rows, columns=columns)


def _money_weighted_return(wealth: pd.Series, dates: Iterable[object], cashflows: pd.DataFrame | None) -> tuple[float | None, str]:
    if cashflows is None or cashflows.empty or wealth.empty or "amount" not in cashflows.columns:
        return None, "unavailable_without_external_cashflows"
    flow = cashflows.copy()
    if "date" not in flow.columns:
        return None, "unavailable_without_dated_cashflows"
    flow["date"] = pd.to_datetime(flow["date"], errors="coerce")
    flow["amount"] = pd.to_numeric(flow["amount"], errors="coerce")
    flow = flow.dropna(subset=["date", "amount"])
    if flow.empty:
        return None, "unavailable_without_valid_cashflows"
    start = pd.Timestamp(next(iter(dates)))
    end = pd.Timestamp(wealth.index[-1])
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
