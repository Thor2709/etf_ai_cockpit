"""Issue 969: native claim, issuance, merger and filing regression guards."""

from copy import deepcopy

import pytest

from etf_cockpit.analysis.sparebank.claim import (
    analyse_sparebank_ec, build_claim_path, build_claim_state, routing,
)
from etf_cockpit.analysis.sparebank.events import (
    analyse_events, conversion_event, merger_bridge, primary_issue_event, rights_issue,
)
from etf_cockpit.analysis.sparebank.scorecard import _input_value
from etf_cockpit.analysis.sparebank.valuation import owner_valuation
from etf_cockpit.application.sparebank_evidence import with_derived_owner_earnings


def evidence():
    return {
        "known_at": "2025-02-01T00:00:00Z", "effective_at": "2024-12-31",
        "source_id": "fixture:969", "jurisdiction": "NO", "legal_form": "savings_bank",
        "instrument_subtype": "equity_certificate",
        "facts": {name: {"value": value, "available": True, "period": "2024-12-31",
                         "unit": "shares" if "count" in name else "ratio" if name == "eierbrok" else "NOK"}
                  for name, value in dict(ec_capital=400, overkursfond=0, utjevningsfond=0,
                      sparebankens_fond=600, gavefond=0, kompensasjonsfond=0,
                      eierbrok=0.4, outstanding_ec_count=4, period_end_ec_count=4,
                      weighted_average_ec_count=4, owner_attributable_book=400,
                      ec_attributable_result=48).items()},
    }


def merger(**overrides):
    return merger_bridge(100, **(dict(gross_benefit=1_000_000,
        recurring_added_capability=0, lost_customer_contribution=0,
        tax_rate=0.2, allocation_weight=0.4, legacy_ec_count=400_000) | overrides))


@pytest.mark.parametrize("key", ["ec_capital", "overkursfond", "utjevningsfond"])
def test_b015_n001_missing_owner_pool_key(key):
    data = evidence()
    del data["facts"][key]
    state = build_claim_state(data)
    assert state.claim_status != "resolved"
    assert state.reconstructed_eierbrok is None
    assert key in state.unavailable_fields


def test_b015_n002_period_end_count_conflict():
    data = evidence()
    data["facts"]["period_end_ec_count"]["value"] = 40
    result = analyse_sparebank_ec(data, price=100)
    assert result.owner_pb is None
    assert owner_valuation(result.claim_state, price=100, allow_partial=True)["status"] == "unavailable"


def test_b015_n002_period_end_count_without_reconciliation_evidence():
    data = evidence()
    del data["facts"]["outstanding_ec_count"]
    result = analyse_sparebank_ec(data, price=100)
    assert result.owner_pb is None
    assert owner_valuation(result.claim_state, price=100, allow_partial=True)["status"] == "unavailable"


def test_required_counts_match_book_statement_period():
    data = evidence()
    for name in ("outstanding_ec_count", "period_end_ec_count"):
        data["facts"][name]["period"] = "2023-12-31"
    assert analyse_sparebank_ec(data, price=100).owner_pb is None


@pytest.mark.parametrize("metadata", [{"unit": "NOK thousand"}, {"unit_scale": 1000}, {"scale": 3}])
def test_b015_n003_conditional_unit_scale_mismatch(metadata):
    data = evidence()
    data["facts"]["overkursfond"].update(metadata)
    assert build_claim_state(data).claim_status != "resolved"


def test_b017_n001_primary_issue_reconciles_recipients():
    result = primary_issue_event(10, 20, foundation_quantity=3, external_quantity=6,
                                 issue_resolution={"premium_allocation": {"overkursfond": 100}})
    assert not result["issued_quantity_reconciles"]
    assert result["status"] != "resolved"
    assert result["unknown_fields"]


def test_b017_n002_conversion_count_is_never_money():
    result = conversion_event({"outstanding_ec_count": 4, "owner_pool_total": 400,
                               "self_owned_pool_total": 600}, 3)
    assert result["post_state"]["outstanding_ec_count"] == 7
    assert result["post_state"]["reconstructed_eierbrok"] is None
    assert result["status"] != "resolved"


@pytest.mark.parametrize("ratio", [-0.5, 0, float("nan"), float("inf")])
def test_b017_n003_invalid_rights_ratio(ratio):
    result = rights_issue(10, 100, 5, rights_ratio=ratio, cum_price=10)
    assert result["status"] == "unavailable"
    assert result["terp"] is None


