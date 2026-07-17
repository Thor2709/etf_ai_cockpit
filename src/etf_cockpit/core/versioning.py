"""Deterministic version, lineage and cache-invalidation contracts.

The registry is a local content-addressed catalogue.  It records semantic
versions and hashes together so historical runs can refer to an immutable
versioned input rather than relying on a mutable ``latest`` alias.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import DERIVED_DIR, ROOT


REGISTRY_SCHEMA_VERSION = "1.0"
REGISTRY_VERSION = "1.0.0"
VERSION_REGISTRY_PATH = DERIVED_DIR / "version_registry.json"
RUN_MANIFEST_DIR = DERIVED_DIR / "run_manifests"
_SEMVER_RE = re.compile(r"^(?:v)?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class VersionRegistryError(ValueError):
    """Raised when a registry or run manifest is invalid or unverifiable."""


@dataclass(frozen=True)
class VersionRecord:
    artifact_id: str
    kind: str
    version: str
    content_hash: str
    source: str
    available: bool
    dependencies: tuple[str, ...] = ()
    compatibility: str = "compatible"
    deprecated: bool = False
    requires_rebuild: bool = True
    metadata: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "version": self.version,
            "content_hash": self.content_hash,
            "source": self.source,
            "available": self.available,
            "dependencies": list(self.dependencies),
            "compatibility": self.compatibility,
            "deprecated": self.deprecated,
            "requires_rebuild": self.requires_rebuild,
            "metadata": dict(self.metadata or {}),
        }


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse a strict semantic version, accepting an optional ``v`` prefix."""

    match = _SEMVER_RE.fullmatch(str(value).strip())
    if match is None:
        raise VersionRegistryError(f"invalid semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def build_version_registry(root: Path | None = None, *, code_revision: str | None = None) -> dict[str, object]:
    root = Path(root) if root is not None else ROOT
    records = _build_records(root)
    graph = {
        "nodes": [record.artifact_id for record in records],
        "edges": [
            {"from": dependency, "to": record.artifact_id}
            for record in records
            for dependency in record.dependencies
        ],
    }
    payload: dict[str, object] = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_version": REGISTRY_VERSION,
        "repository_revision": str(code_revision or os.getenv("ETF_COCKPIT_REVISION") or "unknown"),
        "records": [record.as_dict() for record in records],
        "dependency_graph": graph,
        "compatibility": {
            "historical_versions_readable": True,
            "forward_only_migrations": True,
            "mutable_latest_is_not_historical_authority": True,
        },
        "immutable_after_run": True,
        "execution_allowed": False,
    }
    signature = _payload_hash(payload)
    return {**payload, "registry_signature": signature}


def write_version_registry(
    root: Path | None = None,
    *,
    code_revision: str | None = None,
) -> Path:
    root = Path(root) if root is not None else ROOT
    destination = root / "data" / "derived" / "version_registry.json"
    payload = build_version_registry(root, code_revision=code_revision)
    atomic_write_json(destination, payload)
    return destination


def load_version_registry(path: Path | None = None) -> dict[str, object]:
    candidate = Path(path) if path is not None else VERSION_REGISTRY_PATH
    if not candidate.is_file():
        raise VersionRegistryError(f"version registry is unavailable: {candidate}")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VersionRegistryError(f"version registry cannot be read: {candidate}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise VersionRegistryError("version registry has an invalid shape")
    supplied = str(payload.get("registry_signature") or "")
    unsigned = {key: value for key, value in payload.items() if key != "registry_signature"}
    if not supplied or supplied != _payload_hash(unsigned):
        raise VersionRegistryError("version registry signature mismatch")
    return payload


def build_run_manifest(
    run_id: str,
    dependency_ids: Iterable[str],
    *,
    registry: Mapping[str, object] | None = None,
    root: Path | None = None,
    code_revision: str | None = None,
) -> dict[str, object]:
    """Resolve exact version/hash references for one immutable run."""

    if not _SAFE_ID_RE.fullmatch(str(run_id).strip()):
        raise VersionRegistryError("run_id must be a safe local identifier")
    current = dict(registry) if registry is not None else build_version_registry(root, code_revision=code_revision)
    records = {
        str(item.get("artifact_id")): item
        for item in current.get("records", [])
        if isinstance(item, dict) and item.get("artifact_id")
    }
    dependencies: list[dict[str, object]] = []
    for artifact_id in sorted(set(str(item) for item in dependency_ids)):
        record = records.get(artifact_id)
        if record is None:
            raise VersionRegistryError(f"run dependency is not registered: {artifact_id}")
        if not bool(record.get("available")):
            raise VersionRegistryError(f"run dependency is unavailable: {artifact_id}")
        dependencies.append(
            {
                "artifact_id": artifact_id,
                "kind": record.get("kind"),
                "version": record.get("version"),
                "content_hash": record.get("content_hash"),
                "registry_signature": current.get("registry_signature"),
            }
        )
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "manifest_version": "1.0.0",
        "run_id": str(run_id),
        "repository_revision": current.get("repository_revision", "unknown"),
        "registry_signature": current.get("registry_signature"),
        "dependencies": dependencies,
        "immutable_after_run": True,
        "execution_allowed": False,
    }
    payload["dependency_graph_hash"] = _payload_hash(dependencies)
    payload["manifest_signature"] = _payload_hash(payload)
    return payload


