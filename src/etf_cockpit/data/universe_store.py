from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from etf_cockpit.core.atomic_io import atomic_write_json, backup_paths
from etf_cockpit.core.paths import ROOT


UNKNOWN_ISIN_VALUES = {"", "unknown", "needs_verification", "n/a", "na", "none"}
TICKER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,31}$")
CURRENT_INVESTABILITY_POLICY_VERSION = "investability-v1"
POLICY_AUTHORITIES = {"official", "user_reviewed", "manual_review"}
SPAREBANKEN_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Aurskog Sparebank", "AURG", "AURG.OL", "needs_verification"),
    ("Helgeland Sparebank", "HELG", "HELG.OL", "NO0010029804"),
    ("Høland og Setskog Sparebank", "HSPG", "HSPG.OL", "NO0010012636"),
    ("Sogn Sparebank", "SOGN", "SOGN.OL", "needs_verification"),
    ("Jæren Sparebank", "JAEREN", "JAEREN.OL", "NO0010359433"),
    ("Melhus Sparebank", "MELG", "MELG.OL", "needs_verification"),
    ("Sandnes Sparebank", "SADG", "SADG.OL", "needs_verification"),
    ("Skue Sparebank", "SKUE", "SKUE.OL", "needs_verification"),
    ("SpareBank 1 Nord-Norge", "NONG", "NONG.OL", "NO0006000801"),
    ("SpareBank 1 Ringerike Hadeland", "RING", "RING.OL", "NO0006390400"),
    ("SpareBank 1 SMN", "MING", "MING.OL", "NO0006390301"),
    ("SpareBank 1 Østfold Akershus", "SOAG", "SOAG.OL", "NO0010285562"),
    ("SpareBank 1 Østlandet", "SPOL", "SPOL.OL", "NO0010751910"),
    ("Sparebanken Møre", "MORG", "MORG.OL", "NO0006390004"),
    ("Sparebanken Øst", "SPOG", "SPOG.OL", "NO0006222009"),
)


@dataclass(frozen=True)
class UniverseRecord:
    instrument_id: str
    name: str
    isin: str = ""
    isin_status: str = "verified"
    ticker: str = ""
    asset_type: str = "stock"
    tier: str = "secondary"
    group: str = ""
    enabled: bool = True
    data_policy: str = "daily"
    currency: str = "EUR"
    region: str = ""
    sector: str = ""
    theme: str = ""
    notes: str = ""
    # Added in schema v2.  Missing legacy values are deliberately safe.
    leveraged: bool = False
    inverse: bool = False


@dataclass(frozen=True)
class InvestabilityPolicyProfile:
    instrument_id: str
    policy_id: str
    policy_version: str
    source_id: str
    as_of: str
    authority: str
    coverage: tuple[str, ...] = ()
    classification_confidence: float | None = None
    dependency_plan: tuple[str, ...] = ()
    checksum: str = ""
    execution_allowed: bool = False


@dataclass(frozen=True)
class PolicyEvidence:
    instrument_id: str
    state: str
    reason: str
    profile: InvestabilityPolicyProfile | None = None
    recompute_required: bool = True
    execution_allowed: bool = False


@dataclass(frozen=True)
class PolicyBackfillAction:
    instrument_id: str
    action: str
    from_policy_version: str | None
    to_policy_version: str
    reason: str
    expected_profile_checksum: str | None
    execution_allowed: bool = False


@dataclass(frozen=True)
class PolicyBackfillPlan:
    plan_id: str
    target_policy_version: str
    actions: tuple[PolicyBackfillAction, ...]
    mutates_store: bool = False
    execution_allowed: bool = False


@dataclass(frozen=True)
class UniverseValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    unknown_isin_ids: tuple[str, ...]


@dataclass(frozen=True)
class UniverseSaveResult:
    path: Path
    revision: str
    record_count: int
    backup_path: Path | None = None
    pending_refresh: bool = True


@dataclass(frozen=True)
class SupportDecision:
    supported: bool
    score_eligible: bool
    risk_state: str
    reason: str


@dataclass(frozen=True)
class UniverseStoreSnapshot:
    records: tuple[UniverseRecord, ...]
    revision: str
    path: Path
    allow_cross_tier_duplicates: bool = False
    policy_profiles: tuple[InvestabilityPolicyProfile, ...] = ()
    policy_evidence: tuple[PolicyEvidence, ...] = ()
    schema_version: int = 0
    integrity_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyImportResult:
    records: tuple[UniverseRecord, ...]
    warnings: tuple[str, ...] = ()
    source_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CompatibilityExport:
    yaml_path: Path
    csv_path: Path


