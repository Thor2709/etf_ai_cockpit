"""Versioned local persistence and safe CSV export for screener queries."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import csv
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import re
import time

from etf_cockpit.application.screening import ScreenQuery, ScreenResult
from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.paths import DATA_DIR


SCREENS_DIR = DATA_DIR / "screens"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,79}$")
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def save_screen(
    name: str,
    query: ScreenQuery,
    *,
    directory: Path = SCREENS_DIR,
) -> Path:
    """Save an immutable numbered query revision and return its path."""

    screen_dir = _screen_directory(name, directory)
    screen_dir.mkdir(parents=True, exist_ok=True)
    with _revision_lock(screen_dir):
        existing = _revision_paths(screen_dir)
        revision = (int(existing[-1].stem) + 1) if existing else 1
        destination = screen_dir / f"{revision:06d}.json"
        if destination.exists():
            raise FileExistsError(f"saved screen revision already exists: {destination}")
        body: dict[str, object] = {
            "schema_version": "1.0",
            "name": name.strip(),
            "revision": revision,
            "query": query.as_dict(),
            "query_checksum": query.checksum,
            "execution_allowed": False,
        }
        body["record_checksum"] = _checksum(body)
        encoded = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        atomic_write_bytes(destination, encoded, _validate_record_file)
    return destination


def load_screen(
    name: str,
    revision: int | None = None,
    *,
    directory: Path = SCREENS_DIR,
) -> ScreenQuery:
    """Load and verify a saved query, failing closed on missing or corrupt state."""

    screen_dir = _screen_directory(name, directory)
    paths = _revision_paths(screen_dir)
    if revision is None:
        if not paths:
            raise FileNotFoundError(f"no saved screen revisions for {name!r}")
        path = paths[-1]
    else:
        if revision < 1:
            raise ValueError("screen revision must be positive")
        path = screen_dir / f"{revision:06d}.json"
    payload = _read_record(path)
    expected_revision = int(path.stem)
    if payload.get("name") != name.strip() or payload.get("revision") != expected_revision:
        raise ValueError("saved screen envelope does not match its requested name and revision")
    query_payload = payload.get("query")
    if not isinstance(query_payload, Mapping):
        raise ValueError("saved screen query is missing")
    query = ScreenQuery.from_dict(query_payload)
    if payload.get("query_checksum") != query.checksum:
        raise ValueError("saved screen query checksum mismatch")
    return query


def list_saved_screens(*, directory: Path = SCREENS_DIR) -> tuple[str, ...]:
    if not directory.is_dir():
        return ()
    names: list[str] = []
    for path in directory.iterdir():
        revisions = _revision_paths(path) if path.is_dir() else []
        if not revisions:
            continue
        try:
            payload = _read_record(revisions[-1])
        except ValueError:
            continue
        name = payload.get("name")
        if isinstance(name, str):
            names.append(name)
    return tuple(sorted(names, key=str.casefold))


def export_screen_csv(
    result: ScreenResult,
    query: ScreenQuery,
    destination: Path,
) -> Path:
    """Atomically export visible results with reproducibility lineage."""

    if destination.suffix.casefold() != ".csv":
        raise ValueError("screen export destination must use .csv")
    if result.query_checksum != query.checksum:
        raise ValueError("screen result does not match the export query")
    if query.input_checksum == "unavailable" or result.input_checksum != query.input_checksum:
        raise ValueError("screen result does not match the query input dataset")
    lineage = {
        "screen_query_checksum": query.checksum,
        "screen_input_checksum": query.input_checksum,
        "screen_as_of": query.as_of,
        "screen_universe_revision": query.universe_revision,
        "screen_formula_version": query.formula_version,
        "screen_formula_checksum": query.formula_checksum,
        "screen_dataset_checksums": json.dumps(dict(query.dataset_checksums), sort_keys=True, separators=(",", ":")),
        "screen_query_json": json.dumps(query.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "screen_execution_allowed": False,
    }
    row_fields = sorted({str(field) for row in result.rows for field in row})
    header_map = {field: str(_safe_csv_cell(field)) for field in row_fields}
    fields = [*header_map.values(), *lineage]
    if len(fields) != len(set(fields)):
        raise ValueError("screen export columns are ambiguous after safety normalisation")
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in result.rows:
        writer.writerow(
            {
                **{header_map[field]: _safe_csv_cell(row.get(field)) for field in row_fields},
                **{key: _safe_csv_cell(value) for key, value in lineage.items()},
            }
        )
    payload = buffer.getvalue().encode("utf-8")
    atomic_write_bytes(destination, payload, _validate_csv)
    return destination


def _screen_directory(name: str, directory: Path) -> Path:
    cleaned = str(name).strip()
    if not _SAFE_NAME.fullmatch(cleaned):
        raise ValueError("screen name must contain only letters, numbers, spaces, '_' or '-'")
    slug = "screen-" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:24]
    root = directory.resolve()
    destination = (root / slug).resolve()
    if destination.parent != root:
        raise ValueError("screen name escapes the screen store")
    return destination


def _revision_paths(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.glob("[0-9][0-9][0-9][0-9][0-9][0-9].json")
        if path.stem.isdigit()
    )


def _checksum(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_record(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("saved screen exceeds the size limit")
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"saved screen is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("saved screen must be a JSON object")
    expected = {"schema_version", "name", "revision", "query", "query_checksum", "execution_allowed", "record_checksum"}
    if set(payload) != expected or payload.get("schema_version") != "1.0":
        raise ValueError("saved screen envelope schema is invalid")
    if not isinstance(payload.get("name"), str) or type(payload.get("revision")) is not int:
        raise ValueError("saved screen name and revision have invalid types")
    recorded = payload.pop("record_checksum", None)
    if not isinstance(recorded, str) or not _SHA256.fullmatch(recorded) or recorded != _checksum(payload):
        raise ValueError("saved screen record checksum mismatch")
    payload["record_checksum"] = recorded
    if payload.get("execution_allowed") is not False:
        raise ValueError("saved screen must not grant execution authority")
    query_checksum = payload.get("query_checksum")
    if not isinstance(query_checksum, str) or not _SHA256.fullmatch(query_checksum):
        raise ValueError("saved screen query checksum is invalid")
    return payload


def _validate_record_file(path: Path) -> None:
    payload = _read_record(path)
    query_payload = payload.get("query")
    if not isinstance(query_payload, Mapping):
        raise ValueError("saved screen query is missing")
    query = ScreenQuery.from_dict(query_payload)
    if payload.get("query_checksum") != query.checksum:
        raise ValueError("saved screen query checksum mismatch")


@contextmanager
def _revision_lock(directory: Path):
    lock = directory / ".revision.lock"
    deadline = time.monotonic() + 5.0
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for saved screen revision lock: {lock}")
            time.sleep(0.01)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock.unlink(missing_ok=True)


def _safe_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _validate_csv(path: Path) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            for cell in row:
                stripped = cell.lstrip()
                if stripped.startswith(_FORMULA_PREFIXES):
                    raise ValueError("unsafe spreadsheet formula cell in screen export")


__all__ = [
    "SCREENS_DIR",
    "export_screen_csv",
    "list_saved_screens",
    "load_screen",
    "save_screen",
]
