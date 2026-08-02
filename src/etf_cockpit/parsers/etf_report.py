"""Bounded, deterministic English ETF report extraction.

This module deliberately exposes three explicit report kinds and three small
English template plug-ins.  It never falls back to a generic document parser,
and a bounded read is never reported as a complete extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import multiprocessing as mp
import os
from pathlib import Path
import re
from typing import Any

from etf_cockpit.parsers.contracts import ParseResult, ParseWarning


PARSER_VERSION = "2.0"
REPORT_KINDS = ("prospectus", "annual_report", "half_year_report")
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PAGES = 250
DEFAULT_MAX_PAGE_CHARS = 200_000
DEFAULT_MAX_TOTAL_CHARS = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
MAX_EXCERPT_CHARS = 500
MAX_FIELD_VALUE_CHARS = 2_000

_KIND_ALIASES = {
    "prospectus": "prospectus",
    "annual_report": "annual_report",
    "annual-report": "annual_report",
    "annual": "annual_report",
    "half_year_report": "half_year_report",
    "half-year-report": "half_year_report",
    "half-year_report": "half_year_report",
    "half_year": "half_year_report",
    "semi_annual_report": "half_year_report",
    "semi-annual-report": "half_year_report",
}

REPORT_FIELDS = (
    "fund_name",
    "isin",
    "document_date",
    "reporting_period_end",
    "legal_structure",
    "securities_lending",
    "collateral_policy",
    "ongoing_costs",
    "holdings_count",
    "operational_risks",
)
REQUIRED_FIELDS = {
    "fund_name",
    "isin",
    "document_date",
    "legal_structure",
}


@dataclass(frozen=True)
class EtfReportFieldEvidence:
    """One bounded field value and all pages which support its candidates."""

    field_name: str
    value: str | None
    source_page: int | None
    confidence: str
    status: str
    candidates: tuple[str, ...]
    matched_label: str | None
    candidate_pages: tuple[int, ...] = ()
    source_excerpt: str = ""

    @property
    def pages(self) -> tuple[int, ...]:
        return self.candidate_pages

    @property
    def label(self) -> str | None:
        return self.matched_label

    @property
    def bounded_excerpt(self) -> str:
        return self.source_excerpt


@dataclass(frozen=True)
class EtfReportRecord:
    document_kind: str
    language: str
    language_plugin: str
    template_plugin: str
    document_date: str | None
    structured_fields: dict[str, str | None]
    field_evidence: tuple[EtfReportFieldEvidence, ...]
    source_pages: tuple[int, ...]
    extraction_confidence: str
    warnings: tuple[str, ...]
    source_sha256: str
    schema_version: int = 2
    verification_status: str = "pending"
    manual_review: bool = True
    evidence_eligible: bool = False
    score_eligible: bool = False
    execution_allowed: bool = False

    @property
    def reporting_period_end(self) -> str | None:
        return self.structured_fields.get("reporting_period_end")


@dataclass(frozen=True)
class _FieldPattern:
    field_name: str
    label: str
    expression: str


@dataclass(frozen=True)
class ReportTemplatePlugin:
    plugin_id: str
    version: str
    language: str
    document_kind: str
    title_patterns: tuple[str, ...]
    fields: tuple[_FieldPattern, ...]


_EN_FIELDS = (
    _FieldPattern("fund_name", "Fund name", r"(?:fund|sub[- ]fund)\s+name\s*:\s*(?P<value>[^\n]{1,240})"),
    _FieldPattern("isin", "ISIN", r"\bISIN\s*:\s*(?P<value>[A-Z]{2}[A-Z0-9]{10})\b"),
    _FieldPattern("document_date", "Document date", r"(?:document\s+date|dated)\s*:\s*(?P<value>[^\n]{1,80})"),
    _FieldPattern("reporting_period_end", "Reporting period ended", r"(?:reporting\s+period\s+ended|period\s+ended|for\s+the\s+(?:year|half[- ]year)\s+ended)\s*:\s*(?P<value>[^\n]{1,80})"),
    _FieldPattern("legal_structure", "Legal structure", r"(?:legal\s+structure|legal\s+form|fund\s+structure)\s*:\s*(?P<value>[^\n]{1,300})"),
    _FieldPattern("securities_lending", "Securities lending", r"(?:securities\s+lending|stock\s+lending)\s*:\s*(?P<value>[^\n]{1,500})"),
    _FieldPattern("collateral_policy", "Collateral policy", r"(?:collateral\s+policy|collateral)\s*:\s*(?P<value>[^\n]{1,500})"),
    _FieldPattern("ongoing_costs", "Ongoing charges", r"(?:ongoing\s+(?:charges|costs)|total\s+expense\s+ratio|management\s+fee)\s*:\s*(?P<value>[^\n]{1,80})"),
    _FieldPattern("holdings_count", "Number of holdings", r"(?:number\s+of\s+holdings|total\s+holdings)\s*:\s*(?P<value>[^\n]{1,80})"),
    _FieldPattern("operational_risks", "Operational risks", r"(?:operational\s+risks?|operational\s+risk\s+factors?)\s*:\s*(?P<value>[^\n]{1,500})"),
)

_PLUGINS = tuple(
    ReportTemplatePlugin(
        plugin_id=f"template.{kind.replace('_', '-')}.english.v1",
        version="1",
        language="en",
        document_kind=kind,
        title_patterns=titles,
        fields=_EN_FIELDS,
    )
    for kind, titles in (
        ("prospectus", (r"\bprospectus\b",)),
        ("annual_report", (r"\bannual\s+report\b", r"\breport\s+and\s+accounts\b")),
        ("half_year_report", (r"\bhalf[- ]year(?:ly)?\s+report\b", r"\bsemi[- ]annual\s+report\b")),
    )
)


def canonical_report_kind(document_kind: str) -> str:
    value = str(document_kind or "").strip().lower().replace(" ", "_")
    try:
        return _KIND_ALIASES[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported document_kind: {document_kind}") from exc


def available_report_plugins() -> tuple[ReportTemplatePlugin, ...]:
    return _PLUGINS


def configure_memory_limit(limit_bytes: int) -> str:
    """Apply the hard child-process memory cap using only the standard library."""

    limit = int(limit_bytes)
    if limit <= 0:
        raise ValueError("memory_limit_bytes must be positive")
    backend = memory_limit_backend()
    if backend == "posix_rlimit_as":
        import resource  # type: ignore[import-not-found]
        resource_module: Any = resource

        current = resource_module.getrlimit(resource_module.RLIMIT_AS)
        hard = current[1]
        target_hard = limit if hard == resource_module.RLIM_INFINITY else min(hard, limit)
        resource_module.setrlimit(resource_module.RLIMIT_AS, (target_hard, target_hard))
        return "posix_rlimit_as"
    if backend == "windows_job_object":
        _configure_windows_job_memory(limit)
        return "windows_job_object"
    raise RuntimeError(f"unsupported platform for hard memory cap: {os.name}")


def memory_limit_backend(platform_name: str | None = None) -> str:
    platform = platform_name or os.name
    if platform == "posix":
        return "posix_rlimit_as"
    if platform == "nt":
        return "windows_job_object"
    raise RuntimeError(f"unsupported platform for hard memory cap: {platform}")


_WINDOWS_JOB_HANDLE: Any = None


def _configure_windows_job_memory(limit_bytes: int) -> None:
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = limit_bytes
    if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    global _WINDOWS_JOB_HANDLE
    _WINDOWS_JOB_HANDLE = handle


def _sha256_bounded_file(path: Path, max_file_bytes: int) -> tuple[str, bytes, bool]:
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    with Path(path).open("rb") as handle:
        while total <= max_file_bytes:
            chunk = handle.read(min(1024 * 1024, max_file_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            digest.update(chunk)
            total += len(chunk)
            if total > max_file_bytes:
                break
    return digest.hexdigest(), b"".join(chunks), total > max_file_bytes


def parse_etf_report(
    path: Path,
    document_kind: str,
    *,
    expected_isin: str | None = None,
    expected_document_date: str | date | datetime | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_page_chars: int = DEFAULT_MAX_PAGE_CHARS,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
) -> ParseResult[EtfReportRecord]:
    """Parse a local snapshot with strict page/text/output bounds.

    The v2 import path calls this function only from a spawned child.  Keeping
    the deterministic core callable directly also makes parser fixtures and
    bound tests independent of the optional PDF library.
    """

    kind = canonical_report_kind(document_kind)
    if min(max_file_bytes, max_pages, max_page_chars, max_total_chars) <= 0:
        raise ValueError("parser bounds must be positive")
    candidate = Path(path)
    if not candidate.is_file():
        return _failure("pdf_read_failed", "ETF report file is unavailable", "")
    source_sha, _payload, oversized = _sha256_bounded_file(candidate, max_file_bytes)
    if oversized:
        return _failure("document_too_large", "ETF report exceeds the bounded file limit", source_sha)
    pages, read_warnings = _read_pages(candidate, max_pages=max_pages, max_page_chars=max_page_chars, max_total_chars=max_total_chars)
    if not pages or not any(page.strip() for page in pages):
        warning = read_warnings or (ParseWarning("image_only_document", "ETF report contains no extractable text", "error", "document"),)
        return ParseResult((), warning, "etf_report", PARSER_VERSION, source_sha, False)
    text = "\n".join(pages)
    if not _looks_english(text):
        return _failure("unsupported_language", "ETF report language is not supported by the English plug-in", source_sha)
    plugin = next(item for item in _PLUGINS if item.document_kind == kind)
    warnings = list(read_warnings)
    if not any(re.search(pattern, text, re.IGNORECASE) for pattern in plugin.title_patterns):
        warnings.append(ParseWarning("template_mismatch", f"Document does not match the selected {kind} template", "error", "document"))
    evidence = [_extract_field(pattern, pages) for pattern in plugin.fields]
    fields = {item.field_name: item.value for item in evidence}
    evidence, fields = _normalise_dates(evidence, fields)
    required = set(REQUIRED_FIELDS)
    if kind in {"annual_report", "half_year_report"}:
        required.add("reporting_period_end")
    for item in evidence:
        if item.status in {"malformed", "future", "conflict", "truncated"}:
            severity = "error" if item.field_name in required or item.field_name == "document_date" else "warning"
            code = {
                "malformed": f"{item.field_name}_malformed",
                "future": f"future_{item.field_name}",
                "conflict": "field_conflict",
                "truncated": "field_output_truncated",
            }[item.status]
            warnings.append(ParseWarning(code, f"Bounded report field is {item.status}: {item.field_name}", severity, _pages_location(item)))
        elif item.status == "unknown" and item.field_name in required:
            warnings.append(ParseWarning("required_field_missing", f"Required report field is unavailable: {item.field_name}", "error", "document"))
    expected = str(expected_isin or "").strip().upper()
    actual = str(fields.get("isin") or "").strip().upper()
    if expected and actual != expected:
        isin = next(item for item in evidence if item.field_name == "isin")
        warnings.append(ParseWarning("identity_mismatch", "ETF report ISIN does not match expected identity", "error", _pages_location(isin)))
    expected_date = _normalise_date(expected_document_date)
    if expected_date and fields.get("document_date") != expected_date:
        document_date = next(item for item in evidence if item.field_name == "document_date")
        warnings.append(ParseWarning("document_date_mismatch", "ETF report document date does not match expected identity", "error", _pages_location(document_date)))
    warning_codes = tuple(dict.fromkeys(item.code for item in warnings))
    blocking = {"error"}
    complete = not any(item.severity in blocking for item in warnings) and not any(item.code == "field_conflict" for item in warnings)
    record = EtfReportRecord(
        document_kind=kind,
        language="en",
        language_plugin="language.en.v1",
        template_plugin=plugin.plugin_id,
        document_date=fields.get("document_date"),
        structured_fields={field: fields.get(field) for field in REPORT_FIELDS},
        field_evidence=tuple(evidence),
        source_pages=tuple(index for index, page in enumerate(pages, start=1) if page.strip()),
        extraction_confidence="high" if complete else "partial",
        warnings=warning_codes,
        source_sha256=source_sha,
    )
    return ParseResult((record,), tuple(warnings), "etf_report", PARSER_VERSION, source_sha, complete)


def parse_etf_report_in_child(
    path: Path,
    document_kind: str,
    *,
    expected_isin: str | None = None,
    expected_document_date: str | date | datetime | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_page_chars: int = DEFAULT_MAX_PAGE_CHARS,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
) -> ParseResult[EtfReportRecord]:
    """Decode a retained snapshot once in a spawned, hard-bounded child."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_child_parse_entry, args=(child, Path(path), document_kind, expected_isin, expected_document_date, max_file_bytes, max_pages, max_page_chars, max_total_chars, memory_limit_bytes))
    process.start()
    child.close()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2.0)
        if process.is_alive():
            process.kill()
            process.join(2.0)
        return _failure("resource_blocked", "ETF report parser child exceeded its hard timeout", _sha256_if_present(Path(path)))
    if process.exitcode != 0 or not parent.poll():
        return _failure("resource_blocked", "ETF report parser child crashed or returned no result", _sha256_if_present(Path(path)))
    try:
        result = parent.recv()
    except (EOFError, OSError):
        return _failure("resource_blocked", "ETF report parser child result was malformed", _sha256_if_present(Path(path)))
    if not isinstance(result, ParseResult):
        return _failure("resource_blocked", "ETF report parser child result was malformed", _sha256_if_present(Path(path)))
    return result


