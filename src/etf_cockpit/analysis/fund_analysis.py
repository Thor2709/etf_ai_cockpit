"""Point-in-time ordinary-fund NAV return analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

import pandas as pd
import yaml

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.fund_identity import (
    FundLifecycleEvent,
    FundLifecycleStatus,
    FundMetricState,
    FundShareClass,
    FundStructure,
    FundTerm,
)
from etf_cockpit.data.fx_data import build_fx_rate_snapshot, fx_cross_rate


FUND_ANALYSIS_CONTRACT = "fund-analysis.v1"
FUND_RETURN_CONTRACT = "fund-return-decomposition.v1"
FUND_ANALYSIS_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "fund_analysis_v1.yaml"
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_TIME = re.compile(r"^\d{2}:\d{2}$")


class FundAnalysisError(ValueError):
    """Raised when fund analysis inputs or policy configuration are invalid."""


class FundTermChangeKind(StrEnum):
    MANAGER_CHANGE = "manager_change"
    BENCHMARK_CHANGE = "benchmark_change"
    FEE_CHANGE = "fee_change"
    MANDATE_CHANGE = "mandate_change"


@dataclass(frozen=True)
class FundTermChangeEvent:
    fund_id: str
    kind: FundTermChangeKind
    effective_at: str
    available_at: str
    source_id: str
    authority: SourceAuthority
    old_value: str
    new_value: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "kind", FundTermChangeKind(self.kind))
            object.__setattr__(self, "authority", SourceAuthority(self.authority))
        except ValueError as exc:
            raise FundAnalysisError("term-change kind or authority is unsupported") from exc
        for field in ("fund_id", "source_id", "old_value", "new_value"):
            if not getattr(self, field).strip():
                raise FundAnalysisError(f"{field} must be non-empty")
        _timestamp(self.effective_at, "effective_at")
        _timestamp(self.available_at, "available_at")


@dataclass(frozen=True)
class FundUnderlyingLink:
    parent_fund_id: str
    underlying_fund_id: str
    weight: Decimal
    ongoing_fee_bps: Decimal | None
    as_of: date
    available_at: str
    source_id: str

    def __post_init__(self) -> None:
        if not self.parent_fund_id.strip() or not self.underlying_fund_id.strip():
            raise FundAnalysisError("underlying link fund IDs must be non-empty")
        if not self.source_id.strip():
            raise FundAnalysisError("underlying links require a source ID")
        if not self.weight.is_finite() or not Decimal("0") < self.weight <= Decimal("1"):
            raise FundAnalysisError("underlying link weight must be in (0, 1]")
        if self.ongoing_fee_bps is not None and (
            not self.ongoing_fee_bps.is_finite() or self.ongoing_fee_bps < Decimal("0")
        ):
            raise FundAnalysisError("underlying ongoing fee must be finite and non-negative")
        if not isinstance(self.as_of, date):
            raise FundAnalysisError("underlying link as_of must be a date")
        _timestamp(self.available_at, "available_at")


@dataclass(frozen=True)
class FundNAVObservation:
    as_of: date
    available_at: datetime
    nav_per_share: Decimal
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, date):
            raise FundAnalysisError("NAV as_of must be a date")
        _timestamp(self.available_at, "available_at")
        if not self.nav_per_share.is_finite() or self.nav_per_share <= Decimal("0"):
            raise FundAnalysisError("NAV per share must be finite and positive")
        if not self.source_id.strip():
            raise FundAnalysisError("NAV observations require a source ID")


@dataclass(frozen=True)
class FundDistributionObservation:
    ex_date: date
    available_at: datetime
    amount_per_share: Decimal
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.ex_date, date):
            raise FundAnalysisError("distribution ex_date must be a date")
        _timestamp(self.available_at, "available_at")
        if not self.amount_per_share.is_finite() or self.amount_per_share < Decimal("0"):
            raise FundAnalysisError("distribution amount must be finite and non-negative")
        if not self.source_id.strip():
            raise FundAnalysisError("distributions require a source ID")


@dataclass(frozen=True)
class FundAnalysisInput:
    fund_id: str
    share_class: FundShareClass
    structure: FundStructure
    decision_time: datetime
    horizon: str
    selected_currency: str
    terms: tuple[FundTerm, ...]
    nav_history: tuple[FundNAVObservation, ...]
    distributions: tuple[FundDistributionObservation, ...] = ()
    lifecycle_events: tuple[FundLifecycleEvent, ...] = ()
    term_change_events: tuple[FundTermChangeEvent, ...] = ()
    underlying_links: tuple[FundUnderlyingLink, ...] = ()
    underlying_structure: str = "single"
    distribution_history_complete: bool | None = None
    lifecycle_history_complete: bool = False
    fx_rates: pd.DataFrame | None = None


@dataclass(frozen=True)
class FundAnalysisConfig:
    schema_version: int
    reconciliation_tolerance: Decimal
    underlying_weight_tolerance: Decimal
    annual_fee_day_count: int
    maximum_nav_anchor_gap_days: int
    dealing_cutoff_timezone: str
    horizon_days: tuple[tuple[str, int], ...]
    frequency_minimum_horizon_days: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class FundMetricApplicability:
    metric: str
    state: FundMetricState
    value: Decimal | None
    reason: str | None


@dataclass(frozen=True)
class FundLifecycleRisk:
    contract_version: str
    closure_risk: bool | None
    merger_risk: bool | None
    manager_change: bool | None
    benchmark_change: bool | None
    fee_change: bool | None
    evidence_references: tuple[str, ...]


@dataclass(frozen=True)
class FundReturnDecomposition:
    contract_version: str
    fund_id: str
    share_class_id: str
    decision_time: datetime
    requested_horizon: str
    status: str
    nav_currency: str | None
    selected_currency: str
    distribution_policy: str | None
    currency_hedge_policy: str | None
    hedge_currency: str | None
    start_nav_date: date | None
    end_nav_date: date | None
    start_nav_per_share: Decimal | None
    end_nav_per_share: Decimal | None
    nav_change_return: Decimal | None
    reinvested_distributions_return: Decimal | None
    class_fee_return: Decimal | None
    fx_return: Decimal | None
    fx_start_rate: Decimal | None
    fx_end_rate: Decimal | None
    total_return: Decimal | None
    residual: Decimal | None
    reconciliation_tolerance: Decimal
    reason_codes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class FundAnalysisRecord:
    contract_version: str
    record_id: str
    fund_id: str
    share_class_id: str
    decision_time: datetime
    status: str
    benchmark_id: str | None
    total_fee_bps: Decimal | None
    fee_stack_status: str
    return_decomposition: FundReturnDecomposition
    lifecycle_risk: FundLifecycleRisk
    metric_applicability: tuple[FundMetricApplicability, ...]
    blockers: tuple[str, ...]
    assumptions: tuple[str, ...]
    evidence_references: tuple[str, ...]
    execution_allowed: bool = False


def load_fund_analysis_config(path: Path = FUND_ANALYSIS_CONFIG) -> FundAnalysisConfig:
    """Load strict policy defaults; missing or malformed policy fails closed."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FundAnalysisError("fund analysis configuration is unavailable or invalid") from exc
    expected = {
        "schema_version",
        "reconciliation_tolerance",
        "underlying_weight_tolerance",
        "annual_fee_day_count",
        "maximum_nav_anchor_gap_days",
        "dealing_cutoff_timezone",
        "horizon_days",
        "frequency_minimum_horizon_days",
    }
    if not isinstance(raw, dict) or set(raw) != expected or raw.get("schema_version") != 1:
        raise FundAnalysisError("fund analysis configuration keys or schema are invalid")
    tolerance = _config_decimal(raw["reconciliation_tolerance"], "reconciliation_tolerance")
    weight_tolerance = _config_decimal(raw["underlying_weight_tolerance"], "underlying_weight_tolerance")
    if not Decimal("0") < tolerance < Decimal("1") or not Decimal("0") < weight_tolerance < Decimal("1"):
        raise FundAnalysisError("fund analysis tolerances must be in (0, 1)")
    fee_day_count = _config_integer(raw["annual_fee_day_count"], "annual_fee_day_count", 1)
    anchor_gap = _config_integer(raw["maximum_nav_anchor_gap_days"], "maximum_nav_anchor_gap_days", 0)
    if raw["dealing_cutoff_timezone"] != "UTC":
        raise FundAnalysisError("only the configured UTC dealing cutoff is supported")
    horizons = _config_integer_map(raw["horizon_days"], {"1W", "1M", "3M", "6M", "1Y"})
    frequencies = _config_integer_map(
        raw["frequency_minimum_horizon_days"], {"daily", "weekly", "biweekly", "monthly", "quarterly"}
    )
    return FundAnalysisConfig(
        1,
        tolerance,
        weight_tolerance,
        fee_day_count,
        anchor_gap,
        "UTC",
        tuple(sorted(horizons.items())),
        tuple(sorted(frequencies.items())),
    )


