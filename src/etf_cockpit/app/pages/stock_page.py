"""Sections of the normal-stock page: score first, plain-language text, numbers, valuation, peers and notes.

Presentation only: every value comes from ``application.stock_views`` (one shared evidence build) and
every unavailable value shows the reason the calculation stored. Used by Instrument Detail (stocks)
and by Stock Research, so both pages read the same canonical data.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    KpiTile,
    Note,
    ScoreBar,
    TableColumn,
    Tag,
    VerdictRing,
    Well,
    field_input_style,
)
from etf_cockpit.application import stock_service as service
from etf_cockpit.application.stock_views import (
    PEER_COLUMNS,
    ComponentRow,
    NumberRow,
    PeerRow,
    StockPageModel,
    build_stock_page_model,
    stock_notes_for,
)

_DASH = "—"
FULL = {"xs": 12}
HALF = {"xs": 12, "lg": 6}


def _text(value: str, *, size: int = 14, color: str | None = None, weight: ft.FontWeight | None = None) -> ft.Text:
    return ft.Text(value, size=size, color=color or theme.INK, selectable=True, weight=weight, font_family=theme.FONT_FAMILY)


def _refresh(control: ft.Control) -> None:
    try:
        if getattr(control, "page", None) is not None:
            control.update()
    except Exception:  # an unmounted control (tests, page switch) needs no refresh
        pass


def placed(control: ft.Control, col: Mapping[str, int]) -> ft.Control:
    control.col = dict(col)
    return control


def is_normal_stock(identity: Mapping[str, object], score_row: object | None = None) -> bool:
    """Stocks that use the stock page: not funds, bonds, banks or equity certificates."""

    kind = str(identity.get("asset_type", identity.get("asset_class", ""))).casefold()
    if kind not in {"stock", "equity"}:
        return False
    sector = str(identity.get("sector", "")).casefold()
    label = str(getattr(score_row, "final_label", "") or "").casefold()
    return sector not in {"banks", "bank", "savings banks"} and label != "scorecard_owned"


# ---------------------------------------------------------------------------------------------
# Score first (S1) and plain language (S2)
# ---------------------------------------------------------------------------------------------


def _component_table(rows: Sequence[ComponentRow]) -> ft.Control:
    table_rows = []
    for row in rows:
        score_cell: Any = ScoreBar(row.score, expand=False, width=140) if row.eligible and row.score is not None else _DASH
        table_rows.append(
            {
                "component": row.label,
                "score": score_cell,
                "weight": f"{row.weight_share:.0%}",
                "note": _short(row.why, 160),
            }
        )
    return DataTable(
        [
            TableColumn("component", "Component", flex=2, sortable=False),
            TableColumn("score", "Score", width=170, sortable=False),
            TableColumn("weight", "Weight", width=80, numeric=True, sortable=False),
            TableColumn("note", "How it was calculated, or why it is missing", flex=5, sortable=False),
        ],
        table_rows,
        max_visible_rows=12,
        empty_title="No components",
        empty_reason="The score list has no row for this instrument, so no component can be shown.",
    )


def _short(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def score_card(model: StockPageModel, page: ft.Page | None = None) -> ft.Control:
    ring_value = None if model.score is None else model.score * 10
    ring = VerdictRing(ring_value, caption="of 10", value_text=None if model.score is None else f"{model.score:.1f}")
    coverage_text = None if model.coverage is None else f"{model.coverage:.0%}"
    has_row = bool(model.total)
    if coverage_text is not None:
        coverage_sub = f"{model.used} of {model.total} score components"
    else:
        coverage_sub = "the score row stores no coverage value" if has_row else "no score row for this instrument"
    label_reason = "no label: the evidence score is missing (see the missing steps below)" if has_row else "no score row for this instrument, so no label"
    tiles = ft.ResponsiveRow(
        [
            placed(KpiTile("Coverage", coverage_text, coverage_sub), {"xs": 6}),
            placed(KpiTile("Decision label", model.label.replace("_", " ").title() if model.label else None, "from the evidence score; never an order" if model.label else label_reason), {"xs": 6}),
        ],
        spacing=8,
        run_spacing=8,
    )
    body: list[ft.Control] = [
        ft.Row(
            [
                ring,
                ft.Column([_text(model.headline, size=15), tiles], spacing=12, expand=True),
            ],
            spacing=24,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        _component_table(model.components),
    ]

    def open_scores(_event: ft.ControlEvent | None = None) -> None:
        if page is not None and callable(getattr(page, "go", None)):
            page.go("/signals")

    body.append(Button.secondary("Open in Scores", on_click=open_scores, key="instrument-detail.open-scores"))
    return GlassCard("Evidence score", note="composite of the components that are available", body=body)


def words_card(model: StockPageModel) -> ft.Control:
    lines = [_text(sentence, size=14) for sentence in model.sentences]
    if not lines:
        lines = [Note(model.unavailable_reason or "No evidence sentences are available because no fundamentals are loaded.")]
    return GlassCard("In plain words", note="generated from the numbers below", body=lines)


# ---------------------------------------------------------------------------------------------
# Numbers, valuation, peers
# ---------------------------------------------------------------------------------------------


def _number_table(rows: Sequence[NumberRow]) -> ft.Control:
    return DataTable(
        [
            TableColumn("metric", "Metric", flex=3, sortable=False),
            TableColumn("value", "Value", width=130, numeric=True, sortable=False),
            TableColumn("basis", "Basis · as of · source", flex=4, sortable=False),
            TableColumn("why", "Note (why unavailable)", flex=4, sortable=False),
        ],
        [
            {"metric": row.label, "value": row.display, "basis": _short(row.detail, 90), "why": "" if row.available else _short(row.reason or "", 150)}
            for row in rows
        ],
        max_visible_rows=14,
        empty_title="No numbers",
        empty_reason="No fundamentals are loaded for this instrument.",
    )


def numbers_cards(model: StockPageModel, groups: Sequence[str]) -> list[ft.Control]:
    cards = []
    for title, rows in model.numbers:
        if title in groups and rows:
            cards.append(placed(GlassCard(title, body=_number_table(rows)), HALF))
    return cards


def valuation_card(model: StockPageModel) -> ft.Control:
    rows = [row for title, group in model.numbers if title in {"Valuation", "Reverse valuation"} for row in group]
    return GlassCard(
        "Valuation",
        note="multiples, own history, peers and implied growth",
        body=[_number_table(rows)],
    )


def peers_card(model: StockPageModel, config: Any, on_changed: Callable[[], None] | None = None) -> ft.Control:
    columns = [
        TableColumn("peer", "Peer", flex=3, sortable=False),
        TableColumn("why", "Why a peer", flex=3, sortable=False),
        *[TableColumn(key, label, width=110, numeric=True, sortable=False) for key, label in PEER_COLUMNS],
    ]

    def cell(row: PeerRow, key: str) -> Any:
        value, reason = row.cells[key]
        return (value, _short(reason, 40)) if reason else value

    rows = [
        {"peer": (row.name, row.instrument_id or ""), "why": _short(row.reasons, 80), **{key: cell(row, key) for key, _ in PEER_COLUMNS}}
        for row in model.peers
    ]
    status = Note(model.peer_summary)
    picker = ft.TextField(key="stock.peers.input", value=", ".join(model.user_peers), **field_input_style(placeholder="Peer ids or Yahoo tickers, separated by commas"))
    feedback = Note("")

    def save_peers(_event: ft.ControlEvent | None = None) -> None:
        feedback.value = "Saving peers…"
        _refresh(feedback)

        def work() -> None:
            try:
                saved, messages = service.set_stock_peers(model.instrument_id, picker.value or "", config)
                feedback.value = (f"Saved {len(saved)} peers; reopen the page to see them in the table. " if saved or not messages else "No peers saved. ") + " ".join(messages)
            except Exception as exc:
                feedback.value = f"Peers could not be saved ({type(exc).__name__}: {str(exc)[:100]})."
            _refresh(feedback)
            if on_changed is not None:
                on_changed()

        threading.Thread(target=work, daemon=True, name="stock-peers-save").start()

    def reset_peers(_event: ft.ControlEvent | None = None) -> None:
        picker.value = ""
        _refresh(picker)
        save_peers()

    return GlassCard(
        "Peer comparison",
        note="automatic from sector, industry, region and size; your picks come first",
        body=[
            DataTable(columns, rows, max_visible_rows=12, empty_title="No peers", empty_reason=model.peer_summary),
            status,
            Field("Your own peers (added to the automatic ones)", control=picker),
            ft.Row(
                [
                    Button.primary("Save peers", on_click=save_peers, key="stock.peers.save"),
                    Button.secondary("Clear my peers", on_click=reset_peers, key="stock.peers.clear"),
                ],
                spacing=8,
                wrap=True,
            ),
            feedback,
        ],
    )


# ---------------------------------------------------------------------------------------------
# Notes (S3)
# ---------------------------------------------------------------------------------------------


def notes_card(model: StockPageModel, *, title: str = "Your notes") -> ft.Control:
    listing = ft.Column(spacing=8)
    editor = ft.TextField(key="stock.notes.input", **field_input_style(multiline=True, placeholder="What did you decide, or what do you want to remember about this stock?"))
    feedback = Note("")
    state: dict[str, list[dict[str, Any]]] = {"notes": list(model.notes)}

    def render() -> None:
        listing.controls = [_note_item(note, retract_note) for note in state["notes"]] or [Note("No notes yet. Notes are dated, stored on this computer only and kept over time.")]
        _refresh(listing)

    def reload() -> None:
        state["notes"] = stock_notes_for(model.instrument_id)
        render()

    def add_note(_event: ft.ControlEvent | None = None) -> None:
        try:
            service.add_stock_note(model.instrument_id, editor.value or "")
        except Exception as exc:
            feedback.value = f"Note not saved: {exc}"
            _refresh(feedback)
            return
        editor.value = ""
        feedback.value = "Note saved."
        _refresh(editor)
        _refresh(feedback)
        reload()

    def retract_note(note_id: str) -> None:
        try:
            service.retract_stock_note(model.instrument_id, note_id)
            feedback.value = "Note removed from the list (it stays in the file history)."
        except Exception as exc:
            feedback.value = f"Note not removed: {exc}"
        _refresh(feedback)
        reload()

    render()
    return GlassCard(
        title,
        note="dated, local, kept over time",
        body=[Field("New note", control=editor), Button.primary("Add note", on_click=add_note, key="stock.notes.add"), feedback, listing],
    )


def _note_item(note: Mapping[str, Any], retract_note: Callable[[str], None]) -> ft.Control:
    note_id = str(note.get("note_id"))
    stamp = str(note.get("created_at", ""))[:16].replace("T", " ")
    return Well(
        ft.Column(
            [
                ft.Row([Tag(stamp or _DASH, "mute", dense=True), *[Tag(str(t), "ok", dense=True) for t in note.get("tags", [])]], spacing=8),
                _text(str(note.get("text", "")), size=14),
                Button.secondary("Remove", on_click=lambda _e, nid=note_id: retract_note(nid), key=f"stock.notes.retract.{note_id}"),
            ],
            spacing=8,
        ),
        padding=12,
    )


# ---------------------------------------------------------------------------------------------
# Fundamentals, identity, risk and history sections
# ---------------------------------------------------------------------------------------------


def fiscal_history_card(model: StockPageModel) -> ft.Control:
    return GlassCard(
        "Reported history",
        note="fiscal years known at the decision time",
        body=DataTable(
            [
                TableColumn("period", "Period", flex=2, sortable=False),
                TableColumn("revenue", "Revenue", numeric=True, sortable=False),
                TableColumn("ebit", "EBIT", numeric=True, sortable=False),
                TableColumn("net_income", "Net income", numeric=True, sortable=False),
                TableColumn("fcf", "Free cash flow", numeric=True, sortable=False),
                TableColumn("equity", "Parent equity", numeric=True, sortable=False),
                TableColumn("currency", "Currency", width=90, sortable=False),
                TableColumn("source", "Source", sortable=False),
            ],
            model.fiscal_rows,
            max_visible_rows=8,
            empty_title="No fiscal years",
            empty_reason="No fiscal-year statements are known for this instrument at the decision time.",
        ),
    )


def definitions_card(model: StockPageModel) -> ft.Control:
    rows = [{"metric": row.label, "formula": row.formula or _DASH} for _title, group in model.numbers for row in group if row.formula]
    return GlassCard(
        "How each number is calculated",
        note="one definition per calculation",
        body=DataTable(
            [TableColumn("metric", "Metric", flex=2, sortable=False), TableColumn("formula", "Definition", flex=6, sortable=False)],
            rows,
            max_visible_rows=10,
            empty_title="No definitions",
            empty_reason="No calculations ran because no fundamentals are loaded.",
        ),
    )


def identity_card(
    model: StockPageModel,
    identity: Mapping[str, object],
    instrument_ids: Sequence[str],
    on_instrument_change: Callable[[str], object] | None,
    footer: Sequence[ft.Control] = (),
) -> ft.Control:
    """Identity with a reason for every field that is not verified or not available."""

    isin = str(identity.get("isin", "") or "")
    status = str(identity.get("isin_status", "") or "")
    unverified = isin.casefold() in {"", "needs_verification", "unknown"} or status.casefold() == "needs_verification"
    verify_hint = "identity not verified yet: resolve it from the ISIN or ticker (Universe, Add instrument)"
    source_id = identity.get("source_id")
    authority = identity.get("source_authority", identity.get("authority"))
    conflict = identity.get("conflict_id", identity.get("conflict_status"))
    rows = [
        {"field": "Instrument", "value": model.instrument_id, "why": ""},
        {"field": "Ticker", "value": str(identity.get("ticker") or _DASH), "why": "" if identity.get("ticker") else "no provider symbol is configured"},
        {"field": "ISIN", "value": isin if not unverified else _DASH, "why": verify_hint if unverified else ""},
        {"field": "Exchange", "value": _clean(identity.get("exchange")), "why": "" if _clean(identity.get("exchange")) != _DASH else "exchange is not verified; resolving the instrument fills it"},
        {"field": "Currency", "value": str(identity.get("currency") or _DASH), "why": ""},
        {"field": "Region", "value": str(identity.get("region") or _DASH), "why": ""},
        {"field": "Sector", "value": str(identity.get("sector") or _DASH), "why": ""},
        *[{"field": label, "value": value, "why": reason or ""} for label, value, reason in model.identity],
    ]
    options = list(instrument_ids)
    authority_reason = (
        "no source authority is recorded: the identity comes from the universe file and is not verified yet"
        if unverified
        else "no authority record exists for this source"
    )
    conflict_reason = (
        "no conflict check ran: " + ("the ISIN is not verified" if unverified else "no identity conflict record exists for this instrument")
    )
    return GlassCard(
        "Identity and provenance",
        note="where the company data comes from",
        body=[
            *(
                [Field("Instrument", value=model.instrument_id, options=options, on_change=on_instrument_change, key="instrument-detail.instrument")]
                if options
                else []
            ),
            ft.ResponsiveRow(
                [
                    placed(KpiTile("Source", str(source_id) if source_id else None, "identity source" if source_id else "no source id is recorded: the instrument comes from the universe file"), {"xs": 12, "sm": 4}),
                    placed(KpiTile("Authority", str(authority) if authority else None, "recorded source authority" if authority else authority_reason), {"xs": 12, "sm": 4}),
                    placed(KpiTile("Conflict", str(conflict) if conflict else None, "identity conflict evidence" if conflict else conflict_reason), {"xs": 12, "sm": 4}),
                ],
                spacing=8,
                run_spacing=8,
            ),
            DataTable(
                [TableColumn("field", "Field", flex=2, sortable=False), TableColumn("value", "Value", flex=3, sortable=False), TableColumn("why", "Note", flex=4, sortable=False)],
                rows,
                max_visible_rows=14,
            ),
            *footer,
            Note("Research context only · execution_allowed=false."),
        ],
        expand=True,
    )


def _clean(value: object) -> str:
    text = str(value or "").strip()
    return _DASH if text.casefold() in {"", "unverified", "unavailable", "none", "nan"} else text


def _percent(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DASH


def risk_cards(snapshot: Any, instrument_id: str) -> list[ft.Control]:
    """Price risk, momentum and model forecasts as readable tables (no raw records)."""

    signal = next((s for s in getattr(snapshot, "signals", ()) or () if str(getattr(s, "etf_id", "")) == instrument_id), None)
    metrics = getattr(signal, "supporting_metrics", {}) or {}
    no_signal = "no price signal was produced for this instrument (price history too short or missing)"

    def metric_row(label: str, key: str, formatter: Callable[[object], str]) -> dict[str, str]:
        value = metrics.get(key) if signal is not None else None
        ok = value is not None and value == value
        return {"metric": label, "value": formatter(value) if ok else _DASH, "why": "" if ok else (no_signal if signal is None else "not calculated for this snapshot")}

    risk_rows = [
        metric_row("Volatility, 60 days (annualised)", "vol_60d_ann", _percent),
        metric_row("Current drawdown", "drawdown_current", _percent),
        metric_row("Momentum, 60 days", "momentum_60d", _percent),
        metric_row("Momentum, 120 days", "momentum_120d", _percent),
        metric_row("Price above 200-day average", "trend_200", lambda v: "yes" if float(v) >= 1 else "no"),  # type: ignore[arg-type]
        metric_row("Expected edge after the median forecast", "expected_edge_bps", lambda v: f"{float(v):.0f} bps"),  # type: ignore[arg-type]
        metric_row("Estimated trading cost", "estimated_cost_bps", lambda v: f"{float(v):.0f} bps"),  # type: ignore[arg-type]
        metric_row("Edge-to-cost ratio", "edge_to_cost_ratio", lambda v: f"{float(v):.1f}x"),  # type: ignore[arg-type]
    ]
    forecasts = getattr(snapshot, "forecasts", None)
    forecast_rows: list[dict[str, str]] = []
    if forecasts is not None and not forecasts.empty and "etf_id" in forecasts:
        for _, row in forecasts[forecasts["etf_id"].astype(str) == instrument_id].iterrows():
            ok = str(row.get("status")) == "ok" and row.get("q50_return") == row.get("q50_return")
            forecast_rows.append(
                {
                    "model": str(row.get("model_name")),
                    "horizon": f"{int(row.get('horizon_days'))} days" if row.get("horizon_days") == row.get("horizon_days") else _DASH,
                    "range": f"{_percent(row.get('q10_return'))} / {_percent(row.get('q50_return'))} / {_percent(row.get('q90_return'))}" if ok else _DASH,
                    "why": "" if ok else _short(str(row.get("reason_unavailable") or row.get("error_message") or row.get("status")), 140),
                }
            )
    return [
        placed(
            GlassCard(
                "Price risk and cost",
                note="from adjusted prices; descriptive, not advice",
                body=DataTable(
                    [TableColumn("metric", "Metric", flex=3, sortable=False), TableColumn("value", "Value", width=120, numeric=True, sortable=False), TableColumn("why", "Why unavailable", flex=4, sortable=False)],
                    risk_rows,
                    max_visible_rows=10,
                ),
            ),
            HALF,
        ),
        placed(
            GlassCard(
                "Forecasts",
                note="q10 / median / q90 return; forecasts stay separate from the score",
                body=DataTable(
                    [
                        TableColumn("model", "Model", flex=2, sortable=False),
                        TableColumn("horizon", "Horizon", width=100, sortable=False),
                        TableColumn("range", "q10 / q50 / q90", flex=3, numeric=True, sortable=False),
                        TableColumn("why", "Why unavailable", flex=4, sortable=False),
                    ],
                    forecast_rows,
                    max_visible_rows=6,
                    empty_title="No forecasts",
                    empty_reason="No forecast row exists for this instrument: run the forecasting models.",
                ),
            ),
            HALF,
        ),
    ]


def build_model(snapshot: Any, instrument_id: str, score_row: Any | None) -> StockPageModel:
    try:
        return build_stock_page_model(snapshot, instrument_id, score_row)
    except Exception as exc:  # the page still opens and says what failed
        return StockPageModel(instrument_id, instrument_id, "", False, f"stock evidence could not be built ({type(exc).__name__}: {str(exc)[:120]})")


def unavailable_card(model: StockPageModel) -> ft.Control:
    return GlassCard("Stock analysis", body=EmptyState("Stock analysis unavailable", model.unavailable_reason or "no evidence"))


def technical_records(controls: Sequence[ft.Control]) -> ft.Control:
    """Raw evidence cards stay available but collapsed, so the default view carries no record dumps."""

    return GlassCard("Full evidence records", note="technical detail, collapsed", body=[Disclosure("evidence records", ft.Column(list(controls), spacing=12))])
