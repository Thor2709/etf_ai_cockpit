"""Control-plane regression fixtures; no network, personal accounts or live authority."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts import active_work as lanes
from scripts import classify_validation as classifier
from scripts import programme_execution as execution
from scripts import validate_app
from scripts.git_change_paths import changed_paths, working_paths
from scripts.validation_identity import identity_groups

ROOT = Path(__file__).resolve().parents[1]
MAIN = "a" * 40
PROGRAMME = "b" * 64


def run(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.PIPE).strip()


def commit(root: Path, message: str) -> str:
    run(root, "add", ".")
    run(root, "commit", "-qm", message)
    return run(root, "rev-parse", "HEAD")


def initialise(root: Path) -> None:
    run(root, "init", "-q")
    run(root, "config", "user.name", "Control fixture")
    run(root, "config", "user.email", "fixture@example.invalid")
    run(root, "config", "core.autocrlf", "false")


def mini_registry() -> dict:
    records, readiness = [], []
    for number in range(1, 7):
        key = f"ISSUE-{number:04d}"
        deps = ["ISSUE-0001"] if number == 3 else []
        status = {4: "research_only", 5: "blocked", 6: "integrated"}.get(number, "planned")
        records.append({"canonical_id": key, "title": key, "phase": "phase-01", "priority": "P1", "programme_status": status,
                        "ledger_state": "open", "blocking_dependencies": deps, "required_inputs": [], "activation_dependencies": []})
        readiness.append({"issue_id": key, "ready": number != 3, "execution_allowed": False,
                          "reason_codes": ["FIXTURE"], "edges": [{"dependency_id": parent, "resolved": False, "reason_code": "MISSING_EDGE_EVIDENCE"} for parent in deps]})
    return {"records": records, "readiness": readiness, "roadmap_phases": [{"phase": "phase-01"}]}


def lane(number: int, **updates) -> dict:
    value = {"lane_id": f"lane-{number}", "issue": f"ISSUE-{number:04d}", "branch": f"codex/lane-{number}",
             "worktree": f"/tmp/control-fixture/lane-{number}", "base": MAIN, "head": MAIN, "pr": None,
             "writer": "codex-v2", "state": "planned", "owned_paths": [f"src/module{number}.py"],
             "owned_tests": [f"tests/test_module{number}.py"], "runtime_roots": [f"/tmp/control-fixture/runtime-{number}"],
             "ports": [], "resources": [], "blocker": "", "next_action": "Root verifies source and exact acceptance criteria."}
    value.update(updates)
    return value


def manifest(*items, **updates) -> dict:
    value = {"schema_version": lanes.SCHEMA, "observed_main": MAIN, "programme_sha256": PROGRAMME,
             "root_session": "fixture-root", "all_active_writers_reconciled": True,
             "children_in_use": 0, "reviewers_running": 0, "lanes": list(items)}
    value.update(updates)
    return value


def validate(value: object, **kwargs) -> dict:
    return lanes.validate_lanes(value, execution.build_plan(mini_registry()), MAIN, PROGRAMME, root=None, child_ceiling=6, **kwargs)


def test_ready_is_not_lifecycle_eligibility_and_activation_never_enables_execution() -> None:
    registry = mini_registry()
    registry["records"][1]["activation_dependencies"] = ["ISSUE-0005"]
    report = execution.build_plan(registry)
    assert [row["issue"] for row in report["ready"]] == ["ISSUE-0001", "ISSUE-0002"]
    assert {row["issue"] for row in report["excluded"]} == {"ISSUE-0004", "ISSUE-0005"}
    assert report["now"] == "ISSUE-0001" and report["next"] == "ISSUE-0002"
    assert report["execution_allowed"] is False and report["apply_authority"] is False
    assert report["ready"][1]["activation_dependencies"] == ["ISSUE-0005"]
    assert not {"ISSUE-0004", "ISSUE-0005", "ISSUE-0006"} & {key for wave in report["conditional_dependency_waves"] for key in wave}


def test_graph_cycle_and_unknown_dependency_fail_closed() -> None:
    for dependency in ("ISSUE-0003", "ISSUE-9999"):
        registry = mini_registry()
        registry["records"][0]["blocking_dependencies"] = [dependency]
        with pytest.raises(ValueError, match="cycle|Invalid blocking edge"):
            execution.build_plan(registry)


def test_order_independent_and_merged_work_is_verification_not_completion() -> None:
    registry = mini_registry()
    work = {"ISSUE-0002": [{"merge": MAIN, "git_observation": "ancestor_of_observed_main", "acceptance": "NOT_ESTABLISHED"}]}
    first = execution.build_plan(registry, work)
    registry["records"].reverse()
    registry["readiness"].reverse()
    assert execution.build_plan(registry, work) == first
    assert first["now"] == "ISSUE-0002"
    assert first["ready"][0]["status"] == "planned"
    assert first["ready"][0]["work_kind"] == "verify_merged_product_lifecycle"


def test_integrated_parent_does_not_silently_waive_edge_evidence() -> None:
    registry = mini_registry()
    registry["records"][0]["programme_status"] = "integrated"
    report = execution.build_plan(registry)
    blocked = next(row for row in report["blocked"] if row["issue"] == "ISSUE-0003")
    assert blocked["evidence_only"] is True
    assert "ISSUE-0003" not in [row["issue"] for row in report["ready"]]


def test_missing_and_schema_only_lane_observations_never_claim_local_authority() -> None:
    assert validate(None)["parallel_waves"] == []
    report = validate(manifest(lane(1), lane(2)))
    assert report["status"] == "SCHEMA_ONLY_NOT_LOCAL_AUTHORITY"
    assert report["local_verification"] is False
    assert report["parallel_waves"] == [["lane-1", "lane-2"]]
    assert report["apply_authority"] is False


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("observed_main", "c" * 40, "STALE_MAIN"),
    ("programme_sha256", "c" * 64, "STALE_MAIN"),
    ("all_active_writers_reconciled", False, "CENSUS_UNVERIFIED"),
    ("children_in_use", 5, "REVIEW_CAPACITY"),
    ("children_in_use", True, "REVIEW_CAPACITY"),
])
def test_stale_or_unproved_global_lane_state_fails_closed(field, value, reason) -> None:
    result = validate(manifest(lane(1), **{field: value}))
    assert result["parallel_waves"] == []
    assert reason in result["errors"][0]


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("issue", "ISSUE-0006", "ALREADY_INTEGRATED"),
    ("issue", "ISSUE-0003", "ISSUE_NOT_READY"),
    ("issue", "ISSUE-0004", "ISSUE_NOT_READY"),
    ("base", "c" * 40, "STALE_BASE"),
    ("writer", "antigravity-independent", "INDEPENDENT_AGY"),
    ("owned_paths", ["issues/programme_control_state.json"], "ROOT_ONLY"),
    ("owned_paths", ["src/../issues/open.md"], "Noncanonical"),
    ("owned_paths", ["src/*"], "Ambiguous"),
    ("runtime_roots", [], "MISSING_OR_DUPLICATE"),
])
def test_invalid_worker_claims_fail_closed(field, value, reason) -> None:
    result = validate(manifest(lane(1, **{field: value})))
    assert result["parallel_waves"] == []
    assert reason in result["errors"][0]


@pytest.mark.parametrize("field", ["owned_paths", "owned_tests"])
@pytest.mark.parametrize("path", [
    "docs/codex-config/config-core.toml",
    "docs/codex-config/global-AGENTS.md",
    "docs/codex-config/agents/implementer.toml",
    "docs/codex-config/agents/nested/reviewer.toml",
])
def test_worker_cannot_own_durable_routing_policy(field, path) -> None:
    result = validate(manifest(lane(1, **{field: [path]})))
    assert result["parallel_waves"] == []
    assert any("ROOT_ONLY_CANONICAL_OR_POLICY_OWNERSHIP" in error for error in result["errors"])


def test_worker_can_own_nearby_routing_tests() -> None:
    result = validate(manifest(lane(1, owned_tests=["docs/codex-config/test_agent_routing.py"])))
    assert result["errors"] == []
    assert result["parallel_waves"] == [["lane-1"]]


@pytest.mark.parametrize("mutation", [
    {"owned_paths": ["src/module1.py"]},
    {"owned_tests": ["tests/test_module1.py"]},
    {"runtime_roots": ["/tmp/control-fixture/runtime-1"]},
    {"runtime_roots": ["/tmp/control-fixture/lane-1/tmp"]},
    {"ports": [21001]},
    {"resources": ["cuda:0"]},
    {"worktree": "/tmp/control-fixture/lane-1/subtree"},
])
def test_active_path_test_runtime_resource_conflicts_are_not_safe_waves(mutation) -> None:
    first = lane(1, state="active", ports=[21001], resources=["cuda:0"])
    second = lane(2, state="active", **mutation)
    result = validate(manifest(first, second, children_in_use=2))
    assert result["status"] == "BLOCKED_INVALID_OR_STALE_OWNERSHIP"
    assert "ACTIVE_LANE_CONFLICT" in result["errors"][0]
    assert result["parallel_waves"] == []


def test_planned_conflict_is_conditional_not_an_active_collision() -> None:
    result = validate(manifest(lane(1), lane(2, owned_paths=["src/module1.py"])))
    assert not result["errors"]
    assert result["parallel_waves"] == [["lane-1"]]
    assert result["conditional_waves"] == [["lane-2"]]


def test_occupied_discretionary_children_cannot_be_ignored_when_admitting_writers() -> None:
    result = validate(manifest(lane(1), lane(2), children_in_use=3))
    assert result["parallel_waves"] == [["lane-1"]]
    assert result["not_admitted_now"] == ["lane-2"]
    none = validate(manifest(lane(1), children_in_use=4))
    assert none["parallel_waves"] == []


def test_fresh_pr_observation_is_separate_from_lane_claim() -> None:
    claim = manifest(lane(1, pr=123))
    missing = validate(claim)
    assert "CURRENT_PR_HEAD_NOT_OBSERVED" in missing["errors"][0]
    observed = {"observed_main": MAIN, "pulls": {"123": {"head": MAIN, "branch": "codex/lane-1", "base": MAIN, "base_branch": "main", "state": "open"}}}
    assert not validate(claim, pulls=observed)["errors"]
    observed["pulls"]["123"]["head"] = "c" * 40
    assert "PR_HEAD_BRANCH_OR_STATE_DRIFT" in validate(claim, pulls=observed)["errors"][0]


def test_root_control_lane_is_explicit_not_a_fake_canonical_issue() -> None:
    root = lane(1, issue=None, writer="codex-root", owned_paths=["issues/programme_control_state.json"])
    assert not validate(manifest(root))["errors"]
    duplicate = lane(2, writer="codex-root")
    assert "MULTIPLE_ROOT" in validate(manifest(root, duplicate))["errors"][0]


def test_local_lane_identity_and_unowned_changes_are_observed(tmp_path: Path) -> None:
    initialise(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/module1.py").write_text("VALUE = 1\n")
    base = commit(tmp_path, "fixture")
    branch = run(tmp_path, "branch", "--show-current")
    item = lane(1, worktree=str(tmp_path), branch=branch, base=base, head=base)
    value = manifest(item, observed_main=base)
    result = lanes.validate_lanes(value, execution.build_plan(mini_registry()), base, PROGRAMME, root=tmp_path, child_ceiling=6)
    assert result["status"] == "LOCAL_OBSERVATIONS_VALIDATED_ROOT_ADMISSION_REQUIRED"
    (tmp_path / "unowned.txt").write_text("unrelated\n")
    result = lanes.validate_lanes(value, execution.build_plan(mini_registry()), base, PROGRAMME, root=tmp_path, child_ceiling=6)
    assert "WORKING_CHANGES_OUTSIDE" in result["errors"][0]


@pytest.mark.parametrize("operation", ["delete", "rename"])
def test_deleted_or_renamed_financial_path_cannot_hide_behind_ordinary_edit(tmp_path: Path, operation: str) -> None:
    initialise(tmp_path)
    protected = tmp_path / "src/finance/old calculation.py"
    protected.parent.mkdir(parents=True)
    protected.write_text("VALUE = 1\n")
    ordinary = tmp_path / "src/page.py"
    ordinary.write_text("VALUE = 1\n")
    base = commit(tmp_path, "fixture")
    if operation == "delete":
        protected.unlink()
    else:
        protected.rename(tmp_path / "src/ordinary.py")
    ordinary.write_text("VALUE = 2\n")
    head = commit(tmp_path, "changed boundary")
    paths = changed_paths(tmp_path, base, head)
    assert "src/finance/old calculation.py" in paths
    assert classifier.build_report(paths, ordinary_issues_since_full_gate=0)["tier"] == "H"


def test_dirty_state_cannot_mask_committed_diff_and_deleted_tests_are_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    initialise(tmp_path)
    target = tmp_path / "tests/test_old name.py"
    target.parent.mkdir()
    target.write_text("def test_value(): pass\n")
    base = commit(tmp_path, "base")
    target.rename(tmp_path / "tests/test_new name.py")
    head = commit(tmp_path, "rename")
    (tmp_path / "extra.txt").write_text("pending\n")
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_BASE_SHA", base)
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_HEAD_SHA", head)
    assert set(validate_app._changed_paths(tmp_path)) == {"tests/test_old name.py", "tests/test_new name.py", "extra.txt"}
    assert validate_app._changed_test_paths(tmp_path) == ["tests/test_new name.py"]
    monkeypatch.setenv("ETF_COCKPIT_VALIDATION_BASE_SHA", "invalid")
    with pytest.raises(ValueError, match="explicit validation"):
        validate_app._changed_paths(tmp_path)
    assert working_paths(tmp_path) == ["extra.txt"]


def test_protected_groups_include_tests_harness_delivery_and_checkout_policy() -> None:
    groups = identity_groups()
    from scripts.validation_summary import IDENTITY_KEYS
    assert set(groups) == IDENTITY_KEYS
    assert "tests" in groups["source"]
    for path in (".gitattributes", "docs/product-completion/DELIVERY_WORKFLOW.md", "docs/codex-config/agy_delegate.py", ".agents/agents"):
        assert path in groups["policy"]
    assert "requirements-github-mutation-runtime.txt" in groups["environment"]
    groups["policy"] = ()
    assert identity_groups()["policy"]


def evidence_fixture(root: Path, *, stale_source: bool = False) -> tuple[str, str, dict]:
    initialise(root)
    (root / "src").mkdir()
    (root / "src/product.py").write_text("VALUE = 1\n")
    manifest_path = root / ".github/issue-transitions/protected-evidence-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n")
    base = commit(root, "base")
    (root / "review-fixture.txt").write_text("fixture only, not real certification\n")
    certified = commit(root, "certified fixture source")
    manifest_path.write_text(json.dumps({"schema_version": "protected-evidence-manifest.v1", "execution_allowed": False,
         "artifact_identity": {"reviewed_head_sha": certified, "terminal_result": "success", "release_gate_run_id": 1,
                               "release_gate_attempt": 1, "linux_junit_tests": 1, "windows_junit_tests": 1}}))
    if stale_source:
        (root / "src/product.py").write_text("VALUE = 2\n")
    reference = commit(root, "evidence catalogue fixture")
    return base, reference, {"base_sha": base, "head_sha": reference}


def test_old_green_artifact_cannot_certify_a_different_source(tmp_path: Path) -> None:
    _, reference, seed = evidence_fixture(tmp_path, stale_source=True)
    reasons: list[str] = []
    assert classifier.derive_trusted_evidence(tmp_path, base=reference, head=reference,
        artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json", reusable_evidence=seed, diagnostics=reasons) is None
    assert reasons == ["certified_artifact_source_identity_changed:source_sha256"]


def test_real_source_equivalence_still_allows_base_anchored_reuse(tmp_path: Path) -> None:
    _, reference, seed = evidence_fixture(tmp_path)
    expected = classifier.derive_trusted_evidence(tmp_path, base=reference, head=reference,
        artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json", reusable_evidence=seed)
    assert expected is not None
    report = classifier.build_report(["docs/product-completion/PROGRESS.md"], reusable_evidence=expected, expected_evidence=expected)
    assert report["evidence_reuse"]["authorized"] is True
    assert report["package_gate_required"] is False


@pytest.mark.parametrize("path", ["tests/test_product.py", "docs/codex-config/agy_delegate.py", ".agents/agents/codex-flash-editor/agent.md"])
def test_intervening_test_or_harness_change_invalidates_reuse(tmp_path: Path, path: str) -> None:
    _, reference, seed = evidence_fixture(tmp_path)
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n")
    head = commit(tmp_path, "intervening change")
    reasons: list[str] = []
    assert classifier.derive_trusted_evidence(tmp_path, base=reference, head=head,
        artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json", reusable_evidence=seed, diagnostics=reasons) is None
    assert reasons[0].startswith("protected_identity_changed:")


def test_every_ci_source_checkout_and_integration_base_are_explicit() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-gate.yml").read_text())
    count = 0
    for job in workflow["jobs"].values():
        for index, step in enumerate(job["steps"]):
            if step.get("name") != "Check out source":
                continue
            count += 1
            assert step["uses"] == "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
            assert "github.event.pull_request.head.sha" in step["with"]["ref"]
            assert step["with"]["persist-credentials"] is False
            guard = job["steps"][index + 1]
            assert guard["name"] == "Verify exact source checkout"
            assert "git rev-parse HEAD" in guard["run"]
            assert 'git merge-base --is-ancestor "$EXPECTED_BASE_SHA" "$EXPECTED_SOURCE_SHA"' in guard["run"]
            assert '$(git rev-parse origin/main)' in guard["run"]
    assert count == 7


def test_archived_history_is_exact_and_not_current_instruction_authority() -> None:
    archive = ROOT / "plans/archive/2026-09-08-control-plane"
    manifest_data = json.loads((archive / "manifest.json").read_text())
    for item in manifest_data["files"]:
        payload = (ROOT / item["archive_path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
        assert hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest() == item["git_blob"]
    assert (ROOT / "plans/ACTIVE_CODEX_GOAL.md").stat().st_size < 2500
    assert (ROOT / "plans/BATCH-B04-ANALYSIS-SPINE.md").stat().st_size < 2500


def test_current_state_contradiction_is_mechanically_detected(tmp_path: Path) -> None:
    # Run the existing source audit in a subprocess to avoid contaminating role imports.
    code = """