def write_run_manifest(
    run_id: str,
    dependency_ids: Iterable[str],
    *,
    registry: Mapping[str, object] | None = None,
    root: Path | None = None,
    code_revision: str | None = None,
) -> Path:
    root = Path(root) if root is not None else ROOT
    payload = build_run_manifest(
        run_id,
        dependency_ids,
        registry=registry,
        root=root,
        code_revision=code_revision,
    )
    destination = root / "data" / "derived" / "run_manifests" / f"{run_id}.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing != payload:
            raise VersionRegistryError(f"immutable run manifest already exists with different content: {run_id}")
        return destination
    atomic_write_json(destination, payload)
    return destination


def ensure_run_manifest(
    run_id: str,
    dependency_ids: Iterable[str],
    *,
    registry: Mapping[str, object] | None = None,
    root: Path | None = None,
    code_revision: str | None = None,
) -> Path:
    """Return an existing immutable manifest or create it once."""

    root = Path(root) if root is not None else ROOT
    destination = root / "data" / "derived" / "run_manifests" / f"{run_id}.json"
    if destination.is_file():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or not existing.get("manifest_signature"):
            raise VersionRegistryError(f"run manifest is invalid: {destination}")
        supplied = str(existing["manifest_signature"])
        unsigned = {key: value for key, value in existing.items() if key != "manifest_signature"}
        if supplied != _payload_hash(unsigned):
            raise VersionRegistryError(f"run manifest signature mismatch: {destination}")
        return destination
    return write_run_manifest(
        run_id,
        dependency_ids,
        registry=registry,
        root=root,
        code_revision=code_revision,
    )


def cache_invalidation(
    previous_manifest: Mapping[str, object],
    current_registry: Mapping[str, object],
) -> dict[str, object]:
    """Explain whether cached output can be reused under a new registry."""

    current_records = {
        str(item.get("artifact_id")): item
        for item in current_registry.get("records", [])
        if isinstance(item, dict) and item.get("artifact_id")
    }
    changed: list[dict[str, object]] = []
    for dependency in previous_manifest.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        artifact_id = str(dependency.get("artifact_id") or "")
        current = current_records.get(artifact_id)
        reason = None
        if current is None or not bool(current.get("available")):
            reason = "dependency_unavailable"
        elif dependency.get("version") != current.get("version"):
            reason = "semantic_version_changed"
        elif dependency.get("content_hash") != current.get("content_hash"):
            reason = "content_hash_changed"
        if reason:
            changed.append({"artifact_id": artifact_id, "reason": reason})
    changed.sort(key=lambda item: str(item["artifact_id"]))
    return {
        "cache_reusable": not changed,
        "requires_rebuild": bool(changed),
        "changed_dependencies": changed,
        "current_registry_signature": current_registry.get("registry_signature"),
        "execution_allowed": False,
    }


def migration_plan(from_version: str, to_version: str) -> dict[str, object]:
    """Return an explicit forward-only migration decision for registry data."""

    source = parse_semver(from_version)
    target = parse_semver(to_version)
    if source > target:
        raise VersionRegistryError(f"backward registry migration is not supported: {from_version} -> {to_version}")
    return {
        "from_version": from_version,
        "to_version": to_version,
        "forward_only": True,
        "status": "current" if source == target else "migration_required",
        "requires_rebuild": source != target,
        "steps": [] if source == target else [f"migrate:{from_version}:{to_version}"],
    }


def compatibility_summary(registry: Mapping[str, object]) -> dict[str, object]:
    records = [item for item in registry.get("records", []) if isinstance(item, dict)]
    return {
        "registry_version": registry.get("registry_version", "unavailable"),
        "registry_signature": registry.get("registry_signature", "unavailable"),
        "record_count": len(records),
        "available_count": sum(bool(item.get("available")) for item in records),
        "unavailable_count": sum(not bool(item.get("available")) for item in records),
        "deprecated_count": sum(bool(item.get("deprecated")) for item in records),
        "rebuild_sensitive_count": sum(bool(item.get("requires_rebuild")) for item in records),
        "forward_only_migrations": True,
        "immutable_after_run": bool(registry.get("immutable_after_run")),
    }


