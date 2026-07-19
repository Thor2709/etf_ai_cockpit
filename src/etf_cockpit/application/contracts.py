"""Typed, immutable contracts for the local application boundary.

The contracts contain transport-safe data only. They deliberately do not
import domain modules, pandas objects or Flet controls, so another local
frontend can consume the same query and command shapes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


APPLICATION_API_SCHEMA_VERSION = "application_api.v1"


class ApiStatus(StrEnum):
    AVAILABLE = "available"
    ACCEPTED = "accepted"
    REPLAYED = "replayed"
    CONFLICT = "conflict"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ContractModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PageRequest(ContractModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


ViewT = TypeVar("ViewT")


class PageView(ContractModel, Generic[ViewT]):
    schema_version: str = APPLICATION_API_SCHEMA_VERSION
    items: tuple[ViewT, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    next_offset: int | None = Field(default=None, ge=0)


class QueryRequest(ContractModel):
    resource: Literal["universe", "instruments", "scores", "forecasts", "portfolios", "jobs", "paper", "proposals", "operations"]
    page: PageRequest = Field(default_factory=PageRequest)


class InstrumentViewModel(ContractModel):
    instrument_id: str
    name: str
    ticker: str
    asset_class: str
    region: str | None = None
    currency: str
    status: str
    as_of: str | None = None


class ScoreViewModel(ContractModel):
    instrument_id: str
    score: float | None = None
    state: str
    confidence: float | None = None
    status: str
    as_of: str | None = None


class ForecastViewModel(ContractModel):
    instrument_id: str
    model: str
    horizon_days: int | None = None
    expected_return: float | None = None
    status: str
    as_of: str | None = None


class PortfolioViewModel(ContractModel):
    instrument_id: str
    current_weight: float | None = None
    target_weight: float | None = None
    market_value: float | None = None
    currency: str | None = None
    status: str


class JobViewModel(ContractModel):
    workflow_id: str
    label: str
    status: str
    created_at: str
    finished_at: str | None = None
    job_count: int = Field(ge=0)
    active: bool
    hash_chain_valid: bool
    error_message: str = ""


class PaperPositionViewModel(ContractModel):
    instrument_id: str
    quantity: float
    average_cost: float
    mark_price: float | None = None
    unrealised_pnl: float | None = None
    currency: str


class PaperViewModel(ContractModel):
    account_id: str
    status: str
    as_of: str | None = None
    equity: float | None = None
    base_currency: str = "EUR"
    cash: float | None = None
    pnl: float | None = None
    benchmark_return: float | None = None
    drawdown: float | None = None
    open_positions: int = Field(ge=0, default=0)
    closed_trades: int = Field(ge=0, default=0)
    win_rate: float | None = None
    payoff_ratio: float | None = None
    positions: tuple[PaperPositionViewModel, ...] = ()
    reconciliation_status: str = "unavailable"
    matured_outcomes: int = Field(ge=0, default=0)
    operational_incidents: int = Field(ge=0, default=0)
    execution_allowed: Literal[False] = False
    message: str = ""


class PaperAccountOpenRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    initial_cash: float = Field(gt=0)
    base_currency: str = Field(default="EUR", min_length=3, max_length=3)


class PaperProposalRejectRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    proposal_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class PaperProposalAcceptRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    proposal_id: str = Field(min_length=1, max_length=128)
    execution_price: float = Field(gt=0)
    fee: float = Field(default=0, ge=0)
    fx_rate: float = Field(default=1, gt=0)
    mode: Literal["manual_accept", "auto_paper"] = "manual_accept"


class PaperProposalDeferRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    proposal_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class PaperFillRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    order_id: str = Field(min_length=1, max_length=128)
    fill_id: str | None = Field(default=None, min_length=1, max_length=128)
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    fee: float | None = Field(default=None, ge=0)
    fx_rate: float = Field(default=1, gt=0)


class PaperOrderCancelRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    order_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class PaperPositionMarkRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=80)
    adjusted_close: float = Field(gt=0)
    as_of: datetime
    source_authority: str = Field(min_length=1, max_length=160)
    source_checksum: str = Field(min_length=64, max_length=64)
    fx_rate: float = Field(default=1, gt=0)
    benchmark_return: float | None = None


class PaperCorporateActionRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    action_id: str | None = Field(default=None, min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=80)
    split_ratio: float = Field(gt=0)
    cash_dividend_per_unit: float = Field(default=0, ge=0)
    as_of: datetime
    source_authority: str = Field(min_length=1, max_length=160)
    source_checksum: str = Field(min_length=64, max_length=64)
    fx_rate: float = Field(default=1, gt=0)


class PaperOutcomeMatureRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    reference_id: str = Field(min_length=1, max_length=128)
    adjusted_close: float = Field(gt=0)
    benchmark_return: float
    cash_return: float
    horizon_days: int = Field(default=20, ge=1, le=3650)
    as_of: datetime
    source_authority: str = Field(min_length=1, max_length=160)
    source_checksum: str = Field(min_length=64, max_length=64)


class PaperOperationalErrorRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    related_id: str | None = Field(default=None, min_length=1, max_length=128)


class PaperOrderViewModel(ContractModel):
    account_id: str = "local-paper"
    order_id: str
    proposal_id: str
    instrument_id: str
    side: Literal["buy", "sell"]
    quantity: float
    filled_quantity: float
    remaining_quantity: float
    execution_price: float
    currency: str
    status: str
    execution_allowed: Literal[False] = False


class PaperProposalDecisionViewModel(ContractModel):
    account_id: str = "local-paper"
    proposal_id: str
    instrument_id: str
    status: Literal["rejected", "deferred"]
    reason: str
    execution_allowed: Literal[False] = False


class PaperOutcomeViewModel(ContractModel):
    account_id: str = "local-paper"
    outcome_id: str
    reference_id: str
    order_id: str
    proposal_id: str
    instrument_id: str
    net_return: float
    benchmark_return: float
    cash_return: float
    horizon_days: int = Field(ge=1, le=3650, default=20)
    excess_return_vs_benchmark: float
    excess_return_vs_cash: float
    price_basis: Literal["adjusted_close"] = "adjusted_close"
    execution_allowed: Literal[False] = False


class PaperOperationalIncidentViewModel(ContractModel):
    account_id: str = "local-paper"
    incident_id: str
    code: str
    message: str
    related_id: str | None = None
    execution_allowed: Literal[False] = False


ProposalAuthorityStage = Literal[
    "research",
    "shadow_proposal",
    "paper",
    "broker_read_only",
    "draft_order",
    "capped_automatic",
    "disabled",
]


class ProposalGateEvidence(ContractModel):
    gate_id: str = Field(min_length=1)
    passed: bool
    reason: str = ""
    blocker: bool = True


class ProposalReviewRequest(ContractModel):
    instrument_id: str = Field(min_length=1)
    current_quantity: float = Field(ge=0)
    target_quantity: float = Field(ge=0)
    strategy_id: str = Field(min_length=1)
    strategy_stage: ProposalAuthorityStage
    model_id: str = Field(min_length=1)
    model_stage: ProposalAuthorityStage
    account_id: str = Field(min_length=1)
    account_stage: ProposalAuthorityStage
    optimiser_output_id: str | None = None
    portfolio_revision: str | None = None
    data_revision: str | None = None
    as_of: datetime
    expires_at: datetime
    authority_policy_checksum: str = Field(min_length=64, max_length=64)
    gate_evidence: tuple[ProposalGateEvidence, ...] = ()
    rationale: str = ""
    approvals: tuple[str, ...] = ()


class ProposalGateViewModel(ContractModel):
    gate_id: str
    passed: bool
    reason: str
    blocker: bool


class ProposalViewModel(ContractModel):
    proposal_id: str
    instrument_id: str
    outcome: str
    authority_stage: str
    proposal_allowed: bool
    execution_allowed: Literal[False] = False
    quantity_delta: float
    rationale: str
    as_of: str
    expires_at: str
    gate_count: int = Field(ge=0)
    failed_gate_count: int = Field(ge=0)
    alternatives: tuple[str, ...] = ()
    input_checksum: str
    gates: tuple[ProposalGateViewModel, ...] = ()
    authority_policy_checksum: str = ""
    gate_policy_version: str = ""
    gate_policy_checksum: str = ""


class OperationViewModel(ContractModel):
    operation_id: str
    operation_type: str
    status: str
    occurred_at: str
    message: str = ""


class CommandModel(ContractModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    expected_revision: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be blank")
        return value


class RefreshDataCommand(CommandModel):
    kind: Literal["refresh_data"] = "refresh_data"
    force_sample: bool = False


class SubmitWorkflowCommand(CommandModel):
    kind: Literal["submit_workflow"] = "submit_workflow"
    workflow_type: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    input_payload: dict[str, object] = Field(default_factory=dict)
    job_keys: tuple[str, ...] = ("start",)
    dedupe_key: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("job_keys")
    @classmethod
    def validate_job_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not key.strip() for key in value):
            raise ValueError("job_keys must contain at least one non-blank key")
        if len(value) != len(set(value)):
            raise ValueError("job_keys must be unique")
        return tuple(key.strip() for key in value)


class CancelWorkflowCommand(CommandModel):
    kind: Literal["cancel_workflow"] = "cancel_workflow"
    workflow_id: str = Field(min_length=1, max_length=128)


ApplicationCommand = RefreshDataCommand | SubmitWorkflowCommand | CancelWorkflowCommand


class CommandResult(ContractModel):
    schema_version: str = APPLICATION_API_SCHEMA_VERSION
    status: ApiStatus
    command_id: str
    idempotency_key: str
    replayed: bool = False
    resource_id: str | None = None
    revision: str = ""
    details: tuple[tuple[str, str], ...] = ()
    error_code: str | None = None
    error_message: str | None = None


__all__ = [
    "APPLICATION_API_SCHEMA_VERSION",
    "ApiStatus",
    "ApplicationCommand",
    "CancelWorkflowCommand",
    "CommandResult",
    "ForecastViewModel",
    "InstrumentViewModel",
    "JobViewModel",
    "OperationViewModel",
    "PaperAccountOpenRequest",
    "PaperFillRequest",
    "PaperOrderCancelRequest",
    "PaperOrderViewModel",
    "PaperPositionMarkRequest",
    "PaperCorporateActionRequest",
    "PaperOutcomeMatureRequest",
    "PaperOperationalErrorRequest",
    "PaperPositionViewModel",
    "PaperProposalDecisionViewModel",
    "PaperProposalAcceptRequest",
    "PaperProposalDeferRequest",
    "PaperProposalRejectRequest",
    "PaperOutcomeViewModel",
    "PaperOperationalIncidentViewModel",
    "PageRequest",
    "PageView",
    "PaperViewModel",
    "PortfolioViewModel",
    "ProposalAuthorityStage",
    "ProposalGateEvidence",
    "ProposalGateViewModel",
    "ProposalReviewRequest",
    "ProposalViewModel",
    "QueryRequest",
    "RefreshDataCommand",
    "ScoreViewModel",
    "SubmitWorkflowCommand",
]
