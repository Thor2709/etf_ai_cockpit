"""Return uncertainty decomposition and replayable forecast scenarios.

Uncertainty components are expressed in decimal-return units. Aleatoric
uncertainty is the q90-q10 interval width, epistemic uncertainty is the
population standard deviation of independent model medians, and the
data-quality term scales the aleatoric width by the larger of missing
coverage and forecast age as a fraction of its configured maximum. The
total combines the three orthogonal components by root-sum-square.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import math
import random
import statistics
from typing import Any


def decompose_forecast_uncertainty(
    distribution: Mapping[str, object] | None,
    settings: object | None,
    *,
    base_confidence: object = None,
) -> dict[str, object]:
    """Return uncertainty components and model breadth, failing closed on gaps."""

    if settings is None:
        return unavailable_decomposition("forecast_uncertainty configuration is missing.")
    values = _settings(settings)
    required = {
        "high_disagreement_threshold",
        "confidence_haircut",
        "minimum_confidence",
        "maximum_forecast_age_days",
        "clone_return_tolerance",
    }
    if values is None or not required.issubset(values):
        return unavailable_decomposition("forecast_uncertainty configuration is incomplete.")
    if not isinstance(distribution, Mapping):
        return unavailable_decomposition("A return distribution is unavailable.")

    models = _model_records(distribution.get("per_model_distributions"))
    if not models:
        return unavailable_decomposition("Per-model return distributions are unavailable.")

    tolerance = _finite(values.get("clone_return_tolerance"))
    threshold = _finite(values.get("high_disagreement_threshold"))
    haircut = _probability(values.get("confidence_haircut"))
    minimum_confidence = _probability(values.get("minimum_confidence"))
    maximum_age = _positive(values.get("maximum_forecast_age_days"))
    if None in (tolerance, threshold, haircut, minimum_confidence, maximum_age):
        return unavailable_decomposition("forecast_uncertainty configuration has invalid values.")

    independent = _independent_models(models, float(tolerance))
    model_returns = [model["q50_return"] for model in independent]
    disagreement = statistics.pstdev(model_returns) if len(model_returns) > 1 else 0.0
    flagged = disagreement > float(threshold)

    q10 = _finite(distribution.get("q10_return"))
    q90 = _finite(distribution.get("q90_return"))
    aleatoric = q90 - q10 if q10 is not None and q90 is not None and q90 >= q10 else None

    coverage = _probability(distribution.get("coverage_ratio"))
    freshness = _freshness_age_days(distribution, models)
    if aleatoric is None or coverage is None or freshness is None:
        data_quality = None
    else:
        quality_fraction = max(1.0 - coverage, min(freshness / float(maximum_age), 1.0))
        data_quality = aleatoric * quality_fraction

    components = {
        "aleatoric": aleatoric,
        "epistemic": disagreement,
        "data_quality": data_quality,
    }
    total = (
        math.sqrt(math.fsum(value * value for value in components.values() if value is not None))
        if all(value is not None for value in components.values())
        else None
    )
    raw_confidence = _probability(base_confidence)
    adjusted_confidence = (
        raw_confidence * (1.0 - float(haircut)) if raw_confidence is not None and flagged else raw_confidence
    )
    reasons: list[str] = []
    if aleatoric is None:
        reasons.append("Distribution q10/q90 width is unavailable.")
    if coverage is None:
        reasons.append("Coverage ratio is unavailable.")
    if freshness is None:
        reasons.append("Forecast freshness is unavailable.")
    return {
        "status": "available" if total is not None else "unavailable",
        "reason": "; ".join(reasons) if reasons else None,
        "aleatoric_uncertainty": aleatoric,
        "epistemic_uncertainty": disagreement,
        "data_quality_uncertainty": data_quality,
        "total_uncertainty": total,
        "combination_rule": "root_sum_square",
        "model_disagreement": disagreement,
        "disagreement_threshold": float(threshold),
        "disagreement_flagged": flagged,
        "raw_model_count": len(models),
        "effective_model_count": len(independent),
        "breadth_discount": len(independent) / len(models),
        "forecast_age_days": freshness,
        "coverage_ratio": coverage,
        "base_confidence": raw_confidence,
        "adjusted_confidence": adjusted_confidence,
        "confidence_haircut": float(haircut) if flagged else 0.0,
        "minimum_confidence": float(minimum_confidence),
    }


def uncertainty_gate_reasons(
    assessment: Mapping[str, object],
    settings: object | None,
    *,
    effective_confidence: object = None,
) -> list[str]:
    """Return blocked_by-compatible gate codes for forecast uncertainty."""

    if settings is None:
        return ["forecast_uncertainty_config_missing"]
    if assessment.get("status") != "available":
        return ["forecast_uncertainty_unavailable"]
    reasons: list[str] = []
    if assessment.get("disagreement_flagged") is True:
        reasons.append("forecast_model_disagreement")
    values = _settings(settings)
    minimum = _probability(values.get("minimum_confidence")) if values is not None else None
    confidence = _probability(effective_confidence)
    if minimum is None:
        reasons.append("forecast_uncertainty_config_invalid")
    elif confidence is None or confidence < minimum:
        reasons.append("forecast_confidence_below_threshold")
    return reasons


def generate_scenarios(
    distribution: Mapping[str, object] | None,
    settings: object | None,
) -> dict[str, object]:
    """Create a replayable, seeded triangular scenario set from stored returns."""

    if settings is None:
        return {"status": "unavailable", "reason": "forecast_uncertainty configuration is missing."}
    values = _settings(settings)
    if values is None:
        return {"status": "unavailable", "reason": "forecast_uncertainty configuration is incomplete."}
    seed = _integer(values.get("scenario_seed"))
    count = _positive(values.get("scenario_count"))
    if seed is None or count is None:
        return {"status": "unavailable", "reason": "Scenario seed or count is invalid."}
    models = _model_records(distribution.get("per_model_distributions") if isinstance(distribution, Mapping) else None)
    tolerance = _finite(values.get("clone_return_tolerance"))
    if not models or tolerance is None:
        return {"status": "unavailable", "reason": "Per-model scenario inputs are unavailable."}
    independent = _independent_models(models, tolerance)
    inputs = {
        "method": "triangular_q10_q50_q90_v1",
        "scenario_count": count,
        "independent_models": independent,
    }
    replay_record = {"scenario_seed": seed, "scenario_inputs": inputs}
    return {
        "status": "available",
        **replay_record,
        "scenario_returns": replay_scenarios(replay_record),
    }


def replay_scenarios(record: Mapping[str, object]) -> list[float]:
    """Replay the recorded scenario inputs exactly using the stored seed."""

    seed = _integer(record.get("scenario_seed"))
    inputs = record.get("scenario_inputs")
    if seed is None or not isinstance(inputs, Mapping) or inputs.get("method") != "triangular_q10_q50_q90_v1":
        raise ValueError("A supported scenario seed and input record are required.")
    count = _positive(inputs.get("scenario_count"))
    models = _model_records(inputs.get("independent_models"))
    if count is None or not models:
        raise ValueError("Scenario count and per-model return inputs are required.")

    generator = random.Random(seed)
    output: list[float] = []
    for _ in range(count):
        model = models[generator.randrange(len(models))]
        lower, mode, upper = model["q10_return"], model["q50_return"], model["q90_return"]
        uniform = generator.random()
        split = (mode - lower) / (upper - lower) if upper > lower else 0.0
        if upper == lower:
            value = lower
        elif uniform < split:
            value = lower + math.sqrt(uniform * (upper - lower) * (mode - lower))
        else:
            value = upper - math.sqrt((1.0 - uniform) * (upper - lower) * (upper - mode))
        output.append(value)
    return output


def unavailable_decomposition(reason: str) -> dict[str, object]:
    """Return a fully shaped unavailable decomposition without inventing zeroes."""

    return {
        "status": "unavailable",
        "reason": reason,
        "aleatoric_uncertainty": None,
        "epistemic_uncertainty": None,
        "data_quality_uncertainty": None,
        "total_uncertainty": None,
        "combination_rule": "root_sum_square",
        "model_disagreement": None,
        "disagreement_threshold": None,
        "disagreement_flagged": False,
        "raw_model_count": None,
        "effective_model_count": None,
        "breadth_discount": None,
        "forecast_age_days": None,
        "coverage_ratio": None,
        "base_confidence": None,
        "adjusted_confidence": None,
        "confidence_haircut": None,
        "minimum_confidence": None,
    }


def _model_records(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    records: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        q10 = _finite(item.get("q10_return"))
        q50 = _finite(item.get("q50_return"))
        q90 = _finite(item.get("q90_return"))
        if q10 is None or q50 is None or q90 is None or not q10 <= q50 <= q90:
            continue
        records.append({
            "model_name": str(item.get("model_name") or ""),
            "model_id": _identifier(item.get("model_id")),
            "q10_return": q10,
            "q50_return": q50,
            "q90_return": q90,
            "forecast_date": item.get("forecast_date"),
        })
    return sorted(records, key=lambda row: (row["model_name"], row["model_id"] or ""))


def _independent_models(models: list[dict[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    independent: list[dict[str, Any]] = []
    for model in models:
        clone = any(
            (model["model_id"] is not None and model["model_id"] == other["model_id"])
            or all(abs(model[field] - other[field]) <= tolerance for field in ("q10_return", "q50_return", "q90_return"))
            for other in independent
        )
        if not clone:
            independent.append(model)
    return independent


def _freshness_age_days(distribution: Mapping[str, object], models: list[dict[str, Any]]) -> int | None:
    decision = _date_value(distribution.get("decision_time"))
    forecast_dates = [_date_value(model.get("forecast_date")) for model in models]
    if decision is None or not forecast_dates or any(value is None for value in forecast_dates):
        return None
    ages = [(decision - value).total_seconds() / 86400 for value in forecast_dates if value is not None]
    if any(age < 0 for age in ages):
        return None
    return math.ceil(max(ages))


def _date_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _settings(settings: object) -> dict[str, object] | None:
    if isinstance(settings, Mapping):
        return dict(settings)
    dump = getattr(settings, "model_dump", None)
    if callable(dump):
        result = dump()
        return result if isinstance(result, dict) else None
    return None


def _identifier(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and text.casefold() not in {"none", "nan", "<na>"} else None


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _probability(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and 0 <= number <= 1 else None


def _positive(value: object) -> int | None:
    number = _finite(value)
    return int(number) if number is not None and number > 0 and number.is_integer() else None


def _integer(value: object) -> int | None:
    number = _finite(value)
    return int(number) if number is not None and number >= 0 and number.is_integer() else None


__all__ = [
    "decompose_forecast_uncertainty",
    "generate_scenarios",
    "replay_scenarios",
    "uncertainty_gate_reasons",
    "unavailable_decomposition",
]
