"""Reproduction tests for slice S10 findings."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.pages import dashboard
from etf_cockpit.app.pages import portfolio
from etf_cockpit.app.pages import risk
from etf_cockpit.app.pages import strategy_builder
from etf_cockpit.app.pages import stress_lab
from etf_cockpit.app.pages import trust_evidence
from etf_cockpit.portfolio.optimiser import OptimiserConstraints, PortfolioOptimiser


def _walk_controls(control):
    """Walk all child controls under a Flet control hierarchy."""
    yield control
    children = (getattr(control, "controls", None) or [])
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        children = list(children) + [content]
    for child in children:
        yield from _walk_controls(child)


def test_s10_02_invalid_cash_never_becomes_feasible():
    returns = pd.DataFrame({"A": [0.01, -0.01] * 10, "B": [0.02, -0.02] * 10})
    comparison = PortfolioOptimiser(returns).compare(
        ["inverse_volatility"],
        constraints=OptimiserConstraints(cash_weight=-0.1, max_weight=0.6),
    )
    assert not comparison["feasible"].any()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S10-03: Risk analysis admits holdings newer than its snapshot",
)
def test_s10_03_risk_excludes_post_snapshot_holdings(monkeypatch):
    monkeypatch.setattr(
        risk,
        "_holdings_reference_day",
        lambda ref=None: pd.Timestamp(ref or "2026-10-06", tz="UTC").normalize(),
    )
    holdings = pd.DataFrame(
        [
            dict(
                etf_id="VWCE",
                as_of_date="2026-10-01",
                weight=1.0,
                score_eligible=True,
                authority="issuer",
                freshness="fresh",
                completeness="full",
                source_id="issuer",
                country="US",
                currency="USD",
                industry="Technology",
            )
        ]
    )
    monkeypatch.setattr(risk, "_load_holdings_evidence", lambda: holdings)
    for name in (
        "allocation_frame",
        "exposure_limit_report",
        "return_correlation_matrix",
        "drawdown_contribution",
    ):
        monkeypatch.setattr(risk, name, lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(risk, "build_direct_overlap_view", lambda *a, **k: {})
    factor = Mock(side_effect=RuntimeError("stop after capture"))
    monkeypatch.setattr(risk, "build_factor_risk_report", factor)
    snapshot = NS(
        config=NS(universe=NS(enabled_ids=["VWCE"])),
        holdings=pd.DataFrame(),
        prices=pd.DataFrame({"date": ["2026-09-02"]}),
        latest_features=pd.DataFrame(),
        data_report=NS(as_of_date="2026-09-02"),
    )
    with pytest.raises(RuntimeError, match="stop after capture"):
        risk.risk_page(None, NS(snapshot=snapshot))
    assert factor.call_args.args[3].empty


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S10-04: Credibility review buttons persist changes to another note",
)
def test_s10_04_review_targets_clicked_note(monkeypatch):
    rows = pd.DataFrame(
        [
            dict(as_of_date="2026-10-02", credibility_flag_status="available"),
            dict(as_of_date="2026-10-01", credibility_flag_status="available"),
        ]
    )
    for name in ("load_news_items", "load_calendar_events"):
        monkeypatch.setattr(trust_evidence, name, lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "contradiction_digest_records", lambda *a, **k: [])
    monkeypatch.setattr(trust_evidence, "load_manual_news", lambda *a: rows)
    save = Mock(
        return_value=rows.assign(
            credibility_review_status="reviewed",
            credibility_review_override="clear_flags",
        )
    )
    monkeypatch.setattr(trust_evidence, "save_manual_note_credibility_review", save)
    state = NS(snapshot=NS(prices=pd.DataFrame(), data_report=NS(as_of_date="2026-10-06")))
    root = trust_evidence._news_context_extra(state)
    controls = {c.key: c for c in _walk_controls(root)}
    controls["manual-note.reviewer"].value = "Reviewer"
    controls["manual-note.review-note"].value = "Checked this note"
    controls["manual-note.clear.0"].on_click(None)
    assert save.call_args.args[1] == 0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S10-05: Save ignores edited stress assumptions and scenario identity",
)
def test_s10_05_save_uses_current_controls(monkeypatch):
    facade = MagicMock()
    facade.list_saved.return_value = []
    facade.run.return_value = NS(status="available")
    facade.save.return_value = NS(scenario=NS(scenario_id="edited-stress"), revision=1)
    monkeypatch.setattr(stress_lab, "StressLabFacade", lambda *a: facade)
    monkeypatch.setattr(stress_lab, "_result_view", lambda result: ft.Text("result"))
    root = stress_lab.stress_lab_page(None, NS(snapshot=NS()))
    controls = {c.key: c for c in _walk_controls(root)}
    controls["stress-lab.run"].on_click(None)
    controls["stress-lab.equity"].value = "-30"
    controls["stress-lab.scenario-id"].value = "edited-stress"
    controls["stress-lab.save"].on_click(None)
    saved = facade.save.call_args.args[0]
    assert saved.scenario_id == "edited-stress"
    assert saved.shocks["equity"] == -0.3


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S10-06: Expanded dashboard digests exceed the advertised snapshot cutoff",
)
def test_s10_06_expanded_run_digest_respects_snapshot(monkeypatch):
    history = pd.DataFrame(
        {
            "run_id": ["old", "snapshot", "future"],
            "run_completed_at": [
                "2026-09-01T12:00:00Z",
                "2026-09-02T12:00:00Z",
                "2026-10-01T12:00:00Z",
            ],
        }
    )
    monkeypatch.setattr(dashboard, "score_history_frame", lambda: history)
    compare = Mock(return_value=NS(summary="comparison", changes=[]))
    monkeypatch.setattr(dashboard, "compare_runs", compare)
    state = NS(snapshot=NS(data_report=NS(as_of_date="2026-09-02")))
    dashboard._run_changes_digest(None, state)
    assert compare.call_args.args[1:] == ("snapshot", "old")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S10-07: Dropdown selections never trigger their registered refresh callbacks",
)
def test_s10_07_metric_dropdown_registers_selection_handler(monkeypatch):
    series = NS(
        metric="twr_index",
        unit="index",
        currency="EUR",
        status="available",
        reason=None,
        aggregation="day",
        quality="valid",
    )
    monkeypatch.setattr(portfolio, "load_portfolio_performance_series", lambda **k: series)
    monkeypatch.setattr(portfolio, "performance_series_frame", lambda s: pd.DataFrame())
    monkeypatch.setattr(
        portfolio,
        "portfolio_performance_chart",
        lambda *a, **k: NS(control=ft.Text("chart")),
    )
    root = portfolio._portfolio_performance_block(None)
    metric = next(c for c in _walk_controls(root) if c.key == "portfolio.performance.metric")
    assert callable(metric.on_select)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S10-08: Strategy toggle retains its old action and enabled badge",
)
def test_s10_08_strategy_can_toggle_twice_without_navigation(monkeypatch):
    enabled = {"t": True}
    facade = MagicMock()
    facade.templates = [
        NS(
            template_id="t",
            name="Template",
            version=1,
            definition_hash="abc",
            benchmark="B",
            stages={},
            context_only=False,
        )
    ]
    facade.enabled = ["t"]
    facade.matches.return_value = []
    facade.is_enabled.side_effect = lambda tid: enabled[tid]
    facade.set_enabled.side_effect = lambda tid, value: enabled.__setitem__(tid, value)
    monkeypatch.setattr(strategy_builder, "StrategyTemplateFacade", lambda: facade)
    root = strategy_builder.strategy_builder_page(None, NS(snapshot=NS(signals=[])))
    button = next(c for c in _walk_controls(root) if c.key == "strategy-builder.template.*")
    button.on_click(NS(control=button))
    button.on_click(NS(control=button))
    assert enabled["t"] is True
