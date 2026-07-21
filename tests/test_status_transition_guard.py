from __future__ import annotations

import copy
import hashlib
import subprocess
from pathlib import Path

import pytest

from scripts.issue_registry_core import deterministic_json
from scripts.status_transition_guard import _git_commit_is_ancestor, guard_proposal
from scripts.update_programme_control import apply_transition
from scripts.update_programme_status import deterministic_text, progress_markdown, status_payload


BASE_COMMIT = "a" * 40
SOURCE_MANIFEST_SHA256 = "b" * 64


def _registry(statuses: dict[str, str]) -> dict:
    return {
        "policy": {"execution_allowed": False},
        "records": [
            {
                "canonical_id": issue_id,
                "title": f"Title {issue_id}",
                "programme_status": status,
                "phase": "phase-01-governance-scope",
                "priority": "P0",
                "ledger_state": "open",
                "blocking_dependencies": [],
                "required_inputs": [],
                "downstream_issues": [],
                "related_issues": [],
            }
            for issue_id, status in statuses.items()
        ],
        "local_only_records": [],
        "source_of_truth": {"source_manifest_sha256": SOURCE_MANIFEST_SHA256},
    }


def _manifest(*transitions: tuple[str, str, str], **overrides: object) -> dict:
    manifest = {
        "schema_version": "1.0",
        "base_commit": BASE_COMMIT,
        "branch": "feature/status-guard",
        "issue_ids": [issue_id for issue_id, _, _ in transitions],
        "allowed_status_transitions": [
            {"issue_id": issue_id, "from": previous, "to": proposed}
            for issue_id, previous, proposed in transitions
        ],
        "allow_other_status_changes": False,
        "allow_downgrades": False,
    }
    manifest.update(overrides)
    return manifest


def _registry_sha256(registry: dict) -> str:
    return hashlib.sha256(deterministic_json(registry)).hexdigest()


def _migration_manifest(
    base: dict,
    proposed: dict,
    *,
    added_issue_ids: list[str],
    removed_issue_ids: list[str] | None = None,
) -> dict:
    manifest = _manifest()
    manifest["schema_version"] = "1.1"
    manifest["registry_migration"] = {
        "mode": "canonical_schema_and_intake",
        "reason": "Reviewed canonical schema and source-intake migration.",
        "generator": "scripts/generate_issue_registry.py",
        "base_registry_sha256": _registry_sha256(base),
        "proposed_registry_sha256": _registry_sha256(proposed),
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "added_issue_ids": added_issue_ids,
        "removed_issue_ids": removed_issue_ids or [],
    }
    return manifest


def _base_refresh_transition_manifest(
    base: dict,
    proposed: dict,
    *transitions: tuple[str, str, str],
) -> dict:
    manifest = _manifest(*transitions)
    manifest["schema_version"] = "1.2"
    manifest["registry_migration"] = {
        "mode": "generation_base_and_status_transitions",
        "reason": "Refresh the reviewed generation base with exact status evidence.",
        "generator": "scripts/generate_issue_registry.py",
        "base_registry_sha256": _registry_sha256(base),
        "proposed_registry_sha256": _registry_sha256(proposed),
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "added_issue_ids": [],
        "removed_issue_ids": [],
    }
    return manifest


def _apply_reviewed_transition(
    registry: dict,
    issue_id: str,
    *,
    previous: str,
    proposed: str,
    allow_downgrade: bool = False,
) -> None:
    record_index = next(
        index for index, row in enumerate(registry["records"]) if row["canonical_id"] == issue_id
    )
    record = registry["records"][record_index]
    assert record["programme_status"] == previous
    control = {"records": {issue_id: copy.deepcopy(record)}}
    apply_transition(
        control,
        issue_id=issue_id,
        expected_from=previous,
        to_status=proposed,
        review_reference="Independent reviewed merge evidence",
        evidence_references=["PR #458 release gates and post-merge smoke"],
        reviewer="Codex independent reviewer",
        reviewed_date="2026-07-21",
        verified_commit=BASE_COMMIT,
        allow_downgrade=allow_downgrade,
    )
    transitioned = control["records"][issue_id]
    for field in ("programme_status", "verified_commit", "verified_date", "acceptance_evidence"):
        record[field] = copy.deepcopy(transitioned[field])


