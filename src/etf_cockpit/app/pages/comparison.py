from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    Note,
    ScoreBar,
    TableColumn,
    Tag,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_currency, format_date, format_number, format_percent
from etf_cockpit.app.pages import _p3_common as common
from etf_cockpit.app.state import AppState
from etf_cockpit.app.workspaces import save_workspace
from etf_cockpit.application.ui_facade import export_table, load_score_history_summary
from etf_cockpit.application.ui_views import comparison as compare_view
from etf_cockpit.core.paths import EXPORTS_DIR

_RANGES = ["1M", "3M", "1Y", "5Y"]
_EXPORT_TIP = "CSV export writes a local file only; nothing is uploaded."
_HERO = {
    "Price": ("Price, indexed to 100", "same start date", "Index (start = 100)"),
    "Score": ("Score history", "stored runs", "Score (0–10)"),
    "Risk": ("Drawdown", "peak of range", "Drawdown (%)"),
}
_ROW_HEIGHT = 35


def _comparison_fields() -> tuple[tuple[str, object], ...]:
    return (
        ("Instrument", lambda score: score.display_id),
        ("Name", lambda score: score.name),
        ("Latest price", lambda score: format_currency(score.latest_price)),
        ("Final score", lambda score: format_number(score.final_score_10, decimals=1, unavailable="Unavailable")),
        ("Evidence quality", lambda score: format_number(score.evidence_quality_10, decimals=1, unavailable="Unavailable")),
        ("Risk/friction", lambda score: format_number(score.risk_friction_10, decimals=1, unavailable="Unavailable")),
        ("Period return", lambda score: format_percent(score.instrument_period_return)),
        ("Cash return", lambda score: format_percent(getattr(score, "cash_return", None))),
        ("Excess over cash", lambda score: format_percent(getattr(score, "excess_over_cash", None))),
        ("Cash comparison", lambda score: str(getattr(score, "cash_comparison_status", "unavailable"))),
        ("Data date", lambda score: format_date(score.latest_date)),
        ("Coverage", lambda score: "available" if score.latest_price is not None else "partial/unavailable"),
        ("Execution authority", lambda _score: "disabled"),
    )


def comparison_frame(first: object, second: object) -> pd.DataFrame:
    """Return the displayed comparison rows as strings; missing values stay explicit."""
    records = [
        {"Measure": label, f"A: {first.display_id}": str(value(first)), f"B: {second.display_id}": str(value(second))}
        for label, value in _comparison_fields()
    ]
    return pd.DataFrame(records)


def _signed_cell(value: float | None) -> ft.Control:
    text = common.signed(value, 1, ratio=True)
    if text is None:
        return common.text("—", theme.FONT_MD, 400, theme.INK3, text_align=ft.TextAlign.RIGHT)
    tone = common.tone_of(value)
    colour = theme.POS if tone == "pos" else theme.NEG if tone == "neg" else theme.INK
    return common.text(text, theme.FONT_MD, 400, colour, text_align=ft.TextAlign.RIGHT)


def _row_values(label: str, score: object, ter: str, plain: object) -> object:
    """Cell for one aligned measure: kit controls for the spec rows, the canonical text for every other row."""
    if label == "Final score":
        return ScoreBar(getattr(score, "final_score_10", None))
    if label == "Evidence quality":
        text, kind = common.evidence_tag(score)
        return None if _is_missing(text) else Tag(text, kind, dense=True)
    if label == "Risk/friction":
        band = compare_view.risk_band(getattr(score, "risk_friction_10", None))
        return None if band is None else " · ".join(filter(None, (band, f"TER {ter}" if ter else "")))
    if label == "Period return":
        return _signed_cell(getattr(score, "instrument_period_return", None))
    if label == "Excess over cash":
        value = getattr(score, "excess_over_cash", None)
        return _signed_cell(value) if value is not None else plain
    if label == "Execution authority":
        return Tag("None", "bad", dense=True)
    return plain


_MISSING_WORDS = {"", "unavailable", "n/a", "na", "none", "nan"}
_STATUS_LABELS = {
    "available": "Available",
    "partial": "Partial",
    "unavailable": "Not recorded",
    "stale": "Stale",
    "not_evaluated": "Not evaluated",
    "insufficient_history": "Insufficient history",
    "missing": "Not recorded",
    "partial/unavailable": "Partial",
}


