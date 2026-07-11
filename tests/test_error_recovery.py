from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.core.errors import ErrorCategory, ErrorStore, classify_exception


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
