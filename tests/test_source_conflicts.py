from __future__ import annotations

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.source_conflicts import MetricClaim, resolve_conflicts


def test_material_conflict_is_visible_and_not_silently_overwritten() -> None:
    result = resolve_conflicts(
        [
            MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "v1"),
            MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "o1"),
        ]
    )
    assert result.selected["revenue"].value == 120
    assert result.conflicts[0].requires_manual_review is True
    assert result.conflicts[0].source_ids == ("o1", "v1")


def test_conflict_resolution_has_deterministic_manual_review_reason() -> None:
    claims = [
        MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "v1"),
        MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "o1", unit="USD", period="FY2025", as_of="2026-02-01"),
    ]
    first = resolve_conflicts(claims)
    second = resolve_conflicts(reversed(claims))
    assert first == second
    conflict = first.conflicts[0]
    assert conflict.resolution_status == "manual_review"
    assert "official" in conflict.reason.lower()
    assert "vendor" in conflict.reason.lower()
    assert conflict.conflict_id
    assert first.claims == second.claims
