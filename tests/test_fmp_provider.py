from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.fmp_provider import FmpProvider, FMP_SHARED_CONFIG_BLOCK


START = date(2024, 1, 1)
END = date(2024, 1, 2)


def _configured(transport, **kwargs) -> FmpProvider:
    section = ProviderSection(
        active_provider="fmp",
        api_key="private-fmp-key",
        base_url="https://financialmodelingprep.com/stable/",
    )
    return FmpProvider(section=section, transport=transport, **kwargs)


def _assert_metadata(result) -> None:
    assert result.licence
    assert result.quota["failure_policy"] == "non_blocking"
    assert result.cache["enabled"] is True
    assert result.authority is SourceAuthority.VENDOR


def test_disabled_or_keyless_never_uses_transport_and_is_not_score_eligible() -> None:
    calls: list[str] = []
    disabled = FmpProvider(transport=lambda *args: calls.append("disabled"))
    missing_key = FmpProvider(
        section=ProviderSection(active_provider="fmp", base_url="https://financialmodelingprep.com/stable/"),
        transport=lambda *args: calls.append("keyless"),
    )

    disabled_result = disabled.fetch_prices(["ABC"], START, END)
    keyless_result = missing_key.fetch_prices(["ABC"], START, END)

    assert calls == []
    assert disabled.probe_capabilities()[0].entitlement == "disabled"
    assert missing_key.probe_capabilities()[0].entitlement == "api_key_required"
    assert not disabled.probe_capabilities()[0].score_eligible
    assert not missing_key.probe_capabilities()[0].score_eligible
    assert disabled_result.status == keyless_result.status == "unavailable"
    _assert_metadata(disabled_result)
    _assert_metadata(keyless_result)


def test_every_result_has_licence_quota_cache_and_authority_metadata() -> None:
    provider = FmpProvider()
    results = [
        provider.fetch_prices(["ABC"], START, END),
        provider.fetch_fx(["EURUSD"], START, END),
        provider.fetch_etf_metadata(["ISIN"]),
        provider.fetch_etf_holdings(["ISIN"]),
    ]

    for result in results:
        _assert_metadata(result)

    assert "optional_commercial" in FMP_SHARED_CONFIG_BLOCK
    assert "mandatory_allowed: false" in FMP_SHARED_CONFIG_BLOCK
    assert "quota_failure: non_blocking" in FMP_SHARED_CONFIG_BLOCK


def test_vendor_disagreement_records_conflict_and_preserves_official_value() -> None:
    provider = FmpProvider()
    official = pd.DataFrame([{"symbol": "ABC", "date": "2024-01-02", "close": 100.0}])
    vendor = pd.DataFrame([{
        "symbol": "ABC",
        "date": "2024-01-02",
        "close": 101.0,
        "known_at": "2024-01-03T00:00:00+00:00",
    }])

    result = provider.verify_against_official(
        vendor,
        official,
        decision_time=datetime(2024, 1, 4, tzinfo=timezone.utc),
    )

    assert result.status == "ok"
    pd.testing.assert_frame_equal(result.data, official)
    assert len(result.conflicts) == 1
    assert result.conflicts[0]["selected_authority"] == "official"
    assert result.conflicts[0]["vendor_value"] == 101.0
    assert result.conflicts[0]["official_value"] == 100.0
    _assert_metadata(result)


def test_quota_exhaustion_is_non_blocking_fingerprinted_and_key_is_redacted() -> None:
    def transport(url, headers, timeout):
        assert parse_qs(urlparse(url).query)["apikey"] == ["private-fmp-key"]
        return 429, b""

    result = _configured(transport).fetch_prices(["ABC"], START, END)

    assert result.status == "unavailable"
    assert result.quota["status"] == "rate_limited"
    assert result.quota["failure_policy"] == "non_blocking"
    assert result.error_fingerprint
    assert "private-fmp-key" not in str(result)
    _assert_metadata(result)


def test_successful_vendor_fetch_is_cached_and_not_score_eligible() -> None:
    calls: list[str] = []

    def transport(url, headers, timeout):
        calls.append(url)
        return 200, b'[{"symbol":"ABC","date":"2024-01-02","close":101.0}]'

    provider = _configured(transport)
    first = provider.fetch_prices(["ABC"], START, END)
    second = provider.fetch_prices(["ABC"], START, END)

    assert len(calls) == 1
    assert first.status == second.status == "ok"
    assert first.cache["hit"] is False
    assert second.cache["hit"] is True
    assert first.data is not None and not first.data["score_eligible"].any()
    assert second.data is not None and not second.data["score_eligible"].any()
    _assert_metadata(first)
    _assert_metadata(second)


def test_vendor_values_known_after_decision_time_are_unavailable() -> None:
    provider = FmpProvider()
    official = pd.DataFrame([{"symbol": "ABC", "date": "2024-01-02", "close": 100.0}])
    vendor = pd.DataFrame([{
        "symbol": "ABC",
        "date": "2024-01-02",
        "close": 101.0,
        "known_at": "2024-01-03T00:00:00+00:00",
    }])

    result = provider.verify_against_official(
        vendor,
        official,
        decision_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )

    assert result.status == "unavailable"
    assert result.conflicts == ()
    _assert_metadata(result)


def test_absent_provider_keeps_core_official_output_usable() -> None:
    official = pd.DataFrame([{"symbol": "ABC", "date": "2024-01-02", "close": 100.0}])
    absent = FmpProvider().fetch_prices(["ABC"], START, END)

    assert absent.status == "unavailable"
    assert absent.data is None
    pd.testing.assert_frame_equal(official, pd.DataFrame([{"symbol": "ABC", "date": "2024-01-02", "close": 100.0}]))
    _assert_metadata(absent)
