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


def test_legacy_etf_detail_renders_controlled_empty_state_without_scores() -> None:
    snapshot = build_snapshot()
    empty_snapshot = replace(snapshot, signals=[], latest_features=pd.DataFrame())
    state = AppState(snapshot=empty_snapshot, selected_etf=empty_snapshot.config.ui.default_etf)

    control = etf_detail_page(None, state)

    assert control is not None
