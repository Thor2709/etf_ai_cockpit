from __future__ import annotations

import json

import pandas as pd

from etf_cockpit.models.coverage_audit import build_coverage_audit, coverage_summary_lines, write_coverage_audit
from etf_cockpit.models.model_zoo import model_zoo_frame
from etf_cockpit.features.forecast_lab import build_forecast_lab_report


def test_model_cards_expose_subgroup_results_and_unavailable_reason() -> None:
    result = {
        "dimension": "region",
        "bucket": "EU",
        "observation_coverage": 0.5,
        "status": "unsupported",
        "authority": "unsupported",
        "warnings": ["coverage_below_threshold"],
    }

    frame = model_zoo_frame(subgroup_results_by_model={"naive_drift": [result]})
    cards = frame.set_index("model_id")

    assert cards.loc["naive_drift", "subgroup_status"] == "available"
    assert cards.loc["naive_drift", "subgroup_results"] == [result]
    assert cards.loc["naive_drift", "subgroup_reason"] is None
    assert cards.loc["historical_median", "subgroup_status"] == "unavailable"
    assert cards.loc["historical_median", "subgroup_reason"]


def test_forecast_lab_passes_per_model_subgroup_audits_to_model_cards() -> None:
    dates = pd.bdate_range("2026-01-01", periods=12)
    prices = pd.DataFrame(
        [
            {"etf_id": etf_id, "date": day, "adjusted_close": 100.0 + index}
            for etf_id in ("A", "B")
            for index, day in enumerate(dates)
        ]
    )
    forecasts = pd.DataFrame(
        [
            {
                "model_name": "naive_drift",
                "etf_id": etf_id,
                "forecast_date": dates[index],
                "horizon_days": 1,
                "expected_return": 0.01,
                "q10_return": -0.01,
                "q90_return": 0.03,
                "status": "ok",
            }
            for etf_id in ("A", "B")
            for index in range(3, 9)
        ]
    )
    universe = [
        {"id": "A", "enabled": True, "region": "EU", "sector": "Technology", "currency": "EUR", "exchange": "XETRA"},
        {"id": "B", "enabled": True, "region": "US", "sector": "Technology", "currency": "USD", "exchange": "NYSE"},
    ]

    report = build_forecast_lab_report(
        forecasts,
        prices,
        as_of_date=dates[-1],
        subgroup_universe=universe,
    )
    cards = report["model_catalogue"].set_index("model_id")

    assert cards.loc["naive_drift", "subgroup_status"] == "available"
    assert any(group["dimension"] == "geography" for group in cards.loc["naive_drift", "subgroup_results"])
    assert cards.loc["historical_median", "subgroup_status"] == "unavailable"
    assert cards.loc["historical_median", "subgroup_reason"]


def test_coverage_dashboard_summary_includes_subgroup_results() -> None:
    report = build_coverage_audit(
        [
            {"id": "A", "enabled": True, "region": "EU", "sector": "Technology", "currency": "EUR", "exchange": "XETRA"},
            {"id": "B", "enabled": True, "region": "US", "sector": "Technology", "currency": "USD", "exchange": "NYSE"},
        ],
        pd.DataFrame(
            [
                {"etf_id": "A", "date": "2024-01-01", "adjusted_close": 100.0},
                {"etf_id": "A", "date": "2024-01-02", "adjusted_close": 101.0},
                {"etf_id": "B", "date": "2024-01-01", "adjusted_close": 100.0},
                {"etf_id": "B", "date": "2024-01-02", "adjusted_close": 101.0},
            ]
        ),
        as_of_date="2024-01-02",
    )

    lines = coverage_summary_lines(report)

    assert any("geography=EU" in line and "coverage=100%" in line for line in lines)
    assert any("geography=US" in line and "coverage=100%" in line for line in lines)


def test_coverage_audit_history_appends_dated_versioned_drift(tmp_path) -> None:
    universe = [
        {"id": "A", "enabled": True, "region": "EU", "sector": "Technology", "currency": "EUR", "exchange": "XETRA"},
        {"id": "B", "enabled": True, "region": "EU", "sector": "Technology", "currency": "EUR", "exchange": "XETRA"},
    ]
    first_prices = pd.DataFrame(
        [
            {"etf_id": "A", "date": day, "adjusted_close": value}
            for day, value in zip(
                ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"),
                (100.0, 101.0, 102.0, 103.0, 104.0),
            )
        ]
    )
    complete_prices = pd.concat(
        [
            first_prices,
            pd.DataFrame(
                [
                    {"etf_id": "B", "date": day, "adjusted_close": value}
                    for day, value in zip(
                        ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"),
                        (100.0, 101.0, 102.0, 103.0, 104.0),
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    first_forecasts = pd.DataFrame(
        [
            {"etf_id": "A", "model_name": "baseline", "forecast_date": "2024-01-01", "horizon_days": 1, "expected_return": 0.02, "q10_return": 0.0, "q90_return": 0.04, "status": "ok"}
        ]
    )
    complete_forecasts = pd.concat(
        [
            first_forecasts,
            pd.DataFrame(
                [
                    {"etf_id": "B", "model_name": "baseline", "forecast_date": "2024-01-01", "horizon_days": 1, "expected_return": -0.01, "q10_return": -0.03, "q90_return": 0.01, "status": "ok"}
                ]
            ),
        ],
        ignore_index=True,
    )
    partial = build_coverage_audit(universe, first_prices, first_forecasts, as_of_date="2024-01-05")
    complete = build_coverage_audit(universe, complete_prices, complete_forecasts, as_of_date="2024-01-06")

    write_coverage_audit(partial, tmp_path)
    write_coverage_audit(complete, tmp_path)
    history_path = tmp_path / "coverage_audit_history.jsonl"
    records = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 2
    assert [record["as_of_date"] for record in records] == ["2024-01-05", "2024-01-06"]
    assert all(record["history_schema_version"] == "coverage-audit-history.v1" for record in records)
    assert all(record["recorded_at"] and record["report_checksum"] for record in records)
    early_group = next(group for group in records[0]["report"]["groups"] if group["dimension"] == "geography")
    later_group = next(group for group in records[1]["report"]["groups"] if group["dimension"] == "geography")
    assert early_group["universe_count"] == later_group["universe_count"] == 2
    assert early_group["observed_count"] == 1
    assert later_group["observed_count"] == 2
    assert early_group["observation_coverage"] == 0.5
    assert later_group["observation_coverage"] == 1.0
    assert early_group["directional_accuracy"] == 1.0
    assert later_group["directional_accuracy"] == 0.5
