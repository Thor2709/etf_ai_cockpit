from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd

from etf_cockpit.analysis.fund_analysis import (
    FundAnalysisInput,
    FundDistributionObservation,
    FundNAVObservation,
    FundTermChangeEvent,
    FundTermChangeKind,
    FundUnderlyingLink,
    analyze_fund,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.fund_identity import (
    FundLifecycleEvent,
    FundLifecycleStatus,
    FundShareClass,
    FundStructure,
    FundTerm,
)


DECISION = datetime(2026, 2, 5, 12, tzinfo=timezone.utc)


def test_accumulating_return_matches_hand_calculated_values() -> None:
    accumulating = analyze_fund(_input())
    result = accumulating.return_decomposition

    # 104 / 100 - 1 = 0.04; no distribution; -50 bps * 34 / 365;
    # 0.04 - 50 / 10000 * 34 / 365 = 0.039534246575342465753424658.
    assert accumulating.status == "available"
    assert result.nav_change_return == Decimal("0.04")
    assert result.reinvested_distributions_return == Decimal("0")
    assert result.class_fee_return == Decimal("-0.0004657534246575342465753424658")
    assert result.total_return == Decimal("0.039534246575342465753424658")
    # (104 / 100 - 1 - 50 / 10000 * 34 / 365) -
    # (0.04 + 0 - 50 / 10000 * 34 / 365) = 0.
    assert result.residual == Decimal("0")
    assert abs(result.residual) <= result.reconciliation_tolerance


def test_distributing_return_matches_hand_calculated_values() -> None:
    distribution = FundDistributionObservation(
        ex_date=date(2026, 1, 15),
        available_at=datetime(2026, 1, 15, 17, tzinfo=timezone.utc),
        amount_per_share=Decimal("2"),
        source_id="distribution:jan",
    )
    distributing = analyze_fund(
        _input(
            distribution_policy="distributing",
            distributions=(distribution,),
            distribution_history_complete=True,
            nav_values=("100", "101", "102"),
        )
    )
    result = distributing.return_decomposition

    # Reinvest 2 / 101 units at the Jan 15 ex-date NAV: (1 + 2 / 101) *
    # 102 / 100 - 1 = 0.04019801980198019801980198. Minus the 0.02 NAV
    # change gives 0.02019801980198019801980198; subtract 50 bps * 34 / 365.
    assert distributing.status == "available"
    assert result.nav_change_return == Decimal("0.02")
    assert result.reinvested_distributions_return == Decimal("0.02019801980198019801980198")
    assert result.class_fee_return == Decimal("-0.0004657534246575342465753424658")
    assert result.total_return == Decimal("0.039732266377322663773226638")
    # Both (1 + 2 / 101) * 102 / 100 - 1 and
    # 0.02 + (((1 + 2 / 101) * 102 / 100 - 1) - 0.02) give the same gross
    # return, so after subtracting 50 / 10000 * 34 / 365 on each side the residual is 0.
    assert result.residual == Decimal("0")
    assert abs(result.residual) <= result.reconciliation_tolerance


def test_fee_change_after_nav_window_does_not_reprice_historical_interval() -> None:
    source = _input()
    fee_term = next(term for term in source.terms if term.name == "ongoing_fee_bps")
    terms = tuple(term for term in source.terms if term.name != "ongoing_fee_bps") + (
        replace(fee_term, valid_to="2026-02-05T00:00:00Z"),
        replace(
            fee_term,
            value="100",
            valid_from="2026-02-05T00:00:00Z",
            source_id="term:fee-increase",
        ),
    )

    record = analyze_fund(replace(source, terms=terms))

    # Jan 1 to Feb 4 is 34 days; the Feb 5 increase earns no days in this window.
    assert record.status == "available"
    assert record.total_fee_bps == Decimal("100")
    assert record.return_decomposition.class_fee_return == Decimal(
        "-0.0004657534246575342465753424658"
    )


def test_fee_term_coverage_gap_abstains() -> None:
    source = _input()
    fee_term = next(term for term in source.terms if term.name == "ongoing_fee_bps")
    terms = tuple(term for term in source.terms if term.name != "ongoing_fee_bps") + (
        replace(fee_term, valid_to="2026-01-20T00:00:00Z"),
        replace(
            fee_term,
            valid_from="2026-01-22T00:00:00Z",
            source_id="term:fee-after-gap",
        ),
    )

    record = analyze_fund(replace(source, terms=terms))

    assert record.status == "insufficient_evidence"
    assert record.return_decomposition.status == "insufficient_evidence"
    assert "insufficient_fee_term_coverage" in record.blockers
    assert record.return_decomposition.total_return is None


def test_intraday_fee_change_boundary_abstains() -> None:
    source = _input()
    fee_term = next(term for term in source.terms if term.name == "ongoing_fee_bps")
    boundary = "2026-01-20T12:00:00Z"
    terms = tuple(term for term in source.terms if term.name != "ongoing_fee_bps") + (
        replace(fee_term, valid_to=boundary),
        replace(
            fee_term,
            value="100",
            valid_from=boundary,
            source_id="term:fee-increase-noon",
        ),
    )

    record = analyze_fund(replace(source, terms=terms))

    assert record.status == "insufficient_evidence"
    assert "fee_term_intraday_boundary_unsupported" in record.blockers
    assert "fee_term_intraday_boundary_unsupported" in record.return_decomposition.reason_codes
    assert record.return_decomposition.class_fee_return is None


def test_intraday_fee_coverage_start_abstains() -> None:
    source = _input()
    fee_term = next(term for term in source.terms if term.name == "ongoing_fee_bps")
    terms = tuple(
        replace(term, valid_from="2026-01-20T12:00:00Z")
        if term is fee_term
        else term
        for term in source.terms
    )

    record = analyze_fund(replace(source, terms=terms))

    assert record.status == "insufficient_evidence"
    assert "fee_term_intraday_boundary_unsupported" in record.blockers
    assert record.return_decomposition.class_fee_return is None


def test_date_aligned_fee_change_still_accrues_by_day() -> None:
    source = _input()
    fee_term = next(term for term in source.terms if term.name == "ongoing_fee_bps")
    terms = tuple(term for term in source.terms if term.name != "ongoing_fee_bps") + (
        replace(fee_term, valid_to="2026-01-20T00:00:00Z"),
        replace(
            fee_term,
            value="100",
            valid_from="2026-01-20T00:00:00Z",
            source_id="term:fee-increase-midnight",
        ),
    )

    record = analyze_fund(replace(source, terms=terms))

    assert record.status == "available"
    assert record.total_fee_bps == Decimal("100")
    assert record.return_decomposition.class_fee_return == Decimal(
        "-0.0006712328767123287671232876713"
    )


def test_distribution_reinvests_at_exact_ex_date_nav() -> None:
    source = _input(
        distribution_policy="distributing",
        distributions=(
            FundDistributionObservation(
                date(2026, 1, 31),
                datetime(2026, 1, 31, 17, tzinfo=timezone.utc),
                Decimal("10"),
                "distribution:jan31",
            ),
        ),
        distribution_history_complete=True,
        nav_values=("100", "90"),
        nav_dates=(date(2026, 1, 1), date(2026, 1, 31)),
    )
    terms = tuple(
        replace(term, value="true") if term.name == "fees_reflected_in_nav" else term
        for term in source.terms
    )

    record = analyze_fund(replace(source, terms=terms))

    # 1 + 10 / 90 units, valued at the 90 end NAV, returns 100 / 100 - 1 = 0.
    assert record.status == "available"
    assert abs(record.return_decomposition.total_return) < Decimal("1e-26")


def test_distribution_without_ex_date_nav_abstains_instead_of_using_stale_nav() -> None:
    source = _input(
        distribution_policy="distributing",
        distributions=(
            FundDistributionObservation(
                date(2026, 1, 15),
                datetime(2026, 1, 15, 17, tzinfo=timezone.utc),
                Decimal("10"),
                "distribution:jan15",
            ),
        ),
        distribution_history_complete=True,
        nav_values=("100", "90"),
        nav_dates=(date(2026, 1, 1), date(2026, 2, 4)),
    )

    record = analyze_fund(source)

    assert record.status == "insufficient_evidence"
    assert record.return_decomposition.status == "insufficient_evidence"
    assert "missing_distribution_reinvestment_nav" in record.blockers
    assert record.return_decomposition.total_return is None


def test_hedged_and_unhedged_classes_use_point_in_time_fx() -> None:
    fx_rates = pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-01",
                "base_currency": "EUR",
                "quote_currency": "USD",
                "rate": 1.1,
                "source": "fixture-fx",
                "ingested_at": "2026-01-01T09:00:00Z",
            },
            {
                "as_of_date": "2026-02-03",
                "base_currency": "EUR",
                "quote_currency": "USD",
                "rate": 1.2,
                "source": "fixture-fx",
                "ingested_at": "2026-02-03T09:00:00Z",
            },
            {
                "as_of_date": "2026-02-04",
                "base_currency": "EUR",
                "quote_currency": "USD",
                "rate": 9.9,
                "source": "late-fx",
                "ingested_at": "2026-02-06T09:00:00Z",
            },
        ]
    )
    unhedged = analyze_fund(
        _input(selected_currency="USD", fx_rates=fx_rates, class_id="CLASS-U")
    )
    hedged = analyze_fund(
        _input(
            selected_currency="USD",
            fx_rates=fx_rates,
            class_id="CLASS-H",
            hedge_policy="hedged",
            hedge_currency="EUR",
        )
    )

    for result in (unhedged.return_decomposition, hedged.return_decomposition):
        assert result.status == "available"
        assert result.currency_hedge_policy in {"hedged", "unhedged"}
        assert result.fx_start_rate == Decimal("1.1")
        assert result.fx_end_rate == Decimal("1.2")
        assert result.fx_return == Decimal("1.2") / Decimal("1.1") - Decimal("1")
        assert "late-fx" not in result.evidence_references
    assert hedged.return_decomposition.hedge_currency == "EUR"


