from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.portfolio_valuation import build_portfolio_valuation_history
from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio import top_n_selection
from etf_cockpit.portfolio.costs import compare_realised_fill, estimate_execution_cost, fill_feasibility
from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series
from etf_cockpit.portfolio.top_n_selection import _UTILITY_FIELDS, _bootstrap_fields, _constraint_reasons
from etf_cockpit.portfolio.valuation import SNAPSHOT_COLUMNS, calculate_money_weighted_return


def _history(
    dates: pd.DatetimeIndex,
    prices: list[float],
    *,
    cash: list[float] | None = None,
    events: pd.DataFrame | None = None,
    decision_time: str | None = None,
) -> pd.DataFrame:
    cash_values = cash if cash is not None else [0.0] * len(dates)
    event_rows = events if events is not None else pd.DataFrame(columns=["date", "event_type", "amount"])
    report = build_portfolio_valuation_history(
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "quantity": [1.0] * len(dates)}),
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "price": prices}),
        pd.DataFrame({"date": dates, "cash_value": cash_values}),
        event_rows,
        decision_time=decision_time or (pd.Timestamp(dates[-1]).normalize() + pd.Timedelta(days=1)),
    )
    return report["snapshots"]


def _series_snapshots(dates: pd.DatetimeIndex, values: list[float]) -> pd.DataFrame:
    invested_capital: float | None = None
    rows: list[dict[str, object]] = []
    for index, (observed, value) in enumerate(zip(dates, values, strict=True)):
        invested_capital = value if index == 0 else invested_capital
        rows.append(
            {
                "date": observed,
                "cash_value": 0.0,
                "securities_value": value,
                "total_value": value,
                "external_flow": 0.0,
                "invested_capital": invested_capital,
                "dividends": 0.0,
                "coupons": 0.0,
                "fees": 0.0,
                "taxes": 0.0,
                "investment_pnl": float("nan") if index == 0 else value - values[index - 1],
                "period_return": float("nan") if index == 0 else value / values[index - 1] - 1.0,
                "valuation_status": "available",
                "flow_status": "available",
                "availability_evidence": "timestamped",
                "missing_reasons": "",
                "execution_allowed": False,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SNAPSHOT_COLUMNS)


def test_bootstrap_ranks_every_candidate_against_each_reference_sample() -> None:
    rows = []
    candidate_count = 15
    for index in range(candidate_count):
        rows.append(
            {
                "instrument_id": "zz-worst" if index == 0 else f"candidate-{index:02d}",
                "common_metrics": {
                    "net_expected_return": float(index),
                    "downside_risk": float(candidate_count - index),
                    "marginal_impact": float(index),
                    "liquidity": float(index),
                    "cost": float(candidate_count - index),
                    "evidence": float(index),
                },
            }
        )
    weights = {field: 1.0 / len(_UTILITY_FIELDS) for field in _UTILITY_FIELDS}

    _bootstrap_fields(rows, weights, top_n=10, bootstrap_count=250, seed=77)

    worst = next(row for row in rows if row["instrument_id"] == "zz-worst")
    assert worst["selection_probability"] == 0.0
    assert worst["rank_interval"] == [15, 15]


def test_unavailable_flow_keeps_event_metrics_unavailable() -> None:
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])
    snapshots = _history(
        dates,
        [100.0, 101.0],
        events=pd.DataFrame(
            {
                "date": [dates[1]],
                "event_type": ["dividend"],
                "amount": [7.0],
                "available_at": [pd.Timestamp("2026-01-08T09:00:00Z")],
            }
        ),
        decision_time="2026-01-07T12:00:00Z",
    )

    latest = snapshots.iloc[-1]
    assert latest["flow_status"] == "unavailable"
    assert all(pd.isna(latest[field]) for field in ("dividends", "coupons", "fees", "taxes"))
    income = build_portfolio_performance_series(snapshots, metric="income", aggregation="day")
    fees_tax = build_portfolio_performance_series(snapshots, metric="fees_tax", aggregation="day")
    assert income.points[-1].value is None
    assert fees_tax.points[-1].value is None


