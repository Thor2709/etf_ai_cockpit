from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.pages import backtests, data_models, portfolio
import etf_cockpit.application.monthly_decision_template as monthly_decision
from etf_cockpit.application.monthly_decision_template import (
    build_monthly_decision_template,
    monthly_decision_template_lines,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry
from etf_cockpit.signals.strategy_templates import strategy_template_frame


_TEST_REGISTRY = CanonicalBenchmarkRegistry()


@pytest.fixture(autouse=True)
def _validated_reference_dependency(monkeypatch) -> None:
    """Keep ISSUE-0046 tests focused on composition; ISSUE-0112 owns registry semantics."""

    def validate(reference, benchmark_data_id, *, registry=None):
        if registry is not _TEST_REGISTRY:
            return None
        return str(benchmark_data_id) if isinstance(reference, dict) else None

    monkeypatch.setattr(monthly_decision, "validate_benchmark_reference", validate)


def _reference() -> dict[str, object]:
    return {
        "status": "available", "execution_allowed": False,
        "benchmark_data_id": "VWCE", "registry_hash": "registry-hash",
        "selected_records": {"benchmark": "benchmark-hash", "cash": "cash-hash", "peer_set": "peer-hash"},
        "provenance": {"registry_hash": "registry-hash", "selected_records": {"benchmark": "benchmark-hash", "cash": "cash-hash", "peer_set": "peer-hash"}},
        "benchmark": {"status": "available", "id": "benchmark:global", "version": "1.0.0", "content_hash": "benchmark-hash"},
        "cash": {"status": "available", "id": "cash:EUR", "version": "1.0.0", "content_hash": "cash-hash"},
        "references": [{"status": "available", "id": "reference:no-trade", "version": "1.0.0", "content_hash": "no-trade-hash", "method": "no_trade"}],
    }


def _full_evidence() -> dict[str, object]:
    return {
        "alternatives": {
            "basket": {"status": "available", "version": "returns.v3", "source_id": "candidate:42", "source_dataset": "forward:2026-08", "period_return": 0.07, "benchmark_relative_return": 0.02, "cash_relative_return": 0.04, "execution_allowed": False},
            "benchmark": {"status": "available", "version": "returns.v3", "source_id": "benchmark:42", "source_dataset": "forward:2026-08", "reference_id": "benchmark:global", "period_return": 0.05, "execution_allowed": False},
            "cash": {"status": "available", "version": "returns.v3", "source_id": "cash:42", "source_dataset": "forward:2026-08", "reference_id": "cash:EUR", "period_return": 0.03, "execution_allowed": False},
            "no_action": {"status": "available", "version": "returns.v3", "source_id": "no-trade:42", "source_dataset": "forward:2026-08", "reference_id": "reference:no-trade", "reference_method": "no_trade", "period_return": 0.04, "execution_allowed": False},
        },
        "expected_returns": {
            "status": "available", "version": "distribution.v2", "source_id": "score:42", "source_dataset": "features:2026-08", "horizon_days": 21,
            "gross": {"q10": -0.03, "q50": 0.06, "q90": 0.14},
            "net": {"q10": -0.035, "q50": 0.055, "q90": 0.135}, "execution_allowed": False,
        },
        "optimiser": {
            "status": "available", "model_version": "optimiser.v4", "method": "robust_mean_variance", "source_id": "solution:42",
            "constraints": {"status": "available", "values": {"max_weight": 0.25, "turnover_limit": 0.15}, "execution_allowed": False},
            "solution": {"status": "success", "feasible": True, "weights": {"VWCE": 0.25}, "diagnostics": {"status": "available", "binding_constraints": ["max_weight"], "execution_allowed": False}, "execution_allowed": False},
            "execution_allowed": False,
        },
        "costs": {
            "status": "available", "model_id": "cost-model.v2", "source_id": "portfolio-cost:42",
            "components": [{"estimate_id": "estimate:VWCE", "instrument_id": "VWCE", "order_value_eur": 10_000.0, "cost_eur": 12.5, "cost_bps": 12.5, "commission_eur": 2.5, "spread_bps": 4.0, "slippage_bps": 3.0, "market_impact_bps": 3.0, "execution_allowed": False}],
            "total": {"order_value_eur": 10_000.0, "cost_eur": 12.5, "cost_bps": 12.5},
            "capacity": {"status": "available", "amount_eur": 75_000.0},
            "assumptions": ["caller-supplied canonical cost estimate"], "execution_allowed": False,
        },
        "events": {
            "status": "available", "version": "event-replay.v1", "source_id": "replay:42",
            "replay": {"status": "available", "event_count": 8, "execution_allowed": False},
            "next_session": {"status": "available", "execution_delay_sessions": 1, "same_bar_execution_avoided": True, "arrival_price_assumption": "next_adjusted_close", "execution_allowed": False},
            "execution_allowed": False,
        },
        "forward_evidence": {"status": "available", "version": "forward-evidence.v1", "source_id": "forward:42", "snapshot": {"snapshot_id": "forward:42", "as_of": "2026-08-21", "execution_allowed": False}, "outcomes": [{"horizon_days": 21, "status": "matured", "net_return": 0.055}], "execution_allowed": False},
        "paper_outcomes": {"status": "available", "version": "paper-account.v1", "source_id": "paper:42", "account_id": "paper:local", "ledger_hash": "ledger-hash", "reconciliation_status": "reconciled", "matured_outcomes": 4, "outcomes": [{"decision_id": "decision:1", "status": "matured"}], "execution_allowed": False},
        "concentration": {"status": "available", "sector": {"status": "available", "max_weight": 0.32, "execution_allowed": False}, "theme": {"status": "available", "max_weight": 0.18, "execution_allowed": False}, "execution_allowed": False},
        "assumptions": {"status": "available", "version": "assumptions.v1", "source_id": "policy:42", "values": {"rebalance_cadence": "monthly", "execution_assumption": "next_session"}, "execution_allowed": False},
    }


def _build(evidence: dict[str, object] | None = None):
    values = evidence or _full_evidence()
    return build_monthly_decision_template(
        benchmark_reference=_reference(), alternatives=values["alternatives"],
        expected_returns=values["expected_returns"], optimiser=values["optimiser"],
        costs=values["costs"], events=values["events"],
        forward_evidence=values["forward_evidence"], paper_outcomes=values["paper_outcomes"],
        concentration=values["concentration"], assumptions=values["assumptions"],
        benchmark_registry=_TEST_REGISTRY, evidence_maturity="mature", sample_size=4,
    )


def _walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _text(control) -> str:
    return "\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))


def _assert_execution_disabled(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "execution_allowed":
                assert item is False
            _assert_execution_disabled(item)
    elif isinstance(value, list):
        for item in value:
            _assert_execution_disabled(item)


def test_full_projection_preserves_canonical_evidence_without_calculation() -> None:
    result = _build()
    projection = result.projection()

    assert result.status == "available"
    assert projection["alternatives"]["basket"]["benchmark_relative_return"] == 0.02
    assert projection["alternatives"]["basket"]["cash_relative_return"] == 0.04
    assert projection["expected_returns"]["gross"] == {"q10": -0.03, "q50": 0.06, "q90": 0.14}
    assert projection["expected_returns"]["net"]["q50"] == 0.055
    assert projection["expected_returns"]["version"] == "distribution.v2"
    assert projection["optimiser"]["constraints"]["values"]["turnover_limit"] == 0.15
    assert projection["optimiser"]["solution"]["diagnostics"]["binding_constraints"] == ["max_weight"]
    assert projection["costs"]["components"][0]["market_impact_bps"] == 3.0
    assert projection["costs"]["capacity"]["amount_eur"] == 75_000.0
    assert projection["events"]["next_session"]["execution_delay_sessions"] == 1
    assert projection["forward_evidence"]["snapshot"]["snapshot_id"] == "forward:42"
    assert projection["paper_outcomes"]["matured_outcomes"] == 4
    assert set(projection["alternatives"]) == {"basket", "benchmark", "cash", "no_action"}
    _assert_execution_disabled(projection)
    rendered = "\n".join(monthly_decision_template_lines(result)).casefold()
    assert "gross=" in rendered and "net=" in rendered
    assert "buy" not in rendered and "sell" not in rendered


def test_missing_producers_are_explicitly_unavailable_and_warn_as_young() -> None:
    result = build_monthly_decision_template(
        benchmark_reference=_reference(),
        benchmark_registry=_TEST_REGISTRY,
        evidence_maturity="young/noisy",
        sample_size=1,
    )
    projection = result.projection()

    assert result.status == "partial"
    assert all(value["status"] == "unavailable" for value in projection["alternatives"].values())
    for name in ("expected_returns", "optimiser", "costs", "events", "forward_evidence", "paper_outcomes", "concentration", "assumptions"):
        assert projection[name]["status"] == "unavailable"
    assert any("Young/noisy live/paper warning" in item for item in result.warnings)
    _assert_execution_disabled(projection)


@pytest.mark.parametrize(
    ("section", "mutation"),
    [
        ("expected_returns", lambda value: value["gross"].update(q50="not-a-number")),
        ("optimiser", lambda value: value["solution"]["diagnostics"].update(binding_constraints="max_weight")),
        ("costs", lambda value: value["capacity"].update(amount_eur=float("nan"))),
        ("events", lambda value: value["next_session"].update(execution_delay_sessions=0)),
        ("forward_evidence", lambda value: value.update(snapshot=[])),
        ("paper_outcomes", lambda value: value.update(outcomes="matured")),
        ("concentration", lambda value: value["sector"].update(max_weight=1.2)),
        ("assumptions", lambda value: value["values"].update(rebalance_cadence="weekly")),
    ],
)
def test_malformed_nested_evidence_fails_closed(section: str, mutation) -> None:
    evidence = deepcopy(_full_evidence())
    mutation(evidence[section])
    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()[section]["status"] == "unavailable"
    assert any(
        blocker in {f"{section}_invalid", f"{section}_malformed"}
        for blocker in result.blockers
    )
    _assert_execution_disabled(result.projection())


@pytest.mark.parametrize(
    "path",
    [
        ("alternatives", "basket"), ("expected_returns", "gross"),
        ("optimiser", "solution", "diagnostics"), ("costs", "components", 0),
        ("events", "next_session"), ("forward_evidence", "snapshot"),
        ("paper_outcomes", "outcomes", 0), ("concentration", "sector"),
        ("assumptions", "values"),
    ],
)
def test_nested_execution_authority_injection_fails_closed(path: tuple[object, ...]) -> None:
    evidence = deepcopy(_full_evidence())
    target: object = evidence
    for part in path:
        target = target[part]  # type: ignore[index]
    assert isinstance(target, dict)
    target["execution_allowed"] = True

    result = _build(evidence)
    assert result.status == "unavailable"
    assert any("authority_invalid" in blocker for blocker in result.blockers)
    _assert_execution_disabled(result.projection())


def test_reference_execution_authority_injection_fails_closed() -> None:
    reference = _reference()
    reference["references"][0]["execution_allowed"] = True  # type: ignore[index]
    evidence = _full_evidence()
    result = build_monthly_decision_template(
        benchmark_reference=reference,
        benchmark_registry=_TEST_REGISTRY,
        **evidence,
    )

    assert result.status == "unavailable"
    assert "canonical_reference_authority_invalid" in result.blockers
    _assert_execution_disabled(result.projection())


def test_available_reference_without_authoritative_registry_fails_closed() -> None:
    evidence = _full_evidence()

    result = build_monthly_decision_template(benchmark_reference=_reference(), **evidence)

    assert result.status == "unavailable"
    assert result.benchmark_reference == {
        "status": "unavailable",
        "reason": "canonical_reference_validation_failed",
        "execution_allowed": False,
    }
    assert "canonical_reference_invalid" in result.blockers


def test_recursive_reference_and_section_evidence_fail_closed() -> None:
    recursive_reference = _reference()
    recursive_reference["nested"] = recursive_reference

    reference_result = build_monthly_decision_template(
        benchmark_reference=recursive_reference,
        benchmark_registry=_TEST_REGISTRY,
    )

    assert reference_result.status == "unavailable"
    assert "canonical_reference_authority_invalid" in reference_result.blockers

    recursive_section: dict[str, object] = {"status": "partial", "reason": "recursive"}
    recursive_section["nested"] = recursive_section
    evidence = _full_evidence()
    evidence["forward_evidence"] = recursive_section

    section_result = _build(evidence)

    assert section_result.status == "unavailable"
    assert "forward_evidence_authority_invalid" in section_result.blockers


def test_strategy_template_frame_retains_required_projection_inputs() -> None:
    frame = strategy_template_frame(pd.DataFrame([{"instrument_id": "VWCE", "q10_expected_return": -0.03, "q50_expected_return": 0.06, "q90_expected_return": 0.14, "net_q10_expected_return": -0.035, "net_expected_return": 0.055, "net_q90_expected_return": 0.135, "expected_return_distribution_version": "distribution.v2", "expected_return_source_dataset": "features:2026-08", "expected_return_cost_bps": 12.5, "expected_return_cost_eur": 12.5, "expected_return_cost_ratio": 0.00125, "execution_allowed": False}]))

    assert {"q10_expected_return", "q50_expected_return", "q90_expected_return", "net_q10_expected_return", "net_expected_return", "net_q90_expected_return", "expected_return_distribution_version", "expected_return_source_dataset", "expected_return_cost_bps", "expected_return_cost_eur", "expected_return_cost_ratio", "execution_allowed"} <= set(frame.columns)
    assert frame.iloc[0]["execution_allowed"] == False  # noqa: E712


@pytest.mark.parametrize("invalid", [True, False, float("inf"), float("-inf")])
def test_strategy_distribution_component_rejects_non_financial_numbers(invalid: object) -> None:
    row = {
        "instrument_id": "VWCE",
        "q10_expected_return": invalid,
        "q50_expected_return": 0.06,
        "q90_expected_return": 0.14,
        "net_q10_expected_return": -0.035,
        "net_expected_return": 0.055,
        "net_q90_expected_return": 0.135,
        "expected_return_horizon_days": 21,
        "expected_return_distribution_version": "distribution.v2",
        "expected_return_source_dataset": "features:2026-08",
    }

    projection = data_models._strategy_distribution_component(row)

    assert projection == {
        "instrument_id": "VWCE",
        "status": "unavailable",
        "reason": "complete_gross_net_distribution_unavailable",
        "execution_allowed": False,
    }


def test_actual_ui_consumers_render_the_monthly_projection(monkeypatch, tmp_path) -> None:
    frame = pd.DataFrame([
        {"instrument_id": instrument_id, "q10_expected_return": -0.03, "q50_expected_return": 0.06, "q90_expected_return": 0.14, "net_q10_expected_return": -0.035, "net_expected_return": 0.055, "net_q90_expected_return": 0.135, "expected_return_horizon_days": 21, "expected_return_distribution_version": "distribution.v2", "expected_return_source_dataset": "features:2026-08", "sector_theme_warning": "partial", "crowding_top_ranked_theme_concentration": 0.18}
        for instrument_id in ("VWCE", "LYP6")
    ])
    frame.to_csv(tmp_path / "strategy_templates.csv", index=False)
    monkeypatch.setattr(data_models, "DERIVED_DIR", tmp_path)
    monkeypatch.setattr(data_models, "context_from_snapshot", lambda *_args, **_kwargs: SimpleNamespace(projection=_reference(), registry=None))
    strategy_text = data_models._monthly_decision_text(SimpleNamespace(snapshot=SimpleNamespace(universe_revision="revision:42")))
    assert "Expected-return distributions: partial" in strategy_text
    assert "components=2" in strategy_text
    assert "No-action context" in strategy_text

    report = SimpleNamespace(metadata={"execution_delay_sessions": 1, "same_bar_execution_avoided": True, "input_checksum": "backtest-input-hash", "price_field": "adjusted_close", "lookahead_protection": "enabled", "walk_forward_periods": 4}, quality_label="mature")
    backtest_panel = backtests._monthly_decision_panel(SimpleNamespace(projection=_reference(), registry=None), report=report, config=load_config())
    backtest_text = _text(backtest_panel)
    assert "Monthly decision template" in backtest_text
    assert "Events/next-session evidence: partial" in backtest_text
    assert "Basket: unavailable" in backtest_text

    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame([{"etf_id": "VWCE", "current_weight": 1.0, "market_value_eur": 40_000.0, "as_of_date": "2026-08-21", "known_at": "2026-08-21T12:00:00Z"}]),
        universe_revision="revision:42", data_report=SimpleNamespace(as_of_date="2026-08-21"),
    )
    portfolio_text = _text(portfolio.portfolio_page(None, SimpleNamespace(snapshot=snapshot)))
    assert "Monthly decision template" in portfolio_text
    assert "No-action context: unavailable" in portfolio_text
    assert "execution_allowed=false" in portfolio_text
