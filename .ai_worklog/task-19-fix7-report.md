# Task 19 fix 7 - candidate detail context and metadata fail-closed guards

## Task completed

Implemented the approved Task 19 review fixes without changing score authority
or enabling execution:

- Score-row navigation now carries the `SimpleInstrumentScore` through
  `AppState.selected_instrument_score` to `build_instrument_detail`.
- Secondary-tier ETF/stock and Sparebanken candidate rows absent from the
  configured universe now render canonical score-row identity, latest price and
  score evidence. Optional stores remain explicit unavailable/manual-review
  panels.
- Friction scenarios accept only scalar `low`, `base` or `high` values.
- Parsed disclosure freshness, backtest trust quality and fundamentals
  eligibility reject unknown or container values and fail closed.
- `execution_allowed` remains `False` on score, friction, price and backtest
  evidence panels.

## Files and symbols examined

- `src/etf_cockpit/app/components/simple_scores.py`: `_score_tile` detail
  callback.
- `src/etf_cockpit/app/router.py`: `navigate_to` candidate context hand-off.
- `src/etf_cockpit/app/state.py`: `AppState.selected_instrument_score`.
- `src/etf_cockpit/app/pages/instrument_detail.py`:
  `instrument_detail_page` selector hand-off.
- `src/etf_cockpit/app/selectors/instrument_detail.py`:
  `_fundamentals_panel`, `_parsed_panel`, `_friction_panel`, `_backtest_panel`,
  `_price_panel`, `_scoreboard_row` and `build_instrument_detail`.
- `tests/test_task19_instrument_detail.py`: candidate drill-down/navigation
  and adversarial metadata regressions.

## Findings or changes

- Candidate IDs are not in `snapshot.config.universe.etfs`; the selector now
  uses row context only when the requested ID has no configured identity. This
  preserves canonical configured-instrument stores and avoids stale score-row
  context overriding primary data.
- Candidate score rows provide only the existing row fields (instrument key,
  display/name/ticker/ISIN, latest price/date, score labels/reason and friction
  evidence); no issuer identifiers or optional-store data are invented.
- Malformed containers and unknown scalar metadata are rendered as
  `unavailable` with `manual_review` where evidence rows exist.

## Evidence

RED:

- Before production edits,
  `python -m pytest tests/test_task19_instrument_detail.py -q --tb=short`
  failed on the missing `candidate_score` APIs, arbitrary friction scenario,
  parsed freshness containers, backtest trust containers and malformed
  fundamentals eligibility.

GREEN:

- `python -m pytest tests/test_task19_instrument_detail.py -q --tb=short` - 52
  passed.
- Candidate parameterisation covers ETF, stock and Sparebanken rows; focused
  adversarial cases cover unknown scalar and list/dict/NumPy-array metadata.

## Commands or tests run

- `python -m pytest tests/test_task19_instrument_detail.py -q --tb=short` - 52
  passed.
- `python -m pytest tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_task18_ui.py -q --tb=short` - 73 passed.
- `python -m pytest tests/test_e2e_workflow.py tests/test_flet_startup.py -q --tb=short` - 14 passed.
- `python -m pytest tests/test_button_contracts.py tests/test_accessibility_contracts.py -q --tb=short` - 6 passed (UI acceptance inventory).
- `python -m ruff check src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/router.py src/etf_cockpit/app/components/simple_scores.py src/etf_cockpit/app/state.py src/etf_cockpit/app/pages/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src tests/test_task19_instrument_detail.py` - passed.
- `git diff --check` - passed; Git emitted only expected LF/CRLF conversion warnings.

## Remaining uncertainty and risk

- Full release/package/browser, keyboard/focus/responsive, audit/export and
  clean-first-run closure gates remain parent-owned and were not run.
- Candidate optional stores intentionally remain unavailable until the
  candidate is normalised into canonical local stores.
- The parent-owned untracked `.ai_worklog/task-19-brief.md` was not edited or
  staged.

## Recommended next action

Review the diff and run the parent-owned release/package/browser and
clean-first-run closure gates before integration.