def _errors(
    base: dict,
    proposed: dict,
    manifest: dict,
    *,
    current_status: dict | None = None,
    current_progress: bytes | None = None,
    latest_commit: str = BASE_COMMIT,
    branch: str = "feature/status-guard",
) -> list[str]:
    expected_status = status_payload(proposed)
    expected_progress = deterministic_text(progress_markdown(expected_status, proposed))
    return guard_proposal(
        base_registry=base,
        latest_registry=copy.deepcopy(base),
        proposed_registry=proposed,
        manifest=manifest,
        current_status=expected_status if current_status is None else current_status,
        current_progress=expected_progress if current_progress is None else current_progress,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        expected_base_commit=BASE_COMMIT,
        latest_commit=latest_commit,
        branch=branch,
        base_is_ancestor=True,
        verified_commit_is_ancestor=lambda commit: commit == BASE_COMMIT,
    )


def test_allows_one_legitimate_planned_to_integrated_transition() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})

    assert _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "planned", "integrated")),
    ) == []


def test_allows_deterministic_source_manifest_hash_recalculation() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})
    proposed["source_of_truth"]["source_manifest_sha256"] = "c" * 64
    expected_status = status_payload(proposed)
    expected_progress = deterministic_text(progress_markdown(expected_status, proposed))

    assert guard_proposal(
        base_registry=base,
        latest_registry=copy.deepcopy(base),
        proposed_registry=proposed,
        manifest=_manifest(("ISSUE-0070", "planned", "integrated")),
        current_status=expected_status,
        current_progress=expected_progress,
        source_manifest_sha256="c" * 64,
        expected_base_commit=BASE_COMMIT,
        latest_commit=BASE_COMMIT,
        branch="feature/status-guard",
        base_is_ancestor=True,
    ) == []


def test_rejects_stale_implemented_initially_to_planned_reversion() -> None:
    base = _registry({"ISSUE-0070": "implemented_initially"})
    proposed = _registry({"ISSUE-0070": "planned"})

    errors = _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "implemented_initially", "planned")),
    )

    assert any("unapproved downgrade" in error for error in errors)


def test_rejects_unexpected_second_issue() -> None:
    base = _registry({"ISSUE-0070": "planned", "ISSUE-0071": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated", "ISSUE-0071": "in_progress"})

    errors = _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "planned", "integrated")),
    )

    assert any("not allow-listed: ISSUE-0071" in error for error in errors)


def test_rejects_unauthorised_integrated_to_planned_downgrade() -> None:
    base = _registry({"ISSUE-0070": "integrated"})
    proposed = _registry({"ISSUE-0070": "planned"})

    errors = _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "integrated", "planned")),
    )

    assert any("unapproved downgrade" in error for error in errors)


def test_allows_explicit_downgrade_with_nonblank_reason() -> None:
    base = _registry({"ISSUE-0070": "integrated"})
    proposed = _registry({"ISSUE-0070": "planned"})

    assert _errors(
        base,
        proposed,
        _manifest(
            ("ISSUE-0070", "integrated", "planned"),
            allow_downgrade=True,
            reason="Re-opened after a reviewed evidence correction.",
        ),
    ) == []


@pytest.mark.parametrize("mismatch", ["count", "checksum", "freshness"])
def test_rejects_generated_status_count_checksum_or_freshness_mismatch(mismatch: str) -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})
    expected_status = status_payload(proposed)
    expected_progress = deterministic_text(progress_markdown(expected_status, proposed))
    current_status = copy.deepcopy(expected_status)
    current_progress = expected_progress
    if mismatch == "count":
        current_status["counts"]["integrated"] = 2
    elif mismatch == "checksum":
        current_status["source_registry_sha256"] = "0" * 64
    else:
        current_progress = b"stale\n"

    errors = _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "planned", "integrated")),
        current_status=current_status,
        current_progress=current_progress,
    )

    expected_message = {
        "count": "generated CURRENT_STATUS counts mismatch",
        "checksum": "source-registry checksum mismatch",
        "freshness": "generated PROGRESS.md is stale",
    }[mismatch]
    assert expected_message in errors


