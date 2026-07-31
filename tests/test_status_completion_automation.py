from __future__ import annotations

import base64
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import apply_reviewed_status_completion as completion
from scripts import sync_github_issues as sync


PARENT = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40


def _record(status: str = "integrated") -> dict[str, object]:
    return {
        "canonical_id": "ISSUE-0179",
        "title": "Atomic programme generation",
        "classification": "proposed_new",
        "ledger_state": "open",
        "programme_status": status,
        "priority": "P1",
        "owner": "programme-governance",
        "phase": "phase-01-governance-scope",
        "blocking_dependencies": [],
        "required_inputs": [],
        "activation_dependencies": [],
        "capability_lane": "CORE_ANALYSIS",
        "release_blocking": True,
        "downstream_issues": [],
        "related_issues": [],
    }


def _remote(status: str = "implemented_initially") -> list[dict[str, object]]:
    record = _record(status)
    body = sync.managed_block(record)
    return [
        {
            "number": 179,
            "title": record["title"],
            "body": body,
            "state": "OPEN",
            "url": "https://example.invalid/issues/179",
        }
    ]


def _plan_and_candidate() -> tuple[
    list[dict[str, object]], dict[str, object], dict[str, object]
]:
    remote = _remote()
    plan = sync.plan_actions({"records": [_record()]}, remote, historical_map={})
    candidate = {
        "schema_version": completion.SCHEMA_VERSION,
        "execution_allowed": False,
        "expected_parent_sha": PARENT,
        "remote_inventory_sha256": plan["remote_inventory_sha256"],
        "plan_semantic_sha256": plan["plan_sha256"],
        "expected_update": {
            "stable_id": "ISSUE-0179",
            "from_status": "implemented_initially",
            "to_status": "integrated",
        },
    }
    return remote, plan, candidate


def test_happy_apply_uses_approved_plan_and_requires_zero_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate_path = tmp_path / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    registry = tmp_path / sync.REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"records": [_record()]}), encoding="utf-8")
    observed: list[str] = []
    monkeypatch.setattr(
        completion,
        "validate_git_bindings",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        completion.sync,
        "apply_actions",
        lambda value, *, approved_sha256: (
            observed.append(approved_sha256)
            if value == plan
            else pytest.fail("unexpected plan")
        ),
    )
    readbacks = iter([remote, _remote("integrated")])
    evidence_path = tmp_path / "artifacts/evidence.json"

    completion.run(
        tmp_path,
        candidate_path,
        expected_parent=PARENT,
        expected_head=HEAD,
        main_ref="origin/main",
        apply=True,
        evidence_out=evidence_path,
        remote_reader=lambda: next(readbacks),
    )

    assert observed == [plan["plan_sha256"]]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == "applied_and_verified"
    assert evidence["zero_action_readback"] is True
    assert "body" not in json.dumps(evidence).lower()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("remote_inventory_sha256", "0" * 64, "inventory"),
        ("plan_semantic_sha256", "0" * 64, "semantic"),
        ("expected_parent_sha", "0" * 40, "parent"),
    ],
)
def test_candidate_rejects_wrong_bindings(field: str, value: str, message: str) -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate[field] = value

    if field == "expected_parent_sha":
        with pytest.raises(ValueError, match=message):
            completion.validate_git_bindings(
                Path("."),
                candidate,
                candidate_path=Path("."),
                candidate_bytes=b"",
                expected_parent=PARENT,
                expected_head=HEAD,
                main_ref=None,
            )
    else:
        with pytest.raises(ValueError, match=message):
            completion.validate_candidate(candidate, plan, remote)


