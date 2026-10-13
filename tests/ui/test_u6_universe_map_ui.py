from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.pages import catalogue, trust_evidence
from etf_cockpit.app.pages._glass import UNAVAILABLE, glass, kpi_row, tone_for
from etf_cockpit.application.ui_facade import DataCatalogueError


def _walk(control):
    if control is None:
        return
    yield control
    body = getattr(control, "body", None)
    if body is not None:
        yield from _walk(body)
    content = getattr(control, "content", None)
    if content is not None and content is not body:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _texts(control) -> list[str]:
    return [str(item.value) for item in _walk(control) if isinstance(item, ft.Text)]


def _keys(control) -> list[str]:
    return [str(item.key) for item in _walk(control) if getattr(item, "key", None)]


def test_kpi_row_shows_unavailable_with_reason_never_zero() -> None:
    row = kpi_row("u6.kpi", [("Datasets", None, "Catalogue could not be read"), ("Rows", "4", "ok")])
    texts = _texts(row)
    assert UNAVAILABLE in texts and "Catalogue could not be read" in texts and "4" in texts
    assert "0" not in texts
    assert _keys(row)[:1] == ["u6.kpi.0"]


def test_glass_surface_carries_key_and_label_and_tone_mapping() -> None:
    panel = glass("u6.panel", "Panel label", ft.Text("x"))
    assert panel.key == "u6.panel"
    assert tone_for("healthy") == "g" and tone_for("stale") == "w" and tone_for("failed") == "b"


def test_catalogue_unreadable_state_is_honest(monkeypatch) -> None:
    def broken(_root):
        raise DataCatalogueError("boom")

    monkeypatch.setattr(catalogue, "DataCatalogue", broken)
    page = catalogue.catalogue_page(None, SimpleNamespace(selected_etf=""))
    texts = _texts(page)
    assert texts.count(UNAVAILABLE) == 4
    assert "Manual review required" in texts
    assert any("Execution allowed: false" in item for item in texts)
    assert {"catalogue.status-tag", "catalogue.kpi.0", "catalogue.status"} <= set(_keys(page))


def test_trust_table_panels_have_distinct_keys_and_unavailable_copy(tmp_path: Path) -> None:
    missing = tmp_path / "absent.csv"
    first = trust_evidence._table_panel("Provider probes", missing, ["status"])
    second = trust_evidence._table_panel("Source conflicts", missing, ["status"])
    assert first.key != second.key
    assert any("explicit unavailable/missing state" in item for item in _texts(first))


def test_trust_status_page_uses_status_tags_for_boundaries(tmp_path: Path) -> None:
    page = trust_evidence._status_page("Provider Status", "sub", [("Probes", tmp_path / "none.csv", ["a"])])
    texts = _texts(page)
    assert "Broker execution: disabled" in texts
    assert "Missing data: Unavailable, not invented" in texts
    assert "evidence.tag.execution" in _keys(page)
