from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import flet as ft
import flet.canvas as cv
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.globe import Globe
from etf_cockpit.app.components.kit import GlassCard, KpiTile
from etf_cockpit.app.pages import forecast_lab, sectors, stock_research


def _walk(control: object):
    if not isinstance(control, ft.Control):
        return
    yield control
    for child in getattr(control, "controls", None) or ():
        yield from _walk(child)
    for child in getattr(control, "items", None) or ():
        yield from _walk(child)
    yield from _walk(getattr(control, "content", None))


def test_globe_backed_labels_are_optional_bounded_rotating_and_replace_page_overlay() -> None:
    exposure = {"USA": 62.0, "JPN": 5.5, "FRA": 4.0}
    plain = Globe(exposure, size=300)
    assert not any(isinstance(shape, cv.Rect) for shape in plain.overlay.shapes)
    assert any(isinstance(shape, cv.Text) for shape in plain.overlay.shapes)

    backed = Globe(exposure, size=300, label_backing=True)
    plates = [shape for shape in backed.overlay.shapes if isinstance(shape, cv.Rect)]
    assert plates and any(shape.paint.color == theme.WELL_FILL for shape in plates)
    assert all(shape.x >= 4 and shape.y >= 4 for shape in plates)
    assert all(shape.x + shape.width <= 296 and shape.y + shape.height <= 296 for shape in plates)
    label = next(shape for shape in backed.overlay.shapes if isinstance(shape, cv.Text))
    assert label.alignment == ft.Alignment(-1, -1) and label.text_align == ft.TextAlign.LEFT
    before = [(shape.x, shape.y) for shape in plates]
    backed.rotate_to(120)
    after = [(shape.x, shape.y) for shape in backed.overlay.shapes if isinstance(shape, cv.Rect)]
    assert before != after

    page_source = inspect.getsource(sectors)
    assert not hasattr(sectors, "_PillGlobe") and not hasattr(sectors, "_pill_layer")
    assert "_screen" not in page_source and "label_backing=True" in page_source


def test_horizontal_stacked_bar_legend_is_opt_in_and_forecast_page_uses_it() -> None:
    rows = ["Fold 1"]
    segments = [[ck.Segment(10, "pos"), ck.Segment(2, "gold")]]
    plain = ck.horizontal_stacked_bar(rows, segments)
    assert not {"Train window", "Test fold"} & set(ck.scene_of(plain).texts())

    legend = [
        ck.LegendItem("Train window", ck.palette.BAR_KINDS["pos"][0], "bar"),
        ck.LegendItem("Test fold", ck.palette.BAR_KINDS["gold"][0], "bar"),
    ]
    shown = ck.horizontal_stacked_bar(rows, segments, legend=legend)
    assert {"Train window", "Test fold"} <= set(ck.scene_of(shown).texts())
    assert "_fold_legend" not in inspect.getsource(forecast_lab)


def test_grouped_bar_clip_marker_has_clearance_and_sectors_uses_chart_defaults(monkeypatch) -> None:
    chart = ck.grouped_bar_chart(
        ["USA"], [ck.BarSeries("Exposure %", [62.0], "blue")], y_max=12,
        margins=ck.Margins(58, 56, 36, 50), width=400, height=300,
    )
    scene = ck.scene_of(chart)
    marker = next(shape for shape in scene.shapes if isinstance(shape, cv.Text) and "▲" in shape.value)
    assert marker.y - marker.style.size / 2 >= 40
    assert marker.y < 300 - 50

    calls: dict[str, object] = {}

    def capture(categories, bars, **kwargs):
        calls.update(categories=categories, bars=bars, kwargs=kwargs)
        return ft.Container()

    monkeypatch.setattr(sectors.ck, "grouped_bar_chart", capture)
    model = SimpleNamespace(countries=[SimpleNamespace(weight=15.0, ret=None, short="US", name="United States")], exposure_reason=None)
    sectors._country_chart(model, 400, 300, "1Y")
    assert "bar_width" not in calls["kwargs"]
    series = calls["bars"][0]
    assert series.kind == "blue" and series.color is None


def test_kpi_attention_tone_is_amber_and_forecast_promotion_uses_it(monkeypatch) -> None:
    tile = KpiTile("Promotion", "Shadow only", "execution off", tone="attention")
    assert tile.content.controls[1].style.color == theme.AMBER

    captured: dict[str, object] = {}

    def capture(items):
        captured["items"] = items
        return ft.Container()

    monkeypatch.setattr(forecast_lab.common, "tile_grid", capture)
    report = {"models": pd.DataFrame(), "walk_forward_splits": [], "model_catalogue": pd.DataFrame(), "status": "ok", "notes": []}
    state = SimpleNamespace(
        snapshot=SimpleNamespace(model_status={}), current_activity=None, recent_activity=(),
        run_forecasting_models=lambda: None,
    )
    layout = SimpleNamespace(card_body=lambda *_args, **_kwargs: (500, 300), span_width=lambda _span: 500, row_heights=[300, 300])
    forecast_lab._run_card(layout, None, state, report, lambda: None)
    assert captured["items"][3][3] == "attention"


def test_forecast_status_filters_reasons_and_humanizes_no_net_edge() -> None:
    report = {
        "models": pd.DataFrame(),
        "walk_forward_splits": [],
        "model_catalogue": pd.DataFrame({"model_id": ["baseline"], "display_name": ["Baseline"]}),
        "status": "ok",
        "notes": [],
    }
    state = SimpleNamespace(
        snapshot=SimpleNamespace(model_status={"baseline": True, "Reasons": {"baseline": "local row"}}),
        current_activity=None, recent_activity=(), run_forecasting_models=lambda: None,
    )
    layout = SimpleNamespace(card_body=lambda *_args, **_kwargs: (500, 300), span_width=lambda _span: 500, row_heights=[300, 300])
    card = forecast_lab._run_card(layout, None, state, report, lambda: None)
    notes = [control.value for control in _walk(card) if isinstance(control, ft.Text)]
    cached = next(note for note in notes if note.startswith("Conformal intervals are diagnostic"))
    assert "Cached model status: Baseline." in cached and "Reasons" not in cached

    cell = forecast_lab._net_cell("+1.0%", "no_net_edge")
    labels = [control.value for control in _walk(cell) if isinstance(control, ft.Text)]
    assert "no net edge" in labels and "no_net_edge" not in labels


def test_stock_research_uses_scaled_spacing_and_kit_text() -> None:
    source = inspect.getsource(stock_research)
    tree = ast.parse(source)
    scale = {0, 4, 8, 12, 16, 20, 24, 28}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in {"spacing", "padding", "run_spacing", "margin"} and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, (int, float)):
                    assert keyword.value.value in scale
        assert not (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "ft" and node.func.attr == "Text")
    assert "Note(" in source


def test_glass_card_long_title_uses_row_width_and_ellipsis() -> None:
    title_text = "A GlassCard title that is much wider than this entire row"
    card = GlassCard(title_text, "note", width=160)
    row = next(control for control in _walk(card) if isinstance(control, ft.Row) and len(control.controls) == 2)
    title = row.controls[0]
    available = 160 - 2 * theme.CARD_PADDING[1] - 8
    assert title.width == available
    assert title.max_lines == 1 and title.overflow == ft.TextOverflow.ELLIPSIS and title.tooltip == title_text
