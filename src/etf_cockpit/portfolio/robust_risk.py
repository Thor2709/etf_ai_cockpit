"""Robust covariance and tail-risk evidence for the local Risk workspace."""

from __future__ import annotations

import numpy as np
import pandas as pd


ROBUST_RISK_MODEL_VERSION = "robust_risk.v1"
ANNUALISATION_FACTOR = 252.0
ESTIMATOR_NAMES = ("sample", "ewma", "shrinkage", "robust", "diagonal", "factor_model")


def build_robust_risk_report(
    prices: pd.DataFrame,
    allocation: pd.DataFrame | None = None,
    *,
    factor_report: dict[str, object] | None = None,
    window: int = 252,
    ewma_lambda: float = 0.97,
    shrinkage_alpha: float = 0.10,
    bootstrap_reps: int = 100,
    block_size: int = 5,
    seed: int = 42,
) -> dict[str, object]:
    """Build versioned covariance, tail-risk and uncertainty evidence."""

    returns = _return_matrix(prices, window=window)
    ids = list(returns.columns)
    weights = _weights(allocation, ids)
    if returns.empty or len(ids) < 2:
        return _unavailable_report("At least two instruments with adjusted-price returns are required.", returns, weights)
    covariances, estimator_meta = _covariance_estimators(returns, factor_report, ewma_lambda=ewma_lambda, shrinkage_alpha=shrinkage_alpha)
    comparison, selected, validation_warnings = _out_of_sample_selection(returns, factor_report, ewma_lambda=ewma_lambda, shrinkage_alpha=shrinkage_alpha)
    selected_covariance = covariances.get(selected, pd.DataFrame()).reindex(index=ids, columns=ids)
    if selected_covariance.empty:
        selected = "sample"
        selected_covariance = covariances["sample"]
        validation_warnings.append("selected_estimator_unavailable_fallback_sample")
    contribution, portfolio = _portfolio_contributions(selected_covariance, weights)
    bootstrap = _bootstrap_uncertainty(returns, weights, block_size=block_size, repetitions=bootstrap_reps, seed=seed)
    regimes = _regime_report(returns, weights)
    tail_risk = _tail_risk_report(returns, weights, prices, allocation)
    diagnostics = {
        "model_version": ROBUST_RISK_MODEL_VERSION,
        "window": int(window),
        "ewma_lambda": float(ewma_lambda),
        "shrinkage_alpha": float(shrinkage_alpha),
        "block_size": int(block_size),
        "bootstrap_repetitions": int(bootstrap_reps),
        "estimators": estimator_meta,
        "out_of_sample": comparison.to_dict("records"),
        "selection_method": "lowest validation covariance Frobenius error; sample baseline if validation is unavailable",
        "warnings": validation_warnings,
    }
    warnings = [*validation_warnings]
    if bootstrap.get("status") != "available":
        warnings.append("bootstrap_uncertainty_unavailable")
    if tail_risk.get("liquidity_adjusted", {}).get("status") != "available":
        warnings.append("liquidity_adjusted_risk_unavailable")
    if len(returns) < 60:
        warnings.append("short_return_history")
    status = "available" if not warnings else "partial"
    return {
        "status": status,
        "message": "Covariance, tail-risk and estimator-selection evidence; execution_allowed=false.",
        "model_version": ROBUST_RISK_MODEL_VERSION,
        "execution_allowed": False,
        "returns": returns,
        "covariances": covariances,
        "estimator_comparison": comparison,
        "selected_estimator": selected,
        "portfolio_contributions": contribution,
        "portfolio": portfolio,
        "bootstrap": bootstrap,
        "regimes": regimes,
        "tail_risk": tail_risk,
        "diagnostics": diagnostics,
        "warnings": warnings,
    }


def covariance_estimators(
    returns: pd.DataFrame,
    *,
    factor_report: dict[str, object] | None = None,
    ewma_lambda: float = 0.97,
    shrinkage_alpha: float = 0.10,
) -> dict[str, pd.DataFrame]:
    """Public covariance-estimator contract used by optimisers and tests."""

    return _covariance_estimators(returns, factor_report, ewma_lambda=ewma_lambda, shrinkage_alpha=shrinkage_alpha)[0]


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
    result = np.log(pivot / pivot.shift(1)).replace([np.inf, -np.inf], np.nan).dropna(how="all")
    return result.tail(int(window)) if window > 0 else result


