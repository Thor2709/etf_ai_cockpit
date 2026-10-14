from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.features.crowding import build_correlation_clusters
from etf_cockpit.features.feature_pipeline import compute_features
from etf_cockpit.features.liquidity import liquidity_score


def _turnover_inputs(n: int = 80) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(7)
    price = pd.Series(100.0 + rng.normal(0, 1, n).cumsum() * 0.1)
    volume = pd.Series(rng.uniform(900, 1100, n))
    return price, volume


def test_split_with_unchanged_turnover_keeps_liquidity_score() -> None:
    # C04-C2-N001
    price, volume = _turnover_inputs()
    base = liquidity_score(volume, price=price)
    split_at = 50
    split_price = price.copy()
    split_volume = volume.copy()
    split_price.iloc[:split_at] = price.iloc[:split_at] / 4.0  # 4:1 split restated
    split_volume.iloc[:split_at] = volume.iloc[:split_at] * 4.0
    # Raw (unadjusted) history keeps its original price/volume, the split-consistent series is identical turnover.
    after = liquidity_score(split_volume, price=split_price)
    pd.testing.assert_series_equal(base, after, check_exact=False, rtol=1e-12)
    assert base.notna().sum() > 0


def test_share_volume_alone_is_not_a_liquidity_score() -> None:
    _, volume = _turnover_inputs()
    assert liquidity_score(volume).isna().all()


def test_feature_pipeline_uses_close_turnover_and_fails_closed_without_close() -> None:
    price, volume = _turnover_inputs()
    dates = pd.bdate_range("2025-01-01", periods=len(price))
    frame = pd.DataFrame({"date": dates, "etf_id": "A", "close": price.values, "adjusted_close": price.values, "volume": volume.values})
    assert compute_features(frame)["liquidity_score"].notna().any()
    assert compute_features(frame.drop(columns=["close"]))["liquidity_score"].isna().all()


@pytest.mark.parametrize("bad", [-5.0, float("nan"), float("inf"), float("-inf")])
def test_invalid_volume_is_unavailable_not_finite(bad: float) -> None:
    # C04-C2-N004
    price, volume = _turnover_inputs()
    volume = volume.copy()
    volume.iloc[60] = bad
    score = liquidity_score(volume, price=price)
    assert pd.isna(score.iloc[60])
    assert np.isfinite(score.iloc[70])  # rest of the history is unaffected, and the bad row is not in the median


def _prices(columns: list[str], n: int = 130) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    index = pd.bdate_range("2025-01-01", periods=n)
    data = {c: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))) for c in columns}
    return pd.DataFrame(data, index=index)


def test_missing_theme_weights_do_not_create_full_concentration() -> None:
    # C04-C2-N002
    prices = _prices(["A", "B", "C"])
    meta = {"A": {"theme": "ai"}, "B": {"theme": "ai"}, "C": {"theme": "ai"}}
    report = build_correlation_clusters(prices, meta, ranked_instruments=["A", "B", "C"])
    assert report.top_ranked_theme_concentration is None
    assert report.top_ranked_concentration is None
    assert report.ranking_coverage is None
    partial = build_correlation_clusters(prices, meta, ranked_instruments=["A", "B", "C"], weights={"A": 1.0})
    assert partial.ranking_coverage == pytest.approx(1 / 3, abs=1e-6)


def test_crowding_without_as_of_in_historical_mode_is_unavailable() -> None:
    # C04-C2-N003
    prices = _prices(["A", "B"])
    missing = build_correlation_clusters(prices, historical=True)
    assert missing.status == "unavailable"
    assert "as_of" in missing.reason
    anchored = build_correlation_clusters(prices, historical=True, as_of="2025-06-30")
    assert anchored.status != "unavailable"
    assert anchored.as_of is not None and anchored.as_of <= "2025-06-30"
    before_data = build_correlation_clusters(prices, historical=True, as_of="2024-01-01")
    assert before_data.status == "unavailable"
