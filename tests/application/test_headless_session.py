"""Focused coverage for headless workflows, publication status and writer exclusion."""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
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


def _install_scoreboard_fakes(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.application import score_views

    monkeypatch.setattr(scoreboard_publication, "load_latest_candidate_report", lambda: (None, None))
    monkeypatch.setattr(
        scoreboard_publication,
        "context_from_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(
            benchmark_data_id=None,
            projection=None,
            registry=None,
        ),
    )
    monkeypatch.setattr(scoreboard_publication, "build_market_regime", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(scoreboard_publication, "write_market_regime", lambda _value: None)
    monkeypatch.setattr(scoreboard_publication, "load_forecast_history", lambda: None)
    monkeypatch.setattr(scoreboard_publication, "evaluate_forecast_calibration", lambda *_args: object())
    monkeypatch.setattr(scoreboard_publication, "write_forecast_calibration", lambda _value: None)
    monkeypatch.setattr(score_views, "published_scores", lambda _snapshot: [{"instrument_id": "ETF1", "score": 7.0}])
    monkeypatch.setattr(
        scoreboard_publication,
        "simple_scoreboard_frame",
        lambda _scores: pd.DataFrame({"instrument_id": ["ETF1"], "score": [7.0]}),
    )

    def write_board(_scores, path: Path | None = None) -> Path:
        destination = path or tmp_path / "default-scoreboard.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"instrument_id": ["ETF1"], "score": [7.0]}).to_parquet(destination, index=False)
        return destination

    history_path = tmp_path / "score-history.parquet"
    history_path.write_bytes(b"fixture")
    monkeypatch.setattr(scoreboard_publication, "write_simple_scoreboard", write_board)
    monkeypatch.setattr(
        scoreboard_publication,
        "write_trust_artifacts_for_scores",
        lambda *_args, **_kwargs: {"score_history": history_path},
    )
    monkeypatch.setattr(scoreboard_publication, "_record_scoreboard_publication_binding", lambda *_args, **_kwargs: {})


class _FakeDataService:
    def __init__(self, _config) -> None:
        self.last_operation_succeeded = True

    def refresh_yfinance_data(self, **_kwargs) -> str:
        return "fixture refresh completed"

    def run_yfinance_candidate_analysis(self, **_kwargs) -> str:
        return "fixture rescore completed. Report: candidates.json"


def _make_app_state(snapshot: object) -> AppState:
    return AppState(snapshot=snapshot, selected_etf="ETF1")


def test_headless_refresh_rescore_publish_matches_app_state_path(monkeypatch, tmp_path) -> None:
    _install_scoreboard_fakes(monkeypatch, tmp_path)
    snapshot = _snapshot()
    builder = lambda **_kwargs: snapshot
    monkeypatch.setattr(headless_session, "DataService", _FakeDataService)
    monkeypatch.setattr(headless_session, "build_snapshot", builder)
    headless_root = tmp_path / "headless"
    headless = HeadlessSession(snapshot, root=headless_root, snapshot_builder=builder)

    headless.refresh()
    headless.rescore()
    headless.publish()

    app_root = tmp_path / "app"
    monkeypatch.setattr(app_state_module, "ROOT", app_root)
    monkeypatch.setattr(app_state_module, "DataService", _FakeDataService)
    monkeypatch.setattr(app_state_module, "build_snapshot", builder)
    monkeypatch.setattr(AppState, "refresh_runtime_profile", lambda self, *_args, **_kwargs: "minimum")
    monkeypatch.setattr(AppState, "assign_sector_projections", lambda self, *_args, **_kwargs: None)
    monkeypatch.setattr(app_state_module, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "app" / "logs" / "session.jsonl")
    app_state = _make_app_state(snapshot)
    monkeypatch.setattr(app_state, "_app_activity_publication", lambda *_args: nullcontext())
    AppState.refresh_yfinance_data.__wrapped__(app_state)
    AppState.run_algorithm_scores.__wrapped__(app_state)
    AppState._write_current_scoreboard.__wrapped__(app_state)

    headless_board = pd.read_parquet(headless_root / "data" / "derived" / "scoreboard.parquet")
    app_board = pd.read_parquet(app_root / "data" / "derived" / "scoreboard.parquet")
    pd.testing.assert_frame_equal(headless_board, app_board)


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


def test_blocking_data_quality_gate_prevents_scoreboard_publish(monkeypatch, tmp_path) -> None:
    _install_scoreboard_fakes(monkeypatch, tmp_path)
    root = tmp_path / "blocked"
    session = HeadlessSession(_snapshot(blocked=True), root=root)

    with pytest.raises(scoreboard_publication.ScoreboardPublicationBlockedError):
        session.publish()

    assert not (root / "data" / "derived" / "scoreboard.parquet").exists()
