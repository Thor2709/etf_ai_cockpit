from __future__ import annotations

import os

import flet as ft

from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    Field,
    GlassCard,
    Note,
    Segmented,
    TableColumn,
    Tag,
    Toggle,
    field_input_style,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_percent
from etf_cockpit.app.state import AppState
from etf_cockpit.application.release_metadata import (
    describe_release_evidence,
    read_changelog_excerpt,
    read_rebuild_timestamp,
)
from etf_cockpit.application.scope_facade import load_authority_matrix, load_product_governance
from etf_cockpit.application.settings import (
    ANALYSIS_DEPTHS,
    ASSET_SCOPES,
    HORIZONS,
    OUTPUT_CURRENCIES,
    RISK_PROFILES,
    CredentialVault,
    CredentialVaultError,
    SettingsError,
    canonical_provider_account,
    load_config,
    load_settings_bundle,
    load_settings_bundle_with_issues,
    preview_settings,
    save_settings,
)
from etf_cockpit.application.ui_facade import (
    create_encrypted_backup,
    delete_private_data,
    legal_terms_report,
    run_disaster_recovery_drill,
    supply_chain_intake_report,
    validate_encrypted_restore,
)
from etf_cockpit.core.constants import APP_VERSION
from etf_cockpit.core.paths import CONFIG_DIR, DATA_DIR, ROOT


_RISK_LABELS = {
    "safe": "Safe",
    "safe_medium": "Safe-Medium",
    "medium": "Medium",
    "medium_aggressive": "Medium-Aggressive",
    "aggressive": "Aggressive",
}
_HORIZON_LABELS = {str(value): str(value).upper() for value in HORIZONS}
_DEPTH_LABELS = {str(value): str(value).title() for value in ANALYSIS_DEPTHS}


def _label(value: object) -> str:
    text = str(value or "").replace("_", " ").strip()
    known = {
        "none": "Not configured",
        "true": "Enabled",
        "false": "Disabled",
        "available": "Available",
        "unavailable": "Unavailable",
        "passed": "Passed",
        "failed": "Failed",
        "ready": "Ready",
        "review_required": "Review required",
        "local": "Local",
    }
    return known.get(text.casefold(), text.title()) if text else "—"


def _value(record: object, name: str, default: object = None) -> object:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _field(
    label: str,
    *,
    value: str = "",
    placeholder: str = "",
    password: bool = False,
    key: str | None = None,
    on_change=None,
) -> ft.Control:
    control = ft.TextField(
        value=value,
        password=password,
        can_reveal_password=password,
        key=key,
        on_change=on_change,
        **field_input_style(placeholder=placeholder),
    )
    return Field(label, control=control, expand=True)


