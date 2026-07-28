from __future__ import annotations

from dataclasses import replace

import pytest

from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.analysis.real_asset_sector_adapters import (
    RealAssetAdapterError,
    RealAssetMetricEvidence,
    build_real_asset_projection,
    projection_payload,
    real_asset_adapter_definitions,
)
from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import load_real_asset_projection
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.services import build_snapshot


DECISION = "2025-03-01T00:00:00Z"
SECTORS = {"reit": "real_estate", "utility": "utilities", "infrastructure": "industrials"}


def _context(model: str, *, instrument_id: str | None = None, sector: str | None = None):
    canonical_id = instrument_id or f"{model}-1"
    values = {
        "instrument_type": "stock", "asset_class": "equity",
        "sector": sector or SECTORS[model], "industry": model,
        "business_model_tag": model, "operating_country": "AU",
        "reporting_currency": "AUD", "entity_id": canonical_id,
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{canonical_id}:{field}", instrument_id=canonical_id,
            field=field, value=value, source="fixture",
            authority=SourceAuthority.OFFICIAL, source_id=f"fixture:{field}",
            confidence=0.99, valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence, instrument_id=canonical_id,
        effective_at="2024-12-31T00:00:00Z", decision_time=DECISION,
    )


def _metric(
    metric: str, model: str, value: float | None, *,
    unit: str = "currency",
    authority: SourceAuthority = SourceAuthority.ISSUER,
) -> RealAssetMetricEvidence:
    return RealAssetMetricEvidence(
        metric=metric, value=value, unit=unit, period="FY2024",
        reporting_standard="IFRS", jurisdiction="AU", business_model=model,
        source_id=f"issuer:{metric}", source_authority=authority,
        as_of="2024-12-31T00:00:00Z", known_at="2025-02-15T00:00:00Z",
    )


def _shocks():
    return {
        "rate": {"shock_rate": -0.02, "exposed_amount": 200.0, "base_amount": 100.0},
        "inflation": {"shock_rate": 0.03, "exposed_amount": 50.0, "base_amount": 100.0},
        "refinancing": {"shock_rate": -0.01, "exposed_amount": 300.0, "base_amount": 100.0},
        "nav_sensitivity": {"shock_rate": -0.05, "exposed_amount": 400.0, "base_amount": 100.0},
    }


def _build(model: str, evidence, *, context=None, shocks=None):
    return build_real_asset_projection(
        context or _context(model), evidence,
        registry=AdapterRegistry(real_asset_adapter_definitions()),
        decision_time=DECISION, shocks=_shocks() if shocks is None else shocks,
    )


def test_reit_ffo_affo_capex_payout_leverage_and_stress_reconcile() -> None:
    evidence = tuple(_metric(name, "reit", value) for name, value in {
        "net_income": 100, "depreciation_amortisation": 40,
        "property_sale_gains": 10, "ffo": 130, "maintenance_capex": 20,
        "expansion_capex": 70, "recurring_adjustments": 5, "affo": 115,
        "distributions": 92, "net_debt": 300, "ebitda": 150,
        "interest_expense": 30, "nav": 400,
    }.items())
    evidence += (
        _metric("occupancy_rate", "reit", 0.96, unit="ratio"),
        _metric("weighted_average_lease_maturity", "reit", 6.2, unit="years"),
        _metric("loan_to_value", "reit", 0.35, unit="ratio"),
    )
    result = _build("reit", evidence)
    checks = {row.check: row for row in result.checks}
    assert checks["ffo_reconciliation"].status == "available"
    assert checks["affo_reconciliation"].status == "available"
    assert checks["payout"].value == pytest.approx(0.8)
    assert checks["leverage"].value == pytest.approx(2.0)
    assert checks["interest_coverage"].value == pytest.approx(5.0)
    assert {row.shock: row.impact for row in result.stresses} == {
        "rate": -0.04, "inflation": 0.015, "refinancing": -0.03,
        "nav_sensitivity": -0.2,
    }
    assert result.status == "available"
    assert "expansion capex excluded" in checks["affo_reconciliation"].formula
    assert projection_payload(result) == projection_payload(_build("reit", evidence))
    assert result.execution_allowed is False


@pytest.mark.parametrize(
    ("model", "protected"),
    [("utility", "rab"), ("infrastructure", "regulated_asset_base")],
)
def test_utility_and_infrastructure_rab_and_statement_checks_fail_explicitly(
    model: str, protected: str,
) -> None:
    protected_metric = _metric(protected, model, 500)
    result = _build(model, (
        _metric("operating_cash_flow", model, 100),
        _metric("maintenance_capex", model, 20),
        _metric("expansion_capex", model, 50),
        _metric("distributions", model, 60),
        _metric("net_debt", model, 240),
        _metric("ebitda", model, 80),
        _metric("interest_expense", model, 16),
        protected_metric,
        _metric("allowed_return", model, 0.08, unit="ratio"),
        _metric("capex_funding_ratio", model, 0.9, unit="ratio"),
        _metric("tariff_regulatory_exposure", model, 0.75, unit="ratio"),
    ))
    checks = {row.check: row for row in result.checks}
    assert checks["payout"].value == pytest.approx(0.6)
    assert checks["leverage"].value == pytest.approx(3)
    assert checks["interest_coverage"].value == pytest.approx(5)
    assert result.status == "available"
    assert next(row for row in result.metrics if row.metric == protected).status == "available"
    assert next(row for row in result.metrics if row.metric == "allowed_return").direction == "higher_is_better"
    assert next(row for row in result.metrics if row.metric == "tariff_regulatory_exposure").direction == "lower_is_better"


