from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages import portfolio
from etf_cockpit.app.router import PAGES
from etf_cockpit import services
from etf_cockpit.application import portfolio_sandbox
from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkDefinition,
    CanonicalBenchmarkRegistry,
    CashProxyDefinition,
    PeerSetDefinition,
    VWCE_CANONICAL_SHARE_CLASS,
    VwceAnchorEvidence,
    VwceListingObservation,
    declare_reference_portfolios,
)


def _state():
    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame(
            [
                {"etf_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0, "as_of_date": "2026-07-18", "known_at": "2026-07-18T12:00:00Z"},
                {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0, "as_of_date": "2026-07-18", "known_at": "2026-07-18T12:00:00Z"},
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


def _available_registry() -> CanonicalBenchmarkRegistry:
    common = {
        "effective_at": "2024-01-01T00:00:00Z",
        "known_at": "2024-01-02T00:00:00Z",
    }
    anchor = VwceAnchorEvidence(
        canonical_isin="IE00BK5BQT80",
        canonical_share_class_id=VWCE_CANONICAL_SHARE_CLASS,
        official_facts_as_of="2024-01-01",
        benchmark_name="source-backed fixture",
        benchmark_as_of="2024-01-01",
        fees={"ongoing_charges": "source-backed fixture"},
        fees_as_of="2024-01-01",
        tracking={"tracking_difference": "source-backed fixture"},
        tracking_as_of="2024-01-01",
        product_risk_indicator={"version": "source-backed-fixture-v1"},
        risk_indicator_as_of="2024-01-01",
        currency="USD",
        source_hashes=("a" * 64,),
        listing_observations=(VwceListingObservation(
            "listing:xetra", "VWCE", "XETR", "EUR",
            "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z", "a" * 64,
        ),),
        minimum_horizon_years=0.1,
        maximum_horizon_years=10.0,
        **common,
    )
    return CanonicalBenchmarkRegistry(
        benchmarks=(BenchmarkDefinition(
            "benchmark:global-equity", "1.0.0", "asset", {"asset_class": "equity"},
            "EUR", 0.1, 10.0, start_date="2020-01-01", end_date="2030-01-01",
            methodology="source-backed fixture", constituents=("VWCE",),
            source_hashes=("a" * 64,), **common,
        ),),
        cash_proxies=(CashProxyDefinition(
            "cash:EUR", "1.0.0", {"asset_class": "equity"}, "EUR", 0.1, 10.0,
            start_date="2020-01-01", end_date="2030-01-01",
            methodology="source-backed fixture", source_hashes=("a" * 64,), **common,
        ),),
        peer_sets=(PeerSetDefinition(
            "peers:global-equity", "1.0.0", "asset", {"asset_class": "equity"},
            ("VWCE",), methodology="source-backed fixture", source_hashes=("a" * 64,),
            **common,
        ),),
        reference_portfolios=declare_reference_portfolios(
            ("VWCE",), current_weights={"VWCE": 1.0}, currency="EUR",
            minimum_horizon_years=0.1, maximum_horizon_years=10.0,
            start_date="2020-01-01", end_date="2030-01-01", **common,
        ),
        vwce_anchors=(anchor,),
    )


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
    assert "benchmark_reference: status=unavailable" in result_text
    assert "profile_relative: status=unavailable" in result_text
    assert "provenance=registry_hash:" in result_text
    assert "provenance=anchor_digest:" in result_text
    assert "canonical_share_class_id:unavailable" in result_text
    assert "listing_id:unavailable" in result_text
    assert "effective_date:unavailable" in result_text
    assert "knowledge_cutoff:unavailable" in result_text
    overlap_text = _text(_by_key(root, "portfolio.etf-overlap"))
    assert "coverage_status=missing" in overlap_text
    assert "No holdings evidence is available" in overlap_text


def test_portfolio_ui_renders_available_canonical_identities_versions_and_digests(monkeypatch) -> None:
    state = _state()
    registry = _available_registry()
    monkeypatch.setattr(services, "load_canonical_benchmark_registry", lambda path: registry)
    evidence = services._benchmark_reference_snapshot_inputs(
        state.snapshot.config, state.snapshot.data_report.as_of_date,
        state.snapshot.holdings,
    )
    state.snapshot.benchmark_reference_registry = evidence["registry"]
    state.snapshot.benchmark_reference_instrument = evidence["instrument"]
    state.snapshot.benchmark_reference_currency = evidence["currency"]
    state.snapshot.benchmark_reference_horizon_years = evidence["horizon_years"]
    state.snapshot.benchmark_reference_start_date = evidence["start_date"]
    state.snapshot.benchmark_reference_end_date = evidence["end_date"]
    state.snapshot.benchmark_reference_decision_time = evidence["decision_time"]
    state.snapshot.benchmark_reference_portfolio_ids = evidence["reference_ids"]
    state.snapshot.vwce_anchor_evidence = evidence["anchor"]
    state.snapshot.vwce_listing_id = evidence["listing_id"]
    state.snapshot.vwce_conversion_evidence = None

    root = portfolio.portfolio_page(None, state)
    _set_candidate(root)
    _by_key(root, "portfolio.analyse").on_click(None)
    result_text = _text(_by_key(root, "portfolio.results"))
    assert "benchmark_reference: status=available" in result_text
    assert "benchmark=benchmark:global-equity@1.0.0 digest:" in result_text
    assert "cash=cash:EUR@1.0.0 digest:" in result_text
    assert "peer=peers:global-equity@1.0.0 digest:" in result_text
    assert "reference:equal_weight@1.0.0 digest:" in result_text
    assert "reference:maximum_diversification@1.0.0 digest:" in result_text
    assert "reference:no_trade@1.0.0 digest:" in result_text
    assert "provenance=registry_hash:" in result_text
    assert f"canonical_share_class_id:{VWCE_CANONICAL_SHARE_CLASS}" in result_text
    assert "listing_id:listing:xetra" in result_text
    assert "effective_date:2025-07-18" in result_text
    assert "knowledge_cutoff:2026-07-18T23:59:59+00:00" in result_text


def test_snapshot_selector_cannot_relabel_the_supplied_snapshot() -> None:
    state = _state()
    state.snapshot.account_id = "account-A"
    state.snapshot.account_ids = ("account-A", "account-B")
    root = portfolio.portfolio_page(None, state)

    account = _by_key(root, "portfolio.account")
    assert [option.key for option in account.options] == ["account-A"]
    account.value = "account-B"
    _by_key(root, "portfolio.analyse").on_click(None)

    assert "does not match supplied snapshot" in str(_by_key(root, "portfolio.status").value)


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


def test_rebalance_preview_reports_mixed_asset_inapplicable_without_dropping_it() -> None:
    state = _state()
    state.snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0, "holding_view": "direct"},
            {"instrument_id": "AAPL", "asset_type": "stock", "current_weight": 0.3, "market_value_eur": 30_000.0, "holding_view": "direct"},
        ]
    )
    root = portfolio.portfolio_page(None, state)
    for control in _walk(root):
        if str(getattr(control, "key", "")).startswith("portfolio.target-weight."):
            control.value = "0"
    _by_key(root, "portfolio.target-weight.VWCE").value = "40"
    _by_key(root, "portfolio.target-weight.AAPL").value = "30"
    _by_key(root, "portfolio.cash-weight").value = "30"

    _by_key(root, "portfolio.rebalance-preview").on_click(None)

    assert "inapplicable for mixed-asset targets" in str(_by_key(root, "portfolio.status").value)
    result_text = _text(_by_key(root, "portfolio.rebalance-results"))
    assert "Inapplicable mixed-asset targets: AAPL" in result_text
    assert "execution_allowed=false" in result_text


