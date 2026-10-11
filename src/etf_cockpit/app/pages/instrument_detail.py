"""Instrument detail and provenance page."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Mapping, Sequence

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    CardMenu,
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    KpiTile,
    ListRow,
    Note,
    ScoreBar,
    SectionHeader,
    TableColumn,
    Tag,
    VerdictRing,
    Well,
    Segmented,
    field_input_style,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_number, format_timestamp, plain_text
from etf_cockpit.app.pages import stock_page as sp
from etf_cockpit.app.pages._sparebank_view import render_sparebank_workspace
from etf_cockpit.application.alerts import read_local_alerts
from etf_cockpit.application.digest import contradiction_digest_records  # noqa: F401
from etf_cockpit.application.instrument_detail_view import (
    InstrumentDetailViewModel,
    _valuation_panel,
    build_etf_structure_panel,
    build_instrument_detail,
)
from etf_cockpit.application.ui_facade import bitemporal_history_summary, load_market_series_projection
from etf_cockpit.core.paths import ROOT

_MISSING = "\u2014"


def _value(value: object) -> str:
    if value is None:
        return _MISSING
    if isinstance(value, float) and not (value == value and abs(value) != float("inf")):
        return _MISSING
    text = str(value).strip()
    return _MISSING if text.casefold() in {"", "none", "nan", "<na>", "nat"} else text


def _plain_with_code(reason: object) -> str:
    """Plain wording first; the stored reason code stays visible after it so support can still quote it."""

    text, raw = plain_text(reason), str(reason)
    return text if text == raw else f"{text} ({raw})"


def _reason(value: object, title: str) -> str:
    if isinstance(value, Mapping):
        for key in ("unavailable_reason", "message", "reason"):
            candidate = value.get(key)
            if candidate:
                return plain_text(str(candidate).splitlines()[0])
    return f"{title} evidence is unavailable for this instrument."


def _payload(value: object) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True, indent=2)


def _render_evidence_section(
    title: str,
    value: object,
    *,
    subtitle: str = "Canonical local evidence and explicit limitations.",
    key: str | None = None,
    expanded: bool = False,
    extra: Sequence[ft.Control] = (),
) -> ft.Control:
    available = isinstance(value, Mapping) and value.get("status") not in {"unavailable", "missing"}
    if available:
        summary: ft.Control = Note("Evidence is available. The technical records are listed below, collapsed.")
    else:
        summary = KpiTile(title, None, _reason(value, title))
    record_lines: list[str] = []

    def collect_records(node: Mapping[str, object], prefix: str = "") -> None:
        for name, child in node.items():
            path = f"{prefix} / {name}" if prefix else str(name)
            if isinstance(child, Mapping):
                collect_records(child, path)
                continue
            if not isinstance(child, Sequence) or isinstance(child, (str, bytes)):
                record_lines.append(f"{path}: {_value(child)}" if name == "coverage" else f"{path}={_value(child) if _value(child) != _MISSING else 'N/A'}")
                continue
            if not child:
                record_lines.append(f"{path}: unavailable")
                continue
            for index, item in enumerate(child, start=1):
                row_path = f"{path} [{index}]" if " / " in path else f"{path} {index}"
                if isinstance(item, Mapping):
                    scalar = [
                        (field, field_value)
                        for field, field_value in item.items()
                        if not isinstance(field_value, Mapping)
                        and not isinstance(field_value, Sequence)
                        or isinstance(field_value, (str, bytes))
                    ]
                    if scalar and " / " not in path:
                        record_lines.append(f"{row_path}: " + ", ".join(f"{field}={_value(field_value) if _value(field_value) != _MISSING else 'N/A'}" for field, field_value in scalar))
                    elif scalar:
                        record_lines.extend(f"{row_path} / {field}: {field_value}" for field, field_value in scalar)
                    for field, field_value in item.items():
                        if isinstance(field_value, Mapping):
                            collect_records(field_value, f"{row_path} / {field}")
                        elif isinstance(field_value, Sequence) and not isinstance(field_value, (str, bytes)):
                            if not field_value:
                                record_lines.append(f"{row_path} / {field}: unavailable")
                            else:
                                nested = {str(field): field_value}
                                collect_records(nested, row_path)
                else:
                    record_lines.append(f"{row_path}: {item}")

    if isinstance(value, Mapping):
        collect_records(value)
    structured_rows = [ft.Text(line, color=theme.MUTED, selectable=True, size=11) for line in record_lines]
    records = ft.Column(structured_rows, height=320 if len(structured_rows) > 20 else None, scroll=ft.ScrollMode.AUTO)
    body = [summary, *_provenance_tags(value), *extra, Disclosure("Evidence records", records, expanded=expanded), Disclosure("Evidence details", _payload(value))]
    return GlassCard(title, note=subtitle, body=body, key=key)


def _provenance_tags(value: object) -> list[ft.Control]:
    """Source ID / Authority / Conflict badges; missing metadata is shown as unavailable, never as evidence."""

    if not isinstance(value, Mapping):
        return []

    def metadata(*keys: str) -> str:
        for name in keys:
            candidate = _value(value.get(name))
            if candidate != _MISSING:
                return candidate
        return "unavailable"

    if not any(name in value for name in ("source_id", "source_authority", "authority", "conflict_id", "conflict_status")):
        return []
    return [
        ft.Row(
            [
                Tag(f"Source ID {metadata('source_id')}", "mute", dense=True),
                Tag(f"Authority {metadata('source_authority', 'authority')}", "mute", dense=True),
                Tag(f"Conflict {metadata('conflict_id', 'conflict_status')}", "mute", dense=True),
            ],
            wrap=True,
            spacing=theme.SPACE_2,
        )
    ]


def _render_crowding_attribution_panel(sections: Mapping[str, object]) -> ft.Control:
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
        f"Cash comparison: return {attribution.get('cash_return', 'N/A')} | excess {attribution.get('excess_over_cash', 'N/A')} | currency {attribution.get('cash_currency', 'N/A')} | horizon {attribution.get('cash_horizon_years', 'N/A')} | vintage {attribution.get('cash_vintage', 'N/A')} | status {attribution.get('cash_comparison_status', 'unavailable')}",
        f"Sector-relative: return {attribution.get('sector_relative_return', 'N/A')} | alpha {attribution.get('sector_alpha_proxy', 'N/A')} | status {attribution.get('sector_attribution_status', 'N/A')} | theme-relative return {attribution.get('theme_relative_return', 'N/A')} | theme alpha {attribution.get('theme_alpha_proxy', 'N/A')} | theme status {attribution.get('theme_attribution_status', 'N/A')} | source {attribution.get('source_dataset', 'N/A')}",
        f"Gross edge: {_bps(friction.get('gross_expected_edge_bps'))} | Estimated cost: {_bps(friction.get('estimated_total_cost_bps'))} | Net edge: {_bps(friction.get('net_expected_edge_bps'))} | Edge/cost: {_ratio(friction.get('edge_to_cost_ratio'))} | Cost scenario: {friction.get('cost_stress_scenario', 'unavailable')} | status {friction.get('status', 'unavailable')}",
        f"Expected-return distribution ({horizon_text}): q10 {_pct(friction.get('q10_expected_return'))} | q50 {_pct(friction.get('q50_expected_return'))} | q90 {_pct(friction.get('q90_expected_return'))} | net {_pct(friction.get('net_expected_return'))} on {_euro(friction.get('expected_return_order_value_eur'))} | cost {_bps(friction.get('expected_return_cost_bps'))} / {_euro(friction.get('expected_return_cost_eur'))} | return/cost {_ratio(friction.get('expected_return_cost_ratio'))} | source {friction.get('expected_return_source_dataset', 'forecast_return_distribution')}",
        "These diagnostics are descriptive evidence only; execution_allowed=false.",
    ]

    return GlassCard("Crowding and attribution", note="Instrument-scoped, non-executable evidence.", body=[*[ft.Text(line, size=11, selectable=True) for line in lines], Disclosure("Attribution details", _payload(sections))])


_DISCLOSURE_LINES = (
    ("KID", "kid", ("status", "sri", "holding_period_years", "document_date", "extraction_confidence", "source_pages", "warnings", "source_sha256", "parser_version")),
    ("Methodology", "methodology", ("status", "provider", "index_series", "version", "document_date", "confidence", "source_pages", "warnings", "source_sha256", "parser_version")),
    ("Holdings", "holdings", ("completeness", "freshness", "confidence", "source", "authority", "as_of")),
    ("SFDR", "sfdr", ("status", "classification", "document_type", "document_date", "methodology_disclosed", "data_sources_disclosed", "sustainable_characteristics", "taxonomy_alignment_pct", "warnings", "conflict_id", "manual_review", "score_eligible", "execution_allowed")),
)


def _disclosure_metadata(disclosure: Mapping[str, object]) -> str:
    """Document inventory and per-family evidence lines; missing fields read ``unavailable``."""

    lines = [
        f"{row.get('document_type', 'document')}: {row.get('coverage_status', 'unavailable')} | date={row.get('document_date', 'unavailable')} | source={row.get('source', 'unavailable')} | checksum={row.get('checksum', 'unavailable')}"
        for row in disclosure.get("document_inventory", []) or []
        if isinstance(row, Mapping)
    ]
    for label, name, fields in _DISCLOSURE_LINES:
        family = disclosure.get(name)
        family = family if isinstance(family, Mapping) else {}
        lines.append(f"{label} evidence metadata")
        lines.append(f"{label}: " + ", ".join(f"{field}={family.get(field, 'unavailable')}" for field in fields))
    return "\n".join(lines)


def render_etf_disclosure_panel(model: InstrumentDetailViewModel) -> ft.Control:
    section = model.sections.get("etf_disclosures")
    shown = isinstance(section, Mapping) and section.get("status") not in {"unavailable", "missing"}
    return _render_evidence_section(
        "ETF disclosure evidence",
        section,
        subtitle="Document inventory and normalised holdings quality.",
        extra=[Disclosure("Evidence metadata", _disclosure_metadata(section))] if shown else (),
    )


def render_etf_structure_panel(model: InstrumentDetailViewModel) -> ft.Control:
    """Render ETF structure claims with document provenance and explicit limitations."""

    structure = build_etf_structure_panel(model)
    fields = structure.get("fields", {})
    fields = fields if isinstance(fields, Mapping) else {}
    documents = structure.get("documents", {})
    documents = documents if isinstance(documents, Mapping) else {}
    field_lines: list[str] = []
    for field_name, field in fields.items():
        if not isinstance(field, Mapping):
            continue
        field_lines.append(
            f"{field_name}: status={field.get('status', 'unknown')} | value={field.get('value', 'unavailable')} | "
            f"document={field.get('document_id', 'unavailable')} | date={field.get('document_date', 'unavailable')} | "
            f"page={field.get('page', 'unavailable')} | confidence={field.get('confidence', 0.0)} | "
            f"known_at={field.get('known_at', 'unavailable')} | checksum={field.get('checksum', 'unavailable')}"
        )
        if field.get("status") == "conflict":
            candidates = field.get("candidates", ())
            for index, candidate in enumerate(candidates, start=1):
                if not isinstance(candidate, Mapping):
                    continue
                field_lines.append(
                    f"{field_name} conflict candidate {index}: value={candidate.get('value', 'unavailable')} | "
                    f"source_id={candidate.get('source_id', 'unavailable')} | "
                    f"document_id={candidate.get('document_id', candidate.get('source_id', 'unavailable'))} | "
                    f"date={candidate.get('document_date', 'unavailable')} | page={candidate.get('page', 'unavailable')} | "
                    f"confidence={candidate.get('confidence', 0.0)} | known_at={candidate.get('known_at', 'unavailable')} | "
                    f"checksum={candidate.get('checksum', 'unavailable')}"
                )
    document_lines = [
        f"{family}: status={value.get('status', 'unknown')} | source_id={value.get('source_id', 'unavailable')} | "
        f"date={value.get('document_date', 'unavailable')} | version={value.get('version', 'unavailable')} | "
        f"checksum={value.get('checksum', 'unavailable')}"
        for family, value in documents.items()
        if isinstance(value, Mapping)
    ]
    versions = structure.get("versions", ())
    version_lines = [
        f"version {row.get('family', 'document')}: {row.get('version', 'unavailable')} | date={row.get('document_date', 'unavailable')} | source_id={row.get('source_id', 'unavailable')}"
        for row in versions
        if isinstance(row, Mapping)
    ] if isinstance(versions, Sequence) and not isinstance(versions, (str, bytes)) else []
    stress = structure.get("stress", {})
    stress = stress if isinstance(stress, Mapping) else {}
    lines = [
        f"status={structure.get('status', 'unavailable')} | evidence_confidence_cap={structure.get('evidence_confidence_cap', 0.0)} | confidence_version={structure.get('confidence_version', 'unavailable')}",
        f"flags={structure.get('flags', [])} | conflicts={structure.get('conflict_fields', [])} | limitations={structure.get('confidence_limitation', 'unavailable')}",
        f"stress: status={stress.get('status', 'unavailable')} | unsecured={stress.get('unsecured', 'unavailable')} | concentration={stress.get('concentration', 'unavailable')} | formula={stress.get('formula_version', 'unavailable')}",
        "Legal and sustainability labels are context-only; no alpha or expected return is derived from them.",
        "execution_allowed=false",
        *document_lines,
        *version_lines,
        *field_lines,
    ]
    details = ft.Column([ft.Text(line, color=theme.MUTED, selectable=True, size=11) for line in lines], spacing=4)
    return GlassCard(
        "ETF Structure & Documents",
        note="Document-bound structural and legal evidence",
        body=Disclosure("Structure evidence", details),
        key="instrument-detail.etf-structure",
    )


def render_etf_e1_panel(economics: object) -> ft.Control:
    """Readable ETF economics, disclosed holdings and dated NAV splits."""
    payload = economics if isinstance(economics, Mapping) else {}
    fields = payload.get("e1", {})
    tiles = []
    for name, label in (("ter", "TER"), ("tracking_difference", "Tracking difference"), ("aum", "Fund size (AUM)"), ("distribution_policy", "Distribution policy")):
        field = fields.get(name, {})
        value = field.get("value")
        shown = None
        if value is not None:
            if name in {"ter", "tracking_difference"}:
                shown = f"{value:+.2%}" if name == "tracking_difference" else f"{value:.2%}"
            elif name == "aum":
                shown = f"{value:,.0f} {field.get('currency') or '(currency unavailable)'}"
            else:
                shown = str(value).capitalize()
        detail = _plain_with_code(field.get("reason")) if field.get("reason") else (
            f"{plain_text(field.get('source'))} · as of {format_timestamp(field.get('as_of'))} · known {format_timestamp(field.get('known_at'))}"
        )
        if not field:
            detail = _plain_with_code(f"{name}_missing_all_sources")
        if field.get("window"):
            detail += f" · window {field['window']}"
        if field.get("difference"):
            detail += " · sources differ; preferred source shown"
        tiles.append(ft.Column([KpiTile(label, shown, detail, key=f"etf.e1.{name}"), Note(detail)], col={"xs": 12, "md": 6}, spacing=4))
    holdings = payload.get("holdings", [])
    count = payload.get("holdings_count", 0)
    reason = payload.get("holdings_reason") or "holdings_no_dated_source"
    rows = [{"name": row.get("name") or "Name unavailable", "weight": f"{row['weight']:.2%}", "country": row.get("country") or "Other/unclassified", "sector": row.get("sector") or "Other/unclassified"} for row in holdings]
    table = DataTable(
        [TableColumn("name", "Holding", flex=3), TableColumn("weight", "Weight", numeric=True), TableColumn("country", "Country"), TableColumn("sector", "Sector", flex=2)],
        rows, max_visible_rows=25, key="etf.e1.holdings", empty_title="Holdings unavailable", empty_reason=reason,
    )
    return GlassCard(
        "ETF Economics",
        body=[
            ft.ResponsiveRow(tiles, spacing=8, run_spacing=8),
            Note(payload.get("summary") or "ETF economics are unavailable: no dated local evidence."),
            SectionHeader("ETF holdings and exposure"),
            KpiTile("Disclosed holdings", str(count) if holdings else None, f"Top 25 of {count} disclosed rows · as of {payload.get('holdings_as_of')}" if holdings else reason, key="etf.e1.holdings-count"),
            table,
            _render_etf_split("Country split", fields.get("country_split", {}), "etf.e1.country-split"),
            _render_etf_split("Sector split", fields.get("sector_split", {}), "etf.e1.sector-split"),
        ], key="instrument-detail.etf-economics",
    )


def _render_etf_split(title: str, field: Mapping[str, object], key: str) -> ft.Control:
    values = field.get("value")
    values = values if isinstance(values, Mapping) else {}
    # Numbered bars have full, wrapping labels below them; long country and
    # sector names cannot be clipped by the chart's fixed plotting margin.
    entries = list(values.items())
    return GlassCard(title, body=[
        KpiTile(title, f"{sum(name != 'Other/unclassified' for name, _ in entries)} classified buckets" if entries else None, f"{float(values.get('Other/unclassified', 0)):.1%} Other/unclassified" if entries else str(field.get("reason") or "split_no_dated_source")),
        ck.bar_chart([str(index) for index in range(1, len(entries) + 1)], [float(weight) * 100 for _, weight in entries], unit="%", signed_labels=False, width=680, height=260, unavailable_reason=field.get("reason") if not entries else None, empty_title=f"{title} unavailable", insight=title),
        *[Note(f"{index}. {name}: {float(weight):.2%}") for index, (name, weight) in enumerate(entries, 1)],
        Note(f"Source {field.get('source')} · as of {field.get('as_of')} · known {field.get('known_at')}" if entries else str(field.get("reason") or "split_no_dated_source")),
    ], key=key)


def render_news_context_panel(model: InstrumentDetailViewModel) -> ft.Control:
    """Render dated news and manual-note credibility with source provenance."""

    news = model.sections.get("news")
    news = news if isinstance(news, Mapping) else {"status": "unavailable", "items": []}
    items = news.get("items", ())
    item_rows: list[ft.Control] = []
    provenance: list[ft.Control] = []
    if news.get("status") == "available" and isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            headline = str(item.get("headline", "Headline unavailable"))
            source = " | ".join(
                (
                    f"source_url={item.get('source_url', 'unavailable')}",
                    f"published_at={item.get('published_at', 'unavailable')}",
                    f"ingested_at={item.get('ingested_at', 'unavailable')}",
                    f"provider_name={item.get('provider_name', 'unavailable')}",
                    f"credibility={item.get('credibility', 'unverified')}",
                    f"credibility_flag_status={item.get('credibility_flag_status', 'unavailable')}",
                    f"credibility_flags={item.get('credibility_flags', 'unknown')}",
                    f"credibility_reason_codes={item.get('credibility_reason_codes', 'unknown')}",
                    f"instrument_mapping_method={item.get('instrument_mapping_method', 'unavailable')}",
                    f"available_at_decision_time={bool(item.get('available_at_decision_time', False))}",
                    f"timestamp_status={item.get('timestamp_status', 'unavailable')}",
                    "context_only=true",
                    "executable_authority=false",
                )
            )
            item_rows.append(
                ListRow(
                    theme.MUTED,
                    headline,
                    f"{item.get('published_at', 'Date unavailable')} · {item.get('provider_name', 'Source unavailable')}",
                    tag=Tag(str(item.get("direction", "context")), "mute"),
                    last=index == len(items) - 1,
                )
            )
            provenance.append(ft.Text(f"{headline} | {source}", color=theme.MUTED, selectable=True, size=11))
    if not item_rows:
        body: list[ft.Control] = [
            EmptyState("No point-in-time news", str(news.get("message", "News unavailable for this instrument.")))
        ]
    else:
        body = [*item_rows, Disclosure("News source and credibility details", ft.Column(provenance, spacing=4))]
    return GlassCard(
        "News & context",
        note="Dated evidence · context only",
        body=body,
        key="instrument-detail.news-context",
    )


def render_news_contradiction_panel(model: InstrumentDetailViewModel) -> ft.Control:
    """Render only validated point-in-time contradiction records from the selector."""

    news = model.sections.get("news")
    news = news if isinstance(news, Mapping) else {}
    supplied = news.get("contradictions")
    cutoff = news.get("contradiction_cutoff")

    def valid_record(item: object) -> bool:
        if not isinstance(item, Mapping) or item.get("status") not in {"available", "manual_review", "unavailable"}:
            return False
        contradiction = item.get("contradiction")
        return (
            isinstance(contradiction, Mapping)
            and bool(contradiction.get("rule"))
            and item.get("rule_status") == contradiction.get("status")
            and contradiction.get("execution_allowed") is False
        )

    results = [item for item in supplied if valid_record(item)] if isinstance(supplied, (list, tuple)) and cutoff else []
    rows: list[ft.Control] = []
    details: list[ft.Control] = []
    for index, result in enumerate(results):
        status = str(result.get("rule_status", result.get("status", "unavailable")))
        kind = "ok" if status == "clear" else "warn" if status == "manual_review" else "mute"
        dot = theme.GREEN if status == "clear" else theme.AMBER if status == "manual_review" else theme.MUTED
        title = str(result.get("title", "contradiction"))
        detail = str(result.get("detail", "unavailable"))
        rows.append(ListRow(dot, title, detail, tag=Tag(status, kind), last=index == len(results) - 1))
        details.append(ft.Text(f"{title}: status={status} | {detail}", color=theme.MUTED, selectable=True, size=11))
    if not rows:
        rows = [ListRow(theme.MUTED, "No contradiction rule results are available.", last=True)]
    body = list(rows)
    if details:
        body.append(Disclosure("Contradiction evidence", ft.Column(details, spacing=4)))
    return GlassCard(
        "News/macro contradictions",
        note="Point-in-time · informational",
        body=body,
        key="instrument-detail.news-contradictions",
    )


def render_event_calendar_panel(model: InstrumentDetailViewModel) -> ft.Control:
    """Render event dates with source and availability metadata as context only."""

    events = model.sections.get("events")
    events = events if isinstance(events, Mapping) else {"status": "unavailable", "events": []}
    records = events.get("events", ())
    rows: list[ft.Control] = []
    details: list[ft.Control] = []
    if events.get("status") == "available" and isinstance(records, Sequence) and not isinstance(records, (str, bytes)):
        valid_records = [item for item in records if isinstance(item, Mapping)]
        for index, item in enumerate(valid_records):
            risk = str(item.get("risk_level", "unknown"))
            high_risk = risk.casefold() in {"high", "critical"}
            rows.append(
                ListRow(
                    theme.AMBER if high_risk else theme.MUTED,
                    f"{item.get('event_type', 'event')} · {item.get('event_date', 'unavailable')}",
                    str(item.get("title") or "Event title unavailable"),
                    tag=Tag(risk, "warn" if high_risk else "mute"),
                    last=index == len(valid_records) - 1,
                )
            )
            details.append(
                ft.Text(
                    " | ".join(
                        (
                            f"{item.get('event_type', 'event')}={item.get('event_date', 'unavailable')}",
                            f"title={item.get('title') or 'unavailable'}",
                            f"risk={risk}",
                            f"source={item.get('source_id', 'unavailable')}",
                            f"authority={item.get('source_authority', 'unavailable')}",
                            f"source_url={item.get('source_url', 'unavailable')}",
                            f"timezone_name={item.get('timezone_name', 'unavailable')}",
                            f"available_at={item.get('available_at', 'unavailable')}",
                            f"available_at_decision_time={item.get('available_at_decision_time', False)}",
                            f"decision_time={item.get('decision_time', events.get('decision_time', 'unavailable'))}",
                            f"precision={item.get('precision', 'unavailable')}",
                            "context_only=true",
                            "execution_allowed=false",
                        )
                    ),
                    color=theme.MUTED,
                    selectable=True,
                    size=11,
                )
            )
    if not rows:
        rows = [EmptyState("Unavailable", str(events.get("message", "Event calendar unavailable.")))]
    body = list(rows)
    if details:
        body.append(Disclosure("Event source and timing details", ft.Column(details, spacing=4)))
    return GlassCard(
        "Event calendar",
        note="Dated events · context only",
        body=body,
        key="instrument-detail.event-calendar",
    )


def _instrument_id(page: ft.Page | None, state: object) -> str:
    route = str(getattr(page, "route", "") or "") if page is not None else ""
    if route.startswith("/instrument/") or route.startswith("/etf/"):
        selected = route.split("/", 2)[-1].split("?", 1)[0].split("#", 1)[0]
        if selected:
            return selected
    selected = str(getattr(state, "selected_etf", "") or "").strip()
    if selected:
        return selected
    snapshot = getattr(state, "snapshot", None)
    config = getattr(snapshot, "config", None)
    return str(getattr(getattr(config, "ui", None), "default_etf", "") or "")


def _instrument_ids(snapshot: object, selected: str) -> list[str]:
    values: list[str] = []
    universe = getattr(getattr(getattr(snapshot, "config", None), "universe", None), "etfs", ())
    for item in universe or ():
        identifier = getattr(item, "id", None)
        if identifier:
            values.append(str(identifier))
    for item in getattr(snapshot, "signals", ()) or ():
        identifier = getattr(item, "etf_id", None) or getattr(item, "display_id", None)
        if identifier:
            values.append(str(identifier))
    unique = list(dict.fromkeys(values))
    if selected and selected not in unique:
        unique.insert(0, selected)
    unique = unique[:3]
    if selected and selected not in unique:
        unique[-1] = selected
    return unique


def _model_for(state: object, selected: str) -> InstrumentDetailViewModel:
    snapshot = getattr(state, "snapshot", None)
    if snapshot is None or not selected:
        return InstrumentDetailViewModel(
            selected,
            "",
            "unavailable",
            {"instrument_id": selected},
            {},
        )
    return build_instrument_detail(
        snapshot,
        selected,
        candidate_score=getattr(state, "selected_instrument_score", None),
        financial_projection=getattr(state, "financial_projection", None),
        real_asset_projection=getattr(state, "real_asset_projection", None),
        cyclical_projection=getattr(state, "cyclical_projection", None),
        cyclical_source_digest=getattr(state, "cyclical_source_digest", None),
        innovation_projection=getattr(state, "innovation_projection", None),
        innovation_source_digest=getattr(state, "innovation_source_digest", None),
    )


def _price_chart(
    model: InstrumentDetailViewModel,
    state: object,
    basis: str,
    currency: str,
    range_name: str,
    mode: str,
) -> ft.Control:
    snapshot = getattr(state, "snapshot", None)
    local_currency = str(model.identity.get("currency") or "")
    projection = load_market_series_projection(
        getattr(snapshot, "prices", None),
        model.instrument_id,
        basis=basis,
        local_currency=local_currency,
        output_currency=currency or local_currency,
        decision_time=getattr(getattr(snapshot, "data_report", None), "as_of_date", None),
    )
    frame = projection.get("frame")
    fallback_note = None
    if basis != "raw" and projection.get("reason_code") == "corporate_action_coverage_unavailable":
        # The adjusted basis needs verified corporate-action coverage; show the raw close instead of nothing.
        projection = load_market_series_projection(
            getattr(snapshot, "prices", None),
            model.instrument_id,
            basis="raw",
            local_currency=local_currency,
            output_currency=currency or local_currency,
            decision_time=getattr(getattr(snapshot, "data_report", None), "as_of_date", None),
        )
        frame = projection.get("frame")
        fallback_note = "Showing raw close: the adjusted series needs verified corporate-action coverage."
    if projection.get("status") != "available" or frame is None or frame.empty:
        return EmptyState(
            "Unavailable",
            "No complete local price series is available for the selected basis and currency.",
        )
    if range_name != "All" and "date" in frame.columns:
        months = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}[range_name]
        dates = pd.to_datetime(frame["date"], errors="coerce", utc=True)
        latest = dates.max()
        if pd.notna(latest):
            frame = frame.loc[dates >= latest - pd.DateOffset(months=months)]
    rows = frame.to_dict(orient="records")
    x_values = [str(row.get("date", "")) for row in rows]
    if mode == "Candles":
        price_rows = getattr(snapshot, "prices", None)
        if isinstance(price_rows, pd.DataFrame):
            identifier = "etf_id" if "etf_id" in price_rows.columns else "instrument_id"
            if identifier in price_rows.columns:
                price_rows = price_rows.loc[
                    price_rows[identifier].astype(str).eq(model.instrument_id)
                ]
            else:
                price_rows = pd.DataFrame()
        else:
            price_rows = pd.DataFrame()
        if price_rows.empty or not {"date", "open", "high", "low", "close", "volume"}.issubset(price_rows.columns):
            return EmptyState(
                "Unavailable",
                "Daily OHLC and volume are unavailable in the local price evidence.",
            )
        candle_rows = price_rows.set_index(price_rows["date"].astype(str)).reindex(x_values)
        candle_dates = list(candle_rows["date"].astype(str)) if "date" in candle_rows else []
        if not candle_dates or candle_rows["volume"].isna().all():
            return EmptyState(
                "Unavailable",
                "Daily OHLC or volume observations are unavailable for the selected range.",
            )
        price_series = [
            ck.Series(name.title(), pd.to_numeric(candle_rows[name], errors="coerce").where(pd.notna(candle_rows[name]), None).tolist(), color=color)
            for name, color in (("open", theme.INK2), ("high", theme.GREEN), ("low", theme.RED), ("close", theme.CYAN))
        ]
        return ft.Column(
            [
                Note("Daily OHLC values shown as lines; the chart kit has no candlestick primitive."),
                ck.line_chart(
                    candle_dates,
                    price_series,
                    x_name="Date",
                    y_name=f"Price ({local_currency or 'local currency'})",
                    insight="Daily raw open, high, low and close from local price evidence.",
                ),
                ck.bar_chart(
                    candle_dates,
                    pd.to_numeric(candle_rows["volume"], errors="coerce").where(pd.notna(candle_rows["volume"]), None).tolist(),
                    x_name="Date",
                    y_name="Volume (shares)",
                    unit="shares",
                    unavailable_reason="Daily volume observations are unavailable for the selected range."
                    if candle_rows["volume"].isna().all()
                    else None,
                ),
            ],
            spacing=8,
        )
    values = [row.get("series_value") for row in rows]
    valid = [value for value in values if isinstance(value, (int, float)) and value == value]
    if not x_values or not valid:
        return ck.line_chart(
            [],
            [],
            x_name="Date",
            y_name=f"Price ({currency})",
            unavailable_reason="No numeric observations are available for the selected price series.",
            insight="Price history is unavailable.",
        )
    parsed = pd.to_datetime(pd.Series(x_values), errors="coerce")
    # Real dates give a time axis with short, spaced labels instead of overlapping timestamp strings.
    chart_x = [value.date() for value in parsed] if parsed.notna().all() else x_values
    chart = ck.line_chart(
        chart_x,
        [ck.Series("Raw close" if fallback_note else "Adjusted close", values, color=theme.CYAN, glow=True, area=True)],
        x_name="Date",
        y_name=f"Price ({currency})",
        insight=f"Price history across {len(valid)} stored observations.",
    )
    return ft.Column([Note(fallback_note), chart], spacing=8) if fallback_note else chart


def _forecast_chart(forecasts: object) -> ft.Control:
    rows = forecasts.get("rows", ()) if isinstance(forecasts, Mapping) else ()
    rows = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, Sequence) else []
    complete = [
        row
        for row in rows
        if row.get("horizon_days") is not None
        if all(isinstance(row.get(key), (int, float)) for key in ("q10", "q50", "q90"))
        and row.get("q10") <= row.get("q50") <= row.get("q90")
    ]
    if not complete:
        return EmptyState(
            "No forecast fan",
            "No complete ordered q10/q50/q90 distribution is stored for this instrument; a fan chart is not drawn and missing quantiles are never filled.",
        )
    horizons = [row.get("horizon_days") for row in complete]
    lower = [row["q10"] for row in complete]
    median = [row["q50"] for row in complete]
    upper = [row["q90"] for row in complete]
    return ck.line_chart(
        horizons,
        [ck.Series("q50", median, color=theme.CYAN, glow=True)],
        bands=[ck.Band("80% range", lower, upper, color=theme.CYAN)],
        x_name="Horizon (days)",
        y_name="Expected return (%)",
        insight=f"Stored quantiles cover {len(complete)} horizons.",
    )


def _price_card(
    model: InstrumentDetailViewModel,
    state: object,
    page: ft.Page | None,
) -> ft.Control:
    local_currency = str(model.identity.get("currency") or "")
    base_currency = str(
        getattr(getattr(getattr(state, "snapshot", None), "config", None), "targets", None)
        and state.snapshot.config.targets.base_currency
        or local_currency
    )
    currencies = list(dict.fromkeys(value for value in (local_currency, base_currency) if value))
    settings = {"basis": "adjusted", "currency": local_currency, "range": "All", "mode": "Line"}
    well = Well(
        _price_chart(model, state, settings["basis"], settings["currency"], settings["range"], settings["mode"]),
        expand=True,
        key="instrument-detail.price-series",
    )
    card_ref: dict[str, ft.Control] = {}

    def update_chart() -> None:
        well.content = _price_chart(
            model,
            state,
            settings["basis"],
            settings["currency"],
            settings["range"],
            settings["mode"],
        )
        card = card_ref.get("card")
        note = getattr(card, "data", {}).get("note_control") if card is not None else None
        if note is not None:
            note.value = (
                f"{local_currency or 'local currency'} · raw OHLC and volume"
                if settings["mode"] == "Candles"
                else f"{settings['currency']} · {settings['basis']} close"
            )
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    def change_mode(value: str) -> None:
        settings["mode"] = value
        update_chart()

    def choose_basis(value: str) -> None:
        settings["basis"] = value
        update_chart()

    def choose_currency(value: str) -> None:
        settings["currency"] = value
        update_chart()

    def choose_range(value: str):
        def select(_event: ft.ControlEvent | None = None) -> None:
            settings["range"] = value
            update_chart()
        return select

    menu = CardMenu(
        [(value, choose_range(value)) for value in ("1M", "3M", "6M", "1Y", "All")]
    )
    card = GlassCard(
        "Price history",
        note=f"{_value(settings['currency'])} · adjusted close",
        insight="Price history from the selected stored price series.",
        body=[
            ft.ResponsiveRow(
                [
                    Field(
                        "Price basis",
                        value=settings["basis"],
                        options=["raw", "adjusted", "total_return"],
                        on_change=choose_basis,
                        key="instrument-detail.price-basis",
                    ),
                    Field(
                        "Currency",
                        value=settings["currency"],
                        options=currencies,
                        on_change=choose_currency,
                        key="instrument-detail.price-currency",
                    ),
                ],
                spacing=8,
                run_spacing=8,
            ),
            Segmented(["Line", "Candles"], "Line", on_change=change_mode),
            well,
            Disclosure(
                "Price-series details",
                _payload(model.sections.get("price")),
            ),
        ],
        menu=menu,
        expand=True,
    )
    card_ref["card"] = card
    return card


def _export_controls(model: InstrumentDetailViewModel, state: object, page: ft.Page | None) -> tuple[ft.Control, ft.Text]:
    """The audit-evidence export button and its status line (shared by every instrument kind)."""

    can_export = model.status != "unavailable" and callable(getattr(state, "export_audit_packet", None))
    status = Note("No audit evidence export has been created in this session.")

    def export_instrument_evidence(_event: ft.ControlEvent | None = None) -> None:
        exporter = getattr(state, "export_audit_packet", None)
        if not can_export or not callable(exporter):
            status.value = "Audit evidence export is unavailable for this selection."
        else:
            try:
                exporter()
                status.value = "Exported audit evidence."
            except Exception:
                status.value = "Audit evidence export could not be created."
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    button = Button.secondary(
        "Export audit evidence",
        on_click=export_instrument_evidence,
        disabled=not can_export,
        disabled_reason="Canonical evidence or export capability is missing.",
        key="instrument-detail.export-evidence",
    )
    return button, status


def _identity_card(
    model: InstrumentDetailViewModel,
    state: object,
    page: ft.Page | None,
    instrument_ids: Sequence[str],
    on_instrument_change: object,
) -> ft.Control:
    identity = model.identity
    source_id = identity.get("source_id")
    authority = identity.get("source_authority", identity.get("authority"))
    conflict = identity.get("conflict_id", identity.get("conflict_status"))
    rows = [
        {"field": label, "value": "—" if key == "exchange" and _value(identity.get(key)).casefold() == "unavailable" else _value(identity.get(key))}
        for key, label in (
            ("instrument_id", "instrument_id"),
            ("ticker", "ticker"),
            ("isin", "ISIN"),
            ("asset_type", "asset type"),
            ("asset_class", "asset class"),
            ("exchange", "exchange"),
            ("currency", "currency"),
            ("region", "region"),
            ("sector", "sector"),
            ("theme", "theme"),
        )
    ]
    export_button, status = _export_controls(model, state, page)

    return GlassCard(
        "Identity and provenance",
        note="canonical identity",
        body=[
            *(
                [
                    Field(
                        "Instrument",
                        value=model.instrument_id,
                        options=instrument_ids,
                        on_change=on_instrument_change,
                        key="instrument-detail.instrument",
                    )
                ]
                if instrument_ids
                else []
            ),
            ft.ResponsiveRow(
                [
                    KpiTile(
                        "Source ID",
                        _value(source_id) if source_id is not None else None,
                        "Canonical source identifier" if source_id is not None else "Source identifier is unavailable.",
                    ),
                    KpiTile(
                        "Authority",
                        _value(authority) if authority is not None else None,
                        "Recorded source authority" if authority is not None else "Source authority is unavailable.",
                    ),
                    KpiTile(
                        "Conflict",
                        _value(conflict) if conflict is not None else None,
                        "Identity conflict evidence" if conflict is not None else "No conflict evidence is available.",
                    ),
                ],
                spacing=8,
                run_spacing=8,
            ),
            DataTable(
                [TableColumn("field", "Field"), TableColumn("value", "Value")],
                rows,
                empty_title="Unavailable",
                empty_reason="Identity fields are unavailable.",
            ),
            *(
                [Note("Exchange is unavailable in local identity evidence.")]
                if _value(identity.get("exchange")).casefold() in {"unavailable", "—"}
                else []
            ),
            export_button,
            status,
            Note("Research context only · execution_allowed=false."),
            Disclosure(
                "Export details",
                str(getattr(state, "last_export_path", "") or "No export path is available."),
            ),
        ],
        expand=True,
    )


def _listed_score(state: object, instrument_id: str) -> object | None:
    """The instrument's row in the canonical score list, so the headline matches every other page."""

    from etf_cockpit.application.score_views import snapshot_scores

    try:
        rows = snapshot_scores(getattr(state, "snapshot", None))
    except Exception:  # the card falls back to the detail model's own score
        return None
    return next((row for row in rows if str(getattr(row, "display_id", "")) == str(instrument_id)), None)