def test_range_currency_conversion_keeps_inception_cost_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-02-02", "2026-02-03"])
    snapshots = _series_snapshots(pd.DatetimeIndex(dates), [10_000.0] * len(dates))
    inception = dates[0].date()

    def conversion_rates(history: pd.DataFrame, _currency: str, _fx_rates: pd.DataFrame | None):
        return {
            observed.date(): (1.05 if observed.date() == inception else 1.20, None, "test-fx")
            for observed in history["date"]
        }

    monkeypatch.setattr("etf_cockpit.portfolio.performance_series._conversion_rates", conversion_rates)
    series = build_portfolio_performance_series(
        snapshots,
        metric="net_invested_capital",
        date_range="custom",
        aggregation="day",
        currency="USD",
        custom_start="2026-02-02",
        custom_end="2026-02-03",
    )

    assert series.points[-1].value == pytest.approx(10_500.0)


def test_money_weighted_return_requires_expected_session_coverage() -> None:
    dates = pd.DatetimeIndex(["2026-04-06", "2026-04-08"])
    snapshots = _history(dates, [1_000.0, 1_500.0])

    result = calculate_money_weighted_return(snapshots)

    assert result["status"] == "unavailable"
    assert result["value"] is None
    assert "2026-04-07" in result["reason"]


def test_fill_feasibility_rejects_nonfinite_order_and_uses_required_manual_quote() -> None:
    with pytest.raises(ValueError, match="order_value_eur must be a finite number"):
        fill_feasibility(
            float("nan"),
            day_volume_shares=500.0,
            price_eur=100.0,
            adv_eur=50_000.0,
            participation_rate=0.1,
        )

    result = fill_feasibility(
        1_000.0,
        day_volume_shares=500.0,
        price_eur=None,
        adv_eur=50_000.0,
        participation_rate=0.1,
        manual_quote_required=True,
        manual_quote_eur=100.0,
    )
    assert result.status == "full_fill"
    assert result.fillable_eur == 1_000.0


def test_blocked_risk_profile_projection_rejects_candidate_with_ready_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = SimpleNamespace(
        what_if_scenario=None,
        constraint_results=(SimpleNamespace(constraint_id="ready-limit", status="ready", blocking=False),),
        constraint_analysis=object(),
        constraint_snapshot=object(),
    )
    monkeypatch.setattr(
        top_n_selection,
        "project_risk_profile",
        lambda *_args: SimpleNamespace(scenario={"status": "blocked", "constraints": ()}),
    )

    reasons = _constraint_reasons(candidate, None, object())

    assert reasons == ("risk_profile_after_trade_constraint_blocked",)


def test_daily_investment_pnl_is_unavailable_across_missing_session() -> None:
    dates = pd.DatetimeIndex(["2026-04-06", "2026-04-08"])
    snapshots = _series_snapshots(dates, [1_000.0, 1_500.0])

    series = build_portfolio_performance_series(
        snapshots,
        metric="investment_pnl",
        date_range="inception",
        aggregation="day",
    )
    wednesday = next(point for point in series.points if point.period_end.isoformat() == "2026-04-08")

    assert wednesday.value is None
    assert "2026-04-07" in str(wednesday.reason)


def test_realised_fill_impact_requires_positive_finite_prices() -> None:
    estimate = estimate_execution_cost(load_config(), "VWCE", 1_000.0)

    for reference, fill in (
        (100.0, float("nan")),
        (100.0, float("inf")),
        (100.0, 0.0),
        (100.0, -1.0),
        (float("nan"), 100.0),
        (0.0, 100.0),
        (-1.0, 100.0),
    ):
        result = compare_realised_fill(estimate, reference_price=reference, fill_price=fill)
        assert result["realised_price_impact_bps"] is None
