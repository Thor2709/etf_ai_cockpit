"""Bughunt D (#981): rebalance report and portfolio sandbox regression tests."""

from __future__ import annotations

from dataclasses import replace
import math

import pandas as pd
import pytest

from etf_cockpit.application.portfolio_sandbox import (
    analyse_portfolio_candidate,
    build_portfolio_candidate,
    draft_portfolio_proposal,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio.rebalancing import (
    RebalanceConstraints,
    build_rebalance_report,
    rebalance_score,
)
from etf_cockpit.portfolio.sandbox import holdings_checksum, select_holdings_view
from tests.test_portfolio_sandbox import _snapshot


def _config():
    return load_config()


def _holdings(**price: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.40, "market_value_eur": 40_000.0, "quantity": 40.0, "price_eur": price.get("vwce", 1_000.0)},
            {"etf_id": "LYP6", "current_weight": 0.20, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": price.get("lyp6", 1_000.0)},
        ]
    )


def _draft_snapshot():
    snapshot = _snapshot()
    candidate = build_portfolio_candidate(
        snapshot,
        name="Draft",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.20, "LYP6": 0.10},
        cash_weight=0.7,
    )
    return snapshot, analyse_portfolio_candidate(snapshot, candidate)


# --- D013-N001 / D013-N002 -------------------------------------------------


def test_unavailable_rebalancing_emits_no_draft_changes() -> None:
    snapshot, analysis = _draft_snapshot()
    unavailable = replace(
        analysis,
        service_evidence={**analysis.service_evidence, "rebalancing": {"status": "unavailable", "reason": "no inputs", "execution_allowed": False}},
    )
    handoff = draft_portfolio_proposal(snapshot, unavailable)
    assert handoff["changes"] == []
    assert handoff["rejected"]
    assert all("rebalancing_unavailable" in item["reason"] for item in handoff["rejected"])
    assert handoff["evidence"]["no_trade_alternative"]["status"] == "unavailable"


def test_draft_handoff_binds_one_snapshot() -> None:
    snapshot, analysis = _draft_snapshot()
    other = _snapshot()
    other.holdings = other.holdings.assign(current_weight=[0.30, 0.30], market_value_eur=[30_000.0, 30_000.0])
    with pytest.raises(ValueError, match="snapshot"):
        draft_portfolio_proposal(other, analysis)
    # The matching snapshot still drafts.
    assert draft_portfolio_proposal(snapshot, analysis)["source_snapshot"]["source_checksum"] == analysis.snapshot_binding.source_checksum


# --- D102-N001 / D102-N003 / D002 ------------------------------------------


@pytest.mark.parametrize("fractional", [True, False])
def test_buy_rounding_never_overshoots_target(fractional: bool) -> None:
    # Full buy is 3_200 EUR (3.2 lots), partial 1_600 EUR (1.6 lots): nearest-lot rounding would buy 2 lots (2_000).
    report = build_rebalance_report(
        _config(),
        _holdings(),
        {"VWCE": 0.432, "LYP6": 0.20},
        target_cash_weight=0.368,
        portfolio_value_eur=100_000.0,
        constraints=RebalanceConstraints(lot_size=1.0, allow_fractional_lots=fractional),
    )
    for name, scale in (("full", 1.0), ("partial", 0.5)):
        vwce = next(item for item in report.alternatives[name].trades if item.instrument_id == "VWCE")
        assert 0 < vwce.trade_value_eur <= 3_200.0 * scale + 1e-6, name
        assert vwce.proposed_weight <= 0.40 + 0.032 * scale + 1e-9, name


def test_conflicting_duplicate_quotes_are_a_conflict() -> None:
    holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.20, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": 1_000.0},
            {"etf_id": "VWCE", "current_weight": 0.20, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": 1_100.0},
        ]
    )
    with pytest.raises(ValueError, match="conflict"):
        build_rebalance_report(_config(), holdings, {"VWCE": 0.6}, target_cash_weight=0.4)
    # Row order cannot matter either.
    with pytest.raises(ValueError, match="conflict"):
        build_rebalance_report(_config(), holdings.iloc[::-1], {"VWCE": 0.6}, target_cash_weight=0.4)


def test_agreeing_duplicate_quotes_are_accepted() -> None:
    holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.20, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": 1_000.0},
            {"etf_id": "VWCE", "current_weight": 0.20, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": 1_000.0},
        ]
    )
    report = build_rebalance_report(_config(), holdings, {"VWCE": 0.6}, target_cash_weight=0.4)
    assert report.trades[0].price_eur == 1_000.0


def test_turnover_constraint_enforced() -> None:
    report = build_rebalance_report(
        _config(),
        _holdings(),
        {"VWCE": 0.20, "LYP6": 0.60},
        target_cash_weight=0.20,
        constraints=RebalanceConstraints(max_turnover=0.10),
    )
    for name in ("full", "partial", "deferred", "no_trade"):
        alternative = report.alternatives[name]
        turnover = sum(abs(item.trade_value_eur) for item in alternative.trades) / report.portfolio_value_eur
        assert turnover <= 0.10 + 1e-9, name
    assert sum(abs(item.trade_value_eur) for item in report.trades) > 0
    assert "turnover_limit_applied" in report.warnings
    assert report.assumptions["max_turnover"] == 0.10


