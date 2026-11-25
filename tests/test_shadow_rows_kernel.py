"""Shadow rank-validation rows: the as-traded kernel against the Python close_on path, and the per-revision cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import build_stock_evidence
from etf_cockpit.analysis.stock_universe import as_traded_kernel_ready, as_traded_prefixes, market_inputs
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data.stock_fundamentals import load_stock_config
from tests.test_decision_rank_validation import _shadow_periods


def _bars(n: int = 160, **changes) -> pd.DataFrame:
    days = pd.bdate_range("2022-01-03", periods=n)
    frame = pd.DataFrame({
        "date": days, "close": 50.0 + np.arange(n) * 0.37, "currency": "USD", "dividends": 0.0,
        "stock_splits": 0.0, "actions_evidenced": np.full(n, True, dtype=object),  # object: a test row may hold None
    })
    for column, values in changes.items():
        for row, value in values.items():
            frame.loc[row, column] = value
    return frame


def _month_end_rows(frame: pd.DataFrame) -> list[int]:
    return list(frame.groupby(frame["date"].dt.to_period("M")).tail(1).index)


ENDS = _month_end_rows(_bars())
CASES = {  # split ratios include a reverse split; row labels are positions
    "plain": _bars(),
    "split_on_month_end": _bars(stock_splits={ENDS[1]: 4.0, ENDS[3]: 0.1, 70: 3.0}),
    "unevidenced": _bars(stock_splits={40: 2.0, 100: 5.0}, actions_evidenced={60: False, 159: None}),
    "invalid_split_late": _bars(stock_splits={30: 2.0, 120: -1.0}),
    "nan_split": _bars(stock_splits={90: np.nan}),
    "missing_closes": _bars(close={ENDS[0]: np.nan, ENDS[2]: np.nan, ENDS[2] - 1: np.nan, 50: 0.0, 51: -2.0, 159: np.nan}),
    "overflow": _bars(stock_splits={100: 1e300, 110: 1e300}),
    "short": _bars(3),
    "one_bar": _bars(1, stock_splits={0: 2.0}),
}


def _versions(frame: pd.DataFrame) -> list[tuple[int, datetime]]:
    """Prefix cuts and decision times: before the first bar, inside months, on month starts, and stamps whose day rule
    knows fewer bars than the prefix (bars stamped before their next midnight)."""

    out = []
    for end in sorted({0, 1, 2, len(frame) // 3, len(frame) // 2, len(frame) - 1, len(frame)}):
        if not 0 <= end <= len(frame):
            continue
        last = frame["date"].iloc[end - 1] if end else frame["date"].iloc[0]
        for when in (last + timedelta(days=1, hours=1), last + timedelta(hours=20), last + timedelta(days=40), pd.Timestamp("2022-01-01")):
            out.append((end, when.to_pydatetime().replace(tzinfo=timezone.utc)))
    return out


@pytest.mark.parametrize("name", sorted(CASES))
def test_kernel_matches_the_python_close_on_path(name) -> None:
    frame, config = CASES[name], load_stock_config()
    assert as_traded_kernel_ready(frame)
    versions = _versions(frame)
    for (end, when), prepared in zip(versions, as_traded_prefixes(frame, versions), strict=True):
        bars = frame.iloc[:end]
        want = market_inputs(bars, None, "USD", when, pd.DataFrame(), config)
        got = market_inputs(bars, None, "USD", when, pd.DataFrame(), config, prepared)
        assert got == want, (name, end, when)
        assert (prepared is None) == (want.price_date is None), (name, end, when)


def test_kernel_reads_stated_split_values() -> None:
    frame = CASES["split_on_month_end"]
    (price, reason), series = as_traded_prefixes(frame, [(len(frame), datetime(2022, 9, 1, tzinfo=timezone.utc))])[0]
    assert reason is None and price == frame["close"].iloc[-1]
    values = dict(series)
    days = frame["date"].dt.date
    assert values[days[ENDS[0]]] == frame["close"][ENDS[0]] * (4.0 * 0.1 * 3.0)  # every later split, left to right
    assert values[days[ENDS[1]]] == frame["close"][ENDS[1]] * (0.1 * 3.0)  # its own split is already in its price


@pytest.mark.parametrize("change", ["duplicate_day", "factor_column", "etf_id", "no_evidence", "object_close", "tz_dates", "nat"])
def test_frames_the_kernel_cannot_prove_stay_on_the_python_path(change) -> None:
    frame = _bars(20)
    if change == "duplicate_day":
        frame.loc[5, "date"] = frame.loc[4, "date"]
    elif change == "factor_column":
        frame["as_traded_split_factor"] = 1.0
    elif change == "etf_id":
        frame["etf_id"] = "X"
    elif change == "no_evidence":
        frame = frame.drop(columns="actions_evidenced")
    elif change == "object_close":
        frame["close"] = frame["close"].astype(object)
    elif change == "tz_dates":
        frame["date"] = frame["date"].dt.tz_localize("UTC")
    else:
        frame.loc[0, "date"] = pd.NaT
    assert as_traded_kernel_ready(_bars(20)) and not as_traded_kernel_ready(frame)


def _store_root(tmp_path):
    root = tmp_path / "root"
    (root / "data" / "clean").mkdir(parents=True)
    _shadow_periods().to_parquet(root / "data" / "clean" / "stock_fundamentals.parquet")
    return root


def _shadow_prices() -> pd.DataFrame:
    days = pd.bdate_range("2021-06-01", "2024-12-31")
    frames = []
    for i in range(6):
        frame = pd.DataFrame({
            "instrument_id": f"I{i}", "date": days.strftime("%Y-%m-%d"), "known_at": (days + pd.Timedelta(hours=22)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "currency": "EUR", "close": 20.0 + i + np.arange(len(days)) * 0.01, "adjusted_close": 20.0 + i,
            "dividends": 0.0, "stock_splits": 0.0, "actions_evidenced": True,
        })
        frame.loc[300 + 40 * i, "stock_splits"] = 2.0 + i
        frames.append(frame)
    frames[1].loc[500, "actions_evidenced"] = False  # unevidenced split history from then on
    frames[2].loc[200, "known_at"] = "2024-06-01T00:00:00Z"  # a late stamp: the known bars are no prefix (Python path)
    frames[3].loc[100:130, "close"] = np.nan
    return pd.concat(frames, ignore_index=True)


def _oracle_shadow_rows(service, root, prices) -> pd.DataFrame:
    """The per-version loop of main f3edc23b (Python close_on path for every version): the parity oracle."""

    frame = store.read_periods(root)
    config = store.load_stock_config(root)
    chain = list((config.get("sources", {}) or {}).get("chain", ["sec_edgar", "esef", "yfinance"]))
    snapshots, fx = store.read_snapshots(root), store.read_fx(root)
    dates = pd.to_datetime(prices["date"], errors="coerce")
    traded = prices.assign(date=dates.dt.normalize()).dropna(subset=["date"])
    traded["_known"] = pd.to_datetime(traded["known_at"], errors="coerce", utc=True)
    rows = []
    for instrument in sorted(frame["instrument_id"].astype(str).unique()):
        periods = store.periods_for(instrument, frame[frame["instrument_id"].astype(str) == instrument], chain)
        history = traded[traded["instrument_id"].astype(str) == instrument].sort_values("date")
        for known in sorted({period.known_at for period in periods}):
            visible = sm.known_periods(periods, known)
            if not visible:
                continue
            bars = history.loc[history["_known"] <= known].drop(columns="_known")
            market = market_inputs(bars, store.latest_snapshot(instrument, snapshots, known), visible[-1].currency, known, fx, config)
            metrics = build_stock_evidence(instrument, periods, known, market, None, config).metrics
            row = {"instrument_id": instrument, "effective_at": visible[-1].period_end.isoformat(), "known_at": known.isoformat()}
            for key, column, sign in service._SHADOW_METRICS:
                metric = metrics.get(key)
                row[column] = sign * float(metric.value) if metric is not None and metric.available else float("nan")
            latest = sm.latest_balance(visible, ["total_assets"])
            prior = sm.opening_balance(visible, latest.period_end, ["total_assets"]) if latest is not None else None
            row["asset_growth_neg"] = (
                -(latest.values["total_assets"] / prior.values["total_assets"] - 1.0)
                if prior is not None and prior.currency == latest.currency and prior.values["total_assets"] > 0
                else float("nan")
            )
            rows.append(row)
    return pd.DataFrame(rows, columns=service._SHADOW_COLUMNS)


def test_shadow_rows_equal_the_per_version_python_loop(tmp_path) -> None:
    import etf_cockpit.application.rank_validation_service as service

    root, prices = _store_root(tmp_path), _shadow_prices()
    got = service._shadow_rows(root, prices)
    want = _oracle_shadow_rows(service, root, prices)
    assert got["shareholder_yield"].notna().any()  # the price-dependent challenger is exercised
    pd.testing.assert_frame_equal(got, want, check_exact=True)


def _cached(root) -> list:
    return sorted((root / "data" / "derived" / "cache" / "rank_validation_shadow").glob("*.parquet"))


def test_shadow_cache_hit_reads_the_stored_rows_and_bypass_ignores_them(tmp_path) -> None:
    import etf_cockpit.application.rank_validation_service as service

    root, prices = _store_root(tmp_path), _shadow_prices()
    first = service._shadow_rows(root, prices)
    (path,) = _cached(root)
    pd.testing.assert_frame_equal(service._shadow_rows(root, prices), first, check_exact=True)  # a hit is the same frame
    first.assign(piotroski_f=-1.0).to_parquet(path)  # a marked entry shows which path answered
    assert (service._shadow_rows(root, prices)["piotroski_f"] == -1.0).all()
    pd.testing.assert_frame_equal(service._shadow_rows(root, prices, cache=False), first, check_exact=True)
    assert _cached(root) == [path]


@pytest.mark.parametrize("change", ["periods", "snapshots", "fx", "prices", "reconstructed", "config", "code"])
def test_a_change_of_any_shadow_cache_input_misses(tmp_path, monkeypatch, change) -> None:
    import shutil

    import etf_cockpit.application.rank_validation_service as service

    root, prices = _store_root(tmp_path), _shadow_prices()
    service._shadow_rows(root, prices)
    reconstructed, clean = False, root / "data" / "clean"
    if change == "periods":
        periods = _shadow_periods()
        periods.loc[0, "revenue"] += 1.0
        periods.to_parquet(clean / "stock_fundamentals.parquet")
    elif change == "snapshots":
        pd.DataFrame([{"instrument_id": "I0", "known_at": "2023-01-01T00:00:00Z", "status": "ok", "quote_currency": "EUR"}]).reindex(
            columns=store.SNAPSHOT_COLUMNS).to_parquet(clean / "stock_snapshots.parquet")
    elif change == "fx":
        pd.DataFrame([{"pair": "USDEUR", "date": "2023-01-02", "rate": 0.9, "known_at": "2023-01-02T18:00:00Z"}]).to_parquet(clean / "stock_fx.parquet")
    elif change == "prices":
        prices.loc[prices.index[-1], "close"] += 0.5
    elif change == "reconstructed":
        reconstructed = True
    elif change == "config":
        (root / "configs").mkdir()
        shutil.copy(store.config_path(None), root / "configs" / store.CONFIG_NAME)
        with (root / "configs" / store.CONFIG_NAME).open("a", encoding="utf-8") as handle:
            handle.write("\nshadow_cache_probe: 1\n")
    else:
        monkeypatch.setattr(service, "_code_version", lambda: "another build")
    service._shadow_rows(root, prices, reconstructed=reconstructed)
    assert len(_cached(root)) == 2
