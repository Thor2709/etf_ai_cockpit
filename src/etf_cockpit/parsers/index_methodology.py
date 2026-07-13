"""Deterministic index-methodology evidence importer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re

import pandas as pd

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


@dataclass(frozen=True)
class MethodologyHoldingsAssessment:
    """Deterministic comparison of methodology rules with normalised holdings."""

    warnings: tuple[ParseWarning, ...]
    manual_review: bool
    score_eligible: bool
    availability: str
    conflict: bool


def assess_methodology_holdings(
    record: IndexMethodologyRecord,
    holdings: pd.DataFrame | None,
) -> MethodologyHoldingsAssessment:
    """Compare explicit methodology constraints with actual holdings rows.

    The helper accepts the canonical normalised holdings frame (``security`` /
    ``weight`` plus optional region aliases).  Missing holdings are an explicit
    unavailable/manual-review state; no conflict is inferred from an absent
    frame.  Only material, directly stated cap or geography rules can produce
    a conflict warning.
    """

    if holdings is None or holdings.empty:
        warning = ParseWarning(
            "methodology_holdings_unavailable",
            "Methodology holdings comparison is unavailable because no holdings rows were supplied",
            "warning",
            "holdings",
        )
        return MethodologyHoldingsAssessment((warning,), True, False, "unavailable", False)

    frame = holdings.copy()
    security_column = next((column for column in ("security", "holding_name", "security_name", "name", "ticker", "symbol", "isin") if column in frame.columns), None)
    weight_column = next((column for column in ("weight", "weight_decimal", "weight_percent", "weight_pct") if column in frame.columns), None)
    if security_column is None or weight_column is None:
        warning = ParseWarning(
            "methodology_holdings_unavailable",
            "Methodology holdings comparison requires normalised security and weight columns",
            "warning",
            "holdings",
        )
        return MethodologyHoldingsAssessment((warning,), True, False, "unavailable", False)

    weights = pd.to_numeric(frame[weight_column], errors="coerce")
    if weights.isna().any():
        warning = ParseWarning("methodology_holdings_unavailable", "Methodology holdings contain non-numeric weights", "warning", "holdings")
        return MethodologyHoldingsAssessment((warning,), True, False, "unavailable", False)
    weights = weights.astype(float)
    if weight_column in {"weight_percent", "weight_pct"} or float(weights.max()) > 1:
        weights = weights / 100.0
    if (weights < 0).any() or (weights > 1).any():
        warning = ParseWarning("methodology_holdings_unavailable", "Methodology holdings contain unusable weights", "warning", "holdings")
        return MethodologyHoldingsAssessment((warning,), True, False, "unavailable", False)

    rules_text = " ".join((*record.eligibility_rules, *record.weighting_rules, *record.caps)).casefold()
    conflicts: list[str] = []
    cap_match = re.search(
        r"(?:maximum|max(?:imum)?\s+weight|cap(?:ping)?).{0,40}?(\d+(?:\.\d+)?)\s*%|"
        r"(\d+(?:\.\d+)?)\s*%[^.;]{0,20}(?:cap|maximum)",
        rules_text,
        re.IGNORECASE,
    )
    if cap_match is not None:
        cap_text = cap_match.group(1) or cap_match.group(2)
        cap = float(cap_text) / 100.0
        if bool((weights > cap + 1e-9).any()):
            conflicts.append(f"holding weight exceeds stated {cap_text}% cap")

    region_column = next((column for column in ("region", "market", "country_group", "geography") if column in frame.columns), None)
    if region_column is not None:
        regions = frame[region_column].fillna("").astype(str).str.casefold()
        if "developed" in rules_text and bool(regions.str.contains("emerging|frontier", regex=True).any()):
            conflicts.append("holding geography is outside the stated developed-market eligibility")
        if "emerging" in rules_text and bool(regions.str.contains("developed", regex=True).any()) and "developed" not in rules_text:
            conflicts.append("holding geography is outside the stated emerging-market eligibility")

    if conflicts:
        warning = ParseWarning(
            "methodology_holdings_conflict",
            "Methodology and holdings evidence materially disagree: " + "; ".join(conflicts),
            "warning",
            "holdings",
        )
        return MethodologyHoldingsAssessment((warning,), True, False, "available", True)
    return MethodologyHoldingsAssessment(
        (),
        bool(record.manual_review),
        bool(record.score_eligible),
        "available",
        False,
    )


def apply_methodology_holdings_assessment(
    result: ParseResult[IndexMethodologyRecord],
    holdings: pd.DataFrame | None,
) -> ParseResult[IndexMethodologyRecord]:
    """Attach holdings comparison warnings to persisted methodology evidence."""

    if not result.records:
        return result
    updated_records: list[IndexMethodologyRecord] = []
    extra_warnings: list[ParseWarning] = []
    for record in result.records:
        assessment = assess_methodology_holdings(record, holdings)
        extra_warnings.extend(assessment.warnings)
        if assessment.warnings:
            updated_records.append(
                replace(
                    record,
                    warnings=tuple(dict.fromkeys((*record.warnings, *(item.code for item in assessment.warnings)))),
                    manual_review=True,
                    score_eligible=False,
                    confidence="partial",
                )
            )
        else:
            updated_records.append(record)
    warnings = tuple((*result.warnings, *extra_warnings))
    return ParseResult(tuple(updated_records), warnings, result.parser_name, result.parser_version, result.source_sha256, result.success and not extra_warnings)


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


__all__ = [
    "PARSER_VERSION",
    "IndexMethodologyRecord",
    "MethodologyHoldingsAssessment",
    "apply_methodology_holdings_assessment",
    "assess_methodology_holdings",
    "parse_index_methodology",
]
