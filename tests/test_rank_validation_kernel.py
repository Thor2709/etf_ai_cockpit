from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import math
from statistics import NormalDist, stdev

import numpy as np
import pandas as pd

from etf_cockpit.analysis.decision import rank_validation as rv
from etf_cockpit.analysis.decision.rank_validation import (
    RankReplayReport,
    _aware_timestamp,
    _date_value,
    _finite,
    _finite_or,
    _true_flag,
    evaluate_rank_validation,
    load_rank_validation_policy,
    rank_validation_metrics,
)


def _oracle_forward_return(prices, instrument_id, cutoff, holding_period_sessions, *, target_session=None):
    """The per-row pandas rule of main 90df4331 (no outcome-knowledge bound): the parity oracle."""
    if target_session is None:
        all_sessions = sorted(
            value
            for value in (prices["_date"] if "_date" in prices else prices["date"].map(_date_value)).dropna().unique()
            if value > cutoff.date()
        )
        if len(all_sessions) >= holding_period_sessions:
            target_session = all_sessions[holding_period_sessions - 1]
    frame = prices.loc[prices["instrument_id"].astype(str).eq(instrument_id)].copy()
    frame["_known"] = frame["known_at"].map(_aware_timestamp)
    if "_date" not in frame:
        frame["_date"] = frame["date"].map(_date_value)
    frame["_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.loc[frame["_date"].notna()]
    frame = frame.sort_values(["_date", "_known"], kind="stable")
    entry_rows = frame.loc[
        frame["_date"].map(lambda value: value <= cutoff.date())
        & frame["_known"].notna()
        & frame["_known"].le(cutoff)
        & frame["_close"].map(_finite)
        & frame["_close"].gt(0)
    ]
    if entry_rows.empty:
        return None, "entry_price_unavailable_at_decision_time"
    entry_date = entry_rows["_date"].max()
    entry_candidates = entry_rows.loc[entry_rows["_date"].eq(entry_date)]
    if len(entry_candidates) != 1:
        return None, "entry_price_ambiguous"
    entry = float(entry_candidates.iloc[0]["_close"])
    if target_session is None:
        return None, "forward_price_window_not_matured"
    future = frame.loc[frame["_date"].map(lambda value: cutoff.date() < value <= target_session)]
    delisted = future.loc[future["delisted"].map(_true_flag)] if "delisted" in future.columns else future.iloc[0:0]
    if not delisted.empty:
        terminal_rows = delisted.loc[delisted["_date"].eq(delisted["_date"].min())]
        if "delisting_return" in terminal_rows and len(terminal_rows):
            reported_return = terminal_rows.iloc[-1]["delisting_return"]
            if pd.notna(reported_return):
                terminal_return = _finite_or(reported_return, math.nan)
                if not math.isfinite(terminal_return) or terminal_return < -1:
                    return None, "delisting_terminal_return_invalid"
                return terminal_return, "available_delisting_return"
        terminal_price = terminal_rows.iloc[-1]["_close"] if len(terminal_rows) else None
        if _finite(terminal_price) and float(terminal_price) >= 0:
            return float(terminal_price) / entry - 1.0, "available_delisted_terminal_price"
        return None, "delisting_terminal_value_unavailable"
    target = future.loc[future["_date"].eq(target_session)]
    if len(target) != 1 or not _finite(target.iloc[0]["_close"]) or float(target.iloc[0]["_close"]) <= 0:
        return None, "target_price_unavailable"
    return float(target.iloc[0]["_close"]) / entry - 1.0, "available"


def _messy_prices(seed: int) -> pd.DataFrame:
    """Prices with revisions, unknown and late knowledge times, bad closes, delistings and missing sessions."""
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2024-01-01", periods=30).date
    rows = []
    for instrument in ("A", "B", "C", "D"):
        close = 100.0
        delist_at = int(rng.integers(5, 40)) if instrument in {"B", "C", "D"} else 99
        for position, day in enumerate(sessions):
            if rng.random() < 0.08:  # a missing session for this instrument
                continue
            close *= 1.0 + rng.normal(0.0, 0.02)
            known = datetime(day.year, day.month, day.day, 22, tzinfo=timezone.utc)
            value = close
            draw = rng.random()
            if draw < 0.04:
                value = math.nan
            elif draw < 0.06:
                value = -1.0 if rng.random() < 0.5 else 0.0
            elif draw < 0.08:
                known = None
            elif draw < 0.10:
                known = known + timedelta(days=3)  # first published late
            row = {"instrument_id": instrument, "date": day, "known_at": known, "adjusted_close": value,
                   "delisted": position >= delist_at, "delisting_return": math.nan}
            if position == delist_at:
                row["delisting_return"] = {"B": -0.4, "C": math.nan, "D": -2.0}[instrument]
                if instrument == "C" and rng.random() < 0.5:
                    row["adjusted_close"] = math.nan
            rows.append(row)
            if rng.random() < 0.06:  # a revision of the same session, known later
                rows.append(dict(row, known_at=known + timedelta(days=2) if known else None,
                                 adjusted_close=value * 1.001 if _finite(value) else value))
            if rng.random() < 0.03:  # a tied duplicate: ambiguous entry
                rows.append(dict(row))
    frame = pd.DataFrame(rows).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return frame


def test_forward_return_matches_the_per_row_oracle_on_messy_prices() -> None:
    checked = 0
    for seed in range(4):
        prices = _messy_prices(seed)
        sessions = sorted(prices["date"].unique())
        for day in sessions[::3]:
            for hour in (21, 23):
                cutoff = pd.Timestamp(datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc))
                for instrument in ("A", "B", "C", "D", "MISSING"):
                    for holding in (1, 3, 8):
                        expected = _oracle_forward_return(prices, instrument, cutoff, holding)
                        assert rv._forward_return(prices, instrument, cutoff, holding) == expected
                        checked += 1
    assert checked == 4 * 10 * 2 * 5 * 3


