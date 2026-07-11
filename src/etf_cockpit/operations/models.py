from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class OperationalEvent(BaseModel):
    """Typed projection of one row in the authoritative session trace."""

    model_config = ConfigDict(extra="allow")

    event_id: str = ""
    session_id: str
    sequence_number: int
    timestamp_utc: datetime
    event_type: str
    status: str | None = None
    component: str | None = None
    action_id: str | None = None
    prior_event_hash: str | None = None
    event_hash: str | None = None


class VerificationRun(BaseModel):
    verification_run_id: str
    verification_type: str
    command: str
    source_hash: str
    result: Literal["pass", "fail", "blocked"]
    exit_code: int
    output_paths: list[str]
    output_checksums: list[str]
    issue_ids: list[str]


class ClosureEvidenceRecord(BaseModel):
    closure_evidence_id: str
    issue_id: str
    requirement_version: str
    verification_run_ids: list[str]
    builder: str
    independent_reviewer: str
    review_result: Literal["approved", "rejected"]
    evidence_hash: str

    @model_validator(mode="after")
    def require_independent_reviewer(self) -> Self:
        if self.review_result == "approved":
            self.builder = self.builder.strip()
            self.independent_reviewer = self.independent_reviewer.strip()
            if not self.builder:
                raise ValueError("builder must be non-empty for approved closure evidence")
            if not self.independent_reviewer:
                raise ValueError(
                    "independent_reviewer must be non-empty for approved closure evidence"
                )
            if self.builder == self.independent_reviewer:
                raise ValueError("independent_reviewer must differ from builder")
        return self


WriteTransactionStatus = Literal[
    "started",
    "staging",
    "validating",
    "ready_to_commit",
    "committing",
    "committed",
    "rolling_back",
    "rolled_back",
    "recovery_required",
    "quarantined",
]


class WriteTransaction(BaseModel):
    """Durable projection of the existing atomic grouped-write journal."""

    transaction_id: str
    workflow_run_id: str
    transaction_type: str
    model_config = ConfigDict(populate_by_name=True)

    affected_dataset_ids: list[str] = Field(
        validation_alias=AliasChoices("affected_dataset_ids", "affected_datasets")
    )
    base_generations: dict[str, str]
    staging_paths: dict[str, str]
    final_paths: dict[str, str]
    expected_checksums: dict[str, str]
    status: WriteTransactionStatus
    started_at: datetime = Field(validation_alias=AliasChoices("started_at", "created_at"))
    updated_at: datetime
    committed_at: datetime | None = None
    recovery_instructions: str

    @property
    def affected_datasets(self) -> list[str]:
        """Compatibility alias for the pre-approval Task 3 draft name."""
        return self.affected_dataset_ids

    @property
    def created_at(self) -> datetime:
        """Compatibility alias for the pre-approval Task 3 draft name."""
        return self.started_at
