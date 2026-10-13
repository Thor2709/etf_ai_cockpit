"""Forecast Lab honesty fixes: permutation-stable MASE, retrospective labels, simple-return display, insight wording."""

from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.app.pages import forecast_lab as page
from etf_cockpit.application.ui_views.forecast_lab import ErrorSeries
from etf_cockpit.features.forecast_lab import (
    EVIDENCE_BASIS_RETROSPECTIVE,
    build_forecast_lab_report,
    normalise_evidence_basis,
)
from etf_cockpit.models.calibration import _mase_scale

DATES = pd.bdate_range("2026-01-01", periods=60)


def _prices() -> pd.DataFrame:
    frames = []
    for etf_id, vol in (("AAA", 0.004), ("BBB", 0.02)):
        wave = np.sin(np.arange(len(DATES)) * (1.3 if etf_id == "AAA" else 0.7)) * vol
        frames.append(pd.DataFrame({"etf_id": etf_id, "date": DATES, "adjusted_close": 100.0 * np.exp(np.cumsum(wave))}))
    return pd.concat(frames, ignore_index=True)


def _forecasts() -> pd.DataFrame:
    rows = []
    for etf_id in ("AAA", "BBB"):
        for horizon in (1, 5):
            for index, forecast_date in enumerate(DATES[:20]):
                rows.append(
                    {
                        "run_id": "run-1", "model_name": "naive_drift", "etf_id": etf_id, "forecast_date": forecast_date,
                        "horizon_days": horizon, "expected_return": 0.001 * horizon * (1 + index % 3),
                        "q10_return": -0.03, "q90_return": 0.03, "status": "ok",
                    }
                )
    return pd.DataFrame(rows)


def _model_row(report: dict[str, object]) -> pd.Series:
    return report["models"].set_index("model_name").loc["naive_drift"]


def test_mase_is_row_order_stable_and_matches_promotion_definition() -> None:
    prices, forecasts = _prices(), _forecasts()
    report = build_forecast_lab_report(forecasts, prices)
    shuffled = build_forecast_lab_report(forecasts.sample(frac=1.0, random_state=7).reset_index(drop=True), prices)
    assert _model_row(report)["mase"] == _model_row(shuffled)["mase"]
    assert _model_row(report)["mae"] == _model_row(shuffled)["mae"]

    outcomes = report["forecast_outcomes"].query("outcome_status == 'matured'")
    merged = outcomes.merge(forecasts, on=["etf_id", "forecast_date", "horizon_days", "model_name"])
    series = {e: g.set_index("date")["adjusted_close"] for e, g in prices.groupby("etf_id")}
    scaled = [
        abs(row.expected_return - row.actual_return) / _mase_scale(series[row.etf_id], int(row.horizon_days))
        for row in merged.itertuples()
    ]
    assert len(scaled) == len(outcomes) > 0
    assert abs(_model_row(report)["mase"] - np.mean(scaled)) < 1e-3
    unscaled = np.mean([abs(r.expected_return - r.actual_return) for r in merged.itertuples()])
    assert abs(_model_row(report)["mae"] - unscaled) < 1e-3
    assert _model_row(report)["mase_method"] == "per_instrument_horizon_naive_scale"


def test_walk_forward_rows_are_labelled_retrospective_not_out_of_fold() -> None:
    report = build_forecast_lab_report(_forecasts(), _prices())
    outcomes = report["forecast_outcomes"]
    assert "out_of_fold" not in outcomes.columns
    assert set(outcomes["evidence_basis"]) <= {EVIDENCE_BASIS_RETROSPECTIVE, "ungrouped"}
    assert EVIDENCE_BASIS_RETROSPECTIVE in set(outcomes["evidence_basis"])
    notes = " ".join(report["notes"])
    assert "retrospective date groups" in notes and "not prospective" in notes
    legacy = normalise_evidence_basis(pd.DataFrame({"out_of_fold": [True, "False"]}))
    assert legacy["evidence_basis"].tolist() == [EVIDENCE_BASIS_RETROSPECTIVE, "ungrouped"]


def test_ui_shows_log_return_as_simple_return() -> None:
    assert page._simple_return_text(0.10) == "+10.52%"
    assert page._simple_return_text(-0.10) == "-9.52%"
    assert page._simple_return_text(None) == "unavailable"


def test_error_insight_is_hedged_and_makes_no_superiority_claim() -> None:
    series = ErrorSeries(horizons=(1, 5, 20), baseline="naive", lines={"naive": [0.0, 0.0, 0.0], "toto": [-0.4, -0.1, 0.3]}, reason=None)
    text = page._error_insight(series, {"toto": "Toto"})
    assert "showed lower observed MAE" in text and "horizon 5 days" in text
    assert "limited sample" in text and "not statistically tested" in text and "beats" not in text
    none = ErrorSeries(horizons=(1,), baseline="naive", lines={"naive": [0.0], "toto": [0.2]}, reason=None)
    assert "beats" not in page._error_insight(none, {})
