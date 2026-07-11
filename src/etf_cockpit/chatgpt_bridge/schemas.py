from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from etf_cockpit.core.constants import ALLOWED_ACTIONS


class PortfolioActionAudit(BaseModel):
    etf_id: str
    action: Literal["hold", "no_trade", "add_candidate", "trim_candidate", "manual_review", "buy", "add", "trim", "sell"]
    conviction: float = Field(ge=0, le=1)
    reason_short: str
    main_supporting_metrics: list[str]
    main_risks: list[str]
    blocked_by: list[str]
    manual_checks: list[str]


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


def allowed_actions() -> tuple[str, ...]:
    return ALLOWED_ACTIONS