def test_etf_only_metrics_are_not_applicable_to_ordinary_funds() -> None:
    record = analyze_fund(_input())

    assert [metric.metric for metric in record.metric_applicability] == [
        "market_premium_discount",
        "exchange_spread",
        "intraday_liquidity",
    ]
    for metric in record.metric_applicability:
        assert metric.state.value == "not_applicable"
        assert metric.value is None
        assert metric.reason


def test_weekly_horizon_is_unsupported_for_monthly_dealing_and_cutoff_applies() -> None:
    record = analyze_fund(
        _input(
            decision_time=datetime(2026, 2, 4, 17, tzinfo=timezone.utc),
            horizon="1W",
            nav_values=("100", "101", "102"),
            nav_dates=(date(2026, 1, 1), date(2026, 1, 15), date(2026, 2, 4)),
        )
    )

    assert record.status == "unsupported"
    assert "unsupported_horizon_for_dealing_frequency" in record.blockers
    assert record.return_decomposition.end_nav_date == date(2026, 1, 15)


def test_fund_of_funds_stacks_known_underlying_fees_and_abstains_if_unknown() -> None:
    links = (
        FundUnderlyingLink(
            "FUND-1", "UNDER-1", Decimal("0.6"), Decimal("30"),
            date(2026, 1, 1), "2026-01-01T09:00:00Z", "link:one", terminal_holding=True,
        ),
        FundUnderlyingLink(
            "FUND-1", "UNDER-2", Decimal("0.4"), Decimal("20"),
            date(2026, 1, 1), "2026-01-01T09:00:00Z", "link:two", terminal_holding=True,
        ),
    )
    known = analyze_fund(_input(underlying_structure="fund_of_funds", underlying_links=links))
    unknown = analyze_fund(
        _input(
            underlying_structure="fund_of_funds",
            underlying_links=(links[0], replace(links[1], ongoing_fee_bps=None)),
        )
    )

    assert known.total_fee_bps == Decimal("76")
    assert known.fee_stack_status == "complete"
    assert unknown.total_fee_bps is None
    assert unknown.fee_stack_status == "fee_stack_incomplete"
    assert "fee_stack_incomplete" in unknown.blockers
    assert unknown.return_decomposition.total_return is None


