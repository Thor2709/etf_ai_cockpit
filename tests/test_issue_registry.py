from __future__ import annotations

import json
from pathlib import Path

from scripts.issue_registry_core import (
    baseline_sha,
    build_registry,
    deterministic_json,
    parse_closed_index,
    parse_open_ledger,
    ready_records,
    sha256_text_file,
    validate_registry,
)
from scripts.generate_completion_documents import write_text
from scripts.update_programme_status import deterministic_text, progress_markdown, status_payload


ROOT = Path(__file__).resolve().parents[1]


def test_baseline_sha_uses_recorded_reconciliation_intake(tmp_path: Path) -> None:
    intake = tmp_path / "docs" / "product-completion" / "reconciliation" / "2026-07-17-3321ebd" / "intake-report.json"
    intake.parent.mkdir(parents=True)
    intake.write_text(json.dumps({"baseline_commit": "a" * 40}), encoding="utf-8")
    assert baseline_sha(tmp_path) == "a" * 40


def test_ledgers_have_disjoint_canonical_sections() -> None:
    open_ids = set(parse_open_ledger(ROOT / "issues/open.md"))
    closed_ids = set(parse_closed_index(ROOT / "issues/closed.md"))
    assert not open_ids & closed_ids
    assert "ISSUE-0067" in open_ids
    assert "ISSUE-0069" in closed_ids
    assert "UPDATEV2-0010" in closed_ids
    assert "UPDATEV2-0022" in closed_ids


def test_registry_has_stable_mapping_and_acyclic_blocking_graph() -> None:
    registry = build_registry(ROOT, baseline="3321ebd0733f188f25668f67e3b41fd90808591d")
    errors = validate_registry(registry, open_ids=set(parse_open_ledger(ROOT / "issues/open.md")), closed_ids=set(parse_closed_index(ROOT / "issues/closed.md")))
    assert errors == []
    assert len(registry["records"]) == registry["counts"]["package_records"]
    assert registry["counts"]["final_release_new_records"] == 24
    assert len(registry["local_only_records"]) == 14
    assert registry["policy"]["execution_allowed"] is False
    assert registry["policy"]["adjusted_prices_required_for_returns"] is True


def test_proposed_ids_and_phase_coverage_are_source_derived() -> None:
    registry = json.loads((ROOT / "issues/issue_registry.json").read_text(encoding="utf-8"))
    proposed = sorted(
        int(record["canonical_id"].rsplit("-", 1)[1])
        for record in registry["records"]
        if record["classification"] == "proposed_new"
    )
    expected = sorted(
        int(record["canonical_id"].rsplit("-", 1)[1])
        for record in registry["records"]
        if record["classification"] == "proposed_new"
    )
    assert proposed == expected
    phase_ids = {phase["phase"] for phase in registry["roadmap_phases"]}
    assert {record["phase"] for record in registry["records"]} <= phase_ids


def test_registry_json_and_ready_order_are_deterministic() -> None:
    registry = json.loads((ROOT / "issues/issue_registry.json").read_text(encoding="utf-8"))
    generated = deterministic_json(registry)
    assert b"\r\n" not in generated
    assert generated == (ROOT / "issues/issue_registry.json").read_bytes()
    ready = ready_records(registry)
    assert [(record["priority"], record["canonical_id"]) for record in ready] == sorted(
        (record["priority"], record["canonical_id"]) for record in ready
    )


def test_registry_generation_preserves_accepted_statuses_when_adding_one_transition() -> None:
    registry = build_registry(ROOT, baseline="4627118588a0764459ef1552f7d201331db127a3")
    statuses = {record["canonical_id"]: record["programme_status"] for record in registry["records"]}

    assert statuses["ISSUE-0121"] == "implemented_initially"
    assert statuses["ISSUE-0129"] == "integrated"
    assert statuses["ISSUE-0130"] == "integrated"
    assert statuses["ISSUE-0117"] == "implemented_initially"
    assert statuses["ISSUE-0120"] == "implemented_initially"


def test_completion_markdown_writer_is_lf_deterministic(tmp_path: Path) -> None:
    destination = tmp_path / "generated.md"

    write_text(destination, "one\r\ntwo\rthree")

    assert destination.read_bytes() == b"one\ntwo\nthree\n"
    assert b"\r\n" not in destination.read_bytes()


def test_programme_status_markdown_is_lf_deterministic() -> None:
    registry = json.loads((ROOT / "issues/issue_registry.json").read_text(encoding="utf-8"))

    generated = deterministic_text(progress_markdown(status_payload(registry), registry))

    assert b"\r" not in generated
    assert generated.endswith(b"\n")


def test_checked_out_programme_status_markdown_is_byte_fresh() -> None:
    registry = json.loads((ROOT / "issues/issue_registry.json").read_text(encoding="utf-8"))
    generated = deterministic_text(progress_markdown(status_payload(registry), registry))
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    assert "docs/product-completion/PROGRESS.md text eol=lf" in attributes
    assert (ROOT / "docs/product-completion/PROGRESS.md").read_bytes() == generated


def test_source_manifest_hash_is_stable_across_checkout_line_endings(tmp_path: Path) -> None:
    manifest = tmp_path / "SOURCE_MANIFEST.sha256"
    manifest.write_bytes(b"# manifest\r\nabc  file.txt\r\n")
    crlf_hash = sha256_text_file(manifest)

    manifest.write_bytes(b"# manifest\nabc  file.txt\n")

    assert sha256_text_file(manifest) == crlf_hash
