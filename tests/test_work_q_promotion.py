"""Automatic, evidence-based promotion of optional forecast models (work-Q)."""

from __future__ import annotations

import pytest
from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.application.forecast_service import (
    ForecastService,
    _apply_promotion,
    _forecast_to_row,
)
from etf_cockpit.core.config import ModelPromotionSettings, load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.models.model_promotion import COUNTING, NOT_PROVEN, evaluate_model_promotions

HORIZON = 60
SETTINGS = ModelPromotionSettings()
INSTRUMENTS = ["E1", "E2", "E3", "E4"]
SESSIONS = pd.bdate_range("2023-01-02", periods=900)


def _prices() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    frames = [
        pd.DataFrame({"etf_id": etf, "date": SESSIONS, "adjusted_close": 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(SESSIONS))))})
        for etf in INSTRUMENTS
    ]
    return pd.concat(frames, ignore_index=True)


def _forecasts(prices: pd.DataFrame, origins: dict[str, list[str]], *, model_accurate: bool = True) -> pd.DataFrame:
    """The baseline predicts the wrong direction; the model is accurate, or equally wrong."""

    rows = []
    for etf, group in prices.groupby("etf_id"):
        series = group.set_index("date")["adjusted_close"]
        for model, days in origins.items():
            for day in days:
                start = series.index.get_loc(pd.Timestamp(day))
                # An origin whose target session is not yet priced stays unmatured; its value is irrelevant.
                actual = 0.01 if start + HORIZON >= len(series) else float(np.log(series.iloc[start + HORIZON] / series.iloc[start]))
                for name, expected in (("baseline", -0.5 * actual), (model, 0.9 * actual if model_accurate else -0.5 * actual)):
                    rows.append({"run_id": f"r-{day}", "model_name": name, "model_version": "v", "created_at": (pd.Timestamp(day) - pd.Timedelta(days=1 if name == "timesfm3" else 0)).isoformat(), "etf_id": etf, "forecast_date": day, "horizon_days": HORIZON, "target_id": f"adj_close_log_return_{HORIZON}d", "expected_return": expected, "status": "ok"})
    return pd.DataFrame(rows).drop_duplicates(["model_name", "etf_id", "forecast_date"])


def _days(first: str, count: int, step: int = 5) -> list[str]:
    start = SESSIONS.get_loc(pd.Timestamp(first))
    return [SESSIONS[start + step * i].date().isoformat() for i in range(count)]


def _decide(forecasts: pd.DataFrame, prices: pd.DataFrame, as_of: str | None = None) -> dict:
    return evaluate_model_promotions(forecasts, prices, date.fromisoformat(as_of) if as_of else prices["date"].max().date(), SETTINGS)


def _checkpoint_settings(tmp_path, model_name="timesfm3"):
    checkpoint = tmp_path / f"{model_name}-checkpoint"
    checkpoint.mkdir(exist_ok=True)
    (checkpoint / "config.json").write_text("{}", encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"verified fixture weights")
    return {model_name: {"model_path": str(checkpoint)}}


def _row(model: str) -> ForecastResult:
    return ForecastResult("r", model, "v", "E1", date(2025, 6, 2), HORIZON, 0.02, 0.02, target_id=f"adj_close_log_return_{HORIZON}d")


def test_model_below_the_evidence_minimum_is_not_counted(tmp_path) -> None:
    prices = _prices()
    decision = _decide(_forecasts(prices, {"timesfm3": _days("2024-01-02", 6)}), prices)["timesfm3"]
    assert decision.state == NOT_PROVEN and not decision.counting
    assert decision.matured_forecasts == 24 and decision.required_forecasts == 100
    assert "24 of 100 matured forecasts" in decision.reason
    row = _apply_promotion(_row("timesfm3"), {"timesfm3": decision}, False)
    assert row.model_allowed_in_score is False and row.promotion_status == NOT_PROVEN
    assert row.calibration_status in {"good", "mixed", "weak", "limited"}
    assert _forecast_to_row(row, {"timesfm3": decision}, _checkpoint_settings(tmp_path))["promotion_state"] == NOT_PROVEN


def test_model_beating_the_baseline_after_its_cutoff_is_counted(tmp_path) -> None:
    prices = _prices()
    decision = _decide(_forecasts(prices, {"timesfm3": _days("2023-12-04", 30)}), prices)["timesfm3"]
    assert decision.state == COUNTING, decision.reason
    assert decision.matured_forecasts == 120 and decision.forecast_origins == 30
    assert decision.model_mase < decision.baseline_mase and decision.model_directional > decision.baseline_directional
    row = _apply_promotion(_row("timesfm3"), {"timesfm3": decision}, False)
    assert row.model_allowed_in_score is True and row.oos_mase == decision.model_mase
    stored = _forecast_to_row(row, {"timesfm3": decision}, _checkpoint_settings(tmp_path))
    assert stored["promotion_state"] == COUNTING and stored["promotion_evidence_allowed"] is True
    assert stored["contamination_status"] == "after_declared_cutoff" and stored["execution_allowed"] is False
    # The service decides from stored history; the same evidence with a worse model never counts.
    served = ForecastService(load_config()).evaluate_promotions(prices["date"].max().date(), prices, history=_forecasts(prices, {"timesfm": _days("2024-01-02", 31)}))
    assert served["timesfm"].counting and not served["toto"].counting
    worse = _decide(_forecasts(prices, {"timesfm3": _days("2023-12-04", 30)}, model_accurate=False), prices)["timesfm3"]
    assert worse.state == NOT_PROVEN and "does not beat the baseline" in worse.reason