class UniverseRevisionConflict(RuntimeError):
    pass


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _is_unknown_isin(value: str, status: str) -> bool:
    return status.strip().lower() in {"needs_verification", "unknown", "unresolved"} or value.strip().lower() in UNKNOWN_ISIN_VALUES


def _normalise_record(record: UniverseRecord) -> UniverseRecord:
    isin = _text(record.isin)
    status = _text(record.isin_status, "verified").lower()
    if _is_unknown_isin(isin, status):
        isin = "needs_verification"
        status = "needs_verification"
    return replace(
        record,
        instrument_id=_text(record.instrument_id),
        name=_text(record.name, _text(record.instrument_id)),
        isin=isin,
        isin_status=status,
        ticker=_text(record.ticker).upper(),
        asset_type=_text(record.asset_type, "stock").lower(),
        tier=_text(record.tier, "secondary").lower(),
        group=_text(record.group),
        data_policy=_text(record.data_policy, "daily").lower(),
        currency=_text(record.currency, "EUR").upper(),
        region=_text(record.region),
        sector=_text(record.sector),
        theme=_text(record.theme),
        notes=_text(record.notes),
        enabled=_as_bool(record.enabled),
        leveraged=_as_bool(record.leveraged),
        inverse=_as_bool(record.inverse),
    )


def validate_universe(
    records: Iterable[UniverseRecord],
    *,
    allow_cross_tier_duplicates: bool = False,
) -> UniverseValidationReport:
    items = tuple(_normalise_record(record) for record in records)
    errors: list[str] = []
    warnings: list[str] = []
    unknown: list[str] = []
    ids: dict[str, tuple[str, str]] = {}
    isins: dict[str, tuple[str, str]] = {}
    tickers: dict[str, tuple[str, str]] = {}
    for record in items:
        record_id = record.instrument_id.casefold()
        ticker = record.ticker.casefold()
        if not record.instrument_id:
            errors.append("instrument_id is required")
        elif record_id in ids:
            prior_id, prior_tier = ids[record_id]
            if not (allow_cross_tier_duplicates and prior_tier != record.tier):
                errors.append(f"duplicate instrument_id: {record.instrument_id}")
            else:
                warnings.append(f"cross-tier duplicate override: instrument_id {record.instrument_id}")
        ids[record_id] = (record.instrument_id, record.tier)
        if not record.ticker:
            errors.append(f"ticker is required: {record.instrument_id}")
        elif not TICKER_PATTERN.fullmatch(record.ticker):
            errors.append(f"malformed ticker: {record.ticker}")
        elif ticker in tickers:
            prior_ticker, prior_tier = tickers[ticker]
            if not (allow_cross_tier_duplicates and prior_tier != record.tier):
                errors.append(f"duplicate ticker: {record.ticker}")
            else:
                warnings.append(f"cross-tier duplicate override: ticker {record.ticker}")
        else:
            tickers[ticker] = (record.instrument_id, record.tier)
        if _is_unknown_isin(record.isin, record.isin_status):
            unknown.append(record.instrument_id)
        elif record.isin.casefold() in isins:
            prior_isin, prior_tier = isins[record.isin.casefold()]
            if not (allow_cross_tier_duplicates and prior_tier != record.tier):
                errors.append(f"duplicate isin: {record.isin}")
            else:
                warnings.append(f"cross-tier duplicate override: ISIN {record.isin}")
        else:
            isins[record.isin.casefold()] = (record.instrument_id, record.tier)
        if record.tier not in {"primary", "secondary", "sparebanken"}:
            errors.append(f"invalid tier: {record.tier}")
        decision = support_decision(record.asset_type, record.data_policy, record.leveraged, record.inverse)
        if decision.risk_state == "research_only":
            warnings.append(f"research_only: {record.instrument_id}")
        elif not decision.supported:
            errors.append(f"unsupported asset type/frequency: {record.asset_type}/{record.data_policy}")
        if not record.enabled:
            warnings.append(f"disabled: {record.instrument_id}")
        if _is_unknown_isin(record.isin, record.isin_status):
            warnings.append(f"needs_verification: {record.instrument_id}")
    return UniverseValidationReport(not errors, tuple(errors), tuple(warnings), tuple(sorted(set(unknown))))


def _store_path(root: Path) -> Path:
    return root / "configs" / "universe_store.json"


