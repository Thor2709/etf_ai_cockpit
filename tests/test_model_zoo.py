from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.models.model_zoo import model_zoo_catalogue, model_zoo_frame, run_model_zoo


def test_model_zoo_catalogue_has_baselines_challengers_cards_and_safe_optional_states() -> None:
    cards = {card.model_id: card for card in model_zoo_catalogue()}

    assert {"naive_drift", "historical_median", "linear_ridge"}.issubset(cards)
    assert {"elastic_net", "robust_regression", "state_space", "econometric_ar"}.issubset(cards)
    assert cards["timesfm"].state == "unavailable"
    assert cards["toto"].state == "unavailable"
    assert all(card.execution_allowed is False for card in cards.values())
    assert all(card.promotion_state == "shadow_only" for card in cards.values())
    assert all(card.licence and card.data_needs and card.horizons for card in cards.values())


def test_model_zoo_optional_status_is_explicit_and_serialisable() -> None:
    frame = model_zoo_frame(optional_status={"timesfm": True, "toto": False})

    assert frame.set_index("model_id").loc["timesfm", "state"] == "available"
    assert frame.set_index("model_id").loc["toto", "state"] == "unavailable"
    assert not bool(frame.set_index("model_id").loc["timesfm", "execution_allowed"])


def test_model_zoo_runs_multiple_deterministic_return_baselines_without_selection() -> None:
    prices = pd.Series([100.0, 101.0, 100.5, 102.0, 103.0, 104.0], name="adjusted_close")

    first = run_model_zoo(prices, [5, 20], etf_id="AAA")
    second = run_model_zoo(prices, [5, 20], etf_id="AAA")

    pd.testing.assert_frame_equal(first, second)
    assert {"naive_drift", "historical_median", "linear_ridge"}.issubset(set(first["model_id"]))
    assert set(first["selection_state"]) == {"not_selected"}
    assert set(first["validation_scope"]) == {"walk_forward_required"}
    assert first["execution_allowed"].eq(False).all()
    assert first.loc[first["status"] == "ok", "expected_return"].notna().all()
    assert set(first.loc[first["status"] == "unavailable", "model_id"]) >= {"timesfm", "toto"}


def test_model_zoo_rejects_non_adjusted_or_invalid_price_values() -> None:
    with pytest.raises(ValueError, match="positive finite"):
        run_model_zoo(pd.Series([100.0, float("nan")]), [5])

    with pytest.raises(ValueError, match="positive finite"):
        run_model_zoo(pd.Series([100.0, -1.0]), [5])


def test_model_zoo_fundamentals_without_point_in_time_target_is_unavailable() -> None:
    result = run_model_zoo(pd.Series([100.0, 101.0, 102.0]), [5], task="fundamentals")

    assert not result.empty
    assert set(result["status"]) == {"unavailable"}
    assert result["reason"].str.contains("point-in-time").all()


def test_model_zoo_separates_risk_and_quantile_outputs() -> None:
    prices = pd.Series([100.0, 101.0, 100.5, 102.0, 103.0], name="adjusted_close")

    risk = run_model_zoo(prices, [20], task="risk")
    quantiles = run_model_zoo(prices, [20], task="quantile")

    assert risk["expected_return"].isna().all()
    assert risk.loc[risk["status"] == "ok", "forecast_vol"].notna().all()
    assert quantiles.loc[quantiles["status"] == "ok", "q10_return"].notna().all()
    assert quantiles.loc[quantiles["status"] == "ok", "q90_return"].notna().all()
