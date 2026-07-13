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


def test_correlation_clusters_preserve_membership_metadata_and_evidence() -> None:
    index = pd.date_range("2026-01-01", periods=150, freq="D")
    base = np.linspace(100, 120, len(index)) + np.sin(np.arange(len(index)))
    prices = pd.DataFrame({"A": base, "B": base * 1.01, "C": base * 0.99}, index=index)
    report = build_correlation_clusters(
        prices,
        {"A": {"sector": "Technology", "theme": "AI"}, "B": {"sector": "Technology", "theme": "AI"}, "C": {"sector": "Defensive", "theme": "Bonds"}},
        window=120,
    )

    assert report.status == "available"
    assert report.sample_size >= 100
    assert report.as_of == "2026-05-30"
    rows = {row.instrument_id: row for row in report.rows}
    assert rows["A"].sector == "Technology"
    assert rows["A"].theme == "AI"
    assert rows["A"].cluster_id == rows["B"].cluster_id
    assert "warning" in rows["A"].crowding_warning
    assert rows["A"].execution_allowed is False


def test_correlation_clusters_returns_explicit_unavailable_for_short_or_invalid_data() -> None:
    prices = pd.DataFrame({"A": [100.0, 101.0], "B": [100.0, 99.0]}, index=pd.date_range("2026-01-01", periods=2))
    report = build_correlation_clusters(prices, {"A": "technology", "B": "technology"}, window=120)

    assert report.status == "unavailable"
    assert report.rows == ()
    assert report.reason
    assert report.sample_size == 0