def _payload_revision(payload: Mapping[str, object]) -> str:
    canonical = dict(payload)
    canonical["revision"] = "pending"
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _policy_profile_payload(profile: InvestabilityPolicyProfile) -> dict[str, object]:
    return {
        "instrument_id": _text(profile.instrument_id),
        "policy_id": _text(profile.policy_id),
        "policy_version": _text(profile.policy_version),
        "source_id": _text(profile.source_id),
        "as_of": _text(profile.as_of),
        "authority": _text(profile.authority).lower(),
        "coverage": sorted({_text(item) for item in profile.coverage if _text(item)}),
        "classification_confidence": profile.classification_confidence,
        "dependency_plan": sorted({_text(item) for item in profile.dependency_plan if _text(item)}),
        "execution_allowed": False,
    }


def _policy_profile_checksum(profile: InvestabilityPolicyProfile) -> str:
    encoded = json.dumps(
        _policy_profile_payload(profile),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("policy profile as_of must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_policy_profile(
    profile: InvestabilityPolicyProfile,
    *,
    verify_checksum: bool = True,
) -> None:
    required = {
        "instrument_id": profile.instrument_id,
        "policy_id": profile.policy_id,
        "policy_version": profile.policy_version,
        "source_id": profile.source_id,
        "as_of": profile.as_of,
        "authority": profile.authority,
    }
    missing = sorted(name for name, value in required.items() if not _text(value))
    if missing:
        raise ValueError(f"policy profile missing required fields: {', '.join(missing)}")
    _parse_as_of(profile.as_of)
    if profile.authority not in POLICY_AUTHORITIES:
        raise ValueError(f"unsupported policy authority: {profile.authority}")
    if profile.execution_allowed:
        raise ValueError("policy profiles cannot grant execution authority")
    confidence = profile.classification_confidence
    if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("classification_confidence must be between 0 and 1")
    if verify_checksum and profile.checksum != _policy_profile_checksum(profile):
        raise ValueError("policy profile checksum mismatch")


def create_policy_profile(
    *,
    instrument_id: str,
    policy_id: str,
    policy_version: str,
    source_id: str,
    as_of: str,
    authority: str,
    coverage: Iterable[str] = (),
    classification_confidence: float | None = None,
    dependency_plan: Iterable[str] = (),
) -> InvestabilityPolicyProfile:
    profile = InvestabilityPolicyProfile(
        instrument_id=_text(instrument_id),
        policy_id=_text(policy_id),
        policy_version=_text(policy_version),
        source_id=_text(source_id),
        as_of=_text(as_of),
        authority=_text(authority).lower(),
        coverage=tuple(sorted({_text(item) for item in coverage if _text(item)})),
        classification_confidence=classification_confidence,
        dependency_plan=tuple(sorted({_text(item) for item in dependency_plan if _text(item)})),
    )
    _validate_policy_profile(profile, verify_checksum=False)
    return replace(profile, checksum=_policy_profile_checksum(profile))


def _policy_profile_from_mapping(raw: Mapping[str, object]) -> InvestabilityPolicyProfile:
    coverage = raw.get("coverage", ())
    dependencies = raw.get("dependency_plan", ())
    if not isinstance(coverage, (list, tuple)) or any(
        not isinstance(item, str) for item in coverage
    ):
        raise ValueError("coverage must be a list of strings")
    if not isinstance(dependencies, (list, tuple)) or any(
        not isinstance(item, str) for item in dependencies
    ):
        raise ValueError("dependency_plan must be a list of strings")
    profile = InvestabilityPolicyProfile(
        instrument_id=_text(raw.get("instrument_id")),
        policy_id=_text(raw.get("policy_id")),
        policy_version=_text(raw.get("policy_version")),
        source_id=_text(raw.get("source_id")),
        as_of=_text(raw.get("as_of")),
        authority=_text(raw.get("authority")).lower(),
        coverage=tuple(sorted(_text(item) for item in coverage if _text(item))),
        classification_confidence=(
            float(raw["classification_confidence"])
            if raw.get("classification_confidence") is not None
            else None
        ),
        dependency_plan=tuple(
            sorted(_text(item) for item in dependencies if _text(item))
        ),
        checksum=_text(raw.get("checksum")),
        execution_allowed=_as_bool(raw.get("execution_allowed", False)),
    )
    _validate_policy_profile(profile)
    return profile


def _policy_evidence(
    records: tuple[UniverseRecord, ...],
    profiles: tuple[InvestabilityPolicyProfile, ...],
    *,
    schema_version: int,
    invalid_profiles: Mapping[str, str] | None = None,
    current_policy_version: str = CURRENT_INVESTABILITY_POLICY_VERSION,
    store_integrity_errors: Iterable[str] = (),
) -> tuple[PolicyEvidence, ...]:
    by_id = {profile.instrument_id: profile for profile in profiles}
    invalid_profiles = invalid_profiles or {}
    integrity_errors = tuple(store_integrity_errors)
    evidence: list[PolicyEvidence] = []
    for record in records:
        if integrity_errors:
            evidence.append(
                PolicyEvidence(
                    record.instrument_id,
                    "manual_review",
                    "universe store integrity failed: " + "; ".join(integrity_errors),
                )
            )
            continue
        if record.instrument_id in invalid_profiles:
            evidence.append(
                PolicyEvidence(record.instrument_id, "manual_review", invalid_profiles[record.instrument_id])
            )
            continue
        profile = by_id.get(record.instrument_id)
        if profile is None:
            state = "legacy_unmigrated" if schema_version < 3 else "unavailable"
            reason = (
                "legacy store has no versioned policy profile; inspect a backfill plan"
                if state == "legacy_unmigrated"
                else "no versioned policy profile is available"
            )
            evidence.append(PolicyEvidence(record.instrument_id, state, reason))
        elif profile.policy_version != current_policy_version:
            evidence.append(
                PolicyEvidence(
                    record.instrument_id,
                    "stale",
                    f"policy {profile.policy_version} differs from current {current_policy_version}",
                    profile,
                )
            )
        elif profile.authority == "manual_review":
            evidence.append(
                PolicyEvidence(
                    record.instrument_id,
                    "manual_review",
                    "policy evidence requires reviewed manual confirmation",
                    profile,
                )
            )
        else:
            evidence.append(
                PolicyEvidence(
                    record.instrument_id,
                    "current",
                    "policy profile checksum, authority and version are current",
                    profile,
                    recompute_required=False,
                )
            )
    return tuple(evidence)


def _decode_v3_store(
    payload: Mapping[str, object],
) -> tuple[
    tuple[UniverseRecord, ...],
    tuple[InvestabilityPolicyProfile, ...],
    tuple[str, ...],
]:
    errors: list[str] = []
    if payload.get("schema_version") != 3:
        errors.append(f"unsupported universe store schema: {payload.get('schema_version')}")
    persisted_revision = _text(payload.get("revision"))
    if not persisted_revision or persisted_revision != _payload_revision(payload):
        errors.append("store revision checksum mismatch")

    raw_records = payload.get("records")
    records: list[UniverseRecord] = []
    record_ids: set[str] = set()
    if not isinstance(raw_records, list):
        errors.append("records must be a list")
        raw_records = []
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, Mapping):
            errors.append(f"record {index} must be an object")
            continue
        try:
            record = _normalise_record(UniverseRecord(**raw))
        except (TypeError, ValueError) as exc:
            errors.append(f"record {index} is malformed: {exc}")
            continue
        if record.instrument_id in record_ids:
            errors.append(f"duplicate universe record: {record.instrument_id}")
            continue
        record_ids.add(record.instrument_id)
        records.append(record)
    allow_duplicates = payload.get("allow_cross_tier_duplicates", False)
    if not isinstance(allow_duplicates, bool):
        errors.append("allow_cross_tier_duplicates must be a boolean")
    else:
        report = validate_universe(
            records,
            allow_cross_tier_duplicates=allow_duplicates,
        )
        errors.extend(f"invalid universe record: {error}" for error in report.errors)

    raw_profiles = payload.get("policy_profiles")
    profiles: list[InvestabilityPolicyProfile] = []
    profile_ids: set[str] = set()
    if not isinstance(raw_profiles, list):
        errors.append("policy_profiles must be a list")
        raw_profiles = []
    for index, raw in enumerate(raw_profiles):
        if not isinstance(raw, Mapping):
            errors.append(f"policy profile {index} must be an object")
            continue
        instrument_id = _text(raw.get("instrument_id"))
        if instrument_id in profile_ids:
            errors.append(f"duplicate policy profile: {instrument_id or '<missing>'}")
            continue
        profile_ids.add(instrument_id)
        try:
            profile = _policy_profile_from_mapping(raw)
        except (TypeError, ValueError) as exc:
            errors.append(f"policy profile {index} is malformed: {exc}")
            continue
        if profile.instrument_id not in record_ids:
            errors.append(
                f"policy profile references unknown instrument_id: {profile.instrument_id}"
            )
            continue
        profiles.append(profile)
    if errors:
        profiles = []
    return tuple(records), tuple(profiles), tuple(errors)


