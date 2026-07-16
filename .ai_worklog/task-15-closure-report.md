# Wave 4 Task 15 closure report - current finalisation checkpoint

## Owning issues

- `UPDATEV2-0017` - PRIIPs KID parser and cost/risk disclosure extraction.
- `UPDATEV2-0019` - index methodology importer and source mapping.

## Task state

- Branch: `wave4/task15-closure-final`.
- Worktree: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.worktrees\TASK15-CLOSURE-20260715`.
- Base: `origin/main` at `29b46fa` when the closure branch was created.
- Current source verification hash: `13e8d244c4360baa44d44b1bac61d5d59b3ccd5eb27a19b9b4604b3daff9c9d0`.
- Environment hash: `92d7950f655410515a5c3d8b0d89a50c20c620a3da5c8f130fd8fedfeca085db`.
- `execution_allowed=false`; no broker execution, score-weight, model-authority, portfolio-target, research-threshold or DATA-05 scope change.

## RED-GREEN-REFACTOR evidence

The final source fix added deterministic newest-document selection, null-safe checksums and durable import progress/error activity. RED observations were recorded for the missing `_latest_document_row` helper and missing `_start_disclosure_import` helper; GREEN is recorded in `tests/test_task15_file_picker.py` and the current focused evidence. Earlier Task 15 parser, persistence and registry RED/GREEN evidence remains in `.ai_worklog/task-15-report.md`, `task-15-fix1-report.md`, `task-15-fix2-report.md` and `task-15-fix3-report.md`.

## Closure checklist

| Gate | State | Evidence |
| --- | --- | --- |
| Source/parser implementation | passed | `evidence/final/source/UPDATEV2-0017.md`, `UPDATEV2-0019.md`; implementation PR 185 |
| Schema and persistence | passed | parsed-disclosure, fund-document and audit CSV/JSON tests |
| Focused behavioural tests | passed | current Task 15 focused raw evidence and `tests/test_task15_file_picker.py` |
| Full authoritative test suite | passed | `evidence/final/tests/task15-full-ui-root-fixes-raw.txt`, SHA-256 `c3316a11ed907503aee27cdb9dd5ec62efad2b2ca355638493c34e098f8d41ef` |
| Ruff | passed | `evidence/final/tests/task15-ruff-ui-root-fixes-raw.txt`, exit 0 |
| Compileall | passed | exact `compileall -q src` at `tests/task15-source-exact-raw.txt`, SHA-256 `cc258d839e50d5e0cf220528399d5c29a6bcc5c3a9ee2616a915627e0363d91` |
| UI/source startup | passed | exact Flet startup at `tests/task15-ui-exact-raw.txt`, exit 0; 13 tests |
| Audit/export | passed | audit validation raw `evidence/final/export/task15-audit-ui-root-fixes-raw.txt`; canonical ZIP SHA-256 `c5f2233e7eb53ebfa4f7ad2413c6ec803d1b488e42ca7526826aa8fb157d32b0`, 162 entries; fixture-path provenance reconciled in `evidence/final/export/task15-audit-provenance-note.md` |
| Native/package build | passed | `build/task15-build-ui-root-fixes-raw.txt`, exit 0; executable SHA-256 `35e4b9182ee53feaa872eccfe2270cb7995dac11a27e2a5f807209ad0fab669b` |
| Clean extracted package | passed | `C:\Users\thor2\AppData\Local\Temp\ETF_AI_Cockpit_Task15PortableUIRootFixes_20260716`, outside repository and `.venv` |
| Browser/source smoke | passed | `browser/task15-browser-exact-raw.txt`, SHA-256 `cf65b23cc9d5e28d96ecc165e944f9928952fbdca8ab7f502a3f6ee0aa1a6eb3`; one clean retry after stale process isolation |
| Packaged UI | passed with limitation | 1280x720 capture `browser/task15-packaged-imported-ui-root-fixes-final.png`, SHA-256 `fa38188ec6a7a35beb333571f127ab8a0d92443301dd99f0a720eb022fef14f3`; browser accessibility placeholder only |
| Independent final review | passed | fresh re-review approved specification compliance and code quality with no Critical or Important findings |
| Closure evaluator | passed | both `scripts/verify_issue.py` runs returned `status=pass`, with no missing gates or limitations after the manifest correction pass |
| GitHub integration and issue sync | passed | PR #204 merged to `main` at `4379132092b8f037bd6227eb4562c2bfbcaa6748`; GitHub Issues #157 and #159 synchronised closed after local ledger transition |

## Bounded failure record

The first exact `python scripts/smoke_app.py --mode source` attempt failed after 60 seconds because two repository-owned `scripts/run_app.py` processes from earlier checks were still present; one eventually served HTTP 200 on port 8550, while the smoke controller timed out waiting for its own child. No unrelated processes were stopped. PIDs 37752 and 40932 were stopped, the port was confirmed clear, and one clean second attempt passed. No third smoke attempt is permitted for this source hash.

## Audit/package evidence

The final audit was generated once from the isolated imported-package root after the packaged KID and methodology imports. The KID row retains parsed fields while recording `identity_mismatch`, `manual_review=true` and `score_eligible=false`; the failed registry row is explicitly unavailable with no ephemeral path. The methodology row retains FTSE Russell version/date/rules and source checksum while holdings comparison is separately unavailable/manual-review. The complete portable folder contains native executable, launcher and package resources and launched outside the repository on port 8568.

## Policy checkpoint

`docs/superpowers/verification-finalisation-policy.md` is binding and referenced by the programme index and active closure plan. For the current source hash, one full suite, one build, one browser pass, one independent review and one re-review are permitted; only the exact missing verifier commands were added before the final review. Evidence edits do not alter executable verification inputs. Task 15 merged through PR #204 at `4379132092b8f037bd6227eb4562c2bfbcaa6748`; issue synchronisation was completed for #157 and #159. Phase 2 workflow refactor is the required boundary before Task 16.

## Post-merge integration

- Task 15 branch `wave4/task15-closure-final` was pushed and merged through PR #204.
- Local `main` and `origin/main` are aligned at `4379132092b8f037bd6227eb4562c2bfbcaa6748`.
- The local issue ledger records `UPDATEV2-0017` and `UPDATEV2-0019` as closed; corresponding GitHub Issues #157 and #159 were closed after the merge.
