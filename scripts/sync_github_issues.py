"""Plan and, only with an approved checksum, synchronise canonical issues.

The default command is read-only. Managed fields are bounded by HTML markers;
all issue-body content outside that block is preserved byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.issue_registry_core import REGISTRY_PATH, deterministic_json
except ModuleNotFoundError:
    from issue_registry_core import REGISTRY_PATH, deterministic_json


REPO = "Thor2709/etf_ai_cockpit"
MARKER_RE = re.compile(r"<!--\s*etf-ai-cockpit:stable-id=((?:ISSUE|UPDATEV2)-\d{4})\s*-->")
LEGACY_MARKER_RE = re.compile(
    r"<!--\s*etf-ai-cockpit-local-issue-id:\s*((?:ISSUE|UPDATEV2)-\d{4})\s*-->"
)
MANAGED_START = "<!-- etf-ai-cockpit:managed:start -->"
MANAGED_END = "<!-- etf-ai-cockpit:managed:end -->"
LEGACY_MANAGED_START = "<!-- etf-ai-cockpit-managed-start -->"
LEGACY_MANAGED_END = "<!-- etf-ai-cockpit-managed-end -->"
REVIEWED_REOPEN_IDS = frozenset({"ISSUE-0048", "ISSUE-0067", "ISSUE-0122"})
DEFAULT_MAP_PATH = Path(
    "docs/product-completion/reconciliation/2026-07-17-3321ebd/github-issue-map.json"
)
DEFAULT_RECONCILIATION_ROOT = Path(
    "docs/product-completion/reconciliation/2026-07-21-452d440"
)


def managed_block(record: dict[str, Any]) -> str:
    stable_id = record.get("canonical_id", record.get("stable_id", ""))
    dependencies = ", ".join(f"`{value}`" for value in record.get("blocking_dependencies", [])) or "None"
    required_inputs = ", ".join(f"`{value}`" for value in record.get("required_inputs", [])) or "None"
    activation = ", ".join(f"`{value}`" for value in record.get("activation_dependencies", [])) or "None"
    downstream = ", ".join(f"`{value}`" for value in record.get("downstream_issues", [])) or "None"
    related = ", ".join(f"`{value}`" for value in record.get("related_issues", [])) or "None"
    return "\n".join(
        [
            MANAGED_START,
            f"<!-- etf-ai-cockpit:stable-id={stable_id} -->",
            "## Canonical programme record",
            f"- Title: {record.get('title', '')}",
            f"- Classification: `{record.get('classification', '')}`",
            f"- Ledger state: `{record.get('ledger_state', 'open')}`",
            f"- Programme status: `{record.get('programme_status', 'planned')}`",
            f"- Priority: `{record.get('priority', '')}`",
            f"- Owner: `{record.get('owner', '')}`",
            f"- Phase: `{record.get('phase', '')}`",
            f"- Blocking dependencies: {dependencies}",
            f"- Required inputs: {required_inputs}",
            f"- Activation dependencies: {activation}",
            f"- Capability lane: `{record.get('capability_lane', 'unassigned')}`",
            f"- Release blocking in lane: `{str(record.get('release_blocking', False)).lower()}`",
            f"- Downstream issues: {downstream}",
            f"- Related issues: {related}",
            "- Execution allowed: `false`",
            MANAGED_END,
        ]
    )


def replace_managed_block(body: str, block: str) -> str:
    pairs = [
        (MANAGED_START, MANAGED_END),
        (LEGACY_MANAGED_START, LEGACY_MANAGED_END),
    ]
    present = [(start, end) for start, end in pairs if start in body or end in body]
    valid = [(start, end) for start, end in pairs if body.count(start) == 1 and body.count(end) == 1]
    if not present:
        separator = "\n\n" if body and not body.endswith("\n") else "\n"
        return body + separator + block + "\n"
    if len(valid) != 1 or len(present) != 1:
        raise ValueError("managed block is missing a boundary or is duplicated")
    start_token, end_token = valid[0]
    start = body.index(start_token)
    end = body.index(end_token, start) + len(end_token)
    return body[:start] + block + body[end:]


def marker_ids(remote_issues: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for issue in remote_issues:
        body = str(issue.get("body", ""))
        values = set(MARKER_RE.findall(body)) | set(LEGACY_MARKER_RE.findall(body))
        for value in values:
            result.setdefault(value, []).append(issue)
    return result


def normalise_remote_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": int(issue.get("number", 0)),
        "title": str(issue.get("title", "")),
        "body": str(issue.get("body") or ""),
        "state": str(issue.get("state", "OPEN")).lower(),
        "url": str(issue.get("url", "")),
    }


def registry_sync_records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    records = [dict(record) for record in registry.get("records", [])]
    for record in registry.get("local_only_records", []):
        local = dict(record)
        local.setdefault("programme_status", "closed" if local.get("ledger_state") == "closed" else "planned")
        local.setdefault("source_kind", "local_only")
        local.setdefault("owner", "programme-governance")
        local.setdefault("phase", "phase-01-governance-scope")
        local.setdefault("blocking_dependencies", [])
        local.setdefault("required_inputs", [])
        local.setdefault("activation_dependencies", [])
        local.setdefault("downstream_issues", [])
        local.setdefault("related_issues", [])
        records.append(local)
    return sorted(records, key=lambda record: str(record.get("canonical_id", "")))


def _legacy_matches(record: dict[str, Any], remote: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_id = str(record["canonical_id"])
    title = str(record.get("title", "")).strip().casefold()
    matches = []
    for issue in remote:
        body = str(issue.get("body", ""))
        if issue_id in LEGACY_MARKER_RE.findall(body) or issue_id in str(issue.get("title", "")):
            matches.append(issue)
        elif title and title == str(issue.get("title", "")).strip().casefold():
            matches.append(issue)
    return matches


def _action(kind: str, record: dict[str, Any] | None = None, **values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": kind}
    if record is not None:
        result["stable_id"] = record.get("canonical_id")
        result["title"] = record.get("title", "")
        result["desired_state"] = "closed" if record.get("ledger_state") == "closed" else "open"
        for field in (
            "classification",
            "ledger_state",
            "programme_status",
            "priority",
            "owner",
            "phase",
            "blocking_dependencies",
            "required_inputs",
            "activation_dependencies",
            "capability_lane",
            "release_blocking",
            "downstream_issues",
            "related_issues",
        ):
            result[field] = record.get(field, [] if field.endswith("_dependencies") or field.endswith("_issues") else "")
    result.update(values)
    return result


def plan_actions(
    registry: dict[str, Any],
    remote_issues: Iterable[dict[str, Any]],
    *,
    reviewed_reopen_ids: Iterable[str] = REVIEWED_REOPEN_IDS,
    historical_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    remote = [normalise_remote_issue(issue) for issue in remote_issues]
    by_marker = marker_ids(remote)
    reopen_ids = set(reviewed_reopen_ids)
    actions: list[dict[str, Any]] = []
    selected_numbers: dict[str, int] = {}
    legacy_duplicates: list[dict[str, Any]] = []
    desired_ids = {str(record.get("canonical_id")) for record in registry_sync_records(registry)}
    records = registry_sync_records(registry)
    for stable_id, issues in sorted(by_marker.items()):
        if stable_id not in desired_ids:
            actions.append(_action("blocked", stable_id=stable_id, reason="unmapped_remote_stable_id", remote_numbers=[issue["number"] for issue in issues]))
        elif len(issues) > 1:
            mapping = (historical_map or {}).get("mappings", {}).get(stable_id)
            remote_numbers = sorted(issue["number"] for issue in issues)
            selected = mapping.get("selected_remote_number") if isinstance(mapping, dict) else None
            if (
                isinstance(selected, int)
                and selected in remote_numbers
                and sorted(mapping.get("remote_numbers", [])) == remote_numbers
                and all(issue["state"] == "closed" for issue in issues if issue["number"] != selected)
            ):
                selected_numbers[stable_id] = selected
                legacy_duplicates.append(
                    {
                        "stable_id": stable_id,
                        "selected_remote_number": selected,
                        "retained_closed_remote_numbers": [number for number in remote_numbers if number != selected],
                        "selection_basis": mapping.get("selection_basis", "reviewed historical duplicate map"),
                    }
                )
            else:
                actions.append(_action("blocked", stable_id=stable_id, reason="duplicate_stable_marker", remote_numbers=remote_numbers))

    mapped_numbers: set[int] = set()
    for record in records:
        stable_id = str(record["canonical_id"])
        matches = by_marker.get(stable_id, [])
        if stable_id in selected_numbers:
            matches = [issue for issue in matches if issue["number"] == selected_numbers[stable_id]]
        if len(matches) > 1:
            continue
        if not matches:
            legacy = _legacy_matches(record, remote)
            if len(legacy) > 1:
                actions.append(_action("blocked", record, reason="ambiguous_legacy_match", remote_numbers=[issue["number"] for issue in legacy]))
                continue
            if len(legacy) == 1:
                actions.append(_action("blocked", record, reason="legacy_unmanaged_match", remote_number=legacy[0]["number"]))
                continue
            if record.get("ledger_state") == "closed":
                actions.append(_action("blocked", record, reason="missing_closed_record"))
            else:
                actions.append(_action("create", record))
            continue

        issue = matches[0]
        mapped_numbers.add(issue["number"])
        body = issue["body"]
        new_markers = MARKER_RE.findall(body)
        legacy_markers = LEGACY_MARKER_RE.findall(body)
        marker_values = set(new_markers) | set(legacy_markers)
        marker_count = len(marker_values)
        has_managed_boundary = any(
            body.count(start) == 1 and body.count(end) == 1
            for start, end in (
                (MANAGED_START, MANAGED_END),
                (LEGACY_MANAGED_START, LEGACY_MANAGED_END),
            )
        )
        if (
            marker_count != 1
            or marker_values != {stable_id}
            or len(new_markers) > 1
            or len(legacy_markers) > 1
            or not has_managed_boundary
        ):
            actions.append(_action("blocked", record, reason="ambiguous_managed_body", remote_number=issue["number"]))
            continue
        try:
            desired_body = replace_managed_block(body, managed_block(record))
        except ValueError as exc:
            actions.append(_action("blocked", record, reason=str(exc), remote_number=issue["number"]))
            continue
        if desired_body != body or str(issue.get("title", "")) != str(record.get("title", "")):
            actions.append(_action("update", record, remote_number=issue["number"], body=desired_body))
        desired_state = "closed" if record.get("ledger_state") == "closed" else "open"
        remote_state = str(issue.get("state", "open")).lower()
        if desired_state == "open" and remote_state == "closed":
            if stable_id in reopen_ids:
                actions.append(_action("reopen", record, remote_number=issue["number"]))
            else:
                actions.append(_action("blocked", record, reason="unexpected_transition_closed_to_open", remote_number=issue["number"]))
        elif desired_state == "closed" and remote_state == "open":
            actions.append(_action("close", record, remote_number=issue["number"]))

    for issue in remote:
        if issue["number"] in mapped_numbers:
            continue
        values = MARKER_RE.findall(issue["body"])
        if values:
            continue

    summary = {
        "create": sum(action["kind"] == "create" for action in actions),
        "update": sum(action["kind"] == "update" for action in actions),
        "close": sum(action["kind"] == "close" for action in actions),
        "reopen": sum(action["kind"] == "reopen" for action in actions),
        "blocked": sum(action["kind"] == "blocked" for action in actions),
    }
    payload = {
        "schema_version": "1.0",
        "repository": REPO,
        "remote_inventory_sha256": inventory_sha256(remote),
        "desired_record_count": len(records),
        "remote_issue_count": len(remote),
        "reviewed_reopen_ids": sorted(reopen_ids),
        "historical_map_sha256": (historical_map or {}).get("map_sha256"),
        "legacy_duplicates": legacy_duplicates,
        "summary": summary,
        "actions": sorted(actions, key=lambda action: (str(action.get("stable_id", "")), action["kind"])),
    }
    payload["plan_sha256"] = plan_sha256(payload)
    return payload


def inventory_sha256(remote_issues: Iterable[dict[str, Any]]) -> str:
    normalised = [normalise_remote_issue(issue) for issue in remote_issues]
    normalised.sort(key=lambda issue: issue["number"])
    return hashlib.sha256(deterministic_json(normalised)).hexdigest()


def safe_remote_inventory(remote_issues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalised = sorted(
        (normalise_remote_issue(issue) for issue in remote_issues),
        key=lambda issue: issue["number"],
    )
    rows = []
    for issue in normalised:
        ids = sorted(set(MARKER_RE.findall(issue["body"])) | set(LEGACY_MARKER_RE.findall(issue["body"])))
        rows.append({
            "number": issue["number"],
            "stable_id": ids[0] if len(ids) == 1 else "",
            "state": issue["state"],
            "title": issue["title"],
            "url": issue["url"],
        })
    return {
        "schema_version": "1.0",
        "repository": REPO,
        "inventory_sha256": inventory_sha256(normalised),
        "issues": rows,
        "privacy": "stable identifiers and issue metadata only; bodies excluded",
    }


def _managed_delta_fields(action: dict[str, Any], remote: dict[str, Any] | None) -> list[str]:
    if action.get("kind") != "update" or remote is None:
        return []
    body = str(remote.get("body", ""))
    desired = managed_block(action)
    labels = (
        "Title", "Classification", "Ledger state", "Programme status", "Priority",
        "Owner", "Phase", "Blocking dependencies", "Required inputs",
        "Activation dependencies", "Capability lane", "Release blocking in lane",
        "Downstream issues", "Related issues", "Execution allowed",
    )
    changed = []
    for label in labels:
        prefix = f"- {label}:"
        old = next((line for line in body.splitlines() if line.startswith(prefix)), "")
        new = next((line for line in desired.splitlines() if line.startswith(prefix)), "")
        if old != new:
            changed.append(label)
    return changed


def safe_plan_evidence(plan: dict[str, Any], remote_issues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    remote = {issue["number"]: issue for issue in (normalise_remote_issue(row) for row in remote_issues)}
    actions = []
    for action in plan.get("actions", []):
        issue = remote.get(action.get("remote_number"))
        actions.append({
            "kind": action.get("kind"),
            "stable_id": action.get("stable_id", ""),
            "title": action.get("title", issue.get("title", "") if issue else ""),
            "remote_number": action.get("remote_number"),
            "remote_state": issue.get("state", "") if issue else "",
            "url": issue.get("url", "") if issue else "",
            "managed_field_deltas": _managed_delta_fields(action, issue),
        })
    return {
        "schema_version": "1.0",
        "repository": plan.get("repository"),
        "remote_inventory_sha256": plan.get("remote_inventory_sha256"),
        "plan_semantic_sha256": plan.get("plan_sha256"),
        "summary": plan.get("summary"),
        "actions": actions,
        "apply_authority": False,
        "fresh_exact_plan_required_for_apply": True,
    }


def plan_sha256(plan: dict[str, Any]) -> str:
    value = dict(plan)
    value.pop("plan_sha256", None)
    return hashlib.sha256(deterministic_json(value)).hexdigest()


def sync_review_markdown(plan: dict[str, Any], *, plan_file_sha256: str) -> str:
    lines = [
        "# GitHub issue sync dry-run review",
        "",
        "This is read-only B00 evidence. The plan was not applied and no GitHub issue was mutated.",
        "",
        f"- Repository: `{plan.get('repository')}`",
        f"- Remote inventory SHA-256: `{plan.get('remote_inventory_sha256')}`",
        f"- Plan semantic SHA-256: `{plan.get('plan_semantic_sha256', plan.get('plan_sha256'))}`",
        f"- Plan file SHA-256: `{plan_file_sha256}`",
        f"- Desired actions: {len(plan.get('actions', []))}",
        "- `execution_allowed=false`",
        "",
        "## Exact action scope",
        "",
    ]
    for kind in ("create", "update", "close", "reopen", "blocked"):
        actions = [action for action in plan.get("actions", []) if action.get("kind") == kind]
        lines.append(f"### `{kind}` ({len(actions)})")
        lines.append("")
        if not actions:
            lines.append("- none")
        else:
            lines.append("| Stable ID | Remote | Managed-field delta |")
            lines.append("|---|---:|---|")
            for action in actions:
                fields = ", ".join(action.get("managed_field_deltas", [])) or "state/action only"
                lines.append(f"| `{action.get('stable_id', 'unknown')}` | {action.get('remote_number') or '-'} | {fields} |")
        lines.append("")
    lines.extend(
        [
            "",
            "A later apply requires explicit root authority and the exact reviewed semantic plan checksum. "
            "Any remote inventory or local registry change requires a new plan and review.",
            "",
        ]
    )
    return "\n".join(lines)


def gh_list_issues() -> list[dict[str, Any]]:
    value = json.loads(
        gh_command(
            [
                "issue",
                "list",
                "--repo",
                REPO,
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                "number,title,body,state,url",
            ]
        )
    )
    if not isinstance(value, list):
        raise ValueError("gh issue list did not return a JSON list")
    return value


def gh_write(args: list[str]) -> str:
    return gh_command(args)


def gh_command(args: list[str], *, attempts: int = 3) -> str:
    """Run one gh operation, retrying only transient HTTP 503 failures."""

    for attempt in range(attempts):
        completed = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode == 0:
            return completed.stdout
        combined = f"{completed.stdout}\n{completed.stderr}"
        if "503" not in combined or attempt == attempts - 1:
            raise subprocess.CalledProcessError(
                completed.returncode,
                ["gh", *args],
                output=completed.stdout,
                stderr=completed.stderr,
            )
        time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def apply_actions(plan: dict[str, Any], *, approved_sha256: str) -> None:
    if approved_sha256 != plan.get("plan_sha256") or approved_sha256 != plan_sha256(plan):
        raise ValueError("approved plan SHA-256 does not match the current deterministic plan")
    blocked = [action for action in plan.get("actions", []) if action.get("kind") == "blocked"]
    if blocked:
        raise ValueError("cannot apply a plan containing blocked actions")
    for action in plan.get("actions", []):
        kind = action["kind"]
        number = action.get("remote_number")
        if kind == "create":
            body = managed_block(action)
            output = gh_write(["issue", "create", "--repo", REPO, "--title", action["title"], "--body", body])
            match = re.search(r"/issues/(\d+)", output)
            if not match:
                raise RuntimeError("gh issue create did not return an issue URL")
            number = match.group(1)
        elif kind == "update":
            gh_write(["issue", "edit", str(number), "--repo", REPO, "--title", action["title"], "--body", action["body"]])
        if kind == "close" or (kind == "create" and action.get("desired_state") == "closed"):
            gh_write(["issue", "close", str(number), "--repo", REPO])
        elif kind == "reopen":
            gh_write(["issue", "reopen", str(number), "--repo", REPO])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--remote-snapshot", type=Path, help="read a saved gh issue JSON list instead of calling gh")
    parser.add_argument("--plan-out", type=Path)
    parser.add_argument("--review-out", type=Path, help="write a deterministic read-only scope review")
    parser.add_argument(
        "--inventory-out",
        type=Path,
        help="write a redacted deterministic inventory (never remote bodies)",
    )
    parser.add_argument("--safe-evidence-out", type=Path, help="write a redacted deterministic action summary")
    parser.add_argument("--historical-map", type=Path, help="reviewed map for duplicate legacy remote issues")
    parser.add_argument("--apply", action="store_true", help="apply only after the approved plan SHA-256 is supplied")
    parser.add_argument("--approved-plan-sha256")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
    if args.remote_snapshot:
        remote = json.loads(args.remote_snapshot.read_text(encoding="utf-8"))
    else:
        remote = gh_list_issues()
    if not isinstance(remote, list):
        raise SystemExit("remote snapshot must be a JSON list")
    normalised_remote = sorted(
        (normalise_remote_issue(issue) for issue in remote),
        key=lambda issue: issue["number"],
    )
    if args.inventory_out:
        args.inventory_out.parent.mkdir(parents=True, exist_ok=True)
        args.inventory_out.write_bytes(deterministic_json(safe_remote_inventory(normalised_remote)))
    map_path = args.historical_map or root / DEFAULT_MAP_PATH
    historical_map = None
    if map_path.exists():
        historical_map = json.loads(map_path.read_text(encoding="utf-8"))
    plan = plan_actions(registry, normalised_remote, historical_map=historical_map)
    safe_evidence = safe_plan_evidence(plan, normalised_remote)
    if args.safe_evidence_out:
        args.safe_evidence_out.parent.mkdir(parents=True, exist_ok=True)
        args.safe_evidence_out.write_bytes(deterministic_json(safe_evidence))
    output = args.plan_out or root / DEFAULT_RECONCILIATION_ROOT / "github-sync-plan.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    plan_bytes = deterministic_json(plan)
    output.write_bytes(plan_bytes)
    if args.review_out:
        args.review_out.parent.mkdir(parents=True, exist_ok=True)
        args.review_out.write_text(
            sync_review_markdown(
                safe_evidence,
                plan_file_sha256=hashlib.sha256(plan_bytes).hexdigest(),
            ),
            encoding="utf-8",
            newline="\n",
        )
    print(f"PLAN: {output}")
    print(f"PLAN_SHA256: {plan['plan_sha256']}")
    print(json.dumps(plan["summary"], indent=2, sort_keys=True))
    if args.apply:
        if not args.approved_plan_sha256:
            raise SystemExit("--apply requires --approved-plan-sha256")
        apply_actions(plan, approved_sha256=args.approved_plan_sha256)
        expected_noop = {"create": 0, "update": 0, "close": 0, "reopen": 0, "blocked": 0}
        readback = None
        for attempt in range(4):
            readback = plan_actions(registry, gh_list_issues(), historical_map=historical_map)
            if readback["summary"] == expected_noop:
                break
            if attempt < 3:
                time.sleep(2**attempt)
        if readback is None or readback["summary"] != expected_noop:
            raise SystemExit("GitHub read-back is not idempotent")
        print("APPLIED_AND_VERIFIED")
    return 0 if not plan["summary"]["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
