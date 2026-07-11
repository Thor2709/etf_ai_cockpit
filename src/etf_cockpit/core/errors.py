from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable

from etf_cockpit.core.paths import LOG_DIR


class ErrorCategory(StrEnum):
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    ENTITLEMENT = "entitlement"
    INVALID_INPUT = "invalid_input"
    IDENTITY_CONFLICT = "identity_conflict"
    PARSER_SCHEMA = "parser_schema"
    PERMISSION = "permission"
    LOCKED_FILE = "locked_file"
    MISSING_DATA = "missing_data"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ErrorRecord:
    error_id: str
    action_id: str
    category: ErrorCategory
    user_message: str
    fingerprint: str
    retryable: bool
    created_at: str
    detail: str = ""
    retry_key: str | None = None


RetryHandler = Callable[[], object]


class ErrorStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (LOG_DIR / "errors.jsonl")
        self._retry_handlers: dict[str, RetryHandler] = {}
        self._lock = threading.Lock()

    def append(
        self,
        *,
        action_id: str,
        category: ErrorCategory,
        user_message: str,
        retryable: bool,
        retry_key: str | None = None,
        detail: str = "",
    ) -> ErrorRecord:
        safe_message = _redact(str(user_message))
        safe_detail = _redact(str(detail)) if os.getenv("ETF_COCKPIT_DEVELOPER_MODE") == "1" else ""
        fingerprint = hashlib.sha256(f"{category.value}:{safe_message}".encode("utf-8")).hexdigest()[:16]
        record = ErrorRecord(
            error_id=f"error_{uuid.uuid4().hex[:12]}",
            action_id=str(action_id),
            category=ErrorCategory(category),
            user_message=safe_message,
            fingerprint=fingerprint,
            retryable=bool(retryable),
            created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            detail=safe_detail,
            retry_key=retry_key,
        )
        self._append(record)
        return record

    def recent(self, limit: int = 20) -> list[ErrorRecord]:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        records: list[ErrorRecord] = []
        for line in reversed(lines):
            try:
                payload = json.loads(line)
                records.append(
                    ErrorRecord(
                        error_id=str(payload["error_id"]),
                        action_id=str(payload.get("action_id") or ""),
                        category=ErrorCategory(str(payload.get("category") or ErrorCategory.UNKNOWN.value)),
                        user_message=str(payload.get("user_message") or ""),
                        fingerprint=str(payload.get("fingerprint") or ""),
                        retryable=bool(payload.get("retryable")),
                        created_at=str(payload.get("created_at") or ""),
                        detail=str(payload.get("detail") or ""),
                        retry_key=payload.get("retry_key"),
                    )
                )
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if len(records) >= limit:
                break
        return records

    def register_retry(self, retry_key: str, callback: RetryHandler) -> None:
        self._retry_handlers[str(retry_key)] = callback

    def retry_request(self, error_id: str) -> object | None:
        record = next((item for item in self.recent(100) if item.error_id == error_id), None)
        if record is None or not record.retryable or not record.retry_key:
            return None
        callback = self._retry_handlers.get(record.retry_key)
        return None if callback is None else callback()

    def _append(self, record: ErrorRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.__dict__, default=str, sort_keys=True) + "\n")
                handle.flush()
        except Exception:
            pass


def classify_exception(exc: BaseException) -> tuple[ErrorCategory, bool]:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return ErrorCategory.NETWORK, True
    if isinstance(exc, PermissionError):
        return ErrorCategory.PERMISSION, False
    if isinstance(exc, FileNotFoundError):
        return ErrorCategory.MISSING_DATA, False
    if isinstance(exc, (ValueError, TypeError)):
        return ErrorCategory.INVALID_INPUT, False
    text = str(exc).lower()
    if "429" in text or "rate limit" in text:
        return ErrorCategory.RATE_LIMIT, True
    if "token" in text or "api key" in text or "authentication" in text:
        return ErrorCategory.AUTHENTICATION, False
    if "schema" in text or "parse" in text or "malformed" in text:
        return ErrorCategory.PARSER_SCHEMA, False
    if "identity" in text or "isin" in text:
        return ErrorCategory.IDENTITY_CONFLICT, False
    if "locked" in text or "sharing violation" in text:
        return ErrorCategory.LOCKED_FILE, True
    return ErrorCategory.UNKNOWN, False


def _redact(value: str) -> str:
    return re.sub(
        r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|bearer)(\s*[=:]\s*)(['\"]?)[^'\"\s,;]+",
        r"\1\2***redacted***",
        value,
    )
