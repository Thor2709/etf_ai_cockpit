"""Structured result envelope shared by all MCP tools.

Open defaults: as_of is the current UTC time, execution_allowed is always false, warnings
and provenance are empty, optional freshness/gate metadata is null, and data is null.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    universe_revision: str | None = None
    scoreboard_binding: str | None = None


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_as_of: datetime | str | None = None
    freshness: str | None = None
    execution_allowed: Literal[False] = False
    gate_summary: Any = None
    warnings: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    next_cursor: str | None = None
    data: Any = None
