"""Immutable, checksum-bearing governance policy contracts.

The governance files are deliberately represented by small, strict Pydantic
models.  A policy can describe advisory research and review authority, but the
execution boundary is encoded as ``Literal[False]`` in every model so a YAML
value cannot opt the application into an executable mode.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_serializer, field_validator, model_validator

from etf_cockpit.signals.research_states import (
    AuthorityDecision,
    GateResult,
    GateSeverity as GateSeverityEnum,
    InternalSignalIntent,
    PortfolioReviewState,
    ResearchState as PublicResearchState,
    ScoreComponent,
)


SCHEMA_VERSION = "1.0"
STRATEGY_SCOPE_SCHEMA_VERSION = "2.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})
Checksum = str
Lifecycle = Literal[
    "supported",
    "supported_with_limitations",
    "experimental",
    "research_only",
    "future_only",
    "rejected",
]
Authority = Literal[
    "evidence_only",
    "context_only",
    "research_state",
    "portfolio_review",
    "user_record",
    "none",
]
AuthorityStage = Literal[
    "research",
    "shadow_proposal",
    "paper",
    "broker_read_only",
    "draft_order",
    "capped_automatic",
    "disabled",
]
CapabilityKind = Literal["route", "dataset", "model", "strategy", "broker"]
StrategyCapabilityStage = Literal[
    "analyse",
    "portfolio",
    "backtest",
    "paper",
    "draft_order",
    "canary",
    "bounded_automatic",
]
CapabilitySupportState = Literal[
    "supported",
    "supported_with_limitations",
    "research_only",
    "unavailable",
    "rejected",
]
AssetFamily = Literal[
    "stock",
    "etf",
    "bond_etf",
    "ordinary_fund",
    "fixed_rate_bond",
    "zero_coupon_bond",
    "floating_rate_bond",
    "inflation_linked_bond",
    "callable_bond",
    "cash",
    "fx",
]
LongOnlyAction = Literal["buy_add", "hold", "avoid_no_trade", "trim_sell", "manual_review"]
STRATEGY_CAPABILITY_STAGES: tuple[StrategyCapabilityStage, ...] = (
    "analyse",
    "portfolio",
    "backtest",
    "paper",
    "draft_order",
    "canary",
    "bounded_automatic",
)
REQUIRED_ASSET_FAMILIES: frozenset[AssetFamily] = frozenset(
    {
        "stock",
        "etf",
        "bond_etf",
        "ordinary_fund",
        "fixed_rate_bond",
        "zero_coupon_bond",
        "floating_rate_bond",
        "inflation_linked_bond",
        "callable_bond",
        "cash",
        "fx",
    }
)
# Compatibility aliases for Task 1 policy callers.  The public values now
# come from the dedicated v2 state module and remain string-compatible.
ResearchState = PublicResearchState
GateSeverity = GateSeverityEnum

# These are the policy terms and gate identifiers required by GOV-01.4-GOV-01.7.
# Keeping the lists in the typed contract makes completeness checks deterministic
# and gives loaders a single source of truth.
REQUIRED_GATE_IDS = (
    "identity",
    "data_quality",
    "evidence",
    "model_validity",
    "risk",
    "valuation",
    "signal",
    "portfolio_fit",
    "cost",
)
REQUIRED_GLOSSARY_TERMS = frozenset(
    {
        "alpha",
        "beta",
        "drawdown",
        "calibration",
        "pbo",
        "dsr",
        "mase",
        "slippage",
        "edge-to-cost",
        "evidence authority",
        "freshness",
        "research state",
        "portfolio-review state",
        "blocker",
        "authority-warning",
        "notice",
        "volatility",
        "liquidity/spread proxy",
        "confidence interval/quantile",
        "walk-forward",
        "purging/embargo",
        "model promotion",
        "forecast-error measures",
        "n/a versus zero",
        "source conflict",
    }
)


class ImmutableModel(BaseModel):
    """Base contract for policy data loaded from local YAML."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class AuthorityPolicy(ImmutableModel):
    """The non-executable authority boundary shared by governance policies."""

    execution_allowed: Literal[False] = False
    executable_authority: Literal[False] = False
    order_transmission: Literal[False] = False
    external_upload: Literal[False] = False
    credential_access: Literal[False] = False
    maximum_operational_authority: Literal["manual_research"] = "manual_research"
    broker_execution: Literal["forbidden"] = "forbidden"
    autonomous_portfolio_management: Literal[False] = False
    unvalidated_ai_score_authority: Literal[False] = False


