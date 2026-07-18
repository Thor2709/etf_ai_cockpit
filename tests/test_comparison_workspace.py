from __future__ import annotations

import json
from pathlib import Path

import flet as ft

from etf_cockpit.app import formatting
from etf_cockpit.app.pages.comparison import comparison_page
from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
from etf_cockpit.app.workspaces import load_workspace, save_workspace
from etf_cockpit.services import build_snapshot


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _text(control: object) -> str:
    return "\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))


def test_formatting_is_explicit_and_uses_european_currency_labels() -> None:
    assert formatting.format_number(1234.5) == "1,234.50"
    assert formatting.format_percent(0.1234) == "12.3%"
    assert formatting.format_currency(1234.5) == "EUR 1,234.50"
    assert formatting.format_currency(None) == "N/A"
    assert formatting.format_date(None) == "N/A"


def test_saved_workspace_is_local_versioned_and_reproducible(tmp_path: Path) -> None:
    path = save_workspace("latest comparison", {"instrument_ids": ["VWCE", "SPY"]}, directory=tmp_path)
    assert path.name == "latest_comparison.json"
    payload = load_workspace("latest comparison", directory=tmp_path)
    assert payload == {"execution_allowed": False, "instrument_ids": ["VWCE", "SPY"], "schema_version": "1.0"}
    assert json.loads(path.read_text(encoding="utf-8"))["execution_allowed"] is False


def test_comparison_workspace_is_registered_and_has_explicit_authority_text() -> None:
    assert PAGES["/comparison"][0] == "Comparison"
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    rendered = comparison_page(None, state)
    text = _text(rendered)
    assert "Comparison workspace" in text or "Comparison unavailable" in text
    assert "disabled" in text
    assert "local" in text.casefold()
