from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.features.training_centre import LocalTrainingRegistry
from etf_cockpit.models.local_weights import LocalModelStatus, model_weight_inventory


def model_availability(
    config: AppConfig,
    *,
    training_registry: LocalTrainingRegistry | None = None,
) -> dict[str, object]:
    inventory = model_weight_inventory(config)
    availability: dict[str, object] = {
        "baseline": True,
        "timesfm": any(status.model_name == "timesfm" and status.live_ready for status in inventory),
        "toto": any(status.model_name == "toto" and status.live_ready for status in inventory),
    }
    reasons: dict[str, str | None] = {"timesfm": None, "toto": None}
    for model_name in ("timesfm", "toto"):
        status = next((item for item in inventory if item.model_name == model_name), None)
        if not availability[model_name] and status is not None:
            reasons[model_name] = status.message

    registry = training_registry
    if registry is None:
        if not storage_layout(ROOT).transactional_path.exists():
            availability["reasons"] = reasons
            return availability
        registry = LocalTrainingRegistry(ROOT)
    try:
        registered_models = registry.list_records("training.model")
        for model_name in ("timesfm", "toto"):
            matching = [
                model
                for model in registered_models
                if str(model.get("name") or "").strip().casefold() == model_name
            ]
            for model in matching:
                try:
                    require_scoreable_model(model, registry.verify_artifact)
                except ModelScoringRejected as exc:
                    availability[model_name] = False
                    reasons[model_name] = exc.reason
                    break
    except Exception as exc:
        reason = f"registered model integrity is unavailable: {type(exc).__name__}: {exc}"
        for model_name in ("timesfm", "toto"):
            availability[model_name] = False
            reasons[model_name] = reason
    availability["reasons"] = reasons
    return availability


def model_diagnostics(config: AppConfig) -> list[LocalModelStatus]:
    inventory = model_weight_inventory(config)
    availability = model_availability(config)
    reasons = availability.get("reasons", {})
    if not isinstance(reasons, Mapping):
        return inventory
    return [
        replace(item, live_ready=False, status="unavailable", message=str(reasons[item.model_name]))
        if item.model_name in reasons and reasons[item.model_name] is not None
        else item
        for item in inventory
    ]


class ModelScoringRejected(RuntimeError):
    """A typed reason that a registered model cannot produce a score."""

    def __init__(self, model_id: str, reason: str):
        self.model_id = model_id
        self.reason = reason
        super().__init__(f"model scoring blocked for {model_id}: {reason}")


def require_scoreable_model(
    model: Mapping[str, object],
    verify_artifact: Callable[[str], object],
) -> Mapping[str, object]:
    """Gate inference on non-retired state and verified local artefact hashes.

    Score-producing callers must use this check before loading a registered
    artefact. An unavailable artefact or checksum mismatch fails closed.
    """

    model_id = str(model.get("model_id", "unknown"))
    if model.get("promotion_state") == "retired":
        raise ModelScoringRejected(model_id, "retired models cannot be scored")
    if model.get("promotion_state") not in {"approved", "challenger", "champion"}:
        raise ModelScoringRejected(model_id, "model has not passed approval for scoring")
    artifact_ids = model.get("artifact_ids")
    if not isinstance(artifact_ids, Sequence) or isinstance(artifact_ids, (str, bytes)) or not artifact_ids:
        raise ModelScoringRejected(model_id, "registered model has no verifiable artefacts")
    for artifact_id in artifact_ids:
        verification = verify_artifact(str(artifact_id))
        if not bool(getattr(verification, "verified", False)):
            reason = str(getattr(verification, "message", "artefact integrity verification is unavailable"))
            raise ModelScoringRejected(model_id, reason)
    return model


__all__ = [
    "ModelScoringRejected",
    "model_availability",
    "model_diagnostics",
    "require_scoreable_model",
]
