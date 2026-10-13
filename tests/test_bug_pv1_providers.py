"""Bughunt A (#954): provider adapters, source policy and retrieval cache.

Every test is offline: fixtures and mocks only, no network, no owner data.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

import pandas as pd
import pytest

from etf_cockpit.core import http_fetch
from etf_cockpit.core.config import DataProvidersConfig, ProviderSection
from etf_cockpit.data import bulk_cache
from etf_cockpit.data.alphavantage_provider import AlphaVantageProvider
from etf_cockpit.data.bulk_cache import BulkCacheError, ContentAddressedCache, DownloadRequest, DownloadResponse
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority
from etf_cockpit.data.finnhub_provider import FinnhubProvider
from etf_cockpit.data.fmp_provider import FmpProvider
from etf_cockpit.data.provider_registry import ProviderRegistry
from etf_cockpit.data.retrieval_batch import BatchRetriever
from etf_cockpit.data.source_policy import SourcePolicyError, load_source_policies
from etf_cockpit.data.stooq_provider import StooqProvider
from etf_cockpit.data.tiingo_provider import TiingoProvider
from etf_cockpit.data.twelvedata_provider import RateLimiter, TwelveDataProvider
from etf_cockpit.data.yfinance_provider import YFinanceProvider, _fund_operation_value
from etf_cockpit.signals.simple_scores import _price_liquidity_lookup

UTC = timezone.utc


# --------------------------------------------------------------------------- yfinance


class _FundsData:
    def __init__(self, operations: pd.DataFrame) -> None:
        self.fund_overview = {"family": "Fam", "legalType": "ETF"}
        self.fund_operations = operations
        self.top_holdings = pd.DataFrame()


def _ticker_factory(operations: pd.DataFrame):
    class _Ticker:
        info = {"currency": "EUR", "quoteType": "ETF", "longName": "Fund"}
        fast_info = {"currency": "EUR"}
        funds_data = _FundsData(operations)

    return lambda _symbol: _Ticker()


def _operations(own: float | None, category: float | None) -> pd.DataFrame:
    return pd.DataFrame(
        {"VWCE.DE": [own], "Category Average": [category]},
        index=pd.Index(["Annual Report Expense Ratio"], name="Attributes"),
    )


def test_a102_n001_missing_own_symbol_ter_never_takes_category_average(monkeypatch) -> None:
    frame = _operations(None, 0.0075)
    assert _fund_operation_value(frame, "VWCE.DE", "Annual Report Expense Ratio") is None
    assert _fund_operation_value(_operations(0.002, 0.0075), "VWCE.DE", "Annual Report Expense Ratio") == 0.002
    assert _fund_operation_value(frame, "OTHER.DE", "Annual Report Expense Ratio") is None

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=_ticker_factory(frame)))
    section = ProviderSection(symbols_map={"VWCE": "VWCE.DE"})

    configured = YFinanceProvider(section, instrument_metadata={"VWCE": {"configured_ter": 0.002}}).fetch_etf_metadata([])
    assert configured.data is not None
    assert configured.data.iloc[0]["ter"] == 0.002
    assert configured.data.iloc[0]["ter_source"] == "configured"

    unavailable = YFinanceProvider(section).fetch_etf_metadata([])
    assert unavailable.data is not None
    assert pd.isna(unavailable.data.iloc[0]["ter"])
    assert unavailable.data.iloc[0]["ter_source"] == "unavailable"


def _download_frame(with_volume: bool) -> pd.DataFrame:
    data = {
        "Open": [10.0, 10.5],
        "High": [10.8, 10.9],
        "Low": [9.8, 10.2],
        "Close": [10.4, 10.7],
        "Adj Close": [10.3, 10.6],
    }
    if with_volume:
        data["Volume"] = [1000, 1200]
    return pd.DataFrame(data, index=pd.to_datetime(["2026-06-25", "2026-06-26"]))


def test_a102_n002_missing_volume_is_nan_and_liquidity_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *a, **k: _download_frame(False)))
    result = YFinanceProvider(ProviderSection(symbols_map={"A": "A.OL"})).fetch_prices([], date(2026, 6, 1), date(2026, 6, 30))

    assert result.ok and result.data is not None
    assert result.data["volume"].isna().all()
    liquidity = _price_liquidity_lookup(result.data.assign(currency="EUR"), currency_by_id={"A": "EUR"})
    assert liquidity["A"]["avg_turnover_20"] is None

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *a, **k: _download_frame(True)))
    with_volume = YFinanceProvider(ProviderSection(symbols_map={"A": "A.OL"})).fetch_prices([], date(2026, 6, 1), date(2026, 6, 30))
    assert with_volume.data is not None and with_volume.data["volume"].tolist() == [1000.0, 1200.0]


def test_a002_n003_mixed_row_currencies_are_recorded_as_mixed(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *a, **k: _download_frame(True)))
    provider = YFinanceProvider(
        ProviderSection(symbols_map={"A": "A.OL", "B": "B.US"}),
        default_currency="EUR",
        instrument_metadata={"A": {"currency": "EUR"}, "B": {"currency": "USD"}},
    )
    result = provider.fetch_prices([], date(2026, 6, 1), date(2026, 6, 30))
    assert result.metadata is not None and result.metadata.currency == "mixed"

    usd_only = YFinanceProvider(
        ProviderSection(symbols_map={"B": "B.US"}),
        default_currency="EUR",
        instrument_metadata={"B": {"currency": "USD"}},
    ).fetch_prices([], date(2026, 6, 1), date(2026, 6, 30))
    assert usd_only.metadata is not None and usd_only.metadata.currency == "USD"


# --------------------------------------------------------------------------- stooq


def _csv_response(text: str):
    return SimpleNamespace(text=text, status_code=200, headers={}, raise_for_status=lambda: None)


def test_a102_n003_disabled_stooq_makes_no_network_call(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("requests.get", lambda *a, **k: calls.append("get") or _csv_response(""))

    disabled = StooqProvider(ProviderSection(active_provider="none"))
    assert disabled.fetch_daily_prices("vwce.de", date(2026, 9, 21), date(2026, 9, 22)).empty
    assert disabled.validate_symbol("vwce.de") is False
    assert StooqProvider().fetch_daily_prices("vwce.de", date(2026, 9, 21), date(2026, 9, 22)).empty
    assert calls == []


def test_a102_n004_stooq_rejects_out_of_range_dates(monkeypatch) -> None:
    csv = "Date,Open,High,Low,Close,Volume\n2026-09-20,1,1,1,1,1\n2026-09-21,1,1,1,1,1\n2026-09-22,1,1,1,1,1\n2026-09-23,1,1,1,1,1\n"
    monkeypatch.setattr("requests.get", lambda *a, **k: _csv_response(csv))
    stooq = StooqProvider(ProviderSection(active_provider="stooq"))

    frame = stooq.fetch_daily_prices("vwce.de", date(2026, 9, 21), date(2026, 9, 22))

    assert frame["date"].tolist() == [date(2026, 9, 21), date(2026, 9, 22)]
    assert stooq.fetch_daily_prices("vwce.de", date(2026, 9, 22), date(2026, 9, 21)).empty


# --------------------------------------------------------------------------- source policy / registry


def _policy_file(tmp_path: Path, **overrides: object) -> Path:
    row = {
        "provider_id": "demo",
        "dataset_type": "prices",
        "source_tier": "optional_commercial",
        "mandatory_allowed": False,
        "optional_provider": True,
        "cache_path": "data/raw/demo",
        "licence": "x",
        "network_required": True,
    }
    row.update(overrides)
    path = tmp_path / "policy.yaml"
    path.write_text(
        json.dumps({"schema_version": "data-source-policy.v1", "quota_failure": "non_blocking", "sources": [row]}),
        encoding="utf-8",
    )
    return path


def test_a101_n001_quoted_false_is_false_and_garbage_is_rejected(tmp_path: Path) -> None:
    quoted = load_source_policies(_policy_file(tmp_path, mandatory_allowed="false", optional_provider="false", network_required="true"))[0]
    assert quoted.mandatory_allowed is False
    assert quoted.optional_provider is False
    assert quoted.network_required is True
    for bad in ("maybe", 1, "", None):
        with pytest.raises(SourcePolicyError):
            load_source_policies(_policy_file(tmp_path, mandatory_allowed=bad))


class _SelfDeclaredOfficial:
    def __init__(self, *, configured: bool = True) -> None:
        self.section = ProviderSection(active_provider="fmp", api_key="k")
        self._configured = configured

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        return (
            ProviderCapability(
                provider_id="fmp",
                dataset_type="prices",
                status="ok",
                authority=SourceAuthority.OFFICIAL,
                configured=self._configured,
                entitlement="entitled",
                rate_limit_note="",
                last_success_at=None,
                error_fingerprint=None,
            ),
        )


def _fmp_registry(adapter: object) -> ProviderRegistry:
    config = DataProvidersConfig(providers={"fmp": ProviderSection(active_provider="fmp", api_key="fmp-test-key")})
    registry = ProviderRegistry(config)
    registry.register_adapter("fmp", adapter)
    return registry


def test_a101_n002_adapter_official_does_not_override_registry_vendor(monkeypatch) -> None:
    monkeypatch.setenv("ETF_COCKPIT_FMP_API_KEY", "fmp-test-key")
    capability = next(item for item in _fmp_registry(_SelfDeclaredOfficial()).probe_all() if item.provider_id == "fmp")
    assert capability.authority is SourceAuthority.VENDOR


def test_a01_c2_n001_adapter_configured_false_is_not_overridden(monkeypatch) -> None:
    monkeypatch.setenv("ETF_COCKPIT_FMP_API_KEY", "fmp-test-key")
    capability = next(item for item in _fmp_registry(_SelfDeclaredOfficial(configured=False)).probe_all() if item.provider_id == "fmp")
    assert capability.configured is False
    assert capability.score_eligible is False


def test_a01_c2_n003_unclassified_source_is_not_mandatory_compatible(monkeypatch) -> None:
    registry = ProviderRegistry(DataProvidersConfig())
    capability = ProviderCapability("zz_unknown", "prices", "unavailable", SourceAuthority.VENDOR, False, "disabled", "", None, None)
    monkeypatch.setattr("etf_cockpit.data.provider_registry.load_source_policies", lambda: (_ for _ in ()).throw(SourcePolicyError("bad")))
    row = registry.status_rows([capability])[0]
    assert row["source_tier"] == "unclassified"
    assert row["optionality"] != "mandatory-compatible"


def test_a101_n003_has_api_key_reflects_resolved_credential(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.data import trust_artifacts

    secret_present = ProviderCapability("p1", "prices", "unavailable", SourceAuthority.VENDOR, True, "configured", "", None, None, secret_present=True)
    secret_absent = ProviderCapability("p2", "prices", "unavailable", SourceAuthority.VENDOR, True, "configured", "", None, None, secret_present=False)

    class _Registry:
        def __init__(self, _config) -> None:
            pass

        def probe_all(self):
            return (secret_present, secret_absent)

    captured: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(trust_artifacts, "ProviderRegistry", _Registry)
    # p1 has no key in config (resolved from vault/env); p2 has a stale config key but no resolved credential.
    sections = {"p1": ProviderSection(active_provider="p1"), "p2": ProviderSection(active_provider="p2", api_key="stale")}
    monkeypatch.setattr(trust_artifacts, "_provider_section_for", lambda _config, pid: (sections[pid], "prices"))
    monkeypatch.setattr(trust_artifacts, "_write_dual", lambda frame, _path: captured.update(frame=frame) or tmp_path)
    trust_artifacts.write_provider_probe_results(SimpleNamespace(data_providers=None))

    rows = captured["frame"].set_index("provider_id")
    assert bool(rows.loc["p1", "has_api_key"]) is True
    assert bool(rows.loc["p2", "has_api_key"]) is False


# --------------------------------------------------------------------------- alpha vantage


def _alpha_payload() -> dict[str, object]:
    return {
        "Time Series (Daily)": {
            "2026-01-02": {"1. open": "10", "2. high": "11", "3. low": "9", "4. close": "10.5", "5. volume": "100"},
        }
    }


def test_a103_n003_alpha_known_at_is_retrieval_time_not_midnight() -> None:
    retrieved = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
    provider = AlphaVantageProvider(
        section=ProviderSection(active_provider="alphavantage", api_key="alpha-key"),
        transport=lambda url, headers: (json.dumps(_alpha_payload()).encode(), 200),
        clock=lambda: retrieved,
    )
    early = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3), decision_time=datetime(2026, 1, 2, 10, 0, tzinfo=UTC))
    assert early.status == "unavailable" and early.data is None

    late = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3), decision_time=datetime(2026, 1, 2, 16, 0, tzinfo=UTC))
    assert late.status == "ok" and late.data is not None
    assert pd.Timestamp(late.data.loc[0, "known_at"]) == pd.Timestamp("2026-01-02 15:00:00")

    # A date-only clock carries no time of day: rows are stamped at the end of that day, never at midnight.
    date_clock = AlphaVantageProvider(
        section=ProviderSection(active_provider="alphavantage", api_key="alpha-key"),
        transport=lambda url, headers: (json.dumps(_alpha_payload()).encode(), 200),
        clock=lambda: date(2026, 1, 2),
    )
    same_day = date_clock.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3), decision_time=datetime(2026, 1, 2, 10, 0, tzinfo=UTC))
    assert same_day.data is None


def test_a103_n001_n002_alpha_sends_documented_apikey_and_free_tier_outputsize() -> None:
    seen: list[str] = []

    def transport(url: str, headers: dict[str, str]):
        seen.append(url)
        return json.dumps(_alpha_payload()).encode(), 200

    provider = AlphaVantageProvider(section=ProviderSection(active_provider="alphavantage", api_key="alpha-key"), transport=transport)
    result = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))

    assert "apikey=alpha-key" in seen[0]
    assert "outputsize=compact" in seen[0] and "outputsize=full" not in seen[0]
    assert "alpha-key" not in result.message

    premium = AlphaVantageProvider(section=ProviderSection(active_provider="alphavantage", api_key="alpha-key"), transport=transport, outputsize="full")
    premium.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))
    assert "outputsize=full" in seen[-1]
    with pytest.raises(ValueError):
        AlphaVantageProvider(outputsize="huge")


def test_a103_n008_alpha_transport_typeerror_is_not_retried() -> None:
    calls: list[str] = []

    def transport(url: str, headers: dict[str, str], extra: object = None):
        calls.append(url)
        raise TypeError("bug inside the transport")

    provider = AlphaVantageProvider(section=ProviderSection(active_provider="alphavantage", api_key="alpha-key"), transport=transport)
    result = provider.fetch_prices(["MSFT"], date(2026, 1, 1), date(2026, 1, 3))

    assert result.status == "unavailable"
    assert len(calls) == 1


def test_a103_n004_alpha_replay_is_symbol_scoped_and_daily_wrapper_needs_ok(tmp_path: Path) -> None:
    section = ProviderSection(active_provider="alphavantage", api_key="alpha-key", symbols_map={"AAA": "X.DE", "BBB": "X.DE", "CCC": "Y.DE"})
    clock = lambda: datetime(2026, 1, 2, 15, 0, tzinfo=UTC)  # noqa: E731
    first = AlphaVantageProvider(section=section, cache_dir=tmp_path, transport=lambda url, headers: (json.dumps(_alpha_payload()).encode(), 200), clock=clock)
    assert first.fetch_prices(["AAA"], date(2026, 1, 1), date(2026, 1, 3)).status == "ok"

    failing = AlphaVantageProvider(section=section, cache_dir=tmp_path, transport=lambda url, headers: (b"", 500), clock=lambda: datetime(2026, 1, 3, tzinfo=UTC))
    replay = failing.fetch_prices(["BBB"], date(2026, 1, 1), date(2026, 1, 3))
    assert replay.status == "unavailable" and replay.data is not None
    assert replay.data["etf_id"].unique().tolist() == ["BBB"]
    assert failing.fetch_prices(["CCC"], date(2026, 1, 1), date(2026, 1, 3)).data is None
    assert failing.fetch_daily_prices("BBB", date(2026, 1, 1), date(2026, 1, 3)).empty


# --------------------------------------------------------------------------- FMP


def _fmp(transport, **kwargs) -> FmpProvider:
    section = ProviderSection(active_provider="fmp", api_key="private-fmp-key", base_url="https://financialmodelingprep.com/stable/")
    return FmpProvider(section=section, transport=transport, **kwargs)


def test_a103_n005_fmp_returned_identity_must_match_request() -> None:
    other = _fmp(lambda url, headers, timeout: (200, b'[{"symbol":"XYZ","date":"2024-01-02","close":1.0}]'))
    result = other.fetch_prices(["ABC"], date(2024, 1, 1), date(2024, 1, 2))
    assert result.status == "unavailable" and result.data is None

    anonymous = _fmp(lambda url, headers, timeout: (200, b'[{"date":"2024-01-02","close":1.0}]'))
    assert anonymous.fetch_prices(["ABC"], date(2024, 1, 1), date(2024, 1, 2)).status == "unavailable"

    matching = _fmp(lambda url, headers, timeout: (200, b'[{"symbol":"abc","date":"2024-01-02","close":1.0}]'))
    assert matching.fetch_prices(["ABC"], date(2024, 1, 1), date(2024, 1, 2)).status == "ok"


def test_a103_n006_fmp_missing_vendor_value_is_unknown_not_zero_conflicts() -> None:
    official = pd.DataFrame([{"symbol": "ABC", "date": "2024-01-02", "close": 100.0, "known_at": "2024-01-01T00:00:00+00:00"}])
    vendor = pd.DataFrame([{"symbol": "ABC", "date": "2024-01-02", "close": None, "known_at": "2024-01-01T00:00:00+00:00"}])

    result = FmpProvider().verify_against_official(vendor, official, decision_time=datetime(2024, 1, 4, tzinfo=UTC))

    assert result.status == "unavailable"
    details = json.loads(result.metadata.notes)  # type: ignore[union-attr]
    assert details["conflicts"] == [] and len(details["unknown_comparisons"]) == 1

    nothing_in_common = vendor.assign(date="2024-02-01", close=1.0)
    assert FmpProvider().verify_against_official(nothing_in_common, official, decision_time=datetime(2024, 1, 4, tzinfo=UTC)).status == "unavailable"


def test_a03_c2_n001_fmp_cache_key_includes_configuration() -> None:
    calls: list[str] = []

    def transport(url: str, headers: dict[str, str], timeout: float):
        calls.append(headers["apikey"])
        return 200, b'[{"symbol":"ABC","date":"2024-01-02","close":1.0}]'

    provider = _fmp(transport)
    provider.fetch_prices(["ABC"], date(2024, 1, 1), date(2024, 1, 2))
    provider.fetch_prices(["ABC"], date(2024, 1, 1), date(2024, 1, 2))
    assert len(calls) == 1
    provider.api_key = "another-plan-key"
    provider.section = provider.section.model_copy(update={"base_url": "https://financialmodelingprep.com/other/"})
    provider.fetch_prices(["ABC"], date(2024, 1, 1), date(2024, 1, 2))
    assert len(calls) == 2


# --------------------------------------------------------------------------- redirects


class _FakeOpener:
    def __init__(self, location: str) -> None:
        self.location = location
        self.opened: list[str] = []

    def open(self, request: Request, timeout: float | None = None):
        self.opened.append(request.full_url)
        if len(self.opened) == 1:
            raise HTTPError(request.full_url, 302, "Found", {"Location": self.location}, None)  # type: ignore[arg-type]
        return SimpleNamespace(read=lambda: b"[]", status=200)


def test_a103_n007_redirect_to_foreign_host_is_refused(monkeypatch) -> None:
    foreign = _FakeOpener("https://evil.example/steal")
    monkeypatch.setattr(http_fetch, "_NO_REDIRECT_OPENER", foreign)
    with pytest.raises(ValueError, match="source_redirect_not_supported"):
        http_fetch.host_checked_urlopen(Request("https://financialmodelingprep.com/stable/x", headers={"apikey": "k"}))
    assert foreign.opened == ["https://financialmodelingprep.com/stable/x"]

    downgrade = _FakeOpener("http://financialmodelingprep.com/stable/x")
    monkeypatch.setattr(http_fetch, "_NO_REDIRECT_OPENER", downgrade)
    with pytest.raises(ValueError):
        http_fetch.host_checked_urlopen(Request("https://financialmodelingprep.com/stable/x"))

    same_host = _FakeOpener("https://financialmodelingprep.com/stable/y")
    monkeypatch.setattr(http_fetch, "_NO_REDIRECT_OPENER", same_host)
    response = http_fetch.host_checked_urlopen(Request("https://financialmodelingprep.com/stable/x"))
    assert response.status == 200 and len(same_host.opened) == 2

    # The provider reports the refusal as unavailable and never contacts the foreign host.
    monkeypatch.setattr(http_fetch, "_NO_REDIRECT_OPENER", _FakeOpener("https://evil.example/steal"))
    result = FmpProvider(
        section=ProviderSection(active_provider="fmp", api_key="private-fmp-key", base_url="https://financialmodelingprep.com/stable/")
    ).fetch_prices(["ABC"], date(2024, 1, 1), date(2024, 1, 2))
    assert result.status == "unavailable"


def test_a103_n007_requests_based_providers_refuse_foreign_redirects(monkeypatch) -> None:
    requested: list[str] = []

    def fake_get(url: str, **kwargs):
        requested.append(url)
        assert kwargs["allow_redirects"] is False
        return SimpleNamespace(status_code=302, headers={"Location": "https://evil.example/steal"}, text="", json=lambda: {})

    monkeypatch.setattr("requests.get", fake_get)
    twelve = TwelveDataProvider(ProviderSection(active_provider="twelvedata", api_key="twelve-key"))
    tiingo = TiingoProvider(ProviderSection(active_provider="tiingo", api_key="tiingo-key"))
    stooq = StooqProvider(ProviderSection(active_provider="stooq"))

    assert twelve.fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5)).empty
    assert tiingo.fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5)).empty
    with pytest.raises(ValueError, match="source_redirect_not_supported"):
        stooq.fetch_daily_prices("aaa", date(2026, 1, 1), date(2026, 1, 5))
    assert all("evil.example" not in url for url in requested) and len(requested) == 3


# --------------------------------------------------------------------------- finnhub


FROM = 1_700_000_000
TO = 1_700_086_400


def _finnhub(**kwargs) -> FinnhubProvider:
    return FinnhubProvider(ProviderSection(active_provider="finnhub", api_key="finnhub-test-secret"), enabled=True, terms_accepted=True, **kwargs)


def _validate(provider: FinnhubProvider, start: date, end: date) -> object:
    frame = pd.DataFrame({"date": [start], "symbol": ["S"], "known_at": ["2023-11-20T00:00:00+00:00"], "available_at": ["2023-11-20T00:00:00+00:00"]})
    return provider.validate_historical_data("prices", frame, start_date=start, end_date=end, decision_time=datetime(2023, 11, 30, tzinfo=UTC))


def test_a03_c2_n003_finnhub_revoked_entitlement_invalidates_stale_validation() -> None:
    provider = _finnhub(transport=lambda url, headers, timeout: {"s": "ok", "t": [FROM, TO]})
    provider.probe_entitlements({"prices": {"symbol": "S", "resolution": "D", "from": FROM, "to": TO}})
    assert _validate(provider, date(2023, 11, 14), date(2023, 11, 15)).status == "ok"  # type: ignore[attr-defined]

    provider.terms_accepted = False
    assert _validate(provider, date(2023, 11, 14), date(2023, 11, 15)).status == "unavailable"  # type: ignore[attr-defined]
    provider.terms_accepted = True
    provider.section = provider.section.model_copy(update={"api_key": ""})
    assert _validate(provider, date(2023, 11, 14), date(2023, 11, 15)).status == "unavailable"  # type: ignore[attr-defined]


def test_a03_c2_n005_finnhub_weekend_edges_do_not_lose_coverage() -> None:
    saturday = 1_699_700_000  # 2023-11-11 (Saturday)
    sunday_end = 1_700_352_000  # 2023-11-19 (Sunday)
    candles = {"s": "ok", "t": [1_699_833_600, 1_700_179_200]}  # Monday 13th .. Thursday 16th... plus gap below
    candles["t"] = [1_699_833_600, 1_700_006_400, 1_700_265_600]  # Mon 13th, Wed 15th, Fri 17th
    provider = _finnhub(transport=lambda url, headers, timeout: candles)
    provider.probe_entitlements({"prices": {"symbol": "S", "resolution": "D", "from": saturday, "to": sunday_end}})
    capability = next(item for item in provider.probe_capabilities() if item.dataset_type == "prices")
    assert capability.entitlement == "entitled"
    assert "coverage metadata is missing" not in capability.message
    assert _validate(provider, date(2023, 11, 11), date(2023, 11, 19)).status == "ok"  # type: ignore[attr-defined]

    far_edge = {"s": "ok", "t": [1_700_265_600]}  # first candle > 4 days after the requested start
    unproven = _finnhub(transport=lambda url, headers, timeout: far_edge)
    unproven.probe_entitlements({"prices": {"symbol": "S", "resolution": "D", "from": saturday, "to": sunday_end}})
    assert _validate(unproven, date(2023, 11, 11), date(2023, 11, 19)).status == "unavailable"  # type: ignore[attr-defined]


def test_a103_n009_finnhub_records_entitlement_evidence_and_rejects_wrong_identity() -> None:
    provider = _finnhub(transport=lambda url, headers, timeout: {"s": "ok", "t": [FROM, TO]})
    provider.probe_entitlements({"prices": {"symbol": "S", "resolution": "D", "from": FROM, "to": TO}})
    prices = next(item for item in provider.probe_capabilities() if item.dataset_type == "prices")
    assert prices.last_success_at
    fx = next(item for item in provider.probe_capabilities() if item.dataset_type == "fx")
    assert fx.last_success_at is None

    mismatched = _finnhub(transport=lambda url, headers, timeout: {"s": "ok", "t": [FROM, TO], "symbol": "OTHER"})
    mismatched.probe_entitlements({"prices": {"symbol": "S", "resolution": "D", "from": FROM, "to": TO}})
    assert next(item for item in mismatched.probe_capabilities() if item.dataset_type == "prices").entitlement != "entitled"


# --------------------------------------------------------------------------- twelve data / tiingo


def _twelve(payload, **kwargs) -> TwelveDataProvider:
    return TwelveDataProvider(ProviderSection(active_provider="twelvedata", api_key="twelve-key"), transport=lambda url, headers: payload, **kwargs)


def _values(*days: str) -> list[dict[str, str]]:
    return [{"datetime": day, "open": "1", "high": "2", "low": "1", "close": "1.5", "volume": "10"} for day in days]


def test_a121_n003_twelvedata_null_meta_is_unavailable_not_an_exception() -> None:
    provider = _twelve({"meta": None, "values": _values("2026-01-02")})
    assert provider.fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5)).empty
    assert provider.fetch_intraday_prices("AAA", "5min", date(2026, 1, 1), date(2026, 1, 5)).empty
    assert len(_twelve({"values": _values("2026-01-02")}).fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5))) == 1
    assert _twelve({"meta": None, "values": []}).fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5)).empty
    assert _twelve({"meta": {"symbol": "BBB"}, "values": _values("2026-01-02")}).fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5)).empty


def test_a04_c2_n002_n003_out_of_window_bars_dropped_and_unsupported_interval_refused() -> None:
    twelve = _twelve({"meta": {}, "values": _values("2025-12-31", "2026-01-02", "2026-01-09")})
    assert twelve.fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5))["date"].tolist() == [date(2026, 1, 2)]

    calls: list[str] = []
    tiingo = TiingoProvider(
        ProviderSection(active_provider="tiingo", api_key="tiingo-key"),
        transport=lambda url, headers: calls.append(url) or [{"date": "2026-01-02T00:00:00.000Z", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1}],
    )
    assert tiingo.fetch_intraday_prices("AAA", interval="7min").empty
    assert calls == []
    daily = TiingoProvider(
        ProviderSection(active_provider="tiingo", api_key="tiingo-key"),
        transport=lambda url, headers: [
            {"date": "2025-12-30T00:00:00.000Z", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1},
            {"date": "2026-01-02T00:00:00.000Z", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1},
        ],
    ).fetch_daily_prices("AAA", date(2026, 1, 1), date(2026, 1, 5))
    assert daily["date"].tolist() == [date(2026, 1, 2)]


def test_a04_c2_n001_rate_limiter_is_atomic_under_concurrency() -> None:
    def slow_clock() -> float:
        time.sleep(0.002)  # widen the check-then-record window so an unlocked limiter overshoots
        return 100.0

    limiter = RateLimiter(calls_per_minute=5, clock=slow_clock)
    allowed: list[bool] = []
    barrier = threading.Barrier(16)

    def worker() -> None:
        barrier.wait()
        allowed.append(limiter.acquire().allowed)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(allowed) == 5


# --------------------------------------------------------------------------- retrieval cache


def test_a121_n004_unavailable_retrieval_is_not_cached_indefinitely(tmp_path: Path) -> None:
    now = [1_000_000.0]
    answers = [pd.DataFrame(), pd.DataFrame({"close": [1.0]})]
    calls: list[str] = []

    def downloader(symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        return answers[min(len(calls) - 1, 1)]

    def make() -> BatchRetriever:
        return BatchRetriever(
            provider="demo",
            cache_dir=tmp_path / "cache",
            checkpoint_path=tmp_path / "checkpoint.json",
            max_retries=0,
            clock=lambda: now[0],
            encode=lambda frame: frame.to_json(orient="table").encode(),
            decode=lambda payload: pd.read_json(__import__("io").BytesIO(payload), orient="table"),
            is_available=lambda frame: not frame.empty,
            unavailable_ttl_seconds=600.0,
            limiter=SimpleNamespace(acquire=lambda: None),  # type: ignore[arg-type]
        )

    first = make().retrieve(["AAA"], start=date(2026, 1, 1), end=date(2026, 1, 2), downloader=downloader)
    assert first.symbols["AAA"].status == "unavailable"
    now[0] += 300.0
    again = make().retrieve(["AAA"], start=date(2026, 1, 1), end=date(2026, 1, 2), downloader=downloader)
    assert again.symbols["AAA"].status == "unavailable" and len(calls) == 1  # still within the TTL
    now[0] += 600.0
    later = make().retrieve(["AAA"], start=date(2026, 1, 1), end=date(2026, 1, 2), downloader=downloader)
    assert later.symbols["AAA"].status == "done" and len(calls) == 2


# --------------------------------------------------------------------------- bulk cache


def test_a017_n001_206_resume_with_changed_validator_restarts(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    request = DownloadRequest("resumable", "https://example.test/file", expected_size=6, allowlisted_hosts=("example.test",))
    calls: list[int] = []

    class Interrupted:
        def __iter__(self):
            yield b"abc"
            raise OSError("fixture interruption")

    def fetcher(_request: DownloadRequest, offset: int) -> DownloadResponse:
        calls.append(offset)
        if offset == 0 and len(calls) == 1:
            return DownloadResponse(200, Interrupted(), etag='"v1"')
        if offset == 0:
            return DownloadResponse(200, [b"XYZ", b"123"], etag='"v2"')
        return DownloadResponse(206, [b"def"], total_size=3, etag='"v2"')

    with pytest.raises(OSError):
        cache.download(request, fetcher=fetcher)
    result = cache.download(request, fetcher=fetcher)

    assert calls == [0, 3, 0]
    assert result.resumed is False
    assert Path(tmp_path / result.manifest.object_path).read_bytes() == b"XYZ123"


def test_a017_n001_206_resume_with_same_validator_continues(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    request = DownloadRequest("resumable", "https://example.test/file", expected_size=6, allowlisted_hosts=("example.test",))
    calls: list[int] = []

    class Interrupted:
        def __iter__(self):
            yield b"abc"
            raise OSError("fixture interruption")

    def fetcher(_request: DownloadRequest, offset: int) -> DownloadResponse:
        calls.append(offset)
        if offset == 0:
            return DownloadResponse(200, Interrupted(), etag='"v1"')
        return DownloadResponse(206, [b"def"], total_size=3, etag='"v1"')

    with pytest.raises(OSError):
        cache.download(request, fetcher=fetcher)
    result = cache.download(request, fetcher=fetcher)
    assert calls == [0, 3] and result.resumed is True
    assert Path(tmp_path / result.manifest.object_path).read_bytes() == b"abcdef"


def test_a017_n003_promoted_bytes_are_verified_against_the_staged_hash(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    staged = cache.stage_generation("prices", b"valid", source_sha256="1" * 64)
    assert len(staged.payload_sha256) == 64

    (tmp_path / staged.relative_path).write_bytes(b"tampered")
    with pytest.raises(BulkCacheError, match="changed after staging"):
        cache.promote_generation(staged)
    assert not list((cache.generations).rglob("*.bin"))

    clean = cache.stage_generation("prices", b"valid-2", source_sha256="1" * 64)
    promoted = cache.promote_generation(clean)
    assert promoted.payload_sha256 == clean.payload_sha256
    assert (tmp_path / promoted.relative_path).read_bytes() == b"valid-2"


def test_a017_n002_health_flags_a_manifest_whose_object_is_missing(tmp_path: Path) -> None:
    cache = ContentAddressedCache(tmp_path)
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    result = cache.store_local_file("src", source)
    assert cache.health()["status"] == "passed"

    (tmp_path / result.manifest.object_path).unlink()
    report = cache.health()
    assert report["status"] == "failed"
    assert report["failures"]


def test_a103_n007_bulk_download_redirect_must_stay_on_allowlist(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []

    class _Opener:
        def open(self, request: Request, timeout: float | None = None):
            opened.append(request.full_url)
            raise HTTPError(request.full_url, 302, "Found", {"Location": "https://evil.example/x"}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(bulk_cache.urllib.request, "build_opener", lambda *handlers: _Opener())
    request = DownloadRequest("src", "https://example.test/file", allowlisted_hosts=("example.test",))
    with pytest.raises(BulkCacheError):
        ContentAddressedCache(tmp_path).download(request)
    assert opened == ["https://example.test/file"]
