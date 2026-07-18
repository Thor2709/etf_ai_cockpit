from __future__ import annotations

import json
from pathlib import Path

from scripts.issue_registry_core import (
    PHASES,
    baseline_sha,
    build_registry,
    deterministic_json,
    parse_closed_index,
    parse_open_ledger,
    ready_records,
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
    assert len(registry["records"]) == 159
    assert len(registry["local_only_records"]) == 14
    assert registry["policy"]["execution_allowed"] is False
    assert registry["policy"]["adjusted_prices_required_for_returns"] is True


def test_proposed_ids_and_phase_coverage_are_contiguous() -> None:
    registry = json.loads((ROOT / "issues/issue_registry.json").read_text(encoding="utf-8"))
    proposed = sorted(
        int(record["canonical_id"].rsplit("-", 1)[1])
        for record in registry["records"]
        if record["source_kind"] == "proposed"
    )
    assert proposed == list(range(70, 153))
    phase_ids = {phase["phase"] for phase in PHASES}
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
