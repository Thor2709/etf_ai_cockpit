"""Focused regression tests for issue #937 fundamentals semantics."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import MarketInputs, build_stock_evidence
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_sources as sources
from etf_cockpit.data.capital_efficiency import capital_efficiency_analysis
from etf_cockpit.data.stock_fundamentals import load_stock_config
from etf_cockpit.data.stock_research import profitability_analysis, valuation_analysis

UTC = timezone.utc
DECISION = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
CONFIG = load_stock_config()


def _fact(start: str | None, end: str, value: float, filed: str) -> dict[str, object]:
    row: dict[str, object] = {"end": end, "val": value, "filed": filed}
    if start is not None:
        row["start"] = start
    return row


def _sec_payload(*, facts: dict[str, object] | None = None) -> dict[str, object]:
    base: dict[str, object] = {
        "Revenues": {"units": {"USD": [_fact("2025-01-01", "2025-12-31", 500.0, "2026-02-10")]}},
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {"USD": [_fact("2025-01-01", "2025-12-31", 80.0, "2026-02-10")]}
        },
    }
    base.update(facts or {})
    return {"facts": {"us-gaap": base, "dei": {}}}


def _period(
    year: int,
    *,
    known_at: str | None = None,
    source: str = "sec_edgar",
    **overrides: float,
) -> sm.Period:
    values: dict[str, float] = {
        "revenue": 100.0 + year,
        "gross_profit": 40.0,
        "ebit": 20.0,
        "da": 5.0,
        "pretax_income": 18.0,
        "income_tax": 4.5,
        "net_income_parent": 12.0,
        "cfo": 25.0,
        "capex": 8.0,
        "dividends_paid": 2.0,
        "equity_parent": 100.0 + year,
        "minority_interest": 0.0,
        "ib_debt": 30.0,
        "lease_liabilities": 5.0,
        "cash_sti": 10.0,
        "shares_outstanding": 10.0,
    }
    values.update(overrides)
    known = datetime.fromisoformat(known_at or f"{year + 1}-02-15").replace(tzinfo=UTC)
    return sm.Period(date(year, 12, 31), "FY", known, "EUR", source, values)


def test_cash_only_sec_balance_keeps_cash_and_uses_a_covered_lower_bound() -> None:
    payload = _sec_payload(
        facts={
            "CashAndCashEquivalentsAtCarryingValue": {
                "units": {"USD": [_fact(None, "2025-12-31", 100.0, "2026-02-10")]}
            },
            "LongTermDebtNoncurrent": {"units": {"USD": [_fact(None, "2025-12-31", 120.0, "2026-02-10")]}},
            "LongTermDebtCurrent": {"units": {"USD": [_fact(None, "2025-12-31", 30.0, "2026-02-10")]}},
        }
    )
    row = next(r for r in sources.parse_edgar_companyfacts(payload, CONFIG, source_ref="test") if r["period_type"] == "FY")

    assert row["cash"] == 100.0
    assert "cash_sti" not in row  # missing STI is unknown, never zero-filled
    periods = store.periods_for("T", pd.DataFrame([{**row, "instrument_id": "T"}]), ["sec_edgar"])
    evidence = build_stock_evidence("T", periods, DECISION, MarketInputs(), None, CONFIG)
    net_debt = evidence.metrics["net_debt"]
    assert net_debt.value == 50.0
    assert "lower bound" in net_debt.formula and "short-term investments are unknown" in net_debt.formula


def test_intangible_only_capex_is_retained_as_partial_and_fcf_fails_closed() -> None:
    payload = _sec_payload(
        facts={
            "PaymentsToAcquireIntangibleAssets": {
                "units": {"USD": [_fact("2025-01-01", "2025-12-31", 20.0, "2026-02-10")]}
            }
        }
    )
    row = next(r for r in sources.parse_edgar_companyfacts(payload, CONFIG, source_ref="test") if r["period_type"] == "FY")

    assert row["capex_extra"] == 20.0
    assert "capex" not in row  # the total remains partial without the PPE leg
    period = store.periods_for("T", pd.DataFrame([{**row, "instrument_id": "T"}]), ["sec_edgar"])[0]
    evidence = build_stock_evidence("T", [period], DECISION, MarketInputs(), None, CONFIG)
    assert evidence.metrics["fcf"].status == sm.UNAVAILABLE
    assert "partial" in str(evidence.metrics["fcf"].reason)


def _research_statements() -> pd.DataFrame:
    metrics = {
        2024: {"net_income": 12.0, "equity": 55.0, "operating_income": 18.0, "debt": 40.0, "cash": 8.0, "income_before_tax": 24.0, "tax_expense": 6.0},
        2025: {"net_income": 15.0, "equity": 60.0, "operating_income": 22.0, "debt": 37.0, "cash": 10.0, "income_before_tax": 20.0, "tax_expense": 5.0},
        2026: {"net_income": 20.0, "equity": 68.0, "operating_income": 27.0, "debt": 35.0, "cash": 12.0, "income_before_tax": 18.0, "tax_expense": 4.5},
    }
    rows = []
    for year, period_values in metrics.items():
        for metric, value in period_values.items():
            rows.append(
                {
                    "instrument_id": "ACME",
                    "canonical_metric": metric,
                    "value": value,
                    "period_type": "annual",
                    "period_key": f"FY{year}",
                    "period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "source_id": f"filing-{year}",
                    "filed": f"{year + 1}-02-15",
                    "restatement_kind": "reported",
                }
            )
    return pd.DataFrame(rows)


def test_roe_roic_formula_parity_across_metrics_research_and_capital_efficiency() -> None:
    frame = _research_statements()
    research = profitability_analysis(frame, instrument_id="ACME", tax_rate=0.25)
    capital = capital_efficiency_analysis(frame, instrument_id="ACME", tax_rate=0.25, profitability_output=research)
    metrics_roe = sm.roe(20.0, 60.0, 68.0)
    metrics_roic = sm.roic(20.25, 87.0, 91.0)

    assert research["metrics"]["roe"]["value"] == pytest.approx(metrics_roe.value)
    assert research["metrics"]["roic"]["value"] == pytest.approx(metrics_roic.value)
    assert capital["reported"]["metrics"]["roic"]["value"] == pytest.approx(metrics_roic.value)
    assert research["metrics"]["roe"]["formula"] == metrics_roe.formula
    assert research["metrics"]["roic"]["formula"] == capital["reported"]["metrics"]["roic"]["formula"]


def test_stale_report_is_display_only_and_never_score_eligible() -> None:
    stale_periods = [
        _period(2023, known_at="2026-10-12", source="yfinance"),
        _period(2024, known_at="2026-10-12", source="yfinance"),
    ]
    evidence = build_stock_evidence("T", stale_periods, DECISION, MarketInputs(price=50.0, price_currency="EUR"), None, CONFIG)
    quality = evidence.components["stock_quality"]

    assert quality.score_10 is None
    assert quality.status == "stale"
    assert quality.freshness == "stale"
    assert quality.used_count == 0
    assert quality.input_count == 6
    assert "shown but not scored" in quality.why


def test_stale_metrics_do_not_inflate_quality_evidence() -> None:
    periods = [_period(year, known_at="2026-10-12", source="yfinance") for year in (2022, 2023, 2024)]
    evidence = build_stock_evidence("T", periods, DECISION, MarketInputs(price=50.0, price_currency="EUR"), None, CONFIG)
    quality = evidence.components["stock_quality"]

    assert quality.input_count == 6
    assert quality.used == ()
    assert all(item.score is None for item in quality.inputs)


def test_quality_component_exposes_the_two_of_six_case_without_claiming_solvency() -> None:
    periods = [
        sm.Period(
            date(year, 12, 31),
            "FY",
            datetime(year + 1, 2, 15, tzinfo=UTC),
            "EUR",
            "sec_edgar",
            {"revenue": 100.0 + (year - 2021) * 10.0, "net_income_parent": 12.0, "equity_parent": 100.0 + year},
        )
        for year in range(2022, 2026)
    ]
    quality = build_stock_evidence("T", periods, DECISION, MarketInputs(), None, CONFIG).components["stock_quality"]

    assert quality.input_count == 6
    assert quality.used_count == 2
    assert "2 of 6 inputs" in quality.why
    assert quality.status == "available"


@pytest.mark.parametrize("snapshot_shares", [20.0, 100.0], ids=["2-to-1-adr", "10-to-1-split"])
def test_share_count_disagreement_requires_reconciliation(snapshot_shares: float) -> None:
    periods = [_period(year, shares_outstanding=10.0) for year in (2022, 2023, 2024, 2025)]
    market = MarketInputs(
        price=50.0,
        price_currency="EUR",
        price_date=date(2026, 10, 11),
        shares_fallback=snapshot_shares,
        shares_fallback_known_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
    evidence = build_stock_evidence("T", periods, DECISION, market, None, CONFIG)

    assert evidence.metrics["market_cap"].status == sm.UNAVAILABLE
    assert evidence.metrics["market_cap"].value is None
    assert "reconcil" in str(evidence.metrics["market_cap"].reason).lower()
    assert evidence.metrics["pe"].status == sm.UNAVAILABLE


def test_unattributed_consolidated_income_is_unavailable_when_nci_exists() -> None:
    """P1-06, B102-N003 and B105-N001: consolidated earnings never stand in for parent income."""
    payload = _sec_payload(
        facts={
            "NetIncomeLoss": {"units": {"USD": [_fact("2025-01-01", "2025-12-31", 100.0, "2026-02-10")]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {"USD": [_fact("2025-01-01", "2025-12-31", 10.0, "2026-02-10")]}
            },
            "MinorityInterest": {"units": {"USD": [_fact(None, "2025-12-31", 20.0, "2026-02-10")]}},
        }
    )
    row = next(r for r in sources.parse_edgar_companyfacts(payload, CONFIG, source_ref="test") if r["period_type"] == "FY")

    assert "net_income_parent" not in row
    periods = store.periods_for("T", pd.DataFrame([{**row, "instrument_id": "T"}]), ["sec_edgar"])
    assert all(not period.has("net_income_parent") for period in periods), [period.values for period in periods]
    evidence = build_stock_evidence("T", periods, DECISION, MarketInputs(), None, CONFIG)
    assert evidence.metrics["net_income"].status == sm.UNAVAILABLE
    assert "non-controlling interests" in str(evidence.metrics["net_income"].reason)
    assert evidence.metrics["pe"].status == sm.UNAVAILABLE
    assert evidence.metrics["fcf_conversion"].status == sm.UNAVAILABLE
    assert "non-controlling interests" in str(evidence.metrics["fcf_conversion"].reason)


def test_yahoo_acquisition_cannot_be_used_for_a_pre_acquisition_decision() -> None:
    acquired = sm.Period(
        date(2023, 12, 31),
        "FY",
        datetime(2026, 10, 12, tzinfo=UTC),
        "USD",
        "yfinance",
        {"revenue": 500.0},
    )
    decision = datetime(2024, 1, 31, tzinfo=UTC)

    assert sm.known_periods([acquired], decision) == []


def test_diluted_weighted_average_shares_do_not_replace_point_in_time_shares() -> None:
    statements = pd.DataFrame(
        [
            {"instrument_id": "ACME", "canonical_metric": "free_cash_flow", "value": 100.0, "period_type": "annual", "period_key": "FY2025", "period_end": "2025-12-31", "fiscal_year": 2025, "source_id": "filing-2025", "filed": "2026-02-15", "restatement_kind": "reported"},
            {"instrument_id": "ACME", "canonical_metric": "diluted_shares_outstanding", "value": 15.0, "period_type": "annual", "period_key": "FY2025", "period_end": "2025-12-31", "fiscal_year": 2025, "source_id": "filing-2025", "filed": "2026-02-15", "restatement_kind": "reported"},
        ]
    )
    report = valuation_analysis(
        statements,
        instrument_id="ACME",
        market_inputs={"shares_outstanding": 10.0, "market_cap": 1000.0, "net_debt": 0.0},
        assumptions={
            "discount_rate": 0.10,
            "terminal_growth": 0.02,
            "forecast_years": 3,
            "scenarios": {"base": {"growth": 0.05}},
        },
    )
    base = report["intrinsic_value"]["scenarios"]["base"]

    assert base["per_share"] == pytest.approx(base["equity_value"] / 10.0)


def test_yahoo_lease_exceeding_total_debt_does_not_create_negative_gross_debt() -> None:
    balance = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [10.0, 20.0]},
        index=["Total Debt", "Capital Lease Obligations"],
    )
    empty = pd.DataFrame()
    ticker = SimpleNamespace(
        info={"financialCurrency": "EUR", "currency": "EUR", "quoteType": "EQUITY", "longName": "Test"},
        income_stmt=empty,
        cashflow=empty,
        balance_sheet=balance,
        quarterly_income_stmt=empty,
        quarterly_cashflow=empty,
        quarterly_balance_sheet=empty,
        eps_trend=empty,
        eps_revisions=empty,
    )
    result = sources.fetch_yfinance("T", CONFIG, now=DECISION, ticker_factory=lambda _symbol: ticker)

    assert result.rows
    assert "ib_debt" not in result.rows[0]


def test_sparse_newer_statement_row_keeps_previous_cash_flow_evidence() -> None:
    base = {column: None for column in store.PERIOD_COLUMNS}
    base.update(
        instrument_id="T",
        period_end="2025-12-31",
        period_type="FY",
        fiscal_year=2025,
        currency="USD",
        source="sec_edgar",
        source_ref="filing-1",
        known_at="2026-02-15T00:00:00+00:00",
        revenue=500.0,
        cfo=80.0,
        capex=20.0,
    )
    sparse = {**base, "source_ref": "filing-2", "known_at": "2026-03-15T00:00:00+00:00", "revenue": 520.0, "cfo": None, "capex": None}
    frame = pd.DataFrame([base, sparse], columns=store.PERIOD_COLUMNS)

    periods = store.periods_for("T", frame, ["sec_edgar"])
    latest = periods[-1]
    assert latest.known_at == datetime(2026, 3, 15, tzinfo=UTC)
    assert latest.values["revenue"] == 520.0
    assert latest.values["cfo"] == 80.0
    assert latest.values["capex"] == 20.0