def _score_card(model: InstrumentDetailViewModel, page: ft.Page | None, state: object = None) -> ft.Control:
    score = model.sections.get("scores")
    score = score if isinstance(score, Mapping) else {}
    raw_score = score.get("evidence_score")
    listed = _listed_score(state, model.instrument_id) if state is not None else None
    listed_score = getattr(listed, "final_score_10", None)
    if isinstance(listed_score, (int, float)):
        raw_score = float(listed_score)
    scorecard_owned = str(getattr(listed, "final_label", "") or "").casefold() == "scorecard_owned"
    ring_score = raw_score * 10 if isinstance(raw_score, (int, float)) else None
    component_keys = (
        ("canonical_attractiveness_10", "Attractiveness"),
        ("canonical_expected_return_10", "Expected return"),
        ("canonical_risk_implementation_10", "Risk / implementation"),
        ("canonical_evidence_confidence_10", "Evidence confidence"),
        ("canonical_coverage", "Coverage"),
    )
    from etf_cockpit.application.score_views import confidence_cap_note, score_card_values

    # One canonical value path: when the instrument is in the score list, every number comes from that row.
    values = score_card_values(listed) if listed is not None else score
    bars = [
        ft.Row(
            [
                Note(label),
                ScoreBar(values.get(key) if isinstance(values.get(key), (int, float)) else None),
            ],
            spacing=8,
        )
        for key, label in component_keys
    ]
    if listed is not None:
        quality = values.get("evidence_quality_10")
        bars.append(ft.Row([Note("Evidence quality"), ScoreBar(quality if isinstance(quality, (int, float)) else None)], spacing=8))
        bars.append(Note(f"Components: {values['valid_components']} of {values['total_components']} usable"))
        cap_note = confidence_cap_note(values)
        if cap_note:
            bars.append(Note(cap_note))
    if scorecard_owned:
        bars = [
            Note(
                "Generic components do not apply: banks are scored on the Sparebank scorecard axes. "
                "See the bank workspace below for the per-axis breakdown and coverage."
            )
        ]

    def open_scores(_event: ft.ControlEvent | None = None) -> None:
        if page is not None and callable(getattr(page, "go", None)):
            page.go("/signals")

    return GlassCard(
        "Evidence score",
        note="Canonical score evidence",
        body=[
            VerdictRing(ring_score, caption="of 10", value_text=None if ring_score is None else f"{raw_score:.1f}"),
            KpiTile(
                "Evidence score",
                format_number(raw_score, decimals=1, unavailable="Unavailable")
                if raw_score is not None
                else None,
                _reason(score, "Evidence score")
                if raw_score is None
                else str(getattr(listed, "one_line_reason", "") or "Canonical score evidence."),
            ),
            *bars,
            Button.secondary(
                "Open in Scores",
                on_click=open_scores,
                key="instrument-detail.open-scores",
            ),
        ],
        expand=True,
    )


