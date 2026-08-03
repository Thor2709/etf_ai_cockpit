"""Atomic persistence for parsed PRIIPs KID and methodology evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR
from etf_cockpit.data.fund_documents import (
    FUND_DOCUMENTS_PATH,
    fund_document_registry_guard,
    build_document_inventory,
    read_document_registry,
    register_document,
    _register_report_document,
    report_source_id,
    unavailable_document,
)
from etf_cockpit.parsers.etf_report import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_PAGE_CHARS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_TOTAL_CHARS,
    DEFAULT_MEMORY_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    REPORT_FIELDS,
    EtfReportRecord,
    canonical_report_kind,
    parse_etf_report_in_child,
)
from etf_cockpit.parsers.contracts import ParseResult
from etf_cockpit.parsers.index_methodology import IndexMethodologyRecord, apply_methodology_holdings_assessment
from etf_cockpit.parsers.priips_kid import PriipsKidRecord


PRIIPS_KID_RECORDS_PATH = CLEAN_DIR / "priips_kid_records.parquet"
INDEX_METHODOLOGY_RECORDS_PATH = CLEAN_DIR / "index_methodology_records.parquet"
ETF_REPORT_RECORDS_PATH = CLEAN_DIR / "etf_report_records.parquet"
ETF_REPORT_CONFLICTS_PATH = CLEAN_DIR / "etf_report_conflicts.parquet"
REPORT_RAW_DIR = RAW_DIR / "etf_reports"

KID_COLUMNS = [
    "schema_version", "source_id", "instrument_id", "parser_name", "parser_version", "source_sha256", "source_authority", "freshness_status",
    "source_pages", "product", "isin", "manufacturer", "sri", "cost_fields", "holding_period_years",
    "scenarios", "document_date", "document_version", "extraction_confidence", "warnings", "manual_review",
    "score_eligible", "success", "imported_at",
]
METHODOLOGY_COLUMNS = [
    "schema_version", "source_id", "instrument_id", "parser_name", "parser_version", "source_sha256", "source_authority", "freshness_status",
    "source_pages", "provider", "index_series", "version", "document_date", "eligibility_rules",
    "weighting_rules", "review_frequency", "caps", "confidence", "warnings", "manual_review",
    "score_eligible", "success", "imported_at",
]


def persist_priips_kid_result(
    result: ParseResult[PriipsKidRecord],
    instrument_id: str,
    *,
    destination: Path = PRIIPS_KID_RECORDS_PATH,
) -> Path:
    rows = [_kid_row(result, instrument_id, record) for record in result.records]
    if not rows:
        rows = [_kid_unavailable_row(result, instrument_id)]
    return _persist_rows(rows, destination, KID_COLUMNS)


def persist_index_methodology_result(
    result: ParseResult[IndexMethodologyRecord],
    instrument_id: str,
    *,
    destination: Path = INDEX_METHODOLOGY_RECORDS_PATH,
    holdings: pd.DataFrame | None = None,
) -> Path:
    if holdings is not None:
        result = apply_methodology_holdings_assessment(result, holdings)
    rows = [_methodology_row(result, instrument_id, record) for record in result.records]
    if not rows:
        rows = [_methodology_unavailable_row(result, instrument_id)]
    return _persist_rows(rows, destination, METHODOLOGY_COLUMNS)


def read_priips_kid_records(path: Path = PRIIPS_KID_RECORDS_PATH) -> pd.DataFrame:
    return _read_frame(path, KID_COLUMNS)


def read_index_methodology_records(path: Path = INDEX_METHODOLOGY_RECORDS_PATH) -> pd.DataFrame:
    return _read_frame(path, METHODOLOGY_COLUMNS)


# Compatibility aliases for import callers.
persist_priips_kid = persist_priips_kid_result
persist_index_methodology = persist_index_methodology_result


def persist_priips_kid_with_document(
    result: ParseResult[PriipsKidRecord],
    instrument_id: str,
    document_path: Path,
    *,
    destination: Path = PRIIPS_KID_RECORDS_PATH,
    registry_destination: Path = FUND_DOCUMENTS_PATH,
    source_url: str = "",
    authority: str = "issuer_document",
    document_date: str | None = None,
    configured_instrument_ids: Iterable[str] = (),
) -> Path:
    """Publish KID parsed rows and the FundDocument registry as one transaction."""

    return _persist_with_document(
        result,
        instrument_id,
        document_path,
        "kid",
        destination=destination,
        registry_destination=registry_destination,
        source_url=source_url,
        authority=authority,
        document_date=document_date or (result.records[0].document_date if result.records else None),
        configured_instrument_ids=configured_instrument_ids,
    )


def persist_index_methodology_with_document(
    result: ParseResult[IndexMethodologyRecord],
    instrument_id: str,
    document_path: Path,
    *,
    destination: Path = INDEX_METHODOLOGY_RECORDS_PATH,
    registry_destination: Path = FUND_DOCUMENTS_PATH,
    source_url: str = "",
    authority: str = "issuer_document",
    document_date: str | None = None,
    configured_instrument_ids: Iterable[str] = (),
    holdings: pd.DataFrame | None = None,
) -> Path:
    """Publish methodology parsed rows and the FundDocument registry atomically."""

    document_available = bool(result.records and Path(document_path).is_file())
    if holdings is not None:
        result = apply_methodology_holdings_assessment(result, holdings)
    return _persist_with_document(
        result,
        instrument_id,
        document_path,
        "methodology",
        destination=destination,
        registry_destination=registry_destination,
        source_url=source_url,
        authority=authority,
        document_date=document_date,
        configured_instrument_ids=configured_instrument_ids,
        document_available=document_available,
    )


def _persist_with_document(
    result: ParseResult[Any],
    instrument_id: str,
    document_path: Path,
    document_type: str,
    *,
    destination: Path,
    registry_destination: Path,
    source_url: str,
    authority: str,
    document_date: str | None,
    configured_instrument_ids: Iterable[str],
    document_available: bool | None = None,
) -> Path:
    destination = Path(destination)
    registry_destination = Path(registry_destination)
    if document_type == "kid":
        columns = KID_COLUMNS
        rows = [_kid_row(result, instrument_id, record) for record in result.records]
        if not rows:
            rows = [_kid_unavailable_row(result, instrument_id)]
    else:
        columns = METHODOLOGY_COLUMNS
        rows = [_methodology_row(result, instrument_id, record) for record in result.records]
        if not rows:
            rows = [_methodology_unavailable_row(result, instrument_id)]
    if result.success or document_available is True:
        document = register_document(
            Path(document_path),
            document_type,
            instrument_id,
            source_url,
            authority,
            document_date=document_date,
        )
    else:
        warning_codes = ", ".join(item.code for item in result.warnings) or "parse_failed"
        document = unavailable_document(instrument_id, document_type, warning_codes)
    # All registry publishers acquire the registry guard first, then their
    # disclosure-store guard. This keeps one lock order across report/KID/
    # methodology and generic imports.
    with fund_document_registry_guard(registry_destination):
        with persistent_file_guard(_guard_path(destination), timeout_seconds=5.0):
            existing = _read_frame(destination, columns)
            incoming = pd.DataFrame(rows, columns=columns)
            combined = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming
            if not combined.empty:
                combined = combined.drop_duplicates(subset=["source_id"], keep="last").sort_values("source_id", kind="stable").reset_index(drop=True)
            registry_existing = _read_registry_fail_closed(registry_destination)
            ids = [str(item).strip() for item in configured_instrument_ids if str(item).strip()]
            if not registry_existing.empty and "instrument_id" in registry_existing.columns:
                ids.extend(value for value in registry_existing["instrument_id"].dropna().astype(str).map(str.strip) if value)
            ids.append(str(instrument_id).strip())
            inventory = build_document_inventory(ids, [*registry_existing.to_dict("records"), document])
            requests = (
                AtomicWriteRequest(destination, parquet_payload(combined), validate_parquet_file),
                AtomicWriteRequest(destination.with_suffix(".csv"), combined.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
                AtomicWriteRequest(registry_destination, parquet_payload(inventory), validate_parquet_file),
                AtomicWriteRequest(registry_destination.with_suffix(".csv"), inventory.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
            )
            atomic_write_group(requests)
    return destination


def _read_registry_fail_closed(path: Path) -> pd.DataFrame:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return pd.DataFrame()
    try:
        raw = pd.read_parquet(candidate)
    except Exception as exc:
        raise ValueError(f"Fund document registry is corrupt: {candidate}") from exc
    normalised = read_document_registry(path=candidate)
    if len(normalised) != len(raw):
        raise ValueError(f"Fund document registry contains duplicate source_id: {candidate}")
    return normalised


def _validate_report_registry_identity_parity(
    reports: pd.DataFrame,
    registry: pd.DataFrame,
) -> None:
    report_ids = [
        str(value).strip()
        for value in reports.get("source_id", pd.Series(dtype=str)).tolist()
        if str(value).strip().startswith("report:v2:")
    ]
    registry_ids = [
        str(value).strip()
        for value in registry.get("source_id", pd.Series(dtype=str)).tolist()
        if str(value).strip().startswith("report:v2:")
    ]
    if len(report_ids) != len(set(report_ids)):
        raise ValueError("ETF report store contains duplicate source_id")
    if len(registry_ids) != len(set(registry_ids)):
        raise ValueError("Fund document registry contains duplicate source_id")
    if set(report_ids) != set(registry_ids):
        raise ValueError("ETF report and registry v2 identity sets are inconsistent")


def _kid_row(result: ParseResult[PriipsKidRecord], instrument_id: str, record: PriipsKidRecord) -> dict[str, Any]:
    return {
        "schema_version": int(getattr(record, "schema_version", 2)),
        "source_id": _source_id("kid", instrument_id, result.source_sha256),
        "instrument_id": str(instrument_id or "").strip(),
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "source_sha256": result.source_sha256,
        "source_authority": "issuer_document",
        "freshness_status": _freshness(record.document_date),
        "source_pages": _json(getattr(record, "source_pages", ())),
        "product": record.product,
        "isin": record.isin,
        "manufacturer": record.manufacturer,
        "sri": record.sri,
        "cost_fields": _json(record.cost_fields),
        "holding_period_years": record.holding_period_years,
        "scenarios": _json(record.scenarios),
        "document_date": record.document_date,
        "document_version": getattr(record, "document_version", None),
        "extraction_confidence": record.extraction_confidence,
        "warnings": _json(_warning_payload(result.warnings, record.warnings)),
        "manual_review": bool(getattr(record, "manual_review", False) or result.warnings),
        "score_eligible": _eligible(getattr(record, "score_eligible", False), result.success, _freshness(record.document_date)),
        "success": bool(result.success),
        "imported_at": _utc_now(),
    }


def _kid_unavailable_row(result: ParseResult[PriipsKidRecord], instrument_id: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "source_id": _source_id("kid", instrument_id, result.source_sha256 or _warning_digest(result)),
        "instrument_id": str(instrument_id or "").strip(),
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "source_sha256": result.source_sha256,
        "source_authority": "issuer_document",
        "freshness_status": "unknown",
        "source_pages": "[]",
        "product": "",
        "isin": "",
        "manufacturer": "",
        "sri": None,
        "cost_fields": "{}",
        "holding_period_years": None,
        "scenarios": "[]",
        "document_date": None,
        "document_version": None,
        "extraction_confidence": "unavailable",
        "warnings": _json(_warning_payload(result.warnings)),
        "manual_review": True,
        "score_eligible": False,
        "success": False,
        "imported_at": _utc_now(),
    }


def _methodology_row(result: ParseResult[IndexMethodologyRecord], instrument_id: str, record: IndexMethodologyRecord) -> dict[str, Any]:
    return {
        "schema_version": int(getattr(record, "schema_version", 2)),
        "source_id": _source_id("methodology", instrument_id, result.source_sha256),
        "instrument_id": str(instrument_id or "").strip(),
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "source_sha256": result.source_sha256,
        "source_authority": "issuer_document",
        "freshness_status": _freshness(record.document_date),
        "source_pages": _json(record.source_pages),
        "provider": record.provider,
        "index_series": record.index_series,
        "version": record.version,
        "document_date": record.document_date,
        "eligibility_rules": _json(record.eligibility_rules),
        "weighting_rules": _json(record.weighting_rules),
        "review_frequency": record.review_frequency,
        "caps": _json(record.caps),
        "confidence": record.confidence,
        "warnings": _json(_warning_payload(result.warnings, record.warnings)),
        "manual_review": bool(getattr(record, "manual_review", False) or result.warnings),
        "score_eligible": _eligible(getattr(record, "score_eligible", False), result.success, _freshness(record.document_date)),
        "success": bool(result.success),
        "imported_at": _utc_now(),
    }


def _methodology_unavailable_row(result: ParseResult[IndexMethodologyRecord], instrument_id: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "source_id": _source_id("methodology", instrument_id, result.source_sha256 or _warning_digest(result)),
        "instrument_id": str(instrument_id or "").strip(),
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "source_sha256": result.source_sha256,
        "source_authority": "issuer_document",
        "freshness_status": "unknown",
        "source_pages": "[]",
        "provider": "",
        "index_series": "",
        "version": None,
        "document_date": None,
        "eligibility_rules": "[]",
        "weighting_rules": "[]",
        "review_frequency": None,
        "caps": "[]",
        "confidence": "unavailable",
        "warnings": _json(_warning_payload(result.warnings)),
        "manual_review": True,
        "score_eligible": False,
        "success": False,
        "imported_at": _utc_now(),
    }


def _persist_rows(rows: list[dict[str, Any]], destination: Path, columns: list[str]) -> Path:
    destination = Path(destination)
    existing = _read_frame(destination, columns)
    incoming = pd.DataFrame(rows, columns=columns)
    combined = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["source_id"], keep="last").sort_values("source_id", kind="stable").reset_index(drop=True)
    requests = (
        AtomicWriteRequest(destination, parquet_payload(combined), validate_parquet_file),
        AtomicWriteRequest(destination.with_suffix(".csv"), combined.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
    )
    atomic_write_group(requests)
    return destination


def _read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return pd.DataFrame(columns=columns)
    try:
        frame = pd.read_parquet(candidate)
    except Exception as exc:
        raise ValueError(f"Parsed disclosure store is corrupt: {candidate}") from exc
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    return frame[columns]


def _source_id(kind: str, instrument_id: str, checksum: str) -> str:
    payload = "|".join((kind, str(instrument_id or "").strip(), str(checksum or "missing")))
    return f"parsed:{'kid' if kind == 'kid' else 'methodology'}:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _warning_digest(result: ParseResult[Any]) -> str:
    return hashlib.sha256("|".join(item.code for item in result.warnings).encode("utf-8")).hexdigest()


def _warning_payload(warnings: Iterable[Any], fallback: Iterable[str] = ()) -> list[object]:
    items = list(warnings)
    if items:
        return [
            {
                "code": item.code,
                "message": item.message,
                "severity": item.severity,
                "source_location": item.source_location,
            }
            for item in items
        ]
    return list(fallback)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _freshness(document_date: str | None) -> str:
    if not document_date:
        return "missing_or_pending"
    try:
        parsed = pd.Timestamp(document_date).date()
    except Exception:
        return "unknown"
    age_days = (datetime.now(timezone.utc).date() - parsed).days
    if age_days < 0:
        return "unknown"
    if age_days <= 10:
        return "ok"
    if age_days <= 90:
        return "warning"
    return "stale_block"


def _eligible(record_eligible: bool, success: bool, freshness: str) -> bool:
    return bool(record_eligible and success and freshness == "ok")


__all__ = [
    "INDEX_METHODOLOGY_RECORDS_PATH",
    "KID_COLUMNS",
    "METHODOLOGY_COLUMNS",
    "PRIIPS_KID_RECORDS_PATH",
    "persist_index_methodology",
    "persist_index_methodology_result",
    "persist_index_methodology_with_document",
    "persist_priips_kid",
    "persist_priips_kid_result",
    "persist_priips_kid_with_document",
    "read_index_methodology_records",
    "read_priips_kid_records",
]


class ReportSourceAuthority(StrEnum):
    OFFICIAL_REGULATOR = "official_regulator"
    ISSUER_DOCUMENT = "issuer_document"
    LOCAL_USER_IMPORT = "local_user_import"


EtfReportAuthority = ReportSourceAuthority


@dataclass(frozen=True)
class EtfReportImportRequest:
    """Typed authority boundary for local ETF report imports."""

    instrument_id: str
    document_kind: str
    source_authority: ReportSourceAuthority | str
    source_path: Path | None = None
    path: Path | None = None
    expected_isin: str | None = None
    expected_document_date: str | date | datetime | None = None
    expected_sha256: str | None = None
    source_url: str = ""
    configured_instrument_ids: tuple[str, ...] = ()
    destination: Path = ETF_REPORT_RECORDS_PATH
    registry_destination: Path = FUND_DOCUMENTS_PATH
    conflict_destination: Path = ETF_REPORT_CONFLICTS_PATH
    raw_dir: Path = RAW_DIR
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_pages: int = DEFAULT_MAX_PAGES
    max_page_chars: int = DEFAULT_MAX_PAGE_CHARS
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES

    def resolved_path(self) -> Path:
        candidate = self.source_path or self.path
        if candidate is None:
            raise ValueError("source_path is required")
        return Path(candidate)

    def canonical_kind(self) -> str:
        return canonical_report_kind(self.document_kind)

    def authority(self) -> ReportSourceAuthority:
        try:
            return self.source_authority if isinstance(self.source_authority, ReportSourceAuthority) else ReportSourceAuthority(str(self.source_authority).strip().lower())
        except ValueError as exc:
            raise ValueError("source_authority must be official_regulator, issuer_document, or local_user_import") from exc


@dataclass(frozen=True)
class EtfReportReviewRequest:
    source_id: str
    extraction_sha256: str
    reviewer: str
    decision: str
    note: str | None = None


@dataclass(frozen=True)
class EtfReportImportResult:
    source_id: str
    document: Any
    parse_result: ParseResult[EtfReportRecord]
    extraction_status: str
    report_path: Path
    registry_path: Path
    conflict_path: Path

    @property
    def success(self) -> bool:
        return self.parse_result.success


REPORT_SCHEMA_VERSION = 2.1
REPORT_COLUMNS = [
    "schema_version", "source_id", "instrument_id", "document_type", "document_kind",
    "parser_name", "parser_version", "language_plugin", "template_plugin", "source_sha256",
    "source_authority", "source_url", "source_pages", "known_at", *REPORT_FIELDS, "structured_fields", "field_evidence", "warnings", "extraction_status",
    "parse_success", "extraction_sha256", "stored_extraction_sha256", "verification_status",
    "verified_by", "verified_at", "review_note", "review_history", "manual_review",
    "evidence_eligible", "score_eligible", "execution_allowed", "imported_at", "registry_path",
]
_REVIEW_COLUMNS = frozenset({
    "verification_status", "verified_by", "verified_at", "review_note", "review_history",
    "manual_review", "evidence_eligible", "score_eligible", "execution_allowed",
    "extraction_sha256", "stored_extraction_sha256", "imported_at",
})
_PRE_21_REPORT_FIELDS = (
    "fund_name", "isin", "document_date", "reporting_period_end",
    "legal_structure", "securities_lending", "collateral_policy",
    "ongoing_costs", "holdings_count", "operational_risks",
)
_LEGACY_REPORT_COLUMNS = (
    "schema_version", "source_id", "instrument_id", "document_type", "document_kind",
    "parser_name", "parser_version", "language_plugin", "template_plugin", "source_sha256",
    "source_authority", "source_url", "source_pages", *_PRE_21_REPORT_FIELDS,
    "structured_fields", "field_evidence", "warnings", "extraction_status", "parse_success",
    "extraction_sha256", "stored_extraction_sha256", "verification_status", "verified_by",
    "verified_at", "review_note", "review_history", "manual_review", "evidence_eligible",
    "score_eligible", "execution_allowed", "imported_at", "registry_path",
)


def import_etf_report(request: EtfReportImportRequest) -> EtfReportImportResult:
    """Snapshot, parse and persist one report without accepting caller results."""

    if not isinstance(request, EtfReportImportRequest):
        raise TypeError("ETF report imports require EtfReportImportRequest")
    kind = request.canonical_kind()
    authority = request.authority().value
    instrument = str(request.instrument_id or "").strip()
    if not instrument:
        raise ValueError("instrument_id is required")
    source_path = request.resolved_path()
    checksum, snapshot = _retain_bounded_snapshot(source_path, request.raw_dir, request.max_file_bytes)
    expected_checksum = str(request.expected_sha256 or "").strip().lower()
    if expected_checksum and checksum != expected_checksum:
        raise ValueError("source checksum does not match expected_sha256")
    snapshot_path = Path(request.raw_dir) / "etf_reports" / f"{checksum}.pdf"
    snapshot_guard = _guard_path(snapshot_path)
    # A checksum-specific guard remains held from first publication through
    # decode and the final atomic group, preventing a mutable retained file
    # from diverging from its registry and extraction identities.
    with persistent_file_guard(snapshot_guard, timeout_seconds=request.timeout_seconds):
        if not snapshot_path.exists():
            atomic_write_bytes(snapshot_path, snapshot, validator=lambda path: _validate_snapshot(path, snapshot, checksum))
        elif not _snapshot_matches(snapshot_path, snapshot, checksum):
            raise ValueError("immutable ETF report snapshot is corrupt")
        parse_result = parse_etf_report_in_child(
            snapshot_path,
            kind,
            expected_isin=request.expected_isin,
            expected_document_date=request.expected_document_date,
            max_file_bytes=request.max_file_bytes,
            max_pages=request.max_pages,
            max_page_chars=request.max_page_chars,
            max_total_chars=request.max_total_chars,
            timeout_seconds=request.timeout_seconds,
            memory_limit_bytes=request.memory_limit_bytes,
        )
        if any(item.code == "document_date_mismatch" for item in parse_result.warnings):
            raise ValueError("source document_date does not match expected_document_date")
        if parse_result.source_sha256 != checksum:
            raise ValueError("parser result checksum is not bound to retained snapshot")
        if parse_result.records and parse_result.records[0].document_kind != kind:
            raise ValueError("parser result document kind is not bound to import request")
        record = parse_result.records[0] if parse_result.records else None
        document_date = record.document_date if record is not None else None
        source_id = report_source_id(
            instrument,
            kind,
            checksum,
            document_date,
            authority,
            parser_name=parse_result.parser_name,
            parser_version=parse_result.parser_version,
            language_plugin=record.language_plugin if record else None,
            template_plugin=record.template_plugin if record else None,
        )
        extraction_status = _report_extraction_status(parse_result)
        document = _register_report_document(
            snapshot_path,
            instrument_id=instrument,
            document_kind=kind,
            source_url=request.source_url,
            authority=authority,
            sha256=checksum,
            document_date=document_date,
            extraction_status=extraction_status,
            source_id=source_id,
        )
        report_row = _report_row(parse_result, record, request, document, source_id, extraction_status)
        with fund_document_registry_guard(Path(request.registry_destination), timeout_seconds=request.timeout_seconds):
            with persistent_file_guard(_guard_path(Path(request.destination)), timeout_seconds=request.timeout_seconds):
                with persistent_file_guard(_guard_path(Path(request.conflict_destination)), timeout_seconds=request.timeout_seconds):
                    registry_existing = _read_registry_fail_closed(Path(request.registry_destination))
                    report_existing = _read_report_frame(Path(request.destination))
                    _validate_report_registry_identity_parity(report_existing, registry_existing)
                    registry_match = registry_existing.loc[registry_existing["source_id"].astype(str).eq(source_id)] if not registry_existing.empty else pd.DataFrame()
                    report_match = report_existing.loc[report_existing["source_id"].astype(str).eq(source_id)] if not report_existing.empty else pd.DataFrame()
                    if len(registry_match) > 1:
                        raise ValueError("same-ID registry extraction is corrupt: duplicate source_id")
                    if len(report_match) > 1:
                        raise ValueError("same-ID report extraction is corrupt: duplicate source_id")
                    if registry_match.empty != report_match.empty:
                        raise ValueError("same-ID report and registry extraction state is inconsistent")
                    if len(registry_match) == 1:
                        prior_registry = registry_match.iloc[0]
                        identity = {
                            "instrument_id": document.instrument_id,
                            "document_kind": document.document_kind,
                            "source_sha256": checksum,
                            "source_authority": document.authority,
                            "document_date": document.document_date,
                        }
                        for field, old_field in (("instrument_id", "instrument_id"), ("document_kind", "document_kind"), ("source_sha256", "sha256"), ("source_authority", "authority"), ("document_date", "document_date")):
                            if _cell_text(prior_registry.get(old_field)) != _cell_text(identity[field]):
                                raise ValueError(f"same-ID registry identity mismatch: {field}")
                        report_row["known_at"] = _registry_known_at(prior_registry)
                        refreshed_fingerprint = _row_extraction_fingerprint(pd.Series(report_row))
                        report_row["extraction_sha256"] = refreshed_fingerprint
                        report_row["stored_extraction_sha256"] = refreshed_fingerprint
                    combined = _merge_report_row(report_existing, report_row)
                    ids = [str(item).strip() for item in request.configured_instrument_ids if str(item).strip()]
                    if not registry_existing.empty and "instrument_id" in registry_existing.columns:
                        ids.extend(value for value in registry_existing["instrument_id"].dropna().astype(str).map(str.strip) if value)
                    ids.append(instrument)
                    registry_records = registry_existing.to_dict("records")
                    if registry_match.empty:
                        registry_records.append(document)
                    inventory = build_document_inventory(ids, registry_records)
                    inventory = _preserve_registry_rows(inventory, registry_existing)
                    conflicts = build_etf_report_conflicts(combined)
                    combined = _apply_conflict_eligibility(combined, conflicts, inventory)
                    _write_report_group(
                        combined, inventory, conflicts, Path(request.destination), Path(request.registry_destination),
                        Path(request.conflict_destination), snapshot_path=snapshot_path, snapshot=snapshot, snapshot_sha256=checksum,
                    )
    return EtfReportImportResult(source_id, document, parse_result, extraction_status, Path(request.destination), Path(request.registry_destination), Path(request.conflict_destination))


def read_etf_report_records(path: Path = ETF_REPORT_RECORDS_PATH) -> pd.DataFrame:
    return _read_report_frame(Path(path))


def review_etf_report(
    request: EtfReportReviewRequest,
    *,
    destination: Path = ETF_REPORT_RECORDS_PATH,
    registry_destination: Path = FUND_DOCUMENTS_PATH,
    conflict_destination: Path | None = None,
) -> Path:
    """Append a typed human review using a server-generated current timestamp."""

    if not isinstance(request, EtfReportReviewRequest):
        raise TypeError("ETF report reviews require EtfReportReviewRequest")
    source_id = str(request.source_id or "").strip()
    fingerprint = str(request.extraction_sha256 or "").strip().lower()
    reviewer = str(request.reviewer or "").strip()
    decision = str(request.decision or "").strip().lower()
    if not source_id or not reviewer or len(fingerprint) != 64:
        raise ValueError("source_id, reviewer and exact extraction_sha256 are required")
    if decision not in {"verified", "rejected"}:
        raise ValueError("review decision must be verified or rejected")
    conflict_path = Path(conflict_destination or Path(destination).with_name("etf_report_conflicts.parquet"))
    with fund_document_registry_guard(Path(registry_destination), timeout_seconds=5.0):
        with persistent_file_guard(_guard_path(Path(destination)), timeout_seconds=5.0):
            with persistent_file_guard(_guard_path(conflict_path), timeout_seconds=5.0):
                frame = _read_report_frame(Path(destination))
                matches = frame.index[frame["source_id"].astype(str).eq(source_id)]
                if len(matches) != 1:
                    raise ValueError("review source_id is not bound to exactly one extraction")
                index = matches[0]
                row = frame.loc[index].copy()
                stored_registry_path = _cell_text(row.get("registry_path"))
                if not stored_registry_path or Path(stored_registry_path).resolve() != Path(registry_destination).resolve():
                    raise ValueError("review registry_destination does not match extraction registry_path")
                if not _fingerprint_matches(row, fingerprint) or str(row.get("stored_extraction_sha256", "")) != fingerprint:
                    raise ValueError("review fingerprint does not match stored extraction")
                _validate_report_binding(row, Path(registry_destination))
                history = _review_history(row.get("review_history"), expected_fingerprint=fingerprint, row=row)
                now = datetime.now(timezone.utc)
                if history:
                    last = _review_timestamp(history[-1])
                    if now < last:
                        raise ValueError("review history is not ordered")
                if decision == "verified":
                    if not _row_is_verifiable(row):
                        raise ValueError("only a complete, fully evidenced extraction can be verified")
                    current_conflicts = build_etf_report_conflicts(frame)
                    if source_id in set(current_conflicts.get("source_id_a", ())) | set(current_conflicts.get("source_id_b", ())):
                        raise ValueError("conflicting report evidence requires manual resolution")
                history.append({
                    "decision": decision,
                    "reviewer": reviewer,
                    "note": str(request.note or "").strip(),
                    "reviewed_at": now.isoformat(timespec="seconds"),
                    "extraction_sha256": fingerprint,
                })
                frame.at[index, "verification_status"] = decision
                frame.at[index, "verified_by"] = reviewer
                frame.at[index, "verified_at"] = now.isoformat(timespec="seconds")
                frame.at[index, "review_note"] = str(request.note or "").strip()
                frame.at[index, "review_history"] = _json(history)
                frame.at[index, "manual_review"] = decision != "verified"
                frame.at[index, "evidence_eligible"] = decision == "verified"
                frame.at[index, "score_eligible"] = False
                frame.at[index, "execution_allowed"] = False
                conflicts = build_etf_report_conflicts(frame)
                registry = _read_registry_fail_closed(Path(registry_destination))
                frame = _apply_conflict_eligibility(frame, conflicts, registry)
                _write_report_group(frame, registry, conflicts, Path(destination), Path(registry_destination), conflict_path, include_registry=False)
    return Path(destination)


review_etf_report_record = review_etf_report


def build_etf_report_conflicts(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(columns=REPORT_CONFLICT_COLUMNS)
    candidates = frame.loc[~frame["verification_status"].astype(str).eq("rejected")].copy()
    stable = {"fund_name", "isin", "legal_structure"}
    varying = set(REPORT_FIELDS) - stable - {"document_date", "reporting_period_end"}
    for instrument_id, group in candidates.groupby("instrument_id", sort=True):
        latest: dict[str, pd.Series] = {}
        for kind, kind_group in group.groupby("document_kind", sort=True):
            latest[str(kind)] = kind_group.sort_values(["document_date", "imported_at", "source_id"], kind="stable").iloc[-1]
        for field in (*stable, *sorted(varying)):
            pairs = list(latest.values())
            if field in varying:
                pairs = [row for row in pairs if str(row.get("reporting_period_end") or "").strip()]
                pairs = [row for row in pairs if all(str(row.get("reporting_period_end")) == str(other.get("reporting_period_end")) for other in pairs)]
            for left_index, left in enumerate(pairs):
                for right in pairs[left_index + 1:]:
                    left_value = _cell_text(left.get(field))
                    right_value = _cell_text(right.get(field))
                    if not left_value or not right_value or left_value == right_value:
                        continue
                    conflict_id = hashlib.sha256(f"{instrument_id}|{field}|{min(left['source_id'], right['source_id'])}|{max(left['source_id'], right['source_id'])}".encode()).hexdigest()
                    rows.append({
                        "conflict_id": f"report-conflict:{conflict_id}", "instrument_id": str(instrument_id), "field_name": field,
                        "source_id_a": str(left["source_id"]), "source_id_b": str(right["source_id"]),
                        "source_a": str(left["source_id"]), "source_b": str(right["source_id"]),
                        "document_kind_a": str(left["document_kind"]), "document_kind_b": str(right["document_kind"]),
                        "document_date_a": _cell_text(left.get("document_date")), "document_date_b": _cell_text(right.get("document_date")),
                        "reporting_period_end": _cell_text(left.get("reporting_period_end")), "value_a": left_value, "value_b": right_value,
                        "pages_a": _field_pages(left, field), "pages_b": _field_pages(right, field),
                        "resolution_status": "unresolved", "requires_manual_review": True, "canonical_value": None,
                        "score_eligible": False, "execution_allowed": False,
                    })
    return pd.DataFrame(rows, columns=REPORT_CONFLICT_COLUMNS)


REPORT_CONFLICT_COLUMNS = [
    "conflict_id", "instrument_id", "field_name", "source_id_a", "source_id_b", "source_a", "source_b",
    "document_kind_a", "document_kind_b", "document_date_a", "document_date_b", "reporting_period_end",
    "value_a", "value_b", "pages_a", "pages_b", "resolution_status", "requires_manual_review",
    "canonical_value", "score_eligible", "execution_allowed",
]


def read_etf_report_conflicts(path: Path = ETF_REPORT_CONFLICTS_PATH) -> pd.DataFrame:
    candidate = Path(path)
    if not candidate.is_file():
        return pd.DataFrame(columns=REPORT_CONFLICT_COLUMNS)
    try:
        frame = pd.read_parquet(candidate)
    except Exception as exc:
        raise ValueError(f"ETF report conflict store is corrupt: {candidate}") from exc
    for column in REPORT_CONFLICT_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame[REPORT_CONFLICT_COLUMNS]


def _retain_bounded_snapshot(source_path: Path, raw_dir: Path, max_file_bytes: int) -> tuple[str, bytes]:
    if max_file_bytes <= 0:
        raise ValueError("max_file_bytes must be positive")
    digest = hashlib.sha256()
    payload = bytearray()
    with Path(source_path).open("rb") as handle:
        while len(payload) <= max_file_bytes:
            chunk = handle.read(min(1024 * 1024, max_file_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            digest.update(chunk)
            if len(payload) > max_file_bytes:
                break
    checksum = digest.hexdigest()
    destination = Path(raw_dir) / "etf_reports" / f"{checksum}.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    return checksum, bytes(payload)


def _report_row(result: ParseResult[EtfReportRecord], record: EtfReportRecord | None, request: EtfReportImportRequest, document: Any, source_id: str, status: str) -> dict[str, Any]:
    fields = {field: (record.structured_fields.get(field) if record is not None else None) for field in REPORT_FIELDS}
    evidence = [_field_to_dict(item) for item in (record.field_evidence if record is not None else ())]
    row: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION, "source_id": source_id, "instrument_id": request.instrument_id, "document_type": "prospectus_report",
        "document_kind": request.canonical_kind(), "parser_name": result.parser_name, "parser_version": result.parser_version,
        "language_plugin": record.language_plugin if record else None, "template_plugin": record.template_plugin if record else None,
        "source_sha256": result.source_sha256, "source_authority": request.authority().value, "source_url": request.source_url,
        "source_pages": _json(record.source_pages if record else ()), "document_date": record.document_date if record else None,
        "known_at": getattr(document, "ingested_at", None),
        "reporting_period_end": fields["reporting_period_end"], **fields, "structured_fields": _json(fields), "field_evidence": _json(evidence),
        "warnings": _json(_warning_payload(result.warnings, record.warnings if record else ())), "extraction_status": status,
        "parse_success": bool(result.success), "verification_status": "pending", "verified_by": None, "verified_at": None,
        "review_note": "", "review_history": "[]", "manual_review": True, "evidence_eligible": False,
        "score_eligible": False, "execution_allowed": False, "imported_at": _utc_now(), "registry_path": str(request.registry_destination),
    }
    fingerprint = _row_extraction_fingerprint(pd.Series(row))
    row["extraction_sha256"] = fingerprint
    row["stored_extraction_sha256"] = fingerprint
    return row


def _preserve_registry_rows(inventory: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    """Keep byte-relevant registry state for identities already persisted."""

    if inventory.empty or existing.empty:
        return inventory
    existing_ids = set(existing["source_id"].dropna().astype(str))
    retained = existing.loc[existing["source_id"].astype(str).isin(set(inventory["source_id"].astype(str))), inventory.columns]
    additions = inventory.loc[~inventory["source_id"].astype(str).isin(existing_ids)]
    return pd.concat([retained, additions], ignore_index=True)[inventory.columns]


def _merge_report_row(existing: pd.DataFrame, incoming: dict[str, Any]) -> pd.DataFrame:
    if existing.empty:
        return pd.DataFrame([incoming], columns=REPORT_COLUMNS)
    matches = existing.index[existing["source_id"].astype(str).eq(str(incoming["source_id"]))]
    if len(matches) > 1:
        raise ValueError("same-ID report extraction is corrupt: duplicate source_id")
    if len(matches) == 1:
        prior = existing.loc[matches[0]].copy()
        for field in ("instrument_id", "document_kind", "source_sha256", "source_authority", "document_date"):
            if _cell_text(prior.get(field)) != _cell_text(incoming.get(field)):
                raise ValueError(f"same-ID report identity mismatch: {field}")
        prior_fingerprint = str(prior.get("stored_extraction_sha256") or "")
        if prior_fingerprint and _fingerprint_matches_rows(prior, incoming, prior_fingerprint):
            incoming["verification_status"] = prior.get("verification_status", "pending")
            incoming["verified_by"] = prior.get("verified_by")
            incoming["verified_at"] = prior.get("verified_at")
            incoming["review_note"] = prior.get("review_note", "")
            incoming["review_history"] = prior.get("review_history", "[]")
            incoming["manual_review"] = prior.get("manual_review", True)
            incoming["evidence_eligible"] = prior.get("evidence_eligible", False)
        else:
            raise ValueError("same-ID report extraction fingerprint mismatch")
        existing = existing.drop(index=matches[0])
    combined = pd.concat([existing, pd.DataFrame([incoming])], ignore_index=True)
    return _read_report_frame_from_frame(combined, validate_authority=False)


def _apply_conflict_eligibility(frame: pd.DataFrame, conflicts: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    conflicted = set(conflicts["source_id_a"].astype(str)) | set(conflicts["source_id_b"].astype(str)) if not conflicts.empty else set()
    for index, row in result.iterrows():
        result.at[index, "score_eligible"] = False
        result.at[index, "execution_allowed"] = False
        fingerprint = _cell_text(row.get("stored_extraction_sha256"))
        eligible = (
            _cell_text(row.get("verification_status")) == "verified"
            and bool(fingerprint)
            and _fingerprint_matches(row, fingerprint)
            and _row_is_verifiable(row)
            and _row_binding_matches_registry(row, registry)
            and str(row.get("source_id")) not in conflicted
        )
        result.at[index, "evidence_eligible"] = eligible
    return result


def _write_report_group(
    frame: pd.DataFrame,
    registry: pd.DataFrame,
    conflicts: pd.DataFrame,
    destination: Path,
    registry_destination: Path,
    conflict_destination: Path,
    *,
    include_registry: bool = True,
    snapshot_path: Path | None = None,
    snapshot: bytes | None = None,
    snapshot_sha256: str | None = None,
) -> None:
    requests = [
        AtomicWriteRequest(destination, parquet_payload(frame[REPORT_COLUMNS]), validate_parquet_file),
        AtomicWriteRequest(destination.with_suffix(".csv"), frame[REPORT_COLUMNS].to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
        AtomicWriteRequest(conflict_destination, parquet_payload(conflicts[REPORT_CONFLICT_COLUMNS]), validate_parquet_file),
        AtomicWriteRequest(conflict_destination.with_suffix(".csv"), conflicts[REPORT_CONFLICT_COLUMNS].to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
    ]
    if include_registry:
        requests.extend((
            AtomicWriteRequest(registry_destination, parquet_payload(registry), validate_parquet_file),
            AtomicWriteRequest(registry_destination.with_suffix(".csv"), registry.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
        ))
    if snapshot_path is not None:
        if snapshot is None or snapshot_sha256 is None:
            raise ValueError("snapshot bytes and checksum are required together")
        requests.append(AtomicWriteRequest(snapshot_path, snapshot, lambda path: _validate_snapshot(path, snapshot, snapshot_sha256)))
    atomic_write_group(requests)


def _read_report_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=REPORT_COLUMNS)
    try:
        return _read_report_frame_from_frame(pd.read_parquet(path))
    except Exception as exc:
        raise ValueError(f"ETF report extraction store is corrupt: {path}") from exc


def _read_report_frame_from_frame(frame: pd.DataFrame, *, validate_authority: bool = True) -> pd.DataFrame:
    result = frame.copy()
    for column in REPORT_COLUMNS:
        if column not in result.columns:
            result[column] = None
    result = result[REPORT_COLUMNS].sort_values("source_id", kind="stable").reset_index(drop=True)
    _backfill_legacy_known_at(result)
    for _, row in result.iterrows():
        fingerprint = _cell_text(row.get("stored_extraction_sha256"))
        if fingerprint and not _fingerprint_matches(row, fingerprint):
            raise ValueError("stored extraction fingerprint does not match extraction")
        _review_history(row.get("review_history"), expected_fingerprint=fingerprint or None, row=row)
    if validate_authority:
        conflicts = build_etf_report_conflicts(result)
        conflicted = set(conflicts["source_id_a"].astype(str)) | set(conflicts["source_id_b"].astype(str)) if not conflicts.empty else set()
        for _, row in result.iterrows():
            fingerprint = _cell_text(row.get("stored_extraction_sha256"))
            registry_path = _cell_text(row.get("registry_path"))
            eligible = (
                _cell_text(row.get("verification_status")) == "verified"
                and bool(fingerprint)
                and _fingerprint_matches(row, fingerprint)
                and _row_is_verifiable(row)
                and bool(registry_path)
                and _row_binding_matches_registry(row, _read_registry_fail_closed(Path(registry_path)))
                and str(row.get("source_id")) not in conflicted
            )
            if _strict_stored_bool(row.get("evidence_eligible"), "evidence_eligible") != eligible:
                raise ValueError("evidence eligibility does not match persisted evidence")
    return result


def _report_extraction_status(result: ParseResult[EtfReportRecord]) -> str:
    if result.success:
        return "complete"
    codes = {item.code for item in result.warnings}
    if "unsupported_language" in codes or "template_mismatch" in codes:
        return "unsupported"
    if "document_too_large" in codes or "resource_blocked" in codes or "page_limit_applied" in codes or "page_text_limit" in codes or "total_text_limit" in codes:
        return "resource_blocked"
    if any("malformed" in code or "future_" in code for code in codes):
        return "malformed"
    return "incomplete" if result.records else "parse_failed"


def _validate_report_binding(row: pd.Series, registry_path: Path) -> None:
    registry = _read_registry_fail_closed(registry_path)
    if not _row_binding_matches_registry(row, registry):
        raise ValueError("report extraction is not bound to its exact registry identity")


def _row_binding_matches_registry(row: pd.Series, registry: pd.DataFrame) -> bool:
    if registry.empty or "source_id" not in registry.columns:
        return False
    matches = registry.loc[registry["source_id"].astype(str).eq(str(row["source_id"]))]
    if len(matches) != 1:
        return False
    registered = matches.iloc[0]
    for field in ("instrument_id", "document_kind", "source_sha256", "source_authority", "document_date", "known_at"):
        registry_field = {"source_sha256": "sha256", "source_authority": "authority", "known_at": "ingested_at"}.get(field, field)
        registered_value = _registry_known_at(registered) if field == "known_at" else registered.get(registry_field)
        if _cell_text(registered_value) != _cell_text(row.get(field)):
            return False
    return True


def _row_is_verifiable(row: pd.Series) -> bool:
    if str(row.get("extraction_status")) != "complete" or not bool(row.get("parse_success")):
        return False
    try:
        evidence = json.loads(str(row.get("field_evidence") or "[]"))
    except (TypeError, json.JSONDecodeError):
        return False
    required = set(REPORT_FIELDS[:3])
    if str(row.get("document_kind")) in {"annual_report", "half_year_report"}:
        required.add("reporting_period_end")
    by_field = {str(item.get("field_name")): item for item in evidence if isinstance(item, dict)}
    warning_codes = _warning_codes(row.get("warnings"))
    if warning_codes & {"field_conflict", "page_text_limit", "total_text_limit", "page_limit_applied", "required_field_missing", "identity_mismatch"}:
        return False
    legal_structure_ok = any(
        by_field.get(field, {}).get("status") == "extracted" and by_field[field].get("candidate_pages")
        for field in ("legal_structure", "legal_form")
    )
    return legal_structure_ok and all(by_field.get(field, {}).get("status") == "extracted" and by_field[field].get("candidate_pages") for field in required)


def _warning_codes(value: Any) -> set[str]:
    try:
        payload = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return {"malformed_warning_store"}
    return {str(item.get("code")) for item in payload if isinstance(item, dict)} | {str(item) for item in payload if isinstance(item, str)}


def _field_to_dict(item: Any) -> dict[str, Any]:
    return {"field_name": item.field_name, "value": item.value, "source_page": item.source_page, "confidence": item.confidence, "status": item.status, "candidates": list(item.candidates), "matched_label": item.matched_label, "candidate_pages": list(item.candidate_pages), "source_excerpt": item.source_excerpt}


def _field_pages(row: pd.Series, field: str) -> str:
    try:
        evidence = json.loads(str(row.get("field_evidence") or "[]"))
        item: dict[str, Any] = next((candidate for candidate in evidence if isinstance(candidate, dict) and candidate.get("field_name") == field), {})
        return _json(item.get("candidate_pages", []))
    except (TypeError, json.JSONDecodeError):
        return "[]"


def _row_extraction_fingerprint(row: pd.Series, *, columns: tuple[str, ...] | None = None) -> str:
    fingerprint_columns = columns or tuple(REPORT_COLUMNS)
    payload = {column: _jsonable(row.get(column)) for column in fingerprint_columns if column not in _REVIEW_COLUMNS}
    payload.pop("extraction_sha256", None)
    payload.pop("stored_extraction_sha256", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _report_schema_version(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_legacy_report_row(row: pd.Series | dict[str, Any]) -> bool:
    return _report_schema_version(row.get("schema_version")) < REPORT_SCHEMA_VERSION


def _fingerprint_matches(row: pd.Series, fingerprint: str) -> bool:
    if fingerprint == _row_extraction_fingerprint(row):
        return True
    return _is_legacy_report_row(row) and fingerprint == _row_extraction_fingerprint(row, columns=_LEGACY_REPORT_COLUMNS)


def _fingerprint_matches_rows(prior: pd.Series, incoming: dict[str, Any], fingerprint: str) -> bool:
    incoming_series = pd.Series(incoming)
    if fingerprint == _row_extraction_fingerprint(incoming_series):
        return True
    if not _is_legacy_report_row(prior):
        return False
    legacy_incoming = incoming_series.copy()
    legacy_incoming["schema_version"] = prior.get("schema_version")
    return fingerprint == _row_extraction_fingerprint(legacy_incoming, columns=_LEGACY_REPORT_COLUMNS)


def _registry_known_at(row: Any) -> str:
    return _cell_text(row.get("known_at")) or _cell_text(row.get("ingested_at"))


def _backfill_legacy_known_at(frame: pd.DataFrame) -> None:
    for index, row in frame.iterrows():
        if not _is_legacy_report_row(row) or _cell_text(row.get("known_at")):
            continue
        registry_path = _cell_text(row.get("registry_path"))
        if not registry_path:
            continue
        try:
            registry = _read_registry_fail_closed(Path(registry_path))
            matches = registry.loc[registry["source_id"].astype(str).eq(_cell_text(row.get("source_id")))]
            if len(matches) == 1:
                known_at = _registry_known_at(matches.iloc[0])
                if known_at:
                    frame.at[index, "known_at"] = known_at
        except Exception:
            continue


def _jsonable(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def _review_history(
    value: Any,
    *,
    expected_fingerprint: str | None = None,
    row: pd.Series | None = None,
) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("review history is corrupt") from exc
    if not isinstance(parsed, list):
        raise ValueError("review history is corrupt")
    prior: datetime | None = None
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("review history is corrupt")
        timestamp = _review_timestamp(item)
        if prior is not None and timestamp < prior:
            raise ValueError("review history is not ordered")
        prior = timestamp
        if expected_fingerprint is not None and _cell_text(item.get("extraction_sha256")) != expected_fingerprint:
            raise ValueError("review history fingerprint does not match extraction")
    if row is not None:
        if parsed:
            final = parsed[-1]
            if (
                _cell_text(row.get("verification_status")) != _cell_text(final.get("decision"))
                or _cell_text(row.get("verified_by")) != _cell_text(final.get("reviewer"))
                or _cell_text(row.get("verified_at")) != _cell_text(final.get("reviewed_at"))
                or _cell_text(row.get("review_note")) != _cell_text(final.get("note"))
            ):
                raise ValueError("top-level review fields do not match review history")
        elif (
            _cell_text(row.get("verification_status")) not in {"", "pending"}
            or _cell_text(row.get("verified_by"))
            or _cell_text(row.get("verified_at"))
            or _cell_text(row.get("review_note"))
        ):
            raise ValueError("top-level review fields exist without review history")
        decision = _cell_text(row.get("verification_status")) or "pending"
        manual_review = _strict_stored_bool(row.get("manual_review"), "manual_review")
        evidence_eligible = _strict_stored_bool(row.get("evidence_eligible"), "evidence_eligible")
        score_eligible = _strict_stored_bool(row.get("score_eligible"), "score_eligible")
        execution_allowed = _strict_stored_bool(row.get("execution_allowed"), "execution_allowed")
        if manual_review != (decision != "verified"):
            raise ValueError("manual-review authority does not match review status")
        if decision != "verified" and evidence_eligible:
            raise ValueError("unverified report cannot be evidence eligible")
        if evidence_eligible and not _row_is_verifiable(row):
            raise ValueError("incomplete report cannot be evidence eligible")
        if score_eligible or execution_allowed:
            raise ValueError("report authority flags exceed the allowed boundary")
    return parsed


def _strict_stored_bool(value: Any, field: str) -> bool:
    if type(value).__name__ not in {"bool", "bool_"}:
        raise ValueError(f"{field} is not a stored boolean")
    return bool(value)


def _review_timestamp(item: dict[str, Any]) -> datetime:
    try:
        timestamp = datetime.fromisoformat(str(item["reviewed_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("review history timestamp is malformed") from exc
    if timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc):
        raise ValueError("review history timestamp is invalid or in the future")
    return timestamp


def _cell_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_matches(path: Path, expected: bytes, expected_sha256: str) -> bool:
    digest = hashlib.sha256()
    offset = 0
    try:
        with Path(path).open("rb") as handle:
            while offset < len(expected):
                chunk = handle.read(min(1024 * 1024, len(expected) - offset))
                if not chunk or chunk != expected[offset:offset + len(chunk)]:
                    return False
                digest.update(chunk)
                offset += len(chunk)
            if handle.read(1):
                return False
    except OSError:
        return False
    return offset == len(expected) and digest.hexdigest() == expected_sha256


def _validate_snapshot(path: Path, expected: bytes, expected_sha256: str) -> None:
    if not _snapshot_matches(path, expected, expected_sha256):
        raise ValueError("immutable ETF report snapshot validation failed")


def _guard_path(path: Path) -> Path:
    return path.with_name(path.name + ".guard")


__all__ = [
    "ETF_REPORT_CONFLICTS_PATH", "ETF_REPORT_RECORDS_PATH", "EtfReportAuthority", "EtfReportImportRequest", "EtfReportImportResult", "EtfReportReviewRequest",
    "INDEX_METHODOLOGY_RECORDS_PATH", "KID_COLUMNS", "METHODOLOGY_COLUMNS", "PRIIPS_KID_RECORDS_PATH", "REPORT_COLUMNS",
    "REPORT_CONFLICT_COLUMNS", "REPORT_RAW_DIR", "ReportSourceAuthority", "build_etf_report_conflicts", "import_etf_report",
    "persist_index_methodology", "persist_index_methodology_result", "persist_index_methodology_with_document", "persist_priips_kid",
    "persist_priips_kid_result", "persist_priips_kid_with_document", "read_etf_report_conflicts", "read_etf_report_records",
    "read_index_methodology_records", "read_priips_kid_records", "review_etf_report", "review_etf_report_record",
]
