"""Refresh pytest's per-file scheduling weights from JUnit XML reports."""

from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import json
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET


_ROOT = Path(__file__).resolve().parents[1]


def _test_file(testcase: ET.Element) -> str:
    file_attribute = testcase.get("file")
    if file_attribute:
        parts = PurePosixPath(file_attribute.replace("\\", "/")).parts
        if "tests" in parts:
            parts = parts[parts.index("tests") :]
        elif not PurePosixPath(file_attribute.replace("\\", "/")).is_absolute():
            parts = ("tests", *parts)
        else:
            parts = ()
        if parts:
            path = PurePosixPath(*parts)
            if path.suffix != ".py":
                path = path.with_suffix(".py")
            return path.as_posix()

    classname = testcase.get("classname", "").replace("/", ".").replace("\\", ".")
    parts = tuple(part for part in classname.split(".") if part)
    module_end = next(
        (index for index in range(len(parts) - 1, -1, -1) if parts[index].startswith("test_")),
        None,
    )
    if module_end is None:
        raise ValueError(f"JUnit testcase has no recognizable tests file: {testcase.attrib!r}")
    return PurePosixPath(*parts[: module_end + 1]).with_suffix(".py").as_posix()


def _duration(testcase: ET.Element, report: Path) -> Decimal:
    value = testcase.get("time")
    try:
        duration = Decimal(value) if value is not None else None
    except InvalidOperation as exc:
        raise ValueError(f"Invalid testcase time {value!r} in {report}") from exc
    if duration is None or not duration.is_finite() or duration < 0:
        raise ValueError(f"Invalid testcase time {value!r} in {report}")
    return duration


def build_duration_payload(reports: list[Path]) -> dict[str, object]:
    """Sum testcase time per file within each report, then keep the largest report total."""

    if not reports:
        raise ValueError("At least one JUnit XML report is required")

    maximum_by_file: dict[str, Decimal] = {}
    for report in reports:
        try:
            root = ET.parse(report).getroot()
        except (OSError, ET.ParseError) as exc:
            raise ValueError(f"Could not read JUnit XML report {report}: {exc}") from exc

        report_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
        for testcase in root.iter("testcase"):
            report_totals[_test_file(testcase)] += _duration(testcase, report)
        if not report_totals:
            raise ValueError(f"JUnit XML report contains no testcases: {report}")
        for file_path, total in report_totals.items():
            maximum_by_file[file_path] = max(maximum_by_file.get(file_path, Decimal(0)), total)

    files = {
        file_path: float(duration.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN))
        for file_path, duration in sorted(maximum_by_file.items())
    }
    report_names = sorted(f"{report.parent.name}/{report.name}" for report in reports)
    source = f"JUnit XML reports: {', '.join(report_names)}"
    return {"source": source, "unit": "seconds", "files": files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit_xml", nargs="+", type=Path, help="JUnit XML report files")
    parser.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "tests" / "file_durations.json",
        help="destination JSON file (default: tests/file_durations.json)",
    )
    args = parser.parse_args(argv)
    try:
        payload = build_duration_payload(args.junit_xml)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
