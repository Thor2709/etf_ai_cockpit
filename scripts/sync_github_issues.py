"""Synchronise the authoritative local issue ledger with GitHub Issues.

The local Markdown ledgers remain authoritative.  This tool only mirrors their
stable IDs, titles, selected state and available evidence; it never edits
``issues/open.md`` or ``issues/closed.md`` and never closes a product issue
based on GitHub state alone.

Run without ``--apply`` for a deterministic read-only inventory.  ``--apply``
creates or updates the corresponding GitHub Issues and writes the versioned map
and reconciliation report after every remote action has been read back.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Thor2709/etf_ai_cockpit"
MAP_PATH = ROOT / "issues" / "github_issue_map.json"
REPORT_PATH = ROOT / "issues" / "github_issue_sync_report.json"
MARKER_TEMPLATE = "<!-- etf-ai-cockpit-local-issue-id: {issue_id} -->"
MANAGED_START = "<!-- etf-ai-cockpit-managed-start -->"
MANAGED_END = "<!-- etf-ai-cockpit-managed-end -->"
HEADING_RE = re.compile(r"^(#{2,3})\s+([A-Z]+-[0-9]+)\s+-\s+(.+?)\s*$")
MARKER_RE = re.compile(r"<!--\s*etf-ai-cockpit-local-issue-id:\s*([^\s]+)\s*-->")


class SyncError(RuntimeError):
    """A deterministic inventory or reconciliation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_gh(args: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["gh", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        input=input_text,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "gh command failed").strip()
        raise SyncError(f"gh {' '.join(args)} failed ({completed.returncode}): {detail}")
    return completed.stdout


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError(f"JSON root must be an object: {path}")
    return value


def load_remote_issues() -> list[dict[str, Any]]:
    raw = run_gh(
        [
            "issue",
            "list",
            "--repo",
            REPOSITORY,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "number,title,state,url,body,labels,updatedAt",
        ]
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SyncError(f"GitHub issue inventory was not JSON: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SyncError("GitHub issue inventory must be a list of objects")
    return value


def headings(path: Path) -> list[tuple[int, str, str, str]]:
    rows: list[tuple[int, str, str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = HEADING_RE.match(line)
        if match:
            rows.append((line_number, match.group(1), match.group(2), match.group(3)))
    return rows


def section_for(path: Path, issue_id: str, *, title: str) -> tuple[int | None, str]:
    """Return the selected issue heading location and its bounded Markdown."""

    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(rf"^##{{1,3}}\s+{re.escape(issue_id)}\s+-\s+", line)
    ]
    if not starts:
        return None, f"### {issue_id} - {title}\n\nNo bounded local Markdown section was found."
    start = starts[0]
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return start + 1, "\n".join(lines[start:end]).strip()


def local_records(map_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_records = map_payload.get("records")
    if not isinstance(raw_records, list):
        raise SyncError("github_issue_map.json records must be a list")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise SyncError("local issue record is not an object")
        issue_id = str(raw.get("local_issue_id", "")).strip()
        title = str(raw.get("title", "")).strip()
        state = str(raw.get("local_state", "")).strip().lower()
        if not issue_id or not title:
            raise SyncError("local issue record lacks stable ID or title")
        if issue_id in seen:
            raise SyncError(f"duplicate local issue ID: {issue_id}")
        if state not in {"open", "closed"}:
            raise SyncError(f"contradictory local state for {issue_id}: {state!r}")
        seen.add(issue_id)
        source_file = Path(str(raw.get("source_file", "")))
        if source_file not in {Path("issues/open.md"), Path("issues/closed.md")}:
            raise SyncError(f"unsupported source file for {issue_id}: {source_file}")
        source_path = ROOT / source_file
        if not source_path.is_file():
            raise SyncError(f"source file missing for {issue_id}: {source_file}")
        preferred = source_path
        if state == "open" and source_file != Path("issues/open.md"):
            preferred = ROOT / "issues" / "open.md"
        if state == "closed" and source_file != Path("issues/closed.md"):
            preferred = ROOT / "issues" / "closed.md"
        selected_source = preferred if preferred.is_file() else source_path
        location, section = section_for(selected_source, issue_id, title=title)
        if location is None and selected_source != source_path:
            selected_source = source_path
            location, section = section_for(selected_source, issue_id, title=title)
        row = dict(raw)
        row.update(
            {
                "title": title,
                "local_state": state,
                "source_file": selected_source.relative_to(ROOT).as_posix(),
                "source_location": f"{selected_source.relative_to(ROOT).as_posix()}:{location or 1}",
                "source_checksum": sha256_file(selected_source),
                "local_section": section,
            }
        )
        records.append(row)
    contradictions = map_payload.get("unresolved_contradictions", [])
    if not isinstance(contradictions, list):
        contradictions = [{"reason": "unresolved_contradictions_not_a_list"}]
    return records, [item for item in contradictions if isinstance(item, dict)]


def ownership_hint(issue_id: str) -> str | None:
    path = ROOT / "docs" / "superpowers" / "plans" / "2026-07-11-etf-ai-cockpit-programme-index.md"
    for line in path.read_text(encoding="utf-8").splitlines():
        if issue_id in line and line.startswith("|"):
            return line.strip()
    return None


def managed_body(record: dict[str, Any]) -> str:
    issue_id = record["local_issue_id"]
    title = record["title"]
    state = record["local_state"]
    section = record.get("local_section", "").strip()
    owner = ownership_hint(issue_id) or "No owning-plan row was recorded in the programme index."
    closure = section if state == "closed" else "No closure evidence is recorded; the local ledger state is open."
    return "\n".join(
        [
            MARKER_TEMPLATE.format(issue_id=issue_id),
            MANAGED_START,
            f"# [{issue_id}] {title}",
            "",
            "## Local ledger authority",
            "The committed local issue ledger and approved specification are authoritative. This GitHub Issue is a synchronised project-management representation and must not be closed independently of the repository closure process.",
            "",
            f"- Local issue ID: `{issue_id}`",
            f"- Local state: `{state}`",
            f"- Source: `{record['source_location']}`",
            f"- Source checksum: `{record['source_checksum']}`",
            f"- Owning plan/wave hint: {owner}",
            "",
            "## Local summary and acceptance record",
            section,
            "",
            "## Closure evidence",
            closure,
            "",
            "## Synchronisation boundary",
            "This body is managed from the local ledger. Human discussion outside this managed block must be preserved. GitHub state is reconciled to the local state after the corresponding repository evidence exists.",
            MANAGED_END,
        ]
    )


def merge_managed_body(existing: str, managed: str) -> str:
    if MANAGED_START in existing and MANAGED_END in existing:
        prefix = existing.split(MANAGED_START, 1)[0].rstrip()
        suffix = existing.split(MANAGED_END, 1)[1].lstrip()
        return "\n\n".join(part for part in (prefix, managed, suffix) if part)
    return f"{existing.rstrip()}\n\n{managed}" if existing.strip() else managed


def marker_ids(issue: dict[str, Any]) -> set[str]:
    body = issue.get("body") or ""
    return {match.group(1).strip() for match in MARKER_RE.finditer(str(body))}


def remote_matches(remote: Iterable[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for issue in remote:
        ids = marker_ids(issue)
        title = str(issue.get("title", ""))
        ids.update(re.findall(r"^\[([A-Z]+-[0-9]+)\]", title))
        for issue_id in ids:
            if issue_id in by_id:
                duplicates.append({"local_issue_id": issue_id, "issue_number": issue.get("number"), "reason": "duplicate_remote_match"})
            else:
                by_id[issue_id] = issue
    return by_id, duplicates


def labels_for(record: dict[str, Any]) -> list[str]:
    labels = ["source:local-ledger"]
    if record["local_state"] == "open":
        labels.append("closure-pending")
    return labels


def ensure_labels(apply: bool) -> None:
    if not apply:
        return
    run_gh(["label", "create", "source:local-ledger", "--repo", REPOSITORY, "--color", "1d76db", "--description", "Mirrored from the authoritative local issue ledger", "--force"])
    run_gh(["label", "create", "closure-pending", "--repo", REPOSITORY, "--color", "fbca04", "--description", "Local issue remains open pending closure evidence", "--force"])


def gh_body_file(body: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False)
    try:
        handle.write(body)
    finally:
        handle.close()
    return Path(handle.name)


def sync_record(record: dict[str, Any], remote: dict[str, Any] | None, *, apply: bool) -> dict[str, Any]:
    issue_id = record["local_issue_id"]
    desired_title = f"[{issue_id}] {record['title']}"
    body = managed_body(record)
    action = "unchanged"
    current = remote
    if current is None:
        action = "create" if apply else "would_create"
        if apply:
            body_path = gh_body_file(body)
            try:
                output = run_gh(
                    [
                        "issue",
                        "create",
                        "--repo",
                        REPOSITORY,
                        "--title",
                        desired_title,
                        "--body-file",
                        str(body_path),
                        *sum((["--label", label] for label in labels_for(record)), []),
                    ]
                )
            finally:
                body_path.unlink(missing_ok=True)
            url = output.strip().splitlines()[-1]
            number_match = re.search(r"/(\d+)$", url)
            if number_match is None:
                raise SyncError(f"cannot parse created issue URL for {issue_id}: {url}")
            current = {"number": int(number_match.group(1)), "url": url, "title": desired_title, "state": "OPEN", "body": body}
            if record["local_state"] == "closed":
                run_gh(["issue", "close", str(current["number"]), "--repo", REPOSITORY, "--comment", "Closed to match the authoritative local ledger; historical closure evidence is in the managed body."])
                current["state"] = "CLOSED"
    else:
        number = int(current["number"])
        if current.get("title") != desired_title or body != str(current.get("body") or ""):
            action = "update" if apply else "would_update"
            if apply:
                body_path = gh_body_file(merge_managed_body(str(current.get("body") or ""), body))
                try:
                    run_gh(["issue", "edit", str(number), "--repo", REPOSITORY, "--title", desired_title, "--body-file", str(body_path)])
                finally:
                    body_path.unlink(missing_ok=True)
        remote_state = str(current.get("state", "")).lower()
        desired_state = record["local_state"]
        if desired_state == "open" and remote_state == "closed":
            action = "reopen" if apply else "would_reopen"
            if apply:
                run_gh(["issue", "reopen", str(number), "--repo", REPOSITORY])
        elif desired_state == "closed" and remote_state == "open":
            action = "close" if apply else "would_close"
            if apply:
                run_gh(["issue", "close", str(number), "--repo", REPOSITORY, "--comment", "Closed to match the authoritative local ledger; do not close independently of repository evidence."])
        if apply:
            current = next(item for item in load_remote_issues() if int(item["number"]) == number)
    return {
        "local_issue_id": issue_id,
        "github_issue_number": current.get("number") if current else None,
        "github_url": current.get("url") if current else None,
        "local_state": record["local_state"],
        "github_state": str(current.get("state", "")).lower() if current else None,
        "source_file": record["source_file"],
        "source_location": record["source_location"],
        "source_checksum": record["source_checksum"],
        "last_synchronised_commit": None,
        "action": action,
    }


def reconcile(records: list[dict[str, Any]], mapped: list[dict[str, Any]], duplicates: list[dict[str, Any]], *, apply: bool) -> dict[str, Any]:
    if duplicates:
        raise SyncError(f"unresolved duplicate GitHub matches: {duplicates}")
    local_counts = {state: sum(record["local_state"] == state for record in records) for state in ("open", "closed")}
    mapped_counts = {state: sum(item.get("github_state") == state for item in mapped) for state in ("open", "closed")}
    unresolved = [item for item in mapped if item.get("github_issue_number") is None]
    if apply and unresolved:
        raise SyncError(f"apply reconciliation has unmapped records: {unresolved[:3]}")
    return {
        "local_open_count": local_counts["open"],
        "local_closed_count": local_counts["closed"],
        "mapped_open_count": mapped_counts["open"],
        "mapped_closed_count": mapped_counts["closed"],
        "all_local_ids_unique": len({item["local_issue_id"] for item in mapped}) == len(mapped),
        "all_mappings_have_github_issue": not unresolved,
        "states_agree": all(item.get("local_state") == item.get("github_state") for item in mapped if item.get("github_state")),
        "unresolved_duplicates": duplicates,
        "passes": not unresolved and not duplicates and all(item.get("local_state") == item.get("github_state") for item in mapped if item.get("github_state")),
    }


def build_payload(*, records: list[dict[str, Any]], mapped: list[dict[str, Any]], contradictions: list[dict[str, Any]], remote_count: int, reconciliation: dict[str, Any], apply: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for item in mapped:
        item["last_synchronised_commit"] = commit if apply else None
    map_payload = {
        "schema_version": "1.1",
        "repository": REPOSITORY,
        "generated_at_utc": generated,
        "source_commit": commit,
        "local_ledger_policy": "One canonical record per stable ID. The committed local ledger and approved specification are authoritative; GitHub is a synchronised mirror.",
        "github_inventory": {"remote_count_before_sync": remote_count},
        "local_counts": {state: sum(record["local_state"] == state for record in records) for state in ("open", "closed")},
        "unresolved_contradictions": contradictions,
        "records": mapped,
        "reconciliation": reconciliation,
        "apply_mode": apply,
    }
    report = {
        "schema_version": "1.0",
        "generated_at_utc": generated,
        "repository": REPOSITORY,
        "source_commit": commit,
        "apply_mode": apply,
        "actions": [item["action"] for item in mapped],
        "unresolved_contradictions": contradictions,
        "reconciliation": reconciliation,
    }
    return map_payload, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform idempotent GitHub Issue writes")
    args = parser.parse_args(argv)
    map_source = load_json(MAP_PATH)
    records, contradictions = local_records(map_source)
    remote = load_remote_issues()
    by_id, duplicates = remote_matches(remote)
    if duplicates:
        raise SyncError(f"unresolved duplicate GitHub matches: {duplicates}")
    ensure_labels(args.apply)
    mapped = [sync_record(record, by_id.get(record["local_issue_id"]), apply=args.apply) for record in records]
    reconciliation = reconcile(records, mapped, duplicates, apply=args.apply)
    map_payload, report = build_payload(records=records, mapped=mapped, contradictions=contradictions, remote_count=len(remote), reconciliation=reconciliation, apply=args.apply)
    if args.apply:
        MAP_PATH.write_text(json.dumps(map_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"apply": args.apply, "record_count": len(records), "remote_count_before": len(remote), "reconciliation": reconciliation, "actions": {action: sum(item["action"] == action for item in mapped) for action in sorted({item["action"] for item in mapped})}}, indent=2, sort_keys=True))
    return 0 if (not args.apply or reconciliation["passes"]) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SyncError as exc:
        print(f"sync blocked: {exc}", file=sys.stderr)
        raise SystemExit(2)
