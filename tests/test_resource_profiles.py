from __future__ import annotations

from pathlib import Path
import os

import pytest

from etf_cockpit.core.resource_profiles import (
    HardwareSnapshot,
    ResourcePolicy,
    detect_hardware,
    estimate_workflow_resources,
    generated_cache_cleanup,
    resource_profile_report,
)
from etf_cockpit.core.resource_profiles import _linux_memory


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
    assert report["calculation_contract"]["profile_does_not_affect"] == [
        "deterministic_formulas",
        "risk_gates",
        "execution_authority",
    ]
    assert report["benchmarks"]["network_calls"] is False


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


def test_profile_quotas_limit_jobs_below_host_capacity() -> None:
    policy = ResourcePolicy(
        requested_profile="minimum",
        snapshot=_snapshot(memory_total=32_768, memory_available=30_000, disk=100_000, cpu=16),
    )

    decision = policy.evaluate({"memory_mb": 769, "disk_mb": 1_537, "cpu": 2})

    assert decision.status == "blocked"
    assert any("memory request 769 MB exceeds safe limit 768 MB" in reason for reason in decision.reasons)
    assert any("disk request 1537 MB exceeds safe limit 1536 MB" in reason for reason in decision.reasons)
    assert any("CPU request 2 exceeds safe limit 1" in reason for reason in decision.reasons)


@pytest.mark.parametrize("value", [0, -1, float("inf"), "unknown", True, None])
def test_malformed_declared_resources_fail_closed(value: object) -> None:
    policy = ResourcePolicy(snapshot=_snapshot())

    decision = policy.evaluate({"memory_mb": value})

    assert decision.status == "blocked"
    assert "memory request must be a finite positive number" in decision.reasons


def test_malformed_profile_and_gpu_declarations_fail_closed() -> None:
    policy = ResourcePolicy(snapshot=_snapshot())

    profile = policy.evaluate({"profile": "unlimited"})
    gpu = policy.evaluate({"gpu": ["cuda:0"]})

    assert profile.status == "blocked"
    assert "resource profile must be" in profile.reasons[0]
    assert gpu.status == "blocked"
    assert "GPU request must be" in gpu.reasons[0]


def test_minimum_profile_supports_reduced_training_estimate() -> None:
    estimate = estimate_workflow_resources(
        "training",
        requested_profile="minimum",
        snapshot=_snapshot(memory_total=2_048, memory_available=1_536, disk=5_000, cpu=1),
    )

    assert estimate["profile"] == "minimum"
    assert estimate["model_size"] == "baseline_or_small"
    assert estimate["memory_mb"] == 512
    assert estimate["disk_mb"] == 512
    assert estimate["status"] == "supported"


def test_generated_cache_cleanup_is_bounded_and_oldest_first(tmp_path: Path) -> None:
    cache = tmp_path / "artifacts" / "resource-cache"
    cache.mkdir(parents=True)
    oldest = cache / "old.cache"
    newest = cache / "new.cache"
    sibling = tmp_path / "artifacts" / "user-export.csv"
    sibling.write_text("preserve", encoding="utf-8")
    oldest.write_bytes(b"old!")
    newest.write_bytes(b"new!")
    os.utime(oldest, (1, 1))
    os.utime(newest, (2, 2))

    planned = generated_cache_cleanup(tmp_path, maximum_bytes=4)
    applied = generated_cache_cleanup(tmp_path, maximum_bytes=4, apply=True)

    assert planned["status"] == "cleanup_required"
    assert planned["planned_removals"] == ["old.cache"]
    assert applied["status"] == "clean"
    assert applied["removed"] == ["old.cache"]
    assert not oldest.exists()
    assert newest.read_bytes() == b"new!"
    assert sibling.read_text(encoding="utf-8") == "preserve"


def test_linux_memory_reader_reports_total_and_available_memory(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       8388608 kB\nMemFree:         100000 kB\nMemAvailable:   4194304 kB\n",
        encoding="utf-8",
    )

    assert _linux_memory(meminfo) == (8_192, 4_096)
