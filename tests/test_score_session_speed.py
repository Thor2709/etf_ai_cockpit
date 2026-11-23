"""Score-session speed changes keep the old results (each oracle is the replaced expression)."""

from __future__ import annotations

from datetime import date, datetime, timezone
import pickle

import numpy as np
import pandas as pd

from etf_cockpit.core.config import ETFConfig, load_config
from etf_cockpit.data.universe_store import support_decision
from etf_cockpit.features.crowding import build_correlation_clusters, correlation_matrix
from etf_cockpit.models.baseline_models import observed_history_is_sparse
from etf_cockpit.signals.simple_scores import _parse_date


def test_universe_index_follows_every_edit_of_the_universe() -> None:
    universe = load_config().universe.model_copy(deep=True)

    def check() -> None:  # the replaced expressions, evaluated on the current state
        enabled = [
            etf.id for etf in universe.etfs
            if etf.enabled and support_decision(etf.instrument_type, etf.data_policy, etf.leveraged, etf.inverse).score_eligible
        ]
        assert universe.enabled_ids == enabled
        assert universe.by_id() == {etf.id: etf for etf in universe.etfs}
        assert all(universe.find(etf.id) is etf for etf in universe.etfs)

    check()
    universe.by_id().pop(universe.etfs[0].id)  # edits a copy, not the index
    check()
    universe.etfs[0].enabled = not universe.etfs[0].enabled  # item edit
    check()
    universe.etfs.append(ETFConfig(id="ZZNEW", name="New", ticker="ZZNEW", role="watchlist"))  # list edit
    check()
    universe.etfs[1] = universe.etfs[1].model_copy(update={"enabled": not universe.etfs[1].enabled})  # item replaced
    check()
    universe.etfs.reverse()  # order
    check()
    universe.etfs = universe.etfs[:3]  # list replaced
    check()
    assert "_universe_index" not in universe.model_dump()
    assert universe == universe.model_copy(deep=True) == pickle.loads(pickle.dumps(universe))


def _long_prices() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2025-01-01", periods=260)
    base = np.cumsum(rng.normal(0, 0.01, len(days)))
    columns = {
        "A": base + rng.normal(0, 0.001, len(days)),
        "B": base + rng.normal(0, 0.001, len(days)),
        "C": np.cumsum(rng.normal(0, 0.01, len(days))),
        "D": np.cumsum(rng.normal(0, 0.01, len(days))),
    }
    wide = pd.DataFrame({key: 100 * np.exp(value) for key, value in columns.items()}, index=days)
    wide = wide.mask(rng.random(wide.shape) < 0.05)
    wide.loc[days[60]:, "D"] = np.nan  # D has no row in the last window
    long = wide.rename_axis("date").reset_index().melt(id_vars="date", var_name="etf_id", value_name="adjusted_close")
    return long.dropna().assign(date=lambda frame: frame["date"].dt.date)


def test_cluster_window_and_shared_matrix_give_the_full_history_report() -> None:
    prices = _long_prices()
    wide = prices.pivot_table(index="date", columns="etf_id", values="adjusted_close", aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    as_of = date(2025, 11, 3)
    weights = {"A": 0.5, "C": 0.5}
    expected = build_correlation_clusters(wide, {"A": "x"}, weights=weights, as_of=as_of)  # wide frame: full-history pivot
    assert expected.status == "available" and "D" in {row.instrument_id for row in expected.rows}
    assert build_correlation_clusters(prices, {"A": "x"}, weights=weights, as_of=as_of) == expected
    matrix = correlation_matrix(prices, as_of=as_of)
    assert build_correlation_clusters(prices, {"A": "x"}, weights=weights, matrix=matrix) == expected
    assert build_correlation_clusters(prices, matrix=correlation_matrix(prices.iloc[:30])) == build_correlation_clusters(prices.iloc[:30])


def test_parse_date_fast_path_equals_pandas() -> None:
    def oracle(value: object) -> date | None:
        try:
            parsed = pd.to_datetime(value, errors="coerce")
        except (TypeError, ValueError, OverflowError):
            return None
        return None if pd.isna(parsed) else parsed.date()

    values = [
        "2025-06-02", "2024-02-29", "2025-02-29", "2025-13-01", "1677-01-01", "1678-01-01", "2261-12-31", "2262-12-31",
        "2025-06-02T10:00:00+02:00", " 2025-06-02", "20250602", "2025-6-2", "", "n/a", None, float("nan"),
        date(2025, 6, 2), date(1500, 1, 1), datetime(2025, 6, 2, 23, 30, tzinfo=timezone.utc), pd.Timestamp("2025-06-02"),
    ]
    assert [_parse_date(value) for value in values] == [oracle(value) for value in values]


def test_sparse_history_weekday_count_equals_bdate_range() -> None:
    def oracle(series: pd.Series) -> bool:
        days = pd.DatetimeIndex(series.dropna().index)
        if len(days) < 2:
            return False
        days = (days.tz_convert("UTC").tz_localize(None) if days.tz is not None else days).normalize()
        weekdays = len(pd.bdate_range(days[0], days[-1]))
        return bool(int(pd.Series(days).diff().dt.days.max()) > 7 or (weekdays > 1 and len(days) / weekdays < 0.9))

    full = pd.Series(1.0, index=pd.bdate_range("2025-01-06", periods=40))
    cases = [
        full,
        full.iloc[::2],
        full.drop(full.index[[3, 9, 15, 21, 27]]),
        full.iloc[[0, 1]],
        full.iloc[::-1],  # reversed: no weekday range
        full.tz_localize("Europe/Berlin"),
        pd.Series(1.0, index=pd.to_datetime(["2025-01-04", "2025-01-05", "2025-01-06"])),  # weekend start
    ]
    assert [observed_history_is_sparse(case) for case in cases] == [oracle(case) for case in cases]
