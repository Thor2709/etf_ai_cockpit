from __future__ import annotations

import pandas as pd

from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.app.state import AppState
from etf_cockpit.core.config import load_config
from etf_cockpit.features.etf_economics import calculate_etf_liquidity
from etf_cockpit.services import build_snapshot


def _prices(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-04-01", periods=rows, freq="B")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "etf_id": "VWCE",
            "open": close - 0.25,
            "high": close + 0.50,
            "low": close - 0.50,
            "close": close,
            "adjusted_close": close,
            "volume": 10_000.0,
            "currency": "EUR",
        }
    )


def test_etf_capacity_is_order_size_and_horizon_specific_and_cost_stress_widens() -> None:
    config = load_config()
    one_day = calculate_etf_liquidity(config, _prices(), "VWCE", order_value_eur=10_000, horizon_days=1)
    five_day = calculate_etf_liquidity(config, _prices(), "VWCE", order_value_eur=50_000, horizon_days=5, stress_multiplier=1.5)

    assert one_day.status == "available"
    assert one_day.exchange_capacity_eur == one_day.rolling_turnover_eur_20d * config.costs.cost_model.max_participation_rate
    assert one_day.capacity_status == "within_configured_participation"
    assert five_day.horizon_days == 5
    assert five_day.order_to_daily_turnover > one_day.order_to_daily_turnover
    assert five_day.exchange_capacity_eur > one_day.exchange_capacity_eur
    assert five_day.stressed_cost_bps >= five_day.estimated_cost_bps
    assert five_day.execution_allowed is False


def test_etf_quote_panel_flags_stale_off_hours_and_calculates_premium_discount() -> None:
    config = load_config()
    prices = _prices()
    latest = prices["date"].max()
    report = calculate_etf_liquidity(
        config,
        prices,
        "VWCE",
        quote_evidence=pd.DataFrame(
            [
                {
                    "instrument_id": "VWCE",
                    "quote_timestamp": latest - pd.Timedelta(days=2),
                    "session": "after_hours",
                    "bid": 100.0,
                    "ask": 102.0,
                    "nav": 100.0,
                    "underlying_adv_eur": 2_000_000.0,
                    "primary_market_capacity_eur": 5_000_000.0,
                    "source_id": "import:quote-test",
                }
            ]
        ),
        as_of=latest,
    )

    assert report.quote_status == "available"
    assert report.stale_quote is True
    assert report.off_hours_quote is True
    assert report.quote_freshness == "stale"
    assert report.premium_discount_bps == 100.0
    assert report.underlying_liquidity_eur == 2_000_000.0
    assert report.primary_market_capacity_eur == 5_000_000.0
    assert report.primary_market_status == "available"
    assert report.source_id == "import:quote-test"


def test_missing_quote_and_primary_market_evidence_remain_explicit() -> None:
    report = calculate_etf_liquidity(load_config(), _prices(), "VWCE")

    assert report.quote_status == "unavailable"
    assert report.bid_eur is None
    assert report.ask_eur is None
    assert report.nav_eur is None
    assert {"bid_ask", "nav", "quote_timestamp"} <= set(report.missing_evidence)
    assert report.spread_source == "high_low_proxy"
    assert report.primary_market_capacity_eur is None
    assert report.primary_market_status == "unavailable_not_exchange_volume"


def test_instrument_detail_exposes_etf_liquidity_and_order_preview() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    control = instrument_detail_page(None, state)

    def text_values(node: object) -> list[str]:
        values = []
        value = getattr(node, "value", None)
        if value is not None:
            values.append(str(value))
        for child in getattr(node, "controls", []) or []:
            values.extend(text_values(child))
        content = getattr(node, "content", None)
        if content is not None:
            values.extend(text_values(content))
        return values

    rendered = "\n".join(text_values(control))
    assert "ETF Liquidity" in rendered
    assert "ETF order-preview capacity meter" in rendered
    assert "execution_allowed=false" in rendered
