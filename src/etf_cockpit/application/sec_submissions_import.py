"""Explicit local SEC submissions/history and raw-filing retention."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile
from urllib.parse import urlparse

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.workflow import PublicationScopeFactory, WorkflowTransitionError, publication_scope
from etf_cockpit.data.bulk_cache import ContentAddressedCache
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import ParseWarning, RawDocument
from etf_cockpit.parsers.sec_submissions import SubmissionRecord, parse_submissions


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
MAX_SOURCE_BYTES = 8 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 1_000_000
MANIFEST_SCHEMA = "sec_submissions_import.v1"


@dataclass(frozen=True)
class SubmissionsImportResult:
    status: str
    cik: str
    instrument_id: str
    records: tuple[SubmissionRecord, ...] = ()
    warnings: tuple[dict[str, object], ...] = ()
    raw_documents: tuple[RawDocument, ...] = ()
    manifest_path: Path | None = None
    detail: str = ""
    execution_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cik": self.cik,
            "instrument_id": self.instrument_id,
            "records": [asdict(record) for record in self.records],
            "warnings": list(self.warnings),
            "raw_documents": [asdict(document) for document in self.raw_documents],
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "detail": self.detail,
            "execution_allowed": False,
        }


def import_sec_submissions(
    source: Path,
    identity: CanonicalIdentity,
    *,
    cache_dir: Path,
    history_paths: Mapping[str, Path] | None = None,
    filing_documents: Mapping[str, Path | RawDocument] | None = None,
    provenance: RawDocument | None = None,
    history_provenance: Mapping[str, RawDocument] | None = None,
    identity_registry: Path | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> SubmissionsImportResult:
    """Parse selected submissions data and retain every supplied raw input.

    This function performs no acquisition and never creates financial facts.
    A ZIP is inspected and only the selected CIK member plus advertised history
    members are read; filing documents must be supplied explicitly by accession.
    """

    selection, selection_error = _selection(identity, identity_registry)
    if selection_error or selection is None:
        return _failed(selection_error or "invalid submissions identity", identity)
    cik, instrument_id = selection
    source_path = Path(source)
    try:
        _validate_input_path(source_path)
        source_sha = _sha256_file(source_path)
        is_zip = zipfile.is_zipfile(source_path)
        source_meta = _validated_provenance(provenance, source_path, source_sha, cik, is_zip)
        with tempfile.TemporaryDirectory(prefix="sec-submissions-import-") as temp_name:
            parse_path, history_for_parser, member_inputs = _prepare_parse_inputs(
                source_path, cik, Path(temp_name), history_paths, provenance
            )
            parsed = parse_submissions(parse_path, CanonicalIdentity(
                instrument_id, "Imported SEC entity", None, "needs_verification", "", None,
                None, "stock", {}, "manual_review", (), cik,
            ), history_paths=history_for_parser)
            warnings = _warning_payload(parsed.warnings)
            if not parsed.success or not parsed.records:
                return _failed(
                    "submissions parse failed: " + ", ".join(str(item["code"]) for item in warnings) if warnings else "submissions parse returned no records",
                    identity,
                    warnings=warnings,
                )
            filing_inputs = _validate_filing_inputs(filing_documents, parsed.records)
            warnings = tuple(list(warnings) + list(filing_inputs[1]))
            raw_inputs = [("snapshot", source_path, source_meta)]
            raw_inputs.extend(member_inputs)
            known_history = {role.removeprefix("history:") for role, _, _ in member_inputs if role.startswith("history:")}
            for name, history_path in history_for_parser.items():
                if not history_path.is_file():
                    continue
                if name not in known_history:
                    history_source = (history_provenance or {}).get(name)
                    history_digest = _sha256_file(history_path)
                    history_meta = _validated_aux_provenance(history_source, history_path, history_digest)
                    raw_inputs.append((f"history:{name}", history_path, history_meta))
            raw_inputs.extend(filing_inputs[0])
            retained, raw_docs = _retain_inputs(
                raw_inputs, cache_dir=Path(cache_dir), publish_guard=publish_guard
            )
            manifest_path = Path(cache_dir).resolve() / "sec_submissions_import" / "records" / f"CIK{cik}.json"
            snapshot = {
                "source_sha256": source_sha,
                "source_document": retained["snapshot"],
                "snapshot_member": retained.get("snapshot-member"),
                "history_documents": {key.removeprefix("history:"): value for key, value in retained.items() if key.startswith("history:")},
                "filing_documents": {key.removeprefix("filing:"): value for key, value in retained.items() if key.startswith("filing:")},
                "records": [_json_safe(asdict(record)) for record in parsed.records],
                "warnings": list(warnings),
                "coverage_status": "partial" if warnings else "complete",
                "parser_name": parsed.parser_name,
                "parser_version": parsed.parser_version,
                "identity": {"cik": cik, "instrument_id": instrument_id},
                "provenance": _json_safe(asdict(source_meta)),
            }
            manifest = _publish_manifest(
                manifest_path, snapshot, cache_dir=Path(cache_dir), publish_guard=publish_guard
            )
            status = "partial" if warnings else "complete"
            detail = "verified restart or new source retained" if manifest == "verified" else "raw submissions evidence retained"
            return SubmissionsImportResult(status, cik, instrument_id, parsed.records, warnings, tuple(raw_docs), manifest_path, detail, False)
    except WorkflowTransitionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        return _failed(f"submissions import unavailable: {type(exc).__name__}: {str(exc)[:180]}", identity)


def _selection(identity: CanonicalIdentity, registry: Path | None) -> tuple[tuple[str, str] | None, str | None]:
    if not isinstance(identity, CanonicalIdentity):
        return None, "identity must be a CanonicalIdentity"
    if not isinstance(identity.cik, str) or re.fullmatch(r"(?:CIK)?[0-9]{1,10}", identity.cik.strip(), re.ASCII) is None:
        return None, "identity CIK must be an ASCII decimal string"
    cik = identity.cik.strip().upper().removeprefix("CIK").zfill(10)
    instrument_id = identity.instrument_id if isinstance(identity.instrument_id, str) else ""
    if not instrument_id.strip():
        return None, "identity instrument_id must be a non-empty string"
    if registry is not None:
        bindings = _registry_bindings(Path(registry), cik)
        if bindings is None:
            return None, "identity registry is unavailable or malformed"
        if bindings != {instrument_id.strip(): cik}:
            return None, "identity registry does not bidirectionally bind the selected CIK and instrument"
    return (cik, instrument_id.strip()), None


def _registry_bindings(path: Path, cik: str) -> dict[str, str] | None:
    try:
        import pandas as pd  # type: ignore[import-untyped]
        frame = pd.read_parquet(path)
        if "cik" not in frame.columns or "instrument_id" not in frame.columns:
            return None
        values: dict[str, str] = {}
        for _, row in frame.iterrows():
            raw_cik, raw_instrument = row.get("cik"), row.get("instrument_id")
            if not isinstance(raw_cik, str) or not isinstance(raw_instrument, str) or not raw_instrument.strip():
                return None
            if re.fullmatch(r"(?:CIK)?[0-9]{1,10}", raw_cik.strip(), re.ASCII) is None:
                return None
            normalized = raw_cik.strip().upper().removeprefix("CIK").zfill(10)
            if raw_instrument.strip() in values and values[raw_instrument.strip()] != normalized:
                return None
            values[raw_instrument.strip()] = normalized
        selected = {instrument: value for instrument, value in values.items() if value == cik}
        reverse = {instrument: value for instrument, value in values.items() if instrument}
        if len(selected) != 1 or len({value for value in reverse.values() if value == cik}) != 1:
            return None
        return selected
    except (OSError, ValueError, TypeError, ImportError):
        return None


def _prepare_parse_inputs(source: Path, cik: str, temp_root: Path, supplied: Mapping[str, Path] | None, provenance: RawDocument | None) -> tuple[Path, dict[str, Path], list[tuple[str, Path, RawDocument]]]:
    if not zipfile.is_zipfile(source):
        history = dict(supplied or {})
        for raw_path in history.values():
            candidate = Path(raw_path)
            if candidate.exists():
                _validate_input_path(candidate)
        return source, history, []
    current_name = f"CIK{cik}.json"
    members: dict[str, zipfile.ZipInfo] = {}
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError("submissions ZIP contains too many members")
        for info in infos:
            _validate_member(info)
            if info.filename in members:
                raise ValueError(f"duplicate submissions ZIP member: {info.filename}")
            members[info.filename] = info
        current = members.get(current_name)
        if current is None:
            raise ValueError(f"selected submissions member is missing: {current_name}")
        current_path = _extract_member(archive, current, temp_root / current_name)
        try:
            payload = json.loads(current_path.read_text(encoding="utf-8"))
            advertised = payload.get("filings", {}).get("files", [])
            advertised_names = [str(item["name"]) for item in advertised if isinstance(item, dict) and isinstance(item.get("name"), str)]
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            advertised_names = []
        selected = dict(supplied or {})
        member_inputs: list[tuple[str, Path, RawDocument]] = [("snapshot-member", current_path, _derived_member_document(current_path, provenance))]
        for name in advertised_names:
            if name in selected:
                continue
            member = members.get(str(name))
            if member is None:
                continue
            history_path = _extract_member(archive, member, temp_root / name)
            selected[name] = history_path
            member_inputs.append((f"history:{name}", history_path, _derived_member_document(history_path, provenance)))
        return current_path, selected, member_inputs


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename.replace("\\", "/")
    parsed = PurePosixPath(name)
    mode = (info.external_attr >> 16) & 0xFFFF
    if not name or parsed.is_absolute() or ".." in parsed.parts or re.match(r"^[A-Za-z]:", name) or stat.S_ISLNK(mode):
        raise ValueError("submissions ZIP contains an unsafe member")
    if info.flag_bits & 0x1 or info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
        raise ValueError("submissions ZIP member is encrypted or oversized")


def _extract_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, destination.open("wb") as target:
        copied = 0
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > MAX_MEMBER_BYTES:
                raise ValueError("submissions ZIP member exceeded its bounded extraction size")
            target.write(chunk)
    return destination


def _validate_filing_inputs(mapping: Mapping[str, Path | RawDocument] | None, records: tuple[SubmissionRecord, ...]) -> tuple[list[tuple[str, Path, RawDocument]], tuple[dict[str, object], ...]]:
    expected = {record.accession for record in records}
    if mapping is None:
        return [], ({"code": "filing_documents_missing", "message": "no filing document bytes were supplied; submissions coverage is partial"},)
    inputs: list[tuple[str, Path, RawDocument]] = []
    warnings: list[dict[str, object]] = []
    for accession, value in mapping.items():
        if not isinstance(accession, str) or accession not in expected:
            raise ValueError("filing_documents contains an accession not present in parsed submissions")
        document = value if isinstance(value, RawDocument) else None
        path = document.path if document is not None else Path(value)
        _validate_input_path(path)
        digest = _sha256_file(path)
        meta = _validated_provenance(document, path, digest, None, False) if document is not None else _local_document(path, "sec_filing")
        inputs.append((f"filing:{accession}", path, meta))
    missing = sorted(expected - set(mapping))
    if missing:
        warnings.append({"code": "filing_documents_missing", "message": f"filing bytes missing for {len(missing)} accession(s)"})
    return inputs, tuple(warnings)


def _retain_inputs(inputs: list[tuple[str, Path, RawDocument]], *, cache_dir: Path, publish_guard: PublicationScopeFactory | None) -> tuple[dict[str, dict[str, object]], list[RawDocument]]:
    _validate_namespace(cache_dir, cache_dir.parent)
    cache = ContentAddressedCache(cache_dir, relative_path=Path("sec_submissions_import"))
    _validate_namespace(cache.base, cache_dir)
    retained: dict[str, dict[str, object]] = {}
    documents: list[RawDocument] = []
    with publication_scope(publish_guard):
        with persistent_file_guard(cache.base / "import.guard"):
            for role, path, source in inputs:
                _validate_namespace(cache.base, cache_dir)
                digest = _sha256_file(path)
                if digest != source.sha256:
                    raise ValueError(f"{role} changed while submissions evidence was being retained")
                source_id = _safe_source_id(role, digest)
                result = cache.store_local_file(source_id, path, licence="SEC public data" if source.provider_id == "sec_edgar" else "local import", expected_sha256=digest, max_bytes=MAX_SOURCE_BYTES)
                object_path = (cache.root / result.manifest.object_path).resolve()
                _validate_namespace(object_path, cache.base)
                retained[role] = {"sha256": digest, "path": str(object_path), "source_url": source.source_url, "retrieved_at": source.retrieved_at.isoformat(), "provider_id": source.provider_id, "document_type": source.document_type, "http_status": source.http_status}
                documents.append(RawDocument(object_path, source.source_url, source.retrieved_at, digest, source.provider_id, source.document_type, source.media_type, source.http_status))
    return retained, documents


def _publish_manifest(path: Path, snapshot: dict[str, object], *, cache_dir: Path, publish_guard: PublicationScopeFactory | None) -> str:
    _validate_namespace(path, cache_dir / "sec_submissions_import")
    with publication_scope(publish_guard):
        path.parent.mkdir(parents=True, exist_ok=True)
        with persistent_file_guard(path.with_name(f"{path.name}.guard")):
            previous: dict[str, object] | None = None
            if path.is_file():
                try:
                    candidate = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(candidate, dict) and _manifest_snapshot_valid(candidate, cache_dir):
                        previous = candidate
                    else:
                        raise ValueError("existing submissions manifest is invalid; refusing replacement")
                except (OSError, ValueError, TypeError):
                    raise ValueError("existing submissions manifest is unreadable or invalid; refusing replacement")
            previous_snapshots = previous.get("snapshots") if previous else None
            snapshots: list[dict[str, object]] = [item for item in previous_snapshots if isinstance(item, dict)] if isinstance(previous_snapshots, list) else []
            if not any(isinstance(item, dict) and item.get("source_sha256") == snapshot["source_sha256"] for item in snapshots):
                snapshots.append(snapshot)
            payload = {"schema_version": MANIFEST_SCHEMA, "identity": snapshot["identity"], "parser_name": snapshot["parser_name"], "parser_version": snapshot["parser_version"], "snapshots": snapshots, "latest_source_sha256": snapshot["source_sha256"], "execution_allowed": False}
            atomic_write_json(path, payload)
            return "verified" if previous and snapshots[-1].get("source_sha256") == snapshot["source_sha256"] else "new"


def _manifest_snapshot_valid(manifest: dict[str, object], cache_dir: Path) -> bool:
    snapshots = manifest.get("snapshots")
    if manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("execution_allowed") is not False or not isinstance(snapshots, list):
        return False
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            return False
        items = [snapshot.get("source_document"), snapshot.get("snapshot_member"), *dict(snapshot.get("history_documents", {})).values(), *dict(snapshot.get("filing_documents", {})).values()]
        for item in items:
            if item is None:
                continue
            if not isinstance(item, dict) or not _retained_item_valid(item, cache_dir):
                return False
    return True


def _retained_item_valid(item: dict[str, object], cache_dir: Path) -> bool:
    path_value, digest = item.get("path"), item.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    path = Path(path_value)
    try:
        _validate_namespace(path, cache_dir / "sec_submissions_import")
        return path.is_file() and _sha256_file(path) == digest
    except (OSError, ValueError):
        return False


def _validated_provenance(document: RawDocument | None, path: Path, digest: str, cik: str | None, bulk: bool) -> RawDocument:
    if document is None:
        return _local_document(path, "sec_submissions_bulk" if bulk else "sec_submissions")
    if not isinstance(document.path, Path) or document.path.resolve() != path.resolve() or document.sha256 != digest:
        raise ValueError("submissions provenance path/checksum does not match supplied bytes")
    if not isinstance(document.retrieved_at, datetime) or document.retrieved_at.tzinfo is None or document.retrieved_at.utcoffset() is None:
        raise ValueError("submissions provenance timestamp must be timezone-aware")
    if type(document.http_status) is not int or document.http_status not in {200, 206, 304}:
        raise ValueError("submissions provenance HTTP status is invalid")
    expected_type = "sec_submissions_bulk" if bulk else "sec_submissions"
    if document.provider_id != "sec_edgar" or document.document_type != expected_type or document.media_type != ("application/zip" if bulk else "application/json"):
        raise ValueError("submissions provenance provider or document type is invalid")
    parsed = urlparse(document.source_url)
    if bulk:
        if document.source_url != SUBMISSIONS_BULK_URL:
            raise ValueError("submissions bulk provenance URL is invalid")
    elif cik is not None and document.source_url != SUBMISSIONS_URL.format(cik=cik):
        raise ValueError("submissions provenance URL does not match the selected CIK")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("submissions provenance URL contains unexpected credentials or components")
    return document


def _validated_aux_provenance(document: RawDocument | None, path: Path, digest: str) -> RawDocument:
    if document is None:
        return _local_document(path, "sec_submissions")
    if not isinstance(document.path, Path) or document.path.resolve() != path.resolve() or document.sha256 != digest:
        raise ValueError("submissions history provenance path/checksum does not match supplied bytes")
    if not isinstance(document.retrieved_at, datetime) or document.retrieved_at.tzinfo is None or document.retrieved_at.utcoffset() is None:
        raise ValueError("submissions history provenance timestamp must be timezone-aware")
    if type(document.http_status) is not int or document.http_status not in {200, 206, 304}:
        raise ValueError("submissions history provenance HTTP status is invalid")
    if document.provider_id == "sec_edgar" and (document.document_type != "sec_submissions" or document.media_type != "application/json"):
        raise ValueError("submissions history provenance document type or media type is invalid")
    return document


def _derived_member_document(path: Path, provenance: RawDocument | None) -> RawDocument:
    if provenance is None:
        return _local_document(path, "sec_submissions")
    return RawDocument(path, provenance.source_url, provenance.retrieved_at, _sha256_file(path), provenance.provider_id, "sec_submissions", "application/json", provenance.http_status)


def _local_document(path: Path, document_type: str) -> RawDocument:
    return RawDocument(path, path.resolve().as_uri(), datetime.now(timezone.utc), _sha256_file(path), "sec_local_import", document_type, "application/zip" if document_type.endswith("bulk") else "application/json", 200)


def _validate_input_path(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or _is_reparse(path):
        raise ValueError("submissions input must be an existing non-link file")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("submissions input exceeds the bounded size limit")


def _validate_namespace(path: Path, root: Path) -> None:
    absolute, root_absolute = Path(path).absolute(), Path(root).absolute()
    if not absolute.is_relative_to(root_absolute):
        raise ValueError("submissions cache path escapes its namespace")
    current = absolute
    while True:
        if current.is_symlink() or _is_reparse(current):
            raise ValueError("submissions cache namespace contains a link")
        if current.parent == current:
            break
        current = current.parent


def _is_reparse(path: Path) -> bool:
    try:
        return bool(int(getattr(path.lstat(), "st_file_attributes", 0)) & 0x400)
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_source_id(role: str, digest: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", role)[:100] + "-" + digest


def _warning_payload(warnings: tuple[ParseWarning, ...]) -> tuple[dict[str, object], ...]:
    return tuple(asdict(warning) for warning in warnings)


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _failed(detail: str, identity: CanonicalIdentity, *, warnings: tuple[dict[str, object], ...] = ()) -> SubmissionsImportResult:
    cik = identity.cik if isinstance(identity, CanonicalIdentity) and isinstance(identity.cik, str) else ""
    instrument = identity.instrument_id if isinstance(identity, CanonicalIdentity) and isinstance(identity.instrument_id, str) else ""
    return SubmissionsImportResult("failed", cik, instrument, warnings=warnings, detail=detail, execution_allowed=False)
