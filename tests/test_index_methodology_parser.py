from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pandas as pd

import etf_cockpit.parsers.index_methodology as methodology_module
from etf_cockpit.parsers.index_methodology import IndexMethodologyRecord, parse_index_methodology


FIXTURE = Path("tests/fixtures/official/index_methodology/ftse-global-equity-index-series-ground-rules.pdf")


def test_official_methodology_extracts_version_provider_and_review_terms() -> None:
    result = parse_index_methodology(FIXTURE, "FTSE Russell")
    assert result.success is True
    record = result.records[0]
    assert record.provider == "FTSE Russell"
    assert record.version == "14.2"
    assert "FTSE Global Equity" in record.index_series
    assert record.source_pages


def test_official_methodology_ignores_toc_noise_and_requires_contextual_evidence() -> None:
    result = parse_index_methodology(FIXTURE, "FTSE Russell")

    assert result.success is True
    record = result.records[0]

    # The table of contents contains "Periodic review" and index names with
    # "cap", but neither is methodology evidence.  The body contains the
    # labelled review cadence and explicit 10% capping rule instead.
    assert record.review_frequency is not None
    assert "semi-annually" in record.review_frequency.casefold()
    assert "section 7 periodic review" not in record.review_frequency.casefold()
    assert any("capped at 10%" in rule.casefold() for rule in record.caps)
    assert all("index series" not in rule.casefold() for rule in record.caps)
    assert result.warnings == ()
    assert record.confidence == "high"
    assert record.manual_review is False
    assert record.score_eligible is True


def test_empty_pdf_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF")
    result = parse_index_methodology(path, "FTSE Russell")
    assert result.success is False
    assert any(item.code == "empty_document" for item in result.warnings)


class _FakePdf:
    def __init__(self, pages: list[str]):
        self.pages = [SimpleNamespace(extract_text=lambda text=text: text) for text in pages]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _fake_pdfplumber(monkeypatch, pages: list[str]) -> None:
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: _FakePdf(pages)))


def test_missing_version_and_date_are_manual_review_with_source_pages(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "methodology.pdf"
    path.write_bytes(b"synthetic-methodology")
    _fake_pdfplumber(monkeypatch, ["FTSE Global Equity Index Series\nInclusion criteria and eligible securities."])

    result = parse_index_methodology(path, "FTSE Russell")

    assert result.records and result.success is False
    record = result.records[0]
    assert record.version is None and record.document_date is None
    assert record.manual_review is True
    assert record.source_pages == (1,)
    assert {item.code for item in result.warnings} >= {"methodology_version_missing", "methodology_date_missing"}


def test_unknown_provider_and_index_are_not_accepted(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "methodology.pdf"
    path.write_bytes(b"synthetic-methodology")
    _fake_pdfplumber(monkeypatch, ["Some unrelated benchmark rules\nv1.0\nJanuary 2026"])

    result = parse_index_methodology(path, "Unknown Provider")

    assert result.records and result.success is False
    assert result.records[0].manual_review is True
    assert {item.code for item in result.warnings} >= {"unknown_provider", "unknown_index"}


def test_methodology_conflict_warning_is_retained(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "methodology.pdf"
    path.write_bytes(b"synthetic-methodology")
    _fake_pdfplumber(
        monkeypatch,
        ["FTSE Global Equity Index Series v14.2\nJuly 2026\nconflict with holdings: cap 5%"],
    )

    result = parse_index_methodology(path, "FTSE Russell")

    assert result.records and any(item.code == "methodology_holdings_conflict" for item in result.warnings)


def _complete_methodology(**changes: object) -> IndexMethodologyRecord:
    values: dict[str, object] = {
        "provider": "FTSE Russell",
        "index_series": "FTSE Global Equity Index Series",
        "version": "14.2",
        "document_date": "2026-07-01",
        "eligibility_rules": ("Eligible securities from developed markets",),
        "weighting_rules": ("Free-float market capitalisation weighting; maximum weight 5%",),
        "review_frequency": "Quarterly review",
        "caps": ("Maximum weight 5%",),
        "source_pages": (1,),
        "confidence": "high",
        "warnings": (),
        "source_sha256": "m" * 64,
        "score_eligible": True,
    }
    values.update(changes)
    return IndexMethodologyRecord(**values)


def test_methodology_holdings_helper_flags_material_weight_conflict() -> None:
    holdings = pd.DataFrame(
        {
            "security": ["Large constituent", "Small constituent"],
            "weight": [0.08, 0.02],
            "region": ["Developed Markets", "Developed Markets"],
        }
    )

    assert hasattr(methodology_module, "assess_methodology_holdings")
    assessment = methodology_module.assess_methodology_holdings(_complete_methodology(), holdings)

    assert assessment.conflict is True
    assert assessment.manual_review is True
    assert assessment.score_eligible is False
    assert any(item.code == "methodology_holdings_conflict" for item in assessment.warnings)


def test_methodology_holdings_helper_preserves_no_conflict_and_unavailable_states() -> None:
    aligned = pd.DataFrame(
        {
            "security": ["A", "B"],
            "weight": [0.04, 0.02],
            "region": ["Developed Markets", "Developed Markets"],
        }
    )
    assert hasattr(methodology_module, "assess_methodology_holdings")
    aligned_assessment = methodology_module.assess_methodology_holdings(_complete_methodology(), aligned)
    unavailable_assessment = methodology_module.assess_methodology_holdings(_complete_methodology(), pd.DataFrame())

    assert aligned_assessment.conflict is False
    assert aligned_assessment.manual_review is False
    assert aligned_assessment.score_eligible is True
    assert unavailable_assessment.availability == "unavailable"
    assert unavailable_assessment.manual_review is True
    assert unavailable_assessment.score_eligible is False
    assert any(item.code == "methodology_holdings_unavailable" for item in unavailable_assessment.warnings)