class AuthorityStageDefinition(ImmutableModel):
    """One named product stage in the finite authority ladder."""

    stage_id: AuthorityStage
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    enabled_by_default: bool = False
    execution_allowed: Literal[False] = False


class AuthorityCapability(ImmutableModel):
    """A route, source, model, strategy or broker capability declaration."""

    capability_id: str = Field(min_length=1)
    kind: CapabilityKind
    authority_stage: AuthorityStage
    description: str = Field(min_length=1)
    required_evidence: tuple[str, ...] = ()
    required_approvals: tuple[str, ...] = ()
    max_quantity_delta: float | None = Field(default=None, gt=0)
    availability: Literal["mandatory", "optional", "future", "disabled"] = "mandatory"
    execution_allowed: Literal[False] = False

    @field_validator("required_approvals")
    @classmethod
    def validate_required_approvals(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("required approvals must be non-empty strings")
        if len(value) != len(set(value)):
            raise ValueError("required approvals must be unique")
        return value


class ProductDefinition(ImmutableModel):
    canonical_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    intended_user: str = Field(min_length=1)
    default_horizon: str = Field(min_length=1)
    decision_owner: Literal["user"] = "user"


class PolicyModel(ImmutableModel):
    """Common metadata and immutable execution boundary for a policy."""

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    execution_allowed: Literal[False] = False
    executable_authority: Literal[False] = False
    checksum: str = "unavailable"

    @field_validator("checksum")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        if value == "unavailable":
            return value
        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("checksum must be a SHA-256 hexadecimal digest")
        return value.lower()


class AuthorityMatrixPolicy(PolicyModel):
    """Versioned scope, capability and authority closure contract."""

    adr_id: str = Field(min_length=1)
    adr_path: str = Field(min_length=1)
    mandatory_core: tuple[str, ...] = ()
    optional_enrichment: tuple[str, ...] = ()
    authority_stages: tuple[AuthorityStageDefinition, ...] = ()
    capabilities: tuple[AuthorityCapability, ...] = ()
    completion_contract: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_matrix(self) -> AuthorityMatrixPolicy:
        stage_ids = tuple(stage.stage_id for stage in self.authority_stages)
        capability_ids = tuple(capability.capability_id for capability in self.capabilities)
        required_stages = {
            "research",
            "shadow_proposal",
            "paper",
            "broker_read_only",
            "draft_order",
            "capped_automatic",
            "disabled",
        }
        if set(stage_ids) != required_stages:
            raise ValueError("authority matrix must declare the complete authority stage set")
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("authority stage identifiers must be unique")
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("capability identifiers must be unique")
        if not self.mandatory_core or not self.completion_contract:
            raise ValueError("authority matrix requires mandatory_core and completion_contract")
        if tuple(stage.stage_id for stage in self.authority_stages if stage.enabled_by_default) != ("research",):
            raise ValueError("only the research authority stage may be enabled by default")
        return self


class ProductGovernancePolicy(PolicyModel):
    """Top-level product authority and fail-closed defaults."""

    product: ProductDefinition
    authority: AuthorityPolicy
    prohibited_claims: tuple[str, ...] = ()
    required_disclosures: tuple[str, ...] = ()
    default_research_state: str = "research_candidate"
    default_portfolio_review_state: str = "not_applicable"

    @model_validator(mode="after")
    def validate_authority_boundary(self) -> ProductGovernancePolicy:
        for field_name in (
            "execution_allowed",
            "executable_authority",
        ):
            if getattr(self, field_name) is not False or getattr(self.authority, field_name) is not False:
                raise ValueError(f"{field_name} must remain false")
        return self


class FeatureRegistryEntry(ImmutableModel):
    """One user-visible feature or production route."""

    feature_id: str = Field(default="unnamed", min_length=1)
    # ``route``/``required_data``/``title`` are retained as typed compatibility
    # aliases for the first Task 1 implementation. New policy files use the
    # plural/more explicit contract fields below.
    route: str = ""
    routes: tuple[str, ...] = ()
    name: str = ""
    category: str = ""
    title: str = ""
    lifecycle: Lifecycle = "supported"
    authority: Authority = "none"
    data_dependencies: tuple[str, ...] = ()
    required_data: tuple[str, ...] = ()
    issue_ids: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    export_contracts: tuple[str, ...] = ()
    package_gate: str = ""
    limitations: tuple[str, ...] = ()
    visible: bool = True
    score_authority: bool = False
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    execution_allowed: Literal[False] = False

    @field_validator("route")
    @classmethod
    def validate_route(cls, value: str) -> str:
        if value and not value.startswith("/"):
            raise ValueError("route must start with '/'")
        return value

    @field_validator("routes")
    @classmethod
    def validate_routes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not route.startswith("/") for route in value):
            raise ValueError("routes must start with '/'")
        return value

    @property
    def canonical_routes(self) -> tuple[str, ...]:
        """Return routes using the plural contract with legacy fallback."""

        return self.routes or ((self.route,) if self.route else ())

    @model_validator(mode="after")
    def validate_lifecycle_authority(self) -> FeatureRegistryEntry:
        if self.lifecycle in {"experimental", "research_only", "future_only", "rejected"} and (
            self.score_authority or self.research_promotion_allowed or self.portfolio_review_allowed
        ):
            raise ValueError("lifecycle does not permit positive authority")
        if self.authority == "none" and (
            self.score_authority or self.research_promotion_allowed or self.portfolio_review_allowed
        ):
            raise ValueError("authority 'none' cannot carry positive authority flags")
        if self.portfolio_review_allowed and self.authority != "portfolio_review":
            raise ValueError("portfolio_review authority is required for portfolio_review_allowed")
        if (self.score_authority or self.research_promotion_allowed) and self.authority not in {
            "research_state",
            "portfolio_review",
        }:
            raise ValueError("research_state or portfolio_review authority is required for score/promotion flags")
        if self.route and self.routes and self.route not in self.routes:
            raise ValueError("route must be present in routes")
        return self


