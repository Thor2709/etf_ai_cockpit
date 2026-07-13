from __future__ import annotations

from dataclasses import replace

import pandas as pd

from etf_cockpit.app.pages.etf_detail import etf_detail_page
from etf_cockpit.app.pages.instrument_detail import render_news_context_panel
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


def test_instrument_detail_disclosure_panel_surfaces_parsed_kid_and_methodology_provenance() -> None:
    from etf_cockpit.app.selectors.instrument_detail import build_etf_disclosure_panel

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    model = build_instrument_detail(
        snapshot,
        instrument_id,
        document_registry=pd.DataFrame(),
        holdings=pd.DataFrame(),
        kid_records=pd.DataFrame(
            {
                "instrument_id": [instrument_id],
                "source_id": ["parsed:kid:test"],
                "source_sha256": ["a" * 64],
                "parser_version": ["2.0"],
                "source_pages": ["[1, 2]"],
                "product": ["Example ETF"],
                "isin": ["IE000Q4J3CW6"],
                "manufacturer": ["Vanguard"],
                "sri": [4],
                "cost_fields": ['{"entry_costs": "EUR 0"}'],
                "holding_period_years": [5],
                "scenarios": ['["moderate"]'],
                "document_date": ["2026-04-14"],
                "extraction_confidence": ["high"],
                "warnings": ["[]"],
                "manual_review": [False],
                "score_eligible": [True],
                "success": [True],
            }
        ),
        methodology_records=pd.DataFrame(
            {
                "instrument_id": [instrument_id],
                "source_id": ["parsed:methodology:test"],
                "source_sha256": ["b" * 64],
                "parser_version": ["2.0"],
                "source_pages": ["[1, 3]"],
                "provider": ["FTSE Russell"],
                "index_series": ["FTSE Global Equity Index Series"],
                "version": ["14.2"],
                "document_date": ["July 2026"],
                "eligibility_rules": ['["Eligible securities"]'],
                "weighting_rules": ['["Capitalisation weighting"]'],
                "review_frequency": ["Quarterly review"],
                "caps": ['["5% cap"]'],
                "confidence": ["high"],
                "warnings": ["[]"],
                "manual_review": [False],
                "score_eligible": [True],
                "success": [True],
            }
        ),
    )
    panel = build_etf_disclosure_panel(model)
    assert panel["kid"]["sri"] == 4
    assert panel["kid"]["source_pages"] == [1, 2]
    assert panel["kid"]["source_sha256"] == "a" * 64
    assert panel["methodology"]["version"] == "14.2"
    assert panel["methodology"]["provider"] == "FTSE Russell"


def test_legacy_etf_detail_renders_controlled_empty_state_without_scores() -> None:
    snapshot = build_snapshot()
    empty_snapshot = replace(snapshot, signals=[], latest_features=pd.DataFrame())
    state = AppState(snapshot=empty_snapshot, selected_etf=empty_snapshot.config.ui.default_etf)

    control = etf_detail_page(None, state)

    assert control is not None


def test_instrument_detail_news_panel_renders_complete_provenance_and_authority_flags() -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    model = build_instrument_detail(
        snapshot,
        instrument_id,
        news=pd.DataFrame(
            {
                "news_id": ["news-ui-1"],
                "instrument_id": [instrument_id],
                "headline": ["Provider headline"],
                "source_url": ["https://example.invalid/news-ui-1"],
                "published_at": ["2026-07-10T10:00:00+00:00"],
                "ingested_at": ["2026-07-10T10:05:00+00:00"],
                "provider_name": ["Example Provider"],
                "credibility": ["high"],
                "instrument_mapping_method": ["isin_exact"],
                "available_at_decision_time": [True],
                "timestamp_status": ["valid_context"],
            }
        ),
    )
    control = render_news_context_panel(model)

    def text_values(node: object) -> list[str]:
        values: list[str] = []
        for attribute in ("value", "text"):
            value = getattr(node, attribute, None)
            if value:
                values.append(str(value))
        content = getattr(node, "content", None)
        if content is not None:
            values.extend(text_values(content))
        for attribute in ("controls", "rows", "cells"):
            children = getattr(node, attribute, None) or []
            for child in children:
                values.extend(text_values(child))
        return values

    rendered = "\n".join(text_values(control))
    for expected in (
        "source_url=https://example.invalid/news-ui-1",
        "published_at=2026-07-10T10:00:00+00:00",
        "ingested_at=2026-07-10T10:05:00+00:00",
        "provider_name=Example Provider",
        "credibility=high",
        "instrument_mapping_method=isin_exact",
        "available_at_decision_time=True",
        "timestamp_status=valid_context",
        "context_only=true",
        "executable_authority=false",
    ):
        assert expected in rendered
