"""Allow-listed, local-first plugin contracts."""

from etf_cockpit.plugins.contracts import (
    PLUGIN_CONTRACT_SCHEMA_VERSION,
    PluginHealth,
    PluginKind,
    PluginManifest,
    PluginResult,
    PluginStatus,
)
from etf_cockpit.plugins.registry import PluginRegistry

__all__ = [
    "PLUGIN_CONTRACT_SCHEMA_VERSION",
    "PluginHealth",
    "PluginKind",
    "PluginManifest",
    "PluginRegistry",
    "PluginResult",
    "PluginStatus",
]
