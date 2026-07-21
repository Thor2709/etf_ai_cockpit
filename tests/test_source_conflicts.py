from __future__ import annotations

from etf_cockpit.data.contracts import SourceAuthority
import pytest
import pandas as pd

from etf_cockpit.data.source_conflicts import (
    AmbiguousMetricAvailabilityError,
    MetricClaim,
    MetricPolicy,
    MetricReviewDecision,
    resolve_conflicts,
)
from etf_cockpit.data import trust_artifacts


def test_material_conflict_is_visible_and_not_silently_overwritten() -> None:
    result = resolve_conflicts(
        [
            MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "v1"),
            MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "o1"),
        ]
    )
    assert result.selected["revenue"].value == 120
    assert result.conflicts[0].requires_manual_review is True
    assert result.conflicts[0].source_ids == ("o1", "v1")


def test_conflict_resolution_has_deterministic_manual_review_reason() -> None:
    claims = [
        MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "v1", unit="USD", period="FY2025", as_of="2026-02-01"),
        MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "o1", unit="USD", period="FY2025", as_of="2026-02-01"),
    ]
    first = resolve_conflicts(claims)
    second = resolve_conflicts(reversed(claims))
    assert first == second
    conflict = first.conflicts[0]
    assert conflict.resolution_status == "manual_review"
    assert "official" in conflict.reason.lower()
    assert "vendor" in conflict.reason.lower()
    assert conflict.conflict_id
    assert first.claims == second.claims


def test_metric_contexts_are_never_pooled_across_period_unit_or_currency() -> None:
    claims = [
        MetricClaim(
            "X",
            "revenue",
            100,
            "official",
            SourceAuthority.OFFICIAL,
            "official:x",
            unit="millions",
            period="FY2024",
            currency="USD",
            as_of="2024-12-31T00:00:00Z",
            available_at="2025-02-01T00:00:00Z",
            revision=1,
        ),
        MetricClaim(
            "X",
            "revenue",
            92,
            "official",
            SourceAuthority.OFFICIAL,
            "official:x",
            unit="millions",
            period="FY2024",
            currency="EUR",
            as_of="2024-12-31T00:00:00Z",
            available_at="2025-02-01T00:00:00Z",
            revision=1,
        ),
        MetricClaim(
            "X",
            "revenue",
            25,
            "official",
            SourceAuthority.OFFICIAL,
            "official:x",
            unit="millions",
            period="Q1-2025",
            currency="USD",
            as_of="2025-03-31T00:00:00Z",
            available_at="2025-05-01T00:00:00Z",
            revision=1,
        ),
    ]

    result = resolve_conflicts(claims, decision_time="2025-06-01T00:00:00Z")

    assert len(result.selected) == 3
    assert result.state == "block"
    assert {item.reason_code for item in result.conflicts} == {"incompatible_metric_context"}
    assert all(item.requires_manual_review for item in result.conflicts)
    assert result.execution_allowed is False


def test_tolerance_policy_distinguishes_warn_from_material_quarantine() -> None:
    policy = MetricPolicy("fundamentals.v1", version=1, absolute_tolerance=1.0, relative_tolerance=0.01)
    common = {
        "unit": "millions",
        "period": "FY2025",
        "currency": "USD",
        "as_of": "2025-12-31T00:00:00Z",
        "available_at": "2026-02-01T00:00:00Z",
    }
    within = resolve_conflicts(
        [
            MetricClaim("X", "revenue", 100.0, "official", SourceAuthority.OFFICIAL, "o1", **common),
            MetricClaim("X", "revenue", 100.5, "vendor", SourceAuthority.VENDOR, "v1", **common),
        ],
        decision_time="2026-03-01T00:00:00Z",
        policy=policy,
    )
    material = resolve_conflicts(
        [
            MetricClaim("X", "revenue", 100.0, "official", SourceAuthority.OFFICIAL, "o1", **common),
            MetricClaim("X", "revenue", 105.0, "vendor", SourceAuthority.VENDOR, "v1", **common),
        ],
        decision_time="2026-03-01T00:00:00Z",
        policy=policy,
    )

    assert within.state == "warn"
    assert within.conflicts[0].reason_code == "within_materiality_tolerance"
    assert within.conflicts[0].requires_manual_review is False
    assert material.state == "quarantine"
    assert material.conflicts[0].reason_code == "material_value_conflict"
    assert material.conflicts[0].requires_manual_review is True
    assert within.policy_id == material.policy_id == "fundamentals.v1:1"