def analyze_fund(item: FundAnalysisInput) -> FundAnalysisRecord:
    """Build an evidence-backed ordinary-fund return record or abstain."""

    config = load_fund_analysis_config()
    _validate_input(item)
    decision = _timestamp(item.decision_time, "decision_time")
    decision = decision.astimezone(timezone.utc)
    selected_currency = _currency(item.selected_currency, "selected_currency")
    horizon_days = dict(config.horizon_days).get(item.horizon)
    if horizon_days is None:
        raise FundAnalysisError("requested horizon is not configured")

    blockers: list[str] = []
    evidence: list[str] = list(item.share_class.source_ids)
    if item.share_class.distribution_policy_source_id:
        evidence.append(item.share_class.distribution_policy_source_id)
    effective_date = decision.date()
    terms: dict[str, FundTerm | None] = {}
    for name in (
        "benchmark_id",
        "ongoing_fee_bps",
        "fees_reflected_in_nav",
        "dealing_cutoff",
        "dealing_frequency",
        "share_class_currency",
        "currency_hedge",
        "hedge_currency",
    ):
        term, conflict = _term_at(item.terms, name, effective_date, decision)
        terms[name] = term
        if term is not None:
            evidence.append(_term_reference(term))
        if conflict:
            blockers.append(f"conflicted_{name}")

    benchmark = terms["benchmark_id"]
    benchmark_id = benchmark.value if benchmark is not None else None
    if benchmark is None and "conflicted_benchmark_id" not in blockers:
        blockers.append("missing_benchmark")

    share_currency = terms["share_class_currency"]
    nav_currency: str | None = None
    if share_currency is None:
        blockers.append("missing_share_class_currency")
    else:
        try:
            nav_currency = _currency(share_currency.value, "share_class_currency")
        except FundAnalysisError:
            blockers.append("invalid_share_class_currency")

    fee_term = terms["ongoing_fee_bps"]
    root_fee: Decimal | None = None
    if fee_term is None:
        blockers.append("missing_fee")
    else:
        try:
            root_fee = _decimal(fee_term.value, "ongoing_fee_bps")
            if root_fee < Decimal("0"):
                raise FundAnalysisError("ongoing fee must be non-negative")
        except FundAnalysisError:
            blockers.append("invalid_fee")

    fee_treatment_term = terms["fees_reflected_in_nav"]
    fees_reflected_in_nav: bool | None = None
    if fee_treatment_term is None:
        blockers.append("missing_fee_treatment")
    elif fee_treatment_term.value.casefold() in {"true", "false"}:
        fees_reflected_in_nav = fee_treatment_term.value.casefold() == "true"
    else:
        blockers.append("invalid_fee_treatment")

    cutoff_term = terms["dealing_cutoff"]
    cutoff: time | None = None
    if cutoff_term is None:
        blockers.append("missing_dealing_cutoff")
    else:
        try:
            cutoff = _cutoff_time(cutoff_term.value)
        except FundAnalysisError:
            blockers.append("invalid_dealing_cutoff")

    frequency_term = terms["dealing_frequency"]
    frequency = frequency_term.value.casefold() if frequency_term is not None else None
    frequency_days = dict(config.frequency_minimum_horizon_days).get(frequency or "")
    if frequency_term is None:
        blockers.append("missing_dealing_frequency")
    elif frequency_days is None:
        blockers.append("unsupported_dealing_frequency")
    unsupported_horizon = (
        frequency_days is not None and horizon_days < frequency_days
    )
    if unsupported_horizon:
        blockers.append("unsupported_horizon_for_dealing_frequency")

    hedge_term = terms["currency_hedge"]
    hedge_policy = hedge_term.value.casefold() if hedge_term is not None else None
    if hedge_policy not in {"hedged", "unhedged"}:
        blockers.append("missing_or_invalid_currency_hedge_policy")
    hedge_currency: str | None = None
    if hedge_policy == "hedged":
        hedge_currency_term = terms["hedge_currency"]
        if hedge_currency_term is None:
            blockers.append("missing_hedge_currency")
        else:
            try:
                hedge_currency = _currency(hedge_currency_term.value, "hedge_currency")
            except FundAnalysisError:
                blockers.append("invalid_hedge_currency")

    distribution_policy = (
        item.share_class.distribution_policy.casefold()
        if item.share_class.distribution_policy is not None
        else None
    )
    if distribution_policy not in {"accumulating", "distributing"}:
        blockers.append("missing_or_invalid_distribution_policy")
    elif distribution_policy == "distributing" and item.distribution_history_complete is not True:
        blockers.append("missing_distribution_history")

    eligible_nav = tuple(
        observation
        for observation in item.nav_history
        if _timestamp(observation.available_at, "NAV available_at") <= decision
    )
    if len({observation.as_of for observation in eligible_nav}) != len(eligible_nav):
        raise FundAnalysisError("NAV history contains duplicate as_of dates")
    allowed_end_date: date | None = None
    if cutoff is not None:
        allowed_end_date = decision.date()
        if decision.timetz().replace(tzinfo=None) > cutoff:
            allowed_end_date = date.fromordinal(decision.date().toordinal() - 1)
    eligible_nav = tuple(
        sorted(
            (row for row in eligible_nav if allowed_end_date is not None and row.as_of <= allowed_end_date),
            key=lambda row: row.as_of,
        )
    )
    for observation in eligible_nav:
        evidence.append(observation.source_id)
    start_nav: FundNAVObservation | None = None
    end_nav: FundNAVObservation | None = eligible_nav[-1] if eligible_nav else None
    if not eligible_nav:
        blockers.append("insufficient_nav_history")
    else:
        target_start = end_nav.as_of.fromordinal(end_nav.as_of.toordinal() - horizon_days)
        candidates = tuple(row for row in eligible_nav if row.as_of <= target_start)
        start_nav = candidates[-1] if candidates else None
        if start_nav is None:
            blockers.append("insufficient_nav_history")
        elif (target_start - start_nav.as_of).days > config.maximum_nav_anchor_gap_days:
            blockers.append("nav_anchor_gap_exceeded")

    end_date = end_nav.as_of if end_nav is not None else effective_date
    if item.underlying_structure not in {"single", "fund_of_funds", "master_feeder"}:
        raise FundAnalysisError("underlying structure is unsupported")
    total_fee_bps, fee_stack_complete, fee_refs = _fee_stack(
        item,
        root_fee,
        end_date,
        decision,
        config,
    )
    evidence.extend(fee_refs)
    if not fee_stack_complete:
        blockers.append("fee_stack_incomplete")

    lifecycle_risk, lifecycle_refs = _lifecycle_risk(item, decision)
    evidence.extend(lifecycle_refs)

    known_distributions = tuple(
        sorted(
            (
                row
                for row in item.distributions
                if _timestamp(row.available_at, "distribution available_at") <= decision
                and start_nav is not None
                and end_nav is not None
                and start_nav.as_of < row.ex_date <= end_nav.as_of
            ),
            key=lambda row: row.ex_date,
        )
    )
    evidence.extend(row.source_id for row in known_distributions)
    if distribution_policy == "accumulating" and any(
        row.amount_per_share != Decimal("0") for row in known_distributions
    ):
        blockers.append("distributions_conflict_with_accumulating_class")

    fx_start: Decimal | None = None
    fx_end: Decimal | None = None
    fx_return: Decimal | None = None
    fx_refs: tuple[str, ...] = ()
    if nav_currency is not None and nav_currency != selected_currency:
        if start_nav is not None and end_nav is not None:
            fx_start, fx_end, fx_return, fx_refs = _point_in_time_fx(
                item.fx_rates,
                nav_currency,
                selected_currency,
                start_nav.as_of,
                end_nav.as_of,
                decision,
            )
        if fx_return is None:
            blockers.append("missing_point_in_time_fx")
    else:
        fx_start = fx_end = Decimal("1")
        fx_return = Decimal("0")
    evidence.extend(fx_refs)

    unsupported = unsupported_horizon or "unsupported_dealing_frequency" in blockers
    status = "unsupported" if unsupported else ("insufficient_evidence" if blockers else "available")
    return_decomposition = _decomposition(
        item,
        decision,
        selected_currency,
        nav_currency,
        distribution_policy,
        hedge_policy,
        hedge_currency,
        start_nav,
        end_nav,
        known_distributions,
        eligible_nav,
        total_fee_bps,
        fees_reflected_in_nav,
        fx_start,
        fx_end,
        fx_return,
        status,
        tuple(dict.fromkeys(blockers)),
        tuple(dict.fromkeys(evidence)),
        config,
    )
    record_evidence = tuple(dict.fromkeys(evidence))
    record_id = _hash(
        {
            "version": FUND_ANALYSIS_CONTRACT,
            "fund_id": item.fund_id,
            "share_class_id": item.share_class.share_class_id,
            "decision_time": decision.isoformat(),
            "horizon": item.horizon,
            "selected_currency": selected_currency,
            "evidence": record_evidence,
            "blockers": tuple(dict.fromkeys(blockers)),
        }
    )
    return FundAnalysisRecord(
        contract_version=FUND_ANALYSIS_CONTRACT,
        record_id=record_id,
        fund_id=item.fund_id,
        share_class_id=item.share_class.share_class_id,
        decision_time=decision,
        status=status,
        benchmark_id=benchmark_id,
        total_fee_bps=total_fee_bps,
        fee_stack_status="complete" if fee_stack_complete else "fee_stack_incomplete",
        return_decomposition=return_decomposition,
        lifecycle_risk=lifecycle_risk,
        metric_applicability=(
            _not_applicable("market_premium_discount"),
            _not_applicable("exchange_spread"),
            _not_applicable("intraday_liquidity"),
        ),
        blockers=tuple(dict.fromkeys(blockers)),
        assumptions=(
            "nav_share_class_returns_include_any_declared_currency_hedge",
            "reinvest_distributions_at_latest_known_nav_on_or_before_ex_date",
            "dealing_cutoff_is_interpreted_in_utc",
            "ongoing_fees_accrue_linearly_on_actual_elapsed_days",
            "execution_allowed=false",
        ),
        evidence_references=record_evidence,
    )


