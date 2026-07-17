"""Transparent, local-first multi-factor risk estimation.

The model deliberately uses public, inspectable descriptors and adjusted-price
returns.  It is an evidence model for research and portfolio review; it never
creates execution authority or silently fills missing exposures.
"""

from __future__ import annotations

from collections.abc import Iterable
import math

import numpy as np
import pandas as pd


FACTOR_MODEL_VERSION = "factor_risk.v1"
ANNUALISATION_FACTOR = 252.0
NUMERIC_FACTORS = ("size", "value", "momentum", "quality", "investment", "low_volatility")
LOOKTHROUGH_DIMENSIONS = ("industry", "country", "currency")
_EXPOSURE_COLUMNS = (
    "instrument_id",
    "factor",
    "raw_value",
    "exposure",
    "descriptor",
    "source",
    "coverage",
)


def build_factor_exposures(
    allocation: pd.DataFrame,
    latest_features: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build inspectable numeric and categorical exposures.

    Numeric descriptors are robustly winsorised and standardised across the
    supplied universe.  Category exposures use explicit one-hot weights.  A
    missing descriptor remains missing and is reported in model coverage.
    """

    columns = list(_EXPOSURE_COLUMNS)
    if allocation is None or allocation.empty or "etf_id" not in allocation.columns:
        return pd.DataFrame(columns=columns)
    allocation_frame = allocation.copy()
    feature_frame = _latest_feature_rows(latest_features)
    if not feature_frame.empty:
        feature_frame = feature_frame.rename(columns={"etf_id": "instrument_id"})
        allocation_frame = allocation_frame.merge(feature_frame, left_on="etf_id", right_on="instrument_id", how="left", suffixes=("", "_feature"))
    lookthrough = _lookthrough_map(holdings)
    rows: list[dict[str, object]] = []
    for _, item in allocation_frame.iterrows():
        instrument_id = str(item.get("etf_id") or "").strip()
        if not instrument_id:
            continue
        numeric_values = {
            "size": _positive_log_value(item.get("market_value_eur")),
            "value": _first_number(item, ("value_score_10", "value_score", "stock_value_score")),
            "momentum": _first_number(item, ("momentum_120d", "momentum_60d", "return_60d_log")),
            "quality": _first_number(item, ("quality_score_10", "quality_score", "stock_quality_score")),
            "investment": _first_number(item, ("investment_score_10", "investment_score")),
            "low_volatility": _negative_number(_first_number(item, ("vol_60d_ann", "vol_120d_ann", "ewma_vol_ann"))),
        }
        rows.append(_exposure_row(instrument_id, "market", 1.0, "market_presence", "allocation", 1.0))
        for factor, value in numeric_values.items():
            rows.append(_exposure_row(instrument_id, factor, value, _descriptor_name(factor), _numeric_source(item, factor), float(pd.notna(value))))

        for dimension, allocation_column in (("industry", "sector"), ("country", "region"), ("currency", "currency")):
            mapped = lookthrough.get(instrument_id, {}).get(dimension, {})
            if mapped:
                for label, weight in mapped.items():
                    rows.append(_exposure_row(instrument_id, f"{dimension}:{label}", weight, dimension, "holdings_lookthrough", min(1.0, sum(mapped.values()))))
                continue
            label = _clean_label(item.get(allocation_column))
            if label:
                rows.append(_exposure_row(instrument_id, f"{dimension}:{label}", 1.0, allocation_column, "allocation_metadata", 1.0))

    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return pd.DataFrame(columns=columns)
    for factor in NUMERIC_FACTORS:
        mask = frame["factor"].eq(factor) & frame["raw_value"].notna()
        frame.loc[mask, "exposure"] = _robust_standardise(frame.loc[mask, "raw_value"])
    frame["coverage"] = pd.to_numeric(frame["coverage"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    return frame.sort_values(["factor", "instrument_id"], kind="stable").reset_index(drop=True)


def build_factor_risk_report(
    prices: pd.DataFrame,
    allocation: pd.DataFrame,
    latest_features: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    *,
    public_factors: pd.DataFrame | None = None,
    window: int = 252,
) -> dict[str, object]:
    """Estimate factor, specific and portfolio risk with visible limitations."""

    exposures = build_factor_exposures(allocation, latest_features, holdings)
    returns = _return_matrix(prices, window=window)
    empty_factor_returns = pd.DataFrame(columns=["date", "factor", "factor_return", "standard_error", "sample_count", "method"])
    empty_contributions = pd.DataFrame(columns=["factor", "portfolio_exposure", "variance_contribution", "variance_share"])
    empty_specific = pd.DataFrame(columns=["instrument_id", "specific_vol_ann", "sample_count", "coverage"])
    coverage = _coverage_report(prices, returns, exposures, holdings)
    if returns.empty or exposures.empty:
        return _unavailable_report(exposures, coverage, empty_factor_returns, empty_contributions, empty_specific, "Adjusted-price returns or transparent factor descriptors are unavailable.")

    matrix = exposures.pivot_table(index="instrument_id", columns="factor", values="exposure", aggfunc="sum", sort=True)
    matrix = matrix.reindex(index=sorted(set(returns.columns) & set(matrix.index)))
    if matrix.empty or len(matrix.index) < 2:
        report = _unavailable_report(exposures, coverage, empty_factor_returns, empty_contributions, empty_specific, "At least two instruments with adjusted-price history and descriptors are required.")
        report["diagnostics"]["excluded_factors"] = {}
        return report

    selected, excluded = _select_factors(matrix, returns)
    if not selected:
        return _unavailable_report(exposures, coverage, empty_factor_returns, empty_contributions, empty_specific, "No factor has enough cross-sectional coverage for estimation.") | {"excluded_factors": excluded}
    factor_returns, residuals, fit_diagnostics = _fit_cross_sectional(returns, matrix[selected])
    if factor_returns.empty:
        report = _unavailable_report(exposures, coverage, factor_returns, empty_contributions, empty_specific, "Cross-sectional factor returns are unavailable for the selected sample.")
        report["diagnostics"].update({"excluded_factors": excluded, "fit": fit_diagnostics})
        return report
    factor_covariance, covariance_diagnostics = _factor_covariance(factor_returns, selected)
    specific = _specific_risk(residuals, returns)
    portfolio_contributions, instrument_contributions, portfolio = _portfolio_decomposition(allocation, matrix[selected], factor_covariance, specific)
    baseline_beta = _simple_beta_baseline(returns)
    stability = _stability_report(factor_returns)
    public_validation = validate_public_factor_series(factor_returns, public_factors)
    warnings = _warnings(coverage, excluded, specific, public_validation, covariance_diagnostics)
    status = "available" if not warnings else "partial"
    diagnostics = {
        "model_version": FACTOR_MODEL_VERSION,
        "method": "iteratively reweighted cross-sectional least squares",
        "window": int(window),
        "winsorisation": "robust median/MAD; clipped at +/-3",
        "selected_factors": selected,
        "excluded_factors": excluded,
        "fit": fit_diagnostics,
        "covariance": covariance_diagnostics,
        "stability": stability,
        "public_factor_validation": public_validation,
        "baseline_beta": baseline_beta,
        "warnings": warnings,
    }
    return {
        "status": status,
        "message": "Transparent factor and specific-risk evidence; execution_allowed=false.",
        "model_version": FACTOR_MODEL_VERSION,
        "execution_allowed": False,
        "factor_exposures": exposures,
        "exposure_matrix": matrix,
        "factor_returns": factor_returns,
        "factor_covariance": factor_covariance,
        "specific_risk": specific,
        "portfolio_contributions": portfolio_contributions,
        "instrument_contributions": instrument_contributions,
        "portfolio": portfolio,
        "coverage": coverage,
        "diagnostics": diagnostics,
        "warnings": warnings,
    }


def validate_public_factor_series(factor_returns: pd.DataFrame, public_factors: pd.DataFrame | None) -> dict[str, object]:
    """Compare supplied public factor returns without fetching or trusting them."""

    if public_factors is None or public_factors.empty:
        return {"status": "unavailable", "message": "No public factor validation series supplied.", "rows": []}
    model = _factor_return_wide(factor_returns)
    public = _public_factor_wide(public_factors)
    common = sorted(set(model.columns) & set(public.columns))
    if not common:
        return {"status": "unavailable", "message": "Public factor series has no matching factor names.", "rows": []}
    rows: list[dict[str, object]] = []
    for factor in common:
        joined = pd.concat([model[factor], public[factor]], axis=1, join="inner").dropna()
        joined.columns = ["model", "public"]
        if len(joined) < 3:
            continue
        rows.append(
            {
                "factor": factor,
                "observations": int(len(joined)),
                "correlation": _safe_corr(joined["model"], joined["public"]),
                "mean_absolute_error": float((joined["model"] - joined["public"]).abs().mean()),
            }
        )
    return {"status": "available" if rows else "unavailable", "message": "Public factor comparison is descriptive validation only.", "rows": rows}


def _exposure_row(instrument_id: str, factor: str, value: object, descriptor: str, source: str, coverage: float) -> dict[str, object]:
    numeric = _numeric_or_nan(value)
    return {"instrument_id": instrument_id, "factor": factor, "raw_value": numeric, "exposure": numeric, "descriptor": descriptor, "source": source, "coverage": coverage}


def _latest_feature_rows(features: pd.DataFrame | None) -> pd.DataFrame:
    if features is None or features.empty or "etf_id" not in features.columns:
        return pd.DataFrame()
    frame = features.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.sort_values(["etf_id", "date"], kind="stable")
    return frame.groupby("etf_id", as_index=False, sort=True).tail(1).reset_index(drop=True)


def _lookthrough_map(holdings: pd.DataFrame | None) -> dict[str, dict[str, dict[str, float]]]:
    result: dict[str, dict[str, dict[str, float]]] = {}
    if holdings is None or holdings.empty:
        return result
    id_column = "instrument_id" if "instrument_id" in holdings.columns else "etf_id" if "etf_id" in holdings.columns else None
    if id_column is None or "weight" not in holdings.columns:
        return result
    frame = holdings.copy()
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce")
    for instrument_id, group in frame.dropna(subset=[id_column, "weight"]).groupby(id_column, sort=True):
        dimensions: dict[str, dict[str, float]] = {}
        for dimension, column in (("industry", "sector"), ("country", "region"), ("currency", "currency")):
            if column not in group.columns:
                continue
            labels = group[column].map(_clean_label)
            valid = group.loc[labels.ne("")].copy()
            if valid.empty:
                continue
            valid["label"] = labels.loc[valid.index]
            weighted = valid.groupby("label", sort=True)["weight"].sum()
            dimensions[dimension] = {str(label): float(weight) for label, weight in weighted.items() if float(weight) > 0}
        if dimensions:
            result[str(instrument_id)] = dimensions
    return result


def _descriptor_name(factor: str) -> str:
    return {"low_volatility": "negative_realised_volatility"}.get(factor, factor)


def _numeric_source(item: pd.Series, factor: str) -> str:
    if factor in {"momentum", "low_volatility"} and any(column in item.index for column in ("momentum_120d", "momentum_60d", "vol_60d_ann", "vol_120d_ann", "ewma_vol_ann")):
        return "adjusted_price_features"
    if factor == "size" and pd.notna(item.get("market_value_eur")):
        return "portfolio_market_value"
    return "fundamental_descriptors" if factor in {"value", "quality", "investment"} else "unavailable"


def _positive_log_value(value: object) -> float | None:
    number = _numeric_or_nan(value)
    return None if not np.isfinite(number) or number <= 0 else float(np.log1p(number))


def _negative_number(value: object) -> float | None:
    number = _numeric_or_nan(value)
    return None if not np.isfinite(number) else -number


def _first_number(item: pd.Series, columns: Iterable[str]) -> float | None:
    for column in columns:
        value = _numeric_or_nan(item.get(column))
        if np.isfinite(value):
            return value
    return None


def _numeric_or_nan(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _clean_label(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _robust_standardise(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    median = float(numeric.median())
    mad = float((numeric - median).abs().median())
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= 1e-12:
        scale = float(numeric.std(ddof=0))
    if not np.isfinite(scale) or scale <= 1e-12:
        return pd.Series(0.0, index=values.index)
    return ((numeric - median) / scale).clip(-3.0, 3.0)


def _return_matrix(prices: pd.DataFrame, *, window: int) -> pd.DataFrame:
    if prices is None or prices.empty or not {"date", "etf_id", "adjusted_close"}.issubset(prices.columns):
        return pd.DataFrame()
    frame = prices[["date", "etf_id", "adjusted_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna(subset=["date", "etf_id", "adjusted_close"])
    frame = frame[frame["adjusted_close"] > 0]
    if frame.empty:
        return pd.DataFrame()
    pivot = frame.pivot_table(index="date", columns="etf_id", values="adjusted_close", aggfunc="last").sort_index()
    returns = np.log(pivot / pivot.shift(1)).replace([np.inf, -np.inf], np.nan).dropna(how="all")
    if window > 0:
        returns = returns.tail(int(window))
    return returns.dropna(axis=1, how="all")


def _select_factors(matrix: pd.DataFrame, returns: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    available = [column for column in matrix.columns if column == "market" or column in NUMERIC_FACTORS or str(column).split(":", 1)[0] in LOOKTHROUGH_DIMENSIONS]
    selected: list[str] = ["market"] if "market" in available else []
    excluded: dict[str, str] = {}
    candidates = [column for column in available if column != "market"]
    for factor in candidates:
        values = matrix[factor].dropna()
        if len(values) < 3:
            excluded[str(factor)] = "fewer_than_three_exposures"
            continue
        if values.nunique(dropna=True) < 2:
            excluded[str(factor)] = "constant_exposure"
            continue
        proposed = [*selected, factor]
        valid_instruments = matrix[proposed].dropna().index.intersection(returns.columns)
        minimum = max(5, 2 * len(proposed))
        if len(valid_instruments) < minimum:
            excluded[str(factor)] = f"insufficient_cross_section:{len(valid_instruments)}<{minimum}"
            continue
        selected.append(str(factor))
    return selected, excluded


def _fit_cross_sectional(returns: pd.DataFrame, exposures: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    factor_names = list(exposures.columns)
    factor_rows: list[dict[str, object]] = []
    residual_rows: list[dict[str, object]] = []
    dates = sorted(returns.index)
    usable_dates = 0
    for dt in dates:
        joined = pd.concat([returns.loc[[dt]].T.rename(columns={dt: "observed_return"}), exposures], axis=1, join="inner")
        joined = joined.dropna(subset=["observed_return", *factor_names])
        minimum = max(5, 2 * len(factor_names))
        if len(joined) < minimum:
            continue
        beta, standard_error, residual = _robust_fit(joined[factor_names].to_numpy(float), joined["observed_return"].to_numpy(float))
        usable_dates += 1
        for index, factor in enumerate(factor_names):
            factor_rows.append({"date": pd.Timestamp(dt).date(), "factor": factor, "factor_return": float(beta[index]), "standard_error": float(standard_error[index]), "sample_count": int(len(joined)), "method": "robust_cross_sectional"})
        fitted = joined[factor_names].to_numpy(float) @ beta
        for instrument_id, observed, fitted_value, residual_value in zip(joined.index, joined["observed_return"], fitted, residual):
            residual_rows.append({"date": pd.Timestamp(dt).date(), "instrument_id": str(instrument_id), "observed_return": float(observed), "fitted_return": float(fitted_value), "residual": float(residual_value)})
    factor_columns = ["date", "factor", "factor_return", "standard_error", "sample_count", "method"]
    residual_columns = ["date", "instrument_id", "observed_return", "fitted_return", "residual"]
    return pd.DataFrame(factor_rows, columns=factor_columns), pd.DataFrame(residual_rows, columns=residual_columns), {"candidate_dates": len(dates), "usable_dates": usable_dates, "factor_count": len(factor_names)}


def _robust_fit(x_values: np.ndarray, y_values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    weights = np.ones(len(y_values), dtype=float)
    beta = np.linalg.lstsq(x_values, y_values, rcond=None)[0]
    for _ in range(6):
        root_weights = np.sqrt(weights)
        beta = np.linalg.lstsq(x_values * root_weights[:, None], y_values * root_weights, rcond=None)[0]
        residual = y_values - x_values @ beta
        scale = 1.4826 * float(np.median(np.abs(residual - np.median(residual))))
        if not np.isfinite(scale) or scale <= 1e-12:
            break
        limit = 1.345 * scale
        absolute = np.abs(residual)
        weights = np.where(absolute <= limit, 1.0, limit / np.maximum(absolute, 1e-12))
    residual = y_values - x_values @ beta
    gram = x_values.T @ (weights[:, None] * x_values)
    covariance = np.linalg.pinv(gram)
    degrees_of_freedom = max(1, len(y_values) - x_values.shape[1])
    variance = float(np.sum(weights * residual**2) / degrees_of_freedom)
    standard_error = np.sqrt(np.maximum(0.0, np.diag(covariance) * variance))
    return beta, standard_error, residual


def _factor_covariance(factor_returns: pd.DataFrame, selected: list[str]) -> tuple[pd.DataFrame, dict[str, object]]:
    wide = _factor_return_wide(factor_returns).reindex(columns=selected)
    covariance = wide.cov(min_periods=2).reindex(index=selected, columns=selected).fillna(0.0).to_numpy(float)
    covariance = (covariance + covariance.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    floor = max(float(np.nanmax(np.diag(covariance))) * 1e-8 if covariance.size else 0.0, 1e-12)
    regularised = bool(np.any(eigenvalues < floor))
    eigenvalues = np.maximum(eigenvalues, floor)
    covariance = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    diagnostics = {
        "observations": int(len(wide)),
        "condition_number": _condition_number(covariance),
        "minimum_eigenvalue": float(np.min(eigenvalues)) if len(eigenvalues) else None,
        "regularised": regularised,
        "annualised": False,
    }
    return pd.DataFrame(covariance, index=selected, columns=selected), diagnostics


def _specific_risk(residuals: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    ids = sorted(map(str, returns.columns))
    rows: list[dict[str, object]] = []
    for instrument_id in ids:
        values = residuals.loc[residuals["instrument_id"].eq(instrument_id), "residual"] if not residuals.empty else pd.Series(dtype=float)
        values = pd.to_numeric(values, errors="coerce").dropna()
        volatility = float(values.std(ddof=1) * np.sqrt(ANNUALISATION_FACTOR)) if len(values) >= 2 else float("nan")
        rows.append({"instrument_id": instrument_id, "specific_vol_ann": volatility, "sample_count": int(len(values)), "coverage": float(len(values) / max(1, len(returns)))})
    return pd.DataFrame(rows)


def _portfolio_decomposition(
    allocation: pd.DataFrame,
    exposures: pd.DataFrame,
    covariance: pd.DataFrame,
    specific: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    factor_names = list(covariance.columns)
    instruments = list(exposures.index)
    weights = _weights(allocation).reindex(instruments).fillna(0.0).to_numpy(float)
    matrix = exposures.reindex(index=instruments, columns=factor_names).fillna(0.0).to_numpy(float)
    portfolio_exposure = weights @ matrix
    annual_covariance = covariance.to_numpy(float) * ANNUALISATION_FACTOR
    factor_variance_contributions = portfolio_exposure * (annual_covariance @ portfolio_exposure)
    specific_lookup = specific.set_index("instrument_id")["specific_vol_ann"] if not specific.empty else pd.Series(dtype=float)
    specific_vol = specific_lookup.reindex(instruments).fillna(0.0).to_numpy(float)
    specific_instrument_contribution = weights**2 * specific_vol**2
    factor_variance = float(np.sum(factor_variance_contributions))
    specific_variance = float(np.sum(specific_instrument_contribution))
    total_variance = max(0.0, factor_variance + specific_variance)
    denominator = total_variance if total_variance > 0 else 1.0
    factor_rows = [
        {"factor": factor, "portfolio_exposure": float(portfolio_exposure[index]), "variance_contribution": float(factor_variance_contributions[index]), "variance_share": float(factor_variance_contributions[index] / denominator)}
        for index, factor in enumerate(factor_names)
    ]
    factor_rows.append({"factor": "specific", "portfolio_exposure": None, "variance_contribution": specific_variance, "variance_share": specific_variance / denominator})
    instrument_covariance_contribution = weights * (matrix @ (annual_covariance @ portfolio_exposure))
    instrument_variance_contribution = instrument_covariance_contribution + specific_instrument_contribution
    instrument_rows = [
        {"instrument_id": instrument_id, "weight": float(weights[index]), "variance_contribution": float(instrument_variance_contribution[index]), "variance_share": float(instrument_variance_contribution[index] / denominator)}
        for index, instrument_id in enumerate(instruments)
    ]
    return pd.DataFrame(factor_rows), pd.DataFrame(instrument_rows).sort_values("variance_share", ascending=False).reset_index(drop=True), {
        "annualised_volatility": float(np.sqrt(total_variance)),
        "factor_variance": factor_variance,
        "specific_variance": specific_variance,
        "total_variance": total_variance,
        "factor_share": factor_variance / denominator,
        "specific_share": specific_variance / denominator,
        "component_share_sum": float(sum(row["variance_share"] for row in factor_rows)),
    }


def _weights(allocation: pd.DataFrame) -> pd.Series:
    if allocation is None or allocation.empty or "etf_id" not in allocation.columns:
        return pd.Series(dtype=float)
    column = "current_weight" if "current_weight" in allocation.columns else "target_weight" if "target_weight" in allocation.columns else None
    if column is None:
        return pd.Series(0.0, index=allocation["etf_id"].astype(str), dtype=float)
    values = pd.to_numeric(allocation[column], errors="coerce").fillna(0.0)
    return pd.Series(values.to_numpy(float), index=allocation["etf_id"].astype(str)).groupby(level=0).sum()


def _simple_beta_baseline(returns: pd.DataFrame) -> list[dict[str, object]]:
    if returns.empty:
        return []
    market = returns.mean(axis=1, skipna=True)
    variance = float(market.var(ddof=1))
    rows: list[dict[str, object]] = []
    for instrument_id in returns.columns:
        joined = pd.concat([returns[instrument_id], market], axis=1).dropna()
        beta = float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / variance) if len(joined) >= 3 and variance > 0 else float("nan")
        rows.append({"instrument_id": str(instrument_id), "beta": beta, "observations": int(len(joined)), "method": "equal_weight_market_beta"})
    return rows


def _stability_report(factor_returns: pd.DataFrame) -> dict[str, object]:
    wide = _factor_return_wide(factor_returns)
    if len(wide) < 6:
        return {"status": "unavailable", "message": "At least six factor-return observations are required for split-sample stability."}
    midpoint = len(wide) // 2
    first, second = wide.iloc[:midpoint], wide.iloc[midpoint:]
    rows = []
    for factor in wide.columns:
        first_mean, second_mean = float(first[factor].mean()), float(second[factor].mean())
        rows.append({"factor": factor, "first_mean": first_mean, "second_mean": second_mean, "sign_agreement": bool(first_mean == 0 or second_mean == 0 or np.sign(first_mean) == np.sign(second_mean))})
    return {"status": "available", "split_index": midpoint, "rows": rows}


def _coverage_report(prices: pd.DataFrame, returns: pd.DataFrame, exposures: pd.DataFrame, holdings: pd.DataFrame | None) -> dict[str, object]:
    instrument_count = int(len(set(returns.columns) | set(exposures["instrument_id"].unique())))
    factor_coverage = []
    if not exposures.empty:
        for factor, group in exposures.groupby("factor", sort=True):
            factor_coverage.append({"factor": str(factor), "instrument_count": int(group["exposure"].notna().sum()), "coverage": float(group["exposure"].notna().mean()), "sources": sorted(set(group["source"].astype(str)))})
    return {
        "instrument_count": instrument_count,
        "price_observations": int(len(prices)) if prices is not None else 0,
        "return_observations": int(len(returns)),
        "return_instrument_count": int(len(returns.columns)),
        "factor_coverage": factor_coverage,
        "lookthrough": _lookthrough_coverage(holdings),
    }


def _lookthrough_coverage(holdings: pd.DataFrame | None) -> dict[str, object]:
    if holdings is None or holdings.empty:
        return {"status": "unavailable", "instrument_count": 0, "dimensions": {}}
    mapped = _lookthrough_map(holdings)
    dimensions: dict[str, dict[str, object]] = {}
    for dimension in LOOKTHROUGH_DIMENSIONS:
        coverage_values: list[float] = []
        for instrument, values in mapped.items():
            total = sum(values.get(dimension, {}).values())
            if total > 0:
                coverage_values.append(min(1.0, float(total)))
        dimensions[dimension] = {"instrument_count": len(coverage_values), "mean_coverage": float(np.mean(coverage_values)) if coverage_values else 0.0, "full_coverage": bool(coverage_values and min(coverage_values) >= 0.99)}
    return {"status": "available" if mapped else "unavailable", "instrument_count": len(mapped), "dimensions": dimensions}


def _warnings(coverage: dict[str, object], excluded: dict[str, str], specific: pd.DataFrame, public_validation: dict[str, object], covariance: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if int(coverage.get("return_observations", 0)) < 60:
        warnings.append("short_return_history")
    if excluded:
        warnings.append("some_factors_excluded_for_coverage_or_rank")
    if specific.empty or (pd.to_numeric(specific.get("sample_count", pd.Series(dtype=float)), errors="coerce") < 20).any():
        warnings.append("specific_risk_sample_sufficiency")
    if public_validation.get("status") != "available":
        warnings.append("public_factor_validation_unavailable")
    if covariance.get("regularised"):
        warnings.append("factor_covariance_regularised")
    lookthrough = coverage.get("lookthrough", {})
    if lookthrough.get("status") != "available":
        warnings.append("etf_lookthrough_unavailable")
    return warnings


def _unavailable_report(exposures: pd.DataFrame, coverage: dict[str, object], factor_returns: pd.DataFrame, contributions: pd.DataFrame, specific: pd.DataFrame, message: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "message": message,
        "model_version": FACTOR_MODEL_VERSION,
        "execution_allowed": False,
        "factor_exposures": exposures,
        "exposure_matrix": pd.DataFrame(),
        "factor_returns": factor_returns,
        "factor_covariance": pd.DataFrame(),
        "specific_risk": specific,
        "portfolio_contributions": contributions,
        "instrument_contributions": pd.DataFrame(),
        "portfolio": {"annualised_volatility": None, "component_share_sum": None},
        "coverage": coverage,
        "diagnostics": {"model_version": FACTOR_MODEL_VERSION, "warnings": [message]},
        "warnings": [message],
    }


def _factor_return_wide(factor_returns: pd.DataFrame) -> pd.DataFrame:
    if factor_returns is None or factor_returns.empty or not {"date", "factor", "factor_return"}.issubset(factor_returns.columns):
        return pd.DataFrame()
    return factor_returns.pivot_table(index="date", columns="factor", values="factor_return", aggfunc="last").sort_index()


def _public_factor_wide(public_factors: pd.DataFrame) -> pd.DataFrame:
    frame = public_factors.copy()
    if "date" not in frame.columns:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    if "factor" in frame.columns and "factor_return" in frame.columns:
        return frame.pivot_table(index="date", columns="factor", values="factor_return", aggfunc="last").sort_index()
    return frame.set_index("date").apply(pd.to_numeric, errors="coerce").sort_index()


def _safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    value = left.corr(right)
    return None if pd.isna(value) else float(value)


def _condition_number(matrix: np.ndarray) -> float | None:
    try:
        value = float(np.linalg.cond(matrix))
    except np.linalg.LinAlgError:
        return None
    return value if np.isfinite(value) else None


__all__ = [
    "ANNUALISATION_FACTOR",
    "FACTOR_MODEL_VERSION",
    "LOOKTHROUGH_DIMENSIONS",
    "NUMERIC_FACTORS",
    "build_factor_exposures",
    "build_factor_risk_report",
    "validate_public_factor_series",
]
