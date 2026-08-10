from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Mapping
from typing import Callable, Iterable, Literal

import flet as ft
import yaml

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.settings import ANALYSIS_DEPTHS, HORIZONS, OUTPUT_CURRENCIES, RISK_PROFILES
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
from etf_cockpit.core.config import load_config
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.ui_facade import UniverseRecord, import_legacy_universe, legal_terms_report, load_universe, resource_profile_report, save_universe, source_policy_rows, validate_import


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
    bulk_source_path: str = ""


@dataclass(frozen=True)
class OnboardingValidation:
    valid: bool
    errors: tuple[str, ...]
    unresolved_symbols: tuple[str, ...]
    optional_provider_status: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TickerValidationResult:
    status: Literal["valid", "invalid", "unavailable", "quota_exceeded", "quota_unavailable"]
    provider_id: str = "yfinance"


class ProviderQuotaExceeded(RuntimeError):
    """Recognised optional-provider quota result; callers must not retry."""

    def __init__(self, provider_id: str = "yfinance") -> None:
        self.provider_id = _text(provider_id).casefold() or "yfinance"
        super().__init__(f"optional provider quota exceeded: {self.provider_id}")


@dataclass(frozen=True)
class BootstrapResult:
    mode: str
    status: Literal["ready", "unavailable"]
    rows: int
    output_paths: tuple[str, ...]
    message: str
    source_path: str = ""
    market_data_status: str = "unavailable"
    execution_allowed: bool = False


@dataclass(frozen=True)
class OnboardingResult:
    saved: bool
    unresolved_symbols: tuple[str, ...]
    records: tuple[UniverseRecord, ...]
    revision: str = ""
    optional_provider_status: tuple[tuple[str, str], ...] = ()
    storage_root: str = ""
    bootstrap: BootstrapResult | None = None


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
_SAMPLE_INSTRUMENT_IDS = ("VWCE", "MSFT")


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
    if location.casefold() == "project_local":
        return "project_local"
    raise ValueError(
        "storage_location must be project_local; custom runtime roots are unsupported. "
        "Choose project-local storage and retry."
    )


def _normalise_local_file(value: object, *, field: str) -> str:
    location = _text(value)
    if not location:
        raise ValueError(f"{field} is required")
    if "\x00" in location or location.startswith(("//", "\\\\")):
        raise ValueError(f"{field} must be a local project file")
    uri_scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", location)
    windows_drive = re.match(r"^[A-Za-z]:[\\/]", location)
    if "://" in location or (uri_scheme and not windows_drive):
        raise ValueError(f"{field} must be a local project file")
    if ".." in re.split(r"[\\/]", location):
        raise ValueError(f"{field} must not contain parent traversal")
    return Path(location).as_posix()


def _resolve_local_path(value: object, supplied_root: Path, *, field: str, project_local: bool = False) -> Path:
    supplied = Path(supplied_root).resolve()
    if project_local:
        _normalise_storage_location(value)
        return supplied
    normalised = _normalise_local_file(value, field=field)
    candidate = Path(normalised)
    if candidate.is_absolute():
        return candidate.resolve()
    resolved = (supplied / candidate).resolve()
    if not resolved.is_relative_to(supplied):
        raise ValueError(f"{field} must remain beneath the supplied root")
    return resolved


def _selected_storage_root(profile: OnboardingProfile) -> Path:
    _normalise_storage_location(profile.storage_location)
    return ROOT.resolve()


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(str(path)))


def _reject_symlink_path(path: Path, *, field: str) -> None:
    absolute = _absolute_path(path)
    resolved = absolute.resolve(strict=False)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(absolute)):
        raise ValueError(f"{field} contains a symlink or escaped destination")
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{field} contains a symlink: {current}")


class _CheckedDestination:
    """Revalidate a destination before the atomic writer resolves it."""

    def __init__(self, path: Path, field: str) -> None:
        self._path = Path(path)
        self._field = field

    def _check(self) -> None:
        _reject_symlink_path(self._path, field=self._field)

    def __fspath__(self) -> str:
        self._check()
        return os.fspath(self._path)

    @property
    def parent(self) -> Path:
        self._check()
        return self._path.parent

    @property
    def name(self) -> str:
        self._check()
        return self._path.name

    def resolve(self, *args: object, **kwargs: object) -> Path:
        self._check()
        return self._path.resolve(*args, **kwargs)


