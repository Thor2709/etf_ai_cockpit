from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages import portfolio
from etf_cockpit.app.router import PAGES
from etf_cockpit.application import portfolio_sandbox
from etf_cockpit.core.config import load_config


def _state():
    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame(
            [
                {"etf_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0},
                {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0},
            ]
        ),
        universe_revision="universe-ui-1",
        data_report=SimpleNamespace(as_of_date="2026-07-18"),
    )
    return SimpleNamespace(snapshot=snapshot, last_message="Ready")


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


def _by_key(root, key: str):
    return next(control for control in _walk(root) if getattr(control, "key", None) == key)


def _text(root) -> str:
    return "\n".join(str(control.value) for control in _walk(root) if isinstance(control, ft.Text))


def _set_candidate(root) -> None:
    for control in _walk(root):
        if str(getattr(control, "key", "")).startswith("portfolio.target-weight."):
            control.value = "0"
    _by_key(root, "portfolio.target-weight.VWCE").value = "60"
    _by_key(root, "portfolio.target-weight.LYP6").value = "30"
    _by_key(root, "portfolio.cash-weight").value = "10"


def test_portfolio_sandbox_exposes_non_executable_controls_and_results() -> None:
    root = portfolio.portfolio_page(None, _state())
    keys = {str(control.key) for control in _walk(root) if getattr(control, "key", None)}
    assert {
        "portfolio.workspace-name",
        "portfolio.analysis-notional",
        "portfolio.cash-weight",
        "portfolio.analyse",
        "portfolio.save",
        "portfolio.load",
        "portfolio.reset-current",
    } <= keys
    text = _text(root)
    assert "Portfolio Sandbox" in text
    assert "Execution" in text and "disabled" in text
    assert "ETF direct overlap" in text
    assert "coverage_status=missing" in text
    assert "execution_allowed=false" in text
    assert PAGES["/portfolio"] == ("Portfolio Sandbox", portfolio.portfolio_page)


def test_portfolio_sandbox_validation_and_analysis_are_readable() -> None:
    root = portfolio.portfolio_page(None, _state())
    _by_key(root, "portfolio.cash-weight").value = "90"
    _by_key(root, "portfolio.analyse").on_click(None)
    assert "must equal 100%" in str(_by_key(root, "portfolio.status").value)
    assert "results are unavailable" in _text(_by_key(root, "portfolio.results"))

    _set_candidate(root)
    _by_key(root, "portfolio.analyse").on_click(None)
    assert "execution remains disabled" in str(_by_key(root, "portfolio.status").value)
    result_text = _text(_by_key(root, "portfolio.results"))
    assert "Current versus candidate" in result_text
    assert "EUR +12,000.00" in result_text
    assert "ETF overlap is unavailable" in result_text
    overlap_text = _text(_by_key(root, "portfolio.etf-overlap"))
    assert "coverage_status=missing" in overlap_text
    assert "No holdings evidence is available" in overlap_text


def test_portfolio_sandbox_save_load_and_stale_states(monkeypatch, tmp_path) -> None:
    state = _state()

    def save(*args, **kwargs):
        return portfolio_sandbox.save_portfolio_candidate(*args, **kwargs, root=tmp_path)

    def load(*args, **kwargs):
        return portfolio_sandbox.load_portfolio_candidate(*args, **kwargs, root=tmp_path)

    monkeypatch.setattr(portfolio, "save_portfolio_candidate", save)
    monkeypatch.setattr(portfolio, "load_portfolio_candidate", load)
    root = portfolio.portfolio_page(None, state)
    _by_key(root, "portfolio.workspace-name").value = "UI candidate"
    _set_candidate(root)
    _by_key(root, "portfolio.save").on_click(None)
    assert "Saved local candidate revision 1" in str(_by_key(root, "portfolio.status").value)

    _by_key(root, "portfolio.target-weight.VWCE").value = "50"
    _by_key(root, "portfolio.target-weight.LYP6").value = "40"
    _by_key(root, "portfolio.load").on_click(None)
    assert _by_key(root, "portfolio.target-weight.VWCE").value == "60.0000"
    assert "Loaded local candidate revision 1" in str(_by_key(root, "portfolio.status").value)

    state.snapshot.universe_revision = "universe-ui-2"
    _by_key(root, "portfolio.load").on_click(None)
    assert "source binding changed" in str(_by_key(root, "portfolio.status").value)


