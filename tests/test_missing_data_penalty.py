"""Global missing-data penalty: one preference, applied once in the shared score list."""

from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.application import score_views
from etf_cockpit.core import ui_preferences


def _score(value, coverage, label="watchlist"):
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Row:
        display_id: str
        final_score_10: float | None
        score_coverage: float
        final_label: str
        one_line_reason: str

    return Row("X", value, coverage, label, "Base.")


def test_penalty_pulls_toward_neutral_by_coverage() -> None:
    assert score_views.apply_missing_data_penalty(_score(9.0, 0.5)).final_score_10 == 7.0
    assert score_views.apply_missing_data_penalty(_score(1.0, 0.5)).final_score_10 == 3.0
    assert score_views.apply_missing_data_penalty(_score(9.0, 1.0)).final_score_10 == 9.0
    shrunk = score_views.apply_missing_data_penalty(_score(9.0, 0.25))
    assert shrunk.final_score_10 == 6.0 and "9.0 -> 6.0 at 25%" in shrunk.one_line_reason
    assert score_views.apply_missing_data_penalty(_score(None, 0.5)).final_score_10 is None


def test_native_sparebank_uses_stored_scorecard_coverage(monkeypatch) -> None:
    monkeypatch.setattr(score_views, "latest_sparebank_scores", lambda: {"X": {"coverage": 0.3}})
    assert score_views.apply_missing_data_penalty(_score(7.0, 0.9, "scorecard_owned")).final_score_10 == 5.6


def test_toggle_reuses_cached_scores_and_follows_preference(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(score_views, "build_simple_instrument_scores", lambda *a, **k: calls.append(1) or [_score(9.0, 0.5)])
    monkeypatch.setattr(score_views, "missing_data_penalty", lambda: ui_preferences.missing_data_penalty(tmp_path))
    snapshot = SimpleNamespace(signals=(), universe_revision="r1")
    assert score_views.snapshot_scores(snapshot)[0].final_score_10 == 9.0
    ui_preferences.save_preference(ui_preferences.MISSING_DATA_PENALTY, True, root=tmp_path)
    assert score_views.snapshot_scores(snapshot)[0].final_score_10 == 7.0
    assert len(calls) == 1


def test_depth_dialog_offers_the_penalty_tickbox(tmp_path) -> None:
    import flet as ft

    from etf_cockpit.app.components.shell.depth_dialog import open_depth_dialog

    shown = []
    saved = []
    state = SimpleNamespace(analysis_depth="medium", evidence_mode="default", settings_root=tmp_path, last_message="",
                            set_missing_data_penalty=lambda value: saved.append(value))
    page = SimpleNamespace(height=900, show_dialog=shown.append, pop_dialog=lambda: None, update=lambda: None)
    open_depth_dialog(page, state, on_changed=lambda: None)

    def walk(node):
        yield node
        for child in getattr(node, "controls", None) or []:
            yield from walk(child)
        content = getattr(node, "content", None)
        if content is not None:
            yield from walk(content)

    box = next(c for c in walk(shown[0]) if isinstance(c, ft.Checkbox))
    assert box.value is False and "missing data" in box.label
    box.value = True
    box.on_change(SimpleNamespace(control=box))
    assert saved == [True]
