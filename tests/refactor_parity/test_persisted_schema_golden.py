"""Golden: persisted-artifact schemas (forecast, backtest, features, scoreboard/trust artifacts, run manifests)."""

from __future__ import annotations

from refactor_parity._harness import assert_matches_golden

NOTES = (
    "Every file the pinned pipeline persists under data/ (excluding atomic-write guards and the tracked "
    ".schema_versions): CSV -> header columns + row count; parquet -> arrow schema + row count; JSON -> key structure "
    "(types, list lengths) with the values of schema/version/contract/execution_allowed keys; run manifests -> "
    "(artifact_id, kind, version) dependency tuples and run-id pattern; plus the forecast CSV frame digest and the "
    "per-model/status counts (baseline ok; TimesFM and Toto unavailable because no weights exist). Excluded fields are "
    "listed under excluded_fields (digests masked, timestamps, absolute paths). The score run manifest file name "
    "embeds a clock-derived stamp and is normalised to score_<stamp>_<8hex>.json. Defaults chosen: structure-level "
    "(not value-level) comparison for JSON sidecars and manifests."
)


def test_persisted_schemas_match_golden(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["persisted_schema"]  # type: ignore[index]
    assert_matches_golden("persisted_schema", section, notes=NOTES)


def test_persisted_schema_golden_covers_the_required_families(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["persisted_schema"]  # type: ignore[index]
    files = set(section["files"])
    for required in (
        "data/forecasts/forecast_results_yfinance_20260930.csv",
        "data/forecasts/forecast_results_yfinance_20260930.csv.meta.json",
        "data/backtests/backtest_results.csv",
        "data/backtests/backtest_results.csv.meta.json",
        "data/backtests/backtest_metadata.json",
        "data/backtests/signal_log.csv",
        "data/features/features_daily.parquet",
        "data/features/features_daily.parquet.meta.json",
        "data/derived/scoreboard.parquet",
        "data/derived/run_manifests/backtest__s54eb00f2a924.json",
    ):
        assert required in files, required
    manifest = section["files"]["data/derived/run_manifests/backtest__s54eb00f2a924.json"]
    assert ["dataset:prices", "dataset", "1.0.0"] in manifest["dataset_tuples"]
    assert section["forecast_file"]["present"] is True
