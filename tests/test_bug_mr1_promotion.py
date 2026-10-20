"""Issue 971: promotion evidence must not admit the audited 2-pair/1-origin floor."""

import pytest

from etf_cockpit.core.config import ModelPromotionSettings
from etf_cockpit.models.model_promotion import evaluate_model_promotions
from tests.test_work_q_promotion import _forecasts, _prices


def test_c108_n003_rejects_two_pair_one_origin_configuration():
    """The required minimum-floor validation must reject the audited settings."""
    with pytest.raises(ValueError):
        ModelPromotionSettings(minimum_matured_forecasts=2, minimum_forecast_origins=1)


def test_c108_n003_limited_evidence_cannot_promote():
    """Two accurate pairs on one origin are still limited evidence."""
    prices = _prices()
    history = _forecasts(prices, {"timesfm3": ["2024-01-02"]})
    history = history.loc[history.etf_id.isin(["E1", "E2"])]
    settings = ModelPromotionSettings(minimum_matured_forecasts=2, minimum_forecast_origins=1)
    decision = evaluate_model_promotions(history, prices, prices.date.max().date(), settings)["timesfm3"]
    assert decision.matured_forecasts == 2
    assert decision.forecast_origins == 1
    assert decision.calibration_status == "limited"
    assert not decision.counting, decision.reason
