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
    assert not any("Traceback" in value for value in values)


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    rendered = _render(
        monkeypatch,
        {key: () for key in ("training.run", "training.model", "training.metric", "validation.report", "validation.trial", "validation.researcher_decision", "validation.promotion_result")},
    )
    values = _text(rendered)
    assert "Unavailable" in " ".join(values)
    assert not any(value.strip() == "0" for value in values)
