from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

import pytest

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.classification import (
    AdapterRoute,
    ClassificationEvidence,
    ClassificationOverride,
    ClassificationSchemaError,
    ClassificationStore,
    InstrumentContextV2,
    classification_store_exists,
    measure_classification_accuracy,
    resolve_instrument_context,
    sector_adapter_route,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "classification_labelled.json"
AS_OF = "2024-06-30T00:00:00Z"
DECISION_TIME = "2024-07-02T00:00:00Z"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _evidence(
    instrument_id: str,
    field: str,
    value: object,
    *,
    authority: str = "official",
    confidence: float = 0.95,
    source: str | None = None,
    valid_from: str = "2020-01-01T00:00:00Z",
    valid_to: str | None = None,
    available_at: str = "2020-01-02T00:00:00Z",
) -> ClassificationEvidence:
    evidence_id = source or f"fixture:{instrument_id}:{field}"
    return ClassificationEvidence(
        evidence_id=evidence_id,
        instrument_id=instrument_id,
        field=field,
        value=str(value),
        authority=SourceAuthority(authority),
        confidence=confidence,
        source=evidence_id,
        source_id=evidence_id,
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at,
    )


def _case_evidence(case: dict) -> tuple[ClassificationEvidence, ...]:
    return tuple(
        _evidence(
            case["instrument_id"],
            item["field"],
            item["value"],
            authority=item.get("authority", "official"),
            confidence=item.get("confidence", 0.95),
            source=f"fixture:{case['instrument_id']}:{index}",
        )
        for index, item in enumerate(case["evidence"])
    )


def _context_for(case: dict, *, effective_at: str = AS_OF, decision_time: str = DECISION_TIME) -> InstrumentContextV2:
    return resolve_instrument_context(
        _case_evidence(case),
        effective_at=effective_at,
        decision_time=decision_time,
    )


@pytest.mark.parametrize("case", _fixture()["cases"], ids=lambda case: case["instrument_id"])
def test_labelled_route_table_resolves_or_explicitly_unresolved(case: dict) -> None:
    context = _context_for(case)
    expected = case["expected"]

    assert isinstance(context, InstrumentContextV2)
    assert context.execution_allowed is False
    assert context.instrument_id == case["instrument_id"]
    assert context.instrument_type == expected["instrument_type"]
    assert context.asset_class == expected["asset_class"]
    assert context.sector == expected["sector"]
    assert context.industry == expected["industry"]
    assert bool(context.fallback_path) is bool(expected["fallback"])
    assert context.version_id
    assert context.evidence_ids or expected["instrument_type"] is None


def test_every_case_has_an_explicit_outcome_without_unknown_zero_fill() -> None:
    contexts = [_context_for(case) for case in _fixture()["cases"]]
    assert len(contexts) == 12
    for context in contexts:
        assert context.instrument_id
        assert context.classification_status in {"resolved", "unresolved", "available", "manual_review"}
        assert context.execution_allowed is False
        if context.instrument_type is None:
            assert context.fallback_path
            assert context.classification_status in {"unresolved", "manual_review"}


def test_bond_etf_preserves_outer_type_and_fixed_income_lookthrough() -> None:
    case = next(item for item in _fixture()["cases"] if item["instrument_id"] == "ETF-BOND-001")
    context = _context_for(case)

    assert context.instrument_type == "etf"
    assert context.asset_class == "fixed_income"
    assert context.asset_class == "fixed_income"
    assert context.bond_type == "government"
    assert context.issuer_sector == "sovereign"
    assert context.sector_adapter_allowed is False
    assert context.execution_allowed is False


def test_low_confidence_leaf_uses_fallback_and_blocks_sector_adapter() -> None:
    evidence = (
        _evidence("LOW-001", "instrument_type", "stock", confidence=0.99),
        _evidence("LOW-001", "asset_class", "equity", confidence=0.99),
        _evidence("LOW-001", "sector", "technology", confidence=0.74),
        _evidence("LOW-001", "industry", "software", confidence=0.74),
    )
    context = resolve_instrument_context(evidence, min_leaf_confidence=0.75)
    route = sector_adapter_route(context, min_confidence=0.75)

    assert context.sector is None
    assert context.industry is None
    assert context.fallback_path
    assert context.sector_adapter_allowed is False
    assert isinstance(route, AdapterRoute)
    assert route.allowed is False
    assert route.reason_code in {"SECTOR_CLASSIFICATION_UNAVAILABLE", "SECTOR_CONFIDENCE_BELOW_THRESHOLD"}
    assert route.execution_allowed is False


def test_pit_resolution_excludes_future_fact_even_when_decision_time_is_later() -> None:
    evidence = (
        _evidence("PIT-001", "instrument_type", "stock"),
        _evidence("PIT-001", "asset_class", "equity"),
        _evidence("PIT-001", "sector", "technology", valid_from="2025-01-01T00:00:00Z", available_at="2025-01-02T00:00:00Z"),
    )

    historical = resolve_instrument_context(evidence, effective_at="2024-06-30T00:00:00Z", decision_time="2024-07-02T00:00:00Z")
    future = resolve_instrument_context(evidence, effective_at="2025-06-30T00:00:00Z", decision_time="2025-07-02T00:00:00Z")

    assert historical.sector is None
    assert historical.excluded_evidence_ids
    assert future.sector == "technology"


def test_authority_wins_deterministically_and_conflicts_remain_visible() -> None:
    evidence = (
        _evidence("AUTH-001", "instrument_type", "stock", authority="vendor", confidence=0.99, source="vendor:asset"),
        _evidence("AUTH-001", "instrument_type", "etf", authority="official", confidence=0.80, source="official:asset"),
        _evidence("AUTH-001", "asset_class", "equity", authority="official", confidence=0.99),
        _evidence("AUTH-001", "sector", "technology", authority="official", confidence=0.90, source="official:sector"),
        _evidence("AUTH-001", "sector", "financials", authority="official", confidence=0.90, source="official:sector-conflict"),
    )
    first = resolve_instrument_context(evidence)
    second = resolve_instrument_context(tuple(reversed(evidence)))

    assert first.instrument_type == second.instrument_type == "etf"
    assert first.sector is None
    assert first.alternatives
    assert first.evidence_ids == second.evidence_ids


def test_multi_label_strategy_and_distinct_geography_currency_dimensions_are_retained() -> None:
    case = next(item for item in _fixture()["cases"] if item["instrument_id"] == "FUND-001")
    context = _context_for(case)

    assert set(context.strategy_labels) == {"active", "value"}
    assert context.reporting_currency == "EUR"
    assert context.trading_currency == "GBP"
    assert context.share_class_currency == "GBP"
    assert context.hedging_currency == "GBP"
    assert context.reporting_currency != context.trading_currency


def test_override_is_versioned_and_invalidates_dependent_scores_only_after_cutoff() -> None:
    evidence = (
        _evidence("OVR-001", "instrument_type", "stock"),
        _evidence("OVR-001", "asset_class", "equity"),
        _evidence("OVR-001", "sector", "technology", confidence=0.90),
    )
    override = ClassificationOverride(
        override_id="OVR-001:sector:2025",
        instrument_id="OVR-001",
        field="sector",
        value="financials",
        reason="reviewed classification correction",
        reviewer="fixture-reviewer",
        valid_from="2025-01-01T00:00:00Z",
        available_at="2025-01-02T00:00:00Z",
        dependent_score_keys=("sector_quality", "peer_percentile"),
    )
    before = resolve_instrument_context(evidence, overrides=(override,), effective_at="2024-06-30T00:00:00Z", decision_time="2024-07-02T00:00:00Z")
    after = resolve_instrument_context(evidence, overrides=(override,), effective_at="2025-06-30T00:00:00Z", decision_time="2025-07-02T00:00:00Z")

    assert before.sector == "technology"
    assert before.dependent_scores_invalidated is False
    assert after.sector == "financials"
    assert after.override_ids
    assert after.version_id != before.version_id
    assert after.score_invalidation_token != before.score_invalidation_token
    assert after.dependent_scores_invalidated is True
    assert set(after.invalidated_score_keys) >= {"sector_quality", "peer_percentile"}


def test_accuracy_measurement_uses_labelled_fixture_and_does_not_score_unknown_as_correct() -> None:
    fixture = _fixture()
    expected = {case["instrument_id"]: case["expected"]["asset_class"] for case in fixture["cases"]}
    actual = {case["instrument_id"]: _context_for(case).asset_class for case in fixture["cases"]}
    report = measure_classification_accuracy(expected, actual)

    assert report.total == len(expected)
    assert report.correct >= 9
    assert 0.0 <= report.accuracy <= 1.0
    assert report.mismatches
    assert report.execution_allowed is False


def test_classification_store_is_immutable_and_replays_point_in_time(tmp_path: Path) -> None:
    evidence = (
        _evidence("STORE-001", "instrument_type", "stock"),
        _evidence("STORE-001", "asset_class", "equity"),
        _evidence("STORE-001", "sector", "technology", source="store:sector:old", valid_from="2020-01-01T00:00:00Z"),
        _evidence("STORE-001", "sector", "financials", source="store:sector:new", valid_from="2025-01-01T00:00:00Z", available_at="2025-01-02T00:00:00Z"),
    )
    assert classification_store_exists(tmp_path) is False
    with ClassificationStore(tmp_path) as store:
        store.append_evidence(evidence)
        old = store.classify("STORE-001", effective_at="2024-06-30T00:00:00Z", decision_time="2024-07-02T00:00:00Z")
        new = store.classify("STORE-001", effective_at="2025-06-30T00:00:00Z", decision_time="2025-07-02T00:00:00Z")
        projection = store.projection("STORE-001", effective_at="2024-06-30T00:00:00Z", decision_time="2024-07-02T00:00:00Z")

    assert classification_store_exists(tmp_path) is True
    assert old.sector == "technology"
    assert new.sector == "financials"
    assert projection["sector"] == "technology"
    assert projection["execution_allowed"] is False


def test_classification_store_rejects_corruption_and_duplicate_revision(tmp_path: Path) -> None:
    evidence = _evidence("CORRUPT-001", "instrument_type", "stock")
    conflicting = replace(evidence, value="etf")
    with ClassificationStore(tmp_path) as store:
        store.append_evidence((evidence,))
        with pytest.raises(ClassificationSchemaError):
            store.append_evidence((conflicting,))

    db_path = tmp_path / "data" / "storage" / "cockpit.sqlite3"
    assert db_path.exists()
    with db_path.open("r+b") as handle:
        handle.seek(100)
        handle.write(b"\xff" * 8)
    with pytest.raises(ClassificationSchemaError):
        ClassificationStore(tmp_path)


def test_classification_store_concurrent_appenders_do_not_drop_evidence(tmp_path: Path) -> None:
    batches = [
        (_evidence(f"CONCURRENT-{index}", "instrument_type", "stock"), _evidence(f"CONCURRENT-{index}", "asset_class", "equity"))
        for index in range(8)
    ]

    def append(batch: tuple[ClassificationEvidence, ...]) -> None:
        with ClassificationStore(tmp_path) as store:
            store.append_evidence(batch)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, batches))

    with ClassificationStore(tmp_path) as store:
        for index in range(8):
            context = store.classify(f"CONCURRENT-{index}")
            assert context.instrument_type == "stock"
            assert context.asset_class == "equity"


def test_proprietary_taxonomy_is_rejected_without_silent_mapping() -> None:
    evidence = (
        _evidence("TAX-001", "instrument_type", "stock"),
        _evidence("TAX-001", "asset_class", "equity"),
        _evidence("TAX-001", "sector_code", "GICS-45", authority="vendor", confidence=0.99),
    )
    with pytest.raises(ClassificationSchemaError):
        resolve_instrument_context(evidence)
