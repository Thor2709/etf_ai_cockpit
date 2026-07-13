from __future__ import annotations

import pandas as pd

from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
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