@pytest.mark.parametrize(
    ("model", "protected"),
    [("reit", "nav"), ("utility", "rab"), ("infrastructure", "regulated_asset_base")],
)
def test_protected_valuation_metric_is_visible_and_blocks_available(
    model: str, protected: str,
) -> None:
    base = (
        (_metric("ffo", model, 100),) if model == "reit"
        else (_metric("operating_cash_flow", model, 100),)
    )
    result = _build(model, base)
    metric = next(row for row in result.metrics if row.metric == protected)
    assert metric.status == "unavailable" and metric.missing_policy == "unavailable"
    assert result.status == "partial"
    with pytest.raises(RealAssetAdapterError, match="reliable"):
        _build(model, base + (
            _metric(protected, model, 500, authority=SourceAuthority.COMMUNITY),
        ))


def test_wrong_route_cutoff_units_direction_future_and_generic_fallback_fail_closed() -> None:
    cases = [
        (_context("reit", sector="technology"), (_metric("ffo", "reit", 1),), "route"),
        (replace(_context("reit"), decision_time="2025-03-02T00:00:00Z"), (_metric("ffo", "reit", 1),), "cutoff"),
        (_context("reit"), (replace(_metric("ffo", "reit", 1), unit="ratio"),), "unit"),
        (_context("reit"), (replace(_metric("ffo", "reit", 1), direction="lower_is_better"),), "direction"),
        (_context("reit"), (replace(_metric("ffo", "reit", 1), known_at="2026-01-01T00:00:00Z"),), "lineage"),
        (_context("reit"), (replace(_metric("ffo", "reit", 1), as_of="2020-01-01T00:00:00Z"),), "lineage"),
        (_context("reit"), (_metric("pe_ratio", "reit", 10),), "fallback"),
    ]
    for context, evidence, match in cases:
        with pytest.raises(RealAssetAdapterError, match=match):
            _build("reit", evidence, context=context)


def test_invalid_stress_and_missing_statement_inputs_are_unavailable() -> None:
    result = _build("reit", (_metric("ffo", "reit", 100),), shocks={
        "rate": {"shock_rate": float("nan"), "exposed_amount": 1, "base_amount": 1},
        "inflation": {"shock_rate": 0.1, "exposed_amount": 1},
        "refinancing": {"shock_rate": 0.1, "exposed_amount": 1, "base_amount": 0},
    })
    assert all(row.status == "unavailable" for row in result.stresses)
    assert all(row.status == "unavailable" for row in result.checks)


def test_reit_derives_safe_ffo_affo_and_failed_reported_reconciliation_is_partial() -> None:
    derived = _build("reit", (
        _metric("net_income", "reit", 100),
        _metric("depreciation_amortisation", "reit", 40),
        _metric("property_sale_gains", "reit", 10),
        _metric("maintenance_capex", "reit", 20),
        _metric("recurring_adjustments", "reit", 5),
        _metric("nav", "reit", 400),
    ))
    metrics = {row.metric: row for row in derived.metrics}
    assert metrics["ffo"].value == 130 and metrics["affo"].value == 115
    assert metrics["ffo"].source_authority == "derived_statement_evidence"
    assert metrics["ffo"].definition.startswith("derived from statement evidence")
    failed = _build("reit", (
        _metric("net_income", "reit", 100),
        _metric("depreciation_amortisation", "reit", 40),
        _metric("property_sale_gains", "reit", 10),
        _metric("ffo", "reit", 999),
        _metric("maintenance_capex", "reit", 20),
        _metric("recurring_adjustments", "reit", 5),
        _metric("affo", "reit", 1),
        _metric("nav", "reit", 400),
    ))
    assert failed.status == "partial"
    assert "ffo_reconciliation:statement_mismatch" in failed.limitations
    assert "affo_reconciliation:statement_mismatch" in failed.limitations


def test_forgery_identity_and_bad_ui_payload_fail_closed() -> None:
    projection = _build("reit", (_metric("ffo", "reit", 100),))
    payload = projection_payload(projection)
    assert load_real_asset_projection("reit-1", projection=payload)["status"] == "partial"
    assert load_real_asset_projection("other", projection=payload)["status"] == "unavailable"
    assert load_real_asset_projection("reit-1", projection={**payload, "status": "forged"})["status"] == "unavailable"
    nested = {**payload, "metrics": [dict(payload["metrics"][0], value=999)]}
    assert load_real_asset_projection("reit-1", projection=nested)["status"] == "unavailable"
    assert load_real_asset_projection("reit-1", projection={**payload, "execution_allowed": True})["status"] == "unavailable"
    assert load_real_asset_projection("none")["status"] == "unavailable"


def test_projection_flows_through_selector_state_and_page() -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    projection = _build(
        "reit", (_metric("ffo", "reit", 100),),
        context=_context("reit", instrument_id=instrument_id),
    )
    payload = projection_payload(projection)
    model = build_instrument_detail(snapshot, instrument_id, real_asset_projection=payload)
    assert model.sections["real_assets"]["checks"]
    state = AppState(snapshot=snapshot, selected_etf=instrument_id, real_asset_projection=payload)
    rendered = instrument_detail_page(None, state)

    def texts(control: object) -> list[str]:
        values = [value] if isinstance((value := getattr(control, "value", None)), str) else []
        if (content := getattr(control, "content", None)) is not None:
            values.extend(texts(content))
        for child in getattr(control, "controls", ()) or ():
            values.extend(texts(child))
        return values

    visible = "\n".join(texts(rendered))
    assert "Real Assets" in visible and "ffo" in visible and "rate" in visible
