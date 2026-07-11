from __future__ import annotations

from dataclasses import dataclass

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState


@dataclass(frozen=True)
class OnboardingProfile:
    base_currency: str
    region: str
    asset_scope: tuple[str, ...]
    risk_profile: str
    horizon: str


@dataclass(frozen=True)
class OnboardingValidation:
    valid: bool
    errors: tuple[str, ...]
    unresolved_symbols: tuple[str, ...]


def validate_onboarding(profile: OnboardingProfile) -> OnboardingValidation:
    errors: list[str] = []
    if not profile.base_currency.strip():
        errors.append("base_currency")
    if not profile.region.strip():
        errors.append("region")
    if not profile.asset_scope:
        errors.append("asset_scope")
    if not profile.risk_profile.strip():
        errors.append("risk_profile")
    unresolved = tuple(sorted({symbol.strip() for symbol in profile.asset_scope if symbol.strip().upper().startswith("UNKNOWN")}))
    return OnboardingValidation(not errors, tuple(errors), unresolved)


def onboarding_page(_page: ft.Page, _state: AppState) -> ft.Control:
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("First-run setup", "Configure local evidence scope and daily supported instruments. Unresolved symbols remain disabled until identity is verified."),
                        ft.Text("No broker execution is available. This setup does not provide financial advice.", color=theme.MUTED),
                        ft.Text("Base currency, region, risk profile and initial universe are stored locally after validation.", color=theme.MUTED),
                    ],
                    spacing=8,
                )
            )
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