def _child_parse_entry(connection: Any, path: Path, kind: str, expected_isin: str | None, expected_date: Any, max_file_bytes: int, max_pages: int, max_page_chars: int, max_total_chars: int, memory_limit_bytes: int) -> None:
    try:
        configure_memory_limit(memory_limit_bytes)
        connection.send(parse_etf_report(path, kind, expected_isin=expected_isin, expected_document_date=expected_date, max_file_bytes=max_file_bytes, max_pages=max_pages, max_page_chars=max_page_chars, max_total_chars=max_total_chars))
    except BaseException:
        os._exit(70)
    finally:
        try:
            connection.close()
        except Exception:
            pass


def _read_pages(path: Path, *, max_pages: int, max_page_chars: int, max_total_chars: int) -> tuple[list[str], tuple[ParseWarning, ...]]:
    try:
        import pdfplumber
    except Exception as exc:
        return [], (ParseWarning("pdf_read_failed", f"PDF decoder unavailable: {type(exc).__name__}", "error", "document"),)
    warnings: list[ParseWarning] = []
    pages: list[str] = []
    total = 0
    try:
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            page_limit = min(page_count, max_pages)
            for number in range(page_limit):
                raw = pdf.pages[number].extract_text() or ""
                if len(raw) > max_page_chars:
                    warnings.append(ParseWarning("page_text_limit", "PDF page text exceeded the per-page bound", "error", f"page {number + 1}"))
                    pages.append("")
                    break
                normalised = _normalise_page(raw)
                total += len(normalised)
                if total > max_total_chars:
                    warnings.append(ParseWarning("total_text_limit", "PDF text exceeded the total output bound", "error", f"page {number + 1}"))
                    break
                pages.append(normalised)
            if page_count > max_pages:
                warnings.append(ParseWarning("page_limit_applied", "PDF page count exceeded the parser bound", "error", f"page {max_pages}"))
        return pages, tuple(warnings)
    except Exception as exc:
        return [], (ParseWarning("pdf_read_failed", f"PDF decode failed: {type(exc).__name__}", "error", "document"),)


