from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application.screening_data import build_screen_rows, query_for_snapshot


def _snapshot():
    instrument = SimpleNamespace(
        id="ETF1",
        name="Example ETF",
        instrument_type="etf",
        asset_class="equity",
        region="Europe",
        sector="Technology",
        theme="Semiconductors",
        analysis_tier="primary",
    )
    signal = SimpleNamespace(
        etf_id="ETF1",
        confidence=0.8,
        blocked_by=["stale_data"],
        warnings=["limited_history"],
        supporting_metrics={
            "canonical_attractiveness_10": 7.5,
            "canonical_expected_return_10": 6.0,
            "canonical_evidence_confidence_10": 8.0,
            "canonical_coverage": 0.75,
            "canonical_risk_implementation_10": 4.0,
            "momentum_60d": 0.12,
            "drift_percent": 0.03,
            "formula_version": "canonical-v1",
        },
    )
    return SimpleNamespace(
        config=SimpleNamespace(universe=SimpleNamespace(etfs=[instrument])),
        signals=[signal],
        model_status={"toto": False, "timesfm": False},
        universe_revision="revision-3",
        data_report=SimpleNamespace(as_of_date=date(2026, 7, 18)),
    )


def test_screen_rows_join_local_evidence_without_inventing_unavailable_fields() -> None:
    fundamentals = pd.DataFrame(
        [{"instrument_id": "ETF1", "valuation": 5.0, "profitability": 9.0, "growth": 8.0}]
    )
    frame = build_screen_rows(_snapshot(), fundamentals)
    row = frame.iloc[0]
    assert row["score"] == 7.5
    assert row["region"] == "Europe"
    assert row["quality"] == 8.5
    assert row["news_conflict"] == "unavailable"
    assert row["backtest_trust"] == "unavailable"
    assert row["model_availability"] == "baseline_only"
    assert row["execution_allowed"] == False  # noqa: E712
    assert row["score_percentile"] == 100.0
    assert row["freshness"] == "as_of_snapshot"
    assert row["freshness_days"] == 0


def test_snapshot_query_carries_reproducible_lineage() -> None:
    frame = build_screen_rows(_snapshot(), pd.DataFrame())
    first = query_for_snapshot(_snapshot(), frame)
    second = query_for_snapshot(_snapshot(), frame.copy())
    assert first.checksum == second.checksum
    assert first.as_of == "2026-07-18"
    assert first.universe_revision == "revision-3"
    assert first.formula_version == "canonical-v1"
    assert dict(first.dataset_checksums)["local_screen_rows"]
