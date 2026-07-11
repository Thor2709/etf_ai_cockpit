from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterator, Mapping

import yaml


VALID_GATES = frozenset(
    {
        "source",
        "schema",
        "tests",
        "ui",
        "audit",
        "export",
        "package",
        "build",
        "browser",
    }
)
VALID_STATUSES = frozenset({"still_open", "closed", "blocked", "deferred"})


@dataclass(frozen=True)
class ClosureCriterion:
    criterion_id: str
    text: str
    required_gates: tuple[str, ...]
    evidence_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueClosureRecord:
    issue_id: str
    title: str
    wave: int
    criteria: tuple[ClosureCriterion, ...]
    status: str = "still_open"


@dataclass(frozen=True)
class ClosureEvaluation:
    issue_id: str
    ready: bool
    missing_gates: tuple[str, ...]
    evidence_paths: tuple[str, ...]


@dataclass(frozen=True)
class ClosureMatrix:
    programme_schema_version: int
    historic_baseline_count: int
    records: tuple[IssueClosureRecord, ...]
    verification_policy: Mapping[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator[IssueClosureRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> IssueClosureRecord:
        return self.records[index]

    def record_for(self, issue_id: str) -> IssueClosureRecord:
        for record in self.records:
            if record.issue_id == issue_id:
                return record
        raise KeyError(issue_id)


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _parse_criterion(raw: Any, issue_id: str) -> ClosureCriterion:
    if not isinstance(raw, dict):
        raise ValueError(f"{issue_id} criteria must be mappings")
    criterion_id = _require_text(raw.get("criterion_id"), "criterion_id")
    text = _require_text(raw.get("text"), "criterion text")
    gates = tuple(_require_text(gate, "required gate") for gate in raw.get("required_gates", ()))
    if not gates:
        raise ValueError(f"{criterion_id} must require at least one gate")
    unknown_gates = sorted(set(gates) - VALID_GATES)
    if unknown_gates:
        raise ValueError(f"{criterion_id} has unknown gates: {', '.join(unknown_gates)}")
    paths = tuple(_normalise_evidence_path(path) for path in raw.get("evidence_paths", ()))
    return ClosureCriterion(criterion_id, text, gates, paths)


def _normalise_evidence_path(value: Any) -> str:
    path = _require_text(value, "evidence path").replace("\\", "/")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or re.match(r"^[A-Za-z]:/", path):
        raise ValueError(f"evidence path must be relative to the evidence root: {path}")
    return parsed.as_posix()


def load_closure_matrix(path: Path) -> ClosureMatrix:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("issues"), list):
        raise ValueError("closure matrix must contain an issues list")

    programme_schema_version = raw.get("programme_schema_version", raw.get("schema_version", 1))
    if isinstance(programme_schema_version, bool) or not isinstance(programme_schema_version, int):
        raise ValueError("programme_schema_version must be an integer")
    historic_baseline_count = raw.get("historic_baseline_count", len(raw["issues"]))
    if isinstance(historic_baseline_count, bool) or not isinstance(historic_baseline_count, int):
        raise ValueError("historic_baseline_count must be an integer")

    policy = raw.get("verification_policy", {})
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise ValueError("verification_policy must be a mapping")

    records: list[IssueClosureRecord] = []
    seen_issues: set[str] = set()
    seen_criteria: set[str] = set()
    for item in raw["issues"]:
        if not isinstance(item, dict):
            raise ValueError("each issue must be a mapping")
        issue_id = _require_text(item.get("issue_id"), "issue_id")
        if issue_id in seen_issues:
            raise ValueError(f"duplicate issue_id: {issue_id}")
        seen_issues.add(issue_id)
        status = _require_text(item.get("status", "still_open"), "status")
        if status not in VALID_STATUSES:
            raise ValueError(f"{issue_id} has invalid status: {status}")
        criteria = tuple(_parse_criterion(value, issue_id) for value in item.get("criteria", ()))
        if not criteria:
            raise ValueError(f"{issue_id} must contain criteria")
        for criterion in criteria:
            if criterion.criterion_id in seen_criteria:
                raise ValueError(f"duplicate criterion_id: {criterion.criterion_id}")
            seen_criteria.add(criterion.criterion_id)
        wave = item.get("wave")
        if isinstance(wave, bool) or not isinstance(wave, int) or wave < 1:
            raise ValueError(f"{issue_id} wave must be a positive integer")
        records.append(
            IssueClosureRecord(
                issue_id=issue_id,
                title=_require_text(item.get("title"), "title"),
                wave=wave,
                criteria=criteria,
                status=status,
            )
        )
    return ClosureMatrix(
        programme_schema_version=programme_schema_version,
        historic_baseline_count=historic_baseline_count,
        records=tuple(records),
        verification_policy=policy,
    )


def _gate_for_path(path: str) -> str | None:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    return parts[0] if parts and parts[0] in VALID_GATES else None


def evaluate_issue(record: IssueClosureRecord, evidence_root: Path) -> ClosureEvaluation:
    evidence_paths = tuple(
        dict.fromkeys(path for criterion in record.criteria for path in criterion.evidence_paths)
    )
    missing: set[str] = set()
    for criterion in record.criteria:
        existing_gates = {
            gate
            for path in criterion.evidence_paths
            if (gate := _gate_for_path(path)) is not None and _is_verified_evidence(evidence_root, path)
        }
        missing.update(set(criterion.required_gates) - existing_gates)
    missing_gates = tuple(gate for gate in sorted(VALID_GATES) if gate in missing)
    return ClosureEvaluation(
        issue_id=record.issue_id,
        ready=not missing_gates,
        missing_gates=missing_gates,
        evidence_paths=evidence_paths,
    )


def _is_verified_evidence(evidence_root: Path, relative_path: str) -> bool:
    try:
        root = evidence_root.resolve(strict=True)
        candidate = evidence_root / relative_path
        checksum_path = candidate.with_name(candidate.name + ".sha256")
        if candidate.is_symlink() or checksum_path.is_symlink():
            return False
        resolved = candidate.resolve(strict=True)
        resolved_checksum = checksum_path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved_checksum.is_relative_to(root):
            return False
        if not resolved.is_file() or not resolved_checksum.is_file():
            return False
        expected = resolved_checksum.read_text(encoding="ascii").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            return False
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected
    except (OSError, UnicodeError):
        return False
