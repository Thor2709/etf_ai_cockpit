"""Generate the visible reconciliation, roadmap and phase documents."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from scripts.issue_registry_core import (
        CLOSED_LEDGER,
        PROGRAMME_ROOT,
        build_registry,
        deterministic_json,
        records_by_phase,
    )
    from scripts.validate_completion_package import validate_package
except ModuleNotFoundError:
    from issue_registry_core import (
        CLOSED_LEDGER,
        PROGRAMME_ROOT,
        build_registry,
        deterministic_json,
        records_by_phase,
    )
    from validate_completion_package import validate_package


RECONCILIATION_DATE = "2026-07-21"
DEFAULT_PACKAGE_NAME = "ETF_AI_Cockpit_Full_Research_and_Issue_Package.zip"
REPO = "Thor2709/etf_ai_cockpit"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    path.write_bytes((normalised.rstrip() + "\n").encode("utf-8"))


def write_managed_section(path: Path, name: str, body: str) -> None:
    begin = f"<!-- BEGIN GENERATED {name} -->"
    end = f"<!-- END GENERATED {name} -->"
    block = f"{begin}\n{body.strip()}\n{end}"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    current = current.replace("\r\n", "\n").replace("\r", "\n")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    rendered = pattern.sub(block, current) if pattern.search(current) else current.rstrip() + "\n\n" + block
    write_text(path, rendered)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(deterministic_json(value))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def command_json(command: list[str], *, retries: int = 2) -> Any:
    for attempt in range(retries + 1):
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            return json.loads(completed.stdout)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            if attempt >= retries:
                return None
            time.sleep(0.5 * (attempt + 1))
    return None


def worktree_inventory(root: Path) -> list[dict[str, str]]:
    try:
        output = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"],
            cwd=root,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    result: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines() + [""]:
        if line.startswith("worktree "):
            if current:
                result.append(current)
            current = {"path": line.removeprefix("worktree ")}
        elif line.startswith("HEAD "):
            current["head"] = line.removeprefix("HEAD ")
        elif line.startswith("branch "):
            current["branch"] = line.removeprefix("branch refs/heads/")
        elif not line and current:
            result.append(current)
            current = {}
    return result


def package_path_for(root: Path, supplied: Path | None) -> Path:
    if supplied is not None:
        return supplied.resolve()
    return (root.parent.parent / "etf_ai_cockpit" / DEFAULT_PACKAGE_NAME).resolve()


def raw_candidate_cycles(registry: dict[str, Any]) -> list[list[str]]:
    records = {str(row["canonical_id"]): row for row in registry.get("records", [])}
    graph = {
        issue_id: sorted(
            dependency
            for dependency in row.get("dependency_candidates", [])
            if dependency in records
        )
        for issue_id, row in records.items()
    }
    cycles: set[tuple[str, ...]] = set()

    def canonical_cycle(path: list[str]) -> tuple[str, ...]:
        rotations = [tuple(path[index:] + path[:index]) for index in range(len(path))]
        return min(rotations)

    def visit(start: str, node: str, path: list[str]) -> None:
        for dependency in graph.get(node, []):
            if dependency == start:
                cycles.add(canonical_cycle(path))
            elif dependency not in path and len(path) < len(graph):
                visit(start, dependency, path + [dependency])

    for start in sorted(graph):
        visit(start, start, [start])
    return [list(cycle) for cycle in sorted(cycles)]


def route_inventory(root: Path) -> list[str]:
    path = root / "src/etf_cockpit/app/router.py"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^PAGES\s*=\s*\{(.*?)^\}", text, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    return re.findall(r'^\s*"([^"]+)":\s*\(', match.group(1), re.MULTILINE)


def package_source_rows(registry: dict[str, Any]) -> list[dict[str, object]]:
    rows = []
    for record in registry.get("records", []):
        rows.append(
            {
                "source_record_id": record.get("source_record_id"),
                "source_kind": record.get("source_kind"),
                "source_file": record.get("source_file"),
                "source_title": record.get("source_title"),
                "canonical_id": record.get("canonical_id"),
                "canonical_title": record.get("title"),
                "classification": record.get("classification"),
                "ledger_state": record.get("ledger_state"),
                "package_status": record.get("package_status"),
                "programme_status": record.get("programme_status"),
                "priority": record.get("priority"),
                "owner": record.get("owner"),
                "phase": record.get("phase"),
                "dependency_candidates": ";".join(record.get("dependency_candidates", [])),
                "blocking_dependencies": ";".join(record.get("blocking_dependencies", [])),
                "required_inputs": ";".join(record.get("required_inputs", [])),
                "activation_dependencies": ";".join(record.get("activation_dependencies", [])),
                "downstream_issues": ";".join(record.get("downstream_issues", [])),
                "related_issues": ";".join(record.get("related_issues", [])),
                "discrepancy": (
                    "canonical title follows latest ledger"
                    if record.get("source_title") != record.get("title")
                    else ""
                ),
            }
        )
    return rows


def current_only_rows(registry: dict[str, Any]) -> list[dict[str, object]]:
    return [
        {
            "canonical_id": row.get("canonical_id"),
            "title": row.get("title"),
            "ledger_state": row.get("ledger_state"),
            "classification": row.get("classification"),
            "priority": row.get("priority", ""),
            "reason": row.get("reason", ""),
        }
        for row in registry.get("local_only_records", [])
    ]


def phase_table(registry: dict[str, Any]) -> list[dict[str, object]]:
    grouped = records_by_phase(registry)
    rows = []
    for phase in registry.get("roadmap_phases", []):
        phase_id = str(phase["phase"])
        records = grouped.get(phase_id, [])
        statuses = Counter(str(row.get("programme_status")) for row in records)
        owners = sorted({str(row.get("owner")) for row in records})
        rows.append(
            {
                "phase": phase_id,
                "title": phase["title"],
                "issue_range": phase["issue_range"],
                "record_count": len(records),
                "status_summary": ", ".join(
                    f"{status}={count}" for status, count in sorted(statuses.items())
                ),
                "owners": ", ".join(owners),
            }
        )
    return rows


def build_github_inventory() -> dict[str, object]:
    issues = command_json(
        ["gh", "issue", "list", "--repo", REPO, "--state", "all", "--limit", "1000", "--json", "number,title,state,url"]
    )
    prs = command_json(
        ["gh", "pr", "list", "--repo", REPO, "--state", "all", "--limit", "1000", "--json", "number,title,state,url,headRefName"]
    )
    if not isinstance(issues, list):
        issues = []
    if not isinstance(prs, list):
        prs = []
    return {
        "repository": REPO,
        "issue_count": len(issues),
        "open_issue_count": sum(str(row.get("state", "")).upper() == "OPEN" for row in issues),
        "closed_issue_count": sum(str(row.get("state", "")).upper() == "CLOSED" for row in issues),
        "pull_request_count": len(prs),
        "open_pull_request_count": sum(str(row.get("state", "")).upper() == "OPEN" for row in prs),
        "issues": sorted(issues, key=lambda row: int(row.get("number", 0))),
        "pull_requests": sorted(prs, key=lambda row: int(row.get("number", 0))),
        "read_only_collection": True,
    }


def phase_document(registry: dict[str, Any], phase: dict[str, Any]) -> str:
    grouped = records_by_phase(registry)
    records = grouped.get(str(phase["phase"]), [])
    lines = [
        f"# {phase['title']}",
        "",
        f"Phase `{phase['phase']}` covers `{phase['issue_range']}`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.",
        "",
        "## Objective",
        "",
        f"Deliver the bounded {phase['title'].lower()} work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.",
        "",
        "## Affected modules, schemas and UI",
        "",
        "- Confirm the existing module boundary before implementation; keep UI orchestration separate from feature, signal, model, backtest and ChatGPT bridge logic.",
        "- Keep persisted user data under `data/`, configuration under `configs/`, logs under `logs/` and optional model files under `models/`.",
        "- Extend existing schemas and reusable components only where the acceptance criteria require it; document compatibility for every schema change.",
        "",
        "## Tests and evidence",
        "",
        "- Add deterministic tests for calculations, parsing and safety gates before claiming the phase is implemented.",
        "- Cover empty, partial, stale, conflicting, provider-unavailable and permission-denied states where the phase handles those inputs.",
        "- Preserve source evidence, provenance and point-in-time boundaries in outputs and audit records.",
        "",
        "## Performance",
        "",
        "- Measure the affected local operation with representative data before and after the change.",
        "- Avoid network calls or model loading on the baseline launch path; optional Toto and TimesFM integrations must remain optional.",
        "",
        "## Security and authority",
        "",
        "- Keep the app advisory and local-first. Risk gates override forecasts, audits and UI actions.",
        "- Automatic trading remains staged, disabled and non-default. No broker automation or external upload is part of this phase.",
        "- Treat imported files, provider responses and model output as untrusted evidence; validate before use.",
        "",
        "## Migration and compatibility",
        "",
        "- Prefer additive, versioned changes with an explicit migration or compatibility path.",
        "- Do not silently mix adjusted and raw prices for returns, signals or backtests.",
        "",
        "## Blockers, dependencies and related links",
        "",
        "- Resolve only `blocking_dependencies` as prerequisites; `required_inputs` are policy/evidence inputs and do not block readiness. `downstream_issues` are generated reverse links and `related_issues` are context only.",
        "- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-17-3321ebd/dependency-reconciliation.csv`.",
        "",
        "## Issue coverage",
        "",
        "| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            "| `{id}` | `{priority}` | `{status}` | `{owner}` | {blocking} | {required} | {downstream} | {related} |".format(
                id=record["canonical_id"],
                priority=record.get("priority", ""),
                status=record.get("programme_status", ""),
                owner=record.get("owner", ""),
                blocking=", ".join(f"`{value}`" for value in record.get("blocking_dependencies", [])) or "-",
                required=", ".join(f"`{value}`" for value in record.get("required_inputs", [])) or "-",
                downstream=", ".join(f"`{value}`" for value in record.get("downstream_issues", [])) or "-",
                related=", ".join(f"`{value}`" for value in record.get("related_issues", [])) or "-",
            )
        )
    return "\n".join(lines)


def generate(root: Path, package_path: Path | None = None) -> dict[str, object]:
    baseline = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=root, text=True).strip()
    registry = build_registry(root, baseline=baseline)
    package_candidate = package_path_for(root, package_path)
    report = validate_package(package_candidate) if package_candidate.is_file() else None
    recon = root / PROGRAMME_ROOT / "reconciliation" / f"{RECONCILIATION_DATE}-{baseline[:7]}"
    rows = package_source_rows(registry)
    current_rows = current_only_rows(registry)
    cycles = raw_candidate_cycles(registry)
    blocking_edges = [
        {"from": row["canonical_id"], "to": dependency}
        for row in registry["records"]
        for dependency in row.get("blocking_dependencies", [])
    ]
    dag = {
        "schema_version": "1.0",
        "nodes": sorted(row["canonical_id"] for row in registry["records"]),
        "blocking_edges": sorted(blocking_edges, key=lambda edge: (edge["from"], edge["to"])),
        "blocking_cycle_count": 0,
        "raw_candidate_cycle_count": len(cycles),
        "raw_candidate_cycles": cycles,
        "external_or_closed_dependencies": sorted(
            {
                dependency
                for row in registry["records"]
                for dependency in row.get("dependency_candidates", [])
                if dependency not in {item["canonical_id"] for item in registry["records"]}
            }
        ),
    }
    write_csv(
        recon / "source-to-canonical.csv",
        [
            "source_record_id", "source_kind", "source_file", "source_title", "canonical_id",
            "canonical_title", "classification", "ledger_state", "package_status",
            "programme_status", "priority", "owner", "phase", "dependency_candidates",
            "blocking_dependencies", "required_inputs", "activation_dependencies", "downstream_issues", "related_issues", "discrepancy",
        ],
        rows,
    )
    write_csv(
        recon / "current-only-records.csv",
        ["canonical_id", "title", "ledger_state", "classification", "priority", "reason"],
        current_rows,
    )
    write_csv(
        recon / "dependency-reconciliation.csv",
        ["source_id", "dependency", "candidate_type", "resolved_as", "reason"],
        registry.get("dependency_reconciliation", []),
    )
    ownership: dict[str, dict[str, object]] = {}
    for record in registry["records"]:
        owner = str(record.get("owner", ""))
        row = ownership.setdefault(
            owner,
            {
                "owner": owner,
                "record_count": 0,
                "open_count": 0,
                "closed_count": 0,
                "proposed_count": 0,
                "phases": set(),
            },
        )
        row["record_count"] = int(row["record_count"]) + 1
        row["open_count"] = int(row["open_count"]) + (record.get("ledger_state") == "open")
        row["closed_count"] = int(row["closed_count"]) + (record.get("ledger_state") == "closed")
        row["proposed_count"] = int(row["proposed_count"]) + (
            record.get("classification") == "proposed_new"
        )
        row["phases"].add(str(record.get("phase")))
    ownership_rows = []
    for row in sorted(ownership.values(), key=lambda value: str(value["owner"])):
        ownership_rows.append(
            {
                **row,
                "phases": ";".join(sorted(row["phases"])),
            }
        )
    write_csv(
        recon / "ownership.csv",
        ["owner", "record_count", "open_count", "closed_count", "proposed_count", "phases"],
        ownership_rows,
    )
    write_json(recon / "canonical-dag.json", dag)

    package_sha = (
        report.package_sha256
        if report is not None
        else str(registry["source_of_truth"].get("package_sha256", ""))
    )
    current_package_ids = sorted(
        row["canonical_id"] for row in registry["records"] if row.get("source_kind") == "current"
    )
    open_package_ids = sorted(
        row["canonical_id"] for row in registry["records"]
        if row.get("source_kind") == "current" and row.get("ledger_state") == "open"
    )
    closed_package_ids = sorted(
        row["canonical_id"] for row in registry["records"]
        if row.get("source_kind") == "current" and row.get("ledger_state") == "closed"
    )
    open_ledger_ids = sorted(
        re.findall(r"(?m)^##\s+((?:ISSUE|UPDATEV2)-\d{4})\s+-", (root / "issues/open.md").read_text(encoding="utf-8"))
    )
    closed_index_ids = sorted(
        re.findall(r"(?m)^\|\s+`((?:ISSUE|UPDATEV2)-\d{4})`\s+\|", (root / CLOSED_LEDGER).read_text(encoding="utf-8"))
    )
    package_discrepancies = f"""# Package reconciliation discrepancies

