from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class SourceAuthority(StrEnum):
    OFFICIAL = "official"
    ISSUER = "issuer"
    VENDOR = "vendor"
    COMMUNITY = "community"
    MODEL = "model"
    MANUAL = "manual"

    @property
    def rank(self) -> int:
        return {
            SourceAuthority.OFFICIAL: 100,
            SourceAuthority.ISSUER: 85,
            SourceAuthority.VENDOR: 55,
            SourceAuthority.COMMUNITY: 25,
            SourceAuthority.MANUAL: 20,
            SourceAuthority.MODEL: 0,
        }[self]


@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    dataset_type: str
    status: str
    authority: SourceAuthority
    configured: bool
    entitlement: str
    rate_limit_note: str
    last_success_at: str | None
    error_fingerprint: str | None
    secret_present: bool = False
    message: str = ""

    @property
    def score_eligible(self) -> bool:
        return self.status == "ok" and self.authority is not SourceAuthority.MODEL

    def with_status(self, status: str, *, message: str = "") -> "ProviderCapability":
        return replace(self, status=status, message=message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "dataset_type": self.dataset_type,
            "status": self.status,
            "authority": self.authority.value,
            "authority_rank": self.authority.rank,
            "configured": self.configured,
            "entitlement": self.entitlement,
            "rate_limit_note": self.rate_limit_note,
            "last_success_at": self.last_success_at,
            "error_fingerprint": self.error_fingerprint,
            "secret_present": self.secret_present,
            "score_eligible": self.score_eligible,
            "message": self.message,
        }
