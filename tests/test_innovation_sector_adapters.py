from dataclasses import replace

import pytest

from etf_cockpit.analysis.innovation_sector_adapters import (
    InnovationAdapterError,
    InnovationEventEvidence,
    InnovationMetricEvidence,
    INNOVATION_CONFIDENCE_CAP,
    INNOVATION_MANUAL_CONFIDENCE_CAP,
    build_innovation_projection,
    innovation_adapter_definitions,
    innovation_formula_registry,
    innovation_result_hash,
    innovation_source_digest,
    projection_payload,
    verify_innovation_projection,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import load_innovation_projection
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.services import build_snapshot


DECISION = "2025-03-01T00:00:00Z"
EFFECTIVE = "2024-12-31T00:00:00Z"


def _context(model: str, *, instrument_id: str = "innovation-1", sector: str | None = None):
    sector = sector or ("technology" if model in {"software", "semiconductors"} else "healthcare")
    values = {
        "instrument_type": "stock", "asset_class": "equity", "sector": sector,
        "industry": model, "business_model_tag": model, "operating_country": "AU",
        "reporting_currency": "AUD", "entity_id": instrument_id,
    }
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
        evidence, instrument_id=instrument_id, effective_at=EFFECTIVE,
        decision_time=DECISION,
    )


def _metric(metric: str, model: str, value, *, unit: str = "currency", authority=SourceAuthority.ISSUER):
    return InnovationMetricEvidence(
        metric=metric, value=value, unit=unit, period="FY2024", reporting_standard="IFRS",
        jurisdiction="AU", business_model=model, source_id=f"issuer:{metric}",
        source_authority=authority, as_of=EFFECTIVE, known_at="2025-02-15T00:00:00Z",
    )


def _build(model: str, evidence, *, events=(), context=None):
    return build_innovation_projection(
        context or _context(model), evidence, events=events,
        registry=AdapterRegistry(innovation_adapter_definitions()), decision_time=DECISION,
    )


@pytest.mark.parametrize(
    ("model", "evidence"),
    [
        ("software", (
            _metric("recurring_revenue", "software", 800),
            _metric("net_revenue_retention", "software", 1.12, unit="ratio"),
            _metric("gross_margin", "software", 0.78, unit="ratio"),
            _metric("free_cash_flow", "software", 120),
            _metric("stock_compensation", "software", 45),
            _metric("diluted_shares", "software", 110, unit="shares"),
        )),
        ("semiconductors", (
            _metric("inventory", "semiconductors", 300),
            _metric("utilisation", "semiconductors", 0.86, unit="ratio"),
            _metric("capex", "semiconductors", 140),
            _metric("gross_margin", "semiconductors", 0.55, unit="ratio"),
            _metric("customer_concentration", "semiconductors", 0.22, unit="ratio"),
            _metric("cycle_phase", "semiconductors", "recovery", unit="label"),
        )),
        ("healthcare_pharma", (
            _metric("product_concentration", "healthcare_pharma", 0.48, unit="ratio"),
            _metric("patent_exclusivity_years", "healthcare_pharma", 7, unit="years"),
            _metric("r_and_d", "healthcare_pharma", 210),
            _metric("reimbursement_exposure", "healthcare_pharma", 0.35, unit="ratio"),
        )),
    ],
)
def test_golden_sector_metrics_keep_units_sources_periods_and_missing_states(model, evidence):
    result = _build(model, evidence)
    rows = {row.metric: row for row in result.metrics}
    assert all(row.source_id != "unavailable" for row in rows.values() if row.status == "available")
    assert all(row.period == "FY2024" for row in rows.values() if row.status == "available")
    missing = set(rows) - {item.metric for item in evidence}
    if missing:
        assert all(rows[metric].status == "unavailable" for metric in missing)
    assert result.valuation_status == "confidence_capped_inapplicable"
    assert result.execution_allowed is False


def test_biotech_runway_and_dilution_reconcile_and_event_probability_stays_low_authority():
    evidence = (
        _metric("cash_balance", "biotech", 120),
        _metric("operating_cash_burn", "biotech", 30, unit="currency_per_month"),
        _metric("cash_runway_months", "biotech", 4, unit="months"),
        _metric("shares_outstanding", "biotech", 100, unit="shares"),
        _metric("potential_dilution_shares", "biotech", 20, unit="shares"),
        _metric("dilution_rate", "biotech", 0.2, unit="ratio"),
    )
    event = InnovationEventEvidence(
        event_id="trial-1", event_type="trial_milestone", title="Phase 2 readout",
        stage="phase_2", event_date="2025-06-30T00:00:00Z", period="FY2025",
        source_id="registry:trial-1", source_authority=SourceAuthority.OFFICIAL,
        as_of=EFFECTIVE, known_at="2025-02-15T00:00:00Z", outcome_probability=0.75,
    )
    result = _build("biotech", evidence, events=(event,))
    assert result.status == "available"
    assert {check.check: check.status for check in result.checks} == {
        "cash_runway_reconciliation": "available", "dilution_reconciliation": "available",
    }
    assert result.milestone_timeline[0]["event_id"] == "trial-1"
    assert result.events[0].outcome_probability is None
    assert result.events[0].probability_status == "low_authority_not_used"
    assert "event_outcomes:low_authority_not_used" in result.limitations


