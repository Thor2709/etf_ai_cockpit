from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import kit
from etf_cockpit.app.pages import _lab_style as lab


def _walk(control):
    yield control
    kids = getattr(control, "controls", None)
    if kids is None and getattr(control, "content", None) is not None:
        kids = [control.content]
    for kid in kids or []:
        yield from _walk(kid)


def test_panel_uses_kit_glass_with_key_and_label() -> None:
    built = lab.panel(ft.Column([lab.section_header("Model comparison", "note")]))
    assert built.key.startswith("lab.panel.")
    assert built.tooltip == "Model comparison"
    assert built.border_radius == kit.theme.CARD_RADIUS


def test_metric_card_is_kit_tile_and_never_blank() -> None:
    tile = lab.metric_card("Forecast rows", "", "as-of=unavailable")
    texts = [c.value for c in _walk(tile) if isinstance(c, ft.Text)]
    assert "Unavailable" in texts
    assert tile.key.startswith("lab.metric.forecast-rows")


def test_disabled_models_show_unavailable_with_reason() -> None:
    row = lab.model_status_row({"timesfm": False, "toto": True}, key_prefix="t")
    texts = [c.value for c in _walk(row) if isinstance(c, ft.Text)]
    assert "timesfm: Unavailable" in texts
    assert "toto: Available" in texts
    assert any("disabled-safe" in t for t in texts)
    keys = {c.key for c in _walk(row) if c.key}
    assert {"t.baseline", "t.timesfm", "t.toto"} <= keys


def test_missing_model_status_still_shows_baseline() -> None:
    row = lab.model_status_row(None, key_prefix="x")
    assert row.controls[0].key == "x.baseline"
    assert len(row.controls) == 1


def test_forecasts_alias_exports_forecast_lab() -> None:
    from etf_cockpit.app.pages import forecast_lab, forecasts

    assert forecasts.forecast_lab_page is forecast_lab.forecast_lab_page
