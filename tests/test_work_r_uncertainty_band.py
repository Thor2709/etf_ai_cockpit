"""Work-R: the uncertainty gate evaluates from the model band and coverage, and stays closed without them."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import _forecast_to_row
from etf_cockpit.core.config import load_config
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import forecast_return_distributions
from etf_cockpit.models.uncertainty import decompose_forecast_uncertainty, uncertainty_gate_reasons

FORECAST_DATE = date(2026, 9, 30)


def _prices(days: int = 300, seed: int = 3) -> pd.Series:
    index = pd.bdate_range(end=pd.Timestamp(FORECAST_DATE), periods=days)
    steps = np.random.default_rng(seed).normal(0.0004, 0.01, days)
    return pd.Series(100.0 * np.exp(np.cumsum(steps)), index=index)


def test_missing_coverage_keeps_the_gate_closed_with_its_reason() -> None:
    row = _forecast_to_row(baseline_forecast("ETF", _prices(), [60], FORECAST_DATE, "r")[0])
    row["coverage_ratio"] = None
    settings = load_config().models.forecast_uncertainty
    distribution = forecast_return_distributions(pd.DataFrame([row]), horizon_days=60, decision_time=FORECAST_DATE)["ETF"]
    assessment = decompose_forecast_uncertainty(distribution, settings, base_confidence=0.6)
    assert assessment["status"] == "unavailable"
    assert "Coverage ratio is unavailable" in str(assessment["reason"])
    assert uncertainty_gate_reasons(assessment, settings, effective_confidence=0.6) == ["forecast_uncertainty_unavailable"]


def test_end_to_end_uncertainty_is_available_for_a_fully_populated_instrument() -> None:
    rows = [_forecast_to_row(row) for row in baseline_forecast("ETF", _prices(), [60], FORECAST_DATE, "r")]
    frame = pd.DataFrame(rows)
    distribution = forecast_return_distributions(frame, horizon_days=60, decision_time=FORECAST_DATE)["ETF"]
    assert distribution["coverage_ratio"] == 1.0
    band = distribution["uncertainty_band"]
    assert band is not None and band["q10_return"] < band["q90_return"]
    settings = load_config().models.forecast_uncertainty
    assessment = decompose_forecast_uncertainty(distribution, settings, base_confidence=0.6)
    assert assessment["status"] == "available", assessment["reason"]
    assert assessment["aleatoric_uncertainty"] == pytest.approx(band["q90_return"] - band["q10_return"])
    assert uncertainty_gate_reasons(assessment, settings, effective_confidence=0.6) == []

    # An incomplete model row (no q05) closes the band and the gate with its reason.
    closed = forecast_return_distributions(frame.assign(q05_return=np.nan), horizon_days=60, decision_time=FORECAST_DATE)["ETF"]
    assert closed["uncertainty_band"] is None
    assert decompose_forecast_uncertainty(closed, settings, base_confidence=0.6)["status"] == "unavailable"
