from __future__ import annotations

from dataclasses import replace
import json
import pickle
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application.ui_facade import load_portfolio_goals_projection
from etf_cockpit.core.config import load_config
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio.goals_constraints import (
    PortfolioPolicy,
    build_alerts,
    build_what_if_scenario,
    evaluate_constraints,
    validate_portfolio_policy,
)
from etf_cockpit.portfolio.sandbox import (
    PortfolioSnapshotBinding,
    analyse_candidate,
    create_candidate,
)


def _portfolio(*, metadata: bool = False):
    config = load_config()
    rows = [
        {"etf_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0},
        {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0},
    ]
    if metadata:
        rows[0].update({"asset_class": "fixed_income", "sector": "Portfolio bonds", "duration_years": 8.0, "rating": "BB"})
        rows[1].update({"asset_class": "fixed_income", "sector": "Portfolio bonds", "duration_years": 2.0, "rating": "AAA"})
    holdings = pd.DataFrame(rows)
    candidate = create_candidate(
        config,
        holdings,
        name="Goal test candidate",
        analysis_notional_eur=100_000.0,
        target_weights={"VWCE": 0.6, "LYP6": 0.4},
        cash_weight=0.0,
        source_revision="universe-test",
        source_as_of="2026-07-18",
    )
    analysis = analyse_candidate(config, holdings, candidate, current_revision="universe-test")
    binding = PortfolioSnapshotBinding(
        account_id="default",
        portfolio_id="default",
        snapshot_id="snapshot-1",
        source_revision="universe-test",
        source_checksum=candidate.source_checksum,
        price_source_revision="prices-test",
        price_source_checksum="a" * 64,
        as_of="2026-07-18",
    )
    analysis = replace(analysis, snapshot_binding=binding)
    snapshot = SimpleNamespace(
        config=config,
        holdings=holdings,
        account_id="default",
        portfolio_id="default",
        snapshot_id="snapshot-1",
    )
    return snapshot, analysis


def test_what_if_leaves_live_portfolio_and_stored_snapshot_bytes_identical(tmp_path) -> None:
    snapshot, analysis = _portfolio()
    live_before = pickle.dumps(snapshot.holdings, protocol=pickle.HIGHEST_PROTOCOL)
    with TransactionalStore(tmp_path) as store:
        record = store.put(
            "portfolio_snapshot",
            "snapshot-1",
            {"snapshot_id": "snapshot-1", "holdings": snapshot.holdings.to_dict(orient="records")},
        )
        stored_before = json.dumps(record.payload, sort_keys=True, separators=(",", ":")).encode()

    policy = PortfolioPolicy(policy_id="portfolio-goals:test", version=0)
    scenario = build_what_if_scenario(analysis, snapshot, policy)

    with TransactionalStore(tmp_path) as store:
        stored_after = json.dumps(store.get("portfolio_snapshot", "snapshot-1").payload, sort_keys=True, separators=(",", ":")).encode()
    assert pickle.dumps(snapshot.holdings, protocol=pickle.HIGHEST_PROTOCOL) == live_before
    assert stored_after == stored_before
    assert scenario.execution_allowed is False


def test_constraints_evaluate_position_sector_duration_and_rating_after_trade() -> None:
    snapshot, analysis = _portfolio(metadata=True)
    policy = validate_portfolio_policy(
        {
            "max_position_weight": 0.5,
            "max_sector_weight": 0.8,
            "max_duration_years": 4.0,
            "minimum_rating": "BBB",
        },
        policy_id="portfolio-goals:test",
        version=1,
    )

    results = {item.constraint_id: item for item in evaluate_constraints(policy, analysis, snapshot)}

    assert results["max_position_weight:VWCE"].status == "blocked"
    assert results["max_position_weight:VWCE"].observed == 0.6
    assert results["max_sector_weight"].status == "blocked"
    assert results["max_sector_weight"].observed == 1.0
    assert results["max_duration_years"].status == "blocked"
    assert results["max_duration_years"].observed == 5.6
    assert results["minimum_rating"].status == "blocked"
    assert results["minimum_rating"].observed == "BB"


def test_alerts_reproduce_exactly_from_their_source_snapshot_hash() -> None:
    snapshot, analysis = _portfolio()
    policy = validate_portfolio_policy(
        {"max_position_weight": 0.5, "max_drawdown": 0.1},
        policy_id="portfolio-goals:test",
        version=1,
    )
    snapshot_hash = "b" * 64
    evidence = {"max_drawdown": {"status": "available", "value": 0.2}}

    first, unavailable = build_alerts(analysis, policy, snapshot=snapshot, evidence=evidence, snapshot_hash=snapshot_hash)
    replay, replay_unavailable = build_alerts(analysis, policy, snapshot=snapshot, evidence=evidence, snapshot_hash=snapshot_hash)

    assert first == replay
    assert unavailable == replay_unavailable
    assert first
    assert all(item.source_snapshot_hash == snapshot_hash for item in first)
    assert all(item.alert_id for item in first)

    changed_allocations = tuple(
        replace(row, target_weight=0.9 if row.instrument_id == "VWCE" else 0.1)
        for row in analysis.allocations
    )
    changed_candidate = replace(analysis.candidate, target_weights=(("LYP6", 0.1), ("VWCE", 0.9)))
    changed_analysis = replace(analysis, candidate=changed_candidate, allocations=changed_allocations)
    changed_candidate_alerts, _ = build_alerts(
        changed_analysis, policy, snapshot=snapshot, evidence=evidence, snapshot_hash=snapshot_hash
    )
    first_concentration = next(item for item in first if item.condition == "max_position_weight:VWCE")
    changed_concentration = next(item for item in changed_candidate_alerts if item.condition == first_concentration.condition)
    assert changed_concentration.evidence["observed"] == 0.9
    assert changed_concentration.alert_id != first_concentration.alert_id

    changed_policy = validate_portfolio_policy(
        {"max_position_weight": 0.75, "max_drawdown": 0.1},
        policy_id="portfolio-goals:test",
        version=2,
    )
    changed_policy_alerts, _ = build_alerts(
        changed_analysis, changed_policy, snapshot=snapshot, evidence=evidence, snapshot_hash=snapshot_hash
    )
    changed_policy_concentration = next(item for item in changed_policy_alerts if item.condition == first_concentration.condition)
    assert changed_policy_concentration.alert_id != changed_concentration.alert_id

    changed_evidence_alerts, _ = build_alerts(
        changed_analysis,
        changed_policy,
        snapshot=snapshot,
        evidence={"max_drawdown": {"status": "available", "value": 0.3}},
        snapshot_hash=snapshot_hash,
    )
    policy_drawdown = next(item for item in changed_policy_alerts if item.kind == "drawdown")
    changed_evidence_drawdown = next(item for item in changed_evidence_alerts if item.kind == "drawdown")
    assert changed_evidence_drawdown.evidence["observed"] == 0.3
    assert changed_evidence_drawdown.alert_id != policy_drawdown.alert_id


def test_infeasible_constraint_remains_blocked_with_explanation() -> None:
    snapshot, analysis = _portfolio()
    policy = validate_portfolio_policy(
        {"max_position_weight": 0.25, "max_drawdown": 0.12},
        policy_id="portfolio-goals:test",
        version=1,
    )

    scenario = build_what_if_scenario(
        analysis,
        snapshot,
        policy,
        evidence={"max_drawdown": {"status": "available", "value": -0.2}},
    )
    result = next(item for item in scenario.constraints if item.constraint_id == "max_position_weight:VWCE")
    drawdown = next(item for item in scenario.constraints if item.constraint_id == "max_drawdown")

    assert scenario.status == "blocked"
    assert result.status == "blocked"
    assert result.limit == 0.25
    assert result.explanation
    assert "max_position_weight:VWCE" in scenario.binding_constraints
    assert any("0.25" in item or "25.0%" in item for item in scenario.rejected_candidates)
    assert drawdown.status == "blocked"
    assert drawdown.observed == 0.2


def test_policy_versions_are_appended_and_invalid_versions_are_rejected(tmp_path) -> None:
    snapshot, analysis = _portfolio()
    first = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={"type": "save_policy", "policy": {"max_position_weight": 0.4}, "at": "2026-10-01T08:00:00+00:00"},
        root=tmp_path,
    )
    second = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={"type": "save_policy", "policy": {"max_sector_weight": 0.6}, "at": "2026-10-01T08:01:00+00:00"},
        root=tmp_path,
    )

    assert first["status"] == "available"
    assert second["status"] == "available"
    assert [row["version"] for row in second["policy_history"]] == [1, 2]
    assert second["policy_as_of"]["status"] == "unavailable"
    invalid = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={"type": "save_policy", "policy": {"max_position_weight": 2}, "at": "2026-10-01T08:02:00+00:00"},
        root=tmp_path,
    )
    assert invalid["status"] == "invalid"


