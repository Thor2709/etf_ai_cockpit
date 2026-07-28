from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.parsers.priips_kid import PriipsKidRecord
from etf_cockpit.app.router import build_shell
from etf_cockpit.app.components.simple_scores import _component_row, simple_score_grouped_sections, simple_score_tiles
from etf_cockpit.app.components.simple_scores import _score_history_panel
from etf_cockpit.app.state import AppState
from etf_cockpit.core.config import load_config
from etf_cockpit.core.paths import RAW_DIR
from etf_cockpit.data.classification import ClassificationOverride, ClassificationStore
from etf_cockpit.services import DataService, build_snapshot
from etf_cockpit.signals import simple_scores as simple_scores_module
from etf_cockpit.signals.friction_edge import estimate_friction_edge
from etf_cockpit.signals.simple_scores import (
    SimpleInstrumentScore,
    SimpleScoreComponent,
    _evidence_maturity,
    _model_backtest_validity,
    build_candidate_simple_scores,
    build_simple_instrument_scores,
    combine_component_scores,
    decision_from_score,
    final_label_from_scores,
    group_simple_scores,
    load_simple_scoreboard,
    raw_to_score_10,
    simple_scoreboard_frame,
    write_simple_scoreboard,
)


PRIMARY_IDS = {
    "VWCE",
    "LYP6",
    "SPYK",
    "SXRJ_EMU_SMALL",
    "EXX1",
    "UCG",
    "SU",
    "LR",
    "PRY",
    "NEX",
    "DB1",
    "ENX",
    "VIE",
    "SGO",
    "FLXI",
    "H4ZT",
}

SECONDARY_IDS = {
    "AIR",
    "BA",
    "BRK_B",
    "AM",
    "IDR",
    "KOG",
    "KMAR",
    "LDO",
    "MSFT",
    "RR",
    "SAAB_B",
    "SPCX",
    "SBNOR",
    "HO",
    "TKA",
    "TKMS",
    "EUNK",
    "CBUK",
    "SEC0",
    "SXRV_NASDAQ100",
    "JEDI",
    "VFEM",
    "VUSA",
    "EUDF",
    "XAIX",
    "EXUS",
    "XDWU",
    "RABO",
}

SPAREBANKEN_IDS = {
    "AURG",
    "HELG",
    "HSPG",
    "SOGN",
    "JAEREN",
    "MELG",
    "SADG",
    "SKUE",
    "NONG",
    "RING",
    "MING",
    "SOAG",
    "SPOL",
    "MORG",
    "SPOG",
}

SPAREBANKEN_NEEDS_VERIFICATION = {"AURG", "SOGN", "MELG", "SADG", "SKUE"}


def test_raw_score_conversion_to_x_out_of_ten() -> None:
    assert raw_to_score_10(-1.0) == 0.0
    assert raw_to_score_10(0.0) == 5.0
    assert raw_to_score_10(1.0) == 10.0
    assert raw_to_score_10(2.0) == 10.0
    assert raw_to_score_10(None) is None


def test_decision_threshold_mapping() -> None:
    assert decision_from_score(8.0) == "Strong Evidence Candidate"
    assert decision_from_score(6.5) == "Positive Evidence Candidate"
    assert decision_from_score(5.0) == "Watchlist"
    assert decision_from_score(4.0) == "Hold Context"
    assert decision_from_score(3.9) == "Weak Evidence Review"
    assert decision_from_score(None) == "Manual Review"


def test_final_label_requires_quality_and_friction() -> None:
    label, action, decision = final_label_from_scores(8.5, 7.5, 6.5, warnings=[])

    assert label == "strong_evidence_candidate"
    assert action == "add_candidate"
    assert decision == "Strong Evidence Candidate"


def test_final_label_demotes_low_quality_high_score() -> None:
    label, action, decision = final_label_from_scores(8.5, 3.5, 8.0, warnings=[])

    assert label == "low_quality_manual_review"
    assert action == "manual_review"
    assert decision == "Manual Review"


