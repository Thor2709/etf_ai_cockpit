"""Point-in-time execution-cost-v1 round-trip table from stored daily bars (owner 2026-11-25: reconstructed model).

One row per instrument and month-end session: the last stored session of each calendar month. A row uses only bars
dated up to that session and FX quotes known by its close, and is known at that close (23:59:59 UTC, the OD-1 b
session-close rule). Inputs: 20-session EUR ADV (``average_daily_value_eur``), daily volatility of adjusted-close
returns over 60 sessions (at least half observed), spread/slippage/commission from the cost config, and the most
conservative documented tier where no per-instrument spread is configured. A missing input gives no row; nothing is
filled or zeroed. ``round_trip_cost_bps`` is a buy plus a sell of ``order_value_eur``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.data.fx_data import EurRateBook, major_currency
from etf_cockpit.portfolio.costs import COST_MODEL_ID, _valid_quote, average_daily_value_eur, estimate_execution_cost

COST_BASIS = "reconstructed_model"
ADV_WINDOW = 20
VOLATILITY_WINDOW = 60
COLUMNS = [
    "instrument_id", "known_at", "round_trip_cost_bps", "cost_model_id", "cost_basis", "order_value_eur",
    "adv_eur", "daily_volatility", "conservative_tier", "data_quality",
]


def build_pit_cost_table(
    prices: pd.DataFrame, fx_rates: pd.DataFrame | None, config: AppConfig, *, order_value_eur: float
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return the table (sorted by instrument and ``known_at``) and the count of month-end rows skipped per reason."""

    frame = prices.loc[:, ["etf_id", "date", "close", "adjusted_close", "volume", "currency"]]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["etf_id", "date"]).drop_duplicates(["etf_id", "date"], keep="last")
    frame = frame.sort_values(["etf_id", "date"], kind="stable")
    per_etf = getattr(config.costs, "per_etf", {})
    series: dict[str, tuple] = {}
    month_ends: list[tuple[pd.Timestamp, str, int]] = []
    skipped: dict[str, int] = {}
    for instrument, group in frame.groupby("etf_id", sort=True, observed=True):
        instrument = str(instrument)
        dates = pd.DatetimeIndex(group["date"])
        positions = np.flatnonzero(np.append(dates.to_period("M")[1:] != dates.to_period("M")[:-1], True))
        currencies = {major_currency(value) for value in group["currency"]}
        if len(currencies) != 1 or None in currencies:
            skipped["currency_unknown"] = skipped.get("currency_unknown", 0) + len(positions)
            continue
        series[instrument] = (
            dates, next(iter(currencies)),
            *(pd.to_numeric(group[name], errors="coerce").to_numpy(dtype=float) for name in ("close", "adjusted_close", "volume")),
        )
        month_ends.extend((dates[position], instrument, int(position)) for position in positions)
    del frame
    # Sessions in order: one FX book (FX known by that session's close) is alive at a time.
    book: tuple[pd.Timestamp, EurRateBook] | None = None
    rows: list[dict[str, object]] = []
    for session, instrument, position in sorted(month_ends):
        dates, currency, close, adjusted, volume = series[instrument]
        cutoff = session.tz_localize("UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
        window = slice(max(0, position - ADV_WINDOW + 1), position + 1)
        rate = np.ones(window.stop - window.start)
        if currency != "EUR":
            if book is None or book[0] != session:
                book = (session, EurRateBook(fx_rates, known_by=cutoff.to_pydatetime()))
            rate = book[1].series(currency, [item.date() for item in dates[window]]).rates.to_numpy(dtype=float)
        adv = average_daily_value_eur(volume[window], close[window] * rate, currency="EUR", window=ADV_WINDOW)
        volatility = _daily_volatility(adjusted[max(0, position - VOLATILITY_WINDOW): position + 1])
        reason = (
            "adv_unavailable" if adv is None or adv <= 0
            else "volatility_unavailable" if volatility is None
            else None
        )
        if reason is not None:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        # no per-instrument spread configured and none stored as a quote: the conservative documented tier applies
        conservative = _valid_quote(per_etf.get(instrument, {}).get("spread_bps")) is None
        estimate = estimate_execution_cost(
            config, instrument, order_value_eur, adv_eur=adv, daily_volatility=volatility,
            conservative_tier=conservative,
        )
        if estimate.model_id != COST_MODEL_ID:
            raise ValueError(f"cost config model {estimate.model_id!r} is not {COST_MODEL_ID!r}")
        rows.append({
            "instrument_id": instrument,
            "known_at": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "round_trip_cost_bps": 2.0 * estimate.total_cost_bps,
            "cost_model_id": COST_MODEL_ID,
            "cost_basis": COST_BASIS,
            "order_value_eur": float(order_value_eur),
            "adv_eur": adv,
            "daily_volatility": volatility,
            "conservative_tier": conservative,
            "data_quality": estimate.data_quality,
        })
    table = pd.DataFrame(rows, columns=COLUMNS).sort_values(["instrument_id", "known_at"], kind="stable", ignore_index=True)
    return table, dict(sorted(skipped.items()))


def _daily_volatility(adjusted: np.ndarray) -> float | None:
    """Sample std of daily returns over the trailing window; None below half the window or when not positive."""

    with np.errstate(all="ignore"):
        returns = adjusted[1:] / adjusted[:-1] - 1.0
    returns = returns[np.isfinite(returns)]
    if len(returns) * 2 < VOLATILITY_WINDOW:
        return None
    value = float(np.std(returns, ddof=1))
    return value if math.isfinite(value) and value > 0 else None


__all__ = ["ADV_WINDOW", "COLUMNS", "COST_BASIS", "VOLATILITY_WINDOW", "build_pit_cost_table"]
