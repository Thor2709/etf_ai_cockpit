"""Application boundary for the ISSUE-0037 typed settings centre.

The settings bundle implementation is shared configuration and lives in
:mod:`etf_cockpit.core.settings_bundle` (ADR-0002), so lower layers can read it
without depending on the application layer. Presentation keeps importing it here.
"""

from __future__ import annotations

from etf_cockpit.core.settings_bundle import (
    ANALYSIS_DEPTHS,
    ASSET_SCOPES,
    HORIZONS,
    OUTPUT_CURRENCIES,
    RISK_PROFILES,
    SETTINGS_SCHEMA_VERSION,  # noqa: F401 - consumed through this path
    SettingsBundle,
    SettingsControls,
    SettingsError,
    SettingsMigrationIssue,
    SettingsPreview,
    SettingsSaveResult,
    load_settings_bundle,
    load_settings_bundle_with_issues,
    migrate_legacy_settings,
    preview_settings,
    save_settings,
    settings_export,
    settings_run_identity,
)

__all__ = [
    "ANALYSIS_DEPTHS",
    "ASSET_SCOPES",
    "HORIZONS",
    "OUTPUT_CURRENCIES",
    "RISK_PROFILES",
    "SettingsBundle",
    "SettingsControls",
    "SettingsError",
    "SettingsMigrationIssue",
    "SettingsPreview",
    "SettingsSaveResult",
    "load_settings_bundle",
    "load_settings_bundle_with_issues",
    "migrate_legacy_settings",
    "preview_settings",
    "save_settings",
    "settings_export",
    "settings_run_identity",
]
