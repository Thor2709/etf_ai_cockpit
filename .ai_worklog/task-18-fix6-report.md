# Task 18 fix6 report

## Task completed

Corrected crowding warning-state semantics at exact head `6547208`. Explicit
non-warning states (`no_cluster_warning`, `no_theme_concentration_warning`,
empty/N/A and unavailable/partial coverage states) no longer count or render
as amber warnings. Risk now counts distinct warning `cluster_id` values rather
than instrument rows. Actual `high_correlation_cluster_warning` and
`theme_concentration_warning` states remain amber, and the existing
`execution_allowed=false` boundary is unchanged.

## Files and symbols examined

- `src/etf_cockpit/app/pages/risk.py`: `_crowding_attribution_panel`.
- `src/etf_cockpit/app/components/simple_scores.py`: `_score_tile` and the
  shared `_is_crowding_warning_state` predicate.
- `tests/test_task18_ui.py`: Flet control traversal and crowding regressions.
- `src/etf_cockpit/features/crowding.py`: persisted crowding state vocabulary.
- `.ai_worklog/task-18-fix5-report.md` and `.ai_worklog/task-18-brief.md`:
  required Task 18 validation bundle and scope.

## Findings or changes

- Replaced substring matching with `_is_crowding_warning_state`, which rejects
  `no_` states, empty/N/A, pending, partial and `_unavailable` states while
  retaining explicit warning states.
- Risk filters with the shared predicate and counts non-empty distinct warning
  cluster IDs; without IDs, no warning-cluster count is inferred.
- Added regressions for duplicate warning rows, both explicit non-warning
  states and Scores chip colours for actual warning states.
- Edited only the two UI source files, `tests/test_task18_ui.py` and this
  report. Four pre-existing `data/.schema_versions/*.json` edits remain local
  generated noise and were not edited or staged.

## Evidence

### RED

`python -m pytest -q tests/test_task18_ui.py -k "crowding_counts_distinct or scores_crowding_no_cluster"`
failed as intended (`2 failed`): Risk rendered row-level substring matches and
Scores coloured `no_cluster_warning` amber (`#f6b44b` instead of cyan
`#67e8f9`).

### GREEN

`python -m pytest tests/test_task18_integration.py tests/test_crowding.py
tests/test_benchmark_attribution.py tests/test_friction_edge.py
tests/test_evidence_derivatives.py tests/test_signal_gates.py
tests/test_instrument_detail.py tests/test_risk_analytics.py
tests/test_task18_ui.py -q --tb=short` passed (`53 passed`).

`python -m pytest tests/test_task18_ui.py -q --tb=short` passed (`7 passed`).

## Commands or tests run

- Task 18 focused bundle above: `53 passed`.
- UI regression slice:
  `python -m pytest tests/test_task18_ui.py tests/test_simple_scores.py
  tests/test_instrument_detail.py tests/test_risk_analytics.py -q --tb=short`:
  `58 passed, 6 failed`. The six failures are the known missing candidate /
  two-tier / identity fixture failures in `tests/test_simple_scores.py` (no
  `trade_candidates` CSV, missing secondary rows and `AURG`); they pre-date
  this fix and are unrelated to crowding.
- Scoped Ruff:
  `python -m ruff check src/etf_cockpit/app/pages/risk.py
  src/etf_cockpit/app/components/simple_scores.py tests/test_task18_ui.py
  --no-cache`: passed (`All checks passed!`).
- Compilation: `python -m compileall -q src tests`: passed.
- `git diff --check`: passed; Git emitted only normal LF/CRLF conversion
  notices, including the four pre-existing generated schema files.

## Remaining uncertainty and risk

- The broader UI slice retains six known fixture/data-state failures; the
  authoritative Task 18 bundle and changed-file tests are green.
- Full release/package/browser validation was not run; it is outside this
  bounded fix.
- Four generated schema-version files were intentionally left untouched and
  must remain excluded from the commit.

## Recommended next action

Review and integrate commit `fix: correct crowding warning state semantics`.
