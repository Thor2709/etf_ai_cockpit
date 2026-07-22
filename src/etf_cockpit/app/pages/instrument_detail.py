from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.selectors.instrument_detail import InstrumentDetailViewModel, build_etf_disclosure_panel, build_etf_liquidity_panel, build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import bitemporal_history_summary


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
        metadata = ft.Column(
            [
                ft.Text("KID evidence metadata", color=theme.TEXT, size=11, weight=ft.FontWeight.BOLD),
                _render_evidence_badges(kid),
                ft.Text("Methodology evidence metadata", color=theme.TEXT, size=11, weight=ft.FontWeight.BOLD),
                _render_evidence_badges(methodology),
                ft.Text("Holdings evidence metadata", color=theme.TEXT, size=11, weight=ft.FontWeight.BOLD),
                _render_evidence_badges(holdings),
            ],
            spacing=4,
        )
        body = ft.Column([metadata, *[ft.Text(line, color=theme.MUTED, selectable=True, size=11) for line in [*document_lines, holdings_line, kid_line, methodology_line] or ["No local disclosure rows are available."]]], spacing=4)
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
            number = float(value)
        except (TypeError, ValueError):
            return "N/A"
        return "N/A" if not math.isfinite(number) else f"{number:.2f} bps"

    def _ratio(value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "N/A"
        return "N/A" if not math.isfinite(number) else f"{number:.2f}"

    def _pct(value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "N/A"
        return "N/A" if not math.isfinite(number) else f"{number:+.1%}"

    def _euro(value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "N/A"
        return "N/A" if not math.isfinite(number) else f"EUR {number:,.2f}"

    horizon = friction.get("expected_return_horizon_days")
    try:
        horizon_text = f"{int(float(horizon))}d" if math.isfinite(float(horizon)) else "N/A"
    except (TypeError, ValueError):
        horizon_text = "N/A"

    lines = [
        f"Crowding: {crowding.get('crowding_warning', 'N/A')} | cluster {crowding.get('cluster_label', 'N/A')} | peer corr {crowding.get('average_peer_correlation', 'N/A')} | risk contribution {crowding.get('cluster_risk_contribution', 'N/A')} | coverage {crowding.get('ranking_coverage', 'N/A')} | pair sample {crowding.get('pair_sample_size', 'N/A')} / row sample {crowding.get('sample_size', 'N/A')} | top-theme concentration {crowding.get('top_ranked_theme_concentration', 'N/A')} | top-theme warning {crowding.get('top_ranked_theme_warning', 'N/A')} | as of {crowding.get('as_of_date', 'N/A')}",
        f"Broad benchmark: beta {attribution.get('benchmark_beta', 'N/A')} | corr {attribution.get('benchmark_correlation', 'N/A')} | alpha {attribution.get('alpha') if attribution.get('alpha') is not None else attribution.get('alpha_proxy', 'N/A')}",
        f"Sector-relative: return {attribution.get('sector_relative_return', 'N/A')} | alpha {attribution.get('sector_alpha_proxy', 'N/A')} | status {attribution.get('sector_attribution_status', 'N/A')} | theme-relative return {attribution.get('theme_relative_return', 'N/A')} | theme alpha {attribution.get('theme_alpha_proxy', 'N/A')} | theme status {attribution.get('theme_attribution_status', 'N/A')} | source {attribution.get('source_dataset', 'N/A')}",
        f"Gross edge: {_bps(friction.get('gross_expected_edge_bps'))} | Estimated cost: {_bps(friction.get('estimated_total_cost_bps'))} | Net edge: {_bps(friction.get('net_expected_edge_bps'))} | Edge/cost: {_ratio(friction.get('edge_to_cost_ratio'))} | Cost scenario: {friction.get('cost_stress_scenario', 'unavailable')} | status {friction.get('status', 'unavailable')}",
        f"Expected-return distribution ({horizon_text}): q10 {_pct(friction.get('q10_expected_return'))} | q50 {_pct(friction.get('q50_expected_return'))} | q90 {_pct(friction.get('q90_expected_return'))} | net {_pct(friction.get('net_expected_return'))} on {_euro(friction.get('expected_return_order_value_eur'))} | cost {_bps(friction.get('expected_return_cost_bps'))} / {_euro(friction.get('expected_return_cost_eur'))} | return/cost {_ratio(friction.get('expected_return_cost_ratio'))} | source {friction.get('expected_return_source_dataset', 'forecast_return_distribution')}",
        "These diagnostics are descriptive evidence only; execution_allowed=false.",
    ]
    return panel(ft.Column([section_header("Crowding and attribution", "Configured sector/theme metadata and clean adjusted-price evidence; unavailable values remain N/A."), *[ft.Text(line, color=theme.MUTED, size=11, selectable=True) for line in lines]], spacing=5))


def _format_record_value(value: object) -> str:
    if value is None:
        return "N/A"
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return "N/A"
    except (TypeError, ValueError):
        return "N/A"
    return str(value)


def _render_evidence_badges(value: Mapping[str, object]) -> ft.Control:
    """Render provenance metadata without treating missing values as evidence."""

    def metadata_value(*keys: str) -> str:
        for key in keys:
            candidate = value.get(key)
            if candidate is None:
                continue
            text = str(candidate).strip()
            if text and text.casefold() not in {"<na>", "nan", "nat", "none"}:
                return text
        return "unavailable"

    return ft.Row(
        [
            evidence_chip("Source ID", metadata_value("source_id"), theme.CYAN),
            evidence_chip("Authority", metadata_value("source_authority", "authority"), theme.CYAN),
            evidence_chip("Conflict", metadata_value("conflict_id", "conflict_status"), theme.CYAN),
        ],
        wrap=True,
        spacing=6,
    )


def _render_record_group(label: str, records: object) -> ft.Control:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        records = []
    if not records:
        return ft.Column(
            [
                ft.Text(label, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12),
                ft.Text("No scoped records available.", color=theme.MUTED, size=11, selectable=True),
            ],
            spacing=4,
        )
    lines: list[ft.Control] = [ft.Text(label, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12)]
    for index, record in enumerate(records, start=1):
        if isinstance(record, Mapping):
            details = " | ".join(f"{key}={_format_record_value(value)}" for key, value in record.items())
        else:
            details = _format_record_value(record)
        lines.append(ft.Text(f"{label} {index}: {details or 'unavailable'}", color=theme.MUTED, size=11, selectable=True))
    return ft.Column(lines, spacing=4, scroll=ft.ScrollMode.AUTO)


def _render_evidence_section(
    title: str,
    value: object,
    *,
    subtitle: str = "Canonical local evidence is shown as stored; unavailable values remain explicit.",
    key: str | None = None,
) -> ft.Control:
    if not isinstance(value, dict):
        return panel(ft.Column([section_header(title, subtitle), ft.Text(str(value), color=theme.MUTED, selectable=True)], key=key, spacing=6))
    lines: list[ft.Control] = [_render_evidence_badges(value)]
    for field_name, item in value.items():
        if field_name in {
            "history",
            "rows",
            "entries",
            "signal_rows",
            "trade_rows",
            "changes",
            "document_inventory",
            "statement_history",
            "coverage",
            "pairs",
            "concentrations",
        }:
            lines.append(_render_record_group(str(field_name), item))
            continue
        if isinstance(item, dict):
            compact = ", ".join(f"{child}={child_value if child_value is not None else 'N/A'}" for child, child_value in item.items())
            lines.append(ft.Text(f"{field_name}: {compact or 'unavailable'}", color=theme.MUTED, size=11, selectable=True))
        elif isinstance(item, (list, tuple)):
            if any(isinstance(child, Mapping) for child in item):
                lines.append(_render_record_group(str(field_name), item))
            else:
                lines.append(ft.Text(f"{field_name}: {', '.join(str(child) for child in item) or 'unavailable'}", color=theme.MUTED, size=11, selectable=True))
        else:
            lines.append(ft.Text(f"{field_name}: {item if item is not None else 'N/A'}", color=theme.MUTED, size=11, selectable=True))
    if not lines:
        lines.append(ft.Text("Unavailable", color=theme.MUTED, size=11, selectable=True))
    return panel(ft.Column([section_header(title, subtitle), *lines], key=key, spacing=5))


def _render_etf_order_preview(page: ft.Page | None, state: AppState, instrument_id: str, report: object) -> ft.Control:
    """Render a small local order-size preview without granting execution authority."""

    initial = report if isinstance(report, dict) else {}
    order_field = ft.TextField(
        label="Order value (EUR)",
        value=str(initial.get("order_value_eur", 10_000.0)),
        width=180,
        key="instrument-detail.order-size",
    )


    horizon_field = ft.TextField(
        label="Horizon (days)",
        value=str(initial.get("horizon_days", 1)),
        width=150,
        key="instrument-detail.capacity-horizon",
    )
    result = ft.Text(color=theme.MUTED, selectable=True, size=11)

    def _format_preview(value: dict[str, object]) -> str:
        return (
            f"Capacity: {value.get('capacity_status', 'unavailable')} | "
            f"exchange capacity={value.get('exchange_capacity_eur', 'N/A')} EUR | "
            f"headroom={value.get('capacity_headroom_eur', 'N/A')} EUR | "
            f"estimated cost={value.get('estimated_cost_bps', 'N/A')} bps | "
            f"stressed={value.get('stressed_cost_bps', 'N/A')} bps | "
            "execution_allowed=false"
        )

    result.value = _format_preview(initial)

    def preview(_event: ft.ControlEvent) -> None:
        try:
            order_value = max(0.0, float(order_field.value or 0.0))
            horizon = max(1, int(float(horizon_field.value or 1)))
        except (TypeError, ValueError):
            result.value = "Capacity preview failed: enter a non-negative order value and a positive whole-day horizon."
        else:
            refreshed = build_etf_liquidity_panel(state.snapshot, instrument_id, order_value_eur=order_value, horizon_days=horizon)
            result.value = _format_preview(refreshed)
        if page is not None and hasattr(page, "update"):
            page.update()

    return panel(
        ft.Column(
            [
                section_header("ETF order-preview capacity meter", "Preview only: exchange volume and optional primary-market context remain separate; no order is submitted."),
                ft.Row([order_field, horizon_field, ft.OutlinedButton("Preview capacity", key="instrument-detail.preview-capacity", on_click=preview)], wrap=True),
                result,
            ],
            spacing=6,
        )
    )


def render_event_calendar_panel(model: InstrumentDetailViewModel) -> ft.Control:
    """Render dated events and high-risk warnings as non-executable context."""

    events = model.sections.get("events")
    if not isinstance(events, dict):
        events = {"status": "unavailable", "events": []}
    records = events.get("events", [])
    if events.get("status") != "available" or not records:
        body: ft.Control = ft.Text(str(events.get("message", "Event calendar unavailable.")), color=theme.MUTED, selectable=True)
    else:
        body = ft.Column(
            [
                ft.Text(
                    " | ".join(
                        (
                            f"{item.get('event_type', 'event')}={item.get('event_date', 'unavailable')}",
                            f"title={item.get('title') or 'unavailable'}",
                            f"risk={item.get('risk_level', 'unknown')}",
                            f"source={item.get('source_id', 'unavailable')}",
                            f"authority={item.get('source_authority', 'unavailable')}",
                            f"available_at={item.get('available_at', 'unavailable')}",
                            f"precision={item.get('precision', 'unavailable')}",
                            "context_only=true",
                            "execution_allowed=false",
                        )
                    ),
                    color=theme.AMBER if str(item.get("risk_level", "")).casefold() in {"high", "critical"} else theme.MUTED,
                    selectable=True,
                    size=11,
                )
                for item in records
            ],
            spacing=4,
        )
    return panel(ft.Column([section_header("Event calendar", "Upcoming earnings, dividends, splits and high-risk actions are shown with source and availability metadata; events are context-only."), body], spacing=8))


def instrument_detail_page(page: ft.Page, state: AppState) -> ft.Control:
    route = str(getattr(page, "route", "") or "") if page is not None else ""
    selected = route.split("/", 2)[-1].split("?", 1)[0].split("#", 1)[0] if route.startswith("/instrument/") else state.selected_etf
    if selected:
        state.selected_etf = selected
    model = build_instrument_detail(state.snapshot, selected, candidate_score=getattr(state, "selected_instrument_score", None))
    vintage_history = bitemporal_history_summary(selected) if selected else {"status": "unavailable", "message": "No instrument selected."}
    export_status = ft.Text(
        "Audit evidence export unavailable for this selection."
        if model.status == "unavailable" or not callable(getattr(state, "export_audit_packet", None))
        else str(getattr(state, "last_export_path", "") or "No audit evidence export has been created in this session."),
        color=theme.MUTED,
        selectable=True,
    )
    export_available = model.status != "unavailable" and callable(getattr(state, "export_audit_packet", None))

    def export_instrument_evidence(_event: ft.ControlEvent) -> None:
        if not export_available:
            export_status.value = "Audit evidence export unavailable: canonical evidence or export capability is missing."
        else:
            try:
                path = state.export_audit_packet()
                export_status.value = f"Exported audit evidence: {path}"
            except Exception as exc:
                export_status.value = f"Audit evidence export failed: {type(exc).__name__}. No score authority changed."
        if page is not None and hasattr(page, "update"):
            page.update()

    export_control = ft.OutlinedButton(
        "Export audit evidence",
        key="instrument-detail.export-evidence",
        icon=ft.Icons.DOWNLOAD,
        disabled=not export_available,
        on_click=export_instrument_evidence,
    )
    rows = [
        _render_evidence_section(
            "Classification context",
            model.identity.get(
                "classification",
                {
                    "status": model.identity.get("classification_status", "unavailable"),
                    "reason_code": model.identity.get(
                        "classification_reason_code",
                        "classification_evidence_unavailable",
                    ),
                    "execution_allowed": False,
                },
            ),
            subtitle="Point-in-time asset, sector, industry, strategy and fixed-income look-through with confidence, fallback and invalidation lineage.",
            key="instrument-detail.classification",
        ),
        _render_evidence_section("Price history", model.sections.get("price"), subtitle="Adjusted-price history, latest value/date and freshness."),
        _render_evidence_section("ETF Liquidity", model.sections.get("etf_liquidity"), subtitle="Rolling turnover, spread/gap proxies, zero-volume days, quote/NAV evidence and primary-market context remain explicit."),
        _render_etf_order_preview(page, state, selected, model.sections.get("etf_liquidity")),
        _render_evidence_section("Evidence Score", model.sections.get("scores"), subtitle="Authority score, quality, final label/reason and blocked gates; execution_allowed=false."),
        _render_evidence_section("Risk and feature evidence", model.sections.get("risk"), subtitle="Momentum, trend, relative strength, volatility, drawdown and liquidity/cost."),
        _render_evidence_section("Alpha, beta and correlation", model.sections.get("attribution")),
        _render_evidence_section(
            "Fundamentals",
            model.sections.get("fundamentals"),
            subtitle="Five-section values, statement coverage, source, period, freshness and limitations; execution_allowed=false.",
            key="instrument-detail.fundamentals",
        ),
        _render_evidence_section("ETF holdings and exposure", model.sections.get("etf_holdings")),
        _render_evidence_section(
            "ETF direct overlap",
            model.sections.get("etf_overlap"),
            subtitle="Exact typed identities, dated coverage and unresolved exposure; execution_allowed=false.",
            key="instrument-detail.etf-overlap",
        ),
        _render_evidence_section("Forecast evidence", model.sections.get("forecasts")),
        _render_evidence_section("Backtest trust", model.sections.get("backtests")),
        _render_evidence_section("Paper-trade history", model.sections.get("paper_trades")),
        _render_evidence_section("Decision journal", model.sections.get("journal")),
        _render_evidence_section("What changed since the last run", model.sections.get("run_changes")),
        _render_evidence_section("Point-in-time vintage history", vintage_history, subtitle="Append-only effective and availability timestamps, revisions, corrections and source-vintage metadata."),
    ]
    return ft.Column(
        [
            panel(ft.Column([
                section_header(f"Instrument Detail: {model.display_name}", "Canonical identity, score evidence, data freshness and unavailable states are shown without recalculating authority in the UI."),
                _render_evidence_badges(model.identity),
                _render_record_group(
                    "Identity",
                    [
                        {
                            field: model.identity.get(field)
                            for field in (
                                "instrument_id",
                                "ticker",
                                "isin",
                                "asset_type",
                                "asset_class",
                                "exchange",
                                "currency",
                                "region",
                                "sector",
                                "theme",
                                "identity_resolution_state",
                                "identity_confidence",
                                "identity_decision_id",
                                "source_id",
                                "execution_allowed",
                            )
                            if field in model.identity
                        }
                    ],
                ),
                ft.Row([export_control, export_status], wrap=True),
            ], spacing=8)),
            _render_feature_driver_panel(model.sections.get("feature_drivers")),
            _render_crowding_attribution_panel(model.sections),
            render_etf_disclosure_panel(model),
            render_news_context_panel(model),
            render_event_calendar_panel(model),
            *rows,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
