from __future__ import annotations

from etf_cockpit.data.macro_warehouse import (
    MacroObservation,
    MacroWarehouse,
    parse_csv_records,
    parse_world_bank_records,
    transform_observations,
)


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

    assert historical.loc[historical["period_start"] == "2024-01-01", "value"].tolist() == [11.0]
    assert current.loc[current["period_start"] == "2024-01-01", "value"].tolist() == [12.0]
    assert historical.loc[0, "country"] == "AUS"


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


def test_missing_country_and_currency_are_explicitly_unavailable(tmp_path) -> None:
    row = _row(country=None, currency=None)
    assert row.availability_status == "unavailable_context"
    summary = MacroWarehouse().ingest([row], root=tmp_path)
    assert summary["execution_allowed"] is False
    report = MacroWarehouse().summary(root=tmp_path)
    assert report["status"] == "available"
    assert report["missing_country_or_currency_count"] == 1
