from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, model_validator


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
