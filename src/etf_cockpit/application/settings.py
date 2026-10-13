"""Application boundary for the ISSUE-0037 typed settings centre.

The settings bundle implementation is shared configuration and lives in
:mod:`etf_cockpit.core.settings_bundle` (ADR-0002), so lower layers can read it
without depending on the application layer. Presentation keeps importing it here.
"""

from __future__ import annotations

from etf_cockpit.core.config import AppConfig, load_config, save_provider_settings
from etf_cockpit.security.credentials import CredentialVault, CredentialVaultError, canonical_provider_account

from etf_cockpit.core.settings_bundle import (
    ANALYSIS_DEPTHS,
    ASSET_SCOPES,
    HORIZONS,
    OUTPUT_CURRENCIES,
    RISK_PROFILES,
    SettingsControls,
    SettingsError,
    SettingsMigrationIssue,
    SettingsPreview,
    SettingsSaveResult,
    load_settings_bundle,
    load_settings_bundle_with_issues,
    preview_settings,
    save_settings,
)

__all__ = [
    "ANALYSIS_DEPTHS",
    "MISSING_DATA_PENALTY",
    "missing_data_penalty",
    "save_preference",
    "ASSET_SCOPES",
    "AppConfig",
    "CredentialVault",
    "CredentialVaultError",
    "HORIZONS",
    "OUTPUT_CURRENCIES",
    "RISK_PROFILES",
    "SettingsControls",
    "SettingsError",
    "SettingsMigrationIssue",
    "SettingsPreview",
    "SettingsSaveResult",
    "canonical_provider_account",
    "load_config",
    "load_settings_bundle",
    "load_settings_bundle_with_issues",
    "preview_settings",
    "save_provider_settings",
    "save_settings",
]

from etf_cockpit.core.ui_preferences import MISSING_DATA_PENALTY, missing_data_penalty, save_preference
