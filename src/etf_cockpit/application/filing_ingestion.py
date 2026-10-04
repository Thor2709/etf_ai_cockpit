"""SEC/ESEF/OAM filing-ingestion helpers: raw-document capture and validation, SEC bulk identity, provenance (application; ADR-0002)."""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import hashlib
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse

from etf_cockpit.core.atomic_io import (
    atomic_write_bytes,
    sha256_file,
)
from etf_cockpit.core.paths import (
    CLEAN_DIR,
    RAW_DIR,
)
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.workflow import (
    PublicationScopeFactory,
    publication_scope,
)
from etf_cockpit.application.sec_bulk_import import BulkImportResult
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.data.sec_edgar_bulk import SecEdgarBulkUnavailable
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import (
    RawDocument,
    load_fixture_manifest,
)


MAX_LOCAL_ESEF_BYTES = 300 * 1024 * 1024


def _preserve_esef_raw(
    package_path: Path,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> tuple[Path, str]:
    if not package_path.is_file():
        raise FileNotFoundError(f"ESEF package is not a readable file: {package_path}")
    if package_path.stat().st_size > MAX_LOCAL_ESEF_BYTES:
        raise ValueError("ESEF local package exceeds the size limit")
    source_sha256 = sha256_file(package_path)
    raw_path = RAW_DIR / "filings" / "eu_esef" / f"{source_sha256}.xbri"
    payload = package_path.read_bytes()
    if raw_path.exists():
        _validate_esef_raw_checksum(raw_path, source_sha256)
    else:
        with publication_scope(publish_guard):
            atomic_write_bytes(raw_path, payload, lambda candidate: _validate_esef_raw_checksum(candidate, source_sha256))
    return raw_path, source_sha256


def _esef_source_provenance(package_path: Path) -> tuple[str, str]:
    resolved = package_path.resolve()
    immutable_root = (RAW_DIR / "esef" / "immutable").resolve()
    if resolved == immutable_root or immutable_root in resolved.parents:
        return "filings_xbrl_org", "https://filings.xbrl.org"
    try:
        for fixture in load_fixture_manifest():
            if fixture.document_type == "esef_report_package" and fixture.path.resolve() == resolved:
                return "filings_xbrl_org", fixture.source_url
    except (OSError, ValueError):
        pass
    return "esef_local_import", resolved.as_uri()


def _validate_esef_raw_checksum(path: Path, expected: str) -> None:
    if sha256_file(path) != expected:
        raise ValueError("ESEF raw filing checksum mismatch")


def _resolve_sec_instrument(cik: str) -> str | None:
    """Resolve a unique persisted CIK mapping before falling back to review."""

    try:
        import pandas as pd

        frame = pd.read_parquet(IDENTITY_PATH)
        if "cik" not in frame.columns or "instrument_id" not in frame.columns:
            return None
        values = frame["cik"].map(lambda value: str(value).strip().upper().removeprefix("CIK").zfill(10))
        matches = sorted({str(value) for value in frame.loc[values == cik, "instrument_id"] if str(value).strip()})
        return matches[0] if len(matches) == 1 else None
    except (OSError, ValueError, TypeError, ImportError):
        return None


def _normalise_sec_cik(value: object) -> str | None:
    text = str(value or "").strip().upper().removeprefix("CIK")
    if re.fullmatch(r"[0-9]{1,10}", text) is None or int(text) <= 0:
        return None
    return text.zfill(10)


def _persisted_sec_instruments(cik: str, instrument_id: str | None = None) -> tuple[str, ...] | None:
    """Validate relevant registry rows in both directions; absence is not corruption."""

    try:
        if not IDENTITY_PATH.exists():
            return ()
        import pandas as pd

        frame = pd.read_parquet(IDENTITY_PATH)
        if "cik" not in frame.columns or "instrument_id" not in frame.columns:
            return None
        bindings: list[tuple[str | None, str | None, bool]] = []
        for raw_cik, raw_id in frame[["cik", "instrument_id"]].itertuples(index=False, name=None):
            row_cik = _normalise_sec_cik(raw_cik) if isinstance(raw_cik, (str, int)) and not isinstance(raw_cik, bool) else None
            row_id = raw_id.strip() if isinstance(raw_id, str) else None
            canonical_id = isinstance(raw_id, str) and bool(row_id) and raw_id == row_id
            bindings.append((row_cik, row_id, canonical_id))
        if any(row_cik == cik and not canonical_id for row_cik, _, canonical_id in bindings):
            return None
        forward = {row_id for row_cik, row_id, _ in bindings if row_cik == cik and row_id is not None}
        relevant_ids = forward | ({instrument_id} if instrument_id else set())
        if any(row_id in relevant_ids and (row_cik != cik or not canonical_id) for row_cik, row_id, canonical_id in bindings):
            return None
        return tuple(sorted(forward))
    except (OSError, ValueError, TypeError, ImportError):
        return None


def _validate_sec_bulk_identity(identity: CanonicalIdentity) -> str:
    """Validate supplied bulk identity against the registry when one exists."""

    if not isinstance(identity, CanonicalIdentity):
        raise ValueError("SEC bulk import requires a CanonicalIdentity")
    cik = _normalise_sec_cik(identity.cik)
    if cik is None:
        raise ValueError("SEC bulk identity CIK is invalid")
    instrument_id = identity.instrument_id
    if not isinstance(instrument_id, str) or not instrument_id or instrument_id != instrument_id.strip():
        raise ValueError("SEC bulk identity instrument_id must be a non-empty canonical string")
    persisted = _persisted_sec_instruments(cik, instrument_id)
    if persisted is None:
        raise ValueError("SEC bulk identity registry is unavailable or malformed")
    if len(persisted) > 1:
        raise ValueError(f"SEC bulk identity mapping is ambiguous for CIK {cik}")
    if persisted and persisted[0] != instrument_id:
        raise ValueError(f"SEC bulk identity conflicts with persisted CIK mapping for {cik}")
    return cik


def _build_sec_bulk_identity(cik: str, instrument_id: str | None, *, allow_manual: bool = False) -> CanonicalIdentity | None:
    if instrument_id is not None and (not isinstance(instrument_id, str) or not instrument_id or instrument_id != instrument_id.strip()):
        return None
    requested = instrument_id or ""
    persisted = _persisted_sec_instruments(cik, requested or None)
    if allow_manual and persisted == () and requested:
        persisted = (requested,)
    if persisted is None or len(persisted) != 1:
        return None
    resolved = requested or persisted[0]
    if resolved != persisted[0]:
        return None
    return CanonicalIdentity(
        resolved,
        "Imported SEC entity",
        None,
        "needs_verification",
        "",
        None,
        None,
        "stock",
        {},
        "manual_review",
        (),
        cik,
    )


def _sec_bulk_identity_reason(cik: str, instrument_id: str | None) -> str:
    requested = str(instrument_id or "").strip()
    persisted = _persisted_sec_instruments(cik, requested or None)
    if persisted is None:
        return "SEC bulk identity registry is unavailable or malformed"
    if len(persisted) > 1:
        return f"SEC bulk identity mapping is ambiguous for CIK {cik}"
    if requested and persisted and persisted[0] != requested:
        return f"SEC bulk identity conflicts with persisted CIK mapping for {cik}"
    return "no unique persisted CIK-to-instrument identity"


def _cached_sec_bulk_document(cache_dir: Path, provider: SecEdgarProvider | None = None) -> tuple[RawDocument | None, str]:
    try:
        if provider is None or Path(provider.cache_dir).resolve() != Path(cache_dir).resolve():
            return None, "validated SEC bulk cache unavailable (no same-session acquisition proof)"
        document = provider.fetch_companyfacts_bulk(cache_only=True)
        age_seconds = int((datetime.now(timezone.utc) - document.retrieved_at).total_seconds())
        return document, f"retrieved_at={document.retrieved_at.isoformat()}; cache age {age_seconds}s; freshness unverified"
    except (OSError, ValueError, TypeError, SecEdgarBulkUnavailable) as exc:
        return None, f"validated SEC bulk cache unavailable ({type(exc).__name__})"


def _bulk_result_message(result: BulkImportResult, prefix: str, *, context: str = "") -> str:
    statuses: list[str] = []
    for item in result.per_cik[:5]:
        detail = redact_text(" ".join(str(item.detail or "").split()))[:240]
        displayed: list[str] = []
        for warning in item.warnings[:20]:
            code = redact_text(str(warning.get("code") or warning.get("message") or "warning"))[:80]
            if code not in displayed and len(displayed) < 5:
                displayed.append(code)
        warning_codes = ",".join(displayed)
        parts = [f"{item.cik}:{item.status}"]
        if item.coverage_status != "complete":
            parts.append(f"coverage={item.coverage_status}")
        if warning_codes:
            parts.append(f"warnings={warning_codes}")
        omitted = len(item.warnings) - len(displayed)
        if omitted:
            parts.append(f"{omitted} warning entries omitted")
        if detail:
            parts.append(detail)
        statuses.append(" ".join(parts))
    status_text = ", ".join(statuses) or "none"
    if len(result.per_cik) > 5:
        status_text += f"; {len(result.per_cik) - 5} CIK results omitted"
    message = f"{prefix} {result.overall_status}: {status_text}"
    if context:
        message += f"; {context}"
    suffix = "; execution_allowed=false."
    message = redact_text(message)
    limit = 2048 - len(suffix)
    if len(message) > limit:
        message = message[:limit - 23] + " ... [output truncated]"
    return message + suffix


def _sec_failure_state(statement_import_started: bool) -> str:
    if statement_import_started:
        return "Statement import completion unconfirmed; inspect stored evidence. Raw cache/partials or checkpoints may have changed."
    return "Canonical statement stores unchanged; raw cache/partials may have changed."


def _sec_failure_detail(exc: BaseException) -> str:
    """Expose bounded SEC transport/quota context without echoing raw errors."""

    current: BaseException | None = exc
    seen: set[int] = set()
    details: list[str] = []
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        match = re.search(r"\bHTTP(?:\s+Error)?\s+(\d{3})\b", str(current)[:512], flags=re.IGNORECASE)
        status = str(current.code) if isinstance(current, HTTPError) else match.group(1) if match else None
        if status is not None:
            if status == "429":
                return "SEC endpoint returned HTTP 429 (rate limit/quota)"
            return f"SEC endpoint returned HTTP {status}"
        safe_message = redact_text(" ".join(str(current).split()))[:160]
        detail = f"{type(current).__name__}: {safe_message}" if safe_message else type(current).__name__
        if detail not in details and len(details) < 3:
            details.append(detail)
        current = current.__cause__ or current.__context__
    return "; caused by ".join(details)[:512]


def _capture_sec_raw_document(
    source_path: Path,
    content: bytes,
    source_sha256: str,
    *,
    document: RawDocument,
    publish_guard: PublicationScopeFactory | None = None,
) -> Path:
    """Bind parsing/publication to a durable content-addressed local copy.

    Even provider generations with content-addressed names may be mutable at
    the filesystem level, so retain a validated sibling snapshot before
    parsing every supplied document. The original path remains available for
    provenance validation and legacy callers.
    """

    stem, suffix = source_path.stem, source_path.suffix
    capture_parts = stem.split(".")
    already_captured = (
        len(capture_parts) >= 3
        and capture_parts[-1] == "immutable"
        and len(capture_parts[-2]) == 64
        and capture_parts[-2].casefold() == source_sha256
    )
    if already_captured:
        return source_path
    captured_path = source_path.with_name(f"{stem}.{source_sha256}.immutable{suffix}")
    if captured_path.is_symlink():
        raise ValueError("SEC captured raw document path must not be a symlink")
    if captured_path.is_file():
        if hashlib.sha256(captured_path.read_bytes()).hexdigest() != source_sha256:
            raise ValueError("SEC captured raw document checksum mismatch")
        return captured_path
    if captured_path.exists():
        raise ValueError("SEC captured raw document target is not a regular file")
    with publication_scope(publish_guard):
        atomic_write_bytes(
            captured_path,
            content,
            lambda candidate: _validate_captured_sec_raw(candidate, source_sha256),
        )
    return captured_path


def _validate_captured_sec_raw(path: Path, expected_sha256: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("SEC captured raw document checksum mismatch")


def _validate_sec_raw_document(
    document: RawDocument,
    path: Path,
    expected_cik: str | None = None,
    parsed_sha256: str | None = None,
    *,
    content: bytes | None = None,
) -> None:
    """Fail closed when fetched SEC provenance is not bound to the parsed file."""

    if not isinstance(document, RawDocument):
        raise ValueError("SEC source evidence must be a RawDocument")
    if not isinstance(document.path, Path):
        raise ValueError("SEC source evidence path must be a Path")
    source_path = Path(path)
    if document.path.resolve() != source_path.resolve():
        raise ValueError("SEC source evidence path does not match the parsed file")
    if document.path.is_symlink() or not document.path.is_file():
        raise ValueError("SEC source evidence file is missing or not immutable")
    if document.provider_id != "sec_edgar" or document.document_type != "sec_companyfacts":
        raise ValueError("SEC source evidence provider or document type is invalid")
    if document.media_type != "application/json" or type(document.http_status) is not int or document.http_status not in {200, 304}:
        raise ValueError("SEC source evidence media type or HTTP status is invalid")
    retrieved_at = document.retrieved_at
    if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("SEC source evidence retrieved_at must be timezone-aware")
    source_url = urlparse(document.source_url) if isinstance(document.source_url, str) else None
    if (
        source_url is None
        or source_url.scheme != "https"
        or source_url.hostname != "data.sec.gov"
        or source_url.username is not None
        or source_url.password is not None
        or source_url.port is not None
        or source_url.query
        or source_url.fragment
        or not source_url.path.startswith("/api/xbrl/companyfacts/CIK")
    ):
        raise ValueError("SEC source evidence URL is invalid")
    if not isinstance(document.sha256, str) or len(document.sha256) != 64 or document.sha256 != document.sha256.lower() or any(character not in "0123456789abcdef" for character in document.sha256):
        raise ValueError("SEC source evidence checksum is invalid")
    actual_sha256 = hashlib.sha256(content).hexdigest() if content is not None else sha256_file(document.path)
    if actual_sha256 != document.sha256:
        raise ValueError("SEC source evidence checksum does not match the file")
    if parsed_sha256 is not None and parsed_sha256 != actual_sha256:
        raise ValueError("SEC parsed source checksum does not match the fetched document")
    if expected_cik is not None:
        expected_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{expected_cik}.json"
        if document.source_url != expected_url:
            raise ValueError("SEC source evidence URL does not match the fetched CIK")


def _sec_identity_matches(cik: str, instrument_id: str) -> bool:
    """Accept an explicit instrument only when the persisted CIK mapping is unique."""

    try:
        import pandas as pd

        frame = pd.read_parquet(IDENTITY_PATH)
        if "cik" not in frame.columns or "instrument_id" not in frame.columns:
            return False
        values = frame["cik"].map(lambda value: str(value).strip().upper().removeprefix("CIK").zfill(10))
        candidates = sorted({str(value).strip() for value in frame.loc[values == cik, "instrument_id"] if str(value).strip()})
        return len(candidates) == 1 and candidates[0] == instrument_id
    except (OSError, ValueError, TypeError, ImportError):
        return False


def _load_vendor_statement_claims(instrument_id: str) -> tuple[dict[str, object], ...]:
    """Load optional vendor statement claims for exact-match authority checks."""

    try:
        import pandas as pd

        path = CLEAN_DIR / "fundamentals.parquet"
        if not path.exists():
            return ()
        frame = pd.read_parquet(path)
        if "instrument_id" in frame.columns:
            frame = frame[frame["instrument_id"].astype(str) == instrument_id]
        concept_columns = {"concept", "canonical_metric"} & set(frame.columns)
        period_columns = {"period", "end", "instant", "as_of_date"} & set(frame.columns)
        if not concept_columns or "unit" not in frame.columns or not period_columns:
            return ()
        return tuple(frame.to_dict(orient="records"))
    except (OSError, ValueError, TypeError, ImportError):
        return ()
