from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.app.components.overlap import overlap_evidence_panel
from etf_cockpit.app.pages import risk
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot
from etf_cockpit.features.overlap import calculate_direct_overlap


def _holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"instrument_id": "VWCE", "security": "Alpha", "isin": "GB0002634946", "weight": 0.6, "as_of": "2026-07-10", "as_of_date": "2026-07-10", "source_id": "vwce-1", "authority": "issuer", "completeness": "full", "freshness": "fresh", "score_eligible": True, "sector": "Technology", "country": "GB", "currency": "GBP"},
            {"instrument_id": "VWCE", "security": "Beta", "isin": "FR0000120271", "weight": 0.4, "as_of": "2026-07-10", "as_of_date": "2026-07-10", "source_id": "vwce-1", "authority": "issuer", "completeness": "full", "freshness": "fresh", "score_eligible": True, "sector": "Financials", "country": "FR", "currency": "EUR"},
            {"instrument_id": "LYP6", "security": "Alpha renamed", "isin": "GB0002634946", "weight": 0.25, "as_of": "2026-07-11", "as_of_date": "2026-07-11", "source_id": "lyp6-1", "authority": "issuer", "completeness": "partial", "freshness": "fresh", "score_eligible": False, "sector": "Technology", "country": "GB", "currency": "GBP"},
        ]
    )


def _walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _text(control) -> str:
    return "\n".join(str(getattr(item, "value", "")) for item in _walk(control) if getattr(item, "value", None) is not None)


def test_risk_page_shows_dated_lower_bound_and_unresolved_coverage(monkeypatch) -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    monkeypatch.setattr(risk, "_load_holdings_evidence", _holdings)

    rendered = risk.risk_page(None, state)
    text = _text(rendered)

    assert "ETF direct overlap" in text
    assert "coverage_status=dated_lower_bound" in text
    assert "observed dated overlap=25.0%" in text
    assert "unresolved=75.0%" in text
    assert "execution_allowed=false" in text


def test_instrument_detail_exposes_structured_overlap_payload() -> None:
    snapshot = build_snapshot()
    model = build_instrument_detail(snapshot, "VWCE", holdings=_holdings())

    overlap = model.sections["etf_overlap"]
    assert overlap["status"] == "dated_lower_bound"
    assert overlap["execution_allowed"] is False
    pair = next(item for item in overlap["pairs"] if item["left"] == "LYP6" and item["right"] == "VWCE")
    assert pair["observed_overlap_weight"] == 0.25
    assert pair["current_overlap_weight"] is None
    assert pair["top_overlapping_companies"] == ["Alpha (25.00%)"]


def test_overlap_panel_shows_lookthrough_authority_checksum_and_unknown() -> None:
    report = calculate_direct_overlap(
        _holdings(),
        ["VWCE", "LYP6"],
        current_weights={"VWCE": 0.5, "LYP6": 0.5},
        today=date(2026, 7, 18),
    )
    text = _text(overlap_evidence_panel(report, key="test.overlap"))

    assert "look-through:" in text
    assert "unknown/unmapped=" in text
    assert "authority=issuer" in text
    assert "checksum=" in text
    assert f"report_hash={report.report_hash}" in text
    assert "execution_allowed=false" in text
