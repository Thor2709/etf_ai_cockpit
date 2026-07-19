from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from etf_cockpit.features.training_centre import LocalTrainingRegistry, TrainingRegistryError
from etf_cockpit.validation.protocol import ValidationSpec, evaluate_trials


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _registry(tmp_path: Path) -> tuple[LocalTrainingRegistry, dict[str, object]]:
    registry = LocalTrainingRegistry(tmp_path)
    experiment = registry.create_experiment("baseline", experiment_id="exp-baseline")
    run = registry.create_run(
        str(experiment["experiment_id"]),
        run_id="run-001",
        parameters={"learning_rate": 0.1, "api_key": "do-not-store"},
        dataset_hash=_hash("data"),
        feature_hash=_hash("features"),
        code_hash=_hash("code"),
        environment_hash=_hash("environment"),
    )
    return registry, run


def test_registry_persists_lineage_and_replays_after_restart(tmp_path: Path) -> None:
    registry, run = _registry(tmp_path)
    assert run["lineage_hash"]
    assert run["parameters"]["api_key"] == "[REDACTED]"
    restarted = LocalTrainingRegistry(tmp_path)

    replay = restarted.replay(
        "run-001",
        dataset_hash=_hash("data"),
        feature_hash=_hash("features"),
        code_hash=_hash("code"),
        environment_hash=_hash("environment"),
        parameters={"learning_rate": 0.1, "api_key": "different"},
    )
    assert replay.replayable is True
    assert replay.mismatches == ()
    mismatch = restarted.replay(
        "run-001",
        dataset_hash=_hash("changed"),
        feature_hash=_hash("features"),
        code_hash=_hash("code"),
        environment_hash=_hash("environment"),
        parameters={"learning_rate": 0.1},
    )
    assert mismatch.replayable is False
    assert "dataset_hash" in mismatch.mismatches


def test_artefact_integrity_and_approval_gated_promotion(tmp_path: Path) -> None:
    registry, run = _registry(tmp_path)
    model_path = tmp_path / "models" / "baseline.json"
    model_path.parent.mkdir()
    model_path.write_text('{"model":"baseline"}', encoding="utf-8")
    registry.update_run("run-001", status="completed", progress=1.0, completion_report={"mae": 0.2})
    artifact = registry.register_artifact("run-001", model_path)
    model = registry.register_model("run-001", name="baseline", artifact_ids=[str(artifact["artifact_id"])], model_card={"method": "deterministic"})
    model_path.write_text('{"model":"tampered"}', encoding="utf-8")
    with pytest.raises(TrainingRegistryError, match="integrity"):
        registry.approve_model(str(model["model_id"]), reviewer="analyst", evaluation={"walk_forward": "passed"})
    model_path.write_text('{"model":"baseline"}', encoding="utf-8")
    with pytest.raises(TrainingRegistryError, match="approved"):
        registry.promote_model(str(model["model_id"]), "challenger")
    approved = registry.approve_model(str(model["model_id"]), reviewer="analyst", evaluation={"walk_forward": "passed"})
    promoted = registry.promote_model(str(approved["model_id"]), "challenger")
    assert promoted["aliases"] == ["challenger"]
    assert registry.verify_artifact(str(artifact["artifact_id"])).verified is True
    model_path.write_text('{"model":"tampered"}', encoding="utf-8")
    assert registry.verify_artifact(str(artifact["artifact_id"])).verified is False


def test_failed_or_cancelled_runs_cannot_register_or_publish_models(tmp_path: Path) -> None:
    registry = LocalTrainingRegistry(tmp_path)
    registry.create_experiment("failure", experiment_id="exp-failure")
    for run_id, status in (("run-failed", "failed"), ("run-cancelled", "cancelled")):
        registry.create_run("exp-failure", run_id=run_id, dataset_hash=_hash(run_id), feature_hash=_hash("f"), code_hash=_hash("c"), environment_hash=_hash("e"))
        registry.update_run(run_id, status=status)  # type: ignore[arg-type]
        with pytest.raises(TrainingRegistryError, match="completed"):
            registry.register_model(run_id, name="blocked", artifact_ids=["missing"], model_card={})


def test_unsafe_model_serialisation_is_rejected(tmp_path: Path) -> None:
    registry, _run = _registry(tmp_path)
    path = tmp_path / "models" / "unsafe.pkl"
    path.parent.mkdir()
    path.write_bytes(b"not a model")
    with pytest.raises(TrainingRegistryError, match="unsafe"):
        registry.register_artifact("run-001", path)


def test_registered_run_uses_durable_job_lifecycle(tmp_path: Path) -> None:
    registry, _run = _registry(tmp_path)
    workflow = registry.submit_run("run-001")
    assert workflow.workflow_id == "training:run-001"
    result = registry.run_next_job(lambda _context: {"evaluation": "passed"})
    assert result is not None
    run = registry.require("training.run", "run-001")
    assert run["status"] == "completed"
    assert run["workflow_id"] == workflow.workflow_id


def test_validation_evidence_retains_all_trials_and_fails_closed_without_researcher_approval(tmp_path: Path) -> None:
    registry, run = _registry(tmp_path)
    values = {"baseline": np.full(20, 0.1), "challenger": np.full(20, 0.2)}
    report = evaluate_trials(values, spec=ValidationSpec(n_splits=2, test_size=5, final_test_size=5, bootstrap_repetitions=10))

    stored = registry.record_validation_report(
        str(run["run_id"]),
        report,
        trial_returns={key: value.tolist() for key, value in values.items()},
        data_hash=_hash("data"),
        code_hash=_hash("code"),
        features={"price_basis": "adjusted_close"},
        thresholds={"minimum_score": 0.0},
        variants={"baseline": "naive", "challenger": "candidate"},
        selection_method="highest development-fold mean",
    )

    assert len(registry.list_validation_reports()) == 1
    assert len(registry.list_validation_reports()[0]["folds"]) == 2
    retained_report = registry.list_validation_reports()[0]
    assert {"data_hash", "code_hash", "features", "thresholds", "variants", "selection_method"} <= retained_report.keys()
    retained_trials = registry.list_validation_trials(str(stored["report_id"]))
    assert len(retained_trials) == 2
    assert {"return_series", "parameters", "validation_scores", "discarded_reason", "data_hash", "code_hash"} <= retained_trials[0].keys()
    result = registry.validation_promotion_result(str(stored["report_id"]))
    assert result["eligible"] is False
    assert "researcher_approval_missing" in result["reasons"]
    assert registry.snapshot()["validation.promotion_result"]
    decision = registry.record_researcher_decision(str(stored["report_id"]), decision="pending", reviewer="analyst", rationale="Review required")
    assert decision["execution_allowed"] is False

    with pytest.raises(TrainingRegistryError, match="return series"):
        registry.record_validation_report(
            str(run["run_id"]),
            report,
            trial_returns={"baseline": [0.1]},
            data_hash=_hash("data"),
            code_hash=_hash("code"),
            features={},
            thresholds={},
            variants={},
            selection_method="invalid",
        )

    with pytest.raises(TrainingRegistryError, match="report not found"):
        registry.validation_promotion_result("missing-report")
