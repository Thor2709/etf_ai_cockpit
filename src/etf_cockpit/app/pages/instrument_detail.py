from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.selectors.instrument_detail import InstrumentDetailViewModel, build_etf_disclosure_panel, build_instrument_detail
from etf_cockpit.app.state import AppState


def render_etf_disclosure_panel(model: InstrumentDetailViewModel) -> ft.Control:
    """Render selected ETF document inventory and holdings quality without inventing evidence."""
    disclosure = build_etf_disclosure_panel(model)
    if disclosure.get("status") == "unavailable" and not disclosure.get("document_inventory"):
        body: ft.Control = ft.Text("ETF disclosure evidence unavailable; no local document inventory is registered.", color=theme.MUTED, selectable=True)
    else:
        documents = disclosure.get("document_inventory", [])
        document_lines = [
            f"{row.get('document_type', 'document')}: {row.get('coverage_status', 'unavailable')} | date={row.get('document_date', 'unavailable')} | source={row.get('source', 'unavailable')} | checksum={row.get('checksum', 'unavailable')}"
            for row in documents
        ]
        holdings = disclosure.get("holdings", {})
        holdings_line = "Holdings: " + ", ".join(f"{key}={holdings.get(key, 'unavailable')}" for key in ("completeness", "freshness", "confidence", "source", "authority", "as_of"))
        kid = disclosure.get("kid", {})
        methodology = disclosure.get("methodology", {})
        kid_line = "KID: " + ", ".join(f"{key}={kid.get(key, 'unavailable')}" for key in ("status", "sri", "holding_period_years", "document_date", "extraction_confidence", "source_pages", "warnings", "source_sha256", "parser_version"))
        methodology_line = "Methodology: " + ", ".join(f"{key}={methodology.get(key, 'unavailable')}" for key in ("status", "provider", "index_series", "version", "document_date", "confidence", "source_pages", "warnings", "source_sha256", "parser_version"))
        body = ft.Column([ft.Text(line, color=theme.MUTED, selectable=True, size=11) for line in [*document_lines, holdings_line, kid_line, methodology_line] or ["No local disclosure rows are available."]], spacing=4)
    return panel(ft.Column([section_header("ETF disclosure evidence", "Document inventory and normalised holdings quality for the selected instrument; unavailable values stay explicit."), body], spacing=8))


def render_news_context_panel(model: InstrumentDetailViewModel) -> ft.Control:
    """Render source-linked news context with every point-in-time field visible."""

    news = model.sections.get("news")
    if not isinstance(news, dict):
        news = {"status": "unavailable", "items": []}
    items = news.get("items", [])
    if news.get("status") != "available" or not items:
        body: ft.Control = ft.Text(
            str(news.get("message", "News unavailable for this instrument.")),
            color=theme.MUTED,
            selectable=True,
        )
    else:
        rows: list[ft.Control] = []
        for item in items:
            headline = item.get("headline", "Headline unavailable")
            provenance = " | ".join(
                (
                    f"source_url={item.get('source_url', 'unavailable')}",
                    f"published_at={item.get('published_at', 'unavailable')}",
                    f"ingested_at={item.get('ingested_at', 'unavailable')}",
                    f"provider_name={item.get('provider_name', 'unavailable')}",
                    f"credibility={item.get('credibility', 'unverified')}",
                    f"instrument_mapping_method={item.get('instrument_mapping_method', 'unavailable')}",
                    f"available_at_decision_time={bool(item.get('available_at_decision_time', False))}",
                    f"timestamp_status={item.get('timestamp_status', 'unavailable')}",
                    "context_only=true",
                    "executable_authority=false",
                )
            )
            rows.append(ft.Text(f"{headline} | {provenance}", color=theme.MUTED, selectable=True, size=11))
        body = ft.Column(rows, spacing=4)
    return panel(
        ft.Column(
            [
                section_header("News & context", "Source URL, timestamps, provider and point-in-time status are shown for each item; news is context-only."),
                body,
            ],
            spacing=8,
        )
    )


def _driver_table(label: str, rows: list[dict[str, object]]) -> ft.Control:
    columns = ["Component", "Score", "Direction", "Authority", "Freshness", "Driver"]
    if not rows:
        return ft.Column([ft.Text(label, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12), ft.Text("Unavailable", color=theme.MUTED, size=11)], spacing=4)
    table_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.get("component") or "unavailable"), color=theme.TEXT)),
                ft.DataCell(ft.Text(str(row.get("normalised_score") if row.get("normalised_score") is not None else "N/A"), color=theme.CYAN)),
                ft.DataCell(ft.Text(str(row.get("direction") or "unavailable"), color=theme.MUTED)),
                ft.DataCell(ft.Text(str(row.get("authority") or "unavailable"), color=theme.MUTED)),
                ft.DataCell(ft.Text(str(row.get("freshness_status") or "unavailable"), color=theme.MUTED)),
                ft.DataCell(ft.Text(str(row.get("driver_text") or "unavailable"), color=theme.MUTED, selectable=True)),
            ]
        )
        for row in rows
    ]
    return ft.Column(
        [
            ft.Text(label, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12),
            ft.DataTable(columns=[ft.DataColumn(ft.Text(column, color=theme.TEXT)) for column in columns], rows=table_rows),
        ],
        spacing=4,
    )


