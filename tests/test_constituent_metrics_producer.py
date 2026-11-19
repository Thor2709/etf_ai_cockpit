"""ISSUE-0211: the statement import writes the per-constituent metric vintages the look-through roll-up reads."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.data import fundamentals as fundamentals_module
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_sources as src
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.data.fundamentals import load_constituent_metrics

UTC = timezone.utc
CONFIG = store.load_stock_config()
EARLY = "2025-03-01T00:00:00+00:00"
LATE = "2026-03-01T00:00:00+00:00"
ISINS = {"AAA": "US0378331005", "BBB": "US5949181045", "CCC": "US0231351067"}


def _statement(known: str, year: int, revenue: float, ebit: float | None) -> dict:
    row = {
        "period_end": f"{year}-12-31", "period_type": "FY", "fiscal_year": year, "currency": "EUR",
        "source": "yfinance", "source_ref": "t", "known_at": known, "revenue": revenue,
    }
    if ebit is not None:
        row["ebit"] = ebit
    return row


def _fetch(symbol: str, _cfg: dict, now: datetime) -> src.FetchResult:
    rows = {
        "AAA": [_statement(EARLY, 2024, 100.0, 10.0), _statement(LATE, 2025, 120.0, 24.0)],
        "CCC": [_statement(EARLY, 2024, 100.0, None)],  # reports revenue but no EBIT: no metric is derivable
    }.get(symbol)
    if rows is None:
        return src.FetchResult("yfinance", status="not_found", reason="no profile", snapshot={"known_at": EARLY, "status": "not_found"})
    return src.FetchResult("yfinance", rows=rows, snapshot={"known_at": EARLY, "quote_currency": "EUR", "financial_currency": "EUR", "status": "ok"})


def _run_import(root, prices: pd.DataFrame | None = None) -> None:
    (root / "data" / "clean").mkdir(parents=True)
    if prices is not None:
        (root / "data" / "validated" / "prices").mkdir(parents=True)
        prices.to_parquet(root / "data" / "validated" / "prices" / "prices_daily.parquet")
    store.refresh_stock_fundamentals(
        [store.StockTarget(name, name, name) for name in ISINS],
        root=root, now=datetime(2026, 3, 2, tzinfo=UTC), config=CONFIG, environ={}, yfinance_fetch=_fetch,
        fx_fetch=lambda _base, _quote: [],
    )


def _prices(last_available: str = "2026-02-28T00:00:00+00:00") -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-06-30", "2026-02-27"])
    return pd.DataFrame({
        "etf_id": "AAA", "date": dates, "close": 20.0, "currency": "EUR",
        "stock_splits": 0.0, "dividends": [0.0, 0.5, 0.5], "actions_evidenced": True,
        "available_at": ["2025-01-03T00:00:00+00:00", "2025-07-01T00:00:00+00:00", last_available],
    })


def _holdings() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "security": name, "isin": ISINS[name], "weight": weight, "issuer": name, "company": name, "currency": "EUR",
            "exposure_type": "security", "instrument_id": "TESTETF", "as_of": "2026-01-31", "source": "issuer",
            "source_id": "issuer:holdings-v1", "known_at": "2026-02-01T12:00:00Z", "revision": "r1",
        }
        for name, weight in (("AAA", 0.5), ("BBB", 0.3), ("CCC", 0.2))
    ])


def _roll_up(metrics: pd.DataFrame, decision_time: str):
    return calculate_look_through(
        _holdings(), instrument_id="TESTETF", decision_time=decision_time, constituent_fundamentals=metrics,
        minimum_aggregate_coverage=0.4,
    )


def test_statement_import_from_an_empty_store_writes_one_vintage_per_known_at(tmp_path) -> None:
    assert load_constituent_metrics(tmp_path / "data" / "clean" / "constituent_metrics.parquet").empty
    _run_import(tmp_path, _prices())
    frame = load_constituent_metrics(tmp_path / "data" / "clean" / "constituent_metrics.parquet")
    aaa = frame[frame["instrument_id"] == "AAA"].sort_values("known_at")
    assert list(aaa["known_at"]) == [EARLY, LATE]
    assert list(aaa["as_of_date"]) == ["2024-12-31", "2025-12-31"]
    assert list(aaa["ebit_margin"]) == pytest.approx([0.10, 0.20])
    assert all(aaa["source_id"].astype(str).str.strip() != "")
    assert pd.isna(aaa.iloc[0]["dividend_yield"]) and aaa.iloc[1]["dividend_yield"] == pytest.approx(1.0 / 20.0)


def test_roll_up_reads_only_the_vintages_known_at_the_cut_off(tmp_path) -> None:
    _run_import(tmp_path)
    frame = load_constituent_metrics(tmp_path / "data" / "clean" / "constituent_metrics.parquet")
    assert _roll_up(frame, "2026-02-15T00:00:00Z").calculated_metrics["ebit_margin"]["value"] == pytest.approx(0.10)
    assert _roll_up(frame, "2026-03-15T00:00:00Z").calculated_metrics["ebit_margin"]["value"] == pytest.approx(0.20)


def test_constituents_without_metrics_lower_coverage_and_are_never_zero_filled(tmp_path) -> None:
    _run_import(tmp_path)
    frame = load_constituent_metrics(tmp_path / "data" / "clean" / "constituent_metrics.parquet")
    assert set(frame["instrument_id"]) == {"AAA", "CCC"}  # BBB was never fetched: no row at all
    assert frame[frame["instrument_id"] == "CCC"]["ebit_margin"].isna().all()  # CCC has no EBIT: NaN, not a zero
    summary = _roll_up(frame, "2026-03-15T00:00:00Z")
    coverage = summary.fundamental_data_coverage["ebit_margin"]
    assert coverage["covered_weight"] == pytest.approx(0.5) and coverage["coverage_fraction"] == pytest.approx(0.5)
    assert summary.calculated_metrics["ebit_margin"]["value"] == pytest.approx(0.20)  # not diluted by the 0.5 weight without metrics


def test_look_through_loader_reads_the_constituent_metric_store(tmp_path, monkeypatch) -> None:
    from etf_cockpit.application.market_views import load_etf_look_through

    _run_import(tmp_path)
    monkeypatch.setattr(fundamentals_module, "CONSTITUENT_METRICS_PATH", tmp_path / "data" / "clean" / "constituent_metrics.parquet")
    result = load_etf_look_through(
        "TESTETF", decision_time="2026-03-15T00:00:00Z", holdings_frame=_holdings(), minimum_aggregate_coverage=0.4
    )
    assert result["fundamental_data_coverage"]["ebit_margin"]["covered_weight"] == pytest.approx(0.5)


def test_a_price_available_after_the_vintage_does_not_enter_it(tmp_path) -> None:
    _run_import(tmp_path, _prices(last_available="2026-03-02T00:00:00+00:00"))  # the Feb 27 bar was backfilled after LATE
    frame = load_constituent_metrics(tmp_path / "data" / "clean" / "constituent_metrics.parquet")
    late = frame[(frame["instrument_id"] == "AAA") & (frame["known_at"] == LATE)].iloc[0]
    assert pd.isna(late["dividend_yield"])


def test_a_newer_unavailable_vintage_is_not_replaced_by_an_older_finite_value(tmp_path) -> None:
    path = tmp_path / "constituent_metrics.parquet"
    base = {"instrument_id": "AAA", "as_of_date": "2025-12-31", "source_id": "s"}
    rows = [
        {**base, "known_at": EARLY, "ebit_margin": 0.10, "ebit_margin_as_of": "2025-12-31"},
        {**base, "known_at": LATE, "ebit_margin": float("nan"), "ebit_margin_as_of": "2025-12-31"},  # revised: no longer derivable
    ]
    fundamentals_module.write_constituent_metrics(rows, ["AAA"], path)
    summary = _roll_up(load_constituent_metrics(path), "2026-03-15T00:00:00Z")
    assert summary.fundamental_data_coverage["ebit_margin"]["covered_weight"] == 0.0
    assert _roll_up(load_constituent_metrics(path), "2026-02-15T00:00:00Z").calculated_metrics["ebit_margin"]["value"] == pytest.approx(0.10)


def test_a_metric_dated_after_the_analysis_date_is_not_used(tmp_path) -> None:
    path = tmp_path / "constituent_metrics.parquet"
    base = {"instrument_id": "AAA", "as_of_date": "2025-12-31", "source_id": "s"}
    rows = [
        {**base, "known_at": EARLY, "ebit_margin": 0.10, "ebit_margin_as_of": "2025-12-31"},
        {**base, "known_at": "2026-02-10T00:00:00+00:00", "ebit_margin": 0.20, "ebit_margin_as_of": "2026-02-27"},
    ]
    fundamentals_module.write_constituent_metrics(rows, ["AAA"], path)
    summary = calculate_look_through(
        _holdings(), instrument_id="TESTETF", decision_time="2026-03-15T00:00:00Z", analysis_date="2026-02-15",
        constituent_fundamentals=load_constituent_metrics(path), minimum_aggregate_coverage=0.4,
    )
    assert summary.calculated_metrics["ebit_margin"]["value"] == pytest.approx(0.10)


def test_the_metric_store_write_holds_a_cross_process_guard(tmp_path, monkeypatch) -> None:
    path = tmp_path / "constituent_metrics.parquet"
    seen = []

    def probe(target, *args, **kwargs):
        with pytest.raises(TimeoutError):  # a second holder cannot enter while the first merge is writing
            with persistent_file_guard(path.with_name(path.name + ".lock"), timeout_seconds=0.0):
                pass
        seen.append(target)

    monkeypatch.setattr(fundamentals_module, "atomic_write_bytes", probe)
    fundamentals_module.write_constituent_metrics([{"instrument_id": "AAA", "known_at": EARLY}], ["AAA"], path)
    assert seen == [path]


def test_an_unreadable_input_store_leaves_the_metric_store_unchanged(tmp_path) -> None:
    _run_import(tmp_path, _prices())
    path = tmp_path / "data" / "clean" / "constituent_metrics.parquet"
    before = path.read_bytes()
    (tmp_path / "data" / "validated" / "prices" / "prices_daily.parquet").write_bytes(b"not parquet")
    reason = store.produce_constituent_metrics(ISINS, root=tmp_path, config=CONFIG)
    assert reason is not None and "prices_daily.parquet" in reason
    assert path.read_bytes() == before


def test_rewriting_an_instrument_drops_a_vintage_that_is_no_longer_derivable(tmp_path) -> None:
    path = tmp_path / "constituent_metrics.parquet"
    row = {"instrument_id": "AAA", "as_of_date": "2024-12-31", "known_at": EARLY, "source_id": "s", "ebit_margin": 0.1}
    fundamentals_module.write_constituent_metrics([row, {**row, "instrument_id": "BBB"}], ["AAA", "BBB"], path)
    fundamentals_module.write_constituent_metrics([], ["AAA"], path)
    assert list(load_constituent_metrics(path)["instrument_id"]) == ["BBB"]
