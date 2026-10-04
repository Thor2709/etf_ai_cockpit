from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import ui_facade
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import ComponentScores, DataQualityReport, ForecastResult, SignalResult
from etf_cockpit.features import macro, regime, volatility
from etf_cockpit.parsers.priips_kid import PriipsKidRecord
from etf_cockpit.services import BacktestService, _load_structure_caps, _postprocess_forecast_benchmark_fields
from etf_cockpit.signals import simple_scores
from etf_cockpit.signals.gates import evaluate_risk_gates
from etf_cockpit.signals.scoring import component_scores
from etf_cockpit.signals.signal_pipeline import _attach_authority, _technical_expected_edge


def _gate_row(**overrides: object) -> pd.Series:
    row: dict[str, object] = {
        "etf_id": "AAA",
        "trend_200": 1.0,
        "drawdown_60d_max": -0.05,
        "expected_edge_60d": 0.05,
        "cost_bps": 10.0,
        "current_weight": 0.0,
    }
    row.update(overrides)
    return pd.Series(row)


def _risk_report() -> DataQualityReport:
    return DataQualityReport(as_of_date=date(2025, 1, 2), issues=[])


def test_buy_gate_blocks_when_drawdown_evidence_is_missing() -> None:
    blocked, _warnings = evaluate_risk_gates(
        load_config(),
        _gate_row(drawdown_60d_max=None),
        _risk_report(),
        candidate_action="buy",
        projected_weight=None,
        cash_weight=1.0,
    )

    assert "expected_drawdown_unavailable" in blocked


@pytest.mark.parametrize("missing_field", ["cost_bps", "expected_edge_60d"])
def test_trade_gate_blocks_when_edge_to_cost_evidence_is_missing(missing_field: str) -> None:
    blocked, _warnings = evaluate_risk_gates(
        load_config(),
        _gate_row(**{missing_field: None}),
        _risk_report(),
        candidate_action="buy",
        projected_weight=None,
        cash_weight=1.0,
    )

    assert "edge_inputs_unavailable" in blocked


def test_authority_publication_keeps_missing_edge_cost_evidence_blocked() -> None:
    signal = SignalResult(
        run_id="run-cost-missing",
        signal_date=date(2025, 1, 2),
        etf_id="AAA",
        action="buy",
        confidence=0.7,
        total_score=0.4,
        components=ComponentScores(
            momentum=0.4,
            trend=0.3,
            risk=0.2,
            rebalance=0.1,
            relative_strength=0.2,
            toto=0.0,
            timesfm=0.0,
            baseline_ml=0.4,
            chatgpt_thesis=0.0,
            cost_penalty=0.0,
            turnover_penalty=0.0,
            concentration_penalty=0.0,
        ),
        blocked_by=["edge_inputs_unavailable"],
        warnings=[],
        reason_short="missing edge inputs",
        reason_long="Expected edge or transaction cost evidence is unavailable.",
        horizon_primary="1-3 months",
        model_versions_used={"baseline": "momentum_shrunk_v1"},
    )

    resolved = _attach_authority(signal, _risk_report())
    cost_gate = next(gate for gate in resolved.authority_decision.gates if gate.gate_id == "cost")

    assert cost_gate.passed is False
    assert "edge_inputs_unavailable" in cost_gate.message
    assert "unavailable" in cost_gate.message


