from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.config import load_config
import etf_cockpit.data.health as health

from etf_cockpit.data.health import DataHealthStatus, build_data_health, export_data_health


def _text_values(control):
    yield str(getattr(control, "value", "") or "")
    for attribute in ("controls", "columns", "rows", "cells", "label"):
        children = getattr(control, attribute, []) or []
        if not isinstance(children, (list, tuple)):
            children = (children,)
        for child in children:
            yield from _text_values(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _text_values(content)


def test_health_distinguishes_missing_stale_and_healthy_stores(tmp_path: Path) -> None:
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame({"date": ["2026-07-09"], "value": [1]}).to_parquet(clean / "prices.parquet")
    pd.DataFrame({"date": ["2026-06-01"], "value": [1]}).to_parquet(clean / "fx.parquet")
    forecasts = tmp_path / "data" / "forecasts"
    forecasts.mkdir(parents=True)
    pd.DataFrame({"forecast_date": ["2026-07-09"], "expected_return": [0.01]}).to_csv(forecasts / "forecast_20260709.csv", index=False)

    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10", stale_after_days=7)
    rows = {row.dataset: row for row in report.rows}
    assert rows["prices"].status is DataHealthStatus.HEALTHY
    assert rows["fx"].status is DataHealthStatus.STALE
    assert rows["news"].status is DataHealthStatus.MISSING
    assert {"forecasts", "backtest", "macro"} <= set(rows)
    assert rows["backtest"].provider == "derived"
    assert rows["forecasts"].checksum is not None
    assert report.has_failures is True


def test_corrupt_store_is_reported_and_exported(tmp_path: Path) -> None:
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    (clean / "prices.parquet").write_bytes(b"not parquet")
    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    row = next(item for item in report.rows if item.dataset == "prices")
    assert row.status is DataHealthStatus.CORRUPT
    destination = tmp_path / "health.csv"
    export_data_health(report, destination)
    assert destination.exists()
    assert "corrupt" in destination.read_text(encoding="utf-8")
    assert destination.read_text(encoding="utf-8").splitlines()[0].endswith("warnings")


def test_data_health_ui_names_cache_provenance_and_failure_columns() -> None:
    from etf_cockpit.app.pages.data_health import data_health_page
    from etf_cockpit.services import build_snapshot
    from etf_cockpit.app.state import AppState

    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {"route": "/data-health", "update": lambda self: None})()
    values = set(value for value in _text_values(data_health_page(page, state)) if value)
    assert {"Data Health", "Dataset", "Path", "Checksum", "Last success", "Last failure"} <= values
    assert {"Filter status", "Filter dataset", "Filter provider", "Provider status", "Filings", "ETF", "Errors"} <= values


def test_health_inventory_exposes_explicit_migration_status(tmp_path: Path) -> None:
    state_path = tmp_path / "data" / ".migration_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "applied": [
                    {"version": 1, "name": "provider_identity_evidence_v1", "applied_at": "2026-07-01T00:00:00+00:00"},
                    {"version": 2, "name": "official_documents_v1", "applied_at": "2026-07-02T00:00:00+00:00"},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    rows = {row.dataset: row for row in report.rows}

    migration = rows["migration_status"]
    assert migration.status is DataHealthStatus.STALE
    assert migration.as_of == "2026-07-02T00:00:00+00:00"
    assert any("pending_migrations:2" in warning for warning in migration.warnings)
    assert report.migration_status is migration


def test_missing_migration_state_is_not_inferred_from_schema_markers(tmp_path: Path) -> None:
    marker = tmp_path / "data" / ".schema_versions" / "history_changes_v1.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"schema_version": 4}', encoding="utf-8")

    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    migration = report.migration_status

    assert migration.status is DataHealthStatus.MISSING
    assert migration.last_success is None
    assert "migration_markers_not_inferred" in migration.warnings


