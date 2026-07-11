from __future__ import annotations

import sys
from datetime import date
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.yfinance_provider import YFinanceProvider, looks_like_yahoo_symbol, validate_yahoo_symbols, yfinance_symbol_map_from_config
from etf_cockpit.core.config import load_config


def test_yfinance_provider_normalises_adjusted_price_schema(monkeypatch) -> None:
    calls: list[str] = []

    def fake_download(symbol: str, **kwargs):
        calls.append(symbol)
        return pd.DataFrame(
            {
                "Open": [10.0, 10.5],
                "High": [10.8, 10.9],
                "Low": [9.8, 10.2],
                "Close": [10.4, 10.7],
                "Adj Close": [10.3, 10.6],
                "Volume": [1000, 1200],
                "Dividends": [0.0, 0.1],
                "Stock Splits": [0.0, 0.0],
            },
            index=pd.to_datetime(["2026-06-25", "2026-06-26"]),
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    section = ProviderSection(symbols_map={"SPYK": "SPYK.F"})

    result = YFinanceProvider(section).fetch_prices([], date(2026, 6, 1), date(2026, 6, 30))

    assert result.ok
    assert calls == ["SPYK.F"]
    assert result.data is not None
    assert set(["date", "etf_id", "open", "high", "low", "close", "adjusted_close", "volume", "currency"]).issubset(result.data.columns)
    assert result.data["etf_id"].unique().tolist() == ["SPYK"]
    assert result.data["provider_symbol"].unique().tolist() == ["SPYK.F"]
    assert result.data["currency"].unique().tolist() == ["EUR"]
    assert result.data["adjusted_close"].iloc[-1] == 10.6
    assert result.data["dividends"].iloc[-1] == 0.1


def test_yfinance_symbol_map_uses_configured_provider_symbols() -> None:
    config = load_config()
    mapping = yfinance_symbol_map_from_config(config)

    assert mapping["VWCE"] == "VWCE.DE"
    assert mapping["EXX1"] == "EXX1.DE"


def test_yfinance_symbol_shape_accepts_sparebanken_oslo_symbols_and_rejects_paths() -> None:
    for symbol in ("AURG.OL", "JAEREN.OL", "NONG.OL", "BRK-B", "MSFT"):
        assert looks_like_yahoo_symbol(symbol)

    for symbol in ("BAD SYMBOL.OL", "../secret", "", "AURG/OL"):
        assert not looks_like_yahoo_symbol(symbol)


def test_yfinance_symbol_validation_is_deterministic_and_non_network() -> None:
    result = validate_yahoo_symbols({"AURG": "AURG.OL", "BAD": "../bad"})
    assert result["AURG"].status == "shape_valid"
    assert result["BAD"].status == "invalid_symbol"


def test_yfinance_targeted_fetch_only_requests_selected_instruments(monkeypatch) -> None:
    calls: list[str] = []

    def fake_download(symbol: str, **kwargs):
        calls.append(symbol)
        return pd.DataFrame(
            {"Open": [10.0], "High": [10.5], "Low": [9.5], "Close": [10.2], "Adj Close": [10.2]},
            index=pd.to_datetime(["2026-06-26"]),
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    provider = YFinanceProvider(ProviderSection(symbols_map={"A": "A.OL", "B": "B.OL"}))

    result = provider.fetch_prices(["A"], date(2026, 6, 1), date(2026, 6, 30))

    assert result.ok
    assert calls == ["A.OL"]
    assert result.data is not None
    assert result.data["etf_id"].unique().tolist() == ["A"]


def test_yfinance_partial_price_refresh_is_not_successful(monkeypatch) -> None:
    def fake_download(symbol: str, **kwargs):
        if symbol == "B.OL":
            return pd.DataFrame()
        return pd.DataFrame(
            {"Open": [10.0], "High": [10.5], "Low": [9.5], "Close": [10.2], "Adj Close": [10.2]},
            index=pd.to_datetime(["2026-06-26"]),
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    provider = YFinanceProvider(ProviderSection(symbols_map={"A": "A.OL", "B": "B.OL"}))

    result = provider.fetch_prices([], date(2026, 6, 1), date(2026, 6, 30))

    assert result.status == "error"
    assert not result.ok
    assert result.data is not None
    assert "Partial refresh rejected" in result.message


def test_yfinance_provider_extracts_metadata_from_funds_data(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *args, **kwargs: pd.DataFrame(), Ticker=_fake_ticker))
    section = ProviderSection(symbols_map={"VWCE": "VWCE.DE"})
    provider = YFinanceProvider(
        section,
        instrument_metadata={
            "VWCE": {
                "isin": "IE00BK5BQT80",
                "ticker": "VWCE",
                "name": "Configured name",
                "currency": "EUR",
                "configured_ter": 0.002,
            }
        },
    )

    result = provider.fetch_etf_metadata([])

    assert result.ok
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["etf_id"] == "VWCE"
    assert row["provider_symbol"] == "VWCE.DE"
    assert row["isin"] == "IE00BK5BQT80"
    assert row["currency"] == "EUR"
    assert row["ter"] == 0.002
    assert row["provider"] == "BlackRock"


def test_yfinance_provider_extracts_top_holdings(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *args, **kwargs: pd.DataFrame(), Ticker=_fake_ticker))
    section = ProviderSection(symbols_map={"VWCE": "VWCE.DE"})

    result = YFinanceProvider(section).fetch_etf_holdings([])

    assert result.ok
    assert result.data is not None
    assert result.data["etf_id"].unique().tolist() == ["VWCE"]
    assert result.data["holding_id"].tolist() == ["NVDA", "AAPL"]
    assert result.data["weight"].round(4).tolist() == [0.0542, 0.0509]


def test_yfinance_provider_fetches_fx_pairs(monkeypatch) -> None:
    def fake_download(symbol: str, **kwargs):
        assert symbol == "USDEUR=X"
        return pd.DataFrame(
            {
                "Open": [0.9],
                "High": [0.91],
                "Low": [0.89],
                "Close": [0.905],
                "Adj Close": [0.905],
                "Volume": [0],
            },
            index=pd.to_datetime(["2026-06-26"]),
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))

    result = YFinanceProvider().fetch_fx(["USD/EUR"], date(2026, 6, 1), date(2026, 6, 30))

    assert result.ok
    assert result.data is not None
    assert result.data[["base_currency", "quote_currency", "pair", "rate"]].iloc[0].to_dict() == {
        "base_currency": "USD",
        "quote_currency": "EUR",
        "pair": "USD/EUR",
        "rate": 0.905,
    }


class _FakeFundsData:
    fund_overview = {"family": "BlackRock", "legalType": "Exchange Traded Fund"}
    fund_operations = pd.DataFrame(
        {"VWCE.DE": [0.002, 0.11], "Category Average": [None, None]},
        index=pd.Index(["Annual Report Expense Ratio", "Annual Holdings Turnover"], name="Attributes"),
    )
    top_holdings = pd.DataFrame(
        {"Name": ["NVIDIA Corp", "Apple Inc"], "Holding Percent": [0.054153398, 0.050900698]},
        index=pd.Index(["NVDA", "AAPL"], name="Symbol"),
    )


class _FakeTicker:
    info = {
        "currency": "EUR",
        "quoteType": "ETF",
        "longName": "Vanguard FTSE All-World UCITS ETF USD Accumulating",
        "fundFamily": "BlackRock",
        "totalAssets": 123456,
    }
    fast_info = {"currency": "EUR", "quoteType": "ETF"}
    funds_data = _FakeFundsData()


def _fake_ticker(symbol: str) -> _FakeTicker:
    assert symbol == "VWCE.DE"
    return _FakeTicker()
