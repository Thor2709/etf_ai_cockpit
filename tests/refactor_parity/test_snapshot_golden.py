"""Golden: ``build_snapshot(force_sample=True)`` digest on the pinned sample pipeline."""

from __future__ import annotations

from refactor_parity._harness import assert_matches_golden

NOTES = (
    "Pinned clock: date.today()=2026-09-30, datetime.now()=2026-09-30T12:00Z (see tests/refactor_parity/_clock.py); "
    "sample prices end 2026-09-30 (900 business days, np.random.default_rng(42)). Private root without models/, offline. "
    "Recorded: CockpitSnapshot field names; per frame shape/columns/dtypes/numeric aggregates/first+last rows/exact digest "
    "of non-float columns; per-instrument price row counts; data report; every signal (action, score, components, "
    "blocked_by); model availability booleans; benchmark-reference scalars. Excluded: ingested_at column (pandas "
    "Timestamp.now cannot be frozen), dataset checksum/ingested_at, signal run_id, absolute paths, model messages and "
    "runtime_packages (depend on optional installs). All sha256 values are masked. Floats rel=1e-9/abs=1e-12; NaN is "
    "'<NaN>', missing is null. universe_revision is '' in a clean checkout (no universe store), so forecasts are "
    "fail-closed empty in the snapshot: pinned as is. Defaults chosen: sample rows 3, string-float rounding 6 places."
)


def test_snapshot_digest_matches_golden(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["snapshot"]  # type: ignore[index]
    assert_matches_golden("snapshot", section, notes=NOTES)


def test_snapshot_digest_is_not_vacuous(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["snapshot"]  # type: ignore[index]
    assert section["data_report"]["as_of_date"] == "2026-09-30"
    assert section["frames"]["prices"]["shape"][0] > 50_000
    assert section["signals"]["count"] == len(section["universe"]["enabled_ids"])
    assert section["model_status"]["baseline"] is True
    assert section["model_status"]["timesfm"] is False and section["model_status"]["toto"] is False
