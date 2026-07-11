from __future__ import annotations

import pandas as pd

from etf_cockpit.app.router import PAGES
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.features.feature_pipeline import compute_features, latest_features
from etf_cockpit.portfolio.allocation import allocation_frame
from etf_cockpit.portfolio.risk_analytics import drawdown_contribution, exposure_limit_report, return_correlation_matrix, underlying_holdings_exposure


def _sample_allocation() -> tuple[object, pd.DataFrame, pd.DataFrame]:
    config = load_config()
    prices = generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-06-26").date())
    holdings = _holdings_from_weights(prices, {"VWCE": 0.40, "SPYK": 0.10})
    allocation = allocation_frame(config, holdings)
    return config, allocation, prices


def test_risk_page_is_registered() -> None:
    assert "/risk" in PAGES
    assert PAGES["/risk"][0] == "Risk Evidence"


def test_audit_page_uses_neutral_audit_label() -> None:
    assert "/chatgpt" in PAGES
    assert PAGES["/chatgpt"][0] == "Audit Notes"


def test_exposure_limit_report_flags_current_concentration_breach() -> None:
    config, allocation, _prices = _sample_allocation()

    report = exposure_limit_report(config, allocation)
    world_core = report[(report["risk_type"] == "etf") & (report["bucket"] == "VWCE")].iloc[0]

    assert world_core["status"] == "breach"
    assert world_core["current_weight"] > world_core["limit"]


def test_correlation_matrix_uses_complete_adjusted_price_returns() -> None:
    config, _allocation, prices = _sample_allocation()

    correlation = return_correlation_matrix(prices, config.universe.enabled_ids, window=120)

    assert list(correlation.index) == config.universe.enabled_ids
    assert list(correlation.columns) == config.universe.enabled_ids
    assert (correlation.values.diagonal() == 1.0).all()


def test_drawdown_contribution_sums_to_one_when_drawdown_exists() -> None:
    _config, allocation, prices = _sample_allocation()
    latest = latest_features(compute_features(prices, benchmark_etf_id="VWCE"), pd.Timestamp("2026-06-26").date())

    contribution = drawdown_contribution(allocation, latest)

    assert not contribution.empty
    assert contribution["risk_share"].between(0, 1).all()
    if contribution["drawdown_contribution"].abs().sum() > 0:
        assert abs(contribution["risk_share"].sum() - 1.0) < 1e-9


def test_underlying_holdings_exposure_uses_portfolio_weights_and_latest_date() -> None:
    allocation = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.40, "target_weight": 0.35},
            {"etf_id": "SPYK", "current_weight": 0.10, "target_weight": 0.12},
        ]
    )
    holdings = pd.DataFrame(
        [
            {"as_of_date": "2026-05-31", "etf_id": "VWCE", "holding_name": "Old A", "weight": 1.0, "sector": "Old"},
            {"as_of_date": "2026-06-30", "etf_id": "VWCE", "holding_name": "Tech A", "weight": 0.60, "sector": "Technology"},
            {"as_of_date": "2026-06-30", "etf_id": "VWCE", "holding_name": "Health A", "weight": 0.40, "sector": "Healthcare"},
            {"as_of_date": "2026-06-30", "etf_id": "SPYK", "holding_name": "Tech B", "weight": 1.0, "sector": "Technology"},
        ]
    )

    exposure = underlying_holdings_exposure(allocation, holdings, "sector")
    values = dict(zip(exposure["sector"], exposure["current_weight"]))

    assert "Old" not in values
    assert abs(values["Technology"] - 0.34) < 1e-12
    assert abs(values["Healthcare"] - 0.16) < 1e-12


def _holdings_from_weights(prices: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    latest = prices.sort_values("date").groupby("etf_id").tail(1).set_index("etf_id")
    rows: list[dict[str, object]] = []
    for etf_id, weight in weights.items():
        price = float(latest.loc[etf_id, "adjusted_close"])
        market_value = 10_000.0 * weight
        rows.append(
            {
                "as_of_date": pd.Timestamp("2026-06-26").date(),
                "etf_id": etf_id,
                "units": market_value / price,
                "market_price": price,
                "market_value_eur": market_value,
                "current_weight": weight,
                "source": "test",
            }
        )
    return pd.DataFrame(rows)
