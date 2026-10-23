"""A10 regressions. All identities and numbers below are synthetic test evidence."""

from dataclasses import replace
from datetime import date, datetime, timezone
from itertools import permutations

import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.look_through import _latest_metric_row
from etf_cockpit.analysis.peer_cohorts import construct_cohort, normalize_peer_metric
from test_etf_look_through import (
    APPLE_ISIN, MICROSOFT_ISIN, _analyze, _fundamental, _holding,
)
from test_peer_cohorts import AS_OF, DECISION, _context, _observation


def _cohort(observations, **kwargs):
    return construct_cohort(
        _context("TARGET"), observations, metric="quality", effective_at=AS_OF,
        decision_time=DECISION, minimum_support=1, **kwargs,
    )


def test_a10_f1_latest_invalid_revision_never_restores_old_value() -> None:
    old = _observation("PEER", 15.0)
    for changes, reason in (
        ({"value": None}, "invalid_value"),
        ({"value": float("nan")}, "invalid_value"),
        ({"weight": float("inf")}, "non_positive_weight"),
        ({"applicable": False}, "metric_inapplicable"),
        ({"active_to": AS_OF}, "inactive_at_cutoff"),
        ({"context": _context("CLASS-A")}, "classification_identity_mismatch"),
    ):
        new = replace(old, revision=2, known_at="2024-06-02T00:00:00Z", **changes)
        for rows in ((old, new), (new, old)):
            result = _cohort(rows)
            assert result.members == () and result.parent_observations == ()
            assert result.exclusions["PEER"] == reason
            assert result.exclusions["PEER@revision:1"] == "superseded_revision"
        # A retraction learned later or effective later cannot affect replay.
        for future in (
            replace(new, known_at="2024-08-01T00:00:00Z"),
            replace(new, effective_at="2024-08-01T00:00:00Z"),
        ):
            assert _cohort((old, future)).observations == (old,)


@pytest.mark.xfail(strict=True, reason=(
    "NEEDS_OPUS_DECISION A10-F2: conflicts with intended ROIC-only carry-forward "
    "in test_bug_hl1_look_through.py::test_a011_n004_newer_roic_only_record_does_not_suppress_earlier_pe"
))
def test_a10_f2_latest_nonfinite_metric_is_unavailable() -> None:
    old = _fundamental("apple", pe_ratio=18.0, as_of_date="2025-09-30")
    new = _fundamental("apple", pe_ratio=None, as_of_date="2025-12-31")
    assert _latest_metric_row([old, new], "pe_ratio") == (None, False)


def test_a10_f3_currency_mismatch_blocks_windows_and_ratios() -> None:
    period = sm.Period(
        date(2025, 12, 31), "FY", datetime(2026, 2, 1, tzinfo=timezone.utc),
        "EUR", "sec_edgar", {"revenue": 100.0, "__currency_revenue": "currency_mismatch"},
    )
    for explicit in ({}, {"revenue": "observed"}):
        conflicted = replace(period, value_status=explicit)
        assert conflicted.status_of("revenue") == "conflicted"
        assert conflicted.blocked_state("revenue") == "conflicted"
        assert not conflicted.usable("revenue") and not conflicted.has("revenue")
        assert sm.flow_window([conflicted], ["revenue"]) is None
        assert sm.latest_balance([conflicted], ["revenue"]) is None


