"""Deterministic, non-executable monthly decision evidence projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
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
    for name in SECTION_NAMES:
        section, errors = _normalise_section(name, supplied[name], validators[name])
        sections[name] = section
        blockers.extend(errors)

    evidence_warning = _evidence_warning(evidence_maturity, sample_size)
    if evidence_warning:
        warnings.append(evidence_warning)
    for dimension in ("sector", "theme"):
        value = sections["concentration"].get(dimension)
        if not isinstance(value, Mapping) or value.get("status") != "available":
            warnings.append(f"{dimension.title()} concentration evidence is unavailable or partial.")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    malformed = any(item.endswith(("_malformed", "_invalid", "_authority_invalid")) for item in blockers)
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
    return result, None


def _normalise_alternatives(
    value: Mapping[str, object] | None,
    reference: Mapping[str, object],
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
        item, item_errors = _normalise_alternative(name, raw)
        result[name] = item
        errors.extend(item_errors)
    if reference.get("status") == "available":
        benchmark = reference.get("benchmark")
        cash = reference.get("cash")
        references = reference.get("references")
        no_action = next(
            (item for item in references if isinstance(item, Mapping) and item.get("method") == "no_trade"),
            None,
        ) if _sequence(references) else None
        expected_ids = {
            "benchmark": benchmark.get("id") if isinstance(benchmark, Mapping) else None,
            "cash": cash.get("id") if isinstance(cash, Mapping) else None,
            "no_action": no_action.get("id") if isinstance(no_action, Mapping) else None,
        }
        for name, expected_id in expected_ids.items():
            item = result[name]
            if isinstance(item, Mapping) and item.get("status") == "available" and item.get("reference_id") != expected_id:
                result[name] = unavailable_monthly_evidence(f"{name}_reference_identity_mismatch")
                errors.append(f"{name}_alternative_invalid")
    return _json_copy(result), errors


def _normalise_alternative(name: str, value: object) -> tuple[dict[str, object], list[str]]:
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
    if status != "available":
        if not _text(item.get("reason")):
            return unavailable_monthly_evidence(f"{name}_alternative_reason_unavailable"), [f"{name}_alternative_invalid"]
        item["execution_allowed"] = False
        return item, [f"{name}_alternative_unavailable"]
    if any(not _text(item.get(field)) for field in ("version", "source_id", "source_dataset")) or _finite(item.get("period_return")) is None:
        return unavailable_monthly_evidence(f"{name}_alternative_evidence_invalid"), [f"{name}_alternative_invalid"]
    if name == "basket" and (
        _finite(item.get("benchmark_relative_return")) is None
        or _finite(item.get("cash_relative_return")) is None
    ):
        return unavailable_monthly_evidence("basket_relative_return_invalid"), ["basket_alternative_invalid"]
    if name in {"benchmark", "cash", "no_action"} and not _text(item.get("reference_id")):
        return unavailable_monthly_evidence(f"{name}_reference_identity_unavailable"), [f"{name}_alternative_invalid"]
    if name == "no_action" and item.get("reference_method") != "no_trade":
        return unavailable_monthly_evidence("no_action_reference_method_invalid"), ["no_action_alternative_invalid"]
    item["execution_allowed"] = False
    return item, []


def _normalise_section(name: str, value: Mapping[str, object] | None, validator) -> tuple[dict[str, object], list[str]]:
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
    if status in {"unavailable", "pending"}:
        if not _text(item.get("reason")):
            return unavailable_monthly_evidence(f"{name}_reason_unavailable"), [f"{name}_invalid"]
        item["execution_allowed"] = False
        return item, [f"{name}_unavailable"]
    if validator(item, status == "available"):
        return unavailable_monthly_evidence(f"{name}_evidence_invalid"), [f"{name}_invalid"]
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
    if isinstance(constraints, Mapping) and (
        constraints.get("status") not in _STATUSES
        or not isinstance(constraints.get("values", constraints.get("rows")), (Mapping, list))
    ):
        errors.append("constraints")
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
    if _sequence(components):
        for component in components:
            if not isinstance(component, Mapping) or not _text(component.get("estimate_id", component.get("instrument_id"))):
                errors.append("component")
            elif _finite(component.get("cost_eur", component.get("estimated_cost_eur"))) is None:
                errors.append("component_cost")
    if complete and not isinstance(total, Mapping):
        errors.append("total")
    if isinstance(total, Mapping) and any(_finite(total.get(field)) is None for field in ("order_value_eur", "cost_eur", "cost_bps")):
        errors.append("total")
    if complete and not isinstance(capacity, Mapping):
        errors.append("capacity")
    if isinstance(capacity, Mapping):
        if capacity.get("status") not in _STATUSES:
            errors.append("capacity_status")
        if capacity.get("status") == "available" and _finite(capacity.get("amount_eur")) is None:
            errors.append("capacity")
    if complete and not _sequence(value.get("assumptions"), allow_empty=True):
        errors.append("assumptions")
    return errors


def _validate_events(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("version", "source_id")):
        errors.append("identity")
    replay = value.get("replay")
    next_session = value.get("next_session")
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
    if complete and not isinstance(value.get("snapshot"), Mapping):
        errors.append("snapshot")
    if complete and not _sequence(value.get("outcomes"), allow_empty=True):
        errors.append("outcomes")
    return errors


def _validate_paper_outcomes(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("version", "source_id", "account_id", "ledger_hash")):
        errors.append("identity")
    if complete and not _text(value.get("reconciliation_status")):
        errors.append("reconciliation")
    if complete and _finite(value.get("matured_outcomes")) is None:
        errors.append("matured_outcomes")
    if complete and not _sequence(value.get("outcomes"), allow_empty=True):
        errors.append("outcomes")
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
                        if not isinstance(exposure, Mapping) or _finite(exposure.get("weight")) is None:
                            errors.append(dimension)
        elif complete:
            errors.append(dimension)
    return errors


def _validate_assumptions(value: Mapping[str, object], complete: bool) -> list[str]:
    errors: list[str] = []
    if complete and any(not _text(value.get(field)) for field in ("version", "source_id")):
        errors.append("identity")
    values = value.get("values")
    if complete and not isinstance(values, Mapping):
        errors.append("values")
    if isinstance(values, Mapping) and (
        values.get("rebalance_cadence") != MONTHLY_REBALANCE_CADENCE
        or values.get("execution_assumption") != NEXT_SESSION_EXECUTION_ASSUMPTION
    ):
        errors.append("values")
    return errors


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
    return all(_text(value.get(field)) for field in ("id", "version", "content_hash"))


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
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise TypeError("monthly evidence must be a mapping")
    return result


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
    text = str(value or "").strip()
    return "" if text.casefold() in {"none", "nan", "unavailable"} else text


def _alternative_line(label: str, value: object) -> str:
    if not isinstance(value, Mapping):
        return f"{label}: unavailable"
    return (
        f"{label}: {value.get('status', 'unavailable')} | return={_format_percent(value.get('period_return'))} | "
        f"vs benchmark={_format_percent(value.get('benchmark_relative_return'))} | "
        f"vs cash={_format_percent(value.get('cash_relative_return'))} | "
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