def _git_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, object], str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
    marker = root / "marker.txt"
    marker.write_text("parent\n", encoding="utf-8")
    subprocess.run(["git", "add", "marker.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "parent"], cwd=root, check=True)
    parent = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    _remote_rows, _plan, candidate = _plan_and_candidate()
    candidate["expected_parent_sha"] = parent
    candidate_path = root / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(
        json.dumps(candidate, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    attributes = root / ".gitattributes"
    attributes.write_text(
        f"{completion.DEFAULT_CANDIDATE.as_posix()} text\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".gitattributes", completion.DEFAULT_CANDIDATE.as_posix()],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=root, check=True)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return root, candidate_path, candidate, parent, head


def _validate_repo_binding(
    root: Path,
    candidate_path: Path,
    candidate: dict[str, object],
    parent: str,
    head: str,
) -> None:
    completion.validate_git_bindings(
        root,
        candidate,
        candidate_path=candidate_path,
        candidate_bytes=candidate_path.read_bytes() if candidate_path.exists() else b"",
        expected_parent=parent,
        expected_head=head,
        main_ref=None,
    )


def test_candidate_git_binding_accepts_clean_crlf_checkout(tmp_path: Path) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    subprocess.run(["git", "config", "core.autocrlf", "true"], cwd=root, check=True)
    candidate_path.unlink()
    subprocess.run(["git", "reset", "--hard", "-q", "HEAD"], cwd=root, check=True)
    assert b"\r\n" in candidate_path.read_bytes()

    _validate_repo_binding(root, candidate_path, candidate, parent, head)


@pytest.mark.parametrize(
    "change", ["edit", "delete", "staged_edit", "untracked_replacement"]
)
def test_candidate_git_binding_rejects_dirty_or_replaced_path(
    tmp_path: Path, change: str
) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    if change == "edit":
        candidate_path.write_text("{}\n", encoding="utf-8")
    elif change == "delete":
        candidate_path.unlink()
    elif change == "staged_edit":
        candidate_path.write_text("{}\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", completion.DEFAULT_CANDIDATE.as_posix()],
            cwd=root,
            check=True,
        )
    else:
        original = candidate_path.read_bytes()
        subprocess.run(
            ["git", "rm", "--cached", completion.DEFAULT_CANDIDATE.as_posix()],
            cwd=root,
            check=True,
        )
        candidate_path.write_bytes(original)

    with pytest.raises(ValueError, match="not tracked|staged, unstaged, or untracked"):
        _validate_repo_binding(root, candidate_path, candidate, parent, head)


def test_candidate_git_binding_rejects_wrong_head_and_path(tmp_path: Path) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    with pytest.raises(ValueError, match="does not contain"):
        _validate_repo_binding(root, candidate_path, candidate, parent, parent)

    wrong_path = root / "candidate.json"
    wrong_path.write_bytes(candidate_path.read_bytes())
    with pytest.raises(ValueError, match="canonical status-completion path"):
        _validate_repo_binding(root, wrong_path, candidate, parent, head)


@pytest.mark.parametrize(
    "altered",
    [
        b'{"altered": true}\n',
        b'{\r\n  "altered": true\n}\r\n',
        b'{"altered": true}\r',
    ],
)
def test_candidate_git_binding_rejects_altered_bytes_hidden_by_clean_filter(
    tmp_path: Path, altered: bytes
) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    filter_script = root / "clean-filter.py"
    encoded_reviewed = base64.b64encode(candidate_path.read_bytes()).decode("ascii")
    filter_script.write_text(
        "import base64, sys\n"
        f"sys.stdout.buffer.write(base64.b64decode('{encoded_reviewed}'))\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "config",
            "filter.hide.clean",
            f"python {filter_script.as_posix()}",
        ],
        cwd=root,
        check=True,
    )
    info_attributes = root / ".git/info/attributes"
    info_attributes.write_text(
        f"{completion.DEFAULT_CANDIDATE.as_posix()} filter=hide\n",
        encoding="utf-8",
    )
    candidate_path.write_bytes(altered)
    subprocess.run(
        ["git", "add", completion.DEFAULT_CANDIDATE.as_posix()],
        cwd=root,
        check=True,
    )
    assert (
        subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--",
                completion.DEFAULT_CANDIDATE.as_posix(),
            ],
            cwd=root,
            text=True,
        )
        == ""
    )

    with pytest.raises(ValueError, match="bytes do not match"):
        _validate_repo_binding(root, candidate_path, candidate, parent, head)


def test_candidate_git_binding_rejects_swap_after_byte_capture(tmp_path: Path) -> None:
    root, candidate_path, candidate, parent, head = _git_repo(tmp_path)
    captured = candidate_path.read_bytes()
    candidate_path.write_text('{"swapped": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="staged, unstaged, or untracked"):
        completion.validate_git_bindings(
            root,
            candidate,
            candidate_path=candidate_path,
            candidate_bytes=captured,
            expected_parent=parent,
            expected_head=head,
            main_ref=None,
        )


def test_candidate_rejects_disallowed_direct_status_transition() -> None:
    remote, plan, candidate = _plan_and_candidate()
    candidate["expected_update"]["from_status"] = "planned"  # type: ignore[index]
    remote = _remote("planned")
    plan = sync.plan_actions({"records": [_record()]}, remote, historical_map={})
    candidate["remote_inventory_sha256"] = plan["remote_inventory_sha256"]
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="canonical direct transition"):
        completion.validate_candidate(candidate, plan, remote)


def test_failure_evidence_is_privacy_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _plan, candidate = _plan_and_candidate()
    remote[0]["body"] = str(remote[0]["body"]) + "\nPRIVATE REMOTE BODY"
    candidate["remote_inventory_sha256"] = "0" * 64
    candidate_path = tmp_path / completion.DEFAULT_CANDIDATE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    registry = tmp_path / sync.REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"records": [_record()]}), encoding="utf-8")
    evidence_path = tmp_path / "artifacts/failure.json"
    monkeypatch.setattr(
        completion, "validate_git_bindings", lambda *_args, **_kwargs: None
    )

    with pytest.raises(ValueError, match="inventory"):
        completion.run(
            tmp_path,
            candidate_path,
            expected_parent=PARENT,
            expected_head=HEAD,
            main_ref=None,
            apply=False,
            evidence_out=evidence_path,
            remote_reader=lambda: remote,
        )

    evidence_text = evidence_path.read_text(encoding="utf-8")
    assert "PRIVATE REMOTE BODY" not in evidence_text
    assert json.loads(evidence_text)["terminal_status"] == "failed"


