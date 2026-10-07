from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import date
from inspect import getclosurevars
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
import pandas as pd

import etf_cockpit.app.components.tables as tables
import etf_cockpit.app.pages.chatgpt_audit as chatgpt_audit
import etf_cockpit.app.pages.comparison as comparison
from etf_cockpit.app.pages import _p3_common as common
import etf_cockpit.app.pages.import_export as import_export
import etf_cockpit.app.pages.operations as operations
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.core.job_scheduler import DurableJobScheduler
from etf_cockpit.data.import_export import validate_import


def test_s11_01_operation_worker_is_scoped_to_its_workflow():
    scheduler = DurableJobScheduler.__new__(DurableJobScheduler)
    older_job = N(job_id="old", workflow_id="other", resources={}, cancel_requested=False)
    scheduler.claim_next = Mock(side_effect=lambda **kw: None if kw.get("workflow_id") == "own" else older_job)
    scheduler.resource_policy = Mock()
    scheduler.get_job = Mock(return_value=older_job)
    scheduler.complete = Mock()
    scheduler.checkpoint = Mock()
    scheduler.heartbeat = Mock()
    scheduler.cancel = Mock()
    scheduler.fail = Mock()
    api = LocalApplicationApi(lambda: N(), scheduler=scheduler)
    api.get_paper = Mock(return_value=N(items=[]))
    api.get_portfolios = Mock(return_value=N(items=[]))
    api.get_jobs = Mock(return_value=N(items=[N(workflow_id="own", status="queued")]))
    with (
        patch.object(operations, "load_operation_records", return_value=()),
        patch.object(operations, "load_paper_tca_view", return_value={"status": "unavailable"}),
        patch.object(operations, "save_operation_record"),
    ):
        root = operations.operations_page(None, N(application_api=api, selected_etf="A"))
        run = getclosurevars(root.controls[3].content.controls[2].controls[2].on_click).nonlocals["run_workflow"]
        preview = operations.build_operation_preview(environment="paper", instrument_id="A", quantity=1)
        run(preview, "own")
        scheduler.complete.assert_not_called()


def test_s11_02_failed_job_is_not_recorded_completed():
    api = Mock()
    api.get_paper.return_value = N(items=[])
    api.get_portfolios.return_value = N(items=[])
    api.run_next_job.return_value = N(workflow_id="w", status="failed")
    api.get_jobs.return_value = N(items=[N(workflow_id="w", status="failed")])
    with (
        patch.object(operations, "load_operation_records", return_value=()),
        patch.object(operations, "load_paper_tca_view", return_value={"status": "unavailable"}),
        patch.object(operations, "save_operation_record") as saved,
    ):
        root = operations.operations_page(None, N(application_api=api, selected_etf="A"))
        run = getclosurevars(root.controls[3].content.controls[2].controls[2].on_click).nonlocals["run_workflow"]
        run(operations.build_operation_preview(environment="paper", instrument_id="A", quantity=1), "w")
        assert saved.call_args.args[0].status == "failed"


def test_s11_03_portfolio_context_includes_all_holdings():
    holdings = pd.DataFrame({"etf_id": [f"A{i}" for i in range(51)], "market_value_eur": [100.0] * 51})
    api = LocalApplicationApi(lambda: N(holdings=holdings), scheduler=Mock())
    api.get_paper = Mock(return_value=N(items=[]))
    with (
        patch.object(operations, "load_operation_records", return_value=()),
        patch.object(operations, "load_paper_tca_view", return_value={"status": "unavailable"}),
        patch.object(operations, "metric_card", wraps=operations.metric_card) as cards,
    ):
        operations.operations_page(None, N(application_api=api, selected_etf="A0"))
        assert cards.call_args_list[0].args[1] == operations.format_currency(5100.0)


def test_s11_04_cancelled_worker_preserves_new_preview():
    api = Mock()
    api.get_paper.return_value = N(items=[])
    api.get_portfolios.return_value = N(items=[])
    api.execute.return_value = N(status=operations.ApiStatus.ACCEPTED)
    api.get_jobs.return_value = N(items=[N(workflow_id="w", status="cancelled")])
    with (
        patch.object(operations, "load_operation_records", return_value=()),
        patch.object(operations, "load_paper_tca_view", return_value={"status": "unavailable"}),
        patch.object(operations, "save_operation_record"),
    ):
        root = operations.operations_page(None, N(application_api=api, selected_etf="A"))
        buttons = root.controls[3].content.controls[2].controls
        run = getclosurevars(buttons[2].on_click).nonlocals["run_workflow"]
        finish = getclosurevars(run).nonlocals["finish"]
        set_record = getclosurevars(finish).nonlocals["set_record"]
        first = operations.build_operation_preview(environment="paper", instrument_id="A", quantity=1).with_update(
            status="queued", audit={"workflow_id": "w"}
        )
        set_record(first)
        expected = []

        def late_result(_handler):
            buttons[3].on_click(None)
            root.controls[3].content.controls[1].controls[1].content.value = "2"
            buttons[0].on_click(None)
            expected.append(getclosurevars(buttons[2].on_click).nonlocals["active_record"].operation_id)
            return N(workflow_id="w", status="cancelled")

        api.run_next_job.side_effect = late_result
        run(first, "w")
        assert getclosurevars(buttons[2].on_click).nonlocals["active_record"].operation_id == expected[0]


