from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.data.universe_store import UniverseRecord, save_universe


@dataclass(frozen=True)
class OnboardingProfile:
    base_currency: str
    region: str
    asset_scope: tuple[str, ...]
    risk_profile: str
    horizon: str
    tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class OnboardingValidation:
    valid: bool
    errors: tuple[str, ...]
    unresolved_symbols: tuple[str, ...]


@dataclass(frozen=True)
class OnboardingResult:
    saved: bool
    unresolved_symbols: tuple[str, ...]
    records: tuple[UniverseRecord, ...]
    revision: str = ""


_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,20}$", re.IGNORECASE)
_ASSET_SCOPES = {"etf", "stock", "both"}


def _profile_tickers(profile: OnboardingProfile) -> tuple[str, ...]:
    # The original Task 11 draft used asset_scope for initial symbols. Keep that
    # positional form compatible while supporting the explicit tickers field.
    if profile.tickers:
        return tuple(dict.fromkeys(symbol.strip().upper() for symbol in profile.tickers if symbol.strip()))
    if any(value.strip().lower() in _ASSET_SCOPES for value in profile.asset_scope):
        return ()
    return tuple(dict.fromkeys(symbol.strip().upper() for symbol in profile.asset_scope if symbol.strip()))


def validate_tickers(tickers: Iterable[str], *, validator: Callable[[str], bool] | None = None, online: bool = False) -> tuple[str, ...]:
    unresolved: list[str] = []
    for raw in tickers:
        symbol = raw.strip().upper()
        if not symbol:
            continue
        valid = bool(_TICKER_RE.fullmatch(symbol))
        if valid and online and validator is not None:
            try:
                valid = bool(validator(symbol))
            except Exception:
                valid = False
        if not valid or symbol.startswith("UNKNOWN") or symbol.startswith("UNRESOLVED"):
            unresolved.append(symbol)
    return tuple(sorted(set(unresolved)))


def validate_onboarding(
    profile: OnboardingProfile,
    *,
    validator: Callable[[str], bool] | None = None,
    online: bool = False,
) -> OnboardingValidation:
    errors: list[str] = []
    if not profile.base_currency.strip():
        errors.append("base_currency")
    if not profile.region.strip():
        errors.append("region")
    if not profile.asset_scope:
        errors.append("asset_scope")
    elif profile.tickers and not all(value.strip().lower() in _ASSET_SCOPES for value in profile.asset_scope):
        errors.append("asset_scope")
    if not profile.risk_profile.strip():
        errors.append("risk_profile")
    if not profile.horizon.strip():
        errors.append("horizon")
    unresolved = validate_tickers(_profile_tickers(profile), validator=validator, online=online)
    return OnboardingValidation(not errors, tuple(errors), unresolved)


def _onboarding_records(profile: OnboardingProfile, unresolved: tuple[str, ...]) -> tuple[UniverseRecord, ...]:
    scope = next((value.strip().lower() for value in profile.asset_scope if value.strip().lower() in _ASSET_SCOPES), "both")
    tickers = _profile_tickers(profile)
    rows: list[UniverseRecord] = []
    for ticker in tickers:
        asset_type = "etf" if scope == "etf" else "stock" if scope == "stock" else ("etf" if ticker.endswith((".DE", ".L", ".PA")) else "stock")
        rows.append(
            UniverseRecord(
                instrument_id=ticker.replace(".", "_"),
                name=ticker,
                ticker=ticker,
                asset_type=asset_type,
                tier="secondary",
                group="Onboarding watchlist",
                enabled=ticker not in unresolved,
                data_policy="daily",
                currency=profile.base_currency.strip().upper(),
                region=profile.region.strip(),
                notes="Unresolved ticker disabled until local/yfinance identity validation." if ticker in unresolved else "Added during first-run onboarding.",
            )
        )
    return tuple(rows)


def complete_onboarding(
    profile: OnboardingProfile,
    root: Path,
    *,
    online: bool = False,
    validator: Callable[[str], bool] | None = None,
) -> OnboardingResult:
    validation = validate_onboarding(profile, validator=validator, online=online)
    if not validation.valid:
        raise ValueError("Onboarding validation failed: " + ", ".join(validation.errors))
    records = _onboarding_records(profile, validation.unresolved_symbols)
    path = Path(root) / "configs" / "onboarding.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"profile": {"base_currency": profile.base_currency, "region": profile.region, "asset_scope": list(profile.asset_scope), "risk_profile": profile.risk_profile, "horizon": profile.horizon, "tickers": list(_profile_tickers(profile))}, "unresolved_symbols": list(validation.unresolved_symbols)}, indent=2) + "\n", encoding="utf-8")
    revision = ""
    if records:
        revision = save_universe(records, expected_revision="", root=Path(root)).revision
    return OnboardingResult(True, validation.unresolved_symbols, records, revision)


def onboarding_page(page: ft.Page, state: AppState) -> ft.Control:
    base_currency = ft.TextField(label="Base currency", value="EUR", width=180, dense=True)
    region = ft.TextField(label="Region", value="Europe", width=220, dense=True)
    scope = ft.Dropdown(label="Asset scope", value="both", options=[ft.dropdown.Option(item) for item in ("etf", "stock", "both")], width=180, dense=True)
    risk = ft.Dropdown(label="Risk profile", value="balanced", options=[ft.dropdown.Option(item) for item in ("conservative", "balanced", "growth")], width=180, dense=True)
    horizon = ft.Dropdown(label="Target horizon", value="medium", options=[ft.dropdown.Option(item) for item in ("short", "medium", "long")], width=180, dense=True)
    tickers = ft.TextField(label="Initial tickers (comma separated)", hint_text="VWCE.DE, MSFT", expand=True, dense=True)
    status = ft.Text("", color=theme.MUTED, selectable=True)

    def submit(_event: ft.ControlEvent) -> None:
        values = tuple(value.strip() for value in (tickers.value or "").split(",") if value.strip())
        profile = OnboardingProfile(base_currency.value or "", region.value or "", (scope.value or "both",), risk.value or "", horizon.value or "", values)
        try:
            result = complete_onboarding(profile, Path.cwd(), online=False)
            status.value = f"Saved locally. {len(result.unresolved_symbols)} unresolved ticker(s) remain disabled; no refresh or model run was started."
        except Exception as exc:
            status.value = f"Setup not saved: {exc}"
        page.update()

    return ft.Column(
        [
            panel(ft.Column([section_header("First-run setup", "Create a local watchlist without requiring network access."), ft.Text("Local-only evidence is not financial advice. Offline or unresolved tickers remain disabled until validated.", color=theme.MUTED), ft.Row([base_currency, region, scope, risk, horizon], wrap=True), ft.Row([tickers, ft.Button("Save setup", key="onboarding.save", icon=ft.Icons.SAVE, on_click=submit)], wrap=True), status], spacing=10)),
            panel(ft.Column([section_header("Authority boundary", "Universe edits only persist configuration. They never trigger yfinance downloads, scoring, forecasts or broker execution."), ft.Text("execution_allowed=false", color=theme.AMBER)])),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