def test_portfolio_sandbox_new_name_starts_an_independent_revision(monkeypatch, tmp_path) -> None:
    state = _state()

    def save(*args, **kwargs):
        return portfolio_sandbox.save_portfolio_candidate(*args, **kwargs, root=tmp_path)

    monkeypatch.setattr(portfolio, "save_portfolio_candidate", save)
    root = portfolio.portfolio_page(None, state)
    _set_candidate(root)
    _by_key(root, "portfolio.workspace-name").value = "Candidate A"
    _by_key(root, "portfolio.save").on_click(None)
    assert "revision 1" in str(_by_key(root, "portfolio.status").value)
    _by_key(root, "portfolio.workspace-name").value = "Candidate B"
    _by_key(root, "portfolio.save").on_click(None)
    assert "revision 1" in str(_by_key(root, "portfolio.status").value)


def test_portfolio_sandbox_stale_save_conflict_is_readable(monkeypatch, tmp_path) -> None:
    state = _state()

    def save(*args, **kwargs):
        return portfolio_sandbox.save_portfolio_candidate(*args, **kwargs, root=tmp_path)

    monkeypatch.setattr(portfolio, "save_portfolio_candidate", save)
    root = portfolio.portfolio_page(None, state)
    _set_candidate(root)
    _by_key(root, "portfolio.workspace-name").value = "Conflict candidate"
    _by_key(root, "portfolio.save").on_click(None)
    portfolio_sandbox.save_portfolio_candidate(
        state.snapshot,
        name="Conflict candidate",
        analysis_notional_eur=60_000,
        target_weights={"VWCE": 0.5, "LYP6": 0.4},
        cash_weight=0.1,
        expected_revision=1,
        root=tmp_path,
    )
    _by_key(root, "portfolio.save").on_click(None)
    assert "newer local revision exists" in str(_by_key(root, "portfolio.status").value)


def test_portfolio_sandbox_empty_holdings_state_is_explicit() -> None:
    state = _state()
    state.snapshot.holdings = pd.DataFrame(columns=["etf_id", "current_weight", "market_value_eur"])
    root = portfolio.portfolio_page(None, state)
    assert "No current holdings are available" in str(_by_key(root, "portfolio.status").value)
    assert "zero current exposure" in _text(_by_key(root, "portfolio.results"))


def test_portfolio_reset_uses_current_weights() -> None:
    root = portfolio.portfolio_page(None, _state())
    _set_candidate(root)
    _by_key(root, "portfolio.reset-current").on_click(None)
    assert _by_key(root, "portfolio.target-weight.VWCE").value == "40.0000"
    assert _by_key(root, "portfolio.target-weight.LYP6").value == "20.0000"
    assert _by_key(root, "portfolio.cash-weight").value == "40.0000"


def test_portfolio_controls_and_reset_cover_selected_mixed_assets() -> None:
    state = _state()
    state.snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000, "holding_view": "direct"},
            {"instrument_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000, "holding_view": "direct"},
            {"instrument_id": "AAPL", "asset_type": "stock", "current_weight": 0.15, "market_value_eur": 15_000, "holding_view": "direct"},
            {"instrument_id": "BOND-1", "asset_type": "fixed_rate_bond", "current_weight": 0.1, "market_value_eur": 10_000, "holding_view": "direct"},
            {"instrument_id": "ETF-LOOK", "asset_type": "etf", "current_weight": 0.05, "market_value_eur": 5_000, "holding_view": "look_through"},
        ]
    )
    root = portfolio.portfolio_page(None, state)
    assert "current stock" in str(_by_key(root, "portfolio.target-weight.AAPL").label)
    assert "current fixed_rate_bond" in str(_by_key(root, "portfolio.target-weight.BOND-1").label)
    assert _by_key(root, "portfolio.target-weight.ETF-LOOK") is not None

    _by_key(root, "portfolio.holdings-view").value = "direct"
    _by_key(root, "portfolio.reset-current").on_click(None)
    assert _by_key(root, "portfolio.target-weight.AAPL").value == "15.0000"
    assert _by_key(root, "portfolio.target-weight.BOND-1").value == "10.0000"
    assert _by_key(root, "portfolio.target-weight.ETF-LOOK").value == "0.0000"
    assert _by_key(root, "portfolio.cash-weight").value == "15.0000"


