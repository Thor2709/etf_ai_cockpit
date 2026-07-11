from __future__ import annotations

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.evidence_ledger import EvidenceSource, ledger_entry_for_component


def test_missing_source_or_conflict_is_not_score_eligible() -> None:
    source = EvidenceSource("prices", "row-1", SourceAuthority.VENDOR, "2026-07-10", "fresh")
    eligible = ledger_entry_for_component("X", "momentum", 7.0, source)
    conflicted = ledger_entry_for_component("X", "value", 7.0, source, conflict_id="c1")
    missing = ledger_entry_for_component("X", "quality", None, None)
    assert eligible.score_eligible is True
    assert conflicted.score_eligible is False
    assert missing.score_eligible is False
