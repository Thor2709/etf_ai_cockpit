"""Validate the immutable completion-package ZIP before it is archived.

The validator deliberately performs all checks in memory.  It never extracts
an untrusted member into the repository and is usable with only Python's
standard library.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


EXPECTED_MEMBERS = frozenset(
    {
        "ETF_AI_Cockpit_Completion_Blueprint.md",
        "ETF_AI_Cockpit_Completion_Programme_Index.md",
        "ETF_AI_Cockpit_Current_Open_Issues_Audit.md",
        "ETF_AI_Cockpit_Current_Open_Issues_Audit.csv",
        "ETF_AI_Cockpit_New_Issues_Ready_To_Append.md",
        "ETF_AI_Cockpit_New_Issues.csv",
        "ETF_AI_Cockpit_Master_Issue_Registry.json",
        "ETF_AI_Cockpit_Research_Sources.md",
        "ETF_AI_Cockpit_Research_Sources.csv",
    }
)

ISSUE_ID_RE = re.compile(r"\b(?:ISSUE|UPDATEV2)-\d{4}\b")
HEADING_RE = re.compile(
    r"^##\s+((?:ISSUE|UPDATEV2)-\d{4})\s+—\s+(.+?)\s*$", re.MULTILINE
)
SECRET_PATTERNS = (
    re.compile(
        r"\b(?:api[_ -]?key|secret(?:[_ -]?key)?|password|token)\b"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9+/=_-]{12,}",
        re.IGNORECASE,
    ),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|github_pat|xox[baprs]|sk)-[A-Za-z0-9_-]{12,}\b"),
)
ALLOWED_EXTERNAL_REFERENCES = frozenset({"UPDATEV2-0028"})
DEFAULT_MAX_MEMBER_BYTES = 8_000_000
DEFAULT_MAX_TOTAL_BYTES = 20_000_000
DEFAULT_MAX_COMPRESSION_RATIO = 1_000


@dataclass
class ValidationReport:
    package_sha256: str = ""
    member_hashes: dict[str, str] = field(default_factory=dict)
    current_open_issue_count: int = 0
    new_issue_count: int = 0
    combined_issue_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["valid"] = self.valid
        return payload


def _error(report: ValidationReport, message: str) -> None:
    report.errors.append(message)


def _warning(report: ValidationReport, message: str) -> None:
    report.warnings.append(message)


def _is_safe_member_name(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and all(path.parts)


def _check_control_characters(report: ValidationReport, member: str, text: str) -> None:
    invalid = sorted({ord(char) for char in text if ord(char) < 32 and char not in "\r\n\t"})
    if invalid:
        formatted = ", ".join(f"U+{value:04X}" for value in invalid)
        _error(report, f"{member}: control characters detected ({formatted})")


def _check_secret_patterns(report: ValidationReport, member: str, text: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            _error(report, f"{member}: common secret pattern detected")
            return


def _parse_csv(report: ValidationReport, member: str, payload: bytes) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        _error(report, f"{member}: invalid UTF-8 ({exc})")
        return []
    _check_control_characters(report, member, text)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames:
            _error(report, f"{member}: CSV header is missing")
            return []
        if any(not field or field.strip() != field for field in reader.fieldnames):
            _error(report, f"{member}: CSV header contains an empty or padded field")
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                _error(report, f"{member}: row {row_number} has more fields than its header")
                continue
            rows.append({str(key): value or "" for key, value in row.items()})
        return rows
    except csv.Error as exc:
        _error(report, f"{member}: malformed CSV ({exc})")
        return []


def _parse_json(report: ValidationReport, member: str, payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
        _check_control_characters(report, member, text)
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _error(report, f"{member}: malformed JSON ({exc})")
        return {}
    if not isinstance(value, dict):
        _error(report, f"{member}: JSON root must be an object")
        return {}
    return value


def _parse_markdown(report: ValidationReport, member: str, payload: bytes) -> dict[str, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        _error(report, f"{member}: invalid UTF-8 ({exc})")
        return {}
    _check_control_characters(report, member, text)
    _check_secret_patterns(report, member, text)
    records = dict(HEADING_RE.findall(text))
    ids = ISSUE_ID_RE.findall(text)
    if len(records) != len(set(records)):
        _error(report, f"{member}: duplicate canonical issue headings")
    if len(ids) != len(set(ids)) and member.endswith("Audit.md"):
        _warning(report, f"{member}: repeated issue references are present outside headings")
    return records


def _record_rows(
    report: ValidationReport,
    label: str,
    csv_rows: list[dict[str, str]],
    json_rows: Any,
    markdown_rows: dict[str, str],
) -> list[str]:
    if not isinstance(json_rows, list):
        _error(report, f"{label}: JSON record list is missing")
        return []
    csv_by_id: dict[str, dict[str, str]] = {}
    for row in csv_rows:
        issue_id = row.get("issue_id", "").strip()
        if issue_id in csv_by_id:
            _error(report, f"{label}: duplicate CSV record {issue_id}")
        if issue_id:
            csv_by_id[issue_id] = row
    json_by_id: dict[str, dict[str, Any]] = {}
    for row in json_rows:
        if not isinstance(row, dict):
            _error(report, f"{label}: JSON record is not an object")
            continue
        issue_id = str(row.get("issue_id", "")).strip()
        if issue_id in json_by_id:
            _error(report, f"{label}: duplicate JSON record {issue_id}")
        if issue_id:
            json_by_id[issue_id] = row

    csv_ids = set(csv_by_id)
    json_ids = set(json_by_id)
    md_ids = set(markdown_rows)
    if csv_ids != json_ids:
        _error(report, f"{label}: CSV/JSON record IDs disagree")
    if csv_ids != md_ids:
        _error(report, f"{label}: Markdown/CSV record IDs disagree")
    for issue_id in sorted(csv_ids & json_ids & md_ids):
        csv_title = csv_by_id[issue_id].get("title", "").strip()
        json_title = str(json_by_id[issue_id].get("title", "")).strip()
        markdown_title = markdown_rows[issue_id].strip()
        if len({csv_title, json_title, markdown_title}) != 1:
            _error(report, f"{label}: title mismatch for {issue_id}")
    return sorted(csv_ids)


def _validate_references(report: ValidationReport, registry: dict[str, Any]) -> None:
    all_rows: list[dict[str, Any]] = []
    for key in ("current_open_issues", "proposed_new_issues"):
        rows = registry.get(key, [])
        if isinstance(rows, list):
            all_rows.extend(row for row in rows if isinstance(row, dict))
    known = {str(row.get("issue_id", "")) for row in all_rows}
    for row in all_rows:
        source_id = str(row.get("issue_id", ""))
        for value in row.values():
            for reference in ISSUE_ID_RE.findall(str(value)):
                if reference == source_id or reference in known:
                    continue
                if reference in ALLOWED_EXTERNAL_REFERENCES:
                    _warning(report, f"{source_id}: reference {reference} is outside the package")
                else:
                    _error(report, f"{source_id}: unknown issue reference {reference}")


def validate_package(
    package_path: str | Path,
    *,
    expected_counts: tuple[int, int] | None = (76, 83),
    expected_member_hashes: dict[str, str] | None = None,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
) -> ValidationReport:
    """Return a complete validation report for ``package_path``.

    ``expected_counts`` is configurable for small synthetic test packages;
    production validation keeps the package contract at 76 current and 83
    proposed records.
    """

    path = Path(package_path)
    report = ValidationReport()
    try:
        report.package_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        _error(report, f"package: cannot read file ({exc})")
        return report

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        _error(report, f"package: invalid ZIP ({exc})")
        return report

    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicates:
            _error(report, f"package: duplicate ZIP members: {', '.join(duplicates)}")
        unsafe = sorted(name for name in names if not _is_safe_member_name(name))
        if unsafe:
            _error(report, f"package: unsafe ZIP member names: {', '.join(unsafe)}")
        if set(names) != EXPECTED_MEMBERS:
            missing = sorted(EXPECTED_MEMBERS - set(names))
            extra = sorted(set(names) - EXPECTED_MEMBERS)
            if missing:
                _error(report, f"package: missing expected members: {', '.join(missing)}")
            if extra:
                _error(report, f"package: unexpected members: {', '.join(extra)}")

        total_size = sum(info.file_size for info in infos)
        if total_size > max_total_bytes:
            _error(report, f"package: decompressed size exceeds limit ({total_size} bytes)")

        members: dict[str, bytes] = {}
        for info in infos:
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                _error(report, f"{info.filename}: symlink entries are not allowed")
            if info.file_size > max_member_bytes:
                _error(report, f"{info.filename}: decompressed size exceeds member limit")
            if info.file_size and not info.compress_size:
                _error(report, f"{info.filename}: invalid zero-size compressed member")
            if info.compress_size and info.file_size / info.compress_size > max_compression_ratio:
                _error(report, f"{info.filename}: compression ratio exceeds safety limit")
            try:
                payload = archive.read(info)
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                _error(report, f"{info.filename}: cannot read member ({exc})")
                continue
            if len(payload) != info.file_size:
                _error(report, f"{info.filename}: decompressed size does not match ZIP metadata")
            digest = hashlib.sha256(payload).hexdigest()
            report.member_hashes[info.filename] = digest
            if expected_member_hashes and info.filename in expected_member_hashes:
                if digest.lower() != expected_member_hashes[info.filename].lower():
                    _error(report, f"{info.filename}: hash mismatch")
            members[info.filename] = payload

    for member, payload in members.items():
        if member.endswith(".md"):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                _error(report, f"{member}: invalid UTF-8 ({exc})")
                continue
            _check_control_characters(report, member, text)
            _check_secret_patterns(report, member, text)
        elif member.endswith(".csv"):
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                _error(report, f"{member}: invalid UTF-8 ({exc})")
                continue
            _check_control_characters(report, member, text)

    current_csv = _parse_csv(
        report, "ETF_AI_Cockpit_Current_Open_Issues_Audit.csv", members.get("ETF_AI_Cockpit_Current_Open_Issues_Audit.csv", b"")
    )
    new_csv = _parse_csv(
        report, "ETF_AI_Cockpit_New_Issues.csv", members.get("ETF_AI_Cockpit_New_Issues.csv", b"")
    )
    registry = _parse_json(
        report, "ETF_AI_Cockpit_Master_Issue_Registry.json", members.get("ETF_AI_Cockpit_Master_Issue_Registry.json", b"")
    )
    current_md = _parse_markdown(
        report, "ETF_AI_Cockpit_Current_Open_Issues_Audit.md", members.get("ETF_AI_Cockpit_Current_Open_Issues_Audit.md", b"")
    )
    new_md = _parse_markdown(
        report, "ETF_AI_Cockpit_New_Issues_Ready_To_Append.md", members.get("ETF_AI_Cockpit_New_Issues_Ready_To_Append.md", b"")
    )
    current_ids = _record_rows(
        report, "current_open_issues", current_csv, registry.get("current_open_issues"), current_md
    )
    new_ids = _record_rows(
        report, "proposed_new_issues", new_csv, registry.get("proposed_new_issues"), new_md
    )
    report.current_open_issue_count = len(current_ids)
    report.new_issue_count = len(new_ids)
    report.combined_issue_count = report.current_open_issue_count + report.new_issue_count

    if expected_counts is not None:
        expected_current, expected_new = expected_counts
        if report.current_open_issue_count != expected_current:
            _error(report, f"current_open_issues: expected {expected_current} records, found {report.current_open_issue_count}")
        if report.new_issue_count != expected_new:
            _error(report, f"proposed_new_issues: expected {expected_new} records, found {report.new_issue_count}")

    new_numbers = sorted(int(issue_id.rsplit("-", 1)[1]) for issue_id in new_ids if issue_id.startswith("ISSUE-"))
    expected_numbers = list(range(70, 70 + len(new_numbers)))
    if new_numbers != expected_numbers:
        _error(report, "proposed_new_issues: ISSUE IDs are not continuous from ISSUE-0070")
    if len(new_ids) != len(set(new_ids)):
        _error(report, "proposed_new_issues: duplicate issue IDs")
    _validate_references(report, registry)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="path to the supplied completion-package ZIP")
    parser.add_argument("--json-report", action="store_true", help="emit the report as JSON")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = validate_package(args.package)
    if args.json_report:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(f"package_sha256: {report.package_sha256}")
        print(f"current_open_issue_count: {report.current_open_issue_count}")
        print(f"new_issue_count: {report.new_issue_count}")
        for message in report.warnings:
            print(f"WARNING: {message}")
        for message in report.errors:
            print(f"ERROR: {message}")
        print("VALID" if report.valid else "INVALID")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
