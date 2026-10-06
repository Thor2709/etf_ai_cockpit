"""Versioned local performance budgets and resource evidence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import tracemalloc
from typing import Iterator

import yaml

from etf_cockpit.core.timing import read_timing_records


PERFORMANCE_SCHEMA_VERSION = "performance-budgets.v1"
DEFAULT_BUDGETS_PATH = Path("configs/performance_budgets.yaml")


class PerformanceBudgetError(ValueError):
    """Raised when a performance policy is malformed or unavailable."""


@dataclass(frozen=True)
class PerformanceBudget:
    metric_id: str
    category: str
    unit: str
    limit: float
    tolerance_pct: float
    dataset_size: int | None
    description: str

    @property
    def threshold(self) -> float:
        return self.limit * (1 + self.tolerance_pct / 100)


@dataclass(frozen=True)
class BudgetEvaluation:
    metric_id: str
    status: str
    observed: float
    limit: float | None
    threshold: float | None
    unit: str
    baseline: float | None
    regression_pct: float | None
    message: str


def load_performance_budgets(path: Path | None = None) -> tuple[PerformanceBudget, ...]:
    source = Path(path or DEFAULT_BUDGETS_PATH)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PerformanceBudgetError(f"Could not load performance budget policy: {source}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PERFORMANCE_SCHEMA_VERSION:
        raise PerformanceBudgetError("performance policy must use schema performance-budgets.v1")
    raw_budgets = payload.get("budgets")
    if not isinstance(raw_budgets, list) or not raw_budgets:
        raise PerformanceBudgetError("performance policy must contain budgets")
    budgets: list[PerformanceBudget] = []
    seen: set[str] = set()
    for raw in raw_budgets:
        if not isinstance(raw, dict):
            raise PerformanceBudgetError("each performance budget must be an object")
        metric_id = str(raw.get("metric_id", "")).strip().lower()
        category = str(raw.get("category", "")).strip().lower()
        unit = str(raw.get("unit", "")).strip()
        if not metric_id or not category or not unit or metric_id in seen:
            raise PerformanceBudgetError(f"invalid or duplicate performance metric: {metric_id!r}")
        try:
            limit = float(raw["limit"])
            tolerance = float(raw.get("tolerance_pct", payload.get("regression_tolerance_pct", 0)))
            dataset_size = int(raw["dataset_size"]) if raw.get("dataset_size") is not None else None
        except (KeyError, TypeError, ValueError) as exc:
            raise PerformanceBudgetError(f"invalid numeric budget: {metric_id}") from exc
        if not math.isfinite(limit) or limit <= 0 or not math.isfinite(tolerance) or tolerance < 0:
            raise PerformanceBudgetError(f"performance budget must be finite and positive: {metric_id}")
        if dataset_size is not None and dataset_size <= 0:
            raise PerformanceBudgetError(f"dataset_size must be positive: {metric_id}")
        seen.add(metric_id)
        budgets.append(
            PerformanceBudget(
                metric_id=metric_id,
                category=category,
                unit=unit,
                limit=limit,
                tolerance_pct=tolerance,
                dataset_size=dataset_size,
                description=str(raw.get("description", "")).strip(),
            )
        )
    return tuple(sorted(budgets, key=lambda item: item.metric_id))


def evaluate_budget(
    metric_id: str,
    observed: float,
    *,
    budgets: tuple[PerformanceBudget, ...],
    baseline: float | None = None,
) -> BudgetEvaluation:
    key = str(metric_id).strip().lower()
    budget = next((item for item in budgets if item.metric_id == key), None)
    try:
        value = float(observed)
    except (TypeError, ValueError):
        return BudgetEvaluation(key, "failed", float("nan"), None, None, "unknown", baseline, None, "observed value is not numeric")
    if not math.isfinite(value) or value < 0:
        return BudgetEvaluation(key, "failed", value, None, None, "unknown", baseline, None, "observed value is not finite and non-negative")
    if budget is None:
        return BudgetEvaluation(key, "unbudgeted", value, None, None, "unknown", baseline, None, "no versioned budget is declared")
    regression_pct = None if baseline is None or baseline <= 0 else round((value - baseline) / baseline * 100, 3)
    over_limit = value > budget.threshold
    over_baseline = baseline is not None and baseline > 0 and value > baseline * (1 + budget.tolerance_pct / 100)
    status = "failed" if over_limit or over_baseline else "passed"
    if over_limit:
        message = f"observed {value:.3f} {budget.unit} exceeds budget tolerance {budget.threshold:.3f} {budget.unit}"
    elif over_baseline:
        message = f"observed regression {regression_pct:.3f}% exceeds tolerance {budget.tolerance_pct:.3f}%"
    else:
        message = "within versioned budget and regression tolerance"
    return BudgetEvaluation(key, status, value, budget.limit, budget.threshold, budget.unit, baseline, regression_pct, message)


@contextmanager
def measure_performance(metric_id: str, *, store_path: Path | None = None) -> Iterator[None]:
    """Measure duration and peak Python allocations without network or secrets."""

    started = time.perf_counter()
    tracemalloc.start()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event_type": "performance",
            "metric_id": str(metric_id).strip().lower(),
            "duration_ms": round(duration_ms, 3),
            "peak_memory_mb": round(peak / 1024 / 1024, 3),
            "network_calls": False,
            "secrets_present": False,
        }
        destination = Path(store_path or Path("logs") / "timings.jsonl")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError:
            pass


def build_performance_report(
    root: Path,
    *,
    timing_path: Path | None = None,
    budgets_path: Path | None = None,
) -> dict[str, object]:
    root = Path(root).resolve()
    resolved_budgets_path = budgets_path or root / DEFAULT_BUDGETS_PATH
    if not resolved_budgets_path.is_absolute():
        resolved_budgets_path = root / resolved_budgets_path
    budgets = load_performance_budgets(resolved_budgets_path)
    records = read_timing_records(timing_path or root / "logs" / "timings.jsonl")
    budget_ids = {budget.metric_id for budget in budgets}
    by_metric: dict[str, list[float]] = {}
    peaks: list[float] = []
    for record in records:
        metric_id = str(record.get("metric_id") or record.get("step") or "").strip().lower()
        action_id = str(record.get("action_id") or "").strip().lower()
        if metric_id not in budget_ids and action_id in budget_ids:
            metric_id = action_id
        if not metric_id or "duration_ms" not in record:
            continue
        try:
            by_metric.setdefault(metric_id, []).append(float(record["duration_ms"]))
            if record.get("peak_memory_mb") is not None:
                peaks.append(float(record["peak_memory_mb"]))
        except (TypeError, ValueError):
            continue
    measurements: list[dict[str, object]] = []
    failures: list[str] = []
    for budget in budgets:
        if budget.metric_id == "local_storage":
            values = [float(_storage_bytes(root))]
        elif budget.metric_id == "app_peak_memory":
            values = peaks
        else:
            values = by_metric.get(budget.metric_id, [])
        if not values:
            measurements.append({"metric_id": budget.metric_id, "status": "unmeasured", "unit": budget.unit, "sample_count": 0, "limit": budget.limit})
            continue
        result = evaluate_budget(budget.metric_id, max(values), budgets=budgets)
        item = asdict(result) | {"sample_count": len(values), "observed_max": max(values), "observed_average": sum(values) / len(values)}
        measurements.append(item)
        if result.status == "failed":
            failures.append(budget.metric_id)
    storage_bytes = _storage_bytes(root)
    return {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "policy_path": str(resolved_budgets_path.as_posix()),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "failed" if failures else "passed" if any(item.get("status") == "passed" for item in measurements) else "unmeasured",
        "failures": sorted(set(failures)),
        "measurements": measurements,
        "timing_record_count": len(records),
        "cache_counts": {status: sum(1 for item in records if item.get("event_type") == "cache" and item.get("cache_status") == status) for status in ("hit", "miss", "invalidation")},
        "storage_bytes": storage_bytes,
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "cpu_count": os.cpu_count() or 1, "network_calls": False},
    }


def write_performance_report(report: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    lines = ["# Performance budget report", "", f"- Schema: `{report['schema_version']}`", f"- Status: `{report['status']}`", f"- Timing records: `{report['timing_record_count']}`", f"- Local storage: `{report['storage_bytes']}` bytes", "", "| Metric | Status | Observed | Limit | Unit | Samples |", "|---|---|---:|---:|---|---:|"]
    for item in report["measurements"]:
        lines.append(f"| `{item['metric_id']}` | `{item['status']}` | {item.get('observed_max', '-')} | {item.get('limit', '-')} | {item.get('unit', '-')} | {item.get('sample_count', 0)} |")
    failure_lines = [f"- {failure}" for failure in report["failures"]]
    lines.extend(["", "## Failures", "", *(failure_lines or ["- None"]), ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _storage_bytes(root: Path) -> int:
    total = 0
    for directory in (root / "data", root / "logs"):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
    return total


__all__ = [
    "DEFAULT_BUDGETS_PATH",
    "BudgetEvaluation",
    "PerformanceBudget",
    "PerformanceBudgetError",
    "build_performance_report",
    "evaluate_budget",
    "load_performance_budgets",
    "measure_performance",
    "write_performance_report",
]
