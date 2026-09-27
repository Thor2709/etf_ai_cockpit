from __future__ import annotations

import copy
from dataclasses import replace
import time
import pytest

from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.state import AppState
from etf_cockpit.app.router import PAGES, navigate_to
from etf_cockpit.services import build_snapshot


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


class _Page:
    route = "/"
    width = 1400
    update_count = 0
    views: list[object] = []

    def update(self) -> None:
        self.update_count += 1


def test_source_workflow_success_and_failure_have_visible_terminal_states(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", tmp_path / "activity.jsonl")
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _Page()

    _run_action(page, state, "Deterministic success", lambda: "done")
    deadline = time.time() + 5
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.02)
    assert state.recent_activity[-1].status == "success"

    _run_action(page, state, "Deterministic failure", lambda: (_ for _ in ()).throw(TimeoutError("provider timeout")))
    deadline = time.time() + 5
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.02)
    assert state.recent_activity[-1].status == "failed"
    assert "timeout" in state.recent_activity[-1].message.lower()
    assert page.update_count >= 4


def test_navigation_matrix_has_all_declared_trust_routes() -> None:
    snapshot = _snapshot_copy()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _Page()
    for route in ("/", "/providers", "/evidence", "/filings", "/etf-disclosures", "/news-context", "/diagnostics"):
        navigate_to(page, state, route)
        assert page.route == route
        assert route in PAGES
