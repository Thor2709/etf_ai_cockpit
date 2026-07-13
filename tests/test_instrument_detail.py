from __future__ import annotations

from dataclasses import replace

import pandas as pd

from etf_cockpit.app.pages.etf_detail import etf_detail_page
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def test_instrument_detail_has_required_sections_for_primary_and_sparebanken() -> None:
    snapshot = build_snapshot()
    model = build_instrument_detail(snapshot, snapshot.config.universe.enabled_ids[0])
    assert {"identity", "price", "scores", "risk", "attribution", "fundamentals", "etf_disclosures", "news", "forecasts", "backtests", "history", "journal", "run_changes"} <= set(model.sections)
    assert model.instrument_id


def test_missing_optional_stores_are_unavailable_not_crash() -> None:
    snapshot = build_snapshot()
    model = build_instrument_detail(snapshot, "missing-instrument")
    assert model.status == "unavailable"
    assert model.sections["identity"] == "unavailable"


def test_instrument_detail_etf_disclosure_panel_shows_inventory_and_holdings_quality() -> None:
    from etf_cockpit.app.selectors.instrument_detail import build_etf_disclosure_panel

    snapshot = build_snapshot()
    model = build_instrument_detail(
        snapshot,
        snapshot.config.universe.enabled_ids[0],
        document_registry=pd.DataFrame(
            {
                "instrument_id": [snapshot.config.universe.enabled_ids[0]],
                "document_type": ["factsheet"],
                "coverage_status": ["available"],
                "document_date": ["2026-07-10"],
                "source_id": ["funddoc:test"],
                "checksum": ["a" * 64],
            }
        ),
        holdings=pd.DataFrame(
            {
                "instrument_id": [snapshot.config.universe.enabled_ids[0]],
                "as_of": ["2026-07-10"],
                "completeness": ["full"],
                "freshness": ["fresh"],
                "confidence": [1.0],
                "source": ["issuer"],
            }
        ),
    )
    panel = build_etf_disclosure_panel(model)
    assert panel["document_inventory"][0]["document_type"] == "factsheet"
    assert panel["holdings"]["completeness"] == "full"
    assert panel["holdings"]["confidence"] == 1.0


def test_instrument_detail_disclosure_panel_is_honest_when_inventory_is_missing() -> None:
    from etf_cockpit.app.selectors.instrument_detail import build_etf_disclosure_panel

    snapshot = build_snapshot()
    model = build_instrument_detail(snapshot, snapshot.config.universe.enabled_ids[0], document_registry=pd.DataFrame(), holdings=pd.DataFrame())
    panel = build_etf_disclosure_panel(model)
    assert panel["status"] == "unavailable"
    assert {row["coverage_status"] for row in panel["document_inventory"]} == {"missing"}
    assert panel["holdings"]["status"] == "unavailable"


def test_legacy_etf_detail_renders_controlled_empty_state_without_scores() -> None:
    snapshot = build_snapshot()
    empty_snapshot = replace(snapshot, signals=[], latest_features=pd.DataFrame())
    state = AppState(snapshot=empty_snapshot, selected_etf=empty_snapshot.config.ui.default_etf)

    control = etf_detail_page(None, state)

    assert control is not None
