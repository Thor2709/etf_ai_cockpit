from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from numbers import Integral
from pathlib import Path
import re
from typing import Any

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import TransactionalStore


_CHECKSUM = re.compile(r"^[0-9a-fA-F]{64}$")
_CONFIDENCE = {"exact", "normalised", "unknown"}
_STATUSES = {"active", "retracted", "superseded"}


class BitemporalError(ValueError):
    """Raised when an observation cannot be used safely for point-in-time work."""


class AmbiguousAvailabilityError(BitemporalError):
    """Raised when the application cannot prove when an observation was available."""


def _positive_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise BitemporalError("revision must be a positive integer")
    return int(value)


@dataclass(frozen=True)
class BitemporalObservation:
    observation_id: str
    dataset_id: str
    entity_id: str
    stable_id: str
    run_id: str
    value: Any
    valid_from: str
    valid_to: str | None
    published_at: str
    available_at: str
    observed_at: str
    ingested_at: str
    revised_at: str | None
    revision: int
    source_id: str
    source_checksum: str
    timezone_confidence: str
    availability_confidence: str
    status: str


@dataclass(frozen=True)
class VintageManifest:
    dataset_id: str
    decision_time: str
    observation_ids: tuple[str, ...]
    source_checksums: tuple[str, ...]
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "dataset_id": self.dataset_id,
            "decision_time": self.decision_time,
            "observation_ids": list(self.observation_ids),
            "source_checksums": list(self.source_checksums),
            "sha256": self.sha256,
        }


