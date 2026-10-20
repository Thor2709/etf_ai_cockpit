"""Issue #FC2B: adapter probability honesty, checkpoint identity, log->simple display, calibration identity/PIT."""
from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import etf_cockpit.application.forecast_service as service_module
from etf_cockpit.application.forecast_service import (
    ForecastService,
    _align_forecast_origins,
    _checkpoint_evidence,
    _demote_unadmitted_probabilities,
    _forecast_to_row,
    _identity_gated_forecast,
    _probability_scope,
)
from etf_cockpit.core.config import ModelRuntimeConfig, load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.features.forecast_lab import _conformal_diagnostics, build_forecast_lab_report
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.calibration import (
    adjusted_log_return_target,
    calibrate_forecast_distribution,
    evaluate_forecast_calibration,
    log_to_simple_return,
)
from etf_cockpit.models.forecast_scores import (
    forecast_component_maps,
    forecast_return_distributions,
    forecast_score_details,
)
from etf_cockpit.models.local_weights import checkpoint_content_sha
from etf_cockpit.models.model_promotion import matured_probability_frame
from etf_cockpit.models.timesfm_adapter import TimesFMAdapter
from etf_cockpit.models.toto_adapter import TotoAdapter

HORIZON_60 = adjusted_log_return_target(60).target_id
HORIZON_5 = adjusted_log_return_target(5).target_id


# 1. Adapter probability fields are heuristic until admitted -------------------------------------
def _series(count: int = 320, end: str = "2026-03-06") -> pd.Series:
    rng = np.random.default_rng(3)
    index = pd.bdate_range(end=end, periods=count)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, count))), index=index)


def test_adapter_probabilities_are_heuristic_fields_not_probabilities() -> None:
    mock = ModelRuntimeConfig(enabled=True, mode="mock")
    series = _series()
    rows = TimesFMAdapter(mock).forecast_series(series, [5, 20], etf_id="AAA", forecast_date=series.index[-1].date(), run_id="r")
    frame = pd.DataFrame({"date": series.index, "etf_id": "AAA", "adjusted_close": series.to_numpy()})
    rows += TotoAdapter(mock).forecast_etf("AAA", series.index[-1].date(), [5, 20], prices=frame, run_id="r")
    ok = [row for row in rows if row.status == "ok"]
    assert len(ok) == 4 and {row.model_name for row in ok} == {"timesfm", "toto"}
    for row in rows:
        assert row.prob_positive_return is None
    for row in ok:
        assert row.prob_positive_return is None and row.prob_beat_benchmark is None
        assert row.heuristic_probability_positive is not None and 0.0 <= row.heuristic_probability_positive <= 1.0


def _optional_row(**overrides: object) -> ForecastResult:
    values = dict(
        run_id="r", model_name="toto", model_version="v", etf_id="AAA", forecast_date=date(2026, 3, 2), horizon_days=60,
        expected_return=0.02, expected_excess_return=None, forecast_vol=0.1, heuristic_probability_positive=0.62,
        target_id=HORIZON_60,
    )
    values.update(overrides)
    return ForecastResult(**values)


def test_heuristic_adapter_value_is_promoted_only_for_an_admitted_scope() -> None:
    row = _optional_row()
    for status in (None, {}, {_probability_scope(row): "unavailable"}, {("toto", "v", HORIZON_5, 5): "calibrated"}):
        kept = _demote_unadmitted_probabilities(row, status)
        assert kept.prob_positive_return is None and kept.heuristic_probability_positive == 0.62
        assert kept.probability_calibration_status == "unavailable"
    admitted = _demote_unadmitted_probabilities(row, {_probability_scope(row): "calibrated"})
    assert admitted.prob_positive_return == 0.62 and admitted.heuristic_probability_positive is None
    assert admitted.probability_calibration_status == "calibrated"
    # Another horizon of the same model is a different scope and stays heuristic.
    other = _demote_unadmitted_probabilities(_optional_row(horizon_days=5, target_id=HORIZON_5), {_probability_scope(row): "calibrated"})
    assert other.prob_positive_return is None