def test_allows_crlf_checkout_of_deterministic_progress() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})
    expected_status = status_payload(proposed)
    expected_progress = deterministic_text(progress_markdown(expected_status, proposed))

    errors = _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "planned", "integrated")),
        current_status=expected_status,
        current_progress=expected_progress.replace(b"\n", b"\r\n"),
    )

    assert errors == []


def test_rejects_missing_and_duplicate_manifest_issue_ids() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})
    manifest = _manifest(("ISSUE-0070", "planned", "integrated"))
    manifest["issue_ids"] = ["ISSUE-0070", "ISSUE-0070"]

    errors = _errors(base, proposed, manifest)

    assert any("duplicate issue ID" in error for error in errors)


def test_rejects_missing_proposed_issue_id() -> None:
    base = _registry({"ISSUE-0070": "planned", "ISSUE-0071": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})

    errors = _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "planned", "integrated")),
    )

    assert "proposed registry is missing issue ID: ISSUE-0071" in errors


def test_rejects_stale_origin_and_branch_mismatch() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})

    errors = _errors(
        base,
        proposed,
        _manifest(("ISSUE-0070", "planned", "integrated")),
        latest_commit="c" * 40,
        branch="other/status-guard",
    )

    assert "stale origin/base mismatch: latest origin is not the manifest base" in errors
    assert "manifest branch does not match the proposed branch" in errors


def test_rejects_non_allowlisted_record_edit_and_from_to_mismatch() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "integrated"})
    proposed["records"][0]["title"] = "Unexpected edit"
    manifest = _manifest(("ISSUE-0070", "in_progress", "integrated"))

    errors = _errors(base, proposed, manifest)

    assert "non-allowlisted registry change: ISSUE-0070" in errors
    assert "manifest transition from/to mismatch: ISSUE-0070" in errors


def test_allows_exact_canonical_schema_and_intake_migration_without_status_changes() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "planned", "ISSUE-0153": "planned"})
    proposed["records"][0]["title"] = "Canonical migrated title"
    proposed["schema_version"] = "2.0"

    assert _errors(
        base,
        proposed,
        _migration_manifest(base, proposed, added_issue_ids=["ISSUE-0153"]),
    ) == []


@pytest.mark.parametrize(
    ("manifest_added", "expected_error"),
    [
        ([], "registry migration has unexpected added issue ID: ISSUE-0153"),
        (
            ["ISSUE-0153", "ISSUE-0154"],
            "registry migration expected added issue ID is absent: ISSUE-0154",
        ),
    ],
)
def test_rejects_registry_migration_added_id_mismatch(
    manifest_added: list[str], expected_error: str
) -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "planned", "ISSUE-0153": "planned"})

    errors = _errors(
        base,
        proposed,
        _migration_manifest(base, proposed, added_issue_ids=manifest_added),
    )

    assert expected_error in errors


def test_rejects_registry_migration_removal_or_status_change() -> None:
    base = _registry({"ISSUE-0070": "planned", "ISSUE-0071": "integrated"})
    proposed = _registry({"ISSUE-0070": "integrated"})
    manifest = _migration_manifest(
        base,
        proposed,
        added_issue_ids=[],
        removed_issue_ids=[],
    )

    errors = _errors(base, proposed, manifest)

    assert "registry migration has unexpected removed issue ID: ISSUE-0071" in errors
    assert "status change is not allow-listed: ISSUE-0070" in errors


def test_rejects_registry_migration_after_undeclared_record_or_top_level_mutation() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "planned", "ISSUE-0153": "planned"})
    manifest = _migration_manifest(base, proposed, added_issue_ids=["ISSUE-0153"])
    proposed["records"][0]["title"] = "Mutation after review"
    proposed["policy"]["execution_allowed"] = True

    errors = _errors(base, proposed, manifest)

    assert "registry migration proposed checksum mismatch" in errors