def test_what_if_policy_binding_blocks_a_draft_after_policy_tightening(tmp_path) -> None:
    snapshot, analysis = _portfolio()
    analysis = replace(analysis, constraints=())
    saved = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={
            "type": "save_policy",
            "policy": {"max_position_weight": 0.8},
            "at": "2026-10-01T10:00:00+00:00",
        },
        root=tmp_path,
    )
    simulated = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={"type": "simulate", "at": "2026-10-01T10:30:00+00:00"},
        root=tmp_path,
    )
    tightened = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={
            "type": "save_policy",
            "policy": {"max_position_weight": 0.5},
            "at": "2026-10-01T11:00:00+00:00",
        },
        root=tmp_path,
    )
    old_scenario = tightened["scenario"]

    assert simulated["scenario"]["status"] == "ready", simulated["scenario"].get("rejected_candidates")
    assert simulated["scenario"]["policy_binding"] == saved["effective_policy_binding"]
    assert old_scenario["status"] == "ready"
    assert old_scenario["policy_binding"] != tightened["effective_policy_binding"]


def test_alert_acknowledgement_and_snooze_persist_without_removing_conditions(tmp_path) -> None:
    snapshot, analysis = _portfolio()
    initial = load_portfolio_goals_projection(snapshot, analysis, root=tmp_path)
    alert_ids = [item["alert_id"] for item in initial["alerts"]]
    acknowledged = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={"type": "acknowledge", "alert_ids": alert_ids, "at": "2026-10-01T08:00:00+00:00"},
        root=tmp_path,
    )
    snoozed = load_portfolio_goals_projection(
        snapshot,
        analysis,
        action={
            "type": "snooze",
            "alert_ids": alert_ids,
            "at": "2026-10-01T08:01:00+00:00",
            "until": "2026-10-02T08:00:00+00:00",
        },
        root=tmp_path,
    )

    assert [item["alert_id"] for item in acknowledged["alerts"]] == alert_ids
    assert all(item["acknowledged"] for item in acknowledged["alerts"])
    assert [item["alert_id"] for item in snoozed["alerts"]] == alert_ids
    assert all(item["snoozed_until"] == "2026-10-02T08:00:00+00:00" for item in snoozed["alerts"])
    assert [item["action"] for item in snoozed["acknowledgement_history"]] == ["acknowledge"] * len(alert_ids) + ["snooze"] * len(alert_ids)
