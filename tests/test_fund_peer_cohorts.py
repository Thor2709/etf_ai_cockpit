from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import math
from pathlib import Path
import statistics

import pandas as pd
import pytest
import yaml

from etf_cockpit.analysis.fund_analysis import (
    FUND_RETURN_CONTRACT,
    FUND_ANALYSIS_CONFIG,
    FundAnalysisError,
    FundAnalysisRecord,
    FundLifecycleRisk,
    FundReturnDecomposition,
    load_fund_analysis_config,
)
from etf_cockpit.analysis.fund_peers import (
    FundPeerFund,
    build_fund_peer_cohort,
    calculate_fund_benchmark_metrics,
)
from etf_cockpit.analysis.peer_cohorts import (
    PeerCohortError,
    PeerObservation,
    construct_cohort,
)
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.etf_economics import TotalReturnEvidence
from etf_cockpit.data.fund_identity import (
    FundLifecycleEvent,
    FundLifecycleStatus,
    FundMetricState,
    FundShareClass,
    FundStructure,
)
from etf_cockpit.data.market_adjustments import (
    CorporateActionCoverage,
    CorporateActionCoverageStore,
    apply_total_return_adjustments,
)


DECISION = "2025-01-02T00:00:00Z"
EFFECTIVE = "2025-01-01T00:00:00Z"
START = date(2024, 1, 1)
END = date(2025, 1, 1)


def test_fund_dimensions_form_expected_leaves_and_sparse_leaf_falls_back() -> None:
    config = replace(load_fund_analysis_config(), peer_minimum_support=3)
    target = _fund(
        "TARGET",
        "TARGET-CLASS",
        mandate="index",
        distribution="accumulating",
        hedge="unhedged",
    )
    exact = tuple(
        _fund(
            f"EXACT-{index}",
            f"EXACT-{index}-CLASS",
            mandate="index",
            distribution="accumulating",
            hedge="unhedged",
        )
        for index in range(3)
    )
    leaf = build_fund_peer_cohort(
        target, exact, effective_at=EFFECTIVE, decision_time=DECISION, config=config
    )
    assert leaf.cohort.cohort_key == (
        "FUND_PEERS:vehicle+mandate+benchmark_objective+geography_sector+asset_class"
        "+currency_hedge+distribution_policy+fee_tier+dealing_class"
    )
    assert leaf.status == "available"
    assert leaf.cohort.support == 3

    active = _fund(
        "ACTIVE",
        "ACTIVE-CLASS",
        mandate="active",
        distribution="distributing",
        hedge="hedged",
        hedge_currency="EUR",
    )
    active_peers = tuple(
        _fund(
            f"ACTIVE-{index}",
            f"ACTIVE-{index}-CLASS",
            mandate="active",
            distribution="distributing",
            hedge="hedged",
            hedge_currency="EUR",
        )
        for index in range(3)
    )
    active_leaf = build_fund_peer_cohort(
        active,
        (*active_peers, exact[0]),
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        config=config,
    )
    assert active_leaf.cohort.cohort_key.endswith(
        "+currency_hedge+distribution_policy+fee_tier+dealing_class"
    )
    assert active_leaf.cohort.support == 3
    assert "EXACT-0-CLASS" not in active_leaf.cohort.members

    sparse = build_fund_peer_cohort(
        target,
        (
            exact[0],
            _fund("DISTRIBUTING-1", "DISTRIBUTING-1-CLASS", distribution="distributing"),
            _fund("DISTRIBUTING-2", "DISTRIBUTING-2-CLASS", distribution="distributing"),
        ),
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        config=config,
    )
    assert sparse.cohort.cohort_key == (
        "FUND_PEERS:vehicle+mandate+benchmark_objective+geography_sector+asset_class"
        "+currency_hedge"
    )
    assert sparse.cohort.fallback_path[-1] == sparse.cohort.cohort_key
    assert sparse.cohort.support == 3


