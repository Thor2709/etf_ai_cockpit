"""B22-N002: quote-currency turnover must be converted to EUR (dated, PIT FX) before liquidity thresholds."""

from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.signals.simple_scores import (
    _liquidity_component,
    _liquidity_fx_snapshot,
    _price_liquidity_lookup,
)

AS_OF = "2026-10-09"
# Exactly representable rates keep the threshold-boundary assertions free of rounding noise.
RATES_TO_EUR = {"EUR": 1.0, "USD": 0.5, "GBP": 1.25, "NOK": 0.125}
THRESHOLDS_EUR = (10_000_000, 2_000_000, 500_000, 100_000, 25_000)


def _dates(count: int = 25, end: str = AS_OF) -> pd.DatetimeIndex:
    return pd.bdate_range(end=end, periods=count)


def _prices(eur_value: float, currency: str, *, rate: float | None = None, currency_label: str | None = None, count: int = 25) -> pd.DataFrame:
    """Daily traded value equal to ``eur_value`` EUR, expressed in ``currency``."""

    native = eur_value / (RATES_TO_EUR[currency] if rate is None else rate)
    close = 100.0
    frame = pd.DataFrame(
        {
            "etf_id": "X",
            "date": _dates(count),
            "close": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "volume": native / close,
        }
    )
    if currency_label is not None:
        frame["currency"] = currency_label
    return frame


def _fx(currencies: tuple[str, ...] = ("USD", "GBP", "NOK"), *, last: str = AS_OF, ingested_at: str | None = None, rates: dict[str, float] | None = None) -> pd.DataFrame:
    rates = rates or RATES_TO_EUR
    rows = []
    for day in pd.bdate_range(end=last, periods=60):
        for currency in currencies:
            rows.append(
                {
                    "as_of_date": day.date(),
                    "base_currency": currency,
                    "quote_currency": "EUR",
                    "rate": rates[currency],
                    "source": "test_fx",
                    # Ordinary fixture evidence is available on each quote day; overrides test late ingestion.
                    "ingested_at": pd.Timestamp(ingested_at) if ingested_at is not None else day.tz_localize("UTC") + pd.Timedelta(hours=12),
                }
            )
    return pd.DataFrame(rows)


def _component(prices: pd.DataFrame, currency: str, fx: pd.DataFrame | None):
    info = _price_liquidity_lookup(prices, currency_by_id={"X": currency}, fx_rates=fx)["X"]
    return _liquidity_component(info), info


@pytest.mark.parametrize("threshold", THRESHOLDS_EUR)
@pytest.mark.parametrize("delta", [0.0, -0.01])
def test_same_economic_value_scores_identically_in_every_currency(threshold: float, delta: float) -> None:
    eur_value = threshold + delta
    fx = _fx()
    reference, _ = _component(_prices(eur_value, "EUR"), "EUR", fx)
    assert reference.raw_score is not None
    for currency in ("USD", "GBP", "NOK"):
        component, info = _component(_prices(eur_value, currency), currency, fx)
        assert info["avg_turnover_20"] == pytest.approx(eur_value, rel=1e-12)
        assert component.raw_score == reference.raw_score, currency
        assert f"EUR {eur_value:,.0f}" in component.why


def test_threshold_edges_are_not_all_equal() -> None:
    fx = _fx()
    above, _ = _component(_prices(2_000_000, "USD"), "USD", fx)
    below, _ = _component(_prices(1_999_999, "USD"), "USD", fx)
    assert above.raw_score > below.raw_score


def test_issue_examples_use_eur_not_quote_currency_value() -> None:
    # USD 2.20m at 0.8918 is EUR 1.962m (below the 2m step); GBP 1.80m at 1.18 is EUR 2.124m (above it).
    fx = _fx(rates={"USD": 0.8918, "GBP": 1.18, "NOK": 0.085})
    usd = _price_liquidity_lookup(_prices(1_962_000, "USD", rate=0.8918), currency_by_id={"X": "USD"}, fx_rates=fx)["X"]
    assert usd["avg_turnover_20"] == pytest.approx(1_962_000)
    gbp = _price_liquidity_lookup(_prices(2_124_000, "GBP", rate=1.18), currency_by_id={"X": "GBP"}, fx_rates=fx)["X"]
    assert gbp["avg_turnover_20"] == pytest.approx(2_124_000)
    usd_score = _liquidity_component(usd).raw_score
    gbp_score = _liquidity_component(gbp).raw_score
    assert gbp_score > usd_score


