"""Read-only projection of the canonical issue registry for the app."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REGISTRY_PATH = Path("issues/issue_registry.json")
_PROGRAMME_STATUSES = frozenset(
    {
        "blocked",
        "closed",
        "deferred",
        "hardening_required",
        "implemented",
        "implemented_initially",
        "in_progress",
        "integrated",
        "planned",
        "ready",
        "rejected",
        "research_only",
    }
)


@dataclass(frozen=True)
class ProgrammeMapEntry:
    """One issue with independent implementation and authority dimensions."""

    canonical_id: str
    title: str
    phase: str
    priority: str
    implementation: str
    release: str
    data: str
    model: str
    paper: str
    live: str
    ready: bool
    readiness_reason_codes: tuple[str, ...]
    edge_reason_codes: tuple[str, ...]
    activation_ready: bool
    activation_reason_codes: tuple[str, ...]
    blocking_dependencies: tuple[str, ...]
    required_inputs: tuple[str, ...]
    activation_dependencies: tuple[str, ...]
    downstream_issues: tuple[str, ...]
    related_issues: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class ProgrammeMap:
    """Fail-closed, deterministic programme-map payload."""

    status: str
    registry_sha256: str
    entries: tuple[ProgrammeMapEntry, ...] = ()
    counts: tuple[tuple[str, int], ...] = ()
    error: str = ""
    execution_allowed: bool = False


def _string(value: object, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted({_string(item) for item in value if _string(item)}))


def _strict_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"canonical registry field {field} must be a non-empty string")
    return value.strip()


def _strict_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"canonical registry field {field} must be a list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"canonical registry field {field} contains a malformed value")
    return tuple(sorted(set(item.strip() for item in value)))


def _strict_codes(value: object, field: str) -> tuple[str, ...]:
    codes = _strict_string_tuple(value, field)
    if not codes:
        raise ValueError(f"canonical readiness field {field} must not be empty")
    return codes


def _strict_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"canonical readiness field {field} must be boolean")
    return value


def _release_state(record: Mapping[str, Any]) -> str:
    """Expose package status without claiming that it is release certification."""

    package_status = record.get("package_status")
    if package_status is not None and not isinstance(package_status, str):
        raise ValueError("canonical registry field package_status must be a string")
    package_status = _string(package_status)
    if package_status:
        return package_status
    return "not_recorded"


def _data_state(record: Mapping[str, Any]) -> str:
    if "required_inputs" not in record:
        return "not_recorded"
    required_inputs = _strict_string_tuple(record["required_inputs"], "required_inputs")
    return "required_inputs_recorded" if required_inputs else "none_declared"


def _model_state(record: Mapping[str, Any]) -> str:
    """Do not infer model readiness from issue prose or implementation status."""

    if "model_authority" not in record:
        return "not_separately_recorded"
    value = record["model_authority"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("canonical registry field model_authority must be a non-empty string")
    return value.strip()


def _edge_rows(
    value: object,
    *,
    field: str,
    expected_dependencies: tuple[str, ...],
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise ValueError(f"canonical readiness field {field} must be a list")
    rows: list[Mapping[str, Any]] = []
    for index, edge in enumerate(value):
        if not isinstance(edge, Mapping):
            raise ValueError(f"canonical readiness field {field}[{index}] must be an object")
        dependency_id = _strict_string(edge.get("dependency_id"), f"{field}[{index}].dependency_id")
        _strict_bool(edge.get("resolved"), f"{field}[{index}].resolved")
        _strict_string(edge.get("reason_code"), f"{field}[{index}].reason_code")
        if field == "edges":
            _strict_string(edge.get("evidence_state"), f"{field}[{index}].evidence_state")
        rows.append(edge)
        if dependency_id not in expected_dependencies:
            raise ValueError(f"canonical readiness field {field} contains unknown dependency {dependency_id}")
    actual_dependencies = tuple(edge["dependency_id"] for edge in rows)
    if len(set(actual_dependencies)) != len(actual_dependencies) or set(actual_dependencies) != set(expected_dependencies):
        raise ValueError(f"canonical readiness field {field} does not match canonical dependencies")
    return tuple(rows)


def _validate_decision(record: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
    issue_id = _strict_string(decision.get("issue_id"), "issue_id")
    expected_dependencies = _strict_string_tuple(record.get("blocking_dependencies", []), "blocking_dependencies")
    expected_activation = _strict_string_tuple(record.get("activation_dependencies", []), "activation_dependencies")
    record_inputs = (
        _strict_string_tuple(record["required_inputs"], "required_inputs")
        if "required_inputs" in record
        else None
    )
    decision_inputs = _strict_string_tuple(decision.get("required_inputs"), "readiness.required_inputs")
    if record_inputs is not None and decision_inputs != record_inputs:
        raise ValueError(f"readiness required_inputs does not match record {issue_id}")
    ready = _strict_bool(decision.get("ready"), f"{issue_id}.ready")
    activation_ready = _strict_bool(decision.get("activation_ready"), f"{issue_id}.activation_ready")
    if decision.get("execution_allowed") is not False:
        raise ValueError(f"readiness execution_allowed must remain false for {issue_id}")
    _strict_codes(decision.get("reason_codes"), f"{issue_id}.reason_codes")
    _strict_codes(decision.get("activation_reason_codes"), f"{issue_id}.activation_reason_codes")
    edges = _edge_rows(decision.get("edges"), field="edges", expected_dependencies=expected_dependencies)
    activation_edges = _edge_rows(
        decision.get("activation_edges"),
        field="activation_edges",
        expected_dependencies=expected_activation,
    )
    derived_ready = record.get("ledger_state") != "closed" and all(edge["resolved"] is True for edge in edges)
    derived_activation_ready = all(edge["resolved"] is True for edge in activation_edges)
    if ready is not derived_ready:
        raise ValueError(f"readiness ready is inconsistent with canonical closure evidence for {issue_id}")
    if activation_ready is not derived_activation_ready:
        raise ValueError(f"readiness activation_ready is inconsistent with canonical closure evidence for {issue_id}")


def _entry(record: Mapping[str, Any], decision: Mapping[str, Any] | None) -> ProgrammeMapEntry:
    canonical_id = _string(record.get("canonical_id"), "unknown")
    if decision is None:
        raise ValueError(f"canonical readiness is missing for {canonical_id}")
    edges = decision["edges"]
    return ProgrammeMapEntry(
        canonical_id=canonical_id,
        title=_string(record.get("title"), "Untitled issue"),
        phase=_string(record.get("phase"), "unassigned"),
        priority=_string(record.get("priority"), "unassigned"),
        implementation=_string(record.get("programme_status"), "not_recorded"),
        release=_release_state(record),
        data=_data_state(record),
        model=_model_state(record),
        paper="disabled_by_policy",
        live="disabled_by_policy",
        ready=decision["ready"],
        readiness_reason_codes=tuple(decision["reason_codes"]),
        edge_reason_codes=tuple(
            f"{_string(edge.get('dependency_id'), 'unknown')}:{_string(edge.get('reason_code'), 'EDGE_EVIDENCE_UNAVAILABLE')}"
            for edge in edges
        ),
        activation_ready=decision["activation_ready"],
        activation_reason_codes=tuple(decision["activation_reason_codes"]),
        blocking_dependencies=_string_tuple(record.get("blocking_dependencies")),
        required_inputs=_string_tuple(record.get("required_inputs")),
        activation_dependencies=_string_tuple(record.get("activation_dependencies")),
        downstream_issues=_string_tuple(record.get("downstream_issues")),
        related_issues=_string_tuple(record.get("related_issues")),
        execution_allowed=False,
    )


def build_programme_map(registry: Mapping[str, Any], *, registry_sha256: str = "unavailable") -> ProgrammeMap:
    """Build a deterministic map from a parsed canonical registry."""

    policy = registry.get("policy")
    if not isinstance(policy, Mapping) or policy.get("execution_allowed") is not False:
        raise ValueError("canonical registry policy execution_allowed must be false")

    records = registry.get("records")
    if not isinstance(records, list) or not all(isinstance(record, Mapping) for record in records):
        raise ValueError("canonical issue registry must contain a records list of objects")
    if not records:
        raise ValueError("canonical issue registry records must not be empty")

    readiness = registry.get("readiness")
    if not isinstance(readiness, list) or not readiness:
        raise ValueError("canonical issue registry must contain a complete readiness list")
    record_ids: list[str] = []
    for record in records:
        canonical_id = _strict_string(record.get("canonical_id"), "canonical_id")
        record_ids.append(canonical_id)
        if "programme_status" in record and record["programme_status"] not in (None, ""):
            programme_status = _strict_string(record["programme_status"], "programme_status")
            if programme_status not in _PROGRAMME_STATUSES:
                raise ValueError(f"unsupported programme_status for {canonical_id}: {programme_status}")
        for field in ("blocking_dependencies", "activation_dependencies"):
            _strict_string_tuple(record.get(field, []), field)
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("canonical issue registry contains duplicate canonical_id values")
    decisions: dict[str, Mapping[str, Any]] = {}
    for decision in readiness:
        if not isinstance(decision, Mapping):
            raise ValueError("canonical readiness entries must be objects")
        issue_id = _strict_string(decision.get("issue_id"), "issue_id")
        if issue_id in decisions:
            raise ValueError(f"canonical readiness contains duplicate issue_id {issue_id}")
        record = next(record for record in records if record["canonical_id"] == issue_id) if issue_id in record_ids else None
        if record is None:
            raise ValueError(f"canonical readiness contains unknown issue_id {issue_id}")
        _validate_decision(record, decision)
        decisions[issue_id] = decision
    if set(decisions) != set(record_ids):
        raise ValueError("canonical readiness list is partial")
    entries = tuple(
        _entry(record, decisions[record["canonical_id"]])
        for record in records
    )

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.implementation] = counts.get(entry.implementation, 0) + 1
    return ProgrammeMap(
        status="loaded",
        registry_sha256=registry_sha256,
        entries=entries,
        counts=tuple(sorted(counts.items())),
        execution_allowed=False,
    )


def _blocked(error: str, registry_sha256: str = "unavailable") -> ProgrammeMap:
    return ProgrammeMap(status="blocked", registry_sha256=registry_sha256, error=error)


def load_programme_map(root: Path, path: Path | None = None) -> ProgrammeMap:
    """Load the canonical registry without writing or starting any workflow."""

    registry_path = (path or root / DEFAULT_REGISTRY_PATH).resolve()
    registry_sha256 = "unavailable"
    try:
        raw = registry_path.read_bytes()
        registry_sha256 = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            return _blocked("canonical issue registry root is not an object", registry_sha256)
        return build_programme_map(value, registry_sha256=registry_sha256)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _blocked(f"canonical issue registry unavailable: {type(exc).__name__}: {exc}", registry_sha256)


__all__ = ["DEFAULT_REGISTRY_PATH", "ProgrammeMap", "ProgrammeMapEntry", "build_programme_map", "load_programme_map"]