def test_biotech_mismatch_is_partial_and_missing_inputs_are_explicit():
    mismatch = _build("biotech", (
        _metric("cash_balance", "biotech", 120),
        _metric("operating_cash_burn", "biotech", 30, unit="currency_per_month"),
        _metric("cash_runway_months", "biotech", 9, unit="months"),
        _metric("shares_outstanding", "biotech", 100, unit="shares"),
        _metric("potential_dilution_shares", "biotech", 20, unit="shares"),
        _metric("dilution_rate", "biotech", 0.4, unit="ratio"),
    ))
    assert mismatch.status == "partial"
    assert "cash_runway_reconciliation:statement_mismatch" in mismatch.limitations
    assert "dilution_reconciliation:statement_mismatch" in mismatch.limitations
    missing = _build("biotech", (_metric("cash_balance", "biotech", 120),))
    assert next(row for row in missing.metrics if row.metric == "cash_runway_months").status == "unavailable"
    assert "cash_runway_reconciliation:inputs_missing" in missing.limitations


def test_metric_aware_domains_allow_signed_fcf_growth_and_unbounded_nrr_but_reject_bad_bounds():
    result = _build("software", (
        _metric("free_cash_flow", "software", -120),
        _metric("recurring_revenue_growth", "software", -0.2, unit="ratio"),
        _metric("net_revenue_retention", "software", 1.35, unit="ratio"),
        _metric("stock_compensation", "software", -1),
        _metric("gross_margin", "software", 1.2, unit="ratio"),
    ))
    rows = {row.metric: row for row in result.metrics}
    assert rows["free_cash_flow"].status == "available"
    assert rows["recurring_revenue_growth"].status == "available"
    assert rows["net_revenue_retention"].status == "available"
    assert rows["stock_compensation"].status == "unavailable"
    assert rows["gross_margin"].status == "unavailable"


def test_software_share_dilution_reconciles_mismatch_and_missing_inputs_explicitly():
    derived = _build("software", (
        _metric("basic_shares", "software", 100, unit="shares"),
        _metric("diluted_shares", "software", 115, unit="shares"),
    ))
    rows = {row.metric: row for row in derived.metrics}
    assert rows["dilution_rate"].value == pytest.approx(0.15)
    assert rows["dilution_rate"].source_id == "derived:dilution_rate"
    assert derived.checks[0].check == "dilution_reconciliation"
    assert derived.checks[0].status == "available"

    mismatch = _build("software", (
        _metric("basic_shares", "software", 100, unit="shares"),
        _metric("diluted_shares", "software", 115, unit="shares"),
        _metric("dilution_rate", "software", 0.3, unit="ratio"),
    ))
    mismatch_rows = {row.metric: row for row in mismatch.metrics}
    assert mismatch_rows["dilution_rate"].status == "unavailable"
    assert mismatch.checks[0].status == "partial"
    assert "dilution_reconciliation:statement_mismatch" in mismatch.limitations

    missing = _build("software", (_metric("diluted_shares", "software", 115, unit="shares"),))
    assert next(row for row in missing.metrics if row.metric == "dilution_rate").status == "unavailable"
    assert missing.checks[0].status == "partial"
    assert "dilution_reconciliation:inputs_missing" in missing.limitations

    disclosed_without_inputs = _build(
        "software", (_metric("dilution_rate", "software", 0.15, unit="ratio"),)
    )
    assert disclosed_without_inputs.checks[0].status == "partial"


def test_wrong_sector_unit_missing_authority_and_generic_valuation_fail_closed():
    cases = [
        (_context("software", sector="industrials"), (_metric("gross_margin", "software", 0.8, unit="ratio"),), "technology or healthcare"),
        (_context("software"), (replace(_metric("gross_margin", "software", 80, unit="percent"), unit="currency"),), "unit"),
        (_context("software"), (_metric("gross_margin", "software", 0.8, unit="ratio", authority=SourceAuthority.VENDOR),), "authority"),
        (_context("software"), (_metric("pe_ratio", "software", 12),), "generic"),
    ]
    for context, evidence, message in cases:
        with pytest.raises(InnovationAdapterError, match=message):
            _build("software", evidence, context=context)


