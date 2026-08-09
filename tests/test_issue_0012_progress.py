from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from etf_cockpit.app import state as app_state_module
from etf_cockpit.app.pages.dashboard import _activity_panel
from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.pages.import_export import _record_export_terminal
from etf_cockpit.app.pages import jobs as jobs_page_module
from etf_cockpit.app.pages import chatgpt_audit as chatgpt_audit_module
from etf_cockpit.app.pages import import_export as import_export_page_module
from etf_cockpit.app.pages import trust_evidence as trust_evidence_module
from etf_cockpit.app.state import ActivityEntry, ActivityUnavailableError, AppState, _read_recent_activity
from etf_cockpit.core import session_log
from etf_cockpit.core.workflow import LONG_RUNNING_ACTIONS, LONG_RUNNING_ACTION_SPECS, WorkflowTransitionError
from etf_cockpit import services as services_module
from etf_cockpit.data import fund_holdings as fund_holdings_module
from etf_cockpit.data import trade_candidate_analysis as candidate_analysis_module
from etf_cockpit.parsers.contracts import ParseResult, ParseWarning
from etf_cockpit.services import ForecastService
from etf_cockpit.services import build_snapshot


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


@lru_cache(maxsize=1)
def _snapshot():
    return build_snapshot()


def _state() -> AppState:
    snapshot = _snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_issue_0012_contract_names_every_declared_long_running_action() -> None:
    assert tuple(LONG_RUNNING_ACTIONS) == (
        "yfinance_fetch",
        "validation",
        "algorithms",
        "baseline_forecast",
        "timesfm_forecast",
        "toto_forecast",
        "forecasts",
        "scoreboard_write",
        "audit_export",
        "cache_rebuild",
        "notes_news_import",
        "holdings_factsheet_import",
        "macro_news_refresh",
    )
    assert all(label for label in LONG_RUNNING_ACTIONS.values())


def test_direct_state_action_persists_terminal_fields_and_readable_error(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    state = _state()

    action_id = state.begin_activity("Import manual_news", "Reading selected notes").action_id
    state.update_activity(
        "Validating notes",
        completed_units=1,
        total_units=2,
        output_path=tmp_path / "notes.csv",
        expected_action_id=action_id,
    )
    failed = state.fail_activity(
        "Import manual_news",
        ValueError("notes schema is invalid"),
        expected_action_id=action_id,
    )

    assert failed.status == "failed"
    assert failed.started_at
    assert failed.finished_at
    assert failed.step == "Failed"
    assert "schema is invalid" in failed.message
    assert failed.error and "schema is invalid" in failed.error
    assert failed.output_path == str(tmp_path / "notes.csv")

    restored = _read_recent_activity()
    assert len(restored) == 1
    entry = restored[0]
    assert entry.action_id == failed.action_id
    assert entry.started_at == failed.started_at
    assert entry.finished_at == failed.finished_at
    assert entry.error == failed.error
    assert entry.output_path == failed.output_path
    assert entry.status == "failed"

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    terminal = next(row for row in rows if row["event_type"] == "activity_failed")
    assert terminal["output_summary"]["started_at"] == failed.started_at
    assert terminal["output_summary"]["finished_at"] == failed.finished_at
    assert terminal["output_summary"]["error"] == failed.error


@pytest.mark.parametrize(
    ("method_name", "expected_message"),
    (("refresh_sample_data", "Sample data regenerated and signals refreshed."), ("refresh_signals", "Signals refreshed from local data.")),
)
def test_void_state_actions_persist_meaningful_terminal_messages(tmp_path, monkeypatch, method_name, expected_message) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    snapshot = _state().snapshot
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False: snapshot)
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    assert getattr(state, method_name)() is None
    assert state.recent_activity[-1].message == expected_message
    assert state.recent_activity[-1].message != "None"
    assert _read_recent_activity()[-1].message == expected_message


