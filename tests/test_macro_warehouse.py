from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from etf_cockpit.data import macro_warehouse as macro_warehouse_module
from etf_cockpit.data.bitemporal import BitemporalError, BitemporalStore
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.macro_warehouse import (
    BenchmarkMetadata,
    CurvePoint,
    CurveSnapshot,
    MacroObservation,
    MacroWarehouse,
    MacroWarehouseError,
    RiskFreeProxyMapping,
    interpolate_curve,
    load_risk_free_proxy_mappings,
    parse_csv_records,
    parse_world_bank_records,
    transform_observations,
)
import pytest


def _row(**updates: object) -> MacroObservation:
    values: dict[str, object] = {
        "dataset_id": "policy-rate",
        "series_id": "policy-rate:AU",
        "period_start": "2024-01-01",
        "value": 4.35,
        "unit": "percentage",
        "frequency": "monthly",
        "country": "AU",
        "currency": "AUD",
        "dataset_kind": "risk_free",
        "source_id": "central-bank-fixture",
        "source_authority": "official_regulator",
        "source_checksum": "a" * 64,
        "published_at": "2024-02-01T00:00:00+00:00",
        "available_at": "2024-02-01T00:00:00+00:00",
        "observed_at": "2024-01-01T00:00:00+00:00",
        "ingested_at": "2024-02-02T00:00:00+00:00",
    }
    values.update(updates)
    return MacroObservation.model_validate(values)


def test_world_bank_parser_and_decision_time_vintage_selection(tmp_path) -> None:
    source_rows = [
        {"indicator_id": "NY.GDP.MKTP.CD", "countryiso3code": "AUS", "date": "2023", "value": 10.0},
        {"indicator_id": "NY.GDP.MKTP.CD", "countryiso3code": "AUS", "date": "2024", "value": 11.0},
    ]
    first = parse_world_bank_records(
        source_rows,
        dataset_id="world-bank-gdp",
        source_id="world-bank-fixture",
        source_checksum="b" * 64,
        available_at="2024-06-01T00:00:00+00:00",
        ingested_at="2024-06-02T00:00:00+00:00",
        unit="currency",
    )
    revised = [first[1].model_copy(update={"value": 12.0, "revision": 2, "available_at": "2025-06-01T00:00:00+00:00", "ingested_at": "2025-06-02T00:00:00+00:00", "source_checksum": "c" * 64})]
    warehouse = MacroWarehouse()
    warehouse.ingest(first, root=tmp_path)
    warehouse.ingest(revised, root=tmp_path)

    historical = warehouse.as_of(root=tmp_path, dataset_id="world-bank-gdp", decision_time="2025-01-01T00:00:00+00:00")
    current = warehouse.as_of(root=tmp_path, dataset_id="world-bank-gdp", decision_time="2026-01-01T00:00:00+00:00")
    selected = warehouse.observations_as_of(root=tmp_path, decision_time="2025-01-01T00:00:00+00:00")

    assert historical.loc[historical["period_start"] == "2024-01-01", "value"].tolist() == [11.0]
    assert current.loc[current["period_start"] == "2024-01-01", "value"].tolist() == [12.0]
    assert historical.loc[0, "country"] == "AUS"
    assert [row.value for row in selected if row.period_start == "2024-01-01"] == [11.0]


def test_csv_parser_and_reversible_unit_frequency_transform(tmp_path) -> None:
    content = "series_id,period_start,value,country,currency\nrate,2024-01-01,4.0,AU,AUD\nrate,2024-02-01,5.0,AU,AUD\nrate,2024-04-01,6.0,AU,AUD\n"
    rows = parse_csv_records(
        content,
        dataset_id="csv-rates",
        source_id="local-fixture",
        available_at="2024-05-01T00:00:00+00:00",
        ingested_at="2024-05-02T00:00:00+00:00",
        unit="percentage",
        frequency="monthly",
        dataset_kind="risk_free",
    )
    transformed = transform_observations(rows, target_unit="decimal", target_frequency="quarterly")

    assert len(transformed) == 2
    assert transformed[0].value == 0.045
    assert transformed[0].unit == "decimal"
    assert transformed[0].frequency == "quarterly"
    assert transformed[0].transformation_version == "macro-transform.v1"
    assert len(transformed[0].source_observation_ids) == 2
    assert transformed[0].source_checksum != rows[0].source_checksum


def test_csv_parser_rejects_textual_revision_identity() -> None:
    with pytest.raises(MacroWarehouseError, match="revision identity is textual"):
        parse_csv_records(
            "series_id,period_start,value,revision\nrate,2024-01-01,4.0,1\n",
            dataset_id="csv-rates",
            source_id="local-fixture",
            available_at="2024-05-01T00:00:00+00:00",
            ingested_at="2024-05-02T00:00:00+00:00",
        )


def test_missing_country_and_currency_are_explicitly_unavailable(tmp_path) -> None:
    row = _row(country=None, currency=None)
    assert row.availability_status == "unavailable_context"
    summary = MacroWarehouse().ingest([row], root=tmp_path)
    assert summary["execution_allowed"] is False
    report = MacroWarehouse().summary(root=tmp_path)
    assert report["status"] == "available"
    assert report["missing_country_or_currency_count"] == 1


def test_generic_ingest_rejects_curve_rows_before_any_write(tmp_path) -> None:
    row = _direct_curve_row(
        dataset_id="curve:valid-curve",
        series_id="valid-curve:1Y",
        curve_id="valid-curve",
    )

    with pytest.raises(MacroWarehouseError, match="ingest_curve"):
        MacroWarehouse().ingest([row], root=tmp_path)

    with BitemporalStore(tmp_path) as store:
        assert store.observations("curve:valid-curve") == ()
        assert store.store.list("macro_warehouse_manifest") == ()


def test_generic_ingest_rejects_curve_observation_before_timestamp_validation(tmp_path) -> None:
    row = _row(
        dataset_id="curve:aud-direct",
        series_id="curve:aud-direct:1",
        curve_id="aud-direct",
        curve_version="v1",
        curve_type="spot",
        tenor_years=1.0,
        value=0.02,
        unit="decimal",
        compounding="annual",
        day_count="ACT/365F",
        reinvestment="reinvested_income",
        interpolation="none",
        freshness="fresh",
        freshness_status="fresh",
        published_at="2024-01-01",
        available_at="2024-01-01",
        observed_at="2024-01-01",
        ingested_at="2024-01-01",
    )

    with pytest.raises(MacroWarehouseError, match="ingest_curve"):
        MacroWarehouse().ingest([row], root=tmp_path)


