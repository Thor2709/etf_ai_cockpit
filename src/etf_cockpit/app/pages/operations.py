from datetime import datetime, timedelta, timezone
import threading
import uuid

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    KpiStrip,
    KpiStripItem,
    ListRow,
    Note,
    Segmented,
    TableColumn,
    Tag,
    Toggle,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.application.contracts import (
    ApiStatus,
    PageRequest,
    CancelWorkflowCommand,
    EventBlockPolicy,
    ProposalReviewRequest,
    SubmitWorkflowCommand,
    PaperAccountOpenRequest,
    PaperCorporateActionRequest,
    PaperFillRequest,
    PaperOperationalErrorRequest,
    PaperOrderCancelRequest,
    PaperOutcomeMatureRequest,
    PaperPositionMarkRequest,
    PaperProposalAcceptRequest,
    PaperProposalDeferRequest,
    PaperProposalRejectRequest,
)

from etf_cockpit.application.operation_records import OperationRecord, build_operation_preview, load_operation_records, save_operation_record
from etf_cockpit.application.ui_facade import load_paper_tca_view
from etf_cockpit.app.formatting import format_currency, format_number
from collections.abc import Mapping

def _safe_update(page: ft.Page | None) -> None:
    if page is not None and callable(getattr(page, "update", None)):
        page.update()


