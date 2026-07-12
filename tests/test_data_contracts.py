from __future__ import annotations

import etf_cockpit.data.contracts as contracts

ProviderCapability = contracts.ProviderCapability
SourceAuthority = contracts.SourceAuthority


def test_provider_capability_redaction_and_score_eligibility() -> None:
    capability = ProviderCapability(
        provider_id="fred",
        dataset_type="macro",
        status="ok",
        authority=SourceAuthority.VENDOR,
        configured=True,
        entitlement="free",
        rate_limit_note="bounded",
        last_success_at="2026-07-10T00:00:00Z",
        error_fingerprint=None,
        secret_present=True,
    )
    payload = capability.to_dict()
    assert "secret" not in str(payload).lower() or payload["secret_present"] is True
    assert capability.score_eligible is True
    assert capability.with_status("unavailable").score_eligible is False


def test_ok_capability_requires_configuration_and_authority_is_serialised_without_secrets() -> None:
    capability = ProviderCapability(
        provider_id="fred",
        dataset_type="macro",
        status="ok",
        authority=SourceAuthority.VENDOR,
        configured=False,
        entitlement="free",
        rate_limit_note="bounded",
        last_success_at=None,
        error_fingerprint=None,
        secret_present=True,
        message="token=do-not-leak",
    )

    assert capability.score_eligible is False
    payload = capability.to_dict()
    assert payload["authority"] == "vendor"
    assert "do-not-leak" not in str(payload)
    assert "token=" not in str(payload)


def test_provider_capability_redacts_complete_bearer_header_values() -> None:
    token = "super-secret-token"
    capability = ProviderCapability(
        provider_id="fred",
        dataset_type="macro",
        status="ok",
        authority=SourceAuthority.VENDOR,
        configured=True,
        entitlement=f"Authorization: Bearer {token}",
        rate_limit_note=f"Bearer {token}",
        last_success_at=None,
        error_fingerprint=f"Authorization: Bearer {token}",
        message=f"Authorization: Bearer {token}",
    )

    payload = capability.to_dict()

    assert token not in str(payload)
    assert "Bearer ***redacted***" in str(payload)


def test_official_authority_ranks_above_vendor() -> None:
    assert SourceAuthority.OFFICIAL.rank > SourceAuthority.VENDOR.rank
    assert SourceAuthority.MODEL.rank == 0


def test_preferred_authority_uses_official_before_vendor() -> None:
    preferred_authority = getattr(contracts, "preferred_authority", None)
    assert callable(preferred_authority)
    assert preferred_authority((SourceAuthority.VENDOR, SourceAuthority.OFFICIAL)) is SourceAuthority.OFFICIAL
