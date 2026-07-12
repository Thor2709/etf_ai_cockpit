from __future__ import annotations

from etf_cockpit.data.universe_store import UniverseRecord, support_decision, validate_universe
from etf_cockpit.core.config import ETFConfig, UniverseConfig, AppConfig, CostConfig, ModelSettings, PortfolioTargets, RiskLimits, UISettings
from etf_cockpit.data.yfinance_provider import yfinance_symbol_map_from_config
from etf_cockpit.signals.simple_scores import build_candidate_simple_scores
import pandas as pd


def test_unsupported_assets_never_become_score_eligible() -> None:
    for asset_type in ("futures", "options", "crypto", "forex"):
        decision = support_decision(asset_type, "daily", False, False)
        assert decision.supported is False
        assert decision.score_eligible is False


def test_research_only_assets_are_explicitly_marked_without_silent_scoring() -> None:
    for asset_type in ("futures", "options"):
        decision = support_decision(asset_type, "daily", False, False)
        assert decision.risk_state == "research_only"
        assert "research" in decision.reason.lower()


def test_research_only_records_can_persist_but_unsupported_records_cannot() -> None:
    future = UniverseRecord("FUT", "Future", isin="needs_verification", isin_status="needs_verification", ticker="FUT", asset_type="futures")
    crypto = UniverseRecord("COIN", "Coin", isin="needs_verification", isin_status="needs_verification", ticker="COIN", asset_type="crypto")
    future_report = validate_universe([future])
    assert future_report.valid is True
    assert any("research_only" in warning for warning in future_report.warnings)
    assert validate_universe([crypto]).valid is False


def test_configured_enabled_and_yfinance_boundaries_exclude_guarded_records() -> None:
    rows = [
        ETFConfig(id="DAILY", name="Daily", ticker="DAILY", role="core"),
        ETFConfig(id="LEV", name="Leveraged", ticker="LEV", role="watchlist", leveraged=True),
        ETFConfig(id="FUT", name="Future", ticker="FUT", role="watchlist", instrument_type="futures"),
        ETFConfig(id="INTRA", name="Intraday", ticker="INTRA", role="watchlist", data_policy="intraday"),
    ]
    universe = UniverseConfig(etfs=rows)
    assert universe.configured_enabled_ids == ["DAILY", "LEV", "FUT", "INTRA"]
    assert universe.enabled_ids == ["DAILY"]
    config = AppConfig(
        universe=universe,
        targets=PortfolioTargets(),
        risks=RiskLimits(),
        costs=CostConfig(),
        models=ModelSettings(),
        ui=UISettings(),
        chatgpt_schema={},
    )
    assert yfinance_symbol_map_from_config(config) == {"DAILY": "DAILY"}


def test_candidate_scoring_boundary_skips_research_and_high_risk_rows() -> None:
    report = pd.DataFrame(
        [
            {"instrument_id": "FUT", "name": "Future", "yahoo_symbol": "FUT", "instrument_type": "futures", "data_policy": "daily", "latest_date": "2026-07-10", "latest_price": 1.0},
            {"instrument_id": "LEV", "name": "Leveraged", "yahoo_symbol": "LEV", "instrument_type": "etf", "data_policy": "daily", "leveraged": True, "latest_date": "2026-07-10", "latest_price": 1.0},
            {"instrument_id": "OK", "name": "Stock", "yahoo_symbol": "OK", "instrument_type": "stock", "data_policy": "daily", "latest_date": "2026-07-10", "latest_price": 1.0},
        ]
    )
    scores = build_candidate_simple_scores(report, pd.DataFrame())
    assert {score.display_id for score in scores} == {"OK"}