def test_share_classes_count_once_and_collapsed_classes_are_auditable() -> None:
    config = replace(load_fund_analysis_config(), peer_minimum_support=1)
    target = _fund("TARGET", "TARGET-CLASS")
    classes = tuple(
        _fund(
            "PEER-FUND",
            f"PEER-CLASS-{letter}",
            sub_fund_id="PEER-MANDATE",
            return_value=Decimal(value),
        )
        for letter, value in (("A", "0.01"), ("B", "0.02"), ("C", "0.03"))
    )

    result = build_fund_peer_cohort(
        target,
        classes,
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        config=config,
    )

    assert result.cohort.support == 1
    assert len(result.cohort.members) == 1
    assert result.cohort.observations[0].economic_strategy_id == "PEER-MANDATE"
    assert result.collapsed_share_classes[0].retained_share_class_id == "PEER-CLASS-A"
    assert result.collapsed_share_classes[0].collapsed_share_class_ids == (
        "PEER-CLASS-B",
        "PEER-CLASS-C",
    )
    assert result.peer_metric.raw_value == pytest.approx(0.01)


def test_share_class_representative_does_not_change_when_returns_are_swapped() -> None:
    config = replace(load_fund_analysis_config(), peer_minimum_support=1)
    target = _fund("TARGET", "TARGET-CLASS")

    def cohort(old_return: str, new_return: str):
        old_launch = FundLifecycleEvent(
            fund_id="PEER-OLD",
            event_id="old-launch",
            status=FundLifecycleStatus.LAUNCHED,
            effective_at="2010-01-01T00:00:00Z",
            available_at="2010-01-02T00:00:00Z",
            source="fixture",
            source_id="old-launch-source",
            authority=SourceAuthority.OFFICIAL,
        )
        new_launch = FundLifecycleEvent(
            fund_id="PEER-NEW",
            event_id="new-launch",
            status=FundLifecycleStatus.LAUNCHED,
            effective_at="2015-01-01T00:00:00Z",
            available_at="2015-01-02T00:00:00Z",
            source="fixture",
            source_id="new-launch-source",
            authority=SourceAuthority.OFFICIAL,
        )
        peers = (
            _fund(
                "PEER-OLD",
                "PEER-CLASS-Z",
                sub_fund_id="PEER-MANDATE",
                return_value=Decimal(old_return),
                lifecycle_events=(old_launch,),
            ),
            _fund(
                "PEER-NEW",
                "PEER-CLASS-A",
                sub_fund_id="PEER-MANDATE",
                return_value=Decimal(new_return),
                lifecycle_events=(new_launch,),
            ),
        )
        return build_fund_peer_cohort(
            target,
            peers,
            effective_at=EFFECTIVE,
            decision_time=DECISION,
            config=config,
        )

    old_class_wins = cohort("0.01", "0.99")
    old_class_loses = cohort("0.99", "0.01")

    assert old_class_wins.cohort.observations[0].instrument_id == "PEER-CLASS-Z"
    assert old_class_loses.cohort.observations[0].instrument_id == "PEER-CLASS-Z"
    assert old_class_wins.cohort.observations[0].value == pytest.approx(0.01)
    assert old_class_loses.cohort.observations[0].value == pytest.approx(0.99)
    assert old_class_wins.collapsed_share_classes[0].retained_share_class_id == (
        "PEER-CLASS-Z"
    )
    assert old_class_wins.share_class_representative_rule == (
        "earliest_inception_then_share_class_id"
    )


