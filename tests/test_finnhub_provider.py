from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.finnhub_provider import (
    CAPABILITIES,
    SHARED_CONFIG_BLOCK,
    FinnhubProvider,
)


TOKEN = "finnhub-test-secret-value"
FROM = 1_700_000_000
TO = 1_700_086_400


def _section() -> ProviderSection:
    return ProviderSection(active_provider="finnhub", api_key=TOKEN)


def _probe_inputs() -> dict[str, dict[str, object]]:
    return {
        "prices": {"symbol": "caller-price-symbol", "resolution": "D", "from": FROM, "to": TO},
        "fx": {"symbol": "caller-fx-symbol", "resolution": "D", "from": FROM, "to": TO},
        "etf_metadata": {"isin": "caller-etf-isin"},
        "etf_holdings": {"isin": "caller-etf-isin", "date": "2023-11-15"},
    }


def _covered_candles() -> dict[str, object]:
    return {"s": "ok", "t": [FROM, TO]}


def test_disabled_experimental_provider_has_no_io_and_reports_disabled() -> None:
    calls: list[str] = []
    provider = FinnhubProvider(
        _section(),
        transport=lambda url, _headers, _timeout: calls.append(url),
    )

    capabilities = provider.probe_entitlements(_probe_inputs())

    assert calls == []
    assert {item.dataset_type for item in capabilities} == set(CAPABILITIES)
    assert all(item.status == "unavailable" and item.entitlement == "disabled" for item in capabilities)


def test_probe_checks_every_capability_and_keeps_entitlement_per_endpoint() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str], _timeout: float):
        calls.append((url, headers))
        if url.endswith("/stock/candle?symbol=caller-price-symbol&resolution=D&from=1700000000&to=1700086400"):
            return {"s": "ok", "t": [FROM, TO]}
        if "/forex/candle?" in url:
            return {"error": "Access denied"}, 403
        if "/etf/profile?" in url:
            return {"error": "rate limited"}, 429
        if "/etf/holdings?" in url:
            return {"atDate": "2023-11-15", "holdings": []}, 200
        raise AssertionError(f"unexpected Finnhub endpoint: {url}")

    provider = FinnhubProvider(_section(), enabled=True, terms_accepted=True, transport=transport)
    capabilities = {item.dataset_type: item for item in provider.probe_entitlements(_probe_inputs())}

    assert len(calls) == len(CAPABILITIES)
    assert all(headers["X-Finnhub-Token"] == TOKEN for _, headers in calls)
    assert all("token=" not in url for url, _ in calls)
    assert capabilities["prices"].entitlement == "entitled"
    assert capabilities["prices"].score_eligible is False
    assert capabilities["fx"].status == "forbidden"
    assert capabilities["fx"].score_eligible is False
    assert capabilities["etf_metadata"].entitlement == "unknown"
    assert capabilities["etf_metadata"].status == "unavailable"
    assert capabilities["etf_holdings"].entitlement == "entitled"


def test_401_and_403_are_forbidden_only_for_their_capabilities() -> None:
    def transport(url: str, _headers: dict[str, str], _timeout: float):
        if "/stock/candle?" in url:
            return {"error": "Unauthorized"}, 401
        if "/forex/candle?" in url:
            return {"error": "Forbidden"}, 403
        return {"error": "Unavailable"}, 429

    provider = FinnhubProvider(_section(), enabled=True, terms_accepted=True, transport=transport)
    capabilities = {item.dataset_type: item for item in provider.probe_entitlements(_probe_inputs())}

    assert capabilities["prices"].status == "forbidden"
    assert capabilities["fx"].status == "forbidden"
    assert capabilities["prices"].error_fingerprint
    assert capabilities["fx"].error_fingerprint
    assert capabilities["etf_metadata"].status == "unavailable"
    assert capabilities["etf_holdings"].status == "unavailable"
    assert all(not item.score_eligible for item in capabilities.values())