def _alerts_card(model: InstrumentDetailViewModel, state: object) -> ft.Control:
    snapshot = getattr(state, "snapshot", None)
    as_of = getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    if as_of is not None and len(str(as_of)) == 10:
        as_of = f"{as_of}T23:59:59+00:00"
    readback = read_local_alerts(ROOT, subject_id=model.instrument_id, as_of=as_of)
    records = readback.records
    rows = [
        ListRow(
            "info",
            _value(getattr(item, "title", None) or getattr(item, "alert_id", None)),
            _value(getattr(item, "reason", None) or getattr(item, "message", None)),
            last=index == len(records) - 1,
        )
        for index, item in enumerate(records)
    ]
    details = [
        Disclosure(
            "Alert audit",
            f"type={item.alert.alert_type.value}\nseverity={item.alert.severity.value}\n"
            f"execution_allowed={str(item.alert.execution_allowed).lower()}",
        )
        for item in records
    ]
    if readback.status != "available":
        rows = [Note("Alerts unavailable · manual review required.")]
        details = []
    elif not records:
        rows = [Note("No local alerts or review reminders for this instrument.")]
    content = ft.Column([*rows, *details], spacing=theme.SPACE_2)
    return GlassCard(
        "Alerts & review reminders",
        note="instrument-scoped · informational",
        body=content,
        expand=True,
    )