def test_fund_peer_engine_keeps_caller_representative_when_returns_are_swapped() -> None:
    target = _fund("TARGET", "TARGET-CLASS")
    representative = _fund("PEER-REPRESENTATIVE", "PEER-CLASS-Z")
    alternate = _fund("PEER-ALTERNATE", "PEER-CLASS-A")
    dimensions = {
        "TARGET-CLASS": {"mandate": "index"},
        "PEER-CLASS-Z": {"mandate": "index"},
        "PEER-CLASS-A": {"mandate": "index"},
    }

    def members(representative_return: float, alternate_return: float) -> tuple[str, ...]:
        return construct_cohort(
            target.context,
            (
                PeerObservation(
                    representative.context.instrument_id,
                    representative.context,
                    "total_return",
                    representative_return,
                    1.0,
                    EFFECTIVE,
                    "2024-12-31T00:00:00Z",
                    economic_strategy_id="PEER-MANDATE",
                ),
                PeerObservation(
                    alternate.context.instrument_id,
                    alternate.context,
                    "total_return",
                    alternate_return,
                    1.0,
                    EFFECTIVE,
                    "2024-12-31T00:00:00Z",
                    economic_strategy_id="PEER-MANDATE",
                ),
            ),
            metric="total_return",
            effective_at=EFFECTIVE,
            decision_time=DECISION,
            minimum_support=1,
            comparison_scope="FUND_PEERS",
            comparison_dimension_order=("mandate",),
            comparison_dimension_groups=dimensions,
        ).members

    assert members(0.01, 0.99) == ("PEER-CLASS-Z",)
    assert members(0.99, 0.01) == ("PEER-CLASS-Z",)


def test_share_class_representative_without_inception_uses_id_not_window_start() -> None:
    config = replace(load_fund_analysis_config(), peer_minimum_support=1)
    target = _fund("TARGET", "TARGET-CLASS")
    class_z = _fund(
        "PEER-Z",
        "PEER-CLASS-Z",
        sub_fund_id="PEER-MANDATE",
        start=date(2023, 12, 27),
        end=date(2024, 12, 27),
    )
    class_a = _fund(
        "PEER-A",
        "PEER-CLASS-A",
        sub_fund_id="PEER-MANDATE",
        start=date(2024, 1, 1),
        end=date(2025, 1, 1),
    )

    result = build_fund_peer_cohort(
        target,
        (class_z, class_a),
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        config=config,
    )

    assert result.collapsed_share_classes[0].retained_share_class_id == (
        "PEER-CLASS-A"
    )
    assert result.share_class_representative_rule == (
        "share_class_id_no_inception_evidence"
    )


def test_lifecycle_window_and_future_known_observations_are_point_in_time() -> None:
    config = replace(load_fund_analysis_config(), peer_minimum_support=1)
    target = _fund(
        "TARGET",
        "TARGET-CLASS",
        start=date(2023, 5, 31),
        end=date(2024, 5, 31),
    )
    merged = FundLifecycleEvent(
        fund_id="MERGED-FUND",
        event_id="merge-event",
        status=FundLifecycleStatus.MERGED,
        effective_at="2024-06-01T00:00:00Z",
        available_at="2024-06-02T00:00:00Z",
        source="fixture",
        source_id="merge-source",
        authority=SourceAuthority.OFFICIAL,
        successor_fund_id="SUCCESSOR",
    )
    merged_fund = _fund(
        "MERGED-FUND",
        "MERGED-CLASS",
        record_known_at="2024-05-31T00:00:00Z",
        lifecycle_events=(merged,),
        start=date(2023, 5, 31),
        end=date(2024, 5, 31),
    )
    before = build_fund_peer_cohort(
        target,
        (merged_fund,),
        effective_at="2024-05-31T00:00:00Z",
        decision_time=DECISION,
        config=config,
    )
    after = build_fund_peer_cohort(
        target,
        (merged_fund,),
        effective_at="2024-06-02T00:00:00Z",
        decision_time=DECISION,
        config=config,
    )
    assert "MERGED-CLASS" in before.cohort.members
    assert "MERGED-CLASS" not in after.cohort.members
    assert before.peer_lifecycle_risks[0][0] == "MERGED-FUND"
    assert after.peer_lifecycle_risks == ()

    future_known = _fund(
        "FUTURE-FUND",
        "FUTURE-CLASS",
        record_known_at="2025-01-03T00:00:00Z",
    )
    excluded = build_fund_peer_cohort(
        target,
        (future_known,),
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        config=config,
    )
    assert "FUTURE-CLASS" not in excluded.cohort.members
    assert excluded.cohort.exclusions["FUTURE-CLASS"] == "future_known"


