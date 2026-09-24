"""Immutable final-release dependency clauses and capability ownership."""

from pathlib import Path

import pytest

from scripts import issue_registry_core as core


@pytest.mark.parametrize("suffix", [
    "; downstream consumers ISSUE-0132, ISSUE-0133; execution disabled.",
    "; execution disabled.",
    ".",
    "",
])
def test_compact_dependencies_stop_at_clause_boundary(suffix):
    metadata = core._compact_metadata(
        "**Canonical metadata:** P1; owner `analysis`; phase `analysis`; "
        f"depends on ISSUE-0085, ISSUE-0114{suffix}"
    )
    assert metadata == {
        "Priority": "P1", "Owner": "analysis", "Phase": "analysis",
        "Blocking dependencies": "ISSUE-0085, ISSUE-0114",
    }


def test_final_release_dependencies_match_immutable_source_clauses():
    root = Path(__file__).resolve().parents[1]
    rows = {row["issue_id"]: row for row in core.parse_final_release_new_issues(
        (root / core.FINAL_RELEASE_SOURCE).read_text(encoding="utf-8")
    )}
    assert rows["ISSUE-0167"]["dependencies"] == [
        "ISSUE-0085", "ISSUE-0114", "ISSUE-0127", "ISSUE-0130", "ISSUE-0131",
    ]
    assert rows["ISSUE-0168"]["dependencies"] == [
        "ISSUE-0108", "ISSUE-0109", "ISSUE-0110", "ISSUE-0111", "ISSUE-0115",
        "ISSUE-0127", "ISSUE-0161",
    ]
    assert rows["ISSUE-0169"]["dependencies"] == [
        "ISSUE-0074", "ISSUE-0136", "ISSUE-0142", "ISSUE-0161", "ISSUE-0165", "ISSUE-0167",
    ]


@pytest.mark.parametrize(("issue", "lane"), [
    ("ISSUE-0133", "LIVE_CANARY_SCAFFOLD_DISABLED"),
    ("ISSUE-0165", "BULK_SCREENING"),
    ("ISSUE-0166", "BULK_SCREENING"),
    ("ISSUE-0167", "PAPER_BROKER_OPERATIONS"),
    ("ISSUE-0168", "PORTFOLIO_READ_ONLY"),
    ("ISSUE-0169", "BULK_SCREENING"),
    ("ISSUE-0170", "FUND_ANALYSIS"),
])
def test_capability_lanes_preserve_neighbours_and_disabled_canary(issue, lane):
    assert core._capability_lane(issue, "") == lane