The supplied package is immutable evidence. It is archived under `docs/product-completion/sources/2026-07-15/` and is not committed as a binary ZIP. Its external SHA-256 is `{package_sha}`; the member hashes are recorded in `SOURCE_MANIFEST.sha256`.

## Snapshot and ledger differences

- Package reviewed commit: `{registry['source_of_truth']['package_reviewed_commit']}`.
- Reconciliation baseline: `{baseline}` (`origin/main`).
- Package current records: `{len(current_package_ids)}`; latest canonical open headings: `{len(open_ledger_ids)}`.
- Current package records now closed by the canonical closed index: {', '.join(f'`{value}`' for value in closed_package_ids) or 'none'}.
- Local-only current/closed records are listed in `current-only-records.csv`; no identifiers were renumbered.
- Stale open sections for `ISSUE-0069`, `UPDATEV2-0010` and `UPDATEV2-0022` were removed. `ISSUE-0067` remains open. The full `UPDATEV2-0010` record is preserved in `issues/closed.md`.

## Dependency and structure differences

- Raw package candidate graph cycles: `{len(cycles)}`. The canonical blocking graph contains zero cycles; converted candidates and reasons are recorded in `dependency-reconciliation.csv`.
- External or historical dependency references are retained as related context; `UPDATEV2-0028` is the known package reference outside the package snapshot.
- The current router exposes `{len(route_inventory(root))}` registered routes. This is recorded as source evidence because the supplied plan's earlier route estimate was lower; no routes were removed in this documentation task.

