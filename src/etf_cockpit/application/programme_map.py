"""Read-only projection of the canonical issue registry for the app."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REGISTRY_PATH = Path("issues/issue_registry.json")


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


@dataclass(frozen=True)
class ProgrammeMap:
    """Fail-closed, deterministic programme-map payload."""

    status: str
    registry_sha256: str
    entries: tuple[ProgrammeMapEntry, ...] = ()
    counts: tuple[tuple[str, int], ...] = ()
    error: str = ""


def _string(value: object, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted({_string(item) for item in value if _string(item)}))


def _release_state(record: Mapping[str, Any]) -> str:
    """Expose package status without claiming that it is release certification."""

    package_status = _string(record.get("package_status"))
    if package_status:
        return package_status
    return "not_recorded"


def _data_state(record: Mapping[str, Any]) -> str:
    required_inputs = _string_tuple(record.get("required_inputs"))
    return "required_inputs_recorded" if required_inputs else "none_declared"


def _model_state(record: Mapping[str, Any]) -> str:
    """Do not infer model readiness from issue prose or implementation status."""

    value = record.get("model_authority")
    return _string(value, "not_separately_recorded")


def _entry(record: Mapping[str, Any], decision: Mapping[str, Any] | None) -> ProgrammeMapEntry:
    canonical_id = _string(record.get("canonical_id"), "unknown")
    decision = decision or {}
    edges = decision.get("edges") if isinstance(decision.get("edges"), list) else []
    return ProgrammeMapEntry(
        canonical_id=canonical_id,
        title=_string(record.get("title"), "Untitled issue"),
        phase=_string(record.get("phase"), "unassigned"),
        priority=_string(record.get("priority"), "unassigned"),
        implementation=_string(record.get("programme_status"), "unavailable"),
        release=_release_state(record),
        data=_data_state(record),
        model=_model_state(record),
        paper="disabled_by_policy",
        live="disabled_by_policy",
        ready=decision.get("ready") is True,
        readiness_reason_codes=(
            _string_tuple(decision.get("reason_codes"))
            or ("READINESS_EVIDENCE_UNAVAILABLE",)
        ),
        edge_reason_codes=tuple(
            f"{_string(edge.get('dependency_id'), 'unknown')}:{_string(edge.get('reason_code'), 'EDGE_EVIDENCE_UNAVAILABLE')}"
            for edge in edges
            if isinstance(edge, Mapping)
        ),
        activation_ready=decision.get("activation_ready") is True,
        activation_reason_codes=(
            _string_tuple(decision.get("activation_reason_codes"))
            or ("ACTIVATION_EVIDENCE_UNAVAILABLE",)
        ),
        blocking_dependencies=_string_tuple(record.get("blocking_dependencies")),
        required_inputs=_string_tuple(record.get("required_inputs")),
        activation_dependencies=_string_tuple(record.get("activation_dependencies")),
        downstream_issues=_string_tuple(record.get("downstream_issues")),
        related_issues=_string_tuple(record.get("related_issues")),
    )


def build_programme_map(registry: Mapping[str, Any], *, registry_sha256: str = "unavailable") -> ProgrammeMap:
    """Build a deterministic map from a parsed canonical registry."""

    records = registry.get("records")
    if not isinstance(records, list) or not all(isinstance(record, Mapping) for record in records):
        raise ValueError("canonical issue registry must contain a records list of objects")

    readiness = registry.get("readiness")
    decisions = {
        _string(decision.get("issue_id")): decision
        for decision in readiness
        if isinstance(decision, Mapping)
    } if isinstance(readiness, list) else {}
    entries = tuple(
        _entry(record, decisions.get(_string(record.get("canonical_id"))))
        for record in records
    )
    if any(entry.canonical_id == "unknown" for entry in entries):
        raise ValueError("canonical issue registry contains a record without canonical_id")
    if len({entry.canonical_id for entry in entries}) != len(entries):
        raise ValueError("canonical issue registry contains duplicate canonical_id values")

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.implementation] = counts.get(entry.implementation, 0) + 1
    return ProgrammeMap(
        status="loaded",
        registry_sha256=registry_sha256,
        entries=entries,
        counts=tuple(sorted(counts.items())),
    )


def _blocked(error: str, registry_sha256: str = "unavailable") -> ProgrammeMap:
    return ProgrammeMap(status="blocked", registry_sha256=registry_sha256, error=error)


def load_programme_map(root: Path, path: Path | None = None) -> ProgrammeMap:
    """Load the canonical registry without writing or starting any workflow."""

    registry_path = (path or root / DEFAULT_REGISTRY_PATH).resolve()
    try:
        raw = registry_path.read_bytes()
        registry_sha256 = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            return _blocked("canonical issue registry root is not an object", registry_sha256)
        return build_programme_map(value, registry_sha256=registry_sha256)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return _blocked(f"canonical issue registry unavailable: {type(exc).__name__}: {exc}")


__all__ = ["DEFAULT_REGISTRY_PATH", "ProgrammeMap", "ProgrammeMapEntry", "build_programme_map", "load_programme_map"]
