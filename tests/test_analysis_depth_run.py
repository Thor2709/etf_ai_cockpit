from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.application.analysis_depth import (
    ANALYSIS_CERTIFICATIONS_RELATIVE_PATH,
    ANALYSIS_TIMINGS_RELATIVE_PATH,
    AnalysisDepthError,
    AnalysisTimingRecord,
    ProfileRunBinding,
    certify_and_record_benchmark,
    load_analysis_depth_profiles,
    read_certification,
    run_analysis_profile,
)


def _binding(calls: list[str], *, on_stage=None, fail_stage: str | None = None) -> ProfileRunBinding:
    def runner(instrument_id, analysis_input, stage, _plan):
        calls.append(stage.stage_id)
        if on_stage is not None:
            on_stage(stage.stage_id)
        if stage.stage_id == fail_stage:
            raise RuntimeError("provider exploded")
        return {"instrument_id": instrument_id, "stage_id": stage.stage_id, "value": 1}

    return ProfileRunBinding("ETF-A", {"value": 1}, "run-profile-test.v1", runner)


def test_facade_runs_stages_in_order_reports_progress_and_stores_timings(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["quick"]
    calls: list[str] = []
    events = []
    result = run_analysis_profile(profile, _binding(calls), root=tmp_path, on_progress=events.append)
    expected = [stage.stage_id for stage in profile.stages]
    assert result.status == "completed" and result.reason is None
    assert calls == expected and list(result.completed_stages) == expected
    assert [(e.stage_index, e.state) for e in events if e.state == "running"] == [
        (index, "running") for index in range(1, len(expected) + 1)
    ]
    assert [e.stage_id for e in events if e.state == "completed"] == expected
    assert all(e.total_stages == len(expected) for e in events)
    stored = pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)
    assert set(stored["run_id"]) == {result.run_id} and len(stored) == len(expected)


def test_cancel_stops_between_stages_and_resume_reuses_completed_stages(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["medium"]
    calls: list[str] = []
    cancelled = {"flag": False}
    first_stage = profile.stages[0].stage_id

    def cancel_after_first_completes(event) -> None:
        if event.state == "completed" and event.stage_id == first_stage:
            cancelled["flag"] = True  # the user clicks Cancel between stage 1 and stage 2

    cache: dict = {}
    result = run_analysis_profile(
        profile,
        _binding(calls),
        root=tmp_path,
        cache=cache,
        on_progress=cancel_after_first_completes,
        is_cancel_requested=lambda: cancelled["flag"],
    )
    assert result.status == "cancelled" and result.resumable
    assert calls == [first_stage]  # the next stage never started
    assert result.completed_stages == (first_stage,) and result.total_stages == len(profile.stages)
    assert "cancelled" in set(pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)["outcome"])
    cancelled["flag"] = False
    resumed_calls: list[str] = []
    resumed = run_analysis_profile(profile, _binding(resumed_calls), root=tmp_path, cache=cache)
    assert resumed.status == "completed"
    assert first_stage not in resumed_calls  # reused from the same-session cache, not recomputed


def test_stage_failure_stops_the_run_failed_with_reason_and_stores_timings(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["quick"]
    stages = [stage.stage_id for stage in profile.stages]
    broken = stages[2]
    calls: list[str] = []
    result = run_analysis_profile(profile, _binding(calls, fail_stage=broken), root=tmp_path)
    assert result.status == "failed" and result.output is None
    assert broken in (result.reason or "") and "provider exploded" in (result.reason or "")
    assert calls == stages[:3]  # fail closed: nothing after the failed stage ran
    stored = pd.read_parquet(tmp_path / ANALYSIS_TIMINGS_RELATIVE_PATH)
    assert stored[stored["stage_id"] == broken]["outcome"].tolist() == ["failed"]


def _records(profile_id: str, run_id: str, seconds: list[float], outcome: str = "succeeded"):
    return [
        AnalysisTimingRecord(run_id, profile_id, "stage", "benchmark_instrument", value, "warm", outcome=outcome)
        for value in seconds
    ]


def test_certification_store_round_trip_and_never_certified_without_a_measured_run(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["quick"]
    assert read_certification(tmp_path, "quick") is None  # nothing stored -> no verdict
    with pytest.raises(AnalysisDepthError, match="measured timing records"):
        certify_and_record_benchmark(
            tmp_path, profile, run_id="r0", records=[], fixture_id=profile.reference_fixture_id,
            fixture_content_digest=profile.reference_fixture_digest, instrument_count=3000,
            cache_state="warm", cache_hits=1, machine=None,
        )
    assert not (tmp_path / ANALYSIS_CERTIFICATIONS_RELATIVE_PATH).exists()  # nothing was stored either
    row = certify_and_record_benchmark(
        tmp_path, profile, run_id="r1", records=_records("quick", "r1", [1.0, 2.0, 3.0]),
        fixture_id="synthetic_test_fixture", fixture_content_digest="0" * 64, instrument_count=3,
        cache_state="warm", cache_hits=2, machine={"cpu_cores": 2, "memory_total_mb": 1024, "gpu_label": ""},
    )
    assert row["status"] == "not_certified" and row["sample_count"] == 3
    stored = read_certification(tmp_path, "quick", manifest_hash=profile.manifest_hash)
    assert stored is not None and stored["run_id"] == "r1" and stored["status"] == "not_certified"
    assert stored["p95_seconds"] == pytest.approx(2.9) and stored["slo_seconds"] == profile.slo_seconds
    assert read_certification(tmp_path, "quick", manifest_hash="other-manifest") is None
    assert read_certification(tmp_path, "medium") is None
    # a run with a failed stage can never be certified, whatever its timings are
    failed = certify_and_record_benchmark(
        tmp_path, profile, run_id="r2", records=_records("quick", "r2", [1.0], outcome="failed"),
        fixture_id=profile.reference_fixture_id, fixture_content_digest=profile.reference_fixture_digest,
        instrument_count=3000, cache_state="warm", cache_hits=1,
        machine={"cpu_cores": 64, "memory_total_mb": 10**6, "gpu_label": profile.reference_gpu_label},
    )
    assert failed["status"] == "not_certified" and "failed" in str(failed["reason"])


def test_a_tampered_certified_row_without_a_passing_measurement_reads_as_not_certified(tmp_path) -> None:
    profile = load_analysis_depth_profiles()["quick"]
    certify_and_record_benchmark(
        tmp_path, profile, run_id="r1", records=_records("quick", "r1", [profile.slo_seconds * 2]),
        fixture_id="synthetic_test_fixture", fixture_content_digest="0" * 64, instrument_count=1,
        cache_state="warm", cache_hits=1, machine=None,
    )
    path = tmp_path / ANALYSIS_CERTIFICATIONS_RELATIVE_PATH
    frame = pd.read_parquet(path)
    frame["status"] = "certified"  # hand-edited: p95 is above the target
    frame.to_parquet(path, index=False)
    stored = read_certification(tmp_path, "quick")
    assert stored is not None and stored["status"] == "not_certified" and "measured run" in str(stored["reason"])