def _decomposition(
    item: FundAnalysisInput,
    decision: datetime,
    selected_currency: str,
    nav_currency: str | None,
    distribution_policy: str | None,
    hedge_policy: str | None,
    hedge_currency: str | None,
    start_nav: FundNAVObservation | None,
    end_nav: FundNAVObservation | None,
    distributions: tuple[FundDistributionObservation, ...],
    nav_history: tuple[FundNAVObservation, ...],
    total_fee_bps: Decimal | None,
    fees_reflected_in_nav: bool | None,
    fx_start: Decimal | None,
    fx_end: Decimal | None,
    fx_return: Decimal | None,
    status: str,
    blockers: tuple[str, ...],
    evidence: tuple[str, ...],
    config: FundAnalysisConfig,
) -> FundReturnDecomposition:
    fields: dict[str, Decimal | None] = {
        "start_nav_per_share": start_nav.nav_per_share if start_nav else None,
        "end_nav_per_share": end_nav.nav_per_share if end_nav else None,
        "nav_change_return": None,
        "reinvested_distributions_return": None,
        "class_fee_return": None,
        "total_return": None,
        "residual": None,
    }
    if status == "available" and start_nav is not None and end_nav is not None and total_fee_bps is not None:
        nav_change = end_nav.nav_per_share / start_nav.nav_per_share - Decimal("1")
        units = Decimal("1")
        matching_nav = tuple(row for row in nav_history if row.as_of <= end_nav.as_of)
        for distribution in distributions:
            reinvestment_nav = next(
                (row for row in reversed(matching_nav) if row.as_of <= distribution.ex_date),
                None,
            )
            if reinvestment_nav is None:
                blockers = (*blockers, "missing_distribution_reinvestment_nav")
                status = "insufficient_evidence"
                break
            units *= Decimal("1") + distribution.amount_per_share / reinvestment_nav.nav_per_share
        if status == "available":
            gross_local_return = units * end_nav.nav_per_share / start_nav.nav_per_share - Decimal("1")
            distribution_return = gross_local_return - nav_change
            elapsed_days = Decimal((end_nav.as_of - start_nav.as_of).days)
            fee_return = (
                -(total_fee_bps / Decimal("10000"))
                * elapsed_days
                / Decimal(config.annual_fee_day_count)
                if fees_reflected_in_nav is False
                else Decimal("0")
            )
            selected_return = (Decimal("1") + gross_local_return + fee_return) * (
                Decimal("1") + (fx_return or Decimal("0"))
            ) - Decimal("1")
            reconciled = (
                Decimal("1")
                + nav_change
                + distribution_return
                + fee_return
            ) * (Decimal("1") + (fx_return or Decimal("0"))) - Decimal("1")
            residual = selected_return - reconciled
            fields.update(
                nav_change_return=nav_change,
                reinvested_distributions_return=distribution_return,
                class_fee_return=fee_return,
                total_return=selected_return,
                residual=residual,
            )
            if abs(residual) > config.reconciliation_tolerance:
                status = "insufficient_evidence"
                blockers = (*blockers, "return_reconciliation_exceeds_tolerance")
    return FundReturnDecomposition(
        contract_version=FUND_RETURN_CONTRACT,
        fund_id=item.fund_id,
        share_class_id=item.share_class.share_class_id,
        decision_time=decision,
        requested_horizon=item.horizon,
        status=status,
        nav_currency=nav_currency,
        selected_currency=selected_currency,
        distribution_policy=distribution_policy,
        currency_hedge_policy=hedge_policy,
        hedge_currency=hedge_currency,
        start_nav_date=start_nav.as_of if start_nav else None,
        end_nav_date=end_nav.as_of if end_nav else None,
        start_nav_per_share=fields["start_nav_per_share"],
        end_nav_per_share=fields["end_nav_per_share"],
        nav_change_return=fields["nav_change_return"],
        reinvested_distributions_return=fields["reinvested_distributions_return"],
        class_fee_return=fields["class_fee_return"],
        fx_return=fx_return if status == "available" else None,
        fx_start_rate=fx_start if status == "available" else None,
        fx_end_rate=fx_end if status == "available" else None,
        total_return=fields["total_return"],
        residual=fields["residual"],
        reconciliation_tolerance=config.reconciliation_tolerance,
        reason_codes=tuple(dict.fromkeys(blockers)),
        evidence_references=evidence,
    )


