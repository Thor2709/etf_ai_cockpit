# Wave 5 Task 23 bounded verification-fix report

Date: 2026-07-14
Branch: `wave5/task23-working`
Worktree: `etf_ai_cockpit/.worktrees/TASK22-RECONCILIATION`
Base: `ff75414` (local Task 22 reconciliation checkpoint)

## Scope

This checkpoint addresses verified defects exposed while completing the Task 22
full-suite and Task 23 closure preparation: detached Flet controls in headless
table filtering, nullable identity values in contradictory-identifier checks,
and pandas Arrow-backed fixture assignment for malformed metadata cases. No
product scope, authority, scoring, execution or DATA-05 coverage was changed.

## RED evidence

Command:

```text
PYTHONPATH=src; cached-python -m pytest tests/test_accessible_tables.py::test_accessible_table_search_treats_regex_punctuation_literally_and_updates tests/test_task19_instrument_detail.py::test_instrument_rows_reject_foreign_and_contradictory_supported_ids_with_nullable_values tests/test_task19_instrument_detail.py::test_friction_panel_malformed_scenarios_fail_closed_without_crashing tests/test_task19_instrument_detail.py::test_parsed_panel_malformed_freshness_metadata_fails_closed -q --tb=short
```

Observed exit code: `1`. The detached Flet update raised `Control must be
added to the page first`; nullable identity rows were incorrectly filtered;
malformed scenario/freshness cases either produced an available/high result or
failed during Arrow string assignment.

The independent-review regression was then run before its implementation fix:

```text
cached-python -m pytest tests/test_accessible_tables.py::test_accessible_table_does_not_mask_unrelated_runtime_errors -q --tb=short
```

Observed exit code: `1` with `Failed: DID NOT RAISE RuntimeError`, proving that
the broad detached-control substring suppressed an unrelated persistence error.

## GREEN evidence

Applied the smallest changes:

- suppress only the exact Flet detached-control phrase `control must be added
  to the page first` in table and status updates;
- treat pandas missing scalars as absent when evaluating contradictory
  instrument identifiers;
- keep malformed scenario and freshness fixture columns as object dtype before
  injecting list/array/non-string values.

Focused verification:

```text
cached-python -m pytest tests/test_accessible_tables.py tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_instrument_identity.py -q --tb=short
```

Result: exit code `0` (all collected tests passed).

Additional checks:

```text
cached-python -m compileall -q src tests
system-git diff --check
```

Both passed. The fresh full suite after the first Task 23 fixes completed with
one failure only: the known long-worktree Windows `WinError 3` ambiguous-news
atomic replacement test. The same test passes in the short-path Task 22
worktree; no Task 23-specific failure remains.

## Review state

The first fresh independent reviewer rejected the broad RuntimeError filter as
Important and required propagation regressions. That finding was reproduced by
the RED test above and fixed. A fresh re-review is in progress. No commit,
issue transition, package claim or closure claim is made until re-review and
remaining Task 23 gates pass.

`execution_allowed` remains `false`.
