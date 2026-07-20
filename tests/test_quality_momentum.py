from __future__ import annotations

import json
from datetime import date

import pandas as pd

from etf_cockpit.signals.quality_momentum import build_quality_momentum_frame, quality_momentum_weights


def _fundamental(instrument_id: str, as_of: str, *, values: tuple[float, ...], sector: str, authority: str = "sec_edgar") -> dict[str, object]:
    fields = ("valuation", "profitability", "leverage", "growth", "shareholder_return")
    sections = {
        field: {"value": value, "period_end": as_of, "source_id": "sec-filing", "source_authority": authority}
        for field, value in zip(fields, values, strict=True)
    }
    return {
        "instrument_id": instrument_id,
        "as_of_date": as_of,
        "available_at": as_of,
        "valuation": values[0],
        "profitability": values[1],
        "leverage": values[2],
        "growth": values[3],
        "shareholder_return": values[4],
        "eligibility": "eligible",
        "score_eligible": True,
        "source_authority": authority,
        "source_id": "sec-filing",
        "manual_review": False,
        "merge_status": "single_source",
        "rejected_source_count": 0,
        "execution_allowed": False,
        "sections_json": json.dumps(sections, separators=(",", ":")),
        "sector": sector,
    }


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=200)
    rows = []
    for offset, instrument_id in enumerate(("A", "B", "C", "D")):
        for index, timestamp in enumerate(dates):
            rows.append(
                {
                    "date": timestamp,
                    "etf_id": instrument_id,
                    "adjusted_close": 100.0 + index * (0.20 + offset * 0.03),
                }
            )
    return pd.DataFrame(rows)


def test_quality_momentum_is_point_in_time_and_sector_neutral() -> None:
    as_of = date(2025, 10, 7)
    fundamentals = pd.DataFrame(
        [
            _fundamental("A", "2025-06-30", values=(4, 8, 2, 7, 8), sector="technology"),
            _fundamental("B", "2025-06-30", values=(5, 6, 5, 5, 6), sector="technology"),
            _fundamental("C", "2025-06-30", values=(6, 7, 3, 6, 7), sector="healthcare"),
            _fundamental("D", "2025-06-30", values=(7, 5, 6, 4, 5), sector="healthcare"),
            _fundamental("A", "2025-12-31", values=(1, 1, 1, 1, 1), sector="technology"),
        ]
    )

    result = build_quality_momentum_frame(_prices(), fundamentals, as_of_date=as_of)

    assert set(result.loc[result["status"] == "available", "instrument_id"]) == {"A", "B", "C", "D"}
    assert result["fundamental_as_of"].eq("2025-06-30").all()
    assert result["execution_allowed"].eq(False).all()
    assert result["source_authority"].eq("sec_edgar").all()
    assert result["quality_score"].between(0, 1).all()
    assert result["composite_score"].between(0, 1).all()
    assert result.loc[result["instrument_id"] == "A", "quality_score"].item() > result.loc[result["instrument_id"] == "B", "quality_score"].item()


def test_non_official_or_missing_sector_evidence_fails_closed() -> None:
    fundamentals = pd.DataFrame(
        [
            _fundamental("A", "2025-06-30", values=(4, 8, 2, 7, 8), sector="technology", authority="vendor_unofficial"),
            _fundamental("B", "2025-06-30", values=(5, 6, 5, 5, 6), sector=""),
        ]
    )

    result = build_quality_momentum_frame(_prices(), fundamentals, as_of_date=date(2025, 10, 7))

    assert set(result["reason"]) == {
        "unavailable_non_official_fundamentals",
        "unavailable_missing_sector_for_neutralisation",
        "unavailable_missing_official_point_in_time_fundamentals",
    }
    assert result["status"].eq("unavailable").all()
    assert quality_momentum_weights(result, ["A", "B", "C", "D"]).sum() == 0


def test_quality_momentum_weights_are_deterministic_and_long_only() -> None:
    fundamentals = pd.DataFrame(
        [
            _fundamental("A", "2025-06-30", values=(4, 8, 2, 7, 8), sector="technology"),
            _fundamental("B", "2025-06-30", values=(5, 6, 5, 5, 6), sector="technology"),
            _fundamental("C", "2025-06-30", values=(6, 7, 3, 6, 7), sector="healthcare"),
            _fundamental("D", "2025-06-30", values=(7, 5, 6, 4, 5), sector="healthcare"),
        ]
    )
    evidence = build_quality_momentum_frame(_prices(), fundamentals, as_of_date=date(2025, 10, 7))

    first = quality_momentum_weights(evidence, ["A", "B", "C", "D"])
    second = quality_momentum_weights(evidence, ["A", "B", "C", "D"])

    pd.testing.assert_series_equal(first, second)
    assert first.sum() == 1.0
    assert (first >= 0).all()


def test_future_availability_vintage_is_not_used_when_reporting_period_is_old() -> None:
    fundamentals = pd.DataFrame(
        [
            _fundamental("A", "2025-06-30", values=(4, 8, 2, 7, 8), sector="technology"),
            {
                **_fundamental("A", "2025-06-30", values=(1, 1, 1, 1, 1), sector="technology"),
                "available_at": "2025-12-31",
            },
            _fundamental("B", "2025-06-30", values=(5, 6, 5, 5, 6), sector="technology"),
        ]
    )

    result = build_quality_momentum_frame(_prices(), fundamentals, as_of_date=date(2025, 10, 7))

    selected = result.loc[result["instrument_id"] == "A"].iloc[0]
    assert selected["status"] == "available"
    assert selected["fundamental_available_at"] == "2025-06-30"
    assert selected["quality_score"] > 0.5


def test_missing_availability_timestamp_fails_closed() -> None:
    row = _fundamental("A", "2025-06-30", values=(4, 8, 2, 7, 8), sector="technology")
    row.pop("available_at")

    result = build_quality_momentum_frame(
        _prices(),
        pd.DataFrame([row, _fundamental("B", "2025-06-30", values=(5, 6, 5, 5, 6), sector="technology")]),
        as_of_date=date(2025, 10, 7),
    )

    assert result.loc[result["instrument_id"] == "A", "reason"].item() == "unavailable_missing_official_availability_timestamp"
