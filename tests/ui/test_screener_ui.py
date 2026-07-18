from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
from etf_cockpit.application.screening import ScreenQuery, ScreenSort
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for row in getattr(control, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            content = getattr(cell, "content", None)
            if content is not None:
                yield from _walk(content)
    for column in getattr(control, "columns", []) or []:
        content = getattr(column, "label", None)
        if content is not None:
            yield from _walk(content)


def _visible_text(control) -> str:
    return "\n".join(
        str(getattr(item, "value", "") or getattr(item, "text", ""))
        for item in _walk(control)
    )


def test_screener_exposes_canonical_fundamentals_and_explicit_missing_state(monkeypatch) -> None:
    assert "/screener" in PAGES
    from etf_cockpit.app.pages import screener

    frame = pd.DataFrame(
        [
            {
                "instrument_id": "MSFT",
                "valuation": 7.0,
                "profitability": 8.0,
                "leverage": 5.0,
                "growth": 9.0,
                "shareholder_return": 6.0,
                "eligibility": "eligible",
                "source": "sec_edgar",
                "as_of_date": "2026-07-10",
                "missing_fields": "",
                "warnings": "",
                "limitations": "Official SEC facts outrank vendor fundamentals when identity and period match.",
                "sector_relative_status": "available",
            },
            {
                "instrument_id": "NO_DATA",
                "eligibility": "not_score_eligible",
                "source": "vendor",
                "as_of_date": "unavailable",
                "missing_fields": "valuation|profitability|leverage|growth|shareholder_return",
                "warnings": "missing_fundamental_fields",
                "limitations": "Missing metrics remain unavailable.",
                "sector_relative_status": "unavailable",
            },
        ]
    )
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: frame)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    controls = PAGES["/screener"][1](None, state)
    text = _visible_text(controls)

    assert "MSFT" in text
    assert "Valuation" in text
    assert "7.0" in text
    assert "Profitability" in text
    assert "Eligibility" in text
    assert "sec_edgar" in text
    assert "2026-07-10" in text
    assert "Sector-relative" in text
    assert "NO_DATA" in text
    assert "unavailable" in text
    assert "missing_fundamental_fields" in text
    assert text.count("N/A") >= 5
    assert "executable_authority=false" in text


def test_screener_is_registered_with_fundamentals_title() -> None:
    assert PAGES["/screener"][0] == "Fundamentals Screener"


def test_screener_empty_clean_store_is_explicit_unavailable(monkeypatch) -> None:
    from etf_cockpit.app.pages import screener

    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _visible_text(screener.screener_page(None, state))

    assert "Fundamentals unavailable" in text
    assert "no canonical rows" in text
    assert "missing metrics are not inferred or scored" in text


def test_screener_renders_sector_relative_comparison_values_and_limitation(monkeypatch) -> None:
    from etf_cockpit.app.pages import screener

    frame = pd.DataFrame(
        [
            {
                "instrument_id": "MSFT",
                "valuation": 7.0,
                "profitability": 8.0,
                "leverage": 5.0,
                "growth": 9.0,
                "shareholder_return": 6.0,
                "eligibility": "eligible",
                "source": "vendor",
                "as_of_date": "2026-07-10",
                "sector_relative_status": "available",
                "sector_relative_value": 8.2,
                "sector_relative_peer": "Technology large-cap peers",
                "sector_relative_benchmark": "MSCI World Information Technology",
                "sector_relative_delta": 1.4,
                "sector_relative_limitation": "Peer set is provider-defined.",
            }
        ]
    )
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: frame)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _visible_text(screener.screener_page(None, state))

    assert "Technology large-cap peers" in text
    assert "MSCI World Information Technology" in text
    assert "1.4" in text
    assert "Peer set is provider-defined." in text


def _by_key(control, key: str):
    return next(item for item in _walk(control) if getattr(item, "key", None) == key)


def test_screener_applies_typed_filter_and_updates_visible_results(monkeypatch) -> None:
    from etf_cockpit.app.pages import screener

    snapshot = build_snapshot()
    first, second = snapshot.config.universe.etfs[:2]
    frame = pd.DataFrame(
        [
            {"instrument_id": first.id, "region": "Europe", "valuation": 8.0},
            {"instrument_id": second.id, "region": "World", "valuation": 4.0},
        ]
    )
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: frame)
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = screener.screener_page(None, state)

    _by_key(page, "screener.filter.field").value = "instrument_id"
    _by_key(page, "screener.filter.operator").value = "eq"
    _by_key(page, "screener.filter.value").value = f" {first.id.lower()} "
    _by_key(page, "screener.filter.add").on_click(None)

    assert f"Active filters: instrument_id eq {first.id.lower()}" in _visible_text(page)
    assert f"1 of {len(snapshot.config.universe.etfs)} local instruments shown" in _visible_text(page)
    assert first.id in _visible_text(_by_key(page, "screener.results"))
    assert second.id not in _visible_text(_by_key(page, "screener.results"))


def test_screener_save_load_and_export_callbacks_report_readable_status(monkeypatch) -> None:
    from etf_cockpit.app.pages import screener

    snapshot = build_snapshot()
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    saved = []
    exported = []
    monkeypatch.setattr(screener, "save_screen", lambda name, query: saved.append((name, query)) or Path("data/screens/my-screen/000001.json"))
    loaded_query = ScreenQuery(sort=(ScreenSort("quality", descending=False),))
    monkeypatch.setattr(screener, "load_screen", lambda _name: loaded_query)
    monkeypatch.setattr(screener, "export_screen_csv", lambda result, query, path: exported.append((result, query, path)) or path)
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = screener.screener_page(None, state)
    _by_key(page, "screener.saved.name").value = "my screen"

    _by_key(page, "screener.saved.save").on_click(None)
    assert saved and "Saved local screen revision" in _visible_text(page)
    _by_key(page, "screener.saved.load").on_click(None)
    assert "Loaded latest saved screen" in _visible_text(page)
    assert _by_key(page, "screener.sort.field").value == "quality"
    assert _by_key(page, "screener.sort.direction").value == "ascending"
    _by_key(page, "screener.filter.field").value = "asset_type"
    _by_key(page, "screener.filter.value").value = "etf"
    _by_key(page, "screener.filter.add").on_click(None)
    _by_key(page, "screener.export.csv").on_click(None)
    assert exported and exported[0][2].name == "screener_results.csv"
    assert "Screener CSV exported" in _visible_text(page)
    assert state.last_export_path == exported[0][2]
    assert exported[0][1].sort == loaded_query.sort


def test_screener_invalid_filter_is_controlled_and_does_not_change_results(monkeypatch) -> None:
    from etf_cockpit.app.pages import screener

    snapshot = build_snapshot()
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = screener.screener_page(None, state)
    _by_key(page, "screener.filter.operator").value = "min"
    _by_key(page, "screener.filter.value").value = "not-a-number"

    _by_key(page, "screener.filter.add").on_click(None)

    assert "Filter not applied" in _visible_text(page)
    assert "numeric filter value must be finite" in _visible_text(page)
