"""Transport-safe event-window preview restriction shared by domain and application.

One class identity serves portfolio.event_controls and the application contracts
without the domain importing the application layer (ADR-0002).
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventBlockPolicy(BaseModel):
    """Transport-safe explicit preview restriction, never execution authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    policy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    targets: tuple[Literal["proposal_preview", "order_preview"], ...] = ("proposal_preview", "order_preview")
    event_types: tuple[Literal["earnings", "dividend", "ex_dividend", "split", "corporate_action", "high_risk", "filing", "guidance", "fund_rebalance", "index_change", "review_date"], ...] = ("earnings", "high_risk")
    risk_levels: tuple[Literal["low", "medium", "high", "critical", "unknown"], ...] = ("high", "critical")
    pre_minutes: int = Field(default=0, ge=0, le=525600, strict=True)
    post_minutes: int = Field(default=0, ge=0, le=525600, strict=True)
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_policy(self):
        if not self.policy_id.strip() or not self.version.strip():
            raise ValueError("Policy identity must not be blank")
        for values in (self.targets, self.event_types, self.risk_levels):
            if not values or len(set(values)) != len(values):
                raise ValueError("Policy selections must be nonempty and unique")
        return self

    @property
    def checksum(self) -> str:
        payload = self.model_dump(mode="json")
        for key in ("targets", "event_types", "risk_levels"):
            payload[key] = sorted(payload[key])
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


__all__ = ["EventBlockPolicy"]