# 2. Checkpoint identity derived from the weights --------------------------------------------------
def _checkpoint(tmp_path, payload: bytes = b"weights-v1") -> str:
    directory = tmp_path / "ckpt"
    directory.mkdir(exist_ok=True)
    (directory / "config.json").write_text('{"patch_size": 32}', encoding="utf-8")
    (directory / "model.safetensors").write_bytes(payload)
    return str(directory)


def test_checkpoint_sha_is_the_hash_of_the_weight_files(tmp_path) -> None:
    path = _checkpoint(tmp_path)
    first = checkpoint_content_sha(path)
    assert first is not None and len(first) == 64 and first == checkpoint_content_sha(path)
    (tmp_path / "ckpt" / "model.safetensors").write_bytes(b"weights-v2")
    assert checkpoint_content_sha(path) != first  # changed weights are a different checkpoint
    assert checkpoint_content_sha(str(tmp_path / "empty")) is None and checkpoint_content_sha(None) is None
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "config.json").write_text("{}", encoding="utf-8")
    assert checkpoint_content_sha(str(tmp_path / "bare")) is None  # a config without weights has no identity


def test_model_sha_comes_from_weights_and_absence_blocks_promotion(tmp_path) -> None:
    path = _checkpoint(tmp_path)
    digest = checkpoint_content_sha(path)
    settings = {"toto": {"model_path": path}, "timesfm": {"model_path": str(tmp_path / "missing")}}
    assert _checkpoint_evidence("toto", settings)["checkpoint_sha"] == digest
    assert _forecast_to_row(_optional_row(model_allowed_in_score=True), model_settings=settings)["checkpoint_sha"] == digest
    assert _checkpoint_evidence("timesfm", settings)["checkpoint_sha"] == "unknown"
    declared_without_weights = {"timesfm": {"model_path": str(tmp_path / "missing"), "revision": "a" * 40}}
    assert _checkpoint_evidence("timesfm", declared_without_weights)["checkpoint_sha"] == "unknown"
    ok = _optional_row(model_allowed_in_score=True)
    assert _identity_gated_forecast(ok, settings).status == "ok"
    blocked = _identity_gated_forecast(_optional_row(model_name="timesfm", model_allowed_in_score=True), settings)
    assert blocked.status == "unavailable" and "checkpoint identity" in blocked.reason_unavailable
    assert not blocked.model_allowed_in_score
    published = _forecast_to_row(_optional_row(model_name="timesfm", model_allowed_in_score=True), model_settings=settings)
    assert published["status"] == "unavailable" and published["checkpoint_sha"] == "unknown"


