"""Read-only projection of the canonical issue registry for the app."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
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
_EDGE_EVIDENCE_STATES = frozenset({"unresolved", "complete", "partial_interface", "waived"})
_ISSUE_ID_RE = re.compile(r"(?:ISSUE|UPDATEV2)-\d{4}")
_PRIORITIES = frozenset({"P0", "P0/P1", "P1", "P1/P2", "P2", "P3"})
_CLASSIFICATIONS = frozenset(
    {
        "current_open_retained",
        "current_closed_reconciled",
        "local_only_current",
        "local_only_closed",
        "proposed_new",
    }
)
_EDGE_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "evidence_references",
        "contract_reference",
        "reviewer",
        "reviewed_date",
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


def _strict_issue_id(value: object, field: str) -> str:
    issue_id = _strict_string(value, field)
    if value != issue_id or _ISSUE_ID_RE.fullmatch(issue_id) is None:
        raise ValueError(f"canonical registry field {field} must be a canonical issue ID")
    return issue_id


def _strict_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"canonical registry field {field} must be a list of strings")
    if any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in value
    ):
        raise ValueError(f"canonical registry field {field} contains a malformed value")
    if len(set(value)) != len(value):
        raise ValueError(f"canonical registry field {field} contains duplicate values")
    return tuple(sorted(value))


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


def _edge_evidence_is_valid(evidence: object) -> bool:
    if (
        not isinstance(evidence, Mapping)
        or set(evidence) != _EDGE_EVIDENCE_KEYS
        or evidence.get("schema_version") != "1.0"
    ):
        return False
    state = evidence.get("state")
    if state not in _EDGE_EVIDENCE_STATES:
        return False
    references = evidence.get("evidence_references")
    if not isinstance(references, list) or any(
        not isinstance(reference, str) or not reference.strip() for reference in references
    ):
        return False
    if state == "unresolved":
        return references == [] and all(
            evidence.get(field) == "" for field in ("contract_reference", "reviewer", "reviewed_date")
        )
    if not references:
        return False
    if not all(
        isinstance(evidence.get(field), str) and evidence[field].strip()
        for field in ("contract_reference", "reviewer", "reviewed_date")
    ):
        return False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", evidence["reviewed_date"]) is None:
        return False
    try:
        date.fromisoformat(evidence["reviewed_date"])
    except ValueError:
        return False
    return True


def _validate_decision(
    record: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    closed_ids: frozenset[str],
) -> None:
    issue_id = _strict_string(decision.get("issue_id"), "issue_id")
    ledger_state = record.get("ledger_state")
    if ledger_state not in {"open", "closed"}:
        raise ValueError(f"canonical record ledger_state must be open or closed for {issue_id}")
    expected_dependencies = _strict_string_tuple(record.get("blocking_dependencies", []), "blocking_dependencies")
    expected_activation = _strict_string_tuple(record.get("activation_dependencies", []), "activation_dependencies")
    record_inputs = _strict_string_tuple(record.get("required_inputs"), "required_inputs")
    decision_inputs = _strict_string_tuple(decision.get("required_inputs"), "readiness.required_inputs")
    if decision_inputs != record_inputs:
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
    evidence_by_edge = record.get("dependency_edge_evidence")
    if (
        not isinstance(evidence_by_edge, Mapping)
        or set(evidence_by_edge) != set(expected_dependencies)
        or any(not _edge_evidence_is_valid(evidence) for evidence in evidence_by_edge.values())
    ):
        raise ValueError(f"canonical dependency edge evidence is malformed for {issue_id}")

    expected_edges: list[dict[str, object]] = []
    invalid_edge = False
    unresolved_edge = False
    for dependency in expected_dependencies:
        evidence = evidence_by_edge.get(dependency, {})
        state = evidence.get("state", "unresolved") if isinstance(evidence, Mapping) else "unresolved"
        if dependency in closed_ids:
            resolved = True
            reason_code = "DEPENDENCY_LEDGER_CLOSED"
        elif state != "unresolved" and _edge_evidence_is_valid(evidence):
            resolved = True
            reason_code = f"EDGE_EVIDENCE_{str(state).upper()}"
        elif state != "unresolved":
            resolved = False
            invalid_edge = True
            reason_code = "EDGE_EVIDENCE_INVALID"
        else:
            resolved = False
            unresolved_edge = True
            reason_code = "EDGE_UNRESOLVED"
        expected_edges.append(
            {
                "dependency_id": dependency,
                "resolved": resolved,
                "reason_code": reason_code,
                "evidence_state": state,
            }
        )

    if ledger_state == "closed":
        expected_ready = False
        expected_reasons = ["CLOSED_LEDGER_NOT_IMPLEMENTATION_CANDIDATE"]
    elif invalid_edge:
        expected_ready = False
        expected_reasons = ["BLOCKED_INVALID_EDGE_EVIDENCE"]
        if unresolved_edge:
            expected_reasons.append("BLOCKED_UNRESOLVED_DEPENDENCY")
    elif unresolved_edge:
        expected_ready = False
        expected_reasons = ["BLOCKED_UNRESOLVED_DEPENDENCY"]
    else:
        expected_ready = True
        expected_reasons = ["READY_BLOCKING_EDGES_RESOLVED" if expected_edges else "READY_NO_BLOCKING_DEPENDENCIES"]

    expected_activation_edges = [
        {
            "dependency_id": dependency,
            "resolved": dependency in closed_ids,
            "reason_code": (
                "ACTIVATION_DEPENDENCY_LEDGER_CLOSED"
                if dependency in closed_ids
                else "ACTIVATION_EDGE_UNRESOLVED"
            ),
        }
        for dependency in expected_activation
    ]
    expected_activation_ready = all(edge["resolved"] is True for edge in expected_activation_edges)
    expected_activation_reasons = [
        (
            "ACTIVATION_READY_DEPENDENCIES_RESOLVED"
            if expected_activation_edges
            else "ACTIVATION_READY_NO_DEPENDENCIES"
        )
        if expected_activation_ready
        else "ACTIVATION_BLOCKED_UNRESOLVED_DEPENDENCY"
    ]
    if (
        ready is not expected_ready
        or list(decision["reason_codes"]) != expected_reasons
        or list(edges) != expected_edges
        or activation_ready is not expected_activation_ready
        or list(decision["activation_reason_codes"]) != expected_activation_reasons
        or list(activation_edges) != expected_activation_edges
    ):
        raise ValueError(f"readiness projection is inconsistent with canonical closure evidence for {issue_id}")


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

    roadmap_phases = registry.get("roadmap_phases")
    if not isinstance(roadmap_phases, list) or not roadmap_phases:
        raise ValueError("canonical registry roadmap_phases must be a non-empty list")
    phase_ids: set[str] = set()
    for phase in roadmap_phases:
        if not isinstance(phase, Mapping):
            raise ValueError("canonical roadmap phase entries must be objects")
        phase_id = _strict_string(phase.get("phase"), "roadmap_phases.phase")
        if phase_id in phase_ids:
            raise ValueError("canonical roadmap phase IDs must be unique")
        phase_ids.add(phase_id)

    readiness = registry.get("readiness")
    if not isinstance(readiness, list) or not readiness:
        raise ValueError("canonical issue registry must contain a complete readiness list")
    record_ids: list[str] = []
    records_by_id: dict[str, Mapping[str, Any]] = {}
    for record in records:
        canonical_id = _strict_issue_id(record.get("canonical_id"), "canonical_id")
        record_ids.append(canonical_id)
        records_by_id[canonical_id] = record
        programme_status = _strict_string(record.get("programme_status"), "programme_status")
        if programme_status not in _PROGRAMME_STATUSES:
            raise ValueError(f"unsupported programme_status for {canonical_id}: {programme_status}")
        if record.get("classification") not in _CLASSIFICATIONS:
            raise ValueError(f"canonical record classification is invalid for {canonical_id}")
        if record.get("priority") not in _PRIORITIES:
            raise ValueError(f"canonical record priority is invalid for {canonical_id}")
        if record.get("phase") not in phase_ids:
            raise ValueError(f"canonical record phase is invalid for {canonical_id}")
        required_types = {
            "provenance": Mapping,
            "verified_commit": str,
            "verified_date": str,
            "acceptance_evidence": list,
            "capability_lane": str,
            "release_blocking": bool,
            "write_conflict_group": str,
            "risk": Mapping,
            "owner": str,
        }
        for field, expected_type in required_types.items():
            value = record.get(field)
            if not isinstance(value, expected_type) or (
                expected_type is str and not value.strip()
            ):
                raise ValueError(f"canonical record field {field} is invalid for {canonical_id}")
        for field in (
            "blocking_dependencies",
            "required_inputs",
            "activation_dependencies",
            "downstream_issues",
            "related_issues",
        ):
            if field not in record:
                raise ValueError(f"canonical registry field {field} is required")
            for dependency in _strict_string_tuple(record[field], field):
                _strict_issue_id(dependency, field)
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("canonical issue registry contains duplicate canonical_id values")
    known_ids = set(record_ids)
    relationship_fields = (
        "blocking_dependencies",
        "required_inputs",
        "activation_dependencies",
        "downstream_issues",
        "related_issues",
    )
    for canonical_id, record in records_by_id.items():
        for field in relationship_fields:
            references = set(_strict_string_tuple(record[field], field))
            if canonical_id in references:
                raise ValueError(f"canonical record {canonical_id} contains a self-reference")
            unknown = references - known_ids
            if unknown:
                raise ValueError(f"canonical record {canonical_id} contains unknown {field}")

    expected_downstream: dict[str, set[str]] = {issue_id: set() for issue_id in known_ids}
    for source_id, record in records_by_id.items():
        for field in ("blocking_dependencies", "required_inputs", "activation_dependencies"):
            for dependency in _strict_string_tuple(record[field], field):
                expected_downstream[dependency].add(source_id)
    for issue_id, record in records_by_id.items():
        if set(_strict_string_tuple(record["downstream_issues"], "downstream_issues")) != expected_downstream[issue_id]:
            raise ValueError(f"canonical downstream links are inconsistent for {issue_id}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(issue_id: str) -> None:
        if issue_id in visiting:
            raise ValueError("canonical blocking dependency graph contains a cycle")
        if issue_id in visited:
            return
        visiting.add(issue_id)
        for dependency in _strict_string_tuple(
            records_by_id[issue_id]["blocking_dependencies"], "blocking_dependencies"
        ):
            visit(dependency)
        visiting.remove(issue_id)
        visited.add(issue_id)

    for issue_id in sorted(known_ids):
        visit(issue_id)
    closed_ids = {issue_id for issue_id, record in records_by_id.items() if record.get("ledger_state") == "closed"}
    local_only_records = registry.get("local_only_records", [])
    if not isinstance(local_only_records, list) or not all(isinstance(record, Mapping) for record in local_only_records):
        raise ValueError("canonical local-only records must be a list of objects")
    if local_only_records:
        raise ValueError("canonical local-only records must be folded into canonical records")
    decisions: dict[str, Mapping[str, Any]] = {}
    for decision in readiness:
        if not isinstance(decision, Mapping):
            raise ValueError("canonical readiness entries must be objects")
        issue_id = _strict_issue_id(decision.get("issue_id"), "issue_id")
        if issue_id in decisions:
            raise ValueError(f"canonical readiness contains duplicate issue_id {issue_id}")
        record = records_by_id.get(issue_id)
        if record is None:
            raise ValueError(f"canonical readiness contains unknown issue_id {issue_id}")
        _validate_decision(record, decision, closed_ids=frozenset(closed_ids))
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
