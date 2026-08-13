from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from etf_cockpit.application.benchmark_reference import (
    CanonicalReferenceContext,
    unavailable_reference_projection,
)
from etf_cockpit.features.regime import (
    build_benchmark_attribution_lookup,
    build_market_regime,
    build_portfolio_fit_lookup,
)
from etf_cockpit.services import (
    _cache_matches_universe,
    _postprocess_forecast_benchmark_fields,
    _write_universe_cache_metadata,
)
from etf_cockpit.models.forecast_scores import (
    filter_forecasts_for_universe,
    latest_forecast_file,
    load_latest_forecasts,
)
from etf_cockpit.services import SignalService
from etf_cockpit.signals import simple_scores as simple_scores_module
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    unavailable_reference_projection as contract_unavailable_reference_projection,
)
from etf_cockpit.portfolio.attribution import _unavailable_reference_projection as attribution_unavailable_reference_projection


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=260)
    return pd.DataFrame(
        [
            {"date": dt, "etf_id": instrument, "adjusted_close": 100.0 + index * slope}
            for instrument, slope in (("ALT", 0.10), ("BENCH", 0.20))
            for index, dt in enumerate(dates)
        ]
    )


def test_relative_consumers_require_explicit_canonical_benchmark_and_cash_resolution() -> None:
    prices = _prices()
    assert build_market_regime(prices)["regime_score_10"] is None
    assert all(row["score"] is None for row in build_portfolio_fit_lookup(prices).values())
    assert all(row["benchmark_return"] is None for row in build_benchmark_attribution_lookup(prices).values())

    reordered = prices.sort_values(["date", "etf_id"], ascending=[True, False])
    first = build_benchmark_attribution_lookup(reordered, benchmark_id="BENCH")
    second = build_benchmark_attribution_lookup(prices, benchmark_id="BENCH")
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

    metadata = {
        "universe_revision": "universe",
        "settings_revision": "settings",
        "reference_identity": identity,
        "reference_identity_hash": _reference_identity_hash(identity),
    }
    path.with_name(f"{path.name}.meta.json").write_text(json.dumps(metadata), encoding="utf-8")
    exact = {"source_file": str(path), "etf_id": "BENCH"}
    assert latest_forecast_file(
        directory=tmp_path,
        pattern="forecast_results_*.csv",
        universe_revision="universe",
        settings_revision="settings",
        reference_identity=identity,
    ) == path
    loaded = load_latest_forecasts(
        directory=tmp_path,
        pattern="forecast_results_*.csv",
        universe_revision="universe",
        settings_revision="settings",
        reference_identity=identity,
    )
    assert len(loaded) == 1
    assert filter_forecasts_for_universe(
        pd.DataFrame([exact]),
        "universe",
        "settings",
        reference_identity={**identity, "status": "available"},
    ).empty
    assert len(
        filter_forecasts_for_universe(
            pd.DataFrame([exact]),
            "universe",
            "settings",
            reference_identity=identity,
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


def test_signal_service_binds_forecast_read_to_current_reference_identity(monkeypatch) -> None:
    import etf_cockpit.services as services_module

    captured: dict[str, object] = {}
    prices = pd.DataFrame([{"date": date(2025, 1, 2), "etf_id": "VWCE", "adjusted_close": 100.0}])
    monkeypatch.setattr(services_module, "load_prices", lambda: prices.copy())
    monkeypatch.setattr(services_module, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(services_module.DataService, "validate_prices", lambda *args, **kwargs: object())
    monkeypatch.setattr(services_module, "model_availability", lambda config: {"toto": False, "timesfm": False})
    monkeypatch.setattr(services_module, "_load_structure_caps", lambda *args, **kwargs: {})
    monkeypatch.setattr(services_module, "generate_signals", lambda *args, **kwargs: [])

    def capture_forecasts(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(services_module, "load_latest_forecasts", capture_forecasts)
    SignalService(load_config()).generate_signals(
        as_of_date=date(2025, 1, 2),
        features=pd.DataFrame(columns=["date", "etf_id"]),
    )
    assert isinstance(captured.get("reference_identity"), dict)
    assert captured["reference_identity"]["schema"] == "benchmark-reference-cache.v1"


def test_simple_score_candidate_loader_passes_reference_identity(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(simple_scores_module, "load_latest_candidate_report", lambda: (pd.DataFrame(), None))
    monkeypatch.setattr(simple_scores_module, "load_forecast_history", lambda: pd.DataFrame())

    def capture_forecasts(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(simple_scores_module, "load_latest_forecasts", capture_forecasts)
    identity = {"schema": "benchmark-reference-cache.v1", "execution_allowed": False}
    build_simple_instrument_scores(
        load_config(),
        [],
        pd.DataFrame(),
        pd.DataFrame(),
        reference_identity=identity,
    )
    assert captured["reference_identity"] == identity


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