def _instrument_alerts_panel(model: InstrumentDetailViewModel, state: object) -> ft.Control:
    """Keep the page-level alert seam pointed at its canonical card renderer."""

    return _alerts_card(model, state)


def _section_card(title: str, value: object, key: str | None = None) -> ft.Control:
    return _render_evidence_section(title, value, key=key)


def _driver_value(value: object, *, missing: str = "unavailable") -> str:
    if value is None:
        return missing
    if isinstance(value, float) and not math.isfinite(value):
        return missing
    text = str(value).strip()
    if text.casefold() in {"", "nan", "none", "<na>", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        return missing
    return text


def _driver_table(label: str, rows: list[dict[str, object]]) -> ft.Control:
    columns = [
        "Component", "Score", "Direction", "Peer group", "Peer percentile", "Historical contribution",
        "Coverage", "Uncertainty", "Interaction", "Counterfactual sensitivity",
        "Authority", "Source authority", "Freshness", "Source span", "Source vintage hash", "Claim hash", "Missingness", "Conflict", "Contribution", "Driver",
    ]
    if not rows:
        return ft.Column(
            [ft.Text(label, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12), Note("Unavailable")],
            spacing=4,
        )
    table_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(_driver_value(row.get("component")), color=theme.TEXT)),
                ft.DataCell(ft.Text(_driver_value(row.get("normalised_score"), missing="N/A"), color=theme.CYAN)),
                ft.DataCell(ft.Text(_driver_value(row.get("direction")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("peer_group")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("peer_percentile")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("historical_contribution")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("coverage")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("uncertainty")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("interaction")), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(_driver_value(row.get("counterfactual_sensitivity")), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(_driver_value(row.get("authority")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("source_authority")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("freshness_status")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("source_span")), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(_driver_value(row.get("source_vintage_hash")), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(_driver_value(row.get("claim_hash")), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(_driver_value(row.get("missingness")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("conflict")), color=theme.MUTED, selectable=True)),
                ft.DataCell(ft.Text(_driver_value(row.get("contribution")), color=theme.MUTED)),
                ft.DataCell(ft.Text(_driver_value(row.get("driver_text")), color=theme.MUTED, selectable=True)),
            ]
        )
        for row in rows
    ]
    return ft.Column(
        [
            ft.Text(label, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12),
            ft.Row(
                [ft.DataTable(columns=[ft.DataColumn(ft.Text(column, color=theme.TEXT)) for column in columns], rows=table_rows)],
                scroll=ft.ScrollMode.AUTO,
            ),
        ],
        spacing=4,
    )


def _render_sparebank_workspace(workspace: object, *, page: ft.Page | None = None) -> ft.Control:
    """The Sparebank EC workspace; layout and formatting live in ``_sparebank_view`` (no UI-side calculations)."""

    return render_sparebank_workspace(workspace, root=ROOT, page=page)


def _render_opportunity_card(value: object) -> ft.Control:
    opportunity = value if isinstance(value, Mapping) else {}
    percentile = opportunity.get("percentile")
    percentile_text = f"{float(percentile):.1f}%" if isinstance(percentile, (int, float)) else "unavailable"
    domain_scores = opportunity.get("domain_scores", ())
    domain_line = ", ".join(
        f"{row[0]}={row[1] if row[1] is not None else 'unavailable'}"
        for row in domain_scores
        if isinstance(row, (tuple, list)) and len(row) == 2
    ) or "unavailable"
    driver_lines = []
    for label, field in (("Positive drivers", "positive_drivers"), ("Negative drivers", "negative_drivers")):
        rows = opportunity.get(field, ())
        summaries = [
            f"{row.get('metric_id', 'unavailable')} (z={row.get('z_score', 'unavailable')})"
            for row in rows
            if isinstance(row, Mapping)
        ]
        driver_lines.append(Note(f"{label}: {', '.join(summaries) or 'unavailable'}"))
    content = ft.Column(
        [
            Tag(str(opportunity.get("status", "Insufficient Evidence")), "mute"),
            Note(f"Universe rank: {opportunity.get('universe_rank', 'unavailable')}/{opportunity.get('universe_support', 'unavailable')} | Percentile: {percentile_text}"),
            Note(f"Peer: {opportunity.get('peer_id', 'unavailable')} | Peer rank: {opportunity.get('peer_rank', 'unavailable')}/{opportunity.get('peer_support', 'unavailable')} | Peer percentile: {opportunity.get('peer_percentile', 'unavailable')}"),
            Note(f"Domains: {domain_line}"),
            Note(f"Confidence: {opportunity.get('confidence', 'unavailable')} | Coverage: {opportunity.get('coverage', 'unavailable')}"),
            *driver_lines,
            Note(f"Timing: {opportunity.get('timing', 'Insufficient')}"),
            Note(str(opportunity.get("explanation", "Domain evidence is unavailable."))),
            Disclosure("Opportunity evidence", _payload(value)),
        ],
        key="instrument-detail.opportunity",
        spacing=theme.SPACE_1,
    )
    card = GlassCard(
        "Opportunity",
        note="Point-in-time universe and peer rank; timing remains separate",
        body=content,
        key="instrument-detail.opportunity-card",
    )
    if card.content is not None:
        card.content.key = "instrument-detail.opportunity"
    return card


def _feature_driver_chart(value: object) -> ft.Control:
    rows = value.get("rows", ()) if isinstance(value, Mapping) else ()
    rows = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, Sequence) else []
    chart_rows = [
        row for row in rows
        if isinstance(row.get("contribution"), (int, float))
        and pd.notna(row.get("contribution"))
    ]
    chart: ft.Control
    if chart_rows:
        chart_rows = chart_rows[:12]
        chart = ck.bar_chart(
            [str(row.get("component") or "—") for row in chart_rows],
            [float(row["contribution"]) for row in chart_rows],
            x_name="Feature driver",
            y_name="Contribution (score points)",
            unit="score points",
            unavailable_reason="No numeric feature driver contributions are available.",
        )
    else:
        chart = EmptyState("Unavailable", _reason(value, "Feature driver chart"))
    categories = (
        ("Top positive", "top_positive", theme.GREEN, "ok"),
        ("Top negative", "top_negative", theme.RED, "bad"),
        ("Missing / N/A", "missing_or_na", theme.MUTED, "mute"),
        ("Low authority", "low_authority", theme.AMBER, "warn"),
        ("Stale / partial", "stale_or_partial", theme.AMBER, "warn"),
    )
    category_rows: list[ft.Control] = []
    for label, key, dot, tag_kind in categories:
        entries = value.get(key, ()) if isinstance(value, Mapping) else ()
        entries = [entry for entry in entries if isinstance(entry, Mapping)] if isinstance(entries, Sequence) else []
        category_rows.append(SectionHeader(label, f"{len(entries)} stored rows"))
        if entries:
            category_rows.extend(
                ListRow(
                    dot,
                    _driver_value(entry.get("component")),
                    _driver_value(entry.get("driver_text"), missing="Evidence detail unavailable"),
                    tag=Tag(label, tag_kind),
                    last=index == len(entries) - 1,
                )
                for index, entry in enumerate(entries)
            )
        else:
            category_rows.append(Note("No evidence rows in this category."))
    return GlassCard(
        "Feature drivers",
        note="Diverging contribution and evidence quality",
        body=[
            chart,
            *category_rows,
            Disclosure("Complete driver fields", _driver_table("Feature driver rows", rows)),
            Disclosure("Feature driver provenance", _payload(value)),
        ],
        key="instrument-detail.feature-drivers",
    )


def _render_feature_driver_panel(panel_data: object) -> ft.Control:
    """Compatibility name for the canonical feature-driver card renderer."""

    return _feature_driver_chart(panel_data)


def _score_history_chart(value: object) -> ft.Control:
    rows = value.get("rows", ()) if isinstance(value, Mapping) else ()
    rows = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, Sequence) else []
    date_key = next((key for key in ("run_completed_at", "run_started_at", "data_as_of_date") if any(row.get(key) for row in rows)), None)
    score_key = next((key for key in ("final_combined_score_10", "evidence_score_10") if any(isinstance(row.get(key), (int, float)) and pd.notna(row.get(key)) for row in rows)), None)
    chart_rows = [row for row in rows if date_key and score_key and row.get(date_key) and isinstance(row.get(score_key), (int, float)) and pd.notna(row.get(score_key))]
    if not chart_rows:
        return GlassCard(
            "Score history",
            body=EmptyState("Unavailable", _reason(value, "Score history chart")),
            key="instrument-detail.score-history",
        )
    return GlassCard(
        "Score history",
        note="Stored score history",
        body=[
            ck.line_chart(
                [str(row[date_key]) for row in chart_rows],
                [ck.Series("Score", [float(row[score_key]) for row in chart_rows], color=theme.CYAN, glow=True)],
                x_name="Run date",
                y_name="Score (0–10)",
                insight=f"{len(chart_rows)} stored score observations.",
            ),
            Disclosure("Score history evidence", _payload(value)),
        ],
        key="instrument-detail.score-history",
    )


