from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data.ecb_provider import EcbProvider
from etf_cockpit.data.fred_provider import FredProvider
from etf_cockpit.data.legal_terms import load_legal_terms
from etf_cockpit.data.macro_warehouse import MacroWarehouse
from etf_cockpit.features.macro import INDICATOR_IDS, macro_feature_value, macro_indicator, macro_indicators

FETCHED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
_FOREVER = "9999-12-31"


def _fred_payload(rows: list[tuple[str, str, str, str]]) -> bytes:
    observations = [
        {"realtime_start": start, "realtime_end": end, "date": date, "value": value}
        for date, value, start, end in rows
    ]
    return json.dumps({"count": len(observations), "observations": observations}).encode()


# UNRATE: January was first published as 3.7 and revised to 3.9 on 2024-03-08.
_UNRATE_VINTAGES = _fred_payload([
    ("2024-01-01", "3.7", "2024-02-02", "2024-03-07"),
    ("2024-01-01", "3.9", "2024-03-08", _FOREVER),
    ("2024-02-01", "3.9", "2024-03-08", _FOREVER),
    ("2024-03-01", ".", "2024-04-05", _FOREVER),
])


def _frame(root, decision_time: str, dataset_ids: tuple[str, ...]) -> pd.DataFrame:
    frames = [MacroWarehouse().as_of(root=root, dataset_id=name, decision_time=decision_time) for name in dataset_ids]
    return pd.concat(frames, ignore_index=True)


def test_fred_as_of_before_a_revision_returns_the_earlier_vintage(tmp_path) -> None:
    urls: list[str] = []

    def transport(url: str) -> bytes:
        urls.append(url)
        return _UNRATE_VINTAGES

    result = FredProvider(api_key="test-key", transport=transport).fetch_vintages("UNRATE", fetched_at=FETCHED_AT)
    assert result.status == "available"
    assert "realtime_start=1776-07-04" in urls[0] and f"realtime_end={_FOREVER}" in urls[0]
    warehouse = MacroWarehouse()
    warehouse.ingest_vintages(result.observations, root=tmp_path)
    warehouse.ingest_vintages(result.observations, root=tmp_path)  # a refresh with no new vintage is a no-op

    before = _frame(tmp_path, "2024-03-01T00:00:00+00:00", ("fred:UNRATE",))
    after = _frame(tmp_path, "2024-04-01T00:00:00+00:00", ("fred:UNRATE",))
    assert before["value"].tolist() == [3.7]
    assert after.sort_values("period_start")["value"].tolist() == [3.9, 3.9]
    assert macro_feature_value(before, series_id="UNRATE")["value"] == 3.7
    assert set(before["availability_confidence"]) == {"exact"}


def test_fred_series_fetched_without_vintages_cannot_enter_a_historical_feature(tmp_path) -> None:
    latest = _fred_payload([("2024-02-01", "3.9", "2026-01-01", "2026-01-01")])
    result = FredProvider(api_key="test-key", transport=lambda url: latest).fetch_latest("UNRATE", fetched_at=FETCHED_AT)
    assert result.status == "available"
    MacroWarehouse().ingest(list(result.observations), root=tmp_path)

    assert _frame(tmp_path, "2025-01-01T00:00:00+00:00", ("fred_latest:UNRATE",)).empty
    later = _frame(tmp_path, "2026-06-01T00:00:00+00:00", ("fred_latest:UNRATE",))
    assert len(later) == 1
    feature = macro_feature_value(later, series_id="UNRATE")
    assert feature["status"] == "unavailable" and "exact" in str(feature["reason"])


_EXR_CSV = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2025-12-30,1.1750,A,USD,0\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2025-12-31,,A,USD,0\n"
)
_RATE_CSV = (
    "KEY,FREQ,REF_AREA,CURRENCY,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
    "FM.B.U2.EUR.4F.KR.DFR.LEV,B,U2,EUR,DFR,2025-12-30,2.00,A,PCPA,0\n"
)