# 3. Display: forecast log returns go through the canonical conversion --------------------------
def test_portfolio_and_fan_chart_show_simple_returns(monkeypatch) -> None:
    import etf_cockpit.app.pages.instrument_detail as detail
    from etf_cockpit.app.pages.portfolio import _short

    assert _short({"status": "available", "value": 0.10}, percent=True, log_return=True) == "10.5%"
    assert _short(0.10, percent=True) == "10.0%"  # plain percent cells are untouched
    assert _short(float("nan"), percent=True, log_return=True).startswith("unavailable")

    drawn: list[dict[str, object]] = []

    def fake_line_chart(x, series, *, bands, **kwargs):
        drawn.append({"x": list(x), "q50": list(series[0].values), "low": list(bands[0].lower), "high": list(bands[0].upper)})
        return "chart"

    monkeypatch.setattr(detail.ck, "line_chart", fake_line_chart)
    stored = {"horizon_days": 20, "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1}
    assert detail._forecast_chart({"rows": [stored]}) == "chart"  # stored log-return quantile keys now draw
    assert drawn[0]["x"] == [20] and drawn[0]["q50"] == [0.0]
    assert drawn[0]["low"] == [pytest.approx(math.expm1(-0.1) * 100)] and drawn[0]["high"] == [pytest.approx(math.expm1(0.1) * 100)]
    for broken in ({**stored, "q10_return": 0.2}, {**stored, "q10_return": None}, {**stored, "q90_return": float("nan")}):
        assert detail._forecast_chart({"rows": [broken]}) != "chart"
    assert len(drawn) == 1
    assert log_to_simple_return(0.10) == pytest.approx(math.expm1(0.10))


def test_friction_forecast_fields_shown_by_simple_scores_are_simple_returns(monkeypatch) -> None:
    from etf_cockpit.signals import friction_edge
    from etf_cockpit.signals.friction_edge import estimate_friction_adjusted_return

    converted: list[object] = []

    def canonical(value: object) -> float | None:
        converted.append(value)
        return log_to_simple_return(value)

    monkeypatch.setattr(friction_edge, "log_to_simple_return", canonical)
    result = estimate_friction_adjusted_return(
        {"q10_return": -0.1, "q50_return": 0.10, "q90_return": 0.2, "horizon_days": 60},
        order_value_eur=1000.0,
        cost_estimate={"total_cost_bps": 10.0, "total_cost_eur": 1.0, "order_value_eur": 1000.0},
    )
    assert result.q50_return == pytest.approx(math.expm1(0.10)) and result.net_expected_return == pytest.approx(math.expm1(0.10) - 0.001)
    assert converted == [-0.1, 0.10, 0.2]


# 4. Calibration evidence: matured as of the evaluation date, same target and horizon -----------
def _matured_history(target_id: str = HORIZON_5) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2025-01-01", periods=220)
    prices = pd.DataFrame({"etf_id": "AAA", "date": index, "adjusted_close": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(index))))})
    series = prices.set_index("date")["adjusted_close"]
    rows = []
    for origin in index[:60]:
        actual = float(np.log(series.iloc[series.index.get_loc(origin) + 5] / series.loc[origin]))
        rows.append({
            "model_name": "timesfm", "etf_id": "AAA", "forecast_date": origin, "horizon_days": 5, "status": "ok",
            "expected_return": 0.0, "heuristic_probability_positive": 0.95 if actual > 0 else 0.05, "model_version": "v",
            "run_id": "r", "created_at": origin + pd.Timedelta(hours=9), "target_id": target_id,
        })
    return pd.DataFrame(rows), prices


def test_probability_evidence_matures_only_with_prices_known_at_as_of_and_same_scope() -> None:
    history, prices = _matured_history()
    scope = dict(model_version="v", target_id=HORIZON_5, horizon_days=5)
    full = matured_probability_frame(history, prices, "timesfm", date(2025, 12, 31), **scope)
    assert len(full) == 60 and set(full["horizon_days"]) == {5}
    index = pd.DatetimeIndex(prices["date"])
    as_of = pd.Timestamp("2025-02-14")
    early = matured_probability_frame(history, prices, "timesfm", as_of.date(), **scope)
    last_matured = index[index.get_loc(as_of) - 5]  # the target session five sessions later must exist at as_of
    assert early["forecast_date"].max() == last_matured and len(early) == index.get_loc(last_matured) + 1
    assert matured_probability_frame(history, prices, "timesfm", date(2025, 12, 31), model_version="v", target_id=HORIZON_60, horizon_days=60).empty
    assert matured_probability_frame(history, prices, "timesfm", date(2025, 12, 31), model_version="other", target_id=HORIZON_5, horizon_days=5).empty
    assert matured_probability_frame(_matured_history(HORIZON_60)[0], prices, "timesfm", date(2025, 12, 31), **scope).empty


