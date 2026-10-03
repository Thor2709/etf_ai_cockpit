from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app.components.depth_selector import DETAIL_KEY, SELECTOR_KEY, summarise_depth
from etf_cockpit.app.router import build_shell
from etf_cockpit.app.state import AppState
from etf_cockpit.application.analysis_depth import AnalysisTimingRecord
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for name in ("content", "controls", "title", "leading", "trailing", "actions"):
        child = getattr(control, name, None)
        if isinstance(child, (list, tuple)):
            for item in child:
                if item is not None:
                    yield from _walk(item)
        elif child is not None and hasattr(child, "__dict__"):
            yield from _walk(child)
    for view in getattr(control, "views", None) or ():
        yield from _walk(view)


def _by_key(root, key):
    return next(c for c in _walk(root) if getattr(c, "key", None) == key)


def _texts(control):
    return [str(c.value) for c in _walk(control) if isinstance(c, ft.Text)]


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


class _Page:
    width = 1920
    route = "/"

    def __init__(self):
        self.updates = 0

    def update(self):
        self.updates += 1


def _shell(snapshot):
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _Page()
    return state, page, build_shell(page, state, "/")


def test_selector_renders_four_options_and_chip_starts_unavailable(snapshot) -> None:
    _state, _page, view = _shell(snapshot)
    selector = _by_key(view, SELECTOR_KEY)
    assert [option.key for option in selector.options] == ["quick", "medium", "high", "full"]
    assert [option.text for option in selector.options] == ["Quick", "Medium", "High", "Full"]
    assert selector.value is None
    chip = _by_key(view, "shell.as-of.analysis-depth")
    assert "Unavailable" in _texts(chip) and chip.data == "unavailable" and chip.tooltip


def test_choice_updates_app_state_and_chip(snapshot) -> None:
    state, page, view = _shell(snapshot)
    selector = _by_key(view, SELECTOR_KEY)
    selector.value = "high"
    selector.on_select(SimpleNamespace(control=selector, data="high"))
    chip = _by_key(view, "shell.as-of.analysis-depth")
    assert state.analysis_depth == "high"
    assert "High" in _texts(chip) and chip.data == "available"
    assert page.updates >= 1
    assert "SLO target" in _by_key(view, DETAIL_KEY).value
    with pytest.raises(ValueError):
        state.set_analysis_depth("turbo")
    assert state.analysis_depth == "high"


def test_restored_choice_renders_selected_in_new_shell(snapshot) -> None:
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.set_analysis_depth("quick")
    view = build_shell(_Page(), state, "/")
    assert _by_key(view, SELECTOR_KEY).value == "quick"
    assert "Quick" in _texts(_by_key(view, "shell.as-of.analysis-depth"))


def test_unavailable_measurements_say_unavailable_never_zero(tmp_path) -> None:
    summary = summarise_depth("full", root=tmp_path, timing_reader=lambda _root, _depth: [])
    assert not summary.measured_available
    assert "Unavailable" in summary.measured and "no measured timings" in summary.measured
    assert summary.reason and "0.0" not in summary.measured
    assert "SLO target" in summary.slo_target

    def broken(_root, _depth):
        raise OSError("disk")

    assert "Unavailable" in summarise_depth("quick", root=tmp_path, timing_reader=broken).measured


def test_measured_timings_are_projected_without_certification_claim(tmp_path) -> None:
    records = [
        AnalysisTimingRecord("r1", "medium", "stage", "s", seconds, "warm") for seconds in (10.0, 20.0, 30.0)
    ]
    summary = summarise_depth("medium", root=tmp_path, timing_reader=lambda _r, _d: records)
    assert summary.measured_available
    assert "p50 20.0 s" in summary.measured and "n=3" in summary.measured
    assert "not claimed" in summary.measured
