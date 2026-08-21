from __future__ import annotations

import hashlib
import json
import os
import threading
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from typing import Literal

import pandas as pd
import pytest
import etf_cockpit.models.forecast_scores as forecast_scores
import etf_cockpit.services as services_module
from etf_cockpit.app import state as app_state_module
from etf_cockpit.app.pages import dashboard as dashboard_module
from etf_cockpit.app.state import AppState

from etf_cockpit.application.benchmark_reference import (
    CanonicalReferenceContext,
    clip_to_decision_window,
    resolve_canonical_reference,
    unavailable_reference_projection,
    validate_benchmark_reference,
    adjusted_price_snapshot_binding,
)
from etf_cockpit.application.validation import _clip_to_reference_window
from etf_cockpit.backtest.engine import (
    BacktestDataUnavailableError,
    _declared_calculation_window,
    _validated_benchmark_data_id,
    backtest_input_checksum,
    run_backtest,
)
from etf_cockpit.core import atomic_io
from etf_cockpit.operations.recovery import recover_incomplete_transactions
from etf_cockpit.features.regime import (
    _average_correlation,
    _candidate_pct_above_sma200,
    build_benchmark_attribution_lookup,
    build_market_regime,
    build_portfolio_fit_lookup,
)
from etf_cockpit.features.macro import build_macro_context
from etf_cockpit.services import (
    _cache_matches_universe,
    _cached_backtest_binding_matches,
    _forecast_request_identity,
    _read_bound_cache_payload,
    _reference_binding,
    _reference_identity_hash,
    _postprocess_forecast_benchmark_fields,
    _write_bound_cache_group,
    _write_universe_cache_metadata,
)
from etf_cockpit.data.duckdb_store import load_features, write_features
from etf_cockpit.data.trade_candidate_analysis import (
    load_candidate_price_binding,
    write_candidate_price_snapshot,
)
from etf_cockpit.models.forecast_scores import (
    configured_forecast_request_identity,
    filter_forecasts_for_universe,
    latest_forecast_file,
    load_latest_forecasts,
)
from etf_cockpit.services import SignalService
from etf_cockpit.signals import simple_scores as simple_scores_module
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores
from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.portfolio.benchmark_reference_contract import (
    AnalysisDeclaration,
    AnalysisResolution,
    BenchmarkDefinition,
    BenchmarkReferenceError,
    CashProxyDefinition,
    CanonicalBenchmarkRegistry,
    PeerSetDefinition,
    ReferencePortfolioDefinition,
    Selection,
    load_canonical_benchmark_registry,
    unavailable_reference_projection as contract_unavailable_reference_projection,
)
from etf_cockpit.portfolio.attribution import (
    _benchmark_attribution,
    _unavailable_reference_projection as attribution_unavailable_reference_projection,
    build_performance_attribution,
)


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=260)
    return pd.DataFrame(
        [
            {"date": dt, "etf_id": instrument, "adjusted_close": 100.0 + index * slope}
            for instrument, slope in (("ALT", 0.10), ("BENCH", 0.20))
            for index, dt in enumerate(dates)
        ]
    )


def _available_reference(
    *,
    peer: bool = True,
    benchmark_data_id: str = "BENCH",
    benchmark_constituents: tuple[str, ...] | None = None,
) -> dict[str, object]:
    registry = _available_registry(benchmark_constituents or benchmark_data_id)
    benchmark = registry.benchmarks[0]
    cash = registry.cash_proxies[0]
    peer_set = registry.peer_sets[0]
    reference = registry.reference_portfolios[0]
    peer_record = {
        "status": "available" if peer else "unavailable",
        "id": peer_set.peer_set_id if peer else None,
        "version": peer_set.version if peer else None,
        "content_hash": peer_set.digest() if peer else None,
        "member_instrument_ids": ["PEER"] if peer else [],
    }
    return {
        "status": "available",
        "analysis_id": "analysis:test",
        "purpose": "comparison",
        "registry_hash": registry.as_payload()["registry_hash"],
        "benchmark_data_id": benchmark_data_id,
        "benchmark": {
            "status": "available",
            "id": benchmark.benchmark_id,
            "version": benchmark.version,
            "content_hash": benchmark.digest(),
        },
        "cash": {
            "status": "available",
            "id": cash.proxy_id,
            "version": cash.version,
            "content_hash": cash.digest(),
        },
        "peer_set": peer_record,
        "references": [{
            "id": reference.portfolio_id,
            "version": reference.version,
            "method": reference.method,
            "content_hash": reference.digest(),
            "constituent_instrument_ids": list(reference.constituent_instrument_ids),
            "current_weights": None,
            "effective_at": pd.Timestamp(reference.effective_at).isoformat(),
            "known_at": pd.Timestamp(reference.known_at).isoformat(),
            "source_hashes": list(reference.source_hashes),
        }],
        "selected_records": {
            "benchmark": benchmark.digest(),
            "cash": cash.digest(),
            "peer_set": peer_set.digest() if peer else None,
            "references": {f"{reference.portfolio_id}@{reference.version}": reference.digest()},
        },
        "analysis": {
            "instrument_id": "ETF",
            "currency": "EUR",
            "horizon_years": 1.0,
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "decision_time": "2026-01-01T00:00:00Z",
        },
        "execution_allowed": False,
    }


def test_relative_consumers_require_explicit_canonical_benchmark_and_cash_resolution() -> None:
    prices = _prices()
    assert build_market_regime(prices)["regime_score_10"] is None
    assert all(row["score"] is None for row in build_portfolio_fit_lookup(prices).values())
    assert all(row["benchmark_return"] is None for row in build_benchmark_attribution_lookup(prices).values())

    reordered = prices.sort_values(["date", "etf_id"], ascending=[True, False])
    reference = _available_reference()
    first = build_benchmark_attribution_lookup(
        reordered,
        benchmark_id="BENCH",
        benchmark_reference=reference,
        benchmark_registry=_available_registry(),
    )
    second = build_benchmark_attribution_lookup(
        prices,
        benchmark_id="BENCH",
        benchmark_reference=reference,
        benchmark_registry=_available_registry(),
    )
    assert first["ALT"]["benchmark_id"] == second["ALT"]["benchmark_id"] == "BENCH"
    assert first["ALT"]["benchmark_return"] == second["ALT"]["benchmark_return"]


def test_unavailable_reference_shapes_are_identical_and_execution_disabled() -> None:
    shapes = [
        unavailable_reference_projection(),
        contract_unavailable_reference_projection(),
        attribution_unavailable_reference_projection(),
    ]
    assert {tuple(sorted(item)) for item in shapes} == {tuple(sorted(shapes[0]))}
    for item in shapes:
        assert item["execution_allowed"] is False
        assert item["benchmark"]["display"] == "N/A"
        assert item["cash"]["display"] == "N/A"
        assert item["peer_set"]["display"] == "N/A"


def test_reference_context_rejects_forged_authority_and_rebuilds_fresh_projection() -> None:
    registry = CanonicalBenchmarkRegistry()
    with pytest.raises(BenchmarkReferenceError):
        CanonicalReferenceContext(
            registry,
            None,
            {"nested": {"execution_allowed": True}},
        )
    context = CanonicalReferenceContext(registry)
    projection = context.projection
    projection["execution_allowed"] = True
    assert context.projection["execution_allowed"] is False


def test_cache_metadata_requires_matching_canonical_reference_identity(tmp_path) -> None:
    path = tmp_path / "forecast.csv"
    path.write_text("etf_id\nBENCH\n", encoding="utf-8")
    identity = {
        "schema": "benchmark-reference-cache.v1",
        "status": "unavailable",
        "registry_hash": "unavailable",
        "benchmark_data_id": None,
        "selected_records": {},
        "calculation_schema": "canonical-benchmark-cash.v1",
        "execution_allowed": False,
    }
    _write_universe_cache_metadata(path, "universe", "settings", identity)
    assert _cache_matches_universe(path, "universe", "settings", identity)
    assert not _cache_matches_universe(path, "universe", "settings", {**identity, "status": "available"})
    legacy = tmp_path / "legacy.csv"
    legacy.write_text("etf_id\nBENCH\n", encoding="utf-8")
    _write_universe_cache_metadata(legacy, "universe", "settings")
    assert not _cache_matches_universe(legacy, "universe", "settings", identity)


