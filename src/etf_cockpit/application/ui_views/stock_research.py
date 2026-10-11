"""Read-only view model for the Stock Research first screen (spec 6.3, section 8).

Plain values plus an unavailable reason per element. Nothing here changes a score, gate, forecast or
portfolio decision; every series is cut at the last stored price date and missing values stay None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import pandas as pd

RANGE_DAYS = {"1M": 30, "3M": 91, "1Y": 365, "5Y": 1826}
TRADING_DAYS = 252.0
FACTOR_AXES = ("Value", "Size", "Momentum", "Quality", "Low vol", "Yield")
_FACTOR_KEYS = {"Value": "value", "Momentum": "momentum", "Quality": "quality", "Low vol": "low_volatility"}


@dataclass
class ForecastLine:
    model: str
    dates: list[pd.Timestamp]
    q10: list[float]
    q25: list[float | None]
    q50: list[float]
    q75: list[float | None]
    q90: list[float]


@dataclass
class StockView:
    instrument_id: str
    range_key: str
    dates: list[pd.Timestamp] = field(default_factory=list)
    close: list[float | None] = field(default_factory=list)
    benchmark: list[float | None] = field(default_factory=list)
    benchmark_id: str | None = None
    drawdown: list[float | None] = field(default_factory=list)  # percent, <= 0
    dividend_index: list[int] = field(default_factory=list)
    forecasts: list[ForecastLine] = field(default_factory=list)
    baseline: ForecastLine | None = None
    forecast_note: str | None = None
    unavailable_price: str | None = None
    # stat tiles
    total_return: float | None = None
    volatility: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    stat_reasons: dict[str, str] = field(default_factory=dict)
    spark_price: list[float | None] = field(default_factory=list)
    spark_vol: list[float | None] = field(default_factory=list)
    spark_dd: list[float | None] = field(default_factory=list)
    benchmark_return: float | None = None
    # attribution: component -> index points (None = n/a)
    attribution: dict[str, float | None] = field(default_factory=dict)
    attribution_reasons: dict[str, str] = field(default_factory=dict)
    # rolling 12M
    roll_labels: list[str] = field(default_factory=list)
    roll_instrument: list[float | None] = field(default_factory=list)
    roll_benchmark: list[float | None] = field(default_factory=list)
    roll_reason: str | None = None
    # data quality
    adjusted_share: float | None = None
    gap_count: int | None = None
    last_date: pd.Timestamp | None = None


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def price_series(prices: pd.DataFrame, instrument_id: str) -> pd.DataFrame:
    """Stored price rows of one instrument, sorted by date, one row per date."""
    if prices is None or prices.empty or "etf_id" not in prices:
        return pd.DataFrame()
    frame = prices[prices["etf_id"].astype(str) == str(instrument_id)].copy()
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame.dropna(subset=["date"]).drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def adjusted_close(frame: pd.DataFrame) -> pd.Series:
    column = "adjusted_close" if "adjusted_close" in frame else "close"
    return pd.to_numeric(frame[column], errors="coerce")


def month_end_returns(frame: pd.DataFrame, months: int = 12) -> pd.Series:
    """N-month return at each month end, from adjusted closes already stored (no look-ahead)."""
    series = pd.Series(adjusted_close(frame).to_numpy(), index=pd.DatetimeIndex(frame["date"])).dropna()
    monthly = series.resample("ME").last().dropna()
    return (monthly / monthly.shift(months) - 1.0).dropna()


def _forecast_lines(forecasts: pd.DataFrame, instrument_id: str, last_date: pd.Timestamp, prices: pd.DataFrame) -> tuple[list[ForecastLine], bool]:
    """Pass-through of stored quantile rows; a row with a missing or unordered q10/q50/q90 is skipped."""
    needed = {"etf_id", "model_name", "forecast_date", "horizon_days", "q10_return", "q50_return", "q90_return"}
    if forecasts is None or forecasts.empty or not needed.issubset(forecasts.columns):
        return [], False
    rows = forecasts[forecasts["etf_id"].astype(str) == str(instrument_id)]
    if rows.empty:
        return [], False
    dates = pd.to_datetime(rows["forecast_date"], errors="coerce", utc=True)
    rows = rows.loc[dates.notna()].copy()
    if rows.empty:
        return [], False
    rows["__forecast_date"] = pd.to_datetime(rows["forecast_date"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    latest_vintage = rows["__forecast_date"].max()
    rows = rows.loc[rows["__forecast_date"].eq(latest_vintage)]
    if "date" not in prices.columns or "close" not in prices.columns:
        return [], False
    price_dates = pd.to_datetime(prices["date"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    price_closes = pd.to_numeric(prices["close"], errors="coerce")
    close_by_date = {day: finite(close) for day, close in zip(price_dates, price_closes, strict=True) if pd.notna(day)}
    lines: list[ForecastLine] = []
    stale = False
    for model, group in rows.groupby("model_name", sort=True):
        line = ForecastLine(str(model), [], [], [], [], [], [])
        for _, row in group.sort_values("horizon_days").iterrows():
            horizon = finite(row.get("horizon_days"))
            q10, q50, q90 = (finite(row.get(name)) for name in ("q10_return", "q50_return", "q90_return"))
            if horizon is None or horizon <= 0 or q10 is None or q50 is None or q90 is None or not q10 <= q50 <= q90:
                continue
            forecast_date = row["__forecast_date"]
            target_date = forecast_date + pd.Timedelta(days=int(horizon))
            if target_date <= last_date:
                stale = True
                continue
            forecast_close = close_by_date.get(forecast_date)
            if forecast_close is None:
                continue
            q25, q75 = finite(row.get("q25_return")), finite(row.get("q75_return"))
            if q25 is None or q75 is None or not q10 <= q25 <= q50 <= q75 <= q90:
                q25 = q75 = None  # never interpolated: the 50% fan is simply not drawn
            line.dates.append(target_date)
            line.q10.append(forecast_close * (1 + q10))
            line.q50.append(forecast_close * (1 + q50))
            line.q90.append(forecast_close * (1 + q90))
            line.q25.append(None if q25 is None else forecast_close * (1 + q25))
            line.q75.append(None if q75 is None else forecast_close * (1 + q75))
        if line.dates:
            lines.append(line)
    return lines, stale


def build_stock_view(
    prices: pd.DataFrame,
    forecasts: pd.DataFrame,
    instrument_id: str,
    range_key: str,
    *,
    benchmark_id: str | None = None,
    cash_return: float | None = None,
    cash_horizon_years: float | None = None,
) -> StockView:
    view = StockView(instrument_id=instrument_id, range_key=range_key, benchmark_id=benchmark_id)
    full = price_series(prices, instrument_id)
    if full.empty:
        view.unavailable_price = "No stored price rows for this instrument."
        for key in ("return", "volatility", "drawdown", "sharpe"):
            view.stat_reasons[key] = view.unavailable_price
        view.roll_reason = view.unavailable_price
        return view
    last = full["date"].iloc[-1]
    view.last_date = last
    window = full[full["date"] >= last - pd.Timedelta(days=RANGE_DAYS.get(range_key, 365))].reset_index(drop=True)
    adj = adjusted_close(window)
    raw = pd.to_numeric(window["close"], errors="coerce") if "close" in window else adj
    view.dates = list(window["date"])
    view.close = [finite(v) for v in raw]
    if len(window) < 2:
        view.unavailable_price = "Fewer than two stored prices in this range."
    view.drawdown = [finite(v) for v in (adj / adj.cummax() - 1.0) * 100.0]

    # benchmark rebased to the first close; exact-date matches only (no fill)
    bench_frame = price_series(prices, benchmark_id) if benchmark_id and benchmark_id != instrument_id else pd.DataFrame()
    if not bench_frame.empty:
        bench = pd.Series(adjusted_close(bench_frame).to_numpy(), index=pd.DatetimeIndex(bench_frame["date"]))
        aligned = bench.reindex(pd.DatetimeIndex(window["date"]))
        present = aligned.dropna()
        if not present.empty and view.close and view.close[0] is not None:
            base = float(present.iloc[0])
            view.benchmark = [None if pd.isna(v) else float(v) / base * view.close[0] for v in aligned]
            if len(present) > 1:
                view.benchmark_return = float(present.iloc[-1]) / base - 1.0

    # ex-dividend markers where the adjusted / raw close ratio steps
    if "close" in window and len(window) > 2:
        ratio = (adj / raw).replace([math.inf, -math.inf], math.nan)
        step = ratio.pct_change(fill_method=None).abs()
        view.dividend_index = [int(i) for i in step.index[step > 0.001]][:12]

    # stat tiles (descriptive statistics over the selected range)
    reason = "Needs at least two prices in the range."
    if len(window) >= 2 and adj.notna().sum() >= 2:
        valid = adj.dropna()
        view.total_return = float(valid.iloc[-1] / valid.iloc[0] - 1.0)
        daily = valid.pct_change().dropna()
        if len(daily) >= 2:
            view.volatility = float(daily.std(ddof=1) * math.sqrt(TRADING_DAYS))
        view.max_drawdown = float((valid / valid.cummax() - 1.0).min())
        view.spark_price = [finite(v) for v in adj]
        view.spark_dd = list(view.drawdown)
        rolling = adj.pct_change().rolling(min(20, max(2, len(window) // 3))).std() * math.sqrt(TRADING_DAYS)
        view.spark_vol = [finite(v) for v in rolling]
        years = max((window["date"].iloc[-1] - window["date"].iloc[0]).days / 365.25, 1e-9)
        if view.volatility and cash_return is not None and cash_horizon_years and cash_horizon_years > 0:
            risk_free = (1.0 + cash_return) ** (1.0 / cash_horizon_years) - 1.0
            annual = (1.0 + view.total_return) ** (1.0 / years) - 1.0
            view.sharpe = (annual - risk_free) / view.volatility
    for key, value in (("return", view.total_return), ("volatility", view.volatility), ("drawdown", view.max_drawdown)):
        if value is None:
            view.stat_reasons[key] = reason
    if view.sharpe is None:
        view.stat_reasons["sharpe"] = (
            "No risk-free rate is bound to this range."
            if cash_return is None or not cash_horizon_years
            else "Volatility is unavailable for this range."
        )

    # return attribution in index points (base 100); components without evidence stay n/a
    if view.total_return is not None and raw.notna().sum() >= 2:
        raw_valid = raw.dropna()
        price_points = (float(raw_valid.iloc[-1] / raw_valid.iloc[0]) - 1.0) * 100.0
        view.attribution["Price"] = price_points
        flagged = bool(window["is_adjusted"].astype(bool).all()) if "is_adjusted" in window else False
        if flagged:
            view.attribution["Dividends"] = view.total_return * 100.0 - price_points
        else:
            view.attribution["Dividends"] = None
            view.attribution_reasons["Dividends"] = "prices are not marked adjusted"
    else:
        view.attribution["Price"] = None
        view.attribution["Dividends"] = None
        view.attribution_reasons["Price"] = reason
    for name, why in (("FX", "no FX series is bound"), ("Fees", "no fee evidence is bound"), ("Tax", "no tax evidence is stored")):
        view.attribution[name] = None
        view.attribution_reasons[name] = why

    # rolling 12M return vs benchmark: the last 24 month-ends
    own = month_end_returns(full)
    if own.empty:
        view.roll_reason = "Needs at least 13 month-end prices."
    else:
        own = own.iloc[-24:]
        bench_roll = month_end_returns(bench_frame) if not bench_frame.empty else pd.Series(dtype=float)
        view.roll_labels = [d.strftime("%b %y") for d in own.index]
        view.roll_instrument = [float(v) * 100.0 for v in own]
        view.roll_benchmark = [float(bench_roll.loc[d]) * 100.0 if d in bench_roll.index else None for d in own.index]

    if "is_adjusted" in window:
        view.adjusted_share = float(window["is_adjusted"].astype(bool).mean())
    view.gap_count = int((window["date"].diff().dt.days.dropna() > 5).sum())

    last_close = view.close[-1] if view.close else None
    if last_close is not None:
        lines, stale = _forecast_lines(forecasts, instrument_id, last, full)
        if not lines and stale:
            view.forecast_note = "forecast stale"
        view.baseline = next((line for line in lines if "baseline" in line.model.casefold()), None)
        view.forecasts = [line for line in lines if line is not view.baseline]
    return view


def factor_profile(
    latest_features: pd.DataFrame,
    holdings: pd.DataFrame,
    universe_ids: list[str],
    instrument_id: str,
    benchmark_id: str | None,
) -> tuple[list[float | None], str | None]:
    """Instrument minus benchmark factor z-scores per axis, from the existing exposure builder."""
    from etf_cockpit.portfolio.factor_risk import build_factor_exposures

    none = [None] * len(FACTOR_AXES)
    if latest_features is None or latest_features.empty or instrument_id not in universe_ids:
        return none, "No factor descriptors are stored for this instrument."
    allocation = pd.DataFrame({"etf_id": universe_ids, "market_value_eur": 1.0})
    try:
        exposures = build_factor_exposures(allocation, latest_features, holdings)
    except (KeyError, ValueError, TypeError):
        return none, "Factor exposures could not be built from the stored descriptors."
    if exposures.empty:
        return none, "No factor descriptors are stored for this instrument."

    def exposure(identifier: str, factor: str) -> float | None:
        rows = exposures[(exposures["instrument_id"].astype(str) == identifier) & (exposures["factor"] == factor)]
        return None if rows.empty else finite(rows["exposure"].iloc[0])

    values: list[float | None] = []
    for axis in FACTOR_AXES:
        key = _FACTOR_KEYS.get(axis)
        own = exposure(instrument_id, key) if key else None
        if own is None:
            values.append(None)
            continue
        reference = exposure(benchmark_id, key) if benchmark_id else None
        values.append(own - reference if reference is not None else own)
    return values, None if any(v is not None for v in values) else "Descriptors for these factors are missing."


def scenario_surface_reason(forecasts: pd.DataFrame, instrument_id: str, saved_scenario_count: int) -> str:
    """Why the 3D scenario surface is unavailable. Saved Stress Lab scenarios carry shocks, not a volatility level,
    so the surface is never synthesised: the forecast median is not re-scaled by an invented volatility."""
    horizons = 0
    if forecasts is not None and not forecasts.empty and {"etf_id", "horizon_days"}.issubset(forecasts.columns):
        horizons = int(forecasts.loc[forecasts["etf_id"].astype(str) == str(instrument_id), "horizon_days"].nunique())
    if horizons < 3:
        return f"Needs forecasts for at least 3 horizons ({horizons} stored)."
    if saved_scenario_count < 2:
        return f"Needs at least 2 saved stress scenarios ({saved_scenario_count} saved)."
    return "Saved stress scenarios define market shocks, not a volatility level, so no scenario surface is drawn."
