from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import training_centre


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _render(monkeypatch, data):
    monkeypatch.setattr(training_centre, "load_training_evidence", lambda _root: data)
    monkeypatch.setattr(training_centre, "load_optimisation_evidence", lambda _root: {"trials": (), "summaries": ()})
    monkeypatch.setattr(training_centre.DurableJobScheduler, "list_workflows", lambda _self, limit=100: ())
    return training_centre.training_centre_page(SimpleNamespace(go=lambda _route: None), SimpleNamespace(snapshot=None))


def _text(page: PageView) -> list[str]:
    return [str(item.value) for item in _walk(page.body) if isinstance(item, ft.Text)]


def test_renders_with_sample_data(monkeypatch) -> None:
    rendered = _render(
        monkeypatch,
        {
            "training.run": ({"run_id": "run-a", "status": "completed", "model_id": "model-a", "best_metric": "loss"},),
            "training.model": ({"name": "model-a"},),
            "training.metric": ({"run_id": "run-a", "name": "loss", "value": 0.2, "step": 1},),
            "validation.report": (),
            "validation.trial": (),
            "validation.researcher_decision": (),
            "validation.promotion_result": (),
        },
    )
    values = _text(rendered)
    assert isinstance(rendered, PageView)
    for title in ("Run list", "Live metrics", "Validation Designer", "Bounded optimisation", "Synthetic Scenario Builder", "Model comparison and registry", "Final reports and replay"):
        assert title in values
    assert rendered.chrome.title == "Training Centre"
    assert rendered.chrome.subtitle == "Experiments, runs, metrics and model cards · promotion needs recorded human approval"
    assert tuple(rendered.chrome.segment_groups[0].items) == ("Runs", "Validation", "Optimisation")
    assert not any("Traceback" in value for value in values)


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    rendered = _render(
        monkeypatch,
        {key: () for key in ("training.run", "training.model", "training.metric", "validation.report", "validation.trial", "validation.researcher_decision", "validation.promotion_result")},
    )
    values = _text(rendered)
    assert "Unavailable" in " ".join(values)
    assert not any(value.strip() == "0" for value in values)


def test_cards_are_side_by_side_and_refresh_controls_are_text_buttons(monkeypatch) -> None:
    data = {key: () for key in ("training.run", "training.model", "training.metric", "validation.report", "validation.trial", "validation.researcher_decision", "validation.promotion_result")}
    rendered = _render(monkeypatch, data)
    values = _text(rendered)
    buttons = [item for item in _walk(rendered.body) if isinstance(item, ft.TextButton)]
    assert {item.key for item in buttons} >= {"training-centre.refresh", "training-centre.validation-refresh"}
    assert "Validation Designer" in values and "Bounded optimisation" in values
    rows = [item for item in _walk(rendered.body) if isinstance(item, ft.Row) and len(item.controls) == 2 and all(isinstance(child, ft.Container) for child in item.controls)]
    assert any(item.vertical_alignment == ft.CrossAxisAlignment.STRETCH for item in rows)
    rendered.chrome.segment_groups[0].on_change("Validation")
    assert _text(rendered).index("Validation Designer") < _text(rendered).index("Run list")
    rendered.chrome.segment_groups[0].on_change("Optimisation")
    assert _text(rendered).index("Bounded optimisation") < _text(rendered).index("Validation Designer")
    assert not any(isinstance(item, ft.ListView) and item.expand for item in _walk(rendered.body))