def test_future_known_target_fund_record_is_unavailable() -> None:
    target = _fund(
        "TARGET",
        "TARGET-CLASS",
        record_known_at="2025-01-03T00:00:00Z",
    )
    result = build_fund_peer_cohort(
        target,
        (_fund("PEER", "PEER-CLASS"),),
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        config=replace(load_fund_analysis_config(), peer_minimum_support=1),
    )

    assert result.status == "unavailable"
    assert result.abstention_reason == "target_not_known_at_decision"
    assert result.peer_metric.reason_code == "TARGET_NOT_KNOWN_AT_DECISION"


def test_misaligned_peer_return_window_is_excluded() -> None:
    target = _fund("TARGET", "TARGET-CLASS")
    peer = _fund(
        "PEER",
        "PEER-CLASS",
        start=date(2023, 12, 26),
        end=date(2024, 12, 26),
    )
    result = build_fund_peer_cohort(
        target,
        (peer,),
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        config=replace(load_fund_analysis_config(), peer_minimum_support=1),
    )

    assert "PEER-CLASS" not in result.cohort.members
    assert result.cohort.exclusions["PEER-CLASS"] == "window_misaligned"


def test_benchmark_excess_tracking_difference_and_error_match_hand_values(tmp_path) -> None:
    window = _record(
        "FUND",
        "CLASS",
        Decimal("0.10"),
        start=START,
        end=END,
        benchmark_id="DISCLOSURE-INDEX",
    )
    middle = date(2024, 7, 1)
    periods = (
        _record(
            "FUND",
            "CLASS",
            Decimal("0.10"),
            start=START,
            end=middle,
            benchmark_id="DISCLOSURE-INDEX",
        ),
        _record(
            "FUND",
            "CLASS",
            Decimal("0.00"),
            start=middle,
            end=END,
            benchmark_id="DISCLOSURE-INDEX",
        ),
    )
    benchmark = _benchmark_series(
        "DISCLOSURE-INDEX",
        START,
        END,
        {START: 100.0, middle: 100.0, END: 105.0},
        coverage_directory=tmp_path / "benchmark-coverage",
    )

    result = calculate_fund_benchmark_metrics(
        window,
        benchmark,
        decision_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
        mandate="index",
        periodic_fund_returns=periods,
        tracking_minimum_periods=2,
    )

    elapsed_years = Decimal((END - START).days) / Decimal("365.2425")
    expected_difference = (
        Decimal("1.10") ** (Decimal(1) / elapsed_years)
        - Decimal("1.05") ** (Decimal(1) / elapsed_years)
    )
    observed_periods_per_year = Decimal(2) / elapsed_years
    expected_error = statistics.stdev((0.10, -0.05)) * math.sqrt(
        float(observed_periods_per_year)
    )
    assert result.excess_total_return.state is FundMetricState.AVAILABLE
    assert result.excess_total_return.value == Decimal("0.05")
    assert result.tracking_difference.state is FundMetricState.AVAILABLE
    assert float(result.tracking_difference.value) == pytest.approx(float(expected_difference))
    assert result.tracking_error.state is FundMetricState.AVAILABLE
    assert float(result.tracking_error.value) == pytest.approx(expected_error)


def test_future_known_window_fund_record_makes_excess_unavailable(tmp_path) -> None:
    window = _record(
        "FUND",
        "CLASS",
        Decimal("0.10"),
        start=START,
        end=END,
        benchmark_id="DISCLOSURE-INDEX",
        decision_time=datetime(2025, 1, 3, tzinfo=timezone.utc),
    )
    result = _benchmark_metrics(window, (), tmp_path)

    assert result.excess_total_return.state is FundMetricState.UNAVAILABLE
    assert result.excess_total_return.reason == "fund_record_not_known_at_decision"


