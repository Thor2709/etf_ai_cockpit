"""Candidate figures from a Pillar 3 / annual-report PDF (SB2, semi-automatic).

This module only *proposes*: every figure carries its page, the printed line and the flags that make it
uncertain, and lands in the owner's confirm queue (``pillar3_queue``) as ``pending``. Nothing here is evidence.
The PDF is untrusted input: it is parsed for text only (``pypdf``), never executed or rendered.

A figure is proposed only when its label, its percent sign and its reporting period can all be read from the
page. Column order is read from the nearest year header above the line; when no header is found the first
column is proposed and flagged ``header_not_found``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
import re

_PCT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s?%")
_YEAR = re.compile(r"(?<!\d)(20[12]\d)(?!\d)")
_DATE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](20[12]\d|[12]\d)(?!\d)")
_EXCLUDE_BASE = re.compile(r"\b(?:krav|requirement|target|mål|buffer|minimum|minstekrav|legal|regulatory|management)\b", re.I)

# metric -> (label regex that must match near the start of the line, unit, lines that must NOT match, extra context)
_SPECS: dict[str, dict[str, object]] = {
    "cet1_ratio_pct": {
        "label": re.compile(r"(?:ren kjernekapitaldekning|cet\s?1[- ]?(?:capital )?(?:ratio|dekning)|common equity tier 1 (?:capital )?ratio)", re.I),
        "exclude": _EXCLUDE_BASE,
    },
    "cet1_requirement_pct": {
        "label": re.compile(r"(?:(?:samlet |totalt |minimums)?krav (?:til|på) ren kjernekapital|cet\s?1(?: capital)? requirement|total cet\s?1 requirement|minimum requirement on cet\s?1)", re.I),
        "exclude": re.compile(r"\b(?:target|mål|uvektet|leverage)\b", re.I),
    },
    "leverage_ratio_pct": {
        "label": re.compile(r"(?:uvektet kjernekapitalandel|leverage ratio)", re.I),
        "exclude": _EXCLUDE_BASE,
    },
    "lcr_pct": {
        "label": re.compile(r"\blcr\b", re.I),
        "exclude": re.compile(r"\b(?:krav|requirement|minimum|minstekrav|mål|target|buffer)\b", re.I),
    },
    "nsfr_pct": {
        "label": re.compile(r"\bnsfr\b", re.I),
        "exclude": re.compile(r"\b(?:krav|requirement|minimum|minstekrav|mål|target|buffer)\b", re.I),
    },
    "deposit_to_loan_ratio_pct": {
        "label": re.compile(r"(?:innskuddsdekning|innskudd i prosent av (?:brutto )?utlån|deposit(?:s)?(?:[- ]to[- ]loan| coverage| to (?:net )?loans)|deposit-to-loan)", re.I),
        "exclude": re.compile(r"\b(?:krav|requirement|target|mål)\b", re.I),
    },
    "stage2_pct_gross_loans": {
        "label": re.compile(r"(?:(?:trinn|steg|stage)\s?2\b)", re.I),
        "exclude": re.compile(r"\b(?:krav|requirement|target|mål)\b", re.I),
        "context": re.compile(r"(?:brutto|gross|utlån|loans|andel|share|ratio|prosent)", re.I),
    },
    "stage3_pct_gross_loans": {
        "label": re.compile(r"(?:(?:trinn|steg|stage)\s?3\b)", re.I),
        "exclude": re.compile(r"\b(?:krav|requirement|target|mål)\b", re.I),
        "context": re.compile(r"(?:brutto|gross|utlån|loans|andel|share|ratio|prosent)", re.I),
    },
}
_MAX_PER_METRIC = 4


def _to_float(token: str) -> float:
    return float(token.replace(",", "."))


def _years(line: str) -> list[int]:
    return [int(item) for item in _YEAR.findall(line)]


def _header_years(lines: Sequence[str], index: int, window: int = 18) -> list[int]:
    for back in range(index - 1, max(0, index - window) - 1, -1):
        found = _years(lines[back])
        if len(found) >= 2:
            return found
    return []


def detect_period(pages: Sequence[str]) -> str | None:
    """The reporting date of the whole document: the latest ``dd.mm.yyyy`` that appears at least three times."""

    counts: Counter[str] = Counter()
    for text in pages[:12]:
        for day, month, year in _DATE.findall(text):
            year_value = int(year) if len(year) == 4 else 2000 + int(year)
            day_value, month_value = int(day), int(month)
            if 1 <= day_value <= 31 and 1 <= month_value <= 12:
                counts[f"{year_value:04d}-{month_value:02d}-{day_value:02d}"] += 1
    frequent = sorted(date for date, number in counts.items() if number >= 3)
    return frequent[-1] if frequent else None


_THRESHOLD = re.compile(r"\(?\s*[<>≥≤]=?\s?\d{1,3}(?:[.,]\d{1,2})?\s?%\s*\)?")


def _line_figures(line: str) -> list[float]:
    """Percent values on the line, ignoring thresholds such as ``(>100 %)``."""

    return [_to_float(token) for token in _PCT.findall(_THRESHOLD.sub(" ", line))]


def _line_period(line: str) -> tuple[str | None, bool]:
    """The single reporting date or year named in a prose line, else ``(None, ambiguous)``."""

    dates = {f"{(int(y) if len(y) == 4 else 2000 + int(y)):04d}-{int(m):02d}-{int(d):02d}" for d, m, y in _DATE.findall(line) if 1 <= int(d) <= 31 and 1 <= int(m) <= 12}
    if len(dates) == 1:
        return next(iter(dates)), False
    years = set(_years(line))
    if len(dates) > 1 or len(years) > 1:
        return None, True
    if len(years) == 1:
        return f"{next(iter(years))}-12-31", False
    return None, False


def extract_figures(pages: Sequence[str], *, document_period: str | None = None) -> list[dict[str, object]]:
    """Propose candidate figures; each has page, printed line and uncertainty flags."""

    document_period = document_period or detect_period(pages)
    candidates: dict[str, list[tuple[tuple[int, int, int], dict[str, object]]]] = {}
    for page_number, text in enumerate(pages, start=1):
        lines = [line.strip() for line in text.splitlines()]
        for index, line in enumerate(lines):
            if len(line) < 6 or len(line) > 220:
                continue
            for metric, spec in _SPECS.items():
                label = spec["label"].search(line)  # type: ignore[union-attr]
                if label is None or label.start() > 70:
                    continue
                if spec["exclude"].search(line):  # type: ignore[union-attr]
                    continue
                context = spec.get("context")
                if context is not None and not context.search(line):  # type: ignore[union-attr]
                    continue
                values = _line_figures(line[label.start():])
                if not values:
                    continue
                years = _header_years(lines, index)
                flags: list[str] = []
                position = 0
                if years:
                    descending = years[0] >= years[-1]
                    position = 0 if descending else len(years) - 1
                    if len(values) != len(years):
                        flags.append("header_columns_differ_from_values")
                        position = 0 if descending else len(values) - 1
                    period = f"{max(years)}-12-31"
                else:
                    flags.append("header_not_found")
                    period, ambiguous = _line_period(line)
                    if period is not None:
                        flags.append("period_from_line")
                    else:
                        period = document_period
                        if ambiguous:
                            flags.append("several_years_in_line")
                    if len(values) > 2:
                        flags.append("several_columns")
                if period is None:
                    continue  # no reporting period: cannot be proposed
                if position >= len(values):
                    position = 0
                if not label.start() <= 3:
                    flags.append("label_not_at_line_start")
                rank = (len(flags), page_number, index)
                candidates.setdefault(metric, []).append(
                    (
                        rank,
                        {
                            "metric": metric,
                            "label": line[: label.end()].strip(),
                            "value": values[position],
                            "unit": "percent",
                            "period": period,
                            "page": page_number,
                            "printed_text": line,
                            "flags": flags,
                            "header_years": years,
                            "columns_found": len(values),
                        },
                    )
                )
    figures: list[dict[str, object]] = []
    for metric in _SPECS:
        seen: set[tuple[float, object]] = set()
        for _, figure in sorted(candidates.get(metric, ()), key=lambda item: item[0]):
            key = (figure["value"], figure["period"])  # type: ignore[assignment]
            if key in seen:
                continue
            seen.add(key)
            figures.append(figure)
            if sum(1 for item in figures if item["metric"] == metric) >= _MAX_PER_METRIC:
                break
    return figures


def read_pdf_pages(path: str) -> list[str]:
    """Text of every page; the file is parsed, never executed."""

    from pypdf import PdfReader

    reader = PdfReader(path)
    return [(page.extract_text() or "") for page in reader.pages]


def document_summary(pages: Iterable[str]) -> str:
    for page in pages:
        for line in page.splitlines():
            if line.strip():
                return line.strip()[:120]
    return ""


EXTRACTOR_VERSION = "pillar3_extract.v1"


def ingest_pdf(root: object, instrument_id: str, path: str, *, source_url: str, title: str | None = None) -> dict[str, object]:
    """Extract candidates from one PDF and add them to the owner's confirm queue as ``pending``.

    The source URL must be https; the file is hashed so every later confirmation can be traced to the exact bytes.
    """

    import hashlib
    from datetime import datetime, timezone
    from pathlib import Path

    from etf_cockpit.data.pillar3_queue import merge_extraction

    if not str(source_url).startswith("https://"):
        raise ValueError("source_url must be an https URL of the issuer or regulator document")
    data = Path(path).read_bytes()
    if not data.startswith(b"%PDF"):
        raise ValueError("file is not a PDF")
    pages = read_pdf_pages(str(path))
    period = detect_period(pages)
    figures = extract_figures(pages, document_period=period)
    digest = hashlib.sha256(data).hexdigest()
    document = {
        "document_id": digest[:16],
        "source_url": source_url,
        "title": title or document_summary(pages),
        "sha256": digest,
        "pages": len(pages),
        "document_period": period,
        "extractor": EXTRACTOR_VERSION,
        "extracted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    queue = merge_extraction(Path(str(root)), instrument_id, document, figures)  # type: ignore[arg-type]
    return {"document": document, "proposed": len(figures), "queue_figures": len(queue["figures"]), "metrics": sorted({str(item["metric"]) for item in figures})}
