"""Local data catalogue, immutable snapshots and dependency lineage.

The catalogue records metadata and content hashes only.  It does not copy raw
data, fetch providers or grant execution authority.  Snapshot IDs are derived
from canonical rows and schema metadata so the same inputs produce the same
reproducible identifier.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping

from etf_cockpit.core.atomic_io import atomic_write_json


CATALOGUE_SCHEMA_VERSION = "1.0"
CATALOGUE_VERSION = "data-catalogue.v1"
CATALOGUE_RELATIVE_PATH = Path("data") / "catalogue" / "catalogue.json"
_ALLOWED_LAYERS = {"raw", "clean", "derived"}
_ALLOWED_PII = {"none", "internal", "restricted"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DataCatalogueError(ValueError):
    """Raised when catalogue metadata or lineage cannot be trusted."""


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    layer: str
    schema: Mapping[str, str]
    owner: str
    source_id: str
    licence: str
    update_schedule: str
    partitions: tuple[str, ...] = ()
    row_count: int = 0
    quality: Mapping[str, object] = field(default_factory=dict)
    pii_classification: str = "none"
    retention_days: int | None = None
    stale: bool = False

    @property
    def schema_sha256(self) -> str:
        return _hash_payload(_normalise_schema(self.schema))

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "layer": self.layer,
            "schema": dict(_normalise_schema(self.schema)),
            "schema_sha256": self.schema_sha256,
            "owner": self.owner,
            "source_id": self.source_id,
            "licence": self.licence,
            "update_schedule": self.update_schedule,
            "partitions": list(sorted(set(self.partitions))),
            "row_count": self.row_count,
            "quality": dict(self.quality or {}),
            "pii_classification": self.pii_classification,
            "retention_days": self.retention_days,
            "stale": self.stale,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> DatasetDefinition:
        schema = payload.get("schema")
        if not isinstance(schema, Mapping):
            raise DataCatalogueError("dataset schema is missing or malformed")
        quality = payload.get("quality")
        if quality is not None and not isinstance(quality, Mapping):
            raise DataCatalogueError("dataset quality metadata is malformed")
        return _validated_dataset(
            cls(
                dataset_id=str(payload.get("dataset_id") or ""),
                layer=str(payload.get("layer") or ""),
                schema={str(key): str(value) for key, value in schema.items()},
                owner=str(payload.get("owner") or ""),
                source_id=str(payload.get("source_id") or ""),
                licence=str(payload.get("licence") or ""),
                update_schedule=str(payload.get("update_schedule") or ""),
                partitions=tuple(str(item) for item in payload.get("partitions", ())),
                row_count=int(payload.get("row_count", 0)),
                quality=dict(quality or {}),
                pii_classification=str(payload.get("pii_classification") or "none"),
                retention_days=int(payload["retention_days"]) if payload.get("retention_days") is not None else None,
                stale=bool(payload.get("stale", False)),
            )
        )


@dataclass(frozen=True)
class DatasetSnapshot:
    dataset_id: str
    snapshot_id: str
    content_sha256: str
    schema_sha256: str
    row_count: int
    partitions: tuple[str, ...] = ()
    quality: Mapping[str, object] = field(default_factory=dict)
    dependency_snapshot_ids: tuple[str, ...] = ()
    coverage_ids: tuple[str, ...] = ()
    captured_at: str = ""
    stale: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "snapshot_id": self.snapshot_id,
            "content_sha256": self.content_sha256,
            "schema_sha256": self.schema_sha256,
            "row_count": self.row_count,
            "partitions": list(sorted(set(self.partitions))),
            "quality": dict(self.quality or {}),
            "dependency_snapshot_ids": list(sorted(set(self.dependency_snapshot_ids))),
            "coverage_ids": list(sorted(set(self.coverage_ids))),
            "captured_at": self.captured_at,
            "stale": self.stale,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> DatasetSnapshot:
        quality = payload.get("quality")
        if quality is not None and not isinstance(quality, Mapping):
            raise DataCatalogueError("snapshot quality metadata is malformed")
        return _validated_snapshot(
            cls(
                dataset_id=str(payload.get("dataset_id") or ""),
                snapshot_id=str(payload.get("snapshot_id") or ""),
                content_sha256=str(payload.get("content_sha256") or ""),
                schema_sha256=str(payload.get("schema_sha256") or ""),
                row_count=int(payload.get("row_count", 0)),
                partitions=tuple(str(item) for item in payload.get("partitions", ())),
                quality=dict(quality or {}),
                dependency_snapshot_ids=tuple(str(item) for item in payload.get("dependency_snapshot_ids", ())),
                coverage_ids=tuple(str(item) for item in payload.get("coverage_ids", ())),
                captured_at=str(payload.get("captured_at") or ""),
                stale=bool(payload.get("stale", False)),
            )
        )


@dataclass(frozen=True)
class LineageEdge:
    upstream_snapshot_id: str
    downstream_snapshot_id: str
    relation: str = "derived_from"

    def as_dict(self) -> dict[str, str]:
        return {
            "upstream_snapshot_id": self.upstream_snapshot_id,
            "downstream_snapshot_id": self.downstream_snapshot_id,
            "relation": self.relation,
        }


class DataCatalogue:
    """Append-only metadata catalogue stored under the configured project root."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / CATALOGUE_RELATIVE_PATH
        self._datasets: dict[str, DatasetDefinition] = {}
        self._snapshots: dict[str, DatasetSnapshot] = {}
        self._edges: set[tuple[str, str, str]] = set()
        self._load()

    @property
    def datasets(self) -> tuple[DatasetDefinition, ...]:
        return tuple(self._datasets[key] for key in sorted(self._datasets))

    @property
    def snapshots(self) -> tuple[DatasetSnapshot, ...]:
        return tuple(self._snapshots[key] for key in sorted(self._snapshots))

    @property
    def lineage(self) -> tuple[LineageEdge, ...]:
        return tuple(LineageEdge(*edge) for edge in sorted(self._edges))

    def register_dataset(self, dataset: DatasetDefinition) -> DatasetDefinition:
        dataset = _validated_dataset(dataset)
        existing = self._datasets.get(dataset.dataset_id)
        if existing is not None and existing.as_dict() != dataset.as_dict():
            raise DataCatalogueError(f"dataset definition is immutable: {dataset.dataset_id}")
        self._datasets[dataset.dataset_id] = existing or dataset
        self.save()
        return self._datasets[dataset.dataset_id]

    def register_snapshot(self, snapshot: DatasetSnapshot) -> DatasetSnapshot:
        snapshot = _validated_snapshot(snapshot)
        if snapshot.dataset_id not in self._datasets:
            raise DataCatalogueError(f"snapshot dataset is not registered: {snapshot.dataset_id}")
        existing = self._snapshots.get(snapshot.snapshot_id)
        if existing is not None:
            if _snapshot_immutable_fields(existing) != _snapshot_immutable_fields(snapshot):
                raise DataCatalogueError(f"snapshot ID is already registered with different content: {snapshot.snapshot_id}")
            return existing
        self._snapshots[snapshot.snapshot_id] = snapshot
        for dependency in snapshot.dependency_snapshot_ids:
            self._edges.add((dependency, snapshot.snapshot_id, "derived_from"))
        self.save()
        return snapshot

    def register_rows(
        self,
        dataset_id: str,
        rows: Iterable[Mapping[str, object]] | object,
        *,
        schema: Mapping[str, str] | None = None,
        partitions: Iterable[str] = (),
        quality: Mapping[str, object] | None = None,
        dependency_snapshot_ids: Iterable[str] = (),
        coverage_ids: Iterable[str] = (),
        captured_at: str | None = None,
        stale: bool = False,
    ) -> DatasetSnapshot:
        normalised_rows = _canonical_rows(rows)
        resolved_schema = _normalise_schema(schema or _infer_schema(normalised_rows))
        content_sha256 = _hash_payload(normalised_rows)
        schema_sha256 = _hash_payload(resolved_schema)
        snapshot_id = f"{dataset_id}:{content_sha256[:24]}:{schema_sha256[:16]}"
        return self.register_snapshot(
            DatasetSnapshot(
                dataset_id=dataset_id,
                snapshot_id=snapshot_id,
                content_sha256=content_sha256,
                schema_sha256=schema_sha256,
                row_count=len(normalised_rows),
                partitions=tuple(str(item) for item in partitions),
                quality=dict(quality or {}),
                dependency_snapshot_ids=tuple(str(item) for item in dependency_snapshot_ids),
                coverage_ids=tuple(str(item) for item in coverage_ids),
                captured_at=captured_at or _utc_now(),
                stale=stale,
            )
        )

    def validate(self) -> dict[str, object]:
        errors: list[str] = []
        orphan_snapshot_ids: set[str] = set()
        incompatible_dataset_ids: set[str] = set()
        stale_snapshot_ids = {snapshot.snapshot_id for snapshot in self.snapshots if snapshot.stale}
        for snapshot in self.snapshots:
            dataset = self._datasets.get(snapshot.dataset_id)
            if dataset is None:
                errors.append(f"snapshot dataset missing: {snapshot.snapshot_id}")
                orphan_snapshot_ids.add(snapshot.snapshot_id)
                continue
            if dataset.schema_sha256 != snapshot.schema_sha256:
                errors.append(f"snapshot schema is incompatible: {snapshot.snapshot_id}")
                incompatible_dataset_ids.add(dataset.dataset_id)
            for dependency in snapshot.dependency_snapshot_ids:
                if dependency not in self._snapshots:
                    errors.append(f"lineage dependency missing: {snapshot.snapshot_id} <- {dependency}")
                    orphan_snapshot_ids.add(snapshot.snapshot_id)
        errors.extend(self._cycle_errors())
        return {
            "status": "passed" if not errors else "failed",
            "error_count": len(errors),
            "errors": sorted(errors),
            "orphan_snapshot_ids": sorted(orphan_snapshot_ids),
            "incompatible_dataset_ids": sorted(incompatible_dataset_ids),
            "stale_snapshot_ids": sorted(stale_snapshot_ids),
        }

    def impact_analysis(self, snapshot_id: str) -> dict[str, object]:
        snapshot_id = str(snapshot_id).strip()
        if snapshot_id not in self._snapshots:
            raise DataCatalogueError(f"snapshot is not registered: {snapshot_id}")
        downstream: dict[str, set[str]] = {}
        for upstream, downstream_id, _relation in self._edges:
            downstream.setdefault(upstream, set()).add(downstream_id)
        affected: set[str] = set()
        queue = deque([snapshot_id])
        while queue:
            current = queue.popleft()
            for child in sorted(downstream.get(current, ())):
                if child not in affected:
                    affected.add(child)
                    queue.append(child)
        return {
            "source_snapshot_id": snapshot_id,
            "affected_snapshot_ids": sorted(affected),
            "affected_dataset_ids": sorted({self._snapshots[item].dataset_id for item in affected}),
            "execution_allowed": False,
        }

    def upstream_snapshot_graph(self, snapshot_id: str) -> dict[str, object]:
        """Return the complete registered upstream graph, failing closed on gaps."""

        snapshot_id = str(snapshot_id).strip()
        if snapshot_id not in self._snapshots:
            raise DataCatalogueError(f"snapshot is not registered: {snapshot_id}")
        included: set[str] = set()
        missing: set[str] = set()
        edges: set[tuple[str, str, str]] = set()
        queue = deque([snapshot_id])
        while queue:
            current_id = queue.popleft()
            if current_id in included:
                continue
            included.add(current_id)
            current = self._snapshots[current_id]
            for dependency_id in sorted(set(current.dependency_snapshot_ids)):
                edges.add((dependency_id, current_id, "derived_from"))
                if dependency_id not in self._snapshots:
                    missing.add(dependency_id)
                elif dependency_id not in included:
                    queue.append(dependency_id)

        nodes = [self._snapshot_node(item) for item in sorted(included)]
        stale_snapshot_ids = [str(item["snapshot_id"]) for item in nodes if item["stale"]]
        incompatible_snapshot_ids = [
            str(item["snapshot_id"]) for item in nodes if not item["schema_compatible"]
        ]
        complete = not missing and not incompatible_snapshot_ids
        return {
            "target_snapshot_id": snapshot_id,
            "status": "failed" if not complete else "degraded" if stale_snapshot_ids else "passed",
            "complete": complete,
            "nodes": nodes,
            "edges": [LineageEdge(*edge).as_dict() for edge in sorted(edges)],
            "missing_upstream_snapshot_ids": sorted(missing),
            "stale_snapshot_ids": stale_snapshot_ids,
            "incompatible_snapshot_ids": incompatible_snapshot_ids,
            "execution_allowed": False,
        }

    def downstream_impact(
        self,
        *,
        dataset_id: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, object]:
        """Project deterministic downstream impact from one dataset or source."""

        if (dataset_id is None) == (source_id is None):
            raise DataCatalogueError("exactly one of dataset_id or source_id must be provided")
        if dataset_id is not None:
            reference_id = str(dataset_id).strip()
            if reference_id not in self._datasets:
                raise DataCatalogueError(f"dataset is not registered: {reference_id}")
            reference_type = "dataset"
            direct_dataset_ids = {reference_id}
        else:
            reference_id = str(source_id).strip()
            direct_dataset_ids = {
                item.dataset_id for item in self.datasets if item.source_id == reference_id
            }
            if not direct_dataset_ids:
                raise DataCatalogueError(f"source is not registered: {reference_id}")
            reference_type = "source"

        direct_snapshot_ids = {
            item.snapshot_id for item in self.snapshots if item.dataset_id in direct_dataset_ids
        }
        downstream: dict[str, set[str]] = {}
        for upstream, downstream_id, _relation in self._edges:
            downstream.setdefault(upstream, set()).add(downstream_id)
        affected: set[str] = set()
        queue = deque(sorted(direct_snapshot_ids))
        while queue:
            for child in sorted(downstream.get(queue.popleft(), ())):
                if child in self._snapshots and child not in direct_snapshot_ids and child not in affected:
                    affected.add(child)
                    queue.append(child)
        affected_dataset_ids = {
            self._snapshots[item].dataset_id for item in affected
        } - direct_dataset_ids
        involved = direct_snapshot_ids | affected
        stale_snapshot_ids = sorted(item for item in involved if self._snapshots[item].stale)
        incompatible_snapshot_ids = sorted(
            item
            for item in involved
            if self._datasets[self._snapshots[item].dataset_id].schema_sha256
            != self._snapshots[item].schema_sha256
        )
        return {
            "reference_type": reference_type,
            "reference_id": reference_id,
            "direct_dataset_ids": sorted(direct_dataset_ids),
            "direct_snapshot_ids": sorted(direct_snapshot_ids),
            "affected_snapshot_ids": sorted(affected),
            "affected_dataset_ids": sorted(affected_dataset_ids),
            "status": "failed" if incompatible_snapshot_ids else "degraded" if stale_snapshot_ids else "passed",
            "stale_snapshot_ids": stale_snapshot_ids,
            "incompatible_snapshot_ids": incompatible_snapshot_ids,
            "execution_allowed": False,
        }

    def provenance_for(self, instrument_id: str) -> dict[str, object]:
        instrument_id = str(instrument_id or "").strip()
        direct = [snapshot.snapshot_id for snapshot in self.snapshots if instrument_id in snapshot.coverage_ids]
        included: set[str] = set(direct)
        queue = deque(direct)
        while queue:
            current = self._snapshots.get(queue.popleft())
            if current is None:
                continue
            for dependency in current.dependency_snapshot_ids:
                if dependency in self._snapshots and dependency not in included:
                    included.add(dependency)
                    queue.append(dependency)
        return {
            "instrument_id": instrument_id,
            "snapshot_ids": sorted(included),
            "dataset_ids": sorted({self._snapshots[item].dataset_id for item in included}),
            "direct_snapshot_count": len(direct),
            "execution_allowed": False,
        }

    def retention_candidates(self, before: str) -> dict[str, object]:
        """Report snapshots eligible for retention review without deleting anything."""

        try:
            cutoff = datetime.fromisoformat(str(before).replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataCatalogueError(f"retention cutoff is not an ISO timestamp: {before!r}") from exc
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        candidate_ids = []
        for snapshot in self.snapshots:
            dataset = self._datasets.get(snapshot.dataset_id)
            if dataset is None or dataset.retention_days is None or not snapshot.captured_at:
                continue
            captured_at = datetime.fromisoformat(snapshot.captured_at.replace("Z", "+00:00"))
            if captured_at < cutoff:
                candidate_ids.append(snapshot.snapshot_id)
        return {
            "before": cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "candidate_snapshot_ids": sorted(candidate_ids),
            "deletion_allowed": False,
            "execution_allowed": False,
        }

    def compaction_candidates(self, dataset_id: str, *, keep_latest: int = 1) -> dict[str, object]:
        """Report older snapshots while keeping compaction explicitly non-destructive."""

        if keep_latest < 1:
            raise DataCatalogueError("keep_latest must be at least 1")
        if dataset_id not in self._datasets:
            raise DataCatalogueError(f"dataset is not registered: {dataset_id}")
        snapshots = sorted(
            (item for item in self.snapshots if item.dataset_id == dataset_id),
            key=lambda item: (item.captured_at, item.snapshot_id),
            reverse=True,
        )
        return {
            "dataset_id": dataset_id,
            "keep_latest": keep_latest,
            "candidate_snapshot_ids": [item.snapshot_id for item in snapshots[keep_latest:]],
            "deletion_allowed": False,
            "execution_allowed": False,
        }

    def summary(self) -> dict[str, object]:
        validation = self.validate()
        return {
            "schema_version": CATALOGUE_SCHEMA_VERSION,
            "catalogue_version": CATALOGUE_VERSION,
            "status": "unavailable" if not self._datasets else "available" if validation["status"] == "passed" else "degraded",
            "dataset_count": len(self._datasets),
            "snapshot_count": len(self._snapshots),
            "lineage_edge_count": len(self._edges),
            "raw_dataset_count": sum(item.layer == "raw" for item in self.datasets),
            "clean_dataset_count": sum(item.layer == "clean" for item in self.datasets),
            "derived_dataset_count": sum(item.layer == "derived" for item in self.datasets),
            "orphan_snapshot_ids": validation["orphan_snapshot_ids"],
            "incompatible_dataset_ids": validation["incompatible_dataset_ids"],
            "stale_snapshot_ids": validation["stale_snapshot_ids"],
            "retention_policy_dataset_count": sum(item.retention_days is not None for item in self.datasets),
            "catalogue_signature": self._signature(),
            "execution_allowed": False,
        }

    def save(self) -> Path:
        payload = self._payload()
        payload["catalogue_signature"] = _hash_payload(payload)
        atomic_write_json(self.path, payload)
        return self.path

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataCatalogueError(f"catalogue cannot be read: {self.path}") from exc
        if not isinstance(payload, Mapping) or payload.get("schema_version") != CATALOGUE_SCHEMA_VERSION:
            raise DataCatalogueError("catalogue schema version is unsupported")
        supplied = str(payload.get("catalogue_signature") or "")
        unsigned = {key: value for key, value in payload.items() if key != "catalogue_signature"}
        if supplied != _hash_payload(unsigned):
            raise DataCatalogueError("catalogue signature mismatch")
        for item in payload.get("datasets", ()):
            dataset = DatasetDefinition.from_dict(item)
            self._datasets[dataset.dataset_id] = dataset
        for item in payload.get("snapshots", ()):
            snapshot = DatasetSnapshot.from_dict(item)
            self._snapshots[snapshot.snapshot_id] = snapshot
        for item in payload.get("lineage", ()):
            edge = LineageEdge(str(item["upstream_snapshot_id"]), str(item["downstream_snapshot_id"]), str(item.get("relation", "derived_from")))
            self._edges.add((edge.upstream_snapshot_id, edge.downstream_snapshot_id, edge.relation))

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": CATALOGUE_SCHEMA_VERSION,
            "catalogue_version": CATALOGUE_VERSION,
            "datasets": [item.as_dict() for item in self.datasets],
            "snapshots": [item.as_dict() for item in self.snapshots],
            "lineage": [item.as_dict() for item in self.lineage],
            "execution_allowed": False,
        }

    def _signature(self) -> str:
        return _hash_payload(self._payload())

    def _snapshot_node(self, snapshot_id: str) -> dict[str, object]:
        snapshot = self._snapshots[snapshot_id]
        dataset = self._datasets.get(snapshot.dataset_id)
        return {
            "snapshot_id": snapshot.snapshot_id,
            "dataset_id": snapshot.dataset_id,
            "stale": snapshot.stale,
            "schema_compatible": dataset is not None and dataset.schema_sha256 == snapshot.schema_sha256,
        }

    def _cycle_errors(self) -> list[str]:
        children: dict[str, set[str]] = {}
        for upstream, downstream, _relation in self._edges:
            children.setdefault(upstream, set()).add(downstream)
        visiting: set[str] = set()
        visited: set[str] = set()
        errors: list[str] = []

        def visit(node: str) -> None:
            if node in visiting:
                errors.append(f"lineage cycle detected at snapshot: {node}")
                return
            if node in visited:
                return
            visiting.add(node)
            for child in sorted(children.get(node, ())):
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in sorted(self._snapshots):
            visit(node)
        return errors


