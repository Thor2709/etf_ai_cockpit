"""Versioned advisory risk-profile policies projected onto portfolio goals.

Preset ratios and concentration guardrails live in ``configs/risk_profiles_v1.yaml``.
The ratio ladder and tier-separated concentration bands are conservative defaults:
they keep the five preset envelopes ordered while leaving edits inside explicit
guardrails. VWCE distribution metrics are only available when a sealed saved
distribution exists; this module never substitutes the product risk indicator,
market history, or a forecast for that missing envelope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Literal

import yaml

from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.core.values import finite_non_bool_float_or_none as _optional_number
from etf_cockpit.portfolio.goals_constraints import (
    build_what_if_scenario,
    policy_record,
    source_snapshot_hash,
    validate_portfolio_policy,
    what_if_record,
)


RISK_PROFILE_CONFIG = CONFIG_DIR / "risk_profiles_v1.yaml"
RISK_PROFILE_SCHEMA = "risk_profiles.v1"
_PARAMETERS = (
    "risk_budget_ratio",
    "max_position_weight",
    "max_sector_weight",
    "max_country_weight",
    "max_currency_weight",
)
_EXPECTED_LABELS = (
    "Safe",
    "Safe–Medium",
    "Medium",
    "Medium–Aggressive",
    "Aggressive",
)
_RISK_METRICS = (
    "probability_loss",
    "probability_underperform_vwce",
    "probability_underperform_cash",
    "lower_tail_quantile",
    "expected_shortfall",
    "max_drawdown",
    "volatility",
    "liquidity",
    "spread_and_dealing_cost",
    "liquidation_time",
    "evidence_quality",
    "calibration",
    "coverage",
    "model_disagreement",
    "net_return_and_upside",
    "certainty_equivalent_utility",
)
_RISK_METRIC_REASONS = {
    "probability_loss": "vwce_risk_distribution_unavailable",
    "probability_underperform_vwce": "vwce_risk_distribution_unavailable",
    "probability_underperform_cash": "cash_risk_distribution_unavailable",
    "lower_tail_quantile": "vwce_risk_distribution_unavailable",
    "expected_shortfall": "vwce_risk_distribution_unavailable",
    "max_drawdown": "vwce_risk_distribution_unavailable",
    "volatility": "vwce_risk_distribution_unavailable",
    "liquidity": "liquidity_evidence_unavailable",
    "spread_and_dealing_cost": "cost_evidence_unavailable",
    "liquidation_time": "liquidation_time_evidence_unavailable",
    "evidence_quality": "saved_calibration_quality_evidence_unavailable",
    "calibration": "saved_calibration_quality_evidence_unavailable",
    "coverage": "saved_calibration_quality_evidence_unavailable",
    "model_disagreement": "saved_calibration_quality_evidence_unavailable",
    "net_return_and_upside": "vwce_risk_distribution_unavailable",
    "certainty_equivalent_utility": "vwce_risk_distribution_unavailable",
}


class RiskProfileError(ValueError):
    """Invalid risk-profile configuration, version or edit."""


@dataclass(frozen=True)
class RiskProfilePolicy:
    profile_id: str
    label: str
    intent: str
    version: int
    parameters: tuple[tuple[str, float], ...]
    guardrails: tuple[tuple[str, float, float], ...]
    config_hash: str


@dataclass(frozen=True)
class RiskProfileVersion:
    profile_id: str
    label: str
    intent: str
    version: int
    parameters: tuple[tuple[str, float], ...]
    guardrails: tuple[tuple[str, float, float], ...]
    origin: Literal["preset", "user_edit", "reset_to_preset"]
    policy_hash: str


@dataclass(frozen=True)
class VWCEAnchorSnapshot:
    status: Literal["available", "unavailable"]
    reason: str | None
    canonical_share_class_id: str | None
    listing_id: str | None
    effective_date: str | None
    knowledge_cutoff: str | None
    output_currency: str | None
    horizon_years: float | None
    anchor_digest: str | None
    resolution_digest: str | None
    risk_envelope_status: Literal["unavailable"]
    risk_metrics: tuple[tuple[str, str], ...]
    execution_allowed: Literal[False] = False


@dataclass(frozen=True)
class ProfileEligibilityResult:
    profile_id: str
    status: Literal["eligible", "blocked", "unavailable"]
    eligible: bool | None
    rank: int | None
    recommendation: str
    binding_reasons: tuple[str, ...]
    constraints: tuple[Mapping[str, object], ...]
    execution_allowed: Literal[False] = False


@dataclass(frozen=True)
class ProfileProjection:
    status: Literal["partial", "unavailable"]
    reason: str | None
    profile: RiskProfileVersion
    profile_policy: Mapping[str, object]
    vwce_anchor: VWCEAnchorSnapshot
    eligibility: ProfileEligibilityResult
    scenario: Mapping[str, object]
    source_snapshot_hash: str | None
    projection_id: str
    execution_allowed: Literal[False] = False

    def to_record(self) -> dict[str, object]:
        return {
            "contract": "profile-projection.v1",
            "status": self.status,
            "reason": self.reason,
            "profile": risk_profile_version_record(self.profile),
            "profile_policy": dict(self.profile_policy),
            "vwce_anchor": asdict(self.vwce_anchor),
            "eligibility": asdict(self.eligibility),
            "scenario": dict(self.scenario),
            "source_snapshot_hash": self.source_snapshot_hash,
            "projection_id": self.projection_id,
            "execution_allowed": False,
        }


def load_risk_profile_presets(
    config_path: Path = RISK_PROFILE_CONFIG,
) -> tuple[RiskProfilePolicy, ...]:
    """Load and strictly validate all five presets; missing config never defaults."""

    try:
        text = config_path.read_text(encoding="utf-8")
        payload = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RiskProfileError("risk_profile_config_unavailable_or_invalid") from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version", "preset_version", "default_profile_id", "profiles"
    }:
        raise RiskProfileError("risk_profile_config_schema_invalid")
    if payload.get("schema_version") != RISK_PROFILE_SCHEMA:
        raise RiskProfileError("risk_profile_config_schema_unsupported")
    preset_version = payload.get("preset_version")
    if isinstance(preset_version, bool) or not isinstance(preset_version, int) or preset_version < 1:
        raise RiskProfileError("risk_profile_preset_version_invalid")
    rows = payload.get("profiles")
    if not isinstance(rows, list) or len(rows) != len(_EXPECTED_LABELS):
        raise RiskProfileError("risk_profile_presets_incomplete")
    config_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    profiles: list[RiskProfilePolicy] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "profile_id", "label", "intent", "parameters", "guardrails"
        }:
            raise RiskProfileError("risk_profile_preset_invalid")
        profile_id = _safe_text(row.get("profile_id"), "profile_id")
        label = _safe_text(row.get("label"), "label")
        intent = _safe_text(row.get("intent"), "intent")
        raw_parameters = row.get("parameters")
        raw_guardrails = row.get("guardrails")
        if not isinstance(raw_parameters, Mapping) or set(raw_parameters) != set(_PARAMETERS):
            raise RiskProfileError("risk_profile_parameters_invalid")
        if not isinstance(raw_guardrails, Mapping) or set(raw_guardrails) != set(_PARAMETERS):
            raise RiskProfileError("risk_profile_guardrails_invalid")
        guardrails = tuple(
            (name, *_guardrail_bounds(raw_guardrails[name], name))
            for name in _PARAMETERS
        )
        values = _validated_parameters(raw_parameters, guardrails)
        profiles.append(
            RiskProfilePolicy(
                profile_id=profile_id,
                label=label,
                intent=intent,
                version=preset_version,
                parameters=tuple((name, values[name]) for name in _PARAMETERS),
                guardrails=guardrails,
                config_hash=config_hash,
            )
        )
    if tuple(item.label for item in profiles) != _EXPECTED_LABELS:
        raise RiskProfileError("risk_profile_preset_order_invalid")
    if len({item.profile_id for item in profiles}) != len(profiles):
        raise RiskProfileError("risk_profile_ids_not_unique")
    if payload.get("default_profile_id") != "medium" or not any(
        item.profile_id == payload.get("default_profile_id") for item in profiles
    ):
        raise RiskProfileError("risk_profile_default_invalid")
    _validate_profile_order(profiles)
    return tuple(profiles)


def risk_profile_preset_version(policy: RiskProfilePolicy) -> RiskProfileVersion:
    """Create immutable version 1 from one configured preset."""

    return _new_version(
        profile_id=policy.profile_id,
        label=policy.label,
        intent=policy.intent,
        version=policy.version,
        parameters=policy.parameters,
        guardrails=policy.guardrails,
        origin="preset",
    )


def edit_risk_profile(
    profile: RiskProfileVersion,
    edits: Mapping[str, object],
) -> RiskProfileVersion:
    """Return a new guarded version; the supplied preset/version is untouched."""

    if not isinstance(edits, Mapping) or not edits or set(edits) - set(_PARAMETERS):
        raise RiskProfileError("risk_profile_edits_invalid")
    parameters = dict(profile.parameters)
    parameters.update(edits)
    validated = _validated_parameters(parameters, profile.guardrails)
    return _new_version(
        profile_id=profile.profile_id,
        label=profile.label,
        intent=profile.intent,
        version=profile.version + 1,
        parameters=tuple((name, validated[name]) for name in _PARAMETERS),
        guardrails=profile.guardrails,
        origin="user_edit",
    )


def reset_risk_profile_to_preset(
    profile: RiskProfileVersion,
    preset: RiskProfilePolicy,
) -> RiskProfileVersion:
    """Create a new reset version while retaining all earlier profile versions."""

    if profile.profile_id != preset.profile_id:
        raise RiskProfileError("risk_profile_reset_identity_mismatch")
    return _new_version(
        profile_id=preset.profile_id,
        label=preset.label,
        intent=preset.intent,
        version=profile.version + 1,
        parameters=preset.parameters,
        guardrails=preset.guardrails,
        origin="reset_to_preset",
    )


def risk_profile_version_record(profile: RiskProfileVersion) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "label": profile.label,
        "intent": profile.intent,
        "version": profile.version,
        "parameters": dict(profile.parameters),
        "guardrails": {name: [lower, upper] for name, lower, upper in profile.guardrails},
        "origin": profile.origin,
        "policy_hash": profile.policy_hash,
    }


def risk_profile_version_from_record(value: object) -> RiskProfileVersion:
    """Verify a stored immutable profile version before replay."""

    if not isinstance(value, Mapping) or set(value) != {
        "profile_id", "label", "intent", "version", "parameters", "guardrails", "origin", "policy_hash"
    }:
        raise RiskProfileError("risk_profile_version_record_invalid")
    profile_id = _safe_text(value.get("profile_id"), "profile_id")
    label = _safe_text(value.get("label"), "label")
    intent = _safe_text(value.get("intent"), "intent")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise RiskProfileError("risk_profile_version_invalid")
    raw_guardrails = value.get("guardrails")
    raw_parameters = value.get("parameters")
    if not isinstance(raw_guardrails, Mapping) or set(raw_guardrails) != set(_PARAMETERS):
        raise RiskProfileError("risk_profile_guardrails_invalid")
    if not isinstance(raw_parameters, Mapping) or set(raw_parameters) != set(_PARAMETERS):
        raise RiskProfileError("risk_profile_parameters_invalid")
    guardrails = tuple((name, *_guardrail_bounds(raw_guardrails[name], name)) for name in _PARAMETERS)
    parameters = _validated_parameters(raw_parameters, guardrails)
    origin = value.get("origin")
    if origin not in {"preset", "user_edit", "reset_to_preset"}:
        raise RiskProfileError("risk_profile_origin_invalid")
    profile = _new_version(
        profile_id=profile_id,
        label=label,
        intent=intent,
        version=version,
        parameters=tuple((name, parameters[name]) for name in _PARAMETERS),
        guardrails=guardrails,
        origin=origin,
    )
    if value.get("policy_hash") != profile.policy_hash:
        raise RiskProfileError("risk_profile_version_hash_invalid")
    return profile


def project_risk_profile(
    profile: RiskProfileVersion,
    analysis: object,
    snapshot: object,
) -> ProfileProjection:
    """Project one version through canonical after-trade constraints.

    The risk-budget ratio is retained as an editable target. It is not converted
    into absolute risk limits without a saved VWCE distribution for the exact
    horizon and currency.
    """

    anchor = _vwce_anchor_snapshot(analysis)
    policy = validate_portfolio_policy(
        {
            "max_position_weight": dict(profile.parameters)["max_position_weight"],
            "max_sector_weight": dict(profile.parameters)["max_sector_weight"],
            "max_country_weight": dict(profile.parameters)["max_country_weight"],
            "max_currency_weight": dict(profile.parameters)["max_currency_weight"],
        },
        policy_id=f"risk-profile-{profile.profile_id}",
        version=profile.version,
    )
    scenario = build_what_if_scenario(analysis, snapshot, policy)
    scenario_record = what_if_record(scenario)
    constraints = tuple(
        dict(item)
        for item in scenario_record.get("constraints", ())
        if isinstance(item, Mapping)
    )
    blocking = tuple(
        str(item.get("constraint_id"))
        for item in constraints
        if item.get("blocking") is True
    )
    unavailable_constraints = tuple(
        str(item.get("constraint_id"))
        for item in constraints
        if item.get("status") == "unavailable"
    )
    if scenario.status == "blocked":
        eligibility_status: Literal["eligible", "blocked", "unavailable"] = "blocked"
        eligible: bool | None = False
        reasons = blocking or ("after_trade_policy_blocked",)
    elif scenario.status == "unavailable" or unavailable_constraints:
        eligibility_status = "unavailable"
        eligible = None
        reasons = unavailable_constraints or ("after_trade_scenario_unavailable",)
    elif anchor.status != "available":
        eligibility_status = "unavailable"
        eligible = None
        reasons = (anchor.reason or "vwce_anchor_unavailable",)
    else:
        # The canonical hierarchy supplies identity and alignment, but current
        # saved inputs do not supply the sealed VWCE risk distribution to score.
        eligibility_status = "unavailable"
        eligible = None
        reasons = ("vwce_risk_distribution_unavailable",)
    eligibility = ProfileEligibilityResult(
        profile_id=profile.profile_id,
        status=eligibility_status,
        eligible=eligible,
        rank=None,
        recommendation="unavailable",
        binding_reasons=reasons,
        constraints=constraints,
    )
    projection_status: Literal["partial", "unavailable"] = (
        "unavailable" if anchor.status != "available" else "partial"
    )
    projection_reason = anchor.reason if anchor.status != "available" else (
        "vwce_risk_distribution_unavailable"
    )
    profile_policy = policy_record(policy)
    profile_policy["risk_budget_ratio"] = dict(profile.parameters)["risk_budget_ratio"]
    profile_policy["risk_budget_status"] = "unavailable"
    profile_policy["risk_budget_reason"] = "vwce_risk_distribution_unavailable"
    source_hash = source_snapshot_hash(analysis)
    material = {
        "profile": risk_profile_version_record(profile),
        "source_snapshot_hash": source_hash,
        "vwce_anchor": asdict(anchor),
        "scenario": scenario_record,
        "eligibility": asdict(eligibility),
    }
    projection_id = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8")
    ).hexdigest()
    return ProfileProjection(
        status=projection_status,
        reason=projection_reason,
        profile=profile,
        profile_policy=profile_policy,
        vwce_anchor=anchor,
        eligibility=eligibility,
        scenario=scenario_record,
        source_snapshot_hash=source_hash,
        projection_id=projection_id,
    )


def replay_risk_profile_projection(
    profile_record: object,
    analysis: object,
    snapshot: object,
) -> dict[str, object]:
    """Recreate an advisory projection from its stored version and snapshot."""

    profile = risk_profile_version_from_record(profile_record)
    return project_risk_profile(profile, analysis, snapshot).to_record()


def build_risk_profile_workspace(
    snapshot: object,
    analysis: object,
    *,
    selected_profile_id: str = "medium",
    selected_version: object = None,
    version_history: Sequence[object] = (),
    profile_edits: Mapping[str, object] | None = None,
    reset_to_preset: bool = False,
    config_path: Path = RISK_PROFILE_CONFIG,
) -> dict[str, object]:
    """Return selected projection plus five comparable policy projections."""

    presets = load_risk_profile_presets(config_path)
    selected_policy = next((item for item in presets if item.profile_id == selected_profile_id), None)
    if selected_policy is None:
        raise RiskProfileError("risk_profile_selection_invalid")
    selected = (
        risk_profile_version_from_record(selected_version)
        if selected_version is not None
        else risk_profile_preset_version(selected_policy)
    )
    if selected.profile_id != selected_profile_id:
        raise RiskProfileError("risk_profile_selection_version_mismatch")
    history = [risk_profile_version_record(risk_profile_version_from_record(item)) for item in version_history]
    if profile_edits is not None and reset_to_preset:
        raise RiskProfileError("risk_profile_actions_conflict")
    if profile_edits is not None:
        history.append(risk_profile_version_record(selected))
        selected = edit_risk_profile(selected, profile_edits)
    elif reset_to_preset:
        history.append(risk_profile_version_record(selected))
        selected = reset_risk_profile_to_preset(selected, selected_policy)
    defaults = [risk_profile_preset_version(item) for item in presets]
    comparison: list[dict[str, object]] = []
    active_projection: ProfileProjection | None = None
    for default in defaults:
        version = selected if default.profile_id == selected_profile_id else default
        projection = project_risk_profile(version, analysis, snapshot)
        record = projection.to_record()
        comparison.append(
            {
                "profile_id": version.profile_id,
                "label": version.label,
                "risk_budget_ratio": dict(version.parameters)["risk_budget_ratio"],
                "eligibility": record["eligibility"],
                "projection_id": record["projection_id"],
            }
        )
        if version.profile_id == selected_profile_id:
            active_projection = projection
    if active_projection is None:
        raise RiskProfileError("risk_profile_selection_invalid")
    result = active_projection.to_record()
    result.update(
        {
            "comparison": comparison,
            "version_history": history,
            "version_history_persistence": {
                "status": "unavailable",
                "reason": "risk_profile_persistent_store_unavailable",
            },
            "execution_allowed": False,
        }
    )
    return result


def unavailable_risk_profile_workspace(reason: str) -> dict[str, object]:
    """Return a compact fail-closed envelope for the presentation facade."""

    return {
        "contract": "profile-projection.v1",
        "status": "unavailable",
        "reason": reason,
        "profile": None,
        "profile_policy": {"status": "unavailable", "reason": reason},
        "vwce_anchor": asdict(_unavailable_anchor(reason)),
        "eligibility": {
            "status": "unavailable",
            "eligible": None,
            "rank": None,
            "recommendation": "unavailable",
            "binding_reasons": [reason],
            "constraints": [],
        },
        "scenario": {"status": "unavailable", "reason": reason, "execution_allowed": False},
        "source_snapshot_hash": None,
        "projection_id": None,
        "comparison": [],
        "version_history": [],
        "version_history_persistence": {
            "status": "unavailable",
            "reason": "risk_profile_persistent_store_unavailable",
        },
        "execution_allowed": False,
    }


def _vwce_anchor_snapshot(analysis: object) -> VWCEAnchorSnapshot:
    evidence = getattr(analysis, "service_evidence", None)
    relative = evidence.get("profile_relative") if isinstance(evidence, Mapping) else None
    relative = relative if isinstance(relative, Mapping) else {}
    raw_resolution = relative.get("anchor_resolution")
    resolution_present = isinstance(raw_resolution, Mapping)
    resolution = raw_resolution if resolution_present else {}
    relative_reason = relative.get("anchor_reason")
    reason = (
        str(relative_reason)
        if relative_reason
        else str(resolution.get("reason"))
        if resolution.get("reason")
        else "vwce_anchor_resolution_unavailable"
    )
    resolved = (
        relative.get("profile_relative_status") == "available"
        and relative.get("profile_relative_claims_allowed") is True
        and resolution.get("status") == "available"
        and resolution.get("execution_allowed") is False
    )
    required = (
        "canonical_share_class_id", "listing_id", "effective_date", "knowledge_cutoff",
        "output_currency", "horizon_years", "anchor_digest", "resolution_digest",
    )
    if any(resolution.get(name) is None for name in required):
        resolved = False
        if resolution_present and reason == "vwce_anchor_resolution_unavailable":
            reason = "vwce_anchor_resolution_incomplete"
    metrics = tuple(
        (name, _RISK_METRIC_REASONS[name])
        for name in _RISK_METRICS
    )
    return VWCEAnchorSnapshot(
        status="available" if resolved else "unavailable",
        reason=None if resolved else reason,
        canonical_share_class_id=_optional_text(resolution.get("canonical_share_class_id")),
        listing_id=_optional_text(resolution.get("listing_id")),
        effective_date=_optional_text(resolution.get("effective_date")),
        knowledge_cutoff=_optional_text(resolution.get("knowledge_cutoff")),
        output_currency=_optional_text(resolution.get("output_currency")),
        horizon_years=_optional_number(resolution.get("horizon_years")),
        anchor_digest=_optional_text(resolution.get("anchor_digest")),
        resolution_digest=_optional_text(resolution.get("resolution_digest")),
        risk_envelope_status="unavailable",
        risk_metrics=metrics,
    )


def _unavailable_anchor(reason: str) -> VWCEAnchorSnapshot:
    return VWCEAnchorSnapshot(
        status="unavailable",
        reason=reason,
        canonical_share_class_id=None,
        listing_id=None,
        effective_date=None,
        knowledge_cutoff=None,
        output_currency=None,
        horizon_years=None,
        anchor_digest=None,
        resolution_digest=None,
        risk_envelope_status="unavailable",
        risk_metrics=tuple((name, reason) for name in _RISK_METRICS),
    )


def _new_version(
    *,
    profile_id: str,
    label: str,
    intent: str,
    version: int,
    parameters: tuple[tuple[str, float], ...],
    guardrails: tuple[tuple[str, float, float], ...],
    origin: Literal["preset", "user_edit", "reset_to_preset"],
) -> RiskProfileVersion:
    material = {
        "profile_id": profile_id,
        "label": label,
        "intent": intent,
        "version": version,
        "parameters": dict(parameters),
        "guardrails": {name: [lower, upper] for name, lower, upper in guardrails},
        "origin": origin,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return RiskProfileVersion(
        profile_id=profile_id,
        label=label,
        intent=intent,
        version=version,
        parameters=parameters,
        guardrails=guardrails,
        origin=origin,
        policy_hash=digest,
    )


def _validated_parameters(
    values: Mapping[str, object],
    guardrails: tuple[tuple[str, float, float], ...],
) -> dict[str, float]:
    if set(values) != set(_PARAMETERS):
        raise RiskProfileError("risk_profile_parameters_invalid")
    bounds = {name: (lower, upper) for name, lower, upper in guardrails}
    if set(bounds) != set(_PARAMETERS):
        raise RiskProfileError("risk_profile_guardrails_invalid")
    result: dict[str, float] = {}
    for name in _PARAMETERS:
        value = values[name]
        if isinstance(value, bool):
            raise RiskProfileError(f"risk_profile_parameter_invalid:{name}")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RiskProfileError(f"risk_profile_parameter_invalid:{name}") from exc
        lower, upper = bounds[name]
        if not math.isfinite(number) or number < lower or number > upper:
            raise RiskProfileError(f"risk_profile_parameter_outside_guardrails:{name}")
        result[name] = number
    return result


def _guardrail_bounds(value: object, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise RiskProfileError(f"risk_profile_guardrail_invalid:{name}")
    lower, upper = value
    if isinstance(lower, bool) or isinstance(upper, bool):
        raise RiskProfileError(f"risk_profile_guardrail_invalid:{name}")
    try:
        low_number, high_number = float(lower), float(upper)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RiskProfileError(f"risk_profile_guardrail_invalid:{name}") from exc
    if (
        not math.isfinite(low_number)
        or not math.isfinite(high_number)
        or low_number < 0
        or low_number >= high_number
        or high_number > 1.5
    ):
        raise RiskProfileError(f"risk_profile_guardrail_invalid:{name}")
    return low_number, high_number


def _validate_profile_order(profiles: Sequence[RiskProfilePolicy]) -> None:
    if len(profiles) != len(_EXPECTED_LABELS):
        raise RiskProfileError("risk_profile_presets_incomplete")
    for field in _PARAMETERS:
        values = [dict(item.parameters)[field] for item in profiles]
        ranges = [{name: (lower, upper) for name, lower, upper in item.guardrails}[field] for item in profiles]
        if any(left >= right for left, right in zip(values, values[1:])):
            raise RiskProfileError(f"risk_profile_envelope_not_ordered:{field}")
        if any(left[1] >= right[0] for left, right in zip(ranges, ranges[1:])):
            raise RiskProfileError(f"risk_profile_guardrails_not_ordered:{field}")


def _safe_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise RiskProfileError(f"risk_profile_text_invalid:{field}")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "ProfileEligibilityResult",
    "ProfileProjection",
    "RiskProfileError",
    "RiskProfilePolicy",
    "RiskProfileVersion",
    "VWCEAnchorSnapshot",
    "build_risk_profile_workspace",
    "edit_risk_profile",
    "load_risk_profile_presets",
    "project_risk_profile",
    "replay_risk_profile_projection",
    "reset_risk_profile_to_preset",
    "risk_profile_preset_version",
    "risk_profile_version_from_record",
    "risk_profile_version_record",
    "unavailable_risk_profile_workspace",
]