class FeatureRegistryPolicy(PolicyModel):
    """Registry of routes and visible product subsystems."""

    entries: tuple[FeatureRegistryEntry, ...] = ()

    @model_validator(mode="after")
    def validate_unique_features_and_routes(self) -> FeatureRegistryPolicy:
        feature_ids = [entry.feature_id for entry in self.entries]
        routes = [route for entry in self.entries for route in entry.canonical_routes]
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("feature_id values must be unique")
        if len(routes) != len(set(routes)):
            raise ValueError("route values must be unique")
        return self


class CapabilityPrerequisites(ImmutableModel):
    """Evidence and authority prerequisites for one capability cell."""

    data: tuple[str, ...]
    models: tuple[str, ...]
    liquidity: tuple[str, ...]
    broker: tuple[str, ...]
    legal: tuple[str, ...]

    @model_validator(mode="after")
    def validate_unique_prerequisites(self) -> CapabilityPrerequisites:
        for field_name in ("data", "models", "liquidity", "broker", "legal"):
            values = getattr(self, field_name)
            if any(not value for value in values) or len(values) != len(set(values)):
                raise ValueError(f"{field_name} prerequisites must contain unique non-empty values")
        return self


class StrategyCapabilityCell(ImmutableModel):
    """One explicit strategy/stage decision in the scope matrix."""

    state: CapabilitySupportState
    reason_code: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]+$")
    prerequisites: CapabilityPrerequisites
    execution_allowed: Literal[False] = False


class StrategyCapabilityProfile(ImmutableModel):
    """Reusable seven-stage profile referenced by one or more strategies."""

    profile_id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]+$")
    cells: dict[StrategyCapabilityStage, StrategyCapabilityCell]

    @model_validator(mode="after")
    def validate_complete_stage_set(self) -> StrategyCapabilityProfile:
        if tuple(self.cells) != STRATEGY_CAPABILITY_STAGES:
            raise ValueError("strategy capability profiles must declare the complete ordered stage set")
        for stage in ("draft_order", "canary", "bounded_automatic"):
            if self.cells[stage].state not in {"unavailable", "rejected"}:
                raise ValueError("execution-stage capability cells must remain unavailable or rejected")
        object.__setattr__(self, "cells", MappingProxyType(dict(self.cells)))
        return self

    @field_serializer("cells")
    def serialize_cells(self, value: dict[StrategyCapabilityStage, StrategyCapabilityCell]) -> dict[str, object]:
        return {stage: cell.model_dump(mode="json") for stage, cell in value.items()}


