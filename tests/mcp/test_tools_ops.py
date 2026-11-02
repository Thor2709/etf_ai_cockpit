from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.errors import ConfirmationError
from etf_cockpit.mcp.registry import CallContext, invoke_tool, use_call_context


def _context(root: Path) -> CallContext:
    return CallContext(
        enabled_tiers=frozenset({"read", "edit", "read_job"}),
        profile="full",
        session=SimpleNamespace(root=root),
        audit=AuditRecorder(sink=lambda _record: None),
    )


def test_write_tools_refuse_invalid_confirmation_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import alerts, chatgpt_review
    from etf_cockpit.core import settings_bundle

    writes: list[str] = []
    monkeypatch.setattr(alerts, "dismiss_local_alert", lambda *args, **kwargs: writes.append("alert"))
    monkeypatch.setattr(chatgpt_review.ChatGPTBridge, "import_audit_json", lambda *args, **kwargs: writes.append("audit"))
    monkeypatch.setattr(settings_bundle, "save_settings", lambda *args, **kwargs: writes.append("settings"))
    calls = (
        ("alert_update", {"alert_id": "a1", "action": "dismiss", "expected_revision": 1, "confirm_token": ""}),
        ("audit_import", {"path": "audit.json", "confirm_token": ""}),
        ("settings_change_commit", {"changes": {"providers.providers.test.active_provider": "none"}, "expected_revision": "r1", "confirm_token": ""}),
    )
    context = _context(tmp_path)
    for name, arguments in calls:
        with pytest.raises(ConfirmationError):
            invoke_tool(name, arguments, context=context)
    assert writes == []
    assert [record.reason_code for record in context.audit.records] == ["CONFIRMATION_REQUIRED"] * 3


def test_unavailable_alert_store_stays_unavailable_and_never_becomes_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import alerts
    from etf_cockpit.mcp import tools_ops

    monkeypatch.setattr(alerts, "read_local_alerts", lambda *args, **kwargs: SimpleNamespace(status="unavailable", records=()))
    with use_call_context(_context(tmp_path)):
        result = tools_ops.alerts_list()
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"]
    assert "total" not in result
    assert "count" not in result


def test_alert_output_uses_bounded_signed_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import alerts
    from etf_cockpit.mcp import tools_ops

    records = tuple(SimpleNamespace(alert_id=f"a{index}", status="active", revision=index) for index in range(5))
    monkeypatch.setattr(alerts, "read_local_alerts", lambda *args, **kwargs: SimpleNamespace(status="available", records=records))
    context = _context(tmp_path)
    with use_call_context(context):
        first = tools_ops.alerts_list(limit=2)
        second = tools_ops.alerts_list(cursor=first["next_cursor"], limit=2)
    assert [row.alert_id for row in first["alerts"]] == ["a0", "a1"]
    assert [row.alert_id for row in second["alerts"]] == ["a2", "a3"]
    assert first["next_cursor"] and second["next_cursor"]
    assert len(first["alerts"]) <= 2


