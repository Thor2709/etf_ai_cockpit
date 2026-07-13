# Task 19 fix 3 - general instrument identity and parsed disclosure safety

## Task completed

Closed the latest Task 19 review findings for general instrument-linked panels
and parsed KID/methodology evidence. General row scoping now requires every
populated supported identifier to match the selected instrument, while
foreign-only and idless rows are ignored safely. Parsed disclosure rows use the
same contradiction-aware scoping and nullable parser flags fail closed to
manual review with score eligibility disabled. `execution_allowed` remains
false.

## Files and symbols examined

- `src/etf_cockpit/app/selectors/instrument_detail.py`: `_instrument_rows`,
  `_parsed_panel`, `_safe_bool` and all forecast/backtest/history/journal,
  price, feature and scoreboard callers.
- `tests/test_task19_instrument_detail.py`: new contradiction, nullable flag,
  and parsed disclosure regressions.
- `AGENTS.md`, `.ai_worklog/task-19-brief.md`, and prior Task 19 reports for
  ownership and closure boundaries. No ledgers or closure files were edited;
  the parent brief remains untracked.

## Findings or changes

- Replaced OR-matching in `_instrument_rows` with row-wise identity validation:
  at least one supported ID must match, no populated supported ID may disagree,
  and duplicate/nullable identifier frames fail closed without exceptions.
  Single recognised `instrument_id` or `etf_id` rows remain compatible.
- Routed `_parsed_panel` through the guarded row helper so contradictory KID or
  methodology IDs cannot be selected as evidence.
- Replaced nullable-unsafe `bool()` calls with `_safe_bool` defaults. Missing or
  nullable success/manual-review flags, blocked/unknown freshness, or any
  malformed parsed state produce `manual_review`; `score_eligible` is false
  unless the record is fully available.
- Added RED regressions covering contradictory/foreign/nullable general rows,
  nullable KID and methodology flags, and contradictory parsed IDs.

## Evidence

RED (before implementation):

- `python -m pytest tests/test_task19_instrument_detail.py -q`
- Result: exit 1 with one contradictory general row admitted, two
  `TypeError: boolean value of NA is ambiguous` failures, and one contradictory
  parsed row incorrectly marked `available`.
- `python -m pytest tests/test_task19_instrument_detail.py::test_derived_panels_reject_contradictory_supported_ids -q`
- Result: exit 1 before the derived-path changes; the feature-driver panel
  incorrectly returned `available` for a contradictory row.

GREEN and affected checks:

- `python -m pytest tests/test_task19_instrument_detail.py -q` - 17 passed.
- `python -m pytest tests/test_instrument_detail.py tests/test_task19_instrument_detail.py -q` - 29 passed.
- `python -m ruff check src/etf_cockpit/app/selectors/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src` - passed.
- `git diff --check` - passed (only Git's LF/CRLF conversion warnings).

## Commands or tests run

The focused RED/GREEN commands, affected instrument-detail regression suite,
Ruff, compileall, and diff check listed above were run in the Task 19 worktree.

## Remaining uncertainty and risk

- Full release/package/browser, keyboard/focus/responsive, audit/export and
  clean-first-run closure gates remain parent-owned and were not run here.
- The guard treats unsupported identifier columns as out of scope unless the
  caller explicitly includes them; existing callers' supported column lists
  were preserved. Duplicate-column frames are ignored fail closed.

## Recommended next action

Commit this focused fix and report the hash to the parent, then obtain fresh
Task 19 independent review and complete the parent-owned closure gates.
