from dataclasses import replace

from etf_cockpit.analysis.decision.contracts import OpportunityResult
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio.risk_profiles import VWCEAnchorSnapshot
from etf_cockpit.portfolio.selection_slices import materialise_selection_slices
from etf_cockpit.portfolio.top_n_selection import (
    SelectionCandidate,
    build_selection_run,
    load_selection_policy,
    persist_selection_run,
)


DECISION_TIME = "2026-09-30T20:00:00+00:00"


def _candidate(
    instrument: str,
    family: str,
    *,
    raw_score: float = 1.0,
    peer_rank: int = 1,
    common: tuple[float, float, float, float, float, float] = (0.5, 0.2, 0.5, 0.5, 0.2, 0.8),
    country: str = "DE",
    sector: str = "Industrials",
    hard_gate_reasons: tuple[str, ...] = (),
    opportunity_status: str = "Available",
    opportunity_reason: str = "AVAILABLE",
) -> SelectionCandidate:
    opportunity = OpportunityResult(
        instrument=instrument,
        asset_type=family,
        decision_time=DECISION_TIME,
        status=opportunity_status,
        baseline_z=raw_score,
        percentile=0.5,
        universe_rank=peer_rank,
        universe_support=20,
        peer_percentile=0.5,
        peer_rank=peer_rank,
        peer_support=8,
        domain_scores=(("quality", raw_score),),
        confidence=common[5],
        coverage=0.9,
        positive_drivers=(),
        negative_drivers=(),
        explanation="synthetic opportunity result",
        timing="Neutral",
        timing_reason_code="MOMENTUM_PERCENTILE_NEUTRAL",
        benchmark_rankers=(),
        universe_hash="synthetic-universe",
        peer_id=f"synthetic-{family}-peers",
        config_hash="synthetic-opportunity-policy",
        source_vintage_hash="synthetic-source-vintage",
        reason_code=opportunity_reason,
    )
    return SelectionCandidate(
        opportunity=opportunity,
        common_metrics_as_of=DECISION_TIME,
        country=country,
        sector=sector,
        net_expected_return=common[0],
        downside_risk=common[1],
        marginal_impact=common[2],
        liquidity=common[3],
        cost=common[4],
        evidence=common[5],
        hard_gate_reasons=hard_gate_reasons,
    )


def _policy(*, top_n: int = 1, support: int = 2, bootstrap_count: int = 30):
    return replace(
        load_selection_policy(),
        top_n=top_n,
        minimum_raw_support=support,
        minimum_effective_support=float(support),
        bootstrap_count=bootstrap_count,
    )


def test_cross_asset_utility_never_pools_raw_scores_and_asset_lists_keep_peer_ranks() -> None:
    stock_best_common = _candidate(
        "stock-a", "stock", raw_score=900.0, peer_rank=2,
        common=(0.1, 0.8, 0.1, 0.1, 0.8, 0.2),
    )
    stock_other_peer = _candidate("stock-b", "stock", raw_score=5.0, peer_rank=1)
    bond = _candidate(
        "bond-a", "bond", raw_score=-900.0, peer_rank=1,
        common=(0.9, 0.1, 0.9, 0.9, 0.1, 0.9),
    )
    run = build_selection_run(
        (stock_best_common, stock_other_peer, bond),
        decision_time=DECISION_TIME,
        policy=_policy(),
        portfolio_snapshot={"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-1", "as_of": DECISION_TIME},
    )

    assert run.selected_ids == ("bond-a",)
    assert dict(run.asset_specific_lists)["stock"] == ("stock-b", "stock-a")
    rows = {row["instrument_id"]: row for row in run.candidate_table}
    assert rows["stock-a"]["peer_rank"] == 2
    assert rows["bond-a"]["peer_rank"] == 1
    assert rows["bond-a"]["utility_score"] > rows["stock-a"]["utility_score"]


def test_hard_gate_failure_is_excluded_with_reason_in_funnel() -> None:
    candidates = (
        _candidate(
            "blocked-stock", "stock",
            opportunity_status="Blocked",
            opportunity_reason="eligibility:blocked",
        ),
        _candidate("eligible-bond", "bond", common=(0.9, 0.1, 0.9, 0.9, 0.1, 0.9)),
    )
    run = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=_policy(),
        portfolio_snapshot={"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-1", "as_of": DECISION_TIME},
    )

    assert "blocked-stock" not in run.selected_ids
    assert dict(run.exclusion_funnel)["hard_gate_failed:eligibility:blocked"] == 1
    blocked = next(row for row in run.candidate_table if row["instrument_id"] == "blocked-stock")
    assert blocked["why_not"] == ("hard_gate_failed:eligibility:blocked",)