@pytest.mark.parametrize("revision", (True, 1.0, "1"))
def test_curve_models_reject_coerced_revision_identities(revision: object) -> None:
    with pytest.raises(ValueError):
        MacroObservation.model_validate(
            {**_row().model_dump(), "revision": revision}
        )
    with pytest.raises(ValueError):
        CurveSnapshot.model_validate(
            {**_curve().model_dump(), "revision": revision}
        )


def test_curve_snapshot_rejects_whitespace_curve_version() -> None:
    with pytest.raises(ValueError, match="curve_version"):
        CurveSnapshot.model_validate({**_curve().model_dump(), "curve_version": "   "})


@pytest.mark.parametrize(
    "point",
    (
        {"tenor_years": 1.0, "rate": True},
        {"tenor_years": float("inf"), "rate": 0.01},
        {"tenor_years": float("nan"), "rate": 0.01},
        {"tenor_years": "1.0", "rate": 0.01},
        {"tenor_years": 1.0, "rate": "0.01"},
    ),
)
def test_curve_points_reject_coercive_or_nonfinite_values(
    point: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        CurvePoint.model_validate(point)


@pytest.mark.parametrize(
    "updates",
    (
        {"value": True, "tenor_years": 1.0},
        {"value": "0.01", "tenor_years": 1.0},
        {"value": 0.01, "tenor_years": float("inf")},
        {"value": 0.01, "tenor_years": float("nan")},
    ),
)
def test_direct_curve_rows_reject_malformed_points(
    updates: dict[str, object],
) -> None:
    values = {
        **_row().model_dump(),
        "curve_id": "aud-direct",
        "curve_type": "spot",
        "curve_version": "v1",
        **updates,
    }
    with pytest.raises(ValueError):
        MacroObservation.model_validate(values)


@pytest.mark.parametrize("revision", (True, 1.0, 1.5, "1"))
def test_macro_revision_is_strict_before_append_and_at_ledger_readback(
    tmp_path,
    revision: object,
) -> None:
    forged = _row().model_copy(update={"revision": revision})
    with pytest.raises(MacroWarehouseError, match="positive integer"):
        MacroWarehouse().ingest([forged], root=tmp_path)

    row = _row()
    ledger = {
        "value": row.ledger_value(),
        "source_id": row.source_id,
        "source_checksum": row.source_checksum,
        "published_at": row.published_at,
        "available_at": row.available_at,
        "observed_at": row.observed_at,
        "ingested_at": row.ingested_at,
        "revised_at": row.revised_at,
        "revision": row.revision,
        "timezone_confidence": row.timezone_confidence,
        "availability_confidence": row.availability_confidence,
    }
    ledger["revision"] = revision
    with pytest.raises((MacroWarehouseError, ValueError)):
        MacroObservation.from_ledger(ledger)


def test_macro_timestamps_preserve_subsecond_point_in_time_ordering(tmp_path) -> None:
    row = _row(
        published_at="2024-02-01T00:00:00.800Z",
        available_at="2024-02-01T00:00:00.900Z",
        ingested_at="2024-02-01T00:00:01.100Z",
    )
    warehouse = MacroWarehouse()
    warehouse.ingest([row], root=tmp_path)
    stored = warehouse.observations(root=tmp_path)[0]
    assert stored.published_at.endswith("00.800000+00:00")
    assert stored.available_at.endswith("00.900000+00:00")

    with pytest.raises(MacroWarehouseError, match="published_at"):
        warehouse.ingest(
            [
                row.model_copy(
                    update={
                        "published_at": "2024-02-01T00:00:00.901Z",
                        "available_at": "2024-02-01T00:00:00.900Z",
                    }
                )
            ],
            root=tmp_path / "publication-after-availability",
        )


def test_curve_readback_rejects_subsecond_decision_look_ahead(tmp_path) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(
        _curve(
            published_at="2025-01-01T00:00:00.900Z",
            available_at="2025-01-01T00:00:00.900Z",
        ),
        root=tmp_path,
    )

    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="aud-official-spot",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00.500Z",
    )
    assert selected["status"] == "unavailable"
    assert "then-known" in str(selected["reason"])


@pytest.mark.parametrize("field_name", ("extrapolation_allowed", "execution_allowed"))
@pytest.mark.parametrize("value", (0, "false"))
def test_curve_authority_booleans_are_not_coerced(field_name: str, value: object) -> None:
    with pytest.raises(ValueError):
        CurveSnapshot.model_validate({**_curve().model_dump(), field_name: value})

    if field_name == "execution_allowed":
        with pytest.raises(ValueError):
            RiskFreeProxyMapping.model_validate(
                {
                    "currency": "AUD",
                    "minimum_horizon_years": 0.0,
                    "maximum_horizon_years": 1.0,
                    "curve_id": "aud-cash",
                    "methodology": "official mapping",
                    "execution_allowed": value,
                }
            )
    else:
        with pytest.raises(ValueError):
            MacroObservation.model_validate(
                {**_row().model_dump(), "extrapolation_allowed": value}
            )
        row = _row()
        ledger = {
            "value": row.ledger_value(),
            "source_id": row.source_id,
            "source_checksum": row.source_checksum,
            "published_at": row.published_at,
            "available_at": row.available_at,
            "observed_at": row.observed_at,
            "ingested_at": row.ingested_at,
            "revised_at": row.revised_at,
            "revision": row.revision,
            "timezone_confidence": row.timezone_confidence,
            "availability_confidence": row.availability_confidence,
        }
        ledger["value"]["extrapolation_allowed"] = value
        with pytest.raises(ValueError):
            MacroObservation.from_ledger(ledger)


def test_curve_ingestion_rejects_duplicate_and_regressing_revision_identities(tmp_path) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(_curve(revision=2), root=tmp_path)

    with pytest.raises(MacroWarehouseError, match="revision"):
        warehouse.ingest_curve(_curve(revision=1), root=tmp_path)
    with pytest.raises(MacroWarehouseError, match="revision"):
        warehouse.ingest_curve(_curve(revision=2), root=tmp_path)


