"""Shared parsing and deterministic modelling for the completion programme."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from copy import deepcopy
from collections import defaultdict
from datetime import date
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
    {
        "current_open_retained",
        "current_closed_reconciled",
        "local_only_current",
        "local_only_closed",
        "proposed_new",
    }
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
CONTROL_ALLOWED_TRANSITIONS = {
    "planned": frozenset({"ready", "in_progress", "research_only", "rejected", "deferred"}),
    "ready": frozenset({"in_progress"}),
    "in_progress": frozenset({"implemented", "implemented_initially"}),
    "implemented": frozenset({"hardening_required", "integrated"}),
    "implemented_initially": frozenset({"hardening_required", "integrated"}),
    "hardening_required": frozenset({"integrated"}),
    "integrated": frozenset({"closed"}),
    "blocked": frozenset({"planned", "ready"}),
}
CONTROL_STATUS_ORDER = {
    "planned": 10,
    "ready": 20,
    "in_progress": 30,
    "implemented": 40,
    "implemented_initially": 40,
    "hardening_required": 50,
    "integrated": 60,
    "closed": 70,
}
CONTROL_HIGH_STATUSES = frozenset(
    {"implemented", "implemented_initially", "hardening_required", "integrated", "closed"}
)
CONTROL_STATE_PATH = Path("issues/programme_control_state.json")
STATUS_GUARD_MANIFEST = Path(".github/status-transition-guard-manifest.json")
PACKAGE_JSON = Path("docs/product-completion/sources/2026-07-15/ETF_AI_Cockpit_Master_Issue_Registry.json")
SOURCE_MANIFEST = Path("docs/product-completion/sources/2026-07-15/SOURCE_MANIFEST.sha256")
FINAL_RELEASE_SOURCE = Path(
    "docs/product-completion/sources/2026-07-21/"
    "ETF_AI_Cockpit_Final_Release_Implementation_Spec_2026-07-21.md"
)
FINAL_RELEASE_MANIFEST = FINAL_RELEASE_SOURCE.parent / "SOURCE_MANIFEST.sha256"
FINAL_RELEASE_SPEC_SHA256 = "7a1d122e0bdbcb68dcd2b202a6f628f33718b2b9ae81cc2305649a7016d95810"
FINAL_RELEASE_VERIFIED_DATE = "2026-07-21"
FINAL_RELEASE_AUDITED_COMMIT = "452d44034197cd5d837c1854603eea030e02acf6"
EDGE_EVIDENCE_STATES = frozenset({"unresolved", "complete", "partial_interface", "waived"})
FINAL_RELEASE_OPEN_BEGIN = "<!-- BEGIN GENERATED FINAL RELEASE ISSUES -->"
FINAL_RELEASE_OPEN_END = "<!-- END GENERATED FINAL RELEASE ISSUES -->"
OPEN_LEDGER = Path("issues/open.md")
CLOSED_LEDGER = Path("issues/closed.md")
REGISTRY_PATH = Path("issues/issue_registry.json")
PROGRAMME_ROOT = Path("docs/product-completion")
STATUS_PATH = PROGRAMME_ROOT / "CURRENT_STATUS.json"
PROGRESS_PATH = PROGRAMME_ROOT / "PROGRESS.md"
RECONCILIATION_ROOT = PROGRAMME_ROOT / "reconciliation"

def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_text_bytes(payload: bytes) -> bytes:
    """Return text bytes with platform line endings represented as LF."""
    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def sha256_text_file(path: Path) -> str:
    """Hash a UTF-8 text file independently of its checkout line endings."""
    return sha256_bytes(canonical_text_bytes(path.read_bytes()))


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


def parse_issue_refs_expanded(value: object) -> list[str]:
    """Parse issue references and expand inclusive ISSUE ranges."""

    text = str(value)
    result = set(parse_issue_refs(text))
    range_re = re.compile(
        r"ISSUE-(\d{4})`?\s*[–-]\s*`?ISSUE-(\d{4})"
    )
    for match in range_re.finditer(text):
        start, end = (int(value) for value in match.groups())
        if start <= end:
            result.update(f"ISSUE-{number:04d}" for number in range(start, end + 1))
    return sorted(result)


def _final_release_source(root: Path) -> tuple[str, str]:
    path = root / FINAL_RELEASE_SOURCE
    digest = sha256_file(path)
    if digest != FINAL_RELEASE_SPEC_SHA256:
        raise ValueError(
            f"final-release source checksum mismatch: expected {FINAL_RELEASE_SPEC_SHA256}, found {digest}"
        )
    manifest = read_manifest_file(root / FINAL_RELEASE_MANIFEST)
    if manifest.get(FINAL_RELEASE_SOURCE.name) != digest:
        raise ValueError("final-release source manifest does not match the canonical specification")
    return path.read_text(encoding="utf-8"), digest


def read_manifest_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        digest, member, *_ = line.split()
        result[member] = digest.lower()
    return result


def _field_from_block(block: str, name: str) -> str:
    match = re.search(rf"(?m)^- {re.escape(name)}:\s*(.+?)\s*$", block)
    return match.group(1).strip().strip("`") if match else ""


def _compact_metadata(block: str) -> dict[str, str]:
    match = re.search(r"(?m)^\*\*Canonical metadata:\*\*\s*(.+?)\s*$", block)
    if not match:
        return {}
    value = match.group(1)
    result: dict[str, str] = {}
    priority = re.match(r"\s*(P0(?:/P1)?|P1(?:/P2)?|P2|P3)\s*;", value)
    if priority:
        result["Priority"] = priority.group(1)
    patterns = {
        "Owner": r"\bowner\s+`([^`]+)`",
        "Phase": r"\bphase\s+`([^`]+)`",
        "Blocking dependencies": r"\bdepends on\s+(.+?)(?:;\s*execution\b|\.$)",
    }
    for key, pattern in patterns.items():
        found = re.search(pattern, value)
        if found:
            result[key] = found.group(1).strip()
    return result


def _acceptance_criteria(block: str) -> list[str]:
    match = re.search(
        r"(?ms)^\*\*Acceptance criteria\*\*\s*(.+?)(?=^\*\*[^\n]+\*\*|\Z)",
        block,
    )
    if not match:
        return []
    return [
        item.strip()
        for item in re.findall(r"(?m)^- \[[ xX]\]\s+(.+?)\s*$", match.group(1))
        if item.strip()
    ]


def parse_final_release_new_issues(text: str) -> list[dict[str, Any]]:
    part = text.split("## Part VIII — Proposed new canonical issues", 1)[1].split(
        "## Part IX — Dependency and implementation sequence", 1
    )[0]
    headings = list(re.finditer(r"(?m)^#### `(ISSUE-\d{4})` — (.+?)\s*$", part))
    records: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(part)
        block = part[heading.start():end].strip() + "\n"
        compact = _compact_metadata(block)
        metadata = {
            name: _field_from_block(block, name) or compact.get(name, "")
            for name in ("Classification", "Ledger state", "Programme status", "Priority", "Owner", "Phase")
        }
        dependencies = parse_issue_refs_expanded(
            _field_from_block(block, "Blocking dependencies")
            or compact.get("Blocking dependencies", "")
        )
        records.append(
            {
                "issue_id": heading.group(1),
                "title": heading.group(2).strip(),
                "classification": metadata["Classification"] or "proposed_new",
                "ledger_state": metadata["Ledger state"] or "open",
                "status": metadata["Programme status"] or "planned",
                "priority": metadata["Priority"] or "P0",
                "owner": metadata["Owner"] or "programme-governance",
                "phase": metadata["Phase"] or "phase-01-governance-scope",
                "dependencies": dependencies,
                "acceptance_criteria": _acceptance_criteria(block),
                "contract_markdown": block,
                "source_heading": heading.group(0),
            }
        )
    actual = [record["issue_id"] for record in records]
    if not actual or len(actual) != len(set(actual)):
        raise ValueError("final-release issue intake must contain unique canonical issue headings")
    return records


def render_open_ledger_with_final_release(root: Path) -> bytes:
    """Return the open ledger with the source-derived final-release issue block."""

    source, _digest = _final_release_source(root)
    records = parse_final_release_new_issues(source)
    lines = [FINAL_RELEASE_OPEN_BEGIN, "", "# Final-release adopted issues", ""]
    for record in records:
        dependencies = ", ".join(f"`{value}`" for value in record["dependencies"]) or "None"
        lines.extend(
            [
                f"## {record['issue_id']} - {record['title']}",
                "",
                "**Status:** Open — planned",
                f"**Priority:** {record['priority']}",
                f"**Owner:** {record['owner']}",
                f"**Phase:** {record['phase']}",
                f"**Blocking dependencies:** {dependencies}",
                "**Execution allowed:** false",
                "",
                f"Canonical contract: `{FINAL_RELEASE_SOURCE.as_posix()}` ({record['source_heading']}).",
                "",
            ]
        )
    lines.append(FINAL_RELEASE_OPEN_END)
    block = "\n".join(lines)
    path = root / OPEN_LEDGER
    current = path.read_bytes().decode("utf-8")
    pattern = re.compile(
        re.escape(FINAL_RELEASE_OPEN_BEGIN) + r".*?" + re.escape(FINAL_RELEASE_OPEN_END),
        re.DOTALL,
    )
    if pattern.search(current):
        rendered = pattern.sub(block, current)
    else:
        rendered = current.rstrip("\r\n") + "\n\n" + block + "\n"
    return rendered.rstrip("\r\n").encode("utf-8") + b"\n"


def parse_final_release_amendments(text: str) -> dict[str, list[dict[str, str]]]:
    part = text.split("## Part VII — Amend existing canonical issues", 1)[1].split(
        "## Part VIII — Proposed new canonical issues", 1
    )[0]
    headings = list(re.finditer(r"(?m)^#### (?:AMEND|USER-REQUIREMENTS DELTA) .+$", part))
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(part)
        block = part[heading.start():end].strip() + "\n"
        title = heading.group(0).removeprefix("#### ")
        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        for issue_id in parse_issue_refs_expanded(heading.group(0)):
            result[issue_id].append(
                {
                    "heading": title,
                    "source_reference": f"{FINAL_RELEASE_SOURCE.as_posix()}#{slug}",
                    "contract_markdown": block,
                }
            )
    return dict(result)


def parse_release_acceptance_matrix(text: str) -> list[dict[str, str]]:
    part = text.split("## Part X — Shared release-blocking acceptance matrix", 1)[1].split(
        "### Common definition of done", 1
    )[0]
    rows: list[dict[str, str]] = []
    for match in re.finditer(r"(?m)^\| (T-\d{2}) \| (.+?) \| (.+?) \|$", part):
        rows.append({"id": match.group(1), "test": match.group(2), "pass_condition": match.group(3)})
    if [row["id"] for row in rows] != [f"T-{number:02d}" for number in range(1, 56)]:
        raise ValueError("final-release acceptance matrix must contain continuous T-01–T-55")
    return rows


def load_control_state(root: Path) -> dict[str, Any]:
    path = root / CONTROL_STATE_PATH
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValueError(f"unsupported canonical control-state schema: {path}")
    if not isinstance(value.get("metadata"), dict) or not isinstance(value.get("records"), dict):
        raise ValueError("canonical control state requires object metadata and records")
    baseline = value["metadata"].get("generation_base_commit")
    if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise ValueError("canonical control generation base must be a full lowercase Git SHA")
    phases = value.get("phase_definitions")
    if not isinstance(phases, list) or not phases:
        raise ValueError("canonical control state requires phase definitions")
    phase_ids = [phase.get("phase") for phase in phases if isinstance(phase, dict)]
    if len(phase_ids) != len(phases) or len(phase_ids) != len(set(phase_ids)):
        raise ValueError("canonical control phase definitions must be unique objects")
    return value


def verify_generation_base(root: Path, control: dict[str, Any] | None = None) -> None:
    """Validate generation metadata without pinning generation to moving main.

    ``generation_base_commit`` is retained as historical/projection metadata.
    It must be a real commit reachable from the configured ref, but the ref may
    advance after any successful merge without making unrelated projections
    stale.
    """
    value = control or load_control_state(root)
    metadata = value["metadata"]
    expected = str(metadata["generation_base_commit"])
    ref = str(metadata.get("generation_base_ref", "origin/main"))
    try:
        subprocess.check_output(
            ["git", "merge-base", "--is-ancestor", expected, ref],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(
            f"canonical generation base {expected} is not reachable from {ref}"
        ) from exc


def validate_control_authority(
    root: Path,
    control: dict[str, Any],
    *,
    allowed_dependency_edge_update: tuple[str, str] | Iterable[tuple[str, str]] | None = None,
) -> None:
    """Reject unreviewed manual control edits relative to authoritative origin."""
    try:
        payload = subprocess.check_output(
            ["git", "show", f"origin/main:{CONTROL_STATE_PATH.as_posix()}"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        metadata = control.get("metadata", {})
        if metadata.get("bootstrap") is not True or not str(metadata.get("bootstrap_reason", "")).strip():
            raise ValueError("control state has no authoritative origin predecessor and is not an explicit bootstrap")
        return
    prior = json.loads(payload.decode("utf-8"))
    prior_top_level = {
        key: value for key, value in prior.items() if key not in {"metadata", "records"}
    }
    current_top_level = {
        key: value for key, value in control.items() if key not in {"metadata", "records"}
    }
    if prior_top_level != current_top_level:
        raise ValueError("control top-level fields changed without an authorised migration")
    if prior.get("schema_version") != control.get("schema_version"):
        raise ValueError("control schema changed without an authorised migration")
    if prior.get("phase_definitions") != control.get("phase_definitions"):
        raise ValueError("control phase definitions changed without an authorised handoff")
    prior_metadata = prior.get("metadata")
    current_metadata = control.get("metadata")
    if not isinstance(prior_metadata, dict) or not isinstance(current_metadata, dict):
        raise ValueError("control metadata must remain an object")
    expected_metadata = deepcopy(prior_metadata)
    generation_base = current_metadata.get("generation_base_commit")
    if not isinstance(generation_base, str) or not re.fullmatch(r"[0-9a-f]{40}", generation_base):
        raise ValueError("control generation base must be a full lowercase Git SHA")
    expected_metadata["generation_base_commit"] = generation_base
    expected_metadata["generation_base_ref"] = "origin/main"
    expected_metadata["bootstrap"] = False
    expected_metadata["bootstrap_reason"] = ""
    if current_metadata != expected_metadata:
        raise ValueError("control metadata changed outside the generation-base refresh allowlist")
    prior_records = prior.get("records", {})
    current_records = control.get("records", {})
    added_issue_ids = set(current_records) - set(prior_records)
    removed_issue_ids = set(prior_records) - set(current_records)
    if removed_issue_ids or (
        added_issue_ids and added_issue_ids != _authorised_registry_additions(root)
    ):
        raise ValueError("control state issue IDs do not exactly match the authorised registry migration")
    changed_issue_ids: list[str] = []
    for issue_id in sorted(set(current_records) & set(prior_records)):
        previous = prior_records[issue_id]
        current = current_records[issue_id]
        if previous == current:
            continue
        changed_issue_ids.append(issue_id)
        history = current.get("transition_history")
        prior_history = previous.get("transition_history", [])
        if (
            not isinstance(history, list)
            or not isinstance(prior_history, list)
            or history[: len(prior_history)] != prior_history
            or len(history) == len(prior_history)
        ):
            raise ValueError(f"{issue_id}: control change lacks transition history")
        expected = deepcopy(previous)
        expected_history = expected.setdefault("transition_history", [])
        if not isinstance(expected_history, list):
            raise ValueError(f"{issue_id}: authoritative transition history is invalid")
        for event in history[len(prior_history) :]:
            if not isinstance(event, dict):
                raise ValueError(f"{issue_id}: transition history does not match authoritative prior state")
            edge_only = event.get("event_type") == "dependency_edge_update"
            if edge_only:
                if event.get("from") is not None or event.get("to") is not None:
                    raise ValueError(f"{issue_id}: dependency-edge update changed authoritative status")
            elif event.get("from") != expected.get("programme_status"):
                raise ValueError(f"{issue_id}: transition history does not match authoritative prior state")
            validate_control_transition_event(issue_id, expected, event)
            expected_history.append(event)
            expected["verified_commit"] = event.get("verified_commit")
            expected["verified_date"] = event.get("reviewed_date")
            if not edge_only:
                expected["programme_status"] = event["to"]
                expected["status_transition"] = {
                    "from": event["from"],
                    "to": event["to"],
                    "review_reference": event["review_reference"],
                }
                acceptance = expected.setdefault("acceptance_evidence", [])
                if not isinstance(acceptance, list):
                    raise ValueError(f"{issue_id}: authoritative acceptance evidence is invalid")
                acceptance.append({
                    "status": event["to"],
                    "evidence_references": event["evidence_references"],
                    "review_reference": event["review_reference"],
                    "reviewer": event.get("reviewer"),
                    "reviewed_date": event.get("reviewed_date"),
                })
            edge_change = event.get("dependency_edge")
            if edge_change is not None:
                if not isinstance(edge_change, dict) or not str(edge_change.get("dependency", "")):
                    raise ValueError(f"{issue_id}: transition dependency edge is invalid")
                edges = expected.get("dependency_edge_evidence")
                dependency = str(edge_change["dependency"])
                if not isinstance(edges, dict) or dependency not in edges:
                    raise ValueError(f"{issue_id}: transition changes a non-declared dependency edge")
                edges[dependency] = edge_change.get("evidence")
        if expected != current:
            new_events = history[len(prior_history) :]
            kind = (
                "dependency-edge update"
                if all(event.get("event_type") == "dependency_edge_update" for event in new_events)
                else "transition"
            )
            raise ValueError(f"{issue_id}: control change contains fields outside the reviewed {kind}")
    if allowed_dependency_edge_update is not None:
        if (
            isinstance(allowed_dependency_edge_update, tuple)
            and len(allowed_dependency_edge_update) == 2
            and all(isinstance(value, str) for value in allowed_dependency_edge_update)
        ):
            allowed_edges = {
                (str(allowed_dependency_edge_update[0]), str(allowed_dependency_edge_update[1]))
            }
        else:
            allowed_edges = {
                (str(issue_id), str(dependency_id))
                for issue_id, dependency_id in allowed_dependency_edge_update
            }
        if set(changed_issue_ids) != {issue for issue, _ in allowed_edges}:
            raise ValueError(
                "dependency-edge manifest does not match changed control records"
            )
        actual_edges: set[tuple[str, str]] = set()
        for issue_id in changed_issue_ids:
            prior_count = len(prior_records[issue_id].get("transition_history", []))
            for event in current_records[issue_id]["transition_history"][prior_count:]:
                edge_change = event.get("dependency_edge") if isinstance(event, dict) else None
                if event.get("event_type") != "dependency_edge_update" or not isinstance(edge_change, dict):
                    raise ValueError("dependency-edge manifest encountered a non-edge event")
                actual_edges.add((issue_id, str(edge_change.get("dependency", ""))))
        if actual_edges != allowed_edges:
            raise ValueError("dependency-edge manifest does not match reviewed control events")


def _authorised_registry_additions(root: Path) -> set[str]:
    """Return the exact canonical intake authorised by the reviewed guard manifest."""

    path = root / STATUS_GUARD_MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("canonical control additions require a valid status-transition guard manifest") from exc
    migration = manifest.get("registry_migration") if isinstance(manifest, dict) else None
    if (
        manifest.get("schema_version") != "1.1"
        or not isinstance(migration, dict)
        or migration.get("mode") != "canonical_schema_and_intake"
        or migration.get("generator") != "scripts/generate_issue_registry.py"
        or migration.get("removed_issue_ids") != []
    ):
        raise ValueError("canonical control additions require canonical_schema_and_intake registry migration")
    values = migration.get("added_issue_ids")
    if (
        not isinstance(values, list)
        or not all(isinstance(value, str) and ISSUE_ID_RE.fullmatch(value) for value in values)
        or len(values) != len(set(values))
    ):
        raise ValueError("registry migration added_issue_ids must be unique canonical issue IDs")
    return set(values)


def _persisted_control_extension_ids(root: Path) -> set[str]:
    """Return control extensions already present in the canonical registry."""

    path = root / REGISTRY_PATH
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    records = registry.get("records") if isinstance(registry, dict) else None
    if not isinstance(records, list):
        return set()
    return {
        str(record["canonical_id"])
        for record in records
        if isinstance(record, dict)
        and record.get("source_kind") == "control_extension"
        and isinstance(record.get("canonical_id"), str)
    }


def baseline_sha(root: Path) -> str:
    """Return the reviewed, explicitly refreshed generation base."""
    return str(load_control_state(root)["metadata"]["generation_base_commit"])


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


def phase_for(issue_id: str, owner: str, control_record: dict[str, Any]) -> str:
    controlled = str(control_record.get("phase", "")).strip()
    if controlled:
        return controlled
    owner_to_phase = {
        "frontend-and-api": "phase-08-frontend-api",
        "data-and-evidence": "phase-02-data-policy-identity",
        "analysis-and-validation": "phase-05-returns-risk-portfolio",
        "trading-safety": "phase-07-backtest-paper-execution",
        "platform-and-operations": "phase-01-governance-scope",
    }
    return owner_to_phase.get(owner, "phase-01-governance-scope")


def source_programme_status(source_kind: str, row: dict[str, Any], ledger_state: str) -> str:
    if ledger_state == "closed":
        return "closed"
    if source_kind == "proposed":
        return "planned"
    status = str(row.get("status", "")).lower()
    if "research-only" in status:
        return "research_only"
    if "partial" in status:
        return "in_progress"
    if "implementation complete" in status:
        return "implemented_initially"
    return "planned"


def _validated_control_record(
    issue_id: str,
    control: dict[str, Any],
    *,
    declared_dependencies: Iterable[str],
    source_status: str,
) -> dict[str, Any]:
    value = control.get("records", {}).get(issue_id)
    if not isinstance(value, dict):
        raise ValueError(f"canonical control state is missing {issue_id}")
    status = value.get("programme_status")
    if status not in PROGRAMME_STATUSES:
        raise ValueError(f"{issue_id}: invalid controlled programme status {status!r}")
    transition = value.get("status_transition")
    if not isinstance(transition, dict):
        raise ValueError(f"{issue_id}: controlled status requires a reviewed transition declaration")
    if transition.get("to") != status or transition.get("from") not in PROGRAMME_STATUSES:
        raise ValueError(f"{issue_id}: controlled status transition is not allowlisted")
    if not isinstance(transition.get("review_reference"), str) or not transition["review_reference"].strip():
        raise ValueError(f"{issue_id}: controlled status transition requires review_reference")
    evidence = value.get("dependency_edge_evidence")
    if not isinstance(evidence, dict) or set(evidence) != set(declared_dependencies):
        raise ValueError(f"{issue_id}: control edge evidence must exactly match declared blockers")
    evidence_errors = [
        error
        for dependency, edge in evidence.items()
        for error in _validate_edge_evidence(issue_id, dependency, edge)
    ]
    if evidence_errors:
        raise ValueError("; ".join(evidence_errors))
    acceptance = value.get("acceptance_evidence")
    if not isinstance(acceptance, list) or not all(isinstance(item, dict) for item in acceptance):
        raise ValueError(f"{issue_id}: acceptance_evidence must be a list of objects")
    if transition.get("from") == transition.get("to") and status != source_status:
        # An imported reviewed state is allowed only when it is tied to the
        # immutable initial-import review reference.
        if "canonical import" not in transition["review_reference"]:
            raise ValueError(f"{issue_id}: non-source status lacks an allowlisted transition")
    return value


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
                "candidate_type": (
                    "blocking"
                    if source_kind in {"proposed", "final_release", "control_extension"}
                    else "related"
                ),
            }
            if dependency not in known:
                related[source_id].append(dependency)
                candidate["resolved_as"] = "related_issues"
                candidate["reason"] = "reference is outside the package and closed index"
                report.append(candidate)
                continue
            if source_kind not in {"proposed", "final_release", "control_extension"}:
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
    # Certification is an activation gate for the disabled canary, not a gate
    # for implementing and testing the disabled scaffold itself.
    "ISSUE-0133": {
        "blocking_dependencies": ["ISSUE-0132"],
        "activation_dependencies": ["ISSUE-0152"],
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
    activation_dependencies = sorted(set(override.get("activation_dependencies", [])))
    related = sorted(set(resolved_related) - set(blocking) - set(required_inputs))
    return {
        "blocking_dependencies": blocking,
        "required_inputs": required_inputs,
        "activation_dependencies": activation_dependencies,
        "related_issues": related,
    }


def _capability_lane(issue_id: str, phase: str) -> str:
    number = issue_number(issue_id)
    if issue_id == "ISSUE-0133":
        return "LIVE_CANARY_SCAFFOLD_DISABLED"
    if number is not None and 125 <= number <= 135:
        return "PAPER_BROKER_OPERATIONS"
    if number is not None and 153 <= number <= 158:
        return "FIXED_INCOME_ANALYSIS"
    if number is not None and 159 <= number <= 164:
        return "PORTFOLIO_READ_ONLY"
    if number is not None and 170 <= number <= 172:
        return "FUND_ANALYSIS"
    if number is not None and 165 <= number <= 169:
        return "BULK_SCREENING"
    if "portfolio" in phase:
        return "PORTFOLIO_READ_ONLY"
    return "CORE_ANALYSIS"


def _risk(owner: str, issue_id: str, priority: str) -> dict[str, object]:
    categories: list[str] = []
    if owner in {"trading-safety", "security-and-release"} or issue_id in {"ISSUE-0127", "ISSUE-0167"}:
        categories.append("authority_or_security")
    if issue_id in {"ISSUE-0084", "ISSUE-0127", "ISSUE-0159", "ISSUE-0167"}:
        categories.append("financial_correctness")
    level = "high" if categories else "medium" if priority in {"P0", "P0/P1"} else "normal"
    return {"level": level, "categories": categories}


def _unresolved_edge_evidence(blocking_dependencies: Iterable[str]) -> dict[str, dict[str, object]]:
    return {
        dependency: {
            "schema_version": "1.0",
            "state": "unresolved",
            "evidence_references": [],
            "contract_reference": "",
            "reviewer": "",
            "reviewed_date": "",
        }
        for dependency in sorted(blocking_dependencies)
    }


def _compress_issue_coverage(issue_ids: Iterable[str]) -> str:
    grouped: dict[str, list[int]] = defaultdict(list)
    for issue_id in sorted(set(issue_ids)):
        prefix, number = issue_id.rsplit("-", 1)
        grouped[prefix].append(int(number))
    values: list[str] = []
    for prefix, numbers in sorted(grouped.items()):
        start = previous = numbers[0]
        for number in numbers[1:] + [numbers[-1] + 2]:
            if number == previous + 1:
                previous = number
                continue
            values.append(
                f"{prefix}-{start:04d}"
                if start == previous
                else f"{prefix}-{start:04d}–{prefix}-{previous:04d}"
            )
            start = previous = number
    return ", ".join(values)


def _roadmap_phases(
    records: Iterable[dict[str, Any]], phase_definitions: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    records_by_id: dict[str, list[str]] = defaultdict(list)
    for record in records:
        records_by_id[str(record["phase"])].append(str(record["canonical_id"]))
    result: list[dict[str, Any]] = []
    for phase in sorted(phase_definitions, key=lambda value: int(value["order"])):
        phase_id = str(phase["phase"])
        issue_ids = sorted(records_by_id.get(phase_id, []))
        if not issue_ids:
            continue
        result.append(
            {
                "phase": phase_id,
                "title": str(phase["title"]),
                "issue_range": _compress_issue_coverage(issue_ids),
                "issue_ids": issue_ids,
                "record_count": len(issue_ids),
            }
        )
    return result


def build_registry(
    root: Path, *, baseline: str | None = None, verify_base: bool = True
) -> dict[str, Any]:
    package = load_package_registry(root)
    control = load_control_state(root)
    if verify_base:
        verify_generation_base(root, control)
        validate_control_authority(root, control)
    final_release_text, final_release_digest = _final_release_source(root)
    final_release_rows = parse_final_release_new_issues(final_release_text)
    amendments = parse_final_release_amendments(final_release_text)
    effective_baseline = baseline or str(control["metadata"]["generation_base_commit"])
    if effective_baseline != control["metadata"]["generation_base_commit"]:
        raise ValueError("generation baseline differs from canonical control metadata; refresh control first")
    open_records = parse_open_ledger(root / OPEN_LEDGER)
    closed_records = parse_closed_index(root / CLOSED_LEDGER)
    package_rows: list[tuple[str, str, dict[str, Any]]] = []
    for row in package.get("current_open_issues", []):
        package_rows.append((str(row["issue_id"]), "current", row))
    for row in package.get("proposed_new_issues", []):
        package_rows.append((str(row["issue_id"]), "proposed", row))
    for row in final_release_rows:
        package_rows.append((str(row["issue_id"]), "final_release", row))
    source_package_ids = {issue_id for issue_id, _, _ in package_rows}
    for issue_id in sorted((set(open_records) | set(closed_records)) - source_package_ids):
        if issue_id in open_records:
            source = open_records[issue_id]
            row = {
                "issue_id": issue_id,
                "title": source["title"],
                "status": source.get("status", "Open"),
                "priority": source.get("priority", "") or "P3",
                "dependencies": [
                    value for value in parse_issue_refs(source.get("section", ""))
                    if value != issue_id
                ],
            }
        else:
            source = closed_records[issue_id]
            row = {
                "issue_id": issue_id,
                "title": source["title"],
                "status": source.get("final_state", "Closed"),
                "priority": "P3",
                "dependencies": [],
            }
        package_rows.append((issue_id, "local", row))
    immutable_ids = {issue_id for issue_id, _, _ in package_rows}
    overridden_ids = {
        issue_id
        for issue_id in immutable_ids
        if isinstance(control["records"].get(issue_id), dict)
        and "canonical_definition" in control["records"][issue_id]
    }
    if overridden_ids:
        raise ValueError(
            "control canonical_definition cannot override immutable issue IDs: "
            + ", ".join(sorted(overridden_ids))
        )
    extension_ids = set(control["records"]) - immutable_ids
    if extension_ids:
        persisted_ids = _persisted_control_extension_ids(root) & extension_ids
        new_extension_ids = extension_ids - persisted_ids
        if new_extension_ids and new_extension_ids != _authorised_registry_additions(root):
            raise ValueError("control extension IDs do not exactly match authorised added_issue_ids")
        phase_ids = {str(value["phase"]) for value in control["phase_definitions"]}
        known_ids = immutable_ids | extension_ids
        required_definition_keys = {
            "title", "priority", "owner", "phase", "blocking_dependencies",
            "required_inputs", "activation_dependencies", "related_issues",
            "capability_lane", "release_blocking", "objective", "scope",
            "exclusions", "acceptance_criteria", "validation", "rollback",
        }
        optional_definition_keys = {
            "current_gap", "required_change", "problem", "why", "implementation",
            "data_and_dependencies", "completion_evidence", "rollback_plan",
            "tests_required", "ui_requirement", "security_and_audit",
            "free_no_quota_policy", "contract_markdown",
        }
        for issue_id in sorted(extension_ids):
            control_record = control["records"][issue_id]
            definition = control_record.get("canonical_definition")
            if (
                not isinstance(definition, dict)
                or not required_definition_keys.issubset(definition)
                or set(definition) - required_definition_keys - optional_definition_keys
            ):
                raise ValueError(f"{issue_id}: canonical_definition has unsupported or missing fields")
            if definition["priority"] not in PRIORITIES:
                raise ValueError(f"{issue_id}: canonical_definition has invalid priority")
            if definition["phase"] not in phase_ids:
                raise ValueError(f"{issue_id}: canonical_definition has unknown phase")
            for field in ("title", "owner", "capability_lane", "objective", "rollback"):
                if not isinstance(definition[field], str) or not definition[field].strip():
                    raise ValueError(f"{issue_id}: canonical_definition requires non-blank {field}")
            if not isinstance(definition["release_blocking"], bool):
                raise ValueError(f"{issue_id}: canonical_definition release_blocking must be boolean")
            for field in ("scope", "exclusions"):
                values = definition[field]
                if (
                    not isinstance(values, list)
                    or not all(isinstance(value, str) and value.strip() for value in values)
                    or len(values) != len(set(values))
                ):
                    raise ValueError(f"{issue_id}: canonical_definition {field} must be a unique string list")
            if not isinstance(definition["validation"], dict):
                raise ValueError(f"{issue_id}: canonical_definition validation must be an object")
            for field in (
                "blocking_dependencies", "required_inputs",
                "activation_dependencies", "related_issues",
            ):
                values = definition[field]
                if (
                    not isinstance(values, list)
                    or not all(isinstance(value, str) for value in values)
                    or len(values) != len(set(values))
                ):
                    raise ValueError(f"{issue_id}: canonical_definition {field} must be a unique list")
                if issue_id in values or any(value not in known_ids for value in values):
                    raise ValueError(f"{issue_id}: canonical_definition {field} has unknown or self dependency")
            acceptance = definition["acceptance_criteria"]
            if not isinstance(acceptance, list) or not all(isinstance(value, dict) for value in acceptance):
                raise ValueError(
                    f"{issue_id}: canonical_definition acceptance_criteria must be a list of objects"
                )
            encoded_acceptance = [
                json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                for value in acceptance
            ]
            if len(encoded_acceptance) != len(set(encoded_acceptance)):
                raise ValueError(
                    f"{issue_id}: canonical_definition acceptance_criteria contains duplicates"
                )
            if issue_id in new_extension_ids and control_record.get("programme_status") != "planned":
                raise ValueError(f"{issue_id}: newly added canonical issue must be planned")
            row = dict(definition)
            row["issue_id"] = issue_id
            row["dependencies"] = definition["blocking_dependencies"]
            package_rows.append((issue_id, "control_extension", row))
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
        "final_release": FINAL_RELEASE_SOURCE.as_posix(),
        "local": "issues/open.md and issues/closed.md",
        "control_extension": CONTROL_STATE_PATH.as_posix(),
    }
    for issue_id, source_kind, row in sorted(package_rows, key=lambda item: item[0]):
        is_closed_reconciled = source_kind in {"current", "local"} and issue_id in closed_ids
        classification = (
            "current_closed_reconciled"
            if source_kind == "current" and is_closed_reconciled
            else "current_open_retained"
            if source_kind == "current"
            else "local_only_closed"
            if source_kind == "local" and is_closed_reconciled
            else "local_only_current"
            if source_kind == "local"
            else "proposed_new"
        )
        ledger_state = "closed" if is_closed_reconciled else "open"
        owner = str(row.get("owner", "")).strip() or owner_for(row, source_kind)
        source_title = str(row.get("title", "")).strip()
        canonical_title = source_title
        if source_kind in {"current", "local"}:
            canonical_title = (
                open_records.get(issue_id, {}).get("title")
                or closed_records.get(issue_id, {}).get("title")
                or source_title
            )
        if source_kind == "control_extension":
            dependency_fields = {
                field: sorted(row[field])
                for field in (
                    "blocking_dependencies", "required_inputs",
                    "activation_dependencies", "related_issues",
                )
            }
        else:
            dependency_fields = _semantic_dependency_fields(
                issue_id,
                blocking.get(issue_id, []),
                related.get(issue_id, []),
            )
        source_status = source_programme_status(source_kind, row, ledger_state)
        controlled = _validated_control_record(
            issue_id,
            control,
            declared_dependencies=dependency_fields["blocking_dependencies"],
            source_status=source_status,
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
            "programme_status": controlled["programme_status"],
            "priority": str(row.get("priority", "")).strip(),
            "owner": owner,
            "phase": str(row.get("phase", "")).strip() or phase_for(issue_id, owner, controlled),
            "epic": str(row.get("epic", "")).strip(),
            "evidence_grade": str(row.get("evidence_grade", "")).strip(),
            "dependency_candidates": parse_issue_refs(row.get("dependencies", "")),
            **dependency_fields,
            "dependency_conversions": conversions.get(issue_id, []),
            "normative_amendments": amendments.get(issue_id, []),
        }
        source_fields = (
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
            "contract_markdown",
        )
        if source_kind == "control_extension":
            source_fields += (
                "problem",
                "objective",
                "scope",
                "exclusions",
                "completion_evidence",
                "rollback_plan",
                "validation",
                "rollback",
            )
        for field in source_fields:
            if field in row:
                value = row.get(field)
                record[field] = (
                    value if isinstance(value, (list, dict)) else str(value or "").strip()
                )
        record["dependency_edge_evidence"] = controlled["dependency_edge_evidence"]
        record["provenance"] = {
            "schema_version": "1.0",
            "primary_source": record["source_file"],
            "source_record_id": issue_id,
            "final_release_spec_sha256": final_release_digest,
            "amendment_references": [
                amendment["source_reference"] for amendment in record["normative_amendments"]
            ],
        }
        record["verified_commit"] = controlled["verified_commit"]
        record["verified_date"] = controlled["verified_date"]
        record["acceptance_evidence"] = controlled["acceptance_evidence"]
        record["capability_lane"] = (
            str(row["capability_lane"])
            if source_kind == "control_extension"
            else _capability_lane(issue_id, record["phase"])
        )
        record["release_blocking"] = (
            bool(row["release_blocking"])
            if source_kind == "control_extension"
            else record["programme_status"] not in {"research_only", "rejected", "deferred"}
        )
        record["write_conflict_group"] = owner
        record["risk"] = _risk(owner, issue_id, record["priority"])
        records.append(record)

    # Downstream links are derived from all prerequisite kinds. They are
    # generated reverse links, not hand-maintained sequencing metadata.
    downstream: dict[str, set[str]] = defaultdict(set)
    for record in records:
        source_id = str(record["canonical_id"])
        for dependency_field in ("blocking_dependencies", "required_inputs", "activation_dependencies"):
            for dependency in record.get(dependency_field, []):
                downstream[str(dependency)].add(source_id)
    for record in records:
        record["downstream_issues"] = sorted(downstream.get(str(record["canonical_id"]), set()))

    blocking_graph = {
        str(record["canonical_id"]): set(record["blocking_dependencies"]) for record in records
    }
    for source, dependencies in blocking_graph.items():
        for dependency in dependencies:
            if _would_create_cycle(
                {key: value for key, value in blocking_graph.items() if key != source},
                source,
                dependency,
            ):
                raise ValueError(f"blocking dependency cycle involving {source} and {dependency}")

    manifest = read_manifest(root)
    package_sha = manifest.get("ETF_AI_Cockpit_Full_Research_and_Issue_Package.zip", "")
    open_digest = sha256_text_file(root / OPEN_LEDGER)
    closed_digest = sha256_text_file(root / CLOSED_LEDGER)
    package_digest = sha256_text_file(root / PACKAGE_JSON)
    control_digest = sha256_text_file(root / CONTROL_STATE_PATH)
    local_only_records: list[dict[str, Any]] = []
    registry = {
        "schema_version": "2.0",
        "source_of_truth": {
            "repository": package.get("repository", "Thor2709/etf_ai_cockpit"),
            "baseline_commit": effective_baseline,
            "package_reviewed_commit": package.get("reviewed_commit", ""),
            "package_sha256": package_sha,
            "package_registry_sha256": package_digest,
            "programme_control_state_sha256": control_digest,
            "source_manifest_sha256": sha256_text_file(root / SOURCE_MANIFEST),
            "open_ledger_sha256": open_digest,
            "closed_ledger_sha256": closed_digest,
            "final_release_spec_sha256": final_release_digest,
            "final_release_manifest_sha256": sha256_text_file(root / FINAL_RELEASE_MANIFEST),
            "hash_semantics": {
                "final_release_spec_sha256": "exact bytes; immutable binary fixture",
                "other_text_inputs": "UTF-8 text with CRLF/CR canonicalised to LF",
            },
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
            "final_release_new_records": len(final_release_rows),
            "package_records": len(records),
            "canonical_records": len(records),
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
            "local_only_records": sum(record["source_kind"] == "local" for record in records),
        },
        "classification_enum": sorted(CLASSIFICATIONS),
        "programme_status_enum": sorted(PROGRAMME_STATUSES),
        "records": records,
        "local_only_records": local_only_records,
        "dependency_reconciliation": dependency_report,
        "release_acceptance_matrix": parse_release_acceptance_matrix(final_release_text),
        "core_contracts": sorted(
            set(
                name
                for heading in re.findall(
                    r"(?m)^### (.+?)\s*$",
                    final_release_text.split("## Part XI — Core data contracts", 1)[1].split(
                        "## Part XII", 1
                    )[0],
                )
                for name in re.findall(r"`([^`]+)`", heading)
            )
        ),
        "roadmap_phases": _roadmap_phases(records, control["phase_definitions"]),
    }
    registry["readiness"] = readiness_projection(registry)
    return registry


def deterministic_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(deterministic_json(value))


def _validate_edge_evidence(
    issue_id: str, dependency: str, evidence: object
) -> list[str]:
    prefix = f"{issue_id}->{dependency}"
    if not isinstance(evidence, dict):
        return [f"{prefix}: edge evidence must be an object"]
    errors: list[str] = []
    if evidence.get("schema_version") != "1.0":
        errors.append(f"{prefix}: unsupported edge evidence schema version")
    state = evidence.get("state")
    if state not in EDGE_EVIDENCE_STATES:
        errors.append(f"{prefix}: invalid edge evidence state {state!r}")
        return errors
    references = evidence.get("evidence_references")
    if not isinstance(references, list):
        errors.append(f"{prefix}: evidence_references must be a list")
        references = []
    if state != "unresolved":
        if not references or not all(isinstance(value, str) and value.strip() for value in references):
            errors.append(f"{prefix}: resolved edge requires evidence references")
        for field in ("contract_reference", "reviewer", "reviewed_date"):
            if not isinstance(evidence.get(field), str) or not str(evidence.get(field)).strip():
                errors.append(f"{prefix}: resolved edge requires {field}")
        if evidence.get("reviewed_date") and not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", str(evidence.get("reviewed_date"))
        ):
            errors.append(f"{prefix}: reviewed_date must be YYYY-MM-DD")
    return errors


def _control_is_downgrade(previous: str, proposed: str) -> bool:
    if previous in CONTROL_STATUS_ORDER and proposed in CONTROL_STATUS_ORDER:
        return CONTROL_STATUS_ORDER[proposed] < CONTROL_STATUS_ORDER[previous]
    return previous in CONTROL_HIGH_STATUSES and proposed not in CONTROL_HIGH_STATUSES


def validate_control_transition_event(
    issue_id: str,
    previous_record: dict[str, Any],
    event: dict[str, Any],
) -> None:
    """Validate the canonical reviewed event used by both writer and readback."""
    common_keys = {
        "review_reference",
        "evidence_references",
        "reviewer",
        "reviewed_date",
        "verified_commit",
    }
    if event.get("event_type") == "dependency_edge_update":
        required_keys = common_keys | {"event_type", "dependency_edge"}
        if set(event) != required_keys:
            missing = required_keys - set(event)
            unsupported = set(event) - required_keys
            if missing:
                raise ValueError(f"{issue_id}: dependency-edge update requires {', '.join(sorted(missing))}")
            raise ValueError(
                f"{issue_id}: dependency-edge update has unsupported fields: {', '.join(sorted(unsupported))}"
            )
        edge_only = True
    else:
        required_keys = common_keys | {
            "from",
            "to",
            "allow_downgrade",
        }
        allowed_keys = required_keys | {"dependency_edge"}
        missing = required_keys - set(event)
        if missing:
            raise ValueError(f"{issue_id}: transition requires {', '.join(sorted(missing))}")
        unsupported = set(event) - allowed_keys
        if unsupported:
            raise ValueError(f"{issue_id}: transition event has unsupported fields: {', '.join(sorted(unsupported))}")
        previous = previous_record.get("programme_status")
        source = event.get("from")
        target = event.get("to")
        if source != previous or source not in PROGRAMME_STATUSES:
            raise ValueError(f"{issue_id}: transition source does not match authoritative status")
        if target not in PROGRAMME_STATUSES:
            raise ValueError(f"{issue_id}: transition target is not a programme status")
        allow_downgrade = event.get("allow_downgrade")
        if not isinstance(allow_downgrade, bool):
            raise ValueError(f"{issue_id}: allow_downgrade must be boolean")
        normal = target in CONTROL_ALLOWED_TRANSITIONS.get(str(source), frozenset())
        downgrade = _control_is_downgrade(str(source), str(target))
        if not normal and not (allow_downgrade and downgrade):
            raise ValueError(f"transition is not allowed: {issue_id} {source}->{target}")
        if allow_downgrade and not downgrade:
            raise ValueError(f"{issue_id}: allow_downgrade is valid only for a downgrade")
        edge_only = False
    for field in ("review_reference", "reviewer"):
        if not isinstance(event.get(field), str) or not str(event[field]).strip():
            raise ValueError(f"{issue_id}: transition requires {field}")
    references = event.get("evidence_references")
    if not isinstance(references, list) or not references or not all(
        isinstance(reference, str) and reference.strip() for reference in references
    ):
        raise ValueError(f"{issue_id}: transition requires non-blank evidence references")
    reviewed_date = event.get("reviewed_date")
    if not isinstance(reviewed_date, str):
        raise ValueError(f"{issue_id}: reviewed_date must be YYYY-MM-DD")
    try:
        date.fromisoformat(reviewed_date)
    except ValueError as exc:
        raise ValueError(f"{issue_id}: reviewed_date must be a valid YYYY-MM-DD date") from exc
    verified_commit = event.get("verified_commit")
    if not isinstance(verified_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", verified_commit):
        raise ValueError(f"{issue_id}: verified_commit must be a full lowercase Git SHA")
    edge_change = event.get("dependency_edge")
    if edge_change is None:
        if edge_only:
            raise ValueError(f"{issue_id}: dependency-edge update requires dependency_edge")
        return
    if not isinstance(edge_change, dict) or set(edge_change) != {"dependency", "evidence"}:
        raise ValueError(f"{issue_id}: transition dependency edge is invalid")
    dependency = edge_change.get("dependency")
    declared = previous_record.get("dependency_edge_evidence")
    if not isinstance(dependency, str) or not isinstance(declared, dict) or dependency not in declared:
        raise ValueError(f"{issue_id}: transition changes a non-declared dependency edge")
    edge = edge_change.get("evidence")
    if edge == declared[dependency]:
        raise ValueError(f"{issue_id}: dependency-edge update must change reviewed evidence")
    if edge_only and event.get("verified_commit") == previous_record.get("verified_commit"):
        raise ValueError(f"{issue_id}: dependency-edge update must advance verified_commit")
    errors = _validate_edge_evidence(issue_id, dependency, edge)
    if errors:
        raise ValueError("; ".join(errors))
    if not isinstance(edge, dict) or any(
        edge.get(field) != event.get(event_field)
        for field, event_field in (
            ("evidence_references", "evidence_references"),
            ("reviewer", "reviewer"),
            ("reviewed_date", "reviewed_date"),
        )
    ):
        raise ValueError(f"{issue_id}: dependency-edge review evidence must match the transition")


def validate_registry(registry: dict[str, Any], *, open_ids: set[str], closed_ids: set[str]) -> list[str]:
    errors: list[str] = []
    records = registry.get("records")
    if not isinstance(records, list):
        return ["records must be a list"]
    ids = [str(record.get("canonical_id", "")) for record in records if isinstance(record, dict)]
    if len(ids) != len(set(ids)):
        errors.append("canonical IDs are not unique")
    declared_count = registry.get("counts", {}).get("package_records")
    if declared_count != len(ids):
        errors.append(
            f"source-derived package record count mismatch: declared {declared_count}, found {len(ids)}"
        )
    supported_ids = set(ids)
    if len(supported_ids) != len(ids):
        errors.append("supported canonical IDs are not unique")
    phase_ids = {
        str(phase.get("phase"))
        for phase in registry.get("roadmap_phases", [])
        if isinstance(phase, dict)
    }
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
    if not (open_ids | closed_ids).issubset(set(ids)):
        errors.append("latest ledger records are absent from canonical records")
    if registry.get("local_only_records"):
        errors.append("local ledger records must be folded into canonical records")
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
        if record.get("phase") not in phase_ids:
            errors.append(f"{issue_id}: missing roadmap phase")
        blocking = record.get("blocking_dependencies", [])
        required_inputs = record.get("required_inputs", [])
        activation = record.get("activation_dependencies", [])
        related = record.get("related_issues", [])
        downstream = record.get("downstream_issues", [])
        if not all(
            isinstance(value, list)
            for value in (blocking, required_inputs, activation, related, downstream)
        ):
            errors.append(f"{issue_id}: dependency fields must be lists")
            continue
        if (
            issue_id in blocking
            or issue_id in required_inputs
            or issue_id in activation
            or issue_id in related
            or issue_id in downstream
        ):
            errors.append(f"{issue_id}: self-reference")
        for dependency in [*blocking, *required_inputs, *activation, *related, *downstream]:
            if dependency not in set(ids) | closed_ids:
                errors.append(f"{issue_id}: unresolved dependency {dependency}")
        evidence = record.get("dependency_edge_evidence")
        if not isinstance(evidence, dict):
            errors.append(f"{issue_id}: dependency_edge_evidence must be an object")
        else:
            for dependency in sorted(set(evidence) - set(blocking)):
                errors.append(
                    f"{issue_id}: evidence for non-declared blocking edge {dependency}"
                )
            for dependency in sorted(set(blocking) - set(evidence)):
                errors.append(f"{issue_id}: missing evidence state for blocking edge {dependency}")
            for dependency in sorted(set(blocking) & set(evidence)):
                errors.extend(_validate_edge_evidence(issue_id, dependency, evidence[dependency]))
        required_types = {
            "provenance": dict,
            "verified_commit": str,
            "verified_date": str,
            "acceptance_evidence": list,
            "capability_lane": str,
            "release_blocking": bool,
            "write_conflict_group": str,
            "risk": dict,
        }
        for field, expected_type in required_types.items():
            value = record.get(field)
            if not isinstance(value, expected_type) or (
                expected_type is str and not value.strip()
            ):
                errors.append(f"{issue_id}: invalid or missing typed field {field}")

    expected_downstream: dict[str, set[str]] = defaultdict(set)
    for record in records:
        source_id = str(record.get("canonical_id"))
        for field in ("blocking_dependencies", "required_inputs", "activation_dependencies"):
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


def readiness_projection(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Project implementation and activation readiness without consulting status labels."""

    records = {str(record["canonical_id"]): record for record in registry.get("records", [])}
    closed_ids = {
        issue_id
        for issue_id, record in records.items()
        if record.get("ledger_state") == "closed"
    }
    closed_ids.update(
        str(record.get("canonical_id"))
        for record in registry.get("local_only_records", [])
        if isinstance(record, dict) and record.get("ledger_state") == "closed"
    )
    decisions: list[dict[str, Any]] = []
    for issue_id, record in sorted(records.items()):
        edges: list[dict[str, object]] = []
        invalid_edge = False
        unresolved_edge = False
        evidence_by_edge = record.get("dependency_edge_evidence", {})
        if not isinstance(evidence_by_edge, dict):
            evidence_by_edge = {}
        for dependency in sorted(record.get("blocking_dependencies", [])):
            evidence = evidence_by_edge.get(dependency, {})
            state = evidence.get("state", "unresolved") if isinstance(evidence, dict) else "unresolved"
            if dependency in closed_ids:
                resolved = True
                reason_code = "DEPENDENCY_LEDGER_CLOSED"
            elif state != "unresolved" and not _validate_edge_evidence(issue_id, dependency, evidence):
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
            edges.append(
                {
                    "dependency_id": dependency,
                    "resolved": resolved,
                    "reason_code": reason_code,
                    "evidence_state": state,
                }
            )

        if record.get("ledger_state") == "closed":
            ready = False
            reason_codes = ["CLOSED_LEDGER_NOT_IMPLEMENTATION_CANDIDATE"]
        elif invalid_edge:
            ready = False
            reason_codes = ["BLOCKED_INVALID_EDGE_EVIDENCE"]
            if unresolved_edge:
                reason_codes.append("BLOCKED_UNRESOLVED_DEPENDENCY")
        elif unresolved_edge:
            ready = False
            reason_codes = ["BLOCKED_UNRESOLVED_DEPENDENCY"]
        else:
            ready = True
            reason_codes = [
                "READY_BLOCKING_EDGES_RESOLVED" if edges else "READY_NO_BLOCKING_DEPENDENCIES"
            ]

        activation_edges: list[dict[str, object]] = []
        for dependency in sorted(record.get("activation_dependencies", [])):
            resolved = dependency in closed_ids
            activation_edges.append(
                {
                    "dependency_id": dependency,
                    "resolved": resolved,
                    "reason_code": (
                        "ACTIVATION_DEPENDENCY_LEDGER_CLOSED"
                        if resolved
                        else "ACTIVATION_EDGE_UNRESOLVED"
                    ),
                }
            )
        activation_ready = all(edge["resolved"] for edge in activation_edges)
        activation_reason_codes = [
            (
                "ACTIVATION_READY_DEPENDENCIES_RESOLVED"
                if activation_edges
                else "ACTIVATION_READY_NO_DEPENDENCIES"
            )
            if activation_ready
            else "ACTIVATION_BLOCKED_UNRESOLVED_DEPENDENCY"
        ]
        decisions.append(
            {
                "issue_id": issue_id,
                "ready": ready,
                "reason_codes": reason_codes,
                "edges": edges,
                "required_inputs": sorted(record.get("required_inputs", [])),
                "activation_ready": activation_ready,
                "activation_reason_codes": activation_reason_codes,
                "activation_edges": activation_edges,
                "execution_allowed": False,
            }
        )
    return decisions


def ready_records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    records = {str(record["canonical_id"]): record for record in registry.get("records", [])}
    ready_ids = {decision["issue_id"] for decision in readiness_projection(registry) if decision["ready"]}
    return sorted(
        (records[issue_id] for issue_id in ready_ids),
        key=lambda record: (str(record.get("priority")), str(record["canonical_id"])),
    )


__all__ = [
    "CLOSED_LEDGER",
    "CLASSIFICATIONS",
    "EDGE_EVIDENCE_STATES",
    "FINAL_RELEASE_SOURCE",
    "OPEN_LEDGER",
    "PACKAGE_JSON",
    "PROGRAMME_ROOT",
    "PROGRAMME_STATUSES",
    "REGISTRY_PATH",
    "STATUS_PATH",
    "PROGRESS_PATH",
    "RECONCILIATION_ROOT",
    "build_registry",
    "canonical_text_bytes",
    "deterministic_json",
    "load_package_registry",
    "parse_closed_index",
    "parse_final_release_new_issues",
    "parse_open_ledger",
    "render_open_ledger_with_final_release",
    "ready_records",
    "readiness_projection",
    "records_by_phase",
    "sha256_file",
    "sha256_text_file",
    "validate_registry",
    "write_json",
]
