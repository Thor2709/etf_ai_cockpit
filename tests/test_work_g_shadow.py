from datetime import date
from dataclasses import asdict
import pandas as pd
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.application.forecast_service import _shadow_forecast, _forecast_to_row
from etf_cockpit.application.forecast_service import build_forecast_lab_workspace
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity, forecast_component_maps, forecast_return_distributions


def test_shadow_opt_in_runs_inference_without_optional_score_authority():
    config = load_config().model_copy(deep=True)
    assert not configured_forecast_request_identity(config)['live_optional_models']
    config.models.shadow_optional_models = True
    assert configured_forecast_request_identity(config)['live_optional_models']
    rows = [_shadow_forecast(ForecastResult('run', model, 'v', 'ETF', date(2026, 1, 1), 60, 0.9, 0.9, q10_return=0.5, q50_return=0.9, q90_return=1.5)) for model in ('timesfm','timesfm3','toto')]
    frame = pd.DataFrame([asdict(row) for row in rows])
    assert all(not row.model_allowed_in_score for row in rows)
    assert all(not values for values in forecast_component_maps(frame).values())
    assert forecast_return_distributions(frame, decision_time='2026-01-01')['ETF']['status'] == 'unavailable'
    prices = pd.DataFrame({'date': pd.bdate_range('2026-01-01', periods=3), 'etf_id': ['ETF'] * 3, 'adjusted_close': [100.,101.,102.]})
    report = build_forecast_lab_workspace(config, frame, prices, timing_records=[])
    assert report['model_catalogue'].set_index('model_id').loc['timesfm3','state'] == 'available'
    historical = build_forecast_lab_workspace(config, frame, prices, as_of_date='2025-12-31', timing_records=[])
    assert historical['model_catalogue'].set_index('model_id').loc['timesfm3','state'] == 'unavailable'


def test_pretraining_windows_are_flagged_and_never_promotion_evidence():
    for model, day, contamination in [('timesfm3',date(2023,11,30),'possibly_leaked'),('timesfm3',date(2023,12,1),'after_declared_cutoff'),('timesfm',date(2026,1,1),'possibly_leaked'),('toto',date(2026,1,1),'possibly_leaked')]:
        row = _forecast_to_row(_shadow_forecast(ForecastResult('run',model,'v','ETF',day,60,0.1,0.1)))
        assert row['contamination_status'] == contamination
        assert row['promotion_evidence_allowed'] is False
        assert row['promotion_state'] == 'shadow_only'
        assert row['execution_allowed'] is False


def test_promoted_timesfm3_takes_timesfm_family_slot_and_shadow_rows_do_not() -> None:
    import pandas as pd
    from etf_cockpit.models.forecast_scores import forecast_component_maps

    rows = pd.DataFrame(
        [
            {"model_name": "timesfm", "etf_id": "A", "horizon_days": 60, "expected_return": -0.02, "status": "ok", "model_allowed_in_score": True, "forecast_date": "2026-10-09"},
            {"model_name": "timesfm3", "etf_id": "A", "horizon_days": 60, "expected_return": 0.03, "status": "ok", "model_allowed_in_score": True, "forecast_date": "2026-10-09"},
            {"model_name": "timesfm3", "etf_id": "B", "horizon_days": 60, "expected_return": 0.05, "status": "ok", "model_allowed_in_score": False, "forecast_date": "2026-10-09"},
        ]
    )
    maps = forecast_component_maps(rows)
    only_v25 = forecast_component_maps(rows.iloc[[0]])

    assert maps["timesfm"]["A"] > only_v25["timesfm"]["A"]
    assert "B" not in maps["timesfm"]
    assert "timesfm3" not in maps
