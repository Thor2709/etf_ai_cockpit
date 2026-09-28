from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.application.portfolio_valuation import (
    build_portfolio_valuation_history,
    load_portfolio_valuation_history,
    save_portfolio_valuation_history,
)
from etf_cockpit.portfolio.valuation import calculate_money_weighted_return, link_time_weighted_return


def _history(
    dates: pd.DatetimeIndex | list[pd.Timestamp],
    *,
    prices: list[float],
    cash: list[float],
    quantities: list[float] | None = None,
    events: list[tuple[int, str, float]] | None = None,
) -> pd.DataFrame:
    positions = [1.0] * len(dates) if quantities is None else quantities
    event_rows = [
        {"date": dates[index], "event_type": event_type, "amount": amount}
        for index, event_type, amount in (events or [])
    ]
    report = build_portfolio_valuation_history(
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "quantity": positions}),
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "price": prices}),
        pd.DataFrame({"date": dates, "cash_value": cash}),
        pd.DataFrame(event_rows, columns=["date", "event_type", "amount"]),
        decision_time=dates[-1],
    )
    assert report["execution_allowed"] is False
    return report["snapshots"]


def test_external_flow_does_not_affect_same_instant_twr() -> None:
    dates = pd.bdate_range("2026-01-05", periods=2)
    baseline = _history(dates, prices=[100.0, 110.0], cash=[0.0, 0.0])
    contributed = _history(
        dates,
        prices=[100.0, 110.0],
        cash=[0.0, 50.0],
        events=[(1, "contribution", 50.0)],
    )

    baseline_return = link_time_weighted_return(baseline)
    contributed_return = link_time_weighted_return(contributed)

    assert contributed.iloc[-1]["total_value"] == 160.0
    assert contributed.iloc[-1]["invested_capital"] == 150.0
    assert contributed_return["value"] == pytest.approx(baseline_return["value"])
    assert contributed_return["value"] == pytest.approx(0.1)


def test_cash_funded_purchase_conserves_total_value() -> None:
    dates = pd.bdate_range("2026-01-05", periods=2)
    snapshots = _history(
        dates,
        prices=[100.0, 100.0],
        cash=[50.0, 0.0],
        quantities=[1.0, 1.5],
        events=[(1, "purchase", 50.0)],
    )

    assert snapshots["total_value"].tolist() == [150.0, 150.0]
    assert snapshots.iloc[-1]["external_flow"] == 0.0
    assert snapshots.iloc[-1]["period_return"] == pytest.approx(0.0)


def test_dividend_coupon_fee_tax_internal_accounting() -> None:
    dates = pd.bdate_range("2026-01-05", periods=4)
    snapshots = _history(
        dates,
        prices=[100.0, 100.0, 100.0, 100.0],
        cash=[0.0, 10.0, 8.0, 7.0],
        events=[(1, "dividend", 7.0), (1, "coupon", 3.0), (2, "fee", 2.0), (3, "tax", 1.0)],
    )

    assert snapshots["investment_pnl"].iloc[1:].tolist() == [10.0, -2.0, -1.0]
    assert snapshots["external_flow"].tolist() == [0.0, 0.0, 0.0, 0.0]
    assert snapshots.iloc[1]["dividends"] == 7.0
    assert snapshots.iloc[1]["coupons"] == 3.0
    assert snapshots.iloc[2]["fees"] == 2.0
    assert snapshots.iloc[3]["taxes"] == 1.0


def test_sub_year_mwr_deannualisation_and_dietz_fallback() -> None:
    dates = [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-07-01")]
    subyear = _history(dates, prices=[100.0, 110.0], cash=[0.0, 0.0])
    xirr_result = calculate_money_weighted_return(subyear)

    assert xirr_result["method"] == "xirr_deannualized_period_return"
    assert xirr_result["value"] == pytest.approx(0.1, abs=1e-10)
    assert xirr_result["annualized_xirr"] > xirr_result["value"]
    assert "de-annualised" in str(xirr_result["label"])

    fallback_dates = pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"])
    fallback = _history(
        fallback_dates,
        prices=[100.0, 250.0, 200.0, 320.0],
        cash=[0.0, 0.0, 0.0, 0.0],
        events=[(1, "withdrawal", 150.0), (2, "contribution", 120.0)],
    )
    dietz_result = calculate_money_weighted_return(fallback)

    assert dietz_result["method"] == "modified_dietz_fallback"
    assert dietz_result["status"] == "available"
    assert dietz_result["value"] is not None
    assert "not annualised" in str(dietz_result["label"])


def test_reproduction_from_saved_daily_snapshots(tmp_path) -> None:
    dates = pd.bdate_range("2026-01-05", periods=3)
    snapshots = _history(dates, prices=[100.0, 110.0, 121.0], cash=[0.0, 0.0, 0.0])
    expected = link_time_weighted_return(snapshots)
    expected_period = link_time_weighted_return(snapshots, start=dates[0], end=dates[1])

    saved_path = save_portfolio_valuation_history(snapshots, storage_root=tmp_path)
    loaded = load_portfolio_valuation_history(storage_root=tmp_path)
    reproduced = link_time_weighted_return(loaded["snapshots"])
    reproduced_period = link_time_weighted_return(loaded["snapshots"], start=dates[0], end=dates[1])

    assert saved_path.name == "portfolio_valuations.parquet"
    assert loaded["status"] == "partial"
    assert reproduced["value"] == pytest.approx(expected["value"])
    assert reproduced["value"] == pytest.approx(0.21)
    assert reproduced_period["value"] == pytest.approx(expected_period["value"])
    assert reproduced_period["value"] == pytest.approx(0.1)


def test_missing_or_stale_price_makes_performance_unavailable() -> None:
    dates = pd.bdate_range("2026-01-05", periods=3)
    snapshots = _history(dates, prices=[100.0, float("nan"), 120.0], cash=[0.0, 0.0, 0.0])

    result = link_time_weighted_return(snapshots)

    assert snapshots.iloc[1]["valuation_status"] == "unavailable"
    assert "price_missing_or_invalid:AAA" in snapshots.iloc[1]["missing_reasons"]
    assert result["status"] == "unavailable"
    assert result["value"] is None

    late_event_report = build_portfolio_valuation_history(
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "quantity": [1.0] * len(dates)}),
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "price": [100.0, 110.0, 120.0]}),
        pd.DataFrame({"date": dates, "cash_value": [0.0, 0.0, 0.0]}),
        pd.DataFrame(
            {
                "date": [dates[1]],
                "event_type": ["contribution"],
                "amount": [25.0],
                "available_at": [pd.Timestamp("2026-01-08T09:00:00Z")],
            }
        ),
        decision_time=pd.Timestamp("2026-01-07T12:00:00Z"),
    )

    assert late_event_report["snapshots"].iloc[1]["flow_status"] == "unavailable"
    assert "events_not_available_by_decision_time" in late_event_report["snapshots"].iloc[1]["missing_reasons"]
    assert late_event_report["time_weighted_return"] is None

    missing_inputs = build_portfolio_valuation_history(
        None,
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "price": [100.0, 110.0, 120.0]}),
        pd.DataFrame({"date": dates, "cash_value": [0.0, 0.0, 0.0]}),
        pd.DataFrame(columns=["date", "event_type", "amount"]),
        decision_time=dates[-1],
    )

    assert missing_inputs["status"] == "unavailable"
    assert missing_inputs["time_weighted_return"] is None
    assert "holdings evidence is unavailable" in missing_inputs["reason"]
