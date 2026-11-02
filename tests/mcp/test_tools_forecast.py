from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import backtest_service, forecast_lab_inputs, forecast_run, stress_lab
from etf_cockpit.core.config import load_config
from etf_cockpit.data.local_storage import TransactionalStore, storage_layout
from etf_cockpit.mcp import tools_forecast
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.errors import MCPToolError
from etf_cockpit.mcp.registry import CallContext, find_tool, invoke_tool
from etf_cockpit.portfolio.stress_testing import StressResult


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


def test_backtest_get_equity_summary_matches_each_page(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{
        "strategy_name": f"strategy-{index}",
        "final_value_eur": None if index == 0 else 100.0 + index,
        "max_drawdown": None,
        "extra_metric": index,
    } for index in range(101)]
    report = SimpleNamespace(
        metadata={"cost_regime": "modelled_default"},
        results=pd.DataFrame(rows),
        quality_label="unavailable",
        quality_notes=[],
    )
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (None, SimpleNamespace(config=load_config())))
    monkeypatch.setattr(
        backtest_service, "BacktestService",
        lambda _config: SimpleNamespace(load_cached_backtest=lambda: report),
    )

    cursor = None
    for index in range(2):
        result = tools_forecast.backtest_get("modelled_default", cursor=cursor, limit=1)
        assert result["result_count"] == 101
        assert len(result["results"]) == 1
        assert result["results"][0]["strategy_name"] == f"strategy-{index}"
        assert len(result["equity_summary"]) == 1
        assert result["equity_summary"][0] == {
            field: result["results"][0][field]
            for field in ("strategy_name", "final_value_eur", "max_drawdown")
        }
        cursor = result["next_cursor"]
        assert cursor is not None


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


@pytest.mark.parametrize("portfolio", ["current", "paper:acct-7", "candidate"])
def test_stress_test_resolves_portfolio_calls_canonical_service_and_paginates(
    portfolio: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from etf_cockpit.application import portfolio_sandbox
    from etf_cockpit.portfolio import paper_trading

    snapshot = SimpleNamespace(
        holdings=pd.DataFrame([{"instrument_id": "AAA", "current_weight": 0.6, "asset_class": "equity", "currency": "EUR"}]),
        latest_features=pd.DataFrame(),
        prices=None,
    )

    class Session:
        def __init__(self) -> None:
            self.root = tmp_path
            self.snapshot = snapshot

    session = Session()
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (session, snapshot))
    monkeypatch.setattr(stress_lab, "_factor_exposures", lambda *_args: pd.DataFrame())

    if portfolio.startswith("paper:"):
        class Ledger:
            def __init__(self, _root: Path, *, account_id: str) -> None:
                assert account_id == "acct-7"
                self.path = SimpleNamespace(is_file=lambda: True)

            def snapshot(self):
                return SimpleNamespace(
                    status="ready",
                    event_count=2,
                    equity=100.0,
                    positions=(SimpleNamespace(
                        instrument_id="AAA", quantity=5.0, mark_price=10.0,
                        mark_fx_rate=1.0, currency="EUR",
                    ),),
                )

        monkeypatch.setattr(paper_trading, "PaperLedger", Ledger)
    elif portfolio == "candidate":
        with TransactionalStore(tmp_path) as store:
            store.put(portfolio_sandbox.PORTFOLIO_SANDBOX_ENTITY, "candidate-1", {"name": "latest"})
            store.put(portfolio_sandbox.PORTFOLIO_SANDBOX_RESULT_ENTITY, "candidate-1", {"status": "available"})
        monkeypatch.setattr(
            portfolio_sandbox,
            "load_portfolio_candidate",
            lambda *_args, **_kwargs: SimpleNamespace(
                candidate=SimpleNamespace(target_weights=(("AAA", 0.6),)),
                result_payload={"status": "available"},
            ),
        )

    canonical_calls: list[tuple[object, pd.DataFrame]] = []

    def canonical_run(scenario, allocation, **_kwargs):
        canonical_calls.append((scenario, allocation.copy()))
        return StressResult(
            scenario,
            "available",
            -250.0,
            (
                {"instrument_id": "AAA", "weight": 0.6, "pnl": -150.0, "shock": -0.1, "source": "hypothetical_explicit_shock"},
                {"instrument_id": "BBB", "weight": 0.4, "pnl": -100.0, "shock": -0.1, "source": "hypothetical_explicit_shock"},
            ),
            (),
            {"instrument_count": 2},
            (),
        )

    monkeypatch.setattr(stress_lab, "run_stress_scenario", canonical_run)
    context = CallContext(
        enabled_tiers=frozenset({"read"}),
        profile="full",
        session=session,
        audit=AuditRecorder(sink=lambda _record: None),
    )
    result = invoke_tool(
        "stress_test",
        {"portfolio": portfolio, "shocks": {"equity": -0.1}, "limit": 1},
        context=context,
    )

    assert len(canonical_calls) == 1
    assert canonical_calls[0][1].iloc[0]["instrument_id"] == "AAA"
    assert canonical_calls[0][1].iloc[0]["current_weight"] == pytest.approx(0.6 if portfolio != "paper:acct-7" else 0.5)
    assert result["status"] == "available"
    assert result["loss"] == pytest.approx(250.0)
    assert len(result["contributors"]) == 1
    assert result["next_cursor"] is not None
    assert result["execution_allowed"] is False


