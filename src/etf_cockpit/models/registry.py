from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from etf_cockpit.core.config import AppConfig
from etf_cockpit.models.local_weights import LocalModelStatus, model_weight_inventory


def model_availability(config: AppConfig) -> dict[str, bool]:
    inventory = model_weight_inventory(config)
    return {
        "baseline": True,
        "timesfm": any(status.model_name == "timesfm" and status.live_ready for status in inventory),
        "toto": any(status.model_name == "toto" and status.live_ready for status in inventory),
    }


def model_diagnostics(config: AppConfig) -> list[LocalModelStatus]:
    return model_weight_inventory(config)


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
