from __future__ import annotations

from etf_cockpit.data.contracts import SourceAuthority

import pytest

from etf_cockpit.data.instrument_identity import (
    AmbiguousIdentityAvailabilityError,
    IdentityClaim,
    IdentityReviewDecision,
    resolve_identity,
)


def test_identity_resolution_preserves_unknown_isin_and_provider_symbols() -> None:
    result = resolve_identity(
        [
            IdentityClaim("AURG", "name", "Aurskog Sparebank", "universe", SourceAuthority.MANUAL),
            IdentityClaim("AURG", "ticker", "AURG", "universe", SourceAuthority.MANUAL),
            IdentityClaim("AURG", "yahoo_symbol", "AURG.OL", "universe", SourceAuthority.MANUAL),
            IdentityClaim("AURG", "isin", "needs_verification", "universe", SourceAuthority.MANUAL),
        ]
    )
    assert result.identity.isin_status == "needs_verification"
    assert result.identity.provider_symbols["yahoo"] == "AURG.OL"
    assert result.identity.warnings


def test_official_claim_wins_but_conflict_is_retained() -> None:
    result = resolve_identity(
        [
            IdentityClaim("X", "isin", "NO0000000001", "vendor", SourceAuthority.VENDOR),
            IdentityClaim("X", "isin", "NO0000000002", "sec", SourceAuthority.OFFICIAL),
            IdentityClaim("X", "ticker", "X", "vendor", SourceAuthority.VENDOR),
        ]
    )
    assert result.identity.isin == "NO0000000002"
    assert len(result.conflicts) == 1
    assert result.conflicts[0].requires_manual_review is True


