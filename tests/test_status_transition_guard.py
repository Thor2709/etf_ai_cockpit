from __future__ import annotations

import copy

import pytest

from scripts.status_transition_guard import guard_proposal
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
