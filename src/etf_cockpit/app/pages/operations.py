from datetime import datetime

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
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
    local_status = {"paper": "Local paper actions are available when their required evidence is supplied."}

    preview_instrument = text_field("Instrument", "operations.instrument")
    preview_quantity = text_field("Quantity", "operations.quantity")
    event_blackout = Toggle(
        on=False,
        disabled=True,
        disabled_reason="Event policy details are unavailable in this build.",
    )
    event_blackout.key = "operations.event-policy"
    event_status = ft.Text("Event policy unavailable")
    preview_details = ft.Container(content=Disclosure("preview details", "No operation preview has been stored."))

    def notify(status: ft.Text, details: ft.Container, name: str, action) -> None:
        try:
            result = action()
        except Exception as exc:
            status.value = f"{name} unavailable. Review details."
            details.content = Disclosure(f"{name} details", str(exc))
        else:
            status.value = f"{name} recorded locally."
            details.content = Disclosure(f"{name} details", str(result))
        if page is not None:
            page.update()

    def preview(_event: ft.ControlEvent | None) -> None:
        def store_preview():
            from etf_cockpit.application.operation_records import build_operation_preview, save_operation_record

            record = build_operation_preview(
                environment="paper",
                instrument_id=_required(preview_instrument, "Instrument"),
                quantity=_number(preview_quantity, "Quantity"),
            )
            save_operation_record(record)
            return record

        notify(event_status, preview_details, "Operation preview", store_preview)

    def change_event_policy(_value: bool) -> None:
        event_status.value = "Event policy unavailable in this build."
        if page is not None:
            page.update()

    event_blackout.on_change = change_event_policy
    proposal_status = ft.Text("Proposal review unavailable: current authority and optimiser evidence is not available here.")
    proposal_details = ft.Container(
        content=Disclosure("proposal review details", "No validated proposal review is available.")
    )
    cancel_status = ft.Text("No active workflow is available to cancel.")
    cancel_details = ft.Container(content=Disclosure("workflow details", "No active workflow is available."))

    def proposal_review(_event: ft.ControlEvent | None) -> None:
        def unavailable() -> None:
            raise ValueError("Required authority and optimiser evidence is unavailable.")

        notify(proposal_status, proposal_details, "Proposal review", unavailable)

    def confirm(_event: ft.ControlEvent | None) -> None:
        proposal_status.value = "Confirmation is unavailable until a reviewed proposal exists."
        if page is not None:
            page.update()

    def cancel(_event: ft.ControlEvent | None) -> None:
        def unavailable() -> None:
            raise ValueError("No active workflow is available.")

        notify(cancel_status, cancel_details, "Workflow cancellation", unavailable)

    paper_equity = Well(
        EmptyState(
            "Paper equity unavailable",
            "The paper ledger does not provide a dated equity series for a chart.",
        )
    )
    tca = Well(EmptyState("Paper TCA unavailable", "Paper ledger cost attribution is not available."))

    overview = GlassCard(
        "Preview and confirm",
        note="Every preview remains non-executable; live authority is disabled.",
        body=ft.Column(
            [
                preview_instrument,
                preview_quantity,
                Segmented(["Paper proposal"], "Paper proposal"),
                ft.Row([Tag("Live environment disabled", "bad"), event_blackout], wrap=True),
                ft.Row(
                    [
                        Button.secondary("Preview selected operation", key="operations.preview", on_click=preview),
                        Button.secondary(
                            "Validate proposal review",
                            key="operations.proposal-review",
                            on_click=proposal_review,
                        ),
                        Button.primary(
                            "Confirm paper workflow",
                            key="operations.confirm",
                            on_click=confirm,
                            disabled=True,
                            disabled_reason="Confirmation remains disabled until a reviewed paper proposal exists.",
                        ),
                        Button.secondary(
                            "Cancel workflow",
                            key="operations.cancel",
                            on_click=cancel,
                        ),
                    ],
                    wrap=True,
                ),
                ft.Column(
                    [
                        ListRow("info", "State", "Paper proposal preview"),
                        ListRow("info", "Preview", "Unavailable until a preview is stored."),
                        ListRow("info", "Authority", "Paper proposal only · live disabled"),
                        ListRow("info", "Result", "Unavailable until a review is available."),
                        ListRow("info", "Audit", "Unavailable until a preview is stored."),
                        ListRow("info", "Proposal review", "Unavailable · authority evidence is missing"),
                        ListRow("info", "Event policy", "Unavailable · policy details are missing"),
                    ],
                    spacing=theme.SPACE_1,
                ),
                event_status,
                preview_details,
                proposal_status,
                proposal_details,
                cancel_status,
                cancel_details,
            ],
            spacing=theme.SPACE_2,
        ),
    )

    account_id = text_field("Paper account ID", "operations.paper-account-id", value="local-paper")
    opening_cash = text_field("Opening cash EUR", "operations.paper-opening-cash")
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
                    initial_cash=_number(opening_cash, "Opening cash EUR"),
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

    def fill_paper_order(_event: ft.ControlEvent | None) -> None:
        notify(
            fill_status,
            fill_details,
            "Paper fill",
            lambda: api.fill_paper_order(
                PaperFillRequest(
                    order_id=_required(order_id, "Paper order ID"),
                    quantity=_number(fill_quantity, "Fill quantity"),
                    price=_number(fill_price, "Fill price"),
                )
            ),
        )

    def cancel_paper_order(_event: ft.ControlEvent | None) -> None:
        notify(
            fill_status,
            fill_details,
            "Paper order cancellation",
            lambda: api.cancel_paper_order(
                PaperOrderCancelRequest(
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
    dividend = text_field("Dividend per unit", "operations.paper-dividend-per-unit")
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
                    instrument_id=_required(action_instrument, "Action instrument"),
                    split_ratio=_number(split_ratio, "Split ratio"),
                    cash_dividend_per_unit=_number(dividend, "Dividend per unit"),
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
                    f"ID: {getattr(item, 'operation_id', '—')}\n"
                    f"Status: {getattr(item, 'status', 'unavailable')}\n"
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
                ListRow("info", "Training", "Training Centre is available."),
            ],
            spacing=theme.SPACE_2,
        ),
    )

    kpis = KpiStrip(
        "Live authority",
        "Disabled",
        "No credentials or order route",
        [
            KpiStripItem("Portfolio context", "Unavailable", "Portfolio execution context is not available."),
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
        "Records": [records_card, Note("Paper ledger records are local and non-executable.")],
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
