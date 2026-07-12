# ETF AI Cockpit Programme Progress Ledger

**Purpose:** Durable continuation state for the approved A/C-N implementation programme. This file records evidence-backed state only; it does not close a requirement by itself.

## Current checkpoint

| Field | Value |
|---|---|
| Updated | 2026-07-12 |
| Active phase | Wave 0 Task 5 independently approved, corrected after re-review, merged and post-merge verified; Wave 1 governance Task 1 is next |
| Active plan | `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md` |
| Git state | `main` is clean and matches `origin/main` at merge commit `fc4d61cfc6e77da9a91aeb5afe0341b1d7658f55`; Task 5 PR 4 is integrated |
| Existing closure state | 4 ready / 37 tracker records still open; DATA-05 is a new separate requirement |
| Fresh baseline | pytest exit 0, Ruff clean, compileall exit 0, source snapshot smoke exit 0, source/native/portable smoke exit 0 and rendered in-app-browser source-route inspection |
| Pre-existing type state | recorded mypy failure caused by external stubs and existing typing debt; no new failure attributed |
| Known historical evidence limitation | Existing package/browser evidence predates this programme and cannot close new work |

## Wave ledger

| Wave | Owning plan | State | Last verified evidence | Next gate |
|---:|---|---|---|---|
| 0 | foundation, operations and boundary | Tasks 1-5 independently approved, merged and post-merge verified; local issue mirror synchronised | Task 5: focused 31 passed, release 26 passed, operations 81 passed, fresh independent re-review approved with no Critical/Important findings, Ruff/compileall/pip/PowerShell AST clean and source smoke; GitHub reconciliation 98 records, 77/21 state counts, no unresolved duplicates | Start Wave 1 governance Task 1; `UPDATEV2-0029`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0045` and later tracker issues remain open |
| 1 | governance | Not started | occurrence map identifies legacy action, `trading_allowed`, proposal and model-weight seams | establish typed governance RED suite |
| 2 | registry and universe | Not started | `UniverseRecord`/optimistic revision/atomic save present | registry dry-run and validator RED suite |
| 3 | DATA-05 | Not started | no live seed verification has been performed in this programme | retrieve current official identity evidence and write failing seed-contract tests |
| 4 | storage and evidence | Not started | DuckDB helper, atomic I/O, Data Health and parser scaffolds present | catalogue/evidence contract RED suite |
| 5 | domain and scoring | Not started | source-aware deterministic scorer present; first-enabled benchmark and legacy ensemble remain | template/benchmark/champion RED suite |
| 6 | AI and validation | Not started | optional adapter foundations present; authority/caching/validation seams remain | strict forecast-state and fold/trial RED suite |
| 7 | portfolio | Not started | static holdings/allocation foundation present | immutable ledger RED suite |
| 8 | workspaces and workflow | Not started | router, dark shell and route inventory present | route/view-model/semantics RED suite |
| 9 | release closure | Not started | closure matrix and audit foundations present | fresh issue-specific evidence only after owning waves pass |

## Task-review log

| Date | Plan/task | Implementer | Reviewer | RED command/result | GREEN command/result | Review result | Evidence paths | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-07-11 | Planning pre-flight | primary agent | primary agent self-review only | Not applicable | Not applicable | Passed: no blocking contradiction; independent task review remains required before task closure | programme index and baseline commands | No implementation has started; nine plan headers, 60 epics and 37 open tracker mappings verified |
| 2026-07-11 | Wave 0 Task 1 - typed verification and closure evidence | fresh implementer | Pending fresh independent reviewer | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py -q` - exit 1, expected missing `etf_cockpit.operations` | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q` - exit 0, 15 passed | Implementation self-review passed; independent review pending | `.ai_worklog/task-1-report.md` | Matrix schema 2 exposes 42 records while preserving the historic 41 IDs; DATA-05 remains `still_open`. Source SHA-256: models `e648ff729aa29beb2754a44911d8293ec0fcd142941fbb4c52e466f8487275f8`, closure `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595` |
| 2026-07-11 | Wave 0 Task 1 - Important reviewer-finding fix | fresh fix implementer | Fresh independent re-review pending | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py -q` - exit 1, expected blank/whitespace identity tests did not raise | `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q` - exit 0, 18 passed; scoped Ruff and compileall exit 0 | Round-1 Important finding fixed locally; fresh independent re-review pending | `.ai_worklog/task-1-report.md`, `.ai_worklog/task-1-review-1.md` | Approved records now strip both actor IDs, reject blank IDs and reject normalised same-actor identities. No matrix or issue status change. Source SHA-256: models `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`; closure `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595` |
| 2026-07-11 | Wave 0 Task 1 - final independent task review | fresh closure reviewer | approved | original and actor-fix RED evidence recorded in task report | post-review 18 passed, Ruff clean, compileall exit 0 and source snapshot smoke exit 0 | Approved for Task 1 only; no issue closure | `.ai_worklog/task-1-review-4.md`, `.ai_worklog/task-1-report.md` | Important findings resolved; metadata-validation Minor retained for broad final triage |
| 2026-07-11 | Wave 0 Task 2 - operational event authority implementation | fresh completion implementer after interrupted first implementer | fresh review 1 | `.\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_event_store.py -q` - exit 1 for contextual schema-invalid complete-row error | same command - exit 0, 6 passed; focused operational/diagnostics regression 21 passed; full `tests` suite exit 0; scoped Ruff/compile exit 0 | Review 1 CHANGES_REQUIRED: default workflow secondary log and stale dashboard path | `.ai_worklog/task-2-report.md`, `.ai_worklog/task-2-review-package.md`, `.ai_worklog/task-2-review-1.md` | New event IDs/hashes, legacy rows, tail quarantine, AppState projection and diagnostics integrity status were otherwise accepted; no issue closure |
| 2026-07-11 | Wave 0 Task 2 - authority-seam fix | fresh fix implementer | fresh review 2 | `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_workflow_runtime.py -q` - exit 1, 2 failures and 5 passes | same command - exit 0, 7 passed; final focused review bundle 28 passed; full `tests` suite exit 0; Ruff/compile exit 0 | Approved after both Important findings resolved | `.ai_worklog/task-2-authority-fix-report.md`, `.ai_worklog/task-2-review-2.md`, `.ai_worklog/task-2-review-package-final.md` | Default workflow lifecycle now persists only through `logs/session.jsonl`; explicit `log_path` is a compatibility/test seam; no issue status changed |
| 2026-07-11 | Wave 0 Task 3 - atomic transaction and deterministic recovery implementation/fix | fresh implementer plus five fresh fix/review cycles | fresh independent final reviewer `task-3-review-final2.md` | initial RED exit 1 with 11 behavioural failures; later RED cycles covered lock order, strict schema, mixed-reader, manual-review, rollback durability, owned artefacts, unreadable evidence, malformed states and null-backup safety | final focused bundle exit 0 with 71 passed; independent 11-test slice exit 0; Ruff/compile/diff exit 0 | **Approved for Task 3 integration**; no Critical, Important or Minor findings; issue remains open for later UI/package/browser closure | `.ai_worklog/task-3-report.md`, `.ai_worklog/task-3-fix-pass-2-report.md`, `.ai_worklog/task-3-fix-pass-3-report.md`, `.ai_worklog/task-3-fix-pass-4-report.md`, `.ai_worklog/task-3-fix-pass-5-report.md`, `.ai_worklog/task-3-review-final2.md`, `evidence/wave0/task3/` | Final implementation `201ee9e`; no issue transition yet; branch integration and GitHub synchronisation remain next gates |
| 2026-07-12 | Wave 0 Task 4 - no-execution/rejection boundary and generated-package correction | fresh implementer plus bounded parent fix pass after independent findings | fresh independent reviewers `.ai_worklog/task-4-review-postfix.md` and `.ai_worklog/task-4-postmerge-review.md` | initial RED collected 7 behavioural failures; fix-pass RED collected 2 bypass failures; post-merge regression RED reproduced generated `build/` false positives | final scope/release bundle 54 passed; release/operations 75 passed; Ruff/compile/pip/diff clean; deterministic production scan 358 files, zero violations; source smoke passed | **Approved and integrated**; no Critical, Important or Minor findings; no issue closure because Task 4 does not satisfy complete `ISSUE-0040` or later tracker gates | `.ai_worklog/task-4-brief.md`, `.ai_worklog/task-4-report.md`, `.ai_worklog/task-4-fix-report.md`, `.ai_worklog/task-4-fix-pass-2-report.md`, `.ai_worklog/task-4-review-1.md`, `.ai_worklog/task-4-review-postfix.md`, `.ai_worklog/task-4-postmerge-fix-report.md`, `.ai_worklog/task-4-postmerge-review.md` | PR 2 merged at `0f2b2cb`; correction PR 3 merged at `5b732e4`; `execution_allowed=false`; Task 5 is next |
| 2026-07-12 | Wave 0 Task 5 - deterministic evidence automation and fail-closed clean environment | fresh implementer plus fresh fix implementer | fresh independent reviewer and re-review `.ai_worklog/task-5-review-rereview.md` | initial RED exit 1 with three missing-artifact failures; fix-pass RED covered five Important fail-open paths with 8 failures | focused 31 passed; release 26 passed; operations 81 passed; Ruff/compileall/pip/PowerShell AST clean; source smoke passed; clean-environment execution intentionally unrun because it creates venv/package/browser artefacts | **Approved and integrated**; no Critical or Important findings remain; no issue closure because owning release/UI/browser gates remain open | `.ai_worklog/task-5-report.md`, `.ai_worklog/task-5-review.md`, `.ai_worklog/task-5-fix-pass-1-report.md`, `.ai_worklog/task-5-review-rereview.md` | PR 4 merged at `fc4d61cfc6e77da9a91aeb5afe0341b1d7658f55`; `execution_allowed=false`; Wave 1 governance Task 1 is next |
| 2026-07-12 | GitHub issue synchronisation | primary controller using deterministic sync tool; no product issue transition | focused release tests and deterministic read-back | RED/fix cycles covered duplicate identity and newline/idempotence handling; final apply exit 0; final dry-run exit 0 | 7 sync tests passed; Ruff clean; 98 canonical records mapped (77 open/21 closed), remote state counts agree and unresolved duplicates empty | **Synchronisation approved**; local ledgers remain authoritative and no issue state changed | `issues/github_issue_map.json`, `issues/github_issue_sync_report.json`, `.ai_worklog/github-issue-sync.md`, `scripts/sync_github_issues.py` | 166 remote records retained, including 68 closed exact-marker historical duplicates; no GitHub issue deleted; next task is Wave 1 Governance Task 1 |

