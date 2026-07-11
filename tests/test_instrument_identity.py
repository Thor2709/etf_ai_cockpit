from __future__ import annotations

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.instrument_identity import IdentityClaim, resolve_identity


def test_identity_resolution_preserves_unknown_isin_and_provider_symbols() -> None:
    result = resolve_identity(
        [
            IdentityClaim("AURG", "name", "Aurskog Sparebank", "universe", SourceAuthority.MANUAL),
            IdentityClaim("AURG", "ticker", "AURG", "universe", SourceAuthority.MANUAL),
            IdentityClaim("AURG", "yahoo_symbol", "AURG.OL", "universe", SourceAuthority.MANUAL),
            IdentityClaim("AURG", "isin", "needs_verification", "universe", SourceAuthority.MANUAL),
        ]
    )
    assert result.identity.isin_status == "needs_verification"
    assert result.identity.provider_symbols["yahoo"] == "AURG.OL"
    assert result.identity.warnings


def test_official_claim_wins_but_conflict_is_retained() -> None:
    result = resolve_identity(
        [
            IdentityClaim("X", "isin", "NO0000000001", "vendor", SourceAuthority.VENDOR),
            IdentityClaim("X", "isin", "NO0000000002", "sec", SourceAuthority.OFFICIAL),
            IdentityClaim("X", "ticker", "X", "vendor", SourceAuthority.VENDOR),
        ]
    )
    assert result.identity.isin == "NO0000000002"
    assert len(result.conflicts) == 1
    assert result.conflicts[0].requires_manual_review is True
