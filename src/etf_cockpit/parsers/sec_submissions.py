"""Deterministic parsing of SEC submissions and advertised filing history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path, PurePath
import re
from typing import Any

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import ParseResult, ParseWarning


PARSER_NAME = "sec_submissions"
PARSER_VERSION = "1.0"
_REQUIRED_COLUMNS = (
    "accessionNumber",
    "form",
    "filingDate",
    "reportDate",
    "primaryDocument",
)
_OPTIONAL_COLUMNS = ("acceptanceDateTime",)
_ROW_CIK_COLUMNS = ("cik", "cik_str", "issuerCik", "issuer_cik", "issuerCIK")


@dataclass(frozen=True)
class SubmissionRecord:
    """One retained SEC submission row, including its unrecognised fields."""

    instrument_id: str
    cik: str
    accession: str
    form: str
    filing_date: str | None
    report_date: str | None
    primary_document: str | None
    accepted_at: str | None
    available_at: str | None
    is_amendment: bool
    source_sha256: str
    source_id: str
    raw_row: Mapping[str, Any]


@dataclass(frozen=True)
class _HistoryAdvertisement:
    name: str
    filing_count: int | None
    count_valid: bool


def parse_submissions(
    path: Path,
    identity: CanonicalIdentity,
    *,
    history_paths: Mapping[str, Path] | None = None,
    acquired_at: datetime | None = None,
    history_acquired_at: Mapping[str, datetime] | None = None,
    source_provider: str = "sec_local_import",
    history_source_providers: Mapping[str, str] | None = None,
) -> ParseResult[SubmissionRecord]:
    """Parse one SEC submissions snapshot and explicitly supplied history files.

    History files are read only when their exact SEC-advertised names are
    supplied by the caller.  No acquisition or path discovery is performed.
    """

    source_path = Path(path)
    payload, source_sha256, read_warning = _read_json(source_path)
    if read_warning is not None:
        return _failure(source_sha256, read_warning)
    warnings: list[ParseWarning] = []
    expected_cik = _normalise_cik(getattr(identity, "cik", None))
    if expected_cik is None:
        return _failure(source_sha256, _warning("identity_missing", "SEC submissions requires a canonical identity CIK", "error"))
    if not isinstance(payload, dict):
        return _failure(source_sha256, _warning("schema_error", "SEC submissions root must be an object", "error"))
    supplied_top_ciks = [payload[key] for key in ("cik", "cik_str") if key in payload]
    normalised_top_ciks = {_normalise_cik(value) for value in supplied_top_ciks}
    if not supplied_top_ciks or None in normalised_top_ciks:
        return _failure(source_sha256, _warning("identity_missing", "SEC submissions is missing a valid top-level CIK", "error"))
    if normalised_top_ciks != {expected_cik}:
        return _failure(source_sha256, _warning("identity_mismatch", "SEC submissions top-level CIK does not match requested identity", "error"))
    if not isinstance(payload.get("name"), str) or not payload["name"].strip():
        return _failure(source_sha256, _warning("entity_invalid", "SEC submissions is missing a valid entity name", "error"))
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return _failure(source_sha256, _warning("schema_error", "SEC submissions filings object is missing", "error"))
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        return _failure(source_sha256, _warning("schema_error", "SEC submissions recent filings object is missing", "error"))
    recent_columns = _validate_columns(recent, "recent", warnings)
    if recent_columns is None:
        return ParseResult((), tuple(warnings), PARSER_NAME, PARSER_VERSION, source_sha256, False)
    records = list(_records_from_columns(recent_columns, source_sha256, identity, expected_cik, warnings, "recent", acquired_at, source_provider))

    advertised = _advertised_history(filings, expected_cik, warnings)
    if advertised is None:
        return ParseResult((), tuple(warnings), PARSER_NAME, PARSER_VERSION, source_sha256, False)
    selected_history = _select_history_paths(history_paths, advertised, expected_cik, warnings)
    if selected_history is None:
        return ParseResult((), tuple(warnings), PARSER_NAME, PARSER_VERSION, source_sha256, False)
    advertisements_by_name = {advertisement.name: advertisement for advertisement in advertised}
    history_incomplete = "files" not in filings or bool(advertised and len(selected_history) < len(advertised))
    for name in (advertisement.name for advertisement in advertised):
        history_path = selected_history.get(name)
        if history_path is None:
            continue
        history_payload, history_sha256, read_warning = _read_json(history_path)
        if read_warning is not None:
            warnings.append(_warning("history_file_unavailable", f"SEC submissions history {name} could not be read"))
            history_incomplete = True
            continue
        history_columns = _history_columns(history_payload, name, expected_cik, warnings)
        if history_columns is None:
            history_incomplete = True
            continue
        history_time = history_acquired_at.get(name, acquired_at) if isinstance(history_acquired_at, Mapping) else acquired_at
        history_provider = history_source_providers.get(name, source_provider) if isinstance(history_source_providers, Mapping) else source_provider
        history_records = _records_from_columns(history_columns, history_sha256, identity, expected_cik, warnings, name, history_time, history_provider)
        records.extend(history_records)
        history_incomplete |= len(history_records) != len(history_columns["accessionNumber"])
        advertisement = advertisements_by_name[name]
        if not advertisement.count_valid:
            history_incomplete = True
        elif advertisement.filing_count is not None and len(history_records) != advertisement.filing_count:
            warnings.append(_warning("history_count_mismatch", f"SEC submissions history {name} contains {len(history_records)} valid rows but advertises {advertisement.filing_count}"))
            history_incomplete = True
    if history_incomplete:
        warnings.append(_warning("history_incomplete", "SEC submissions advertises history files that were not supplied or could not be parsed; coverage is incomplete"))

    _warn_duplicate_accessions(records, warnings)
    if not records:
        warnings.append(_warning("empty_history", "SEC submissions contains no valid filing rows"))
    return ParseResult(tuple(records), tuple(warnings), PARSER_NAME, PARSER_VERSION, source_sha256, bool(records))


def _read_json(path: Path) -> tuple[object | None, str, ParseWarning | None]:
    try:
        payload_bytes = path.read_bytes()
    except OSError as exc:
        return None, "", _warning("read_error", f"SEC submissions could not be read: {type(exc).__name__}", "error")
    source_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    try:
        return json.loads(payload_bytes.decode("utf-8")), source_sha256, None
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        return None, source_sha256, _warning("malformed_json", f"SEC submissions JSON is invalid: {type(exc).__name__}", "error")


def _validate_columns(columns: object, label: str, warnings: list[ParseWarning]) -> dict[str, list[object]] | None:
    if not isinstance(columns, dict):
        warnings.append(_warning("schema_error", f"SEC submissions {label} columns must be an object", "error"))
        return None
    missing = [name for name in _REQUIRED_COLUMNS if name not in columns]
    if missing:
        warnings.append(_warning("missing_columns", f"SEC submissions {label} is missing columns: {', '.join(missing)}", "error"))
        return None
    if any(not isinstance(value, list) for value in columns.values()):
        warnings.append(_warning("column_type", f"SEC submissions {label} columns must all be arrays", "error"))
        return None
    lengths = {len(value) for value in columns.values()}
    if len(lengths) != 1:
        warnings.append(_warning("column_length_mismatch", f"SEC submissions {label} columns have different lengths", "error"))
        return None
    normalised = {str(key): value for key, value in columns.items()}
    row_count = next(iter(lengths), 0)
    for name in _OPTIONAL_COLUMNS:
        if name not in normalised:
            normalised[name] = [None] * row_count
    return normalised


def _history_columns(
    payload: object,
    name: str,
    expected_cik: str,
    warnings: list[ParseWarning],
) -> dict[str, list[object]] | None:
    if not isinstance(payload, dict):
        warnings.append(_warning("history_schema_error", f"SEC submissions history {name} must be an object"))
        return None
    supplied_ciks = [payload[key] for key in _ROW_CIK_COLUMNS if key in payload]
    normalised_ciks = {_normalise_cik(value) for value in supplied_ciks}
    if supplied_ciks and (None in normalised_ciks or normalised_ciks != {expected_cik}):
        warnings.append(_warning("history_identity_mismatch", f"SEC submissions history {name} does not match the requested CIK"))
        return None
    supplied_name = payload.get("name")
    if supplied_name is not None and (not isinstance(supplied_name, str) or not supplied_name.strip()):
        warnings.append(_warning("history_entity_invalid", f"SEC submissions history {name} has an invalid entity name"))
        return None
    columns = payload.get("filings", payload)
    if isinstance(columns, dict) and isinstance(columns.get("recent"), dict):
        columns = columns["recent"]
    return _validate_columns(columns, f"history {name}", warnings)


def _advertised_history(filings: dict[str, object], expected_cik: str, warnings: list[ParseWarning]) -> tuple[_HistoryAdvertisement, ...] | None:
    if "files" not in filings:
        warnings.append(_warning("history_advertisement_missing", "SEC submissions filings.files is absent; historical coverage is unknown and remains partial"))
        return ()
    files = filings["files"]
    if not isinstance(files, list):
        warnings.append(_warning("history_advertisement_invalid", "SEC submissions filings.files must be an array", "error"))
        return None
    names: list[_HistoryAdvertisement] = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            warnings.append(_warning("history_advertisement_invalid", "SEC submissions history advertisement is malformed", "error"))
            return None
        name = item["name"]
        if PurePath(name).name != name or not re.fullmatch(rf"CIK{expected_cik}-submissions-[0-9]+\.json", name):
            warnings.append(_warning("history_name_invalid", f"SEC submissions history name is unsafe or not bound to CIK: {name!r}", "error"))
            return None
        if any(advertisement.name == name for advertisement in names):
            warnings.append(_warning("history_advertisement_duplicate", f"SEC submissions history name is duplicated: {name}"))
            return None
        filing_count = item.get("filingCount")
        count_valid = filing_count is None or (type(filing_count) is int and filing_count >= 0)
        if not count_valid:
            warnings.append(_warning("history_count_invalid", f"SEC submissions history filingCount is invalid for {name}"))
        names.append(_HistoryAdvertisement(name, filing_count if count_valid else None, count_valid))
    return tuple(names)


def _select_history_paths(
    history_paths: Mapping[str, Path] | None,
    advertised: tuple[_HistoryAdvertisement, ...],
    expected_cik: str,
    warnings: list[ParseWarning],
) -> dict[str, Path] | None:
    if history_paths is None:
        return {}
    if not isinstance(history_paths, Mapping):
        warnings.append(_warning("history_paths_invalid", "SEC submissions history_paths must be a mapping", "error"))
        return None
    advertised_set = {advertisement.name for advertisement in advertised}
    selected: dict[str, Path] = {}
    for raw_name, raw_path in history_paths.items():
        if not isinstance(raw_name, str) or raw_name not in advertised_set:
            warnings.append(_warning("history_not_advertised", "SEC submissions history path was not named in filings.files", "error"))
            return None
        try:
            candidate = Path(raw_path)
        except (TypeError, ValueError):
            warnings.append(_warning("history_path_invalid", f"SEC submissions history path is invalid for {raw_name}"))
            continue
        if candidate.name != raw_name or candidate.is_symlink() or not candidate.is_file():
            warnings.append(_warning("history_path_invalid", f"SEC submissions history path is not a safe file for {raw_name}"))
            continue
        selected[raw_name] = candidate
    return selected


def _records_from_columns(
    columns: dict[str, list[object]],
    source_sha256: str,
    identity: CanonicalIdentity,
    expected_cik: str,
    warnings: list[ParseWarning],
    source_label: str,
    acquired_at: datetime | None = None,
    source_provider: str = "sec_local_import",
) -> tuple[SubmissionRecord, ...]:
    count = len(columns["accessionNumber"])
    result: list[SubmissionRecord] = []
    for index in range(count):
        raw_row = {key: values[index] for key, values in columns.items()}
        row_ciks = [raw_row[key] for key in _ROW_CIK_COLUMNS if key in raw_row]
        normalised_row_ciks = {_normalise_cik(value) for value in row_ciks}
        if row_ciks and (None in normalised_row_ciks or normalised_row_ciks != {expected_cik}):
            warnings.append(_warning("row_identity_mismatch", f"SEC submissions {source_label} row {index} does not match the requested CIK"))
            continue
        accession = _text(raw_row.get("accessionNumber"))
        form = _text(raw_row.get("form"))
        if not accession or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) or not form:
            code = "invalid_accession" if accession and not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) else "invalid_row"
            warnings.append(_warning(code, f"SEC submissions {source_label} row {index} has no valid accession or form"))
            continue
        filing_date = _date_value(raw_row.get("filingDate"), "filing_date", source_label, index, warnings)
        report_date = _date_value(raw_row.get("reportDate"), "report_date", source_label, index, warnings)
        accepted_at = _accepted_value(raw_row.get("acceptanceDateTime"), source_label, index, warnings)
        available_at = accepted_at
        if accepted_at is not None and acquired_at is not None and acquired_at.tzinfo is not None and acquired_at.utcoffset() is not None:
            accepted_timestamp = datetime.fromisoformat(accepted_at)
            if accepted_timestamp > acquired_at:
                warnings.append(_warning("acceptance_after_acquisition", f"SEC submissions {source_label} row {index} acceptanceDateTime is later than its bound acquisition time"))
                available_at = None
        row_digest = hashlib.sha256(json.dumps(raw_row, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:16]
        result.append(
            SubmissionRecord(
                instrument_id=str(identity.instrument_id),
                cik=expected_cik,
                accession=accession,
                form=form,
                filing_date=filing_date,
                report_date=report_date,
                primary_document=_optional_text(raw_row.get("primaryDocument")),
                accepted_at=accepted_at,
                available_at=available_at,
                is_amendment=form.upper().endswith("/A"),
                source_sha256=source_sha256,
                source_id=f"{source_provider}:{source_sha256[:16]}:submission:{index}:{row_digest}",
                raw_row=raw_row,
            )
        )
    return tuple(result)


def _warn_duplicate_accessions(records: list[SubmissionRecord], warnings: list[ParseWarning]) -> None:
    prior: dict[str, SubmissionRecord] = {}
    for record in records:
        previous = prior.get(record.accession)
        if previous is not None:
            code = "duplicate_accession" if previous.raw_row == record.raw_row else "conflicting_accession"
            warnings.append(_warning(code, f"SEC submissions retains repeated accession {record.accession} as a distinct source row"))
        else:
            prior[record.accession] = record


def _date_value(value: object, field: str, source_label: str, index: int, warnings: list[ParseWarning]) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        warnings.append(_warning("invalid_date", f"SEC submissions {source_label} row {index} has an invalid {field}"))
        return None


def _accepted_value(value: object, source_label: str, index: int, warnings: list[ParseWarning]) -> str | None:
    text = _optional_text(value)
    if text is None:
        warnings.append(_warning("missing_acceptance_timestamp", f"SEC submissions {source_label} row {index} has no acceptanceDateTime"))
        return None
    try:
        accepted = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        warnings.append(_warning("invalid_acceptance_timestamp", f"SEC submissions {source_label} row {index} has an invalid acceptanceDateTime"))
        return None
    if accepted.tzinfo is None or accepted.utcoffset() is None:
        warnings.append(_warning("invalid_acceptance_timestamp", f"SEC submissions {source_label} row {index} acceptanceDateTime is not timezone-aware"))
        return None
    return accepted.isoformat()


def _normalise_cik(value: object) -> str | None:
    text = str(value or "").strip().upper().removeprefix("CIK")
    if not text or not re.fullmatch(r"[0-9]{1,10}", text) or int(text) <= 0:
        return None
    return text.zfill(10)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _warning(code: str, message: str, severity: str = "warning") -> ParseWarning:
    return ParseWarning(code, message, severity)


def _failure(source_sha256: str, warning: ParseWarning) -> ParseResult[SubmissionRecord]:
    return ParseResult((), (warning,), PARSER_NAME, PARSER_VERSION, source_sha256, False)
