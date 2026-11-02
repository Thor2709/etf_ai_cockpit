"""Assemble canonical Forecast Lab inputs from one local application snapshot.

Open defaults: use the snapshot's latest forecast rows and prices, and all stored
forecast history. Keeping every historical run lets the application service grade
matured outcomes and walk-forward folds without restricting the view to the latest
forecast file.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from etf_cockpit.application.forecast_service import forecast_lab_inputs, load_forecast_history
from etf_cockpit.core.config import AppConfig


def assemble_forecast_lab_inputs(snapshot: Any) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return combined forecasts, complete history, and snapshot prices for Forecast Lab."""

    latest = getattr(snapshot, "forecasts", None)
    history = load_forecast_history()
    prices = getattr(snapshot, "prices", None)
    if not isinstance(latest, pd.DataFrame):
        latest = pd.DataFrame()
    if not isinstance(history, pd.DataFrame):
        history = pd.DataFrame()
    if not isinstance(prices, pd.DataFrame):
        prices = pd.DataFrame()
    combined = forecast_lab_inputs(latest, history, prices)
    return combined, history, prices


def load_forecast_model_diagnostics(config: AppConfig) -> list[Any]:
    """Load model readiness through the application boundary."""

    from etf_cockpit.models.registry import model_diagnostics

    return model_diagnostics(config)
