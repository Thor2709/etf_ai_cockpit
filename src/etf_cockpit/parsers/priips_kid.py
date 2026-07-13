"""Deterministic PRIIPs KID extraction.

The parser deliberately treats a KID as issuer disclosure evidence only.  It
does not manufacture holdings/prospectus fields and keeps partial extraction
rows visible for manual review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


PARSER_VERSION = "2.0"


@dataclass(frozen=True)
class PriipsKidRecord:
    product: str
    isin: str
    manufacturer: str
    sri: int | None
    cost_fields: dict[str, str]
    holding_period_years: int | None
    scenarios: tuple[str, ...]
    document_date: str | None
    extraction_confidence: str
    warnings: tuple[str, ...]
    source_sha256: str
    source_pages: tuple[int, ...] = ()
    document_version: str | None = None
    schema_version: int = 2
    manual_review: bool = False
    score_eligible: bool = False


_CRITICAL_WARNINGS = {
    "sri_missing",
    "holding_period_missing",
    "cost_table_malformed",
    "document_date_missing",
    "unsupported_language",
}


def parse_priips_kid(path: Path, expected_isin: str | None = None) -> ParseResult[PriipsKidRecord]:
    """Parse a local text-bearing PDF using pdfplumber page extraction.

    Missing optional parser dependencies and image-only documents return an
    explicit unavailable result.  A partially extracted record is retained,
    but ``success`` is false when critical fields require manual review.
    """

    candidate = Path(path)
    source_sha = _sha256_file(candidate) if candidate.exists() and candidate.is_file() else ""
    pages, read_warning = _read_pages(candidate)
    if read_warning is not None:
        return ParseResult((), (read_warning,), "priips_kid", PARSER_VERSION, source_sha, False)
    source_pages = tuple(index for index, text in enumerate(pages, start=1) if text.strip())
    if not source_pages:
        return ParseResult(
            (),
            (ParseWarning("image_only_document", "KID contains no extractable text; manual review is required", "error", "document"),),
            "priips_kid",
            PARSER_VERSION,
            source_sha,
            False,
        )

    text = "\n".join(pages)
    isin_match = re.search(r"(?<![A-Z0-9])([A-Z]{2}[A-Z0-9]{10})(?![A-Z0-9])", text)
    isin = isin_match.group(1).upper() if isin_match else ""
    if expected_isin and isin != str(expected_isin).strip().upper():
        location = _location_for(text, pages, expected_isin)
        return ParseResult(
            (),
            (ParseWarning("identity_mismatch", f"KID ISIN {isin or 'missing'} does not match expected identity", "error", location),),
            "priips_kid",
            PARSER_VERSION,
            source_sha,
            False,
        )

    warnings: list[ParseWarning] = []
    product = _first_line_after(text, "Product:") or ""
    manufacturer = _manufacturer(text)
    sri_match = re.search(r"(?:classified[^\n]*?as\s+)?([1-7])\s+out\s+of\s+7", text, flags=re.IGNORECASE)
    holding_match = re.search(r"(?:recommended holding period|keep the Fund for|keep you invested for)\s*:?\s*(\d+)\s*years?", text, flags=re.IGNORECASE)
    date_match = re.search(
        r"(?:dated|date(?:d)?|document date)\s*:?\s*(\d{1,2})[\s/.-](\d{1,2})[\s/.-](\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if date_match is None:
        # Some issuers use an ISO date in the header.
        date_match = re.search(r"(?:dated|document date)\s*:?\s*(\d{4})-(\d{2})-(\d{2})", text, flags=re.IGNORECASE)
        document_date = None if date_match is None else f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
    else:
        document_date = f"{date_match.group(3)}-{int(date_match.group(2)):02d}-{int(date_match.group(1)):02d}"
    if sri_match is None:
        warnings.append(_warning("sri_missing", "Summary risk indicator is unavailable", text, pages, "risk indicator"))
    if holding_match is None:
        warnings.append(_warning("holding_period_missing", "Recommended holding period is unavailable", text, pages, "holding period"))
    if date_match is None:
        warnings.append(_warning("document_date_missing", "KID document date is unavailable", text, pages, "document"))
    if not _looks_english(text):
        warnings.append(_warning("unsupported_language", "KID language is not supported for deterministic extraction", text, pages, None))

    costs, cost_warning = _extract_costs(text, pages)
    if cost_warning is not None:
        warnings.append(cost_warning)
    scenarios = tuple(
        label
        for label in ("stress", "unfavourable", "moderate", "favourable")
        if re.search(rf"\b{label}\b", text, flags=re.IGNORECASE)
    )
    record_warnings = tuple(item.code for item in warnings)
    manual_review = bool(warnings)
    complete = bool(isin and product and manufacturer and sri_match and holding_match and document_date and costs)
    record = PriipsKidRecord(
        product=product[:240],
        isin=isin,
        manufacturer=manufacturer[:120],
        sri=None if sri_match is None else int(sri_match.group(1)),
        cost_fields=costs,
        holding_period_years=None if holding_match is None else int(holding_match.group(1)),
        scenarios=scenarios,
        document_date=document_date,
        extraction_confidence="high" if complete else "partial",
        warnings=record_warnings,
        source_sha256=source_sha,
        source_pages=source_pages,
        manual_review=manual_review,
        score_eligible=complete and not warnings,
    )
    success = not any(item.code in _CRITICAL_WARNINGS for item in warnings)
    return ParseResult((record,), tuple(warnings), "priips_kid", PARSER_VERSION, source_sha, success)


def _read_pages(path: Path) -> tuple[list[str], ParseWarning | None]:
    if not path.exists() or not path.is_file():
        return [], ParseWarning("pdf_read_failed", "KID file is unavailable", "error", "document")
    try:
        import pdfplumber
    except Exception as exc:
        return [], ParseWarning(
            "pdf_read_failed",
            f"Could not read KID: optional pdfplumber dependency is unavailable ({type(exc).__name__})",
            "error",
            "document",
        )
    try:
        with pdfplumber.open(path) as pdf:
            return [_normalise_page(page.extract_text() or "") for page in pdf.pages], None
    except Exception as exc:
        return [], ParseWarning("pdf_read_failed", f"Could not read KID: {type(exc).__name__}", "error", "document")


def _normalise_page(value: str) -> str:
    # Keep line boundaries for field extraction while making wrapped PDF text
    # deterministic across pdfplumber versions.
    return "\n".join(" ".join(line.split()) for line in str(value).splitlines() if line.strip())


def _first_line_after(text: str, label: str) -> str | None:
    match = re.search(re.escape(label) + r"\s*([^\n]+)", text, flags=re.IGNORECASE)
    return None if match is None else match.group(1).strip()


def _manufacturer(text: str) -> str:
    match = re.search(r"(?:manufacturer|product manufacturer)\s*:?\s*([^\n]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\n(Vanguard Group \([^\n]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _extract_costs(text: str, pages: list[str]) -> tuple[dict[str, str], ParseWarning | None]:
    """Extract only bounded values from the issuer's cost-table rows.

    KID PDF tables are commonly emitted by ``pdfplumber`` in visual-column
    order rather than reading order.  Parsing one broad DOTALL expression can
    therefore capture the next question/header or transaction prose.  This
    routine anchors each row to its label, keeps the row within the cost
    section, and requires an explicit percentage/currency token before a value
    is accepted.
    """

    lines = text.splitlines()
    section_start = next((index for index, line in enumerate(lines) if re.search(r"Composition of Costs", line, re.IGNORECASE)), None)
    if section_start is None:
        return {}, _warning("cost_table_malformed", "KID cost table is unavailable or malformed", text, pages, "cost")
    section_end = next(
        (index for index in range(section_start + 1, len(lines)) if re.search(r"How long should I hold it", lines[index], re.IGNORECASE)),
        len(lines),
    )
    rows = [" ".join(line.split()).strip() for line in lines[section_start:section_end] if line.strip()]
    result: dict[str, str] = {}

    def clean(parts: list[str]) -> str | None:
        value = " ".join(" ".join(parts).split()).strip()
        value = re.sub(r"\bWhat are the costs\?\b", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\bIf you exit after \d+\b", "", value, flags=re.IGNORECASE)
        value = " ".join(value.split()).strip(" -:")
        if not value or "?" in value or re.search(r"What are the costs|Composition of Costs", value, re.IGNORECASE):
            return None
        if not re.search(r"(?:\b(?:EUR|GBP|USD)\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*%)", value, re.IGNORECASE):
            return None
        return value[:500]

    def after(prefix: str, index: int) -> str:
        return rows[index][len(prefix):].strip(" :")

    entry_index = next((index for index, row in enumerate(rows) if re.match(r"^Entry costs\b", row, re.IGNORECASE)), None)
    if entry_index is not None:
        value = clean([after("Entry costs", entry_index)])
        if value:
            result["entry_costs"] = value

    exit_index = next((index for index, row in enumerate(rows) if re.match(r"^Exit costs\b", row, re.IGNORECASE)), None)
    if exit_index is not None:
        parts: list[str] = []
        if exit_index and rows[exit_index - 1].casefold().startswith("the fund does not charge an exit fee"):
            parts.append(rows[exit_index - 1])
        parts.append(after("Exit costs", exit_index))
        if exit_index + 1 < len(rows) and rows[exit_index + 1].casefold() == "so.":
            parts.insert(1, rows[exit_index + 1])
        value = clean(parts)
        if value:
            result["exit_costs"] = value

    management_index = next((index for index, row in enumerate(rows) if row.casefold().startswith("management fees and other")), None)
    transaction_index = next((index for index, row in enumerate(rows) if re.match(r"^Transaction costs\b", row, re.IGNORECASE)), None)
    if management_index is not None:
        parts = [after("Management fees and other", management_index)]
        index = management_index + 1
        while index < len(rows):
            row = rows[index]
            if re.match(r"^(?:Incidental costs|Performance fees)\b", row, re.IGNORECASE):
                break
            if transaction_index is not None and index >= transaction_index:
                break
            if re.match(r"^\d+(?:[.,]\d+)?\s*%", row) and any("%" in item for item in parts):
                break
            parts.append(row)
            index += 1
        # Amounts are often emitted between a wrapped label and its final
        # continuation.  Move a standalone currency amount to the end.
        amounts: list[str] = []
        text_parts: list[str] = []
        for part in parts:
            matches = re.findall(r"(?:EUR|GBP|USD)\s*\d+(?:[.,]\d+)?", part, re.IGNORECASE)
            amounts.extend(matches)
            text_parts.append(re.sub(r"(?:EUR|GBP|USD)\s*\d+(?:[.,]\d+)?", "", part, flags=re.IGNORECASE).strip())
        parts = [part for part in text_parts if part] + amounts
        value = clean(parts)
        if value:
            result["ongoing_costs"] = value

    transaction_start = None
    if transaction_index is not None:
        transaction_start = transaction_index
        if transaction_index and re.match(r"^\d+(?:[.,]\d+)?\s*%", rows[transaction_index - 1]):
            transaction_start = transaction_index - 1
    else:
        transaction_start = next(
            (index for index, row in enumerate(rows) if re.match(r"^\d+(?:[.,]\d+)?\s*%", row)),
            None,
        )
    if transaction_start is not None:
        parts = []
        for index in range(transaction_start, len(rows)):
            row = rows[index]
            if re.match(r"^Incidental costs\b|^Performance fees\b", row, re.IGNORECASE):
                break
            if re.match(r"^Transaction costs\b", row, re.IGNORECASE):
                row = after("Transaction costs", index)
            parts.append(row)
        amounts = []
        text_parts = []
        for part in parts:
            matches = re.findall(r"(?:EUR|GBP|USD)\s*\d+(?:[.,]\d+)?", part, re.IGNORECASE)
            amounts.extend(matches)
            text_parts.append(re.sub(r"(?:EUR|GBP|USD)\s*\d+(?:[.,]\d+)?", "", part, flags=re.IGNORECASE).strip())
        parts = [part for part in text_parts if part] + amounts
        value = clean(parts)
        if value:
            result["transaction_costs"] = value

    performance_index = next((index for index, row in enumerate(rows) if re.match(r"^Performance fees\b", row, re.IGNORECASE)), None)
    if performance_index is not None:
        value = clean([after("Performance fees", performance_index)])
        if value:
            result["performance_fees"] = value

    has_cost_section = bool(re.search(r"(?:What are the costs|Composition of Costs|Costs over Time)", text, flags=re.IGNORECASE))
    malformed = has_cost_section and set(result) != {"entry_costs", "exit_costs", "ongoing_costs", "transaction_costs", "performance_fees"}
    warning = None
    if malformed:
        warning = _warning("cost_table_malformed", "KID cost table is incomplete or malformed", text, pages, "Composition of Costs")
    return result, warning


def _looks_english(text: str) -> bool:
    if re.search(r"\b(Key Information Document|What is this product|Risk Indicator)\b", text, flags=re.IGNORECASE):
        return True
    return not bool(
        re.search(
            r"(?:Document d['’]informations|Dokument mit wesentlichen|Basisinformationsblatt|Documento de datos fundamentales|Documento contenente le informazioni chiave|Essentiële-informatiedocument)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _location_for(text: str, pages: list[str], term: object) -> str:
    needle = str(term or "").casefold()
    for index, page in enumerate(pages, start=1):
        if needle and needle.casefold() in page.casefold():
            return f"page {index}"
    if pages:
        for index, page in enumerate(pages, start=1):
            if page.strip():
                return f"page {index}"
    return "document"


def _warning(code: str, message: str, text: str, pages: list[str], term: str | None) -> ParseWarning:
    return ParseWarning(code, message, "warning", _location_for(text, pages, term) if term else "document")


__all__ = ["PARSER_VERSION", "PriipsKidRecord", "parse_priips_kid"]