## Scope boundary

This change implements package validation, archival, reconciliation, canonical registry/roadmap documents and safe synchronisation tooling only. It does not implement product features, broker automation, external uploads or cloud services.
"""
    write_text(recon / "package-discrepancies.md", package_discrepancies)

    route_list = route_inventory(root)
    current_state = f"""# Current-state diff and implementation inventory

Baseline: `{baseline}`. This inventory is evidence for sequencing, not a claim that product features were implemented by this task.

## Application entry points and packaging

- The existing desktop/local application remains the launch surface. Keep startup baseline-safe and do not require optional provider or model packages.
- The repository retains its existing scripts and packaging conventions. New programme tooling is standard-library Python and writes only visible, deterministic artefacts.

## Navigation and workflow state

`src/etf_cockpit/app/router.py` currently registers **{len(route_list)}** routes: {', '.join(f'`{route}`' for route in route_list)}. The count is higher than the plan's earlier estimate; this reconciliation records the source-of-truth count without altering routing.

The existing app state, onboarding, diagnostics, data-health, evidence and decision-journal surfaces should remain separate from feature calculations and provider/model bridges. Any later implementation must preserve default, loading, empty, partial, error, disabled and permission-denied states.

## Persistence, schemas and price policy

Existing persistence and configuration boundaries are retained. New user data belongs under `data/`, configs under `configs/`, logs under `logs/` and model files under `models/`. Return, signal and backtest work must use adjusted prices consistently and identify the price basis in evidence.