# 5. Baseline excess return over the date intersection ---------------------------------------------
def test_baseline_excess_survives_a_cross_exchange_holiday() -> None:
    index = pd.bdate_range(end="2026-03-06", periods=260)
    rng = np.random.default_rng(5)
    asset = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(index)))), index=index)
    benchmark_prices = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.008, len(index)))), index=index)
    benchmark_returns = np.log(benchmark_prices).diff().dropna()
    holiday = benchmark_returns.index[-40]
    benchmark_returns = benchmark_returns.drop(holiday)  # asset trades on a day the benchmark's exchange is closed
    row = baseline_forecast("AAA", asset, [20], date(2026, 3, 6), "r", benchmark_returns=benchmark_returns)[0]
    assert row.expected_excess_return is not None and math.isfinite(row.expected_excess_return)
    assert row.heuristic_probability_beat_benchmark is not None and row.reason_unavailable is None
    asset_returns = np.log(asset).diff().dropna().tail(180)
    common = asset_returns.index.intersection(benchmark_returns.index)
    expected = (asset_returns.loc[common].mean() - benchmark_returns.loc[common].mean()) * 0.35 * 20
    assert row.expected_excess_return == pytest.approx(expected)
    # Full overlap keeps the previous value: asset window mean minus benchmark window mean.
    full = baseline_forecast("AAA", asset, [20], date(2026, 3, 6), "r", benchmark_returns=np.log(benchmark_prices).diff().dropna())[0]
    assert full.expected_excess_return == pytest.approx(
        (asset_returns.mean() - np.log(benchmark_prices).diff().dropna().loc[asset_returns.index].mean()) * 0.35 * 20
    )


def test_baseline_excess_is_none_with_a_reason_when_overlap_is_insufficient() -> None:
    index = pd.bdate_range(end="2026-03-06", periods=260)
    asset = pd.Series(100 * np.exp(np.arange(260) * 0.0005), index=index)
    sparse_benchmark = pd.Series(0.0002, index=np.log(asset).diff().dropna().index[::2])  # half the window
    row = baseline_forecast("AAA", asset, [20], date(2026, 3, 6), "r", benchmark_returns=sparse_benchmark)[0]
    assert row.status == "ok" and row.expected_excess_return is None and row.heuristic_probability_beat_benchmark is None
    assert row.reason_unavailable == "benchmark_overlap_insufficient_for_excess_return"


# 6. Optional-model origins equal the baseline origin on a weekend run -----------------------------
def _identity() -> dict[str, object]:
    return {"status": "available", "instrument_id": "AAA", "identity_decision_id": "fixture", "identity_decision_time": "2024-01-01T00:00:00+00:00",
            "identity_effective_at": "2024-01-01", "identity_history": [{"source_id": "fixture"}],
            "identity_objects": [{"object_type": "listing", "object_id": "fixture-AAA-XNYS", "fields": {"mic": "XNYS", "calendar_id": "XNYS", "timezone": "America/New_York"}}]}


@pytest.fixture
def mock_service(monkeypatch):
    config = load_config()
    config.models.promotion.enabled = False
    config.models.models["timesfm"] = {"enabled": True, "mode": "mock"}
    config.models.models["toto"] = {"enabled": True, "mode": "mock"}
    context = SimpleNamespace(resolution=None, benchmark_data_id=None, identity={})
    service = ForecastService(config, reference_context=context)
    monkeypatch.setattr(service_module, "ensure_run_manifest", lambda *a, **k: None)
    monkeypatch.setattr(service, "_evidence_gated_forecasts", lambda rows, *a: rows)
    monkeypatch.setattr(service, "_probability_statuses", lambda *a: {})
    monkeypatch.setattr(service, "_write_forecasts", lambda *a, **k: None)
    return service


