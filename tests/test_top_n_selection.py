from dataclasses import asdict, replace
from types import SimpleNamespace

from etf_cockpit.analysis.decision.contracts import OpportunityResult
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.application.ui_facade import load_top_n_selection
from etf_cockpit.portfolio.risk_profiles import VWCEAnchorSnapshot
from etf_cockpit.portfolio.selection_slices import materialise_selection_slices
from etf_cockpit.portfolio.top_n_selection import (
    SelectionCandidate,
    build_selection_run,
    load_selection_policy,
    persist_selection_run,
)
from etf_cockpit.portfolio.goals_constraints import validate_portfolio_policy


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
    constraints_a = validate_portfolio_policy(
        {"max_position_weight": 0.2}, policy_id="portfolio-goals:test", version=1
    )
    constraints_b = validate_portfolio_policy(
        {"max_position_weight": 0.3}, policy_id="portfolio-goals:test", version=1
    )
    earlier = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=policy,
        portfolio_snapshot=original_portfolio,
        portfolio_policy=constraints_a,
    )
    frozen_record = earlier.to_record()
    changed_constraints = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=policy,
        portfolio_snapshot=original_portfolio,
        portfolio_policy=constraints_b,
    )
    changed_portfolio_run = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=policy,
        portfolio_snapshot=changed_portfolio,
        portfolio_policy=constraints_a,
    )

    assert len({earlier.run_id, changed_constraints.run_id, changed_portfolio_run.run_id}) == 3
    assert len({earlier.input_hash, changed_constraints.input_hash, changed_portfolio_run.input_hash}) == 3
    assert earlier.to_record() == frozen_record
    with TransactionalStore(tmp_path) as store:
        first_record = persist_selection_run(store, earlier)
        second_record = persist_selection_run(store, changed_constraints)
        third_record = persist_selection_run(store, changed_portfolio_run)
        stored_runs = store.list("top_n_selection_run.v1")
    assert first_record.payload == frozen_record
    assert second_record.payload == changed_constraints.to_record()
    assert third_record.payload == changed_portfolio_run.to_record()
    assert len(stored_runs) == 3
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
        reference_anchor=replace(anchor, risk_envelope_status="available"),
    )
    unavailable_envelope = build_selection_run(
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
    assert len(available.selected_ids) == 1
    assert all(row["utility_score"] is not None for row in available.candidate_table)
    assert unavailable_envelope.mode == "cross_asset"
    assert unavailable_envelope.reason == "vwce_reference_risk_envelope_unavailable"
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


def test_country_sector_slice_with_missing_classification_is_unavailable() -> None:
    candidates = tuple(
        _candidate(
            f"unclassified-{index}",
            "etf",
            country=None,
            sector=None,
        )
        for index in range(5)
    )
    run = build_selection_run(
        candidates,
        decision_time=DECISION_TIME,
        policy=_policy(support=5),
        portfolio_snapshot={"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-1", "as_of": DECISION_TIME},
    )

    missing_slice = next(
        item for item in materialise_selection_slices(run)
        if item["dimension"] == "country_sector"
        and item["value"] == ("unavailable", "unavailable")
    )
    assert missing_slice["status"] == "unavailable"
    assert missing_slice["reason"] == "slice_classification_unavailable"
    assert missing_slice["selected_ids"] == ()


def test_loader_builds_persists_frozen_evidence_and_rejects_stale_context_reuse(tmp_path, monkeypatch) -> None:
    import etf_cockpit.application.bulk_run as bulk_run
    import etf_cockpit.application.selection_views as selection_views

    instrument_ids = tuple(f"asset-{index}" for index in range(5))
    opportunities = {
        instrument_id: _candidate(
            instrument_id,
            "bond" if instrument_id == "asset-4" else "etf",
        ).opportunity
        for instrument_id in instrument_ids
    }
    bulk_results = {
        instrument_id: {
            "decision_time": DECISION_TIME,
            "marginal_impact": 0.5,
            "liquidity": 0.5,
            "cost": 0.2,
            **({} if instrument_id == "asset-4" else {
                "net_expected_return": 0.5,
                "downside_risk": 0.2,
            }),
        }
        for instrument_id in instrument_ids
    }
    fixed_screen = {
        "status": "available",
        "decision_time": DECISION_TIME,
        "analysis_snapshot_id": "fixed-screen-snapshot",
        "rows": [{
            "instrument_id": "asset-4",
            "net_total_return": 0.7,
            "loss_probability": 0.1,
            "country": "DE",
            "issuer_sector": "Industrials",
        }],
    }

    class FakeBulkService:
        workflow_type = "bulk_analysis"

        def __init__(self, _root):
            self.scheduler = SimpleNamespace(
                list_workflows=lambda limit: (SimpleNamespace(
                    workflow_type="bulk_analysis",
                    workflow_id="bulk-run-1",
                    created_at=DECISION_TIME,
                ),),
                list_jobs=lambda _workflow_id: tuple(
                    SimpleNamespace(
                        inputs={"instrument_id": instrument_id},
                        finished_at=DECISION_TIME,
                    )
                    for instrument_id in instrument_ids
                ),
            )

        def get_run(self, _workflow_id):
            return SimpleNamespace(
                results=bulk_results,
                hashes={instrument_id: f"bulk-hash-{instrument_id}" for instrument_id in instrument_ids},
            )

    monkeypatch.setattr(bulk_run, "BulkAnalysisService", FakeBulkService)
    monkeypatch.setattr(
        selection_views,
        "load_fixed_income_screener",
        lambda **_kwargs: fixed_screen,
    )
    monkeypatch.setattr(
        selection_views,
        "load_opportunity_assessment",
        lambda instrument_id, **_kwargs: asdict(opportunities[instrument_id]),
    )
    monkeypatch.setattr(
        selection_views,
        "load_classification_projection",
        lambda instrument_id, **_kwargs: {
            "status": "available",
            "classification": {"country": "DE", "sector": "Industrials"},
        },
    )
    snapshot = SimpleNamespace(
        config=SimpleNamespace(
            universe=SimpleNamespace(by_id=lambda: {instrument_id: object() for instrument_id in instrument_ids})
        ),
    )
    portfolio = {"portfolio_id": "portfolio-test", "snapshot_id": "snapshot-1", "as_of": DECISION_TIME}
    constraints_a = validate_portfolio_policy(
        {"max_position_weight": 0.2}, policy_id="portfolio-goals:test", version=1
    )
    constraints_b = validate_portfolio_policy(
        {"max_position_weight": 0.3}, policy_id="portfolio-goals:test", version=1
    )

    earlier = load_top_n_selection(
        mode="cross_asset",
        top_n=1,
        decision_time=DECISION_TIME,
        snapshot=snapshot,
        portfolio_snapshot=portfolio,
        portfolio_policy=constraints_a,
        storage_root=tmp_path,
    )
    changed = load_top_n_selection(
        mode="cross_asset",
        top_n=1,
        decision_time=DECISION_TIME,
        snapshot=snapshot,
        portfolio_snapshot=portfolio,
        portfolio_policy=constraints_b,
        storage_root=tmp_path,
    )
    assert earlier["persistence_status"] == "persisted"
    assert len(earlier["candidate_table"]) == 5
    assert earlier["candidate_table"][-1]["instrument_id"] == "asset-4"
    bond_metrics = earlier["candidate_table"][-1]["common_metrics"]
    assert bond_metrics["net_expected_return"] == 0.7
    assert bond_metrics["downside_risk"] == 0.1
    earlier_record = dict(earlier)
    assert changed["persistence_status"] == "persisted"
    assert changed["run_id"] != earlier["run_id"]
    assert changed["input_hash"] != earlier["input_hash"]
    assert earlier == earlier_record
    with TransactionalStore(tmp_path) as store:
        stored_runs = store.list("top_n_selection_run.v1")
    assert len(stored_runs) == 2
    assert next(item for item in stored_runs if item.entity_id == earlier["run_id"]).payload["input_hash"] == earlier["input_hash"]

    monkeypatch.setattr(
        selection_views,
        "load_opportunity_assessment",
        lambda instrument_id, **_kwargs: {
            "status": "unavailable",
            "instrument": instrument_id,
            "reason_code": "opportunity_result_unavailable",
        },
    )
    unavailable = load_top_n_selection(
        mode="cross_asset",
        top_n=1,
        decision_time=DECISION_TIME,
        snapshot=snapshot,
        portfolio_snapshot=portfolio,
        portfolio_policy=constraints_b,
        storage_root=tmp_path,
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["reason"] == "frozen_opportunity_candidates_unavailable"
    assert unavailable.get("run_id") != changed["run_id"]
