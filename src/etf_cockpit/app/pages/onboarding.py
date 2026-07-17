from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import flet as ft
import yaml

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.config import load_config
from etf_cockpit.application.ui_facade import UniverseRecord, load_universe, save_universe


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


def validate_tickers(
    tickers: Iterable[str],
    *,
    validator: Callable[[str], bool] | None = None,
    online: bool = False,
    local_evidence: Iterable[str] = (),
) -> tuple[str, ...]:
    evidence = {str(value).strip().upper() for value in local_evidence if str(value).strip()}
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
        elif valid:
            # Offline onboarding is local-first: a shape-valid symbol is not
            # evidence of a real instrument. Existing local universe/config
            # identity is the only offline positive signal.
            valid = symbol in evidence
        if not valid or symbol.startswith("UNKNOWN") or symbol.startswith("UNRESOLVED"):
            unresolved.append(symbol)
    return tuple(sorted(set(unresolved)))


def _local_ticker_evidence(root: Path) -> tuple[str, ...]:
    """Read only local identity evidence; never performs provider/network I/O."""

    root = Path(root)
    symbols: set[str] = set()
    try:
        symbols.update(record.ticker.upper() for record in load_universe(root).records if record.ticker)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    yaml_path = root / "configs" / "universe.yaml"
    if yaml_path.exists():
        try:
            payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            for row in payload.get("etfs", ()) if isinstance(payload, dict) else ():
                if not isinstance(row, dict):
                    continue
                for key in ("ticker", "symbol", "provider_symbol", "yahoo_symbol", "yahoo_ticker"):
                    value = str(row.get(key) or "").strip().upper()
                    if value:
                        symbols.add(value)
        except (OSError, ValueError, TypeError):
            pass
    return tuple(sorted(symbols))


def validate_onboarding(
    profile: OnboardingProfile,
    *,
    validator: Callable[[str], bool] | None = None,
    online: bool = False,
    root: Path | None = None,
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
    unresolved = validate_tickers(
        _profile_tickers(profile),
        validator=validator,
        online=online,
        local_evidence=_local_ticker_evidence(root) if root is not None else (),
    )
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
    root = Path(root).resolve()
    validation = validate_onboarding(profile, validator=validator, online=online, root=root)
    if not validation.valid:
        raise ValueError("Onboarding validation failed: " + ", ".join(validation.errors))
    records = _onboarding_records(profile, validation.unresolved_symbols)
    path = Path(root) / "configs" / "onboarding.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"profile": {"base_currency": profile.base_currency, "region": profile.region, "asset_scope": list(profile.asset_scope), "risk_profile": profile.risk_profile, "horizon": profile.horizon, "tickers": list(_profile_tickers(profile))}, "unresolved_symbols": list(validation.unresolved_symbols)}, indent=2) + "\n", encoding="utf-8")
    revision = ""
    if records:
        revision = save_universe(records, expected_revision="", root=root).revision
    return OnboardingResult(True, validation.unresolved_symbols, records, revision)


def onboarding_page(
    page: ft.Page,
    state: AppState,
    *,
    validator: Callable[[str], bool] | None = None,
) -> ft.Control:
    base_currency = ft.TextField(label="Base currency", value="EUR", width=180, dense=True)
    region = ft.TextField(label="Region", value="Europe", width=220, dense=True)
    scope = ft.Dropdown(label="Asset scope", value="both", options=[ft.dropdown.Option(item) for item in ("etf", "stock", "both")], width=180, dense=True)
    risk = ft.Dropdown(label="Risk profile", value="balanced", options=[ft.dropdown.Option(item) for item in ("conservative", "balanced", "growth")], width=180, dense=True)
    horizon = ft.Dropdown(label="Target horizon", value="medium", options=[ft.dropdown.Option(item) for item in ("short", "medium", "long")], width=180, dense=True)
    tickers = ft.TextField(label="Initial tickers (comma separated)", hint_text="VWCE.DE, MSFT", expand=True, dense=True)
    online_validation = ft.Checkbox(
        label="Validate tickers online (optional)" if validator is not None else "Online validation unavailable (no validator configured)",
        value=False,
        disabled=validator is None,
        key="onboarding.online-validation",
    )
    status = ft.Text("", color=theme.MUTED, selectable=True)

    def submit(_event: ft.ControlEvent) -> None:
        values = tuple(value.strip() for value in (tickers.value or "").split(",") if value.strip())
        profile = OnboardingProfile(base_currency.value or "", region.value or "", (scope.value or "both",), risk.value or "", horizon.value or "", values)
        try:
            result = complete_onboarding(
                profile,
                Path.cwd(),
                online=bool(online_validation.value),
                validator=validator,
            )
            if result.revision and state is not None:
                refreshed_config = load_config()
                apply_method = getattr(state, "apply_universe_config", None)
                if callable(apply_method):
                    apply_method(refreshed_config, result.revision)
                else:
                    state.snapshot.config = refreshed_config
                    state.snapshot.universe_revision = result.revision
                    state.universe_cache_revision = result.revision
            status.value = f"Saved locally. {len(result.unresolved_symbols)} unresolved ticker(s) remain disabled; no refresh or model run was started."
        except Exception as exc:
            status.value = f"Setup not saved: {exc}"
        page.update()

    return ft.Column(
        [
            panel(ft.Column([section_header("First-run setup", "Create a local watchlist without requiring network access."), ft.Text("Local-only evidence is not financial advice. Offline or unresolved tickers remain disabled until validated. Online validation is opt-in and requires an injected provider callback.", color=theme.MUTED), ft.Row([base_currency, region, scope, risk, horizon], wrap=True), ft.Row([tickers, ft.Button("Save setup", key="onboarding.save", icon=ft.Icons.SAVE, on_click=submit)], wrap=True), online_validation, status], spacing=10)),
            panel(ft.Column([section_header("Authority boundary", "Universe edits only persist configuration. They never trigger yfinance downloads, scoring, forecasts or broker execution."), ft.Text("execution_allowed=false", color=theme.AMBER)])),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
