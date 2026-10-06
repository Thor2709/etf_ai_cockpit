"""Identity, classification and peer-cohort read models for presentation (application; ADR-0002)."""

from pathlib import Path

from etf_cockpit.data.identity_master import (
    IdentityMasterSchemaError,
    IdentityMasterStore,
    identity_master_exists,
)
from etf_cockpit.data.classification import (
    ClassificationOverride,
    ClassificationSchemaError,
    ClassificationStore,
    read_classification_projection,
)
from etf_cockpit.data.peer_cohort_store import read_peer_cohort_projection
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH


def load_identity_projection(
    instrument_id: str,
    path: Path | None = None,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return one fail-closed, read-only identity lineage projection for presentation."""

    import pandas as pd

    master_root = Path(storage_root).resolve() if storage_root is not None else None
    if master_root is None and path is None:
        default_path = Path(IDENTITY_PATH).resolve()
        if len(default_path.parents) >= 3:
            master_root = default_path.parents[2]
    if master_root is not None:
        try:
            if identity_master_exists(master_root):
                with IdentityMasterStore(master_root) as master:
                    return master.projection(
                        instrument_id,
                        effective_at=effective_at,
                        decision_time=decision_time,
                    )
            if storage_root is not None and path is None:
                return {
                    "status": "unavailable",
                    "instrument_id": str(instrument_id),
                    "reason_code": "identity_master_evidence_unavailable",
                    "execution_allowed": False,
                }
        except KeyError:
            if storage_root is not None and path is None:
                return {
                    "status": "unavailable",
                    "instrument_id": str(instrument_id),
                    "reason_code": "identity_master_evidence_unavailable",
                    "execution_allowed": False,
                }
        except (IdentityMasterSchemaError, OSError, ValueError):
            return {
                "status": "unavailable",
                "instrument_id": str(instrument_id),
                "reason_code": "identity_master_evidence_invalid",
                "execution_allowed": False,
            }

    identity_path = Path(path or IDENTITY_PATH)
    try:
        frame = pd.read_parquet(identity_path)
    except (OSError, ValueError, ImportError):
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "identity_evidence_unavailable",
            "execution_allowed": False,
        }
    if "instrument_id" not in frame.columns:
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "identity_schema_unavailable",
            "execution_allowed": False,
        }
    matches = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    if len(matches) != 1:
        return {
            "status": "quarantined" if len(matches) > 1 else "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "duplicate_identity_projection" if len(matches) > 1 else "identity_evidence_unavailable",
            "candidate_count": len(matches),
            "execution_allowed": False,
        }
    row = matches.iloc[0]
    fields = (
        "identity_confidence",
        "identity_status",
        "identity_decision_id",
        "identity_conflict_ids",
        "identity_resolution_state",
        "identity_effective_at",
        "identity_decision_time",
        "identity_objects",
        "identity_history",
        "warnings",
    )
    projection: dict[str, object] = {
        "status": "available",
        "instrument_id": str(instrument_id),
        "execution_allowed": False,
    }
    for field in fields:
        value = row.get(field)
        projection[field] = "unavailable" if value is None or bool(pd.isna(value)) else value
    return projection


def load_classification_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
    min_leaf_confidence: float = 0.75,
) -> dict[str, object]:
    """Return fail-closed point-in-time classification for presentation."""

    root = Path(storage_root).resolve() if storage_root is not None else None
    if root is None:
        default_path = Path(IDENTITY_PATH).resolve()
        if len(default_path.parents) >= 3:
            root = default_path.parents[2]
    if root is None:
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_storage_unavailable",
            "execution_allowed": False,
        }
    try:
        return read_classification_projection(
            root,
            instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
            min_leaf_confidence=min_leaf_confidence,
        )
    except (ClassificationSchemaError, OSError, ValueError):
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_evidence_invalid",
            "execution_allowed": False,
        }


def load_peer_cohort_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return persisted peer lineage only; presentation never calculates statistics."""

    from etf_cockpit.core.paths import ROOT

    try:
        return read_peer_cohort_projection(
            Path(storage_root or ROOT).resolve(),
            instrument_id,
            decision_time=decision_time,
        )
    except (OSError, TypeError, ValueError):
        return {
            "contract": "peer-cohort.v1",
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "peer_cohort_evidence_invalid",
            "execution_allowed": False,
        }


def save_classification_overrides(
    storage_root: Path,
    overrides: tuple[ClassificationOverride, ...],
) -> dict[str, object]:
    """Persist reviewed local overrides through the application boundary."""

    try:
        with ClassificationStore(Path(storage_root).resolve()) as store:
            record_ids = store.append_overrides(overrides)
        return {
            "status": "saved",
            "record_ids": record_ids,
            "dependent_scores_invalidated": bool(record_ids),
            "execution_allowed": False,
        }
    except (ClassificationSchemaError, OSError, ValueError) as exc:
        return {
            "status": "rejected",
            "record_ids": (),
            "reason_code": "classification_override_rejected",
            "message": str(exc),
            "dependent_scores_invalidated": False,
            "execution_allowed": False,
        }