def _fee_stack(
    item: FundAnalysisInput,
    root_fee: Decimal | None,
    as_of: date,
    decision: datetime,
    config: FundAnalysisConfig,
) -> tuple[Decimal | None, bool, tuple[str, ...]]:
    if root_fee is None:
        return None, item.underlying_structure == "single", ()
    if item.underlying_structure == "single":
        return root_fee, True, ()
    links = tuple(
        link
        for link in item.underlying_links
        if link.parent_fund_id == item.fund_id
        and link.as_of <= as_of
        and _timestamp(link.available_at, "underlying available_at") <= decision
    )
    refs = tuple(link.source_id for link in links)
    if not links:
        return None, False, refs
    if abs(sum((link.weight for link in links), Decimal("0")) - Decimal("1")) > config.underlying_weight_tolerance:
        return None, False, refs
    if any(link.ongoing_fee_bps is None for link in links):
        return None, False, refs
    stacked = root_fee + sum(
        (link.weight * link.ongoing_fee_bps for link in links if link.ongoing_fee_bps is not None),
        Decimal("0"),
    )
    return stacked, True, refs


def _lifecycle_risk(
    item: FundAnalysisInput,
    decision: datetime,
) -> tuple[FundLifecycleRisk, tuple[str, ...]]:
    known_lifecycle = tuple(
        event
        for event in item.lifecycle_events
        if event.fund_id == item.fund_id
        and _timestamp(event.available_at, "lifecycle available_at") <= decision
    )
    known_changes = tuple(
        event
        for event in item.term_change_events
        if event.fund_id == item.fund_id
        and _timestamp(event.available_at, "term change available_at") <= decision
    )
    refs = tuple(dict.fromkeys(
        [event.source_id for event in known_lifecycle]
        + [event.source_id for event in known_changes]
    ))
    complete = item.lifecycle_history_complete
    return FundLifecycleRisk(
        contract_version=FUND_ANALYSIS_CONTRACT,
        closure_risk=(
            any(event.status in {FundLifecycleStatus.CLOSED, FundLifecycleStatus.LIQUIDATED} for event in known_lifecycle)
            if complete
            else None
        ),
        merger_risk=(
            any(event.status is FundLifecycleStatus.MERGED for event in known_lifecycle)
            if complete
            else None
        ),
        manager_change=(
            any(event.kind is FundTermChangeKind.MANAGER_CHANGE for event in known_changes)
            if complete
            else None
        ),
        benchmark_change=(
            any(event.kind is FundTermChangeKind.BENCHMARK_CHANGE for event in known_changes)
            if complete
            else None
        ),
        fee_change=(
            any(event.kind is FundTermChangeKind.FEE_CHANGE for event in known_changes)
            if complete
            else None
        ),
        evidence_references=refs,
    ), refs