def _existing_volume(path: Path) -> tuple[str, int | str]:
    candidate = _absolute_path(path)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    try:
        return ("device", int(candidate.stat().st_dev))
    except OSError as exc:
        raise ValueError(f"cannot inspect storage volume for {path}: {exc}") from exc


def _preflight_onboarding_destinations(paths: Iterable[tuple[Path, str]]) -> None:
    destinations = tuple((_absolute_path(path), field) for path, field in paths)
    if not destinations:
        raise ValueError("onboarding has no destinations")
    for destination, field in destinations:
        _reject_symlink_path(destination, field=field)
        _reject_symlink_path(destination.parent, field=f"{field} parent")
        nearest = destination
        while not nearest.exists():
            parent = nearest.parent
            if parent == nearest:
                break
            nearest = parent
        if not nearest.exists() or not os.access(nearest, os.W_OK):
            raise ValueError(f"onboarding destination is not writable: {destination}")
    volumes = {_existing_volume(destination.parent) for destination, _field in destinations}
    if len(volumes) != 1:
        raise ValueError("onboarding outputs span storage volumes; grouped publish is unavailable")
    try:
        Path(os.path.commonpath([str(destination.parent) for destination, _field in destinations]))
    except ValueError as exc:
        raise ValueError("onboarding outputs do not have one grouped local transaction root") from exc


def overlay_universe_config(active_config: object, selected_config: object) -> object:
    """Overlay only the selected universe onto the active non-universe config."""

    selected_universe = getattr(selected_config, "universe", None)
    if selected_universe is None:
        return active_config
    model_copy = getattr(active_config, "model_copy", None)
    if callable(model_copy):
        return model_copy(update={"universe": selected_universe})
    try:
        from copy import copy

        result = copy(active_config)
        result.universe = selected_universe
        return result
    except (AttributeError, TypeError):
        return selected_config


def _onboarding_document_path(_root: Path | None = None) -> tuple[Path, Path]:
    canonical = ROOT.resolve()
    direct = canonical / "configs" / "onboarding.json"
    return direct, canonical


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
        "bootstrap": {
            "mode": _text(profile.bootstrap_mode).casefold(),
            "offline": True,
            "bulk_source_path": _normalise_local_file(profile.bulk_source_path, field="bulk_source_path") if _text(profile.bulk_source_path) else "",
        },
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
            "bulk_source_path": bootstrap["bulk_source_path"],
            "encryption_preference": privacy["encryption_preference"],
            "backup_preference": privacy["backup_preference"],
            "execution_allowed": False,
            "staged_execution_enabled": False,
        }
    )
    return profile_payload, setup


def _canonical_scopes(values: Iterable[str]) -> tuple[str, ...]:
    scopes: list[str] = []
    raw_values = tuple(values)
    for raw in raw_values:
        value = _text(raw).lower()
        if value in {"both", "stock+etf"}:
            scopes.extend(("stock", "etf"))
        elif value == "all":
            scopes.extend(("stock", "etf", "fund", "bond"))
        elif value in {"stock", "etf", "fund", "bond"}:
            scopes.append(value)
        elif not _TICKER_RE.fullmatch(value):
            raise ValueError("asset_scope contains an unsupported scope or legacy ticker")
    if scopes:
        if len(scopes) != len(raw_values) and not all(_text(value).lower() in _ASSET_SCOPES for value in raw_values):
            raise ValueError("asset_scope cannot mix scopes and legacy tickers")
        return tuple(dict.fromkeys(scopes))
    # Compatibility with the original positional ticker form is limited to
    # shape-valid symbols and is normalised to the safe stock scope so the
    # persisted document remains loadable.
    if raw_values and all(_TICKER_RE.fullmatch(_text(value).upper()) for value in raw_values):
        return ("stock",)
    raise ValueError("asset_scope must contain a supported scope")


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
    validator: Callable[[str], bool | TickerValidationResult] | None = None,
    online: bool = False,
    local_evidence: Iterable[str] = (),
) -> tuple[str, ...]:
    unresolved, _statuses = _validate_tickers_with_status(
        tickers,
        validator=validator,
        online=online,
        local_evidence=local_evidence,
    )
    return unresolved


