from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.simple_scores import simple_score_grouped_sections, simple_score_legend
from etf_cockpit.app.components.governance_badges import build_gate_summary
from etf_cockpit.app.state import AppState
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.ui_facade import build_simple_instrument_scores
from etf_cockpit.app.selectors.instrument_detail import _operational_evidence_panel


def _latest_operational_row(rows: object) -> dict[str, object]:
    if not isinstance(rows, list):
        return {}

    def sort_key(row: Mapping[str, object]) -> tuple[int, str, str, str]:
        execution_key = pd.to_datetime(row.get("execution_timestamp"), errors="coerce")
        signal_key = pd.to_datetime(row.get("signal_timestamp"), errors="coerce")
        return (
            0 if pd.isna(execution_key) else 1,
            "" if pd.isna(execution_key) else execution_key.isoformat(),
            "" if pd.isna(signal_key) else signal_key.isoformat(),
            str(row.get("strategy", "")),
        )

    valid_rows = [row for row in rows if isinstance(row, Mapping)]
    return dict(max(valid_rows, key=sort_key, default={}))


def _signals_operational_evidence(scores: list[object], report: object) -> ft.Control:
    lines: list[str] = []
    evidence_fields = (
        "evidence_status", "evidence_reason", "signal_date", "signal_timestamp",
        "execution_date", "execution_timestamp", "decision_price", "decision_price_basis",
        "decision_price_source_identity", "next_open_reference_price", "next_open_reference_basis",
        "next_open_source_identity", "next_period_reference_price", "next_period_reference_basis",
        "next_period_source_identity", "close_to_next_open_gap", "price_provenance",
        "arrival_price_assumption", "execution_delay_sessions", "same_bar_execution_avoided",
        "observed_range_spread_proxy", "spread_proxy", "cost_spread_assumption_bps", "cost_spread_assumption_source",
        "estimated_cost_bps", "estimated_cost_bps_source", "session_state", "auction_state",
        "expiry_state", "order_lifecycle", "fill_source", "paper_fill_source",
        "reconciled_fill_source", "execution_allowed",
    )

    def display(value: object) -> str:
        return "unavailable" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)

    for score in scores:
        instrument_id = str(getattr(score, "display_id", "")).strip()
        if not instrument_id:
            continue
        projection = _operational_evidence_panel(report, instrument_id)
        if projection.get("status") == "available":
            rows = projection.get("rows", [])
            latest = _latest_operational_row(rows)
            lines.append(f"{instrument_id}: " + "; ".join(f"{field}={display(latest.get(field))}" for field in evidence_fields))
        else:
            lines.append(
                f"{instrument_id}: unavailable/context-only (evidence_reason={display(projection.get('message', 'exact operational evidence unavailable'))}); "
                + "; ".join(f"{field}=unavailable" for field in evidence_fields if field not in {"evidence_reason", "execution_allowed"})
                + "; evidence_reason=" + display(projection.get("message", "exact operational evidence unavailable"))
                + "; execution_allowed=false; aggregate aliases are excluded"
            )
    if not lines:
        lines = ["Instrument-scoped operational evidence unavailable; execution_allowed=false"]
    return panel(
        ft.Column(
            [
                section_header(
                    "Operational evidence",
                    "Exact-instrument backtest evidence only. Decision price, next-open reference, source and timestamp are descriptive; paper/reconciled fills remain separate.",
                ),
                ft.Text("\n".join(lines), color=theme.MUTED, selectable=True),
            ],
            spacing=6,
        )
    )


def signals_page(_page: ft.Page, state: AppState) -> ft.Control:
    narrow = float(getattr(_page, "width", 0) or state.snapshot.config.ui.window_width) < 760
    reference_context = context_from_snapshot(
        state.snapshot,
        purpose="comparison",
        analysis_id=f"signals:{getattr(state.snapshot, 'universe_revision', 'unknown')}",
    )
    scores = build_simple_instrument_scores(
        state.snapshot.config,
        state.snapshot.signals,
        state.snapshot.forecasts,
        state.snapshot.prices,
        benchmark_data_id=reference_context.benchmark_data_id,
        benchmark_reference=reference_context.projection,
        benchmark_registry=reference_context.registry,
        reference_identity=reference_context.identity,
        peer_member_ids=reference_context.peer_member_ids,
        cash_observation_time=state.snapshot.benchmark_reference_decision_time,
    )
    strong = sum(1 for score in scores if score.final_label == "strong_evidence_candidate")
    positive = sum(1 for score in scores if score.final_label == "positive_evidence_candidate")
    watch = sum(1 for score in scores if score.final_label in {"watchlist", "mixed_evidence_review", "hold_context"})
    review = sum(1 for score in scores if score.final_action == "manual_review")
    forecast_source = "No forecast file loaded"
    if not state.snapshot.forecasts.empty and "source_file" in state.snapshot.forecasts.columns:
        forecast_source = Path(str(state.snapshot.forecasts["source_file"].iloc[0])).name

    card_controls = [
        metric_card("Strong evidence", str(strong), "score, quality and friction all pass", theme.GREEN),
        metric_card("Positive evidence", str(positive), "usable evidence with enough quality", theme.LIGHT_GREEN),
        metric_card("Watch/mixed", str(watch), "mixed or context-only evidence", theme.CYAN),
        metric_card("Manual review", str(review), "blocked, weak or low-quality evidence", theme.AMBER),
        metric_card("Forecast source", forecast_source, "latest local model CSV", theme.PURPLE),
    ]

    gate_summary = None
    if scores and scores[0].authority_decision is not None:
        def open_help(_event: ft.ControlEvent) -> None:
            go = getattr(_page, "go", None)
            if callable(go):
                go("/help#manual_review")
            else:
                _page.route = "/help#manual_review"

        gate_summary = build_gate_summary(
            scores[0].authority_decision,
            open_help=open_help,
        )

    controls: list[ft.Control] = [
        ft.Column(card_controls, spacing=8) if narrow else ft.Row(card_controls, spacing=12),
        simple_score_legend(),
    ]
    if gate_summary is not None:
        controls.append(gate_summary)
    controls.append(_signals_operational_evidence(scores, getattr(state.snapshot, "backtest", None)))
    controls.append(
        panel(
            ft.Column(
                [
                    section_header(
                        "All stock and ETF scores",
                        "Rows include primary tier instruments, yfinance-only secondary tier instruments and Sparebanken equity certificates. Expand a row for evidence quality, distribution-based expected return, order-size friction, algorithms and model authority.",
                    ),
                    simple_score_grouped_sections(scores, page=_page, state=state),
                ],
                spacing=12,
            )
        )
    )
    return ft.Column(
        controls,
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