def test_status_tools_call_the_canonical_application_aggregators(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import status_views
    from etf_cockpit.mcp import tools_jobs, tools_ops

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(status_views, "build_gate_status", lambda **kwargs: calls.append(("gates", kwargs)) or {"status": "unavailable", "data_quality": {"status": "unavailable"}})
    monkeypatch.setattr(status_views, "build_cockpit_status", lambda **kwargs: calls.append(("cockpit", kwargs)) or {"status": "available", "execution_allowed": False})
    context = _context(tmp_path)
    with use_call_context(context):
        gates = tools_ops.gates_status()
        cockpit = tools_jobs.cockpit_status()
    assert gates["status"] == "unavailable"
    assert cockpit["execution_allowed"] is False
    assert calls[0][0] == "gates" and calls[0][1]["root"] == tmp_path.resolve()
    assert calls[1][0] == "cockpit" and calls[1][1]["enabled_tiers"] == ("edit", "read", "read_job")


def test_settings_and_resource_catalogue_use_canonical_readers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import validation_report
    from etf_cockpit.mcp import tools_ops
    from etf_cockpit.mcp import server as server_module
    from etf_cockpit.mcp.prompts import prompt_specs
    from etf_cockpit.mcp.resources import resource_specs

    calls: list[object] = []
    monkeypatch.setattr(validation_report, "load_settings_view", lambda root, section: calls.append((root, section)) or {"controls": {"output_currency": "EUR"}, "revision": "rev-1", "settings_version": 3})
    with use_call_context(_context(tmp_path)):
        result = tools_ops.settings_get("controls")
    assert result == {"controls": {"output_currency": "EUR"}, "revision": "rev-1", "settings_version": 3}
    assert calls == [(tmp_path.resolve(), "controls")]
    assert len(resource_specs()) == 13
    assert {item.name for item in prompt_specs()} == {
        "health_check", "weekly_review", "research_best_etfs", "research_best_stocks", "assess_web_candidates",
        "sentiment_paper_trade", "add_instrument", "explain_instrument", "monthly_decision", "bots_review",
    }

    class FakeServer:
        def __init__(self, name: str, *, instructions: str) -> None:
            self.name = name
            self.instructions = instructions
            self.tools: list[str] = []
            self.resources: list[str] = []
            self.prompts: list[str] = []

        def add_tool(self, _function, *, name: str, **_kwargs) -> None:
            self.tools.append(name)

        def resource(self, uri: str, **_kwargs):
            return lambda _function: self.resources.append(uri)

        def prompt(self, *, name: str, **_kwargs):
            return lambda _function: self.prompts.append(name)

    monkeypatch.setattr(server_module, "_load_sdk", lambda: (FakeServer, RuntimeError, lambda **kwargs: kwargs))
    server = server_module.create_server(profile="core", tiers=("read",))
    assert len(server.resources) == 13
    assert len(server.prompts) == 10
    assert "execution_allowed is always false" in server.instructions


def test_report_export_submits_job_and_delegates_to_canonical_export_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import portfolio_views
    from etf_cockpit.application.chatgpt_review import ChatGPTBridge
    from etf_cockpit.application.workflow_handlers import headless_workflow_handlers
    from etf_cockpit.mcp import tools_ops
    from etf_cockpit.mcp.errors import InvalidArgumentsError

    submitted: list[tuple[object, ...]] = []
    workflow_inputs = {"kind": "review_pack", "as_of": None}
    data_report = SimpleNamespace(as_of_date=date(2025, 1, 2))
    snapshot = SimpleNamespace(
        config=object(), data_report=data_report, holdings=[], features=[], signals=[],
        ensure_backtest=lambda: "canonical-backtest",
    )
    session = SimpleNamespace(
        root=tmp_path,
        snapshot=snapshot,
        submit_workflow=lambda *args, **kwargs: submitted.append((args, kwargs)) or "workflow-1",
        get_workflow=lambda _workflow_id: SimpleNamespace(inputs=workflow_inputs),
        publish=lambda: submitted.append(("publish",)),
        activity_publication=lambda *_args, **_kwargs: None,
    )
    context = _context(tmp_path)
    context.session = session
    with use_call_context(context):
        with pytest.raises(InvalidArgumentsError):
            tools_ops.report_export(as_of="2025-01-02T12:00:00")
        submitted_result = tools_ops.report_export()
    assert submitted_result["status"] == "submitted"
    assert submitted_result["job_id"] == "workflow-1"
    assert submitted[0][0] == ("report_export",)
    assert submitted[0][1]["input_payload"] == {"kind": "review_pack", "as_of": None}

    export_calls: list[tuple[object, ...]] = []
    export_path = tmp_path / "data" / "chatgpt_exports" / "audit_packet_2025-01-02.zip"
    export_path.parent.mkdir(parents=True)
    export_path.write_bytes(b"archive")
    export_summary = export_path.with_suffix("") / "combined_review_packet.md"
    export_summary.parent.mkdir(parents=True)
    export_summary.write_text("review", encoding="utf-8")
    monkeypatch.setattr(
        ChatGPTBridge,
        "export_review_pack",
        lambda self, *args, **kwargs: export_calls.append((self, args, kwargs)) or export_path,
    )
    handler = headless_workflow_handlers(lambda: session, include_paper=True)["report_export"]
    result = handler(SimpleNamespace(workflow_id="workflow-1"))
    assert result["status"] == "exported"
    assert result["path"] == "data/chatgpt_exports/audit_packet_2025-01-02.zip"
    assert result["resource_link"]["uri"] == "cockpit://exports/data/chatgpt_exports/audit_packet_2025-01-02/combined_review_packet.md"
    assert len(export_calls) == 1
    assert export_calls[0][1][0] == date(2025, 1, 2)
    assert export_calls[0][1][4] == "canonical-backtest"
    assert submitted[-1] == ("publish",)

    portfolio_path = tmp_path / "data" / "reports" / "portfolio.json"
    portfolio_path.parent.mkdir(parents=True)
    portfolio_path.write_text("{}", encoding="utf-8")
    portfolio_calls: list[tuple[object, ...]] = []

    def create_review(signals, report, *, run_id):
        portfolio_calls.append((signals, report, run_id))
        return {"status": "draft", "path": str(portfolio_path)}

    monkeypatch.setattr(portfolio_views, "create_portfolio_review_report", create_review)
    workflow_inputs.update({"kind": "portfolio_review", "as_of": None})
    result = handler(SimpleNamespace(workflow_id="workflow-2"))
    assert result["status"] == "draft"
    assert portfolio_calls == [([], data_report, "manual_trade_proposal")]


def test_incident_status_reads_freeze_projection_without_lock_or_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import status_views
    from etf_cockpit.trading.incidents import IncidentJournal

    journal = IncidentJournal(tmp_path)
    journal.record("paper_state_mismatch", message="Paper state differs", requires_freeze=True)
    original_journal = journal.path.read_bytes()
    original_head = journal._head_path.read_bytes()

    def forbidden_lock(_self):
        pytest.fail("incident status must not acquire the journal lock")

    monkeypatch.setattr(IncidentJournal, "_file_lock", forbidden_lock)
    from etf_cockpit.application.incident_status import load_incident_status

    projection = load_incident_status(tmp_path)
    assert projection["status"] == "frozen"
    assert projection["frozen"] is True
    assert len(projection["active_incidents"]) == 1
    assert journal.path.read_bytes() == original_journal
    assert journal._head_path.read_bytes() == original_head

    from etf_cockpit.application import quality_programme
    from etf_cockpit.governance import release_certification
    from etf_cockpit.security import policy

    monkeypatch.setattr(status_views, "_data_health", lambda _root: {"status": "passed"})
    monkeypatch.setattr(status_views, "load_validation_report", lambda _root: {"status": "passed"})
    monkeypatch.setattr(status_views, "_paper_kill_switch_status", lambda _root: {"status": "available", "active": False})
    monkeypatch.setattr(release_certification, "release_certification_report", lambda _root: {"status": "passed"})
    monkeypatch.setattr(policy, "build_security_report", lambda _root: {"status": "passed"})
    monkeypatch.setattr(quality_programme, "load_quality_programme_report", lambda _root: {"status": "passed"})
    gates = status_views.build_gate_status(root=tmp_path)
    assert gates["freeze"]["frozen"] is True
    assert gates["status"] == "blocked"


def test_settings_ui_is_unsupported_and_provider_writes_match_bundle_fields(tmp_path: Path) -> None:
    from etf_cockpit.application.validation_report import _apply_provider_setting, load_settings_view

    ui = load_settings_view(tmp_path, "ui")
    assert ui["status"] == "unsupported"
    assert ui["section"] == "ui"
    values: dict[str, object] = {}
    _apply_provider_setting(values, "providers.providers.yfinance.base_url", "")
    assert values["providers"]["providers"]["yfinance"]["base_url"] == ""
    with pytest.raises(ValueError, match="only providers.providers"):
        _apply_provider_setting(values, "controls.output_currency", "USD")
    with pytest.raises(ValueError, match="not allow-listed"):
        _apply_provider_setting(values, "providers.providers.yfinance.api_key", "secret")