def _build_records(root: Path) -> tuple[VersionRecord, ...]:
    specs = (
        ("schema:local-storage", "schema", "3.0.0", "configs/storage_policy.yaml", (), "storage_schema_version"),
        ("formula:score-engine-v3", "formula", "3.0.0", "configs/score_engine_v3.yaml", ("schema:local-storage",), "formula_version"),
        ("feature:feature-registry", "feature", "1.0.0", "configs/feature_registry.yaml", ("schema:local-storage",), "policy_version"),
        ("policy:gate-policy", "policy", "1.0.0", "configs/gate_policy.yaml", ("schema:local-storage",), "policy_version"),
        ("policy:product-governance", "policy", "1.0.0", "configs/product_governance.yaml", (), "policy_version"),
        ("policy:audit-manifest", "policy", "1.0.0", "configs/audit_manifest.yaml", (), "version"),
        ("policy:portfolio-targets", "policy", "1.0.0", "configs/portfolio_targets.yaml", ("dataset:universe",), "schema_version"),
        ("policy:risk-limits", "policy", "1.0.0", "configs/risk_limits.yaml", ("policy:portfolio-targets",), "schema_version"),
        ("policy:costs", "policy", "1.0.0", "configs/costs.yaml", ("policy:portfolio-targets",), "schema_version"),
        ("policy:model-settings", "policy", "1.0.0", "configs/model_settings.yaml", ("formula:score-engine-v3",), "schema_version"),
        ("policy:strategy-scope", "policy", "1.0.0", "configs/strategy_scope.yaml", ("policy:gate-policy",), "schema_version"),
        ("dataset:universe", "dataset", "1.0.0", "configs/universe.yaml", ("schema:local-storage",), "schema_version"),
        ("dataset:prices", "dataset", "1.0.0", "data/validated/prices/prices_daily.parquet", ("schema:local-storage",), None),
        ("dataset:features", "dataset", "1.0.0", "data/features/features_daily.parquet", ("dataset:prices",), None),
        ("dataset:forecasts", "dataset", "1.0.0", "data/forecasts", ("dataset:features",), None),
        ("dataset:score-history", "dataset", "1.0.0", "data/derived/score_history.parquet", ("schema:local-storage",), None),
        ("model:baseline", "model", "1.0.0", "configs/model_settings.yaml", ("formula:score-engine-v3",), "schema_version"),
        ("model:timesfm", "model", "1.0.0", "configs/model_settings.yaml", ("formula:score-engine-v3",), "schema_version"),
        ("model:toto", "model", "1.0.0", "configs/model_settings.yaml", ("formula:score-engine-v3",), "schema_version"),
        ("code:etf-cockpit", "code", "1.0.0", "src/etf_cockpit", (), None),
    )
    records: list[VersionRecord] = []
    for artifact_id, kind, version, relative_source, dependencies, metadata_key in specs:
        source_path = root / relative_source
        available = source_path.exists()
        content_hash = _hash_path(source_path) if available else ""
        metadata: dict[str, object] = {"source_version": _read_source_version(source_path, metadata_key)}
        if kind == "model":
            metadata["optional"] = artifact_id != "model:baseline"
        records.append(
            VersionRecord(
                artifact_id=artifact_id,
                kind=kind,
                version=version,
                content_hash=content_hash,
                source=relative_source,
                available=available,
                dependencies=tuple(dependencies),
                compatibility="compatible" if available else "unavailable_optional" if kind == "model" else "unavailable",
                requires_rebuild=kind not in {"code"},
                metadata=metadata,
            )
        )
    return tuple(records)


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(_hash_bytes(path))
        return digest.hexdigest()
    for child in sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    ):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_hash_bytes(child))
        digest.update(b"\0")
    return digest.hexdigest()


_TEXT_HASH_SUFFIXES = {".csv", ".json", ".md", ".py", ".txt", ".yaml", ".yml"}


def _hash_bytes(path: Path) -> bytes:
    """Normalise text line endings without altering binary artefact hashes."""

    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n") if path.suffix.casefold() in _TEXT_HASH_SUFFIXES else data


def _read_source_version(path: Path, key: str | None) -> str:
    if not key or not path.is_file():
        return "unavailable"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"\'')
    return "unavailable"


def _payload_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


__all__ = [
    "REGISTRY_SCHEMA_VERSION",
    "REGISTRY_VERSION",
    "RUN_MANIFEST_DIR",
    "VERSION_REGISTRY_PATH",
    "VersionRecord",
    "VersionRegistryError",
    "build_run_manifest",
    "build_version_registry",
    "cache_invalidation",
    "compatibility_summary",
    "ensure_run_manifest",
    "load_version_registry",
    "migration_plan",
    "parse_semver",
    "write_run_manifest",
    "write_version_registry",
]