class BitemporalStore:
    """Append-only observation ledger with effective and decision-time dimensions."""

    def __init__(self, root: Path):
        self.store = TransactionalStore(root)

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> BitemporalStore:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def record_observation(
        self,
        *,
        dataset_id: str,
        entity_id: str,
        value: Any,
        source_id: str,
        source_checksum: str,
        revision: int,
        valid_from: str | datetime,
        available_at: str | datetime | None,
        observed_at: str | datetime,
        published_at: str | datetime,
        run_id: str,
        stable_id: str | None = None,
        valid_to: str | datetime | None = None,
        ingested_at: str | datetime | None = None,
        revised_at: str | datetime | None = None,
        timezone_confidence: str = "exact",
        availability_confidence: str = "exact",
        status: str = "active",
        require_revision_advance: bool = False,
    ) -> BitemporalObservation:
        dataset_id, entity_id, stable_id, run_id, source_id = _identities(dataset_id, entity_id, stable_id or entity_id, run_id, source_id)
        if available_at is None:
            raise AmbiguousAvailabilityError("available_at is required for point-in-time authority")
        if not _CHECKSUM.fullmatch(str(source_checksum)):
            raise BitemporalError("source_checksum must be a 64-character SHA-256 value")
        revision = _positive_revision(revision)
        if timezone_confidence not in _CONFIDENCE:
            raise BitemporalError(f"unsupported timezone_confidence: {timezone_confidence}")
        if availability_confidence not in {"exact", "inferred"}:
            raise AmbiguousAvailabilityError("availability_confidence must be exact or inferred")
        if status not in _STATUSES:
            raise BitemporalError(f"unsupported observation status: {status}")
        canonical = {
            "dataset_id": dataset_id,
            "stable_id": stable_id,
            "source_id": source_id,
            "revision": revision,
            "value": value,
            "valid_from": _timestamp(valid_from, "valid_from"),
            "valid_to": _timestamp(valid_to, "valid_to", allow_none=True),
            "published_at": _timestamp(published_at, "published_at"),
            "available_at": _timestamp(available_at, "available_at"),
            "observed_at": _timestamp(observed_at, "observed_at"),
            "ingested_at": _timestamp(ingested_at or datetime.now(timezone.utc), "ingested_at"),
            "revised_at": _timestamp(revised_at, "revised_at", allow_none=True),
            "source_checksum": str(source_checksum).lower(),
            "timezone_confidence": timezone_confidence,
            "availability_confidence": availability_confidence,
            "status": status,
        }
        observation_id = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.store.transaction() as connection:
            try:
                if require_revision_advance:
                    row = connection.execute(
                        "SELECT revision, available_at FROM bitemporal_observations WHERE dataset_id = ? AND stable_id = ? ORDER BY revision DESC, available_at DESC LIMIT 1",
                        (dataset_id, stable_id),
                    ).fetchone()
                    maximum = _positive_revision(row[0]) if row is not None else 0
                    if revision <= maximum:
                        raise BitemporalError(f"revision must advance beyond {maximum} for {stable_id}")
                    if row is not None and str(canonical["available_at"]) < str(row[1]):
                        raise BitemporalError(f"available_at cannot move backwards for {stable_id}")
                connection.execute(
                    """
                    INSERT INTO bitemporal_observations
                        (observation_id, dataset_id, entity_id, stable_id, run_id, value_json,
                         valid_from, valid_to, published_at, available_at, observed_at,
                         ingested_at, revised_at, revision, source_id, source_checksum,
                         timezone_confidence, availability_confidence, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        dataset_id,
                        entity_id,
                        stable_id,
                        run_id,
                        payload,
                        canonical["valid_from"],
                        canonical["valid_to"],
                        canonical["published_at"],
                        canonical["available_at"],
                        canonical["observed_at"],
                        canonical["ingested_at"],
                        canonical["revised_at"],
                        revision,
                        source_id,
                        canonical["source_checksum"],
                        timezone_confidence,
                        availability_confidence,
                        status,
                    ),
                )
            except Exception as exc:
                raise BitemporalError(f"observation append rejected: {type(exc).__name__}") from exc
        return BitemporalObservation(
            observation_id,
            dataset_id,
            entity_id,
            stable_id,
            run_id,
            value,
            canonical["valid_from"],
            canonical["valid_to"],
            canonical["published_at"],
            canonical["available_at"],
            canonical["observed_at"],
            canonical["ingested_at"],
            canonical["revised_at"],
            revision,
            source_id,
            canonical["source_checksum"],
            timezone_confidence,
            availability_confidence,
            status,
        )

    def observations(self, dataset_id: str | None, *, entity_id: str | None = None) -> tuple[BitemporalObservation, ...]:
        query = "SELECT * FROM bitemporal_observations"
        params: tuple[object, ...] = ()
        if dataset_id is not None:
            query += " WHERE dataset_id = ?"
            params = (str(dataset_id),)
        if entity_id is not None:
            query += " AND " if " WHERE " in query else " WHERE "
            query += "entity_id = ?"
            params += (str(entity_id),)
        query += " ORDER BY stable_id, available_at, revision, observation_id"
        return tuple(_observation(row) for row in self.store.connection.execute(query, params))

    def as_of(self, dataset_id: str, decision_time: str | datetime, *, entity_id: str | None = None) -> pd.DataFrame:
        cutoff = _timestamp(decision_time, "decision_time")
        query = "SELECT * FROM bitemporal_observations WHERE dataset_id = ? AND available_at <= ? AND timezone_confidence != 'unknown'"
        params: tuple[object, ...] = (str(dataset_id), cutoff)
        if entity_id is not None:
            query += " AND entity_id = ?"
            params += (str(entity_id),)
        query += " ORDER BY stable_id, available_at, revision, observation_id"
        rows = list(self.store.connection.execute(query, params))
        selected: dict[str, Any] = {}
        for row in rows:
            selected[str(row["stable_id"])] = row
        records = [_observation(row) for row in selected.values() if str(row["status"]) == "active"]
        return pd.DataFrame([_observation_payload(item) for item in records])

    def vintage_manifest(self, dataset_id: str, decision_time: str | datetime, *, entity_id: str | None = None) -> VintageManifest:
        selected = self.as_of(dataset_id, decision_time, entity_id=entity_id)
        observation_ids = tuple(sorted(str(value) for value in selected.get("observation_id", pd.Series(dtype=str)).tolist()))
        checksums = tuple(sorted(str(value) for value in selected.get("source_checksum", pd.Series(dtype=str)).tolist()))
        normalised_decision_time = _timestamp(decision_time, "decision_time")
        assert normalised_decision_time is not None
        content = json.dumps(
            {"dataset_id": str(dataset_id), "decision_time": normalised_decision_time, "observation_ids": observation_ids, "source_checksums": checksums},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return VintageManifest(str(dataset_id), normalised_decision_time, observation_ids, checksums, hashlib.sha256(content).hexdigest())

    def stamp_derived_frame(self, frame: pd.DataFrame, dataset_id: str, decision_time: str | datetime, *, entity_id: str | None = None) -> pd.DataFrame:
        manifest = self.vintage_manifest(dataset_id, decision_time, entity_id=entity_id)
        stamped = frame.copy()
        stamped["decision_time"] = manifest.decision_time
        stamped["source_vintage_hash"] = manifest.sha256
        return stamped

    def export_vintage_manifest(self, destination: Path, dataset_id: str, decision_time: str | datetime, *, entity_id: str | None = None) -> Path:
        manifest = self.vintage_manifest(dataset_id, decision_time, entity_id=entity_id)
        atomic_write_json(Path(destination), manifest.as_dict())
        return Path(destination)

    def record_retraction(
        self,
        observation_id: str,
        *,
        available_at: str | datetime,
        run_id: str,
        reason: str,
    ) -> BitemporalObservation:
        row = self.store.connection.execute(
            "SELECT * FROM bitemporal_observations WHERE observation_id = ?",
            (str(observation_id),),
        ).fetchone()
        if row is None:
            raise KeyError(observation_id)
        return self.record_observation(
            dataset_id=str(row["dataset_id"]),
            entity_id=str(row["entity_id"]),
            stable_id=str(row["stable_id"]),
            run_id=run_id,
            value={"retracts_observation_id": observation_id, "reason": str(reason)},
            source_id=str(row["source_id"]),
            source_checksum=str(row["source_checksum"]),
            revision=int(row["revision"]) + 1,
            valid_from=str(row["valid_from"]),
            valid_to=str(row["valid_to"]) if row["valid_to"] else None,
            published_at=available_at,
            available_at=available_at,
            observed_at=available_at,
            revised_at=available_at,
            timezone_confidence=str(row["timezone_confidence"]),
            availability_confidence="exact",
            status="retracted",
        )

    def record_supersession(
        self,
        observation_id: str,
        *,
        available_at: str | datetime,
        run_id: str,
        replacement_observation_id: str,
        reason: str,
    ) -> BitemporalObservation:
        """Append a supersession marker without mutating the superseded fact."""

        row = self.store.connection.execute(
            "SELECT * FROM bitemporal_observations WHERE observation_id = ?",
            (str(observation_id),),
        ).fetchone()
        if row is None:
            raise KeyError(observation_id)
        return self.record_observation(
            dataset_id=str(row["dataset_id"]),
            entity_id=str(row["entity_id"]),
            stable_id=str(row["stable_id"]),
            run_id=run_id,
            value={
                "supersedes_observation_id": observation_id,
                "replacement_observation_id": str(replacement_observation_id),
                "reason": str(reason),
            },
            source_id=str(row["source_id"]),
            source_checksum=str(row["source_checksum"]),
            revision=int(row["revision"]) + 1,
            valid_from=str(row["valid_from"]),
            valid_to=str(row["valid_to"]) if row["valid_to"] else None,
            published_at=available_at,
            available_at=available_at,
            observed_at=available_at,
            revised_at=available_at,
            timezone_confidence=str(row["timezone_confidence"]),
            availability_confidence="exact",
            status="superseded",
        )


def bitemporal_history_summary(entity_id: str, root: Path | None = None) -> dict[str, object]:
    root = root or ROOT
    try:
        with BitemporalStore(root) as store:
            rows = store.observations(None, entity_id=entity_id)
    except Exception as exc:
        return {"status": "unavailable", "entity_id": entity_id, "message": f"vintage history unavailable: {type(exc).__name__}"}
    if not rows:
        return {"status": "unavailable", "entity_id": entity_id, "message": "No bitemporal observations are registered for this instrument."}
    return {
        "status": "available",
        "entity_id": entity_id,
        "observation_count": len(rows),
        "active_count": sum(row.status == "active" for row in rows),
        "retracted_count": sum(row.status == "retracted" for row in rows),
        "vintages": [
            {
                "dataset_id": row.dataset_id,
                "stable_id": row.stable_id,
                "revision": row.revision,
                "available_at": row.available_at,
                "valid_from": row.valid_from,
                "status": row.status,
                "source_id": row.source_id,
                "source_checksum": row.source_checksum,
                "run_id": row.run_id,
            }
            for row in rows
        ],
    }


def _observation(row: Any) -> BitemporalObservation:
    return BitemporalObservation(
        str(row["observation_id"]),
        str(row["dataset_id"]),
        str(row["entity_id"]),
        str(row["stable_id"]),
        str(row["run_id"]),
        json.loads(str(row["value_json"])),
        str(row["valid_from"]),
        str(row["valid_to"]) if row["valid_to"] else None,
        str(row["published_at"]),
        str(row["available_at"]),
        str(row["observed_at"]),
        str(row["ingested_at"]),
        str(row["revised_at"]) if row["revised_at"] else None,
        _positive_revision(row["revision"]),
        str(row["source_id"]),
        str(row["source_checksum"]),
        str(row["timezone_confidence"]),
        str(row["availability_confidence"]),
        str(row["status"]),
    )


def _observation_payload(observation: BitemporalObservation) -> dict[str, object]:
    payload = dict(observation.__dict__)
    payload.pop("value", None)
    payload["value"] = observation.value
    return payload


def _identities(*values: str) -> tuple[str, ...]:
    cleaned = tuple(str(value).strip() for value in values)
    if any(not value for value in cleaned):
        raise BitemporalError("dataset, entity, stable, run and source identifiers are required")
    return cleaned


def _timestamp(value: str | datetime | None, label: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if value is None:
        raise BitemporalError(f"{label} is required")
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BitemporalError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise BitemporalError(f"{label} must include an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
