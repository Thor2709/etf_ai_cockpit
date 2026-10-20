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
    "embeds a clock-derived stamp and is normalised to score_<stamp>_<8hex>.json. "
    "The price digest in feature manifest filenames is normalised to _p<12hex>; dates and settings hashes are kept. "
    "Defaults chosen: structure-level "
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
        "data/derived/run_manifests/backtest__s5307f54f8af7.json",
    ):
        assert required in files, required
    manifest = section["files"]["data/derived/run_manifests/backtest__s5307f54f8af7.json"]
    assert ["dataset:prices", "dataset", "1.0.0"] in manifest["dataset_tuples"]
    assert section["forecast_file"]["present"] is True


def test_feature_manifest_price_digest_is_masked_without_hiding_schema_or_settings(tmp_path) -> None:
    import json

    from refactor_parity._capture import persisted_schema_section

    manifests = tmp_path / "data" / "derived" / "run_manifests"
    manifests.mkdir(parents=True)
    path = manifests / "features_2026-09-30_p50feb083c593__s2e451e324e57.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    original = persisted_schema_section(tmp_path)
    other = path.with_name("features_2026-09-30_pe25bce0c2421__s2e451e324e57.json")
    path.rename(other)
    assert persisted_schema_section(tmp_path) == original
    assert list(original["files"]) == ["data/derived/run_manifests/features_2026-09-30_p<12hex>__s2e451e324e57.json"]
    other.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    assert persisted_schema_section(tmp_path) != original
    other.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    other.rename(other.with_name("features_2026-09-30_pe25bce0c2421__s123456789abc.json"))
    assert persisted_schema_section(tmp_path) != original
