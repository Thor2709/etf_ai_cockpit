"""Deterministic fault-injection checks for ISSUE-0143."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from etf_cockpit import services
from etf_cockpit.core.config import load_config


def test_provider_failure_preserves_last_valid_price_state(monkeypatch, tmp_path: Path) -> None:
    last_valid = tmp_path / "prices.csv"
    original = b"etf_id,date,adjusted_close\nFIXTURE,2026-01-01,100.0\n"
    last_valid.write_bytes(original)
    committed: list[object] = []

    class FailedProvider:
        def fetch_prices(self, *_args):
            return SimpleNamespace(ok=False, data=None, message="offline provider failure")

    monkeypatch.setattr(services.YFinanceProvider, "from_config", staticmethod(lambda _config: FailedProvider()))

    def record_commit(result):
        committed.append(result)
        last_valid.write_bytes(b"invalid replacement")

    monkeypatch.setattr(services, "commit_price_import", record_commit)
    service = services.DataService(load_config())

    message = service.refresh_yfinance_data(include_reference_data=False)

    assert message == "offline provider failure"
    assert service.last_operation_succeeded is False
    assert committed == []
    assert last_valid.read_bytes() == original
