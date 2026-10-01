from __future__ import annotations

from copy import deepcopy
import math
from types import SimpleNamespace

import numpy as np

from etf_cockpit.portfolio.forecast_aggregation import (
    PortfolioForecastConfig,
    build_portfolio_forecast_snapshot,
)
from etf_cockpit.application import ui_facade


_CONFIG = PortfolioForecastConfig(scenario_seed=168, scenario_count=12000, stress_correlation=1.0)
_QUANTILE_LEVELS = (5, 10, 25, 50, 75, 90, 95)


def _quantiles(values: tuple[float, ...]) -> dict[str, float]:
    return {f"q{level:02d}_return": value for level, value in zip(_QUANTILE_LEVELS, values, strict=True)}


def _distribution(offset: float = 0.0, *, coverage: float | None = 1.0) -> dict[str, object]:
    gross = _quantiles((-0.20, -0.12, -0.05, 0.02, 0.10, 0.21, 0.32))
    gross = {key: value + offset for key, value in gross.items()}
    costs = {"fee": 0.004, "spread": 0.002, "impact": 0.001, "fx": 0.003}
    net = {key: value - math.fsum(costs.values()) for key, value in gross.items()}
    return {
        "status": "available",
        "horizon_days": 30,
        "decision_time": "2026-09-29T12:00:00+00:00",
        "analysis_run_id": "analysis-run-1",
        "coverage_ratio": coverage,
        "gross_quantiles": gross,
        "net_quantiles": net,
        "net_status": "available",
        "return_components": {"price_return": 0.04 + offset, "income_return": 0.01, "fx_return": 0.002},
        "cost_deductions": costs,
        "per_model_distributions": [
            {"q50_return": 0.01 + offset},
            {"q50_return": 0.03 + offset},
        ],
    }


def _inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    portfolio = {
        "portfolio_id": "portfolio-1",
        "snapshot_id": "snapshot-1",
        "as_of": "2026-09-30T00:00:00+00:00",
        "source_checksum": "sealed-holdings-checksum",
        "sealed": True,
        "total_value": 1000.0,
        "cash_weight": 0.0,
        "positions": {
            "AAA": {"weight": 0.5, "market_value": 500.0},
            "BBB": {"weight": 0.5, "market_value": 500.0},
        },
    }
    analysis = {
        "portfolio_id": "portfolio-1",
        "snapshot_id": "snapshot-1",
        "as_of": "2026-09-30T00:00:00+00:00",
        "analysis_run_id": "analysis-run-1",
        "candidate_id": "candidate-1",
        "decision_time": "2026-09-30T00:00:00+00:00",
        "status": "complete",
        "policy_status": "available",
        "distributions": {"AAA": _distribution(), "BBB": _distribution(0.08)},
        "target_weights": {"AAA": 0.25, "BBB": 0.75},
        "cash_weight": 0.0,
        "cash_return": None,
        "benchmark_return": None,
    }
    risk = {
        "portfolio_id": "portfolio-1",
        "snapshot_id": "snapshot-1",
        "as_of": "2026-09-30T00:00:00+00:00",
        "candidate_id": "candidate-1",
        "status": "available",
        "model_version": "robust_risk.v1",
        "execution_allowed": False,
        "selected_estimator": "sample",
        "covariances": {
            "sample": {
                "columns": ["AAA", "BBB"],
                "index": ["AAA", "BBB"],
                "data": [[0.04, 0.03], [0.03, 0.09]],
            }
        },
    }
    return portfolio, analysis, risk


def _build(inputs: tuple[dict[str, object], dict[str, object], dict[str, object]]):
    portfolio, analysis, risk = inputs
    return build_portfolio_forecast_snapshot(
        portfolio,
        analysis,
        risk,
        horizon_days=30,
        output_currency="EUR",
        config=_CONFIG,
    )


def test_one_sealed_snapshot_and_compatible_analysis_are_required() -> None:
    inputs = _inputs()
    forecast = _build(inputs)
    assert forecast.status == "available"
    assert forecast.portfolio_snapshot_id == "snapshot-1"
    assert forecast.analysis_run_id == "analysis-run-1"
    assert forecast.current["net"]["status"] == "available"

    mismatched = deepcopy(inputs)
    mismatched[1]["snapshot_id"] = "snapshot-2"
    rejected = _build(mismatched)
    assert rejected.status == "unavailable"
    assert rejected.reason == "analysis_snapshot_identity_mismatch"


