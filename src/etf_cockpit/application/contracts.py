"""Typed, immutable contracts for the local application boundary.

The contracts contain transport-safe data only. They deliberately do not
import domain modules, pandas objects or Flet controls, so another local
frontend can consume the same query and command shapes.
"""

from __future__ import annotations

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


class PaperViewModel(ContractModel):
    account_id: str
    status: str
    as_of: str | None = None
    equity: float | None = None
    message: str = ""


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
    "PageRequest",
    "PageView",
    "PaperViewModel",
    "PortfolioViewModel",
    "ProposalViewModel",
    "QueryRequest",
    "RefreshDataCommand",
    "ScoreViewModel",
    "SubmitWorkflowCommand",
]