def settings_page(page: ft.Page | None, state: AppState | None) -> PageView:
    settings_bundle, migration_issues = load_settings_bundle_with_issues(ROOT)
    config = state.snapshot.config if state is not None and getattr(state, "snapshot", None) is not None else None
    if config is None:
        config = load_config()

    selected: dict[str, object] = {
        "output_currency": settings_bundle.controls.output_currency,
        "risk_profile": settings_bundle.controls.risk_profile,
        "horizon": settings_bundle.controls.horizon,
        "analysis_depth": (
            getattr(state, "analysis_depth", None)
            if getattr(state, "analysis_depth", None) in ANALYSIS_DEPTHS
            else settings_bundle.controls.analysis_depth
        ),
        "evidence_mode": getattr(state, "evidence_mode", "default"),
    }
    status_note = Note("No settings action has run in this session.")
    status_details = ft.Text("")
    preview_table = ft.Container(
        content=DataTable(
            [TableColumn("setting", "Setting"), TableColumn("previous", "Previous"), TableColumn("proposed", "Proposed")],
            [],
            empty_title="Unavailable",
            empty_reason="Preview changes to see the setting-by-setting policy impact.",
        ),
        expand=True,
    )
    preview_note = Note("Preview shows whether a new analysis/selection run is required: Unavailable until settings are previewed.")
    last_preview: dict[str, str] = {}
    preview_details = ft.Text("")

    def update_page() -> None:
        if page is not None:
            page.update()

    def candidate_bundle():
        selected_scopes = tuple(scope for scope, toggle in scope_toggles.items() if toggle.data.get("on"))
        controls = settings_bundle.controls.model_copy(
            update={
                "output_currency": str(selected["output_currency"]),
                "asset_scopes": selected_scopes,
                "risk_profile": str(selected["risk_profile"]),
                "horizon": str(selected["horizon"]),
                "analysis_depth": str(selected["analysis_depth"]),
            }
        )
        return settings_bundle.model_copy(update={"controls": controls})

    def preview(_event: object) -> None:
        try:
            candidate = candidate_bundle()
            report = preview_settings(candidate, expected_revision=settings_bundle.revision, root=ROOT)
            last_preview["revision"] = report.after_revision
            current_values = settings_bundle.controls.model_dump()
            next_values = candidate.controls.model_dump()
            changes = [
                {
                    "setting": _label(name),
                    "previous": _display_setting(current_values.get(name)),
                    "proposed": _display_setting(next_values.get(name)),
                }
                for name in report.changed_fields
            ]
            preview_table.content = DataTable(
                [TableColumn("setting", "Setting"), TableColumn("previous", "Previous"), TableColumn("proposed", "Proposed")],
                changes,
                empty_title="No changes",
                empty_reason="The current choices do not change the saved settings.",
                expand=True,
            )
            preview_note.value = f"Preview shows whether a new analysis/selection run is required: {'yes' if report.creates_new_run else 'no'}"
            preview_details.value = (
                f"Changed fields: {report.changed_fields}; before revision: {report.before_revision}; "
                f"after revision: {report.after_revision}; effects: {report.run_effects}; warnings: {report.warnings}"
            )
            status_note.value = "Settings preview is ready."
            status_details.value = ""
        except SettingsError as exc:
            last_preview.clear()
            status_note.value = "Settings preview needs review."
            status_details.value = f"{exc.code}: {exc.message}"
        except Exception as exc:
            last_preview.clear()
            status_note.value = "Settings preview could not be completed."
            status_details.value = f"{type(exc).__name__}: {exc}"
        update_page()

    def save(_event: object) -> None:
        nonlocal settings_bundle
        try:
            candidate = candidate_bundle()
            fresh_preview = preview_settings(candidate, expected_revision=settings_bundle.revision, root=ROOT)
            if last_preview.get("revision") != fresh_preview.after_revision:
                raise SettingsError("SETTINGS_MIGRATION_REVIEW_REQUIRED", "preview the current edits before saving")
            result = save_settings(candidate, expected_revision=settings_bundle.revision, root=ROOT)
            if state is not None:
                state.snapshot.config = load_config()
                state.analysis_depth = str(selected["analysis_depth"])
            settings_bundle = load_settings_bundle(ROOT)
            status_note.value = "Settings saved atomically. No analysis, provider, model or execution workflow was started."
            status_details.value = f"Settings version: {result.settings_version}; revision: {result.revision}; snapshot path: {result.snapshot_path}"
            last_preview.clear()
        except Exception as exc:
            status_note.value = "Settings were not saved."
            status_details.value = f"{type(exc).__name__}: {exc}"
        update_page()

    def select_output_currency(value: str) -> None:
        selected["output_currency"] = value

    currency_field = Field(
        "Output currency",
        options=OUTPUT_CURRENCIES,
        value=str(selected["output_currency"]),
        on_change=lambda value: select_output_currency(value),
        key="settings.output-currency",
        expand=True,
    )

    risk_labels = tuple(_RISK_LABELS.get(value, _label(value)) for value in RISK_PROFILES)
    risk_to_value = dict(zip(risk_labels, RISK_PROFILES, strict=True))
    selected_risk_label = _RISK_LABELS.get(str(selected["risk_profile"]), _label(selected["risk_profile"]))
    risk_control = Segmented(
        risk_labels,
        selected_risk_label,
        on_change=lambda value: selected.__setitem__("risk_profile", risk_to_value[value]),
        key="settings.risk-profile",
    )
    horizon_labels = tuple(_HORIZON_LABELS[value] for value in HORIZONS)
    horizon_to_value = dict(zip(horizon_labels, HORIZONS, strict=True))
    selected_horizon_label = _HORIZON_LABELS[str(selected["horizon"])]
    horizon_control = Segmented(
        horizon_labels,
        selected_horizon_label,
        on_change=lambda value: selected.__setitem__("horizon", horizon_to_value[value]),
        key="settings.horizon",
    )
    depth_labels = tuple(_DEPTH_LABELS[value] for value in ANALYSIS_DEPTHS)
    depth_to_value = dict(zip(depth_labels, ANALYSIS_DEPTHS, strict=True))
    selected_depth_label = _DEPTH_LABELS[str(selected["analysis_depth"])]
    depth_control = Segmented(
        depth_labels,
        selected_depth_label,
        on_change=lambda value: selected.__setitem__("analysis_depth", depth_to_value[value]),
        key="settings.analysis-depth",
    )
    scope_toggles = {
        scope: Toggle(
            on=scope in settings_bundle.controls.asset_scopes,
        )
        for scope in ASSET_SCOPES
    }
    scope_controls = ft.Column(
        [
            Note("Asset scope"),
            ft.Row(
                [
                    ft.Column([Note(scope.title()), toggle], spacing=8, tight=True)
                    for scope, toggle in scope_toggles.items()
                ],
                spacing=16,
                wrap=True,
            ),
        ],
        spacing=8,
        key="settings.asset-scopes",
    )
    evidence_items = ("Compact", "Default", "Advanced")
    evidence_selected = _label(selected["evidence_mode"])
    if evidence_selected not in evidence_items:
        evidence_selected = "Default"
    evidence_control = Segmented(
        evidence_items,
        evidence_selected,
        on_change=lambda value: state.set_evidence_mode(value.casefold()) if state is not None else None,
    )

    settings_version = Note(f"Settings version {settings_bundle.settings_version}", key="settings.version")
    if migration_issues:
        migration_note = Note("Some legacy settings need manual review before they can be used.")
        migration_details = ft.Text(", ".join(f"{issue.code} ({issue.field})" for issue in migration_issues))
    else:
        migration_note = Note("Saved settings are loaded from the local settings bundle.")
        migration_details = ft.Text("")

    settings_details = Disclosure(
        "Settings revision and policy details",
        ft.Column(
            [
                ft.Text(f"Revision: {settings_bundle.revision}"),
                ft.Text("execution_allowed=false"),
                migration_details,
            ],
            spacing=8,
        ),
    )
    product_policy = load_product_governance()
    authority_matrix = load_authority_matrix()
    product_details_text = (
        f"Product: {product_policy.policy.product.canonical_name}; ADR: {authority_matrix.policy.adr_id}; "
        f"active stage: Research; authority checksum: {authority_matrix.checksum}; "
        f"capabilities: {authority_matrix.policy.capabilities}; execution_allowed=false"
        if product_policy.policy is not None and authority_matrix.policy is not None
        else "Product authority contract or capability matrix is unavailable; execution_allowed=false."
    )

    def _display_setting(value: object) -> str:
        if value is None:
            return "—"
        if isinstance(value, (tuple, list)):
            return ", ".join(_label(item) for item in value) or "—"
        return _label(value)

    settings_centre = GlassCard(
        "Settings centre",
        note=f"Settings v{settings_bundle.settings_version}",
        body=ft.Column(
            [
                ft.Row([currency_field], spacing=12),
                ft.Column([Note("Risk profile"), risk_control], spacing=8),
                ft.Column([Note("Target horizon"), horizon_control], spacing=8),
                ft.Column([Note("Analysis depth"), depth_control], spacing=8),
                ft.Column([Note("Evidence mode"), evidence_control], spacing=8),
                scope_controls,
                Button.secondary("Preview changes", on_click=preview, key="settings.preview"),
                Button.primary("Save settings", on_click=save, key="settings.save"),
                settings_version,
                migration_note,
                status_note,
                Note("Edit locally, preview the complete policy impact, then save one atomic settings version."),
                Note("Any semantic change invalidates reuse of an existing run manifest."),
                Note("Execution authority remains off."),
                Note("Credential values never enter the settings bundle, logs or exports."),
                settings_details,
                Disclosure("Product scope and authority", product_details_text, expanded=False),
            ],
            spacing=12,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    change_preview = GlassCard(
        "Change preview",
        note="policy impact",
        body=ft.Column(
            [
                preview_note,
                preview_table,
                Note("Credential values never enter this bundle, logs or exports."),
                Disclosure("Preview revision and effects", preview_details),
                Disclosure("Settings action details", status_details),
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )

    if config is not None:
        limits = config.risks.portfolio_limits
        guardrail_rows = [
            {"limit": "Max single ETF weight", "value": format_percent(limits.max_single_etf_weight, decimals=0, unavailable="—")},
            {"limit": "Max sector weight", "value": format_percent(limits.max_sector_weight, decimals=0, unavailable="—")},
            {"limit": "Max region weight", "value": format_percent(limits.max_region_weight, decimals=0, unavailable="—")},
            {"limit": "Max theme weight", "value": format_percent(limits.max_theme_weight, decimals=0, unavailable="—")},
            {"limit": "Max monthly turnover", "value": format_percent(limits.max_monthly_turnover, decimals=0, unavailable="—")},
        ]
        target_rows = [
            {
                "instrument": instrument,
                "target": format_percent(position.target_weight, decimals=0, unavailable="—"),
                "bands": f"{format_percent(position.soft_band, decimals=0, unavailable='—')} / {format_percent(position.hard_band, decimals=0, unavailable='—')}",
            }
            for instrument, position in config.targets.positions.items()
        ]
    else:
        guardrail_rows = []
        target_rows = []

    guardrails = GlassCard(
        "Guardrail settings",
        note="allocation caps are context",
        body=ft.Column(
            [
                DataTable(
                    [TableColumn("limit", "Limit"), TableColumn("value", "Value", numeric=True)],
                    guardrail_rows,
                    empty_title="Unavailable",
                    empty_reason="Guardrail values are unavailable without a loaded configuration.",
                    expand=True,
                ),
                Note("Data-quality failures still block analysis; allocation caps are displayed as context."),
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )
    portfolio_targets = GlassCard(
        "Portfolio context targets",
        note="drift context only",
        body=ft.Column(
            [
                DataTable(
                    [
                        TableColumn("instrument", "Instrument", flex=2),
                        TableColumn("target", "Context target", numeric=True),
                        TableColumn("bands", "Drift bands", numeric=True),
                    ],
                    target_rows,
                    empty_title="Unavailable",
                    empty_reason="Portfolio context targets are unavailable without a loaded configuration.",
                    expand=True,
                ),
                Note("Used for drift context only; they do not override stock or ETF evidence scores."),
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )

    provider_items = tuple(config.data_providers.providers.items()) if config is not None else ()
    provider_rows = [
        {
            "provider": _label(name),
            "active": _label(section.active_provider or "none"),
            "base_url": "Configured" if section.base_url else "Not configured",
        }
        for name, section in provider_items
    ]
    provider_names = sorted(
        {
            canonical_provider_account(name)
            for name, section in provider_items
            if name not in {"prices", "fx", "etf_metadata", "etf_holdings"}
        }
        | {
            canonical_provider_account(section.active_provider)
            for _, section in provider_items
            if (section.active_provider or "none").strip().casefold() not in {"", "none"}
        }
    )
    provider_display = tuple(_label(name) for name in provider_names) or ("Unavailable",)
    provider_by_label = dict(zip(provider_display, provider_names, strict=False))
    credential_provider_id = {"value": provider_names[0] if provider_names else ""}

    def edit_credential(_event: object) -> None:
        credential_note.value = "Credential values are never shown after save."
        update_page()

    credential_provider = Field(
        "Provider",
        options=provider_display,
        value=provider_display[0],
        on_change=lambda value: select_credential_provider(value),
        key="settings.credential-provider",
        expand=True,
    )
    credential_value = ft.TextField(
        password=True,
        can_reveal_password=False,
        key="settings.credential-value",
        on_change=edit_credential,
        **field_input_style(placeholder="Stored with Windows protection; never included in settings exports."),
    )
    credential_field = Field("Provider credential", control=credential_value, expand=True)
    vault_status = CredentialVault().status()
    credential_note = Note(
        "Credential vault unavailable; existing environment values remain a fallback."
        if vault_status.get("status") == "unavailable"
        else "No credential action has run in this session.",
        key="settings.credential-status",
    )
    credential_details = ft.Text(str(vault_status.get("reason") or ""))
    credential_recovery = Note(
        "Credentials can be recovered only by the same Windows user profile. Re-enter credentials if a backup is restored under another profile.",
        key="settings.credential-recovery",
    )
    credential_delete_pending = {"value": False}

    def select_credential_provider(value: str) -> None:
        credential_provider_id["value"] = provider_by_label.get(value, "")
        credential_value.value = ""
        credential_note.value = "Enter a credential to save or remove the selected provider value."
        update_page()

    def save_provider_credential(_event: object) -> None:
        provider_name = credential_provider_id["value"]
        secret = credential_value.value or ""
        try:
            if not provider_name:
                raise CredentialVaultError("No provider definition is available.")
            CredentialVault().set(canonical_provider_account(provider_name), secret)
            credential_note.value = "Credential saved in the Windows-protected vault; cached provider probes were invalidated."
            credential_details.value = ""
        except CredentialVaultError as exc:
            credential_note.value = "Credential could not be saved safely."
            credential_details.value = str(exc)
        except Exception as exc:
            credential_note.value = "Credential could not be saved safely. Check the Windows vault status and try again."
            credential_details.value = f"{type(exc).__name__}: {exc}"
        finally:
            credential_value.value = ""
        update_page()

    def delete_provider_credential(_event: object) -> None:
        provider_name = credential_provider_id["value"]
        if not credential_delete_pending["value"]:
            credential_delete_pending["value"] = True
            credential_note.value = "Select Delete credential again to confirm removal."
            update_page()
            return
        credential_delete_pending["value"] = False
        try:
            if not provider_name:
                raise CredentialVaultError("No provider definition is available.")
            CredentialVault().delete(canonical_provider_account(provider_name))
            credential_note.value = "Credential removed from the Windows-protected vault; cached provider probes were invalidated."
            credential_details.value = ""
        except CredentialVaultError as exc:
            credential_note.value = "Credential could not be removed safely."
            credential_details.value = str(exc)
        except Exception as exc:
            credential_note.value = "Credential could not be removed safely. Check the Windows vault status and try again."
            credential_details.value = f"{type(exc).__name__}: {exc}"
        update_page()

    provider_details = ft.Column(
        [ft.Text(f"{name}: active={section.active_provider or 'none'}; base_url={section.base_url or 'not configured'}") for name, section in provider_items]
        or [Note("Provider definitions are unavailable without a loaded configuration.")],
        spacing=8,
    )
    data_providers = GlassCard(
        "Data providers",
        note="local definitions and protected credentials",
        body=ft.Column(
            [
                DataTable(
                    [TableColumn("provider", "Provider"), TableColumn("active", "Active source"), TableColumn("base_url", "Base URL")],
                    provider_rows,
                    empty_title="Unavailable",
                    empty_reason="Provider definitions are unavailable without a loaded configuration.",
                    expand=True,
                ),
                ft.Row([credential_provider, credential_field], spacing=12),
                ft.Row(
                    [
                        Button.primary("Save credential", on_click=save_provider_credential, key="settings.credential-save"),
                        ft.TextButton("Delete credential", on_click=delete_provider_credential, key="settings.credential-delete"),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                credential_note,
                Note("Stored with Windows protection; never included in settings exports."),
                credential_recovery,
                Disclosure("Credential vault details", credential_details),
                Disclosure("Provider definitions and URLs", provider_details),
            ],
            spacing=12,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )

    model_items = tuple(config.models.models.items()) if config is not None else ()
    model_rows = []
    model_details = []
    for model_name, model_settings in model_items:
        enabled = bool(_value(model_settings, "enabled", False))
        mode = _value(model_settings, "mode")
        backend = _value(model_settings, "backend")
        model_path = _value(model_settings, "model_path", _value(model_settings, "path"))
        model_rows.append(
            {
                "model": _label(model_name),
                "enabled": Tag("Enabled" if enabled else "Disabled", "ok" if enabled else "mute"),
                "mode": _label(mode),
                "backend": _label(backend),
                "path": "Configured" if model_path else "—",
            }
        )
        model_details.append(ft.Text(f"{model_name}: path={model_path or 'unavailable'}; settings={model_settings}"))
    model_settings_card = GlassCard(
        "Model settings",
        note="local optional evidence sources",
        body=ft.Column(
            [
                DataTable(
                    [
                        TableColumn("model", "Model"),
                        TableColumn("enabled", "Enabled"),
                        TableColumn("mode", "Mode"),
                        TableColumn("backend", "Backend"),
                        TableColumn("path", "Model path"),
                    ],
                    model_rows,
                    empty_title="Unavailable",
                    empty_reason="Model settings are unavailable without a loaded configuration.",
                    expand=True,
                ),
                Disclosure("Model paths and full settings", ft.Column(model_details or [Note("Model paths are unavailable.")], spacing=8)),
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )

    universe_items = tuple(config.universe.etfs) if config is not None else ()
    universe_rows = [
        {
            "instrument": f"{item.id} · {item.name}",
            "type": _label(getattr(item, "model_extra", {}).get("instrument_type", item.asset_class)),
            "status": Tag("Enabled" if item.enabled else "Disabled", "ok" if item.enabled else "mute"),
        }
        for item in universe_items
    ]
    universe_manager = GlassCard(
        "Universe manager",
        note="validated local CRUD",
        body=ft.Column(
            [
                ft.Row(
                    [
                        Button.secondary("Open Universe manager", on_click=lambda _event: page.go("/universe") if page is not None else None, key="settings.open-universe"),
                        Button.secondary("Open first-run setup", on_click=lambda _event: page.go("/onboarding") if page is not None else None, key="settings.open-onboarding"),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                Note("Configuration saves show pending refresh only; they never trigger refresh, scoring or model calls."),
            ],
            spacing=12,
        ),
        expand=True,
    )
    primary_universe = GlassCard(
        "Primary tier universe",
        note="configured local instruments",
        body=DataTable(
            [TableColumn("instrument", "Instrument", flex=2), TableColumn("type", "Asset type"), TableColumn("status", "Status")],
            universe_rows,
            empty_title="Unavailable",
            empty_reason="The primary universe is unavailable without a loaded configuration.",
            expand=True,
        ),
        expand=True,
    )
    secondary_groups = GlassCard(
        "Secondary and Sparebanken groups",
        note="separate candidate groups",
        body=ft.Column(
            [
                Note("Secondary ETFs and stocks remain separate from the primary universe."),
                Note("Unknown Sparebanken instruments remain marked for verification."),
                Disclosure("Candidate source details", "data/raw/trade_candidates/yahoo_trade_candidates_2026-07-09.csv"),
            ],
            spacing=12,
        ),
        expand=True,
    )
    asset_support = GlassCard(
        "Asset support matrix",
        note="daily evidence only",
        body=DataTable(
            [TableColumn("asset", "Asset class"), TableColumn("support", "Support"), TableColumn("note", "Review note")],
            [
                {"asset": "Daily stock and ETF data", "support": Tag("Eligible", "ok"), "note": "Score eligible"},
                {"asset": "Intraday data", "support": Tag("Research only", "warn"), "note": "Not score eligible"},
                {"asset": "Futures and options", "support": Tag("Unsupported", "bad"), "note": "Not eligible"},
                {"asset": "Leveraged and inverse", "support": Tag("Manual review", "warn"), "note": "Review before use"},
            ],
            expand=True,
        ),
        expand=True,
    )

    version_metadata_path = ROOT / "pyproject.toml"
    version_metadata = f"Available at {version_metadata_path}" if version_metadata_path.is_file() else "Unavailable: project version metadata is missing."
    changelog_excerpt = read_changelog_excerpt(ROOT)
    rebuild_timestamp = read_rebuild_timestamp(ROOT)
    release_metadata = GlassCard(
        "Release and data metadata",
        note=f"App version {APP_VERSION}",
        body=ft.Column(
            [
                Note(f"App version: {APP_VERSION}"),
                Note(f"Last rebuild: {rebuild_timestamp or 'Unavailable'}"),
                Disclosure(
                    "Version metadata, data root and changelog",
                    ft.Column(
                        [
                            ft.Text(version_metadata),
                            ft.Text(f"Data root: {DATA_DIR}"),
                            ft.Text(f"Last rebuild timestamp: {rebuild_timestamp}"),
                            ft.Text(f"Changelog excerpt: {changelog_excerpt}"),
                            ft.Text("ISSUE-0044 update plan: build and verify the Windows package, back up local data/configuration, run restore/startup checks, and retain release metadata."),
                        ],
                        spacing=8,
                    ),
                ),
            ],
            spacing=12,
        ),
        expand=True,
    )
    release_evidence = describe_release_evidence(ROOT)
    offline_update = GlassCard(
        "Offline update verification",
        note="local-only verification",
        body=ft.Column(
            [
                Note("Unsigned, tampered or unsafe update bundles are rejected before staging."),
                Note("Network retrieval and live execution are disabled by policy."),
                Disclosure(
                    "Release evidence and notices",
                    ft.Text(
                        f"Verification: {release_evidence.get('verification')}; version: {release_evidence.get('version')}; "
                        f"notices: {release_evidence.get('notices')}; notices path: {release_evidence.get('notices_path')}"
                    ),
                ),
            ],
            spacing=12,
        ),
        expand=True,
    )
    legal_report = legal_terms_report(ROOT)
    legal_terms = GlassCard(
        "Legal terms, disclaimers and jurisdiction",
        note="local terms and source permissions",
        body=ft.Column(
            [
                Note("Research and education only. Not financial or tax advice. No broker execution or order transmission."),
                Note("Restricted sources are excluded from standard audit export unless the registry permits attribution."),
                Disclosure(
                    "Legal terms registry status and checksum",
                    ft.Text(
                        f"Status: {legal_report.get('status')}; review status: {legal_report.get('review_status')}; "
                        f"checksum: {legal_report.get('registry_sha256')}"
                    ),
                ),
            ],
            spacing=12,
        ),
        expand=True,
    )
    supply_chain_report = supply_chain_intake_report(ROOT)
    supply_chain = GlassCard(
        "Third-party intake and upstream governance",
        note="local intake records",
        body=ft.Column(
            [
                Note("Copied third-party code requires an approved intake record."),
                Note("Upstream and licence review is recorded before release."),
                Disclosure(
                    "Supply-chain status, counts, checksum and notices",
                    ft.Text(
                        f"Status: {supply_chain_report.get('status')}; review: {supply_chain_report.get('review_status')}; "
                        f"components: {supply_chain_report.get('component_count')}; locked dependencies: {supply_chain_report.get('dependency_count')}; "
                        f"checksum: {supply_chain_report.get('registry_sha256')}; notices: {supply_chain_report.get('third_party_notices')}"
                    ),
                ),
            ],
            spacing=12,
        ),
        expand=True,
    )
    config_folder_status = Note("Configuration folder is available in the local app directory.")

    def open_config_folder(_event: object) -> None:
        opener = getattr(os, "startfile", None)
        if callable(opener):
            try:
                opener(str(CONFIG_DIR))
                config_folder_status.value = "Configuration folder opened."
            except OSError:
                config_folder_status.value = "Configuration folder could not be opened."
        update_page()

    config_folder = GlassCard(
        "Config folder",
        note="local YAML and JSON settings",
        body=ft.Column(
            [
                Button.secondary("Open folder", on_click=open_config_folder, key="settings.open-config-folder"),
                config_folder_status,
                Disclosure("Configuration folder path", str(CONFIG_DIR)),
            ],
            spacing=12,
        ),
        expand=True,
    )

    if config is not None:
        status_note.value = "Local settings and configuration are ready."
    else:
        status_note.value = "Unavailable: no application configuration is loaded."

    general_view = ft.Column(
        [
            ft.Row([settings_centre, change_preview], spacing=24),
            ft.Row([guardrails, portfolio_targets], spacing=24),
        ],
        spacing=24,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    data_view = ft.Column(
        [
            ft.Row([data_providers, model_settings_card], spacing=24),
            ft.Row([universe_manager, primary_universe], spacing=24),
            ft.Row([secondary_groups, asset_support], spacing=24),
            ft.Row([config_folder], spacing=24),
        ],
        spacing=24,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    backup_archive = ROOT / "exports" / "storage" / "cockpit-encrypted.backup"
    recovery_key = ft.TextField(
        password=True,
        can_reveal_password=True,
        **field_input_style(placeholder="At least 16 characters; never logged or exported"),
    )
    recovery_key_field = Field("Recovery key", control=recovery_key, expand=True)
    deletion_confirmation = ft.TextField(
        password=True,
        **field_input_style(placeholder="Type DELETE PRIVATE DATA to confirm"),
    )
    deletion_field = Field(
        "Type DELETE PRIVATE DATA to remove local private notes",
        control=deletion_confirmation,
        expand=True,
    )
    privacy_note = Note("No privacy or recovery action has run in this session.")
    privacy_details = ft.Text("")

    def set_privacy_status(message: str, details: str = "") -> None:
        privacy_note.value = message
        privacy_details.value = details
        update_page()

    def create_backup(_event: object) -> None:
        try:
            manifest = create_encrypted_backup([DATA_DIR, CONFIG_DIR], backup_archive, recovery_key.value or "")
            set_privacy_status("Encrypted backup created.", f"Archive: {manifest.archive}; files: {manifest.checksums}; excluded: {manifest.excluded}")
        except Exception as exc:
            set_privacy_status("Backup creation failed safely.", f"{type(exc).__name__}: {exc}")

    def validate_backup(_event: object) -> None:
        preview = validate_encrypted_restore(backup_archive, recovery_key.value or "") if backup_archive.is_file() else None
        if preview is None:
            set_privacy_status("Backup validation is unavailable because no backup archive is present.", str(backup_archive))
        elif preview.valid:
            set_privacy_status("Backup validated; no data was restored.", f"Entries: {preview.entries}")
        else:
            set_privacy_status("Backup validation failed safely.", f"Validation detail: {preview.errors}")

    def recovery_drill(_event: object) -> None:
        try:
            drill = run_disaster_recovery_drill(
                [DATA_DIR, CONFIG_DIR],
                ROOT / "exports" / "storage" / "recovery-drill",
                recovery_key=recovery_key.value or "",
            )
            set_privacy_status(
                "Recovery drill completed." if drill.ok else "Recovery drill did not complete.",
                f"Restored entries: {drill.restored_files}; archive: {drill.archive}; errors: {drill.errors}",
            )
        except Exception as exc:
            set_privacy_status("Recovery drill failed safely.", f"{type(exc).__name__}: {exc}")

    def delete_private(_event: object) -> None:
        try:
            deleted = delete_private_data(ROOT, confirmation=deletion_confirmation.value or "")
            set_privacy_status("Private data deletion completed.", f"Deleted entries: {deleted}")
        except Exception as exc:
            set_privacy_status("Private data was not deleted.", f"{type(exc).__name__}: {exc}")

    privacy_view = ft.Column(
        [
            GlassCard(
                "Privacy, backup and recovery",
                note="local encrypted backups; no credential export",
                body=ft.Column(
                    [
                        Note("Private fields, credentials, transient logs and caches are excluded from encrypted backups by default."),
                        recovery_key_field,
                        ft.Row(
                            [
                                Button.secondary("Create encrypted backup", on_click=create_backup, key="settings.backup-create"),
                                Button.secondary("Validate latest backup", on_click=validate_backup, key="settings.backup-validate"),
                                Button.secondary("Run recovery drill", on_click=recovery_drill, key="settings.recovery-drill"),
                            ],
                            spacing=12,
                            wrap=True,
                        ),
                        Note("Backup destination is stored locally."),
                        deletion_field,
                        ft.TextButton("Delete private data", on_click=delete_private, key="settings.delete-private"),
                        privacy_note,
                        Disclosure("Backup destination and recovery details", ft.Column([ft.Text(str(backup_archive)), privacy_details], spacing=8)),
                    ],
                    spacing=16,
                ),
            ),
        ],
        spacing=24,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    about_view = ft.Column(
        [
            ft.Row([release_metadata, offline_update], spacing=24),
            ft.Row([legal_terms, supply_chain], spacing=24),
            ft.Row(
                [GlassCard("Settings status", body=ft.Column([status_note, Disclosure("Settings action details", status_details)], spacing=12))],
                spacing=24,
            ),
        ],
        spacing=24,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    views = {"General": general_view, "Data & models": data_view, "Privacy": privacy_view, "About": about_view}
    body_slot = ft.Container(content=general_view, expand=True)

    def select_view(value: str) -> None:
        body_slot.content = views[value]
        update_page()

    body = ft.Column([body_slot], spacing=0, expand=True)
    return PageView(
        chrome=PageChrome(
            title="Settings",
            subtitle="Local preferences, credentials and release metadata · no provider, broker or live authority",
            segment_groups=(
                SegmentGroup(
                    "settings",
                    ("General", "Data & models", "Privacy", "About"),
                    "General",
                    on_change=select_view,
                ),
            ),
        ),
        body=body,
    )