def test_health_provenance_comes_from_persisted_session_history(tmp_path: Path) -> None:
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    prices_path = clean / "prices.parquet"
    pd.DataFrame({"date": ["2026-07-09"], "value": [1]}).to_parquet(prices_path)
    log_path = tmp_path / "logs" / "session.jsonl"
    log_path.parent.mkdir(parents=True)
    events = [
        {
            "event_type": "activity_complete",
            "status": "success",
            "timestamp_local": "2026-07-09T10:00:00+10:00",
            "timestamp_utc": "2026-07-09T00:00:00+00:00",
            "file_paths": [str(prices_path)],
        },
        {
            "event_type": "activity_failed",
            "status": "failed",
            "timestamp_local": "2026-07-10T11:00:00+10:00",
            "timestamp_utc": "2026-07-10T01:00:00+00:00",
            "file_paths": [str(tmp_path / "data" / "clean" / "fx.parquet")],
        },
    ]
    log_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    rows = {row.dataset: row for row in report.rows}

    assert rows["prices"].last_success == "2026-07-09T10:00:00+10:00"
    assert rows["prices"].last_success != report.created_at
    assert rows["fx"].last_failure == "2026-07-10T11:00:00+10:00"
    assert rows["news"].last_success is None
    assert "history_unavailable" in rows["news"].warnings


def test_macro_inventory_uses_dated_file_content_for_freshness(tmp_path: Path) -> None:
    macro_dir = tmp_path / "data" / "raw" / "macro"
    macro_dir.mkdir(parents=True)
    pd.DataFrame({"date": ["2026-06-01"], "value": [100]}).to_csv(macro_dir / "macro.csv", index=False)

    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10", stale_after_days=7)
    row = next(item for item in report.rows if item.dataset == "macro")

    assert row.status is DataHealthStatus.STALE
    assert row.as_of == "2026-06-01"
    assert row.freshness == "stale"


def test_macro_schema_mismatch_and_corrupt_states_are_explicit(tmp_path: Path) -> None:
    macro_dir = tmp_path / "data" / "raw" / "macro"
    macro_dir.mkdir(parents=True)
    pd.DataFrame({"value": [100]}).to_csv(macro_dir / "missing-date.csv", index=False)
    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    assert next(item for item in report.rows if item.dataset == "macro").status is DataHealthStatus.SCHEMA_MISMATCH

    (macro_dir / "missing-date.csv").unlink()
    (macro_dir / "broken.parquet").write_bytes(b"not-a-parquet")
    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    assert next(item for item in report.rows if item.dataset == "macro").status is DataHealthStatus.CORRUPT


def test_macro_invalid_sibling_remains_visible_with_valid_file(tmp_path: Path) -> None:
    macro_dir = tmp_path / "data" / "raw" / "macro"
    macro_dir.mkdir(parents=True)
    pd.DataFrame({"date": ["2026-07-09"], "value": [100]}).to_csv(macro_dir / "valid.csv", index=False)
    (macro_dir / "broken.parquet").write_bytes(b"not-a-parquet")

    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    row = next(item for item in report.rows if item.dataset == "macro")

    assert row.status is DataHealthStatus.CORRUPT
    assert "invalid_file:broken.parquet:corrupt" in row.warnings


def test_health_filters_are_case_insensitive_and_support_all_values(tmp_path: Path) -> None:
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame({"date": ["2026-06-01"], "value": [1]}).to_parquet(clean / "prices.parquet")
    report = build_data_health(load_config(), tmp_path, as_of_date="2026-07-10")
    stale = health.filter_data_health_rows(report.rows, status="STALE")
    assert stale and all(row.status is DataHealthStatus.STALE for row in stale)
    assert health.filter_data_health_rows(report.rows, dataset="PRICES") == tuple(row for row in report.rows if row.dataset == "prices")
    assert health.filter_data_health_rows(report.rows, provider="missing") == ()
    assert health.filter_data_health_rows(report.rows, status="all") == report.rows