def test_future_known_periodic_fund_record_makes_tracking_unavailable(tmp_path) -> None:
    window = _record(
        "FUND", "CLASS", Decimal("0.10"), start=START, end=END,
        benchmark_id="DISCLOSURE-INDEX",
    )
    middle = date(2024, 7, 1)
    periods = (
        _record(
            "FUND", "CLASS", Decimal("0.05"), start=START, end=middle,
            benchmark_id="DISCLOSURE-INDEX",
        ),
        _record(
            "FUND", "CLASS", Decimal("0.05"), start=middle, end=END,
            benchmark_id="DISCLOSURE-INDEX",
            decision_time=datetime(2025, 1, 3, tzinfo=timezone.utc),
        ),
    )
    result = _benchmark_metrics(window, periods, tmp_path)

    assert result.excess_total_return.state is FundMetricState.AVAILABLE
    assert result.tracking_difference.reason == (
        "periodic_fund_record_not_known_at_decision"
    )
    assert result.tracking_error.reason == (
        "periodic_fund_record_not_known_at_decision"
    )


def test_tracking_rejects_periodic_returns_for_a_foreign_fund(tmp_path) -> None:
    window = _record(
        "FUND", "CLASS", Decimal("0.10"), start=START, end=END,
        benchmark_id="DISCLOSURE-INDEX",
    )
    periodic = _record(
        "OTHER-FUND", "CLASS", Decimal("0.10"), start=START,
        end=date(2024, 7, 1), benchmark_id="DISCLOSURE-INDEX",
    )
    result = _benchmark_metrics(window, (periodic,), tmp_path)

    assert result.tracking_difference.reason == "periodic_fund_identity_mismatch"
    assert result.tracking_error.reason == "periodic_fund_identity_mismatch"


def test_tracking_rejects_periodic_returns_for_a_foreign_share_class(tmp_path) -> None:
    window = _record(
        "FUND", "CLASS", Decimal("0.10"), start=START, end=END,
        benchmark_id="DISCLOSURE-INDEX",
    )
    periodic = _record(
        "FUND", "OTHER-CLASS", Decimal("0.10"), start=START,
        end=date(2024, 7, 1), benchmark_id="DISCLOSURE-INDEX",
    )
    result = _benchmark_metrics(window, (periodic,), tmp_path)

    assert result.tracking_difference.reason == "periodic_share_class_mismatch"
    assert result.tracking_error.reason == "periodic_share_class_mismatch"


def test_tracking_rejects_periodic_returns_in_a_foreign_currency(tmp_path) -> None:
    window = _record(
        "FUND", "CLASS", Decimal("0.10"), start=START, end=END,
        benchmark_id="DISCLOSURE-INDEX",
    )
    periodic = _record(
        "FUND", "CLASS", Decimal("0.10"), start=START,
        end=date(2024, 7, 1), benchmark_id="DISCLOSURE-INDEX",
    )
    periodic = replace(
        periodic,
        return_decomposition=replace(
            periodic.return_decomposition, selected_currency="USD"
        ),
    )
    result = _benchmark_metrics(window, (periodic,), tmp_path)

    assert result.tracking_difference.reason == "periodic_currency_mismatch"
    assert result.tracking_error.reason == "periodic_currency_mismatch"


