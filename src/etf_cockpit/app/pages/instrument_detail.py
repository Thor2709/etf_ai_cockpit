"""Instrument detail and provenance page."""

from __future__ import annotations

import json
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
from etf_cockpit.app.formatting import format_number
from etf_cockpit.application.alerts import read_local_alerts
from etf_cockpit.application.instrument_detail_view import (
    InstrumentDetailViewModel,
    _valuation_panel,
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


def _reason(value: object, title: str) -> str:
    if isinstance(value, Mapping):
        for key in ("unavailable_reason", "message", "reason"):
            candidate = value.get(key)
            if candidate:
                return str(candidate).splitlines()[0]
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
        summary: ft.Control = Note("Evidence details are available in the local result.")
    else:
        summary = KpiTile(title, None, _reason(value, title))
    body = [summary, *_provenance_tags(value), *extra, Disclosure("Evidence details", _payload(value), expanded=expanded)]
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
    attribution = sections.get("attribution")
    value = attribution.get("alpha") if isinstance(attribution, Mapping) else None
    alpha = format_number(value, decimals=2, unavailable="Unavailable")
    return GlassCard(
        "Crowding and attribution",
        note="Instrument-scoped attribution and crowding evidence.",
        body=[
            KpiTile(
                "Alpha",
                alpha if alpha != "Unavailable" else None,
                "Stored attribution value" if alpha != "Unavailable" else "No stored alpha value is available.",
            ),
            Disclosure("Attribution details", _payload(sections)),
        ],
    )


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
    return ck.line_chart(
        x_values,
        [ck.Series("Adjusted close", values, color=theme.CYAN, glow=True, area=True)],
        x_name="Date",
        y_name=f"Price ({currency})",
        insight=f"Price history across {len(valid)} stored observations.",
    )


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
    can_export = model.status != "unavailable" and callable(getattr(state, "export_audit_packet", None))
    status = Note("No audit evidence export has been created in this session.")

    def export_instrument_evidence(_event: ft.ControlEvent | None = None) -> None:
        exporter = getattr(state, "export_audit_packet", None)
        if not can_export or not callable(exporter):
            status.value = "Audit evidence export is unavailable for this selection."
        else:
            try:
                exporter()
                status.value = "Audit evidence export created."
            except Exception:
                status.value = "Audit evidence export could not be created."
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

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
            Button.secondary(
                "Export audit evidence",
                on_click=export_instrument_evidence,
                disabled=not can_export,
                disabled_reason="Canonical evidence or export capability is missing.",
                key="instrument-detail.export-evidence",
            ),
            status,
            Note("Research context only · execution_allowed=false."),
            Disclosure(
                "Export details",
                str(getattr(state, "last_export_path", "") or "No export path is available."),
            ),
        ],
        expand=True,
    )


