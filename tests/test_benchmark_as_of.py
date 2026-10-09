from datetime import date

import pandas as pd

from etf_cockpit.features.feature_pipeline import _benchmark_as_of


def test_uses_latest_earlier_benchmark_close_when_calendars_differ():
    bench = pd.Series([1.0, 2.0], index=[date(2026, 10, 6), date(2026, 10, 7)])
    out = _benchmark_as_of(bench, pd.Index([date(2026, 10, 7), date(2026, 10, 8)]))
    assert out.tolist() == [2.0, 2.0]


def test_never_uses_a_later_close_and_stops_after_the_gap():
    bench = pd.Series([1.0, 5.0], index=[date(2026, 10, 1), date(2026, 10, 20)])
    out = _benchmark_as_of(bench, pd.Index([date(2026, 9, 30), date(2026, 10, 3), date(2026, 10, 10)]))
    assert pd.isna(out.iloc[0])          # before the first benchmark close
    assert out.iloc[1] == 1.0            # within the gap
    assert pd.isna(out.iloc[2])          # too stale; the later 5.0 is never used
