"""Deterministic index-methodology evidence importer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


PARSER_VERSION = "2.0"
_KNOWN_PROVIDERS = {
    "ftse russell",
    "lseg",
    "msci",
    "s&p",
    "s&p dow jones",
    "stoxx",
    "solactive",
    "nasdaq",
    "dow jones",
    "ice",
    "index provider",
}
_CRITICAL_WARNINGS = {
    "methodology_version_missing",
    "methodology_date_missing",
    "unknown_provider",
    "unknown_index",
}


@dataclass(frozen=True)
class IndexMethodologyRecord:
    provider: str
    index_series: str
    version: str | None
    document_date: str | None
    eligibility_rules: tuple[str, ...]
    weighting_rules: tuple[str, ...]
    review_frequency: str | None
    caps: tuple[str, ...]
    source_pages: tuple[int, ...]
    confidence: str
    warnings: tuple[str, ...]
    source_sha256: str
    schema_version: int = 2
    manual_review: bool = False
    score_eligible: bool = False


def parse_index_methodology(path: Path, provider: str) -> ParseResult[IndexMethodologyRecord]:
    """Parse index rules while retaining missing/conflicting evidence states."""

    candidate = Path(path)
    source_sha = _sha256_file(candidate) if candidate.exists() and candidate.is_file() else ""
    pages, read_warning = _read_pages(candidate)
    if read_warning is not None:
        return ParseResult((), (read_warning,), "index_methodology", PARSER_VERSION, source_sha, False)
    source_pages = tuple(index for index, text in enumerate(pages, start=1) if text.strip())
    if not source_pages:
        empty_code = "empty_document" if candidate.read_bytes()[:4] == b"%PDF" else "image_only_document"
        return ParseResult(
            (),
            (ParseWarning(empty_code, "Methodology contains no extractable text; manual review is required", "error", "document"),),
            "index_methodology",
            PARSER_VERSION,
            source_sha,
            False,
        )

    text = "\n".join(pages)
    provider_value = str(provider or "").strip()
    warnings: list[ParseWarning] = []
    provider_key = provider_value.casefold()
    if provider_key not in _KNOWN_PROVIDERS and not any(item in provider_key for item in _KNOWN_PROVIDERS if item):
        warnings.append(ParseWarning("unknown_provider", f"Index methodology provider is not recognised: {provider_value or 'missing'}", "warning", "document"))

    version_match = re.search(r"\bv\s*(\d+(?:\.\d+)*)\b", text, flags=re.IGNORECASE)
    date_match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if version_match is None:
        warnings.append(_warning("methodology_version_missing", "Methodology version is unavailable", text, pages, "ground rules"))
    if date_match is None:
        warnings.append(ParseWarning("methodology_date_missing", "Methodology document date is unavailable", "warning", "document"))

    series_match = re.search(r"([A-Z][A-Za-z&.\-/ ]{2,100}Index(?: Series)?)(?=\s+v?\d|\n|,)", text)
    if series_match is None:
        warnings.append(ParseWarning("unknown_index", "Index series could not be identified", "warning", "document"))
        index_series = ""
    else:
        index_series = " ".join(series_match.group(1).split()).strip()
    if not re.search(r"\b(?:FTSE|MSCI|S&P|STOXX|Solactive|Nasdaq|Dow Jones|ICE)\b", text, flags=re.IGNORECASE):
        if not any(item.code == "unknown_index" for item in warnings):
            warnings.append(ParseWarning("unknown_index", "Index series is not from a recognised index family", "warning", "document"))
    if re.search(r"conflict(?:s|ing)?\s+with\s+holdings|holdings\s+conflict", text, flags=re.IGNORECASE):
        warnings.append(ParseWarning("methodology_holdings_conflict", "Methodology and holdings evidence conflict; manual review is required", "warning", _location(text, pages, "conflict")))

    eligibility = _rules(text, ("inclusion", "eligib", "screen", "security"))
    weighting = _rules(text, ("weight", "capitalisation", "capitalization"))
    review_terms = _rules(text, ("review", "rebalance", "reconstitution"))
    caps = _rules(text, ("cap", "capping", "maximum weight"))
    record_warnings = tuple(item.code for item in warnings)
    complete = bool(version_match and date_match and index_series and not warnings)
    record = IndexMethodologyRecord(
        provider=provider_value,
        index_series=index_series or "Unknown index series",
        version=None if version_match is None else version_match.group(1),
        document_date=None if date_match is None else f"{date_match.group(1)} {date_match.group(2)}",
        eligibility_rules=eligibility,
        weighting_rules=weighting,
        review_frequency=review_terms[0] if review_terms else None,
        caps=caps,
        source_pages=source_pages,
        confidence="high" if complete else "partial",
        warnings=record_warnings,
        source_sha256=source_sha,
        manual_review=bool(warnings),
        score_eligible=complete,
    )
    success = not any(item.code in _CRITICAL_WARNINGS for item in warnings)
    return ParseResult((record,), tuple(warnings), "index_methodology", PARSER_VERSION, source_sha, success)


def _read_pages(path: Path) -> tuple[list[str], ParseWarning | None]:
    if not path.exists() or not path.is_file():
        return [], ParseWarning("pdf_read_failed", "Methodology file is unavailable", "error", "document")
    try:
        import pdfplumber
    except Exception as exc:
        return [], ParseWarning(
            "pdf_read_failed",
            f"Could not read methodology: optional pdfplumber dependency is unavailable ({type(exc).__name__})",
            "error",
            "document",
        )
    try:
        with pdfplumber.open(path) as pdf:
            return [_normalise_page(page.extract_text() or "") for page in pdf.pages], None
    except Exception as exc:
        if path.read_bytes()[:4] == b"%PDF":
            return [], ParseWarning("empty_document", "Methodology contains no extractable text", "error", "document")
        return [], ParseWarning("pdf_read_failed", f"Could not read methodology: {type(exc).__name__}", "error", "document")


def _normalise_page(value: str) -> str:
    return "\n".join(" ".join(line.split()) for line in str(value).splitlines() if line.strip())


def _rules(text: str, terms: tuple[str, ...], limit: int = 20) -> tuple[str, ...]:
    rows: list[str] = []
    for raw in text.splitlines():
        value = " ".join(raw.split()).strip()
        if value and any(term in value.casefold() for term in terms):
            if value not in rows:
                rows.append(value[:500])
    return tuple(rows[:limit])


def _location(text: str, pages: list[str], term: str) -> str:
    for index, page in enumerate(pages, start=1):
        if term.casefold() in page.casefold():
            return f"page {index}"
    return "document"


def _warning(code: str, message: str, text: str, pages: list[str], term: str) -> ParseWarning:
    return ParseWarning(code, message, "warning", _location(text, pages, term))


__all__ = ["PARSER_VERSION", "IndexMethodologyRecord", "parse_index_methodology"]