def _render_valuation_scenarios(
    page: ft.Page | None,
    model: InstrumentDetailViewModel,
    decision_time: object,
    *,
    session_active: object = None,
) -> ft.Control:
    """Keep scenario assumptions in the active page-owned dialog session."""

    initial = model.sections.get("valuation")
    if str(model.identity.get("asset_type", "")).casefold() not in {"stock", "equity"}:
        return _render_evidence_section("Stock valuation and scenarios", initial)

    def render(projection: object) -> ft.Control:
        return _render_evidence_section(
            "Stock valuation and scenarios",
            projection,
            subtitle="Relative valuation, intrinsic value, reverse DCF and residual income; dated source lineage; execution_allowed=false.",
            key="instrument-detail.valuation",
            expanded=True,
        )

    result = ft.Container(content=render(initial))

    def active() -> bool:
        return not callable(session_active) or bool(session_active())

    def refresh() -> None:
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    def invalidate_valuation(_event: ft.ControlEvent | None = None) -> None:
        if active():
            result.content = render(
                {
                    "status": "unavailable",
                    "message": "Inputs changed. Preview valuation scenarios to calculate current inputs.",
                    "execution_allowed": False,
                }
            )
            refresh()

    labels = {
        "forecast_years": "Forecast years (1-50)",
        "discount_rate": "Discount rate (%) >0 to 100",
        "terminal_growth": "Terminal growth (%)",
        "bear": "Bear growth (%) >=-50",
        "base": "Base growth (%)",
        "bull": "Bull growth (%) <=100",
    }

    inputs = {
        name: ft.TextField(
            label=label,
            value="",
            col={"xs": 12, "sm": 6},
            autofocus=name == "forecast_years",
            on_change=invalidate_valuation,
            key=f"instrument-detail.valuation-input.{name}",
            **field_input_style(),
        )
        for name, label in labels.items()
    }

    def preview_valuation(_event: ft.ControlEvent | None = None) -> None:
        if not active():
            return
        try:
            assumptions = {
                "forecast_years": int(inputs["forecast_years"].value.strip()),
                "discount_rate": float(inputs["discount_rate"].value) / 100,
                "terminal_growth": float(inputs["terminal_growth"].value) / 100,
                "scenarios": {
                    name: {"growth": float(inputs[name].value) / 100}
                    for name in ("bear", "base", "bull")
                },
            }
        except (ValueError, TypeError, AttributeError, OverflowError):
            assumptions = {}
        result.content = render(
            _valuation_panel(
                model.instrument_id,
                model.identity.get("asset_type"),
                decision_time,
                assumptions,
            )
        )
        refresh()

    def clear_valuation(_event: ft.ControlEvent | None = None) -> None:
        if not active():
            return
        for control in inputs.values():
            control.value = ""
        result.content = render(initial)
        refresh()

    return ft.Column(
        [
            ft.Text(
                "Session-only scenario assumptions. Enter every input; bear < base < bull. Inputs are not saved or exported and do not change scores. execution_allowed=false.",
                selectable=True,
            ),
            ft.Text("Terminal growth must be at least -100% and below the discount rate.", size=11),
            ft.ResponsiveRow(list(inputs.values()), spacing=8, run_spacing=8),
            ft.Row(
                [
                    ft.OutlinedButton(
                        "Preview valuation scenarios",
                        key="instrument-detail.preview-valuation",
                        on_click=preview_valuation,
                    ),
                    ft.OutlinedButton(
                        "Clear scenario inputs",
                        key="instrument-detail.clear-valuation",
                        on_click=clear_valuation,
                    ),
                ],
                wrap=True,
            ),
            result,
        ],
        tight=True,
    )


