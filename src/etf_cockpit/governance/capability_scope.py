"""Deterministic strategy and instrument capability resolution.

The matrix is descriptive and fail-closed.  It can expose research, portfolio,
backtest and paper eligibility, but every decision retains
``execution_allowed=False`` and no resolver grants broker authority.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from etf_cockpit.governance.models import (
    AssetFamily,
    CapabilityPrerequisites,
    CapabilitySupportState,
    ImmutableModel,
    LongOnlyAction,
    StrategyCapabilityStage,
    StrategyScopePolicy,
    STRATEGY_CAPABILITY_STAGES,
)


CAPABILITY_STAGES = STRATEGY_CAPABILITY_STAGES
Horizon = Literal["1W", "1M", "3M", "6M", "9M", "2Y", "5Y"]


class InstrumentDescriptor(ImmutableModel):
    """Provider-neutral classification evidence used by the scope resolver."""

    asset_type: str = ""
    security_type: str = ""
    cfi_code: str = ""
    exchange: str = ""
    leveraged: bool = False
    inverse: bool = False
    derivative: bool = False
    crypto: bool = False
    otc: bool = False
    complex_structured: bool = False
    market_cap_usd: float | None = Field(default=None, ge=0)
    average_daily_value_usd: float | None = Field(default=None, ge=0)
    dealing_frequency: Literal["intraday", "daily", "weekly", "monthly", "unknown"] = "unknown"


class StrategyCapabilityDecision(ImmutableModel):
    strategy_id: str
    stage: StrategyCapabilityStage
    state: CapabilitySupportState
    reason_code: str
    prerequisites: CapabilityPrerequisites
    execution_allowed: Literal[False] = False


class InstrumentCapabilityDecision(ImmutableModel):
    asset_family: AssetFamily | Literal["unknown"]
    stage: StrategyCapabilityStage
    horizon: Horizon
    state: CapabilitySupportState
    reason_code: str
    prerequisites: CapabilityPrerequisites
    allowed_actions: tuple[LongOnlyAction, ...] = ()
    execution_allowed: Literal[False] = False


def _empty_prerequisites() -> CapabilityPrerequisites:
    return CapabilityPrerequisites(data=(), models=(), liquidity=(), broker=(), legal=())


def _merge_prerequisites(base: CapabilityPrerequisites, *, required_data: tuple[str, ...] = ()) -> CapabilityPrerequisites:
    return base.model_copy(update={"data": tuple(dict.fromkeys((*required_data, *base.data)))})


def resolve_strategy_capability(
    policy: StrategyScopePolicy,
    *,
    strategy_id: str,
    stage: StrategyCapabilityStage,
) -> StrategyCapabilityDecision:
    """Resolve one strategy/stage cell without interpreting it in presentation."""

    entries = {entry.strategy_id: entry for entry in policy.entries}
    entry = entries.get(strategy_id)
    if entry is None:
        return StrategyCapabilityDecision(
            strategy_id=strategy_id,
            stage=stage,
            state="rejected",
            reason_code="UNKNOWN_STRATEGY",
            prerequisites=_empty_prerequisites(),
        )
    profiles = {profile.profile_id: profile for profile in policy.capability_profiles}
    profile = profiles.get(entry.capability_profile)
    if profile is None:
        return StrategyCapabilityDecision(
            strategy_id=strategy_id,
            stage=stage,
            state="rejected",
            reason_code="UNKNOWN_STRATEGY_CAPABILITY_PROFILE",
            prerequisites=_empty_prerequisites(),
        )
    cell = profile.cells[stage]
    return StrategyCapabilityDecision(
        strategy_id=strategy_id,
        stage=stage,
        state=cell.state,
        reason_code=cell.reason_code,
        prerequisites=_merge_prerequisites(cell.prerequisites, required_data=entry.required_data),
    )


def _rejected_instrument(
    *,
    stage: StrategyCapabilityStage,
    horizon: Horizon,
    reason_code: str,
    state: CapabilitySupportState = "rejected",
    asset_family: AssetFamily | Literal["unknown"] = "unknown",
    prerequisites: CapabilityPrerequisites | None = None,
) -> InstrumentCapabilityDecision:
    return InstrumentCapabilityDecision(
        asset_family=asset_family,
        stage=stage,
        horizon=horizon,
        state=state,
        reason_code=reason_code,
        prerequisites=prerequisites or _empty_prerequisites(),
        allowed_actions=(),
    )


def _classification_evidence(
    policy: StrategyScopePolicy,
    descriptor: InstrumentDescriptor,
) -> tuple[set[AssetFamily], tuple[str, ...]]:
    signals = (
        ("asset_type", descriptor.asset_type.strip().casefold(), "match_asset_types", False),
        ("security_type", descriptor.security_type.strip().casefold(), "match_security_types", False),
        ("cfi_code", descriptor.cfi_code.strip().upper(), "match_cfi_prefixes", True),
    )
    families: set[AssetFamily] = set()
    unresolved: list[str] = []
    for label, value, field_name, prefix_match in signals:
        if not value:
            continue
        matches: set[AssetFamily] = set()
        for rule in policy.instrument_rules:
            rule_values = getattr(rule, field_name)
            if prefix_match:
                matched = any(value.startswith(item.upper()) for item in rule_values)
            else:
                matched = value in {item.casefold() for item in rule_values}
            if matched:
                matches.add(rule.asset_family)
        if matches:
            families.update(matches)
        else:
            unresolved.append(label)
    return families, tuple(unresolved)


def resolve_instrument_capability(
    policy: StrategyScopePolicy,
    descriptor: InstrumentDescriptor,
    *,
    stage: StrategyCapabilityStage,
    horizon: Horizon,
    risk_profile: str | None = None,
) -> InstrumentCapabilityDecision:
    """Resolve one instrument from explicit classification and safety evidence.

    ``risk_profile`` is accepted only to make the non-override contract
    explicit: product-class exclusions and capability states are invariant to
    it.
    """

    _ = risk_profile
    exclusion = policy.exclusion_policy
    protected_flags = (
        (descriptor.leveraged, "EXCLUDED_LEVERAGED_PRODUCT"),
        (descriptor.inverse, "EXCLUDED_INVERSE_PRODUCT"),
        (descriptor.derivative, "EXCLUDED_DERIVATIVE_PRODUCT"),
        (descriptor.crypto, "EXCLUDED_CRYPTO_PRODUCT"),
        (descriptor.otc, "EXCLUDED_OTC_PRODUCT"),
        (descriptor.complex_structured, "EXCLUDED_COMPLEX_STRUCTURED_PRODUCT"),
    )
    for active, reason_code in protected_flags:
        if active:
            return _rejected_instrument(stage=stage, horizon=horizon, reason_code=reason_code)
    if descriptor.exchange.strip().upper() in {exchange.upper() for exchange in exclusion.excluded_exchanges}:
        return _rejected_instrument(stage=stage, horizon=horizon, reason_code="EXCLUDED_OTC_EXCHANGE")
    if descriptor.market_cap_usd is not None and descriptor.market_cap_usd < exclusion.minimum_market_cap_usd:
        return _rejected_instrument(stage=stage, horizon=horizon, reason_code="EXCLUDED_MICROCAP")
    if descriptor.average_daily_value_usd is not None and descriptor.average_daily_value_usd < exclusion.minimum_average_daily_value_usd:
        return _rejected_instrument(stage=stage, horizon=horizon, reason_code="EXCLUDED_ILLIQUID_INSTRUMENT")

    families, unresolved_classifiers = _classification_evidence(policy, descriptor)
    if not families:
        return _rejected_instrument(stage=stage, horizon=horizon, reason_code="UNKNOWN_INSTRUMENT_CLASSIFICATION")
    if unresolved_classifiers:
        reason_code = {
            "asset_type": "UNKNOWN_ASSET_TYPE",
            "security_type": "UNKNOWN_SECURITY_TYPE",
            "cfi_code": "UNKNOWN_CFI_CLASSIFICATION",
        }[unresolved_classifiers[0]]
        return _rejected_instrument(stage=stage, horizon=horizon, reason_code=reason_code)
    if len(families) != 1:
        return _rejected_instrument(stage=stage, horizon=horizon, reason_code="CONFLICTING_INSTRUMENT_CLASSIFICATION")

    family = next(iter(families))
    rule = next(rule for rule in policy.instrument_rules if rule.asset_family == family)
    if "minimum_market_cap" in rule.prerequisites.liquidity and descriptor.market_cap_usd is None:
        return _rejected_instrument(
            stage=stage,
            horizon=horizon,
            state="unavailable",
            asset_family=family,
            reason_code="MARKET_CAP_EVIDENCE_MISSING",
            prerequisites=rule.prerequisites,
        )
    if "minimum_average_daily_value" in rule.prerequisites.liquidity and descriptor.average_daily_value_usd is None:
        return _rejected_instrument(
            stage=stage,
            horizon=horizon,
            state="unavailable",
            asset_family=family,
            reason_code="LIQUIDITY_EVIDENCE_MISSING",
            prerequisites=rule.prerequisites,
        )
    if family == "ordinary_fund" and descriptor.dealing_frequency == "unknown":
        return _rejected_instrument(
            stage=stage,
            horizon=horizon,
            state="unavailable",
            asset_family=family,
            reason_code="DEALING_FREQUENCY_UNKNOWN",
            prerequisites=rule.prerequisites,
        )
    if family == "ordinary_fund" and horizon == "1W" and descriptor.dealing_frequency not in {"intraday", "daily"}:
        return _rejected_instrument(
            stage=stage,
            horizon=horizon,
            state="unavailable",
            asset_family=family,
            reason_code="HORIZON_UNSUPPORTED_FOR_DEALING_FREQUENCY",
            prerequisites=rule.prerequisites,
        )
    if horizon not in rule.horizons:
        return _rejected_instrument(
            stage=stage,
            horizon=horizon,
            state="unavailable",
            asset_family=family,
            reason_code="HORIZON_UNSUPPORTED_FOR_ASSET_FAMILY",
            prerequisites=rule.prerequisites,
        )
    if stage not in rule.stages:
        return _rejected_instrument(
            stage=stage,
            horizon=horizon,
            state="unavailable",
            asset_family=family,
            reason_code="CAPABILITY_STAGE_UNAVAILABLE",
            prerequisites=rule.prerequisites,
        )
    return InstrumentCapabilityDecision(
        asset_family=family,
        stage=stage,
        horizon=horizon,
        state=rule.state,
        reason_code=rule.reason_code,
        prerequisites=rule.prerequisites,
        allowed_actions=rule.allowed_actions,
    )


def strategy_capability_export(policy: StrategyScopePolicy) -> dict[str, object]:
    """Return the canonical resolved matrix for UI/audit consumers."""

    strategy_rows = []
    for entry in policy.entries:
        for stage in CAPABILITY_STAGES:
            row = resolve_strategy_capability(policy, strategy_id=entry.strategy_id, stage=stage).model_dump(mode="json")
            row.update(
                {
                    "name": entry.name,
                    "lifecycle": entry.lifecycle,
                    "authority": entry.authority,
                    "ui_visibility": entry.ui_visibility,
                    "required_data": list(entry.required_data),
                    "tests": list(entry.tests),
                    "score_authority": entry.score_authority,
                    "paper_authority": entry.paper_authority,
                    "live_authority": False,
                }
            )
            strategy_rows.append(row)
    instrument_rows = [rule.model_dump(mode="json") for rule in policy.instrument_rules]
    instrument_stage_rows = []
    for rule in policy.instrument_rules:
        for stage in CAPABILITY_STAGES:
            available = stage in rule.stages
            instrument_stage_rows.append(
                {
                    "asset_family": rule.asset_family,
                    "stage": stage,
                    "state": rule.state if available else "unavailable",
                    "reason_code": rule.reason_code if available else f"INSTRUMENT_STAGE_{stage.upper()}_UNAVAILABLE",
                    "prerequisites": rule.prerequisites.model_dump(mode="json"),
                    "allowed_actions": list(rule.allowed_actions) if available else [],
                    "execution_allowed": False,
                }
            )
    return {
        "schema_version": policy.schema_version,
        "matrix_version": policy.matrix_version,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_checksum": policy.checksum,
        "execution_allowed": False,
        "long_only_actions": ["buy_add", "hold", "avoid_no_trade", "trim_sell", "manual_review"],
        "strategy_matrix": strategy_rows,
        "instrument_matrix": instrument_rows,
        "instrument_stage_matrix": instrument_stage_rows,
        "exclusion_policy": policy.exclusion_policy.model_dump(mode="json"),
    }


__all__ = [
    "CAPABILITY_STAGES",
    "InstrumentCapabilityDecision",
    "InstrumentDescriptor",
    "StrategyCapabilityDecision",
    "resolve_instrument_capability",
    "resolve_strategy_capability",
    "strategy_capability_export",
]
