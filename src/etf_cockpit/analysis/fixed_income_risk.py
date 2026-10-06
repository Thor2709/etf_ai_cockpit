"""Transparent, deterministic fixed-income component and scenario risk."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from etf_cockpit.analysis.fixed_income_analytics import (
    CurveNode,
    FixedIncomeAnalyticsError,
    FixedIncomeValuationInput,
    _hash,
    _jsonable,
    calculate_fixed_income_analytics,
)

FIXED_INCOME_RISK_CONTRACT = "fixed-income-risk.v1"
FIXED_INCOME_RISK_SCHEMA_VERSION = 1


class FixedIncomeRiskError(ValueError):
    """Raised when fixed-income risk evidence cannot be used safely."""


@dataclass(frozen=True)
class RiskEvidence:
    value: Decimal | None
    unit: str
    method: str
    mapping: str
    assumptions: tuple[str, ...]
    support: str
    coverage: Decimal
    unknown_amount: Decimal | None
    lineage: tuple[str, ...]


@dataclass(frozen=True)
class CurveShock:
    scenario_id: str
    parallel_bps: Decimal = Decimal("0")
    key_rate_bps: tuple[tuple[Decimal, Decimal], ...] = ()


@dataclass(frozen=True)
class FixedIncomeRiskInput:
    valuation: FixedIncomeValuationInput
    instrument_kind: str
    position_face_value: Decimal
    scenarios: tuple[CurveShock, ...]
    spread_shock_bps: Decimal | None = None
    rating_change_loss: Decimal | None = None
    default_probability: Decimal | None = None
    recovery_rate: Decimal | None = None
    issuer_id: str | None = None
    quote_age_seconds: Decimal | None = None
    minimum_size: Decimal | None = None
    intended_liquidation_size: Decimal | None = None
    liquidity_cost_bps: Decimal | None = None
    callable: bool = False
    inflation_linked: bool = False
    fx_exposed: bool = False
    evidence_lineage: tuple[str, ...] = ()
    schema_version: int = FIXED_INCOME_RISK_SCHEMA_VERSION

    @property
    def input_hash(self) -> str:
        return _hash(
            {
                "contract": FIXED_INCOME_RISK_CONTRACT,
                "schema_version": self.schema_version,
                "input": _jsonable(asdict(self)),
                "execution_allowed": False,
            }
        )


@dataclass(frozen=True)
class BondScenarioResult:
    scenario_id: str
    parallel_bps: Decimal
    key_rate_bps: tuple[tuple[Decimal, Decimal], ...]
    rate_approximation_pnl: Decimal
    rate_full_reprice_pnl: Decimal
    approximation_discrepancy: Decimal
    spread_pnl: Decimal | None
    credit_pnl: Decimal | None
    default_pnl: Decimal | None
    liquidity_pnl: Decimal | None
    known_component_total: Decimal
    total_pnl: Decimal | None
    unknown_components: tuple[str, ...]
    unit: str
    method: str
    mapping: str
    assumptions: tuple[str, ...]
    support: str
    coverage: Decimal
    unknown_amount: Decimal | None
    lineage: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class FixedIncomeRiskRecord:
    instrument_id: str
    input_hash: str
    decision_time: datetime
    status: str
    instrument_kind: str
    issuer_id: str | None
    position_face_value: Decimal
    risk_label: str
    components: Mapping[str, RiskEvidence]
    scenarios: tuple[BondScenarioResult, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    contract: str = FIXED_INCOME_RISK_CONTRACT
    schema_version: int = FIXED_INCOME_RISK_SCHEMA_VERSION
    execution_allowed: bool = False


def calculate_fixed_income_risk(item: FixedIncomeRiskInput) -> FixedIncomeRiskRecord:
    """Calculate component risk and reconciled scenarios using canonical repricing."""

    _validate(item)
    base = calculate_fixed_income_analytics(item.valuation)
    if item.instrument_kind == "bond_etf":
        return _unsupported_etf(item)
    if item.valuation.curve is None or base.curve_model_value is None:
        raise FixedIncomeRiskError("typed curve and canonical model value are required")
    if base.modified_duration is None or base.convexity is None:
        raise FixedIncomeRiskError("canonical duration and convexity are required")
    scale = item.position_face_value / Decimal("100")
    components = _components(item, base.modified_duration, base.dv01)
    results: list[BondScenarioResult] = []
    for shock in item.scenarios:
        try:
            shifted = _reprice(item, shock)
        except FixedIncomeAnalyticsError as exc:
            raise FixedIncomeRiskError(
                f"canonical full repricing failed for scenario {shock.scenario_id}"
            ) from exc
        if shifted.curve_model_value is None:
            raise FixedIncomeRiskError("full repricing is unavailable")
        if shock.key_rate_bps:
            approx = _key_rate_approximation(item, shock, base.curve_model_value) * scale
            approximation_method = "sum_of_canonical_single_node_full_reprices"
        else:
            dy = shock.parallel_bps / Decimal("10000")
            approx = (
                base.curve_model_value
                * (-base.modified_duration * dy + base.convexity * dy * dy / Decimal("2"))
                * scale
            )
            approximation_method = "canonical_duration_convexity"
        full = (shifted.curve_model_value - base.curve_model_value) * scale
        spread = (
            -base.modified_duration
            * item.spread_shock_bps
            / Decimal("10000")
            * base.curve_model_value
            * scale
            if item.spread_shock_bps is not None
            else None
        )
        credit = (
            -item.rating_change_loss * scale
            if item.rating_change_loss is not None
            else None
        )
        default = (
            -item.default_probability
            * (Decimal("1") - item.recovery_rate)
            * item.position_face_value
            if item.default_probability is not None and item.recovery_rate is not None
            else None
        )
        liquidity = (
            -item.liquidity_cost_bps / Decimal("10000") * base.curve_model_value * scale
            if item.liquidity_cost_bps is not None
            else None
        )
        optional = (spread, credit, default, liquidity)
        unknown = tuple(
            name
            for name, value in zip(
                ("spread", "rating_change", "default_recovery", "liquidity"),
                optional,
                strict=True,
            )
            if value is None
        )
        known = sum((value for value in (full, *optional) if value is not None), Decimal("0"))
        results.append(
            BondScenarioResult(
                scenario_id=shock.scenario_id,
                parallel_bps=shock.parallel_bps,
                key_rate_bps=shock.key_rate_bps,
                rate_approximation_pnl=approx,
                rate_full_reprice_pnl=full,
                approximation_discrepancy=approx - full,
                spread_pnl=spread,
                credit_pnl=credit,
                default_pnl=default,
                liquidity_pnl=liquidity,
                known_component_total=known,
                total_pnl=known if not unknown else None,
                unknown_components=unknown,
                unit=item.valuation.currency,
                method=f"canonical_full_reprice_and_{approximation_method}",
                mapping="parallel" if not shock.key_rate_bps else "curve_node_exact_key_rate",
                assumptions=("pnl_in_position_currency", "components_additive"),
                support="supported",
                coverage=Decimal(5 - len(unknown)) / Decimal("5"),
                unknown_amount=None if not unknown else item.position_face_value,
                lineage=item.evidence_lineage
                + (item.valuation.input_hash, item.valuation.curve.curve_hash),
            )
        )
    warnings = _warnings(item)
    unknown_material = any(component.support != "supported" for component in components.values())
    material_component = any(
        value is not None and value != 0
        for value in (
            item.spread_shock_bps,
            item.rating_change_loss,
            item.default_probability,
            item.liquidity_cost_bps,
        )
    )
    material_flags = (
        material_component
        or bool(item.valuation.calls)
        or item.callable
        or item.inflation_linked
        or item.fx_exposed
        or bool(warnings)
    )
    low_duration = base.modified_duration < Decimal("2")
    label = "low" if low_duration and not unknown_material and not material_flags else "review_required"
    return FixedIncomeRiskRecord(
        instrument_id=item.valuation.instrument_id,
        input_hash=item.input_hash,
        decision_time=item.valuation.decision_time,
        status="available" if not unknown_material else "partial",
        instrument_kind=item.instrument_kind,
        issuer_id=item.issuer_id,
        position_face_value=item.position_face_value,
        risk_label=label,
        components=components,
        scenarios=tuple(results),
        warnings=warnings,
        limitations=("not_a_recommendation", "no_oas_or_option_model"),
    )


def aggregate_portfolio_scenarios(
    records: tuple[FixedIncomeRiskRecord, ...],
) -> tuple[Mapping[str, object], ...]:
    """Aggregate matching scenario components without inventing unknown totals."""

    scenario_ids = sorted({row.scenario_id for record in records for row in record.scenarios})
    output = []
    for scenario_id in scenario_ids:
        matched = [
            (
                record,
                next(
                    (row for row in record.scenarios if row.scenario_id == scenario_id),
                    None,
                ),
            )
            for record in records
        ]
        rows = [row for _, row in matched if row is not None]
        missing = tuple(
            record.instrument_id for record, row in matched if row is None
        )
        units = {row.unit for row in rows}
        if len(units) != 1:
            raise FixedIncomeRiskError("portfolio scenario currencies do not reconcile")
        known = sum((row.known_component_total for row in rows), Decimal("0"))
        unknown = tuple(sorted({name for row in rows for name in row.unknown_components}))
        reconciled = not missing and not unknown
        output.append(
            {
                "scenario_id": scenario_id,
                "known_component_total": known,
                "total_pnl": known if reconciled else None,
                "unknown_components": unknown,
                "missing_instruments": missing,
                "coverage": Decimal(len(records) - len(missing))
                / Decimal(len(records)),
                "reconciled": reconciled,
                "unit": next(iter(units)),
                "issuer_concentration": _issuer_concentration(records),
                "execution_allowed": False,
            }
        )
    return tuple(output)


def _components(
    item: FixedIncomeRiskInput, duration: Decimal, dv01: Decimal | None
) -> Mapping[str, RiskEvidence]:
    def evidence(name: str, value: Decimal | None, unit: str) -> RiskEvidence:
        return RiskEvidence(
            value=value,
            unit=unit,
            method=name,
            mapping=item.issuer_id or "unmapped",
            assumptions=("explicit_inputs_only",),
            support="supported" if value is not None else "unavailable",
            coverage=Decimal("1") if value is not None else Decimal("0"),
            unknown_amount=None if value is not None else item.position_face_value,
            lineage=item.evidence_lineage,
        )

    default_loss = (
        item.default_probability * (Decimal("1") - item.recovery_rate)
        if item.default_probability is not None and item.recovery_rate is not None
        else None
    )
    return {
        "rates": evidence(
            "canonical_position_dv01",
            dv01 * item.position_face_value / Decimal("100") if dv01 is not None else None,
            f"{item.valuation.currency}/bp",
        ),
        "spread": evidence("duration_spread", item.spread_shock_bps, "bps"),
        "credit": evidence("rating_change", item.rating_change_loss, item.valuation.currency),
        "default_recovery": evidence("explicit_pd_lgd", default_loss, "fraction"),
        "liquidity": evidence("explicit_liquidation_cost", item.liquidity_cost_bps, "bps"),
        "optionality": evidence(
            "call_schedule_flag",
            Decimal(int(item.callable or bool(item.valuation.calls))),
            "flag",
        ),
        "inflation": evidence("inflation_linkage_flag", Decimal(int(item.inflation_linked)), "flag"),
        "fx": evidence("currency_mismatch_flag", Decimal(int(item.fx_exposed)), "flag"),
        "duration": evidence("canonical_modified_duration", duration, "years"),
    }


def _validate(item: FixedIncomeRiskInput) -> None:
    if (
        not item.position_face_value.is_finite()
        or (
            item.default_probability is not None
            and not item.default_probability.is_finite()
        )
        or (item.recovery_rate is not None and not item.recovery_rate.is_finite())
    ):
        raise FixedIncomeRiskError("fixed-income risk numeric input is invalid")
    if (
        item.schema_version != 1
        or item.instrument_kind not in {"bond", "bond_etf"}
        or item.position_face_value <= 0
        or not item.scenarios
        or (item.default_probability is None) != (item.recovery_rate is None)
        or (
            item.default_probability is not None
            and not Decimal("0") <= item.default_probability <= Decimal("1")
        )
        or (
            item.recovery_rate is not None
            and not Decimal("0") <= item.recovery_rate <= Decimal("1")
        )
        or len({shock.scenario_id for shock in item.scenarios}) != len(item.scenarios)
    ):
        raise FixedIncomeRiskError("fixed-income risk input is invalid")
    optional_nonnegative = (
        item.rating_change_loss,
        item.quote_age_seconds,
        item.minimum_size,
        item.intended_liquidation_size,
        item.liquidity_cost_bps,
    )
    if any(
        value is not None and (not value.is_finite() or value < 0)
        for value in optional_nonnegative
    ) or (
        item.spread_shock_bps is not None and not item.spread_shock_bps.is_finite()
    ):
        raise FixedIncomeRiskError("optional risk evidence is invalid")
    curve_nodes = {node.tenor_years for node in (item.valuation.curve.nodes if item.valuation.curve else ())}
    for shock in item.scenarios:
        key_nodes = tuple(node for node, _ in shock.key_rate_bps)
        if (
            not shock.parallel_bps.is_finite()
            or any(not node.is_finite() or not shift.is_finite() for node, shift in shock.key_rate_bps)
            or len(set(key_nodes)) != len(key_nodes)
            or any(node not in curve_nodes for node in key_nodes)
        ):
            raise FixedIncomeRiskError("curve shock mapping is invalid")
    try:
        calculate_fixed_income_analytics(item.valuation)
    except FixedIncomeAnalyticsError as exc:
        raise FixedIncomeRiskError("canonical valuation input is invalid") from exc


def _key_shift(tenor: Decimal, shifts: tuple[tuple[Decimal, Decimal], ...]) -> Decimal:
    return next((shift for node, shift in shifts if node == tenor), Decimal("0"))


def _reprice(item: FixedIncomeRiskInput, shock: CurveShock):
    assert item.valuation.curve is not None
    shifted_curve = replace(
        item.valuation.curve,
        nodes=tuple(
            CurveNode(
                node.tenor_years,
                node.rate
                + (shock.parallel_bps + _key_shift(node.tenor_years, shock.key_rate_bps))
                / Decimal("10000"),
            )
            for node in item.valuation.curve.nodes
        ),
    )
    return calculate_fixed_income_analytics(
        replace(item.valuation, curve=shifted_curve, scenario_shifts_bps=())
    )


def _key_rate_approximation(
    item: FixedIncomeRiskInput, shock: CurveShock, base_value: Decimal
) -> Decimal:
    total = Decimal("0")
    if shock.parallel_bps:
        parallel = _reprice(
            item, CurveShock(f"{shock.scenario_id}:parallel", shock.parallel_bps)
        )
        if parallel.curve_model_value is None:
            raise FixedIncomeRiskError("parallel key-rate approximation unavailable")
        total += parallel.curve_model_value - base_value
    for node, shift in shock.key_rate_bps:
        single = _reprice(
            item,
            CurveShock(
                f"{shock.scenario_id}:{node}",
                key_rate_bps=((node, shift),),
            ),
        )
        if single.curve_model_value is None:
            raise FixedIncomeRiskError("key-rate approximation unavailable")
        total += single.curve_model_value - base_value
    return total


def _warnings(item: FixedIncomeRiskInput) -> tuple[str, ...]:
    warnings: list[str] = []
    if item.callable or item.valuation.calls:
        warnings.extend(("call_risk", "reinvestment_risk"))
    if item.inflation_linked:
        warnings.append("inflation_risk")
    if item.fx_exposed:
        warnings.append("fx_risk")
    if item.quote_age_seconds is None:
        warnings.append("quote_age_unknown")
    elif item.quote_age_seconds > Decimal("900"):
        warnings.append("stale_quote")
    if item.minimum_size is None:
        warnings.append("minimum_size_unknown")
    elif (
        item.intended_liquidation_size is not None
        and item.intended_liquidation_size < item.minimum_size
    ):
        warnings.append("below_minimum_size")
    return tuple(warnings)


def _unsupported_etf(item: FixedIncomeRiskInput) -> FixedIncomeRiskRecord:
    return FixedIncomeRiskRecord(
        instrument_id=item.valuation.instrument_id,
        input_hash=item.input_hash,
        decision_time=item.valuation.decision_time,
        status="unavailable",
        instrument_kind="bond_etf",
        issuer_id=item.issuer_id,
        position_face_value=item.position_face_value,
        risk_label="review_required",
        components={},
        scenarios=(),
        warnings=("bond_etf_requires_lookthrough_risk",),
        limitations=("bond_formulas_not_applied_to_bond_etf",),
    )


def _issuer_concentration(records: tuple[FixedIncomeRiskRecord, ...]) -> Mapping[str, object]:
    if any(record.issuer_id is None for record in records):
        return {
            "status": "partial",
            "amounts": {},
            "unknown_amount": sum(
                (record.position_face_value for record in records if record.issuer_id is None),
                Decimal("0"),
            ),
            "unit": "face_value",
        }
    amounts: dict[str, Decimal] = {}
    for record in records:
        assert record.issuer_id is not None
        amounts[record.issuer_id] = amounts.get(record.issuer_id, Decimal("0")) + record.position_face_value
    return {"status": "available", "amounts": amounts, "unknown_amount": Decimal("0"), "unit": "face_value"}
