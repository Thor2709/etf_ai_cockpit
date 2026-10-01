"""Append-only point-in-time universe membership capture.

Raw payloads are gzip-compressed under their SHA-256 digest.  Capture logs and
membership interval revisions live in SQLite; the consumer frame expands only
captured snapshot dates and never fills dates before a capture.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time, timezone
import gzip
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Mapping

import pandas as pd
import yaml

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.catalogue import DataCatalogue, DatasetDefinition, DatasetSnapshot


_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "universe_membership_v1.yaml"
_DB_RELATIVE_PATH = Path("data") / "derived" / "universe_membership" / "membership.sqlite"
_RAW_RELATIVE_PATH = Path("data") / "raw" / "universe_membership"
_RAW_DATASET_ID = "universe_membership_raw"
_PROCESSED_DATASET_ID = "universe_membership_intervals"
_FRAME_COLUMNS = (
    "instrument_id",
    "valid_from",
    "valid_to",
    "known_at",
    "snapshot_date",
    "snapshot_complete",
)
_CAPTURE_COLUMNS = (
    "capture_id",
    "snapshot_date",
    "scope",
    "source",
    "source_id",
    "checksum",
    "complete",
    "known_at",
    "row_count",
    "raw_path",
    "source_kind",
    "licence_ref",
)
_INTERVAL_COLUMNS = (
    "scope",
    "instrument_id",
    "valid_from",
    "valid_to",
    "known_at",
    "source",
    "source_id",
    "source_kind",
)
_SCOPE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOG = logging.getLogger(__name__)


class MembershipCaptureError(ValueError):
    """Raised when membership input cannot be recorded without guessing."""


@dataclass(frozen=True)
class CaptureStatus:
    status: str
    scope: str
    checksum: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class LicensedImportStatus:
    status: str
    imported_rows: int
    skipped_self_captured_rows: int
    checksum: str


_LAST_CONFIGURED_STATUS = CaptureStatus("not_attempted", "configured")


def get_configured_capture_status() -> CaptureStatus:
    """Return the status from the most recent configured-universe save hook."""

    return _LAST_CONFIGURED_STATUS


def set_configured_capture_status(status: CaptureStatus) -> None:
    """Expose the save hook outcome without changing the universe save result."""

    global _LAST_CONFIGURED_STATUS
    _LAST_CONFIGURED_STATUS = status


def record_configured_capture(*, root: Path | None = None) -> CaptureStatus:
    """Capture the saved universe store after a successful canonical save."""

    from etf_cockpit.data.universe_store import load_universe

    active_root = Path(root or ROOT).resolve()
    try:
        snapshot = load_universe(active_root)
        if snapshot.integrity_errors:
            raise MembershipCaptureError(
                "saved universe integrity check failed: " + "; ".join(snapshot.integrity_errors)
            )
        payload_path = snapshot.path
        payload = payload_path.read_bytes()
        rows = [
            {"instrument_id": record.instrument_id}
            for record in snapshot.records
            if record.enabled
        ]
        config = _load_scope_config()
        status = _record_capture(
            rows,
            source=str(config["configured_source_id"]),
            source_id=str(config["configured_source_id"]),
            scope="configured",
            known_at=datetime.now(timezone.utc),
            root=active_root,
            raw_payload=payload,
            raw_row_count=len(snapshot.records),
        )
    except Exception as exc:
        status = CaptureStatus("failed", "configured", reason=f"{type(exc).__name__}: {exc}")
    set_configured_capture_status(status)
    if status.status != "recorded":
        _LOG.error("configured membership capture status=%s reason=%s", status.status, status.reason)
    else:
        _LOG.info("configured membership capture status=recorded checksum=%s", status.checksum)
    return status


def record_listing_capture(
    rows: Iterable[Mapping[str, object]] | object,
    source: str,
    scope: str,
    known_at: str | datetime,
    *,
    root: Path | None = None,
    raw_payload: bytes | None = None,
    snapshot_date: str | None = None,
) -> CaptureStatus:
    """Record one full listing capture for a config-declared listing scope."""

    scope_kind, _complete, _source_id = _validate_scope(scope, allow_configured=False)
    if scope_kind != "listing":
        raise MembershipCaptureError("record_listing_capture requires a listing:<venue>:<asset_type> scope")
    clean_source = _required_text(source, "source")
    return _record_capture(
        rows,
        source=clean_source,
        source_id=clean_source,
        scope=scope,
        known_at=known_at,
        root=Path(root or ROOT),
        raw_payload=raw_payload,
        snapshot_date=snapshot_date,
    )


def capture_log(scope: str | None = None, *, root: Path | None = None) -> pd.DataFrame:
    """Return immutable self-capture log rows for inspection."""

    if scope is not None:
        _validate_scope(scope)
    path = _database_path(root)
    if not path.is_file():
        return pd.DataFrame(columns=_CAPTURE_COLUMNS)
    connection = _connect(path, create=False)
    try:
        if scope is None:
            records = connection.execute(
                "SELECT capture_id, snapshot_date, scope, source, source_id, checksum, complete, "
                "known_at, row_count, raw_path, source_kind, licence_ref "
                "FROM capture_log ORDER BY capture_id"
            ).fetchall()
        else:
            records = connection.execute(
                "SELECT capture_id, snapshot_date, scope, source, source_id, checksum, complete, "
                "known_at, row_count, raw_path, source_kind, licence_ref "
                "FROM capture_log WHERE scope=? ORDER BY capture_id",
                (scope,),
            ).fetchall()
        return pd.DataFrame.from_records(records, columns=_CAPTURE_COLUMNS)
    finally:
        connection.close()


def membership_frame(
    scope: str,
    as_known_at: str | datetime | date,
    *,
    root: Path | None = None,
) -> pd.DataFrame:
    """Project captured membership into rank-validation's exact input schema."""

    _validate_scope(scope)
    cutoff = _utc_timestamp(as_known_at, "as_known_at")
    result: list[dict[str, object]] = []
    path = _database_path(root)
    if not path.is_file():
        return pd.DataFrame(columns=_FRAME_COLUMNS)
    connection = _connect(path, create=False)
    try:
        captures = connection.execute(
            "SELECT capture_id, snapshot_date, complete, known_at FROM capture_log "
            "WHERE scope=? AND source_kind='self' AND known_at<=? "
            "ORDER BY snapshot_date, known_at, capture_id",
            (scope, cutoff),
        ).fetchall()
        latest_self_by_day: dict[str, tuple[object, ...]] = {}
        for capture in captures:
            latest_self_by_day[str(capture[1])] = capture
        self_days = set(latest_self_by_day)
        for snapshot_date, capture in sorted(latest_self_by_day.items()):
            capture_known_at = str(capture[3])
            for interval in _latest_intervals(connection, scope, capture_known_at, "self"):
                if _covers(interval["valid_from"], interval["valid_to"], snapshot_date):
                    result.append(
                        {
                            "instrument_id": interval["instrument_id"],
                            "valid_from": interval["valid_from"],
                            "valid_to": interval["valid_to"],
                            "known_at": capture_known_at,
                            "snapshot_date": snapshot_date,
                            "snapshot_complete": bool(capture[2]),
                        }
                    )
        licensed = connection.execute(
            "SELECT scope, instrument_id, valid_from, valid_to, known_at, snapshot_date, complete "
            "FROM licensed_history WHERE scope=? AND known_at<=? "
            "ORDER BY snapshot_date, known_at, history_id",
            (scope, cutoff),
        ).fetchall()
        latest_licensed: dict[tuple[str, str], tuple[object, ...]] = {}
        for row in licensed:
            snapshot_date = str(row[5])
            if snapshot_date in self_days:
                continue
            latest_licensed[(snapshot_date, str(row[1]))] = row
        for (snapshot_date, _instrument_id), row in sorted(latest_licensed.items()):
            if _covers(str(row[2]), str(row[3]) if row[3] is not None else None, snapshot_date):
                result.append(
                    {
                        "instrument_id": row[1],
                        "valid_from": row[2],
                        "valid_to": row[3],
                        "known_at": row[4],
                        "snapshot_date": row[5],
                        "snapshot_complete": bool(row[6]),
                    }
                )
    finally:
        connection.close()
    return pd.DataFrame.from_records(result, columns=_FRAME_COLUMNS)


