from __future__ import annotations

from dataclasses import replace

import pandas as pd

from etf_cockpit.app.pages.etf_detail import etf_detail_page
from etf_cockpit.app.pages.instrument_detail import render_news_context_panel
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import load_identity_projection
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore, IdentitySourceRow
from etf_cockpit.data.instrument_identity import IdentityClaim
from etf_cockpit.services import build_snapshot


def _walk_controls(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)
    for row in getattr(control, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            yield from _walk_controls(getattr(cell, "content", None))


def test_instrument_detail_exposes_identity_lineage_from_application_facade(monkeypatch) -> None:
    from etf_cockpit.app.selectors import instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    monkeypatch.setattr(
        selector,
        "load_identity_projection",
        lambda _instrument_id: {
            "status": "available",
            "identity_confidence": "high",
            "identity_status": "resolved",
            "identity_decision_id": "a" * 64,
            "identity_conflict_ids": '["conflict-1"]',
            "identity_resolution_state": "resolved",
            "identity_effective_at": "2026-07-21T00:00:00Z",
            "identity_decision_time": "2026-07-21T00:00:00Z",
            "identity_objects": '[{"object_id":"LISTING-XETR"}]',
            "identity_history": '[{"event_type":"ticker_changed"}]',
            "identity_conflicts": [{"conflict_id": "conflict-1", "resolution_status": "manual_review"}],
            "identity_reviews": [{"decision_id": "review-1", "reviewer": "local-user"}],
            "warnings": "",
            "execution_allowed": False,
        },
    )

    model = selector.build_instrument_detail(snapshot, instrument_id)

    assert model.identity["identity_decision_id"] == "a" * 64
    assert model.identity["identity_conflict_ids"] == '["conflict-1"]'
    assert model.identity["identity_resolution_state"] == "resolved"
    assert "LISTING-XETR" in model.identity["identity_objects"]
    assert "ticker_changed" in model.identity["identity_history"]
    assert model.identity["identity_conflicts"][0]["conflict_id"] == "conflict-1"
    assert model.identity["identity_reviews"][0]["decision_id"] == "review-1"
    assert model.identity["execution_allowed"] is False


def test_identity_projection_loader_fails_closed_on_duplicate_rows(tmp_path) -> None:
    path = tmp_path / "instrument_identity.parquet"
    pd.DataFrame(
        [
            {
                "instrument_id": "X",
                "identity_decision_id": "a" * 64,
                "identity_conflict_ids": '["conflict-1"]',
                "identity_resolution_state": "resolved",
                "identity_confidence": "high",
            }
        ]
    ).to_parquet(path, index=False)
    available = load_identity_projection("X", path)
    assert available["status"] == "available"
    assert available["identity_decision_id"] == "a" * 64
    assert available["identity_conflict_ids"] == '["conflict-1"]'
    assert available["execution_allowed"] is False

    pd.DataFrame([{"instrument_id": "X"}, {"instrument_id": "X"}]).to_parquet(path, index=False)
    duplicate = load_identity_projection("X", path)
    assert duplicate == {
        "status": "quarantined",
        "instrument_id": "X",
        "reason_code": "duplicate_identity_projection",
        "candidate_count": 2,
        "execution_allowed": False,
    }


def test_identity_projection_loader_exposes_durable_master_graph_and_reviews(tmp_path) -> None:
    with IdentityMasterStore(tmp_path) as store:
        store.import_rows(
            (
                IdentitySourceRow(
                    row_id="official-sec-1",
                    instrument_id="SEC-1",
                    object_type="listing",
                    object_id="LISTING-XNAS",
                    parent_object_id="SEC-1",
                    relationship="quotation_for",
                    identifiers={"isin": "US0000000001"},
                    attributes={"ticker": "ABC", "exchange": "XNAS"},
                    source="official",
                    authority=SourceAuthority.OFFICIAL,
                    source_id="official:sec-1",
                    valid_from="2024-01-01T00:00:00Z",
                    available_at="2024-01-02T00:00:00Z",
                ),
            )
        )

    projection = load_identity_projection("SEC-1", storage_root=tmp_path)

    assert projection["status"] == "available"
    assert projection["identity_objects"][0]["object_id"] == "LISTING-XNAS"
    assert projection["identity_conflicts"] == []
    assert projection["identity_reviews"] == []
    assert projection["execution_allowed"] is False


def test_identity_master_migration_preserves_legacy_projection_until_imported(tmp_path) -> None:
    legacy_path = tmp_path / "instrument_identity.parquet"
    pd.DataFrame(
        [
            {
                "instrument_id": "LEGACY-1",
                "identity_confidence": "manual_review",
                "identity_resolution_state": "manual_review",
                "identity_decision_id": "b" * 64,
            }
        ]
    ).to_parquet(legacy_path, index=False)
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(
            (
                IdentityClaim(
                    "OTHER",
                    "ticker",
                    "OTHER",
                    "fixture",
                    SourceAuthority.OFFICIAL,
                    "fixture:other",
                ),
            )
        )

    projection = load_identity_projection("LEGACY-1", legacy_path, storage_root=tmp_path)

    assert projection["status"] == "available"
    assert projection["identity_decision_id"] == "b" * 64
    assert projection["execution_allowed"] is False


def test_instrument_detail_driver_groups_are_ordered_structured_rows(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
    from etf_cockpit.app.selectors import instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    monkeypatch.setattr(selector, "FEATURE_DRIVERS_PATH", tmp_path / "feature_drivers.parquet")
    pd.DataFrame(
        [
            {"instrument_id": instrument_id, "component": "trend", "normalised_score": 8.5, "direction": "positive", "authority": "high", "freshness_status": "ok", "driver_text": "trend positive", "flags": "none"},
            {"instrument_id": instrument_id, "component": "risk", "normalised_score": 2.0, "direction": "negative", "authority": "high", "freshness_status": "ok", "driver_text": "risk negative", "flags": "none"},
            {"instrument_id": instrument_id, "component": "value", "normalised_score": None, "direction": "missing", "authority": "unknown", "freshness_status": "unknown", "driver_text": "value unavailable", "flags": "missing|low_authority"},
            {"instrument_id": instrument_id, "component": "news", "normalised_score": 5.0, "direction": "mixed", "authority": "low", "freshness_status": "stale", "driver_text": "news stale", "flags": "stale|low_authority"},
        ]
    ).to_parquet(selector.FEATURE_DRIVERS_PATH, index=False)

    rendered = instrument_detail_page(None, type("State", (), {"selected_etf": instrument_id, "snapshot": snapshot})())
    texts = [str(getattr(item, "value", "")) for item in _walk_controls(rendered) if hasattr(item, "value")]
    assert "Top positive" in texts
    assert "Top negative" in texts
    assert "Missing / N/A" in texts
    assert "Low authority" in texts
    assert "Stale / partial" in texts
    assert "trend positive" in texts
    assert "risk negative" in texts
    assert "{'instrument_id'" not in " ".join(texts)


def test_instrument_detail_driver_panel_normalises_legacy_store_columns(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.selectors import instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    monkeypatch.setattr(selector, "FEATURE_DRIVERS_PATH", tmp_path / "feature_drivers.parquet")
    pd.DataFrame(
        [{
            "instrument_id": instrument_id,
            "component": "trend",
            "normalised_score": 8.0,
            "direction": "positive",
            "authority": "high",
            "driver_text": "legacy trend",
        }]
    ).to_parquet(selector.FEATURE_DRIVERS_PATH, index=False)

    panel = selector._feature_driver_panel(instrument_id)
    assert panel["status"] == "available"
    assert panel["top_positive"][0]["driver_text"] == "legacy trend"
    assert panel["low_authority"] == []
    assert panel["stale_or_partial"] == []


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


def test_instrument_detail_selects_latest_fundamentals_by_as_of_not_checksum() -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    model = build_instrument_detail(
        snapshot,
        instrument_id,
        fundamentals=pd.DataFrame(
            [
                {
                    "instrument_id": instrument_id,
                    "as_of_date": "2026-07-12",
                    "evidence_checksum": "0" * 64,
                    "eligibility": "eligible",
                    "score_eligible": True,
                    "source": "vendor",
                },
                {
                    "instrument_id": instrument_id,
                    "as_of_date": "2026-07-11",
                    "evidence_checksum": "f" * 64,
                    "eligibility": "eligible",
                    "score_eligible": True,
                    "source": "vendor",
                },
            ]
        ),
    )

    assert model.sections["fundamentals"]["as_of"] == "2026-07-12"


def test_instrument_detail_news_is_sorted_by_published_then_ingested_time() -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    model = build_instrument_detail(
        snapshot,
        instrument_id,
        news=pd.DataFrame(
            [
                {
                    "news_id": "newer",
                    "instrument_id": instrument_id,
                    "headline": "Newer headline",
                    "published_at": "2026-07-12T10:00:00+00:00",
                    "ingested_at": "2026-07-12T10:01:00+00:00",
                    "item_checksum": "0" * 64,
                },
                {
                    "news_id": "older",
                    "instrument_id": instrument_id,
                    "headline": "Older headline",
                    "published_at": "2026-07-11T10:00:00+00:00",
                    "ingested_at": "2026-07-11T10:01:00+00:00",
                    "item_checksum": "f" * 64,
                },
            ]
        ),
    )

    assert [item["news_id"] for item in model.sections["news"]["items"]] == ["older", "newer"]


def test_instrument_detail_surfaces_cost_edge_fields_and_unavailable_state(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    scoreboard_path = tmp_path / "scoreboard.parquet"
    pd.DataFrame(
        [{
            "display_id": instrument_id,
            "gross_expected_edge_bps": 42.0,
            "estimated_total_cost_bps": 7.0,
            "net_expected_edge_bps": 35.0,
            "edge_to_cost_ratio": 5.0,
            "cost_stress_scenario": "high",
        }]
    ).to_parquet(scoreboard_path, index=False)
    monkeypatch.setattr(selector, "SCOREBOARD_PATH", scoreboard_path)

    model = build_instrument_detail(snapshot, instrument_id)
    friction = model.sections["scores"]["friction"]
    assert friction["gross_expected_edge_bps"] == 42.0
    assert friction["estimated_total_cost_bps"] == 7.0
    assert friction["net_expected_edge_bps"] == 35.0
    assert friction["edge_to_cost_ratio"] == 5.0
    assert friction["cost_stress_scenario"] == "high"
    assert friction["status"] == "available"

    monkeypatch.setattr(selector, "SCOREBOARD_PATH", tmp_path / "missing.parquet")
    unavailable = build_instrument_detail(snapshot, instrument_id)
    assert unavailable.sections["scores"]["friction"]["status"] == "unavailable"
    assert unavailable.sections["scores"]["friction"]["gross_expected_edge_bps"] is None