import sys
from pathlib import Path
sys.path.insert(0, 'docs/codex-config')
import agent_routing
root = Path.cwd()
assert not agent_routing.validate_source_templates(root)
from unittest.mock import patch
original = Path.read_text

def changed(path, *args, **kwargs):
    value = original(path, *args, **kwargs)
    return value + '\\nThe editor remains disabled.\\n' if path == root / 'plans/ACTIVE_CODEX_GOAL.md' else value
with patch.object(Path, 'read_text', changed):
    assert any('Contradictory editor' in item for item in agent_routing.validate_source_templates(root))
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True)


def test_all_generated_paths_are_root_only_not_worker_ownership() -> None:
    manifest_data = json.loads((ROOT / "docs/product-completion/programme/generation-manifest.json").read_text())
    for item in manifest_data["outputs"]:
        protected = lanes.boundary(item["path"])
        assert any(lanes.overlaps(protected, prefix) for prefix in lanes.ROOT_ONLY), item["path"]


def test_json_observations_reject_duplicates_and_nonfinite_values(tmp_path: Path) -> None:
    path = tmp_path / "observation.json"
    for content in ('{"head": 1, "head": 2}', '{"children_in_use": NaN}'):
        path.write_text(content)
        with pytest.raises(ValueError):
            execution.read_json(path)


