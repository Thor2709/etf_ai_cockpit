from __future__ import annotations

from dataclasses import replace
import json

import pytest

from etf_cockpit.analysis.cyclical_sector_adapters import (
    CYCLICAL_FORMULA_VERSION,
    CycleHistoryEvidence,
    CyclicalAdapterError,
    CyclicalMetricEvidence,
    build_cyclical_projection,
    cyclical_adapter_definitions,
    cyclical_formula_registry,
    cyclical_result_hash,
    cyclical_source_digest,
    projection_payload,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import load_cyclical_projection
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.services import build_snapshot


DECISION = "2025-03-01T00:00:00Z"
SECTORS = {"energy": "energy", "materials": "materials", "industrials": "industrials"}


def _context(model: str, **overrides):
    instrument_id = overrides.pop("instrument_id", f"{model}-1")
    values = {
        "instrument_type": "stock", "asset_class": "equity", "sector": SECTORS[model],
        "industry": model, "business_model_tag": model, "operating_country": "AU",
        "reporting_currency": "AUD", "entity_id": instrument_id,
    }
    values.update(overrides)
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument_id}:{field}", instrument_id=instrument_id,
            field=field, value=value, source="fixture", authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{field}", confidence=0.99,
            valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence, instrument_id=instrument_id,
        effective_at="2024-12-31T00:00:00Z", decision_time=DECISION,
    )


def _metric(metric: str, model: str, value: float | None, *, unit="currency", authority=SourceAuthority.ISSUER, commodity_id=None):
    return CyclicalMetricEvidence(
        metric, value, unit, "FY2024", "IFRS", "AU", model, f"issuer:{metric}",
        authority, "2024-12-31T00:00:00Z", "2025-02-15T00:00:00Z",
        commodity_id=commodity_id or ("brent" if model in {"energy", "materials"} and metric in {"production", "unit_cost", "reserves", "resource_life", "realised_price", "hedge_ratio", "inventory"} else None),
        normalisation_cycle_ids=("cycle-0", "cycle-1") if metric == "normalised_margin" else (),
    )


def _history(count=2):
    return tuple(
        CycleHistoryEvidence(
            f"cycle-{index}", "trough_to_peak", f"{2010 + index * 5}-01-01T00:00:00Z",
            f"{2013 + index * 5}-12-31T00:00:00Z", "2025-02-01T00:00:00Z",
            f"issuer:cycle-{index}", SourceAuthority.ISSUER,
        )
        for index in range(count)
    )


def _scenarios():
    return {
        name: {"shock_rate": shock, "exposed_amount": 50.0, "portfolio_base": 100.0}
        for name, shock in {"commodity_price": -0.2, "input_cost": 0.1, "demand_rate": 0.15}.items()
    }


def _build(model, evidence, *, context=None, history=None, scenarios=None):
    return build_cyclical_projection(
        context or _context(model), evidence,
        cycle_history=_history() if history is None else history,
        registry=AdapterRegistry(cyclical_adapter_definitions()),
        decision_time=DECISION, scenarios=_scenarios() if scenarios is None else scenarios,
    )


def _payload_with_digest(result):
    return projection_payload(result), cyclical_source_digest(result.source_payload)


@pytest.mark.parametrize(
    ("model", "metrics"),
    [
        ("energy", {"production": ("quantity", 120), "unit_cost": ("currency_per_quantity", 30), "reserves": ("quantity", 900), "resource_life": ("years", 7.5), "realised_price": ("currency_per_quantity", 75), "hedge_ratio": ("ratio", 0.3), "sustaining_capex": ("currency", 40), "decommissioning": ("currency", 15)}),
        ("materials", {"production": ("quantity", 220), "unit_cost": ("currency_per_quantity", 45), "reserves": ("quantity", 1500), "inventory": ("quantity", 80), "capital_intensity": ("ratio", 0.4)}),
        ("industrials", {"order_backlog": ("currency", 600), "book_to_bill": ("multiple", 1.15), "backlog_quality": ("ratio", 0.8), "aftermarket_mix": ("ratio", 0.35), "utilisation": ("ratio", 0.82), "working_capital": ("currency", 90), "customer_concentration": ("ratio", 0.2)}),
    ],
)
def test_golden_cyclical_families_preserve_metrics_cycles_and_scenarios(model, metrics):
    evidence = tuple(_metric(name, model, value, unit=unit) for name, (unit, value) in metrics.items())
    evidence += (_metric("spot_cycle_margin", model, 0.22, unit="ratio"), _metric("normalised_margin", model, 0.16, unit="ratio"))
    result = _build(model, evidence)
    by_metric = {row.metric: row for row in result.metrics}
    assert by_metric["spot_cycle_margin"].value == 0.22
    assert by_metric["normalised_margin"].value == 0.16
    assert by_metric["spot_cycle_margin"].formula_version == CYCLICAL_FORMULA_VERSION
    assert result.cycle_history_adequate is True
    assert {row.scenario: row.portfolio_impact for row in result.scenarios} == {
        "commodity_price": -0.1, "input_cost": -0.05, "demand_rate": 0.075,
    }
    assert result.execution_allowed is False
    assert projection_payload(result) == projection_payload(_build(model, evidence))


