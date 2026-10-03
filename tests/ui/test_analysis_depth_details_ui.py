from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.components.depth_selector import (
    COMPARE_KEY,
    DETAILS_KEY,
    certification_line,
    compare_depths,
    depth_details_view,
    depth_selector,
    omitted_evidence,
    timing_history,
)
from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.analysis_depth import AnalysisTimingRecord
from etf_cockpit.application.settings import load_settings_bundle
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


def _by_key(root, key):
    return next(c for c in _walk(root) if getattr(c, "key", None) == key)


def _texts(control):
    return [str(c.value) for c in _walk(control) if isinstance(c, ft.Text)]


def test_header_choice_persists_to_settings_and_settings_page_follows(tmp_path) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf, settings_root=tmp_path)
    assert load_settings_bundle(tmp_path).controls.analysis_depth == "medium"  # Settings default unchanged
    state.set_analysis_depth("full")
    assert "saved to Settings" in state.persist_analysis_depth("full")
    assert load_settings_bundle(tmp_path).controls.analysis_depth == "full"
    assert "already saved" in state.persist_analysis_depth("full")
    unbound = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    assert "session only" in unbound.persist_analysis_depth("quick")  # nothing written, honest message
    state.analysis_depth = "high"
    page = settings_page(SimpleNamespace(), state)
    assert _by_key(page, "settings.analysis-depth").value == "high"


def test_stage_lists_omitted_warning_and_read_only_compare() -> None:
    quick_omits = omitted_evidence("quick")
    assert quick_omits and all(depth in ("medium", "high", "full") for _s, depth in quick_omits)
    assert omitted_evidence("full") == ()
    diff = compare_depths("quick", "full")
    assert diff.only_in_to and not diff.only_in_from
    view = depth_details_view("quick", root=None, history_reader=lambda _r, _d: [])
    assert "Omitted evidence:" in _by_key(view, f"{DETAILS_KEY}.omitted").value
    assert "mandatory" in _by_key(view, f"{DETAILS_KEY}.stages").value
    compare = _by_key(view, COMPARE_KEY)
    assert "quick" not in [o.key for o in compare.options]
    compare.value = "full"
    compare.on_select(SimpleNamespace(control=compare, data="full"))
    assert "Only in Full" in _by_key(view, f"{COMPARE_KEY}.result").value
    assert "Omitted evidence: none" in _by_key(depth_details_view("full", history_reader=lambda _r, _d: []), f"{DETAILS_KEY}.omitted").value


def test_history_split_is_measured_or_unavailable_never_zero() -> None:
    records = [
        AnalysisTimingRecord("r1", "medium", "stage", "s", 10.0, "warm"),
        AnalysisTimingRecord("r1", "medium", "stage", "s", 40.0, "cold"),
        AnalysisTimingRecord("r2", "medium", "training_centre", "t", 90.0, "cold"),
    ]
    history = timing_history("medium", history_reader=lambda _r, _d: records)
    text = "\n".join(history.lines)
    assert history.available and "2 run(s)" in text
    assert "warm cache: p50 10.0 s" in text and "cold cache: p50 40.0 s" in text
    assert "Training Centre: p50 1.5 min" in text and "Cold acquisition: Unavailable" in text
    empty = timing_history("medium", history_reader=lambda _r, _d: [])
    assert not empty.available and "Unavailable" in empty.lines[0] and empty.reason

    def broken(_r, _d):
        raise OSError("disk")

    assert "Unavailable" in timing_history("medium", history_reader=broken).lines[0]


def test_certification_is_never_claimed_without_a_stored_result() -> None:
    text, tone = certification_line("medium")
    assert text.startswith("Certification: not available") and tone == "w"
    assert certification_line("medium", certification_reader=lambda _r, _d: {"status": "certified"})[0].startswith(
        "Certification: certified"
    )
    assert "not certified" in certification_line(
        "medium", certification_reader=lambda _r, _d: {"status": "not_certified", "reason": "p95 too slow"}
    )[0]
    view = depth_details_view("medium", history_reader=lambda _r, _d: [])
    assert "not available" in " ".join(_texts(_by_key(view, f"{DETAILS_KEY}.certification")))


def test_details_button_opens_dialog_only_with_a_selected_depth() -> None:
    opened: list[ft.AlertDialog] = []
    group = depth_selector(
        None, on_selected=lambda _d: None, open_dialog=opened.append, history_reader=lambda _r, _d: []
    )
    button = _by_key(group, DETAILS_KEY)
    button.on_click(SimpleNamespace())
    assert not opened and "select a depth first" in _by_key(group, "shell.analysis-depth-detail").value
    chosen = depth_selector(
        "high", on_selected=lambda _d: None, open_dialog=opened.append, history_reader=lambda _r, _d: []
    )
    _by_key(chosen, DETAILS_KEY).on_click(SimpleNamespace())
    assert len(opened) == 1 and isinstance(opened[0], ft.AlertDialog)
    assert "Omitted evidence" in " ".join(_texts(opened[0].content))