def _validated_dataset(dataset: DatasetDefinition) -> DatasetDefinition:
    if not _SAFE_ID.fullmatch(dataset.dataset_id):
        raise DataCatalogueError(f"invalid dataset_id: {dataset.dataset_id!r}")
    if dataset.layer not in _ALLOWED_LAYERS:
        raise DataCatalogueError(f"invalid dataset layer: {dataset.layer!r}")
    if not dataset.schema:
        raise DataCatalogueError(f"dataset schema is empty: {dataset.dataset_id}")
    if dataset.row_count < 0:
        raise DataCatalogueError("dataset row_count cannot be negative")
    if dataset.pii_classification not in _ALLOWED_PII:
        raise DataCatalogueError(f"invalid PII classification: {dataset.pii_classification!r}")
    if dataset.retention_days is not None and dataset.retention_days < 1:
        raise DataCatalogueError("retention_days must be positive")
    return dataset


def _validated_snapshot(snapshot: DatasetSnapshot) -> DatasetSnapshot:
    if not _SAFE_ID.fullmatch(snapshot.dataset_id):
        raise DataCatalogueError(f"invalid snapshot dataset_id: {snapshot.dataset_id!r}")
    if not snapshot.snapshot_id.startswith(f"{snapshot.dataset_id}:"):
        raise DataCatalogueError(f"snapshot ID does not identify its dataset: {snapshot.snapshot_id}")
    if not _SHA256.fullmatch(snapshot.content_sha256) or not _SHA256.fullmatch(snapshot.schema_sha256):
        raise DataCatalogueError("snapshot hashes must be SHA-256 values")
    if snapshot.row_count < 0:
        raise DataCatalogueError("snapshot row_count cannot be negative")
    if snapshot.captured_at:
        try:
            datetime.fromisoformat(snapshot.captured_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataCatalogueError("snapshot captured_at is not an ISO timestamp") from exc
    return snapshot


def _snapshot_immutable_fields(snapshot: DatasetSnapshot) -> tuple[object, ...]:
    payload = snapshot.as_dict()
    payload.pop("captured_at", None)
    return tuple((key, json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)) for key, value in sorted(payload.items()))


def _normalise_schema(schema: Mapping[str, object]) -> dict[str, str]:
    return {str(key): str(schema[key]) for key in sorted(schema)}


def _canonical_rows(rows: Iterable[Mapping[str, object]] | object) -> list[dict[str, object]]:
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict(orient="records")
    if isinstance(rows, Mapping):
        rows = [rows]
    try:
        result = [dict(row) for row in rows]  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise DataCatalogueError("snapshot rows must be mappings") from exc
    return sorted(result, key=lambda row: _canonical_json(row))


def _infer_schema(rows: list[Mapping[str, object]]) -> dict[str, str]:
    values: dict[str, object] = {}
    for row in rows:
        for key, value in row.items():
            values.setdefault(str(key), value)
    return {key: _type_name(value) for key, value in values.items()}


def _type_name(value: object) -> str:
    if value is None:
        return "nullable"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "string"


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "CATALOGUE_RELATIVE_PATH",
    "CATALOGUE_SCHEMA_VERSION",
    "CATALOGUE_VERSION",
    "DataCatalogue",
    "DataCatalogueError",
    "DatasetDefinition",
    "DatasetSnapshot",
    "LineageEdge",
]