def test_benchmark_absence_date_mismatch_and_short_series_abstain_distinctly(
    tmp_path,
) -> None:
    window = _record(
        "FUND",
        "CLASS",
        Decimal("0.10"),
        start=START,
        end=END,
        benchmark_id="DISCLOSURE-INDEX",
    )
    period = _record(
        "FUND",
        "CLASS",
        Decimal("0.10"),
        start=START,
        end=END,
        benchmark_id="DISCLOSURE-INDEX",
    )
    decision = datetime(2025, 1, 2, tzinfo=timezone.utc)
    missing = calculate_fund_benchmark_metrics(
        replace(window, benchmark_id=None),
        None,
        decision_time=decision,
        mandate="index",
    )
    mismatch = calculate_fund_benchmark_metrics(
        window,
        _benchmark_series(
            "DISCLOSURE-INDEX",
            date(2024, 1, 2),
            END,
            {date(2024, 1, 2): 100.0, END: 105.0},
            coverage_directory=tmp_path / "mismatch-coverage",
        ),
        decision_time=decision,
        mandate="index",
        periodic_fund_returns=(period,),
        tracking_minimum_periods=2,
    )
    too_few = calculate_fund_benchmark_metrics(
        window,
        _benchmark_series(
            "DISCLOSURE-INDEX",
            START,
            END,
            {START: 100.0, END: 105.0},
            coverage_directory=tmp_path / "short-coverage",
        ),
        decision_time=decision,
        mandate="index",
        periodic_fund_returns=(period,),
        tracking_minimum_periods=2,
    )
    future_benchmark = calculate_fund_benchmark_metrics(
        window,
        _benchmark_series(
            "DISCLOSURE-INDEX",
            START,
            END,
            {START: 100.0, END: 105.0},
            coverage_directory=tmp_path / "future-coverage",
            known_at="2025-01-03T00:00:00Z",
        ),
        decision_time=decision,
        mandate="index",
        periodic_fund_returns=(period,),
        tracking_minimum_periods=2,
    )

    assert missing.excess_total_return.reason == "missing_disclosure_benchmark"
    assert mismatch.excess_total_return.reason == "date_mismatch"
    assert mismatch.tracking_difference.reason == "date_mismatch"
    assert too_few.tracking_difference.reason == "too_few_periods"
    assert future_benchmark.excess_total_return.reason == (
        "benchmark_not_known_at_decision"
    )
    for result in (missing, mismatch, too_few, future_benchmark):
        for metric in (
            result.excess_total_return,
            result.tracking_difference,
            result.tracking_error,
        ):
            if metric.state is not FundMetricState.AVAILABLE:
                assert metric.value is None


def test_insufficient_fallback_support_and_missing_peer_config_fail_closed(tmp_path) -> None:
    target = _fund("TARGET", "TARGET-CLASS")
    sparse = build_fund_peer_cohort(
        target,
        (_fund("PEER", "PEER-CLASS"),),
        effective_at=EFFECTIVE,
        decision_time=DECISION,
    )
    assert sparse.status == "unavailable"
    assert sparse.abstention_reason == "insufficient_peer_support"
    assert sparse.peer_metric.raw_value == pytest.approx(0.01)
    assert sparse.peer_metric.reason_code == "INSUFFICIENT_PEER_SUPPORT"

    config = yaml.safe_load(FUND_ANALYSIS_CONFIG.read_text(encoding="utf-8"))
    config.pop("peers")
    missing_peers_config = tmp_path / "fund_analysis_without_peers.yaml"
    missing_peers_config.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(FundAnalysisError):
        load_fund_analysis_config(missing_peers_config)


def test_stock_and_etf_scope_outputs_stay_stable_and_reject_fund_contexts() -> None:
    stock_target = _context(
        "STOCK-TARGET", instrument_type="stock", effective_at=EFFECTIVE
    )
    stock_peer = _context(
        "STOCK-PEER", instrument_type="stock", effective_at=EFFECTIVE
    )
    stock = construct_cohort(
        stock_target,
        (_peer_observation(stock_peer),),
        metric="quality",
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        minimum_support=1,
    )
    assert (
        stock.cohort_key,
        stock.fallback_path,
        stock.members,
        stock.support,
    ) == ("sector", ("sector",), ("STOCK-PEER",), 1)

    etf_target = _context("ETF-TARGET", instrument_type="etf")
    etf_peer = _context("ETF-PEER", instrument_type="etf")
    etf = construct_cohort(
        etf_target,
        (_peer_observation(etf_peer),),
        metric="quality",
        effective_at=EFFECTIVE,
        decision_time=DECISION,
        minimum_support=1,
        comparison_scope="ETF_EXPOSURE_PEERS",
        comparison_groups={
            "ETF_EXPOSURE_PEERS": {"ETF-TARGET": "group", "ETF-PEER": "group"}
        },
    )
    assert (
        etf.cohort_key,
        etf.fallback_path,
        etf.members,
        etf.support,
    ) == (
        "ETF_EXPOSURE_PEERS",
        ("ETF_EXPOSURE_PEERS",),
        ("ETF-PEER",),
        1,
    )

    fund_context = _context("FUND-CONTEXT", instrument_type="ordinary_fund")
    fund_observation = _peer_observation(fund_context)
    with pytest.raises(PeerCohortError):
        construct_cohort(
            fund_context,
            (fund_observation,),
            metric="quality",
            effective_at=EFFECTIVE,
            decision_time=DECISION,
            minimum_support=1,
        )
    with pytest.raises(PeerCohortError):
        construct_cohort(
            fund_context,
            (fund_observation,),
            metric="quality",
            effective_at=EFFECTIVE,
            decision_time=DECISION,
            minimum_support=1,
            comparison_scope="ETF_EXPOSURE_PEERS",
            comparison_groups={"ETF_EXPOSURE_PEERS": {"FUND-CONTEXT": "group"}},
        )


