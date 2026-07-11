from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import CONFIG_DIR


def settings_page(_page: ft.Page, state: AppState) -> ft.Control:
    config = state.snapshot.config
    target_lines = [f"{etf_id}: context target {pos.target_weight:.1%}, drift bands {pos.soft_band:.1%}/{pos.hard_band:.1%}" for etf_id, pos in config.targets.positions.items()]
    model_lines = [f"{name}: {settings}" for name, settings in config.models.models.items()]
    status_text = ft.Text(state.last_message, color=theme.MUTED, selectable=True)
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
                            ft.Button("Save", icon=ft.Icons.SAVE, on_click=save_provider),
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
            panel(ft.Column([section_header("Config folder", "Local YAML, JSON and .env-backed settings."), ft.Text(str(CONFIG_DIR), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Settings status", "Provider saves show progress here and are also written to the dashboard activity log."), status_text])),
            panel(ft.Column([section_header("Primary tier universe", "These first-class stocks and ETFs are loaded into the main score table. Secondary tier and Sparebanken entries come from the yfinance-only candidate CSV."), ft.Text("\n".join(f"{etf.id} - {etf.name} ({getattr(etf, 'model_extra', {}).get('instrument_type', etf.asset_class)})" for etf in config.universe.etfs), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Secondary and Sparebanken groups", "Secondary ETFs/stocks and Norwegian savings-bank equity-certificate issuers are displayed as separate Simple Scores groups. Unknown Sparebanken ISINs stay needs_verification."), ft.Text("Candidate source: data/raw/trade_candidates/yahoo_trade_candidates_2026-07-09.csv", color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Portfolio context targets", "Used for drift context only; they do not override stock/ETF evidence scores."), ft.Text("\n".join(target_lines), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Guardrail settings", "Data-quality failures still block analysis; allocation caps are displayed as context."), ft.Text(str(config.risks.model_dump()), color=theme.MUTED, selectable=True)])),
            panel(ft.Column([section_header("Data providers", "Local files work immediately; API providers can be configured later."), *provider_fields], spacing=12)),
            panel(ft.Column([section_header("Model settings", "Toto and TimesFM remain local optional evidence sources."), ft.Text("\n".join(model_lines), color=theme.MUTED, selectable=True)])),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