class InstrumentCapabilityRule(ImmutableModel):
    """Fail-closed instrument classification and stage/horizon scope rule."""

    rule_id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]+$")
    asset_family: AssetFamily
    match_asset_types: tuple[str, ...] = ()
    match_security_types: tuple[str, ...] = ()
    match_cfi_prefixes: tuple[str, ...] = ()
    state: CapabilitySupportState
    reason_code: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]+$")
    stages: tuple[StrategyCapabilityStage, ...]
    horizons: tuple[Literal["1W", "1M", "3M", "6M", "9M", "2Y", "5Y"], ...]
    prerequisites: CapabilityPrerequisites
    allowed_actions: tuple[LongOnlyAction, ...] = ()
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_instrument_rule(self) -> InstrumentCapabilityRule:
        match_fields = (self.match_asset_types, self.match_security_types, self.match_cfi_prefixes)
        if not any(match_fields):
            raise ValueError("instrument capability rule requires at least one classifier")
        for values in (*match_fields, self.stages, self.horizons, self.allowed_actions):
            if len(values) != len(set(values)):
                raise ValueError("instrument capability rule values must be unique")
        if any(stage in {"draft_order", "canary", "bounded_automatic"} for stage in self.stages):
            raise ValueError("instrument capability rules cannot enable execution stages")
        if self.state in {"unavailable", "rejected"} and self.allowed_actions:
            raise ValueError("unavailable or rejected instruments cannot expose actions")
        return self


class InstrumentExclusionPolicy(ImmutableModel):
    """Versioned safe bounds that no risk profile may override."""

    policy_version: str = Field(min_length=1)
    minimum_market_cap_usd: float = Field(ge=50_000_000, le=2_000_000_000)
    minimum_average_daily_value_usd: float = Field(ge=100_000, le=10_000_000)
    excluded_exchanges: tuple[str, ...] = ()
    excluded_product_flags: tuple[
        Literal["leveraged", "inverse", "derivative", "crypto", "otc", "complex_structured"], ...
    ]
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_exclusion_policy(self) -> InstrumentExclusionPolicy:
        if len(self.excluded_exchanges) != len(set(self.excluded_exchanges)):
            raise ValueError("excluded exchanges must be unique")
        required = {"leveraged", "inverse", "derivative", "crypto", "otc", "complex_structured"}
        if set(self.excluded_product_flags) != required:
            raise ValueError("exclusion policy must declare every protected product flag")
        return self


