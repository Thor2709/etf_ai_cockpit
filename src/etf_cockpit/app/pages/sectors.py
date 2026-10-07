"""Sectors & Countries page (FINAL_UI_SPEC 6.7): exposure strip, globe / map / bars, sector treemap and the
constituent bubble, country-return and return-distribution charts.

Everything shown is a projection of the read-only view model in ``application/ui_views/sectors.py``; a missing
value is "Unavailable" or an empty state with its reason, never zero.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.globe import Globe, WorldMap
from etf_cockpit.app.components.kit import EmptyState, FloatingPanel, GlassCard, KpiStrip, ScoreBar, Segmented, Well
from etf_cockpit.app.components.shell.page_view import PageView, SegmentGroup
from etf_cockpit.app.pages import _p2_common as shared
from etf_cockpit.app.pages import _p3_common as links
from etf_cockpit.app.pages import _p4_common as common
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_views import sectors as view

_UNAVAILABLE_COMPANIES = ("No constituent fundamentals", "Import benchmark holdings and fundamentals to compare companies.")
_REGION_ONLY = "Region level only · ETF holdings evidence missing"
_REGION_COLOURS = {"N. America": ck.palette.P, "Asia-Pacific": ck.palette.AMBER, "Europe": ck.palette.POS, "Other": ck.palette.CATEGORICAL[2]}
_GROUP_COLOURS = [(name, ck.palette.CATEGORICAL[index]) for index, name in enumerate(view.SECTOR_GROUPS[1:])]
_PANEL_WIDTH = 210
_TREEMAP_INSET = (6, 6, 76, 6)  # room for the colour legend labels (+21.0%)
_REGION_STRIP = 56  # region bar (16) + labels (20) + insets under the globe


def _pct(value: float | None, decimals: int = 1) -> str | None:
    return None if value is None else f"{value:.{decimals}f}%"


def _top_rows(countries: Sequence[view.Weight], count: int) -> ft.Control:
    """TOP COUNTRIES rows: name, weight bar, value."""
    top = sorted(countries, key=lambda item: -item.weight)[:count]
    peak = max((item.weight for item in top), default=1.0)
    rows = [
        ft.Row(
            [
                ft.Container(content=common.text(item.name, 12.5, 400, theme.INK, trunc=True), width=70),
                ScoreBar(item.weight, ck.palette.GOLD, maximum=peak, decimals=0 if item.weight >= 10 else 1),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        for item in top
    ]
    return ft.Column(rows, spacing=8, tight=True)


def _region_bar(shares: Sequence[tuple[str, float]], width: float) -> ft.Control:
    """Share bar (one segment per region) with its labels below."""
    track = width - 28
    segments = [
        ft.ProgressBar(value=1.0, color=_REGION_COLOURS[name], height=16, width=max(track * share / 100.0 - 1, 2.0))
        for name, share in shares
    ]
    labels = [common.text(f"{name} {share:.0f}%", 12, 400, theme.INK2, trunc=True) for name, share in shares]
    return ft.Column(
        [ft.Row(segments, spacing=1), ft.Row(labels, spacing=12, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)],
        spacing=8,
        tight=True,
    )


def _bars_view(countries: Sequence[view.Weight], width: float, height: float) -> ft.Control:
    top = sorted(countries, key=lambda item: -item.weight)[:15]
    peak = max((item.weight for item in top), default=1.0)
    rows = [
        ft.Row(
            [
                ft.Container(content=common.text(item.name, 12.5, 400, theme.INK, trunc=True), width=120),
                ScoreBar(item.weight, ck.palette.GB, maximum=peak, decimals=0 if item.weight >= 10 else 1),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        for item in top
    ]
    return Well(ft.Column(rows, spacing=12, scroll=ft.ScrollMode.AUTO), padding=16, width=width, height=height)


def _world_body(data: view.SectorsView, mode: str, width: float, height: float, on_mode: Callable[[str], None]) -> ft.Control:
    selector = Segmented(["Globe", "Map", "Bars"], mode, on_change=on_mode)
    well_h = max(height - 50, 160.0)
    if not data.countries:
        reason = data.exposure_reason or "No country exposure is available."
        return ft.Column([selector, Well(EmptyState("Exposure unavailable", reason), width=width, height=well_h)], spacing=12)
    if mode == "Bars":
        return ft.Column([selector, _bars_view(data.countries, width, well_h)], spacing=12)
    exposure = {item.code: item.weight for item in data.countries if item.code}
    reason = _REGION_ONLY if data.region_only else None if exposure else "No country exposure available"
    size = max(min(well_h - _REGION_STRIP, width - _PANEL_WIDTH - 24), 120.0)
    area = width - _PANEL_WIDTH - 24
    if mode == "Map":
        scene = WorldMap(exposure, reason, width=max(area, 160.0), height=size).control
        left = 12.0
    else:
        scene = Globe(exposure, reason, size=size, asset_base="globe").control
        left = max((area - size) / 2, 0.0) + 12
    panel = FloatingPanel("Top countries", _top_rows(data.countries, 5), width=_PANEL_WIDTH)
    shares = view.region_shares(data.countries, region_only=data.region_only)
    stage = ft.Stack(
        [
            ft.Container(content=scene, left=left, top=8),
            ft.Container(content=panel, right=12, top=12),
            ft.Container(content=_region_bar(shares, width), left=14, right=14, bottom=8) if shares else ft.Container(),
        ],
        width=width,
        height=well_h,
    )
    return ft.Column([selector, Well(stage, width=width, height=well_h)], spacing=12)


def _world_insight(data: view.SectorsView) -> str | None:
    if not data.countries:
        return None
    ordered = sorted(data.countries, key=lambda item: -item.weight)
    scope = "exposure" if not data.region_only else "region exposure"
    return f"{ordered[0].name} is {ordered[0].weight:.0f}% of {scope}; the top 5 {'regions' if data.region_only else 'countries'} make up {view.top_share(ordered, 5):.0f}%."


def _tile_at(items: Sequence[ck.TreeItem], x: float, y: float, width: float, height: float) -> ck.TreeItem | None:
    """The treemap tile under a click, using the same squarified layout and inset as ``ck.treemap``."""
    ordered = sorted((item for item in items if item.weight > 0), key=lambda item: -item.weight)
    left, top, right, bottom = _TREEMAP_INSET
    rects = ck.squarify([item.weight for item in ordered], left, top, width - left - right, height - top - bottom)
    for item, (rx, ry, rw, rh) in zip(ordered, rects, strict=True):
        if rx <= x <= rx + rw and ry <= y <= ry + rh:
            return item
    return None


def _sector_card_insight(sectors: Sequence[view.Weight], window: str) -> str | None:
    if not sectors:
        return None
    top = max(sectors, key=lambda item: item.weight)
    known = [item for item in sectors if item.ret is not None]
    if not known:
        return f"{top.name} is the largest sector ({top.weight:.1f}%); {window} returns are unavailable."
    best = max(known, key=lambda item: item.ret)  # type: ignore[arg-type,return-value]
    worst = min(known, key=lambda item: item.ret)  # type: ignore[arg-type,return-value]
    pick, word = (best, "best") if top is best or abs(best.ret or 0) >= abs(worst.ret or 0) else (worst, "worst")  # type: ignore[arg-type]
    ret = view.signed_pct(pick.ret) or "—"
    if pick is top:
        return f"{top.name} is the largest sector ({top.weight:.1f}%) and the {word} performer ({ret})."
    return f"{top.name} is the largest sector ({top.weight:.1f}%); {pick.name} is the {word} performer ({ret})."


def _treemap_items(sectors: Sequence[view.Weight]) -> list[ck.TreeItem]:
    return [ck.TreeItem(item.short or item.name, item.weight, item.ret, item.short) for item in sectors]


def _sector_body(data: view.SectorsView, mode: str, drill: str | None, width: float, height: float, handlers: dict[str, Callable]) -> ft.Control:
    selector = Segmented(["Treemap", "Sunburst", "Bars"], mode, on_change=handlers["mode"])
    well_h = max(height - 50, 160.0)
    if not data.sectors:
        reason = data.sector_reason or "No sector exposure is available."
        return ft.Column([selector, Well(EmptyState("Sector exposure unavailable", reason), width=width, height=well_h)], spacing=12)
    if mode == "Sunburst":
        chart = ck.donut_chart(
            [ck.Slice(item.name, item.weight, ck.palette.CATEGORICAL[index % len(ck.palette.CATEGORICAL)]) for index, item in enumerate(data.sectors)],
            unit="%", width=width, height=well_h, insight="Sector weights", empty_title="No sector data",
        )
        return ft.Column([selector, Well(chart, width=width, height=well_h)], spacing=12)
    if mode == "Bars":
        ordered = sorted(data.sectors, key=lambda item: -item.weight)
        peak = ordered[0].weight
        rows = [
            ft.Row(
                [
                    ft.Container(content=common.text(item.name, 12.5, 400, theme.INK, trunc=True), width=140),
                    ScoreBar(item.weight, ck.palette.GB, maximum=peak, decimals=0 if item.weight >= 10 else 1),
                    ft.Container(content=common.text(view.signed_pct(item.ret) or "—", 12.5, 500, theme.POS if (item.ret or 0) > 0 else theme.NEG if (item.ret or 0) < 0 else theme.INK3, text_align=ft.TextAlign.RIGHT), width=56),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            for item in ordered
        ]
        return ft.Column([selector, Well(ft.Column(rows, spacing=12, scroll=ft.ScrollMode.AUTO), padding=16, width=width, height=well_h)], spacing=12)
    chosen = next((item for item in data.sectors if item.name == drill), None)
    if chosen is not None and chosen.parts:
        items = [ck.TreeItem(name, weight, None, name) for name, weight in chosen.parts if weight > 0]
        crumb = links.link(f"All sectors › {chosen.name}", handlers["back"], key=None)
    else:
        items = _treemap_items(data.sectors)
        crumb = None
    chart = ck.treemap(items, inset=_TREEMAP_INSET, width=width, height=well_h, insight=_sector_card_insight(data.sectors, data.window), empty_title="No sector data")

    def tapped(event: ft.TapEvent) -> None:
        if chosen is not None:
            return
        tile = _tile_at(items, event.local_position.x, event.local_position.y, width, well_h)
        if tile is not None:
            handlers["drill"](next((item.name for item in data.sectors if (item.short or item.name) == tile.name), tile.name))

    pad = ft.Container(content=crumb, left=16, top=12) if crumb else ft.Container()
    stage = ft.Stack([ft.GestureDetector(content=chart, on_tap_down=tapped), pad], width=width, height=well_h)
    return ft.Column([selector, Well(stage, width=width, height=well_h)], spacing=12)


def _metric_axes(metric: str) -> tuple[str, str, str, str]:
    """x name, y name, x unit, y unit for the selected bubble metric."""
    if metric == "P/B":
        return "P/B ratio (×)", "Return on equity (%)", "×", "%"
    if metric == "ROE":
        return "Return on equity (%)", "P/E ratio (×)", "%", "×"
    return "P/E ratio (×)", "Return on equity (%)", "×", "%"


def _bubble_points(data: view.SectorsView, metric: str) -> list[ck.Bubble]:
    points = []
    for item in data.bubbles:
        if metric == "ROE":
            x, y = item.roe, item.pe
        else:
            x, y = (item.pb if metric == "P/B" else item.pe), item.roe
        points.append(ck.Bubble(item.name, x, y, item.cap, item.group, item.highlight))
    return points


def _bubble_insight(data: view.SectorsView) -> str | None:
    named = [item for item in data.bubbles if item.highlight and item.pe is not None and item.roe is not None]
    if named:
        return " ".join(f"{item.name}: {item.pe:.1f}× P/E at {item.roe:.0f}% ROE." for item in named[:2])
    pes = [item.pe for item in data.bubbles if item.pe is not None]
    roes = [item.roe for item in data.bubbles if item.roe is not None]
    if not pes or not roes:
        return None
    return f"{len(data.bubbles)} constituents; median P/E {statistics.median(pes):.1f}× at median ROE {statistics.median(roes):.0f}%."


def _country_chart(data: view.SectorsView, width: float, height: float, window: str) -> tuple[ft.Control, str | None]:
    top = sorted(data.countries, key=lambda item: -item.weight)[:8]
    cap = 12.0 if top and top[0].weight > 12.0 else None
    returns = [item.ret for item in top]
    leader = max((item for item in top if item.ret is not None), key=lambda item: item.ret, default=None)  # type: ignore[arg-type,return-value]
    parts = []
    if leader is not None:
        parts.append(f"{leader.name} leads {window} return ({view.signed_pct(leader.ret)}) on a {leader.weight:.1f}% weight.")
    if cap and top:
        parts.append(f"{top[0].name} bar is cut at {cap:.0f}%.")
    insight = " ".join(parts) or (None if not top else f"{window} returns are unavailable for these exposures.")
    chart = ck.grouped_bar_chart(
        [item.short or item.name[:2].upper() for item in top],
        [ck.BarSeries("Exposure %", [item.weight for item in top], "blue")],
        line_series=ck.LineSeries(f"{window} return %", returns) if any(value is not None for value in returns) else None,
        x_name="Country", y_name="Exposure (% of portfolio)", y2_name=f"{window} return (%)", y_max=cap, bar_width=0.46,
        margins=ck.Margins(58, 56, 36, 50), width=width, height=height, insight=insight, empty_title="No country exposure",
        unavailable_reason=None if top else (data.exposure_reason or "No country exposure is available."),
    )
    return chart, insight


def sectors_page(page: ft.Page | None, state: AppState) -> PageView:
    layout = common.make_layout(page, strip=True)
    ui: dict[str, object] = {"perspective": "Country", "metric": "P/E", "window": "1Y", "world": "Globe", "sector": "Treemap", "group": "All", "drill": None}
    data = {"view": view.load(state.snapshot, str(ui["window"]))}
    hosts = {name: ft.Container() for name in ("strip", "world", "sector", "bubble", "country", "histogram")}

    def refresh(*names: str) -> None:
        builders = {"strip": strip_card, "world": world_card, "sector": sector_card, "bubble": bubble_card, "country": country_card, "histogram": histogram_card}
        for name in names:
            hosts[name].content = builders[name]()
            common.refresh(hosts[name])

    # ----- KPI strip -----
    def strip_card() -> ft.Control:
        d: view.SectorsView = data["view"]  # type: ignore[assignment]
        perspective = str(ui["perspective"])
        items = {"Sector": d.sectors, "Country": d.countries, "Company": d.companies}[perspective]
        noun = {"Sector": "sector", "Country": "country", "Company": "company"}[perspective]
        word = {"Sector": "sectors", "Country": "countries", "Company": "companies"}[perspective]
        reason = d.exposure_reason or f"No {noun} exposure is available."
        headline, sub = view.headline(items, perspective)
        top = max(items, key=lambda item: item.weight) if items else None
        top5 = view.top_share(items, 5)
        hhi, band = view.concentration(items)
        delta, tone = (None, None)
        if top is not None and perspective == "Country" and d.benchmark_top_country is not None:
            gap = top.weight - d.benchmark_top_country
            delta, tone = f"{view.signed_pct(gap, 1, ' pts')} vs. benchmark", "neg" if gap > 0 else "pos"
        elif top is not None and perspective == "Country":
            delta = "Benchmark exposure unavailable"
        largest = max(d.sectors, key=lambda item: item.weight) if d.sectors else None
        ret = view.signed_pct(largest.ret) if largest is not None else None
        sector_delta = f"{ret} {d.window}" if ret else (f"{d.window} return unavailable" if largest is not None else reason)
        entries = [
            (f"Top-1 {noun}", _pct(top.weight) if top else None, delta or ("" if top else reason), tone),
            (f"Top-5 {word}", _pct(top5), "of portfolio" if top5 is not None else reason, None),
            ("Concentration (HHI)", None if hhi is None else f"{hhi:.2f}", (band or "").capitalize() if hhi is not None else reason, {"high": "neg", "low": "pos"}.get(band or "")),
            ("Largest sector", f"{largest.short or largest.name} {largest.weight:.1f}%" if largest else None, sector_delta, "pos" if (largest and (largest.ret or 0) > 0) else "neg" if (largest and (largest.ret or 0) < 0) else None),
        ]
        return KpiStrip("Headline", headline or "Unavailable", sub or reason, entries, key="sectors.strip")

    # ----- World exposure -----
    def world_card() -> ft.Control:
        d: view.SectorsView = data["view"]  # type: ignore[assignment]
        width, height = layout.card_body(6, 1, insight=True)

        def set_mode(label: str) -> None:
            ui["world"] = label
            refresh("world")

        note = _REGION_ONLY if d.region_only and d.countries else "% of portfolio · satellite view"
        return shared.title_first(GlassCard("World exposure", note, _world_insight(d), body=ft.Container(content=_world_body(d, str(ui["world"]), width, height, set_mode), width=width, height=height), width=layout.span_width(6), height=layout.row_heights[1]), "World exposure")

    # ----- Sector overview -----
    def sector_card() -> ft.Control:
        d: view.SectorsView = data["view"]  # type: ignore[assignment]
        width, height = layout.card_body(6, 1, insight=True)

        def set_mode(label: str) -> None:
            ui["sector"], ui["drill"] = label, None
            refresh("sector")

        def drill(name: str) -> None:
            ui["drill"] = name
            refresh("sector")

        def back(_event: object = None) -> None:
            ui["drill"] = None
            refresh("sector")

        body = _sector_body(d, str(ui["sector"]), ui["drill"], width, height, {"mode": set_mode, "drill": drill, "back": back})  # type: ignore[arg-type]
        return shared.title_first(GlassCard("Sector overview", f"size = weight (%) · colour = {d.window} return · click a tile to drill down", _sector_card_insight(d.sectors, d.window), body=ft.Container(content=body, width=width, height=height), width=layout.span_width(6), height=layout.row_heights[1]), "Sector overview")

    # ----- Benchmark vs. analysed companies -----
    def bubble_card() -> ft.Control:
        d: view.SectorsView = data["view"]  # type: ignore[assignment]
        width, height = layout.card_body(5, 2, insight=True)
        metric, group = str(ui["metric"]), str(ui["group"])
        x_name, y_name, x_unit, y_unit = _metric_axes(metric)

        def set_group(label: str) -> None:
            ui["group"] = label
            refresh("bubble")

        well_h = max(height - 50, 140.0)
        chart = ck.scatter_bubble(
            _bubble_points(d, metric),
            groups=_GROUP_COLOURS,
            active_group=None if group == "All" else group,
            x_name=x_name, y_name=y_name, x_unit=x_unit, y_unit=y_unit,
            margins=ck.Margins(62, 18, 34, 48), width=width, height=well_h, insight=_bubble_insight(d),
            unavailable_reason=d.bubbles_reason, empty_title=_UNAVAILABLE_COMPANIES[0],
        )
        note = {"P/E": "P/E vs. ROE", "P/B": "P/B vs. ROE", "ROE": "ROE vs. P/E"}[metric] + " · bubble = market cap"
        body = ft.Column([Segmented(list(view.SECTOR_GROUPS), group, on_change=set_group), Well(chart, width=width, height=well_h)], spacing=12)
        return shared.title_first(GlassCard("Benchmark vs. analysed companies", note, _bubble_insight(d), quiet=True, body=ft.Container(content=body, width=width, height=height), width=layout.span_width(5), height=layout.row_heights[2]), "Benchmark vs. analysed companies")

    # ----- Country exposure vs. return -----
    def country_card() -> ft.Control:
        d: view.SectorsView = data["view"]  # type: ignore[assignment]
        width, height = layout.card_body(4, 2, insight=True)
        chart, insight = _country_chart(d, width, height, d.window)
        return shared.title_first(GlassCard("Country exposure vs. return", f"% · {d.window} return %", insight, quiet=True, body=Well(chart, width=width, height=height), width=layout.span_width(4), height=layout.row_heights[2]), "Country exposure vs. return")

    # ----- Distribution of returns -----
    def histogram_card() -> ft.Control:
        d: view.SectorsView = data["view"]  # type: ignore[assignment]
        width, height = layout.card_body(3, 2, insight=True)
        counts, negatives, total = view.histogram_counts([item.ret for item in d.bubbles])
        insight = view.histogram_insight(counts, negatives, total)
        chart = ck.histogram(
            list(view.HISTOGRAM_BINS), counts if total else [], negative=[index < 3 for index in range(len(counts))],
            x_name=f"{d.window} return, bin start (%)", width=width, height=height, insight=insight,
            unavailable_reason=None if total else "No constituent returns are stored for this window.", empty_title="No constituent returns",
        )
        return shared.title_first(GlassCard(f"Distribution of {d.window} returns", "companies per return bin", insight, quiet=True, body=Well(chart, width=width, height=height), width=layout.span_width(3), height=layout.row_heights[2]), f"Distribution of {d.window} returns")

    refresh("strip", "world", "sector", "bubble", "country", "histogram")
    body = common.grid(
        layout,
        [
            [(hosts["strip"], 12)],
            [(hosts["world"], 6), (hosts["sector"], 6)],
            [(hosts["bubble"], 5), (hosts["country"], 4), (hosts["histogram"], 3)],
        ],
    )

    def select_perspective(label: str) -> None:
        ui["perspective"] = label
        refresh("strip")

    def select_metric(label: str) -> None:
        ui["metric"] = label
        refresh("bubble")

    def select_window(label: str) -> None:
        ui["window"], ui["drill"] = label, None
        data["view"] = view.load(state.snapshot, label)
        refresh("strip", "world", "sector", "bubble", "country", "histogram")

    groups = (
        SegmentGroup("perspective", list(view.PERSPECTIVES), "Country", select_perspective),
        SegmentGroup("metric", list(view.METRICS), "P/E", select_metric),
        SegmentGroup("window", list(view.WINDOWS), "1Y", select_window),
    )
    return common.page_view("Sectors & Countries", "Global exposure · benchmark vs. analysed companies", body, groups)
