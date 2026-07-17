from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.components.simple_scores import score_colour
from etf_cockpit.app.components.risk_badges import risk_badge
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    FUNDAMENTAL_CLEAN_PATH,
    NEWS_CLEAN_PATH,
    decision_from_score,
    forecast_score_details,
    latest_fundamental_rows,
    load_fundamental_evidence,
    load_news_items,
    raw_to_score_10,
    sort_news_items,
)


def etf_detail_page(page: ft.Page, state: AppState) -> ft.Control:
    config = state.snapshot.config
    etf_map = config.universe.by_id()
    ids = config.universe.enabled_ids
    if not ids:
        return ft.Column([section_header("Instrument Detail unavailable", "No enabled instruments are configured in the local universe."), ft.Text("Add a validated instrument before opening this detail view.", color=theme.MUTED)], expand=True)
    selected = state.selected_etf if state.selected_etf in ids else ids[0]
    etf = etf_map[selected]
    signal = next((item for item in state.snapshot.signals if item.etf_id == selected), None)
    latest_features = state.snapshot.latest_features
    latest_frame = latest_features[latest_features["etf_id"] == selected] if "etf_id" in latest_features.columns else latest_features
    if signal is None or latest_frame.empty or "etf_id" not in latest_features.columns:
        return ft.Column(
            [
                section_header(f"Instrument Detail: {etf.name}", "Canonical identity remains available even when score or feature evidence is unavailable."),
                ft.Text(f"{etf.ticker} | {etf.isin or 'ISIN needs verification'}", color=theme.TEXT),
                ft.Text("No score or feature evidence is loaded for this instrument. Refresh validated local data before using this view.", color=theme.AMBER, selectable=True),
                _fundamentals_panel(selected),
                _news_panel(selected),
            ],
            expand=True,
        )
    latest = latest_frame.iloc[0]
    price_history = state.snapshot.prices[state.snapshot.prices["etf_id"] == selected].tail(8)
    forecast_details = forecast_score_details(state.snapshot.forecasts)
    forecast_details = forecast_details[forecast_details["etf_id"].astype(str) == selected] if not forecast_details.empty else forecast_details
    evidence_score = raw_to_score_10(signal.total_score)

    def change_etf(event: ft.ControlEvent) -> None:
        state.selected_etf = event.control.value
        from etf_cockpit.app.router import render_shell

        render_shell(page, state, page.route or state.snapshot.config.ui.default_page)

    metrics = [
        ("Last price", f"{latest['last_price']:.2f} {etf.currency}"),
        ("Momentum 60d", f"{latest['momentum_60d']:+.2%}"),
        ("Momentum 120d", f"{latest['momentum_120d']:+.2%}"),
        ("Trend 200", "Above" if latest["trend_200"] > 0 else "Below"),
        ("Vol 60d", f"{latest['vol_60d_ann']:.1%}"),
        ("Drawdown", f"{latest['drawdown_current']:.1%}"),
    ]
    price_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row["date"]), color=theme.MUTED, size=11)),
                ft.DataCell(ft.Text(f"{row['adjusted_close']:.2f}", color=theme.TEXT, size=11)),
            ]
        )
        for _, row in price_history.iterrows()
    ]
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Dropdown(
                        label="Instrument",
                        value=selected,
                        options=[ft.DropdownOption(etf_id) for etf_id in ids],
                        on_select=change_etf,
                        width=220,
                    ),
                    ft.Text(f"{etf.name} | {etf.ticker} | {etf.isin or 'No ISIN'} | {etf.exchange} | TER {etf.ter or 0:.2%}", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD),
                    _decision_badge(evidence_score),
                ],
                spacing=14,
            ),
            ft.Row(
                [
                    metric_card("Evidence score", _score_label(signal.total_score), f"{decision_from_score(evidence_score)} | confidence {signal.confidence:.2f}", score_colour(evidence_score)),
                    metric_card("Toto score", _score_label(signal.components.toto), "latest valid forecast row", score_colour(raw_to_score_10(signal.components.toto))),
                    metric_card("TimesFM score", _score_label(signal.components.timesfm), "latest valid forecast row", score_colour(raw_to_score_10(signal.components.timesfm))),
                    metric_card("Baseline score", _score_label(signal.components.baseline_ml), "algorithm/model baseline", score_colour(raw_to_score_10(signal.components.baseline_ml))),
                ],
                spacing=12,
            ),
            ft.Row(
                [
                    metric_card("Attractiveness", _score_label(getattr(signal.canonical_score, "attractiveness_10", None)), "canonical v3 research output", score_colour(getattr(signal.canonical_score, "attractiveness_10", None))),
                    metric_card("Expected return", _score_label(getattr(signal.canonical_score, "expected_return_10", None)), "model evidence kept separate", score_colour(getattr(signal.canonical_score, "expected_return_10", None))),
                    metric_card("Risk/implementation", _score_label(getattr(signal.canonical_score, "risk_implementation_10", None)), "risk and implementation quality", score_colour(getattr(signal.canonical_score, "risk_implementation_10", None))),
                    metric_card("Evidence confidence", _score_label(getattr(signal.canonical_score, "evidence_confidence_10", None)), "coverage-adjusted confidence", score_colour(getattr(signal.canonical_score, "evidence_confidence_10", None))),
                ],
                spacing=12,
            ),
            ft.Row(
                [
                    panel(
                        ft.Column(
                            [
                                section_header("Recent adjusted prices", "Local adjusted-close history used for algorithms and model inputs."),
                                ft.DataTable(columns=[ft.DataColumn(ft.Text("Date")), ft.DataColumn(ft.Text("Adjusted close"))], rows=price_rows),
                            ],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        expand=True,
                    ),
                    panel(
                        ft.Column([section_header("Algorithm inputs", "Momentum, trend, volatility and drawdown are deterministic calculations.")] + [ft.Row([ft.Text(k, color=theme.MUTED, width=130), ft.Text(v, color=theme.TEXT)]) for k, v in metrics]),
                        expand=True,
                    ),
                    panel(
                        ft.Column(
                            [
                                section_header("Analysis rating", "This rating is advisory and cannot execute a broker order."),
                                _decision_badge(evidence_score),
                                ft.Text(f"Confidence {signal.confidence:.2f}", color=theme.TEXT),
                                _score_10_bar(evidence_score, width=180),
                                ft.Text(_analysis_summary(signal, evidence_score), color=theme.MUTED, selectable=True),
                                ft.Row([risk_badge(code, "block") for code in signal.blocked_by] or [risk_badge("No execution guardrail flags", "ok")], wrap=True),
                                ft.Text("Portfolio trade values are context only; use the score and evidence rows for analysis.", color=theme.MUTED),
                            ],
                            spacing=10,
                        ),
                        expand=True,
                    ),
                ],
                spacing=12,
                expand=True,
            ),
            panel(
                ft.Column(
                    [
                        section_header("Model forecast evidence", "Only forecast rows with status ok and model_allowed_in_score=true are shown as score inputs."),
                        _forecast_table(forecast_details),
                    ],
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            _fundamentals_panel(selected),
            _news_panel(selected),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _fundamentals_panel(instrument_id: str) -> ft.Control:
    frame = load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    if frame.empty or "instrument_id" not in frame.columns:
        return panel(ft.Column([section_header("Fundamentals unavailable", "Five-section fundamentals are optional context and cannot authorise an action."), ft.Text("No local fundamentals record is available; missing data is not treated as bad data.", color=theme.MUTED, selectable=True)]))
    scoped = latest_fundamental_rows(frame[frame["instrument_id"].astype(str).eq(str(instrument_id))])
    if scoped.empty:
        return panel(ft.Column([section_header("Fundamentals unavailable", "No source-matched record is available for this instrument."), ft.Text("Manual review required; deterministic price scores remain unchanged.", color=theme.MUTED, selectable=True)]))
    row = scoped.iloc[-1]
    fields = ["valuation", "profitability", "leverage", "growth", "shareholder_return"]
    lines = [
        f"{field.replace('_', ' ').title()}: {row.get(field, 'N/A')}" for field in fields
    ]
    lines.extend([
        f"Eligibility: {row.get('eligibility', 'not_score_eligible')}",
        f"Source: {row.get('source', row.get('source_authority', 'unavailable'))} | as of {row.get('as_of_date', 'unavailable')}",
        f"Missing: {row.get('missing_fields', 'none') or 'none'} | Sector-relative: {row.get('sector_relative_status', 'unavailable')} | value={row.get('sector_relative_value', 'unavailable')} | peer={row.get('sector_relative_peer', 'unavailable')} | benchmark={row.get('sector_relative_benchmark', 'unavailable')} | delta={row.get('sector_relative_delta', 'unavailable')} | limitation={row.get('sector_relative_limitation', 'No sector-relative comparison evidence supplied.')}",
        f"Limitations: {row.get('limitations', 'unavailable')}",
        "executable_authority=false",
    ])
    return panel(ft.Column([section_header("Fundamental evidence", "Valuation, profitability, leverage, growth and shareholder return remain source-linked context."), *[ft.Text(line, color=theme.MUTED, selectable=True, size=11) for line in lines]]))


def _news_panel(instrument_id: str) -> ft.Control:
    frame = load_news_items(NEWS_CLEAN_PATH)
    if frame.empty or "instrument_id" not in frame.columns:
        return panel(ft.Column([section_header("News & context unavailable", "News is point-in-time validated context only."), ft.Text("No local news source is available. Ambiguous/current-only items are excluded from backtests.", color=theme.MUTED, selectable=True)]))
    scoped = sort_news_items(frame[frame["instrument_id"].astype(str).eq(str(instrument_id))])
    if scoped.empty:
        return panel(ft.Column([section_header("News & context unavailable", "No source-mapped news is available for this instrument."), ft.Text("Manual review required; news cannot change deterministic scores.", color=theme.MUTED, selectable=True)]))
    rows = []
    for _, row in scoped.tail(8).iterrows():
        rows.append(
            ft.Text(
                " | ".join(
                    (
                        str(row.get("headline", "Headline unavailable")),
                        f"source_url={row.get('source_url', row.get('url', 'unavailable'))}",
                        f"published_at={row.get('published_at', 'unavailable')}",
                        f"ingested_at={row.get('ingested_at', 'unavailable')}",
                        f"provider_name={row.get('provider_name', row.get('provider', 'provider unavailable'))}",
                        f"credibility={row.get('credibility', 'unverified')}",
                        f"instrument_mapping_method={row.get('instrument_mapping_method', 'unavailable')}",
                        f"available_at_decision_time={bool(row.get('available_at_decision_time', False))}",
                        f"timestamp_status={row.get('timestamp_status', row.get('timestamp_confidence', 'unavailable'))}",
                        "context_only=true",
                        "executable_authority=false",
                    )
                ),
                color=theme.MUTED,
                selectable=True,
                size=11,
            )
        )
    return panel(ft.Column([section_header("News & context", "Source URL, published/ingested time, mapping and availability are shown; context cannot alter final action."), *rows]))


def _forecast_table(frame) -> ft.Control:
    if frame.empty:
        return ft.Text("No valid forecast rows are loaded for this instrument. Run scripts/run_forecasts.py to refresh baseline, Toto and TimesFM outputs.", color=theme.MUTED)
    rows = []
    for _, row in frame.sort_values("model_name").iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row["model_name"]).title(), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(row["horizon_days"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(f"{float(row['expected_return']):+.1%}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(_score_label(float(row["score"])), color=score_colour(raw_to_score_10(float(row["score"]))), size=12, weight=ft.FontWeight.BOLD)),
                ]
            )
        )
    return ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Model")),
            ft.DataColumn(ft.Text("Horizon")),
            ft.DataColumn(ft.Text("Expected return")),
            ft.DataColumn(ft.Text("Score")),
        ],
        rows=rows,
        data_row_min_height=38,
        data_row_max_height=46,
    )


