from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.analysis.sparebank import (
    CONTRACT_ID,
    analyse_sparebank_ec,
    build_claim_path,
    build_claim_state,
    reconstruct_eierbrok,
    routing,
)
from etf_cockpit.application.ui_facade import load_financial_institution_projection
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority


FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_full_ec_evidence_routes_to_native_suite() -> None:
    result = analyse_sparebank_ec(_fixture("teaching_bank.json"))
    assert result.contract == CONTRACT_ID
    assert result.routing.applies
    assert result.routing.suite_id == CONTRACT_ID


@pytest.mark.parametrize(
    "evidence",
    [
        {"jurisdiction": "NO", "legal_form": "savings_bank", "instrument_type": "stock"},
        {"jurisdiction": "NO", "legal_form": "ordinary_corporation", "instrument_type": "equity_certificate"},
        {"jurisdiction": "NO", "legal_form": "savings_bank"},
    ],
)
def test_ordinary_or_missing_ec_evidence_does_not_route(evidence: dict[str, str]) -> None:
    result = routing(evidence)
    assert not result.applies
    assert result.reason_codes


def test_teaching_bank_owner_figures_reject_whole_bank_pe() -> None:
    result = analyse_sparebank_ec(_fixture("teaching_bank.json"), price=100.0)
    assert result.claim_state.reconstructed_eierbrok is None
    assert result.claim_state.reported_eierbrok == pytest.approx(0.4)
    assert result.owner_eps == pytest.approx(12.0)
    assert result.owner_book_per_ec == pytest.approx(100.0)
    assert result.owner_pe == pytest.approx(100 / 12)
    assert 100 / 120 * 4 != pytest.approx(result.owner_pe)


def test_haugesund_reconstruction_uses_owner_pools_not_accounting_equity() -> None:
    state = build_claim_state(_fixture("haugesund_2025.json"))
    assert state.reconstructed_eierbrok is None  # gavefond is not reported, so its value is not inferred as zero
    assert state.reported_eierbrok == pytest.approx(0.2584)
    assert state.accounting_equity == pytest.approx(2760.431)
    assert reconstruct_eierbrok({"ec_capital": 625.430}, {"sparebankens_fond": 1795.172}) != pytest.approx(625.430 / 2760.431)


def test_period_end_and_weighted_average_counts_are_not_swapped() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"]["owner_attributable_book"] = {"available": True, "value": 400.0}
    evidence["facts"]["ec_attributable_result"] = {"available": True, "value": 48.0}
    evidence["facts"]["outstanding_ec_count"] = {"available": True, "value": 4.0}
    evidence["facts"]["weighted_average_ec_count"] = {"available": True, "value": 6.0}
    result = analyse_sparebank_ec(evidence)
    assert result.owner_book_per_ec == pytest.approx(100.0)
    assert result.owner_eps == pytest.approx(8.0)
    assert result.count_conventions["owner_book_per_ec"] == "period_end_ec_count"
    assert result.count_conventions["owner_eps"] == "weighted_average_ec_count"


def test_foundation_ecs_are_outstanding_not_treasury() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"].update(
        {
            "outstanding_ec_count": {"available": True, "value": 10.0},
            "treasury_ec_count": {"available": True, "value": 2.0},
            "foundation_ec_count": {"available": True, "value": 3.0},
        }
    )
    state = build_claim_state(evidence)
    assert state.outstanding_ec_count == 10.0
    assert state.treasury_ec_count == 2.0
    assert state.foundation_ec_count == 3.0


def test_eierbrok_path_uses_each_side_payout() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"]["gavefond"] = {"available": True, "value": 0.0}
    state = build_claim_state(evidence)
    equal = build_claim_path(state, [{"period": "equal", "profit": 120.0, "owner_payout_ratio": 0.5, "self_owned_payout_ratio": 0.5}])
    unequal = build_claim_path(state, [{"period": "unequal", "profit": 120.0, "owner_payout_ratio": 0.75, "self_owned_payout_ratio": 0.25}])
    retained = build_claim_path(state, [{"period": "retained", "profit": 120.0, "owner_payout_ratio": 0.75, "self_owned_payout_ratio": 0.25}])
    assert equal.periods[0]["eierbrok"] == pytest.approx(0.4)
    assert unequal.periods[0]["eierbrok"] == pytest.approx(0.386491228, abs=0.0001)
    assert retained.periods[0]["eierbrok"] == pytest.approx(0.386491228, abs=0.0001)
    assert (equal.periods[0]["owner_pool"] + equal.periods[0]["owner_distribution"]) / 4 == pytest.approx(112.0)
    assert (unequal.periods[0]["owner_pool"] + unequal.periods[0]["owner_distribution"]) / 4 == pytest.approx(112.0)
    assert retained.periods[0]["owner_distribution"] == pytest.approx(36.0)
    assert retained.periods[0]["self_owned_distribution"] == pytest.approx(18.0)


def test_unavailable_pool_component_does_not_resolve_claim() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"]["overkursfond"] = {"available": False, "value": None}
    result = analyse_sparebank_ec(evidence)
    assert result.claim_state.claim_status == "partial"
    assert result.claim_state.reconstructed_eierbrok is None
    assert "POOL_COMPONENT_EVIDENCE_MISSING" in result.claim_state.reason_codes


def test_partial_claim_suppresses_owner_valuation_figures() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"].pop("sparebankens_fond")
    result = analyse_sparebank_ec(evidence, price=100.0)
    assert result.owner_book_per_ec is None
    assert result.owner_eps is None
    assert result.owner_pe is None
    assert result.owner_pb is None
    assert "OWNER_VALUATION_CLAIM_NOT_RESOLVED" in result.reason_codes