def test_turnover_limit_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        RebalanceConstraints(max_turnover=-0.1)


def test_sandbox_rebalancing_evidence_enforces_turnover_limit() -> None:
    snapshot, analysis = _draft_snapshot()
    evidence = analysis.service_evidence["rebalancing"]
    assert evidence["turnover_limit"] == snapshot.config.risks.portfolio_limits.max_monthly_turnover
    assert evidence["max_turnover_applied"] is True
    assert evidence["planned_turnover"] <= evidence["turnover_limit"] + 1e-9


def test_cash_and_notional_are_consistent() -> None:
    # Weights claim 130% invested: cash cannot be inferred as zero silently.
    holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.80, "market_value_eur": 80_000.0},
            {"etf_id": "LYP6", "current_weight": 0.50, "market_value_eur": 50_000.0},
        ]
    )
    with pytest.raises(ValueError, match="exceed"):
        build_rebalance_report(_config(), holdings, {"VWCE": 0.5, "LYP6": 0.5}, portfolio_value_eur=100_000.0)
    # Holdings values larger than the supplied notional are inconsistent with the weights.
    with pytest.raises(ValueError, match="notional"):
        build_rebalance_report(_config(), _holdings(), {"VWCE": 0.5, "LYP6": 0.5}, portfolio_value_eur=30_000.0)
    # D002-N001 DEFERRED (documented): weights are authoritative for cash. Values of only 30% of the
    # notional with weights summing to 0.6 are NOT rejected: a weight/value-over-notional check would
    # reject every what-if whose analysis notional differs from the held value (owner/Opus decision).
    mixed = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.40, "market_value_eur": 20_000.0},
            {"etf_id": "LYP6", "current_weight": 0.20, "market_value_eur": 10_000.0},
        ]
    )
    report = build_rebalance_report(_config(), mixed, {"VWCE": 0.5, "LYP6": 0.5}, portfolio_value_eur=100_000.0)
    assert report.trades


# --- D102-N002 --------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", None, float("nan")])
def test_blank_holding_id_rejected(blank: object) -> None:
    holdings = pd.DataFrame(
        [
            {"etf_id": "AAA", "current_weight": 0.60, "market_value_eur": 600.0},
            {"etf_id": blank, "current_weight": 0.40, "market_value_eur": 400.0},
        ]
    )
    with pytest.raises(ValueError, match="blank"):
        build_rebalance_report(_config(), holdings, {"VWCE": 1.0}, portfolio_value_eur=1_000.0)


# --- D02-C2 -----------------------------------------------------------------


def test_target_ids_colliding_after_trim_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        build_rebalance_report(_config(), _holdings(), {"VWCE": 0.3, " VWCE ": 0.4}, target_cash_weight=0.3)


def test_restricted_positions_are_normalised_to_instrument_identity() -> None:
    report = build_rebalance_report(
        _config(),
        _holdings(),
        {"VWCE": 0.60, "LYP6": 0.20},
        target_cash_weight=0.20,
        constraints=RebalanceConstraints(restricted_positions=(" vwce ",)),
    )
    vwce = next(item for item in report.trades if item.instrument_id == "VWCE")
    assert vwce.status == "restricted"
    assert vwce.trade_value_eur == 0.0


@pytest.mark.parametrize("current", [float("nan"), float("inf")])
def test_non_finite_rebalance_score_input_is_not_buy_pressure(current: float) -> None:
    assert math.isnan(rebalance_score(current, 0.10, 0.05))
    assert math.isnan(rebalance_score(0.05, current, 0.05))
    assert math.isnan(rebalance_score(0.05, 0.10, current))


def test_buy_reduced_to_zero_by_cash_fit_is_a_hold() -> None:
    holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.98, "market_value_eur": 98_000.0},
            {"etf_id": "LYP6", "current_weight": 0.0, "market_value_eur": 0.0},
        ]
    )
    report = build_rebalance_report(
        _config(),
        holdings,
        {"VWCE": 0.60, "LYP6": 0.38},
        target_cash_weight=0.02,
        constraints=RebalanceConstraints(cash_buffer_weight=0.02),
    )
    for trade in report.alternatives["full"].trades:
        if trade.trade_value_eur == 0:
            assert trade.action == "hold", trade


# --- D113-N001 ---------------------------------------------------------------


def _combined_holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"etf_id": "SYNTH", "current_weight": 1.0, "market_value_eur": 100_000.0, "holding_view": "direct"},
            {"etf_id": "AAPL", "current_weight": 0.6, "market_value_eur": 60_000.0, "holding_view": "look_through"},
            {"etf_id": "MSFT", "current_weight": 0.4, "market_value_eur": 40_000.0, "holding_view": "look_through"},
        ]
    )


