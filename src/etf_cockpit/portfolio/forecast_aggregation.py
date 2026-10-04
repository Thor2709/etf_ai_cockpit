"""Point-in-time portfolio forecast aggregation from saved holding evidence.

Holding quantiles are joined only when portfolio, analysis, risk and forecast
identities agree. Portfolio quantiles come from seeded Gaussian-copula
scenarios, with the saved robust-risk covariance supplying dependence. The
copula interpolates the saved q05--q95 marginal quantiles and clamps draws
outside that interval to the nearest saved quantile. Horizon covariance scales
the annualised risk model by calendar days / 365.25. An all-positive-correlation
stress case is shown alongside the selected saved correlation regime.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Literal

import numpy as np
import yaml

from etf_cockpit.core.values import finite_non_bool_float_or_none as _finite
from etf_cockpit.models.distribution_store import normalise_quantiles


_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "portfolio_forecast_v1.yaml"
_QUANTILE_PROBABILITIES = np.asarray((0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95), dtype=float)
_QUANTILE_FIELDS = (
    "q05_return",
    "q10_return",
    "q25_return",
    "q50_return",
    "q75_return",
    "q90_return",
    "q95_return",
)
_COST_FIELDS = ("fee", "spread", "impact", "fx")
_COMPONENT_FIELDS = ("price_return", "income_return", "fx_return")


@dataclass(frozen=True)
class PortfolioForecastConfig:
    """Saved, versioned simulation defaults; callers may supply test overrides."""

    scenario_seed: int
    scenario_count: int
    stress_correlation: float


@dataclass(frozen=True)
class PortfolioForecastSnapshot:
    """Forecast result keyed to one bound portfolio, analysis and risk input set."""

    portfolio_id: str | None
    portfolio_snapshot_id: str | None
    portfolio_as_of: str | None
    analysis_run_id: str | None
    risk_snapshot_hash: str | None
    horizon_days: int | None
    output_currency: str | None
    status: str
    reason: str | None
    current: Mapping[str, object]
    target: Mapping[str, object]
    comparison: Mapping[str, object]
    provenance: Mapping[str, object]
    assumptions: Mapping[str, object]
    execution_allowed: Literal[False] = False


def load_portfolio_forecast_config(path: Path = _CONFIG_PATH) -> PortfolioForecastConfig | None:
    """Load scenario defaults and fail closed when the versioned config is invalid."""

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "portfolio_forecast.v1":
        return None
    seed = _integer(payload.get("scenario_seed"), minimum=0)
    count = _integer(payload.get("scenario_count"), minimum=1)
    stress = _finite(payload.get("stress_correlation"))
    if seed is None or count is None or stress is None or not -1.0 <= stress <= 1.0:
        return None
    return PortfolioForecastConfig(seed, count, stress)


def build_portfolio_forecast_snapshot(
    portfolio_snapshot: Mapping[str, object] | None,
    analysis_snapshot: Mapping[str, object] | None,
    risk_snapshot: Mapping[str, object] | None,
    *,
    horizon_days: object,
    output_currency: object,
    config: PortfolioForecastConfig | None = None,
) -> PortfolioForecastSnapshot:
    """Aggregate exact-horizon saved distributions for current and target weights.

    A partial scenario result contains only the supported exposure contribution;
    its coverage and unsupported exposure are returned separately. Unsupported
    returns are never filled with zero. Loss probabilities come from portfolio
    scenarios. Cash and benchmark probabilities remain unavailable unless the
    compatible analysis snapshot contains their saved horizon returns.
    """

    portfolio_id = _text(_get(portfolio_snapshot, "portfolio_id"))
    snapshot_id = _text(_get(portfolio_snapshot, "snapshot_id"))
    portfolio_as_of = _text(_get(portfolio_snapshot, "as_of"))
    analysis_run_id = _text(_get(analysis_snapshot, "analysis_run_id"))
    horizon = _integer(horizon_days, minimum=1)
    currency = _currency(output_currency)
    selected_config = config if config is not None else load_portfolio_forecast_config()
    risk_hash = _digest(risk_snapshot)
    provenance: dict[str, object] = {
        "portfolio_input_hash": _digest(portfolio_snapshot),
        "analysis_input_hash": _digest(analysis_snapshot),
        "risk_input_hash": risk_hash,
        "scenario_seed": None if selected_config is None else selected_config.scenario_seed,
        "scenario_count": None if selected_config is None else selected_config.scenario_count,
    }
    assumptions: dict[str, object] = {
        "scenario_method": "seeded_gaussian_copula_quantile_interpolation_v1",
        "quantile_tail_policy": "clamp_outside_q05_q95",
        "horizon_covariance_scale": "calendar_days_over_365.25",
        "stress_correlation": None if selected_config is None else selected_config.stress_correlation,
        "confidence_definition": "weighted saved distribution coverage over total supplied exposure",
        "drawdown": _unavailable("A single-horizon return distribution does not contain a path for drawdown."),
        "execution_allowed": False,
    }

    reason = _snapshot_error(
        portfolio_snapshot,
        analysis_snapshot,
        risk_snapshot,
        horizon=horizon,
        currency=currency,
        config=selected_config,
    )
    if reason is not None:
        return _unavailable_snapshot(
            portfolio_id,
            snapshot_id,
            portfolio_as_of,
            analysis_run_id,
            risk_hash,
            horizon,
            currency,
            reason,
            provenance,
            assumptions,
        )

    assert portfolio_snapshot is not None
    assert analysis_snapshot is not None
    assert risk_snapshot is not None
    assert horizon is not None
    assert currency is not None
    assert selected_config is not None
    covariances = _get(risk_snapshot, "covariances")
    estimator = _text(_get(risk_snapshot, "selected_estimator"))
    covariance_payload = _get(covariances, estimator) if estimator else None
    covariance_ids, covariance_matrix = _covariance_matrix(covariance_payload)
    if covariance_ids is None or covariance_matrix is None:
        return _unavailable_snapshot(
            portfolio_id,
            snapshot_id,
            portfolio_as_of,
            analysis_run_id,
            risk_hash,
            horizon,
            currency,
            "selected_robust_risk_covariance_unavailable_or_invalid",
            provenance,
            assumptions,
        )
    provenance = {
        **provenance,
        "risk_model_version": _text(_get(risk_snapshot, "model_version")),
        "risk_status": _text(_get(risk_snapshot, "status")),
        "risk_warnings": _get(risk_snapshot, "warnings"),
        "risk_coverage": _get(risk_snapshot, "coverage"),
        "risk_estimator": estimator,
        "risk_candidate_id": _text(_get(risk_snapshot, "candidate_id")),
        "covariance_instrument_ids": covariance_ids,
    }

    distributions = _get(analysis_snapshot, "distributions")
    current_positions = _current_positions(_get(portfolio_snapshot, "positions"))
    target_positions = _target_positions(_get(analysis_snapshot, "target_weights"))
    portfolio_value = _finite(_get(portfolio_snapshot, "total_value"))
    if portfolio_value is not None:
        target_positions = {
            instrument_id: {
                **position,
                "market_value": portfolio_value * float(position["weight"]),
            }
            for instrument_id, position in target_positions.items()
        }
    current_cash_weight = _finite(_get(portfolio_snapshot, "cash_weight"))
    target_cash_weight = _finite(_get(analysis_snapshot, "cash_weight"))

    rng = np.random.default_rng(selected_config.scenario_seed)
    scenario_state = deepcopy(rng.bit_generator.state)
    current = _aggregate_view(
        name="current",
        positions=current_positions,
        cash_weight=current_cash_weight,
        distributions=distributions,
        analysis_run_id=analysis_run_id,
        portfolio_as_of=portfolio_as_of,
        covariance_ids=covariance_ids,
        covariance=covariance_matrix,
        horizon_days=horizon,
        portfolio_value=portfolio_value,
        output_currency=currency,
        scenario_seed=selected_config.scenario_seed,
        scenario_count=selected_config.scenario_count,
        stress_correlation=selected_config.stress_correlation,
        rng=rng,
        cash_return=_get(analysis_snapshot, "cash_return"),
        benchmark_return=_get(analysis_snapshot, "benchmark_return"),
    )
    after_current_state = deepcopy(rng.bit_generator.state)
    rng.bit_generator.state = scenario_state
    target = _aggregate_view(
        name="target",
        positions=target_positions,
        cash_weight=target_cash_weight,
        distributions=distributions,
        analysis_run_id=analysis_run_id,
        portfolio_as_of=portfolio_as_of,
        covariance_ids=covariance_ids,
        covariance=covariance_matrix,
        horizon_days=horizon,
        portfolio_value=portfolio_value,
        output_currency=currency,
        scenario_seed=selected_config.scenario_seed,
        scenario_count=selected_config.scenario_count,
        stress_correlation=selected_config.stress_correlation,
        rng=rng,
        cash_return=_get(analysis_snapshot, "cash_return"),
        benchmark_return=_get(analysis_snapshot, "benchmark_return"),
    )
    rng.bit_generator.state = after_current_state
    comparison = _compare_views(current, target)
    status = "available" if current.get("status") == "available" and target.get("status") == "available" else "partial"
    return PortfolioForecastSnapshot(
        portfolio_id=portfolio_id,
        portfolio_snapshot_id=snapshot_id,
        portfolio_as_of=portfolio_as_of,
        analysis_run_id=analysis_run_id,
        risk_snapshot_hash=risk_hash,
        horizon_days=horizon,
        output_currency=currency,
        status=status,
        reason=None if status == "available" else "One or more portfolio forecast views have incomplete coverage or inputs.",
        current=current,
        target=target,
        comparison=comparison,
        provenance=provenance,
        assumptions=assumptions,
    )


def _aggregate_view(
    *,
    name: str,
    positions: Mapping[str, Mapping[str, object]],
    cash_weight: float | None,
    distributions: object,
    analysis_run_id: str | None,
    portfolio_as_of: str | None,
    covariance_ids: Sequence[str],
    covariance: np.ndarray,
    horizon_days: int,
    portfolio_value: float | None,
    output_currency: str,
    scenario_seed: int,
    scenario_count: int,
    stress_correlation: float,
    rng: np.random.Generator,
    cash_return: object,
    benchmark_return: object,
) -> dict[str, object]:
    raw_weights = [_finite(row.get("weight")) for row in positions.values()]
    weights_complete = all(value is not None and value >= 0 for value in raw_weights) and cash_weight is not None and cash_weight >= 0
    exposure_weights = [value for value in raw_weights if value is not None and value > 0]
    supplied_weight = math.fsum(exposure_weights) + (cash_weight if cash_weight is not None and cash_weight > 0 else 0.0)
    total_weight = max(1.0, supplied_weight)
    if not positions or total_weight <= 0:
        return _unavailable_view(name, "No positive saved portfolio exposure is available.")

    prepared: dict[str, dict[str, object]] = {}
    for instrument_id, position in sorted(positions.items()):
        weight = _finite(position.get("weight"))
        distribution = _distribution_for(
            distributions,
            instrument_id,
            horizon_days,
            portfolio_as_of,
            analysis_run_id,
        )
        if weight is None or weight <= 0:
            continue
        quantiles = _quantiles_for(distribution, "gross_quantiles")
        net_quantiles = (
            _quantiles_for(distribution, "net_quantiles")
            if _text(_get(distribution, "net_status")) == "available"
            else None
        )
        coverage = _coverage(_get(distribution, "coverage_ratio"))
        components = _number_map(_get(distribution, "return_components"), _COMPONENT_FIELDS)
        costs = _number_map(_get(distribution, "cost_deductions"), _COST_FIELDS, nonnegative=True)
        models = _model_medians(_get(distribution, "per_model_distributions"))
        prepared[instrument_id] = {
            "weight": weight,
            "market_value": _finite(position.get("market_value")),
            "distribution": distribution,
            "gross_quantiles": quantiles,
            "net_quantiles": net_quantiles,
            "coverage": coverage,
            "components": components,
            "costs": costs,
            "model_medians": models,
        }

    coverage_sum = 0.0
    for instrument in prepared.values():
        coverage = instrument["coverage"]
        if isinstance(coverage, float):
            coverage_sum += float(instrument["weight"]) * coverage
    confidence = coverage_sum / total_weight if weights_complete else None
    unsupported_weight = max(0.0, total_weight - math.fsum(
        float(row["weight"]) * (float(row["coverage"]) if isinstance(row["coverage"], float) else 0.0)
        for row in prepared.values()
    ))
    coverage_projection = {
        "status": "unavailable" if confidence is None else "available" if confidence >= 1.0 else "partial",
        "confidence": confidence,
        "covered_exposure_weight": coverage_sum,
        "total_exposure_weight": total_weight,
        "unsupported_exposure_weight": unsupported_weight if weights_complete else None,
        "cash_exposure_weight": cash_weight,
        "reason": None if confidence is not None and confidence >= 1.0 else "Saved exposure weights or distribution coverage are incomplete.",
    }

    scenario_state = deepcopy(rng.bit_generator.state)
    gross = _aggregate_basis(
        name=name,
        basis="gross",
        quantile_key="gross_quantiles",
        positions=prepared,
        total_weight=total_weight,
        covariance_ids=covariance_ids,
        covariance=covariance,
        horizon_days=horizon_days,
        portfolio_value=portfolio_value,
        output_currency=output_currency,
        scenario_seed=scenario_seed,
        scenario_count=scenario_count,
        stress_correlation=stress_correlation,
        rng=rng,
        cash_return=cash_return,
        benchmark_return=benchmark_return,
    )
    after_gross_state = deepcopy(rng.bit_generator.state)
    rng.bit_generator.state = scenario_state
    net = _aggregate_basis(
        name=name,
        basis="net",
        quantile_key="net_quantiles",
        positions=prepared,
        total_weight=total_weight,
        covariance_ids=covariance_ids,
        covariance=covariance,
        horizon_days=horizon_days,
        portfolio_value=portfolio_value,
        output_currency=output_currency,
        scenario_seed=scenario_seed,
        scenario_count=scenario_count,
        stress_correlation=stress_correlation,
        rng=rng,
        cash_return=cash_return,
        benchmark_return=benchmark_return,
    )
    rng.bit_generator.state = after_gross_state
    components = _component_contributions(prepared, total_weight, output_currency)
    costs = _cost_contributions(prepared, total_weight, output_currency)
    disagreement = _model_disagreement(prepared, total_weight)
    sensitivity = _cost_sensitivity(gross, net, output_currency)
    return {
        "status": "available" if confidence is not None and confidence >= 1.0 and net.get("status") == "available" else "partial",
        "reason": None if confidence is not None and confidence >= 1.0 and net.get("status") == "available" else "Forecast covers only the supported exposure or net cost inputs are incomplete.",
        "coverage": coverage_projection,
        "gross": gross,
        "net": net,
        "components": components,
        "cost_contributions": costs,
        "model_disagreement": disagreement,
        "cost_sensitivity": sensitivity,
        "correlation_sensitivity": {
            "selected_regime": _text(gross.get("correlation_regime")) or "unavailable",
            "stress_regime": _text(_get(gross.get("stress"), "correlation_regime")) or "unavailable",
            "gross_q05_selected": _get(gross.get("quantiles"), "q05"),
            "gross_q05_stress": _get(_get(gross.get("stress"), "quantiles"), "q05"),
            "reason": None if gross.get("status") == "available" else _text(gross.get("reason")),
        },
        "reconciliation": {
            "portfolio_value": portfolio_value,
            "position_value_total": _sum_values(positions),
            "output_currency": output_currency,
            "reason": None if portfolio_value is not None else "Selected-currency portfolio value is unavailable.",
        },
        "assumptions": {
            "scenario_seed": scenario_seed,
            "scenario_count": scenario_count,
            "method": "seeded_gaussian_copula_quantile_interpolation_v1",
            "quantile_tail_policy": "clamp_outside_q05_q95",
            "cash_and_benchmark_probabilities_require_saved_horizon_returns": True,
            "drawdown": _unavailable("A single-horizon return distribution does not contain a path for drawdown."),
        },
        "execution_allowed": False,
    }


def _aggregate_basis(
    *,
    name: str,
    basis: str,
    quantile_key: str,
    positions: Mapping[str, Mapping[str, object]],
    total_weight: float,
    covariance_ids: Sequence[str],
    covariance: np.ndarray,
    horizon_days: int,
    portfolio_value: float | None,
    output_currency: str,
    scenario_seed: int,
    scenario_count: int,
    stress_correlation: float,
    rng: np.random.Generator,
    cash_return: object,
    benchmark_return: object,
) -> dict[str, object]:
    available_ids = [
        instrument_id
        for instrument_id, row in sorted(positions.items())
        if isinstance(row.get(quantile_key), Mapping)
    ]
    if not available_ids:
        return _unavailable_basis(basis, "Compatible saved holding quantiles are unavailable.")
    if any(instrument_id not in covariance_ids for instrument_id in available_ids):
        return _unavailable_basis(basis, "Selected risk covariance does not cover every forecast instrument.")
    indexes = [list(covariance_ids).index(instrument_id) for instrument_id in available_ids]
    selected_covariance = covariance[np.ix_(indexes, indexes)]
    correlation = _correlation_matrix(selected_covariance)
    if correlation is None:
        return _unavailable_basis(basis, "Selected risk covariance cannot define a valid correlation matrix.")
    root = _correlation_root(correlation)
    stress_matrix = np.full_like(correlation, stress_correlation)
    np.fill_diagonal(stress_matrix, 1.0)
    stress_root = _correlation_root(stress_matrix)
    if root is None or stress_root is None:
        return _unavailable_basis(basis, "Selected or stressed correlation matrix is not positive semidefinite.")

    independent = rng.standard_normal((scenario_count, len(available_ids)))
    correlated = independent @ root.T
    stress_independent = rng.standard_normal((scenario_count, len(available_ids)))
    stress_draws = stress_independent @ stress_root.T
    returns = _marginal_scenarios(available_ids, positions, quantile_key, correlated)
    stress_returns = _marginal_scenarios(available_ids, positions, quantile_key, stress_draws)
    if returns is None or stress_returns is None:
        return _unavailable_basis(basis, "Saved quantiles could not be transformed into scenario returns.")

    weights = np.asarray([float(positions[item]["weight"]) for item in available_ids], dtype=float)
    known_weights = math.fsum(float(value) for value in weights)
    portfolio_returns = returns @ weights
    stress_portfolio_returns = stress_returns @ weights
    notionals = [_finite(positions[item].get("market_value")) for item in available_ids]
    gain_scenarios = (
        returns @ np.asarray(notionals, dtype=float)
        if all(value is not None for value in notionals)
        else None
    )
    stress_gain_scenarios = (
        stress_returns @ np.asarray(notionals, dtype=float)
        if all(value is not None for value in notionals)
        else None
    )
    variance = _covariance_variance(weights, selected_covariance, horizon_days)
    if variance is None:
        variance_cell = _unavailable("Horizon covariance variance is unavailable.")
    else:
        variance_cell = _available(variance)
    coverage_weight = math.fsum(
        float(positions[item]["weight"])
        * (float(positions[item]["coverage"]) if isinstance(positions[item]["coverage"], float) else 0.0)
        for item in available_ids
    )
    coverage = coverage_weight / total_weight if total_weight > 0 else 0.0
    status = "available" if coverage >= 1.0 and variance_cell["status"] == "available" else "partial"
    stats = _scenario_stats(portfolio_returns, gain_scenarios, output_currency)
    stress_stats = _scenario_stats(stress_portfolio_returns, stress_gain_scenarios, output_currency)
    probabilities = {
        "loss": _available(float(np.mean(portfolio_returns < 0.0))),
        "beat_cash": _probability_above(portfolio_returns, cash_return),
        "beat_benchmark": _probability_above(portfolio_returns, benchmark_return),
    }
    if status == "partial":
        for field in ("expected_return", "expected_gain_loss"):
            cell = stats[field]
            if isinstance(cell, Mapping) and cell.get("status") == "available":
                stats[field] = {
                    **_partial(cell.get("value"), _text(cell.get("currency"))),
                    "reason": "Value covers supported exposure only.",
                }
        probabilities["loss"] = {
            **_partial(probabilities["loss"]["value"]),
            "reason": "Loss probability covers supported exposure only.",
        }
    return {
        "status": status,
        "reason": None if status == "available" else "Scenario statistics cover supported holdings only; covariance or exposure coverage is partial.",
        "basis": basis,
        **stats,
        "variance_from_covariance": variance_cell,
        "volatility": _available(float(np.std(portfolio_returns, ddof=1))) if scenario_count > 1 else _unavailable("At least two scenarios are required for volatility."),
        "probabilities": probabilities,
        "coverage_ratio": coverage,
        "supported_exposure_weight": known_weights,
        "unknown_exposure_weight": max(0.0, total_weight - coverage_weight),
        "correlation_regime": "selected_robust_risk_covariance",
        "correlation_matrix": {
            instrument_id: {other_id: float(correlation[i, j]) for j, other_id in enumerate(available_ids)}
            for i, instrument_id in enumerate(available_ids)
        },
        "covariance_matrix_annualised": {
            instrument_id: {other_id: float(selected_covariance[i, j]) for j, other_id in enumerate(available_ids)}
            for i, instrument_id in enumerate(available_ids)
        },
        "stress": {
            "status": "available",
            "correlation_regime": "perfect_positive_correlation_stress",
            "correlation": stress_correlation,
            **stress_stats,
        },
        "tail_dependence": _tail_dependence(available_ids, returns),
        "scenario_returns": tuple(float(value) for value in portfolio_returns),
        "scenario_gain_loss": (
            tuple(float(value) for value in gain_scenarios)
            if gain_scenarios is not None
            else None
        ),
        "scenario_seed": scenario_seed,
        "scenario_count": scenario_count,
        "instrument_ids": tuple(available_ids),
    }


def _scenario_stats(values: np.ndarray, gain_values: np.ndarray | None, currency: str) -> dict[str, object]:
    quantiles = np.quantile(values, (0.05, 0.25, 0.50, 0.75, 0.95))
    mean = float(np.mean(values))
    amount = None if gain_values is None else float(np.mean(gain_values))
    return {
        "expected_return": _available(mean),
        "expected_gain_loss": _available(amount, currency) if amount is not None else _unavailable("Selected-currency portfolio value is unavailable."),
        "quantiles": {
            name: float(value)
            for name, value in zip(("q05", "q25", "q50", "q75", "q95"), quantiles, strict=True)
        },
        "gain_loss_quantiles": (
            {
                name: float(value)
                for name, value in zip(
                    ("q05", "q25", "q50", "q75", "q95"),
                    np.quantile(gain_values, (0.05, 0.25, 0.50, 0.75, 0.95)),
                    strict=True,
                )
            }
            if gain_values is not None
            else _unavailable("Selected-currency portfolio value is unavailable.")
        ),
        "currency": currency,
    }


def _marginal_scenarios(
    instrument_ids: Sequence[str],
    positions: Mapping[str, Mapping[str, object]],
    quantile_key: str,
    normal_values: np.ndarray,
) -> np.ndarray | None:
    flat = normal_values.ravel()
    uniforms = np.fromiter(
        (0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0))) for value in flat),
        dtype=float,
        count=len(flat),
    ).reshape(normal_values.shape)
    output = np.empty_like(uniforms)
    for column, instrument_id in enumerate(instrument_ids):
        quantiles = positions[instrument_id].get(quantile_key)
        if not isinstance(quantiles, Mapping):
            return None
        points = np.asarray([_finite(quantiles.get(field)) for field in _QUANTILE_FIELDS], dtype=float)
        if not np.isfinite(points).all() or np.any(np.diff(points) < 0):
            return None
        output[:, column] = np.interp(uniforms[:, column], _QUANTILE_PROBABILITIES, points)
    return output


def _correlation_matrix(covariance: np.ndarray) -> np.ndarray | None:
    diagonal = np.diag(covariance)
    if not np.isfinite(covariance).all() or np.any(diagonal <= 0):
        return None
    scale = np.sqrt(diagonal)
    correlation = covariance / np.outer(scale, scale)
    np.fill_diagonal(correlation, 1.0)
    if not np.isfinite(correlation).all() or np.any(np.abs(correlation) > 1.0):
        return None
    if not np.array_equal(correlation, correlation.T):
        return None
    return correlation


def _correlation_root(correlation: np.ndarray) -> np.ndarray | None:
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(correlation)
    except np.linalg.LinAlgError:
        return None
    if not np.isfinite(eigenvalues).all() or np.any(eigenvalues < 0):
        return None
    return eigenvectors @ np.diag(np.sqrt(eigenvalues))


def _covariance_variance(weights: np.ndarray, covariance: np.ndarray, horizon_days: int) -> float | None:
    horizon_covariance = covariance * (horizon_days / 365.25)
    value = float(weights @ horizon_covariance @ weights)
    return value if math.isfinite(value) and value >= 0 else None


def _tail_dependence(instrument_ids: Sequence[str], returns: np.ndarray) -> dict[str, object]:
    result: dict[str, object] = {}
    if len(instrument_ids) < 2:
        return {"status": "unavailable", "reason": "At least two supported instruments are required for tail dependence.", "pairs": {}}
    thresholds = np.quantile(returns, 0.05, axis=0)
    for left in range(len(instrument_ids)):
        for right in range(left + 1, len(instrument_ids)):
            key = f"{instrument_ids[left]}|{instrument_ids[right]}"
            joint_probability = float(np.mean((returns[:, left] <= thresholds[left]) & (returns[:, right] <= thresholds[right])))
            result[key] = {
                "joint_q05_probability": joint_probability,
                "lower_tail_dependence_ratio": joint_probability / 0.05,
            }
    return {"status": "available", "method": "joint_q05_probability_over_0.05", "pairs": result}


def _component_contributions(positions: Mapping[str, Mapping[str, object]], total_weight: float, currency: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in _COMPONENT_FIELDS:
        amount = 0.0
        covered_weight = 0.0
        for row in positions.values():
            components = row.get("components")
            value = _finite(row.get("market_value"))
            contribution = _finite(components.get(field)) if isinstance(components, Mapping) else None
            if value is None or contribution is None:
                continue
            amount += value * contribution
            covered_weight += float(row["weight"])
        if covered_weight <= 0:
            result[field.removesuffix("_return")] = _unavailable(
                "No saved return component and selected-currency value support this contribution."
            )
        elif total_weight > 0 and covered_weight >= total_weight:
            result[field.removesuffix("_return")] = _available(amount, currency)
        else:
            result[field.removesuffix("_return")] = {
                **_partial(amount, currency),
                "covered_exposure_weight": covered_weight,
                "reason": "Saved return component or currency value is incomplete.",
            }
    return result


def _cost_contributions(positions: Mapping[str, Mapping[str, object]], total_weight: float, currency: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in _COST_FIELDS:
        amount = 0.0
        covered_weight = 0.0
        for row in positions.values():
            costs = row.get("costs")
            value = _finite(row.get("market_value"))
            deduction = _finite(costs.get(field)) if isinstance(costs, Mapping) else None
            if value is None or deduction is None:
                continue
            amount += value * deduction
            covered_weight += float(row["weight"])
        if covered_weight <= 0:
            result[field] = _unavailable("No saved cost and selected-currency value support this contribution.")
        elif total_weight > 0 and covered_weight >= total_weight:
            result[field] = _available(amount, currency)
        else:
            result[field] = {
                **_partial(amount, currency),
                "covered_exposure_weight": covered_weight,
                "reason": "Saved cost or selected-currency value is incomplete.",
            }
    return result


def _model_disagreement(positions: Mapping[str, Mapping[str, object]], total_weight: float) -> dict[str, object]:
    values: dict[str, object] = {}
    weighted_variance = 0.0
    covered_weight = 0.0
    for instrument_id, row in positions.items():
        medians = row.get("model_medians")
        if not isinstance(medians, Sequence) or len(medians) < 2:
            values[instrument_id] = _unavailable("At least two saved model medians are required.")
            continue
        spread = float(np.std(np.asarray(medians, dtype=float), ddof=0))
        values[instrument_id] = _available(spread)
        weight = float(row["weight"])
        weighted_variance += weight * spread * spread
        covered_weight += weight
    aggregate = (
        _available(math.sqrt(weighted_variance / covered_weight))
        if covered_weight >= total_weight and covered_weight > 0
        else {**_partial(None, None), "covered_exposure_weight": covered_weight, "reason": "Model disagreement is unavailable for part of the exposure."}
    )
    return {"status": aggregate["status"], "aggregate": aggregate, "by_instrument": values}


def _cost_sensitivity(gross: Mapping[str, object], net: Mapping[str, object], currency: str) -> dict[str, object]:
    gross_amount = _finite(_get(gross, "expected_gain_loss", "value"))
    net_amount = _finite(_get(net, "expected_gain_loss", "value"))
    if gross_amount is None or net_amount is None:
        return _unavailable("Complete gross and net scenario distributions are required for cost sensitivity.")
    if (
        _finite(gross.get("supported_exposure_weight")) != _finite(net.get("supported_exposure_weight"))
        or gross.get("instrument_ids") != net.get("instrument_ids")
    ):
        return _unavailable("Gross and net scenario exposure do not match.")
    difference = net_amount - gross_amount
    return (
        _available(difference, currency)
        if gross.get("status") == "available" and net.get("status") == "available"
        else {**_partial(difference, currency), "reason": "Cost sensitivity covers supported exposure only."}
    )


def _compare_views(current: Mapping[str, object], target: Mapping[str, object]) -> dict[str, object]:
    current_expected = _finite(_get(_get(current, "net"), "expected_return", "value"))
    target_expected = _finite(_get(_get(target, "net"), "expected_return", "value"))
    current_q05 = _finite(_get(_get(_get(current, "net"), "quantiles"), "q05"))
    target_q05 = _finite(_get(_get(_get(target, "net"), "quantiles"), "q05"))
    if None in (current_expected, target_expected, current_q05, target_q05):
        return _unavailable("Compatible current and target net scenario summaries are required.")
    return {
        "status": "available",
        "expected_return_difference": float(target_expected - current_expected),
        "q05_return_difference": float(target_q05 - current_q05),
        "reason": None,
    }


def _probability_above(scenarios: np.ndarray, threshold: object) -> dict[str, object]:
    value = _finite(threshold)
    if value is None:
        return _unavailable("A compatible saved horizon cash or benchmark return is unavailable.")
    return _available(float(np.mean(scenarios > value)))


def _distribution_for(
    distributions: object,
    instrument_id: str,
    horizon_days: int,
    portfolio_as_of: str | None,
    analysis_run_id: str | None,
) -> Mapping[str, object] | None:
    if not isinstance(distributions, Mapping):
        return None
    value = distributions.get(instrument_id)
    if isinstance(value, Mapping) and any(str(key).isdigit() for key in value):
        value = value.get(horizon_days, value.get(str(horizon_days)))
    if not isinstance(value, Mapping):
        return None
    if _integer(_get(value, "horizon_days"), minimum=1) != horizon_days:
        return None
    if _text(_get(value, "status")) != "available":
        return None
    distribution_run_id = _text(_get(value, "analysis_run_id"))
    if analysis_run_id is None or distribution_run_id != analysis_run_id:
        return None
    decision_time = _text(_get(value, "decision_time"))
    if decision_time is None or portfolio_as_of is None or not _same_or_before(decision_time, portfolio_as_of):
        return None
    return value


def _quantiles_for(distribution: Mapping[str, object] | None, field: str) -> dict[str, float] | None:
    value = _get(distribution, field)
    quantiles = normalise_quantiles(value if isinstance(value, Mapping) else None)
    if quantiles is None:
        return None
    return quantiles


def _coverage(value: object) -> float | None:
    result = _finite(value)
    return result if result is not None and 0 < result <= 1 else None


def _model_medians(value: object) -> list[float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    medians = [_finite(_get(row, "q50_return")) for row in value]
    return [float(item) for item in medians if item is not None] if len([item for item in medians if item is not None]) == len(medians) else None


def _number_map(value: object, fields: Sequence[str], *, nonnegative: bool = False) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    result = {field: _finite(value.get(field)) for field in fields}
    if any(item is None or (nonnegative and item < 0) for item in result.values()):
        return None
    return {field: float(item) for field, item in result.items() if item is not None}


def _current_positions(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, dict[str, object]] = {}
    for key, raw in value.items():
        instrument_id = str(key).strip()
        if instrument_id and isinstance(raw, Mapping):
            output[instrument_id] = {
                "weight": _finite(raw.get("weight")),
                "market_value": _finite(raw.get("market_value")),
            }
    return output


def _target_positions(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, dict[str, object]] = {}
    for key, raw in value.items():
        instrument_id = str(key).strip()
        weight = _finite(raw)
        if instrument_id and weight is not None and weight > 0:
            output[instrument_id] = {"weight": weight, "market_value": None}
    return output


def _covariance_matrix(value: object) -> tuple[list[str] | None, np.ndarray | None]:
    if not isinstance(value, Mapping):
        return None, None
    columns = value.get("columns")
    index = value.get("index")
    data = value.get("data")
    if not isinstance(columns, Sequence) or isinstance(columns, (str, bytes)) or not isinstance(index, Sequence) or isinstance(index, (str, bytes)) or not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        return None, None
    column_ids = [str(item) for item in columns]
    index_ids = [str(item) for item in index]
    if not column_ids or len(set(column_ids)) != len(column_ids) or column_ids != index_ids or len(data) != len(column_ids):
        return None, None
    try:
        matrix = np.asarray(data, dtype=float)
    except (TypeError, ValueError):
        return None, None
    if matrix.shape != (len(column_ids), len(column_ids)) or not np.isfinite(matrix).all() or not np.array_equal(matrix, matrix.T):
        return None, None
    return column_ids, matrix


def _snapshot_error(
    portfolio: Mapping[str, object] | None,
    analysis: Mapping[str, object] | None,
    risk: Mapping[str, object] | None,
    *,
    horizon: int | None,
    currency: str | None,
    config: PortfolioForecastConfig | None,
) -> str | None:
    if portfolio is None or analysis is None:
        return "sealed_portfolio_or_analysis_snapshot_unavailable"
    required = ("portfolio_id", "snapshot_id", "as_of", "source_checksum")
    if any(not _text(_get(portfolio, key)) for key in required):
        return "sealed_portfolio_snapshot_identity_or_checksum_unavailable"
    if _get(portfolio, "sealed") is not True:
        return "portfolio_snapshot_not_sealed_or_reconciled"
    components_reconciled = _get(portfolio, "value_components_reconciled")
    if components_reconciled is False:
        return "portfolio_security_cash_value_reconciliation_unavailable"
    component_fields = tuple(_get(portfolio, field) for field in ("securities_value", "cash_value", "total_value"))
    if components_reconciled is True:
        securities_value, cash_value, total_value = (_finite(value) for value in component_fields)
        if securities_value is None or cash_value is None or total_value is None:
            return "portfolio_security_cash_value_reconciliation_unavailable"
        if not math.isclose(securities_value + cash_value, total_value, rel_tol=1e-12, abs_tol=1e-9):
            return "portfolio_security_cash_value_reconciliation_failed"
        positions = _current_positions(_get(portfolio, "positions"))
        position_values = [row.get("market_value") for row in positions.values()]
        if (
            not position_values
            or any(_finite(value) is None for value in position_values)
            or not math.isclose(
                math.fsum(float(value) for value in position_values if _finite(value) is not None),
                securities_value,
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        ):
            return "portfolio_security_cash_value_reconciliation_failed"
    identity = tuple(_text(_get(portfolio, key)) for key in ("portfolio_id", "snapshot_id", "as_of"))
    analysis_identity = tuple(_text(_get(analysis, key)) for key in ("portfolio_id", "snapshot_id", "as_of"))
    if identity != analysis_identity:
        return "analysis_snapshot_identity_mismatch"
    if not _text(_get(analysis, "analysis_run_id")):
        return "analysis_run_identity_unavailable"
    if _text(_get(analysis, "status")) != "complete" or _get(analysis, "policy_status") != "available":
        return "compatible_complete_analysis_snapshot_unavailable"
    if _text(_get(analysis, "decision_time")) is None or not _same_or_before(_get(analysis, "decision_time"), _get(portfolio, "as_of")):
        return "analysis_decision_time_unavailable_or_postdates_portfolio_snapshot"
    if risk is None:
        return "compatible_risk_snapshot_unavailable"
    risk_identity = tuple(_text(_get(risk, key)) for key in ("portfolio_id", "snapshot_id", "as_of"))
    if (
        identity != risk_identity
        or not _text(_get(analysis, "candidate_id"))
        or _text(_get(risk, "candidate_id")) != _text(_get(analysis, "candidate_id"))
    ):
        return "risk_snapshot_identity_mismatch"
    if _text(_get(risk, "status")) not in {"available", "partial"} or _get(risk, "execution_allowed") is not False:
        return "compatible_risk_covariance_unavailable"
    if not _text(_get(risk, "model_version")):
        return "risk_model_version_unavailable"
    if horizon is None:
        return "forecast_horizon_invalid"
    if currency is None:
        return "output_currency_invalid"
    if config is None:
        return "portfolio_forecast_configuration_missing_or_invalid"
    if _integer(config.scenario_seed, minimum=0) is None or _integer(config.scenario_count, minimum=1) is None:
        return "portfolio_forecast_scenario_configuration_invalid"
    if _finite(config.stress_correlation) is None or not -1.0 <= config.stress_correlation <= 1.0:
        return "portfolio_forecast_stress_correlation_invalid"
    return None


def _same_or_before(decision_time: object, as_of: object) -> bool:
    decision = _datetime_value(decision_time)
    cutoff = _datetime_value(as_of)
    return decision is not None and cutoff is not None and decision <= cutoff


def _datetime_value(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _digest(value: object) -> str | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> object:
    if hasattr(value, "item") and callable(value.item):
        return value.item()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported forecast input type: {type(value).__name__}")


def _available(value: object, currency: str | None = None) -> dict[str, object]:
    return {"status": "available", "value": value, "currency": currency, "reason": None}


def _partial(value: object, currency: str | None = None) -> dict[str, object]:
    return {"status": "partial", "value": value, "currency": currency, "reason": None}


def _unavailable(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "value": None, "reason": reason}


def _unavailable_basis(basis: str, reason: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "reason": reason,
        "basis": basis,
        "expected_return": _unavailable(reason),
        "expected_gain_loss": _unavailable(reason),
        "quantiles": _unavailable(reason),
        "gain_loss_quantiles": _unavailable(reason),
        "variance_from_covariance": _unavailable(reason),
        "volatility": _unavailable(reason),
        "probabilities": {
            "loss": _unavailable(reason),
            "beat_cash": _unavailable(reason),
            "beat_benchmark": _unavailable(reason),
        },
        "stress": {"status": "unavailable", "reason": reason},
        "tail_dependence": {"status": "unavailable", "reason": reason, "pairs": {}},
    }


def _unavailable_view(name: str, reason: str) -> dict[str, object]:
    unavailable_basis = _unavailable_basis("net", reason)
    return {
        "status": "unavailable",
        "reason": reason,
        "coverage": {
            "status": "unavailable",
            "confidence": None,
            "unsupported_exposure_weight": None,
            "reason": reason,
        },
        "gross": {**unavailable_basis, "basis": "gross"},
        "net": unavailable_basis,
        "components": {field.removesuffix("_return"): _unavailable(reason) for field in _COMPONENT_FIELDS},
        "cost_contributions": {field: _unavailable(reason) for field in _COST_FIELDS},
        "model_disagreement": {"status": "unavailable", "aggregate": _unavailable(reason), "by_instrument": {}},
        "cost_sensitivity": _unavailable(reason),
        "correlation_sensitivity": {"status": "unavailable", "reason": reason},
        "assumptions": {"view": name, "execution_allowed": False},
        "execution_allowed": False,
    }


def _unavailable_snapshot(
    portfolio_id: str | None,
    snapshot_id: str | None,
    portfolio_as_of: str | None,
    analysis_run_id: str | None,
    risk_hash: str | None,
    horizon: int | None,
    currency: str | None,
    reason: str,
    provenance: Mapping[str, object],
    assumptions: Mapping[str, object],
) -> PortfolioForecastSnapshot:
    return PortfolioForecastSnapshot(
        portfolio_id=portfolio_id,
        portfolio_snapshot_id=snapshot_id,
        portfolio_as_of=portfolio_as_of,
        analysis_run_id=analysis_run_id,
        risk_snapshot_hash=risk_hash,
        horizon_days=horizon,
        output_currency=currency,
        status="unavailable",
        reason=reason,
        current=_unavailable_view("current", reason),
        target=_unavailable_view("target", reason),
        comparison=_unavailable(reason),
        provenance=provenance,
        assumptions=assumptions,
    )


def _sum_values(positions: Mapping[str, Mapping[str, object]]) -> float | None:
    values = [_finite(row.get("market_value")) for row in positions.values()]
    if not values or any(value is None for value in values):
        return None
    return math.fsum(float(value) for value in values if value is not None)


def _integer(value: object, *, minimum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return result if result >= minimum else None


def _currency(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    code = text.upper()
    return code if len(code) == 3 and code.isascii() and code.isalpha() else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _get(value: object, key: str, nested: str | None = None) -> object:
    if not isinstance(value, Mapping):
        return None
    result = value.get(key)
    return result.get(nested) if nested is not None and isinstance(result, Mapping) else result


__all__ = [
    "PortfolioForecastConfig",
    "PortfolioForecastSnapshot",
    "build_portfolio_forecast_snapshot",
    "load_portfolio_forecast_config",
]