def _covariance_estimators(
    returns: pd.DataFrame,
    factor_report: dict[str, object] | None,
    *,
    ewma_lambda: float,
    shrinkage_alpha: float,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, object]]]:
    ids = list(returns.columns)
    complete = returns.dropna(how="any")
    if complete.empty:
        complete = returns.fillna(0.0)
    sample_daily = complete.cov().reindex(index=ids, columns=ids).fillna(0.0)
    ewma_daily = _ewma_covariance(complete, ewma_lambda)
    diagonal_daily = pd.DataFrame(np.diag(np.diag(sample_daily.to_numpy(float))), index=ids, columns=ids)
    target_daily = diagonal_daily
    shrinkage_daily = (1.0 - float(shrinkage_alpha)) * sample_daily + float(shrinkage_alpha) * target_daily
    clipped = _winsorise(complete)
    robust_daily = clipped.cov().reindex(index=ids, columns=ids).fillna(0.0)
    raw_matrices = {
        "sample": sample_daily * ANNUALISATION_FACTOR,
        "ewma": ewma_daily * ANNUALISATION_FACTOR,
        "shrinkage": shrinkage_daily * ANNUALISATION_FACTOR,
        "robust": robust_daily * ANNUALISATION_FACTOR,
        "diagonal": diagonal_daily * ANNUALISATION_FACTOR,
    }
    matrices: dict[str, pd.DataFrame] = {}
    repair_metadata: dict[str, dict[str, object]] = {}
    for name, raw_matrix in raw_matrices.items():
        matrices[name], repair_metadata[name] = _psd_repair(raw_matrix, ids)
    factor_matrix = _factor_covariance(factor_report, ids)
    if factor_matrix is not None:
        matrices["factor_model"], repair_metadata["factor_model"] = _psd_repair(factor_matrix, ids)
    else:
        matrices["factor_model"] = pd.DataFrame()
    meta = {name: _covariance_diagnostics(matrix, len(complete), name) for name, matrix in matrices.items() if not matrix.empty}
    for name, details in repair_metadata.items():
        if name in meta:
            meta[name].update(details)
    return matrices, meta


def _ewma_covariance(returns: pd.DataFrame, lambda_: float) -> pd.DataFrame:
    value = float(np.clip(lambda_, 0.0, 0.9999))
    observations = len(returns)
    if observations == 0:
        return pd.DataFrame()
    weights = (1.0 - value) * value ** np.arange(observations - 1, -1, -1)
    weights = weights / max(float(weights.sum()), 1e-12)
    centre = np.average(returns.to_numpy(float), axis=0, weights=weights)
    demeaned = returns.to_numpy(float) - centre
    covariance = (demeaned * weights[:, None]).T @ demeaned
    return pd.DataFrame(covariance, index=returns.columns, columns=returns.columns)


def _winsorise(returns: pd.DataFrame) -> pd.DataFrame:
    frame = returns.copy()
    for column in frame.columns:
        series = pd.to_numeric(frame[column], errors="coerce")
        median = float(series.median())
        scale = 1.4826 * float((series - median).abs().median())
        scale = scale if np.isfinite(scale) and scale > 1e-12 else float(series.std(ddof=0))
        if np.isfinite(scale) and scale > 1e-12:
            frame[column] = series.clip(median - 3.0 * scale, median + 3.0 * scale)
    return frame


def _factor_covariance(factor_report: dict[str, object] | None, ids: list[str]) -> pd.DataFrame | None:
    if not isinstance(factor_report, dict):
        return None
    covariance = factor_report.get("factor_covariance")
    exposures = factor_report.get("exposure_matrix")
    specific = factor_report.get("specific_risk")
    if not isinstance(covariance, pd.DataFrame) or covariance.empty or not isinstance(exposures, pd.DataFrame) or exposures.empty:
        return None
    factors = [factor for factor in covariance.columns if factor in exposures.columns]
    if not factors:
        return None
    matrix = exposures.reindex(index=ids, columns=factors).fillna(0.0).to_numpy(float)
    factor_covariance = covariance.reindex(index=factors, columns=factors).fillna(0.0).to_numpy(float) * ANNUALISATION_FACTOR
    result = matrix @ factor_covariance @ matrix.T
    if isinstance(specific, pd.DataFrame) and {"instrument_id", "specific_vol_ann"}.issubset(specific.columns):
        specific_vol = pd.to_numeric(specific.set_index("instrument_id")["specific_vol_ann"], errors="coerce").reindex(ids).fillna(0.0).to_numpy(float)
        result = result + np.diag(specific_vol**2)
    return pd.DataFrame(result, index=ids, columns=ids)


