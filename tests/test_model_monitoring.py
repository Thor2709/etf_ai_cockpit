from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from pathlib import Path

import pytest

from etf_cockpit.features.training_centre import LocalTrainingRegistry, TrainingRegistryError
from etf_cockpit.models.monitoring import DatedReturn, DatedValue, DriftAlert, compare_net_performance
from etf_cockpit.models.registry import ModelScoringRejected, require_scoreable_model


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _approved_model(registry: LocalTrainingRegistry, root: Path, name: str) -> dict[str, object]:
    run_id = f"run-{name}"
    experiment_id = f"exp-{name}"
    registry.create_experiment(name, experiment_id=experiment_id)
    registry.create_run(
        experiment_id,
        run_id=run_id,
        dataset_hash=_hash(f"data-{name}"),
        feature_hash=_hash("features"),
        code_hash=_hash("code"),
        environment_hash=_hash("environment"),
    )
    registry.update_run(run_id, status="completed", progress=1.0)
    path = root / "models" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"model":"{name}"}}', encoding="utf-8")
    artifact = registry.register_artifact(run_id, path)
    model = registry.register_model(
        run_id,
        name=name,
        artifact_ids=[str(artifact["artifact_id"])],
        model_card={"method": "deterministic"},
    )
    return registry.approve_model(str(model["model_id"]), reviewer="analyst", evaluation={"walk_forward": "passed"})


def test_drift_emits_alert_and_requests_review_without_changing_champion(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    champion = _approved_model(registry, tmp_path, "champion")
    registry.promote_model(str(champion["model_id"]), "champion")
    challenger = _approved_model(registry, tmp_path, "challenger")
    registry.promote_model(str(challenger["model_id"]), "challenger")
    champion_before = registry.require("training.model", str(champion["model_id"]))
    cutoff = datetime(2026, 1, 10, tzinfo=timezone.utc)
    observations = [
        DatedValue(date(2026, 1, 1), 0.0),
        DatedValue(date(2026, 1, 2), 0.01),
        DatedValue(date(2026, 1, 3), 0.2),
        DatedValue(date(2026, 1, 4), 0.3),
        DatedValue(date(2026, 2, 1), 100.0),
    ]

    result = registry.monitor_model_drift(str(champion["model_id"]), observations, as_of=cutoff)

    assert isinstance(result.alert, DriftAlert)
    assert result.alert.score >= result.alert.threshold
    champion_after = registry.require("training.model", str(champion["model_id"]))
    assert champion_after["promotion_state"] == "champion"
    assert champion_after["aliases"] == champion_before["aliases"]
    assert registry.require("training.model", str(challenger["model_id"]))["promotion_state"] == "challenger"
    review = registry.snapshot()["training.model.monitoring_review"][-1]
    assert review["review_type"] == "warning_challenger"
    assert review["status"] == "pending"
    assert review["alert_id"] == result.alert.alert_id


def test_retired_model_is_rejected_for_proposals_and_scoring(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    model = _approved_model(registry, tmp_path, "retired")
    retired = registry.retire_model(str(model["model_id"]), reviewer="analyst", reason="superseded")

    assert retired["promotion_state"] == "retired"
    with pytest.raises(TrainingRegistryError, match="retired"):
        registry.promote_model(str(model["model_id"]), "challenger")
    with pytest.raises(ModelScoringRejected, match="retired"):
        require_scoreable_model(
            registry.require("training.model", str(model["model_id"])),
            registry.verify_artifact,
        )


def test_champion_rollback_restores_prior_models_and_appends_audit_event(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    prior_champion = _approved_model(registry, tmp_path, "prior")
    promoted_prior = registry.promote_model(str(prior_champion["model_id"]), "champion")
    candidate = _approved_model(registry, tmp_path, "candidate")
    candidate_before = dict(candidate)
    history_before = registry.audit_history()
    registry.promote_model(str(candidate["model_id"]), "champion")

    restored = registry.rollback_champion(str(candidate["model_id"]), reviewer="analyst", reason="regression review")

    assert restored == promoted_prior
    assert registry.require("training.model", str(prior_champion["model_id"])) == promoted_prior
    assert registry.require("training.model", str(candidate["model_id"])) == candidate_before
    history_after = registry.audit_history()
    assert len(history_after) > len(history_before)
    rollback = history_after[-1]
    assert rollback["event_type"] == "champion_rollback"
    assert rollback["who"] == "analyst"
    assert rollback["when"]
    assert rollback["why"] == "regression review"
    assert rollback["prior_state"]["promotion_state"] == "champion"
    assert rollback["new_state"]["promotion_state"] == "approved"
    assert history_after[: len(history_before)] == history_before


def test_performance_comparison_uses_net_returns_against_deterministic_baseline() -> None:
    cutoff = datetime(2026, 1, 5, tzinfo=timezone.utc)
    candidate = [
        DatedReturn(date(2026, 1, 1), 0.03, 100.0),
        DatedReturn(date(2026, 1, 2), 0.01, 100.0),
        DatedReturn(date(2026, 1, 6), 10.0, 0.0),
    ]
    baseline = [
        DatedReturn(date(2026, 1, 1), 0.02, 25.0),
        DatedReturn(date(2026, 1, 2), 0.02, 25.0),
        DatedReturn(date(2026, 1, 6), 10.0, 0.0),
    ]

    result = compare_net_performance(
        "candidate",
        candidate,
        "naive_drift",
        baseline,
        baseline_is_deterministic=True,
        as_of=cutoff,
    )

    assert result.status == "available"
    assert result.paired_observations == 2
    assert result.model_net_mean == pytest.approx(0.01)
    assert result.baseline_net_mean == pytest.approx(0.0175)
    assert result.excess_net_mean == pytest.approx(-0.0075)


def test_artifact_sha256_mismatch_blocks_model_scoring(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    model = _approved_model(registry, tmp_path, "mutated")
    artifact_id = str(model["artifact_ids"][0])
    artifact = registry.require("training.artifact", artifact_id)
    (tmp_path / str(artifact["path"])).write_text('{"model":"changed"}', encoding="utf-8")

    with pytest.raises(ModelScoringRejected, match="checksum mismatch"):
        require_scoreable_model(model, registry.verify_artifact)