def test_future_restatement_is_excluded_and_changes_invalidation_identity_when_known() -> None:
    claims = [
        MetricClaim(
            "X",
            "revenue",
            100,
            "official",
            SourceAuthority.OFFICIAL,
            "official:x",
            unit="USD",
            period="FY2025",
            currency="USD",
            restatement_id="original",
            as_of="2025-12-31T00:00:00Z",
            available_at="2026-02-01T00:00:00Z",
            revision=1,
        ),
        MetricClaim(
            "X",
            "revenue",
            110,
            "official",
            SourceAuthority.OFFICIAL,
            "official:x",
            unit="USD",
            period="FY2025",
            currency="USD",
            restatement_id="restated-1",
            as_of="2025-12-31T00:00:00Z",
            available_at="2026-06-01T00:00:00Z",
            revision=2,
        ),
    ]
    before = resolve_conflicts(claims, decision_time="2026-03-01T00:00:00Z")
    after = resolve_conflicts(claims, decision_time="2026-07-01T00:00:00Z")

    assert next(iter(before.selected.values())).value == 100
    assert next(iter(after.selected.values())).value == 110
    assert len(before.excluded_claims) == 1
    assert before.invalidation_token != after.invalidation_token


def test_review_decision_is_audited_and_cannot_select_an_unknown_candidate() -> None:
    claims = [
        MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "v1"),
        MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "o1"),
    ]
    initial = resolve_conflicts(claims)
    conflict_id = initial.conflicts[0].conflict_id
    reviewed = resolve_conflicts(
        claims,
        review_decisions=(
            MetricReviewDecision(conflict_id, "v1", "reviewer-1", "2026-07-21T00:00:00Z", "Audited restatement"),
        ),
    )

    assert reviewed.selected["revenue"].source_id == "v1"
    assert reviewed.conflicts[0].resolution_status == "reviewed"
    assert reviewed.conflicts[0].review_decision_id
    assert reviewed.conflicts[0].requires_manual_review is False
    assert len(reviewed.claims) == 2
    with pytest.raises(ValueError, match="candidate"):
        resolve_conflicts(
            claims,
            review_decisions=(
                MetricReviewDecision(conflict_id, "missing", "reviewer-1", "2026-07-21T00:00:00Z", "Invalid"),
            ),
        )


def test_future_metric_review_cannot_change_a_historical_decision() -> None:
    common = {
        "unit": "USD",
        "period": "FY2025",
        "currency": "USD",
        "as_of": "2025-12-31T00:00:00Z",
        "available_at": "2026-02-01T00:00:00Z",
    }
    claims = [
        MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "official:x", **common),
        MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "vendor:x", **common),
    ]
    initial = resolve_conflicts(claims, decision_time="2026-03-01T00:00:00Z")
    reviewed = resolve_conflicts(
        claims,
        decision_time="2026-03-01T00:00:00Z",
        review_decisions=(
            MetricReviewDecision(
                initial.conflicts[0].conflict_id,
                "vendor:x",
                "reviewer-1",
                "2026-07-21T00:00:00Z",
                "Later evidence",
            ),
        ),
    )

    assert reviewed.selected["revenue"].source_id == "official:x"
    assert reviewed.conflicts[0].resolution_status == "manual_review"
    assert reviewed.conflicts[0].review_decision_id == ""
    assert reviewed.decision_id == initial.decision_id


def test_review_cannot_promote_a_quality_ineligible_retained_candidate() -> None:
    policy = MetricPolicy("quality.v1", version=1, blocked_freshness_statuses=("stale",))
    common = {
        "unit": "USD",
        "period": "FY2025",
        "currency": "USD",
        "as_of": "2025-12-31T00:00:00Z",
        "available_at": "2026-02-01T00:00:00Z",
    }
    claims = [
        MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "official:x", freshness_status="ok", **common),
        MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "vendor:x", freshness_status="ok", **common),
        MetricClaim("X", "revenue", 999, "community", SourceAuthority.COMMUNITY, "stale:x", freshness_status="stale", **common),
    ]
    initial = resolve_conflicts(claims, decision_time="2026-03-01T00:00:00Z", policy=policy)

    with pytest.raises(ValueError, match="quality"):
        resolve_conflicts(
            claims,
            decision_time="2026-03-01T00:00:00Z",
            policy=policy,
            review_decisions=(
                MetricReviewDecision(
                    initial.conflicts[0].conflict_id,
                    "stale:x",
                    "reviewer-1",
                    "2026-02-15T00:00:00Z",
                    "Invalid stale promotion",
                ),
            ),
        )


