from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.fund_identity import (
    FundEvidence,
    FundEvidencePeriod,
    FundIdentityError,
    FundLifecycleEvent,
    FundLifecycleStatus,
    FundMetricState,
    FundTerm,
    fund_metric_availability,
    fund_recommendation_readiness,
    select_prospective_fund_evidence,
)
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.instrument_identity import IdentityClaim


def _claim(
    instrument_id: str,
    field: str,
    value: str,
    source_id: str,
    *,
    object_type: str = "instrument",
    object_id: str | None = None,
    parent_object_id: str | None = None,
    relationship: str | None = None,
    valid_from: str = "2024-01-01T00:00:00Z",
    available_at: str = "2024-01-02T00:00:00Z",
) -> IdentityClaim:
    return IdentityClaim(
        instrument_id=instrument_id,
        field=field,
        value=value,
        source="fixture",
        authority=SourceAuthority.OFFICIAL,
        source_id=source_id,
        object_type=object_type,
        object_id=object_id or instrument_id,
        parent_object_id=parent_object_id,
        relationship=relationship,
        valid_from=valid_from,
        available_at=available_at,
    )


def test_fund_multi_share_class_hierarchy(tmp_path: Path) -> None:
    claims = (
        _claim("SEC-ACC", "isin", "US0000000001", "acc:isin"),
        _claim(
            "SEC-ACC",
            "fund_structure",
            "ordinary_fund",
            "acc:structure",
            object_type="subfund",
            object_id="SUBFUND-1",
        ),
        _claim(
            "SEC-ACC",
            "distribution_policy",
            "accumulating",
            "acc:policy",
            object_type="share_class",
            object_id="SHARE-ACC",
            parent_object_id="SUBFUND-1",
            relationship="share_class_of",
        ),
        _claim("SEC-DIST", "isin", "US0000000002", "dist:isin"),
        _claim(
            "SEC-DIST",
            "fund_structure",
            "ordinary_fund",
            "dist:structure",
            object_type="subfund",
            object_id="SUBFUND-1",
        ),
        _claim(
            "SEC-DIST",
            "distribution_policy",
            "distributing",
            "dist:policy",
            object_type="share_class",
            object_id="SHARE-DIST",
            parent_object_id="SUBFUND-1",
            relationship="share_class_of",
        ),
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        accumulating = store.projection("SEC-ACC")
        distributing = store.projection("SEC-DIST")

    accumulating_class = accumulating["fund_identity"]["share_classes"][0]
    distributing_class = distributing["fund_identity"]["share_classes"][0]
    assert accumulating_class["distribution_policy"] == "accumulating"
    assert distributing_class["distribution_policy"] == "distributing"
    assert accumulating_class["share_class_id"] != distributing_class["share_class_id"]
    assert accumulating_class["sub_fund_id"] == distributing_class["sub_fund_id"] == "SUBFUND-1"
    assert accumulating["fund_identity"]["sub_funds"][0]["structure"] == "ordinary_fund"
    assert accumulating["fund_identity"]["share_classes"][0]["source_ids"] == ("acc:policy",)
    assert accumulating["execution_allowed"] is False


def test_fund_terms_project_lineage_for_their_selected_fields(tmp_path: Path) -> None:
    claims = (
        _claim(
            "SEC-ACC",
            "fund_structure",
            "ordinary_fund",
            "doc:structure",
            object_type="subfund",
            object_id="SUBFUND-1",
        ),
        _claim(
            "SEC-ACC",
            "sub_fund_currency",
            "EUR",
            "doc:currency",
            object_type="subfund",
            object_id="SUBFUND-1",
        ),
        _claim(
            "SEC-ACC",
            "distribution_policy",
            "accumulating",
            "doc:distribution",
            object_type="share_class",
            object_id="SHARE-ACC",
            parent_object_id="SUBFUND-1",
            relationship="share_class_of",
        ),
        _claim(
            "SEC-ACC",
            "share_class_currency",
            "EUR",
            "doc:share-class-currency",
            object_type="share_class",
            object_id="SHARE-ACC",
            parent_object_id="SUBFUND-1",
            relationship="share_class_of",
        ),
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_claims(claims)
        projection = store.projection("SEC-ACC")

    sub_fund = projection["fund_identity"]["sub_funds"][0]
    share_class = projection["fund_identity"]["share_classes"][0]
    assert sub_fund["structure"] == "ordinary_fund"
    assert sub_fund["structure_source_id"] == "doc:structure"
    assert set(sub_fund["source_ids"]) == {"doc:structure", "doc:currency"}
    assert share_class["distribution_policy"] == "accumulating"
    assert share_class["distribution_policy_source_id"] == "doc:distribution"
    assert set(share_class["source_ids"]) == {
        "doc:distribution",
        "doc:share-class-currency",
    }


def test_ordinary_fund_pricing_blocks_etf_spread() -> None:
    result = fund_metric_availability("ordinary_fund", "bid_ask_spread")

    assert result.state is FundMetricState.NOT_APPLICABLE
    assert result.value is None
    assert result.reason == "not_applicable_to_ordinary_fund_dealing"


def test_incubated_period_exclusion() -> None:
    evidence = (
        FundEvidence(
            "before-inception",
            "2023-12-31T00:00:00Z",
            "2023-12-31T00:00:00Z",
            FundEvidencePeriod.NORMAL,
            "source:pre-inception",
        ),
        FundEvidence(
            "incubated",
            "2024-01-02T00:00:00Z",
            "2024-01-03T00:00:00Z",
            FundEvidencePeriod.INCUBATED,
            "source:incubated",
        ),
        FundEvidence(
            "backfilled",
            "2024-01-03T00:00:00Z",
            "2024-01-04T00:00:00Z",
            FundEvidencePeriod.BACKFILLED,
            "source:backfilled",
        ),
        FundEvidence(
            "prospective",
            "2024-01-04T00:00:00Z",
            "2024-01-05T00:00:00Z",
            FundEvidencePeriod.NORMAL,
            "source:prospective",
        ),
    )
    selected = select_prospective_fund_evidence(
        evidence,
        inception_at="2024-01-01T00:00:00Z",
        effective_at="2024-01-10T00:00:00Z",
        decision_time="2024-01-10T00:00:00Z",
    )
    missing_inception = select_prospective_fund_evidence(evidence)

    assert tuple(item.evidence_id for item in selected.eligible) == ("prospective",)
    assert tuple((item.evidence_id, reason) for item, reason in selected.excluded) == (
        ("before-inception", "pre_inception"),
        ("incubated", "incubated_period"),
        ("backfilled", "backfilled_period"),
    )
    assert not missing_inception.eligible
    assert all(
        reason == "inception_at_unavailable,effective_at_unavailable,decision_time_unavailable"
        for _, reason in missing_inception.excluded
    )


def test_lifecycle_events_replay_at_effective_and_decision_times(tmp_path: Path) -> None:
    events = (
        FundLifecycleEvent(
            "FUND-CLOSED",
            "launch-1",
            FundLifecycleStatus.LAUNCHED,
            "2020-01-01T00:00:00Z",
            "2020-01-02T00:00:00Z",
            "fixture",
            "source:launch",
            SourceAuthority.OFFICIAL,
        ),
        FundLifecycleEvent(
            "FUND-CLOSED",
            "close-1",
            FundLifecycleStatus.CLOSED,
            "2024-01-01T00:00:00Z",
            "2024-01-02T00:00:00Z",
            "fixture",
            "source:close",
            SourceAuthority.OFFICIAL,
        ),
        FundLifecycleEvent(
            "FUND-CLOSED",
            "backdated-liquidation",
            FundLifecycleStatus.LIQUIDATED,
            "2024-06-01T00:00:00Z",
            "2025-01-02T00:00:00Z",
            "fixture",
            "source:late-liquidation",
            SourceAuthority.OFFICIAL,
        ),
        FundLifecycleEvent(
            "FUND-MERGED",
            "merge-1",
            FundLifecycleStatus.MERGED,
            "2024-01-01T00:00:00Z",
            "2024-01-02T00:00:00Z",
            "fixture",
            "source:merge",
            SourceAuthority.OFFICIAL,
            successor_fund_id="FUND-SUCCESSOR",
        ),
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_fund_lifecycle_events(events)
        historical = store.fund_lifecycle_events(
            "FUND-CLOSED",
            effective_at="2023-06-01T00:00:00Z",
            decision_time="2024-01-01T00:00:00Z",
        )
        current = store.fund_lifecycle_events(
            "FUND-CLOSED",
            effective_at="2024-06-01T00:00:00Z",
            decision_time="2024-06-01T00:00:00Z",
        )
        merged = store.fund_lifecycle_events(
            "FUND-MERGED",
            effective_at="2024-06-01T00:00:00Z",
            decision_time="2024-06-01T00:00:00Z",
        )
        later = store.fund_lifecycle_events(
            "FUND-CLOSED",
            effective_at="2025-06-01T00:00:00Z",
            decision_time="2025-06-01T00:00:00Z",
        )

    assert tuple(event.status for event in historical) == (FundLifecycleStatus.LAUNCHED,)
    assert tuple(event.status for event in current) == (
        FundLifecycleStatus.LAUNCHED,
        FundLifecycleStatus.CLOSED,
    )
    assert all(event.status is not FundLifecycleStatus.LIQUIDATED for event in current)
    assert merged[0].successor_fund_id == "FUND-SUCCESSOR"
    assert tuple(event.status for event in later) == (
        FundLifecycleStatus.LAUNCHED,
        FundLifecycleStatus.CLOSED,
        FundLifecycleStatus.LIQUIDATED,
    )


def test_lifecycle_replay_selects_latest_eligible_event_revision(tmp_path: Path) -> None:
    events = (
        FundLifecycleEvent(
            "FUND-CORRECTED",
            "closure-1",
            FundLifecycleStatus.CLOSED,
            "2024-01-01T00:00:00Z",
            "2024-01-02T00:00:00Z",
            "fixture",
            "source:closure",
            SourceAuthority.OFFICIAL,
            revision=1,
        ),
        FundLifecycleEvent(
            "FUND-CORRECTED",
            "closure-1",
            FundLifecycleStatus.LIQUIDATED,
            "2024-01-01T00:00:00Z",
            "2024-02-02T00:00:00Z",
            "fixture",
            "source:closure",
            SourceAuthority.OFFICIAL,
            revision=2,
        ),
    )
    with IdentityMasterStore(tmp_path) as store:
        store.append_fund_lifecycle_events(events)
        before_correction = store.fund_lifecycle_events(
            "FUND-CORRECTED",
            effective_at="2024-06-01T00:00:00Z",
            decision_time="2024-02-01T00:00:00Z",
        )
        after_correction = store.fund_lifecycle_events(
            "FUND-CORRECTED",
            effective_at="2024-06-01T00:00:00Z",
            decision_time="2024-03-01T00:00:00Z",
        )

    assert tuple(event.status for event in before_correction) == (FundLifecycleStatus.CLOSED,)
    assert tuple(event.revision for event in before_correction) == (1,)
    assert tuple(event.status for event in after_correction) == (FundLifecycleStatus.LIQUIDATED,)
    assert tuple(event.revision for event in after_correction) == (2,)


def test_critical_fund_terms_fail_closed_and_require_lineage() -> None:
    with pytest.raises(FundIdentityError, match="source ID or declared overlay ID"):
        FundTerm(
            "dealing_cutoff",
            "16:00",
            "2024-01-02T00:00:00Z",
            "2024-01-01T00:00:00Z",
        )

    dealing_cutoff = FundTerm(
        "dealing_cutoff",
        "16:00",
        "2024-01-02T00:00:00Z",
        "2024-01-01T00:00:00Z",
        source_id="document:dealing-terms",
    )
    fee = FundTerm(
        "ongoing_fee_bps",
        "12",
        "2024-01-02T00:00:00Z",
        "2024-01-01T00:00:00Z",
        overlay_id="declared-overlay:fee",
    )
    conflicting_fee = FundTerm(
        "ongoing_fee_bps",
        "14",
        "2024-01-02T00:00:00Z",
        "2024-01-01T00:00:00Z",
        source_id="document:conflicting-fee",
    )
    readiness = fund_recommendation_readiness(
        (dealing_cutoff, fee, conflicting_fee),
        effective_at="2024-06-01T00:00:00Z",
        decision_time="2024-06-01T00:00:00Z",
    )
    missing = fund_recommendation_readiness(
        (),
        effective_at="2024-06-01T00:00:00Z",
        decision_time="2024-06-01T00:00:00Z",
    )
    future_fee = FundTerm(
        "ongoing_fee_bps",
        "11",
        "2026-01-02T00:00:00Z",
        "2024-01-01T00:00:00Z",
        source_id="document:future-fee",
    )
    not_yet_known = fund_recommendation_readiness(
        (dealing_cutoff, future_fee),
        effective_at="2024-06-01T00:00:00Z",
        decision_time="2024-06-01T00:00:00Z",
    )
    missing_cutoffs = fund_recommendation_readiness((dealing_cutoff, fee))

    assert readiness.precise_liquidity_available is True
    assert readiness.precise_cost_available is False
    assert readiness.reasons == ("conflicted_ongoing_fee_bps",)
    assert missing.precise_liquidity_available is False
    assert missing.precise_cost_available is False
    assert missing.reasons == ("missing_dealing_cutoff", "missing_ongoing_fee_bps")
    assert not_yet_known.precise_cost_available is False
    assert not_yet_known.reasons == ("missing_ongoing_fee_bps",)
    assert not missing_cutoffs.precise_liquidity_available
    assert not missing_cutoffs.precise_cost_available
    assert missing_cutoffs.reasons == ("effective_time_unavailable", "decision_time_unavailable")