def _psd_repair(matrix: pd.DataFrame, ids: list[str]) -> tuple[pd.DataFrame, dict[str, object]]:
    numeric = matrix.reindex(index=ids, columns=ids).fillna(0.0).to_numpy(float)
    numeric = (numeric + numeric.T) / 2.0
    if not numeric.size:
        return pd.DataFrame(index=ids, columns=ids, dtype=float), {"regularised": False}
    raw_eigenvalues, eigenvectors = np.linalg.eigh(numeric)
    scale = max(float(np.nanmax(np.diag(numeric))), 0.0)
    floor = max(scale * 1e-10, 1e-12)
    repaired_eigenvalues = np.maximum(raw_eigenvalues, floor)
    repaired = eigenvectors @ np.diag(repaired_eigenvalues) @ eigenvectors.T
    return pd.DataFrame(repaired, index=ids, columns=ids), {"regularised": bool(np.any(raw_eigenvalues < floor)), "minimum_eigenvalue_before": float(raw_eigenvalues.min()), "minimum_eigenvalue_after": float(repaired_eigenvalues.min())}


def _covariance_diagnostics(matrix: pd.DataFrame, sample_count: int, estimator: str) -> dict[str, object]:
    values = matrix.to_numpy(float)
    eigenvalues = np.linalg.eigvalsh((values + values.T) / 2.0) if values.size else np.array([])
    condition = _condition_number(values)
    return {
        "estimator": estimator,
        "sample_count": int(sample_count),
        "effective_sample": float(sample_count),
        "condition_number": condition,
        "minimum_eigenvalue": float(eigenvalues.min()) if len(eigenvalues) else None,
        "maximum_eigenvalue": float(eigenvalues.max()) if len(eigenvalues) else None,
        "positive_semidefinite": bool(len(eigenvalues) == 0 or eigenvalues.min() >= -1e-10),
        "stable": bool(condition is None or condition < 1e10),
    }


def _out_of_sample_selection(returns: pd.DataFrame, factor_report: dict[str, object] | None, *, ewma_lambda: float, shrinkage_alpha: float) -> tuple[pd.DataFrame, str, list[str]]:
    if len(returns) < 30:
        return pd.DataFrame(columns=["estimator", "validation_error", "validation_observations", "selected"]), "sample", ["out_of_sample_validation_unavailable"]
    split = max(10, int(len(returns) * 0.7))
    train, validation = returns.iloc[:split], returns.iloc[split:]
    train_matrices, _ = _covariance_estimators(train, factor_report, ewma_lambda=ewma_lambda, shrinkage_alpha=shrinkage_alpha)
    realised = validation.dropna(how="any").cov() * ANNUALISATION_FACTOR
    realised, _ = _psd_repair(realised, list(returns.columns))
    denominator = max(float(np.linalg.norm(realised.to_numpy(float), ord="fro")), 1e-12)
    rows: list[dict[str, object]] = []
    for estimator, matrix in train_matrices.items():
        if matrix.empty or not np.isfinite(matrix.to_numpy(float)).all():
            continue
        error = float(np.linalg.norm(matrix.reindex(index=returns.columns, columns=returns.columns).to_numpy(float) - realised.to_numpy(float), ord="fro") / denominator)
        rows.append({"estimator": estimator, "validation_error": error, "validation_observations": int(len(validation.dropna(how="any"))), "selected": False})
    if not rows:
        return pd.DataFrame(columns=["estimator", "validation_error", "validation_observations", "selected"]), "sample", ["out_of_sample_estimators_unavailable"]
    selected_index = int(np.argmin([float(row["validation_error"]) for row in rows]))
    rows[selected_index]["selected"] = True
    return pd.DataFrame(rows).sort_values("validation_error", kind="stable").reset_index(drop=True), str(rows[selected_index]["estimator"]), []


