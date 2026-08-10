from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping
from typing import Callable, Iterable

import flet as ft
import yaml

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.settings import ANALYSIS_DEPTHS, HORIZONS, OUTPUT_CURRENCIES, RISK_PROFILES
from etf_cockpit.core.atomic_io import atomic_write_bytes
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
    storage_location: str = "project_local"
    hardware_profile: str = "auto"
    mandatory_providers: tuple[str, ...] = ("manual_local",)
    optional_providers: tuple[str, ...] = ()
    bootstrap_mode: str = "sample"
    encryption_preference: str = "disabled"
    backup_preference: str = "local"
    execution_allowed: bool = False
    staged_execution_enabled: bool = False
    optional_provider_status: tuple[tuple[str, str], ...] = ()


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
    optional_provider_status: tuple[tuple[str, str], ...] = ()


_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,20}$", re.IGNORECASE)
_ASSET_SCOPES = {"etf", "stock", "fund", "bond", "both", "stock+etf", "all"}
_RISK_MAP = {"conservative": "safe", "balanced": "medium", "growth": "aggressive", **{item: item for item in RISK_PROFILES}}
_HORIZON_MAP = {"short": "1M", "medium": "3M", "long": "9M", **{item.casefold(): item for item in HORIZONS}}
ONBOARDING_SCHEMA_VERSION = "onboarding.v2"
_HARDWARE_PROFILES = {"auto", "minimum", "recommended", "high"}
_BOOTSTRAP_MODES = {"sample", "bulk"}
_MANDATORY_PROVIDERS = {"local", "manual_local", "issuer_document", "filings_xbrl_org", "sec_edgar", "index_provider"}
_OPTIONAL_PROVIDERS = _MANDATORY_PROVIDERS | {"yfinance", "stooq", "fred", "rss"}
_OPTIONAL_PROVIDER_STATUSES = {"available", "disabled", "missing", "not_configured", "quota_exceeded", "unavailable"}
_ENCRYPTION_PREFERENCES = {"disabled", "user_managed"}
_BACKUP_PREFERENCES = {"disabled", "local", "encrypted"}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _choice_values(values: object, *, field: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = tuple(item for item in values.split(","))
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise ValueError(f"{field} must be a sequence of provider IDs")
    result: list[str] = []
    for raw in values:
        value = _text(raw).casefold()
        if not value:
            raise ValueError(f"{field} contains an empty provider ID")
        if value not in _OPTIONAL_PROVIDERS:
            raise ValueError(f"{field} contains unsupported provider: {value}")
        if value not in result:
            result.append(value)
    return tuple(sorted(result))


def _normalise_storage_location(value: object) -> str:
    location = _text(value)
    if not location:
        raise ValueError("storage_location is required")
    if "\x00" in location or "://" in location or location.startswith(("//", "\\\\")):
        raise ValueError("storage_location must be a local filesystem path")
    path = Path(location)
    if ".." in path.parts or ".." in re.split(r"[\\/]", location):
        raise ValueError("storage_location must not contain parent traversal")
    return path.as_posix()


def _normalise_preference(value: object, *, field: str, allowed: set[str], aliases: Mapping[str, str]) -> str:
    preference = _text(value).casefold()
    preference = aliases.get(preference, preference)
    if preference not in allowed:
        raise ValueError(f"{field} is unsupported")
    return preference


def _normalise_provider_status(
    values: Mapping[str, str] | Iterable[tuple[str, str]],
    optional_providers: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    raw_items = values.items() if isinstance(values, Mapping) else values
    statuses: dict[str, str] = {}
    for raw_provider, raw_status in raw_items:
        provider = _text(raw_provider).casefold()
        status = _text(raw_status).casefold()
        if provider not in optional_providers:
            raise ValueError("optional provider status must refer to an optional provider")
        if status not in _OPTIONAL_PROVIDER_STATUSES:
            raise ValueError(f"unsupported optional provider status: {status}")
        statuses[provider] = status
    return tuple(sorted(statuses.items()))


def _setup_payload(profile: OnboardingProfile) -> dict[str, object]:
    mandatory = _choice_values(profile.mandatory_providers, field="mandatory_providers")
    optional = _choice_values(profile.optional_providers, field="optional_providers")
    if not mandatory:
        raise ValueError("at least one mandatory provider is required")
    if set(mandatory) & set(optional):
        raise ValueError("a provider cannot be both mandatory and optional")
    if not set(mandatory).issubset(_MANDATORY_PROVIDERS):
        raise ValueError("mandatory providers must be offline-compatible")
    statuses = _normalise_provider_status(profile.optional_provider_status, optional)
    status_map = {provider: "not_configured" for provider in optional}
    status_map.update(dict(statuses))
    return {
        "storage_location": _normalise_storage_location(profile.storage_location),
        "hardware_profile": _text(profile.hardware_profile).casefold(),
        "providers": {
            "mandatory": list(mandatory),
            "optional": list(optional),
            "optional_status": status_map,
        },
        "bootstrap": {"mode": _text(profile.bootstrap_mode).casefold(), "offline": True},
        "privacy": {
            "encryption_preference": _normalise_preference(
                profile.encryption_preference,
                field="encryption_preference",
                allowed=_ENCRYPTION_PREFERENCES,
                aliases={"off": "disabled", "none": "disabled", "on": "user_managed", "enabled": "user_managed"},
            ),
            "backup_preference": _normalise_preference(
                profile.backup_preference,
                field="backup_preference",
                allowed=_BACKUP_PREFERENCES,
                aliases={"off": "disabled", "none": "disabled", "enabled": "local", "encrypted_local": "encrypted"},
            ),
        },
        "execution": {
            "execution_allowed": False,
            "staged_execution_enabled": False,
            "paper_enabled": False,
            "broker_write_enabled": False,
        },
    }


def _canonical_profile(profile: OnboardingProfile) -> tuple[dict[str, object], dict[str, object]]:
    setup = _setup_payload(profile)
    hardware = str(setup["hardware_profile"])
    if hardware not in _HARDWARE_PROFILES:
        raise ValueError("hardware_profile is unsupported")
    bootstrap = setup["bootstrap"]
    assert isinstance(bootstrap, dict)
    if bootstrap["mode"] not in _BOOTSTRAP_MODES:
        raise ValueError("bootstrap_mode must be sample or bulk")
    if profile.execution_allowed:
        raise ValueError("execution_allowed must remain false")
    if profile.staged_execution_enabled:
        raise ValueError("staged execution must remain disabled")
    base_currency = _text(profile.base_currency).upper()
    risk_profile = _text(profile.risk_profile).casefold()
    horizon = _text(profile.horizon).casefold()
    analysis_depth = _text(profile.analysis_depth).casefold()
    scopes = _canonical_scopes(profile.asset_scope)
    tickers = _profile_tickers(profile)
    profile_payload = {
        "base_currency": base_currency,
        "region": _text(profile.region),
        "asset_scope": list(scopes),
        "risk_profile": _RISK_MAP.get(risk_profile, risk_profile),
        "horizon": _HORIZON_MAP.get(horizon, _HORIZON_MAP.get(horizon.casefold(), horizon)),
        "analysis_depth": analysis_depth,
        "tickers": list(tickers),
    }
    providers = setup["providers"]
    privacy = setup["privacy"]
    assert isinstance(providers, dict)
    assert isinstance(privacy, dict)
    profile_payload.update(
        {
            "storage_location": setup["storage_location"],
            "hardware_profile": setup["hardware_profile"],
            "mandatory_providers": providers["mandatory"],
            "optional_providers": providers["optional"],
            "optional_provider_status": providers["optional_status"],
            "bootstrap_mode": bootstrap["mode"],
            "encryption_preference": privacy["encryption_preference"],
            "backup_preference": privacy["backup_preference"],
            "execution_allowed": False,
            "staged_execution_enabled": False,
        }
    )
    return profile_payload, setup


def _canonical_scopes(values: Iterable[str]) -> tuple[str, ...]:
    scopes: list[str] = []
    for raw in values:
        value = _text(raw).lower()
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
    if profile.tickers and isinstance(profile.tickers, (list, tuple, set, frozenset)):
        return tuple(dict.fromkeys(_text(symbol).upper() for symbol in profile.tickers if _text(symbol)))
    if not isinstance(profile.asset_scope, (list, tuple, set, frozenset)):
        return ()
    if any(_text(value).lower() in _ASSET_SCOPES for value in profile.asset_scope):
        return ()
    return tuple(dict.fromkeys(_text(symbol).upper() for symbol in profile.asset_scope if _text(symbol)))


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
    if _text(profile.base_currency).upper() not in OUTPUT_CURRENCIES:
        errors.append("base_currency")
    if not _text(profile.region):
        errors.append("region")
    if not isinstance(profile.asset_scope, (list, tuple, set, frozenset)) or not profile.asset_scope:
        errors.append("asset_scope")
    elif profile.tickers and not all(_text(value).casefold() in _ASSET_SCOPES for value in profile.asset_scope):
        errors.append("asset_scope")
    if _text(profile.risk_profile).casefold() not in _RISK_MAP:
        errors.append("risk_profile")
    if _text(profile.horizon).casefold() not in _HORIZON_MAP:
        errors.append("horizon")
    if _text(profile.analysis_depth).casefold() not in ANALYSIS_DEPTHS:
        errors.append("analysis_depth")
    try:
        _canonical_profile(profile)
    except (TypeError, ValueError):
        errors.append("setup")
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
    optional_provider_status: Mapping[str, str] | None = None,
    provider_status: Mapping[str, str] | None = None,
) -> OnboardingResult:
    root = Path(root).resolve()
    statuses = dict(optional_provider_status or {})
    if provider_status is not None:
        if statuses:
            raise ValueError("provide only one optional provider status mapping")
        statuses = dict(provider_status)
    if statuses:
        profile = OnboardingProfile(**{**profile.__dict__, "optional_provider_status": tuple(statuses.items())})
    profile_payload, setup_payload = _canonical_profile(profile)
    validation = validate_onboarding(profile, validator=validator, online=online, root=root)
    if not validation.valid:
        raise ValueError("Onboarding validation failed: " + ", ".join(validation.errors))
    records = _onboarding_records(profile, validation.unresolved_symbols)
    revision = ""
    if records:
        revision = save_universe(records, expected_revision="", root=root).revision
    payload = {
        "schema_version": ONBOARDING_SCHEMA_VERSION,
        "profile": profile_payload,
        "setup": setup_payload,
        "unresolved_symbols": list(validation.unresolved_symbols),
        "execution_allowed": False,
    }
    path = Path(root) / "configs" / "onboarding.json"
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write_bytes(path, encoded, lambda candidate: json.loads(candidate.read_text(encoding="utf-8")))
    provider_payload = setup_payload["providers"]
    assert isinstance(provider_payload, dict)
    status_payload = provider_payload["optional_status"]
    assert isinstance(status_payload, dict)
    return OnboardingResult(True, validation.unresolved_symbols, records, revision, tuple(sorted((str(key), str(value)) for key, value in status_payload.items())))


def load_onboarding(root: Path) -> OnboardingProfile:
    """Load one complete onboarding document; malformed state fails closed."""

    path = Path(root).resolve() / "configs" / "onboarding.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"onboarding settings cannot be loaded: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != ONBOARDING_SCHEMA_VERSION:
        raise ValueError("onboarding settings schema is unsupported")
    if payload.get("execution_allowed") is not False:
        raise ValueError("onboarding execution_allowed must remain false")
    raw_profile = payload.get("profile")
    setup = payload.get("setup")
    if not isinstance(raw_profile, dict) or not isinstance(setup, dict):
        raise ValueError("onboarding settings are incomplete")
    providers = setup.get("providers")
    bootstrap = setup.get("bootstrap")
    privacy = setup.get("privacy")
    execution = setup.get("execution")
    if not all(isinstance(value, dict) for value in (providers, bootstrap, privacy, execution)):
        raise ValueError("onboarding setup sections are incomplete")
    if bootstrap.get("offline") is not True or execution.get("execution_allowed") is not False:
        raise ValueError("onboarding setup safety defaults are invalid")
    if execution.get("staged_execution_enabled") is not False or execution.get("paper_enabled") is not False or execution.get("broker_write_enabled") is not False:
        raise ValueError("onboarding staged-execution defaults must remain disabled")
    mirrored_profile = {
        "storage_location": setup.get("storage_location"),
        "hardware_profile": setup.get("hardware_profile"),
        "mandatory_providers": providers.get("mandatory"),
        "optional_providers": providers.get("optional"),
        "optional_provider_status": providers.get("optional_status"),
        "bootstrap_mode": bootstrap.get("mode"),
        "encryption_preference": privacy.get("encryption_preference"),
        "backup_preference": privacy.get("backup_preference"),
        "execution_allowed": False,
        "staged_execution_enabled": False,
    }
    if any(raw_profile.get(key) != value for key, value in mirrored_profile.items()):
        raise ValueError("onboarding profile and setup sections disagree")
    try:
        profile = OnboardingProfile(
            str(raw_profile["base_currency"]),
            str(raw_profile["region"]),
            tuple(raw_profile["asset_scope"]),
            str(raw_profile["risk_profile"]),
            str(raw_profile["horizon"]),
            tuple(raw_profile["tickers"]),
            str(raw_profile["analysis_depth"]),
            str(setup["storage_location"]),
            str(setup["hardware_profile"]),
            tuple(providers["mandatory"]),
            tuple(providers["optional"]),
            str(bootstrap["mode"]),
            str(privacy["encryption_preference"]),
            str(privacy["backup_preference"]),
            False,
            False,
            tuple(sorted((str(key), str(value)) for key, value in providers["optional_status"].items())),
        )
        validation = validate_onboarding(profile, root=Path(root).resolve())
        unresolved = payload.get("unresolved_symbols")
        if not validation.valid or not isinstance(unresolved, list) or any(not isinstance(item, str) for item in unresolved):
            raise ValueError("onboarding settings do not match their validated profile")
        canonical_unresolved = tuple(sorted(set(item.strip().upper() for item in unresolved if item.strip())))
        if tuple(unresolved) != canonical_unresolved or not set(canonical_unresolved).issubset(set(_profile_tickers(profile))):
            raise ValueError("onboarding unresolved symbols are invalid")
        _canonical_profile(profile)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"onboarding settings are invalid: {exc}") from exc
    return profile


