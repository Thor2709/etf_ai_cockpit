"""Canonical validation and cost reconciliation for forecast distributions."""

from collections.abc import Mapping, Sequence
import math
from numbers import Real


QUANTILE_LEVELS = (5, 10, 25, 50, 75, 90, 95)
QUANTILE_FIELDS = tuple(f"q{level:02d}_return" for level in QUANTILE_LEVELS)
RETURN_COMPONENT_FIELDS = ("price_return", "income_return", "fx_return")
COST_DEDUCTION_FIELDS = ("fee", "spread", "impact", "fx")
RETURN_DISTRIBUTION_VERSION = "expected-return-distribution.v1"
HORIZON_VALIDATION_STATUSES = frozenset({"good", "mixed", "weak", "limited"})


def normalise_quantiles(values: Mapping[str, object] | None) -> dict[str, float] | None:
    """Return a complete, finite, monotone quantile vector or ``None``."""

    if not isinstance(values, Mapping):
        return None
    result: dict[str, float] = {}
    for field in QUANTILE_FIELDS:
        value = _finite(values.get(field))
        if value is None:
            return None
        result[field] = value
    quantile_values = tuple(result.values())
    if any(left > right for left, right in zip(quantile_values, quantile_values[1:])):
        return None
    return result


def widen_for_coverage(
    quantiles: Mapping[str, object] | None,
    coverage_ratio: object,
) -> dict[str, float] | None:
    """Widen valid quantiles as observed coverage falls; unknown coverage is unavailable."""

    normalised = normalise_quantiles(quantiles)
    coverage = _finite(coverage_ratio)
    if normalised is None or coverage is None or not 0 < coverage <= 1:
        return None
    if coverage == 1:
        return normalised
    median = normalised["q50_return"]
    scale = 1.0 / math.sqrt(coverage)
    widened = {
        field: median + (value - median) * scale
        for field, value in normalised.items()
    }
    return normalise_quantiles(widened)


def net_return_distribution(
    gross_quantiles: Mapping[str, object] | None,
    cost_deductions: Mapping[str, object] | None,
) -> dict[str, float] | None:
    """Subtract a complete explicit cost decomposition from each gross quantile.

    Costs are decimal return deductions. A missing cost component does not mean
    that the cost is zero.
    """

    gross = normalise_quantiles(gross_quantiles)
    if gross is None or not isinstance(cost_deductions, Mapping):
        return None
    deductions: list[float] = []
    for field in COST_DEDUCTION_FIELDS:
        value = _finite(cost_deductions.get(field))
        if value is None or value < 0:
            return None
        deductions.append(value)
    total_deduction = math.fsum(deductions)
    net = {field: value - total_deduction for field, value in gross.items()}
    return normalise_quantiles(net)


def build_distribution_record(
    quantiles: Mapping[str, object] | None,
    *,
    horizon_days: object,
    coverage_ratio: object,
    return_components: Mapping[str, object] | None,
    calibration_status: object = None,
    calibration_horizon_days: object = None,
    probability_positive_return: object = None,
    probability_beat_cash: object = None,
    probability_beat_benchmark: object = None,
    cost_deductions: Mapping[str, object] | None = None,
    per_model_distributions: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build the contract record without filling missing return or cost inputs.

    The optional model records retain each input distribution for downstream
    disagreement and clone-breadth analysis; the aggregate quantiles remain
    the existing median contract.
    """

    horizon = _positive_integer(horizon_days)
    widened = widen_for_coverage(quantiles, coverage_ratio)
    components = _normalise_components(return_components)
    reason = None
    if horizon is None:
        reason = "Unsupported or invalid forecast horizon."
    elif widened is None:
        reason = "Complete quantiles and valid coverage are required."
    elif components is None:
        reason = "Price, income and FX return components are unavailable."

    probabilities: dict[str, float | None] = {
        "probability_loss": None,
        "probability_beat_cash": None,
        "probability_beat_benchmark": None,
    }
    calibration_horizon = _positive_integer(calibration_horizon_days)
    if calibration_status == "good" and horizon is not None and calibration_horizon == horizon:
        positive = _probability(probability_positive_return)
        probabilities = {
            "probability_loss": None if positive is None else 1.0 - positive,
            "probability_beat_cash": _probability(probability_beat_cash),
            "probability_beat_benchmark": _probability(probability_beat_benchmark),
        }

    net = net_return_distribution(widened, cost_deductions) if widened is not None else None
    return {
        "schema_version": RETURN_DISTRIBUTION_VERSION,
        "status": "available" if reason is None else "unavailable",
        "reason": reason,
        "horizon_days": horizon,
        "coverage_ratio": _finite(coverage_ratio),
        "gross_status": "available" if widened is not None else "unavailable",
        "gross_quantiles": widened,
        "components_status": "available" if components is not None else "unavailable",
        "return_components": components,
        "cost_deductions": _normalise_costs(cost_deductions),
        "net_status": "available" if net is not None else "unavailable",
        "net_reason": None if net is not None else "A complete explicit cost deduction breakdown is required.",
        "net_quantiles": net,
        "probabilities": probabilities,
        "per_model_distributions": (
            [dict(record) for record in per_model_distributions]
            if isinstance(per_model_distributions, Sequence)
            else None
        ),
        "execution_allowed": False,
    }


def _normalise_components(values: Mapping[str, object] | None) -> dict[str, float] | None:
    if not isinstance(values, Mapping):
        return None
    result = {field: _finite(values.get(field)) for field in RETURN_COMPONENT_FIELDS}
    if any(value is None for value in result.values()):
        return None
    return {field: float(value) for field, value in result.items() if value is not None}


def _normalise_costs(values: Mapping[str, object] | None) -> dict[str, float] | None:
    if not isinstance(values, Mapping):
        return None
    result = {field: _finite(values.get(field)) for field in COST_DEDUCTION_FIELDS}
    if any(value is None or value < 0 for value in result.values()):
        return None
    return {field: float(value) for field, value in result.items() if value is not None}


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        return None
    integer = int(value)
    return integer if integer > 0 and integer == value else None


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        return None
    return float(value)


def _probability(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and 0 <= number <= 1 else None


__all__ = [
    "COST_DEDUCTION_FIELDS",
    "HORIZON_VALIDATION_STATUSES",
    "QUANTILE_FIELDS",
    "QUANTILE_LEVELS",
    "RETURN_COMPONENT_FIELDS",
    "RETURN_DISTRIBUTION_VERSION",
    "build_distribution_record",
    "net_return_distribution",
    "normalise_quantiles",
    "widen_for_coverage",
]
