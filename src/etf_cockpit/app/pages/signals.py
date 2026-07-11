from __future__ import annotations

from pathlib import Path

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.simple_scores import simple_score_grouped_sections, simple_score_legend
from etf_cockpit.app.state import AppState
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores


def signals_page(_page: ft.Page, state: AppState) -> ft.Control:
    narrow = float(getattr(_page, "width", 0) or state.snapshot.config.ui.window_width) < 760
    scores = build_simple_instrument_scores(
        state.snapshot.config,
        state.snapshot.signals,
        state.snapshot.forecasts,
        state.snapshot.prices,
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

    return ft.Column(
        [
            ft.Column(card_controls, spacing=8) if narrow else ft.Row(card_controls, spacing=12),
            simple_score_legend(),
            panel(
                ft.Column(
                    [
                        section_header(
                            "All stock and ETF scores",
                            "Rows include primary tier instruments, yfinance-only secondary tier instruments and Sparebanken equity certificates. Expand a row for evidence quality, risk/friction, algorithms and model authority.",
                        ),
                        simple_score_grouped_sections(scores),
                    ],
                    spacing=12,
                ),
            ),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