def _schema_version(payload: Mapping[str, object]) -> int:
    if "schema_version" not in payload:
        return 0
    value = payload["schema_version"]
    if type(value) is not int or value < 0:
        raise ValueError("schema_version must be a non-negative integer")
    return value


def build_policy_backfill_plan(
    snapshot: UniverseStoreSnapshot,
    *,
    target_policy_version: str = CURRENT_INVESTABILITY_POLICY_VERSION,
) -> PolicyBackfillPlan:
    target = _text(target_policy_version)
    if not target:
        raise ValueError("target_policy_version is required")
    actions = tuple(
        PolicyBackfillAction(
            instrument_id=item.instrument_id,
            action=(
                "review_legacy"
                if item.state == "legacy_unmigrated"
                else "recompute"
                if item.state == "stale"
                else "manual_review"
            ),
            from_policy_version=item.profile.policy_version if item.profile else None,
            to_policy_version=target,
            reason=item.reason,
            expected_profile_checksum=item.profile.checksum if item.profile else None,
        )
        for item in snapshot.policy_evidence
        if item.state != "current"
    )
    canonical = {
        "target_policy_version": target,
        "actions": [asdict(item) for item in actions],
        "mutates_store": False,
        "execution_allowed": False,
    }
    plan_id = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return PolicyBackfillPlan(plan_id, target, actions)