def test_identity_retains_mic_share_class_listing_and_missing_source_review() -> None:
    result = resolve_identity(
        [
            IdentityClaim("ETF", "ticker", "VWCE", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
            IdentityClaim("ETF", "isin", "IE00BK5BQT80", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
            IdentityClaim("ETF", "exchange", "XETRA", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "mic", "XETR", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "currency", "EUR", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "share_class", "accumulating", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
            IdentityClaim("ETF", "listing", "XETR:VWCE", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "provider_symbol", "VWCE.DE", "yfinance", SourceAuthority.VENDOR, "yfinance:quote"),
        ]
    )
    assert result.identity.mic == "XETR"
    assert result.identity.share_class == "accumulating"
    assert result.identity.listing == "XETR:VWCE"
    assert result.identity.provider_symbols["yfinance"] == "VWCE.DE"
    assert result.identity.confidence == "high"

    missing_source = resolve_identity(
        [IdentityClaim("ETF", "ticker", "VWCE", "manual", SourceAuthority.MANUAL)]
    )
    assert missing_source.identity.confidence == "manual_review"
    assert "missing_source_id" in missing_source.identity.warnings
    assert missing_source.requires_manual_review is True


def test_identity_ticker_and_isin_mismatch_is_fail_closed() -> None:
    result = resolve_identity(
        [
            IdentityClaim("ETF", "ticker", "VWCE", "official", SourceAuthority.OFFICIAL, "sec:identity"),
            IdentityClaim("ETF", "ticker", "VWRL", "vendor", SourceAuthority.VENDOR, "vendor:identity"),
            IdentityClaim("ETF", "isin", "UNKNOWN", "vendor", SourceAuthority.VENDOR, "vendor:identity"),
        ]
    )
    assert result.identity.ticker == "VWCE"
    assert result.identity.isin_status == "needs_verification"
    assert result.identity.confidence == "manual_review"
    assert any("ticker" in warning for warning in result.identity.warnings)
    assert any(conflict.field == "ticker" for conflict in result.conflicts)


def test_manual_override_is_distinct_from_ordinary_local_config_claim() -> None:
    config_claims = [
        IdentityClaim("X", "ticker", "X", "universe", SourceAuthority.MANUAL, "config:X"),
        IdentityClaim("X", "isin", "US0000000000", "universe", SourceAuthority.MANUAL, "config:X"),
        IdentityClaim("X", "exchange", "NYSE", "universe", SourceAuthority.MANUAL, "config:X"),
    ]
    assert resolve_identity(config_claims).identity.confidence == "high"
    override = resolve_identity([IdentityClaim("X", "ticker", "Y", "manual_override", SourceAuthority.MANUAL, "override:X", manual_override=True)])
    assert override.identity.confidence == "manual_review"
    assert "manual_override_requires_review" in override.identity.warnings


def test_unknown_or_missing_exchange_requires_manual_review() -> None:
    common_claims = [
        IdentityClaim("ETF", "ticker", "VWCE", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
        IdentityClaim("ETF", "isin", "IE00BK5BQT80", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
    ]

    unknown = resolve_identity(common_claims + [IdentityClaim("ETF", "exchange", "unknown", "vendor", SourceAuthority.VENDOR, "vendor:listing")])
    missing = resolve_identity(common_claims)

    for result in (unknown, missing):
        assert "exchange_needs_verification" in result.identity.warnings
        assert result.identity.confidence == "manual_review"
        assert result.requires_manual_review is True


def test_point_in_time_identity_replays_history_without_future_knowledge() -> None:
    claims = [
        IdentityClaim(
            "SEC-1",
            "ticker",
            "OLD",
            "exchange",
            SourceAuthority.OFFICIAL,
            "mic:XNAS:SEC-1",
            object_type="listing",
            object_id="LISTING-XNAS",
            parent_object_id="SEC-1",
            relationship="quotation_for",
            valid_from="2020-01-01T00:00:00Z",
            valid_to="2024-06-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
            revision=1,
            event_type="listing_created",
        ),
        IdentityClaim(
            "SEC-1",
            "ticker",
            "NEW",
            "exchange",
            SourceAuthority.OFFICIAL,
            "mic:XNAS:SEC-1",
            object_type="listing",
            object_id="LISTING-XNAS",
            parent_object_id="SEC-1",
            relationship="quotation_for",
            valid_from="2024-06-01T00:00:00Z",
            available_at="2024-06-02T00:00:00Z",
            revision=2,
            event_type="ticker_changed",
        ),
    ]

    old = resolve_identity(
        claims,
        effective_at="2024-05-01T00:00:00Z",
        decision_time="2024-05-01T00:00:00Z",
    )
    new = resolve_identity(
        claims,
        effective_at="2024-07-01T00:00:00Z",
        decision_time="2024-07-01T00:00:00Z",
    )

    assert old.objects[0].fields["ticker"] == "OLD"
    assert new.objects[0].fields["ticker"] == "NEW"
    assert [entry.value for entry in old.history] == ["OLD"]
    assert [entry.value for entry in new.history] == ["OLD", "NEW"]
    assert [claim.value for claim in old.excluded_claims] == ["NEW"]
    assert old.decision_id != new.decision_id
    assert new.execution_allowed is False


def test_multiple_listings_remain_distinct_objects_in_one_identity_graph() -> None:
    common = {
        "valid_from": "2020-01-01T00:00:00Z",
        "available_at": "2020-01-02T00:00:00Z",
    }
    result = resolve_identity(
        [
            IdentityClaim(
                "SEC-1",
                "ticker",
                "ABC",
                "exchange",
                SourceAuthority.OFFICIAL,
                "mic:XNAS:SEC-1",
                object_type="listing",
                object_id="LISTING-XNAS",
                parent_object_id="SEC-1",
                relationship="quotation_for",
                **common,
            ),
            IdentityClaim(
                "SEC-1",
                "ticker",
                "ABC1",
                "exchange",
                SourceAuthority.OFFICIAL,
                "mic:XLON:SEC-1",
                object_type="listing",
                object_id="LISTING-XLON",
                parent_object_id="SEC-1",
                relationship="quotation_for",
                **common,
            ),
        ],
        effective_at="2025-01-01T00:00:00Z",
        decision_time="2025-01-01T00:00:00Z",
    )

    assert {(item.object_id, item.fields["ticker"]) for item in result.objects} == {
        ("LISTING-XLON", "ABC1"),
        ("LISTING-XNAS", "ABC"),
    }
    assert not result.conflicts
    assert result.resolution_state == "manual_review"


def test_point_in_time_identity_rejects_ambiguous_availability() -> None:
    with pytest.raises(AmbiguousIdentityAvailabilityError, match="available_at"):
        resolve_identity(
            [
                IdentityClaim(
                    "SEC-1",
                    "isin",
                    "US0000000001",
                    "official",
                    SourceAuthority.OFFICIAL,
                    "official:SEC-1",
                    valid_from="2020-01-01T00:00:00Z",
                )
            ],
            effective_at="2025-01-01T00:00:00Z",
            decision_time="2025-01-01T00:00:00Z",
        )


def test_identity_review_selects_only_a_retained_candidate_and_preserves_lineage() -> None:
    claims = [
        IdentityClaim("SEC-1", "isin", "US0000000001", "vendor", SourceAuthority.VENDOR, "vendor:1"),
        IdentityClaim("SEC-1", "isin", "US0000000002", "official", SourceAuthority.OFFICIAL, "official:1"),
        IdentityClaim("SEC-1", "ticker", "ABC", "official", SourceAuthority.OFFICIAL, "official:1"),
        IdentityClaim("SEC-1", "exchange", "XNAS", "official", SourceAuthority.OFFICIAL, "official:1"),
    ]
    initial = resolve_identity(claims)
    conflict_id = initial.conflicts[0].conflict_id
    reviewed = resolve_identity(
        claims,
        review_decisions=(
            IdentityReviewDecision(conflict_id, "vendor:1", "reviewer-1", "2026-07-21T00:00:00Z", "Verified corporate event"),
        ),
    )

    assert reviewed.identity.isin == "US0000000001"
    assert reviewed.conflicts[0].resolution_status == "reviewed"
    assert reviewed.conflicts[0].review_decision_id
    assert reviewed.conflicts[0].requires_manual_review is False
    assert reviewed.decision_id != initial.decision_id
    assert len(reviewed.claims) == len(claims)
    assert reviewed.execution_allowed is False
    with pytest.raises(ValueError, match="candidate"):
        resolve_identity(
            claims,
            review_decisions=(
                IdentityReviewDecision(conflict_id, "missing", "reviewer-1", "2026-07-21T00:00:00Z", "Invalid"),
            ),
        )


def test_future_identity_review_cannot_change_a_historical_decision() -> None:
    common = {
        "valid_from": "2024-01-01T00:00:00Z",
        "available_at": "2024-01-02T00:00:00Z",
    }
    claims = [
        IdentityClaim("SEC-1", "ticker", "AAA", "official", SourceAuthority.OFFICIAL, "official:1", **common),
        IdentityClaim("SEC-1", "ticker", "BBB", "vendor", SourceAuthority.VENDOR, "vendor:1", **common),
    ]
    initial = resolve_identity(
        claims,
        effective_at="2024-06-01T00:00:00Z",
        decision_time="2024-06-01T00:00:00Z",
    )
    reviewed = resolve_identity(
        claims,
        effective_at="2024-06-01T00:00:00Z",
        decision_time="2024-06-01T00:00:00Z",
        review_decisions=(
            IdentityReviewDecision(
                initial.conflicts[0].conflict_id,
                "vendor:1",
                "reviewer-1",
                "2026-07-21T00:00:00Z",
                "Later evidence",
            ),
        ),
    )

    assert reviewed.identity.ticker == "AAA"
    assert reviewed.conflicts[0].resolution_status == "manual_review"
    assert reviewed.conflicts[0].review_decision_id == ""
    assert reviewed.decision_id == initial.decision_id


def test_conflicting_identity_reviews_with_the_same_revision_fail_closed_in_any_order() -> None:
    claims = [
        IdentityClaim("SEC-1", "ticker", "AAA", "official", SourceAuthority.OFFICIAL, "official:1"),
        IdentityClaim("SEC-1", "ticker", "BBB", "vendor", SourceAuthority.VENDOR, "vendor:1"),
    ]
    conflict_id = resolve_identity(claims).conflicts[0].conflict_id
    decisions = (
        IdentityReviewDecision(conflict_id, "official:1", "reviewer-1", "2026-07-21T00:00:00Z", "Decision A"),
        IdentityReviewDecision(conflict_id, "vendor:1", "reviewer-2", "2026-07-21T00:00:00Z", "Decision B"),
    )

    for ordered in (decisions, tuple(reversed(decisions))):
        with pytest.raises(ValueError, match="same revision"):
            resolve_identity(claims, review_decisions=ordered)
