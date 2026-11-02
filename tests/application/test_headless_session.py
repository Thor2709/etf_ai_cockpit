"""Focused coverage for headless workflows, publication status and writer exclusion."""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import threading
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import headless_session, scoreboard_publication
from etf_cockpit.application.headless_session import (
    HeadlessSession,
    HeadlessWriterBusyError,
    cross_process_writer_guard,
)
from etf_cockpit.application.workflow_handlers import estimate_headless_workflow, headless_workflow_handlers
from etf_cockpit.app import state as app_state_module
from etf_cockpit.app.state import AppState
from etf_cockpit.core import workflow as workflow_module
from etf_cockpit.core.resource_profiles import HardwareSnapshot


@pytest.fixture(autouse=True)
def _disable_timing_log_writes(monkeypatch) -> None:
    monkeypatch.setattr(headless_session, "timed_step", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(app_state_module, "timed_step", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(workflow_module, "log_event", lambda **_kwargs: None)


def _snapshot(*, blocked: bool = False) -> SimpleNamespace:
    report = SimpleNamespace(
        analysis_allowed=not blocked,
        status="Blocked" if blocked else "Clean",
    )
    return SimpleNamespace(
        config=SimpleNamespace(ui=SimpleNamespace(default_etf="ETF1")),
        data_report=report,
        prices=pd.DataFrame({"etf_id": ["ETF1"], "close": [100.0]}),
        signals=[],
        forecasts=pd.DataFrame(),
        universe_revision="fixture-revision",
    )


def _make_app_state(snapshot: object) -> AppState:
    return AppState(snapshot=snapshot, selected_etf="ETF1")


def _fixture_publication(mode: str) -> None:
    """Run offline I/O fixtures with real scoring, serialization and trust writes."""
    from dataclasses import replace
    from datetime import date

    from etf_cockpit.core.config import load_config
    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.core.types import ComponentScores, SignalResult

    config = load_config()
    config.universe.etfs = [etf for etf in config.universe.etfs if etf.id == "VWCE"]
    config.ui.default_etf = "VWCE"
    source = ROOT / "prices.csv"
    stored = ROOT / "data" / "clean" / "fixture_prices.csv"
    stored.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, stored)
    signal = SignalResult(
        run_id="fixture", signal_date=date(2026, 10, 30), etf_id="VWCE",
        action="HOLD", confidence=0.8, total_score=0.3,
        components=ComponentScores(0.2, 0.3, 0.1, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        blocked_by=[], warnings=[], reason_short="fixture", reason_long="fixture",
        horizon_primary="1-3 months", supporting_metrics={},
    )

    def builder(**_kwargs):
        prices = pd.read_csv(stored, parse_dates=["date"])
        current = replace(signal, components=replace(signal.components, momentum=float(prices.iloc[-1]["momentum"])))
        return SimpleNamespace(
            config=config, data_report=SimpleNamespace(analysis_allowed=True, status="Clean"),
            prices=prices, signals=[current], forecasts=pd.DataFrame(), universe_revision="fixture-revision",
        )

    class FixtureDataService:
        def __init__(self, _config):
            self.last_operation_succeeded = True

        def refresh_yfinance_data(self, **_kwargs):
            shutil.copyfile(source, stored)
            return "fixture refresh completed"

        def run_yfinance_candidate_analysis(self, **_kwargs):
            prices = pd.read_csv(stored)
            prices.loc[prices.index[-1], ["close", "adj_close", "momentum"]] = [125.0, 125.0, 0.8]
            prices.to_csv(stored, index=False)
            return "fixture rescore completed. Report: candidates.json"

    if mode == "headless":
        session = HeadlessSession(builder(), root=ROOT, snapshot_builder=builder, data_service_factory=FixtureDataService)
        session.refresh()
        refreshed = pd.read_parquet(ROOT / "data" / "derived" / "scoreboard.parquet")
        session.rescore()
        session.publish()
        assert session.score_history_warning is None, session.score_history_warning
    else:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(app_state_module, "DataService", FixtureDataService)
            patch.setattr(app_state_module, "build_snapshot", builder)
            patch.setattr(AppState, "refresh_runtime_profile", lambda *_args, **_kwargs: "minimum")
            patch.setattr(AppState, "assign_sector_projections", lambda *_args, **_kwargs: None)
            state = AppState(snapshot=builder(), selected_etf="VWCE")
            patch.setattr(state, "_app_activity_publication", lambda *_args: nullcontext())
            AppState.refresh_yfinance_data.__wrapped__(state)
            refreshed = pd.read_parquet(ROOT / "data" / "derived" / "scoreboard.parquet")
            AppState.run_algorithm_scores.__wrapped__(state)
            AppState._write_current_scoreboard.__wrapped__(state)
            assert state.score_history_warning is None, state.score_history_warning
    final = pd.read_parquet(ROOT / "data" / "derived" / "scoreboard.parquet")
    assert not refreshed.equals(final), "Rescoring must affect serialized financial outputs"
    assert final["momentum_score_10"].notna().any()
    assert not final["execution_allowed"].any()
    assert (ROOT / "data" / "derived" / "score_history.parquet").is_file()


def test_headless_refresh_rescore_publish_matches_app_state_path(tmp_path) -> None:
    # Each process selects its root before application imports. The two roots
    # use identical fixtures; each also checks sensitivity to a rescore change.
    roots = {}
    processes = []
    for mode in ("headless", "app"):
        root = tmp_path / mode
        roots[mode] = root
        shutil.copytree(Path(__file__).resolve().parents[2] / "configs", root / "configs")
        pd.DataFrame({
            "date": pd.bdate_range(end="2026-10-30", periods=320), "etf_id": "VWCE",
            "close": [100.0 + n * 0.05 for n in range(320)],
            "adj_close": [100.0 + n * 0.05 for n in range(320)],
            "volume": 100000, "momentum": 0.2,
        }).to_csv(root / "prices.csv", index=False)
        environment = dict(
            os.environ, ETF_COCKPIT_ROOT=str(root), CUDA_VISIBLE_DEVICES="",
            PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
        )
        processes.append(subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), mode], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ))
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=120)
        results.append((process.returncode, stdout, stderr))
    assert all(code == 0 for code, _, _ in results), results
    for suffix in ("parquet", "csv", "json"):
        loader = {"parquet": pd.read_parquet, "csv": pd.read_csv, "json": pd.read_json}[suffix]
        left = loader(roots["headless"] / "data" / "derived" / f"scoreboard.{suffix}")
        right = loader(roots["app"] / "data" / "derived" / f"scoreboard.{suffix}")
        pd.testing.assert_frame_equal(left, right)


