from datetime import date
from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import numpy as np
import pandas as pd

from etf_cockpit.application import filing_ingestion, forecast_service, sec_bulk_import, signal_service
from etf_cockpit.application.forecast_service import ForecastService, _apply_promotion
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.models.model_promotion import COUNTING, ModelPromotion


def test_forecasts_use_promotion_prices_for_evidence(tmp_path, monkeypatch):
    config = forecast_service._config_with_optional_models_disabled(load_config())
    config.models.promotion.enabled = False
    context = SimpleNamespace(resolution=None, benchmark_data_id=None, identity={})
    service = ForecastService(config, reference_context=context)
    candidate_prices = pd.DataFrame(
        {"date": pd.bdate_range(end="2026-10-20", periods=40), "etf_id": "CANDIDATE", "adjusted_close": np.arange(40) + 100.0}
    )
    promotion_prices = pd.DataFrame(
        {"date": pd.bdate_range(end="2026-10-20", periods=40), "etf_id": "UNIVERSE", "adjusted_close": np.arange(40) + 200.0}
    )
    captured = {}

    monkeypatch.setattr(forecast_service, "current_settings_identity", lambda: {"settings_revision": "a" * 64})
    monkeypatch.setattr(forecast_service, "settings_bound_run_id", lambda run_id, *, settings_identity: run_id)
    monkeypatch.setattr(forecast_service, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(forecast_service, "_price_snapshot_binding", lambda *_args, **_kwargs: {"binding": "test"})
    monkeypatch.setattr(forecast_service, "timed_step", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(forecast_service, "baseline_forecast", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_run_timesfm_forecasts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_run_toto_forecasts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_write_forecasts", lambda *_args, **_kwargs: None)

    def capture_evidence(rows, _as_of_date, prices):
        captured["evidence_prices"] = prices.copy()
        return rows

    def capture_probabilities(rows, _as_of_date, prices):
        captured["probability_prices"] = prices.copy()
        return {}

    monkeypatch.setattr(service, "_evidence_gated_forecasts", capture_evidence)
    monkeypatch.setattr(service, "_probability_statuses", capture_probabilities)

    service.run_forecasts(
        date(2026, 10, 20), ["CANDIDATE"], candidate_prices,
        horizons=[1], output_path=tmp_path / "forecasts.csv", promotion_prices=promotion_prices,
    )

    assert captured["evidence_prices"]["etf_id"].unique().tolist() == ["UNIVERSE"]
    assert captured["probability_prices"]["etf_id"].unique().tolist() == ["UNIVERSE"]


def test_timesfm_forecasts_fail_closed_on_stale_history_at_canonical_cutoff(monkeypatch):
    as_of = date(2026, 10, 20)
    decision_time = "2026-10-20T23:59:59+00:00"
    prices = pd.DataFrame({"date": [pd.Timestamp("2026-10-01", tz="UTC")], "etf_id": ["ETF"], "adjusted_close": [100.0]})
    pivot = prices.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
    pivot.attrs["decision_time"] = decision_time
    pivot.attrs["timesfm_price_rows"] = {"ETF": prices}
    captured = {}
    original = forecast_service._baseline_price_series

    def capture_gate(frame, etf_id, forecast_date, *, decision_time=None):
        captured["decision_time"] = decision_time
        return original(frame, etf_id, forecast_date, decision_time=decision_time)

    monkeypatch.setattr(forecast_service, "_baseline_price_series", capture_gate)
    rows = ForecastService(load_config())._run_timesfm_forecasts(pivot, ["ETF"], [1], as_of, "run")

    assert captured["decision_time"] == decision_time
    assert rows and all(row.status == "unavailable" for row in rows)
    assert all(row.reason_unavailable == "stale_adjusted_price_session_history" for row in rows)


def test_signal_service_uses_canonical_time_and_raw_prices_for_shadow_guard(monkeypatch):
    config = load_config()
    instrument_id = config.universe.enabled_ids[0]
    feature_frame = pd.DataFrame({"etf_id": [instrument_id], "feature_marker": [1]})
    raw_prices = pd.DataFrame(
        {
            "date": ["2026-01-02"], "etf_id": [instrument_id], "open": [99.0], "high": [101.0],
            "low": [98.0], "close": [100.0], "volume": [1000], "adjusted_close": [100.0],
        }
    )
    reference_context = SimpleNamespace(identity={"reference": "test"})
    captured = {}
    decision_time = "2026-01-02T23:59:59+00:00"

    monkeypatch.setattr(signal_service, "load_prices", lambda **_kwargs: raw_prices.copy())
    monkeypatch.setattr(signal_service, "load_holdings", lambda **_kwargs: pd.DataFrame())
    monkeypatch.setattr(signal_service, "_benchmark_reference_snapshot_inputs", lambda *_args: {})
    monkeypatch.setattr(signal_service, "_reference_context_from_inputs", lambda *_args, **_kwargs: reference_context)
    monkeypatch.setattr(
        signal_service, "_calculation_window",
        lambda *_args, **_kwargs: {"start_date": "2026-01-02", "end_date": "2026-01-02", "decision_time": decision_time},
    )
    monkeypatch.setattr(signal_service, "_price_snapshot_binding", lambda *_args, **_kwargs: {"binding": "test"})
    monkeypatch.setattr(signal_service, "_current_universe_revision", lambda: "revision")
    monkeypatch.setattr(signal_service, "current_settings_revision", lambda: "settings")
    monkeypatch.setattr(signal_service, "configured_forecast_request_identity", lambda _config: "request")
    monkeypatch.setattr(signal_service, "_feature_cache_binding", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(signal_service, "load_features", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(signal_service.FeatureService, "fx_binding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal_service.FeatureService, "compute_features", lambda *_args, **_kwargs: feature_frame.copy())
    monkeypatch.setattr(signal_service, "latest_features", lambda *_args, **_kwargs: feature_frame.copy())
    monkeypatch.setattr(signal_service.DataService, "validate_prices", lambda *_args, **_kwargs: SimpleNamespace(issues=[]))
    monkeypatch.setattr(signal_service, "model_availability", lambda _config: {"toto": False, "timesfm": False})
    monkeypatch.setattr(signal_service, "load_latest_forecasts", lambda **_kwargs: pd.DataFrame())
    monkeypatch.setattr(signal_service, "_load_structure_caps", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(signal_service, "forecast_component_maps", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(signal_service, "forecast_return_distributions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(signal_service, "load_forecast_history", lambda: pd.DataFrame())

    def capture_signals(_config, _latest, *_args, **kwargs):
        captured["decision_time"] = kwargs["decision_time"]
        return []

    def capture_shadow(_config, _signals, **kwargs):
        captured["price_history"] = kwargs["price_history"]

    monkeypatch.setattr(signal_service, "generate_signals", capture_signals)
    monkeypatch.setattr(signal_service, "_run_decision_shadow_guard", capture_shadow)

    signal_service.SignalService(config).generate_signals(date(2026, 1, 2))

    assert captured["decision_time"] == pd.Timestamp(decision_time)
    assert {"open", "high", "low", "close", "volume"}.issubset(captured["price_history"].columns)
    assert "feature_marker" not in captured["price_history"].columns


def test_sec_identity_resolution_rejects_null_and_reverse_mappings(tmp_path, monkeypatch):
    identity_path = tmp_path / "identity.parquet"
    identity_path.write_bytes(b"fixture")
    monkeypatch.setattr(filing_ingestion, "IDENTITY_PATH", identity_path)
    registry = pd.DataFrame({"cik": ["1"], "instrument_id": [np.nan]})
    monkeypatch.setattr(pd, "read_parquet", lambda _path: registry)

    assert filing_ingestion._resolve_sec_instrument("0000000001") is None
    assert filing_ingestion._sec_identity_matches("0000000001", "TARGET") is False

    registry = pd.DataFrame({"cik": ["1", "2"], "instrument_id": ["TARGET", "TARGET"]})
    assert filing_ingestion._resolve_sec_instrument("0000000001") is None
    assert filing_ingestion._sec_identity_matches("0000000001", "TARGET") is False


def test_optional_promotion_shadows_rows_and_rejects_pre_evidence_origins():
    row = ForecastResult(
        "run", "timesfm3", "v", "ETF", date(2025, 6, 2), 60, 0.02, 0.02,
        target_id="adj_close_log_return_60d",
    )
    open_window = ModelPromotion(
        "timesfm3", COUNTING, "test", model_version="v", evidence_after="2024-01-01", evidence_horizon_days=60,
    )
    closed_window = ModelPromotion(
        "timesfm3", COUNTING, "test", model_version="v", evidence_after="2026-01-01", evidence_horizon_days=60,
    )

    shadowed = _apply_promotion(row, {"timesfm3": open_window}, True)
    prewindow = _apply_promotion(row, {"timesfm3": closed_window}, False)

    assert shadowed.model_allowed_in_score is False and shadowed.promotion_status == "shadow_only"
    assert prewindow.model_allowed_in_score is False


def test_bulk_sec_import_scopes_vendor_claims_and_fails_closed_without_instrument_id(tmp_path, monkeypatch):
    fundamentals_path = tmp_path / "fundamentals.parquet"
    fundamentals_path.write_bytes(b"fixture")
    monkeypatch.setattr(filing_ingestion, "CLEAN_DIR", tmp_path)
    with monkeypatch.context() as context:
        context.setattr(
            pd,
            "read_parquet",
            lambda _path: pd.DataFrame({"concept": ["Assets"], "period": ["2024-12-31"], "unit": ["USD"]}),
        )
        assert filing_ingestion._load_vendor_statement_claims("TARGET") == ()

    claims = ({"instrument_id": "TARGET", "concept": "Assets", "period": "2024-12-31", "unit": "USD", "value": 12},)
    monkeypatch.setattr(filing_ingestion, "_load_vendor_statement_claims", lambda instrument_id: claims if instrument_id == "TARGET" else ())
    captured = {}

    def capture_write(_source, _records, _facts, _inventory, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(sec_bulk_import, "write_statement_evidence", capture_write)
    archive = tmp_path / "companyfacts.zip"
    facts = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "Assets": {"units": {"USD": [{"val": 10, "end": "2024-12-31", "form": "10-K", "filed": "2025-01-01"}]}}
            }
        },
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("CIK0000000001.json", json.dumps(facts))
    identity = CanonicalIdentity("TARGET", "TARGET", None, "needs_verification", "", None, None, "stock", {}, "manual_review", (), "1")

    result = sec_bulk_import.import_sec_companyfacts_bulk(
        archive, (identity,), cache_dir=tmp_path / "cache", facts_destination=tmp_path / "facts.parquet",
        inventory_destination=tmp_path / "inventory.parquet",
    )

    assert result.per_cik[0].status == "imported"
    assert captured["vendor_records"] == claims
