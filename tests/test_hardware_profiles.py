from __future__ import annotations

import builtins

import pandas as pd
import pytest

from etf_cockpit.core.resource_profiles import (
    HardwareSnapshot,
    ResourcePolicy,
    estimate_workflow_resources,
)
from etf_cockpit.features.forecast_lab import build_forecast_lab_report


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
    original_import = builtins.__import__

    def import_without_foundation_models(name, *args, **kwargs):
        if name.split(".", maxsplit=1)[0] in {"torch", "transformers"}:
            raise AssertionError(f"foundation model package imported: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_foundation_models)
    snapshot = HardwareSnapshot("test", 1, 2_048, 1_536, 5_000, False, "cpu-only")
    estimate = estimate_workflow_resources(
        "training", requested_profile="minimum", snapshot=snapshot
    )
    report = build_forecast_lab_report(_forecasts(), _prices())

    assert estimate["profile"] == "minimum"
    assert estimate["model_size"] == "baseline_or_small"
    assert estimate["status"] == "supported"
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


def test_cross_profile_numerical_parity() -> None:
    snapshot = _snapshot()
    forecasts = _forecasts()
    prices = _prices()
    metrics: dict[str, tuple[float, float, float]] = {}

    for profile_id in ("minimum", "recommended", "high"):
        policy = ResourcePolicy(requested_profile=profile_id, snapshot=snapshot)
        calculation_contract = policy.report()["calculation_contract"]
        estimate = estimate_workflow_resources(
            "analysis", requested_profile=profile_id, snapshot=snapshot
        )
        report = build_forecast_lab_report(forecasts, prices)
        baseline = report["models"].set_index("model_name").loc["baseline"]

        assert policy.profile_status == "supported"
        assert "deterministic_formulas" in calculation_contract["profile_does_not_affect"]
        assert estimate["status"] == "supported"
        metrics[profile_id] = (
            float(baseline["mae"]),
            float(baseline["mase"]),
            float(baseline["directional_accuracy"]),
        )

    reference = metrics["minimum"]
    for profile_metrics in metrics.values():
        assert profile_metrics == pytest.approx(reference, rel=0, abs=1e-9)


def test_hardware_specific_limitations_are_visible() -> None:
    policy = ResourcePolicy(
        snapshot=HardwareSnapshot("test", 1, 512, None, 1_024, False, "cpu-only")
    )

    report = policy.report()
    minimum = next(row for row in report["profiles"] if row["profile_id"] == "minimum")

    assert any("GPU acceleration is unavailable" in item for item in report["limitations"])
    assert any("memory 512 MB" in reason for reason in minimum["reasons"])
    assert any("free disk 1024 MB" in reason for reason in minimum["reasons"])
    assert minimum["job_memory_limit_mb"] == 768
    assert minimum["job_disk_limit_mb"] == 1_536
