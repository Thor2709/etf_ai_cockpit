from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import backtest_service, forecast_lab_inputs, forecast_run
from etf_cockpit.core.config import load_config
from etf_cockpit.mcp import tools_forecast
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.registry import CallContext, find_tool, invoke_tool


def test_forecast_get_paginates_simple_returns_and_keeps_unavailable_values_null(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_forecast_lab import _forecasts

    snapshot = SimpleNamespace(forecasts=_forecasts())
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (None, snapshot))

    first = tools_forecast.forecast_get(["AAA"], [1], limit=1)
    assert len(first["forecasts"]) == 1
    assert first["forecasts"][0]["model"] == "baseline"
    assert first["forecasts"][0]["expected_simple_return"] == pytest.approx(math.expm1(0.01))
    assert first["next_cursor"]

    second = tools_forecast.forecast_get(["AAA"], [1], cursor=first["next_cursor"], limit=1)
    assert second["forecasts"][0]["status"] == "unavailable"
    assert second["forecasts"][0]["expected_simple_return"] is None
    assert second["forecasts"][0]["q10_simple_return"] is None
    missing = tools_forecast.forecast_get(["not-stored"], [1])
    assert missing["status"] == "unavailable"
    assert missing["forecasts"][0]["expected_simple_return"] is None


def test_forecast_models_status_uses_model_registry_and_forecast_lab_services(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = SimpleNamespace(config=load_config())
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (None, snapshot))
    diagnostic = SimpleNamespace(
        model_name="timesfm", model_id="TimesFM", status="missing_weights", live_ready=False,
        present=False, weight_files=(), total_bytes=0, runtime_packages={"torch": False}, message="weights unavailable",
    )
    monkeypatch.setattr(forecast_lab_inputs, "load_forecast_model_diagnostics", lambda _config: [diagnostic])
    monkeypatch.setattr(
        forecast_lab_inputs,
        "assemble_forecast_lab_inputs",
        lambda _snapshot: (pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
    )
    calls: list[str] = []

    def report(*_args, **_kwargs):
        calls.append("forecast_lab_workspace")
        return {"status": "unavailable", "promotion": pd.DataFrame([{"model_name": "timesfm", "state": "not_proven", "reason": "no evidence"}])}

    from etf_cockpit.application import forecast_service

    monkeypatch.setattr(forecast_service, "build_forecast_lab_workspace", report)
    result = tools_forecast.forecast_models_status()

    assert calls == ["forecast_lab_workspace"]
    assert result["models"][0]["promotion_status"] == "not_proven"
    assert result["models"][0]["weights_present"] is False


def test_forecast_lab_compare_filters_inputs_and_returns_canonical_metrics_and_exclusions(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_forecast_lab import _forecasts, _prices

    snapshot = SimpleNamespace(config=load_config())
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (None, snapshot))
    monkeypatch.setattr(
        forecast_lab_inputs,
        "assemble_forecast_lab_inputs",
        lambda _snapshot: (_forecasts(), _forecasts(), _prices()),
    )
    seen: dict[str, object] = {}

    def report(_config, forecasts, prices, *, forecast_history):
        seen["forecast_ids"] = set(forecasts["etf_id"].astype(str))
        seen["horizons"] = set(forecasts["horizon_days"].astype(int))
        seen["price_ids"] = set(prices["etf_id"].astype(str))
        seen["history_rows"] = len(forecast_history)
        return {
            "status": "ok",
            "as_of_date": "2026-01-06",
            "models": pd.DataFrame([{"model_name": "baseline", "mase": None, "directional_accuracy": None, "calibration_status": "conformal_pending"}]),
            "walk_forward_evaluation": pd.DataFrame([{"model_name": "baseline", "fold_count": 0}]),
            "promotion": pd.DataFrame([{"model_name": "baseline", "state": "shadow_only"}]),
            "excluded": pd.DataFrame([{"model_name": "baseline", "etf_id": "AAA", "reason": "missing_price_series"}]),
            "notes": (),
        }

    from etf_cockpit.application import forecast_service

    monkeypatch.setattr(forecast_service, "build_forecast_lab_workspace", report)
    result = tools_forecast.forecast_lab_compare(1, models=["baseline"], instrument_ids=["AAA"], limit=1)

    assert seen == {"forecast_ids": {"AAA"}, "horizons": {1}, "price_ids": {"AAA"}, "history_rows": len(_forecasts())}
    assert result["models"][0]["mase"] is None
    assert result["exclusions"][0]["reason"] == "missing_price_series"
    assert result["status"] == "ok"


def test_backtest_get_reads_only_cached_report_and_preserves_unavailable_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    report = SimpleNamespace(
        metadata={"cost_regime": "modelled_default"},
        results=pd.DataFrame([{
            "strategy_name": "signal_strategy", "start_date": None, "end_date": None,
            "final_value_eur": None, "max_drawdown": None, "backtest_quality": "unavailable",
        }]),
        quality_label="unavailable",
        quality_notes=["cached evidence unavailable"],
    )
    calls: list[str] = []

    class CachedService:
        def __init__(self, _config):
            pass

        def load_cached_backtest(self):
            calls.append("cache")
            return report

        def run_backtest(self, *_args, **_kwargs):
            calls.append("run")
            raise AssertionError("a read tool must not run a backtest")

    snapshot = SimpleNamespace(config=load_config())
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (None, snapshot))
    monkeypatch.setattr(backtest_service, "BacktestService", CachedService)

    result = tools_forecast.backtest_get("modelled_default", strategy="signal_strategy")
    assert calls == ["cache"]
    assert result["status"] == "available"
    assert result["equity_summary"][0]["final_value_eur"] is None

    class MissingService(CachedService):
        def load_cached_backtest(self):
            return None

    monkeypatch.setattr(backtest_service, "BacktestService", MissingService)
    unavailable = tools_forecast.backtest_get("modelled_default")
    assert unavailable["status"] == "unavailable"
    assert unavailable["unavailable_reason"] == "cached_backtest_unavailable"
    assert unavailable["results"] == []


