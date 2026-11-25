"""BF2: ``eur_basis_prices`` reads one rate series per currency and converts all rows at once.

The oracle is the former per-instrument loop (kept here verbatim); the result must be equal in every field.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.data.fx_data import EurRateBook, eur_rate_book
from etf_cockpit.features import feature_pipeline as fp

KNOWN_BY = "2025-12-31T23:59:59+00:00"
DAYS = pd.bdate_range("2025-03-03", periods=60)


def _oracle(prices, fx_rates, *, configured_currency, known_by) -> fp.EurBasisPrices:
    binding = fp.fx_basis_binding(prices, fx_rates, configured_currency=configured_currency, known_by=known_by)
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return fp.EurBasisPrices(prices.copy(), {}, {}, binding)
    frame = prices.copy()
    frame["adjusted_close_local"] = frame["adjusted_close"]
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce").astype(float)
    has_close = "close" in frame.columns
    if has_close:
        frame["close_local"] = frame["close"]
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce").astype(float)
    days = fp._session_days(frame["date"])
    resolved, problems = fp._resolve_quote_currencies(frame, configured_currency)
    unavailable: dict[str, str] = {}
    first_gap: dict[str, date] = {}
    book: EurRateBook | None = None
    for etf_id, group in frame.groupby("etf_id", sort=False):
        key = str(etf_id)
        member_days = days.loc[group.index]
        valid_days = member_days.dropna()
        if key in problems:
            frame.loc[group.index, "adjusted_close"] = float("nan")
            if has_close:
                frame.loc[group.index, "close"] = float("nan")
            unavailable[key] = problems[key]
            if not valid_days.empty:
                first_gap[key] = min(valid_days)
            continue
        currency = resolved[key]
        if currency == "EUR":
            continue
        if book is None:
            book = eur_rate_book(fx_rates, known_by=known_by)
        series = book.series(currency, sorted(set(valid_days)))
        rate = member_days.map(series.rates.to_dict()).astype(float)
        frame.loc[group.index, "adjusted_close"] = frame.loc[group.index, "adjusted_close"] * rate
        if has_close:
            frame.loc[group.index, "close"] = frame.loc[group.index, "close"] * rate
        missing = rate.isna() & frame.loc[group.index, "adjusted_close_local"].notna()
        if missing.any():
            gap_days = sorted(set(member_days[missing].dropna()))
            if gap_days:
                first_gap[key] = gap_days[0]
            latest = valid_days.max() if not valid_days.empty else None
            if latest is not None and latest in gap_days:
                unavailable[key] = (
                    f"{fp.FX_UNAVAILABLE_REASON}: {currency}/EUR rate unavailable for the latest session "
                    f"{latest.isoformat()} ({series.reasons.get(latest)}); {len(gap_days)} session(s) lack FX in the window"
                )
    return fp.EurBasisPrices(frame, unavailable, first_gap, binding)


def _fx() -> pd.DataFrame:
    rows = []
    for position, day in enumerate(DAYS):
        if 20 <= position < 40:  # a NOK gap longer than the staleness band, then fresh quotes again
            continue
        rows.append((day.date(), "NOK", "EUR", 0.085 + position * 1e-4))
        if position < 50:  # USD quotes stop: the latest USD sessions have no rate
            rows.append((day.date(), "EUR", "USD", 1.08 + position * 1e-4))
    frame = pd.DataFrame(rows, columns=["as_of_date", "base_currency", "quote_currency", "rate"])
    frame["source"] = "fixture"
    frame["ingested_at"] = "2025-01-01T00:00:00Z"
    return frame


def _series(etf_id, days, *, currency, seed, close=True):
    rng = np.random.default_rng(seed)
    values = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
    frame = pd.DataFrame({"date": list(days), "etf_id": etf_id, "adjusted_close": values, "volume": 1000.0, "currency": currency})
    if close:
        frame["close"] = values * 1.01
    return frame


def _prices(close=True) -> pd.DataFrame:
    frames = [
        _series("EURX", DAYS, currency="EUR", seed=1, close=close),
        _series("NOKX", DAYS, currency="NOK", seed=2, close=close),  # inner FX gap: first_gap, latest is fine
        _series("USDX", DAYS, currency="USD", seed=3, close=close),  # latest sessions lack FX: unavailable
        _series("NOKY", DAYS[30:], currency="NOK", seed=4, close=close),  # starts inside the gap
        _series("MIXD", DAYS, currency="NOK", seed=5, close=close),  # one row in USD conflicts: problem
        _series("UNKN", DAYS[:10], currency=None, seed=6, close=close),  # no configured or row currency: problem
        _series("GBXX", DAYS[:5], currency="GBp", seed=7, close=close),  # minor unit, no GBP quotes
    ]
    frame = pd.concat(frames, ignore_index=True)
    frame.loc[frame.index[frame["etf_id"].eq("MIXD")][5], "currency"] = "USD"
    frame.loc[frame.index[frame["etf_id"].eq("NOKX")][3], "date"] = None  # unparsable date row
    frame.loc[frame.index[frame["etf_id"].eq("NOKX")][4], "adjusted_close"] = float("nan")
    frame.loc[len(frame)] = {**frame.iloc[0].to_dict(), "etf_id": None}  # a row without an id is left as it is
    frame = frame.sample(frac=1.0, random_state=3)  # rows of one id need not be contiguous
    frame.index = frame.index * 3 + 7  # labels, not positions
    return frame


CONFIGURED = {"EURX": "EUR", "NOKX": "NOK", "USDX": "USD", "NOKY": "NOK", "MIXD": "NOK", "GBXX": "GBP"}


def _assert_equal(new: fp.EurBasisPrices, old: fp.EurBasisPrices) -> None:
    pd.testing.assert_frame_equal(new.frame, old.frame, check_exact=True)
    assert new.unavailable == old.unavailable and list(new.unavailable) == list(old.unavailable)
    assert new.first_gap == old.first_gap
    assert new.binding == old.binding


@pytest.mark.parametrize("close", [True, False])
@pytest.mark.parametrize("known_by", [KNOWN_BY, "2025-04-15T23:59:59+00:00", "2025-03-01T23:59:59+00:00"])
def test_vectorised_eur_basis_equals_the_per_instrument_loop(close, known_by):
    prices, fx = _prices(close), _fx()
    new = fp.eur_basis_prices(prices, fx, configured_currency=CONFIGURED, known_by=known_by)
    _assert_equal(new, _oracle(prices, fx, configured_currency=CONFIGURED, known_by=known_by))
    assert set(new.unavailable) >= {"MIXD", "UNKN"}


@pytest.mark.parametrize("fx", [None, pd.DataFrame()])
def test_vectorised_eur_basis_without_fx_and_on_edge_frames(fx):
    prices = _prices()
    for frame in (prices, prices.iloc[0:0], prices.drop(columns=["adjusted_close"]), prices.loc[prices["etf_id"].eq("EURX")]):
        _assert_equal(
            fp.eur_basis_prices(frame, fx, configured_currency=CONFIGURED, known_by=KNOWN_BY),
            _oracle(frame, fx, configured_currency=CONFIGURED, known_by=KNOWN_BY),
        )