## Providers, evidence, scores and models

Provider results, filings, ETF disclosures, news context and model outputs are evidence inputs rather than authority. Toto and TimesFM remain optional. Baseline signals must still run without model packages or weights, and conflict/provenance handling must remain visible.

## Backtests, portfolio and authority

Backtests and portfolio analysis remain advisory. Risk gates override forecasts, audits and UI actions. Automatic trading is staged, disabled and non-default; this task adds no broker integration or execution path.

## Known limitations to carry into later implementation

- Point-in-time data completeness, holdings/transaction-cost fidelity and provider quotas require explicit evidence before certification.
- Static source inspection confirms the route inventory, but this documentation task does not claim runtime visual or performance certification.
- Performance work must measure refresh, cache, backtest and model operations with representative data; no training or inference target is invented here.
"""
    write_text(recon / "current-state-diff.md", current_state)

    inventory = build_github_inventory()
    worktrees = worktree_inventory(root)
    intake = {
        "schema_version": "1.0",
        "repository": REPO,
        "baseline_commit": baseline,
        "worktree": str(root),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip(),
        "worktree_inventory": worktrees,
        "package": {
            "path": str(package_candidate) if package_candidate.is_file() else "unavailable",
            "sha256": package_sha,
            "reviewed_commit": registry["source_of_truth"]["package_reviewed_commit"],
            "member_hashes": report.member_hashes if report is not None else {},
            "validation": (
                report.as_dict()
                if report is not None
                else {
                    "status": "archived_sources_only",
                    "valid": None,
                    "errors": [],
                    "warnings": [
                        "External ZIP was unavailable; checked-in extracted sources and manifest remain canonical evidence."
                    ],
                }
            ),
            "archived_directory": "docs/product-completion/sources/2026-07-15",
        },
        "latest_ledgers": {
            "open_heading_count": len(open_ledger_ids),
            "closed_index_count": len(closed_index_ids),
            "package_current_open_ids": open_package_ids,
            "package_current_closed_ids": closed_package_ids,
            "local_only_records": current_rows,
        },
        "github_inventory": {
            "issue_count": inventory["issue_count"],
            "open_issue_count": inventory["open_issue_count"],
            "closed_issue_count": inventory["closed_issue_count"],
            "pull_request_count": inventory["pull_request_count"],
            "open_pull_request_count": inventory["open_pull_request_count"],
            "collection_method": "read-only gh issue/pr list",
        },
        "safety": {
            "product_features_implemented": False,
            "broker_automation": False,
            "external_uploads": False,
            "optional_providers_and_models": True,
            "zip_committed": False,
            "github_writes_from_generator": False,
        },
    }
    write_json(recon / "intake-report.json", intake)
    write_json(recon / "github-inventory.json", inventory)
    write_text(
        recon / "README.md",
        f"""# Completion-programme reconciliation

