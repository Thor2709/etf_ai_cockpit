"""Bug-hunt S4 reproductions (strict xfail: each asserts the CORRECT behaviour)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pandas as pd
import pytest

from etf_cockpit.analysis.candles.backtest_safety import backtest_candle_templates
from etf_cockpit.analysis.candles.features import calculate_candle_features
from etf_cockpit.analysis.decision.contracts import ScoredMetric
from etf_cockpit.analysis.decision.domains import (
    DomainRegistry,
    MetricDefinition,
    build_instrument_assessment,
)
from etf_cockpit.analysis.fixed_income_analytics import (
    ContractualCashFlow as CF,
    CurveNode,
    DiscountCurveEvidence,
    FixedIncomeValuationInput,
    calculate_fixed_income_analytics,
)
from etf_cockpit.analysis.fixed_income_returns import (
    FixedIncomeReturnInput,
    calculate_fixed_income_return_decomposition,
)
from etf_cockpit.analysis.innovation_sector_adapters import (
    InnovationMetricEvidence,
    build_innovation_projection,
    innovation_adapter_definitions,
)
from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry, PeerObservation
from etf_cockpit.analysis.sparebank.events import deficit_coverage
from etf_cockpit.application.market_views import load_etf_look_through
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority as A
from etf_cockpit.data.market_calendar import DayCountConvention as DC

_CLASS_VALUES = {
    "instrument_type": "stock",
    "asset_class": "equity",
    "sector": "technology",
    "industry": "software",
    "business_model_tag": "software",
}


def _context(name, *, effective_at, decision_time):
    evidence = [
        ClassificationEvidence(
            name + field,
            name,
            field,
            value,
            "issuer",
            A.OFFICIAL,
            "s" + field,
            0.99,
            "2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in _CLASS_VALUES.items()
    ]
    return resolve_instrument_context(
        evidence,
        instrument_id=name,
        effective_at=effective_at,
        decision_time=decision_time,
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S4-01: ex-coupon pricing includes detached coupon",
)
def test_s4_01_ex_coupon_dirty_price():
    flows = (
        CF(date(2026, 7, 1), D("2.5"), "coupon", "v", date(2026, 1, 1), date(2026, 7, 1), date(2026, 6, 24)),
        CF(date(2027, 1, 1), D("2.5"), "coupon", "v", date(2026, 7, 1), date(2027, 1, 1), date(2026, 12, 24)),
        CF(date(2027, 1, 1), D(100), "redemption", "v"),
    )
    v = FixedIncomeValuationInput(
        "B", "v", "EUR", D(100), date(2026, 6, 25), date(2027, 1, 1), D(".05"), 2,
        DC.ACT_365F, flows, datetime(2026, 6, 25, tzinfo=timezone.utc),
        yield_to_maturity=D(0),
    )
    assert calculate_fixed_income_analytics(v).dirty_price == D("102.5")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S4-02: deficit waterfall overdraws capital pools",
)
def test_s4_02_deficit_cannot_overdraw_capital_pools():
    r = deficit_coverage(300, owner_nominal=100, owner_premium_fund=50, self_owned_capital=100)
    assert r["self_owned_reduction"] <= 100
    assert r["owner_fund_reduction"] <= 50
    assert r["owner_book_after"] == 0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S4-03: default loss changes when curve is supplied",
)
def test_s4_03_default_loss_basis_independent_of_curve():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    v = FixedIncomeValuationInput(
        "B", "v", "EUR", D(100), date(2026, 1, 1), date(2028, 1, 1), D(0), 0,
        DC.ACT_365F, (CF(date(2028, 1, 1), D(100), "redemption", "v"),), t,
        clean_price=D(50),
    )
    rate = D(2).sqrt() - 1
    curve = DiscountCurveEvidence(
        "c", "zero", "EUR", "decimal", "annual", "linear_zero", DC.ACT_365F,
        (CurveNode(D(".5"), rate), CurveNode(D(2), rate)),
        "issuer", "1", "a" * 64, t, t, t,
    )
    i = FixedIncomeReturnInput(
        v, 90, default_probability=D(".1"), recovery_rate=D(".4"),
        fx_return=D(0), cost_bps=D(0),
    )
    without = calculate_fixed_income_return_decomposition(i)
    with_curve = calculate_fixed_income_return_decomposition(
        replace(i, valuation=replace(v, curve=curve))
    )
    assert without.default_recovery == with_curve.default_recovery


def test_s4_04_gap_stop_uses_reachable_execution_price():
    bars = [(100, 102, 99, 101), (104, 106, 103, 105), (100, 101, 99, 100), (90, 91, 89, 90)]
    candles = [
        dict(date=f"2026-09-0{i + 1}", open=o, high=h, low=lo, close=c, volume=10, price_basis="raw")
        for i, (o, h, lo, c) in enumerate(bars)
    ]
    r = backtest_candle_templates(candles)
    trade = next(x for x in r["rows"] if x.get("signal_date") == "2026-09-02")
    assert trade["status"] == "closed"
    assert trade["exit_date"] == "2026-09-04"
    # the exit bar traded 89-91, so a fill at the 98 stop is unreachable
    assert 89 <= trade["exit_price"] <= 91


def test_s4_05_historical_metric_uses_decision_classification_cutoff():
    t, e, k = "2025-03-01T00:00:00Z", "2024-12-31T00:00:00Z", "2025-02-01T00:00:00Z"

    def ctx(n):
        return _context(n, effective_at=t, decision_time=t)

    peers = [
        PeerObservation(n, ctx(n), "gross_margin", v, 1, e, k)
        for n, v in [("A", 0.3), ("B", 0.4), ("C", 0.6)]
    ]
    m = ScoredMetric(
        "gross_margin", 0.5, "ratio", e, k, "issuer", 1, 1, 1, None, "SECTOR",
        "higher_is_better", "CRITICAL", True, 1, 0, "AVAILABLE",
    )
    d = MetricDefinition(
        "gross_margin", "quality", "profit", 1, "SECTOR", "CRITICAL",
        "higher_is_better", rank_authority=True,
    )
    r = build_instrument_assessment(
        "X", "stock", "software", t, [m], DomainRegistry("v", "a" * 64, (d,)),
        target_context=ctx("X"), peer_observations=peers,
    )
    # normalisation reports lower-case "available"; failures are upper-case
    assert r.drivers[0].status.upper() == "AVAILABLE"
    assert r.drivers[0].reason_code != "PEER_COHORT_UNAVAILABLE"


def test_s4_06_latest_holdings_means_latest_known_snapshot():
    common = dict(instrument_id="F", isin="US0378331005", weight=1, source="issuer")
    h = pd.DataFrame(
        [
            dict(common, as_of="2026-09-29", known_at="2026-09-30T00:00:00Z", source_id="s1"),
            dict(common, as_of="2026-09-30", known_at="2026-10-03T00:00:00Z", source_id="s2"),
        ]
    )
    r = load_etf_look_through(
        "F", decision_time="2026-10-01T00:00:00Z", holdings_frame=h,
        fundamentals_frame=pd.DataFrame(),
    )
    assert r["holdings_date"] == "2026-09-29"
    assert r["reported_total_weight"] == 1.0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S4-07: percentage dilution compared with fractional dilution",
)
def test_s4_07_percentage_dilution_reconciles_with_share_counts():
    t, e = "2025-03-01T00:00:00Z", "2024-12-31T00:00:00Z"
    ctx = _context("X", effective_at=e, decision_time=t)
    ev = [
        InnovationMetricEvidence(
            n, v, u, "FY2024", "IFRS", "AU", "software", "issuer:" + n, A.ISSUER, e,
            "2025-02-15T00:00:00Z",
        )
        for n, v, u in [
            ("basic_shares", 100, "shares"),
            ("diluted_shares", 110, "shares"),
            ("dilution_rate", 10, "percent"),
        ]
    ]
    r = build_innovation_projection(
        ctx, ev, registry=AdapterRegistry(innovation_adapter_definitions()), decision_time=t
    )
    dilution = next(m for m in r.metrics if m.metric == "dilution_rate")
    assert dilution.status == "available"
    assert dilution.value == 10


def test_s4_08_candle_features_preserve_valid_volume():
    r = calculate_candle_features(
        dict(open=100, high=102, low=99, close=101, volume=12345, price_basis="raw")
    )
    assert r["status"] == "available"
    assert r["volume"] == 12345


def _s4_candles(bars):
    return [
        dict(date=f"2026-09-0{i + 1}", open=o, high=h, low=lo, close=c, volume=10, price_basis="raw")
        for i, (o, h, lo, c) in enumerate(bars)
    ]


def test_s4_04_gap_through_target_fills_at_open_inside_bar():
    bars = [(100, 102, 99, 101), (104, 106, 103, 105), (100, 101, 99, 100), (110, 111, 109, 110)]
    r = backtest_candle_templates(_s4_candles(bars))
    trade = next(x for x in r["rows"] if x.get("signal_date") == "2026-09-02")
    assert trade["exit_reason"] == "target"
    assert trade["exit_price"] == 110


def test_s4_04_short_gap_up_through_stop_fills_at_open():
    bars = [(100, 102, 99, 101), (98, 99, 96, 97), (100, 101, 99, 100), (105, 106, 104, 105)]
    r = backtest_candle_templates(_s4_candles(bars))
    trade = next(x for x in r["rows"] if x.get("signal_date") == "2026-09-02")
    assert trade["side"] == "short"
    assert trade["exit_reason"] == "stop"
    assert trade["exit_price"] == 105


def test_s4_06_requested_source_applies_before_latest_date_selection():
    base = dict(instrument_id="F", isin="US0378331005", weight=1)
    h = pd.DataFrame(
        [
            dict(base, as_of="2026-09-29", known_at="2026-09-30T00:00:00Z", source="issuer", source_id="s1"),
            dict(base, as_of="2026-09-30", known_at="2026-09-30T12:00:00Z", source="vendor", source_id="s2"),
        ]
    )
    r = calculate_look_through(
        h, instrument_id="F", decision_time="2026-10-01T00:00:00Z", source="issuer"
    )
    assert r.holdings_date == "2026-09-29"