def test_rejects_registry_migration_base_or_source_binding_mismatch() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "planned", "ISSUE-0153": "planned"})
    manifest = _migration_manifest(base, proposed, added_issue_ids=["ISSUE-0153"])
    manifest["registry_migration"]["base_registry_sha256"] = "0" * 64
    manifest["registry_migration"]["source_manifest_sha256"] = "1" * 64

    errors = _errors(base, proposed, manifest)

    assert "registry migration base checksum mismatch" in errors
    assert "registry migration source manifest checksum mismatch" in errors


def test_rejects_registry_migration_with_wrong_checked_out_head() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "planned", "ISSUE-0153": "planned"})
    expected_status = status_payload(proposed)
    expected_progress = deterministic_text(progress_markdown(expected_status, proposed))

    errors = guard_proposal(
        base_registry=base,
        latest_registry=copy.deepcopy(base),
        proposed_registry=proposed,
        manifest=_migration_manifest(base, proposed, added_issue_ids=["ISSUE-0153"]),
        current_status=expected_status,
        current_progress=expected_progress,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        expected_base_commit=BASE_COMMIT,
        latest_commit=BASE_COMMIT,
        branch="feature/status-guard",
        actual_head_commit="c" * 40,
        expected_head_commit="d" * 40,
        base_is_ancestor=True,
    )

    assert "checked-out head does not match the proposed head commit" in errors


def test_rejects_registry_migration_combined_with_forward_status_authority() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    proposed = _registry({"ISSUE-0070": "ready", "ISSUE-0153": "planned"})
    manifest = _migration_manifest(base, proposed, added_issue_ids=["ISSUE-0153"])
    manifest["issue_ids"] = ["ISSUE-0070"]
    manifest["allowed_status_transitions"] = [
        {"issue_id": "ISSUE-0070", "from": "planned", "to": "ready"}
    ]

    errors = _errors(base, proposed, manifest)

    assert "manifest registry_migration cannot authorize status transitions" in errors
    assert "registry migration cannot change programme_status: ISSUE-0070" in errors


def test_rejects_registry_migration_combined_with_reasoned_downgrade() -> None:
    base = _registry({"ISSUE-0070": "integrated"})
    proposed = _registry({"ISSUE-0070": "planned", "ISSUE-0153": "planned"})
    manifest = _migration_manifest(base, proposed, added_issue_ids=["ISSUE-0153"])
    manifest["issue_ids"] = ["ISSUE-0070"]
    manifest["allowed_status_transitions"] = [
        {"issue_id": "ISSUE-0070", "from": "integrated", "to": "planned"}
    ]
    manifest["allow_downgrade"] = True
    manifest["reason"] = "Reviewed downgrade request that migration mode must reject."

    errors = _errors(base, proposed, manifest)

    assert "manifest registry_migration cannot authorize status transitions" in errors
    assert "manifest registry_migration cannot allow a downgrade" in errors
    assert "registry migration cannot change programme_status: ISSUE-0070" in errors


def test_schema_1_0_rejects_explicit_null_registry_migration() -> None:
    base = _registry({"ISSUE-0070": "planned"})
    manifest = _manifest()
    manifest["registry_migration"] = None

    errors = _errors(base, copy.deepcopy(base), manifest)

    assert "manifest registry_migration requires schema_version 1.1 or 1.2" in errors


def test_allows_generation_base_refresh_with_exact_canonical_writer_evidence() -> None:
    base = _registry({"ISSUE-0008": "implemented_initially", "ISSUE-0037": "planned"})
    for record in base["records"]:
        record["verified_commit"] = "d" * 40
        record["acceptance_evidence"] = []
    base["source_of_truth"].update(
        {
            "baseline_commit": "e" * 40,
            "programme_control_state_sha256": "1" * 64,
        }
    )
    proposed = copy.deepcopy(base)
    _apply_reviewed_transition(
        proposed,
        "ISSUE-0008",
        previous="implemented_initially",
        proposed="integrated",
    )
    _apply_reviewed_transition(
        proposed,
        "ISSUE-0037",
        previous="planned",
        proposed="in_progress",
    )
    proposed["source_of_truth"]["baseline_commit"] = BASE_COMMIT
    proposed["source_of_truth"]["programme_control_state_sha256"] = "2" * 64

    errors = _errors(
        base,
        proposed,
        _base_refresh_transition_manifest(
            base,
            proposed,
            ("ISSUE-0008", "implemented_initially", "integrated"),
            ("ISSUE-0037", "planned", "in_progress"),
        ),
    )

    assert errors == []