def test_optional_forecast_dates_equal_the_baseline_origin_on_a_weekend_run(mock_service) -> None:
    series = _series(260, "2026-03-06")  # Friday
    frame = pd.DataFrame({"date": series.index.strftime("%Y-%m-%d"), "etf_id": "AAA", "adjusted_close": series.to_numpy()})
    rows = mock_service.run_forecasts(date(2026, 3, 8), ["AAA"], frame, horizons=[5], live_optional_models=True)  # Sunday
    by_model = {row.model_name: row.forecast_date for row in rows}
    assert by_model["baseline"] == date(2026, 3, 6)
    assert {"timesfm", "toto"} <= set(by_model)
    assert by_model["timesfm"] == by_model["toto"] == by_model["baseline"]
    # A weekday run on the last session is unchanged.
    weekday = mock_service.run_forecasts(date(2026, 3, 6), ["AAA"], frame, horizons=[5], live_optional_models=True)
    assert {row.forecast_date for row in weekday} == {date(2026, 3, 6)}


def test_origin_alignment_is_limited_to_optional_rows_at_the_requested_date() -> None:
    sunday, friday = date(2026, 3, 8), date(2026, 3, 6)
    rows = [_optional_row(forecast_date=sunday), _optional_row(forecast_date=date(2026, 3, 2)),
            _optional_row(model_name="baseline", forecast_date=sunday), _optional_row(etf_id="ZZZ", forecast_date=sunday)]
    aligned = _align_forecast_origins(rows, {"AAA": friday}, sunday)
    assert [row.forecast_date for row in aligned] == [friday, date(2026, 3, 2), sunday, sunday]


# 7. V8 items ---------------------------------------------------------------------------------------
def _scoring_rows(**overrides: object) -> dict[str, object]:
    values = dict(etf_id="X", model_name="a", model_version="mv1", horizon_days=60, forecast_date="2026-01-02", expected_return=0.01,
                  status="ok", model_allowed_in_score=True, q10_return=-0.1, q50_return=0.0, q90_return=0.1,
                  target_id="custom-target", target_horizon_days=60)
    values.update(overrides)
    return values


def test_c2_s09_n001_per_model_distribution_records_model_version() -> None:
    frame = pd.DataFrame([_scoring_rows()])
    members = forecast_return_distributions(frame, decision_time="2026-02-01")["X"]["per_model_distributions"]
    assert [member["model_version"] for member in members] == ["mv1"]
    unversioned = forecast_return_distributions(pd.DataFrame([_scoring_rows(model_version=None)]), decision_time="2026-02-01")["X"]
    assert unversioned["per_model_distributions"][0]["model_version"] is None


def _calibration_inputs(rows: int = 12):
    dates = pd.bdate_range("2026-01-01", periods=rows)
    prices = pd.DataFrame({"etf_id": "AAA", "date": dates, "adjusted_close": 100.0 * 1.01 ** np.arange(rows)})
    forecasts = pd.DataFrame({
        "etf_id": "AAA", "model_name": "baseline", "model_id": "model-A", "model_version": "v1", "target_id": "target-1",
        "prediction_id": [f"p{index}" for index in range(8)], "fold_id": "wf-01", "out_of_fold": True,
        "forecast_date": dates[:8].to_numpy(), "horizon_days": 1, "expected_return": 0.01, "q10_return": -0.1, "q90_return": 0.1,
        "created_at": dates[:8] + pd.Timedelta(hours=9), "status": "ok", "model_allowed_in_score": True,
    })
    distribution = {
        "status": "available", "model_name": "baseline", "model_id": "model-A", "model_version": "v1", "target_id": "target-1", "horizon_days": 1,
        "q05_return": -0.2, "q10_return": -0.1, "q25_return": -0.05, "q50_return": 0.0, "q75_return": 0.05, "q90_return": 0.1, "q95_return": 0.2,
    }
    return prices, forecasts, distribution, dates


