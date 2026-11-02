from __future__ import annotations

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
