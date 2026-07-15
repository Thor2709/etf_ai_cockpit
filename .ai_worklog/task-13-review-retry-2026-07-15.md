# UPDATEV2-0013 post-review retry and release verification - 2026-07-15

## Scope

This checkpoint records a defect-correction and verification pass for the ESEF/iXBRL parser and the Windows release path. `UPDATEV2-0013` remains open because the programme closure rules require final issue dossiers, audit/export evidence and the complete packaged/browser matrix in the later closure task.

## RED-GREEN-REFACTOR evidence

- RED: `python -m pytest tests/test_esef_ixbrl_parser.py::test_nonfatal_arelle_package_diagnostics_do_not_block_offline_facts -q --tb=short` failed before the parser change because optional Arelle package-loader diagnostics were treated as blocking errors (`result.success is False`).
- GREEN: the focused parser suite passed after the implementation and after the independent reviewer’s two fix passes. The final run was `python -m pytest tests/test_esef_ixbrl_parser.py -q --tb=short` with 14 passed.
- The implementation now preserves typed child-process exception codes, correlates `ix11.12.1.2:missingReferences` only with a loader limitation from the same run, and leaves explicit conformance failures blocking. Tests cover standalone errors, correlated offline loader diagnostics and explicit conformance errors alongside retrieval failures.

## Independent review

- Fresh reviewer `/root/task13_review` performed two re-reviews. The first rejected the change with two Important findings; both were fixed. The second review passed specification compliance and code quality with no Critical or Important findings. Minor recommendations were limited to direct worker-boundary and behavioural PyInstaller-spec tests.

## Verification evidence

- `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests -q --tb=short` → full authoritative suite passed at 100%; only existing GluonTS/deprecation warnings were emitted.
- `...python.exe -m ruff check src tests` → `All checks passed!`.
- `...python.exe -m compileall -q src tests` → passed.
- `git diff --check` → passed; only normal CRLF conversion warnings were reported.
- Audit/backup/import/export/data-health/release bundle → passed.
- PyInstaller Python 3.12 build (`build/flet_dist_rc1_task13fix`) → completed successfully; warnings are limited to optional `pycparser`, SciPy and `jvm.dll` discovery.
- Fresh native onedir smoke on port 8921 → ready and HTTP 200.
- Fresh portable ZIP: `build/ETF_AI_Cockpit_Portable_v0.1.0rc1_task13fix.zip`, 259856181 bytes, SHA-256 `EDD1E70453AF9D1DC6EFE0967F551711695946F8EC7956BB5AA6C0428C219CAA`.
- ZIP extracted outside the repository to `C:\Users\thor2\Desktop\release_test_task13fix` (path contains spaces); native executable returned HTTP 200 on port 8922. The no-Python batch fallback also returned exit code 0 on port 8923.

## Closure position

The parser and release regression is implementation-complete and independently approved. The issue remains open/closure-pending because the approved closure gate is owned by the later full issue-dossier/evaluator task; no issue ledger transition is made in this checkpoint. `execution_allowed=false` is unchanged.