def test_c2_s09_n002_calibration_ignores_rows_created_after_the_decision_time() -> None:
    prices, forecasts, distribution, dates = _calibration_inputs()
    settings = {"minimum_matured_samples": 2, "coverage_tolerance": 0.05}

    def calibration(frame: pd.DataFrame) -> dict[str, object]:
        return calibrate_forecast_distribution(frame, prices, distribution, instrument_id="AAA", decision_time=dates[6], settings=settings)

    missing_stamp = calibration(forecasts.drop(columns="created_at"))["conformal_calibration"]
    assert missing_stamp["sample_count"] == 0 and "knowledge timestamp" in missing_stamp["reason"]
    assert calibration(forecasts)["conformal_calibration"]["sample_count"] == 5  # origins 0-4 mature before the decision day
    created = forecasts.assign(created_at=forecasts["forecast_date"] + pd.Timedelta(hours=18))
    assert calibration(created)["conformal_calibration"]["sample_count"] == 5
    backfilled = created.copy()
    backfilled.loc[[3, 4], "created_at"] = pd.Timestamp(dates[7], tz="UTC")  # written after the decision, origin and outcome earlier
    assert calibration(backfilled)["conformal_calibration"]["sample_count"] == 3
    unreadable = created.copy()
    unreadable.loc[[0], "created_at"] = "not-a-time"
    assert calibration(unreadable)["conformal_calibration"]["sample_count"] == 4  # an unreadable stamp fails closed


def _family_rows(older: str, newer: str, *, family_first: bool = True) -> pd.DataFrame:
    return pd.DataFrame([
        dict(etf_id="AAA", model_name="timesfm", horizon_days=60, expected_return=0.05, status="ok", model_allowed_in_score=True, forecast_date=older if family_first else newer, run_id="r2"),
        dict(etf_id="AAA", model_name="timesfm3", horizon_days=60, expected_return=-0.05, status="ok", model_allowed_in_score=True, forecast_date=newer if family_first else older, run_id="r3"),
    ])


def test_c2_s10_n002_and_c3_s10_n002_timesfm_family_follows_the_newest_row_and_details_agree() -> None:
    # TimesFM 3 is newer: it supplies the family score and the details show its row.
    newer3 = _family_rows("2026-03-02", "2026-03-09")
    score3 = forecast_component_maps(newer3)["timesfm"]["AAA"]
    details = forecast_score_details(newer3).query("model_name == 'timesfm'").iloc[0]
    assert score3 < 0 and details["expected_return"] == pytest.approx(-0.05) and details["score"] == pytest.approx(score3)
    # TimesFM 2.5 is the fresher run: an older TimesFM 3 row must not overwrite it.
    fresher2 = _family_rows("2026-03-02", "2026-03-09", family_first=False)
    score2 = forecast_component_maps(fresher2)["timesfm"]["AAA"]
    details = forecast_score_details(fresher2).query("model_name == 'timesfm'").iloc[0]
    assert score2 > 0 and details["expected_return"] == pytest.approx(0.05) and details["score"] == pytest.approx(score2)
    # Same forecast time: the newer version wins (previous behaviour).
    assert forecast_component_maps(_family_rows("2026-03-09", "2026-03-09"))["timesfm"]["AAA"] < 0


def test_c3_s09_n003_conformal_residuals_are_grouped_by_model_version() -> None:
    days = pd.bdate_range("2026-01-01", periods=10)
    rows = [
        {"etf_id": "AAA", "horizon_days": 5, "model_version": "v1", "forecast_date": day, "target_date": day + pd.Timedelta(days=1),
         "absolute_error": 0.01, "actual_return": 0.01, "expected_return": 0.0}
        for day in days[:9]
    ]
    late = {"etf_id": "AAA", "horizon_days": 5, "model_version": "v2", "forecast_date": days[9] + pd.Timedelta(days=4), "target_date": days[9] + pd.Timedelta(days=5),
            "absolute_error": 0.01, "actual_return": 0.01, "expected_return": 0.0}
    mixed = _conformal_diagnostics(pd.DataFrame([*rows, late]), 9)
    assert mixed["status"] == "conformal_pending"  # v2 has no residuals of its own; v1's nine never calibrate it
    same_version = _conformal_diagnostics(pd.DataFrame([*rows, {**late, "model_version": "v1"}]), 9)
    assert same_version["status"] == "conformal_diagnostic" and same_version["coverage"] == 1.0


