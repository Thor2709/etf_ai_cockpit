"""Bughunt C05-C2 (#996): feature run identity, immutable manifest bindings and cache invalidation. Fixtures only."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import etf_cockpit.application.feature_service as feature_service
from etf_cockpit.application.derived_cache import _feature_cache_binding, _price_snapshot_binding
from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.core.config import load_config
from etf_cockpit.core.versioning import (
    VersionRegistryError,
    build_version_registry,
    ensure_run_manifest,
)
from etf_cockpit.data.duckdb_store import load_features, write_features
from etf_cockpit.data import duckdb_store

_SOURCES = {
    "configs/storage_policy.yaml": "storage_schema_version: 4\n",
    "configs/universe.yaml": "schema_version: 1\n",
    "data/validated/prices/prices_daily.parquet": "price fixture\n",
}
_WINDOW = {"start_date": "2025-12-01", "end_date": "2026-01-01", "decision_time": "2026-01-01T23:59:59+00:00"}
_DEPENDENCIES = ("schema:local-storage", "dataset:prices", "dataset:universe")


def _settings(revision: str = "a") -> dict[str, object]:
    return {
        "settings_schema_version": "1",
        "settings_version": "1.0.0",
        "settings_revision": revision * 64,
        "settings_snapshot_id": f"snapshot-{revision}",
    }


def _prices(close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({"date": ["2025-01-01"], "etf_id": ["VWCE"], "adjusted_close": [close]})


def _fixture_root(tmp_path: Path) -> Path:
    for relative, content in _SOURCES.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return tmp_path


def _wire_feature_service(monkeypatch, root: Path, settings: dict[str, object], run_ids: list[str]) -> None:
    registry = build_version_registry(root, code_revision="fixture")

    def manifest(run_id, dependencies, *, settings_identity, **kwargs):
        run_ids.append(run_id)
        return ensure_run_manifest(
            run_id, dependencies, registry=registry, root=root, settings_identity=settings_identity, **kwargs
        )

    monkeypatch.setattr(feature_service, "current_settings_identity", lambda: settings)
    monkeypatch.setattr(feature_service, "ensure_run_manifest", manifest)
    monkeypatch.setattr(feature_service, "compute_features", lambda _frame, benchmark_etf_id=None: pd.DataFrame({"value": [1]}))
    monkeypatch.setattr(feature_service, "write_features", lambda _frame, **_kwargs: None)


# --- C05-C2-N001 (HIGH) ----------------------------------------------------------------------
def test_changed_prices_never_reuse_the_same_run_manifest(tmp_path, monkeypatch) -> None:
    run_ids: list[str] = []
    _wire_feature_service(monkeypatch, _fixture_root(tmp_path), _settings(), run_ids)
    service = FeatureService(load_config())

    service.compute_features(prices=_prices(100.0))
    service.compute_features(prices=_prices(101.0))  # corrected price, same date and settings

    assert run_ids[0] != run_ids[1]
    manifests = sorted((tmp_path / "data" / "derived" / "run_manifests").glob("*.json"))
    assert len(manifests) == 2


def test_unchanged_prices_and_settings_reuse_the_manifest(tmp_path, monkeypatch) -> None:
    run_ids: list[str] = []
    _wire_feature_service(monkeypatch, _fixture_root(tmp_path), _settings(), run_ids)
    service = FeatureService(load_config())

    service.compute_features(prices=_prices(100.0))
    service.compute_features(prices=_prices(100.0))

    assert run_ids[0] == run_ids[1]
    assert len(list((tmp_path / "data" / "derived" / "run_manifests").glob("*.json"))) == 1


def test_changed_settings_revision_gives_a_new_run_id(tmp_path, monkeypatch) -> None:
    run_ids: list[str] = []
    settings = _settings("a")
    _wire_feature_service(monkeypatch, _fixture_root(tmp_path), settings, run_ids)
    service = FeatureService(load_config())

    service.compute_features(prices=_prices())
    monkeypatch.setattr(feature_service, "current_settings_identity", lambda: _settings("b"))
    service.compute_features(prices=_prices())

    assert run_ids[0] != run_ids[1]


def test_existing_manifest_with_different_dataset_bindings_is_rejected(tmp_path) -> None:
    root = _fixture_root(tmp_path)
    registry = build_version_registry(root, code_revision="fixture")
    old = {"dataset:prices": {"price_snapshot_checksum": "1" * 64}}
    new = {"dataset:prices": {"price_snapshot_checksum": "2" * 64}}
    kwargs = {"registry": registry, "root": root, "settings_identity": _settings()}

    path = ensure_run_manifest("features_x", _DEPENDENCIES, dataset_bindings=old, **kwargs)
    assert ensure_run_manifest("features_x", _DEPENDENCIES, dataset_bindings=old, **kwargs) == path
    with pytest.raises(VersionRegistryError, match="different dataset bindings"):
        ensure_run_manifest("features_x", _DEPENDENCIES, dataset_bindings=new, **kwargs)
    with pytest.raises(VersionRegistryError, match="different dataset bindings"):
        ensure_run_manifest("features_x", _DEPENDENCIES, **kwargs)


# --- C05-C2-N002 / N003 (MEDIUM) -------------------------------------------------------------
def _cached_features(tmp_path, *, settings_revision: str = "s1"):
    path = tmp_path / "features.parquet"
    prices = pd.DataFrame({"date": ["2026-01-01"], "etf_id": ["A"], "adjusted_close": [1.0], "volume": [10.0]})
    price_binding = _price_snapshot_binding(prices, calculation_window=_WINDOW)
    assert price_binding is not None
    extra = _feature_cache_binding(prices, calculation_window=_WINDOW)
    features = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "etf_id": ["A"], "x": [1.0]})
    write_features(
        features,
        path,
        cache_metadata={"universe_revision": "u1", "settings_revision": settings_revision, **price_binding, **extra},
    )
    return path, prices, price_binding, extra


def test_feature_cache_unchanged_inputs_are_reused(tmp_path) -> None:
    path, _, price_binding, extra = _cached_features(tmp_path)
    loaded = load_features(
        path, universe_revision="u1", settings_revision="s1", price_binding=price_binding, extra_binding=extra
    )
    assert len(loaded) == 1


def test_feature_cache_invalidated_by_upstream_price_change(tmp_path) -> None:
    path, prices, _, extra = _cached_features(tmp_path)
    revised = _price_snapshot_binding(prices.assign(adjusted_close=[1.5]), calculation_window=_WINDOW)
    assert revised is not None
    assert load_features(
        path, universe_revision="u1", settings_revision="s1", price_binding=revised, extra_binding=extra
    ).empty
    # A price-only lookup (no revision arguments) must not skip the stored identity either.
    assert load_features(path, price_binding=revised).empty


def test_feature_cache_invalidated_by_settings_revision_when_only_bindings_are_supplied(tmp_path, monkeypatch) -> None:
    path, _, price_binding, extra = _cached_features(tmp_path, settings_revision="s1")
    monkeypatch.setattr(duckdb_store, "current_settings_revision", lambda: "s2")
    assert load_features(path, price_binding=price_binding).empty
    assert load_features(path, extra_binding=extra).empty
    monkeypatch.setattr(duckdb_store, "current_settings_revision", lambda: "s1")
    assert not load_features(path, price_binding=price_binding).empty


def test_feature_cache_invalidated_by_universe_or_settings_revision(tmp_path) -> None:
    path, _, price_binding, extra = _cached_features(tmp_path)
    for universe, settings in (("u2", "s1"), ("u1", "s2")):
        assert load_features(
            path, universe_revision=universe, settings_revision=settings, price_binding=price_binding, extra_binding=extra
        ).empty
