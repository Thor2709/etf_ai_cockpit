"""C1: point-in-time execution-cost-v1 round-trip table built from stored bars (reconstructed model estimate)."""

from __future__ import annotations

import math

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio.cost_table import build_pit_cost_table
from etf_cockpit.portfolio.costs import COST_MODEL_ID, estimate_execution_cost

_DAYS = pd.bdate_range("2024-01-01", "2024-06-28")
_MEMBERS = 24  # above the policy's 20-member minimum cross-section


def _prices() -> pd.DataFrame:
    rows = []
    for k, (name, currency) in enumerate((("A", "EUR"), ("B", "USD"), ("C", "EUR"), ("D", "JPY"))):
        for t, day in enumerate(_DAYS):
            close = 50.0 + 10.0 * k + 3.0 * math.sin(t / (3.0 + k))
            rows.append({
                "etf_id": name, "date": day, "close": close, "adjusted_close": close * 0.9, "currency": currency,
                "volume": float("nan") if name == "C" else 20_000.0 + 1_000.0 * ((t * 7 + k) % 5),
                "known_at": pd.Timestamp("2026-11-20T09:00:00Z"),  # a late fetch stamp, as in the real store
            })
    return pd.DataFrame(rows)


def _fx() -> pd.DataFrame:  # USD only: D (JPY) has no rate, so no EUR ADV
    return pd.DataFrame([
        {"as_of_date": day.date(), "pair": "USD/EUR", "base_currency": "USD", "quote_currency": "EUR",
         "rate": 0.9 + 0.001 * t, "source": "fixture", "ingested_at": pd.Timestamp("2026-11-20T10:00:00Z"),
         "available_at": day.tz_localize("UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59),
         "availability_basis": "market_close_unrevised"}
        for t, day in enumerate(_DAYS)
    ])


def test_month_end_rows_are_point_in_time_deterministic_and_never_filled() -> None:
    config = load_config()
    table, _ = build_pit_cost_table(_prices(), _fx(), config, order_value_eur=1000.0)
    again, _ = build_pit_cost_table(_prices(), _fx(), config, order_value_eur=1000.0)
    assert table.equals(again)
    assert set(table["instrument_id"]) == {"A", "B"}  # C: no volume, D: no JPY rate -> no row, never zero
    assert (table["cost_model_id"] == COST_MODEL_ID).all() and (table["cost_basis"] == "reconstructed_model").all()
    # month-end sessions with a full trailing volatility window; known at that session's close
    assert sorted(table.loc[table["instrument_id"].eq("A"), "known_at"].astype(str)) == [
        f"{day}T23:59:59Z" for day in ("2024-02-29", "2024-03-29", "2024-04-30", "2024-05-31", "2024-06-28")
    ]
    row = table.iloc[0]
    one_way = estimate_execution_cost(
        config, row["instrument_id"], 1000.0, adv_eur=row["adv_eur"], daily_volatility=row["daily_volatility"],
        conservative_tier=bool(row["conservative_tier"]),
    )
    assert row["round_trip_cost_bps"] == 2.0 * one_way.total_cost_bps > 0

    later = _prices()  # bars and FX after 2024-03-29 change: rows known by then must not move
    after = later["date"] > "2024-03-29"
    later.loc[after, ["close", "adjusted_close"]] *= 3.0
    later.loc[after, "volume"] *= 0.001
    fx = _fx()
    fx.loc[pd.to_datetime(fx["as_of_date"]) > "2024-03-29", "rate"] = 5.0
    moved, _ = build_pit_cost_table(later, fx, config, order_value_eur=1000.0)
    def split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        early = frame["known_at"] <= "2024-03-29T23:59:59Z"
        return frame.loc[early].reset_index(drop=True), frame.loc[~early].reset_index(drop=True)

    pd.testing.assert_frame_equal(split(moved)[0], split(table)[0])
    assert len(split(moved)[1]) == len(split(table)[1])
    assert not split(moved)[1]["round_trip_cost_bps"].equals(split(table)[1]["round_trip_cost_bps"])  # later rows see it


def test_rank_validation_replays_with_the_built_table(tmp_path) -> None:
    from etf_cockpit.analysis.decision.rank_validation import window_decision_times
    from etf_cockpit.application.rank_validation_service import build_rank_validation_report

    days = pd.bdate_range("2023-01-02", periods=520)
    prices = pd.DataFrame([
        {"etf_id": f"I{i}", "date": day, "known_at": f"{day.date()}T23:59:59Z", "currency": "EUR",
         "adjusted_close": close, "close": close, "volume": 10_000.0 + 100.0 * i, "stock_splits": 0.0,
         "actions_evidenced": True}
        for i in range(_MEMBERS)
        for t, day in enumerate(days)
        for close in [100.0 * math.exp(0.0004 * (i + 1) * t + 0.03 * math.sin(t / (4.0 + i)))]
    ])
    prices.to_parquet(tmp_path / "prices.parquet")
    times, _ = window_decision_times(prices.rename(columns={"etf_id": "instrument_id"}), 1, step_sessions=21,
                                     holding_period_sessions=21)
    pd.DataFrame([
        {"instrument_id": f"I{i}", "valid_from": "2022-01-01", "valid_to": None, "known_at": f"{day.date()}T00:00:00Z",
         "snapshot_date": day.date().isoformat(), "snapshot_complete": True}
        for i in range(_MEMBERS) for day in days
    ]).to_csv(tmp_path / "membership.csv", index=False)
    pd.DataFrame([{"decision_date": text[:10], "net_return": 0.0001} for text in times]).to_csv(tmp_path / "cash.csv", index=False)
    table, _ = build_pit_cost_table(prices, None, load_config(), order_value_eur=1000.0)
    table.to_parquet(tmp_path / "costs.parquet")

    def section(costs):
        report = build_rank_validation_report(
            root=tmp_path, years=(1,), benchmark_id="I0", prices_path=tmp_path / "prices.parquet",
            membership_path=tmp_path / "membership.csv", costs_path=costs, cash_path=tmp_path / "cash.csv",
        )
        return report["windows"][0]["sections"]["price_factors"]

    assert section(None)["covered_decisions"] == 0  # no cost table: every replay is empty (today's state)
    replayed = section(tmp_path / "costs.parquet")
    assert replayed["covered_decisions"] == len(times)
    assert replayed["development"] and replayed["holdout"]