def _point_in_time_fx(
    rates: pd.DataFrame | None,
    nav_currency: str,
    selected_currency: str,
    start_date: date,
    end_date: date,
    decision: datetime,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, tuple[str, ...]]:
    if rates is None or rates.empty or "ingested_at" not in rates.columns:
        return None, None, None, ()
    try:
        ingested = pd.to_datetime(rates["ingested_at"], errors="coerce", utc=True)
        known = rates.loc[ingested.notna() & ingested.le(pd.Timestamp(decision))].copy()
    except (TypeError, ValueError):
        return None, None, None, ()
    if known.empty:
        return None, None, None, ()
    start_rate, start_refs = _fx_rate_on_date(known, nav_currency, selected_currency, start_date)
    end_rate, end_refs = _fx_rate_on_date(known, nav_currency, selected_currency, end_date)
    if start_rate is None or end_rate is None:
        return None, None, None, tuple(dict.fromkeys(start_refs + end_refs))
    return start_rate, end_rate, end_rate / start_rate - Decimal("1"), tuple(dict.fromkeys(start_refs + end_refs))


def _fx_rate_on_date(
    rates: pd.DataFrame,
    base_currency: str,
    quote_currency: str,
    on_date: date,
) -> tuple[Decimal | None, tuple[str, ...]]:
    cutoff = datetime.combine(on_date, time.max, tzinfo=timezone.utc)
    snapshot = build_fx_rate_snapshot(rates, decision_time=cutoff)
    if not snapshot.available:
        return None, ()
    cross = fx_cross_rate(snapshot, base_currency, quote_currency)
    if cross is None:
        return None, ()
    refs = tuple(dict.fromkeys(leg.source for leg in cross.legs))
    return Decimal(str(cross.rate)), refs