def test_pipeline_run_uses_job_api_and_canonical_services_without_confirmation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from etf_cockpit.application import api as api_module
    from etf_cockpit.application.contracts import ApiStatus

    calls: list[str] = []
    snapshot = SimpleNamespace(config=load_config())
    canonical_forecast_recipe = forecast_run.run_forecast_recipe

    class Session:
        def __init__(self):
            self.root = tmp_path
            self.snapshot = snapshot

        @contextmanager
        def activity_publication(self, *_args, **_kwargs):
            yield

        def refresh_snapshot(self):
            calls.append("snapshot")

        def publish(self):
            calls.append("publish")
            return tmp_path / "scoreboard.csv"

    class Features:
        def __init__(self, _config):
            pass

        def compute_features(self, **_kwargs):
            calls.append("features")
            return pd.DataFrame([{"etf_id": "AAA"}])

    class Signals:
        last_unavailable_reason = None

        def __init__(self, _config):
            pass

        def generate_signals(self):
            calls.append("signals")
            return [object()]

    class Backtests:
        def __init__(self, _config):
            pass

        def run_backtest(self, **_kwargs):
            calls.append("backtest")
            return SimpleNamespace(results=pd.DataFrame(), quality_label="unavailable", quality_notes=[])

    monkeypatch.setattr(forecast_run, "FeatureService", Features)
    monkeypatch.setattr(forecast_run, "SignalService", Signals)
    monkeypatch.setattr(forecast_run, "BacktestService", Backtests)
    monkeypatch.setattr(forecast_run, "run_forecast_recipe", lambda *_args, **_kwargs: calls.append("forecasts") or {"status": "available"})
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (Session(), snapshot))

    class FakeApi:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _command):
            return SimpleNamespace(status=ApiStatus.ACCEPTED, resource_id="workflow-1")

        def run_next_job(self, runner, *, workflow_id):
            assert workflow_id == "workflow-1"
            outputs = runner(SimpleNamespace(workflow_id=workflow_id))
            return SimpleNamespace(status="completed", outputs=outputs)

    monkeypatch.setattr(api_module, "LocalApplicationApi", FakeApi)
    spec = find_tool("pipeline_run")
    assert spec.tier == "read_job"
    assert spec.requires_confirmation is False
    context = CallContext(
        enabled_tiers=frozenset({"read_job"}),
        profile="full",
        audit=AuditRecorder(sink=lambda _record: None),
    )

    result = invoke_tool(
        "pipeline_run",
        {"steps": ["features", "signals", "forecasts", "scores", "backtest"]},
        context=context,
    )

    assert result["job_id"] == "workflow-1"
    assert result["status"] == "completed"
    assert calls == ["features", "signals", "forecasts", "snapshot", "publish", "backtest"]
    assert result["result"]["execution_allowed"] is False

    config = load_config()
    first_enabled_id = config.universe.enabled_ids[0]
    with monkeypatch.context() as patch:
        patch.setattr(forecast_run, "ForecastService", lambda *_args, **_kwargs: pytest.fail("partial forecasts must stop before model execution"))
        with pytest.raises(ValueError, match="Per-instrument forecast runs are unavailable"):
            canonical_forecast_recipe(
                config,
                instrument_ids=list(config.universe.enabled_ids[:-1]),
                prices=pd.DataFrame([{"etf_id": first_enabled_id, "date": None}]),
            )