def test_ecb_fixture_import_stores_rate_and_fx_series_with_units_terms_and_timestamps(tmp_path) -> None:
    payloads = {"EXR": _EXR_CSV, "FM": _RATE_CSV}
    provider = EcbProvider(transport=lambda url: payloads[url.split("/service/data/")[1].split("/")[0]].encode())
    fx = provider.fetch("EXR", "D.USD.EUR.SP00.A", fetched_at=FETCHED_AT)
    rate = provider.fetch("FM", "B.U2.EUR.4F.KR.DFR.LEV", fetched_at=FETCHED_AT)
    assert fx.status == rate.status == "available"
    for result in (fx, rate):
        MacroWarehouse().ingest(list(result.observations), root=tmp_path)

    stored = MacroWarehouse().observations(root=tmp_path)
    by_series = {row.series_id: row for row in stored}
    # The blank FX value is skipped, not zero-filled.
    assert set(by_series) == {"EXR.D.USD.EUR.SP00.A", "FM.B.U2.EUR.4F.KR.DFR.LEV"}
    assert by_series["EXR.D.USD.EUR.SP00.A"].unit == "USD_per_EUR"
    assert by_series["FM.B.U2.EUR.4F.KR.DFR.LEV"].unit == "percent"
    registry = load_legal_terms()
    for row in stored:
        assert registry.entry(row.source_terms) is not None  # the legal-terms row resolves
        # Known when fetched, not when observed; the API has no vintage history.
        assert pd.Timestamp(row.available_at) == pd.Timestamp(row.ingested_at) == pd.Timestamp(FETCHED_AT)
        assert row.availability_confidence == "inferred"
    ecb_terms = registry.entry("ecb")
    text = f"{ecb_terms.terms_reference} {ecb_terms.review_note}".lower()
    assert "unmodified" in text and "third-part" in text and "permission" in text
    before_fetch = MacroWarehouse().as_of(
        root=tmp_path, dataset_id="ecb:EXR.D.USD.EUR.SP00.A", decision_time="2025-12-31T00:00:00+00:00"
    )
    assert before_fetch.empty


def _series(series_id: str, unit: str, points: dict[str, float]) -> list[dict[str, object]]:
    return [
        {"series_id": series_id, "period_start": period, "value": value, "unit": unit,
         "available_at": "2024-01-01T00:00:00+00:00", "availability_confidence": "exact"}
        for period, value in points.items()
    ]