def test_curve_readback_fails_closed_for_persisted_regressing_history(tmp_path) -> None:
    warehouse = MacroWarehouse()
    first = _direct_curve_row(
        dataset_id="curve:readback-curve",
        series_id="readback-curve:1Y",
        curve_id="readback-curve",
        methodology="official method",
        available_at="2024-01-02T00:00:00+00:00",
        revision=2,
    )
    later_regression = first.model_copy(
        update={
            "available_at": "2024-01-03T00:00:00+00:00",
            "ingested_at": "2024-01-03T00:00:00+00:00",
            "revision": 1,
        }
    )
    _store_direct_curve_row(tmp_path, first)
    _store_direct_curve_row(tmp_path, later_regression)

    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="readback-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "revision" in str(selected["reason"])


def test_curve_readback_fails_closed_for_effective_at_after_available_at(tmp_path) -> None:
    row = _direct_curve_row(
        curve_id="effective-after-availability",
        dataset_id="curve:effective-after-availability",
        series_id="effective-after-availability:1Y",
        observed_at="2025-01-03T00:00:00+00:00",
        available_at="2025-01-02T00:00:00+00:00",
    )
    _store_direct_curve_row(tmp_path, row)

    selected = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="effective-after-availability",
        tenor_years=1.0,
        decision_time="2025-01-05T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "effective_at" in str(selected["reason"])


def test_curve_readback_fails_closed_for_ingested_at_before_available_at(tmp_path) -> None:
    row = _direct_curve_row(
        curve_id="ingested-before-availability",
        dataset_id="curve:ingested-before-availability",
        series_id="ingested-before-availability:1Y",
        available_at="2025-01-02T00:00:00+00:00",
        ingested_at="2025-01-01T23:59:59+00:00",
    )
    _store_direct_curve_row(tmp_path, row)

    selected = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="ingested-before-availability",
        tenor_years=1.0,
        decision_time="2025-01-05T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "ingested_at" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_curve_readback_fails_closed_for_whitespace_curve_version(tmp_path) -> None:
    row = _direct_curve_row(
        curve_id="blank-version",
        dataset_id="curve:blank-version",
        series_id="blank-version:1Y",
        curve_version="   ",
    )
    _store_direct_curve_row(tmp_path, row)

    selected = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="blank-version",
        tenor_years=1.0,
        decision_time="2025-01-05T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "curve_version" in str(selected["reason"])


def test_curve_readback_fails_closed_for_persisted_duplicate_revision_identity(tmp_path) -> None:
    first = _direct_curve_row(
        dataset_id="curve:duplicate-curve",
        series_id="duplicate-curve:1Y",
        curve_id="duplicate-curve",
        methodology="official method",
    )
    duplicate_identity = first.model_copy(
        update={"series_id": "duplicate-curve:other-1Y", "value": 0.02}
    )
    _store_direct_curve_row(tmp_path, first)
    _store_direct_curve_row(tmp_path, duplicate_identity)

    selected = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="duplicate-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "duplicated" in str(selected["reason"])


