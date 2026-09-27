from pathlib import Path

import pytest

import etf_cockpit.parsers.sfdr as sfdr


def _parse(monkeypatch: pytest.MonkeyPatch, text: str, document_type: str = "factsheet"):
    source = Path("tests/fixtures/sfdr/article-8.txt")
    monkeypatch.setattr(sfdr, "_read_pages", lambda _path: ([text], None))
    return sfdr.parse_sfdr(source, document_type=document_type)


def test_article_8_extracts_methodology_and_characteristics(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Path("tests/fixtures/sfdr/article-8.txt").read_text(encoding="utf-8")
    result = _parse(monkeypatch, fixture)
    record = result.records[0]
    assert record.classification == "article_8"
    assert record.methodology_disclosed is True
    assert record.data_sources_disclosed is True
    assert "climate transition" in str(record.sustainable_characteristics)
    assert record.document_type == "factsheet"
    assert record.document_date == "2026-09-01"
    assert record.score_eligible is False
    assert record.execution_allowed is False


def test_article_9_extracts_explicit_taxonomy_percentage(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Path("tests/fixtures/sfdr/article-9.txt").read_text(encoding="utf-8")
    result = _parse(monkeypatch, fixture, document_type="periodic_report")
    record = result.records[0]
    assert record.classification == "article_9"
    assert record.taxonomy_alignment_pct == 25.0
    assert record.document_type == "periodic_report"
    assert record.document_date == "2026-09-01"


def test_article_8_missing_disclosures_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _parse(monkeypatch, "Article 8 financial product")
    codes = {warning.code for warning in result.warnings}
    assert {"sfdr_missing_methodology", "sfdr_missing_data_sources"} <= codes
    assert result.records[0].manual_review is True


def test_missing_classification_remains_unclassified(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _parse(monkeypatch, "Sustainability disclosure with no SFDR article classification")
    assert result.records[0].classification == "unclassified"
    assert result.records[0].classification != "article_6"


def test_taxonomy_article_reference_is_not_sfdr_classification() -> None:
    result = sfdr.parse_sfdr_text("Article 8 of Regulation (EU) 2020/852 applies to taxonomy alignment.")
    assert result.records[0].classification == "unclassified"


def test_distinct_sfdr_articles_are_ambiguous() -> None:
    result = sfdr.parse_sfdr_text(
        "This is an Article 8 product under SFDR. The marketing section also refers to Article 9 products."
    )
    assert result.records[0].classification == "ambiguous"
    assert result.records[0].manual_review is True
    assert "sfdr_ambiguous_classification" in {warning.code for warning in result.warnings}


def test_unknown_document_type_is_unspecified() -> None:
    result = sfdr.parse_sfdr_text("SFDR disclosure with no document family label.", document_type="other")
    assert result.records[0].document_type == "unspecified"
