from __future__ import annotations

from datetime import datetime, timezone
import threading

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.states import state_panel
from etf_cockpit.app.formatting import format_currency, format_number
from etf_cockpit.app.operations import OperationRecord, build_operation_preview, load_operation_records, save_operation_record
from etf_cockpit.app.state import AppState
from etf_cockpit.application.contracts import ApiStatus, CancelWorkflowCommand, SubmitWorkflowCommand


def _safe_update(page: ft.Page | None) -> None:
    if page is not None and callable(getattr(page, "update", None)):
        page.update()


def operations_page(page: ft.Page | None, state: AppState) -> ft.Control:
    api = state.application_api
    paper = api.get_paper()
    portfolios = api.get_portfolios()
    total_value = sum(item.market_value or 0.0 for item in portfolios.items)
    paper_status = paper.items[0].status if paper.items else "unavailable"
    message = ft.Text("No operation has been submitted.", color=theme.MUTED, selectable=True)
    operation_state = ft.Text("State: idle", color=theme.TEXT, weight=ft.FontWeight.BOLD, selectable=True)
    preview_text = ft.Text("Preview: none", color=theme.MUTED, selectable=True)
    authority_text = ft.Text("Authority: paper preview or live disabled", color=theme.MUTED, selectable=True)
    result_text = ft.Text("Result: none", color=theme.MUTED, selectable=True)
    audit_text = ft.Text("Audit: none", color=theme.MUTED, selectable=True)
    instrument = ft.TextField(label="Instrument", value=state.selected_etf or "VWCE", key="operations.instrument", width=180)
    quantity = ft.TextField(label="Quantity", value="1", key="operations.quantity", width=130, keyboard_type=ft.KeyboardType.NUMBER)
    environment = ft.Dropdown(
        label="Environment",
        value="paper",
        key="operations.environment",
        width=190,
        options=[ft.dropdown.Option("paper", "Paper proposal"), ft.dropdown.Option("live", "Live (disabled)")],
    )
    preview_button = ft.OutlinedButton("Preview selected operation", key="operations.preview", icon=ft.Icons.PREVIEW)
    confirm_button = ft.OutlinedButton("Confirm paper workflow", key="operations.confirm", icon=ft.Icons.CHECK, disabled=True)
    cancel_button = ft.TextButton("Cancel workflow", key="operations.cancel", icon=ft.Icons.CANCEL, disabled=True)
    records_body = ft.Column(spacing=6)
    active_record: OperationRecord | None = None
    busy = False

    def set_record(record: OperationRecord) -> None:
        nonlocal active_record
        active_record = record
        operation_state.value = f"State: {record.status}"
        preview_text.value = f"Preview: {record.instrument_id} · {format_number(record.quantity)} · {record.currency} · {record.action}"
        authority_text.value = (
            f"Authority: stage={record.authority.get('stage')} · execution_allowed={str(record.authority.get('execution_allowed')).lower()} · "
            f"{record.authority.get('reason')}"
        )
        result_text.value = f"Result: {record.result.get('status')} · {record.result.get('message')}"
        audit_text.value = f"Audit: record={record.audit.get('record_id')} · workflow={record.audit.get('workflow_id') or 'not submitted'} · event chain={record.audit.get('event_chain')}"

    def refresh_records() -> None:
        records_body.controls = []
        records = load_operation_records()
        if not records:
            records_body.controls.append(ft.Text("No local paper/live operation records yet.", color=theme.MUTED, selectable=True))
        for record in records[:6]:
            records_body.controls.append(
                ft.Text(
                    f"{record.get('operation_id')} · {record.get('environment')} · {record.get('status')} · "
                    f"{record.get('instrument_id')} · workflow={record.get('audit', {}).get('workflow_id') or 'none'}",
                    color=theme.TEXT,
                    size=theme.FONT_XS,
                    selectable=True,
                )
            )

    def finish(record: OperationRecord, status: str, text: str, *, workflow_id: str | None = None) -> None:
        nonlocal busy
        updated = record.with_update(
            status=status,
            result={"status": status, "message": text},
            audit={**record.audit, "workflow_id": workflow_id or record.audit.get("workflow_id")},
        )
        save_operation_record(updated)
        set_record(updated)
        busy = False
        preview_button.disabled = False
        confirm_button.disabled = True
        cancel_button.disabled = True
        refresh_records()
        _safe_update(page)

    def run_workflow(record: OperationRecord, workflow_id: str) -> None:
        try:
            result = api.run_next_job(lambda _context: {"operation_id": record.operation_id, "execution_allowed": False})
            if result is None:
                finish(record, "failed", "The paper preview workflow did not claim a job.", workflow_id=workflow_id)
            elif any(item.workflow_id == workflow_id and item.status == "cancelled" for item in api.get_jobs().items):
                finish(record, "cancelled", "Cancellation recorded; no order was transmitted.", workflow_id=workflow_id)
            else:
                finish(record, "completed", "Paper proposal preview completed; no order was transmitted.", workflow_id=workflow_id)
        except Exception as exc:
            finish(record, "failed", f"Paper preview failed safely: {type(exc).__name__}: {exc}", workflow_id=workflow_id)

    def preview(_event: ft.ControlEvent) -> None:
        if busy:
            message.value = "Duplicate click ignored: the current operation is already running."
            _safe_update(page)
            return
        try:
            selected_environment = str(environment.value or "paper")
            selected_quantity = float(str(quantity.value or "0").replace(",", ""))
            record = build_operation_preview(
                environment=selected_environment,  # type: ignore[arg-type]
                instrument_id=str(instrument.value or ""),
                quantity=selected_quantity,
            )
            save_operation_record(record)
            set_record(record)
            if selected_environment == "live":
                message.value = "Live operation blocked by policy; preview retained locally and no workflow was submitted."
                confirm_button.disabled = True
                refresh_records()
                _safe_update(page)
                return
            message.value = "Paper preview ready. Confirm the local workflow to start it; no order will be transmitted."
            confirm_button.disabled = False
            refresh_records()
            _safe_update(page)
        except (TypeError, ValueError) as exc:
            message.value = f"Preview could not be created: {exc}"
            operation_state.value = "State: error"
            _safe_update(page)

    def confirm(_event: ft.ControlEvent) -> None:
        nonlocal busy
        if busy:
            message.value = "Duplicate click ignored: the current operation is already running."
            _safe_update(page)
            return
        if active_record is None or active_record.status != "preview" or active_record.environment != "paper":
            message.value = "Confirmation blocked: create a valid paper preview first."
            _safe_update(page)
            return
        record = active_record
        busy = True
        preview_button.disabled = True
        confirm_button.disabled = True
        cancel_button.disabled = False
        try:
            dedupe_key = f"paper-preview:{record.operation_id}"
            command = SubmitWorkflowCommand(
                idempotency_key=dedupe_key,
                workflow_type="paper_proposal_preview",
                label=f"Paper proposal preview · {record.instrument_id}",
                input_payload=record.to_payload(),
                job_keys=("preview",),
                dedupe_key=dedupe_key,
            )
            result = api.execute(command)
            if result.status not in {ApiStatus.ACCEPTED, ApiStatus.REPLAYED} or not result.resource_id:
                finish(record, "failed", result.error_message or "The local paper preview workflow was not accepted.")
                return
            queued = record.with_update(
                status="queued",
                result={"status": "queued", "message": "Paper preview workflow acknowledged."},
                audit={**record.audit, "workflow_id": result.resource_id, "command_id": result.command_id},
            )
            save_operation_record(queued)
            set_record(queued)
            message.value = f"Acknowledged locally at {datetime.now(timezone.utc).isoformat(timespec='seconds')}; first workflow event recorded."
            refresh_records()
            _safe_update(page)
            threading.Thread(target=run_workflow, args=(queued, result.resource_id), name="paper-preview", daemon=True).start()
        except (TypeError, ValueError) as exc:
            finish(record, "failed", f"Paper preview could not start safely: {exc}")
            _safe_update(page)

    def cancel(_event: ft.ControlEvent) -> None:
        nonlocal busy
        if active_record is None or not active_record.audit.get("workflow_id"):
            message.value = "Nothing is running; cancellation made no changes."
            _safe_update(page)
            return
        workflow_id = str(active_record.audit["workflow_id"])
        result = api.execute(CancelWorkflowCommand(idempotency_key=f"cancel:{active_record.operation_id}", workflow_id=workflow_id))
        if result.status in {ApiStatus.ACCEPTED, ApiStatus.REPLAYED}:
            finish(active_record, "cancelled", "Cancellation recorded; no order was transmitted.", workflow_id=workflow_id)
            message.value = f"Cancelled local workflow {workflow_id}."
        else:
            message.value = f"Cancellation failed safely: {result.error_message or result.status.value}"
            _safe_update(page)

    preview_button.on_click = preview
    confirm_button.on_click = confirm
    cancel_button.on_click = cancel
    refresh_records()
    portfolio_cards = [
        metric_card("Portfolio context", format_currency(total_value), "Local holdings only"),
        metric_card("Paper account", paper_status, "Reconciliation must be ready before submission"),
        metric_card("Live authority", "Disabled", "No credentials or order route", theme.GREEN),
    ]
    return ft.Column(
        [
            panel(ft.Column([section_header("Operations Centre", "Portfolio, training, paper proposals and live authority in one explicit local-first workspace."), message], spacing=6)),
            ft.ResponsiveRow([ft.Container(content=card, col={"sm": 12, "md": 4}) for card in portfolio_cards], spacing=10),
            ft.ResponsiveRow(
                [
                    ft.Container(content=state_panel("success", "Paper environment", "Paper proposal previews may start a local durable workflow. They never transmit an order.", details="environment=paper · submission=proposal only · execution_allowed=false"), col={"sm": 12, "md": 6}),
                    ft.Container(content=state_panel("warning", "Live environment: disabled", "Live account access, order submission and broker credentials are unavailable in this build.", details="environment=live · authority stage=live_disabled · unknown/reconciling states block submission"), col={"sm": 12, "md": 6}),
                ],
                spacing=10,
            ),
            panel(
                ft.Column(
                    [
                        section_header("Preview and confirm", "A command preview is stored before a local workflow is acknowledged. The selected environment is never inferred from colour."),
                        ft.ResponsiveRow([ft.Container(content=instrument, col={"sm": 12, "md": 3}), ft.Container(content=quantity, col={"sm": 12, "md": 2}), ft.Container(content=environment, col={"sm": 12, "md": 3})], spacing=8),
                        ft.Row([preview_button, confirm_button, cancel_button], wrap=True),
                        operation_state,
                        preview_text,
                        authority_text,
                        result_text,
                        audit_text,
                    ],
                    spacing=8,
                )
            ),
            panel(ft.Column([section_header("Training Centre", "Training jobs, trials, validation and model promotion remain explicitly unavailable until their governed workflow slice is implemented."), ft.Text("State: empty · use Jobs & Activity for existing local durable self-checks; no model is promoted by this page.", color=theme.MUTED, selectable=True)], spacing=6)),
            panel(ft.Column([section_header("Recent operation records", "Local JSON records are reproducible evidence; they are not broker or account truth."), records_body], spacing=6)),
        ],
        expand=True,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )


__all__ = ["operations_page"]