This directory is the deterministic reconciliation record for baseline `{baseline}` on `{intake['branch']}`.

## Contents

- `intake-report.json` - repository, worktree, package, ledger and read-only GitHub inventory.
- `github-inventory.json` - read-only issue and pull-request inventory.
- `source-to-canonical.csv` - one row for every package record and its classification.
- `current-only-records.csv` - canonical local records absent from the older package snapshot.
- `ownership.csv` - deterministic owner/phase counts.
- `dependency-reconciliation.csv` - candidate dependency classifications and cycle conversions.
- `canonical-dag.json` - acyclic blocking graph plus documented raw candidate cycles.
- `package-discrepancies.md` - package/ledger differences and scope boundaries.
- `current-state-diff.md` - current application inventory and limitations.
- `github-sync-plan.json` and `github-sync-review.md` - safe dry-run action manifest and review record.

The supplied ZIP is immutable external evidence. It is archived as nine extracted members under `docs/product-completion/sources/2026-07-15/`; the binary ZIP is not committed. No product feature, broker automation, external upload or cloud service was implemented by this task.
""",
    )

    programme = root / PROGRAMME_ROOT / "programme"
    table = phase_table(registry)
    roadmap_lines = [
        "# ETF AI Cockpit completion roadmap",
        "",
        "This roadmap is the lightweight programme view. `issues/issue_registry.json` owns issue identity, title, priority, state, acceptance criteria and dependencies; phase documents own implementation guidance.",
        "",
        "## Guardrails",
        "",
        "- Local-first and advisory by default; no broker automation, external upload or cloud service is introduced.",
        "- Risk gates override model forecasts, audits and UI actions.",
        "- Adjusted prices are required for returns, signals and backtests.",
        "- Toto and TimesFM are optional; baseline signals must work without their packages or weights.",
        "- GitHub synchronisation is dry-run by default and apply requires a reviewed plan checksum.",
        "",
        "## Phase order",
        "",
        "| Phase | Coverage | Records | State summary | Owners |",
        "|---|---|---:|---|---|",
    ]
    for row in table:
        roadmap_lines.append(
            f"| `{row['phase']}` | `{row['issue_range']}` - {row['title']} | {row['record_count']} | {row['status_summary']} | {row['owners']} |"
        )
    roadmap_lines.extend(
        [
            "",
            "## Phase mapping",
            "",
            "1. Scope and governance - `phase-01-governance-scope`.",
            "2. Architecture and storage - `phase-01-governance-scope` / `phase-02-data-policy-identity`.",
            "3. Local data and identity - `phase-02-data-policy-identity`.",
            "4. Stock research - `phase-03-stock-research`.",
            "5. ETF research - `phase-04-etf-research`.",
            "6. Returns and risk - `phase-05-returns-risk-portfolio`.",
            "7. Model governance - `phase-06-model-research`.",
            "8. Event and backtest evidence - `phase-07-backtest-paper-execution`.",
            "9. Paper trading and execution safety - `phase-07-backtest-paper-execution`.",
            "10. Frontend and local API - `phase-08-frontend-api`.",
            "11. Quality and release - `phase-09-quality-release-security`.",
            "12. Security, resilience, audit, documentation and bias controls - `phase-09-quality-release-security` / `phase-10-audit-documentation-governance`.",
            "13. Certification - `phase-11-certification`.",
            "",
            "## Completion evidence",
            "",
            "A phase is complete only when its deterministic tests, safety gates, evidence/provenance checks, compatibility path and reviewable diff are present. Product implementation is intentionally outside this reconciliation task.",
            "",
        ]
    )
    write_text(programme / "roadmap.md", "\n".join(roadmap_lines))

    order_lines = [
        "# Implementation order",
        "",
        "Follow the phase order below. Within a phase, resolve `blocking_dependencies` before implementation; treat `related_issues` as context only.",
        "",
    ]
    for index, row in enumerate(table, start=1):
        order_lines.append(f"{index}. **{row['phase']}** - {row['title']} ({row['issue_range']}; {row['record_count']} records).")
    order_lines.extend(
        [
            "",
            "The canonical blocking graph is available as `docs/product-completion/reconciliation/2026-07-17-3321ebd/canonical-dag.json`. Cyclic raw candidates were converted to related references with reasons rather than silently dropped.",
            "",
        ]
    )
    write_text(programme / "implementation-order.md", "\n".join(order_lines))

    write_text(
        programme / "test-and-performance-strategy.md",
        """# Test and performance strategy

