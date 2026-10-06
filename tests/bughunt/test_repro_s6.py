from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from etf_cockpit.analysis.fixed_income_analytics import (
    ContractualCashFlow,
    FixedIncomeAnalyticsError,
    FixedIncomeValuationInput,
    calculate_fixed_income_analytics,
)
from etf_cockpit.data import bond_analytics_store, euronext_listing, sample_data, yfinance_provider
from etf_cockpit.data.bond_analytics_store import BondAnalyticsRecord
from etf_cockpit.data.universe_membership import CaptureStatus
from etf_cockpit.data.fixed_income_terms import (
    FixedIncomeSecurityTerms,
    FixedIncomeTermsError,
    SettlementConvention,
    generate_contractual_schedules,
)
from etf_cockpit.data.fx_data import build_fx_rate_snapshot, validate_fx_rates
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.market_calendar import (
    BusinessDayConvention,
    DayCountConvention,
    SettlementCalendarEvidence,
)
from etf_cockpit.data.news_context import (
    NewsItem,
    _clean_row,
    build_news_macro_contradictions,
    validate_news_item,
)
from etf_cockpit.data.trade_candidate_analysis import analyse_candidate_prices


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S6-01: Missing sample prices overwrites existing portfolio")
def test_s6_01_missing_prices_preserves_holdings(monkeypatch):
    writes = []
    monkeypatch.setattr(Path, "exists", lambda path: path.name != "sample_prices.csv")
    monkeypatch.setattr(sample_data, "generate_sample_prices", lambda config: pd.DataFrame({"close": [10]}))
    monkeypatch.setattr(sample_data, "generate_sample_holdings", lambda config, prices: pd.DataFrame({"shares": [1]}))
    monkeypatch.setattr(sample_data, "ensure_project_dirs", lambda: None)
    monkeypatch.setattr(pd.DataFrame, "to_csv", lambda self, path, **kwargs: writes.append(Path(path).name))
    sample_data.ensure_sample_files(object(), force=False)
    assert "current_holdings.csv" not in writes


def test_s6_02_inconsistent_four_currency_cycle_is_rejected():
    rates = pd.DataFrame({
        "as_of_date": ["2026-10-05"] * 4,
        "ingested_at": ["2026-10-05T08:00:00Z"] * 4,
        "pair": ["EUR/USD", "USD/GBP", "GBP/JPY", "EUR/JPY"],
        "rate": [1.1, 0.8, 200.0, 180.0],
    })
    assert not validate_fx_rates(rates, today=date(2026, 10, 5)).ok
    assert not build_fx_rate_snapshot(rates, decision_time="2026-10-05T12:00:00Z").available


def test_s6_03_yahoo_preserves_quote_currency(monkeypatch):
    frame = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Adj Close": [100.0], "Volume": [10.0]},
        index=pd.to_datetime(["2026-10-02"]),
    )
    monkeypatch.setattr(yfinance_provider, "_import_yfinance", lambda: SimpleNamespace(download=lambda *args, **kwargs: frame))
    provider = yfinance_provider.YFinanceProvider(default_currency="EUR", instrument_metadata={"US": {"currency": "USD"}})
    output = provider._download_one(symbol="AAPL", etf_id="US", start_date=date(2026, 10, 1), end_date=date(2026, 10, 5))
    assert output.iloc[0]["currency"] == "USD"


@pytest.mark.xfail(strict=True, raises=FixedIncomeAnalyticsError, reason="S6-04: Failed database commit invalidates persisted analytics")
def test_s6_04_failed_commit_preserves_previous_projection(tmp_path, monkeypatch):
    calculated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valuation = FixedIncomeValuationInput(
        "B", "v", "USD", D("1000"), date(2026, 1, 1), date(2027, 1, 1), D(".05"), 2,
        DayCountConvention.THIRTY_360_US,
        (
            ContractualCashFlow(date(2026, 7, 1), D("25"), "coupon", "v", date(2026, 1, 1), date(2026, 7, 1)),
            ContractualCashFlow(date(2027, 1, 1), D("25"), "coupon", "v", date(2026, 7, 1), date(2027, 1, 1)),
            ContractualCashFlow(date(2027, 1, 1), D("1000"), "redemption", "v"),
        ),
        calculated_at,
        yield_to_maturity=D(".05"),
    )
    result = calculate_fixed_income_analytics(valuation)
    path = tmp_path / "bond.parquet"
    bond_analytics_store.write_bond_analytics(path, [BondAnalyticsRecord("old", calculated_at, valuation, result)])

    @contextmanager
    def fail_commit(store):
        store.connection.execute("BEGIN IMMEDIATE")
        try:
            yield store.connection
            store.connection.rollback()
            raise OSError("commit failure")
        except Exception:
            store.connection.rollback()
            raise

    monkeypatch.setattr(TransactionalStore, "transaction", fail_commit)
    with pytest.raises(OSError, match="commit failure"):
        bond_analytics_store.write_bond_analytics(path, [BondAnalyticsRecord("new", calculated_at, valuation, result)])
    assert bond_analytics_store.read_bond_analytics(path)[0]["record_id"] == "old"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S6-05: Malformed listing rows close valid memberships")