class StrategyScopeEntry(ImmutableModel):
    """Strategy lifecycle and the authority that strategy may contribute."""

    strategy_id: str = Field(default="unnamed", min_length=1)
    name: str = ""
    lifecycle: Lifecycle = "supported"
    asset_scope: Literal["etf", "stock", "mixed", "general"] = "general"
    authority: Authority = "none"
    intended_use: str = ""
    permitted_authority: Authority | None = None
    execution_authority: Literal["none"] = "none"
    score_authority: bool = False
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    paper_authority: bool = False
    required_data: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    linked_issues: tuple[str, ...] = ()
    promotion_conditions: tuple[str, ...] = ()
    rejection_reason: str = ""
    tests: tuple[str, ...] = ()
    capability_profile: str = ""
    ui_visibility: Literal["system_map"] = "system_map"
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_strategy_authority(self) -> StrategyScopeEntry:
        if self.permitted_authority is not None and self.authority != "none" and self.authority != self.permitted_authority:
            raise ValueError("authority and permitted_authority must agree")
        effective_authority = self.permitted_authority or self.authority
        if self.lifecycle in {"rejected", "future_only"}:
            lifecycle_label = "rejected" if self.lifecycle == "rejected" else "future-only"
            if self.paper_authority:
                raise ValueError(f"{lifecycle_label} strategies cannot have paper_authority")
            if self.score_authority:
                detail = "score_authority or authority" if self.lifecycle == "rejected" else "score_authority"
                raise ValueError(f"{lifecycle_label} strategies cannot have {detail}")
            if self.research_promotion_allowed:
                detail = "research_promotion_allowed or authority" if self.lifecycle == "rejected" else "research_promotion_allowed"
                raise ValueError(f"{lifecycle_label} strategies cannot have {detail}")
            if self.portfolio_review_allowed:
                detail = "portfolio_review_allowed or authority" if self.lifecycle == "rejected" else "portfolio_review_allowed"
                raise ValueError(f"{lifecycle_label} strategies cannot have {detail}")
            if effective_authority != "none":
                raise ValueError(f"{lifecycle_label} strategies cannot have authority")
        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.score_authority:
            raise ValueError("score_authority is not permitted for this lifecycle")
        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.research_promotion_allowed:
            raise ValueError("research_promotion_allowed is not permitted for this lifecycle")
        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.portfolio_review_allowed:
            raise ValueError("portfolio_review_allowed is not permitted for this lifecycle")
        if self.authority == "none" and self.permitted_authority not in {None, "none"}:
            raise ValueError("authority 'none' cannot disagree with permitted_authority")
        if self.portfolio_review_allowed and effective_authority != "portfolio_review":
            raise ValueError("portfolio_review authority is required for portfolio_review_allowed")
        if (self.score_authority or self.research_promotion_allowed) and effective_authority not in {
            "research_state",
            "portfolio_review",
        }:
            raise ValueError("research_state or portfolio_review authority is required for score/promotion flags")
        if self.execution_authority != "none":
            raise ValueError("execution_authority must remain none")
        return self