def test_formula_units_directions_and_cycle_history_confidence():
    registry = {(row.business_model, row.metric): row for row in cyclical_formula_registry()}
    assert registry["energy", "unit_cost"].direction == "lower_is_better"
    assert registry["industrials", "book_to_bill"].allowed_units == ("multiple",)
    evidence = (_metric("production", "energy", 10, unit="quantity"),)
    adequate = _build("energy", evidence)
    inadequate = _build("energy", evidence, history=_history(1))
    assert inadequate.status == "partial"
    assert inadequate.aggregate_confidence < adequate.aggregate_confidence
    assert "cycle_history:insufficient_distinct_cycles" in inadequate.limitations
    normalised = _build(
        "energy",
        (_metric("normalised_margin", "energy", 0.16, unit="ratio"),),
        history=_history(1),
    )
    normalised_row = next(row for row in normalised.metrics if row.metric == "normalised_margin")
    assert normalised_row.status == "unavailable" and normalised_row.value is None


def test_canonical_source_payload_survives_json_round_trip():
    result = _build("energy", (_metric("production", "energy", 10, unit="quantity"),))
    payload = json.loads(json.dumps(projection_payload(result)))
    assert load_cyclical_projection(
        "energy-1",
        projection=payload,
        expected_source_digest=cyclical_source_digest(result.source_payload),
    )["status"] == "partial"


def test_omitted_applicable_metrics_are_explicit_unavailable_and_reduce_confidence():
    result = _build("energy", (_metric("production", "energy", 10, unit="quantity"),))
    by_metric = {row.metric: row for row in result.metrics}
    assert by_metric["reserves"].status == "unavailable"
    assert by_metric["reserves"].missing_policy == "unavailable"
    assert result.status == "partial"
    assert result.aggregate_confidence < 1.0


def test_commodity_mapping_and_metric_specific_units_fail_closed():
    with pytest.raises(CyclicalAdapterError, match="commodity mapping"):
        _build("energy", (_metric("production", "energy", 10, unit="quantity", commodity_id=" "),))
    with pytest.raises(CyclicalAdapterError, match="unit or direction"):
        _build("energy", (_metric("unit_cost", "energy", 10, unit="currency"),))
    result = _build("energy", (_metric("realised_price", "energy", 70, unit="currency_per_quantity", commodity_id="brent"),))
    assert next(row for row in result.metrics if row.metric == "realised_price").commodity_id == "brent"


def test_cycle_valuation_and_distress_checks_available_failed_and_unavailable():
    passed = _build("industrials", (
        _metric("cycle_adjusted_ev_to_earnings", "industrials", 8, unit="multiple"),
        _metric("trough_interest_coverage", "industrials", 3, unit="multiple"),
    ))
    assert {row.check: row.status for row in passed.checks} == {
        "cycle_adjusted_ev_to_earnings": "available",
        "trough_interest_coverage": "available",
    }
    failed = _build("industrials", (
        _metric("cycle_adjusted_ev_to_earnings", "industrials", 15, unit="multiple"),
        _metric("trough_interest_coverage", "industrials", 1, unit="multiple"),
    ))
    assert all(row.status == "failed" for row in failed.checks)
    unavailable = _build("industrials", (_metric("order_backlog", "industrials", 10),))
    assert all(row.status == "unavailable" for row in unavailable.checks)


@pytest.mark.parametrize(
    "bad",
    [
        lambda item: replace(item, source_authority=SourceAuthority.VENDOR),
        lambda item: replace(item, known_at="2025-04-01T00:00:00Z"),
        lambda item: replace(item, as_of="2025-04-01T00:00:00Z"),
        lambda item: replace(item, reporting_standard=""),
        lambda item: replace(item, jurisdiction=""),
    ],
)
def test_operational_claims_require_linked_point_in_time_authority(bad):
    with pytest.raises(CyclicalAdapterError):
        _build("energy", (bad(_metric("production", "energy", 10, unit="quantity")),))