def test_fee_stack_uses_latest_applicable_allocation_snapshot_and_rejects_duplicates() -> None:
    old_snapshot = FundUnderlyingLink(
        "FUND-1", "UNDER-1", Decimal("1"), Decimal("30"),
        date(2026, 1, 1), "2026-01-01T09:00:00Z", "link:old-snapshot", terminal_holding=True,
    )
    latest_snapshot = replace(
        old_snapshot,
        ongoing_fee_bps=Decimal("40"),
        as_of=date(2026, 2, 1),
        available_at="2026-02-01T09:00:00Z",
        source_id="link:latest-snapshot",
    )
    latest = analyze_fund(
        _input(underlying_structure="fund_of_funds", underlying_links=(old_snapshot, latest_snapshot))
    )
    duplicate = analyze_fund(
        _input(
            underlying_structure="fund_of_funds",
            underlying_links=(
                latest_snapshot,
                replace(latest_snapshot, ongoing_fee_bps=Decimal("45"), source_id="link:duplicate"),
            ),
        )
    )

    assert latest.total_fee_bps == Decimal("90")
    assert latest.fee_stack_status == "complete"
    assert duplicate.total_fee_bps is None
    assert duplicate.fee_stack_status == "fee_stack_incomplete"


def test_fee_stack_traverses_nested_links_and_marks_missing_fees_or_cycles_incomplete() -> None:
    root_to_master = FundUnderlyingLink(
        "FUND-1", "MASTER-1", Decimal("1"), Decimal("30"),
        date(2026, 1, 1), "2026-01-01T09:00:00Z", "link:root-master",
    )
    master_to_underlying = FundUnderlyingLink(
        "MASTER-1", "UNDER-1", Decimal("1"), Decimal("20"),
        date(2026, 1, 1), "2026-01-01T09:00:00Z", "link:master-underlying", terminal_holding=True,
    )
    complete = analyze_fund(
        _input(
            underlying_structure="master_feeder",
            underlying_links=(root_to_master, master_to_underlying),
        )
    )
    missing_child_links = analyze_fund(
        _input(
            underlying_structure="master_feeder",
            underlying_links=(root_to_master,),
        )
    )
    missing_fee = analyze_fund(
        _input(
            underlying_structure="master_feeder",
            underlying_links=(root_to_master, replace(master_to_underlying, ongoing_fee_bps=None)),
        )
    )
    cycle = analyze_fund(
        _input(
            underlying_structure="master_feeder",
            underlying_links=(
                root_to_master,
                replace(master_to_underlying, underlying_fund_id="FUND-1"),
            ),
        )
    )

    assert complete.total_fee_bps == Decimal("100")
    assert complete.fee_stack_status == "complete"
    assert missing_child_links.fee_stack_status == "fee_stack_incomplete"
    assert "fee_stack_incomplete_holding:MASTER-1" in missing_child_links.blockers
    assert missing_fee.fee_stack_status == "fee_stack_incomplete"
    assert cycle.fee_stack_status == "fee_stack_incomplete"


