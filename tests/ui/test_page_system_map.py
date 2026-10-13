from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import system_map
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.app.state import AppState


def _texts(control: object) -> list[str]:
    values = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(control, "controls", ()) or ():
        values.extend(_texts(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_texts(content))
    body = getattr(control, "body", None)
    if body is not None:
        values.extend(_texts(body))
    return values


def test_renders_with_sample_data() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    result = system_map.system_map_page(None, state)
    text = "\n".join(_texts(result))
    assert isinstance(result, PageView)
    assert all(title in text for title in ("Product contract", "Capability map", "Strategy and instrument capabilities", "Rejected strategies"))
    assert "Traceback" not in text


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(system_map, "load_feature_registry", lambda: SimpleNamespace(policy=None, diagnostic_mode=True))
    monkeypatch.setattr(system_map, "load_authority_matrix", lambda: SimpleNamespace(policy=None, checksum=None))
    monkeypatch.setattr(system_map, "capability_scope_view", lambda: SimpleNamespace(status="unavailable", stages=(), strategies=(), instruments=(), rejected_strategy_ids=(), checksum=None, matrix_version=None))
    monkeypatch.setattr(system_map, "supply_chain_intake_report", lambda _root: {})
    result = system_map.system_map_page(None, SimpleNamespace())
    texts = _texts(result)
    assert isinstance(result, PageView)
    assert any("Unavailable" in value or "unavailable" in value.casefold() for value in texts)
    assert "0" not in texts


def test_stage_coverage_empty_card_has_bounded_unavailable_control(monkeypatch) -> None:
    monkeypatch.setattr(system_map, "load_feature_registry", lambda: SimpleNamespace(policy=None, diagnostic_mode=True))
    monkeypatch.setattr(system_map, "load_authority_matrix", lambda: SimpleNamespace(policy=None, checksum=None))
    monkeypatch.setattr(system_map, "capability_scope_view", lambda: SimpleNamespace(status="unavailable", stages=(), strategies=(), instruments=(), rejected_strategy_ids=(), checksum=None, matrix_version=None))
    monkeypatch.setattr(system_map, "supply_chain_intake_report", lambda _root: {})
    result = system_map.system_map_page(None, SimpleNamespace())
    controls = [control for control in _texts_walk(result) if isinstance(getattr(control, "data", None), dict)]
    cards = {control.data.get("title"): control for control in controls if control.data.get("kit") == "GlassCard"}
    strategy_card = cards["Strategy and instrument capabilities"]
    assert strategy_card.expand is True
    assert any(control.data.get("kit") == "EmptyState" and control.data.get("title") == "Strategy stage coverage unavailable" for control in _texts_walk(strategy_card) if isinstance(getattr(control, "data", None), dict))
    assert any(isinstance(control, ft.Column) and control.expand is True and control.scroll == ft.ScrollMode.AUTO for control in _texts_walk(strategy_card))
    assert not any(type(control).__name__ == "ListView" for control in _texts_walk(result))


def _texts_walk(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _texts_walk(child)
    for name in ("content", "body"):
        child = getattr(control, name, None)
        if child is not None:
            yield from _texts_walk(child)
