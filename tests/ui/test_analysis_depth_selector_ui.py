from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app.components.depth_selector import summarise_depth
from etf_cockpit.app.router import build_shell
from etf_cockpit.app.state import AppState
from etf_cockpit.application.analysis_depth import AnalysisTimingRecord
from etf_cockpit.application.snapshot_builder import build_snapshot


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


class _DialogPage(_Page):
    height = 900

    def __init__(self):
        super().__init__()
        self.dialog = None

    def show_dialog(self, dialog):
        self.dialog = dialog

    def pop_dialog(self):
        self.dialog = None


def _open_dialog(state, page, view):
    """The depth selector lives in the footer-opened Analysis depth dialog (spec 5.5)."""
    _by_key(view, "shell.as-of.analysis-depth").on_click(None)
    return page.dialog.content


def _segments(control):
    return {c.data["value"]: c for c in _walk(control) if isinstance(c.data, dict) and c.data.get("kit") == "Segment"}


def test_dialog_renders_four_options_and_footer_starts_unavailable(snapshot) -> None:
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _DialogPage()
    view = build_shell(page, state, "/")
    chip = _by_key(view, "shell.as-of.analysis-depth")
    assert "Unavailable" in _texts(chip) and chip.data == "unavailable" and chip.tooltip
    dialog = _open_dialog(state, page, view)
    selector = _by_key(dialog, "shell.depth-dialog.depth")
    assert list(_segments(selector)) == ["Quick", "Medium", "High", "Full"]
    assert not any(segment.data["selected"] for segment in _segments(selector).values())  # nothing pretends to be chosen


def test_choice_updates_app_state_and_footer(snapshot) -> None:
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _DialogPage()
    view = build_shell(page, state, "/")
    dialog = _open_dialog(state, page, view)
    _segments(_by_key(dialog, "shell.depth-dialog.depth"))["High"].on_click(None)
    chip = _by_key(view, "shell.as-of.analysis-depth")
    assert state.analysis_depth == "high"
    assert "High" in _texts(chip) and chip.data == "available"
    assert page.updates >= 1
    assert "High profile stages" in " ".join(_texts(dialog))
    with pytest.raises(ValueError):
        state.set_analysis_depth("turbo")
    assert state.analysis_depth == "high"


def test_restored_choice_renders_selected_in_new_shell(snapshot) -> None:
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.set_analysis_depth("quick")
    page = _DialogPage()
    view = build_shell(page, state, "/")
    assert "Quick" in _texts(_by_key(view, "shell.as-of.analysis-depth"))
    selector = _by_key(_open_dialog(state, page, view), "shell.depth-dialog.depth")
    assert [name for name, segment in _segments(selector).items() if segment.data["selected"]] == ["Quick"]


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