def test_c3_s15_n001_legacy_view_without_decision_time_is_flagged_not_canonical() -> None:
    legacy = forecast_return_distributions(pd.DataFrame([_scoring_rows()]))["X"]
    assert legacy["status"] == "available"  # the unbound three-quantile view for existing consumers
    assert legacy["point_in_time_status"] == "unavailable" and legacy["canonical_status"] == "unavailable"
    bound = forecast_return_distributions(pd.DataFrame([_scoring_rows()]), decision_time="2026-02-01")["X"]
    assert bound["point_in_time_status"] == "available"


def _calibration_inputs_h5(intervals: int, total: int, covered: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-01", periods=60)
    step = math.log(1.01)
    prices = pd.DataFrame({"etf_id": "AAA", "date": dates, "adjusted_close": 100.0 * 1.01 ** np.arange(60)})
    rows = []
    for index in range(total):
        actual = 5 * step
        row = {
            "model_name": "m", "etf_id": "AAA", "forecast_date": dates[index], "horizon_days": 5, "status": "ok", "model_allowed_in_score": True,
            "expected_return": actual, "target_id": HORIZON_5, "q10_return": None, "q90_return": None,
        }
        if index < intervals:
            low = actual - 0.01 if index < covered else actual + 0.01
            row.update(q10_return=low, q90_return=low + 0.02)
        rows.append(row)
    return pd.DataFrame(rows), prices


def test_c2_s24_n003_coverage_grade_needs_the_same_denominator_as_matured_forecasts() -> None:
    forecasts, prices = _calibration_inputs_h5(intervals=12, total=12, covered=10)
    complete = evaluate_forecast_calibration(forecasts, prices).iloc[0]
    assert complete["matured_forecasts"] == 12 and complete["q10_q90_coverage"] == pytest.approx(0.8333, abs=1e-4)
    assert complete["calibration_status"] == "good"
    # Only 10 of 12 matured rows carry an interval: that coverage cannot support a "good" grade of all 12.
    partial_forecasts, prices = _calibration_inputs_h5(intervals=10, total=12, covered=8)
    partial = evaluate_forecast_calibration(partial_forecasts, prices).iloc[0]
    assert partial["matured_forecasts"] == 12 and partial["q10_q90_coverage"] == pytest.approx(0.8)
    assert partial["calibration_status"] == "mixed"


def test_c2_s09_n003_fractional_horizons_are_not_truncated_into_evidence() -> None:
    forecasts, prices = _calibration_inputs_h5(intervals=12, total=12, covered=12)
    fractional = forecasts.copy()
    fractional.loc[0:3, "horizon_days"] = 5.7
    fractional.loc[4, "horizon_days"] = float("inf")
    result = evaluate_forecast_calibration(fractional, prices).iloc[0]
    assert result["matured_forecasts"] == 7
    assert evaluate_forecast_calibration(forecasts.assign(horizon_days=5.5), prices).empty


def test_c2_s11_n002_implicit_as_of_does_not_grade_forecasts_with_future_prices() -> None:
    dates = pd.bdate_range("2026-01-05", periods=4)
    forecasts = pd.DataFrame([{
        "run_id": "r", "model_name": "baseline", "model_version": "v1", "etf_id": "AAA",
        "forecast_date": dates[0], "horizon_days": 1, "expected_return": 0.01,
        "q10_return": -0.01, "q90_return": 0.03, "status": "ok",
    }])
    prices = pd.DataFrame({"etf_id": "AAA", "date": dates, "adjusted_close": [100.0, 101.0, 102.0, 103.0]})

    report = build_forecast_lab_report(forecasts, prices)

    assert report["as_of_date"] == dates[0].date().isoformat()
    assert report["outcomes_through"] == dates[0].date().isoformat()
    outcome = report["forecast_outcomes"].iloc[0]
    assert outcome["outcome_status"] == "unavailable" and outcome["actual_return"] is None
