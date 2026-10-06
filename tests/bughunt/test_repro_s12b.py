"""Bug hunt slice S12B reproduction tests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import (
    generate_completion_documents as completion_documents,
    generate_programme,
    github_mutation_gateway,
    release_gate,
    sync_github_issues,
    update_programme_control,
)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-03: Metadata refresh invalidates durable creation authority",
)
def test_s12_03_refresh_preserves_creation_acceptance() -> None:
    record = {
        "canonical_id": "ISSUE-0001",
        "title": "Issue 1",
        "classification": "proposed_new",
        "ledger_state": "open",
        "programme_status": "planned",
        "priority": "P1",
        "owner": "owner",
        "phase": "phase-01",
        "blocking_dependencies": [],
        "required_inputs": [],
        "activation_dependencies": [],
        "capability_lane": "CORE_ANALYSIS",
        "release_blocking": True,
        "downstream_issues": [],
        "related_issues": [],
    }
    issue = {
        "number": 1,
        "id": "101",
        "node_id": "NODE_1",
        "title": record["title"],
        "state": "open",
        "labels": [],
        "comments": [],
        "body": github_mutation_gateway.CREATE_MARKER_TEMPLATE.format("a" * 64)
        + "\n"
        + sync_github_issues.managed_block(record),
    }
    _, receipt = github_mutation_gateway.build_create_receipt(
        issue, mutation_id="a" * 64, stable_id=record["canonical_id"]
    )
    issue["comments"] = [
        {
            "id": "C1",
            "body": receipt,
            "author": "github-actions[bot]",
            "author_id": github_mutation_gateway.GITHUB_ACTIONS_BOT_USER_ID,
            "author_type": "Bot",
            "app_slug": "github-actions",
            "app_id": github_mutation_gateway.GITHUB_ACTIONS_APP_ID,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z",
        }
    ]
    assert github_mutation_gateway.validate_create_acceptance(issue)["accepted"]

    registry = {"records": [{**record, "priority": "P0"}], "execution_allowed": False}
    plan = sync_github_issues.plan_actions(registry, [issue])
    updates = github_mutation_gateway.managed_refresh_updates(registry, plan, [issue])
    assert updates
    issue["body"] = plan["actions"][0]["body"]

    assert github_mutation_gateway.validate_create_acceptance(issue)["accepted"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-04: Failed check retains generated changes",
)
def test_s12_04_check_restores_outputs_after_generation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = (
        tmp_path
        / completion_documents.PROGRAMME_ROOT
        / "reconciliation"
        / f"{completion_documents.RECONCILIATION_DATE}-0000000"
        / "source-to-canonical.csv"
    )
    output.parent.mkdir(parents=True)
    output.write_bytes(b"original")
    monkeypatch.setattr(
        completion_documents,
        "build_registry",
        lambda *args, **kwargs: {"source_of_truth": {"baseline_commit": "0" * 40}},
    )

    def fail_after_write(*args: object, **kwargs: object) -> frozenset[str]:
        output.write_bytes(b"changed")
        raise json.JSONDecodeError("bad summary", "[", 1)

    monkeypatch.setattr(completion_documents, "generate", fail_after_write)
    with pytest.raises(json.JSONDecodeError):
        completion_documents.main(["--root", str(tmp_path), "--check"])

    assert output.read_bytes() == b"original"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-05: Convergence manifest always disagrees with normal generation",
)
def test_s12_05_convergence_manifest_matches_normal_projection() -> None:
    root = Path.cwd()
    outputs = generate_programme.required_outputs(root)
    plan = next(
        (Path(path).parent / "github-sync-plan.json").as_posix()
        for path in outputs
        if path.endswith("/github-remote-summary.json")
    )
    real_is_file, real_read_bytes = Path.is_file, Path.read_bytes
    with (
        patch.object(
            Path,
            "is_file",
            lambda path: True if path == root / plan else real_is_file(path),
        ),
        patch.object(
            Path,
            "read_bytes",
            lambda path: b"{}\n" if path == root / plan else real_read_bytes(path),
        ),
    ):
        assert generate_programme.build_manifest(
            root, outputs | {plan}
        ) == generate_programme.build_manifest(root, outputs)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-06: Convergence publishes stale inventory projections",
)
def test_s12_06_convergence_renders_fresh_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative_summary = (
        "docs/product-completion/reconciliation/2026-07-21-0000000/"
        "github-remote-summary.json"
    )
    state = {"issues": [{"state": "OPEN"}]}
    rendered: dict[str, int] = {}

    def stage_generation(*args: object, **kwargs: object) -> frozenset[str]:
        rendered.update(
            completion_documents.load_github_inventory(
                (tmp_path / relative_summary).parent
            )
        )
        return frozenset({relative_summary})

    monkeypatch.setattr(generate_programme, "stage_generation", stage_generation)
    monkeypatch.setattr(
        generate_programme.subprocess,
        "run",
        lambda *args, **kwargs: state["issues"].append({"state": "OPEN"}),
    )
    for name in (
        "_verify_exact_head",
        "_validate_and_emit_convergence_evidence",
        "_accept_reviewed_or_fresh_noop_sidecar",
    ):
        monkeypatch.setattr(generate_programme, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_programme, "build_manifest", lambda *args: b"{}")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: json.dumps(state),
    )
    monkeypatch.setattr(Path, "write_bytes", lambda *args: 2)

    generate_programme.run_convergence(
        tmp_path,
        tmp_path,
        expected_head="0" * 40,
        main_ref="origin/main",
        remote_snapshot=None,
        reviewed_sidecar=tmp_path / "sidecar",
    )

    assert rendered["issue_count"] == len(state["issues"])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-07: SBOM passes with an invalid UUID URN",
)
def test_s12_07_sbom_serial_number_is_uuid_urn(tmp_path: Path) -> None:
    bom = release_gate.build_sbom(
        tmp_path,
        {"manifest_sha256": "0123456789abcdef" * 4},
        {"dependency_lock": "absent.txt"},
    )

    assert re.fullmatch(
        r"urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        bom["serialNumber"],
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S12-08: Control writer accepts dates its replay reader rejects",
)
def test_s12_08_writer_rejects_noncanonical_review_date() -> None:
    value = {
        "records": {
            "ISSUE-0001": {
                "programme_status": "planned",
                "verified_commit": "0" * 40,
                "dependency_edge_evidence": {},
                "transition_history": [],
                "acceptance_evidence": [],
            }
        }
    }

    try:
        update_programme_control.apply_transition(
            value,
            issue_id="ISSUE-0001",
            expected_from="planned",
            to_status="in_progress",
            review_reference="review/1",
            evidence_references=["evidence/1"],
            reviewer="reviewer",
            reviewed_date="20261006",
            verified_commit="1" * 40,
        )
    except ValueError as exc:
        assert "YYYY-MM-DD" in str(exc)
    else:
        assert False, "writer accepted a date its replay reader rejects"