def _valuation_workspace(page: ft.Page | None, model: InstrumentDetailViewModel, decision_time: object) -> ft.Control:
    evidence = _render_evidence_section(
        "Stock valuation and scenarios",
        model.sections.get("valuation"),
        key="instrument-detail.valuation",
    )
    if str(model.identity.get("asset_type", "")).casefold() not in {"stock", "equity"}:
        return evidence

    owner = {"mounted": True}
    sessions: list[tuple[dict[str, bool], ft.AlertDialog]] = []

    def dispose_workspace() -> None:
        owner["mounted"] = False
        for session, dialog in sessions:
            session["active"] = False
            dialog.open = False
            dialog.content = None

    if page is not None:
        page._valuation_workspace_dispose = dispose_workspace

    def open_valuation_workspace(_event: ft.ControlEvent | None = None) -> None:
        if page is None or not callable(getattr(page, "show_dialog", None)):
            return
        if not owner["mounted"] or any(session["active"] for session, _dialog in sessions):
            return
        session = {"active": True}

        def session_active() -> bool:
            return owner["mounted"] and session["active"]

        async def restore_valuation_focus(_event: ft.ControlEvent | None = None) -> None:
            session["active"] = False
            dialog.content = None
            sessions[:] = [item for item in sessions if item[1] is not dialog]
            if owner["mounted"]:
                await opener.focus()

        async def close_valuation_workspace(_event: ft.ControlEvent | None = None) -> None:
            session["active"] = False
            dialog.open = False
            dialog.content = None
            sessions[:] = [item for item in sessions if item[1] is not dialog]
            page.update()
            if owner["mounted"]:
                await opener.focus()

        dialog = ft.AlertDialog(
            title=ft.Text("Valuation scenario workspace"),
            modal=False,
            scrollable=True,
            inset_padding=12,
            content_padding=12,
            content=ft.Container(
                width=620,
                content=ft.Column(
                    [
                        ft.Text(
                            "Closing this workspace discards its inputs and results. Resize retains them. Escape or Close returns to Instrument Detail."
                        ),
                        _render_valuation_scenarios(page, model, decision_time, session_active=session_active),
                    ],
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Close scenario workspace",
                    key="instrument-detail.close-valuation",
                    on_click=close_valuation_workspace,
                )
            ],
            on_dismiss=restore_valuation_focus,
        )
        sessions.append((session, dialog))
        page.show_dialog(dialog)

    opener = ft.OutlinedButton(
        "Open valuation scenarios",
        key="instrument-detail.open-valuation",
        on_click=open_valuation_workspace,
        disabled=page is None or not callable(getattr(page, "show_dialog", None)),
        tooltip="A local scenario workspace is unavailable for this page session.",
    )
    return ft.Column([opener, evidence])


