"""Read-only programme navigation: canonical readiness is not execution authority.

No network, canonical mutation, worker launch, evidence certification or merge.
The caller fetches main and supplies fresh local ownership observations.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import Any

try:
    from scripts.issue_registry_core import (
        build_registry, deterministic_json, parse_open_ledger, parse_closed_index,
        validate_registry, render_open_ledger_with_final_release,
    )
    from scripts.active_work import validate_lanes
except ModuleNotFoundError:
    from issue_registry_core import (
        build_registry, deterministic_json, parse_open_ledger, parse_closed_index,
        validate_registry, render_open_ledger_with_final_release,
    )
    from active_work import validate_lanes

SCHEMA = "programme-execution.v1"
FINISHED = frozenset({"integrated", "closed"})
IMPLEMENTABLE = frozenset({"planned", "ready", "in_progress", "implemented", "implemented_initially", "hardening_required"})
PRIORITY = {name: position for position, name in enumerate(("P0", "P0/P1", "P1", "P1/P2", "P2", "P3"))}
INDEX = "docs/development/work-index.json"
SHA = re.compile(r"[0-9a-f]{40}")


def read_json(path: Path) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + value)))


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=root, text=True, stderr=subprocess.PIPE).strip()


def ancestor(root: Path, parent: str, child: str) -> bool:
    if not SHA.fullmatch(parent) or not SHA.fullmatch(child):
        raise ValueError("Expected exact Git identities")
    result = subprocess.run(["git", "merge-base", "--is-ancestor", parent, child], cwd=root, capture_output=True)
    if result.returncode not in (0, 1):
        raise ValueError(f"Missing Git ancestry objects: {parent}..{child}")
    return result.returncode == 0


def graph_properties(records: dict[str, dict]) -> tuple[dict[str, set[str]], dict[str, int], list[list[str]]]:
    """Deterministic Kahn waves; no activation/related edges silently become blockers."""
    pending = {key: set(value["blocking_dependencies"]) for key, value in records.items()}
    for key, parents in pending.items():
        if key in parents or parents - records.keys():
            raise ValueError(f"Invalid blocking edge: {key}")
    waves = []
    done: set[str] = set()
    while pending:
        wave = sorted(key for key, parents in pending.items() if parents <= done)
        if not wave:
            raise ValueError("Blocking dependency cycle: " + ", ".join(sorted(pending)))
        waves.append(wave)
        done.update(wave)
        for key in wave:
            del pending[key]
    descendants = {key: set() for key in records}
    depth = {key: 0 for key in records}
    for wave in reversed(waves):
        for key in wave:
            for parent in records[key]["blocking_dependencies"]:
                descendants[parent].update({key} | descendants[key])
                depth[parent] = max(depth[parent], depth[key] + 1)
    return descendants, depth, waves


def load_work_index(root: Path, main: str) -> dict[str, list[dict]]:
    """Historical locators, not current PR status, acceptance or ownership."""
    source = read_json(root / INDEX)
    if source.get("schema_version") != "programme-work-locators.v1" or source.get("apply_authority") is not False:
        raise ValueError("Invalid historical work index")
    result: dict[str, list[dict]] = {}
    for item in source["items"]:
        if set(item) != {"issue_ids", "pr", "branch", "head", "merge", "purpose"}:
            raise ValueError("Work locators cannot contain status or ownership authority")
        if ((item["pr"] is not None and (type(item["pr"]) is not int or item["pr"] < 1))
                or not isinstance(item["head"], str) or not SHA.fullmatch(item["head"])
                or (item["pr"] is None and not item["branch"])):
            raise ValueError("Invalid historical work locator")
        if item["branch"] is not None:
            if not isinstance(item["branch"], str) or subprocess.run(
                    ["git", "check-ref-format", "refs/heads/" + item["branch"]],
                    capture_output=True).returncode != 0:
                raise ValueError("Invalid historical branch locator")
        if item["merge"] is not None and not SHA.fullmatch(item["merge"]):
            raise ValueError("Invalid merge locator")
        try:
            merged_head_valid = (not item["merge"] or ancestor(root, item["head"], item["merge"])
                                 or git(root, "rev-parse", item["head"] + "^{tree}")
                                 == git(root, "rev-parse", item["merge"] + "^{tree}"))
            present = ancestor(root, item["merge"] or item["head"], main)
            observation = "ancestor_of_observed_main" if present else "candidate_not_integrated_by_ancestry"
        except ValueError:
            observation = "missing_git_objects_preserve_and_fetch"
        else:
            if not merged_head_valid:
                raise ValueError("Locator head has neither ancestry nor exact tree identity with claimed merge")
        entry = {**item, "git_observation": observation, "acceptance": "NOT_ESTABLISHED_BY_LOCATOR"}
        for key in item["issue_ids"]:
            if not re.fullmatch(r"(?:ISSUE|UPDATEV2)-\d{4}", key):
                raise ValueError("Invalid issue locator")
            result.setdefault(key, []).append(entry)
    return result


def contract_diagnostics(registry: dict) -> list[dict]:
    """Expose source/parser disagreement without inventing migration authority.

    Compact source metadata is semicolon-delimited. Downstream consumers must
    never become upstream blockers merely because both appear on the same line.
    Existing canonical edges remain enforced until the guarded repair is reviewed.
    """
    findings = []
    for record in registry["records"]:
        text = record.get("contract_markdown", "")
        line = re.search(r"(?m)^\*\*Canonical metadata:\*\*\s*(.+)$", text)
        if not line or "; downstream " not in line[1]:
            continue
        match = re.search(r"\bdepends on\s+([^;]+)", line[1])
        if not match:
            continue
        try:
            from scripts.issue_registry_core import parse_issue_refs_expanded
        except ModuleNotFoundError:
            from issue_registry_core import parse_issue_refs_expanded
        intended = set(parse_issue_refs_expanded(match[1]))
        actual = set(record["blocking_dependencies"])
        if actual != intended:
            findings.append({"issue": record["canonical_id"],
                "code": "COMPACT_SOURCE_DEPENDENCY_BOUNDARY_MISMATCH",
                "source_dependencies": sorted(intended), "canonical_dependencies": sorted(actual),
                "unexpected_blockers": sorted(actual - intended), "missing_blockers": sorted(intended - actual),
                "source_reference": record["provenance"]["primary_source"],
                "required_action": "Root-reviewed canonical/parser and GitHub-projection migration; do not waive edges, fabricate review, or edit generated state."})
    return sorted(findings, key=lambda item: item["issue"])


def build_plan(registry: dict, work: dict[str, list[dict]] | None = None) -> dict:
    records = {item["canonical_id"]: item for item in registry["records"]}
    readiness = {item["issue_id"]: item for item in registry["readiness"]}
    if len(records) != len(registry["records"]) or len(readiness) != len(registry["readiness"]) or set(records) != set(readiness):
        raise ValueError("Missing or duplicate canonical/readiness records")
    phases = {phase["phase"]: number for number, phase in enumerate(registry["roadmap_phases"])}
    if len(phases) != len(registry["roadmap_phases"]):
        raise ValueError("Duplicate phase identity")
    descendants, depth, waves = graph_properties(records)
    unfinished = {key for key, value in records.items() if value["programme_status"] not in FINISHED and value["ledger_state"] != "closed"}
    work = work or {}
    ready, blocked, excluded = [], [], []
    for key in sorted(unfinished):
        record, decision = records[key], readiness[key]
        if record["phase"] not in phases or record["priority"] not in PRIORITY:
            raise ValueError(f"Unknown phase/priority: {key}")
        if decision.get("execution_allowed") is not False or type(decision.get("ready")) is not bool:
            raise ValueError(f"Invalid readiness/authority: {key}")
        locators = work.get(key, [])
        merged = any(item["merge"] and item["git_observation"] == "ancestor_of_observed_main" for item in locators)
        route = "verify_merged_product_lifecycle" if merged else "inspect_existing_candidate" if locators else "implementation_preflight"
        entry = {
            "issue": key, "title": record["title"], "phase": record["phase"],
            "priority": record["priority"], "status": record["programme_status"],
            "work_kind": route, "required_inputs": record["required_inputs"],
            "activation_dependencies": record["activation_dependencies"],
            "unfinished_descendants": len(descendants[key] & unfinished),
            "graph_depth": depth[key], "work_references": locators,
        }
        if record["programme_status"] not in IMPLEMENTABLE:
            excluded.append({**entry, "reason": "LIFECYCLE_NOT_IMPLEMENTATION_ELIGIBLE", "dependency_ready": decision["ready"]})
        elif not decision["ready"]:
            edges = [edge for edge in decision["edges"] if edge["resolved"] is not True]
            blocked.append({**entry, "reason_codes": decision["reason_codes"], "edges": edges,
                            "evidence_only": bool(edges) and all(records[e["dependency_id"]]["programme_status"] in FINISHED for e in edges)})
        else:
            # Observed existing work reduces duplicate coding, never lowers any gate.
            stage = 0 if merged else 1 if locators else 2
            entry["rank"] = [phases[record["phase"]], stage, PRIORITY[record["priority"]], -entry["unfinished_descendants"], -depth[key], key]
            ready.append(entry)
    ready.sort(key=lambda item: item["rank"])
    blocked.sort(key=lambda item: (phases[item["phase"]], item["issue"]))
    # Future waves are topology only. They are NOT ownership-safe dispatch waves.
    conditional = [[key for key in wave if key in unfinished and records[key]["programme_status"] in IMPLEMENTABLE] for wave in waves]
    return {
        "schema_version": SCHEMA, "execution_allowed": False, "apply_authority": False,
        "counts": {"records": len(records), "incomplete": len(unfinished), "ready_candidates": len(ready),
                   "blocked": len(blocked), "excluded": len(excluded), "statuses": dict(sorted(Counter(v["programme_status"] for v in records.values()).items()))},
        "contract_diagnostics": contract_diagnostics(registry),
        "ranking_policy": "phase; merged-product verification; preserved candidate; priority; unfinished descendants; graph depth; ID",
        "now": ready[0]["issue"] if ready else None,
        "next": ready[1]["issue"] if len(ready) > 1 else None,
        "ready": ready, "blocked": blocked, "excluded": excluded,
        "conditional_dependency_waves": [wave for wave in conditional if wave],
        "wave_caveat": "Topology, not dispatch: every edge still needs canonical evidence, lifecycle eligibility, contract feasibility and exclusive ownership. Activation remains disabled.",
        "bottlenecks": sorted(({
            "issue": key, "unfinished_descendants": len(descendants[key] & unfinished), "graph_depth": depth[key],
        } for key in unfinished), key=lambda item: (-item["unfinished_descendants"], -item["graph_depth"], item["issue"])),
    }


def harness(root: Path, live_skill: Path | None = None) -> dict:
    subprocess.run([sys.executable, str(root / "docs/codex-config/agent_routing.py"), "--source-only"], cwd=root, check=True, capture_output=True)
    config = tomllib.loads((root / "docs/codex-config/config-core.toml").read_text())
    roles = {path.stem: {"model": value["model"], "effort": value["model_reasoning_effort"]}
             for path in sorted((root / "docs/codex-config/agents").glob("*.toml"))
             for value in [tomllib.loads(path.read_text())]}
    tree = ast.parse((root / "docs/codex-config/agy_delegate.py").read_text())
    states = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "CAPABILITY_STATES" for target in node.targets)]
    if len(states) != 1 or len(roles) != 12:
        raise ValueError("Unknown reviewed harness structure")
    skill = {"status": "LOCAL_LIVE_HASHES_NOT_OBSERVED"}
    if live_skill is not None:
        def hashes(directory: Path) -> dict[str, str]:
            if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
                raise ValueError("Skill root must be an explicit real absolute directory")
            result = {}
            for path in sorted(directory.rglob("*")):
                if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                    raise ValueError("Skill contains a link/reparse point")
                if path.is_file():
                    result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            return result
        source = hashes(root / "docs/codex-config/codex-skills/antigravity-flash")
        live = hashes(live_skill)
        skill = {"status": "MATCH" if source == live else "DRIFT_PRESERVE_UNEXPECTED_CONTENT", "source": source, "live": live}
    return {"root": {"model": config["model"], "effort": config["model_reasoning_effort"]},
            "child_ceiling": config["agents"]["max_concurrent_threads_per_session"], "roles": roles,
            "agy_source_capabilities": states[0], "editor_route": "disposable-worktree-whole-candidate-promotion",
            "skill": skill, "live_codex_runtime": "UNVERIFIED_BY_REPOSITORY_SNAPSHOT"}


def issue_card(root: Path, registry: dict, key: str, work: dict) -> dict:
    matches = [record for record in registry["records"] if record["canonical_id"] == key]
    if len(matches) != 1:
        raise ValueError(f"Unknown issue: {key}")
    ledger = parse_open_ledger(root / "issues/open.md")
    return {"canonical_record": matches[0], "readiness": next(d for d in registry["readiness"] if d["issue_id"] == key),
            "source_ledger_section": ledger.get(key, {}).get("section", "See immutable source/closed ledger in canonical provenance."),
            "historical_work_locators": work.get(key, []),
            "contract_diagnostics": [item for item in contract_diagnostics(registry) if item["issue"] == key],
            "warning": "All required changes and normative amendments remain binding; initial implementation and PR merge are not completion. Related issues/required inputs are not silently blocking edges."}


def evidence_state(root: Path, main: str, head: str, dirty: bool) -> dict:
    try:
        from scripts.classify_validation import _load_base_reusable_evidence, derive_trusted_evidence, build_report
    except ModuleNotFoundError:
        from classify_validation import _load_base_reusable_evidence, derive_trusted_evidence, build_report
    reasons: list[str] = []
    source = _load_base_reusable_evidence(root, base=main, head=head, path=Path(".github/issue-transitions/reuse-evidence.json"))
    expected = derive_trusted_evidence(root, base=main, head=head,
            artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json", reusable_evidence=source, diagnostics=reasons)
    try:
        from scripts.git_change_paths import changed_paths
    except ModuleNotFoundError:
        from git_change_paths import changed_paths
    from_paths = changed_paths(root, main, head)
    report = build_report(from_paths, reusable_evidence=source, expected_evidence=expected)
    if source is not None and expected is not None and source != expected:
        reasons.append("recorded_identity_does_not_match_recomputed_identity")
    if dirty:
        reasons.append("working_tree_not_frozen")
    return {"authorized": not dirty and report["evidence_reuse"]["authorized"],
            "reasons": reasons or [report["evidence_reuse"]["reason"]],
            "tier": report["tier"], "package_gate_required": report["package_gate_required"],
            "reviewed_source_head": source.get("head_sha") if source else None,
            "authority": "existing classifier and exact source evidence only; this is a read-only projection"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--issue")
    parser.add_argument("--lanes", type=Path)
    parser.add_argument("--live-skill", type=Path)
    parser.add_argument("--pulls", type=Path, help="fresh root-observed PR identity snapshot for allocated PR lanes")
    parser.add_argument("--check", action="store_true", help="also run the complete existing atomic generation freshness check")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        remote = git(root, "remote", "get-url", "origin")
        if remote.removesuffix(".git").rstrip("/").lower() not in {
            "https://github.com/thor2709/etf_ai_cockpit", "git@github.com:thor2709/etf_ai_cockpit"}:
            raise ValueError("Wrong repository remote; no unrelated repository may be changed")
        head, main_sha = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "origin/main")
        if not ancestor(root, main_sha, head):
            raise ValueError("Checkout does not descend from observed origin/main")
        registry = build_registry(root)
        errors = validate_registry(registry, open_ids=set(parse_open_ledger(root / "issues/open.md")), closed_ids=set(parse_closed_index(root / "issues/closed.md")))
        if errors:
            raise ValueError("; ".join(errors))
        if (root / "issues/issue_registry.json").read_bytes() != deterministic_json(registry) or (root / "issues/open.md").read_bytes() != render_open_ledger_with_final_release(root):
            raise ValueError("Stale generated registry/ledger; use the existing atomic generator")
        if args.check:
            subprocess.run([sys.executable, "scripts/generate_programme.py", "--root", str(root), "--check"], cwd=root, check=True, stdout=sys.stderr)
        work = load_work_index(root, main_sha)
        if args.issue:
            print(json.dumps(issue_card(root, registry, args.issue, work), indent=2, sort_keys=True))
            return 0
        report = build_plan(registry, work)
        dirty = bool(git(root, "status", "--porcelain"))
        checksum = hashlib.sha256(deterministic_json(registry)).hexdigest()
        common = Path(git(root, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = (root / common).resolve()
        lane_path = args.lanes or common / "etf-control/active-work.json"
        lanes = read_json(lane_path) if lane_path.exists() else None
        report["git"] = {"head": head, "observed_main": main_sha, "dirty": dirty,
                         "fetch_freshness": "caller_must_fetch_before_invocation", "programme_sha256": checksum}
        report["harness"] = harness(root, args.live_skill)
        report["ownership"] = validate_lanes(lanes, report, main_sha, checksum, root=root,
                child_ceiling=report["harness"]["child_ceiling"], pulls=read_json(args.pulls) if args.pulls else None)
        report["evidence_reuse"] = evidence_state(root, main_sha, head, dirty)
        report["dispatch_authority"] = False
        report["operational_preflight"] = "CLEAN_MAIN" if head == main_sha and not dirty else "PREVIEW_ONLY_NOT_CLEAN_MAIN"
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"Main: {main_sha}\nHEAD: {head} ({report['operational_preflight']})")
            print(f"NOW: {report['now']}\nNEXT: {report['next']}")
            for item in report["ready"][:6]:
                print(f"  {item['issue']} [{item['phase']}, {item['priority']}] {item['work_kind']}")
            print(f"BLOCKED: {len(report['blocked'])}; evidence-only: {sum(x['evidence_only'] for x in report['blocked'])}; excluded lifecycle: {len(report['excluded'])}")
            print("SOURCE CONTRACT DIAGNOSTICS: " + str(len(report["contract_diagnostics"])) + " (see --json; no automatic edge mutation)")
            print("PARALLEL: " + json.dumps(report["ownership"]["parallel_waves"]))
            print("OWNERSHIP: " + report["ownership"]["status"])
            print("EVIDENCE REUSE: " + json.dumps(report["evidence_reuse"]))
            print("Details: --issue ID; --json for all blockers, conditional waves, roles and evidence locators.")
        return 1 if report["ownership"]["status"] == "BLOCKED_INVALID_OR_STALE_OWNERSHIP" else 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