def test_each_indicator_is_computed_from_exact_vintages_known_at_the_cutoff() -> None:
    months = pd.period_range("2023-01", "2024-03", freq="M").strftime("%Y-%m-01")
    unrate = dict(zip(months, [3.4, 3.4, 3.5, 3.4, 3.6, 3.6, 3.5, 3.8, 3.8, 3.8, 3.7, 3.7, 3.7, 3.9, 4.1]))
    rows = pd.DataFrame(
        _series("DGS10", "percent", {"2024-03-01": 4.0})
        + _series("DGS2", "percent", {"2024-03-01": 4.5})
        + _series("DGS3MO", "percent", {"2024-03-01": 5.0})
        + _series("BAA10Y", "percent", {"2024-03-01": 1.8})
        + _series("BAMLH0A0HYM2", "percent", {"2024-03-01": 3.1})
        + _series("NFCI", "index", {"2024-03-01": -0.5})
        + _series("VIXCLS", "index", {"2024-03-01": 14.0})
        + _series("UNRATE", "percent", unrate)
        + _series("SHILLER_CAPE", "ratio", {"2024-03-01": 30.0})
        + _series("DFII10", "percent", {"2024-03-01": 2.0})
        + _series("BOGZ1LM893064105Q", "millions_usd", {"2023-10-01": 54_000_000.0})
        + _series("GDP", "billions_usd", {"2023-10-01": 27_000.0, "2024-01-01": 28_000.0})
    )
    result = macro_indicators(rows)
    assert set(result) == set(INDICATOR_IDS)
    assert result["slope_10y_2y"]["value"] == pytest.approx(-0.5)
    assert result["slope_10y_3m"]["value"] == pytest.approx(-1.0)
    assert result["baa_10y_spread"]["value"] == 1.8
    assert result["hy_oas"]["value"] == 3.1
    assert result["nfci"]["value"] == -0.5 and result["vix"]["value"] == 14.0
    # Current 3-month average (3.9) less the lowest of the 12 preceding averages (March 2023).
    assert result["sahm_rule"]["value"] == pytest.approx(3.9 - (3.4 + 3.5 + 3.4) / 3)
    assert result["cape"]["value"] == 30.0
    assert result["equity_risk_premium"]["value"] == pytest.approx(100 / 30 - 2.0)
    assert result["market_cap_to_gdp"]["value"] == pytest.approx(200.0)

    # An input whose availability is not exact, or whose period differs for a same-period spread, is never used.
    inferred = rows.assign(availability_confidence=rows["availability_confidence"].where(rows["series_id"] != "DGS2", "inferred"))
    assert macro_indicator(inferred, "slope_10y_2y")["status"] == "unavailable"
    stale_leg = rows.assign(period_start=rows["period_start"].where(rows["series_id"] != "DGS2", "2024-02-01"))
    assert macro_indicator(stale_leg, "slope_10y_2y")["status"] == "unavailable"
    gdp_other_quarter = rows[~((rows["series_id"] == "GDP") & (rows["period_start"] == "2023-10-01"))]
    assert macro_indicator(gdp_other_quarter, "market_cap_to_gdp")["status"] == "unavailable"
    short_history = rows[~((rows["series_id"] == "UNRATE") & (rows["period_start"] < "2023-02-01"))]
    assert macro_indicator(short_history, "sahm_rule")["status"] == "unavailable"

    # Preceding 3-month averages are all 3.5; the current one is (3.5 + 3.5 + 5.6) / 3 = 4.2.
    flat = pd.DataFrame(_series("UNRATE", "percent", dict(zip(months, [3.5] * 14 + [5.6]))))
    assert macro_indicator(flat, "sahm_rule")["value"] == pytest.approx(0.70)
    # A new low is below every preceding average, so the rule is negative, never floored by the current month.
    falling = pd.DataFrame(_series("UNRATE", "percent", dict(zip(months, [5.0 - 0.1 * n for n in range(15)]))))
    assert macro_indicator(falling, "sahm_rule")["value"] == pytest.approx(-0.1)


def test_indicators_use_only_vintages_known_at_the_cutoff(tmp_path) -> None:
    payloads = {
        "DGS10": _fred_payload([
            ("2024-03-01", "4.0", "2024-03-02", "2024-04-01"),
            ("2024-03-01", "9.0", "2024-04-02", _FOREVER),
        ]),
        "DGS2": _fred_payload([("2024-03-01", "5.0", "2024-03-02", _FOREVER)]),
    }
    for series_id, payload in payloads.items():
        provider = FredProvider(api_key="test-key", transport=lambda url, payload=payload: payload)
        result = provider.fetch_vintages(series_id, fetched_at=FETCHED_AT)
        MacroWarehouse().ingest_vintages(result.observations, root=tmp_path)
    names = ("fred:DGS10", "fred:DGS2")
    early = macro_indicator(_frame(tmp_path, "2024-03-15T00:00:00+00:00", names), "slope_10y_2y")
    late = macro_indicator(_frame(tmp_path, "2024-05-01T00:00:00+00:00", names), "slope_10y_2y")
    assert early["value"] == pytest.approx(-1.0)
    assert late["value"] == pytest.approx(4.0)