def test_invalid_or_missing_scenarios_are_explicitly_unavailable():
    result = _build("energy", (_metric("production", "energy", 10, unit="quantity"),), scenarios={
        "commodity_price": {"shock_rate": float("nan"), "exposed_amount": 2, "portfolio_base": 1},
        "input_cost": {"shock_rate": 1, "exposed_amount": 2, "portfolio_base": 0},
    })
    assert all(row.status == "unavailable" and row.portfolio_impact is None for row in result.scenarios)


def test_routing_and_classification_fail_closed():
    evidence = (_metric("production", "energy", 10, unit="quantity"),)
    with pytest.raises(CyclicalAdapterError):
        _build("energy", evidence, context=_context("energy", sector="financials"))
    with pytest.raises(CyclicalAdapterError):
        _build("energy", evidence, context=replace(_context("energy"), decision_time="2025-02-01T00:00:00Z"))
    with pytest.raises(CyclicalAdapterError):
        _build("energy", evidence, context=replace(_context("energy"), effective_at="2025-04-01T00:00:00Z"))
    with pytest.raises(CyclicalAdapterError):
        _build("energy", evidence, context=replace(_context("energy"), instrument_type="fund"))
    with pytest.raises(CyclicalAdapterError):
        _build("industrials", (_metric("order_backlog", "industrials", 10),), context=replace(_context("industrials"), business_model_tags=("industrials", "infrastructure")))


def test_duplicates_cross_model_generic_fallback_and_future_cycle_fail_closed():
    row = _metric("production", "energy", 10, unit="quantity")
    with pytest.raises(CyclicalAdapterError):
        _build("energy", (row, row))
    with pytest.raises(CyclicalAdapterError):
        _build("energy", (replace(row, business_model="materials"),))
    with pytest.raises(CyclicalAdapterError):
        _build("energy", (replace(row, metric="generic_pe"),))
    with pytest.raises(CyclicalAdapterError):
        _build("energy", (row,), history=(replace(_history(1)[0], known_at="2025-04-01T00:00:00Z"),))


def test_hash_tamper_nested_authority_and_identity_mismatch_fail_closed():
    result = _build("energy", (_metric("production", "energy", 10, unit="quantity"),))
    payload, digest = _payload_with_digest(result)
    assert load_cyclical_projection(
        "energy-1", projection=payload, expected_source_digest=digest
    )["status"] == "partial"
    forged = dict(payload)
    forged["aggregate_confidence"] = 0.123
    assert load_cyclical_projection(
        "energy-1", projection=forged, expected_source_digest=digest
    )["reason_code"] == "cyclical_evidence_invalid"
    nested = projection_payload(result)
    nested["lineage"]["execution_allowed"] = True
    assert load_cyclical_projection(
        "energy-1", projection=nested, expected_source_digest=digest
    )["status"] == "unavailable"
    assert load_cyclical_projection(
        "other", projection=payload, expected_source_digest=digest
    )["status"] == "unavailable"
    assert load_cyclical_projection("energy-1", projection=payload)["status"] == "unavailable"


def test_cycles_must_be_completed_non_overlapping_and_normalisation_linked():
    row = _history(1)[0]
    relabelled = replace(row, cycle_id="renamed", source_id="issuer:renamed")
    with pytest.raises(CyclicalAdapterError, match="non-overlapping"):
        _build("energy", (_metric("production", "energy", 1, unit="quantity"),), history=(row, relabelled))
    overlapping = replace(row, cycle_id="later", start_at="2013-01-01T00:00:00Z", end_at="2016-01-01T00:00:00Z")
    with pytest.raises(CyclicalAdapterError, match="non-overlapping"):
        _build("energy", (_metric("production", "energy", 1, unit="quantity"),), history=(row, overlapping))
    with pytest.raises(CyclicalAdapterError, match="lineage"):
        _build("energy", (_metric("production", "energy", 1, unit="quantity"),), history=(replace(row, phase="peak"),))
    unlinked = replace(_metric("normalised_margin", "energy", 0.2, unit="ratio"), normalisation_cycle_ids=("cycle-0", "unknown"))
    result = _build("energy", (unlinked,))
    normalised = next(item for item in result.metrics if item.metric == "normalised_margin")
    assert normalised.status == "unavailable" and result.status != "available"


