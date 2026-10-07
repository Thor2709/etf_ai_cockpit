from __future__ import annotations

from types import SimpleNamespace

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
    monkeypatch.setattr(system_map, "load_product_governance", lambda: SimpleNamespace(policy=None))
    monkeypatch.setattr(system_map, "load_authority_matrix", lambda: SimpleNamespace(policy=None, checksum=None))
    monkeypatch.setattr(system_map, "capability_scope_view", lambda: SimpleNamespace(status="unavailable", stages=(), strategies=(), instruments=(), rejected_strategy_ids=(), checksum=None, matrix_version=None))
    monkeypatch.setattr(system_map, "supply_chain_intake_report", lambda _root: {})
    result = system_map.system_map_page(None, SimpleNamespace())
    texts = _texts(result)
    assert isinstance(result, PageView)
    assert any("Unavailable" in value or "unavailable" in value.casefold() for value in texts)
    assert "0" not in texts
