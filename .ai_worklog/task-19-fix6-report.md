# Task 19 fix 6 - malformed score and friction metadata

## Task completed

Closed the latest Task 19 Instrument Detail review findings without changing
score authority or enabling execution:

- Friction cost scenarios now accept only non-empty scalar text. List, dict,
  array, null and other malformed values become `cost_stress_scenario=
  unavailable`; numeric friction evidence with an invalid scenario is marked
  `manual_review`, while fully missing numeric evidence remains `unavailable`.
- Score labels, reasons and freshness are scalar-safe. Numeric score evidence
  cannot produce `status=available` when required metadata is null or
  malformed; such records remain `manual_review` with explicit fallbacks.
- The UI acceptance control now honestly says `Export audit evidence`; its
  existing `export_instrument_evidence` callback and Task 19 test contract are
  unchanged and coherent.
- `execution_allowed` remains `False` for both panels.

## Files and symbols examined

- `src/etf_cockpit/app/selectors/instrument_detail.py`: `_safe_text`,
  `_friction_panel` and `_score_panel`.
- `tests/test_task19_instrument_detail.py`: malformed scenario and nullable
  score metadata regressions.
- `configs/ui_acceptance.yaml`: `instrument-detail.export-evidence` contract.
- `src/etf_cockpit/app/pages/instrument_detail.py`: export button callback and
  status wording.

## Findings or changes

- Added scalar-safe text normalisation that never evaluates list/dict/array
  values in a boolean context.
- Added parameterised regressions for list-, dict-, NumPy-array- and numeric
  `cost_stress_scenario` values.
- Added a numeric-evidence score regression covering null label/reason and
  malformed label/reason/freshness values.
- Updated only the acceptance contract label; callback, key, success signal,
  controlled error signal and acceptance test remain unchanged.

## Evidence

RED:

- `python -m pytest tests/test_task19_instrument_detail.py::test_friction_panel_malformed_scenarios_fail_closed_without_crashing tests/test_task19_instrument_detail.py::test_score_panel_numeric_evidence_with_malformed_required_metadata_fails_closed -q --tb=short`
  failed as expected: malformed scenarios were stringified and numeric score
  evidence remained `available` despite malformed required metadata.

GREEN:

- The same focused command passed (5 parameterised friction cases plus score
  metadata regression).
- `python -m pytest tests/test_task19_instrument_detail.py -q --tb=short` -
  32 passed.
- `python -m pytest tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_task18_ui.py -q --tb=short` -
  53 passed.
- `python -m pytest tests/test_button_contracts.py -q --tb=short` - 3 passed.
- `python -m ruff check src/etf_cockpit/app/selectors/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src tests/test_task19_instrument_detail.py` - passed.
- `git diff --check` - passed; Git emitted only expected LF/CRLF conversion
  warnings.

## Commands or tests run

The exact RED/GREEN focused checks, affected Task 18/19 regressions, UI
acceptance inventory, Ruff, compileall and diff checks listed above were run in
`etf_ai_cockpit/.worktrees/task19-instrument-detail`.

## Remaining uncertainty and risk

- Full release/package/browser, keyboard/focus/responsive, audit/export and
  clean-first-run closure evidence remain parent-owned and were not run.
- The existing export service remains portfolio-wide by design; the label now
  avoids implying instrument-only archive scope.
- The untracked parent-owned `.ai_worklog/task-19-brief.md` was not edited or
  staged.

## Recommended next action

Review this commit, then run the parent-owned release/package/browser and
clean-first-run closure gates before integration.
