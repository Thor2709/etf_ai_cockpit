from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


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


def register_document(path: Path, document_type: str, instrument_id: str, source_url: str, authority: str, *, document_date: str | None = None) -> FundDocument:
    if not path.exists() or not path.is_file():
        raise ValueError(f"Document is missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return FundDocument(instrument_id, document_type, str(path), source_url, authority, digest, document_date, "available", ())


def unavailable_document(instrument_id: str, document_type: str, reason: str) -> FundDocument:
    return FundDocument(instrument_id, document_type, "", "", "unknown", None, None, "unavailable", (reason,))
