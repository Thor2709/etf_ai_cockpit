"""Immutable, checksum-bearing governance policy contracts.

The governance files are deliberately represented by small, strict Pydantic
models.  A policy can describe advisory research and review authority, but the
execution boundary is encoded as ``Literal[False]`` in every model so a YAML
value cannot opt the application into an executable mode.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator


SCHEMA_VERSION = "1.0"
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
ResearchState = Literal["research_candidate", "manual_review", "not_scoreable"]
GateSeverity = Literal["blocker", "authority_warning", "notice"]

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

    entries: tuple[StrategyScopeEntry, ...] = ()

    @model_validator(mode="after")
    def validate_unique_strategies(self) -> StrategyScopePolicy:
        identifiers = [entry.strategy_id for entry in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("strategy_id values must be unique")
        return self


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
    "SUPPORTED_SCHEMA_VERSIONS",
    "REQUIRED_GATE_IDS",
    "REQUIRED_GLOSSARY_TERMS",
    "AuthorityPolicy",
    "FeatureRegistryEntry",
    "FeatureRegistryPolicy",
    "GatePolicy",
    "GatePolicyEntry",
    "GlossaryEntry",
    "GlossaryPolicy",
    "GovernanceLoadResult",
    "ImmutableModel",
    "Authority",
    "ProductDefinition",
    "PolicyModel",
    "ProductGovernancePolicy",
    "StrategyScopeEntry",
    "StrategyScopePolicy",
]