def _valuation_card(model: InstrumentDetailViewModel, page: ft.Page | None, state: object) -> ft.Control:
    decision_time = getattr(
        getattr(getattr(state, "snapshot", None), "data_report", None),
        "as_of_date",
        None,
    )
    return _valuation_workspace(page, model, decision_time)


def _section_rows(
    model: InstrumentDetailViewModel,
    vintage: object,
    page: ft.Page | None,
    state: object,
) -> dict[str, list[ft.Control]]:
    def preview(_event: object) -> None:
        return None

    sections = model.sections
    valuation_workspace = _valuation_card(model, page, state)
    score_history = _score_history_chart(sections.get("history"))
    overview = [
        _render_evidence_section(
            "Candle Evidence",
            sections.get("candle_evidence"),
            subtitle="Candle research evidence; same-bar exits remain ambiguous; execution_allowed=false.",
            key="instrument-detail.candle-evidence",
        ),
        _render_feature_driver_panel(sections.get("feature_drivers")),
        _render_crowding_attribution_panel(
            {"scores": sections.get("scores"), "attribution": sections.get("attribution")}
        ),
        _section_card("Alpha, beta and correlation", sections.get("attribution")),
        _render_opportunity_card(sections.get("opportunity")),
        _section_card("Peer cohort and adapter lineage", sections.get("peer_cohort")),
        _section_card("Classification context", model.identity),
        _section_card("Market clock and session", sections.get("market_clock")),
    ]
    fund = [
        render_etf_structure_panel(model),
        render_etf_disclosure_panel(model),
        render_etf_e1_panel(sections.get("etf_economics")),
        _section_card("ETF direct overlap", sections.get("etf_overlap"), "instrument-detail.etf-overlap"),
        _section_card("ETF Liquidity", sections.get("etf_liquidity")),
        GlassCard(
            "ETF order-preview capacity meter",
            note="Order value and horizon capacity are unavailable without a stored preview result.",
            body=[
                ft.ResponsiveRow(
                    [
                        Field("Order value (EUR)", control=ft.TextField(**field_input_style())),
                        Field("Horizon (days)", control=ft.TextField(**field_input_style())),
                    ],
                    spacing=8,
                    run_spacing=8,
                ),
                KpiTile("Capacity preview", None, "No capacity preview result is available for this instrument."),
                Disclosure("Capacity evidence", _payload(sections.get("etf_liquidity"))),
                Button.primary(
                    "Preview capacity",
                    on_click=preview,
                    disabled=True,
                    disabled_reason="A capacity preview result is unavailable.",
                    key="instrument-detail.preview-capacity",
                ),
            ],
        ),
    ]
    fundamentals = [
        _render_evidence_section("Fundamentals", sections.get("fundamentals"), key="instrument-detail.fundamentals", subtitle="Five-section values and statement_history with provenance; execution_allowed=false."),
        valuation_workspace,
        _render_evidence_section(
            "Financial Institutions",
            sections.get("financial_institutions"),
            subtitle="Bank and insurer evidence with the separate Sparebank EC workspace.",
            key="instrument-detail.financial-institutions",
            extra=[_render_sparebank_workspace(sections.get("sparebank_workspace"), page=page)],
        ),
        _section_card("Real Assets", sections.get("real_assets")),
        _section_card("Cyclicals", sections.get("cyclicals")),
        _section_card("Innovation and Healthcare", sections.get("innovation")),
    ]
    fixed_income = [
        _section_card("Fixed-income risk", sections.get("fixed_income_risk"), "instrument-detail.fixed-income-risk"),
        _section_card("Fixed-income market data", sections.get("fixed_income_market_data"), "instrument-detail.fixed-income-market-data"),
        _section_card("Fixed-income analytics", sections.get("fixed_income_analytics")),
        _section_card(
            "Fixed-income terms and contractual cash flows",
            sections.get("fixed_income_terms"),
            "instrument-detail.fixed-income-terms",
        ),
    ]
    backtests = sections.get("backtests")
    operational = (
        backtests.get("operational_evidence", "unavailable")
        if isinstance(backtests, Mapping)
        else "unavailable"
    )
    risk = [
        _section_card("Risk and feature evidence", sections.get("risk")),
        _section_card("Factor risk", sections.get("factor_risk"), "instrument-detail.factor-risk"),
        _section_card("Forecast evidence", sections.get("forecasts")),
        _section_card("Model cards", sections.get("model_cards"), "instrument-detail.model-cards"),
        _section_card("Backtest trust", sections.get("backtests")),
        _section_card("Operational evidence", operational),
        _section_card("Evidence Score", sections.get("scores")),
        render_news_contradiction_panel(model),
    ]
    history = [
        score_history,
        _section_card("Score-component metric history", sections.get("metric_history"), "instrument-detail.metric-history"),
        _section_card("Point-in-time vintage history", vintage),
        _section_card("What changed since the last run", sections.get("run_changes")),
        _section_card("Paper-trade history", sections.get("paper_trades")),
        _section_card("Decision journal", sections.get("journal")),
        _render_evidence_section("LLM thesis diary", sections.get("thesis_diary"), key="instrument-detail.thesis-diary", subtitle="Local non-executable thesis evidence; execution_allowed=false."),
        render_news_context_panel(model),
        render_event_calendar_panel(model),
    ]
    return {
        "Overview": overview,
        "Fund": fund,
        "Fundamentals": fundamentals,
        "Fixed income": fixed_income,
        "Risk & forecasts": risk,
        "History": history,
        # Built once and listed above; the stock page shows them outside the collapsed evidence records.
        "_valuation_workspace": [valuation_workspace],
        "_score_history": [score_history],
    }


def _section_kind(identity: Mapping[str, object]) -> str:
    asset_type = str(identity.get("asset_type", identity.get("asset_class", ""))).casefold()
    if "bond" in asset_type or "fixed_income" in asset_type or "fixed income" in asset_type:
        return "Fixed income"
    if asset_type in {"etf", "fund", "mutual_fund"}:
        return "Fund"
    return "Fundamentals"


def _stock_model(model: InstrumentDetailViewModel, state: object) -> sp.StockPageModel | None:
    """The stock page model for normal (non-bank) stocks; None keeps the generic page for everything else."""

    listed = _listed_score(state, model.instrument_id)
    if not sp.is_normal_stock(model.identity, listed):
        return None
    stock = sp.build_model(getattr(state, "snapshot", None), model.instrument_id, listed)
    return stock if stock.available else None


def _without(cards: Sequence[ft.Control], *shown: ft.Control) -> list[ft.Control]:
    return [card for card in cards if not any(card is other for other in shown)]