def test_rebalance_preview_blocks_zero_target_exit_for_held_mixed_asset() -> None:
    state = _state()
    state.snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0, "holding_view": "direct"},
            {"instrument_id": "AAPL", "asset_type": "stock", "current_weight": 0.3, "market_value_eur": 30_000.0, "holding_view": "direct"},
        ]
    )
    root = portfolio.portfolio_page(None, state)
    for control in _walk(root):
        if str(getattr(control, "key", "")).startswith("portfolio.target-weight."):
            control.value = "0"
    _by_key(root, "portfolio.target-weight.VWCE").value = "70"
    _by_key(root, "portfolio.target-weight.AAPL").value = "0"
    _by_key(root, "portfolio.cash-weight").value = "30"

    _by_key(root, "portfolio.rebalance-preview").on_click(None)

    assert "inapplicable for mixed-asset targets" in str(_by_key(root, "portfolio.status").value)
    result_text = _text(_by_key(root, "portfolio.rebalance-results"))
    assert "Inapplicable mixed-asset targets: AAPL" in result_text
    assert "EUR -21,000.00" not in result_text
    assert "execution_allowed=false" in result_text


def test_rebalance_preview_blocks_zero_target_exit_for_configured_stock() -> None:
    state = _state()
    state.snapshot.holdings = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0, "holding_view": "direct"},
            {"instrument_id": "UCG", "current_weight": 0.3, "market_value_eur": 30_000.0, "holding_view": "direct"},
        ]
    )
    root = portfolio.portfolio_page(None, state)
    for control in _walk(root):
        if str(getattr(control, "key", "")).startswith("portfolio.target-weight."):
            control.value = "0"
    _by_key(root, "portfolio.target-weight.VWCE").value = "70"
    _by_key(root, "portfolio.target-weight.UCG").value = "0"
    _by_key(root, "portfolio.cash-weight").value = "30"

    _by_key(root, "portfolio.rebalance-preview").on_click(None)

    assert "inapplicable for mixed-asset targets" in str(_by_key(root, "portfolio.status").value)
    result_text = _text(_by_key(root, "portfolio.rebalance-results"))
    assert "Inapplicable mixed-asset targets: UCG" in result_text
    assert "EUR -21,000.00" not in result_text
    assert "EUR -30,000.00" not in result_text
    assert "execution_allowed=false" in result_text
