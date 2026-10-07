from __future__ import annotations

import math
from datetime import date, timedelta

from flet import canvas as cv

from etf_cockpit.app.components import chartkit as ck


def _scene(control):
    return ck.scene_of(control)


def _rect_count(scene):
    return sum(isinstance(s, cv.Rect) for s in scene.shapes)


def test_bar_chart_empty_and_unavailable_show_reason():
    empty = ck.bar_chart([], [])
    assert _scene(empty).empty and _scene(empty).reason
    gated = ck.bar_chart(["a"], [1.0], unavailable_reason="Fewer than 20 matured forecasts")
    assert _scene(gated).empty
    assert _scene(gated).reason == "Fewer than 20 matured forecasts"
    all_nan = ck.bar_chart(["a", "b"], [float("nan"), None])
    assert _scene(all_nan).empty


def test_bar_chart_filled_signed_labels_and_missing_not_zero():
    chart = ck.bar_chart(["A", "B", "C"], [5, float("nan"), -3], x_name="Instrument", y_name="Score change (points)")
    sc = _scene(chart)
    assert not sc.empty and _rect_count(sc) >= 4  # 2 bars x (fill + border)
    texts = sc.texts()
    assert "+5.0" in texts and "−3.0" in texts
    assert "Instrument" in texts and "Score change (points)" in texts
    assert len(sc.hits) == 2  # the NaN category has no hover target and no bar


def test_grouped_bar_clips_above_cap_and_has_secondary_axis():
    chart = ck.grouped_bar_chart(
        ["USA", "JP"], [ck.BarSeries("Exposure %", [62, 5.5])],
        line_series=ck.LineSeries("1Y return %", [12, None]), y_max=12, y2_name="1Y return (%)")
    sc = _scene(chart)
    assert any("▲" in t for t in sc.texts())
    assert "1Y return (%)" in sc.texts()
    assert sum(isinstance(s, cv.Circle) for s in sc.shapes) == 3  # one point (fill + ring, JP gap) + legend marker


def test_histogram_and_stacked_bar_smoke():
    h = ck.histogram(["<-20", "0", "10"], [3, 9, 14], negative=[True, False, False], x_name="1Y return")
    assert not _scene(h).empty and len(_scene(h).hits) == 3
    s = ck.horizontal_stacked_bar(
        ["Fold 2", "Fold 1"], [[ck.Segment(10, "pos"), ck.Segment(3, "gold")], [ck.Segment(6)]], x_name="Months")
    assert not _scene(s).empty and len(_scene(s).hits) == 3
    assert _scene(ck.horizontal_stacked_bar([], [])).empty


def test_line_chart_gaps_break_the_line_and_never_zero_fill():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(6)]
    chart = ck.line_chart(days, [ck.Series("A", [1, 2, None, float("nan"), 3, 4])], x_name="Date", y_name="Price")
    sc = _scene(chart)
    paths = [s for s in sc.shapes if isinstance(s, cv.Path) and s.paint.stroke_width == 3.0]
    assert len(paths) == 2  # two runs, not one line through a fake zero
    assert len(sc.hits) == 4 and all(h.rows for h in sc.hits)


def test_line_chart_empty_and_forecast_extras():
    assert _scene(ck.line_chart([], [])).empty
    assert _scene(ck.line_chart(["a"], [ck.Series("s", [None])])).empty
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(10)]
    vals = [10 + i for i in range(5)] + [None] * 5
    fc = [None] * 4 + [14, 15, 16, 17, 18, 19]
    chart = ck.line_chart(
        days, [ck.Series("Close", vals), ck.Series("Model", fc, glow=True)],
        bands=[ck.Band("80%", [None] * 4 + [13] * 6, [None] * 4 + [16] * 6)],
        events=[ck.EventMark(1)], today=days[4])
    sc = _scene(chart)
    assert "today" in sc.texts() and "Div" in sc.texts()


def test_price_drawdown_and_sparkline():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(30)]
    close = [100 + math.sin(i / 3) * 3 for i in range(30)]
    dd = [min(0.0, v - 103) for v in close]
    hero = ck.price_drawdown_chart(days, [ck.Series("Close", close)], dd, price_name="Price (EUR)")
    sc = _scene(hero)
    assert "Price (EUR)" in sc.texts() and "Drawdown (%)" in sc.texts() and "Date" in sc.texts()
    assert any(r[0] == "Drawdown" for h in sc.hits for r in h.rows)
    assert _scene(ck.drawdown_panel(days, dd)).empty is False
    assert _scene(ck.sparkline(close)).empty is False
    assert _scene(ck.sparkline([1.0])).empty and _scene(ck.sparkline([])).empty


def test_resize_rebuilds_scene():
    chart = ck.bar_chart(["a", "b"], [1, 2], width=300, height=200)
    before = _scene(chart)
    chart.data.resize(500, 260)
    assert _scene(chart) is not before and _scene(chart).width == 500 and chart.width == 500