@pytest.mark.parametrize("missing_field", ["trend_slope", "trend_100", "trend_200"])
def test_each_missing_trend_input_makes_trend_score_unavailable(missing_field: str) -> None:
    features = pd.DataFrame(
        [
            {
                "etf_id": "AAA",
                "momentum_20d": 0.01,
                "momentum_60d": 0.02,
                "momentum_120d": 0.03,
                "momentum_180d": 0.04,
                "trend_slope": 0.01,
                "trend_100": 1.0,
                "trend_200": 1.0,
                "vol_60d_ann": 0.2,
                "ewma_vol_ann": 0.2,
                "drawdown_60d_max": -0.05,
                "relative_strength_60d": 0.02,
            }
        ]
    )
    features.loc[0, missing_field] = None
    allocation = pd.DataFrame(
        [{"etf_id": "AAA", "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}]
    )

    scored = component_scores(features, allocation, load_config(), toto_available=True, timesfm_available=True)
    row = scored.iloc[0]

    assert pd.isna(row["score_trend"])
    assert "trend_inputs_unavailable" in row["score_unavailable_reason_codes"]


def test_missing_drawdown_alone_makes_risk_score_unavailable() -> None:
    features = pd.DataFrame(
        [
            {
                "etf_id": "AAA",
                "momentum_20d": 0.01,
                "momentum_60d": 0.02,
                "momentum_120d": 0.03,
                "momentum_180d": 0.04,
                "trend_slope": 0.01,
                "trend_100": 1.0,
                "trend_200": 1.0,
                "vol_60d_ann": 0.2,
                "ewma_vol_ann": 0.2,
                "drawdown_60d_max": None,
                "relative_strength_60d": 0.02,
            }
        ]
    )
    allocation = pd.DataFrame(
        [{"etf_id": "AAA", "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}]
    )

    row = component_scores(features, allocation, load_config(), toto_available=True, timesfm_available=True).iloc[0]

    assert pd.notna(row["score_trend"])
    assert pd.isna(row["score_risk"])
    assert "risk_inputs_unavailable" in row["score_unavailable_reason_codes"]


def test_missing_relative_strength_alone_makes_relative_score_unavailable() -> None:
    features = pd.DataFrame(
        [
            {
                "etf_id": "AAA",
                "momentum_20d": 0.01,
                "momentum_60d": 0.02,
                "momentum_120d": 0.03,
                "momentum_180d": 0.04,
                "trend_slope": 0.01,
                "trend_100": 1.0,
                "trend_200": 1.0,
                "vol_60d_ann": 0.2,
                "ewma_vol_ann": 0.2,
                "drawdown_60d_max": -0.05,
                "relative_strength_60d": None,
            }
        ]
    )
    allocation = pd.DataFrame(
        [{"etf_id": "AAA", "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}]
    )

    row = component_scores(features, allocation, load_config(), toto_available=True, timesfm_available=True).iloc[0]

    assert pd.notna(row["score_trend"])
    assert pd.notna(row["score_risk"])
    assert pd.isna(row["score_relative_strength"])
    assert "relative_strength_unavailable" in row["score_unavailable_reason_codes"]


def test_unavailable_toto_is_not_weighted_as_a_neutral_score() -> None:
    features = pd.DataFrame(
        [
            {
                "etf_id": "AAA",
                "momentum_20d": 0.01,
                "momentum_60d": 0.02,
                "momentum_120d": 0.03,
                "momentum_180d": 0.04,
                "trend_slope": 0.01,
                "trend_100": 1.0,
                "trend_200": 1.0,
                "vol_60d_ann": 0.2,
                "ewma_vol_ann": 0.2,
                "drawdown_60d_max": -0.05,
                "relative_strength_60d": 0.02,
            }
        ]
    )
    allocation = pd.DataFrame(
        [{"etf_id": "AAA", "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}]
    )

    scored = component_scores(features, allocation, load_config(), toto_available=False)

    assert pd.isna(scored.iloc[0]["score_toto"])
    assert scored.iloc[0]["score_unavailable_reason_codes"] == "toto_forecast_unavailable|timesfm_forecast_unavailable"


def test_technical_expected_edge_is_unavailable_when_a_required_input_is_missing() -> None:
    scored = pd.DataFrame({"momentum_60d": [0.1], "momentum_120d": [0.2], "relative_strength_60d": [None]})

    expected_edge = _technical_expected_edge(scored)

    assert pd.isna(expected_edge.iloc[0])


def test_ewma_volatility_keeps_missing_returns_unavailable_without_zero_observations() -> None:
    log_returns = pd.Series([0.1, None, -0.1])

    result = volatility.ewma_volatility(log_returns, lambda_=0.5)
    observed_only = pd.Series([0.1, -0.1]).pow(2).ewm(alpha=0.5, adjust=False, ignore_na=True).mean()

    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx((observed_only.iloc[-1] * 252) ** 0.5)


def test_missing_forecast_volatility_leaves_benchmark_probability_unavailable_with_reason() -> None:
    forecast = ForecastResult(
        run_id="run-1",
        model_name="baseline",
        model_version="v1",
        etf_id="AAA",
        forecast_date=date(2025, 1, 2),
        horizon_days=30,
        expected_return=0.1,
        expected_excess_return=None,
        forecast_vol=None,
    )

    result = _postprocess_forecast_benchmark_fields([forecast], pd.Series([0.01, 0.02]))[0]

    assert result.expected_excess_return is not None
    assert result.prob_beat_benchmark is None
    assert result.reason_unavailable == "forecast_vol_unavailable_for_benchmark_probability"


def test_structural_load_failure_has_zero_confidence_cap_and_explicit_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit import services
    import etf_cockpit.application.structural_evidence as structural_evidence
    import etf_cockpit.application.backtest_service as backtest_service

    def fail_load() -> None:
        raise ValueError("corrupt structural evidence")

    monkeypatch.setattr(services, "_load_local_structural_evidence", fail_load)
    monkeypatch.setattr(backtest_service, "_load_local_structural_evidence", services._load_local_structural_evidence)
    monkeypatch.setattr(structural_evidence, "_load_local_structural_evidence", services._load_local_structural_evidence)

    caps = _load_structure_caps(["AAA"], date(2025, 1, 2))

    assert caps["AAA"] == 0.0
    assert caps.provenance["AAA"]["status"] == "unavailable"
    assert caps.provenance["AAA"]["reason_code"] == "structural_evidence_load_failed"
    assert "ValueError" in caps.provenance["AAA"]["reason"]


def test_unexpected_structural_load_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit import services
    import etf_cockpit.application.structural_evidence as structural_evidence
    import etf_cockpit.application.backtest_service as backtest_service

    def fail_load() -> None:
        raise RuntimeError("unexpected loader failure")

    monkeypatch.setattr(services, "_load_local_structural_evidence", fail_load)
    monkeypatch.setattr(backtest_service, "_load_local_structural_evidence", services._load_local_structural_evidence)
    monkeypatch.setattr(structural_evidence, "_load_local_structural_evidence", services._load_local_structural_evidence)

    with pytest.raises(RuntimeError, match="unexpected loader failure"):
        _load_structure_caps(["AAA"], date(2025, 1, 2))


def test_backtest_does_not_run_after_structural_evidence_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit import services
    import etf_cockpit.application.backtest_service as backtest_service
    import etf_cockpit.application.feature_service as feature_service
    import etf_cockpit.application.forecast_service as forecast_service
    import etf_cockpit.application.reference_context as reference_context
    import etf_cockpit.application.structural_evidence as structural_evidence

    monkeypatch.setattr(services, "current_settings_identity", lambda: "settings")
    monkeypatch.setattr(backtest_service, "current_settings_identity", services.current_settings_identity)
    monkeypatch.setattr(feature_service, "current_settings_identity", services.current_settings_identity)
    monkeypatch.setattr(forecast_service, "current_settings_identity", services.current_settings_identity)
    monkeypatch.setattr(services, "load_prices", pd.DataFrame)
    monkeypatch.setattr(backtest_service, "load_prices", services.load_prices)
    monkeypatch.setattr(feature_service, "load_prices", services.load_prices)
    monkeypatch.setattr(forecast_service, "load_prices", services.load_prices)
    monkeypatch.setattr(services, "_backtest_calculation_context", lambda *_args: None)
    monkeypatch.setattr(backtest_service, "_backtest_calculation_context", services._backtest_calculation_context)
    monkeypatch.setattr(reference_context, "_backtest_calculation_context", services._backtest_calculation_context)
    monkeypatch.setattr(services, "load_fundamental_evidence", pd.DataFrame)
    monkeypatch.setattr(backtest_service, "load_fundamental_evidence", services.load_fundamental_evidence)
    monkeypatch.setattr(services, "_load_local_structural_evidence", lambda: (_ for _ in ()).throw(ValueError("corrupt")))
    monkeypatch.setattr(backtest_service, "_load_local_structural_evidence", services._load_local_structural_evidence)
    monkeypatch.setattr(structural_evidence, "_load_local_structural_evidence", services._load_local_structural_evidence)

    report = BacktestService(load_config(), universe_revision="audit-test").run_backtest()

    assert report.results.empty
    assert any("Structural evidence unavailable" in note for note in report.quality_notes)


def test_missing_exposure_weights_make_the_component_unavailable() -> None:
    component = simple_scores._etf_exposure_component({"holding_count": 10})

    assert component.score_10 is None
    assert component.status == "N/A"
    assert "concentration evidence is incomplete" in component.why


def test_simple_score_freshness_uses_explicit_historical_decision_date() -> None:
    assert simple_scores._component_freshness_status("2024-01-01", date(2024, 1, 10)) == "ok"
    assert simple_scores._component_freshness_status("2024-01-01", date(2024, 1, 16)) == "stale"
    assert simple_scores._component_freshness_status("2024-01-17", date(2024, 1, 16)) == "unavailable"


def test_kid_cost_scores_use_the_explicit_decision_as_of_date() -> None:
    def record(cost: str) -> SimpleNamespace:
        return SimpleNamespace(
            document_date="2025-01-01",
            source_sha256="f" * 64,
            warnings=(),
            cost_fields={"ongoing_costs": cost},
            sri=4,
            score_eligible=True,
            manual_review=False,
        )

    lower_cost = simple_scores.build_priips_kid_cost_evidence(record("0.05%"), as_of_date=date(2025, 1, 10))
    higher_cost = simple_scores.build_priips_kid_cost_evidence(record("0.50%"), as_of_date=date(2025, 1, 10))

    assert lower_cost.freshness_status == higher_cost.freshness_status == "ok"
    assert lower_cost.score_eligible and higher_cost.score_eligible
    assert higher_cost.score_10 < lower_cost.score_10
    assert higher_cost.raw_score < lower_cost.raw_score


def test_kid_cost_evidence_without_decision_date_is_unavailable() -> None:
    record = PriipsKidRecord(
        product="Example ETF",
        isin="IE000Q4J3CW6",
        manufacturer="Vanguard",
        sri=4,
        cost_fields={"ongoing_costs": "0.07% of the value of your investment p.a. EUR 7"},
        holding_period_years=5,
        scenarios=("moderate",),
        document_date="2025-01-06",
        extraction_confidence="high",
        warnings=(),
        source_sha256="k" * 64,
        source_pages=(1, 2, 3),
        manual_review=False,
        score_eligible=True,
    )

    component = simple_scores.build_priips_kid_cost_evidence(record)

    assert component.freshness_status == "unknown"
    assert component.score_eligible is False
    assert component.score_10 is None


def _macro_prices() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=240, freq="B")
    return pd.DataFrame(
        [
            {"date": current, "etf_id": instrument, "adjusted_close": 100.0 + index * slope}
            for index, current in enumerate(dates)
            for instrument, slope in (("EQUITY", 0.2), ("BOND", 0.03), ("GOLD", 0.08))
        ]
    )


def test_macro_freshness_uses_passed_as_of_date_and_excludes_future_prices() -> None:
    prices = _macro_prices()
    as_of_date = pd.to_datetime(prices["date"].max()).date()
    future = pd.DataFrame([{"date": pd.Timestamp(as_of_date) + pd.Timedelta(days=2), "etf_id": "EQUITY", "adjusted_close": 500.0}])

    first = macro.build_macro_context(pd.concat([prices, future], ignore_index=True), as_of_date=as_of_date)
    second = macro.build_macro_context(pd.concat([prices, future], ignore_index=True), as_of_date=as_of_date)

    assert first == second
    assert first["as_of"] == as_of_date.isoformat()
    assert first["freshness_days"] == 0


def test_macro_decision_time_excludes_same_day_prices_after_explicit_as_of_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macro, "validate_benchmark_reference", lambda *_args, **_kwargs: "BENCH")
    prices = pd.DataFrame(
        [
            {"date": "2024-01-09T18:00:00Z", "etf_id": "EQUITY", "adjusted_close": 100.0},
            {"date": "2024-01-10T10:00:00Z", "etf_id": "EQUITY", "adjusted_close": 110.0},
            {"date": "2024-01-10T12:00:00Z", "etf_id": "EQUITY", "adjusted_close": 999.0},
            {"date": "2024-01-10T18:00:00Z", "etf_id": "EQUITY", "adjusted_close": 500.0},
        ]
    )
    reference = {"status": "unavailable", "analysis": {"decision_time": "2024-01-10T12:00:00Z"}}

    result = macro.build_macro_context(
        prices,
        benchmark_data_id="BENCH",
        benchmark_reference=reference,
        as_of_date=date(2024, 1, 10),
    )

    equity = next(row for row in result["proxy_rows"] if row["proxy"] == "equity")
    assert result["as_of"] == "2024-01-10"
    assert equity["period_return_20d"] == pytest.approx(0.1)


def test_macro_price_projection_excludes_prices_known_after_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macro, "validate_benchmark_reference", lambda *_args, **_kwargs: "BENCH")
    prices = pd.DataFrame(
        [
            {"date": "2024-01-09T18:00:00Z", "known_at": "2024-01-09T18:00:00Z", "etf_id": "EQUITY", "adjusted_close": 100.0},
            {"date": "2024-01-10T10:00:00Z", "known_at": "2024-01-10T13:00:00Z", "etf_id": "EQUITY", "adjusted_close": 999.0},
        ]
    )
    reference = {"status": "unavailable", "analysis": {"decision_time": "2024-01-10T12:00:00Z"}}

    result = macro.build_macro_context(
        prices,
        benchmark_data_id="BENCH",
        benchmark_reference=reference,
        as_of_date=date(2024, 1, 10),
    )

    assert result["as_of"] == "2024-01-09"


def test_macro_observations_exclude_effective_times_after_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macro, "validate_benchmark_reference", lambda *_args, **_kwargs: "BENCH")
    decision_time = "2024-01-10T12:00:00Z"
    reference = {"status": "unavailable", "analysis": {"decision_time": decision_time}}
    observations = [
        {
            "series_id": "cpi_inflation",
            "value": 3.0,
            "unit": "%",
            "source_id": "local",
            "observed_at": "2024-01-09T00:00:00Z",
            "available_at": "2024-01-09T23:59:00Z",
            "timezone_confidence": "exact",
            "availability_confidence": "exact",
        },
        {
            "series_id": "cpi_inflation",
            "value": 4.0,
            "unit": "%",
            "source_id": "local",
            "observed_at": "2024-01-10T12:00:00Z",
            "available_at": "2024-01-10T11:00:00Z",
            "timezone_confidence": "exact",
            "availability_confidence": "exact",
        },
        {
            "series_id": "cpi_inflation",
            "value": 5.0,
            "unit": "%",
            "source_id": "local",
            "observed_at": "2024-01-10T13:00:00Z",
            "available_at": "2024-01-10T11:00:00Z",
            "timezone_confidence": "exact",
            "availability_confidence": "exact",
        },
    ]

    result = macro.build_macro_context(
        _macro_prices(),
        observations=observations,
        benchmark_data_id="BENCH",
        benchmark_reference=reference,
        as_of_date=date(2024, 1, 10),
    )

    assert [row["value"] for row in result["inflation_rates"]["rows"]] == [3.0]


def test_empty_signal_scoring_uses_nested_benchmark_decision_date(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate_report = pd.DataFrame(
        [
            {
                "instrument_id": "ABC",
                "name": "ABC Test Stock",
                "yahoo_symbol": "ABC.DE",
                "latest_date": "2025-01-10",
                "latest_price": 100.0,
                "rows": 300,
                "return_3m": 0.10,
                "return_6m": 0.18,
                "return_12m": 0.25,
                "volatility_60d_ann": 0.18,
                "current_drawdown": -0.04,
                "sma50_signal": True,
                "sma200_signal": True,
                "median_turnover_60d_eur": 2_500_000,
                "blocked_by": "",
            }
        ]
    )
    monkeypatch.setattr(simple_scores, "load_latest_candidate_report", lambda: (candidate_report, None))
    monkeypatch.setattr(simple_scores, "load_candidate_price_binding", lambda: None)
    monkeypatch.setattr(simple_scores, "load_forecast_history", pd.DataFrame)
    monkeypatch.setattr(simple_scores, "evaluate_forecast_calibration", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(simple_scores, "build_market_regime", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(simple_scores, "build_portfolio_fit_lookup", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(simple_scores, "build_benchmark_attribution_lookup", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(simple_scores, "build_universe_simple_scores", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(simple_scores, "_latest_candidate_input_frame", pd.DataFrame)
    monkeypatch.setattr(simple_scores, "_etf_exposure_lookup", dict)
    monkeypatch.setattr(simple_scores, "_backtest_trust_lookup", lambda **_kwargs: {})
    monkeypatch.setattr(simple_scores, "_news_inventory_lookup", dict)
    reference = {"status": "unavailable", "analysis": {"decision_time": "2025-01-15T00:00:00Z"}}

    scores = simple_scores.build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        pd.DataFrame(),
        universe_revision="audit-test",
        cash_comparison_lookup={},
        benchmark_reference=reference,
    )

    candidate = next(score for score in scores if score.display_id == "ABC")
    freshness = next(component.freshness_status for component in candidate.components if component.key == "momentum")
    data_quality = next(component for component in candidate.components if component.key == "data_quality")
    assert freshness == "ok"
    assert data_quality.score_10 is not None


def test_macro_observations_available_at_decision_time_are_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macro, "validate_benchmark_reference", lambda *_args, **_kwargs: "BENCH")
    decision_time = "2024-01-10T12:00:00Z"
    reference = {"status": "unavailable", "analysis": {"decision_time": decision_time}}
    observations = [
        {
            "series_id": "cpi_inflation",
            "value": 3.0,
            "unit": "%",
            "source_id": "local",
            "observed_at": "2024-01-09T00:00:00Z",
            "available_at": "2024-01-09T23:59:00Z",
            "timezone_confidence": "exact",
            "availability_confidence": "exact",
        },
        {
            "series_id": "cpi_inflation",
            "value": 3.5,
            "unit": "%",
            "source_id": "local",
            "observed_at": "2024-01-09T00:00:00Z",
            "available_at": "2024-01-10T11:00:00Z",
            "timezone_confidence": "exact",
            "availability_confidence": "exact",
        },
        {
            "series_id": "cpi_inflation",
            "value": 4.0,
            "unit": "%",
            "source_id": "local",
            "observed_at": "2024-01-09T00:00:00Z",
            "available_at": decision_time,
            "timezone_confidence": "exact",
            "availability_confidence": "exact",
        },
    ]

    result = macro.build_macro_context(
        _macro_prices(),
        observations=observations,
        benchmark_data_id="BENCH",
        benchmark_reference=reference,
        as_of_date=date(2024, 1, 10),
    )

    assert result["inflation_rates"]["status"] == "available"
    assert [(row["value"], row["available_at"]) for row in result["inflation_rates"]["rows"]] == [
        (3.0, "2024-01-09T23:59:00Z"),
        (3.5, "2024-01-10T11:00:00Z"),
    ]


def test_macro_missing_evaluation_date_reports_freshness_unavailable() -> None:
    result = macro.build_macro_context(_macro_prices())

    assert result["freshness_days"] is None
    assert result["freshness_status"] == "unavailable"
    assert all(row["freshness_status"] == "unavailable" for row in result["proxy_rows"])


def test_scoreboard_parquet_read_failure_is_not_converted_to_an_empty_frame(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "scoreboard.parquet"
    path.write_bytes(b"broken")

    def fail_read(_path: object) -> pd.DataFrame:
        raise ValueError("corrupt scoreboard parquet")

    monkeypatch.setattr(simple_scores.pd, "read_parquet", fail_read)

    with pytest.raises(ValueError, match="corrupt scoreboard parquet"):
        simple_scores.load_simple_scoreboard(path)


def test_regime_is_unavailable_when_benchmark_return_horizons_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.bdate_range("2025-01-01", periods=220)
    rows = []
    for index, current in enumerate(dates):
        rows.append({"date": current, "etf_id": "ALT", "adjusted_close": 100.0 + index})
        if index >= 170:
            rows.append({"date": current, "etf_id": "BENCH", "adjusted_close": 100.0 + index})
    prices = pd.DataFrame(rows)
    monkeypatch.setattr(regime, "validate_benchmark_reference", lambda *_args, **_kwargs: "BENCH")
    monkeypatch.setattr(regime, "_clip_to_reference_window", lambda frame, _reference: frame)

    result = regime.build_market_regime(prices, benchmark_id="BENCH")

    assert result["regime_score_10"] is None
    assert "Benchmark return evidence is unavailable" in result["summary"]


@pytest.mark.parametrize("cutoff_field", ["effective_at", "known_at"])
def test_regime_excludes_candidate_evidence_at_decision_time(
    monkeypatch: pytest.MonkeyPatch,
    cutoff_field: str,
) -> None:
    monkeypatch.setattr(regime, "validate_benchmark_reference", lambda *_args, **_kwargs: "BENCH")
    monkeypatch.setattr(regime, "_clip_to_reference_window", lambda frame, _reference: frame)
    decision_time = "2024-01-10T12:00:00Z"
    reference = {
        "status": "unavailable",
        "execution_allowed": False,
        "analysis": {"decision_time": decision_time},
    }
    dates = pd.bdate_range(end="2024-01-09", periods=220)
    prices = pd.DataFrame(
        [
            {"date": current, "etf_id": "BENCH", "adjusted_close": 100.0 + index}
            for index, current in enumerate(dates)
        ]
    )
    candidate = {"sma200_signal": True, "provenance": "local candidate evidence"}
    if cutoff_field == "effective_at":
        candidate[cutoff_field] = decision_time
    else:
        candidate.update({"effective_at": "2024-01-09T00:00:00Z", cutoff_field: decision_time})

    result = regime.build_market_regime(
        prices,
        pd.DataFrame([candidate]),
        benchmark_id="BENCH",
        benchmark_reference=reference,
    )

    assert result["regime_score_10"] is not None
    assert result["candidate_pct_above_sma200"] is None


def test_total_return_chart_seeds_only_the_first_undefined_fx_return(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from etf_cockpit.data import market_adjustments

    monkeypatch.setattr(
        market_adjustments,
        "derive_fx_cross",
        lambda *_args, **_kwargs: SimpleNamespace(available=True, rate=1.0),
    )
    prices = pd.DataFrame(
        [
            {"date": pd.Timestamp("2024-01-01"), "etf_id": "AAA", "close": 100.0, "known_at": "2024-01-01T18:00:00Z"},
            {"date": pd.Timestamp("2024-01-02"), "etf_id": "AAA", "close": 110.0, "known_at": "2024-01-02T18:00:00Z"},
            {"date": pd.Timestamp("2024-01-02"), "etf_id": "AAA", "close": 999.0, "known_at": "2024-01-05T18:00:00Z"},
            {"date": pd.Timestamp("2024-01-03"), "etf_id": "AAA", "close": 120.0, "known_at": "2024-01-03T18:00:00Z"},
        ]
    )

    result = ui_facade._load_market_series_projection(
        prices,
        "AAA",
        basis="raw",
        local_currency="EUR",
        output_currency="USD",
        storage_root=tmp_path,
        decision_time="2024-01-04T00:00:00Z",
    )

    assert result["status"] == "available"
    frame = result["frame"]
    assert len(frame) == 3
    assert 999.0 not in frame["raw_close"].tolist()
    assert frame["output_total_return"].iloc[0] == 0.0
    assert frame["output_total_return"].iloc[1:].notna().all()


def test_total_return_chart_rejects_a_later_fx_return_gap(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from etf_cockpit.data import market_adjustments

    def derive_fx(_observations: object, _local: str, _output: str, value: object, **_kwargs: object) -> SimpleNamespace:
        rate = float("nan") if pd.Timestamp(value) == pd.Timestamp("2024-01-03T00:00:00Z") else 1.0
        return SimpleNamespace(available=True, rate=rate)

    monkeypatch.setattr(market_adjustments, "derive_fx_cross", derive_fx)
    prices = pd.DataFrame(
        [
            {"date": pd.Timestamp("2024-01-01"), "etf_id": "AAA", "close": 100.0, "known_at": "2024-01-01T18:00:00Z"},
            {"date": pd.Timestamp("2024-01-02"), "etf_id": "AAA", "close": 110.0, "known_at": "2024-01-02T18:00:00Z"},
            {"date": pd.Timestamp("2024-01-03"), "etf_id": "AAA", "close": 120.0, "known_at": "2024-01-03T18:00:00Z"},
        ]
    )

    result = ui_facade._load_market_series_projection(
        prices,
        "AAA",
        basis="raw",
        local_currency="EUR",
        output_currency="USD",
        storage_root=tmp_path,
        decision_time="2024-01-04T00:00:00Z",
    )

    assert result["status"] == "unavailable"
    assert result["reason_code"] == "required_total_return_input_missing"


def test_dependent_callers_report_corrupt_scoreboard_as_unavailable(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    corrupt = tmp_path / "scoreboard.parquet"
    corrupt.write_bytes(b"not parquet")
    monkeypatch.setattr(selector, "SCOREBOARD_PATH", corrupt)

    friction = selector._friction_panel("VWCE", candidate_score=None)
    assert friction["status"] == "unavailable"
    assert friction["reason_code"] == "scoreboard_store_unreadable"
    assert "unavailable" in friction["friction_reason"]
    assert friction["execution_allowed"] is False
    assert selector._scoreboard_row("VWCE") == {}
    # The loader itself must keep raising: no empty-frame conversion.
    with pytest.raises(ValueError):
        simple_scores.load_simple_scoreboard(corrupt)


def test_market_series_excludes_bar_dated_at_decision_cutoff_and_keeps_earlier_bar(tmp_path) -> None:
    prices = pd.DataFrame(
        {
            "etf_id": ["ETF-1", "ETF-1"],
            "date": ["2024-01-10", "2024-01-11"],
            "close": [100.0, 101.0],
            "adjusted_close": [100.0, 101.0],
        }
    )
    at_cutoff = ui_facade.load_market_series_projection(
        prices, "ETF-1", basis="raw", local_currency="EUR", storage_root=tmp_path, decision_time="2024-01-11T00:00:00Z"
    )
    after = ui_facade.load_market_series_projection(
        prices, "ETF-1", basis="raw", local_currency="EUR", storage_root=tmp_path, decision_time="2024-01-12T00:00:00Z"
    )
    assert at_cutoff["frame"]["series_value"].tolist() == [100.0]
    assert after["frame"]["series_value"].tolist() == [100.0, 101.0]


def test_cash_comparison_requires_matching_instrument_currency() -> None:
    injected = {"status": "available", "instrument_id": "X", "currency": "EUR", "execution_allowed": False}
    info = simple_scores._cash_comparison_info({"X": injected}, "X", expected_currency="NOK")
    assert info["cash_comparison_status"] == "unavailable"
    assert info["cash_return"] is None
