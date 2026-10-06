"""Golden: ensemble weight renormalisation and the optional-model (TimesFM/Toto) result shapes.

No weights are loaded or downloaded.  Unavailable paths use explicit ``ModelRuntimeConfig`` values (never the
machine's ``models/`` folder); the "available" path uses the adapters' built-in ``mode="mock"`` stub, which is the
existing deterministic fake pattern (see tests/test_model_shapes.py).  Nothing here reads a wall clock: dates and
run ids are passed explicitly.
"""

from __future__ import annotations

from datetime import date
from itertools import product

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.core.config import ModelRuntimeConfig, load_config
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.ensemble import effective_ensemble_weights
from etf_cockpit.models.timesfm_adapter import TimesFMAdapter, timesfm_level_forecast_to_results
from etf_cockpit.models.toto_adapter import TotoAdapter, toto_quantiles_to_log_return_results
from refactor_parity._harness import assert_matches_golden
from refactor_parity._serialise import jsonable

FORECAST_DATE = date(2026, 9, 30)
RUN_ID = "parity-run"
HORIZONS = [1, 5, 20, 60]
NOTES = (
    "Weights: the repository default (configs/model_settings.yaml ensemble.weights, loaded through load_config) plus "
    "three hand-written tables (toto-only, no optional weights, penalties present). Every (toto_available, "
    "timesfm_available) combination is pinned, keys in insertion order, floats rel=1e-9/abs=1e-12. Adapters: disabled, "
    "live-without-checkpoint (unavailable) and mock (the existing stub) for TimesFM and Toto; synthetic series from "
    "np.random.default_rng(7) on a business-day index ending 2026-09-30; forecast_date and run_id passed explicitly "
    "(no wall clock). Real weights are never loaded."
)

_LITERAL_WEIGHTS = {
    "toto_only": {"toto": 1.0},
    "no_optional_weights": {"momentum": 0.5, "trend": 0.3, "baseline_ml": 0.2},
    "with_penalties": {
        "momentum": 0.2, "trend": 0.15, "risk": 0.1, "toto": 0.25, "timesfm": 0.2, "baseline_ml": 0.1,
        "cost_penalty": 0.05, "turnover_penalty": 0.02, "concentration_penalty": 0.01,
    },
}


def _ensemble_table() -> dict[str, object]:
    weight_sets: dict[str, dict[str, float]] = {"configured_default": {str(k): float(v) for k, v in load_config().models.ensemble["weights"].items()}}
    weight_sets.update(_LITERAL_WEIGHTS)
    table: dict[str, object] = {}
    for name, weights in weight_sets.items():
        combinations: dict[str, object] = {}
        for toto, timesfm in product((True, False), repeat=2):
            effective = effective_ensemble_weights(weights, toto_available=toto, timesfm_available=timesfm)
            combinations[f"toto={toto},timesfm={timesfm}"] = {
                "weights": effective,
                "non_penalty_sum": sum(v for k, v in effective.items() if not k.endswith("_penalty")),
            }
        table[name] = {"input": weights, "combinations": combinations}
    return table


def _series() -> pd.Series:
    rng = np.random.default_rng(7)
    index = pd.bdate_range(end=pd.Timestamp(FORECAST_DATE), periods=320)
    return pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(index)))), index=index, name="adjusted_close")


def _price_frame() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    index = pd.bdate_range(end=pd.Timestamp(FORECAST_DATE), periods=320)
    frames = []
    for etf_id in ("AAA", "BBB", "CCC"):
        close = 50.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.009, len(index))))
        frames.append(pd.DataFrame({"date": index, "etf_id": etf_id, "adjusted_close": close}))
    return pd.concat(frames, ignore_index=True)


def _adapter_shapes() -> dict[str, object]:
    series = _series()
    prices = _price_frame()
    runtime = {
        "disabled": ModelRuntimeConfig(enabled=False, mode="disabled"),
        "live_without_checkpoint": ModelRuntimeConfig(enabled=True, mode="live", local_files_only=True, allow_remote_download=False),
        "mock": ModelRuntimeConfig(enabled=True, mode="mock"),
    }
    out: dict[str, object] = {}
    for name, config in runtime.items():
        timesfm = TimesFMAdapter(config)
        toto = TotoAdapter(config)
        out[name] = {
            "timesfm_is_available": timesfm.is_available(),
            "timesfm_results": jsonable(timesfm.forecast_series(series, HORIZONS, etf_id="AAA", forecast_date=FORECAST_DATE, run_id=RUN_ID)),
            "toto_is_available": toto.is_available(),
            "toto_results": jsonable(toto.forecast_etf("AAA", FORECAST_DATE, HORIZONS, prices=prices, run_id=RUN_ID)),
        }
        timesfm.unload_model()
        toto.unload_model()
    return out


def _converters() -> dict[str, object]:
    timesfm = timesfm_level_forecast_to_results(
        mean_predictions=np.array([[101.0, 104.0]]),
        quantile_predictions=np.array([[[99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]] * 2]),
        last_value=100.0,
        horizons=[1, 2, 3],
        etf_id="AAA",
        forecast_date=FORECAST_DATE,
        run_id=RUN_ID,
        model_version="timesfm_2_5_transformers",
    )
    quantiles = np.zeros((9, 1, 1, 3))
    quantiles[0, 0, 0, :] = -0.01
    quantiles[4, 0, 0, :] = 0.02
    quantiles[8, 0, 0, :] = 0.04
    toto = toto_quantiles_to_log_return_results(
        quantiles=quantiles,
        horizons=[1, 3, 4],
        etf_id="AAA",
        forecast_date=FORECAST_DATE,
        run_id=RUN_ID,
        model_version="toto_2_0_4m",
    )
    return {"timesfm_level_to_results": jsonable(timesfm), "toto_quantiles_to_results": jsonable(toto)}


def _baseline() -> dict[str, object]:
    series = _series()
    benchmark = series.pct_change(fill_method=None).dropna() * 0.9
    return {
        "without_benchmark": jsonable(baseline_forecast("AAA", series, HORIZONS, FORECAST_DATE, RUN_ID)),
        "with_benchmark": jsonable(baseline_forecast("AAA", series, HORIZONS, FORECAST_DATE, RUN_ID, benchmark_returns=benchmark)),
        "empty_series": jsonable(baseline_forecast("AAA", series.iloc[0:0], HORIZONS, FORECAST_DATE, RUN_ID)),
    }


@pytest.fixture(scope="module")
def payload() -> dict[str, object]:
    return {
        "ensemble_effective_weights": _ensemble_table(),
        "adapter_shapes": _adapter_shapes(),
        "converters": _converters(),
        "baseline_forecast": _baseline(),
    }


def test_optional_models_match_golden(payload: dict[str, object]) -> None:
    assert_matches_golden("optional_models", payload, notes=NOTES)


def test_unavailable_adapter_results_are_explicit_not_zero_filled(payload: dict[str, object]) -> None:
    shapes = payload["adapter_shapes"]
    assert isinstance(shapes, dict)
    for name in ("disabled", "live_without_checkpoint"):
        entry = shapes[name]
        assert entry["timesfm_is_available"] is False and entry["toto_is_available"] is False
        for key in ("timesfm_results", "toto_results"):
            assert [row["status"] for row in entry[key]] == ["unavailable"] * len(HORIZONS)
            assert all(row["expected_return"] is None for row in entry[key])
    assert all(row["status"] == "ok" for row in shapes["mock"]["timesfm_results"])
