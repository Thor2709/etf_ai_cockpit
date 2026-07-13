# Task 19 fix 1 - independent review findings

## Task completed

Fixed the three Important findings from the independent review of the Task 19
Instrument Detail implementation. Instrument Detail now renders scoped record
content for price history, forecasts, backtest signal/trade logs, paper trades,
decision-journal entries and run changes. ETF disclosure registry and holdings
rows are accepted only when a canonical `instrument_id` or `etf_id` column is
present, and foreign or unscoped rows are fail-closed. Broad alpha fallback is
kept separate from `sector_alpha_proxy`. `execution_allowed` remains false.

## Files and symbols examined

- `src/etf_cockpit/app/pages/instrument_detail.py`: `_render_evidence_section`,
  record rendering helpers.
- `src/etf_cockpit/app/selectors/instrument_detail.py`: `_etf_disclosure_panel`,
  holdings scoping and `_attribution_panel`.
- `tests/test_task19_instrument_detail.py`: UI record-content, disclosure ID
  validation and broad/sector alpha regressions.
- `issues/open.md` and `plan.md`: binding `ISSUE-0019` acceptance criteria and
  UI/test scope. No Task 19-specific export-control requirement was present.

## Findings or changes

- Added accessible, token-coloured selectable text rows for all list-valued
  evidence collections rather than silently omitting them from the page.
- Added explicit `manual_review`/unavailable states for non-canonical ETF
  registry and holdings schemas. Valid `instrument_id` and `etf_id` aliases are
  filtered to the selected instrument before any row is used.
- Removed `sector_alpha_proxy` from broad-alpha fallback aliases; broad alpha
  is sourced only from `alpha`/`alpha_proxy`, while sector alpha remains a
  separate field.

## Evidence

RED:

- `python -m pytest tests/test_task19_instrument_detail.py -q`
- Result: exit 1, five expected behavioural failures (record content omitted,
  idless/foreign disclosure handling, and sector-alpha fallback).

GREEN:

- `python -m pytest tests/test_task19_instrument_detail.py -q`
- Result: exit 0, 10 passed.

## Commands or tests run

- `python -m pytest tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_task18_ui.py -q` - 31 passed.
- `python -m ruff check src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src tests/test_task19_instrument_detail.py` - passed.

## Remaining uncertainty and risk

- Full release/package/browser, keyboard/focus/responsive, audit/export and
  clean-first-run gates remain pending for Task 19 closure.
- The generic record renderer displays all scoped rows as selectable evidence
  text; very large local stores may require future pagination, which is outside
  this focused review fix.
- No issue ledgers or closure records were edited.

## Recommended next action

Commit this focused fix, obtain fresh independent re-review, then run the
parent-owned full release and browser evidence gates before integration.
