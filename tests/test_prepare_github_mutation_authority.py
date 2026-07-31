from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import apply_reviewed_status_completion as completion
from scripts import github_mutation_gateway as gateway
from scripts import prepare_github_mutation_authority as prepare
from scripts import sync_github_issues as sync


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


def _remote() -> list[dict[str, object]]:
    return [
        {
            "id": "4179",
            "node_id": "ISSUE_NODE_179",
            "number": 179,
            "title": "Atomic programme generation",
            "body": sync.managed_block(_record("implemented_initially")),
            "state": "OPEN",
            "url": "https://example.invalid/issues/179",
            "comments": [],
        }
    ]


def _bootstrap() -> dict[str, object]:
    return gateway.build_authority_record(
        "legacy_bootstrap",
        {
            "legacy_issues": [
                {
                    "stable_id": "ISSUE-0179",
                    "issue_number": 179,
                    "database_id": "4179",
                    "node_id": "ISSUE_NODE_179",
                    "initial_status": "implemented_initially",
                }
            ]
        },
        sequence=0,
        previous_authority_id=None,
    )


def _repo(tmp_path: Path) -> tuple[Path, str, dict[str, object]]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    bootstrap = _bootstrap()
    ledger = root / gateway.AUTHORITY_PATH
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(gateway.authority_ledger_bytes([bootstrap]))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "bootstrap"], cwd=root, check=True)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", source],
        cwd=root,
        check=True,
    )
    return root, source, bootstrap


def test_status_preparation_command_is_deterministic_and_repository_read_only(
    tmp_path: Path,
) -> None:
    root, source, bootstrap = _repo(tmp_path)
    remote = _remote()
    plan = sync.plan_actions(
        {"records": [_record()]},
        remote,
        historical_map={},
        authority_records=[bootstrap],
    )
    plan_path = tmp_path / "reviewed-plan.json"
    remote_path = tmp_path / "live-snapshot.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    remote_path.write_text(json.dumps(remote), encoding="utf-8")

    outputs = [tmp_path / "prepared-one", tmp_path / "prepared-two"]
    for output in outputs:
        assert (
            prepare.main(
                [
                    "--root",
                    str(root),
                    "--plan",
                    str(plan_path),
                    "--remote-snapshot",
                    str(remote_path),
                    "--source-sha",
                    source,
                    "--mode",
                    "status",
                    "--output-dir",
                    str(output),
                ]
            )
            == 0
        )

    first_candidate = (outputs[0] / completion.DEFAULT_CANDIDATE).read_bytes()
    second_candidate = (outputs[1] / completion.DEFAULT_CANDIDATE).read_bytes()
    first_ledger = (outputs[0] / gateway.AUTHORITY_PATH).read_bytes()
    second_ledger = (outputs[1] / gateway.AUTHORITY_PATH).read_bytes()
    assert first_candidate == second_candidate
    assert first_ledger == second_ledger
    records = gateway.parse_authority_ledger(first_ledger)
    assert len(records) == 2
    assert records[-1]["authority_type"] == "status"
    assert records[-1]["payload"]["candidate_blob_sha256"] == __import__(
        "hashlib"
    ).sha256(first_candidate).hexdigest()
    assert json.loads(first_candidate)["execution_allowed"] is False
    assert subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ) == ""


def test_create_preparation_emits_one_safe_append_without_candidate(
    tmp_path: Path,
) -> None:
    root, source, bootstrap = _repo(tmp_path)
    remote = _remote()
    new_record = _record("planned")
    new_record["canonical_id"] = "ISSUE-0180"
    new_record["title"] = "Parallel validation pilot"
    plan = sync.plan_actions(
        {"records": [_record("implemented_initially"), new_record]},
        remote,
        historical_map={},
        authority_records=[bootstrap],
    )

    candidate, ledger, manifest = prepare.prepare(
        root,
        plan,
        remote,
        source_sha=source,
        mode="create",
    )

    assert candidate is None
    records = gateway.parse_authority_ledger(ledger)
    assert len(records) == 2
    assert records[-1]["authority_type"] == "create"
    assert records[-1]["payload"]["stable_id"] == "ISSUE-0180"
    assert manifest["execution_allowed"] is False
