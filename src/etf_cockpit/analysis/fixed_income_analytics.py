"""Deterministic fixed-rate and zero-coupon bond analytics.

All inputs are explicit and versioned. Contractual cash flows originate from
the fixed-income terms master; curve observations are a separate typed input.
No provider, UI, persistence, proposal, or execution authority lives here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import re
from typing import Mapping

from etf_cockpit.data.market_calendar import DayCountConvention, MarketCalendarService
from etf_cockpit.data.fixed_income_terms import (
    CouponSchedule,
    FixedIncomeSecurityTerms,
    RedemptionSchedule,
)


FIXED_INCOME_ANALYTICS_SCHEMA_VERSION = 1
FIXED_INCOME_ANALYTICS_CONTRACT = "fixed-income-analytics.v1"
REFERENCE_HARNESS_VERSION = "local-reference-harness.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class FixedIncomeAnalyticsError(ValueError):
    """Raised when deterministic analytics cannot be produced safely."""


@dataclass(frozen=True)
class ContractualCashFlow:
    payment_date: date
    amount: Decimal
    kind: str
    source_version_id: str
    accrual_start: date | None = None
    accrual_end: date | None = None
    ex_coupon_date: date | None = None


@dataclass(frozen=True)
class CallRedemption:
    call_date: date
    amount: Decimal
    source_id: str


@dataclass(frozen=True)
class CurveNode:
    tenor_years: Decimal
    rate: Decimal


@dataclass(frozen=True)
class DiscountCurveEvidence:
    curve_id: str
    curve_kind: str
    currency: str
    rate_unit: str
    compounding: str
    interpolation: str
    day_count: DayCountConvention
    nodes: tuple[CurveNode, ...]
    source_id: str
    source_version: str
    source_checksum: str
    as_of: datetime
    retrieved_at: datetime
    decision_time: datetime
    schema_version: int = 1

    @property
    def curve_hash(self) -> str:
        return _hash(_jsonable(asdict(self)))


@dataclass(frozen=True)
class ObservedBondPrice:
    clean_price: Decimal
    currency: str
    price_unit: str
    source_id: str
    source_checksum: str
    as_of: datetime
    retrieved_at: datetime


@dataclass(frozen=True)
class FixedIncomeValuationInput:
    instrument_id: str
    terms_version_id: str
    currency: str
    face_value: Decimal
    settlement_date: date
    maturity_date: date
    coupon_rate: Decimal
    coupon_frequency: int
    day_count: DayCountConvention
    cashflows: tuple[ContractualCashFlow, ...]
    decision_time: datetime
    clean_price: Decimal | None = None
    yield_to_maturity: Decimal | None = None
    calls: tuple[CallRedemption, ...] = ()
    curve: DiscountCurveEvidence | None = None
    observed_price: ObservedBondPrice | None = None
    scenario_shifts_bps: tuple[Decimal, ...] = (
        Decimal("-100"),
        Decimal("-50"),
        Decimal("50"),
        Decimal("100"),
    )
    yield_compounding: str = "periodic"
    explicit_stub: bool = False
    tolerance: Decimal = Decimal("0.000001")
    schema_version: int = FIXED_INCOME_ANALYTICS_SCHEMA_VERSION

    @property
    def input_hash(self) -> str:
        return _hash(
            {
                "schema_version": self.schema_version,
                "contract": FIXED_INCOME_ANALYTICS_CONTRACT,
                "input": _jsonable(asdict(self)),
                "execution_allowed": False,
            }
        )


@dataclass(frozen=True)
class YieldToCall:
    call_date: date
    call_amount: Decimal
    yield_value: Decimal
    source_id: str


@dataclass(frozen=True)
class ScenarioValue:
    shift_bps: Decimal
    model_value: Decimal
    change: Decimal


@dataclass(frozen=True)
class FixedIncomeValuationResult:
    instrument_id: str
    input_hash: str
    status: str
    curve_status: str
    settlement_date: date
    clean_price: Decimal | None
    dirty_price: Decimal | None
    accrued_interest: Decimal | None
    current_yield: Decimal | None
    yield_to_maturity: Decimal | None
    yields_to_call: tuple[YieldToCall, ...]
    yield_to_worst: Decimal | None
    yield_to_worst_basis: str | None
    macaulay_duration: Decimal | None
    modified_duration: Decimal | None
    convexity: Decimal | None
    dv01: Decimal | None
    pv01: Decimal | None
    curve_dirty_value: Decimal | None
    curve_model_value: Decimal | None
    observed_clean_price: Decimal | None
    observed_model_discrepancy: Decimal | None
    scenarios: tuple[ScenarioValue, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    warnings: tuple[str, ...]
    curve_hash: str | None
    terms_version_id: str
    schema_version: int = FIXED_INCOME_ANALYTICS_SCHEMA_VERSION
    execution_allowed: bool = False


@dataclass(frozen=True)
class DifferentialReference:
    fixture_id: str
    fixture_version: str
    provenance: str
    fixture_kind: str
    review_status: str
    expected: Mapping[str, Decimal]
    tolerances: Mapping[str, Decimal]
    source_checksum: str


@dataclass(frozen=True)
class DifferentialValidation:
    fixture_id: str
    harness_version: str
    status: str
    differences: Mapping[str, Decimal]
    provenance: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    execution_allowed: bool = False


def calculate_fixed_income_analytics(
    valuation: FixedIncomeValuationInput,
) -> FixedIncomeValuationResult:
    """Calculate one deterministic, non-executable bond analysis."""

    item = _validate_input(valuation)
    future = tuple(flow for flow in item.cashflows if flow.payment_date > item.settlement_date)
    if not future:
        raise FixedIncomeAnalyticsError("no contractual cash flows remain after settlement")
    accrued = accrued_interest(item)
    clean = item.clean_price
    ytm = item.yield_to_maturity
    if clean is None and ytm is None:
        raise FixedIncomeAnalyticsError("clean_price or yield_to_maturity is required")
    if clean is None:
        clean = clean_price_from_yield(item, ytm)
    if ytm is None:
        ytm = yield_from_clean_price(item, clean)
    dirty = clean + accrued
    coupon_annual = item.face_value * item.coupon_rate
    current_yield = (
        coupon_annual / (clean / Decimal("100") * item.face_value)
        if clean != 0
        else None
    )
    displayed_ytm = ytm.quantize(Decimal("0.0000000001"))
    ytc = tuple(_yield_to_call(item, clean, call) for call in item.calls)
    candidates = [(displayed_ytm, "maturity"), *((entry.yield_value, f"call:{entry.call_date.isoformat()}") for entry in ytc)]
    worst_value, worst_basis = min(candidates, key=lambda value: value[0])
    macaulay, modified, convexity, dv01 = _risk_measures(item, ytm, dirty)
    curve_dirty = _curve_value(item, item.curve, Decimal("0")) if item.curve else None
    curve_value = curve_dirty - accrued if curve_dirty is not None else None
    scenarios = (
        tuple(
            ScenarioValue(
                shift,
                shifted := _curve_value(item, item.curve, shift) - accrued,
                shifted - curve_value,
            )
            for shift in item.scenario_shifts_bps
        )
        if item.curve is not None and curve_value is not None
        else ()
    )
    observed = item.observed_price.clean_price if item.observed_price else None
    discrepancy = (
        observed - curve_value if observed is not None and curve_value is not None else None
    )
    warnings: list[str] = []
    if ytm < 0:
        warnings.append("negative_yield")
    if item.explicit_stub:
        warnings.append("explicit_stub_cashflow")
    if item.observed_price and item.observed_price.as_of > item.decision_time:
        raise FixedIncomeAnalyticsError("observed price is future-known")
    return FixedIncomeValuationResult(
        instrument_id=item.instrument_id,
        input_hash=item.input_hash,
        status="available" if item.curve is not None else "partial",
        curve_status="available" if item.curve is not None else "unavailable",
        settlement_date=item.settlement_date,
        clean_price=_q(clean),
        dirty_price=_q(dirty),
        accrued_interest=_q(accrued),
        current_yield=_q(current_yield),
        yield_to_maturity=displayed_ytm,
        yields_to_call=ytc,
        yield_to_worst=_q(worst_value),
        yield_to_worst_basis=worst_basis,
        macaulay_duration=_q(macaulay),
        modified_duration=_q(modified),
        convexity=_q(convexity),
        dv01=_q(dv01),
        pv01=_q(dv01),
        curve_dirty_value=_q(curve_dirty),
        curve_model_value=_q(curve_value),
        observed_clean_price=_q(observed),
        observed_model_discrepancy=_q(discrepancy),
        scenarios=scenarios,
        assumptions=(
            f"yield_compounding={item.yield_compounding}",
            f"coupon_frequency={item.coupon_frequency}",
            f"day_count={item.day_count.value}",
            "prices_per_100_face",
            "contractual_cashflows_from_terms_master",
        ),
        limitations=(
            "deterministic_contractual_analysis_only",
            "not_expected_return_or_recommendation",
            "no_oas_or_option_model",
            "observed_price_not_executable_quote",
            *(
                ("curve_valuation_unavailable_missing_typed_curve",)
                if item.curve is None
                else ()
            ),
        ),
        warnings=tuple(warnings),
        curve_hash=item.curve.curve_hash if item.curve else None,
        terms_version_id=item.terms_version_id,
        execution_allowed=False,
    )


def valuation_input_from_terms(
    terms: FixedIncomeSecurityTerms,
    coupon_schedule: CouponSchedule,
    redemption_schedule: RedemptionSchedule,
    *,
    settlement_date: date,
    decision_time: datetime,
    clean_price: Decimal | None = None,
    yield_to_maturity: Decimal | None = None,
    curve: DiscountCurveEvidence | None = None,
    observed_price: ObservedBondPrice | None = None,
) -> FixedIncomeValuationInput:
    """Adapt certified terms schedules without recomputing calendar conventions."""

    version = terms.version_id
    if (
        terms.schema_version != 1
        or terms.conflict_ids
        or terms.optionality.unsupported_features
        or terms.security_type not in {"government_bond", "corporate_bond"}
        or terms.coupon_type not in {"fixed_rate", "zero_coupon"}
        or terms.valid_from.date() > settlement_date
        or terms.known_at > decision_time
        or terms.retrieved_at > decision_time
        or terms.known_at > terms.retrieved_at
        or (terms.valid_to is not None and settlement_date >= terms.valid_to.date())
        or settlement_date < terms.issue_date
        or settlement_date >= terms.maturity_date
        or decision_time.tzinfo is None
        or
        coupon_schedule.instrument_id != terms.instrument_id
        or redemption_schedule.instrument_id != terms.instrument_id
        or coupon_schedule.source_version_id != version
        or redemption_schedule.source_version_id != version
    ):
        raise FixedIncomeAnalyticsError("terms schedules do not share certified lineage")
    _validate_certified_schedules(terms, coupon_schedule, redemption_schedule)
    flows = tuple(
        ContractualCashFlow(
            payment.payment_date,
            payment.amount,
            "coupon",
            payment.source_version_id,
            payment.accrual_start,
            payment.accrual_end,
            payment.ex_coupon_date,
        )
        for payment in coupon_schedule.payments
    ) + tuple(
        ContractualCashFlow(
            payment.payment_date,
            payment.amount,
            "redemption",
            payment.source_version_id,
        )
        for payment in redemption_schedule.payments
    )
    return _validate_input(
        FixedIncomeValuationInput(
            instrument_id=terms.instrument_id,
            terms_version_id=version,
            currency=terms.currency,
            face_value=terms.face_value,
            settlement_date=settlement_date,
            maturity_date=terms.maturity_date,
            coupon_rate=terms.coupon_rate,
            coupon_frequency=terms.coupon_frequency,
            day_count=terms.day_count,
            cashflows=tuple(sorted(flows, key=lambda flow: flow.payment_date)),
            decision_time=decision_time,
            clean_price=clean_price,
            yield_to_maturity=yield_to_maturity,
            curve=curve,
            observed_price=observed_price,
        )
    )


def _validate_certified_schedules(
    terms: FixedIncomeSecurityTerms,
    coupons: CouponSchedule,
    redemptions: RedemptionSchedule,
) -> None:
    expected_coupon = (
        terms.face_value * terms.coupon_rate / Decimal(terms.coupon_frequency)
        if terms.coupon_frequency
        else Decimal("0")
    )
    previous_end = terms.issue_date
    for expected_sequence, payment in enumerate(coupons.payments, start=1):
        if (
            payment.sequence != expected_sequence
            or payment.accrual_start != previous_end
            or payment.accrual_end != payment.contractual_date
            or payment.contractual_date <= previous_end
            or payment.payment_date < payment.contractual_date
            or payment.ex_coupon_date > payment.payment_date
            or payment.amount != expected_coupon
            or payment.currency != terms.currency
            or payment.source_version_id != terms.version_id
            or payment.source_id != terms.source_id
            or payment.source_checksum != terms.source_checksum
        ):
            raise FixedIncomeAnalyticsError("coupon schedule certification is invalid")
        previous_end = payment.accrual_end
    if terms.coupon_type == "fixed_rate":
        if not coupons.payments or previous_end != terms.maturity_date:
            raise FixedIncomeAnalyticsError("coupon schedule is incomplete")
    elif coupons.payments:
        raise FixedIncomeAnalyticsError("zero-coupon schedule contains coupons")
    if (
        len(redemptions.payments) != 1
        or redemptions.payments[0].contractual_date != terms.maturity_date
        or redemptions.payments[0].payment_date < terms.maturity_date
        or redemptions.payments[0].amount != terms.face_value
        or redemptions.payments[0].currency != terms.currency
        or redemptions.payments[0].source_version_id != terms.version_id
        or redemptions.payments[0].source_id != terms.source_id
        or redemptions.payments[0].source_checksum != terms.source_checksum
    ):
        raise FixedIncomeAnalyticsError("redemption schedule certification is invalid")


def accrued_interest(valuation: FixedIncomeValuationInput) -> Decimal:
    """Return accrued interest per 100 face, including ex-coupon convention."""

    item = _validate_input(valuation)
    coupons = tuple(flow for flow in item.cashflows if flow.kind == "coupon")
    for flow in coupons:
        if (
            flow.accrual_start is None
            or flow.accrual_end is None
            or not (flow.accrual_start <= item.settlement_date < flow.accrual_end)
        ):
            continue
        full = MarketCalendarService.year_fraction(
            flow.accrual_start, flow.accrual_end, item.day_count
        )
        elapsed = MarketCalendarService.year_fraction(
            flow.accrual_start, item.settlement_date, item.day_count
        )
        if full <= 0:
            raise FixedIncomeAnalyticsError("coupon accrual period is invalid")
        amount = flow.amount * Decimal(str(elapsed / full))
        if (
            flow.ex_coupon_date is not None
            and flow.ex_coupon_date <= item.settlement_date < flow.payment_date
        ):
            amount -= flow.amount
        return amount / item.face_value * Decimal("100")
    return Decimal("0")


def clean_price_from_yield(
    valuation: FixedIncomeValuationInput, yield_value: Decimal | None
) -> Decimal:
    item = _validate_input(valuation)
    if yield_value is None:
        raise FixedIncomeAnalyticsError("yield is required")
    dirty_value = _present_value_from_yield(item, yield_value)
    dirty_price = dirty_value / item.face_value * Decimal("100")
    return dirty_price - accrued_interest(item)


def yield_from_clean_price(
    valuation: FixedIncomeValuationInput, clean_price: Decimal
) -> Decimal:
    item = _validate_input(valuation)
    target = (clean_price + accrued_interest(item)) / Decimal("100") * item.face_value
    frequency = max(item.coupon_frequency, 1)
    lower = Decimal("-0.999999") * Decimal(frequency)
    upper = Decimal("10")
    lower_value = _present_value_from_yield(item, lower) - target
    upper_value = _present_value_from_yield(item, upper) - target
    if lower_value * upper_value > 0:
        raise FixedIncomeAnalyticsError("price does not admit a bounded yield solution")
    for _ in range(200):
        midpoint = (lower + upper) / Decimal("2")
        value = _present_value_from_yield(item, midpoint) - target
        if abs(value) <= item.tolerance:
            return midpoint
        if value > 0:
            lower = midpoint
        else:
            upper = midpoint
    return (lower + upper) / Decimal("2")


def validate_differential_reference(
    result: FixedIncomeValuationResult,
    reference: DifferentialReference,
) -> DifferentialValidation:
    if not _SHA256.fullmatch(reference.source_checksum.casefold()):
        raise FixedIncomeAnalyticsError("reference checksum must be SHA-256")
    if (
        not reference.fixture_id
        or not reference.fixture_version
        or not reference.provenance
        or reference.fixture_kind != "local_golden"
        or reference.review_status != "locally_reviewed"
        or not reference.expected
        or any(not value.is_finite() for value in reference.expected.values())
        or any(value < 0 or not value.is_finite() for value in reference.tolerances.values())
    ):
        raise FixedIncomeAnalyticsError("reference provenance/version is required")
    differences: dict[str, Decimal] = {}
    failures: list[str] = []
    for field, expected in reference.expected.items():
        actual = getattr(result, field, None)
        if actual is None:
            failures.append(f"{field}:unavailable")
            continue
        difference = abs(Decimal(str(actual)) - expected)
        differences[field] = difference
        tolerance = reference.tolerances.get(field)
        if tolerance is None or difference > tolerance:
            failures.append(f"{field}:outside_tolerance")
    return DifferentialValidation(
        fixture_id=reference.fixture_id,
        harness_version=REFERENCE_HARNESS_VERSION,
        status="passed" if not failures else "quarantined",
        differences=differences,
        provenance=reference.provenance,
        warnings=tuple(failures),
        limitations=("external_pinned_library_validation_unavailable",),
        execution_allowed=False,
    )


def _yield_to_call(
    item: FixedIncomeValuationInput,
    clean_price: Decimal,
    call: CallRedemption,
) -> YieldToCall:
    if not (item.settlement_date < call.call_date < item.maturity_date):
        raise FixedIncomeAnalyticsError("call date must be after settlement and before maturity")
    flows = tuple(
        flow for flow in item.cashflows if flow.payment_date <= call.call_date and flow.kind != "redemption"
    ) + (
        ContractualCashFlow(
            call.call_date,
            call.amount,
            "call_redemption",
            item.terms_version_id,
        ),
    )
    called = replace(
        item,
        maturity_date=call.call_date,
        cashflows=flows,
        calls=(),
    )
    solved = yield_from_clean_price(called, clean_price)
    return YieldToCall(
        call.call_date,
        call.amount,
        solved.quantize(Decimal("0.0000000001")),
        call.source_id,
    )


def _risk_measures(
    item: FixedIncomeValuationInput, ytm: Decimal, dirty_price: Decimal
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    flows = tuple(flow for flow in item.cashflows if flow.payment_date > item.settlement_date)
    frequency = max(item.coupon_frequency, 1)
    base = Decimal("1") + ytm / Decimal(frequency)
    if base <= 0:
        raise FixedIncomeAnalyticsError("yield is outside periodic compounding domain")
    weighted = Decimal("0")
    convex = Decimal("0")
    pv_total = Decimal("0")
    for flow in flows:
        t = Decimal(str(_time(item, flow.payment_date)))
        pv = flow.amount / (base ** (Decimal(frequency) * t))
        pv_total += pv
        weighted += t * pv
        convex += t * (t + Decimal("1") / Decimal(frequency)) * pv
    macaulay = weighted / pv_total
    modified = macaulay / base
    convexity = convex / pv_total / (base * base)
    bump = Decimal("0.0001")
    up = _present_value_from_yield(item, ytm + bump)
    down = _present_value_from_yield(item, ytm - bump)
    dv01_value = (down - up) / Decimal("2") / item.face_value * Decimal("100")
    return macaulay, modified, convexity, dv01_value


def _present_value_from_yield(
    item: FixedIncomeValuationInput, yield_value: Decimal
) -> Decimal:
    frequency = max(item.coupon_frequency, 1)
    base = Decimal("1") + yield_value / Decimal(frequency)
    if base <= 0:
        raise FixedIncomeAnalyticsError("yield is outside periodic compounding domain")
    return sum(
        (
            flow.amount
            / (base ** (Decimal(frequency) * Decimal(str(_time(item, flow.payment_date)))))
            for flow in item.cashflows
            if flow.payment_date > item.settlement_date
        ),
        Decimal("0"),
    )


def _curve_value(
    item: FixedIncomeValuationInput,
    curve: DiscountCurveEvidence | None,
    shift_bps: Decimal,
) -> Decimal:
    if curve is None:
        raise FixedIncomeAnalyticsError("curve evidence is required")
    curve = _validate_curve(curve, item)
    total = Decimal("0")
    for flow in item.cashflows:
        if flow.payment_date <= item.settlement_date:
            continue
        tenor = Decimal(
            str(
                MarketCalendarService.year_fraction(
                    item.settlement_date,
                    flow.payment_date,
                    curve.day_count,
                )
            )
        )
        rate = _interpolate(curve.nodes, tenor) + shift_bps / Decimal("10000")
        if curve.compounding == "continuous":
            discount = Decimal(str(math.exp(-float(rate * tenor))))
        elif curve.compounding == "annual":
            if Decimal("1") + rate <= 0:
                raise FixedIncomeAnalyticsError("curve rate outside annual domain")
            discount = Decimal("1") / ((Decimal("1") + rate) ** tenor)
        else:
            denominator = Decimal("1") + rate * tenor
            if denominator <= 0:
                raise FixedIncomeAnalyticsError("curve rate outside simple domain")
            discount = Decimal("1") / denominator
        total += flow.amount * discount
    return total / item.face_value * Decimal("100")


def _interpolate(nodes: tuple[CurveNode, ...], tenor: Decimal) -> Decimal:
    if tenor <= nodes[0].tenor_years:
        return nodes[0].rate
    if tenor >= nodes[-1].tenor_years:
        return nodes[-1].rate
    for left, right in zip(nodes, nodes[1:]):
        if left.tenor_years <= tenor <= right.tenor_years:
            weight = (tenor - left.tenor_years) / (
                right.tenor_years - left.tenor_years
            )
            return left.rate + weight * (right.rate - left.rate)
    raise FixedIncomeAnalyticsError("curve interpolation failed")


def _validate_input(
    item: FixedIncomeValuationInput,
) -> FixedIncomeValuationInput:
    if not isinstance(item, FixedIncomeValuationInput):
        raise FixedIncomeAnalyticsError("valuation input type is invalid")
    if item.schema_version != FIXED_INCOME_ANALYTICS_SCHEMA_VERSION:
        raise FixedIncomeAnalyticsError("analytics schema version is unsupported")
    if not item.instrument_id or not item.terms_version_id:
        raise FixedIncomeAnalyticsError("instrument and terms version are required")
    if not _CURRENCY.fullmatch(item.currency.upper()):
        raise FixedIncomeAnalyticsError("currency must be explicit")
    if not item.face_value.is_finite() or item.face_value <= 0 or item.maturity_date <= item.settlement_date:
        raise FixedIncomeAnalyticsError("face value or maturity is invalid")
    if (
        not item.coupon_rate.is_finite()
        or item.coupon_rate < 0
        or item.coupon_rate > 1
        or (item.coupon_frequency == 0 and item.coupon_rate != 0)
        or (item.coupon_frequency > 0 and item.coupon_rate == 0)
    ):
        raise FixedIncomeAnalyticsError("coupon rate/frequency is invalid")
    if item.decision_time.tzinfo is None:
        raise FixedIncomeAnalyticsError("decision_time must be timezone-aware")
    if item.yield_compounding != "periodic":
        raise FixedIncomeAnalyticsError("only periodic yield compounding is supported")
    if item.coupon_frequency not in {0, 1, 2, 4, 12}:
        raise FixedIncomeAnalyticsError("coupon frequency is unsupported")
    if not item.cashflows:
        raise FixedIncomeAnalyticsError("contractual cash flows are required")
    if item.tolerance <= 0 or not item.tolerance.is_finite():
        raise FixedIncomeAnalyticsError("tolerance must be finite and positive")
    if any(
        value is not None and (not value.is_finite() or value <= 0)
        for value in (item.clean_price,)
    ) or any(
        value is not None and not value.is_finite()
        for value in (item.yield_to_maturity,)
    ):
        raise FixedIncomeAnalyticsError("price/yield is invalid")
    if item.clean_price is not None and item.yield_to_maturity is not None:
        implied = clean_price_from_yield(
            replace(item, clean_price=None), item.yield_to_maturity
        )
        if abs(implied - item.clean_price) > item.tolerance:
            raise FixedIncomeAnalyticsError("clean price and yield are contradictory")
    if any(not shift.is_finite() for shift in item.scenario_shifts_bps):
        raise FixedIncomeAnalyticsError("scenario shifts must be finite")
    call_dates = [call.call_date for call in item.calls]
    if call_dates != sorted(call_dates) or len(set(call_dates)) != len(call_dates):
        raise FixedIncomeAnalyticsError("call schedule is duplicate or out of order")
    if any(
        not call.amount.is_finite()
        or call.amount <= 0
        or not call.source_id.strip()
        or not (item.settlement_date < call.call_date < item.maturity_date)
        for call in item.calls
    ):
        raise FixedIncomeAnalyticsError("call schedule is invalid")
    dates = [flow.payment_date for flow in item.cashflows]
    if dates != sorted(dates):
        raise FixedIncomeAnalyticsError("cash flows must be date ordered")
    if any(
        not flow.amount.is_finite()
        or flow.amount <= 0
        or flow.source_version_id != item.terms_version_id
        or flow.kind not in {"coupon", "redemption", "call_redemption"}
        for flow in item.cashflows
    ):
        raise FixedIncomeAnalyticsError("cash flow amount/source is invalid")
    for flow in item.cashflows:
        if flow.kind == "coupon":
            if flow.accrual_start is None or flow.accrual_end is None:
                raise FixedIncomeAnalyticsError("coupon accrual dates are required")
            if flow.accrual_start >= flow.accrual_end or flow.payment_date < flow.accrual_end:
                raise FixedIncomeAnalyticsError("coupon accrual ordering is invalid")
            if item.coupon_frequency == 0:
                raise FixedIncomeAnalyticsError("zero frequency cannot contain coupons")
            regular = abs(
                MarketCalendarService.year_fraction(
                    flow.accrual_start, flow.accrual_end, item.day_count
                )
                - (1 / item.coupon_frequency)
            ) <= 0.02
            if not regular and not item.explicit_stub:
                raise FixedIncomeAnalyticsError("stub cash flow must be explicit")
    if item.curve is not None:
        _validate_curve(item.curve, item)
    if item.observed_price is not None:
        observed = item.observed_price
        if observed.currency != item.currency or observed.price_unit != "per_100":
            raise FixedIncomeAnalyticsError("observed price currency/unit mismatch")
        if (
            observed.as_of.tzinfo is None
            or observed.retrieved_at.tzinfo is None
            or observed.as_of > observed.retrieved_at
            or observed.retrieved_at > item.decision_time
        ):
            raise FixedIncomeAnalyticsError("observed price is future-known")
        if (
            not observed.clean_price.is_finite()
            or observed.clean_price <= 0
            or not observed.source_id.strip()
        ):
            raise FixedIncomeAnalyticsError("observed price/source is invalid")
        if not _SHA256.fullmatch(observed.source_checksum.casefold()):
            raise FixedIncomeAnalyticsError("observed price checksum is invalid")
    return item


def _validate_curve(
    curve: DiscountCurveEvidence, item: FixedIncomeValuationInput
) -> DiscountCurveEvidence:
    required = (
        curve.curve_id,
        curve.source_id,
        curve.source_version,
        curve.currency,
        curve.rate_unit,
        curve.compounding,
        curve.interpolation,
    )
    if any(not str(value).strip() for value in required):
        raise FixedIncomeAnalyticsError("curve metadata is incomplete")
    if curve.schema_version != 1 or curve.curve_kind != "zero":
        raise FixedIncomeAnalyticsError("curve kind/schema is unsupported")
    if curve.currency != item.currency or curve.rate_unit != "decimal":
        raise FixedIncomeAnalyticsError("curve currency/unit mismatch")
    if curve.compounding not in {"annual", "continuous", "simple"}:
        raise FixedIncomeAnalyticsError("curve compounding is unsupported")
    if curve.interpolation != "linear_zero":
        raise FixedIncomeAnalyticsError("curve interpolation is unsupported")
    if curve.day_count not in {
        DayCountConvention.ACT_365F,
        DayCountConvention.ACT_360,
        DayCountConvention.ACT_ACT_ISDA,
    }:
        raise FixedIncomeAnalyticsError("curve day-count is unsupported")
    if not _SHA256.fullmatch(curve.source_checksum.casefold()):
        raise FixedIncomeAnalyticsError("curve checksum is invalid")
    for value in (curve.as_of, curve.retrieved_at, curve.decision_time):
        if value.tzinfo is None:
            raise FixedIncomeAnalyticsError("curve chronology must be timezone-aware")
    if (
        curve.as_of > curve.retrieved_at
        or curve.retrieved_at > curve.decision_time
        or curve.decision_time > item.decision_time
    ):
        raise FixedIncomeAnalyticsError("curve evidence is future-known")
    if len(curve.nodes) < 2:
        raise FixedIncomeAnalyticsError("curve requires at least two explicit nodes")
    tenors = [node.tenor_years for node in curve.nodes]
    if tenors != sorted(tenors) or len(set(tenors)) != len(tenors) or tenors[0] <= 0:
        raise FixedIncomeAnalyticsError("curve nodes are duplicate or out of order")
    if any(not node.rate.is_finite() for node in curve.nodes):
        raise FixedIncomeAnalyticsError("curve rates must be finite")
    return curve


def _time(item: FixedIncomeValuationInput, payment_date: date) -> float:
    return MarketCalendarService.year_fraction(
        item.settlement_date, payment_date, item.day_count
    )


def _q(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.0000000001")) if value is not None else None


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        if isinstance(value, datetime) and value.tzinfo:
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _hash(payload: object) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