def test_without_api_key_or_network_every_indicator_is_unavailable_not_zero(tmp_path) -> None:
    def forbidden(url: str) -> bytes:
        raise AssertionError("no network request may be made without an API key")

    no_key = FredProvider(transport=forbidden).fetch_vintages("UNRATE", fetched_at=FETCHED_AT)
    assert no_key.status == "unavailable" and "API key" in str(no_key.reason) and no_key.observations == ()

    def offline(url: str) -> bytes:
        raise OSError("offline")

    for result in (
        FredProvider(api_key="secret-key", transport=offline).fetch_vintages("UNRATE", fetched_at=FETCHED_AT),
        FredProvider(api_key="secret-key", transport=offline).fetch_latest("UNRATE", fetched_at=FETCHED_AT),
        EcbProvider(transport=offline).fetch("FM", "B.U2.EUR.4F.KR.DFR.LEV", fetched_at=FETCHED_AT),
    ):
        assert result.status == "unavailable" and result.observations == ()
        assert "secret-key" not in str(result.reason)

    empty = MacroWarehouse().observations_as_of(root=tmp_path, decision_time="2026-01-01T00:00:00+00:00")
    indicators = macro_indicators(pd.DataFrame([row.model_dump() for row in empty]))
    assert set(indicators) == set(INDICATOR_IDS)
    assert all(item["status"] == "unavailable" and item["value"] is None for item in indicators.values())


def test_ice_series_get_a_stricter_legal_terms_row_than_generic_fred() -> None:
    payload = _fred_payload([("2024-03-01", "3.1", "2024-03-02", _FOREVER)])
    registry = load_legal_terms()
    for series_id, terms_id in (("BAMLH0A0HYM2", "fred_ice_bofa"), ("DGS10", "fred")):
        result = FredProvider(api_key="test-key", transport=lambda url: payload).fetch_vintages(series_id, fetched_at=FETCHED_AT)
        assert {row.source_terms for row in result.observations} == {terms_id}
    ice, generic = registry.entry("fred_ice_bofa"), registry.entry("fred")
    assert not registry.can_export("fred_ice_bofa", "audit_export") and not registry.can_export("fred_ice_bofa", "redistribution")
    assert ice.redistribution == "prohibited" and generic.redistribution != "prohibited"


def test_default_fetch_time_is_taken_after_the_response_arrives() -> None:
    returned: list[datetime] = []

    def slow(url: str) -> bytes:
        time.sleep(0.05)
        returned.append(datetime.now(timezone.utc))
        return _fred_payload([("2024-02-01", "3.9", "2026-01-01", "2026-01-01")]) if "fred" in url else _RATE_CSV.encode()

    fred = FredProvider(api_key="test-key", transport=slow).fetch_latest("UNRATE")
    ecb = EcbProvider(transport=slow).fetch("FM", "B.U2.EUR.4F.KR.DFR.LEV")
    for result, arrived in ((fred, returned[0]), (ecb, returned[1])):
        assert result.status == "available"
        assert all(pd.Timestamp(row.available_at) >= arrived for row in result.observations)


def test_ecb_rate_effective_after_the_fetch_is_deferred_not_rejecting_the_batch(tmp_path) -> None:
    csv_text = _RATE_CSV + "FM.B.U2.EUR.4F.KR.DFR.LEV,B,U2,EUR,DFR,2026-02-01,1.75,A,PCPA,0\n"
    result = EcbProvider(transport=lambda url: csv_text.encode()).fetch("FM", "B.U2.EUR.4F.KR.DFR.LEV", fetched_at=FETCHED_AT)
    assert [row.period_start for row in result.observations] == ["2025-12-30"]
    MacroWarehouse().ingest(list(result.observations), root=tmp_path)
    later = EcbProvider(transport=lambda url: csv_text.encode()).fetch(
        "FM", "B.U2.EUR.4F.KR.DFR.LEV", fetched_at=datetime(2026, 2, 2, tzinfo=timezone.utc)
    )
    assert [row.period_start for row in later.observations] == ["2025-12-30", "2026-02-01"]


