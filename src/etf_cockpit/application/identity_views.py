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
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.universe_store import load_sparebank_records


def load_identity_projection(
    instrument_id: str,
    path: Path | None = None,
    *,
    storage_root: Path | None = None,
    universe_root: Path | None = None,
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
                    projection = master.projection(
                        instrument_id,
                        effective_at=effective_at,
                        decision_time=decision_time,
                    )
                    return _with_configured_instrument_type(projection, instrument_id, universe_root)
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
    projection = _with_configured_instrument_type(projection, instrument_id, universe_root)
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
    universe_root: Path | None = None,
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
        configured_record = _configured_record(root, instrument_id, universe_root)
        configured_type = _configured_instrument_type(configured_record).casefold().replace("-", "_").replace(" ", "_")
        configured_bank = (
            configured_type in {"equity_certificate", "certificate"}
            and str(getattr(configured_record, "region", "") or "").strip().casefold() in {"norway", "norge", "norwegian"}
            and str(getattr(configured_record, "sector", "") or "").strip().casefold() in {"bank", "banks", "banking"}
            and str(getattr(configured_record, "tier", "") or "").strip().casefold() == "sparebanken"
        )
        if configured_bank or (projection.get("status") == "unresolved" and _projection_sector(projection) is None):
            _seed_universe_classification(root, instrument_id, universe_root=universe_root)
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


def _configured_record(root: Path, instrument_id: str, universe_root: Path | None = None) -> object | None:
    config_root = Path(universe_root or (root if (root / "configs").is_dir() else ROOT))
    try:
        records = load_sparebank_records(config_root, enabled_only=False)
        configured = next((item for item in records if item.instrument_id == str(instrument_id)), None)
        if configured is not None:
            return configured
    except (OSError, TypeError, ValueError):
        pass
    try:
        config = load_config(config_root / "configs")
    except (OSError, TypeError, ValueError):
        return None
    return next((item for item in config.universe.etfs if str(item.id) == str(instrument_id)), None)


def _seed_universe_classification(
    root: Path, instrument_id: str, *, universe_root: Path | None = None
) -> None:
    """Persist missing classification fields from the explicit local universe record."""

    try:
        record = _configured_record(root, instrument_id, universe_root)
        if record is None:
            return
        raw_sector = str(record.sector or "").strip()
        if not raw_sector:
            return
        canonical_sector = "financials" if raw_sector.casefold() == "banks" else raw_sector
        instrument_type = _configured_instrument_type(record)
        source_values = {
            "instrument_type": instrument_type,
            "asset_class": str(getattr(record, "asset_class", "") or ("equity" if instrument_type.casefold() in {"equity_certificate", "certificate"} else "")).strip(),
            "sector": canonical_sector,
            "trading_currency": str(record.currency or "").strip(),
        }
        normalized_type = instrument_type.casefold().replace("-", "_").replace(" ", "_")
        configured_bank = (
            normalized_type in {"equity_certificate", "certificate"}
            and str(record.region or "").strip().casefold() in {"norway", "norge", "norwegian"}
            and str(record.sector or "").strip().casefold() in {"bank", "banks", "banking"}
            and str(record.tier or "").strip().casefold() == "sparebanken"
        )
        if configured_bank:
            source_values.update(
                instrument_subtype="equity_certificate",
                special_structure="equity_certificate",
                legal_domicile="NO",
                operating_country="NO",
                issuer_type="savings_bank",
            )
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
    except ClassificationSchemaError as exc:
        # The same configured fields were already seeded earlier (only the timestamp differs): nothing to do.
        if "already exists" not in str(exc):
            log_event(
                event_type="data_write_failed",
                severity="warning",
                component="classification_projection",
                operation="seed_universe_classification",
                instrument_id=str(instrument_id),
                exception_type=type(exc).__name__,
                exception_message_redacted=str(exc),
            )
    except (OSError, TypeError, ValueError) as exc:
        log_event(
            event_type="data_write_failed",
            severity="warning",
            component="classification_projection",
            operation="seed_universe_classification",
            instrument_id=str(instrument_id),
            exception_type=type(exc).__name__,
            exception_message_redacted=str(exc),
        )


def _with_configured_instrument_type(
    projection: dict[str, object], instrument_id: str, universe_root: Path | None
) -> dict[str, object]:
    """Expose configured instrument type when a legacy identity row says ETF."""

    config_root = Path(universe_root or ROOT)
    record = _configured_record(config_root, instrument_id, config_root)
    instrument_type = _configured_instrument_type(record)
    if record is not None and instrument_type:
        projection = dict(projection)
        projection["instrument_type"] = instrument_type
        projection["configured_instrument_type"] = True
    return projection


def _configured_instrument_type(record: object | None) -> str:
    return str(
        getattr(record, "instrument_type", "")
        or getattr(record, "asset_type", "")
        or ""
    ).strip()


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