def test_derived_caches_invalidate_after_adjusted_price_revision(tmp_path) -> None:
    identity = _cache_identity()
    prices = pd.DataFrame(
        [
            {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
            {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
        ]
    )
    window = {
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
        "decision_time": "2025-01-02T23:59:59Z",
    }
    binding = services_module._price_snapshot_binding(prices, calculation_window=window)
    assert binding is not None
    forecast_path = tmp_path / "forecast_results_20250102.csv"
    _write_bound_cache_group(
        forecast_path,
        b"etf_id,expected_return\nETF,0.01\n",
        lambda candidate: pd.read_csv(candidate),
        "u1",
        "s1",
        identity,
        binding,
    )
    metadata = json.loads(forecast_path.with_name(f"{forecast_path.name}.meta.json").read_text(encoding="utf-8"))
    assert metadata["price_snapshot_checksum"] == binding["price_snapshot_checksum"]
    assert metadata["price_snapshot_revision"] == binding["price_snapshot_revision"]
    assert metadata["effective_cutoff"] == window["decision_time"]
    assert _cache_matches_universe(forecast_path, "u1", "s1", identity, binding)
    revised = prices.assign(adjusted_close=[100.0, 102.0])
    revised_binding = services_module._price_snapshot_binding(revised, calculation_window=window)
    assert revised_binding is not None
    assert revised_binding["price_snapshot_revision"] != binding["price_snapshot_revision"]
    assert not _cache_matches_universe(forecast_path, "u1", "s1", identity, revised_binding)
    assert _read_bound_cache_payload(forecast_path, "u1", "s1", identity, revised_binding) is None

    feature_path = tmp_path / "features.parquet"
    write_features(
        pd.DataFrame([{"date": "2025-01-02", "etf_id": "ETF", "value": 1.0}]),
        feature_path,
        cache_metadata={
            "universe_revision": "u1",
            "settings_revision": "s1",
            "reference_identity": identity,
            **binding,
        },
    )
    assert load_features(
        feature_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
        price_binding=revised_binding,
    ).empty


def test_feature_and_forecast_services_clip_to_exact_declared_window(monkeypatch, tmp_path) -> None:
    declaration = SimpleNamespace(
        start_date="2025-01-01",
        end_date="2025-01-02",
        decision_time="2025-01-02T12:00:00Z",
    )
    context = SimpleNamespace(
        resolution=SimpleNamespace(declaration=declaration),
        benchmark_data_id=None,
        identity=_cache_identity(),
        projection={},
    )
    prices = pd.DataFrame(
        [
            {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
            {"date": "2025-01-02 12:00:00Z", "etf_id": "ETF", "adjusted_close": 101.0},
            {"date": "2025-01-02 20:00:00Z", "etf_id": "ETF", "adjusted_close": 102.0},
        ]
    )
    monkeypatch.setattr(services_module, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    captured_features: list[pd.DataFrame] = []
    monkeypatch.setattr(
        services_module,
        "compute_features",
        lambda frame, benchmark_etf_id=None: captured_features.append(frame.copy()) or frame,
    )
    monkeypatch.setattr(services_module, "write_features", lambda *_args, **_kwargs: None)
    services_module.FeatureService(load_config(), reference_context=context).compute_features(
        date(2025, 1, 2), prices, reference_context=context,
    )
    assert captured_features[0]["date"].astype(str).tolist() == ["2025-01-01", "2025-01-02 12:00:00Z"]

    captured_forecast_dates: list[list[str]] = []
    monkeypatch.setattr(
        services_module,
        "baseline_forecast",
        lambda _etf_id, series, *_args, **_kwargs: captured_forecast_dates.append([str(value) for value in series.index]) or [],
    )
    service = services_module.ForecastService(load_config(), reference_context=context)
    monkeypatch.setattr(service, "_run_timesfm_forecasts", lambda *_args: [])
    monkeypatch.setattr(service, "_run_toto_forecasts", lambda *_args: [])
    monkeypatch.setattr(service, "_write_forecasts", lambda *_args, **_kwargs: None)
    service.run_forecasts(date(2025, 1, 2), ["ETF"], prices, horizons=[1])
    assert captured_forecast_dates == [["2025-01-01 00:00:00+00:00", "2025-01-02 12:00:00+00:00"]]


def test_forecast_readers_require_matching_reference_identity(tmp_path) -> None:
    path = tmp_path / "forecast_results_20250101.csv"
    path.write_text("etf_id,expected_return\nBENCH,0.01\n", encoding="utf-8")
    identity = {
        "schema": "benchmark-reference-cache.v1",
        "status": "unavailable",
        "registry_hash": "unavailable",
        "benchmark_data_id": None,
        "selected_records": {},
        "calculation_schema": "canonical-benchmark-cash.v1",
        "execution_allowed": False,
    }
    from etf_cockpit.models.forecast_scores import _reference_identity_hash
    request_identity = _forecast_request_identity(load_config(), [60], live_optional_models=False)

    metadata = {
        "universe_revision": "universe",
        "settings_revision": "settings",
        "reference_identity": identity,
        "reference_identity_hash": _reference_identity_hash(identity),
        "payload_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "forecast_request_identity": request_identity,
        "forecast_request_identity_hash": _reference_identity_hash(request_identity),
    }
    path.with_name(f"{path.name}.meta.json").write_text(json.dumps(metadata), encoding="utf-8")
    exact = {"source_file": str(path), "etf_id": "BENCH"}
    assert latest_forecast_file(
        directory=tmp_path,
        pattern="forecast_results_*.csv",
        universe_revision="universe",
        settings_revision="settings",
        reference_identity=identity,
        forecast_request_identity=request_identity,
    ) == path
    loaded = load_latest_forecasts(
        directory=tmp_path,
        pattern="forecast_results_*.csv",
        universe_revision="universe",
        settings_revision="settings",
        reference_identity=identity,
        forecast_request_identity=request_identity,
    )
    assert len(loaded) == 1
    assert filter_forecasts_for_universe(
        pd.DataFrame([exact]),
        "universe",
        "settings",
        reference_identity={**identity, "status": "available"},
        forecast_request_identity=request_identity,
    ).empty
    assert len(
        filter_forecasts_for_universe(
            pd.DataFrame([exact]),
            "universe",
            "settings",
            reference_identity=identity,
            forecast_request_identity=request_identity,
        )
    ) == 1


def test_forecast_readers_reject_legacy_metadata(tmp_path) -> None:
    path = tmp_path / "forecast_results_20250101.csv"
    path.write_text("etf_id,expected_return\nBENCH,0.01\n", encoding="utf-8")
    path.with_name(f"{path.name}.meta.json").write_text(
        json.dumps({"universe_revision": "universe", "settings_revision": "settings"}),
        encoding="utf-8",
    )
    identity = {"schema": "benchmark-reference-cache.v1", "execution_allowed": False}
    assert latest_forecast_file(
        directory=tmp_path,
        pattern="forecast_results_*.csv",
        universe_revision="universe",
        settings_revision="settings",
        reference_identity=identity,
    ) is None


def test_source_less_forecast_rows_are_rejected_when_reference_bound() -> None:
    identity = {"schema": "benchmark-reference-cache.v1", "execution_allowed": False}
    rows = pd.DataFrame([{"etf_id": "BENCH", "expected_return": 0.01}])
    assert filter_forecasts_for_universe(rows, "universe", "settings", reference_identity=identity).empty


def test_feature_reader_requires_universe_settings_and_reference_sidecar(tmp_path) -> None:
    path = tmp_path / "features.parquet"
    pd.DataFrame([{"date": "2025-01-01", "etf_id": "BENCH"}]).to_parquet(path, index=False)
    identity = {"schema": "benchmark-reference-cache.v1", "execution_allowed": False}
    metadata = {
        "universe_revision": "u1",
        "settings_revision": "s1",
        "reference_identity": identity,
        "reference_identity_hash": _reference_identity_hash(identity),
        "payload_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    path.with_name(f"{path.name}.meta.json").write_text(json.dumps(metadata), encoding="utf-8")
    assert load_features(path, universe_revision="u2", settings_revision="s1", reference_identity=identity).empty
    assert load_features(path, universe_revision="u1", settings_revision="s2", reference_identity=identity).empty
    loaded = load_features(path, universe_revision="u1", settings_revision="s1", reference_identity=identity)
    assert len(loaded) == 1


def test_bound_feature_reader_rejects_checksum_valid_payload_without_date_schema(tmp_path) -> None:
    path = tmp_path / "features.parquet"
    pd.DataFrame([{"etf_id": "BENCH", "value": 1.0}]).to_parquet(path, index=False)
    identity = _cache_identity()
    metadata = {
        "universe_revision": "u1",
        "settings_revision": "s1",
        "reference_identity": identity,
        "reference_identity_hash": _reference_identity_hash(identity),
        "payload_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    path.with_name(f"{path.name}.meta.json").write_text(json.dumps(metadata), encoding="utf-8")

    assert load_features(path, universe_revision="u1", settings_revision="s1", reference_identity=identity).empty


def _cache_identity() -> dict[str, object]:
    return {
        "schema": "benchmark-reference-cache.v1",
        "status": "unavailable",
        "registry_hash": "unavailable",
        "benchmark_data_id": None,
        "selected_records": {},
        "calculation_schema": "canonical-benchmark-cash.v1",
        "execution_allowed": False,
    }


def _available_registry(
    benchmark_data_id: str | tuple[str, ...] = "BENCH",
    *,
    benchmark_status: Literal["available", "unavailable"] = "available",
    cash_status: Literal["available", "unavailable"] = "available",
    peer_status: Literal["available", "unavailable"] = "available",
) -> CanonicalBenchmarkRegistry:
    benchmark_constituents = (
        (benchmark_data_id,) if isinstance(benchmark_data_id, str) else benchmark_data_id
    )
    common = {
        "version": "1.0.0",
        "selector": {"asset_class": "equity"},
        "effective_at": "2020-01-01T00:00:00Z",
        "known_at": "2020-01-02T00:00:00Z",
        "methodology": "test authority",
        "source_hashes": ("a" * 64,),
    }
    return CanonicalBenchmarkRegistry(
        benchmarks=(BenchmarkDefinition(
            benchmark_id="benchmark:test",
            hierarchy="asset",
            currency="EUR",
            minimum_horizon_years=0.1,
            maximum_horizon_years=50.0,
            start_date="2020-01-01",
            end_date="2100-12-31",
            constituents=benchmark_constituents,
            status=benchmark_status,
            **common,
        ),),
        cash_proxies=(CashProxyDefinition(
            proxy_id="cash:test",
            currency="EUR",
            minimum_horizon_years=0.1,
            maximum_horizon_years=50.0,
            start_date="2020-01-01",
            end_date="2100-12-31",
            status=cash_status,
            **common,
        ),),
        peer_sets=(PeerSetDefinition(
            peer_set_id="peers:test",
            hierarchy="asset",
            member_instrument_ids=("PEER",),
            status=peer_status,
            **common,
        ),),
        reference_portfolios=(ReferencePortfolioDefinition(
            portfolio_id="reference:test",
            version="1.0.0",
            method="equal_weight",
            constituent_instrument_ids=benchmark_constituents,
            methodology="test authority",
            effective_at="2020-01-01T00:00:00Z",
            known_at="2020-01-02T00:00:00Z",
            source_hashes=("a" * 64,),
            currency="EUR",
            minimum_horizon_years=0.1,
            maximum_horizon_years=50.0,
            start_date="2020-01-01",
            end_date="2100-12-31",
        ),),
    )


def _typed_context_with_registry_status(
    unavailable_kind: Literal["benchmark", "cash", "peer"],
) -> CanonicalReferenceContext:
    registry = _available_registry(
        benchmark_status="unavailable" if unavailable_kind == "benchmark" else "available",
        cash_status="unavailable" if unavailable_kind == "cash" else "available",
        peer_status="unavailable" if unavailable_kind == "peer" else "available",
    )
    benchmark = registry.benchmarks[0]
    cash = registry.cash_proxies[0]
    peer = registry.peer_sets[0]
    reference = registry.reference_portfolios[0]
    declaration = AnalysisDeclaration(
        "analysis:typed-inconsistent",
        "comparison",
        "ETF",
        "EUR",
        1.0,
        "2025-01-01",
        "2025-12-31",
        "2025-12-31T23:59:59Z",
        benchmark.benchmark_id,
        cash.proxy_id,
        peer.peer_set_id,
        (reference.portfolio_id,),
    )
    resolution = AnalysisResolution(
        declaration,
        Selection(
            "benchmark", "available", benchmark.benchmark_id, benchmark.version, None,
            content_hash=benchmark.digest(),
        ),
        Selection(
            "cash", "available", cash.proxy_id, cash.version, None,
            content_hash=cash.digest(),
        ),
        Selection(
            "peer", "available", peer.peer_set_id, peer.version, None,
            content_hash=peer.digest(),
        ),
        (reference,),
        (),
    )
    return CanonicalReferenceContext(registry, resolution)


@pytest.mark.parametrize("unavailable_kind", ["benchmark", "cash", "peer"])
def test_typed_context_cannot_project_registry_record_marked_unavailable(
    unavailable_kind: Literal["benchmark", "cash", "peer"],
) -> None:
    context = _typed_context_with_registry_status(unavailable_kind)

    assert context.projection["status"] == "unavailable"
    assert context.projection["blockers"] == ["reference_projection_invalid"]
    assert _reference_binding(context)["benchmark_strategy"] == "unavailable"
    assert context.benchmark_data_id is None


def test_feature_and_forecast_consumers_cannot_use_unavailable_typed_benchmark(
    monkeypatch,
) -> None:
    context = _typed_context_with_registry_status("benchmark")
    prices = pd.DataFrame([
        {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
        {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
        {"date": "2025-01-01", "etf_id": "BENCH", "adjusted_close": 100.0},
        {"date": "2025-01-02", "etf_id": "BENCH", "adjusted_close": 102.0},
    ])
    captured: dict[str, object] = {}
    monkeypatch.setattr(services_module, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        services_module,
        "compute_features",
        lambda frame, benchmark_etf_id=None: captured.update(
            feature_benchmark=benchmark_etf_id,
        ) or frame,
    )
    monkeypatch.setattr(services_module, "write_features", lambda *_args, **_kwargs: None)
    services_module.FeatureService(load_config(), reference_context=context).compute_features(
        date(2025, 1, 2), prices,
    )

    def capture_baseline(*_args, **kwargs):
        captured["forecast_benchmark_returns"] = kwargs["benchmark_returns"]
        return []

    monkeypatch.setattr(services_module, "baseline_forecast", capture_baseline)
    forecast_service = services_module.ForecastService(load_config(), reference_context=context)
    monkeypatch.setattr(forecast_service, "_run_timesfm_forecasts", lambda *_args: [])
    monkeypatch.setattr(forecast_service, "_run_toto_forecasts", lambda *_args: [])
    monkeypatch.setattr(forecast_service, "_write_forecasts", lambda *_args, **_kwargs: None)
    forecast_service.run_forecasts(date(2025, 1, 2), ["ETF"], prices, horizons=[1])

    assert captured == {
        "feature_benchmark": None,
        "forecast_benchmark_returns": None,
    }


def test_feature_and_forecast_pair_round_trip_rejects_payload_substitution(tmp_path) -> None:
    identity = _cache_identity()
    request_identity = _forecast_request_identity(load_config(), [60], live_optional_models=False)
    feature_path = tmp_path / "features.parquet"
    features = pd.DataFrame([{"date": "2025-01-01", "etf_id": "BENCH", "value": 1.0}])
    write_features(
        features,
        feature_path,
        cache_metadata={
            "universe_revision": "u1",
            "settings_revision": "s1",
            "reference_identity": identity,
            "reference_identity_hash": _reference_identity_hash(identity),
        },
    )
    assert len(load_features(feature_path, universe_revision="u1", settings_revision="s1", reference_identity=identity)) == 1
    replacement = pd.DataFrame([{"date": "2025-01-01", "etf_id": "FORGED", "value": 99.0}])
    replacement.to_parquet(feature_path, index=False)
    assert load_features(feature_path, universe_revision="u1", settings_revision="s1", reference_identity=identity).empty

    forecast_path = tmp_path / "forecast_results_20250101.csv"
    payload = b"etf_id,expected_return\nBENCH,0.01\n"
    _write_bound_cache_group(
        forecast_path,
        payload,
        lambda candidate: pd.read_csv(candidate),
        "u1",
        "s1",
        identity,
        forecast_request_identity=request_identity,
    )
    assert latest_forecast_file(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
        forecast_request_identity=request_identity,
    ) == forecast_path
    forecast_path.write_bytes(b"etf_id,expected_return\nFORGED,0.99\n")
    assert latest_forecast_file(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
        forecast_request_identity=request_identity,
    ) is None


def test_legacy_unbound_feature_read_remains_available_without_binding_request(tmp_path) -> None:
    feature_path = tmp_path / "features.parquet"
    pd.DataFrame([{"date": "2025-01-01", "etf_id": "LEGACY", "value": 1.0}]).to_parquet(
        feature_path, index=False
    )

    assert load_features(feature_path)["etf_id"].tolist() == ["LEGACY"]
    assert load_features(feature_path, universe_revision="u1").empty

    forecast_path = tmp_path / "forecast_results_20250101.csv"
    forecast_path.write_text("etf_id,expected_return\nLEGACY,0.01\n", encoding="utf-8")
    assert load_latest_forecasts(directory=tmp_path)["etf_id"].tolist() == ["LEGACY"]
    assert load_latest_forecasts(directory=tmp_path, universe_revision="u1").empty


def test_feature_pair_crash_rolls_back_without_exposing_intermediate_state(tmp_path, monkeypatch) -> None:
    identity = _cache_identity()
    path = tmp_path / "features.parquet"
    old = pd.DataFrame([{"date": "2025-01-01", "etf_id": "OLD", "value": 1.0}])
    new = pd.DataFrame([{"date": "2025-01-01", "etf_id": "NEW", "value": 2.0}])
    binding = {"universe_revision": "u1", "settings_revision": "s1", "reference_identity": identity}
    write_features(old, path, cache_metadata=binding)

    real_group = atomic_io.atomic_write_group

    def interrupted(requests):
        return real_group(requests, lifecycle_hook=lambda state, _journal: (_ for _ in ()).throw(atomic_io.AtomicWriteInterrupted(state)) if state == "committing" else None)

    monkeypatch.setattr("etf_cockpit.data.duckdb_store.atomic_write_group", interrupted)
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        write_features(new, path, cache_metadata=binding)
    assert recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0].state == "rolled_back"
    loaded = load_features(path, universe_revision="u1", settings_revision="s1", reference_identity=identity)
    assert loaded["etf_id"].tolist() == ["OLD"]


def test_forecast_pair_crash_rolls_back_without_exposing_intermediate_state(tmp_path, monkeypatch) -> None:
    identity = _cache_identity()
    request_identity = _forecast_request_identity(load_config(), [60], live_optional_models=False)
    path = tmp_path / "forecast_results_20250101.csv"
    old = b"etf_id,expected_return\nOLD,0.01\n"
    new = b"etf_id,expected_return\nNEW,0.02\n"
    _write_bound_cache_group(
        path, old, lambda candidate: pd.read_csv(candidate), "u1", "s1", identity,
        forecast_request_identity=request_identity,
    )
    real_group = atomic_io.atomic_write_group

    def interrupted(requests):
        def hook(state, _journal):
            if state == "committing":
                raise atomic_io.AtomicWriteInterrupted(state)

        return real_group(requests, lifecycle_hook=hook)

    monkeypatch.setattr("etf_cockpit.services.atomic_write_group", interrupted)
    with pytest.raises(atomic_io.AtomicWriteInterrupted):
        _write_bound_cache_group(
            path, new, lambda candidate: pd.read_csv(candidate), "u1", "s1", identity,
            forecast_request_identity=request_identity,
        )
    assert recover_incomplete_transactions(tmp_path, event_path=tmp_path / "events.json")[0].state == "rolled_back"
    loaded = load_latest_forecasts(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
        forecast_request_identity=request_identity,
    )
    assert loaded["etf_id"].tolist() == ["OLD"]


def test_feature_pair_reader_waits_for_interleaved_publish(tmp_path, monkeypatch) -> None:
    identity = _cache_identity()
    path = tmp_path / "features.parquet"
    old = pd.DataFrame([{"date": "2025-01-01", "etf_id": "OLD", "value": 1.0}])
    new = pd.DataFrame([{"date": "2025-01-01", "etf_id": "NEW", "value": 2.0}])
    binding = {"universe_revision": "u1", "settings_revision": "s1", "reference_identity": identity}
    write_features(old, path, cache_metadata=binding)
    real_group = atomic_io.atomic_write_group
    started = threading.Event()
    release = threading.Event()

    def interleaved(requests):
        def hook(state, _journal):
            if state == "committing":
                started.set()
                if not release.wait(5):
                    raise TimeoutError("interleaving test release timed out")

        return real_group(requests, lifecycle_hook=hook)

    monkeypatch.setattr("etf_cockpit.data.duckdb_store.atomic_write_group", interleaved)
    writer = threading.Thread(target=lambda: write_features(new, path, cache_metadata=binding))
    writer.start()
    assert started.wait(5)
    observed: dict[str, pd.DataFrame] = {}
    reader = threading.Thread(
        target=lambda: observed.setdefault(
            "frame",
            load_features(path, universe_revision="u1", settings_revision="s1", reference_identity=identity),
        )
    )
    reader.start()
    assert reader.is_alive()
    release.set()
    writer.join(5)
    reader.join(5)
    assert not writer.is_alive() and not reader.is_alive()
    assert observed["frame"]["etf_id"].tolist() in (["OLD"], ["NEW"])


def test_forecast_pair_crash_and_reader_interleaving_are_fail_closed(tmp_path, monkeypatch) -> None:
    identity = _cache_identity()
    request_identity = _forecast_request_identity(load_config(), [60], live_optional_models=False)
    path = tmp_path / "forecast_results_20250101.csv"
    old = b"etf_id,expected_return\nOLD,0.01\n"
    new = b"etf_id,expected_return\nNEW,0.02\n"
    _write_bound_cache_group(
        path, old, lambda candidate: pd.read_csv(candidate), "u1", "s1", identity,
        forecast_request_identity=request_identity,
    )

    real_group = atomic_io.atomic_write_group
    started = threading.Event()
    release = threading.Event()

    def interleaved(requests):
        def hook(state, _journal):
            if state == "committing":
                started.set()
                if not release.wait(5):
                    raise TimeoutError("interleaving test release timed out")

        return real_group(requests, lifecycle_hook=hook)

    monkeypatch.setattr("etf_cockpit.services.atomic_write_group", interleaved)
    writer = threading.Thread(
        target=lambda: _write_bound_cache_group(
            path, new, lambda candidate: pd.read_csv(candidate), "u1", "s1", identity,
            forecast_request_identity=request_identity,
        )
    )
    writer.start()
    assert started.wait(5)
    observed: dict[str, pd.DataFrame] = {}
    reader = threading.Thread(
        target=lambda: observed.setdefault(
            "frame",
            load_latest_forecasts(
                directory=tmp_path,
                universe_revision="u1",
                settings_revision="s1",
                reference_identity=identity,
                forecast_request_identity=request_identity,
            ),
        )
    )
    reader.start()
    assert reader.is_alive()
    release.set()
    writer.join(5)
    reader.join(5)
    assert not writer.is_alive() and not reader.is_alive()
    assert observed["frame"]["etf_id"].tolist() in (["OLD"], ["NEW"])


def test_forecast_reader_rejects_cross_identity_publish_between_selection_and_read(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "forecast_results_20250101.csv"
    identity_a = {**_cache_identity(), "registry_hash": "a" * 64}
    identity_b = {**_cache_identity(), "registry_hash": "b" * 64}
    _write_bound_cache_group(
        path,
        b"etf_id,expected_return\nA,0.01\n",
        lambda candidate: pd.read_csv(candidate),
        "u1",
        "s1",
        identity_a,
    )
    real_read = forecast_scores.read_atomic_group
    reads = 0

    def interleaved_read(paths, *, timeout_seconds=5.0):
        nonlocal reads
        snapshot = real_read(paths, timeout_seconds=timeout_seconds)
        reads += 1
        if reads == 1:
            _write_bound_cache_group(
                path,
                b"etf_id,expected_return\nB,0.99\n",
                lambda candidate: pd.read_csv(candidate),
                "u2",
                "s2",
                identity_b,
            )
        return snapshot

    monkeypatch.setattr(forecast_scores, "read_atomic_group", interleaved_read)

    assert load_latest_forecasts(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity_a,
    ).empty


def test_forecast_selection_skips_newer_cache_from_other_settings_revision(tmp_path) -> None:
    matching = tmp_path / "forecast_results_20250101.csv"
    stale = tmp_path / "forecast_results_20250102.csv"
    _write_bound_cache_group(
        matching,
        b"etf_id,expected_return\nMATCH,0.01\n",
        lambda candidate: pd.read_csv(candidate),
        "u1",
        "s1",
        None,
    )
    _write_bound_cache_group(
        stale,
        b"etf_id,expected_return\nSTALE,0.99\n",
        lambda candidate: pd.read_csv(candidate),
        "u1",
        "s2",
        None,
    )
    os.utime(matching, (1, 1))
    os.utime(stale, (2, 2))

    assert latest_forecast_file(directory=tmp_path, settings_revision="s1") == matching
    assert load_latest_forecasts(directory=tmp_path, settings_revision="s1")["etf_id"].tolist() == ["MATCH"]
    rows = pd.DataFrame(
        [
            {"source_file": str(matching), "etf_id": "MATCH"},
            {"source_file": str(stale), "etf_id": "STALE"},
        ]
    )
    assert filter_forecasts_for_universe(rows, None, settings_revision="s1")["etf_id"].tolist() == ["MATCH"]


def test_bound_cache_readers_reject_type_forged_reference_identity(tmp_path) -> None:
    identity = _cache_identity()
    forged = {**identity, "execution_allowed": 0}

    feature_path = tmp_path / "features.parquet"
    write_features(
        pd.DataFrame([{"date": "2025-01-01", "etf_id": "FORGED", "value": 99.0}]),
        feature_path,
        cache_metadata={
            "universe_revision": "u1",
            "settings_revision": "s1",
            "reference_identity": identity,
        },
    )
    feature_metadata_path = feature_path.with_name(f"{feature_path.name}.meta.json")
    feature_metadata = json.loads(feature_metadata_path.read_text(encoding="utf-8"))
    feature_metadata["reference_identity"] = forged
    feature_metadata_path.write_text(json.dumps(feature_metadata), encoding="utf-8")
    assert load_features(
        feature_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
    ).empty

    forecast_path = tmp_path / "forecast_results_20250101.csv"
    _write_bound_cache_group(
        forecast_path,
        b"etf_id,expected_return\nFORGED,0.99\n",
        lambda candidate: pd.read_csv(candidate),
        "u1",
        "s1",
        identity,
    )
    forecast_metadata_path = forecast_path.with_name(f"{forecast_path.name}.meta.json")
    forecast_metadata = json.loads(forecast_metadata_path.read_text(encoding="utf-8"))
    forecast_metadata["reference_identity"] = forged
    forecast_metadata_path.write_text(json.dumps(forecast_metadata), encoding="utf-8")
    assert latest_forecast_file(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
    ) is None
    assert not _cache_matches_universe(forecast_path, "u1", "s1", identity)
    assert _read_bound_cache_payload(forecast_path, "u1", "s1", identity) is None


def test_cache_readers_fail_closed_on_recursively_nested_sidecars(tmp_path) -> None:
    nested_json = '{"nested":' + "[" * 10_000 + "0" + "]" * 10_000 + "}"
    identity = _cache_identity()

    feature_path = tmp_path / "features.parquet"
    pd.DataFrame([{"date": "2025-01-01", "etf_id": "ETF", "value": 1.0}]).to_parquet(
        feature_path, index=False
    )
    feature_path.with_name(f"{feature_path.name}.meta.json").write_text(
        nested_json, encoding="utf-8"
    )
    assert load_features(
        feature_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
    ).empty

    forecast_path = tmp_path / "forecast_results_20250101.csv"
    forecast_path.write_text("etf_id,expected_return\nETF,0.01\n", encoding="utf-8")
    forecast_path.with_name(f"{forecast_path.name}.meta.json").write_text(
        nested_json, encoding="utf-8"
    )
    assert latest_forecast_file(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
    ) is None
    assert load_latest_forecasts(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
    ).empty
    assert not _cache_matches_universe(forecast_path, "u1", "s1", identity)
    assert _read_bound_cache_payload(forecast_path, "u1", "s1", identity) is None


def test_application_reference_validator_fails_closed_on_deep_recursion() -> None:
    nested: dict[str, object] = {"execution_allowed": True}
    for _ in range(10_000):
        nested = {"nested": nested}
    assert validate_benchmark_reference(nested, "BENCH") is None


def test_application_reference_resolution_maps_deep_instrument_recursion_to_unavailable() -> None:
    nested: dict[str, object] = {"fact": "value"}
    for _ in range(10_000):
        nested = {"nested": nested}
    context = resolve_canonical_reference(
        CanonicalBenchmarkRegistry(),
        analysis_id="deep",
        purpose="comparison",
        instrument_id="VWCE",
        instrument=nested,
        currency="AUD",
        horizon_years=1.0,
        start_date="2025-01-01",
        end_date="2025-12-31",
        decision_time="2025-12-31T23:59:59Z",
        reference_portfolio_ids=(),
    )
    assert context.resolution is None
    assert context.blocker.startswith("reference_resolution_invalid:")


def test_application_reference_resolution_maps_non_mapping_instrument_to_unavailable() -> None:
    registry = load_canonical_benchmark_registry()
    direct = registry.resolve_analysis(
        analysis_id="malformed-instrument-direct",
        purpose="comparison",
        instrument_id="VWCE",
        instrument=object(),  # type: ignore[arg-type]
        currency="EUR",
        horizon_years=1.0,
        start_date="2025-01-01",
        end_date="2025-12-31",
        decision_time="2025-12-31T23:59:59Z",
        reference_portfolio_ids=(registry.reference_portfolios[0].portfolio_id,),
    )
    assert all(
        selection.status == "unavailable"
        for selection in (direct.benchmark, direct.cash, direct.peer_set)
    )

    context = resolve_canonical_reference(
        registry,
        analysis_id="malformed-instrument",
        purpose="comparison",
        instrument_id="VWCE",
        instrument=object(),  # type: ignore[arg-type]
        currency="EUR",
        horizon_years=1.0,
        start_date="2025-01-01",
        end_date="2025-12-31",
        decision_time="2025-12-31T23:59:59Z",
        reference_portfolio_ids=(),
    )
    assert context.resolution is None
    assert context.blocker == "reference_resolution_inputs_unavailable"
    assert context.projection["status"] == "unavailable"


def test_backtest_engine_keeps_relative_features_unavailable_without_benchmark(monkeypatch) -> None:
    from etf_cockpit.backtest import engine

    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=date(2026, 6, 26))
    captured: list[pd.DataFrame] = []
    original_latest_features = engine.latest_features

    def capture(features: pd.DataFrame, *args, **kwargs) -> pd.DataFrame:
        captured.append(features.copy())
        return original_latest_features(features, *args, **kwargs)

    monkeypatch.setattr(engine, "latest_features", capture)
    run_backtest(config, prices)

    assert captured
    assert all(frame["relative_strength_60d"].isna().all() for frame in captured)
    assert all(frame["relative_strength_120d"].isna().all() for frame in captured)
    assert all(frame["return_60d_log"].notna().any() for frame in captured)


def test_backtest_metadata_binds_fresh_reference_projection_and_rejects_tamper(tmp_path, monkeypatch) -> None:
    from etf_cockpit.data.etf_structure import LocalStructuralEvidence

    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=date(2026, 6, 26))
    monkeypatch.setattr(services_module, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(services_module, "load_prices", lambda: prices.copy())
    monkeypatch.setattr(services_module, "load_fundamental_evidence", pd.DataFrame)
    monkeypatch.setattr(
        services_module,
        "_load_local_structural_evidence",
        lambda: LocalStructuralEvidence(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(services_module, "ensure_run_manifest", lambda *_args, **_kwargs: {})
    service = services_module.BacktestService(config, universe_revision="test-revision")
    report = service.run_backtest()
    metadata_path = tmp_path / "backtest_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    context = service.reference_context
    binding = _reference_binding(context)
    assert metadata["benchmark_reference"] == binding["benchmark_reference"]
    assert metadata["benchmark_reference_hash"] == _reference_identity_hash(binding["benchmark_reference"])
    assert metadata["reference_identity_hash"] == _reference_identity_hash(binding["reference_identity"])
    assert _cached_backtest_binding_matches(metadata, context)

    metadata["benchmark_reference"]["nested"] = {"execution_allowed": True}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert service._load_cached_backtest() is None

    metadata = json.loads(json.dumps(report.metadata, default=str))
    metadata["benchmark_strategy"] = "forged"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert service._load_cached_backtest() is None


def test_attribution_clips_observations_to_declared_calculation_window() -> None:
    prices = pd.DataFrame(
        [
            {"date": f"2025-01-0{day}", "etf_id": "ALT", "adjusted_close": 100.0 + day}
            for day in range(1, 7)
        ]
    )
    context = SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-02",
                end_date="2025-01-04",
                decision_time="2025-01-04T23:59:59Z",
            )
        )
    )
    report = build_performance_attribution(
        prices,
        pd.DataFrame([{"etf_id": "ALT", "current_weight": 1.0}]),
        reference_context=context,
    )
    assert report["coverage"]["return_observations"] == 2
    assert report["daily"]["date"].min() >= pd.Timestamp("2025-01-02")
    assert report["daily"]["date"].max() <= pd.Timestamp("2025-01-04")


def test_portfolio_benchmark_comparison_uses_joined_dates_only() -> None:
    benchmark = pd.DataFrame(
        {
            "date": pd.date_range("2025-02-01", periods=3),
            "benchmark": "BENCH",
            "return": [0.01, 0.02, 0.03],
        }
    )
    comparison = _benchmark_attribution(
        0.0,
        benchmark,
        pd.date_range("2025-01-01", periods=4),
        portfolio_returns=pd.Series(
            [0.01, 0.02, 0.03],
            index=pd.date_range("2025-01-01", periods=3),
        ),
    )
    assert comparison.iloc[0]["status"] == "N/A"
    assert comparison.iloc[0]["observations"] == 0
    assert comparison.iloc[0]["return"] is None
    assert comparison.iloc[0]["active_return"] is None


def test_candidate_breadth_excludes_future_and_unproven_rows() -> None:
    report = pd.DataFrame(
        [
            {
                "sma200_signal": True,
                "latest_date": "2025-02-01",
                "provenance": "yfinance_adjusted_close",
            },
            {
                "sma200_signal": False,
                "latest_date": "2025-01-01",
                "provenance": "yfinance_adjusted_close",
            },
            {"sma200_signal": True, "latest_date": "2025-01-01"},
        ]
    )
    assert _candidate_pct_above_sma200(
        report,
        decision_time="2025-01-15T12:00:00Z",
    ) == 0.0


def test_candidate_breadth_rejects_malformed_aliases_and_date_only_knowledge_at_intraday_cutoff() -> None:
    malformed = pd.DataFrame(
        [{
            "sma200_signal": True,
            "effective_at": "2025-01-10",
            "latest_date": "not-a-date",
            "provenance": "yfinance_adjusted_close",
        }]
    )
    date_only_knowledge = pd.DataFrame(
        [{
            "sma200_signal": True,
            "effective_at": "2025-01-01",
            "known_at": "2025-01-15",
            "provenance": "yfinance_adjusted_close",
        }]
    )
    assert _candidate_pct_above_sma200(malformed, decision_time="2025-01-15T12:00:00Z") is None
    assert _candidate_pct_above_sma200(date_only_knowledge, decision_time="2025-01-15T12:00:00Z") is None


def test_candidate_breadth_rejects_future_contradictory_populated_aliases() -> None:
    future_knowledge_alias = pd.DataFrame([{
        "sma200_signal": True,
        "effective_at": "2025-01-10T12:00:00Z",
        "known_at": "2025-01-10T12:00:00Z",
        "available_at": "2025-01-16T12:00:00Z",
        "provenance": "yfinance_adjusted_close",
    }])
    future_observation_alias = pd.DataFrame([{
        "sma200_signal": True,
        "effective_at": "2025-01-10T12:00:00Z",
        "as_of_date": "2025-01-16",
        "known_at": "2025-01-10T12:00:00Z",
        "provenance": "yfinance_adjusted_close",
    }])
    cutoff = "2025-01-15T12:00:00Z"
    assert _candidate_pct_above_sma200(future_knowledge_alias, decision_time=cutoff) is None
    assert _candidate_pct_above_sma200(future_observation_alias, decision_time=cutoff) is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("sma200_signal", [True]),
        ("latest_date", ["2025-01-10"]),
        ("provenance", ["yfinance_adjusted_close"]),
    ),
)
def test_candidate_breadth_rejects_sequence_chronology_and_provenance(
    field: str,
    value: list[str],
) -> None:
    row: dict[str, object] = {
        "sma200_signal": True,
        "latest_date": "2025-01-10",
        "provenance": "yfinance_adjusted_close",
    }
    row[field] = value
    report = pd.DataFrame([row])
    reference = _available_reference()

    assert (
        _candidate_pct_above_sma200(
            report,
            decision_time=reference["analysis"]["decision_time"],
        )
        is None
    )
    regime = build_market_regime(
        _prices(),
        report,
        benchmark_id="BENCH",
        benchmark_reference=reference,
    )
    assert regime["candidate_pct_above_sma200"] is None


def test_shared_window_clip_caps_intraday_authority_and_date_only_rows() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02 12:00:00Z", "2025-01-02 20:00:00Z"],
            "adjusted_close": [100.0, 101.0, 102.0],
        }
    )
    clipped = clip_to_decision_window(
        prices,
        start_date="2025-01-01",
        end_date="2025-01-02",
        decision_time="2025-01-02T12:00:00Z",
    )
    assert clipped["date"].tolist() == ["2025-01-01", "2025-01-02 12:00:00Z"]
    date_only = clip_to_decision_window(
        pd.DataFrame({"date": ["2025-01-02"], "adjusted_close": [101.0]}),
        start_date="2025-01-01",
        end_date="2025-01-02",
        decision_time="2025-01-02T12:00:00Z",
    )
    assert date_only.empty


def test_backtest_excludes_date_only_close_before_intraday_decision_cutoff() -> None:
    config = load_config()
    end_date = date(2025, 1, 3)
    prices = generate_sample_prices(config, periods=261, end_date=end_date)
    start_date = pd.to_datetime(prices["date"]).min().date()
    identity = {
        "status": "available",
        "analysis": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "decision_time": "2025-01-03T12:00:00Z",
        },
        "execution_allowed": False,
    }

    report = run_backtest(config, prices, reference_identity=identity)

    assert pd.to_datetime(report.results["end_date"]).max().date() < end_date


def test_regime_rejects_nested_forged_benchmark_authority() -> None:
    with pytest.raises(BenchmarkReferenceError):
        build_market_regime(
            _prices(),
            benchmark_reference={"nested": {"execution_allowed": True}},
        )


@pytest.mark.parametrize("binding_mode", ["missing", "stale"])
def test_signal_service_recomputes_supplied_features_without_current_price_binding(
    monkeypatch, binding_mode: str
) -> None:
    import etf_cockpit.services as services_module

    captured: dict[str, object] = {}
    prices = pd.DataFrame([{"date": date(2025, 1, 2), "etf_id": "VWCE", "adjusted_close": 100.0}])
    monkeypatch.setattr(services_module, "load_prices", lambda: prices.copy())
    monkeypatch.setattr(services_module, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(services_module.DataService, "validate_prices", lambda *args, **kwargs: object())
    monkeypatch.setattr(services_module, "model_availability", lambda config: {"toto": False, "timesfm": False})
    monkeypatch.setattr(services_module, "_load_structure_caps", lambda *args, **kwargs: {})
    monkeypatch.setattr(services_module, "generate_signals", lambda *args, **kwargs: [])
    identity = {
        "schema": "benchmark-reference-cache.v1",
        "status": "unavailable",
        "analysis": None,
        "execution_allowed": False,
    }
    monkeypatch.setattr(
        services_module,
        "_reference_context_from_inputs",
        lambda *args, **kwargs: SimpleNamespace(identity=identity, benchmark_data_id=None),
    )
    monkeypatch.setattr(services_module, "load_features", lambda *args, **kwargs: pd.DataFrame())
    recomputed = pd.DataFrame(
        [{"date": date(2025, 1, 2), "etf_id": "RECOMPUTED"}]
    )
    monkeypatch.setattr(
        services_module.FeatureService,
        "compute_features",
        lambda *_args, **_kwargs: recomputed,
    )

    def capture_latest(frame, *_args, **_kwargs):
        captured["feature_ids"] = frame["etf_id"].tolist()
        return frame

    monkeypatch.setattr(services_module, "latest_features", capture_latest)

    def capture_forecasts(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(services_module, "load_latest_forecasts", capture_forecasts)
    supplied_features = pd.DataFrame(columns=["date", "etf_id"])
    supplied_features.attrs["reference_identity"] = dict(identity)
    supplied_features.attrs["reference_identity_hash"] = _reference_identity_hash(identity)
    if binding_mode == "stale":
        supplied_features.attrs["price_binding"] = {
            "price_snapshot_checksum": "b" * 64,
            "price_snapshot_revision": "b" * 64,
            "effective_cutoff": "2025-01-02T23:59:59+00:00",
            "calculation_window": {
                "start_date": "2025-01-02",
                "end_date": "2025-01-02",
                "decision_time": "2025-01-02T23:59:59+00:00",
            },
        }
    SignalService(load_config()).generate_signals(
        as_of_date=date(2025, 1, 2),
        features=supplied_features,
    )
    assert isinstance(captured.get("reference_identity"), dict)
    assert captured["reference_identity"]["schema"] == "benchmark-reference-cache.v1"
    assert captured["feature_ids"] == ["RECOMPUTED"]


def test_feature_service_without_as_of_derives_bound_window_before_publication(monkeypatch) -> None:
    captured: dict[str, object] = {}
    prices = pd.DataFrame([
        {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
        {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
    ])
    monkeypatch.setattr(services_module, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        services_module,
        "compute_features",
        lambda frame, **_kwargs: pd.DataFrame({"date": frame["date"], "etf_id": frame["etf_id"]}),
    )

    def capture_write(frame, *, cache_metadata):
        captured["metadata"] = cache_metadata
        captured["attrs"] = dict(frame.attrs)

    monkeypatch.setattr(services_module, "write_features", capture_write)
    services_module.FeatureService(load_config()).compute_features(prices=prices)

    metadata = captured["metadata"]
    assert metadata["calculation_window"] == {
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
        "decision_time": "2025-01-02T23:59:59+00:00",
    }
    assert metadata["price_snapshot_checksum"] == captured["attrs"]["price_binding"]["price_snapshot_checksum"]


def test_attribution_excludes_future_commission_from_declared_window() -> None:
    context = SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-01",
                end_date="2025-01-02",
                decision_time="2025-01-02T23:59:59Z",
            )
        )
    )
    report = build_performance_attribution(
        pd.DataFrame([
            {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
            {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
        ]),
        pd.DataFrame([{"etf_id": "ETF", "current_weight": 1.0}]),
        costs=pd.DataFrame([{
            "date": "2025-02-01",
            "known_at": "2025-02-01T12:00:00Z",
            "category": "commission",
            "amount": 0.005,
        }]),
        reference_context=context,
    )
    assert report["cost_attribution"].empty
    assert report["net_return_after_explicit_costs"] == report["time_weighted_return"]
    assert "explicit_costs_outside_canonical_window_excluded" in report["warnings"]


@pytest.mark.parametrize(
    "chronology",
    [
        {"date": "not-a-date"},
        {"date": ["2025-01-01"]},
        {"date": "2025-01-01", "effective_at": "2025-01-02T12:00:00Z"},
    ],
)
def test_attribution_marks_malformed_or_contradictory_cost_chronology_unavailable(chronology) -> None:
    context = SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-01",
                end_date="2025-01-02",
                decision_time="2025-01-02T23:59:59Z",
            )
        )
    )
    report = build_performance_attribution(
        pd.DataFrame([
            {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
            {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
        ]),
        pd.DataFrame([{"etf_id": "ETF", "current_weight": 1.0}]),
        costs=pd.DataFrame([{"category": "commission", "amount": 0.005, **chronology}]),
        reference_context=context,
    )
    assert report["net_return_after_explicit_costs"] is None
    assert report["coverage"]["cost_status"] == "invalid"
    assert "explicit_costs_invalid_for_canonical_window" in report["warnings"]


def test_attribution_future_cashflow_cannot_publish_money_weighted_return() -> None:
    context = SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-01",
                end_date="2025-01-02",
                decision_time="2025-01-02T23:59:59Z",
            )
        )
    )
    report = build_performance_attribution(
        pd.DataFrame([
            {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
            {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
        ]),
        pd.DataFrame([{"etf_id": "ETF", "current_weight": 1.0}]),
        cashflows=pd.DataFrame([{
            "date": "2025-02-01",
            "known_at": "2025-02-01T12:00:00Z",
            "amount": 100.0,
        }]),
        reference_context=context,
    )
    assert report["money_weighted_return"] is None
    assert report["money_weighted_status"] == "unavailable_invalid_or_outside_canonical_window"
    assert "external_cashflows_outside_canonical_window_excluded" in report["warnings"]


@pytest.mark.parametrize(
    "chronology",
    [
        {"date": "not-a-date"},
        {"date": ["2025-01-01"]},
        {"date": "2025-01-01", "effective_at": "2025-01-02T12:00:00Z"},
        {
            "date": "2025-01-01",
            "known_at": "2025-01-01T12:00:00Z",
            "available_at": "2025-01-02T12:00:00Z",
        },
    ],
)
def test_attribution_malformed_or_contradictory_cashflow_is_unavailable(chronology) -> None:
    context = SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-01",
                end_date="2025-01-02",
                decision_time="2025-01-02T23:59:59Z",
            )
        )
    )
    report = build_performance_attribution(
        pd.DataFrame([
            {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
            {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
        ]),
        pd.DataFrame([{"etf_id": "ETF", "current_weight": 1.0}]),
        cashflows=pd.DataFrame([{**chronology, "amount": 100.0}]),
        reference_context=context,
    )
    assert report["money_weighted_return"] is None
    assert report["money_weighted_status"] == "unavailable_invalid_or_outside_canonical_window"
    assert "external_cashflows_invalid_for_canonical_window" in report["warnings"]


@pytest.mark.parametrize("amount", ["not-a-number", True, float("nan"), float("inf")])
def test_attribution_invalid_cost_amount_cannot_publish_available_net_return(amount) -> None:
    context = SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-01",
                end_date="2025-01-02",
                decision_time="2025-01-02T23:59:59Z",
            )
        )
    )
    report = build_performance_attribution(
        pd.DataFrame([
            {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
            {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
        ]),
        pd.DataFrame([{"etf_id": "ETF", "current_weight": 1.0}]),
        costs=pd.DataFrame([{
            "date": "2025-01-01",
            "known_at": "2025-01-01T12:00:00Z",
            "category": "commission",
            "amount": amount,
        }]),
        reference_context=context,
    )
    assert report["net_return_after_explicit_costs"] is None
    assert report["coverage"]["cost_status"] == "invalid"
    assert "explicit_costs_invalid_for_canonical_window" in report["warnings"]


def test_main_and_candidate_forecast_caches_bind_horizons_and_optional_mode(tmp_path) -> None:
    identity = _cache_identity()
    price_binding = {
        "price_snapshot_checksum": "a" * 64,
        "price_snapshot_revision": "a" * 64,
        "effective_cutoff": "2025-01-02T23:59:59Z",
        "calculation_window": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "decision_time": "2025-01-02T23:59:59Z",
        },
    }
    written_request = _forecast_request_identity(load_config(), [1, 1], live_optional_models=False)
    requested = _forecast_request_identity(load_config(), [60], live_optional_models=True)
    for name in ("forecast_results_yfinance_20250102.csv", "yfinance_candidate_forecasts_20250102.csv"):
        path = tmp_path / name
        _write_bound_cache_group(
            path,
            b"etf_id,status\nETF,ok\n",
            lambda candidate: pd.read_csv(candidate),
            "u1",
            "s1",
            identity,
            price_binding,
            written_request,
        )
        assert not _cache_matches_universe(
            path, "u1", "s1", identity, price_binding, requested
        )
        assert _read_bound_cache_payload(
            path, "u1", "s1", identity, price_binding, requested
        ) is None
        assert latest_forecast_file(
            pattern=name,
            directory=tmp_path,
            universe_revision="u1",
            settings_revision="s1",
            reference_identity=identity,
            price_binding=price_binding,
            forecast_request_identity=requested,
        ) is None
        assert load_latest_forecasts(
            pattern=name,
            directory=tmp_path,
            universe_revision="u1",
            settings_revision="s1",
            reference_identity=identity,
            price_binding=price_binding,
            forecast_request_identity=requested,
        ).empty
        assert filter_forecasts_for_universe(
            pd.DataFrame([{"source_file": str(path), "etf_id": "ETF"}]),
            "u1",
            "s1",
            reference_identity=identity,
            price_binding=price_binding,
            forecast_request_identity=requested,
        ).empty
    assert written_request["requested_horizons"] == [1]


def test_ui_forecast_action_rebuild_reads_configured_and_candidate_caches_with_one_request(
    tmp_path, monkeypatch
) -> None:
    config = load_config()
    expected_request = configured_forecast_request_identity(config)
    identity = {
        **_cache_identity(),
        "analysis": {
            "currency": "EUR",
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "decision_time": "2025-01-02T23:59:59Z",
        },
    }
    main_binding = {
        "price_snapshot_checksum": "a" * 64,
        "price_snapshot_revision": "a" * 64,
        "effective_cutoff": "2025-01-02T23:59:59Z",
        "calculation_window": dict(identity["analysis"]),
    }
    candidate_binding = {
        **main_binding,
        "price_snapshot_checksum": "b" * 64,
        "price_snapshot_revision": "b" * 64,
    }
    main_path = tmp_path / "forecast_results_yfinance_20250102.csv"
    candidate_path = tmp_path / "yfinance_candidate_forecasts_20250102.csv"
    readback: dict[str, pd.DataFrame] = {}

    class PublishingDataService:
        last_operation_succeeded = True

        def __init__(self, supplied_config) -> None:
            self.config = supplied_config

        def run_yfinance_forecasts(self, **kwargs) -> str:
            writer_request = _forecast_request_identity(
                self.config,
                kwargs["horizons"],
                live_optional_models=kwargs["live_optional_models"],
            )
            assert writer_request == expected_request
            for path, instrument_id, binding in (
                (main_path, "MAIN", main_binding),
                (candidate_path, "CANDIDATE", candidate_binding),
            ):
                _write_bound_cache_group(
                    path,
                    f"etf_id,status\n{instrument_id},ok\n".encode(),
                    lambda candidate: pd.read_csv(candidate),
                    "u1",
                    "s1",
                    identity,
                    binding,
                    writer_request,
                )
            return "Configured and candidate forecasts published."

    snapshot = SimpleNamespace(config=config)

    def rebuild_snapshot(*_args, **_kwargs):
        snapshot_request = configured_forecast_request_identity(config)
        readback["configured"] = load_latest_forecasts(
            "forecast_results_yfinance_*.csv",
            tmp_path,
            universe_revision="u1",
            settings_revision="s1",
            reference_identity=identity,
            price_binding=main_binding,
            forecast_request_identity=snapshot_request,
        )
        readback["candidate"] = load_latest_forecasts(
            "yfinance_candidate_forecasts_*.csv",
            tmp_path,
            universe_revision="u1",
            settings_revision="s1",
            reference_identity=identity,
            price_binding=candidate_binding,
            forecast_request_identity=snapshot_request,
        )
        return snapshot

    monkeypatch.setattr(app_state_module, "DataService", PublishingDataService)
    monkeypatch.setattr(app_state_module, "build_snapshot", rebuild_snapshot)
    state = AppState(snapshot=snapshot, selected_etf="MAIN")
    monkeypatch.setattr(state, "_write_current_scoreboard", lambda: SimpleNamespace(name="scores.parquet"))

    state.run_forecasting_models()

    assert expected_request == {
        "schema": "forecast-cache-request.v1",
        "requested_horizons": [60],
        "live_optional_models": False,
    }
    assert readback["configured"]["etf_id"].tolist() == ["MAIN"]
    assert readback["candidate"]["etf_id"].tolist() == ["CANDIDATE"]


def test_packaged_registry_unavailable_cash_blocks_local_curve_lookup(monkeypatch) -> None:
    context = CanonicalReferenceContext(load_canonical_benchmark_registry())
    monkeypatch.setattr(
        simple_scores_module,
        "_build_local_cash_comparison_lookup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local curve evidence bypassed unavailable canonical cash")
        ),
    )
    scores = build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        pd.DataFrame(),
        benchmark_reference=context.projection,
        reference_identity=context.identity,
        benchmark_registry=context.registry,
    )
    assert scores
    assert all(score.cash_comparison_status == "unavailable" for score in scores)
    assert all(score.cash_return is None for score in scores)


