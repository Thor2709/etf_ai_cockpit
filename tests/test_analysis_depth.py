from __future__ import annotations

from dataclasses import replace
import copy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from etf_cockpit.application.analysis_depth import (
    AnalysisDepthError,
    AnalysisTimingRecord,
    MANDATORY_STAGE_IDS,
    analysis_run_identity,
    append_timing_records,
    certify_benchmark,
    load_analysis_depth_profiles,
    timing_percentiles,
)
from etf_cockpit.application.bulk_run import BulkAnalysisService
from scripts.analysis_depth_benchmark import run_benchmark


def _runner(instrument_id, analysis_input, stage, _resource_plan):
    return {
        "instrument_id": instrument_id,
        "stage_id": stage.stage_id,
        "value": analysis_input["value"],
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
    service = BulkAnalysisService(tmp_path)
    inputs = {"ETF.TEST": {"value": 4.25}}
    quick = service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        stage_runner=_runner,
    )
    full = service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="full",
        stage_runner=_runner,
    )
    quick_output = quick.results["ETF.TEST"]
    full_output = full.results["ETF.TEST"]
    quick_profile = load_analysis_depth_profiles()["quick"]
    full_profile = load_analysis_depth_profiles()["full"]

    assert quick_output["deterministic_fields"] == full_output["deterministic_fields"]
    assert set(quick_output["deterministic_fields"]) == set(MANDATORY_STAGE_IDS)
    assert set(full_output["stages"]) - set(quick_output["stages"]) == (
        set(full_profile.optional_stages) - set(quick_profile.optional_stages)
    )
    assert set(quick_output["stages"]) - set(full_output["stages"]) == (
        set(quick_profile.optional_stages) - set(full_profile.optional_stages)
    )
    for stage_id in MANDATORY_STAGE_IDS:
        assert full_output["stage_hashes"][stage_id]["content_hash"] == quick_output["stage_hashes"][stage_id]["content_hash"]


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
        instrument_count=3000,
        cache_state="warm",
        p95_seconds=profile.slo_seconds + 1,
        machine={"cpu_cores": 20, "memory_mb": 32768, "gpu_label": "RTX 5070"},
    )
    assert over_slo["status"] == "not_certified"
    assert "exceeded" in over_slo["reason"]


def test_low_resource_mode_changes_sharding_not_mandatory_results_or_hashes(tmp_path):
    service = BulkAnalysisService(tmp_path)
    inputs = {"ETF.TEST": {"value": 11.5}}
    normal = service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        stage_runner=_runner,
    )
    low_resource = service.start(
        inputs,
        analyzer_id="tests.depth.v1",
        depth_profile="quick",
        stage_runner=_runner,
        hardware_profile="minimum",
        low_resource=True,
    )
    normal_manifest = service.get_depth_manifest(normal.run_id)
    low_manifest = service.get_depth_manifest(low_resource.run_id)
    normal_output = normal.results["ETF.TEST"]
    low_output = low_resource.results["ETF.TEST"]

    assert normal_output["deterministic_fields"] == low_output["deterministic_fields"]
    for stage_id in MANDATORY_STAGE_IDS:
        assert normal_output["stage_hashes"][stage_id]["content_hash"] == low_output["stage_hashes"][stage_id]["content_hash"]
    assert normal_manifest["run_identity"] == low_manifest["run_identity"]
    assert low_manifest["resource_plan"]["shard_size"] < normal_manifest["resource_plan"]["shard_size"]
    assert low_manifest["resource_plan"]["cpu_fallback"] is True
