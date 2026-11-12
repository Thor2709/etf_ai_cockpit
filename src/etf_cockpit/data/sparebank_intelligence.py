"""Frozen ``sparebank-intelligence-result.v1`` envelope: strict parse + validation.

The envelope is an analytical intelligence record produced by an independent
specialist engine.  This module only validates and projects it; it never
reinterprets the science and never grants execution authority.  Any problem
yields stable machine-readable issue codes and *no* projection (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any, Mapping

SCHEMA_NAME = "sparebank-intelligence-result"
SCHEMA_ID = "sparebank-intelligence-result.v1"
SUPPORTED_MAJOR = 1
SUPPORTED_MINOR = 0

MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 12
MAX_ITEMS = 20000
MAX_STRING = 4096
CLOCK_SKEW = timedelta(minutes=5)
PROBABILITY_SUM_TOLERANCE = 1e-6

STATUSES = frozenset({"VALID", "DEGRADED", "INVALID"})
EPISTEMIC_CLASSES = frozenset(
    {"OBSERVED", "CALCULATED", "NORMALISED", "MODEL_ESTIMATE", "ASSUMPTION", "MANAGEMENT_TARGET", "THESIS", "SPECULATION"}
)
CONFIDENCE_CLASSES = frozenset({"OBSERVED", "HIGH", "MEDIUM", "LOW"})
MISSINGNESS = frozenset({"PRESENT", "PARTIAL", "MISSING"})
EVENT_TYPES = frozenset({"CONVERSION", "FOUNDATION_PLACEMENT", "LISTING_MIGRATION", "MERGER", "ISSUE", "OTHER"})
SYNERGY_STATES = frozenset({"ANNOUNCED", "TARGET", "IMPLEMENTED", "FINANCIALLY_VISIBLE", "SEASONED"})
ADVISORY_STATES = frozenset({"WATCH", "REJECT", "INVESTABLE_CANDIDATE"})
FOUR_RATIOS = ("bank_value_split", "target_ec_conversion_ratio", "post_merger_ec_class_split", "post_merger_eierbrok")
_UNIT_INTERVAL_RATIOS = frozenset({"bank_value_split", "post_merger_ec_class_split", "post_merger_eierbrok"})
# Keys that would turn an analytical envelope into an instruction.
FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {"order", "orders", "target_weight", "target_weights", "weights", "quantity", "broker_instruction", "execute", "trade", "trades"}
)
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_TOP = frozenset(
    {
        "schema", "schema_version", "producer", "model_version", "science_version", "code_revision", "run_id",
        "as_of", "known_at_cutoff", "generated_at", "status", "critical_missing", "coverage", "content_hash",
        "attachments", "execution_allowed", "metrics", "owner_claims", "bank_state", "valuations",
        "structural_events", "distributions", "monitoring", "advisory",
    }
)


@dataclass(frozen=True)
class IntelligenceIssue:
    code: str
    path: str = "$"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path}


@dataclass(frozen=True)
class IntelligenceParseResult:
    ok: bool
    issues: tuple[IntelligenceIssue, ...]
    projection: dict[str, Any] | None
    content_hash: str | None
    raw_sha256: str
    run_id: str | None = None

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(sorted({issue.code for issue in self.issues}))


class _Reject(Exception):
    def __init__(self, code: str, path: str = "$") -> None:
        super().__init__(code)
        self.issue = IntelligenceIssue(code, path)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def compute_content_hash(envelope: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the envelope without its ``content_hash`` field."""

    body = {key: value for key, value in envelope.items() if key != "content_hash"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def seal_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Producer-side helper (tests/fixtures): return a copy with a correct ``content_hash``."""

    sealed = dict(envelope)
    sealed["content_hash"] = compute_content_hash(sealed)
    return sealed


# ----------------------------------------------------------------------------- parsing


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Reject("duplicate_key", key)
        result[key] = value
    return result


def _bad_constant(name: str) -> Any:
    raise _Reject("non_finite_number", name)


def _check_bounds(value: Any, path: str = "$", depth: int = 1, counter: list[int] | None = None) -> None:
    counter = counter if counter is not None else [0]
    if depth > MAX_DEPTH:
        raise _Reject("depth_exceeded", path)
    counter[0] += 1
    if counter[0] > MAX_ITEMS:
        raise _Reject("item_count_exceeded", path)
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_AUTHORITY_KEYS:
                raise _Reject("execution_authority_field", f"{path}.{key}")
            if key == "execution_allowed" and item is not False:
                raise _Reject("execution_authority_field", f"{path}.{key}")
            _check_bounds(item, f"{path}.{key}", depth + 1, counter)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_bounds(item, f"{path}[{index}]", depth + 1, counter)
    elif isinstance(value, str):
        if len(value) > MAX_STRING:
            raise _Reject("string_too_long", path)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise _Reject("non_finite_number", path)


def parse_envelope_bytes(raw: bytes, *, now: datetime | None = None) -> IntelligenceParseResult:
    """Validate raw envelope bytes; return a projection only when every check passes."""

    raw_sha = hashlib.sha256(raw).hexdigest()
    run_id: str | None = None
    try:
        if len(raw) > MAX_BYTES:
            raise _Reject("size_exceeded")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise _Reject("invalid_utf8") from None
        if text.startswith("﻿"):
            raise _Reject("invalid_utf8", "byte_order_mark")
        try:
            data = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_bad_constant)
        except (json.JSONDecodeError, RecursionError):
            raise _Reject("malformed_json") from None
        if not isinstance(data, dict):
            raise _Reject("wrong_type", "$")
        _check_bounds(data)
        if isinstance(data.get("run_id"), str):
            run_id = data["run_id"]
        projection = _validate(data, now or datetime.now(timezone.utc))
        return IntelligenceParseResult(True, (), projection, projection["content_hash"], raw_sha, run_id)
    except _Reject as exc:
        return IntelligenceParseResult(False, (exc.issue,), None, None, raw_sha, run_id)


# --------------------------------------------------------------------------- validation


def _req(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping or mapping[key] is None:
        raise _Reject("missing_required_field", f"{path}.{key}")
    return mapping[key]


def _dict(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _Reject("wrong_type", path)
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _Reject("wrong_type", path)
    return value


def _str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Reject("wrong_type", path)
    return value


def _num(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Reject("wrong_type", path)
    if not math.isfinite(value):
        raise _Reject("non_finite_number", path)
    return float(value)


def _prob(value: Any, path: str) -> float:
    number = _num(value, path)
    if not 0.0 <= number <= 1.0:
        raise _Reject("probability_out_of_range", path)
    return number


def _enum(value: Any, allowed: frozenset[str], path: str, code: str = "invalid_enum") -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _Reject(code, path)
    return value


def _ts(value: Any, path: str) -> datetime:
    """Timezone-aware ISO-8601 instant (date-only values are read as 00:00 UTC)."""

    text = _str(value, path)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _Reject("invalid_timestamp", path) from None
    if parsed.tzinfo is None:
        raise _Reject("timestamp_missing_timezone", path)
    return parsed.astimezone(timezone.utc)


def _validate(data: dict[str, Any], now: datetime) -> dict[str, Any]:
    if data.get("schema") != SCHEMA_NAME:
        raise _Reject("unknown_schema", "$.schema")
    version = _str(_req(data, "schema_version", "$"), "$.schema_version")
    match = re.fullmatch(r"(\d+)\.(\d+)", version)
    if not match:
        raise _Reject("unknown_schema_version", "$.schema_version")
    major, minor = int(match.group(1)), int(match.group(2))
    if major != SUPPORTED_MAJOR:
        raise _Reject("unsupported_schema_major", "$.schema_version")
    producer = _dict(_req(data, "producer", "$"), "$.producer")
    _str(_req(producer, "id", "$.producer"), "$.producer.id")
    _str(_req(producer, "engine_capability_profile", "$.producer"), "$.producer.engine_capability_profile")
    for key in ("model_version", "science_version", "code_revision"):
        _str(_req(data, key, "$"), f"$.{key}")
    run_id = _str(_req(data, "run_id", "$"), "$.run_id")
    if not _RUN_ID.fullmatch(run_id):
        raise _Reject("invalid_run_id", "$.run_id")
    if data.get("execution_allowed") is not False:
        raise _Reject("execution_authority_field", "$.execution_allowed")

    as_of = _ts(_req(data, "as_of", "$"), "$.as_of")
    cutoff = _ts(_req(data, "known_at_cutoff", "$"), "$.known_at_cutoff")
    generated = _ts(_req(data, "generated_at", "$"), "$.generated_at")
    if as_of > cutoff:
        raise _Reject("as_of_after_known_at_cutoff", "$.as_of")
    if cutoff > generated:
        raise _Reject("known_at_cutoff_after_generation", "$.known_at_cutoff")
    if generated > now + CLOCK_SKEW:
        raise _Reject("future_timestamp", "$.generated_at")

    status = _enum(_req(data, "status", "$"), STATUSES, "$.status", "invalid_status")
    missing = [_str(item, f"$.critical_missing[{i}]") for i, item in enumerate(_list(_req(data, "critical_missing", "$"), "$.critical_missing"))]
    coverage = _dict(_req(data, "coverage", "$"), "$.coverage")
    for key, flag in coverage.items():
        if not isinstance(flag, bool):
            raise _Reject("wrong_type", f"$.coverage.{key}")
    incomplete = any(flag is False for flag in coverage.values())
    if status == "INVALID":
        raise _Reject("producer_status_invalid", "$.status")
    if status == "VALID" and (missing or incomplete):
        raise _Reject("status_missingness_inconsistent", "$.status")
    if status == "DEGRADED" and not (missing or incomplete):
        raise _Reject("status_missingness_inconsistent", "$.status")

    attachments = _validate_attachments(_list(_req(data, "attachments", "$"), "$.attachments"))
    declared = _req(data, "content_hash", "$")
    if not isinstance(declared, str) or not _SHA256.fullmatch(declared):
        raise _Reject("invalid_content_hash", "$.content_hash")
    if declared != compute_content_hash(data):
        raise _Reject("content_hash_mismatch", "$.content_hash")

    metrics = _validate_metrics(data.get("metrics", []), cutoff)
    claims = _validate_claims(data.get("owner_claims", []), cutoff)
    claim_ids = {claim["instrument_id"] for claim in claims}
    valuations = _validate_valuations(data.get("valuations", []), claim_ids)
    events = _validate_events(data.get("structural_events", []))
    distributions = _validate_distributions(data.get("distributions", []))
    monitoring = _validate_monitoring(data.get("monitoring", {}))
    advisory = _validate_advisory(data.get("advisory", []))
    bank_state = _validate_bank_state(data.get("bank_state", []), cutoff)

    projection: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "schema_major": major,
        "schema_minor": minor,
        "run_id": run_id,
        "producer": dict(producer),
        "model_version": data["model_version"],
        "science_version": data["science_version"],
        "code_revision": data["code_revision"],
        "as_of": data["as_of"],
        "known_at_cutoff": data["known_at_cutoff"],
        "generated_at": data["generated_at"],
        "status": status,
        "critical_missing": missing,
        "coverage": dict(coverage),
        "content_hash": declared,
        "attachments": attachments,
        "metrics": metrics,
        "owner_claims": claims,
        "bank_state": bank_state,
        "valuations": valuations,
        "structural_events": events,
        "distributions": distributions,
        "monitoring": monitoring,
        "advisory": advisory,
        "execution_allowed": False,
        # Unknown optional fields from a newer minor are preserved verbatim, never interpreted.
        "preserved_unknown": {key: data[key] for key in sorted(data) if key not in _KNOWN_TOP},
        "unknown_minor": minor > SUPPORTED_MINOR,
    }
    if projection["preserved_unknown"] and minor <= SUPPORTED_MINOR:
        raise _Reject("unknown_field_in_supported_minor", "$")
    return projection


def _validate_attachments(items: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for index, item in enumerate(items):
        path = f"$.attachments[{index}]"
        row = _dict(item, path)
        attachment_id = _str(_req(row, "attachment_id", path), f"{path}.attachment_id")
        digest = _req(row, "sha256", path)
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise _Reject("invalid_attachment_hash", f"{path}.sha256")
        size = _req(row, "size_bytes", path)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise _Reject("wrong_type", f"{path}.size_bytes")
        required = row.get("required", True)
        if not isinstance(required, bool):
            raise _Reject("wrong_type", f"{path}.required")
        if attachment_id in seen:
            raise _Reject("duplicate_identifier", path)
        seen.add(attachment_id)
        result.append({"attachment_id": attachment_id, "sha256": digest, "size_bytes": size, "required": required,
                       "media_type": _str(_req(row, "media_type", path), f"{path}.media_type")})
    return result


def validate_attachment_bytes(projection: Mapping[str, Any], available: Mapping[str, bytes]) -> tuple[IntelligenceIssue, ...]:
    """Check manifest attachments against supplied bytes; required ones must match."""

    issues: list[IntelligenceIssue] = []
    for index, row in enumerate(projection.get("attachments", [])):
        path = f"$.attachments[{index}]"
        blob = available.get(row["attachment_id"])
        if blob is None:
            if row["required"]:
                issues.append(IntelligenceIssue("attachment_missing", path))
            continue
        if len(blob) != row["size_bytes"] or hashlib.sha256(blob).hexdigest() != row["sha256"]:
            issues.append(IntelligenceIssue("attachment_hash_mismatch", path))
    return tuple(issues)


def _validate_value(row: Mapping[str, Any], path: str) -> None:
    """Value or value_range, never both; finite and ordered."""

    has_value, has_range = "value" in row, "value_range" in row
    if has_value and has_range:
        raise _Reject("value_and_range", path)
    if has_value:
        _num(row["value"], f"{path}.value")
    elif has_range:
        rng = _dict(row["value_range"], f"{path}.value_range")
        low, high = _num(_req(rng, "low", f"{path}.value_range"), f"{path}.value_range.low"), _num(_req(rng, "high", f"{path}.value_range"), f"{path}.value_range.high")
        if low > high:
            raise _Reject("range_inverted", f"{path}.value_range")


def _validate_evidence(row: Mapping[str, Any], path: str, cutoff: datetime) -> dict[str, Any]:
    """Profile B: unit, period, known_at, provenance, definition, epistemic class, missingness."""

    missingness = _enum(_req(row, "missingness", path), MISSINGNESS, f"{path}.missingness", "invalid_missingness")
    has_value = "value" in row or "value_range" in row
    if missingness == "MISSING" and has_value:
        raise _Reject("missing_with_value", path)
    if missingness != "MISSING" and not has_value:
        raise _Reject("value_absent_without_missing_flag", path)
    _validate_value(row, path)
    _str(_req(row, "unit", path), f"{path}.unit")
    _str(_req(row, "period", path), f"{path}.period")
    known_at = _ts(_req(row, "known_at", path), f"{path}.known_at")
    if known_at > cutoff:
        raise _Reject("known_after_cutoff", f"{path}.known_at")
    _str(_req(row, "source_ref", path), f"{path}.source_ref")
    if "source_hash" in row and (not isinstance(row["source_hash"], str) or not _SHA256.fullmatch(row["source_hash"])):
        raise _Reject("invalid_source_hash", f"{path}.source_hash")
    _str(_req(row, "definition_id", path), f"{path}.definition_id")
    _enum(_req(row, "epistemic_class", path), EPISTEMIC_CLASSES, f"{path}.epistemic_class", "invalid_epistemic_class")
    if "confidence_class" in row:
        _enum(row["confidence_class"], CONFIDENCE_CLASSES, f"{path}.confidence_class", "invalid_confidence_class")
    return dict(row)


def _validate_metrics(items: Any, cutoff: datetime) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for index, item in enumerate(_list(items, "$.metrics")):
        path = f"$.metrics[{index}]"
        row = _dict(item, path)
        metric_id = _str(_req(row, "metric_id", path), f"{path}.metric_id")
        if metric_id in seen:
            raise _Reject("duplicate_identifier", path)
        seen.add(metric_id)
        result.append(_validate_evidence(row, path, cutoff))
    return result


def _validate_bank_state(items: Any, cutoff: datetime) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_list(items, "$.bank_state")):
        path = f"$.bank_state[{index}]"
        row = _dict(item, path)
        _str(_req(row, "driver_id", path), f"{path}.driver_id")
        _str(_req(row, "layer", path), f"{path}.layer")
        result.append(_validate_evidence(row, path, cutoff))
        # Normalisation must keep reported -> adjustment -> mechanism -> evidence -> persistence.
        if row["epistemic_class"] == "NORMALISED":
            for key in ("reported_value", "adjustment", "mechanism", "evidence_ref", "persistence_assumption"):
                _req(row, key, path)
    return result


def _validate_claims(items: Any, cutoff: datetime) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for index, item in enumerate(_list(items, "$.owner_claims")):
        path = f"$.owner_claims[{index}]"
        row = _dict(item, path)
        instrument = _str(_req(row, "instrument_id", path), f"{path}.instrument_id")
        if instrument in seen:
            raise _Reject("duplicate_identifier", path)
        seen.add(instrument)
        _str(_req(row, "bank_legal_entity", path), f"{path}.bank_legal_entity")
        _str(_req(row, "share_class", path), f"{path}.share_class")
        for key in ("eierandelskapital", "grunnfondskapital"):
            capital = _dict(_req(row, key, path), f"{path}.{key}")
            _num(_req(capital, "value", f"{path}.{key}"), f"{path}.{key}.value")
            _str(_req(capital, "definition", f"{path}.{key}"), f"{path}.{key}.definition")
        eierbrok = _dict(_req(row, "eierbrok", path), f"{path}.eierbrok")
        _prob(_req(eierbrok, "value", f"{path}.eierbrok"), f"{path}.eierbrok.value")
        _ts(_req(eierbrok, "effective_at", f"{path}.eierbrok"), f"{path}.eierbrok.effective_at")
        known = _ts(_req(eierbrok, "known_at", f"{path}.eierbrok"), f"{path}.eierbrok.known_at")
        if known > cutoff:
            raise _Reject("known_after_cutoff", f"{path}.eierbrok.known_at")
        current, diluted = _count(row, "ec_count_current", path), _count(row, "ec_count_fully_diluted", path)
        treasury = _count(row, "treasury_ec_count", path)
        if diluted < current:
            raise _Reject("claim_invariant_violated", f"{path}.ec_count_fully_diluted")
        if treasury > current:
            raise _Reject("claim_invariant_violated", f"{path}.treasury_ec_count")
        holdings = _dict(_req(row, "holdings", path), f"{path}.holdings")
        foundation = _prob(_req(holdings, "foundation_share", f"{path}.holdings"), f"{path}.holdings.foundation_share")
        strategic = _prob(_req(holdings, "strategic_share", f"{path}.holdings"), f"{path}.holdings.strategic_share")
        free_float = _prob(_req(holdings, "effective_free_float", f"{path}.holdings"), f"{path}.holdings.effective_free_float")
        if foundation + strategic + free_float > 1.0 + PROBABILITY_SUM_TOLERANCE:
            raise _Reject("claim_invariant_violated", f"{path}.holdings")
        status = _enum(_req(row, "claimant_allocation_status", path), frozenset({"RESOLVED", "UNRESOLVED"}), f"{path}.claimant_allocation_status")
        if "owner_valuation" in row:
            valuation = _dict(row["owner_valuation"], f"{path}.owner_valuation")
            if status != "RESOLVED":
                raise _Reject("owner_valuation_unresolved_claimant", f"{path}.owner_valuation")
            if valuation.get("denominator_basis") != "OWNER_ATTRIBUTABLE_EC":
                raise _Reject("owner_valuation_denominator_mismatch", f"{path}.owner_valuation.denominator_basis")
            _num(_req(valuation, "owner_attributable_book", f"{path}.owner_valuation"), f"{path}.owner_valuation.owner_attributable_book")
            _num(_req(valuation, "owner_attributable_earnings", f"{path}.owner_valuation"), f"{path}.owner_valuation.owner_attributable_earnings")
        if "event_id" in row:
            _str(row["event_id"], f"{path}.event_id")
            for key in ("pre_event_state", "post_event_state"):
                _dict(_req(row, key, path), f"{path}.{key}")
        if "voting_share" in row:
            _prob(row["voting_share"], f"{path}.voting_share")  # governance only, separate from economics
        result.append(dict(row))
    return result


def _count(row: Mapping[str, Any], key: str, path: str) -> int:
    value = _req(row, key, path)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _Reject("wrong_type", f"{path}.{key}")
    return value


def _validate_valuations(items: Any, claim_ids: set[str]) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_list(items, "$.valuations")):
        path = f"$.valuations[{index}]"
        row = _dict(item, path)
        instrument = _str(_req(row, "instrument_id", path), f"{path}.instrument_id")
        if instrument not in claim_ids:
            raise _Reject("valuation_without_owner_claim", f"{path}.instrument_id")
        _str(_req(row, "model_id", path), f"{path}.model_id")
        scenarios = _list(_req(row, "scenarios", path), f"{path}.scenarios")
        if len(scenarios) < 2:
            raise _Reject("valuation_single_point_only", f"{path}.scenarios")
        total = 0.0
        for s_index, scenario in enumerate(scenarios):
            s_path = f"{path}.scenarios[{s_index}]"
            s_row = _dict(scenario, s_path)
            _str(_req(s_row, "name", s_path), f"{s_path}.name")
            _num(_req(s_row, "value", s_path), f"{s_path}.value")
            total += _prob(_req(s_row, "probability", s_path), f"{s_path}.probability")
            # Probability and evidence confidence are separate fields and both are mandatory.
            _enum(_req(s_row, "probability_confidence", s_path), CONFIDENCE_CLASSES, f"{s_path}.probability_confidence", "invalid_confidence_class")
        if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
            raise _Reject("probabilities_do_not_sum_to_one", f"{path}.scenarios")
        result.append(dict(row))
    return result


def _validate_events(items: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for index, item in enumerate(_list(items, "$.structural_events")):
        path = f"$.structural_events[{index}]"
        row = _dict(item, path)
        event_id = _str(_req(row, "event_id", path), f"{path}.event_id")
        if event_id in seen:
            raise _Reject("duplicate_identifier", path)
        seen.add(event_id)
        event_type = _enum(_req(row, "event_type", path), EVENT_TYPES, f"{path}.event_type", "invalid_event_type")
        _dict(_req(row, "pre_state", path), f"{path}.pre_state")
        _dict(_req(row, "post_state", path), f"{path}.post_state")
        _str(_req(row, "milestone", path), f"{path}.milestone")
        previous: datetime | None = None
        for h_index, entry in enumerate(_list(_req(row, "history", path), f"{path}.history")):
            h_path = f"{path}.history[{h_index}]"
            at = _ts(_req(_dict(entry, h_path), "at", h_path), f"{h_path}.at")
            _str(_req(entry, "milestone", h_path), f"{h_path}.milestone")
            if previous is not None and at < previous:
                raise _Reject("event_history_out_of_order", h_path)
            previous = at
        if event_type == "MERGER":
            _validate_merger(row, path)
        result.append(dict(row))
    return result


def _validate_merger(row: Mapping[str, Any], path: str) -> None:
    ratios = _dict(_req(row, "four_ratios", path), f"{path}.four_ratios")
    for name in FOUR_RATIOS:
        value = _num(_req(ratios, name, f"{path}.four_ratios"), f"{path}.four_ratios.{name}")
        if value <= 0 or (name in _UNIT_INTERVAL_RATIOS and value > 1):
            raise _Reject("ratio_out_of_range", f"{path}.four_ratios.{name}")
    ledgers = _dict(_req(row, "ledger_refs", path), f"{path}.ledger_refs")
    for name in ("legal", "valuation", "capital_class", "security", "accounting"):
        _str(_req(ledgers, name, f"{path}.ledger_refs"), f"{path}.ledger_refs.{name}")
    for s_index, synergy in enumerate(_list(row.get("synergies", []), f"{path}.synergies")):
        s_path = f"{path}.synergies[{s_index}]"
        s_row = _dict(synergy, s_path)
        _enum(_req(s_row, "component", s_path), frozenset({"COST", "FUNDING", "CAPITAL", "REVENUE", "INTEGRATION_COST"}), f"{s_path}.component")
        _enum(_req(s_row, "state", s_path), SYNERGY_STATES, f"{s_path}.state", "invalid_synergy_state")
        _num(_req(s_row, "value", s_path), f"{s_path}.value")
    _str(_req(row, "integration_state", path), f"{path}.integration_state")
    _req(row, "owner_value_per_legacy_ec", path)
    _num(row["owner_value_per_legacy_ec"], f"{path}.owner_value_per_legacy_ec")


def _validate_distributions(items: Any) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_list(items, "$.distributions")):
        path = f"$.distributions[{index}]"
        row = _dict(item, path)
        _str(_req(row, "instrument_id", path), f"{path}.instrument_id")
        _str(_req(row, "horizon", path), f"{path}.horizon")
        _str(_req(row, "simulation_id", path), f"{path}.simulation_id")
        quantiles = _dict(_req(row, "quantiles", path), f"{path}.quantiles")
        points = []
        for key, value in quantiles.items():
            if not re.fullmatch(r"p\d{1,2}(\.\d+)?", key):
                raise _Reject("invalid_quantile_key", f"{path}.quantiles.{key}")
            points.append((float(key[1:]), _num(value, f"{path}.quantiles.{key}")))
        points.sort()
        if any(b[1] < a[1] for a, b in zip(points, points[1:])):
            raise _Reject("quantiles_not_monotone", f"{path}.quantiles")
        for key in ("p_value_exceeds_price", "p_return_clears_hurdle", "p_cet1_breach"):
            if key in row:
                _prob(row[key], f"{path}.{key}")
        result.append(dict(row))
    return result


def _validate_monitoring(value: Any) -> dict[str, Any]:
    row = _dict(value, "$.monitoring")
    for key in ("drivers", "kill_variables", "limitations", "weakening_observations"):
        for i, entry in enumerate(_list(row.get(key, []), f"$.monitoring.{key}")):
            if key == "kill_variables":
                _dict(entry, f"$.monitoring.{key}[{i}]")
            else:
                _str(entry, f"$.monitoring.{key}[{i}]")
    for i, entry in enumerate(row.get("kill_variables", [])):
        path = f"$.monitoring.kill_variables[{i}]"
        _str(_req(entry, "variable", path), f"{path}.variable")
        _enum(_req(entry, "comparator", path), frozenset({"<", "<=", ">", ">=", "between"}), f"{path}.comparator")
        if "expires_at" in entry:
            _ts(entry["expires_at"], f"{path}.expires_at")
    return dict(row)


def _validate_advisory(items: Any) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_list(items, "$.advisory")):
        path = f"$.advisory[{index}]"
        row = _dict(item, path)
        _str(_req(row, "instrument_id", path), f"{path}.instrument_id")
        _enum(_req(row, "state", path), ADVISORY_STATES, f"{path}.state", "invalid_advisory_state")
        _str(_req(row, "score_definition", path), f"{path}.score_definition")
        if "opportunity_score" in row:
            _num(row["opportunity_score"], f"{path}.opportunity_score")
        if "suggested_exposure_range" in row:
            rng = _dict(row["suggested_exposure_range"], f"{path}.suggested_exposure_range")
            low, high = _prob(_req(rng, "low", path), f"{path}.suggested_exposure_range.low"), _prob(_req(rng, "high", path), f"{path}.suggested_exposure_range.high")
            if low > high:
                raise _Reject("range_inverted", f"{path}.suggested_exposure_range")
        result.append({**row, "advisory_only": True})
    return result


__all__ = [
    "IntelligenceIssue",
    "IntelligenceParseResult",
    "SCHEMA_ID",
    "canonical_json",
    "compute_content_hash",
    "parse_envelope_bytes",
    "seal_envelope",
    "validate_attachment_bytes",
]
