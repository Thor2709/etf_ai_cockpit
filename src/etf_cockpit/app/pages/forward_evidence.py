"""Local forward-evidence diary and paper-proposal evidence surface."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    ForwardEvidenceDiary,
    ForwardEvidenceIntegrityError,
    ForwardEvidenceObservation,
    ForwardInputManifest,
)
from etf_cockpit.core.paths import DATA_DIR


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def _timestamp(value: str | None, label: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{label} is required and must include a timezone")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone, for example +00:00")
    return parsed


def forward_evidence_page(page: ft.Page | None, state: AppState) -> ft.Control:
    diary = ForwardEvidenceDiary()
    observation_id = ft.TextField(label="Observation ID", key="forward-evidence.observation-id")
    instrument_ids = ft.TextField(label="Instrument IDs (comma-separated)", key="forward-evidence.instrument-ids")
    decision_as_of = ft.TextField(label="Decision as-of (ISO 8601 with timezone)", key="forward-evidence.as-of")
    data_hash = ft.TextField(label="Data hash (SHA-256)", key="forward-evidence.data-hash")
    formula_hash = ft.TextField(label="Formula hash (SHA-256)", key="forward-evidence.formula-hash")
    model_hash = ft.TextField(label="Model hash (SHA-256)", key="forward-evidence.model-hash")
    portfolio_hash = ft.TextField(label="Portfolio hash (SHA-256)", key="forward-evidence.portfolio-hash")
    policy_hash = ft.TextField(label="Policy hash (SHA-256)", key="forward-evidence.policy-hash")
    proposal_hash = ft.TextField(label="Proposal hash (SHA-256)", key="forward-evidence.proposal-hash")
    source_authority = ft.TextField(label="Decision source authority", key="forward-evidence.source-authority")
    source_checksum = ft.TextField(label="Decision source checksum (SHA-256)", key="forward-evidence.source-checksum")
    decision = ft.TextField(label="Decision", key="forward-evidence.decision")
    proposal_outcome = ft.Dropdown(
        label="Proposal outcome",
        key="forward-evidence.proposal-outcome",
        value="observation_only",
        options=[ft.dropdown.Option(value) for value in ("not_proposed", "observation_only", "paper_proposed", "paper_accepted", "paper_rejected", "cancelled", "expired")],
    )
    proposal_id = ft.TextField(label="Proposal ID (optional)", key="forward-evidence.proposal-id")
    paper_order_ids = ft.TextField(label="Paper order IDs (comma-separated)", key="forward-evidence.paper-order-ids")
    rationale = ft.TextField(label="Rationale / limitations", key="forward-evidence.rationale", multiline=True, min_lines=2, max_lines=5)
    update_id = ft.TextField(label="Observation ID to update", key="forward-evidence.update-id")
    outcome_status = ft.Dropdown(
        label="Outcome status",
        key="forward-evidence.outcome-status",
        value="available",
        options=[ft.dropdown.Option(value) for value in ("available", "unavailable", "stale", "conflicted")],
    )
    outcome_as_of = ft.TextField(label="Outcome as-of (ISO 8601 with timezone)", key="forward-evidence.outcome-as-of")
    outcome_authority = ft.TextField(label="Outcome source authority", key="forward-evidence.outcome-authority")
    outcome_checksum = ft.TextField(label="Outcome source checksum (SHA-256)", key="forward-evidence.outcome-checksum")
    metrics = ft.TextField(label="Outcome metrics (JSON object)", key="forward-evidence.metrics")
    outcome_notes = ft.TextField(label="Outcome notes", key="forward-evidence.outcome-notes", multiline=True, min_lines=2, max_lines=4)
    status = ft.Text("No external or broker action is available; execution_allowed=false.", color=theme.MUTED, selectable=True)
    entries = ft.Column(spacing=6)

    def refresh() -> None:
        try:
            rows = diary.list_entries(root=DATA_DIR)
            if not rows:
                entries.controls = [ft.Text("Empty: record a local observation opportunity to begin.", color=theme.MUTED)]
            else:
                entries.controls = [
                    ft.Text(
                        f"{row.observation.observation_id} | {row.observation.manifest.as_of.isoformat()} | instruments={','.join(row.observation.instrument_ids)} | "
                        f"proposal={row.observation.proposal_outcome} | outcome={row.outcome.status} | "
                        f"manifest={str(row.observation.checksum or '')[:12]}… | execution_allowed={row.observation.execution_allowed}",
                        color=theme.TEXT,
                        size=12,
                        selectable=True,
                    )
                    for row in rows
                ]
        except (ForwardEvidenceIntegrityError, PermissionError, OSError, ValueError) as exc:
            entries.controls = [ft.Text(f"Unavailable: forward-evidence storage requires manual review ({exc}).", color=theme.AMBER, selectable=True)]

    def show(message: str, colour: str) -> None:
        status.value = message
        status.color = colour
        refresh()
        if page is not None:
            page.update()

    def record_observation(_event: ft.ControlEvent) -> None:
        try:
            manifest = ForwardInputManifest(
                as_of=_timestamp(decision_as_of.value, "decision as-of"),
                data_hash=data_hash.value or "",
                formula_hash=formula_hash.value or "",
                model_hash=model_hash.value or "",
                portfolio_hash=portfolio_hash.value or "",
                policy_hash=policy_hash.value or "",
                proposal_hash=proposal_hash.value or "",
                source_authority=source_authority.value or "",
                source_checksum=source_checksum.value or "",
            )
            observation = diary.record_observation(
                ForwardEvidenceObservation(
                    observation_id=observation_id.value or "",
                    created_at=datetime.now(timezone.utc),
                    instrument_ids=_split(instrument_ids.value),
                    manifest=manifest,
                    proposal_outcome=proposal_outcome.value or "observation_only",
                    proposal_id=(proposal_id.value or "").strip() or None,
                    paper_order_ids=_split(paper_order_ids.value),
                    decision=decision.value or "",
                    rationale=rationale.value or "",
                ),
                root=DATA_DIR,
            )
            show(f"Recorded {observation.observation.observation_id}; manifest and pending outcome are durable locally.", theme.GREEN)
        except Exception as exc:
            show(f"Error: observation was not recorded ({type(exc).__name__}: {exc}). No external action was created.", theme.RED)

    def update_outcome(_event: ft.ControlEvent) -> None:
        try:
            metric_value = json.loads(metrics.value or "{}")
            if not isinstance(metric_value, dict):
                raise ValueError("outcome metrics must be a JSON object")
            outcome = diary.update_outcome(
                update_id.value or "",
                status=outcome_status.value or "available",
                outcome_as_of=_timestamp(outcome_as_of.value, "outcome as-of"),
                source_authority=outcome_authority.value or "",
                source_checksum=outcome_checksum.value or "",
                metrics=metric_value,
                notes=outcome_notes.value or "",
                root=DATA_DIR,
            )
            show(f"Recorded outcome version {outcome.version} for {outcome.observation_id}; prior records remain immutable.", theme.GREEN)
        except Exception as exc:
            show(f"Error: outcome was not recorded ({type(exc).__name__}: {exc}). The prior outcome remains unchanged.", theme.RED)

    refresh()
    return ft.Column(
        [
            section_header("Forward Evidence Diary", "Record every local observation opportunity with decision-time hashes, then mature its outcome separately. Paper proposals are evidence only; execution_allowed=false."),
            panel(ft.Column([
                ft.Text("Decision-time manifest", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.Row([observation_id, instrument_ids], wrap=True),
                decision_as_of,
                ft.Row([data_hash, formula_hash], wrap=True),
                ft.Row([model_hash, portfolio_hash], wrap=True),
                ft.Row([policy_hash, proposal_hash], wrap=True),
                ft.Row([source_authority, source_checksum], wrap=True),
                ft.Row([decision, proposal_outcome, proposal_id], wrap=True),
                paper_order_ids,
                rationale,
                ft.FilledButton("Record observation", key="forward-evidence.record", on_click=record_observation),
            ], spacing=8)),
            panel(ft.Column([
                ft.Text("Mature outcome", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.Row([update_id, outcome_status], wrap=True),
                ft.Row([outcome_as_of, outcome_authority], wrap=True),
                outcome_checksum,
                metrics,
                outcome_notes,
                ft.FilledButton("Update outcome", key="forward-evidence.update", on_click=update_outcome),
                status,
            ], spacing=8)),
            panel(ft.Column([ft.Text("Recent local diary entries", color=theme.TEXT, weight=ft.FontWeight.BOLD), entries], spacing=8), expand=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["forward_evidence_page"]
