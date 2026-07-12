from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
import hashlib
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
from etf_cockpit.core.config import DataProvidersConfig, ProviderSection
from etf_cockpit.core.paths import CLEAN_DIR
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority, redact_mapping, redact_text


REQUIRED_PROVIDER_IDS = frozenset(
    {
        "yfinance",
        "sec_edgar",
        "filings_xbrl_org",
        "fred",
        "stooq",
        "rss",
        "manual_local",
        "issuer_document",
        "index_provider",
    }
)
DEFAULT_PROBE_PATH = CLEAN_DIR / "provider_probe_results.parquet"
PROBE_SCHEMA_VERSION = "provider_probe_results.v1"

Probe = Callable[[], object]
Adapter = object

_KEYLESS_PROVIDERS = frozenset(
    {
        "yfinance",
        "sec_edgar",
        "filings_xbrl_org",
        "stooq",
        "rss",
        "manual_local",
        "issuer_document",
        "index_provider",
    }
)
_AUTHORITY_BY_PROVIDER = {
    "sec_edgar": SourceAuthority.OFFICIAL,
    "filings_xbrl_org": SourceAuthority.OFFICIAL,
    "index_provider": SourceAuthority.OFFICIAL,
    "issuer_document": SourceAuthority.ISSUER,
    "rss": SourceAuthority.COMMUNITY,
    "manual_local": SourceAuthority.COMMUNITY,
}
_VALID_STATUSES = frozenset({"ok", "unavailable", "rate_limited", "timeout", "malformed", "error"})


