from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.features.feature_pipeline import compute_features


def test_features_do_not_change_when_future_rows_removed() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    cutoff = pd.Timestamp("2026-01-30").date()
    full_features = compute_features(prices, benchmark_etf_id="WORLD_CORE")
    truncated_prices = prices[pd.to_datetime(prices["date"]).dt.date <= cutoff]
    truncated_features = compute_features(truncated_prices, benchmark_etf_id="WORLD_CORE")
    full_cut = full_features[pd.to_datetime(full_features["date"]).dt.date <= cutoff].reset_index(drop=True)
    trunc_cut = truncated_features.reset_index(drop=True)
    pd.testing.assert_frame_equal(full_cut[trunc_cut.columns], trunc_cut, check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-12)