def test_pre_cutoff_and_first_run_windows_never_count() -> None:
    prices = _prices()
    # timesfm3: 30 perfect dates on or before its 2023-11-30 cutoff, only 2 afterwards.
    leaked = _decide(_forecasts(prices, {"timesfm3": _days("2023-03-01", 30) + _days("2024-01-02", 2)}), prices)["timesfm3"]
    assert leaked.state == NOT_PROVEN and leaked.matured_forecasts == 8
    assert leaked.excluded_pre_cutoff == 120 and leaked.evidence_after == "2023-11-30"
    # toto has no published cutoff: its first local run date (the first stored forecast) is excluded too.
    toto = _forecasts(prices, {"toto": _days("2024-01-02", 31)})
    unknown = _decide(toto, prices)["toto"]
    assert unknown.first_local_run == "2024-01-02" and unknown.excluded_pre_cutoff == 4
    assert unknown.forecast_origins == 30 and unknown.state == COUNTING
    # Prices after the as-of date cannot mature forecasts (no look-ahead).
    early = _decide(toto, prices, as_of="2024-03-01")["toto"]
    assert early.matured_forecasts == 0 and early.state == NOT_PROVEN


@pytest.mark.usefixtures("synthetic_sample_opt_in")
def test_run_forecasts_applies_the_decision_to_stored_rows(tmp_path, monkeypatch) -> None:
    from etf_cockpit.application.forecast_service import _config_with_optional_models_disabled
    from etf_cockpit.application.reference_context import _benchmark_reference_snapshot_inputs, _reference_context_from_inputs
    from etf_cockpit.data.duckdb_store import load_holdings, load_prices
    from etf_cockpit.models.model_promotion import ModelPromotion

    config = _config_with_optional_models_disabled(load_config())
    prices = load_prices()
    as_of = pd.to_datetime(prices["date"]).max().date()
    context = _reference_context_from_inputs(
        _benchmark_reference_snapshot_inputs(config, as_of, load_holdings()), purpose="comparison", analysis_id="work-q"
    )
    etf = config.universe.enabled_ids[0]
    seen = {}
    config.models.models["timesfm"] = {**dict(config.models.models.get("timesfm") or {}), **_checkpoint_settings(tmp_path, "timesfm")["timesfm"]}
    # Calibration-evidence sufficiency has its own tests (test_forecast_honesty); this one covers promotion.
    monkeypatch.setattr("etf_cockpit.application.forecast_service.horizon_calibration_scores", lambda frame: pd.DataFrame({"status": ["ok"]}))

    def fake_timesfm(self, pivot, etf_ids, horizons, as_of_date, run_id, *, model_name="timesfm"):
        return [ForecastResult(run_id, "timesfm", "v", etf, as_of_date, horizons[0], 0.02, None, q10_return=-0.1, q90_return=0.1)]

    def run(state: str):
        monkeypatch.setattr(ForecastService, "_run_timesfm_forecasts", fake_timesfm)
        decision = ModelPromotion("timesfm", state, "test", matured_forecasts=120, required_forecasts=100, evidence_after="2020-01-01", model_version="v")

        def evaluate(self, as_of_date, evidence_prices, history=None):
            seen["first_price_day"] = pd.to_datetime(evidence_prices["date"], utc=True).min().tz_localize(None)
            return {"timesfm": decision}

        monkeypatch.setattr(ForecastService, "evaluate_promotions", evaluate)
        output = tmp_path / f"{state}.csv"
        ForecastService(config, reference_context=context).run_forecasts(as_of, [etf], prices, output_path=output, horizons=[60])
        stored = pd.read_csv(output)
        return stored.loc[stored["model_name"].eq("timesfm")].iloc[0]

    counted, unproven = run(COUNTING), run(NOT_PROVEN)
    assert bool(counted["model_allowed_in_score"]) and counted["promotion_state"] == COUNTING
    assert not bool(unproven["model_allowed_in_score"]) and unproven["promotion_state"] == NOT_PROVEN
    assert unproven["execution_allowed"] in (False, "False")
    # The decision is graded on the full stored history, not the shorter forecast calculation window.
    assert seen["first_price_day"] == pd.to_datetime(prices["date"]).min()