def test_git_commit_ancestry_verifier_requires_existing_ancestor(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "guard-test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Guard Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    tracked.write_text("descendant\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "descendant"], cwd=tmp_path, check=True)
    descendant = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "switch", "-q", "--detach", base_commit], cwd=tmp_path, check=True)
    (tmp_path / "divergent.txt").write_text("divergent\n", encoding="utf-8")
    subprocess.run(["git", "add", "divergent.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "divergent"], cwd=tmp_path, check=True)
    divergent = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    assert _git_commit_is_ancestor(tmp_path, base_commit, descendant) is True
    assert _git_commit_is_ancestor(tmp_path, divergent, descendant) is False
    assert _git_commit_is_ancestor(tmp_path, "c" * 40, descendant) is False


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("unrelated_record", "non-allowlisted registry change: ISSUE-0008"),
        ("non_transitioned_record", "non-allowlisted registry change: ISSUE-0037"),
        ("replacement_evidence", "transition acceptance evidence must append exactly one entry: ISSUE-0008"),
        ("invalid_verified_commit", "transition verified_commit must be a full lowercase Git SHA: ISSUE-0008"),
        ("invalid_verified_date", "transition verified_date must match reviewed evidence: ISSUE-0008"),
        ("unexpected_top_level", "non-allowlisted registry change: top-level registry data"),
        ("unexpected_source_truth", "non-allowlisted source_of_truth change: package_sha256"),
        ("wrong_generation_base", "proposed registry generation base does not match manifest base"),
    ],
)
def test_generation_base_transition_mode_rejects_unreviewed_mutation(
    mutation: str,
    expected_error: str,
) -> None:
    base = _registry({"ISSUE-0008": "implemented_initially", "ISSUE-0037": "planned"})
    for record in base["records"]:
        record["verified_commit"] = "d" * 40
        record["acceptance_evidence"] = [
            {
                "status": record["programme_status"],
                "evidence_references": ["prior evidence"],
                "review_reference": "Prior review",
                "reviewer": "Prior reviewer",
                "reviewed_date": "2026-07-20",
            }
        ]
    base["source_of_truth"].update(
        {
            "baseline_commit": "e" * 40,
            "programme_control_state_sha256": "1" * 64,
            "package_sha256": "3" * 64,
        }
    )
    proposed = copy.deepcopy(base)
    _apply_reviewed_transition(
        proposed,
        "ISSUE-0008",
        previous="implemented_initially",
        proposed="integrated",
    )
    proposed["source_of_truth"]["baseline_commit"] = BASE_COMMIT
    proposed["source_of_truth"]["programme_control_state_sha256"] = "2" * 64
    transition_record = next(row for row in proposed["records"] if row["canonical_id"] == "ISSUE-0008")
    if mutation == "unrelated_record":
        transition_record["title"] = "Unreviewed mutation"
    elif mutation == "non_transitioned_record":
        next(row for row in proposed["records"] if row["canonical_id"] == "ISSUE-0037")["title"] = "Mutation"
    elif mutation == "replacement_evidence":
        transition_record["acceptance_evidence"] = transition_record["acceptance_evidence"][-1:]
    elif mutation == "invalid_verified_commit":
        transition_record["verified_commit"] = "not-a-commit"
    elif mutation == "invalid_verified_date":
        transition_record["verified_date"] = "2026-07-20"
    elif mutation == "unexpected_top_level":
        proposed["policy"]["execution_allowed"] = True
    elif mutation == "unexpected_source_truth":
        proposed["source_of_truth"]["package_sha256"] = "4" * 64
    elif mutation == "wrong_generation_base":
        proposed["source_of_truth"]["baseline_commit"] = "f" * 40
    manifest = _base_refresh_transition_manifest(
        base,
        proposed,
        ("ISSUE-0008", "implemented_initially", "integrated"),
    )

    errors = _errors(base, proposed, manifest)

    assert expected_error in errors


