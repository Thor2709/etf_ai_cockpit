"""Versioned portfolio goals, after-trade constraints and snapshot alerts.

Policy limits are supplied by the user and are never defaulted or relaxed.
Credit ratings use the conventional descending agency scale documented in
``_RATING_SCALE``; unknown grades fail closed as unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from typing import Literal

from etf_cockpit.portfolio.sandbox import WEIGHT_TOLERANCE


PORTFOLIO_GOALS_SCHEMA = "portfolio_goals.v1"
PORTFOLIO_POLICY_SCHEMA = "portfolio_policy.v1"
_RATING_SCALE = (
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D",
)
_POLICY_FIELDS = frozenset({
    "target_weights", "target_bands", "cash_reserve_weight", "max_position_weight",
    "max_sector_weight", "max_country_weight", "max_currency_weight", "max_issuer_weight",
    "max_duration_years", "minimum_rating", "minimum_income_yield", "maximum_maturity_days",
    "minimum_liquidity_eur", "max_drawdown", "event_within_days", "maturity_within_days",
    "forecast_deterioration_pct",
})


@dataclass(frozen=True)
class PortfolioPolicy:
    policy_id: str
    version: int
    target_weights: tuple[tuple[str, float], ...] = ()
    target_bands: tuple[tuple[str, float, float], ...] = ()
    cash_reserve_weight: float | None = None
    max_position_weight: float | None = None
    max_sector_weight: float | None = None
    max_country_weight: float | None = None
    max_currency_weight: float | None = None
    max_issuer_weight: float | None = None
    max_duration_years: float | None = None
    minimum_rating: str | None = None
    minimum_income_yield: float | None = None
    maximum_maturity_days: int | None = None
    minimum_liquidity_eur: float | None = None
    max_drawdown: float | None = None
    event_within_days: int | None = None
    maturity_within_days: int | None = None
    forecast_deterioration_pct: float | None = None
    schema_version: str = PORTFOLIO_POLICY_SCHEMA


@dataclass(frozen=True)
class ConstraintResult:
    constraint_id: str
    status: Literal["pass", "blocked", "unavailable", "not_applicable"]
    observed: float | str | None
    limit: float | str | tuple[float, float] | None
    explanation: str
    blocking: bool


@dataclass(frozen=True)
class Alert:
    alert_id: str
    kind: str
    condition: str
    severity: str
    source_snapshot_hash: str
    explanation: str
    evidence: Mapping[str, object]
    execution_allowed: Literal[False] = False


@dataclass(frozen=True)
class WhatIfScenario:
    scenario_id: str
    candidate_id: str
    name: str
    source_snapshot_hash: str | None
    status: Literal["ready", "blocked", "unavailable"]
    constraints: tuple[ConstraintResult, ...]
    after_trade_value: Mapping[str, object]
    return_distribution: Mapping[str, object]
    risk: Mapping[str, object]
    cost: Mapping[str, object]
    exposure: Mapping[str, object]
    binding_constraints: tuple[str, ...]
    rejected_candidates: tuple[str, ...]
    execution_allowed: Literal[False] = False


def validate_portfolio_policy(
    values: object,
    *,
    policy_id: str,
    version: int,
) -> PortfolioPolicy:
    """Validate a user-authored policy; omitted limits remain unconfigured.

    A target without an explicit band is matched using the existing sandbox
    ``WEIGHT_TOLERANCE``. Drawdown limits compare the magnitude of the
    canonical signed peak-to-trough result.
    """

    if not isinstance(values, Mapping):
        raise ValueError("policy must be a JSON object")
    payload = dict(values)
    if "schema_version" in payload and payload.pop("schema_version") != PORTFOLIO_POLICY_SCHEMA:
        raise ValueError("policy schema_version is not supported")
    unknown = set(payload) - _POLICY_FIELDS
    if unknown:
        raise ValueError(f"unknown policy fields: {', '.join(sorted(map(str, unknown)))}")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("policy version must be a positive integer")
    clean_weights = _weight_map(payload.get("target_weights", {}), "target_weights")
    clean_bands = _weight_bands(payload.get("target_bands", {}))
    clean: dict[str, object] = {
        "policy_id": _clean_identifier(policy_id, "policy_id"),
        "version": version,
        "target_weights": tuple(sorted(clean_weights.items())),
        "target_bands": tuple(sorted((key, lower, upper) for key, (lower, upper) in clean_bands.items())),
    }
    for field in (
        "cash_reserve_weight", "max_position_weight", "max_sector_weight", "max_country_weight",
        "max_currency_weight", "max_issuer_weight", "minimum_income_yield", "max_drawdown",
        "forecast_deterioration_pct",
    ):
        clean[field] = _optional_fraction(payload.get(field), field)
    clean["max_duration_years"] = _optional_nonnegative(payload.get("max_duration_years"), "max_duration_years")
    clean["minimum_liquidity_eur"] = _optional_nonnegative(payload.get("minimum_liquidity_eur"), "minimum_liquidity_eur")
    clean["maximum_maturity_days"] = _optional_days(payload.get("maximum_maturity_days"), "maximum_maturity_days")
    clean["event_within_days"] = _optional_days(payload.get("event_within_days"), "event_within_days")
    clean["maturity_within_days"] = _optional_days(payload.get("maturity_within_days"), "maturity_within_days")
    rating = payload.get("minimum_rating")
    if rating is not None:
        rating = str(rating).strip().upper().replace(" ", "")
        if rating not in _RATING_SCALE:
            raise ValueError("minimum_rating must use a supported agency rating grade")
    clean["minimum_rating"] = rating
    return PortfolioPolicy(**clean)  # type: ignore[arg-type]


def policy_record(policy: PortfolioPolicy, *, saved_at: str | None = None) -> dict[str, object]:
    """Return the JSON-safe immutable version record used by local storage."""

    value = asdict(policy)
    value["target_weights"] = dict(policy.target_weights)
    value["target_bands"] = {key: [lower, upper] for key, lower, upper in policy.target_bands}
    if saved_at is not None:
        value["saved_at"] = saved_at
    return value


def policy_editor_value(policy: PortfolioPolicy | None) -> dict[str, object]:
    """Return editable fields without repository identity or version metadata."""

    if policy is None:
        return {
            "target_weights": {},
            "target_bands": {},
            **{field: None for field in sorted(_POLICY_FIELDS - {"target_weights", "target_bands"})},
        }
    record = policy_record(policy)
    return {key: record[key] for key in _POLICY_FIELDS}


def policy_from_record(record: object) -> PortfolioPolicy | None:
    if not isinstance(record, Mapping):
        return None
    try:
        policy = validate_portfolio_policy(
            {key: record[key] for key in _POLICY_FIELDS if key in record},
            policy_id=str(record.get("policy_id", "")),
            version=record.get("version"),  # type: ignore[arg-type]
        )
    except (TypeError, ValueError):
        return None
    if record.get("schema_version") != PORTFOLIO_POLICY_SCHEMA:
        return None
    return policy


def source_snapshot_hash(analysis: object) -> str | None:
    """Hash the existing snapshot binding so alert replay uses exact lineage."""

    binding = getattr(analysis, "snapshot_binding", None)
    if binding is None:
        return None
    fields = (
        "account_id", "portfolio_id", "snapshot_id", "source_revision", "source_checksum",
        "price_source_revision", "price_source_checksum", "as_of", "holdings_view", "holdings_sources",
    )
    payload = {name: _json_value(getattr(binding, name, None)) for name in fields}
    if not payload.get("source_checksum") or not payload.get("snapshot_id"):
        return None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_constraints(
    policy: PortfolioPolicy,
    analysis: object,
    snapshot: object,
    *,
    evidence: Mapping[str, object] | None = None,
) -> tuple[ConstraintResult, ...]:
    """Evaluate configured constraints against candidate after-trade weights."""

    evidence = evidence or {}
    rows = tuple(getattr(analysis, "allocations", ()) or ())
    candidate = getattr(analysis, "candidate", None)
    weights = {
        str(getattr(row, "instrument_id", "")): _finite_or_none(getattr(row, "target_weight", None))
        for row in rows
    }
    weights = {key: value for key, value in weights.items() if key and value is not None}
    candidate_weights = getattr(candidate, "targets", None)
    if not rows and isinstance(candidate_weights, Mapping):
        # The candidate contract stores only positive targets; omission means
        # the user explicitly selected a zero target for that instrument.
        weights = {str(key): float(value) for key, value in candidate_weights.items()}
    if not rows and candidate is None:
        return tuple(
            _unavailable_result(name, "after_trade_allocations_unavailable")
            for name, configured in _configured_constraints(policy)
            if configured
        )
    results: list[ConstraintResult] = []
    bands = {key: (lower, upper) for key, lower, upper in policy.target_bands}
    for instrument_id, target in policy.target_weights:
        if instrument_id in bands:
            continue
        actual = weights.get(instrument_id)
        if actual is None:
            actual = _candidate_weight(candidate, instrument_id)
        if actual is None:
            results.append(_unavailable_result(f"target_weight:{instrument_id}", "after_trade_weight_unavailable"))
        else:
            blocked = abs(actual - target) > WEIGHT_TOLERANCE
            results.append(ConstraintResult(
                f"target_weight:{instrument_id}", "blocked" if blocked else "pass", actual, target,
                f"after-trade weight {actual:.1%} differs from target {target:.1%}" if blocked else "after-trade weight matches target",
                blocked,
            ))
    for instrument_id, lower, upper in policy.target_bands:
        weight = weights.get(instrument_id)
        if weight is None:
            weight = _candidate_weight(candidate, instrument_id)
        if weight is None:
            results.append(_unavailable_result(f"target_band:{instrument_id}", "after_trade_weight_unavailable"))
        else:
            blocked = weight < lower - WEIGHT_TOLERANCE or weight > upper + WEIGHT_TOLERANCE
            results.append(ConstraintResult(
                f"target_band:{instrument_id}", "blocked" if blocked else "pass", weight, (lower, upper),
                f"after-trade weight {weight:.1%} is outside [{lower:.1%}, {upper:.1%}]" if blocked else "after-trade weight is inside the target band",
                blocked,
            ))
    if policy.cash_reserve_weight is not None:
        cash_weight = _finite_or_none(getattr(candidate, "cash_weight", None))
        results.append(_compare_minimum("cash_reserve_weight", cash_weight, policy.cash_reserve_weight, "after-trade cash reserve"))
    if policy.max_position_weight is not None:
        if not weights:
            results.append(ConstraintResult("max_position_weight", "not_applicable", None, policy.max_position_weight, "No after-trade positions are present.", False))
        else:
            for instrument_id, weight in sorted(weights.items()):
                results.append(_compare_maximum(
                    f"max_position_weight:{instrument_id}", weight, policy.max_position_weight,
                    f"after-trade position {instrument_id}",
                ))
    for field, limit, label in (
        ("sector", policy.max_sector_weight, "max_sector_weight"),
        ("country", policy.max_country_weight, "max_country_weight"),
        ("currency", policy.max_currency_weight, "max_currency_weight"),
        ("issuer", policy.max_issuer_weight, "max_issuer_weight"),
    ):
        if limit is not None:
            results.append(_exposure_constraint(label, field, limit, weights, snapshot))
    if policy.max_duration_years is not None:
        results.append(_duration_constraint(policy.max_duration_years, weights, snapshot))
    if policy.minimum_rating is not None:
        results.append(_rating_constraint(policy.minimum_rating, weights, snapshot))
    if policy.minimum_income_yield is not None:
        results.append(_evidence_constraint("minimum_income_yield", evidence.get("income_yield"), policy.minimum_income_yield, minimum=True))
    if policy.maximum_maturity_days is not None:
        results.append(_maturity_constraint(policy.maximum_maturity_days, weights, analysis, snapshot, evidence))
    if policy.minimum_liquidity_eur is not None:
        results.append(_evidence_constraint("minimum_liquidity_eur", evidence.get("liquidity_eur"), policy.minimum_liquidity_eur, minimum=True))
    if policy.max_drawdown is not None:
        value, reason = _canonical_metric(evidence.get("max_drawdown"))
        if value is None:
            results.append(_unavailable_result("max_drawdown", reason or "max_drawdown_unavailable"))
        else:
            results.append(_compare_maximum("max_drawdown", abs(value), policy.max_drawdown, "maximum drawdown magnitude"))
    return tuple(results)


def build_alerts(
    analysis: object,
    policy: PortfolioPolicy,
    *,
    snapshot: object | None = None,
    evidence: Mapping[str, object] | None = None,
    snapshot_hash: str | None = None,
) -> tuple[tuple[Alert, ...], tuple[dict[str, object], ...]]:
    """Build deterministic alerts from one bound snapshot and canonical evidence."""

    evidence = evidence or {}
    bound_hash = snapshot_hash or source_snapshot_hash(analysis)
    if not bound_hash:
        return (), ({"kind": "all", "status": "unavailable", "reason": "source_snapshot_binding_unavailable"},)
    alerts: list[Alert] = []
    unavailable: list[dict[str, object]] = []
    for row in tuple(getattr(analysis, "allocations", ()) or ()):
        drift_status = str(getattr(row, "drift_status", ""))
        if drift_status in {"above_soft_band", "above_hard_band"}:
            identifier = str(getattr(row, "instrument_id", ""))
            alerts.append(_alert(
                bound_hash, "drift", f"{identifier}:{drift_status}",
                "high" if drift_status == "above_hard_band" else "medium",
                f"{identifier} drift is {drift_status.replace('_', ' ')}.",
                {"instrument_id": identifier, "current_weight": getattr(row, "current_weight", None),
                 "target_weight": getattr(row, "target_weight", None)},
            ))
    if snapshot is not None:
        constraints = evaluate_constraints(policy, analysis, snapshot, evidence=evidence)
    else:
        constraints = ()
    for result in constraints:
        if result.status == "blocked":
            alerts.append(_alert(
                bound_hash, "concentration", result.constraint_id, "high", result.explanation,
                {"observed": result.observed, "limit": result.limit},
            ))
    for result in tuple(getattr(analysis, "constraints", ()) or ()):
        if str(getattr(result, "status", "")) == "violated":
            constraint_id = str(getattr(result, "name", "existing_constraint"))
            alerts.append(_alert(
                bound_hash, "concentration", constraint_id, "high",
                str(getattr(result, "reason", "Existing portfolio constraint is violated.")),
                {"observed": getattr(result, "target_value", None), "limit": getattr(result, "limit", None)},
            ))
    if bool(getattr(analysis, "source_stale", False)):
        alerts.append(_alert(
            bound_hash, "stale_data", "source_binding_stale", "high",
            "The candidate source binding differs from the selected portfolio snapshot.",
            {"source_stale": True},
        ))
    else:
        freshness, reason = _canonical_metric(evidence.get("data_staleness"))
        if freshness is None:
            unavailable.append({"kind": "stale_data", "status": "unavailable", "reason": reason or "source_freshness_evidence_unavailable"})
        elif freshness > 0:
            alerts.append(_alert(
                bound_hash, "stale_data", "source_freshness_breached", "high",
                "The canonical source freshness check reports stale portfolio inputs.",
                {"staleness": freshness},
            ))
    _threshold_alert(
        alerts, unavailable, bound_hash, policy.max_drawdown, _absolute_drawdown_evidence(evidence.get("max_drawdown")),
        "drawdown", "max_drawdown", "Drawdown exceeds the configured maximum.", compare="maximum",
    )
    _threshold_alert(
        alerts, unavailable, bound_hash, policy.forecast_deterioration_pct,
        evidence.get("forecast_deterioration"), "forecast_deterioration", "forecast_deterioration_pct",
        "Saved point-in-time forecast deterioration exceeds the configured threshold.", compare="maximum",
    )
    calendar = evidence.get("calendar")
    _calendar_alerts(alerts, unavailable, bound_hash, policy, analysis, calendar)
    return tuple(sorted(alerts, key=lambda item: (item.kind, item.condition, item.alert_id))), tuple(unavailable)


def build_what_if_scenario(
    analysis: object,
    snapshot: object,
    policy: PortfolioPolicy,
    *,
    evidence: Mapping[str, object] | None = None,
    forecast: object | None = None,
) -> WhatIfScenario:
    """Bind the canonical candidate analysis to policy and what-if evidence."""

    evidence = evidence or {}
    binding_hash = source_snapshot_hash(analysis)
    constraints = (*evaluate_constraints(policy, analysis, snapshot, evidence=evidence), *_canonical_constraints(analysis))
    blockers = tuple(
        f"{item.constraint_id}: {item.explanation}"
        for item in constraints
        if item.blocking
    )
    if bool(getattr(analysis, "source_stale", False)):
        blockers = (*blockers, "source_binding: selected source snapshot changed")
    if binding_hash is None:
        blockers = (*blockers, "source_binding: snapshot hash unavailable")
    candidate = getattr(analysis, "candidate", None)
    candidate_id = str(getattr(candidate, "candidate_id", "candidate-unavailable"))
    name = str(getattr(candidate, "name", "What-if scenario"))
    scenario_id = hashlib.sha256(f"{binding_hash or 'unavailable'}:{candidate_id}".encode("utf-8")).hexdigest()
    forecast_projection = _forecast_projection(forecast)
    target_projection = forecast_projection.get("target")
    target_projection = target_projection if isinstance(target_projection, Mapping) else {}
    reconciliation = target_projection.get("reconciliation")
    reconciliation = reconciliation if isinstance(reconciliation, Mapping) else {}
    projected_value = reconciliation.get("portfolio_value")
    after_trade_value = _available(projected_value, "Canonical target value from the bound portfolio forecast.") if _finite_or_none(projected_value) is not None else _unavailable("canonical_after_trade_value_unavailable")
    forecast_status = str(forecast_projection.get("status", "unavailable"))
    return_distribution = (
        _available(target_projection, "Canonical point-in-time portfolio forecast target.")
        if forecast_status in {"available", "partial"} and target_projection
        else _unavailable(str(forecast_projection.get("reason") or "canonical_return_distribution_unavailable"))
    )
    service_evidence = getattr(analysis, "service_evidence", {})
    risk = service_evidence.get("risk") if isinstance(service_evidence, Mapping) else None
    cost = getattr(analysis, "cost", None)
    exposures = {
        "sector": _exposure_rows(getattr(analysis, "sector_exposure", ())),
        "region": _exposure_rows(getattr(analysis, "region_exposure", ())),
        "currency": _exposure_rows(getattr(analysis, "currency_exposure", ())),
    }
    return WhatIfScenario(
        scenario_id=scenario_id,
        candidate_id=candidate_id,
        name=name,
        source_snapshot_hash=binding_hash,
        status="blocked" if blockers else "ready" if binding_hash else "unavailable",
        constraints=constraints,
        after_trade_value=after_trade_value,
        return_distribution=return_distribution,
        risk=_service_projection(risk, "canonical_portfolio_risk_unavailable"),
        cost=_object_projection(cost, "canonical_candidate_cost_unavailable"),
        exposure=_available(exposures, "Post-trade exposure from the canonical sandbox analysis."),
        binding_constraints=tuple(item.constraint_id for item in constraints if item.blocking),
        rejected_candidates=blockers,
    )


def what_if_record(scenario: WhatIfScenario) -> dict[str, object]:
    value = asdict(scenario)
    value["constraints"] = [asdict(item) for item in scenario.constraints]
    return _json_value(value)  # type: ignore[return-value]


def alert_record(alert: Alert) -> dict[str, object]:
    return _json_value(asdict(alert))  # type: ignore[return-value]


def _configured_constraints(policy: PortfolioPolicy) -> tuple[tuple[str, bool], ...]:
    fields = sorted(_POLICY_FIELDS - {"target_weights", "target_bands"})
    configured = [(name, getattr(policy, name) is not None) for name in fields]
    configured.extend((f"target_weight:{key}", True) for key, _ in policy.target_weights)
    configured.extend((f"target_band:{key}", True) for key, _, _ in policy.target_bands)
    return tuple(configured)


def _weight_map(raw: object, label: str) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object keyed by instrument id")
    output: dict[str, float] = {}
    for key, value in raw.items():
        instrument_id = _clean_identifier(key, f"{label} instrument id")
        weight = _fraction(value, f"{label}[{instrument_id}]")
        output[instrument_id] = weight
    return output


def _weight_bands(raw: object) -> dict[str, tuple[float, float]]:
    if not isinstance(raw, Mapping):
        raise ValueError("target_bands must be an object keyed by instrument id")
    output: dict[str, tuple[float, float]] = {}
    for key, raw_band in raw.items():
        instrument_id = _clean_identifier(key, "target band instrument id")
        if isinstance(raw_band, Mapping):
            if set(raw_band) != {"minimum", "maximum"}:
                raise ValueError(f"target_bands[{instrument_id}] needs minimum and maximum")
            lower_raw, upper_raw = raw_band["minimum"], raw_band["maximum"]
        elif isinstance(raw_band, Sequence) and not isinstance(raw_band, (str, bytes)) and len(raw_band) == 2:
            lower_raw, upper_raw = raw_band
        else:
            raise ValueError(f"target_bands[{instrument_id}] must be [minimum, maximum]")
        lower = _fraction(lower_raw, f"target_bands[{instrument_id}].minimum")
        upper = _fraction(upper_raw, f"target_bands[{instrument_id}].maximum")
        if lower > upper:
            raise ValueError(f"target_bands[{instrument_id}] minimum exceeds maximum")
        output[instrument_id] = (lower, upper)
    return output


def _fraction(value: object, label: str) -> float:
    number = _finite(value, label)
    if not 0 <= number <= 1:
        raise ValueError(f"{label} must be between 0 and 1")
    return number


def _optional_fraction(value: object, label: str) -> float | None:
    return None if value is None else _fraction(value, label)


def _optional_nonnegative(value: object, label: str) -> float | None:
    if value is None:
        return None
    number = _finite(value, label)
    if number < 0:
        raise ValueError(f"{label} must be non-negative")
    return number


def _optional_days(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _clean_identifier(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 160:
        raise ValueError(f"{label} must contain 1 to 160 characters")
    return result


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _finite_or_none(value: object) -> float | None:
    try:
        return _finite(value, "value")
    except ValueError:
        return None


def _compare_maximum(name: str, observed: float | None, limit: float, label: str) -> ConstraintResult:
    if observed is None:
        return _unavailable_result(name, f"{label}_unavailable")
    blocked = observed > limit + WEIGHT_TOLERANCE
    return ConstraintResult(name, "blocked" if blocked else "pass", observed, limit,
                            f"{label} {observed:.1%} exceeds {limit:.1%}" if blocked else f"{label} is within {limit:.1%}", blocked)


def _compare_minimum(name: str, observed: float | None, limit: float, label: str) -> ConstraintResult:
    if observed is None:
        return _unavailable_result(name, f"{label}_unavailable")
    blocked = observed < limit - WEIGHT_TOLERANCE
    return ConstraintResult(name, "blocked" if blocked else "pass", observed, limit,
                            f"{label} {observed:.1%} is below {limit:.1%}" if blocked else f"{label} meets {limit:.1%}", blocked)


def _candidate_weight(candidate: object, instrument_id: str) -> float | None:
    targets = getattr(candidate, "targets", None)
    if not isinstance(targets, Mapping):
        return None
    # Candidate targets contain positive positions only; omitted means an
    # explicit after-trade target of zero under the existing sandbox contract.
    return _finite_or_none(targets.get(instrument_id, 0.0))


def _unavailable_result(name: str, reason: str) -> ConstraintResult:
    return ConstraintResult(name, "unavailable", None, None, reason, True)


def _exposure_constraint(
    name: str,
    field: str,
    limit: float,
    weights: Mapping[str, float],
    snapshot: object,
) -> ConstraintResult:
    buckets: dict[str, float] = {}
    missing: list[str] = []
    for instrument_id, weight in weights.items():
        if weight <= WEIGHT_TOLERANCE:
            continue
        value, reason = _metadata(snapshot, instrument_id, field)
        if reason or value is None:
            missing.append(instrument_id)
            continue
        bucket = str(value).strip()
        if not bucket:
            missing.append(instrument_id)
            continue
        buckets[bucket] = buckets.get(bucket, 0.0) + weight
    if missing:
        return _unavailable_result(name, f"{field}_metadata_unavailable_for:{','.join(sorted(missing))}")
    if not buckets:
        if not weights:
            return ConstraintResult(name, "not_applicable", None, limit, "No after-trade invested exposure is present.", False)
        return _unavailable_result(name, "after_trade_exposure_unavailable")
    bucket, observed = max(buckets.items(), key=lambda item: (item[1], item[0]))
    blocked = observed > limit + WEIGHT_TOLERANCE
    return ConstraintResult(name, "blocked" if blocked else "pass", observed, limit,
                            f"{field} {bucket} exposure {observed:.1%} exceeds {limit:.1%}" if blocked else f"largest {field} exposure {bucket} is {observed:.1%}", blocked)


def _metadata(snapshot: object, instrument_id: str, field: str) -> tuple[object | None, str | None]:
    config = getattr(snapshot, "config", None)
    universe = getattr(config, "universe", None)
    by_id = getattr(universe, "by_id", None)
    instrument = by_id().get(instrument_id) if callable(by_id) else None
    holdings = getattr(snapshot, "holdings", None)
    rows: list[object] = []
    if hasattr(holdings, "iterrows"):
        for _, row in holdings.iterrows():
            row_id = str(row.get("etf_id", row.get("instrument_id", "")) or "").strip()
            if row_id == instrument_id and _present(row.get(field)):
                rows.append(row.get(field))
    values = {str(value).strip() for value in rows}
    if len(values) == 1:
        return rows[0], None
    if len(values) > 1:
        return None, f"ambiguous_{field}_metadata"
    configured = _mapping_value(instrument, field)
    if _present(configured):
        return configured, None
    return None, f"{field}_metadata_unavailable"


def _mapping_value(value: object, key: str) -> object | None:
    return value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _fixed_income_positions(weights: Mapping[str, float], snapshot: object) -> tuple[list[tuple[str, float]], list[str]]:
    included: list[tuple[str, float]] = []
    unknown: list[str] = []
    debt_classes = {"bond", "fixed_income", "fixed income", "fixed_rate_bond", "government_bond", "corporate_bond"}
    for instrument_id, weight in weights.items():
        if weight <= WEIGHT_TOLERANCE:
            continue
        asset_type, type_reason = _metadata(snapshot, instrument_id, "asset_type")
        asset_class, class_reason = _metadata(snapshot, instrument_id, "asset_class")
        observed_class = asset_type if str(asset_type or "").strip().casefold() in debt_classes else asset_class or asset_type
        if observed_class is None or (class_reason and type_reason):
            unknown.append(instrument_id)
        elif str(observed_class).strip().casefold() in debt_classes:
            included.append((instrument_id, weight))
    return included, unknown


def _duration_constraint(limit: float, weights: Mapping[str, float], snapshot: object) -> ConstraintResult:
    bonds, unknown = _fixed_income_positions(weights, snapshot)
    if unknown:
        return _unavailable_result("max_duration_years", f"asset_class_metadata_unavailable_for:{','.join(sorted(unknown))}")
    if not bonds:
        return ConstraintResult("max_duration_years", "not_applicable", None, limit, "No after-trade fixed-income exposure is present.", False)
    durations: list[tuple[float, float]] = []
    for instrument_id, weight in bonds:
        raw, reason = _metadata(snapshot, instrument_id, "duration_years")
        value = _finite_or_none(raw)
        if reason or value is None or value < 0:
            return _unavailable_result("max_duration_years", f"duration_years_unavailable_for:{instrument_id}")
        durations.append((value, weight))
    total_weight = math.fsum(weight for _, weight in durations)
    if total_weight <= 0:
        return _unavailable_result("max_duration_years", "after_trade_fixed_income_weight_unavailable")
    observed = math.fsum(value * weight for value, weight in durations) / total_weight
    blocked = observed > limit + WEIGHT_TOLERANCE
    return ConstraintResult("max_duration_years", "blocked" if blocked else "pass", observed, limit,
                            f"after-trade weighted duration {observed:.2f} years exceeds {limit:.2f}" if blocked else f"after-trade weighted duration {observed:.2f} years is within the limit", blocked)


def _rating_constraint(limit: str, weights: Mapping[str, float], snapshot: object) -> ConstraintResult:
    bonds, unknown = _fixed_income_positions(weights, snapshot)
    if unknown:
        return _unavailable_result("minimum_rating", f"asset_class_metadata_unavailable_for:{','.join(sorted(unknown))}")
    if not bonds:
        return ConstraintResult("minimum_rating", "not_applicable", None, limit, "No after-trade fixed-income exposure is present.", False)
    observed: list[str] = []
    for instrument_id, _weight in bonds:
        raw, reason = _metadata(snapshot, instrument_id, "rating")
        grade = str(raw or "").strip().upper().replace(" ", "")
        if reason or grade not in _RATING_SCALE:
            return _unavailable_result("minimum_rating", f"supported_rating_unavailable_for:{instrument_id}")
        observed.append(grade)
    worst = max(observed, key=_RATING_SCALE.index)
    blocked = _RATING_SCALE.index(worst) > _RATING_SCALE.index(limit)
    return ConstraintResult("minimum_rating", "blocked" if blocked else "pass", worst, limit,
                            f"worst after-trade rating {worst} is below {limit}" if blocked else f"worst after-trade rating {worst} meets {limit}", blocked)


def _evidence_constraint(name: str, raw: object, limit: float, *, minimum: bool) -> ConstraintResult:
    value, reason = _canonical_metric(raw)
    if value is None:
        return _unavailable_result(name, reason or f"{name}_unavailable")
    return _compare_minimum(name, value, limit, name) if minimum else _compare_maximum(name, value, limit, name)


def _maturity_constraint(limit: int, weights: Mapping[str, float], analysis: object, snapshot: object, evidence: Mapping[str, object]) -> ConstraintResult:
    bonds, unknown = _fixed_income_positions(weights, snapshot)
    if unknown:
        return _unavailable_result("maximum_maturity_days", f"asset_class_metadata_unavailable_for:{','.join(sorted(unknown))}")
    if not bonds:
        return ConstraintResult("maximum_maturity_days", "not_applicable", None, float(limit), "No after-trade fixed-income exposure is present.", False)
    calendar = evidence.get("calendar")
    rows = calendar.get("events") if isinstance(calendar, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return _unavailable_result("maximum_maturity_days", "point_in_time_maturity_calendar_unavailable")
    binding = getattr(analysis, "snapshot_binding", None)
    decision = _iso_date(getattr(binding, "as_of", None))
    if decision is None:
        return _unavailable_result("maximum_maturity_days", "decision_time_unavailable_for_maturity")
    maturity_by_id: dict[str, date] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        event_type = str(row.get("event_type", row.get("title", ""))).casefold()
        if "matur" not in event_type:
            continue
        instrument_id = str(row.get("instrument_id", "")).strip()
        event_date = _iso_date(row.get("event_date"))
        if instrument_id and event_date is not None:
            maturity_by_id[instrument_id] = event_date
    missing = sorted(identifier for identifier, _ in bonds if identifier not in maturity_by_id)
    if missing:
        return _unavailable_result("maximum_maturity_days", f"point_in_time_maturity_unavailable_for:{','.join(missing)}")
    days = max((maturity_by_id[identifier] - decision).days for identifier, _ in bonds)
    return _compare_maximum("maximum_maturity_days", float(days), float(limit), "after-trade maximum maturity days")


def _canonical_constraints(analysis: object) -> tuple[ConstraintResult, ...]:
    """Retain the candidate analyzer's configured portfolio limits verbatim."""

    output: list[ConstraintResult] = []
    for item in tuple(getattr(analysis, "constraints", ()) or ()):
        status = str(getattr(item, "status", "unavailable"))
        if status == "violated":
            result_status: Literal["pass", "blocked", "unavailable", "not_applicable"] = "blocked"
            blocking = True
        elif status == "pass":
            result_status = "pass"
            blocking = False
        else:
            result_status = "unavailable"
            blocking = True
        name = str(getattr(item, "name", "constraint"))
        reason = str(getattr(item, "reason", ""))
        output.append(ConstraintResult(
            f"existing:{name}",
            result_status,
            _finite_or_none(getattr(item, "target_value", None)),
            _finite_or_none(getattr(item, "limit", None)),
            reason or ("existing candidate constraint is unavailable" if result_status == "unavailable" else "existing candidate constraint evaluated"),
            blocking,
        ))
    return tuple(output)


