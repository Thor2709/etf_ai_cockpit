from __future__ import annotations

from etf_cockpit.data.contracts import SourceAuthority
from types import SimpleNamespace

from etf_cockpit.data.evidence_ledger import EvidenceSource, ledger_entry_for_component


def test_missing_source_or_conflict_is_not_score_eligible() -> None:
    source = EvidenceSource("prices", "row-1", SourceAuthority.VENDOR, "2026-07-10", "fresh")
    eligible = ledger_entry_for_component("X", "momentum", 7.0, source)
    conflicted = ledger_entry_for_component("X", "value", 7.0, source, conflict_id="c1")
    missing = ledger_entry_for_component("X", "quality", None, None)
    assert eligible.score_eligible is True
    assert conflicted.score_eligible is False
    assert missing.score_eligible is False


def test_evidence_source_provenance_and_low_authority_are_visible() -> None:
    source = EvidenceSource(
        "prices",
        "community:post-1",
        SourceAuthority.COMMUNITY,
        "2026-07-10",
        "fresh",
        confidence="low",
        quality=0.2,
        provider_id="community-feed",
    )
    entry = ledger_entry_for_component("X", "news_context", 7.0, source)
    assert entry.score_eligible is False
    assert entry.source is source
    assert entry.reason.startswith("ineligible:")


def test_component_adapter_uses_conflict_and_freshness_metadata() -> None:
    component = SimpleNamespace(key="momentum", score_10=8.0, raw_score=0.6, status="OK")
    source = EvidenceSource("prices", "yfinance:prices", SourceAuthority.VENDOR, "2026-07-10", "stale")
    entry = ledger_entry_for_component(component, source, conflict_id="conflict-1")
    assert entry.instrument_id == ""
    assert entry.component == "momentum"
    assert entry.value == 8.0
    assert entry.score_eligible is False
    assert "conflict" in entry.reason
