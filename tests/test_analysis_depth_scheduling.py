from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Lock

import pandas as pd
import pytest

from etf_cockpit.application import analysis_depth, bulk_run
from etf_cockpit.application.analysis_depth import (
    ANALYSIS_TIMINGS_RELATIVE_PATH,
    MANDATORY_STAGE_IDS,
    AnalysisDepthError,
    load_analysis_depth_profiles,
)
from etf_cockpit.application.bulk_run import BulkAnalysisService
from etf_cockpit.core.resource_profiles import HardwareSnapshot, estimate_workflow_resources


def _install_plan_estimate(monkeypatch, *, cpu=3.0, memory_mb=1_536, disk_mb=4_096):
    monkeypatch.setattr(
        analysis_depth,
        "estimate_workflow_resources",
        lambda _workflow_type, *, requested_profile="auto", snapshot=None: {
            "profile": "high",
            "cpu": cpu,
            "memory_mb": memory_mb,
            "disk_mb": disk_mb,
            "status": "allowed",
            "reasons": [],
        },
    )


def _set_test_hardware(service, *, max_concurrency=3):
    policy = service.scheduler.resource_policy
    policy.profile_id = "high"
    policy.snapshot = HardwareSnapshot(
        platform="test",
        cpu_cores=4,
        memory_total_mb=65_536,
        memory_available_mb=65_536,
        disk_free_mb=131_072,
        gpu_available=False,
        gpu_label="unavailable",
    )
    service.scheduler.max_concurrency = max_concurrency


def _successful_stage_runner(_instrument_id, _analysis_input, stage, _resource_plan):
    return {"stage_id": stage.stage_id, "passed": True}


def test_profile_jobs_reserve_plan_resources_and_legacy_defaults(monkeypatch, tmp_path):
    _install_plan_estimate(monkeypatch)
    service = BulkAnalysisService(tmp_path)
    _set_test_hardware(service)
    observed_plans = []

    def stage_runner(instrument_id, analysis_input, stage, resource_plan):
        observed_plans.append(resource_plan)
        return _successful_stage_runner(instrument_id, analysis_input, stage, resource_plan)

    profiled = service.start(
        {"ETF.A": {"value": 1}},
        analyzer_id="tests.depth.resources.v1",
        depth_profile="quick",
        stage_runner=stage_runner,
    )
    workflow = service.scheduler.get_workflow(profiled.run_id)
    plan = workflow.inputs["analysis_depth"]["resource_plan"]
    profiled_job = service.scheduler.list_jobs(profiled.run_id)[0]
    assert profiled_job.resources == {
        "profile": plan["hardware_profile_id"],
        "cpu": plan["estimated_cpu"],
        "memory_mb": plan["estimated_memory_mb"],
        "disk_mb": plan["estimated_disk_mb"],
    }
    assert observed_plans
    assert all(
        (runner_plan.estimated_cpu, runner_plan.estimated_memory_mb, runner_plan.estimated_disk_mb)
        == (plan["estimated_cpu"], plan["estimated_memory_mb"], plan["estimated_disk_mb"])
        for runner_plan in observed_plans
    )

    legacy = service.start(
        {"ETF.B": {"value": 2}},
        lambda _instrument_id, value: value,
        analyzer_id="tests.bulk.resources.v1",
        max_jobs=0,
    )
    legacy_job = service.scheduler.list_jobs(legacy.run_id)[0]
    legacy_estimate = estimate_workflow_resources(
        "bulk_analysis",
        requested_profile=service.scheduler.resource_policy.requested_profile,
        snapshot=service.scheduler.resource_policy.snapshot,
    )
    assert legacy_job.resources == {
        "profile": legacy_estimate["profile"],
        "cpu": legacy_estimate["cpu"],
        "memory_mb": legacy_estimate["memory_mb"],
        "disk_mb": legacy_estimate["disk_mb"],
    }


