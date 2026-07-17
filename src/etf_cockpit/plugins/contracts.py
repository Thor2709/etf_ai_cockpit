"""Transport-safe contracts for optional local plugins.

Plugins receive request data and a read-only context.  They never receive a
canonical store or a broker authority object.  The manifest is intentionally
strict so an invalid or over-privileged plugin cannot be registered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PLUGIN_CONTRACT_SCHEMA_VERSION = "plugin-contract.v1"
PLUGIN_CONFORMANCE_SCHEMA_VERSION = "plugin-conformance.v1"


class PluginKind(StrEnum):
    PROVIDER = "provider"
    PARSER = "parser"
    MODEL = "model"
    STRATEGY = "strategy"
    OPTIMISER = "optimiser"
    BROKER_ADAPTER = "broker_adapter"


class PluginStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    INVALID = "invalid"


class PluginContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PluginManifest(PluginContractModel):
    schema_version: str = PLUGIN_CONTRACT_SCHEMA_VERSION
    plugin_id: str = Field(min_length=3, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    kind: PluginKind
    capabilities: tuple[str, ...] = Field(min_length=1)
    licence: str = Field(min_length=1, max_length=160)
    network_access: bool = False
    credential_requirements: tuple[str, ...] = ()
    quota: str = Field(default="none", min_length=1, max_length=160)
    retention: str = Field(default="local-cache-only", min_length=1, max_length=160)
    authority: Literal["context_only", "evidence_only", "research_state", "paper_only", "broker_read_only", "disabled"] = "context_only"
    writes_canonical_stores: bool = False
    executable_authority: bool = False
    entry_point: str | None = None

    @field_validator("plugin_id")
    @classmethod
    def validate_plugin_id(cls, value: str) -> str:
        value = value.strip().lower()
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
        if any(char not in allowed for char in value) or value[0] in ".-" or value[-1] in ".-":
            raise ValueError("plugin_id must use lower-case letters, numbers, dots, underscores or hyphens")
        return value

    @field_validator("capabilities", "credential_requirements")
    @classmethod
    def normalise_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(item.strip().lower() for item in value)
        if any(not item for item in values):
            raise ValueError("contract names must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("contract names must be unique")
        return values

    @model_validator(mode="after")
    def reject_authority_escalation(self) -> "PluginManifest":
        if self.writes_canonical_stores:
            raise ValueError("writes_canonical_stores must be false; plugins use core-owned imports")
        if self.executable_authority:
            raise ValueError("executable_authority must be false; execution is disabled by policy")
        if self.kind is PluginKind.BROKER_ADAPTER and self.authority not in {"paper_only", "broker_read_only", "disabled"}:
            raise ValueError("broker adapters may only declare paper or read-only authority")
        return self


class PluginHealth(PluginContractModel):
    status: PluginStatus
    message: str = Field(min_length=1, max_length=500)
    checked_at: str | None = None
    error_fingerprint: str | None = None
    executable_authority: bool = False

    @model_validator(mode="after")
    def reject_executable_health(self) -> "PluginHealth":
        if self.executable_authority:
            raise ValueError("plugin health cannot grant executable authority")
        return self


class PluginResult(PluginContractModel):
    status: Literal["ok", "degraded", "unavailable", "unsupported", "failed"]
    message: str = Field(min_length=1, max_length=500)
    data: dict[str, Any] = Field(default_factory=dict)
    executable_authority: bool = False

    @model_validator(mode="after")
    def reject_executable_result(self) -> "PluginResult":
        if self.executable_authority:
            raise ValueError("plugin results cannot grant executable authority")
        return self


@dataclass(frozen=True)
class PluginContext:
    """Read-only inputs and an audit sink; no canonical storage handle exists."""

    request_id: str
    inputs: Mapping[str, object] = field(default_factory=dict)
    _audit_events: list[dict[str, str]] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, "_audit_events", [])

    def read_input(self, name: str, default: object = None) -> object:
        return self.inputs.get(name, default)

    def record_audit(self, event: str, detail: str = "") -> None:
        self._audit_events.append({"event": str(event), "detail": str(detail)[:240]})

    @property
    def audit_events(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(item) for item in self._audit_events)


__all__ = [
    "PLUGIN_CONFORMANCE_SCHEMA_VERSION",
    "PLUGIN_CONTRACT_SCHEMA_VERSION",
    "PluginContext",
    "PluginHealth",
    "PluginKind",
    "PluginManifest",
    "PluginResult",
    "PluginStatus",
]
