from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data.price_quarantine import quarantine_invalid_ohlc
from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.provenance import metadata_from_frame, sha256_dataframe
from etf_cockpit.data.validation import validate_prices


def _prices():
    return pd.DataFrame({
        "date": pd.bdate_range("2025-01-01", periods=260).date,
        "etf_id": "A", "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "adjusted_close": 8.5, "volume": 100, "currency": "EUR",
    })


def _cli(monkeypatch, tmp_path, result):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("work_f_analysis", scripts / "run_yfinance_analysis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", ["run_yfinance_analysis.py", "--skip-models", "--skip-reference"])
    monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(module.YFinanceProvider, "from_config", lambda _: SimpleNamespace(fetch_prices=lambda *_: result))
    return module


def test_quarantine_preserves_values_reason_and_clean_checksum():
    frame = _prices()
    frame.loc[0, "close"] = 12.0
    metadata = metadata_from_frame(frame, source_name="yfinance", source_type="prices",
        as_of_date=max(frame.date), currency="EUR", provider_or_manual_source="Yahoo")
    result = ProviderResult("yfinance", "prices", "ok", "download", frame, metadata)
    clean, quarantined = quarantine_invalid_ohlc(result)
    pd.testing.assert_frame_equal(clean.data, frame.iloc[1:].reset_index(drop=True))
    pd.testing.assert_frame_equal(quarantined.drop(columns="quarantine_reason"), frame.iloc[:1])
    assert quarantined.quarantine_reason.tolist() == ["invalid_ohlc"]
    assert clean.metadata.checksum == sha256_dataframe(clean.data)
    assert result.metadata.checksum == sha256_dataframe(frame)
    assert "invalid_ohlc" not in {i.code for i in validate_prices(clean.data).issues}


def test_cli_commits_valid_rows_and_keeps_short_history_blocked(monkeypatch, tmp_path):
    frame = _prices()
    frame.loc[:10, "high"] = 1.0  # 249 remaining: still unavailable for signals
    short = frame.iloc[-1:].assign(etf_id="NEW", high=11.0)
    lost = frame.iloc[-1:].assign(etf_id="LOST", high=1.0)
    result = ProviderResult("yfinance", "prices", "ok", "download", pd.concat([frame, short, lost]))
    module = _cli(monkeypatch, tmp_path, result)
    committed = []
    monkeypatch.setattr(module, "commit_price_import", lambda r: committed.append(r) or SimpleNamespace(
        rows=len(r.data), clean_path=tmp_path / "clean", raw_path=tmp_path / "raw", previous_snapshot_path=None))
    monkeypatch.setattr(module, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(module, "model_availability", lambda _: {"toto": False, "timesfm": False})
    def unavailable_backtest(*args, **kwargs):
        raise module.BacktestDataUnavailableError("not_enough_data: 260 complete sessions required")
    monkeypatch.setattr(module, "run_backtest", unavailable_backtest)
    monkeypatch.setattr(module, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(module, "_load_local_structural_evidence", lambda: SimpleNamespace(
        document_registry=None, report_records=None, supplemental_rows=None, holdings=None))
    def signals(_, latest, holdings, report, **kwargs):
        assert {"A", "NEW", "LOST"} <= report.blocked_etfs
        assert all(i.code == "insufficient_history" for i in report.issues if i.severity == "block")
        return []
    monkeypatch.setattr(module, "generate_signals", signals)
    monkeypatch.setattr(module, "compute_features", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(module, "write_features", lambda _: None)
    monkeypatch.setattr(module, "latest_features", lambda *a: pd.DataFrame())
    assert module.main() == 0
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert report["backtest"] == {
        "status": "unavailable", "reason": "not_enough_data: 260 complete sessions required",
    }
    assert report["price_commit"]["committed"] is True
    assert report["quarantined_price_rows"] == 12
    assert len(committed) == 1 and len(committed[0].data) == 250
    quarantined = pd.read_parquet(next((tmp_path / "data" / "quality").glob("*.parquet")))
    assert len(quarantined) == 12
    assert set(quarantined.quarantine_reason) == {"invalid_ohlc"}


def test_cli_rejects_partial_provider_result_without_commit(monkeypatch, tmp_path):
    result = ProviderResult("yfinance", "prices", "error", "Partial refresh rejected", _prices())
    module = _cli(monkeypatch, tmp_path, result)
    monkeypatch.setattr(module, "commit_price_import", lambda _: pytest.fail("partial set committed"))
    assert module.main() == 1
    assert not (tmp_path / "data" / "quality").exists()


def test_cli_rejects_other_validation_blocks(monkeypatch, tmp_path):
    frame = _prices()
    frame.loc[0, "adjusted_close"] = 0.0
    module = _cli(monkeypatch, tmp_path, ProviderResult("yfinance", "prices", "ok", "download", frame))
    monkeypatch.setattr(module, "commit_price_import", lambda _: pytest.fail("invalid adjusted close committed"))
    assert module.main() == 1


def test_cli_rejects_download_with_no_valid_rows(monkeypatch, tmp_path):
    frame = _prices().assign(high=1.0)
    module = _cli(monkeypatch, tmp_path, ProviderResult("yfinance", "prices", "ok", "download", frame))
    monkeypatch.setattr(module, "commit_price_import", lambda _: pytest.fail("empty set committed"))
    assert module.main() == 1
