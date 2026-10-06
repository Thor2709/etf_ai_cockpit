"""Versioned local anomaly rules and append-only review evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Literal, Mapping

from etf_cockpit.data.bitemporal import BitemporalError, BitemporalStore
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.source_conflicts import ConflictResolution


AnomalyState = Literal["pass", "warn", "quarantine", "block"]
ExecutionDenied = Literal[False]
_STATES: tuple[AnomalyState, ...] = ("pass", "warn", "quarantine", "block")


class AnomalyLedgerError(ValueError):
    """Raised when anomaly evidence is ambiguous or unsafe."""


@dataclass(frozen=True)
class QualityRule:
    rule_id: str
    version: int
    family: str
    asset_scope: tuple[str, ...]
    data_scope: tuple[str, ...]
    expected_units: tuple[str, ...]
    severity: AnomalyState
    methodology: str
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    liquidity_scope: tuple[str, ...] = ("all",)
    execution_allowed: ExecutionDenied = False

    @property
    def versioned_id(self) -> str:
        return f"{self.rule_id}:v{self.version}"

    @property
    def sha256(self) -> str:
        return _hash(asdict(self))


@dataclass(frozen=True)
class AnomalyFinding:
    finding_id: str
    rule_id: str
    rule_version: int
    entity_id: str
    state: AnomalyState
    message: str
    observed: object
    expected_units: tuple[str, ...]
    available_at: str
    source_id: str
    source_checksum: str
    revision: int = 1
    canonical_eligible: bool = False
    execution_allowed: ExecutionDenied = False


@dataclass(frozen=True)
class CorrectionEvent:
    finding_id: str
    action: Literal["reviewed", "corrected", "rejected"]
    reviewer: str
    reason: str
    available_at: str
    source_checksum: str
    revision: int = 1
    execution_allowed: ExecutionDenied = False


@dataclass(frozen=True)
class AnomalyEvaluation:
    findings: tuple[AnomalyFinding, ...]
    counts: Mapping[str, int]
    canonical_eligible: bool
    invalidation_token: str
    execution_allowed: ExecutionDenied = False


def default_quality_rules() -> tuple[QualityRule, ...]:
    """Canonical bounded rule registry; values are declared, never inferred."""

    return (
        QualityRule("schema.required", 1, "required", ("all",), ("all",), ("declared",), "block", "Required fields must be present."),
        QualityRule("numeric.finite", 1, "finite", ("all",), ("numeric",), ("declared",), "block", "Numeric values must be finite."),
        QualityRule("date.continuity", 1, "date_continuity", ("all",), ("time_series",), ("ISO-8601",), "warn", "Dates must be unique and strictly increasing."),
        QualityRule("market.ohlc", 1, "ohlc", ("equity", "etf"), ("price",), ("currency_per_share",), "quarantine", "Low <= open/close <= high.", absolute_tolerance=1e-12, liquidity_scope=("liquid", "illiquid")),
        QualityRule("quantity.nonnegative", 1, "nonnegative", ("all",), ("volume", "quantity"), ("shares", "contracts"), "block", "Quantities and volumes cannot be negative."),
        QualityRule("context.unit_currency", 1, "unit_currency", ("all",), ("all",), ("declared",), "block", "Unit and currency context must be explicit."),
        QualityRule("identity.duplicates_actions", 1, "duplicates", ("all",), ("identity", "corporate_action"), ("identity",), "quarantine", "Duplicate identities/actions require review."),
        QualityRule("fixed_income.price_invariant", 1, "fixed_income", ("bond",), ("valuation_inputs",), ("percent_of_par", "currency", "decimal"), "quarantine", "Dirty price must reconcile to clean price plus accrued.", absolute_tolerance=0.02, liquidity_scope=("liquid", "illiquid")),
        QualityRule("fixed_income.schedule", 1, "schedule", ("bond",), ("cashflow_schedule",), ("ISO-8601",), "block", "Coupon schedule and day-count must be possible."),
        QualityRule("freshness.asset_liquidity", 1, "freshness", ("all",), ("market_data",), ("days",), "quarantine", "Freshness tolerance is asset/liquidity specific.", absolute_tolerance=1.0, liquidity_scope=("liquid", "illiquid")),
        QualityRule("holding.balance", 1, "balance", ("portfolio",), ("holding",), ("currency",), "block", "Holding components must reconcile to declared total.", absolute_tolerance=0.01),
    )


def validate_rules(rules: Iterable[QualityRule]) -> tuple[QualityRule, ...]:
    items = tuple(sorted(rules, key=lambda item: (item.rule_id, item.version)))
    identities: set[str] = set()
    for rule in items:
        if (
            not rule.rule_id
            or rule.version < 1
            or rule.severity not in _STATES
            or rule.severity == "pass"
            or not rule.expected_units
            or not rule.methodology
            or rule.execution_allowed
            or rule.absolute_tolerance < 0
            or rule.relative_tolerance < 0
        ):
            raise AnomalyLedgerError(f"invalid quality rule: {rule.rule_id or '<missing>'}")
        if rule.versioned_id in identities:
            raise AnomalyLedgerError(f"duplicate quality rule: {rule.versioned_id}")
        identities.add(rule.versioned_id)
    return items


def evaluate_record(
    entity_id: str,
    record: Mapping[str, object],
    *,
    rules: Iterable[QualityRule] | None = None,
    available_at: str,
    source_id: str,
    source_checksum: str,
) -> AnomalyEvaluation:
    active = validate_rules(rules or default_quality_rules())
    if (
        not entity_id
        or not record
        or not source_id
        or not _checksum(source_checksum)
    ):
        raise AnomalyLedgerError(
            "entity, non-empty record, source identity and SHA-256 source evidence are required"
        )
    timestamp = _timestamp(available_at)
    findings = tuple(
        _finding(rule, entity_id, record, timestamp, source_id, source_checksum)
        for rule in active
        if _applicable(rule, record)
    )
    counts = {state: sum(item.state == state for item in findings) for state in _STATES}
    eligible = not any(item.state in {"quarantine", "block"} for item in findings)
    token = _hash(
        {
            "rules": [item.sha256 for item in active],
            "findings": [item.finding_id for item in findings],
            "canonical_eligible": eligible,
        }
    )
    return AnomalyEvaluation(findings, counts, eligible, token)


def project_conflicts(
    resolution: ConflictResolution,
    *,
    available_at: str,
    source_checksum: str,
) -> AnomalyEvaluation:
    """Adapt canonical conflict decisions without selecting sources again."""

    if not _checksum(source_checksum):
        raise AnomalyLedgerError("conflict projection requires a SHA-256 checksum")
    timestamp = _timestamp(available_at)
    findings = tuple(
        _make_finding(
            QualityRule(
                "source.material_conflict",
                1,
                "source_conflict",
                ("all",),
                ("canonical_candidate",),
                (item.unit,),
                item.state if item.state in _STATES else "block",
                "Projection of resolve_conflicts evidence; candidates and decision IDs are retained.",
            ),
            item.instrument_id,
            item.reason,
            {
                "conflict_id": item.conflict_id,
                "decision_id": item.decision_id,
                "source_ids": item.source_ids,
                "values": item.values,
            },
            timestamp,
            "source_conflicts",
            source_checksum,
        )
        for item in resolution.conflicts
    )
    counts = {state: sum(item.state == state for item in findings) for state in _STATES}
    eligible = resolution.state not in {"quarantine", "block"} and not any(
        item.state in {"quarantine", "block"} for item in findings
    )
    return AnomalyEvaluation(
        findings,
        counts,
        eligible,
        _hash(
            {
                "source_invalidation_token": resolution.invalidation_token,
                "findings": [item.finding_id for item in findings],
            }
        ),
    )


class AnomalyLedger:
    FINDINGS_DATASET = "data-anomaly-findings.v1"
    CORRECTIONS_DATASET = "data-anomaly-corrections.v1"

    def append_findings(self, evaluation: AnomalyEvaluation, *, root: Path) -> None:
        try:
            with BitemporalStore(root) as store:
                for finding in evaluation.findings:
                    store.record_observation(
                        dataset_id=self.FINDINGS_DATASET,
                        entity_id=finding.entity_id,
                        stable_id=finding.finding_id,
                        value=asdict(finding),
                        source_id=finding.source_id,
                        source_checksum=finding.source_checksum,
                        revision=finding.revision,
                        valid_from=finding.available_at,
                        available_at=finding.available_at,
                        observed_at=finding.available_at,
                        published_at=finding.available_at,
                        ingested_at=finding.available_at,
                        run_id=f"anomaly-{evaluation.invalidation_token[:24]}",
                    )
        except BitemporalError as exc:
            raise AnomalyLedgerError(str(exc)) from exc

    def append_correction(self, event: CorrectionEvent, *, root: Path) -> None:
        if (
            not event.finding_id
            or not event.reviewer
            or not event.reason
            or event.execution_allowed
            or not _checksum(event.source_checksum)
        ):
            raise AnomalyLedgerError("correction evidence is incomplete")
        timestamp = _timestamp(event.available_at)
        try:
            with BitemporalStore(root) as store:
                store.record_observation(
                    dataset_id=self.CORRECTIONS_DATASET,
                    entity_id=event.finding_id,
                    stable_id=event.finding_id,
                    value=asdict(event),
                    source_id=f"reviewer:{event.reviewer}",
                    source_checksum=event.source_checksum,
                    revision=event.revision,
                    valid_from=timestamp,
                    available_at=timestamp,
                    observed_at=timestamp,
                    published_at=timestamp,
                    ingested_at=timestamp,
                    run_id=f"correction-{event.finding_id[:16]}-{event.revision}",
                    require_revision_advance=True,
                )
        except BitemporalError as exc:
            raise AnomalyLedgerError(str(exc)) from exc

    def summary(self, *, root: Path, decision_time: str) -> dict[str, object]:
        if not storage_layout(root).transactional_path.exists():
            return {
                "status": "unavailable",
                "reason": "anomaly ledger has not been created",
                "canonical_eligible": False,
                "execution_allowed": False,
            }
        try:
            with BitemporalStore(root) as store:
                findings_frame = store.as_of(self.FINDINGS_DATASET, decision_time)
                corrections_frame = store.as_of(self.CORRECTIONS_DATASET, decision_time)
        except (BitemporalError, OSError) as exc:
            return {
                "status": "unavailable",
                "reason": f"{type(exc).__name__}: anomaly ledger requires manual review",
                "execution_allowed": False,
            }
        findings = [
            AnomalyFinding(**dict(value))
            for value in findings_frame.get("value", [])
            if isinstance(value, Mapping)
        ]
        corrections = {
            str(value.get("finding_id")): CorrectionEvent(**dict(value))
            for value in corrections_frame.get("value", [])
            if isinstance(value, Mapping)
        }
        resolved_finding_ids = {
            finding_id
            for finding_id, event in corrections.items()
            if event.action == "corrected"
        }
        unresolved = [
            item for item in findings if item.finding_id not in resolved_finding_ids
        ]
        counts = {
            state: sum(item.state == state for item in unresolved) for state in _STATES
        }
        rule_versions = sorted(
            {f"{item.rule_id}:v{item.rule_version}" for item in findings}
        )
        token = _hash(
            {
                "findings": [item.finding_id for item in findings],
                "corrections": [
                    asdict(corrections[key]) for key in sorted(corrections)
                ],
                "rules": rule_versions,
            }
        )
        return {
            "status": "available" if findings else "unavailable",
            "rule_versions": rule_versions,
            "rule_count": len(rule_versions),
            "finding_count": len(findings),
            "counts": counts,
            "unresolved_count": len(unresolved),
            "blocked_downstream_count": sum(
                item.state in {"quarantine", "block"} for item in unresolved
            ),
            "correction_count": len(corrections),
            "review_states": sorted({item.action for item in corrections.values()}),
            "canonical_eligible": bool(findings)
            and not any(item.state in {"quarantine", "block"} for item in unresolved),
            "invalidation_token": token,
            "decision_time": _timestamp(decision_time),
            "execution_allowed": False,
        }


def _finding(
    rule: QualityRule,
    entity_id: str,
    record: Mapping[str, object],
    available_at: str,
    source_id: str,
    source_checksum: str,
) -> AnomalyFinding:
    try:
        passed, message, observed = _evaluate(rule, record)
    except (ArithmeticError, TypeError, ValueError, OverflowError) as exc:
        passed = False
        message = f"malformed input: {type(exc).__name__}"
        observed = {
            key: repr(record[key])
            for key in sorted(record)
            if key not in {"raw_payload", "credentials"}
        }
    state: AnomalyState = "pass" if passed else rule.severity
    return _make_finding(
        rule, entity_id, message, observed, available_at, source_id, source_checksum, state
    )


def _make_finding(
    rule: QualityRule,
    entity_id: str,
    message: str,
    observed: object,
    available_at: str,
    source_id: str,
    source_checksum: str,
    state: AnomalyState | None = None,
) -> AnomalyFinding:
    resolved_state = state or rule.severity
    identity = {
        "rule": rule.versioned_id,
        "entity_id": entity_id,
        "state": resolved_state,
        "message": message,
        "observed": observed,
        "available_at": available_at,
        "source_id": source_id,
        "source_checksum": source_checksum.lower(),
    }
    return AnomalyFinding(
        _hash(identity),
        rule.rule_id,
        rule.version,
        entity_id,
        resolved_state,
        message,
        observed,
        rule.expected_units,
        available_at,
        source_id,
        source_checksum.lower(),
        canonical_eligible=resolved_state in {"pass", "warn"},
    )


def _evaluate(
    rule: QualityRule, record: Mapping[str, object]
) -> tuple[bool, str, object]:
    family = rule.family
    if family == "required":
        required = tuple(
            dict.fromkeys(("asset_type", *tuple(record.get("required_fields", ()))))
        )
        missing = sorted(field for field in required if record.get(str(field)) is None)
        return not missing, "required fields present" if not missing else f"missing: {', '.join(missing)}", missing
    if family == "finite":
        invalid = sorted(
            key
            for key, value in record.items()
            if isinstance(value, (int, float)) and not math.isfinite(float(value))
        )
        return not invalid, "numeric values are finite" if not invalid else "non-finite values", invalid
    if family == "date_continuity":
        dates = tuple(str(item) for item in record.get("dates", ()))
        parsed_dates = tuple(datetime.fromisoformat(item.replace("Z", "+00:00")) for item in dates)
        valid = bool(parsed_dates) and parsed_dates == tuple(sorted(set(parsed_dates)))
        return valid, "dates are continuous" if valid else "dates are duplicate or unordered", dates
    if family == "ohlc":
        values = tuple(record.get(key) for key in ("open", "high", "low", "close"))
        if any(value is None for value in values):
            return False, "OHLC context is ambiguous", values
        opening, high, low, close = (float(value) for value in values)
        valid = all(math.isfinite(value) for value in (opening, high, low, close))
        valid = (
            valid
            and low - rule.absolute_tolerance <= opening <= high + rule.absolute_tolerance
            and low - rule.absolute_tolerance <= close <= high + rule.absolute_tolerance
        )
        return valid, "OHLC invariant holds" if valid else "OHLC invariant failed", values
    if family == "nonnegative":
        values = {key: record[key] for key in ("volume", "quantity") if key in record}
        if not values:
            return False, "volume/quantity is unavailable", values
        valid = all(float(value) >= 0 for value in values.values())
        return valid, "quantities are nonnegative" if valid else "negative quantity", values
    if family == "unit_currency":
        valid = bool(record.get("unit")) and bool(record.get("currency"))
        return valid, "unit/currency declared" if valid else "unit or currency unavailable", {"unit": record.get("unit"), "currency": record.get("currency")}
    if family == "duplicates":
        duplicates = tuple(record.get("duplicate_ids", ())) + tuple(record.get("duplicate_actions", ()))
        return not duplicates, "no duplicate identities/actions" if not duplicates else "duplicate identities/actions", duplicates
    if family == "fixed_income":
        required = ("clean_price", "dirty_price", "accrued", "par", "coupon", "notional", "yield", "day_count")
        if any(record.get(field) is None for field in required):
            return False, "fixed-income invariant context is ambiguous", {field: record.get(field) for field in required}
        clean, dirty, accrued, par, coupon, notional, yield_value = (
            float(record[field]) for field in required[:-1]
        )
        difference = abs(dirty - (clean + accrued))
        valid = (
            all(
                math.isfinite(value)
                for value in (
                    clean,
                    dirty,
                    accrued,
                    par,
                    coupon,
                    notional,
                    yield_value,
                )
            )
            and clean > 0
            and dirty > 0
            and par > 0
            and notional > 0
            and difference <= rule.absolute_tolerance
        )
        return valid, "fixed-income supplied values reconcile" if valid else "fixed-income supplied values do not reconcile", difference
    if family == "schedule":
        dates = tuple(str(item) for item in record.get("schedule_dates", ()))
        parsed_dates = tuple(
            datetime.fromisoformat(item.replace("Z", "+00:00")) for item in dates
        )
        valid = (
            bool(parsed_dates)
            and parsed_dates == tuple(sorted(set(parsed_dates)))
            and bool(record.get("day_count"))
        )
        return valid, "schedule is possible" if valid else "schedule is impossible or unavailable", dates
    if family == "freshness":
        age = record.get("age_days")
        liquidity = str(record.get("liquidity", "ambiguous")).strip().lower()
        limit = {"liquid": 1.0, "illiquid": 5.0}.get(liquidity)
        age_value = float(age) if age is not None else math.nan
        valid = (
            limit is not None
            and math.isfinite(age_value)
            and 0 <= age_value <= limit
        )
        return valid, "freshness is within declared tolerance" if valid else "stale or ambiguous liquidity", {"age_days": age, "liquidity": liquidity, "limit": limit}
    if family == "balance":
        total = record.get("holding_total")
        components = record.get("holding_components")
        if total is None or not isinstance(components, (list, tuple)):
            return False, "holding balance is ambiguous", {"total": total, "components": components}
        difference = abs(float(total) - sum(float(item) for item in components))
        return difference <= rule.absolute_tolerance, "holding balances" if difference <= rule.absolute_tolerance else "holding is unbalanced", difference
    return False, f"unsupported rule family: {family}", None


def _applicable(rule: QualityRule, record: Mapping[str, object]) -> bool:
    asset_type = str(record.get("asset_type", "")).strip().lower()
    if "all" not in rule.asset_scope and asset_type not in rule.asset_scope:
        return False
    if "all" not in rule.asset_scope:
        return True
    if "all" in rule.data_scope:
        return True
    family_fields = {
        "finite": tuple(
            key
            for key, value in record.items()
            if isinstance(value, (int, float))
        ),
        "date_continuity": ("dates",),
        "ohlc": ("open", "high", "low", "close"),
        "nonnegative": ("volume", "quantity"),
        "duplicates": ("duplicate_ids", "duplicate_actions"),
        "fixed_income": ("clean_price", "dirty_price", "accrued"),
        "schedule": ("schedule_dates",),
        "freshness": ("age_days", "liquidity"),
        "balance": ("holding_total", "holding_components"),
    }
    required = family_fields.get(rule.family, ())
    trigger_present = bool(required) and any(field in record for field in required)
    raw_declared = record.get("data_scopes", ())
    declared = (
        {str(item).strip().lower() for item in raw_declared}
        if isinstance(raw_declared, (list, tuple, set, frozenset))
        else set()
    )
    return trigger_present or bool(declared & set(rule.data_scope))


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _checksum(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value)


def _timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnomalyLedgerError("available_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise AnomalyLedgerError("available_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


__all__ = [
    "AnomalyEvaluation",
    "AnomalyFinding",
    "AnomalyLedger",
    "AnomalyLedgerError",
    "CorrectionEvent",
    "QualityRule",
    "default_quality_rules",
    "evaluate_record",
    "project_conflicts",
    "validate_rules",
]
