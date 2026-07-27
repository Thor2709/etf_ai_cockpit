"""Immutable local persistence for exact peer-cohort replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import cast

from etf_cockpit.analysis.peer_cohorts import (
    BROAD_STOCK_ADAPTER,
    PEER_COHORT_CONTRACT,
    PEER_COHORT_SCHEMA_VERSION,
    PEER_RULE_VERSION,
    AdapterDefinition,
    AdapterRegistry,
    PeerObservation,
    PeerProjection,
    build_peer_projection,
    canonical_peer_result_payload,
    peer_result_hash,
    projection_payload,
)
from etf_cockpit.data.classification import InstrumentContextV2, read_instrument_context
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
    storage_layout,
)


_TYPE = "peer_cohort_result_v1"
_META_TYPE = "peer_cohort_meta"
_META_ID = "schema"


def build_point_in_time_peer_projection(
    root: Path,
    *,
    target_instrument_id: str,
    observations: tuple[PeerObservation, ...],
    metric: str,
    target_value: float | None,
    effective_at: str,
    decision_time: str,
    registry: AdapterRegistry,
    applicable: bool,
    minimum_support: int = 3,
    bootstrap_seed: int = 0,
) -> PeerProjection:
    """Resolve ISSUE-0083 contexts at the run cutoffs, then invoke analysis."""

    target = _freeze_context(
        read_instrument_context(
            root,
            target_instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
        )
    )
    resolved = tuple(
        replace(
            item,
            context=_freeze_context(
                read_instrument_context(
                    root,
                    item.instrument_id,
                    effective_at=effective_at,
                    decision_time=decision_time,
                )
            ),
        )
        for item in observations
    )
    return build_peer_projection(
        target,
        resolved,
        metric=metric,
        target_value=target_value,
        effective_at=effective_at,
        decision_time=decision_time,
        registry=registry,
        applicable=applicable,
        minimum_support=minimum_support,
        bootstrap_seed=bootstrap_seed,
    )


def _freeze_context(context: InstrumentContextV2) -> InstrumentContextV2:
    """Retain selected exact-cutoff lineage, not later excluded store rows."""

    return replace(context, excluded_evidence_ids=())


class PeerCohortStoreError(RuntimeError):
    """Raised for immutable conflicts or corrupt peer evidence."""


class PeerCohortStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._store: TransactionalStore | None = None

    def __enter__(self) -> PeerCohortStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def _opened(self) -> TransactionalStore:
        if self._store is None:
            self._store = TransactionalStore(self._root)
            self._store.put_many(
                [(_META_TYPE, _META_ID, {"contract": PEER_COHORT_CONTRACT})],
                immutable=True,
            )
        return self._store

    def append(self, projection: PeerProjection) -> str:
        expected = peer_result_hash(projection)
        if projection.result_hash != expected:
            raise PeerCohortStoreError("peer cohort result hash is not canonical")
        # Normalise tuples and frozen containers before the immutable comparison,
        # because the shared JSON store necessarily replays them as lists.
        payload = json.loads(json.dumps(projection_payload(projection), sort_keys=True))
        envelope = {
            "contract": PEER_COHORT_CONTRACT,
            "payload": payload,
            "checksum": _hash(payload),
        }
        _decode(envelope)
        try:
            self._opened().put_many(
                [(_TYPE, _semantic_identity(payload), envelope)], immutable=True
            )
        except StorageRevisionConflict as exc:
            raise PeerCohortStoreError(str(exc)) from exc
        return projection.result_hash

    def get(self, result_hash: str) -> dict[str, object]:
        try:
            records = self._opened().list(_TYPE)
        except (StorageSchemaError, sqlite3.DatabaseError) as exc:
            raise PeerCohortStoreError(f"peer cohort store is corrupt: {exc}") from exc
        for record in records:
            payload = _decode(record.payload)
            if payload.get("result_hash") == result_hash:
                return payload
        raise KeyError(result_hash)

    def projection(
        self, instrument_id: str, *, decision_time: str | None = None
    ) -> dict[str, object]:
        try:
            rows = [_decode(record.payload) for record in self._opened().list(_TYPE)]
            dated_rows = [(row, _timestamp(row.get("decision_time"))) for row in rows]
            cutoff = _timestamp(decision_time) if decision_time is not None else None
        except (
            KeyError,
            TypeError,
            ValueError,
            StorageSchemaError,
            sqlite3.DatabaseError,
        ) as exc:
            raise PeerCohortStoreError(f"peer cohort store is corrupt: {exc}") from exc
        matches = [
            (row, row_time)
            for row, row_time in dated_rows
            if row.get("instrument_id") == str(instrument_id)
            and (cutoff is None or row_time <= cutoff)
        ]
        if not matches:
            raise KeyError(instrument_id)
        return max(
            matches,
            key=lambda item: (item[1], str(item[0]["result_hash"])),
        )[0]


def peer_cohort_store_exists(root: Path) -> bool:
    path = storage_layout(Path(root).resolve()).transactional_path
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            return (
                connection.execute(
                    "SELECT 1 FROM transactional_records WHERE entity_type=? AND entity_id=? AND deleted_at IS NULL",
                    (_META_TYPE, _META_ID),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise PeerCohortStoreError(f"peer cohort store is unreadable: {exc}") from exc


def read_peer_cohort_projection(
    root: Path, instrument_id: str, *, decision_time: str | None = None
) -> dict[str, object]:
    try:
        if not peer_cohort_store_exists(root):
            return _unavailable(instrument_id, "peer_cohort_evidence_unavailable")
        with PeerCohortStore(root) as store:
            return store.projection(instrument_id, decision_time=decision_time)
    except KeyError:
        return _unavailable(instrument_id, "peer_cohort_evidence_unavailable")
    except (PeerCohortStoreError, StorageSchemaError, OSError, ValueError):
        return _unavailable(instrument_id, "peer_cohort_evidence_invalid")


def _decode(envelope: Mapping[str, object]) -> dict[str, object]:
    if envelope.get("contract") != PEER_COHORT_CONTRACT or not isinstance(
        envelope.get("payload"), Mapping
    ):
        raise PeerCohortStoreError("unsupported peer cohort record")
    payload = dict(cast(Mapping[str, object], envelope["payload"]))
    if envelope.get("checksum") != _hash(payload):
        raise PeerCohortStoreError("peer cohort checksum mismatch")
    expected_fields = {
        "contract",
        "schema_version",
        "status",
        "instrument_id",
        "effective_at",
        "decision_time",
        "target_context",
        "universe",
        "universe_version",
        "adapter",
        "cohort",
        "metric",
        "rule_version",
        "formula_parameters",
        "warnings",
        "result_hash",
        "execution_allowed",
    }
    if (
        set(payload) != expected_fields
        or payload.get("contract") != PEER_COHORT_CONTRACT
        or payload.get("schema_version") != PEER_COHORT_SCHEMA_VERSION
        or payload.get("status") != "available"
        or payload.get("rule_version") != PEER_RULE_VERSION
        or payload.get("execution_allowed") is not False
        or payload.get("result_hash") != peer_result_hash(payload)
    ):
        raise PeerCohortStoreError("peer cohort canonical result is invalid")
    target = payload.get("target_context")
    adapter = payload.get("adapter")
    cohort = payload.get("cohort")
    if (
        not isinstance(target, Mapping)
        or not isinstance(adapter, Mapping)
        or not isinstance(cohort, Mapping)
        or target.get("instrument_id") != payload.get("instrument_id")
        or target.get("execution_allowed") is not False
        or adapter.get("execution_allowed") is not False
        or adapter.get("classification_token") != target.get("score_invalidation_token")
        or cohort.get("members") is None
    ):
        raise PeerCohortStoreError("peer cohort lineage is inconsistent")
    effective = _timestamp(payload.get("effective_at"))
    decision = _timestamp(payload.get("decision_time"))
    if (
        _timestamp(target.get("effective_at")) != effective
        or _timestamp(target.get("decision_time")) != decision
        or target.get("classification_status") in {"unresolved", "manual_review"}
        or target.get("instrument_type") != "stock"
        or target.get("asset_class") != "equity"
    ):
        raise PeerCohortStoreError("peer cohort target chronology is invalid")
    expected_adapter_lineage = _hash(
        {
            "adapter_id": adapter.get("adapter_id"),
            "adapter_version": adapter.get("adapter_version"),
            "applicable_metrics": sorted(adapter.get("applicable_metrics", [])),
            "classification_token": target.get("score_invalidation_token"),
            "classification_version": target.get("version_id"),
            "rule_version": payload.get("rule_version"),
        }
    )
    if adapter.get("lineage_hash") != expected_adapter_lineage:
        raise PeerCohortStoreError("peer cohort adapter lineage is inconsistent")
    for collection in ("observations", "parent_observations"):
        rows = cohort.get(collection)
        if not isinstance(rows, list):
            raise PeerCohortStoreError("peer cohort observations are invalid")
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(
                row.get("context"), Mapping
            ):
                raise PeerCohortStoreError("peer cohort observation is invalid")
            context = cast(Mapping[str, object], row["context"])
            if (
                _timestamp(context.get("effective_at")) != effective
                or _timestamp(context.get("decision_time")) != decision
                or context.get("execution_allowed") is not False
                or context.get("classification_status")
                in {"unresolved", "manual_review"}
            ):
                raise PeerCohortStoreError(
                    "peer cohort candidate chronology is invalid"
                )
    rebuilt = _rebuild_projection(payload)
    if canonical_peer_result_payload(rebuilt) != canonical_peer_result_payload(payload):
        raise PeerCohortStoreError("peer cohort result is not reproducible")
    return payload


def _semantic_identity(payload: Mapping[str, object]) -> str:
    metric = payload.get("metric")
    if not isinstance(metric, Mapping):
        raise PeerCohortStoreError("peer cohort metric is invalid")
    return _hash(
        {
            "contract": payload.get("contract"),
            "schema_version": payload.get("schema_version"),
            "instrument_id": payload.get("instrument_id"),
            "effective_at": payload.get("effective_at"),
            "decision_time": payload.get("decision_time"),
            "metric": metric.get("metric"),
            "universe_version": payload.get("universe_version"),
            "rule_version": payload.get("rule_version"),
        }
    )


_CONTEXT_TUPLES = {
    "strategy_labels",
    "business_model_tags",
    "revenue_regions",
    "asset_regions",
    "special_structures",
    "fallback_path",
    "evidence_ids",
    "excluded_evidence_ids",
    "override_ids",
    "source_ids",
    "invalidated_score_keys",
    "warnings",
}


def _rebuild_projection(payload: Mapping[str, object]) -> PeerProjection:
    try:
        target = _context_from_payload(payload["target_context"])
        universe_raw = payload["universe"]
        formula = payload["formula_parameters"]
        adapter = payload["adapter"]
        metric = payload["metric"]
        if (
            not isinstance(universe_raw, list)
            or not isinstance(formula, Mapping)
            or not isinstance(adapter, Mapping)
            or not isinstance(metric, Mapping)
            or set(formula)
            != {
                "minimum_support",
                "bootstrap_seed",
                "bootstrap_samples",
                "winsor_mad",
                "shrinkage_strength",
                "target_value",
                "requested_applicable",
            }
            or formula["bootstrap_samples"] != 400
            or formula["winsor_mad"] != 3.0
            or formula["shrinkage_strength"] != 5.0
        ):
            raise PeerCohortStoreError("peer cohort formula inputs are invalid")
        universe = tuple(_observation_from_payload(item) for item in universe_raw)
        definitions: list[AdapterDefinition] = []
        adapter_id = str(adapter["adapter_id"])
        if adapter_id != BROAD_STOCK_ADAPTER:
            applicable_metrics = adapter["applicable_metrics"]
            if not isinstance(applicable_metrics, list):
                raise PeerCohortStoreError("peer cohort adapter metrics are invalid")
            definitions.append(
                AdapterDefinition(
                    adapter_id,
                    str(adapter["adapter_version"]),
                    frozenset(str(item) for item in applicable_metrics),
                )
            )
        rebuilt = build_peer_projection(
            target,
            universe,
            metric=str(metric["metric"]),
            target_value=(
                None
                if formula["target_value"] is None
                else float(formula["target_value"])
            ),
            effective_at=str(payload["effective_at"]),
            decision_time=str(payload["decision_time"]),
            registry=AdapterRegistry(definitions),
            applicable=bool(formula["requested_applicable"]),
            minimum_support=int(formula["minimum_support"]),
            bootstrap_seed=int(formula["bootstrap_seed"]),
        )
        return rebuilt
    except PeerCohortStoreError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PeerCohortStoreError("peer cohort semantic inputs are corrupt") from exc


def _context_from_payload(value: object) -> InstrumentContextV2:
    if not isinstance(value, Mapping):
        raise PeerCohortStoreError("peer cohort classification context is invalid")
    expected = {item.name for item in fields(InstrumentContextV2)}
    if set(value) != expected:
        raise PeerCohortStoreError("peer cohort classification schema is invalid")
    data = dict(value)
    for name in _CONTEXT_TUPLES:
        if not isinstance(data[name], list):
            raise PeerCohortStoreError("peer cohort classification tuple is invalid")
        data[name] = tuple(data[name])
    alternatives = data["alternatives"]
    if not isinstance(alternatives, Mapping):
        raise PeerCohortStoreError("peer cohort alternatives are invalid")
    data["alternatives"] = {
        str(key): tuple(items) for key, items in alternatives.items()
    }
    if not isinstance(data["field_confidence"], Mapping):
        raise PeerCohortStoreError("peer cohort confidence lineage is invalid")
    return InstrumentContextV2(**data)


def _observation_from_payload(value: object) -> PeerObservation:
    if not isinstance(value, Mapping):
        raise PeerCohortStoreError("peer cohort observation is invalid")
    expected = {item.name for item in fields(PeerObservation)}
    if set(value) != expected:
        raise PeerCohortStoreError("peer cohort observation schema is invalid")
    data = dict(value)
    data["context"] = _context_from_payload(data["context"])
    return PeerObservation(**data)


def _unavailable(instrument_id: str, reason: str) -> dict[str, object]:
    return {
        "contract": PEER_COHORT_CONTRACT,
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_code": reason,
        "execution_allowed": False,
    }


def _hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("peer cohort decision_time is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("peer cohort decision_time requires an explicit timezone")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "PeerCohortStore",
    "PeerCohortStoreError",
    "build_point_in_time_peer_projection",
    "peer_cohort_store_exists",
    "read_peer_cohort_projection",
]
