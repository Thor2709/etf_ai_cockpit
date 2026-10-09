"""Identity, classification and peer-cohort read models for presentation (application; ADR-0002)."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

from etf_cockpit.data.identity_master import (
    IdentityMasterSchemaError,
    IdentityMasterStore,
    identity_master_exists,
)
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    ClassificationOverride,
    ClassificationSchemaError,
    ClassificationStore,
    read_classification_projection,
)
from etf_cockpit.data.peer_cohort_store import read_peer_cohort_projection
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH
from etf_cockpit.core.session_log import log_event
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.core.config import load_config


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
        except KeyError:
            pass
        except (IdentityMasterSchemaError, OSError, ValueError) as exc:
            log_event(
                event_type="data_read_failed",
                severity="warning",
                component="identity_projection",
                operation="read_identity_master",
                instrument_id=str(instrument_id),
                exception_type=type(exc).__name__,
                exception_message_redacted=str(exc),
            )
            return {
                "status": "unavailable",
                "instrument_id": str(instrument_id),
                "reason_code": "identity_master_evidence_invalid",
                "execution_allowed": False,
            }

    identity_path = Path(path) if path is not None else (
        master_root / "data" / "clean" / "instrument_identity.parquet"
        if master_root is not None
        else Path(IDENTITY_PATH)
    )
    try:
        frame = pd.read_parquet(identity_path)
    except (OSError, ValueError, ImportError) as exc:
        log_event(
            event_type="data_read_failed",
            severity="warning",
            component="identity_projection",
            operation="read_identity_parquet_fallback",
            instrument_id=str(instrument_id),
            file_paths=identity_path,
            exception_type=type(exc).__name__,
            exception_message_redacted=str(exc),
        )
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
    candidate_count = len(matches)
    duplicate_sources: tuple[str, ...] = ()
    if len(matches) > 1 and "source" in matches.columns:
        configured = matches.loc[matches["source"].astype(str).str.casefold().eq("configs/universe.yaml")]
        if len(configured) == 1:
            duplicate_sources = tuple(dict.fromkeys(matches["source"].fillna("unavailable").astype(str)))
            matches = configured
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
        "display_name",
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
    if duplicate_sources:
        projection["candidate_count"] = candidate_count
        projection["candidate_sources"] = duplicate_sources
    for field in fields:
        value = row.get(field)
        projection[field] = "unavailable" if value is None or bool(pd.isna(value)) else value
    if duplicate_sources:
        projection["warnings"] = tuple(dict.fromkeys((*_text_sequence(row.get("warnings")), "duplicate_identity_candidates_retained")))
    return projection


def _text_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part for part in value.split("|") if part)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(part) for part in value if str(part).strip())
    return ()


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
        projection = read_classification_projection(
            root,
            instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
            min_leaf_confidence=min_leaf_confidence,
        )
        if projection.get("status") == "unresolved" and _projection_sector(projection) is None:
            _seed_universe_classification(root, instrument_id)
            projection = read_classification_projection(
                root,
                instrument_id,
                effective_at=effective_at,
                decision_time=decision_time,
                min_leaf_confidence=min_leaf_confidence,
            )
        return projection
    except (ClassificationSchemaError, OSError, ValueError) as exc:
        log_event(
            event_type="data_read_failed",
            severity="warning",
            component="classification_projection",
            operation="read_classification_evidence",
            instrument_id=str(instrument_id),
            exception_type=type(exc).__name__,
            exception_message_redacted=str(exc),
        )
        return {
            "status": "unavailable",
            "instrument_id": str(instrument_id),
            "reason_code": "classification_evidence_invalid",
            "execution_allowed": False,
        }


def _projection_sector(projection: dict[str, object]) -> str | None:
    classification = projection.get("classification")
    value = classification.get("sector") if isinstance(classification, dict) else None
    text = str(value or "").strip()
    if text.casefold() in {"", "unavailable", "unknown", "n/a", "none", "nan"}:
        return None
    return text


def _seed_universe_classification(root: Path, instrument_id: str) -> None:
    """Persist missing classification fields from the explicit local universe record."""

    try:
        config = load_config(root / "configs")
        record = next((item for item in config.universe.etfs if str(item.id) == str(instrument_id)), None)
        if record is None:
            return
        raw_sector = str(record.sector or "").strip()
        if not raw_sector:
            return
        canonical_sector = "financials" if raw_sector.casefold() == "banks" else raw_sector
        source_values = {
            "instrument_type": str(record.instrument_type or "").strip(),
            "asset_class": str(record.asset_class or "").strip(),
            "sector": canonical_sector,
            "trading_currency": str(record.currency or "").strip(),
        }
        source_values = {field: value for field, value in source_values.items() if value}
        source_payload = json.dumps(
            {"instrument_id": str(instrument_id), "fields": source_values, "raw_sector": raw_sector},
            sort_keys=True,
            separators=(",", ":"),
        )
        source_checksum = hashlib.sha256(source_payload.encode("utf-8")).hexdigest()
        available_at = datetime.now(timezone.utc).isoformat()
        alternatives = (raw_sector,) if canonical_sector != raw_sector else ()
        evidence = tuple(
            ClassificationEvidence(
                evidence_id=f"universe-config:{instrument_id}:{field}:{source_checksum[:16]}",
                instrument_id=str(instrument_id),
                field=field,
                value=value,
                source="configs/universe.yaml",
                authority=SourceAuthority.MANUAL,
                source_id=f"universe-config:{instrument_id}",
                confidence=0.75,
                source_checksum=source_checksum,
                available_at=available_at,
                alternatives=alternatives if field == "sector" else (),
            )
            for field, value in source_values.items()
        )
        with ClassificationStore(root) as store:
            store.append_evidence(evidence)
    except (ClassificationSchemaError, OSError, TypeError, ValueError) as exc:
        log_event(
            event_type="data_write_failed",
            severity="warning",
            component="classification_projection",
            operation="seed_universe_classification",
            instrument_id=str(instrument_id),
            exception_type=type(exc).__name__,
            exception_message_redacted=str(exc),
        )


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