def test_b120_n001_missing_legacy_count():
    result = merger(legacy_ec_count=None)
    assert result["status"] == "unavailable"
    assert result["value_per_legacy_ec"] is None


def test_b120_n002_missing_allocation():
    result = merger(allocation_weight=None)
    assert result["status"] == "unavailable"
    assert result["value_per_legacy_ec"] is None


def test_b120_n003_soon_sb1no_consideration_continuity():
    terms = {"successor_instrument_id": "SB1NO", "successor_ec_per_legacy_ec": 0.481702,
             "cash_per_legacy_ec": 4.33235}
    result = analyse_events([{"event_type": "merger", "instrument_id": "SOON",
        "known_at": "2025-01-01T00:00:00Z", "effective_at": "2025-04-01", "terms": terms}])
    event = result.events[0]
    assert event["terms"] == terms
    assert event["instrument_id"] == "SOON"
    assert event["recipient_ledger"][0]["recipient"] == "legacy_ec_holders"
    assert event["recipient_ledger"][0]["successor_ec_per_legacy_ec"] == 0.481702
    assert event["recipient_ledger"][0]["cash_per_legacy_ec"] == 4.33235


def test_b120_n004_malformed_decision_time():
    result = analyse_events([{"event_type": "merger", "known_at": "2030-01-01"}], decision_time="bad")
    assert result.events == ()


@pytest.mark.parametrize("increment", [float("nan"), float("inf"), -float("inf")])
def test_required_finite_per_ec_increment(increment):
    result = merger_bridge(100, per_ec_increment=increment)
    assert result["status"] == "unavailable"
    assert result["value_per_legacy_ec"] is None


def test_b020_n001_missing_rate_preserves_horizon_fail_closed():
    result = merger(duration_years=3)
    assert result["status"] == "unavailable"
    assert result["value_per_legacy_ec"] is None


def test_b020_n002_one_off_cost_not_repeated():
    result = merger_bridge(100, gross_benefit=10, recurring_added_capability=0,
        lost_customer_contribution=0, tax_rate=0, integration_costs=(6,),
        duration_years=3, discount_rate=0, allocation_weight=1, legacy_ec_count=1)
    assert result["value_per_legacy_ec"] == pytest.approx(124)


@pytest.mark.parametrize("ramp", [[float("nan")], [-1], [], [1, 1]])
def test_b020_n003_invalid_ramp(ramp):
    result = merger(duration_years=3, discount_rate=0, implementation_ramp=ramp)
    assert result["status"] == "unavailable"
    assert result["value_per_legacy_ec"] is None


@pytest.mark.parametrize("weight", [-0.1, 1.1, float("nan")])
def test_b020_n004_invalid_owner_allocation(weight):
    result = merger(allocation_weight=weight)
    assert result["status"] == "unavailable"
    assert result["value_per_legacy_ec"] is None


def test_b020_n005_scorecard_selects_latest_effective_event():
    rows = [{"effective_at": "2024-01-01", "owner_value_accretion_pct": 1},
            {"effective_at": "2025-01-01", "owner_value_accretion_pct": 9}]
    for events in (rows, rows[::-1]):
        value = _input_value({"transform": "event_value_accretion_percent"}, {"events": {"events": events}})
        assert value == 9


@pytest.mark.parametrize("effective", [None, "bad"])
def test_b020_n005_unverifiable_event_chronology(effective):
    rows = [{"effective_at": "2024-01-01", "owner_value_accretion_pct": 1},
            {"effective_at": effective, "owner_value_accretion_pct": 9}]
    assert _input_value({"transform": "event_value_accretion_percent"}, {"events": {"events": rows}}) is None


def test_b016_n001_no_cross_period_derived_earnings():
    facts = evidence()["facts"]
    del facts["ec_attributable_result"]
    result = with_derived_owner_earnings(facts, {"period_end": "2025-12-31",
        "current": {"net_profit": 120, "basic_eps": 12}})
    assert "ec_attributable_result" not in result


def test_b016_n001_undated_book_cannot_receive_statement_earnings():
    facts = evidence()["facts"]
    del facts["ec_attributable_result"]
    for item in facts.values():
        item.pop("period", None)
    result = with_derived_owner_earnings(facts, {"period_end": "2025-12-31",
        "current": {"net_profit": 120, "basic_eps": 12}})
    assert "ec_attributable_result" not in result