def test_app_state_delegates_refresh_rescore_and_publish(monkeypatch, tmp_path) -> None:
    snapshot = _snapshot()
    monkeypatch.setattr(AppState, "refresh_runtime_profile", lambda self, *_args, **_kwargs: "minimum")
    monkeypatch.setattr(AppState, "assign_sector_projections", lambda self, *_args, **_kwargs: None)
    monkeypatch.setattr(app_state_module, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "activity.jsonl")
    state = _make_app_state(snapshot)
    output = tmp_path / "scoreboard.parquet"
    calls: list[str] = []

    class Session:
        def refresh(self, **_kwargs) -> str:
            calls.append("refresh")
            return "refreshed"

        def rescore(self, **_kwargs) -> tuple[str, Path]:
            calls.append("rescore")
            return "rescored", output

        def publish(self) -> Path:
            calls.append("publish")
            return output

    monkeypatch.setattr(state, "_headless_session", lambda: Session())
    monkeypatch.setattr(app_state_module, "DataService", lambda *_args, **_kwargs: pytest.fail("duplicated data orchestration"))
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda *_args, **_kwargs: pytest.fail("duplicated snapshot orchestration"))

    AppState.refresh_yfinance_data.__wrapped__(state)
    AppState.run_algorithm_scores.__wrapped__(state)
    assert AppState._write_current_scoreboard.__wrapped__(state) == output

    assert calls == ["refresh", "rescore", "publish"]

    handlers = headless_workflow_handlers(lambda: Session())
    assert set(handlers) == {"refresh", "rescore", "publish"}
    assert handlers["refresh"](None) == {"message": "refreshed", "execution_allowed": False}
    estimate = estimate_headless_workflow(
        "rescore",
        requested_profile="minimum",
        snapshot=HardwareSnapshot("test", 2, 4096, 2048, 10240, False, "none"),
    )
    assert estimate["status"] == "supported"
    assert estimate["execution_allowed"] is False