def test_malformed_candidate_report_fails_closed_through_score_builder(
    tmp_path, monkeypatch
) -> None:
    report_path = tmp_path / "yfinance_trade_candidate_analysis_20250102.csv"
    report_path.write_bytes(b"\xff\xfe\x00invalid-candidate-report")
    monkeypatch.setattr(simple_scores_module, "REPORTS_DIR", tmp_path)

    scores = build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        pd.DataFrame(),
    )

    assert scores
    assert all(score.execution_allowed is False for score in scores)


def test_malformed_raw_candidate_input_fails_closed_through_score_builder(
    tmp_path, monkeypatch
) -> None:
    raw_directory = tmp_path / "trade_candidates"
    raw_directory.mkdir()
    (raw_directory / "yahoo_trade_candidates_20250102.csv").write_bytes(
        b"\xff\xfe\x00invalid-raw-candidate-input"
    )
    monkeypatch.setattr(simple_scores_module, "RAW_DIR", tmp_path)

    scores = build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        pd.DataFrame(),
    )

    assert scores
    assert all(score.execution_allowed is False for score in scores)


@pytest.mark.parametrize("value", ([True], [True, False]))
def test_candidate_score_rejects_non_scalar_trend_signal(value: list[bool]) -> None:
    scores = simple_scores_module.build_candidate_simple_scores(
        pd.DataFrame(
            [
                {
                    "instrument_id": "MALFORMED",
                    "instrument_type": "ETF",
                    "data_policy": "yfinance_only",
                    "latest_date": "2025-01-02",
                    "latest_price": 100.0,
                    "rows": 260,
                    "sma50_signal": None,
                    "sma200_signal": value,
                }
            ]
        ),
        pd.DataFrame(),
    )

    assert len(scores) == 1
    trend = next(component for component in scores[0].components if component.key == "trend")
    assert trend.raw_score is None
    assert trend.score_10 is None
    assert scores[0].execution_allowed is False


