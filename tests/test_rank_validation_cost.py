"""Cost guards for rank validation: stamps are parsed once, never once per decision/instrument.

These pin work counts, not results: each guard also checks the result against the plain path.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd

from etf_cockpit.analysis.decision import rank_validation as rv
from etf_cockpit.application.rank_validation_service import build_rank_validation_report


def _prices(sessions: int = 40, names: int = 5) -> pd.DataFrame:
    days = [item.date() for item in pd.bdate_range("2024-01-02", periods=sessions)]
    rows = [
        {
            "instrument_id": f"I{item}",
            "date": day,
            "adjusted_close": 100.0 + item + 0.5 * index,
            "known_at": f"{day.isoformat()}T23:59:59Z",
        }
        for item in range(names)
        for index, day in enumerate(days)
    ]
    return pd.DataFrame(rows)


def _count_date_value(monkeypatch) -> list[int]:
    calls = [0]
    original = rv._date_value

    def counting(value: object) -> date | None:
        calls[0] += 1
        return original(value)

    monkeypatch.setattr(rv, "_date_value", counting)
    return calls


def test_forward_return_reuses_a_precomputed_date_column(monkeypatch) -> None:
    prices = _prices()
    cutoff = pd.Timestamp("2024-01-19T23:59:59Z")
    plain = rv._forward_return(prices, "I1", cutoff, 3)
    stamped = prices.assign(_date=prices["date"].map(rv._date_value))
    calls = _count_date_value(monkeypatch)
    assert rv._forward_return(stamped, "I1", cutoff, 3) == plain
    assert plain[1] == "available"
    assert calls[0] == 0  # the default of ``DataFrame.get`` used to be evaluated (a full-frame map) on every call


def test_factor_attribution_stamps_prices_once_for_all_decisions(monkeypatch) -> None:
    prices = _prices()
    decisions = [f"{day.isoformat()}T23:59:59Z" for day in sorted(prices["date"].unique())[20:24]]
    rows = pd.DataFrame(
        [
            {
                "decision_time": decision,
                "ranker": "r",
                "instrument_id": f"I{item}",
                "score": float(item),
                "quality_score": float(item),
                "value_score": float(item),
                "momentum_score": float(item),
            }
            for decision in decisions
            for item in range(5)
        ]
    )
    policy = replace(rv.load_rank_validation_policy(), top_n=3)
    seen: list[int] = []

    def fake_report(prices_for_risk: pd.DataFrame, *_args: object, **_kwargs: object) -> dict[str, object]:
        seen.append(len(prices_for_risk))
        return {}

    monkeypatch.setattr(rv, "build_factor_risk_report", fake_report)
    calls = _count_date_value(monkeypatch)
    result = rv._factor_attribution(rows, "r", prices, policy)
    assert result["status"] == "unavailable"  # the stub returns no contributions
    assert len(seen) == len(decisions)
    expected = [int((prices["date"] <= pd.Timestamp(item).date()).sum()) for item in decisions]
    assert seen == expected and seen[0] > 0  # the point-in-time cut-off still applies to every decision
    assert calls[0] == len(prices)  # once per price row, not once per decision


def test_report_counts_unverifiable_known_at_stamps_with_one_parse_per_distinct_stamp(tmp_path, monkeypatch) -> None:
    prices = _prices()
    prices.loc[prices.index[:3], "known_at"] = "not-a-timestamp"
    prices_path = tmp_path / "prices.csv"
    prices.to_csv(prices_path, index=False)
    membership_path = tmp_path / "membership.csv"
    pd.DataFrame([{"instrument_id": "I0"}]).to_csv(membership_path, index=False)
    parsed: list[object] = []
    original = pd.to_datetime

    def counting(value, *args, **kwargs):
        if isinstance(value, str):
            parsed.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(pd, "to_datetime", counting)
    report = build_rank_validation_report(
        root=tmp_path, years=(1,), prices_path=prices_path, membership_path=membership_path
    )
    assert report["inputs"]["price_rows_without_verifiable_known_at"] == 3
    assert len(parsed) == prices["known_at"].nunique()  # 40 stamps + 1 invalid, not one parse per price row