def test_publish_status_reports_missing_inputs_as_unavailable_not_zero(tmp_path) -> None:
    status = HeadlessSession(_snapshot(), root=tmp_path).status()

    assert status["status"] == "unavailable"
    assert status["reason_code"] == "scoreboard_missing"
    assert status["row_count"] is None


def test_headless_binding_failure_keeps_persisted_history_explicit() -> None:
    session = HeadlessSession(_snapshot())
    session._record_score_history_failure(
        scoreboard_publication.ScoreboardPublicationBindingError("binding store unavailable"),
        Path("scoreboard.parquet"),
    )

    warning = session.score_history_warning or ""
    assert "score-history publication binding" in warning
    assert "binding store unavailable" in warning
    assert "Paper bot decisions for this publication are unavailable" in warning
    assert "Score history was not persisted" not in warning


def test_headless_history_failure_redacts_details_before_truncating() -> None:
    session = HeadlessSession(_snapshot())
    credential = "fixture-private-token"
    session._record_score_history_failure(
        OSError("disk full " + "x" * 200 + " api_key=" + credential),
        Path("scoreboard.parquet"),
    )

    warning = session.score_history_warning or ""
    assert warning.startswith("Score history was not persisted (OSError: disk full")
    assert "unavailable, not empty" in warning
    assert credential not in warning
    assert credential[:5] not in warning


def test_second_writer_is_refused_while_guard_is_held(tmp_path) -> None:
    result: list[str] = []

    def second_writer() -> None:
        try:
            with cross_process_writer_guard(tmp_path):
                result.append("acquired")
        except HeadlessWriterBusyError:
            result.append("refused")

    with cross_process_writer_guard(tmp_path):
        thread = threading.Thread(target=second_writer)
        thread.start()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert result == ["refused"]

    # A separate interpreter has no shared threading lock or writer context.
    command = """
import sys
from pathlib import Path
from etf_cockpit.application.headless_session import cross_process_writer_guard, HeadlessWriterBusyError
try:
    with cross_process_writer_guard(Path(sys.argv[1])):
        raise AssertionError('second process acquired the writer lock')
except HeadlessWriterBusyError:
    print('refused')
"""
    with cross_process_writer_guard(tmp_path):
        child = subprocess.run(
            [sys.executable, "-c", command, str(tmp_path)], capture_output=True, text=True, timeout=30,
            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src")),
        )
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "refused"


def test_stale_dead_pid_lock_is_recovered_with_audit_note(tmp_path) -> None:
    owner_path = tmp_path / "data" / ".headless-writer.lock.owner.json"
    audit_path = tmp_path / "data" / "operations" / "headless_writer_audit.jsonl"
    dead_pid = os.getpid() + 1_000_000
    owner_path.parent.mkdir(parents=True)
    owner_path.write_text(json.dumps({"active": True, "pid": dead_pid}) + "\n", encoding="utf-8")

    with cross_process_writer_guard(tmp_path):
        assert owner_path.is_file()

    audit = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert audit == [
        {
            "event": "headless_writer_stale_lock_recovered",
            "stale_pid": dead_pid,
            "recovered_by_pid": os.getpid(),
            "root": str(tmp_path.resolve()),
            "recovered_at": audit[0]["recovered_at"],
        }
    ]


def test_blocking_data_quality_gate_prevents_scoreboard_publish(monkeypatch) -> None:
    root = headless_session.ROOT
    session = HeadlessSession(_snapshot(blocked=True), root=root)
    path = root / "data" / "derived" / "scoreboard.parquet"
    previous = path.read_bytes() if path.exists() else None

    def unexpected(*_args, **_kwargs):
        pytest.fail("A blocked snapshot reached publication")

    monkeypatch.setattr(scoreboard_publication, "load_latest_candidate_report", unexpected)

    with pytest.raises(scoreboard_publication.ScoreboardPublicationBlockedError):
        session.publish()

    assert (path.read_bytes() if path.exists() else None) == previous


