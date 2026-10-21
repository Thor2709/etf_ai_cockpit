"""Typed, immutable contracts for the local application boundary.

The contracts contain transport-safe data only. They deliberately do not
import domain modules, pandas objects or Flet controls, so another local
frontend can consume the same query and command shapes.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, NoReturn, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from etf_cockpit.core.event_policy import EventBlockPolicy


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


class FrozenDict(dict):
    """Read-only mapping: every mutator raises. It is still a ``dict``, so JSON encoders and readers work."""

    __slots__ = ()

    def _readonly(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise TypeError("contract mappings are immutable; copy with dict(...) before editing")

    __setitem__ = __delitem__ = __ior__ = _readonly
    clear = pop = popitem = setdefault = update = _readonly

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(frozenset(self.items()))

    def __reduce__(self):
        return (FrozenDict, (dict(self),))

    def __copy__(self) -> FrozenDict:
        return self

    def __deepcopy__(self, memo: dict) -> FrozenDict:
        return self


class FrozenList(list):
    """Read-only list: compares equal to a list and encodes as a JSON array, but cannot be edited."""

    __slots__ = ()

    def _readonly(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise TypeError("contract sequences are immutable; copy with list(...) before editing")

    __setitem__ = __delitem__ = __iadd__ = __imul__ = _readonly
    append = extend = insert = pop = remove = clear = sort = reverse = _readonly

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(tuple(self))

    def __reduce__(self):
        return (FrozenList, (list(self),))

    def __copy__(self) -> FrozenList:
        return self

    def __deepcopy__(self, memo: dict) -> FrozenList:
        return self


def freeze_contract_value(value: object) -> object:
    """Deep-copy mappings into FrozenDict and lists into FrozenList, sets into frozensets so nothing nested can be edited."""

    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, Mapping):
        return FrozenDict({key: freeze_contract_value(item) for key, item in value.items()})  # type: ignore[attr-defined]
    if isinstance(value, list):
        return FrozenList(freeze_contract_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_contract_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_contract_value(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _freeze_mapping(value: dict[str, object]) -> dict[str, object]:
    return freeze_contract_value(value)  # type: ignore[return-value]


FrozenMap = Annotated[dict[str, object], AfterValidator(_freeze_mapping)]
FrozenStrMap = Annotated[dict[str, str], AfterValidator(_freeze_mapping)]


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
    # Omitted only for a base-currency quote; the ledger requires it for any foreign quote.
    fx_rate: float | None = Field(default=None, gt=0)
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
    # Omitted only for a base-currency order; the ledger requires it for any foreign quote.
    fx_rate: float | None = Field(default=None, gt=0)


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
    # Omitted only for a base-currency position; the ledger requires it for any foreign position.
    fx_rate: float | None = Field(default=None, gt=0)
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
    # Omitted only for a base-currency position; the ledger requires it for any foreign position.
    fx_rate: float | None = Field(default=None, gt=0)


class PaperOutcomeMatureRequest(ContractModel):
    account_id: str = Field(default="local-paper", min_length=1, max_length=128)
    reference_id: str = Field(min_length=1, max_length=128)
    adjusted_close: float = Field(gt=0)
    benchmark_return: float
    cash_return: float
    horizon_days: int = Field(default=20, ge=1, le=3650)
    exit_fx_rate: float | None = Field(default=None, gt=0)
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
    event_policy: EventBlockPolicy | None = None
    rationale: str = ""
    approvals: tuple[str, ...] = ()
    # Friction-edge evidence (all optional; the proposal stays suppressed unless the first three are supplied).
    expected_benefit_bps: float | None = Field(default=None, allow_inf_nan=False)
    reference_price_eur: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    uncertainty_bps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    adv_eur: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    daily_volatility: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ProposalGateViewModel(ContractModel):
    gate_id: str
    passed: bool
    reason: str
    blocker: bool


class ProposalViewModel(ContractModel):
    event_control: FrozenMap = Field(default_factory=FrozenDict)
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
    input_payload: FrozenMap = Field(default_factory=FrozenDict)
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


DashboardAction = Literal[
    "refresh_yfinance_data",
    "run_algorithm_scores",
    "run_forecasting_models",
    "renew_data_dry_run",
    "renew_data_api_status",
    "rollback_latest_prices",
    "export_audit_packet",
    "validate_local_import",
    "import_local_upload",
]


class DashboardActionCommand(CommandModel):
    """Execute one existing dashboard action through the application boundary."""

    # Uploaded bytes need not be UTF-8; base64 keeps JSON serialisation (the idempotency fingerprint) total.
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    kind: Literal["dashboard_action"] = "dashboard_action"
    action: DashboardAction
    dataset_type: str | None = Field(default=None, min_length=1, max_length=80)
    selected_path: str | None = Field(default=None, min_length=1, max_length=4096)
    file_name: str | None = Field(default=None, min_length=1, max_length=512)
    content: bytes | None = None

    @field_validator("content", mode="before")
    @classmethod
    def decode_dumped_content(cls, value: object, info: ValidationInfo) -> object:
        """Python-mode input of a ``model_dump(mode="json")`` dict carries URL-safe base64 text; decode it strictly (fail closed)."""

        if isinstance(value, str) and info.mode == "python":
            try:
                return base64.b64decode(value.replace("-", "+").replace("_", "/"), validate=True)  # pydantic emits URL-safe base64
            except ValueError as exc:  # binascii.Error is a ValueError
                raise ValueError("content must be bytes or strict base64 text") from exc
        return value

    @model_validator(mode="after")
    def validate_import_arguments(self):
        if self.action == "validate_local_import" and self.selected_path is None:
            raise ValueError("validate_local_import requires selected_path")
        if self.action == "import_local_upload" and (self.file_name is None or self.content is None):
            raise ValueError("import_local_upload requires file_name and content")
        return self


class CancelWorkflowCommand(CommandModel):
    kind: Literal["cancel_workflow"] = "cancel_workflow"
    workflow_id: str = Field(min_length=1, max_length=128)


ApplicationCommand = RefreshDataCommand | SubmitWorkflowCommand | DashboardActionCommand | CancelWorkflowCommand


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


class BulkAnalysisRun(ContractModel):
    """Transport-safe snapshot of one durable instrument-analysis run."""

    schema_version: str = APPLICATION_API_SCHEMA_VERSION
    run_id: str
    analyzer_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "blocked"]
    hashes: FrozenStrMap
    states: FrozenStrMap
    results: FrozenMap = Field(default_factory=FrozenDict)
    failures: FrozenStrMap = Field(default_factory=FrozenDict)
    coverage_completed: int = Field(ge=0)
    coverage_total: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_manifest_coverage(self):
        if self.coverage_completed > self.coverage_total:
            raise ValueError("coverage_completed cannot exceed coverage_total")
        if len(self.hashes) != self.coverage_total or set(self.hashes) != set(self.states):
            raise ValueError("hashes and states must cover every instrument")
        if set(self.results) - set(self.states) or set(self.failures) - set(self.states):
            raise ValueError("results and failures must refer to manifest instruments")
        return self


__all__ = [
    "APPLICATION_API_SCHEMA_VERSION",
    "ApiStatus",
    "ApplicationCommand",
    "BulkAnalysisRun",
    "CancelWorkflowCommand",
    "CommandResult",
    "DashboardAction",
    "DashboardActionCommand",
    "EventBlockPolicy",
    "ForecastViewModel",
    "FrozenDict",
    "FrozenList",
    "FrozenMap",
    "FrozenStrMap",
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
    "freeze_contract_value",
]