def save_universe(
    records: Iterable[UniverseRecord],
    expected_revision: str,
    *,
    root: Path | None = None,
    allow_cross_tier_duplicates: bool = False,
    policy_profiles: Iterable[InvestabilityPolicyProfile] | None = None,
) -> UniverseSaveResult:
    root = (root or ROOT).resolve()
    items = tuple(_normalise_record(record) for record in records)
    report = validate_universe(items, allow_cross_tier_duplicates=allow_cross_tier_duplicates)
    if not report.valid:
        raise ValueError("Universe validation failed: " + "; ".join(report.errors))
    path = _store_path(root)
    current_revision = ""
    current_schema_version = 0
    retained_profiles: tuple[InvestabilityPolicyProfile, ...] = ()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise ValueError("universe store root must be an object")
            current_revision = str(raw.get("revision") or "")
            current_schema_version = _schema_version(raw)
            if current_schema_version >= 3:
                _, decoded_profiles, integrity_errors = _decode_v3_store(raw)
                if integrity_errors:
                    raise ValueError(
                        "Universe store integrity failed: "
                        + "; ".join(integrity_errors)
                    )
                if policy_profiles is None:
                    retained_profiles = decoded_profiles
            elif policy_profiles is None:
                retained_profiles = tuple(
                    _policy_profile_from_mapping(item)
                    for item in raw.get("policy_profiles", ())
                    if isinstance(item, Mapping)
                )
        except OSError:
            raise
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Universe store is corrupt: {exc}") from exc
    if current_revision != expected_revision:
        raise UniverseRevisionConflict(f"Expected revision {expected_revision or '<empty>'}, found {current_revision or '<empty>'}")
    backup_path: Path | None = None
    if path.is_file():
        backup = backup_paths((path,), root / "backups" / "universe")
        backup_path = backup.manifest_path
    selected_profiles = (
        tuple(policy_profiles) if policy_profiles is not None else retained_profiles
    )
    record_ids = {item.instrument_id for item in items}
    profile_ids: set[str] = set()
    for profile in selected_profiles:
        _validate_policy_profile(profile)
        if profile.instrument_id not in record_ids:
            raise ValueError(
                f"policy profile references unknown instrument_id: {profile.instrument_id}"
            )
        if profile.instrument_id in profile_ids:
            raise ValueError(f"duplicate policy profile: {profile.instrument_id}")
        profile_ids.add(profile.instrument_id)
    write_schema_version = (
        3
        if not path.exists() or policy_profiles is not None or selected_profiles
        else current_schema_version
    )
    payload: dict[str, object] = {
        "schema_version": write_schema_version,
        "revision": "pending",
        "allow_cross_tier_duplicates": bool(allow_cross_tier_duplicates),
        "records": [asdict(item) for item in items],
    }
    if write_schema_version >= 3:
        payload["policy_profiles"] = [
            {**_policy_profile_payload(item), "checksum": item.checksum}
            for item in sorted(selected_profiles, key=lambda profile: profile.instrument_id)
        ]
    revision = _payload_revision(payload)
    payload["revision"] = revision
    atomic_write_json(path, payload)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    if persisted.get("revision") != revision:
        raise IOError("Universe revision verification failed after atomic write")
    return UniverseSaveResult(path, revision, len(items), backup_path)


