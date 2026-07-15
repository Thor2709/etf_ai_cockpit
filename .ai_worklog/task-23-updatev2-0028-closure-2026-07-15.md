# Task 23 - UPDATEV2-0028 closure evidence (2026-07-15)

## Closure checklist

- [x] Required audit-packet functionality is present in the existing export, validation and import paths.
- [x] Provider, filing, ETF-document, conflict, holdings and candle evidence are represented; missing optional evidence is explicit and non-fabricated.
- [x] External audit import remains non-executable and `execution_allowed=false` remains unchanged.
- [x] UI export status and output path were observed in the rebuilt native package at `/chatgpt`.
- [x] Focused audit/backup/import/Data Health/release tests passed.
- [x] Fresh authoritative full suite passed with exit code 0; output is recorded in `evidence/final/tests/UPDATEV2-0028-full-suite.txt`.
- [x] Rebuilt Windows onedir package completed with `cmd.exe /d /c scripts\\build_windows.bat`, exit code 0.
- [x] Native package launch returned HTTP 200 on port 8955 and the packaged Audit Notes export was captured.
- [x] ZIP contents were inspected: 156 members, `ZipFile.testzip()` returned no corrupt member, SHA-256 `64010cb1f6cc33bfbe250c925a129e065dbfd07053313e0adbe5f9caf84badb6`.
- [x] Evidence paths, checksums, source hash and Python 3.12 environment hash are bound in `evidence/final/UPDATEV2-0028/verification_manifest.json`.
- [x] The canonical local issue record was moved from `issues/open.md` to `issues/closed.md`; the matrix status and checkpoint now agree.
- [x] Fresh independent specification/code review approval: `/root/updatev2_0028_reviewer`, SPEC PASS and CODE/EVIDENCE PASS; no Critical or Important findings.
- [x] PR #199 merged into `origin/main` at `772817c15ec9eeb9cb805a16451249f44536bfa9`; GitHub Issue #168 is closed and synchronised.

## RED-GREEN-REFACTOR evidence

The source implementation and prior Task 21 regression tests were already present at this Task 23 closure boundary. The fresh closure RED was the read-only evaluator: before the evidence refresh it returned `blocked` because the required build evidence and candle artefact proof were absent. The GREEN refresh generated the current package/export/browser evidence; the fresh independent review then approved specification compliance and code/evidence quality with no Critical or Important findings.

## Fresh commands

```text
C:\Users\thor2\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_complete_audit_packet.py tests/test_backup_restore.py tests/test_import_export.py tests/test_data_health.py tests/test_release_hardening.py -q --tb=short  # exit 0
C:\Users\thor2\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests -q --tb=short  # exit 0; evidence/final/tests/UPDATEV2-0028-full-suite.txt
cmd.exe /d /c scripts\\build_windows.bat  # exit 0
C:\Users\thor2\AppData\Local\Programs\Python\Python312\python.exe scripts/verify_issue.py UPDATEV2-0028 --evidence-root evidence/final --matrix-path configs/closure_matrix.yaml  # pass
C:\Users\thor2\AppData\Local\Programs\Python\Python312\python.exe scripts/sync_github_issues.py --apply  # reconciliation pass: 76 open, 22 closed, states agree
```

## Scope and authority

No score weights, model authority, portfolio target, research threshold, data coverage or execution scope changed. `execution_allowed=false` remains true as a safety invariant (execution is disabled). No broker or autonomous trading capability was introduced.

## Integration

Branch `wave5/task23-final-records` was pushed normally and merged through
[PR #199](https://github.com/Thor2709/etf_ai_cockpit/pull/199). The resulting
merge commit is `772817c15ec9eeb9cb805a16451249f44536bfa9`. GitHub Issue #168
was read back as closed with the canonical local-ID marker, current closed
record, manifest path and archive checksum. The synchronisation report proves
98 mapped records: 76 local/open and 22 local/closed, matching GitHub states,
with no unresolved duplicates.