def test_simple_score_candidate_loader_passes_reference_identity(monkeypatch) -> None:
    captured: dict[str, object] = {}
    candidate_binding = {
        "price_snapshot_checksum": "b" * 64,
        "price_snapshot_revision": "b" * 64,
        "effective_cutoff": "2025-01-02T23:59:59Z",
        "calculation_window": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "decision_time": "2025-01-02T23:59:59Z",
        },
    }
    monkeypatch.setattr(simple_scores_module, "load_latest_candidate_report", lambda: (pd.DataFrame(), None))
    monkeypatch.setattr(simple_scores_module, "load_forecast_history", lambda: pd.DataFrame())
    monkeypatch.setattr(simple_scores_module, "load_candidate_price_binding", lambda: candidate_binding)

    def capture_forecasts(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(simple_scores_module, "load_latest_forecasts", capture_forecasts)
    identity = {
        "schema": "benchmark-reference-cache.v1",
        "analysis": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "decision_time": "2025-01-02T23:59:59Z",
        },
        "execution_allowed": False,
    }
    prices = pd.DataFrame([
        {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": 100.0},
        {"date": "2025-01-02", "etf_id": "ETF", "adjusted_close": 101.0},
    ])
    build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        prices,
        reference_identity=identity,
    )
    assert captured["reference_identity"] == identity
    assert captured["price_binding"] == candidate_binding
    assert captured["forecast_request_identity"] == configured_forecast_request_identity(load_config())


