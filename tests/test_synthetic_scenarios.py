from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.features.synthetic_scenarios import (
    SyntheticScenarioError,
    SyntheticScenarioGenerator,
    SyntheticScenarioSpec,
)


def test_seed_reproduces_every_fixture_and_metadata() -> None:
    generator = SyntheticScenarioGenerator()
    spec = SyntheticScenarioSpec(periods=80, seed=17, missing_rate=0.12, restatement_rate=0.08, action_rate=0.08, conflict_rate=0.08)
    first = generator.generate(spec)
    second = generator.generate(spec)

    for name in ("prices", "data_quality", "corporate_actions", "provider_conflicts", "execution_events"):
        pd.testing.assert_frame_equal(getattr(first, name), getattr(second, name))
    assert first.metadata == second.metadata


def test_outputs_cover_quality_actions_conflicts_and_execution_failures() -> None:
    dataset = SyntheticScenarioGenerator().generate(
        SyntheticScenarioSpec(periods=60, seed=3, missing_rate=0.0, restatement_rate=1.0, action_rate=1.0, conflict_rate=1.0, execution_failures=4)
    )
    assert dataset.prices["synthetic"].all()
    assert "restatement" in set(dataset.data_quality["issue"])
    assert not dataset.corporate_actions.empty
    assert not dataset.provider_conflicts.empty
    assert set(dataset.execution_events["status"]) == {"partial_fill", "latency", "rejected", "reconciliation_mismatch"}
    missing = SyntheticScenarioGenerator().generate(SyntheticScenarioSpec(periods=20, seed=3, missing_rate=1.0))
    assert missing.prices["close"].isna().all()


def test_validation_and_promotion_guard_keep_synthetic_evidence_out() -> None:
    dataset = SyntheticScenarioGenerator().generate(SyntheticScenarioSpec(periods=20, execution_failures=0))
    evidence = SyntheticScenarioGenerator.validate(dataset)
    assert evidence["status"] == "pass"
    assert evidence["promotion_eligible"] is False
    guard = SyntheticScenarioGenerator.promotion_guard({"observed_evidence_count": 2})
    assert guard == {"promotion_eligible": False, "synthetic_evidence_excluded": True, "reason": "Synthetic fixtures are for invariants, rare failures and robustness only.", "observed_evidence_count": 2}


def test_invalid_scenario_parameters_fail_closed() -> None:
    with pytest.raises(SyntheticScenarioError):
        SyntheticScenarioSpec(periods=1)
    with pytest.raises(SyntheticScenarioError):
        SyntheticScenarioSpec(missing_rate=1.1)
    with pytest.raises(SyntheticScenarioError):
        SyntheticScenarioSpec(assets=("DUP", "DUP"))
