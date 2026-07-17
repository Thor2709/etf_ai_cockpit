"""Shared parsing and deterministic modelling for the completion programme."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ISSUE_ID_RE = re.compile(r"\b(?:ISSUE|UPDATEV2)-\d{4}\b")
OPEN_HEADING_RE = re.compile(
    r"(?m)^##\s+((?:ISSUE|UPDATEV2)-\d{4})\s+-\s+(.+?)\s*$"
)
CLOSED_INDEX_RE = re.compile(
    r"(?m)^\|\s+`((?:ISSUE|UPDATEV2)-\d{4})`\s+\|\s+(.+?)\s+\|\s+(.+?)\s+\|\s+\[record\]\((#[^)]+)\)\s*\|$"
)
PRIORITIES = frozenset({"P0", "P0/P1", "P1", "P1/P2", "P2", "P3"})
CLASSIFICATIONS = frozenset(
    {"current_open_retained", "current_closed_reconciled", "proposed_new"}
)
LEDGER_STATES = frozenset({"open", "closed"})
PROGRAMME_STATUSES = frozenset(
    {
        "planned",
        "ready",
        "implemented_initially",
        "in_progress",
        "integrated",
        "hardening_required",
        "blocked",
        "rejected",
        "implemented",
        "deferred",
        "research_only",
        "closed",
    }
)
PROGRAMME_STATUS_OVERRIDES = {
    "ISSUE-0070": "integrated",
    "ISSUE-0071": "integrated",
    "ISSUE-0038": "integrated",
    "ISSUE-0072": "integrated",
    "ISSUE-0073": "integrated",
    "ISSUE-0074": "integrated",
    "ISSUE-0075": "integrated",
    "ISSUE-0077": "integrated",
    "ISSUE-0091": "integrated",
    "ISSUE-0110": "integrated",
    "ISSUE-0111": "integrated",
    "ISSUE-0136": "integrated",
    "ISSUE-0141": "integrated",
    "ISSUE-0076": "integrated",
    "ISSUE-0078": "integrated",
    "ISSUE-0080": "integrated",
    "ISSUE-0081": "integrated",
    "ISSUE-0013": "integrated",
    "UPDATEV2-0029": "integrated",
    "ISSUE-0145": "integrated",
    "ISSUE-0144": "integrated",
    "ISSUE-0146": "integrated",
    "ISSUE-0028": "implemented_initially",
    "ISSUE-0049": "implemented_initially",
    "ISSUE-0050": "implemented_initially",
    "ISSUE-0065": "implemented_initially",
    "ISSUE-0149": "hardening_required",
    "ISSUE-0152": "blocked",
    "ISSUE-0079": "hardening_required",
}
PACKAGE_JSON = Path("docs/product-completion/sources/2026-07-15/ETF_AI_Cockpit_Master_Issue_Registry.json")
SOURCE_MANIFEST = Path("docs/product-completion/sources/2026-07-15/SOURCE_MANIFEST.sha256")
OPEN_LEDGER = Path("issues/open.md")
CLOSED_LEDGER = Path("issues/closed.md")
REGISTRY_PATH = Path("issues/issue_registry.json")
PROGRAMME_ROOT = Path("docs/product-completion")
STATUS_PATH = PROGRAMME_ROOT / "CURRENT_STATUS.json"
PROGRESS_PATH = PROGRAMME_ROOT / "PROGRESS.md"
RECONCILIATION_ROOT = PROGRAMME_ROOT / "reconciliation"

PHASES: tuple[dict[str, Any], ...] = (
    {
        "phase": "phase-01-governance-scope",
        "title": "Governance, scope and completion contract",
        "issue_range": "ISSUE-0070–ISSUE-0079",
        "ids": set(range(70, 80)),
    },
    {
        "phase": "phase-02-data-policy-identity",
        "title": "Local-first data policy, identity and data platform",
        "issue_range": "ISSUE-0080–ISSUE-0090",
        "ids": set(range(80, 91)),
    },
    {
        "phase": "phase-03-stock-research",
        "title": "Stock statements, fundamentals, valuation and sectors",
        "issue_range": "ISSUE-0091–ISSUE-0102",
        "ids": set(range(91, 103)),
    },
    {
        "phase": "phase-04-etf-research",
        "title": "ETF economics, structure, exposure and context",
        "issue_range": "ISSUE-0103–ISSUE-0107",
        "ids": set(range(103, 108)),
    },
    {
        "phase": "phase-05-returns-risk-portfolio",
        "title": "Expected return, risk and portfolio construction",
        "issue_range": "ISSUE-0108–ISSUE-0116",
        "ids": set(range(108, 117)),
    },
    {
        "phase": "phase-06-model-research",
        "title": "Training, validation and model governance",
        "issue_range": "ISSUE-0117–ISSUE-0124",
        "ids": set(range(117, 125)),
    },
    {
        "phase": "phase-07-backtest-paper-execution",
        "title": "Backtest, paper trading and staged execution",
        "issue_range": "ISSUE-0125–ISSUE-0135",
        "ids": set(range(125, 136)),
    },
    {
        "phase": "phase-08-frontend-api",
        "title": "Typed local API and task-oriented frontend",
        "issue_range": "ISSUE-0136–ISSUE-0140",
        "ids": set(range(136, 141)),
    },
    {
        "phase": "phase-09-quality-release-security",
        "title": "Quality, release, security and resilience",
        "issue_range": "ISSUE-0141–ISSUE-0146",
        "ids": set(range(141, 147)),
    },
    {
        "phase": "phase-10-audit-documentation-governance",
        "title": "Audit, reproducibility, documentation and governance",
        "issue_range": "ISSUE-0147–ISSUE-0151",
        "ids": set(range(147, 152)),
    },
    {
        "phase": "phase-11-certification",
        "title": "Final certification and programme closure",
        "issue_range": "ISSUE-0152",
        "ids": {152},
    },
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def issue_number(issue_id: str) -> int | None:
    if not issue_id.startswith("ISSUE-"):
        return None
    return int(issue_id.rsplit("-", 1)[1])


def parse_issue_refs(value: object) -> list[str]:
    return sorted(set(ISSUE_ID_RE.findall(str(value))))


def _section_text(text: str, issue_id: str) -> str:
    matches = list(OPEN_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1) != issue_id:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[match.start():end]
    return ""


def parse_open_ledger(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    records: dict[str, dict[str, Any]] = {}
    for match in OPEN_HEADING_RE.finditer(text):
        issue_id, title = match.groups()
        section = _section_text(text, issue_id)
        status_match = re.search(r"(?mi)^\*\*Status:\*\*\s*(.+?)\s*$", section)
        priority_match = re.search(r"(?mi)^\*\*Priority:\*\*\s*(.+?)\s*$", section)
        records[issue_id] = {
            "canonical_id": issue_id,
            "title": title.strip(),
            "status": status_match.group(1).strip() if status_match else "Open",
            "priority": priority_match.group(1).strip() if priority_match else "",
            "section": section,
        }
    return records


def parse_closed_index(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    records: dict[str, dict[str, str]] = {}
    for match in CLOSED_INDEX_RE.finditer(text):
        issue_id, title, final_state, anchor = match.groups()
        records[issue_id] = {
            "canonical_id": issue_id,
            "title": title.strip(),
            "final_state": final_state.strip(),
            "anchor": anchor,
        }
    return records


def load_package_registry(root: Path) -> dict[str, Any]:
    path = root / PACKAGE_JSON
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Package registry must be an object: {path}")
    return value


def read_manifest(root: Path) -> dict[str, str]:
    path = root / SOURCE_MANIFEST
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        digest, member, *_ = line.split()
        result[member] = digest
    return result


def baseline_sha(root: Path) -> str:
    intake_reports = sorted((root / RECONCILIATION_ROOT).glob("*/intake-report.json"), reverse=True)
    for path in intake_reports:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        baseline = value.get("baseline_commit") if isinstance(value, dict) else None
        if isinstance(baseline, str) and re.fullmatch(r"[0-9a-f]{40}", baseline):
            return baseline
    for ref in ("origin/main", "HEAD"):
        try:
            return subprocess.check_output(
                ["git", "rev-parse", ref], cwd=root, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            continue
    return "unknown"


def owner_for(row: dict[str, Any], source_kind: str) -> str:
    if source_kind == "proposed":
        return {
            "Foundation & governance": "programme-governance",
            "Data platform": "data-platform",
            "Data programme": "data-platform",
            "Scoring architecture": "scoring-and-evidence",
            "Reproducibility": "reproducibility",
            "Extensibility": "platform-and-operations",
            "Workflow platform": "platform-and-operations",
            "Performance": "platform-and-operations",
            "Supply-chain governance": "security-and-release",
            "Stock analysis": "stock-research",
            "ETF analysis": "etf-research",
            "Expected return": "returns-and-risk",
            "Risk model": "returns-and-risk",
            "Benchmarking": "returns-and-risk",
            "Portfolio construction": "portfolio-construction",
            "Risk & scenarios": "returns-and-risk",
            "Attribution": "returns-and-risk",
            "Model research": "model-governance",
            "Backtest & execution": "backtest-and-paper",
            "Trading foundation": "trading-safety",
            "Paper trading": "backtest-and-paper",
            "Broker integration": "trading-safety",
            "Execution safety": "trading-safety",
            "Execution": "trading-safety",
            "Execution analytics": "trading-safety",
            "Frontend & API": "frontend-and-api",
            "Quality & release": "quality-and-release",
            "Security": "security-and-release",
            "Security & resilience": "security-and-release",
            "Audit & reproducibility": "audit-and-reproducibility",
            "Documentation": "documentation",
            "Governance": "programme-governance",
            "Model governance": "model-governance",
            "Performance & release": "quality-and-release",
            "Final certification": "programme-governance",
        }.get(str(row.get("epic", "")), "programme-governance")
    title = str(row.get("title", "")).lower()
    if any(
        word in title
        for word in ("navigation", "onboarding", "screener", "journal", "accessibility", "chart", "manual", "user interface")
    ) or re.search(r"\bui\b", title):
        return "frontend-and-api"
    if any(word in title for word in ("provider", "filing", "etf", "fundamental", "news", "data", "identity", "source conflict")):
        return "data-and-evidence"
    if any(word in title for word in ("score", "benchmark", "risk", "return", "backtest", "strategy", "crowding", "edge")):
        return "analysis-and-validation"
    if any(word in title for word in ("execution", "paper", "broker", "reconciliation", "authority")):
        return "trading-safety"
    if any(word in title for word in ("storage", "database", "backup", "performance", "rebuild", "error")):
        return "platform-and-operations"
    return "programme-governance"


def phase_for(issue_id: str, owner: str) -> str:
    number = issue_number(issue_id)
    if number is not None:
        for phase in PHASES:
            if number in phase["ids"]:
                return str(phase["phase"])
    owner_to_phase = {
        "frontend-and-api": "phase-08-frontend-api",
        "data-and-evidence": "phase-02-data-policy-identity",
        "analysis-and-validation": "phase-05-returns-risk-portfolio",
        "trading-safety": "phase-07-backtest-paper-execution",
        "platform-and-operations": "phase-01-governance-scope",
    }
    return owner_to_phase.get(owner, "phase-01-governance-scope")


def programme_status(source_kind: str, row: dict[str, Any], ledger_state: str) -> str:
    if ledger_state == "closed":
        return "closed"
    if row.get("issue_id") in PROGRAMME_STATUS_OVERRIDES:
        return PROGRAMME_STATUS_OVERRIDES[str(row["issue_id"])]
    if source_kind == "proposed":
        return "ready" if row.get("issue_id") == "ISSUE-0070" else "planned"
    status = str(row.get("status", "")).lower()
    if "research-only" in status:
        return "research_only"
    if "partial" in status:
        return "in_progress"
    if "implementation complete" in status:
        return "implemented_initially"
    return "planned"


def _would_create_cycle(graph: dict[str, set[str]], source: str, dependency: str) -> bool:
    if source == dependency:
        return True
    pending = [dependency]
    visited: set[str] = set()
    while pending:
        node = pending.pop()
        if node == source:
            return True
        if node in visited:
            continue
        visited.add(node)
        pending.extend(graph.get(node, set()))
    return False


def _dependency_resolution(
    rows: Iterable[tuple[str, str, dict[str, Any]]],
    package_ids: set[str],
    closed_ids: set[str],
    local_open_ids: set[str] | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    graph: dict[str, set[str]] = defaultdict(set)
    blocking: dict[str, list[str]] = defaultdict(list)
    related: dict[str, list[str]] = defaultdict(list)
    conversions: dict[str, list[dict[str, str]]] = defaultdict(list)
    report: list[dict[str, str]] = []
    known = package_ids | closed_ids | (local_open_ids or set())
    for source_id, source_kind, row in rows:
        for dependency in parse_issue_refs(row.get("dependencies", "")):
            candidate = {
                "source_id": source_id,
                "dependency": dependency,
                "candidate_type": "blocking" if source_kind == "proposed" else "related",
            }
            if dependency not in known:
                related[source_id].append(dependency)
                candidate["resolved_as"] = "related_issues"
                candidate["reason"] = "reference is outside the package and closed index"
                report.append(candidate)
                continue
            if source_kind != "proposed":
                related[source_id].append(dependency)
                candidate["resolved_as"] = "related_issues"
                candidate["reason"] = "current-ledger dependency retained as a candidate pending explicit prerequisite review"
                report.append(candidate)
                continue
            if _would_create_cycle(graph, source_id, dependency):
                related[source_id].append(dependency)
                conversions[source_id].append(
                    {
                        "dependency": dependency,
                        "from": "blocking_candidate",
                        "to": "related_issues",
                        "reason": "blocking graph cycle prevention",
                    }
                )
                candidate["resolved_as"] = "related_issues"
                candidate["reason"] = "blocking graph cycle prevention"
                report.append(candidate)
                continue
            graph[source_id].add(dependency)
            blocking[source_id].append(dependency)
            candidate["resolved_as"] = "blocking_dependencies"
            candidate["reason"] = "proposed programme prerequisite"
            report.append(candidate)
    return (
        {key: sorted(value) for key, value in blocking.items()},
        {key: sorted(value) for key, value in related.items()},
        {key: value for key, value in conversions.items()},
        report,
    )


DEPENDENCY_SEMANTIC_OVERRIDES: dict[str, dict[str, list[str]]] = {
    # These records are evidence/policy inputs for the scope decision. They
    # must not make the scope decision appear ready by bypassing the ordinary
    # blocker graph.
    "ISSUE-0070": {
        "blocking_dependencies": [],
        "required_inputs": ["ISSUE-0008", "ISSUE-0032", "ISSUE-0060", "ISSUE-0066"],
    },
}


def _semantic_dependency_fields(
    issue_id: str,
    resolved_blocking: list[str],
    resolved_related: list[str],
) -> dict[str, list[str]]:
    override = DEPENDENCY_SEMANTIC_OVERRIDES.get(issue_id, {})
    blocking = sorted(set(override.get("blocking_dependencies", resolved_blocking)))
    required_inputs = sorted(set(override.get("required_inputs", [])))
    related = sorted(set(resolved_related) - set(blocking) - set(required_inputs))
    return {
        "blocking_dependencies": blocking,
        "required_inputs": required_inputs,
        "related_issues": related,
    }


def build_registry(root: Path, *, baseline: str | None = None) -> dict[str, Any]:
    package = load_package_registry(root)
    open_records = parse_open_ledger(root / OPEN_LEDGER)
    closed_records = parse_closed_index(root / CLOSED_LEDGER)
    package_rows: list[tuple[str, str, dict[str, Any]]] = []
    for row in package.get("current_open_issues", []):
        package_rows.append((str(row["issue_id"]), "current", row))
    for row in package.get("proposed_new_issues", []):
        package_rows.append((str(row["issue_id"]), "proposed", row))
    package_ids = {issue_id for issue_id, _, _ in package_rows}
    closed_ids = set(closed_records)
    open_ids = set(open_records)
    blocking, related, conversions, dependency_report = _dependency_resolution(
        package_rows, package_ids, closed_ids, open_ids
    )
    records: list[dict[str, Any]] = []
    source_file = {
        "current": "ETF_AI_Cockpit_Current_Open_Issues_Audit.csv",
        "proposed": "ETF_AI_Cockpit_New_Issues.csv",
    }
    for issue_id, source_kind, row in sorted(package_rows, key=lambda item: item[0]):
        is_closed_reconciled = source_kind == "current" and issue_id in closed_ids
        classification = (
            "current_closed_reconciled"
            if source_kind == "current" and is_closed_reconciled
            else "current_open_retained"
            if source_kind == "current"
            else "proposed_new"
        )
        ledger_state = "closed" if source_kind == "current" and is_closed_reconciled else "open"
        owner = owner_for(row, source_kind)
        source_title = str(row.get("title", "")).strip()
        canonical_title = source_title
        if source_kind == "current":
            canonical_title = (
                open_records.get(issue_id, {}).get("title")
                or closed_records.get(issue_id, {}).get("title")
                or source_title
            )
        dependency_fields = _semantic_dependency_fields(
            issue_id,
            blocking.get(issue_id, []),
            related.get(issue_id, []),
        )
        record = {
            "canonical_id": issue_id,
            "source_record_id": issue_id,
            "source_kind": source_kind,
            "source_file": source_file[source_kind],
            "classification": classification,
            "title": canonical_title,
            "source_title": source_title,
            "ledger_state": ledger_state,
            "package_status": str(row.get("status", "")).strip(),
            "programme_status": programme_status(source_kind, row, ledger_state),
            "priority": str(row.get("priority", "")).strip(),
            "owner": owner,
            "phase": phase_for(issue_id, owner),
            "epic": str(row.get("epic", "")).strip(),
            "evidence_grade": str(row.get("evidence_grade", "")).strip(),
            "dependency_candidates": parse_issue_refs(row.get("dependencies", "")),
            **dependency_fields,
            "dependency_conversions": conversions.get(issue_id, []),
        }
        for field in (
            "current_gap",
            "required_change",
            "why",
            "implementation",
            "data_and_dependencies",
            "acceptance_criteria",
            "tests_required",
            "ui_requirement",
            "security_and_audit",
            "free_no_quota_policy",
        ):
            if field in row:
                record[field] = str(row.get(field, "")).strip()
        records.append(record)

    # Downstream links are derived from all prerequisite kinds. They are
    # generated reverse links, not hand-maintained sequencing metadata.
    downstream: dict[str, set[str]] = defaultdict(set)
    for record in records:
        source_id = str(record["canonical_id"])
        for dependency_field in ("blocking_dependencies", "required_inputs"):
            for dependency in record.get(dependency_field, []):
                downstream[str(dependency)].add(source_id)
    for record in records:
        record["downstream_issues"] = sorted(downstream.get(str(record["canonical_id"]), set()))

    manifest = read_manifest(root)
    package_sha = manifest.get("ETF_AI_Cockpit_Full_Research_and_Issue_Package.zip", "")
    open_digest = sha256_file(root / OPEN_LEDGER)
    closed_digest = sha256_file(root / CLOSED_LEDGER)
    package_digest = sha256_file(root / PACKAGE_JSON)
    local_only_ids = sorted((open_ids | closed_ids) - package_ids)
    local_only_records: list[dict[str, Any]] = []
    for issue_id in local_only_ids:
        if issue_id in open_records:
            source = open_records[issue_id]
            local_only_records.append(
                {
                    "canonical_id": issue_id,
                    "title": source["title"],
                    "ledger_state": "open",
                    "classification": "local_only_current",
                    "reason": "present in latest open ledger but absent from the older package snapshot",
                    "priority": source.get("priority", ""),
                }
            )
        else:
            source = closed_records[issue_id]
            local_only_records.append(
                {
                    "canonical_id": issue_id,
                    "title": source["title"],
                    "ledger_state": "closed",
                    "classification": "local_only_closed",
                    "reason": "closed in the latest ledger after the package snapshot or reconciled from a stale open record",
                    "priority": "",
                }
            )
    registry = {
        "schema_version": "2.0",
        "source_of_truth": {
            "repository": package.get("repository", "Thor2709/etf_ai_cockpit"),
            "baseline_commit": baseline or baseline_sha(root),
            "package_reviewed_commit": package.get("reviewed_commit", ""),
            "package_sha256": package_sha,
            "package_registry_sha256": package_digest,
            "source_manifest_sha256": sha256_file(root / SOURCE_MANIFEST),
            "open_ledger_sha256": open_digest,
            "closed_ledger_sha256": closed_digest,
        },
        "policy": {
            "local_first": True,
            "optional_providers_non_blocking": True,
            "execution_allowed": False,
            "adjusted_prices_required_for_returns": True,
            "github_apply_requires_reviewed_checksum": True,
        },
        "counts": {
            "package_current_records": len(package.get("current_open_issues", [])),
            "package_proposed_records": len(package.get("proposed_new_issues", [])),
            "package_records": len(records),
            "current_open_ledger_records": len(open_records),
            "closed_index_records": len(closed_records),
            "package_current_open_records": sum(
                record["source_kind"] == "current" and record["ledger_state"] == "open" for record in records
            ),
            "package_current_closed_records": sum(
                record["source_kind"] == "current" and record["ledger_state"] == "closed" for record in records
            ),
            "canonical_open_package_records": sum(record["ledger_state"] == "open" for record in records),
            "canonical_closed_package_records": sum(record["ledger_state"] == "closed" for record in records),
            "local_only_records": len(local_only_records),
        },
        "classification_enum": sorted(CLASSIFICATIONS),
        "programme_status_enum": sorted(PROGRAMME_STATUSES),
        "records": records,
        "local_only_records": local_only_records,
        "dependency_reconciliation": dependency_report,
        "roadmap_phases": [
            {key: value for key, value in phase.items() if key != "ids"}
            for phase in PHASES
        ],
    }
    return registry


def deterministic_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(deterministic_json(value))


def validate_registry(registry: dict[str, Any], *, open_ids: set[str], closed_ids: set[str]) -> list[str]:
    errors: list[str] = []
    records = registry.get("records")
    if not isinstance(records, list):
        return ["records must be a list"]
    ids = [str(record.get("canonical_id", "")) for record in records if isinstance(record, dict)]
    if len(ids) != len(set(ids)):
        errors.append("canonical IDs are not unique")
    if len(ids) != 159:
        errors.append(f"expected 159 package records, found {len(ids)}")
    package_current_ids = {
        str(record.get("canonical_id"))
        for record in records
        if record.get("source_kind") == "current"
    }
    package_current_open_ids = {
        str(record.get("canonical_id"))
        for record in records
        if record.get("source_kind") == "current" and record.get("ledger_state") == "open"
    }
    if package_current_open_ids != (open_ids & package_current_ids):
        errors.append("current package/open ledger IDs disagree")
    expected_local_only = (open_ids | closed_ids) - package_current_ids
    actual_local_only = {
        str(record.get("canonical_id")) for record in registry.get("local_only_records", [])
    }
    if actual_local_only != expected_local_only:
        errors.append("latest ledger records absent from package are not reconciled")
    for record in records:
        if not isinstance(record, dict):
            errors.append("record is not an object")
            continue
        issue_id = str(record.get("canonical_id", ""))
        if not re.fullmatch(r"(?:ISSUE|UPDATEV2)-\d{4}", issue_id):
            errors.append(f"invalid canonical ID: {issue_id}")
        if record.get("classification") not in CLASSIFICATIONS:
            errors.append(f"{issue_id}: invalid classification")
        if record.get("ledger_state") not in LEDGER_STATES:
            errors.append(f"{issue_id}: invalid ledger state")
        if record.get("programme_status") not in PROGRAMME_STATUSES:
            errors.append(f"{issue_id}: invalid programme status")
        if record.get("priority") not in PRIORITIES:
            errors.append(f"{issue_id}: invalid priority {record.get('priority')!r}")
        if not str(record.get("owner", "")).strip():
            errors.append(f"{issue_id}: missing owner")
        blocking = record.get("blocking_dependencies", [])
        required_inputs = record.get("required_inputs", [])
        related = record.get("related_issues", [])
        downstream = record.get("downstream_issues", [])
        if not all(isinstance(value, list) for value in (blocking, required_inputs, related, downstream)):
            errors.append(f"{issue_id}: dependency fields must be lists")
        if issue_id in blocking or issue_id in required_inputs or issue_id in related or issue_id in downstream:
            errors.append(f"{issue_id}: self-reference")
        for dependency in [*blocking, *required_inputs, *related, *downstream]:
            if dependency not in set(ids) | closed_ids:
                errors.append(f"{issue_id}: unresolved dependency {dependency}")

    expected_downstream: dict[str, set[str]] = defaultdict(set)
    for record in records:
        source_id = str(record.get("canonical_id"))
        for field in ("blocking_dependencies", "required_inputs"):
            for dependency in record.get(field, []):
                expected_downstream[str(dependency)].add(source_id)
    for record in records:
        issue_id = str(record.get("canonical_id"))
        actual = sorted(str(value) for value in record.get("downstream_issues", []))
        expected = sorted(expected_downstream.get(issue_id, set()))
        if actual != expected:
            errors.append(f"{issue_id}: downstream links are not generated reverse dependencies")

    graph = {
        str(record.get("canonical_id")): set(record.get("blocking_dependencies", []))
        for record in records
        if isinstance(record, dict)
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            errors.append("blocking dependency cycle: " + " -> ".join(stack + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, set()):
            if dependency in graph:
                visit(dependency, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node, [])
    source_mapping_ids = [str(record.get("source_record_id")) for record in records]
    if len(source_mapping_ids) != len(set(source_mapping_ids)):
        errors.append("source-to-canonical mapping is not one-to-one")
    if package_current_ids & (open_ids & closed_ids):
        errors.append("current issue appears in both open and closed ledgers")
    return errors


def records_by_phase(registry: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in registry.get("records", []):
        result[str(record["phase"])].append(record)
    for records in result.values():
        records.sort(key=lambda record: str(record["canonical_id"]))
    return dict(result)


def ready_records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    records = {str(record["canonical_id"]): record for record in registry.get("records", [])}
    closed_ids = {
        issue_id
        for issue_id, record in records.items()
        if record.get("ledger_state") == "closed"
    }
    ready: list[dict[str, Any]] = []
    for record in records.values():
        if record.get("ledger_state") == "closed":
            continue
        if record.get("programme_status") not in {"planned", "ready"}:
            continue
        dependencies = record.get("blocking_dependencies", [])
        if all(
            dependency in closed_ids
            or records.get(dependency, {}).get("programme_status") in {
                "implemented",
                "implemented_initially",
                "integrated",
                "hardening_required",
                "closed",
            }
            for dependency in dependencies
        ):
            ready.append(record)
    return sorted(ready, key=lambda record: (str(record.get("priority")), str(record["canonical_id"])))


__all__ = [
    "CLOSED_LEDGER",
    "CLASSIFICATIONS",
    "OPEN_LEDGER",
    "PACKAGE_JSON",
    "PHASES",
    "PROGRAMME_ROOT",
    "PROGRAMME_STATUSES",
    "REGISTRY_PATH",
    "STATUS_PATH",
    "PROGRESS_PATH",
    "RECONCILIATION_ROOT",
    "build_registry",
    "deterministic_json",
    "load_package_registry",
    "parse_closed_index",
    "parse_open_ledger",
    "ready_records",
    "records_by_phase",
    "sha256_file",
    "validate_registry",
    "write_json",
]
