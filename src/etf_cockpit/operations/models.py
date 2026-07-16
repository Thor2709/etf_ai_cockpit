from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


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


WriteTransactionStatus = Literal[
    "planned",
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
    base_generation_ids: dict[str, str] = Field(
        validation_alias=AliasChoices("base_generation_ids", "base_generations")
    )
    staging_paths: list[str]
    final_paths: list[str]
    expected_checksums: dict[str, str]
    status: WriteTransactionStatus
    started_at: datetime = Field(validation_alias=AliasChoices("started_at", "created_at"))
    updated_at: datetime
    committed_at: datetime | None = None
    recovery_instructions: list[str]

    @field_validator("staging_paths", "final_paths", mode="before")
    @classmethod
    def accept_legacy_path_maps(cls, value: object) -> object:
        """Accept the pre-approval mapping shape while exposing only list fields."""
        if isinstance(value, dict):
            return list(value.values())
        return value

    @field_validator("recovery_instructions", mode="before")
    @classmethod
    def accept_legacy_recovery_instruction(cls, value: object) -> object:
        if isinstance(value, str):
            return [value]
        return value

    @property
    def affected_datasets(self) -> list[str]:
        """Compatibility alias for a legacy draft name."""
        return self.affected_dataset_ids

    @property
    def created_at(self) -> datetime:
        """Compatibility alias for a legacy draft name."""
        return self.started_at

    @property
    def base_generations(self) -> dict[str, str]:
        """Compatibility alias for a legacy draft name."""
        return self.base_generation_ids