def _render_feature_driver_panel(panel_data: object) -> ft.Control:
    if not isinstance(panel_data, dict):
        return panel(ft.Column([ft.Text("Feature drivers unavailable", color=theme.MUTED)], spacing=4))
    groups = [
        ("Top positive", panel_data.get("top_positive", [])),
        ("Top negative", panel_data.get("top_negative", [])),
        ("Missing / N/A", panel_data.get("missing_or_na", [])),
        ("Low authority", panel_data.get("low_authority", [])),
        ("Stale / partial", panel_data.get("stale_or_partial", [])),
    ]
    return panel(
        ft.Column(
            [
                section_header("Feature drivers", "Ordered driver rows are informational evidence only; missing, low-authority and stale values remain explicit."),
                *[_driver_table(label, rows if isinstance(rows, list) else []) for label, rows in groups],
            ],
            spacing=8,
        )
    )


def _render_crowding_attribution_panel(sections: dict[str, object]) -> ft.Control:
    scores = sections.get("scores") if isinstance(sections.get("scores"), dict) else {}
    attribution = sections.get("attribution") if isinstance(sections.get("attribution"), dict) else {}
    crowding = scores.get("crowding") if isinstance(scores.get("crowding"), dict) else {}
    friction = scores.get("friction") if isinstance(scores.get("friction"), dict) else {}

    def _bps(value: object) -> str:
        try:
            return f"{float(value):.2f} bps"
        except (TypeError, ValueError):
            return "N/A"

    def _ratio(value: object) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "N/A"

    lines = [
        f"Crowding: {crowding.get('crowding_warning', 'N/A')} | cluster {crowding.get('cluster_label', 'N/A')} | peer corr {crowding.get('average_peer_correlation', 'N/A')} | risk contribution {crowding.get('cluster_risk_contribution', 'N/A')} | coverage {crowding.get('ranking_coverage', 'N/A')} | pair sample {crowding.get('pair_sample_size', 'N/A')} / row sample {crowding.get('sample_size', 'N/A')} | as of {crowding.get('as_of_date', 'N/A')}",
        f"Broad benchmark: beta {attribution.get('benchmark_beta', 'N/A')} | corr {attribution.get('benchmark_correlation', 'N/A')} | alpha {attribution.get('alpha_proxy', 'N/A')}",
        f"Sector-relative: return {attribution.get('sector_relative_return', 'N/A')} | alpha {attribution.get('sector_alpha_proxy', 'N/A')} | status {attribution.get('sector_attribution_status', 'N/A')} | theme-relative return {attribution.get('theme_relative_return', 'N/A')} | theme alpha {attribution.get('theme_alpha_proxy', 'N/A')} | theme status {attribution.get('theme_attribution_status', 'N/A')} | source {attribution.get('source_dataset', 'N/A')}",
        f"Gross edge: {_bps(friction.get('gross_expected_edge_bps'))} | Estimated cost: {_bps(friction.get('estimated_total_cost_bps'))} | Net edge: {_bps(friction.get('net_expected_edge_bps'))} | Edge/cost: {_ratio(friction.get('edge_to_cost_ratio'))} | Cost scenario: {friction.get('cost_stress_scenario', 'unavailable')} | status {friction.get('status', 'unavailable')}",
        "These diagnostics are descriptive evidence only; execution_allowed=false.",
    ]
    return panel(ft.Column([section_header("Crowding and attribution", "Configured sector/theme metadata and clean adjusted-price evidence; unavailable values remain N/A."), *[ft.Text(line, color=theme.MUTED, size=11, selectable=True) for line in lines]], spacing=5))


def instrument_detail_page(_page: ft.Page, state: AppState) -> ft.Control:
    selected = state.selected_etf
    model = build_instrument_detail(state.snapshot, selected)
    rows = [
        ft.Row([ft.Text(name, color=theme.TEXT, width=160), ft.Text(str(value), color=theme.MUTED, selectable=True)], spacing=8)
        for name, value in model.sections.items()
        if name not in {"feature_drivers", "scores", "risk", "attribution"}
    ]
    return ft.Column(
        [
            panel(ft.Column([section_header(f"Instrument Detail: {model.display_name}", "Canonical identity, score evidence, data freshness and unavailable states are shown without recalculating authority in the UI."), ft.Text(str(model.identity), color=theme.MUTED, selectable=True)], spacing=8)),
            _render_feature_driver_panel(model.sections.get("feature_drivers")),
            _render_crowding_attribution_panel(model.sections),
            render_etf_disclosure_panel(model),
            render_news_context_panel(model),
            panel(ft.Column(rows, spacing=8)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
