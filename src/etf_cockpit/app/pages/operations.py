from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.states import state_panel
from etf_cockpit.app.formatting import format_currency, format_number
from etf_cockpit.app.operations import OperationRecord, build_operation_preview, load_operation_records, save_operation_record
from etf_cockpit.app.state import AppState
from etf_cockpit.application.contracts import (
    ApiStatus,
    CancelWorkflowCommand,
    PaperCorporateActionRequest,
    PaperAccountOpenRequest,
    PaperFillRequest,
    PaperOrderCancelRequest,
    PaperOperationalErrorRequest,
    PaperOutcomeMatureRequest,
    PaperPositionMarkRequest,
    PaperProposalAcceptRequest,
    PaperProposalDeferRequest,
    PaperProposalRejectRequest,
    ProposalReviewRequest,
    SubmitWorkflowCommand,
)


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
    proposal_state = ft.Text("Proposal review: not evaluated", color=theme.MUTED, selectable=True)
    proposal_evidence = ft.Text("Proposal evidence: validated optimiser output and all policy gates are required.", color=theme.MUTED, selectable=True)
    paper_account_text = ft.Text(_paper_summary(paper.items[0] if paper.items else None), color=theme.MUTED, selectable=True)
    paper_account_id = ft.TextField(label="Paper account ID", value="local-paper", key="operations.paper-account-id", width=180)
    paper_initial_cash = ft.TextField(label="Opening cash (EUR)", value="100000", key="operations.paper-initial-cash", width=180)
    paper_open_button = ft.OutlinedButton("Open local paper account", key="operations.paper-open", icon=ft.Icons.ACCOUNT_BALANCE)
    paper_proposal_id = ft.TextField(label="Validated proposal ID", key="operations.paper-proposal-id", width=230)
    paper_execution_price = ft.TextField(label="Paper fill price", value="100", key="operations.paper-price", width=150, keyboard_type=ft.KeyboardType.NUMBER)
    paper_accept_button = ft.OutlinedButton("Accept to paper", key="operations.paper-accept", icon=ft.Icons.CHECK)
    paper_auto_button = ft.OutlinedButton("Auto-paper (local)", key="operations.paper-auto", icon=ft.Icons.PLAY_ARROW)
    paper_reject_reason = ft.TextField(label="Reject reason", value="Manual review required", key="operations.paper-reject-reason", width=230)
    paper_reject_button = ft.TextButton("Reject proposal", key="operations.paper-reject", icon=ft.Icons.BLOCK)
    paper_defer_reason = ft.TextField(label="Defer reason", value="Wait for a fresh evidence window", key="operations.paper-defer-reason", width=250)
    paper_defer_button = ft.TextButton("Defer proposal", key="operations.paper-defer", icon=ft.Icons.PAUSE)
    paper_order_id = ft.TextField(label="Paper order ID", key="operations.paper-order-id", width=230)
    paper_fill_quantity = ft.TextField(label="Fill quantity", value="1", key="operations.paper-fill-quantity", width=130, keyboard_type=ft.KeyboardType.NUMBER)
    paper_fill_price = ft.TextField(label="Fill price", value="100", key="operations.paper-fill-price", width=130, keyboard_type=ft.KeyboardType.NUMBER)
    paper_fill_button = ft.OutlinedButton("Record fill", key="operations.paper-fill", icon=ft.Icons.ADD_TASK)
    paper_cancel_reason = ft.TextField(label="Cancel reason", value="Manual review deferred", key="operations.paper-cancel-reason", width=230)
    paper_cancel_button = ft.TextButton("Cancel paper order", key="operations.paper-order-cancel", icon=ft.Icons.CANCEL)
    paper_mark_instrument = ft.TextField(label="Mark instrument", value=state.selected_etf or "VWCE", key="operations.paper-mark-instrument", width=180)
    paper_mark_price = ft.TextField(label="Adjusted-close mark", value="100", key="operations.paper-mark-price", width=160, keyboard_type=ft.KeyboardType.NUMBER)
    paper_mark_checksum = ft.TextField(label="Mark source checksum", value="a" * 64, key="operations.paper-mark-checksum", width=280)
    paper_mark_button = ft.OutlinedButton("Record adjusted-close mark", key="operations.paper-mark", icon=ft.Icons.QUERY_STATS)
    paper_split_ratio = ft.TextField(label="Split ratio", value="1", key="operations.paper-split-ratio", width=130, keyboard_type=ft.KeyboardType.NUMBER)
    paper_dividend = ft.TextField(label="Dividend/unit", value="0", key="operations.paper-dividend", width=130, keyboard_type=ft.KeyboardType.NUMBER)
    paper_action_checksum = ft.TextField(label="Action source checksum", value="b" * 64, key="operations.paper-action-checksum", width=280)
    paper_action_button = ft.OutlinedButton("Apply corporate action", key="operations.paper-corporate-action", icon=ft.Icons.ACCOUNT_BALANCE)
    paper_outcome_reference = ft.TextField(label="Outcome order/proposal ID", key="operations.paper-outcome-reference", width=230)
    paper_outcome_benchmark = ft.TextField(label="Benchmark return", value="0", key="operations.paper-outcome-benchmark", width=140, keyboard_type=ft.KeyboardType.NUMBER)
    paper_outcome_cash = ft.TextField(label="Cash return", value="0", key="operations.paper-outcome-cash", width=120, keyboard_type=ft.KeyboardType.NUMBER)
    paper_outcome_button = ft.OutlinedButton("Mature outcome", key="operations.paper-outcome", icon=ft.Icons.ASSESSMENT)
    paper_incident_code = ft.TextField(label="Incident code", value="manual_review", key="operations.paper-incident-code", width=160)
    paper_incident_message = ft.TextField(label="Operational incident", value="Evidence unavailable", key="operations.paper-incident-message", width=240)
    paper_incident_button = ft.TextButton("Record incident", key="operations.paper-incident", icon=ft.Icons.WARNING)
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
    proposal_button = ft.OutlinedButton("Validate proposal review", key="operations.proposal-review", icon=ft.Icons.RULE)
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

    def proposal_review(_event: ft.ControlEvent) -> None:
        try:
            selected_quantity = float(str(quantity.value or "0").replace(",", ""))
            as_of = datetime.combine(state.snapshot.data_report.as_of_date, datetime.min.time(), tzinfo=timezone.utc)
            decision = api.review_proposal(
                ProposalReviewRequest(
                    instrument_id=str(instrument.value or ""),
                    current_quantity=0.0,
                    target_quantity=selected_quantity,
                    strategy_id="strategy:manual_review",
                    strategy_stage="research",
                    model_id="model:baseline",
                    model_stage="research",
                    account_id="broker:paper_portfolio",
                    account_stage="paper",
                    optimiser_output_id=None,
                    portfolio_revision=None,
                    data_revision=None,
                    as_of=as_of,
                    expires_at=as_of + timedelta(days=1),
                    authority_policy_checksum=api.get_authority_policy_checksum(),
                    rationale="Manual input is shown as review-only until validated optimiser and portfolio evidence is supplied.",
                )
            )
            failed = sum(not item.passed for item in decision.gates)
            alternatives = ", ".join(decision.alternatives)
            gate_summary = ", ".join(f"{item.gate_id}={'passed' if item.passed else 'failed'}" for item in decision.gates)
            proposal_state.value = f"Proposal review: {decision.outcome} · authority={decision.authority_stage} · allowed={str(decision.proposal_allowed).lower()}"
            proposal_evidence.value = f"Proposal evidence: {failed} gate(s) failed; gates={gate_summary}; alternatives={alternatives}; execution_allowed=false. {decision.rationale}"
            message.value = "Proposal review recorded locally. No order or draft-order authority was created."
            _safe_update(page)
        except (OSError, TypeError, ValueError) as exc:
            proposal_state.value = "Proposal review: manual_review"
            proposal_evidence.value = f"Proposal evidence unavailable: {exc}"
            _safe_update(page)

    def refresh_paper_account() -> None:
        current = api.get_paper(account_id=str(paper_account_id.value or "local-paper")).items
        paper_account_text.value = _paper_summary(current[0] if current else None)

    def open_paper_account(_event: ft.ControlEvent) -> None:
        try:
            view = api.open_paper_account(
                PaperAccountOpenRequest(account_id=str(paper_account_id.value or "local-paper"), initial_cash=float(str(paper_initial_cash.value or "0").replace(",", "")))
            )
            paper_account_text.value = _paper_summary(view)
            message.value = "Local paper account is ready. No broker credentials or order route were used."
        except (OSError, TypeError, ValueError) as exc:
            paper_account_text.value = f"Paper account unavailable: {exc}"
            message.value = f"Paper account could not be opened safely: {exc}"
        _safe_update(page)

    def accept_paper_proposal(_event: ft.ControlEvent) -> None:
        try:
            result = api.accept_paper_proposal(
                PaperProposalAcceptRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    proposal_id=str(paper_proposal_id.value or ""),
                    execution_price=float(str(paper_execution_price.value or "0").replace(",", "")),
                )
            )
            message.value = f"Paper order {result.order_id} accepted locally ({result.status}); execution_allowed=false."
            refresh_paper_account()
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Paper acceptance blocked safely: {exc}"
        _safe_update(page)

    def auto_paper_proposal(_event: ft.ControlEvent) -> None:
        try:
            result = api.accept_paper_proposal(
                PaperProposalAcceptRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    proposal_id=str(paper_proposal_id.value or ""),
                    execution_price=float(str(paper_execution_price.value or "0").replace(",", "")),
                    mode="auto_paper",
                )
            )
            message.value = f"Auto-paper order {result.order_id} accepted locally; execution_allowed=false."
            refresh_paper_account()
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Auto-paper decision blocked safely: {exc}"
        _safe_update(page)

    def reject_paper_proposal(_event: ft.ControlEvent) -> None:
        try:
            result = api.reject_paper_proposal(
                PaperProposalRejectRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    proposal_id=str(paper_proposal_id.value or ""),
                    reason=str(paper_reject_reason.value or ""),
                )
            )
            message.value = f"Proposal {result.proposal_id} rejected locally; no paper order was created."
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Proposal rejection could not be recorded safely: {exc}"
        _safe_update(page)

    def defer_paper_proposal(_event: ft.ControlEvent) -> None:
        try:
            result = api.defer_paper_proposal(
                PaperProposalDeferRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    proposal_id=str(paper_proposal_id.value or ""),
                    reason=str(paper_defer_reason.value or ""),
                )
            )
            message.value = f"Proposal {result.proposal_id} deferred locally; no paper order was created."
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Proposal deferral could not be recorded safely: {exc}"
        _safe_update(page)

    def fill_paper_order(_event: ft.ControlEvent) -> None:
        try:
            result = api.fill_paper_order(
                PaperFillRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    order_id=str(paper_order_id.value or ""),
                    quantity=float(str(paper_fill_quantity.value or "0").replace(",", "")),
                    price=float(str(paper_fill_price.value or "0").replace(",", "")),
                )
            )
            paper_order_id.value = result.order_id
            message.value = f"Paper fill recorded for {result.order_id}; status={result.status}; execution_allowed=false."
            refresh_paper_account()
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Paper fill blocked safely: {exc}"
        _safe_update(page)

    def cancel_paper_order(_event: ft.ControlEvent) -> None:
        try:
            result = api.cancel_paper_order(
                PaperOrderCancelRequest(account_id=str(paper_account_id.value or "local-paper"), order_id=str(paper_order_id.value or ""), reason=str(paper_cancel_reason.value or ""))
            )
            message.value = f"Paper order {result.order_id} is {result.status}; no order was transmitted."
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Paper cancellation blocked safely: {exc}"
        _safe_update(page)

    def mark_paper_position(_event: ft.ControlEvent) -> None:
        try:
            view = api.mark_paper_position(
                PaperPositionMarkRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    instrument_id=str(paper_mark_instrument.value or ""),
                    adjusted_close=float(str(paper_mark_price.value or "0").replace(",", "")),
                    as_of=datetime.now(timezone.utc),
                    source_authority="local_manual_adjusted_close",
                    source_checksum=str(paper_mark_checksum.value or ""),
                )
            )
            paper_account_text.value = _paper_summary(view)
            message.value = "Adjusted-close mark recorded with source provenance; execution_allowed=false."
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Adjusted-close mark blocked safely: {exc}"
        _safe_update(page)

    def apply_paper_corporate_action(_event: ft.ControlEvent) -> None:
        try:
            view = api.apply_paper_corporate_action(
                PaperCorporateActionRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    instrument_id=str(paper_mark_instrument.value or ""),
                    split_ratio=float(str(paper_split_ratio.value or "0").replace(",", "")),
                    cash_dividend_per_unit=float(str(paper_dividend.value or "0").replace(",", "")),
                    as_of=datetime.now(timezone.utc),
                    source_authority="local_manual_corporate_action",
                    source_checksum=str(paper_action_checksum.value or ""),
                )
            )
            paper_account_text.value = _paper_summary(view)
            message.value = "Corporate action recorded with source provenance; execution_allowed=false."
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Corporate action blocked safely: {exc}"
        _safe_update(page)

    def mature_paper_outcome(_event: ft.ControlEvent) -> None:
        try:
            view = api.mature_paper_outcome(
                PaperOutcomeMatureRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    reference_id=str(paper_outcome_reference.value or ""),
                    adjusted_close=float(str(paper_mark_price.value or "0").replace(",", "")),
                    benchmark_return=float(str(paper_outcome_benchmark.value or "0").replace(",", "")),
                    cash_return=float(str(paper_outcome_cash.value or "0").replace(",", "")),
                    as_of=datetime.now(timezone.utc),
                    source_authority="local_manual_adjusted_close",
                    source_checksum=str(paper_mark_checksum.value or ""),
                )
            )
            message.value = f"Paper outcome {view.outcome_id} matured against benchmark and cash; execution_allowed=false."
            refresh_paper_account()
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Paper outcome could not be matured safely: {exc}"
        _safe_update(page)

    def record_paper_incident(_event: ft.ControlEvent) -> None:
        try:
            view = api.record_paper_operational_error(
                PaperOperationalErrorRequest(
                    account_id=str(paper_account_id.value or "local-paper"),
                    code=str(paper_incident_code.value or ""),
                    message=str(paper_incident_message.value or ""),
                )
            )
            message.value = f"Operational incident {view.incident_id} recorded separately from investment performance."
            refresh_paper_account()
        except (OSError, TypeError, ValueError) as exc:
            message.value = f"Operational incident could not be recorded safely: {exc}"
        _safe_update(page)

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
    proposal_button.on_click = proposal_review
    paper_open_button.on_click = open_paper_account
    paper_accept_button.on_click = accept_paper_proposal
    paper_auto_button.on_click = auto_paper_proposal
    paper_reject_button.on_click = reject_paper_proposal
    paper_defer_button.on_click = defer_paper_proposal
    paper_fill_button.on_click = fill_paper_order
    paper_cancel_button.on_click = cancel_paper_order
    paper_mark_button.on_click = mark_paper_position
    paper_action_button.on_click = apply_paper_corporate_action
    paper_outcome_button.on_click = mature_paper_outcome
    paper_incident_button.on_click = record_paper_incident
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
                        ft.Row([preview_button, proposal_button, confirm_button, cancel_button], wrap=True),
                        operation_state,
                        preview_text,
                        authority_text,
                        result_text,
                        audit_text,
                        proposal_state,
                        proposal_evidence,
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Paper account and ledger", "Manual paper actions consume only validated proposal records. The append-only local ledger replays after restart."),
                        paper_account_text,
                        ft.Row([paper_account_id, paper_initial_cash, paper_open_button], wrap=True),
                        ft.Row([paper_proposal_id, paper_execution_price, paper_accept_button, paper_auto_button], wrap=True),
                        ft.Row([paper_reject_reason, paper_reject_button, paper_defer_reason, paper_defer_button], wrap=True),
                        ft.Row([paper_order_id, paper_fill_quantity, paper_fill_price, paper_fill_button], wrap=True),
                        ft.Row([paper_cancel_reason, paper_cancel_button], wrap=True),
                        ft.Row([paper_mark_instrument, paper_mark_price, paper_mark_checksum, paper_mark_button], wrap=True),
                        ft.Row([paper_split_ratio, paper_dividend, paper_action_checksum, paper_action_button], wrap=True),
                        ft.Row([paper_outcome_reference, paper_outcome_benchmark, paper_outcome_cash, paper_outcome_button], wrap=True),
                        ft.Row([paper_incident_code, paper_incident_message, paper_incident_button], wrap=True),
                        ft.Text("Paper marks use adjusted-close evidence and retain source provenance; live broker access, credentials and transmission remain disabled.", color=theme.MUTED, selectable=True),
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


def _paper_summary(item: object | None) -> str:
    if item is None:
        return "Paper account: unavailable · open a local account before paper activity."
    return (
        f"Paper account: {getattr(item, 'status', 'unavailable')} · cash={getattr(item, 'cash', None)} · "
        f"equity={getattr(item, 'equity', None)} · PnL={getattr(item, 'pnl', None)} · "
        f"positions={getattr(item, 'open_positions', 0)} · reconciliation={getattr(item, 'reconciliation_status', 'unavailable')} · "
        f"matured_outcomes={getattr(item, 'matured_outcomes', 0)} · operational_incidents={getattr(item, 'operational_incidents', 0)} · "
        "execution_allowed=false"
    )
