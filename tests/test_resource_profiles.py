from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.core.resource_profiles import (
    HardwareSnapshot,
    ResourcePolicy,
    detect_hardware,
    estimate_workflow_resources,
    resource_profile_report,
)


def _snapshot(*, memory_total: float = 8_192, memory_available: float = 6_144, disk: float = 60_000, cpu: int = 8) -> HardwareSnapshot:
    return HardwareSnapshot("test", cpu, memory_total, memory_available, disk, False, "not_checked")


def test_profiles_are_deterministic_and_cpu_only_baseline_is_supported() -> None:
    snapshot = _snapshot(memory_total=4_096, memory_available=2_048, disk=12_000, cpu=2)
    report = resource_profile_report(Path("."), snapshot=snapshot)

    assert report["selected_profile"]["profile_id"] == "recommended"
    assert report["selected_status"] == "supported"
    assert [row["profile_id"] for row in report["profiles"]] == ["minimum", "recommended", "high"]
    assert report["profiles"][0]["status"] == "supported"
    assert report["profiles"][2]["status"] == "blocked"
    assert report["execution_allowed"] is False
    assert report["network_calls"] is False


def test_requested_profile_degrades_and_job_limits_fail_closed() -> None:
    policy = ResourcePolicy(requested_profile="high", snapshot=_snapshot(memory_total=2_048, memory_available=1_024, disk=4_000, cpu=1))

    assert policy.profile_id == "minimum"
    assert policy.profile_status == "degraded"
    decision = policy.evaluate({"profile": "high", "memory_mb": 8_192, "disk_mb": 50_000, "cpu": 4, "gpu": True})
    assert decision.status == "blocked"
    assert len(decision.reasons) >= 3


def test_detection_and_estimates_use_injected_local_measurements() -> None:
    snapshot = detect_hardware(
        Path("."),
        cpu_counter=lambda: 4,
        memory_reader=lambda: (8_192, 4_096),
        disk_reader=lambda _root: 20_000,
        gpu_reader=lambda: (False, "cpu-only"),
    )
    estimate = estimate_workflow_resources("training", snapshot=snapshot)

    assert snapshot.cpu_cores == 4
    assert snapshot.memory_available_mb == 4_096
    assert estimate["model_size"] == "baseline_or_small"
    assert estimate["batch_size"] > 0
    assert estimate["status"] == "supported"
    assert estimate["execution_allowed"] is False


def test_declared_resources_block_when_capacity_is_unavailable() -> None:
    policy = ResourcePolicy(snapshot=HardwareSnapshot("test", 2, None, None, None, False, "cpu-only"))

    decision = policy.evaluate({"memory_mb": 512, "disk_mb": 512, "cpu": 1})

    assert decision.status == "blocked"
    assert any("memory request cannot be checked" in reason for reason in decision.reasons)
    assert any("disk request cannot be checked" in reason for reason in decision.reasons)

    exhausted = ResourcePolicy(snapshot=HardwareSnapshot("test", 2, 8_192, 0, 10_000, False, "cpu-only"))
    assert exhausted.evaluate({"memory_mb": 1}).status == "blocked"


def test_invalid_requested_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown resource profile"):
        ResourcePolicy(requested_profile="unlimited", snapshot=_snapshot())
