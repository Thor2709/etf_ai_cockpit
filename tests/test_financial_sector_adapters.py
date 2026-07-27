from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from etf_cockpit.analysis.financial_sector_adapters import (
    FinancialAdapterError,
    FinancialMetricEvidence,
    build_financial_institution_projection,
    financial_adapter_definition,
    financial_formula_registry,
    projection_payload,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import load_financial_institution_projection
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.services import build_snapshot


DECISION = "2025-03-01T00:00:00Z"


def _context(
    model: str,
    *,
    sector: str = "financials",
    country: str = "NO",
    instrument_id: str | None = None,
):
    canonical_id = instrument_id or f"{model}-1"
    values = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": sector,
        "industry": "banks" if model == "bank" else "insurance",
        "business_model_tag": model,
        "operating_country": country,
        "reporting_currency": "NOK",
        "entity_id": canonical_id,
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{canonical_id}:{field}",
            instrument_id=canonical_id,
            field=field,
            value=value,
            source="fixture",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{field}",
            confidence=0.99,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence,
        instrument_id=canonical_id,
        effective_at="2024-12-31T00:00:00Z",
        decision_time=DECISION,
    )


def _metric(
    metric: str,
    model: str,
    value: float | None = 0.12,
    *,
    authority: SourceAuthority = SourceAuthority.OFFICIAL,
    unit: str | None = None,
    reporting_standard: str = "IFRS",
    jurisdiction: str = "NO",
) -> FinancialMetricEvidence:
    return FinancialMetricEvidence(
        metric=metric,
        value=value,
        unit=unit
        or ("currency_per_share" if metric == "tangible_book_value" else "ratio"),
        period="FY2024",
        reporting_standard=reporting_standard,
        jurisdiction=jurisdiction,
        business_model=model,
        source_id=f"regulator:{metric}",
        source_authority=authority,
        as_of="2024-12-31T00:00:00Z",
        known_at="2025-02-15T00:00:00Z",
    )


def _shocks() -> dict[str, object]:
    return {
        "credit_loss": {
            "shock_rate": 0.02,
            "exposed_amount": 500.0,
            "capital_base": 100.0,
        },
        "funding": {"shock_rate": 0.01, "exposed_amount": 200.0, "capital_base": 100.0},
        "market": {"shock_rate": 0.03, "exposed_amount": 100.0, "capital_base": 100.0},
    }


def _build(model: str, evidence: tuple[FinancialMetricEvidence, ...]):
    return build_financial_institution_projection(
        _context(model),
        evidence,
        registry=AdapterRegistry([financial_adapter_definition()]),
        decision_time=DECISION,
        shocks=_shocks(),
    )


@pytest.mark.parametrize(
    ("model", "metrics"),
    [
        (
            "bank",
            (
                "cet1_ratio",
                "total_capital_ratio",
                "tangible_book_value",
                "net_interest_margin",
                "cost_income_ratio",
                "loan_growth",
                "deposit_growth",
                "loan_deposit_ratio",
                "npl_ratio",
                "provision_ratio",
                "npl_coverage_ratio",
                "liquidity_coverage_ratio",
                "rote",
            ),
        ),
        (
            "insurer",
            (
                "combined_ratio",
                "loss_ratio",
                "expense_ratio",
                "solvency_capital_ratio",
                "reserve_adequacy",
                "premium_growth",
                "investment_yield",
                "reinsurance_exposure",
            ),
        ),
        (
            "diversified",
            (
                "funding_cost",
                "credit_loss_ratio",
                "capital_ratio",
                "fee_income_mix",
                "interest_income_mix",
            ),
        ),
    ],
)
def test_golden_models_units_authority_and_replay(
    model: str, metrics: tuple[str, ...]
) -> None:
    inputs = tuple(_metric(metric, model) for metric in metrics)
    result = _build(model, inputs)
    assert {item.metric for item in result.metrics} == set(metrics)
    assert result.authority_status == "high" and result.aggregate_confidence >= 0.8
    assert all(
        item.period == "FY2024" and item.reporting_standard == "IFRS"
        for item in result.metrics
    )
    assert all(item.status == "available" for item in result.stresses)
    assert result.variant_path == (
        f"financials:{model}:no",
        f"financials:{model}",
        "financials",
    )
    assert projection_payload(result) == projection_payload(_build(model, inputs))
    formulas = {
        item.metric: item
        for item in financial_formula_registry()
        if item.business_model == model
    }
    assert set(formulas) == set(metrics)
    assert (
        formulas.get(
            "tangible_book_value", next(iter(formulas.values()))
        ).formula_version
        == "financial-formulas.v1"
    )
    assert result.execution_allowed is False


