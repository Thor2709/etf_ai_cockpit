from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.core.errors import ErrorCategory, ErrorStore, classify_exception
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.services import BacktestService, ForecastService


def test_error_classification_is_controlled_and_retryable() -> None:
    assert classify_exception(TimeoutError("slow provider")) == (ErrorCategory.NETWORK, True)
    assert classify_exception(PermissionError("locked destination")) == (ErrorCategory.PERMISSION, False)
    assert classify_exception(ValueError("invalid input")) == (ErrorCategory.INVALID_INPUT, False)


def test_error_store_redacts_secrets_and_retries_only_retryable(tmp_path: Path) -> None:
    store = ErrorStore(tmp_path / "errors.jsonl")
    calls: list[str] = []
    store.register_retry("refresh", lambda: calls.append("refresh") or "retried")

    retryable = store.append(
        action_id="a1",
        category=ErrorCategory.NETWORK,
        user_message="Provider timed out token=secret-value",
        retryable=True,
        retry_key="refresh",
    )
    non_retryable = store.append(
        action_id="a2",
        category=ErrorCategory.INVALID_INPUT,
        user_message="Bad file api_key=secret-value",
        retryable=False,
    )

    assert "secret-value" not in retryable.user_message
    assert store.retry_request(retryable.error_id) == "retried"
    assert store.retry_request(non_retryable.error_id) is None
    assert calls == ["refresh"]
    records = [json.loads(line) for line in (tmp_path / "errors.jsonl").read_text().splitlines()]
    assert all("secret-value" not in json.dumps(record) for record in records)


def test_error_store_handles_corrupt_history_and_developer_detail(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "errors.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    store = ErrorStore(path)
    monkeypatch.delenv("ETF_COCKPIT_DEVELOPER_MODE", raising=False)
    record = store.append(
        action_id="a3",
        category=ErrorCategory.PARSER_SCHEMA,
        user_message="Parser failed",
        detail="Traceback with token=hidden",
        retryable=False,
    )
    assert store.recent()[0].error_id == record.error_id
    assert store.recent()[0].detail == ""


def test_error_classification_precedence_covers_controlled_failure_states() -> None:
    cases = {
        TimeoutError("provider timeout"): (ErrorCategory.NETWORK, True),
        RuntimeError("HTTP 429 rate limit"): (ErrorCategory.RATE_LIMIT, True),
        RuntimeError("authentication token rejected"): (ErrorCategory.AUTHENTICATION, False),
        RuntimeError("entitlement required"): (ErrorCategory.ENTITLEMENT, False),
        RuntimeError("parser schema malformed response"): (ErrorCategory.PARSER_SCHEMA, False),
        RuntimeError("identity conflict for ISIN"): (ErrorCategory.IDENTITY_CONFLICT, False),
        PermissionError("permission denied"): (ErrorCategory.PERMISSION, False),
        OSError("locked file sharing violation"): (ErrorCategory.LOCKED_FILE, False),
        FileNotFoundError("missing data store"): (ErrorCategory.MISSING_DATA, False),
    }
    for exc, expected in cases.items():
        assert classify_exception(exc) == expected


def test_retryable_exception_registers_callback_and_retry_key(tmp_path: Path) -> None:
    store = ErrorStore(tmp_path / "errors.jsonl")
    calls: list[str] = []
    record = store.record_exception(
        action_id="refresh-1",
        exc=TimeoutError("provider timeout"),
        retry_callback=lambda: calls.append("ok") or "retried",
    )
    assert record.category is ErrorCategory.NETWORK
    assert record.retryable is True
    assert record.retry_key
    assert store.retry_request(record.error_id) == "retried"
    assert calls == ["ok"]


def test_forecast_atomic_write_preserves_previous_output_on_failure(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "forecast.csv"
    destination.write_text("old,clean\n1,yes\n", encoding="utf-8")
    forecast = ForecastResult(
        run_id="run-1",
        model_name="baseline",
        model_version="1",
        etf_id="ETF",
        forecast_date=date(2026, 7, 12),
        horizon_days=5,
        expected_return=0.01,
        expected_excess_return=0.0,
    )

    def fail_write(*_args, **_kwargs):
        raise PermissionError("locked forecast output")

    monkeypatch.setattr("etf_cockpit.services.atomic_write_group", fail_write)
    with pytest.raises(PermissionError):
        ForecastService(load_config())._write_forecasts([forecast], date(2026, 7, 12), output_path=destination)
    assert destination.read_text(encoding="utf-8") == "old,clean\n1,yes\n"


def test_backtest_atomic_group_preserves_all_previous_outputs_on_failure(tmp_path: Path, monkeypatch) -> None:
    paths = [tmp_path / name for name in ("backtest_results.csv", "equity_curves.csv", "trade_log.csv", "signal_log.csv")]
    for path in paths:
        path.write_text("previous\n", encoding="utf-8")
    report = BacktestReport(
        results=pd.DataFrame({"strategy_name": ["signal_strategy"], "backtest_quality": ["low"], "calmar": [0.0]}),
        equity_curves=pd.DataFrame({"signal_strategy": [1.0]}),
        trade_log=pd.DataFrame(),
        signal_log=pd.DataFrame(),
        ai_added_value=False,
    )
    monkeypatch.setattr("etf_cockpit.services.BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr("etf_cockpit.services.run_backtest", lambda *_args, **_kwargs: report)
    monkeypatch.setattr("etf_cockpit.services.load_prices", lambda: pd.DataFrame())
    monkeypatch.setattr("etf_cockpit.services.atomic_write_group", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked backtest output")))
    with pytest.raises(PermissionError):
        BacktestService(load_config()).run_backtest()
    assert [path.read_text(encoding="utf-8") for path in paths] == ["previous\n"] * 4