def test_unknown_distribution_coverage_lowers_aggregate_confidence() -> None:
    inputs = _inputs()
    inputs[1]["distributions"]["BBB"]["coverage_ratio"] = 0.5
    forecast = _build(inputs)
    coverage = forecast.current["coverage"]
    assert coverage["status"] == "partial"
    assert coverage["confidence"] == 0.75
    assert coverage["unsupported_exposure_weight"] == 0.25


def test_nonlinear_quantiles_and_volatility_use_scenarios_and_covariance() -> None:
    forecast = _build(_inputs())
    net = forecast.current["net"]
    individual_q05_sum = 0.5 * -0.20 + 0.5 * (-0.20 + 0.08)
    assert not math.isclose(net["quantiles"]["q05"], individual_q05_sum, abs_tol=1e-4)

    expected_variance = np.asarray([0.5, 0.5]) @ (np.asarray([[0.04, 0.03], [0.03, 0.09]]) * (30 / 365.25)) @ np.asarray([0.5, 0.5])
    assert math.isclose(net["variance_from_covariance"]["value"], float(expected_variance), rel_tol=1e-12)
    independent_volatility_sum = 0.5 * math.sqrt(0.04 * 30 / 365.25) + 0.5 * math.sqrt(0.09 * 30 / 365.25)
    assert not math.isclose(net["volatility"]["value"], independent_volatility_sum, rel_tol=1e-3)
    assert net["tail_dependence"]["status"] == "available"
    assert net["stress"]["correlation_regime"] == "perfect_positive_correlation_stress"


def test_scenarios_replay_from_fixed_seed_and_frozen_inputs() -> None:
    inputs = _inputs()
    first = _build(inputs)
    frozen = deepcopy(inputs)
    second = _build(frozen)
    assert first.provenance["scenario_seed"] == 168
    assert first.provenance["portfolio_input_hash"] == second.provenance["portfolio_input_hash"]
    assert first.provenance["analysis_input_hash"] == second.provenance["analysis_input_hash"]
    assert first.provenance["risk_input_hash"] == second.provenance["risk_input_hash"]
    assert first.current["net"]["scenario_returns"] == second.current["net"]["scenario_returns"]


def test_saved_components_costs_and_reference_probabilities_stay_explicit() -> None:
    forecast = _build(_inputs())
    current = forecast.current
    assert current["components"]["price"]["value"] == 80.0
    assert current["components"]["income"]["value"] == 10.0
    assert current["components"]["fx"]["value"] == 2.0
    assert current["cost_contributions"]["fee"]["value"] == 4.0
    assert current["cost_sensitivity"]["status"] == "available"
    assert current["cost_sensitivity"]["value"] < 0
    assert current["net"]["probabilities"]["loss"]["status"] == "available"
    assert current["net"]["probabilities"]["beat_cash"]["status"] == "unavailable"
    assert current["net"]["probabilities"]["beat_benchmark"]["status"] == "unavailable"


def test_components_and_costs_without_supported_inputs_are_unavailable_not_zero() -> None:
    inputs = _inputs()
    for distribution in inputs[1]["distributions"].values():
        distribution["return_components"] = {}
        distribution["cost_deductions"] = {}

    current = _build(inputs).current

    for contribution in (*current["components"].values(), *current["cost_contributions"].values()):
        assert contribution["status"] == "unavailable"
        assert contribution["value"] is None


def test_distribution_from_another_analysis_run_is_excluded() -> None:
    inputs = _inputs()
    inputs[1]["distributions"]["BBB"]["analysis_run_id"] = "analysis-run-2"

    current = _build(inputs).current

    assert current["coverage"]["status"] == "partial"
    assert current["coverage"]["confidence"] == 0.5


