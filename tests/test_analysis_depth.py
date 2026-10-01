from __future__ import annotations

from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from etf_cockpit.application import analysis_depth
from etf_cockpit.application.analysis_depth import (
    ANALYSIS_TIMINGS_RELATIVE_PATH,
    AnalysisDepthError,
    AnalysisTimingRecord,
    MANDATORY_STAGE_IDS,
    MandatoryEvidenceError,
    REFERENCE_FIXTURE_ID,
    analysis_run_identity,
    append_timing_records,
    certify_benchmark,
    create_resource_plan,
    execute_profiled_stages,
    load_analysis_depth_profiles,
    timing_percentiles,
)
from etf_cockpit.application.bulk_run import BulkAnalysisService
from scripts.analysis_depth_benchmark import run_benchmark


def _runner(instrument_id, analysis_input, stage, resource_plan):
    values = analysis_input.get("values")
    if values is None:
        values = (analysis_input["value"],)
    result_value = 0
    for first in range(0, len(values), resource_plan.shard_size):
        chunk = values[first:first + resource_plan.shard_size]
        if resource_plan.cpu_fallback:
            for value in chunk:
                result_value += value
        else:
            result_value += sum(chunk)
    return {
        "instrument_id": instrument_id,
        "stage_id": stage.stage_id,
        "value": result_value,
    }


def test_registry_rejects_missing_mandatory_stage_and_gate_and_hashes_identity(tmp_path):
    registry_path = Path(__file__).resolve().parents[1] / "configs" / "analysis_depth_profiles.yaml"
    original = yaml.safe_load(registry_path.read_text(encoding="utf-8"))

    for profile_id in ("quick", "medium", "high", "full"):
        for removed_stage in ("identity_gate", "hard_risk_gate"):
            mutated = copy.deepcopy(original)
            mutated["profiles"][profile_id]["mandatory_stages"].remove(removed_stage)
            path = tmp_path / f"{profile_id}-{removed_stage}.yaml"
            path.write_text(yaml.safe_dump(mutated), encoding="utf-8")
            with pytest.raises(AnalysisDepthError, match="mandatory stage or gate"):
                load_analysis_depth_profiles(path)

    profiles = load_analysis_depth_profiles()
    profile = profiles["quick"]
    changed = replace(profile, sources=(*profile.sources, "additional_configured_source"))
    inputs = {"ETF.TEST": {"value": 2}}
    assert profile.mandatory_stages == MANDATORY_STAGE_IDS
    assert profile.manifest_hash != changed.manifest_hash
    assert analysis_run_identity(inputs, "tests.depth.v1", profile) != analysis_run_identity(
        inputs,
        "tests.depth.v1",
        changed,
    )


def test_quick_and_full_preserve_shared_deterministic_fields_and_declared_stage_differences(tmp_path):
    quick_root = tmp_path / "quick"
    full_root = tmp_path / "full"
    quick_root.mkdir()
    full_root.mkdir()
    quick_service = BulkAnalysisService(quick_root)
    full_service = BulkAnalysisService(full_root)
    inputs = {"ETF.TEST": {"value": 4.25}}
    quick_calls = []
    full_calls = []

    def quick_runner(instrument_id, analysis_input, stage, resource_plan):
        quick_calls.append(stage.stage_id)
        return _runner(instrument_id, analysis_input, stage, resource_plan)

    def full_runner(instrument_id, analysis_input, stage, resource_plan):
        full_calls.append(stage.stage_id)
        return _runner(instrument_id, analysis_input, stage, resource_plan)

    quick = quick_service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        cache_state="cold",
        stage_runner=quick_runner,
    )
    assert "ETF.TEST" in quick.results, quick.failures
    full = full_service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="full",
        cache_state="cold",
        stage_runner=full_runner,
    )
    assert "ETF.TEST" in full.results, full.failures
    quick_output = quick.results["ETF.TEST"]
    full_output = full.results["ETF.TEST"]
    quick_profile = load_analysis_depth_profiles()["quick"]
    full_profile = load_analysis_depth_profiles()["full"]

    assert quick_output["deterministic_fields"] == full_output["deterministic_fields"]
    assert set(quick_output["deterministic_fields"]) == set(MANDATORY_STAGE_IDS)
    assert set(MANDATORY_STAGE_IDS).issubset(quick_calls)
    assert set(MANDATORY_STAGE_IDS).issubset(full_calls)
    assert set(full_output["stages"]) - set(quick_output["stages"]) == (
        set(full_profile.optional_stages) - set(quick_profile.optional_stages)
    )
    assert set(quick_output["stages"]) - set(full_output["stages"]) == (
        set(quick_profile.optional_stages) - set(full_profile.optional_stages)
    )
    for stage_id in MANDATORY_STAGE_IDS:
        assert full_output["stage_hashes"][stage_id]["content_hash"] == quick_output["stage_hashes"][stage_id]["content_hash"]
        assert quick_output["stage_hashes"][stage_id]["reused"] is False
        assert full_output["stage_hashes"][stage_id]["reused"] is False