def load_universe(root: Path | None = None) -> UniverseStoreSnapshot:
    root = (root or ROOT).resolve()
    path = _store_path(root)
    if not path.exists():
        return UniverseStoreSnapshot((), "", path, False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("universe store root must be an object")
    try:
        schema_version = _schema_version(payload)
    except ValueError as exc:
        records, policy_profiles, decoded_errors = _decode_v3_store(payload)
        integrity_errors = (str(exc),) + tuple(
            error
            for error in decoded_errors
            if not error.startswith("unsupported universe store schema:")
        )
        return UniverseStoreSnapshot(
            records,
            _text(payload.get("revision")),
            path,
            _as_bool(payload.get("allow_cross_tier_duplicates", False)),
            policy_profiles,
            _policy_evidence(
                records,
                policy_profiles,
                schema_version=0,
                store_integrity_errors=integrity_errors,
            ),
            0,
            integrity_errors,
        )
    if schema_version >= 3:
        records, policy_profiles, integrity_errors = _decode_v3_store(payload)
        return UniverseStoreSnapshot(
            records,
            _text(payload.get("revision")),
            path,
            _as_bool(payload.get("allow_cross_tier_duplicates", False)),
            policy_profiles,
            _policy_evidence(
                records,
                policy_profiles,
                schema_version=schema_version,
                store_integrity_errors=integrity_errors,
            ),
            schema_version,
            integrity_errors,
        )

    records = tuple(
        _normalise_record(UniverseRecord(**raw))
        for raw in payload.get("records", ())
    )
    profiles: list[InvestabilityPolicyProfile] = []
    invalid_profiles: dict[str, str] = {}
    for index, raw in enumerate(payload.get("policy_profiles", ())):
        if not isinstance(raw, Mapping):
            invalid_profiles[f"<profile-{index}>"] = "policy profile is not an object"
            continue
        instrument_id = _text(raw.get("instrument_id"), f"<profile-{index}>")
        try:
            profiles.append(_policy_profile_from_mapping(raw))
        except (TypeError, ValueError) as exc:
            invalid_profiles[instrument_id] = str(exc)
    policy_profiles = tuple(profiles)
    return UniverseStoreSnapshot(
        records,
        _text(payload.get("revision")),
        path,
        _as_bool(payload.get("allow_cross_tier_duplicates", False)),
        policy_profiles,
        _policy_evidence(
            records,
            policy_profiles,
            schema_version=schema_version,
            invalid_profiles=invalid_profiles,
        ),
        schema_version,
        (),
    )


def add_record(
    records: Iterable[UniverseRecord],
    record: UniverseRecord,
    *,
    allow_cross_tier_duplicates: bool = False,
) -> tuple[UniverseRecord, ...]:
    items = tuple(records) + (_normalise_record(record),)
    report = validate_universe(items, allow_cross_tier_duplicates=allow_cross_tier_duplicates)
    if not report.valid:
        raise ValueError("Universe validation failed: " + "; ".join(report.errors))
    return items


def edit_record(
    records: Iterable[UniverseRecord],
    instrument_id: str,
    *,
    allow_cross_tier_duplicates: bool = False,
    **changes: object,
) -> tuple[UniverseRecord, ...]:
    items = tuple(records)
    for index, record in enumerate(items):
        if record.instrument_id == instrument_id:
            allowed = set(asdict(record))
            unknown = sorted(set(changes) - allowed)
            if unknown:
                raise ValueError(f"Unknown universe fields: {', '.join(unknown)}")
            updated = _normalise_record(replace(record, **changes))
            candidate = items[:index] + (updated,) + items[index + 1 :]
            report = validate_universe(candidate, allow_cross_tier_duplicates=allow_cross_tier_duplicates)
            if not report.valid:
                raise ValueError("Universe validation failed: " + "; ".join(report.errors))
            return candidate
    raise KeyError(f"Unknown instrument_id: {instrument_id}")


def disable_record(
    records: Iterable[UniverseRecord],
    instrument_id: str,
    *,
    allow_cross_tier_duplicates: bool = False,
) -> tuple[UniverseRecord, ...]:
    return edit_record(
        records,
        instrument_id,
        enabled=False,
        allow_cross_tier_duplicates=allow_cross_tier_duplicates,
    )


def remove_record(records: Iterable[UniverseRecord], instrument_id: str) -> tuple[UniverseRecord, ...]:
    items = tuple(records)
    if not any(record.instrument_id == instrument_id for record in items):
        raise KeyError(f"Unknown instrument_id: {instrument_id}")
    return tuple(record for record in items if record.instrument_id != instrument_id)


def support_decision(asset_type: str, frequency: str, leveraged: bool, inverse: bool) -> SupportDecision:
    normalized = _text(asset_type).lower()
    cadence = _text(frequency).lower()
    if normalized in {"futures", "future", "options", "option", "derivative"}:
        return SupportDecision(False, False, "research_only", f"{asset_type} is research-only and is not scored by the daily pipeline.")
    if normalized in {"crypto", "cryptocurrency"}:
        return SupportDecision(False, False, "unsupported", "Crypto is unsupported unless a separately configured proxy is approved; no silent scoring.")
    if normalized not in {"etf", "stock", "equity", "equity_certificate", "certificate"}:
        return SupportDecision(False, False, "unsupported", f"{asset_type} is unsupported and cannot be scored.")
    # ``yfinance_only`` is the historical provider-policy marker, not an
    # intraday cadence.  Keep it compatible with the daily pipeline.
    if cadence not in {"daily", "daily_close", "yfinance_now_multi_provider_later", "yfinance_only"}:
        return SupportDecision(False, False, "unsupported_frequency", "Intraday and non-daily frequencies are unsupported for current scoring.")
    if leveraged or inverse:
        return SupportDecision(True, False, "high_risk_manual_review", "Leveraged or inverse instruments require manual review and are not score eligible by default.")
    return SupportDecision(True, True, "normal", "Daily ETF/stock/equity-certificate scoring is supported.")


def _field(row: Mapping[str, object], *names: str) -> str:
    lower = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = lower.get(name.lower())
        if value not in (None, ""):
            return _text(value)
    return ""


def _record_from_mapping(raw: Mapping[str, object], *, default_tier: str) -> UniverseRecord:
    ticker = _field(raw, "ticker", "yahoo_symbol", "yahoo_ticker", "provider_symbol", "symbol")
    isin = _field(raw, "isin", "ISIN") or "needs_verification"
    status = _field(raw, "isin_status", "isin_state") or ("needs_verification" if _is_unknown_isin(isin, "") else "verified")
    tier = (_field(raw, "tier", "analysis_tier") or default_tier).lower()
    group = _field(raw, "group", "source_group") or ("Sparebanken" if tier == "sparebanken" else "")
    instrument_id = _field(raw, "instrument_id", "id", "symbol", "ticker") or ticker
    asset_type = _field(raw, "asset_type", "instrument_type", "type") or ("equity_certificate" if tier == "sparebanken" else "stock")
    leveraged = _field(raw, "leveraged", "is_leveraged").lower() in {"true", "1", "yes", "on"}
    inverse = _field(raw, "inverse", "is_inverse").lower() in {"true", "1", "yes", "on"}
    return _normalise_record(
        UniverseRecord(
            instrument_id=instrument_id,
            name=_field(raw, "name", "security_name", "company") or instrument_id,
            isin=isin,
            isin_status=status,
            ticker=ticker,
            asset_type=asset_type,
            tier=tier,
            group=group,
            enabled=_field(raw, "enabled").lower() not in {"false", "0", "no", "disabled"},
            data_policy=_field(raw, "data_policy", "frequency", "price_frequency") or "daily",
            currency=_field(raw, "currency") or "NOK" if tier == "sparebanken" else _field(raw, "currency") or "EUR",
            region=_field(raw, "region") or ("Norway" if tier == "sparebanken" else ""),
            sector=_field(raw, "sector") or ("Banks" if tier == "sparebanken" else ""),
            theme=_field(raw, "theme"),
            notes=_field(raw, "notes", "comment"),
            leveraged=leveraged,
            inverse=inverse,
        )
    )


def _sparebanken_fallback() -> tuple[UniverseRecord, ...]:
    return tuple(
        _record_from_mapping(
            {"name": name, "symbol": symbol, "yahoo_symbol": ticker, "isin": isin, "analysis_tier": "sparebanken"},
            default_tier="sparebanken",
        )
        for name, symbol, ticker, isin in SPAREBANKEN_ROWS
    )


def import_legacy_universe(primary_yaml: Path, candidate_csv: Path | None = None) -> LegacyImportResult:
    primary_yaml = Path(primary_yaml)
    payload = yaml.safe_load(primary_yaml.read_text(encoding="utf-8")) if primary_yaml.exists() else {}
    primary_rows = (payload.get("etfs", ()) or ()) if isinstance(payload, dict) else ()
    records: list[UniverseRecord] = [_record_from_mapping(raw, default_tier="primary") for raw in primary_rows if isinstance(raw, Mapping)]
    warnings: list[str] = []
    candidate_path = Path(candidate_csv) if candidate_csv else None
    candidate_rows: list[Mapping[str, object]] = []
    if candidate_path and candidate_path.exists():
        with candidate_path.open(newline="", encoding="utf-8-sig") as handle:
            candidate_rows = list(csv.DictReader(handle))
    fallback = _sparebanken_fallback()
    fallback_by_id = {record.instrument_id.casefold(): record for record in fallback}
    fallback_by_ticker = {record.ticker.casefold(): record for record in fallback}
    if candidate_rows:
        for raw in candidate_rows:
            records.append(_record_from_mapping(raw, default_tier="secondary"))
    else:
        warnings.append("candidate CSV unavailable; retained built-in Sparebanken identity rows")
    # Both primary YAML and candidate feeds historically mixed Sparebanken
    # rows into other tiers. Canonical fallback identity always wins.
    canonical_ids = set(fallback_by_id)
    canonical_tickers = set(fallback_by_ticker)
    records = [
        record
        for record in records
        if record.instrument_id.casefold() not in canonical_ids
        and record.ticker.casefold() not in canonical_tickers
    ]
    records.extend(fallback)
    # Preserve one authoritative row per canonical ID even if an unusual
    # legacy source repeats a row under a case variant.
    seen: set[str] = set()
    deduped: list[UniverseRecord] = []
    for record in records:
        key = record.instrument_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return LegacyImportResult(tuple(deduped), tuple(warnings), tuple(path for path in (primary_yaml, candidate_path) if path is not None and path.exists()))


def migrate_legacy_universe(
    root: Path | None = None,
    *,
    primary_yaml: Path | None = None,
    candidate_csv: Path | None = None,
    expected_revision: str | None = None,
) -> tuple[LegacyImportResult, UniverseSaveResult]:
    """Import legacy YAML/CSV inputs and publish one revisioned local store."""

    root = (root or ROOT).resolve()
    primary = primary_yaml or (root / "configs" / "universe.yaml")
    candidates = candidate_csv
    if candidates is None:
        candidate_dir = root / "data" / "raw" / "trade_candidates"
        found = sorted(candidate_dir.glob("yahoo_trade_candidates_*.csv")) if candidate_dir.exists() else []
        candidates = found[-1] if found else None
    imported = import_legacy_universe(primary, candidates)
    current = load_universe(root)
    revision = current.revision if expected_revision is None else expected_revision
    saved = save_universe(imported.records, expected_revision=revision, root=root)
    return imported, saved


def export_compatibility(records: Iterable[UniverseRecord], export_root: Path) -> CompatibilityExport:
    export_root = Path(export_root)
    export_root.mkdir(parents=True, exist_ok=True)
    items = tuple(_normalise_record(record) for record in records)
    yaml_path = export_root / "universe.yaml"
    yaml_payload = {"etfs": [{"id": row.instrument_id, "name": row.name, "isin": row.isin, "ticker": row.ticker, "provider_symbol": row.ticker, "instrument_type": row.asset_type, "analysis_tier": row.tier, "data_policy": row.data_policy, "currency": row.currency, "region": row.region, "sector": row.sector, "theme": row.theme, "enabled": row.enabled, "leveraged": row.leveraged, "inverse": row.inverse, "role": "core" if row.tier == "primary" else "watchlist", "notes": row.notes} for row in items if row.tier == "primary"]}
    yaml_path.write_text(yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    csv_path = export_root / "yahoo_trade_candidates.csv"
    fieldnames = ["instrument_id", "name", "isin", "isin_status", "ticker", "asset_type", "analysis_tier", "group", "enabled", "data_policy", "currency", "region", "sector", "theme", "notes", "leveraged", "inverse"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in items:
            if row.tier != "primary":
                writer.writerow({"instrument_id": row.instrument_id, "name": row.name, "isin": row.isin, "isin_status": row.isin_status, "ticker": row.ticker, "asset_type": row.asset_type, "analysis_tier": row.tier, "group": row.group, "enabled": row.enabled, "data_policy": row.data_policy, "currency": row.currency, "region": row.region, "sector": row.sector, "theme": row.theme, "notes": row.notes, "leveraged": row.leveraged, "inverse": row.inverse})
    return CompatibilityExport(yaml_path, csv_path)