def _term_at(
    terms: tuple[FundTerm, ...],
    name: str,
    effective_date: date,
    decision: datetime,
) -> tuple[FundTerm | None, bool]:
    matching = tuple(
        term
        for term in terms
        if term.name == name
        and _timestamp(term.available_at, "term available_at") <= decision
        and _timestamp(term.valid_from, "term valid_from").date() <= effective_date
        and (term.valid_to is None or _timestamp(term.valid_to, "term valid_to").date() > effective_date)
    )
    if not matching:
        return None, False
    latest = max(_timestamp(term.valid_from, "term valid_from") for term in matching)
    latest_terms = tuple(term for term in matching if _timestamp(term.valid_from, "term valid_from") == latest)
    values = {term.value for term in latest_terms}
    if len(values) != 1 or any(term.conflicted for term in latest_terms):
        return None, True
    return latest_terms[0], False


def _not_applicable(metric: str) -> FundMetricApplicability:
    return FundMetricApplicability(
        metric,
        FundMetricState.NOT_APPLICABLE,
        None,
        "not_applicable_to_ordinary_fund_nav_dealing",
    )


def _validate_input(item: FundAnalysisInput) -> None:
    if not isinstance(item, FundAnalysisInput):
        raise FundAnalysisError("fund analysis input type is invalid")
    if not item.fund_id.strip() or not isinstance(item.share_class, FundShareClass):
        raise FundAnalysisError("fund identity and existing share-class contract are required")
    if item.share_class.sub_fund_id != item.fund_id:
        raise FundAnalysisError("share class does not belong to the selected sub-fund")
    if item.structure is not FundStructure.ORDINARY_FUND:
        raise FundAnalysisError("this analysis contract accepts ordinary funds only")
    _timestamp(item.decision_time, "decision_time")
    if item.horizon not in {"1W", "1M", "3M", "6M", "1Y"}:
        raise FundAnalysisError("requested horizon is unsupported")
    if item.underlying_structure not in {"single", "fund_of_funds", "master_feeder"}:
        raise FundAnalysisError("underlying structure is unsupported")