def test_missing_mandatory_evidence_fails_with_reason_without_downgrade(tmp_path):
    service = BulkAnalysisService(tmp_path)

    def incomplete(_instrument_id, _analysis_input, stage, _resource_plan):
        if stage.stage_id == "hard_risk_gate":
            return None
        return {"stage_id": stage.stage_id, "passed": True}

    run = service.start(
        {"ETF.TEST": {"value": 1}},
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        stage_runner=incomplete,
    )

    assert run.status == "failed"
    assert "mandatory evidence missing for stage hard_risk_gate" in run.failures["ETF.TEST"]
    assert run.results == {}
    timing_path = service.scheduler.root / ANALYSIS_TIMINGS_RELATIVE_PATH
    timing_frame = pd.read_parquet(timing_path)
    assert timing_frame["stage_id"].tolist() == list(MANDATORY_STAGE_IDS[:4])
    assert timing_frame["outcome"].tolist() == ["succeeded", "succeeded", "succeeded", "failed"]


def test_mandatory_runner_exception_keeps_prior_and_failed_stage_timings():
    profile = load_analysis_depth_profiles()["quick"]
    failure = RuntimeError("evidence unavailable")

    def runner(instrument_id, analysis_input, stage, resource_plan):
        if stage.stage_id == "hard_risk_gate":
            raise failure
        return _runner(instrument_id, analysis_input, stage, resource_plan)

    with pytest.raises(MandatoryEvidenceError) as caught:
        execute_profiled_stages(
            profile,
            "ETF.TEST",
            {"value": 1},
            "tests.depth.v1",
            runner,
            {},
            run_id="failed-stage-test",
            resource_plan=create_resource_plan(profile),
        )

    assert caught.value.__cause__ is failure
    records = caught.value.timing_records
    assert [record.stage_id for record in records] == list(MANDATORY_STAGE_IDS[:4])
    assert [record.outcome for record in records] == ["succeeded", "succeeded", "succeeded", "failed"]
    assert records[-1].wall_time_seconds >= 0


def test_optional_runner_exception_keeps_its_existing_type():
    profile = load_analysis_depth_profiles()["full"]
    optional_stage = next(stage for stage in profile.stages if not stage.mandatory)
    one_stage_profile = replace(profile, stages=(optional_stage,))
    failure = RuntimeError("optional stage unavailable")

    def runner(_instrument_id, _analysis_input, _stage, _resource_plan):
        raise failure

    with pytest.raises(RuntimeError) as caught:
        execute_profiled_stages(
            one_stage_profile,
            "ETF.TEST",
            {"value": 1},
            "tests.depth.v1",
            runner,
            {},
            run_id="optional-stage-test",
            resource_plan=create_resource_plan(one_stage_profile),
        )

    assert caught.value is failure


def test_stage_timing_excludes_acquisition_and_training_with_fake_clock(monkeypatch):
    profile = load_analysis_depth_profiles()["quick"]
    one_stage_profile = replace(profile, stages=(profile.stages[0],))
    resource_plan = create_resource_plan(one_stage_profile)
    reported = {"cold_acquisition_seconds": 5.0, "training_centre_seconds": 8.0}

    def runner(_instrument_id, _analysis_input, stage, _resource_plan):
        return {
            "analysis_depth_result": {"stage_id": stage.stage_id},
            "analysis_depth_timing": reported,
        }

    clock_ticks = iter((1.0, 2.0, 22.0))
    monkeypatch.setattr(analysis_depth.time, "perf_counter", lambda: next(clock_ticks))
    _output, records = execute_profiled_stages(
        one_stage_profile,
        "ETF.TEST",
        {"value": 1},
        "tests.depth.timing.v1",
        runner,
        {},
        run_id="timing-test",
        resource_plan=resource_plan,
    )
    stage_record = next(record for record in records if record.timing_kind == "stage")
    separate = {record.timing_kind: record.wall_time_seconds for record in records if record.timing_kind != "stage"}
    assert stage_record.wall_time_seconds == 7.0
    assert separate == {"cold_acquisition": 5.0, "training_centre": 8.0}

    reported["cold_acquisition_seconds"] = 15.0
    clock_ticks = iter((1.0, 2.0, 22.0))
    monkeypatch.setattr(analysis_depth.time, "perf_counter", lambda: next(clock_ticks))
    with pytest.raises(AnalysisDepthError, match="exceeds stage runner wall time"):
        execute_profiled_stages(
            one_stage_profile,
            "ETF.TEST",
            {"value": 1},
            "tests.depth.timing.v1",
            runner,
            {},
            run_id="timing-inconsistent-test",
            resource_plan=resource_plan,
        )


