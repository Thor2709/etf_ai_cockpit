"""Offline tests for the stock source parsers: yfinance statements and SEC EDGAR companyfacts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.data import stock_sources as src
from etf_cockpit.data.stock_fundamentals import load_stock_config

CONFIG = load_stock_config()
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def _frame(columns: list[str], rows: dict[str, list[float]]) -> pd.DataFrame:
    """Statement frame like yfinance: row labels as index, period-end timestamps as columns."""

    return pd.DataFrame({pd.Timestamp(c): [rows[label][i] for label in rows] for i, c in enumerate(columns)}, index=list(rows))


def _ticker(info: dict, **frames: pd.DataFrame) -> SimpleNamespace:
    empty = pd.DataFrame()
    return SimpleNamespace(
        info=info,
        income_stmt=frames.get("income", empty),
        cashflow=frames.get("cash", empty),
        balance_sheet=frames.get("balance", empty),
        quarterly_income_stmt=empty,
        quarterly_cashflow=empty,
        quarterly_balance_sheet=empty,
        eps_trend=pd.DataFrame({"current": [4.4], "90daysAgo": [4.0]}, index=["0y"]),
        eps_revisions=pd.DataFrame({"upLast30days": [5.0], "downLast30days": [1.0]}, index=["0y"]),
    )


def test_yfinance_rows_use_positive_outflows_and_split_leases_from_debt() -> None:
    income = _frame(["2025-12-31"], {"Total Revenue": [1000.0], "Operating Income": [150.0], "Net Income Common Stockholders": [90.0]})
    cash = _frame(["2025-12-31"], {"Operating Cash Flow": [200.0], "Capital Expenditure": [-60.0], "Cash Dividends Paid": [-30.0]})
    balance = _frame(["2025-12-31"], {"Total Debt": [400.0], "Capital Lease Obligations": [50.0], "Stockholders Equity": [700.0]})
    info = {"financialCurrency": "EUR", "currency": "GBp", "quoteType": "EQUITY", "longName": "Test plc", "sharesOutstanding": 10.0}
    result = src.fetch_yfinance("T.L", CONFIG, now=NOW, ticker_factory=lambda _s: _ticker(info, income=income, cash=cash, balance=balance))
    row = result.rows[0]
    assert (row["capex"], row["dividends_paid"]) == (60.0, 30.0)
    assert (row["ib_debt"], row["lease_liabilities"]) == (350.0, 50.0)  # total debt includes leases
    assert row["currency"] == "EUR" and row["known_at"] == NOW.isoformat()  # known when fetched, never earlier
    assert result.snapshot["quote_currency"] == "GBp" and result.snapshot["eps_current"] == 4.4
    assert result.snapshot["revisions_up_30d"] == 5.0


def test_yfinance_missing_symbol_and_empty_statements_state_the_reason() -> None:
    def broken(_symbol: str):
        raise RuntimeError("HTTP Error 404: Quote not found")

    missing = src.fetch_yfinance("GONE.AS", CONFIG, now=NOW, ticker_factory=broken)
    assert missing.status == "not_found" and "GONE.AS" in missing.reason and missing.rows == []
    profile_only = src.fetch_yfinance("X.PA", CONFIG, now=NOW, ticker_factory=lambda _s: _ticker({"quoteType": "EQUITY", "longName": "X"}))
    assert profile_only.status == "no_statements" and "no income statement" in profile_only.reason
    unknown = src.fetch_yfinance("Y", CONFIG, now=NOW, ticker_factory=lambda _s: _ticker({}))
    assert unknown.status == "not_found" and "delisted" in unknown.reason


def _fact(start: str | None, end: str, val: float, filed: str) -> dict:
    entry = {"end": end, "val": val, "filed": filed}
    if start:
        entry["start"] = start
    return entry


def _companyfacts() -> dict:
    revenue = [
        _fact("2025-01-01", "2025-03-31", 100.0, "2025-05-01"),
        _fact("2025-01-01", "2025-06-30", 210.0, "2025-08-01"),
        _fact("2025-01-01", "2025-09-30", 333.0, "2025-11-01"),
        _fact("2025-01-01", "2025-12-31", 460.0, "2026-02-10"),
        _fact("2025-01-01", "2025-12-31", 470.0, "2027-02-01"),  # later restatement: must not replace what was known
    ]
    cfo = [
        _fact("2025-01-01", "2025-03-31", 30.0, "2025-05-01"),
        _fact("2025-01-01", "2025-06-30", 70.0, "2025-08-01"),
        _fact("2025-01-01", "2025-09-30", 120.0, "2025-11-01"),
        _fact("2025-01-01", "2025-12-31", 180.0, "2026-02-10"),
    ]
    equity = [_fact(None, d, v, f) for d, v, f in (("2025-03-31", 500.0, "2025-05-01"), ("2025-12-31", 560.0, "2026-02-10"))]
    return {
        "entityName": "Test Inc",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": revenue}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": cfo}},
                "StockholdersEquity": {"units": {"USD": equity}},
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [_fact(None, "2025-12-31", 40.0, "2026-02-10")]}},
                "ShortTermInvestments": {"units": {"USD": [_fact(None, "2025-12-31", 15.0, "2026-02-10")]}},
                "LongTermDebtNoncurrent": {"units": {"USD": [_fact(None, "2025-12-31", 90.0, "2026-02-10")]}},
                "LongTermDebtCurrent": {"units": {"USD": [_fact(None, "2025-12-31", 10.0, "2026-02-10")]}},
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [_fact(None, "2026-02-01", 1000.0, "2026-02-10")]}}},
        },
    }


def test_edgar_differences_cumulative_flows_into_discrete_quarters_as_originally_filed() -> None:
    rows = src.parse_edgar_companyfacts(_companyfacts(), CONFIG, source_ref="test")
    by_key = {(r["period_end"], r["period_type"]): r for r in rows}
    assert by_key[("2025-03-31", "Q")]["revenue"] == 100.0
    assert by_key[("2025-06-30", "Q")]["revenue"] == 110.0  # H1 210 - Q1 100
    assert by_key[("2025-09-30", "Q")]["revenue"] == 123.0  # 9M 333 - H1 210
    assert by_key[("2025-12-31", "Q")]["revenue"] == 127.0  # FY 460 - 9M 333
    assert by_key[("2025-12-31", "FY")]["revenue"] == 460.0  # the 2027 restatement (470) is not used
    assert by_key[("2025-06-30", "Q")]["known_at"] == "2025-08-01"  # filing date of the later of the two facts
    assert by_key[("2025-12-31", "Q")]["cfo"] == 60.0 and by_key[("2025-09-30", "Q")]["cfo"] == 50.0


def test_edgar_balance_items_sum_parts_and_attach_cover_page_shares() -> None:
    rows = src.parse_edgar_companyfacts(_companyfacts(), CONFIG, source_ref="test")
    fy = next(r for r in rows if r["period_end"] == "2025-12-31" and r["period_type"] == "FY")
    assert fy["cash_sti"] == 55.0 and fy["ib_debt"] == 100.0 and fy["equity_parent"] == 560.0
    assert fy["shares_outstanding"] == 1000.0 and fy["currency"] == "USD" and fy["source"] == "sec_edgar"


def test_edgar_cash_and_investments_are_known_at_the_later_filing() -> None:
    payload = _companyfacts()
    gaap = payload["facts"]["us-gaap"]
    gaap["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"][0]["filed"] = "2026-02-10"
    gaap["ShortTermInvestments"]["units"]["USD"][0]["filed"] = "2026-03-10"
    fy = next(row for row in src.parse_edgar_companyfacts(payload, CONFIG, source_ref="test") if row["period_type"] == "FY")
    assert fy["cash_sti"] == 55.0
    assert fy["known_at"] == "2026-03-10"


def test_edgar_keeps_each_field_currency_instead_of_labeling_every_value_with_one_unit() -> None:
    payload = _companyfacts()
    payload["facts"]["us-gaap"]["NetIncomeLoss"] = {
        "units": {"EUR": [_fact("2025-01-01", "2025-12-31", 90.0, "2026-02-10")]}
    }
    fy = next(row for row in src.parse_edgar_companyfacts(payload, CONFIG, source_ref="test") if row["period_type"] == "FY")
    assert fy["revenue_currency"] == "USD" and fy["net_income_parent_currency"] == "EUR"


def test_edgar_debt_adds_disjoint_borrowings_and_normalizes_lease_inclusive_total() -> None:
    payload = _companyfacts()
    gaap = payload["facts"]["us-gaap"]
    concepts = {**CONFIG["sec_edgar_concepts"], "debt_total": ["LongTermDebt"], "debt_parts": ["ShortTermBorrowings"]}
    debt_config = {**CONFIG, "sec_edgar_concepts": concepts}
    gaap["LongTermDebt"] = {"units": {"USD": [_fact(None, "2025-12-31", 100.0, "2026-02-10")]}}
    gaap["ShortTermBorrowings"] = {"units": {"USD": [_fact(None, "2025-12-31", 50.0, "2026-02-10")]}}
    row = next(row for row in src.parse_edgar_companyfacts(payload, debt_config, source_ref="test") if row["period_type"] == "FY")
    assert row["ib_debt"] == 150.0

    lease_payload = _companyfacts()
    lease_gaap = lease_payload["facts"]["us-gaap"]
    lease_config = {**CONFIG, "sec_edgar_concepts": {**CONFIG["sec_edgar_concepts"], "debt_total": ["DebtAndCapitalLeaseObligations"]}}
    lease_gaap["DebtAndCapitalLeaseObligations"] = {"units": {"USD": [_fact(None, "2025-12-31", 125.0, "2026-02-10")]}}
    lease_gaap["FinanceLeaseLiabilityNoncurrent"] = {"units": {"USD": [_fact(None, "2025-12-31", 25.0, "2026-02-10")]}}
    lease_gaap["FinanceLeaseLiabilityCurrent"] = {"units": {"USD": [_fact(None, "2025-12-31", 0.0, "2026-02-10")]}}
    lease_row = next(row for row in src.parse_edgar_companyfacts(lease_payload, lease_config, source_ref="test") if row["period_type"] == "FY")
    assert lease_row["ib_debt"] == 100.0 and lease_row["lease_liabilities"] == 25.0


def test_edgar_without_user_agent_is_unavailable_with_the_exact_step() -> None:
    result = src.fetch_edgar("0000789019", CONFIG, user_agent=None)
    assert result.status == "unavailable" and "ETF_COCKPIT_SEC_EDGAR_USER_AGENT" in result.reason
    ok = src.fetch_edgar("789019", CONFIG, user_agent="Tester tester@example.org", fetch=lambda _u, _a: _companyfacts(), sleep=lambda _s: None)
    assert ok.status == "ok" and ok.rows
    assert src.sec_user_agent(CONFIG, {}) is None
    assert src.resolve_cik("SU.PA", "ua") is None  # exchange-suffixed symbols have no CIK
    tickers = {"0": {"cik_str": 789019, "ticker": "MSFT"}}
    assert src.resolve_cik("msft", "ua", fetch=lambda _u, _a: tickers) == "0000789019"