def test_frozen_inputs_and_seed_reproduce_run_and_other_seeds_only_change_bootstrap_fields() -> None:
    candidates = tuple(
        _candidate(
            f"asset-{index}", "etf",
            common=(0.1 + 0.13 * index, 0.85 - 0.12 * index, 0.2 + 0.11 * index,
                    0.15 + 0.14 * index, 0.9 - 0.1 * index, 0.2 + 0.1 * index),
        )
        for index in range(5)
    )
    common = {
        "decision_time": DECISION_TIME,
        "policy": _policy(support=5, bootstrap_count=45),
        "portfolio_snapshot": {"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-1", "as_of": DECISION_TIME},
    }
    first = build_selection_run(candidates, seed=17, **common)
    repeated = build_selection_run(candidates, seed=17, **common)
    changed_seed = build_selection_run(candidates, seed=71, **common)

    assert first.to_record() == repeated.to_record()
    assert first.selected_ids == changed_seed.selected_ids
    assert first.input_hash == changed_seed.input_hash
    excluded_bootstrap = {"selection_probability", "rank_stability", "rank_interval"}
    rows_a = {row["instrument_id"]: row for row in first.candidate_table}
    rows_b = {row["instrument_id"]: row for row in changed_seed.candidate_table}
    for instrument in rows_a:
        assert {key: value for key, value in rows_a[instrument].items() if key not in excluded_bootstrap} == {
            key: value for key, value in rows_b[instrument].items() if key not in excluded_bootstrap
        }
    assert any(
        rows_a[instrument][field] != rows_b[instrument][field]
        for instrument in rows_a
        for field in excluded_bootstrap
    )


def test_portfolio_change_creates_new_run_identity_without_mutating_earlier_run(tmp_path) -> None:
    candidates = (_candidate("asset-a", "etf"), _candidate("asset-b", "bond", common=(0.8, 0.2, 0.8, 0.7, 0.1, 0.8)))
    policy = _policy()
    original_portfolio = {"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-1", "as_of": DECISION_TIME}
    changed_portfolio = {"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-2", "as_of": DECISION_TIME}
    earlier = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=policy,
        portfolio_snapshot=original_portfolio,
    )
    frozen_record = earlier.to_record()
    later = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=policy,
        portfolio_snapshot=changed_portfolio,
    )

    assert earlier.run_id != later.run_id
    assert earlier.input_hash != later.input_hash
    assert earlier.to_record() == frozen_record
    with TransactionalStore(tmp_path) as store:
        first_record = persist_selection_run(store, earlier)
        second_record = persist_selection_run(store, later)
        stored_runs = store.list("top_n_selection_run.v1")
    assert first_record.payload == frozen_record
    assert second_record.payload == later.to_record()
    assert len(stored_runs) == 2
    assert next(item for item in stored_runs if item.entity_id == earlier.run_id).payload == frozen_record


def test_missing_portfolio_uses_vwce_anchor_or_returns_unavailable_reason() -> None:
    anchor = VWCEAnchorSnapshot(
        status="available",
        reason=None,
        canonical_share_class_id="synthetic-vwce-anchor",
        listing_id="synthetic-anchor-listing",
        effective_date="2026-09-30",
        knowledge_cutoff=DECISION_TIME,
        output_currency="EUR",
        horizon_years=10.0,
        anchor_digest="anchor-digest",
        resolution_digest="resolution-digest",
        risk_envelope_status="unavailable",
        risk_metrics=(("expected_shortfall", "unavailable"),),
    )
    candidates = (_candidate("asset-a", "stock"), _candidate("asset-b", "bond", common=(0.8, 0.2, 0.8, 0.7, 0.1, 0.8)))
    available = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=_policy(),
        reference_anchor=anchor,
    )
    unavailable = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=_policy(),
        reference_anchor=None,
    )

    assert available.mode == "cross_asset"
    assert available.portfolio_reference["kind"] == "vwce_benchmark_hierarchy_reference"
    assert available.portfolio_reference["instrument_id"] == "synthetic-vwce-anchor"
    assert unavailable.mode == "unavailable"
    assert unavailable.reason == "reference_portfolio_unavailable"


def test_slices_conserve_table_sparse_country_sector_is_insufficient_and_scores_are_frozen() -> None:
    candidates = tuple(
        _candidate(
            f"asset-{index}",
            "etf",
            common=(0.2 + index * 0.1, 0.8 - index * 0.1, 0.1 + index * 0.12,
                    0.2 + index * 0.1, 0.8 - index * 0.1, 0.3 + index * 0.1),
            country="DE" if index < 5 else "FR",
            sector="Industrials" if index < 5 else "Energy",
        )
        for index in range(6)
    )
    run = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=_policy(support=5, bootstrap_count=20),
        portfolio_snapshot={"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-1", "as_of": DECISION_TIME},
    )
    original_scores = {row["instrument_id"]: row["utility_score"] for row in run.candidate_table}
    slices = materialise_selection_slices(run)
    sparse = next(
        item for item in slices
        if item["dimension"] == "country_sector" and item["value"] == ("FR", "Energy")
    )
    for item in slices:
        members = set(item["candidate_ids"])
        excluded = set(item["excluded_from_slice_ids"])
        assert members.isdisjoint(excluded)
        assert members | excluded == set(original_scores)
        assert item["candidate_table_count"] == len(original_scores)
        for row in item["rows"]:
            assert row["utility_score"] == original_scores[row["instrument_id"]]
    assert sparse["status"] == "insufficient_support"
    assert sparse["selected_ids"] == ()
