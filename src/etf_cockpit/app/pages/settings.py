from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    create_encrypted_backup,
    run_disaster_recovery_drill,
    validate_encrypted_restore,
    delete_private_data,
    legal_terms_report,
    supply_chain_intake_report,
)
from etf_cockpit.application.settings import (
    ANALYSIS_DEPTHS,
    ASSET_SCOPES,
    HORIZONS,
    OUTPUT_CURRENCIES,
    RISK_PROFILES,
    SettingsError,
    load_settings_bundle,
    load_settings_bundle_with_issues,
    preview_settings,
    save_settings,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.core.constants import APP_VERSION
from etf_cockpit.core.paths import CONFIG_DIR, DATA_DIR, ROOT
from etf_cockpit.core.secure_update import describe_release_evidence
from etf_cockpit.governance.product_scope import load_authority_matrix, load_product_governance


def settings_page(_page: ft.Page, state: AppState) -> ft.Control:
    config = state.snapshot.config
    product_policy = load_product_governance()
    authority_matrix = load_authority_matrix()
    target_lines = [f"{etf_id}: context target {pos.target_weight:.1%}, drift bands {pos.soft_band:.1%}/{pos.hard_band:.1%}" for etf_id, pos in config.targets.positions.items()]
    model_lines = [f"{name}: {settings}" for name, settings in config.models.models.items()]
    status_text = ft.Text(state.last_message, color=theme.MUTED, selectable=True)
    version_metadata_path = ROOT / "pyproject.toml"
    version_status = f"available at {version_metadata_path}" if version_metadata_path.is_file() else "unavailable (missing pyproject.toml)"
    changelog_path = ROOT / "CHANGELOG.md"
    changelog_status = f"available at {changelog_path}" if changelog_path.is_file() else "unavailable (missing CHANGELOG.md)"
    release_evidence = describe_release_evidence(ROOT)
    legal_report = legal_terms_report(ROOT)
    supply_chain_report = supply_chain_intake_report(ROOT)
    rebuild_timestamp = "available through the normal Windows package output"
    issue_0044_update_plan = (
        "ISSUE-0044 packaged-app update workflow: build the Windows package, record the release version and SHA-256 checksum, "
        "back up local data/configs, install the package, run a restore/startup smoke check, then retain the changelog and rebuild timestamp."
    )
    backup_archive = ROOT / "exports" / "storage" / "cockpit-encrypted.backup"
    recovery_key = ft.TextField(
        label="Recovery key",
        password=True,
        can_reveal_password=True,
        hint_text="At least 16 characters; never logged or exported",
        key="settings.recovery-key",
        width=360,
    )
    privacy_status = ft.Text("No privacy or recovery action has run in this session.", color=theme.MUTED, selectable=True)
    deletion_confirmation = ft.TextField(
        label="Type DELETE PRIVATE DATA to remove local private notes",
        password=True,
        key="settings.delete-private-confirmation",
        width=360,
    )

    def refresh_privacy_status() -> None:
        if _page is not None:
            _page.update()

    def create_backup(_event: ft.ControlEvent) -> None:
        try:
            manifest = create_encrypted_backup([DATA_DIR, CONFIG_DIR], backup_archive, recovery_key.value or "")
            privacy_status.value = f"Encrypted backup created: {manifest.archive} | files={len(manifest.checksums)} | excluded={len(manifest.excluded)}"
            privacy_status.color = theme.GREEN
        except Exception as exc:
            privacy_status.value = f"Backup failed safely: {type(exc).__name__}: {exc}"
            privacy_status.color = theme.RED
        refresh_privacy_status()

    def validate_backup(_event: ft.ControlEvent) -> None:
        preview = validate_encrypted_restore(backup_archive, recovery_key.value or "") if backup_archive.is_file() else None
        if preview is None:
            privacy_status.value = f"Backup unavailable: {backup_archive}"
            privacy_status.color = theme.AMBER
        elif preview.valid:
            privacy_status.value = f"Backup validated: {len(preview.entries)} files; no data was restored."
            privacy_status.color = theme.GREEN
        else:
            privacy_status.value = f"Backup validation failed safely: {'; '.join(preview.errors)}"
            privacy_status.color = theme.RED
        refresh_privacy_status()

    def recovery_drill(_event: ft.ControlEvent) -> None:
        try:
            drill = run_disaster_recovery_drill([DATA_DIR, CONFIG_DIR], ROOT / "exports" / "storage" / "recovery-drill", recovery_key=recovery_key.value or "")
            privacy_status.value = f"Recovery drill {'passed' if drill.ok else 'failed'}: {drill.restored_files} files restored | {drill.archive}"
            if drill.errors:
                privacy_status.value += f" | {'; '.join(drill.errors)}"
            privacy_status.color = theme.GREEN if drill.ok else theme.RED
        except Exception as exc:
            privacy_status.value = f"Recovery drill failed safely: {type(exc).__name__}: {exc}"
            privacy_status.color = theme.RED
        refresh_privacy_status()

    def delete_private(_event: ft.ControlEvent) -> None:
        try:
            deleted = delete_private_data(ROOT, confirmation=deletion_confirmation.value or "")
            privacy_status.value = f"Private data deletion complete: {len(deleted)} files removed from data/private/."
            privacy_status.color = theme.GREEN
        except Exception as exc:
            privacy_status.value = f"Private data was not deleted: {type(exc).__name__}: {exc}"
            privacy_status.color = theme.AMBER
        refresh_privacy_status()
    settings_bundle, migration_issues = load_settings_bundle_with_issues(ROOT)
    migration_message = ""
    if migration_issues:
        issue_summary = ", ".join(f"{issue.code} ({issue.field})" for issue in migration_issues)
        migration_message = f"Legacy settings require manual review: {issue_summary}. "
    settings_status = ft.Text(
        migration_message + "Edit locally, preview the complete policy impact, then save one atomic settings version.",
        color=theme.MUTED,
        selectable=True,
    )
    output_currency = ft.Dropdown(
        label="Output currency",
        value=settings_bundle.controls.output_currency,
        options=[ft.dropdown.Option(item) for item in OUTPUT_CURRENCIES],
        key="settings.output-currency",
        width=180,
        dense=True,
    )
    scope_checks = {
        scope: ft.Checkbox(label=scope.title(), value=scope in settings_bundle.controls.asset_scopes)
        for scope in ASSET_SCOPES
    }
    asset_scopes = ft.Column(
        [ft.Text("Asset scope", color=theme.MUTED, size=11), ft.Row(list(scope_checks.values()), wrap=True)],
        key="settings.asset-scopes",
        spacing=2,
    )
    risk_profile = ft.Dropdown(
        label="Risk profile",
        value=settings_bundle.controls.risk_profile,
        options=[ft.dropdown.Option(item) for item in RISK_PROFILES],
        key="settings.risk-profile",
        width=220,
        dense=True,
    )
    horizon = ft.Dropdown(
        label="Target horizon",
        value=settings_bundle.controls.horizon,
        options=[ft.dropdown.Option(item) for item in HORIZONS],
        key="settings.horizon",
        width=180,
        dense=True,
    )
    analysis_depth = ft.Dropdown(
        label="Analysis depth",
        value=settings_bundle.controls.analysis_depth,
        options=[ft.dropdown.Option(item) for item in ANALYSIS_DEPTHS],
        key="settings.analysis-depth",
        width=190,
        dense=True,
    )
    version_text = ft.Text(
        f"Settings v{settings_bundle.settings_version} · {settings_bundle.revision[:16]}",
        key="settings.version",
        color=theme.MUTED,
        selectable=True,
    )
    last_preview: dict[str, str] = {}

    def candidate_bundle():
        selected_scopes = tuple(scope for scope, checkbox in scope_checks.items() if checkbox.value)
        controls = settings_bundle.controls.model_copy(
            update={
                "output_currency": output_currency.value or "",
                "asset_scopes": selected_scopes,
                "risk_profile": risk_profile.value or "",
                "horizon": horizon.value or "",
                "analysis_depth": analysis_depth.value or "",
            }
        )
        return settings_bundle.model_copy(update={"controls": controls})

    def refresh_settings_status() -> None:
        if _page is not None:
            _page.update()

    def preview(_event: ft.ControlEvent) -> None:
        try:
            report = preview_settings(candidate_bundle(), expected_revision=settings_bundle.revision, root=ROOT)
            last_preview["revision"] = report.after_revision
            changed = ", ".join(report.changed_fields) or "no semantic fields"
            settings_status.value = (
                f"Preview valid: {changed}. "
                f"{'A new analysis/selection run is required.' if report.creates_new_run else 'No new run is required.'} "
                "Currency/risk/depth effects remain explicitly unavailable until ISSUE-0173/0174/0175."
            )
            settings_status.color = theme.GREEN
        except SettingsError as exc:
            last_preview.clear()
            settings_status.value = f"Preview rejected: {exc}"
            settings_status.color = theme.RED
        refresh_settings_status()

    def save(_event: ft.ControlEvent) -> None:
        nonlocal settings_bundle
        try:
            candidate = candidate_bundle()
            fresh_preview = preview_settings(candidate, expected_revision=settings_bundle.revision, root=ROOT)
            if last_preview.get("revision") != fresh_preview.after_revision:
                raise SettingsError("SETTINGS_MIGRATION_REVIEW_REQUIRED", "preview the current edits before saving")
            result = save_settings(candidate, expected_revision=settings_bundle.revision, root=ROOT)
            state.snapshot.config = load_config()
            settings_bundle = load_settings_bundle(ROOT)
            settings_status.value = (
                f"Settings v{result.settings_version} saved atomically; revision {result.revision[:16]}. "
                "No analysis, provider, model or execution workflow was started."
            )
            settings_status.color = theme.GREEN
            version_text.value = f"Settings v{result.settings_version} · {result.revision[:16]}"
            last_preview.clear()
        except Exception as exc:
            settings_status.value = f"Settings not saved: {exc}"
            settings_status.color = theme.RED
        refresh_settings_status()

    provider_lines = [
        f"{name}: provider={section.active_provider or 'none'}; base URL={'configured' if section.base_url else 'not configured'}"
        for name, section in config.data_providers.providers.items()
    ]
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Product scope and authority", "The active local contract is versioned, checksum-bearing and fail-closed."),
                        ft.Text(
                            f"{product_policy.policy.product.canonical_name} · ADR {authority_matrix.policy.adr_id} · active stage: Research · execution_allowed=false"
                            if product_policy.policy is not None and authority_matrix.policy is not None
                            else "Product authority contract unavailable; manual review required; execution_allowed=false.",
                            key="settings.product-authority",
                            color=theme.AMBER,
                            selectable=True,
                        ),
                        ft.Text(
                            f"Capability matrix: {len(authority_matrix.policy.capabilities)} entries; checksum {authority_matrix.checksum}"
                            if authority_matrix.policy is not None
                            else "Capability matrix unavailable.",
                            key="settings.authority-matrix",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                    ],
                    spacing=6,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header(
                            "Settings centre",
                            "Typed local controls are staged, previewed as one policy bundle and saved atomically.",
                        ),
                        ft.Row([output_currency, risk_profile, horizon, analysis_depth], wrap=True, spacing=10),
                        asset_scopes,
                        ft.Text(
                            "Quick/Medium/High/Full describe warm/cold analysis effort; selection is stored now, while measured runtime effects remain unavailable until ISSUE-0175.",
                            color=theme.MUTED,
                            size=11,
                            selectable=True,
                        ),
                        ft.Row(
                            [
                                ft.Button("Preview changes", key="settings.preview", icon=ft.Icons.PREVIEW, on_click=preview),
                                ft.Button("Save settings", key="settings.save", icon=ft.Icons.SAVE, on_click=save),
                                ft.Button(
                                    "Manage credentials",
                                    key="settings.manage-credentials",
                                    disabled=True,
                                    tooltip="Unavailable: secure credential CRUD depends on ISSUE-0176.",
                                ),
                            ],
                            wrap=True,
                        ),
                        version_text,
                        settings_status,
                        ft.Text(
                            "Any semantic change creates a new settings version and invalidates reuse of an existing run manifest. execution_allowed=false",
                            color=theme.AMBER,
                            selectable=True,
                        ),
                        ft.Text(
                            "Preview shows whether a new analysis/selection run is required. Credential values never enter this bundle, logs or exports.",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                    ],
                    spacing=8,
                )
            ),
            panel(ft.Column([section_header("Release and data metadata", "Local release metadata helps users identify the current evidence build."), ft.Text(f"App version: {APP_VERSION}", key="settings.app-version", selectable=True), ft.Text(f"Version metadata: {version_status}", key="settings.version-metadata", selectable=True), ft.Text(f"Package metadata: {rebuild_timestamp}", key="settings.last-rebuild", selectable=True), ft.Text(f"Current data root: {DATA_DIR}", key="settings.data-root", selectable=True), ft.Text(f"Changelog: {changelog_status}", key="settings.changelog", selectable=True), ft.Text(issue_0044_update_plan, key="settings.issue-0044-update-plan", color=theme.MUTED, selectable=True)], spacing=6)),
            panel(ft.Column([section_header("Privacy, backup and recovery", "Local encrypted backups use Fernet with PBKDF2-HMAC-SHA256. Private fields, credentials, transient logs and caches are excluded by default."), recovery_key, ft.Row([ft.OutlinedButton("Create encrypted backup", key="settings.backup-create", icon=ft.Icons.SAVE, on_click=create_backup), ft.OutlinedButton("Validate latest backup", key="settings.backup-validate", icon=ft.Icons.VERIFIED, on_click=validate_backup), ft.OutlinedButton("Run recovery drill", key="settings.recovery-drill", icon=ft.Icons.SECURITY, on_click=recovery_drill)], wrap=True), ft.Text(f"Backup destination: {backup_archive}", color=theme.MUTED, selectable=True), deletion_confirmation, ft.OutlinedButton("Delete private data", key="settings.delete-private", icon=ft.Icons.DELETE_OUTLINE, on_click=delete_private), privacy_status], spacing=8)),
            panel(ft.Column([section_header("About and offline update verification", "Updates are local-only: unsigned, tampered or path-unsafe bundles are rejected before staging."), ft.Text(f"Release evidence: {release_evidence['verification']}", key="settings.update-verification", selectable=True), ft.Text(f"Release evidence version: {release_evidence['version']}", key="settings.update-version", selectable=True), ft.Text(f"Third-party notices: {release_evidence['notices']} ({release_evidence['notices_path']})", key="settings.third-party-notices", selectable=True), ft.Text("Network retrieval and live execution are disabled by policy.", color=theme.MUTED, selectable=True)], spacing=6)),
            panel(ft.Column([section_header("Legal terms, disclaimers and jurisdiction", "Terms and source permissions are versioned locally and reviewed before release."), ft.Text("Research and education only. Not financial or tax advice. No broker execution or order transmission.", color=theme.AMBER, selectable=True), ft.Text(f"Legal terms registry: {legal_report['status']} ({legal_report['review_status']}); checksum={legal_report['registry_sha256']}", key="settings.legal-terms-status", selectable=True), ft.Text("Restricted sources are excluded from standard audit export unless the registry explicitly permits metadata or attribution.", color=theme.MUTED, selectable=True)], spacing=6)),
            panel(ft.Column([section_header("Third-party intake and upstream governance", "Dependencies, optional model archives and copied-file boundaries are recorded locally before release."), ft.Text(f"Supply-chain intake: {supply_chain_report['status']} ({supply_chain_report['review_status']}); components={supply_chain_report['component_count']}; locked dependencies={supply_chain_report['dependency_count']}", key="settings.supply-chain-intake-status", color=theme.AMBER, selectable=True), ft.Text(f"Intake checksum: {supply_chain_report['registry_sha256']}; notices: {supply_chain_report['third_party_notices']}", key="settings.supply-chain-intake-checksum", color=theme.MUTED, size=11, selectable=True), ft.Text("No copied third-party core is permitted without an approved intake record. Upstream and licence hardening remains visible.", color=theme.MUTED, size=11, selectable=True)], spacing=6)),
            panel(ft.Column([section_header("Universe manager", "Validated local CRUD for watchlists and the Primary, Secondary and Sparebanken tiers."), ft.Row([ft.Button("Open Universe manager", key="settings.open-universe", on_click=lambda _event: _page.go("/universe")), ft.Button("Open first-run setup", key="settings.open-onboarding", on_click=lambda _event: _page.go("/onboarding"))]), ft.Text("Configuration saves show pending-refresh only; they never trigger refresh, scoring or model calls.", color=theme.MUTED)], spacing=8)),
            panel(ft.Column([section_header("Config folder", "Local YAML, JSON and .env-backed settings."), ft.Text(str(CONFIG_DIR), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Settings status", "Provider saves show progress here and are also written to the dashboard activity log."), status_text])),
            panel(ft.Column([section_header("Primary tier universe", "These first-class stocks and ETFs are loaded into the main score table. Secondary tier and Sparebanken entries come from the yfinance-only candidate CSV."), ft.Text("\n".join(f"{etf.id} - {etf.name} ({getattr(etf, 'model_extra', {}).get('instrument_type', etf.asset_class)})" for etf in config.universe.etfs), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Secondary and Sparebanken groups", "Secondary ETFs/stocks and Norwegian savings-bank equity-certificate issuers are displayed as separate Simple Scores groups. Unknown Sparebanken ISINs stay needs_verification."), ft.Text("Candidate source: data/raw/trade_candidates/yahoo_trade_candidates_2026-07-09.csv", color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Portfolio context targets", "Used for drift context only; they do not override stock/ETF evidence scores."), ft.Text("\n".join(target_lines), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Guardrail settings", "Data-quality failures still block analysis; allocation caps are displayed as context."), ft.Text(str(config.risks.model_dump()), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Asset support matrix", "Daily ETF/stock data is score eligible. Intraday, futures and options are research-only or unsupported; leveraged/inverse instruments require manual review."), ft.Text("execution_allowed=false", color=theme.AMBER)])),
            panel(ft.Column([section_header("Data providers", "Provider definitions are visible and versioned here. Credential CRUD is unavailable until ISSUE-0176."), ft.Text("\n".join(provider_lines), color=theme.MUTED, selectable=True), ft.Text("CREDENTIAL_CRUD_UNAVAILABLE_ISSUE_0176 · no plaintext credential field is exposed.", color=theme.AMBER, selectable=True)], spacing=12)),
            panel(ft.Column([section_header("Model settings", "Toto and TimesFM remain local optional evidence sources."), ft.Text("\n".join(model_lines), color=theme.MUTED, selectable=True)])),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