def test_facade_loader_binds_saved_holdings_analysis_and_risk(monkeypatch) -> None:
    portfolio, analysis_input, _ = _inputs()
    projection = {
        "portfolio_snapshot": {
            "portfolio_id": portfolio["portfolio_id"],
            "snapshot_id": portfolio["snapshot_id"],
            "as_of": portfolio["as_of"],
            "source_checksum": portfolio["source_checksum"],
        },
        "rows": [
            {
                "instrument_id": "AAA",
                "weight": {"status": "available", "value": 1.0},
                "value": {"status": "available", "value": 1000.0},
            }
        ],
        "analysis_run_id": "analysis-run-1",
        "analysis_date": "2026-09-30",
        "analysis_current": True,
        "proposal_handoff_allowed": True,
        "performance_snapshot": {
            "securities_value_output_currency": {"status": "available", "value": 1000.0},
            "cash_value_output_currency": {"status": "available", "value": 0.0},
            "total_value_output_currency": {"status": "available", "value": 1000.0},
            "reconciliation": {"status": "available", "value": True},
            "portfolio_value_reconciliation": {"status": "available", "value": True},
        },
    }
    risk_projection = {
        "status": "available",
        "model_version": "robust_risk.v1",
        "selected_estimator": "sample",
        "covariances": {
            "sample": {
                "columns": ["AAA"],
                "index": ["AAA"],
                "data": [[0.04]],
            }
        },
        "execution_allowed": False,
    }
    monkeypatch.setattr(ui_facade, "load_portfolio_holdings_projection", lambda *_args, **_kwargs: projection)
    monkeypatch.setattr(ui_facade, "load_forecast_return_distributions", lambda *_args, **_kwargs: {"AAA": analysis_input["distributions"]["AAA"]})
    analysis = SimpleNamespace(
        snapshot_binding=SimpleNamespace(
            portfolio_id=portfolio["portfolio_id"],
            snapshot_id=portfolio["snapshot_id"],
            as_of=portfolio["as_of"],
        ),
        service_evidence={"risk": risk_projection},
        candidate=SimpleNamespace(candidate_id="candidate-1", targets={"AAA": 1.0}, cash_weight=0.0),
        current_cash_weight=0.0,
    )

    result = ui_facade.load_portfolio_forecast_aggregation(
        SimpleNamespace(forecasts=None),
        analysis,
        horizon_days=30,
        output_currency="EUR",
    )

    assert result.status == "available"
    assert result.current["coverage"]["confidence"] == 1.0
    assert result.provenance["risk_candidate_id"] == "candidate-1"


def test_facade_uses_reconciled_snapshot_total_including_cash_for_target_notional(monkeypatch) -> None:
    portfolio, analysis_input, _ = _inputs()
    distribution = deepcopy(analysis_input["distributions"]["AAA"])
    distribution["gross_quantiles"] = {key: 0.10 for key in distribution["gross_quantiles"]}
    distribution["net_quantiles"] = dict(distribution["gross_quantiles"])
    distribution["cost_deductions"] = {"fee": 0.0, "spread": 0.0, "impact": 0.0, "fx": 0.0}
    projection = {
        "portfolio_snapshot": {
            "portfolio_id": portfolio["portfolio_id"],
            "snapshot_id": portfolio["snapshot_id"],
            "as_of": portfolio["as_of"],
            "source_checksum": portfolio["source_checksum"],
        },
        "performance_snapshot": {
            "securities_value_output_currency": {"status": "available", "value": 800.0},
            "cash_value_output_currency": {"status": "available", "value": 200.0},
            "total_value_output_currency": {"status": "available", "value": 1000.0},
            "reconciliation": {"status": "available", "value": True},
            "portfolio_value_reconciliation": {"status": "available", "value": True},
        },
        "rows": [
            {
                "instrument_id": "AAA",
                "weight": {"status": "available", "value": 0.8},
                "value": {"status": "available", "value": 800.0},
            }
        ],
        "analysis_run_id": "analysis-run-1",
        "analysis_date": "2026-09-30",
        "analysis_current": True,
        "proposal_handoff_allowed": True,
    }
    risk_projection = {
        "status": "available",
        "model_version": "robust_risk.v1",
        "selected_estimator": "sample",
        "covariances": {"sample": {"columns": ["AAA"], "index": ["AAA"], "data": [[0.04]]}},
        "execution_allowed": False,
    }
    monkeypatch.setattr(ui_facade, "load_portfolio_holdings_projection", lambda *_args, **_kwargs: projection)
    monkeypatch.setattr(ui_facade, "load_forecast_return_distributions", lambda *_args, **_kwargs: {"AAA": distribution})
    analysis = SimpleNamespace(
        snapshot_binding=SimpleNamespace(
            portfolio_id=portfolio["portfolio_id"],
            snapshot_id=portfolio["snapshot_id"],
            as_of=portfolio["as_of"],
        ),
        service_evidence={"risk": risk_projection},
        candidate=SimpleNamespace(candidate_id="candidate-1", targets={"AAA": 1.0}, cash_weight=0.0),
        current_cash_weight=0.2,
    )

    result = ui_facade.load_portfolio_forecast_aggregation(
        SimpleNamespace(forecasts=None),
        analysis,
        horizon_days=30,
        output_currency="EUR",
    )

    assert result.target["reconciliation"]["portfolio_value"] == 1000.0
    assert result.target["net"]["expected_gain_loss"]["value"] == 100.0