def test_missing_benchmark_fee_dealing_or_history_abstains_without_zero_fills() -> None:
    full = _input()
    missing_benchmark = replace(
        full, terms=tuple(term for term in full.terms if term.name != "benchmark_id")
    )
    missing_fee = replace(
        full, terms=tuple(term for term in full.terms if term.name != "ongoing_fee_bps")
    )
    missing_dealing = replace(
        full, terms=tuple(term for term in full.terms if term.name != "dealing_cutoff")
    )
    missing_history = replace(full, nav_history=())
    late_manager_change = FundTermChangeEvent(
        "FUND-1", FundTermChangeKind.MANAGER_CHANGE, "2026-02-01T00:00:00Z",
        "2026-02-06T00:00:00Z", "manager:late", SourceAuthority.OFFICIAL, "A", "B",
    )
    late_closure = FundLifecycleEvent(
        fund_id="FUND-1",
        event_id="closure:late",
        status=FundLifecycleStatus.CLOSED,
        effective_at="2026-02-06T00:00:00Z",
        available_at="2026-02-06T00:00:00Z",
        source="fixture",
        source_id="closure:late",
        authority=SourceAuthority.OFFICIAL,
    )
    missing_history = replace(
        missing_history,
        term_change_events=(late_manager_change,),
        lifecycle_events=(late_closure,),
        lifecycle_history_complete=True,
    )

    for source, blocker in (
        (missing_benchmark, "missing_benchmark"),
        (missing_fee, "missing_fee"),
        (missing_dealing, "missing_dealing_cutoff"),
        (missing_history, "insufficient_nav_history"),
    ):
        record = analyze_fund(source)
        result = record.return_decomposition
        assert record.status == "insufficient_evidence"
        assert blocker in record.blockers
        assert result.total_return is None
        assert result.nav_change_return is None
        assert result.reinvested_distributions_return is None
        assert result.class_fee_return is None
    no_history_record = analyze_fund(missing_history)
    assert no_history_record.lifecycle_risk.manager_change is False
    assert no_history_record.lifecycle_risk.closure_risk is False


