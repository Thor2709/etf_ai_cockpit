"""Local experiment tracking and model-governance primitives.

This is deliberately a small adapter over the existing transactional store.
It keeps experiment lineage durable without requiring an MLflow service or
serialising arbitrary Python objects.  The adapter records evidence and
promotion state; model execution remains disabled by policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Literal

from etf_cockpit.core.job_scheduler import DurableJobScheduler, JobSpec, WorkflowRecord
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.data.local_storage import StoredRecord, StorageRevisionConflict, TransactionalStore


RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
PromotionState = Literal["unpromoted", "approved", "challenger", "champion"]

_ENTITY_EXPERIMENT = "training.experiment"
_ENTITY_RUN = "training.run"
_ENTITY_METRIC = "training.metric"
_ENTITY_DATASET = "training.dataset"
_ENTITY_ARTIFACT = "training.artifact"
_ENTITY_MODEL = "training.model"
_ENTITY_VALIDATION_REPORT = "validation.report"
_ENTITY_VALIDATION_TRIAL = "validation.trial"
_ENTITY_VALIDATION_DECISION = "validation.researcher_decision"
_ENTITY_VALIDATION_PROMOTION = "validation.promotion_result"
_SAFE_HASH = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_SUFFIXES = {".pkl", ".pickle", ".joblib", ".dill", ".pt", ".pth"}
_SECRET_KEY = re.compile(r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd|authorization|bearer|secret|token)", re.I)


class TrainingRegistryError(RuntimeError):
    """Raised when a training record would violate lineage or authority rules."""


@dataclass(frozen=True)
class ReplayReport:
    run_id: str
    replayable: bool
    status: str
    mismatches: tuple[str, ...]
    lineage_hash: str


@dataclass(frozen=True)
class ArtifactVerification:
    artifact_id: str
    verified: bool
    sha256: str
    expected_sha256: str
    message: str


class LocalTrainingRegistry:
    """Durable local registry compatible with a future MLflow adapter."""

    execution_allowed = False

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def create_experiment(self, name: str, *, description: str = "", tags: Mapping[str, object] | None = None, experiment_id: str | None = None) -> dict[str, object]:
        experiment_id = _identifier(experiment_id or f"exp_{_hash_payload([name, description])[:16]}", "experiment_id")
        payload = {
            "experiment_id": experiment_id,
            "name": _bounded_text(name, "name"),
            "description": _bounded_text(description, "description", limit=2_000),
            "tags": _safe_mapping(tags or {}),
            "created_at": _utc_now(),
            "execution_allowed": False,
        }
        existing = self.get(_ENTITY_EXPERIMENT, experiment_id)
        if existing is not None:
            if existing.get("name") == payload["name"] and existing.get("description") == payload["description"] and existing.get("tags") == payload["tags"]:
                return existing
            raise TrainingRegistryError(f"experiment already exists with different content: {experiment_id}")
        return self._put(_ENTITY_EXPERIMENT, experiment_id, payload)

    def create_run(
        self,
        experiment_id: str,
        *,
        parameters: Mapping[str, object] | None = None,
        dataset_hash: str,
        feature_hash: str,
        code_hash: str,
        environment_hash: str,
        run_id: str | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, object]:
        experiment_id = _identifier(experiment_id, "experiment_id")
        if self.get(_ENTITY_EXPERIMENT, experiment_id) is None:
            raise TrainingRegistryError(f"unknown experiment: {experiment_id}")
        for label, value in (("dataset_hash", dataset_hash), ("feature_hash", feature_hash), ("code_hash", code_hash), ("environment_hash", environment_hash)):
            _require_hash(value, label)
        run_id = _identifier(run_id or f"run_{_hash_payload([experiment_id, dataset_hash, feature_hash, code_hash, environment_hash])[:16]}", "run_id")
        safe_parameters = _safe_mapping(parameters or {})
        lineage = {
            "dataset_hash": dataset_hash,
            "feature_hash": feature_hash,
            "code_hash": code_hash,
            "environment_hash": environment_hash,
            "parameters": safe_parameters,
        }
        payload = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "status": "queued",
            "progress": 0.0,
            "parameters": safe_parameters,
            **{key: lineage[key] for key in ("dataset_hash", "feature_hash", "code_hash", "environment_hash")},
            "lineage_hash": _hash_payload(lineage),
            "workflow_id": workflow_id or "",
            "promotion_state": "unpromoted",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "completion_report": {},
            "execution_allowed": False,
        }
        existing = self.get(_ENTITY_RUN, run_id)
        if existing is not None:
            if existing.get("lineage_hash") == payload["lineage_hash"]:
                return existing
            raise TrainingRegistryError(f"run already exists with different lineage: {run_id}")
        return self._put(_ENTITY_RUN, run_id, payload)

    def submit_run(self, run_id: str, *, label: str | None = None) -> WorkflowRecord:
        run = self.require(_ENTITY_RUN, run_id)
        if str(run["status"]) not in {"queued", "running"}:
            raise TrainingRegistryError("only queued or running runs can be submitted")
        scheduler = DurableJobScheduler(self.root)
        workflow_id = f"training:{run_id}"
        workflow = scheduler.submit(
            "model_training",
            label or f"Training run {run_id}",
            (JobSpec("train", f"Train {run_id}", input_payload={"run_id": run_id}),),
            input_payload={"run_id": run_id, "lineage_hash": run["lineage_hash"]},
            dedupe_key=f"training:{run_id}",
            workflow_id=workflow_id,
        )
        self.update_run(run_id, workflow_id=workflow.workflow_id, status="queued")
        return workflow

    def run_next_job(self, handler: Any) -> object | None:
        """Run one registered training job and mirror its durable lifecycle."""

        scheduler = DurableJobScheduler(self.root)

        def wrapped(context: Any) -> object:
            run_id = context.workflow_id.removeprefix("training:")
            self.update_run(run_id, status="running")
            try:
                output = handler(context)
            except Exception as exc:
                self.update_run(run_id, status="failed", completion_report={"error": f"{type(exc).__name__}: {exc}"})
                raise
            if context.is_cancel_requested():
                self.update_run(run_id, status="cancelled", completion_report={"message": "Cancelled before publication."})
            else:
                self.update_run(run_id, status="completed", progress=1.0, completion_report=_safe_mapping(output) if isinstance(output, Mapping) else {"output": redact_text(str(output))})
            return output

        return scheduler.run_once(wrapped)

    def update_run(self, run_id: str, *, status: RunStatus | None = None, progress: float | None = None, completion_report: Mapping[str, object] | None = None, workflow_id: str | None = None) -> dict[str, object]:
        run = self.require(_ENTITY_RUN, run_id)
        next_status = str(status or run["status"])
        if next_status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise TrainingRegistryError(f"invalid run status: {next_status}")
        if next_status in {"completed", "failed", "cancelled"} and str(run["status"]) in {"completed", "failed", "cancelled"} and next_status != str(run["status"]):
            raise TrainingRegistryError("terminal run status cannot be changed")
        value = float(run.get("progress", 0.0) if progress is None else progress)
        if not 0.0 <= value <= 1.0:
            raise ValueError("progress must be between 0 and 1")
        payload = dict(run)
        payload.update({"status": next_status, "progress": value, "updated_at": _utc_now()})
        if completion_report is not None:
            payload["completion_report"] = _safe_mapping(completion_report)
        if workflow_id is not None:
            payload["workflow_id"] = _identifier(workflow_id, "workflow_id")
        return self._put(_ENTITY_RUN, run_id, payload)

    def record_metric(self, run_id: str, name: str, value: float, *, step: int = 0) -> dict[str, object]:
        self.require(_ENTITY_RUN, run_id)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("metric value must be numeric")
        if step < 0:
            raise ValueError("metric step must be non-negative")
        metric_id = f"{run_id}:{_identifier(name, 'metric_name')}:{step}"
        return self._put(_ENTITY_METRIC, metric_id, {"metric_id": metric_id, "run_id": run_id, "name": _bounded_text(name, "metric_name"), "value": float(value), "step": int(step), "recorded_at": _utc_now()})

    def record_validation_report(
        self,
        run_id: str,
        report: object,
        *,
        trial_returns: Mapping[str, Sequence[float]],
        data_hash: str,
        code_hash: str,
        features: Mapping[str, object],
        thresholds: Mapping[str, object],
        variants: Mapping[str, object],
        selection_method: str,
    ) -> dict[str, object]:
        """Persist complete validation search evidence without promotion authority."""

        from etf_cockpit.validation.protocol import ValidationReport, report_fingerprint

        self.require(_ENTITY_RUN, run_id)
        if not isinstance(report, ValidationReport):
            raise TrainingRegistryError("validation evidence requires a ValidationReport")
        for label, value in (("data_hash", data_hash), ("code_hash", code_hash)):
            _require_hash(value, label)
        trial_ids = {trial.trial_id for trial in report.trials}
        if set(trial_returns) != trial_ids:
            raise TrainingRegistryError("every retained validation trial must have a return series")
        validated_returns: dict[str, list[float]] = {}
        for trial_id in trial_ids:
            series = [float(value) for value in trial_returns[trial_id]]
            if not series or len(series) > 100_000 or any(not math.isfinite(value) for value in series):
                raise TrainingRegistryError(f"trial {trial_id} has an invalid return series")
            validated_returns[trial_id] = series
        report_hash = report_fingerprint(report)
        report_id = f"validation_report_{_identifier(run_id, 'run_id')}_{report_hash[:12]}"
        report_payload = {
            "report_id": report_id,
            "run_id": _identifier(run_id, "run_id"),
            "report_fingerprint": report_hash,
            "protocol_version": report.protocol_version,
            "spec": report.spec.__dict__,
            "folds": [asdict(fold) for fold in report.folds],
            "trial_ids": sorted(trial_ids),
            "selected_trial_id": report.selected_trial_id,
            "final_test_score": report.final_test_score,
            "final_test_used_for_selection": report.final_test_used_for_selection,
            "uncertainty": _safe_mapping(report.uncertainty),
            "regime_results": _safe_mapping(report.regime_results),
            "subgroup_results": _safe_mapping(report.subgroup_results),
            "effective_independent_trial_count": report.effective_independent_trial_count,
            "deflated_sharpe": report.deflated_sharpe,
            "probability_of_backtest_overfitting": report.probability_of_backtest_overfitting,
            "false_discovery_rate": report.false_discovery_rate,
            "promotion_eligible": report.promotion_eligible,
            "warnings": list(report.warnings),
            "data_hash": data_hash,
            "code_hash": code_hash,
            "features": _safe_mapping(features),
            "thresholds": _safe_mapping(thresholds),
            "variants": _safe_mapping(variants),
            "selection_method": _bounded_text(selection_method, "selection_method", limit=500),
            "execution_allowed": False,
        }
        records: list[tuple[str, str, Mapping[str, object]]] = [(_ENTITY_VALIDATION_REPORT, report_id, report_payload)]
        for trial in report.trials:
            trial_payload = {
                "evidence_id": f"{report_id}:{_identifier(trial.trial_id, 'trial_id')}",
                "report_id": report_id,
                "run_id": _identifier(run_id, "run_id"),
                "trial_id": trial.trial_id,
                "return_series": validated_returns[trial.trial_id],
                "parameters": _safe_mapping(trial.parameters),
                "validation_scores": list(trial.validation_scores),
                "validation_mean": trial.validation_mean,
                "final_test_score": trial.final_test_score,
                "selected": trial.selected,
                "discarded_reason": trial.discarded_reason,
                "data_hash": data_hash,
                "code_hash": code_hash,
                "execution_allowed": False,
            }
            records.append((_ENTITY_VALIDATION_TRIAL, str(trial_payload["evidence_id"]), trial_payload))
        self._put_many_immutable(records)
        return report_payload

    def record_researcher_decision(self, report_id: str, *, decision: Literal["pending", "approved", "rejected"], reviewer: str, rationale: str) -> dict[str, object]:
        report = self.require(_ENTITY_VALIDATION_REPORT, report_id)
        if decision not in {"pending", "approved", "rejected"}:
            raise TrainingRegistryError("researcher decision is unsupported")
        if decision == "approved" and not bool(report.get("promotion_eligible")):
            raise TrainingRegistryError("an ineligible validation report cannot receive an approval decision")
        payload = {
            "decision_id": f"decision_{_hash_payload([report_id, decision, reviewer, rationale])[:20]}",
            "report_id": _identifier(report_id, "report_id"),
            "decision": decision,
            "reviewer": _bounded_text(reviewer, "reviewer"),
            "rationale": _bounded_text(rationale, "rationale", limit=2_000),
            "decided_at": _utc_now(),
            "execution_allowed": False,
        }
        existing = self.get(_ENTITY_VALIDATION_DECISION, str(payload["decision_id"]))
        if existing is not None:
            comparable = {key: value for key, value in payload.items() if key != "decided_at"}
            previous = {key: value for key, value in existing.items() if key != "decided_at"}
            if comparable == previous:
                return existing
        return self._put_immutable(_ENTITY_VALIDATION_DECISION, str(payload["decision_id"]), payload)

    def validation_promotion_result(self, report_id: str) -> dict[str, object]:
        report = self.get(_ENTITY_VALIDATION_REPORT, report_id)
        if report is None:
            payload = {"promotion_id": f"promotion_{_hash_payload([report_id, 'report_unavailable'])[:20]}", "report_id": report_id, "eligible": False, "reasons": ["report_unavailable"], "execution_allowed": False, "evaluated_at": ""}
            return self._put_immutable(_ENTITY_VALIDATION_PROMOTION, str(payload["promotion_id"]), payload)
        trial_ids = report.get("trial_ids", [])
        missing = [trial_id for trial_id in trial_ids if self.get(_ENTITY_VALIDATION_TRIAL, f"{report_id}:{trial_id}") is None]
        decisions = [item for item in self.list_records(_ENTITY_VALIDATION_DECISION) if item.get("report_id") == report_id]
        latest = max(decisions, key=lambda item: str(item.get("decided_at", "")), default=None)
        reasons = []
        if missing:
            reasons.append("trial_evidence_incomplete")
        if not bool(report.get("promotion_eligible")):
            reasons.append("protocol_promotion_ineligible")
        if latest is None or latest.get("decision") != "approved":
            reasons.append("researcher_approval_missing")
        decision_id = str(latest.get("decision_id", "")) if latest else ""
        payload = {
            "promotion_id": f"promotion_{_hash_payload([report_id, decision_id, not reasons, reasons])[:20]}",
            "report_id": report_id,
            "eligible": not reasons,
            "reasons": reasons,
            "researcher_decision": latest,
            "execution_allowed": False,
            "evaluated_at": str(latest.get("decided_at", "")) if latest else "",
        }
        return self._put_immutable(_ENTITY_VALIDATION_PROMOTION, str(payload["promotion_id"]), payload)

    def list_validation_reports(self) -> tuple[dict[str, object], ...]:
        return self.list_records(_ENTITY_VALIDATION_REPORT)

    def list_validation_trials(self, report_id: str | None = None) -> tuple[dict[str, object], ...]:
        rows = self.list_records(_ENTITY_VALIDATION_TRIAL)
        return tuple(row for row in rows if report_id is None or row.get("report_id") == report_id)

    def register_dataset(self, dataset_id: str, *, sha256: str, source: str, feature_hash: str = "") -> dict[str, object]:
        _require_hash(sha256, "sha256")
        if feature_hash:
            _require_hash(feature_hash, "feature_hash")
        payload = {"dataset_id": _identifier(dataset_id, "dataset_id"), "sha256": sha256, "source": _bounded_text(source, "source", limit=2_000), "feature_hash": feature_hash, "created_at": _utc_now()}
        return self._put(_ENTITY_DATASET, str(payload["dataset_id"]), payload)

    def register_artifact(self, run_id: str, path: Path, *, artifact_id: str | None = None, kind: str = "model") -> dict[str, object]:
        self.require(_ENTITY_RUN, run_id)
        resolved = self._safe_artifact_path(path)
        digest = _sha256_file(resolved)
        artifact_id = _identifier(artifact_id or f"artifact_{digest[:16]}", "artifact_id")
        payload = {"artifact_id": artifact_id, "run_id": run_id, "path": resolved.relative_to(self.root).as_posix(), "kind": _bounded_text(kind, "kind"), "sha256": digest, "size_bytes": resolved.stat().st_size, "created_at": _utc_now(), "safe_format": True}
        existing = self.get(_ENTITY_ARTIFACT, artifact_id)
        if existing is not None:
            if existing.get("sha256") == digest and existing.get("run_id") == run_id:
                return existing
            raise TrainingRegistryError(f"artefact already exists with different content: {artifact_id}")
        return self._put(_ENTITY_ARTIFACT, artifact_id, payload)

    def verify_artifact(self, artifact_id: str) -> ArtifactVerification:
        artifact = self.require(_ENTITY_ARTIFACT, artifact_id)
        try:
            path = self._safe_artifact_path(self.root / str(artifact["path"]))
        except (OSError, TrainingRegistryError) as exc:
            return ArtifactVerification(artifact_id, False, "", str(artifact["sha256"]), f"artefact is unavailable: {exc}")
        actual = _sha256_file(path)
        ok = actual == str(artifact["sha256"])
        return ArtifactVerification(artifact_id, ok, actual, str(artifact["sha256"]), "verified" if ok else "checksum mismatch")

    def register_model(self, run_id: str, *, name: str, artifact_ids: Sequence[str], model_card: Mapping[str, object]) -> dict[str, object]:
        run = self.require(_ENTITY_RUN, run_id)
        if str(run["status"]) != "completed":
            raise TrainingRegistryError("only completed runs can register models")
        if not artifact_ids or isinstance(artifact_ids, (str, bytes)):
            raise TrainingRegistryError("a model requires at least one verified artefact")
        for artifact_id in artifact_ids:
            artifact = self.require(_ENTITY_ARTIFACT, str(artifact_id))
            if str(artifact["run_id"]) != run_id or not self.verify_artifact(str(artifact_id)).verified:
                raise TrainingRegistryError("model artefacts must belong to the run and verify before registration")
        model_id = f"model_{_hash_payload([run_id, name, sorted(artifact_ids)])[:16]}"
        payload = {"model_id": model_id, "run_id": run_id, "name": _bounded_text(name, "name"), "artifact_ids": list(artifact_ids), "model_card": _safe_mapping(model_card), "approval_state": "pending", "promotion_state": "unpromoted", "aliases": [], "created_at": _utc_now(), "execution_allowed": False}
        existing = self.get(_ENTITY_MODEL, model_id)
        if existing is not None:
            return existing
        return self._put(_ENTITY_MODEL, model_id, payload)

    def approve_model(self, model_id: str, *, reviewer: str, evaluation: Mapping[str, object]) -> dict[str, object]:
        model = self.require(_ENTITY_MODEL, model_id)
        run = self.require(_ENTITY_RUN, str(model["run_id"]))
        if str(run["status"]) != "completed":
            raise TrainingRegistryError("only completed runs can be approved")
        if not evaluation:
            raise TrainingRegistryError("model approval requires an evaluation report")
        self._verify_model_artifacts(model)
        payload = dict(model)
        payload.update({"approval_state": "approved", "reviewer": _bounded_text(reviewer, "reviewer"), "evaluation": _safe_mapping(evaluation), "approved_at": _utc_now()})
        return self._put(_ENTITY_MODEL, model_id, payload)

    def promote_model(self, model_id: str, target: Literal["challenger", "champion"]) -> dict[str, object]:
        model = self.require(_ENTITY_MODEL, model_id)
        run = self.require(_ENTITY_RUN, str(model["run_id"]))
        if str(run["status"]) in {"failed", "cancelled"}:
            raise TrainingRegistryError("failed or cancelled runs cannot publish model aliases")
        if str(model["approval_state"]) != "approved":
            raise TrainingRegistryError("only approved models can become challengers or champions")
        self._verify_model_artifacts(model)
        payload = dict(model)
        aliases = sorted(set(str(item) for item in payload.get("aliases", [])) | {target})
        payload.update({"promotion_state": target, "aliases": aliases, "promoted_at": _utc_now()})
        return self._put(_ENTITY_MODEL, model_id, payload)

    def replay(self, run_id: str, *, dataset_hash: str, feature_hash: str, code_hash: str, environment_hash: str, parameters: Mapping[str, object] | None = None) -> ReplayReport:
        run = self.require(_ENTITY_RUN, run_id)
        expected = {"dataset_hash": dataset_hash, "feature_hash": feature_hash, "code_hash": code_hash, "environment_hash": environment_hash, "parameters": _safe_mapping(parameters or {})}
        mismatches = tuple(key for key in expected if expected[key] != run.get(key))
        return ReplayReport(run_id, not mismatches, "replayable" if not mismatches else "mismatch", mismatches, str(run["lineage_hash"]))

    def list_records(self, entity_type: str) -> tuple[dict[str, object], ...]:
        return tuple(record.payload for record in self._list(entity_type))

    def snapshot(self) -> dict[str, tuple[dict[str, object], ...]]:
        return {key: self.list_records(key) for key in (_ENTITY_EXPERIMENT, _ENTITY_RUN, _ENTITY_METRIC, _ENTITY_DATASET, _ENTITY_ARTIFACT, _ENTITY_MODEL, _ENTITY_VALIDATION_REPORT, _ENTITY_VALIDATION_TRIAL, _ENTITY_VALIDATION_DECISION, _ENTITY_VALIDATION_PROMOTION)}

    def get(self, entity_type: str, entity_id: str) -> dict[str, object] | None:
        record = self._store_get(entity_type, entity_id)
        return None if record is None else record.payload

    def require(self, entity_type: str, entity_id: str) -> dict[str, object]:
        value = self.get(entity_type, entity_id)
        if value is None:
            raise TrainingRegistryError(f"unknown {entity_type}: {entity_id}")
        return value

    def _put(self, entity_type: str, entity_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self._store_put(entity_type, entity_id, payload).payload

    def _put_immutable(self, entity_type: str, entity_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            with TransactionalStore(self.root) as store:
                return store.put_many([(entity_type, entity_id, payload)], immutable=True)[0].payload
        except StorageRevisionConflict as exc:
            raise TrainingRegistryError(f"immutable validation evidence already exists with different content: {entity_id}") from exc

    def _put_many_immutable(self, records: Sequence[tuple[str, str, Mapping[str, object]]]) -> None:
        with TransactionalStore(self.root) as store:
            store.put_many(records, immutable=True)

    def _list(self, entity_type: str) -> tuple[StoredRecord, ...]:
        with TransactionalStore(self.root) as store:
            return store.list(entity_type)

    def _store_get(self, entity_type: str, entity_id: str) -> StoredRecord | None:
        with TransactionalStore(self.root) as store:
            return store.get(entity_type, entity_id)

    def _store_put(self, entity_type: str, entity_id: str, payload: Mapping[str, object]) -> StoredRecord:
        with TransactionalStore(self.root) as store:
            return store.put(entity_type, entity_id, payload)

    def _safe_artifact_path(self, path: Path) -> Path:
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else self.root / candidate).resolve(strict=True)
        allowed_roots = tuple((self.root / name).resolve() for name in ("models", "data"))
        if not any(_within(resolved, allowed) for allowed in allowed_roots):
            raise TrainingRegistryError("artefacts must remain under the local models/ or data/ directories")
        if resolved.suffix.casefold() in _UNSAFE_SUFFIXES:
            raise TrainingRegistryError("unsafe serialised model artefact format is not accepted")
        return resolved

    def _verify_model_artifacts(self, model: Mapping[str, object]) -> None:
        artifact_ids = model.get("artifact_ids", ())
        for artifact_id in artifact_ids if isinstance(artifact_ids, Sequence) and not isinstance(artifact_ids, (str, bytes)) else ():
            if not self.verify_artifact(str(artifact_id)).verified:
                raise TrainingRegistryError("model artefact integrity verification failed")


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_mapping(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("mapping expected")
    return {str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact_value(item) for key, item in value.items()}


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value[:100]]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def _hash_payload(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_HASH.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hash")


def _identifier(value: str, label: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 160 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise ValueError(f"{label} must be a bounded identifier")
    return value


def _bounded_text(value: str, label: str, *, limit: int = 160) -> str:
    value = str(value).strip()
    if len(value) > limit or any(char in value for char in "\r\n"):
        raise ValueError(f"{label} is too long or contains a line break")
    return redact_text(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


__all__ = ["ArtifactVerification", "LocalTrainingRegistry", "ReplayReport", "TrainingRegistryError"]