def test_portfolio_storage_failure_is_reported_without_crashing(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise portfolio_sandbox.PortfolioSandboxPersistenceError("local store is read-only")

    monkeypatch.setattr(portfolio, "load_portfolio_candidate", unavailable)
    root = portfolio.portfolio_page(None, _state())
    _by_key(root, "portfolio.load").on_click(None)
    assert "Candidate not loaded: local store is read-only" in str(_by_key(root, "portfolio.status").value)


def test_portfolio_sandbox_shows_snapshot_lineage_capability_and_draft_boundary() -> None:
    state = _state()
    state.snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "asset_type": "etf", "current_weight": 0.4, "market_value_eur": 40_000.0, "holding_view": "direct"},
            {"instrument_id": "ETF-HOLDING", "asset_type": "etf", "current_weight": 0.1, "market_value_eur": 10_000.0, "holding_view": "look_through"},
            {"instrument_id": "COIN", "asset_type": "crypto", "current_weight": 0.1, "market_value_eur": 10_000.0, "holding_view": "direct"},
        ]
    )
    root = portfolio.portfolio_page(None, state)
    keys = {str(control.key) for control in _walk(root) if getattr(control, "key", None)}
    assert {"portfolio.account", "portfolio.portfolio", "portfolio.snapshot", "portfolio.holdings-view", "portfolio.export", "portfolio.draft-proposal"} <= keys
    text = _text(root)
    assert "Selected portfolio snapshot" in text
    assert "Direct and look-through holdings" in text
    assert "ISSUE-0130:draft-only" in text
    assert "execution_allowed=false" in text

def test_portfolio_rebalance_preview_exposes_alternatives_and_assumptions() -> None:
    root = portfolio.portfolio_page(None, _state())
    _set_candidate(root)
    _by_key(root, "portfolio.rebalance-preview").on_click(None)
    result_text = _text(_by_key(root, "portfolio.rebalance-results"))
    assert "Rebalance workspace" in result_text
    assert "Alternatives" in result_text
    assert "Full" in result_text and "No Trade" in result_text
    assert "lot_policy=integer_lots" in result_text
    assert "tax_jurisdiction=not_provided" in result_text
    assert "execution_allowed=false" in result_text


def test_rebalance_preview_uses_selected_view_and_cites_snapshot() -> None:
    state = _state()
    state.snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0, "holding_view": "direct"},
            {"instrument_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0, "holding_view": "look_through"},
        ]
    )
    root = portfolio.portfolio_page(None, state)
    _by_key(root, "portfolio.holdings-view").value = "direct"
    for control in _walk(root):
        if str(getattr(control, "key", "")).startswith("portfolio.target-weight."):
            control.value = "0"
    _by_key(root, "portfolio.target-weight.VWCE").value = "15"
    _by_key(root, "portfolio.cash-weight").value = "85"

    _by_key(root, "portfolio.rebalance-preview").on_click(None)

    result_text = _text(_by_key(root, "portfolio.rebalance-results"))
    assert "VWCE" in result_text
    assert "LYP6" not in result_text
    assert "account=default" in result_text
    assert "portfolio=default" in result_text
    assert "snapshot=current" in result_text
    assert "as_of=2026-07-18" in result_text
    assert "view=direct" in result_text
