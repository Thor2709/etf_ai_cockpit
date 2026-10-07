from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import feature_catalogue


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


class _Store:
    def feature_catalogue(self):
        return (SimpleNamespace(feature_id="feature-a", source_column="close", lookback_days=5, availability_delay_days=1, units="ratio", missing_policy="reject"),)

    def target_catalogue(self):
        return ()

    def coverage(self, _source):
        return {"rows": 1, "features": 1, "coverage": {"feature-a": 0.98}, "missing_rows": 0}


def _render(monkeypatch, source):
    monkeypatch.setattr(feature_catalogue, "LocalFeatureStore", lambda _root: _Store())
    state = SimpleNamespace(snapshot=SimpleNamespace(features=source))
    return feature_catalogue.feature_catalogue_page(None, state)


def _text(page: PageView) -> list[str]:
    return [str(item.value) for item in _walk(page.body) if isinstance(item, ft.Text)]


def test_renders_with_sample_data(monkeypatch) -> None:
    rendered = _render(monkeypatch, pd.DataFrame({"decision_timestamp": ["2026-01-02"], "feature-a": [0.5]}))
    values = _text(rendered)
    assert isinstance(rendered, PageView)
    for title in ("Feature definitions", "Feature coverage", "Training data preview", "Targets and leakage controls"):
        assert title in values
    assert rendered.chrome.title == "Feature Catalogue"
    assert rendered.chrome.subtitle == "Versioned point-in-time feature definitions and a leakage-safe training preview"
    assert rendered.chrome.segment_groups == ()
    assert not any("Traceback" in value for value in values)


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    rendered = _render(monkeypatch, None)
    values = _text(rendered)
    assert "Unavailable" in " ".join(values)
    assert not any(value.strip() == "0" for value in values)
