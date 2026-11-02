"""Single-use, client-bound confirmation tokens for MCP write calls.

Open defaults: confirmations expire after 900 seconds (15 minutes); a random process-local
HMAC key invalidates outstanding tokens when the server restarts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any

from etf_cockpit.mcp.errors import ConfirmationError
from etf_cockpit.mcp.serialise import canonical_json


DEFAULT_CONFIRMATION_TTL_SECONDS = 900


class ConfirmationStore:
    def __init__(self, secret: bytes | None = None, *, ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS, clock=time.time) -> None:
        if ttl_seconds < 1:
            raise ValueError("confirmation ttl_seconds must be positive")
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("confirmation signing key must be at least 32 bytes")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    def issue(self, payload: Any, *, store_revision: str, client_id: str) -> str:
        now = int(self._clock())
        body = {
            "payload_sha256": hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            "store_revision": str(store_revision),
            "client_id": str(client_id),
            "issued_at": now,
            "expires_at": now + self._ttl_seconds,
            "nonce": secrets.token_urlsafe(18),
        }
        encoded = _b64encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"v1.{encoded}.{_b64encode(signature)}"

    def consume(self, token: str, payload: Any, *, store_revision: str, client_id: str) -> bool:
        try:
            version, encoded, signature_text = token.split(".", 2)
            if version != "v1":
                return False
            signature = _b64decode(signature_text)
            expected = hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return False
            body = json.loads(_b64decode(encoded))
            payload_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
            now = int(self._clock())
            nonce = body["nonce"]
            valid = (
                body["payload_sha256"] == payload_hash
                and body["store_revision"] == str(store_revision)
                and body["client_id"] == str(client_id)
                and isinstance(body["issued_at"], int)
                and isinstance(body["expires_at"], int)
                and body["issued_at"] <= now <= body["expires_at"]
                and body["expires_at"] - body["issued_at"] <= self._ttl_seconds
                and isinstance(nonce, str)
            )
            if not valid:
                return False
            with self._lock:
                if nonce in self._consumed:
                    return False
                self._consumed.add(nonce)
            return True
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
            return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