def test_b016_n001_undated_claim_cannot_form_roe():
    data = evidence()
    del data["effective_at"]
    for item in data["facts"].values():
        item.pop("period", None)
    result = analyse_sparebank_ec(data, price=100)
    assert result.owner_eps is None
    assert result.bank_economics.normalised["reported_roe"] is None


def test_required_shared_statement_envelope_can_bind_undated_facts():
    data = evidence()
    for item in data["facts"].values():
        item.pop("period", None)
    assert analyse_sparebank_ec(data).owner_eps == 12
    del data["facts"]["ec_attributable_result"]
    statements = {"period_end": "2024-12-31", "current": {"net_profit": 120}}
    derived = with_derived_owner_earnings(data["facts"], statements, effective_at=data["effective_at"])
    assert derived["ec_attributable_result"]["value"] == 48
    assert "ec_attributable_result" not in with_derived_owner_earnings(
        data["facts"], statements, effective_at="2023-12-31")


def test_b016_n002_owner_only_profit_not_reapportioned():
    facts = evidence()["facts"]
    del facts["ec_attributable_result"]
    result = with_derived_owner_earnings(facts, {"period_end": "2024-12-31",
        "current": {"profit_attributable_to_owners": 90, "ownerless_result": 10}})
    assert "ec_attributable_result" not in result


def test_b115_n002_equivalent_norway_aliases():
    data = evidence() | {"operating_country": "Norway"}
    assert routing(data).applies


def test_b115_n003_negative_payout_rejected():
    result = build_claim_path(build_claim_state(evidence()), [{"profit": 120,
        "owner_payout_ratio": -0.1, "self_owned_payout_ratio": 0.5}])
    assert not result.periods
    assert result.reason_codes == ("PAYOUT_RATIO_EVIDENCE_MISSING",)


def test_b115_n001_unspecified_nested_identity_fails_closed():
    # The summary supplies no nested identity schema. Unsupported nesting
    # cannot confer routing authority; the specific audit claim is deferred.
    assert not routing({"issuer": evidence()}).applies


def test_required_matched_claim_periods():
    data = evidence()
    data["facts"]["ec_attributable_result"]["period"] = "2025-12-31"
    result = analyse_sparebank_ec(data, price=100)
    assert result.owner_eps is None
    assert result.bank_economics.normalised["reported_roe"] is None


def test_required_valid_merger_and_issue_controls():
    assert merger()["value_per_legacy_ec"] == pytest.approx(100.8)
    issue = primary_issue_event(10, 20, foundation_quantity=3, external_quantity=7,
                               issue_resolution={"premium_allocation": {"overkursfond": 100}})
    assert issue["status"] == "resolved"
    assert issue["issued_quantity_reconciles"]


def test_b017_n004_production_passes_payouts(tmp_path, monkeypatch):
    import etf_cockpit.analysis.sparebank as suite
    from etf_cockpit.application import financial_institution_views as views
    from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
    from etf_cockpit.data.contracts import SourceAuthority

    payouts = [{"profit": 120, "owner_payout_ratio": 0.5, "self_owned_payout_ratio": 0.2}]
    revision = evidence() | {"instrument_id": "fixture:969", "payouts": payouts}
    monkeypatch.setattr(views, "_read_json_artifact", lambda root, name, **kw: deepcopy(revision) if name == "ec_facts.json" else {})
    received = {}
    original = suite.analyse_sparebank_ec

    def capture(*args, **kwargs):
        received.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(suite, "analyse_sparebank_ec", capture)
    context = resolve_instrument_context(tuple(
        ClassificationEvidence(evidence_id=f"fixture:{field}", instrument_id="fixture:969",
            field=field, value=value, source="fixture", authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{field}", confidence=0.99,
            valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z")
        for field, value in {"instrument_type": "equity_certificate", "asset_class": "equity",
            "sector": "financials", "operating_country": "NO", "issuer_type": "savings_bank",
            "business_model_tag": "bank"}.items()), instrument_id="fixture:969",
        effective_at="2024-12-31T00:00:00Z", decision_time="2025-03-01T00:00:00Z")
    views.load_financial_institution_projection("fixture:969", storage_root=tmp_path,
        decision_time="2025-03-01T00:00:00Z", context=context)
    assert received.get("payouts") == payouts