def _base_refresh_registry(status: str) -> dict:
    base = _registry({"ISSUE-0008": status})
    base["records"][0].update({"verified_commit": "d" * 40, "acceptance_evidence": []})
    base["source_of_truth"].update(
        {
            "baseline_commit": "e" * 40,
            "programme_control_state_sha256": "1" * 64,
        }
    )
    return base


def test_generation_base_transition_mode_rejects_added_or_removed_issue() -> None:
    base = _base_refresh_registry("planned")
    proposed = copy.deepcopy(base)
    _apply_reviewed_transition(
        proposed,
        "ISSUE-0008",
        previous="planned",
        proposed="in_progress",
    )
    proposed["source_of_truth"]["baseline_commit"] = BASE_COMMIT
    proposed["source_of_truth"]["programme_control_state_sha256"] = "2" * 64
    proposed["records"].append(
        {
            **copy.deepcopy(proposed["records"][0]),
            "canonical_id": "ISSUE-0099",
            "programme_status": "planned",
        }
    )
    manifest = _base_refresh_transition_manifest(
        base,
        proposed,
        ("ISSUE-0008", "planned", "in_progress"),
    )

    errors = _errors(base, proposed, manifest)

    assert "generation-base transition mode cannot add or remove issue IDs" in errors


def test_generation_base_transition_mode_rejects_dependency_evidence_mutation() -> None:
    base = _base_refresh_registry("planned")
    base["records"][0]["dependency_edge_evidence"] = {"ISSUE-0001": {"state": "unresolved"}}
    proposed = copy.deepcopy(base)
    _apply_reviewed_transition(
        proposed,
        "ISSUE-0008",
        previous="planned",
        proposed="in_progress",
    )
    proposed["records"][0]["dependency_edge_evidence"]["ISSUE-0001"] = {"state": "complete"}
    proposed["source_of_truth"]["baseline_commit"] = BASE_COMMIT
    proposed["source_of_truth"]["programme_control_state_sha256"] = "2" * 64
    manifest = _base_refresh_transition_manifest(
        base,
        proposed,
        ("ISSUE-0008", "planned", "in_progress"),
    )

    errors = _errors(base, proposed, manifest)

    assert "non-allowlisted registry change: ISSUE-0008" in errors


def test_generation_base_transition_mode_rejects_reasoned_downgrade() -> None:
    base = _base_refresh_registry("integrated")
    proposed = copy.deepcopy(base)
    _apply_reviewed_transition(
        proposed,
        "ISSUE-0008",
        previous="integrated",
        proposed="planned",
        allow_downgrade=True,
    )
    proposed["source_of_truth"]["baseline_commit"] = BASE_COMMIT
    proposed["source_of_truth"]["programme_control_state_sha256"] = "2" * 64
    manifest = _base_refresh_transition_manifest(
        base,
        proposed,
        ("ISSUE-0008", "integrated", "planned"),
    )
    manifest["allow_downgrade"] = True
    manifest["reason"] = "Attempted downgrade that this mode must reject."

    errors = _errors(base, proposed, manifest)

    assert "manifest registry_migration cannot allow a downgrade" in errors


def test_generation_base_transition_mode_rejects_fabricated_verified_commit() -> None:
    base = _base_refresh_registry("planned")
    proposed = copy.deepcopy(base)
    _apply_reviewed_transition(
        proposed,
        "ISSUE-0008",
        previous="planned",
        proposed="in_progress",
    )
    proposed["source_of_truth"]["baseline_commit"] = BASE_COMMIT
    proposed["source_of_truth"]["programme_control_state_sha256"] = "2" * 64
    record = proposed["records"][0]
    record["verified_commit"] = "c" * 40
    manifest = _base_refresh_transition_manifest(
        base,
        proposed,
        ("ISSUE-0008", "planned", "in_progress"),
    )

    errors = _errors(base, proposed, manifest)

    assert (
        "transition verified_commit is not an ancestor of the reviewed generation base: ISSUE-0008"
        in errors
    )
