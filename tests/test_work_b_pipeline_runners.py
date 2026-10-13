"""Regression coverage for cached-data and fail-closed pipeline entry points."""

from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _runner(monkeypatch, name):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return importlib.import_module(name)


def test_explicit_invalid_root_never_invokes_pipeline(monkeypatch, capsys, tmp_path):
    cli = _runner(monkeypatch, "run_pipeline_cli")
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))

    def unexpected_pipeline():
        raise AssertionError("Invalid explicit root must not fall back to worktree data")

    assert cli.run_cli(unexpected_pipeline) == 1
    output = capsys.readouterr().out
    assert "Invalid ETF_COCKPIT_ROOT" in output
    assert "configs/universe.yaml and data/" in output
    assert "Traceback" not in output


def test_missing_cached_input_fails_without_sample_initialisation(monkeypatch, capsys, tmp_path):
    cli = _runner(monkeypatch, "run_pipeline_cli")
    monkeypatch.delenv("ETF_COCKPIT_ROOT", raising=False)
    missing = tmp_path / "prices_daily.parquet"

    def pipeline():
        cli.require_cached_inputs(missing)
        raise AssertionError("Missing real prices must not continue into sample loaders")

    assert cli.run_cli(pipeline) == 1
    assert "Cached input unavailable" in capsys.readouterr().out
    assert not missing.exists()


def test_signals_honours_historical_date_without_latest_feature_precompute(monkeypatch):
    runner = _runner(monkeypatch, "run_signals")
    monkeypatch.setattr(sys, "argv", ["run_signals.py", "--date", "2026-06-30"])
    monkeypatch.setattr(runner, "require_cached_inputs", lambda *paths: None)
    config = object()
    monkeypatch.setattr(runner, "load_config", lambda: config)
    calls = []

    class Service:
        def __init__(self, received):
            assert received is config

        def generate_signals(self, **kwargs):
            calls.append(kwargs)
            return []

    monkeypatch.setattr(runner, "SignalService", Service)
    assert runner.main() == 0
    assert calls == [{"as_of_date": date(2026, 6, 30)}]


def test_backtest_uses_cached_data_and_reports_unavailability(monkeypatch, capsys):
    runner = _runner(monkeypatch, "run_backtest")
    from etf_cockpit.application.data_service import DataService

    def reject_sample_update(*args, **kwargs):
        raise AssertionError("Backtest must not initialise or replace prices with samples")

    monkeypatch.setattr(DataService, "update_prices", reject_sample_update)
    monkeypatch.setattr(runner, "require_cached_inputs", lambda *paths: None)
    monkeypatch.setattr(runner, "load_config", lambda: object())
    report = SimpleNamespace(results=pd.DataFrame(), quality_label="low", quality_notes=[])
    monkeypatch.setattr(runner, "BacktestService", lambda config: SimpleNamespace(run_backtest=lambda: report))
    assert runner.main() == 0
    report.quality_label = "not_available"
    report.quality_notes = ["Adjusted-price evidence unavailable"]
    assert runner.main() == 1
    assert "Backtest unavailable: Adjusted-price evidence unavailable" in capsys.readouterr().out


def test_forecasts_empty_prices_fail_clearly_before_model_execution(monkeypatch, capsys):
    runner = _runner(monkeypatch, "run_forecasts")
    monkeypatch.setattr(sys, "argv", ["run_forecasts.py"])
    monkeypatch.delenv("ETF_COCKPIT_ROOT", raising=False)
    monkeypatch.setattr(runner, "require_cached_inputs", lambda *paths: None)
    monkeypatch.setattr(runner, "load_config", lambda: object())
    monkeypatch.setattr(runner, "load_prices", lambda: pd.DataFrame(columns=["date", "etf_id", "adjusted_close"]))

    def reject_models(*args, **kwargs):
        raise AssertionError("Empty prices must fail before models run")

    monkeypatch.setattr(runner, "ForecastService", reject_models)
    assert runner.run_cli(runner.main) == 1
    assert "Cached prices contain no dated observations" in capsys.readouterr().out


def test_yahoo_runners_accept_leap_day_and_candidate_path_uses_data_root(monkeypatch):
    analysis = _runner(monkeypatch, "run_yfinance_analysis")
    candidate = _runner(monkeypatch, "run_yfinance_candidate_forecasts")
    assert candidate.DEFAULT_CANDIDATES == candidate.RAW_DIR / "trade_candidates" / "yahoo_trade_candidates_2026-06-30.csv"
    calls = []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        @classmethod
        def from_config(cls, config):
            return cls()

        def fetch_prices(self, symbols, start, end):
            calls.append((start, end))
            return SimpleNamespace(ok=False, data=None, message="Network unavailable")

    monkeypatch.setattr(analysis, "load_config", lambda: object())
    monkeypatch.setattr(analysis, "YFinanceProvider", Provider)
    monkeypatch.setattr(sys, "argv", ["run_yfinance_analysis.py", "--as-of", "2024-02-29", "--years", "1"])
    assert analysis.main() == 1
    monkeypatch.setattr(candidate, "YFinanceProvider", Provider)
    # Use actual configured identifiers; do not synthesize external symbols.
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data.yfinance_provider import yfinance_symbol_map_from_config

    candidates = pd.DataFrame(
        yfinance_symbol_map_from_config(load_config()).items(),
        columns=["instrument_id", "yahoo_symbol"],
    )
    monkeypatch.setattr(candidate.pd, "read_csv", lambda path: candidates)
    monkeypatch.setattr(sys, "argv", ["run_yfinance_candidate_forecasts.py", "--as-of", "2024-02-29", "--years", "1"])
    assert candidate.main() == 1
    assert calls == [(date(2023, 2, 28), date(2024, 2, 29))] * 2
