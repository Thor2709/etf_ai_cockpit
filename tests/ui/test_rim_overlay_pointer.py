from __future__ import annotations

import flet as ft
import flet.canvas as cv

from etf_cockpit.app.components.kit.surfaces import _rim_overlay


def test_rim_overlay_ignores_pointer_input():
    rim = _rim_overlay(12)
    # Flet's Canvas hit-tests its whole area, so the decorative edge must sit inside a holder
    # that ignores pointer input; otherwise every click on the panel underneath is swallowed.
    assert isinstance(rim, ft.Container)
    assert rim.ignore_interactions is True
    assert isinstance(rim.content, cv.Canvas)
