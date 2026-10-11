from __future__ import annotations

import math

from flet import canvas as cv

from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.chartkit.core import Hit, nice_ticks


def _scene(control):
    return ck.scene_of(control)


def test_palette_values_match_spec():
    assert ck.palette.P == "#9ad1ff" and ck.palette.BM == "#9aa6bd"
    assert ck.palette.GP == ("#8fdcbc", "#4fae88") and ck.palette.GOLD == ("#f0d79a", "#c9a45e")
    assert ck.palette.rgba("#9ad1ff", 0.5).startswith("#80")
    assert ck.palette.ramp_color(0) == ck.palette.RETURN_RAMP[0]
    assert ck.palette.ramp_color(1) == ck.palette.RETURN_RAMP[-1]


def test_radar_donut_and_gauge():
    axes = ["Quality", "Momentum", "Value", "Low vol", "Cost", "Data"]
    radar = ck.radar_chart(axes, [ck.RadarSeries("A", [78, 70, None, 74, 82, 95])])
    sc = _scene(radar)
    assert not sc.empty and all(a in sc.texts() for a in axes)
    assert any(r[1] == "—" for h in sc.hits for r in h.rows)  # missing axis shown as an em dash
    assert _scene(ck.radar_chart(axes, [ck.RadarSeries("A", [None] * 6)], unavailable_reason="No scores")).empty
    donut = ck.donut_chart([ck.Slice("Equity", 214, "#9ad1ff"), ck.Slice("Zero", 0, "#ffffff"), ck.Slice("Bond", 61, "#6fcfa6")])
    ds = _scene(donut)
    assert len(ds.hits) == 2 and "Equity\n214" in ds.texts()
    assert _scene(ck.donut_chart([])).empty
    g = _scene(ck.gauge(72))
    assert "72" in g.texts() and sum(isinstance(s, cv.Arc) for s in g.shapes) == 2
    none = _scene(ck.gauge(None, unavailable_reason="not evaluated"))
    assert "—" in none.texts() and sum(isinstance(s, cv.Arc) for s in none.shapes) == 1  # track only


def test_sector_hit_testing_is_clockwise_from_top():
    h = Hit("sector", (100, 100, 20, 50, -math.pi / 2, 0.0), "q", [])
    assert h.contains(120, 70) and not h.contains(80, 70) and not h.contains(100, 100)


def test_sankey_and_treemap():
    nodes = [ck.SankeyNode("a"), ck.SankeyNode("b"), ck.SankeyNode("c")]
    ok = _scene(ck.sankey(nodes, [ck.SankeyLink("a", "b", 4), ck.SankeyLink("b", "c", 4), ck.SankeyLink("a", "a", 9)]))
    assert not ok.empty and sum(isinstance(s, cv.Path) for s in ok.shapes) == 2
    assert _scene(ck.sankey(nodes, [])).empty
    assert _scene(ck.sankey(nodes, [ck.SankeyLink("a", "b", float("nan"))])).empty
    rects = ck.squarify([6, 3, 1], 0, 0, 100, 50)
    assert math.isclose(sum(w * h for _, _, w, h in rects), 5000.0, rel_tol=1e-9)
    tm = _scene(ck.treemap([ck.TreeItem("Tech", 25.0, 21.0), ck.TreeItem("RE", 2.0, None, short="RE"), ck.TreeItem("Zero", 0, 1)]))
    assert len(tm.hits) == 2 and any("Tech" in t and "+21.0%" in t for t in tm.texts())
    assert _scene(ck.treemap([], unavailable_reason="No sector data")).empty


def test_scatter_skips_missing_and_surface_requires_enough_data():
    pts = [ck.Bubble("A", 10, 20, 100, "Tech", True), ck.Bubble("B", None, 5, 50, "Tech"), ck.Bubble("C", 3, float("nan"), 5)]
    sc = _scene(ck.scatter_bubble(pts, x_name="P/E", y_name="ROE"))
    assert len(sc.hits) == 1 and "A" in sc.texts()
    empty = _scene(ck.scatter_bubble([]))
    assert empty.empty and empty.title == "No constituent fundamentals"
    few = _scene(ck.surface3d([[1, 2], [3, 4]], [1, 3], [10, 20]))
    assert few.empty and "3 horizons" in few.reason
    z = [[1 + c + r for c in range(4)] for r in range(3)]
    full = _scene(ck.surface3d(z, [1, 3, 6, 12], [10, 20, 30]))
    assert not full.empty and sum(isinstance(s, cv.Path) for s in full.shapes) >= 12 and len(full.hits) == 12


def test_nice_ticks_cover_range():
    ticks, lo, hi = nice_ticks(-6, 5, 5)
    assert lo <= -6 and hi >= 5 and ticks[0] == lo and ticks[-1] == hi
