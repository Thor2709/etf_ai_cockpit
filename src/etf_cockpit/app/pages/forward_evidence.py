"""Local forward-evidence diary and paper-proposal evidence surface."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import (
    Button,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    KpiTile,
    ListRow,
    Note,
    Segmented,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_timestamp
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import ForwardEvidenceDiary, ForwardEvidenceObservation, ForwardInputManifest
from etf_cockpit.core.paths import DATA_DIR


_PROPOSAL_OUTCOMES = {
    "Not proposed": "not_proposed",
    "Observation only": "observation_only",
    "Paper proposed": "paper_proposed",
    "Paper accepted": "paper_accepted",
    "Paper rejected": "paper_rejected",
    "Cancelled": "cancelled",
    "Expired": "expired",
}
_OUTCOME_STATUSES = {
    "Available": "available",
    "Unavailable": "unavailable",
    "Stale": "stale",
    "Conflicted": "conflicted",
}
_STATUS_LABELS = {
    "pending": ("Pending", "mute"),
    "available": ("Available", "ok"),
    "unavailable": ("Unavailable", "bad"),
    "stale": ("Stale", "warn"),
    "conflicted": ("Conflicted", "warn"),
}


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def _timestamp(value: str | None, label: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def forward_evidence_page(page: ft.Page | None, state: AppState) -> PageView:
    diary = ForwardEvidenceDiary()
    fields = {
        "observation_id": text_field("Observation ID", "forward-evidence.observation-id"),
        "instrument_ids": text_field("Instrument IDs (comma-separated)", "forward-evidence.instrument-ids"),
        "decision_as_of": text_field("Decision as-of (ISO 8601 with timezone)", "forward-evidence.as-of"),
        "decision": text_field("Decision", "forward-evidence.decision"),
        "proposal_id": text_field("Proposal ID (optional)", "forward-evidence.proposal-id"),
        "paper_order_ids": text_field("Paper order IDs (comma-separated)", "forward-evidence.paper-order-ids"),
        "rationale": text_field("Rationale / limitations", "forward-evidence.rationale", multiline=True),
        "data_hash": text_field("Data hash", "forward-evidence.data-hash"),
        "formula_hash": text_field("Formula hash", "forward-evidence.formula-hash"),
        "model_hash": text_field("Model hash", "forward-evidence.model-hash"),
        "portfolio_hash": text_field("Portfolio hash", "forward-evidence.portfolio-hash"),
        "policy_hash": text_field("Policy hash", "forward-evidence.policy-hash"),
        "proposal_hash": text_field("Proposal hash", "forward-evidence.proposal-hash"),
        "source_authority": text_field("Decision source authority", "forward-evidence.source-authority"),
        "source_checksum": text_field("Decision source checksum", "forward-evidence.source-checksum"),
        "update_id": text_field("Observation ID to update", "forward-evidence.update-id"),
        "outcome_as_of": text_field("Outcome as-of", "forward-evidence.outcome-as-of"),
        "outcome_authority": text_field("Outcome source authority", "forward-evidence.outcome-authority"),
        "outcome_checksum": text_field("Outcome source checksum", "forward-evidence.outcome-checksum"),
        "metrics": text_field("Outcome metrics (JSON object)", "forward-evidence.metrics", multiline=True),
        "outcome_notes": text_field("Outcome notes", "forward-evidence.outcome-notes", multiline=True),
    }
    proposal_outcome = {"value": "observation_only"}
    outcome_status = {"value": "available"}
    selected_view = {"value": "Record"}
    status_note = Note("No external or broker action is available; execution_allowed=false.")
    entries: list[object] = []
    outcomes_well = Well(EmptyState("No observations yet", "Record a local observation opportunity to begin."))
    recent_host = ft.Column(spacing=theme.SPACE_2)

    def _render_recent() -> None:
        statuses = [str(row.outcome.status).casefold() for row in entries]
        if statuses:
            other = len(statuses) - statuses.count("available") - statuses.count("pending")
            outcomes_well.content = ft.Column(
                [
                    ft.Row(
                        [
                            KpiTile("Matured", format_count(statuses.count("available"), unavailable="—"), sub="Outcome available"),
                            KpiTile("Pending", format_count(statuses.count("pending"), unavailable="—"), sub="Horizon not yet matured"),
                        ],
                        spacing=theme.SPACE_2,
                        wrap=True,
                    ),
                    Note(f"Stale, unavailable or conflicted: {format_count(other, unavailable='—')}"),
                ],
                spacing=theme.SPACE_2,
            )
        else:
            outcomes_well.content = EmptyState("No observations yet", "Record a local observation opportunity to begin.")
        recent_rows = []
        for row in entries[-12:]:
            status_key = str(row.outcome.status).casefold()
            label, kind = _STATUS_LABELS.get(status_key, ("Unavailable", "bad"))
            recent_rows.append(
                ListRow(
                    "info" if status_key in {"pending", "available"} else "warn" if status_key == "stale" else "bad",
                    row.observation.observation_id,
                    f"{format_timestamp(row.observation.manifest.as_of, unavailable='—')} · {label}",
                    tag=(label, kind),
                )
            )
        recent_host.controls = recent_rows or [Well(EmptyState("No diary entries yet", "Recorded local observations will appear here."))]

    def refresh() -> None:
        try:
            entries[:] = diary.list_entries(root=DATA_DIR)
        except Exception:
            entries.clear()
        _render_recent()

    def show(message: str) -> None:
        status_note.value = message
        if page is not None:
            page.update()

    def record_observation(_event: ft.ControlEvent | None) -> None:
        try:
            manifest = ForwardInputManifest.create(
                as_of=_timestamp(input_of(fields["decision_as_of"]).value, "decision as-of"),
                data_hash=input_of(fields["data_hash"]).value or "",
                formula_hash=input_of(fields["formula_hash"]).value or "",
                model_hash=input_of(fields["model_hash"]).value or "",
                portfolio_hash=input_of(fields["portfolio_hash"]).value or "",
                policy_hash=input_of(fields["policy_hash"]).value or "",
                proposal_hash=input_of(fields["proposal_hash"]).value or "",
                source_authority=input_of(fields["source_authority"]).value or "",
                source_checksum=input_of(fields["source_checksum"]).value or "",
            )
            diary.record_observation(
                ForwardEvidenceObservation(
                    observation_id=input_of(fields["observation_id"]).value or "",
                    created_at=datetime.now(timezone.utc),
                    instrument_ids=_split(input_of(fields["instrument_ids"]).value),
                    manifest=manifest,
                    proposal_outcome=proposal_outcome["value"],
                    proposal_id=(input_of(fields["proposal_id"]).value or "").strip() or None,
                    paper_order_ids=_split(input_of(fields["paper_order_ids"]).value),
                    decision=input_of(fields["decision"]).value or "",
                    rationale=input_of(fields["rationale"]).value or "",
                ),
                root=DATA_DIR,
            )
            refresh()
            show("Observation recorded locally with its decision-time manifest.")
        except Exception as exc:
            show(f"Error: observation was not recorded ({type(exc).__name__}: {exc}). No external action was created.")

    def update_outcome(_event: ft.ControlEvent | None) -> None:
        try:
            metric_value = json.loads(input_of(fields["metrics"]).value or "{}")
            if not isinstance(metric_value, dict):
                raise ValueError
            diary.update_outcome(
                input_of(fields["update_id"]).value or "",
                status=outcome_status["value"],
                outcome_as_of=_timestamp(input_of(fields["outcome_as_of"]).value, "outcome as-of"),
                source_authority=input_of(fields["outcome_authority"]).value or "",
                source_checksum=input_of(fields["outcome_checksum"]).value or "",
                metrics=metric_value,
                notes=input_of(fields["outcome_notes"]).value or "",
                root=DATA_DIR,
            )
            refresh()
            show("Mature outcome recorded locally; prior records remain immutable.")
        except Exception as exc:
            show(f"Error: outcome was not recorded ({type(exc).__name__}: {exc}). The prior outcome remains unchanged.")

    proposal_field = Field(
        "Proposal outcome",
        options=list(_PROPOSAL_OUTCOMES),
        value="Observation only",
        on_change=lambda label: proposal_outcome.update(value=_PROPOSAL_OUTCOMES[label]),
    )
    outcome_segment = Segmented(
        list(_OUTCOME_STATUSES),
        "Available",
        on_change=lambda label: outcome_status.update(value=_OUTCOME_STATUSES[label]),
    )
    record_form = ft.Column(
        [
            fields["observation_id"],
            fields["instrument_ids"],
            fields["decision_as_of"],
            fields["decision"],
            proposal_field,
            fields["proposal_id"],
            fields["paper_order_ids"],
            fields["rationale"],
            Disclosure(
                "hashes and sources",
                ft.Column(
                    [
                        fields[name]
                        for name in (
                            "data_hash",
                            "formula_hash",
                            "model_hash",
                            "portfolio_hash",
                            "policy_hash",
                            "proposal_hash",
                            "source_authority",
                            "source_checksum",
                        )
                    ],
                    spacing=theme.SPACE_2,
                ),
            ),
            Button.primary("Record observation", key="forward-evidence.record", on_click=record_observation),
            status_note,
        ],
        spacing=theme.SPACE_2,
    )
    mature_form = ft.Column(
        [
            fields["update_id"],
            ft.Column([Note("Outcome status"), outcome_segment], spacing=theme.SPACE_1),
            fields["outcome_as_of"],
            Disclosure(
                "outcome sources",
                ft.Column(
                    [fields["outcome_authority"], fields["outcome_checksum"], fields["metrics"]],
                    spacing=theme.SPACE_2,
                ),
            ),
            fields["outcome_notes"],
            Button.primary("Update outcome", key="forward-evidence.update", on_click=update_outcome),
            status_note,
            Note("No external or broker action is available; execution_allowed=false."),
        ],
        spacing=theme.SPACE_2,
    )
    form_host = ft.Container(content=record_form)
    manifest_card = GlassCard("Decision-time manifest / Mature outcome", body=form_host)

    def show_view(value: str) -> None:
        selected_view["value"] = value
        form_host.content = record_form if value == "Record" else mature_form
        if page is not None:
            page.update()

    refresh()
    backtest = getattr(state.snapshot, "backtest", None)
    evidence = getattr(backtest, "quality_momentum_evidence", None)
    metadata = getattr(backtest, "metadata", {}) or {}
    observations = metadata.get("quality_momentum_evidence_rows") if hasattr(metadata, "get") else None
    available = None
    if evidence is not None and hasattr(evidence, "get") and "status" in evidence and not getattr(evidence, "empty", True):
        available = int((evidence["status"].astype(str).str.casefold() == "available").sum())
    backtest_status = getattr(backtest, "status", None)
    status_label = {"available": "Available", "partial": "Partial", "unavailable": "Unavailable"}.get(
        str(backtest_status).casefold(),
    ) if backtest_status is not None else None
    summary_card = GlassCard(
        "Quality-momentum forward paper evidence",
        body=ft.Column(
            [
                KpiTile(
                    "Backtest observations",
                    format_count(observations, unavailable="—") if observations is not None else None,
                    sub="Quality-momentum backtest observations" if observations is not None else "Backtest observations are unavailable",
                ),
                KpiTile(
                    "Available",
                    format_count(available, unavailable="—") if available is not None else None,
                    sub="Available outcome observations" if available is not None else "Availability evidence is unavailable",
                ),
                KpiTile(
                    "Status",
                    status_label,
                    sub="Backtest result status" if status_label is not None else "Backtest result status is unavailable",
                ),
                KpiTile("Fills", "next adjusted close", sub="Forward paper evidence method"),
                Note("Paper proposals are evidence only; fills=next adjusted close | execution_allowed=false."),
                Note("Use the decision-time hashes below to record a local paper observation; no broker or external action is created."),
            ],
            spacing=theme.SPACE_2,
        ),
    )

    outcomes_card = GlassCard("Outcomes over time", body=outcomes_well)
    return PageView(
        chrome=PageChrome(
            "Forward Evidence Diary",
            "Frozen decisions checked against outcomes after their horizons mature",
            [SegmentGroup("forward-evidence", ["Record", "Mature"], selected_view["value"], show_view)],
        ),
        body=page_body(
            [
                manifest_card,
                summary_card,
                outcomes_card,
                GlassCard("Recent local diary entries", body=recent_host),
            ]
        ),
    )


__all__ = ["forward_evidence_page"]
