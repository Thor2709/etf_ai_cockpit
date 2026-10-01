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


def test_accumulating_and_distributing_returns_reconcile_with_class_fees() -> None:
    accumulating = analyze_fund(_input())
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

    for record in (accumulating, distributing):
        result = record.return_decomposition
        assert record.status == "available"
        assert result.total_return is not None
        assert result.nav_change_return is not None
        assert result.reinvested_distributions_return is not None
        assert result.class_fee_return is not None
        assert result.residual is not None
        expected = (
            Decimal("1")
            + result.nav_change_return
            + result.reinvested_distributions_return
            + result.class_fee_return
        ) * (Decimal("1") + result.fx_return) - Decimal("1")
        assert abs(result.total_return - expected) <= result.reconciliation_tolerance
        assert abs(result.residual) <= result.reconciliation_tolerance
    assert accumulating.return_decomposition.reinvested_distributions_return == Decimal("0")
    assert distributing.return_decomposition.reinvested_distributions_return > Decimal("0")
    assert accumulating.return_decomposition.class_fee_return < Decimal("0")


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
            date(2026, 1, 1), "2026-01-01T09:00:00Z", "link:one",
        ),
        FundUnderlyingLink(
            "FUND-1", "UNDER-2", Decimal("0.4"), Decimal("20"),
            date(2026, 1, 1), "2026-01-01T09:00:00Z", "link:two",
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