def test_candidate_rejects_wrong_id_and_non_status_delta() -> None:
    remote, plan, candidate = _plan_and_candidate()
    wrong_id = copy.deepcopy(candidate)
    wrong_id["expected_update"]["stable_id"] = "ISSUE-0180"  # type: ignore[index]
    with pytest.raises(ValueError, match="stable ID"):
        completion.validate_candidate(wrong_id, plan, remote)

    changed = copy.deepcopy(plan)
    changed["actions"][0]["title"] = "Changed title"
    changed["plan_sha256"] = sync.plan_sha256(changed)
    changed_candidate = copy.deepcopy(candidate)
    changed_candidate["plan_semantic_sha256"] = changed["plan_sha256"]
    with pytest.raises(ValueError, match="non-status delta"):
        completion.validate_candidate(changed_candidate, changed, remote)


@pytest.mark.parametrize("kind", ["create", "close", "reopen", "blocked"])
def test_candidate_rejects_non_update_actions(kind: str) -> None:
    remote, plan, candidate = _plan_and_candidate()
    plan["actions"][0]["kind"] = kind
    plan["summary"] = dict(completion.ZERO_SUMMARY)
    plan["summary"][kind] = 1
    plan["plan_sha256"] = sync.plan_sha256(plan)
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="exactly one update"):
        completion.validate_candidate(candidate, plan, remote)


def test_candidate_rejects_multiple_actions() -> None:
    remote, plan, candidate = _plan_and_candidate()
    plan["actions"].append(copy.deepcopy(plan["actions"][0]))
    plan["summary"]["update"] = 2
    plan["plan_sha256"] = sync.plan_sha256(plan)
    candidate["plan_semantic_sha256"] = plan["plan_sha256"]

    with pytest.raises(ValueError, match="exactly one update"):
        completion.validate_candidate(candidate, plan, remote)


def test_workflow_permissions_trigger_and_convergence_deferral() -> None:
    root = Path(__file__).resolve().parents[1]
    status_text = (
        root / ".github/workflows/programme-status-completion.yml"
    ).read_text(encoding="utf-8")
    convergence = (root / ".github/workflows/programme-convergence.yml").read_text(
        encoding="utf-8"
    )
    release = (root / ".github/workflows/release-gate.yml").read_text(encoding="utf-8")
    status_workflow = yaml.safe_load(status_text)

    assert status_workflow["permissions"] == {"contents": "read", "issues": "write"}
    assert status_workflow[True]["push"]["branches"] == ["main"]
    assert status_workflow[True]["push"]["paths"] == [
        ".github/issue-transitions/post-merge-control-candidate.json"
    ]
    assert "--apply" in status_text and "--main-ref origin/main" in status_text
    module_invocation = "python -m scripts.apply_reviewed_status_completion"
    direct_script_invocation = "python scripts/apply_reviewed_status_completion.py"
    assert module_invocation in status_text
    assert direct_script_invocation not in status_text
    assert (
        "--evidence-out artifacts/programme-status-completion/evidence.json"
        in status_text
    )
    assert "if: always()" in status_text
    assert "actions/upload-artifact@v4" in status_text
    assert "--control-candidate" not in convergence
    assert "deferring to programme-status-completion" in convergence
    assert "issues: read" in release
    assert isinstance(yaml.safe_load(release), dict)
    assert "steps.status_candidate.outputs.changed == 'true'" in release
    assert module_invocation in release
    assert direct_script_invocation not in release
    assert (
        'git diff --quiet "$ETF_COCKPIT_VALIDATION_BASE_SHA" "$ETF_COCKPIT_VALIDATION_HEAD_SHA" -- "$candidate"'
        in release
    )
    assert (
        "--evidence-out artifacts/validation/status-completion-candidate.json"
        in release
    )
    assert "name: validation-status-completion-candidate-${{ github.sha }}" in release
    assert "path: artifacts/validation/status-completion-candidate.json" in release
    assert "!artifacts/validation/status-completion-candidate.json" in release
    candidate_upload = release.index(
        "- name: Upload status-completion candidate evidence"
    )
    assert (
        "if-no-files-found: error" in release[candidate_upload : candidate_upload + 420]
    )


def test_status_completion_module_help_smoke() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "scripts.apply_reviewed_status_completion", "--help"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "usage:" in result.stdout
