"""Statement FX fallback uses only direct canonical quotes known at the decision."""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import build_stock_evidence
from etf_cockpit.analysis.stock_universe import market_inputs
from etf_cockpit.data import stock_fundamentals as store


DECISION = datetime(2025, 10, 1, 12, tzinfo=timezone.utc)
PRICE_DATE = date(2025, 9, 30)


def _canonical(**overrides):
    return {
        "as_of_date": "2025-09-30", "base_currency": "GBP", "quote_currency": "EUR",
        "pair": "GBP/EUR", "rate": 1.17, "source": "yfinance",
        "ingested_at": "2026-10-21T12:00:00+00:00",
        "available_at": "2025-10-01T12:00:00+00:00",
        "availability_basis": "market_close_unrevised", **overrides,
    }


def _write_fx(root, canonical, snapshot=()):
    clean = root / "data" / "clean"
    clean.mkdir(parents=True, exist_ok=True)
    if canonical is not None:
        pd.DataFrame(canonical).to_parquet(clean / "fx.parquet", index=False)
    if snapshot:
        pd.DataFrame(snapshot).to_parquet(clean / "stock_fx.parquet", index=False)


def _cbuk_evidence(root):
    config = store.load_stock_config()
    fx = store.read_fx(root)
    prices = pd.DataFrame({
        "date": pd.to_datetime(["2025-09-30"]), "close": [50.0], "currency": ["GBP"],
    })
    market = market_inputs(prices, None, "EUR", DECISION, fx, config)
    period = sm.Period(
        date(2024, 12, 31), "FY", datetime(2025, 3, 1, tzinfo=timezone.utc),
        "EUR", "esef", {"shares_outstanding": 10.0, "net_income_parent": 100.0},
        field_sources={"shares_outstanding": "esef_reported"},
    )
    return market, build_stock_evidence("CBUK", [period], DECISION, market, None, config)


@pytest.mark.parametrize("snapshot_case", ["absent", "not_yet_known", "stale", "preferred"])
def test_cbuk_gbp_eur_resolves_via_canonical_fx(tmp_path, snapshot_case):
    snapshot = []
    if snapshot_case != "absent":
        snapshot = [{
            "pair": "GBPEUR", "date": "2025-09-29", "rate": 1.15,
            "known_at": "2025-09-30T00:00:00+00:00",
        }]
        if snapshot_case == "not_yet_known":
            snapshot[0]["known_at"] = "2025-10-01T12:00:01+00:00"
        elif snapshot_case == "stale":
            snapshot[0]["date"] = "2025-09-22"
    _write_fx(tmp_path, [
        _canonical(as_of_date="2025-09-29", rate=1.16),
        _canonical(),
        _canonical(rate=9.0, available_at="2025-10-01T12:00:01+00:00"),
        _canonical(as_of_date="2025-10-01", rate=8.0),
    ], snapshot)
    expected = 1.15 if snapshot_case == "preferred" else 1.17
    expected_date = "2025-09-29" if snapshot_case == "preferred" else "2025-09-30"
    market, evidence = _cbuk_evidence(tmp_path)
    assert market.fx_to_reporting == expected
    assert store.fx_rate("GBPEUR", PRICE_DATE, store.read_fx(tmp_path), decision_time=DECISION) == (expected, expected_date)
    assert evidence.metrics["market_cap"].status == sm.OK
    assert evidence.metrics["market_cap"].value == pytest.approx(50.0 * expected * 10.0)
    assert evidence.metrics["pe"].value == pytest.approx(50.0 * expected * 10.0 / 100.0)
    # The refresh reader must never promote canonical observations into stock_fx.
    snapshot_only = store.read_fx(tmp_path, include_canonical=False)
    assert len(snapshot_only) == len(snapshot)
    assert "_canonical_fx" not in snapshot_only.columns
    if snapshot_case == "absent":
        assert store.fx_rate("GBPEUR", PRICE_DATE, store.read_fx(tmp_path)) == (None, None)


@pytest.mark.parametrize("overrides", [
    {"as_of_date": "2025-10-01"},  # known at decision, but later than the price date
    {"available_at": "2025-10-01T12:00:01+00:00"},
    {"available_at": None},
    {"available_at": "invalid"},
    {"as_of_date": "2025-09-22"},  # preserve the existing seven-day freshness guard
    {"rate": float("nan")},
    {"rate": 0.0},
    {"rate": -1.0},
])
def test_future_dated_or_unavailable_rate_rejected(tmp_path, overrides):
    _write_fx(tmp_path, [_canonical(**overrides)])
    market, evidence = _cbuk_evidence(tmp_path)
    assert market.fx_to_reporting is None
    assert evidence.metrics["market_cap"].status == sm.UNAVAILABLE
    assert "currency_mismatch" in evidence.metrics["market_cap"].reason


@pytest.mark.parametrize("canonical", [
    None,
    [],
    [{key: value for key, value in _canonical().items() if key != "available_at"}],
    [_canonical(pair="EUR/GBP", base_currency="EUR", quote_currency="GBP", rate=0.85)],
    [
        _canonical(pair="GBP/USD", quote_currency="USD", rate=1.3),
        _canonical(pair="USD/EUR", base_currency="USD", rate=0.9),
    ],
])
def test_no_rate_anywhere_still_currency_mismatch(tmp_path, canonical):
    _write_fx(tmp_path, canonical)
    market, evidence = _cbuk_evidence(tmp_path)
    assert market.fx_to_reporting is None
    assert evidence.metrics["market_cap"].status == sm.UNAVAILABLE
    assert evidence.metrics["market_cap"].value is None
    assert "currency_mismatch" in evidence.metrics["market_cap"].reason
    assert "currency_mismatch" in evidence.metrics["pe"].reason
