from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from etf_cockpit.core.constants import ALLOWED_ACTIONS
from etf_cockpit.signals.research_states import PortfolioReviewState, ResearchState


class PortfolioActionAudit(BaseModel):
    """v1 compatibility import model; never used by v2 exports."""

    etf_id: str
    action: Literal["hold", "no_trade", "add_candidate", "trim_candidate", "manual_review", "buy", "add", "trim", "sell"]
    conviction: float = Field(ge=0, le=1)
    reason_short: str
    main_supporting_metrics: list[str]
    main_risks: list[str]
    blocked_by: list[str]
    manual_checks: list[str]


class PortfolioReviewAudit(BaseModel):
    """Release-facing v2 review row with no transaction-shaped action field."""

    model_config = ConfigDict(extra="forbid")

    etf_id: str
    research_state: ResearchState
    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
    analysis_status: Literal["complete", "partial", "unavailable"] = "unavailable"
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    execution_allowed: Literal[False] = False
    legacy_action: str | None = None
    migration_version: str = "2.0"
    gate_policy_version: str = "unavailable"
    gate_policy_checksum: str = "unavailable"
    schema_version: Literal["2.0"] = "2.0"
    conviction: float = Field(default=0.0, ge=0, le=1)
    reason_short: str = ""
    main_supporting_metrics: list[str] = Field(default_factory=list)
    main_risks: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    manual_checks: list[str] = Field(default_factory=list)

    @field_validator("research_promotion_allowed", "portfolio_review_allowed", mode="before")
    @classmethod
    def _force_task2_authority_false(cls, _value: object) -> bool:
        """Direct v2 audit construction cannot mint positive authority."""

        return False


class IgnoredSignal(BaseModel):
    etf_id: str
    reason: str


class RiskFlag(BaseModel):
    type: Literal["concentration", "data_quality", "overfitting", "model_disagreement", "liquidity", "cost", "thesis_change"]
    severity: Literal["low", "medium", "high"]
    description: str


class ModelAudit(BaseModel):
    toto_usefulness: str
    timesfm_usefulness: str
    baseline_comparison: str
    overfitting_concerns: list[str]


class ChatGPTAudit(BaseModel):
    schema_version: str
    review_date: str
    overall_view: Literal["risk_on", "neutral", "risk_off", "unclear"]
    portfolio_actions: list[PortfolioActionAudit]
    ignored_signals: list[IgnoredSignal] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    model_audit: ModelAudit
    dashboard_notes: list[str] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != "1.0":
            raise ValueError("schema_version must be 1.0")
        return value


class ChatGPTAuditV2(BaseModel):
    """Typed v2 external-review import; v1 remains accepted at the seam."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    review_date: str
    overall_view: Literal["risk_on", "neutral", "risk_off", "unclear"]
    portfolio_actions: list[PortfolioReviewAudit]
    ignored_signals: list[IgnoredSignal] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    model_audit: ModelAudit
    dashboard_notes: list[str] = Field(default_factory=list)


def allowed_actions() -> tuple[str, ...]:
    return ALLOWED_ACTIONS