def _human_status(raw: str) -> str:
    return _STATUS_LABELS.get(raw.strip().casefold(), raw.strip().replace("_", " ").capitalize())


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().casefold() in _MISSING_WORDS)


def _comparison_table(first: object, second: object, *, ters: tuple[str, str] = ("", ""), max_rows: int = 14) -> ft.Container:
    rows = []
    missing_rows: list[str] = []
    raw_statuses: list[str] = []
    for label, value in _comparison_fields():
        if label in {"Instrument", "Name"}:
            continue  # the two dropdowns above already name both sides
        cells = []
        for score, ter in ((first, ters[0]), (second, ters[1])):
            plain: object = str(value(score))
            if label in {"Cash comparison", "Coverage"}:
                raw_statuses.append(f"{score.display_id}: {plain}")
                plain = plain if _is_missing(plain) else _human_status(str(plain))
            cell = _row_values(label, score, ter, plain)
            if _is_missing(cell):  # one form for a missing value in a table cell (rulebook V7)
                cell = None
                if label not in missing_rows:
                    missing_rows.append(label)
            cells.append(cell)
        rows.append({"measure": label, "a": cells[0], "b": cells[1]})
    columns = [
        TableColumn("measure", "Aligned evidence", flex=3, sortable=False),
        TableColumn("a", first.display_id, flex=3, numeric=True, sortable=False),
        TableColumn("b", second.display_id, flex=3, numeric=True, sortable=False),
    ]
    table = DataTable(columns, rows, row_height=_ROW_HEIGHT, max_visible_rows=max_rows, key="comparison.table")
    parts: list[ft.Control] = [table]
    if missing_rows:
        parts.append(Note(f"— = not recorded for this instrument ({', '.join(missing_rows)})."))
    if raw_statuses:
        parts.append(Disclosure("raw cash comparison status", "; ".join(raw_statuses)))
    return ft.Container(content=ft.Column(parts, spacing=8, tight=True), key="comparison.evidence")


def Dropdown(label: str, *, key: str, options: list[str], value: str, on_change: object) -> ft.Control:  # noqa: N802 - the acceptance scanner finds keyed inputs by this name
    return Field(label, options=options, value=value, on_change=on_change, expand=True, key=key)


def _workflow_button(label: str, *, key_name: str, on_click: object, primary: bool = False) -> ft.Container:
    return (Button.primary if primary else Button.secondary)(label, on_click, key=key_name)


def _option(score: object) -> str:
    return f"{score.display_id}  {score.name}"


