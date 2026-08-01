"""Compare report-only pytest pilot evidence from Linux and Windows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
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
    "repeatable_collections",
    "sample_count",
    "run_order",
    "manifest_valid",
    "lane_counts",
    "lane_codes",
)
_LANES = ("full_serial", "candidate_safe", "candidate_unsafe", "candidate_combined")
_UNSAFE_GROUPS = ["concurrency", "environment", "flet", "package", "ports", "sqlite"]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CACHE_SCHEMA = "pytest-parallel-pilot-cache.v1"
_CACHE_LOCKS = ("requirements-release.txt", "requirements-release-parsers.txt")
_CACHE_TOOLS = ("build", "pip", "pytest", "pytest-xdist")
_KNOWN_PLATFORM_OUTCOMES = {
    "tests/test_pid_liveness.py::test_windows_pid_probe_detects_exited_child_before_popen_handle_closes",
    "tests/test_pid_liveness.py::test_windows_pid_probe_does_not_terminate_a_child_process",
}
_KNOWN_PLATFORM_LANES = {"full_serial", "candidate_safe", "candidate_combined"}


def _cache_key(inputs: Mapping[str, object]) -> str:
    encoded = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_is_valid(cache: object, platform_label: str | None = None) -> bool:
    if not isinstance(cache, dict) or set(cache) != {"schema_version", "key_sha256", "inputs", "setup_python_cache_hit"}:
        return False
    if cache.get("schema_version") != _CACHE_SCHEMA or not isinstance(cache.get("key_sha256"), str) or not _SHA256_RE.fullmatch(cache["key_sha256"]):
        return False
    inputs = cache.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {"os", "python", "locks", "build_tools"}:
        return False
    if not all(isinstance(inputs.get(key), str) and inputs[key] for key in ("os", "python")):
        return False
    if platform_label is not None and str(inputs["os"]).lower() != platform_label:
        return False
    locks = inputs.get("locks")
    if not isinstance(locks, dict) or set(locks) != set(_CACHE_LOCKS) or not all(isinstance(value, str) and _SHA256_RE.fullmatch(value) for value in locks.values()):
        return False
    tools = inputs.get("build_tools")
    if not isinstance(tools, dict) or set(tools) != set(_CACHE_TOOLS) or not all(isinstance(value, str) and value for value in tools.values()):
        return False
    setup_cache_hit = cache.get("setup_python_cache_hit")
    return (
        cache["key_sha256"] == _cache_key(inputs)
        and isinstance(setup_cache_hit, str)
        and setup_cache_hit in {"true", "false", "unknown"}
    )


def _platform_outcome_is_allowed(
    lane: str, nodeid: str, linux: str, windows: str
) -> bool:
    return (
        lane in _KNOWN_PLATFORM_LANES
        and nodeid in _KNOWN_PLATFORM_OUTCOMES
        and (linux, windows) == ("skipped", "passed")
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _read_report(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"pilot report is not an object: {path}")
    return value


def _report_is_valid(label: str, report: Mapping[str, object]) -> bool:
    sample_count = report.get("sample_count")
    if type(sample_count) is not int or sample_count < 1:
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
        or report.get("repeatable_collections") is not True
        or report.get("status") != "passed"
        or not _cache_is_valid(report.get("cache"), label)
    ):
        return False
    lanes = report.get("lanes")
    manifest_valid = report.get("manifest_valid")
    for field in ("lane_counts", "lane_codes", "lane_fingerprints"):
        field_value = report.get(field)
        if not isinstance(field_value, dict) or set(field_value) != set(_LANES):
            return False
    timing_projection = report.get("timings")
    if not isinstance(timing_projection, dict) or set(timing_projection) != {*_LANES, "candidate_wall"}:
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
            "executed_nodeids",
            "result_outcomes",
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
        if not all(type(value) is int for key in ("collection_counts", "result_counts", "collection_exit_codes", "exit_codes") for value in record[key]):
            return False
        if not all(isinstance(value, str) and _SHA256_RE.fullmatch(value) for key in ("collection_fingerprints", "result_fingerprints") for value in record[key]):
            return False
        executed_nodeids = record["executed_nodeids"]
        outcomes = record["result_outcomes"]
        if not isinstance(executed_nodeids, list) or len(executed_nodeids) != sample_count:
            return False
        if not isinstance(outcomes, list) or len(outcomes) != sample_count:
            return False
        for index, (nodeids, outcome_map) in enumerate(zip(executed_nodeids, outcomes)):
            if not isinstance(nodeids, list) or nodeids != sorted(set(nodeids)) or not all(isinstance(nodeid, str) and nodeid for nodeid in nodeids):
                return False
            if not isinstance(outcome_map, dict) or set(outcome_map) != set(nodeids) or not all(value in {"passed", "failure", "error", "skipped"} for value in outcome_map.values()):
                return False
            if len(nodeids) != record["result_counts"][index]:
                return False
            expected_collection_fingerprint = hashlib.sha256(
                json.dumps(sorted(set(nodeids)), separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if record["collection_fingerprints"][index] != expected_collection_fingerprint:
                return False
            expected_result_fingerprint = hashlib.sha256(
                json.dumps(outcome_map, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if record["result_fingerprints"][index] != expected_result_fingerprint:
                return False
        validity = manifest_valid[lane]
        timing = record["timings"]
        if not isinstance(timing, dict):
            return False
        samples = timing.get("samples_seconds")
        if not isinstance(samples, list) or len(samples) != sample_count or not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 for value in samples):
            return False
        for percentile, key in ((0.50, "p50_seconds"), (0.95, "p95_seconds")):
            expected = round(_percentile([float(value) for value in samples], percentile), 3)
            actual = timing.get(key)
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isfinite(actual) or actual != expected:
                return False
        if not isinstance(validity, list) or len(validity) != sample_count or not all(value is True for value in validity):
            return False
    expected_counts = {
        lane: {"collection": lanes[lane]["collection_counts"], "results": lanes[lane]["result_counts"]}
        for lane in _LANES
    }
    expected_codes = {
        lane: {"collection": lanes[lane]["collection_exit_codes"], "tests": lanes[lane]["exit_codes"]}
        for lane in _LANES
    }
    expected_fingerprints = {
        lane: {"collection": lanes[lane]["collection_fingerprints"], "results": lanes[lane]["result_fingerprints"]}
        for lane in _LANES
    }
    if report.get("lane_counts") != expected_counts or report.get("lane_codes") != expected_codes or report.get("lane_fingerprints") != expected_fingerprints:
        return False
    assert isinstance(timing_projection, dict)
    if report.get("timings") != {**{lane: lanes[lane]["timings"] for lane in _LANES}, "candidate_wall": timing_projection["candidate_wall"]}:
        return False
    candidate_wall = timing_projection.get("candidate_wall")
    if not isinstance(candidate_wall, dict):
        return False
    wall_samples = candidate_wall.get("samples_seconds")
    if not isinstance(wall_samples, list) or len(wall_samples) != sample_count or not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 for value in wall_samples):
        return False
    for percentile, key in ((0.50, "p50_seconds"), (0.95, "p95_seconds")):
        expected = round(_percentile([float(value) for value in wall_samples], percentile), 3)
        actual = candidate_wall.get(key)
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isfinite(actual) or actual != expected:
            return False
    for index in range(sample_count):
        for field in ("collection_counts", "result_counts"):
            safe_count = lanes["candidate_safe"][field][index]
            unsafe_count = lanes["candidate_unsafe"][field][index]
            combined_count = lanes["candidate_combined"][field][index]
            full_count = lanes["full_serial"][field][index]
            if safe_count + unsafe_count != combined_count or combined_count != full_count:
                return False
        if (
            lanes["full_serial"]["collection_fingerprints"][index]
            != lanes["candidate_combined"]["collection_fingerprints"][index]
            or lanes["full_serial"]["result_fingerprints"][index]
            != lanes["candidate_combined"]["result_fingerprints"][index]
        ):
            return False
        safe_seconds = float(lanes["candidate_safe"]["timings"]["samples_seconds"][index])
        unsafe_seconds = float(
            lanes["candidate_unsafe"]["timings"]["samples_seconds"][index]
        )
        combined_seconds = float(
            lanes["candidate_combined"]["timings"]["samples_seconds"][index]
        )
        wall_seconds = float(wall_samples[index])
        if abs(combined_seconds - (safe_seconds + unsafe_seconds)) > 0.001:
            return False
        if wall_seconds + 0.002 < safe_seconds + unsafe_seconds:
            return False
    if any(
        len(set(lanes[lane]["collection_fingerprints"])) != 1 for lane in _LANES
    ):
        return False
    if any(
        len(set(lanes[lane]["result_fingerprints"])) != 1
        for lane in ("full_serial", "candidate_combined")
    ):
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
        linux_cache = linux.get("cache")
        windows_cache = windows.get("cache")
        if isinstance(linux_cache, dict) and isinstance(windows_cache, dict):
            linux_inputs = linux_cache.get("inputs")
            windows_inputs = windows_cache.get("inputs")
            if isinstance(linux_inputs, dict) and isinstance(windows_inputs, dict):
                for field in ("python", "locks", "build_tools"):
                    if linux_inputs.get(field) != windows_inputs.get(field):
                        differences[f"cache.{field}"] = {
                            "linux": linux_inputs.get(field),
                            "windows": windows_inputs.get(field),
                        }
        linux_lanes = linux.get("lanes")
        windows_lanes = windows.get("lanes")
        if not isinstance(linux_lanes, dict) or not isinstance(windows_lanes, dict):
            linux_lanes = {}
            windows_lanes = {}
        for lane in _LANES:
            linux_record = linux_lanes.get(lane, {})
            windows_record = windows_lanes.get(lane, {})
            if not isinstance(linux_record, dict) or not isinstance(windows_record, dict):
                continue
            if linux_record.get("collection_fingerprints") != windows_record.get("collection_fingerprints"):
                differences[f"{lane}.collection_fingerprints"] = {
                    "linux": linux_record.get("collection_fingerprints"),
                    "windows": windows_record.get("collection_fingerprints"),
                }
            linux_ids = linux_record.get("executed_nodeids")
            windows_ids = windows_record.get("executed_nodeids")
            if linux_ids != windows_ids:
                differences[f"{lane}.executed_nodeids"] = {
                    "linux": linux_ids,
                    "windows": windows_ids,
                }
                continue
            linux_outcomes = linux_record.get("result_outcomes")
            windows_outcomes = windows_record.get("result_outcomes")
            if (
                not isinstance(linux_ids, list)
                or not isinstance(windows_ids, list)
                or not isinstance(linux_outcomes, list)
                or not isinstance(windows_outcomes, list)
                or len(linux_ids) != len(windows_ids)
                or len(linux_outcomes) != len(linux_ids)
                or len(windows_outcomes) != len(windows_ids)
            ):
                continue
            for index, nodeids in enumerate(linux_ids):
                linux_map = linux_outcomes[index]
                windows_map = windows_outcomes[index]
                if not isinstance(linux_map, dict) or not isinstance(windows_map, dict):
                    continue
                unexpected = {
                    nodeid: {"linux": linux_map.get(nodeid), "windows": windows_map.get(nodeid)}
                    for nodeid in nodeids
                    if linux_map.get(nodeid) != windows_map.get(nodeid)
                    and not _platform_outcome_is_allowed(
                        lane,
                        nodeid,
                        str(linux_map.get(nodeid)),
                        str(windows_map.get(nodeid)),
                    )
                }
                if unexpected:
                    differences[f"{lane}.result_outcomes[{index}]"] = unexpected
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
