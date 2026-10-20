"""Issue #991: forecast and model view-model contracts (quantile keys, horizon axis, basis, labels, availability)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from etf_cockpit.application.ui_views import forecast_lab as lab_view
from etf_cockpit.application.ui_views.stock_research import build_stock_view
from etf_cockpit.features.forecast_lab import _horizon_diagnostics


def _prices(periods: int = 40, ratio: float = 0.5) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=periods)
    close = pd.Series(range(100, 100 + periods), dtype=float)
    return pd.DataFrame({"etf_id": "A", "date": dates, "close": close, "adjusted_close": close * ratio})


def _row(forecast_date: pd.Timestamp, horizon: int = 5, **overrides: object) -> dict[str, object]:
    row = {"etf_id": "A", "model_name": "toto", "forecast_date": forecast_date, "horizon_days": horizon,
           "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1}
    row.update(overrides)
    return row


def test_chart_reads_canonical_q10_return_keys() -> None:  # E109-N001
    prices = _prices()
    origin = prices["date"].iloc[-3]
    view = build_stock_view(prices, pd.DataFrame([_row(origin, q10_return=-0.2, q90_return=0.3)]), "A", "1Y")
    anchor = float(prices["adjusted_close"].iloc[-3])
    assert len(view.forecasts) == 1
    assert view.forecasts[0].q10 == [pytest.approx(anchor * math.exp(-0.2))]
    assert view.forecasts[0].q90 == [pytest.approx(anchor * math.exp(0.3))]
    legacy = pd.DataFrame([_row(origin)]).rename(columns={"q10_return": "q10", "q50_return": "q50", "q90_return": "q90"})
    assert build_stock_view(prices, legacy, "A", "1Y").forecasts == []  # non-canonical keys fail closed


def test_trading_day_horizon_axis_counts_sessions_not_calendar_days() -> None:  # E109-N003
    prices = _prices()
    origin = prices["date"].iloc[-3]  # a weekday
    view = build_stock_view(prices, pd.DataFrame([_row(origin, horizon=10)]), "A", "1Y")
    target = view.forecasts[0].dates[0]
    assert target == origin + pd.offsets.BDay(10)
    assert target != origin + pd.Timedelta(days=10)
    assert target.weekday() < 5


def test_chart_and_fan_use_the_adjusted_basis_of_the_return_tiles() -> None:  # E109-N002
    prices = _prices(ratio=0.5)
    origin = prices["date"].iloc[-3]
    view = build_stock_view(prices, pd.DataFrame([_row(origin)]), "A", "1Y")
    assert view.close == [pytest.approx(v) for v in prices["adjusted_close"]]
    assert view.total_return == pytest.approx(prices["adjusted_close"].iloc[-1] / prices["adjusted_close"].iloc[0] - 1.0)
    assert view.forecasts[0].q50 == [pytest.approx(float(prices["adjusted_close"].iloc[-3]))]


def test_forecast_horizons_are_strictly_increasing_and_conflicting_duplicates_dropped() -> None:  # E013 monotonic horizon
    prices = _prices()
    origin = prices["date"].iloc[-3]
    rows = [_row(origin, 20), _row(origin, 5), _row(origin, 5), _row(origin, 10), _row(origin, 10, q90_return=0.4)]
    line = build_stock_view(prices, pd.DataFrame(rows), "A", "1Y").forecasts[0]
    assert line.dates == sorted(set(line.dates))
    assert line.dates == [origin + pd.offsets.BDay(5), origin + pd.offsets.BDay(20)]  # the conflicting 10 is not drawn


@pytest.mark.parametrize(
    ("coverage", "low", "high", "label"),
    [
        (0.84, 0.70, 0.93, "Inconclusive"),  # interval keeps the target, point coverage below it: not Good (E113-N002)
        (0.92, 0.82, 0.96, "Good"),
        (0.70, 0.55, 0.80, "Poor"),
        (None, 0.5, 0.9, "n/a"),
        (0.9, None, 0.9, "n/a"),
    ],
)
def test_inconclusive_wilson_calibration_is_not_good(coverage, low, high, label) -> None:
    assert lab_view.calibration_label(coverage, low, high)[0] == label


def test_failed_only_model_is_not_available_without_registry_status() -> None:  # E113-N004
    models = pd.DataFrame({"model_name": ["toto", "timesfm", "baseline"], "ok_rows": [0, 3, 0]})
    assert lab_view.model_available("toto", models, {}, None) is False
    assert lab_view.model_available("timesfm", models, {}, None) is True
    assert lab_view.model_available("baseline", models, {}, None) is True
    assert lab_view.model_available("toto", models, {"toto": True}, None) is True  # registry status wins when present
    assert lab_view.model_available("toto", models, {}, False) is False
    assert lab_view.model_available("missing", models, {}, None) is False


def test_failed_horizon_is_not_counted_as_covered() -> None:  # E113-N003
    group = pd.DataFrame(
        {"horizon_days": [5, 10, 10], "status": ["ok", "failed", "failed"], "reason_unavailable": [None, "model_error", "model_error"]}
    )
    observed, skipped = _horizon_diagnostics(group, pd.DataFrame(columns=["outcome_status", "outcome_reason", "horizon_days"]), [5, 10, 21])
    assert observed == [5]
    reasons = {item["horizon_days"]: item["reason"] for item in skipped}
    assert reasons[10] == "forecast_failed: model_error"
    assert reasons[21] == "no_forecast_row"


def test_runs_table_shows_newest_runs_first() -> None:  # E013 oldest runs shown
    runs = pd.DataFrame({"run_id": [f"r{i:02d}" for i in range(30)], "as_of_date": pd.date_range("2026-01-01", periods=30).strftime("%Y-%m-%d")})
    shown = lab_view.recent_runs(runs, 5)
    assert list(shown["run_id"]) == ["r29", "r28", "r27", "r26", "r25"]
