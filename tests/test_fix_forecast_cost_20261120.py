"""Forecast components carry their own as-of; as-of research costs use the paper bots' reference order."""

from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.application import score_backfill
from etf_cockpit.core.config import load_config
from etf_cockpit.models.forecast_scores import forecast_component_maps, forecast_score_details
from etf_cockpit.portfolio.paper_bots_execution import load_execution_config
from etf_cockpit.signals import simple_scores
from tests._pit_listing import verified_listing_history  # noqa: F401
from tests.test_score_backfill import _prices, _run

DECISION = date(2026, 10, 20)


def _baseline_component(forecast_date):
    row = {"model_name": "baseline", "etf_id": "AAA", "horizon_days": 21, "expected_return": 0.03,
           "status": "ok", "model_allowed_in_score": True}
    if forecast_date is not None:
        row["forecast_date"] = pd.Timestamp(forecast_date, tz="UTC")
    forecasts = pd.DataFrame([row])
    component = simple_scores._forecast_component(
        "AAA", "baseline", forecast_component_maps(forecasts), forecast_score_details(forecasts), forecasts
    )
    return simple_scores._attach_component_provenance([component], DECISION.isoformat(), DECISION)[0]


def test_forecast_component_is_aged_by_its_own_forecast_date():
    fresh = _baseline_component(DECISION)
    assert (fresh.score_10 is not None, fresh.as_of_date, fresh.freshness_status) == (True, "2026-10-20", "ok")
    assert _baseline_component(date(2026, 9, 1)).freshness_status == "stale"
    assert _baseline_component(date(2026, 10, 21)).freshness_status == "unavailable"
    undated = _baseline_component(None)
    assert (undated.as_of_date, undated.freshness_status) == (None, "unknown")


def test_as_of_score_costs_use_the_paper_bots_reference_order(monkeypatch):
    expected = float(load_execution_config()[1]["cost_model"]["reference_order_value_eur"])
    seen = []
    build = score_backfill.build_universe_simple_scores

    def capture(*args, **kwargs):
        seen.append(kwargs["as_of_sources"].reference_order_value_eur)
        return build(*args, **kwargs)

    monkeypatch.setattr(score_backfill, "build_universe_simple_scores", capture)
    config = load_config()
    _run(config, _prices(config))
    _digest, material = score_backfill.config_fingerprint(config, None)
    assert seen == [expected]
    assert material["baseline_forecast"]["reference_order_value_eur"] == expected