def test_a10_f4_latest_or_nearest_invalid_period_does_not_fallback() -> None:
    decision = datetime(2026, 7, 1, tzinfo=timezone.utc)
    old = sm.Period(date(2024, 12, 31), "FY", datetime(2025, 2, 1, tzinfo=timezone.utc),
                    "EUR", "sec_edgar", {"ebit": 20.0, "equity_parent": 100.0})
    latest = replace(old, period_end=date(2025, 12, 31), known_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    for invalid in (
        replace(latest, value_status={"ebit": "invalid", "equity_parent": "conflicted"}),
        replace(latest, values={}),
    ):
        for rows in ((old, invalid), (invalid, old)):
            assert sm.flow_window(rows, ["ebit"]) is None
            assert sm.latest_balance(rows, ["equity_parent"]) is None
        near_old = replace(old, period_end=date(2025, 12, 1))
        assert sm.balance_near([near_old, invalid], invalid.period_end, ["equity_parent"]) is None
        # A later revision of the same reporting period also blocks the old value.
        previous = replace(latest, known_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert sm.latest_balance([invalid, previous], ["equity_parent"]) is None
        assert sm.balance_near([previous, invalid], invalid.period_end, ["equity_parent"]) is None
    quarters = [replace(latest, period_type="Q", period_end=date.fromisoformat(end)) for end in
                ("2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31")]
    quarters[-1] = replace(quarters[-1], value_status={"ebit": "invalid"})
    assert sm.flow_window([old, *quarters], ["ebit"]) is None
    old_revision = replace(quarters[-1], known_at=datetime(2026, 1, 1, tzinfo=timezone.utc), value_status={})
    assert sm.flow_window([old, *quarters, old_revision], ["ebit"]) is None
    shares = replace(old, period_type="SHARES", source="sec_dei", values={"shares_outstanding": 100.0})
    provider = replace(shares, source="yfinance", known_at=latest.known_at)
    assert sm.latest_reported_shares([shares], decision) is shares
    assert sm.latest_reported_shares([shares, provider], decision) is None
    assert sm.latest_reported_shares([shares, replace(provider, values={})], decision) is None
    assert sm.latest_reported_shares([shares, replace(provider, known_at=datetime(2027, 1, 1, tzinfo=timezone.utc))], decision) is shares
    assert sm.latest_balance([latest, provider], ["equity_parent"]) is latest


def test_a10_f5_nonfinite_inputs_never_produce_available_ratios() -> None:
    calls = (
        (sm.roe, (10.0, 100.0, 100.0), {}),
        (sm.roic, (10.0, 100.0, 100.0), {}),
        (sm.margin, (10.0, 100.0), {"key": "margin", "label": "Margin"}),
        (sm.net_debt_to_ebitda, (10.0, 100.0), {}),
        (sm.debt_to_equity, (10.0, 100.0), {}),
        (sm.multiple, (100.0, 10.0), {"key": "pe", "label": "P/E", "formula": "", "denominator_name": "income"}),
        (sm.yield_of, (10.0, 100.0), {"key": "yield", "label": "Yield", "formula": ""}),
        (sm.dividend_yield, (1.0, 10.0), {}),
        (sm.cagr, (100.0, 120.0, 3.0), {"key": "g", "label": "Growth"}),
        (sm.implied_growth_from_pe, (20.0, 0.4, 0.08), {}),
        (sm.implied_growth_from_dcf, (100.0, 10.0, 0.08, 0.02, 5), {}),
        (sm.accruals_ratio, (10.0, 12.0, 100.0), {}),
        (sm.cash_conversion, (12.0, 10.0), {}),
        (sm.interest_cover, (10.0, 2.0), {}),
        (sm.dilution, (100.0, 110.0), {}),
        (sm.effective_tax_rate, (10.0, 100.0), {}),
        (sm.nopat, (100.0, 0.2), {}),
        (sm.invested_capital, (100.0, 10.0, 1.0, 5.0), {}),
        (sm.free_cash_flow, (100.0, 10.0), {}),
        (sm.net_debt, (100.0, 10.0, 5.0), {}),
        (sm.ebitda, (100.0, 10.0), {}),
        (sm.market_cap, (100.0, 10.0), {}),
        (sm.enterprise_value, (100.0, 10.0, 1.0), {}),
    )
    # Formula helpers with leading key/label arguments use keyword-only adapters
    # here so every numeric input can be exercised independently.
    for function, args, kwargs in calls:
        for index in range(len(args)):
            for bad in (float("nan"), float("inf"), -float("inf")):
                changed = list(args)
                changed[index] = bad
                if function in (sm.margin, sm.multiple, sm.yield_of):
                    options = dict(kwargs)
                    result = function(options.pop("key"), options.pop("label"), *changed, **options)
                else:
                    result = function(*changed, **kwargs)
                if isinstance(result, sm.Metric):
                    assert result.status == sm.UNAVAILABLE and result.value is None, (function.__name__, index, bad)
                else:
                    assert result is None, (function.__name__, index, bad)
    for years in (0, -1, True, 1.5):
        assert sm.implied_growth_from_dcf(100.0, 10.0, 0.08, 0.02, years).status == sm.UNAVAILABLE
    assert sm.percentile_rank([10.0, 20.0], float("nan")) is None
    assert sm.to_currency(float("nan"), "EUR", "EUR", fx_rate=None, minor_units={}) == (None, "amount_unavailable")
    assert sm.price_shares_consistency(10.0, 10.0, float("nan")) == (None, None)


@pytest.mark.xfail(strict=True, reason=(
    "NEEDS_OPUS_DECISION A10-F6: deterministic instrument tie-break conflicts with "
    "test_fund_peer_cohorts.py::test_fund_peer_engine_keeps_caller_representative_when_returns_are_swapped"
))
def test_a10_f6_same_entity_exclusion_and_fund_ties_are_order_invariant() -> None:
    same_entity = _observation("CLASS-A", 3.0, context=replace(_context("CLASS-A"), entity_id="TARGET"))
    assert _cohort([same_entity]).members == ()
    rows = [_observation("CLASS-B", 4.0, strategy="same-company"),
            _observation("CLASS-A", 3.0, strategy="same-company")]
    results = [_cohort(order, comparison_scope="FUND_PEERS", comparison_dimension_order=("mandate",),
                       comparison_dimension_groups={identifier: {"mandate": "index"} for identifier in
                                                    ("TARGET", "CLASS-A", "CLASS-B")})
               for order in permutations(rows)]
    assert all(result.members == ("CLASS-A",) for result in results)
    assert len({result.cohort_hash for result in results}) == 1


def test_a10_f7_reverse_metric_preserves_favourable_parent_prior() -> None:
    cohort = replace(_cohort([_observation("CLASS-A", 1.0), _observation("CLASS-B", 3.0)]),
                     parent_observations=())
    for shape, band in (("lower_is_better", None), ("target_band", (0.0, 0.0)),
                        ("higher_is_better", None)):
        result = normalize_peer_metric("quality", 2.0, cohort, applicable=True, metric_shape=shape,
                                       comparison_scope="UNIVERSE", band=band, parent_percentile=0.8,
                                       shrinkage_strength=5.0, bootstrap_samples=20)
        assert result.percentile == pytest.approx(0.5)
        assert result.shrunk_percentile == pytest.approx((2 * 0.5 + 5 * 0.8) / 7)


def test_a10_f8_listing_fundamentals_aggregate_without_false_issuer_conflict() -> None:
    holdings = [_holding("Acme ordinary", APPLE_ISIN, 0.4, "acme"),
                _holding("Acme ADR", MICROSOFT_ISIN, 0.6, "acme")]
    facts = [{**_fundamental("acme", pe_ratio=22.1, roic=0.1), "isin": APPLE_ISIN},
             {**_fundamental("acme", pe_ratio=22.3, roic=0.2), "isin": MICROSOFT_ISIN}]
    for ordered in (facts, list(reversed(facts))):
        summary = _analyze(holdings, ordered)
        assert summary.calculated_metrics["pe_ratio"]["value"] == pytest.approx(1 / (0.4 / 22.1 + 0.6 / 22.3))
        assert summary.calculated_metrics["roic"]["value"] == pytest.approx(0.4 * 0.1 + 0.6 * 0.2)
        assert summary.fundamental_data_coverage["pe_ratio"]["covered_weight"] == 1.0
        assert summary.fundamental_data_coverage["roic"]["covered_weight"] == 1.0
        assert len(summary.concentration["top_holdings"]) == 1
        assert not any("Conflicting same-vintage" in warning for warning in summary.limitations)
        assert summary.execution_allowed is False
    # An actual contradiction within one listing still withholds its weight.
    conflict = {**facts[0], "pe_ratio": 30.0}
    summary = _analyze(holdings, [*facts, conflict])
    assert summary.fundamental_data_coverage["pe_ratio"]["covered_weight"] == pytest.approx(0.6)
    assert summary.calculated_metrics["pe_ratio"]["status"] == "unavailable"