@pytest.mark.parametrize("report", [None, SimpleNamespace(status="unavailable")])
def test_missing_optional_report_does_not_become_a_passed_gate(report) -> None:
    snapshot = _snapshot()
    snapshot.data_report = report

    scoreboard_publication._require_publishable_snapshot(snapshot)

    assert snapshot.data_report is report
    assert getattr(report, "analysis_allowed", None) is None


def test_empty_first_run_can_publish_unavailable_rows_without_clearing_its_gate() -> None:
    from datetime import date
    from etf_cockpit.core.types import DataQualityIssue, DataQualityReport

    snapshot = _snapshot()
    snapshot.prices = pd.DataFrame()
    snapshot.data_report = DataQualityReport(
        date(2026, 11, 2), [DataQualityIssue("ALL", "block", "empty_prices", "No price rows are available.")],
    )

    scoreboard_publication._require_publishable_snapshot(snapshot)

    assert snapshot.data_report.analysis_allowed is False
    assert snapshot.data_report.status == "Blocked"
    assert snapshot.prices.empty
    assert snapshot.signals == []


@pytest.mark.parametrize("failure", ["invalid_price_values", "missing_adjusted_close", "stale_data", "risk_limit"])
def test_empty_inputs_do_not_hide_another_failed_gate(failure) -> None:
    from datetime import date
    from etf_cockpit.core.types import DataQualityIssue, DataQualityReport

    snapshot = _snapshot()
    snapshot.prices = pd.DataFrame()
    snapshot.data_report = DataQualityReport(date(2026, 11, 2), [
        DataQualityIssue("ALL", "block", "empty_prices", "No price rows are available."),
        DataQualityIssue("ETF1", "block", failure, "A required gate failed."),
    ])

    with pytest.raises(scoreboard_publication.ScoreboardPublicationBlockedError):
        scoreboard_publication._require_publishable_snapshot(snapshot)


def test_empty_price_gate_cannot_publish_signals_as_available() -> None:
    snapshot = _snapshot(blocked=True)
    snapshot.prices = pd.DataFrame()
    snapshot.signals = [SimpleNamespace(etf_id="ETF1")]
    snapshot.data_report.issues = [SimpleNamespace(severity="block", code="empty_prices")]

    with pytest.raises(scoreboard_publication.ScoreboardPublicationBlockedError):
        scoreboard_publication._require_publishable_snapshot(snapshot)


@pytest.mark.parametrize("operation", ["refresh", "rescore", "refresh_snapshot", "publish"])
def test_runtime_root_mismatch_is_refused_before_any_persistence(monkeypatch, tmp_path, operation) -> None:
    def unexpected(*_args, **_kwargs):
        pytest.fail("A mismatched root reached a default-scoped persistence service")

    monkeypatch.setattr(scoreboard_publication, "load_latest_candidate_report", unexpected)
    session = HeadlessSession(_snapshot(), root=tmp_path, snapshot_builder=unexpected, data_service_factory=unexpected)
    with pytest.raises(ValueError, match="ETF_COCKPIT_ROOT before importing"):
        getattr(session, operation)()
    assert not (tmp_path / "data").exists()


