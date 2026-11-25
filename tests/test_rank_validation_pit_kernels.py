"""Compiled point-in-time picks of rank validation vs their former pandas form (the oracles): exact equality."""

from __future__ import annotations

from dataclasses import fields, replace
import math

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


def _oracle_attach(price_evidence, fundamentals, score_columns=("quality_score", "value_score", "v3_score")):
    """`attach_fundamental_evidence` of base 52d46f27."""
    score_columns = list(score_columns)
    required = {"instrument_id", "effective_at", "known_at", *score_columns}
    result = price_evidence.copy()
    if not rv._has_columns(fundamentals, required) or result.empty:
        return result
    funds = fundamentals.copy()
    funds["_known"] = funds["known_at"].map(_aware_timestamp)
    funds["_effective"] = funds["effective_at"].map(rv._date_value)
    funds["instrument_id"] = funds["instrument_id"].astype(str)
    funds = funds.loc[funds["_known"].notna() & funds["_effective"].notna()]
    conflicts: dict[str, list[str]] = {}
    for cutoff_text, group in result.groupby("known_at", sort=False):
        cutoff = _aware_timestamp(cutoff_text)
        if cutoff is None:
            continue
        usable = funds.loc[funds["_known"].le(cutoff) & funds["_effective"].map(lambda value: value <= cutoff.date())]
        if usable.empty:
            continue
        chosen: list[pd.Series] = []
        for instrument, rows in usable.groupby("instrument_id", sort=True):
            top = rows.loc[rows["_effective"].eq(rows["_effective"].max())]
            top = top.loc[top["_known"].eq(top["_known"].max())]
            values = top[score_columns].apply(pd.to_numeric, errors="coerce")
            if len(values.drop_duplicates()) > 1:
                conflicts.setdefault(str(cutoff_text), []).append(str(instrument))
                continue
            chosen.append(top.iloc[-1])
        by_instrument = pd.DataFrame(chosen).set_index("instrument_id") if chosen else pd.DataFrame(columns=score_columns)
        for column in score_columns:
            result.loc[group.index, column] = pd.to_numeric(group["instrument_id"].astype(str).map(by_instrument[column]), errors="coerce")
    result.attrs["fundamental_conflicts"] = conflicts
    return result


def test_attach_fundamental_evidence_matches_the_oracle() -> None:
    funds = _evidence().rename(columns={"momentum_score": "growth"})[
        ["instrument_id", "effective_at", "known_at", "quality_score", "value_score", "v3_score", "growth"]]
    funds.loc[len(funds)] = ["B", "2020-01-01", "2020-01-02T00:00:00Z", "3.0", float("nan"), float("nan"), 0.5]  # text, same number
    cutoffs = ["2019-12-01T23:00:00Z", "2019-12-02T00:00:00Z", "2020-01-02T00:00:00Z", "2020-02-02T00:00:00Z",
               "2020-03-02T00:00:00Z", "2020-01-01", None]
    evidence = pd.DataFrame([
        {"instrument_id": item, "known_at": text, "effective_at": text, "quality_score": float("nan"),
         "value_score": float("nan"), "v3_score": float("nan"), "momentum_score": 0.1}
        for text in cutoffs for item in ("A", "B", "C", "D", "7", "E", "F", "G")
    ])
    conflicts = []
    for frame in (funds, funds.iloc[::-1].reset_index(drop=True)):
        for columns in (("quality_score", "value_score", "v3_score"), ("growth", "quality_score"), ("value_score",)):
            expected = _oracle_attach(evidence, frame, columns)
            got = rv.attach_fundamental_evidence(evidence, frame, columns)
            pd.testing.assert_frame_equal(got, expected, check_exact=True)
            assert got.attrs == expected.attrs
            conflicts.append(expected.attrs["fundamental_conflicts"])
    assert any(conflicts) and not all(conflicts)
    first = evidence.iloc[:8]  # one cut-off: only row 7 is known; a new score column is created
    pd.testing.assert_frame_equal(rv.attach_fundamental_evidence(first, funds, ("growth",)),
                                  _oracle_attach(first, funds, ("growth",)), check_exact=True)


def _replay_frames(names: int = 6, sessions: int = 30) -> dict[str, object]:
    days = [item.date() for item in pd.bdate_range("2024-01-02", periods=sessions)]
    decisions = days[5:20:3]
    prices = pd.DataFrame([
        {"instrument_id": f"I{item}", "date": day, "known_at": f"{day.isoformat()}T23:59:59Z",
         "adjusted_close": 100.0 + item + 3.0 * math.sin(index / (2.0 + item)), "delisted": item == 5 and index == 16}
        for item in range(names) for index, day in enumerate(days)
    ])
    memberships = pd.DataFrame([
        {"instrument_id": f"I{item}", "valid_from": "2023-01-01", "valid_to": None, "known_at": f"{day.isoformat()}T00:00:00Z",
         "snapshot_date": day.isoformat(), "snapshot_complete": True}
        for day in days for item in range(names)
    ])
    costs = pd.DataFrame([{"instrument_id": f"I{item}", "known_at": "2023-12-01T00:00:00Z", "round_trip_cost_bps": 10.0 + item,
                           "cost_model_id": COST_MODEL_ID} for item in range(names)])
    texts = [f"{day.isoformat()}T23:59:59Z" for day in decisions]
    comparator = pd.DataFrame([{"decision_date": day.isoformat(), "net_return": 0.001} for day in decisions])

    def evidence(shift: float) -> pd.DataFrame:
        return pd.DataFrame([
            {"instrument_id": f"I{item}", "effective_at": text, "known_at": text, "quality_score": (item * shift) % 1,
             "value_score": (item * 0.37 + shift) % 1, "momentum_score": (item * 0.61) % 1, "v3_score": (item * shift * 0.7) % 1,
             "sector": "s", "size_bucket": "large", "size_value": 1.0 + item}
            for text in texts for item in range(names)
        ])

    policy = replace(rv.load_rank_validation_policy(), holding_period_sessions=3, minimum_universe_support=3, top_n=2)
    return {"evidence": [evidence(0.3), evidence(0.8)], "memberships": memberships, "prices": prices, "costs": costs,
            "comparator": comparator, "times": texts, "policy": policy}


def test_replays_sharing_inputs_equal_separate_replays(monkeypatch) -> None:
    frames = _replay_frames()
    calls: list[int] = []
    forward = rv._forward_returns
    monkeypatch.setattr(rv, "_forward_returns", lambda frame, *args: calls.append(len(frame)) or forward(frame, *args))

    def run(evidence, inputs=None):
        return rv.replay_rank_panel(evidence, frames["memberships"], frames["prices"], frames["costs"], frames["comparator"],
                                    frames["comparator"], frames["times"], policy=frames["policy"], inputs=inputs)

    separate = [run(item) for item in frames["evidence"]]
    separate_calls = len(calls)
    shared = rv.ReplayInputs(frames["memberships"], frames["prices"], frames["costs"])
    together = [run(item, shared) for item in frames["evidence"]]
    assert separate_calls == 12 and len(calls) - separate_calls == 6  # the second shared replay reuses every forward return
    for one, two in zip(separate, together):
        assert one.status == "complete" and not one.rows.empty
        for item in fields(one):
            left, right = getattr(one, item.name), getattr(two, item.name)
            if isinstance(left, pd.DataFrame):
                pd.testing.assert_frame_equal(left, right, check_exact=True)
            else:
                assert left == right