def test_wrong_sector_cross_model_and_industrial_metrics_fail_closed() -> None:
    with pytest.raises(FinancialAdapterError, match="classified financials"):
        build_financial_institution_projection(
            _context("bank", sector="technology"),
            (_metric("cet1_ratio", "bank"),),
            registry=AdapterRegistry([financial_adapter_definition()]),
            decision_time=DECISION,
            shocks={},
        )
    with pytest.raises(FinancialAdapterError, match="invalid for bank"):
        _build("bank", (_metric("combined_ratio", "bank"),))
    result = _build(
        "bank",
        (
            _metric("cet1_ratio", "bank"),
            _metric("industrial_leverage", "bank"),
            _metric("pe_ratio", "bank"),
        ),
    )
    assert {item.metric for item in result.metrics} == {"cet1_ratio"}
    assert "industrial_leverage:inapplicable" in result.limitations


def test_units_directions_and_country_accounting_variants() -> None:
    for invalid in (
        replace(_metric("cet1_ratio", "bank"), unit="currency_per_share"),
        replace(_metric("tangible_book_value", "bank"), unit="ratio"),
        replace(_metric("cet1_ratio", "bank"), direction="lower_is_better"),
    ):
        with pytest.raises(FinancialAdapterError, match="unit or direction"):
            _build("bank", (invalid,))
    no = _build("bank", (_metric("cet1_ratio", "bank"),))
    us = build_financial_institution_projection(
        _context("bank", country="US"),
        (
            _metric(
                "cet1_ratio",
                "bank",
                12.5,
                unit="percent",
                reporting_standard="US-GAAP",
                jurisdiction="US",
            ),
        ),
        registry=AdapterRegistry([financial_adapter_definition()]),
        decision_time=DECISION,
        shocks={},
    )
    assert (no.metrics[0].value, no.metrics[0].unit) == (0.12, "ratio")
    assert (us.metrics[0].value, us.metrics[0].unit) == (12.5, "percent")
    assert us.metrics[0].reporting_standard == "US-GAAP"
    assert us.variant_path[0] == "financials:bank:us"


def test_projection_authority_complete_weak_missing_and_unavailable() -> None:
    complete = _build("bank", (_metric("cet1_ratio", "bank"),))
    weak = _build(
        "bank", (_metric("cet1_ratio", "bank", authority=SourceAuthority.COMMUNITY),)
    )
    missing = _build("bank", (_metric("npl_ratio", "bank"),))
    unavailable = _build("bank", (_metric("cet1_ratio", "bank", None),))
    assert complete.authority_status == "high"
    assert weak.authority_status == "limited" and weak.aggregate_confidence <= 0.55
    assert (
        missing.authority_status == "limited" and missing.aggregate_confidence <= 0.45
    )
    assert (
        unavailable.status == "unavailable" and unavailable.aggregate_confidence == 0.0
    )