def test_candidate_price_binding_replays_exact_retained_source_and_rejects_substitution(tmp_path) -> None:
    path = tmp_path / "candidate_prices.csv"
    window = {
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
        "decision_time": "2025-01-02T23:59:59Z",
    }
    candidate_prices = pd.DataFrame([
        {"date": "2025-01-01", "etf_id": "CANDIDATE", "adjusted_close": 20.0},
        {"date": "2025-01-02", "etf_id": "CANDIDATE", "adjusted_close": 21.0},
    ])
    main_prices = pd.DataFrame([
        {"date": "2025-01-01", "etf_id": "MAIN", "adjusted_close": 100.0},
        {"date": "2025-01-02", "etf_id": "MAIN", "adjusted_close": 101.0},
    ])
    candidate_binding = adjusted_price_snapshot_binding(candidate_prices, calculation_window=window)
    main_binding = adjusted_price_snapshot_binding(main_prices, calculation_window=window)
    assert candidate_binding is not None and candidate_binding != main_binding
    write_candidate_price_snapshot(candidate_prices, candidate_binding, path=path)
    assert load_candidate_price_binding(path=path) == candidate_binding

    path.write_text("date,etf_id,adjusted_close\n2025-01-01,FORGED,999\n", encoding="utf-8")
    assert load_candidate_price_binding(path=path) is None