## Open review findings

| Severity | Finding | Owning plan | Disposition |
|---|---|---|---|
| Important | Existing legacy actions, `trading_allowed`, proposal naming and positive model ensemble weights contradict the approved authority model | Governance | Planned Wave 1 migration; do not relabel-only fix |
| Important | Flat universe model cannot represent issuer/security/listing relationships or DATA-05 subareas without a controlled migration | Registry/Data-05 | Planned Waves 2-3 |
| Important | Existing broad passing tests and historical package screenshots do not satisfy issue-specific closure | Foundation/release | Planned Wave 0 and Wave 9 evidence controls |
| Minor | Closure-matrix metadata accepts unsupported programme schema versions and impossible historic-baseline counts | Wave 0 Task 1 foundation | Preserve for broad final-review triage; excluded from the narrowly scoped Important-finding fix |

## Resume instructions

1. Read the attached specification, the programme index, this ledger and the active plan.
2. Check `RUN_STATE.json`, `.ai_worklog/TESTING.md`, the latest task review and current file state.
3. Continue only the first unchecked task whose prerequisites are verified; Tasks 1-5 are merged and post-merge verified. Start Wave 1 governance Task 1 with a fresh implementer and independent reviewer; do not close `UPDATEV2-0029`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0045` or `ISSUE-0040` until their complete UI/package/browser gates pass.
4. Use a fresh implementer and a fresh reviewer for every substantive task; record their reports here.
5. Do not update issue state to closed until the closure-matrix evidence is fresh and independently reviewed.

### Wave 0 Task 3 review-capability checkpoint - 2026-07-11

Task 3 initially reached this checkpoint with implementation/fix evidence and parent-side adversarial verification, but its fresh independent review was then completed. The superseding final approval is recorded below; the historical capability-pending note is retained for audit chronology.

### Wave 0 Task 3 independent approval and integration handoff - 2026-07-12

Five bounded fix passes addressed the independent findings. Final implementation commit `201ee9e` passed 71 focused Task 3 tests, scoped Ruff, compileall and diff checks. A fresh independent reviewer ran an 11-test adversarial slice and approved specification compliance and code quality with no Critical, Important or Minor findings (`.ai_worklog/task-3-review-final2.md`). PR 1 merged the branch at `046e3bbfe9cab41f6cfec59547f540bce85b2c44`; post-merge focused tests, source smoke, Ruff and compileall passed. `ISSUE-0040` remains open because its Error/Recovery UI, package and browser gates belong to later dependency-valid work; `execution_allowed` remains `false`; DATA-05 remains `still_open`.

### Round-3 checkpoint-evidence correction - 2026-07-11

The durable PLAN now carries the four required slash-form actor-validation commands with individual exit codes. Current model SHA-256 is `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`; matrix schema 2, historic baseline 41, 42 active records and DATA-05 `still_open` remain unchanged. No issue was closed; the final independent task review later approved Task 1 only.

### Wave 0 Task 2 final checkpoint - 2026-07-11

Task 2 is independently approved. The final event authority includes typed `OperationalEvent` records, canonical session JSONL append/index, redaction-before-hashing, event IDs/prior hashes/current hashes for new writes, legacy-row support, incomplete-tail quarantine, complete-row integrity errors, AppState trace projection and diagnostics recovery status. The first review's two Important findings were fixed by a fresh implementer: default `WorkflowController` no longer writes `logs/workflow.jsonl`, and the dashboard names `logs/session.jsonl`. Final review 2 approved with no Critical, Important or Minor findings.

Evidence: `.ai_worklog/task-2-report.md`, `.ai_worklog/task-2-authority-fix-report.md`, `.ai_worklog/task-2-review-1.md`, `.ai_worklog/task-2-review-2.md`, `.ai_worklog/task-2-review-package-final.md`.

Final focused review bundle: 28 passed; full `tests` suite: exit 0; scoped Ruff and compilation: exit 0. Existing warnings are GluonTS JSON performance, pandas mixed-dtype loading and pandas concatenation deprecation. Fixture SHA-256: `ef7a5209f51a197b239b83e1ae117d6676817883d016325c7704dad1c80d806b`.

No issue moved between `issues/open.md` and `issues/closed.md`; `ISSUE-0069` remains historically closed and was only extended with regression protection. `execution_allowed` remains `false`; DATA-05 remains `still_open`.

### Wave 0 Task 4 integration checkpoint - 2026-07-12

Task 4’s static execution/rejection boundary, versioned rejection registry
and future-only architecture records were independently approved and merged
through PR 2 at `0f2b2cb`. Post-merge verification found false positives from
ignored generated `build/` artefacts; the RED regression, minimal `build`/`dist`
exclusion correction and fresh independent review are recorded in
`.ai_worklog/task-4-postmerge-fix-report.md` and
`.ai_worklog/task-4-postmerge-review.md`. PR 3 merged the correction at
`5b732e4`.

Final clean-main verification passed 54 scope/release tests, 75
release/operations tests, scoped Ruff, compileall, pip check, diff checks, a
deterministic 358-file production scan with zero violations and both authority
fields false, and source smoke. No issue moved between `issues/open.md` and
`issues/closed.md`; `ISSUE-0040` and later tracker records remain open. Wave 0
Wave 0 Task 5 is independently approved, merged through PR 4 and post-merge
verified. Its evidence automation and fail-closed clean-environment stages are
recorded in `.ai_worklog/task-5-report.md`,
`.ai_worklog/task-5-fix-pass-1-report.md`,
`.ai_worklog/task-5-review.md` and
`.ai_worklog/task-5-review-rereview.md`. No issue state changed; Wave 1
governance Task 1 is the next dependency-valid task.

### GitHub issue synchronisation checkpoint - 2026-07-12

The authenticated remote mirror now reconciles the authoritative local issue
ledger. `issues/github_issue_map.json` records 98 unique local IDs (77 open,
21 closed), canonical GitHub numbers and URLs, source checksums and the
selected local state. The final apply and read-only idempotence run both
passed; mapped state counts are 77/21 and there are no unresolved duplicate
matches. Exact stable-ID duplicate issues were retained and closed as
duplicates, with the complete history recorded in
`.ai_worklog/github-issue-sync.md`. No local issue moved between ledgers.
