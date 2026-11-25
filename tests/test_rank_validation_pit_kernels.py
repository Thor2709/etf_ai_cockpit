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


def _oracle_latest(evidence_frame: pd.DataFrame, active_ids: pd.Series, cutoff: pd.Timestamp) -> pd.DataFrame | str:
    """The per-cut-off latest-evidence pick of `replay_rank_panel` at base 52d46f27."""
    decision_day = cutoff.date()
    available_evidence = evidence_frame.loc[
        evidence_frame["_known_at"].notna()
        & evidence_frame["_effective_date"].notna()
        & evidence_frame["_known_at"].le(cutoff)
        & evidence_frame["_effective_date"].map(lambda value: value <= decision_day)
        & evidence_frame["instrument_id"].astype(str).isin(active_ids)
    ].copy()
    if available_evidence.empty:
        return "point_in_time_evidence_unavailable"
    available_evidence["instrument_id"] = available_evidence["instrument_id"].astype(str)
    available_evidence = available_evidence.sort_values(["instrument_id", "_effective_date", "_known_at"], kind="stable")
    keys = ["instrument_id", "_effective_date", "_known_at"]
    latest_keys = available_evidence.groupby("instrument_id", sort=False).tail(1)[keys]
    latest_candidates = available_evidence.merge(latest_keys, on=keys, how="inner", validate="many_to_one")
    conflict_columns = [column for column in latest_candidates.columns if column not in keys]
    if any(
        len(group[conflict_columns].drop_duplicates()) > 1
        for _, group in latest_candidates.groupby(keys, sort=False, dropna=False)
    ):
        return "point_in_time_evidence_has_ambiguous_latest_rows"
    latest = latest_candidates.drop_duplicates(subset=keys, keep="last")
    if latest["instrument_id"].duplicated().any() or set(latest["instrument_id"]) != set(active_ids):
        return "point_in_time_evidence_incomplete_for_membership"
    return latest


def _evidence() -> pd.DataFrame:
    nan = float("nan")
    rows = [  # instrument, effective, known, quality, value, sector
        ("A", "2020-01-01", "2020-01-02T00:00:00Z", 1.0, 2.0, "x"),
        ("A", "2020-02-01", "2020-02-02T00:00:00Z", 1.5, 2.5, "x"),
        ("A", "2020-02-01", "2020-03-01T00:00:00Z", 1.6, 2.6, "x"),  # revision known later
        ("B", "2020-01-01", "2020-01-02T00:00:00Z", 3.0, nan, "y"),
        ("B", "2020-01-01", "2020-01-02T00:00:00Z", 3.0, nan, "y"),  # agreeing tie (NaN equal)
        ("C", "2020-01-01", "2020-01-02T00:00:00Z", 4.0, 1.0, "z"),
        ("C", "2020-02-01", "2020-02-02T00:00:00Z", 4.0, 1.0, "z"),
        ("C", "2020-02-01", "2020-02-02T00:00:00Z", 4.0, 1.0, "w"),  # disagreeing tie (text column)
        ("D", "2020-03-01", "2020-01-15T00:00:00Z", 5.0, 5.0, "x"),  # effective after it is known
        ("D", "2019-12-01", "2019-12-02", 5.5, 5.5, "x"),  # naive stamp: never known
        (7, "2019-12-01", "2019-12-02T00:00:00+01:00", 6.0, 6.0, "x"),
        ("E", None, "2019-12-02T00:00:00Z", 7.0, 7.0, "x"),  # no effective date
        ("F", "2020-01-01", "2020-01-02T00:00:00Z", 8.0, 8.0, "x"),
        ("F", "2020-01-01", "2020-01-02T00:00:00Z", 8.5, 8.0, "x"),  # disagreeing tie (score)
    ]
    frame = pd.DataFrame(rows, columns=["instrument_id", "effective_at", "known_at", "quality_score", "value_score", "sector"])
    frame["momentum_score"] = 0.5
    frame["v3_score"] = nan
    for column in ("known_at", "effective_at"):
        frame[f"_{column}"] = rv._map_repeated(frame[column], _aware_timestamp)
    frame["_effective_date"] = rv._map_repeated(frame["effective_at"], rv._date_value)
    return frame


def test_latest_evidence_matches_the_per_cutoff_oracle() -> None:
    cutoffs = [pd.Timestamp(text, tz="UTC") for text in (
        "2019-11-30", "2019-12-01 23:00", "2019-12-02", "2020-01-02", "2020-01-31 23:59:59", "2020-02-02", "2020-02-29",
        "2020-03-01", "2020-03-02", "2021-01-01",
    )]
    actives = [["A"], ["A", "B"], ["B", "7"], ["A", "C"], ["D"], ["E"], ["F"], ["A", "B", "7", "G"], ["G"], []]
    dated = _evidence().loc[lambda f: f["effective_at"].notna()]  # base raised TypeError on an undated row
    for frame in (dated, dated.iloc[::-1].reset_index(drop=True)):
        picks = rv._latest_known_rows(frame["instrument_id"], frame["effective_at"], frame["known_at"], cutoffs)
        seen = set()
        for position, cutoff in enumerate(cutoffs):
            for ids in actives:
                active = pd.Series(ids, dtype=object)
                expected = _oracle_latest(frame, active, cutoff)
                got = rv._latest_evidence(frame, picks, active, position)
                if isinstance(expected, str):
                    assert got == expected, (cutoff, ids)
                else:
                    pd.testing.assert_frame_equal(got.reset_index(drop=True), expected.reset_index(drop=True), check_exact=True)
                seen.add(expected if isinstance(expected, str) else "rows")
        assert seen == {"rows", "point_in_time_evidence_unavailable", "point_in_time_evidence_has_ambiguous_latest_rows",
                        "point_in_time_evidence_incomplete_for_membership"}
