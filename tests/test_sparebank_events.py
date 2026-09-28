from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.analysis.sparebank.events import (
    analyse_events,
    conversion_event,
    deficit_coverage,
    merger_bridge,
    merger_ratios,
    rights_issue,
)


FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"


def _fixture() -> dict[str, object]:
    return json.loads((FIXTURES / "events.json").read_text(encoding="utf-8"))


def test_conversion_secondary_and_primary_claim_cash_boundaries() -> None:
    values = _fixture()["conversion"]
    result = conversion_event({"outstanding_ec_count": 4, "owner_pool_total": 400, "self_owned_pool_total": 600, "reconstructed_eierbrok": values["old_allocation_weight"]}, values["converted"], foundation_ec_count=values["foundation_ec"], converted_capital=300)
    assert result["cash_to_bank"] == 0
    assert result["post_state"]["outstanding_ec_count"] == 7
    assert result["allocation_weight_old_holders"] == pytest.approx(0.4)
    assert result["post_state"]["reconstructed_eierbrok"] == pytest.approx(0.7)


def test_rights_terp_and_deficit_waterfall() -> None:
    rights = _fixture()["rights"]
    result = rights_issue(rights["shares"], rights["book"], rights["subscription_price"], rights_ratio=rights["rights_ratio"], cum_price=rights["cum_price"])
    assert result["terp"] == pytest.approx(80)
    assert result["book_value_per_share_after"] == pytest.approx(86.6666667)
    assert result["right_value"] == pytest.approx(10)
    deficit = _fixture()["deficit"]
    waterfall = deficit_coverage(deficit["deficit"], owner_nominal=deficit["owner_nominal"], owner_premium_fund=deficit["owner_fund"], self_owned_capital=deficit["self_owned"])
    assert waterfall["self_owned_reduction"] == pytest.approx(60)
    assert waterfall["owner_fund_reduction"] == pytest.approx(5)


def test_skue_ratios_and_teaching_merger_paths_stay_separate() -> None:
    values = _fixture()
    ratios = merger_ratios(**values["skue"])
    assert ratios["bank_value_split"] == pytest.approx(0.227)
    assert ratios["target_ec_exchange_ratio"] == pytest.approx(0.5039375)
    assert ratios["post_merger_ec_class_ownership"] == pytest.approx(0.088)
    assert ratios["post_merger_eierbrok"] == pytest.approx(0.219)
    paths = {
        "delayed": (-1.98, (0.2,)),
        "base": (7.17, (1.0,)),
        "faster": (10.78, (1.5,)),
    }
    for path, (increment, ramp) in paths.items():
        result = merger_bridge(99, per_ec_increment=increment, implementation_path=path, implementation_ramp=ramp)
        assert result["increment_per_legacy_ec"] == pytest.approx(increment)
        assert result["ramp_factors"] == ramp


def test_merger_release_is_incremental_and_maturity_is_not_legal_close() -> None:
    bridge = merger_bridge(99, implementation_path="base", capital_release=75)
    assert bridge["capital_release"] == 75
    assert bridge["capital_release"] != 225
    analysis = analyse_events(({"event_type": "merger", "known_at": "2024-01-01T00:00:00Z", "legal_completion": "2024-02-01", "economic_maturity": None},), decision_time="2024-03-01T00:00:00Z")
    assert "economic_maturity" in analysis.unresolved_milestones


def test_known_at_invisibility_and_unsupported_event_fail_closed() -> None:
    analysis = analyse_events(({"event_type": "merger", "known_at": "2030-01-01T00:00:00Z"}, {"event_type": "mystery", "known_at": "2024-01-01T00:00:00Z"}), decision_time="2025-01-01T00:00:00Z")
    assert len(analysis.events) == 1
    assert analysis.events[0]["status"] == "UNSUPPORTED_EVENT"


@pytest.mark.parametrize("known_at", [None, "not-a-timestamp"])
def test_missing_or_invalid_known_at_is_invisible_at_decision_time(known_at: str | None) -> None:
    analysis = analyse_events(({"event_type": "conversion", "known_at": known_at, "converted": 3},), decision_time="2025-01-01T00:00:00Z")
    assert analysis.events == ()


def test_native_event_analysis_dispatches_conversion_and_merger_calculators() -> None:
    analysis = analyse_events(
        (
            {"event_type": "conversion", "known_at": "2024-01-01T00:00:00Z", "pre_state": {"outstanding_ec_count": 4}, "converted": 3},
            {"event_type": "merger", "known_at": "2024-01-01T00:00:00Z", "standalone": 99, "gross_benefit": 20, "recurring_added_capability": 5, "lost_customer_contribution": 3, "integration_costs": (2,), "tax_rate": 0.25, "per_ec_increment": 15},
        ),
        decision_time="2025-01-01T00:00:00Z",
    )
    assert analysis.events[0]["post_state"]["outstanding_ec_count"] == pytest.approx(7)
    assert analysis.events[1]["value_per_legacy_ec"] == pytest.approx(114)
