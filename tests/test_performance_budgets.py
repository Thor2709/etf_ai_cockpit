from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.core.performance import (
    PerformanceBudgetError,
    build_performance_report,
    evaluate_budget,
    load_performance_budgets,
    measure_performance,
    write_performance_report,
)


def test_versioned_budget_policy_is_complete_and_sorted() -> None:
    budgets = load_performance_budgets()

    assert budgets
    assert [item.metric_id for item in budgets] == sorted(item.metric_id for item in budgets)
    assert {item.unit for item in budgets} >= {"ms", "MiB", "bytes"}
    assert all(item.tolerance_pct >= 0 for item in budgets)


def test_budget_evaluation_blocks_only_beyond_tolerance_and_reports_regression() -> None:
    budgets = load_performance_budgets()
    budget = next(item for item in budgets if item.metric_id == "route_render")

    passed = evaluate_budget("route_render", budget.limit * 1.05, budgets=budgets, baseline=budget.limit)
    failed = evaluate_budget("route_render", budget.limit * 1.25, budgets=budgets, baseline=budget.limit)

    assert passed.status == "passed"
    assert failed.status == "failed"
    assert failed.regression_pct == pytest.approx(25.0)
    assert "tolerance" in failed.message


def test_measurement_records_duration_and_peak_memory_without_network(tmp_path: Path) -> None:
    path = tmp_path / "performance.jsonl"
    with measure_performance("route_render", store_path=path):
        _ = ["local"] * 100

    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["event_type"] == "performance"
    assert row["metric_id"] == "route_render"
    assert row["duration_ms"] >= 0
    assert row["peak_memory_mb"] >= 0
    assert row["network_calls"] is False


def test_report_uses_latest_resource_measurements_and_writes_json_and_markdown(tmp_path: Path) -> None:
    timing_path = tmp_path / "timings.jsonl"
    with measure_performance("route_render", store_path=timing_path):
        pass

    policy_path = Path(__file__).resolve().parents[1] / "configs" / "performance_budgets.yaml"
    report = build_performance_report(tmp_path, timing_path=timing_path, budgets_path=policy_path)
    json_path = tmp_path / "performance.json"
    markdown_path = tmp_path / "performance.md"
    write_performance_report(report, json_path, markdown_path)

    assert report["schema_version"] == "performance-budgets.v1"
    assert report["status"] in {"passed", "unmeasured"}
    route_measurement = next(item for item in report["measurements"] if item["metric_id"] == "route_render")
    assert route_measurement["sample_count"] == 1
    assert sum(item["metric_id"] == "local_storage" for item in report["measurements"]) == 1
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == "performance-budgets.v1"
    assert "Performance budget report" in markdown_path.read_text(encoding="utf-8")


def test_invalid_budget_policy_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "budgets.yaml"
    path.write_text("schema_version: wrong\nbudgets: []\n", encoding="utf-8")

    with pytest.raises(PerformanceBudgetError):
        load_performance_budgets(path)


def test_over_budget_report_is_a_release_blocking_failure(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "configs" / "performance_budgets.yaml").write_text(
        "schema_version: performance-budgets.v1\n"
        "budgets:\n"
        "  - {metric_id: route_render, category: ui, unit: ms, limit: 1, tolerance_pct: 0}\n"
        "  - {metric_id: local_storage, category: storage, unit: bytes, limit: 1000000, tolerance_pct: 0}\n",
        encoding="utf-8",
    )
    (tmp_path / "logs" / "timings.jsonl").write_text(
        '{"action_id":"route_render","duration_ms":2,"step":"render"}\n',
        encoding="utf-8",
    )

    report = build_performance_report(tmp_path)

    assert report["status"] == "failed"
    assert report["failures"] == ["route_render"]
