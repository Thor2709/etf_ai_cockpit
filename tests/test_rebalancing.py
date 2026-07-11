from __future__ import annotations

from etf_cockpit.portfolio.rebalancing import proposed_new_weight, rebalance_score, target_weight_drift


def test_target_weight_drift_and_rebalance_score() -> None:
    assert target_weight_drift(0.15, 0.10) == 0.05
    assert rebalance_score(0.05, 0.10, 0.05) == 1.0
    assert rebalance_score(0.15, 0.10, 0.05) == -1.0


def test_proposed_new_weight_moves_halfway_to_target() -> None:
    new_weight = proposed_new_weight(0.06, 0.10, "add", 0.15)
    assert new_weight == 0.08
