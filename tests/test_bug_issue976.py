"""MC1 (#976): macro warehouse / risk-free proxy integrity and market-clock inputs.

One native test per finding.  A test that already passes on the base is kept as a
regression guard and the finding is recorded as REJECTED in the handoff.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.macro_context import build_macro_context_binding
from etf_cockpit.application.market_clock import build_market_clock_diagnostics
from etf_cockpit.data.macro_warehouse import (
    CurvePoint,
    CurveSnapshot,
    MacroObservation,
    MacroWarehouse,
    MacroWarehouseError,
    parse_csv_records,
    parse_world_bank_records,
    transform_observations,
)
from etf_cockpit.data.market_calendar import ListingCalendarEvidence, MarketClockError
from etf_cockpit.features.macro import build_macro_context
from etf_cockpit.features.regime import _candidate_pct_above_sma200


def _row(**updates: object) -> MacroObservation:
    values: dict[str, object] = {
        "dataset_id": "cpi",
        "series_id": "cpi:AU",
        "period_start": "2024-01-01",
        "value": 4.35,
        "unit": "percentage",
        "frequency": "monthly",
        "country": "AU",
        "currency": "AUD",
        "dataset_kind": "macro",
        "source_id": "stat-office-fixture",
        "source_authority": "official_public_file",
        "source_checksum": "a" * 64,
        "published_at": "2024-02-01T00:00:00+00:00",
        "available_at": "2024-02-01T00:00:00+00:00",
        "observed_at": "2024-01-01T00:00:00+00:00",
        "ingested_at": "2024-02-02T00:00:00+00:00",
    }
    values.update(updates)
    return MacroObservation.model_validate(values)


def _identity_projection(*, closing_auction_minutes: int | None = None) -> dict[str, object]:
    fields: dict[str, object] = {
        "mic": "XNYS",
        "calendar_id": "XNYS",
        "timezone": "America/New_York",
    }
    if closing_auction_minutes is not None:
        fields["closing_auction_minutes"] = closing_auction_minutes
    return {
        "status": "available",
        "instrument_id": "SEC-1",
        "identity_decision_id": "identity-decision-1",
        "identity_decision_time": "2020-01-02T20:00:00Z",
        "identity_effective_at": "2010-01-01T00:00:00Z",
        "identity_conflict_ids": [],
        "identity_objects": [
            {
                "object_type": "listing",
                "object_id": "listing:XNYS",
                "parent_object_id": "SEC-1",
                "relationship": "listed_as",
                "fields": fields,
                "source_ids": ["iso-mic:test", "exchange-calendar:test"],
            }
        ],
        "identity_history": [
            {
                "object_type": "listing",
                "object_id": "listing:XNYS",
                "field": "mic",
                "value": "XNYS",
                "source_id": "iso-mic:test",
                "valid_from": "2010-01-01T00:00:00Z",
                "valid_to": None,
                "available_at": "2010-01-02T00:00:00Z",
                "revision": 1,
                "event_type": "observation",
            }
        ],
        "execution_allowed": False,
    }


# --- A108-N001: namespaced World Bank indicator / country identities ---------------------


def test_nested_world_bank_indicator_ids_do_not_collide(tmp_path: Path) -> None:
    payload = [
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP"},
            "country": {"id": "AU", "value": "Australia"},
            "countryiso3code": "AUS",
            "date": "2023",
            "value": 10.0,
        },
        {
            "indicator": {"id": "FP.CPI.TOTL", "value": "CPI"},
            "country": {"id": "AU", "value": "Australia"},
            "countryiso3code": "AUS",
            "date": "2023",
            "value": 5.0,
        },
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP"},
            "country": {"id": "NL", "value": "Netherlands"},
            "countryiso3code": "NLD",
            "date": "2023",
            "value": 7.0,
        },
        {  # aggregate without ISO3 code: identity falls back to the nested country id
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP"},
            "country": {"id": "1W", "value": "World"},
            "countryiso3code": "",
            "date": "2023",
            "value": 90.0,
        },
    ]
    rows = parse_world_bank_records(
        payload,
        dataset_id="world-bank",
        source_id="wb-fixture",
        source_checksum="b" * 64,
        available_at="2024-06-01T00:00:00+00:00",
        ingested_at="2024-06-02T00:00:00+00:00",
    )
    assert len({row.stable_id for row in rows}) == 4
    assert {row.country for row in rows} == {"AUS", "NLD", "1W"}
    assert all("NY.GDP.MKTP.CD" in row.series_id or "FP.CPI.TOTL" in row.series_id for row in rows)

    MacroWarehouse().ingest(rows, root=tmp_path)
    stored = MacroWarehouse().as_of(
        root=tmp_path, dataset_id="world-bank", decision_time="2025-01-01T00:00:00+00:00"
    )
    assert len(stored) == 4


# --- A108-N002: flows sum, stocks take the period end ------------------------------------


def _monthly(values: list[float], *, unit: str = "currency", start_month: int = 1) -> list[MacroObservation]:
    return [
        _row(
            dataset_id="gdp-monthly",
            series_id="gdp:AU",
            period_start=f"2024-{start_month + index:02d}-01",
            observed_at=f"2024-{start_month + index:02d}-01T00:00:00+00:00",
            published_at="2024-06-01T00:00:00+00:00",
            available_at="2024-06-01T00:00:00+00:00",
            ingested_at="2024-06-02T00:00:00+00:00",
            value=value,
            unit=unit,
        )
        for index, value in enumerate(values)
    ]


def test_flow_series_is_aggregated_by_sum_and_stock_by_period_end() -> None:
    flows = transform_observations(
        _monthly([10.0, 20.0, 30.0]), target_frequency="quarterly", aggregation="flow"
    )
    stocks = transform_observations(
        _monthly([10.0, 20.0, 30.0]), target_frequency="quarterly", aggregation="stock"
    )
    assert [row.value for row in flows] == [60.0]
    assert [row.value for row in stocks] == [30.0]


def test_flow_or_stock_conversion_fails_closed_without_declaration_or_complete_period() -> None:
    with pytest.raises(MacroWarehouseError, match="aggregation"):
        transform_observations(_monthly([10.0, 20.0, 30.0]), target_frequency="quarterly")
    with pytest.raises(MacroWarehouseError, match="incomplete"):
        transform_observations(
            _monthly([10.0, 20.0]), target_frequency="quarterly", aggregation="flow"
        )
    with pytest.raises(MacroWarehouseError, match="aggregation"):
        transform_observations(
            _monthly([10.0, 20.0, 30.0]), target_frequency="quarterly", aggregation="median"
        )


# --- C121-N001: timezone-free publication time -------------------------------------------


def test_naive_publication_time_is_not_treated_as_utc(tmp_path: Path) -> None:
    with pytest.raises(MacroWarehouseError, match="timezone"):
        MacroWarehouse().ingest([_row(available_at="2024-02-01T09:00:00")], root=tmp_path)
    with pytest.raises(MacroWarehouseError, match="timezone"):
        MacroWarehouse().ingest([_row(published_at="2024-02-01")], root=tmp_path)
    content = "series_id,period_start,value,country,currency\ncpi:AU,2024-01-01,3.0,AU,AUD\n"
    common = dict(
        dataset_id="cpi",
        source_id="fixture",
        ingested_at="2024-05-02T00:00:00+00:00",
        unit="percentage",
    )
    with pytest.raises(MacroWarehouseError, match="timezone"):
        parse_csv_records(content, available_at="2024-02-01T09:00:00", **common)
    declared = parse_csv_records(
        content, available_at="2024-02-01T09:00:00", source_timezone="America/New_York", **common
    )
    assert declared[0].available_at == "2024-02-01T14:00:00+00:00"
    assert declared[0].published_at == "2024-02-01T14:00:00+00:00"


# --- C121-N002 / A008 quarterly revision double count ------------------------------------


def _vintaged_rows() -> list[MacroObservation]:
    jan_first = _row(period_start="2024-01-01", value=4.0, revision=1)  # available 2024-02-01
    jan_revised = _row(
        period_start="2024-01-01",
        value=6.0,
        revision=2,
        source_checksum="c" * 64,
        available_at="2024-04-15T00:00:00+00:00",
        published_at="2024-04-15T00:00:00+00:00",
        ingested_at="2024-04-16T00:00:00+00:00",
    )
    others = [
        _row(
            period_start=f"2024-0{month}-01",
            value=5.0,
            observed_at=f"2024-0{month}-01T00:00:00+00:00",
            available_at=f"2024-0{month + 1}-01T00:00:00+00:00",
            published_at=f"2024-0{month + 1}-01T00:00:00+00:00",
            ingested_at=f"2024-0{month + 1}-02T00:00:00+00:00",
        )
        for month in (2, 3)
    ]
    return [jan_first, jan_revised, *others]


def test_revised_period_uses_the_latest_vintage_known_at_the_decision() -> None:
    rows = _vintaged_rows()
    after = transform_observations(
        rows, target_frequency="quarterly", decision_time="2024-06-01T00:00:00+00:00"
    )
    before = transform_observations(
        rows, target_frequency="quarterly", decision_time="2024-04-10T00:00:00+00:00"
    )
    assert after[0].value == pytest.approx((6.0 + 5.0 + 5.0) / 3)
    assert before[0].value == pytest.approx((4.0 + 5.0 + 5.0) / 3)
    assert after[0].available_at == "2024-04-15T00:00:00+00:00"


def test_conversion_with_several_vintages_requires_a_decision_time() -> None:
    with pytest.raises(MacroWarehouseError, match="decision_time"):
        transform_observations(_vintaged_rows(), target_frequency="quarterly")


def test_revised_flow_is_not_double_counted_in_the_sum() -> None:
    first = _monthly([100.0, 50.0, 50.0])
    revised = first[0].model_copy(
        update={
            "value": 150.0,
            "revision": 2,
            "source_checksum": "d" * 64,
            "available_at": "2024-07-01T00:00:00+00:00",
            "published_at": "2024-07-01T00:00:00+00:00",
            "ingested_at": "2024-07-02T00:00:00+00:00",
        }
    )
    late = transform_observations(
        [*first, revised],
        target_frequency="quarterly",
        aggregation="flow",
        decision_time="2024-08-01T00:00:00+00:00",
    )
    early = transform_observations(
        [*first, revised],
        target_frequency="quarterly",
        aggregation="flow",
        decision_time="2024-06-15T00:00:00+00:00",
    )
    assert [row.value for row in late] == [250.0]
    assert [row.value for row in early] == [200.0]


# --- A008 non-finite value ---------------------------------------------------------------


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_non_finite_macro_value_is_rejected_at_parse(bad: str) -> None:
    with pytest.raises(MacroWarehouseError, match="finite"):
        parse_csv_records(
            f"series_id,period_start,value\ncpi:AU,2024-01-01,{bad}\n",
            dataset_id="cpi",
            source_id="fixture",
            available_at="2024-02-01T00:00:00+00:00",
            ingested_at="2024-02-02T00:00:00+00:00",
        )
    with pytest.raises(MacroWarehouseError, match="finite"):
        parse_world_bank_records(
            [{"indicator_id": "X", "countryiso3code": "AUS", "date": "2023", "value": bad}],
            dataset_id="wb",
            source_id="fixture",
            source_checksum="b" * 64,
            available_at="2024-02-01T00:00:00+00:00",
            ingested_at="2024-02-02T00:00:00+00:00",
        )


# --- A008 future summary date / C121-N003 replay -----------------------------------------


def _ingest_two_vintages(tmp_path: Path) -> None:
    early = _row(period_start="2024-01-01", value=3.0)
    later = _row(
        period_start="2025-01-01",
        value=9.0,
        observed_at="2025-01-01T00:00:00+00:00",
        available_at="2025-02-01T00:00:00+00:00",
        published_at="2025-02-01T00:00:00+00:00",
        ingested_at="2025-02-02T00:00:00+00:00",
    )
    MacroWarehouse().ingest([early, later], root=tmp_path)


def test_summary_latest_observed_date_ignores_rows_not_known_at_the_decision(tmp_path: Path) -> None:
    _ingest_two_vintages(tmp_path)
    summary = MacroWarehouse().summary(root=tmp_path, decision_time="2024-06-01T00:00:00+00:00")
    assert summary["row_count"] == 1
    assert pd.Timestamp(summary["latest_observed_at"]) == pd.Timestamp("2024-01-01", tz="UTC")


def test_replay_excludes_records_imported_after_the_decision(tmp_path: Path) -> None:
    backfilled = _row(ingested_at="2024-06-01T00:00:00+00:00")
    MacroWarehouse().ingest([backfilled], root=tmp_path)
    warehouse = MacroWarehouse()
    before = "2024-03-01T00:00:00+00:00"
    after = "2024-07-01T00:00:00+00:00"
    assert warehouse.observations_as_of(root=tmp_path, decision_time=before) == []
    assert warehouse.as_of(root=tmp_path, dataset_id="cpi", decision_time=before).empty
    assert warehouse.summary(root=tmp_path, decision_time=before)["row_count"] == 0
    assert len(warehouse.observations_as_of(root=tmp_path, decision_time=after)) == 1


def test_late_imported_revision_does_not_hide_the_vintage_known_at_the_decision(tmp_path: Path) -> None:
    first = _row(value=3.0)
    backfilled_revision = _row(
        value=8.0,
        revision=2,
        source_checksum="e" * 64,
        available_at="2024-02-15T00:00:00+00:00",
        published_at="2024-02-15T00:00:00+00:00",
        ingested_at="2024-09-01T00:00:00+00:00",
    )
    MacroWarehouse().ingest([first], root=tmp_path)
    MacroWarehouse().ingest([backfilled_revision], root=tmp_path)
    warehouse = MacroWarehouse()
    known = warehouse.observations_as_of(root=tmp_path, decision_time="2024-06-01T00:00:00+00:00")
    assert [row.value for row in known] == [3.0]
    replay = warehouse.observations_as_of(root=tmp_path, decision_time="2024-10-01T00:00:00+00:00")
    assert [row.value for row in replay] == [8.0]


def test_curve_imported_after_the_decision_is_not_a_then_known_rate(tmp_path: Path) -> None:
    snapshot = CurveSnapshot(
        curve_id="eur-ois",
        curve_version="v1",
        curve_type="spot",
        currency="EUR",
        effective_at="2024-02-01T00:00:00+00:00",
        published_at="2024-02-01T00:00:00+00:00",
        available_at="2024-02-01T00:00:00+00:00",
        ingested_at="2024-06-01T00:00:00+00:00",
        source_id="ecb-fixture",
        source_authority="official_regulator",
        source_checksum="f" * 64,
        source_terms="public",
        methodology="fixture",
        compounding="annual",
        day_count="ACT/365F",
        reinvestment="reinvested_income",
        freshness="fresh",
        freshness_status="fresh",
        points=(CurvePoint(tenor_years=1.0, rate=0.03),),
    )
    MacroWarehouse().ingest_curve(snapshot, root=tmp_path)
    warehouse = MacroWarehouse()
    early = warehouse.curve_rate(
        root=tmp_path, curve_id="eur-ois", tenor_years=1.0, decision_time="2024-03-01T00:00:00+00:00"
    )
    late = warehouse.curve_rate(
        root=tmp_path, curve_id="eur-ois", tenor_years=1.0, decision_time="2024-07-01T00:00:00+00:00"
    )
    assert early["status"] == "unavailable"
    assert late["status"] == "available"


# --- C002-N002 / V8 A.C3.S08.N002: availability-time chronology --------------------------


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"ingested_at": "2024-01-15T00:00:00+00:00"}, "ingested_at"),
        ({"revised_at": "2024-03-01T00:00:00+00:00"}, "revised_at"),
    ],
)
def test_availability_chronology_is_validated_before_append(
    tmp_path: Path, update: dict[str, object], message: str
) -> None:
    with pytest.raises(MacroWarehouseError, match=message):
        MacroWarehouse().ingest([_row(**update)], root=tmp_path)


# --- A108-N003 / A008 CPI ordering / C121-N004: inflation context ------------------------


def _snapshot(decision_time: str, prices: pd.DataFrame | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        benchmark_reference_decision_time=decision_time,
        benchmark_reference_currency="EUR",
        benchmark_reference_horizon_years=1.0,
        prices=prices if prices is not None else pd.DataFrame(),
        config=SimpleNamespace(universe=SimpleNamespace(etfs=())),
    )


def _cpi_rows(months: int, *, country: str | None = "AU", reverse: bool = False) -> list[MacroObservation]:
    rows = []
    for index in range(months):
        period = pd.Timestamp("2023-01-01") + pd.DateOffset(months=index)
        available = period + pd.DateOffset(months=1)
        rows.append(
            _row(
                series_id=f"cpi_inflation:{country or 'XX'}",
                period_start=period.date().isoformat(),
                observed_at=period.strftime("%Y-%m-%dT00:00:00+00:00"),
                available_at=available.strftime("%Y-%m-%dT00:00:00+00:00"),
                published_at=available.strftime("%Y-%m-%dT00:00:00+00:00"),
                ingested_at=(available + pd.Timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+00:00"),
                value=float(index),
                country=country,
            )
        )
    return rows[::-1] if reverse else rows


def test_inflation_context_requires_a_jurisdiction(tmp_path: Path) -> None:
    MacroWarehouse().ingest(_cpi_rows(2, country=None), root=tmp_path)
    binding = build_macro_context_binding(
        _snapshot("2025-06-01T00:00:00+00:00"), warehouse=MacroWarehouse(), root=tmp_path
    )
    inflation = binding.context["inflation_rates"]
    assert inflation["status"] == "unavailable"
    assert inflation["rows"] == []
    assert "jurisdiction" in str(inflation["reason"])


def test_inflation_context_rows_carry_their_jurisdiction(tmp_path: Path) -> None:
    MacroWarehouse().ingest(_cpi_rows(2, country="AU"), root=tmp_path)
    binding = build_macro_context_binding(
        _snapshot("2025-06-01T00:00:00+00:00"), warehouse=MacroWarehouse(), root=tmp_path
    )
    inflation = binding.context["inflation_rates"]
    assert inflation["status"] == "available"
    assert {row["country"] for row in inflation["rows"]} == {"AU"}


def test_inflation_context_keeps_the_latest_periods_in_period_order(tmp_path: Path) -> None:
    MacroWarehouse().ingest(_cpi_rows(15, reverse=True), root=tmp_path)
    binding = build_macro_context_binding(
        _snapshot("2025-06-01T00:00:00+00:00"), warehouse=MacroWarehouse(), root=tmp_path
    )
    values = [row["value"] for row in binding.context["inflation_rates"]["rows"]]
    assert values == [float(index) for index in range(3, 15)]


def test_inflation_context_cap_is_per_series_so_one_series_cannot_crowd_out_another(tmp_path: Path) -> None:
    cpi = _cpi_rows(3)
    policy = [
        row.model_copy(update={"series_id": row.series_id.replace("cpi_inflation", "policy_rate")})
        for row in _cpi_rows(14)
    ]
    MacroWarehouse().ingest([*cpi, *policy], root=tmp_path)
    binding = build_macro_context_binding(
        _snapshot("2025-06-01T00:00:00+00:00"), warehouse=MacroWarehouse(), root=tmp_path
    )
    rows = binding.context["inflation_rates"]["rows"]
    assert sum(row["series_id"].startswith("cpi_inflation") for row in rows) == 3
    assert sum(row["series_id"].startswith("policy_rate") for row in rows) == 12


def _price_panel(days: int = 240) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    rows = []
    for index, current in enumerate(dates):
        rows.append({"date": current, "etf_id": "EQUITY", "adjusted_close": 100 + index * 0.2})
    return pd.DataFrame(rows)


def test_feature_inflation_summary_requires_jurisdiction_and_orders_by_period() -> None:
    cutoff = pd.Timestamp("2025-06-01", tz="UTC")
    report = build_macro_context(
        _price_panel(),
        [{"id": "EQUITY", "name": "equity", "asset_class": "equity"}],
        _cpi_rows(15, reverse=True) + _cpi_rows(3, country=None),
        as_of_date=cutoff.date(),
    )
    rows = report["inflation_rates"]["rows"]
    assert [row["value"] for row in rows] == [float(index) for index in range(3, 15)]
    assert {row["country"] for row in rows} == {"AU"}


# --- C021-N002 / C002-N002: price revisions known after the decision ---------------------


def test_price_revision_known_after_the_decision_never_enters_macro_context(tmp_path: Path) -> None:
    prices = _price_panel()
    prices["known_at"] = prices["date"] + pd.Timedelta(hours=22)
    last = prices.iloc[-1]
    decision = (last["date"] + pd.Timedelta(days=1)).strftime("%Y-%m-%dT10:00:00+00:00")
    revision = last.copy()
    revision["adjusted_close"] = 10.0
    revision["known_at"] = pd.Timestamp(decision) + pd.Timedelta(hours=5)
    with_revision = pd.concat([prices, revision.to_frame().T], ignore_index=True)
    with_revision["date"] = pd.to_datetime(with_revision["date"])
    with_revision["adjusted_close"] = with_revision["adjusted_close"].astype(float)

    clean = build_macro_context_binding(
        _snapshot(decision, prices), warehouse=MacroWarehouse(), root=tmp_path
    ).context
    revised = build_macro_context_binding(
        _snapshot(decision, with_revision), warehouse=MacroWarehouse(), root=tmp_path
    ).context
    for key in ("proxy_rows", "breadth", "volatility", "as_of"):
        assert revised[key] == clean[key]


# --- V8: adjusted flag, regime candidate chronology --------------------------------------


@pytest.mark.parametrize("identifier", ["A.C3.S08.N003", "C.C3.S21.N001"])
def test_string_false_adjusted_flag_is_not_truthy(identifier: str) -> None:
    prices = _price_panel()
    prices["is_adjusted"] = "True"
    prices.loc[0, "is_adjusted"] = "False"
    report = build_macro_context(prices, [{"id": "EQUITY", "name": "equity"}])
    assert report["status"] == "unavailable", identifier
    assert "non-adjusted" in report["regime"]["summary"]
    prices["is_adjusted"] = "True"
    assert build_macro_context(prices, [{"id": "EQUITY", "name": "equity"}])["status"] != "unavailable"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "V8 C.C2.S21.N001 is real (RED on the base) but the strict fix drops every production "
        "candidate-report row (the report carries no knowledge-time column) and contradicts "
        "test_candidate_breadth_excludes_future_and_unproven_rows; held for an Opus decision."
    ),
)
def test_candidate_without_any_knowledge_time_is_not_counted_in_breadth() -> None:
    report = pd.DataFrame(
        [
            {
                "sma200_signal": True,
                "as_of": "2024-01-02",
                "source_id": "candidate-fixture",
            },
            {
                "sma200_signal": False,
                "as_of": "2024-01-02",
                "known_at": "2024-01-03T00:00:00+00:00",
                "source_id": "candidate-fixture",
            },
        ]
    )
    assert _candidate_pct_above_sma200(report, decision_time="2024-02-01T00:00:00+00:00") == 0.0


# --- A120: market clock inputs -----------------------------------------------------------


def test_date_only_decision_maps_to_the_exchange_local_session() -> None:
    result = build_market_clock_diagnostics(_identity_projection(), decision_time="2024-11-29")
    assert result["status"] == "available"
    assert result["valuation_date"] == "2024-11-29"
    # 2024-11-29 is the XNYS early-close session (13:00 New York = 18:00 UTC).
    assert result["session_close"] == "2024-11-29T18:00:00+00:00"
    assert result["phase"] == "post_close"
    # Date-only cutoffs include the final fractional second of the exchange-local day.
    assert result["decision_time"] == "2024-11-30T04:59:59.999999+00:00"
    assert result["knowledge_cutoff"] == "2024-11-30T04:59:59.999999+00:00"


def test_date_only_observation_is_the_end_of_its_exchange_local_day() -> None:
    result = build_market_clock_diagnostics(
        _identity_projection(), decision_time="2024-11-29T22:00:00Z", observed_at="2024-11-27"
    )
    staleness = result["staleness"]
    # Sessions closed after the 27 November bar: 27 is its own (not counted), 28 holiday, 29 early close.
    assert staleness["expected_sessions_elapsed"] == 1  # type: ignore[index]


@pytest.mark.parametrize(
    "bad", ["2024-11-29T99:99:99Z", "2024-13-01", "2024-11-29 garbage", "2024-11-29Tnot-a-time"]
)
def test_invalid_timestamp_is_an_error_never_truncated_to_its_date(bad: str) -> None:
    result = build_market_clock_diagnostics(_identity_projection(), decision_time=bad)
    assert result["status"] == "unavailable"
    assert result["reason_code"] == "market_clock_evidence_unavailable"
    assert "invalid" in str(result["message"])


def test_staleness_is_not_truncated_to_a_seven_year_calendar_window() -> None:
    result = build_market_clock_diagnostics(
        _identity_projection(),
        decision_time="2024-11-29T22:00:00Z",
        observed_at="2010-01-04T21:00:00Z",
        maximum_expected_sessions=1500,
    )
    assert result["staleness"]["status"] == "stale"  # type: ignore[index]
    assert result["staleness"]["expected_sessions_elapsed"] > 3000  # type: ignore[index,operator]
    too_old = build_market_clock_diagnostics(
        _identity_projection(),
        decision_time="2024-11-29T22:00:00Z",
        observed_at="1990-01-04T21:00:00Z",
        maximum_expected_sessions=1500,
    )
    assert too_old["staleness"]["certification"] == "unavailable"  # type: ignore[index]
    assert too_old["staleness"]["status"] == "unknown"  # type: ignore[index]


def test_oversized_auction_window_cannot_misclassify_regular_trading() -> None:
    result = build_market_clock_diagnostics(
        _identity_projection(closing_auction_minutes=10000),
        decision_time="2024-11-26T15:00:00Z",
    )
    assert result["phase"] != "closing_auction"
    assert result["status"] == "unavailable"
    with pytest.raises(MarketClockError, match="auction"):
        ListingCalendarEvidence(
            listing_id="l",
            instrument_id="i",
            mic="XNYS",
            calendar_id="XNYS",
            timezone="America/New_York",
            source_id="s",
            source_checksum="a" * 64,
            valid_from=datetime(2020, 1, 1).date(),
            known_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            closing_auction_minutes=10000,
        )
