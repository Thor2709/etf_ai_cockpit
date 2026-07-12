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


def test_identity_retains_mic_share_class_listing_and_missing_source_review() -> None:
    result = resolve_identity(
        [
            IdentityClaim("ETF", "ticker", "VWCE", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
            IdentityClaim("ETF", "isin", "IE00BK5BQT80", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
            IdentityClaim("ETF", "exchange", "XETRA", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "mic", "XETR", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "currency", "EUR", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "share_class", "accumulating", "issuer", SourceAuthority.ISSUER, "issuer:identity"),
            IdentityClaim("ETF", "listing", "XETR:VWCE", "vendor", SourceAuthority.VENDOR, "vendor:listing"),
            IdentityClaim("ETF", "provider_symbol", "VWCE.DE", "yfinance", SourceAuthority.VENDOR, "yfinance:quote"),
        ]
    )
    assert result.identity.mic == "XETR"
    assert result.identity.share_class == "accumulating"
    assert result.identity.listing == "XETR:VWCE"
    assert result.identity.provider_symbols["yfinance"] == "VWCE.DE"
    assert result.identity.confidence == "high"

    missing_source = resolve_identity(
        [IdentityClaim("ETF", "ticker", "VWCE", "manual", SourceAuthority.MANUAL)]
    )
    assert missing_source.identity.confidence == "manual_review"
    assert "missing_source_id" in missing_source.identity.warnings
    assert missing_source.requires_manual_review is True


def test_identity_ticker_and_isin_mismatch_is_fail_closed() -> None:
    result = resolve_identity(
        [
            IdentityClaim("ETF", "ticker", "VWCE", "official", SourceAuthority.OFFICIAL, "sec:identity"),
            IdentityClaim("ETF", "ticker", "VWRL", "vendor", SourceAuthority.VENDOR, "vendor:identity"),
            IdentityClaim("ETF", "isin", "UNKNOWN", "vendor", SourceAuthority.VENDOR, "vendor:identity"),
        ]
    )
    assert result.identity.ticker == "VWCE"
    assert result.identity.isin_status == "needs_verification"
    assert result.identity.confidence == "manual_review"
    assert any("ticker" in warning for warning in result.identity.warnings)
    assert any(conflict.field == "ticker" for conflict in result.conflicts)


def test_manual_override_is_distinct_from_ordinary_local_config_claim() -> None:
    config_claims = [
        IdentityClaim("X", "ticker", "X", "universe", SourceAuthority.MANUAL, "config:X"),
        IdentityClaim("X", "isin", "US0000000000", "universe", SourceAuthority.MANUAL, "config:X"),
    ]
    assert resolve_identity(config_claims).identity.confidence == "high"
    override = resolve_identity([IdentityClaim("X", "ticker", "Y", "manual_override", SourceAuthority.MANUAL, "override:X", manual_override=True)])
    assert override.identity.confidence == "manual_review"
    assert "manual_override_requires_review" in override.identity.warnings
