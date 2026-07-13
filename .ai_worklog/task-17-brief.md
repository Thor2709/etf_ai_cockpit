# Wave 4 Task 17 - Score History, Run Comparison and Feature Drivers

Owning issues: `ISSUE-0067`, `ISSUE-0034`, `ISSUE-0047`.

## Required interfaces

- `append_score_run(scores, run_id, created_at) -> ScoreHistoryWriteResult`
  must append an idempotent snapshot keyed by run ID and snapshot hash.
- `compare_runs(current_run_id, previous_run_id) -> RunChangeReport` must
  compare score/rank, warnings, freshness, model availability, forecasts,
  news inventory, backtest trust and portfolio risk with deterministic
  plain-English summaries.
- `build_feature_drivers(scores, ledger) -> pandas.DataFrame` must emit
  `instrument`, `component`, `raw_metric`, `normalised_score`, `direction`,
  `authority`, `driver_text`, `source_dataset`, `as_of_date` and
  `freshness_status`.

## Observable acceptance

1. Every completed score-generation run appends snapshots for configured ETFs
   and candidate stocks without destroying earlier history.
2. Duplicate run writes are idempotent or deterministically replaced; malformed
   rows do not crash readers.
3. Metric/component history is persisted with its required fields and remains
   informational; history and driver text cannot alter current action labels.
4. Expanded Scores rows show no-history, one-snapshot and multi-snapshot states,
   including compact score evolution, latest/previous/delta and explanation.
5. Run comparison exposes every required change dimension and deterministic
   summary text in What Changed and the Dashboard digest where applicable.
6. Feature drivers classify and expose top positive, top negative, missing/N/A,
   low-authority and stale/partial drivers in Scores and Instrument Detail.
7. Audit/export includes score history, run changes or a truthful summary.
8. Preserve existing trust, revision, atomic persistence, provider/evidence and
   authority boundaries. `execution_allowed` remains `false`; no score weights,
   model authority, portfolio targets, research thresholds or coverage scope
   may change.

## Owned files

Implement in the existing architecture, extending rather than replacing:

- `src/etf_cockpit/data/score_history.py`
- `src/etf_cockpit/data/run_changes.py`
- `src/etf_cockpit/signals/feature_drivers.py`
- `src/etf_cockpit/data/trust_artifacts.py`
- `src/etf_cockpit/app/components/simple_scores.py`
- `src/etf_cockpit/app/pages/what_changed.py`
- relevant Dashboard/Instrument Detail/feature-registry/acceptance metadata
- `tests/test_score_history.py`, `tests/test_run_changes.py`,
  `tests/test_feature_drivers.py` and focused UI/integration tests

## Required workflow

Use RED-GREEN-REFACTOR. Add genuine failing tests before behavioural code,
record exact command/output, implement the smallest compatible change, run
focused and affected regressions, Ruff, compileall and diff checks, then write
`.ai_worklog/task-17-report.md` and commit. Do not edit closure ledgers or
issue state; the parent handles integration and closure-pending records.

## Explicit non-goals

No execution, broker integration, credential storage, autonomous portfolio
management, new scoring authority, product redesign or unrelated refactor.