def test_s6_05_malformed_member_prevents_complete_capture(monkeypatch):
    config = replace(euronext_listing.load_euronext_listing_config(), minimum_rows=1)
    payload = (
        b"Name;ISIN;Symbol;Market;Currency\n05 Oct 2026\nx\nx\n"
        b"A;US0378331005;AAPL;Euronext Growth Oslo;NOK\n"
        b"B;US5949181045;;Euronext Growth Oslo;NOK\n"
    )
    recorder = Mock(return_value=CaptureStatus("recorded", config.scope))
    monkeypatch.setattr(euronext_listing, "load_euronext_listing_config", lambda *args: config)
    monkeypatch.setattr(euronext_listing, "record_listing_capture", recorder)
    result = euronext_listing.capture_euronext_oslo_listing(
        transport=lambda *args: payload,
        clock=lambda: datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
    )
    assert result.status == "error"
    recorder.assert_not_called()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S6-06: Ineligible news bypasses cutoff validation")
def test_s6_06_rejected_news_cannot_flag_cutoff_contradiction():
    cutoff = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    item = NewsItem(
        news_id="N", instrument_id="US", provider="local", headline="Shares rise",
        published_at="2026-10-05T08:00:00Z", ingested_at="2026-10-05T09:00:00Z",
        url="https://example.invalid/n", instrument_mapping_method="id",
        available_at_decision_time=True, revised=True,
    )
    validation = validate_news_item(item, cutoff)
    assert not validation.backtest_eligible
    news = pd.DataFrame([_clean_row(item, validation, "a" * 64, Path("raw.json"))])
    fundamentals = pd.DataFrame([{
        "instrument_id": "US", "as_of": "2026-10-05T10:00:00Z",
        "available_at": "2026-10-05T10:00:00Z", "quality_score": 2,
    }])
    results = build_news_macro_contradictions(news, fundamentals=fundamentals, cutoff=cutoff)
    result = next(row for row in results if row["rule"] == "positive_news_weak_fundamentals")
    assert result["status"] != "flagged"


def test_s6_07_foreign_candidate_requires_fx_for_eur_amounts():
    candidates = pd.DataFrame([{"instrument_id": "US", "currency": "USD", "shares": 10, "yahoo_symbol": "AAPL"}])
    prices = pd.DataFrame({
        "etf_id": ["US"] * 3, "currency": ["USD"] * 3,
        "date": pd.date_range("2026-10-01", periods=3), "close": [100.0] * 3,
        "adjusted_close": [100.0] * 3, "volume": [20.0] * 3,
    })
    result = analyse_candidate_prices(candidates, prices).iloc[0]
    assert pd.isna(result["trade_value_eur"])
    assert pd.isna(result["median_turnover_60d_eur"])


@pytest.mark.xfail(strict=True, raises=FixedIncomeTermsError, reason="S6-08: Coupon month subtraction rejects regular month-end bonds")
def test_s6_08_regular_month_end_coupon_schedule():
    timestamp = datetime(2024, 8, 31, tzinfo=timezone.utc)
    calendar = SettlementCalendarEvidence(
        "B:settlement", "B", "XNYS", "America/New_York", "official:calendar", "a" * 64,
        date(2000, 1, 1), datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    terms = FixedIncomeSecurityTerms(
        "B", "ISSUER", "government_bond", "USD", date(2024, 8, 31), date(2026, 8, 31),
        D("1000"), D("1000"), D("1000"), "fixed_rate", D(".05"), 2,
        DayCountConvention.THIRTY_360_US,
        SettlementConvention(2, BusinessDayConvention.MODIFIED_FOLLOWING, calendar),
        "official:prospectus", "a" * 64, timestamp, timestamp, timestamp,
    )
    assert generate_contractual_schedules(terms, decision_time=timestamp)