class StrategyScopePolicy(PolicyModel):
    """Supported, context-only, research-only and rejected strategy families."""

    schema_version: Literal[STRATEGY_SCOPE_SCHEMA_VERSION] = STRATEGY_SCOPE_SCHEMA_VERSION
    migrated_from_schema: Literal["1.0"] | None = None
    migration_source_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    effective_checksum: str = Field(default="unavailable", pattern=r"^(?:unavailable|[0-9a-f]{64})$")
    matrix_version: str = Field(min_length=1)
    ui_surface: Literal["system_map"]
    capability_profiles: tuple[StrategyCapabilityProfile, ...]
    profile_assignments: dict[str, str]
    instrument_rules: tuple[InstrumentCapabilityRule, ...]
    exclusion_policy: InstrumentExclusionPolicy
    entries: tuple[StrategyScopeEntry, ...] = ()

    @model_validator(mode="after")
    def validate_unique_strategies(self) -> StrategyScopePolicy:
        identifiers = [entry.strategy_id for entry in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("strategy_id values must be unique")
        profile_ids = [profile.profile_id for profile in self.capability_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("strategy capability profile identifiers must be unique")
        if set(self.profile_assignments) != set(identifiers):
            raise ValueError("profile assignments must exactly cover strategy identifiers")
        if any(entry.capability_profile != self.profile_assignments[entry.strategy_id] for entry in self.entries):
            raise ValueError("strategy capability profile must agree with profile assignments")
        profiles = {profile.profile_id: profile for profile in self.capability_profiles}
        if any(entry.capability_profile not in profiles for entry in self.entries):
            raise ValueError("strategy capability profile reference is unknown")
        for entry in self.entries:
            cells = profiles[entry.capability_profile].cells.values()
            if entry.lifecycle == "rejected" and any(cell.state != "rejected" for cell in cells):
                raise ValueError("rejected strategies require a fully rejected capability profile")
        rule_ids = [rule.rule_id for rule in self.instrument_rules]
        asset_families = [rule.asset_family for rule in self.instrument_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("instrument capability rule identifiers must be unique")
        if len(asset_families) != len(set(asset_families)):
            raise ValueError("instrument asset families must be unique")
        if set(asset_families) != REQUIRED_ASSET_FAMILIES:
            raise ValueError("instrument rules must exactly cover the required asset families")
        object.__setattr__(self, "profile_assignments", MappingProxyType(dict(self.profile_assignments)))
        return self

    @field_serializer("profile_assignments")
    def serialize_profile_assignments(self, value: dict[str, str]) -> dict[str, str]:
        return dict(value)


class GatePolicyEntry(ImmutableModel):
    """One ordered gate in the authority ladder."""

    gate_id: str = Field(min_length=1)
    order: PositiveInt = 1
    severity: GateSeverity = "notice"
    description: str = ""
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_gate_authority(self) -> GatePolicyEntry:
        if self.severity in {"blocker", "authority_warning", "notice"} and (
            self.research_promotion_allowed or self.portfolio_review_allowed
        ):
            raise ValueError("gate severity cannot allow research_promotion_allowed or portfolio_review_allowed")
        return self


class GatePolicy(PolicyModel):
    """Ordered, monotonic gate policy."""

    gates: tuple[GatePolicyEntry, ...] = ()

    @model_validator(mode="after")
    def validate_unique_gate_order(self) -> GatePolicy:
        identifiers = [gate.gate_id for gate in self.gates]
        orders = [gate.order for gate in self.gates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("gate_id values must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("order values must be unique")
        if orders and orders != sorted(orders):
            raise ValueError("gates must be ordered by order")
        return self


class GlossaryEntry(ImmutableModel):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    authority_note: str = ""


class GlossaryPolicy(PolicyModel):
    entries: tuple[GlossaryEntry, ...] = ()

    @model_validator(mode="after")
    def validate_unique_terms(self) -> GlossaryPolicy:
        terms = [entry.term.casefold() for entry in self.entries]
        if len(terms) != len(set(terms)):
            raise ValueError("glossary terms must be unique")
        return self


PolicyT = TypeVar("PolicyT", bound=PolicyModel)


class GovernanceLoadResult(ImmutableModel, Generic[PolicyT]):
    """Result of loading one policy, including fail-closed diagnostics."""

    policy: PolicyT | None = None
    schema_version: str = "unknown"
    checksum: str = "unavailable"
    diagnostic_mode: bool = False
    diagnostics: tuple[str, ...] = ()
    research_state: ResearchState = "manual_review"
    score_state: Literal["not_scoreable"] = "not_scoreable"
    research_promotion_allowed: Literal[False] = False
    portfolio_review_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False
    executable_authority: Literal[False] = False

    @property
    def value(self) -> PolicyT | None:
        """Compatibility alias for callers that call the payload ``value``."""

        return self.policy

    @property
    def model(self) -> PolicyT | None:
        """Compatibility alias for callers that call the payload ``model``."""

        return self.policy

    @property
    def valid(self) -> bool:
        return not self.diagnostic_mode and self.policy is not None

    @property
    def scoreable(self) -> bool:
        return self.score_state != "not_scoreable"


__all__ = [
    "SCHEMA_VERSION",
    "STRATEGY_SCOPE_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "REQUIRED_GATE_IDS",
    "REQUIRED_GLOSSARY_TERMS",
    "AuthorityPolicy",
    "AuthorityStageDefinition",
    "AuthorityCapability",
    "AuthorityMatrixPolicy",
    "FeatureRegistryEntry",
    "FeatureRegistryPolicy",
    "GatePolicy",
    "GatePolicyEntry",
    "GlossaryEntry",
    "GlossaryPolicy",
    "GovernanceLoadResult",
    "ImmutableModel",
    "Authority",
    "AuthorityStage",
    "CapabilityKind",
    "StrategyCapabilityStage",
    "CapabilitySupportState",
    "AssetFamily",
    "LongOnlyAction",
    "STRATEGY_CAPABILITY_STAGES",
    "REQUIRED_ASSET_FAMILIES",
    "AuthorityDecision",
    "GateResult",
    "GateSeverity",
    "InternalSignalIntent",
    "PortfolioReviewState",
    "ResearchState",
    "ScoreComponent",
    "ProductDefinition",
    "PolicyModel",
    "ProductGovernancePolicy",
    "StrategyScopeEntry",
    "StrategyScopePolicy",
    "CapabilityPrerequisites",
    "StrategyCapabilityCell",
    "StrategyCapabilityProfile",
    "InstrumentCapabilityRule",
    "InstrumentExclusionPolicy",
]
