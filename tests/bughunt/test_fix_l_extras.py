from datetime import date
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.data import yfinance_provider
from etf_cockpit.data.fx_data import validate_fx_rates
from etf_cockpit.data.sample_data import generate_sample_holdings, generate_sample_prices
from etf_cockpit.data.trade_candidate_analysis import analyse_candidate_prices
from etf_cockpit.data.validation import validate_holdings, validate_prices


def test_yahoo_unknown_quote_currency_stays_unavailable(monkeypatch):
    frame = pd.DataFrame(
        {"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.0], "Adj Close": [10.0], "Volume": [1.0]},
        index=pd.to_datetime(["2026-10-02"]),
    )
    monkeypatch.setattr(yfinance_provider, "_import_yfinance", lambda: SimpleNamespace(download=lambda *args, **kwargs: frame))
    provider = yfinance_provider.YFinanceProvider(default_currency="EUR")
    output = provider._download_one(symbol="UNKNOWN", etf_id="UNKNOWN", start_date=date(2026, 10, 1), end_date=date(2026, 10, 5))
    assert output.iloc[0]["currency"] is None


def test_candidate_native_amounts_keep_currency_without_eur_conversion():
    candidates = pd.DataFrame([{"instrument_id": "US", "currency": "USD", "shares": 10, "yahoo_symbol": "AAPL"}])
    prices = pd.DataFrame(
        {
            "etf_id": ["US"] * 3,
            "currency": ["USD"] * 3,
            "date": pd.date_range("2026-10-01", periods=3),
            "close": [100.0] * 3,
            "adjusted_close": [100.0] * 3,
            "volume": [20.0] * 3,
        }
    )
    result = analyse_candidate_prices(candidates, prices).iloc[0]
    assert result["trade_value_native"] == 1000.0
    assert result["median_turnover_60d_native"] == 2000.0
    assert result["currency"] == "USD"

    conflicting_prices = prices.copy()
    conflicting_prices.loc[conflicting_prices.index[0], "currency"] = "EUR"
    conflicting = analyse_candidate_prices(candidates, conflicting_prices).iloc[0]
    assert conflicting["currency"] == ""
    assert pd.isna(conflicting["trade_value_eur"])


def test_prices_holdings_and_fx_reject_nonfinite_required_values():
    config = load_config()
    as_of = date(2026, 10, 5)
    prices = generate_sample_prices(config, periods=300, end_date=as_of)
    prices.loc[prices.index[0], "volume"] = float("inf")
    price_report = validate_prices(prices, as_of_date=as_of)
    assert "invalid_price_values" in {issue.code for issue in price_report.issues}

    holdings = generate_sample_holdings(config, prices)
    holdings.loc[holdings.index[0], "units"] = float("inf")
    holding_report = validate_holdings(config, holdings, as_of_date=as_of)
    assert "invalid_units" in {issue.code for issue in holding_report.issues}

    rates = pd.DataFrame(
        {"as_of_date": [as_of], "pair": ["EUR/USD"], "rate": [float("inf")]}
    )
    assert not validate_fx_rates(rates, today=as_of).ok
