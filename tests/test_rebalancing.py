from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import etf_cockpit.application.portfolio_sandbox as portfolio_sandbox
from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio.sandbox import PortfolioSnapshotBinding
from etf_cockpit.portfolio.rebalancing import (
    RebalanceConstraints,
    build_rebalance_report,
    proposed_new_weight,
    rebalance_score,
    target_weight_drift,
)
from etf_cockpit.application.portfolio_sandbox import validate_portfolio_draft_handoff


def test_target_weight_drift_and_rebalance_score() -> None:
    assert target_weight_drift(0.15, 0.10) == 0.05
    assert rebalance_score(0.05, 0.10, 0.05) == 1.0
    assert rebalance_score(0.15, 0.10, 0.05) == -1.0


def test_proposed_new_weight_moves_halfway_to_target() -> None:
    new_weight = proposed_new_weight(0.06, 0.10, "add", 0.15)
    assert new_weight == 0.08


def _holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.40, "market_value_eur": 40_000.0, "quantity": 40.0, "price_eur": 1_000.0},
            {"etf_id": "LYP6", "current_weight": 0.20, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": 1_000.0},
        ]
    )


def _config() -> SimpleNamespace:
    return SimpleNamespace(config=load_config())


def test_rebalance_balances_lot_aware_proposals_and_exposes_assumptions() -> None:
    report = build_rebalance_report(
        _config().config,
        _holdings(),
        {"VWCE": 0.60, "LYP6": 0.30},
        target_cash_weight=0.10,
        constraints=RebalanceConstraints(min_trade_eur=50.0, lot_size=1.0, allow_fractional_lots=False),
    )

    assert report.execution_allowed is False
    assert report.feasible is True
    assert report.cash_weight >= 0.10
    assert {item.instrument_id for item in report.trades} == {"VWCE", "LYP6"}
    assert all(item.quantity is not None and item.quantity.is_integer() for item in report.trades)
    assert report.assumptions["lot_policy"] == "integer_lots"
    assert report.assumptions["cost_model"]
    assert report.tax_status == "unavailable"
    assert set(report.alternatives) == {"full", "partial", "deferred", "no_trade"}
    assert report.alternatives["no_trade"].trade_count == 0


def test_rebalance_blocks_restricted_and_defers_small_trades_without_execution() -> None:
    report = build_rebalance_report(
        _config().config,
        _holdings(),
        {"VWCE": 0.405, "LYP6": 0.495},
        target_cash_weight=0.10,
        constraints=RebalanceConstraints(min_trade_eur=30_000.0, restricted_positions=("VWCE",), tax_jurisdiction="AU"),
    )

    vwce = next(item for item in report.trades if item.instrument_id == "VWCE")
    lyp6 = next(item for item in report.trades if item.instrument_id == "LYP6")
    assert vwce.status == "restricted"
    assert lyp6.status == "deferred_below_minimum"
    assert report.tax_status == "informational_only"
    assert report.tax_jurisdiction == "AU"
    assert report.alternatives["deferred"].trade_count == 0


def test_tax_lot_estimate_is_optional_and_jurisdiction_labelled() -> None:
    report = build_rebalance_report(
        _config().config,
        _holdings(),
        {"VWCE": 0.20, "LYP6": 0.70},
        target_cash_weight=0.10,
        constraints=RebalanceConstraints(tax_rate=0.25, tax_jurisdiction="AU"),
        tax_lots=pd.DataFrame([{"instrument_id": "VWCE", "market_value_eur": 40_000.0, "unrealised_gain_eur": 10_000.0}]),
    )

    vwce = next(item for item in report.trades if item.instrument_id == "VWCE")
    assert report.tax_status == "informational_only"
    assert report.tax_jurisdiction == "AU"
    assert vwce.estimated_tax_eur == 750.0
    assert report.execution_allowed is False


def test_rebalance_respects_bond_face_increments_and_persists_no_trade(monkeypatch) -> None:
    # Synthetic face-unit fixture: LYP6 represents a bond lot with EUR 5 face increments.
    holdings = _holdings()
    holdings.loc[holdings["etf_id"] == "LYP6", "asset_type"] = "government_bond"
    holdings.loc[holdings["etf_id"] == "LYP6", "minimum_denomination"] = 5.0
    holdings.loc[holdings["etf_id"] == "LYP6", "denomination_increment"] = 5.0
    targets = {"VWCE": 0.585, "LYP6": 0.315}
    report = build_rebalance_report(
        _config().config,
        holdings,
        targets,
        target_cash_weight=0.10,
        portfolio_value_eur=100_000.0,
    )

    bond = next(item for item in report.trades if item.instrument_id == "LYP6")
    assert bond.quantity == 10.0
    assert bond.trade_value_eur == 10_000.0
    assert "denomination_increment=5" in bond.assumptions
    assert report.cash_weight >= 0.10
    assert report.assumptions["bond_face_policy"] == "minimum_denomination_and_increment"

    below_denomination = build_rebalance_report(
        _config().config,
        holdings,
        {"VWCE": 0.697, "LYP6": 0.203},
        target_cash_weight=0.10,
        portfolio_value_eur=100_000.0,
    )
    small_bond = next(item for item in below_denomination.trades if item.instrument_id == "LYP6")
    assert small_bond.status == "deferred_below_lot"
    assert small_bond.trade_value_eur == 0.0

    missing_terms = build_rebalance_report(
        _config().config,
        holdings.drop(columns=["minimum_denomination", "denomination_increment"]),
        targets,
        target_cash_weight=0.10,
        portfolio_value_eur=100_000.0,
    )
    unavailable_bond = next(item for item in missing_terms.trades if item.instrument_id == "LYP6")
    assert unavailable_bond.status == "deferred_bond_terms_unavailable"
    assert "bond_face_terms_unavailable" in missing_terms.warnings

    binding = PortfolioSnapshotBinding(
        account_id="default",
        portfolio_id="default",
        snapshot_id="synthetic",
        source_revision="synthetic",
        source_checksum="synthetic",
        price_source_revision="synthetic",
        price_source_checksum="synthetic",
        as_of=None,
        holdings_view="direct",
    )
    candidate = SimpleNamespace(
        candidate_id="synthetic-candidate",
        source_checksum="synthetic-source",
        target_weights=tuple(sorted(targets.items())),
        cash_weight=0.10,
        analysis_notional_eur=100_000.0,
    )
    analysis = SimpleNamespace(
        candidate=candidate,
        snapshot_binding=binding,
        allocations=(),
        constraints=(),
        why_not=(),
        service_evidence={"rebalancing": {"status": "available"}},
    )
    snapshot = SimpleNamespace(config=_config().config, holdings=holdings)
    monkeypatch.setattr(portfolio_sandbox, "portfolio_analysis_payload", lambda _analysis: {"payload_checksum": "a" * 64})
    monkeypatch.setattr(portfolio_sandbox, "_candidate_payload", lambda _candidate: {"payload_checksum": "b" * 64})
    monkeypatch.setattr(portfolio_sandbox, "_bound_holdings", lambda _snapshot, _analysis: holdings)

    proposal = validate_portfolio_draft_handoff(portfolio_sandbox.draft_portfolio_proposal(snapshot, analysis))
    no_trade = proposal["evidence"]["no_trade_alternative"]
    assert no_trade["status"] == "available"
    assert no_trade["alternative"]["name"] == "no_trade"
    assert no_trade["alternative"]["trade_count"] == 0
    assert all(item["trade_value_eur"] == 0.0 for item in no_trade["alternative"]["trades"])
    assert no_trade["execution_allowed"] is False