## Required test layers

- Deterministic unit tests for calculations, parsers, schema joins, adjusted-price handling and risk gates.
- Failure-path tests for missing data, provider conflicts, unavailable optional models, malformed imports, stale evidence and authority-denied actions.
- Focused registry/package/synchronisation tests for byte freshness, stable IDs, DAG validity, dry-run safety, duplicate markers and managed-body preservation.
- Targeted application tests for each changed module, followed by the repository's proportionate lint, compile and smoke checks.

## Performance evidence

Measure representative local startup, cache read/write, refresh, screening, backtest and model operations. Record dataset shape, provider mode, cache state and machine context. Do not claim latency or throughput targets without a measurement.

## Release gates

Run deterministic tests and safety gates before user-visible claims. Optional Toto and TimesFM paths must not be required for launch. Keep execution disabled unless a later explicitly authorised milestone changes that policy with independent safety evidence.
""",
    )
    write_text(
        programme / "git-workflow.md",
        f"""# Git workflow

- Working branch: `{intake['branch']}`.
- Base: `{baseline}` (`origin/main`).
- Worktree: `{root}`.
- Keep the primary checkout and its unrelated untracked files untouched.
- Review `git diff`, run targeted checks, commit the focused change, then use capability-based GitHub checks before any push or issue apply.
- Do not commit the supplied ZIP; commit the archived extracted members, manifest, registry, documents, scripts and tests.
- GitHub Issue apply is permitted only with an approved plan SHA-256 and must read back the resulting state.
""",
    )
    write_text(
        programme / "prompt-2-handoff.md",
        """# Prompt 2 handoff