def _fund(
    fund_id: str,
    class_id: str,
    *,
    mandate: str = "index",
    distribution: str = "accumulating",
    hedge: str = "unhedged",
    hedge_currency: str | None = None,
    sub_fund_id: str | None = None,
    return_value: Decimal = Decimal("0.01"),
    record_known_at: str = DECISION,
    lifecycle_events: tuple[FundLifecycleEvent, ...] = (),
    instrument_type: str = "ordinary_fund",
    start: date = START,
    end: date = END,
) -> FundPeerFund:
    record = _record(
        fund_id,
        class_id,
        return_value,
        start=start,
        end=end,
        benchmark_id="BENCHMARK-1",
        mandate=mandate,
        distribution=distribution,
        hedge=hedge,
        hedge_currency=hedge_currency,
        decision_time=datetime.fromisoformat(record_known_at.replace("Z", "+00:00")),
    )
    share_class = FundShareClass(
        class_id,
        sub_fund_id,
        distribution,
        (f"source:{class_id}",),
        f"distribution:{class_id}",
    )
    context = _context(
        class_id,
        instrument_type=instrument_type,
        share_class_id=class_id,
        mandate=mandate,
        distribution=distribution,
    )
    return FundPeerFund(
        record,
        share_class,
        FundStructure.ORDINARY_FUND,
        context,
        lifecycle_events,
    )


def _record(
    fund_id: str,
    class_id: str,
    total_return: Decimal,
    *,
    start: date,
    end: date,
    benchmark_id: str | None,
    mandate: str = "index",
    distribution: str = "accumulating",
    hedge: str = "unhedged",
    hedge_currency: str | None = None,
    decision_time: datetime = datetime(2025, 1, 2, tzinfo=timezone.utc),
) -> FundAnalysisRecord:
    decomposition = FundReturnDecomposition(
        contract_version=FUND_RETURN_CONTRACT,
        fund_id=fund_id,
        share_class_id=class_id,
        decision_time=decision_time,
        requested_horizon="1Y",
        status="available",
        nav_currency="EUR",
        selected_currency="EUR",
        distribution_policy=distribution,
        currency_hedge_policy=hedge,
        hedge_currency=hedge_currency,
        start_nav_date=start,
        end_nav_date=end,
        start_nav_per_share=Decimal("100"),
        end_nav_per_share=Decimal("100") * (Decimal(1) + total_return),
        nav_change_return=total_return,
        reinvested_distributions_return=Decimal("0"),
        class_fee_return=Decimal("0"),
        fx_return=Decimal("0"),
        fx_start_rate=Decimal("1"),
        fx_end_rate=Decimal("1"),
        total_return=total_return,
        residual=Decimal("0"),
        reconciliation_tolerance=Decimal("0.000001"),
        reason_codes=(),
        evidence_references=(f"return:{class_id}",),
    )
    return FundAnalysisRecord(
        contract_version="fund-analysis.v1",
        record_id=f"record:{fund_id}:{class_id}:{start}:{end}",
        fund_id=fund_id,
        share_class_id=class_id,
        decision_time=decision_time,
        status="available",
        benchmark_id=benchmark_id,
        total_fee_bps=Decimal("30"),
        fee_stack_status="complete",
        return_decomposition=decomposition,
        lifecycle_risk=FundLifecycleRisk(
            "fund-lifecycle-risk.v1", False, False, False, False, False, ()
        ),
        metric_applicability=(),
        blockers=(),
        assumptions=(),
        evidence_references=decomposition.evidence_references,
    )


