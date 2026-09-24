"""Score-history persistence failures must stay explicit, never silent."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from etf_cockpit.app import state as app_state_module
from etf_cockpit.app.components.simple_scores import _score_history_panel
from etf_cockpit.app.state import AppState
from etf_cockpit.core import session_log
from etf_cockpit.services import build_snapshot

SECRET = "sk-live-should-never-surface"


@lru_cache(maxsize=1)
def _snapshot():
    return build_snapshot()


def _texts(control: object) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if value is not None:
        values.append(str(value))
    for attribute in ("controls", "content"):
        child = getattr(control, attribute, None)
        children = child if isinstance(child, (list, tuple)) else (child,) if child is not None else ()
        for item in children:
            values.extend(_texts(item))
    return values


def _isolate_scoreboard_write(monkeypatch, tmp_path: Path, *, trust_writer) -> tuple[AppState, Path, list[object], Path]:
    """Stub every publication in the scoreboard path so nothing touches real data dirs."""

    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    scoreboard_path = tmp_path / "simple_scores.parquet"
    scores = [SimpleNamespace(display_id="AAA", final_action="HOLD", execution_allowed=False)]
    monkeypatch.setattr(app_state_module, "load_latest_candidate_report", lambda: (None, None))
    monkeypatch.setattr(
        app_state_module,
        "context_from_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(
            benchmark_data_id="BENCH",
            projection=None,
            registry=None,
            identity=None,
            peer_member_ids=(),
        ),
    )
    monkeypatch.setattr(app_state_module, "build_market_regime", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(app_state_module, "write_market_regime", lambda _regime: None)
    monkeypatch.setattr(app_state_module, "load_forecast_history", lambda: None)
    monkeypatch.setattr(app_state_module, "evaluate_forecast_calibration", lambda *_args: object())
    monkeypatch.setattr(app_state_module, "write_forecast_calibration", lambda _calibration: None)
    monkeypatch.setattr(app_state_module, "build_simple_instrument_scores", lambda *_args, **_kwargs: scores)
    monkeypatch.setattr(app_state_module, "write_simple_scoreboard", lambda _scores: scoreboard_path)
    monkeypatch.setattr(app_state_module, "simple_scoreboard_frame", lambda _scores: None)
    monkeypatch.setattr(app_state_module, "write_trust_artifacts_for_scores", trust_writer)
    snapshot = _snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    return state, scoreboard_path, scores, log_path


def _failing_trust_writer(*_args, **_kwargs):
    raise OSError(f"disk full while writing score_history.parquet api_key={SECRET}")


def _events(log_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_trust_artifact_failure_returns_scoreboard_and_records_explicit_warning(monkeypatch, tmp_path) -> None:
    state, scoreboard_path, scores, log_path = _isolate_scoreboard_write(
        monkeypatch, tmp_path, trust_writer=_failing_trust_writer
    )

    result = state._write_current_scoreboard()

    assert result == scoreboard_path
    warning = state.score_history_warning
    assert warning is not None
    assert warning.startswith("Score history was not persisted (OSError: disk full")
    assert scoreboard_path.name in warning
    assert "unavailable, not empty" in warning
    assert SECRET not in warning
    assert state.recent_activity[-1].status == "success"
    assert state.recent_activity[-1].output_path == str(scoreboard_path)
    assert [(score.final_action, score.execution_allowed) for score in scores] == [("HOLD", False)]

    warnings = [event for event in _events(log_path) if event["event_type"] == "score_history_not_persisted"]
    assert len(warnings) == 1
    event = warnings[0]
    assert event["severity"] == "warning"
    assert event["status"] == "unavailable"
    assert event["operation"] == "write_trust_artifacts_for_scores"
    assert event["exception_type"] == "OSError"
    assert event["warnings"] == ["score_history_not_persisted"]
    assert event["action_id"] == state.recent_activity[-1].action_id
    assert SECRET not in json.dumps(event)


def test_nested_scoreboard_failure_is_carried_into_the_action_result(monkeypatch, tmp_path) -> None:
    state, scoreboard_path, _scores, _log_path = _isolate_scoreboard_write(
        monkeypatch, tmp_path, trust_writer=_failing_trust_writer
    )

    class FakeDataService:
        def __init__(self, _config) -> None:
            pass

        def run_yfinance_candidate_analysis(self, **_kwargs) -> str:
            return "Candidate analysis ok. Report: candidates.json"

    monkeypatch.setattr(app_state_module, "DataService", FakeDataService)
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False, **_kwargs: state.snapshot)

    message = state.run_algorithm_scores()

    assert f"Scoreboard updated: {scoreboard_path.name}." in message
    assert "Score history was not persisted" in message
    assert "Score history was not persisted" in state.last_message
    assert state.recent_activity[-1].status == "success"
    assert "Score history was not persisted" in state.recent_activity[-1].message
    assert SECRET not in message


def test_successful_trust_write_clears_previous_warning(monkeypatch, tmp_path) -> None:
    calls: list[object] = []
    state, scoreboard_path, _scores, log_path = _isolate_scoreboard_write(
        monkeypatch, tmp_path, trust_writer=lambda *args, **_kwargs: calls.append(args)
    )
    state.score_history_warning = "Score history was not persisted (stale)."

    assert state._write_current_scoreboard() == scoreboard_path

    assert len(calls) == 1
    assert state.score_history_warning is None
    assert not any(event["event_type"] == "score_history_not_persisted" for event in _events(log_path))


def test_score_history_panel_distinguishes_failed_persistence_from_first_run() -> None:
    warning = "Score history was not persisted (OSError: disk full)."

    first_run = "\n".join(_texts(_score_history_panel(SimpleNamespace(), [])))
    failed = "\n".join(_texts(_score_history_panel(SimpleNamespace(), [], persistence_warning=warning)))
    failed_with_rows = "\n".join(
        _texts(
            _score_history_panel(
                SimpleNamespace(),
                [{"final_combined_score_10": 6.0}],
                persistence_warning=warning,
            )
        )
    )

    assert "No score history available yet" in first_run
    assert "No score history available yet" not in failed
    assert "Score history unavailable" in failed
    assert warning in failed
    assert "1 earlier stored point(s) do not include this run." in failed_with_rows