def _score_card(model: InstrumentDetailViewModel, page: ft.Page | None) -> ft.Control:
    score = model.sections.get("scores")
    score = score if isinstance(score, Mapping) else {}
    raw_score = score.get("evidence_score")
    ring_score = raw_score * 10 if isinstance(raw_score, (int, float)) else None
    component_keys = (
        ("canonical_attractiveness_10", "Attractiveness"),
        ("canonical_expected_return_10", "Expected return"),
        ("canonical_risk_implementation_10", "Risk / implementation"),
        ("canonical_evidence_confidence_10", "Evidence confidence"),
        ("canonical_coverage", "Coverage"),
    )
    bars = [
        ft.Row(
            [
                Note(label),
                ScoreBar(score.get(key) if isinstance(score.get(key), (int, float)) else None),
            ],
            spacing=8,
        )
        for key, label in component_keys
    ]

    def open_scores(_event: ft.ControlEvent | None = None) -> None:
        if page is not None and callable(getattr(page, "go", None)):
            page.go("/signals")

    return GlassCard(
        "Evidence score",
        note="Canonical score evidence",
        body=[
            VerdictRing(ring_score),
            KpiTile(
                "Evidence score",
                format_number(raw_score, decimals=1, unavailable="Unavailable")
                if raw_score is not None
                else None,
                _reason(score, "Evidence score") if raw_score is None else "Canonical score evidence.",
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


def _section_card(title: str, value: object, key: str | None = None) -> ft.Control:
    return _render_evidence_section(title, value, key=key)


def _feature_driver_chart(value: object) -> ft.Control:
    rows = value.get("rows", ()) if isinstance(value, Mapping) else ()
    rows = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, Sequence) else []
    chart_rows = [
        row for row in rows
        if isinstance(row.get("contribution"), (int, float))
        and pd.notna(row.get("contribution"))
    ]
    if not chart_rows:
        return GlassCard(
            "Feature drivers",
            body=EmptyState("Unavailable", _reason(value, "Feature driver chart")),
            key="instrument-detail.feature-drivers",
        )
    chart_rows = chart_rows[:12]
    return GlassCard(
        "Feature drivers",
        note="Stored driver contribution evidence",
        body=[
            ck.bar_chart(
                [str(row.get("component") or "—") for row in chart_rows],
                [float(row["contribution"]) for row in chart_rows],
                x_name="Feature driver",
                y_name="Contribution (score points)",
                unit="score points",
                unavailable_reason="No numeric feature driver contributions are available.",
            ),
            Disclosure("Feature driver evidence", _payload(value)),
        ],
        key="instrument-detail.feature-drivers",
    )


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


def _valuation_card(model: InstrumentDetailViewModel, page: ft.Page | None, state: object) -> ft.Control:
    valuation = model.sections.get("valuation")
    if str(model.identity.get("asset_type", "")).casefold() not in {"stock", "equity"}:
        return _section_card("Stock valuation and scenarios", valuation)

    decision_time = getattr(
        getattr(getattr(state, "snapshot", None), "data_report", None),
        "as_of_date",
        None,
    )
    initial = valuation
    result = {"value": initial}
    labels = {
        "forecast_years": "Forecast years (1-50)",
        "discount_rate": "Discount rate (%) >0 to 100",
        "terminal_growth": "Terminal growth (%)",
        "bear": "Bear growth (%) >=-50",
        "base": "Base growth (%)",
        "bull": "Bull growth (%) <=100",
    }

    def invalidate_valuation(_event: ft.ControlEvent | None = None) -> None:
        result["value"] = {
            "status": "unavailable",
            "message": "Inputs changed. Preview valuation scenarios to calculate current inputs.",
            "execution_allowed": False,
        }
        result_panel.content = Disclosure("Scenario result", _payload(result["value"]))
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    inputs = {
        name: ft.TextField(
            key=f"instrument-detail.valuation-input.{name}",
            value="",
            on_change=invalidate_valuation,
            **field_input_style(),
        )
        for name in labels
    }
    input_fields = []
    for name, label in labels.items():
        field = Field(label, control=inputs[name])
        field.col = {"xs": 12, "sm": 6}
        input_fields.append(field)

    result_panel = ft.Container(content=Disclosure("Scenario result", _payload(initial)))
    workspace = ft.Column(
        [
            Note(
                "Session-only scenario assumptions. Enter every input; bear < base < bull. "
                "Inputs are not saved or exported and do not change scores. execution_allowed=false."
            ),
            Note("Terminal growth must be at least -100% and below the discount rate."),
            ft.ResponsiveRow(input_fields, spacing=8, run_spacing=8),
            ft.Row(
                [
                    Button.primary(
                        "Preview valuation scenarios",
                        on_click=lambda _event: preview_valuation(),
                        key="instrument-detail.preview-valuation",
                    ),
                    Button.secondary(
                        "Clear scenario inputs",
                        on_click=lambda _event: clear_valuation(),
                        key="instrument-detail.clear-valuation",
                    ),
                    Button.secondary(
                        "Close scenario workspace",
                        on_click=lambda _event: close_valuation_workspace(),
                        key="instrument-detail.close-valuation",
                    ),
                ],
                spacing=8,
                wrap=True,
            ),
            result_panel,
        ],
        spacing=8,
        visible=False,
    )

    def preview_valuation() -> None:
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
        result["value"] = _valuation_panel(
            model.instrument_id,
            model.identity.get("asset_type"),
            decision_time,
            assumptions,
        )
        result_panel.content = Disclosure("Scenario result", _payload(result["value"]))
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    def clear_valuation() -> None:
        for control in inputs.values():
            control.value = ""
        result["value"] = initial
        result_panel.content = Disclosure("Scenario result", _payload(initial))
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    def close_valuation_workspace() -> None:
        workspace.visible = False
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    def open_valuation_workspace(_event: ft.ControlEvent | None = None) -> None:
        workspace.visible = True
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    return GlassCard(
        "Stock valuation and scenarios",
        body=[
            Button.primary(
                "Open valuation scenarios",
                on_click=open_valuation_workspace,
                key="instrument-detail.open-valuation",
            ),
            workspace,
            Disclosure("Stored valuation evidence", _payload(initial)),
        ],
    )


def _section_rows(
    model: InstrumentDetailViewModel,
    vintage: object,
    page: ft.Page | None,
    state: object,
) -> dict[str, list[ft.Control]]:
    def preview(_event: object) -> None:
        return None

    sections = model.sections
    overview = [
        _feature_driver_chart(sections.get("feature_drivers")),
        _render_crowding_attribution_panel(
            {"scores": sections.get("scores"), "attribution": sections.get("attribution")}
        ),
        _section_card("Alpha, beta and correlation", sections.get("attribution")),
        _section_card("Opportunity", sections.get("opportunity")),
        _section_card("Peer cohort and adapter lineage", sections.get("peer_cohort")),
        _section_card("Classification context", model.identity),
        _section_card("Market clock and session", sections.get("market_clock")),
    ]
    fund = [
        _section_card("ETF Structure & Documents", sections.get("etf_structure")),
        render_etf_disclosure_panel(model),
        _section_card("ETF holdings and exposure", sections.get("etf_holdings")),
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
        _section_card("ETF Economics", sections.get("etf_economics")),
    ]
    fundamentals = [
        _section_card("Fundamentals", sections.get("fundamentals"), "instrument-detail.fundamentals"),
        _valuation_card(model, page, state),
        _section_card("Financial Institutions", sections.get("financial_institutions")),
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
        _section_card("News/macro contradictions", sections.get("news")),
    ]
    history = [
        _score_history_chart(sections.get("history")),
        _section_card("Score-component metric history", sections.get("metric_history"), "instrument-detail.metric-history"),
        _section_card("Point-in-time vintage history", vintage),
        _section_card("What changed since the last run", sections.get("run_changes")),
        _section_card("Paper-trade history", sections.get("paper_trades")),
        _section_card("Decision journal", sections.get("journal")),
        _section_card("LLM thesis diary", sections.get("thesis_diary"), "instrument-detail.thesis-diary"),
        _section_card("News & context", sections.get("news")),
        _section_card("Event calendar", sections.get("events")),
    ]
    return {
        "Overview": overview,
        "Fund": fund,
        "Fundamentals": fundamentals,
        "Fixed income": fixed_income,
        "Risk & forecasts": risk,
        "History": history,
    }


def _section_kind(identity: Mapping[str, object]) -> str:
    asset_type = str(identity.get("asset_type", identity.get("asset_class", ""))).casefold()
    if "bond" in asset_type or "fixed_income" in asset_type or "fixed income" in asset_type:
        return "Fixed income"
    if asset_type in {"etf", "fund", "mutual_fund"}:
        return "Fund"
    return "Fundamentals"


def _body(
    model: InstrumentDetailViewModel,
    state: object,
    page: ft.Page | None,
    active_section: str,
    instrument_ids: Sequence[str],
    on_instrument_change: object,
) -> ft.Control:
    identity = _identity_card(model, state, page, instrument_ids, on_instrument_change)
    price = _price_card(model, state, page)
    score = _score_card(model, page)
    forecast = GlassCard(
        "Expected-return range",
        note="q10 / q50 / q90 by horizon",
        body=Well(_forecast_chart(model.sections.get("forecasts")), expand=True),
        expand=True,
    )
    alerts = _alerts_card(model, state)
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
    section_controls = [
        ft.Column(
            [
                SectionHeader(
                    section,
                    "Instrument evidence and review context.",
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
            ft.ResponsiveRow(
                [identity, price],
                spacing=16,
                run_spacing=16,
            ),
            ft.ResponsiveRow(
                [score, forecast, alerts],
                spacing=16,
                run_spacing=16,
            ),
            *section_controls,
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def instrument_detail_page(page: ft.Page | None, state: object) -> PageView:
    snapshot = getattr(state, "snapshot", None)
    selected = _instrument_id(page, state)
    options = _instrument_ids(snapshot, selected)
    holder: dict[str, PageView] = {}

    def render(instrument_id: str, section: str) -> None:
        model = _model_for(state, instrument_id)
        identity = model.identity
        display_name = _value(model.display_name)
        asset_type = _value(identity.get("asset_type", identity.get("asset_class")))
        isin = _value(identity.get("isin"))
        currency = _value(identity.get("currency"))
        kind = _section_kind(identity)
        groups = []
        if options:
            groups.append(
                SegmentGroup(
                    "instrument",
                    options,
                    instrument_id,
                    on_change=lambda value: render(value, section),
                )
            )
        section_options = ["Overview", kind, "Risk & forecasts", "History"]
        if section not in section_options:
            section = "Overview"
        groups.append(
            SegmentGroup(
                "instrument-section",
                section_options,
                section,
                on_change=lambda value: render(instrument_id, value),
            )
        )
        chrome = PageChrome(
            f"Instrument Detail · {instrument_id or 'Unavailable'}",
            f"{display_name} · {asset_type} · {isin} · {currency}",
            groups,
        )
        def on_instrument_change(value: str) -> None:
            state.selected_etf = value
            render(value, "Overview")

        body = _body(model, state, page, section, options, on_instrument_change)
        current = holder.get("view")
        if current is None:
            holder["view"] = PageView(chrome=chrome, body=body)
        else:
            current.chrome = chrome
            current.body = body
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    render(selected, "Overview")
    view = holder["view"]
    if view is None:
        raise RuntimeError("Instrument detail view could not be built.")
    return view


__all__ = ["instrument_detail_page", "render_etf_disclosure_panel"]
