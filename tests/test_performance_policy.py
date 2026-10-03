from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.app.state import AppState
import etf_cockpit.app.state as state_module
from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.core.config import (
    AppConfig,
    CostConfig,
    ETFConfig,
    ModelSettings,
    PortfolioTargets,
    RiskLimits,
    UISettings,
    UniverseConfig,
)
from etf_cockpit.core.timing import read_timing_records, timed_step, timing_summary


HEAVY_MODULES = ("torch", "transformers", "timesfm", "toto2", "accelerate")
STARTUP_MODULES = (
    "etf_cockpit.main",
    "etf_cockpit.app.flet_app",
    "etf_cockpit.app.router",
    "etf_cockpit.services",
    "etf_cockpit.app.state",
)
_STARTUP_IMPORT_ATTEMPTS = 3


def _startup_timing_retry_decision(
    durations_ms: tuple[float, ...], budget_ms: float
) -> tuple[str, str]:
    if any(duration_ms < budget_ms for duration_ms in durations_ms):
        return "pass", ""
    if len(durations_ms) < _STARTUP_IMPORT_ATTEMPTS:
        return "retry", ""
    return (
        "fail",
        f"startup import timing exceeded budget; measured durations_ms={list(durations_ms)!r}; "
        f"budget_ms={budget_ms!r}",
    )


