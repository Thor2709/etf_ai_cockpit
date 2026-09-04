"""Explicit local SEC submissions/history and raw-filing retention."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile
from urllib.parse import urlparse

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.workflow import PublicationScopeFactory, WorkflowTransitionError, publication_scope
from etf_cockpit.data.bulk_cache import BulkCacheError, ContentAddressedCache
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.data.sec_edgar_bulk import SecEdgarBulkError, _validate_zip_container
from etf_cockpit.data.sec_edgar_capability import _admitted, _derive
from etf_cockpit.parsers.contracts import ParseWarning, RawDocument
from etf_cockpit.parsers.sec_submissions import PARSER_NAME, PARSER_VERSION, SubmissionRecord, parse_submissions


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
MAX_SOURCE_BYTES = 8 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_SELECTED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0
MAX_MEMBERS = 1_000_000
MANIFEST_SCHEMA = "sec_submissions_import.v1"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024


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
            "records": [_json_safe(asdict(record)) for record in self.records],
            "warnings": _json_safe(list(self.warnings)),
            "raw_documents": [_json_safe(asdict(document)) for document in self.raw_documents],
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
        is_zip = zipfile.is_zipfile(source_path)
        _validate_input_path(source_path, max_bytes=MAX_SOURCE_BYTES if is_zip else MAX_MEMBER_BYTES)
        source_sha = _sha256_file(source_path)
        source_meta = _validated_provenance(provenance, source_path, source_sha, cik, is_zip)
        provenance_warning = () if provenance is None or source_meta.provider_id == provenance.provider_id else (
            {
                "code": "provenance_unattested",
                "message": "caller-supplied SEC provenance lacked provider-owned acquisition evidence; retained as local/manual evidence",
                "severity": "warning",
                "source_location": None,
            },
        )
        manifest_path = _manifest_path(Path(cache_dir), cik)
        cache = ContentAddressedCache(Path(cache_dir), relative_path=Path("sec_submissions_import"))
        # Admission must prove the complete cache namespace before inspecting
        # whether a manifest exists.  This prevents a link/reparse alias from
        # redirecting even a read outside the selected cache root.
        _validate_cache_targets(cache, source_id=None)
        _validate_namespace(manifest_path, cache.base)
        if manifest_path.is_file():
            if not _manifest_valid(manifest_path, Path(cache_dir)):
                return _failed("existing submissions manifest is invalid; refusing to mutate retained evidence", identity)
            if not _manifest_matches_selection(manifest_path, cik, instrument_id):
                return _failed("existing submissions manifest identity conflicts with the selected canonical identity", identity)
            try:
                candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError, RecursionError) as exc:
                raise ValueError("existing submissions manifest is unreadable; refusing replacement") from exc
            if not isinstance(candidate, dict):
                raise ValueError("existing submissions manifest is not an object")
            if provenance is None or source_meta.provider_id == "sec_local_import":
                for old_snapshot in candidate.get("snapshots", []):
                    if not isinstance(old_snapshot, dict) or old_snapshot.get("source_sha256") != source_sha:
                        continue
                    old_source = old_snapshot.get("source_document")
                    if isinstance(old_source, dict) and old_source.get("provider_id") == "sec_local_import":
                        source_meta = _document_from_metadata(source_path, old_source)
                    break
        with tempfile.TemporaryDirectory(prefix="sec-submissions-import-") as temp_name:
            capture_path = Path(temp_name) / source_path.name
            captured_sha = _capture_input(source_path, capture_path, max_bytes=MAX_SOURCE_BYTES if is_zip else MAX_MEMBER_BYTES)
            if captured_sha != source_sha:
                raise ValueError("submissions source changed while being captured")
            captured_history, history_metadata, history_warnings = _capture_history_inputs(
                history_paths,
                Path(temp_name) / "history",
                history_provenance,
                cik,
                source_is_bulk=is_zip,
                acquired_at=source_meta.retrieved_at,
            )
            parse_path, history_for_parser, member_inputs = _prepare_parse_inputs(
                capture_path, cik, Path(temp_name), captured_history, source_meta
            )
            history_warnings = tuple(history_warnings) + tuple(
                {
                    "code": "history_provenance_manual",
                    "message": f"SEC submissions history {role.removeprefix('history:')} was retained from a local archive without official acquisition provenance",
                    "severity": "warning",
                    "source_location": None,
                }
                for role, _, document in member_inputs
                if role.startswith("history:") and document.provider_id != "sec_edgar"
            )
            parsed = parse_submissions(parse_path, CanonicalIdentity(
                instrument_id, "Imported SEC entity", None, "needs_verification", "", None,
                None, "stock", {}, "manual_review", (), cik,
            ), history_paths=history_for_parser, acquired_at=source_meta.retrieved_at,
                history_acquired_at={
                    role.removeprefix("history:"): document.retrieved_at
                    for role, _, document in member_inputs
                    if role.startswith("history:")
                } | {
                    name: document.retrieved_at
                    for name, document in history_metadata.items()
                }, source_provider=source_meta.provider_id,
                history_source_providers={
                    role.removeprefix("history:"): document.provider_id
                    for role, _, document in member_inputs
                    if role.startswith("history:")
                } | {
                    name: document.provider_id
                    for name, document in history_metadata.items()
                })
            if parsed.source_sha256 != _sha256_file(parse_path):
                raise ValueError("submissions parser result is not bound to the immutable capture")
            warnings = tuple(list(_warning_payload(parsed.warnings)) + list(history_warnings) + list(provenance_warning))
            if not parsed.success or not parsed.records:
                return _failed(
                    "submissions parse failed: " + ", ".join(str(item["code"]) for item in warnings) if warnings else "submissions parse returned no records",
                    identity,
                    warnings=warnings,
                )
            filing_inputs = _validate_filing_inputs(filing_documents, parsed.records)
            warnings = tuple(list(warnings) + list(filing_inputs[1]))
            raw_inputs = [("snapshot", capture_path, source_meta)]
            raw_inputs.extend(member_inputs)
            known_history = {role.removeprefix("history:") for role, _, _ in member_inputs if role.startswith("history:")}
            for name, history_path in history_for_parser.items():
                if not history_path.is_file():
                    continue
                if history_path.name != name:
                    continue
                if name not in known_history:
                    history_meta = history_metadata.get(name)
                    if history_meta is None:
                        history_meta = _local_document(history_path, "sec_submissions")
                    raw_inputs.append((f"history:{name}", history_path, history_meta))
            raw_inputs.extend(filing_inputs[0])
            retained, raw_docs = _retain_inputs(
                raw_inputs, cache_dir=Path(cache_dir), publish_guard=publish_guard
            )
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
            snapshot["bundle_sha256"] = _bundle_sha256(snapshot)
            manifest = _publish_manifest(
                manifest_path, snapshot, cache_dir=Path(cache_dir), publish_guard=publish_guard
            )
            status = "partial" if warnings else "complete"
            detail = "verified restart or new source retained" if manifest == "verified" else "raw submissions evidence retained"
            return SubmissionsImportResult(status, cik, instrument_id, parsed.records, warnings, tuple(raw_docs), manifest_path, detail, False)
    except WorkflowTransitionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, zipfile.BadZipFile, BulkCacheError, SecEdgarBulkError) as exc:
        return _failed(f"submissions import unavailable: {type(exc).__name__}: {str(exc)[:180]}", identity)


def _selection(identity: CanonicalIdentity, registry: Path | None) -> tuple[tuple[str, str] | None, str | None]:
    if not isinstance(identity, CanonicalIdentity):
        return None, "identity must be a CanonicalIdentity"
    if not isinstance(identity.cik, str) or re.fullmatch(r"(?:CIK)?[0-9]{1,10}", identity.cik.strip(), re.ASCII) is None:
        return None, "identity CIK must be an ASCII decimal string"
    cik = identity.cik.strip().upper().removeprefix("CIK").zfill(10)
    instrument_id = identity.instrument_id if isinstance(identity.instrument_id, str) else ""
    if not instrument_id or instrument_id != instrument_id.strip():
        return None, "identity instrument_id must be a non-empty canonical string"
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
            if not isinstance(raw_cik, str) or not isinstance(raw_instrument, str) or not raw_instrument or raw_instrument != raw_instrument.strip():
                return None
            if re.fullmatch(r"(?:CIK)?[0-9]{1,10}", raw_cik.strip(), re.ASCII) is None:
                return None
            normalized = raw_cik.strip().upper().removeprefix("CIK").zfill(10)
            if raw_instrument in values and values[raw_instrument] != normalized:
                return None
            values[raw_instrument] = normalized
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
        selected_size = source.stat().st_size
        for raw_path in history.values():
            candidate = Path(raw_path)
            if candidate.exists():
                _validate_input_path(candidate, max_bytes=MAX_MEMBER_BYTES)
                selected_size += candidate.stat().st_size
                if selected_size > MAX_SELECTED_BYTES:
                    raise ValueError("selected submissions inputs exceed the aggregate size bound")
        return source, history, []
    current_name = f"CIK{cik}.json"
    members: dict[str, zipfile.ZipInfo] = {}
    _validate_zip_container(source, "submissions")
    selected_external_size = 0
    for raw_path in (supplied or {}).values():
        candidate = Path(raw_path)
        if candidate.exists():
            _validate_input_path(candidate, max_bytes=MAX_MEMBER_BYTES)
            selected_external_size += candidate.stat().st_size
    if selected_external_size > MAX_SELECTED_BYTES:
        raise ValueError("selected submissions inputs exceed the aggregate size bound")
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError("submissions ZIP contains too many members")
        for info in infos:
            _validate_member(info)
            if info.filename in members:
                raise ValueError(f"duplicate submissions ZIP member: {info.filename}")
            members[info.filename] = info
        current: zipfile.ZipInfo | None = members.get(current_name)
        if current is None:
            raise ValueError(f"selected submissions member is missing: {current_name}")
        selected_infos = [current]
        advertised_names: list[str] = []
        try:
            with archive.open(current) as current_stream:
                current_bytes = current_stream.read(MAX_MEMBER_BYTES + 1)
            if len(current_bytes) > MAX_MEMBER_BYTES:
                raise ValueError("selected submissions member exceeded its bounded size")
            payload = json.loads(current_bytes.decode("utf-8"))
            advertised = payload.get("filings", {}).get("files", []) if isinstance(payload, dict) else []
            advertised_names = [item["name"] for item in advertised if isinstance(item, dict) and isinstance(item.get("name"), str)]
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, KeyError, TypeError, RecursionError):
            advertised_names = []
        selected_names = set((supplied or {}).keys())
        selected_names.update(name for name in advertised_names if name in members and name not in selected_names)
        for name in selected_names:
            candidate_info: zipfile.ZipInfo | None = members.get(name)
            if candidate_info is not None:
                selected_infos.append(candidate_info)
        selected_total = selected_external_size
        for info in selected_infos:
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError("selected submissions member exceeds its bounded size")
            if info.compress_size <= 0 or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise ValueError("selected submissions member compression ratio is unsafe")
            selected_total += info.file_size
        if selected_total > MAX_SELECTED_BYTES:
            raise ValueError("selected submissions inputs exceed the aggregate size bound")
        current_path = _extract_member(archive, current, temp_root / current_name)
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
    _validate_namespace(destination, destination.parent.parent)
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
        return [], ({"code": "filing_documents_missing", "message": "no filing document bytes were supplied; submissions coverage is partial", "severity": "warning", "source_location": None},)
    if not isinstance(mapping, Mapping):
        raise ValueError("submissions filing_documents must be a mapping")
    inputs: list[tuple[str, Path, RawDocument]] = []
    warnings: list[dict[str, object]] = []
    records_by_accession = {record.accession: record for record in records}
    for accession, value in mapping.items():
        if not isinstance(accession, str) or accession not in expected:
            raise ValueError("filing_documents contains an accession not present in parsed submissions")
        document = value if isinstance(value, RawDocument) else None
        path = document.path if document is not None else Path(value)
        _validate_input_path(path)
        digest = _sha256_file(path)
        meta = _validated_filing_provenance(document, path, digest, records_by_accession[accession]) if document is not None else _local_document(path, "sec_filing")
        inputs.append((f"filing:{accession}", path, meta))
    missing = sorted(expected - set(mapping))
    if missing:
        warnings.append({"code": "filing_documents_missing", "message": f"filing bytes missing for {len(missing)} accession(s)", "severity": "warning", "source_location": None})
    return inputs, tuple(warnings)


def _capture_history_inputs(
    supplied: Mapping[str, Path] | None,
    temp_root: Path,
    history_provenance: Mapping[str, RawDocument] | None,
    cik: str,
    *,
    source_is_bulk: bool,
    acquired_at: datetime,
) -> tuple[dict[str, Path], dict[str, RawDocument], tuple[dict[str, object], ...]]:
    """Capture caller-supplied history and strip unattested official claims."""

    if history_provenance is not None and not isinstance(history_provenance, Mapping):
        raise ValueError("submissions history_provenance must be a mapping")
    if supplied is None:
        return {}, {}, ()
    if not isinstance(supplied, Mapping):
        raise ValueError("submissions history_paths must be a mapping")
    captured: dict[str, Path] = {}
    metadata: dict[str, RawDocument] = {}
    warnings: list[dict[str, object]] = []
    for raw_name, raw_path in supplied.items():
        if not isinstance(raw_name, str) or PurePosixPath(raw_name).name != raw_name or re.fullmatch(rf"CIK{cik}-submissions-[0-9]+\.json", raw_name) is None:
            # Let the parser retain its established warning for malformed
            # advertisements, but never construct a path from an unsafe key.
            raise ValueError("submissions history name is unsafe or not bound to the selected CIK")
        source_path = Path(raw_path)
        destination = temp_root / raw_name
        captured_sha = _capture_input(source_path, destination, max_bytes=MAX_MEMBER_BYTES)
        captured[raw_name] = destination
        # Detached files are newly captured inputs.  Their availability must
        # be anchored to this capture, never copied from the parent snapshot.
        captured_at = datetime.now(timezone.utc)
        source_document = (history_provenance or {}).get(raw_name)
        if source_document is not None and source_document.provider_id == "sec_edgar":
            if source_document.source_url == SUBMISSIONS_URL.format(cik=cik):
                raise ValueError("current SEC submissions endpoint cannot attest a named history file")
            if source_is_bulk or not _admitted(source_document, digest=captured_sha, document_type=source_document.document_type):
                metadata[raw_name] = _local_document(destination, "sec_submissions", retrieved_at=captured_at)
                warnings.append(
                    {
                        "code": "history_provenance_unattested",
                        "message": f"SEC submissions history {raw_name} lacked provider-owned acquisition evidence; retained as local manual evidence",
                        "severity": "warning",
                        "source_location": None,
                    }
                )
                continue
        if source_document is not None:
            validated = _validated_aux_provenance(
                source_document,
                source_path,
                captured_sha,
                raw_name,
                cik,
                source_is_bulk=source_is_bulk,
            )
            if validated.provider_id == "sec_local_import":
                metadata[raw_name] = _local_document(destination, "sec_submissions", retrieved_at=captured_at)
            else:
                metadata[raw_name] = _rebind_document_path(validated, destination)
        else:
            metadata[raw_name] = _local_document(destination, "sec_submissions", retrieved_at=captured_at)
        if metadata[raw_name].provider_id != "sec_edgar":
            warnings.append(
                {
                    "code": "history_provenance_manual",
                    "message": f"SEC submissions history {raw_name} was supplied as local/manual evidence rather than an archive-bound member",
                    "severity": "warning",
                    "source_location": None,
                }
            )
    return captured, metadata, tuple(warnings)


def _retain_inputs(inputs: list[tuple[str, Path, RawDocument]], *, cache_dir: Path, publish_guard: PublicationScopeFactory | None) -> tuple[dict[str, dict[str, object]], list[RawDocument]]:
    _validate_namespace(cache_dir, cache_dir.parent)
    cache = ContentAddressedCache(cache_dir, relative_path=Path("sec_submissions_import"))
    _validate_namespace(cache.base, cache_dir)
    retained: dict[str, dict[str, object]] = {}
    documents: list[RawDocument] = []
    # Validate all fixed targets, including the guard, before opening any
    # synchronization primitive.  A reparse/link guard must fail closed at
    # admission rather than after the OS has opened it.
    _validate_cache_targets(cache, source_id=None)
    with publication_scope(publish_guard):
        with persistent_file_guard(cache.base / "import.guard"):
            for role, path, source in inputs:
                _validate_namespace(cache.base, cache_dir)
                _validate_cache_targets(cache, source_id=None)
                _validate_input_path(path, max_bytes=MAX_SOURCE_BYTES)
                digest = _sha256_file(path)
                if digest != source.sha256:
                    raise ValueError(f"{role} changed while submissions evidence was being retained")
                source_id = _safe_source_id(role, digest)
                _validate_cache_targets(cache, source_id=source_id)
                _validate_namespace(cache.objects / digest[:2], cache.base)
                if (cache.objects / digest[:2]).exists() and (cache.objects / digest[:2]).is_symlink():
                    raise BulkCacheError("existing SEC submissions object prefix is a link")
                object_target = cache.objects / digest[:2] / digest
                if object_target.exists():
                    _validate_namespace(object_target, cache.base)
                    if not object_target.is_file() or _sha256_file(object_target) != digest:
                        raise BulkCacheError("existing SEC submissions cache object checksum is invalid")
                result = cache.store_local_file(source_id, path, licence="SEC public data" if source.provider_id == "sec_edgar" else "local import", expected_sha256=digest, max_bytes=MAX_SOURCE_BYTES)
                object_path = cache.root / result.manifest.object_path
                _validate_namespace(object_path, cache.base)
                if not object_path.is_file() or _sha256_file(object_path) != digest:
                    raise BulkCacheError("SEC submissions cache object checksum is invalid after retention")
                retained[role] = {"sha256": digest, "path": str(object_path), "source_url": source.source_url, "retrieved_at": source.retrieved_at.isoformat(), "provider_id": source.provider_id, "document_type": source.document_type, "media_type": source.media_type, "http_status": source.http_status}
                documents.append(RawDocument(object_path, source.source_url, source.retrieved_at, digest, source.provider_id, source.document_type, source.media_type, source.http_status))
    return retained, documents


def _publish_manifest(path: Path, snapshot: dict[str, object], *, cache_dir: Path, publish_guard: PublicationScopeFactory | None) -> str:
    base = Path(cache_dir).absolute() / "sec_submissions_import"
    _validate_namespace(base, Path(cache_dir).absolute())
    _validate_namespace(path, base)
    _validate_namespace(path.parent, base)
    guard_path = path.with_name(f"{path.name}.guard")
    _validate_namespace(guard_path, base)
    if path.exists() and (path.is_symlink() or _is_reparse(path)):
        raise ValueError("submissions manifest destination is a link")
    with publication_scope(publish_guard):
        path.parent.mkdir(parents=True, exist_ok=True)
        with persistent_file_guard(guard_path):
            if not _snapshot_valid(snapshot, cache_dir):
                raise ValueError("submissions snapshot is not self-consistent with retained evidence")
            previous: dict[str, object] | None = None
            if path.is_file():
                try:
                    if path.stat().st_size > MAX_MANIFEST_BYTES:
                        raise ValueError("existing submissions manifest exceeds its size bound")
                    candidate = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(candidate, dict) and _manifest_valid_payload(candidate, cache_dir):
                        previous = candidate
                    else:
                        raise ValueError("existing submissions manifest is invalid; refusing replacement")
                except (OSError, ValueError, TypeError):
                    raise ValueError("existing submissions manifest is unreadable or invalid; refusing replacement")
            if previous is not None and previous.get("identity") != snapshot.get("identity"):
                raise ValueError("existing submissions manifest identity conflicts with the selected canonical identity")
            previous_snapshots = previous.get("snapshots") if previous else None
            snapshots: list[dict[str, object]] = [item for item in previous_snapshots if isinstance(item, dict)] if isinstance(previous_snapshots, list) else []
            matching = next((item for item in snapshots if item.get("bundle_sha256") == snapshot["bundle_sha256"]), None)
            if matching is not None:
                # Move an already admitted snapshot to the tail when it is
                # observed again, so latest_* always names the final snapshot
                # without manufacturing an A-B-A duplicate generation.
                snapshots.remove(matching)
                snapshots.append(matching)
            else:
                snapshots.append(snapshot)
            payload = {"schema_version": MANIFEST_SCHEMA, "identity": snapshot["identity"], "parser_name": snapshot["parser_name"], "parser_version": snapshot["parser_version"], "snapshots": snapshots, "latest_source_sha256": snapshot["source_sha256"], "latest_bundle_sha256": snapshot["bundle_sha256"], "execution_allowed": False}
            encoded = (json.dumps(payload, indent=2, default=str) + "\n").encode("utf-8")
            if len(encoded) > MAX_MANIFEST_BYTES:
                raise ValueError("submissions manifest exceeds its size bound")
            atomic_write_json(path, payload)
            return "verified" if previous and previous.get("latest_bundle_sha256") == snapshot["bundle_sha256"] else "new"


def _manifest_valid(path: Path, cache_dir: Path) -> bool:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(payload, dict) and _manifest_valid_payload(payload, cache_dir)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _manifest_matches_selection(path: Path, cik: str, instrument_id: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(payload, dict) and payload.get("identity") == {"cik": cik, "instrument_id": instrument_id}
    except (OSError, ValueError, TypeError, json.JSONDecodeError, RecursionError):
        return False


def _manifest_valid_payload(payload: dict[str, object], cache_dir: Path) -> bool:
    snapshots = payload.get("snapshots")
    if payload.get("schema_version") != MANIFEST_SCHEMA or payload.get("execution_allowed") is not False or not isinstance(snapshots, list) or not snapshots:
        return False
    if not isinstance(payload.get("latest_source_sha256"), str) or not isinstance(payload.get("latest_bundle_sha256"), str) or not isinstance(snapshots[-1], dict) or payload["latest_source_sha256"] != snapshots[-1].get("source_sha256") or payload["latest_bundle_sha256"] != snapshots[-1].get("bundle_sha256"):
        return False
    first = snapshots[0]
    if not isinstance(first, dict) or payload.get("identity") != first.get("identity") or payload.get("parser_name") != first.get("parser_name") or payload.get("parser_version") != first.get("parser_version"):
        return False
    return all(
        isinstance(snapshot, dict)
        and snapshot.get("identity") == payload.get("identity")
        and snapshot.get("parser_name") == payload.get("parser_name")
        and snapshot.get("parser_version") == payload.get("parser_version")
        and _snapshot_valid(snapshot, cache_dir)
        for snapshot in snapshots
    )


def _snapshot_valid(snapshot: dict[str, object], cache_dir: Path) -> bool:
    required = {"bundle_sha256", "source_sha256", "source_document", "snapshot_member", "history_documents", "filing_documents", "records", "warnings", "coverage_status", "parser_name", "parser_version", "identity", "provenance"}
    bundle_sha = snapshot.get("bundle_sha256")
    source_sha = snapshot.get("source_sha256")
    if set(snapshot) != required or not isinstance(bundle_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", bundle_sha):
        return False
    if bundle_sha != _bundle_sha256({key: value for key, value in snapshot.items() if key != "bundle_sha256"}):
        return False
    source = snapshot.get("source_document")
    member = snapshot.get("snapshot_member")
    histories, filings = snapshot.get("history_documents"), snapshot.get("filing_documents")
    identity, records, warnings = snapshot.get("identity"), snapshot.get("records"), snapshot.get("warnings")
    if not isinstance(source, dict) or (member is not None and not isinstance(member, dict)) or not isinstance(histories, dict) or not isinstance(filings, dict) or not isinstance(identity, dict) or not isinstance(records, list) or not isinstance(warnings, list):
        return False
    if not isinstance(source_sha, str) or source.get("sha256") != source_sha or not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        return False
    identity_cik = identity.get("cik")
    identity_instrument = identity.get("instrument_id")
    if not isinstance(identity_cik, str) or re.fullmatch(r"[0-9]{10}", identity_cik) is None or not isinstance(identity_instrument, str) or not identity_instrument:
        return False
    if identity_instrument != identity_instrument.strip():
        return False
    if snapshot.get("parser_name") != PARSER_NAME or snapshot.get("parser_version") != PARSER_VERSION or snapshot.get("coverage_status") not in {"complete", "partial"}:
        return False
    if not _retained_item_valid(source, cache_dir) or (member is not None and not _retained_item_valid(member, cache_dir)):
        return False
    source_url = source.get("source_url")
    source_type = source.get("document_type")
    source_provider = source.get("provider_id")
    if source_provider == "sec_edgar":
        expected_url = SUBMISSIONS_BULK_URL if source_type == "sec_submissions_bulk" else SUBMISSIONS_URL.format(cik=identity_cik)
        if source_url != expected_url:
            return False
    elif source_provider != "sec_local_import" or not isinstance(source_url, str) or urlparse(source_url).scheme != "file":
        return False
    if source_type == "sec_submissions_bulk":
        if member is None or not _zip_snapshot_member_valid(source, member, identity_cik):
            return False
    elif source_type == "sec_submissions":
        if member is not None:
            return False
    else:
        return False
    for name, item in histories.items():
        if (
            not isinstance(name, str)
            or PurePosixPath(name).name != name
            or re.fullmatch(rf"CIK{identity_cik}-submissions-[0-9]+\.json", name) is None
            or not isinstance(item, dict)
            or item.get("document_type") != "sec_submissions"
            or not _retained_item_valid(item, cache_dir)
        ):
            return False
        if item.get("provider_id") == "sec_edgar":
            expected_history_url = SUBMISSIONS_BULK_URL if source_type == "sec_submissions_bulk" else f"https://data.sec.gov/submissions/{name}"
            if item.get("source_url") != expected_history_url:
                return False
            if source_type == "sec_submissions_bulk" and not _zip_member_valid(source, item, name):
                return False
        elif item.get("provider_id") != "sec_local_import" or urlparse(str(item.get("source_url", ""))).scheme != "file":
            return False
    for name, item in filings.items():
        if not isinstance(name, str) or re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", name) is None or not isinstance(item, dict) or item.get("document_type") != "sec_filing" or not _retained_item_valid(item, cache_dir):
            return False
    if not all(isinstance(item, dict) and set(item) >= {"code", "message", "severity"} and all(isinstance(item.get(key), str) for key in ("code", "message", "severity")) for item in warnings):
        return False
    if not all(isinstance(item, dict) for item in records):
        return False
    replay_path = Path(member["path"]) if member is not None else Path(source["path"])
    try:
        with tempfile.TemporaryDirectory(prefix="sec-submissions-manifest-") as replay_root:
            replay_history: dict[str, Path] = {}
            for name, item in histories.items():
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    return False
                destination = Path(replay_root) / name
                if not destination.is_relative_to(Path(replay_root)):
                    return False
                shutil.copyfile(Path(item["path"]), destination)
                replay_history[name] = destination
            replay = parse_submissions(
                replay_path,
                _manifest_identity(identity),
                history_paths=replay_history,
                acquired_at=datetime.fromisoformat(str(source["retrieved_at"])),
                history_acquired_at={
                    name: datetime.fromisoformat(str(item["retrieved_at"]))
                    for name, item in histories.items()
                    if isinstance(item, dict)
                },
                source_provider=str(source.get("provider_id", "sec_local_import")),
                history_source_providers={
                    name: str(item.get("provider_id", "sec_local_import"))
                    for name, item in histories.items()
                    if isinstance(item, dict)
                },
            )
    except (OSError, ValueError, TypeError):
        return False
    if [_json_safe(asdict(record)) for record in replay.records] != records:
        return False
    records_by_accession = {record.accession: record for record in replay.records}
    for accession, item in filings.items():
        if not isinstance(item, dict) or accession not in records_by_accession:
            return False
        if item.get("provider_id") == "sec_edgar":
            record = records_by_accession[accession]
            primary = record.primary_document
            archive_cik = str(int(record.cik)) if record.cik.isdigit() else ""
            expected_paths = {
                f"/Archives/edgar/data/{record.cik}/{accession.replace('-', '')}/{primary}",
                f"/Archives/edgar/data/{archive_cik}/{accession.replace('-', '')}/{primary}",
            } if isinstance(primary, str) and primary else set()
            parsed_url = urlparse(str(item.get("source_url", "")))
            if parsed_url.scheme != "https" or parsed_url.hostname != "www.sec.gov" or parsed_url.path not in expected_paths:
                return False
        elif item.get("provider_id") == "sec_local_import":
            if urlparse(str(item.get("source_url", ""))).scheme != "file":
                return False
        else:
            return False
    parser_warnings = _warning_payload(replay.warnings)
    if not all(item in warnings for item in parser_warnings) or (snapshot.get("coverage_status") == "complete" and warnings):
        return False
    if snapshot.get("coverage_status") == "complete" and len(filings) != len(replay.records):
        return False
    provenance = snapshot.get("provenance")
    if (
        not isinstance(provenance, dict)
        or any(
            provenance.get(key) != source.get(key)
            for key in ("sha256", "source_url", "retrieved_at", "provider_id", "document_type", "media_type", "http_status")
        )
        or not _retained_meta_valid(provenance, source, "snapshot")
    ):
        return False
    items = [source, member, *histories.values(), *filings.values()]
    for item in items:
        if item is None:
            continue
        if not isinstance(item, dict):
            return False
    return True


def _zip_snapshot_member_valid(source: dict[str, object], member: dict[str, object], cik: str) -> bool:
    """Verify the retained selected member still comes from its archive."""

    return _zip_member_valid(source, member, f"CIK{cik}.json")


def _zip_member_valid(source: dict[str, object], member: dict[str, object], member_name: str) -> bool:
    """Verify one retained JSON member still comes from its retained archive."""

    source_path, member_path = source.get("path"), member.get("path")
    member_digest = member.get("sha256")
    if (
        not isinstance(source_path, str)
        or not isinstance(member_path, str)
        or not isinstance(member_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", member_digest) is None
    ):
        return False
    try:
        with zipfile.ZipFile(Path(source_path)) as archive:
            info = archive.getinfo(member_name)
            _validate_member(info)
            with archive.open(info) as stream:
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest() == member_digest and _sha256_file(Path(member_path)) == member_digest
    except (OSError, KeyError, RuntimeError, ValueError, zipfile.BadZipFile):
        return False


def _manifest_identity(identity: dict[str, object]) -> CanonicalIdentity:
    return CanonicalIdentity(str(identity["instrument_id"]), "Imported SEC entity", None, "needs_verification", "", None, None, "stock", {}, "manual_review", (), str(identity["cik"]))


def _bundle_sha256(snapshot: dict[str, object]) -> str:
    payload = json.dumps(_json_safe(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_path(cache_dir: Path, cik: str) -> Path:
    root = Path(cache_dir).absolute()
    _validate_namespace(root, root.parent)
    base = root / "sec_submissions_import"
    _validate_namespace(base, root)
    return base / "records" / f"CIK{cik}.json"


def _retained_item_valid(item: dict[str, object], cache_dir: Path) -> bool:
    path_value, digest = item.get("path"), item.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    path = Path(path_value)
    try:
        _validate_namespace(path, cache_dir / "sec_submissions_import")
        expected = Path(cache_dir).absolute() / "sec_submissions_import" / "objects" / "sha256" / digest[:2] / digest
        return path.absolute() == expected and path.is_file() and _sha256_file(path) == digest and _retained_meta_valid(item, item, "retained")
    except (OSError, ValueError):
        return False


def _retained_meta_valid(item: object, source: object | None, role: str) -> bool:
    if not isinstance(item, dict):
        return False
    required = {"sha256", "path", "source_url", "retrieved_at", "provider_id", "document_type", "media_type", "http_status"}
    if set(item) != required:
        return False
    if not isinstance(item["path"], str) or not isinstance(item["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None:
        return False
    if not isinstance(item["source_url"], str) or not item["source_url"] or not isinstance(item["media_type"], str) or not item["media_type"]:
        return False
    try:
        stamp = datetime.fromisoformat(str(item["retrieved_at"]))
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return False
    status = item["http_status"]
    if type(status) is not int or status not in {200, 206, 304}:
        return False
    provider, doc_type = item["provider_id"], item["document_type"]
    if not isinstance(provider, str) or not isinstance(doc_type, str) or provider not in {"sec_edgar", "sec_local_import"}:
        return False
    if provider == "sec_local_import" and status != 200:
        return False
    media = item["media_type"]
    if doc_type == "sec_submissions_bulk" and media != "application/zip":
        return False
    if doc_type == "sec_submissions" and media != "application/json":
        return False
    if doc_type == "sec_filing" and media not in {"text/html", "text/plain", "application/pdf", "application/octet-stream"}:
        return False
    if role == "snapshot" and doc_type not in {"sec_submissions", "sec_submissions_bulk"}:
        return False
    if role.startswith("filing") and doc_type != "sec_filing":
        return False
    parsed = urlparse(item["source_url"])
    return not (parsed.username or parsed.password or parsed.query or parsed.fragment)


def _validated_provenance(document: RawDocument | None, path: Path, digest: str, cik: str | None, bulk: bool) -> RawDocument:
    if document is None:
        return _local_document(path, "sec_submissions_bulk" if bulk else "sec_submissions")
    if not isinstance(document.path, Path) or document.path.absolute() != path.absolute() or document.sha256 != digest:
        raise ValueError("submissions provenance path/checksum does not match supplied bytes")
    if not isinstance(document.retrieved_at, datetime) or document.retrieved_at.tzinfo is None or document.retrieved_at.utcoffset() is None:
        raise ValueError("submissions provenance timestamp must be timezone-aware")
    if type(document.http_status) is not int or document.http_status not in {200, 206, 304}:
        raise ValueError("submissions provenance HTTP status is invalid")
    expected_type = "sec_submissions_bulk" if bulk else "sec_submissions"
    if document.provider_id == "sec_local_import":
        if document.document_type != expected_type or document.media_type != ("application/zip" if bulk else "application/json"):
            raise ValueError("local submissions provenance provider or document type is invalid")
        parsed = urlparse(document.source_url)
        if parsed.scheme != "file" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("local submissions provenance must use a plain file URL")
        return document if document.http_status == 200 else _local_document(path, expected_type)
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
    if not _admitted(document, digest=digest, document_type=expected_type):
        return _local_document(path, expected_type)
    return document


def _validated_filing_provenance(document: RawDocument, path: Path, digest: str, record: SubmissionRecord) -> RawDocument:
    if not isinstance(document.path, Path) or document.path.absolute() != path.absolute() or document.sha256 != digest:
        raise ValueError("filing provenance path/checksum does not match supplied bytes")
    if not isinstance(document.retrieved_at, datetime) or document.retrieved_at.tzinfo is None or document.retrieved_at.utcoffset() is None:
        raise ValueError("filing provenance timestamp must be timezone-aware")
    if type(document.http_status) is not int or document.http_status not in {200, 206, 304}:
        raise ValueError("filing provenance HTTP status is invalid")
    parsed = urlparse(document.source_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("filing provenance URL contains unexpected components")
    if document.provider_id == "sec_local_import":
        if document.document_type != "sec_filing" or document.media_type not in {"text/html", "text/plain", "application/pdf", "application/octet-stream"}:
            raise ValueError("local filing provenance type or media is invalid")
        if parsed.scheme != "file":
            raise ValueError("local filing provenance must use a file URL")
        return document if document.http_status == 200 else _local_document(path, "sec_filing")
    if document.provider_id != "sec_edgar" or document.document_type != "sec_filing" or document.media_type not in {"text/html", "text/plain", "application/pdf", "application/octet-stream"}:
        raise ValueError("filing provenance provider, type, or media is invalid")
    if parsed.scheme != "https" or parsed.hostname != "www.sec.gov":
        raise ValueError("filing provenance must be an SEC Archives URL")
    primary = record.primary_document
    if not isinstance(primary, str) or not primary or PurePosixPath(primary).name != primary or ".." in PurePosixPath(primary).parts:
        raise ValueError("filing record has no safe primary document for provenance binding")
    archive_cik = str(int(record.cik)) if record.cik.isdigit() else ""
    expected_paths = {
        f"/Archives/edgar/data/{record.cik}/{record.accession.replace('-', '')}/{primary}",
        f"/Archives/edgar/data/{archive_cik}/{record.accession.replace('-', '')}/{primary}",
    }
    if parsed.path not in expected_paths:
        raise ValueError("filing provenance URL does not match the selected CIK, accession, and primary document")
    if not _admitted(document, digest=digest, document_type="sec_filing"):
        return _local_document(path, "sec_filing")
    return document if document.http_status == 200 else _local_document(path, "sec_filing")


def _validated_aux_provenance(document: RawDocument | None, path: Path, digest: str, name: str, cik: str, *, source_is_bulk: bool = False) -> RawDocument:
    if document is None:
        return _local_document(path, "sec_submissions")
    if not isinstance(document.path, Path) or document.path.absolute() != path.absolute() or document.sha256 != digest:
        raise ValueError("submissions history provenance path/checksum does not match supplied bytes")
    if not isinstance(document.retrieved_at, datetime) or document.retrieved_at.tzinfo is None or document.retrieved_at.utcoffset() is None:
        raise ValueError("submissions history provenance timestamp must be timezone-aware")
    if type(document.http_status) is not int or document.http_status not in {200, 206, 304}:
        raise ValueError("submissions history provenance HTTP status is invalid")
    parsed = urlparse(document.source_url)
    if document.provider_id == "sec_edgar":
        if document.document_type != "sec_submissions" or document.media_type != "application/json":
            raise ValueError("submissions history provenance document type or media type is invalid")
        expected_url = SUBMISSIONS_BULK_URL if source_is_bulk else f"https://data.sec.gov/submissions/{name}"
        if document.source_url != expected_url:
            raise ValueError("submissions history provenance URL is not the advertised SEC source")
        if source_is_bulk or not _admitted(document, digest=digest, document_type="sec_submissions"):
            return _local_document(path, "sec_submissions")
    elif document.provider_id != "sec_local_import":
        raise ValueError("submissions history provenance provider is invalid")
    elif document.document_type != "sec_submissions" or document.media_type != "application/json" or parsed.scheme != "file":
        raise ValueError("local submissions history provenance type or media is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("submissions history provenance URL contains unexpected components")
    return document


def _document_from_metadata(path: Path, item: dict[str, object]) -> RawDocument:
    """Re-bind a local input to its previously admitted acquisition lineage."""

    timestamp = datetime.fromisoformat(str(item["retrieved_at"]))
    return RawDocument(
        path,
        str(item["source_url"]),
        timestamp,
        str(item["sha256"]),
        str(item["provider_id"]),
        str(item["document_type"]),
        str(item["media_type"]),
        int(item["http_status"]),
    )


def _rebind_document_path(document: RawDocument, path: Path) -> RawDocument:
    return RawDocument(
        path,
        document.source_url,
        document.retrieved_at,
        document.sha256,
        document.provider_id,
        document.document_type,
        document.media_type,
        document.http_status,
    )


def _derived_member_document(path: Path, provenance: RawDocument | None) -> RawDocument:
    if provenance is None:
        return _local_document(path, "sec_submissions")
    document = RawDocument(path, provenance.source_url, provenance.retrieved_at, _sha256_file(path), provenance.provider_id, "sec_submissions", "application/json", provenance.http_status)
    return _derive(provenance, document)


def _local_document(path: Path, document_type: str, *, retrieved_at: datetime | None = None) -> RawDocument:
    if document_type.endswith("bulk"):
        media = "application/zip"
    elif document_type == "sec_filing":
        media = "text/html" if path.suffix.lower() in {".htm", ".html"} else "application/octet-stream"
    else:
        media = "application/json"
    return RawDocument(path, path.absolute().as_uri(), retrieved_at or datetime.now(timezone.utc), _sha256_file(path), "sec_local_import", document_type, media, 200)


def _validate_input_path(path: Path, *, max_bytes: int = MAX_SOURCE_BYTES) -> None:
    current = path.absolute()
    chain: list[Path] = []
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    if any(candidate.is_symlink() or _is_reparse(candidate) for candidate in reversed(chain)):
        raise ValueError("submissions input must be an existing non-link file")
    if not path.is_file():
        raise ValueError("submissions input must be an existing non-link file")
    if path.stat().st_size > max_bytes:
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


def _validate_cache_targets(cache: ContentAddressedCache, source_id: str | None) -> None:
    targets = [
        cache.root, cache.base, cache.objects, cache.manifests, cache.staging,
        cache.staging / "downloads", cache.generations, cache.base / "records",
        cache.base / "import.guard",
        cache.manifests / "invalidations.jsonl",
    ]
    if source_id is not None:
        targets.extend([
            cache.objects / "00",
            cache.manifests / f"{source_id}.json",
            cache.staging / "downloads" / f"{source_id}.part",
        ])
    for target in targets:
        _validate_namespace(target, cache.root)
        if target.exists() and (target.is_symlink() or _is_reparse(target)):
            raise BulkCacheError("SEC submissions cache target is a link")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_input(source: Path, destination: Path, *, max_bytes: int) -> str:
    """Copy one admitted input to a private immutable parse capture."""

    _validate_input_path(source, max_bytes=max_bytes)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as source_handle, destination.open("xb") as capture_handle:
        while True:
            chunk = source_handle.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > max_bytes:
                raise ValueError("submissions input exceeds the bounded capture size")
            digest.update(chunk)
            capture_handle.write(chunk)
        capture_handle.flush()
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
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _failed(detail: str, identity: CanonicalIdentity, *, warnings: tuple[dict[str, object], ...] = ()) -> SubmissionsImportResult:
    cik = identity.cik if isinstance(identity, CanonicalIdentity) and isinstance(identity.cik, str) else ""
    instrument = identity.instrument_id if isinstance(identity, CanonicalIdentity) and isinstance(identity.instrument_id, str) else ""
    return SubmissionsImportResult("failed", cik, instrument, warnings=warnings, detail=detail, execution_allowed=False)
