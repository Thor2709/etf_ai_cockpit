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


def test_ranked_weights_publish_top_concentration_and_cluster_risk_contribution() -> None:
    index = pd.date_range("2026-01-01", periods=150, freq="D")
    base = np.linspace(100, 120, len(index)) + np.sin(np.arange(len(index)))
    prices = pd.DataFrame(
        {"A": base, "B": base * 1.01, "C": np.linspace(100, 80, len(index))},
        index=index,
    )

    report = build_correlation_clusters(
        prices,
        {"A": {"sector": "Technology", "theme": "AI"}, "B": {"sector": "Technology", "theme": "AI"}, "C": {"sector": "Defensive", "theme": "Bonds"}},
        ranked_instruments=["A", "B", "C"],
        weights={"A": 0.5, "B": 0.3, "C": 0.2},
    )

    rows = {row.instrument_id: row for row in report.rows}
    assert report.ranked_instrument_count == 3
    assert report.top_ranked_concentration == 0.8
    assert rows["A"].cluster_weight == 0.8
    assert rows["A"].cluster_risk_contribution == 0.8
    assert rows["A"].ranking_coverage == 1.0
    contributions = {
        row.cluster_id: row.cluster_risk_contribution
        for row in rows.values()
        if row.cluster_risk_contribution is not None
    }
    assert np.isclose(sum(contributions.values()), 1.0)


def test_sparse_instrument_uses_pair_coverage_not_global_sample_size() -> None:
    index = pd.date_range("2026-01-01", periods=150, freq="D")
    base = np.linspace(100, 120, len(index)) + np.sin(np.arange(len(index)))
    prices = pd.DataFrame(
        {
            "A": base,
            "B": base * 1.01,
            "SPARSE": pd.Series([100.0, 101.0, 102.0], index=index[-3:]),
        },
        index=index,
    )

    report = build_correlation_clusters(prices, {"A": "technology", "B": "technology", "SPARSE": "technology"})

    sparse = next(row for row in report.rows if row.instrument_id == "SPARSE")
    assert sparse.sample_size < report.sample_size
    assert sparse.pair_sample_size == 0
    assert sparse.average_peer_correlation is None
    assert "coverage" in sparse.crowding_warning


def test_ranked_cohort_concentration_and_singleton_risk_use_selected_weights() -> None:
    index = pd.date_range("2026-01-01", periods=150, freq="D")
    base = np.linspace(100, 120, len(index)) + np.sin(np.arange(len(index)))
    prices = pd.DataFrame(
        {
            "A": base,
            "B": np.linspace(100, 80, len(index)),
            "C": np.linspace(100, 110, len(index)),
        },
        index=index,
    )
    report = build_correlation_clusters(
        prices,
        ranked_instruments=["A", "B"],
        weights={"A": 0.9, "B": 0.1},
    )

    rows = {row.instrument_id: row for row in report.rows}
    assert report.ranked_instrument_count == 2
    assert report.top_ranked_concentration == 0.9
    assert rows["A"].cluster_weight == 0.9
    assert rows["A"].cluster_risk_contribution is not None
    assert rows["A"].cluster_risk_contribution > 0.0
    assert rows["B"].cluster_risk_contribution is not None
    assert rows["B"].cluster_risk_contribution > 0.0


def test_pair_sample_size_is_minimum_clean_pair_coverage_for_mixed_pairs() -> None:
    index = pd.date_range("2026-01-01", periods=150, freq="D")
    base = np.linspace(100, 120, len(index)) + np.sin(np.arange(len(index)))
    prices = pd.DataFrame(
        {
            "A": base,
            "B": base * 1.01,
            "C": pd.Series(base * 0.99, index=index).where(pd.Series(np.arange(len(index)) >= 60, index=index)),
        },
        index=index,
    )
    report = build_correlation_clusters(prices)

    row_a = next(row for row in report.rows if row.instrument_id == "A")
    assert row_a.pair_sample_size == 89
    assert row_a.ranking_coverage == round(89 / row_a.sample_size, 6)