load_onboarding_profile = load_onboarding


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
    storage_location = ft.TextField(label="Storage location", value="project_local", width=220, dense=True)
    hardware_profile = ft.Dropdown(label="Hardware profile", value="auto", options=[ft.dropdown.Option(item) for item in sorted(_HARDWARE_PROFILES)], width=180, dense=True)
    mandatory_provider = ft.Dropdown(label="Mandatory provider", value="manual_local", options=[ft.dropdown.Option(item) for item in sorted(_MANDATORY_PROVIDERS)], width=220, dense=True)
    optional_providers = ft.TextField(label="Optional providers (comma separated)", hint_text="yfinance, fred", width=280, dense=True)
    bootstrap_mode = ft.Dropdown(label="Offline bootstrap", value="sample", options=[ft.dropdown.Option(item) for item in sorted(_BOOTSTRAP_MODES)], width=180, dense=True)
    encryption_preference = ft.Dropdown(label="Encryption", value="disabled", options=[ft.dropdown.Option(item) for item in sorted(_ENCRYPTION_PREFERENCES)], width=180, dense=True)
    backup_preference = ft.Dropdown(label="Backups", value="local", options=[ft.dropdown.Option(item) for item in sorted(_BACKUP_PREFERENCES)], width=180, dense=True)
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
        selected_optional = tuple(value.strip() for value in (optional_providers.value or "").split(",") if value.strip())
        profile = OnboardingProfile(
            base_currency.value or "",
            region.value or "",
            (scope.value or "stock+etf",),
            risk.value or "",
            horizon.value or "",
            values,
            analysis_depth.value or "medium",
            storage_location.value or "",
            hardware_profile.value or "",
            (mandatory_provider.value or "",),
            selected_optional,
            bootstrap_mode.value or "",
            encryption_preference.value or "",
            backup_preference.value or "",
            False,
            False,
        )
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
            optional_status = ", ".join(f"{provider}: {state}" for provider, state in result.optional_provider_status if state == "quota_exceeded")
            suffix = f" Optional provider status: {optional_status}; mandatory setup was not blocked." if optional_status else ""
            status.value = f"Saved locally. {len(result.unresolved_symbols)} unresolved ticker(s) remain disabled; no refresh or model run was started.{suffix}"
        except Exception as exc:
            status.value = f"Setup not saved: {exc}"
        page.update()

    return ft.Column(
        [
            panel(ft.Column([section_header("First-run setup", "Create a local watchlist without requiring network access."), ft.Text(f"{jurisdiction_disclaimer} Offline or unresolved tickers remain disabled until validated. Online validation is opt-in and requires an injected provider callback.", color=theme.MUTED), ft.Row([base_currency, region, scope, risk, horizon, analysis_depth], wrap=True), ft.Row([storage_location, hardware_profile, mandatory_provider, optional_providers, bootstrap_mode, encryption_preference, backup_preference], wrap=True), ft.Text("Mandatory providers are offline-compatible. Optional provider absence or quota failure is recorded visibly and never blocks setup.", color=theme.MUTED, size=11), ft.Text("Quick/Medium/High/Full are versioned analysis-effort selections; warm/cold timing effects remain unavailable until ISSUE-0175.", color=theme.MUTED, size=11), ft.ResponsiveRow([ft.Container(content=tickers, col={"xs": 12, "md": 9}), ft.Container(content=ft.Button("Save setup", key="onboarding.save", icon=ft.Icons.SAVE, on_click=submit), col={"xs": 12, "md": 3})], spacing=8, run_spacing=8), online_validation, status], spacing=10)),
            panel(ft.Column([section_header("Hardware and resource readiness", "Local profile selection, pre-job limits and graceful degradation. No telemetry or cloud compute is used."), ft.SelectionArea(ft.Text("\n".join(resource_lines), color=theme.MUTED)), ft.SelectionArea(ft.Text("CPU-only baseline remains available; optional foundation models are never required.", color=theme.GREEN))], spacing=6)),
            panel(ft.Column([section_header("Authority boundary", "Setup stores preferences only. It never grants broker/provider write authority or starts execution."), ft.Text("execution_allowed=false | staged_execution_enabled=false | paper_enabled=false | broker_write_enabled=false", color=theme.AMBER)])),
            panel(ft.Column([section_header("Data source policy", "Choose local imports or replayable official evidence for the mandatory path. Online validation is optional and never required for setup."), ft.Text(source_summary, color=theme.MUTED, size=11, selectable=True), ft.Text(f"Terms acknowledgement: {legal_report['review_status']}; restricted sources are not redistributed. Registry checksum: {legal_report['registry_sha256']}", color=theme.AMBER, size=11, selectable=True)])),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