def _calendar_alerts(
    alerts: list[Alert],
    unavailable: list[dict[str, object]],
    bound_hash: str,
    policy: PortfolioPolicy,
    analysis: object,
    calendar: object,
) -> None:
    binding = getattr(analysis, "snapshot_binding", None)
    decision = _iso_date(getattr(binding, "as_of", None))
    for kind, threshold, predicate in (
        ("event", policy.event_within_days, lambda text: "matur" not in text),
        ("maturity", policy.maturity_within_days, lambda text: "matur" in text),
    ):
        if threshold is None:
            unavailable.append({"kind": kind, "status": "unavailable", "reason": f"{kind}_alert_window_not_configured"})
            continue
        rows = calendar.get("events") if isinstance(calendar, Mapping) else None
        if decision is None or not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            unavailable.append({"kind": kind, "status": "unavailable", "reason": "point_in_time_calendar_unavailable"})
            continue
        seen = False
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            event_type = str(row.get("event_type", row.get("title", ""))).casefold()
            if not predicate(event_type):
                continue
            event_date = _iso_date(row.get("event_date"))
            if event_date is None:
                continue
            days = (event_date - decision).days
            if 0 <= days <= threshold:
                seen = True
                instrument_id = str(row.get("instrument_id", "unavailable"))
                condition = f"{instrument_id}:{event_date.isoformat()}:{event_type}"
                alerts.append(_alert(
                    bound_hash, kind, condition, "medium",
                    f"{kind.title()} is scheduled in {days} days.",
                    {"instrument_id": instrument_id, "event_date": event_date.isoformat(), "days": days},
                ))
        # An empty, available calendar is a valid no-alert result.
        if not seen and isinstance(calendar, Mapping) and calendar.get("status") != "available":
            unavailable.append({"kind": kind, "status": "unavailable", "reason": str(calendar.get("reason") or "point_in_time_calendar_incomplete")})


