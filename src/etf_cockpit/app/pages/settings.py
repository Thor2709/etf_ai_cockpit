from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.constants import APP_VERSION
from etf_cockpit.core.paths import CONFIG_DIR, DATA_DIR, ROOT


def settings_page(_page: ft.Page, state: AppState) -> ft.Control:
    config = state.snapshot.config
    target_lines = [f"{etf_id}: context target {pos.target_weight:.1%}, drift bands {pos.soft_band:.1%}/{pos.hard_band:.1%}" for etf_id, pos in config.targets.positions.items()]
    model_lines = [f"{name}: {settings}" for name, settings in config.models.models.items()]
    status_text = ft.Text(state.last_message, color=theme.MUTED, selectable=True)
    version_metadata_path = ROOT / "pyproject.toml"
    version_status = f"available at {version_metadata_path}" if version_metadata_path.is_file() else "unavailable (missing pyproject.toml)"
    changelog_path = ROOT / ".ai_worklog" / "CHANGES.md"
    changelog_status = f"available at {changelog_path}" if changelog_path.is_file() else "unavailable (missing .ai_worklog/CHANGES.md)"
    rebuild_path = ROOT / "RUN_STATE.json"
    rebuild_timestamp = "unavailable"
    try:
        rebuild_timestamp = str(__import__("json").loads(rebuild_path.read_text(encoding="utf-8")).get("updated_at", "unavailable")) if rebuild_path.is_file() else "unavailable"
    except Exception:
        rebuild_timestamp = "unavailable"
    issue_0044_update_plan = (
        "ISSUE-0044 packaged-app update workflow: build the Windows package, record the release version and SHA-256 checksum, "
        "back up local data/configs, install the package, run a restore/startup smoke check, then retain the changelog and rebuild timestamp."
    )
    provider_fields: list[ft.Control] = []
    for name, section in config.data_providers.providers.items():
        provider_input = ft.TextField(label="Provider", value=section.active_provider, dense=True, width=180)
        base_url_input = ft.TextField(label="Base URL", value=section.base_url, dense=True, width=320)
        api_key_input = ft.TextField(label="API key", value="", password=True, can_reveal_password=True, hint_text="saved to local .env only", dense=True, width=220)

        def save_provider(_event: ft.ControlEvent, provider_name: str = name, provider_field: ft.TextField = provider_input, base_url_field: ft.TextField = base_url_input, api_key_field: ft.TextField = api_key_input) -> None:
            state.begin_activity(f"Save {provider_name} provider settings", "Writing local config")
            status_text.value = f"Saving provider settings for {provider_name}..."
            _page.update()
            try:
                status_text.value = state.save_provider_settings(provider_name, provider_field.value or "none", base_url_field.value or "", api_key_field.value or "")
                state.finish_activity(status_text.value)
                api_key_field.value = ""
            except Exception as exc:
                state.fail_activity(f"Save {provider_name} provider settings", exc)
                status_text.value = state.last_message
            _page.update()

        provider_fields.append(
            ft.Column(
                [
                    ft.Text(name.replace("_", " ").title(), color=theme.TEXT, weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            provider_input,
                            base_url_input,
                            api_key_input,
                            ft.Button("Save", key=f"settings.save-provider.{name}", icon=ft.Icons.SAVE, on_click=save_provider),
                        ],
                        wrap=True,
                        spacing=10,
                    ),
                    ft.Text("Provider/base URL are saved in data_providers.yaml. API keys are saved only in local .env and are never exported or logged.", color=theme.MUTED, size=11),
                ],
                spacing=6,
            )
        )
    return ft.Column(
        [
            panel(ft.Column([section_header("Release and data metadata", "Local release metadata helps users identify the current evidence build."), ft.Text(f"App version: {APP_VERSION}", key="settings.app-version", selectable=True), ft.Text(f"Version metadata: {version_status}", key="settings.version-metadata", selectable=True), ft.Text(f"Last rebuild timestamp: {rebuild_timestamp}", key="settings.last-rebuild", selectable=True), ft.Text(f"Current data root: {DATA_DIR}", key="settings.data-root", selectable=True), ft.Text(f"Changelog: {changelog_status}", key="settings.changelog", selectable=True), ft.Text(issue_0044_update_plan, key="settings.issue-0044-update-plan", color=theme.MUTED, selectable=True)], spacing=6)),
            panel(ft.Column([section_header("Universe manager", "Validated local CRUD for watchlists and the Primary, Secondary and Sparebanken tiers."), ft.Row([ft.Button("Open Universe manager", key="settings.open-universe", on_click=lambda _event: _page.go("/universe")), ft.Button("Open first-run setup", key="settings.open-onboarding", on_click=lambda _event: _page.go("/onboarding"))]), ft.Text("Configuration saves show pending-refresh only; they never trigger refresh, scoring or model calls.", color=theme.MUTED)], spacing=8)),
            panel(ft.Column([section_header("Config folder", "Local YAML, JSON and .env-backed settings."), ft.Text(str(CONFIG_DIR), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Settings status", "Provider saves show progress here and are also written to the dashboard activity log."), status_text])),
            panel(ft.Column([section_header("Primary tier universe", "These first-class stocks and ETFs are loaded into the main score table. Secondary tier and Sparebanken entries come from the yfinance-only candidate CSV."), ft.Text("\n".join(f"{etf.id} - {etf.name} ({getattr(etf, 'model_extra', {}).get('instrument_type', etf.asset_class)})" for etf in config.universe.etfs), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Secondary and Sparebanken groups", "Secondary ETFs/stocks and Norwegian savings-bank equity-certificate issuers are displayed as separate Simple Scores groups. Unknown Sparebanken ISINs stay needs_verification."), ft.Text("Candidate source: data/raw/trade_candidates/yahoo_trade_candidates_2026-07-09.csv", color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Portfolio context targets", "Used for drift context only; they do not override stock/ETF evidence scores."), ft.Text("\n".join(target_lines), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Guardrail settings", "Data-quality failures still block analysis; allocation caps are displayed as context."), ft.Text(str(config.risks.model_dump()), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Asset support matrix", "Daily ETF/stock data is score eligible. Intraday, futures and options are research-only or unsupported; leveraged/inverse instruments require manual review."), ft.Text("execution_allowed=false", color=theme.AMBER)])),
            panel(ft.Column([section_header("Data providers", "Local files work immediately; API providers can be configured later."), *provider_fields], spacing=12)),
            panel(ft.Column([section_header("Model settings", "Toto and TimesFM remain local optional evidence sources."), ft.Text("\n".join(model_lines), color=theme.MUTED, selectable=True)])),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
