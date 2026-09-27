"""Deterministic extraction of SFDR disclosure evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


PARSER_VERSION = "1.0"
_DOCUMENT_TYPES = {"factsheet", "prospectus", "periodic_report"}
_SFDR_SCOPE_MARKER = re.compile(r"\b(?:SFDR|2019\s*/\s*2088|Sustainable Finance Disclosure)\b", re.IGNORECASE)
_PRODUCT_SCOPE = re.compile(r"\b(?:fund|product|financial\s+product)\b", re.IGNORECASE)


@dataclass(frozen=True)
class SfdrRecord:
    classification: str
    methodology_disclosed: bool
    data_sources_disclosed: bool
    sustainable_characteristics: str | None
    taxonomy_alignment_pct: float | None
    document_type: str
    document_date: str | None
    source_pages: tuple[int, ...]
    warnings: tuple[str, ...]
    source_sha256: str
    schema_version: int = 1
    manual_review: bool = False
    score_eligible: bool = False
    execution_allowed: bool = False


def parse_sfdr(path: Path, document_type: str | None = None) -> ParseResult[SfdrRecord]:
    candidate = Path(path)
    source_sha = _sha256_file(candidate) if candidate.exists() and candidate.is_file() else ""
    pages, read_warning = _read_pages(candidate)
    if read_warning is not None:
        return ParseResult((), (read_warning,), "sfdr", PARSER_VERSION, source_sha, False)
    source_pages = tuple(index for index, text in enumerate(pages, start=1) if text.strip())
    if not source_pages:
        return ParseResult(
            (),
            (ParseWarning("image_only_document", "SFDR disclosure contains no extractable text; manual review is required", "error", "document"),),
            "sfdr",
            PARSER_VERSION,
            source_sha,
            False,
        )

    text = "\n".join(pages)
    return parse_sfdr_text(text, document_type=document_type, source_sha256=source_sha, source_pages=source_pages)


def parse_sfdr_text(
    text: str,
    document_type: str | None = None,
    *,
    source_sha256: str = "",
    source_pages: tuple[int, ...] = (1,),
) -> ParseResult[SfdrRecord]:
    """Parse extracted SFDR text using only scoped article references.

    An ``Article 6/8/9`` reference is SFDR-scoped when its nearby text (within
    roughly 80 characters) names SFDR, Regulation 2019/2088, or the Sustainable
    Finance Disclosure Regulation, or when it explicitly describes a fund,
    product, or financial product.  Bare Taxonomy Regulation references are
    ignored.  One distinct scoped article determines the classification;
    multiple distinct articles are ambiguous and require manual review.
    """

    text = str(text or "")
    pages = [text]
    warnings: list[ParseWarning] = []
    classification = _classification(text)
    methodology = bool(re.search(r"\b(?:methodology|binding elements|selection methodology|investment strategy)\b", text, re.IGNORECASE))
    data_sources = bool(re.search(r"\b(?:data sources?|source of data|external data|data provider|data quality)\b", text, re.IGNORECASE))
    if classification in {"article_8", "article_9"}:
        if not methodology:
            warnings.append(_warning("sfdr_missing_methodology", "Article 8/9 SFDR disclosure does not state a methodology disclosure", text, pages, "methodology"))
        if not data_sources:
            warnings.append(_warning("sfdr_missing_data_sources", "Article 8/9 SFDR disclosure does not state a data-source disclosure", text, pages, "data source"))
    elif classification == "unclassified":
        warnings.append(ParseWarning("sfdr_unclassified", "SFDR classification is unavailable; it was not defaulted to Article 6", "warning", "document"))
    elif classification == "ambiguous":
        warnings.append(ParseWarning("sfdr_ambiguous_classification", "Several distinct SFDR article classifications were found; manual review is required", "warning", "document"))

    characteristic = _promoted_text(text)
    taxonomy = _taxonomy_pct(text)
    detected_type = _document_type(text, document_type)
    date_value = _document_date(text)
    record = SfdrRecord(
        classification=classification,
        methodology_disclosed=methodology,
        data_sources_disclosed=data_sources,
        sustainable_characteristics=characteristic,
        taxonomy_alignment_pct=taxonomy,
        document_type=detected_type,
        document_date=date_value,
        source_pages=source_pages,
        warnings=tuple(item.code for item in warnings),
            source_sha256=source_sha256,
        manual_review=bool(warnings),
        score_eligible=False,
        execution_allowed=False,
    )
    return ParseResult((record,), tuple(warnings), "sfdr", PARSER_VERSION, source_sha256, True)


def _read_pages(path: Path) -> tuple[list[str], ParseWarning | None]:
    if not path.exists() or not path.is_file():
        return [], ParseWarning("pdf_read_failed", "SFDR disclosure file is unavailable", "error", "document")
    try:
        import pdfplumber
    except Exception as exc:
        return [], ParseWarning("pdf_read_failed", f"Could not read SFDR disclosure: optional pdfplumber dependency is unavailable ({type(exc).__name__})", "error", "document")
    try:
        with pdfplumber.open(path) as pdf:
            return [_normalise_page(page.extract_text() or "") for page in pdf.pages], None
    except Exception as exc:
        return [], ParseWarning("pdf_read_failed", f"Could not read SFDR disclosure: {type(exc).__name__}", "error", "document")


def _normalise_page(value: str) -> str:
    return "\n".join(" ".join(line.split()) for line in str(value).splitlines() if line.strip())


def _classification(text: str) -> str:
    scoped = _scoped_articles(text)
    if not scoped:
        return "unclassified"
    if len(scoped) > 1:
        return "ambiguous"
    return f"article_{next(iter(scoped))}"


def _scoped_articles(text: str) -> set[str]:
    scoped: set[str] = set()
    for match in re.finditer(r"\bArticle\s*([689])\b", text, flags=re.IGNORECASE):
        start, end = match.span()
        window = text[max(0, start - 80):min(len(text), end + 80)]
        tail = text[end:min(len(text), end + 80)]
        has_sfdr_marker = bool(_SFDR_SCOPE_MARKER.search(window))
        has_product_phrase = bool(_PRODUCT_SCOPE.search(tail))
        taxonomy_only = bool(re.search(r"\b(?:2020\s*/\s*852|Taxonomy Regulation)\b", window, re.IGNORECASE)) and not has_sfdr_marker
        if not taxonomy_only and (has_sfdr_marker or has_product_phrase):
            scoped.add(match.group(1))
    return scoped


def _promoted_text(text: str) -> str | None:
    match = re.search(
        r"(?:environmental\s+and/or\s+social\s+characteristics|sustainable\s+investment\s+objective|promoted\s+(?:E/S|environmental|social)\s+characteristics)\s*[:\-]?\s*([^\n.;]{10,500})",
        text,
        flags=re.IGNORECASE,
    )
    return " ".join(match.group(1).split()).strip()[:500] if match else None


def _taxonomy_pct(text: str) -> float | None:
    match = re.search(
        r"(?:taxonomy(?:[- ]aligned)?|aligned with the EU taxonomy)[^\n%]{0,80}?([0-9]+(?:[.,][0-9]+)?)\s*%|"
        r"([0-9]+(?:[.,][0-9]+)?)\s*%[^\n]{0,80}taxonomy",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    value = match.group(1) or match.group(2)
    try:
        parsed = float(value.replace(",", "."))
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 100 else None


def _document_type(text: str, supplied: str | None) -> str:
    value = str(supplied or "").strip().casefold().replace(" ", "_")
    if value in _DOCUMENT_TYPES:
        return value
    if re.search(r"periodic\s+report|annual\s+report|semi[- ]annual", text, re.IGNORECASE):
        return "periodic_report"
    if re.search(r"prospectus", text, re.IGNORECASE):
        return "prospectus"
    if re.search(r"fact\s*sheet", text, re.IGNORECASE):
        return "factsheet"
    return "unspecified"


def _document_date(text: str) -> str | None:
    match = re.search(r"(?:document\s+date|dated|as\s+of|date)\s*[:\-]?\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text, re.IGNORECASE)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"(?:document\s+date|dated|as\s+of|date)\s*[:\-]?\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text, re.IGNORECASE)
    if match:
        return f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
    return None


def _warning(code: str, message: str, text: str, pages: list[str], term: str) -> ParseWarning:
    location = "document"
    for index, page in enumerate(pages, start=1):
        if term.casefold() in page.casefold():
            location = f"page {index}"
            break
    return ParseWarning(code, message, "warning", location)


__all__ = ["PARSER_VERSION", "SfdrRecord", "parse_sfdr", "parse_sfdr_text"]