def test_formula_registry_and_verified_ui_projection_are_versioned_and_fail_closed():
    registry = {(row.business_model, row.metric): row for row in innovation_formula_registry()}
    assert registry["software", "net_revenue_retention"].missing_policy == "unavailable_not_disclosed"
    assert registry["biotech", "cash_runway_months"].parent_fallback == "sector:healthcare"
    result = _build("software", (_metric("gross_margin", "software", 0.8, unit="ratio"),))
    payload = projection_payload(result)
    digest = innovation_source_digest(result.source_payload)
    assert load_innovation_projection("innovation-1", projection=payload, expected_source_digest=digest)["status"] == "partial"
    assert load_innovation_projection("other", projection=payload, expected_source_digest=digest)["status"] == "unavailable"
    forged = {**payload, "metrics": [dict(payload["metrics"][0], value=0.1)]}
    forged["result_hash"] = innovation_result_hash(forged)
    assert load_innovation_projection("innovation-1", projection=forged, expected_source_digest=digest)["status"] == "unavailable"

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.etfs[0].id
    matching = _build(
        "software", (_metric("gross_margin", "software", 0.8, unit="ratio"),),
        events=(InnovationEventEvidence(
            event_id="concentration-1", event_type="product_concentration",
            title="Top customer disclosure", stage=None,
            event_date="2025-06-30T00:00:00Z", period="FY2025",
            source_id="issuer:concentration-1", source_authority=SourceAuthority.ISSUER,
            as_of=EFFECTIVE, known_at="2025-02-15T00:00:00Z", concentration=0.6,
        ),),
        context=_context("software", instrument_id=instrument_id),
    )
    matching_payload = projection_payload(matching)
    model = build_instrument_detail(snapshot, instrument_id, innovation_projection=matching_payload, innovation_source_digest=innovation_source_digest(matching.source_payload))
    assert model.sections["innovation"]["valuation_status"] == "confidence_capped_inapplicable"
    state = AppState(snapshot=snapshot, selected_etf=instrument_id, innovation_projection=matching_payload, innovation_source_digest=innovation_source_digest(matching.source_payload))
    rendered = instrument_detail_page(None, state)
    rendered_text = "\n".join(_text_values(rendered))
    assert "Innovation and Healthcare" in rendered_text
    assert "aggregate_confidence" in rendered_text
    assert "concentration-1" in rendered_text


def test_verified_projection_replays_all_metric_and_event_fields_after_rehash():
    result = _build("biotech", (
        _metric("cash_balance", "biotech", 120),
        _metric("operating_cash_burn", "biotech", 30, unit="currency_per_month"),
        _metric("shares_outstanding", "biotech", 100, unit="shares"),
        _metric("potential_dilution_shares", "biotech", 20, unit="shares"),
    ), events=(InnovationEventEvidence(
        event_id="trial-1", event_type="trial_milestone", title="Phase 2 readout",
        stage="phase_2", event_date="2025-06-30T00:00:00Z", period="FY2025",
        source_id="registry:trial-1", source_authority=SourceAuthority.OFFICIAL,
        as_of=EFFECTIVE, known_at="2025-02-15T00:00:00Z", outcome_probability=0.75,
    ),))
    payload = projection_payload(result)
    digest = innovation_source_digest(result.source_payload)
    mutations = (
        ("metrics", {"source_authority": "manual"}),
        ("events", {"event_date": "2025-07-01T00:00:00Z"}),
        ("events", {"source_id": "forged:event"}),
        ("events", {"probability_status": "not_applicable"}),
    )
    for field, changes in mutations:
        forged = {**payload, field: [dict(row, **changes) for row in payload[field]]}
        forged["result_hash"] = innovation_result_hash(forged)
        with pytest.raises(InnovationAdapterError):
            verify_innovation_projection(forged, expected_source_digest=digest)


@pytest.mark.parametrize("mutation", [
    lambda source: {**source, "extra": True},
    lambda source: {key: value for key, value in source.items() if key != "events"},
])
def test_source_payload_extra_or_missing_keys_fail_closed_even_with_valid_projection_hash(mutation):
    result = _build("software", (_metric("gross_margin", "software", 0.8, unit="ratio"),))
    forged_source = mutation(dict(result.source_payload))
    forged = {**projection_payload(result), "source_payload": forged_source}
    forged["result_hash"] = innovation_result_hash(forged)
    with pytest.raises(InnovationAdapterError):
        verify_innovation_projection(forged, expected_source_digest=innovation_source_digest(forged_source))


@pytest.mark.parametrize("remove_field", [False, True])
def test_projection_extra_or_missing_schema_keys_fail_closed_after_rehash(remove_field):
    result = _build("software", (_metric("gross_margin", "software", 0.8, unit="ratio"),))
    forged = projection_payload(result)
    if remove_field:
        forged.pop("metrics")
    else:
        forged["unexpected"] = True
    forged["result_hash"] = innovation_result_hash(forged)
    with pytest.raises(InnovationAdapterError):
        verify_innovation_projection(forged, expected_source_digest=innovation_source_digest(result.source_payload))