def test_revision_envelope_known_at_binds_claim_before_fact_timestamps() -> None:
    from etf_cockpit.application.financial_institution_views import _select_ec_revision

    facts = _fixture("teaching_bank.json")["facts"]
    payload = {
        "revisions": [
            {"instrument_id": "TEACHING-EC", "known_at": "2030-01-01T00:00:00Z", "filing_version": "v2", "source": "fixture://v2", "facts": facts},
            {"instrument_id": "TEACHING-EC", "known_at": "2024-01-01T00:00:00Z", "filing_version": "v1", "source": "fixture://v1", "facts": facts},
        ]
    }
    assert _select_ec_revision(payload, "TEACHING-EC", "2025-01-01T00:00:00Z")["filing_version"] == "v1"
    selected = _select_ec_revision(payload, "TEACHING-EC", "2031-01-01T00:00:00Z")
    state = build_claim_state({**selected, "facts": selected["facts"]})
    assert state.known_at == "2030-01-01T00:00:00Z"
    assert state.claim_status == "resolved"


def test_tag_only_and_conflicting_routing_evidence_fail_closed() -> None:
    tag_only = routing({"jurisdiction": "NO", "business_model_tags": ["savings_bank"], "instrument_subtype": "equity_certificate"})
    conflicting = routing({"jurisdiction": "NO", "legal_form": "savings_bank", "issuer_type": "ordinary_corporation", "instrument_subtype": "equity_certificate"})
    assert not tag_only.applies
    assert "LEGAL_FORM_EVIDENCE_MISSING" in tag_only.reason_codes
    assert not conflicting.applies
    assert "LEGAL_FORM_EVIDENCE_CONFLICT" in conflicting.reason_codes


def test_contradictory_ec_counts_are_ambiguous() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"].update(
        {
            "registered_ec_count": {"available": True, "value": 2.0},
            "outstanding_ec_count": {"available": True, "value": 2.0},
            "treasury_ec_count": {"available": True, "value": 2.0},
            "foundation_ec_count": {"available": True, "value": 3.0},
        }
    )
    state = build_claim_state(evidence)
    assert state.claim_status == "ambiguous"
    assert "EC_COUNT_RECONCILIATION_CONTRADICTION" in state.reason_codes


def test_unresolved_claim_disables_generic_valuation() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"].pop("sparebankens_fond")
    result = analyse_sparebank_ec(evidence)
    assert result.claim_state.claim_status != "resolved"
    assert result.generic_valuation_status == "inapplicable"


def test_claim_known_after_decision_time_is_invisible() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["known_at"] = "2030-01-01T00:00:00Z"
    state = build_claim_state(evidence, decision_time="2025-01-02T00:00:00Z")
    assert state.claim_status == "stale"
    assert state.reconstructed_eierbrok is None


@pytest.mark.parametrize("known_at", [None, "invalid"])
def test_claim_missing_or_invalid_known_at_is_stale_at_decision_time(known_at: str | None) -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["known_at"] = known_at
    state = build_claim_state(evidence, decision_time="2025-01-02T00:00:00Z")
    assert state.claim_status == "stale"
    assert state.reconstructed_eierbrok is None


def test_missing_optional_fields_lower_coverage_without_zero_fill() -> None:
    evidence = _fixture("teaching_bank.json")
    evidence["facts"].pop("weighted_average_ec_count")
    result = analyse_sparebank_ec(evidence)
    # SB2: without a reported weighted average the EPS uses the period-end certificate count and says so
    # (a labelled, conservative stand-in; it is never a fabricated or zero-filled count).
    assert result.owner_eps == pytest.approx(result.claim_state.owner_attributable_earnings / result.claim_state.period_end_ec_count)
    assert result.claim_state.weighted_average_ec_count is None
    assert result.claim_state.coverage < 1.0
    assert "weighted_average_ec_count" in result.claim_state.unavailable_fields


def test_application_route_consumes_persisted_ec_revision(tmp_path: Path) -> None:
    import pandas as pd

    rows = [
        {"instrument_id": "MING", "canonical_metric": "net_interest_income", "value": 100.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:nim"},
        {"instrument_id": "MING", "canonical_metric": "operating_expenses", "value": 40.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:opex"},
        {"instrument_id": "MING", "canonical_metric": "loans_to_customers", "value": 800.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:loans"},
        {"instrument_id": "MING", "canonical_metric": "deposits_from_customers", "value": 1000.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:deposits"},
        {"instrument_id": "MING", "canonical_metric": "cet1_ratio", "value": 0.18, "unit": "ratio", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "pillar3:cet1", "taxonomy": "pillar3"},
    ]
    pd.DataFrame(rows).to_parquet(tmp_path / "statement_facts.parquet", index=False)
    (tmp_path / "ec_facts.json").write_text(json.dumps(_fixture("teaching_bank.json") | {"instrument_id": "MING"}), encoding="utf-8")
    context = resolve_instrument_context(
        tuple(
            ClassificationEvidence(
                evidence_id=f"MING:{field}", instrument_id="MING", field=field, value=value,
                source="fixture", authority=SourceAuthority.OFFICIAL, source_id=f"fixture:{field}", confidence=0.99,
                valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z",
            )
            for field, value in {
                "instrument_type": "equity_certificate",
                "asset_class": "equity", "sector": "financials", "operating_country": "NO",
                "issuer_type": "savings_bank", "business_model_tag": "bank",
            }.items()
        ),
        instrument_id="MING", effective_at="2024-12-31T00:00:00Z", decision_time="2025-03-01T00:00:00Z",
    )
    payload = load_financial_institution_projection("MING", storage_root=tmp_path, decision_time="2025-03-01T00:00:00Z", context=context)
    assert payload["share_class_identity"]["native_suite"] == CONTRACT_ID
