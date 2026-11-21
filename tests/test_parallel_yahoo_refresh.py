"""Parallel downloads give the same retrieval result as serial ones; Yahoo calls share one HTTP session."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data import yfinance_provider
from etf_cockpit.data.retrieval_batch import BatchRetriever


def _run(root: Path, workers: int) -> tuple[dict[str, tuple[str, object]], int, list[str]]:
    active, peak, calls, lock = [0], [0], [], threading.Lock()

    def download(symbol: str) -> object:
        with lock:
            calls.append(symbol)
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        if symbol == "BAD":
            raise RuntimeError("boom")
        return None if symbol == "EMPTY" else {"symbol": symbol}

    retriever = BatchRetriever(provider="test", cache_dir=root / "cache", checkpoint_path=root / "checkpoint.json",
                               max_retries=0, workers=workers, sleep=lambda _seconds: None, unavailable_retry_passes=1)
    symbols = [f"S{i}" for i in range(12)] + ["EMPTY", "BAD"]
    result = retriever.retrieve(symbols, start="2026-11-06", end="2026-11-21", downloader=download)
    again = retriever.retrieve(symbols, start="2026-11-06", end="2026-11-21", downloader=download)
    assert {s: r.status for s, r in again.symbols.items()} == {s: r.status for s, r in result.symbols.items()}
    return {s: (r.status, r.value) for s, r in result.symbols.items()}, peak[0], calls


def test_parallel_workers_give_the_same_result_and_checkpoint_as_one_worker(tmp_path: Path) -> None:
    serial, serial_peak, serial_calls = _run(tmp_path / "serial", workers=1)
    parallel, parallel_peak, parallel_calls = _run(tmp_path / "parallel", workers=4)
    assert list(parallel) == list(serial) and parallel == serial
    assert serial_peak == 1 and parallel_peak > 1
    assert sorted(parallel_calls) == sorted(serial_calls)  # same downloads, including the resume of the failed symbol


def test_yahoo_downloads_share_one_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[object] = []

    def download(symbol: str, **kwargs: object) -> pd.DataFrame:
        sessions.append(kwargs.get("session"))
        return pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Adj Close": [1.0], "Volume": [1.0],
                             "Dividends": [0.0], "Stock Splits": [0.0]}, index=pd.to_datetime(["2026-11-19"]))

    shared = object()
    monkeypatch.setattr(yfinance_provider, "_import_yfinance", lambda: SimpleNamespace(download=download))
    monkeypatch.setattr(yfinance_provider, "_new_session", lambda: shared)
    provider = yfinance_provider.YFinanceProvider(ProviderSection(symbols_map={"A": "A.DE", "B": "B.DE", "C": "C.PA"}),
                                                  retrieval_root=tmp_path)
    assert provider.fetch_prices([], date(2026, 11, 6), date(2026, 11, 21)).ok
    assert len(sessions) == 3 and all(session is shared for session in sessions)