def _threshold_alert(
    alerts: list[Alert],
    unavailable: list[dict[str, object]],
    bound_hash: str,
    threshold: float | None,
    raw: object,
    kind: str,
    condition: str,
    explanation: str,
    *,
    compare: Literal["maximum", "minimum"],
) -> None:
    if threshold is None:
        unavailable.append({"kind": kind, "status": "unavailable", "reason": f"{condition}_not_configured"})
        return
    value, reason = _canonical_metric(raw)
    if value is None:
        unavailable.append({"kind": kind, "status": "unavailable", "reason": reason or f"{kind}_evidence_unavailable"})
        return
    breached = value > threshold if compare == "maximum" else value < threshold
    if breached:
        alerts.append(_alert(bound_hash, kind, condition, "high", explanation, {"observed": value, "limit": threshold}))


def _canonical_metric(raw: object) -> tuple[float | None, str | None]:
    if not isinstance(raw, Mapping) or raw.get("status") != "available":
        reason = raw.get("reason") if isinstance(raw, Mapping) else None
        return None, str(reason or "canonical_point_in_time_metric_unavailable")
    value = _finite_or_none(raw.get("value"))
    return (value, None) if value is not None else (None, "canonical_metric_value_unavailable")


def _absolute_drawdown_evidence(raw: object) -> dict[str, object]:
    value, reason = _canonical_metric(raw)
    if value is None:
        return {"status": "unavailable", "value": None, "reason": reason or "canonical_drawdown_unavailable"}
    return {"status": "available", "value": abs(value), "reason": "canonical_signed_peak_to_trough_magnitude"}


