from __future__ import annotations

from datetime import date
import json
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


def _sections_json(values: dict[str, float], as_of: str) -> str:
    return json.dumps(
        {
            field: {
                "value": value,
                "period_end": as_of,
                "source_id": "sec-filing",
                "source_authority": "sec_edgar",
            }
            for field, value in values.items()
        },
        sort_keys=True,
    )


def test_screen_rows_join_local_evidence_without_inventing_unavailable_fields() -> None:
    values = {"valuation": 5.0, "profitability": 9.0, "leverage": 5.0, "growth": 8.0, "shareholder_return": 8.5}
    fundamentals = pd.DataFrame(
        [
            {
                "instrument_id": "ETF1",
                "as_of_date": "2026-07-18",
                "eligibility": "eligible",
                "score_eligible": True,
                "source_id": "sec-filing",
                "source_authority": "sec_edgar",
                "sections_json": _sections_json(values, "2026-07-18"),
                **values,
            }
        ]
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


def test_screen_rows_do_not_rank_stale_or_ineligible_fundamentals() -> None:
    values = {"valuation": 10.0, "profitability": 10.0, "leverage": 10.0, "growth": 10.0, "shareholder_return": 10.0}
    fundamentals = pd.DataFrame(
        [
            {
                "instrument_id": "ETF1",
                "as_of_date": "2025-01-01",
                "eligibility": "eligible",
                "score_eligible": True,
                "source_id": "sec-filing",
                "source_authority": "sec_edgar",
                "warnings": "stale_fundamentals",
                "sections_json": _sections_json(values, "2025-01-01"),
                **values,
            }
        ]
    )

    row = build_screen_rows(_snapshot(), fundamentals).iloc[0]

    assert pd.isna(row["valuation"])
    assert pd.isna(row["quality"])
    assert pd.isna(row["valuation_percentile"])
    assert row["execution_allowed"] == False  # noqa: E712


def test_screen_rows_select_latest_deterministic_fundamental_generation() -> None:
    latest_values = {"valuation": 8.0, "profitability": 7.0, "leverage": 6.0, "growth": 5.0, "shareholder_return": 4.0}
    older_values = {"valuation": 3.0, "profitability": 3.0, "leverage": 3.0, "growth": 3.0, "shareholder_return": 3.0}
    fundamentals = pd.DataFrame(
        [
            {
                "instrument_id": "ETF1",
                "as_of_date": "2026-07-18",
                "eligibility": "eligible",
                "score_eligible": True,
                "source_id": "sec-filing",
                "source_authority": "sec_edgar",
                "sections_json": _sections_json(latest_values, "2026-07-18"),
                **latest_values,
            },
            {
                "instrument_id": "ETF1",
                "as_of_date": "2026-07-17",
                "eligibility": "eligible",
                "score_eligible": True,
                "source_id": "sec-filing",
                "source_authority": "sec_edgar",
                "sections_json": _sections_json(older_values, "2026-07-17"),
                **older_values,
            },
        ]
    )

    row = build_screen_rows(_snapshot(), fundamentals).iloc[0]

    assert row["valuation"] == 8.0


def test_screen_rows_fail_closed_for_nullable_fundamental_metadata() -> None:
    fundamentals = pd.DataFrame(
        [
            {
                "instrument_id": "ETF1",
                "as_of_date": "2026-07-18",
                "eligibility": pd.NA,
                "score_eligible": pd.NA,
                "warnings": pd.NA,
                "valuation": 9.0,
            }
        ]
    )

    row = build_screen_rows(_snapshot(), fundamentals).iloc[0]

    assert pd.isna(row["valuation"])
    assert pd.isna(row["valuation_percentile"])


def test_screen_rows_fail_closed_when_snapshot_as_of_is_unavailable() -> None:
    values = {"valuation": 8.0, "profitability": 7.0, "leverage": 6.0, "growth": 5.0, "shareholder_return": 4.0}
    fundamentals = pd.DataFrame(
        [
            {
                "instrument_id": "ETF1",
                "as_of_date": "2026-07-18",
                "eligibility": "eligible",
                "score_eligible": True,
                "source_id": "sec-filing",
                "source_authority": "sec_edgar",
                "sections_json": _sections_json(values, "2026-07-18"),
                **values,
            }
        ]
    )
    snapshot = _snapshot()
    snapshot.data_report.as_of_date = "unavailable"

    row = build_screen_rows(snapshot, fundamentals).iloc[0]

    assert row["freshness"] == "unavailable"
    assert pd.isna(row["valuation"])
    assert pd.isna(row["quality"])


def test_snapshot_query_carries_reproducible_lineage() -> None:
    frame = build_screen_rows(_snapshot(), pd.DataFrame())
    first = query_for_snapshot(_snapshot(), frame)
    second = query_for_snapshot(_snapshot(), frame.copy())
    assert first.checksum == second.checksum
    assert first.as_of == "2026-07-18"
    assert first.universe_revision == "revision-3"
    assert first.formula_version == "canonical-v1"
    assert dict(first.dataset_checksums)["local_screen_rows"]
