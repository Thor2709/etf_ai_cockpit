# GitHub Issue synchronisation checkpoint - 2026-07-12

## Authority and scope

The committed local ledgers remain authoritative. This checkpoint mirrors the
actual stable-ID records from `issues/open.md` and `issues/closed.md` into
`Thor2709/etf_ai_cockpit`; it does not close or reopen a local product issue.
`execution_allowed` remains `false` and no product scope or authority changed.

## Inventory and reconciliation

- Local records: 98 total, comprising 77 selected open records and 21 selected
  closed records. Stable IDs are unique in the synchronisation manifest.
- Initial authenticated GitHub inventory: 0 issues.
- Final GitHub inventory: 166 issues. The additional historical records are
  retained; no GitHub issue was deleted.
- Canonical mapping: 98 records, each with one GitHub number, URL, title,
  hidden stable-ID marker and local source checksum.
- Final reconciliation command:
  `.venv\\Scripts\\python.exe scripts/sync_github_issues.py`
- Final reconciliation result: exit 0; local open/closed counts 77/21 equal
  mapped GitHub open/closed counts 77/21; all IDs are unique; all mappings
  have a number and URL; states agree; unresolved duplicates are empty.
- Idempotence read-back: the final dry run reported 98 `unchanged` actions and
  no create, reopen, close or duplicate action.

## Duplicate handling

The first remote apply produced exact stable-ID duplicates while the long
serial GitHub write was being completed. The deterministic marker matcher
selected the issue with the clearest existing history as canonical and issued
66 authorised close actions for exact-marker duplicates; two additional
duplicate records were already closed. The final inventory therefore contains
68 closed historical duplicate records, with no duplicate open issue. No issue
was deleted and no identity was inferred from vague title similarity.

## Durable artefacts

- `issues/github_issue_map.json` - schema 1.1, generated from source commit
  `6fb38b7e39ba3e82f25755d5c8c35f068c355f5d` after the ledger checkpoint was
  recorded.
- `issues/github_issue_sync_report.json` - final apply and reconciliation
  result.
- `scripts/sync_github_issues.py` - deterministic read-only inventory and
  idempotent apply tool; local ledger files are never written by the tool.
- `tests/release/test_github_issue_sync.py` - seven focused tests covering
  stable inventory, authority markers, discussion preservation, duplicate
  handling and newline/idempotence normalisation.

## Contradictions retained for later ledger cleanup

The manifest records, without guessing, the existing source contradictions:
`ISSUE-0067` and `UPDATEV2-0010` have a closed record in `issues/open.md`, and
`ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` have dated historical
open/closed records. The synchroniser applies the latest dated local selection
and keeps the contradiction list in the manifest; it does not rewrite the
authoritative ledgers as part of remote synchronisation.

## Verification evidence

- `.venv\\Scripts\\python.exe -m pytest tests/release/test_github_issue_sync.py -q`
  -> 7 passed.
- `.venv\\Scripts\\python.exe -m ruff check scripts/sync_github_issues.py tests/release/test_github_issue_sync.py`
  -> passed.
- `.venv\\Scripts\\python.exe scripts/sync_github_issues.py --apply`
  -> exit 0; final ledger-refresh pass updated 79 open records, reconciled all
  98 records and kept the 77/21 state counts in agreement.
- `.venv\\Scripts\\python.exe scripts/sync_github_issues.py`
  -> exit 0; 98 unchanged actions; reconciliation passes.

## Ledger refresh after Wave 1 Governance Task 1 - 2026-07-12

- The Task 1 checkpoint in `issues/open.md` changed the authoritative local
  source checksum. The authorised apply run completed with exit 0, 98 records
  unchanged, local counts 77 open/21 closed, matching mapped counts and no
  unresolved duplicates.
- `issues/github_issue_map.json` and
  `issues/github_issue_sync_report.json` now bind the mirror read-back to
  source commit `83cefead67c5e2d834848a4e84fa375a8827d8e3`.
- The final read-only reconciliation completed with exit 0 and 98 unchanged
  actions. No GitHub Issue was created, closed, reopened, deleted or otherwise
  changed by this refresh; the local issue state remains authoritative.
