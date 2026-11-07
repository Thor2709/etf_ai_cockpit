"""Offline FUND audit regressions: original filings, matched dates and fail-closed values."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import MarketInputs, build_stock_evidence
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_sources as sources
from etf_cockpit.data.sec_pit_facts import select_facts


CONFIG = store.load_stock_config()
DECISION = datetime(2026, 4, 1, 12, tzinfo=timezone.utc)


def period(year, **overrides):
    values = dict(revenue=1000.0, ebit=200.0, da=60.0, pretax_income=180.0,
                  income_tax=45.0, net_income_parent=100.0, equity_parent=900.0,
                  ib_debt=300.0, lease_liabilities=50.0, cash_sti=150.0,
                  minority_interest=0.0, shares_outstanding=10.0)
    values.update(overrides)
    return sm.Period(date(year, 12, 31), "FY",
                     datetime(year + 1, 2, 15, tzinfo=timezone.utc), "EUR", "sec_edgar", values,
                     field_sources={"shares_outstanding": "sec_dei"})


def evidence(periods, *, config=CONFIG, decision=DECISION, market=None, **kwargs):
    market = market or MarketInputs(price=50.0, price_currency="EUR", price_date=decision.date())
    return build_stock_evidence("T", periods, decision, market, None, config, **kwargs)


def fact(value, *, end="2025-12-31", filed="2026-02-10", start=None):
    return {"end": end, "filed": filed, "val": value, **({"start": start} if start else {})}


def concept(*facts, unit="EUR"):
    return {"units": {unit: list(facts)}}


def test_preselected_restatement_keeps_original_and_filing_known_at():
    fixtures = Path(__file__).parent / "fixtures" / "univ1_sp500"
    payload = json.loads((fixtures / "CIK9000000001.json").read_text(encoding="utf-8"))
    submissions = json.loads((fixtures / "submissions_9000000001.json").read_text(encoding="utf-8"))
    specs = {"us-gaap:Revenues": {"unit": "USD", "kind": "duration"}}
    vintages = []
    for stamp, expected in (("2021-02-20T05:00:00+00:00", 100),
                            ("2021-05-03T16:00:00+00:00", 110)):
        selected = select_facts(payload, stamp, specs=specs, submissions=submissions, derive_q4=False)
        annual = next(item for item in selected if item["fp"] == "FY")
        assert annual["known_at"] == stamp and annual["val"] == expected
        visible = {"facts": {"us-gaap": {"Revenues": concept(
            *({key: item[key] for key in ("start", "end", "filed", "accn", "fp", "val")}
              for item in selected), unit="USD")}}}
        mapped = sources.parse_edgar_companyfacts(
            visible, CONFIG, source_ref=str(fixtures / "CIK9000000001.json"), preselected_vintage=True)
        fy = next(row for row in mapped if row["period_type"] == "FY")
        assert fy["revenue"] == expected
        vintages.append({**fy, "instrument_id": "synthetic-instrument-a", "known_at": stamp, "available_at": stamp})

    frame = pd.DataFrame(vintages, columns=store.PERIOD_COLUMNS)
    periods = store.periods_for("synthetic-instrument-a", frame, ["sec_edgar"])
    assert [p.values["revenue"] for p in periods] == [100, 110]
    assert [p.known_at.isoformat() for p in periods] == frame["known_at"].tolist()
    for decision, expected in (("2021-02-20T04:59:59+00:00", None),
                               ("2021-03-01T12:00:00+00:00", 100),
                               ("2021-05-03T15:59:59+00:00", 100),
                               ("2021-05-03T16:00:00+00:00", 110),
                               ("2021-06-01T12:00:00+00:00", 110)):
        known = sm.known_periods(periods, datetime.fromisoformat(decision))
        assert (known[-1].values["revenue"] if known else None) == expected


def test_r1_f1_roic_uses_reported_cash_without_inventing_short_term_investments():
    periods = []
    for year in (2024, 2025):
        p = period(year)
        values = {k: v for k, v in p.values.items() if k != "cash_sti"}
        periods.append(replace(p, values={**values, "cash": 150.0}))
    ev = evidence(periods)
    assert ev.metrics["roic"].value == pytest.approx(150.0 / 1100.0)
    assert "cash only" in ev.metrics["roic"].reason
    assert ev.metrics["net_debt"].value == 200.0
    blocked = replace(periods[-1], value_status={"cash_sti": "conflicted"})
    assert not evidence([periods[0], blocked]).metrics["roic"].available
    missing = replace(periods[-1], values={k: v for k, v in periods[-1].values.items() if k != "cash"})
    assert not evidence([periods[0], missing]).metrics["roic"].available


def test_r1_f2_earliest_instant_concept_wins_and_late_comparatives_do_not_delay():
    payload = {"facts": {"us-gaap": {
        "Revenues": concept(fact(1000.0, start="2025-01-01")),
        "CashAndCashEquivalentsAtCarryingValue": concept(fact(80.0, filed="2026-04-01")),
        "ShortTermInvestments": concept(fact(20.0)),
        "StockholdersEquity": concept(fact(900.0, filed="2027-02-10")),
        "GrossProfit": concept(fact(400.0, start="2025-01-01", filed="2027-02-10")),
        "LongTermDebt": concept(fact(120.0, filed="2026-04-01")),
        "DebtAndCapitalLeaseObligations": concept(fact(100.0)),
    }}}
    cfg = deepcopy(CONFIG)
    cfg["sec_edgar_concepts"]["cash"] = ["CashAndCashEquivalentsAtCarryingValue", "ShortTermInvestments"]
    cfg["sec_edgar_concepts"]["short_term_investments"] = []
    rows = sources.parse_edgar_companyfacts(payload, cfg, source_ref="fixture")
    fy = next(row for row in rows if row["period_type"] == "FY")
    assert fy["cash"] == 20.0 and fy["known_at"] == "2026-02-10"
    assert fy["ib_debt"] == 100.0
    assert "equity_parent" not in fy and "gross_profit" not in fy
    # The original period remains visible through the real storage merge path.
    frame = pd.DataFrame([{**row, "instrument_id": "T"} for row in rows], columns=store.PERIOD_COLUMNS)
    visible = sm.known_periods(store.periods_for("T", frame, ["sec_edgar"]), DECISION)
    assert any(p.period_type == "FY" and p.values["revenue"] == 1000.0 for p in visible)
    # A quick subsequent filing can carry comparatives within the 120-day cap.
    quarterly = {"facts": {"us-gaap": {
        "Revenues": concept(fact(100.0, start="2025-01-01", end="2025-03-31", filed="2025-05-01"),
                            fact(210.0, start="2025-01-01", end="2025-06-30", filed="2025-07-28")),
        "StockholdersEquity": concept(fact(900.0, end="2025-03-31", filed="2025-07-28")),
    }}}
    first = next(row for row in sources.parse_edgar_companyfacts(quarterly, CONFIG, source_ref="fixture")
                 if row["period_end"] == "2025-03-31")
    assert first["known_at"] == "2025-05-01" and "equity_parent" not in first


def test_r1_f5_negative_profitability_scores_remain_zero_after_shrinkage():
    cohorts = {"sector": {key: {"P1": 0.10, "P2": 0.20, "P3": 0.30}
                           for key in ("roe", "roic", "ebit_margin")}}
    ev = evidence([period(y, net_income_parent=-1.0, ebit=-1.0) for y in (2024, 2025)], cohort_values=cohorts)
    for sub in ev.components["stock_quality"].inputs:
        if sub.key in cohorts["sector"]:
            assert sub.value < 0 and sub.shrunk_value > 0
            assert sub.score == 0.0 and sub.band_high == 0.0


def test_r1_f7_stale_balance_and_current_flows_cannot_form_fresh_ratios():
    old = period(2022)
    current = period(2025)
    current = replace(current, values={k: v for k, v in current.values.items()
                                      if k not in ("ib_debt", "minority_interest", "cash_sti", "lease_liabilities")})
    ev = evidence([old, current])
    # A10-F4: missing latest balance fields block older fallback altogether.
    assert ev.metrics["net_debt"].as_of is None
    assert ev.metrics["ev"].as_of is None
    for key in ("net_debt", "ev", "net_debt_to_ebitda", "ebit_ev_yield", "ev_ebit", "ev_sales"):
        assert not ev.metrics[key].available
    # R1-F7: a stale balance remains dated for display when it is the latest
    # statement, and cannot feed a fresh valuation or leverage ratio.
    stale = evidence([old])
    assert stale.metrics["net_debt"].as_of == stale.metrics["ev"].as_of == "2022-12-31"
    for key in ("net_debt_to_ebitda", "ebit_ev_yield", "ev_ebit", "ev_sales"):
        assert not stale.metrics[key].available
    # R1-F7 with A10-F4: a newer balance can join the latest FY flows,
    # retaining the older flow leg's date within the allowed tolerance.
    near = replace(old, period_end=date(2026, 1, 1), period_type="Q", known_at=current.known_at)
    ev = evidence([near, current])
    for key in ("net_debt_to_ebitda", "ebit_ev_yield", "ev_ebit", "ev_sales"):
        assert ev.metrics[key].available and ev.metrics[key].as_of == "2025-12-31"
    far = replace(near, period_end=date(2026, 3, 1), known_at=DECISION)
    assert not evidence([far, current]).metrics["ev_ebit"].available


def test_r1_f8_missing_financial_currency_is_unavailable_and_valid_fx_survives():
    frame = pd.DataFrame({pd.Timestamp("2025-12-31"): [1000.0]}, index=["Total Revenue"])
    ticker = SimpleNamespace(info={"quoteType": "EQUITY", "currency": "GBp", "marketCap": 500.0},
                             income_stmt=frame, cashflow=pd.DataFrame(), balance_sheet=pd.DataFrame(),
                             quarterly_income_stmt=pd.DataFrame(), quarterly_cashflow=pd.DataFrame(),
                             quarterly_balance_sheet=pd.DataFrame(), eps_trend=pd.DataFrame(), eps_revisions=pd.DataFrame())
    result = sources.fetch_yfinance("T", CONFIG, now=DECISION, ticker_factory=lambda _: ticker)
    assert result.status == "unavailable" and result.rows == []
    assert result.snapshot["financial_currency"] == "" and result.snapshot["quote_currency"] == "GBp"
    assert "financialCurrency" in result.reason
    ticker.info["financialCurrency"] = "EUR"
    valid = sources.fetch_yfinance("T", CONFIG, now=DECISION, ticker_factory=lambda _: ticker)
    assert valid.rows[0]["currency"] == "EUR"
    market = MarketInputs(price=5000.0, price_currency="GBp", fx_to_reporting=1.2,
                          price_date=DECISION.date(), market_cap_provider=600.0)
    assert evidence([period(2025)], market=market).metrics["market_cap"].value == pytest.approx(600.0)


def test_r1_f12_history_uses_latest_usable_sample_and_excludes_stale_pe():
    cfg = deepcopy(CONFIG)
    cfg["valuation"]["history_min_points"] = 1
    series = ((date(2026, 3, 1), 50.0), (date(2027, 1, 1), 55.0), (date(2026, 2, 20), 45.0))
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=DECISION.date(), price_series=series)
    ev = evidence([period(2024), period(2025)], config=cfg, market=market)
    assert ev.metrics["pe_percentile"].as_of == "2026-03-01" and ev.history_points == 2
    historical_market = replace(market, price_series=((date(2024, 3, 1), 50.0),))
    stale = evidence([period(2023), period(2025)], config=cfg, market=historical_market)
    sub = next(s for s in stale.components["stock_value"].inputs if s.key == "pe_history_percentile")
    assert stale.metrics["pe_percentile"].available and sub.score is None and "stale" in sub.reason
    # A recent sample cannot rebuild a P/E using a stale filing.
    stale = evidence([period(2023), period(2025)], config=cfg,
                     market=replace(market, price_series=((date(2025, 6, 1), 50.0),)))
    assert stale.history_points == 0 and not stale.metrics["pe_percentile"].available


def test_r1_f12_tiny_parent_equity_blocks_roe_and_price_to_book():
    tiny = period(2025, equity_parent=1.0, total_assets=10_000_000.0)
    ev = evidence([period(2024), tiny])
    for key in ("roe", "pb"):
        assert not ev.metrics[key].available and "denominator" in ev.metrics[key].reason


def test_dei_shares_preserve_publication_and_reject_class_or_split_conflicts():
    payload = {"facts": {
        "us-gaap": {"Revenues": concept(fact(1000.0, start="2025-01-01"))},
        "dei": {"EntityCommonStockSharesOutstanding": concept(
            fact(10.0, end="2026-02-01"), unit="shares")},
    }}

    def periods_for_payload(data):
        rows = sources.parse_edgar_companyfacts(data, CONFIG, source_ref="fixture")
        frame = pd.DataFrame([{**row, "instrument_id": "T"} for row in rows], columns=store.PERIOD_COLUMNS)
        return rows, store.periods_for("T", frame, ["sec_edgar"])

    rows, periods = periods_for_payload(payload)
    fy = next(row for row in rows if row["period_type"] == "FY")
    shares = next(row for row in rows if row["period_type"] == "SHARES")
    assert "shares_outstanding" not in fy
    assert shares["period_end"] == "2026-02-01" and shares["known_at"] == shares["available_at"] == "2026-02-10"
    assert sm.latest_reported_shares(periods, datetime(2026, 2, 10, 12, tzinfo=timezone.utc)) is None
    assert evidence(periods).metrics["market_cap"].value == 500.0
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=DECISION.date(),
                          shares_fallback=20.0, shares_fallback_known_at=DECISION)
    ev = evidence(periods, market=market)
    assert not ev.metrics["market_cap"].available and "split reconciliation" in ev.metrics["market_cap"].reason
    # A later ambiguous publication blocks the earlier valid count.
    entries = payload["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    entries.extend([fact(11.0, end="2026-03-01", filed="2026-03-10"),
                    fact(12.0, end="2026-03-01", filed="2026-03-10")])
    _, periods = periods_for_payload(payload)
    assert sm.latest_reported_shares(periods, DECISION) is None
    assert not evidence(periods).metrics["market_cap"].available


def test_fetch_edgar_leaves_shares_rows_to_the_provider_so_refresh_stores_each_filing_once():
    payload = {"facts": {"us-gaap": {"Revenues": concept(fact(1000.0, start="2025-01-01"))},
                         "dei": {"EntityCommonStockSharesOutstanding": concept(
                             fact(10.0, end="2026-02-01"), unit="shares")}}}
    result = sources.fetch_edgar("1", CONFIG, user_agent="t t@t.invalid", fetch=lambda _u, _a: payload, sleep=lambda _s: None)
    assert result.rows and all(row["period_type"] != "SHARES" for row in result.rows)
