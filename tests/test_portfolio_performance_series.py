from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.app.pages import portfolio
from etf_cockpit.application import ui_facade
from etf_cockpit.application.portfolio_valuation import save_portfolio_valuation_history
from etf_cockpit.portfolio.performance_series import (
    build_portfolio_performance_series,
    performance_series_frame,
    performance_series_to_csv,
)
from etf_cockpit.portfolio.valuation import SNAPSHOT_COLUMNS, link_time_weighted_return


def _snapshots(
    dates: pd.DatetimeIndex | list[pd.Timestamp],
    values: list[float],
    flows: list[float] | None = None,
) -> pd.DataFrame:
    dated = pd.DatetimeIndex(dates)
    external_flows = flows or [0.0] * len(dated)
    rows: list[dict[str, object]] = []
    invested_capital: float | None = None
    for index, observed in enumerate(dated):
        value = values[index]
        flow = external_flows[index]
        pnl = float("nan") if index == 0 else value - values[index - 1] - flow
        period_return = float("nan") if index == 0 else (value - flow) / values[index - 1] - 1.0
        invested_capital = value - flow if index == 0 else float(invested_capital + flow)
        rows.append(
            {
                "date": observed,
                "cash_value": 0.0,
                "securities_value": value,
                "total_value": value,
                "external_flow": flow,
                "invested_capital": invested_capital,
                "dividends": 0.0,
                "coupons": 0.0,
                "fees": 0.0,
                "taxes": 0.0,
                "investment_pnl": pnl,
                "period_return": period_return,
                "valuation_status": "available",
                "flow_status": "available",
                "availability_evidence": "timestamped",
                "missing_reasons": "",
                "execution_allowed": False,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SNAPSHOT_COLUMNS)


def _walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _by_key(control, key: str):
    return next(item for item in _walk(control) if getattr(item, "key", None) == key)


def test_quarter_and_year_bars_reconcile_to_canonical_twr_and_pnl() -> None:
    dates = pd.bdate_range("2024-01-02", "2025-12-31")
    snapshots = _snapshots(dates, [100.0 + index * 0.1 for index in range(len(dates))])

    for aggregation in ("quarter", "year"):
        twr = build_portfolio_performance_series(snapshots, metric="twr_return", aggregation=aggregation)
        pnl = build_portfolio_performance_series(snapshots, metric="investment_pnl", aggregation=aggregation)
        assert twr.status == "available"
        assert pnl.status == "available"
        for twr_point, pnl_point in zip(twr.points, pnl.points, strict=True):
            period = snapshots.loc[
                snapshots["date"].ge(pd.Timestamp(twr_point.period_start))
                & snapshots["date"].le(pd.Timestamp(twr_point.period_end))
            ]
            canonical = link_time_weighted_return(
                period,
                start=period.iloc[0]["date"],
                end=period.iloc[-1]["date"],
            )
            assert canonical["status"] == "available"
            assert twr_point.value == pytest.approx(canonical["value"])
            assert pnl_point.value == pytest.approx(period["investment_pnl"].iloc[1:].sum())


def test_external_flows_stay_separate_from_negative_investment_pnl() -> None:
    dates = pd.bdate_range("2026-01-05", periods=5)
    snapshots = _snapshots(dates, [100.0, 143.0, 122.0, 102.0, 98.0], [0.0, 50.0, -10.0, -15.0, 0.0])
    flows = build_portfolio_performance_series(snapshots, metric="net_contributions", aggregation="quarter")
    pnl = build_portfolio_performance_series(snapshots, metric="investment_pnl", aggregation="quarter")
    returns = build_portfolio_performance_series(snapshots, metric="twr_return", aggregation="quarter")
    daily_flows = build_portfolio_performance_series(snapshots, metric="net_contributions", aggregation="day")

    assert flows.points[0].value == pytest.approx(25.0)
    assert pnl.points[0].value == pytest.approx(-27.0)
    assert returns.points[0].value < 0
    assert snapshots.iloc[-1]["total_value"] - snapshots.iloc[0]["total_value"] == pytest.approx(
        flows.points[0].value + pnl.points[0].value
    )
    assert [point.value for point in daily_flows.points] == [0.0, 50.0, -10.0, -15.0, 0.0]


def test_missing_valuation_is_partial_without_interpolation_and_empty_is_unavailable() -> None:
    dates = pd.bdate_range("2026-01-05", periods=5)
    snapshots = _snapshots(dates, [100.0, 101.0, 102.0, 103.0, 104.0]).drop(index=2).reset_index(drop=True)
    daily = build_portfolio_performance_series(snapshots, metric="portfolio_value", aggregation="day")
    missing = next(point for point in daily.points if point.period_start == dates[2].date())
    empty = build_portfolio_performance_series(pd.DataFrame(columns=SNAPSHOT_COLUMNS))

    assert daily.status == "partial"
    assert missing.value is None
    assert missing.partial is True
    assert "Missing daily valuations" in (missing.reason or "")
    assert empty.status == "unavailable"
    assert empty.reason


def test_view_changes_leave_saved_snapshot_bytes_unchanged(tmp_path) -> None:
    snapshots = _snapshots(pd.bdate_range("2026-02-02", periods=8), [100.0 + index for index in range(8)])
    path = save_portfolio_valuation_history(snapshots, storage_root=tmp_path)
    before = path.read_bytes()
    saved = pd.read_parquet(path)

    for aggregation in ("day", "week", "month", "quarter", "year"):
        build_portfolio_performance_series(saved, metric="portfolio_value", aggregation=aggregation)
    for date_range in ("inception", "YTD", "1M", "3M", "6M", "1Y", "3Y", "5Y"):
        build_portfolio_performance_series(saved, metric="investment_pnl", date_range=date_range, aggregation="week")
    build_portfolio_performance_series(
        saved,
        metric="twr_index",
        date_range="custom",
        aggregation="quarter",
        custom_start="2026-02-03",
        custom_end="2026-02-11",
    )

    assert path.read_bytes() == before


def test_default_eur_and_missing_non_eur_fx_are_explicitly_unavailable() -> None:
    snapshots = _snapshots(pd.bdate_range("2026-03-02", periods=3), [100.0, 101.0, 102.0])
    eur = build_portfolio_performance_series(snapshots, metric="portfolio_value")
    usd = build_portfolio_performance_series(snapshots, metric="portfolio_value", currency="USD", fx_rates=pd.DataFrame())

    assert eur.currency == "EUR"
    assert eur.status == "available"
    assert usd.status == "unavailable"
    assert usd.points
    assert all(point.value is None and point.reason for point in usd.points)


def test_csv_matches_series_and_facade_loader_feeds_portfolio_chart_block(monkeypatch) -> None:
    snapshots = _snapshots(pd.bdate_range("2026-04-06", periods=3), [100.0, 101.0, 102.0])
    monkeypatch.setattr(ui_facade, "load_portfolio_valuation_history", lambda: {"snapshots": snapshots})
    monkeypatch.setattr(ui_facade, "load_fx_rates", lambda: pd.DataFrame())
    series = ui_facade.load_portfolio_performance_series(metric="portfolio_value", aggregation="day")
    exported = pd.read_csv(StringIO(performance_series_to_csv(series)))
    expected = performance_series_frame(series)

    assert exported["value"].tolist() == expected["value"].tolist() == [point.value for point in series.points]

    loader_calls: list[dict[str, object]] = []

    def page_loader(**kwargs):
        loader_calls.append(kwargs)
        return ui_facade.load_portfolio_performance_series(**kwargs)

    captured_exports: list[pd.DataFrame] = []

    def export_stub(_table_id, frame, destination):
        captured_exports.append(frame.copy())
        return SimpleNamespace(ok=True, destination=destination, rows=len(frame), error=None)

    monkeypatch.setattr(portfolio, "load_portfolio_performance_series", page_loader)
    monkeypatch.setattr(portfolio, "export_table", export_stub)
    block = portfolio._portfolio_performance_block(None)
    _by_key(block, "portfolio.performance.download").on_click(None)
    chart_host = _by_key(block, "portfolio.performance.chart")

    assert loader_calls[0]["metric"] == "twr_index"
    assert chart_host.controls
    assert len(captured_exports) == 1
    assert captured_exports[0]["value"].tolist() == pd.read_csv(
        StringIO(performance_series_to_csv(ui_facade.load_portfolio_performance_series(metric="twr_index")))
    )["value"].tolist()