def test_point_in_time_metric_without_valid_or_as_of_context_is_blocked() -> None:
    result = resolve_conflicts(
        [
            MetricClaim(
                "X",
                "revenue",
                100,
                "official",
                SourceAuthority.OFFICIAL,
                "official:x",
                unit="USD",
                period="FY2025",
                currency="USD",
                available_at="2026-02-01T00:00:00Z",
            )
        ],
        decision_time="2026-03-01T00:00:00Z",
    )

    assert not result.selected
    assert result.state == "block"
    assert result.conflicts[0].reason_code == "missing_metric_context"


def test_as_of_and_validity_contexts_are_retained_and_never_pooled() -> None:
    claims = [
        MetricClaim(
            "X", "revenue", 100, "official", SourceAuthority.OFFICIAL, "official:2024",
            unit="USD", period="FY2025", currency="USD", as_of="2025-12-31T00:00:00Z",
            valid_from="2025-12-31T00:00:00Z", available_at="2026-02-01T00:00:00Z",
        ),
        MetricClaim(
            "X", "revenue", 110, "vendor", SourceAuthority.VENDOR, "vendor:2025",
            unit="USD", period="FY2025", currency="USD", as_of="2026-01-31T00:00:00Z",
            valid_from="2026-01-31T00:00:00Z", available_at="2026-02-02T00:00:00Z",
        ),
    ]

    result = resolve_conflicts(claims, decision_time="2026-03-01T00:00:00Z")

    assert result.state == "block"
    assert any(item.reason_code == "incompatible_metric_context" for item in result.conflicts)
    assert {item.as_of for item in result.conflicts if item.reason_code != "incompatible_metric_context"} == set()


def test_conflicting_metric_reviews_with_the_same_revision_fail_closed_in_any_order() -> None:
    claims = [
        MetricClaim("X", "revenue", 110, "official", SourceAuthority.OFFICIAL, "official:x"),
        MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "vendor:x"),
    ]
    conflict_id = resolve_conflicts(claims).conflicts[0].conflict_id
    decisions = (
        MetricReviewDecision(conflict_id, "official:x", "reviewer-1", "2026-07-21T00:00:00Z", "Decision A"),
        MetricReviewDecision(conflict_id, "vendor:x", "reviewer-2", "2026-07-21T00:00:00Z", "Decision B"),
    )

    for ordered in (decisions, tuple(reversed(decisions))):
        with pytest.raises(ValueError, match="same revision"):
            resolve_conflicts(claims, review_decisions=ordered)


def test_conflict_audit_candidate_count_counts_claims_not_unique_sources(tmp_path, monkeypatch) -> None:
    claims = [
        MetricClaim(
            "X", "revenue", 100, "official", SourceAuthority.OFFICIAL, "official:x",
            unit="USD", period="FY2024", currency="USD", as_of="2024-12-31T00:00:00Z",
        ),
        MetricClaim(
            "X", "revenue", 110, "official", SourceAuthority.OFFICIAL, "official:x",
            unit="USD", period="FY2025", currency="USD", as_of="2025-12-31T00:00:00Z",
        ),
    ]
    result = resolve_conflicts(claims)
    output = tmp_path / "source_conflicts.parquet"
    monkeypatch.setattr(trust_artifacts, "SOURCE_CONFLICTS_PATH", output)

    trust_artifacts.write_source_conflicts(result)
    frame = pd.read_parquet(output)
    incompatible = frame.loc[frame["reason_code"].eq("incompatible_metric_context")].iloc[0]

    assert incompatible["candidate_count"] == 2


def test_point_in_time_metric_resolution_rejects_ambiguous_availability() -> None:
    with pytest.raises(AmbiguousMetricAvailabilityError, match="available_at"):
        resolve_conflicts(
            [MetricClaim("X", "revenue", 100, "official", SourceAuthority.OFFICIAL, "o1")],
            decision_time="2026-03-01T00:00:00Z",
        )