def membership_intervals(
    scope: str,
    as_known_at: str | datetime | date,
    *,
    root: Path | None = None,
) -> pd.DataFrame:
    """Return the latest interval revisions known by the requested timestamp."""

    _validate_scope(scope)
    cutoff = _utc_timestamp(as_known_at, "as_known_at")
    path = _database_path(root)
    if not path.is_file():
        return pd.DataFrame(columns=_INTERVAL_COLUMNS)
    connection = _connect(path, create=False)
    try:
        rows = _latest_intervals(connection, scope, cutoff, "self")
    finally:
        connection.close()
    return pd.DataFrame.from_records(rows, columns=_INTERVAL_COLUMNS)


def closure_events(
    scope: str,
    as_known_at: str | datetime | date | None = None,
    *,
    root: Path | None = None,
) -> pd.DataFrame:
    """Return closed self-captured membership intervals known by the cutoff."""

    _validate_scope(scope)
    cutoff = _utc_timestamp(
        as_known_at if as_known_at is not None else datetime.now(timezone.utc), "as_known_at"
    )
    columns = _INTERVAL_COLUMNS
    path = _database_path(root)
    if not path.is_file():
        return pd.DataFrame(columns=columns)
    connection = _connect(path, create=False)
    try:
        revisions = _latest_intervals(connection, scope, cutoff, "self")
    finally:
        connection.close()
    return pd.DataFrame.from_records(
        [row for row in revisions if row["valid_to"] is not None], columns=columns
    )