def test_stress_candidate_uses_latest_publication_instead_of_candidate_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from etf_cockpit.application import portfolio_sandbox
    from etf_cockpit.data import local_storage

    timestamps = iter(f"2026-01-0{day}T00:00:00+00:00" for day in range(1, 5))
    with TransactionalStore(tmp_path) as store:
        monkeypatch.setattr(local_storage, "_utc_now", lambda: next(timestamps))
        candidate_a = store.put(portfolio_sandbox.PORTFOLIO_SANDBOX_ENTITY, "candidate-a", {"name": "A"})
        candidate_b = store.put(portfolio_sandbox.PORTFOLIO_SANDBOX_ENTITY, "candidate-b", {"name": "B"})
        publication_b = store.put(portfolio_sandbox.PORTFOLIO_SANDBOX_RESULT_ENTITY, "candidate-b", {"status": "available"})
        publication_a = store.put(portfolio_sandbox.PORTFOLIO_SANDBOX_RESULT_ENTITY, "candidate-a", {"status": "available"})
    assert candidate_a.updated_at < candidate_b.updated_at
    assert publication_a.updated_at > publication_b.updated_at

    snapshot = SimpleNamespace(holdings=pd.DataFrame())
    loaded_names: list[str] = []

    def load_candidate(actual_snapshot, name, *, root):
        assert actual_snapshot is snapshot
        assert root == tmp_path
        loaded_names.append(name)
        return SimpleNamespace(
            candidate=SimpleNamespace(target_weights=((name, 0.6),)),
            result_payload={"status": "available"},
        )

    monkeypatch.setattr(portfolio_sandbox, "load_portfolio_candidate", load_candidate)

    allocation, reason = stress_lab.resolve_stress_portfolio(snapshot, "candidate", root=tmp_path)

    assert loaded_names == ["A"]
    assert reason is None
    assert allocation["instrument_id"].tolist() == ["A"]
    assert allocation["current_weight"].tolist() == [0.6]


def test_stress_test_unknown_paper_is_not_found_and_missing_candidate_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot = SimpleNamespace(holdings=pd.DataFrame(), latest_features=pd.DataFrame(), prices=None)

    class Session:
        def __init__(self) -> None:
            self.root = tmp_path
            self.snapshot = snapshot

    session = Session()
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (session, snapshot))
    context = CallContext(
        enabled_tiers=frozenset({"read"}),
        profile="full",
        session=session,
        audit=AuditRecorder(sink=lambda _record: None),
    )

    with pytest.raises(MCPToolError) as missing_paper:
        invoke_tool(
            "stress_test",
            {"portfolio": "paper:unknown", "shocks": {"equity": -0.1}},
            context=context,
        )
    assert missing_paper.value.reason_code == "NOT_FOUND"

    missing_candidate = invoke_tool(
        "stress_test",
        {"portfolio": "candidate", "shocks": {"equity": -0.1}},
        context=context,
    )
    assert missing_candidate["status"] == "unavailable"
    assert missing_candidate["loss"] is None
    assert missing_candidate["unavailable_reason"] == "published_candidate_unavailable"
    assert not storage_layout(tmp_path).transactional_path.exists()


def test_reverse_stress_returns_threshold_from_canonical_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot = SimpleNamespace(
        holdings=pd.DataFrame([{"instrument_id": "AAA", "current_weight": 1.0, "asset_class": "equity"}]),
        latest_features=pd.DataFrame(),
        prices=None,
    )

    class Session:
        def __init__(self) -> None:
            self.root = tmp_path
            self.snapshot = snapshot

    session = Session()
    monkeypatch.setattr(tools_forecast, "_snapshot", lambda: (session, snapshot))
    monkeypatch.setattr(stress_lab, "_factor_exposures", lambda *_args: pd.DataFrame())
    canonical_calls: list[tuple[pd.DataFrame, str, float]] = []

    def canonical_reverse(allocation, *, shock_name, loss_limit, **_kwargs):
        canonical_calls.append((allocation.copy(), shock_name, loss_limit))
        return {
            "status": "available",
            "threshold": 0.2,
            "loss_limit": loss_limit,
            "binding_exposure": {"instrument_id": "AAA", "exposure": 1.0, "instrument_count": 1},
            "execution_allowed": False,
        }

    monkeypatch.setattr(stress_lab, "reverse_stress", canonical_reverse)
    context = CallContext(
        enabled_tiers=frozenset({"read"}),
        profile="full",
        session=session,
        audit=AuditRecorder(sink=lambda _record: None),
    )
    result = invoke_tool(
        "stress_test",
        {"portfolio": "current", "reverse_shock_name": "equity", "loss_limit": 1_000.0},
        context=context,
    )

    assert len(canonical_calls) == 1
    assert canonical_calls[0][1:] == ("equity", 1_000.0)
    assert result["threshold"] == pytest.approx(0.2)
    assert result["loss"] is None
    assert result["loss_limit"] == pytest.approx(1_000.0)
    assert result["contributors"][0]["instrument_id"] == "AAA"
    assert result["execution_allowed"] is False
