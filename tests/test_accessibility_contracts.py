from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from etf_cockpit.app.router import PAGES, build_shell
from etf_cockpit.core.ui_acceptance import load_ui_acceptance_contracts
from etf_cockpit.services import build_snapshot
from etf_cockpit.app.state import AppState


_SNAPSHOT_TEMPLATE = None


@pytest.fixture(scope="module", autouse=True)
def _snapshot_template():
    global _SNAPSHOT_TEMPLATE
    _SNAPSHOT_TEMPLATE = build_snapshot()
    yield
    _SNAPSHOT_TEMPLATE = None


def _snapshot_copy():
    assert _SNAPSHOT_TEMPLATE is not None
    snapshot = _SNAPSHOT_TEMPLATE
    return replace(
        snapshot,
        config=copy.deepcopy(snapshot.config),
        prices=snapshot.prices.copy(deep=True),
        holdings=snapshot.holdings.copy(deep=True),
        features=snapshot.features.copy(deep=True),
        latest_features=snapshot.latest_features.copy(deep=True),
        data_report=replace(
            snapshot.data_report,
            issues=copy.deepcopy(snapshot.data_report.issues),
            dataset_metadata=copy.deepcopy(snapshot.data_report.dataset_metadata),
        ),
        signals=[
            replace(
                signal,
                blocked_by=copy.deepcopy(signal.blocked_by),
                warnings=copy.deepcopy(signal.warnings),
                supporting_metrics=copy.deepcopy(signal.supporting_metrics),
                model_versions_used=copy.deepcopy(signal.model_versions_used),
                authority_decision=copy.deepcopy(signal.authority_decision),
                canonical_score=copy.deepcopy(signal.canonical_score),
            )
            for signal in snapshot.signals
        ],
        forecasts=snapshot.forecasts.copy(deep=True),
        model_status=copy.deepcopy(snapshot.model_status),
        model_inventory=copy.deepcopy(snapshot.model_inventory),
        candidate_price_binding=copy.deepcopy(snapshot.candidate_price_binding),
        etf_economics_records=copy.deepcopy(snapshot.etf_economics_records),
        etf_fund_total_return=copy.deepcopy(snapshot.etf_fund_total_return),
        etf_benchmark_total_return=copy.deepcopy(snapshot.etf_benchmark_total_return),
        etf_closure_policy=copy.deepcopy(snapshot.etf_closure_policy),
        benchmark_reference_registry=copy.copy(snapshot.benchmark_reference_registry),
        benchmark_reference_instrument=copy.deepcopy(snapshot.benchmark_reference_instrument),
        benchmark_reference_portfolio_ids=copy.deepcopy(snapshot.benchmark_reference_portfolio_ids),
        vwce_anchor_evidence=copy.copy(snapshot.vwce_anchor_evidence),
        vwce_conversion_evidence=copy.deepcopy(snapshot.vwce_conversion_evidence),
        backtest=replace(
            snapshot.backtest,
            results=snapshot.backtest.results.copy(deep=True),
            equity_curves=snapshot.backtest.equity_curves.copy(deep=True),
            trade_log=snapshot.backtest.trade_log.copy(deep=True),
            signal_log=snapshot.backtest.signal_log.copy(deep=True),
            quality_notes=(
                None
                if snapshot.backtest.quality_notes is None
                else copy.deepcopy(snapshot.backtest.quality_notes)
            ),
            metadata=copy.deepcopy(snapshot.backtest.metadata),
            quality_momentum_evidence=snapshot.backtest.quality_momentum_evidence.copy(deep=True),
        ),
    )


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_declared_ui_actions_have_unique_keys_callbacks_and_signals() -> None:
    contracts = load_ui_acceptance_contracts()
    assert len(contracts) >= 10
    assert len({item.key for item in contracts}) == len(contracts)
    assert all(item.callback and (item.success_signal or item.controlled_error_signal) for item in contracts)
    assert all(item.route in PAGES or item.route == "/signals" for item in contracts)


def test_shell_exposes_stable_navigation_and_dashboard_keys() -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {"width": 1400, "route": "/"})()
    view = build_shell(page, state, "/")
    keys = {str(control.key) for control in _walk(view) if getattr(control, "key", None)}
    expected = {item.key for item in load_ui_acceptance_contracts()}
    assert {key for key in expected if key.startswith("navigation.")} <= keys
    assert {"dashboard.refresh-yfinance", "dashboard.run-algorithms", "dashboard.run-forecasting-models", "dashboard.show-scores"} <= keys


def test_invalid_contracts_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "ui.yaml"
    path.write_text(
        "version: 3\ncontrols:\n"
        "  - {key: navigation.home, route: /, control_label: Home, callback: go, "
        "success_signal: auto, controlled_error_signal: auto, acceptance_test: tests/test.py}\n"
        "  - {key: navigation.home, route: /, control_label: Duplicate, callback: go, "
        "success_signal: auto, controlled_error_signal: auto, acceptance_test: tests/test.py}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        load_ui_acceptance_contracts(path)