def test_quick_to_high_upgrade_links_new_run_and_reuses_cached_hashes(tmp_path):
    service = BulkAnalysisService(tmp_path)
    calls: list[str] = []

    def tracked(instrument_id, analysis_input, stage, _resource_plan):
        calls.append(stage.stage_id)
        return _runner(instrument_id, analysis_input, stage, _resource_plan)

    quick = service.start(
        {"ETF.TEST": {"value": 7}},
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        stage_runner=tracked,
    )
    original = service.get_run(quick.run_id)
    calls_before_upgrade = tuple(calls)
    high = service.upgrade(
        quick.run_id,
        "high",
        analyzer_id="tests.depth.v1",
        stage_runner=tracked,
    )
    link = service.get_upgrade_link(high.run_id)
    high_output = high.results["ETF.TEST"]

    assert high.run_id != quick.run_id
    assert link is not None
    assert link.parent_run_id == quick.run_id
    assert link.child_run_id == high.run_id
    assert link.from_profile == "quick" and link.to_profile == "high"
    assert len(link.reused_stage_hashes) >= len(MANDATORY_STAGE_IDS)
    assert all(high_output["stage_hashes"][stage_id]["reused"] for stage_id in MANDATORY_STAGE_IDS)
    assert tuple(calls[:len(calls_before_upgrade)]) == calls_before_upgrade
    assert set(calls[len(calls_before_upgrade):]).isdisjoint(MANDATORY_STAGE_IDS)
    assert service.get_run(quick.run_id) == original


def test_timing_records_separate_cold_warm_training_and_benchmark_certification(tmp_path):
    records = (
        AnalysisTimingRecord(
            "run-a",
            "quick",
            "stage",
            "prices_gate",
            1.0,
            "warm",
            0.1,
            ("deterministic_baseline",),
            (("python_heap_peak_mb", 1.5),),
        ),
        AnalysisTimingRecord("run-b", "quick", "stage", "prices_gate", 3.0, "cold", 0.2),
        AnalysisTimingRecord("run-a", "quick", "cold_acquisition", "prices_gate", 5.0, "cold"),
        AnalysisTimingRecord("run-a", "quick", "training_centre", "training", 8.0, "warm"),
    )
    target = append_timing_records(tmp_path, records)
    frame = pd.read_parquet(target)
    percentiles = timing_percentiles(records, profile_id="quick", timing_kind="stage")
    assert set(frame["timing_kind"]) == {"stage", "cold_acquisition", "training_centre"}
    assert set(frame["cache_state"]) == {"cold", "warm"}
    assert json.loads(frame.iloc[0]["peak_resources"]) == {"python_heap_peak_mb": 1.5}
    assert frame.iloc[0]["model_omissions"] == ["deterministic_baseline"]
    assert percentiles == {"sample_count": 2, "p50_seconds": 2.0, "p95_seconds": 2.9}

    report = run_benchmark(2)
    assert all(item["certification"] == "not_certified" for item in report["profiles"].values())
    assert "declared reference fixture" in report["profiles"]["quick"]["reason"]
    assert "python_heap_peak_mb" in report["profiles"]["quick"]["measured_peak_resources"]
    profile = load_analysis_depth_profiles()["quick"]
    over_slo = certify_benchmark(
        profile,
        fixture_id=profile.reference_fixture_id,
        fixture_content_digest=hashlib.sha256(b"over-slo-test-fixture").hexdigest(),
        instrument_count=3000,
        cache_state="warm",
        cache_hits=1,
        p95_seconds=profile.slo_seconds + 1,
        machine={"cpu_cores": 20, "memory_mb": 32768, "gpu_label": "RTX 5070"},
    )
    assert over_slo["status"] == "not_certified"
    assert "exceeded" in over_slo["reason"]
    fixture_digest = hashlib.sha256(b"declared-test-reference-fixture").hexdigest()
    declared_profile = replace(profile, reference_fixture_digest=fixture_digest)
    matching_digest = certify_benchmark(
        declared_profile,
        fixture_id=declared_profile.reference_fixture_id,
        fixture_content_digest=fixture_digest,
        instrument_count=3000,
        cache_state="warm",
        cache_hits=1,
        p95_seconds=1.0,
        machine={
            "cpu_cores": profile.reference_cpu_cores,
            "memory_mb": profile.reference_memory_mb,
            "gpu_label": profile.reference_gpu_label,
        },
    )
    mismatched_digest = certify_benchmark(
        declared_profile,
        fixture_id=declared_profile.reference_fixture_id,
        fixture_content_digest=hashlib.sha256(b"different-test-fixture").hexdigest(),
        instrument_count=3000,
        cache_state="warm",
        cache_hits=1,
        p95_seconds=1.0,
        machine={
            "cpu_cores": profile.reference_cpu_cores,
            "memory_mb": profile.reference_memory_mb,
            "gpu_label": profile.reference_gpu_label,
        },
    )
    assert matching_digest["status"] == "certified"
    assert mismatched_digest["status"] == "not_certified"
    assert "does not match" in mismatched_digest["reason"]