def test_malformed_price_identity_cannot_reuse_cache_or_reach_simple_score_disk_reader(
    tmp_path, monkeypatch
) -> None:
    identity = {
        **_cache_identity(),
        "analysis": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-01",
            "decision_time": "2025-01-01T23:59:59Z",
        },
    }
    unavailable_binding = {
        "price_snapshot_checksum": "unavailable",
        "price_snapshot_revision": "unavailable",
        "effective_cutoff": "2025-01-01T23:59:59Z",
        "calculation_window": dict(identity["analysis"]),
    }
    feature_path = tmp_path / "features.parquet"
    write_features(
        pd.DataFrame([{"date": "2025-01-01", "etf_id": "ETF"}]),
        feature_path,
        cache_metadata={
            "universe_revision": "u1",
            "settings_revision": "s1",
            "reference_identity": identity,
            **unavailable_binding,
        },
    )
    forecast_path = tmp_path / "forecast_results_20250101.csv"
    _write_bound_cache_group(
        forecast_path,
        b"etf_id,expected_return\nETF,0.01\n",
        lambda candidate: pd.read_csv(candidate),
        "u1",
        "s1",
        identity,
        unavailable_binding,
    )
    assert load_features(
        feature_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
        price_binding=unavailable_binding,
    ).empty
    assert load_latest_forecasts(
        directory=tmp_path,
        universe_revision="u1",
        settings_revision="s1",
        reference_identity=identity,
        price_binding=unavailable_binding,
    ).empty

    monkeypatch.setattr(simple_scores_module, "load_latest_candidate_report", lambda: (pd.DataFrame(), None))
    monkeypatch.setattr(simple_scores_module, "load_forecast_history", lambda: pd.DataFrame())
    def forbidden_disk_read(*_args, **_kwargs):
        raise AssertionError("malformed current prices must not reach the forecast disk reader")

    monkeypatch.setattr(simple_scores_module, "load_latest_forecasts", forbidden_disk_read)
    build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        pd.DataFrame(),
        universe_revision="u1",
        reference_identity=identity,
    )


