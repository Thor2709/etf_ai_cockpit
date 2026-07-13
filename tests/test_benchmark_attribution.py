from __future__ import annotations

import pandas as pd

from etf_cockpit.features.benchmark_attribution import build_benchmark_attribution


def test_benchmark_attribution_returns_alpha_and_explicit_missing_sector() -> None:
    result = build_benchmark_attribution(pd.Series([0.01, 0.02, 0.0]), pd.Series([0.005, 0.01, 0.0]), None)
    assert result.alpha_proxy is not None
    assert result.sector_attribution == "N/A"


def test_benchmark_attribution_reports_broad_and_sector_relative_evidence() -> None:
    index = pd.date_range("2026-01-01", periods=6, freq="D")
    instrument = pd.Series([0.01, 0.02, 0.00, 0.01, -0.01, 0.02], index=index)
    broad = pd.Series([0.005, 0.01, 0.0, 0.005, 0.0, 0.01], index=index)
    sector = pd.Series([0.008, 0.015, 0.0, 0.006, -0.002, 0.012], index=index)
    result = build_benchmark_attribution(instrument, broad, sector)

    assert result.status == "available"
    assert result.broad_return == result.benchmark_return
    assert result.sector_attribution == "available"
    assert result.sector_relative_return is not None
    assert result.sector_alpha_proxy is not None
    assert result.sector_sample_size == 6
    assert result.as_of == "2026-01-06"
    assert result.execution_allowed is False


def test_benchmark_attribution_marks_insufficient_broad_or_sector_data_as_unavailable() -> None:
    result = build_benchmark_attribution(pd.Series([0.01]), pd.Series([0.005]), pd.Series([0.01]))

    assert result.status == "unavailable"
    assert result.instrument_return is None
    assert result.sector_attribution == "N/A"
    assert result.sector_relative_return is None
