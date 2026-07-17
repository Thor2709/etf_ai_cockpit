"""Fail-closed release-certification evidence for the completion programme.

This module deliberately does not certify a release by counting source files or
by inferring that an issue is complete.  It reports the current evidence
boundary and remains blocked until the canonical programme and release gates
provide the required evidence.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


CERTIFICATION_SCHEMA_VERSION = "release-certification.v1"
REGISTRY_PATH = Path("issues/issue_registry.json")
CERTIFICATION_ISSUE_ID = "ISSUE-0152"

ACCEPTED_FINAL_STATUSES = frozenset(
    {"integrated", "hardening_required", "blocked", "closed", "research_only", "rejected"}
)
HIGH_PRIORITY_MARKERS = frozenset({"P0", "P0/P1", "P1", "P1/P2"})

# These are recorded baseline limitations from the pre-certification full-suite
# run.  They are evidence, not exemptions from the certification contract.
BASELINE_LIMITATIONS = (
    "Baseline full-suite failure: tests/scope_boundary/test_package_inventory.py::test_current_production_package_inventory_passes reports prohibited BROKER_ADAPTER inventory.",
    "Baseline full-suite failure: tests/test_governance_review_regressions.py::test_audit_manifest_includes_governance_checksums_version_and_diagnostic_marker reports diagnostic_mode=true.",
    "Baseline full-suite failure: tests/test_product_governance.py::test_authority_matrix_covers_runtime_capabilities_and_stays_disabled reports a missing policy value.",
    "Baseline full-suite failure: tests/ui/test_system_map_ui.py::test_system_map_shows_future_execution_as_non_interactive reports missing execution: disabled evidence.",
    "Baseline Windows limitation: tests/operations/test_transactions.py::test_group_reader_cannot_observe_mixed_generation_during_activation reports a transaction PermissionError.",
)
ACCEPTED_LIMITATIONS = (
    "Execution remains disabled; this evidence surface cannot authorise order transmission.",
    "Certification reads local evidence only and makes no network calls.",
    "Optional providers and model weights are not mandatory for the local-first path.",
)


def _git_value(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _high_priority(priority: object) -> bool:
    return str(priority or "").strip().upper() in HIGH_PRIORITY_MARKERS


def _load_registry(root: Path) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    path = root / REGISTRY_PATH
    if not path.is_file():
        return None, None, [f"canonical issue registry is missing: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, [f"canonical issue registry could not be loaded: {type(exc).__name__}: {exc}"]
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return None, None, ["canonical issue registry is malformed: records must be a list"]
    return payload, hashlib.sha256(path.read_bytes()).hexdigest(), []


def _record_label(record: dict[str, Any]) -> str:
    return f"{record.get('canonical_id', 'unknown')} ({record.get('programme_status', 'unknown')})"


def _signed_manifest_status(root: Path, release_commit: str) -> tuple[str, str]:
    """Return the current-candidate detached-signature status without secrets."""

    release_root = root / "artifacts" / "release" / "issue-0152"
    manifest_path = release_root / "release-manifest.json"
    signature_path = release_root / "release-manifest.sig.json"
    if not manifest_path.is_file() or not signature_path.is_file():
        return "blocked", "signed ISSUE-0152 release manifest evidence is not present"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        signature = json.loads(signature_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "blocked", f"ISSUE-0152 release manifest evidence is unreadable: {type(exc).__name__}: {exc}"
    if signature.get("status") != "signed":
        return "blocked", "ISSUE-0152 release manifest signature status is not signed"
    git_payload = manifest.get("git")
    if release_commit != "unavailable" and (not isinstance(git_payload, dict) or git_payload.get("head") != release_commit):
        return "blocked", "ISSUE-0152 release manifest does not match the current release commit"
    return "passed", "signed release manifest matches the current candidate"


def release_certification_report(root: Path) -> dict[str, Any]:
    """Build a deterministic, local-only certification report."""

    root = Path(root).resolve()
    registry, registry_sha256, load_failures = _load_registry(root)
    release_commit = _git_value(root, "rev-parse", "HEAD")
    report: dict[str, Any] = {
        "schema_version": CERTIFICATION_SCHEMA_VERSION,
        "issue_id": CERTIFICATION_ISSUE_ID,
        "status": "blocked",
        "network_calls": False,
        "execution_allowed": False,
        "release_commit": release_commit,
        "registry_sha256": registry_sha256 or "unavailable",
        "counts": {},
        "checks": [],
        "blockers": list(load_failures),
        "accepted_limitations": list(ACCEPTED_LIMITATIONS),
        "failures": list(load_failures),
    }
    if registry is None:
        report["checks"] = [
            {"check_id": "canonical_issue_registry", "status": "blocked", "evidence": "; ".join(load_failures)}
        ]
        return report

    records = [record for record in registry["records"] if isinstance(record, dict)]
    status_counts = Counter(str(record.get("programme_status", "unknown")) for record in records)
    unresolved = [record for record in records if str(record.get("programme_status", "")) not in ACCEPTED_FINAL_STATUSES]
    high_priority_unresolved = [record for record in unresolved if _high_priority(record.get("priority"))]
    legal_record = next((record for record in records if record.get("canonical_id") == "ISSUE-0149"), None)
    manifest_status, manifest_evidence = _signed_manifest_status(root, release_commit)

    report["counts"] = {
        "canonical_records": len(records),
        "programme_statuses": dict(sorted(status_counts.items())),
        "unresolved_records": len(unresolved),
        "high_priority_unresolved_records": len(high_priority_unresolved),
    }
    report["checks"] = [
        {
            "check_id": "canonical_issue_registry",
            "status": "passed",
            "evidence": f"{len(records)} canonical records loaded",
        },
        {
            "check_id": "programme_closure_matrix",
            "status": "passed" if not unresolved else "blocked",
            "evidence": "all records have an accepted final programme status"
            if not unresolved
            else f"{len(unresolved)} records remain outside the accepted final status set",
        },
        {
            "check_id": "high_priority_closure",
            "status": "passed" if not high_priority_unresolved else "blocked",
            "evidence": "no unresolved P0/P1 records"
            if not high_priority_unresolved
            else "; ".join(_record_label(record) for record in high_priority_unresolved),
        },
        {
            "check_id": "legal_terms_review",
            "status": "passed" if legal_record and legal_record.get("programme_status") != "hardening_required" else "blocked",
            "evidence": _record_label(legal_record) if legal_record else "ISSUE-0149 is missing",
        },
        {
            "check_id": "signed_release_manifest",
            "status": manifest_status,
            "evidence": manifest_evidence,
        },
        {
            "check_id": "execution_authority",
            "status": "passed",
            "evidence": "execution_allowed=false; certification cannot transmit orders",
        },
        {
            "check_id": "network_policy",
            "status": "passed",
            "evidence": "network_calls=false; certification reads local evidence only",
        },
    ]

    if unresolved:
        report["blockers"].append(
            "canonical programme is not closed: "
            + ", ".join(_record_label(record) for record in unresolved)
        )
    if high_priority_unresolved:
        report["blockers"].append(
            "unresolved P0/P1 records remain: "
            + ", ".join(_record_label(record) for record in high_priority_unresolved)
        )
    if legal_record and legal_record.get("programme_status") == "hardening_required":
        report["blockers"].append(
            "ISSUE-0149 remains hardening_required pending professional legal review and repository licence evidence"
        )
    elif legal_record is None:
        report["blockers"].append("ISSUE-0149 is absent from the canonical registry")
    if manifest_status != "passed":
        report["blockers"].append(manifest_evidence)
    report["blockers"].extend(BASELINE_LIMITATIONS)
    report["failures"] = list(report["blockers"])
    report["status"] = "passed" if not report["blockers"] else "blocked"
    return report


def write_release_certification_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    """Write stable JSON and readable Markdown evidence files."""

    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = [
        "# Release certification report",
        "",
        f"- Issue: `{report.get('issue_id', CERTIFICATION_ISSUE_ID)}`",
        f"- Schema: `{report.get('schema_version', CERTIFICATION_SCHEMA_VERSION)}`",
        f"- Status: `{report.get('status', 'blocked')}`",
        f"- Release commit: `{report.get('release_commit', 'unavailable')}`",
        f"- Registry SHA-256: `{report.get('registry_sha256', 'unavailable')}`",
        "- Network calls: `false`",
        "- Execution allowed: `false`",
        f"- Duration: `{report.get('duration_ms', 'unavailable')} ms`",
        "",
        "## Checks",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for check in report.get("checks", []):
        lines.append(f"| `{check.get('check_id', 'unknown')}` | `{check.get('status', 'blocked')}` | {check.get('evidence', '')} |")
    lines.extend(["", "## Blockers", ""])
    blockers = report.get("blockers", []) or ["None"]
    lines.extend(f"- {item}" for item in blockers)
    lines.extend(["", "## Accepted limitations", ""])
    limitations = report.get("accepted_limitations", []) or ["None recorded"]
    lines.extend(f"- {item}" for item in limitations)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


__all__ = [
    "ACCEPTED_FINAL_STATUSES",
    "ACCEPTED_LIMITATIONS",
    "BASELINE_LIMITATIONS",
    "CERTIFICATION_ISSUE_ID",
    "CERTIFICATION_SCHEMA_VERSION",
    "release_certification_report",
    "write_release_certification_report",
]
