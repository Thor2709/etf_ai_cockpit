"""Refresh pytest's per-file scheduling weights from JUnit XML reports."""

from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET


_ROOT = Path(__file__).resolve().parents[1]
_PLATFORMS = {"linux", "windows"}
# scripts/release_gate.py writes the serial phase to junit-serial.xml and the "not serial" phase to
# junit-parallel.xml, then merges both into junit-full.xml.  Any other report name counts as a
# complete report (both phases).
_SERIAL_REPORT = "junit-serial.xml"
_PARALLEL_REPORT = "junit-parallel.xml"


def _platform(report: Path) -> str:
    """Return the platform label from the nearest platform-labelled directory."""

    for component in reversed(report.parts[:-1]):
        labels = _PLATFORMS.intersection(re.split(r"[-_.]", component.lower()))
        if len(labels) > 1:
            raise ValueError(f"JUnit report path identifies multiple platforms: {report}")
        if labels:
            return next(iter(labels))
    raise ValueError(f"JUnit report path does not identify a platform: {report}")


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
    """Sum testcase time per file within each platform, then keep the platform maximum.

    Reports named ``junit-serial.xml`` (the serial phase) also fill ``serial_files``.  A platform's
    file totals come from its complete/parallel reports; its serial reports are added to the totals
    only when it supplied no complete report (junit-full.xml already contains the serial phase).
    """

    if not reports:
        raise ValueError("At least one JUnit XML report is required")

    totals_by_platform: defaultdict[str, defaultdict[str, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )
    serial_by_platform: defaultdict[str, defaultdict[str, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )
    complete_platforms: set[str] = set()
    serial_seen = False
    any_testcases = False
    for report in reports:
        platform = _platform(report)
        name = report.name.lower()
        is_serial = name == _SERIAL_REPORT
        is_phase = is_serial or name == _PARALLEL_REPORT
        serial_seen = serial_seen or is_serial
        try:
            root = ET.parse(report).getroot()
        except (OSError, ET.ParseError) as exc:
            raise ValueError(f"Could not read JUnit XML report {report}: {exc}") from exc

        report_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
        for testcase in root.iter("testcase"):
            report_totals[_test_file(testcase)] += _duration(testcase, report)
        if not report_totals and not is_phase:
            raise ValueError(f"JUnit XML report contains no testcases: {report}")  # a phase may be empty
        any_testcases = any_testcases or bool(report_totals)
        if not is_phase:
            complete_platforms.add(platform)
        for file_path, total in report_totals.items():
            if is_serial:
                serial_by_platform[platform][file_path] += total
            else:
                totals_by_platform[platform][file_path] += total
    if not any_testcases:
        raise ValueError("JUnit XML reports contain no testcases")
    for platform, serial_totals in serial_by_platform.items():
        if platform not in complete_platforms:
            for file_path, total in serial_totals.items():
                totals_by_platform[platform][file_path] += total

    files = _platform_maximum(totals_by_platform)
    report_names = sorted(f"{report.parent.name}/{report.name}" for report in reports)
    source = f"JUnit XML reports: {', '.join(report_names)}"
    payload: dict[str, object] = {"source": source, "unit": "seconds", "files": files}
    if serial_seen:
        payload["serial_files"] = {
            file_path: seconds for file_path, seconds in _platform_maximum(serial_by_platform).items() if seconds > 0
        }
    return payload


def _platform_maximum(totals_by_platform: defaultdict[str, defaultdict[str, Decimal]]) -> dict[str, float]:
    maximum_by_file: dict[str, Decimal] = {}
    for platform_totals in totals_by_platform.values():
        for file_path, total in platform_totals.items():
            maximum_by_file[file_path] = max(maximum_by_file.get(file_path, total), total)
    return {
        file_path: float(duration.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN))
        for file_path, duration in sorted(maximum_by_file.items())
    }


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
