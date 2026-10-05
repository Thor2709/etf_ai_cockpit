from __future__ import annotations

import builtins

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.core.job_scheduler import DurableJobScheduler, JobSpec, JobStatus
from etf_cockpit.core.resource_profiles import (
    HardwareSnapshot,
    ResourcePolicy,
    estimate_workflow_resources,
)


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=14)
    return pd.DataFrame(
        {
            "etf_id": ["AAA"] * len(dates),
            "date": dates,
            "adjusted_close": [100.0 + index for index in range(len(dates))],
        }
    )


def _forecasts() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=6)
    return pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "model_name": "baseline",
                "model_version": "v1",
                "etf_id": "AAA",
                "forecast_date": forecast_date,
                "horizon_days": 1,
                "expected_return": 0.01,
                "q10_return": -0.01,
                "q90_return": 0.03,
                "status": "ok",
            }
            for forecast_date in dates
        ]
        + [
            {
                "run_id": "run-1",
                "model_name": "timesfm",
                "model_version": "unavailable",
                "etf_id": "AAA",
                "forecast_date": dates[-1],
                "horizon_days": 1,
                "expected_return": None,
                "status": "unavailable",
            }
        ]
    )


def _snapshot() -> HardwareSnapshot:
    return HardwareSnapshot("test", 8, 16_384, 8_192, 100_000, False, "cpu-only")


def test_minimum_profile_runs_without_foundation_models(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config()
    original_import = builtins.__import__

    def import_without_foundation_models(name, *args, **kwargs):
        if name.split(".", maxsplit=1)[0] in {"torch", "transformers"}:
            raise AssertionError(f"foundation model package imported: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_foundation_models)
    from etf_cockpit.features import forecast_lab

    original_policy = forecast_lab.ResourcePolicy

    def policy_for_minimum_snapshot(*, requested_profile: str, snapshot=None):
        return original_policy(
            requested_profile=requested_profile,
            snapshot=HardwareSnapshot("test", 1, 2_048, 1_536, 5_000, False, "cpu-only"),
        )

    monkeypatch.setattr(forecast_lab, "ResourcePolicy", policy_for_minimum_snapshot)
    estimate = estimate_workflow_resources(
        "training",
        requested_profile="minimum",
        snapshot=HardwareSnapshot("test", 1, 2_048, 1_536, 5_000, False, "cpu-only"),
    )
    report = forecast_lab.build_forecast_lab_workspace(
        config, _forecasts(), _prices(), timing_records=[], profile_id="minimum"
    )

    assert estimate["profile"] == "minimum"
    assert estimate["model_size"] == "baseline_or_small"
    assert estimate["status"] == "supported"
    assert report["resource_profile"]["profile"] == "minimum"
    assert report["status"] == "ok"
    models = report["models"].set_index("model_name")
    assert models.loc["baseline", "matured_rows"] == 6
    assert models.loc["timesfm", "status_summary"] == "unavailable=1"


def test_disk_quota_warning() -> None:
    policy = ResourcePolicy(
        requested_profile="minimum",
        snapshot=HardwareSnapshot("test", 8, 16_384, 8_192, 100_000, False, "cpu-only"),
    )

    decision = policy.evaluate({"disk_mb": 1_300})

    assert decision.status == "warning"
    assert not decision.reasons
    assert any("disk request uses at least 80%" in warning for warning in decision.warnings)


def test_resource_budgets_block_over_limit_and_warn_at_threshold() -> None:
    snapshot = _snapshot()
    policy = ResourcePolicy(requested_profile="minimum", snapshot=snapshot)
    thresholds = {
        "memory_mb": 615,
        "disk_mb": 1_229,
        "time_seconds": 2_880,
    }
    over_limits = {
        "memory_mb": 769,
        "disk_mb": 1_537,
        "time_seconds": 3_601,
    }

    for key, amount in thresholds.items():
        decision = policy.evaluate({key: amount})
        assert decision.status == "warning"
        assert any(key.removesuffix("_mb").removesuffix("_seconds") in warning for warning in decision.warnings)

    for key, amount in over_limits.items():
        decision = policy.evaluate({key: amount})
        assert decision.status == "blocked"
        with pytest.raises(ValueError, match="job blocked by resource policy"):
            policy.require_allowed({key: amount})


def test_scheduler_runner_rechecks_resources_before_handler(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = ResourcePolicy(requested_profile="minimum", snapshot=_snapshot())
    scheduler = DurableJobScheduler(tmp_path, resource_policy=policy)
    scheduler.submit(
        "analysis",
        "resource guard test",
        [JobSpec("analysis", "analysis", resources={"profile": "minimum"})],
    )
    original_claim_next = scheduler.claim_next

    def claim_then_block_resources():
        job = original_claim_next()
        if job is not None:
            monkeypatch.setattr(
                policy,
                "snapshot",
                HardwareSnapshot("test", 8, 16_384, 8_192, 0, False, "cpu-only"),
            )
        return job

    monkeypatch.setattr(scheduler, "claim_next", claim_then_block_resources)
    handler_calls: list[bool] = []
    result = scheduler.run_once(lambda _context: handler_calls.append(True))

    assert result is not None
    assert result.status == JobStatus.FAILED
    assert not handler_calls


def test_cross_profile_numerical_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.features import forecast_lab

    original_policy = forecast_lab.ResourcePolicy

    def policy_for_test_snapshot(*, requested_profile: str, snapshot=None):
        return original_policy(
            requested_profile=requested_profile,
            snapshot=snapshot or _snapshot(),
        )

    monkeypatch.setattr(forecast_lab, "ResourcePolicy", policy_for_test_snapshot)
    config = load_config()
    forecasts = _forecasts()
    prices = _prices()
    metrics: dict[str, tuple[float, float, float]] = {}

    for profile_id in ("minimum", "recommended", "high"):
        report = forecast_lab.build_forecast_lab_workspace(
            config, forecasts, prices, timing_records=[], profile_id=profile_id
        )
        estimate = report["resource_profile"]
        baseline = report["models"].set_index("model_name").loc["baseline"]

        assert estimate["profile"] == profile_id
        assert estimate["status"] == "supported"
        metrics[profile_id] = (
            float(baseline["mae"]),
            float(baseline["mase"]),
            float(baseline["directional_accuracy"]),
        )

    reference = metrics["minimum"]
    for profile_metrics in metrics.values():
        assert profile_metrics == pytest.approx(reference, rel=0, abs=1e-9)


def test_hardware_specific_limitations_are_visible_through_facade_diagnostics() -> None:
    from etf_cockpit.application.diagnostics_views import build_resource_profile_diagnostics

    diagnostics = build_resource_profile_diagnostics(
        snapshot=HardwareSnapshot("test", 1, 512, None, 1_024, False, "cpu-only")
    )
    report = diagnostics["resource_profile"]
    minimum = next(row for row in report["profiles"] if row["profile_id"] == "minimum")

    assert any("GPU acceleration is unavailable" in item for item in diagnostics["limitations"])
    assert any("memory 512 MB" in reason for reason in minimum["reasons"])
    assert any("free disk 1024 MB" in reason for reason in minimum["reasons"])
    assert minimum["job_memory_limit_mb"] == 768
    assert minimum["job_disk_limit_mb"] == 1_536
