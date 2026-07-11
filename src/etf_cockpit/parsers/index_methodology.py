from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, _sha256_file


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


def parse_index_methodology(path: Path, provider: str) -> ParseResult[IndexMethodologyRecord]:
    source_sha = _sha256_file(path) if path.exists() else ""
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            pages = [(page.extract_text() or "") for page in pdf.pages]
    except Exception as exc:
        code = "empty_document" if path.exists() and path.read_bytes().startswith(b"%PDF") else "pdf_read_failed"
        message = "Methodology contains no extractable text" if code == "empty_document" else f"Could not read methodology: {type(exc).__name__}"
        return ParseResult((), (ParseWarning(code, message, "error"),), "index_methodology", "1.0", source_sha, False)
    text = "\n".join(pages)
    if not text.strip():
        return ParseResult((), (ParseWarning("empty_document", "Methodology contains no extractable text", "error"),), "index_methodology", "1.0", source_sha, False)
    version_match = re.search(r"\bv(\d+(?:\.\d+)*)\b", text, flags=re.IGNORECASE)
    date_match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", text, flags=re.IGNORECASE)
    series_match = re.search(r"(FTSE Global Equity Index Series)", text, flags=re.IGNORECASE)
    review_terms = tuple(sorted(set(line.strip() for line in text.splitlines() if "review" in line.lower() or "rebalance" in line.lower())))[:12]
    eligibility = tuple(sorted(set(line.strip() for line in text.splitlines() if "inclusion criteria" in line.lower() or "eligible" in line.lower())))[:12]
    weighting = tuple(sorted(set(line.strip() for line in text.splitlines() if "weight" in line.lower())))[:12]
    caps = tuple(sorted(set(line.strip() for line in text.splitlines() if "cap" in line.lower())))[:12]
    record = IndexMethodologyRecord(
        provider=provider,
        index_series=series_match.group(1) if series_match else "Unknown index series",
        version=None if version_match is None else version_match.group(1),
        document_date=None if date_match is None else f"{date_match.group(1)} {date_match.group(2)}",
        eligibility_rules=eligibility,
        weighting_rules=weighting,
        review_frequency=review_terms[0] if review_terms else None,
        caps=caps,
        source_pages=tuple(index + 1 for index, page in enumerate(pages) if page.strip())[:20],
        confidence="high" if version_match and series_match else "partial",
        warnings=(),
        source_sha256=source_sha,
    )
    return ParseResult((record,), (), "index_methodology", "1.0", source_sha, True)
