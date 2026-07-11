# Task 1 closure re-review package - no-Git task base to current workspace

## Scope and review basis
- Base is the immutable pre-dispatch task snapshot; no Git repository or commit exists.
- Head is the current workspace after Round-3 docs-only checkpoint correction.
- Read code/config/test changes from the prior complete package at .ai_worklog/task-1-review-package-final.md; this package supplies the latest durable-record deltas and original requirements/reviews.
- Product code has not changed since the actor-validation re-review; Round-3 changes only durable evidence text.
- The metadata-validation Minor remains recorded for broad final triage.

## Latest PLAN checkpoint
```text
## 2026-07-11 Wave 0 Task 1 Checkpoint-Evidence Correction (Round-3 Important Finding)
```
## Latest report checkpoint
```text
## Round-3 Important Checkpoint-Evidence Correction - 2026-07-11
```
## Current durable state
```json
{
  "name": "2026-07-11-etf-ai-cockpit-approved-programme",
  "programme_index": "docs/superpowers/plans/2026-07-11-etf-ai-cockpit-programme-index.md",
  "progress_ledger": "docs/superpowers/plans/2026-07-11-etf-ai-cockpit-progress-ledger.md",
  "phase": "wave0_task1_review_fix_verified_fresh_independent_rereview_pending",
  "next_task": "Fresh independent re-review of Wave 0, Foundation Task 1 reviewer-finding fix",
  "git_repository": false,
  "baseline": {
    "pytest": 0,
    "ruff": 0,
    "compileall": 0,
    "source_snapshot_smoke": 0,
    "source_smoke": 0,
    "native_smoke": 0,
    "portable_native_smoke": 0,
    "rendered_source_browser_inspection": "passed"
  },
  "plan_preflight": {
    "implementation_plans": 9,
    "authorised_epics": 60,
    "still_open_tracker_records_mapped_once": 37,
    "blocking_contradictions": 0,
    "implementation_started": true
  },
  "task_1_checkpoint": {
    "matrix_programme_schema_version": 2,
    "historic_baseline_count": 41,
    "active_record_count": 42,
    "data05_status": "still_open",
    "red_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py tests\\release\\test_issue_evidence.py -q",
    "red_exit_code": 1,
    "green_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py tests\\release\\test_issue_evidence.py tests\\test_closure_matrix.py -q",
    "green_exit_code": 0,
    "full_test_exit_code": 0,
    "source_checksums_sha256": {
      "src/etf_cockpit/operations/__init__.py": "8c8ee081d0a4fdc3e72a543702ccca1d863413fdf79ba51ff8f7f29681740e48",
      "src/etf_cockpit/operations/models.py": "77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294",
      "src/etf_cockpit/core/closure.py": "59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e",
      "configs/closure_matrix.yaml": "c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595"
    },
    "review_fix": {
      "finding": "Round-1 independent review: approved evidence accepted blank actor IDs and whitespace-equivalent builder/reviewer identities.",
      "red_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py -q",
      "red_exit_code": 1,
      "green_command": ".\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_verification_records.py tests\\release\\test_issue_evidence.py tests\\test_closure_matrix.py -q",
      "green_exit_code": 0,
      "ruff_command": ".\\.venv\\Scripts\\python.exe -m ruff check src\\etf_cockpit\\operations\\models.py tests\\operations\\test_verification_records.py",
      "ruff_exit_code": 0,
      "compile_command": ".\\.venv\\Scripts\\python.exe -m compileall -q src\\etf_cockpit\\operations",
      "compile_exit_code": 0
    },
    "report": ".ai_worklog/task-1-report.md",
    "independent_review": "round_1_important_finding_fixed_fresh_independent_rereview_pending"
  }
}```
## Latest ledger checkpoint
```text
| 0 | foundation, operations and boundary | Task 1 reviewer-finding fix verified - fresh re-review pending | schema v2, historic baseline 41, 42 active records, reviewer-fix focused tests/Ruff/compileall exit 0 | fresh independent reviewer re-checks the Important identity-validation fix and Task 1 evidence |
| 2026-07-11 | Wave 0 Task 1 - Important reviewer-finding fix | fresh fix implementer | Fresh independent re-review pending | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py -q` - exit 1, expected blank/whitespace identity tests did not raise | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q` - exit 0, 18 passed; scoped Ruff and compileall exit 0 | Round-1 Important finding fixed locally; fresh independent re-review pending | `.ai_worklog/task-1-report.md`, `.ai_worklog/task-1-review-1.md` | Approved records now strip both actor IDs, reject blank IDs and reject normalised same-actor identities. No matrix or issue status change. Source SHA-256: models `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`; closure `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595` |
| Minor | Closure-matrix metadata accepts unsupported programme schema versions and impossible historic-baseline counts | Wave 0 Task 1 foundation | Preserve for broad final-review triage; excluded from the narrowly scoped Important-finding fix |
### Round-3 checkpoint-evidence correction - 2026-07-11
```
## Required reads
- Task brief: .ai_worklog/task-1-brief.md
- Consolidated report: .ai_worklog/task-1-report.md
- Reviews: .ai_worklog/task-1-review-1.md, .ai_worklog/task-1-review-2.md, .ai_worklog/task-1-review-3.md
- Complete code/config/test base-to-current package: .ai_worklog/task-1-review-package-final.md
