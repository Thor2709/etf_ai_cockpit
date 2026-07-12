# Task 7 implementation report

Date: 2026-07-12
Issues: ISSUE-0011, ISSUE-0040, ISSUE-0039
Status: implementation and focused acceptance evidence ready; issue dossiers remain open.

## RED

Added first failing tests for route/control inventory metadata, controlled error
category precedence and retry callback registration, atomic forecast/backtest
failure preservation, and parsed timing/cache diagnostics.

Initial command (worktree interpreter):

```text
python -m pytest tests/test_button_contracts.py tests/test_error_recovery.py tests/test_performance_contracts.py -q
C:\Users\thor2\AppData\Local\Programs\Python\Python312\python.exe: No module named pytest
```

The shared Task 6 interpreter initially had the same missing dev dependency.
The existing `requirements-dev.txt` was installed into that local shared
environment, after which the RED tests ran and exposed the expected missing
inventory/category behaviour.

## GREEN

Focused command:

```text
..\task6-workflow-runtime\.venv\Scripts\python.exe -m pytest tests/test_button_contracts.py tests/test_error_recovery.py tests/test_performance_contracts.py -q
11 passed
```

Affected regression command:

```text
..\task6-workflow-runtime\.venv\Scripts\python.exe -m pytest tests/test_accessibility_contracts.py tests/test_flet_startup.py tests/test_release_hardening.py -q
46 passed
```

Workflow/atomic/provider regression command:

```text
..\task6-workflow-runtime\.venv\Scripts\python.exe -m pytest tests/test_workflow_runtime.py tests/test_e2e_workflow.py tests/test_optional_providers.py tests/test_atomic_io.py tests/test_backtest_costs.py tests/test_flet_startup.py -q
39 passed
```

Additional checks:

```text
python -m compileall -q src tests
exit 0

..\task6-workflow-runtime\.venv\Scripts\python.exe -m ruff check <scoped Task 7 source/tests>
All checks passed!

PYTHONPATH=src ..\task6-workflow-runtime\.venv\Scripts\python.exe scripts\run_app.py --smoke
snapshot_ok as_of=2026-07-10 signals=16 backtests=5

PYTHONPATH=src ..\task6-workflow-runtime\.venv\Scripts\python.exe -c "...load_ui_acceptance_contracts(); validate_ui_acceptance_inventory(...); ..."
routes 25 contracts 61 timing {'hit': 21, 'miss': 0, 'invalidation': 0}
```

## Changes and observable contracts

- `ErrorStore.record_exception()` now classifies failures with specific-state
  precedence, redacts messages/details, persists opaque retry keys and captures
  retry callback failures as controlled errors. Locked files, permission,
  missing data, parser/schema, identity, entitlement and authentication states
  are non-retryable; timeout/network and rate-limit states are retryable.
- App workflow failures pass real retry callbacks; startup, activity steps,
  forecast writes and backtest writes emit `timed_step` records to both the
  timing store and the session trace (unless a test-specific store is injected).
- Forecast CSV and the four backtest artefacts use existing atomic I/O. Group
  validation/rollback preserves all previous outputs if staging or validation
  fails. Empty optional forecast/trade frames remain valid artefacts.
- Timing helpers parse corrupt-tail-safe duration/slow records and explicit
  cache hit/miss/invalidation events. Diagnostics renders parsed duration,
  slow-step and cache counts rather than raw JSONL only. Forecast and backtest
  cache paths emit hit/miss/invalidation events.
- Parser imports in the trust/evidence UI remain lazy and parser callback
  exceptions render controlled recovery messages. Local import now owns a real
  FilePicker with cancellation/error guidance.
- UI acceptance inventory expanded to 63 records across all 25 registered
  routes, including navigation, workflow buttons, expandable score rows,
  picker controls, parser actions, retry, settings, journal, audit and import
  controls (including wildcard records for data-driven rows and glossary/route
  links). Every record has callback, success/error signals, control type and
  acceptance-test reference. Stable keys were added to previously anonymous
  controls.

## Files edited

`configs/ui_acceptance.yaml`; `src/etf_cockpit/app/components/simple_scores.py`;
`src/etf_cockpit/app/pages/chatgpt_audit.py`, `dashboard.py`, `diagnostics.py`,
`errors_recovery.py`, `import_export.py`, `settings.py`, `trust_evidence.py`;
`src/etf_cockpit/app/pages/help_glossary.py`;
`src/etf_cockpit/app/state.py`; `src/etf_cockpit/core/errors.py`, `timing.py`,
`ui_acceptance.py`; `src/etf_cockpit/services.py`; and
`tests/test_button_contracts.py`, `tests/test_error_recovery.py`,
`tests/test_performance_contracts.py`.

## Review limitations and skipped checks

- The full repository pytest run was started and reached 41% before the
  execution window was intentionally interrupted; it is not claimed as a
  complete pass. The focused and affected suites above are complete.
- Windows package rebuild, browser/Chrome/computer-use route evidence and
  native/portable smoke were not run in this isolated worktree. No external
  writes, PR or issue closure was performed.
- Test startup touched schema-version file timestamps; their content hashes
  are unchanged and they are not part of the Task 7 source diff.

## Final verification evidence

