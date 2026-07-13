# Task 17 implementation report

## Task completed

Implemented the score-history, run-comparison and feature-driver contract across persistence, trust-artifact, Scores, What Changed and Instrument Detail consumers. The implementation keeps history informational, preserves legacy fields, and forces `execution_allowed=false`.

## Files and symbols examined

- `src/etf_cockpit/data/score_history.py`: `ScoreHistoryWriteResult`, `append_score_run`, `score_history_frame`, v2 payload migration helpers.
- `src/etf_cockpit/data/run_changes.py`: `RunChange`, `RunChangeReport`, `compare_runs`.
- `src/etf_cockpit/signals/feature_drivers.py`: `build_feature_drivers`.
- `src/etf_cockpit/data/trust_artifacts.py`: score/metric history and driver persistence wrappers, artifact schemas.
- `src/etf_cockpit/app/components/simple_scores.py`: score-history and component-driver panels.
- `src/etf_cockpit/app/pages/what_changed.py`: run comparison table.
- `src/etf_cockpit/app/selectors/instrument_detail.py`: Instrument Detail sections and driver inventory.
- `src/etf_cockpit/app/state.py`, audit export paths and existing focused tests were checked for consumers and authority boundaries.

## Findings or changes

- Added canonical score snapshot dimensions (rank, warnings, freshness, model/forecast availability, news inventory, backtest trust and portfolio risk) while retaining legacy action fields.
- Made score writes idempotent by run/snapshot hash; a changed hash replaces the complete run snapshot, and malformed rows are filtered by readers.
- Expanded `compare_runs` with a backwards-compatible DataFrame API and run-ID/local-store API, deterministic summaries, and all required change flags.
- Reworked feature-driver normalisation to emit the required schema, source/freshness classifications, low-authority/stale/partial flags and an explicit non-executable marker.
- Updated trust-artifact writers to persist the expanded schemas and use the canonical driver builder without changing scoring or action authority.
- Added Scores no-history, one-snapshot and multi-snapshot displays; What Changed now renders every comparison dimension and summary; Instrument Detail exposes driver inventories and classifications.
- Added regression tests for idempotency, replacement, malformed rows, all comparison dimensions, driver schema/classification and UI history states.

## Evidence

- RED: `python -m pytest tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py -q` — 5 expected failures covering missing dimensions/API/schema behaviour before implementation.
- GREEN: `python -m pytest tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py tests/test_trust_critical_artifacts.py::test_score_artifacts_write_history_components_and_drivers -q` — 15 passed.
- UI/integration: `python -m pytest tests/test_simple_scores.py -k score_history_panel -q` — 3 passed; `python -m pytest tests/test_instrument_detail.py -q` — 9 passed; trust-artifact integration — 1 passed.
- `python -m ruff check` on all edited source/tests — all checks passed.
- `python -m compileall -q src` — passed.
- `git diff --check` — passed.
- Synthetic What Changed render smoke test returned a Flet `Column` with two persisted runs.

## Commands or tests run

The commands above were run from the task worktree. The full `tests/test_trust_critical_artifacts.py` and unfiltered `tests/test_simple_scores.py` suites were also attempted.

## Remaining uncertainty and risk

- Those broad suites retain pre-existing fixture/environment failures because the local `data/raw/trade_candidates` fixture is absent (identity/universe assertions fail before this change). No edited-file failure was observed in the focused gates.
- Audit export already includes `score_history` and `feature_drivers`; no separate persisted run-change file was introduced because comparison is derived deterministically from the exported history.

## Recommended next action

Review the task branch's implementation commit from this worktree, then rerun the parent branch's full release matrix after restoring the missing candidate fixture.