def test_canonical_feature_and_forecast_writes_reject_unbound_prices(tmp_path) -> None:
    malformed = pd.DataFrame([
        {"date": "2025-01-01", "etf_id": "ETF", "adjusted_close": -1.0},
    ])
    context = CanonicalReferenceContext(CanonicalBenchmarkRegistry())
    with pytest.raises(ValueError, match="snapshot identity is unavailable"):
        services_module.FeatureService(load_config(), reference_context=context).compute_features(
            date(2025, 1, 1), malformed
        )
    output = tmp_path / "forecast_results_20250101.csv"
    with pytest.raises(ValueError, match="snapshot identity is unavailable"):
        services_module.ForecastService(load_config(), reference_context=context).run_forecasts(
            date(2025, 1, 1), ["ETF"], malformed, output_path=output
        )
    assert not output.exists()


def test_dashboard_model_pair_disk_reader_requires_current_price_binding(monkeypatch) -> None:
    identity = {
        "schema": "benchmark-reference-cache.v1",
        "analysis": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "decision_time": "2025-01-02T23:59:59Z",
        },
        "execution_allowed": False,
    }
    binding = {
        "price_snapshot_checksum": "a" * 64,
        "price_snapshot_revision": "a" * 64,
        "effective_cutoff": "2025-01-02T23:59:59Z",
        "calculation_window": dict(identity["analysis"]),
    }
    candidate_binding = {
        **binding,
        "price_snapshot_checksum": "b" * 64,
        "price_snapshot_revision": "b" * 64,
    }
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        dashboard_module,
        "context_from_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(identity=identity),
    )
    monkeypatch.setattr(
        dashboard_module,
        "adjusted_price_binding_for_reference",
        lambda *_args, **_kwargs: binding,
    )

    def capture_load(*_args, **kwargs):
        captured.append(kwargs)
        return pd.DataFrame()

    def capture_filter(frame, *_args, **kwargs):
        captured.append(kwargs)
        return frame.iloc[0:0].copy()

    monkeypatch.setattr(dashboard_module, "load_latest_forecasts", capture_load)
    monkeypatch.setattr(dashboard_module, "filter_forecasts_for_universe", capture_filter)
    state = SimpleNamespace(
        snapshot=SimpleNamespace(
            universe_revision="u1",
            prices=pd.DataFrame(),
            forecasts=pd.DataFrame(),
            config=load_config(),
            candidate_price_binding=candidate_binding,
        ),
        universe_cache_revision="u1",
    )
    assert dashboard_module._valid_model_pairs(state) == 0
    assert len(captured) == 2
    assert captured[0]["price_binding"] == candidate_binding
    assert captured[1]["price_binding"] == binding
    assert all("forecast_request_identity" in call for call in captured)

    monkeypatch.setattr(
        dashboard_module,
        "adjusted_price_binding_for_reference",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        dashboard_module,
        "load_latest_forecasts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disk read bypassed binding")),
    )
    state.snapshot.candidate_price_binding = None
    monkeypatch.setattr(dashboard_module, "load_candidate_price_binding", lambda: None)
    assert dashboard_module._valid_model_pairs(state) == 0


def test_optional_forecast_relative_fields_are_derived_uniformly_or_n_a() -> None:
    forecast = ForecastResult(
        run_id="run",
        model_name="timesfm",
        model_version="test",
        etf_id="ALT",
        forecast_date=date(2025, 1, 1),
        horizon_days=10,
        expected_return=0.10,
        expected_excess_return=0.10,
        forecast_vol=0.05,
    )
    benchmark = pd.Series([0.01, 0.02], dtype=float)
    available = _postprocess_forecast_benchmark_fields([forecast], benchmark)[0]
    assert available.expected_return == 0.10
    assert available.expected_excess_return == pytest.approx(0.10 - 0.35 * benchmark.mean() * 10)
    assert available.prob_beat_benchmark is not None
    unavailable = _postprocess_forecast_benchmark_fields([forecast], None)[0]
    assert unavailable.expected_return == 0.10
    assert unavailable.expected_excess_return is None
    assert unavailable.prob_beat_benchmark is None


def test_shared_reference_validation_rejects_digest_mismatch_for_all_relative_consumers() -> None:
    prices = _prices()
    forged = _available_reference()
    forged["cash"] = {"status": "available", "content_hash": "x" * 64}

    assert validate_benchmark_reference(forged, "BENCH") is None
    assert build_market_regime(
        prices, benchmark_id="BENCH", benchmark_reference=forged
    )["regime_score_10"] is None
    assert all(
        row["score"] is None
        for row in build_portfolio_fit_lookup(
            prices, benchmark_id="BENCH", benchmark_reference=forged
        ).values()
    )
    assert all(
        row["benchmark_return"] is None
        for row in build_benchmark_attribution_lookup(
            prices, benchmark_id="BENCH", benchmark_reference=forged
        ).values()
    )
    assert build_macro_context(
        prices, benchmark_data_id="BENCH", benchmark_reference=forged
    )["status"] == "unavailable"


def test_shared_reference_validation_rejects_self_consistent_forged_registry_authority() -> None:
    registry = _available_registry()
    reference = _available_reference()
    assert validate_benchmark_reference(reference, "BENCH", registry=registry) == "BENCH"

    forged = json.loads(json.dumps(reference))
    forged["registry_hash"] = "f" * 64
    forged["benchmark_data_id"] = "FORGED"
    forged["benchmark"]["content_hash"] = "b" * 64
    forged["cash"]["content_hash"] = "c" * 64
    forged["selected_records"]["benchmark"] = "b" * 64
    forged["selected_records"]["cash"] = "c" * 64
    prices = _prices().replace({"BENCH": "FORGED"})

    assert validate_benchmark_reference(forged, "FORGED", registry=registry) is None
    forged_identity = {
        "status": "available",
        "registry_hash": forged["registry_hash"],
        "benchmark_data_id": "FORGED",
        "selected_records": forged["selected_records"],
        "execution_allowed": False,
    }
    assert _validated_benchmark_data_id(
        "FORGED",
        forged,
        forged_identity,
        registry,
        pd.Index(["FORGED"]),
    ) is None
    assert build_market_regime(
        prices,
        benchmark_id="FORGED",
        benchmark_reference=forged,
        benchmark_registry=registry,
    )["regime_score_10"] is None


def test_shared_reference_validation_requires_explicit_disabled_execution_authority() -> None:
    registry = _available_registry()
    reference = _available_reference()
    reference.pop("execution_allowed")

    assert validate_benchmark_reference(reference, "BENCH", registry=registry) is None
    assert build_market_regime(
        _prices(),
        benchmark_id="BENCH",
        benchmark_reference=reference,
        benchmark_registry=registry,
    )["regime_score_10"] is None


def test_shared_reference_validation_binds_references_and_point_in_time_window() -> None:
    registry = _available_registry()
    reference = _available_reference()
    assert validate_benchmark_reference(reference, "BENCH", registry=registry) == "BENCH"

    forged_reference = deepcopy(reference)
    forged_reference["references"][0]["content_hash"] = "f" * 64
    forged_reference["selected_records"]["references"] = {
        "reference:test@1.0.0": "f" * 64,
    }
    assert validate_benchmark_reference(forged_reference, "BENCH", registry=registry) is None

    forged_window = deepcopy(reference)
    forged_window["analysis"]["start_date"] = "2019-01-01"
    assert validate_benchmark_reference(forged_window, "BENCH", registry=registry) is None
    assert build_market_regime(
        _prices(),
        benchmark_id="BENCH",
        benchmark_reference=forged_window,
        benchmark_registry=registry,
    )["regime_score_10"] is None