def test_failed_export_result_records_unavailable_terminal_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Export scoreboard", "Preparing export").action_id

    _record_export_terminal(
        state,
        label="Export scoreboard",
        message="Export unavailable: permission denied.",
        destination=tmp_path / "scoreboard.csv",
        ok=False,
        error="permission denied",
        action_id=action_id,
    )

    assert state.current_activity is None
    assert state.recent_activity[-1].status == "failed"
    assert "permission denied" in state.recent_activity[-1].message


def test_forecast_steps_cover_baseline_timesfm_toto_and_scoreboard(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    observed: list[str] = []

    class FakeDataService:
        def __init__(self, _config) -> None:
            pass

        def run_yfinance_forecasts(self, **_kwargs) -> str:
            callback = _kwargs["progress_callback"]
            callback("Running baseline forecasts", 1, 4)
            callback("Checking cached TimesFM forecasts", 2, 4)
            callback("Checking cached Toto forecasts", 3, 4)
            observed.append("forecasts")
            return "baseline ok; optional models unavailable"

    monkeypatch.setattr(app_state_module, "DataService", FakeDataService)
    monkeypatch.setattr(app_state_module, "build_snapshot", lambda force_sample=False: snapshot)
    monkeypatch.setattr(state, "_write_current_scoreboard", lambda: tmp_path / "scoreboard.parquet")

    state.run_forecasting_models()

    assert observed == ["forecasts"]
    assert state.recent_activity[-1].status == "success"
    assert state.recent_activity[-1].output_path == str(tmp_path / "scoreboard.parquet")
    events = [json.loads(line) for line in (tmp_path / "session.jsonl").read_text(encoding="utf-8").splitlines()]
    steps = [row["output_summary"].get("step") for row in events if row["event_type"] == "activity_update"]
    assert {"Running baseline forecasts", "Checking cached TimesFM forecasts", "Checking cached Toto forecasts", "Forecasts and scoreboard complete"} <= set(steps)


def test_activity_panel_renders_spinner_step_progress_and_terminal_error() -> None:
    state = SimpleNamespace(
        current_activity=SimpleNamespace(
            label="Run forecasting models",
            step="Checking cached Toto forecasts",
            completed_units=3,
            total_units=4,
            started_at="2026-08-09T01:02:03+00:00",
        ),
        last_message="Running",
        recent_activity=[
            ActivityEntry(
                label="Export audit packet",
                status="failed",
                step="Failed",
                started_at="2026-08-09T00:00:00+00:00",
                finished_at="2026-08-09T00:01:00+00:00",
                message="Export failed safely.",
                output_path="C:/exports/audit.zip",
                error="permission denied",
            )
        ],
    )

    control = _activity_panel(state)
    assert "Run forecasting models" in _texts(control)
    assert "Current step: Checking cached Toto forecasts" in _texts(control)
    assert "Started: 2026-08-09T01:02:03+00:00" in _texts(control)
    assert any("output: audit.zip" in text and "error: permission denied" in text for text in _texts(control))
    progress_bars = [item for item in _walk(control) if type(item).__name__ == "ProgressBar"]
    assert progress_bars and progress_bars[0].value == 0.75


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_startup_retains_terminal_history_and_recovers_interrupted_activity(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", log_path)
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    state = _state()
    completed_id = state.begin_activity("Completed action", "Working").action_id
    state.finish_activity("Completed safely", expected_action_id=completed_id)
    interrupted_id = state.begin_activity("Interrupted action", "Publishing").action_id

    session_log.init_session_log(clear=False, build_mode="desktop", route="/")
    restored = _read_recent_activity()

    assert [(entry.action_id, entry.status) for entry in restored] == [
        (completed_id, "success"),
        (interrupted_id, "interrupted"),
    ]
    assert restored[-1].error == "Application restarted before this action reached a terminal state."
    assert _read_recent_activity()[-1].status == "interrupted"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert sum(row["event_type"] == "activity_interrupted" for row in rows) == 1
    assert len(log_path.read_text(encoding="utf-8").splitlines()) < session_log.SESSION_LOG_MAX_EVENTS


def test_session_history_retention_is_bounded_and_rehashed_in_place(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    monkeypatch.setattr(session_log, "SESSION_LOG_MAX_EVENTS", 5)
    for index in range(8):
        session_log.append_event({"event_type": "test_event", "sequence_number": index}, path=log_path)

    session_log.init_session_log(clear=False, route="/")

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5
    assert rows[0]["prior_event_hash"] is None
    assert all(row["prior_event_hash"] == rows[index - 1]["event_hash"] for index, row in enumerate(rows[1:], 1))


def test_activity_ownership_and_cancellation_do_not_adopt_or_replace_actions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Owner", "Working").action_id

    with pytest.raises(WorkflowTransitionError):
        state.begin_activity("Unrelated", "Starting")
    with pytest.raises(WorkflowTransitionError):
        state.update_activity("Wrong owner", expected_action_id="not-the-owner")
    assert state.current_activity and state.current_activity.action_id == action_id

    state.cancel_activity(expected_action_id=action_id)
    with pytest.raises(WorkflowTransitionError):
        state.update_activity("Late update", expected_action_id=action_id)
    with pytest.raises(WorkflowTransitionError):
        state.finish_activity("Late success", expected_action_id=action_id)
    assert state.current_activity is not None
    with pytest.raises(WorkflowTransitionError):
        state.begin_activity("Replacement", "Starting")
    state.release_activity(action_id)
    assert state.current_activity is None
    assert [(entry.action_id, entry.status) for entry in state.recent_activity] == [(action_id, "cancelled")]


def test_concurrent_begin_activity_creates_exactly_one_controller_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    barrier = threading.Barrier(3)
    started: list[str] = []
    rejected: list[Exception] = []

    def begin(label: str) -> None:
        barrier.wait()
        try:
            started.append(state.begin_activity(label, "Starting").action_id)
        except Exception as exc:
            rejected.append(exc)

    workers = [threading.Thread(target=begin, args=(f"Action {index}",)) for index in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=2)

    assert len(started) == 1
    assert len(rejected) == 1 and isinstance(rejected[0], WorkflowTransitionError)
    assert [result.action_id for result in state.workflow_controller.active()] == started


def test_cancelled_dashboard_action_cannot_publish_or_create_orphan(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    page = SimpleNamespace(update=lambda: None)
    started = threading.Event()
    release = threading.Event()
    worker_rebuilt = threading.Event()
    rebuild_count = 0
    destination = tmp_path / "published.txt"

    def action() -> str:
        started.set()
        release.wait(2)
        state.assert_activity_publishable()
        destination.write_text("should not publish", encoding="utf-8")
        return "published"

    def record_rebuild(*_args) -> None:
        nonlocal rebuild_count
        rebuild_count += 1
        if rebuild_count >= 2:
            worker_rebuilt.set()

    monkeypatch.setattr("etf_cockpit.app.pages.dashboard._rebuild", record_rebuild)
    _run_action(page, state, "Cancellable action", action)
    assert started.wait(2)
    action_id = state.current_activity.action_id
    state.cancel_activity(expected_action_id=action_id)
    release.set()
    assert worker_rebuilt.wait(2)

    assert not destination.exists()
    assert state.current_activity is None
    assert [(entry.action_id, entry.status) for entry in state.recent_activity] == [(action_id, "cancelled")]


def test_long_running_contract_points_to_real_handlers_and_registered_controls() -> None:
    acceptance = Path("configs/ui_acceptance.yaml").read_text(encoding="utf-8")
    assert tuple(LONG_RUNNING_ACTION_SPECS) == tuple(LONG_RUNNING_ACTIONS)
    for key, spec in LONG_RUNNING_ACTION_SPECS.items():
        assert spec.handler and spec.control_key, key
        assert spec.control_key in acceptance, key
        if spec.handler.startswith("AppState."):
            assert callable(getattr(AppState, spec.handler.split(".", 1)[1]))


@pytest.mark.parametrize("action_kind", ["yfinance", "local_import", "dashboard_result"])
def test_normal_return_unavailable_results_are_failed_activities(action_kind, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / f"{action_kind}.jsonl")
    state = _state()

    class UnavailableService:
        def __init__(self, _config) -> None:
            self.last_operation_succeeded = False

        def refresh_yfinance_data(self, **_kwargs) -> str:
            return "Provider unavailable without changing local data."

        def import_local_file(self, *_args, **_kwargs):
            return SimpleNamespace(ok=False, message="Import validation unavailable.")

    monkeypatch.setattr(app_state_module, "DataService", UnavailableService)
    if action_kind == "yfinance":
        with pytest.raises(ActivityUnavailableError):
            state.refresh_yfinance_data()
    elif action_kind == "local_import":
        with pytest.raises(ActivityUnavailableError):
            state.validate_local_import(str(tmp_path / "input.csv"), "prices")
    else:
        worker_rebuilt = threading.Event()
        rebuild_count = 0

        def record_rebuild(*_args) -> None:
            nonlocal rebuild_count
            rebuild_count += 1
            if rebuild_count >= 2:
                worker_rebuilt.set()

        monkeypatch.setattr("etf_cockpit.app.pages.dashboard._rebuild", record_rebuild)
        _run_action(
            SimpleNamespace(update=lambda: None),
            state,
            "Unavailable callback",
            lambda: SimpleNamespace(status="unavailable", message="Forecast unavailable."),
        )
        deadline = time.time() + 2
        while not state.recent_activity and time.time() < deadline:
            time.sleep(0.02)
        assert worker_rebuilt.wait(2)

    assert state.current_activity is None
    assert state.recent_activity[-1].status == "failed"
    assert "unavailable" in state.recent_activity[-1].message.lower()


def test_cache_cleanup_unavailable_is_failed_and_ui_uses_redacted_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "cache.jsonl")
    monkeypatch.setattr(
        jobs_page_module,
        "generated_cache_cleanup",
        lambda *_args, **_kwargs: {
            "status": "unavailable",
            "removed": [],
            "cache_path": tmp_path / "cache",
            "error": "api_key=raw-cache-secret",
        },
    )
    state = _state()
    control = jobs_page_module.jobs_page(SimpleNamespace(update=lambda: None), state)
    button = next(item for item in _walk(control) if getattr(item, "key", None) == "jobs.resource-cache-cleanup")

    button.on_click(SimpleNamespace())

    assert state.recent_activity[-1].status == "failed"
    assert "raw-cache-secret" not in " ".join(_texts(control))
    assert "***redacted***" in " ".join(_texts(control))


def test_forecast_service_emits_model_steps_at_execution_boundaries(monkeypatch) -> None:
    snapshot = _snapshot()
    prices = snapshot.prices.copy()
    prices["date"] = services_module.pd.to_datetime(prices["date"])
    as_of = prices["date"].max().date()
    etf_id = str(prices.iloc[0]["etf_id"])
    observed: list[str] = []
    service = ForecastService(snapshot.config)

    monkeypatch.setattr(services_module, "baseline_forecast", lambda *_args, **_kwargs: observed.append("baseline-call") or [])
    monkeypatch.setattr(service, "_run_timesfm_forecasts", lambda *_args: observed.append("timesfm-call") or [])
    monkeypatch.setattr(service, "_run_toto_forecasts", lambda *_args: observed.append("toto-call") or [])
    monkeypatch.setattr(services_module, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_write_forecasts", lambda *_args, **_kwargs: None)

    service.run_forecasts(
        as_of,
        [etf_id],
        prices,
        progress_callback=lambda stage, _completed, _total: observed.append(stage),
    )

    assert observed == [
        "Running baseline forecasts",
        "baseline-call",
        "Checking cached TimesFM forecasts",
        "timesfm-call",
        "Checking cached Toto forecasts",
        "toto-call",
        "Writing forecast outputs",
    ]


def test_cancel_guard_blocks_real_price_and_forecast_write_boundaries(tmp_path, monkeypatch) -> None:
    snapshot = _snapshot()
    service = services_module.DataService(snapshot.config)
    provider_result = SimpleNamespace(ok=True, data=snapshot.prices.copy(), message="prices fetched")
    provider = SimpleNamespace(fetch_prices=lambda *_args: provider_result)
    monkeypatch.setattr(services_module.YFinanceProvider, "from_config", staticmethod(lambda _config: provider))
    monkeypatch.setattr(services_module, "validate_prices", lambda *_args, **_kwargs: SimpleNamespace(issues=[]))
    price_commit_called = False

    def commit_prices(_result):
        nonlocal price_commit_called
        price_commit_called = True

    monkeypatch.setattr(services_module, "commit_price_import", commit_prices)

    def cancelled() -> None:
        raise WorkflowTransitionError("cancelled before publication")

    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        service.refresh_yfinance_data(include_reference_data=False, publish_guard=cancelled)
    assert price_commit_called is False

    output = tmp_path / "forecast.csv"
    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        ForecastService(snapshot.config)._write_forecasts([], date(2026, 8, 9), output_path=output, publish_guard=cancelled)
    assert not output.exists()


def test_cancel_guard_blocks_real_candidate_report_and_holdings_atomic_group(tmp_path, monkeypatch) -> None:
    snapshot = _snapshot()
    candidates = services_module.pd.DataFrame({"instrument_id": ["VWCE"], "yahoo_symbol": ["VWCE.DE"]})
    prices = services_module.pd.DataFrame({"date": ["2026-08-08"], "etf_id": ["VWCE"], "adjusted_close": [100.0]})
    candidate_data = candidate_analysis_module.CandidatePriceData(candidates, prices, date(2026, 8, 8), "fixture")
    monkeypatch.setattr(candidate_analysis_module, "fetch_candidate_prices", lambda *_args, **_kwargs: candidate_data)
    monkeypatch.setattr(candidate_analysis_module, "fetch_candidate_fundamentals", lambda *_args: services_module.pd.DataFrame())
    monkeypatch.setattr(candidate_analysis_module, "analyse_candidate_prices", lambda *_args, **_kwargs: services_module.pd.DataFrame({"instrument_id": ["VWCE"]}))
    monkeypatch.setattr(candidate_analysis_module, "REPORTS_DIR", tmp_path / "reports")

    def cancelled() -> None:
        raise WorkflowTransitionError("cancelled before publication")

    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        candidate_analysis_module.refresh_candidate_analysis(snapshot.config, publish_guard=cancelled)
    assert not (tmp_path / "reports").exists()

    source = tmp_path / "holdings.csv"
    services_module.pd.DataFrame({"security": ["Issuer"], "ticker": ["ISS"], "weight": [1.0]}).to_csv(source, index=False)
    holdings_destination = tmp_path / "holdings.parquet"
    registry_destination = tmp_path / "documents.parquet"
    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        fund_holdings_module.import_etf_holdings_with_document(
            source,
            "VWCE",
            "2026-08-08",
            holdings_destination=holdings_destination,
            registry_destination=registry_destination,
            today="2026-08-09",
            publish_guard=cancelled,
        )
    assert not holdings_destination.exists()
    assert not registry_destination.exists()

    disclosure_source = tmp_path / "factsheet.pdf"
    disclosure_source.write_bytes(b"issuer disclosure")
    monkeypatch.setattr(trust_evidence_module, "RAW_DIR", tmp_path / "raw")
    with pytest.raises(WorkflowTransitionError, match="cancelled"):
        trust_evidence_module._retain_picker_source(disclosure_source, "factsheets", publish_guard=cancelled)
    assert not (tmp_path / "raw").exists()


def test_holdings_publication_scope_serialises_cancellation_and_rejects_later_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    state = _state()
    action_id = state.begin_activity("Import ETF holdings", "Publishing holdings").action_id
    source = tmp_path / "holdings.csv"
    services_module.pd.DataFrame({"security": ["Issuer"], "ticker": ["ISS"], "weight": [1.0]}).to_csv(source, index=False)
    write_entered = threading.Event()
    release_write = threading.Event()
    cancellation_returned = threading.Event()
    writes: list[int] = []
    worker_errors: list[Exception] = []

    def blocking_atomic_write(_requests) -> None:
        writes.append(1)
        write_entered.set()
        assert release_write.wait(2)

    monkeypatch.setattr(fund_holdings_module, "atomic_write_group", blocking_atomic_write)

    def publish_holdings(capture_error: bool = True) -> None:
        try:
            fund_holdings_module.import_etf_holdings_with_document(
                source,
                "VWCE",
                "2026-08-08",
                holdings_destination=tmp_path / "holdings.parquet",
                registry_destination=tmp_path / "documents.parquet",
                today="2026-08-09",
                publish_guard=lambda: state.activity_publication(action_id),
            )
        except Exception as exc:
            if not capture_error:
                raise
            worker_errors.append(exc)

    worker = threading.Thread(target=publish_holdings)
    worker.start()
    assert write_entered.wait(2)

    def cancel() -> None:
        state.cancel_activity(expected_action_id=action_id)
        cancellation_returned.set()

    canceller = threading.Thread(target=cancel)
    canceller.start()
    assert not cancellation_returned.wait(0.1)
    release_write.set()
    worker.join(timeout=2)
    assert cancellation_returned.wait(2)
    canceller.join(timeout=2)
    assert not worker_errors
    assert writes == [1]

    with pytest.raises(WorkflowTransitionError):
        publish_holdings(False)
    assert writes == [1]
    state.release_activity(action_id)


def test_esef_normal_unavailable_result_is_failed_terminal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / "session.jsonl")
    source = tmp_path / "report.zip"
    source.write_bytes(b"not an ESEF package")
    monkeypatch.setattr(app_state_module, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(
        app_state_module,
        "parse_esef_package",
        lambda _path: ParseResult((), (ParseWarning("invalid_package", "invalid", "error"),), "esef", "1", "unused", False),
    )
    state = _state()
    action_id = state.begin_activity("Import ESEF package", "Reading package").action_id
    with state.share_activity(action_id), pytest.raises(ActivityUnavailableError) as raised:
        state.import_esef_package(source)
    state.fail_activity("Import ESEF package", raised.value, expected_action_id=action_id)

    assert state.recent_activity[-1].status == "failed"
    assert "unavailable" in state.recent_activity[-1].message.lower()


@pytest.mark.parametrize("page_kind", ["import_export", "chatgpt_audit"])
def test_non_dashboard_terminal_rebuilds_shell_and_redacts_secret(page_kind, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_state_module, "ACTIVITY_LOG_PATH", tmp_path / f"{page_kind}.jsonl")
    state = _state()
    page = SimpleNamespace(route="/", views=[], services=[], overlay=[], update=lambda: None)
    rebuilt: list[str] = []
    monkeypatch.setattr("etf_cockpit.app.router.render_shell", lambda _page, _state, route: rebuilt.append(route))

    if page_kind == "import_export":
        monkeypatch.setattr(
            import_export_page_module,
            "export_table",
            lambda category, frame, destination: SimpleNamespace(
                ok=False,
                destination=destination,
                error="api_key=raw-export-secret",
                rows=0,
            ),
        )
        control = import_export_page_module.import_export_page(page, state)
        button = next(item for item in _walk(control) if getattr(item, "key", None) == "import-export.export-scoreboard")
    else:
        class FailingBridge:
            def __init__(self, _config) -> None:
                pass

            def import_audit_json(self, _path):
                raise ValueError("token=raw-audit-secret")

        monkeypatch.setattr(chatgpt_audit_module, "ChatGPTBridge", FailingBridge)
        monkeypatch.setattr(chatgpt_audit_module, "_thesis_diary_text", lambda: "No persisted diary entries.")
        control = chatgpt_audit_module.chatgpt_audit_page(page, state)
        button = next(item for item in _walk(control) if getattr(item, "key", None) == "chatgpt.import-audit")

    button.on_click(SimpleNamespace())

    visible = " ".join(_texts(control))
    assert "raw-export-secret" not in visible
    assert "raw-audit-secret" not in visible
    assert "***redacted***" in visible
    assert state.recent_activity[-1].status == "failed"
    assert rebuilt == ["/"]