def test_synthetic_reference_label_is_not_certified_and_cache_misses_stay_cold():
    report = run_benchmark(3000, fixture_id=REFERENCE_FIXTURE_ID)
    for result in report["profiles"].values():
        assert result["fixture_id"] == REFERENCE_FIXTURE_ID
        assert result["cache_state"] == "cold"
        assert result["cache_hits"] == 0
        assert result["certification"] == "not_certified"
        assert "declared reference fixture" in result["reason"]
        assert "content digest" in result["reason"]

    quick_profile = load_analysis_depth_profiles()["quick"]
    profile = replace(quick_profile, stages=(quick_profile.stages[0],))
    cache = {}
    cold_output, cold_records = execute_profiled_stages(
        profile,
        "ETF.CACHE",
        {"value": 3},
        "tests.depth.cache.v1",
        _runner,
        cache,
        run_id="cache-cold",
        cache_state="warm",
        resource_plan=create_resource_plan(profile),
    )
    warm_output, warm_records = execute_profiled_stages(
        profile,
        "ETF.CACHE",
        {"value": 3},
        "tests.depth.cache.v1",
        _runner,
        cache,
        run_id="cache-warm",
        cache_state="cold",
        resource_plan=create_resource_plan(profile),
    )
    assert cold_output["deterministic_fields"] == warm_output["deterministic_fields"]
    assert all(record.cache_state == "cold" for record in cold_records)
    assert all(record.cache_state == "warm" for record in warm_records)


def test_low_resource_mode_changes_sharding_not_mandatory_results_or_hashes(tmp_path):
    normal_root = tmp_path / "normal"
    low_resource_root = tmp_path / "low-resource"
    normal_root.mkdir()
    low_resource_root.mkdir()
    normal_service = BulkAnalysisService(normal_root)
    low_resource_service = BulkAnalysisService(low_resource_root)
    inputs = {"ETF.TEST": {"value": 11.5}}
    calls = {"normal": [], "low_resource": []}
    observed_plans = {}

    def normal_runner(instrument_id, analysis_input, stage, resource_plan):
        calls["normal"].append(stage.stage_id)
        observed_plans["normal"] = resource_plan
        return _runner(instrument_id, analysis_input, stage, resource_plan)

    def low_resource_runner(instrument_id, analysis_input, stage, resource_plan):
        calls["low_resource"].append(stage.stage_id)
        observed_plans["low_resource"] = resource_plan
        return _runner(instrument_id, analysis_input, stage, resource_plan)

    normal = normal_service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        cache_state="cold",
        stage_runner=normal_runner,
    )
    assert "ETF.TEST" in normal.results, normal.failures
    low_resource = low_resource_service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        hardware_profile="minimum",
        low_resource=True,
        cache_state="cold",
        stage_runner=low_resource_runner,
    )
    assert "ETF.TEST" in low_resource.results, low_resource.failures
    normal_manifest = normal_service.get_depth_manifest(normal.run_id)
    low_manifest = low_resource_service.get_depth_manifest(low_resource.run_id)
    normal_output = normal.results["ETF.TEST"]
    low_output = low_resource.results["ETF.TEST"]

    assert normal_output["deterministic_fields"] == low_output["deterministic_fields"]
    assert set(MANDATORY_STAGE_IDS).issubset(calls["normal"])
    assert set(MANDATORY_STAGE_IDS).issubset(calls["low_resource"])
    for stage_id in MANDATORY_STAGE_IDS:
        assert normal_output["stage_hashes"][stage_id]["content_hash"] == low_output["stage_hashes"][stage_id]["content_hash"]
        assert normal_output["stage_hashes"][stage_id]["reused"] is False
        assert low_output["stage_hashes"][stage_id]["reused"] is False
    assert normal_manifest["run_identity"] == low_manifest["run_identity"]
    assert low_manifest["resource_plan"]["shard_size"] < normal_manifest["resource_plan"]["shard_size"]
    assert low_manifest["resource_plan"]["cpu_fallback"] is True
    assert observed_plans["normal"].shard_size == normal_manifest["resource_plan"]["shard_size"]
    assert observed_plans["low_resource"].low_resource is True
    assert observed_plans["low_resource"].cpu_fallback is True