def test_curve_readback_fails_closed_for_malformed_persisted_ingested_at(tmp_path) -> None:
    row = _direct_curve_row(
        curve_id="malformed-ingested-at",
        dataset_id="curve:malformed-ingested-at",
        series_id="malformed-ingested-at:1Y",
    )
    with BitemporalStore(tmp_path) as store:
        store.store.connection.execute(
            """
            INSERT INTO bitemporal_observations
                (observation_id, dataset_id, entity_id, stable_id, run_id, value_json,
                 valid_from, valid_to, published_at, available_at, observed_at,
                 ingested_at, revised_at, revision, source_id, source_checksum,
                 timezone_confidence, availability_confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "e" * 64,
                row.dataset_id,
                row.series_id,
                row.stable_id,
                "malformed-ingested-at-run",
                json.dumps(row.ledger_value(), sort_keys=True),
                "2024-01-01T00:00:00.000000+00:00",
                None,
                row.published_at,
                row.available_at,
                row.observed_at,
                "not-a-time",
                None,
                row.revision,
                row.source_id,
                row.source_checksum,
                "exact",
                "exact",
                "active",
            ),
        )
        store.store.connection.commit()

    selected = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="malformed-ingested-at",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "ingested_at" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_malformed_primary_curve_falls_back_only_to_official_lineage(tmp_path) -> None:
    primary = _direct_curve_row(
        dataset_id="curve:primary-curve",
        series_id="primary-curve:1Y",
        curve_id="primary-curve",
        methodology="official method",
        source_authority=None,
    )
    fallback = _direct_curve_row(
        dataset_id="curve:fallback-curve",
        series_id="fallback-curve:1Y",
        curve_id="fallback-curve",
        methodology="official fallback method",
        source_authority="official_public_file",
    )
    _store_direct_curve_row(tmp_path, primary)
    _store_direct_curve_row(tmp_path, fallback)

    selected = MacroWarehouse().risk_free_rate(
        root=tmp_path,
        mappings=(
            RiskFreeProxyMapping(
                currency="AUD",
                minimum_horizon_years=1.0,
                maximum_horizon_years=1.0,
                curve_id="primary-curve",
                fallback_curve_ids=("fallback-curve",),
                methodology="official mapping",
            ),
        ),
        currency="AUD",
        horizon_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "available"
    assert selected["curve_id"] == "fallback-curve"
    assert selected["fallback"] is True
    assert selected["execution_allowed"] is False


def test_stale_primary_curve_falls_back_to_fresh_curve(tmp_path) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(
        _curve(curve_id="stale-primary").model_copy(
            update={"freshness": "stale", "freshness_status": "stale"}
        ),
        root=tmp_path,
    )
    warehouse.ingest_curve(
        _curve(curve_id="fresh-fallback").model_copy(
            update={"freshness": "fresh", "freshness_status": "fresh"}
        ),
        root=tmp_path,
    )

    selected = warehouse.risk_free_rate(
        root=tmp_path,
        mappings=(
            RiskFreeProxyMapping(
                currency="AUD",
                minimum_horizon_years=1.0,
                maximum_horizon_years=1.0,
                curve_id="stale-primary",
                fallback_curve_ids=("fresh-fallback",),
                methodology="official mapping",
            ),
        ),
        currency="AUD",
        horizon_years=1.0,
        decision_time="2025-01-05T00:00:00+00:00",
    )
    assert selected["status"] == "available"
    assert selected["curve_id"] == "fresh-fallback"
    assert selected["fallback"] is True
    assert selected["freshness"] == "fresh"


def test_missing_freshness_primary_falls_back_to_fresh_curve(tmp_path) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(
        _curve(curve_id="incomplete-primary").model_copy(
            update={"freshness": None, "freshness_status": None}
        ),
        root=tmp_path,
    )
    warehouse.ingest_curve(
        _curve(curve_id="fresh-fallback").model_copy(
            update={"freshness": "fresh", "freshness_status": "fresh"}
        ),
        root=tmp_path,
    )

    selected = warehouse.risk_free_rate(
        root=tmp_path,
        mappings=(
            RiskFreeProxyMapping(
                currency="AUD",
                minimum_horizon_years=1.0,
                maximum_horizon_years=1.0,
                curve_id="incomplete-primary",
                fallback_curve_ids=("fresh-fallback",),
                methodology="official mapping",
            ),
        ),
        currency="AUD",
        horizon_years=1.0,
        decision_time="2025-01-05T00:00:00+00:00",
    )
    assert selected["status"] == "available"
    assert selected["curve_id"] == "fresh-fallback"
    assert selected["fallback"] is True
    assert selected["freshness"] == "fresh"
    assert selected["freshness_status"] == "fresh"


def _curve(
    *,
    curve_id: str = "aud-official-spot",
    version: str = "v1",
    effective_at: str = "2025-01-01T00:00:00+00:00",
    published_at: str | None = None,
    available_at: str = "2025-01-02T00:00:00+00:00",
    revision: int = 1,
    rates: tuple[float, float] = (-0.01, 0.01),
) -> CurveSnapshot:
    return CurveSnapshot(
        curve_id=curve_id,
        curve_version=version,
        curve_type="spot",
        currency="AUD",
        effective_at=effective_at,
        published_at=published_at or available_at,
        available_at=available_at,
        ingested_at=available_at,
        source_id="official-central-bank-local-snapshot",
        source_authority="official_public_file",
        source_checksum=("a" if revision == 1 else "b") * 64,
        source_terms="official_publication_terms_reviewed",
        methodology="Official decimal zero-rate curve",
        interpolation="linear",
        reinvestment="reinvested_income",
        freshness="fresh",
        freshness_status="fresh",
        points=(
            CurvePoint(tenor_years=1.0, rate=rates[0]),
            CurvePoint(tenor_years=3.0, rate=rates[1]),
        ),
        revision=revision,
    )


def test_curve_interpolation_is_declared_bounded_and_supports_negative_rates() -> None:
    points = _curve().points

    assert interpolate_curve(points, 2.0, policy="linear") == 0.0
    assert interpolate_curve(points, 1.0, policy="none") == -0.01
    with pytest.raises(MacroWarehouseError, match="outside observed coverage"):
        interpolate_curve(points, 4.0, policy="linear")
    with pytest.raises(MacroWarehouseError, match="without interpolation"):
        interpolate_curve(points, 2.0, policy="none")
    with pytest.raises(MacroWarehouseError, match="extrapolation"):
        interpolate_curve(points, 2.0, policy="linear", extrapolation_allowed=True)


def test_curve_admission_rejects_ingested_at_before_available_at_before_append(tmp_path) -> None:
    warehouse = MacroWarehouse()
    snapshot = _curve().model_copy(
        update={"ingested_at": "2025-01-01T23:59:59+00:00"}
    )

    with pytest.raises(MacroWarehouseError, match="ingested_at.*available_at"):
        warehouse.ingest_curve(snapshot, root=tmp_path)

    assert warehouse.observations(
        root=tmp_path, dataset_id="curve:aud-official-spot"
    ) == []


def _direct_curve_row(**updates: object) -> MacroObservation:
    values: dict[str, object] = {
        "dataset_id": "curve:mapped-curve",
        "series_id": "mapped-curve:1Y",
        "value": 0.01,
        "unit": "decimal",
        "frequency": "irregular",
        "curve_id": "foreign-curve",
        "curve_type": "spot",
        "curve_version": "v1",
        "tenor_years": 1.0,
        "curve_point_count": 1,
        "interpolation": "none",
        "compounding": "annual",
        "day_count": "ACT/365F",
        "reinvestment": "reinvested_income",
        "freshness": "fresh",
        "freshness_status": "fresh",
    }
    values.update(updates)
    if "ingested_at" not in updates:
        values["ingested_at"] = updates.get(
            "available_at", "2024-02-01T00:00:00+00:00"
        )
    return _row(**values)


def _store_direct_curve_row(tmp_path, row: MacroObservation) -> None:
    with BitemporalStore(tmp_path) as store:
        store.record_observation(
            dataset_id=row.dataset_id,
            entity_id=row.series_id,
            stable_id=row.stable_id,
            value=row.ledger_value(),
            source_id=row.source_id,
            source_checksum=row.source_checksum,
            revision=row.revision,
            valid_from="2024-01-01T00:00:00+00:00",
            published_at=row.published_at,
            available_at=row.available_at,
            observed_at=row.observed_at,
            ingested_at=row.ingested_at,
            run_id="malformed-direct-row",
        )


def _store_direct_curve_ledger(tmp_path, row: MacroObservation, ledger: dict[str, object]) -> None:
    with BitemporalStore(tmp_path) as store:
        store.record_observation(
            dataset_id=row.dataset_id,
            entity_id=row.series_id,
            stable_id=row.stable_id,
            value=ledger,
            source_id=row.source_id,
            source_checksum=row.source_checksum,
            revision=row.revision,
            valid_from="2024-01-01T00:00:00+00:00",
            published_at=row.published_at,
            available_at=row.available_at,
            observed_at=row.observed_at,
            ingested_at=row.ingested_at,
            run_id="malformed-direct-ledger",
        )


def test_direct_curve_row_binds_declared_curve_to_storage_dataset(tmp_path) -> None:
    warehouse = MacroWarehouse()
    row = _direct_curve_row()
    with pytest.raises(MacroWarehouseError, match="ingest_curve"):
        warehouse.ingest([row], root=tmp_path)

    _store_direct_curve_row(tmp_path, row)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "dataset identity" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_direct_curve_row_rejects_publication_after_availability(tmp_path) -> None:
    warehouse = MacroWarehouse()
    row = _direct_curve_row(
        curve_id="mapped-curve",
        published_at="2030-01-01T00:00:00+00:00",
    )
    with pytest.raises(MacroWarehouseError, match="ingest_curve"):
        warehouse.ingest([row], root=tmp_path)

    _store_direct_curve_row(tmp_path, row)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "published_at" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_partial_curve_snapshot_is_never_visible(tmp_path) -> None:
    warehouse = MacroWarehouse()
    row = _direct_curve_row(
        curve_id="mapped-curve",
        curve_point_count=2,
    )
    _store_direct_curve_row(tmp_path, row)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "incomplete" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_curve_snapshot_append_is_atomic_and_authoritative_retry_succeeds(
    tmp_path, monkeypatch
) -> None:
    warehouse = MacroWarehouse()
    snapshot = _curve().model_copy(
        update={
            "points": (
                CurvePoint(tenor_years=1.0 / 365.0, rate=0.01),
                CurvePoint(tenor_years=2.0 / 365.0, rate=0.02),
            )
        }
    )
    original = BitemporalStore.record_observation
    calls = {"count": 0}

    def fail_on_second(self, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise BitemporalError("injected point failure")
        return original(self, **kwargs)

    monkeypatch.setattr(BitemporalStore, "record_observation", fail_on_second)
    with pytest.raises(MacroWarehouseError, match="injected point failure"):
        warehouse.ingest_curve(snapshot, root=tmp_path)
    assert warehouse.observations(root=tmp_path, dataset_id="curve:aud-official-spot") == []

    monkeypatch.setattr(BitemporalStore, "record_observation", original)
    summary = warehouse.ingest_curve(snapshot, root=tmp_path)
    assert summary["row_count"] == 2
    assert len(warehouse.observations(root=tmp_path, dataset_id="curve:aud-official-spot")) == 2


def test_curve_manifest_projection_failure_keeps_authoritative_sqlite_append(
    tmp_path, monkeypatch
) -> None:
    warehouse = MacroWarehouse()
    snapshot = _curve()
    original = macro_warehouse_module.atomic_write_json
    calls = {"count": 0}

    def fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("injected manifest failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(macro_warehouse_module, "atomic_write_json", fail_once)
    summary = warehouse.ingest_curve(snapshot, root=tmp_path)
    assert summary["row_count"] == 2
    assert summary["authoritative_storage"] == "sqlite"
    assert len(warehouse.observations(root=tmp_path, dataset_id="curve:aud-official-spot")) == 2
    with TransactionalStore(tmp_path) as store:
        persisted = store.get("macro_warehouse_manifest", str(summary["run_id"]))
    assert persisted is not None
    assert persisted.payload == summary
    assert not (tmp_path / "data" / "macro_warehouse" / "manifest.json").exists()


def test_curve_commit_failure_rolls_back_points_and_manifest(
    tmp_path, monkeypatch
) -> None:
    @contextmanager
    def fail_commit(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        finally:
            self.connection.rollback()
        raise sqlite3.OperationalError("injected commit failure")

    monkeypatch.setattr(TransactionalStore, "transaction", fail_commit)
    with pytest.raises(sqlite3.OperationalError, match="injected commit failure"):
        MacroWarehouse().ingest_curve(_curve(), root=tmp_path)

    with BitemporalStore(tmp_path) as store:
        assert store.observations("curve:aud-official-spot") == ()
        assert store.store.list("macro_warehouse_manifest") == ()
    assert not (tmp_path / "data" / "macro_warehouse" / "manifest.json").exists()


def test_curve_admission_rejects_availability_regression_before_append(tmp_path) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(
        _curve(available_at="2025-01-03T00:00:00+00:00"), root=tmp_path
    )
    with pytest.raises(MacroWarehouseError, match="revision"):
        warehouse.ingest_curve(
            _curve(
                revision=2,
                available_at="2025-01-02T00:00:00+00:00",
            ),
            root=tmp_path,
        )
    assert len(warehouse.observations(root=tmp_path, dataset_id="curve:aud-official-spot")) == 2


def test_concurrent_same_effective_revision_different_sources_have_one_commit(tmp_path) -> None:
    warehouse = MacroWarehouse()
    first = _curve()
    second = first.model_copy(
        update={
            "source_id": "official-central-bank-other-source",
            "source_checksum": "c" * 64,
        }
    )

    def append(snapshot: CurveSnapshot) -> str:
        warehouse.ingest_curve(snapshot, root=tmp_path)
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = []
        for future in (
            executor.submit(append, first),
            executor.submit(append, second),
        ):
            try:
                results.append(future.result())
            except MacroWarehouseError:
                results.append("rejected")

    assert sorted(results) == ["committed", "rejected"]
    rows = warehouse.observations(root=tmp_path, dataset_id="curve:aud-official-spot")
    assert len(rows) == 2
    assert {row.source_id for row in rows} in (
        {first.source_id},
        {second.source_id},
    )


def test_curve_rate_ignores_invalid_future_history_for_historical_query(tmp_path) -> None:
    first = _direct_curve_row(
        dataset_id="curve:historical-curve",
        series_id="historical-curve:1Y",
        curve_id="historical-curve",
        available_at="2025-01-02T00:00:00+00:00",
        source_terms="official terms",
        methodology="official method",
    )
    future_duplicate = first.model_copy(
        update={
            "source_id": "future-source",
            "source_checksum": "c" * 64,
            "available_at": "2025-03-01T00:00:00+00:00",
        }
    )
    _store_direct_curve_row(tmp_path, first)
    _store_direct_curve_row(tmp_path, future_duplicate)
    with BitemporalStore(tmp_path) as store:
        store.store.connection.execute(
            """
            INSERT INTO bitemporal_observations
                (observation_id, dataset_id, entity_id, stable_id, run_id, value_json,
                 valid_from, valid_to, published_at, available_at, observed_at,
                 ingested_at, revised_at, revision, source_id, source_checksum,
                 timezone_confidence, availability_confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "f" * 64,
                "curve:historical-curve",
                "historical-curve:1Y",
                "historical-curve:1Y",
                "future-malformed",
                "{malformed-json",
                "2025-01-01T00:00:00.000000+00:00",
                None,
                "2025-03-01T00:00:00.000000+00:00",
                "2025-03-01T00:00:00.123457+00:00",
                "2025-01-01T00:00:00.000000+00:00",
                "2025-03-01T00:00:00.000000+00:00",
                None,
                2,
                "future-malformed-source",
                "d" * 64,
                "exact",
                "exact",
                "active",
            ),
        )
        store.store.connection.commit()

    selected = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="historical-curve",
        tenor_years=1.0,
        decision_time="2025-01-15T00:00:00+00:00",
    )
    assert selected["status"] == "available"
    assert selected["source_id"] == first.source_id


