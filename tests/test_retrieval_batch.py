from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data.contracts import redact_text
from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.retrieval_batch import (
    BatchRetriever,
    ProviderRateLimiter,
    RetrievalCheckpointError,
)
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.core.config import ProviderSection


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


def _retriever(
    root: Path,
    *,
    provider: str = "test-provider",
    batch_size: int = 2,
    retries: int = 0,
    clock: FakeClock | None = None,
    limiter: ProviderRateLimiter | None = None,
) -> BatchRetriever[object]:
    fake_clock = clock or FakeClock()
    return BatchRetriever(
        provider=provider,
        cache_dir=root / "cache",
        checkpoint_path=root / "checkpoint.json",
        batch_size=batch_size,
        max_retries=retries,
        backoff_seconds=1.0,
        clock=fake_clock,
        sleep=fake_clock.sleep,
        limiter=limiter,
    )


def test_batches_and_rate_limiter_respect_configured_limits_with_fake_clock(tmp_path: Path) -> None:
    clock = FakeClock()
    limiter = ProviderRateLimiter(
        minimum_interval_seconds=2.0,
        max_calls_per_window=2,
        window_seconds=5.0,
        clock=clock,
        sleep=clock.sleep,
    )
    retriever = _retriever(tmp_path, batch_size=2, clock=clock, limiter=limiter)
    assert retriever.batches(["A", "B", "C", "D", "E"]) == [["A", "B"], ["C", "D"], ["E"]]

    call_times: list[float] = []
    retriever.retrieve(
        ["A", "B", "C", "D", "E"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 5),
        downloader=lambda symbol: call_times.append(clock()) or {"symbol": symbol},
    )

    assert call_times == [0.0, 2.0, 5.0, 7.0, 10.0]
    assert clock.sleeps == [2.0, 3.0, 2.0, 3.0]


@pytest.mark.parametrize("corruption", ["json", "mismatch"])
def test_cache_hit_skips_downloader_and_corrupt_or_mismatched_cache_refetches(
    tmp_path: Path,
    corruption: str,
) -> None:
    retriever = _retriever(tmp_path)
    calls: list[str] = []

    first = retriever.retrieve(
        ["AAA"],
        start="2026-01-01",
        end="2026-01-31",
        downloader=lambda symbol: calls.append(symbol) or {"symbol": symbol, "value": 1},
    )
    cached = retriever.retrieve(
        ["AAA"],
        start="2026-01-01",
        end="2026-01-31",
        downloader=lambda symbol: pytest.fail(f"cache miss unexpectedly downloaded {symbol}"),
    )
    assert calls == ["AAA"]
    assert cached.symbols["AAA"].value == first.symbols["AAA"].value

    cache_path = next((tmp_path / "cache").glob("*.json"))
    if corruption == "json":
        cache_path.write_text("{broken", encoding="utf-8")
    else:
        entry = json.loads(cache_path.read_text(encoding="utf-8"))
        entry["key"]["symbol"] = "OTHER"
        cache_path.write_text(json.dumps(entry), encoding="utf-8")

    repaired = retriever.retrieve(
        ["AAA"],
        start="2026-01-01",
        end="2026-01-31",
        downloader=lambda symbol: calls.append(symbol) or {"symbol": symbol, "value": 2},
    )
    assert calls == ["AAA", "AAA"]
    assert repaired.symbols["AAA"].status == "done"
    assert repaired.symbols["AAA"].value == {"symbol": "AAA", "value": 2}


def test_resume_fetches_failed_and_pending_only_and_changed_fingerprint_starts_new_run(
    tmp_path: Path,
) -> None:
    retriever = _retriever(tmp_path, retries=0)
    initial_calls: list[str] = []

    def interrupted(symbol: str) -> dict[str, str]:
        initial_calls.append(symbol)
        if symbol == "B":
            raise RuntimeError("temporary provider failure")
        if symbol == "C":
            raise KeyboardInterrupt("simulated crash")
        return {"symbol": symbol}

    with pytest.raises(KeyboardInterrupt, match="simulated crash"):
        retriever.retrieve(
            ["A", "B", "C"],
            start="2026-01-01",
            end="2026-01-31",
            downloader=interrupted,
        )

    resume_calls: list[str] = []
    resumed = retriever.retrieve(
        ["A", "B", "C"],
        start="2026-01-01",
        end="2026-01-31",
        downloader=lambda symbol: resume_calls.append(symbol) or {"symbol": symbol},
    )
    assert initial_calls == ["A", "B", "C"]
    assert resume_calls == ["B", "C"]
    assert {name: item.status for name, item in resumed.symbols.items()} == {
        "A": "done",
        "B": "done",
        "C": "done",
    }

    changed_calls: list[str] = []
    changed = retriever.retrieve(
        ["A", "B", "C"],
        start="2026-01-02",
        end="2026-01-31",
        downloader=lambda symbol: changed_calls.append(symbol) or {"symbol": symbol},
    )
    assert changed.run_id != resumed.run_id
    assert changed_calls == ["A", "B", "C"]


