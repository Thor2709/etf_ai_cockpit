"""Typed, staged and versioned local settings control.

This module is the sole application boundary for ISSUE-0037 settings.  It
never stores credentials, performs provider I/O or grants execution authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
from etf_cockpit.core.config import CostConfig, ModelSettings, PortfolioTargets, RiskLimits


SETTINGS_SCHEMA_VERSION = "settings_bundle.v1"
SETTINGS_SEMANTIC_VERSION = "1.0.0"
ASSET_SCOPES = ("stock", "etf", "fund", "bond")
RISK_PROFILES = ("safe", "safe_medium", "medium", "medium_aggressive", "aggressive")
HORIZONS = ("1W", "1M", "3M", "6M", "9M", "2Y", "5Y")
ANALYSIS_DEPTHS = ("quick", "medium", "high", "full")
OUTPUT_CURRENCIES = ("AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NOK", "SEK", "USD")
PROVIDER_IDS = (
    "none",
    "local",
    "manual_local",
    "yfinance",
    "sec_edgar",
    "filings_xbrl_org",
    "fred",
    "stooq",
    "rss",
    "issuer_document",
    "index_provider",
)
_SECRET_FIELD_SUFFIXES = (
    "apikey",
    "privatekey",
    "signingkey",
    "encryptionkey",
    "password",
    "passphrase",
    "secret",
    "token",
    "credential",
    "credentials",
    "authorization",
)


class SettingsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class PaperSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    initial_cash_eur: float = Field(default=100_000.0, gt=0, le=100_000_000.0)
    execution_allowed: bool = False

    @field_validator("execution_allowed")
    @classmethod
    def execution_is_never_enabled(cls, value: bool) -> bool:
        if value:
            raise ValueError("execution_allowed must remain false")
        return False


class SettingsControls(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output_currency: str = "EUR"
    asset_scopes: tuple[str, ...] = ("stock", "etf")
    risk_profile: str = "medium"
    horizon: str = "3M"
    analysis_depth: str = "medium"
    news_sources: tuple[str, ...] = ()
    rss_sources: tuple[str, ...] = ()
    macro_provider: str = "none"
    paper: PaperSettings = Field(default_factory=PaperSettings)


class SecretFreeProviderSection(BaseModel):
    """Persistable provider metadata; credentials are deliberately absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_provider: str = "none"
    base_url: str = ""
    symbols_map: dict[str, str] = Field(default_factory=dict)


class SecretFreeProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    providers: dict[str, SecretFreeProviderSection] = Field(default_factory=dict)


class SettingsMigrationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field: str
    legacy_value: object
    message: str


class SettingsBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SETTINGS_SCHEMA_VERSION
    semantic_version: str = SETTINGS_SEMANTIC_VERSION
    settings_version: int = Field(default=0, ge=0)
    revision: str = ""
    controls: SettingsControls = Field(default_factory=SettingsControls)
    universe: dict[str, object] = Field(default_factory=dict)
    targets: dict[str, object] = Field(default_factory=dict)
    risks: dict[str, object] = Field(default_factory=dict)
    costs: dict[str, object] = Field(default_factory=dict)
    models: dict[str, object] = Field(default_factory=dict)
    providers: dict[str, object] = Field(default_factory=dict)
    execution_allowed: bool = False

    @field_validator("execution_allowed")
    @classmethod
    def execution_is_never_enabled(cls, value: bool) -> bool:
        if value:
            raise ValueError("execution_allowed must remain false")
        return False

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "SettingsBundle":
        secret_path = _find_secret_path(value)
        if secret_path is not None:
            raise SettingsError("SETTINGS_SECRET_FIELD_FORBIDDEN", f"secret field is forbidden: {secret_path}")
        try:
            bundle = cls.model_validate(value)
        except ValidationError as exc:
            raise SettingsError("SETTINGS_SCHEMA_INVALID", str(exc)) from exc
        if bundle.schema_version != SETTINGS_SCHEMA_VERSION or bundle.semantic_version != SETTINGS_SEMANTIC_VERSION:
            raise SettingsError("SETTINGS_SCHEMA_INVALID", "unsupported settings schema or semantic version")
        expected = _revision_for(bundle)
        if bundle.revision and bundle.revision != expected:
            raise SettingsError("SETTINGS_SCHEMA_INVALID", "settings revision does not match content")
        bundle = bundle.model_copy(update={"revision": expected})
        _validate_bundle(bundle)
        return bundle


class SettingsPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    before_revision: str
    after_revision: str
    changed_fields: tuple[str, ...]
    creates_new_run: bool
    run_effects: dict[str, str]
    warnings: tuple[str, ...]
    execution_allowed: bool = False


class SettingsSaveResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    saved: bool
    revision: str
    settings_version: int
    snapshot_path: str
    creates_new_run: bool
    execution_allowed: bool = False


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _identity_payload(bundle: SettingsBundle) -> dict[str, object]:
    return bundle.model_dump(mode="json", exclude={"revision"})


def _semantic_payload(bundle: SettingsBundle) -> dict[str, object]:
    return bundle.model_dump(mode="json", exclude={"revision", "settings_version"})


def _revision_for(bundle: SettingsBundle) -> str:
    return hashlib.sha256(_canonical_bytes(_identity_payload(bundle))).hexdigest()


def _find_secret_path(value: object, prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            if _is_secret_field_name(name):
                return path
            found = _find_secret_path(item, path)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _find_secret_path(item, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _find_populated_secret_path(value: object, prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            if _is_secret_field_name(name) and item not in (None, "", [], {}):
                return path
            found = _find_populated_secret_path(item, path)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _find_populated_secret_path(item, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _strip_secret_fields(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_secret_fields(item)
            for key, item in value.items()
            if not _is_secret_field_name(str(key))
        }
    if isinstance(value, list):
        return [_strip_secret_fields(item) for item in value]
    return value


def _is_secret_field_name(name: str) -> bool:
    normalised = re.sub(r"[^a-z0-9]", "", name.casefold())
    return any(normalised.endswith(suffix) for suffix in _SECRET_FIELD_SUFFIXES)


def _read_yaml(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError("SETTINGS_SCHEMA_INVALID", f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SettingsError("SETTINGS_SCHEMA_INVALID", f"{path} must contain an object")
    return {str(key): item for key, item in payload.items()}


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError("SETTINGS_SCHEMA_INVALID", f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SettingsError("SETTINGS_SCHEMA_INVALID", f"{path} must contain an object")
    return payload


def _universe_summary(root: Path) -> dict[str, object]:
    config_dir = root / "configs"
    store = _read_json(config_dir / "universe_store.json")
    if store:
        records = store.get("records") if isinstance(store.get("records"), list) else []
        source = config_dir / "universe_store.json"
    else:
        raw = _read_yaml(config_dir / "universe.yaml")
        records = raw.get("etfs") if isinstance(raw.get("etfs"), list) else []
        source = config_dir / "universe.yaml"
    ids = sorted(
        str(row.get("instrument_id") or row.get("id"))
        for row in records
        if isinstance(row, dict) and (row.get("instrument_id") or row.get("id"))
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else "unavailable"
    return {"source": source.relative_to(root).as_posix(), "revision": digest, "instrument_ids": ids, "count": len(ids)}


def _base_bundle(root: Path, controls: SettingsControls) -> SettingsBundle:
    config_dir = root / "configs"
    raw_providers = _read_yaml(config_dir / "data_providers.yaml")
    secret_path = _find_populated_secret_path(raw_providers)
    if secret_path is not None:
        raise SettingsError("SETTINGS_SECRET_FIELD_FORBIDDEN", f"populated secret field is forbidden: {secret_path}")
    providers = _strip_secret_fields(raw_providers)
    value = SettingsBundle(
        controls=controls,
        universe=_universe_summary(root),
        targets=_read_yaml(config_dir / "portfolio_targets.yaml"),
        risks=_read_yaml(config_dir / "risk_limits.yaml"),
        costs=_read_yaml(config_dir / "costs.yaml"),
        models=_read_yaml(config_dir / "model_settings.yaml"),
        providers=providers if isinstance(providers, dict) else {},
    )
    return value.model_copy(update={"revision": _revision_for(value)})


def migrate_legacy_settings(root: Path) -> tuple[SettingsBundle, tuple[SettingsMigrationIssue, ...]]:
    root = Path(root).resolve()
    profile = _read_json(root / "configs" / "onboarding.json").get("profile", {})
    if not isinstance(profile, dict):
        profile = {}
    issues: list[SettingsMigrationIssue] = []

    raw_currency = str(profile.get("base_currency") or "EUR").strip().upper()
    currency = raw_currency if raw_currency in OUTPUT_CURRENCIES else "EUR"
    if raw_currency not in OUTPUT_CURRENCIES:
        issues.append(SettingsMigrationIssue(code="SETTINGS_CURRENCY_UNSUPPORTED", field="output_currency", legacy_value=raw_currency, message="Legacy currency is not in validated local coverage; EUR retained."))

    raw_scopes = profile.get("asset_scope", ["both"])
    if isinstance(raw_scopes, str):
        raw_scopes = [raw_scopes]
    scope_map = {"both": ("stock", "etf"), "stock": ("stock",), "etf": ("etf",), "fund": ("fund",), "bond": ("bond",), "all": ASSET_SCOPES}
    scopes: list[str] = []
    unknown_scope = False
    for raw in raw_scopes if isinstance(raw_scopes, list) else []:
        mapped = scope_map.get(str(raw).strip().lower())
        if mapped is None:
            unknown_scope = True
        else:
            scopes.extend(mapped)
    if unknown_scope or not scopes:
        issues.append(SettingsMigrationIssue(code="SETTINGS_MIGRATION_REVIEW_REQUIRED", field="asset_scopes", legacy_value=raw_scopes, message="Legacy asset scope requires manual review; stock/ETF retained."))
        scopes = ["stock", "etf"]

    raw_risk = str(profile.get("risk_profile") or "balanced").strip().lower()
    risk_map = {"conservative": "safe", "balanced": "medium", "growth": "aggressive", **{item: item for item in RISK_PROFILES}}
    risk = risk_map.get(raw_risk)
    if risk is None:
        issues.append(SettingsMigrationIssue(code="SETTINGS_MIGRATION_REVIEW_REQUIRED", field="risk_profile", legacy_value=raw_risk, message="Legacy risk profile requires manual review; medium retained."))
        risk = "medium"

    raw_horizon = str(profile.get("horizon") or "medium").strip()
    horizon_map = {"short": "1M", "medium": "3M", "long": "9M", **{item.casefold(): item for item in HORIZONS}}
    horizon = horizon_map.get(raw_horizon.casefold())
    if horizon is None:
        issues.append(SettingsMigrationIssue(code="SETTINGS_MIGRATION_REVIEW_REQUIRED", field="horizon", legacy_value=raw_horizon, message="Legacy horizon requires manual review; 3M retained."))
        horizon = "3M"

    raw_depth = str(profile.get("analysis_depth") or "medium").strip().lower()
    depth = raw_depth if raw_depth in ANALYSIS_DEPTHS else "medium"
    if raw_depth not in ANALYSIS_DEPTHS:
        issues.append(SettingsMigrationIssue(code="SETTINGS_MIGRATION_REVIEW_REQUIRED", field="analysis_depth", legacy_value=raw_depth, message="Legacy depth requires manual review; medium retained."))

    raw_macro_provider = str(profile.get("macro_provider") or "none").strip()
    macro_provider = raw_macro_provider if raw_macro_provider in PROVIDER_IDS else "none"
    if raw_macro_provider not in PROVIDER_IDS:
        issues.append(SettingsMigrationIssue(code="SETTINGS_PROVIDER_UNSUPPORTED", field="macro_provider", legacy_value=raw_macro_provider, message="Legacy macro provider is unsupported; none retained."))

    controls = SettingsControls(
        output_currency=currency,
        asset_scopes=tuple(dict.fromkeys(scopes)),
        risk_profile=risk,
        horizon=horizon,
        analysis_depth=depth,
        news_sources=tuple(str(item) for item in profile.get("news_sources", ()) if str(item).strip()) if isinstance(profile.get("news_sources", ()), list) else (),
        rss_sources=tuple(str(item) for item in profile.get("rss_sources", ()) if str(item).strip()) if isinstance(profile.get("rss_sources", ()), list) else (),
        macro_provider=macro_provider,
    )
    return _base_bundle(root, controls), tuple(issues)


def load_settings_bundle(root: Path) -> SettingsBundle:
    return load_settings_bundle_with_issues(root)[0]


def load_settings_bundle_with_issues(root: Path) -> tuple[SettingsBundle, tuple[SettingsMigrationIssue, ...]]:
    """Load effective settings and retain any read-only legacy diagnostics."""

    root = Path(root).resolve()
    path = root / "configs" / "settings.yaml"
    if not path.is_file():
        bundle, issues = migrate_legacy_settings(root)
        _validate_bundle(bundle)
        return bundle, issues
    raw = _read_yaml(path)
    secret_path = _find_secret_path(raw)
    if secret_path is not None:
        raise SettingsError("SETTINGS_SECRET_FIELD_FORBIDDEN", f"secret field is forbidden: {secret_path}")
    try:
        controls = SettingsControls.model_validate(raw.get("controls", {}))
        settings_version = int(raw.get("settings_version", 0))
    except (ValidationError, TypeError, ValueError) as exc:
        raise SettingsError("SETTINGS_SCHEMA_INVALID", str(exc)) from exc
    if raw.get("schema_version") != SETTINGS_SCHEMA_VERSION or raw.get("semantic_version") != SETTINGS_SEMANTIC_VERSION:
        raise SettingsError("SETTINGS_SCHEMA_INVALID", "unsupported settings schema or semantic version")
    # A shipped version-zero default is not allowed to erase an older user's
    # onboarding choices.  Project the legacy values in memory and require the
    # ordinary preview/save path to persist version one; startup never writes.
    if settings_version == 0 and (root / "configs" / "onboarding.json").is_file():
        bundle, issues = migrate_legacy_settings(root)
        _validate_bundle(bundle)
        return bundle, issues
    base = _base_bundle(root, controls).model_copy(update={"settings_version": settings_version, "revision": ""})
    expected = _revision_for(base)
    supplied = str(raw.get("revision") or "")
    if supplied != expected:
        raise SettingsError("SETTINGS_SCHEMA_INVALID", "settings revision does not match companion configuration")
    bundle = base.model_copy(update={"revision": expected})
    _validate_bundle(bundle)
    return bundle, ()


def _validate_bundle(bundle: SettingsBundle) -> None:
    controls = bundle.controls
    if controls.output_currency not in OUTPUT_CURRENCIES:
        raise SettingsError("SETTINGS_CURRENCY_UNSUPPORTED", f"unsupported output currency: {controls.output_currency}")
    if not controls.asset_scopes or any(scope not in ASSET_SCOPES for scope in controls.asset_scopes):
        raise SettingsError("SETTINGS_SAFETY_BOUND_VIOLATION", "asset scopes must use the canonical long-only set")
    if len(controls.asset_scopes) != len(set(controls.asset_scopes)):
        raise SettingsError("SETTINGS_SCHEMA_INVALID", "asset scopes must be unique")
    if controls.risk_profile not in RISK_PROFILES:
        raise SettingsError("SETTINGS_SAFETY_BOUND_VIOLATION", f"unsupported risk profile: {controls.risk_profile}")
    if controls.horizon not in HORIZONS:
        raise SettingsError("SETTINGS_SCHEMA_INVALID", f"unsupported horizon: {controls.horizon}")
    if controls.analysis_depth not in ANALYSIS_DEPTHS:
        raise SettingsError("SETTINGS_SCHEMA_INVALID", f"unsupported analysis depth: {controls.analysis_depth}")
    if controls.macro_provider not in PROVIDER_IDS:
        raise SettingsError("SETTINGS_PROVIDER_UNSUPPORTED", f"unsupported macro provider: {controls.macro_provider}")
    try:
        PortfolioTargets.model_validate(bundle.targets)
        RiskLimits.model_validate(bundle.risks)
        CostConfig.model_validate(bundle.costs)
        ModelSettings.model_validate(bundle.models)
        SecretFreeProvidersConfig.model_validate(bundle.providers)
    except ValidationError as exc:
        raise SettingsError("SETTINGS_SAFETY_BOUND_VIOLATION", str(exc)) from exc
    for name, section in SecretFreeProvidersConfig.model_validate(bundle.providers).providers.items():
        if section.active_provider not in PROVIDER_IDS:
            raise SettingsError("SETTINGS_PROVIDER_UNSUPPORTED", f"unsupported provider for {name}: {section.active_provider}")
    if bundle.execution_allowed or controls.paper.execution_allowed:
        raise SettingsError("SETTINGS_SAFETY_BOUND_VIOLATION", "execution_allowed must remain false")


def _candidate_bundle(candidate: SettingsBundle | Mapping[str, object]) -> SettingsBundle:
    payload = candidate.model_dump(mode="json") if isinstance(candidate, SettingsBundle) else dict(candidate)
    payload["revision"] = ""
    return SettingsBundle.from_mapping(payload)


def _changed_fields(before: object, after: object, prefix: str = "") -> tuple[str, ...]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changed: list[str] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                changed.append(path)
            else:
                changed.extend(_changed_fields(before[key], after[key], path))
        return tuple(changed)
    if before != after:
        return (prefix,)
    return ()


def preview_settings(
    candidate: SettingsBundle | Mapping[str, object],
    *,
    expected_revision: str,
    root: Path,
) -> SettingsPreview:
    current = load_settings_bundle(root)
    if current.revision != expected_revision:
        raise SettingsError("SETTINGS_REVISION_CONFLICT", "settings changed since the editor was loaded")
    proposed = _candidate_bundle(candidate)
    _validate_bundle(proposed)
    changed = _changed_fields(_semantic_payload(current), _semantic_payload(proposed))
    persisted = current
    if changed:
        persisted = proposed.model_copy(update={"settings_version": current.settings_version + 1, "revision": ""})
        persisted = persisted.model_copy(update={"revision": _revision_for(persisted)})
    warnings = (
        "Currency selection is stored, but currency conversion remains unavailable until ISSUE-0173.",
        "Risk-profile effects remain unavailable until ISSUE-0174.",
        "Analysis-depth effects remain unavailable until ISSUE-0175.",
        "Credential CRUD is unavailable until ISSUE-0176.",
    )
    return SettingsPreview(
        valid=True,
        before_revision=current.revision,
        after_revision=persisted.revision,
        changed_fields=changed,
        creates_new_run=bool(changed),
        run_effects={
            "currency": "unavailable_issue_0173",
            "risk_profile": "unavailable_issue_0174",
            "analysis_depth": "unavailable_issue_0175",
            "credentials": "unavailable_issue_0176",
        },
        warnings=warnings,
    )


def _yaml_bytes(value: object) -> bytes:
    return yaml.safe_dump(value, sort_keys=True, allow_unicode=True).encode("utf-8")


def _validate_yaml(path: Path) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("settings YAML must contain an object")


def _validate_settings_yaml(path: Path) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("settings YAML must contain an object")
    if value.get("schema_version") != SETTINGS_SCHEMA_VERSION or value.get("semantic_version") != SETTINGS_SEMANTIC_VERSION:
        raise ValueError("settings YAML has an unsupported schema")
    SettingsControls.model_validate(value.get("controls", {}))
    if not isinstance(value.get("revision"), str) or len(value["revision"]) != 64:
        raise ValueError("settings YAML revision must be a SHA-256 digest")


def _validate_json(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("settings snapshot must contain an object")
    SettingsBundle.from_mapping(value)


def save_settings(
    candidate: SettingsBundle | Mapping[str, object],
    *,
    expected_revision: str,
    root: Path,
) -> SettingsSaveResult:
    root = Path(root).resolve()
    preview = preview_settings(candidate, expected_revision=expected_revision, root=root)
    current = load_settings_bundle(root)
    if not preview.creates_new_run:
        return SettingsSaveResult(saved=False, revision=current.revision, settings_version=current.settings_version, snapshot_path="", creates_new_run=False)
    proposed = _candidate_bundle(candidate).model_copy(update={"settings_version": current.settings_version + 1, "revision": ""})
    proposed = proposed.model_copy(update={"revision": _revision_for(proposed)})
    _validate_bundle(proposed)
    if proposed.revision != preview.after_revision:
        raise SettingsError("SETTINGS_PERSISTENCE_FAILED", "preview identity does not match the save candidate")

    config_dir = root / "configs"
    snapshot = root / "data" / "derived" / "settings_versions" / f"{proposed.settings_version}-{proposed.revision[:16]}.json"
    payload = proposed.model_dump(mode="json")
    settings_document = {
        "schema_version": proposed.schema_version,
        "semantic_version": proposed.semantic_version,
        "settings_version": proposed.settings_version,
        "revision": proposed.revision,
        "controls": proposed.controls.model_dump(mode="json"),
        "execution_allowed": False,
    }
    requests = (
        AtomicWriteRequest(config_dir / "settings.yaml", _yaml_bytes(settings_document), _validate_settings_yaml),
        AtomicWriteRequest(config_dir / "portfolio_targets.yaml", _yaml_bytes(proposed.targets), _validate_yaml),
        AtomicWriteRequest(config_dir / "risk_limits.yaml", _yaml_bytes(proposed.risks), _validate_yaml),
        AtomicWriteRequest(config_dir / "costs.yaml", _yaml_bytes(proposed.costs), _validate_yaml),
        AtomicWriteRequest(config_dir / "model_settings.yaml", _yaml_bytes(proposed.models), _validate_yaml),
        AtomicWriteRequest(config_dir / "data_providers.yaml", _yaml_bytes(proposed.providers), _validate_yaml),
        AtomicWriteRequest(snapshot, _canonical_bytes(payload), _validate_json),
    )

    def precondition() -> None:
        actual = load_settings_bundle(root)
        if actual.revision != expected_revision:
            raise SettingsError("SETTINGS_REVISION_CONFLICT", "settings changed before the atomic commit")
        if snapshot.exists():
            raise SettingsError("SETTINGS_PERSISTENCE_FAILED", f"immutable settings snapshot already exists: {snapshot}")

    try:
        atomic_write_group(requests, precondition=precondition)
    except SettingsError:
        raise
    except Exception as exc:
        raise SettingsError("SETTINGS_PERSISTENCE_FAILED", str(exc)) from exc
    reloaded = load_settings_bundle(root)
    if reloaded.revision != proposed.revision or reloaded.settings_version != proposed.settings_version:
        raise SettingsError("SETTINGS_PERSISTENCE_FAILED", "settings readback does not match the committed snapshot")
    return SettingsSaveResult(
        saved=True,
        revision=proposed.revision,
        settings_version=proposed.settings_version,
        snapshot_path=snapshot.relative_to(root).as_posix(),
        creates_new_run=True,
    )


def settings_run_identity(bundle: SettingsBundle) -> dict[str, object]:
    return {
        "settings_schema_version": bundle.schema_version,
        "settings_semantic_version": bundle.semantic_version,
        "settings_version": bundle.settings_version,
        "settings_revision": bundle.revision,
        "settings_snapshot_id": f"settings:{bundle.settings_version}:{bundle.revision}",
        "output_currency": bundle.controls.output_currency,
        "asset_scopes": list(bundle.controls.asset_scopes),
        "risk_profile": bundle.controls.risk_profile,
        "horizon": bundle.controls.horizon,
        "analysis_depth": bundle.controls.analysis_depth,
        "currency_effect_status": "unavailable_issue_0173",
        "risk_effect_status": "unavailable_issue_0174",
        "depth_effect_status": "unavailable_issue_0175",
        "execution_allowed": False,
    }


def settings_export(bundle: SettingsBundle) -> dict[str, object]:
    payload = _strip_secret_fields(bundle.model_dump(mode="json"))
    assert isinstance(payload, dict)
    payload["run_identity"] = settings_run_identity(bundle)
    payload["credential_management"] = {
        "status": "unavailable",
        "reason_code": "CREDENTIAL_CRUD_UNAVAILABLE_ISSUE_0176",
        "issue_id": "ISSUE-0176",
    }
    payload["execution_allowed"] = False
    return payload


__all__ = [
    "ANALYSIS_DEPTHS",
    "ASSET_SCOPES",
    "HORIZONS",
    "OUTPUT_CURRENCIES",
    "RISK_PROFILES",
    "SettingsBundle",
    "SettingsControls",
    "SettingsError",
    "SettingsMigrationIssue",
    "SettingsPreview",
    "SettingsSaveResult",
    "load_settings_bundle",
    "load_settings_bundle_with_issues",
    "migrate_legacy_settings",
    "preview_settings",
    "save_settings",
    "settings_export",
    "settings_run_identity",
]
