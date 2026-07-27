from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "docs" / "architecture"
CANONICAL_DOCUMENTS = (
    ARCHITECTURE / "SDD.md",
    ARCHITECTURE / "README.md",
    ARCHITECTURE / "TRACEABILITY.md",
    ARCHITECTURE / "decisions" / "README.md",
)
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def test_canonical_architecture_set_and_document_control() -> None:
    for path in CANONICAL_DOCUMENTS:
        assert path.is_file(), path
    sdd = CANONICAL_DOCUMENTS[0].read_text(encoding="utf-8")
    assert sdd.startswith("---\ntitle: ETF AI Cockpit Software Design Description\n")
    for field in (
        "status: current",
        "repository: Thor2709/etf_ai_cockpit",
        "verified_against_commit: 6525429d56160167fbeb023636f8b00b05e28336",
        "verified_on: 2026-07-27",
        'architecture_document_version: "1.0"',
        "supersedes: ETF_AI_Portfolio_Cockpit_Master_Spec.md",
    ):
        assert field in sdd
    index = CANONICAL_DOCUMENTS[1].read_text(encoding="utf-8")
    assert "[Software Design Description](SDD.md)" in index
    assert "[Traceability](TRACEABILITY.md)" in index
    assert "[Architecture decisions](decisions/README.md)" in index


def test_architecture_relative_links_resolve_and_are_portable() -> None:
    for document in ARCHITECTURE.rglob("*.md"):
        text = document.read_text(encoding="utf-8")
        if document in CANONICAL_DOCUMENTS:
            assert not re.search(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]", text)
        for target in LINK.findall(text):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("#"):
                continue
            assert not Path(target).is_absolute(), (document, target)
            assert (document.parent / target).resolve().exists(), (document, target)


def test_legacy_banner_and_compatibility_pointer() -> None:
    legacy = (
        ROOT / "docs" / "history" / "ETF_AI_Portfolio_Cockpit_Master_Spec_legacy.md"
    ).read_text(encoding="utf-8")
    assert "LEGACY — historical ETF-only MVP build specification" in legacy
    assert "not the current architecture" in legacy
    compatibility = (ROOT / "ETF_AI_Portfolio_Cockpit_Master_Spec.md").read_text(
        encoding="utf-8"
    )
    assert "docs/architecture/SDD.md" in compatibility
    assert "docs/history/ETF_AI_Portfolio_Cockpit_Master_Spec_legacy.md" in compatibility
    assert "issues/issue_registry.json" in compatibility


def test_current_documents_do_not_reinstate_legacy_authority() -> None:
    for path in CANONICAL_DOCUMENTS:
        text = path.read_text(encoding="utf-8").lower()
        assert not re.search(
            r"(legacy|master)[^\n]{0,80}(single source of truth|current architecture authority)",
            text,
        )


def test_runtime_scenarios_and_transitional_snapshot_are_explicit() -> None:
    sdd = (ARCHITECTURE / "SDD.md").read_text(encoding="utf-8")
    for heading in (
        "### 7.1 Safe startup and first run",
        "### 7.2 Single-instrument analysis",
        "### 7.3 Bulk and screener run",
        "### 7.4 Data import and canonicalisation",
        "### 7.5 Portfolio valuation and analysis",
        "### 7.6 Backtest and paper replay",
        "### 7.7 Optional model invocation and unavailable fallback",
        "### 7.8 Proposal and authority decision",
    ):
        assert heading in sdd
    assert "`services.CockpitSnapshot`" in sdd
    assert "transitional `CockpitSnapshot` in\n`services.py`" in sdd
    assert "`AnalysisSnapshot`" not in sdd


def test_generated_marker_boundaries_remain_present() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN GENERATED FINAL RELEASE PROGRAMME -->" in readme
    assert "<!-- END GENERATED FINAL RELEASE PROGRAMME -->" in readme
    assert "<!-- BEGIN GENERATED FINAL RELEASE CONTROL PLANE -->" in changelog
    assert "<!-- END GENERATED FINAL RELEASE CONTROL PLANE -->" in changelog