class ProviderRegistry:
    """Local-first provider capability registry.

    Registry probes are explicit and bounded.  A disabled or incomplete
    provider returns a visible unavailable capability and its probe callback is
    never invoked.  Adapters remain lazy: registration does not perform I/O.
    """

    def __init__(self, config: DataProvidersConfig) -> None:
        self.config = config
        self._probes: dict[str, Probe] = {}

    def register_probe(self, provider_id: str, probe: Probe) -> None:
        self._probes[str(provider_id).strip()] = probe

    def register_adapter(self, provider_id: str, adapter: Adapter) -> None:
        probe = getattr(adapter, "probe_capabilities", None)
        if not callable(probe):
            raise TypeError("provider adapter must expose probe_capabilities()")
        self.register_probe(provider_id, probe)

    # Compatibility alias for callers that use adapter terminology.
    register = register_adapter

    def probe_all(self) -> tuple[ProviderCapability, ...]:
        provider_ids = sorted(REQUIRED_PROVIDER_IDS | set(self.config.providers) | set(self._probes))
        return tuple(self._probe(provider_id) for provider_id in provider_ids)

    def status_rows(self, capabilities: Iterable[ProviderCapability] | None = None) -> tuple[dict[str, object], ...]:
        rows = capabilities if capabilities is not None else self.probe_all()
        return tuple(
            {
                "provider_id": item.provider_id,
                "dataset_type": item.dataset_type,
                "enabled": item.configured,
                "configured": item.configured,
                "status": item.status,
                "authority": item.authority.value,
                "capabilities": item.dataset_type,
                "entitlement": item.entitlement,
                "rate_limit_note": item.rate_limit_note,
                "last_success_at": item.last_success_at,
                "redacted_configuration": self.redacted_configuration(item.provider_id),
                "score_eligible": item.score_eligible,
                "message": redact_text(item.message),
            }
            for item in rows
        )

    def redacted_configuration(self, provider_id: str) -> Mapping[str, object]:
        section, _ = self._section_for(provider_id)
        return redact_mapping(section.model_dump())  # type: ignore[return-value]

    def redacted_config(self) -> dict[str, object]:
        return redact_mapping(self.config.model_dump())  # type: ignore[return-value]

    def persist_probe_results(
        self,
        path: Path | None = None,
        capabilities: Iterable[ProviderCapability] | None = None,
    ) -> Path:
        destination = Path(path or DEFAULT_PROBE_PATH)
        items = tuple(capabilities) if capabilities is not None else self.probe_all()
        rows = [item.to_dict() for item in items]
        frame = pd.DataFrame(
            rows,
            columns=[
                "provider_id",
                "dataset_type",
                "status",
                "authority",
                "authority_rank",
                "configured",
                "entitlement",
                "rate_limit_note",
                "last_success_at",
                "error_fingerprint",
                "score_eligible",
                "message",
            ],
        )
        frame.insert(0, "schema_version", PROBE_SCHEMA_VERSION)
        frame.attrs["schema_version"] = PROBE_SCHEMA_VERSION
        destination.parent.mkdir(parents=True, exist_ok=True)
        csv_destination = destination.with_suffix(".csv")
        parquet_payload = BytesIO()
        frame.to_parquet(parquet_payload, index=False)
        csv_payload = frame.to_csv(index=False).encode("utf-8")
        atomic_write_group(
            (
                AtomicWriteRequest(destination, parquet_payload.getvalue(), _validate_parquet),
                AtomicWriteRequest(csv_destination, csv_payload, _validate_csv),
            )
        )
        return destination

    def _probe(self, provider_id: str) -> ProviderCapability:
        section, dataset_type = self._section_for(provider_id)
        active = (section.active_provider or "none").strip().lower()
        configured = active not in {"", "none"}
        authority = _AUTHORITY_BY_PROVIDER.get(provider_id, SourceAuthority.VENDOR)
        base = ProviderCapability(
            provider_id=provider_id,
            dataset_type=dataset_type,
            status="unavailable",
            authority=authority,
            configured=configured,
            entitlement="unknown",
            rate_limit_note="probe not run",
            last_success_at=None,
            error_fingerprint=None,
            secret_present=bool(section.api_key),
        )
        if not configured:
            return replace(base, entitlement="disabled", message="Provider disabled by configuration.")
        if self._requires_api_key(provider_id, active) and not section.api_key.strip():
            return replace(
                base,
                configured=False,
                entitlement="api_key_required",
                message="Provider unavailable: required API key is not configured.",
            )
        probe = self._probes.get(provider_id) or self._probes.get(active)
        if probe is None:
            return replace(base, entitlement="configured", message="No capability probe registered; no network call was made.")
        try:
            result = probe()
            return self._normalise_result(base, result)
        except Exception as exc:
            status = _exception_status(exc)
            fingerprint = hashlib.sha256(f"{type(exc).__name__}:{redact_text(exc)}".encode()).hexdigest()[:16]
            return replace(
                base,
                status=status,
                rate_limit_note="probe failed; retry policy is provider-specific" if status != "ok" else base.rate_limit_note,
                error_fingerprint=fingerprint,
                message=f"Capability probe failed: {type(exc).__name__}.",
            )

    def _section_for(self, provider_id: str) -> tuple[ProviderSection, str]:
        direct = self.config.providers.get(provider_id)
        if direct is not None and (direct.active_provider or "none").strip().lower() not in {"", "none"}:
            return direct, provider_id
        for dataset_type, section in self.config.providers.items():
            if (section.active_provider or "none").strip().lower() == provider_id:
                return section, dataset_type
        return direct or ProviderSection(), provider_id

    @staticmethod
    def _requires_api_key(provider_id: str, active: str) -> bool:
        return provider_id == "fred" or active not in _KEYLESS_PROVIDERS

    @staticmethod
    def _normalise_result(base: ProviderCapability, result: object) -> ProviderCapability:
        if isinstance(result, ProviderCapability):
            return _merge_capability(base, result)
        if isinstance(result, (tuple, list)):
            if len(result) != 1 or not isinstance(result[0], ProviderCapability):
                return replace(base, status="malformed", message="Capability probe returned malformed capability data.")
            return _merge_capability(base, result[0])
        if isinstance(result, Mapping):
            raw_status = str(result.get("status") or "malformed").strip().lower()
            status = raw_status if raw_status in _VALID_STATUSES else "malformed"
            message = redact_text(result.get("message") or ("Injected capability probe completed." if status == "ok" else "Capability probe unavailable."))
            last_success = _utc_now() if status == "ok" else None
            return replace(
                base,
                status=status,
                entitlement=redact_text(result.get("entitlement") or base.entitlement),
                rate_limit_note=redact_text(result.get("rate_limit_note") or base.rate_limit_note),
                last_success_at=last_success,
                message=message,
            )
        if isinstance(result, bool):
            status = "ok" if result else "unavailable"
            return replace(base, status=status, last_success_at=_utc_now() if status == "ok" else None, message="Injected capability probe completed." if result else "Injected capability probe unavailable.")
        return replace(base, status="malformed", message="Capability probe returned malformed data.")


def _merge_capability(base: ProviderCapability, result: ProviderCapability) -> ProviderCapability:
    status = result.status.strip().lower()
    if status not in _VALID_STATUSES:
        status = "malformed"
    return replace(
        base,
        dataset_type=redact_text(result.dataset_type or base.dataset_type),
        status=status,
        authority=result.authority,
        entitlement=redact_text(result.entitlement),
        rate_limit_note=redact_text(result.rate_limit_note),
        last_success_at=result.last_success_at or (_utc_now() if status == "ok" else None),
        error_fingerprint=result.error_fingerprint,
        message=redact_text(result.message),
    )


def _exception_status(exc: Exception) -> str:
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return "timeout"
    if "rate" in type(exc).__name__.lower() or "429" in str(exc):
        return "rate_limited"
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        return "malformed"
    return "error"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_parquet(path: Path) -> None:
    pd.read_parquet(path)


def _validate_csv(path: Path) -> None:
    pd.read_csv(path)


__all__ = ["DEFAULT_PROBE_PATH", "PROBE_SCHEMA_VERSION", "REQUIRED_PROVIDER_IDS", "ProviderRegistry"]