def _alert(bound_hash: str, kind: str, condition: str, severity: str, explanation: str, evidence: Mapping[str, object]) -> Alert:
    canonical = json.dumps({"snapshot": bound_hash, "kind": kind, "condition": condition}, sort_keys=True, separators=(",", ":"))
    alert_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Alert(alert_id, kind, condition, severity, bound_hash, explanation, dict(evidence))


def _forecast_projection(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {"status": "unavailable", "reason": "canonical_portfolio_forecast_unavailable"}
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {"status": "unavailable", "reason": "canonical_portfolio_forecast_unavailable"}


def _service_projection(value: object, reason: str) -> dict[str, object]:
    if isinstance(value, Mapping) and value.get("status") in {"available", "partial"}:
        return _available(dict(value), "Canonical portfolio risk projection.")
    if isinstance(value, Mapping):
        reason = str(value.get("reason") or reason)
    return _unavailable(reason)


def _object_projection(value: object, reason: str) -> dict[str, object]:
    if value is None:
        return _unavailable(reason)
    if isinstance(value, Mapping):
        return _available(dict(value), "Canonical portfolio candidate cost.")
    if hasattr(value, "__dataclass_fields__"):
        return _available(_json_value(asdict(value)), "Canonical portfolio candidate cost.")  # type: ignore[arg-type]
    return _unavailable(reason)


def _exposure_rows(rows: object) -> list[dict[str, object]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    result: list[dict[str, object]] = []
    for row in rows:
        result.append({
            "bucket": getattr(row, "bucket", None),
            "current_weight": getattr(row, "current_weight", None),
            "target_weight": getattr(row, "target_weight", None),
        })
    return result


def _available(value: object, reason: str) -> dict[str, object]:
    return {"status": "available", "value": _json_value(value), "reason": reason}


def _unavailable(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "value": None, "reason": reason}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _iso_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


__all__ = [
    "PORTFOLIO_GOALS_SCHEMA",
    "PORTFOLIO_POLICY_SCHEMA",
    "Alert",
    "ConstraintResult",
    "PortfolioPolicy",
    "WhatIfScenario",
    "alert_record",
    "build_alerts",
    "build_what_if_scenario",
    "evaluate_constraints",
    "policy_editor_value",
    "policy_from_record",
    "policy_record",
    "source_snapshot_hash",
    "validate_portfolio_policy",
    "what_if_record",
]