def _number(field: ft.Control, label: str) -> float:
    value = str(input_of(field).value or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    return float(value)


def _required(field: ft.Control, label: str) -> str:
    value = str(input_of(field).value or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    return value


def _moment(field: ft.Control) -> datetime:
    return datetime.fromisoformat(_required(field, "As of"))


def operations_page(page: ft.Page | None, state: AppState) -> PageView:
    api = state.application_api
    paper = api.get_paper()
    account = paper.items[0] if getattr(paper, "items", None) else None
    operations = api.get_operations()
    portfolio_page = api.get_portfolios(PageRequest())
    portfolio_values = [item.market_value for item in portfolio_page.items]
    next_offset = getattr(portfolio_page, "next_offset", None)
    while next_offset is not None:
        portfolio_page = api.get_portfolios(PageRequest(offset=next_offset, limit=portfolio_page.limit))
        portfolio_values.extend(item.market_value for item in portfolio_page.items)
        next_offset = getattr(portfolio_page, "next_offset", None)
    total_value = sum(portfolio_values) if portfolio_values and all(value is not None for value in portfolio_values) else None
    local_status = {"paper": "Local paper actions are available when their required evidence is supplied."}

    preview_instrument = text_field("Instrument", "operations.instrument", value=str(getattr(state, "selected_etf", "") or ""))
    preview_quantity = text_field("Quantity", "operations.quantity", value="1")
    event_status = ft.Text("Event policy unavailable")

    active_record: OperationRecord | None = None
    busy = False
    event_enabled = {"value": False}

    def change_event_policy(value: bool) -> None:
        nonlocal active_record
        event_enabled["value"] = value
        active_record = None
        confirm_button.disabled = True
        event_status.value = "Event policy changed; create a fresh preview. execution_allowed=false"
        _safe_update(page)

    event_blackout = Toggle(
        on=False,
        on_change=change_event_policy,
        key="operations.event-policy",
    )
    event_policy = Field(
        "Apply local high-risk event blackout (earnings/high-risk; high/critical; ±24 hours)",
        control=event_blackout,
    )
    environment = Field(
        "Environment",
        control=ft.Row(
            [
                Segmented(["Paper proposal"], "Paper proposal"),
                Button.secondary(
                    "Live (disabled)",
                    disabled=True,
                    disabled_reason="Live account access, order submission and broker credentials are unavailable in this build.",
                ),
            ],
            spacing=theme.SPACE_2,
            wrap=True,
        ),
    )
    preview_details = ft.Container(content=Disclosure("preview details", "No operation preview has been stored."))

    def notify(status: ft.Text, details: ft.Container, name: str, action) -> None:
        try:
            result = action()
        except Exception as exc:
            status.value = f"{name} unavailable. Review details."
            details.content = Disclosure(f"{name} details", str(exc))
        else:
            status.value = f"{name}: {result.status}" if name == "Paper account" else f"{name} recorded locally."
            details.content = Disclosure(f"{name} details", str(result))
        if page is not None:
            page.update()

    message = event_status
    operation_state = ft.Text("State: idle")
    preview_text = ft.Text("Preview: none")
    authority_text = ft.Text("Authority: paper preview; execution_allowed=false")
    result_text = ft.Text("Result: none")
    audit_text = ft.Text("Audit: none")
    event_evidence = ft.Text("Event policy disabled; execution_allowed=false")
    proposal_state = ft.Text("Proposal review: not evaluated")
    proposal_evidence = ft.Text("Validated optimiser and portfolio evidence is required.")
    records_body = ft.Column()
    instrument = input_of(preview_instrument)
    quantity = input_of(preview_quantity)
    preview_button = Button.secondary("Preview selected operation", key="operations.preview")
    proposal_button = Button.secondary("Validate proposal review", key="operations.proposal-review")
    confirm_button = Button.primary("Confirm paper workflow", key="operations.confirm", disabled=True, disabled_reason="Create a valid paper preview first.")
    cancel_button = ft.TextButton("Cancel workflow", key="operations.cancel", disabled=True)

    def selected_event_policy() -> EventBlockPolicy | None:
        return EventBlockPolicy(policy_id="local-high-risk-preview", version="1", pre_minutes=1440, post_minutes=1440) if event_enabled["value"] else None

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
        raw_evidence = record.audit.get("event_control", {})
        evidence = raw_evidence if isinstance(raw_evidence, Mapping) else {}
        event_evidence.value = f"Event evidence: {evidence}"

    def refresh_records() -> None:
        records_body.controls = []
        records = load_operation_records()
        if not records:
            records_body.controls.append(ft.Text("No local paper/live operation records yet.", color=theme.MUTED, selectable=True))
        for record in records[:6]:
            raw_audit = record.get("audit", {})
            audit = raw_audit if isinstance(raw_audit, Mapping) else {}
            records_body.controls.append(
                ft.Text(
                    f"{record.get('operation_id')} · {record.get('environment')} · {record.get('status')} · "
                    f"{record.get('instrument_id')} · workflow={audit.get('workflow_id') or 'none'}",
                    color=theme.INK,
                    size=theme.FONT_XS,
                    selectable=True,
                )
            )

    def finish(record: OperationRecord, status: str, text: str, *, workflow_id: str | None = None) -> None:
        nonlocal busy
        if active_record is not None and active_record.operation_id == record.operation_id and active_record.status == "cancelled":
            return
        updated = record.with_update(
            status=status,
            result={"status": status, "message": text},
            audit={**record.audit, "workflow_id": workflow_id or record.audit.get("workflow_id")},
        )
        save_operation_record(updated)
        if active_record is None or active_record.operation_id != record.operation_id:
            refresh_records()
            return
        set_record(updated)
        busy = False
        preview_button.disabled = False
        confirm_button.disabled = True
        cancel_button.disabled = True
        refresh_records()
        _safe_update(page)

    def run_workflow(record: OperationRecord, workflow_id: str) -> None:
        try:
            def runner(_context: object) -> dict[str, object]:
                return {"operation_id": record.operation_id, "execution_allowed": False}

            runner.workflow_id = workflow_id
            result = api.run_next_job(runner)
            if result is None:
                finish(record, "failed", "The paper preview workflow did not claim a job.", workflow_id=workflow_id)
            elif getattr(result, "workflow_id", None) != workflow_id:
                finish(record, "failed", "The paper preview worker claimed an unexpected workflow.", workflow_id=workflow_id)
            else:
                status = str(getattr(result, "status", ""))
                if status == "succeeded":
                    finish(record, "completed", "Paper proposal preview completed; no order was transmitted.", workflow_id=workflow_id)
                elif status == "cancelled":
                    finish(record, "cancelled", "Cancellation recorded; no order was transmitted.", workflow_id=workflow_id)
                else:
                    finish(record, status if status in {"failed", "queued", "running", "blocked"} else "failed", f"Paper preview workflow ended with status {status or 'unknown'}; no order was transmitted.", workflow_id=workflow_id)
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
                    event_policy=selected_event_policy(),
                    rationale="Manual input is shown as review-only until validated optimiser and portfolio evidence is supplied.",
                )
            )
            failed = sum(not item.passed for item in decision.gates)
            alternatives = ", ".join(decision.alternatives)
            gate_summary = ", ".join(f"{item.gate_id}={'passed' if item.passed else 'failed'}" for item in decision.gates)
            proposal_state.value = f"Proposal review: {decision.outcome} · authority={decision.authority_stage} · allowed={str(decision.proposal_allowed).lower()}"
            proposal_evidence.value = f"Proposal evidence: {failed} gate(s) failed; gates={gate_summary}; alternatives={alternatives}; execution_allowed=false. {decision.rationale}"
            event_evidence.value = f"Event evidence: {decision.event_control}"
            message.value = "Proposal review recorded locally. No order or draft-order authority was created."
            _safe_update(page)
        except (OSError, TypeError, ValueError) as exc:
            proposal_state.value = "Proposal review: manual_review"
            proposal_evidence.value = f"Proposal evidence unavailable: {exc}"
            _safe_update(page)

    def preview(_event: ft.ControlEvent) -> None:
        if busy:
            message.value = "Duplicate click ignored: the current operation is already running."
            _safe_update(page)
            return
        try:
            selected_environment = "paper"
            selected_quantity = float(str(quantity.value or "0").replace(",", ""))
            record = build_operation_preview(
                environment=selected_environment,  # type: ignore[arg-type]
                instrument_id=str(instrument.value or ""),
                quantity=selected_quantity,
                event_policy=selected_event_policy(),
                decision_time=datetime.now(timezone.utc) if event_enabled["value"] else None,
            )
            save_operation_record(record)
            set_record(record)
            if not record.authority["submission_allowed"]:
                message.value = f"Operation blocked by policy: {record.authority['reason']} Preview retained locally; no workflow submitted."
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
        if active_record is None or active_record.status != "preview" or active_record.environment != "paper" or not active_record.authority.get("submission_allowed"):
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
    confirm_button.on_click = confirm
    cancel_button.on_click = cancel
    refresh_records()

    paper_equity = GlassCard(
        "Paper equity",
        body=Well(
            EmptyState(
                "Paper equity unavailable",
                "The paper ledger does not provide a dated equity series for a chart.",
            )
        ),
    )
    tca = Well(EmptyState("Paper TCA unavailable", "Paper ledger cost attribution is not available."))

    overview = GlassCard(
        "Preview and confirm",
        note="A preview is stored before any local workflow; live authority remains disabled.",
        body=ft.Column(
            [
                preview_instrument,
                preview_quantity,
                environment,
                event_policy,
                ft.Row(
                    [
                        preview_button, proposal_button, confirm_button, cancel_button,
                    ],
                    wrap=True,
                ),
                operation_state, preview_text, authority_text, result_text, audit_text,
                message, event_evidence, proposal_state, proposal_evidence,
            ],
            spacing=theme.SPACE_2,
        ),
    )

    account_id = text_field("Paper account ID", "operations.paper-account-id")
    opening_cash = text_field("Opening cash (EUR)", "operations.paper-opening-cash")
    account_status = ft.Text("No paper account has been opened from this form.")
    account_details = ft.Container(content=Disclosure("paper account details", "No account action has been recorded."))

    def open_paper_account(_event: ft.ControlEvent | None) -> None:
        notify(
            account_status,
            account_details,
            "Paper account",
            lambda: api.open_paper_account(
                PaperAccountOpenRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    initial_cash=_number(opening_cash, "Opening cash (EUR)"),
                )
            ),
        )

    account_card = GlassCard(
        "Open paper account",
        note="Creates a local paper ledger account; it cannot route orders.",
        body=ft.Column(
            [
                account_id,
                opening_cash,
                Button.secondary("Open local paper account", key="operations.paper-open", on_click=open_paper_account),
                account_status,
                account_details,
                Disclosure("current paper account", str(account) if account is not None else "No paper account is available."),
            ],
            spacing=theme.SPACE_2,
        ),
    )

    proposal_id = text_field("Validated proposal ID", "operations.paper-proposal-id")
    paper_fill_price = text_field("Paper fill price", "operations.paper-fill-price")
    reject_reason = text_field("Reject reason", "operations.paper-reject-reason", multiline=True)
    defer_reason = text_field("Defer reason", "operations.paper-defer-reason", multiline=True)
    decision_status = ft.Text(local_status["paper"])
    decision_details = ft.Container(content=Disclosure("proposal decision details", "No proposal action has been recorded."))

    def _accept_paper_proposal(mode: str) -> None:
        title = "Paper proposal accepted" if mode == "manual_accept" else "Auto-paper decision"
        notify(
            decision_status,
            decision_details,
            title,
            lambda: api.accept_paper_proposal(
                PaperProposalAcceptRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    proposal_id=_required(proposal_id, "Validated proposal ID"),
                    execution_price=_number(paper_fill_price, "Paper fill price"),
                    mode=mode,
                )
            ),
        )

    def accept_paper_proposal(_event: ft.ControlEvent | None) -> None:
        _accept_paper_proposal("manual_accept")

    def auto_paper_proposal(_event: ft.ControlEvent | None) -> None:
        _accept_paper_proposal("auto_paper")

    def reject_paper_proposal(_event: ft.ControlEvent | None) -> None:
        notify(
            decision_status,
            decision_details,
            "Proposal rejection",
            lambda: api.reject_paper_proposal(
                PaperProposalRejectRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    proposal_id=_required(proposal_id, "Validated proposal ID"),
                    reason=_required(reject_reason, "Reject reason"),
                )
            ),
        )

    def defer_paper_proposal(_event: ft.ControlEvent | None) -> None:
        notify(
            decision_status,
            decision_details,
            "Proposal deferral",
            lambda: api.defer_paper_proposal(
                PaperProposalDeferRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    proposal_id=_required(proposal_id, "Validated proposal ID"),
                    reason=_required(defer_reason, "Defer reason"),
                )
            ),
        )

    proposal_decisions_card = GlassCard(
        "Proposal decisions",
        note="Paper accepts require an existing reviewed proposal.",
        body=ft.Column(
            [
                proposal_id,
                paper_fill_price,
                ft.Row(
                    [
                        Button.secondary(
                            "Accept to paper",
                            key="operations.paper-accept",
                            on_click=accept_paper_proposal,
                        ),
                        Button.secondary(
                            "Auto-paper (local)",
                            key="operations.paper-auto",
                            on_click=auto_paper_proposal,
                        ),
                    ],
                    wrap=True,
                ),
                reject_reason,
                Button.secondary("Reject proposal", key="operations.paper-reject", on_click=reject_paper_proposal),
                defer_reason,
                Button.secondary("Defer proposal", key="operations.paper-defer", on_click=defer_paper_proposal),
                decision_status,
                decision_details,
            ],
            spacing=theme.SPACE_2,
        ),
    )

    order_id = text_field("Paper order ID", "operations.paper-order-id")
    fill_quantity = text_field("Fill quantity", "operations.paper-fill-quantity")
    fill_price = text_field("Fill price", "operations.paper-fill-price")
    order_cancel_reason = text_field("Cancel reason", "operations.paper-order-cancel-reason", multiline=True)
    fill_status = ft.Text("Paper fills are unavailable until a paper order is selected.")
    fill_details = ft.Container(content=Disclosure("paper fill details", "No paper order action has been recorded."))

    fill_intent: dict[str, str] = {}

    def fill_paper_order(_event: ft.ControlEvent | None) -> None:
        intent_id = fill_intent.setdefault("id", "fill_" + uuid.uuid4().hex[:20])
        notify(
            fill_status,
            fill_details,
            "Paper fill",
            lambda: api.fill_paper_order(
                PaperFillRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    order_id=_required(order_id, "Paper order ID"),
                    fill_id=intent_id,
                    quantity=_number(fill_quantity, "Fill quantity"),
                    price=_number(fill_price, "Fill price"),
                )
            ),
        )

        if fill_status.value == "Paper fill recorded locally.":
            fill_intent.clear()

    def cancel_paper_order(_event: ft.ControlEvent | None) -> None:
        notify(
            fill_status,
            fill_details,
            "Paper order cancellation",
            lambda: api.cancel_paper_order(
                PaperOrderCancelRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    order_id=_required(order_id, "Paper order ID"),
                    reason=_required(order_cancel_reason, "Cancel reason"),
                )
            ),
        )

    fills_card = GlassCard(
        "Fills",
        note="Fills and cancellations update the local paper ledger only.",
        body=ft.Column(
            [
                order_id,
                fill_quantity,
                fill_price,
                Button.secondary("Record fill", key="operations.paper-fill", on_click=fill_paper_order),
                order_cancel_reason,
                Button.secondary(
                    "Cancel paper order", key="operations.paper-order-cancel", on_click=cancel_paper_order
                ),
                fill_status,
                fill_details,
            ],
            spacing=theme.SPACE_2,
        ),
    )

    mark_instrument = text_field("Mark instrument", "operations.paper-mark-instrument")
    adjusted_close = text_field("Adjusted-close mark", "operations.paper-adjusted-close")
    mark_as_of = text_field("Mark as of (ISO date/time)", "operations.paper-mark-as-of")
    mark_authority = text_field("Mark source authority", "operations.paper-mark-authority")
    mark_checksum = text_field("Mark source checksum", "operations.paper-mark-checksum")
    input_of(mark_checksum).password = True
    input_of(mark_checksum).can_reveal_password = False
    mark_status = ft.Text("Adjusted-close mark unavailable until source evidence is supplied.")
    mark_details = ft.Container(content=Disclosure("mark details", "No mark has been recorded."))

    def mark_paper_position(_event: ft.ControlEvent | None) -> None:
        notify(
            mark_status,
            mark_details,
            "Adjusted-close mark",
            lambda: api.mark_paper_position(
                PaperPositionMarkRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    instrument_id=_required(mark_instrument, "Mark instrument"),
                    adjusted_close=_number(adjusted_close, "Adjusted-close mark"),
                    as_of=_moment(mark_as_of),
                    source_authority=_required(mark_authority, "Mark source authority"),
                    source_checksum=_required(mark_checksum, "Mark source checksum"),
                )
            ),
        )

    action_instrument = text_field("Action instrument", "operations.paper-action-instrument")
    split_ratio = text_field("Split ratio", "operations.paper-split-ratio")
    dividend = text_field("Dividend/unit", "operations.paper-dividend-per-unit")
    action_as_of = text_field("Action as of (ISO date/time)", "operations.paper-action-as-of")
    action_authority = text_field("Action source authority", "operations.paper-action-authority")
    action_checksum = text_field("Action source checksum", "operations.paper-action-checksum")
    input_of(action_checksum).password = True
    input_of(action_checksum).can_reveal_password = False
    action_status = ft.Text("Corporate action unavailable until source evidence is supplied.")
    action_details = ft.Container(content=Disclosure("corporate action details", "No corporate action has been recorded."))

    def apply_paper_corporate_action(_event: ft.ControlEvent | None) -> None:
        notify(
            action_status,
            action_details,
            "Corporate action",
            lambda: api.apply_paper_corporate_action(
                PaperCorporateActionRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    instrument_id=_required(action_instrument, "Action instrument"),
                    split_ratio=_number(split_ratio, "Split ratio"),
                    cash_dividend_per_unit=_number(dividend, "Dividend/unit"),
                    as_of=_moment(action_as_of),
                    source_authority=_required(action_authority, "Action source authority"),
                    source_checksum=_required(action_checksum, "Action source checksum"),
                )
            ),
        )

    marks_card = GlassCard(
        "Marks and corporate actions",
        note="Marks and actions require dated adjusted-price evidence and its source.",
        body=ft.Column(
            [
                mark_instrument,
                adjusted_close,
                mark_as_of,
                mark_authority,
                mark_checksum,
                Button.secondary(
                    "Record adjusted-close mark", key="operations.paper-mark", on_click=mark_paper_position
                ),
                mark_status,
                mark_details,
                action_instrument,
                split_ratio,
                dividend,
                action_as_of,
                action_authority,
                action_checksum,
                Button.secondary(
                    "Apply corporate action",
                    key="operations.paper-corporate-action",
                    on_click=apply_paper_corporate_action,
                ),
                action_status,
                action_details,
            ],
            spacing=theme.SPACE_2,
        ),
    )

    outcome_reference = text_field("Outcome order/proposal ID", "operations.paper-outcome-reference")
    outcome_adjusted_close = text_field("Outcome adjusted-close price", "operations.paper-outcome-price")
    benchmark_return = text_field("Benchmark return", "operations.paper-benchmark-return")
    cash_return = text_field("Cash return", "operations.paper-cash-return")
    horizon = text_field("Outcome horizon days", "operations.paper-outcome-horizon")
    outcome_as_of = text_field("Outcome as of (ISO date/time)", "operations.paper-outcome-as-of")
    outcome_authority = text_field("Outcome source authority", "operations.paper-outcome-authority")
    outcome_checksum = text_field("Outcome source checksum", "operations.paper-outcome-checksum")
    input_of(outcome_checksum).password = True
    input_of(outcome_checksum).can_reveal_password = False
    outcome_status = ft.Text("Mature outcome unavailable until dated source evidence is supplied.")
    outcome_details = ft.Container(content=Disclosure("outcome details", "No outcome has been matured."))

    def mature_paper_outcome(_event: ft.ControlEvent | None) -> None:
        notify(
            outcome_status,
            outcome_details,
            "Paper outcome",
            lambda: api.mature_paper_outcome(
                PaperOutcomeMatureRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    reference_id=_required(outcome_reference, "Outcome order/proposal ID"),
                    adjusted_close=_number(outcome_adjusted_close, "Outcome adjusted-close price"),
                    benchmark_return=_number(benchmark_return, "Benchmark return"),
                    cash_return=_number(cash_return, "Cash return"),
                    horizon_days=int(_number(horizon, "Outcome horizon days")),
                    as_of=_moment(outcome_as_of),
                    source_authority=_required(outcome_authority, "Outcome source authority"),
                    source_checksum=_required(outcome_checksum, "Outcome source checksum"),
                )
            ),
        )

    outcomes_card = GlassCard(
        "Outcomes",
        note="Matured outcomes use the paper ledger's adjusted-close basis.",
        body=ft.Column(
            [
                outcome_reference,
                outcome_adjusted_close,
                benchmark_return,
                cash_return,
                horizon,
                outcome_as_of,
                outcome_authority,
                outcome_checksum,
                Button.secondary("Mature outcome", key="operations.paper-outcome", on_click=mature_paper_outcome),
                outcome_status,
                outcome_details,
            ],
            spacing=theme.SPACE_2,
        ),
    )

    incident_code = text_field("Incident code", "operations.paper-incident-code")
    incident_message = text_field("Operational incident", "operations.paper-incident-message", multiline=True)
    incident_related = text_field("Related paper record ID", "operations.paper-incident-related-id")
    incident_status = ft.Text("No operational incident has been recorded.")
    incident_details = ft.Container(content=Disclosure("incident details", "No incident has been recorded."))

    def record_paper_incident(_event: ft.ControlEvent | None) -> None:
        notify(
            incident_status,
            incident_details,
            "Operational incident",
            lambda: api.record_paper_operational_error(
                PaperOperationalErrorRequest(
                    account_id=_required(account_id, "Paper account ID"),
                    code=_required(incident_code, "Incident code"),
                    message=_required(incident_message, "Operational incident"),
                    related_id=str(input_of(incident_related).value or "").strip() or None,
                )
            ),
        )

    incidents_card = GlassCard(
        "Incidents",
        note="Incident details are recorded in the local paper ledger.",
        body=ft.Column(
            [
                incident_code,
                incident_message,
                incident_related,
                Button.secondary("Record incident", key="operations.paper-incident", on_click=record_paper_incident),
                incident_status,
                incident_details,
            ],
            spacing=theme.SPACE_2,
        ),
    )

    record_rows = []
    for item in getattr(operations, "items", ()):
        record_rows.append(
            {
                "time": getattr(item, "occurred_at", None) or "—",
                "operation": "Local paper operation",
                "result": Tag("Recorded", "ok"),
                "details": Disclosure(
                    "operation record",
                    f"ID: {getattr(item, 'operation_id', '—')}\r\n"
                    f"Status: {getattr(item, 'status', 'unavailable')}\r\n"
                    f"Message: {getattr(item, 'message', '—')}",
                ),
            }
        )
    records_card = GlassCard(
        "Recent operation records",
        note="Operation identifiers, statuses and messages are available in each disclosure.",
        body=Well(
            DataTable(
                [
                    TableColumn("time", "Time"),
                    TableColumn("operation", "Operation"),
                    TableColumn("result", "Result"),
                    TableColumn("details", "Details"),
                ],
                record_rows,
                empty_title="Unavailable",
                empty_reason="No local operation records are available.",
            )
        ),
    )

    def navigate_to_training(_event: ft.ControlEvent | None) -> None:
        if page is not None:
            page.go("/training-centre")

    environments = GlassCard(
        "Environments",
        note="Environment authority is constrained to local paper simulation.",
        body=ft.Column(
            [
                ListRow(
                    "info",
                    "Paper environment",
                    "Paper proposal previews may start a local durable workflow. They never transmit an order.",
                    tag=("proposal only", "ok"),
                ),
                ListRow(
                    "bad",
                    "Live environment: disabled",
                    "Live access and order transmission are unavailable.",
                    tag=("disabled", "bad"),
                ),
                ListRow(
                    "info",
                    "Training",
                    "Training Centre is available.",
                    on_click=navigate_to_training,
                    key="navigation.training-centre",
                ),
            ],
            spacing=theme.SPACE_2,
        ),
    )

    kpis = KpiStrip(
        "Live authority",
        "Disabled",
        "No credentials or order route",
        [
            KpiStripItem("Portfolio context", format_currency(total_value, unavailable="Unavailable"), "Local holdings only"),
            KpiStripItem(
                "Paper account",
                "Unavailable" if account is None else "Local paper account",
                "No paper account is available." if account is None else "Reconciliation is required before submission.",
            ),
            KpiStripItem("Paper environment", "Proposal only", "Local evidence"),
            KpiStripItem("Operations", "Unavailable", "No operation result is available."),
        ],
    )

    views = {
        "Overview": [kpis, overview, paper_equity, environments, GlassCard("Post-trade TCA", body=tca)],
        "Paper ledger": [account_card, proposal_decisions_card, fills_card, marks_card, outcomes_card, incidents_card],
        "Records": [records_card, records_body, Note("Paper ledger records are local and non-executable.")],
    }
    selected = {"view": "Overview"}
    body = page_body([])

    def render() -> None:
        body.controls = views[selected["view"]]
        if page is not None:
            page.update()

    def select_view(value: str) -> None:
        selected["view"] = value
        render()

    render()
    return PageView(
        chrome=PageChrome(
            "Operations Centre",
            "Proposals and local paper simulation · live trading disabled in this build",
            [SegmentGroup("operations", ["Overview", "Paper ledger", "Records"], "Overview", select_view)],
        ),
        body=body,
    )


__all__ = ["operations_page"]
