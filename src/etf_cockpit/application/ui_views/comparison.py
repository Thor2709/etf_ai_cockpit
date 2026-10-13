"""Read-only view model for the Comparison page (spec 6.5, section 8).

Plain values plus an unavailable reason per element. Series use stored adjusted closes only, are aligned on the
dates both instruments share (no fill), and are cut at the last stored price date; missing is never zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from etf_cockpit.application.ui_views.stock_research import RANGE_DAYS, adjusted_close, finite, price_series

METRICS = ("Price", "Score", "Risk")


@dataclass
class HeroSeries:
    x: list[pd.Timestamp] = field(default_factory=list)
    a: list[float | None] = field(default_factory=list)
    b: list[float | None] = field(default_factory=list)
    reason: str | None = None
    end_gap: float | None = None  # last A minus last B, in the unit of the series


@dataclass
class GapSeries:
    labels: list[str] = field(default_factory=list)
    values: list[float | None] = field(default_factory=list)  # percentage points, A minus B
    reason: str | None = None


def _frame(prices: object, instrument_id: str) -> pd.DataFrame:
    return price_series(prices, instrument_id) if isinstance(prices, pd.DataFrame) else pd.DataFrame()


def _aligned(prices: object, id_a: str, id_b: str, range_key: str) -> tuple[pd.DataFrame, str | None]:
    """Adjusted closes of both instruments on the dates they share inside the range (columns a, b)."""
    frame_a, frame_b = _frame(prices, id_a), _frame(prices, id_b)
    if frame_a.empty or frame_b.empty:
        missing = id_a if frame_a.empty else id_b
        return pd.DataFrame(), f"No stored price rows for {missing}."
    a = pd.Series(adjusted_close(frame_a).to_numpy(), index=pd.DatetimeIndex(frame_a["date"]))
    b = pd.Series(adjusted_close(frame_b).to_numpy(), index=pd.DatetimeIndex(frame_b["date"]))
    both = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if both.empty:
        return both, "The two instruments share no stored price date."
    window = both[both.index >= both.index[-1] - pd.Timedelta(days=RANGE_DAYS.get(range_key, 365))]
    if len(window) < 2:
        return window, "Fewer than two shared price dates in this range."
    return window, None


def price_index(prices: object, id_a: str, id_b: str, range_key: str) -> HeroSeries:
    """Both instruments rebased to 100 on the first shared date of the range."""
    window, reason = _aligned(prices, id_a, id_b, range_key)
    if reason:
        return HeroSeries(reason=reason)
    base = window.iloc[0]
    a, b = window["a"] / base["a"] * 100.0, window["b"] / base["b"] * 100.0
    return HeroSeries(list(window.index), [finite(v) for v in a], [finite(v) for v in b], None, float(a.iloc[-1] - b.iloc[-1]))


def drawdown_index(prices: object, id_a: str, id_b: str, range_key: str) -> HeroSeries:
    """Drawdown from the running peak of the range, in percent (<= 0)."""
    window, reason = _aligned(prices, id_a, id_b, range_key)
    if reason:
        return HeroSeries(reason=reason)
    a, b = ((window[c] / window[c].cummax() - 1.0) * 100.0 for c in ("a", "b"))
    return HeroSeries(list(window.index), [finite(v) for v in a], [finite(v) for v in b], None, float(a.min() - b.min()))


def score_history(history: Mapping[str, Sequence[Mapping[str, object]]], id_a: str, id_b: str, range_key: str) -> HeroSeries:
    """Stored score history of both instruments on the run times both share; needs two shared runs."""
    def column(instrument_id: str) -> pd.Series:
        rows = history.get(instrument_id) or ()
        points = {}
        for row in rows:
            value = finite(row.get("final_combined_score_10", row.get("final_score_10")))
            stamp = pd.to_datetime(row.get("run_completed_at"), errors="coerce", utc=True)
            if value is not None and not pd.isna(stamp):
                points[stamp.tz_localize(None)] = value
        return pd.Series(points, dtype=float).sort_index()

    a, b = column(id_a), column(id_b)
    both = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna() if len(a) and len(b) else pd.DataFrame()
    if len(both) < 2:
        return HeroSeries(reason="Needs at least two stored score runs for both instruments.")
    both = both[both.index >= both.index[-1] - pd.Timedelta(days=RANGE_DAYS.get(range_key, 365))]
    if len(both) < 2:
        return HeroSeries(reason="Fewer than two stored score runs in this range.")
    return HeroSeries(list(both.index), list(both["a"]), list(both["b"]), None, float(both["a"].iloc[-1] - both["b"].iloc[-1]))


def monthly_gap(prices: object, id_a: str, id_b: str, range_key: str) -> GapSeries:
    """Month-end return of A minus month-end return of B, in percentage points, for the months inside the range."""
    frame_a, frame_b = _frame(prices, id_a), _frame(prices, id_b)
    if frame_a.empty or frame_b.empty:
        return GapSeries(reason=f"No stored price rows for {id_a if frame_a.empty else id_b}.")
    series = [pd.Series(adjusted_close(f).to_numpy(), index=pd.DatetimeIndex(f["date"])).resample("ME").last() for f in (frame_a, frame_b)]
    both = pd.concat([series[0].rename("a"), series[1].rename("b")], axis=1, join="inner").dropna()
    returns = both.pct_change().dropna() * 100.0
    if returns.empty:
        return GapSeries(reason="Needs at least two shared month-ends.")
    last = both.index[-1]
    returns = returns[returns.index > last - pd.Timedelta(days=RANGE_DAYS.get(range_key, 365))]
    if returns.empty:
        return GapSeries(reason="No complete month-end falls inside this range.")
    gap = returns["a"] - returns["b"]
    return GapSeries([d.strftime("%b %y") for d in gap.index], [finite(v) for v in gap])


def component_axes(first: object, second: object) -> tuple[list[str], list[float | None], list[float | None], str | None]:
    """Canonical score components of both instruments (up to six, the ones scored for A or B), 0-10."""
    def scored(score: object) -> dict[str, tuple[str, float | None]]:
        return {str(c.key): (str(c.label), finite(c.score_10)) for c in getattr(score, "components", None) or ()}

    one, two = scored(first), scored(second)
    keys = [key for key in one if one[key][1] is not None or two.get(key, ("", None))[1] is not None]
    keys += [key for key in two if key not in one and two[key][1] is not None]
    keys = keys[:6]
    if len(keys) < 3:
        return [], [], [], "Needs at least three scored components."
    labels = [(one.get(key) or two[key])[0].removesuffix(" algorithm") for key in keys]
    return labels, [one.get(key, ("", None))[1] for key in keys], [two.get(key, ("", None))[1] for key in keys], None


def risk_band(risk_friction_10: float | None) -> str | None:
    """Spec 6.1 bands of the canonical risk/friction score (10 = low friction)."""
    if risk_friction_10 is None:
        return None
    return "Low" if risk_friction_10 >= 7.0 else "Medium" if risk_friction_10 >= 4.0 else "High"
