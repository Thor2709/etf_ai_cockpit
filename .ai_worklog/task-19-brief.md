# Wave 5 Task 19 brief - Comprehensive Instrument Detail

## Ownership

- Issue: `ISSUE-0019` only.
- Worktree: `wave5/task19-instrument-detail` from `origin/main` at `3cc332c`.
- Implementer owns the instrument-detail selectors/pages/router/navigation and
  their focused tests. Do not edit issue ledgers, closure matrix, programme
  ledgers or GitHub synchronisation files.

## Binding outcome

Build the approved comprehensive Instrument Detail route as a canonical
research drill-down from score rows. It must assemble existing repository
stores without recalculating score authority in UI code or adding execution
capability. Preserve `execution_allowed=false`, current Flet dark evidence-
dense design, route compatibility and all existing authority/safety seams.

## Required view-model contract

`build_instrument_detail(snapshot, instrument_id) -> InstrumentDetailViewModel`
must expose honest sections for:

- identity and group;
- price history, latest price/date and freshness;
- Evidence Score, Evidence Quality, final label/reason and blocked gates;
- momentum, trend, relative strength, volatility, drawdown and liquidity/cost;
- alpha, beta and correlation;
- fundamentals;
- ETF holdings/exposure;
- news/context;
- forecast evidence;
- backtest trust;
- paper-trade history;
- decision journal entries;
- what changed since the last run.

ETF, stock and Sparebanken-like identities plus missing/corrupt optional data
must render explicit unavailable states and never crash. Join by canonical
instrument ID and source IDs; do not infer identity from display text.

## UI and navigation

Link score rows to `/instrument/<id>` or the repository-supported selected-state
equivalent. Retain `/etf` compatibility until tests prove no broken links.
Use reusable current components/tokens and full-width inspectable evidence
sections. Preserve keyboard focus, semantic labels, readable contrast,
responsive layouts and honest loading/empty/partial/stale/unavailable/error
states. No decorative filler or new product capability.

## RED-GREEN-REFACTOR

1. Add meaningful failing ETF, stock, Sparebanken and missing/corrupt optional
   store view-model tests plus route/row-navigation tests; run the exact RED
   command and record a real behavioural failure.
2. Implement the smallest repository-consistent selectors and route/panel
   change.
3. Run focused GREEN tests, affected regressions, Ruff, compileall and diff
   checks; write `.ai_worklog/task-19-report.md` with exact results.

## Closure boundary

Task 19 cannot close `ISSUE-0019` without fresh full release/package/browser,
keyboard/focus/responsive, audit/export and clean-first-run evidence. Keep the
issue open as implementation-complete/closure-pending if those gates are not
fresh. Obtain a fresh independent specification/code review before integration.
