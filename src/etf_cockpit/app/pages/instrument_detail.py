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


def instrument_detail_page(_page: ft.Page, state: AppState) -> ft.Control:
    selected = state.selected_etf
    model = build_instrument_detail(state.snapshot, selected)
    rows = [ft.Row([ft.Text(name, color=theme.TEXT, width=160), ft.Text(str(value), color=theme.MUTED, selectable=True)], spacing=8) for name, value in model.sections.items()]
    return ft.Column([panel(ft.Column([section_header(f"Instrument Detail: {model.display_name}", "Canonical identity, score evidence, data freshness and unavailable states are shown without recalculating authority in the UI."), ft.Text(str(model.identity), color=theme.MUTED, selectable=True)], spacing=8)), render_etf_disclosure_panel(model), render_news_context_panel(model), panel(ft.Column(rows, spacing=8))], expand=True, scroll=ft.ScrollMode.AUTO)