def test_lifecycle_flags_preserve_observed_events_with_incomplete_history() -> None:
    available_closure = FundLifecycleEvent(
        fund_id="FUND-1",
        event_id="closure:known",
        status=FundLifecycleStatus.CLOSED,
        effective_at="2026-02-01T00:00:00Z",
        available_at="2026-02-01T00:00:00Z",
        source="fixture",
        source_id="closure:known",
        authority=SourceAuthority.OFFICIAL,
    )
    available_merger = replace(
        available_closure,
        event_id="merger:known",
        status=FundLifecycleStatus.MERGED,
        source_id="merger:known",
        successor_fund_id="FUND-2",
    )
    known_changes = tuple(
        FundTermChangeEvent(
            "FUND-1",
            kind,
            "2026-02-01T00:00:00Z",
            "2026-02-01T00:00:00Z",
            f"{kind.value}:known",
            SourceAuthority.OFFICIAL,
            "old",
            "new",
        )
        for kind in (
            FundTermChangeKind.MANAGER_CHANGE,
            FundTermChangeKind.BENCHMARK_CHANGE,
            FundTermChangeKind.FEE_CHANGE,
        )
    )
    observed = analyze_fund(
        replace(
            _input(),
            lifecycle_history_complete=False,
            lifecycle_events=(available_closure, available_merger),
            term_change_events=known_changes,
        )
    ).lifecycle_risk
    incomplete_empty = analyze_fund(
        replace(_input(), lifecycle_history_complete=False)
    ).lifecycle_risk
    complete_empty = analyze_fund(
        replace(_input(), lifecycle_history_complete=True)
    ).lifecycle_risk

    assert observed.closure_risk is True
    assert observed.merger_risk is True
    assert observed.manager_change is True
    assert observed.benchmark_change is True
    assert observed.fee_change is True
    assert all(
        value is None
        for value in (
            incomplete_empty.closure_risk,
            incomplete_empty.merger_risk,
            incomplete_empty.manager_change,
            incomplete_empty.benchmark_change,
            incomplete_empty.fee_change,
        )
    )
    assert all(
        value is False
        for value in (
            complete_empty.closure_risk,
            complete_empty.merger_risk,
            complete_empty.manager_change,
            complete_empty.benchmark_change,
            complete_empty.fee_change,
        )
    )


def _input(
    *,
    decision_time: datetime = DECISION,
    horizon: str = "1M",
    distribution_policy: str = "accumulating",
    distributions: tuple[FundDistributionObservation, ...] = (),
    distribution_history_complete: bool | None = None,
    nav_values: tuple[str, ...] = ("100", "101", "104"),
    nav_dates: tuple[date, ...] = (date(2026, 1, 1), date(2026, 1, 15), date(2026, 2, 4)),
    selected_currency: str = "EUR",
    fx_rates: pd.DataFrame | None = None,
    class_id: str = "CLASS-A",
    hedge_policy: str = "unhedged",
    hedge_currency: str | None = None,
    underlying_structure: str = "single",
    underlying_links: tuple[FundUnderlyingLink, ...] = (),
) -> FundAnalysisInput:
    terms = [
        _term("benchmark_id", "INDEX-1", "term:benchmark"),
        _term("ongoing_fee_bps", "50", "term:fee"),
        _term("fees_reflected_in_nav", "false", "term:fee-treatment"),
        _term("dealing_cutoff", "16:00", "term:cutoff"),
        _term("dealing_frequency", "monthly", "term:frequency"),
        _term("share_class_currency", "EUR", "term:currency"),
        _term("currency_hedge", hedge_policy, "term:hedge-policy"),
    ]
    if hedge_currency is not None:
        terms.append(_term("hedge_currency", hedge_currency, "term:hedge-currency"))
    nav_history = tuple(
        FundNAVObservation(
            as_of=as_of,
            available_at=datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc),
            nav_per_share=Decimal(value),
            source_id=f"nav:{as_of.isoformat()}",
        )
        for as_of, value in zip(nav_dates, nav_values, strict=True)
    )
    return FundAnalysisInput(
        fund_id="FUND-1",
        share_class=FundShareClass(class_id, "FUND-1", distribution_policy, ("class:source",), "class:policy"),
        structure=FundStructure.ORDINARY_FUND,
        decision_time=decision_time,
        horizon=horizon,
        selected_currency=selected_currency,
        terms=tuple(terms),
        nav_history=nav_history,
        distributions=distributions,
        underlying_structure=underlying_structure,
        underlying_links=underlying_links,
        distribution_history_complete=distribution_history_complete,
        lifecycle_history_complete=True,
        fx_rates=fx_rates,
    )


def _term(name: str, value: str, source_id: str) -> FundTerm:
    return FundTerm(
        name=name,
        value=value,
        available_at="2025-01-01T00:00:00Z",
        valid_from="2025-01-01T00:00:00Z",
        source_id=source_id,
    )
