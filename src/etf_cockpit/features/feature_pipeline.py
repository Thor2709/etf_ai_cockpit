from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd

from etf_cockpit.data.fx_data import EurRateBook, major_currency
from etf_cockpit.features.drawdown import drawdown, rolling_max_drawdown
from etf_cockpit.features.liquidity import liquidity_score
from etf_cockpit.features.momentum import momentum, weighted_momentum
from etf_cockpit.features.returns import daily_log_returns, horizon_log_returns
from etf_cockpit.features.trend import simple_moving_average
from etf_cockpit.features.volatility import ewma_volatility, realised_volatility


# Broad-market anchor for relative strength when no canonical benchmark evidence is bound:
# the accumulating FTSE All-World tracker, whose adjusted close is a total-return series.
RELATIVE_STRENGTH_FALLBACK_ANCHOR = "VWCE"


# Bumped whenever a feature formula changes so derived feature caches written by an older
# algorithm are never reused (the cache key binds this version).
FEATURE_ALGORITHM_VERSION = "features-4"

# Price features that feed the score are computed on an EUR total-return basis (adjusted close x the
# session's FX rate to EUR); ``last_price`` stays in the listing currency for display only.
CURRENCY_BASIS_EUR = "EUR"
FX_UNAVAILABLE_REASON = "fx_unavailable"
FX_NOT_REQUIRED = "not_required"

# Scale of a normal distribution from the mean absolute deviation (sqrt(pi / 2)); used only when
# more than half of the values are equal and the median absolute deviation collapses to zero.
_MEAN_ABS_DEVIATION_SCALE = 1.2533


def robust_zscore(values: pd.Series) -> pd.Series:
    """Robust z-score clipped to +-3; unavailable (all NaN) when no finite scale exists.

    A zero MAD (over half of the values equal) falls back to the scaled mean absolute
    deviation so real outliers keep their sign; a constant series has no scale and is
    unavailable rather than neutral.
    """

    # Non-finite inputs (inf) carry no usable position: they stay unavailable (NaN) and never distort the scale.
    values = pd.to_numeric(values, errors="coerce").where(lambda series: np.isfinite(series))
    median = values.median(skipna=True)
    deviation = (values - median).abs()
    denom = 1.4826 * deviation.median(skipna=True)
    if not np.isfinite(denom) or denom == 0:
        denom = _MEAN_ABS_DEVIATION_SCALE * deviation.mean(skipna=True)
    if not np.isfinite(denom) or denom == 0:
        return pd.Series(float("nan"), index=values.index)
    return ((values - median) / denom).clip(-3, 3)


def robust_zscore_by_group(values: pd.Series, groups: pd.Series) -> pd.Series:
    """``robust_zscore`` computed separately inside each group (for example asset class).

    A row's z-score depends only on the members of its own group, so adding an instrument of
    another group never changes it. Every row must carry a group label.
    """

    result = pd.Series(float("nan"), index=values.index, dtype=float)
    labels = groups.reindex(values.index)
    for _, members in values.groupby(labels, sort=False):
        result.loc[members.index] = robust_zscore(members)
    return result


@dataclass(frozen=True)
class EurBasisPrices:
    """Prices translated to EUR plus the reasons an instrument has no EUR basis."""

    frame: pd.DataFrame
    unavailable: dict[str, str]
    first_gap: dict[str, date]
    binding: dict[str, object]


