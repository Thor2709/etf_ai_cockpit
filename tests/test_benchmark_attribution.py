from __future__ import annotations

import pandas as pd

from etf_cockpit.features.benchmark_attribution import build_benchmark_attribution


def test_benchmark_attribution_returns_alpha_and_explicit_missing_sector() -> None:
    result = build_benchmark_attribution(pd.Series([0.01, 0.02, 0.0]), pd.Series([0.005, 0.01, 0.0]), None)
    assert result.alpha_proxy is not None
    assert result.sector_attribution == "N/A"