def test_profile_workers_obey_requested_and_scheduler_limits(monkeypatch, tmp_path):
    _install_plan_estimate(monkeypatch, cpu=1.0)
    original_create_plan = bulk_run.create_resource_plan

    def three_worker_plan(*args, **kwargs):
        return replace(original_create_plan(*args, **kwargs), concurrency_limit=3)

    monkeypatch.setattr(bulk_run, "create_resource_plan", three_worker_plan)
    parallel = BulkAnalysisService(tmp_path / "parallel")
    _set_test_hardware(parallel)
    barrier = Barrier(3, timeout=5)
    active = 0
    maximum_active = 0
    active_lock = Lock()

    def barrier_runner(instrument_id, analysis_input, stage, resource_plan):
        nonlocal active, maximum_active
        with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            if stage.stage_id == MANDATORY_STAGE_IDS[0]:
                barrier.wait()
            return _successful_stage_runner(instrument_id, analysis_input, stage, resource_plan)
        finally:
            with active_lock:
                active -= 1

    parallel_run = parallel.start(
        {f"ETF.{index}": {"value": index} for index in range(3)},
        analyzer_id="tests.depth.parallel.v1",
        depth_profile="quick",
        stage_runner=barrier_runner,
    )
    assert parallel_run.coverage_completed == parallel_run.coverage_total == 3
    assert parallel_run.status == "succeeded", parallel_run.failures
    assert maximum_active == 3

    sequential = BulkAnalysisService(tmp_path / "sequential")
    _set_test_hardware(sequential, max_concurrency=1)
    active = 0
    maximum_active = 0

    def sequential_runner(instrument_id, analysis_input, stage, resource_plan):
        nonlocal active, maximum_active
        with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            return _successful_stage_runner(instrument_id, analysis_input, stage, resource_plan)
        finally:
            with active_lock:
                active -= 1

    sequential_run = sequential.start(
        {f"ETF.{index}": {"value": index} for index in range(3)},
        analyzer_id="tests.depth.sequential.v1",
        depth_profile="quick",
        stage_runner=sequential_runner,
    )
    assert sequential_run.coverage_completed == sequential_run.coverage_total == 3
    assert maximum_active == 1


def test_profile_claims_respect_full_resource_reservations(monkeypatch, tmp_path):
    _install_plan_estimate(monkeypatch, cpu=2.0)
    original_create_plan = bulk_run.create_resource_plan

    def three_worker_plan(*args, **kwargs):
        return replace(original_create_plan(*args, **kwargs), concurrency_limit=3)

    monkeypatch.setattr(bulk_run, "create_resource_plan", three_worker_plan)
    service = BulkAnalysisService(tmp_path)
    _set_test_hardware(service, max_concurrency=3)
    barrier = Barrier(2, timeout=5)
    active = 0
    maximum_active = 0
    first_stage_arrivals = 0
    active_lock = Lock()

    def barrier_runner(instrument_id, analysis_input, stage, resource_plan):
        nonlocal active, first_stage_arrivals, maximum_active
        with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            wait_for_pair = stage.stage_id == MANDATORY_STAGE_IDS[0] and first_stage_arrivals < 2
            if wait_for_pair:
                first_stage_arrivals += 1
        try:
            if wait_for_pair:
                barrier.wait()
            return _successful_stage_runner(instrument_id, analysis_input, stage, resource_plan)
        finally:
            with active_lock:
                active -= 1

    run = service.start(
        {f"ETF.{index}": {"value": index} for index in range(3)},
        analyzer_id="tests.depth.resource-admission.v1",
        depth_profile="quick",
        stage_runner=barrier_runner,
    )

    assert run.status == "succeeded", run.failures
    assert maximum_active == 2
    workflow = service.scheduler.get_workflow(run.run_id)
    plan = workflow.inputs["analysis_depth"]["resource_plan"]
    assert plan["concurrency_limit"] == 3
    assert plan["estimated_cpu"] == 2.0
    assert all(job.resources["cpu"] == 2.0 for job in service.scheduler.list_jobs(run.run_id))