def test_blocked_and_frozen_lanes_reserve_without_becoming_runnable() -> None:
    report = validate(manifest(lane(1, state="blocked", blocker="Exact-head review missing"), lane(2)))
    assert report["parallel_waves"] == [["lane-2"]]
    assert report["reserved_not_runnable"] == ["lane-1"]
    assert report["active"][0]["blocker"] == "Exact-head review missing"
    assert validate(manifest(lane(1, state="blocked")))["status"] == "BLOCKED_INVALID_OR_STALE_OWNERSHIP"


def test_runtime_symlink_alias_is_not_physical_isolation(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit creating symlink fixtures")
    with pytest.raises(ValueError, match="LINKED_OWNERSHIP_OR_RUNTIME_BOUNDARY"):
        lanes._reject_aliases(alias / "new" / "runtime")
    lanes._reject_aliases(real / "new" / "runtime")


def test_resource_whitespace_alias_fails_closed() -> None:
    result = validate(manifest(lane(1, resources=["gpu0"]), lane(2, resources=["gpu0 "])))
    assert result["status"] == "BLOCKED_INVALID_OR_STALE_OWNERSHIP"
    assert result["parallel_waves"] == []


def test_invalid_artifact_schema_cannot_certify_source(tmp_path: Path) -> None:
    _, reference, seed = evidence_fixture(tmp_path)
    target = tmp_path / ".github/issue-transitions/protected-evidence-manifest.json"
    value = json.loads(target.read_text())
    value["schema_version"] = "unrecognised"
    target.write_text(json.dumps(value))
    replacement = commit(tmp_path, "invalid catalogue schema")
    reasons: list[str] = []
    assert classifier.derive_trusted_evidence(tmp_path, base=replacement, head=replacement,
        artifact_manifest=".github/issue-transitions/protected-evidence-manifest.json",
        reusable_evidence={**seed, "head_sha": replacement}, diagnostics=reasons) is None
    assert reasons == ["unverifiable_certified_artifact_identity"]


def test_downstream_clause_is_diagnosed_without_silently_rewriting_canonical_edges() -> None:
    registry = mini_registry()
    record = registry["records"][2]
    record["contract_markdown"] = "**Canonical metadata:** P0; depends on `ISSUE-0001`; downstream `ISSUE-0002`; execution false.\n"
    record["provenance"] = {"primary_source": "immutable-fixture.md"}
    record["blocking_dependencies"] = ["ISSUE-0001", "ISSUE-0002"]
    original = copy.deepcopy(registry)
    findings = execution.contract_diagnostics(registry)
    assert findings[0]["unexpected_blockers"] == ["ISSUE-0002"]
    assert findings[0]["source_dependencies"] == ["ISSUE-0001"]
    assert registry == original
    record["blocking_dependencies"] = ["ISSUE-0001"]
    assert execution.contract_diagnostics(registry) == []


def test_historical_locators_resolve_exact_squash_tree(tmp_path: Path) -> None:
    run(tmp_path, "init", "-q")
    run(tmp_path, "config", "user.name", "Fixture")
    run(tmp_path, "config", "user.email", "fixture@example.invalid")
    (tmp_path / "product.txt").write_text("base\n")
    base = commit(tmp_path, "base")
    (tmp_path / "product.txt").write_text("candidate\n")
    head = commit(tmp_path, "candidate")
    run(tmp_path, "checkout", "--detach", base)
    (tmp_path / "product.txt").write_text("candidate\n")
    merged = commit(tmp_path, "squash candidate")
    assert not execution.ancestor(tmp_path, head, merged)
    index = tmp_path / execution.INDEX
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({"schema_version": "programme-work-locators.v1", "apply_authority": False,
        "items": [{"issue_ids": ["ISSUE-0068"], "pr": 597, "branch": "historical-candidate",
                   "head": head, "merge": merged, "purpose": "Fixture, not actual acceptance"}]}))
    result = execution.load_work_index(tmp_path, merged)
    assert result["ISSUE-0068"][0]["git_observation"] == "ancestor_of_observed_main"
    (tmp_path / "product.txt").write_text("different\n")
    unrelated = commit(tmp_path, "different source")
    data = json.loads(index.read_text())
    data["items"][0]["merge"] = unrelated
    index.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="neither ancestry nor exact tree"):
        execution.load_work_index(tmp_path, unrelated)