- Final focused verification after the last implementation refinement:

  ```text
  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_button_contracts.py tests/test_error_recovery.py tests/test_performance_contracts.py tests/test_accessibility_contracts.py
  15 passed

  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_workflow_runtime.py tests/test_e2e_workflow.py tests/test_optional_providers.py tests/test_atomic_io.py tests/test_backtest_costs.py tests/test_flet_startup.py tests/test_release_hardening.py tests/scope_boundary
  72 passed, 1 warning

  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m compileall -q src tests
  exit 0

  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m ruff check src/etf_cockpit tests/test_button_contracts.py tests/test_error_recovery.py tests/test_performance_contracts.py
  All checks passed!

  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\run_app.py --smoke
  snapshot_ok as_of=2026-07-10 signals=16 backtests=5
  ```

- A fresh full `pytest -q` completed with eight failures. Seven are the known
  isolated-worktree generated-market-data/trust-fixture gaps (`data/raw/trade_candidates`
  and the larger identity artefact are absent); the transaction activation
  failure is order-dependent under the complete suite and passes in isolation
  (`tests/operations/test_transactions.py::test_group_reader_cannot_observe_mixed_generation_during_activation`,
  1 passed). These failures pre-date Task 7 and are recorded as baseline
  limitations, not as Task 7 success claims.
- The Windows package was rebuilt with PyInstaller:
  `cmd /c scripts\build_windows.bat` exited 0. Native executable:
  `build/flet_dist/ETF_AI_Cockpit/ETF_AI_Cockpit.exe`, SHA-256
  `CA1BC8CE0D3C521D14323F4577867CDAD84FA0AFF00C2EC36B5CA59C90E6D018`.
  Portable output: `build/ETF_AI_Cockpit_Portable_v0.1.0`.
- Direct native readiness against the verified main data root returned HTTP 200
  and `native_direct_ready=True` on port 8562. The standard native smoke
  remains blocked by the known generated-data fixture (`Sparebanken group did
  not preserve AURG needs_verification ISIN`).
- Source-browser checks used the in-app browser against the Task 7 source server:
  dashboard screenshot `evidence/task7-dashboard.png` (SHA-256
  `80964F9BFB05989BEF37CC9E054621451F65FE8C4A7C4464BCE65BF9562F1DF6`) and
  diagnostics screenshot `evidence/task7-diagnostics.png` (SHA-256
  `B689380B5EED1CBD53AE31A71D57AEEA420B7A88B967EE1B71C9873F6F4BA8A4`) and
  errors/recovery screenshot `evidence/task7-errors.png` (SHA-256
  `B995CC51BC40A3F5A48B33BE63D2C43F669AC19192B57CECB2B65B24902B8E13`).
  The navigation rail is scrollable and the rendered Errors & Recovery route
  was reached by clicking the visible navigation control; retry-enabled
  timeout records and their action IDs are visible. Diagnostics was then
  reached from the same scrolled rail and its URL was `/diagnostics`.
- The source-linked inventory validator now parses every application-page
  callback/file-picker/helper call, resolves stable and wildcard key patterns,
  and fails closed when a source control lacks a contract. A negative test
  removes `dashboard.export-audit` and observes the required failure.
- Package route/launcher checks against the verified main data root all passed:

  ```text
  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\smoke_app.py --mode native --port 8566 --timeout 90
  smoke_ok mode=native url=http://127.0.0.1:8566/

  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\smoke_app.py --mode portable-native --port 8567 --timeout 90
  smoke_ok mode=portable-native url=http://127.0.0.1:8567/

  ..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\smoke_app.py --mode launcher --port 8568 --timeout 90
  smoke_ok mode=launcher url=http://127.0.0.1:8568/
  ```
- The earlier standard native smoke failure remains limited to the isolated
  worktree fixture when `ETF_COCKPIT_ROOT` is not pointed at the verified main
  data root; it is not a Task 7 code failure.

## Independent review and fix-pass evidence

- Fresh independent review initially rejected specification readiness with two
  Important findings: the acceptance inventory validator was not linked to
  source controls, and the required browser/package route evidence was not
  complete. Code-quality review found no Critical or Important correctness
  defect in the error, timing, atomic-write or authority-boundary changes.
- The inventory validator now performs a source-linked AST discovery pass over
  application pages, resolves stable and wildcard control keys, and fails
  closed when a source callback or picker has no acceptance contract. The
  regression suite contains a negative missing-contract test.
- The desktop navigation rail now scrolls, making all registered routes,
  including Diagnostics and Errors & Recovery, reachable in the rendered
  source application. Fresh in-app browser evidence reaches both routes and
  records the screenshots and checksums above. Native, portable-native and
  launcher smoke checks all returned `smoke_ok` against the verified data root.
- The first reviewer’s minor observation that retry callbacks do not create a
  new activity record is documented as non-blocking: the retry action is
  itself persisted by the existing ErrorStore and remains within the approved
  authority boundary.
- Fresh re-review after the fix pass: SPECIFICATION COMPLIANCE PASS; CODE
  QUALITY PASS; READY_FOR_INTEGRATION yes. No Critical or Important findings.
  Two Minor recommendations remain non-blocking: make source parse/read
  failures explicit in the inventory validator, and tighten dynamic-family
  wildcard matching. Compile/test gates currently fail on syntax errors and
  the checked-in contract uses wildcard families, so neither recommendation
  leaves a coverage gap for Task 7.

## Recommended next action

Request the fresh independent review of the 63-control inventory and
retry/error evidence before updating any issue dossier.
