"""Issue #938 (Fundamentals P1): accounting consistency, evidence states and the formula registry.

Bughunt entries covered (native test first; every test below fails on the pre-fix base unless noted):
B104-N002, B102-N002, B105-N002, B106-N002, B02-C2-N002, B06-C2-N001.
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.formula_registry import FORMULA_REGISTRY, formula_for
from etf_cockpit.analysis.stock_evidence import METRIC_LABELS, MarketInputs, build_stock_evidence
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_sources as sources
from etf_cockpit.data.stock_fundamentals import load_stock_config
from etf_cockpit.data.stock_research import growth_analysis
from etf_cockpit.data.yfinance_provider import classify_provider_error

UTC = timezone.utc
DECISION = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
CONFIG = load_stock_config()
_PROPERTY_SETTINGS = settings(max_examples=12, derandomize=True, deadline=None)


def _fact(start: str | None, end: str, value: float, filed: str) -> dict[str, object]:
    row: dict[str, object] = {"end": end, "val": value, "filed": filed}
    if start is not None:
        row["start"] = start
    return row


def _payload(**concepts: list[dict[str, object]]) -> dict[str, object]:
    return {"facts": {"us-gaap": {name: {"units": {"USD": facts}} for name, facts in concepts.items()}, "dei": {}}}


def _rows(payload: dict[str, object], config: dict | None = None) -> dict[tuple[str, str], dict]:
    parsed = sources.parse_edgar_companyfacts(payload, config or CONFIG, source_ref="test")
    return {(row["period_end"], row["period_type"]): row for row in parsed}


def _period(year: int, *, currency: str = "EUR", scale: float = 1.0, **overrides: float) -> sm.Period:
    values = {
        "revenue": 1000.0 * scale,
        "gross_profit": 400.0 * scale,
        "ebit": 200.0 * scale,
        "da": 60.0 * scale,
        "pretax_income": 180.0 * scale,
        "income_tax": 45.0 * scale,
        "net_income_parent": 100.0 * scale,
        "cfo": 220.0 * scale,
        "capex": 70.0 * scale,
        "equity_parent": 900.0 * scale,
        "minority_interest": 0.0,
        "ib_debt": 300.0 * scale,
        "lease_liabilities": 50.0 * scale,
        "cash_sti": 150.0 * scale,
        "total_assets": 2000.0 * scale,
        "shares_outstanding": 10.0,
    }
    values.update(overrides)
    return sm.Period(date(year, 12, 31), "FY", datetime(year + 1, 2, 15, tzinfo=UTC), currency, "sec_edgar", values)


def _evidence(periods: list[sm.Period], market: MarketInputs | None = None):
    return build_stock_evidence("T", periods, DECISION, market or MarketInputs(), None, CONFIG)


# ---------------------------------------------------------------------------------------------
# T02 cumulative quarters, 53-week years, differing fiscal starts (P1-10)
# ---------------------------------------------------------------------------------------------


def test_t02_cumulative_ytd_becomes_discrete_quarters_and_a_gap_stays_unavailable() -> None:
    assert sm.ytd_to_discrete({1: 100.0, 2: 210.0, 3: 300.0, 4: 410.0}) == {1: 100.0, 2: 110.0, 3: 90.0, 4: 110.0}
    gappy = sm.ytd_to_discrete({1: 100.0, 3: 300.0, 4: 410.0})
    assert gappy[2] is None and gappy[3] is None and gappy[4] == 110.0 and gappy[1] == 100.0


def test_t02_parser_handles_a_53_week_year_and_a_non_calendar_fiscal_start() -> None:
    revenue = [
        _fact("2025-09-28", "2025-12-27", 100.0, "2026-01-30"),
        _fact("2025-09-28", "2026-03-28", 210.0, "2026-04-30"),
        _fact("2025-09-28", "2026-06-27", 300.0, "2026-07-30"),
        _fact("2025-09-28", "2026-10-03", 410.0, "2026-11-20"),  # 370-day (53-week) fiscal year, 98-day Q4
    ]
    rows = _rows(_payload(Revenues=revenue))
    quarters = [rows[(end, "Q")]["revenue"] for end in ("2025-12-27", "2026-03-28", "2026-06-27", "2026-10-03")]
    assert quarters == [100.0, 110.0, 90.0, 110.0]
    assert rows[("2026-10-03", "FY")]["revenue"] == 410.0 and rows[("2026-10-03", "FY")]["period_days"] == 370
    assert rows[("2026-10-03", "Q")]["value_status"] == json.dumps({"revenue": "derived"})  # Q2..Q4 are differences


def test_t02_a_missing_half_year_is_not_bridged() -> None:
    revenue = [
        _fact("2025-01-01", "2025-03-31", 100.0, "2025-05-01"),
        _fact("2025-01-01", "2025-09-30", 300.0, "2025-11-01"),
        _fact("2025-01-01", "2025-12-31", 410.0, "2026-02-10"),
    ]
    rows = _rows(_payload(Revenues=revenue))
    assert rows[("2025-03-31", "Q")]["revenue"] == 100.0
    assert ("2025-09-30", "Q") not in rows or "revenue" not in rows[("2025-09-30", "Q")]
    assert ("2025-12-31", "Q") not in rows or "revenue" not in rows[("2025-12-31", "Q")]


# ---------------------------------------------------------------------------------------------
# B102-N002: Q4 direct and inferred facts must not depend on the order of the filing facts
# ---------------------------------------------------------------------------------------------


def _q4_revenue(direct: float | None) -> list[dict[str, object]]:
    facts = [
        _fact("2025-01-01", "2025-03-31", 100.0, "2025-05-01"),
        _fact("2025-01-01", "2025-06-30", 210.0, "2025-08-01"),
        _fact("2025-01-01", "2025-09-30", 300.0, "2025-11-01"),
        _fact("2025-01-01", "2025-12-31", 410.0, "2026-02-10"),
    ]
    if direct is not None:
        facts.append(_fact("2025-10-01", "2025-12-31", direct, "2026-02-10"))
    return facts


@pytest.mark.parametrize("seed", range(6))
def test_b102_q4_result_is_independent_of_fact_order(seed: int) -> None:
    facts = _q4_revenue(110.0)
    random.Random(seed).shuffle(facts)
    reference = _rows(_payload(Revenues=_q4_revenue(110.0)))
    shuffled = _rows(_payload(Revenues=facts))
    assert shuffled[("2025-12-31", "Q")] == reference[("2025-12-31", "Q")]
    assert shuffled[("2025-12-31", "Q")]["revenue"] == 110.0
    assert "value_status" not in shuffled[("2025-12-31", "Q")]  # a reported quarter that agrees with the difference is observed


@pytest.mark.parametrize("seed", range(4))
def test_b102_a_direct_q4_that_contradicts_fy_minus_nine_months_is_conflicted_not_picked(seed: int) -> None:
    facts = _q4_revenue(150.0)  # FY - 9M says 110
    random.Random(seed).shuffle(facts)
    q4 = _rows(_payload(Revenues=facts))[("2025-12-31", "Q")]
    assert "revenue" not in q4
    assert json.loads(q4["value_status"]) == {"revenue": "conflicted"}


def test_b102_conflicted_sec_quarter_is_not_filled_from_a_lower_ranked_source() -> None:
    sec = _rows(_payload(Revenues=_q4_revenue(150.0)))[("2025-12-31", "Q")]
    yahoo = {
        "period_end": "2025-12-31", "period_type": "Q", "currency": "USD", "source": "yfinance", "known_at": "2026-03-01",
        "revenue": 777.0, "ebit": 20.0,
    }
    frame = pd.DataFrame([{**sec, "instrument_id": "T"}, {**yahoo, "instrument_id": "T"}])
    period = store.periods_for("T", frame, ["sec_edgar", "yfinance"])[-1]
    assert not period.has("revenue") and period.status_of("revenue") == "conflicted"
    assert period.values["ebit"] == 20.0  # unrelated fields still merge


# ---------------------------------------------------------------------------------------------
# T09 / B104-N002: debt and leases (P1-09)
# ---------------------------------------------------------------------------------------------


def _balance(name: str, value: float) -> dict[str, list[dict[str, object]]]:
    return {name: [_fact(None, "2025-12-31", value, "2026-02-10")]}


def test_b104_long_term_debt_total_is_not_added_to_its_own_current_portion() -> None:
    payload = _payload(
        Revenues=[_fact("2025-01-01", "2025-12-31", 500.0, "2026-02-10")],
        **_balance("LongTermDebt", 100.0),
        **_balance("LongTermDebtCurrent", 20.0),  # already inside LongTermDebt
        **_balance("ShortTermBorrowings", 7.0),  # disjoint: added
    )
    row = _rows(payload)[("2025-12-31", "FY")]
    assert row["ib_debt"] == 107.0


def test_t09_finance_leases_are_counted_once_in_net_debt() -> None:
    payload = _payload(
        Revenues=[_fact("2025-01-01", "2025-12-31", 500.0, "2026-02-10")],
        **_balance("DebtAndCapitalLeaseObligations", 125.0),
        **_balance("FinanceLeaseLiabilityNoncurrent", 25.0),
        **_balance("OperatingLeaseLiabilityNoncurrent", 10.0),
        **_balance("CashAndCashEquivalentsAtCarryingValue", 40.0),
    )
    config = {**CONFIG, "sec_edgar_concepts": {**CONFIG["sec_edgar_concepts"], "debt_total": ["DebtAndCapitalLeaseObligations"]}}
    row = _rows(payload, config)[("2025-12-31", "FY")]
    assert row["ib_debt"] == 100.0 and row["lease_liabilities"] == 35.0
    period = store.periods_for("T", pd.DataFrame([{**row, "instrument_id": "T"}]), ["sec_edgar"])[0]
    net_debt = _evidence([period]).metrics["net_debt"]
    assert net_debt.value == pytest.approx(100.0 + 35.0 - 40.0)  # 125 total once, not 125 + 35 + 25


def test_p1_09_the_current_portion_without_the_non_current_part_is_partial_not_zero_filled() -> None:
    payload = _payload(
        Revenues=[_fact("2025-01-01", "2025-12-31", 500.0, "2026-02-10")],
        **_balance("LongTermDebtCurrent", 20.0),
        **_balance("CashAndCashEquivalentsAtCarryingValue", 40.0),
        **_balance("ShortTermInvestments", 10.0),
    )
    row = _rows(payload)[("2025-12-31", "FY")]
    assert json.loads(row["value_status"]) == {"ib_debt": "partial"}
    period = store.periods_for("T", pd.DataFrame([{**row, "instrument_id": "T"}]), ["sec_edgar"])[0]
    assert period.status_of("ib_debt") == "partial"
    net_debt = _evidence([period]).metrics["net_debt"]
    assert net_debt.status == sm.UNAVAILABLE and "partial" in str(net_debt.reason)
    assert sm.metric_value_status(net_debt) == "partial"


# ---------------------------------------------------------------------------------------------
# T15 / P1-11: the merge gate
# ---------------------------------------------------------------------------------------------


def _store_row(source: str, end: str = "2025-12-31", **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "instrument_id": "T", "period_end": end, "period_type": "FY", "currency": "USD", "source": source,
        "known_at": "2026-02-10" if source == "sec_edgar" else "2026-03-01",
    }
    row.update(extra)
    return row


def test_t15_scope_standard_or_duration_mismatch_does_not_merge() -> None:
    primary = _store_row("sec_edgar", revenue=500.0, reporting_standard="us-gaap", consolidation_scope="consolidated", period_days=365)
    for mismatch in (
        {"consolidation_scope": "parent_only"},
        {"reporting_standard": "ifrs"},
        {"share_class": "B"},
        {"period_days": 91},
    ):
        base = {"reporting_standard": "us-gaap", "consolidation_scope": "consolidated", "period_days": 365, "share_class": "A" if "share_class" in mismatch else None}
        secondary = _store_row("yfinance", ebit=20.0, **{**base, **mismatch})
        primary_row = {**primary, "share_class": base["share_class"]}
        periods = store.periods_for("T", pd.DataFrame([primary_row, secondary]), ["sec_edgar", "yfinance"])
        assert len(periods) == 1, mismatch
        assert periods[0].values["revenue"] == 500.0 and "ebit" not in periods[0].values, mismatch


def test_t15_a_four_day_end_date_tolerance_alone_does_not_merge() -> None:
    primary = _store_row("sec_edgar", revenue=500.0, period_days=365, reporting_standard="us-gaap", consolidation_scope="consolidated")
    unverified = _store_row("yfinance", end="2025-12-29", ebit=20.0)  # no verified duration / scope
    periods = store.periods_for("T", pd.DataFrame([primary, unverified]), ["sec_edgar", "yfinance"])
    assert len(periods) == 1 and "ebit" not in periods[0].values
    verified = _store_row("yfinance", end="2025-12-29", ebit=20.0, period_days=363, reporting_standard="us-gaap", consolidation_scope="consolidated")
    merged = store.periods_for("T", pd.DataFrame([primary, verified]), ["sec_edgar", "yfinance"])
    assert merged[-1].values["ebit"] == 20.0 and merged[-1].period_end == date(2025, 12, 31)  # positive control: all attributes verified


def test_t15_the_same_end_date_with_unknown_attributes_still_merges() -> None:
    primary = _store_row("sec_edgar", revenue=500.0)
    secondary = _store_row("yfinance", ebit=20.0)
    period = store.periods_for("T", pd.DataFrame([primary, secondary]), ["sec_edgar", "yfinance"])[-1]
    assert period.values["revenue"] == 500.0 and period.values["ebit"] == 20.0


# ---------------------------------------------------------------------------------------------
# T13 evidence states: missing vs zero vs not applicable
# ---------------------------------------------------------------------------------------------


def test_t13_missing_zero_and_not_applicable_are_distinct_states() -> None:
    period = _period(2025, dividends_paid=0.0)
    assert period.status_of("dividends_paid") == "reported_zero"
    assert period.status_of("interest_expense") == "unavailable"  # missing is never zero
    assert period.status_of("revenue") == "observed"
    flagged = sm.Period(date(2025, 12, 31), "FY", DECISION, "EUR", "x", {"ib_debt": 5.0, "__currency_cash": "currency_mismatch"}, value_status={"ib_debt": "derived"})
    assert flagged.status_of("ib_debt") == "derived" and flagged.status_of("cash") == "conflicted"
    assert set(sm.VALUE_STATUSES) == {
        "observed", "reported_zero", "derived", "estimated_scenario", "partial", "unavailable",
        "not_applicable", "conflicted", "stale", "invalid",
    }
    loss = sm.margin("m", "M", 1.0, -5.0)
    assert sm.metric_value_status(loss) == "not_applicable" and loss.value is None
    assert sm.metric_value_status(sm.margin("m", "M", None, 5.0)) == "unavailable"
    assert sm.metric_value_status(sm.margin("m", "M", 1.0, 5.0)) == "derived"


def test_t13_a_missing_fact_is_never_zero_in_the_store_roundtrip(tmp_path) -> None:
    row = _rows(_payload(Revenues=[_fact("2025-01-01", "2025-12-31", 500.0, "2026-02-10")], **_balance("CashAndCashEquivalentsAtCarryingValue", 0.0)))[("2025-12-31", "FY")]
    frame, added = store.append_period_rows(pd.DataFrame(columns=store.PERIOD_COLUMNS), "T", [row])
    assert added == 1 and set(store.STATE_COLUMNS) <= set(frame.columns)
    period = store.periods_for("T", frame, ["sec_edgar"])[0]
    assert period.status_of("cash") == "reported_zero" and period.status_of("capex") == "unavailable"
    assert not period.has("capex")


# ---------------------------------------------------------------------------------------------
# T05 / T16 units, FX and scaling (P1-13)
# ---------------------------------------------------------------------------------------------


def test_t05_gbp_pence_prices_equal_pound_prices() -> None:
    minor = CONFIG["reporting"]["minor_currency_units"]
    pence, reason = sm.to_currency(250.0, "GBp", "GBP", fx_rate=None, minor_units=minor)
    assert reason is None and pence == pytest.approx(2.5)
    assert sm.to_currency(250.0, "GBX", "GBP", fx_rate=None, minor_units=minor)[0] == pytest.approx(2.5)
    periods = [_period(y, currency="GBP") for y in (2024, 2025)]
    in_pence = _evidence(periods, MarketInputs(price=5000.0, price_currency="GBp", price_date=date(2026, 10, 8)))
    in_pounds = _evidence(periods, MarketInputs(price=50.0, price_currency="GBP", price_date=date(2026, 10, 8)))
    assert in_pence.metrics["pe"].value == pytest.approx(in_pounds.metrics["pe"].value)
    mismatch = sm.to_currency(10.0, "USD", "EUR", fx_rate=None, minor_units=minor)
    assert mismatch == (None, "currency_mismatch")


@_PROPERTY_SETTINGS
@given(k=st.floats(min_value=1e-3, max_value=1e4, allow_nan=False, allow_infinity=False))
def test_t05_scaling_all_money_values_leaves_margins_roic_and_pe_unchanged(k: float) -> None:
    def run(scale: float):
        periods = [_period(y, scale=scale) for y in (2024, 2025)]
        return _evidence(periods, MarketInputs(price=50.0 * scale, price_currency="EUR", price_date=date(2026, 10, 8)))

    base, scaled = run(1.0), run(k)
    for key in ("gross_margin", "ebit_margin", "net_margin", "roic", "pe"):
        assert base.metrics[key].available, key
        assert scaled.metrics[key].value == pytest.approx(base.metrics[key].value, rel=1e-9), key


def test_t16_price_times_shares_must_agree_with_an_independent_market_cap() -> None:
    assert sm.price_shares_consistency(10.0, 100.0, 1000.0) == (True, None)
    consistent, why = sm.price_shares_consistency(10.0, 100.0, 5000.0)
    assert consistent is False and "differ" in str(why)
    assert sm.price_shares_consistency(10.0, 100.0, None) == (None, None)
    periods = [_period(y) for y in (2024, 2025)]
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8), market_cap_provider=50000.0)
    cap = _evidence(periods, market).metrics["market_cap"]
    assert cap.status == sm.UNAVAILABLE and "differ" in str(cap.reason)


# ---------------------------------------------------------------------------------------------
# T06 / T07 / T21 identities and anomaly guards
# ---------------------------------------------------------------------------------------------


def test_t07_cash_rollforward_identity() -> None:
    assert sm.cash_rollforward_check(100.0, 50.0, -30.0, -10.0, 1.0, 111.0).status == "ok"
    bad = sm.cash_rollforward_check(100.0, 50.0, -30.0, -10.0, 1.0, 150.0)
    assert bad.status == "failed" and bad.blocks and bad.difference == pytest.approx(39.0)
    missing = sm.cash_rollforward_check(100.0, 50.0, None, -10.0, 1.0, 111.0)
    assert missing.status == "unavailable" and "CFI" in str(missing.reason) and not missing.blocks


def test_t06_balance_identity_includes_non_controlling_interest() -> None:
    assert sm.balance_identity_check(1000.0, 600.0, 350.0, 50.0).status == "ok"
    without_nci = sm.balance_identity_check(1000.0, 600.0, 350.0, 0.0)  # forgetting NCI breaks the identity
    assert without_nci.status == "failed" and without_nci.blocks
    assert sm.balance_identity_check(1000.0, None, 350.0, 50.0).status == "unavailable"


def test_t21_anomaly_guards_block_instead_of_clamping() -> None:
    names = {check.name for check in sm.anomaly_guards(equity=-5.0, total_assets=100.0, cash=150.0, denominators={"revenue": 0.01}, scale=1000.0)}
    assert names == {"negative_equity", "cash_above_assets", "tiny_denominator:revenue"}
    assert sm.anomaly_guards(equity=5.0, total_assets=100.0, cash=50.0, denominators={"revenue": 500.0}, scale=1000.0) == ()
    # the matched ratios are unavailable (not a score of 0 or 10) when cash exceeds total assets
    evidence = _evidence([_period(y, total_assets=100.0, cash_sti=150.0) for y in (2024, 2025)])
    for key in ("net_debt", "roic", "net_debt_to_ebitda"):
        metric = evidence.metrics[key]
        assert metric.status == sm.UNAVAILABLE and metric.value is None, key
    assert "cash_above_assets" in str(evidence.metrics["net_debt"].reason)


# ---------------------------------------------------------------------------------------------
# B105-N002 ROIC endpoints, B106-N002 growth gaps, B06-C2-N001 CAGR years
# ---------------------------------------------------------------------------------------------


def test_b105_negative_opening_invested_capital_is_not_scored() -> None:
    assert sm.roic(10.0, -5.0, 100.0).status == sm.NOT_MEANINGFUL
    assert sm.roic(10.0, 0.0, 100.0).status == sm.NOT_MEANINGFUL
    assert sm.roic(10.0, 50.0, 100.0).value == pytest.approx(0.1)
    assert sm.roic(10.0, None, 100.0).value == pytest.approx(0.1)
    # through the evidence: opening capital = equity + debt + leases - cash = 50 + 30 + 5 - 150 < 0
    periods = [_period(2024, equity_parent=50.0, ib_debt=30.0, lease_liabilities=5.0, cash_sti=150.0), _period(2025)]
    roic = _evidence(periods).metrics["roic"]
    assert roic.status == sm.NOT_MEANINGFUL and roic.value is None


def _growth_periods(years: tuple[int, ...]) -> list[sm.Period]:
    return [_period(y, revenue=1000.0 * 1.1 ** (y - years[0]), net_income_parent=100.0 * 1.1 ** (y - years[0])) for y in years]


def test_b106_a_whole_missing_fiscal_year_is_not_bridged_as_year_over_year() -> None:
    complete = _evidence(_growth_periods((2022, 2023, 2024, 2025)))
    assert complete.metrics["revenue_cagr"].value == pytest.approx(0.10)
    gap = _evidence(_growth_periods((2021, 2023, 2024, 2025)))  # FY2022 is missing
    for key in ("revenue_cagr", "net_income_cagr"):
        assert gap.metrics[key].status == sm.UNAVAILABLE and gap.metrics[key].value is None, key
        assert "missing" in str(gap.metrics[key].reason)


def test_b06_c2_a_transition_year_is_not_rounded_into_a_whole_year() -> None:
    ends = (date(2019, 12, 31), date(2020, 12, 31), date(2021, 6, 30), date(2022, 6, 30))  # FY change leaves a 6-month year
    periods = [
        sm.Period(end, "FY", datetime(end.year + 1, 2, 15, tzinfo=UTC), "EUR", "sec_edgar", {**_period(2025).values, "revenue": 1000.0 * 1.5 ** index})
        for index, end in enumerate(ends)
    ]
    cagr = _evidence(periods).metrics["revenue_cagr"]
    assert cagr.status == sm.UNAVAILABLE and cagr.value is None  # 3.5 calendar years were rounded to 3 before the fix
    assert sm.consecutive_fiscal_years([date(2020, 1, 3), date(2021, 1, 1), date(2021, 12, 31), date(2023, 1, 6)])  # 52/53-week years are fine
    assert not sm.consecutive_fiscal_years(list(ends))


# ---------------------------------------------------------------------------------------------
# B02-C2-N002: EPS uses the weighted-average share count
# ---------------------------------------------------------------------------------------------


def _statements(extra: dict[str, float] | None = None) -> pd.DataFrame:
    rows = []
    for year, income in ((2025, 15.0), (2026, 20.0)):
        values = {"net_income": income, "shares_outstanding": 10.0, "revenue": 100.0, **(extra or {})}
        for metric, value in values.items():
            rows.append({
                "instrument_id": "ACME", "canonical_metric": metric, "value": value, "period_type": "annual", "period_key": f"FY{year}",
                "start": f"{year}-01-01", "end": f"{year}-12-31", "period_end": f"{year}-12-31", "fiscal_year": year, "fiscal_period": "FY",
                "source_id": f"filing-{year}", "filed": f"{year + 1}-02-15", "restatement_kind": "reported",
            })
    return pd.DataFrame(rows)


def test_b02_c2_eps_uses_weighted_average_shares_when_reported() -> None:
    result = growth_analysis(_statements({"weighted_average_shares": 8.0}), instrument_id="ACME")
    eps = result["series"]["per_share"]["earnings_per_share"]
    assert eps["history"][-1]["value"] == pytest.approx(20.0 / 8.0)  # not 20 / 10 period-end shares
    assert eps["history"][-1]["formula"] == "net_income / weighted_average_shares"
    fallback = growth_analysis(_statements(), instrument_id="ACME")["series"]["per_share"]["earnings_per_share"]
    assert fallback["history"][-1]["value"] == pytest.approx(2.0)  # period-end fallback unchanged when nothing better is reported


# ---------------------------------------------------------------------------------------------
# Formula registry (§6) and the capex proxy label (P1-12)
# ---------------------------------------------------------------------------------------------


def test_registry_has_one_complete_formula_id_per_metric() -> None:
    required = {
        "gross_margin", "ebit_margin", "roe", "roic", "nopat", "accruals", "cash_conversion", "fcf", "net_debt",
        "net_debt_to_ebitda", "interest_cover", "revenue_cagr", "dilution",
    }
    assert required <= set(FORMULA_REGISTRY)
    assert set(METRIC_LABELS) <= set(FORMULA_REGISTRY)  # every evidence metric is registered
    ids = [spec.formula_id for spec in FORMULA_REGISTRY.values()]
    assert len(ids) == len(set(ids))
    for spec in FORMULA_REGISTRY.values():
        assert spec.numerator and spec.denominator and spec.period and spec.units, spec.metric_key
    assert "not FCFE" in formula_for("fcf").note and "not FCFE" in formula_for("fcf_yield").note
    assert formula_for("net_debt_to_ebitda").note.startswith("no multiple when EBITDA")
    assert formula_for("nope") is None


def test_capex_proxy_is_labelled_a_screening_proxy_not_owner_earnings() -> None:
    fcf = _evidence([_period(2025)]).metrics["fcf"]
    assert fcf.available and "not FCFE" in fcf.formula and "screening proxy" in fcf.formula and "not owner earnings" in fcf.formula


def test_formula_helpers_cover_the_registered_metrics() -> None:
    assert sm.net_debt_to_ebitda(100.0, -5.0).value is None  # no multiple when EBITDA <= 0
    assert sm.accruals_ratio(10.0, 14.0, 200.0).value == pytest.approx(-0.02)
    assert sm.cash_conversion(14.0, 10.0).value == pytest.approx(1.4)
    assert sm.cash_conversion(14.0, -1.0).status == sm.NOT_MEANINGFUL
    assert sm.interest_cover(50.0, 10.0).value == pytest.approx(5.0)
    assert sm.interest_cover(50.0, 0.0).status == sm.NOT_MEANINGFUL
    assert sm.dilution(100.0, 103.0).value == pytest.approx(0.03)
    assert sm.dilution(None, 103.0).status == sm.UNAVAILABLE


# ---------------------------------------------------------------------------------------------
# T24 / P1-15: per-table provider errors
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (RuntimeError("HTTP Error 404: Quote not found"), "not_found"),
        (RuntimeError("429 Client Error: Too Many Requests"), "throttled"),
        (TimeoutError("read timed out"), "timeout"),
        (ValueError("boom"), "error"),
    ],
)
def test_t24_provider_errors_are_classified(error: Exception, kind: str) -> None:
    assert classify_provider_error(error) == kind


class _Ticker:
    """yfinance-like ticker whose statements fail one by one."""

    info = {"quoteType": "EQUITY", "longName": "X", "currency": "EUR", "financialCurrency": "EUR"}
    eps_trend = pd.DataFrame()
    eps_revisions = pd.DataFrame()
    quarterly_income_stmt = pd.DataFrame()
    quarterly_cashflow = pd.DataFrame()
    quarterly_balance_sheet = pd.DataFrame()

    def __init__(self, failures: dict[str, Exception]) -> None:
        self._failures = failures
        self._income = pd.DataFrame({pd.Timestamp("2025-12-31"): [500.0, 100.0]}, index=["Total Revenue", "Net Income"])

    def _get(self, name: str) -> pd.DataFrame:
        if name in self._failures:
            raise self._failures[name]
        return self._income if name == "income_stmt" else pd.DataFrame()

    income_stmt = property(lambda self: self._get("income_stmt"))
    cashflow = property(lambda self: self._get("cashflow"))
    balance_sheet = property(lambda self: self._get("balance_sheet"))


def test_t24_statement_failures_are_recorded_per_table_and_never_swallowed() -> None:
    failures = {"cashflow": RuntimeError("429 Too Many Requests"), "balance_sheet": TimeoutError("timed out")}
    result = sources.fetch_yfinance("X.PA", CONFIG, now=DECISION, ticker_factory=lambda _s: _Ticker(failures))
    assert result.rows, "the statements that did arrive are kept"
    assert result.statement_errors["cashflow"].startswith("throttled:")
    assert result.statement_errors["balance_sheet"].startswith("timeout:")
    assert "partial statements" in result.reason and "cashflow" in result.reason
    assert result.snapshot["reason"] == result.reason

    everything = {name: RuntimeError("HTTP Error 404") for name in ("income_stmt", "cashflow", "balance_sheet")}
    dead = sources.fetch_yfinance("X.PA", CONFIG, now=DECISION, ticker_factory=lambda _s: _Ticker(everything))
    assert dead.rows == [] and dead.status == "not_found" and set(dead.statement_errors) == set(everything)
    mixed = {"income_stmt": RuntimeError("429 Too Many Requests"), "cashflow": TimeoutError("timed out"), "balance_sheet": RuntimeError("boom")}
    broken = sources.fetch_yfinance("X.PA", CONFIG, now=DECISION, ticker_factory=lambda _s: _Ticker(mixed))
    assert broken.status == "error" and "throttled" in broken.reason and "timeout" in broken.reason


def test_t24_refresh_reports_partial_statements_per_instrument(tmp_path) -> None:
    failures = {"balance_sheet": RuntimeError("429 Too Many Requests")}

    def fetch(symbol, config, *, now):
        return sources.fetch_yfinance(symbol, config, now=now, ticker_factory=lambda _s: _Ticker(failures))

    target = store.StockTarget("T", "Test", "X.PA")
    report = store.refresh_stock_fundamentals(
        [target], root=tmp_path, now=DECISION, config={**CONFIG, "sources": {"chain": ["yfinance"]}}, environ={},
        yfinance_fetch=fetch, fx_fetch=lambda *_a, **_k: [],
    )
    assert "balance_sheet" in report.per_instrument["T"] and report.per_instrument["T"] != "ok"
    assert report.rows_added > 0 and not report.failures