def test_concurrent_cache_and_timing_writes_match_sequential_outputs(monkeypatch, tmp_path):
    _install_plan_estimate(monkeypatch, cpu=2.0)
    service = BulkAnalysisService(tmp_path)
    _set_test_hardware(service)
    barrier = Barrier(2, timeout=5)

    def barrier_runner(instrument_id, analysis_input, stage, resource_plan):
        if stage.stage_id == MANDATORY_STAGE_IDS[0]:
            barrier.wait()
        return {
            "stage_id": stage.stage_id,
            "instrument_id": instrument_id,
            "value": analysis_input["value"],
            "passed": True,
        }

    run_args = {
        "inputs": {"ETF.A": {"value": 7}},
        "analyzer_id": "tests.depth.cache.v1",
        "depth_profile": "quick",
        "stage_runner": barrier_runner,
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(service.start, **run_args)
        second_future = executor.submit(service.start, **run_args)
        concurrent_runs = (first_future.result(), second_future.result())

    assert all(run.status == "succeeded" for run in concurrent_runs), [run.failures for run in concurrent_runs]
    sequential_run = service.start(**run_args)
    expected_stages = concurrent_runs[0].results["ETF.A"]["stages"]
    assert concurrent_runs[1].results["ETF.A"]["stages"] == expected_stages
    assert sequential_run.results["ETF.A"]["stages"] == expected_stages

    timing_frame = pd.read_parquet(service.scheduler.root / ANALYSIS_TIMINGS_RELATIVE_PATH)
    profile_stage_count = len(load_analysis_depth_profiles()["quick"].stages)
    for run in (*concurrent_runs, sequential_run):
        records = timing_frame[timing_frame["run_id"] == run.run_id]
        counts = Counter(zip(records["timing_kind"], records["stage_id"]))
        assert len(records) == profile_stage_count
        assert all(count == 1 for count in counts.values())


def test_cancelled_stage_is_timed_and_new_run_reuses_prior_cache(monkeypatch, tmp_path):
    _install_plan_estimate(monkeypatch)
    service = BulkAnalysisService(tmp_path)
    _set_test_hardware(service, max_concurrency=1)
    run_id = "bulk_cancelled_stage_test"
    inputs = {"ETF.CANCEL": {"value": 9}}
    queued = service.start(
        inputs,
        analyzer_id="tests.depth.cancel.v1",
        depth_profile="quick",
        stage_runner=_successful_stage_runner,
        max_jobs=0,
        _run_id=run_id,
    )
    cancelled_stages = []

    def cancel_in_stage_two(instrument_id, analysis_input, stage, resource_plan):
        cancelled_stages.append(stage.stage_id)
        if stage.stage_id == MANDATORY_STAGE_IDS[1]:
            service.scheduler.cancel(run_id)
        return _successful_stage_runner(instrument_id, analysis_input, stage, resource_plan)

    cancelled = service._execute(run_id, None, 1, cancel_in_stage_two)
    assert cancelled.status == "cancelled", cancelled.failures
    assert cancelled_stages == list(MANDATORY_STAGE_IDS[:2])
    assert MANDATORY_STAGE_IDS[2] not in cancelled_stages

    timing_path = service.scheduler.root / ANALYSIS_TIMINGS_RELATIVE_PATH
    timing_frame = pd.read_parquet(timing_path)
    cancelled_records = timing_frame[timing_frame["run_id"] == run_id]
    assert cancelled_records["stage_id"].tolist() == list(MANDATORY_STAGE_IDS[:2])
    assert cancelled_records["outcome"].tolist() == ["succeeded", "cancelled"]

    rerun_stages = []

    def rerun_stage(instrument_id, analysis_input, stage, resource_plan):
        rerun_stages.append(stage.stage_id)
        return _successful_stage_runner(instrument_id, analysis_input, stage, resource_plan)

    rerun = service.start(
        inputs,
        analyzer_id="tests.depth.cancel.v1",
        depth_profile="quick",
        stage_runner=rerun_stage,
    )
    assert rerun.status == "succeeded", rerun.failures
    assert MANDATORY_STAGE_IDS[0] not in rerun_stages
    assert MANDATORY_STAGE_IDS[1] in rerun_stages
    assert service.get_run(queued.run_id).status == "cancelled"


def test_incompatible_mandatory_plan_fails_before_submission(monkeypatch, tmp_path):
    _install_plan_estimate(monkeypatch)
    service = BulkAnalysisService(tmp_path)
    _set_test_hardware(service)
    original_create_plan = bulk_run.create_resource_plan

    def incompatible_plan(*args, **kwargs):
        return replace(
            original_create_plan(*args, **kwargs),
            compatibility_status="blocked",
            reasons=("mandatory stages exceed available capacity",),
        )

    monkeypatch.setattr(bulk_run, "create_resource_plan", incompatible_plan)
    with pytest.raises(AnalysisDepthError, match="mandatory stages exceed available capacity"):
        service.start(
            {"ETF.BLOCKED": {"value": 1}},
            analyzer_id="tests.depth.blocked.v1",
            depth_profile="quick",
            stage_runner=_successful_stage_runner,
        )
    assert service.scheduler.list_jobs() == ()


def test_mandatory_hashes_match_across_worker_and_low_resource_plans(monkeypatch, tmp_path):
    _install_plan_estimate(monkeypatch)
    values = tuple(range(1, 131))
    inputs = {f"ETF.{index}": {"values": values} for index in range(3)}
    observed_plans = {"serial": [], "parallel": [], "low_resource": [], "perturbed": []}

    def numerical_runner_for(plan_observations, *, numerical_adjustment=0):
        def numerical_runner(instrument_id, analysis_input, stage, resource_plan):
            plan_observations.append(resource_plan)
            result = 0
            values_to_process = analysis_input["values"]
            for first in range(0, len(values_to_process), resource_plan.shard_size):
                shard = values_to_process[first:first + resource_plan.shard_size]
                if resource_plan.cpu_fallback:
                    for value in shard:
                        result += value
                else:
                    result += sum(shard)
            return {
                "stage_id": stage.stage_id,
                "instrument_id": instrument_id,
                "value": result + numerical_adjustment,
                "passed": True,
            }

        return numerical_runner

    serial = BulkAnalysisService(tmp_path / "serial")
    _set_test_hardware(serial, max_concurrency=1)
    serial_run = serial.start(
        inputs,
        analyzer_id="tests.depth.parity.v1",
        depth_profile="quick",
        stage_runner=numerical_runner_for(observed_plans["serial"]),
    )

    parallel = BulkAnalysisService(tmp_path / "parallel")
    _set_test_hardware(parallel)
    parallel_run = parallel.start(
        inputs,
        analyzer_id="tests.depth.parity.v1",
        depth_profile="quick",
        stage_runner=numerical_runner_for(observed_plans["parallel"]),
    )

    low_resource = BulkAnalysisService(tmp_path / "low-resource")
    _set_test_hardware(low_resource, max_concurrency=1)
    low_resource_run = low_resource.start(
        inputs,
        analyzer_id="tests.depth.parity.v1",
        depth_profile="quick",
        stage_runner=numerical_runner_for(observed_plans["low_resource"]),
        low_resource=True,
    )

    perturbed = BulkAnalysisService(tmp_path / "perturbed")
    _set_test_hardware(perturbed, max_concurrency=3)
    perturbed_run = perturbed.start(
        inputs,
        analyzer_id="tests.depth.parity.v1",
        depth_profile="quick",
        stage_runner=numerical_runner_for(observed_plans["perturbed"], numerical_adjustment=1),
    )

    assert serial_run.status == "succeeded", serial_run.failures
    assert parallel_run.status == "succeeded", parallel_run.failures
    assert low_resource_run.status == "succeeded", low_resource_run.failures
    assert perturbed_run.status == "succeeded", perturbed_run.failures
    assert all(observed_plans.values())
    low_resource_workflow = low_resource.scheduler.get_workflow(low_resource_run.run_id)
    low_resource_plan = low_resource_workflow.inputs["analysis_depth"]["resource_plan"]
    assert low_resource_plan["shard_size"] == 1
    serial_workflow = serial.scheduler.get_workflow(serial_run.run_id)
    default_shard_size = serial_workflow.inputs["analysis_depth"]["resource_plan"]["shard_size"]
    assert len(values) > default_shard_size
    assert all(plan.shard_size == default_shard_size for plan in observed_plans["serial"])
    assert all(plan.shard_size == default_shard_size for plan in observed_plans["parallel"])
    assert all(plan.shard_size == 1 for plan in observed_plans["low_resource"])
    assert all(plan.cpu_fallback for plans in observed_plans.values() for plan in plans)

    def mandatory_hashes(run, instrument_id):
        stage_hashes = run.results[instrument_id]["stage_hashes"]
        return {stage_id: stage_hashes[stage_id]["content_hash"] for stage_id in MANDATORY_STAGE_IDS}

    for instrument_id in inputs:
        expected = mandatory_hashes(serial_run, instrument_id)
        assert mandatory_hashes(parallel_run, instrument_id) == expected
        assert mandatory_hashes(low_resource_run, instrument_id) == expected
        assert all(
            mandatory_hashes(perturbed_run, instrument_id)[stage_id] != expected[stage_id]
            for stage_id in MANDATORY_STAGE_IDS
        )