def test_chronology_fatal_limitations_and_required_scenarios_reduce_authority():
    with pytest.raises(CyclicalAdapterError, match="lineage"):
        _build("energy", (replace(_metric("production", "energy", 1, unit="quantity"), as_of="2025-02-20T00:00:00Z", known_at="2025-02-10T00:00:00Z"),))
    with pytest.raises(CyclicalAdapterError, match="lineage"):
        _build("energy", (_metric("production", "energy", 1, unit="quantity"),), history=(replace(_history(1)[0], known_at="2012-01-01T00:00:00Z"),))
    for limitation in ("stale", "conflicted", "invalid", "unsupported"):
        result = _build("energy", (replace(_metric("production", "energy", 1, unit="quantity"), limitations=(limitation,)),))
        assert next(item for item in result.metrics if item.metric == "production").status == "unavailable"
        assert result.status != "available" and result.aggregate_confidence < 1
    complete = _build("energy", (_metric("production", "energy", 1, unit="quantity"),))
    missing = _build("energy", (_metric("production", "energy", 1, unit="quantity"),), scenarios={})
    assert missing.status != "available" and missing.aggregate_confidence < complete.aggregate_confidence


def test_scenario_direction_units_bounds_and_self_rehashed_forgery_rejected():
    result = _build("energy", (_metric("production", "energy", 1, unit="quantity"),))
    _, digest = _payload_with_digest(result)
    scenarios = {row.scenario: row for row in result.scenarios}
    assert scenarios["input_cost"].portfolio_impact == -0.05
    assert scenarios["input_cost"].direction == "adverse_positive_is_negative"
    assert all(row.exposure_unit == row.basis_unit == "portfolio_currency" for row in scenarios.values())
    invalid = _build("energy", (_metric("production", "energy", 1, unit="quantity"),), scenarios={
        "commodity_price": {"shock_rate": 1.1, "exposed_amount": 1, "portfolio_base": 1},
        "input_cost": {"shock_rate": .1, "exposed_amount": -1, "portfolio_base": 1},
        "demand_rate": {"shock_rate": .1, "exposed_amount": 1, "portfolio_base": 0},
    })
    assert all(row.status == "unavailable" for row in invalid.scenarios)
    forged = projection_payload(result)
    forged["metrics"][0]["unit"] = "currency"
    forged["result_hash"] = cyclical_result_hash(forged)
    assert load_cyclical_projection(
        "energy-1", projection=forged, expected_source_digest=digest
    )["status"] == "unavailable"
    forged = projection_payload(result)
    forged["scenarios"][1]["portfolio_impact"] = 0.05
    forged["result_hash"] = cyclical_result_hash(forged)
    assert load_cyclical_projection(
        "energy-1", projection=forged, expected_source_digest=digest
    )["status"] == "unavailable"


@pytest.mark.parametrize(
    "forgery",
    [
        pytest.param(
            lambda: _build(
                "energy",
                (replace(_metric("production", "energy", 1, unit="quantity"), source_id="issuer:forged"),),
            ),
            id="source-identity-and-lineage",
        ),
        pytest.param(
            lambda: _build(
                "energy",
                (_metric("production", "energy", 1, unit="quantity"),),
                history=(replace(_history()[0], end_at="2014-12-31T00:00:00Z"), _history()[1]),
            ),
            id="cycle-parameters-and-result",
        ),
        pytest.param(
            lambda: _build(
                "energy",
                (_metric("production", "energy", 1, unit="quantity"),),
                scenarios={
                    **_scenarios(),
                    "input_cost": {"shock_rate": 0.9, "exposed_amount": 50.0, "portfolio_base": 100.0},
                },
            ),
            id="scenario-input-and-output",
        ),
        pytest.param(
            lambda: _build(
                "energy",
                (_metric("production", "energy", 1, unit="quantity"),),
                scenarios={
                    **_scenarios(),
                    "commodity_price": {"shock_rate": 1.1, "exposed_amount": 50.0, "portfolio_base": 100.0},
                },
            ),
            id="scenario-bound-and-status",
        ),
        pytest.param(
            lambda: _build(
                "energy",
                (_metric("production", "energy", 1, unit="quantity"),),
                context=replace(_context("energy"), score_invalidation_token="f" * 64),
            ),
            id="classification-token-and-adapter-lineage",
        ),
        pytest.param(
            lambda: _build(
                "energy",
                (_metric("production", "energy", 1, unit="quantity"),),
                context=replace(_context("energy"), operating_country="US"),
            ),
            id="operating-country-and-variant-route",
        ),
    ],
)
def test_paired_self_consistent_source_and_projection_forgery_rejected_by_detached_digest(forgery):
    original = _build("energy", (_metric("production", "energy", 1, unit="quantity"),))
    original_digest = cyclical_source_digest(original.source_payload)
    payload = projection_payload(forgery())
    payload["result_hash"] = cyclical_result_hash(payload)
    assert load_cyclical_projection(
        "energy-1",
        projection=payload,
        expected_source_digest=original_digest,
    )["status"] == "unavailable"


