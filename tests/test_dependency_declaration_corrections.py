"""F23/F24 migration tests; all review identities below are synthetic fixtures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import issue_registry_core as core
from scripts import status_transition_guard as guard
from scripts.status_transition_guard import guard_proposal
from scripts.update_programme_control import apply_dependency_declaration_corrections
from scripts.update_programme_status import deterministic_text, progress_markdown, status_payload

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_LEDGER_DIGEST = "c" * 64


@pytest.fixture
def deferred_semantics(monkeypatch):
    """Represent stage-two parser/lane outputs only inside synthetic fixtures."""
    parse = core.parse_final_release_new_issues
    lane = core._capability_lane
    compact = guard._compact_metadata

    def corrected_rows(text):
        rows = parse(text)
        for row in rows:
            row["dependencies"] = [dep for dep in row["dependencies"]
                if (row["issue_id"], dep) not in core.DECLARATION_CORRECTION_PAIRS]
        return rows

    def corrected_compact(block):
        metadata = compact(block)
        if "Blocking dependencies" in metadata:
            metadata["Blocking dependencies"] = metadata["Blocking dependencies"].split(";", 1)[0]
        return metadata

    monkeypatch.setattr(core, "parse_final_release_new_issues", corrected_rows)
    monkeypatch.setattr(core, "_capability_lane", lambda issue, phase:
        {"ISSUE-0167": "PAPER_BROKER_OPERATIONS", "ISSUE-0168": "PORTFOLIO_READ_ONLY"}.get(issue, lane(issue, phase)))
    monkeypatch.setattr(guard, "_compact_metadata", corrected_compact)


def _batch(control):
    return [{"issue_id": issue, "event": {
        "event_type": core.DECLARATION_CORRECTION_EVENT,
        "dependency_edge": {"dependency": dependency, "operation": "remove",
                            "prior_evidence": deepcopy(control["records"][issue]["dependency_edge_evidence"][dependency])},
        "source_reference": f"{core.FINAL_RELEASE_SOURCE.as_posix()}#{issue}",
        "source_sha256": core.FINAL_RELEASE_SPEC_SHA256,
        "review_reference": "synthetic fixture review",
        "evidence_references": ["synthetic fixture evidence"],
        "reviewer": "synthetic fixture reviewer",
        "reviewed_date": "2026-09-08", "verified_commit": "a" * 40,
    }} for issue, dependency in sorted(core.DECLARATION_CORRECTION_PAIRS)]


@pytest.fixture
def migration(monkeypatch, deferred_semantics):
    control = core.load_control_state(ROOT)
    base = json.loads((ROOT / core.REGISTRY_PATH).read_text(encoding="utf-8"))
    proposed_control = apply_dependency_declaration_corrections(control, root=ROOT, corrections=_batch(control))
    monkeypatch.setattr(core, "load_control_state", lambda root: proposed_control)
    proposed = core.build_registry(ROOT, verify_base=False)
    proposed["source_of_truth"]["programme_control_state_sha256"] = hashlib.sha256(core.deterministic_json(proposed_control)).hexdigest()
    proposed["source_of_truth"]["open_ledger_sha256"] = EXPECTED_LEDGER_DIGEST
    return control, base, proposed_control, proposed


def test_deferred_fixture_dependencies_and_lanes(deferred_semantics):
    rows = {row["issue_id"]: row for row in core.parse_final_release_new_issues(
        (ROOT / core.FINAL_RELEASE_SOURCE).read_text(encoding="utf-8"))}
    assert rows["ISSUE-0167"]["dependencies"] == ["ISSUE-0085", "ISSUE-0114", "ISSUE-0127", "ISSUE-0130", "ISSUE-0131"]
    assert rows["ISSUE-0168"]["dependencies"] == ["ISSUE-0108", "ISSUE-0109", "ISSUE-0110", "ISSUE-0111", "ISSUE-0115", "ISSUE-0127", "ISSUE-0161"]
    assert rows["ISSUE-0169"]["dependencies"] == ["ISSUE-0074", "ISSUE-0136", "ISSUE-0142", "ISSUE-0161", "ISSUE-0165", "ISSUE-0167"]
    assert core._capability_lane("ISSUE-0167", "") == "PAPER_BROKER_OPERATIONS"
    assert core._capability_lane("ISSUE-0168", "") == "PORTFOLIO_READ_ONLY"
    assert core._capability_lane("ISSUE-0169", "") == "BULK_SCREENING"


def test_batch_preserves_history_status_and_genuine_evidence(migration):
    control, _, proposed_control, proposed = migration
    for issue in ("ISSUE-0167", "ISSUE-0169"):
        prior = control["records"][issue]
        result = proposed_control["records"][issue]
        assert result["programme_status"] == prior["programme_status"]
        assert result["acceptance_evidence"] == prior["acceptance_evidence"]
        assert result["status_transition"] == prior["status_transition"]
        for dependency, evidence in result["dependency_edge_evidence"].items():
            assert evidence == prior["dependency_edge_evidence"][dependency]
        for event in result["transition_history"]:
            change = event["dependency_edge"]
            assert change["prior_evidence"] == prior["dependency_edge_evidence"][change["dependency"]]
        core.validate_status_replay_prefix_shape(issue, result["transition_history"], result["acceptance_evidence"],
            **{key: result[key] for key in ("programme_status", "dependency_edge_evidence", "verified_commit", "verified_date", "status_transition")})
    for record in proposed["records"]:
        assert set(record["blocking_dependencies"]) == set(record["dependency_edge_evidence"])
    assert proposed["policy"]["execution_allowed"] is False


@pytest.mark.parametrize("mutation", ["pair", "addition", "evidence", "source", "status", "review", "partial"])
def test_writer_rejects_invalid_batch_without_mutation(mutation, deferred_semantics):
    control = core.load_control_state(ROOT)
    before = deepcopy(control)
    batch = _batch(control)
    event = batch[0]["event"]
    if mutation == "pair": event["dependency_edge"]["dependency"] = "ISSUE-0085"
    if mutation == "addition": event["dependency_edge"]["operation"] = "add"
    if mutation == "evidence": event["dependency_edge"]["prior_evidence"]["contract_reference"] = "changed"
    if mutation == "source": event["source_sha256"] = "b" * 64
    if mutation == "status": event["to"] = "integrated"
    if mutation == "review": event["reviewer"] = ""
    if mutation == "partial": batch.pop()
    with pytest.raises(ValueError):
        apply_dependency_declaration_corrections(control, root=ROOT, corrections=batch)
    assert control == before


def _guard(control, base, proposed_control, proposed, mutate_manifest=None):
    digest = lambda value: hashlib.sha256(core.deterministic_json(value)).hexdigest()
    source_digest = base["source_of_truth"]["source_manifest_sha256"]
    manifest = {
        "schema_version": "1.3", "base_commit": "a" * 40, "branch": "fixture",
        "issue_ids": [], "allowed_status_transitions": [],
        "allow_other_status_changes": False, "allow_downgrades": False,
        "allow_downgrade": False,
        "allowed_dependency_edge_updates": [{"issue_id": issue, "dependency_id": dep} for issue, dep in sorted(core.DECLARATION_CORRECTION_PAIRS)],
        "registry_migration": {"mode": "generation_base_and_dependency_edge_corrections", "reason": "synthetic fixture",
            "generator": "scripts/generate_issue_registry.py", "base_registry_sha256": digest(base),
            "proposed_registry_sha256": digest(proposed), "source_manifest_sha256": source_digest,
            "added_issue_ids": [], "removed_issue_ids": []},
    }
    if mutate_manifest: mutate_manifest(manifest)
    status = status_payload(proposed)
    return guard_proposal(base_registry=base, latest_registry=base, proposed_registry=proposed,
        manifest=manifest, current_status=status, current_progress=deterministic_text(progress_markdown(status, proposed)),
        source_manifest_sha256=source_digest, base_control_state=control, latest_control_state=control,
        expected_open_ledger_sha256=EXPECTED_LEDGER_DIGEST,
        proposed_control_state=proposed_control, verified_commit_is_ancestor=lambda sha: sha == "a" * 40)


def test_guard_accepts_only_complete_projection(migration):
    assert _guard(*migration) == []


def test_guard_rejects_expected_ledger_digest_mismatch(migration):
    control, base, proposed_control, proposed = deepcopy(migration)
    proposed["source_of_truth"]["open_ledger_sha256"] = "d" * 64
    assert "declaration correction open-ledger digest mismatch" in _guard(control, base, proposed_control, proposed)


def test_writer_rejects_immutable_source_disagreement(monkeypatch, deferred_semantics):
    control = core.load_control_state(ROOT)
    parse = core.parse_final_release_new_issues
    def disagree(text):
        rows = parse(text)
        next(row for row in rows if row["issue_id"] == "ISSUE-0167")["dependencies"].append("ISSUE-0132")
        return rows
    monkeypatch.setattr(core, "parse_final_release_new_issues", disagree)
    with pytest.raises(ValueError, match="contradicts source"):
        apply_dependency_declaration_corrections(control, root=ROOT, corrections=_batch(control))


@pytest.mark.parametrize("mutation", ["replacement", "deletion", "entry_deletion", "tampering", "reordering", "restoration"])
def test_guard_rejects_reconciliation_corruption(migration, mutation):
    control, base, proposed_control, proposed = deepcopy(migration)
    reconciliation = proposed["dependency_reconciliation"]
    if mutation == "replacement":
        proposed["dependency_reconciliation"] = [{"fabricated": True}]
    elif mutation == "deletion":
        del proposed["dependency_reconciliation"]
    elif mutation == "entry_deletion":
        reconciliation.pop()
    elif mutation == "tampering":
        reconciliation[0]["reason"] = "fabricated reason"
    elif mutation == "reordering":
        reconciliation.reverse()
    elif mutation == "restoration":
        reconciliation.append(next(entry for entry in base["dependency_reconciliation"]
            if (entry["source_id"], entry["dependency"]) in core.DECLARATION_CORRECTION_PAIRS))
    # _guard recomputes the manifest/status hashes so this proves semantic
    # rejection even when an attacker refreshes all projection checksums.
    errors = _guard(control, base, proposed_control, proposed)
    assert "declaration correction dependency reconciliation projection mismatch" in errors


@pytest.mark.parametrize("mutation", ["status", "genuine_edge", "history", "stale_hash", "pair"])
def test_guard_rejects_unrelated_or_stale_changes(migration, mutation):
    control, base, proposed_control, proposed = deepcopy(migration)
    change_manifest = None
    if mutation == "status": proposed_control["records"]["ISSUE-0167"]["programme_status"] = "integrated"
    if mutation == "genuine_edge": proposed["records"][0]["title"] = "unrelated"
    if mutation == "history": proposed_control["records"]["ISSUE-0167"]["transition_history"][0]["dependency_edge"]["prior_evidence"]["contract_reference"] = "changed"
    if mutation == "stale_hash": change_manifest = lambda manifest: manifest["registry_migration"].update(proposed_registry_sha256="b" * 64)
    if mutation == "pair": change_manifest = lambda manifest: manifest["allowed_dependency_edge_updates"].pop()
    assert _guard(control, base, proposed_control, proposed, change_manifest)
