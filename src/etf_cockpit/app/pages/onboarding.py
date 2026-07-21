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
from etf_cockpit.application.settings import ANALYSIS_DEPTHS, HORIZONS, OUTPUT_CURRENCIES, RISK_PROFILES
from etf_cockpit.core.config import load_config
from etf_cockpit.application.ui_facade import UniverseRecord, legal_terms_report, load_universe, resource_profile_report, save_universe, source_policy_rows


@dataclass(frozen=True)
class OnboardingProfile:
    base_currency: str
    region: str
    asset_scope: tuple[str, ...]
    risk_profile: str
    horizon: str
    tickers: tuple[str, ...] = ()
    analysis_depth: str = "medium"


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
_ASSET_SCOPES = {"etf", "stock", "fund", "bond", "both", "stock+etf", "all"}
_RISK_MAP = {"conservative": "safe", "balanced": "medium", "growth": "aggressive", **{item: item for item in RISK_PROFILES}}
_HORIZON_MAP = {"short": "1M", "medium": "3M", "long": "9M", **{item.casefold(): item for item in HORIZONS}}


def _canonical_scopes(values: Iterable[str]) -> tuple[str, ...]:
    scopes: list[str] = []
    for raw in values:
        value = raw.strip().lower()
        if value in {"both", "stock+etf"}:
            scopes.extend(("stock", "etf"))
        elif value == "all":
            scopes.extend(("stock", "etf", "fund", "bond"))
        elif value in {"stock", "etf", "fund", "bond"}:
            scopes.append(value)
    return tuple(dict.fromkeys(scopes))


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
    if profile.base_currency.strip().upper() not in OUTPUT_CURRENCIES:
        errors.append("base_currency")
    if not profile.region.strip():
        errors.append("region")
    if not profile.asset_scope:
        errors.append("asset_scope")
    elif profile.tickers and not all(value.strip().lower() in _ASSET_SCOPES for value in profile.asset_scope):
        errors.append("asset_scope")
    if profile.risk_profile.strip().lower() not in _RISK_MAP:
        errors.append("risk_profile")
    if profile.horizon.strip().casefold() not in _HORIZON_MAP:
        errors.append("horizon")
    if profile.analysis_depth.strip().lower() not in ANALYSIS_DEPTHS:
        errors.append("analysis_depth")
    unresolved = validate_tickers(
        _profile_tickers(profile),
        validator=validator,
        online=online,
        local_evidence=_local_ticker_evidence(root) if root is not None else (),
    )
    return OnboardingValidation(not errors, tuple(errors), unresolved)