def _stock_layout(
    model: InstrumentDetailViewModel,
    stock: sp.StockPageModel,
    state: object,
    page: ft.Page | None,
    instrument_ids: Sequence[str],
    on_instrument_change: object,
    groups: dict[str, list[ft.Control]],
) -> tuple[list[ft.Control], dict[str, list[ft.Control]]]:
    """Score first, then plain words, price and identity; sections hold numbers, valuation, peers and notes."""

    snapshot = getattr(state, "snapshot", None)
    config = getattr(snapshot, "config", None)
    export_button, export_status = _export_controls(model, state, page)
    top = [
        ft.ResponsiveRow([sp.placed(sp.score_card(stock, page), {"xs": 12, "lg": 7}), sp.placed(sp.words_card(stock), {"xs": 12, "lg": 5})], spacing=16, run_spacing=16),
        ft.ResponsiveRow(
            [
                _price_card(model, state, page),
                sp.identity_card(stock, model.identity, instrument_ids, on_instrument_change, footer=[export_button, export_status]),
            ],
            spacing=16,
            run_spacing=16,
        ),
    ]
    valuation_workspace = groups["_valuation_workspace"]
    score_history = groups["_score_history"]
    forecast = GlassCard(
        "Expected-return range",
        note="q10 / q50 / q90 by horizon",
        body=Well(_forecast_chart(model.sections.get("forecasts")), expand=True),
    )
    stock_groups = {
        "Overview": [
            *sp.numbers_cards(stock, ("Market", "Earnings and returns", "Cash and balance sheet")),
            sp.valuation_card(stock),
            sp.peers_card(stock, config),
            sp.notes_card(stock),
            _instrument_alerts_panel(model, state),
            sp.technical_records(_without(groups["Overview"])),
        ],
        "Fundamentals": [
            sp.fiscal_history_card(stock),
            sp.definitions_card(stock),
            *valuation_workspace,
            sp.technical_records(_without(groups["Fundamentals"], *valuation_workspace)),
        ],
        "Risk & forecasts": [
            *sp.risk_cards(snapshot, model.instrument_id),
            forecast,
            sp.technical_records(groups["Risk & forecasts"]),
        ],
        "History": [
            *score_history,
            sp.technical_records(_without(groups["History"], *score_history)),
        ],
    }
    return top, stock_groups


def _body(
    model: InstrumentDetailViewModel,
    state: object,
    page: ft.Page | None,
    active_section: str,
    instrument_ids: Sequence[str],
    on_instrument_change: object,
) -> ft.Control:
    kind = _section_kind(model.identity)
    options = ["Overview", kind, "Risk & forecasts", "History"]
    if active_section not in options:
        active_section = "Overview"
    vintage = (
        bitemporal_history_summary(model.instrument_id)
        if model.instrument_id
        else {"status": "unavailable", "message": "No instrument is selected."}
    )
    groups = _section_rows(model, vintage, page, state)
    extra_evidence = [card for name in ("Fund", "Fundamentals", "Fixed income") if name != kind for card in groups[name]]
    groups["Overview"].append(Disclosure("Additional local evidence", ft.Column(extra_evidence)))
    stock = _stock_model(model, state)
    if stock is not None:
        top_rows, groups = _stock_layout(model, stock, state, page, instrument_ids, on_instrument_change, groups)
    else:
        identity = _identity_card(model, state, page, instrument_ids, on_instrument_change)
        price = _price_card(model, state, page)
        score = _score_card(model, page, state)
        forecast = GlassCard(
            "Expected-return range",
            note="q10 / q50 / q90 by horizon",
            body=Well(_forecast_chart(model.sections.get("forecasts")), expand=True),
            expand=True,
        )
        alerts = _instrument_alerts_panel(model, state)
        top_rows = [
            ft.ResponsiveRow([identity, price], spacing=16, run_spacing=16),
            ft.ResponsiveRow([score, forecast, alerts], spacing=16, run_spacing=16),
        ]
    section_controls = [
        ft.Column(
            [
                SectionHeader(
                    section,
                    "Canonical evidence and review context.",
                ),
                ft.ResponsiveRow(cards, spacing=16, run_spacing=16),
            ],
            spacing=12,
            visible=section == active_section,
        )
        for section in options
        for cards in [groups[section]]
    ]
    return ft.Column(
        [
            *top_rows,
            *section_controls,
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def instrument_detail_page(page: ft.Page | None, state: object) -> PageView:
    snapshot = getattr(state, "snapshot", None)
    selected = _instrument_id(page, state)
    if selected:
        # Opening an instrument makes it the current one for every page (Stock Research follows it).
        state.selected_etf = selected
        recent = [item for item in getattr(state, "recent_instruments", []) if item != selected]
        try:
            state.recent_instruments = [selected, *recent][:5]
        except AttributeError:
            pass
    options = _instrument_ids(snapshot, selected)
    body_holder = ft.Container(key="instrument-detail.body", expand=True)
    chrome_holder: list[PageChrome] = []
    rendered: dict[str, object] = {"instrument": None, "section_controls": {}}
    generation = [0]
    instrument_lock = threading.Lock()
    pending_instrument: list[tuple[int, str] | None] = [None]
    instrument_worker = [False]

    def update_body() -> None:
        try:
            mounted_page = getattr(body_holder, "page", None)
        except Exception:
            mounted_page = None
        if mounted_page is not None:
            body_holder.update()

    def chrome_for(instrument_id: str, section: str, model: InstrumentDetailViewModel) -> PageChrome:
        identity = model.identity
        display_name = _value(model.display_name)
        asset_type = _value(identity.get("asset_type", identity.get("asset_class")))
        isin = _value(identity.get("isin"))
        currency = _value(identity.get("currency"))
        kind = _section_kind(identity)
        groups = []
        if options:
            groups.append(SegmentGroup("instrument", options, instrument_id, on_change=change_instrument))
        section_options = ["Overview", kind, "Risk & forecasts", "History"]
        if section not in section_options:
            section = "Overview"

        def change_section(value: str) -> PageChrome | None:
            # Sections are already built: switching only toggles visibility (no full page rebuild).
            state.selected_instrument_section = value
            try:
                chrome = render(instrument_id, value)
            except RuntimeError:
                # A frozen/unmounted body cannot be toggled in place: fall back to a full rebuild.
                refresh_page = getattr(page, "_shell_refresh", None)
                if callable(refresh_page):
                    refresh_page()
                    return None
                raise
            refresh_chrome = getattr(page, "_shell_chrome_update", None)
            if callable(refresh_chrome):
                refresh_chrome(chrome)
            return chrome

        groups.append(
            SegmentGroup(
                "instrument-section",
                section_options,
                section,
                on_change=change_section,
            )
        )
        return PageChrome(
            f"Instrument Detail \u00b7 {instrument_id or 'Unavailable'}",
            f"{display_name} \u00b7 {asset_type} \u00b7 {isin} \u00b7 {currency}",
            groups,
        )

    def render_model(
        instrument_id: str,
        section: str,
        model: InstrumentDetailViewModel,
        chrome: PageChrome,
        expected: int | None = None,
    ) -> PageChrome:
        kind = _section_kind(model.identity)
        if rendered["instrument"] == instrument_id and isinstance(body_holder.content, ft.Column):
            for name, section_control in rendered["section_controls"].items():
                section_control.visible = name == section
            rendered["section"] = section
        else:
            def on_instrument_change(value: str) -> PageChrome:
                return change_instrument(value)

            body = _body(model, state, page, section, options, on_instrument_change)
            if expected is not None and expected != generation[0]:
                return chrome
            body_holder.content = body
            rendered["instrument"] = instrument_id
            rendered["model"] = model
            rendered["section"] = section
            rendered["section_controls"] = (
                dict(zip(["Overview", kind, "Risk & forecasts", "History"], body.controls[2:], strict=True))
                if isinstance(body, ft.Column)
                else {}
            )
            if not chrome_holder:
                chrome_holder.append(chrome)
        update_body()
        return chrome

    def render(instrument_id: str, section: str) -> PageChrome:
        model = (
            rendered["model"]
            if rendered["instrument"] == instrument_id and isinstance(rendered.get("model"), InstrumentDetailViewModel)
            else _model_for(state, instrument_id)
        )
        chrome = chrome_for(instrument_id, section, model)
        return render_model(instrument_id, section, model, chrome)

    def load_instrument(expected: int, instrument_id: str) -> PageChrome | None:
        try:
            if expected != generation[0]:
                return None
            model = _model_for(state, instrument_id)
            chrome = chrome_for(instrument_id, "Overview", model)
            if expected != generation[0]:
                return None
            render_model(instrument_id, "Overview", model, chrome, expected)
            refresh_chrome = getattr(page, "_shell_chrome_update", None)
            if callable(refresh_chrome):
                refresh_chrome(chrome)
            return chrome
        except Exception as exc:
            if expected != generation[0]:
                return None
            body_holder.content = Note(f"Instrument detail is unavailable ({type(exc).__name__}).")
            update_body()
            return None

    def load_pending_instruments() -> None:
        while True:
            with instrument_lock:
                request = pending_instrument[0]
                pending_instrument[0] = None
                if request is None:
                    instrument_worker[0] = False
                    return
            load_instrument(*request)

    def change_instrument(value: str) -> PageChrome:
        state.selected_etf = value
        state.selected_instrument_section = "Overview"
        with instrument_lock:
            generation[0] += 1
            expected = generation[0]
        if page is None:
            return render(value, "Overview")
        loading_chrome = PageChrome(
            f"Instrument Detail \\u00b7 {value or 'Unavailable'}",
            "Loading instrument evidence...",
            [SegmentGroup("instrument", options, value, on_change=change_instrument)] if options else (),
        )
        body_holder.content = Note("Loading instrument evidence...")
        update_body()
        if not isinstance(page, ft.Page) and not hasattr(page, "views"):
            return load_instrument(expected, value) or loading_chrome
        with instrument_lock:
            pending_instrument[0] = (expected, value)
            if instrument_worker[0]:
                return loading_chrome
            instrument_worker[0] = True
        worker = threading.Timer(0.01, load_pending_instruments)
        worker.name = "instrument-segment-render"
        worker.daemon = True
        worker.start()
        return loading_chrome

    selected_section = str(getattr(state, "selected_instrument_section", "Overview") or "Overview")
    render(selected, selected_section)
    if not chrome_holder:
        raise RuntimeError("Instrument detail view could not be built.")
    return PageView(chrome_holder[0], body_holder)

__all__ = ["instrument_detail_page", "render_etf_disclosure_panel"]