def _score_label(raw_score: float | int | None) -> str:
    score = raw_to_score_10(raw_score)
    return "N/A" if score is None else f"{score:.1f}/10"


def _analysis_summary(signal, evidence_score: float | None) -> str:
    return (
        f"Final evidence score {_score_display(evidence_score)} with confidence {signal.confidence:.2f}. "
        f"Momentum {_score_label(signal.components.momentum)}, trend {_score_label(signal.components.trend)}, "
        f"risk {_score_label(signal.components.risk)}, baseline {_score_label(signal.components.baseline_ml)}, "
        f"Toto {_score_label(signal.components.toto)}, TimesFM {_score_label(signal.components.timesfm)}. "
        "This is an advisory analysis score only; models do not execute trades or invent missing data."
    )


def _score_display(score_10: float | None) -> str:
    return "N/A" if score_10 is None else f"{score_10:.1f}/10"


def _decision_badge(score_10: float | None) -> ft.Container:
    return ft.Container(
        content=ft.Text(decision_from_score(score_10), color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD),
        bgcolor=score_colour(score_10),
        padding=ft.Padding(left=8, top=4, right=8, bottom=4),
        border_radius=6,
    )


def _score_10_bar(score_10: float | None, width: int = 180) -> ft.Row:
    score = 0.0 if score_10 is None else max(0.0, min(10.0, float(score_10)))
    return ft.Row(
        [
            ft.Container(
                content=ft.Container(width=max(4, int(width * score / 10.0)), height=8, bgcolor=score_colour(score_10), border_radius=4),
                width=width,
                height=8,
                bgcolor=theme.SURFACE_2,
                border_radius=4,
            ),
            ft.Text("N/A" if score_10 is None else f"{score:.1f}/10", color=score_colour(score_10), size=12, width=58),
        ],
        spacing=7,
        tight=True,
    )