def _extract_field(pattern: _FieldPattern, pages: list[str]) -> EtfReportFieldEvidence:
    grouped: dict[str, tuple[str, set[int], list[str]]] = {}
    for number, page in enumerate(pages, start=1):
        for match in re.finditer(pattern.expression, page, re.IGNORECASE):
            value = " ".join(match.group("value").strip().split())
            if not value:
                continue
            key = value.casefold()
            grouped.setdefault(key, (value, set(), []))
            grouped[key][1].add(number)
            grouped[key][2].append(page[max(0, match.start() - 80): match.end() + 80])
    if not grouped:
        return EtfReportFieldEvidence(pattern.field_name, None, None, "unknown", "unknown", (), pattern.label)
    values = tuple(item[0] for item in grouped.values())
    candidate_pages = tuple(sorted(page for _, pages_for_value, _ in grouped.values() for page in pages_for_value))
    excerpts = " | ".join(f"page {page}: {excerpt}" for value, pages_for_value, excerpts_for_value in grouped.values() for page in sorted(pages_for_value) for excerpt in excerpts_for_value)
    excerpts = " ".join(excerpts.split())[:MAX_EXCERPT_CHARS]
    if len(values) > 1:
        return EtfReportFieldEvidence(pattern.field_name, None, None, "low", "conflict", values, pattern.label, candidate_pages, excerpts)
    value, pages_for_value, _ = next(iter(grouped.values()))
    if len(value) > MAX_FIELD_VALUE_CHARS:
        return EtfReportFieldEvidence(pattern.field_name, None, min(pages_for_value), "low", "truncated", (value[:MAX_FIELD_VALUE_CHARS],), pattern.label, tuple(sorted(pages_for_value)), excerpts)
    return EtfReportFieldEvidence(pattern.field_name, value, min(pages_for_value), "high", "extracted", values, pattern.label, tuple(sorted(pages_for_value)), excerpts)