def test_stresses_use_explicit_finite_bases_and_no_invention() -> None:
    result = _build("diversified", (_metric("capital_ratio", "diversified"),))
    assert {item.shock: item.capital_impact for item in result.stresses} == {
        "credit_loss": -0.1,
        "funding": -0.02,
        "market": -0.03,
    }
    assert all(
        item.formula == "-(abs(shock_rate) * exposed_amount / capital_base)"
        and item.unit == "ratio"
        for item in result.stresses
    )
    invalid = build_financial_institution_projection(
        _context("diversified"),
        (_metric("capital_ratio", "diversified"),),
        registry=AdapterRegistry([financial_adapter_definition()]),
        decision_time=DECISION,
        shocks={
            "credit_loss": {"shock_rate": 0.02, "exposed_amount": 500.0},
            "funding": {
                "shock_rate": 0.01,
                "exposed_amount": 200.0,
                "capital_base": 0.0,
            },
            "market": {
                "shock_rate": float("nan"),
                "exposed_amount": 100.0,
                "capital_base": 100.0,
            },
        },
    )
    assert all(item.status == "unavailable" for item in invalid.stresses)


def test_exact_classification_cutoff_and_authority() -> None:
    equivalent = replace(_context("bank"), decision_time="2025-03-01T10:00:00+10:00")
    assert (
        build_financial_institution_projection(
            equivalent,
            (_metric("cet1_ratio", "bank"),),
            registry=AdapterRegistry([financial_adapter_definition()]),
            decision_time=DECISION,
            shocks={},
        ).status
        == "available"
    )
    for context in (
        replace(_context("bank"), decision_time="2025-03-02T00:00:00Z"),
        replace(_context("bank"), execution_allowed=True),
    ):
        with pytest.raises(FinancialAdapterError, match="exact decision"):
            build_financial_institution_projection(
                context,
                (_metric("cet1_ratio", "bank"),),
                registry=AdapterRegistry([financial_adapter_definition()]),
                decision_time=DECISION,
                shocks={},
            )


def test_lineage_fields_reject_blank_or_future_values() -> None:
    for invalid in (
        replace(_metric("cet1_ratio", "bank"), period=""),
        replace(_metric("cet1_ratio", "bank"), known_at="2026-01-01T00:00:00Z"),
    ):
        with pytest.raises(FinancialAdapterError, match="lineage"):
            _build("bank", (invalid,))


def test_verified_available_projection_flows_facade_selector_and_page_contract() -> (
    None
):
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    projection = build_financial_institution_projection(
        _context("bank", instrument_id=instrument_id),
        (_metric("cet1_ratio", "bank"), _metric("npl_ratio", "bank")),
        registry=AdapterRegistry([financial_adapter_definition()]),
        decision_time=DECISION,
        shocks=_shocks(),
    )
    payload = projection_payload(projection)
    loaded = load_financial_institution_projection(instrument_id, projection=payload)
    assert loaded["status"] == "available" and loaded["execution_allowed"] is False
    model = build_instrument_detail(
        snapshot, instrument_id, financial_projection=payload
    )
    section = model.sections["financial_institutions"]
    assert section["metrics"] and section["stresses"] and section["lineage"]
    state = AppState(
        snapshot=snapshot,
        selected_etf=instrument_id,
        financial_projection=payload,
    )
    rendered = instrument_detail_page(None, state)

    def text_values(control: object) -> list[str]:
        values: list[str] = []
        value = getattr(control, "value", None)
        if isinstance(value, str):
            values.append(value)
        content = getattr(control, "content", None)
        if content is not None:
            values.extend(text_values(content))
        for child in getattr(control, "controls", ()) or ():
            values.extend(text_values(child))
        return values

    visible = "\n".join(text_values(rendered))
    assert "Financial Institutions" in visible
    assert "cet1_ratio" in visible and "credit_loss" in visible
    forged = {**payload, "execution_allowed": True}
    assert (
        load_financial_institution_projection(instrument_id, projection=forged)[
            "status"
        ]
        == "unavailable"
    )
    assert "instrument-detail.financial-institutions" in Path(
        "configs/ui_acceptance.yaml"
    ).read_text(encoding="utf-8")
    assert '"Financial Institutions"' in Path(
        "src/etf_cockpit/app/pages/instrument_detail.py"
    ).read_text(encoding="utf-8")


def test_default_ui_projection_is_explicitly_unavailable() -> None:
    unavailable = load_financial_institution_projection("NO-EVIDENCE")
    assert unavailable["status"] == "unavailable"
    assert unavailable["execution_allowed"] is False
