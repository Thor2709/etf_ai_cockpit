from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Callable, Generic, TypeVar
from uuid import uuid4

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.data.contracts import redact_text

T = TypeVar("T")
_SCHEMA_VERSION = 1
_RUN_STATUSES = {"pending", "done", "failed", "unavailable"}


class RetrievalCheckpointError(ValueError):
    """Raised when a retrieval checkpoint cannot be safely resumed."""


@dataclass(frozen=True)
class SymbolRetrieval(Generic[T]):
    symbol: str
    status: str
    attempts: int
    value: T | None = None
    retrieved_at: str | None = None
    error: str | None = None
    error_fingerprint: str | None = None


@dataclass(frozen=True)
class RetrievalBatchResult(Generic[T]):
    run_id: str
    request_fingerprint: str
    symbols: dict[str, SymbolRetrieval[T]]


class ProviderRateLimiter:
    """Synchronous rolling-window and minimum-interval provider limiter."""

    def __init__(
        self,
        *,
        minimum_interval_seconds: float = 0.0,
        max_calls_per_window: int | None = None,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if max_calls_per_window is not None and max_calls_per_window < 1:
            raise ValueError("max_calls_per_window must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.minimum_interval_seconds = minimum_interval_seconds
        self.max_calls_per_window = max_calls_per_window
        self.window_seconds = window_seconds
        self.clock = clock
        self.sleep = sleep
        self._calls: deque[float] = deque()
        self._last_call: float | None = None
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = self.clock()
                while self._calls and self._calls[0] <= now - self.window_seconds:
                    self._calls.popleft()
                waits = []
                if self._last_call is not None:
                    waits.append(self._last_call + self.minimum_interval_seconds - now)
                if (
                    self.max_calls_per_window is not None
                    and len(self._calls) >= self.max_calls_per_window
                ):
                    waits.append(self._calls[0] + self.window_seconds - now)
                wait_seconds = max(waits, default=0.0)
                if wait_seconds <= 0:
                    if self.max_calls_per_window is not None:
                        self._calls.append(now)
                    self._last_call = now
                    return
                self.sleep(wait_seconds)


_LIMITER_REGISTRY: dict[str, ProviderRateLimiter] = {}
_LIMITER_REGISTRY_LOCK = threading.Lock()


def provider_rate_limiter(
    provider: str,
    *,
    minimum_interval_seconds: float = 0.0,
    max_calls_per_window: int | None = 60,
    window_seconds: float = 60.0,
) -> ProviderRateLimiter:
    """Return the process-shared limiter for one provider identifier."""

    key = str(provider).strip()
    if not key:
        raise ValueError("provider must be non-empty")
    with _LIMITER_REGISTRY_LOCK:
        limiter = _LIMITER_REGISTRY.get(key)
        if limiter is None:
            limiter = ProviderRateLimiter(
                minimum_interval_seconds=minimum_interval_seconds,
                max_calls_per_window=max_calls_per_window,
                window_seconds=window_seconds,
            )
            _LIMITER_REGISTRY[key] = limiter
        return limiter


class BatchRetriever(Generic[T]):
    """Batch, rate-limit, cache and checkpoint per-symbol provider calls."""

    def __init__(
        self,
        *,
        provider: str,
        cache_dir: Path | None,
        checkpoint_path: Path | None,
        batch_size: int = 25,
        adjusted: bool = False,
        adapter_version: str = "1",
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        limiter: ProviderRateLimiter | None = None,
        encode: Callable[[T], bytes] | None = None,
        decode: Callable[[bytes], T] | None = None,
        is_available: Callable[[T], bool] | None = None,
    ) -> None:
        if not str(provider).strip():
            raise ValueError("provider must be non-empty")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        if (encode is None) != (decode is None):
            raise ValueError("encode and decode must be supplied together")
        if (cache_dir is None) != (checkpoint_path is None):
            raise ValueError("cache_dir and checkpoint_path must be supplied together")
        self.provider = str(provider).strip()
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else None
        self.batch_size = batch_size
        self.adjusted = bool(adjusted)
        self.adapter_version = str(adapter_version)
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.clock = clock
        self.sleep = sleep
        self.limiter = limiter or ProviderRateLimiter(clock=time.monotonic, sleep=time.sleep)
        self.encode = encode or _json_encode
        self.decode = decode or _json_decode
        self.is_available = is_available or (lambda value: value is not None)
        self._memory_cache: dict[bytes, tuple[bytes, str]] = {}
        self._memory_manifest: dict[str, object] | None = None

    def retrieve(
        self,
        symbols: list[str],
        *,
        start: object,
        end: object,
        downloader: Callable[[str], T],
    ) -> RetrievalBatchResult[T]:
        ordered_symbols = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
        request = {
            "provider": self.provider,
            "symbols": ordered_symbols,
            "start": _date_value(start),
            "end": _date_value(end),
            "adjusted": self.adjusted,
            "adapter_version": self.adapter_version,
        }
        fingerprint = _sha256(_canonical_json(request))
        manifest = self._load_or_start_manifest(request, fingerprint)
        run_id = str(manifest["run_id"])
        records = manifest["symbols"]
        assert isinstance(records, dict)
        cached_values: dict[str, tuple[T, str] | None] = {
            symbol: self._read_cache(self._cache_key(symbol, request)) for symbol in ordered_symbols
        }

        # Completed entries must still have a valid content-addressed cache object.
        # Invalid or missing content is converted to failed so it can be refetched.
        changed = False
        for symbol in ordered_symbols:
            record = records[symbol]
            if record["status"] in {"done", "unavailable"} and cached_values[symbol] is None:
                record.update(
                    status="failed",
                    attempts=0,
                    error_fingerprint=_error_fingerprint("completed cache entry unavailable"),
                )
                changed = True
        if changed:
            self._write_manifest(manifest)

        values: dict[str, SymbolRetrieval[T]] = {}
        for batch in self.batches(ordered_symbols):
            for symbol in batch:
                record = records[symbol]
                status = str(record["status"])
                attempts = int(record["attempts"])
                cached = cached_values[symbol]
                if cached is not None and status in {"done", "unavailable"}:
                    value, retrieved_at = cached
                    values[symbol] = self._result(symbol, status, attempts, value, retrieved_at)
                    continue
                if cached is not None and status in {"pending", "failed"}:
                    value, retrieved_at = cached
                    status = "done" if self.is_available(value) else "unavailable"
                    record.update(status=status, error_fingerprint=None)
                    self._write_manifest(manifest)
                    values[symbol] = self._result(symbol, status, attempts, value, retrieved_at)
                    continue
                if status == "done" or status == "unavailable":
                    # The checkpoint was already changed to failed above; retain a
                    # defensive failure if its schema changes unexpectedly.
                    status = "failed"
                error: str | None = None
                attempts_this_run = 0
                while attempts_this_run < self.max_retries + 1:
                    attempts_this_run += 1
                    attempts += 1
                    record.update(status="pending", attempts=attempts, error_fingerprint=None)
                    self._write_manifest(manifest)
                    try:
                        self.limiter.acquire()
                        value = downloader(symbol)
                        payload = self.encode(value)
                        retrieved_at = self._retrieved_at()
                        self._write_cache(self._cache_key(symbol, request), payload, retrieved_at)
                        status = "done" if self.is_available(value) else "unavailable"
                        record.update(status=status, error_fingerprint=None)
                        self._write_manifest(manifest)
                        values[symbol] = self._result(symbol, status, attempts, value, retrieved_at)
                        break
                    except Exception as exc:
                        error = redact_text(f"{type(exc).__name__}: {exc}")
                        record.update(
                            status="failed",
                            error_fingerprint=_error_fingerprint(error),
                        )
                        self._write_manifest(manifest)
                        if attempts_this_run < self.max_retries + 1:
                            self.sleep(self.backoff_seconds * (2 ** (attempts_this_run - 1)))
                else:
                    record["status"] = "failed"
                if symbol not in values:
                    error_fingerprint = record.get("error_fingerprint")
                    values[symbol] = SymbolRetrieval(
                        symbol=symbol,
                        status="failed",
                        attempts=attempts,
                        error=error,
                        error_fingerprint=(str(error_fingerprint) if error_fingerprint else None),
                    )

        self._write_manifest(manifest)
        return RetrievalBatchResult(run_id, fingerprint, values)

    def batches(self, symbols: list[str]) -> list[list[str]]:
        """Split a symbol sequence into the configured bounded batches."""

        ordered_symbols = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
        return [
            ordered_symbols[offset : offset + self.batch_size]
            for offset in range(0, len(ordered_symbols), self.batch_size)
        ]

    def _result(
        self,
        symbol: str,
        status: str,
        attempts: int,
        value: T,
        retrieved_at: str,
    ) -> SymbolRetrieval[T]:
        return SymbolRetrieval(symbol, status, attempts, value, retrieved_at)

    def _cache_key(self, symbol: str, request: dict[str, object]) -> dict[str, object]:
        return {
            "provider": self.provider,
            "symbol": symbol,
            "start": request["start"],
            "end": request["end"],
            "adjusted": self.adjusted,
            "adapter_version": self.adapter_version,
        }

    def _cache_path(self, key: dict[str, object]) -> Path:
        assert self.cache_dir is not None
        return self.cache_dir / f"{_sha256(_canonical_json(key))}.json"

    def _read_cache(self, key: dict[str, object]) -> tuple[T, str] | None:
        if self.cache_dir is None:
            cached = self._memory_cache.get(_canonical_json(key))
            if cached is None:
                return None
            payload, retrieved_at = cached
            try:
                return self.decode(payload), retrieved_at
            except Exception:
                return None
        path = self._cache_path(key)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(entry, dict) or entry.get("key") != key:
                return None
            encoded = entry.get("content")
            digest = entry.get("sha256")
            retrieved_at = entry.get("retrieved_at")
            if not isinstance(encoded, str) or not isinstance(digest, str):
                return None
            payload = encoded.encode("utf-8")
            if _sha256(payload) != digest:
                return None
            if not isinstance(retrieved_at, str) or not _valid_timestamp(retrieved_at):
                return None
            value = self.decode(payload)
            return value, retrieved_at
        except Exception:
            return None

    def _write_cache(self, key: dict[str, object], payload: bytes, retrieved_at: str) -> None:
        try:
            content = payload.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("cache encoder must return UTF-8 bytes") from exc
        if self.cache_dir is None:
            self._memory_cache[_canonical_json(key)] = (content.encode("utf-8"), retrieved_at)
            return
        atomic_write_json(
            self._cache_path(key),
            {"key": key, "content": content, "sha256": _sha256(payload), "retrieved_at": retrieved_at},
        )

    def _load_or_start_manifest(self, request: dict[str, object], fingerprint: str) -> dict[str, object]:
        path = self.checkpoint_path
        manifest = self._memory_manifest if path is None else None
        if path is not None and path.is_file():
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RetrievalCheckpointError(f"retrieval checkpoint is corrupt or unreadable: {path.name}") from exc
        if manifest is not None:
            if not isinstance(manifest, dict):
                raise RetrievalCheckpointError("retrieval checkpoint must contain a JSON object")
            stored_request = manifest.get("request")
            if not isinstance(stored_request, dict):
                raise RetrievalCheckpointError("retrieval checkpoint is missing its request")
            stored_fingerprint = manifest.get("request_fingerprint")
            if (
                not isinstance(stored_fingerprint, str)
                or _sha256(_canonical_json(stored_request)) != stored_fingerprint
            ):
                raise RetrievalCheckpointError("retrieval checkpoint request fingerprint is invalid")
            self._validate_manifest(manifest, stored_request)
            if manifest.get("request_fingerprint") == fingerprint:
                self._validate_manifest(manifest, request)
                return manifest
        manifest = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": str(uuid4()),
            "request_fingerprint": fingerprint,
            "request": request,
            "symbols": {
                symbol: {"status": "pending", "attempts": 0, "error_fingerprint": None}
                for symbol in request["symbols"]
            },
        }
        self._write_manifest(manifest)
        return manifest

    def _validate_manifest(self, manifest: dict[str, object], request: dict[str, object]) -> None:
        records = manifest.get("symbols")
        request_symbols = request.get("symbols")
        if (
            manifest.get("schema_version") != _SCHEMA_VERSION
            or not isinstance(manifest.get("run_id"), str)
            or not manifest.get("run_id")
            or manifest.get("request") != request
            or set(request) != {"provider", "symbols", "start", "end", "adjusted", "adapter_version"}
            or not isinstance(request.get("provider"), str)
            or not request.get("provider")
            or not isinstance(request_symbols, list)
            or any(not isinstance(symbol, str) or not symbol for symbol in request_symbols)
            or len(request_symbols) != len(set(request_symbols))
            or not isinstance(request.get("start"), str)
            or not isinstance(request.get("end"), str)
            or not isinstance(request.get("adjusted"), bool)
            or not isinstance(request.get("adapter_version"), str)
            or not request.get("adapter_version")
            or not isinstance(records, dict)
            or set(records) != set(request_symbols)
            or not isinstance(manifest.get("request_fingerprint"), str)
            or _sha256(_canonical_json(request)) != manifest.get("request_fingerprint")
        ):
            raise RetrievalCheckpointError("retrieval checkpoint does not match its recorded request")
        for symbol in request_symbols:
            record = records.get(symbol)
            if (
                not isinstance(record, dict)
                or record.get("status") not in _RUN_STATUSES
                or not isinstance(record.get("attempts"), int)
                or isinstance(record.get("attempts"), bool)
                or record["attempts"] < 0
                or (
                    record.get("error_fingerprint") is not None
                    and not _valid_sha256(record.get("error_fingerprint"))
                )
            ):
                raise RetrievalCheckpointError(f"retrieval checkpoint has an invalid status for {symbol}")

    def _write_manifest(self, manifest: dict[str, object]) -> None:
        self._validate_manifest(manifest, manifest["request"])
        if self.checkpoint_path is None:
            self._memory_manifest = manifest
            return
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.checkpoint_path, manifest)

    def _retrieved_at(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat().replace("+00:00", "Z")


def _date_value(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat() if callable(isoformat) else value)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _error_fingerprint(error: str) -> str:
    return _sha256(redact_text(error).encode("utf-8"))


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_timestamp(value: str) -> bool:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return timestamp.tzinfo is not None


def _json_encode(value: T) -> bytes:
    return _canonical_json(value)


def _json_decode(payload: bytes) -> T:
    return json.loads(payload.decode("utf-8"))


__all__ = [
    "BatchRetriever",
    "ProviderRateLimiter",
    "RetrievalBatchResult",
    "RetrievalCheckpointError",
    "SymbolRetrieval",
    "provider_rate_limiter",
]
