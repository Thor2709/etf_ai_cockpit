"""Deterministic, non-executable monthly decision evidence projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from types import MappingProxyType
from typing import Literal

from etf_cockpit.application.benchmark_reference import validate_benchmark_reference
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry


MONTHLY_DECISION_TEMPLATE_SCHEMA = "monthly-decision-template.v2"
MONTHLY_REBALANCE_CADENCE = "monthly"
NEXT_SESSION_EXECUTION_ASSUMPTION = "next_session"
ALTERNATIVE_NAMES = ("basket", "benchmark", "cash", "no_action")
SECTION_NAMES = (
    "expected_returns",
    "optimiser",
    "costs",
    "events",
    "forward_evidence",
    "paper_outcomes",
    "concentration",
    "assumptions",
)
_STATUSES = frozenset({"available", "partial", "pending", "unavailable"})
_RELATIVE_RETURN_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class MonthlyDecisionTemplate:
    """One immutable display projection composed from existing read contracts."""

    status: Literal["available", "partial", "unavailable"]
    benchmark_reference: Mapping[str, object]
    alternatives: Mapping[str, object]
    expected_returns: Mapping[str, object]
    optimiser: Mapping[str, object]
    costs: Mapping[str, object]
    events: Mapping[str, object]
    forward_evidence: Mapping[str, object]
    paper_outcomes: Mapping[str, object]
    concentration: Mapping[str, object]
    assumptions: Mapping[str, object]
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    source: str
    execution_allowed: Literal[False] = False
    schema: str = MONTHLY_DECISION_TEMPLATE_SCHEMA
    cadence: str = MONTHLY_REBALANCE_CADENCE
    execution_assumption: str = NEXT_SESSION_EXECUTION_ASSUMPTION

    def __post_init__(self) -> None:
        """Freeze the composed evidence at the application boundary."""

        if self.execution_allowed is not False:
            raise ValueError("monthly decision template cannot grant execution authority")
        for name in (
            "benchmark_reference",
            "alternatives",
            "expected_returns",
            "optimiser",
            "costs",
            "events",
            "forward_evidence",
            "paper_outcomes",
            "concentration",
            "assumptions",
        ):
            object.__setattr__(self, name, _freeze_json(getattr(self, name)))

    def projection(self) -> dict[str, object]:
        """Return a fresh JSON projection without changing supplied evidence."""

        return _json_copy(
            {
                "schema": self.schema,
                "status": self.status,
                "cadence": self.cadence,
                "execution_assumption": self.execution_assumption,
                "execution_allowed": False,
                "source": self.source,
                "benchmark_reference": self.benchmark_reference,
                "alternatives": self.alternatives,
                "expected_returns": self.expected_returns,
                "optimiser": self.optimiser,
                "costs": self.costs,
                "events": self.events,
                "forward_evidence": self.forward_evidence,
                "paper_outcomes": self.paper_outcomes,
                "concentration": self.concentration,
                "assumptions": self.assumptions,
                "warnings": self.warnings,
                "blockers": self.blockers,
            }
        )


def unavailable_monthly_evidence(reason: str, **identity: object) -> dict[str, object]:
    """Create one explicit unavailable input projection for a missing producer."""

    return {
        "status": "unavailable",
        "reason": str(reason or "evidence_unavailable"),
        **identity,
        "execution_allowed": False,
    }


def build_monthly_decision_template(
    *,
    benchmark_reference: Mapping[str, object] | None,
    alternatives: Mapping[str, object] | None = None,
    expected_returns: Mapping[str, object] | None = None,
    optimiser: Mapping[str, object] | None = None,
    costs: Mapping[str, object] | None = None,
    events: Mapping[str, object] | None = None,
    forward_evidence: Mapping[str, object] | None = None,
    paper_outcomes: Mapping[str, object] | None = None,
    concentration: Mapping[str, object] | None = None,
    assumptions: Mapping[str, object] | None = None,
    benchmark_registry: CanonicalBenchmarkRegistry | None = None,
    evidence_maturity: object = None,
    sample_size: object = None,
    source: str = "local_evidence",
) -> MonthlyDecisionTemplate:
    """Compose caller-supplied evidence without deriving financial values."""

    blockers: list[str] = []
    warnings: list[str] = []
    reference, reference_error = _normalise_reference(
        benchmark_reference,
        benchmark_registry=benchmark_registry,
    )
    if reference_error:
        blockers.append(reference_error)

    alternative_projection, alternative_errors = _normalise_alternatives(
        alternatives,
        reference,
        cutoff=_reference_cutoff(reference),
    )
    blockers.extend(alternative_errors)

    supplied = {
        "expected_returns": expected_returns,
        "optimiser": optimiser,
        "costs": costs,
        "events": events,
        "forward_evidence": forward_evidence,
        "paper_outcomes": paper_outcomes,
        "concentration": concentration,
        "assumptions": assumptions,
    }
    validators = {
        "expected_returns": _validate_expected_returns,
        "optimiser": _validate_optimiser,
        "costs": _validate_costs,
        "events": _validate_events,
        "forward_evidence": _validate_forward_evidence,
        "paper_outcomes": _validate_paper_outcomes,
        "concentration": _validate_concentration,
        "assumptions": _validate_assumptions,
    }
    sections: dict[str, dict[str, object]] = {}
    cutoff = _reference_cutoff(reference)
    for name in SECTION_NAMES:
        section, errors = _normalise_section(name, supplied[name], validators[name], cutoff=cutoff)
        sections[name] = section
        blockers.extend(errors)

    horizon_errors = _horizon_mismatch_errors(alternative_projection, sections)
    blockers.extend(horizon_errors)

    evidence_warning = _evidence_warning(evidence_maturity, sample_size)
    if evidence_warning:
        warnings.append(evidence_warning)
    for dimension in ("sector", "theme"):
        value = sections["concentration"].get(dimension)
        if not isinstance(value, Mapping) or value.get("status") != "available":
            warnings.append(f"{dimension.title()} concentration evidence is unavailable or partial.")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    malformed = any(
        item.endswith(
            (
                "_malformed",
                "_invalid",
                "_authority_invalid",
                "_stale",
                "_future_known",
                "_untrusted",
                "_unbound",
                "_financial_invalid",
                "_horizon_mismatch",
            )
        )
        for item in blockers
    )
    fully_available = (
        not reference_error
        and all(
            isinstance(alternative_projection.get(name), Mapping)
            and alternative_projection[name].get("status") == "available"  # type: ignore[index]
            for name in ALTERNATIVE_NAMES
        )
        and all(sections[name].get("status") == "available" for name in SECTION_NAMES)
    )
    if reference_error or malformed:
        status: Literal["available", "partial", "unavailable"] = "unavailable"
    elif fully_available:
        status = "available"
    else:
        status = "partial"
    return MonthlyDecisionTemplate(
        status=status,
        benchmark_reference=reference,
        alternatives=alternative_projection,
        expected_returns=sections["expected_returns"],
        optimiser=sections["optimiser"],
        costs=sections["costs"],
        events=sections["events"],
        forward_evidence=sections["forward_evidence"],
        paper_outcomes=sections["paper_outcomes"],
        concentration=sections["concentration"],
        assumptions=sections["assumptions"],
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        source=str(source or "local_evidence"),
    )


def monthly_decision_template_lines(template: MonthlyDecisionTemplate) -> tuple[str, ...]:
    """Format the same bounded summary on all three product surfaces."""

    projection = template.projection()
    alternatives = projection["alternatives"]
    expected = projection["expected_returns"]
    optimiser = projection["optimiser"]
    costs = projection["costs"]
    events = projection["events"]
    forward = projection["forward_evidence"]
    paper = projection["paper_outcomes"]
    concentration = projection["concentration"]
    return (
        f"Status: {template.status} | cadence: monthly | execution assumption: next-session | execution_allowed=false",
        _alternative_line("Basket", alternatives["basket"]),
        _alternative_line("Benchmark", alternatives["benchmark"]),
        _alternative_line("Cash proxy", alternatives["cash"]),
        _alternative_line("No-action context", alternatives["no_action"]),
        _distribution_line(expected),
        _optimiser_line(optimiser),
        _cost_line(costs),
        f"Events/next-session evidence: {events.get('status', 'unavailable')} | source={events.get('source_id', 'unavailable')}",
        f"Forward evidence: {forward.get('status', 'unavailable')} | paper outcomes: {paper.get('status', 'unavailable')}",
        _concentration_line(concentration),
        f"Evidence warning: {' '.join(template.warnings) if template.warnings else 'none'}",
        f"Unavailable context: {', '.join(template.blockers) if template.blockers else 'none'}",
    )


def _normalise_reference(
    reference: Mapping[str, object] | None,
    *,
    benchmark_registry: CanonicalBenchmarkRegistry | None,
) -> tuple[dict[str, object], str | None]:
    if not isinstance(reference, Mapping):
        return unavailable_monthly_evidence("canonical_reference_unavailable"), "canonical_reference_unavailable"
    if not _safe_execution_disabled(reference):
        return unavailable_monthly_evidence("canonical_reference_authority_invalid"), "canonical_reference_authority_invalid"
    try:
        result = _json_copy(reference)
    except (TypeError, ValueError):
        return unavailable_monthly_evidence("canonical_reference_malformed"), "canonical_reference_malformed"
    if result.get("status") != "available":
        return result, "canonical_reference_unavailable"
    benchmark = result.get("benchmark")
    cash = result.get("cash")
    references = result.get("references")
    if (
        not _available_identity(benchmark)
        or not _available_identity(cash)
        or not _text(result.get("benchmark_data_id"))
        or not _text(result.get("registry_hash"))
        or not isinstance(result.get("selected_records"), Mapping)
        or not isinstance(result.get("provenance"), Mapping)
        or not _sequence(references)
    ):
        return unavailable_monthly_evidence("canonical_reference_malformed"), "canonical_reference_malformed"
    no_action = [item for item in references if isinstance(item, Mapping) and item.get("method") == "no_trade"]
    if len(no_action) != 1 or not _available_reference_identity(no_action[0]):
        return unavailable_monthly_evidence("canonical_no_action_reference_unavailable"), "canonical_reference_invalid"
    if validate_benchmark_reference(
        result,
        result.get("benchmark_data_id"),
        registry=benchmark_registry,
    ) is None:
        return unavailable_monthly_evidence("canonical_reference_validation_failed"), "canonical_reference_invalid"
    if _reference_cutoff(result) is None:
        return unavailable_monthly_evidence("canonical_reference_cutoff_unavailable"), "canonical_reference_invalid"
    return result, None


def _normalise_alternatives(
    value: Mapping[str, object] | None,
    reference: Mapping[str, object],
    *,
    cutoff: datetime | None,
) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    if value is not None and not isinstance(value, Mapping):
        value = None
        errors.append("alternatives_malformed")
    if isinstance(value, Mapping) and set(value) - set(ALTERNATIVE_NAMES):
        errors.append("alternatives_invalid")
    result: dict[str, object] = {}
    for name in ALTERNATIVE_NAMES:
        raw = value.get(name) if isinstance(value, Mapping) else None
        item, item_errors = _normalise_alternative(name, raw, cutoff=cutoff)
        result[name] = item
        errors.extend(item_errors)
    if reference.get("status") != "available":
        for name in ALTERNATIVE_NAMES:
            result[name] = unavailable_monthly_evidence(f"{name}_canonical_reference_unavailable")
    else:
        benchmark = reference.get("benchmark")
        cash = reference.get("cash")
        references = reference.get("references")
        no_action = next(
            (item for item in references if isinstance(item, Mapping) and item.get("method") == "no_trade"),
            None,
        ) if _sequence(references) else None
        expected_identities = {
            "benchmark": _reference_identity(benchmark),
            "cash": _reference_identity(cash),
            "no_action": _reference_identity(no_action),
        }
        for name, expected_identity in expected_identities.items():
            item = result[name]
            actual_identity = (
                item.get("reference_id"),
                item.get("reference_version"),
                item.get("reference_content_hash"),
            ) if isinstance(item, Mapping) else None
            if isinstance(item, Mapping) and item.get("status") == "available" and actual_identity != expected_identity:
                result[name] = unavailable_monthly_evidence(f"{name}_reference_identity_mismatch")
                errors.append(f"{name}_alternative_invalid")
    available_windows = {
        name: _alternative_window(item)
        for name, item in result.items()
        if isinstance(item, Mapping) and item.get("status") == "available"
    }
    if len(available_windows) == len(ALTERNATIVE_NAMES) and len(set(available_windows.values())) > 1:
        for name, item in tuple(result.items()):
            if isinstance(item, Mapping) and item.get("status") == "available":
                result[name] = unavailable_monthly_evidence(f"{name}_alternative_window_mismatch")
        errors.append("monthly_horizon_mismatch")
    available_bundles = {
        name: _alternative_bundle(item)
        for name, item in result.items()
        if isinstance(item, Mapping) and _comparison_bundle_participant(item)
    }
    if len(available_bundles) > 1 and len(set(available_bundles.values())) > 1:
        for name, item in tuple(result.items()):
            if isinstance(item, Mapping) and _comparison_bundle_participant(item):
                result[name] = unavailable_monthly_evidence(f"{name}_alternative_source_mismatch")
        errors.append("monthly_comparison_bundle_invalid")
    basket = result["basket"]
    if isinstance(basket, Mapping) and basket.get("status") == "available":
        comparators_available = all(
            isinstance(result.get(name), Mapping) and result[name].get("status") == "available"  # type: ignore[index]
            for name in ("benchmark", "cash", "no_action")
        )
        if not comparators_available or not _relative_returns_reconcile(basket, result):
            result["basket"] = unavailable_monthly_evidence("basket_relative_return_mismatch")
            errors.append("basket_relative_invalid")
    return _json_copy(result), errors


def _normalise_alternative(name: str, value: object, *, cutoff: datetime | None) -> tuple[dict[str, object], list[str]]:
    if value is None:
        return unavailable_monthly_evidence(f"{name}_alternative_unavailable"), [f"{name}_alternative_unavailable"]
    if not isinstance(value, Mapping):
        return unavailable_monthly_evidence(f"{name}_alternative_malformed"), [f"{name}_alternative_malformed"]
    if not _safe_execution_disabled(value):
        return unavailable_monthly_evidence(f"{name}_alternative_authority_invalid"), [f"{name}_alternative_authority_invalid"]
    try:
        item = _json_copy(value)
    except (TypeError, ValueError):
        return unavailable_monthly_evidence(f"{name}_alternative_malformed"), [f"{name}_alternative_malformed"]
    status = item.get("status")
    if status not in _STATUSES:
        return unavailable_monthly_evidence(f"{name}_alternative_status_invalid"), [f"{name}_alternative_invalid"]
    if _non_available_mapping_contains_financial_return(item):
        return unavailable_monthly_evidence(f"{name}_alternative_evidence_invalid"), [
            f"{name}_alternative_invalid",
            f"{name}_financial_invalid",
        ]
    if status != "available":
        if not _text(item.get("reason")):
            return unavailable_monthly_evidence(f"{name}_alternative_reason_unavailable"), [f"{name}_alternative_invalid"]
        nested_errors = _evidence_contract_errors(item, cutoff=cutoff)
        nested_errors.extend(_partial_alternative_errors(name, item))
        if nested_errors:
            return unavailable_monthly_evidence(f"{name}_alternative_evidence_invalid"), [
                f"{name}_alternative_invalid",
                *(f"{name}_{error}" for error in nested_errors),
            ]
        item["execution_allowed"] = False
        return item, [f"{name}_alternative_unavailable"]
    contract_errors = _evidence_contract_errors(item, cutoff=cutoff)
    if contract_errors:
        return unavailable_monthly_evidence(f"{name}_alternative_evidence_invalid"), [
            f"{name}_alternative_invalid",
            *(f"{name}_{error}" for error in contract_errors),
        ]
    horizon = _finite(item.get("horizon_days"))
    if (
        any(not _text(item.get(field)) for field in ("version", "source_id", "source_dataset"))
        or not _sha256(item.get("source_digest"))
        or _timestamp(item.get("as_of")) is None
        or _timestamp(item.get("known_at")) is None
        or horizon is None
        or horizon <= 0
        or _finite(item.get("period_return")) is None
    ):
        return unavailable_monthly_evidence(f"{name}_alternative_evidence_invalid"), [f"{name}_alternative_invalid"]
    if _finite(item.get("period_return")) < -1:
        return unavailable_monthly_evidence(f"{name}_alternative_financial_invalid"), [f"{name}_financial_invalid", f"{name}_alternative_invalid"]
    if name == "basket" and (
        _finite(item.get("benchmark_relative_return")) is None
        or _finite(item.get("cash_relative_return")) is None
        or _finite(item.get("no_action_relative_return")) is None
    ):
        return unavailable_monthly_evidence("basket_relative_return_invalid"), ["basket_alternative_invalid"]
    if name in {"benchmark", "cash", "no_action"} and any(
        not _text(item.get(field))
        for field in ("reference_id", "reference_version", "reference_content_hash")
    ):
        return unavailable_monthly_evidence(f"{name}_reference_identity_unavailable"), [f"{name}_alternative_invalid"]
    if name == "no_action" and item.get("reference_method") != "no_trade":
        return unavailable_monthly_evidence("no_action_reference_method_invalid"), ["no_action_alternative_invalid"]
    item["execution_allowed"] = False
    return item, []


def _normalise_section(
    name: str,
    value: Mapping[str, object] | None,
    validator,
    *,
    cutoff: datetime | None,
) -> tuple[dict[str, object], list[str]]:
    if value is None:
        return unavailable_monthly_evidence(f"{name}_unavailable"), [f"{name}_unavailable"]
    if not isinstance(value, Mapping):
        return unavailable_monthly_evidence(f"{name}_malformed"), [f"{name}_malformed"]
    if not _safe_execution_disabled(value):
        return unavailable_monthly_evidence(f"{name}_authority_invalid"), [f"{name}_authority_invalid"]
    try:
        item = _json_copy(value)
    except (TypeError, ValueError):
        return unavailable_monthly_evidence(f"{name}_malformed"), [f"{name}_malformed"]
    status = item.get("status")
    if status not in _STATUSES:
        return unavailable_monthly_evidence(f"{name}_status_invalid"), [f"{name}_invalid"]
    if _non_available_mapping_contains_financial_return(item):
        return unavailable_monthly_evidence(f"{name}_evidence_invalid"), [
            f"{name}_invalid",
            f"{name}_financial_invalid",
        ]
    errors = _evidence_contract_errors(item, cutoff=cutoff)
    if status in {"unavailable", "pending"}:
        if not _text(item.get("reason")):
            return unavailable_monthly_evidence(f"{name}_reason_unavailable"), [f"{name}_invalid"]
        if errors:
            return unavailable_monthly_evidence(f"{name}_evidence_invalid"), [
                f"{name}_invalid",
                *(f"{name}_{error}" for error in errors),
            ]
        item["execution_allowed"] = False
        return item, [f"{name}_unavailable"]
    errors.extend(validator(item, status == "available"))
    if errors:
        return unavailable_monthly_evidence(f"{name}_evidence_invalid"), [
            f"{name}_invalid",
            *(f"{name}_{error}" for error in errors),
        ]
    item["execution_allowed"] = False
    return item, ([] if status == "available" else [f"{name}_partial"])


def _validate_expected_returns(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete:
        errors.extend(_distribution_errors(value))
    else:
        if any(field in value for field in ("gross", "net", "version", "source_dataset")):
            errors.extend(_distribution_errors(value))
        components = value.get("components")
        if components is not None:
            if not _sequence(components):
                errors.append("components")
            else:
                for component in components:
                    if not isinstance(component, Mapping) or not _text(component.get("instrument_id")):
                        errors.append("component")
                    elif component.get("status") == "available":
                        errors.extend(_distribution_errors(component))
                    elif component.get("status") not in {"partial", "unavailable"}:
                        errors.append("component_status")
    return errors


def _distribution_errors(value: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if any(not _text(value.get(field)) for field in ("version", "source_id", "source_dataset")):
        errors.append("identity")
    if not _sha256(value.get("source_digest")):
        errors.append("source_digest")
    if _timestamp(value.get("as_of")) is None or _timestamp(value.get("known_at")) is None:
        errors.append("chronology")
    horizon = _finite(value.get("horizon_days"))
    if horizon is None or horizon <= 0:
        errors.append("horizon")
    for name in ("gross", "net"):
        quantiles = value.get(name)
        if not isinstance(quantiles, Mapping):
            errors.append(name)
            continue
        values = [_finite(quantiles.get(key)) for key in ("q10", "q50", "q90")]
        if any(item is None for item in values) or values != sorted(values):
            errors.append(name)
        elif any(item < -1 for item in values if item is not None):
            errors.append("financial_invalid")
    return errors


def _validate_optimiser(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("model_version", "method", "source_id")):
        errors.append("identity")
    constraints = value.get("constraints")
    solution = value.get("solution")
    if complete and not isinstance(constraints, Mapping):
        errors.append("constraints")
    if complete and not isinstance(solution, Mapping):
        errors.append("solution")
    if "constraints" in value and not isinstance(constraints, Mapping):
        errors.append("constraints")
    if isinstance(constraints, Mapping) and (
        constraints.get("status") not in _STATUSES
        or not isinstance(constraints.get("values", constraints.get("rows")), (Mapping, list))
    ):
        errors.append("constraints")
    if isinstance(constraints, Mapping):
        constraint_values = constraints.get("values")
        if isinstance(constraint_values, Mapping):
            for key in ("max_weight", "turnover_limit"):
                number = _finite(constraint_values.get(key))
                if key in constraint_values and (number is None or not 0 <= number <= 1):
                    errors.append("financial_invalid")
    if "solution" in value and not isinstance(solution, Mapping):
        errors.append("solution")
    if isinstance(solution, Mapping):
        if solution.get("status") not in {"success", "fallback", "available", "partial", "unavailable"}:
            errors.append("solution_status")
        if solution.get("status") not in {"partial", "unavailable"} and not isinstance(solution.get("feasible"), bool):
            errors.append("feasible")
        diagnostics = solution.get("diagnostics")
        if complete and not isinstance(diagnostics, Mapping):
            errors.append("diagnostics")
        if isinstance(diagnostics, Mapping) and diagnostics.get("status", "available") == "available":
            if not _sequence(diagnostics.get("binding_constraints"), allow_empty=True):
                errors.append("binding_constraints")
        weights = solution.get("weights")
        if isinstance(weights, Mapping):
            for weight in weights.values():
                number = _finite(weight)
                if number is None or not 0 <= number <= 1:
                    errors.append("financial_invalid")
    return errors


def _validate_costs(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("model_id", "source_id")):
        errors.append("identity")
    components = value.get("components")
    total = value.get("total")
    capacity = value.get("capacity")
    if complete and not _sequence(components):
        errors.append("components")
    if "components" in value and not _sequence(components, allow_empty=True):
        errors.append("components")
    if _sequence(components, allow_empty=True):
        for component in components:
            if not isinstance(component, Mapping) or not _text(component.get("estimate_id", component.get("instrument_id"))):
                errors.append("component")
            elif _finite(component.get("cost_eur", component.get("estimated_cost_eur"))) is None:
                errors.append("component_cost")
            else:
                for field in (
                    "order_value_eur",
                    "cost_eur",
                    "estimated_cost_eur",
                    "cost_bps",
                    "estimated_cost_bps",
                    "commission_eur",
                    "spread_bps",
                    "slippage_bps",
                    "market_impact_bps",
                ):
                    if field in component:
                        number = _finite(component.get(field))
                        if number is None or number < 0:
                            errors.append("financial_invalid")
    if complete and not isinstance(total, Mapping):
        errors.append("total")
    if "total" in value and not isinstance(total, Mapping):
        errors.append("total")
    if isinstance(total, Mapping) and any(_finite(total.get(field)) is None for field in ("order_value_eur", "cost_eur", "cost_bps")):
        errors.append("total")
    if isinstance(total, Mapping) and any(
        _finite(total.get(field)) is not None and _finite(total.get(field)) < 0
        for field in ("order_value_eur", "cost_eur", "cost_bps")
    ):
        errors.append("financial_invalid")
    if complete and not isinstance(capacity, Mapping):
        errors.append("capacity")
    if "capacity" in value and not isinstance(capacity, Mapping):
        errors.append("capacity")
    if isinstance(capacity, Mapping):
        if capacity.get("status") not in _STATUSES:
            errors.append("capacity_status")
        if capacity.get("status") == "available" and _finite(capacity.get("amount_eur")) is None:
            errors.append("capacity")
        if _finite(capacity.get("amount_eur")) is not None and _finite(capacity.get("amount_eur")) < 0:
            errors.append("financial_invalid")
    if complete and not _sequence(value.get("assumptions"), allow_empty=True):
        errors.append("assumptions")
    return errors


def _validate_events(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("version", "source_id")):
        errors.append("identity")
    replay = value.get("replay")
    next_session = value.get("next_session")
    if "replay" in value and not isinstance(replay, Mapping):
        errors.append("replay")
    if "next_session" in value and not isinstance(next_session, Mapping):
        errors.append("next_session")
    if complete and not isinstance(replay, Mapping):
        errors.append("replay")
    if complete and not isinstance(next_session, Mapping):
        errors.append("next_session")
    if isinstance(next_session, Mapping) and next_session.get("status") == "available":
        if _finite(next_session.get("execution_delay_sessions")) != 1 or next_session.get("same_bar_execution_avoided") is not True:
            errors.append("next_session")
    elif complete:
        errors.append("next_session")
    return errors


def _validate_forward_evidence(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("version", "source_id")):
        errors.append("identity")
    if "snapshot" in value and not isinstance(value.get("snapshot"), Mapping):
        errors.append("snapshot")
    if complete and not isinstance(value.get("snapshot"), Mapping):
        errors.append("snapshot")
    outcomes = value.get("outcomes")
    if "outcomes" in value and not _sequence(outcomes, allow_empty=True):
        errors.append("outcomes")
    if complete and not _sequence(outcomes, allow_empty=True):
        errors.append("outcomes")
    if _sequence(outcomes, allow_empty=True):
        for outcome in outcomes:
            if not isinstance(outcome, Mapping):
                errors.append("outcome")
                continue
            if outcome.get("status") == "available":
                if _finite(outcome.get("horizon_days")) is None or _finite(outcome.get("net_return")) is None:
                    errors.append("outcome")
            elif outcome.get("status") not in {"matured", "pending", "partial", "unavailable"}:
                errors.append("outcome_status")
    return errors


def _validate_paper_outcomes(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("version", "source_id", "account_id", "ledger_hash")):
        errors.append("identity")
    if complete and not _text(value.get("reconciliation_status")):
        errors.append("reconciliation")
    if complete and _finite(value.get("matured_outcomes")) is None:
        errors.append("matured_outcomes")
    if _finite(value.get("matured_outcomes")) is not None and _finite(value.get("matured_outcomes")) < 0:
        errors.append("financial_invalid")
    outcomes = value.get("outcomes")
    if "outcomes" in value and not _sequence(outcomes, allow_empty=True):
        errors.append("outcomes")
    if complete and not _sequence(outcomes, allow_empty=True):
        errors.append("outcomes")
    if _sequence(outcomes, allow_empty=True):
        for outcome in outcomes:
            if not isinstance(outcome, Mapping):
                errors.append("outcome")
    return errors


def _validate_concentration(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    for dimension in ("sector", "theme"):
        item = value.get(dimension)
        if not isinstance(item, Mapping):
            if complete:
                errors.append(dimension)
            continue
        status = item.get("status")
        if status not in _STATUSES:
            errors.append(dimension)
        if status == "available":
            weight = _finite(item.get("max_weight"))
            exposures = item.get("exposures")
            if weight is not None and not 0 <= weight <= 1:
                errors.append(dimension)
            elif weight is None:
                if not _sequence(exposures):
                    errors.append(dimension)
                else:
                    for exposure in exposures:
                        if (
                            not isinstance(exposure, Mapping)
                            or _finite(exposure.get("weight")) is None
                            or not 0 <= _finite(exposure.get("weight")) <= 1
                        ):
                            errors.append(dimension)
        elif complete:
            errors.append(dimension)
    return errors


def _validate_assumptions(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("version", "source_id")):
        errors.append("identity")
    values = value.get("values")
    if "values" in value and not isinstance(values, Mapping):
        errors.append("values")
    if complete and not isinstance(values, Mapping):
        errors.append("values")
    if isinstance(values, Mapping) and (
        values.get("rebalance_cadence") != MONTHLY_REBALANCE_CADENCE
        or values.get("execution_assumption") != NEXT_SESSION_EXECUTION_ASSUMPTION
    ):
        errors.append("values")
    return errors


def _evidence_contract_errors(value: Mapping[str, object], *, cutoff: datetime | None = None) -> list[str]:
    errors = _evidence_contract_errors_one(value, cutoff=cutoff, required=value.get("status") == "available")
    for nested in _nested_mappings(value):
        errors.extend(_evidence_contract_errors_one(nested, cutoff=cutoff, required=nested.get("status") == "available"))
    return list(dict.fromkeys(errors))


def _evidence_contract_errors_one(
    value: Mapping[str, object], *, cutoff: datetime | None = None, required: bool = False
) -> list[str]:
    """Reject explicit chronology, trust and source-binding contradictions."""

    errors: list[str] = []
    if required:
        has_version = any(_text(value.get(field)) for field in ("version", "model_version", "model_id"))
        has_source_id = _text(value.get("source_id"))
        has_source_dataset = _text(value.get("source_dataset"))
        has_reference_identity = all(
            _text(value.get(field))
            for field in ("reference_id", "reference_version", "reference_content_hash")
        )
        if not ((has_version and has_source_id and has_source_dataset) or has_reference_identity):
            errors.append("identity")
        if not _sha256(value.get("source_digest")):
            errors.append("source_digest")
        if _timestamp(value.get("as_of")) is None or _timestamp(value.get("known_at")) is None:
            errors.append("chronology")
        if value.get("trust") is not True:
            errors.append("untrusted")
        if value.get("source_bound") is not True:
            errors.append("unbound")
    timestamps: dict[str, datetime] = {}
    for key in (
        "as_of",
        "known_at",
        "decision_time",
        "knowledge_cutoff",
        "decision",
        "knowledge_at",
        "effective_at",
    ):
        if key not in value or value.get(key) in (None, ""):
            continue
        parsed = _timestamp(value.get(key))
        if parsed is None:
            errors.append("temporal_invalid")
        else:
            timestamps[key] = parsed
    if timestamps.get("known_at") is not None:
        if timestamps.get("as_of") is not None and timestamps["known_at"] < timestamps["as_of"]:
            errors.append("temporal_invalid")
        local_cutoffs = (
            timestamps[key]
            for key in ("decision_time", "knowledge_cutoff", "decision", "knowledge_at")
            if key in timestamps
        )
        if any(timestamps["known_at"] > local_cutoff for local_cutoff in local_cutoffs):
            errors.append("future_known")
        if cutoff is not None and timestamps["known_at"] > cutoff:
            errors.append("future_known")
    if timestamps.get("effective_at") is not None and timestamps.get("as_of") is not None:
        if timestamps["effective_at"] > timestamps["as_of"]:
            errors.append("future_known")
    if cutoff is not None and timestamps.get("as_of") is not None and timestamps["as_of"] > cutoff:
        errors.append("future_known")

    if value.get("stale") is True or str(value.get("status", "")).casefold() == "stale":
        errors.append("stale")
    if value.get("trusted") is False:
        errors.append("untrusted")
    for key in ("trust", "trust_status", "source_trust", "provenance_status", "source_status", "data_quality"):
        marker = str(value.get(key, "")).strip().casefold()
        if marker in {"untrusted", "rejected", "invalid", "stale", "future", "future_known"}:
            errors.append("untrusted" if marker == "untrusted" else marker)

    if value.get("bound") is False or value.get("source_bound") is False:
        errors.append("unbound")
    source_binding = value.get("source_binding")
    if source_binding is not None:
        if not isinstance(source_binding, Mapping) or source_binding.get("status") not in {None, "available"}:
            errors.append("unbound")
        elif isinstance(source_binding, Mapping):
            for field in ("source_id", "source_dataset"):
                if field in source_binding and source_binding.get(field) != value.get(field):
                    errors.append("unbound")
    return list(dict.fromkeys(errors))


def _nested_mappings(value: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    nested: list[Mapping[str, object]] = []
    pending: list[object] = list(value.values())
    while pending:
        item = pending.pop()
        if isinstance(item, Mapping):
            nested.append(item)
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return tuple(nested)


def _contains_financial_return_key(value: Mapping[str, object]) -> bool:
    return any(
        isinstance(field, str)
        and (field.casefold() in {"return", "relative_return", "net_return"} or field.casefold().endswith("_return"))
        for item in (value, *_nested_mappings(value))
        for field in item
    )


def _non_available_mapping_contains_financial_return(value: Mapping[str, object]) -> bool:
    return any(
        item.get("status") in {"partial", "pending", "unavailable"}
        and _contains_financial_return_key(item)
        for item in (value, *_nested_mappings(value))
    )


def _reference_cutoff(reference: Mapping[str, object]) -> datetime | None:
    analysis = reference.get("analysis")
    if not isinstance(analysis, Mapping):
        return None
    cutoffs: list[datetime] = []
    for field in ("decision_time", "knowledge_cutoff", "decision", "knowledge_at", "end_date"):
        raw = analysis.get(field)
        if raw in (None, ""):
            continue
        parsed = _timestamp(raw)
        if parsed is None:
            return None
        cutoffs.append(parsed)
    return min(cutoffs) if cutoffs else None


def _reference_identity(value: object) -> tuple[object, object, object] | None:
    if not isinstance(value, Mapping):
        return None
    return value.get("id"), value.get("version"), value.get("content_hash")


def _sha256(value: object) -> str:
    text = _text(value).casefold()
    return text if len(text) == 64 and all(character in "0123456789abcdef" for character in text) else ""


def _alternative_window(value: Mapping[str, object]) -> tuple[datetime, datetime, float]:
    as_of = _timestamp(value.get("as_of"))
    known_at = _timestamp(value.get("known_at"))
    horizon = _finite(value.get("horizon_days"))
    if as_of is None or known_at is None or horizon is None:
        return (datetime.min.replace(tzinfo=timezone.utc), datetime.min.replace(tzinfo=timezone.utc), -1.0)
    return as_of, known_at, horizon


def _alternative_bundle(value: Mapping[str, object]) -> tuple[object, ...]:
    return (
        value.get("version"),
        value.get("source_dataset"),
        value.get("source_digest"),
        *_alternative_window(value),
    )


def _comparison_bundle_participant(value: Mapping[str, object]) -> bool:
    return value.get("status") == "available"


def _partial_alternative_errors(name: str, value: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if _contains_financial_return_key(value):
        errors.append("financial_invalid")
    identity_fields = ("version", "source_id", "source_dataset")
    if any(field in value and not _text(value.get(field)) for field in identity_fields):
        errors.append("identity_invalid")
    if "period_return" in value:
        period_return = _finite(value.get("period_return"))
        if period_return is None or period_return < -1:
            errors.append("financial_invalid")
    if "horizon_days" in value:
        horizon = _finite(value.get("horizon_days"))
        if horizon is None or horizon <= 0:
            errors.append("horizon_invalid")
    if "source_digest" in value and not _sha256(value.get("source_digest")):
        errors.append("source_digest_invalid")
    for field in ("as_of", "known_at"):
        if field in value and _timestamp(value.get(field)) is None:
            errors.append("temporal_invalid")
    relative_fields = (
        "benchmark_relative_return",
        "cash_relative_return",
        "no_action_relative_return",
    )
    if name == "basket" and any(
        field in value and _finite(value.get(field)) is None for field in relative_fields
    ):
        errors.append("financial_invalid")
    reference_fields = ("reference_id", "reference_version", "reference_content_hash")
    if name in {"benchmark", "cash", "no_action"} and any(field in value for field in reference_fields):
        if any(not _text(value.get(field)) for field in reference_fields):
            errors.append("identity_invalid")
    if "trust" in value and value.get("trust") is not True:
        errors.append("untrusted")
    if "source_bound" in value and value.get("source_bound") is not True:
        errors.append("unbound")
    return list(dict.fromkeys(errors))


def _relative_returns_reconcile(basket: Mapping[str, object], alternatives: Mapping[str, object]) -> bool:
    basket_return = _finite(basket.get("period_return"))
    if basket_return is None:
        return False
    for name, field in (
        ("benchmark", "benchmark_relative_return"),
        ("cash", "cash_relative_return"),
        ("no_action", "no_action_relative_return"),
    ):
        comparison = alternatives.get(name)
        comparison_return = _finite(comparison.get("period_return")) if isinstance(comparison, Mapping) else None
        supplied = _finite(basket.get(field))
        if comparison_return is None or supplied is None or not math.isclose(
            supplied, basket_return - comparison_return, rel_tol=0.0, abs_tol=_RELATIVE_RETURN_TOLERANCE
        ):
            return False
    return True


def _horizon_mismatch_errors(
    alternatives: Mapping[str, object],
    sections: Mapping[str, Mapping[str, object]],
) -> list[str]:
    horizons: list[float] = []
    for value in alternatives.values():
        if isinstance(value, Mapping) and value.get("status") == "available":
            horizon = _finite(value.get("horizon_days"))
            if horizon is not None:
                horizons.append(horizon)
    expected = sections.get("expected_returns", {})
    if isinstance(expected, Mapping) and expected.get("status") == "available":
        horizon = _finite(expected.get("horizon_days"))
        if horizon is not None:
            horizons.append(horizon)
    forward = sections.get("forward_evidence", {})
    if isinstance(forward, Mapping) and forward.get("status") == "available":
        outcomes = forward.get("outcomes")
        if _sequence(outcomes, allow_empty=True):
            for outcome in outcomes:
                if isinstance(outcome, Mapping):
                    horizon = _finite(outcome.get("horizon_days"))
                    if horizon is not None:
                        horizons.append(horizon)
    return ["monthly_horizon_mismatch"] if horizons and len(set(horizons)) > 1 else []


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _evidence_warning(maturity: object, sample_size: object) -> str | None:
    sample = _finite(sample_size)
    if sample_size is not None and sample is None:
        return "Young/noisy live/paper warning: evidence sample size is malformed."
    label = str(maturity or "").casefold()
    if any(token in label for token in ("young", "noisy", "pending", "unknown", "unavailable")):
        return "Young/noisy live/paper warning: evidence maturity is limited or unresolved."
    if sample is not None and sample < 3:
        return "Young/noisy live/paper warning: fewer than three independent monthly observations are available."
    return None


def _available_identity(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("status") == "available"
        and all(_text(value.get(field)) for field in ("id", "version", "content_hash"))
    )


def _available_reference_identity(value: Mapping[str, object]) -> bool:
    status = value.get("status")
    return status in {None, "available"} and all(_text(value.get(field)) for field in ("id", "version", "content_hash"))


def _execution_disabled(value: object) -> bool:
    if isinstance(value, Mapping):
        return all(
            (key != "execution_allowed" or item is False) and _execution_disabled(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(_execution_disabled(item) for item in value)
    return True


def _safe_execution_disabled(value: object) -> bool:
    try:
        return _execution_disabled(value)
    except RecursionError:
        return False


def _json_copy(value: object) -> dict[str, object]:
    payload = json.dumps(_thaw_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise TypeError("monthly evidence must be a mapping")
    return result


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sequence(value: object, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and (allow_empty or len(value) > 0)
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return "" if text.casefold() in {"none", "nan", "unavailable"} else text


def _alternative_line(label: str, value: object) -> str:
    if not isinstance(value, Mapping):
        return f"{label}: unavailable"
    return (
        f"{label}: {value.get('status', 'unavailable')} | return={_format_percent(value.get('period_return'))} | "
        f"vs benchmark={_format_percent(value.get('benchmark_relative_return'))} | "
        f"vs cash={_format_percent(value.get('cash_relative_return'))} | "
        f"vs no-action={_format_percent(value.get('no_action_relative_return'))} | "
        f"version={value.get('version', 'unavailable')} | source={value.get('source_id', 'unavailable')}"
    )


def _distribution_line(value: object) -> str:
    if not isinstance(value, Mapping):
        return "Expected-return distributions: unavailable"
    components = value.get("components")
    component_count = len(components) if _sequence(components, allow_empty=True) else 0
    return (
        f"Expected-return distributions: {value.get('status', 'unavailable')} | "
        f"gross={_quantiles(value.get('gross'))} | net={_quantiles(value.get('net'))} | components={component_count} | "
        f"version={value.get('version', 'unavailable')} | source={value.get('source_dataset', 'unavailable')}"
    )


def _optimiser_line(value: object) -> str:
    if not isinstance(value, Mapping):
        return "Optimiser/constraints: unavailable"
    solution = value.get("solution")
    solution = solution if isinstance(solution, Mapping) else {}
    diagnostics = solution.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    binding = diagnostics.get("binding_constraints")
    binding_text = ",".join(str(item) for item in binding) if _sequence(binding) else "none/unavailable"
    return (
        f"Optimiser/constraints: {value.get('status', 'unavailable')} | feasible={solution.get('feasible', 'unavailable')} | "
        f"binding={binding_text} | model={value.get('model_version', 'unavailable')}"
    )


def _cost_line(value: object) -> str:
    if not isinstance(value, Mapping):
        return "Costs/capacity: unavailable"
    total = value.get("total")
    total = total if isinstance(total, Mapping) else {}
    capacity = value.get("capacity")
    capacity = capacity if isinstance(capacity, Mapping) else {}
    return (
        f"Costs/capacity: {value.get('status', 'unavailable')} | cost={_format_number(total.get('cost_eur'))} EUR / "
        f"{_format_number(total.get('cost_bps'))} bps | capacity={_format_number(capacity.get('amount_eur'))} EUR "
        f"({capacity.get('status', 'unavailable')}) | model={value.get('model_id', 'unavailable')}"
    )


def _concentration_line(value: object) -> str:
    if not isinstance(value, Mapping):
        return "Sector/theme concentration: unavailable"
    return (
        f"Sector/theme concentration: {value.get('status', 'unavailable')} | "
        f"sector={_dimension_status(value.get('sector'))} | theme={_dimension_status(value.get('theme'))}"
    )


def _dimension_status(value: object) -> str:
    if not isinstance(value, Mapping):
        return "unavailable"
    exposures = value.get("exposures")
    count = len(exposures) if _sequence(exposures, allow_empty=True) else 0
    return f"{value.get('status', 'unavailable')} max={_format_percent(value.get('max_weight'))} rows={count}"


def _quantiles(value: object) -> str:
    if not isinstance(value, Mapping):
        return "unavailable"
    return "/".join(_format_percent(value.get(name)) for name in ("q10", "q50", "q90"))


def _format_percent(value: object) -> str:
    number = _finite(value)
    return "unavailable" if number is None else f"{number:+.2%}"


def _format_number(value: object) -> str:
    number = _finite(value)
    return "unavailable" if number is None else f"{number:,.2f}"


__all__ = [
    "ALTERNATIVE_NAMES",
    "MONTHLY_DECISION_TEMPLATE_SCHEMA",
    "MONTHLY_REBALANCE_CADENCE",
    "NEXT_SESSION_EXECUTION_ASSUMPTION",
    "MonthlyDecisionTemplate",
    "build_monthly_decision_template",
    "monthly_decision_template_lines",
    "unavailable_monthly_evidence",
]
