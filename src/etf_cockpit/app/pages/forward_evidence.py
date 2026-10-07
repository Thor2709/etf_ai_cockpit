"""Local forward-evidence diary and paper-proposal evidence surface."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import Button, Disclosure, GlassCard, KpiTile, ListRow, Note, Segmented
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import ForwardEvidenceDiary, ForwardEvidenceObservation, ForwardInputManifest
from etf_cockpit.core.paths import DATA_DIR


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
    state_segment = {"value": "Record"}
    status = ft.Text("No external or broker action is available; execution_allowed=false.")
    entries: list[object] = []

    def refresh() -> None:
        try:
            entries[:] = diary.list_entries(root=DATA_DIR)
        except Exception:
            entries.clear()

    def show(message: str) -> None:
        status.value = message
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
        except Exception:
            show("Observation unavailable: check required fields and local storage.")

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
        except Exception:
            show("Outcome unavailable: check required fields and local storage.")

    refresh()
    recent = [
        ListRow(
            "info",
            row.observation.observation_id,
            f"{row.observation.manifest.as_of.isoformat()} · {row.outcome.status}",
            tag=(str(row.outcome.status), "mute"),
        )
        for row in entries[-12:]
    ] or [ListRow("info", "No observations yet.")]
    backtest = getattr(state.snapshot, "backtest", None)
    evidence = getattr(backtest, "quality_momentum_evidence", None)
    metadata = getattr(backtest, "metadata", {}) or {}
    count = metadata.get("quality_momentum_evidence_rows")
    count = count if count else None
    available = None
    if evidence is not None and hasattr(evidence, "get") and "status" in evidence and not evidence.empty:
        available = int((evidence["status"].astype(str) == "available").sum())
        available = available or None
    record_card = GlassCard(
        "Decision-time manifest",
        body=ft.Column(
            [
                fields["observation_id"],
                fields["instrument_ids"],
                fields["decision_as_of"],
                fields["decision"],
                Segmented(
                    ["not_proposed", "observation_only", "paper_proposed", "paper_accepted", "paper_rejected", "cancelled", "expired"],
                    "observation_only",
                    on_change=lambda value: proposal_outcome.update(value=value),
                ),
                fields["proposal_id"],
                fields["paper_order_ids"],
                fields["rationale"],
                Disclosure("hashes and sources", ft.Column([fields[name] for name in ("data_hash", "formula_hash", "model_hash", "portfolio_hash", "policy_hash", "proposal_hash", "source_authority", "source_checksum")])),
                Button.primary("Record observation", key="forward-evidence.record", on_click=record_observation),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    mature_card = GlassCard(
        "Mature outcome",
        body=ft.Column(
            [
                fields["update_id"],
                Segmented(["available", "unavailable", "stale", "conflicted"], "available", on_change=lambda value: outcome_status.update(value=value)),
                fields["outcome_as_of"],
                Disclosure("outcome sources", ft.Column([fields["outcome_authority"], fields["outcome_checksum"], fields["metrics"]])),
                fields["outcome_notes"],
                Button.primary("Update outcome", key="forward-evidence.update", on_click=update_outcome),
                status,
                Note("No external or broker action is available; execution_allowed=false."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    summary = GlassCard(
        "Quality-momentum forward paper evidence",
        body=ft.Column(
            [
                KpiTile("Backtest observations", count, sub="Unavailable in the current backtest result"),
                KpiTile("Available", available, sub="Unavailable in the current backtest result"),
                KpiTile("Status", "Unavailable"),
                KpiTile("Fills", "next adjusted close"),
                Note("Use the decision-time hashes below to record a local paper observation; no broker or external action is created."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    cards = [
        GlassCard("Decision-time manifest / Mature outcome", body=ft.Column([record_card, mature_card], spacing=theme.SPACE_2)),
        summary,
        GlassCard("Outcomes over time", body=ck.scatter_bubble([], x_name="Decision date", y_name="Matured excess return (%)", y_unit="%", insight="Matured excess returns by outcome status.", unavailable_reason="No observations yet.")),
        GlassCard("Recent local diary entries", body=ft.Column(recent, spacing=theme.SPACE_2)),
    ]
    return PageView(
        chrome=PageChrome(
            "Forward Evidence Diary",
            "Frozen decisions checked against outcomes after their horizons mature",
            [SegmentGroup("forward-evidence", ["Record", "Mature"], state_segment["value"], on_change=lambda value: state_segment.update(value=value))],
        ),
        body=page_body(cards),
    )


__all__ = ["forward_evidence_page"]
