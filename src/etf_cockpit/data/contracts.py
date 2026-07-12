from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import re
from typing import Any


class SourceAuthority(StrEnum):
    OFFICIAL = "official"
    ISSUER = "issuer"
    VENDOR = "vendor"
    COMMUNITY = "community"
    MODEL = "model"
    # Retained for identity/manual-note compatibility.  Manual values are
    # descriptive context and never outrank official, issuer or vendor data.
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
        return self.status.strip().lower() == "ok" and self.configured and self.authority is not SourceAuthority.MODEL

    def with_status(self, status: str, *, message: str = "") -> "ProviderCapability":
        return replace(self, status=status, message=redact_text(message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": redact_text(self.provider_id),
            "dataset_type": redact_text(self.dataset_type),
            "status": redact_text(self.status),
            "authority": self.authority.value,
            "authority_rank": self.authority.rank,
            "configured": self.configured,
            "entitlement": redact_text(self.entitlement),
            "rate_limit_note": redact_text(self.rate_limit_note),
            "last_success_at": _redact_optional_text(self.last_success_at),
            "error_fingerprint": _redact_optional_text(self.error_fingerprint),
            "secret_present": self.secret_present,
            "score_eligible": self.score_eligible,
            "message": redact_text(self.message),
        }


_HEADER_CREDENTIAL_PATTERN = re.compile(
    r"(?P<prefix>\b(?:authorization|proxy-authorization)\s*[:=]\s*)"
    r"(?:(?P<scheme>bearer|basic|digest|token)\s+)?"
    r"(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"(?P<prefix>\bbearer\s+)(?P<value>[^\s,;]+)", re.IGNORECASE)
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_ -]?key|token|password|passwd|secret)(\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(?:^|[?&])(api[_-]?key|token|password|secret)=[^&\s]+"),
    re.compile(r"(?i)\b[A-Za-z0-9_-]{24,}\b"),
)


def redact_text(value: object) -> str:
    """Return safe human-readable probe text without credential material."""

    text = str(value or "")
    text = _HEADER_CREDENTIAL_PATTERN.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('scheme')} ***redacted***"
            if match.group("scheme")
            else f"{match.group('prefix')}***redacted***"
        ),
        text,
    )
    text = _BEARER_PATTERN.sub(lambda match: f"{match.group('prefix')}***redacted***", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***redacted***", text)
    return text.replace(".env", "[env-file]")


def _redact_optional_text(value: object) -> str | None:
    return None if value is None else redact_text(value)


def redact_mapping(value: object) -> object:
    """Recursively redact provider settings before serialisation or display."""

    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(?i)(api[_ -]?key|token|password|passwd|secret|bearer|authorization|\.env)", key_text):
                redacted[key] = "***redacted***" if item else ""
            else:
                redacted[key] = redact_mapping(item)
        return redacted
    if isinstance(value, (list, tuple, set)):
        return type(value)(redact_mapping(item) for item in value)
    return redact_text(value) if isinstance(value, str) else value


def preferred_authority(authorities: object) -> SourceAuthority:
    """Select the highest-authority source, with deterministic enum coercion."""

    values = tuple(
        item if isinstance(item, SourceAuthority) else SourceAuthority(str(item).strip().lower())
        for item in authorities  # type: ignore[union-attr]
    )
    if not values:
        return SourceAuthority.MODEL
    return max(values, key=lambda item: item.rank)