def _validate_tickers_with_status(
    tickers: Iterable[str],
    *,
    validator: Callable[[str], bool | TickerValidationResult] | None,
    online: bool,
    local_evidence: Iterable[str],
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    evidence = {str(value).strip().upper() for value in local_evidence if str(value).strip()}
    unresolved: list[str] = []
    provider_status: dict[str, str] = {}
    validator_blocked = False
    for raw in tickers:
        symbol = raw.strip().upper()
        if not symbol:
            continue
        valid = bool(_TICKER_RE.fullmatch(symbol))
        if valid and online and validator is not None:
            provider_id = "yfinance"
            if validator_blocked:
                valid = symbol in evidence
            else:
                try:
                    result = validator(symbol)
                except ProviderQuotaExceeded as exc:
                    provider_id = exc.provider_id
                    if provider_id not in _OPTIONAL_PROVIDERS:
                        raise ValueError(f"unsupported validator provider: {provider_id}") from exc
                    provider_status[provider_id] = "quota_exceeded"
                    validator_blocked = True
                    valid = symbol in evidence
                except Exception:
                    provider_status[provider_id] = "unavailable"
                    validator_blocked = True
                    valid = symbol in evidence
                else:
                    if isinstance(result, TickerValidationResult):
                        provider_id = _text(result.provider_id).casefold() or "yfinance"
                        if provider_id not in _OPTIONAL_PROVIDERS:
                            raise ValueError(f"unsupported validator provider: {provider_id}")
                        status = _text(result.status).casefold()
                        if status in {"quota_exceeded", "quota_unavailable"}:
                            provider_status[provider_id] = "quota_exceeded"
                            validator_blocked = True
                            valid = symbol in evidence
                        elif status == "unavailable":
                            provider_status[provider_id] = "unavailable"
                            validator_blocked = True
                            valid = symbol in evidence
                        elif status == "valid":
                            valid = True
                        elif status == "invalid":
                            valid = False
                        else:
                            raise ValueError(f"unsupported validator status: {status}")
                    else:
                        valid = bool(result)
        elif valid:
            # Offline onboarding is local-first: a shape-valid symbol is not
            # evidence of a real instrument. Existing local universe/config
            # identity is the only offline positive signal.
            valid = symbol in evidence
        if not valid or symbol.startswith("UNKNOWN") or symbol.startswith("UNRESOLVED"):
            unresolved.append(symbol)
    return tuple(sorted(set(unresolved))), tuple(sorted(provider_status.items()))


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
    validator: Callable[[str], bool | TickerValidationResult] | None = None,
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
    unresolved, observed_status = _validate_tickers_with_status(
        _profile_tickers(profile),
        validator=validator,
        online=online,
        local_evidence=_local_ticker_evidence(root) if root is not None else (),
    )
    return OnboardingValidation(not errors, tuple(errors), unresolved, observed_status)


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


def _sample_records() -> tuple[UniverseRecord, ...]:
    candidates = (ROOT.resolve() / "configs" / "universe.yaml",)
    by_id: dict[str, UniverseRecord] = {}
    for fixture in candidates:
        if fixture.is_file():
            imported = import_legacy_universe(fixture)
            candidate_records = {record.instrument_id: record for record in imported.records}
            if all(instrument_id in candidate_records for instrument_id in _SAMPLE_INSTRUMENT_IDS):
                by_id = candidate_records
                break
    if not by_id:
        raise ValueError("bundled sample universe fixture is unavailable or incomplete")
    return tuple(
        replace(
            by_id[instrument_id],
            tier="secondary",
            group="Offline onboarding sample",
            data_policy="daily",
            enabled=True,
            notes="Bundled identity-only onboarding sample; local adjusted price history is not included.",
        )
        for instrument_id in _SAMPLE_INSTRUMENT_IDS
    )


def _merge_records(*groups: Iterable[UniverseRecord]) -> tuple[UniverseRecord, ...]:
    merged: dict[str, UniverseRecord] = {}
    ticker_ids: dict[str, str] = {}
    for group in groups:
        for record in group:
            record_id = record.instrument_id.casefold()
            ticker = record.ticker.casefold()
            previous = merged.get(record_id)
            if previous is not None:
                ticker_ids.pop(previous.ticker.casefold(), None)
            duplicate_id = ticker_ids.get(ticker)
            if duplicate_id is not None and duplicate_id != record_id:
                merged.pop(duplicate_id, None)
            merged[record_id] = record
            ticker_ids[ticker] = record_id
    return tuple(merged[key] for key in sorted(merged))


def _bulk_bootstrap(profile: OnboardingProfile, supplied_root: Path, storage_root: Path) -> BootstrapResult:
    if not _text(profile.bulk_source_path):
        return BootstrapResult(
            "bulk",
            "unavailable",
            0,
            (),
            "Select a local CSV/Parquet price file with date, instrument identity and adjusted-close columns.",
        )
    source = _resolve_local_path(profile.bulk_source_path, supplied_root, field="bulk_source_path")
    if not source.is_file():
        return BootstrapResult("bulk", "unavailable", 0, (), f"Local bulk file is unavailable: {source}", source.as_posix())
    preview = validate_import("prices", source)
    if not preview.valid:
        detail = "; ".join(preview.errors) or "validation_failed"
        return BootstrapResult("bulk", "unavailable", 0, (), f"Local bulk file is not importable: {detail}", source.as_posix())
    columns = {column.casefold() for column in preview.columns}
    if not columns.intersection({"adjusted_close", "adj_close"}):
        return BootstrapResult(
            "bulk",
            "unavailable",
            0,
            (),
            "Local bulk prices require an explicit adjusted_close or adj_close column; raw close was not imported.",
            source.as_posix(),
        )
    return BootstrapResult(
        "bulk",
        "unavailable",
        0,
        (),
        "Local bulk source validated, but a canonical conflict-safe price import is unavailable; action required and zero price files were written.",
        source.as_posix(),
    )


def _stage_universe_payload(
    records: tuple[UniverseRecord, ...],
    *,
    expected_revision: str,
    storage_root: Path,
) -> tuple[bytes, str]:
    """Build a canonical universe candidate without mutating the selected root."""

    with tempfile.TemporaryDirectory(prefix="etf-cockpit-onboarding-") as temporary:
        stage_root = Path(temporary)
        stage_store = stage_root / "configs" / "universe_store.json"
        target_store = storage_root / "configs" / "universe_store.json"
        stage_store.parent.mkdir(parents=True, exist_ok=True)
        if target_store.is_file():
            stage_store.write_bytes(target_store.read_bytes())
        saved = save_universe(records, expected_revision=expected_revision, root=stage_root)
        return stage_store.read_bytes(), saved.revision


def _assert_universe_revision(path: Path, expected_revision: str) -> None:
    if not path.is_file():
        actual = ""
    else:
        # The grouped writer already holds the complete guard closure here;
        # acquiring a nested reader guard would deadlock on Windows.
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual = str(payload.get("revision") or "") if isinstance(payload, dict) else ""
    if actual != expected_revision:
        raise ValueError(
            f"Onboarding universe changed before grouped publish: expected {expected_revision or '<empty>'}, found {actual or '<empty>'}"
        )


def _revalidate_onboarding_destinations(destinations: Iterable[tuple[Path, str]]) -> None:
    """Recheck path identity after atomic group guards are held."""

    for destination, field in destinations:
        _reject_symlink_path(destination, field=field)
        _reject_symlink_path(destination.parent, field=f"{field} parent")


def _bootstrap_payload(result: BootstrapResult) -> dict[str, object]:
    return {
        "mode": result.mode,
        "offline": True,
        "status": result.status,
        "rows": result.rows,
        "output_paths": list(result.output_paths),
        "message": result.message,
        "source_path": result.source_path,
        "market_data_status": result.market_data_status,
        "execution_allowed": False,
    }


def complete_onboarding(
    profile: OnboardingProfile,
    root: Path,
    *,
    online: bool = False,
    validator: Callable[[str], bool | TickerValidationResult] | None = None,
    optional_provider_status: Mapping[str, str] | None = None,
    provider_status: Mapping[str, str] | None = None,
) -> OnboardingResult:
    del root
    supplied_root = ROOT.resolve()
    statuses = dict(optional_provider_status or {})
    if provider_status is not None:
        if statuses:
            raise ValueError("provide only one optional provider status mapping")
        statuses = dict(provider_status)
    if statuses:
        profile = replace(profile, optional_provider_status=tuple(statuses.items()))
    storage_root = _selected_storage_root(profile)
    profile_payload, setup_payload = _canonical_profile(profile)
    privacy_payload = setup_payload["privacy"]
    assert isinstance(privacy_payload, dict)
    backup_preference = str(privacy_payload["backup_preference"])
    if backup_preference in {"disabled", "encrypted"}:
        raise ValueError(
            f"backup_preference={backup_preference} is unsupported by the local plaintext backup path; action required and no onboarding writes were made"
        )
    validation = validate_onboarding(profile, validator=validator, online=online, root=storage_root)
    if not validation.valid:
        raise ValueError("Onboarding validation failed: " + ", ".join(validation.errors))
    if validation.optional_provider_status:
        observed = dict(profile.optional_provider_status)
        observed.update(dict(validation.optional_provider_status))
        optional = tuple(sorted(set(profile.optional_providers) | set(observed)))
        profile = replace(profile, optional_providers=optional, optional_provider_status=tuple(sorted(observed.items())))
        profile_payload, setup_payload = _canonical_profile(profile)

    profile_records = _onboarding_records(profile, validation.unresolved_symbols)
    current = load_universe(storage_root)
    existing_records = current.records
    legacy_universe = storage_root / "configs" / "universe.yaml"
    if not existing_records and legacy_universe.is_file():
        existing_records = import_legacy_universe(legacy_universe).records
    bootstrap: BootstrapResult
    candidate_records: tuple[UniverseRecord, ...] | None
    if profile.bootstrap_mode.casefold() == "sample":
        sample_fixture = _sample_records()
        occupied_tickers = {record.ticker.casefold() for record in (*existing_records, *profile_records)}
        occupied_ids = {record.instrument_id.casefold() for record in (*existing_records, *profile_records)}
        samples = tuple(
            record
            for record in sample_fixture
            if record.ticker.casefold() not in occupied_tickers and record.instrument_id.casefold() not in occupied_ids
        )
        records = _merge_records(existing_records, samples, profile_records)
        sample_tickers = {record.ticker.casefold() for record in sample_fixture}
        sample_rows = sum(record.ticker.casefold() in sample_tickers for record in records)
        bootstrap = BootstrapResult(
            "sample",
            "ready",
            sample_rows,
            ((storage_root / "configs" / "universe_store.json").relative_to(storage_root).as_posix(),),
            "Bundled identity-only sample created; import local adjusted price history before analysis.",
        )
        candidate_records = records
    else:
        bootstrap = _bulk_bootstrap(profile, supplied_root, storage_root)
        if profile_records:
            records = _merge_records(existing_records, profile_records)
            candidate_records = records
        else:
            records = existing_records
            candidate_records = None
            revision = current.revision

    path = storage_root / "configs" / "onboarding.json"
    universe_path = storage_root / "configs" / "universe_store.json"
    prices_path = storage_root / "data" / "clean" / "prices.parquet"
    _preflight_onboarding_destinations(
        (
            (path, "onboarding settings"),
            (universe_path, "universe store"),
            (prices_path, "canonical prices"),
        )
    )
    universe_payload: bytes | None = None
    if candidate_records is not None:
        universe_payload, revision = _stage_universe_payload(
            candidate_records,
            expected_revision=current.revision,
            storage_root=storage_root,
        )
    else:
        revision = current.revision

    setup_payload["resolved_storage_root"] = storage_root.as_posix()
    bootstrap_payload = _bootstrap_payload(bootstrap)
    bootstrap_payload["bulk_source_path"] = profile_payload["bulk_source_path"]
    setup_payload["bootstrap"] = bootstrap_payload
    payload = {
        "schema_version": ONBOARDING_SCHEMA_VERSION,
        "profile": profile_payload,
        "setup": setup_payload,
        "unresolved_symbols": list(validation.unresolved_symbols),
        "storage_root": storage_root.as_posix(),
        "execution_allowed": False,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    requests = [
        AtomicWriteRequest(_CheckedDestination(path, "onboarding settings"), encoded, lambda candidate: json.loads(candidate.read_text(encoding="utf-8"))),
    ]
    if universe_payload is not None:
        requests.append(
            AtomicWriteRequest(
                _CheckedDestination(universe_path, "universe store"),
                universe_payload,
                lambda candidate: json.loads(candidate.read_text(encoding="utf-8")),
            )
        )
    def precondition() -> None:
        destinations = (
            (path, "onboarding settings"),
            (universe_path, "universe store"),
            (prices_path, "canonical prices"),
        )
        _revalidate_onboarding_destinations(destinations)
        _assert_universe_revision(universe_path, current.revision)

    atomic_write_group(requests, precondition=precondition)
    provider_payload = setup_payload["providers"]
    assert isinstance(provider_payload, dict)
    status_payload = provider_payload["optional_status"]
    assert isinstance(status_payload, dict)
    return OnboardingResult(
        True,
        validation.unresolved_symbols,
        records,
        revision,
        tuple(sorted((str(key), str(value)) for key, value in status_payload.items())),
        storage_root.as_posix(),
        bootstrap,
    )


def load_onboarding(_root: Path | None = None) -> OnboardingProfile:
    """Load the persisted profile from the canonical project-local root."""

    path, storage_root = _onboarding_document_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"onboarding settings cannot be loaded: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != ONBOARDING_SCHEMA_VERSION:
        raise ValueError("onboarding settings schema is unsupported")
    if payload.get("execution_allowed") is not False:
        raise ValueError("onboarding execution_allowed must remain false")
    if payload.get("storage_root") != storage_root.as_posix():
        raise ValueError("onboarding storage root does not match its document location")
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
    if setup.get("resolved_storage_root") != storage_root.as_posix():
        raise ValueError("onboarding resolved storage root is invalid")
    if setup.get("storage_location") != "project_local":
        raise ValueError("onboarding storage location is unsupported; choose project-local storage")
    if bootstrap.get("offline") is not True or bootstrap.get("execution_allowed") is not False or execution.get("execution_allowed") is not False:
        raise ValueError("onboarding setup safety defaults are invalid")
    if bootstrap.get("status") not in {"ready", "unavailable"} or bootstrap.get("mode") not in _BOOTSTRAP_MODES:
        raise ValueError("onboarding bootstrap state is invalid")
    if not isinstance(bootstrap.get("rows"), int) or int(bootstrap["rows"]) < 0 or not isinstance(bootstrap.get("output_paths"), list):
        raise ValueError("onboarding bootstrap evidence is invalid")
    if not _text(bootstrap.get("message")) or bootstrap.get("market_data_status") not in {"available", "unavailable"}:
        raise ValueError("onboarding bootstrap evidence is incomplete")
    output_paths: list[Path] = []
    for raw_output in bootstrap["output_paths"]:
        if not isinstance(raw_output, str) or not raw_output or Path(raw_output).is_absolute() or ".." in Path(raw_output).parts:
            raise ValueError("onboarding bootstrap output path is unsafe")
        output = (storage_root / raw_output).resolve()
        if not output.is_relative_to(storage_root) or not output.is_file():
            raise ValueError("onboarding bootstrap output is unavailable")
        output_paths.append(output)
    if bootstrap["status"] == "ready" and not output_paths:
        raise ValueError("ready onboarding bootstrap requires a local output")
    if bootstrap["status"] == "unavailable" and output_paths:
        raise ValueError("unavailable onboarding bootstrap cannot claim outputs")
    if execution.get("staged_execution_enabled") is not False or execution.get("paper_enabled") is not False or execution.get("broker_write_enabled") is not False:
        raise ValueError("onboarding staged-execution defaults must remain disabled")
    mirrored_profile = {
        "storage_location": setup.get("storage_location"),
        "hardware_profile": setup.get("hardware_profile"),
        "mandatory_providers": providers.get("mandatory"),
        "optional_providers": providers.get("optional"),
        "optional_provider_status": providers.get("optional_status"),
        "bootstrap_mode": bootstrap.get("mode"),
        "bulk_source_path": bootstrap.get("bulk_source_path"),
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
            str(bootstrap["bulk_source_path"]),
        )
        validation = validate_onboarding(profile, root=storage_root)
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
    validator: Callable[[str], bool | TickerValidationResult] | None = None,
) -> ft.Control:
    base_currency = ft.Dropdown(label="Output currency", value="EUR", options=[ft.dropdown.Option(item) for item in OUTPUT_CURRENCIES], width=180, dense=True)
    region = ft.TextField(label="Region", value="Europe", width=220, dense=True)
    scope = ft.Dropdown(label="Asset scope", value="stock+etf", options=[ft.dropdown.Option(item) for item in ("stock", "etf", "fund", "bond", "stock+etf", "all")], width=180, dense=True)
    risk = ft.Dropdown(label="Risk profile", value="medium", options=[ft.dropdown.Option(item) for item in RISK_PROFILES], width=220, dense=True)
    horizon = ft.Dropdown(label="Target horizon", value="3M", options=[ft.dropdown.Option(item) for item in HORIZONS], width=180, dense=True)
    analysis_depth = ft.Dropdown(label="Analysis depth", value="medium", options=[ft.dropdown.Option(item) for item in ANALYSIS_DEPTHS], width=180, dense=True)
    storage_location = ft.Dropdown(
        label="Storage location",
        value="project_local",
        options=[ft.dropdown.Option("project_local", "Project-local")],
        width=220,
        dense=True,
    )
    hardware_profile = ft.Dropdown(label="Hardware profile", value="auto", options=[ft.dropdown.Option(item) for item in sorted(_HARDWARE_PROFILES)], width=180, dense=True)
    mandatory_provider = ft.Dropdown(label="Mandatory provider", value="manual_local", options=[ft.dropdown.Option(item) for item in sorted(_MANDATORY_PROVIDERS)], width=220, dense=True)
    optional_providers = ft.TextField(label="Optional providers (comma separated)", hint_text="yfinance, fred", width=280, dense=True)
    bootstrap_mode = ft.Dropdown(label="Offline bootstrap", value="sample", options=[ft.dropdown.Option(item) for item in sorted(_BOOTSTRAP_MODES)], width=180, dense=True)
    bulk_source_path = ft.TextField(label="Local bulk price file", hint_text="data/import/prices.csv", width=280, dense=True, key="onboarding.bulk-source")
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
    status = ft.Text("", color=theme.MUTED, selectable=True, key="onboarding.status")
    project_root = ROOT.resolve()
    try:
        source_rows = source_policy_rows(project_root, project_root / "configs" / "data_source_policy.yaml")
        source_summary = "\n".join(
            f"{row['provider_id']}: tier={row['source_tier']} | {row['optionality']} | cache={row['cache_status']} | network={row['network']}"
            for row in source_rows
        )
    except (OSError, ValueError):
        try:
            source_rows = source_policy_rows(project_root, project_root / "configs" / "data_source_policy.yaml")
            source_summary = (
                "Current-directory policy unavailable; using bundled local policy.\n"
                + "\n".join(
                    f"{row['provider_id']}: tier={row['source_tier']} | {row['optionality']} | cache={row['cache_status']} | network={row['network']}"
                    for row in source_rows
                )
            )
        except (OSError, ValueError) as exc:
            source_summary = f"Data source policy unavailable: {type(exc).__name__}; mandatory policy choices require explicit local action."
    try:
        legal_report = legal_terms_report(project_root, project_root / "configs" / "legal_terms_registry.yaml")
    except (OSError, ValueError):
        try:
            legal_report = legal_terms_report(project_root, project_root / "configs" / "legal_terms_registry.yaml")
        except (OSError, ValueError):
            legal_report = {
                "jurisdictions": [{"disclaimer": "Legal terms registry unavailable; review local terms before use."}],
                "review_status": "unavailable",
                "registry_sha256": "unavailable",
            }
    jurisdiction_disclaimer = str(legal_report["jurisdictions"][0]["disclaimer"])
    selected_profile_id = "auto"
    try:
        selected_profile_id = load_onboarding(ROOT).hardware_profile
    except ValueError:
        pass
    resource_report = resource_profile_report(ROOT, requested_profile=selected_profile_id)
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
        if online_validation.value and validator is not None and "yfinance" not in {item.casefold() for item in selected_optional}:
            selected_optional = (*selected_optional, "yfinance")
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
            bulk_source_path=bulk_source_path.value or "",
        )
        try:
            result = complete_onboarding(
                profile,
                ROOT,
                online=bool(online_validation.value),
                validator=validator,
            )
            if result.revision and state is not None:
                refreshed_config = load_config(ROOT / "configs") if result.storage_root else load_config()
                if result.storage_root and getattr(state, "snapshot", None) is not None:
                    refreshed_config = overlay_universe_config(state.snapshot.config, refreshed_config)
                apply_method = getattr(state, "apply_universe_config", None)
                if callable(apply_method):
                    apply_method(refreshed_config, result.revision)
                else:
                    state.snapshot.config = refreshed_config
                    state.snapshot.universe_revision = result.revision
                    state.universe_cache_revision = result.revision
            if state is not None:
                refresh_profile = getattr(state, "refresh_runtime_profile", None)
                if callable(refresh_profile):
                    refresh_profile(profile.hardware_profile)
            optional_status = ", ".join(f"{provider}: {state}" for provider, state in result.optional_provider_status if state == "quota_exceeded")
            suffix = f" Optional provider status: {optional_status}; mandatory setup was not blocked." if optional_status else ""
            bootstrap_status = f" Bootstrap {result.bootstrap.mode}: {result.bootstrap.status} — {result.bootstrap.message}" if result.bootstrap else ""
            status.value = f"Saved locally at {result.storage_root}. {len(result.unresolved_symbols)} unresolved ticker(s) remain disabled; no refresh or model run was started.{bootstrap_status}{suffix}"
        except Exception as exc:
            status.value = f"Setup not saved: {exc}"
        page.update()

    return ft.Column(
        [
            panel(ft.Column([section_header("First-run setup", "Create a local watchlist without requiring network access."), ft.Text(f"{jurisdiction_disclaimer} Offline or unresolved tickers remain disabled until validated. Online validation is opt-in and requires an injected provider callback.", color=theme.MUTED), ft.Row([base_currency, region, scope, risk, horizon, analysis_depth], wrap=True), ft.Row([storage_location, ft.Text(f"Project-local runtime root: {ROOT}", color=theme.MUTED), hardware_profile, mandatory_provider, optional_providers, bootstrap_mode, bulk_source_path, encryption_preference, backup_preference], wrap=True), ft.Text("Sample creates a shipped identity-only universe without fabricated prices. Bulk accepts only an explicit local price file and remains visibly unavailable when absent or invalid.", color=theme.MUTED, size=11), ft.Text("Mandatory providers are offline-compatible. Optional provider absence or quota failure is recorded visibly and never blocks setup.", color=theme.MUTED, size=11), ft.Text("Quick/Medium/High/Full are versioned analysis-effort selections; warm/cold timing effects remain unavailable until ISSUE-0175.", color=theme.MUTED, size=11), ft.ResponsiveRow([ft.Container(content=tickers, col={"xs": 12, "md": 9}), ft.Container(content=ft.Button("Save setup", key="onboarding.save", icon=ft.Icons.SAVE, on_click=submit), col={"xs": 12, "md": 3})], spacing=8, run_spacing=8), online_validation, status], spacing=10)),
            panel(ft.Column([section_header("Hardware and resource readiness", "Local profile selection, pre-job limits and graceful degradation. No telemetry or cloud compute is used."), ft.SelectionArea(ft.Text("\n".join(resource_lines), color=theme.MUTED)), ft.SelectionArea(ft.Text("CPU-only baseline remains available; optional foundation models are never required.", color=theme.GREEN))], spacing=6)),
            panel(ft.Column([section_header("Authority boundary", "Setup stores preferences only. It never grants broker/provider write authority or starts execution."), ft.Text("execution_allowed=false | staged_execution_enabled=false | paper_enabled=false | broker_write_enabled=false", color=theme.AMBER)])),
            panel(ft.Column([section_header("Data source policy", "Choose local imports or replayable official evidence for the mandatory path. Online validation is optional and never required for setup."), ft.Text(source_summary, color=theme.MUTED, size=11, selectable=True), ft.Text(f"Terms acknowledgement: {legal_report['review_status']}; restricted sources are not redistributed. Registry checksum: {legal_report['registry_sha256']}", color=theme.AMBER, size=11, selectable=True)])),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
