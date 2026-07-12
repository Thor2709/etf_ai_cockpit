# Wave 4 Task 10 - Data Health Centre

## Owner

`ISSUE-0035` (reopened after fresh review found the historical closure dossier and implementation incomplete under the current contract).

## Required observable behaviour

- Deterministically inventory prices, FX, ETF holdings, fundamentals, news, macro, forecasts, backtests, provider probes, official documents and migration state.
- For each row expose status, path, row count, checksum, explicit as-of date, freshness, provider, truthful persisted last-success/last-failure evidence and warnings.
- Missing, stale, corrupt, schema-mismatch and unavailable stores remain visible and cannot crash the page.
- Macro freshness derives from actual dated data, never filesystem time or the requested report date alone.
- `/data-health` provides functional status/dataset/provider filters and actionable links to Provider, Filings, ETF and Error routes; Dashboard retains a summary card.
- CSV export contains the visible inventory and a clear output path.
- Preserve `execution_allowed=false`, current Flet shell/tokens and all authority boundaries.

## Files owned by the implementer

- `src/etf_cockpit/data/health.py`
- `src/etf_cockpit/app/pages/data_health.py`
- `src/etf_cockpit/app/router.py` (only if required for links)
- `src/etf_cockpit/app/pages/dashboard.py` (only if required for summary)
- `tests/test_data_health.py`

## RED-GREEN-REFACTOR contract

Add focused tests first and record the genuine missing-behaviour failure; implement the smallest compatible change; rerun focused and affected regressions; refactor only while green. Do not claim issue closure from code presence alone.

## Independent closure requirements

The task report must include exact commands/results, source/test/UI/export/build/browser evidence paths and checksums, migration/compatibility notes, review findings and limitations. The issue remains open until the closure matrix evaluates every criterion ready.
