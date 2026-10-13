import numpy as np
import pandas as pd

from etf_cockpit.backtest.engine import MIN_INSTRUMENT_HISTORY_SESSIONS, _exclude_late_listed_short_history


def _pivot() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=400)
    frame = pd.DataFrame({"OLD": np.linspace(100, 120, 400), "NEW": np.nan, "DELISTED": np.nan, "MID": np.nan}, index=dates)
    frame.loc[dates[-5:], "NEW"] = 10.0
    frame.loc[dates[:50], "DELISTED"] = 5.0
    frame.loc[dates[100:], "MID"] = 7.0
    return frame


def test_late_listing_with_short_history_is_excluded_and_reported() -> None:
    kept, excluded = _exclude_late_listed_short_history(_pivot(), ["OLD", "NEW", "MID"])
    assert kept == ["OLD", "MID"]
    assert excluded == ("NEW",)


def test_early_starting_short_series_is_kept_so_complete_rule_fails_closed() -> None:
    kept, excluded = _exclude_late_listed_short_history(_pivot(), ["OLD", "DELISTED"])
    assert kept == ["OLD", "DELISTED"]
    assert excluded == ()


def test_never_excludes_every_instrument() -> None:
    pivot = _pivot().iloc[-MIN_INSTRUMENT_HISTORY_SESSIONS + 10 :]
    kept, excluded = _exclude_late_listed_short_history(pivot, ["NEW"])
    assert kept == ["NEW"] and excluded == ()