def test_live_owner_probe_does_not_terminate_a_process(monkeypatch, tmp_path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        owner = tmp_path / "data" / ".headless-writer.lock.owner.json"
        owner.parent.mkdir(parents=True)
        owner.write_text(json.dumps({"active": True, "pid": child.pid}), encoding="utf-8")
        if os.name == "nt":
            monkeypatch.setattr(os, "kill", lambda *_args: pytest.fail("Windows must never signal the owner"))
        assert headless_session._pid_is_alive(child.pid)
        with pytest.raises(HeadlessWriterBusyError, match="live owner"):
            with cross_process_writer_guard(tmp_path):
                pytest.fail("live metadata owner must be refused")
        assert child.poll() is None
        assert json.loads(owner.read_text(encoding="utf-8"))["active"] is True
    finally:
        child.terminate()
        child.wait(timeout=10)


@pytest.mark.parametrize("error, expected", [(87, False), (5, True), (6, True)])
def test_windows_inconclusive_owner_query_fails_closed(monkeypatch, error, expected) -> None:
    import ctypes

    def open_process(*_args):
        return None

    def exit_code(*_args):
        pytest.fail("No process handle was acquired")

    def close_handle(*_args):
        pytest.fail("No process handle was acquired")

    api = SimpleNamespace(OpenProcess=open_process, GetExitCodeProcess=exit_code, CloseHandle=close_handle)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: api, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    assert headless_session._windows_pid_is_alive(12345) is expected


if __name__ == "__main__":
    _fixture_publication(sys.argv[1])


@pytest.fixture
def monthly_analysis(monkeypatch):
    from etf_cockpit.application import portfolio_sandbox
    candidate = SimpleNamespace(candidate_id="candidate:month", source_revision="revision:month")
    cost = SimpleNamespace(model_id="canonical-cost", estimates=(), total_order_value_eur=1000.0,
                           total_cost_eur=12.0, weighted_cost_bps=120.0)
    benchmark = {"status": "unavailable", "reason": "fixture_reference_unavailable", "execution_allowed": False}
    analysis = SimpleNamespace(
        candidate=candidate, snapshot_binding=SimpleNamespace(source_checksum="a" * 64), source_stale=False,
        service_evidence={"benchmark_reference": benchmark,
                          "optimiser": {"status": "success", "method": "minimum_variance", "feasible": True, "weights": {"VWCE": 1.0}}},
        cost=cost, constraints=(), sector_exposure=(SimpleNamespace(bucket="global", target_weight=1.0),),
    )
    calls = []
    monkeypatch.setattr(portfolio_sandbox, "draft_portfolio_candidate", lambda snapshot: candidate)
    def analyse(snapshot, selected):
        calls.append((snapshot, selected))
        return analysis
    monkeypatch.setattr(portfolio_sandbox, "analyse_portfolio_candidate", analyse)
    return analysis, calls


def test_monthly_pack_consumes_month_bound_application_projections(monthly_analysis):
    analysis, calls = monthly_analysis
    snapshot = SimpleNamespace(data_report=SimpleNamespace(as_of_date="2026-08-21"), facts_known_at="2026-08-21T12:00:00Z")
    result = headless_session.load_monthly_decision_pack(snapshot, "2026-08")
    assert calls == [(snapshot, analysis.candidate)]
    assert result["benchmark_reference"] == analysis.service_evidence["benchmark_reference"]
    assert result["costs"]["status"] == "partial", result
    assert result["costs"]["total"]["cost_eur"] == 12.0
    assert result["optimiser"]["solution"]["weights"] == {"VWCE": 1.0}
    assert result["concentration"]["sector"]["exposures"] == [{"label": "global", "weight": 1.0}]
    assert result["assumptions"]["values"]["candidate_source_revision"] == "revision:month"
    assert result["expected_returns"]["status"] == "unavailable"
    assert result["lines"]
    assert result["execution_allowed"] is False


@pytest.mark.parametrize("as_of,known", [
    ("2026-09-01", "2026-09-01T12:00:00Z"),
    ("2026-07-31", "2026-07-31T12:00:00Z"),
    ("2026-08-21", "2026-09-01T00:00:00Z"),
    ("2026-08-21", None),
])
def test_monthly_pack_refuses_other_month_or_future_known_snapshot(monthly_analysis, as_of, known):
    _, calls = monthly_analysis
    snapshot = SimpleNamespace(data_report=SimpleNamespace(as_of_date=as_of), facts_known_at=known)
    result = headless_session.load_monthly_decision_pack(snapshot, "2026-08")
    assert not calls
    for name in ("costs", "optimiser", "concentration", "assumptions"):
        assert result[name]["status"] == "unavailable"
    assert result["benchmark_reference"]["status"] == "unavailable"
