"""Ordinary-fund peer cohorts and disclosure-benchmark comparisons."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import math
import statistics
from typing import Sequence

import pandas as pd

from etf_cockpit.analysis.fund_analysis import (
    FundAnalysisConfig,
    FundAnalysisRecord,
    FundLifecycleRisk,
    FundMetricApplicability,
    load_fund_analysis_config,
)
from etf_cockpit.analysis.peer_cohorts import (
    CohortMembership,
    PeerMetricResult,
    PeerObservation,
    calculate_peer_metric,
    construct_cohort,
)
from etf_cockpit.data.classification import (
    DEFAULT_LEAF_CONFIDENCE,
    InstrumentContextV2,
)
from etf_cockpit.data.fund_identity import (
    FundLifecycleEvent,
    FundLifecycleStatus,
    FundMetricState,
    FundShareClass,
    FundStructure,
)
from etf_cockpit.data.etf_economics import TotalReturnEvidence


FUND_PEER_COHORT_CONTRACT = "fund-peer-cohort.v1"
FUND_BENCHMARK_METRICS_CONTRACT = "fund-benchmark-metrics.v1"
_FUND_DIMENSION_ORDER = (
    "vehicle",
    "mandate",
    "benchmark_objective",
    "geography_sector",
    "asset_class",
    "currency_hedge",
    "distribution_policy",
    "duration",
    "rating",
    "fee_tier",
    "dealing_class",
)
_TERMINAL_LIFECYCLE_STATUSES = frozenset(
    {
        FundLifecycleStatus.CLOSED,
        FundLifecycleStatus.MERGED,
        FundLifecycleStatus.LIQUIDATED,
    }
)
_YEAR_DAYS = Decimal("365.2425")


class FundPeerError(ValueError):
    """Raised when ordinary-fund peer or benchmark evidence is invalid."""


@dataclass(frozen=True)
class FundPeerFund:
    """A slice-A return record with its existing class and classification evidence."""

    analysis_record: FundAnalysisRecord
    share_class: FundShareClass
    structure: FundStructure
    context: InstrumentContextV2
    lifecycle_events: tuple[FundLifecycleEvent, ...] = ()


@dataclass(frozen=True)
class FundPeerClassCollapse:
    economic_strategy_id: str
    retained_share_class_id: str
    collapsed_share_class_ids: tuple[str, ...]


@dataclass(frozen=True)
class FundPeerCohort:
    contract_version: str
    status: str
    cohort: CohortMembership
    peer_metric: PeerMetricResult
    collapsed_share_classes: tuple[FundPeerClassCollapse, ...]
    peer_lifecycle_risks: tuple[tuple[str, FundLifecycleRisk], ...]
    abstention_reason: str | None
    execution_allowed: bool = False


@dataclass(frozen=True)
class FundBenchmarkMetrics:
    contract_version: str
    fund_record_id: str
    benchmark_id: str | None
    window_start: date | None
    window_end: date | None
    excess_total_return: FundMetricApplicability
    tracking_difference: FundMetricApplicability
    tracking_error: FundMetricApplicability
    evidence_references: tuple[str, ...]
    execution_allowed: bool = False


def build_fund_peer_cohort(
    target: FundPeerFund,
    peers: Sequence[FundPeerFund],
    *,
    effective_at: str,
    decision_time: str,
    config: FundAnalysisConfig | None = None,
) -> FundPeerCohort:
    """Build an ordinary-fund cohort from slice-A total returns and known lifecycle facts."""

    policy = config or load_fund_analysis_config()
    _validate_fund_peer_input(target)
    for peer in peers:
        _validate_fund_peer_input(peer)
    peer_instrument_ids = [peer.context.instrument_id for peer in peers]
    if len(peer_instrument_ids) != len(set(peer_instrument_ids)):
        raise FundPeerError("each share class requires its own fund context identity")
    dimensions = {
        item.context.instrument_id: _fund_dimensions(item, policy)
        for item in (target, *peers)
    }
    order = list(_FUND_DIMENSION_ORDER)
    if target.context.asset_class != "fixed_income":
        order = [name for name in order if name not in {"duration", "rating"}]
    observations = tuple(
        _peer_observation(
            peer,
            effective_at,
            decision_time,
            target_horizon=target.analysis_record.return_decomposition.requested_horizon,
        )
        for peer in peers
    )
    cohort = construct_cohort(
        target.context,
        observations,
        metric="total_return",
        effective_at=effective_at,
        decision_time=decision_time,
        minimum_support=policy.peer_minimum_support,
        comparison_scope="FUND_PEERS",
        comparison_dimension_order=order,
        comparison_dimension_groups=dimensions,
    )
    target_decomposition = target.analysis_record.return_decomposition
    target_total_return = (
        target_decomposition.total_return
        if target_decomposition.status == "available"
        else None
    )
    target_value = float(target_total_return) if target_total_return is not None else None
    metric = calculate_peer_metric(
        "total_return",
        target_value,
        cohort,
        applicable=True,
    )
    abstention_reason: str | None = None
    if cohort.support < policy.peer_minimum_support:
        abstention_reason = "insufficient_peer_support"
        metric = replace(
            metric,
            status="unavailable",
            winsorized_value=None,
            median=None,
            mad=None,
            percentile=None,
            shrunk_percentile=None,
            interval=None,
            reason_code="INSUFFICIENT_PEER_SUPPORT",
        )
    elif target_total_return is None or metric.status != "available":
        abstention_reason = "target_total_return_unavailable"
    collapsed = _collapsed_classes(cohort, peers)
    peers_by_instrument = {item.context.instrument_id: item for item in peers}
    lifecycle_risks = tuple(
        sorted(
            (
                (
                    observation.economic_strategy_id
                    or peers_by_instrument[observation.instrument_id].analysis_record.fund_id,
                    peers_by_instrument[observation.instrument_id]
                    .analysis_record.lifecycle_risk,
                )
                for observation in cohort.observations
            ),
            key=lambda row: row[0],
        )
    )
    return FundPeerCohort(
        FUND_PEER_COHORT_CONTRACT,
        metric.status,
        cohort,
        metric,
        collapsed,
        lifecycle_risks,
        abstention_reason,
    )


def calculate_fund_benchmark_metrics(
    window_record: FundAnalysisRecord,
    benchmark_returns: TotalReturnEvidence | None,
    *,
    decision_time: datetime,
    mandate: str | None,
    periodic_fund_returns: Sequence[FundAnalysisRecord] = (),
    tracking_minimum_periods: int | None = None,
    config: FundAnalysisConfig | None = None,
) -> FundBenchmarkMetrics:
    """Compare slice-A returns with the disclosure benchmark over exact dated windows.

    Annualisation infers periods per year as aligned observations multiplied by 365.2425
    and divided by elapsed calendar days. Tracking difference compounds each observed
    periodic series over its window; tracking error uses sample deviation times the square
    root of that observed frequency. No trading-day frequency is assumed.
    """

    policy = config or load_fund_analysis_config()
    decision = _timestamp(decision_time, "decision_time")
    minimum_periods = (
        policy.tracking_minimum_periods
        if tracking_minimum_periods is None
        else tracking_minimum_periods
    )
    if isinstance(minimum_periods, bool) or not isinstance(minimum_periods, int) or minimum_periods < 2:
        raise FundPeerError("tracking minimum periods must be an integer at least two")
    decomposition = window_record.return_decomposition
    start, end = decomposition.start_nav_date, decomposition.end_nav_date
    evidence = (
        tuple(
            sorted(
                (
                    benchmark_returns.source_id,
                    benchmark_returns.provenance,
                    benchmark_returns.checksum,
                    benchmark_returns.artifact_checksum,
                )
            )
        )
        if benchmark_returns is not None
        else ()
    )
    if not window_record.benchmark_id:
        excess = _unavailable("excess_total_return", "missing_disclosure_benchmark")
        tracking_difference = _tracking_state(
            mandate, "tracking_difference", "missing_disclosure_benchmark"
        )
        tracking_error = _tracking_state(
            mandate, "tracking_error", "missing_disclosure_benchmark"
        )
    else:
        unavailable_reason = None
        benchmark_index: dict[date, Decimal] | None = None
        if benchmark_returns is None:
            unavailable_reason = "benchmark_returns_unavailable"
        elif benchmark_returns.instrument_id != window_record.benchmark_id:
            unavailable_reason = "benchmark_identity_mismatch"
        elif _timestamp(benchmark_returns.known_at, "benchmark known_at") > decision:
            unavailable_reason = "benchmark_not_known_at_decision"
        elif benchmark_returns.currency != decomposition.selected_currency:
            unavailable_reason = "benchmark_currency_mismatch"
        else:
            try:
                benchmark_index = _benchmark_index(benchmark_returns)
            except FundPeerError:
                unavailable_reason = "benchmark_series_invalid"
        if decomposition.total_return is None or decomposition.status != "available":
            excess = _unavailable("excess_total_return", "fund_return_unavailable")
        elif unavailable_reason is not None:
            excess = _unavailable("excess_total_return", unavailable_reason)
        elif start is None or end is None:
            excess = _unavailable("excess_total_return", "date_mismatch")
        else:
            benchmark_window_return = _window_return(benchmark_index, start, end)
            if benchmark_window_return is None:
                excess = _unavailable("excess_total_return", "date_mismatch")
            else:
                excess = FundMetricApplicability(
                    "excess_total_return",
                    FundMetricState.AVAILABLE,
                    decomposition.total_return - benchmark_window_return,
                    None,
                )
        tracking_difference, tracking_error = _tracking_metrics(
            window_record,
            benchmark_index,
            periodic_fund_returns,
            mandate,
            minimum_periods,
            start,
            end,
            unavailable_reason,
        )
    return FundBenchmarkMetrics(
        FUND_BENCHMARK_METRICS_CONTRACT,
        window_record.record_id,
        window_record.benchmark_id,
        start,
        end,
        excess,
        tracking_difference,
        tracking_error,
        evidence,
    )


def _tracking_metrics(
    window_record: FundAnalysisRecord,
    benchmark_index: dict[date, Decimal] | None,
    periodic_fund_returns: Sequence[FundAnalysisRecord],
    mandate: str | None,
    minimum_periods: int,
    start: date | None,
    end: date | None,
    unavailable_reason: str | None,
) -> tuple[FundMetricApplicability, FundMetricApplicability]:
    if mandate is None or mandate.casefold() not in {"active", "passive", "index"}:
        unavailable = _unavailable("tracking_difference", "mandate_unclassified")
        return unavailable, _unavailable("tracking_error", "mandate_unclassified")
    if mandate.casefold() == "active":
        return (
            FundMetricApplicability(
                "tracking_difference", FundMetricState.NOT_APPLICABLE, None, "active_mandate"
            ),
            FundMetricApplicability(
                "tracking_error", FundMetricState.NOT_APPLICABLE, None, "active_mandate"
            ),
        )
    if unavailable_reason is not None or benchmark_index is None:
        reason = unavailable_reason or "benchmark_returns_unavailable"
        return _unavailable("tracking_difference", reason), _unavailable(
            "tracking_error", reason
        )
    if start is None or end is None or start >= end:
        return _unavailable("tracking_difference", "date_mismatch"), _unavailable(
            "tracking_error", "date_mismatch"
        )
    matched: list[tuple[FundAnalysisRecord, Decimal]] = []
    saw_date_mismatch = False
    for record in periodic_fund_returns:
        decomposition = record.return_decomposition
        if (
            record.benchmark_id != window_record.benchmark_id
            or decomposition.start_nav_date is None
            or decomposition.end_nav_date is None
        ):
            saw_date_mismatch = True
            continue
        benchmark_return = _window_return(
            benchmark_index,
            decomposition.start_nav_date,
            decomposition.end_nav_date,
        )
        if benchmark_return is None:
            saw_date_mismatch = True
            continue
        if decomposition.status != "available" or decomposition.total_return is None:
            continue
        matched.append((record, benchmark_return))
    matched.sort(key=lambda pair: pair[0].return_decomposition.start_nav_date or date.min)
    contiguous = bool(matched)
    if matched:
        contiguous = (
            matched[0][0].return_decomposition.start_nav_date == start
            and matched[-1][0].return_decomposition.end_nav_date == end
            and all(
                left[0].return_decomposition.end_nav_date
                == right[0].return_decomposition.start_nav_date
                for left, right in zip(matched, matched[1:])
            )
        )
    if saw_date_mismatch or (matched and not contiguous):
        return _unavailable("tracking_difference", "date_mismatch"), _unavailable(
            "tracking_error", "date_mismatch"
        )
    if len(matched) < minimum_periods:
        return _unavailable("tracking_difference", "too_few_periods"), _unavailable(
            "tracking_error", "too_few_periods"
        )
    elapsed_days = (end - start).days
    if elapsed_days <= 0:
        return _unavailable("tracking_difference", "date_mismatch"), _unavailable(
            "tracking_error", "date_mismatch"
        )
    fund_total = _compound(
        row.return_decomposition.total_return for row, _ in matched
    )
    benchmark_total = _compound(benchmark_return for _, benchmark_return in matched)
    if fund_total is None or benchmark_total is None:
        return _unavailable(
            "tracking_difference", "non_positive_growth_factor"
        ), _unavailable("tracking_error", "non_positive_growth_factor")
    elapsed_years = Decimal(elapsed_days) / _YEAR_DAYS
    annual_factor = Decimal(1) / elapsed_years
    try:
        fund_annualized = (Decimal(1) + fund_total) ** annual_factor - Decimal(1)
        benchmark_annualized = (
            Decimal(1) + benchmark_total
        ) ** annual_factor - Decimal(1)
    except (InvalidOperation, OverflowError, ValueError):
        return _unavailable(
            "tracking_difference", "annualization_unavailable"
        ), _unavailable("tracking_error", "annualization_unavailable")
    periods_per_year = Decimal(len(matched)) / elapsed_years
    differences = [
        float(row.return_decomposition.total_return - benchmark_return)
        for row, benchmark_return in matched
    ]
    tracking_error_value = Decimal(
        str(statistics.stdev(differences) * math.sqrt(float(periods_per_year)))
    )
    return (
        FundMetricApplicability(
            "tracking_difference",
            FundMetricState.AVAILABLE,
            fund_annualized - benchmark_annualized,
            None,
        ),
        FundMetricApplicability(
            "tracking_error", FundMetricState.AVAILABLE, tracking_error_value, None
        ),
    )


def _compound(returns: Iterable[Decimal]) -> Decimal | None:
    growth = Decimal(1)
    try:
        for value in returns:
            if value <= Decimal("-1"):
                return None
            growth *= Decimal(1) + value
    except (InvalidOperation, TypeError):
        return None
    return growth - Decimal(1)


def _benchmark_index(evidence: TotalReturnEvidence) -> dict[date, Decimal]:
    if "total_return_index" not in evidence.frame.columns:
        raise FundPeerError("benchmark series lacks its total-return index")
    dates = pd.to_datetime(
        evidence.frame["date"], errors="coerce", utc=True, format="mixed"
    )
    if dates.isna().any():
        raise FundPeerError("benchmark series contains an invalid date")
    result: dict[date, Decimal] = {}
    for timestamp, raw_value in zip(
        dates, evidence.frame["total_return_index"], strict=True
    ):
        day = timestamp.date()
        if day in result:
            raise FundPeerError("benchmark series contains duplicate dates")
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise FundPeerError("benchmark total-return index is invalid") from exc
        if not value.is_finite() or value <= 0:
            raise FundPeerError("benchmark total-return index must be positive")
        result[day] = value
    return result


def _window_return(
    benchmark_index: dict[date, Decimal] | None,
    start: date,
    end: date,
) -> Decimal | None:
    if benchmark_index is None:
        return None
    start_value = benchmark_index.get(start)
    end_value = benchmark_index.get(end)
    if start_value is None or end_value is None or start_value <= 0:
        return None
    return end_value / start_value - Decimal(1)


def _fund_dimensions(
    item: FundPeerFund, config: FundAnalysisConfig
) -> dict[str, str]:
    context = item.context
    result: dict[str, str] = {}
    for dimension, field_name in (
        ("vehicle", "fund_structure"),
        ("mandate", "mandate"),
        ("asset_class", "asset_class"),
        ("duration", "duration_bucket"),
        ("rating", "rating_bucket"),
        ("dealing_class", "dealing_liquidity_class"),
    ):
        value = _classification_value(context, field_name)
        if value:
            if dimension == "mandate" and value.casefold() not in {
                "active",
                "passive",
                "index",
            }:
                continue
            result[dimension] = value.casefold()
    benchmark = _classification_value(context, "benchmark")
    record_benchmark = item.analysis_record.benchmark_id
    if benchmark and record_benchmark and benchmark != record_benchmark:
        benchmark = None
        record_benchmark = None
    if benchmark or record_benchmark:
        result["benchmark_objective"] = f"benchmark:{benchmark or record_benchmark}"
    elif context.strategy_labels and not context.alternatives.get("strategy_label"):
        confidence = context.field_confidence.get("strategy_label", 0.0)
        if confidence >= DEFAULT_LEAF_CONFIDENCE:
            result["benchmark_objective"] = "objective:" + "|".join(
                sorted(context.strategy_labels)
            )
    regions = _classification_value(context, "asset_regions")
    sector = _classification_value(context, "sector")
    if regions or sector:
        components = []
        if regions:
            components.append(f"geography:{regions.casefold()}")
        if sector:
            components.append(f"sector:{sector.casefold()}")
        result["geography_sector"] = ";".join(components)
    policy = item.analysis_record.return_decomposition.currency_hedge_policy
    hedge_currency = item.analysis_record.return_decomposition.hedge_currency
    if policy == "unhedged":
        result["currency_hedge"] = "unhedged"
    elif policy == "hedged" and hedge_currency:
        result["currency_hedge"] = f"hedged:{hedge_currency.upper()}"
    distribution = (
        item.share_class.distribution_policy.casefold()
        if item.share_class.distribution_policy is not None
        else None
    )
    decomposed_distribution = item.analysis_record.return_decomposition.distribution_policy
    if distribution in {"accumulating", "distributing"} and (
        decomposed_distribution is None
        or decomposed_distribution == distribution
    ):
        result["distribution_policy"] = distribution
    total_fee = item.analysis_record.total_fee_bps
    if total_fee is not None and total_fee.is_finite() and total_fee >= 0:
        band = next(
            (
                index
                for index, upper_bound in enumerate(config.fee_tier_bands_bps, start=1)
                if total_fee <= upper_bound
            ),
            len(config.fee_tier_bands_bps) + 1,
        )
        result["fee_tier"] = f"fee_tier_{band}"
    if context.asset_class != "fixed_income":
        result.pop("duration", None)
        result.pop("rating", None)
    return result


def _classification_value(context: InstrumentContextV2, field_name: str) -> str | None:
    value = getattr(context, field_name, None)
    if isinstance(value, tuple):
        if not value:
            return None
        value = "|".join(sorted(str(item) for item in value))
    if not isinstance(value, str) or not value.strip():
        return None
    evidence_field = {
        "asset_regions": "asset_region",
        "revenue_regions": "revenue_region",
    }.get(field_name, field_name)
    if context.alternatives.get(field_name) or context.alternatives.get(evidence_field):
        return None
    if context.field_confidence.get(evidence_field, 0.0) < DEFAULT_LEAF_CONFIDENCE:
        return None
    return value.strip()


def _peer_observation(
    item: FundPeerFund,
    effective_at: str,
    decision_time: str,
    *,
    target_horizon: str,
) -> PeerObservation:
    decomposition = item.analysis_record.return_decomposition
    effective = _time_string(decomposition.end_nav_date, effective_at)
    active_from, active_to = _lifecycle_window(item, decision_time)
    target_return = decomposition.total_return
    return PeerObservation(
        instrument_id=item.context.instrument_id,
        context=item.context,
        metric="total_return",
        value=float(target_return) if target_return is not None else None,
        weight=1.0,
        effective_at=effective,
        known_at=item.analysis_record.decision_time.isoformat(),
        applicable=(
            decomposition.status == "available"
            and decomposition.requested_horizon == target_horizon
        ),
        economic_strategy_id=_economic_strategy_id(item),
        active_from=active_from,
        active_to=active_to,
    )


def _lifecycle_window(
    item: FundPeerFund, decision_time: str
) -> tuple[str | None, str | None]:
    decision = _timestamp(decision_time, "decision_time")
    known = tuple(
        event
        for event in item.lifecycle_events
        if event.fund_id == item.analysis_record.fund_id
        and _timestamp(event.available_at, "lifecycle available_at") <= decision
    )
    launches = tuple(
        event
        for event in known
        if event.status is FundLifecycleStatus.LAUNCHED
    )
    terminal = tuple(
        event for event in known if event.status in _TERMINAL_LIFECYCLE_STATUSES
    )
    active_from = min(
        (event.effective_at for event in launches),
        key=_timestamp,
        default=None,
    )
    active_to = min(
        (event.effective_at for event in terminal),
        key=_timestamp,
        default=None,
    )
    return active_from, active_to


def _collapsed_classes(
    cohort: CohortMembership, peers: Sequence[FundPeerFund]
) -> tuple[FundPeerClassCollapse, ...]:
    by_instrument = {item.context.instrument_id: item for item in peers}
    collapsed: dict[str, list[str]] = {}
    retained: dict[str, str] = {}
    for observation in cohort.observations:
        item = by_instrument[observation.instrument_id]
        retained[observation.economic_strategy_id or item.analysis_record.fund_id] = (
            item.share_class.share_class_id
        )
    for instrument_id, reason in cohort.exclusions.items():
        prefix = "economic_strategy_duplicate_of:"
        if not reason.startswith(prefix) or instrument_id not in by_instrument:
            continue
        item = by_instrument[instrument_id]
        strategy = _economic_strategy_id(item)
        collapsed.setdefault(strategy, []).append(item.share_class.share_class_id)
    return tuple(
        FundPeerClassCollapse(
            strategy,
            retained[strategy],
            tuple(sorted(set(class_ids))),
        )
        for strategy, class_ids in sorted(collapsed.items())
        if strategy in retained
    )


def _economic_strategy_id(item: FundPeerFund) -> str:
    return item.share_class.sub_fund_id or item.analysis_record.fund_id


def _validate_fund_peer_input(item: FundPeerFund) -> None:
    record = item.analysis_record
    if item.structure is not FundStructure.ORDINARY_FUND:
        raise FundPeerError("FUND_PEERS accepts ordinary funds only")
    if record.share_class_id != item.share_class.share_class_id:
        raise FundPeerError("fund record and share-class identity do not match")
    if (
        not item.context.instrument_id
        or item.context.share_class_id != item.share_class.share_class_id
    ):
        raise FundPeerError("fund context and share-class identity do not match")
    if any(event.fund_id != record.fund_id for event in item.lifecycle_events):
        raise FundPeerError("lifecycle event belongs to another fund")


def _tracking_state(
    mandate: str | None, metric: str, unavailable_reason: str
) -> FundMetricApplicability:
    if mandate is not None and mandate.casefold() == "active":
        return FundMetricApplicability(
            metric, FundMetricState.NOT_APPLICABLE, None, "active_mandate"
        )
    return _unavailable(metric, unavailable_reason)


def _unavailable(metric: str, reason: str) -> FundMetricApplicability:
    return FundMetricApplicability(metric, FundMetricState.UNAVAILABLE, None, reason)


def _time_string(value: date | None, default: str) -> str:
    if value is None:
        return default
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).isoformat()


def _timestamp(value: datetime | str, name: str = "timestamp") -> datetime:
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise TypeError
    except (ValueError, TypeError) as exc:
        raise FundPeerError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FundPeerError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "FUND_BENCHMARK_METRICS_CONTRACT",
    "FUND_PEER_COHORT_CONTRACT",
    "FundBenchmarkMetrics",
    "FundPeerClassCollapse",
    "FundPeerError",
    "FundPeerFund",
    "FundPeerCohort",
    "build_fund_peer_cohort",
    "calculate_fund_benchmark_metrics",
]
