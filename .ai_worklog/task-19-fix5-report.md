# Task 19 fix 5 - final review findings

## Task completed

Closed the final Task 19 Instrument Detail review findings without changing
score authority, adding an export service, or enabling execution:

- The legacy `/etf` compatibility route now builds the canonical
  `instrument_detail_page`; the direct legacy `etf_detail_page` function remains
  available to existing callers and tests.
- The existing portfolio-wide `AppState.export_audit_packet` service remains
  the implementation behind the control, but the Instrument Detail button and
  status now say `Export audit evidence`/`Exported audit evidence` honestly.
- Nullable news provenance, score labels/reasons/freshness and signal-derived
  fields, and backtest trust quality now use scalar-safe helpers and fail
  closed to `unavailable` or `manual_review` rather than evaluating
  `pd.NA` as a boolean. `execution_allowed` remains `False`.

## Files and symbols examined

- `src/etf_cockpit/app/router.py`: `PAGES` compatibility mapping.
- `src/etf_cockpit/app/pages/instrument_detail.py`: export button and status
  callback.
- `src/etf_cockpit/app/selectors/instrument_detail.py`:
  `_safe_sequence`, `_news_item_record`, `_score_panel`, `_backtest_panel` and
  existing `_safe_bool`/`_value_or` helpers.
- `tests/test_task19_instrument_detail.py`: route, export wording and nullable
  evidence contracts.

## Findings or changes

- Replaced the `/etf` builder from `etf_detail_page` with
  `instrument_detail_page` while retaining the route title and canonical
  `/instrument/<id>` navigation.
- Renamed only the Instrument Detail export label/status copy; no new
  instrument-only archive or Task 20 service was introduced.
- Added `_safe_sequence` and replaced nullable `or`/`bool` expressions in the
  news, score and backtest selectors with `_first_value`, `_value_or` and
  `_safe_bool`. Unknown score evidence is marked `manual_review`; unknown
  backtest trust is `unavailable`/`manual_review`.

## Evidence

RED:

- `python -m pytest tests/test_task19_instrument_detail.py -q --tb=short`
  initially failed 5 tests: legacy `/etf` builder assertion, export wording,
  and the three nullable news/score/backtest probes. Failures were the expected
  route mismatch, stale text and `TypeError: boolean value of NA is ambiguous`.

GREEN:

- `python -m pytest tests/test_task19_instrument_detail.py -q --tb=short` -
  27 passed.
- `python -m pytest tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_task18_ui.py -q --tb=short` -
  48 passed.
- `python -m ruff check src/etf_cockpit/app/router.py src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src tests/test_task19_instrument_detail.py` - passed.
- `git diff --check` - passed; only expected LF/CRLF conversion warnings were
  emitted.

## Commands or tests run

The exact RED command, focused GREEN command, affected Task 18/19 regression
command, Ruff, compileall and diff checks listed above were run in
`etf_ai_cockpit/.worktrees/task19-instrument-detail`.

## Remaining uncertainty and risk

- Full release/package/browser, keyboard/focus/responsive, audit/export
  end-to-end and clean-first-run evidence remain closure-pending per the Task
  19 brief.
- The export control still produces the repository's portfolio-wide audit
  packet by design; its copy no longer claims that the packet is instrument
  scoped.
- The untracked parent-owned `.ai_worklog/task-19-brief.md` was not edited or
  staged.

## Recommended next action

Obtain the fresh independent review requested by the Task 19 brief, then let
the parent run the release/package/browser and clean-first-run closure gates
before integration.
