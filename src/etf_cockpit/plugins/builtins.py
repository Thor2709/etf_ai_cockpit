"""Safe built-in capability records used by the status UI and conformance kit."""

from __future__ import annotations

from pathlib import Path

import yaml

from etf_cockpit.plugins.contracts import PluginHealth, PluginManifest, PluginResult, PluginStatus
from etf_cockpit.plugins.registry import PluginRegistry


DEFAULT_PLUGIN_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "plugin_registry.yaml"
_BUILTIN_VERSIONS = {
    "builtin.local-provider": "1.0.0",
    "builtin.baseline-model": "1.0.0",
    "builtin.paper-broker": "1.0.0",
    "fixed-income.ecb": "1.0.0",
    "fixed-income.esma-firds-fitrs": "1.0.0",
    "fixed-income.finra-trace": "1.0.0",
}
_REMOTE_FIXED_INCOME_PROVIDERS = frozenset(
    {
        "fixed-income.ecb",
        "fixed-income.esma-firds-fitrs",
        "fixed-income.finra-trace",
    }
)


class _LocalProvider:
    manifest = PluginManifest(
        plugin_id="builtin.local-provider",
        version="1.0.0",
        kind="provider",
        capabilities=("health", "fetch", "import"),
        licence="Project-local",
        network_access=False,
        quota="none",
        retention="local-cache-only",
        authority="evidence_only",
    )

    def health(self, _context) -> PluginHealth:
        return PluginHealth(status=PluginStatus.AVAILABLE, message="Local provider path is available without network access.")

    def fetch(self, _payload, _context) -> PluginResult:
        return PluginResult(status="unsupported", message="Use the canonical local import pipeline for provider data.")

    def import_data(self, _payload, _context) -> PluginResult:
        return PluginResult(status="unsupported", message="Core-owned import validation is required before persistence.")


class _BaselineModel:
    manifest = PluginManifest(
        plugin_id="builtin.baseline-model",
        version="1.0.0",
        kind="model",
        capabilities=("health", "score"),
        licence="Project-local",
        network_access=False,
        quota="none",
        retention="local-model-metadata-only",
        authority="research_state",
    )

    def health(self, _context) -> PluginHealth:
        return PluginHealth(status=PluginStatus.AVAILABLE, message="Deterministic baseline model is mandatory and local.")

    def score(self, _payload, _context) -> PluginResult:
        return PluginResult(status="unsupported", message="Core scoring pipeline owns baseline execution.")


class _PaperBroker:
    manifest = PluginManifest(
        plugin_id="builtin.paper-broker",
        version="1.0.0",
        kind="broker_adapter",
        capabilities=("health", "read_only", "paper_preview"),
        licence="Project-local",
        network_access=False,
        quota="none",
        retention="local-paper-ledger-only",
        authority="disabled",
    )

    def health(self, _context) -> PluginHealth:
        return PluginHealth(status=PluginStatus.DISABLED, message="Broker adapters are disabled by execution policy.")


class _DisabledFixedIncomeProvider:
    """Manifest-only provider: policy prevents health/fetch invocation."""

    def __init__(self, plugin_id: str) -> None:
        self.manifest = PluginManifest(
            plugin_id=plugin_id,
            version="1.0.0",
            kind="provider",
            capabilities=("health", "fixed_income_market_data"),
            licence="Unapproved: source-specific legal record required",
            network_access=False,
            quota="unavailable",
            retention="unapproved",
            authority="disabled",
        )

    def health(self, _context) -> PluginHealth:  # pragma: no cover - disabled policy
        raise RuntimeError("disabled fixed-income provider must never be invoked")


def default_plugin_registry(config_path: Path | None = None) -> PluginRegistry:
    allowlist, enabled = _load_policy(config_path or DEFAULT_PLUGIN_CONFIG)
    registry = PluginRegistry(
        allowlist=allowlist
    )
    registry.register(_LocalProvider(), enabled=enabled["builtin.local-provider"])
    registry.register(_BaselineModel(), enabled=enabled["builtin.baseline-model"])
    registry.register(_PaperBroker(), enabled=enabled["builtin.paper-broker"])
    for plugin_id in (
        "fixed-income.ecb",
        "fixed-income.esma-firds-fitrs",
        "fixed-income.finra-trace",
    ):
        registry.register(_DisabledFixedIncomeProvider(plugin_id), enabled=enabled[plugin_id])
    return registry


def plugin_status_rows() -> tuple[dict[str, object], ...]:
    """Return one safe capability representation for all built-in kinds."""

    return default_plugin_registry().status_rows()


def _load_policy(path: Path) -> tuple[dict[str, str], dict[str, bool]]:
    fallback = dict(_BUILTIN_VERSIONS), {
        "builtin.local-provider": True,
        "builtin.baseline-model": True,
        "builtin.paper-broker": False,
        "fixed-income.ecb": False,
        "fixed-income.esma-firds-fitrs": False,
        "fixed-income.finra-trace": False,
    }
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != "plugin-registry.v1" or payload.get("execution_allowed") is not False:
            return fallback
        rows = payload.get("allowlist")
        if not isinstance(rows, list) or not rows:
            return fallback
        allowlist: dict[str, str] = {}
        enabled: dict[str, bool] = {}
        for row in rows:
            if not isinstance(row, dict):
                return fallback
            plugin_id = str(row.get("plugin_id", "")).strip().lower()
            version = str(row.get("version", "")).strip()
            if plugin_id not in _BUILTIN_VERSIONS or version != _BUILTIN_VERSIONS[plugin_id]:
                return fallback
            if row.get("network_access") is not False:
                return fallback
            allowlist[plugin_id] = version
            enabled[plugin_id] = (
                False
                if plugin_id in _REMOTE_FIXED_INCOME_PROVIDERS
                else bool(row.get("enabled", False))
            )
        if set(allowlist) != set(_BUILTIN_VERSIONS):
            return fallback
        return allowlist, enabled
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return fallback


__all__ = ["DEFAULT_PLUGIN_CONFIG", "default_plugin_registry", "plugin_status_rows"]
