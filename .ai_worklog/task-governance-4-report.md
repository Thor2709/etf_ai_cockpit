# Wave 1 Governance Task 4 report

## RED evidence

- Timestamp (UTC): 2026-07-12T09:32:00Z
- Command: `$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_portfolio_review_reports.py tests\\test_decision_journal.py tests\\test_trade_proposals.py -q --tb=short`
- Exit: 1
- Genuine failure: test collection failed because the Task 4 production modules did not yet exist:
  - `ModuleNotFoundError: No module named 'etf_cockpit.portfolio.review_reports'`
  - `ModuleNotFoundError: No module named 'etf_cockpit.data.decision_journal'`
- Existing `tests/test_trade_proposals.py` was not executed because collection was interrupted by the missing Task 4 imports.

- Timestamp (UTC): 2026-07-12T09:35:00Z
- Command: `$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_portfolio_review_reports.py tests\\test_decision_journal.py tests\\test_trade_proposals.py -q --tb=short`
- Exit: 1
- Genuine failure: collection again failed on the two intentionally absent Task 4 modules (`ModuleNotFoundError: etf_cockpit.portfolio.review_reports` and `ModuleNotFoundError: etf_cockpit.data.decision_journal`); proposal tests were not collected.

## GREEN and refactor evidence - 2026-07-12

- Implemented `create_portfolio_review_report` and the deprecated
  `create_manual_trade_proposal_report` adapter. Reports preserve typed state,
  gate metadata and reasons but set `execution_allowed=false`,
  `executable_authority=false` and `broker_execution=not_supported`.
- Implemented `DecisionJournal` and `JournalEntry` with checksum-verified JSON
  payloads, an atomic grouped payload/index commit, deterministic superseding
  IDs, append-only reads, missing-index/tamper diagnostics, ID/checksum-only
  operation logs and private-note-free export summaries.
- GREEN command: `$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_portfolio_review_reports.py tests\\test_decision_journal.py tests\\test_trade_proposals.py -q --tb=short` - exit **0**, 7 passed; two expected deprecation warnings from the compatibility adapter.
- Compileall over `src` and `tests`: exit **0**.
- The journal checksum-tamper, duplicate-ID, supersede and private-log tests all pass. No Task 5 UI, broker, order routing, credentials or execution authority was added.

## Full-suite classification

- Full isolated-worktree suite capture: `evidence/governance/task4-full-suite.txt`,
  exit **1** with eight failures: the seven known generated-data/identity
  fixture failures plus one transient Windows `PermissionError` in the
  pre-existing atomic transaction recovery test
  `tests/operations/test_transactions.py::test_recovery_of_interrupted_second_real_writer_preserves_first_commit`.
- The atomic recovery failure was rerun in isolation and exited **0**. It is
  therefore recorded as environment-sensitive pre-existing evidence, not a
  Task 4 regression. Post-merge verification must rerun the full suite on
  `main`, where generated artefacts are present.

## Review-fix RED/GREEN evidence - 2026-07-12

- Fix-pass RED command: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/test_decision_journal.py tests/test_portfolio_review_reports.py`.
- Fix-pass RED exit: **1**. The new adversarial tests failed on unsafe IDs,
  malformed index rows, operation-log faults, order-dependent supersede IDs and
  transaction-shaped report output.
- Implemented fixes: grouped index/payload reads for `get` and `list_entries`,
  strict operation-record schema validation, fail-closed persisted-integrity
  errors, safe hashed filenames for long IDs, bounded content-derived
  supersede IDs, neutral release report recommendations, direct AppState use of
  the review report, and policy metadata in journal export evidence.
- Fix-pass GREEN command: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/test_decision_journal.py tests/test_portfolio_review_reports.py tests/test_trade_proposals.py`.
- Fix-pass GREEN exit: **0**, **17 passed**; two expected deprecation warnings.
- Adversarial boundary subset: **5 passed** for missing index, private log
  fields, persisted unsafe IDs, long source IDs and neutral recommendations.
- Fix-pass compileall: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m compileall -q src tests` - exit **0**.
- Fix-pass Ruff: scoped Task 4 source/tests - exit **0**.
- Fix-pass `git diff --check`: exit **0**; only line-ending warnings for the
  pre-existing dirty schema files.

## Final review-fix evidence - 2026-07-12

- Fresh review RED observations: unsupported operation semantics, index/payload
  identity mismatch, supplied-signal policy relabelling, missing supersede
  operation semantics, unsupported persisted entry schema and cross-process
  read-modify-write loss risk.
- Final fixes: operation allow-list with SHA-256/schema validation; explicit
  `superseded` operation events; payload/index identity checks; persisted entry
  schema fail-closed checks; signal-policy evidence preservation; and a
  filesystem-backed per-journal lock around the complete read-modify-write
  publication.
- Final focused GREEN command: `..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe -m pytest -q tests/test_decision_journal.py tests/test_portfolio_review_reports.py tests/test_trade_proposals.py` - exit **0**, **21 passed**; two expected deprecation warnings.
- Lock-fix correction: removed age-based lock stealing, added an unguessable
  owner token, verified ownership before release, and classified an orphaned
  lock as an explicit manual-review timeout. The focused bundle was rerun with
  exit **0**, **21 passed**.
- Ownership-fix correction: acquisition-error cleanup now removes a lock only
  when this attempt created it and the token still matches; superseded
  operations require a source entry and ordinary creates cannot claim a source.
- Ownership-fix GREEN command: the focused Task 4 bundle exited **0**, **23
  passed**; two expected deprecation warnings.