@pytest.mark.parametrize(
    ("malformed_available_at", "should_fail_closed"),
    (
        ("2025-03-01T00:00:00.000000+00:00", False),
        ("2025-01-10T00:00:00.000000+00:00", True),
    ),
)
def test_observations_as_of_decodes_only_cutoff_eligible_rows(
    tmp_path, malformed_available_at: str, should_fail_closed: bool
) -> None:
    row = _row(
        dataset_id="historical-macro",
        series_id="historical-macro:AU",
        available_at="2025-01-02T00:00:00+00:00",
        published_at="2025-01-02T00:00:00+00:00",
        ingested_at="2025-01-02T00:00:00+00:00",
    )
    warehouse = MacroWarehouse()
    warehouse.ingest([row], root=tmp_path)
    with BitemporalStore(tmp_path) as store:
        store.store.connection.execute(
            """
            INSERT INTO bitemporal_observations
                (observation_id, dataset_id, entity_id, stable_id, run_id, value_json,
                 valid_from, valid_to, published_at, available_at, observed_at,
                 ingested_at, revised_at, revision, source_id, source_checksum,
                 timezone_confidence, availability_confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "e" * 64,
                "future-malformed-dataset",
                "future-malformed:AU",
                "future-malformed:AU",
                "future-malformed-run",
                "{malformed-json",
                "2025-01-01T00:00:00.000000+00:00",
                None,
                malformed_available_at,
                malformed_available_at,
                "2025-01-01T00:00:00.000000+00:00",
                "2025-03-01T00:00:00.000000+00:00",
                None,
                1,
                "future-malformed-source",
                "f" * 64,
                "exact",
                "exact",
                "active",
            ),
        )
        store.store.connection.commit()

    if should_fail_closed:
        with pytest.raises(ValueError):
            warehouse.observations_as_of(
                root=tmp_path,
                decision_time="2025-01-15T00:00:00+00:00",
            )
    else:
        selected = warehouse.observations_as_of(
            root=tmp_path,
            decision_time="2025-01-15T00:00:00+00:00",
        )
        assert [(item.dataset_id, item.value) for item in selected] == [
            ("historical-macro", row.value)
        ]


def test_curve_rate_preserves_subsecond_cutoff_and_includes_exact_availability(
    tmp_path,
) -> None:
    row = _direct_curve_row(
        dataset_id="curve:subsecond-curve",
        series_id="subsecond-curve:1Y",
        curve_id="subsecond-curve",
        available_at="2025-01-15T00:00:00.123456+00:00",
        observed_at="2025-01-01T00:00:00.000000+00:00",
        published_at="2025-01-01T00:00:00.000000+00:00",
        methodology="official subsecond curve",
    )
    _store_direct_curve_row(tmp_path, row)

    exact = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="subsecond-curve",
        tenor_years=1.0,
        decision_time="2025-01-15T00:00:00.123456+00:00",
    )
    before = MacroWarehouse().curve_rate(
        root=tmp_path,
        curve_id="subsecond-curve",
        tenor_years=1.0,
        decision_time="2025-01-15T00:00:00.123455+00:00",
    )
    assert exact["status"] == "available"
    assert before["status"] == "unavailable"


def test_non_risk_free_curve_rows_are_unavailable_for_cash(tmp_path) -> None:
    warehouse = MacroWarehouse()
    row = _direct_curve_row(curve_id="mapped-curve", dataset_kind="benchmark")
    with pytest.raises(MacroWarehouseError, match="ingest_curve"):
        warehouse.ingest([row], root=tmp_path / "reject")

    _store_direct_curve_row(tmp_path, row)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "risk_free" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_curve_with_inferred_availability_is_never_visible(tmp_path) -> None:
    warehouse = MacroWarehouse()
    row = _direct_curve_row(curve_id="mapped-curve")
    with BitemporalStore(tmp_path) as store:
        store.record_observation(
            dataset_id=row.dataset_id,
            entity_id=row.series_id,
            stable_id=row.stable_id,
            value=row.ledger_value(),
            source_id=row.source_id,
            source_checksum=row.source_checksum,
            revision=row.revision,
            valid_from="2024-01-01T00:00:00+00:00",
            published_at=row.published_at,
            available_at=row.available_at,
            observed_at=row.observed_at,
            ingested_at=row.ingested_at,
            run_id="inferred-direct-row",
            availability_confidence="inferred",
        )
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "confidence" in str(selected["reason"])
    assert selected["execution_allowed"] is False


@pytest.mark.parametrize("tenors", ((1.0, 1.0), (1.0, None)))
def test_malformed_direct_curve_tenors_are_unavailable(tmp_path, tenors) -> None:
    warehouse = MacroWarehouse()
    for index, tenor in enumerate(tenors):
        row = _direct_curve_row(
            curve_id="mapped-curve",
            series_id=f"mapped-curve:{index}",
            tenor_years=tenor,
            curve_point_count=2,
            value=0.01 + index * 0.01,
        )
        _store_direct_curve_row(tmp_path, row)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "tenor" in str(selected["reason"]) or "malformed" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_malformed_curve_ledger_decoding_is_unavailable(tmp_path) -> None:
    warehouse = MacroWarehouse()
    row = _direct_curve_row(curve_id="mapped-curve")
    ledger = row.ledger_value()
    ledger["tenor_years"] = "corrupt-tenor"
    _store_direct_curve_ledger(tmp_path, row, ledger)

    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "malformed" in str(selected["reason"])
    assert selected["execution_allowed"] is False


@pytest.mark.parametrize("reinvestment", (None, "unsupported"))
def test_unsupported_reinvestment_is_unavailable_at_snapshot_and_readback(
    tmp_path, reinvestment
) -> None:
    warehouse = MacroWarehouse()
    invalid_snapshot = _curve().model_copy(update={"reinvestment": reinvestment})
    with pytest.raises(MacroWarehouseError, match="reinvestment"):
        warehouse.ingest_curve(invalid_snapshot, root=tmp_path / "snapshot")

    row = _direct_curve_row(
        curve_id="mapped-curve",
        reinvestment=reinvestment,
    )
    _store_direct_curve_row(tmp_path, row)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id="mapped-curve",
        tenor_years=1.0,
        decision_time="2025-01-01T00:00:00+00:00",
    )
    assert selected["status"] == "unavailable"
    assert "reinvestment" in str(selected["reason"])
    assert selected["execution_allowed"] is False


def test_curve_snapshot_preserves_distinct_publication_and_availability(tmp_path) -> None:
    warehouse = MacroWarehouse()
    snapshot = _curve(
        published_at="2025-01-01T12:00:00+00:00",
        available_at="2025-01-02T00:00:00+00:00",
    )
    warehouse.ingest_curve(snapshot, root=tmp_path)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id=snapshot.curve_id,
        tenor_years=1.0,
        decision_time="2025-02-01T00:00:00+00:00",
    )
    assert selected["status"] == "available"
    assert selected["published_at"] == "2025-01-01T12:00:00+00:00"
    assert selected["available_at"] == "2025-01-02T00:00:00+00:00"

    invalid = snapshot.model_copy(
        update={"published_at": "2025-01-03T00:00:00+00:00"}
    )
    with pytest.raises(MacroWarehouseError, match="published_at"):
        warehouse.ingest_curve(invalid, root=tmp_path / "invalid")


@pytest.mark.parametrize(
    "updates",
    (
        {"minimum_horizon_years": True},
        {"maximum_horizon_years": "10.0"},
        {"minimum_horizon_years": float("nan")},
        {"maximum_horizon_years": float("inf")},
    ),
)
def test_proxy_mapping_loader_rejects_coercive_or_nonfinite_horizons(
    tmp_path, updates: dict[str, object]
) -> None:
    import json

    row: dict[str, object] = {
        "currency": "AUD",
        "minimum_horizon_years": 0.0,
        "maximum_horizon_years": 10.0,
        "curve_id": "aud-official",
        "fallback_curve_ids": [],
        "methodology": "official mapping",
        "execution_allowed": False,
    }
    row.update(updates)
    path = tmp_path / "risk_free_proxies.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "mappings": [row],
                "execution_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    assert load_risk_free_proxy_mappings(path) == ()


def test_proxy_mapping_loader_rejects_duplicate_json_keys_in_nested_mapping(tmp_path) -> None:
    path = tmp_path / "risk_free_proxies.json"
    path.write_text(
        '{"schema_version":"1.0","mappings":[{"currency":"AUD",'
        '"currency":"EUR","minimum_horizon_years":0.0,'
        '"maximum_horizon_years":10.0,"curve_id":"aud-official",'
        '"fallback_curve_ids":[],"methodology":"official mapping",'
        '"execution_allowed":false}],"execution_allowed":false}',
        encoding="utf-8",
    )
    assert load_risk_free_proxy_mappings(path) == ()


@pytest.mark.parametrize("curve_type", ("spot", "par", "forward"))
def test_official_curve_snapshot_types_are_retained(tmp_path, curve_type: str) -> None:
    warehouse = MacroWarehouse()
    snapshot = _curve().model_copy(update={"curve_type": curve_type})

    warehouse.ingest_curve(snapshot, root=tmp_path)
    selected = warehouse.curve_rate(
        root=tmp_path,
        curve_id=snapshot.curve_id,
        tenor_years=1.0,
        decision_time="2025-02-01T00:00:00+00:00",
    )

    assert selected["curve_type"] == curve_type
    assert selected["source_id"] == "official-central-bank-local-snapshot"
    assert selected["methodology"] == "Official decimal zero-rate curve"


def test_curve_and_benchmark_decision_time_versions_are_point_in_time(tmp_path) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(_curve(), root=tmp_path)
    warehouse.ingest_curve(
        _curve(
            version="v2",
            available_at="2025-02-01T00:00:00+00:00",
            revision=2,
            rates=(0.02, 0.04),
        ),
        root=tmp_path,
    )
    old = warehouse.curve_rate(
        root=tmp_path,
        curve_id="aud-official-spot",
        tenor_years=2.0,
        decision_time="2025-01-15T00:00:00+00:00",
    )
    new = warehouse.curve_rate(
        root=tmp_path,
        curve_id="aud-official-spot",
        tenor_years=2.0,
        decision_time="2025-03-01T00:00:00+00:00",
    )

    assert (old["curve_version"], old["rate"]) == ("v1", 0.0)
    assert (new["curve_version"], new["rate"]) == ("v2", 0.03)

    base = {
        "benchmark_id": "au-sovereign-duration",
        "category": "sovereign",
        "currency": "AUD",
        "effective_at": "2025-01-01T00:00:00+00:00",
        "source_id": "official-index-methodology",
        "source_terms": "lawful_local_metadata_only",
        "methodology": "Australian sovereign duration benchmark",
        "coverage": ("sovereign", "duration"),
    }
    warehouse.ingest_benchmark(
        BenchmarkMetadata(
            **base,
            version="2025.1",
            available_at="2025-01-02T00:00:00+00:00",
            ingested_at="2025-01-02T00:00:00+00:00",
            source_checksum="c" * 64,
        ),
        root=tmp_path,
    )
    warehouse.ingest_benchmark(
        BenchmarkMetadata(
            **base,
            version="2025.2",
            available_at="2025-02-02T00:00:00+00:00",
            ingested_at="2025-02-02T00:00:00+00:00",
            source_checksum="d" * 64,
            revision=2,
        ),
        root=tmp_path,
    )
    historical = warehouse.as_of(
        root=tmp_path,
        dataset_id="benchmark:au-sovereign-duration",
        decision_time="2025-01-15T00:00:00+00:00",
    )
    current = warehouse.as_of(
        root=tmp_path,
        dataset_id="benchmark:au-sovereign-duration",
        decision_time="2025-03-01T00:00:00+00:00",
    )
    assert historical["benchmark_version"].tolist() == ["2025.1"]
    assert current["benchmark_version"].tolist() == ["2025.2"]


def test_latest_then_known_effective_curve_and_benchmark_snapshots_are_selected(
    tmp_path,
) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(_curve(), root=tmp_path)
    later = _curve(
        version="v2-effective",
        effective_at="2025-02-01T00:00:00+00:00",
        available_at="2025-02-02T00:00:00+00:00",
        rates=(0.03, 0.05),
    ).model_copy(
        update={
            "points": (
                CurvePoint(tenor_years=2.0, rate=0.03),
                CurvePoint(tenor_years=4.0, rate=0.05),
            )
        }
    )
    warehouse.ingest_curve(later, root=tmp_path)

    before = warehouse.curve_rate(
        root=tmp_path,
        curve_id="aud-official-spot",
        tenor_years=1.0,
        decision_time="2025-01-15T00:00:00+00:00",
    )
    after = warehouse.curve_rate(
        root=tmp_path,
        curve_id="aud-official-spot",
        tenor_years=3.0,
        decision_time="2025-03-01T00:00:00+00:00",
    )
    old_tenor_after = warehouse.curve_rate(
        root=tmp_path,
        curve_id="aud-official-spot",
        tenor_years=1.0,
        decision_time="2025-03-01T00:00:00+00:00",
    )

    assert before["curve_version"] == "v1"
    assert after["curve_version"] == "v2-effective"
    assert after["rate"] == 0.04
    assert old_tenor_after["status"] == "unavailable"
    assert old_tenor_after["coverage"] == [2.0, 4.0]

    common = {
        "benchmark_id": "aud-aggregate",
        "category": "aggregate",
        "currency": "AUD",
        "source_id": "official-index-owner",
        "source_terms": "lawful_local_metadata_only",
        "methodology": "Published aggregate benchmark methodology",
    }
    warehouse.ingest_benchmark(
        BenchmarkMetadata(
            **common,
            version="v1",
            effective_at="2025-01-01T00:00:00+00:00",
            available_at="2025-01-02T00:00:00+00:00",
            ingested_at="2025-01-02T00:00:00+00:00",
            source_checksum="e" * 64,
        ),
        root=tmp_path,
    )
    warehouse.ingest_benchmark(
        BenchmarkMetadata(
            **common,
            version="v2",
            effective_at="2025-02-01T00:00:00+00:00",
            available_at="2025-02-02T00:00:00+00:00",
            ingested_at="2025-02-02T00:00:00+00:00",
            source_checksum="f" * 64,
        ),
        root=tmp_path,
    )
    old_coverage = warehouse.curve_benchmark_coverage(
        root=tmp_path, decision_time="2025-01-15T00:00:00+00:00"
    )
    new_coverage = warehouse.curve_benchmark_coverage(
        root=tmp_path, decision_time="2025-03-01T00:00:00+00:00"
    )
    assert old_coverage["benchmark_versions"] == ["v1"]
    assert new_coverage["benchmark_versions"] == ["v2"]


@pytest.mark.parametrize(
    ("update", "message"),
    (
        ({"benchmark_id": ""}, "missing required fields"),
        ({"source_checksum": "not-a-checksum"}, "SHA-256"),
        ({"available_at": "not-a-time"}, "Invalid isoformat"),
        ({"execution_allowed": True}, "Input should be False"),
    ),
)
def test_invalid_benchmark_metadata_fails_closed(tmp_path, update, message) -> None:
    values = {
        "benchmark_id": "aud-sovereign",
        "version": "v1",
        "category": "sovereign",
        "currency": "AUD",
        "effective_at": "2025-01-01T00:00:00+00:00",
        "available_at": "2025-01-02T00:00:00+00:00",
        "ingested_at": "2025-01-02T00:00:00+00:00",
        "source_id": "official-index-owner",
        "source_checksum": "a" * 64,
        "source_terms": "lawful_local_metadata_only",
        "methodology": "Published benchmark methodology",
    }
    values.update(update)

    with pytest.raises((MacroWarehouseError, ValueError), match=message):
        MacroWarehouse().ingest_benchmark(
            BenchmarkMetadata.model_validate(values), root=tmp_path
        )


def test_currency_horizon_mapping_fallbacks_and_unsupported_credit_are_explicit(
    tmp_path,
) -> None:
    warehouse = MacroWarehouse()
    warehouse.ingest_curve(_curve(curve_id="aud-fallback"), root=tmp_path)
    mapping = RiskFreeProxyMapping(
        currency="AUD",
        minimum_horizon_years=1.0,
        maximum_horizon_years=3.0,
        curve_id="aud-primary-missing",
        fallback_curve_ids=("aud-fallback",),
        methodology="Official cash proxy mapping v1",
    )

    selected = warehouse.risk_free_rate(
        root=tmp_path,
        mappings=(mapping,),
        currency="AUD",
        horizon_years=2.0,
        decision_time="2025-02-01T00:00:00+00:00",
    )
    unsupported_currency = warehouse.risk_free_rate(
        root=tmp_path,
        mappings=(mapping,),
        currency="EUR",
        horizon_years=2.0,
        decision_time="2025-02-01T00:00:00+00:00",
    )
    outside_curve = warehouse.risk_free_rate(
        root=tmp_path,
        mappings=(mapping,),
        currency="AUD",
        horizon_years=3.5,
        decision_time="2025-02-01T00:00:00+00:00",
    )
    credit = warehouse.issuer_credit_curve(
        issuer_id="issuer-1", decision_time="2025-02-01T00:00:00+00:00"
    )

    assert selected["status"] == "available"
    assert selected["fallback"] is True
    assert selected["fallback_from"] == "aud-primary-missing"
    assert unsupported_currency["status"] == "unavailable"
    assert "mapping" in str(unsupported_currency["reason"])
    assert outside_curve["status"] == "unavailable"
    assert credit == {
        "status": "unavailable",
        "reason": "issuer-specific credit curves are unsupported",
        "issuer_id": "issuer-1",
        "decision_time": "2025-02-01T00:00:00+00:00",
        "execution_allowed": False,
    }

    overlapping = RiskFreeProxyMapping(
        currency="AUD",
        minimum_horizon_years=0.5,
        maximum_horizon_years=2.5,
        curve_id="aud-fallback",
        methodology="Conflicting mapping fixture",
    )
    ambiguous = warehouse.risk_free_rate(
        root=tmp_path,
        mappings=(mapping, overlapping),
        currency="AUD",
        horizon_years=2.0,
        decision_time="2025-02-01T00:00:00+00:00",
    )
    assert ambiguous["status"] == "unavailable"
    assert "overlap" in str(ambiguous["reason"])