def test_freshness_and_confidence_policy_prevents_stale_authority_from_winning() -> None:
    policy = MetricPolicy(
        "quality.v1",
        version=1,
        minimum_confidence=0.7,
        blocked_freshness_statuses=("stale", "block"),
    )
    common = {
        "unit": "USD",
        "period": "FY2025",
        "currency": "USD",
        "as_of": "2025-12-31T00:00:00Z",
        "available_at": "2026-02-01T00:00:00Z",
    }
    result = resolve_conflicts(
        [
            MetricClaim(
                "X",
                "revenue",
                120,
                "official",
                SourceAuthority.OFFICIAL,
                "official:x",
                freshness_status="stale",
                confidence=0.99,
                **common,
            ),
            MetricClaim(
                "X",
                "revenue",
                100,
                "vendor",
                SourceAuthority.VENDOR,
                "vendor:x",
                freshness_status="ok",
                confidence=0.9,
                **common,
            ),
        ],
        decision_time="2026-03-01T00:00:00Z",
        policy=policy,
    )

    assert result.selected["revenue"].source_id == "vendor:x"
    assert result.state == "warn"
    assert result.conflicts[0].reason_code == "candidate_quality_reduced"
    assert result.conflicts[0].requires_manual_review is False
    assert result.policy_sha256 == policy.sha256


def test_all_quality_ineligible_candidates_block_canonical_use() -> None:
    policy = MetricPolicy("quality.v1", version=1, minimum_confidence=0.8)
    result = resolve_conflicts(
        [
            MetricClaim(
                "X",
                "revenue",
                100,
                "official",
                SourceAuthority.OFFICIAL,
                "official:x",
                unit="USD",
                period="FY2025",
                currency="USD",
                as_of="2025-12-31T00:00:00Z",
                available_at="2026-02-01T00:00:00Z",
                freshness_status="ok",
                confidence=0.4,
            )
        ],
        decision_time="2026-03-01T00:00:00Z",
        policy=policy,
    )

    assert result.state == "block"
    assert result.conflicts[0].reason_code == "no_quality_eligible_candidate"
    assert result.execution_allowed is False


def test_model_only_claim_cannot_become_a_canonical_fact() -> None:
    result = resolve_conflicts(
        [
            MetricClaim(
                "X",
                "revenue",
                100,
                "model",
                SourceAuthority.MODEL,
                "model:x",
                unit="USD",
                period="FY2025",
                currency="USD",
            )
        ]
    )

    assert not result.selected
    assert result.state == "block"
    assert result.conflicts[0].reason_code == "no_quality_eligible_candidate"
    assert result.execution_allowed is False


def test_conflict_audit_projection_preserves_context_policy_and_no_execution(tmp_path, monkeypatch) -> None:
    policy = MetricPolicy("fundamentals.v1", version=2, absolute_tolerance=0.5)
    result = resolve_conflicts(
        [
            MetricClaim(
                "X",
                "revenue",
                100,
                "official",
                SourceAuthority.OFFICIAL,
                "official:x",
                unit="millions",
                period="FY2025",
                currency="USD",
                as_of="2025-12-31T00:00:00Z",
            ),
            MetricClaim(
                "X",
                "revenue",
                110,
                "vendor",
                SourceAuthority.VENDOR,
                "vendor:x",
                unit="millions",
                period="FY2025",
                currency="USD",
                as_of="2025-12-31T00:00:00Z",
            ),
        ],
        policy=policy,
    )
    output = tmp_path / "source_conflicts.parquet"
    monkeypatch.setattr(trust_artifacts, "SOURCE_CONFLICTS_PATH", output)

    trust_artifacts.write_source_conflicts(result)
    frame = pd.read_parquet(output)

    assert frame.loc[0, "period"] == "FY2025"
    assert frame.loc[0, "unit"] == "millions"
    assert frame.loc[0, "currency"] == "USD"
    assert frame.loc[0, "as_of"] == "2025-12-31T00:00:00Z"
    assert frame.loc[0, "policy_id"] == "fundamentals.v1:2"
    assert frame.loc[0, "policy_sha256"] == policy.sha256
    assert frame.loc[0, "reason_code"] == "material_value_conflict"
    assert bool(frame.loc[0, "execution_allowed"]) is False