def test_model_score_cannot_rescue_weak_deterministic_evidence() -> None:
    components = [
        SimpleScoreComponent("momentum", "Momentum", 1.0, -0.8, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
        SimpleScoreComponent("trend", "Trend", 1.0, -0.8, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
        SimpleScoreComponent("risk", "Risk", 2.0, -0.6, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
        SimpleScoreComponent("timesfm", "TimesFM", 10.0, 1.0, "OK", "", "", "", authority="low", score_role="model_confirmation", as_of_date="2026-07-10", freshness_status="ok"),
    ]
    _raw, evidence_score = combine_component_scores(components, weights={"momentum": 0.3, "trend": 0.3, "risk": 0.3, "timesfm": 0.1})
    label, action, decision = final_label_from_scores(evidence_score, 3.5, 3.5, warnings=[])

    assert evidence_score is not None
    assert label == "low_quality_manual_review"
    assert action == "manual_review"
    assert decision == "Manual Review"


def test_expanded_score_component_renders_source_id() -> None:
    component = SimpleScoreComponent("momentum", "Momentum", 7.0, 0.4, "OK", "", "", "", source_id="yfinance:prices")
    text = "\n".join(_control_texts(_component_row(component)))
    assert "Source" in text
    assert "yfinance:prices" in text


def test_unmapped_score_component_does_not_invent_source_id() -> None:
    component = SimpleScoreComponent("unmapped", "Unmapped", 7.0, 0.4, "OK", "", "", "")

    assert component.source_id is None


def test_source_less_component_cannot_influence_score() -> None:
    components = [
        SimpleScoreComponent("momentum", "Momentum", 10.0, 1.0, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
        SimpleScoreComponent("unmapped", "Unmapped", 0.0, -1.0, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
    ]

    raw, score = combine_component_scores(components, weights={"momentum": 0.5, "unmapped": 0.5})

    assert raw == 1.0
    assert score == 10.0


def test_score_component_requires_as_of_and_freshness_provenance() -> None:
    missing_provenance = SimpleScoreComponent(
        "momentum",
        "Momentum",
        10.0,
        1.0,
        "OK",
        "",
        "",
        "",
        source_id="yfinance:prices",
    )
    assert missing_provenance.score_eligible is False
    assert combine_component_scores([missing_provenance], weights={"momentum": 1.0}) == (None, None)

    valid_provenance = SimpleScoreComponent(
        "momentum",
        "Momentum",
        10.0,
        1.0,
        "OK",
        "",
        "",
        "",
        source_id="yfinance:prices",
        as_of_date="2026-07-10",
        freshness_status="ok",
    )
    assert valid_provenance.score_eligible is True
    assert combine_component_scores([valid_provenance], weights={"momentum": 1.0}) == (1.0, 10.0)


def _kid_for_score(**changes: object) -> PriipsKidRecord:
    values: dict[str, object] = {
        "product": "Example ETF",
        "isin": "IE000Q4J3CW6",
        "manufacturer": "Vanguard",
        "sri": 4,
        "cost_fields": {"ongoing_costs": "0.07% of the value of your investment p.a. EUR 7"},
        "holding_period_years": 5,
        "scenarios": ("moderate",),
        "document_date": pd.Timestamp.today().date().isoformat(),
        "extraction_confidence": "high",
        "warnings": (),
        "source_sha256": "k" * 64,
        "source_pages": (1, 2, 3),
        "manual_review": False,
        "score_eligible": True,
    }
    values.update(changes)
    return PriipsKidRecord(**values)


def test_complete_fresh_kid_is_observable_as_issuer_cost_evidence() -> None:
    record = _kid_for_score()
    assert hasattr(simple_scores_module, "build_priips_kid_cost_evidence")
    component = simple_scores_module.build_priips_kid_cost_evidence(record)

    assert component is not None
    assert component.key == "liquidity_cost"
    assert component.source_id == "priips_kid:" + "k" * 64
    assert component.source_authority == "issuer_document"
    assert component.as_of_date == record.document_date
    assert component.freshness_status == "ok"
    assert component.score_eligible is True
    assert component.score_10 is not None


def test_higher_disclosed_ongoing_cost_never_improves_liquidity_cost_score() -> None:
    lower_cost = _kid_for_score(cost_fields={"ongoing_costs": "0.05% of the value of your investment"})
    higher_cost = _kid_for_score(cost_fields={"ongoing_costs": "0.50% of the value of your investment"})

    lower_component = simple_scores_module.build_priips_kid_cost_evidence(lower_cost)
    higher_component = simple_scores_module.build_priips_kid_cost_evidence(higher_cost)

    assert lower_component.key == higher_component.key == "liquidity_cost"
    assert lower_component.score_10 is not None
    assert higher_component.score_10 is not None
    assert higher_component.score_10 < lower_component.score_10
    assert higher_component.raw_score < lower_component.raw_score


def test_complete_kid_cost_fields_score_the_ongoing_cost_row() -> None:
    base_costs = {
        "entry_costs": "1.00% of the value of your investment",
        "exit_costs": "2.00% of the value of your investment",
        "transaction_costs": "0.10% of the value of your investment per year",
        "performance_fees": "3.00% of profits",
    }
    lower_cost = _kid_for_score(cost_fields={**base_costs, "ongoing_costs": "0.05% of the value of your investment"})
    higher_cost = _kid_for_score(cost_fields={**base_costs, "ongoing_costs": "0.50% of the value of your investment"})

    lower_component = simple_scores_module.build_priips_kid_cost_evidence(lower_cost)
    higher_component = simple_scores_module.build_priips_kid_cost_evidence(higher_cost)

    assert lower_component.key == higher_component.key == "liquidity_cost"
    assert lower_component.score_10 is not None
    assert higher_component.score_10 is not None
    assert higher_component.score_10 < lower_component.score_10
    assert higher_component.raw_score < lower_component.raw_score


def test_kid_cost_evidence_without_numeric_ongoing_cost_is_unavailable() -> None:
    record = _kid_for_score(
        cost_fields={
            "entry_costs": "1.00% of the value of your investment",
            "exit_costs": "2.00% of the value of your investment",
            "ongoing_costs": "Costs vary by portfolio",
            "transaction_costs": "0.10% of the value of your investment per year",
            "performance_fees": "3.00% of profits",
        },
        sri=None,
    )

    component = simple_scores_module.build_priips_kid_cost_evidence(record)

    assert component.key == "risk"
    assert component.raw_score is None
    assert component.score_10 is None
    assert component.status == "N/A"
    assert component.score_eligible is False


def test_higher_sri_never_improves_risk_score() -> None:
    lower_sri = _kid_for_score(cost_fields={}, sri=2)
    higher_sri = _kid_for_score(cost_fields={}, sri=6)

    lower_component = simple_scores_module.build_priips_kid_cost_evidence(lower_sri)
    higher_component = simple_scores_module.build_priips_kid_cost_evidence(higher_sri)

    assert lower_component.key == higher_component.key == "risk"
    assert lower_component.score_10 is not None
    assert higher_component.score_10 is not None
    assert higher_component.score_10 < lower_component.score_10
    assert higher_component.raw_score < lower_component.raw_score


@pytest.mark.parametrize(
    "changes",
    [
        {"manual_review": True, "score_eligible": False, "warnings": ("cost_table_malformed",)},
        {"document_date": "2020-01-01"},
        {"cost_fields": {"ongoing_costs": "What are the costs?"}},
    ],
)
def test_incomplete_or_stale_kid_is_excluded_from_cost_evidence(changes: dict[str, object]) -> None:
    assert hasattr(simple_scores_module, "build_priips_kid_cost_evidence")
    component = simple_scores_module.build_priips_kid_cost_evidence(_kid_for_score(**changes))

    assert component is not None
    assert component.score_eligible is False
    assert component.score_10 is None


def test_model_confirmation_is_visible_but_not_deterministic_score_evidence() -> None:
    components = [
        SimpleScoreComponent("momentum", "Momentum", 10.0, 1.0, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
        SimpleScoreComponent("timesfm", "TimesFM", 0.0, -1.0, "OK", "", "", "", authority="low", score_role="model_confirmation", as_of_date="2026-07-10", freshness_status="ok"),
    ]

    raw, score = combine_component_scores(components, weights={"momentum": 0.5, "timesfm": 0.5})

    assert raw == 1.0
    assert score == 10.0


def test_non_ok_component_cannot_influence_score() -> None:
    components = [
        SimpleScoreComponent("momentum", "Momentum", 10.0, 1.0, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
        SimpleScoreComponent("trend", "Trend", 0.0, -1.0, "blocked", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
    ]

    raw, score = combine_component_scores(components, weights={"momentum": 0.5, "trend": 0.5})

    assert raw == 1.0
    assert score == 10.0


def test_unknown_source_prefix_cannot_influence_score() -> None:
    component = SimpleScoreComponent(
        "momentum",
        "Momentum",
        10.0,
        1.0,
        "OK",
        "",
        "",
        "",
        source_id="unmapped:foo",
    )

    raw, score = combine_component_scores([component], weights={"momentum": 1.0})

    assert raw is None
    assert score is None


def test_final_score_reweights_missing_components() -> None:
    components = [
        SimpleScoreComponent("momentum", "Momentum", 10.0, 1.0, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
        SimpleScoreComponent("timesfm", "TimesFM", None, None, "N/A", "", "", "", as_of_date="2026-07-10", freshness_status="ok"),
    ]
    raw, score = combine_component_scores(components, weights={"momentum": 0.5, "timesfm": 0.5})

    assert raw == 1.0
    assert score == 10.0


def test_candidate_without_portfolio_fields_gets_algorithm_scores() -> None:
    report = pd.DataFrame(
        [
            {
                "instrument_id": "ABC",
                "name": "ABC Test Stock",
                "yahoo_symbol": "ABC.DE",
                "latest_date": pd.Timestamp.today().date().isoformat(),
                "latest_price": 100.0,
                "return_3m": 0.10,
                "return_6m": 0.18,
                "return_12m": 0.25,
                "volatility_60d_ann": 0.18,
                "current_drawdown": -0.04,
                "sma50_signal": True,
                "sma200_signal": True,
                "blocked_by": "",
            }
        ]
    )

    scores = build_candidate_simple_scores(report, pd.DataFrame())

    assert len(scores) == 1
    assert scores[0].instrument_key == "candidate:ABC"
    assert scores[0].final_score_10 is not None
    assert scores[0].evidence_quality_10 is not None
    assert scores[0].risk_friction_10 is not None
    assert scores[0].valid_component_count >= 4


def test_unavailable_model_forecast_is_na_and_excluded() -> None:
    report = pd.DataFrame(
        [
            {
                "instrument_id": "ABC",
                "name": "ABC Test Stock",
                "yahoo_symbol": "ABC.DE",
                "latest_date": pd.Timestamp.today().date().isoformat(),
                "latest_price": 100.0,
                "return_3m": 0.10,
                "return_6m": 0.18,
                "return_12m": 0.25,
                "volatility_60d_ann": 0.18,
                "current_drawdown": -0.04,
                "sma50_signal": True,
                "sma200_signal": True,
                "blocked_by": "",
            }
        ]
    )
    forecasts = pd.DataFrame(
        [
            {
                "model_name": "timesfm",
                "etf_id": "ABC",
                "horizon_days": 60,
                "expected_return": None,
                "status": "skipped",
                "model_allowed_in_score": False,
                "reason_unavailable": "horizon exceeds local model output length",
            }
        ]
    )

    score = build_candidate_simple_scores(report, forecasts)[0]
    timesfm = next(component for component in score.components if component.key == "timesfm")

    assert timesfm.score_10 is None
    assert timesfm.status == "N/A"
    assert score.final_score_10 is not None


def test_scoreboard_frame_contains_quality_and_authority_columns() -> None:
    report = pd.DataFrame(
        [
            {
                "instrument_id": "ABC",
                "name": "ABC Test Stock",
                "yahoo_symbol": "ABC.DE",
                "latest_date": pd.Timestamp.today().date().isoformat(),
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
    score = build_candidate_simple_scores(report, pd.DataFrame())[0]
    frame = simple_scoreboard_frame([score])

    assert frame.loc[0, "evidence_score_10"] is not None
    assert frame.loc[0, "evidence_quality_10"] is not None
    assert frame.loc[0, "risk_friction_10"] is not None
    assert frame.loc[0, "model_authority_label"] == "Model evidence unavailable"
    assert "q10_expected_return" in frame.columns
    assert "net_expected_return" in frame.columns
    assert "expected_return_order_value_eur" in frame.columns
    assert "expected_return_distribution_version" in frame.columns
    assert "liquidity_cost_score_10" in frame.columns
    assert "model_calibration_label" in frame.columns
    assert "market_regime_label" in frame.columns
    assert "strategy_template_label" in frame.columns
    assert "evidence_maturity_state" in frame.columns
    assert "too_good_to_be_true_warning" in frame.columns
    assert frame.loc[0, "evidence_sample_days"] == 300
    assert "benchmark_attribution_label" in frame.columns
    assert "benchmark_beta" in frame.columns
    assert "sector_theme_warning" in frame.columns
    assert "backtest_validity" in frame.columns
    assert "model_contamination_risk" in frame.columns
    assert "model_authority_reason" in frame.columns
    assert "calibration_required" in frame.columns


def test_scoreboard_binds_classification_token_and_reader_invalidates_stale_score(
    monkeypatch,
    tmp_path,
) -> None:
    report = pd.DataFrame(
        [
            {
                "instrument_id": "ABC",
                "name": "ABC Test Stock",
                "yahoo_symbol": "ABC.DE",
                "latest_date": pd.Timestamp.today().date().isoformat(),
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
    monkeypatch.setattr(simple_scores_module, "ROOT", tmp_path)
    candidate = build_candidate_simple_scores(report, pd.DataFrame())[0]
    bound = simple_scores_module._with_canonical_score(
        simple_scores_module._with_classification_dependency(candidate)
    )
    path = tmp_path / "data" / "derived" / "scoreboard.parquet"
    write_simple_scoreboard([bound], path)
    raw_before = pd.read_parquet(path)

    assert bound.classification_dependency_status == "current"
    assert bound.classification_invalidation_hash != "unavailable"
    assert bound.canonical_score is not None
    assert raw_before.iloc[0]["classification_invalidation_hash"] == bound.classification_invalidation_hash

    with ClassificationStore(tmp_path) as store:
        store.append_overrides(
            (
                ClassificationOverride(
                    override_id="override:ABC:sector:1",
                    instrument_id="ABC",
                    field="sector",
                    value="technology",
                    reason="reviewed issuer activity",
                    reviewer="local_user",
                    valid_from="2026-07-11T00:00:00Z",
                    available_at="2026-07-11T00:00:00Z",
                    dependent_score_keys=("classification:ABC:*",),
                ),
            )
        )

    projected = load_simple_scoreboard(path, root=tmp_path)
    raw_after = pd.read_parquet(path)
    assert pd.notna(raw_after.iloc[0]["canonical_attractiveness_10"])
    assert pd.isna(projected.iloc[0]["canonical_attractiveness_10"])
    assert projected.iloc[0]["classification_dependency_status"] == "classification_override_invalidated"
    assert projected.iloc[0]["analysis_status"] == "unavailable"
    assert not bool(projected.iloc[0]["execution_allowed"])


def test_score_construction_fails_closed_when_classification_storage_is_unavailable(monkeypatch) -> None:
    candidate = SimpleInstrumentScore(
        instrument_key="candidate:ABC",
        display_id="ABC",
        source_group="candidate",
        asset_type="stock",
        name="ABC",
        yahoo_symbol="ABC.DE",
        latest_date="2026-07-10",
        latest_price=100.0,
        final_score_10=7.0,
        decision="review",
        one_line_reason="candidate evidence",
        components=[
            SimpleScoreComponent(
                key="momentum",
                label="Momentum",
                score_10=7.0,
                raw_score=0.10,
                status="available",
                explanation="deterministic adjusted-price evidence",
                good_score="higher is stronger",
                why="review evidence",
            )
        ],
        warnings=[],
    )
    monkeypatch.setattr(
        simple_scores_module,
        "classification_score_state",
        lambda _root, _instrument_id: {
            "status": "unavailable",
            "version_id": "unavailable",
            "invalidation_token": "corrupt-store-hash",
            "invalidated_score_keys": ("classification:ABC:*",),
            "execution_allowed": False,
        },
    )

    result = simple_scores_module._with_canonical_score(
        simple_scores_module._with_classification_dependency(candidate)
    )

    assert result.final_score_10 is None
    assert result.canonical_score is None
    assert result.classification_dependency_status == "classification_unavailable"
    assert "classification_unavailable" in result.warnings
    assert result.execution_allowed is False


def test_score_friction_fields_equal_selected_friction_edge_calculator_output() -> None:
    components = [
        SimpleScoreComponent(
            "liquidity_cost", "Liquidity", 7.0, 0.4, "OK", "", "", "", as_of_date="2026-07-10", freshness_status="ok"
        )
    ]
    fields = simple_scores_module._friction_edge_fields(
        8.0,
        components,
        volatility=0.2,
        costs={"low": 5.0, "base": 15.0, "high": 30.0},
        scenario="high",
    )
    expected = estimate_friction_edge(8.0, 0.2, {"low": 5.0, "base": 15.0, "high": 30.0}, "high")

    assert fields["gross_expected_edge_bps"] == expected.gross_bps
    assert fields["estimated_total_cost_bps"] == expected.cost_bps
    assert fields["net_expected_edge_bps"] == expected.net_bps
    assert fields["edge_to_cost_ratio"] == expected.edge_to_cost_ratio
    assert fields["cost_stress_scenario"] == "high"


def test_score_friction_fields_use_distribution_and_order_size_when_supplied() -> None:
    fields = simple_scores_module._friction_edge_fields(
        8.0,
        [],
        expected_return_distribution={"q10_return": -0.03, "q50_return": 0.05, "q90_return": 0.12, "horizon_days": 60, "status": "available"},
        order_value_eur=1_000.0,
        cost_estimate={"order_value_eur": 1_000.0, "total_cost_bps": 20.0, "total_cost_eur": 2.0},
    )

    assert fields["friction_status"] == "available"
    assert fields["gross_expected_edge_bps"] == 500.0
    assert fields["net_expected_edge_bps"] == 480.0
    assert fields["q10_expected_return"] == -0.03
    assert fields["expected_return_horizon_days"] == 60
    assert fields["net_expected_return"] == 0.048
    assert fields["expected_return_order_value_eur"] == 1_000.0
    assert fields["expected_return_source_dataset"] == "forecast_return_distribution"


def test_order_size_cost_estimate_uses_absolute_trade_value_and_fails_closed_at_zero(monkeypatch) -> None:
    calls: list[float] = []

    def fake_estimate(_config, _instrument_id, order_value):
        calls.append(order_value)
        return SimpleNamespace(
            as_dict=lambda: {
                "order_value_eur": order_value,
                "total_cost_bps": 30.0,
                "total_cost_eur": 3.0,
            }
        )

    monkeypatch.setattr(simple_scores_module, "estimate_execution_cost", fake_estimate)
    config = load_config()

    estimate = simple_scores_module._order_size_cost_estimate(config, "VWCE", -250.0)
    unavailable = simple_scores_module._order_size_cost_estimate(config, "VWCE", 0.0)

    assert calls == [250.0]
    assert estimate is not None
    assert estimate["total_cost_bps"] == 30.0
    assert estimate["order_value_eur"] == 250.0
    assert unavailable is None


def test_missing_production_distribution_does_not_use_legacy_score_proxy() -> None:
    fields = simple_scores_module._friction_edge_fields(
        8.0,
        [],
        volatility=0.2,
        costs={"base": 15.0},
        expected_return_distribution={},
        order_value_eur=None,
        cost_estimate=None,
    )

    assert fields["friction_status"] == "unavailable"
    assert fields["gross_expected_edge_bps"] is None
    assert fields["expected_return_source_dataset"] == "forecast_return_distribution"


def test_model_backtest_validity_marks_uncalibrated_optional_models_unverified() -> None:
    components = [
        SimpleScoreComponent("baseline", "Baseline", 6.0, 0.2, "OK", "", "", "", authority="low", score_role="model_confirmation"),
        SimpleScoreComponent("timesfm", "TimesFM", 8.0, 0.6, "OK", "", "", "", authority="low", score_role="model_confirmation"),
    ]

    validity = _model_backtest_validity(components, calibration_score=None, backtest_score=7.0, candidate=False)

    assert validity["backtest_validity"] == "model_claim_unverified"
    assert validity["model_contamination_risk"] == "unverified_model_history_overlap"
    assert validity["calibration_required"] is True


def test_evidence_maturity_flags_short_high_score_and_large_return() -> None:
    maturity = _evidence_maturity(
        rows=80,
        final_score=8.4,
        evidence_quality=6.2,
        risk_friction=5.5,
        metrics={"return_3m": 0.28, "current_drawdown": -0.02},
        existing_warnings=[],
    )

    assert maturity["sample_days"] == 80
    assert maturity["state"] == "young_noisy"
    assert "only 80 valid price rows" in maturity["label"]
    assert maturity["too_good_to_be_true_warning"] != "No sanity warning"
    assert maturity["warning_count"] >= 4


def test_evidence_maturity_missing_rows_is_unknown_not_mature() -> None:
    maturity = _evidence_maturity(
        rows=None,
        final_score=6.0,
        evidence_quality=6.0,
        risk_friction=6.0,
        metrics={},
        existing_warnings=[],
    )

    assert maturity["sample_days"] is None
    assert maturity["state"] == "unknown"
    assert "unknown" in maturity["label"].lower()


def test_main_page_exposes_simple_workflow_buttons() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1400, route="/", go=lambda route: None)

    view = build_shell(page, state, "/")
    text = "\n".join(_control_texts(view))

    assert "1. Refresh yfinance data" in text
    assert "2. Run algorithms" in text
    assert "3. Run forecasting models" in text
    assert "4. Show scores" in text
    assert "Primary tier - ETFs" in text
    assert "Primary tier - stocks/equity certificates" in text
    assert "Secondary tier - ETFs" in text
    assert "Secondary tier - stocks/equity certificates" in text
    assert "Sparebanken - Norwegian savings-bank equity-certificate issuers" in text
    assert "Maturity" in text
    assert "Sanity" in text
    assert "Benchmark" in text
    assert "Alpha proxy" in text
    assert "Sector/theme" in text
    assert "Backtest validity" in text
    assert "Model contamination" in text


def test_two_tier_universe_config_contains_requested_primary_and_secondary_without_duplicates() -> None:
    config = load_config()
    ids = {etf.id for etf in config.universe.etfs}

    assert {"JAPAN_EQUITY", "GLOBAL_BONDS", "GOLD_HEDGE"}.isdisjoint(ids)
    assert PRIMARY_IDS <= ids

    primary_symbols = config.data_providers.section("prices").symbols_map
    assert primary_symbols["VWCE"] == "VWCE.DE"
    assert primary_symbols["UCG"] == "UCG.MI"
    assert primary_symbols["H4ZT"] == "H4ZT.DE"

    candidate_files = sorted((RAW_DIR / "trade_candidates").glob("yahoo_trade_candidates_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    loaded_generated_candidates = bool(candidate_files)
    if candidate_files:
        candidates = pd.read_csv(candidate_files[0])
    else:
        # Generated candidate CSVs are intentionally excluded from source control;
        # the canonical configured universe remains the authoritative fallback.
        rows = []
        for etf in config.universe.etfs:
            extra = getattr(etf, "model_extra", None) or {}
            tier = str(extra.get("analysis_tier", getattr(etf, "analysis_tier", "primary")))
            if tier == "primary":
                continue
            rows.append(
                {
                    "instrument_id": etf.id,
                    "name": etf.name,
                    "yahoo_symbol": extra.get("yahoo_symbol", etf.ticker),
                    "isin": etf.isin or "needs_verification",
                    "analysis_tier": tier,
                    "data_policy": extra.get("data_policy", "yfinance_only"),
                    "instrument_type": extra.get("instrument_type", getattr(etf, "instrument_type", etf.asset_class)),
                }
            )
        candidates = pd.DataFrame(rows)
    secondary = candidates[candidates["analysis_tier"].astype(str) == "secondary"]
    sparebanken = candidates[candidates["analysis_tier"].astype(str) == "sparebanken"]
    assert SECONDARY_IDS == set(secondary["instrument_id"].astype(str))
    assert SPAREBANKEN_IDS == set(sparebanken["instrument_id"].astype(str))
    assert set(candidates["data_policy"]) == {"yfinance_only"}
    if loaded_generated_candidates:
        assert set(candidates["instrument_id"]).isdisjoint(PRIMARY_IDS)
        known_candidate_isins = {isin for isin in candidates["isin"].astype(str) if isin != "needs_verification"}
        assert not (known_candidate_isins & {etf.isin for etf in config.universe.etfs if etf.isin})
        assert not (set(candidates["yahoo_symbol"]) & set(primary_symbols.values()))
    sparebanken_needs_verification = set(sparebanken[sparebanken["isin"].astype(str) == "needs_verification"]["instrument_id"])
    if loaded_generated_candidates:
        assert sparebanken_needs_verification == SPAREBANKEN_NEEDS_VERIFICATION
    else:
        assert SPAREBANKEN_NEEDS_VERIFICATION <= sparebanken_needs_verification
    assert set(sparebanken["instrument_type"]) == {"equity_certificate"}


def test_simple_scores_show_all_two_tier_instruments_as_pending_without_refresh(monkeypatch) -> None:
    monkeypatch.setattr(simple_scores_module, "load_latest_candidate_report", lambda: (pd.DataFrame(), None))
    monkeypatch.setattr(simple_scores_module, "load_latest_forecasts", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(simple_scores_module, "load_forecast_history", lambda *args, **kwargs: pd.DataFrame())
    config = load_config()
    scores = build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())
    by_id = {score.display_id: score for score in scores}

    assert PRIMARY_IDS <= set(by_id)
    assert SECONDARY_IDS <= set(by_id)
    assert SPAREBANKEN_IDS <= set(by_id)
    assert by_id["VWCE"].source_group == "Primary tier"
    assert by_id["VWCE"].final_score_10 is None
    assert by_id["VWCE"].decision == "Pending Refresh"
    assert by_id["MSFT"].source_group == "Secondary tier"
    assert by_id["MSFT"].decision == "Pending Refresh"
    assert by_id["NONG"].source_group == "Sparebanken"
    assert by_id["NONG"].analysis_tier == "sparebanken"
    assert by_id["NONG"].asset_type == "Equity certificate"
    assert by_id["AURG"].isin == "needs_verification"
    assert by_id["RABO"].asset_type == "Certificate"
    assert by_id["RABO"].final_score_10 is None


def test_simple_scores_group_into_required_main_page_sections() -> None:
    config = load_config()
    scores = build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())
    groups = group_simple_scores(scores)

    assert [group.label for group in groups] == [
        "Primary tier - ETFs",
        "Primary tier - stocks/equity certificates",
        "Secondary tier - ETFs",
        "Secondary tier - stocks/equity certificates",
        "Sparebanken - Norwegian savings-bank equity-certificate issuers",
    ]
    by_label = {group.label: {score.display_id for score in group.scores} for group in groups}
    assert "VWCE" in by_label["Primary tier - ETFs"]
    assert "UCG" in by_label["Primary tier - stocks/equity certificates"]
    assert "EUNK" in by_label["Secondary tier - ETFs"]
    assert "MSFT" in by_label["Secondary tier - stocks/equity certificates"]
    assert SPAREBANKEN_IDS <= by_label["Sparebanken - Norwegian savings-bank equity-certificate issuers"]


def test_scoreboard_frame_preserves_needs_verification_isin_status() -> None:
    config = load_config()
    scores = build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())
    frame = simple_scoreboard_frame(scores).set_index("instrument_id")

    assert frame.loc["AURG", "isin"] == "needs_verification"
    assert frame.loc["AURG", "isin_status"] == "needs_verification"
    assert frame.loc["NONG", "isin_status"] == "verified"


def test_unresolved_isin_placeholder_is_not_used_as_reference_identity() -> None:
    config = load_config()

    context = DataService(config)._reference_context()

    assert "needs_verification" not in context["isin_to_etf_id"]
    assert context["isin_to_etf_id"]["NO0006000801"] == "NONG"


def test_scoreboard_multi_file_write_rolls_back_on_late_template_failure(tmp_path, monkeypatch) -> None:
    snapshot = build_snapshot()
    scores = build_simple_instrument_scores(snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices)
    output = tmp_path / "scoreboard.parquet"
    write_simple_scoreboard(scores, output)
    paths = [output, output.with_suffix(".csv"), output.with_suffix(".json"), output.parent / "strategy_templates.csv"]
    previous = {path: path.read_bytes() for path in paths}
    real_replace = Path.replace

    def fail_template(self: Path, destination: Path):
        if Path(destination).name == "strategy_templates.csv":
            raise PermissionError("template store locked")
        return real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", fail_template)
    with pytest.raises(PermissionError, match="template store locked"):
        write_simple_scoreboard(scores, output)

    assert {path: path.read_bytes() for path in paths} == previous


def test_simple_score_tiles_render_instrument_rows() -> None:
    config = load_config()
    scores = build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())
    tiles = simple_score_tiles(scores)
    text = "\n".join(_control_texts(tiles))

    assert "VWCE - Vanguard FTSE All-World UCITS ETF USD Accumulating" in text
    assert "MSFT - Microsoft Corp" in text
    assert "Primary tier | Yahoo VWCE.DE" in text
    assert "Secondary tier | Yahoo MSFT" in text


def test_score_row_arrow_does_not_toggle_twice_on_parent_click() -> None:
    config = load_config()
    score = build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())[0]
    controls = simple_score_tiles([score])
    buttons = [control for control in _control_nodes(controls) if type(control).__name__ == "IconButton"]

    handlers = [control for control in _control_nodes(controls) if callable(getattr(control, "on_click", None))]

    assert buttons
    assert callable(buttons[0].on_click)
    assert len(handlers) == 1


def test_simple_score_grouped_sections_render_required_labels_and_sparebanken_isin_status() -> None:
    config = load_config()
    scores = build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())
    grouped = simple_score_grouped_sections(scores)
    text = "\n".join(_control_texts(grouped))

    assert "Primary tier - ETFs" in text
    assert "Primary tier - stocks/equity certificates" in text
    assert "Secondary tier - ETFs" in text
    assert "Secondary tier - stocks/equity certificates" in text
    assert "Sparebanken - Norwegian savings-bank equity-certificate issuers" in text
    assert "AURG - Aurskog Sparebank" in text
    assert "ISIN needs_verification" in text


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], "No score history available yet"),
        ([{"final_combined_score_10": 6.0}], "One snapshot"),
        ([{"final_combined_score_10": 6.0}, {"final_combined_score_10": 7.0}], "Latest 7.0/10 | Previous 6.0/10 | Delta +1.0"),
    ],
)
def test_score_history_panel_renders_no_one_and_multi_snapshot_states(rows, expected) -> None:
    panel = _score_history_panel(SimpleNamespace(), rows)

    assert expected in "\n".join(_control_texts(panel))


def _control_texts(control: object) -> list[str]:
    texts: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        texts.append(value)
    text = getattr(control, "text", None)
    if isinstance(text, str):
        texts.append(text)
    values = getattr(control, "_values", {})
    if isinstance(values, dict) and isinstance(values.get("content"), str):
        texts.append(values["content"])
    content = getattr(control, "content", None)
    if content is not None:
        texts.extend(_control_texts(content))
    for attr in ("controls", "rows", "cells"):
        children = getattr(control, attr, None)
        if children:
            for child in children:
                texts.extend(_control_texts(child))
    title = getattr(control, "title", None)
    if title is not None:
        texts.extend(_control_texts(title))
    return texts


def _control_nodes(control: object) -> list[object]:
    nodes = [control]
    content = getattr(control, "content", None)
    if content is not None:
        nodes.extend(_control_nodes(content))
    for attr in ("controls", "rows", "cells"):
        children = getattr(control, attr, None)
        if children:
            for child in children:
                nodes.extend(_control_nodes(child))
    return nodes