def test_replay_forward_outcomes_match_the_oracle_for_all_cutoffs_at_once() -> None:
    prices = _messy_prices(11)
    prices["_known_at"] = prices["known_at"].map(_aware_timestamp)
    prices["_date"] = prices["date"].map(_date_value)
    sessions = sorted(prices["_date"].unique())
    cutoffs = [pd.Timestamp(datetime(d.year, d.month, d.day, 23, tzinfo=timezone.utc)) for d in sessions]
    targets = [sessions[i + 2] if i + 2 < len(sessions) else None for i in range(len(sessions))]
    statuses = set()
    for instrument in ("A", "B", "C", "D"):
        frame = prices.loc[prices["instrument_id"].eq(instrument)]
        batch = rv._forward_returns(frame, cutoffs, targets)
        expected = [_oracle_forward_return(prices, instrument, c, 3, target_session=t) for c, t in zip(cutoffs, targets)]
        assert batch == expected
        statuses.update(status for _, status in expected)
    assert {"available", "entry_price_unavailable_at_decision_time", "forward_price_window_not_matured",
            "available_delisting_return"} <= statuses


def _ic_rows(dates: int) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    rows = []
    for position in range(dates):
        day = date(2024, 1, 1) + timedelta(days=position)
        decision_time = f"{day.isoformat()}T23:59:59Z"
        for index in range(6):
            sector = "A" if index < 3 else "B"
            rows.append({
                "decision_time": decision_time, "decision_date": day.isoformat(), "instrument_id": f"{sector}{index % 3}",
                "ranker": "QV", "score": float(index), "net_return": float(rng.normal(0.01 * index, 0.05)),
                "benchmark_net_return": 0.001, "cash_net_return": 0.0001, "round_trip_cost_bps": 10.0,
                "sector": sector, "size_bucket": sector, "forward_window_end": (day + timedelta(days=1)).isoformat(),
            })
    return pd.DataFrame(rows)


def test_rank_metrics_report_the_minimum_detectable_ic_and_a_block_bootstrap_interval() -> None:
    policy = replace(load_rank_validation_policy(), minimum_universe_support=2, top_n=1, bottom_n=1)
    metrics = rank_validation_metrics(_ic_rows(12), "QV", policy=policy)
    ic = [item["rank_ic"] for item in metrics["per_decision"]]
    expected = (policy.significance_t + NormalDist().inv_cdf(0.8)) * stdev(ic) / math.sqrt(len(ic))
    assert metrics["rank_ic_mde"] == expected
    interval = metrics["rank_ic_ci"]
    assert interval["status"] == "available" and interval["observations"] == len(ic)
    assert interval["lower_5"] <= metrics["rank_ic_mean"] <= interval["upper_95"]


def test_validation_is_underpowered_when_only_the_decision_count_is_short(monkeypatch) -> None:
    monkeypatch.setattr(rv, "_factor_attribution", lambda *args: {"status": "available", "factors": []})
    replay = RankReplayReport(
        rows=_ic_rows(10), status="complete", insufficient_decision_times=(), config_hashes={}, config_versions={},
        pit_availability={"complete": True, "coverage_fraction": 1.0},
    )
    base = load_rank_validation_policy()
    holdout = ["2024-01-09T23:59:59Z", "2024-01-10T23:59:59Z"]
    short = evaluate_rank_validation(replay, holdout_decision_times=holdout, prices=pd.DataFrame(),
                                     policy=replace(base, minimum_decision_dates=3, minimum_universe_support=2,
                                                       top_n=1, bottom_n=1, minimum_group_support=1))
    enough = evaluate_rank_validation(replay, holdout_decision_times=holdout, prices=pd.DataFrame(),
                                      policy=replace(base, minimum_decision_dates=2, minimum_universe_support=2,
                                                        top_n=1, bottom_n=1, minimum_group_support=1))
    assert enough.status == "available"
    assert short.status == "underpowered"
    assert short.holdout["QV"]["rank_ic_mde"] is not None
