"""Local-first SEC companyfacts bulk archive import with resumable evidence."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile
from typing import Any, Iterator

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.workflow import PublicationScopeFactory, WorkflowTransitionError, publication_scope
from etf_cockpit.data.bulk_cache import (
    BulkCacheError,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ARCHIVE_MEMBERS,
    DEFAULT_MAX_COMPRESSION_RATIO,
    ArchiveValidationError,
    ContentAddressedCache,
)
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.sec_facts import (
    StatementFact,
    _authority_selection,
    _record_value,
    _statement_store_guards,
    parse_companyfacts,
    select_authoritative_facts,
    write_statement_evidence,
)


SEC_COMPANYFACTS_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE = "sec_companyfacts_bulk"
SEC_COMPANYFACTS_BULK_PARSER_VERSION = "1.0"
_MAX_SELECTED_MEMBER_BYTES = 256 * 1024 * 1024
_MAX_SELECTED_TOTAL_BYTES = 512 * 1024 * 1024
_CHECKPOINT_SCHEMA_VERSION = "sec_companyfacts_bulk.v1"


@dataclass(frozen=True)
class BulkCikStatus:
    cik: str
    instrument_id: str
    status: str
    member_name: str | None = None
    detail: str = ""
    member_sha256: str | None = None
    coverage_status: str = "complete"
    warnings: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class BulkImportResult:
    overall_status: str
    per_cik: tuple[BulkCikStatus, ...]
    archive_sha256: str | None
    checkpoint_path: Path | None
    execution_allowed: bool = False

    @property
    def status(self) -> str:
        return self.overall_status

    def to_dict(self) -> dict[str, object]:
        return {
            "overall_status": self.overall_status,
            "per_cik": [asdict(item) for item in self.per_cik],
            "archive_sha256": self.archive_sha256,
            "checkpoint_path": str(self.checkpoint_path) if self.checkpoint_path else None,
            "execution_allowed": False,
        }


def import_sec_companyfacts_bulk(
    archive: Path,
    identities: Iterable[CanonicalIdentity],
    *,
    cache_dir: Path,
    facts_destination: Path,
    inventory_destination: Path,
    provenance: RawDocument | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> BulkImportResult:
    """Import only requested SEC companyfacts members from a local ZIP archive."""

    requested, identity_error = _requested_identities(identities)
    if identity_error is not None:
        return _failed_result(identity_error, requested)
    archive_path = Path(archive)
    try:
        archive_sha256 = _validate_archive_source(archive_path, provenance)
        _validate_cache_root(Path(cache_dir))
        # Check the unresolved namespace before the cache constructor resolves it.
        _validate_namespace_path(Path(cache_dir) / "sec_companyfacts_bulk", Path(cache_dir))
        cache = ContentAddressedCache(Path(cache_dir), relative_path=Path("sec_companyfacts_bulk"))
        _validate_cache_namespace(cache)
        with publication_scope(publish_guard):
            with _guard(cache.base / "archive.guard"):
                # These are the existing cache's exact write targets for this source.
                # Validate leaves as well as parents before any archive publication.
                for target in (
                    cache.staging / "downloads" / "sec-companyfacts-bulk.part",
                    cache.objects / archive_sha256[:2] / archive_sha256,
                    cache.manifests / "sec-companyfacts-bulk.json",
                    cache.manifests / "invalidations.jsonl",
                ):
                    _validate_namespace_path(target, cache.base)
                cached_archive = cache.store_local_file(
                    "sec-companyfacts-bulk",
                    archive_path,
                    licence="official SEC public data" if provenance else "local SEC archive",
                    expected_sha256=archive_sha256,
                    max_bytes=DEFAULT_MAX_ARCHIVE_BYTES,
                )
        _validate_cache_namespace(cache)
        archive_object = (cache.root / cached_archive.manifest.object_path).resolve()
        _validate_namespace_path(archive_object, cache.base)
        if _sha256_file(archive_object) != archive_sha256:
            raise ArchiveValidationError("cached bulk archive checksum does not match the source")
        checkpoint_path = cache.base / "checkpoints" / f"{archive_sha256}.json"
        checkpoint = _load_checkpoint(checkpoint_path, archive_sha256)
        with zipfile.ZipFile(archive_object) as package:
            selected_names = {f"CIK{_normalise_cik(identity.cik)}.json" for identity in requested if _normalise_cik(identity.cik) is not None}
            members = _validated_members(package, selected_names)
            results = _import_members(
                package,
                members,
                requested,
                cache,
                archive_sha256,
                provenance,
                checkpoint,
                checkpoint_path,
                facts_destination,
                inventory_destination,
                publish_guard,
            )
    except WorkflowTransitionError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ArchiveValidationError, BulkCacheError) as exc:
        return _failed_result(f"bulk archive unavailable: {type(exc).__name__}: {exc}", requested, archive_sha256 if "archive_sha256" in locals() else None)

    statuses = tuple(results)
    overall = _overall_status(statuses)
    return BulkImportResult(overall, statuses, archive_sha256, checkpoint_path, False)


def _requested_identities(identities: Iterable[CanonicalIdentity]) -> tuple[tuple[CanonicalIdentity, ...], str | None]:
    try:
        values = tuple(identities)
    except TypeError as exc:
        return (), f"identities are invalid: {type(exc).__name__}"
    requested: list[CanonicalIdentity] = []
    seen: set[str] = set()
    seen_instruments: set[str] = set()
    for identity in values:
        if not isinstance(identity, CanonicalIdentity):
            return tuple(requested), "identities must contain CanonicalIdentity values"
        cik = _normalise_cik(identity.cik)
        if cik is None:
            requested.append(identity)
            return tuple(requested), "identity CIK is invalid"
        if cik in seen:
            requested.append(identity)
            return tuple(requested), f"identity CIK is duplicated: {cik}"
        instrument_id = str(identity.instrument_id or "").strip()
        if not instrument_id:
            requested.append(identity)
            return tuple(requested), f"identity {cik} has an empty instrument_id"
        if instrument_id in seen_instruments:
            requested.append(identity)
            return tuple(requested), f"instrument_id is duplicated: {instrument_id}"
        seen.add(cik)
        seen_instruments.add(instrument_id)
        requested.append(identity)
    return tuple(requested), None


def _validate_archive_source(path: Path, provenance: RawDocument | None) -> str:
    if _is_reparse_point(path) or path.is_symlink() or not path.is_file():
        raise ArchiveValidationError("bulk archive must be an existing non-symlink file")
    if path.stat().st_size > DEFAULT_MAX_ARCHIVE_BYTES:
        raise ArchiveValidationError("bulk archive exceeds the configured byte limit")
    archive_path = path.resolve()
    archive_sha256 = _sha256_file(archive_path)
    if provenance is None:
        return archive_sha256
    if not isinstance(provenance, RawDocument):
        raise ValueError("bulk provenance must be a RawDocument")
    if not isinstance(provenance.path, Path) or provenance.path.resolve() != archive_path:
        raise ValueError("bulk provenance path does not match the archive")
    if (
        provenance.provider_id != "sec_edgar"
        or provenance.document_type != SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE
        or provenance.media_type != "application/zip"
        or type(provenance.http_status) is not int
        or provenance.http_status not in {200, 206, 304}
        or provenance.source_url != SEC_COMPANYFACTS_BULK_URL
    ):
        raise ValueError("bulk provenance metadata is invalid")
    if not isinstance(provenance.retrieved_at, datetime) or provenance.retrieved_at.tzinfo is None or provenance.retrieved_at.utcoffset() is None:
        raise ValueError("bulk provenance retrieved_at must be timezone-aware")
    if provenance.sha256 != archive_sha256:
        raise ValueError("bulk provenance checksum does not match the archive")
    return archive_sha256


def _validated_members(package: zipfile.ZipFile, selected_names: set[str] | None = None) -> dict[str, zipfile.ZipInfo]:
    selected_names = selected_names or set()
    values = package.infolist()
    if len(values) > DEFAULT_MAX_ARCHIVE_MEMBERS:
        raise ArchiveValidationError("bulk archive contains too many members")
    members: dict[str, zipfile.ZipInfo] = {}
    compressed_total = 0
    selected_total = 0
    for member in values:
        name = member.filename
        _validate_member_name(name)
        if name in members:
            raise ArchiveValidationError(f"bulk archive contains duplicate member: {name}")
        if member.flag_bits & 0x1:
            raise ArchiveValidationError(f"encrypted bulk archive member is not allowed: {name}")
        mode = (member.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise ArchiveValidationError(f"bulk archive links are not allowed: {name}")
        size = member.file_size
        compressed = member.compress_size
        if not isinstance(size, int) or not isinstance(compressed, int) or size < 0 or compressed < 0:
            raise ArchiveValidationError(f"bulk archive member size is invalid: {name}")
        if name in selected_names and size > _MAX_SELECTED_MEMBER_BYTES:
            raise ArchiveValidationError(f"bulk archive member exceeds size limit: {name}")
        if size and compressed <= 0:
            raise ArchiveValidationError(f"bulk archive member compression size is invalid: {name}")
        if compressed and size / compressed > DEFAULT_MAX_COMPRESSION_RATIO:
            raise ArchiveValidationError(f"bulk archive member compression ratio is unsafe: {name}")
        compressed_total += compressed
        if compressed_total > DEFAULT_MAX_ARCHIVE_BYTES:
            raise ArchiveValidationError("bulk archive compressed bytes exceed the configured byte limit")
        if name in selected_names:
            selected_total += size
            if selected_total > _MAX_SELECTED_TOTAL_BYTES:
                raise ArchiveValidationError("selected bulk members exceed the configured extraction limit")
        members[name] = member
    return members


def _validate_member_name(name: object) -> None:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ArchiveValidationError("bulk archive member name is invalid")
    normalised = name.replace("\\", "/")
    parsed = PurePosixPath(normalised)
    if parsed.is_absolute() or re.match(r"^[A-Za-z]:", normalised) or ".." in parsed.parts or parsed.name != normalised.rsplit("/", 1)[-1]:
        raise ArchiveValidationError(f"bulk archive member escapes its namespace: {name}")


def _load_checkpoint(path: Path, archive_sha256: str) -> dict[str, dict[str, object]]:
    _validate_namespace_path(path, path.parent.parent)
    if not path.is_file():
        return {}
    try:
        with _guard(path):
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != _CHECKPOINT_SCHEMA_VERSION or payload.get("archive_sha256") != archive_sha256 or payload.get("bulk_parser_version") != SEC_COMPANYFACTS_BULK_PARSER_VERSION:
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    if payload.get("execution_allowed") is not False:
        return {}
    return {str(cik): entry for cik, entry in entries.items() if isinstance(entry, dict)}


def _import_members(
    package: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    requested: tuple[CanonicalIdentity, ...],
    cache: ContentAddressedCache,
    archive_sha256: str,
    provenance: RawDocument | None,
    checkpoint: dict[str, dict[str, object]],
    checkpoint_path: Path,
    facts_destination: Path,
    inventory_destination: Path,
    publish_guard: PublicationScopeFactory | None,
) -> list[BulkCikStatus]:
    results: list[BulkCikStatus] = []
    for identity in requested:
        published = False
        member_sha256: str | None = None
        warnings: tuple[dict[str, object], ...] = ()
        try:
            cik = _normalise_cik(identity.cik)
            assert cik is not None
            member_name = f"CIK{cik}.json"
            member = members.get(member_name)
            if member is None or member.is_dir():
                results.append(BulkCikStatus(cik, identity.instrument_id, "missing", member_name, "requested SEC companyfacts member is missing"))
                continue
            member_path = cache.base / "members" / archive_sha256 / member_name
            _validate_namespace_path(member_path, cache.base)
            with publication_scope(publish_guard):
                _safe_mkdir(member_path.parent, cache.base)
                member_sha256 = _extract_member(package, member, member_path)
            parsed = parse_companyfacts(member_path, identity)
            warnings = _warning_payload(parsed.warnings)
            if not parsed.success:
                codes = ", ".join(warning.code for warning in parsed.warnings) or "validation failed"
                results.append(BulkCikStatus(cik, identity.instrument_id, "failed", member_name, f"companyfacts parse failed: {codes}", member_sha256, "partial" if warnings else "complete", warnings))
                continue
            records = parsed.records if provenance is not None else _as_local_records(parsed.records)
            source = RawDocument(
                member_path,
                provenance.source_url if provenance is not None else member_path.resolve().as_uri(),
                provenance.retrieved_at if provenance is not None else datetime.now(timezone.utc),
                member_sha256,
                provenance.provider_id if provenance is not None else "sec_local_import",
                SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE,
                "application/json",
                provenance.http_status if provenance is not None else 200,
            )
            coverage_status = "partial" if warnings else "complete"
            entry = checkpoint.get(cik)
            if entry is not None and _checkpoint_entry_valid(entry, identity, archive_sha256, member_path, member_sha256, source, parsed, records, facts_destination, inventory_destination):
                results.append(BulkCikStatus(cik, identity.instrument_id, "skipped", member_name, "validated completed checkpoint" if not warnings else "validated completed checkpoint with parser warnings", member_sha256, coverage_status, warnings))
                continue
            with publication_scope(publish_guard):
                write_statement_evidence(
                    source,
                    records,
                    facts_destination,
                    inventory_destination,
                    instrument_id=identity.instrument_id,
                )
            published = True
            checkpoint_entry = _checkpoint_entry(identity, archive_sha256, member_path, member_sha256, source, parsed, records, facts_destination, inventory_destination, coverage_status, warnings)
            with publication_scope(publish_guard):
                _write_checkpoint(checkpoint_path, archive_sha256, checkpoint, cik, checkpoint_entry)
        except WorkflowTransitionError:
            raise
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ArchiveValidationError, UnicodeError) as exc:
            cik = _normalise_cik(identity.cik) or ""
            member_name = f"CIK{cik}.json"
            if published:
                results.append(BulkCikStatus(cik, identity.instrument_id, "imported", member_name, f"facts and inventory published; checkpoint unavailable: {type(exc).__name__}: {exc}", member_sha256 if "member_sha256" in locals() else None, "pending", warnings if "warnings" in locals() else ()))
            else:
                results.append(BulkCikStatus(cik, identity.instrument_id, "failed", member_name, f"member import unavailable: {type(exc).__name__}: {exc}"))
            continue
        except Exception as exc:
            cik = _normalise_cik(identity.cik) or ""
            member_name = f"CIK{cik}.json"
            if published:
                results.append(BulkCikStatus(cik, identity.instrument_id, "imported", member_name, f"facts and inventory published; checkpoint unavailable: {type(exc).__name__}", member_sha256 if "member_sha256" in locals() else None, "pending", warnings if "warnings" in locals() else ()))
            else:
                results.append(BulkCikStatus(cik, identity.instrument_id, "failed", member_name, f"member import unavailable: {type(exc).__name__}: {exc}"))
            continue
        results.append(BulkCikStatus(cik, identity.instrument_id, "imported", member_name, "facts and inventory published" if not warnings else "facts and inventory published with parser warnings", member_sha256, coverage_status, warnings))
    return results


def _extract_member(package: zipfile.ZipFile, member: zipfile.ZipInfo, destination: Path) -> str:
    namespace_root = destination.parents[2]
    _validate_namespace_path(destination, namespace_root)
    with _guard(destination):
        if _is_reparse_point(destination) or destination.is_symlink():
            raise ArchiveValidationError(f"selected member path is a symlink: {destination}")
        temporary_path: Path | None = None
        try:
            digest = hashlib.sha256()
            with package.open(member, "r") as source, tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as target:
                temporary_path = Path(target.name)
                streamed = 0
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    streamed += len(chunk)
                    if streamed > _MAX_SELECTED_MEMBER_BYTES:
                        raise ArchiveValidationError(f"selected member exceeds size limit: {destination.name}")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                import os
                os.fsync(target.fileno())
            member_sha256 = digest.hexdigest()
            if destination.is_file() and _sha256_file(destination) == member_sha256:
                temporary_path.unlink(missing_ok=True)
            else:
                temporary_path.replace(destination)
                _fsync_directory(destination.parent)
            return member_sha256
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _as_local_records(records: Iterable[StatementFact]) -> tuple[StatementFact, ...]:
    from dataclasses import replace

    result: list[StatementFact] = []
    for record in records:
        source_id = str(getattr(record, "source_id", ""))
        local_source_id = f"sec_local_import:{source_id.split(':', 1)[1]}" if source_id.startswith("sec_edgar:") else f"sec_local_import:{source_id}"
        result.append(replace(record, source_id=local_source_id, manual_review_required=True, mapping_confidence="manual_review"))
    return tuple(result)


def _checkpoint_entry(
    identity: CanonicalIdentity,
    archive_sha256: str,
    member_path: Path,
    member_sha256: str,
    source: RawDocument,
    parsed: Any,
    records: tuple[StatementFact, ...],
    facts_destination: Path,
    inventory_destination: Path,
    coverage_status: str,
    warnings: tuple[dict[str, object], ...],
) -> dict[str, object]:
    return {
        "cik": _normalise_cik(identity.cik),
        "instrument_id": identity.instrument_id,
        "archive_sha256": archive_sha256,
        "member_name": member_path.name,
        "member_path": str(member_path),
        "member_sha256": member_sha256,
        "provider_id": source.provider_id,
        "http_status": source.http_status,
        "document_type": source.document_type,
        "source_url": source.source_url,
        "source_authority": "official_regulator" if source.provider_id == "sec_edgar" else "manual_review",
        "retrieved_at": source.retrieved_at.isoformat(),
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
        "bulk_parser_version": SEC_COMPANYFACTS_BULK_PARSER_VERSION,
        "coverage_status": coverage_status,
        "warnings": list(warnings),
        "expected_fact_count": len(records),
        "expected_source_ids": sorted(record.source_id for record in records),
        "facts_destination": str(Path(facts_destination).resolve()),
        "inventory_destination": str(Path(inventory_destination).resolve()),
    }


def _write_checkpoint(
    path: Path,
    archive_sha256: str,
    entries: dict[str, dict[str, object]],
    cik: str,
    entry: dict[str, object],
) -> None:
    _validate_namespace_path(path, path.parent.parent)
    _safe_mkdir(path.parent, path.parent.parent)
    with _guard(path):
        current: dict[str, object] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if (
                    isinstance(loaded, dict)
                    and loaded.get("schema_version") == _CHECKPOINT_SCHEMA_VERSION
                    and loaded.get("archive_sha256") == archive_sha256
                    and loaded.get("bulk_parser_version") == SEC_COMPANYFACTS_BULK_PARSER_VERSION
                    and loaded.get("execution_allowed") is False
                    and isinstance(loaded.get("entries"), dict)
                ):
                    current = loaded
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                current = {}
        loaded_entries = current.get("entries")
        merged_entries: dict[str, object] = dict(loaded_entries) if isinstance(loaded_entries, dict) else {}
        merged_entries[cik] = entry
        payload = {
            "schema_version": _CHECKPOINT_SCHEMA_VERSION,
            "archive_sha256": archive_sha256,
            "parser_name": entry.get("parser_name", ""),
            "parser_version": entry.get("parser_version", ""),
            "bulk_parser_version": SEC_COMPANYFACTS_BULK_PARSER_VERSION,
            "source_url": entry.get("source_url", ""),
            "execution_allowed": False,
            "entries": merged_entries,
        }
        atomic_write_json(path, payload)
        entries.clear()
        entries.update({str(key): value for key, value in merged_entries.items() if isinstance(value, dict)})


def _checkpoint_entry_valid(
    entry: dict[str, object],
    identity: CanonicalIdentity,
    archive_sha256: str,
    member_path: Path,
    member_sha256: str,
    source: RawDocument,
    parsed: Any,
    records: tuple[StatementFact, ...],
    facts_destination: Path,
    inventory_destination: Path,
) -> bool:
    expected_source_ids = entry.get("expected_source_ids")
    if not isinstance(expected_source_ids, (list, tuple)):
        return False
    if (
        entry.get("archive_sha256") != archive_sha256
        or entry.get("cik") != _normalise_cik(identity.cik)
        or entry.get("member_name") != member_path.name
        or entry.get("member_path") != str(member_path)
        or entry.get("member_sha256") != member_sha256
        or entry.get("instrument_id") != identity.instrument_id
        or entry.get("facts_destination") != str(Path(facts_destination).resolve())
        or entry.get("inventory_destination") != str(Path(inventory_destination).resolve())
        or entry.get("document_type") != SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE
        or type(entry.get("http_status")) is not int
        or entry.get("http_status") not in {200, 206, 304}
        or entry.get("parser_name") != parsed.parser_name
        or entry.get("parser_version") != parsed.parser_version
        or entry.get("coverage_status") != ("partial" if entry.get("warnings") else "complete")
        or entry.get("warnings") != list(_warning_payload(parsed.warnings))
        or entry.get("expected_fact_count") != len(records)
        or sorted(str(item) for item in expected_source_ids) != sorted(record.source_id for record in records)
    ):
        return False
    if not member_path.is_file() or member_path.is_symlink() or _sha256_file(member_path) != member_sha256:
        return False
    expected_provider = str(entry.get("provider_id") or "")
    expected_authority = str(entry.get("source_authority") or "")
    expected_url = str(entry.get("source_url") or "")
    current_authority = "official_regulator" if source.provider_id == "sec_edgar" else "manual_review"
    if expected_provider == "sec_edgar":
        valid_source = expected_authority == current_authority and expected_url == source.source_url == SEC_COMPANYFACTS_BULK_URL
    else:
        valid_source = expected_authority == current_authority and expected_url == source.source_url and expected_url.startswith("file://")
    try:
        retrieved_at = datetime.fromisoformat(str(entry.get("retrieved_at") or ""))
        valid_timestamp = retrieved_at.tzinfo is not None and retrieved_at.utcoffset() is not None
    except ValueError:
        valid_timestamp = False
    if expected_provider != source.provider_id or expected_provider not in {"sec_edgar", "sec_local_import"} or entry.get("document_type") != source.document_type or source.media_type != "application/json" or type(source.http_status) is not int or source.http_status not in {200, 206, 304} or entry.get("http_status") != source.http_status or not valid_source or not valid_timestamp:
        return False
    if expected_provider == "sec_edgar" and entry.get("retrieved_at") != source.retrieved_at.isoformat():
        return False
    try:
        import pandas as pd  # type: ignore[import-untyped]

        # Read one consistent snapshot under the canonical writers' lock order.
        with _statement_store_guards((facts_destination, inventory_destination)):
            inventory = pd.read_parquet(inventory_destination)
            facts = pd.read_parquet(facts_destination)
    except (OSError, ValueError, ImportError, KeyError):
        return False
    if inventory.empty or facts.empty or not {"instrument_id", "checksum", "path", "document_id"}.issubset(inventory.columns):
        return False
    matches = inventory[
        (inventory["instrument_id"].astype(str) == str(identity.instrument_id))
        & (inventory["checksum"].astype(str) == member_sha256)
        & (inventory["path"].astype(str) == str(member_path))
        & (inventory["document_id"].astype(str) == f"{source.provider_id}:{member_sha256[:20]}")
    ]
    if matches.empty or "instrument_id" not in facts.columns or "source_id" not in facts.columns or "cik" not in facts.columns:
        return False
    inventory_row = matches.iloc[0]
    if _canonical_value(inventory_row.get("executable_authority")) is not False:
        return False
    expected_ids = {record.source_id for record in records}
    actual_ids = _as_string_set(inventory_row.get("source_ids"))
    if actual_ids != expected_ids or int(inventory_row.get("fact_count", -1)) != len(records):
        return False
    if str(inventory_row.get("source_authority", "")) != expected_authority or str(inventory_row.get("source_url", "")) != source.source_url or str(inventory_row.get("document_type", "")) != SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE or str(inventory_row.get("checksum", "")) != member_sha256 or str(inventory_row.get("path", "")) != str(member_path):
        return False
    try:
        persisted_ingested_at = datetime.fromisoformat(str(inventory_row.get("ingested_at", "")))
    except ValueError:
        return False
    if persisted_ingested_at.tzinfo is None or persisted_ingested_at.utcoffset() is None:
        return False
    if str(inventory_row.get("ingested_at", "")) != entry.get("retrieved_at"):
        return False
    if expected_provider == "sec_edgar" and str(inventory_row.get("ingested_at", "")) != source.retrieved_at.isoformat():
        return False
    persisted = facts[facts["instrument_id"].astype(str) == str(identity.instrument_id)]
    if not bool((persisted["cik"].astype(str) == str(records[0].cik if records else identity.cik)).any()):
        return False
    actual_fact_ids = {str(value) for value in persisted["source_id"].tolist()}
    if not expected_ids.issubset(actual_fact_ids):
        return False
    by_source = {record.source_id: record for record in records}
    # Replay the writer's existing selection across the full retained store.
    authoritative_ids = {
        _record_value(record, "source_id")
        for record in select_authoritative_facts(facts.to_dict(orient="records"), ())
    }
    for _, row in persisted[persisted["source_id"].astype(str).isin(expected_ids)].iterrows():
        expected = by_source.get(str(row.get("source_id")))
        if expected is None or any(_canonical_value(row.get(field)) != _canonical_value(getattr(expected, field)) for field in StatementFact.__dataclass_fields__):
            return False
        if row.get("authority_selection") != _authority_selection(expected.source_id, expected.source_id in authoritative_ids):
            return False
    return True


def _overall_status(statuses: tuple[BulkCikStatus, ...]) -> str:
    if not statuses:
        return "empty"
    values = {status.status for status in statuses}
    if values <= {"imported", "skipped"} and all(status.coverage_status == "complete" for status in statuses):
        return "complete"
    if "imported" in values or "skipped" in values:
        return "partial"
    return "failed"


def _failed_result(detail: str, requested: tuple[CanonicalIdentity, ...], archive_sha256: str | None = None) -> BulkImportResult:
    statuses = tuple(
        BulkCikStatus(_normalise_cik(identity.cik) or "", identity.instrument_id, "failed", None, detail)
        for identity in requested
    )
    return BulkImportResult("failed", statuses, archive_sha256, None, False)


def _normalise_cik(value: object) -> str | None:
    text = str(value or "").strip().upper().removeprefix("CIK")
    if not re.fullmatch(r"[0-9]{1,10}", text) or int(text) <= 0:
        return None
    return text.zfill(10)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _warning_payload(warnings: Iterable[Any]) -> tuple[dict[str, object], ...]:
    return tuple(asdict(warning) if hasattr(warning, "__dataclass_fields__") else {"message": str(warning)} for warning in warnings)


def _as_string_set(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    value_any: Any = value
    try:
        items = value_any.tolist() if hasattr(value_any, "tolist") else value_any
        return {str(item) for item in items}
    except (TypeError, AttributeError):
        return {str(value)}


def _canonical_value(value: object) -> object:
    if value is None:
        return None
    try:
        import pandas as pd  # type: ignore[import-untyped]

        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item") and not isinstance(value, (str, bytes, dict, list, tuple)):
        try:
            return _canonical_value(value.item())
        except (AttributeError, ValueError):
            pass
    if isinstance(value, (list, tuple)):
        return tuple(_canonical_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _canonical_value(item)) for key, item in value.items()))
    return value


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & 0x400)


def _reject_link_ancestors(path: Path) -> None:
    absolute = Path(path).absolute()
    current = absolute
    chain: list[Path] = []
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    for candidate in reversed(chain):
        if candidate.is_symlink() or _is_reparse_point(candidate):
            raise ArchiveValidationError(f"path contains a symlink or reparse point: {candidate}")


def _validate_cache_root(root: Path) -> None:
    _reject_link_ancestors(root)


def _validate_cache_namespace(cache: ContentAddressedCache) -> None:
    for path in (cache.base, cache.objects, cache.manifests, cache.staging, cache.generations, cache.base / "members", cache.base / "checkpoints"):
        _validate_namespace_path(path, cache.base if path != cache.base else cache.root)
        if path.exists() and not path.is_dir():
            raise ArchiveValidationError(f"cache namespace component is not a directory: {path}")


def _validate_namespace_path(path: Path, root: Path) -> None:
    root_absolute = Path(root).absolute()
    path_absolute = Path(path).absolute()
    try:
        path_absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise ArchiveValidationError(f"path escapes cache namespace: {path}") from exc
    _reject_link_ancestors(root_absolute)
    _reject_link_ancestors(path_absolute)


def _safe_mkdir(path: Path, root: Path) -> None:
    _validate_namespace_path(path, root)
    path.mkdir(parents=True, exist_ok=True)
    _validate_namespace_path(path, root)


@contextmanager
def _guard(path: Path) -> Iterator[object]:
    guard_path = path.with_name(f"{path.name}.guard")
    _reject_link_ancestors(guard_path)
    with persistent_file_guard(guard_path) as guard:
        yield guard


def _fsync_directory(path: Path) -> None:
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
