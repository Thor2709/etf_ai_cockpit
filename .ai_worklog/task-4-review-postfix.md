# Wave 0 Task 4 - independent postfix review

Date: 2026-07-12 (Australia/Sydney)
Worktree: `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task4-execution-boundary`
Reviewed range: `c5fd053425376508e141f3cef3cc09f72d2fe791b5..c7372d3`, plus the current working-tree residual fix in `src/etf_cockpit/governance/static_checks.py` and `tests/scope_boundary/test_execution_boundary.py`
Reviewer role: fresh bounded post-fix review; no source or test authorship

## Evidence reviewed

- `.ai_worklog/task-4-brief.md`
- `.ai_worklog/task-4-report.md`
- `.ai_worklog/task-4-review-1.md`
- `.ai_worklog/task-4-fix-report.md`
- `.ai_worklog/task-4-fix-pass-2-report.md`
- The Task 4 section of `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md`
- The current diff from `c5fd053`, including the residual working-tree changes
- `src/etf_cockpit/governance/static_checks.py`, `configs/rejection_registry.yaml`, all three future-only documents, and the three scope-boundary test modules

## Verification commands

The requested bounded test bundle passed:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\scope_boundary tests\test_release_hardening.py -q --tb=short
53 passed, exit 0

C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\release -ra --tb=short
2 passed, exit 0
```

`git diff --check c5fd053..HEAD` and `git diff --check` were clean. No full test suite or package rebuild was run, per scope.

The current production-tree scan was run with `PYTHONPATH=src` and returned:

```text
result=pass
scanned_files=355
violations=[]
policy_checksum=2962d01d93f9be08c4ec9e9475a54a58c047c5f18c775f5cc49a159d98be6df0
execution_allowed=False
executable_authority=False
```

Two consecutive scans produced identical result, violation, file-count,
checksum and authority fields (only `generated_at` differed, as expected for a
generation timestamp).

## Post-fix adversarial verification

The following temporary-tree probes were run against the current source. They
were not committed and did not modify source or tests.

- `src/etf_cockpit/data/bad.py` and `src/etf_cockpit/models/bad.py` were visited and rejected with `PROHIBITED_ORDER_SYMBOL`.
- `.pem`, `.key`, `.p12` and `.pfx` resources were inventoried and rejected with `PROHIBITED_CREDENTIAL_RESOURCE`; arbitrary `config.env`, `.env.local` and `*.env` forms rejected enabled authority values.
- INI `[DEFAULT]` authority values were rejected with `EXECUTION_AUTHORITY_ENABLED`.
- A registry with top-level `executable_authority: true` was rejected; missing top-level audit fields, record `scope`/`reviewed_at`, record authority literals, duplicate IDs, non-string evidence refs and missing evidence paths all produced validation errors. The committed registry validates from both its file path and project root with no errors.
- Executable/config files under `docs/architecture/future/` were scanned and rejected, while future Markdown and `tests/**` fixtures retained their explicit allow-list. Boundary names `tests_evil/` and `future_evil/` were scanned rather than skipped.
- UI assignments using `Buy`, `Submit` and control labels were rejected with `PROHIBITED_UI_ORDER_CONTROL`; scalar order URLs in YAML were rejected with `PROHIBITED_ORDER_ENDPOINT`.
- Direct `importlib.import_module("broker_sdk.client")` loads were rejected with `PROHIBITED_BROKER_DEPENDENCY`; `requirements-prod.txt` and `requirements-prod.in` were rejected as manifest dependencies.
- Imported `place_order` and `OrderRouter` symbols were rejected with `PROHIBITED_ORDER_SYMBOL`; an assigned order URL passed to `requests.post(url)` was rejected with `PROHIBITED_ORDER_ENDPOINT`.
- Benign `sort_order = 'asc'` passed without a violation.

## Specification-compliance verdict

**APPROVED**

All six Important findings and the Minor coverage finding from
`task-4-review-1.md` have observable post-fix evidence. Production package
subtrees are scanned, credential suffixes and arbitrary dotenv names are
visited, INI defaults are included, registry authority/schema/reference checks
are enforced, the future allow-list is limited to Markdown, UI labels and
scalar/indirect endpoints are detected, and dynamic imports/imported symbols
and dependency-manifest variants are covered. The committed report and
registry retain false authority values, and the future documents remain
explicitly future-only/no-authority.

## Code-quality verdict

**APPROVED**

The residual changes are scoped to the reviewed bypasses, retain deterministic
relative paths and violation ordering, and have focused regression coverage.
No unrelated source, test, issue status, authority field, broker capability,
credential, endpoint or later-task artefact changed in this review.

## Findings and final decision

No Critical, Important or Minor findings remain in the reviewed Task 4 scope.

**FINAL: APPROVED**