def _run_python(code: str, repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_subprocess_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def _config(*enabled: str) -> AppConfig:
    return AppConfig(
        universe=UniverseConfig(
            etfs=[ETFConfig(id=item, name=item, ticker=item, role="core") for item in enabled]
        ),
        targets=PortfolioTargets(),
        risks=RiskLimits(),
        costs=CostConfig(),
        models=ModelSettings(),
        ui=UISettings(),
        chatgpt_schema={},
    )


def test_optional_model_imports_remain_lazy_in_startup_and_adapters() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    startup = _run_python(
        """
        import sys
        modules = {modules!r}
        for module in modules:
            __import__(module)
        assert not (set({heavy!r}) & set(sys.modules)), sorted(set(sys.modules) & set({heavy!r}))
        """.format(modules=STARTUP_MODULES, heavy=HEAVY_MODULES),
        repo_root,
    )
    _assert_subprocess_ok(startup)

    adapters = _run_python(
        """
        import importlib
        import sys
        for module in ("etf_cockpit.models.timesfm_adapter", "etf_cockpit.models.toto_adapter"):
            importlib.import_module(module)
        assert not (set({heavy!r}) & set(sys.modules)), sorted(set(sys.modules) & set({heavy!r}))
        """.format(heavy=HEAVY_MODULES),
        repo_root,
    )
    _assert_subprocess_ok(adapters)


# Wall-clock budget (startup_cold): CPU contention from parallel workers would distort it.
@pytest.mark.serial
def test_startup_import_timing_stays_within_versioned_budget(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    timing_path = tmp_path / "startup-timings.jsonl"
    durations_ms: list[float] = []
    for _attempt in range(_STARTUP_IMPORT_ATTEMPTS):
        result = _run_python(
            """
        import time
        from pathlib import Path
        from etf_cockpit.core.performance import load_performance_budgets
        from etf_cockpit.core.timing import read_timing_records, timed_step

        budget = next(item for item in load_performance_budgets() if item.metric_id == "startup_cold")
        modules = {modules!r}
        destination = Path({destination!r})
        started = time.perf_counter()
        with timed_step("startup", "cold_import", store_path=destination, slow_ms=budget.threshold):
            for module in modules:
                __import__(module)
        duration_ms = (time.perf_counter() - started) * 1000
        print(f"STARTUP_IMPORT_MEASUREMENT {{duration_ms}} {{budget.threshold}}")
        assert duration_ms < budget.threshold, (duration_ms, budget.threshold)
        records = read_timing_records(destination)
        assert records and "duration_ms" in records[-1] and "slow" in records[-1]
        """.format(modules=STARTUP_MODULES, destination=str(timing_path)),
            repo_root,
        )
        measurement = next(
            (line for line in result.stdout.splitlines() if line.startswith("STARTUP_IMPORT_MEASUREMENT ")),
            None,
        )
        if measurement is None:
            _assert_subprocess_ok(result)
            pytest.fail("startup import subprocess did not report its measured duration")
        _, duration_text, budget_text = measurement.split()
        durations_ms.append(float(duration_text))
        decision, failure_message = _startup_timing_retry_decision(tuple(durations_ms), float(budget_text))
        if decision == "pass":
            _assert_subprocess_ok(result)
            break
        if decision == "fail":
            pytest.fail(failure_message)

    records = read_timing_records(timing_path)
    assert records and isinstance(records[-1]["duration_ms"], (int, float))
    assert isinstance(records[-1]["slow"], bool)


def test_startup_timing_retry_decision_passes_after_an_under_budget_run() -> None:
    decision, message = _startup_timing_retry_decision((1100.0, 1200.0, 999.0), 1000.0)

    assert decision == "pass"
    assert message == ""


def test_startup_timing_retry_decision_lists_all_over_budget_runs() -> None:
    durations_ms = (1100.0, 1200.0, 1300.0)

    decision, message = _startup_timing_retry_decision(durations_ms, 1000.0)

    assert decision == "fail"
    assert all(str(duration_ms) in message for duration_ms in durations_ms)
    assert "budget_ms=1000.0" in message


def test_timing_summary_exposes_slow_and_fast_steps(tmp_path: Path) -> None:
    path = tmp_path / "timings.jsonl"
    with timed_step("action", "slow", store_path=path, slow_ms=0):
        time.sleep(0.005)
    with timed_step("action", "fast", store_path=path, slow_ms=10_000):
        pass

    records = read_timing_records(path)
    assert [record["slow"] for record in records] == [True, False]
    summary = timing_summary(path, limit=10)
    assert len(summary["slow_steps"]) == 1
    assert summary["slow_steps"][0]["step"] == "slow"


def test_apply_universe_config_marks_cached_backtest_stale() -> None:
    report = BacktestReport(
        results=pd.DataFrame({"strategy_name": ["sentinel"]}),
        equity_curves=pd.DataFrame({"signal_strategy": [1.0]}),
        trade_log=pd.DataFrame({"trade": [1]}),
        signal_log=pd.DataFrame({"signal": [1]}),
        ai_added_value=True,
    )
    state = AppState(
        snapshot=SimpleNamespace(
            config=_config("A"),
            prices=pd.DataFrame({"etf_id": ["A", "B"]}),
            holdings=pd.DataFrame({"etf_id": ["A", "B"]}),
            features=pd.DataFrame({"etf_id": ["A", "B"]}),
            latest_features=pd.DataFrame({"etf_id": ["A", "B"]}),
            signals=[],
            forecasts=pd.DataFrame({"etf_id": ["A", "B"]}),
            backtest=report,
            universe_revision="old",
        ),
        selected_etf="A",
    )
    state.apply_universe_config(_config("B"), "new")

    assert state.universe_cache_revision == "new"
    assert state.snapshot.universe_revision == "new"
    assert state.snapshot.prices["etf_id"].tolist() == ["B"]
    assert state.snapshot.backtest.results.empty
    assert state.snapshot.backtest.quality_label == "stale_universe"


def test_classification_invalidation_removes_stale_signals_and_selected_score(monkeypatch, tmp_path: Path) -> None:
    def fake_score_state(root: Path, instrument_id: str) -> dict[str, object]:
        assert root == tmp_path
        if instrument_id == "A":
            return {
                "status": "available",
                "invalidation_token": "new-token",
                "invalidated_score_keys": ("classification:A:*",),
            }
        return {"status": "available", "invalidation_token": "same-token", "invalidated_score_keys": ()}

    monkeypatch.setattr(state_module, "classification_score_state", fake_score_state)
    stale = SimpleNamespace(etf_id="A", supporting_metrics={"classification_invalidation_hash": "old-token"})
    unrelated = SimpleNamespace(etf_id="B", supporting_metrics={"classification_invalidation_hash": "same-token"})
    state = AppState(
        snapshot=SimpleNamespace(config=_config("A", "B"), signals=[stale, unrelated]),
        selected_etf="A",
    )
    state.selected_instrument_score = SimpleNamespace(display_id="A")
    state.invalidate_classification_scores("A", root=tmp_path)

    assert state.snapshot.signals == [unrelated]
    assert state.selected_instrument_score is None
