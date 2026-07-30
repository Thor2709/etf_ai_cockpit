"""Compare report-only pytest pilot evidence from Linux and Windows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence


_COMPARED_FIELDS = (
    "collection_fingerprints",
    "collection_counts",
    "result_fingerprints",
    "result_counts",
    "junit_present",
    "sample_count",
    "sample_counts",
    "run_order",
)


def _read_report(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"pilot report is not an object: {path}")
    return value


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

    return {
        "schema_version": "pytest-parallel-pilot-cross-platform.v1",
        "mode": "report_only",
        "authority": "serial_release_gate",
        "compared_fields": list(_COMPARED_FIELDS) + ["status", "authority"],
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