def _onboarding_records(profile: OnboardingProfile, unresolved: tuple[str, ...]) -> tuple[UniverseRecord, ...]:
    scopes = _canonical_scopes(profile.asset_scope)
    scope = scopes[0] if len(scopes) == 1 else "both"
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
    path.write_text(json.dumps({"profile": {"base_currency": profile.base_currency.strip().upper(), "region": profile.region, "asset_scope": list(_canonical_scopes(profile.asset_scope)), "risk_profile": _RISK_MAP[profile.risk_profile.strip().lower()], "horizon": _HORIZON_MAP[profile.horizon.strip().casefold()], "analysis_depth": profile.analysis_depth.strip().lower(), "tickers": list(_profile_tickers(profile))}, "unresolved_symbols": list(validation.unresolved_symbols)}, indent=2) + "\n", encoding="utf-8")
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
    base_currency = ft.Dropdown(label="Output currency", value="EUR", options=[ft.dropdown.Option(item) for item in OUTPUT_CURRENCIES], width=180, dense=True)
    region = ft.TextField(label="Region", value="Europe", width=220, dense=True)
    scope = ft.Dropdown(label="Asset scope", value="stock+etf", options=[ft.dropdown.Option(item) for item in ("stock", "etf", "fund", "bond", "stock+etf", "all")], width=180, dense=True)
    risk = ft.Dropdown(label="Risk profile", value="medium", options=[ft.dropdown.Option(item) for item in RISK_PROFILES], width=220, dense=True)
    horizon = ft.Dropdown(label="Target horizon", value="3M", options=[ft.dropdown.Option(item) for item in HORIZONS], width=180, dense=True)
    analysis_depth = ft.Dropdown(label="Analysis depth", value="medium", options=[ft.dropdown.Option(item) for item in ANALYSIS_DEPTHS], width=180, dense=True)
    tickers = ft.TextField(
        label="Initial tickers (comma separated)",
        hint_text="VWCE.DE, MSFT",
        dense=True,
    )
    online_validation = ft.Checkbox(
        label="Validate tickers online (optional)" if validator is not None else "Online validation unavailable (no validator configured)",
        value=False,
        disabled=validator is None,
        key="onboarding.online-validation",
    )
    status = ft.Text("", color=theme.MUTED, selectable=True)
    source_rows = source_policy_rows(Path.cwd())
    source_summary = "\n".join(
        f"{row['provider_id']}: tier={row['source_tier']} | {row['optionality']} | cache={row['cache_status']} | network={row['network']}"
        for row in source_rows
    )
    legal_report = legal_terms_report(Path.cwd())
    jurisdiction_disclaimer = str(legal_report["jurisdictions"][0]["disclaimer"])
    resource_report = resource_profile_report(Path.cwd())
    selected_profile = resource_report["selected_profile"]
    resource_lines = [
        f"Selected profile: {selected_profile['profile_id']} ({resource_report['selected_status']}) | CPU {resource_report['snapshot']['cpu_cores']} core(s) | memory {resource_report['snapshot'].get('memory_available_mb') or resource_report['snapshot'].get('memory_total_mb') or 'n/a'} MB available/total | disk {resource_report['snapshot'].get('disk_free_mb') or 'n/a'} MB free",
        f"Per-job quota: {selected_profile['job_memory_limit_mb']} MB memory | {selected_profile['job_disk_limit_mb']} MB disk | {selected_profile['job_cpu_limit']} CPU core(s)",
        "Profiles: " + "; ".join(f"{row['profile_id']}={row['status']}" for row in resource_report["profiles"]),
        f"Performance evidence: {resource_report['benchmarks']['status']} from {resource_report['benchmarks']['timing_record_count']} local timing record(s); generated-cache cleanup: {resource_report['generated_cache']['status']}",
        "Limitations: " + " ".join(resource_report["limitations"]),
    ]

    def submit(_event: ft.ControlEvent) -> None:
        values = tuple(value.strip() for value in (tickers.value or "").split(",") if value.strip())
        profile = OnboardingProfile(base_currency.value or "", region.value or "", (scope.value or "stock+etf",), risk.value or "", horizon.value or "", values, analysis_depth.value or "medium")
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
            panel(ft.Column([section_header("First-run setup", "Create a local watchlist without requiring network access."), ft.Text(f"{jurisdiction_disclaimer} Offline or unresolved tickers remain disabled until validated. Online validation is opt-in and requires an injected provider callback.", color=theme.MUTED), ft.Row([base_currency, region, scope, risk, horizon, analysis_depth], wrap=True), ft.Text("Quick/Medium/High/Full are versioned analysis-effort selections; warm/cold timing effects remain unavailable until ISSUE-0175.", color=theme.MUTED, size=11), ft.ResponsiveRow([ft.Container(content=tickers, col={"xs": 12, "md": 9}), ft.Container(content=ft.Button("Save setup", key="onboarding.save", icon=ft.Icons.SAVE, on_click=submit), col={"xs": 12, "md": 3})], spacing=8, run_spacing=8), online_validation, status], spacing=10)),
            panel(ft.Column([section_header("Hardware and resource readiness", "Local profile selection, pre-job limits and graceful degradation. No telemetry or cloud compute is used."), ft.SelectionArea(ft.Text("\n".join(resource_lines), color=theme.MUTED)), ft.SelectionArea(ft.Text("CPU-only baseline remains available; optional foundation models are never required.", color=theme.GREEN))], spacing=6)),
            panel(ft.Column([section_header("Authority boundary", "Universe edits only persist configuration. They never trigger yfinance downloads, scoring, forecasts or broker execution."), ft.Text("execution_allowed=false", color=theme.AMBER)])),
            panel(ft.Column([section_header("Data source policy", "Choose local imports or replayable official evidence for the mandatory path. Online validation is optional and never required for setup."), ft.Text(source_summary, color=theme.MUTED, size=11, selectable=True), ft.Text(f"Terms acknowledgement: {legal_report['review_status']}; restricted sources are not redistributed. Registry checksum: {legal_report['registry_sha256']}", color=theme.AMBER, size=11, selectable=True)])),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
