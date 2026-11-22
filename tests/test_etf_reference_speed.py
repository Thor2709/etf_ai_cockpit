from __future__ import annotations

import random
import sys
import threading
import time
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.yfinance_provider import YFinanceProvider

SYMBOLS = {f"E{index}": f"E{index}.DE" for index in range(8)}


def _summary(symbol: str) -> dict[str, object]:
    return {
        "quoteType": {"quoteType": "ETF", "longName": f"Fund {symbol}", "shortName": "short"},
        "summaryDetail": {"currency": "EUR", "totalAssets": 1_000, "yield": 0.01},
        "defaultKeyStatistics": {"fundFamily": None, "category": "Global"},
        "price": {"currency": "EUR", "quoteType": "ETF", "longName": f"Fund {symbol}"},
        "fundProfile": {"family": "Issuer", "feesExpensesInvestment": {"annualReportExpenseRatio": 0.002}},
    }


class _Ticker:
    log: list[tuple[str, str]] = []
    lock = threading.Lock()

    def __init__(self, symbol: str, payload: dict[str, object] | None = None) -> None:
        self.symbol = symbol
        self.payload = _summary(symbol) if payload is None else payload
        self._data = SimpleNamespace(get_raw_json=self._get_raw_json)

    def _get_raw_json(self, url: str, params: dict[str, str]) -> dict[str, object]:
        time.sleep(random.uniform(0, 0.02))  # completion order differs from request order
        with self.lock:
            self.log.append(("quoteSummary", params["modules"]))
        if not self.payload:
            raise ValueError("404 Not Found")
        return {"quoteSummary": {"result": [self.payload]}}

    @property
    def fast_info(self) -> SimpleNamespace:
        with self.lock:
            self.log.append(("fast_info", self.symbol))
        return SimpleNamespace(currency="USD", quote_type="EQUITY")

    @property
    def funds_data(self) -> SimpleNamespace:
        with self.lock:
            self.log.append(("funds_data", self.symbol))
        holdings = pd.DataFrame({"Name": ["Apple"], "Holding Percent": [0.05]}, index=pd.Index(["AAPL"], name="Symbol"))
        return SimpleNamespace(top_holdings=holdings)


def _install(monkeypatch, factory=_Ticker) -> list[tuple[str, str]]:
    _Ticker.log = []
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=factory))
    return _Ticker.log


def test_metadata_is_one_quote_summary_request_per_symbol_in_config_order(monkeypatch) -> None:
    log = _install(monkeypatch)

    result = YFinanceProvider(ProviderSection(symbols_map=SYMBOLS)).fetch_etf_metadata([])

    assert result.ok and result.data is not None
    assert log == [("quoteSummary", "quoteType,summaryDetail,defaultKeyStatistics,price,fundProfile")] * len(SYMBOLS)
    assert result.data["etf_id"].tolist() == list(SYMBOLS)
    row = result.data.iloc[0].to_dict()
    assert {key: row[key] for key in ("name", "currency", "quote_type", "provider", "ter", "ter_source", "total_assets", "yield", "category")} == {
        "name": "Fund E0.DE", "currency": "EUR", "quote_type": "ETF", "provider": "Issuer", "ter": 0.002,
        "ter_source": "provider_own_column", "total_assets": 1_000, "yield": 0.01, "category": "Global",
    }


def test_fast_info_is_read_only_when_quote_summary_has_no_answer(monkeypatch) -> None:
    log = _install(monkeypatch, lambda symbol: _Ticker(symbol, payload={}))

    result = YFinanceProvider(ProviderSection(symbols_map={"E0": "E0.DE"}), instrument_metadata={"E0": {"name": "Configured"}}).fetch_etf_metadata([])

    assert result.ok and result.data is not None
    assert log == [("quoteSummary", "quoteType,summaryDetail,defaultKeyStatistics,price,fundProfile"), ("fast_info", "E0.DE")]
    row = result.data.iloc[0]
    assert (row["name"], row["currency"], row["quote_type"], row["provider"], row["ter_source"]) == ("Configured", "USD", "EQUITY", "Yahoo Finance", "unavailable")


def test_holdings_skip_configured_stocks_and_keep_order(monkeypatch) -> None:
    log = _install(monkeypatch)
    metadata = {etf_id: {"instrument_type": "stock" if etf_id == "E1" else "etf"} for etf_id in SYMBOLS}

    result = YFinanceProvider(ProviderSection(symbols_map=SYMBOLS), instrument_metadata=metadata).fetch_etf_holdings([])

    assert result.ok and result.data is not None
    assert sorted(symbol for kind, symbol in log if kind == "funds_data") == sorted(v for k, v in SYMBOLS.items() if k != "E1")
    assert result.data["etf_id"].tolist() == [etf_id for etf_id in SYMBOLS if etf_id != "E1"]


def test_failed_symbol_keeps_error_text_and_rejects_the_partial_set(monkeypatch) -> None:
    def factory(symbol: str) -> _Ticker:
        if symbol == "E3.DE":
            raise ValueError("404 Not Found")
        return _Ticker(symbol)

    _install(monkeypatch, factory)
    provider = YFinanceProvider(ProviderSection(symbols_map=SYMBOLS))

    metadata = provider.fetch_etf_metadata([])
    holdings = provider.fetch_etf_holdings([])

    for result, dataset in ((metadata, "metadata"), (holdings, "holdings")):
        assert result.status == "error"
        assert result.message.startswith(f"Partial {dataset} refresh rejected")
        assert result.message.endswith("E3/E3.DE: [not_found] ValueError: 404 Not Found")
        assert result.data is not None and result.data["etf_id"].tolist() == [etf_id for etf_id in SYMBOLS if etf_id != "E3"]