def _normalise_dates(evidence: list[EtfReportFieldEvidence], fields: dict[str, str | None]) -> tuple[list[EtfReportFieldEvidence], dict[str, str | None]]:
    updated = list(evidence)
    for index, item in enumerate(updated):
        if item.field_name not in {"document_date", "reporting_period_end"} or not item.value:
            continue
        normalised = _normalise_date(item.value)
        if normalised is None:
            fields[item.field_name] = None
            updated[index] = EtfReportFieldEvidence(item.field_name, None, item.source_page, "low", "malformed", item.candidates, item.matched_label, item.candidate_pages, item.source_excerpt)
        elif datetime.fromisoformat(normalised).date() > datetime.now(timezone.utc).date():
            fields[item.field_name] = None
            updated[index] = EtfReportFieldEvidence(item.field_name, None, item.source_page, "low", "future", item.candidates, item.matched_label, item.candidate_pages, item.source_excerpt)
        else:
            fields[item.field_name] = normalised
            updated[index] = EtfReportFieldEvidence(item.field_name, normalised, item.source_page, item.confidence, item.status, (normalised,), item.matched_label, item.candidate_pages, item.source_excerpt)
    return updated, fields


def _normalise_date(value: str | date | datetime | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    if isinstance(value, datetime):
        parsed = value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
        return parsed.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    candidate = " ".join(str(value).replace(",", "").split())
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalise_page(value: str) -> str:
    return "\n".join(" ".join(line.split()) for line in str(value).splitlines() if line.strip())


def _looks_english(text: str) -> bool:
    lowered = text.casefold()
    anchors = ("prospectus", "annual report", "half-year report", "half year report", "fund name", "isin", "legal structure", "document date")
    return sum(anchor in lowered for anchor in anchors) >= 2


def _pages_location(item: EtfReportFieldEvidence) -> str:
    return ", ".join(f"page {page}" for page in item.candidate_pages) or "document"


def _failure(code: str, message: str, source_sha: str) -> ParseResult[EtfReportRecord]:
    return ParseResult((), (ParseWarning(code, message, "error", "document"),), "etf_report", PARSER_VERSION, source_sha, False)


def _sha256_if_present(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    except OSError:
        return ""


__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_PAGE_CHARS",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_TOTAL_CHARS",
    "DEFAULT_MEMORY_LIMIT_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "EtfReportFieldEvidence",
    "EtfReportRecord",
    "PARSER_VERSION",
    "REPORT_FIELDS",
    "REPORT_KINDS",
    "REQUIRED_FIELDS",
    "ReportTemplatePlugin",
    "available_report_plugins",
    "canonical_report_kind",
    "configure_memory_limit",
    "memory_limit_backend",
    "parse_etf_report",
    "parse_etf_report_in_child",
]