@pytest.mark.parametrize("path", ["/tmp/a//b", "C:/dev/cache:stream", "C://dev/cache", "/tmp/cache:stream"])
def test_runtime_path_alias_spellings_are_rejected(path: str) -> None:
    with pytest.raises(ValueError, match="Noncanonical absolute"):
        lanes.boundary(path, absolute=True)


def test_local_lane_cannot_hide_an_unowned_committed_change(tmp_path: Path) -> None:
    initialise(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/module1.py").write_text("base\n")
    base = commit(tmp_path, "base")
    branch = run(tmp_path, "branch", "--show-current")
    (tmp_path / "unowned.txt").write_text("outside owned source\n")
    head = commit(tmp_path, "unowned committed change")
    claim = lane(1, branch=branch, worktree=str(tmp_path), base=base, head=head,
                 runtime_roots=[str(tmp_path / "runtime")])
    with pytest.raises(ValueError, match="COMMITTED_OR_WORKING_CHANGES"):
        lanes._local_check(tmp_path, claim)


@pytest.mark.parametrize(("field", "bad"), [("base", "b" * 40), ("base_branch", "other")])
def test_pr_base_drift_is_not_hidden_by_a_matching_head(field: str, bad: str) -> None:
    observed = {"head": MAIN, "branch": "codex/lane-1", "base": MAIN, "base_branch": "main", "state": "open"}
    observed[field] = bad
    report = validate(manifest(lane(1, pr=123)), pulls={"observed_main": MAIN, "pulls": {"123": observed}})
    assert "PR_HEAD_BRANCH_OR_STATE_DRIFT" in report["errors"][0]
