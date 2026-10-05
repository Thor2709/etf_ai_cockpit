"""Capture subprocess: runs the sample pipeline once under a frozen clock and writes every pipeline golden section.

Usage (by ``_harness.run_capture`` only): ``python _capture.py <output.json> <now_offset_days>`` with
``ETF_COCKPIT_ROOT`` pointing at a private root.  Everything is recorded through ``jsonable``/``frame_golden``;
volatile values (timestamps, run ids derived from "now", ingestion times) are excluded and every digest is masked.

Pipeline (all public entry points, offline, ``execution_allowed`` stays false):

1. ``build_snapshot(force_sample=True)``           -> snapshot + fresh backtest sections
2. ``DataService.run_yfinance_forecasts``          -> persisted forecast CSV + sidecar (baseline ok, TimesFM/Toto unavailable)
3. ``build_snapshot()``                            -> second snapshot (cached backtest/features path)
4. ``AppState._write_current_scoreboard``          -> persisted scoreboard + trust artifacts
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import time
import warnings
from datetime import timedelta
from pathlib import Path

# Third-party packages are imported BEFORE the clock is frozen: their import-time machinery (ABC registration,
# C-level datetime use) must see the real classes.
import numpy  # noqa: F401
import pandas as pd
import pyarrow  # noqa: F401
import pyarrow.parquet as pq
import yaml  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from refactor_parity import _clock  # noqa: E402
from refactor_parity._serialise import compact_large_lists, frame_golden, jsonable, mask_digests  # noqa: E402

warnings.filterwarnings("ignore")

_VALUE_KEYS = {
    "schema_version",
    "manifest_version",
    "settings_schema_version",
    "settings_semantic_version",
    "execution_allowed",
    "immutable_after_run",
    "contract",
    "calculation_schema",
    "schema",
    "formula_version",
    "kind",
    "artifact_id",
    "version",
}
_VOLATILE_COLUMNS = ("ingested_at",)
# Score run manifests are named after the (clock-derived) run id: score_<YYYYMMDDTHHMMSS>_<8 hex>.json.
_SCORE_RUN_NAME = re.compile(r"score_\d{8}T\d{6}_[0-9a-f]{8}")
# The stamp comes from the frozen clock "now"; the 8-hex suffix is uuid.uuid4().hex[:8] (random per run).
_SCORE_RUN_MASK = "score_<stamp>_<8hex>"
# Fields never recorded by value in the persisted-schema golden (listed in the fixture for transparency).
EXCLUDED_FIELDS = {
    "digests": "every 64-hex sha256 value (payload_sha256, *_checksum, *_hash, content_hash, signatures) is masked: float text feeding them is not bit-stable across platforms",
    "timestamps": "ingested_at / created_at / signal_timestamp values and any run id derived from the clock",
    "paths": "absolute paths (isolated root differs per run)",
    "hashes_in_run_id": "the __s<12 hex> settings suffix of run ids is kept: it is derived from committed config only",
}


def _stage(name: str, started: float) -> None:
    print(f"[capture] {name}: {time.time() - started:.1f}s", file=sys.stderr, flush=True)


# --- sections ---------------------------------------------------------------------------------------


def _frame(frame: pd.DataFrame) -> dict[str, object]:
    return frame_golden(frame, exclude_columns=_VOLATILE_COLUMNS)


def _columnar(frame: pd.DataFrame) -> dict[str, object]:
    """Whole frame, column-major (one diff line per column), digests masked, missing values explicit."""

    return {str(column): mask_digests(jsonable(frame[column].tolist())) for column in frame.columns}


def snapshot_section(snapshot: object, forecasts_message: str) -> dict[str, object]:
    fields = [field.name for field in dataclasses.fields(type(snapshot))]  # type: ignore[arg-type]
    frames = {
        name: _frame(getattr(snapshot, name))
        for name in ("prices", "holdings", "features", "latest_features", "forecasts")
    }
    prices = snapshot.prices  # type: ignore[attr-defined]
    per_instrument = (
        prices.assign(date=pd.to_datetime(prices["date"]))
        .groupby("etf_id", sort=True)
        .agg(rows=("date", "size"), first_date=("date", "min"), last_date=("date", "max"), last_adjusted_close=("adjusted_close", "last"))
        .reset_index()
    )
    report = snapshot.data_report  # type: ignore[attr-defined]
    signals = snapshot.signals  # type: ignore[attr-defined]
    supporting_keys = sorted({key for signal in signals for key in signal.supporting_metrics})
    return {
        "snapshot_fields": fields,
        "frames": frames,
        "frame_excluded_columns_reason": "ingested_at is stamped with pandas Timestamp.now (real wall clock, cannot be frozen)",
        "price_rows_per_instrument": _columnar(per_instrument),
        "universe": {
            "enabled_ids": list(snapshot.config.universe.enabled_ids),  # type: ignore[attr-defined]
            "configured_enabled_ids": list(snapshot.config.universe.configured_enabled_ids),  # type: ignore[attr-defined]
            "universe_revision": snapshot.universe_revision,  # type: ignore[attr-defined]
        },
        "data_report": {
            "as_of_date": jsonable(report.as_of_date),
            "analysis_allowed": bool(report.analysis_allowed),
            "issues": jsonable([(issue.severity, issue.code) for issue in report.issues]),
            "dataset_metadata": [
                {
                    key: jsonable(value)
                    for key, value in vars(item).items()
                    if key not in {"ingested_at", "checksum"}
                }
                for item in report.dataset_metadata
            ],
            "dataset_metadata_excluded": ["ingested_at", "checksum"],
        },
        "signals": {
            "count": len(signals),
            "supporting_metric_keys": supporting_keys,
            "items": [
                {
                    "etf_id": signal.etf_id,
                    "signal_date": jsonable(signal.signal_date),
                    "action": signal.action,
                    "confidence": jsonable(signal.confidence),
                    "total_score": jsonable(signal.total_score),
                    "components": jsonable(signal.components),
                    "blocked_by": jsonable(signal.blocked_by),
                    "warnings": jsonable(signal.warnings),
                    "reason_short": signal.reason_short,
                    "horizon_primary": signal.horizon_primary,
                    "supporting_metrics": mask_digests(jsonable(signal.supporting_metrics)),
                }
                for signal in signals
            ],
            "excluded": ["run_id (derived from the clock)"],
        },
        "model_status": {
            key: value for key, value in snapshot.model_status.items() if key != "reasons"  # type: ignore[attr-defined]
        },
        "model_inventory": [
            {
                "model_name": item.model_name,
                "model_id": item.model_id,
                "present": item.present,
                "live_ready": item.live_ready,
                "status": item.status,
            }
            for item in snapshot.model_inventory  # type: ignore[attr-defined]
        ],
        "model_inventory_excluded": ["path (absolute)", "message and runtime_packages (depend on installed optional packages)"],
        "benchmark_reference": {
            name: mask_digests(jsonable(getattr(snapshot, name)))
            for name in (
                "benchmark_reference_instrument",
                "benchmark_reference_currency",
                "benchmark_reference_horizon_years",
                "benchmark_reference_start_date",
                "benchmark_reference_end_date",
                "benchmark_reference_decision_time",
                "benchmark_reference_portfolio_ids",
                "vwce_listing_id",
            )
        },
        "etf_economics_records": len(snapshot.etf_economics_records),  # type: ignore[attr-defined]
        "candidate_price_binding": jsonable(snapshot.candidate_price_binding is None),  # type: ignore[attr-defined]
        "forecast_run_message": re.sub(r"Output: .*$", "Output: <path>", forecasts_message),
    }


def _numeric_columns_equal(fresh: pd.DataFrame, cached: pd.DataFrame) -> bool:
    """Same columns/rows and every numeric column equal (rel 1e-9, abs 1e-12, NaN == NaN).

    The cached reload is read back from CSV, so object columns come back as strings/NaN (dates, '' vs NaN, None vs
    NaN) and ``DataFrame.equals`` is False at the base; the numeric values are what must survive the reload.
    """

    left, right = fresh.reset_index(drop=True), cached.reset_index(drop=True)
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return False
    for column in left.columns:
        if pd.api.types.is_numeric_dtype(left[column]) and not pd.api.types.is_bool_dtype(left[column]):
            if not numpy.allclose(
                pd.to_numeric(left[column], errors="coerce").to_numpy(dtype=float),
                pd.to_numeric(right[column], errors="coerce").to_numpy(dtype=float),
                rtol=1e-9,
                atol=1e-12,
                equal_nan=True,
            ):
                return False
    return True


def backtest_section(report: object, cached_report: object) -> dict[str, object]:
    results = report.results  # type: ignore[attr-defined]
    metadata = compact_large_lists(mask_digests(jsonable(report.metadata)))  # type: ignore[attr-defined]
    cached_results = cached_report.results  # type: ignore[attr-defined]
    return {
        "report_fields": [field.name for field in dataclasses.fields(report)],  # type: ignore[arg-type]
        "quality_label": report.quality_label,  # type: ignore[attr-defined]
        "ai_added_value": report.ai_added_value,  # type: ignore[attr-defined]
        "quality_notes": jsonable(report.quality_notes),  # type: ignore[attr-defined]
        "results_columns": [str(column) for column in results.columns],
        "results": _columnar(results),
        "equity_curves": _frame(report.equity_curves),  # type: ignore[attr-defined]
        "trade_log": _frame(report.trade_log),  # type: ignore[attr-defined]
        "signal_log": _frame(report.signal_log),  # type: ignore[attr-defined]
        "quality_momentum_evidence": _frame(report.quality_momentum_evidence),  # type: ignore[attr-defined]
        "metadata": metadata,
        "cached_reload": {
            "quality_label": cached_report.quality_label,  # type: ignore[attr-defined]
            "results_equal_to_fresh": bool(cached_results.reset_index(drop=True).equals(results.reset_index(drop=True))),
            "numeric_results_equal_to_fresh": _numeric_columns_equal(results, cached_results),
            "quality_notes": jsonable(cached_report.quality_notes),  # type: ignore[attr-defined]
        },
    }


_SCORE_OBJECT_FIELDS = (
    "instrument_key",
    "final_score_10",
    "rank",
    "score_rank",
    "final_action",
    "one_line_reason",
    "warnings",
    "strategy_templates",
    "model_versions_used",
    "forecast_status",
    "news_inventory",
    "internal_intent",
    "authority_decision",
    "canonical_score",
)
_COMPONENT_FIELDS = (
    "key",
    "score_10",
    "raw_score",
    "status",
    "authority",
    "score_role",
    "source_id",
    "source_authority",
    "as_of_date",
    "freshness_status",
    "evidence_quality",
    "score_eligible",
)


def score_objects_section(scores: list[object]) -> dict[str, object]:
    """Per-instrument values that exist on SimpleInstrumentScore but not in the scoreboard frame."""

    section: dict[str, object] = {"order": [score.display_id for score in scores]}  # type: ignore[attr-defined]
    for name in _SCORE_OBJECT_FIELDS:
        section[name] = [mask_digests(jsonable(getattr(score, name))) for score in scores]
    section["valid_component_count"] = [score.valid_component_count for score in scores]  # type: ignore[attr-defined]
    section["total_component_count"] = [score.total_component_count for score in scores]  # type: ignore[attr-defined]
    section["components"] = [
        [mask_digests({field: jsonable(getattr(component, field)) for field in _COMPONENT_FIELDS}) for component in score.components]  # type: ignore[attr-defined]
        for score in scores
    ]
    return section


def scoreboard_section(path: Path, state: object, scores: list[object]) -> dict[str, object]:
    from etf_cockpit.signals.simple_scores import load_simple_scoreboard

    frame = pd.read_parquet(path)
    loaded = load_simple_scoreboard(path)
    return {
        "score_objects": score_objects_section(scores),
        "score_history_warning": getattr(state, "score_history_warning", None),
        "shape": [int(frame.shape[0]), int(frame.shape[1])],
        "columns": [str(column) for column in frame.columns],
        "dtypes": {str(column): str(dtype) for column, dtype in frame.dtypes.items()},
        "order": [str(value) for value in frame["instrument_id"].tolist()],
        "columns_by_name": _columnar(frame),
        "canonical_projection": {
            "shape": [int(loaded.shape[0]), int(loaded.shape[1])],
            "columns": [str(column) for column in loaded.columns],
            "order": [str(value) for value in loaded["instrument_id"].tolist()],
        },
    }


def _shape(value: object, depth: int = 0) -> object:
    if isinstance(value, dict):
        return {
            key: (mask_digests(jsonable(item)) if key in _VALUE_KEYS and not isinstance(item, (dict, list)) else _shape(item, depth + 1))
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return {"list_length": len(value), "item": _shape(value[0], depth + 1) if value else None}
    if value is None:
        return "null"
    return type(value).__name__


def _describe_file(path: Path) -> dict[str, object]:
    name = path.name
    if name.endswith(".parquet"):
        parquet = pq.ParquetFile(path)
        return {
            "kind": "parquet",
            "rows": parquet.metadata.num_rows,
            "schema": [[field.name, str(field.type)] for field in parquet.schema_arrow],
        }
    if name.endswith(".csv"):
        header = pd.read_csv(path, nrows=0)
        rows = sum(len(chunk) for chunk in pd.read_csv(path, usecols=[0], chunksize=50_000))
        return {"kind": "csv", "rows": rows, "columns": [str(column) for column in header.columns]}
    if name.endswith(".json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        description: dict[str, object] = {"kind": "json", "structure": _shape(payload)}
        if "dependencies" in payload and isinstance(payload, dict):
            description["dataset_tuples"] = [
                [item.get("artifact_id"), item.get("kind"), item.get("version")] for item in payload["dependencies"]
            ]
            description["run_id_pattern"] = _SCORE_RUN_NAME.sub(_SCORE_RUN_MASK, re.sub(r"[0-9a-f]{12}", "<12hex>", str(payload.get("run_id", ""))))
        return description
    return {"kind": "other"}


def persisted_schema_section(root: Path) -> dict[str, object]:
    data = root / "data"
    files: dict[str, object] = {}
    for path in sorted(data.rglob("*")):
        if not path.is_file() or path.name == ".atomic-write-group.guard" or ".schema_versions" in path.parts:
            continue
        relative = _SCORE_RUN_NAME.sub(_SCORE_RUN_MASK, path.relative_to(root).as_posix())
        files[relative] = _describe_file(path)
    return {"excluded_fields": EXCLUDED_FIELDS, "files": files}


def forecast_section(root: Path) -> dict[str, object]:
    forecasts = sorted((root / "data" / "forecasts").glob("forecast_results_*.csv"))
    if not forecasts:
        return {"present": False}
    frame = pd.read_csv(forecasts[-1])
    summary = (
        frame.groupby(["model_name", "status"], sort=True)
        .agg(rows=("etf_id", "size"), instruments=("etf_id", "nunique"), horizons=("horizon_days", lambda s: sorted(set(int(v) for v in s))))
        .reset_index()
    )
    return {
        "present": True,
        "file": forecasts[-1].name,
        "frame": _frame(frame),
        "by_model_status": _columnar(summary),
    }


# --- driver -----------------------------------------------------------------------------------------


def main(output: Path, now_offset_days: int) -> None:
    started = time.time()
    shifted_now = _clock.PINNED_NOW + timedelta(days=now_offset_days, hours=7 if now_offset_days else 0)
    _clock.install(now=shifted_now)
    root = Path(os.environ["ETF_COCKPIT_ROOT"])

    from etf_cockpit.app.state import AppState
    try:  # pre-refactor location (public facade)
        from etf_cockpit.services import DataService, build_snapshot
    except ModuleNotFoundError:  # refactor head: the services shim was removed, same objects live in application/
        from etf_cockpit.application.data_service import DataService
        from etf_cockpit.application.snapshot_builder import build_snapshot

    first = build_snapshot(force_sample=True)
    _stage("build_snapshot(force_sample=True)", started)
    message = DataService(first.config).run_yfinance_forecasts(include_candidates=False, use_cache=False)
    _stage("run_yfinance_forecasts", started)
    second = build_snapshot()
    _stage("build_snapshot() cached", started)
    import importlib

    written: dict[str, list[object]] = {}
    original_write = importlib.import_module("etf_cockpit.signals.simple_scores").write_simple_scoreboard

    def spy(scores: list[object], path: Path | None = None) -> Path:  # observes the exact objects AppState scored
        written["scores"] = list(scores)
        return original_write(scores, path)  # type: ignore[arg-type]

    # The module that calls write_simple_scoreboard holds its own binding: app.state before the refactor,
    # application.scoreboard_publication after it.  Patch every candidate that has the name; at least one must.
    patched = 0
    for module_name in ("etf_cockpit.app.state", "etf_cockpit.application.scoreboard_publication"):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        if getattr(module, "write_simple_scoreboard", None) is original_write:
            module.write_simple_scoreboard = spy  # type: ignore[attr-defined]
            patched += 1
    if not patched:
        raise RuntimeError("no module binds write_simple_scoreboard: cannot observe the scored objects")
    state = AppState(snapshot=second, selected_etf=second.config.ui.default_etf)
    scoreboard_path = state._write_current_scoreboard()
    _stage("write scoreboard", started)

    sections = {
        "snapshot": snapshot_section(first, message),
        "backtest": backtest_section(first.backtest, second.backtest),
        "scoreboard": scoreboard_section(scoreboard_path, state, written["scores"]),
        "persisted_schema": {**persisted_schema_section(root), "forecast_file": forecast_section(root)},
    }
    clock_reads = {key: int(value) for key, value in sorted(_clock.READS.items())}
    payload = {"sections": sections, "clock": {"today": _clock.PINNED_TODAY.isoformat(), "now": shifted_now.isoformat(), "reads": clock_reads}}
    output.write_text(json.dumps(payload, allow_nan=False, ensure_ascii=False), encoding="utf-8")
    _stage("done", started)


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]))