def test_historical_use_rejects_missing_entitlement_coverage_and_pit_metadata() -> None:
    provider = FinnhubProvider(_section(), enabled=True, terms_accepted=True, transport=lambda *_: _covered_candles())
    frame = pd.DataFrame({"date": [date(2023, 11, 14)], "close": [1.0]})
    decision_time = datetime(2023, 11, 16, tzinfo=timezone.utc)

    no_entitlement = provider.validate_historical_data(
        "prices", frame, start_date=date(2023, 11, 14), end_date=date(2023, 11, 14), decision_time=decision_time
    )
    assert no_entitlement.status == "unavailable"
    assert "entitlement" in no_entitlement.message.lower()

    requests = _probe_inputs()
    requests["prices"] = {"symbol": "caller-price-symbol", "resolution": "D", "from": 1_700_000_000, "to": 1_700_086_400}
    provider.probe_entitlements(requests)
    uncovered = provider.validate_historical_data(
        "prices", frame, start_date=date(2020, 1, 1), end_date=date(2020, 1, 1), decision_time=decision_time
    )
    assert uncovered.status == "unavailable"
    assert "coverage" in uncovered.message.lower()

    missing_pit = provider.validate_historical_data(
        "prices", frame, start_date=date(2023, 11, 14), end_date=date(2023, 11, 14), decision_time=decision_time
    )
    assert missing_pit.status == "unavailable"
    assert "point-in-time metadata is missing" in missing_pit.message.lower()


def test_historical_use_rejects_point_in_time_values_after_decision() -> None:
    provider = FinnhubProvider(_section(), enabled=True, terms_accepted=True, transport=lambda *_: _covered_candles())
    provider.probe_entitlements(_probe_inputs())
    frame = pd.DataFrame(
        {
            "date": [date(2023, 11, 14)],
            "known_at": ["2023-11-16T00:00:00+00:00"],
            "available_at": ["2023-11-16T00:00:00+00:00"],
        }
    )

    result = provider.validate_historical_data(
        "prices",
        frame,
        start_date=date(2023, 11, 14),
        end_date=date(2023, 11, 14),
        decision_time=datetime(2023, 11, 15, tzinfo=timezone.utc),
    )

    assert result.status == "unavailable"
    assert "after the decision time" in result.message


def test_historical_use_accepts_only_when_entitlement_coverage_and_pit_are_proven() -> None:
    provider = FinnhubProvider(_section(), enabled=True, terms_accepted=True, transport=lambda *_: _covered_candles())
    provider.probe_entitlements(_probe_inputs())
    frame = pd.DataFrame(
        {
            "date": [date(2023, 11, 14)],
            "known_at": ["2023-11-14T23:00:00+00:00"],
            "available_at": ["2023-11-14T23:01:00+00:00"],
        }
    )

    result = provider.validate_historical_data(
        "prices",
        frame,
        start_date=date(2023, 11, 14),
        end_date=date(2023, 11, 14),
        decision_time=datetime(2023, 11, 15, tzinfo=timezone.utc),
    )

    assert result.status == "ok"
    assert result.data is not None
    assert result.data.equals(frame)


def test_provider_authority_is_vendor_only_and_never_score_or_release_authoritative() -> None:
    provider = FinnhubProvider(_section(), enabled=True, terms_accepted=True, transport=lambda *_: _covered_candles())
    capabilities = provider.probe_entitlements(_probe_inputs())

    assert all(item.authority is SourceAuthority.VENDOR for item in capabilities)
    assert all(item.authority.rank <= SourceAuthority.VENDOR.rank for item in capabilities)
    assert all(item.score_eligible is False for item in capabilities)
    assert all("release" in item.message.lower() or "authority" in item.message.lower() for item in capabilities)
    assert all(row.status == "unavailable" for row in (
        provider.fetch_prices([], date(2023, 11, 14), date(2023, 11, 15)),
        provider.fetch_fx([], date(2023, 11, 14), date(2023, 11, 15)),
        provider.fetch_etf_metadata([]),
        provider.fetch_etf_holdings([]),
    ))


def test_probe_failure_fingerprint_does_not_leak_token() -> None:
    def transport(_url: str, _headers: dict[str, str], _timeout: float):
        raise RuntimeError(f"request failed for token={TOKEN}")

    provider = FinnhubProvider(_section(), enabled=True, terms_accepted=True, transport=transport)
    capabilities = provider.probe_entitlements(_probe_inputs())

    assert all(item.error_fingerprint for item in capabilities)
    assert all(TOKEN not in str(item.to_dict()) for item in capabilities)


def test_terms_acknowledgement_is_required_before_network_probe() -> None:
    calls: list[str] = []
    provider = FinnhubProvider(
        _section(),
        enabled=True,
        transport=lambda url, _headers, _timeout: calls.append(url),
    )

    capabilities = provider.probe_entitlements(_probe_inputs())

    assert calls == []
    assert all(item.entitlement == "terms_required" for item in capabilities)


def test_shared_config_block_keeps_provider_disabled_and_optional() -> None:
    assert "active_provider: none" in SHARED_CONFIG_BLOCK
    assert "source_tier: optional_commercial" in SHARED_CONFIG_BLOCK
    assert "mandatory_allowed: false" in SHARED_CONFIG_BLOCK
    assert "non-blocking" in SHARED_CONFIG_BLOCK
