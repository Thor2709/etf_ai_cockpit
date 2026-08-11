"""Local-first watchlist and universe import validation.

This module deliberately stops at a dry-run boundary.  It accepts source rows,
maps only explicit identity evidence, and returns a reproducible manifest.  It
does not call providers, scoring, workflows, or broker adapters.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
from typing import Iterable, Mapping
from xml.etree import ElementTree
from zipfile import ZipFile

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, atomic_write_json
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.universe_store import UniverseRecord, is_valid_isin, support_decision


IMPORT_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
RESUME_SCHEMA_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SOURCE_KINDS = frozenset({"csv", "xlsx", "paste", "provider"})
_ISSUE_SEVERITIES = frozenset({"error", "warning"})
_ISSUE_CODES = frozenset(
    {"unresolved_identity", "delisted", "inactive", "unsupported", "secondary_line", "duplicate"}
)
_MAPPING_CONFIDENCE = frozenset(
    {
        "canonical_id",
        "verified_isin",
        "ticker_mic",
        "provider_symbol",
        "ticker_unique",
        "ticker_ambiguous",
        "ticker_unresolved",
        "missing_identity",
    }
)
_ROW_CLASSIFICATIONS = frozenset(
    {"resolved", "duplicate", "secondary_line", "unsupported", "inactive", "delisted", "unresolved"}
)
_RESUME_STATUSES = frozenset({"pending", "paused", "cancelled", "complete"})
_XLSX_MAX_INPUT_BYTES = 32 * 1024 * 1024
_XLSX_MAX_ZIP_ENTRIES = 2_048
_XLSX_MAX_TOTAL_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_XLSX_MAX_MEMBER_BYTES = 16 * 1024 * 1024
_XLSX_MAX_ROWS = 100_000
_XLSX_MAX_COLUMNS = 512
_XLSX_MAX_CELLS = 1_000_000


@dataclass(frozen=True)
class ImportIssue:
    row_number: int
    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class UniverseImportReport:
    source_kind: str
    source_name: str
    source_checksum: str
    source_rows: tuple[Mapping[str, str], ...]
    records: tuple[UniverseRecord, ...]
    issues: tuple[ImportIssue, ...]
    mapping_confidence: Mapping[int, str]
    duplicate_rows: tuple[int, ...] = ()
    secondary_line_rows: tuple[int, ...] = ()
    unsupported_rows: tuple[int, ...] = ()
    inactive_rows: tuple[int, ...] = ()
    delisted_rows: tuple[int, ...] = ()
    unresolved_rows: tuple[int, ...] = ()
    correction_overlays: Mapping[int, Mapping[str, str]] = ()
    execution_allowed: bool = False

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def warnings(self) -> tuple[ImportIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def errors(self) -> tuple[ImportIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def candidates(self) -> tuple[UniverseRecord, ...]:
        """Records which are safe to stage after the dry-run is reviewed."""

        return self.records


@dataclass(frozen=True)
class UniverseManifest:
    manifest_id: str
    source_kind: str
    source_name: str
    source_checksum: str
    source_rows: tuple[Mapping[str, str], ...]
    records: tuple[UniverseRecord, ...]
    mapping_confidence: Mapping[int, str]
    issues: tuple[ImportIssue, ...]
    row_classifications: Mapping[int, tuple[str, ...]]
    exclusions: tuple[Mapping[str, object], ...]
    requested_horizons: Mapping[str, int]
    per_asset_quotas: Mapping[str, int]
    correction_overlays: Mapping[int, Mapping[str, str]]
    schema_version: int = MANIFEST_SCHEMA_VERSION
    execution_allowed: bool = False


@dataclass(frozen=True)
class ManifestSaveResult:
    path: Path
    snapshot_path: Path
    manifest_id: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class ImportResumeState:
    job_id: str
    source_checksum: str
    total_rows: int
    next_row: int = 0
    chunk_size: int = 100
    status: str = "pending"
    schema_version: int = RESUME_SCHEMA_VERSION
    execution_allowed: bool = False
    report_digest: str = ""

    @property
    def complete(self) -> bool:
        return self.next_row >= self.total_rows and self.status == "complete"


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _text(value).casefold()).strip("_")


def _field(row: Mapping[str, object], *names: str) -> str:
    values = {_header(key): value for key, value in row.items()}
    for name in names:
        value = values.get(_header(name))
        if value is not None and _text(value):
            return _text(value)
    return ""


def _strict_mapping(
    items: Iterable[tuple[object, object]],
    *,
    source_label: str,
    stringify_values: bool,
) -> dict[str, object]:
    result: dict[str, object] = {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in items:
        key = str(raw_key)
        semantic_key = _header(key)
        if semantic_key in normalized:
            raise ValueError(
                f"{source_label} contains normalized key collision: "
                f"{normalized[semantic_key]} / {key}"
            )
        normalized[semantic_key] = key
        result[key] = _text(raw_value) if stringify_values else raw_value
    return result


def _decode_json(text: str, *, source_label: str) -> object:
    def reject_collisions(pairs: list[tuple[str, object]]) -> dict[str, object]:
        raw_keys: set[str] = set()
        for key, _value in pairs:
            if key in raw_keys:
                raise ValueError(f"duplicate {source_label} JSON key: {key}")
            raw_keys.add(key)
        return _strict_mapping(
            pairs,
            source_label=f"{source_label} JSON object",
            stringify_values=False,
        )

    return json.loads(text, object_pairs_hook=reject_collisions)


def _validate_unique_headers(headers: Iterable[object], source_label: str) -> list[str]:
    values = [_text(value) or f"column_{index + 1}" for index, value in enumerate(headers)]
    seen: set[str] = set()
    for value in values:
        normalized = _header(value)
        if normalized in seen:
            raise ValueError(f"duplicate {source_label} header: {value}")
        seen.add(normalized)
    return values


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "on", "active", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "inactive", "disabled"}:
        return False
    return None


def _strict_boolean_field(row: Mapping[str, object], *names: str) -> bool | None:
    values = {_header(key): value for key, value in row.items()}
    selected: bool | None = None
    for name in names:
        value = values.get(_header(name))
        if value is None or not _text(value):
            continue
        parsed = _as_bool(value)
        if parsed is None:
            raise ValueError(f"{name} must be a recognized boolean value")
        if selected is None:
            selected = parsed
        elif selected is not parsed:
            raise ValueError(f"conflicting boolean aliases for {names[0]}")
    return selected


def _decode_bytes(payload: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("source is not a supported text encoding")


def _rows_from_csv_text(text: str) -> tuple[Mapping[str, str], ...]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return ()
    headers = _validate_unique_headers(rows[0], "CSV")
    if len(rows) == 1:
        return ()
    return tuple(
        {headers[index]: cells[index].strip() if index < len(cells) else "" for index in range(len(headers))}
        for cells in rows[1:]
        if any(_text(cell) for cell in cells)
    )


def _xlsx_cell_value(cell: ElementTree.Element, shared: list[str]) -> str:
    value = cell.find("{*}v")
    inline = cell.find("{*}is/{*}t")
    if inline is not None:
        return inline.text or ""
    if value is None or value.text is None:
        return ""
    raw = value.text
    if cell.attrib.get("t") == "s":
        try:
            return shared[int(raw)]
        except (IndexError, ValueError):
            return ""
    return raw


def _xlsx_column_number(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference.upper())
    if not letters:
        return 0
    column = 0
    for char in letters.group(1):
        column = column * 26 + ord(char) - 64
    return column


def _read_xlsx_member(archive: ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size < 0 or info.file_size > _XLSX_MAX_MEMBER_BYTES:
        raise ValueError(f"XLSX ZIP member is too large: {name}")
    return archive.read(info)


def _validate_xlsx_sheet_limits(root: ElementTree.Element) -> None:
    dimension = root.find("{*}dimension")
    if dimension is not None:
        reference = dimension.attrib.get("ref", "")
        match = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", reference.upper())
        if match:
            end_column = _xlsx_column_number(match.group(3) or match.group(1))
            end_row = int(match.group(4) or match.group(2))
            if end_row > _XLSX_MAX_ROWS or end_column > _XLSX_MAX_COLUMNS:
                raise ValueError("XLSX sheet exceeds row or column limits")
    row_elements = root.findall(".//{*}row")
    if len(row_elements) > _XLSX_MAX_ROWS:
        raise ValueError("XLSX sheet exceeds row limit")
    cell_count = 0
    for index, row in enumerate(row_elements, start=1):
        row_number = int(row.attrib.get("r", index))
        if row_number < 1 or row_number > _XLSX_MAX_ROWS:
            raise ValueError("XLSX row is outside the supported range")
        cells = row.findall("{*}c")
        if len(cells) > _XLSX_MAX_COLUMNS:
            raise ValueError("XLSX row exceeds column limit")
        cell_count += len(cells)
        if cell_count > _XLSX_MAX_CELLS:
            raise ValueError("XLSX sheet exceeds cell limit")
        if any(_xlsx_column_number(cell.attrib.get("r", "")) > _XLSX_MAX_COLUMNS for cell in cells):
            raise ValueError("XLSX cell is outside the supported column range")


def _rows_from_xlsx_bytes(payload: bytes) -> tuple[Mapping[str, str], ...]:
    if len(payload) > _XLSX_MAX_INPUT_BYTES:
        raise ValueError("XLSX input exceeds byte limit")
    with ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > _XLSX_MAX_ZIP_ENTRIES:
            raise ValueError("XLSX ZIP exceeds entry-count limit")
        total_uncompressed = sum(info.file_size for info in entries)
        if total_uncompressed < 0 or total_uncompressed > _XLSX_MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("XLSX ZIP exceeds cumulative uncompressed byte limit")
        for info in entries:
            if info.file_size < 0 or info.file_size > _XLSX_MAX_MEMBER_BYTES:
                raise ValueError(f"XLSX ZIP member is too large: {info.filename}")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(_read_xlsx_member(archive, "xl/sharedStrings.xml"))
            items = root.findall("{*}si")
            if len(items) > _XLSX_MAX_CELLS:
                raise ValueError("XLSX shared-string table exceeds cell limit")
            for item in items:
                shared.append("".join(text.text or "" for text in item.findall(".//{*}t")))
        workbook = ElementTree.fromstring(_read_xlsx_member(archive, "xl/workbook.xml"))
        relation_root = ElementTree.fromstring(_read_xlsx_member(archive, "xl/_rels/workbook.xml.rels"))
        relations = {
            item.attrib.get("Id"): item.attrib.get("Target", "")
            for item in relation_root
        }
        sheet = workbook.find(".//{*}sheet")
        if sheet is None:
            return ()
        relation_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
        target = relations.get(relation_id, "worksheets/sheet1.xml")
        sheet_path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        root = ElementTree.fromstring(_read_xlsx_member(archive, sheet_path))
        _validate_xlsx_sheet_limits(root)
        matrix: dict[int, dict[int, str]] = {}
        for row in root.findall(".//{*}row"):
            row_number = int(row.attrib.get("r", len(matrix) + 1))
            cells: dict[int, str] = {}
            for cell in row.findall("{*}c"):
                reference = cell.attrib.get("r", "A1")
                column = _xlsx_column_number(reference)
                if not column:
                    continue
                cells[column] = _xlsx_cell_value(cell, shared)
            matrix[row_number] = cells
        if not matrix:
            return ()
        width = max((max(row, default=0) for row in matrix.values()), default=0)
        header_row = matrix[min(matrix)]
        headers = _validate_unique_headers(
            [header_row.get(index, "") or f"column_{index}" for index in range(1, width + 1)],
            "XLSX",
        )
        return tuple(
            {headers[index - 1]: row.get(index, "") for index in range(1, width + 1)}
            for number, row in sorted(matrix.items())
            if number != min(matrix) and any(_text(value) for value in row.values())
        )


def _provider_rows(text: str) -> tuple[Mapping[str, str], ...]:
    decoded = _decode_json(text, source_label="provider")
    if not isinstance(decoded, list) or not all(isinstance(item, Mapping) for item in decoded):
        raise ValueError("provider JSON input must be a list of row objects")
    return tuple(
        _strict_mapping(
            item.items(),
            source_label="supplied provider mapping",
            stringify_values=True,
        )
        for item in decoded
    )


def _coerce_rows(source: object, source_kind: str | None) -> tuple[tuple[Mapping[str, str], ...], str, str, str]:
    to_dict = getattr(source, "to_dict", None)
    if callable(to_dict):
        source = to_dict(orient="records")
    if isinstance(source, Mapping):
        source = [source]
    if isinstance(source, (list, tuple)) and all(isinstance(item, Mapping) for item in source):
        rows = tuple(
            _strict_mapping(
                item.items(),
                source_label="supplied mapping",
                stringify_values=True,
            )
            for item in source
        )
        encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return rows, source_kind or "provider", "supplied-provider-rows", sha256(encoded).hexdigest()
    is_path = isinstance(source, Path)
    if isinstance(source, str) and "\n" not in source and "\r" not in source:
        try:
            is_path = Path(source).exists()
        except OSError:
            is_path = False
    if is_path:
        path = Path(source)
        is_xlsx = path.suffix.casefold() in {".xlsx", ".xlsm"} or source_kind == "xlsx"
        if is_xlsx and path.stat().st_size > _XLSX_MAX_INPUT_BYTES:
            raise ValueError("XLSX input exceeds byte limit")
        payload = path.read_bytes()
        if source_kind == "provider":
            text, _encoding = _decode_bytes(payload)
            rows = _provider_rows(text)
            kind = "provider"
        elif is_xlsx:
            rows = _rows_from_xlsx_bytes(payload)
            kind = source_kind or "xlsx"
        else:
            text, _encoding = _decode_bytes(payload)
            rows = _rows_from_csv_text(text)
            kind = source_kind or "csv"
        return rows, kind, path.name, sha256(payload).hexdigest()
    if isinstance(source, bytes):
        if source_kind == "provider":
            text, _encoding = _decode_bytes(source)
            rows = _provider_rows(text)
            return rows, "provider", "supplied-provider-rows", sha256(source).hexdigest()
        if source.startswith(b"PK") or source_kind == "xlsx":
            rows = _rows_from_xlsx_bytes(source)
            return rows, source_kind or "xlsx", "supplied-xlsx", sha256(source).hexdigest()
        text, _encoding = _decode_bytes(source)
        rows = _rows_from_csv_text(text)
        return rows, source_kind or "paste", "pasted-source", sha256(source).hexdigest()
    text = _text(source)
    encoded = text.encode("utf-8")
    if source_kind == "provider":
        rows = _provider_rows(text)
        return rows, "provider", "supplied-provider-rows", sha256(encoded).hexdigest()
    rows = _rows_from_csv_text(text)
    return rows, source_kind or "paste", "pasted-source", sha256(encoded).hexdigest()


def _identity_keys(record: UniverseRecord, provider: str, provider_symbol: str) -> tuple[str, ...]:
    keys = [f"id:{record.instrument_id.casefold()}"] if record.instrument_id else []
    if record.isin and record.isin_status == "verified":
        keys.append(f"isin:{record.isin.casefold()}")
    if provider_symbol:
        keys.append(f"provider:{provider.casefold()}:{provider_symbol.casefold()}")
    if not keys and record.ticker:
        keys.append(f"ticker:{record.ticker.casefold()}")
    return tuple(keys)


def _identity_from_row(
    row: Mapping[str, str],
    *,
    provider_name: str,
    identity_index: Mapping[str, object] | None,
) -> tuple[str, str, str, str, str]:
    canonical_id = _field(row, "canonical_id", "instrument_id", "canonical_instrument_id", "id")
    isin = _field(row, "isin", "verified_isin").upper()
    isin_status = _field(row, "isin_status", "isin_verification_status").casefold()
    ticker = _field(row, "ticker", "exchange_ticker", "local_ticker").upper()
    mic = _field(row, "mic", "mic_code", "market_identifier_code").upper()
    provider_symbol = _field(row, "provider_symbol", "symbol", "provider_ticker")
    provider = _field(row, "provider", "provider_id") or provider_name
    if canonical_id:
        return canonical_id, "canonical_id", ticker, isin, provider_symbol
    if isin and is_valid_isin(isin) and isin_status == "verified":
        return isin, "verified_isin", ticker, isin, provider_symbol
    if ticker and mic:
        return f"{ticker}@{mic}", "ticker_mic", ticker, isin, provider_symbol
    if provider_symbol and provider:
        return f"provider:{provider}:{provider_symbol}", "provider_symbol", ticker, isin, provider_symbol
    if ticker:
        matches = () if identity_index is None else identity_index.get(ticker.casefold(), ())
        if isinstance(matches, str):
            matches = (matches,)
        if isinstance(matches, Mapping):
            matches = tuple(matches)
        if isinstance(matches, Iterable):
            unique = tuple(sorted({_text(item) for item in matches if _text(item)}))
            if len(unique) == 1:
                return unique[0], "ticker_unique", ticker, isin, provider_symbol
            if len(unique) > 1:
                return "", "ticker_ambiguous", ticker, isin, provider_symbol
        return "", "ticker_unresolved", ticker, isin, provider_symbol
    return "", "missing_identity", ticker, isin, provider_symbol


def _identity_mapping_hint(row: Mapping[str, str]) -> str:
    """Describe explicit evidence without resolving identity for excluded rows."""

    if _field(row, "canonical_id", "instrument_id", "canonical_instrument_id", "id"):
        return "canonical_id"
    isin = _field(row, "isin", "verified_isin").upper()
    if isin and is_valid_isin(isin) and _field(row, "isin_status", "isin_verification_status").casefold() == "verified":
        return "verified_isin"
    if _field(row, "ticker", "exchange_ticker", "local_ticker") and _field(
        row, "mic", "mic_code", "market_identifier_code"
    ):
        return "ticker_mic"
    if _field(row, "provider_symbol", "symbol", "provider_ticker"):
        return "provider_symbol"
    if _field(row, "ticker", "exchange_ticker", "local_ticker"):
        return "ticker_unresolved"
    return "missing_identity"


def _report_digest(report: UniverseImportReport) -> str:
    payload = {
        "source_kind": report.source_kind,
        "source_name": report.source_name,
        "source_checksum": report.source_checksum,
        "source_rows": [dict(row) for row in report.source_rows],
        "correction_overlays": {
            str(key): dict(value) for key, value in sorted(report.correction_overlays.items())
        },
        "mapping_confidence": {str(key): value for key, value in sorted(report.mapping_confidence.items())},
        "records": [asdict(record) for record in report.records],
        "issues": [asdict(issue) for issue in report.issues],
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def dry_run_universe_import(
    source: object,
    *,
    source_kind: str | None = None,
    provider_name: str = "",
    identity_index: Mapping[str, object] | None = None,
    correction_overlays: Mapping[int | str, Mapping[str, object]] | None = None,
) -> UniverseImportReport:
    """Parse and validate a local source without any external side effect."""

    rows, kind, source_name, checksum = _coerce_rows(source, source_kind)
    overlays: dict[int, Mapping[str, str]] = {}
    for key, overlay in (correction_overlays or {}).items():
        if not isinstance(key, int | str) or not str(key).isdigit():
            raise ValueError("correction overlay rows must be positive integers")
        row_number = int(key)
        if row_number < 1 or row_number > len(rows):
            raise ValueError("correction overlay row is outside the source rows")
        if not isinstance(overlay, Mapping):
            raise ValueError("correction overlay must be an object")
        overlays[row_number] = _strict_mapping(
            overlay.items(),
            source_label="correction overlay",
            stringify_values=True,
        )
    issues: list[ImportIssue] = []
    records: list[UniverseRecord] = []
    confidence: dict[int, str] = {}
    duplicate_rows: list[int] = []
    secondary_rows: list[int] = []
    unsupported_rows: list[int] = []
    inactive_rows: list[int] = []
    delisted_rows: list[int] = []
    unresolved_rows: list[int] = []
    seen: dict[str, int] = {}
    for row_number, original in enumerate(rows, start=1):
        row = dict(original)
        row.update(overlays.get(row_number, {}))
        row = _strict_mapping(
            row.items(),
            source_label=f"source row {row_number}",
            stringify_values=True,
        )
        active = _strict_boolean_field(row, "active", "is_active")
        delisted = _strict_boolean_field(row, "delisted", "is_delisted")
        leveraged = _strict_boolean_field(row, "leveraged", "is_leveraged")
        inverse = _strict_boolean_field(row, "inverse", "is_inverse")
        enabled = _strict_boolean_field(row, "enabled")
        secondary_line = _strict_boolean_field(row, "secondary_line", "is_secondary_line")
        is_primary = _strict_boolean_field(row, "is_primary", "primary")
        status = _field(row, "status", "lifecycle_status", "state").casefold()
        is_delisted = delisted is True or status == "delisted"
        is_inactive = active is False or status in {"inactive", "closed", "terminated", "delisted"}
        if is_delisted:
            confidence[row_number] = _identity_mapping_hint(row)
            delisted_rows.append(row_number)
            issues.append(ImportIssue(row_number, "delisted", "Delisted row is excluded from the active universe.", "warning"))
            continue
        if is_inactive:
            confidence[row_number] = _identity_mapping_hint(row)
            inactive_rows.append(row_number)
            issues.append(ImportIssue(row_number, "inactive", "Inactive row is excluded from the active universe.", "warning"))
            continue
        instrument_id, mapping, ticker, isin, provider_symbol = _identity_from_row(
            row, provider_name=provider_name, identity_index=identity_index
        )
        confidence[row_number] = mapping
        if not instrument_id or (
            mapping in {"canonical_id", "verified_isin"} and not (ticker or provider_symbol)
        ):
            unresolved_rows.append(row_number)
            issues.append(
                ImportIssue(
                    row_number,
                    "unresolved_identity",
                    "Identity evidence is insufficient, ticker-alone is ambiguous, or the required ticker is missing.",
                )
            )
            continue
        asset_type = _field(row, "asset_type", "instrument_type", "asset_class") or "stock"
        data_policy = _field(row, "data_policy", "frequency", "cadence") or "daily"
        decision = support_decision(asset_type, data_policy, leveraged is True, inverse is True)
        if not decision.supported:
            unsupported_rows.append(row_number)
            issues.append(ImportIssue(row_number, "unsupported", decision.reason, "warning"))
            continue
        line_type = _field(row, "line_type", "listing_type", "share_class_type", "share_class").casefold()
        if (
            line_type in {"secondary", "secondary_line", "non_primary", "false"}
            and line_type != "false"
            or secondary_line is True
            or is_primary is False
        ):
            secondary_rows.append(row_number)
            issues.append(ImportIssue(row_number, "secondary_line", "Secondary listing/share-class line retained for review.", "warning"))
        status_value = "verified" if isin and is_valid_isin(isin) and _field(
            row, "isin_status", "isin_verification_status"
        ).casefold() == "verified" else "needs_verification"
        record = UniverseRecord(
            instrument_id=instrument_id,
            name=_field(row, "name", "security_name", "fund_name") or instrument_id,
            isin=isin or "needs_verification",
            isin_status=status_value,
            ticker=ticker or provider_symbol,
            asset_type=asset_type,
            tier=_field(row, "tier", "analysis_tier") or "secondary",
            group=_field(row, "group", "watchlist", "universe_group"),
            enabled=enabled is not False,
            data_policy=data_policy,
            currency=_field(row, "currency") or "EUR",
            region=_field(row, "region", "country"),
            sector=_field(row, "sector"),
            theme=_field(row, "theme"),
            notes=_field(row, "notes", "description"),
            leveraged=leveraged is True,
            inverse=inverse is True,
        )
        keys = _identity_keys(record, provider_name or _field(row, "provider", "provider_id"), provider_symbol)
        duplicate_key = next((key for key in keys if key in seen), None)
        if duplicate_key is not None:
            duplicate_rows.append(row_number)
            issues.append(ImportIssue(row_number, "duplicate", f"Duplicate identity of source row {seen[duplicate_key]}.", "warning"))
            continue
        for key in keys:
            seen[key] = row_number
        records.append(record)
    return UniverseImportReport(
        kind,
        source_name,
        checksum,
        tuple(dict(row) for row in rows),
        tuple(records),
        tuple(issues),
        dict(confidence),
        tuple(duplicate_rows),
        tuple(secondary_rows),
        tuple(unsupported_rows),
        tuple(inactive_rows),
        tuple(delisted_rows),
        tuple(unresolved_rows),
        overlays,
    )


def validate_universe_import(*args: object, **kwargs: object) -> UniverseImportReport:
    return dry_run_universe_import(*args, **kwargs)


def _validate_options(
    requested_horizons: Mapping[str, int] | None,
    per_asset_quotas: Mapping[str, int] | None,
) -> tuple[dict[str, int], dict[str, int]]:
    if requested_horizons is not None and not isinstance(requested_horizons, Mapping):
        raise ValueError("requested horizons must be an object")
    if per_asset_quotas is not None and not isinstance(per_asset_quotas, Mapping):
        raise ValueError("per-asset quotas must be an object")
    horizons: dict[str, int] = {}
    for key, value in (requested_horizons or {}).items():
        if not isinstance(key, str) or not key.strip() or type(value) is not int or value <= 0:
            raise ValueError("requested horizons must have non-empty names and positive integer days")
        horizons[key.strip()] = value
    quotas: dict[str, int] = {}
    for key, value in (per_asset_quotas or {}).items():
        if not isinstance(key, str) or not key.strip() or type(value) is not int or value < 0:
            raise ValueError("per-asset quotas must have non-empty names and non-negative integers")
        quotas[key.strip()] = value
    return dict(sorted(horizons.items())), dict(sorted(quotas.items()))


def _classifications(report: UniverseImportReport) -> dict[int, tuple[str, ...]]:
    values: dict[int, list[str]] = {row: [] for row in range(1, len(report.source_rows) + 1)}
    issue_classes = {
        "unresolved_identity": "unresolved",
        "delisted": "delisted",
        "inactive": "inactive",
        "unsupported": "unsupported",
        "secondary_line": "secondary_line",
        "duplicate": "duplicate",
    }
    for issue in report.issues:
        classification = issue_classes[issue.code]
        if classification not in values[issue.row_number]:
            values[issue.row_number].append(classification)
    excluded = {"unresolved", "delisted", "inactive", "unsupported", "duplicate"}
    for row_number, classifications in values.items():
        if not excluded.intersection(classifications):
            classifications.insert(0, "resolved")
    return {row: tuple(items) for row, items in values.items()}


def _manifest_body(manifest: UniverseManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "source_kind": manifest.source_kind,
        "source_name": manifest.source_name,
        "source_checksum": manifest.source_checksum,
        "source_rows": [dict(row) for row in manifest.source_rows],
        "records": [asdict(record) for record in manifest.records],
        "mapping_confidence": {str(key): value for key, value in sorted(manifest.mapping_confidence.items())},
        "issues": [asdict(issue) for issue in manifest.issues],
        "row_classifications": {str(key): list(value) for key, value in sorted(manifest.row_classifications.items())},
        "exclusions": [dict(item) for item in manifest.exclusions],
        "requested_horizons": dict(sorted(manifest.requested_horizons.items())),
        "per_asset_quotas": dict(sorted(manifest.per_asset_quotas.items())),
        "correction_overlays": {str(key): dict(value) for key, value in sorted(manifest.correction_overlays.items())},
        "execution_allowed": False,
    }


def build_universe_manifest(
    report: UniverseImportReport,
    *,
    requested_horizons: Mapping[str, int] | None = None,
    per_asset_quotas: Mapping[str, int] | None = None,
) -> UniverseManifest:
    horizons, quotas = _validate_options(requested_horizons, per_asset_quotas)
    exclusions = tuple(
        {"row_number": issue.row_number, "code": issue.code, "message": issue.message, "severity": issue.severity}
        for issue in report.issues
        if issue.code != "secondary_line"
    )
    provisional = UniverseManifest(
        manifest_id="pending",
        source_kind=report.source_kind,
        source_name=report.source_name,
        source_checksum=report.source_checksum,
        source_rows=report.source_rows,
        records=report.records,
        mapping_confidence=dict(report.mapping_confidence),
        issues=report.issues,
        row_classifications=_classifications(report),
        exclusions=exclusions,
        requested_horizons=horizons,
        per_asset_quotas=quotas,
        correction_overlays=report.correction_overlays,
    )
    manifest_id = sha256(json.dumps(_manifest_body(provisional), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return replace(provisional, manifest_id=manifest_id)


def _reject_escaped_manifest_path(root: Path, path: Path) -> None:
    """Reject canonical manifest destinations whose path identity escapes root."""

    absolute_root = Path(os.path.abspath(str(root)))
    absolute_path = Path(os.path.abspath(str(path)))
    try:
        relative = absolute_path.relative_to(absolute_root)
    except ValueError as exc:
        raise ValueError("universe manifest destination escapes the selected root") from exc
    current = absolute_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"universe manifest destination contains a symlink: {current}")
    resolved = absolute_path.resolve(strict=False)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(absolute_path)):
        raise ValueError("universe manifest destination contains a symlink or escaped path")


class _CheckedManifestDestination:
    """Revalidate manifest path identity during atomic destination resolution."""

    def __init__(self, root: Path, path: Path) -> None:
        self._root = root
        self._path = path

    def _check(self) -> None:
        _reject_escaped_manifest_path(self._root, self._path)

    def __fspath__(self) -> str:
        self._check()
        return os.fspath(self._path)

    @property
    def parent(self) -> Path:
        self._check()
        return self._path.parent

    @property
    def name(self) -> str:
        self._check()
        return self._path.name

    def resolve(self, *args: object, **kwargs: object) -> Path:
        self._check()
        return self._path.resolve(*args, **kwargs)


def save_universe_manifest(manifest: UniverseManifest, *, root: Path | None = None) -> ManifestSaveResult:
    root = (root or ROOT).resolve()
    path = root / "configs" / "universe_manifest.json"
    snapshot_path = root / "data" / "snapshots" / "universe_manifests" / f"{manifest.manifest_id}.json"
    _reject_escaped_manifest_path(root, path)
    _reject_escaped_manifest_path(root, snapshot_path)
    payload = {"manifest_id": manifest.manifest_id, **_manifest_body(manifest)}
    _manifest_from_payload(payload)
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def precondition() -> None:
        _reject_escaped_manifest_path(root, path)
        _reject_escaped_manifest_path(root, snapshot_path)

    atomic_write_group(
        (
            AtomicWriteRequest(_CheckedManifestDestination(root, path), encoded, _validate_manifest_file),  # type: ignore[arg-type]
            AtomicWriteRequest(  # type: ignore[arg-type]
                _CheckedManifestDestination(root, snapshot_path),
                encoded,
                _validate_manifest_file,
            ),
        ),
        precondition=precondition,
    )
    return ManifestSaveResult(path, snapshot_path, manifest.manifest_id)


def export_universe_manifest(manifest: UniverseManifest, destination: Path) -> Path:
    destination = Path(destination)
    payload = {"manifest_id": manifest.manifest_id, **_manifest_body(manifest)}
    _manifest_from_payload(payload)
    atomic_write_json(destination, payload)
    return destination


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[object, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"universe manifest {key} must be an object")
    return value


def _strict_rows(value: object, label: str) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, list):
        raise ValueError(f"universe manifest {label} must be a list")
    rows: list[Mapping[str, str]] = []
    for index, row in enumerate(value, start=1):
        if not isinstance(row, Mapping) or any(
            not isinstance(key, str) or not key or not isinstance(item, str)
            for key, item in row.items()
        ):
            raise ValueError(f"universe manifest {label} row {index} is malformed")
        rows.append(dict(row))
    return tuple(rows)


def _strict_row_mapping(
    value: object,
    *,
    label: str,
    row_count: int,
    allowed_values: frozenset[str],
) -> dict[int, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"universe manifest {label} must be an object")
    result: dict[int, str] = {}
    for raw_row, raw_value in value.items():
        if not isinstance(raw_row, str) or not raw_row.isdigit() or not isinstance(raw_value, str):
            raise ValueError(f"universe manifest {label} is malformed")
        row_number = int(raw_row)
        if row_number < 1 or row_number > row_count or raw_value not in allowed_values:
            raise ValueError(f"universe manifest {label} is malformed")
        result[row_number] = raw_value
    if set(result) != set(range(1, row_count + 1)):
        raise ValueError(f"universe manifest {label} must cover every source row")
    return result


def _strict_issue(value: object, row_count: int) -> ImportIssue:
    if not isinstance(value, Mapping) or set(value) != {"row_number", "code", "message", "severity"}:
        raise ValueError("universe manifest issue is malformed")
    row_number = value.get("row_number")
    code = value.get("code")
    message = value.get("message")
    severity = value.get("severity")
    if (
        type(row_number) is not int
        or row_number < 1
        or row_number > row_count
        or not isinstance(code, str)
        or code not in _ISSUE_CODES
        or not isinstance(message, str)
        or not message
        or not isinstance(severity, str)
        or severity not in _ISSUE_SEVERITIES
    ):
        raise ValueError("universe manifest issue is malformed")
    return ImportIssue(row_number, code, message, severity)


def _manifest_from_payload(payload: Mapping[str, object]) -> UniverseManifest:
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported universe manifest schema")
    if payload.get("execution_allowed") is not False or type(payload.get("execution_allowed")) is not bool:
        raise ValueError("universe manifest execution_allowed must be exactly false")
    manifest_id = payload.get("manifest_id")
    source_kind = payload.get("source_kind")
    source_name = payload.get("source_name")
    source_checksum = payload.get("source_checksum")
    if not isinstance(manifest_id, str) or not _SHA256.fullmatch(manifest_id):
        raise ValueError("universe manifest ID is malformed")
    if not isinstance(source_checksum, str) or not _SHA256.fullmatch(source_checksum):
        raise ValueError("universe manifest source checksum is malformed")
    if not isinstance(source_kind, str) or source_kind not in _SOURCE_KINDS:
        raise ValueError("universe manifest source kind is unsupported")
    if not isinstance(source_name, str) or not source_name:
        raise ValueError("universe manifest source name is required")
    source_rows = _strict_rows(payload.get("source_rows"), "source_rows")
    row_count = len(source_rows)
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("universe manifest records must be a list")
    record_fields = set(asdict(UniverseRecord("", "")))
    records: list[UniverseRecord] = []
    for index, item in enumerate(raw_records, start=1):
        if not isinstance(item, Mapping) or set(item) != record_fields:
            raise ValueError(f"universe manifest record {index} is malformed")
        if any(type(item[field]) is not bool for field in ("enabled", "leveraged", "inverse")):
            raise ValueError(f"universe manifest record {index} safety flags are malformed")
        if any(not isinstance(item[field], str) for field in record_fields - {"enabled", "leveraged", "inverse"}):
            raise ValueError(f"universe manifest record {index} fields are malformed")
        records.append(UniverseRecord(**item))
    mapping_confidence = _strict_row_mapping(
        payload.get("mapping_confidence"),
        label="mapping_confidence",
        row_count=row_count,
        allowed_values=_MAPPING_CONFIDENCE,
    )
    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list):
        raise ValueError("universe manifest issues must be a list")
    issues = tuple(_strict_issue(item, row_count) for item in raw_issues)
    raw_classifications = payload.get("row_classifications")
    if not isinstance(raw_classifications, Mapping):
        raise ValueError("universe manifest row_classifications must be an object")
    row_classifications: dict[int, tuple[str, ...]] = {}
    for raw_row, raw_values in raw_classifications.items():
        if (
            not isinstance(raw_row, str)
            or not raw_row.isdigit()
            or not isinstance(raw_values, list)
            or not raw_values
            or any(not isinstance(item, str) or item not in _ROW_CLASSIFICATIONS for item in raw_values)
            or len(set(raw_values)) != len(raw_values)
        ):
            raise ValueError("universe manifest row_classifications is malformed")
        row_classifications[int(raw_row)] = tuple(raw_values)
    if set(row_classifications) != set(range(1, row_count + 1)):
        raise ValueError("universe manifest row_classifications must cover every source row")
    raw_exclusions = payload.get("exclusions")
    if not isinstance(raw_exclusions, list):
        raise ValueError("universe manifest exclusions must be a list")
    exclusions = tuple(dict(item) for item in raw_exclusions if isinstance(item, Mapping))
    if len(exclusions) != len(raw_exclusions):
        raise ValueError("universe manifest exclusion is malformed")
    expected_exclusions = tuple(asdict(issue) for issue in issues if issue.code != "secondary_line")
    if exclusions != expected_exclusions:
        raise ValueError("universe manifest exclusions are inconsistent with issues")
    overlays_raw = _required_mapping(payload, "correction_overlays")
    overlays: dict[int, Mapping[str, str]] = {}
    for raw_row, overlay in overlays_raw.items():
        if (
            not isinstance(raw_row, str)
            or not raw_row.isdigit()
            or int(raw_row) < 1
            or int(raw_row) > row_count
            or not isinstance(overlay, Mapping)
            or any(not isinstance(key, str) or not key or not isinstance(value, str) for key, value in overlay.items())
        ):
            raise ValueError("universe manifest correction overlay is malformed")
        overlays[int(raw_row)] = dict(overlay)
    horizons, quotas = _validate_options(
        _required_mapping(payload, "requested_horizons"),
        _required_mapping(payload, "per_asset_quotas"),
    )
    body = UniverseManifest(
        manifest_id=manifest_id,
        source_kind=source_kind,
        source_name=source_name,
        source_checksum=source_checksum,
        source_rows=source_rows,
        records=tuple(records),
        mapping_confidence=mapping_confidence,
        issues=issues,
        row_classifications=row_classifications,
        exclusions=exclusions,
        requested_horizons=horizons,
        per_asset_quotas=quotas,
        correction_overlays=overlays,
    )
    expected_classes = _classifications(
        UniverseImportReport(
            body.source_kind,
            body.source_name,
            body.source_checksum,
            body.source_rows,
            body.records,
            body.issues,
            body.mapping_confidence,
        )
    )
    if body.row_classifications != expected_classes:
        raise ValueError("universe manifest row classifications are inconsistent with issues")
    if sum("resolved" in values for values in body.row_classifications.values()) != len(body.records):
        raise ValueError("universe manifest resolved row count is inconsistent with records")
    expected = sha256(json.dumps(_manifest_body(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    if not _SHA256.fullmatch(body.manifest_id) or expected != body.manifest_id:
        raise ValueError("universe manifest checksum mismatch")
    return body


def _validate_manifest_file(path: Path) -> None:
    payload = _decode_json(path.read_text(encoding="utf-8"), source_label="manifest")
    if not isinstance(payload, Mapping):
        raise ValueError("universe manifest root must be an object")
    _manifest_from_payload(payload)


def load_universe_manifest(root: Path | None = None) -> UniverseManifest:
    path = (root or ROOT).resolve() / "configs" / "universe_manifest.json"
    payload = _decode_json(path.read_text(encoding="utf-8"), source_label="manifest")
    if not isinstance(payload, Mapping):
        raise ValueError("universe manifest root must be an object")
    return _manifest_from_payload(payload)


def create_import_resume_state(report: UniverseImportReport, *, job_id: str | None = None, chunk_size: int = 100) -> ImportResumeState:
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = _report_digest(report)
    identifier = job_id or sha256(f"{report.source_checksum}:{digest}".encode("utf-8")).hexdigest()
    state = ImportResumeState(
        identifier,
        report.source_checksum,
        len(report.records),
        chunk_size=chunk_size,
        report_digest=digest,
    )
    _validate_resume_state(state)
    return state


def resume_universe_import(
    report: UniverseImportReport,
    state: ImportResumeState,
    *,
    max_rows: int | None = None,
    cancel: bool = False,
) -> tuple[tuple[UniverseRecord, ...], ImportResumeState]:
    _validate_resume_state(state)
    if (
        state.source_checksum != report.source_checksum
        or state.total_rows != len(report.records)
        or state.report_digest != _report_digest(report)
    ):
        raise ValueError("resume state does not match the import source")
    if cancel:
        if state.status == "complete":
            raise ValueError("completed import cannot be cancelled")
        if state.status == "cancelled":
            raise ValueError("cancelled import must be restarted with a new dry-run")
        return (), replace(state, status="cancelled")
    if state.status == "cancelled":
        raise ValueError("cancelled import must be restarted with a new dry-run")
    limit = state.chunk_size if max_rows is None else max_rows
    if type(limit) is not int or limit <= 0:
        raise ValueError("max_rows must be positive")
    start = state.next_row
    end = min(state.total_rows, start + limit)
    next_state = replace(state, next_row=end, status="complete" if end == state.total_rows else "paused")
    return report.records[start:end], next_state


def resume_import(*args: object, **kwargs: object) -> tuple[tuple[UniverseRecord, ...], ImportResumeState]:
    return resume_universe_import(*args, **kwargs)


def save_import_resume_state(state: ImportResumeState, destination: Path) -> Path:
    _validate_resume_state(state)
    payload = asdict(state)
    atomic_write_json(Path(destination), payload)
    return Path(destination)


def _validate_resume_state(state: ImportResumeState) -> None:
    if type(state.schema_version) is not int or state.schema_version != RESUME_SCHEMA_VERSION:
        raise ValueError("unsupported import resume schema")
    if state.execution_allowed is not False or type(state.execution_allowed) is not bool:
        raise ValueError("import resume execution_allowed must be exactly false")
    if not isinstance(state.job_id, str) or not _JOB_ID.fullmatch(state.job_id):
        raise ValueError("invalid import resume job_id")
    if not isinstance(state.source_checksum, str) or not _SHA256.fullmatch(state.source_checksum):
        raise ValueError("invalid import resume source checksum")
    if not isinstance(state.report_digest, str) or not _SHA256.fullmatch(state.report_digest):
        raise ValueError("invalid import resume report digest")
    if (
        type(state.total_rows) is not int
        or type(state.next_row) is not int
        or type(state.chunk_size) is not int
        or state.total_rows < 0
        or state.next_row < 0
        or state.next_row > state.total_rows
        or state.chunk_size <= 0
    ):
        raise ValueError("invalid import resume counts")
    if not isinstance(state.status, str) or state.status not in _RESUME_STATUSES:
        raise ValueError("invalid import resume status")
    if state.status == "pending" and state.next_row != 0:
        raise ValueError("pending import resume state must start at row zero")
    if state.status == "complete" and state.next_row != state.total_rows:
        raise ValueError("complete import resume state must cover every row")
    if state.status == "paused" and state.next_row >= state.total_rows:
        raise ValueError("paused import resume state must have rows remaining")


def load_import_resume_state(path: Path) -> ImportResumeState:
    payload = _decode_json(Path(path).read_text(encoding="utf-8"), source_label="resume")
    if not isinstance(payload, Mapping):
        raise ValueError("import resume root must be an object")
    required = {
        "job_id",
        "source_checksum",
        "total_rows",
        "next_row",
        "chunk_size",
        "status",
        "schema_version",
        "execution_allowed",
        "report_digest",
    }
    if set(payload) != required:
        raise ValueError("import resume fields are malformed")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != RESUME_SCHEMA_VERSION:
        raise ValueError("unsupported import resume schema")
    state = ImportResumeState(
        job_id=payload["job_id"],  # type: ignore[arg-type]
        source_checksum=payload["source_checksum"],  # type: ignore[arg-type]
        total_rows=payload["total_rows"],  # type: ignore[arg-type]
        next_row=payload["next_row"],  # type: ignore[arg-type]
        chunk_size=payload["chunk_size"],  # type: ignore[arg-type]
        status=payload["status"],  # type: ignore[arg-type]
        schema_version=payload["schema_version"],  # type: ignore[arg-type]
        execution_allowed=payload["execution_allowed"],  # type: ignore[arg-type]
        report_digest=payload["report_digest"],  # type: ignore[arg-type]
    )
    _validate_resume_state(state)
    return state


def import_csv(source: object, **kwargs: object) -> UniverseImportReport:
    return dry_run_universe_import(source, source_kind="csv", **kwargs)


def import_xlsx(source: object, **kwargs: object) -> UniverseImportReport:
    return dry_run_universe_import(source, source_kind="xlsx", **kwargs)


def import_paste(source: object, **kwargs: object) -> UniverseImportReport:
    return dry_run_universe_import(source, source_kind="paste", **kwargs)


def import_provider_universe(source: object, **kwargs: object) -> UniverseImportReport:
    return dry_run_universe_import(source, source_kind="provider", **kwargs)


build_manifest = build_universe_manifest
save_manifest = save_universe_manifest
load_manifest = load_universe_manifest
create_resume_state = create_import_resume_state
