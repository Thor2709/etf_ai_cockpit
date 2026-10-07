from __future__ import annotations

import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import provider_status, trust_evidence
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _texts(page_view: PageView) -> list[str]:
    return [
        str(getattr(control, "value", "") or getattr(control, "text", ""))
        for control in _walk(page_view.body)
    ]


def test_renders_with_sample_data() -> None:
    rendered = provider_status.provider_status_page(None, _state())

    assert isinstance(rendered, PageView)
    text = "\n".join(_texts(rendered))
    assert all(
        title in text
        for title in (
            "Capability registry",
            "Provider health",
            "Provider evidence",
            "Policy",
        )
    )
    group = rendered.chrome.segment_groups[0]
    for selection, title in (
        ("Source tiers", "Mandatory source tiers"),
        ("Terms", "Legal terms and export boundaries"),
    ):
        group.on_change(selection)
        text = "\n".join(_texts(rendered))
        assert title in text
        assert "Traceback" not in text


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    class EmptyRegistry:
        def __init__(self, _config):
            pass

        def probe_all(self):
            return []

        def status_rows(self, _capabilities):
            return []

    monkeypatch.setattr(trust_evidence, "ProviderRegistry", EmptyRegistry)
    monkeypatch.setattr(trust_evidence, "plugin_status_rows", lambda: [])
    monkeypatch.setattr(trust_evidence, "source_policy_rows", lambda _root: [])
    monkeypatch.setattr(trust_evidence, "legal_terms_rows", lambda _root: [])
    monkeypatch.setattr(trust_evidence, "_read_frame", lambda _path: pd.DataFrame())

    rendered = provider_status.provider_status_page(None, _state())

    assert isinstance(rendered, PageView)
    texts = _texts(rendered)
    assert any("Unavailable" in value or "No data" in value or "No rows" in value for value in texts)
    assert all("Traceback" not in value for value in texts)
    assert "0" not in texts