def _benchmark_series(
    instrument_id: str,
    start: date,
    end: date,
    levels: dict[date, float],
    *,
    coverage_directory: Path,
    known_at: str = "2025-01-02T00:00:00Z",
) -> TotalReturnEvidence:
    dates = pd.bdate_range(start, end)
    current_level = 100.0
    values = []
    for timestamp in dates:
        day = timestamp.date()
        if day in levels:
            current_level = levels[day]
        values.append(current_level)
    frame = pd.DataFrame(
        {
            "date": dates,
            "close": values,
            "instrument_id": instrument_id,
            "currency": "EUR",
            "source_id": "benchmark-fixture",
            "provenance": "test-fixture",
        }
    )
    adjustment = apply_total_return_adjustments(frame)
    as_of = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    coverage = CorporateActionCoverage(
        instrument_id=instrument_id,
        coverage_through=as_of,
        published_at=as_of,
        retrieved_at=as_of,
        known_at=known_at,
        revision=1,
        source="test-fixture",
        source_id="coverage-fixture",
        source_checksum="c" * 64,
        status="active",
    )
    with CorporateActionCoverageStore(coverage_directory) as store:
        canonical_coverage = store.append(coverage)
    return TotalReturnEvidence.from_adjustment_result(
        adjustment,
        instrument_id=instrument_id,
        currency="EUR",
        known_at=known_at,
        as_of=as_of,
        source_id="benchmark-fixture",
        provenance="test-fixture",
        corporate_action_coverage=canonical_coverage,
    )


def _benchmark_metrics(
    window: FundAnalysisRecord,
    periodic: tuple[FundAnalysisRecord, ...],
    coverage_directory: Path,
):
    middle = date(2024, 7, 1)
    benchmark = _benchmark_series(
        "DISCLOSURE-INDEX",
        START,
        END,
        {START: 100.0, middle: 100.0, END: 105.0},
        coverage_directory=coverage_directory / "benchmark-coverage",
    )
    return calculate_fund_benchmark_metrics(
        window,
        benchmark,
        decision_time=datetime.fromisoformat(DECISION.replace("Z", "+00:00")),
        mandate="index",
        periodic_fund_returns=periodic,
        tracking_minimum_periods=2,
    )


def _context(
    instrument_id: str,
    *,
    instrument_type: str = "ordinary_fund",
    share_class_id: str | None = None,
    mandate: str = "index",
    distribution: str = "accumulating",
    effective_at: str = "2024-01-01T00:00:00Z",
):
    values = {
        "instrument_type": instrument_type,
        "asset_class": "equity",
        "share_class_id": share_class_id or instrument_id,
        "fund_structure": "unit_trust",
        "mandate": mandate,
        "benchmark": "BENCHMARK-1",
        "asset_region": "global",
        "sector": "technology",
        "distribution_policy": distribution,
        "dealing_liquidity_class": "monthly",
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument_id}:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            source="fixture",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"classification:{instrument_id}:{field}",
            confidence=0.99,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence,
        instrument_id=instrument_id,
        effective_at=effective_at,
        decision_time=DECISION,
    )


def _peer_observation(context) -> PeerObservation:
    return PeerObservation(
        context.instrument_id,
        context,
        "quality",
        0.5,
        1.0,
        EFFECTIVE,
        "2024-12-31T00:00:00Z",
    )
