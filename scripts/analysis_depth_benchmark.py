"""Measure deterministic synthetic workloads for each analysis-depth profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_cockpit.application.analysis_depth import (
    AnalysisTimingRecord,
    REFERENCE_FIXTURE_ID,
    certify_and_record_benchmark,
    certify_benchmark,
    create_resource_plan,
    execute_profiled_stages,
    load_analysis_depth_profiles,
    timing_percentiles,
)
from etf_cockpit.core.resource_profiles import detect_hardware


SYNTHETIC_FIXTURE_ID = "synthetic_test_fixture"


def run_benchmark(
    instruments_per_profile: int,
    *,
    fixture_id: str = SYNTHETIC_FIXTURE_ID,
    low_resource: bool = False,
    record_root: Path | None = None,
) -> dict[str, object]:
    """Run N deterministic local fixtures per profile and report measured SLOs."""

    if isinstance(instruments_per_profile, bool) or not isinstance(instruments_per_profile, int) or instruments_per_profile <= 0:
        raise ValueError("instruments_per_profile must be a positive integer")
    profiles = load_analysis_depth_profiles()
    profile_results: dict[str, object] = {}
    fixture_inputs = [
        [f"SYNTHETIC-{index + 1:06d}", {"fixture_index": index + 1}]
        for index in range(instruments_per_profile)
    ]
    fixture_content_digest = hashlib.sha256(
        json.dumps(fixture_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    hardware = detect_hardware()
    machine = {
        "cpu_cores": hardware.cpu_cores,
        "memory_total_mb": hardware.memory_total_mb or 0,
        "gpu_label": hardware.gpu_label,
    }

    for profile_id, profile in profiles.items():
        cache: dict[str, dict[str, object]] = {}
        plan = create_resource_plan(profile, hardware_profile="auto", low_resource=low_resource)
        measurements: list[AnalysisTimingRecord] = []
        stage_records: list[AnalysisTimingRecord] = []
        cache_hits = 0
        omitted_stages: set[str] = set()
        model_omissions: set[str] = set()

        def stage_runner(instrument_id: str, analysis_input: object, stage, _resource_plan) -> object:
            payload = json.dumps(
                [instrument_id, analysis_input, stage.to_dict()],
                sort_keys=True,
                separators=(",", ":"),
            )
            return {"fixture_digest": hashlib.sha256(payload.encode("utf-8")).hexdigest()}

        for first in range(0, instruments_per_profile, plan.shard_size):
            stop = min(instruments_per_profile, first + plan.shard_size)
            for index in range(first, stop):
                instrument_id = f"SYNTHETIC-{index + 1:06d}"
                analysis_input = {"fixture_index": index + 1}
                started = time.perf_counter()
                output, instrument_records = execute_profiled_stages(
                    profile,
                    instrument_id,
                    analysis_input,
                    "analysis-depth-benchmark.v1",
                    stage_runner,
                    cache,
                    run_id=f"benchmark-{profile_id}",
                    cache_state="cold",
                    resource_plan=plan,
                    horizons=profile.horizons,
                    seeds=profile.seeds,
                )
                stage_records.extend(instrument_records)
                instrument_cache_hits = sum(
                    1
                    for record in instrument_records
                    if record.timing_kind == "stage" and record.cache_state == "warm"
                )
                cache_hits += instrument_cache_hits
                measured_cache_state = "warm" if instrument_cache_hits > 0 else "cold"
                omitted_stages.update(output["omitted_optional_stages"])
                model_omissions.update(output["model_omissions"])
                elapsed = time.perf_counter() - started
                measurements.append(AnalysisTimingRecord(
                    run_id=f"benchmark-{profile_id}",
                    profile_id=profile_id,
                    timing_kind="stage",
                    stage_id="benchmark_instrument",
                    wall_time_seconds=elapsed,
                    cache_state=measured_cache_state,
                ))

        percentiles = timing_percentiles(measurements, profile_id=profile_id)
        peak_resources: dict[str, float] = {}
        for record in stage_records:
            for resource_name, peak in record.peak_resources:
                peak_resources[resource_name] = max(peak_resources.get(resource_name, 0.0), peak)
        certification = certify_benchmark(
            profile,
            fixture_id=SYNTHETIC_FIXTURE_ID,
            fixture_content_digest=fixture_content_digest,
            instrument_count=instruments_per_profile,
            cache_state="warm" if cache_hits > 0 else "cold",
            cache_hits=cache_hits,
            p95_seconds=float(percentiles["p95_seconds"]),
            machine=machine,
        )
        if record_root is not None:
            certify_and_record_benchmark(
                record_root,
                profile,
                run_id=f"benchmark-{profile_id}",
                records=measurements,
                fixture_id=SYNTHETIC_FIXTURE_ID,
                fixture_content_digest=fixture_content_digest,
                instrument_count=instruments_per_profile,
                cache_state="warm" if cache_hits > 0 else "cold",
                cache_hits=cache_hits,
                machine=machine,
            )
        profile_results[profile_id] = {
            "measured_instruments": len(measurements),
            "fixture_id": fixture_id,
            "fixture_content_digest": fixture_content_digest,
            "cache_state": "warm" if cache_hits > 0 else "cold",
            "cache_hits": cache_hits,
            "p50_seconds": percentiles["p50_seconds"],
            "p95_seconds": percentiles["p95_seconds"],
            "slo_seconds": profile.slo_seconds,
            "certification": certification["status"],
            "reason": certification["reason"],
            "measured_peak_resources": peak_resources,
            "omitted_optional_stages": sorted(omitted_stages),
            "model_omissions": sorted(model_omissions),
            "resource_plan": plan.to_dict(),
        }
    return {
        "schema_version": "analysis-depth-benchmark.v1",
        "reference_fixture_id": REFERENCE_FIXTURE_ID,
        "execution_allowed": False,
        "profiles": profile_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruments", type=int, default=10)
    parser.add_argument("--fixture-id", default="synthetic_test_fixture")
    parser.add_argument("--low-resource", action="store_true")
    parser.add_argument(
        "--record-root",
        type=Path,
        default=None,
        help="Project root whose data/ folder receives the stored certification verdicts (default: not stored).",
    )
    arguments = parser.parse_args(argv)
    report: dict[str, Any] = run_benchmark(
        arguments.instruments,
        fixture_id=arguments.fixture_id,
        low_resource=arguments.low_resource,
        record_root=arguments.record_root,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
