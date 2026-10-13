from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application import data_service as ds


def test_candidate_fetch_failure_does_not_fail_configured_forecasts(tmp_path, monkeypatch):
    prices = pd.DataFrame({"etf_id": ["VWCE"], "date": ["2026-10-08"], "adjusted_close": [1.0]})
    monkeypatch.setattr(ds, "load_prices", lambda: prices)
    monkeypatch.setattr(ds, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(ds, "_benchmark_reference_snapshot_inputs", lambda *a, **k: {})
    monkeypatch.setattr(ds, "_reference_context_from_inputs", lambda *a, **k: SimpleNamespace(identity={}))
    monkeypatch.setattr(ds, "_calculation_window", lambda *a, **k: {"start": None})
    monkeypatch.setattr(ds, "_price_snapshot_binding", lambda *a, **k: {"binding": "x"})
    monkeypatch.setattr(ds, "_forecast_request_identity", lambda *a, **k: {"request": "x"})
    monkeypatch.setattr(ds, "_current_universe_revision", lambda: "rev")
    monkeypatch.setattr(ds, "current_settings_revision", lambda: "settings")
    monkeypatch.setattr(ds, "FORECASTS_DIR", tmp_path)
    monkeypatch.setattr(ds, "ForecastService", lambda *a, **k: SimpleNamespace(run_forecasts=lambda *a, **k: pd.DataFrame()))
    monkeypatch.setattr(ds, "_forecast_status_summary", lambda frame: "baseline ok")

    def no_yfinance(*_args, **_kwargs):
        raise RuntimeError("yfinance is not installed.")

    monkeypatch.setattr(ds, "fetch_candidate_prices", no_yfinance)
    config = SimpleNamespace(universe=SimpleNamespace(enabled_ids=["VWCE"]))
    service = ds.DataService(config)

    message = service.run_yfinance_forecasts(use_cache=False)

    assert service.last_operation_succeeded
    assert "Configured ETF forecasts refreshed" in message
    assert "Candidate forecasts skipped: yfinance is not installed." in message
