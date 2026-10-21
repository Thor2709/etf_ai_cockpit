"""#SRV: sector/industry-relative value and quality (cohort percentiles) + V8 C.C2.S20.N001 availability fallback."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import MarketInputs, build_stock_evidence
from etf_cockpit.analysis.stock_peers import PeerProfile, cohort_members
from etf_cockpit.data.stock_fundamentals import load_stock_config
from etf_cockpit.signals.quality_momentum import build_quality_momentum_frame

UTC = timezone.utc
DECISION = datetime(2026, 10, 9, tzinfo=UTC)
CONFIG = load_stock_config()


def _period(year: int, **overrides: float) -> sm.Period:
    values = {
        "revenue": 1000.0 * (1.1 ** (year - 2022)),
        "gross_profit": 400.0,
        "ebit": 200.0,
        "da": 60.0,
        "pretax_income": 180.0,
        "income_tax": 45.0,
        "net_income_parent": 100.0 * (1.1 ** (year - 2022)),
        "cfo": 220.0,
        "capex": 70.0,
        "dividends_paid": 30.0,
        "equity_parent": 900.0 + 100.0 * (year - 2022),
        "minority_interest": 30.0,
        "ib_debt": 300.0,
        "lease_liabilities": 50.0,
        "cash_sti": 150.0,
        "shares_outstanding": 10.0,
    }
    values.update(overrides)
    known_at = datetime.fromisoformat(f"{year + 1}-02-15").replace(tzinfo=UTC)
    return sm.Period(date(year, 12, 31), "FY", known_at, "EUR", "sec_edgar", values)


def _evidence(cohorts, **overrides: float):
    periods = [_period(y, **overrides) for y in (2022, 2023, 2024, 2025)]
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8))
    return build_stock_evidence("T", periods, DECISION, market, None, CONFIG, cohort_values=cohorts)


def _cohort(metric_values: dict[str, dict[str, float]], peers: int, level: str = "industry"):
    return {level: {key: {f"P{i}": base + 0.01 * i for i in range(peers)} for key, base in metric_values.items()}}


def _sub(ev, component: str, key: str):
    return next(s for s in ev.components[component].inputs if s.key == key)


def test_same_absolute_margin_gets_different_quality_percentile_in_different_sectors() -> None:
    low_margin_sector = {"universe": {}, "sector": {"ebit_margin": {f"L{i}": 0.05 + 0.01 * i for i in range(5)}}}
    high_margin_sector = {"universe": {}, "sector": {"ebit_margin": {f"H{i}": 0.30 + 0.01 * i for i in range(5)}}}
    low = _sub(_evidence(low_margin_sector), "stock_quality", "ebit_margin")
    high = _sub(_evidence(high_margin_sector), "stock_quality", "ebit_margin")
    assert low.value == pytest.approx(high.value)
    assert low.score == 10.0 and high.score == 0.0
    assert low.cohort_level == "sector" and low.peer_count == 5


def test_cohort_of_two_peers_widens_to_sector_and_records_level_and_count() -> None:
    cohorts = {
        "industry": {"roe": {"P0": 0.05, "P1": 0.30}},
        "sector": {"roe": {"P0": 0.05, "P1": 0.30, "P2": 0.02, "P3": 0.40}},
        "region": {"roe": {}},
        "universe": {"roe": {}},
    }
    roe = _sub(_evidence(cohorts), "stock_quality", "roe")
    assert (roe.cohort_level, roe.peer_count) == ("sector", 4)
    assert roe.score is not None and 0.0 < roe.score < 10.0


def test_too_small_cohort_at_every_level_is_unavailable_not_the_absolute_ladder() -> None:
    cohorts = {level: {"roe": {"P0": 0.05, "P1": 0.30}} for level in ("industry", "sector", "region", "universe")}
    ev = _evidence(cohorts)
    roe = _sub(ev, "stock_quality", "roe")
    assert roe.score is None and roe.peer_count == 2 and "needs 3 peers" in (roe.reason or "")
    assert all(s.cohort_level != "absolute_unadjusted" for s in ev.components["stock_quality"].inputs)


@pytest.mark.parametrize("metric", ["earnings_yield", "fcf_yield"])
def test_negative_yield_never_scores_above_neutral_on_value(metric: str) -> None:
    # cohort of cash-burners: a negative yield would rank at the top of its cohort, but is never cheap
    cohorts = {"industry": {metric: {"P0": -0.30, "P1": -0.20, "P2": -0.10, "P3": -0.40}}}
    overrides = {"cfo": 10.0, "capex": 70.0} if metric == "fcf_yield" else {"net_income_parent": -50.0}
    ev = _evidence(cohorts, **overrides)
    sub = _sub(ev, "stock_value", metric)
    if sub.value is not None:
        assert sub.value < 0 and sub.score is not None and sub.score <= 5.0
    else:  # a loss is not-meaningful: scored by the loss rule, never above neutral
        assert sub.score is not None and sub.score <= 5.0


def test_negative_fcf_yield_cap_is_applied_even_at_the_top_rank() -> None:
    cohorts = {"industry": {"fcf_yield": {"P0": -0.30, "P1": -0.20, "P2": -0.10}}}
    ev = _evidence(cohorts, cfo=10.0, capex=70.0)
    sub = _sub(ev, "stock_value", "fcf_yield")
    assert sub.value is not None and sub.value < 0
    assert sub.score == 0.0


def test_missing_input_stays_unavailable_not_zero() -> None:
    cohorts = _cohort({"roic": 0.10, "roe": 0.10}, 5)
    periods = [_period(y) for y in (2022, 2023, 2024, 2025)]
    for period in periods:
        period.values.pop("ebit")
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8))
    ev = build_stock_evidence("T", periods, DECISION, market, None, CONFIG, cohort_values=cohorts)
    margin = _sub(ev, "stock_quality", "ebit_margin")
    assert margin.score is None and margin.value is None
    assert ev.components["stock_quality"].used_count < ev.components["stock_quality"].input_count


def test_legacy_callers_without_cohorts_fail_closed_for_noisy_inputs() -> None:
    ev = _evidence(None)
    roe = _sub(ev, "stock_quality", "roe")
    assert roe.score is None and roe.cohort_level is None
    assert "cohort median" in (roe.reason or "")
    leverage = _sub(ev, "stock_quality", "net_debt_to_ebitda")
    assert leverage.score is not None and leverage.cohort_level == "absolute_unadjusted"


def test_pe_vs_peers_uses_the_widened_cohort_and_lower_pe_is_cheaper() -> None:
    cohorts = {"industry": {"pe": {"P0": 50.0}}, "sector": {"pe": {"P0": 50.0, "P1": 40.0, "P2": 60.0}}}
    pe_sub = _sub(_evidence(cohorts), "stock_value", "pe_vs_peers_discount")
    assert pe_sub.cohort_level == "sector" and pe_sub.peer_count == 3
    assert pe_sub.score == 10.0  # own P/E (~50 / 10) is far below every peer


def test_cohort_members_widen_industry_sector_region_universe_and_exclude_self() -> None:
    target = PeerProfile("T", "T", "Tech", "Software", "US")
    others = [
        PeerProfile("A", "A", "Tech", "Software", "US"),
        PeerProfile("B", "B", "Tech", "Hardware", "EU"),
        PeerProfile("C", "C", "Energy", "Oil", "US"),
        PeerProfile("T", "T", "Tech", "Software", "US"),
    ]
    members = cohort_members(target, others)
    assert members == {"industry": ("A",), "sector": ("A", "B"), "region": ("A", "C"), "universe": ("A", "B", "C")}


def test_availability_falls_back_per_row_to_a_lower_priority_timestamp() -> None:
    """V8 C.C2.S20.N001: a row with only a valid lower-priority timestamp must not be marked unknown."""

    from tests.test_quality_momentum import _fundamental, _prices

    row_a = _fundamental("A", "2025-06-30", values=(4, 8, 2, 7, 8), sector="technology")
    row_b = _fundamental("B", "2025-06-30", values=(5, 6, 5, 5, 6), sector="technology")
    row_a["available_at"] = None
    row_a["filing_date"] = "2025-07-15"
    row_b["filing_date"] = "2025-07-15"
    result = build_quality_momentum_frame(_prices(), pd.DataFrame([row_a, row_b]), as_of_date=date(2025, 10, 7))
    reason = result.loc[result["instrument_id"] == "A", "reason"].item()
    assert reason != "unavailable_missing_official_availability_timestamp"


def test_universe_build_scores_inputs_inside_the_sector_cohort(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.analysis import stock_universe as su
    from etf_cockpit.data import stock_fundamentals as store

    ids = ["S1", "S2", "S3", "S4"]
    rows = [{"id": i, "instrument_type": "stock", "enabled": True, "ticker": i, "sector": "Industrials"} for i in ids]
    records = su.stock_records(rows, CONFIG)
    period_map = {i: [_period(y, ebit=100.0 + 40.0 * n) for y in (2022, 2023, 2024, 2025)] for n, i in enumerate(ids)}
    monkeypatch.setattr(store, "read_fundamentals", lambda _root: pd.DataFrame(columns=store.PERIOD_COLUMNS))
    monkeypatch.setattr(store, "read_snapshots", lambda _root: pd.DataFrame(columns=store.SNAPSHOT_COLUMNS))
    monkeypatch.setattr(store, "read_fx", lambda _root: pd.DataFrame(columns=store.FX_COLUMNS))
    monkeypatch.setattr(store, "periods_for", lambda iid, _frame, _chain: period_map.get(iid, []))
    monkeypatch.setattr(su, "load_user_peers", lambda _root: {})
    prices = pd.DataFrame(
        {"etf_id": ids, "date": pd.to_datetime(["2026-10-08"] * 4), "close": [50.0] * 4, "currency": ["EUR"] * 4, "dividends": [0.0] * 4}
    )
    universe = su.build_universe_evidence(records, prices, DECISION, config=CONFIG)
    top = _sub(universe.evidence["S4"], "stock_quality", "ebit_margin")
    bottom = _sub(universe.evidence["S1"], "stock_quality", "ebit_margin")
    assert top.cohort_level == "sector" and top.peer_count == 3
    # #SHR: 4 annual observations are shrunk (w = 4 / 8) toward the cohort median, so the bottom stock is pulled off 0.0
    assert top.score == 10.0 and bottom.score is not None and 0.0 <= bottom.score < 5.0
    assert bottom.shrunk_value is not None and bottom.raw_value is not None and bottom.shrunk_value > bottom.raw_value
