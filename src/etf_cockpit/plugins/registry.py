"""Allow-list validation, discovery and safe invocation for plugins."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import inspect
import socket
import threading
from typing import Iterable, Iterator, Mapping, Protocol

from etf_cockpit.core.session_log import redact_text
from etf_cockpit.plugins.contracts import (
    PLUGIN_CONFORMANCE_SCHEMA_VERSION,
    PluginContext,
    PluginHealth,
    PluginManifest,
    PluginResult,
    PluginStatus,
)


# `import` is a Python keyword, so the capability maps to a differently named method.
_HANDLER = {"import": "import_data"}


_AUDIT_LOG_LIMIT = 1000
_PROBE_LOCK = threading.Lock()


class PluginRegistrationError(ValueError):
    """Raised when a plugin is not safe or not explicitly allow-listed."""


class PluginImplementation(Protocol):
    manifest: PluginManifest

    def health(self, context: PluginContext) -> PluginHealth: ...


class PluginRegistry:
    """Registry for explicitly allow-listed plugins.

    Entry-point discovery is opt-in and only imports names present in the
    supplied allow-list.  Disabled plugins remain visible but are never
    instantiated or probed by the workflow path.
    """

    def __init__(self, *, allowlist: Iterable[str] | Mapping[str, str] | None = None) -> None:
        self._allowlist = None if allowlist is None else {
            str(key).strip().lower(): (str(value) if value else "")
            for key, value in (allowlist.items() if isinstance(allowlist, Mapping) else ((item, "") for item in allowlist))
        }
        self._plugins: dict[str, PluginImplementation] = {}
        self._enabled: dict[str, bool] = {}
        self._audit_log: deque[dict[str, str]] = deque(maxlen=_AUDIT_LOG_LIMIT)

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def register(self, plugin: PluginImplementation, *, enabled: bool = True) -> None:
        manifest = getattr(plugin, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise PluginRegistrationError("plugin must expose a validated PluginManifest")
        plugin_id = manifest.plugin_id
        if self._allowlist is not None and plugin_id not in self._allowlist:
            raise PluginRegistrationError(f"plugin {plugin_id!r} is not in the explicit allow-list")
        expected_version = self._allowlist.get(plugin_id, "") if self._allowlist is not None else ""
        if expected_version and expected_version != manifest.version:
            raise PluginRegistrationError(f"plugin {plugin_id!r} version {manifest.version!r} is not allow-listed")
        if not callable(getattr(plugin, "health", None)):
            raise PluginRegistrationError(f"plugin {plugin_id!r} must expose health(context)")
        if manifest.writes_canonical_stores or manifest.executable_authority:
            raise PluginRegistrationError(f"plugin {plugin_id!r} requests forbidden authority")
        if manifest.network_access:
            raise PluginRegistrationError(f"plugin {plugin_id!r} requests network access, which is not permitted")
        if plugin_id in self._plugins:
            raise PluginRegistrationError(f"plugin {plugin_id!r} is already registered")
        self._plugins[plugin_id] = plugin
        # A manifest that declares authority="disabled" can never be switched on.
        self._enabled[plugin_id] = bool(enabled) and manifest.authority != "disabled"

    def disable(self, plugin_id: str) -> None:
        key = self._key(plugin_id)
        self._require(key)
        self._enabled[key] = False

    def enable(self, plugin_id: str) -> None:
        key = self._key(plugin_id)
        plugin = self._require(key)
        if plugin.manifest.authority == "disabled":
            raise PluginRegistrationError(f"plugin {key!r} declares authority 'disabled' and cannot be enabled")
        self._enabled[key] = True

    def is_enabled(self, plugin_id: str) -> bool:
        key = self._key(plugin_id)
        plugin = self._require(key)
        return self._enabled[key] and plugin.manifest.authority != "disabled"

    def audit_events(self) -> tuple[dict[str, str], ...]:
        """Audit events recorded by plugins during health/invoke (bounded, most recent last)."""

        return tuple(dict(item) for item in self._audit_log)

    def health(self, plugin_id: str) -> PluginHealth:
        plugin = self._require(plugin_id)
        if not self.is_enabled(plugin_id):
            return PluginHealth(status=PluginStatus.DISABLED, message="Plugin disabled by local allow-list policy.")
        context = PluginContext(request_id=f"health:{plugin_id}")
        try:
            result = plugin.health(context)
            if not isinstance(result, PluginHealth):
                return PluginHealth(status=PluginStatus.INVALID, message="Plugin health response was not a PluginHealth contract.")
            return result
        except Exception as exc:  # plugin failures are visible and contained
            return PluginHealth(
                status=PluginStatus.UNAVAILABLE,
                message=f"Plugin health failed: {type(exc).__name__}.",
                error_fingerprint=_fingerprint(exc),
            )

        finally:
            self._collect_audit(plugin_id, "health", context)

    def invoke(self, plugin_id: str, operation: str, payload: Mapping[str, object] | None = None) -> PluginResult:
        plugin = self._require(plugin_id)
        if not self.is_enabled(plugin_id):
            return PluginResult(status="unavailable", message="Plugin disabled by local allow-list policy.")
        name = str(operation).strip()
        method = getattr(plugin, _HANDLER.get(name, name), None) if name in plugin.manifest.capabilities else None
        if not callable(method):
            return PluginResult(status="unsupported", message=f"Plugin does not support operation {operation!r}.")
        context: PluginContext | None = None
        try:
            # Plugins get their own deep copy so nested caller input cannot be mutated.
            call_payload = copy.deepcopy(dict(payload or {}))
            context = PluginContext(request_id=f"{operation}:{plugin_id}", inputs=call_payload)
            result = method(copy.deepcopy(call_payload), context)
            if not isinstance(result, PluginResult):
                return PluginResult(status="failed", message="Plugin returned a malformed result contract.")
            return result
        except Exception as exc:  # no plugin exception crosses the app boundary
            return PluginResult(status="failed", message=f"Plugin operation failed: {type(exc).__name__}.")
        finally:
            if context is not None:
                self._collect_audit(plugin_id, str(operation), context)

    def status_rows(self) -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        for plugin_id in self.plugin_ids:
            plugin = self._plugins[plugin_id]
            manifest = plugin.manifest
            health = self.health(plugin_id)
            enabled = self.is_enabled(plugin_id)
            rows.append(
                {
                    "provider_id": f"plugin:{plugin_id}",
                    "dataset_type": manifest.kind.value,
                    "enabled": enabled,
                    "configured": enabled,
                    "status": health.status.value,
                    "authority": manifest.authority,
                    "capabilities": ", ".join(manifest.capabilities),
                    "entitlement": "configured" if enabled else "disabled",
                    "rate_limit_note": manifest.quota,
                    "last_success_at": health.checked_at,
                    "redacted_configuration": {
                        "network_access": manifest.network_access,
                        "credential_requirements": manifest.credential_requirements,
                        "retention": manifest.retention,
                        "licence": manifest.licence,
                    },
                    "score_eligible": False,
                    "message": health.message,
                    "executable_authority": False,
                }
            )
        return tuple(rows)

    def conformance_report(self) -> dict[str, object]:
        checks: list[dict[str, object]] = []
        failures: list[str] = []
        for plugin_id in self.plugin_ids:
            plugin = self._plugins[plugin_id]
            manifest = plugin.manifest
            with _network_probe() as network_calls:
                health = self.health(plugin_id)
            missing = tuple(
                capability
                for capability in manifest.capabilities
                if not callable(getattr(plugin, _HANDLER.get(capability, capability), None))
            )
            # Disabled plugins are never invoked, so unimplemented capabilities only fail enabled ones.
            failed = (
                health.status is PluginStatus.INVALID
                or manifest.executable_authority
                or manifest.writes_canonical_stores
                or bool(network_calls)
                or (bool(missing) and self.is_enabled(plugin_id))
            )
            if failed:
                failures.append(plugin_id)
            checks.append(
                {
                    "plugin_id": plugin_id,
                    "kind": manifest.kind.value,
                    "status": health.status.value,
                    "network_calls": bool(network_calls),
                    "network_call_count": len(network_calls),
                    "secrets_required": bool(manifest.credential_requirements),
                    "canonical_store_write": False,
                    "executable_authority": False,
                    "missing_capabilities": list(missing),
                    "passed": not failed,
                }
            )
        return {
            "schema_version": PLUGIN_CONFORMANCE_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "checks": checks,
            "failures": failures,
        }

    def discover_entry_points(self, *, group: str = "etf_cockpit.plugins") -> tuple[str, ...]:
        if self._allowlist is None:
            raise PluginRegistrationError("entry-point discovery requires an explicit allow-list")
        discovered: list[str] = []
        entry_points = metadata.entry_points()
        selected = entry_points.select(group=group) if hasattr(entry_points, "select") else entry_points.get(group, ())
        for entry_point in selected:
            plugin_id = str(entry_point.name).strip().lower()
            if plugin_id not in self._allowlist:
                continue
            candidate = entry_point.load()
            plugin = candidate() if inspect.isclass(candidate) else candidate
            self.register(plugin)
            discovered.append(plugin_id)
        return tuple(sorted(discovered))

    def _collect_audit(self, plugin_id: str, operation: str, context: PluginContext) -> None:
        for event in context.audit_events:
            self._audit_log.append({"plugin_id": plugin_id, "operation": operation, **{key: redact_text(value) for key, value in event.items()}})

    @staticmethod
    def _key(plugin_id: str) -> str:
        return str(plugin_id).strip().lower()

    def _require(self, plugin_id: str) -> PluginImplementation:
        key = self._key(plugin_id)
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc


@contextmanager
def _network_probe() -> Iterator[list[str]]:
    """Count (and block) socket connection attempts made while the block runs."""

    calls: list[str] = []

    def blocked(name: str):
        def guard(*_args, **_kwargs):
            calls.append(name)
            raise OSError("network access is blocked during plugin conformance")

        return guard

    targets = (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket.socket, "sendto"),
        (socket, "getaddrinfo"),
        (socket, "create_connection"),
    )
    if hasattr(socket.socket, "sendmsg"):
        targets += ((socket.socket, "sendmsg"),)
    with _PROBE_LOCK:
        originals = [(owner, attr, getattr(owner, attr)) for owner, attr in targets]
        try:
            for owner, attr in targets:
                setattr(owner, attr, blocked(attr))
            yield calls
        finally:
            for owner, attr, original in originals:
                setattr(owner, attr, original)


def _fingerprint(exc: Exception) -> str:
    return hashlib.sha256(f"{type(exc).__name__}:{exc}".encode("utf-8", errors="replace")).hexdigest()[:16]


__all__ = ["PluginImplementation", "PluginRegistrationError", "PluginRegistry"]