def test_legitimate_new_source_requires_its_new_detached_digest():
    original = _build("energy", (_metric("production", "energy", 1, unit="quantity"),))
    changed = _build(
        "energy",
        (replace(_metric("production", "energy", 1, unit="quantity"), source_id="issuer:replacement"),),
    )
    payload = projection_payload(changed)
    assert load_cyclical_projection(
        "energy-1",
        projection=payload,
        expected_source_digest=cyclical_source_digest(original.source_payload),
    )["status"] == "unavailable"
    assert load_cyclical_projection(
        "energy-1",
        projection=payload,
        expected_source_digest=cyclical_source_digest(changed.source_payload),
    )["status"] == "partial"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["metrics"][0].update(definition="forged formula"),
        lambda payload: payload["checks"][0].update(formula="forged formula"),
        lambda payload: payload.update(parent_fallback="materials"),
    ],
)
def test_self_rehashed_formula_and_projection_semantics_are_rejected(mutate):
    result = _build("energy", (_metric("production", "energy", 1, unit="quantity"),))
    payload, digest = _payload_with_digest(result)
    mutate(payload)
    payload["result_hash"] = cyclical_result_hash(payload)
    assert load_cyclical_projection(
        "energy-1", projection=payload, expected_source_digest=digest
    )["status"] == "unavailable"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda payload: payload["source_payload"]["context"].update(
                business_model_tags=["energy", 7]
            ),
            id="non-string-business-model-tag",
        ),
        pytest.param(
            lambda payload: payload["source_payload"]["context"].update(
                operating_country=7
            ),
            id="non-string-operating-country",
        ),
        pytest.param(
            lambda payload: payload["source_payload"]["scenarios"]["input_cost"].update(
                shock_rate=10**400
            ),
            id="oversized-scenario-integer",
        ),
    ],
)
def test_malformed_self_hashed_source_payload_fails_closed_through_facade(mutate):
    result = _build("energy", (_metric("production", "energy", 1, unit="quantity"),))
    payload = projection_payload(result)
    mutate(payload)
    payload["result_hash"] = cyclical_result_hash(payload)
    malformed_digest = cyclical_source_digest(payload["source_payload"])
    assert load_cyclical_projection(
        "energy-1",
        projection=payload,
        expected_source_digest=malformed_digest,
    )["status"] == "unavailable"


def test_explicit_inapplicability_is_not_treated_as_missing_disclosure():
    evidence = replace(_metric("hedge_ratio", "energy", None, unit="ratio"), applicable=False)
    result = _build("energy", (evidence,))
    row = next(item for item in result.metrics if item.metric == "hedge_ratio")
    assert row.status == "inapplicable"
    assert "hedge_ratio:not_disclosed" not in result.limitations


def test_default_facade_selector_state_render_and_ui_metadata():
    assert load_cyclical_projection("NO-EVIDENCE")["status"] == "unavailable"
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.universe.etfs[0].id)
    matching = _build(
        "energy", (_metric("production", "energy", 10, unit="quantity"),),
        context=_context("energy", instrument_id=state.selected_etf),
    )
    payload = projection_payload(matching)
    payload["result_hash"] = cyclical_result_hash(payload)
    state.cyclical_projection = payload
    state.cyclical_source_digest = cyclical_source_digest(matching.source_payload)
    model = build_instrument_detail(
        state.snapshot,
        state.selected_etf,
        cyclical_projection=payload,
        cyclical_source_digest=state.cyclical_source_digest,
    )
    assert model.sections["cyclicals"]["status"] in {"available", "partial"}
    page = instrument_detail_page(None, state)

    def texts(control):
        values = [value] if isinstance((value := getattr(control, "value", None)), str) else []
        if (content := getattr(control, "content", None)) is not None:
            values.extend(texts(content))
        for child in getattr(control, "controls", ()) or ():
            values.extend(texts(child))
        return values

    visible = "\n".join(texts(page))
    assert "Cyclicals" in visible and "production" in visible and "commodity_price" in visible
    metadata = open("configs/ui_acceptance.yaml", encoding="utf-8").read()
    assert "instrument-detail.cyclicals" in metadata
