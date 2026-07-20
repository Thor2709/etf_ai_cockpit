from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.models.coverage_audit import CoverageThresholds, build_coverage_audit, write_coverage_audit


def _universe() -> list[dict[str, object]]:
    return [
        {"id": "A", "enabled": True, "region": "EU", "sector": "Technology", "size": "large", "currency": "EUR", "exchange": "XETRA"},
        {"id": "B", "enabled": True, "region": "EU", "sector": "Technology", "size": "large", "currency": "EUR", "exchange": "XETRA"},
        {"id": "C", "enabled": True, "region": "US", "sector": "Healthcare", "size": "small", "currency": "USD", "exchange": "NYSE"},
    ]


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"etf_id": "A", "date": "2024-01-01", "adjusted_close": 100.0},
            {"etf_id": "A", "date": "2024-01-02", "adjusted_close": 102.0},
            {"etf_id": "A", "date": "2024-01-03", "adjusted_close": 104.0},
            {"etf_id": "A", "date": "2024-01-04", "adjusted_close": 105.0},
            {"etf_id": "A", "date": "2024-01-05", "adjusted_close": 106.0},
            {"etf_id": "B", "date": "2024-01-01", "adjusted_close": 100.0},
            {"etf_id": "B", "date": "2024-01-02", "adjusted_close": 99.0},
            {"etf_id": "B", "date": "2024-01-03", "adjusted_close": 98.0},
            {"etf_id": "B", "date": "2024-01-04", "adjusted_close": 97.0},
            {"etf_id": "B", "date": "2024-01-05", "adjusted_close": 96.0},
        ]
    )


def test_subgroup_metrics_and_authority_do_not_inherit_from_aggregate() -> None:
    forecasts = pd.DataFrame(
        [
            {"etf_id": "A", "model_name": "baseline", "forecast_date": "2024-01-01", "horizon_days": 1, "expected_return": 0.02, "q10_return": 0.0, "q90_return": 0.04, "status": "ok"},
            {"etf_id": "B", "model_name": "baseline", "forecast_date": "2024-01-01", "horizon_days": 1, "expected_return": -0.01, "q10_return": -0.03, "q90_return": 0.01, "status": "ok"},
        ]
    )
    report = build_coverage_audit(
        _universe(),
        _prices(),
        forecasts,
        [SimpleNamespace(etf_id="A", action="add"), SimpleNamespace(etf_id="C", action="hold")],
        as_of_date="2024-01-03",
        thresholds=CoverageThresholds(minimum_observation_coverage=1.0),
    )

    technology = next(group for group in report.groups if (group.dimension, group.bucket) == ("sector", "Technology"))
    healthcare = next(group for group in report.groups if (group.dimension, group.bucket) == ("sector", "Healthcare"))
    assert technology.status == "supported"
    assert technology.authority == "evidence_only"
    assert technology.matured_forecasts == 2
    assert technology.selected_count == 1
    assert healthcare.observed_count == 0
    assert healthcare.authority == "unsupported"
    assert "sector:Healthcare" in report.unsupported_zones
    assert report.supported_universe == ("A", "B")
    assert report.authority == "manual_review"


def test_synthetic_missingness_and_missing_metadata_are_explicit() -> None:
    universe = [
        {"id": "A", "enabled": True, "region": "EU", "sector": "Technology", "currency": "EUR", "exchange": "XETRA"},
        {"id": "B", "enabled": True, "region": "EU", "sector": None, "currency": "EUR", "exchange": "XETRA"},
    ]
    prices = pd.DataFrame([{"etf_id": "A", "adjusted_close": 100.0}])

    report = build_coverage_audit(universe, prices)

    sector_missing = next(group for group in report.groups if (group.dimension, group.bucket) == ("sector", "unavailable"))
    geography = next(group for group in report.groups if (group.dimension, group.bucket) == ("geography", "EU"))
    assert "missing_sector_metadata" in sector_missing.warnings
    assert sector_missing.authority == "unsupported"
    assert "synthetic_missingness_observed" in geography.warnings
    assert geography.observation_coverage == 0.5


def test_coverage_export_is_auditable_and_deterministic(tmp_path) -> None:
    report = build_coverage_audit(_universe(), _prices(), as_of_date="2024-01-03")

    json_path, markdown_path = write_coverage_audit(report, tmp_path)
    payload = json_path.read_text(encoding="utf-8")
    markdown = markdown_path.read_text(encoding="utf-8")

    assert payload.endswith("\n")
    assert '"aggregate_metrics_inherit_authority": false' in payload
    assert "Coverage groups" in markdown
    assert "Unsupported zones" in markdown
