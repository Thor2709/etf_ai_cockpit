# Wave 1 Governance Task 4 brief

Read this brief first. Implement only Wave 1 Governance Task 4 on branch
`wave1/governance-task4`, based on `origin/main` at `7e9a0eceeef826dd373510e9e1c78269817a2a3d`.

## Required outcome

Replace transaction-shaped portfolio proposal output with a typed,
non-executable portfolio review report and create an immutable, append-only
user-owned Decision Journal using the existing atomic grouped-write foundation.
Preserve the Task 3 `AuthorityDecision`, v2 research/portfolio states and the
literal `execution_allowed=False` boundary.

## Exact scope

Create:

- `src/etf_cockpit/portfolio/review_reports.py`
- `src/etf_cockpit/data/decision_journal.py`
- `tests/test_portfolio_review_reports.py`
- `tests/test_decision_journal.py`
- `evidence/governance/decision_journal_export_summary.json`

Modify only the required seams in `src/etf_cockpit/portfolio/proposals.py`,
`src/etf_cockpit/app/state.py`, `src/etf_cockpit/data/trust_artifacts.py` and
audit/export callers. Reuse `core.atomic_io` grouped writes and current typed
authority models; do not replace them.

## Behavioural contract

- Expose `create_portfolio_review_report(signals, data_report, *, run_id,
  report_dir=REPORTS_DIR) -> dict[str, object]` with research/portfolio state,
  gate metadata, reasons and blocked summary, but no transaction-shaped
  authority. Every output contains `execution_allowed: false`,
  `executable_authority: false`, `broker_execution: "not_supported"` and a
  clear manual-review requirement.
- Keep `create_manual_trade_proposal_report` as a compatibility adapter only;
  it delegates to the review report, emits a deprecation warning/event and
  cannot create executable authority. Existing callers and serializers remain
  compatible.
- Journal entries are typed, user-owned and append-only. Each entry has a
  stable journal ID, created timestamp, thesis/decision/outcome fields,
  checksum and schema version. `create`, `get`, `list_entries` and
  `supersede` are deterministic. Superseding appends a new record and never
  mutates the original. Duplicate IDs, malformed rows, checksum mismatches,
  interrupted grouped writes, missing index/payload files and private-log
  leakage fail closed with explicit diagnostics.
- Journal persistence uses atomic grouped JSON/Parquet (or existing equivalent)
  commits, recovery-safe manifests and checksums. Logs may contain IDs,
  statuses and checksums only; raw thesis/private notes must not be written to
  operational logs or export summaries.
- Export summary is opt-in and contains schema/policy version, row counts,
  IDs and checksums but no raw thesis or notes.
- No broker, order routing, credentials, autonomous execution, Task 5 UI or
  unrelated product redesign.

## TDD and review contract

Write meaningful RED tests first, then run:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_portfolio_review_reports.py tests\\test_decision_journal.py tests\\test_trade_proposals.py -q --tb=short
```

Record the genuine behavioural failure, exact output and timestamp in
`.ai_worklog/task-governance-4-report.md`. Implement the smallest compatible
change, run GREEN and affected regressions (`tests/test_atomic_io.py`, audit,
export, governance and proposal suites), compileall, scoped Ruff and the full
suite. Keep the seven historical fixture failures separate if they recur.
Append a structured report with migration/compatibility, failure injection,
audit/export/checksum, review and limitations evidence. Do not close issues in
this task branch.

## Invariants

`execution_allowed` remains `false`; score weights, model authority, portfolio
targets, thresholds, DATA-05 membership, provider contracts, atomic I/O,
session tracing and Flet architecture remain unchanged. Task 5 UI is out of
scope. Use independent review before integration.
