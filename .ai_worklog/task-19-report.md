# Wave 5 Task 19 implementation report

## Task completed

Implemented the comprehensive Instrument Detail research hub for `ISSUE-0019`.
The selector now joins optional evidence by canonical instrument ID, exposes all
required evidence sections and fail-closed unavailable states, and keeps
`execution_allowed=false`. Instrument routes support `/instrument/<id>` while
retaining the `/etf` compatibility route. Score rows expose a keyboard-operable
"Open instrument detail" action.

## Files and symbols examined

- `src/etf_cockpit/app/selectors/instrument_detail.py`: `InstrumentDetailViewModel`, `build_instrument_detail`, evidence panel loaders.
- `src/etf_cockpit/app/pages/instrument_detail.py`: detail page and existing disclosure/news/driver renderers.
- `src/etf_cockpit/app/router.py`: `PAGES`, `_page_route`, `navigate_to`, shell rendering.
- `src/etf_cockpit/app/components/simple_scores.py`: grouped score rows and expansion controls.
- `src/etf_cockpit/app/pages/dashboard.py`, `src/etf_cockpit/app/pages/signals.py`: score-row callers.
- `tests/test_task19_instrument_detail.py`: focused RED/GREEN contract tests.

## Findings or changes

- Added canonical identity/group fields for ETF, stock and equity-certificate (Sparebanken-like) records.
- Added structured price history/latest price/date/freshness, score authority/reason/gates, risk dimensions, alpha/beta/correlation, forecasts, backtest trust, paper trades, journal, history and run-change panels.
- Optional parquet/parser stores are read defensively; corrupt or missing data is rendered as explicit unavailable evidence without crashing.
- Added `/instrument/<id>` route normalisation, selected-instrument state update and `instrument_detail_route()` helper.
- Added score-row detail actions in dashboard and Scores pages; existing expand-arrow behaviour remains unchanged.
- No issue ledgers, closure matrix, programme ledgers or GitHub synchronisation files were edited.

## Evidence

### RED

Command: `pytest tests/test_task19_instrument_detail.py -q`

Result: exit 1, four behavioural failures before implementation (`paper_trades`
section missing, canonical identity fields missing for custom IDs, corrupt-store
panel missing, and dynamic route helper missing).

### GREEN

Command: `pytest tests/test_task19_instrument_detail.py -q`

Result: exit 0, 5 passed (including score-row navigation callback).

Command: `pytest tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_task18_ui.py -q`

Result: exit 0, 26 passed.

Command: `pytest tests/test_e2e_workflow.py tests/test_flet_startup.py tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_task18_ui.py -q`

Result: exit 0, 40 passed.

## Commands or tests run

- `ruff check src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py src/etf_cockpit/app/router.py src/etf_cockpit/app/components/simple_scores.py src/etf_cockpit/app/pages/dashboard.py src/etf_cockpit/app/pages/signals.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src tests/test_task19_instrument_detail.py` - passed.
- A broader affected bundle including `tests/test_simple_scores.py` was also run; six existing fixture/configuration failures remain because the expected secondary/Sparebanken candidate CSV is absent from this worktree (`RAW_DIR/trade_candidates`), unrelated to Task 19 files.

## Remaining uncertainty and risk

- Strict release/package/browser, keyboard/focus/responsive, audit/export and clean-first-run closure evidence is not fresh and remains outside this implementation worktree, as required by the task brief.
- Paper-trade and decision-journal stores are not present in the current repository; the detail view intentionally reports unavailable until canonical, instrument-keyed records exist.
- The repository baseline `test_simple_scores.py` candidate-data failures need the parent/release gate to resolve or record separately.

## Recommended next action

Obtain the required independent specification/code review, then run the fresh
release/package/browser and clean-first-run evidence gates before integrating.
