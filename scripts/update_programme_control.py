"""Create or update the canonical programme control-state input.

This command is the guarded write path for reviewed status/evidence state.  The
registry remains generated; mutable review decisions live in one versioned
companion input instead of Python constants or generated output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

try:
    from scripts.issue_registry_core import PROGRAMME_STATUSES, _validate_edge_evidence
    from scripts.status_transition_guard import _is_downgrade
except ModuleNotFoundError:
    from issue_registry_core import PROGRAMME_STATUSES, _validate_edge_evidence
    from status_transition_guard import _is_downgrade


CONTROL_PATH = Path("issues/programme_control_state.json")
REGISTRY_PATH = Path("issues/issue_registry.json")
ALLOWED_TRANSITIONS = {
    "planned": {"ready", "in_progress", "research_only", "rejected", "deferred"},
    "ready": {"in_progress"},
    "in_progress": {"implemented", "implemented_initially"},
    "implemented": {"hardening_required", "integrated"},
    "implemented_initially": {"hardening_required", "integrated"},
    "hardening_required": {"integrated"},
    "integrated": {"closed"},
    "blocked": {"planned", "ready"},
}


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _phase_metadata(registry: dict[str, object]) -> list[dict[str, object]]:
    phases = registry.get("roadmap_phases", [])
    return [
        {
            "phase": phase["phase"],
            "title": phase["title"],
            "order": index,
        }
        for index, phase in enumerate(phases, start=1)
        if isinstance(phase, dict)
    ]


def import_registry(root: Path, baseline: str) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise ValueError("--baseline must be a full lowercase Git SHA")
    verified = _git(root, "rev-parse", "origin/main")
    if baseline != verified:
        raise ValueError(f"--baseline {baseline} does not match freshly verified origin/main {verified}")
    registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
    records: dict[str, object] = {}
    source_records = [*registry.get("records", []), *registry.get("local_only_records", [])]
    for record in source_records:
        issue_id = str(record["canonical_id"])
        status = record.get(
            "programme_status",
            "closed" if record.get("ledger_state") == "closed" else "planned",
        )
        records[issue_id] = {
            "programme_status": status,
            "phase": record.get("phase", "phase-01-governance-scope"),
            "acceptance_evidence": record.get("acceptance_evidence", []),
            "dependency_edge_evidence": record.get("dependency_edge_evidence", {}),
            "verified_commit": record.get("verified_commit", baseline),
            "verified_date": record.get("verified_date", "2026-07-21"),
            "status_transition": {
                "from": status,
                "to": status,
                "review_reference": "B00 canonical import from audited programme state",
            },
        }
    return {
        "schema_version": "1.0",
        "metadata": {
            "bootstrap": True,
            "bootstrap_reason": "B00 initial canonical import before origin/main contained this control source",
            "generation_base_commit": baseline,
            "generation_base_ref": "origin/main",
            "verified_date": "2026-07-21",
        },
        "phase_definitions": _phase_metadata(registry),
        "records": records,
    }


def _atomic_write(path: Path, value: dict[str, object]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_transition(
    value: dict[str, object],
    *,
    issue_id: str,
    expected_from: str,
    to_status: str,
    review_reference: str,
    evidence_references: list[str],
    reviewer: str,
    reviewed_date: str,
    verified_commit: str,
    allow_downgrade: bool = False,
    edge_dependency: str | None = None,
    edge_state: str | None = None,
    contract_reference: str | None = None,
) -> dict[str, object]:
    records = value.get("records")
    if not isinstance(records, dict) or not isinstance(records.get(issue_id), dict):
        raise ValueError(f"unknown controlled issue ID: {issue_id}")
    record = records[issue_id]
    current = str(record.get("programme_status", ""))
    if current != expected_from:
        raise ValueError(f"{issue_id}: expected-from {expected_from} does not match current {current}")
    if to_status not in PROGRAMME_STATUSES:
        raise ValueError(f"unknown target programme status: {to_status}")
    normal = to_status in ALLOWED_TRANSITIONS.get(current, set())
    downgrade = _is_downgrade(current, to_status)
    if not normal and not (allow_downgrade and downgrade):
        raise ValueError(f"transition is not allowed: {issue_id} {current}->{to_status}")
    if not review_reference.strip() or not reviewer.strip() or not evidence_references:
        raise ValueError("transition requires review_reference, reviewer and evidence references")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", reviewed_date):
        raise ValueError("reviewed_date must be YYYY-MM-DD")
    if not re.fullmatch(r"[0-9a-f]{40}", verified_commit):
        raise ValueError("verified_commit must be a full lowercase Git SHA")
    if edge_dependency is not None:
        evidence = record.get("dependency_edge_evidence")
        if not isinstance(evidence, dict) or edge_dependency not in evidence:
            raise ValueError(f"{issue_id}: non-declared dependency edge {edge_dependency}")
        edge = {
            "schema_version": "1.0",
            "state": edge_state,
            "evidence_references": evidence_references,
            "contract_reference": contract_reference or "",
            "reviewer": reviewer,
            "reviewed_date": reviewed_date,
        }
        errors = _validate_edge_evidence(issue_id, edge_dependency, edge)
        if errors:
            raise ValueError("; ".join(errors))
        evidence[edge_dependency] = edge
        edge_change = {"dependency": edge_dependency, "evidence": edge}
    else:
        edge_change = None
    event = {
        "from": current,
        "to": to_status,
        "review_reference": review_reference,
        "evidence_references": evidence_references,
        "reviewer": reviewer,
        "reviewed_date": reviewed_date,
        "verified_commit": verified_commit,
        "allow_downgrade": allow_downgrade,
    }
    if edge_change is not None:
        event["dependency_edge"] = edge_change
    history = record.setdefault("transition_history", [])
    if not isinstance(history, list):
        raise ValueError(f"{issue_id}: transition_history must be a list")
    history.append(event)
    record["programme_status"] = to_status
    record["status_transition"] = {
        "from": current,
        "to": to_status,
        "review_reference": review_reference,
    }
    record["verified_commit"] = verified_commit
    record["verified_date"] = reviewed_date
    acceptance = record.setdefault("acceptance_evidence", [])
    if not isinstance(acceptance, list):
        raise ValueError(f"{issue_id}: acceptance_evidence must be a list")
    acceptance.append({
        "status": to_status,
        "evidence_references": evidence_references,
        "review_reference": review_reference,
        "reviewer": reviewer,
        "reviewed_date": reviewed_date,
    })
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--import-registry", action="store_true")
    parser.add_argument("--bootstrap", action="store_true", help="authorise the one-time initial control import")
    parser.add_argument("--baseline", help="freshly verified generation base SHA")
    parser.add_argument("--check-base", action="store_true")
    parser.add_argument("--refresh-base", action="store_true")
    parser.add_argument("--transition")
    parser.add_argument("--expected-from")
    parser.add_argument("--to-status")
    parser.add_argument("--review-reference")
    parser.add_argument("--evidence-reference", action="append", default=[])
    parser.add_argument("--reviewer")
    parser.add_argument("--reviewed-date")
    parser.add_argument("--verified-commit")
    parser.add_argument("--allow-downgrade", action="store_true")
    parser.add_argument("--edge-dependency")
    parser.add_argument("--edge-state")
    parser.add_argument("--contract-reference")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    path = root / CONTROL_PATH
    if args.import_registry:
        if not args.baseline or not args.bootstrap:
            parser.error("--import-registry requires --baseline and explicit --bootstrap")
        try:
            _git(root, "show", f"origin/main:{CONTROL_PATH.as_posix()}")
        except subprocess.CalledProcessError:
            pass
        else:
            raise ValueError("bootstrap import is forbidden after origin/main contains canonical control state")
        value = import_registry(root, args.baseline)
        _atomic_write(path, value)
        print(f"Wrote {path.relative_to(root)}")
        return 0
    if args.check_base:
        value = json.loads(path.read_text(encoding="utf-8"))
        expected = value["metadata"]["generation_base_commit"]
        actual = _git(root, "rev-parse", value["metadata"].get("generation_base_ref", "origin/main"))
        if actual != expected:
            print(f"STALE: control base {expected}, verified ref {actual}")
            return 1
        print(f"FRESH: control base {actual}")
        return 0
    if args.refresh_base:
        if not args.baseline:
            parser.error("--refresh-base requires --baseline")
        actual = _git(root, "rev-parse", "origin/main")
        if args.baseline != actual:
            raise ValueError(f"--baseline {args.baseline} does not match freshly verified origin/main {actual}")
        value = json.loads(path.read_text(encoding="utf-8"))
        metadata = value["metadata"]
        metadata["generation_base_commit"] = actual
        metadata["generation_base_ref"] = "origin/main"
        metadata["bootstrap"] = False
        metadata["bootstrap_reason"] = ""
        _atomic_write(path, value)
        print(f"REFRESHED: generation base {actual}")
        return 0
    if args.transition:
        required = {
            "--expected-from": args.expected_from,
            "--to-status": args.to_status,
            "--review-reference": args.review_reference,
            "--reviewer": args.reviewer,
            "--reviewed-date": args.reviewed_date,
            "--verified-commit": args.verified_commit,
        }
        missing = [name for name, item in required.items() if not item]
        if missing:
            parser.error("transition requires " + ", ".join(missing))
        value = json.loads(path.read_text(encoding="utf-8"))
        apply_transition(
            value,
            issue_id=args.transition,
            expected_from=args.expected_from,
            to_status=args.to_status,
            review_reference=args.review_reference,
            evidence_references=args.evidence_reference,
            reviewer=args.reviewer,
            reviewed_date=args.reviewed_date,
            verified_commit=args.verified_commit,
            allow_downgrade=args.allow_downgrade,
            edge_dependency=args.edge_dependency,
            edge_state=args.edge_state,
            contract_reference=args.contract_reference,
        )
        _atomic_write(path, value)
        print(f"UPDATED: {args.transition} {args.expected_from}->{args.to_status}")
        return 0
    parser.error("select --import-registry, --refresh-base, --check-base or --transition")


if __name__ == "__main__":
    raise SystemExit(main())
