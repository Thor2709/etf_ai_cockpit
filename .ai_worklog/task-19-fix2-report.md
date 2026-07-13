# Task 19 fix 2 - disclosure identity and nullable holdings review

## Task completed

Closed the fresh Task 19 re-review findings for ETF disclosure identity and
holdings metadata. Disclosure registry and holdings rows now fail closed when
supported `instrument_id`/`etf_id` values contradict the selected instrument,
while blank/null aliases remain safe when another supported ID is valid.
Nullable or malformed holdings dates and metadata no longer raise ambiguous
boolean errors; invalid `as_of` evidence is surfaced as manual review and
unavailable metadata uses explicit fallbacks. `execution_allowed` remains
false.

## Files and symbols examined

- `src/etf_cockpit/app/selectors/instrument_detail.py`: `_etf_disclosure_panel`,
  identifier scoping and holdings summary normalisation helpers.
- `tests/test_task19_instrument_detail.py`: contradictory-ID and nullable
  holdings regression tests.
- `AGENTS.md`, `.ai_worklog/task-19-brief.md`, and `task-19-fix1-report.md` for
  ownership and closure boundaries. No ledgers or closure files were edited.

## Findings or changes

- Added shared canonical-ID scoping for disclosure registry and holdings rows.
  A row with `instrument_id=VWCE` and `etf_id=OTHER`, duplicate ID columns, or
  no populated supported ID is rejected as `manual_review`; foreign-only rows
  remain out of scope for the selected instrument.
- Replaced nullable-unsafe metadata fallbacks with scalar/date-safe helpers.
  Holdings dates are selected from `as_of` then `as_of_date`, parsed with
  mixed-format UTC handling, and malformed/missing dates produce a manual
  review state with no rows exposed as authoritative.
- Normalised nullable document and holdings metadata to explicit unavailable
  values and safe booleans/numbers.

## Evidence

RED (before implementation):

- `python -m pytest -q tests/test_task19_instrument_detail.py::test_etf_disclosures_reject_contradictory_supported_ids tests/test_task19_instrument_detail.py::test_etf_disclosures_nullable_holdings_metadata_fail_closed --disable-warnings --maxfail=2`
- Result: exit 1. Contradictory IDs incorrectly returned `available`; nullable
  holdings raised `TypeError: boolean value of NA is ambiguous`.

GREEN:

- The same two tests passed after the fix.
- `python -m pytest -q tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_task18_ui.py --disable-warnings --maxfail=5` - 33 passed.
- `python -m ruff check src/etf_cockpit/app/selectors/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src tests/test_task19_instrument_detail.py` - passed.
- `git diff --check` - passed (only Git's LF/CRLF conversion warnings).

## Commands or tests run

The focused RED/GREEN commands, affected regression suite, Ruff, compileall,
and diff check listed above were run in the Task 19 worktree using the project
virtual environment.

## Remaining uncertainty and risk

- Full release/package/browser, keyboard/focus/responsive, audit/export and
  clean-first-run closure gates remain parent-owned and were not run here.
- Mixed-source frames containing foreign-only rows are ignored for the selected
  instrument; rows that directly conflict or have no usable canonical ID fail
  closed. This preserves multi-instrument stores while preventing ambiguous
  selected rows from being used.

## Recommended next action

Commit this focused fix and report hash to the parent, then obtain fresh Task
19 independent review and complete the parent-owned closure gates.
