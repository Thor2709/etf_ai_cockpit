# Wave 3 Task 7 brief - Button Audit, Error/Recovery Centre and Performance Evidence

## Owning issues

- `ISSUE-0011` - exhaustive button/control audit and acceptance coverage.
- `ISSUE-0040` - controlled error classification, recovery and failure-path
  preservation.
- `ISSUE-0039` - timing, cache diagnostics and lazy-import/performance evidence.

## Binding constraints

- Preserve the approved product scope and the current dark evidence-cockpit
  Flet vocabulary; no decorative or unrelated controls.
- `execution_allowed` remains `false`; do not add broker, credentials,
  autonomous execution or portfolio-management authority.
- Extend existing `core/errors.py`, `core/timing.py`, `/errors` route,
  diagnostics page, UI acceptance config and current atomic write/recovery
  architecture. Do not replace working foundations.
- Use RED-GREEN-REFACTOR. Tests must assert observable control coverage,
  recovery outcomes, cache/timing evidence and failure preservation rather than
  private implementation calls.
- Do not close issues in this task; complete closure evidence remains later.

## Required outcomes

1. UI acceptance inventory is exhaustive for registered routes and actionable
   controls, including expandable rows, file pickers, retry controls and
   callback/success/error signals. Missing inventory entries fail the test.
2. `ErrorStore` classifies network timeout/rate-limit as retryable and
   authentication, entitlement, invalid input, identity conflict, parser/schema,
   permission, locked-file and missing-data states as non-retryable unless the
   approved contract says otherwise. Messages remain redacted. Real workflow
   failures register retry callbacks when retryable; parser/provider callbacks
   surface controlled recovery states.
3. Forecast/backtest writes preserve the previous valid artefact on write
   failure and emit auditable controlled errors; use existing atomic I/O.
4. `timed_step` is integrated around startup/snapshot and workflow steps;
   diagnostics presents parsed duration/slow-step and cache hit/miss/
   invalidation evidence. Heavy model/parser imports remain lazy.

## Known baseline seams from read-only locator

- `src/etf_cockpit/core/errors.py`, `core/timing.py`,
  `app/pages/errors_recovery.py` and `app/pages/diagnostics.py` already exist
  but need stronger category precedence, retry wiring, parsed diagnostics and
  production timing/cache integration.
- `configs/ui_acceptance.yaml` contains 21 controls but omits several registered
  routes and many existing on-click/file-picker/expandable-row controls.
- `tests/test_button_contracts.py` only asserts three keys; current error and
  performance tests cover only three classification cases, one retry fixture,
  and one timing context.

## Owned files

Modify the existing source/configuration and tests necessary for the bounded
outcomes above. Add `.ai_worklog/task7-report.md` with exact RED/GREEN,
failure-injection, package/browser and review evidence. Do not begin Task 8.