def _workspace_card(width: float, height: float, page: object, state: AppState, scores: dict[str, object], ui: dict[str, str], rebuild: object) -> ft.Control:
    first, second = scores.get(ui["a"]), scores.get(ui["b"])
    options = {_option(score): key for key, score in scores.items()}
    status = Note("")
    status.max_lines = 2
    status_row = ft.Container(content=status, visible=False, expand=True)

    def say(message: str, ok: bool) -> None:
        status.value = message
        status.color = theme.POS if ok else theme.AMBER
        status_row.visible = True
        common.update(page)

    def render(side: str, label: str) -> None:
        ui[side] = options.get(label, ui[side])
        rebuild()

    def export_csv(_event: object) -> None:
        if first is None or second is None:
            say("CSV export unavailable: select two instruments from the canonical score set.", False)
            return
        result = export_table("comparison_aligned_evidence", comparison_frame(first, second), EXPORTS_DIR / "comparison_aligned_evidence.csv")
        if result.ok:
            say(f"Exported {result.rows} rows locally to {result.destination}; nothing was uploaded.", True)
        else:
            say(f"CSV export failed: {result.error or result.status}. No file was uploaded.", False)

    def save(_event: object) -> None:
        path = save_workspace(
            "latest-comparison",
            {
                "workspace_type": "instrument_comparison",
                "instrument_ids": [ui["a"], ui["b"]],
                "saved_at_data_date": state.snapshot.data_report.as_of_date,
                "evidence_mode": state.evidence_mode,
                "execution_allowed": False,
            },
        )
        say(f"Saved local comparison workspace: {path}", True)

    inner_w, inner_h = common.inner_size(width, height, insight=False)
    fields = ft.Row(
        [
            Dropdown("Instrument A", key="comparison.left", options=list(options), value=_option(first) if first else "", on_change=lambda label: render("a", label)),
            Dropdown("Instrument B", key="comparison.right", options=list(options), value=_option(second) if second else "", on_change=lambda label: render("b", label)),
        ],
        spacing=16,
    )
    export_button = _workflow_button("Export CSV", key_name="comparison.export-csv", on_click=export_csv)
    export_button.tooltip = _EXPORT_TIP
    save_button = _workflow_button("Save workspace", key_name="comparison.save-workspace", on_click=save, primary=True)
    buttons = ft.Row([save_button, export_button, status_row], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    if first is None or second is None:
        body: list[ft.Control] = [fields, EmptyState("Select two instruments", "Both comparison sides must be present in the canonical local score set.")]
    else:
        # fields 66, table header 44, buttons 36 and three 12 px gaps (the status text sits beside the buttons)
        rows = max(3, int((inner_h - 66 - 44 - 36 - 12) // _ROW_HEIGHT))
        ters = (common.instrument_meta(state, ui["a"])["ter"], common.instrument_meta(state, ui["b"])["ter"])
        body = [fields, _comparison_table(first, second, ters=ters, max_rows=rows), ft.Container(expand=True), buttons]
    column = ft.Column(body, spacing=12)
    return GlassCard("Comparison workspace", "EUR and percent", body=ft.Container(column, width=inner_w, height=inner_h), width=width, height=height)


def _hero_insight(ui: dict[str, str], ids: tuple[str, str], series: compare_view.HeroSeries) -> str:
    if series.reason or series.end_gap is None:
        return series.reason or "Unavailable."
    a, b = ids
    if ui["metric"] == "Risk":
        depth = format_number(abs(series.end_gap), decimals=1)
        return f"{a}'s deepest drawdown is {depth} pts {'shallower' if series.end_gap >= 0 else 'deeper'} than {b}'s over {ui['range']}."
    return f"{a} is {common.signed(series.end_gap, 1, '')} pts {'ahead of' if series.end_gap >= 0 else 'behind'} {b} over {ui['range']}."


def _hero_card(width: float, height: float, ui: dict[str, str], ids: tuple[str, str], series: compare_view.HeroSeries) -> ft.Control:
    title, note, y_name = _HERO[ui["metric"]]
    insight = _hero_insight(ui, ids, series)

    def chart(w: float, h: float) -> ft.Control:
        return ck.line_chart(
            series.x,
            [ck.Series(ids[0], series.a, ck.palette.P, 3.2, glow=True, decimals=1), ck.Series(ids[1], series.b, ck.palette.SECOND, 3.0, decimals=1)],
            x_name="Date", y_name=y_name, margins=ck.Margins(68, 26, 40, 56), legend_at="top-right", width=w, height=h,
            insight=insight, unavailable_reason=series.reason, empty_title="No comparison series",
        )

    return GlassCard(title, f"{ui['range']} · {note}", insight, body=common.chart_well(chart, width, height), width=width, height=height)


def _components_card(width: float, height: float, ids: tuple[str, str], axes: tuple[list[str], list[float | None], list[float | None], str | None]) -> ft.Control:
    labels, values_a, values_b, reason = axes
    lead_a = [name for name, x, y in zip(labels, values_a, values_b, strict=True) if x is not None and y is not None and x > y]
    lead_b = [name for name, x, y in zip(labels, values_a, values_b, strict=True) if x is not None and y is not None and y > x]
    if reason:
        insight = reason
    else:
        insight = f"{ids[0]} leads on {', '.join(lead_a) or 'no component'}; {ids[1]} leads on {', '.join(lead_b) or 'no component'}."

    def chart(w: float, h: float) -> ft.Control:
        return ck.radar_chart(
            labels,
            [
                ck.RadarSeries(ids[0], values_a, ck.palette.P, 3.0, fill_alpha=0.25),
                ck.RadarSeries(ids[1], values_b, ck.palette.SECOND, 3.0, fill_alpha=0.18),
            ],
            lo=0.0, hi=10.0, split_area=False, radius=0.62, center=(0.5, 0.46), legend_at="bottom",
            width=w, height=h, insight=insight, unavailable_reason=reason, empty_title="No score components",
        )

    return GlassCard("Score components", f"0–10 · {ids[0]} vs. {ids[1]}", insight, body=common.chart_well(chart, width, height), width=width, height=height)


def _gap_card(width: float, height: float, ids: tuple[str, str], gap: compare_view.GapSeries) -> ft.Control:
    known = [v for v in gap.values if v is not None]
    if gap.reason or not known:
        insight = gap.reason or "Unavailable."
    else:
        led = sum(1 for v in known if v > 0)
        insight = f"{ids[0]} led in {led} of {len(known)} months; the gap is now {common.signed(known[-1], 1, '')} pp."

    def chart(w: float, h: float) -> ft.Control:
        return ck.bar_chart(
            gap.labels, gap.values, x_name="Month-end", y_name="Gap (pp)", show_labels=False, bar_width=0.6, radius=4,
            label_size=11.5, label_every=6 if len(gap.labels) > 12 else 1, margins=ck.Margins(60, 20, 20, 50),
            width=w, height=h, insight=insight, unavailable_reason=gap.reason, empty_title="No return gap",
            series_name=f"{ids[0]} minus {ids[1]}",
        )

    return GlassCard("Rolling return gap", f"{ids[0]} minus {ids[1]} · percentage points", insight, body=common.chart_well(chart, width, height), width=width, height=height)


def comparison_page(page: ft.Page, state: AppState) -> PageView:
    scored = common.scores_for(state)
    if not scored:
        return PageView(PageChrome("Comparison", "No canonical score rows are available"), EmptyState("Comparison unavailable", "Import or refresh local evidence first; no values are inferred."))
    scores = {score.instrument_key: score for score in scored}
    keys = list(scores)
    left = state.selected_etf if state.selected_etf in scores else keys[0]
    ui = {"a": left, "b": next((item for item in keys if item != left), left), "metric": "Price", "range": "1Y"}
    holder = ft.Container()
    g = common.grid(page)
    history = load_score_history_summary()

    def build() -> ft.Control:
        first, second = scores[ui["a"]], scores[ui["b"]]
        ids = (first.display_id, second.display_id)
        prices = state.snapshot.prices
        if ui["metric"] == "Score":
            rows = {key: history.get(scores[key].display_id) or history.get(key) or () for key in (ui["a"], ui["b"])}
            series = compare_view.score_history(rows, ui["a"], ui["b"], ui["range"])
        elif ui["metric"] == "Risk":
            series = compare_view.drawdown_index(prices, ids[0], ids[1], ui["range"])
        else:
            series = compare_view.price_index(prices, ids[0], ids[1], ui["range"])
        axes = compare_view.component_axes(first, second)
        gap = compare_view.monthly_gap(prices, ids[0], ids[1], ui["range"])
        top = common.place(g, g.row_a, [
            (5, lambda w, h: _workspace_card(w, h, page, state, scores, ui, refresh)),
            (7, lambda w, h: _hero_card(w, h, ui, ids, series)),
        ])
        bottom = common.place(g, g.row_b, [
            (5, lambda w, h: _components_card(w, h, ids, axes)),
            (7, lambda w, h: _gap_card(w, h, ids, gap)),
        ])
        return common.below_fold(g, [top, bottom])

    def refresh() -> None:
        holder.content = build()
        common.update(page)

    def select_metric(label: str) -> None:
        ui["metric"] = label
        refresh()

    def select_range(label: str) -> None:
        ui["range"] = label
        refresh()

    holder.content = build()
    chrome = PageChrome(
        "Comparison",
        "Two instruments on aligned local evidence",
        (
            SegmentGroup("metric", compare_view.METRICS, ui["metric"], select_metric),
            SegmentGroup("range", _RANGES, ui["range"], select_range),
        ),
    )
    return PageView(chrome, holder)


__all__ = ["comparison_page"]
