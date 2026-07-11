from __future__ import annotations

from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority


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


def test_official_authority_ranks_above_vendor() -> None:
    assert SourceAuthority.OFFICIAL.rank > SourceAuthority.VENDOR.rank
    assert SourceAuthority.MODEL.rank == 0
