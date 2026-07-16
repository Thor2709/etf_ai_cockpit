"""Atomic persistence for parsed PRIIPs KID and methodology evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import CLEAN_DIR
from etf_cockpit.data.fund_documents import (
    FUND_DOCUMENTS_PATH,
    build_document_inventory,
    read_document_registry,
    register_document,
    unavailable_document,
)
from etf_cockpit.parsers.contracts import ParseResult
from etf_cockpit.parsers.index_methodology import IndexMethodologyRecord, apply_methodology_holdings_assessment
from etf_cockpit.parsers.priips_kid import PriipsKidRecord


PRIIPS_KID_RECORDS_PATH = CLEAN_DIR / "priips_kid_records.parquet"
INDEX_METHODOLOGY_RECORDS_PATH = CLEAN_DIR / "index_methodology_records.parquet"

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
    existing = _read_frame(destination, columns)
    incoming = pd.DataFrame(rows, columns=columns)
    combined = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["source_id"], keep="last").sort_values("source_id", kind="stable").reset_index(drop=True)

    registry_existing = _read_registry_fail_closed(registry_destination)
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
        pd.read_parquet(candidate)
    except Exception as exc:
        raise ValueError(f"Fund document registry is corrupt: {candidate}") from exc
    return read_document_registry(path=candidate)


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