def test_direct_and_look_through_not_double_counted() -> None:
    combined = select_holdings_view(_combined_holdings(), "combined")
    assert combined["current_weight"].sum() == pytest.approx(1.0)
    assert combined["market_value_eur"].sum() == pytest.approx(100_000.0)
    assert list(combined["etf_id"]) == ["SYNTH"]
    # The pure look-through view and look-through-only evidence stay available.
    assert list(select_holdings_view(_combined_holdings(), "look_through")["etf_id"]) == ["AAPL", "MSFT"]
    only_look_through = _combined_holdings().iloc[1:]
    assert len(select_holdings_view(only_look_through, "combined")) == 2


def test_combined_view_changes_source_checksum_consistently() -> None:
    frame = _combined_holdings()
    assert holdings_checksum(select_holdings_view(frame, "combined")) == holdings_checksum(select_holdings_view(frame, "direct"))


# --- D113-N002 ---------------------------------------------------------------


def _analysis_for(snapshot):
    candidate = build_portfolio_candidate(
        snapshot,
        name="Cfg",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.30, "LYP6": 0.30},
        cash_weight=0.4,
    )
    return analyse_portfolio_candidate(snapshot, candidate)


def test_config_change_changes_the_checksum() -> None:
    snapshot = _snapshot()
    before = _analysis_for(snapshot).snapshot_binding
    snapshot.config = snapshot.config.model_copy(deep=True)
    snapshot.config.risks.portfolio_limits.max_single_etf_weight = 0.5
    after = _analysis_for(snapshot).snapshot_binding
    assert before.price_source_checksum != after.price_source_checksum
    assert before.source_checksum == after.source_checksum


def test_unchanged_config_keeps_the_checksum() -> None:
    snapshot = _snapshot()
    assert _analysis_for(snapshot).snapshot_binding == _analysis_for(snapshot).snapshot_binding


# --- D113-N003 ---------------------------------------------------------------


def test_price_scope_filters_identity_columns() -> None:
    snapshot = _snapshot()
    days = pd.date_range("2026-06-01", periods=5, freq="D")
    rows = []
    for account, level in (("default", 100.0), ("other", 500.0)):
        for index, day in enumerate(days):
            rows.append({"date": day, "etf_id": "VWCE", "account_id": account, "portfolio_id": "default", "adjusted_close": level + index})
    snapshot.prices = pd.DataFrame(rows)
    candidate = build_portfolio_candidate(
        snapshot,
        name="Prices",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
    )
    from etf_cockpit.application import portfolio_sandbox as module

    analysis = analyse_portfolio_candidate(snapshot, candidate)
    scoped = module._bound_service_prices(snapshot, analysis, None)
    assert set(scoped["account_id"]) == {"default"}
    assert len(scoped) == len(days)
    reversed_snapshot = _snapshot()
    reversed_snapshot.prices = snapshot.prices.iloc[::-1].reset_index(drop=True)
    reversed_scoped = module._bound_service_prices(reversed_snapshot, analysis, None)
    assert scoped.sort_values("date")["adjusted_close"].tolist() == reversed_scoped.sort_values("date")["adjusted_close"].tolist()


def test_conflicting_duplicate_price_series_are_excluded_not_collapsed() -> None:
    from etf_cockpit.application import portfolio_sandbox as module

    snapshot = _snapshot()
    days = pd.date_range("2026-06-01", periods=4, freq="D")
    rows = []
    for label, level in (("a", 100.0), ("b", 200.0)):
        for index, day in enumerate(days):
            rows.append({"date": day, "etf_id": "VWCE", "series": label, "adjusted_close": level + index})
            rows.append({"date": day, "etf_id": "LYP6", "series": label, "adjusted_close": 50.0 + index})
    snapshot.prices = pd.DataFrame(rows)
    analysis = _analysis_for(snapshot)
    for frame in (snapshot.prices, snapshot.prices.iloc[::-1].reset_index(drop=True)):
        snapshot.prices = frame
        scoped = module._bound_service_prices(snapshot, analysis, None)
        assert scoped.empty or set(scoped["etf_id"]) == {"LYP6"}
        assert scoped.attrs["price_conflict_ids"] == ("VWCE",)


def test_price_conflict_check_sees_only_vintages_visible_at_the_cutoff() -> None:
    from etf_cockpit.application import portfolio_sandbox as module

    snapshot = _snapshot()
    days = pd.date_range("2026-06-01", periods=4, freq="D")
    rows = []
    for index, day in enumerate(days):
        rows.append({"date": day, "etf_id": "VWCE", "known_at": "2026-06-01", "adjusted_close": 100.0 + index})
        # A later restatement of the same date, known only after the cutoff, must not exclude VWCE.
        rows.append({"date": day, "etf_id": "VWCE", "known_at": "2099-01-01", "adjusted_close": 90.0 + index})
        rows.append({"date": day, "etf_id": "LYP6", "known_at": "2026-06-01", "adjusted_close": 50.0 + index})
    snapshot.prices = pd.DataFrame(rows)
    scoped = module._bound_service_prices(snapshot, _analysis_for(snapshot), None)
    assert set(scoped["etf_id"]) == {"VWCE", "LYP6"}
    assert "price_conflict_ids" not in scoped.attrs
    assert scoped.loc[scoped["etf_id"] == "VWCE", "adjusted_close"].tolist() == [100.0, 101.0, 102.0, 103.0]