@pytest.mark.parametrize("fx", [None, pd.DataFrame(), _fx(("NOK",))])
def test_missing_fx_is_unavailable_never_one_to_one(fx: pd.DataFrame | None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("etf_cockpit.signals.simple_scores.load_fx_rates", lambda *a, **k: pd.DataFrame())
    component, info = _component(_prices(5_000_000, "USD"), "USD", fx)
    assert component.raw_score is None
    assert info["avg_turnover_20"] is None
    assert "unavailable" in component.why.lower() and "USD" in component.why and "1:1" in component.why


def test_eur_instrument_needs_no_fx() -> None:
    component, _ = _component(_prices(5_000_000, "EUR"), "EUR", pd.DataFrame())
    assert component.raw_score is not None
    assert "converted" not in component.why


def test_stale_fx_is_unavailable() -> None:
    stale = _fx(last="2026-09-01")  # 28 business days before the 2026-10-09 rows
    component, _ = _component(_prices(5_000_000, "GBP"), "GBP", stale)
    assert component.raw_score is None
    assert "business days old" in component.why and "GBP" in component.why


def test_fx_ingested_after_the_score_as_of_is_unavailable() -> None:
    later = _fx(ingested_at="2026-10-20T00:00:00Z")
    component, _ = _component(_prices(5_000_000, "USD"), "USD", later)
    assert component.raw_score is None


def test_gbp_pence_label_is_converted_exactly_once() -> None:
    fx = _fx()
    pence, pence_info = _component(_prices(5_000_000, "GBP", currency_label="GBp"), "GBp", fx)
    pounds, pounds_info = _component(_prices(5_000_000, "GBP", currency_label="GBP"), "GBP", fx)
    # Stored prices are already scaled to pounds by the provider: the label must not trigger /100 again.
    assert pence_info["avg_turnover_20"] == pytest.approx(5_000_000)
    assert pence_info["avg_turnover_20"] == pounds_info["avg_turnover_20"]
    assert pence.raw_score == pounds.raw_score
    # Exactly one FX multiplication: native turnover x GBP/EUR.
    native = (100.0 * (5_000_000 / 1.25 / 100.0))
    assert pence_info["avg_turnover_20"] == pytest.approx(native * 1.25)


def test_each_row_uses_its_own_dated_rate_before_averaging() -> None:
    days = _dates(25)
    rows = []
    for day in pd.bdate_range(end=AS_OF, periods=60):
        rows.append(
            {
                "as_of_date": day.date(),
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate": 0.5 if day < days[-10] else 1.0,
                "source": "test_fx",
                "ingested_at": day.tz_localize("UTC") + pd.Timedelta(hours=12),
            }
        )
    prices = _prices(1_000_000, "USD", rate=1.0)  # native 1m per day
    info = _price_liquidity_lookup(prices, currency_by_id={"X": "USD"}, fx_rates=pd.DataFrame(rows))["X"]
    # 10 of the last 20 rows convert at 1.0, the other 10 at 0.5 => mean 750k, not last-rate x mean (1m).
    assert info["avg_turnover_20"] == pytest.approx(750_000)


def test_reason_states_source_currency_and_fx_date() -> None:
    component, _ = _component(_prices(5_000_000, "NOK"), "NOK", _fx())
    assert "NOK" in component.why and "EUR" in component.why
    assert "2026-10-09" in component.why


def test_conflicting_price_row_currency_is_unavailable() -> None:
    component, _ = _component(_prices(5_000_000, "USD", currency_label="CHF"), "USD", _fx())
    assert component.raw_score is None
    assert "conflicts" in component.why


def test_unknown_currency_is_unavailable() -> None:
    info = _price_liquidity_lookup(_prices(5_000_000, "USD"), currency_by_id={}, fx_rates=_fx())["X"]
    component = _liquidity_component(info)
    assert component.raw_score is None and "unknown" in component.why


def test_historical_fx_cutoff_is_per_row_and_cache_includes_cutoff() -> None:
    fx = _fx(ingested_at="2026-10-01T00:00:00Z")
    prices = _prices(1_000_000, "USD", count=2)
    prices["date"] = pd.to_datetime(["2026-09-30", AS_OF])
    earlier = prices.iloc[:1].assign(etf_id="Y")
    for frames in ((prices, earlier), (earlier, prices)):
        result = _price_liquidity_lookup(
            pd.concat(frames, ignore_index=True), currency_by_id={"X": "USD", "Y": "USD"}, fx_rates=fx
        )
        for instrument in ("X", "Y"):
            assert result[instrument]["avg_turnover_20"] is None
            assert "2026-09-30" in result[instrument]["fx_unavailable_reason"]
            assert _liquidity_component(result[instrument]).raw_score is None

    # The same quote day must not reuse a snapshot obtained with later knowledge.
    state = {"frame": fx, "snapshots": {}}
    row_day = pd.Timestamp("2026-09-30").date()
    later = _liquidity_fx_snapshot(state, row_day, pd.Timestamp("2026-10-09T23:59:59Z").to_pydatetime())
    earlier = _liquidity_fx_snapshot(state, row_day, pd.Timestamp("2026-09-30T23:59:59Z").to_pydatetime())
    assert later.available
    assert not earlier.available
    assert len(state["snapshots"]) == 2


@pytest.mark.parametrize("timezone", ["UTC", "Europe/Berlin", "America/New_York"])
def test_timezone_aware_price_dates_convert_without_crashing(timezone: str) -> None:
    naive = _prices(1_000_000, "USD")
    aware = naive.copy()
    aware["date"] = (aware["date"] + pd.Timedelta(hours=12)).dt.tz_localize(timezone)
    expected, expected_info = _component(naive, "USD", _fx(ingested_at="2026-08-01T00:00:00Z"))
    actual, actual_info = _component(aware, "USD", _fx(ingested_at="2026-08-01T00:00:00Z"))
    assert actual_info["avg_turnover_20"] == pytest.approx(1_000_000)
    assert actual_info == expected_info
    assert actual.raw_score == expected.raw_score
    # Berlin's local day has already rolled over; the cutoff must still be the UTC row day.
    boundary = _prices(1_000_000, "USD", count=1)
    boundary["date"] = pd.DatetimeIndex([pd.Timestamp("2026-10-09T23:30:00Z").tz_convert(timezone)])
    unavailable, info = _component(boundary, "USD", _fx(ingested_at="2026-10-10T00:00:00Z"))
    assert unavailable.raw_score is None
    assert "2026-10-09" in info["fx_unavailable_reason"]


@pytest.mark.parametrize("unknown", [None, pd.NA, "", "unknown"])
@pytest.mark.parametrize("currency", ["USD", "EUR"])
def test_every_turnover_row_requires_verified_currency(unknown: object, currency: str) -> None:
    prices = _prices(1_000_000, currency, currency_label=currency, count=20)
    verified = _price_liquidity_lookup(prices, fx_rates=_fx(ingested_at="2026-08-01T00:00:00Z"))["X"]
    assert verified["avg_turnover_20"] == pytest.approx(1_000_000)
    prices.loc[prices.index[1:], "currency"] = unknown
    info = _price_liquidity_lookup(prices, fx_rates=_fx(ingested_at="2026-08-01T00:00:00Z"))["X"]
    assert info["avg_turnover_20"] is None
    assert "unknown" in info["fx_unavailable_reason"].lower()
    assert _liquidity_component(info).raw_score is None
    # Authoritative configuration can supply missing row currency, without changing the amount.
    supplied = _price_liquidity_lookup(
        prices, currency_by_id={"X": currency}, fx_rates=_fx(ingested_at="2026-08-01T00:00:00Z")
    )["X"]
    assert supplied["avg_turnover_20"] == verified["avg_turnover_20"]