Start from `issues/issue_registry.json` and `docs/product-completion/programme/roadmap.md`. Read the relevant phase document before implementing product work. Treat the reconciliation report as the evidence boundary: the package is immutable, local-only historical records are explicit, dependencies are classified, and no product feature was implemented by Prompt 1.

First implementation candidates are the records marked `ready` by the registry helper, subject to their blocking dependencies and the local-first safety policy. Re-run `python scripts/generate_issue_registry.py --check`, `python scripts/update_programme_status.py --check` and the focused tests after changes.
""",
    )
    phases = programme / "phases"
    for phase in registry.get("roadmap_phases", []):
        write_text(phases / f"{phase['phase']}.md", phase_document(registry, phase))
    write_json(
        programme / "readiness.json",
        {
            "schema_version": "1.0",
            "source_registry_sha256": __import__("hashlib").sha256(
                deterministic_json(registry)
            ).hexdigest(),
            "execution_allowed": False,
            "decisions": registry.get("readiness", []),
        },
    )
    write_managed_section(
        root / "README.md",
        "FINAL RELEASE PROGRAMME",
        """## Final-release programme

ETF AI Cockpit is a private, local-first decision-support application. The adopted programme covers core stock, ETF, ordinary-fund and supported fixed-income research; reproducible bulk/top-N analysis; selected-currency outputs; five editable risk-profile projections; and Quick/Medium/High/Full analysis depths. These are programme contracts, not a claim that every capability is certified today.

The canonical registry and current evidence live in `issues/issue_registry.json` and `docs/product-completion/CURRENT_STATUS.json`. Missing providers, keys, optional models, weights or network access must remain explicit unavailable states and must not prevent safe local startup. Returns require adjusted, corporate-action-aware total-return data and point-in-time evidence.

Live execution is not authorised: `execution_allowed=false`. Portfolio, paper, broker-read-only and disabled canary scaffolding have separate certification/activation lanes and cannot gain authority from a model, LLM, UI action or programme status.

Canonical checks: `python scripts/generate_issue_registry.py --check`, `python scripts/validate_issue_registry.py`, `python scripts/update_programme_status.py --check`, `python scripts/validate_app.py --changed`, and `python scripts/validate_app.py --offline`. Full/package certification is delegated to the existing protected release gate through `validate_app.py --full` and `--packaged`.""",
    )
    write_managed_section(
        root / "CHANGELOG.md",
        "FINAL RELEASE CONTROL PLANE",
        """## 2026-07-21 — Final-release control-plane intake

- Adopted the versioned final-release specification and provisional collision-free `ISSUE-0153`–`ISSUE-0176` contracts without implementing their downstream product features.
- Added typed, status-independent dependency-edge readiness, separate activation readiness, dynamic registry/phase/count validation, and deterministic source-derived programme projections.
- Preserved `execution_allowed=false`; no GitHub apply, live order, deployment, publication or release action is part of this change.""",
    )
    return {
        "reconciliation": str(recon),
        "package_sha256": package_sha,
        "github_issue_count": inventory["issue_count"],
        "phase_count": len(registry.get("roadmap_phases", [])),
        "raw_candidate_cycle_count": len(cycles),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--package", type=Path)
    args = parser.parse_args(argv)
    result = generate(args.root.resolve(), args.package)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