def load_raw_payload(checksum: str, *, root: Path | None = None) -> bytes:
    """Read and verify a raw payload by its content-addressed checksum."""

    if not _SHA256.fullmatch(str(checksum)):
        raise MembershipCaptureError("checksum must be a lowercase SHA-256 value")
    active_root = Path(root or ROOT)
    path = active_root / _RAW_RELATIVE_PATH / f"{checksum}.payload.gz"
    try:
        payload = gzip.decompress(path.read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise MembershipCaptureError(f"raw payload is unavailable or corrupt: {checksum}") from exc
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise MembershipCaptureError(f"raw payload checksum mismatch: {checksum}")
    return payload


def import_licensed_history(
    rows: Iterable[Mapping[str, object]] | object,
    source: str,
    licence_ref: str,
    *,
    root: Path | None = None,
) -> LicensedImportStatus:
    """Append licensed point-in-time intervals without replacing self captures.

    Each row must supply scope, instrument_id, valid_from, snapshot_date,
    snapshot_complete and a timezone-aware source known_at value.
    """

    clean_source = _required_text(source, "source")
    clean_licence = _required_text(licence_ref, "licence_ref")
    payload, materialised = _materialise_rows(rows)
    prepared: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in materialised:
        scope = str(row.get("scope") or "")
        _validate_scope(scope)
        instrument_id = _instrument_id(row)
        valid_from = _date_text(row.get("valid_from"), "valid_from")
        valid_to = _optional_date_text(row.get("valid_to"), "valid_to")
        if valid_to is not None and valid_to <= valid_from:
            raise MembershipCaptureError("valid_to must be after valid_from for half-open intervals")
        snapshot_date = _date_text(row.get("snapshot_date"), "snapshot_date")
        if not _covers(valid_from, valid_to, snapshot_date):
            raise MembershipCaptureError(
                "snapshot_date must lie within the half-open valid interval [valid_from, valid_to)"
            )
        complete_value = row.get("snapshot_complete")
        if not isinstance(complete_value, bool):
            raise MembershipCaptureError("snapshot_complete must be a boolean")
        known_at = _utc_timestamp(row.get("known_at"), "known_at")
        identity = (scope, snapshot_date, instrument_id.casefold())
        if identity in seen:
            raise MembershipCaptureError("licensed snapshot contains duplicate instruments")
        seen.add(identity)
        prepared.append(
            {
                "scope": scope,
                "instrument_id": instrument_id,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "known_at": known_at,
                "snapshot_date": snapshot_date,
                "complete": complete_value,
            }
        )
    if not prepared:
        raise MembershipCaptureError("licensed history payload is empty")
    checksum = hashlib.sha256(payload).hexdigest()
    active_root = Path(root or ROOT)
    raw_path = _store_raw_payload(payload, checksum, active_root)
    catalogue = _ensure_catalogue(active_root)
    raw_snapshot = _register_raw_snapshot(catalogue, checksum, len(prepared))
    connection = _connect(active_root / _DB_RELATIVE_PATH, create=True)
    processed_rows: list[dict[str, object]] = []
    imported_count = 0
    skipped_count = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        import_cursor = connection.execute(
            "INSERT INTO licensed_imports(source_id, licence_ref, checksum, row_count, raw_path, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (clean_source, clean_licence, checksum, len(prepared), raw_path, _utc_timestamp(datetime.now(timezone.utc), "imported_at")),
        )
        import_id = int(import_cursor.lastrowid)
        for row in prepared:
            self_capture = connection.execute(
                "SELECT 1 FROM capture_log WHERE scope=? AND snapshot_date=? AND source_kind='self' LIMIT 1",
                (row["scope"], row["snapshot_date"]),
            ).fetchone()
            if self_capture is not None:
                skipped_count += 1
                continue
            existing = connection.execute(
                "SELECT MAX(known_at) FROM licensed_history WHERE scope=? AND snapshot_date=? AND instrument_id=?",
                (row["scope"], row["snapshot_date"], row["instrument_id"]),
            ).fetchone()[0]
            if existing is not None and str(row["known_at"]) <= str(existing):
                raise MembershipCaptureError(
                    "a licensed correction requires a later source known_at revision"
                )
            connection.execute(
                "INSERT INTO licensed_history(interval_id, scope, instrument_id, valid_from, valid_to, known_at, "
                "snapshot_date, complete, source, source_id, licence_ref, checksum, import_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'licensed', ?, ?, ?, ?)",
                (
                    f"{import_id}:{row['snapshot_date']}:{row['instrument_id']}",
                    row["scope"],
                    row["instrument_id"],
                    row["valid_from"],
                    row["valid_to"],
                    row["known_at"],
                    row["snapshot_date"],
                    int(row["complete"]),
                    clean_source,
                    clean_licence,
                    checksum,
                    import_id,
                ),
            )
            processed_rows.append({**row, "source": "licensed", "source_id": clean_source, "licence_ref": clean_licence})
            imported_count += 1
        imported_at = _utc_timestamp(datetime.now(timezone.utc), "imported_at")
        _register_processed_snapshot(
            catalogue,
            processed_rows or [{"source": "licensed", "skipped_self_captured_rows": skipped_count}],
            raw_snapshot.snapshot_id,
            imported_at,
            scope="licensed_history",
            source=clean_source,
            checksum=checksum,
            raw_path=raw_path,
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return LicensedImportStatus("recorded", imported_count, skipped_count, checksum)


def _record_capture(
    rows: Iterable[Mapping[str, object]] | object,
    *,
    source: str,
    source_id: str,
    scope: str,
    known_at: str | datetime,
    root: Path,
    raw_payload: bytes | None = None,
    raw_row_count: int | None = None,
    snapshot_date: str | None = None,
) -> CaptureStatus:
    _scope_kind, complete, _configured_source = _validate_scope(scope)
    payload, materialised = _materialise_rows(rows, raw_payload=raw_payload)
    identifiers = [_instrument_id(row) for row in materialised]
    if not identifiers:
        raise MembershipCaptureError("membership payload is empty")
    folded = [item.casefold() for item in identifiers]
    if len(set(folded)) != len(folded):
        raise MembershipCaptureError("membership payload contains duplicate instruments")
    timestamp = _utc_timestamp(known_at, "known_at")
    deduplicate_snapshot = snapshot_date is not None
    snapshot_date = _date_text(snapshot_date, "snapshot_date") if snapshot_date is not None else timestamp[:10]
    if snapshot_date > timestamp[:10]:
        raise MembershipCaptureError("snapshot_date must not be after known_at")
    digest = hashlib.sha256(payload).hexdigest()
    active_root = Path(root).resolve()
    database_path = active_root / _DB_RELATIVE_PATH
    connection = _connect(database_path, create=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if deduplicate_snapshot:
            duplicate = connection.execute(
                "SELECT 1 FROM capture_log WHERE scope=? AND snapshot_date=? AND checksum=? "
                "AND source_kind='self' LIMIT 1",
                (scope, snapshot_date, digest),
            ).fetchone()
            if duplicate is not None:
                connection.commit()
                return CaptureStatus("duplicate", scope, digest)
        previous_known_at = connection.execute(
            "SELECT MAX(known_at) FROM capture_log WHERE scope=? AND source_kind='self'",
            (scope,),
        ).fetchone()[0]
        if previous_known_at is not None and timestamp <= str(previous_known_at):
            raise MembershipCaptureError("capture known_at must advance within its declared scope")
        active = _latest_intervals(connection, scope, timestamp, "self")
        open_by_instrument = {
            str(row["instrument_id"]): row
            for row in active
            if row["valid_to"] is None
        }
        raw_path = _store_raw_payload(payload, digest, active_root)
        catalogue = _ensure_catalogue(active_root)
        raw_snapshot = _register_raw_snapshot(
            catalogue, digest, int(raw_row_count if raw_row_count is not None else len(materialised))
        )
        cursor = connection.execute(
            "INSERT INTO capture_log(snapshot_date, scope, source, source_id, checksum, complete, known_at, row_count, "
            "raw_path, source_kind, licence_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'self', NULL)",
            (
                snapshot_date,
                scope,
                source,
                source_id,
                digest,
                int(complete),
                timestamp,
                int(raw_row_count if raw_row_count is not None else len(materialised)),
                raw_path,
            ),
        )
        capture_id = int(cursor.lastrowid)
        new_ids = set(identifiers)
        changed_rows: list[dict[str, object]] = []
        for instrument_id, prior in open_by_instrument.items():
            if instrument_id in new_ids:
                continue
            closed = {
                "scope": scope,
                "instrument_id": instrument_id,
                "valid_from": prior["valid_from"],
                "valid_to": snapshot_date,
                "known_at": timestamp,
                "source": source,
                "source_id": source_id,
                "source_kind": "self",
                "interval_id": prior["interval_id"],
                "capture_id": capture_id,
            }
            _insert_interval_revision(connection, closed)
            changed_rows.append(closed)
        for row, instrument_id in zip(materialised, identifiers, strict=True):
            if instrument_id in open_by_instrument:
                continue
            opened = {
                "scope": scope,
                "instrument_id": instrument_id,
                "valid_from": snapshot_date,
                "valid_to": None,
                "known_at": timestamp,
                "source": source,
                "source_id": source_id,
                "source_kind": "self",
                "interval_id": f"capture:{capture_id}:{instrument_id}",
                "capture_id": capture_id,
            }
            _insert_interval_revision(connection, opened)
            changed_rows.append(opened)
        processed_row = {
            "snapshot_date": snapshot_date,
            "scope": scope,
            "source": source,
            "source_id": source_id,
            "checksum": digest,
            "complete": complete,
            "known_at": timestamp,
            "row_count": int(raw_row_count if raw_row_count is not None else len(materialised)),
            "raw_path": raw_path,
            "interval_revisions": changed_rows,
        }
        _register_processed_snapshot(
            catalogue,
            [processed_row],
            raw_snapshot.snapshot_id,
            timestamp,
            scope=scope,
            source=source,
            checksum=digest,
            raw_path=raw_path,
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return CaptureStatus("recorded", scope, digest)


def _insert_interval_revision(connection: sqlite3.Connection, row: Mapping[str, object]) -> None:
    connection.execute(
        "INSERT INTO interval_revisions(interval_id, scope, instrument_id, valid_from, valid_to, known_at, source, "
        "source_id, source_kind, capture_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["interval_id"],
            row["scope"],
            row["instrument_id"],
            row["valid_from"],
            row["valid_to"],
            row["known_at"],
            row["source"],
            row["source_id"],
            row["source_kind"],
            row["capture_id"],
        ),
    )


def _latest_intervals(
    connection: sqlite3.Connection,
    scope: str,
    as_known_at: str,
    source_kind: str,
) -> list[dict[str, object]]:
    records = connection.execute(
        "SELECT r.scope, r.instrument_id, r.valid_from, r.valid_to, r.known_at, r.source, r.source_id, "
        "r.source_kind, r.interval_id FROM interval_revisions r WHERE r.scope=? AND r.source_kind=? "
        "AND r.known_at<=? AND r.revision_id=(SELECT MAX(l.revision_id) FROM interval_revisions l "
        "WHERE l.interval_id=r.interval_id AND l.known_at<=?) ORDER BY r.instrument_id, r.valid_from, r.interval_id",
        (scope, source_kind, as_known_at, as_known_at),
    ).fetchall()
    return [dict(zip((*_INTERVAL_COLUMNS, "interval_id"), row, strict=True)) for row in records]


def _covers(valid_from: str, valid_to: str | None, day: str) -> bool:
    return valid_from <= day and (valid_to is None or day < valid_to)


def _database_path(root: Path | None) -> Path:
    return Path(root or ROOT) / _DB_RELATIVE_PATH


def _materialise_rows(
    rows: Iterable[Mapping[str, object]] | object,
    *,
    raw_payload: bytes | None = None,
) -> tuple[bytes, list[Mapping[str, object]]]:
    if isinstance(rows, (bytes, bytearray)):
        payload = bytes(rows) if raw_payload is None else raw_payload
        try:
            decoded = json.loads(bytes(rows))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MembershipCaptureError("byte payload must contain JSON membership rows") from exc
        material = decoded if isinstance(decoded, list) else [decoded]
    elif isinstance(rows, str):
        payload = rows.encode("utf-8") if raw_payload is None else raw_payload
        try:
            decoded = json.loads(rows)
        except json.JSONDecodeError as exc:
            raise MembershipCaptureError("text payload must contain JSON membership rows") from exc
        material = decoded if isinstance(decoded, list) else [decoded]
    else:
        if hasattr(rows, "to_dict"):
            try:
                rows = rows.to_dict(orient="records")  # type: ignore[union-attr]
            except (TypeError, ValueError) as exc:
                raise MembershipCaptureError("membership rows could not be read") from exc
        if isinstance(rows, Mapping) or is_dataclass(rows):
            material = [rows]
        else:
            try:
                material = list(rows)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise MembershipCaptureError("membership rows must be mappings") from exc
        if raw_payload is None:
            try:
                serialisable = [asdict(row) if is_dataclass(row) else dict(row) for row in material]
                payload = json.dumps(
                    serialisable,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                    default=str,
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise MembershipCaptureError("membership rows are not JSON serialisable") from exc
        else:
            payload = raw_payload
    if not isinstance(material, list) or any(not isinstance(row, Mapping) and not is_dataclass(row) for row in material):
        raise MembershipCaptureError("membership payload must contain mapping rows")
    if raw_payload is not None and isinstance(rows, (bytes, bytearray, str)):
        payload = raw_payload
    return payload, [asdict(row) if is_dataclass(row) else row for row in material]


def _instrument_id(row: Mapping[str, object]) -> str:
    value = row.get("instrument_id")
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise MembershipCaptureError("membership row requires a non-empty instrument_id")
    return value


def _validate_scope(scope: str, *, allow_configured: bool = True) -> tuple[str, bool, str]:
    config = _load_scope_config()
    if not isinstance(scope, str) or not scope:
        raise MembershipCaptureError("scope must be a non-empty configured scope")
    if scope not in config["allowed_scopes"]:
        raise MembershipCaptureError(f"scope is not declared in universe_membership_v1.yaml: {scope!r}")
    if scope == config["configured_scope"]:
        if not allow_configured:
            raise MembershipCaptureError("configured scope is recorded only by save_universe")
        return "configured", bool(config["configured_complete"]), str(config["configured_source_id"])
    parts = scope.split(":")
    if len(parts) == 3 and parts[0] == "listing" and all(_SCOPE_PART.fullmatch(item) for item in parts[1:]):
        return "listing", bool(config["listing_complete"]), ""
    raise MembershipCaptureError(f"scope is not declared in universe_membership_v1.yaml: {scope!r}")


def _load_scope_config() -> dict[str, object]:
    try:
        payload = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MembershipCaptureError("universe membership scope configuration is unavailable") from exc
    required = {
        "version",
        "allowed_scopes",
        "configured_scope",
        "configured_complete",
        "configured_source_id",
        "listing_complete",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise MembershipCaptureError("universe membership scope configuration is malformed")
    if payload.get("version") != "universe_membership_v1":
        raise MembershipCaptureError("unsupported universe membership scope configuration")
    allowed_scopes = payload.get("allowed_scopes")
    if (
        payload.get("configured_scope") != "configured"
        or not isinstance(allowed_scopes, list)
        or any(not isinstance(item, str) for item in allowed_scopes)
        or payload["configured_scope"] not in allowed_scopes
        or len(set(allowed_scopes)) != len(allowed_scopes)
    ):
        raise MembershipCaptureError("universe membership scope declarations are unsupported")
    for scope in allowed_scopes:
        if scope == payload["configured_scope"]:
            continue
        parts = scope.split(":")
        if len(parts) != 3 or parts[0] != "listing" or not all(
            _SCOPE_PART.fullmatch(item) for item in parts[1:]
        ):
            raise MembershipCaptureError("universe membership scope declarations are unsupported")
    if not isinstance(payload.get("configured_complete"), bool) or not isinstance(payload.get("listing_complete"), bool):
        raise MembershipCaptureError("scope completeness declarations must be booleans")
    if not payload["configured_complete"] or not payload["listing_complete"]:
        raise MembershipCaptureError("declared capture scopes must be complete")
    source_id = payload.get("configured_source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise MembershipCaptureError("configured source identifier is missing")
    return dict(payload)


def _utc_timestamp(value: object, label: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        if label == "known_at" or label == "as_known_at":
            raise MembershipCaptureError(f"{label} must include a timezone-aware time")
        parsed = datetime.combine(value, time.min, tzinfo=timezone.utc)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MembershipCaptureError(f"{label} must be an ISO timestamp") from exc
    else:
        raise MembershipCaptureError(f"{label} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MembershipCaptureError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _date_text(value: object, label: str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise MembershipCaptureError(f"{label} must be an ISO date") from exc
    raise MembershipCaptureError(f"{label} must be an ISO date")


def _optional_date_text(value: object, label: str) -> str | None:
    return None if value is None or value == "" else _date_text(value, label)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MembershipCaptureError(f"{label} must be a non-empty string")
    return value.strip()


def _store_raw_payload(payload: bytes, checksum: str, root: Path) -> str:
    raw_root = root / _RAW_RELATIVE_PATH
    path = raw_root / f"{checksum}.payload.gz"
    if path.is_file():
        existing = load_raw_payload(checksum, root=root)
        if existing != payload:
            raise MembershipCaptureError("content-addressed raw payload checksum collision")
        return path.relative_to(root).as_posix()
    compressed = gzip.compress(payload, mtime=0)

    def validate(candidate: Path) -> None:
        decoded = gzip.decompress(candidate.read_bytes())
        if hashlib.sha256(decoded).hexdigest() != checksum or decoded != payload:
            raise MembershipCaptureError("compressed raw payload failed byte-exact validation")

    atomic_write_bytes(path, compressed, validate)
    return path.relative_to(root).as_posix()


def _connect(path: Path, *, create: bool) -> sqlite3.Connection:
    if not create and not path.is_file():
        raise MembershipCaptureError("membership store is unavailable")
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version not in {0, 1}:
        connection.close()
        raise MembershipCaptureError(f"unsupported membership store schema version: {version}")
    if version == 0 and create:
        connection.executescript(
            "CREATE TABLE IF NOT EXISTS capture_log ("
            "capture_id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_date TEXT NOT NULL, scope TEXT NOT NULL, "
            "source TEXT NOT NULL, source_id TEXT NOT NULL, checksum TEXT NOT NULL, complete INTEGER NOT NULL, "
            "known_at TEXT NOT NULL, row_count INTEGER NOT NULL, raw_path TEXT NOT NULL, "
            "source_kind TEXT NOT NULL, licence_ref TEXT);"
            "CREATE TABLE IF NOT EXISTS interval_revisions ("
            "revision_id INTEGER PRIMARY KEY AUTOINCREMENT, interval_id TEXT NOT NULL, scope TEXT NOT NULL, "
            "instrument_id TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT, known_at TEXT NOT NULL, "
            "source TEXT NOT NULL, source_id TEXT NOT NULL, source_kind TEXT NOT NULL, capture_id INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS licensed_imports ("
            "import_id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, licence_ref TEXT NOT NULL, "
            "checksum TEXT NOT NULL, row_count INTEGER NOT NULL, raw_path TEXT NOT NULL, imported_at TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS licensed_history ("
            "history_id INTEGER PRIMARY KEY AUTOINCREMENT, interval_id TEXT NOT NULL, scope TEXT NOT NULL, "
            "instrument_id TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT, known_at TEXT NOT NULL, "
            "snapshot_date TEXT NOT NULL, complete INTEGER NOT NULL, source TEXT NOT NULL CHECK(source='licensed'), "
            "source_id TEXT NOT NULL, licence_ref TEXT NOT NULL, checksum TEXT NOT NULL, import_id INTEGER NOT NULL);"
            "CREATE INDEX IF NOT EXISTS capture_scope_date_known ON capture_log(scope, source_kind, snapshot_date, known_at);"
            "CREATE INDEX IF NOT EXISTS interval_scope_known_id ON interval_revisions(scope, source_kind, interval_id, known_at);"
            "CREATE INDEX IF NOT EXISTS licensed_scope_date_known ON licensed_history(scope, snapshot_date, known_at);"
            "CREATE TRIGGER IF NOT EXISTS capture_log_no_update BEFORE UPDATE ON capture_log "
            "BEGIN SELECT RAISE(ABORT, 'capture_log is append-only'); END;"
            "CREATE TRIGGER IF NOT EXISTS capture_log_no_delete BEFORE DELETE ON capture_log "
            "BEGIN SELECT RAISE(ABORT, 'capture_log is append-only'); END;"
            "CREATE TRIGGER IF NOT EXISTS interval_revisions_no_update BEFORE UPDATE ON interval_revisions "
            "BEGIN SELECT RAISE(ABORT, 'interval_revisions is append-only'); END;"
            "CREATE TRIGGER IF NOT EXISTS interval_revisions_no_delete BEFORE DELETE ON interval_revisions "
            "BEGIN SELECT RAISE(ABORT, 'interval_revisions is append-only'); END;"
            "CREATE TRIGGER IF NOT EXISTS licensed_imports_no_update BEFORE UPDATE ON licensed_imports "
            "BEGIN SELECT RAISE(ABORT, 'licensed_imports is append-only'); END;"
            "CREATE TRIGGER IF NOT EXISTS licensed_imports_no_delete BEFORE DELETE ON licensed_imports "
            "BEGIN SELECT RAISE(ABORT, 'licensed_imports is append-only'); END;"
            "CREATE TRIGGER IF NOT EXISTS licensed_history_no_update BEFORE UPDATE ON licensed_history "
            "BEGIN SELECT RAISE(ABORT, 'licensed_history is append-only'); END;"
            "CREATE TRIGGER IF NOT EXISTS licensed_history_no_delete BEFORE DELETE ON licensed_history "
            "BEGIN SELECT RAISE(ABORT, 'licensed_history is append-only'); END;"
            "PRAGMA user_version=1;"
        )
    elif create:
        connection.executescript(
            "CREATE INDEX IF NOT EXISTS capture_scope_date_known ON capture_log(scope, source_kind, snapshot_date, known_at);"
            "CREATE INDEX IF NOT EXISTS interval_scope_known_id ON interval_revisions(scope, source_kind, interval_id, known_at);"
            "CREATE INDEX IF NOT EXISTS licensed_scope_date_known ON licensed_history(scope, snapshot_date, known_at);"
        )
    return connection


def _ensure_catalogue(root: Path) -> DataCatalogue:
    catalogue = DataCatalogue(root)
    definitions = (
        DatasetDefinition(
            dataset_id=_RAW_DATASET_ID,
            layer="raw",
            schema={"checksum": "sha256", "known_at": "utc timestamp", "row_count": "integer", "scope": "string", "source_id": "string"},
            owner="etf_cockpit",
            source_id="universe_membership_recorder",
            licence="unknown",
            update_schedule="on_capture",
            canonical_path=_RAW_RELATIVE_PATH.as_posix(),
        ),
        DatasetDefinition(
            dataset_id=_PROCESSED_DATASET_ID,
            layer="derived",
            schema={"instrument_id": "string", "known_at": "utc timestamp", "scope": "string", "valid_from": "date", "valid_to": "date|null"},
            owner="etf_cockpit",
            source_id="universe_membership_recorder",
            licence="unknown",
            update_schedule="on_capture",
            canonical_path=_DB_RELATIVE_PATH.as_posix(),
        ),
    )
    for definition in definitions:
        catalogue.register_dataset(definition)
    return catalogue


def _register_raw_snapshot(catalogue: DataCatalogue, checksum: str, row_count: int) -> DatasetSnapshot:
    definition = next(item for item in catalogue.datasets if item.dataset_id == _RAW_DATASET_ID)
    snapshot_id = f"{_RAW_DATASET_ID}:{checksum[:24]}:{definition.schema_sha256[:16]}"
    return catalogue.register_snapshot(
        DatasetSnapshot(
            dataset_id=_RAW_DATASET_ID,
            snapshot_id=snapshot_id,
            content_sha256=checksum,
            schema_sha256=definition.schema_sha256,
            row_count=row_count,
            captured_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
    )


def _register_processed_snapshot(
    catalogue: DataCatalogue,
    rows: list[Mapping[str, object]],
    raw_snapshot_id: str,
    captured_at: str,
    *,
    scope: str,
    source: str,
    checksum: str,
    raw_path: str,
) -> DatasetSnapshot:
    return catalogue.register_rows(
        _PROCESSED_DATASET_ID,
        [
            {
                "scope": scope,
                "source": source,
                "checksum": checksum,
                "raw_path": raw_path,
                "processed": dict(row),
            }
            for row in rows
        ],
        schema={"scope": "string", "source": "string", "checksum": "sha256", "processed": "membership record"},
        dependency_snapshot_ids=(raw_snapshot_id,),
        captured_at=captured_at,
    )


__all__ = [
    "CaptureStatus",
    "LicensedImportStatus",
    "MembershipCaptureError",
    "capture_log",
    "closure_events",
    "get_configured_capture_status",
    "import_licensed_history",
    "load_raw_payload",
    "membership_frame",
    "membership_intervals",
    "record_configured_capture",
    "record_listing_capture",
]
