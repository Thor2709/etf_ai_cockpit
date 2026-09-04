"""Process-bound admission proofs for SEC EDGAR raw documents.

``RawDocument`` is intentionally a small, serialisable value object.  It is
therefore not an authority token: callers can construct an identical value
without having contacted EDGAR.  This module keeps the non-serialisable
admission proof in a process-local registry.  Only the acquisition adapters
in this package mint proofs; replay mints a new proof for the new value
object, so sidecars and manifests cannot be rehydrated into authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections import OrderedDict
from pathlib import Path
import secrets
import threading
import weakref
from typing import Final

from etf_cockpit.parsers.contracts import RawDocument


_SEAL: Final[bytes] = secrets.token_bytes(32)
_LOCK = threading.RLock()
_ADMISSIONS: dict[int, tuple[weakref.ReferenceType[RawDocument], "_Admission"]] = {}
_MAX_CACHE_ADMISSIONS: Final[int] = 1024
_CACHE_ADMISSIONS: OrderedDict[tuple[str, str, str, str, str, str, str], "_Admission"] = OrderedDict()


@dataclass(frozen=True)
class _Admission:
    seal: bytes
    source_url: str
    sha256: str
    document_type: str
    media_type: str
    retrieved_at: datetime
    response_status: int
    acquisition_status: int
    lineage: tuple[int, ...]


def _mint(
    document: RawDocument,
    *,
    acquisition_status: int | None = None,
    lineage: tuple[int, ...] = (),
) -> RawDocument:
    """Register an adapter-created document and return the same value object."""

    if not isinstance(document, RawDocument):
        raise TypeError("SEC admission requires a RawDocument")
    if type(document.http_status) is not int or document.http_status not in {200, 206, 304}:
        raise ValueError("SEC admission status is invalid")
    acquired = document.http_status if acquisition_status is None else acquisition_status
    if type(acquired) is not int or acquired not in {200, 206}:
        raise ValueError("SEC acquisition status is invalid")
    if not isinstance(document.retrieved_at, datetime) or document.retrieved_at.tzinfo is None or document.retrieved_at.utcoffset() is None:
        raise ValueError("SEC admission timestamp must be timezone-aware")
    statuses = tuple(lineage) or (acquired,)
    if any(type(status) is not int or status not in {200, 206, 304} for status in statuses):
        raise ValueError("SEC admission lineage is invalid")
    if statuses[-1] != document.http_status:
        statuses = statuses + (document.http_status,)
    admission = _Admission(
        _SEAL,
        document.source_url,
        document.sha256,
        document.document_type,
        document.media_type,
        document.retrieved_at,
        document.http_status,
        acquired,
        statuses,
    )
    key = id(document)

    def _discard(reference: weakref.ReferenceType[RawDocument], *, key: int = key) -> None:
        with _LOCK:
            current = _ADMISSIONS.get(key)
            if current is not None and current[0] is reference:
                _ADMISSIONS.pop(key, None)

    with _LOCK:
        _ADMISSIONS[key] = (weakref.ref(document, _discard), admission)
        cache_key = _cache_key(document)
        _CACHE_ADMISSIONS[cache_key] = admission
        _CACHE_ADMISSIONS.move_to_end(cache_key)
        while len(_CACHE_ADMISSIONS) > _MAX_CACHE_ADMISSIONS:
            _CACHE_ADMISSIONS.popitem(last=False)
    return document


def _derive(parent: RawDocument, document: RawDocument) -> RawDocument:
    """Admit a ZIP member only when its parent has an adapter proof."""

    parent_admission = _get(parent)
    if parent_admission is None:
        return document
    return _mint(
        document,
        acquisition_status=parent_admission.acquisition_status,
        lineage=parent_admission.lineage,
    )


def _get(document: RawDocument) -> _Admission | None:
    """Return an admission only for the exact in-process object that was minted."""

    if not isinstance(document, RawDocument):
        return None
    with _LOCK:
        current = _ADMISSIONS.get(id(document))
        if current is None or current[0]() is not document:
            return None
        admission = current[1]
    if admission.seal is not _SEAL:
        return None
    if (
        admission.source_url != document.source_url
        or admission.sha256 != document.sha256
        or admission.document_type != document.document_type
        or admission.media_type != document.media_type
        or admission.retrieved_at != document.retrieved_at
        or admission.response_status != document.http_status
    ):
        return None
    return admission


def _admitted(document: RawDocument, *, digest: str, document_type: str) -> bool:
    admission = _get(document)
    return admission is not None and document.sha256 == digest and document.document_type == document_type


def _replay(document: RawDocument, *, status: int | None = None) -> RawDocument:
    """Mint a fresh proof for a cache replay already admitted in this process."""

    with _LOCK:
        prior = _CACHE_ADMISSIONS.get(_cache_key(document))
    if prior is None or prior.seal is not _SEAL:
        raise ValueError("SEC cached artifact has no process-bound acquisition proof")
    response_status = document.http_status if status is None else status
    if response_status not in {200, 206, 304}:
        raise ValueError("SEC replay status is invalid")
    if response_status != 304 and document.http_status != prior.response_status:
        raise ValueError("SEC cached artifact status does not match its acquisition proof")
    replayed = RawDocument(
        document.path,
        document.source_url,
        document.retrieved_at,
        document.sha256,
        document.provider_id,
        document.document_type,
        document.media_type,
        response_status,
    )
    return _mint(
        replayed,
        acquisition_status=prior.acquisition_status,
        lineage=prior.lineage + ((response_status,) if response_status == 304 else ()),
    )


def _cache_key(document: RawDocument) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(Path(document.path).absolute()),
        document.source_url,
        document.sha256,
        document.document_type,
        document.media_type,
        document.provider_id,
        document.retrieved_at.isoformat(),
    )
