"""Golden: BacktestService output (via build_snapshot) on the pinned sample pipeline."""

from __future__ import annotations

from refactor_parity._harness import assert_matches_golden

NOTES = (
    "BacktestReport produced by BacktestService.load_or_run_backtest inside build_snapshot(force_sample=True) on the "
    "pinned sample (end 2026-09-30). Recorded: report field names, quality label/notes, the full results table "
    "(summary metrics for all 7 strategies, column-major, incl. column order), digests of equity_curves / trade_log / "
    "signal_log / quality_momentum_evidence (shape, columns, dtypes, numeric sum/mean/min/max, first+last 3 rows, exact "
    "hash of the non-float columns with decimals inside text rounded to 6 places), and the metadata (lists longer than "
    "50 items are replaced by length + 32-hex content digest + first/last item; the digest covers a canonical form in "
    "which floats with |x| < 1e-12 are 0.0 and others keep 8 significant digits, so it is platform-stable, and lists "
    "of dicts also carry a 16-hex digest per field name). Also pinned: the cached reload (the "
    "second snapshot) returns the same results table. sha256 values are masked; floats rel=1e-9/abs=1e-12. "
    "Defaults chosen: 3 sample rows, 6-place text rounding, list compaction limit 50."
)


def test_backtest_matches_golden(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["backtest"]  # type: ignore[index]
    assert_matches_golden("backtest", section, notes=NOTES)


def test_backtest_golden_is_not_vacuous(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["backtest"]  # type: ignore[index]
    results = section["results"]
    assert len(results["strategy_name"]) == 7
    assert "buy_and_hold" in results["strategy_name"] and "signal_strategy" in results["strategy_name"]
    assert section["signal_log"]["shape"][0] > 1000
    assert section["trade_log"]["shape"][0] > 0
    # Exact DataFrame.equals is False at the base (CSV reload turns dates/None/'' into str/NaN); numeric columns must match.
    assert section["cached_reload"]["numeric_results_equal_to_fresh"] is True
    assert set(results["execution_allowed"]) == {False}
