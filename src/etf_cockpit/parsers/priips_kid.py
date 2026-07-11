from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


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


def parse_priips_kid(path: Path, expected_isin: str | None = None) -> ParseResult[PriipsKidRecord]:
    source_sha = _sha256_file(path) if path.exists() else ""
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        return ParseResult((), (ParseWarning("pdf_read_failed", f"Could not read KID: {type(exc).__name__}", "error"),), "priips_kid", "1.0", source_sha, False)
    if not text.strip():
        return ParseResult((), (ParseWarning("empty_document", "KID contains no extractable text", "error"),), "priips_kid", "1.0", source_sha, False)
    isin_match = re.search(r"\b[A-Z]{2}[A-Z0-9]{10}\b", text)
    isin = isin_match.group(0) if isin_match else ""
    if expected_isin and isin != expected_isin:
        return ParseResult((), (ParseWarning("identity_mismatch", f"KID ISIN {isin or 'missing'} does not match expected identity", "error"),), "priips_kid", "1.0", source_sha, False)
    product = _first_line_after(text, "Product:") or "Unknown product"
    manufacturer = "Vanguard" if "Vanguard" in text else (_first_line_after(text, "Manufacturer:") or "Unknown manufacturer")
    sri_match = re.search(r"(\d)\s+out of\s+7", text, flags=re.IGNORECASE)
    holding_match = re.search(r"keep you invested for\s+(\d+)\s+years|keep the Fund for\s+(\d+)", text, flags=re.IGNORECASE)
    date_match = re.search(r"dated\s+(\d{2})/(\d{2})/(\d{4})", text, flags=re.IGNORECASE)
    warnings: list[str] = []
    if sri_match is None:
        warnings.append("sri_missing")
    if holding_match is None:
        warnings.append("holding_period_missing")
    document_date = None if date_match is None else f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
    record = PriipsKidRecord(
        product=product[:240],
        isin=isin,
        manufacturer=manufacturer[:120],
        sri=None if sri_match is None else int(sri_match.group(1)),
        cost_fields=_extract_costs(text),
        holding_period_years=None if holding_match is None else int(next(group for group in holding_match.groups() if group)),
        scenarios=tuple(sorted(set(re.findall(r"Scenario[^\n:]*", text, flags=re.IGNORECASE))))[:12],
        document_date=document_date,
        extraction_confidence="high" if isin and sri_match and holding_match else "partial",
        warnings=tuple(warnings),
        source_sha256=source_sha,
    )
    return ParseResult((record,), tuple(ParseWarning(code, code.replace("_", " "), "warning") for code in warnings), "priips_kid", "1.0", source_sha, True)


def _first_line_after(text: str, label: str) -> str | None:
    match = re.search(re.escape(label) + r"\s*(.+)", text)
    return None if match is None else match.group(1).strip()


def _extract_costs(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for label in ("Entry costs", "Exit costs", "Ongoing costs", "Transaction costs"):
        match = re.search(re.escape(label) + r"[^\n]*", text, flags=re.IGNORECASE)
        if match:
            result[label.lower().replace(" ", "_")] = match.group(0).strip()[:240]
    return result
