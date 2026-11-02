"""Tamper-evident opaque cursors for stateless MCP pagination.

Open defaults: page size is 25 rows, maximum 100 rows, and cursors expire after one hour.
Cursor signing keys are process-local unless a caller supplies a stable key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from etf_cockpit.mcp.errors import InvalidCursorError


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
DEFAULT_CURSOR_TTL_SECONDS = 3600


def validate_page_size(value: int, *, maximum: int = MAX_PAGE_SIZE) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"page size must be between 1 and {maximum}")
    return value


class CursorCodec:
    def __init__(
        self,
        secret: bytes | None = None,
        *,
        ttl_seconds: int = DEFAULT_CURSOR_TTL_SECONDS,
        clock=time.time,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("cursor ttl_seconds must be positive")
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("cursor signing key must be at least 32 bytes")
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    def encode(self, offset: int, *, filters: Any = None) -> str:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("cursor offset must be a non-negative integer")
        body = {
            "offset": offset,
            "filters": hashlib.sha256(json.dumps(filters, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
            "issued_at": int(self._clock()),
            "nonce": secrets.token_urlsafe(12),
        }
        encoded = _b64encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_b64encode(signature)}"

    def decode(self, cursor: str, *, filters: Any = None) -> int:
        try:
            encoded, signature_text = cursor.split(".", 1)
            signature = _b64decode(signature_text)
            expected = hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            body = json.loads(_b64decode(encoded))
            offset = body["offset"]
            issued_at = body["issued_at"]
            filter_hash = hashlib.sha256(json.dumps(filters, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValueError
            if isinstance(issued_at, bool) or not isinstance(issued_at, int):
                raise ValueError
            if body.get("filters") != filter_hash or issued_at > self._clock() or self._clock() - issued_at > self._ttl_seconds:
                raise ValueError
            return offset
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
            raise InvalidCursorError() from None


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
