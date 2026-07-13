from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import CLEAN_DIR


FUND_DOCUMENTS_PATH = CLEAN_DIR / "fund_documents.parquet"
DOCUMENT_TYPES = ("factsheet", "kid", "prospectus_report", "holdings", "methodology")
_DOCUMENT_TYPE_ALIASES = {
    "factsheet": "factsheet",
    "kid": "kid",
    "priips_kid": "kid",
    "prospectus_report": "prospectus_report",
    "prospectus_or_report": "prospectus_report",
    "prospectus": "prospectus_report",
    "report": "prospectus_report",
    "holdings": "holdings",
    "methodology": "methodology",
    "index_methodology": "methodology",
}


@dataclass(frozen=True)
class FundDocument:
    instrument_id: str
    document_type: str
    path: str
    source_url: str
    authority: str
    sha256: str | None
    document_date: str | None
    coverage_status: str
    warnings: tuple[str, ...]
    source_id: str = ""
    schema_version: int = 1
    ingested_at: str | None = None


def canonical_document_type(document_type: str) -> str:
    value = str(document_type or "").strip().lower().replace(" ", "_").replace("/", "_")
    try:
        return _DOCUMENT_TYPE_ALIASES[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported document_type: {document_type}") from exc


def _normalise_date(document_date: str | date | datetime | None) -> str | None:
    if document_date is None or (isinstance(document_date, str) and not document_date.strip()):
        return None
    if isinstance(document_date, datetime):
        normalised = document_date.astimezone(timezone.utc).date() if document_date.tzinfo else document_date.date()
    elif isinstance(document_date, date):
        normalised = document_date
    else:
        value = str(document_date).strip()
        try:
            normalised = date.fromisoformat(value)
        except ValueError:
            try:
                normalised = datetime.fromisoformat(value).date()
            except ValueError as exc:
                raise ValueError(f"Invalid document_date: {document_date}") from exc
    if normalised > datetime.now(timezone.utc).date():
        raise ValueError(f"future document_date is not allowed: {normalised.isoformat()}")
    return normalised.isoformat()


def _document_source_id(instrument_id: str, document_type: str, checksum: str | None, document_date: str | None) -> str:
    payload = "|".join((instrument_id, document_type, checksum or "missing", document_date or "undated"))
    return "funddoc:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def register_document(
    path: Path,
    document_type: str,
    instrument_id: str,
    source_url: str,
    authority: str,
    *,
    document_date: str | date | datetime | None = None,
    expected_sha256: str | None = None,
) -> FundDocument:
    """Register one readable local disclosure with immutable checksum provenance."""
    resolved_type = canonical_document_type(document_type)
    instrument = str(instrument_id or "").strip()
    if not instrument:
        raise ValueError("instrument_id is required")
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"Document is missing: {candidate}")
    checksum = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if expected_sha256 is not None and checksum.lower() != str(expected_sha256).strip().lower():
        raise ValueError("Document checksum does not match expected_sha256")
    normalised_date = _normalise_date(document_date)
    source_id = _document_source_id(instrument, resolved_type, checksum, normalised_date)
    return FundDocument(
        instrument,
        resolved_type,
        str(candidate),
        str(source_url or "").strip(),
        str(authority or "unknown").strip() or "unknown",
        checksum,
        normalised_date,
        "available",
        (),
        source_id,
        1,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def unavailable_document(instrument_id: str, document_type: str, reason: str) -> FundDocument:
    resolved_type = canonical_document_type(document_type)
    instrument = str(instrument_id or "").strip()
    source_id = _document_source_id(instrument, resolved_type, None, None)
    return FundDocument(
        instrument,
        resolved_type,
        "",
        "",
        "unknown",
        None,
        None,
        "unavailable",
        (str(reason),),
        source_id,
        1,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _as_document(value: FundDocument | dict[str, object]) -> FundDocument:
    if isinstance(value, FundDocument):
        return value
    payload = dict(value)
    if "sha256" not in payload and payload.get("checksum"):
        payload["sha256"] = payload["checksum"]
    payload.pop("checksum", None)
    payload["document_type"] = canonical_document_type(str(payload.get("document_type", "")))
    payload.setdefault("warnings", ())
    payload.setdefault("schema_version", 1)
    payload.setdefault("source_id", _document_source_id(str(payload.get("instrument_id", "")), str(payload["document_type"]), payload.get("sha256") if isinstance(payload.get("sha256"), str) else None, payload.get("document_date") if isinstance(payload.get("document_date"), str) else None))
    return FundDocument(**payload)


def build_document_inventory(
    instrument_ids: Iterable[str],
    documents: Iterable[FundDocument | dict[str, object]] = (),
) -> pd.DataFrame:
    """Return one explicit row per configured ETF/document type, plus real versions."""
    ids = list(dict.fromkeys(str(item).strip() for item in instrument_ids if str(item).strip()))
    unique: dict[str, FundDocument] = {}
    for raw in documents:
        document = _as_document(raw)
        if document.instrument_id not in ids or not document.source_id:
            continue
        unique.setdefault(document.source_id, document)
    rows: list[FundDocument] = []
    for instrument_id in ids:
        for document_type in DOCUMENT_TYPES:
            matches = [document for document in unique.values() if document.instrument_id == instrument_id and document.document_type == document_type and document.coverage_status in {"available", "imported", "mapped"}]
            if matches:
                rows.extend(sorted(matches, key=lambda item: (item.document_date or "", item.source_id), reverse=True))
            else:
                rows.append(replace(unavailable_document(instrument_id, document_type, "document_not_available"), coverage_status="missing"))
    frame = pd.DataFrame([asdict(item) for item in rows])
    if frame.empty:
        return pd.DataFrame(columns=_DOCUMENT_COLUMNS)
    frame["warnings"] = frame["warnings"].map(lambda value: list(value) if isinstance(value, tuple) else value)
    frame["checksum"] = frame["sha256"]
    return frame[_DOCUMENT_COLUMNS]


_DOCUMENT_COLUMNS = [
    "schema_version",
    "source_id",
    "instrument_id",
    "document_type",
    "path",
    "source_url",
    "authority",
    "sha256",
    "checksum",
    "document_date",
    "coverage_status",
    "warnings",
    "ingested_at",
]


def _registry_frame(documents: Iterable[FundDocument | dict[str, object]] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(documents, pd.DataFrame):
        frame = documents.copy()
    else:
        values = [_as_document(item) for item in documents]
        frame = pd.DataFrame([asdict(item) for item in values])
    if frame.empty:
        return pd.DataFrame(columns=_DOCUMENT_COLUMNS)
    if "checksum" not in frame.columns:
        frame["checksum"] = frame.get("sha256", "")
    else:
        frame["checksum"] = frame["checksum"].where(frame["checksum"].notna() & frame["checksum"].astype(str).ne(""), frame.get("sha256", ""))
    source_ids: list[str] = []
    for _, row in frame.iterrows():
        existing = row.get("source_id")
        if existing is not None and not pd.isna(existing) and str(existing).strip():
            source_ids.append(str(existing).strip())
            continue
        checksum = row.get("sha256") if isinstance(row.get("sha256"), str) else row.get("checksum") if isinstance(row.get("checksum"), str) else None
        document_date = row.get("document_date") if isinstance(row.get("document_date"), str) else None
        source_ids.append(_document_source_id(str(row.get("instrument_id", "")), canonical_document_type(str(row.get("document_type", ""))), checksum, document_date))
    frame["source_id"] = source_ids
    frame["schema_version"] = 1
    for column in _DOCUMENT_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame[_DOCUMENT_COLUMNS].drop_duplicates(subset=["source_id"], keep="last").reset_index(drop=True)


def write_document_registry(
    documents: Iterable[FundDocument | dict[str, object]] | pd.DataFrame,
    *,
    destination: Path = FUND_DOCUMENTS_PATH,
) -> Path:
    """Persist the registry and CSV mirror in one atomic transaction."""
    frame = _registry_frame(documents)
    destination = Path(destination)
    csv_destination = destination.with_suffix(".csv")
    requests = (
        AtomicWriteRequest(destination, parquet_payload(frame), validate_parquet_file),
        AtomicWriteRequest(csv_destination, frame.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path)),
    )
    atomic_write_group(requests)
    return destination


def import_etf_document(
    path: Path,
    *,
    instrument_id: str,
    document_type: str,
    source_url: str = "",
    authority: str = "issuer_document",
    document_date: str | date | datetime | None = None,
    expected_sha256: str | None = None,
    destination: Path | None = None,
    configured_instrument_ids: Iterable[str] | None = None,
) -> FundDocument:
    """Register one local ETF disclosure and persist a complete inventory.

    The existing registry is read first so importing a new version retains all
    prior source-linked documents. Inventory generation supplies explicit
    missing rows for configured instruments and document types.
    """
    destination = Path(destination or FUND_DOCUMENTS_PATH)
    document = register_document(
        Path(path),
        document_type,
        instrument_id,
        source_url,
        authority,
        document_date=document_date,
        expected_sha256=expected_sha256,
    )
    existing = read_document_registry(path=destination)
    ids = list(configured_instrument_ids or ())
    if not ids and not existing.empty and "instrument_id" in existing.columns:
        ids.extend(existing["instrument_id"].dropna().astype(str).tolist())
    ids.append(str(instrument_id))
    inventory = build_document_inventory(ids, [*existing.to_dict("records"), document])
    write_document_registry(inventory, destination=destination)
    return document


def read_document_registry(*, path: Path = FUND_DOCUMENTS_PATH) -> pd.DataFrame:
    """Read the canonical registry without inventing rows when it is absent.

    Consumers that need configured-instrument completeness should add explicit
    missing rows through :func:`build_document_inventory`; an absent registry
    is intentionally represented by an empty frame for compatibility with the
    pre-registry local document scan.
    """
    destination = Path(path)
    if not destination.exists() or not destination.is_file():
        return pd.DataFrame(columns=_DOCUMENT_COLUMNS)
    try:
        frame = pd.read_parquet(destination)
    except Exception:
        return pd.DataFrame(columns=_DOCUMENT_COLUMNS)
    return _registry_frame(frame)


# Compatibility aliases for provider/import callers.
document_inventory = build_document_inventory
persist_document_registry = write_document_registry
