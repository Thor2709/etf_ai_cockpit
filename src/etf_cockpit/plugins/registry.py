"""Allow-list validation, discovery and safe invocation for plugins."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import metadata
import inspect
from typing import Iterable, Mapping, Protocol

from etf_cockpit.plugins.contracts import (
    PLUGIN_CONFORMANCE_SCHEMA_VERSION,
    PluginContext,
    PluginHealth,
    PluginManifest,
    PluginResult,
    PluginStatus,
)


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
        self._plugins[plugin_id] = plugin
        self._enabled[plugin_id] = bool(enabled)

    def disable(self, plugin_id: str) -> None:
        self._require(plugin_id)
        self._enabled[plugin_id] = False

    def enable(self, plugin_id: str) -> None:
        self._require(plugin_id)
        self._enabled[plugin_id] = True

    def health(self, plugin_id: str) -> PluginHealth:
        plugin = self._require(plugin_id)
        if not self._enabled[plugin_id]:
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

    def invoke(self, plugin_id: str, operation: str, payload: Mapping[str, object] | None = None) -> PluginResult:
        plugin = self._require(plugin_id)
        if not self._enabled[plugin_id]:
            return PluginResult(status="unavailable", message="Plugin disabled by local allow-list policy.")
        method = getattr(plugin, str(operation).strip(), None)
        if not callable(method):
            return PluginResult(status="unsupported", message=f"Plugin does not support operation {operation!r}.")
        context = PluginContext(request_id=f"{operation}:{plugin_id}", inputs=payload or {})
        try:
            result = method(dict(payload or {}), context)
            if not isinstance(result, PluginResult):
                return PluginResult(status="failed", message="Plugin returned a malformed result contract.")
            return result
        except Exception as exc:  # no plugin exception crosses the app boundary
            return PluginResult(status="failed", message=f"Plugin operation failed: {type(exc).__name__}.")

    def status_rows(self) -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        for plugin_id in self.plugin_ids:
            plugin = self._plugins[plugin_id]
            manifest = plugin.manifest
            health = self.health(plugin_id)
            enabled = self._enabled[plugin_id]
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
            manifest = self._plugins[plugin_id].manifest
            health = self.health(plugin_id)
            failed = health.status is PluginStatus.INVALID or manifest.executable_authority or manifest.writes_canonical_stores
            if failed:
                failures.append(plugin_id)
            checks.append(
                {
                    "plugin_id": plugin_id,
                    "kind": manifest.kind.value,
                    "status": health.status.value,
                    "network_calls": False,
                    "secrets_required": bool(manifest.credential_requirements),
                    "canonical_store_write": False,
                    "executable_authority": False,
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

    def _require(self, plugin_id: str) -> PluginImplementation:
        key = str(plugin_id).strip().lower()
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc


def _fingerprint(exc: Exception) -> str:
    return hashlib.sha256(f"{type(exc).__name__}:{exc}".encode("utf-8", errors="replace")).hexdigest()[:16]


__all__ = ["PluginImplementation", "PluginRegistrationError", "PluginRegistry"]