def test_partial_failure_records_redacted_fingerprint_and_retries_only_that_symbol(
    tmp_path: Path,
) -> None:
    retriever = _retriever(tmp_path, retries=2)
    calls: list[str] = []
    secret = "abcdefghijklmnop" + "qrstuvwxyz123456"
    raw_error = f"authorization: Bearer {secret}"

    def download(symbol: str) -> dict[str, str]:
        calls.append(symbol)
        if symbol == "BAD":
            raise RuntimeError(raw_error)
        return {"symbol": symbol}

    result = retriever.retrieve(
        ["GOOD", "BAD"],
        start="2026-01-01",
        end="2026-01-31",
        downloader=download,
    )

    assert calls == ["GOOD", "BAD", "BAD", "BAD"]
    assert result.symbols["GOOD"].status == "done"
    failed = result.symbols["BAD"]
    assert failed.status == "failed"
    assert failed.attempts == 3
    assert failed.error_fingerprint == hashlib.sha256(
        redact_text(f"RuntimeError: {raw_error}").encode("utf-8")
    ).hexdigest()
    assert secret not in (failed.error or "")
    manifest = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert manifest["symbols"]["BAD"]["error_fingerprint"] == failed.error_fingerprint
    assert secret not in json.dumps(manifest)


def test_corrupt_checkpoint_fails_closed_with_readable_error(tmp_path: Path) -> None:
    retriever = _retriever(tmp_path)
    (tmp_path / "checkpoint.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(RetrievalCheckpointError, match="corrupt or unreadable"):
        retriever.retrieve(
            ["AAA"],
            start="2026-01-01",
            end="2026-01-31",
            downloader=lambda symbol: {"symbol": symbol},
        )


def test_yfinance_fetch_prices_uses_retrieval_layer_and_preserves_provider_result_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_download(symbol: str, **kwargs: object) -> pd.DataFrame:
        calls.append(symbol)
        return pd.DataFrame(
            {
                "Open": [10.0],
                "High": [10.5],
                "Low": [9.5],
                "Close": [10.2],
                "Adj Close": [10.1],
                "Volume": [100],
            },
            index=pd.to_datetime(["2026-08-01"]),
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    monkeypatch.setattr("etf_cockpit.data.yfinance_provider.RAW_DIR", tmp_path)
    provider = YFinanceProvider(ProviderSection(symbols_map={"ETF-A": "FAKE.DE"}))

    result = provider.fetch_prices([], date(2026, 8, 1), date(2026, 8, 31))

    assert isinstance(result, ProviderResult)
    assert result.provider_name == "yfinance"
    assert result.dataset_type == "prices"
    assert result.status == "ok"
    assert result.ok
    assert calls == ["FAKE.DE"]
    assert result.data is not None
    assert result.data["etf_id"].tolist() == ["ETF-A"]
    assert result.data["provider_symbol"].tolist() == ["FAKE.DE"]
    assert result.data["date"].tolist() == [date(2026, 8, 1)]


def test_yfinance_default_providers_do_not_share_persistent_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_download(symbol: str, **kwargs: object) -> pd.DataFrame:
        calls.append(symbol)
        return pd.DataFrame(
            {
                "Open": [10.0],
                "High": [10.5],
                "Low": [9.5],
                "Close": [10.2],
                "Adj Close": [10.1],
                "Volume": [100],
            },
            index=pd.to_datetime(["2026-08-01"]),
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    monkeypatch.setattr("etf_cockpit.data.yfinance_provider.RAW_DIR", tmp_path)
    section = ProviderSection(symbols_map={"ETF-A": "FAKE.DE"})

    first = YFinanceProvider(section).fetch_prices([], date(2026, 8, 1), date(2026, 8, 31))
    second = YFinanceProvider(section).fetch_prices([], date(2026, 8, 1), date(2026, 8, 31))

    assert first.ok
    assert second.ok
    assert calls == ["FAKE.DE", "FAKE.DE"]
    assert list(tmp_path.iterdir()) == []


def test_yfinance_explicit_retrieval_root_reuses_cache_and_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_download(symbol: str, **kwargs: object) -> pd.DataFrame:
        calls.append(symbol)
        return pd.DataFrame(
            {
                "Open": [10.0],
                "High": [10.5],
                "Low": [9.5],
                "Close": [10.2],
                "Adj Close": [10.1],
                "Volume": [100],
            },
            index=pd.to_datetime(["2026-08-01"]),
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    root = tmp_path / "retrieval"
    section = ProviderSection(symbols_map={"ETF-A": "FAKE.DE"})

    first = YFinanceProvider(section, retrieval_root=root).fetch_prices(
        [], date(2026, 8, 1), date(2026, 8, 31)
    )
    checkpoint_path = root / "checkpoint.json"
    first_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    second = YFinanceProvider(section, retrieval_root=root).fetch_prices(
        [], date(2026, 8, 1), date(2026, 8, 31)
    )
    second_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    assert first.ok
    assert second.ok
    assert calls == ["FAKE.DE"]
    assert list((root / "cache").glob("*.json"))
    assert first_checkpoint["run_id"] == second_checkpoint["run_id"]
    assert second_checkpoint["symbols"]["FAKE.DE"]["status"] == "done"
