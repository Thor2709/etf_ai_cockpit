"""Weekly stock-fundamentals job: no crash on an older store, fewer Yahoo requests, parallel Yahoo fetch applied in
target order, one store concat, one price index in the metrics step, one SEC ticker-file download per run."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pandas as pd

from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_sources as src

UTC = timezone.utc
CONFIG = store.load_stock_config()
NOW = datetime(2026, 3, 2, tzinfo=UTC)
KNOWN = "2026-03-01T00:00:00+00:00"


def _row(year: int, revenue: float) -> dict:
    return {"period_end": f"{year}-12-31", "period_type": "FY", "fiscal_year": year, "currency": "EUR", "source": "yfinance",
            "source_ref": "t", "known_at": KNOWN, "revenue": revenue, "ebit": revenue / 10}


def _ok(rows: list[dict]) -> src.FetchResult:
    return src.FetchResult("yfinance", rows=rows, snapshot={"known_at": KNOWN, "quote_currency": "EUR", "financial_currency": "EUR"})


def _refresh(root, names, fetch, **kwargs) -> store.RefreshReport:
    (root / "data" / "clean").mkdir(parents=True, exist_ok=True)
    return store.refresh_stock_fundamentals(
        [store.StockTarget(name, name, name) for name in names], root=root, now=NOW, config=CONFIG,
        environ=kwargs.pop("environ", {}), yfinance_fetch=fetch, fx_fetch=lambda _base, _quote: [], **kwargs,
    )


def test_metrics_step_reads_an_older_store_without_the_line_item_columns(tmp_path) -> None:
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame([{"instrument_id": "AAA", **_row(2025, 100.0)}]).to_parquet(clean / "stock_fundamentals.parquet")
    assert "sga_currency" not in pd.read_parquet(clean / "stock_fundamentals.parquet")  # read back as null
    assert store.produce_constituent_metrics(["AAA"], root=tmp_path, config=CONFIG) is None
    assert len(pd.read_parquet(clean / "constituent_metrics.parquet")) == 1


def test_yahoo_fetch_uses_three_requests_for_profile_statements_and_analyst_trend(monkeypatch) -> None:
    calls: list[str] = []
    summary = {"quoteSummary": {"result": [{
        "financialData": {"financialCurrency": "EUR", "maxAge": 1},
        "quoteType": {"quoteType": "EQUITY", "longName": "Alpha\xa0SE"},
        "assetProfile": {"sector": "Industrials", "industry": "Machinery", "country": "Germany"},
        "summaryDetail": {"currency": "EUR", "marketCap": 1000},
        "defaultKeyStatistics": {"sharesOutstanding": 10},
        "earningsTrend": {"trend": [{"period": "0y", "epsTrend": {"current": {"raw": 2.0}, "90daysAgo": {"raw": 1.5}},
                                     "epsRevisions": {"upLast30days": {"raw": 3}, "downLast30days": {"raw": 1}}}]},
    }]}}
    quote = {"quoteResponse": {"result": [{"symbol": "ALP.DE", "marketCap": 1100}]}}

    def series(name: str, value: float) -> dict:
        return {"meta": {"type": [name]}, "timestamp": [1735603200], name: [{"asOfDate": "2024-12-31", "reportedValue": {"raw": value}}]}

    timeseries = {"timeseries": {"result": [series("annualTotalRevenue", 500.0), series("quarterlyTotalAssets", 900.0)]}}

    def fake_json(url: str, params: dict) -> dict:
        calls.append(url)
        return summary if "quoteSummary" in url else quote if "/v7/" in url else timeseries

    monkeypatch.setattr(src, "_yahoo_json", fake_json)
    result = src.fetch_yfinance("ALP.DE", CONFIG, now=NOW)
    assert len(calls) == 3
    assert result.status == "ok"
    assert {(row["period_type"], row.get("revenue"), row.get("total_assets")) for row in result.rows} == {("FY", 500.0, None), ("Q", None, 900.0)}
    snap = result.snapshot
    assert (snap["long_name"], snap["market_cap_provider"], snap["shares_outstanding"], snap["country"]) == ("Alpha SE", 1100.0, 10.0, "Germany")
    assert (snap["eps_current"], snap["eps_90d_ago"], snap["revisions_up_30d"], snap["revisions_down_30d"]) == (2.0, 1.5, 3.0, 1.0)


def test_yahoo_fetch_runs_in_parallel_and_is_applied_in_target_order(tmp_path) -> None:
    names = [f"S{index}" for index in range(8)]
    lock, running, peak = threading.Lock(), [0], [0]

    def fetch(symbol: str, _cfg: dict, now: datetime) -> src.FetchResult:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05 * (8 - names.index(symbol)))  # the first target finishes last
        with lock:
            running[0] -= 1
        return _ok([_row(2025, 100.0 + names.index(symbol))])

    report = _refresh(tmp_path, names, fetch)
    assert 1 < peak[0] <= 4
    assert list(report.per_instrument) == names
    assert list(store.read_periods(tmp_path)["instrument_id"]) == names


def test_refresh_copies_the_stored_rows_once(tmp_path, monkeypatch) -> None:
    _refresh(tmp_path, ["OLD"], lambda *_a, **_k: _ok([_row(year, 1.0) for year in range(1980, 2030)]))
    stored = len(store.read_periods(tmp_path))
    copies: list[int] = []
    concat = store._concat
    monkeypatch.setattr(store, "_concat", lambda frames, columns: copies.append(max(map(len, frames))) or concat(frames, columns))
    _refresh(tmp_path, ["A", "B", "C"], lambda *_a, **_k: _ok([_row(2025, 5.0)]))
    assert sum(size >= stored for size in copies) == 1


def test_metrics_step_indexes_prices_once(tmp_path, monkeypatch) -> None:
    prices = tmp_path / "data" / "validated" / "prices"
    prices.mkdir(parents=True)
    pd.DataFrame({"etf_id": ["A", "B"], "date": ["2026-02-27", "2026-02-27"], "close": [10.0, 20.0],
                  "available_at": ["2026-02-28T00:00:00+00:00"] * 2}).to_parquet(prices / "prices_daily.parquet")
    seen: list[set[str]] = []
    price_frame = su._price_frame
    monkeypatch.setattr(su, "_price_frame", lambda frame, instrument: seen.append(set(frame["etf_id"])) or price_frame(frame, instrument))
    _refresh(tmp_path, ["A", "B"], lambda *_a, **_k: _ok([_row(2025, 100.0)]))
    assert seen == [{"A"}, {"B"}]


def test_the_sec_ticker_file_is_downloaded_once_per_run(tmp_path, monkeypatch) -> None:
    downloads: list[str] = []

    def http(url: str, _agent: str) -> dict:
        downloads.append(url)
        return {"0": {"ticker": "A", "cik_str": 1}, "1": {"ticker": "B", "cik_str": 2}}

    monkeypatch.setattr(src, "http_get_json", http)
    _refresh(tmp_path, ["A", "B", "C"], lambda *_a, **_k: _ok([_row(2025, 1.0)]),
             environ={"ETF_COCKPIT_SEC_EDGAR_USER_AGENT": "test agent"}, edgar_fetch=lambda *_a, **_k: src.FetchResult("sec_edgar", status="no_statements"),
             esef_fetch=lambda *_a, **_k: src.FetchResult("esef", status="unavailable"))
    assert downloads == [src.SEC_TICKERS_URL]
