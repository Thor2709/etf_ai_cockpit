from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import Button, EmptyState, GlassCard, KpiStrip, KpiStripItem, ListRow, Note, Segmented, Tag, Toggle
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._l4a_common import page_body, text_field
from etf_cockpit.app.state import AppState


def operations_page(page: ft.Page | None, state: AppState) -> PageView:
    paper = state.application_api.get_paper()
    account = paper.items[0] if getattr(paper, "items", None) else None
    instrument = text_field("Instrument", "operations.instrument")
    quantity = text_field("Quantity", "operations.quantity")
    event_blackout = Toggle(
        on=False,
        disabled=True,
        disabled_reason="Event policy details are unavailable in this build.",
    )
    status_values = [
        ListRow("info", "State", "Unavailable until an operation is previewed."),
        ListRow("info", "Preview", "Unavailable until an operation is previewed."),
        ListRow("info", "Authority", "Paper proposal only · live disabled"),
        ListRow("info", "Result", "Unavailable until local validation completes."),
        ListRow("info", "Audit", "Unavailable until an operation is previewed."),
        ListRow("info", "Proposal review", "Not evaluated"),
        ListRow("info", "Event policy", "Unavailable"),
    ]
    action_status = ft.Text("Paper and live operations remain unavailable until local evidence is ready.")

    def change_event_policy(_value: bool) -> None:
        action_status.value = "Event policy unavailable in the current snapshot."

    def preview(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Preview unavailable: current operation inputs are incomplete."

    def proposal_review(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Proposal review unavailable: validated optimiser evidence is required."

    def confirm(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper workflow unavailable until proposal validation is complete."

    def cancel(_event: ft.ControlEvent | None) -> None:
        action_status.value = "No active local workflow is available to cancel."

    def open_paper_account(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper account unavailable: local account inputs are required."

    def accept_paper_proposal(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper proposal unavailable: proposal review is required."

    def auto_paper_proposal(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Auto-paper unavailable: local proposal evidence is required."

    def reject_paper_proposal(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper proposal unavailable: no reviewed proposal is selected."

    def defer_paper_proposal(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper proposal unavailable: no reviewed proposal is selected."

    def fill_paper_order(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper fill unavailable: no paper order is selected."

    def cancel_paper_order(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper order unavailable: no paper order is selected."

    def mark_paper_position(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper mark unavailable: adjusted-close evidence is required."

    def apply_paper_corporate_action(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Corporate action unavailable: source evidence is required."

    def mature_paper_outcome(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Paper outcome unavailable: a mature outcome record is required."

    def record_paper_incident(_event: ft.ControlEvent | None) -> None:
        action_status.value = "Operational incident unavailable: an incident record is required."

    event_blackout.on_change = change_event_policy
    event_blackout.key = "operations.event-policy"
    paper_equity = (
        EmptyState("No paper ledger", "Paper ledger is missing; no fills or costs are inferred.")
        if account is None or getattr(account, "equity", None) is None
        else EmptyState("Paper equity unavailable", "The current paper account has no dated equity series.")
    )
    tca = EmptyState("Paper TCA unavailable", "Paper ledger cost attribution is not available.")
    overview = GlassCard(
        "Preview and confirm",
        note="a preview is stored before any local workflow",
        body=ft.Column(
            [
                instrument,
                quantity,
                Segmented(["Paper proposal"], "Paper proposal"),
                ft.Row([Tag("Live environment disabled", "bad"), event_blackout], wrap=True),
                ft.Row(
                    [
                        Button.secondary("Preview selected operation", key="operations.preview", on_click=preview),
                        Button.secondary("Validate proposal review", key="operations.proposal-review", on_click=proposal_review),
                        Button.primary(
                            "Confirm paper workflow",
                            key="operations.confirm",
                            on_click=confirm,
                            disabled=True,
                            disabled_reason="Confirmation remains disabled until local proposal validation is ready.",
                        ),
                        Button.secondary("Cancel workflow", key="operations.cancel", on_click=cancel),
                    ],
                    wrap=True,
                ),
                ft.Column(status_values, spacing=theme.SPACE_1),
                action_status,
            ],
            spacing=theme.SPACE_2,
        ),
    )
    cards = [
        GlassCard("Live authority: Disabled", body=Note("No credentials or order route")),
        overview,
        GlassCard("Paper equity", body=paper_equity),
        GlassCard(
            "Paper ledger",
            body=ft.Column(
                [
                    Button.secondary("Open local paper account", key="operations.paper-open", on_click=open_paper_account),
                    Button.secondary("Accept to paper", key="operations.paper-accept", on_click=accept_paper_proposal),
                    Button.secondary("Auto-paper (local)", key="operations.paper-auto", on_click=auto_paper_proposal),
                    Button.secondary("Reject proposal", key="operations.paper-reject", on_click=reject_paper_proposal),
                    Button.secondary("Defer proposal", key="operations.paper-defer", on_click=defer_paper_proposal),
                    Button.secondary("Record fill", key="operations.paper-fill", on_click=fill_paper_order),
                    Button.secondary("Cancel paper order", key="operations.paper-order-cancel", on_click=cancel_paper_order),
                    Button.secondary("Record adjusted-close mark", key="operations.paper-mark", on_click=mark_paper_position),
                    Button.secondary("Apply corporate action", key="operations.paper-corporate-action", on_click=apply_paper_corporate_action),
                    Button.secondary("Mature outcome", key="operations.paper-outcome", on_click=mature_paper_outcome),
                    Button.secondary("Record incident", key="operations.paper-incident", on_click=record_paper_incident),
                ],
                spacing=theme.SPACE_2,
            ),
        ),
        GlassCard(
            "Environments",
            body=ft.Column(
                [
                    ListRow("info", "Paper environment", "Paper proposal previews may start a local durable workflow. They never transmit an order.", tag=("proposal only", "ok")),
                    ListRow("bad", "Live environment: disabled", "Live access and order transmission are unavailable.", tag=("disabled", "bad")),
                    ListRow("info", "Training", "Training Centre", tag=("available", "mute")),
                ],
                spacing=theme.SPACE_2,
            ),
        ),
        GlassCard("Post-trade TCA", body=tca),
    ]
    header = KpiStrip(
        "Live authority",
        "Disabled",
        "No credentials or order route",
        [
            KpiStripItem("Portfolio context", None, "Unavailable"),
            KpiStripItem("Paper account", getattr(account, "status", None) if account else None, "Reconciliation must be ready before submission"),
            KpiStripItem("Paper environment", "proposal only", "Local evidence"),
            KpiStripItem("Operations", None, "Unavailable"),
        ],
    )
    body = page_body([header, *cards])
    return PageView(
        chrome=PageChrome(
            "Operations Centre",
            "Proposals and local paper simulation · live trading disabled in this build",
            [SegmentGroup("operations", ["Overview", "Paper ledger", "Records"], "Overview")],
        ),
        body=body,
    )


__all__ = ["operations_page"]