def test_shared_reference_validation_rejects_caller_selection_from_ambiguous_constituents() -> None:
    constituents = ("BENCH_A", "BENCH_B")
    registry = _available_registry(constituents)
    reference = _available_reference(
        benchmark_data_id="BENCH_B",
        benchmark_constituents=constituents,
    )
    assert validate_benchmark_reference(reference, "BENCH_B", registry=registry) is None
    assert _validated_benchmark_data_id(
        "BENCH_B",
        reference,
        {
            "status": "available",
            "registry_hash": reference["registry_hash"],
            "benchmark_data_id": "BENCH_B",
            "selected_records": reference["selected_records"],
            "execution_allowed": False,
        },
        registry,
        pd.Index(constituents),
    ) is None


def test_peer_members_and_cash_identity_are_derived_from_registry_authority(monkeypatch) -> None:
    registry = _available_registry()
    peer_forged = _available_reference(peer=True)
    peer_forged["peer_set"]["member_instrument_ids"] = ["FORGED"]
    assert validate_benchmark_reference(peer_forged, "BENCH", registry=registry) is None
    attribution = build_benchmark_attribution_lookup(
        _prices(),
        benchmark_id="BENCH",
        benchmark_reference=peer_forged,
        benchmark_registry=registry,
    )
    assert all(row["benchmark_return"] is None for row in attribution.values())

    cash_forged = _available_reference()
    cash_forged["cash"]["id"] = "cash:forged"
    cash_forged["cash"]["content_hash"] = "c" * 64
    cash_forged["selected_records"]["cash"] = "c" * 64
    identity = {
        "status": "available",
        "registry_hash": cash_forged["registry_hash"],
        "benchmark_data_id": "BENCH",
        "selected_records": cash_forged["selected_records"],
        "analysis": cash_forged["analysis"],
        "execution_allowed": False,
    }
    assert simple_scores_module._canonical_cash_request(
        cash_forged,
        identity,
        benchmark_registry=registry,
    ) is None
    monkeypatch.setattr(
        simple_scores_module,
        "_build_local_cash_comparison_lookup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("forged cash identity reached local curve lookup")
        ),
    )
    scores = build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        pd.DataFrame(),
        benchmark_data_id="BENCH",
        benchmark_reference=cash_forged,
        benchmark_registry=registry,
        reference_identity=identity,
    )
    assert scores
    assert all(score.cash_comparison_status == "unavailable" for score in scores)


@pytest.mark.parametrize("unavailable_kind", ("benchmark", "cash", "peer"))
def test_reference_validation_rejects_projection_availability_over_unavailable_registry_record(
    unavailable_kind: str,
) -> None:
    registry = _available_registry(
        benchmark_status="unavailable" if unavailable_kind == "benchmark" else "available",
        cash_status="unavailable" if unavailable_kind == "cash" else "available",
        peer_status="unavailable" if unavailable_kind == "peer" else "available",
    )
    reference = _available_reference(peer=unavailable_kind == "peer")
    reference["registry_hash"] = registry.as_payload()["registry_hash"]
    benchmark = registry.benchmarks[0]
    cash = registry.cash_proxies[0]
    reference["benchmark"]["content_hash"] = benchmark.digest()
    reference["cash"]["content_hash"] = cash.digest()
    reference["selected_records"]["benchmark"] = benchmark.digest()
    reference["selected_records"]["cash"] = cash.digest()
    if unavailable_kind == "peer":
        peer = registry.peer_sets[0]
        reference["peer_set"]["content_hash"] = peer.digest()
        reference["selected_records"]["peer_set"] = peer.digest()

    assert validate_benchmark_reference(reference, "BENCH", registry=registry) is None
    assert build_market_regime(
        _prices(),
        benchmark_id="BENCH",
        benchmark_reference=reference,
        benchmark_registry=registry,
    )["regime_score_10"] is None


@pytest.mark.parametrize("projected_status", ("unavailable", "stale"))
def test_reference_validation_rejects_populated_non_available_peer_projection(
    projected_status: str,
) -> None:
    registry = _available_registry(
        peer_status="unavailable" if projected_status == "unavailable" else "available",
    )
    reference = _available_reference(peer=True)
    peer = registry.peer_sets[0]
    reference["registry_hash"] = registry.as_payload()["registry_hash"]
    reference["peer_set"]["status"] = projected_status
    reference["peer_set"]["content_hash"] = peer.digest()
    reference["selected_records"]["peer_set"] = peer.digest()

    assert validate_benchmark_reference(reference, "BENCH", registry=registry) is None
    assert build_market_regime(
        _prices(),
        benchmark_id="BENCH",
        benchmark_reference=reference,
        benchmark_registry=registry,
    )["regime_score_10"] is None


def test_reference_validation_rejects_cleared_available_registry_peer() -> None:
    registry = _available_registry()
    reference = _available_reference(peer=True)
    reference["peer_set"] = {
        "status": "unavailable",
        "id": None,
        "version": None,
        "content_hash": None,
        "member_instrument_ids": [],
    }
    reference["selected_records"]["peer_set"] = None
    identity = {
        "registry_hash": reference["registry_hash"],
        "selected_records": reference["selected_records"],
        "analysis": reference["analysis"],
    }

    assert validate_benchmark_reference(reference, "BENCH", registry=registry) is None
    assert build_benchmark_attribution_lookup(
        _prices(),
        benchmark_id="BENCH",
        benchmark_reference=reference,
        benchmark_registry=registry,
    )["ALT"]["benchmark_return"] is None
    assert simple_scores_module._canonical_cash_request(
        reference,
        identity,
        benchmark_registry=registry,
    ) is None


def test_empty_unavailable_peer_is_legal_without_pit_available_registry_peer() -> None:
    complete_registry = _available_registry()
    registry = CanonicalBenchmarkRegistry(
        benchmarks=complete_registry.benchmarks,
        cash_proxies=complete_registry.cash_proxies,
        reference_portfolios=complete_registry.reference_portfolios,
    )
    reference = _available_reference(peer=False)
    reference["registry_hash"] = registry.as_payload()["registry_hash"]

    assert validate_benchmark_reference(reference, "BENCH", registry=registry) == "BENCH"


def test_cash_request_uses_complete_reference_validation_for_peer_authority() -> None:
    valid_registry = _available_registry()
    valid_reference = _available_reference()
    valid_identity = {
        "registry_hash": valid_reference["registry_hash"],
        "selected_records": valid_reference["selected_records"],
        "analysis": valid_reference["analysis"],
    }
    assert simple_scores_module._canonical_cash_request(
        valid_reference,
        valid_identity,
        benchmark_registry=valid_registry,
    ) is not None

    unavailable_registry = _available_registry(peer_status="unavailable")
    malformed = _available_reference(peer=True)
    peer = unavailable_registry.peer_sets[0]
    malformed["registry_hash"] = unavailable_registry.as_payload()["registry_hash"]
    malformed["peer_set"]["status"] = "unavailable"
    malformed["peer_set"]["content_hash"] = peer.digest()
    malformed["selected_records"]["peer_set"] = peer.digest()
    malformed_identity = {
        "registry_hash": malformed["registry_hash"],
        "selected_records": malformed["selected_records"],
        "analysis": malformed["analysis"],
    }
    assert simple_scores_module._canonical_cash_request(
        malformed,
        malformed_identity,
        benchmark_registry=unavailable_registry,
    ) is None


def test_backtest_write_and_readback_checksum_use_the_same_reference_window() -> None:
    config = load_config()
    benchmark_id = config.universe.enabled_ids[0]
    dates = pd.bdate_range("2024-01-01", periods=261)
    rows = [
        {
            "date": dt,
            "etf_id": instrument_id,
            "adjusted_close": 100.0 + index,
            "volume": 1_000_000.0,
        }
        for index, dt in enumerate(dates)
        for instrument_id in config.universe.enabled_ids
        if index > 0 or instrument_id == benchmark_id
    ]
    prices = pd.DataFrame(rows)
    registry = _available_registry(benchmark_id)
    context = resolve_canonical_reference(
        registry,
        analysis_id="backtest-checksum-window",
        purpose="comparison",
        instrument_id=benchmark_id,
        instrument={"asset_class": "equity"},
        currency="EUR",
        horizon_years=1.0,
        start_date=dates[1].date().isoformat(),
        end_date=dates[-1].date().isoformat(),
        decision_time=f"{dates[-1].date().isoformat()}T23:59:59Z",
        reference_portfolio_ids=("reference:test",),
    )
    checksum_prices = services_module._backtest_prices_for_reference(prices, context)
    assert checksum_prices is not None
    report = run_backtest(
        config,
        prices,
        benchmark_data_id=context.benchmark_data_id,
        benchmark_reference=context.projection,
        reference_identity=context.identity,
    )

    assert report.metadata["input_checksum"] == backtest_input_checksum(
        config, checksum_prices, None
    )
    assert report.metadata["input_checksum"] != backtest_input_checksum(config, prices, None)


def test_peer_attribution_uses_digest_bound_members_not_caller_supplied_members() -> None:
    prices = pd.DataFrame(
        [
            {"date": dt, "etf_id": instrument, "adjusted_close": 100.0 + index * slope}
            for index, dt in enumerate(pd.bdate_range("2025-01-01", periods=90))
            for instrument, slope in (("BENCH", 0.2), ("ALT", 0.3), ("PEER", 0.25))
        ]
    )
    attribution = build_benchmark_attribution_lookup(
        prices,
        benchmark_id="BENCH",
        benchmark_reference=_available_reference(peer=True),
        benchmark_registry=_available_registry(),
        peer_member_ids=("FORGED",),
    )
    assert attribution["ALT"]["sector_sample_size"] > 0


def test_context_detaches_nested_instrument_evidence_and_windows_fail_closed() -> None:
    instrument = {"nested": {"labels": ["canonical"]}}
    context = CanonicalReferenceContext(CanonicalBenchmarkRegistry(), instrument=instrument)
    instrument["nested"]["labels"].append("forged")
    assert context.instrument["nested"]["labels"] == ("canonical",)

    with pytest.raises(BacktestDataUnavailableError, match="outside decision time"):
        _declared_calculation_window(
            {
                "status": "available",
                "analysis": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-03",
                    "decision_time": "2025-01-02T23:59:59Z",
                },
            }
        )
    with pytest.raises(BacktestDataUnavailableError, match="calculation window is malformed"):
        _declared_calculation_window({"status": "available", "analysis": {}})


def test_validation_window_excludes_rows_after_decision_cutoff() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=4),
            "etf_id": "ALT",
            "adjusted_close": [100.0, 101.0, 102.0, 103.0],
        }
    )
    context = SimpleNamespace(
        resolution=SimpleNamespace(
            declaration=SimpleNamespace(
                start_date="2025-01-01",
                end_date="2025-01-02",
                decision_time="2025-01-02T23:59:59Z",
            )
        )
    )
    scoped = _clip_to_reference_window(prices, context)
    assert scoped is not None
    assert scoped["date"].tolist() == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02")]


def test_two_observations_do_not_create_regime_correlation() -> None:
    returns = pd.DataFrame({"A": [0.01, 0.02], "B": [0.01, 0.03]})
    assert _average_correlation(returns) is None
