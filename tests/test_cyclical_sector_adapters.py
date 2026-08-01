from __future__ import annotations

from dataclasses import replace

import pytest

from etf_cockpit.analysis.cyclical_sector_adapters import (
    CYCLICAL_FORMULA_VERSION,
    CycleHistoryEvidence,
    CyclicalAdapterError,
    CyclicalMetricEvidence,
    build_cyclical_projection,
    cyclical_adapter_definitions,
    cyclical_formula_registry,
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
        for name, shock in {"commodity_price": -0.2, "input_cost": -0.1, "demand_rate": 0.15}.items()
    }


def _build(model, evidence, *, context=None, history=None, scenarios=None):
    return build_cyclical_projection(
        context or _context(model), evidence,
        cycle_history=_history() if history is None else history,
        registry=AdapterRegistry(cyclical_adapter_definitions()),
        decision_time=DECISION, scenarios=_scenarios() if scenarios is None else scenarios,
    )


@pytest.mark.parametrize(
    ("model", "metrics"),
    [
        ("energy", {"production": ("quantity", 120), "unit_cost": ("currency_per_quantity", 30), "reserves": ("quantity", 900), "resource_life": ("years", 7.5), "realised_price": ("currency_per_quantity", 75), "hedge_ratio": ("ratio", 0.3), "sustaining_capex": ("currency", 40), "decommissioning": ("currency", 15)}),
        ("materials", {"production": ("quantity", 220), "unit_cost": ("currency_per_quantity", 45), "reserves": ("quantity", 1500), "inventory": ("quantity", 80), "capital_intensity": ("ratio", 0.4)}),
        ("industrials", {"order_backlog": ("currency", 600), "book_to_bill": ("ratio", 1.15), "backlog_quality": ("ratio", 0.8), "aftermarket_mix": ("ratio", 0.35), "utilisation": ("ratio", 0.82), "working_capital": ("currency", 90), "customer_concentration": ("ratio", 0.2)}),
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
    assert registry["industrials", "book_to_bill"].allowed_units == ("ratio", "percent")
    evidence = (_metric("production", "energy", 10, unit="quantity"),)
    adequate = _build("energy", evidence)
    inadequate = _build("energy", evidence, history=_history(1))
    assert inadequate.status == "partial"
    assert inadequate.aggregate_confidence < adequate.aggregate_confidence
    assert "cycle_history:insufficient_distinct_cycles" in inadequate.limitations


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
        _metric("cycle_adjusted_ev_to_earnings", "industrials", 8, unit="ratio"),
        _metric("trough_interest_coverage", "industrials", 3, unit="ratio"),
    ))
    assert {row.check: row.status for row in passed.checks} == {
        "cycle_adjusted_ev_to_earnings": "available",
        "trough_interest_coverage": "available",
    }
    failed = _build("industrials", (
        _metric("cycle_adjusted_ev_to_earnings", "industrials", 15, unit="ratio"),
        _metric("trough_interest_coverage", "industrials", 1, unit="ratio"),
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
    payload = projection_payload(result)
    assert load_cyclical_projection("energy-1", projection=payload)["status"] == "partial"
    forged = dict(payload)
    forged["aggregate_confidence"] = 0.123
    assert load_cyclical_projection("energy-1", projection=forged)["reason_code"] == "cyclical_evidence_invalid"
    nested = projection_payload(result)
    nested["lineage"]["execution_allowed"] = True
    assert load_cyclical_projection("energy-1", projection=nested)["status"] == "unavailable"
    assert load_cyclical_projection("other", projection=payload)["status"] == "unavailable"


def test_default_facade_selector_state_render_and_ui_metadata():
    assert load_cyclical_projection("NO-EVIDENCE")["status"] == "unavailable"
    result = _build("energy", (_metric("production", "energy", 10, unit="quantity"),))
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.universe.etfs[0].id)
    matching = replace(result, instrument_id=state.selected_etf)
    payload = projection_payload(matching)
    payload["result_hash"] = __import__("etf_cockpit.analysis.cyclical_sector_adapters", fromlist=["cyclical_result_hash"]).cyclical_result_hash(payload)
    state.cyclical_projection = payload
    model = build_instrument_detail(state.snapshot, state.selected_etf, cyclical_projection=payload)
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
