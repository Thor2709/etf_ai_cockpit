from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_cockpit.core.config import load_config
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


def test_data_health_ui_names_cache_provenance_and_failure_columns() -> None:
    from etf_cockpit.app.pages.data_health import data_health_page
    from etf_cockpit.services import build_snapshot
    from etf_cockpit.app.state import AppState

    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {"route": "/data-health", "update": lambda self: None})()
    values = set(value for value in _text_values(data_health_page(page, state)) if value)
    assert {"Data Health", "Dataset", "Path", "Checksum", "Last success", "Last failure"} <= values