def _session_days(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def _resolve_quote_currencies(
    frame: pd.DataFrame, configured_currency: Mapping[str, str] | None
) -> tuple[dict[str, str], dict[str, str]]:
    """Per instrument: major quote currency, or the reason it cannot be established."""

    configured_currency = configured_currency or {}
    resolved: dict[str, str] = {}
    problems: dict[str, str] = {}
    for etf_id, group in frame.groupby("etf_id", sort=False):
        key = str(etf_id)
        configured = major_currency(configured_currency.get(key))
        row_currencies: set[str] = set()
        if "currency" in group.columns:
            row_currencies = {code for code in group["currency"].map(major_currency).dropna().unique()}
        if len(row_currencies) > 1 or (configured is not None and row_currencies and row_currencies != {configured}):
            problems[key] = (
                f"{FX_UNAVAILABLE_REASON}: price rows carry quote currency "
                f"{', '.join(sorted(row_currencies))} that conflicts with the configured {configured or 'unknown'}"
            )
            continue
        currency = configured or (next(iter(row_currencies)) if row_currencies else None)
        if currency is None:
            problems[key] = f"{FX_UNAVAILABLE_REASON}: the quote currency is unknown, so no EUR basis can be built"
            continue
        resolved[key] = currency
    return resolved, problems


def fx_basis_binding(
    prices: pd.DataFrame,
    fx_rates: pd.DataFrame | None,
    *,
    configured_currency: Mapping[str, str] | None,
    known_by: date | datetime | str | None,
) -> dict[str, object]:
    """Identity of the FX series behind the EUR basis (feeds the feature run hash and cache binding).

    ``fx_snapshot_checksum`` is ``not_required`` when every instrument is quoted in EUR; otherwise it
    hashes the known FX rows over the price window, so an FX revision changes it.
    """

    binding: dict[str, object] = {"currency_basis": CURRENCY_BASIS_EUR, "fx_snapshot_checksum": FX_NOT_REQUIRED}
    if prices.empty or not {"etf_id", "date"}.issubset(prices.columns):
        return binding
    resolved, problems = _resolve_quote_currencies(prices, configured_currency)
    if not problems and all(currency == "EUR" for currency in resolved.values()):
        return binding
    days = _session_days(prices["date"]).dropna()
    if days.empty:
        return binding
    binding["fx_snapshot_checksum"] = EurRateBook(fx_rates, known_by=known_by).identity(min(days), max(days))
    return binding


def eur_basis_prices(
    prices: pd.DataFrame,
    fx_rates: pd.DataFrame | None,
    *,
    configured_currency: Mapping[str, str] | None,
    known_by: date | datetime | str | None,
) -> EurBasisPrices:
    """Translate ``adjusted_close`` to EUR with the same-session FX rate (canonical FX path).

    A session without a usable, point-in-time, non-stale and unambiguous rate keeps a missing EUR
    price, so every feature touching it is unavailable; the listing-currency price is never used
    in its place and no rate is ever defaulted to 1. The original series is kept in
    ``adjusted_close_local`` for display.
    """

    binding = fx_basis_binding(prices, fx_rates, configured_currency=configured_currency, known_by=known_by)
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return EurBasisPrices(prices.copy(), {}, {}, binding)
    frame = prices.copy()
    frame["adjusted_close_local"] = frame["adjusted_close"]
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce").astype(float)
    days = _session_days(frame["date"])
    resolved, problems = _resolve_quote_currencies(frame, configured_currency)
    unavailable: dict[str, str] = {}
    first_gap: dict[str, date] = {}
    book: EurRateBook | None = None
    for etf_id, group in frame.groupby("etf_id", sort=False):
        key = str(etf_id)
        member_days = days.loc[group.index]
        valid_days = member_days.dropna()
        if key in problems:
            frame.loc[group.index, "adjusted_close"] = float("nan")
            unavailable[key] = problems[key]
            if not valid_days.empty:
                first_gap[key] = min(valid_days)
            continue
        currency = resolved[key]
        if currency == "EUR":
            continue
        if book is None:
            book = EurRateBook(fx_rates, known_by=known_by)
        series = book.series(currency, sorted(set(valid_days)))
        rate = member_days.map(series.rates.to_dict()).astype(float)
        frame.loc[group.index, "adjusted_close"] = frame.loc[group.index, "adjusted_close"] * rate
        missing = rate.isna() & frame.loc[group.index, "adjusted_close_local"].notna()
        if missing.any():
            gap_days = sorted(set(member_days[missing].dropna()))
            if gap_days:
                first_gap[key] = gap_days[0]
            latest = valid_days.max() if not valid_days.empty else None
            if latest is not None and latest in gap_days:
                unavailable[key] = (
                    f"{FX_UNAVAILABLE_REASON}: {currency}/EUR rate unavailable for the latest session "
                    f"{latest.isoformat()} ({series.reasons.get(latest)}); {len(gap_days)} session(s) lack FX in the window"
                )
    return EurBasisPrices(frame, unavailable, first_gap, binding)


def attach_eur_basis(features: pd.DataFrame, eur: EurBasisPrices) -> pd.DataFrame:
    """Label ``features`` with their currency basis and blank state that remembers a missing FX session."""

    features.attrs["currency_basis"] = CURRENCY_BASIS_EUR
    features.attrs["fx_unavailable"] = dict(eur.unavailable)
    features.attrs["fx_binding"] = dict(eur.binding)
    # The running peak behind ``drawdown_current`` spans the whole history: once an FX session is
    # missing the peak (and so the drawdown) is unknown from then on.
    if {"etf_id", "date", "drawdown_current"}.issubset(features.columns):
        for etf_id, first in eur.first_gap.items():
            mask = features["etf_id"].astype(str).eq(etf_id) & features["date"].ge(first)
            features.loc[mask, "drawdown_current"] = float("nan")
    return features


def compute_features(prices: pd.DataFrame, benchmark_etf_id: str | None = None) -> pd.DataFrame:
    frame = prices.copy().sort_values(["etf_id", "date"])
    if frame.empty:
        return pd.DataFrame(columns=["date", "etf_id"])
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    # One row per (instrument, date): an equal duplicate must not shift every rolling horizon by a row.
    # Conflicting duplicates are blocked by price validation before features are computed.
    frame = frame.drop_duplicates(["etf_id", "date"], keep="last")
    feature_frames: list[pd.DataFrame] = []
    benchmark_prices: pd.Series | None = None

    if benchmark_etf_id and benchmark_etf_id in set(frame["etf_id"]):
        benchmark_prices = frame[frame["etf_id"] == benchmark_etf_id].set_index("date")["adjusted_close"].astype(float)

    for etf_id, group in frame.groupby("etf_id", sort=False):
        group = group.sort_values("date").copy()
        price = group["adjusted_close"].astype(float)
        log_ret = daily_log_returns(price)
        sma_100 = simple_moving_average(price, 100)
        sma_200 = simple_moving_average(price, 200)
        out = pd.DataFrame(
            {
                "date": group["date"].values,
                "etf_id": etf_id,
                "return_1d_log": log_ret.values,
                "return_5d_log": horizon_log_returns(price, 5).values,
                "return_20d_log": horizon_log_returns(price, 20).values,
                "return_60d_log": horizon_log_returns(price, 60).values,
                "momentum_20d": horizon_log_returns(price, 20).values,
                "momentum_60d": horizon_log_returns(price, 60).values,
                "momentum_120d": horizon_log_returns(price, 120).values,
                "momentum_180d": horizon_log_returns(price, 180).values,
                # B-04 challengers only: no live score weight pending #811 evaluation.
                "momentum_252d_skip_20d": momentum(price, 252, skip=20).values,
                "sma_50": simple_moving_average(price, 50).values,
                "sma_100": sma_100.values,
                "sma_200": sma_200.values,
                "trend_100": (price > sma_100).where(sma_100.notna()).astype(float).values,
                "trend_200": (price > sma_200).where(sma_200.notna()).astype(float).values,
                "trend_slope": (sma_100 / sma_200 - 1).values,
                "vol_20d_ann": realised_volatility(log_ret, 20).values,
                "vol_60d_ann": realised_volatility(log_ret, 60).values,
                "vol_120d_ann": realised_volatility(log_ret, 120).values,
                "ewma_vol_ann": ewma_volatility(log_ret).values,
                "drawdown_current": drawdown(price).values,
                "drawdown_60d_max": rolling_max_drawdown(price, 60).values,
                "drawdown_120d_max": rolling_max_drawdown(price, 120).values,
                "liquidity_score": liquidity_score(group["volume"], price=group["close"] if "close" in group.columns else None).values,
                # Display only: the listing-currency price (EUR-basis frames keep it in adjusted_close_local).
                "last_price": (
                    group["adjusted_close_local"] if "adjusted_close_local" in group.columns else group["adjusted_close"]
                ).astype(float).values,
            }
        )
        out["weighted_momentum_vol_scaled"] = weighted_momentum(out, volatility=out["vol_60d_ann"])
        if benchmark_prices is not None and etf_id == benchmark_etf_id:
            # The benchmark measured against itself carries no information: unavailable, not neutral.
            out["relative_strength_60d"] = float("nan")
            out["relative_strength_120d"] = float("nan")
        elif benchmark_prices is not None:
            dates = pd.Index(group["date"].values)
            out["relative_strength_60d"] = _relative_strength(price.values, dates, benchmark_prices, 60)
            out["relative_strength_120d"] = _relative_strength(price.values, dates, benchmark_prices, 120)
        else:
            out["relative_strength_60d"] = out["return_60d_log"]
            out["relative_strength_120d"] = out["momentum_120d"]
        feature_frames.append(out)

    result = pd.concat(feature_frames, ignore_index=True)
    return result.sort_values(["date", "etf_id"]).reset_index(drop=True)


# Exchanges close on different days; a benchmark close is reused for at most this many
# calendar days after it was observed (never a later close, so no look-ahead).
BENCHMARK_AS_OF_MAX_GAP_DAYS = 5


def _relative_strength(prices: np.ndarray, dates: pd.Index, benchmark: pd.Series, horizon: int) -> np.ndarray:
    """Own horizon log return minus the benchmark return over the same calendar window.

    The window starts on the instrument's own observation ``horizon`` sessions back; the
    benchmark is read as-of that same start and end instant, so exchanges with different
    holiday calendars are never compared over mismatched dates.
    """

    own = pd.Series(prices, dtype=float)
    own_return = np.log(own / own.shift(horizon)).to_numpy()
    start_dates = pd.Series(list(dates)).shift(horizon)
    valid = start_dates.notna().to_numpy()
    benchmark_end = _benchmark_as_of(benchmark, dates).to_numpy(dtype=float)
    benchmark_start = np.full(len(dates), np.nan)
    if valid.any():
        benchmark_start[valid] = _benchmark_as_of(benchmark, pd.Index(start_dates[valid])).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        benchmark_return = np.log(benchmark_end / benchmark_start)
    return own_return - benchmark_return


def _benchmark_as_of(benchmark: pd.Series, dates: pd.Index) -> pd.Series:
    """Benchmark value at its latest observation on or before each date (as-of join)."""

    source = benchmark.dropna()
    source.index = pd.to_datetime(source.index)
    source = source[~source.index.duplicated(keep="last")].sort_index()
    target = pd.to_datetime(pd.Index(dates))
    if source.empty:
        return pd.Series(float("nan"), index=dates)
    aligned = source.reindex(target, method="ffill", tolerance=pd.Timedelta(days=BENCHMARK_AS_OF_MAX_GAP_DAYS))
    return pd.Series(aligned.values, index=dates)


def latest_features(features: pd.DataFrame, as_of_date: date | None = None) -> pd.DataFrame:
    frame = features.copy()
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    if as_of_date is not None:
        frame = frame[frame["date"] <= as_of_date]
    return frame.sort_values("date").groupby("etf_id", as_index=False).tail(1).reset_index(drop=True)