def _portfolio_contributions(covariance: pd.DataFrame, weights: pd.Series) -> tuple[pd.DataFrame, dict[str, object]]:
    if covariance.empty:
        return pd.DataFrame(columns=["instrument_id", "weight", "variance_contribution", "variance_share"]), {"annualised_volatility": None, "component_share_sum": None}
    ids = list(covariance.index)
    vector = weights.reindex(ids).fillna(0.0).to_numpy(float)
    matrix = covariance.to_numpy(float)
    contributions = vector * (matrix @ vector)
    total = float(vector @ matrix @ vector)
    total = max(0.0, total)
    denominator = total if total > 0 else 1.0
    frame = pd.DataFrame({"instrument_id": ids, "weight": vector, "variance_contribution": contributions, "variance_share": contributions / denominator})
    return frame.sort_values("variance_share", ascending=False).reset_index(drop=True), {"annualised_volatility": float(np.sqrt(total)), "variance": total, "component_share_sum": float((contributions / denominator).sum()), "weight_sum": float(vector.sum())}


def _bootstrap_uncertainty(returns: pd.DataFrame, weights: pd.Series, *, block_size: int, repetitions: int, seed: int) -> dict[str, object]:
    clean = returns.dropna(how="any")
    if len(clean) < max(20, block_size * 2) or repetitions <= 0:
        return {"status": "unavailable", "observations": int(len(clean)), "repetitions": int(repetitions)}
    vector = weights.reindex(clean.columns).fillna(0.0).to_numpy(float)
    rng = np.random.default_rng(seed)
    block = max(1, min(int(block_size), len(clean)))
    values: list[float] = []
    for _ in range(int(repetitions)):
        selected: list[int] = []
        while len(selected) < len(clean):
            start = int(rng.integers(0, len(clean) - block + 1))
            selected.extend(range(start, start + block))
        sample = clean.iloc[selected[: len(clean)]]
        covariance = sample.cov().to_numpy(float) * ANNUALISATION_FACTOR
        values.append(float(np.sqrt(max(0.0, vector @ covariance @ vector))))
    distribution = np.asarray(values, dtype=float)
    return {"status": "available", "observations": int(len(clean)), "repetitions": int(repetitions), "seed": int(seed), "block_size": int(block), "mean": float(distribution.mean()), "lower_5": float(np.quantile(distribution, 0.05)), "upper_95": float(np.quantile(distribution, 0.95)), "standard_deviation": float(distribution.std(ddof=1))}


