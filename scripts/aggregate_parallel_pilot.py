"""Compare report-only pytest pilot evidence from Linux and Windows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence


_COMPARED_FIELDS = (
    "schema_version",
    "strategy",
    "phase_order",
    "selectors",
    "workers",
    "repetitions",
    "unsafe_groups",
    "collection_parity",
    "collection_evidence_valid",
    "result_parity",
    "repeatable_results",
    "sample_count",
    "run_order",
    "manifest_valid",
    "lane_counts",
    "lane_codes",
    "lane_fingerprints",
)
_LANES = ("full_serial", "candidate_safe", "candidate_unsafe", "candidate_combined")
_UNSAFE_GROUPS = ["concurrency", "environment", "flet", "package", "ports", "sqlite"]


def _read_report(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"pilot report is not an object: {path}")
    return value


def _report_is_valid(label: str, report: Mapping[str, object]) -> bool:
    sample_count = report.get("sample_count")
    if type(sample_count) is not int or sample_count < 2:
        return False
    if (
        report.get("schema_version") != "pytest-parallel-pilot.v2"
        or report.get("mode") != "report_only"
        or report.get("authority") != "serial_release_gate"
        or report.get("platform") != label
        or report.get("workers") != 4
        or report.get("repetitions") != sample_count
        or report.get("strategy") != "full_serial_vs_two_phase_xdist"
        or report.get("phase_order") != ["safe", "unsafe"]
        or report.get("selectors")
        != {
            "full_serial": [],
            "safe": ["-m", "not serial"],
            "unsafe": ["-m", "serial"],
        }
        or report.get("unsafe_groups") != _UNSAFE_GROUPS
        or report.get("collection_parity") is not True
        or report.get("collection_evidence_valid") is not True
        or report.get("result_parity") is not True
        or report.get("repeatable_results") is not True
        or report.get("status") != "passed"
    ):
        return False
    lanes = report.get("lanes")
    manifest_valid = report.get("manifest_valid")
    for field in ("lane_counts", "lane_codes", "lane_fingerprints", "timings"):
        field_value = report.get(field)
        if not isinstance(field_value, dict) or set(field_value) != set(_LANES):
            return False
    if (
        not isinstance(lanes, dict)
        or set(lanes) != set(_LANES)
        or not isinstance(manifest_valid, dict)
        or set(manifest_valid) != set(_LANES)
    ):
        return False
    for lane in _LANES:
        record = lanes[lane]
        if not isinstance(record, dict):
            return False
        required = (
            "collection_counts",
            "result_counts",
            "collection_exit_codes",
            "exit_codes",
            "junit_present",
            "collection_fingerprints",
            "result_fingerprints",
            "timings",
        )
        if any(key not in record for key in required):
            return False
        arrays = {key: record[key] for key in required if key != "timings"}
        if any(not isinstance(value, list) or len(value) != sample_count for value in arrays.values()):
            return False
        counts = record["collection_counts"]
        result_counts = record["result_counts"]
        if counts != result_counts or not all(type(count) is int and count > 0 for count in counts):
            return False
        if not all(flag is True for flag in record["junit_present"]):
            return False
        if not all(code == 0 for key in ("collection_exit_codes", "exit_codes") for code in record[key]):
            return False
        validity = manifest_valid[lane]
        timing = record["timings"]
        if not isinstance(timing, dict):
            return False
        samples = timing.get("samples_seconds")
        if not isinstance(samples, list) or len(samples) != sample_count:
            return False
        if not isinstance(validity, list) or len(validity) != sample_count or not all(value is True for value in validity):
            return False
    expected_order = [
        ["full_serial", "candidate"] if index % 2 == 0 else ["candidate", "full_serial"]
        for index in range(sample_count)
    ]
    return report.get("run_order") == expected_order


def compare_reports(linux_path: Path, windows_path: Path) -> dict[str, object]:
    """Return deterministic cross-platform evidence without granting authority."""

    reports: dict[str, Mapping[str, object]] = {}
    errors: list[str] = []
    for label, path in (("linux", linux_path), ("windows", windows_path)):
        try:
            reports[label] = _read_report(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{label}: {exc}")

    differences: dict[str, object] = {}
    if errors:
        differences["artifacts"] = errors
    if len(reports) == 2:
        linux = reports["linux"]
        windows = reports["windows"]
        for field in (*_COMPARED_FIELDS, "status"):
            if field not in linux or field not in windows:
                differences[field] = {
                    "linux_present": field in linux,
                    "windows_present": field in windows,
                }
                continue
            if linux.get(field) != windows.get(field):
                differences[field] = {"linux": linux.get(field), "windows": windows.get(field)}
        statuses = {"linux": linux.get("status"), "windows": windows.get("status")}
        if len(set(statuses.values())) != 1 or any(value != "passed" for value in statuses.values()):
            differences["status"] = statuses
        authority = {
            label: {"mode": report.get("mode"), "authority": report.get("authority")}
            for label, report in reports.items()
        }
        if any(
            details != {"mode": "report_only", "authority": "serial_release_gate"}
            for details in authority.values()
        ):
            differences["authority"] = authority
        platforms = {label: report.get("platform") for label, report in reports.items()}
        if platforms != {"linux": "linux", "windows": "windows"}:
            differences["platform"] = platforms
        for label, report in reports.items():
            if not _report_is_valid(label, report):
                differences[f"{label}_validity"] = False

    return {
        "schema_version": "pytest-parallel-pilot-cross-platform.v2",
        "mode": "report_only",
        "authority": "serial_release_gate",
        "compared_fields": list(_COMPARED_FIELDS) + ["status", "authority", "platform"],
        "platform_reports": {label: str(path) for label, path in (("linux", linux_path), ("windows", windows_path))},
        "differences": differences,
        "status": "passed" if not differences else "divergent",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-report", type=Path, required=True)
    parser.add_argument("--windows-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    report = compare_reports(args.linux_report, args.windows_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
