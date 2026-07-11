from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.features.crowding import build_correlation_clusters


def test_correlation_clusters_flag_highly_correlated_instruments() -> None:
    index = pd.date_range("2026-01-01", periods=140, freq="D")
    base = np.linspace(100, 120, len(index))
    prices = pd.DataFrame({"A": base, "B": base * 1.01, "C": np.linspace(100, 80, len(index))}, index=index)
    report = build_correlation_clusters(prices, {"A": "technology", "B": "technology", "C": "defensive"})
    assert report.rows
    assert any(row.crowding_warning for row in report.rows)