def test_fred_vintage_fetch_reads_every_page_before_assigning_revisions(tmp_path) -> None:
    rows = [
        ("2024-01-01", "3.7", "2024-02-02", "2024-03-07"),
        ("2024-01-01", "3.9", "2024-03-08", _FOREVER),
        ("2024-02-01", "3.9", "2024-03-08", _FOREVER),
    ]
    offsets: list[int] = []

    def paged(url: str) -> bytes:
        offset = int(url.split("offset=")[1].split("&")[0]) if "offset=" in url else 0
        offsets.append(offset)
        page = json.loads(_fred_payload(rows[offset:offset + 2]))
        page["count"] = len(rows)
        return json.dumps(page).encode()

    result = FredProvider(api_key="test-key", transport=paged).fetch_vintages("UNRATE", fetched_at=FETCHED_AT)
    assert offsets == [0, 2] and result.status == "available"
    assert sorted((row.period_start, row.revision, row.value) for row in result.observations) == [
        ("2024-01-01", 1, 3.7), ("2024-01-01", 2, 3.9), ("2024-02-01", 1, 3.9)
    ]
    short = FredProvider(api_key="test-key", transport=lambda url: json.dumps({"count": 5, "observations": []}).encode())
    assert short.fetch_vintages("UNRATE", fetched_at=FETCHED_AT).status == "unavailable"


def _refresh_macro(monkeypatch, tmp_path, transport, *, active: str = "fred", key: str | None = "test-key") -> int:
    from etf_cockpit.core import config as config_module
    from scripts import refresh_macro

    providers = config_module.DataProvidersConfig(providers={"fred": config_module.ProviderSection(active_provider=active)})
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))
    monkeypatch.setattr(config_module, "load_config", lambda *_a, **_k: SimpleNamespace(data_providers=providers))
    monkeypatch.setattr(config_module, "resolve_provider_api_key", lambda *_a, **_k: key)
    return refresh_macro.main(["--root", str(tmp_path)], transport=transport)


@pytest.mark.parametrize("active, key, reason", [("none", "test-key", "not active"), ("fred", None, "API key")])
def test_refresh_macro_without_gate_or_key_makes_no_request(monkeypatch, tmp_path, capsys, active, key, reason) -> None:
    calls: list[str] = []

    assert _refresh_macro(monkeypatch, tmp_path, calls.append, active=active, key=key) == 0
    assert calls == [] and reason in capsys.readouterr().out
    assert MacroWarehouse().observations(root=tmp_path) == []


def test_refresh_macro_stores_each_series_once_and_one_failure_does_not_stop_the_others(monkeypatch, tmp_path, capsys) -> None:
    from etf_cockpit.data.fred_provider import FRED_SERIES

    requested: list[str] = []

    def transport(url: str) -> bytes:
        series_id = url.split("series_id=")[1].split("&")[0]
        requested.append(series_id)
        if series_id == "NFCI":
            raise OSError("offline")
        return _fred_payload([("2024-03-01", "1.5", "2024-03-02", _FOREVER)])

    assert _refresh_macro(monkeypatch, tmp_path, transport) == 0
    first = capsys.readouterr().out.splitlines()
    assert _refresh_macro(monkeypatch, tmp_path, transport, active=" FRED ") == 0  # same normalisation as FredProvider
    second = capsys.readouterr().out.splitlines()

    assert requested == list(FRED_SERIES) * 2
    stored = MacroWarehouse().observations(root=tmp_path)
    assert {row.series_id for row in stored} == set(FRED_SERIES) - {"NFCI"} and len(stored) == len(FRED_SERIES) - 1
    for lines, new in ((first, 1), (second, 0)):
        assert [line.split(":")[0] for line in lines] == list(FRED_SERIES)
        assert all(f"new={new}" in line for line in lines if not line.startswith("NFCI"))
        assert "unavailable" in next(line for line in lines if line.startswith("NFCI"))
    assert "test-key" not in "\n".join(first + second)