@pytest.mark.parametrize("evidence", [
    replace(_metric("gross_margin", "software", 0.8, unit="ratio"), as_of="2025-02-16T00:00:00Z"),
    replace(_metric("gross_margin", "software", 0.8, unit="ratio"), known_at="2025-03-02T00:00:00Z"),
])
def test_metric_temporal_ordering_and_authority_are_fail_closed(evidence):
    with pytest.raises(InnovationAdapterError, match="future-known"):
        _build("software", (evidence,))


def test_event_as_of_must_not_follow_known_at_but_future_milestone_date_is_allowed():
    event = InnovationEventEvidence(
        event_id="trial-1", event_type="trial_milestone", title="Phase 2 readout",
        stage="phase_2", event_date="2030-06-30T00:00:00Z", period="FY2030",
        source_id="registry:trial-1", source_authority=SourceAuthority.OFFICIAL,
        as_of="2025-02-16T00:00:00Z", known_at="2025-02-15T00:00:00Z",
    )
    with pytest.raises(InnovationAdapterError, match="future-known"):
        _build("biotech", (), events=(event,))
    valid = replace(event, as_of=EFFECTIVE)
    assert _build("biotech", (), events=(valid,)).events[0].event_date == "2030-06-30T00:00:00Z"
    with pytest.raises(InnovationAdapterError, match="future-known"):
        _build("biotech", (), events=(replace(valid, known_at="2025-03-02T00:00:00Z"),))


@pytest.mark.parametrize(("field", "value"), [
    ("outcome_probability", "0.75"),
    ("concentration", True),
])
def test_event_numeric_fields_reject_coercible_non_numbers(field, value):
    event = InnovationEventEvidence(
        event_id="trial-1", event_type="trial_milestone", title="Phase 2 readout",
        stage="phase_2", event_date="2030-06-30T00:00:00Z", period="FY2030",
        source_id="registry:trial-1", source_authority=SourceAuthority.OFFICIAL,
        as_of=EFFECTIVE, known_at="2025-02-15T00:00:00Z",
    )
    with pytest.raises(InnovationAdapterError, match="probability|concentration"):
        _build("biotech", (), events=(replace(event, **{field: value}),))


def test_unregistered_adapter_fallback_is_rejected():
    with pytest.raises(InnovationAdapterError, match="classification route"):
        build_innovation_projection(
            _context("software"), (_metric("gross_margin", "software", 0.8, unit="ratio"),),
            registry=AdapterRegistry(), decision_time=DECISION,
        )


def test_concentration_timeline_and_manual_confidence_caps_are_explicit():
    event = InnovationEventEvidence(
        event_id="customer-1", event_type="product_concentration", title="Top customer disclosure",
        stage=None, event_date="2025-06-30T00:00:00Z", period="FY2025",
        source_id="issuer:customer-1", source_authority=SourceAuthority.MANUAL,
        as_of=EFFECTIVE, known_at="2025-02-15T00:00:00Z", concentration=0.6,
    )
    full = (
        _metric("recurring_revenue", "software", 800),
        _metric("recurring_revenue_growth", "software", 0.2, unit="ratio"),
        _metric("net_revenue_retention", "software", 1.12, unit="ratio"),
        _metric("gross_margin", "software", 0.78, unit="ratio"),
        _metric("free_cash_flow", "software", 120),
        _metric("stock_compensation", "software", 45),
        _metric("basic_shares", "software", 100, unit="shares"),
        _metric("diluted_shares", "software", 110, unit="shares"),
        _metric("dilution_rate", "software", 0.1, unit="ratio"),
    )
    capped = _build("software", full)
    manual = _build("software", full, events=(event,))
    assert capped.aggregate_confidence == INNOVATION_CONFIDENCE_CAP
    assert capped.aggregate_confidence < 1
    assert manual.aggregate_confidence == INNOVATION_MANUAL_CONFIDENCE_CAP
    assert "confidence:sector_valuation_cap" in manual.limitations
    assert "confidence:manual_evidence_cap" in manual.limitations
    assert "manual evidence applies a further deterministic confidence cap" in manual.rationale
    assert manual.concentration_timeline == ({
        "event_id": "customer-1", "event_date": "2025-06-30T00:00:00Z",
        "event_type": "product_concentration", "concentration": 0.6,
        "source_id": "issuer:customer-1", "source_authority": "manual",
    },)


def _text_values(control):
    values = [value] if isinstance((value := getattr(control, "value", None)), str) else []
    if (content := getattr(control, "content", None)) is not None:
        values.extend(_text_values(content))
    for child in getattr(control, "controls", ()) or ():
        values.extend(_text_values(child))
    return values
