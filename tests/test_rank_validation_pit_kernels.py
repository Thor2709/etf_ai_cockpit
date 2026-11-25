"""Compiled point-in-time picks of rank validation vs their former pandas form (the oracles): exact equality."""

from __future__ import annotations

import pandas as pd

from etf_cockpit.analysis.decision import rank_validation as rv
from etf_cockpit.analysis.decision.rank_validation import _aware_timestamp, _finite
from etf_cockpit.portfolio.costs import COST_MODEL_ID


def _oracle_cost(costs: pd.DataFrame, instrument_id: str, cutoff: pd.Timestamp) -> float | None:
    """`_point_in_time_cost` of base 52d46f27: one pandas lookup per (instrument, cut-off)."""
    rows = costs.loc[
        costs["instrument_id"].astype(str).eq(instrument_id)
        & costs["cost_model_id"].astype(str).eq(COST_MODEL_ID)
    ].copy()
    rows["_known"] = rows["known_at"].map(_aware_timestamp)
    rows = rows.loc[rows["_known"].notna() & rows["_known"].le(cutoff)]
    if rows.empty:
        return None
    latest = rows["_known"].max()
    rows = rows.loc[rows["_known"].eq(latest)]
    if len(rows) != 1:
        return None
    value = rows.iloc[0]["round_trip_cost_bps"]
    if not _finite(value) or float(value) < 0:
        return None
    return float(value)


def _costs() -> pd.DataFrame:
    rows = [
        ("A", "2020-01-01T00:00:00Z", 10.0, COST_MODEL_ID),
        ("A", "2020-02-01T00:00:00Z", 12.5, COST_MODEL_ID),
        ("A", "2020-03-01T00:00:00+01:00", 14.0, COST_MODEL_ID),  # 2020-02-29 23:00 UTC
        ("B", "2020-01-15T00:00:00Z", 8.0, COST_MODEL_ID),
        ("B", "2020-01-15T00:00:00Z", 9.0, COST_MODEL_ID),  # tie at the latest stamp: ambiguous
        ("B", "2020-01-10T00:00:00Z", 7.0, COST_MODEL_ID),  # unsorted input
        ("C", "2020-01-01T00:00:00Z", float("nan"), COST_MODEL_ID),
        ("C", "2019-12-01T00:00:00Z", 5.0, COST_MODEL_ID),
        ("D", "2020-01-01T00:00:00Z", -1.0, COST_MODEL_ID),
        ("E", "2020-01-01T00:00:00Z", 3.0, "other-model"),
        ("F", "2020-01-01", 4.0, COST_MODEL_ID),  # naive stamp: never known
        ("F", None, 4.5, COST_MODEL_ID),
        ("G", "2020-01-01T00:00:00Z", 0.0, COST_MODEL_ID),
        ("G", "2020-01-01T00:00:00Z", 0.0, COST_MODEL_ID),  # agreeing tie still ambiguous
        (7, "2020-01-01T00:00:00Z", 2.0, COST_MODEL_ID),  # non-text id
        ("H", "2020-01-01T00:00:00Z", "6.0", COST_MODEL_ID),  # text value: not a number
        ("I", "2020-01-01T00:00:00Z", float("inf"), COST_MODEL_ID),
    ]
    return pd.DataFrame(rows, columns=["instrument_id", "known_at", "round_trip_cost_bps", "cost_model_id"])


_IDS = ["A", "B", "C", "D", "E", "F", "G", "7", "H", "I", "absent"]
_CUTOFFS = [pd.Timestamp(text, tz="UTC") for text in (
    "2019-06-01", "2019-12-01", "2020-01-01", "2020-01-12", "2020-01-15", "2020-02-29 23:00", "2020-02-29 22:59:59.999999999", "2021-01-01",
)]


def test_point_in_time_costs_match_the_per_query_oracle() -> None:
    for costs in (_costs(), _costs().iloc[::-1].reset_index(drop=True), _costs().assign(round_trip_cost_bps=lambda f: f["round_trip_cost_bps"].astype(object))):
        ids = [item for item in _IDS for _ in _CUTOFFS]
        cutoffs = [cutoff for _ in _IDS for cutoff in _CUTOFFS]
        expected = [_oracle_cost(costs, item, cutoff) for item, cutoff in zip(ids, cutoffs)]
        assert rv._point_in_time_costs(costs, ids, cutoffs) == expected
    assert any(value is not None for value in expected) and None in expected


def test_point_in_time_costs_handle_empty_inputs() -> None:
    empty = _costs().iloc[0:0]
    assert rv._point_in_time_costs(empty, ["A"], [_CUTOFFS[-1]]) == [None]
    assert rv._point_in_time_costs(_costs(), [], []) == []