def _timestamp(value: datetime | str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00") if isinstance(value, str) else value.isoformat())
    except (TypeError, ValueError) as exc:
        raise FundAnalysisError(f"{name} must be a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise FundAnalysisError(f"{name} must be timezone-aware")
    return parsed


def _cutoff_time(value: str) -> time:
    if not _TIME.fullmatch(value):
        raise FundAnalysisError("dealing cutoff must use HH:MM in the configured timezone")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise FundAnalysisError("dealing cutoff is invalid") from exc


def _currency(value: str, name: str) -> str:
    normalized = value.strip().upper()
    if not _CURRENCY.fullmatch(normalized):
        raise FundAnalysisError(f"{name} must be a three-letter currency code")
    return normalized


def _decimal(value: str | Decimal, name: str) -> Decimal:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise FundAnalysisError(f"{name} must be a decimal") from exc
    if not parsed.is_finite():
        raise FundAnalysisError(f"{name} must be finite")
    return parsed


def _config_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise FundAnalysisError(f"{name} must be encoded as a decimal string")
    return _decimal(value, name)


def _config_integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FundAnalysisError(f"{name} must be an integer at least {minimum}")
    return value


def _config_integer_map(value: object, expected: set[str]) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != expected:
        raise FundAnalysisError("fund analysis configuration mapping keys are invalid")
    return {key: _config_integer(days, key, 1) for key, days in value.items()}


def _term_reference(term: FundTerm) -> str:
    return term.source_id or term.overlay_id or ""


def _hash(value: Mapping[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "FUND_ANALYSIS_CONTRACT",
    "FUND_RETURN_CONTRACT",
    "FundAnalysisConfig",
    "FundAnalysisError",
    "FundAnalysisInput",
    "FundAnalysisRecord",
    "FundDistributionObservation",
    "FundLifecycleRisk",
    "FundMetricApplicability",
    "FundNAVObservation",
    "FundReturnDecomposition",
    "FundTermChangeEvent",
    "FundTermChangeKind",
    "FundUnderlyingLink",
    "analyze_fund",
    "load_fund_analysis_config",
]