def _walk_controls(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)


def test_s11_05_comparison_workspace_save_accepts_snapshot_date():
    snapshot = N(
        config=N(),
        signals=[],
        forecasts=[],
        prices={},
        universe_revision="v",
        benchmark_reference_decision_time=None,
        data_report=N(as_of_date=date(2026, 10, 6)),
    )
    state = N(snapshot=snapshot, selected_etf="A", evidence_mode="advanced")
    scores = [N(instrument_key="A", display_id="A", name="A")]
    context = N(benchmark_data_id=None, projection=None, registry=None, identity=None, peer_member_ids=())
    with (
        patch.object(common, "context_from_snapshot", return_value=context),
        patch.object(common, "build_simple_instrument_scores", return_value=scores),
        patch.object(comparison, "_comparison_table", return_value=ft.Text("stub")),
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text") as write,
    ):
        root = comparison.comparison_page(None, state)
        save = [c for c in _walk_controls(root.body) if getattr(c, "key", None) == "comparison.save-workspace"][0]
        save.on_click(None)
        assert '"2026-10-06"' in write.call_args.args[0]


def test_s11_06_browser_import_uses_selected_bytes():
    page = N(services=[], overlay=[], update=Mock())
    state = N(last_message="Ready", snapshot=N(config=N(ui=N(default_page="/import-export"))))
    data = b"published_at,headline,url\n2026-10-06T12:00:00Z,Selected browser news,https://example.com/news/1\n"
    file = ft.FilePickerFile(id=1, name="__hunt_s11_no_server_file__.csv", size=len(data), path=None, bytes=data)
    health = dict(status="available", object_count=0, manifest_count=0, staged_file_count=0, promoted_generation_count=0)
    with (
        patch.object(import_export, "PortfolioImportApplication"),
        patch.object(import_export, "bulk_cache_health", return_value=health),
        patch.object(ft.FilePicker, "pick_files", new=AsyncMock(return_value=[file])),
        patch.object(import_export, "validate_import", wraps=validate_import),
    ):
        centre = import_export.import_export_page(page, state).controls[0].content
        centre.controls[2].controls[0].value = "news"
        asyncio.run(centre.controls[3].controls[1].on_click(None))
        assert "Preview valid" in centre.controls[5].value


def test_s11_07_completed_llm_audit_is_not_shown_as_unrun(monkeypatch):
    page = N(views=[], route="/chatgpt", update=Mock())
    state = N(last_message="Ready", last_export_path=None, current_activity=None, snapshot=N())
    state.begin_activity = Mock(return_value=N(action_id="a"))
    state.update_activity = Mock()
    state.finish_activity = Mock()
    state.release_activity = Mock()
    state.activity_was_cancelled = Mock(return_value=False)
    state.activity_publication = lambda _action_id: nullcontext()
    status = N(model="demo", context_snapshot={}, request_envelope=None, response_payload=None, generation_time=None)
    results = {
        "_thesis_diary_text": "none",
        "_manual_note_credibility_text": "none",
        "load_authority_matrix": N(policy=None),
        "build_version_registry": None,
        "compatibility_summary": dict(record_count=0, registry_signature="none"),
        "load_local_llm_settings": None,
        "build_local_audit_context": {},
        "generate_local_audit_commentary": (status, N(summary="Generated summary")),
        "save_local_audit_commentary": Path("memory-only.json"),
    }
    for name, value in results.items():
        monkeypatch.setattr(chatgpt_audit, name, Mock(return_value=value))

    def render(page_obj, state_obj, route):
        page_obj.views[:] = [N(controls=[chatgpt_audit.chatgpt_audit_page(page_obj, state_obj)])]

    monkeypatch.setattr("etf_cockpit.app.router.render_shell", render)
    chatgpt_audit.chatgpt_audit_page(page, state).controls[4].content.controls[1].controls[1].on_click(None)
    assert "has not been run" not in page.views[0].controls[0].controls[4].content.controls[2].value


def test_s11_08_sort_preserves_active_search():
    table = tables.accessible_table(
        pd.DataFrame({"strategy": ["alpha", "beta"], "return": [0.1, 0.2]}),
        table_id="repro",
    )
    table.search_control.value = "alpha"
    table.search_control.on_change(N(data="alpha"))
    assert len(table.control.rows) == 1
    table.control.columns[1].on_sort(N(ascending=False))
    assert len(table.control.rows) == 1