def _regime_report(returns: pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    clean = returns.dropna(how="any")
    if clean.empty:
        return pd.DataFrame(columns=["regime", "observations", "portfolio_vol_ann", "market_abs_return_median"])
    market_abs = clean.mean(axis=1).abs()
    threshold = float(market_abs.median())
    regimes = np.where(market_abs >= threshold, "stress", "calm")
    portfolio = clean @ weights.reindex(clean.columns).fillna(0.0).to_numpy(float)
    rows = []
    for regime in ("calm", "stress"):
        values = portfolio[pd.Series(regimes, index=clean.index) == regime]
        rows.append({"regime": regime, "observations": int(len(values)), "portfolio_vol_ann": float(values.std(ddof=1) * np.sqrt(ANNUALISATION_FACTOR)) if len(values) >= 2 else None, "market_abs_return_median": threshold})
    return pd.DataFrame(rows)


def _tail_risk_report(returns: pd.DataFrame, weights: pd.Series, prices: pd.DataFrame, allocation: pd.DataFrame | None) -> dict[str, object]:
    clean = returns.dropna(how="any")
    if clean.empty:
        return {"status": "unavailable", "portfolio": {}, "tail_dependence": {}, "liquidity_adjusted": {"status": "unavailable"}}
    vector = weights.reindex(clean.columns).fillna(0.0).to_numpy(float)
    portfolio = clean @ vector
    threshold = float(portfolio.quantile(0.05))
    losses = portfolio[portfolio <= threshold]
    cumulative = np.exp(portfolio.cumsum())
    drawdown = cumulative / cumulative.cummax() - 1.0
    tail_dependence = _tail_dependence(clean)
    liquidity = _liquidity_adjusted_risk(prices, allocation, clean, vector)
    return {
        "status": "available",
        "portfolio": {
            "observations": int(len(portfolio)),
            "downside_vol_ann": float(portfolio[portfolio < 0].std(ddof=1) * np.sqrt(ANNUALISATION_FACTOR)) if (portfolio < 0).sum() >= 2 else None,
            "var_95": float(-threshold),
            "expected_shortfall_95": float(-losses.mean()) if not losses.empty else None,
            "max_drawdown": float(drawdown.min()),
        },
        "tail_dependence": tail_dependence,
        "liquidity_adjusted": liquidity,
    }


def _tail_dependence(returns: pd.DataFrame) -> dict[str, object]:
    if returns.shape[1] < 2:
        return {"status": "unavailable", "mean_lower_tail_dependence": None, "pairs": 0}
    threshold = returns.quantile(0.05)
    events = returns.le(threshold)
    values: list[float] = []
    for left_index, left in enumerate(returns.columns):
        for right in returns.columns[left_index + 1 :]:
            denominator = int(events[left].sum())
            values.append(float((events[left] & events[right]).sum() / denominator) if denominator else float("nan"))
    values = [value for value in values if np.isfinite(value)]
    return {"status": "available" if values else "unavailable", "mean_lower_tail_dependence": float(np.mean(values)) if values else None, "pairs": len(values), "quantile": 0.05}


def _liquidity_adjusted_risk(prices: pd.DataFrame, allocation: pd.DataFrame | None, returns: pd.DataFrame, weights: np.ndarray) -> dict[str, object]:
    required = {"date", "etf_id", "adjusted_close", "volume"}
    if prices is None or prices.empty or not required.issubset(prices.columns):
        return {"status": "unavailable", "message": "Volume and adjusted-price fields are required for the transparent liquidity proxy."}
    frame = prices.copy()
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame["dollar_volume"] = frame["adjusted_close"] * frame["volume"]
    average = frame.groupby("etf_id")["dollar_volume"].mean().reindex(returns.columns)
    if average.isna().any() or (average <= 0).any():
        return {"status": "unavailable", "message": "At least one instrument lacks a positive average traded-value proxy."}
    pressure = weights / np.maximum(average.to_numpy(float), 1e-12)
    multiplier = float(np.sqrt(1.0 + np.mean(np.clip(pressure * 10_000.0, 0.0, 100.0))))
    return {"status": "available", "method": "sqrt(1 + mean(weight / average_traded_value * 10000))", "mean_pressure": float(np.mean(pressure)), "multiplier": multiplier, "portfolio_vol_multiplier": multiplier}


def _weights(allocation: pd.DataFrame | None, ids: list[str]) -> pd.Series:
    if allocation is None or allocation.empty or "etf_id" not in allocation.columns:
        return pd.Series(1.0 / max(1, len(ids)), index=ids, dtype=float)
    column = "current_weight" if "current_weight" in allocation.columns else "target_weight" if "target_weight" in allocation.columns else None
    if column is None:
        return pd.Series(1.0 / max(1, len(ids)), index=ids, dtype=float)
    frame = allocation[["etf_id", column]].copy()
    frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    weights = frame.groupby("etf_id")[column].sum().reindex(ids).fillna(0.0)
    if float(weights.abs().sum()) <= 0:
        weights[:] = 1.0 / max(1, len(ids))
    return weights.astype(float)


def _condition_number(matrix: np.ndarray) -> float | None:
    try:
        value = float(np.linalg.cond(matrix))
    except np.linalg.LinAlgError:
        return None
    return value if np.isfinite(value) else None


def _unavailable_report(message: str, returns: pd.DataFrame, weights: pd.Series) -> dict[str, object]:
    return {
        "status": "unavailable",
        "message": message,
        "model_version": ROBUST_RISK_MODEL_VERSION,
        "execution_allowed": False,
        "returns": returns,
        "covariances": {name: pd.DataFrame() for name in ESTIMATOR_NAMES},
        "estimator_comparison": pd.DataFrame(columns=["estimator", "validation_error", "validation_observations", "selected"]),
        "selected_estimator": "sample",
        "portfolio_contributions": pd.DataFrame(columns=["instrument_id", "weight", "variance_contribution", "variance_share"]),
        "portfolio": {"annualised_volatility": None, "component_share_sum": None, "weight_sum": float(weights.sum())},
        "bootstrap": {"status": "unavailable"},
        "regimes": pd.DataFrame(),
        "tail_risk": {"status": "unavailable"},
        "diagnostics": {"model_version": ROBUST_RISK_MODEL_VERSION, "warnings": [message]},
        "warnings": [message],
    }


__all__ = ["ANNUALISATION_FACTOR", "ESTIMATOR_NAMES", "ROBUST_RISK_MODEL_VERSION", "build_robust_risk_report", "covariance_estimators"]
