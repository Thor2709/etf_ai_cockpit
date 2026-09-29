from __future__ import annotations

from datetime import date
import json

import pandas as pd

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.alphavantage_provider import AlphaVantageProvider


def _section(api_key: str = "") -> ProviderSection:
    return ProviderSection(active_provider="alphavantage", api_key=api_key)


def _payload() -> dict[str, object]:
    return {
        "Meta Data": {"2. Symbol": "MSFT"},
        "Time Series (Daily)": {
            "2026-01-02": {
                "1. open": "10.0",
                "2. high": "11.0",
                "3. low": "9.0",
                "4. close": "10.5",
                "5. volume": "100",
            }
        },
    }


def test_disabled_by_default_and_missing_key_makes_no_io() -> None:
    calls: list[str] = []
    provider = AlphaVantageProvider(transport=lambda url, headers: calls.append(url))

    capability = provider.probe_capabilities()[0]
    result = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))

    assert calls == []
    assert capability.status == "unavailable"
    assert capability.entitlement == "disabled"
    assert capability.score_eligible is False
    assert result.status == "unavailable"

    missing_key = AlphaVantageProvider(section=_section())
    assert missing_key.probe_capabilities()[0].entitlement == "api_key_required"


def test_daily_budget_returns_quota_exhausted_and_replays_cache(tmp_path) -> None:
    calls: list[str] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[bytes, int]:
        calls.append(url)
        return json.dumps(_payload()).encode(), 200

    provider = AlphaVantageProvider(
        section=_section("secret-key"),
        cache_dir=tmp_path,
        transport=transport,
        daily_call_budget=1,
    )
    first = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))
    second = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))

    assert first.status == "ok"
    assert second.status == "unavailable"
    assert second.quota_exhausted is True
    assert second.data is not None and len(second.data) == 1
    assert len(calls) == 1


def test_verification_only_refuses_universe_refresh() -> None:
    provider = AlphaVantageProvider(section=_section("secret-key"), transport=lambda *_: b"{}")

    result = provider.fetch_prices(["MSFT", "SPY"], date(2026, 1, 1), date(2026, 1, 3))

    assert result.status == "unavailable"
    assert "bulk" in result.message.lower()


def test_json_response_normalises_prices_and_redacts_key(tmp_path) -> None:
    secret = "secret-key"
    seen: list[str] = []
    seen_headers: list[dict[str, str]] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[bytes, int]:
        seen.append(url)
        seen_headers.append(headers)
        return json.dumps(_payload()).encode(), 200

    provider = AlphaVantageProvider(
        section=_section(secret),
        cache_dir=tmp_path,
        transport=transport,
    )
    result = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))

    assert result.status == "ok"
    assert isinstance(result.data, pd.DataFrame)
    assert result.data.loc[0, "close"] == 10.5
    assert result.data.loc[0, "source"] == "alphavantage"
    assert secret not in result.message
    assert secret not in str(provider.probe_capabilities()[0].to_dict())
    assert seen and all(secret not in url for url in seen)
    assert seen_headers[0]["X-Alpha-Vantage-Api-Key"] == secret


def test_http_error_and_429_are_non_blocking_without_canonical_mutation() -> None:
    calls = 0

    def transport(url: str, headers: dict[str, str]) -> tuple[bytes, int]:
        nonlocal calls
        calls += 1
        return b'{"error": "temporary"}', 500 if calls == 1 else 429

    provider = AlphaVantageProvider(section=_section("secret-key"), transport=transport)
    first = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))
    second = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))

    assert first.status == "unavailable"
    assert first.quota_exhausted is False
    assert first.data is None
    assert second.status == "unavailable"
    assert second.quota_exhausted is True
    assert second.data is None
    assert calls == 2


def test_post_decision_vendor_evidence_is_unavailable() -> None:
    provider = AlphaVantageProvider(
        section=_section("secret-key"),
        transport=lambda url, headers: (json.dumps(_payload()).encode(), 200),
        clock=lambda: date(2026, 1, 3),
    )

    result = provider.fetch_prices(
        ["MSFT"],
        date(2026, 1, 1),
        date(2026, 1, 3),
        decision_time=date(2026, 1, 2),
    )

    assert result.status == "unavailable"
    assert result.data is None
    assert "no rows" in result.message.lower()
