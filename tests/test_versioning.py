from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from etf_cockpit.core.versioning import (
    VersionRegistryError,
    build_run_manifest,
    build_version_registry,
    cache_invalidation,
    load_version_registry,
    migration_plan,
    write_run_manifest,
    write_version_registry,
)


_SOURCES = {
    "configs/storage_policy.yaml": "storage_schema_version: 4\n",
    "configs/score_engine_v3.yaml": "formula_version: score-engine-v3.0.0\n",
    "configs/feature_registry.yaml": "policy_version: 2026-07-12\n",
    "configs/gate_policy.yaml": "policy_version: 2026-07-12\n",
    "configs/product_governance.yaml": "policy_version: 2026-07-12\n",
    "configs/audit_manifest.yaml": "version: 1\n",
    "configs/universe.yaml": "schema_version: 1\n",
    "configs/model_settings.yaml": "schema_version: 1\n",
    "data/derived/score_history.parquet": "historical fixture\n",
    "src/etf_cockpit/example.py": "VALUE = 1\n",
}


def _fixture_root(tmp_path: Path) -> Path:
    for relative, content in _SOURCES.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return tmp_path


def test_registry_is_deterministic_and_crlf_stable(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    first = build_version_registry(root, code_revision="fixture")
    first_hash = next(item["content_hash"] for item in first["records"] if item["artifact_id"] == "formula:score-engine-v3")

    (root / "configs/score_engine_v3.yaml").write_bytes(b"formula_version: score-engine-v3.0.0\r\n")
    second = build_version_registry(root, code_revision="fixture")

    assert first == second
    assert first_hash
    assert first["registry_signature"] == second["registry_signature"]


def test_run_manifest_resolves_exact_dependencies_and_cache_invalidates() -> None:
    registry = build_version_registry(code_revision="fixture")
    manifest = build_run_manifest(
        "score_fixture",
        ["formula:score-engine-v3", "policy:gate-policy", "model:baseline"],
        registry=registry,
    )
    changed = deepcopy(registry)
    record = next(item for item in changed["records"] if item["artifact_id"] == "formula:score-engine-v3")
    record["content_hash"] = "f" * 64

    decision = cache_invalidation(manifest, changed)
    assert manifest["immutable_after_run"] is True
    assert {item["artifact_id"] for item in manifest["dependencies"]} == {
        "formula:score-engine-v3",
        "policy:gate-policy",
        "model:baseline",
    }
    assert decision["requires_rebuild"] is True
    assert decision["changed_dependencies"] == [{"artifact_id": "formula:score-engine-v3", "reason": "content_hash_changed"}]


def test_registry_write_read_and_immutable_run_manifest(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    registry_path = write_version_registry(root, code_revision="fixture")
    registry = load_version_registry(registry_path)
    manifest_path = write_run_manifest(
        "run_fixture",
        ["formula:score-engine-v3"],
        registry=registry,
        root=root,
    )
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["execution_allowed"] is False
    assert write_run_manifest("run_fixture", ["formula:score-engine-v3"], registry=registry, root=root) == manifest_path

    with pytest.raises(VersionRegistryError, match="immutable run manifest"):
        write_run_manifest(
            "run_fixture",
            ["policy:gate-policy"],
            registry=registry,
            root=root,
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(VersionRegistryError, match="manifest signature mismatch"):
        from etf_cockpit.core.versioning import ensure_run_manifest

        ensure_run_manifest("run_fixture", ["formula:score-engine-v3"], registry=registry, root=root)


def test_migrations_are_forward_only() -> None:
    assert migration_plan("1.0.0", "1.1.0")["requires_rebuild"] is True
    assert migration_plan("1.1.0", "1.1.0")["status"] == "current"
    with pytest.raises(VersionRegistryError, match="backward"):
        migration_plan("2.0.0", "1.0.0")
