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

## Ledger refresh after Wave 1 Governance Task 2 - 2026-07-12

- The Task 2 checkpoint updated the authoritative local source checksums. The
  deterministic synchroniser was rerun after the PR 172 merge; local counts
  remain 77 open and 21 closed, matching the mapped remote state, with no
  unresolved duplicates.
- No GitHub Issue was created, closed, reopened or deleted by this refresh.
  The local issue ledger remains authoritative and Task 2 does not close any
  governance issue.
- Apply command exit 0: 70 canonical records were unchanged and 28 managed
  bodies were refreshed against the new source checksum. The read-only dry
  run then exited 0 with 98 unchanged actions. Reconciliation passed with 77
  open and 21 closed records, states agreeing and no unresolved duplicates.
  The map/report source commit is `6df20ef1f56306dc49e4b520f1905056e98634d6`.
- No GitHub Issue was created, closed, reopened or deleted. The next sync is
  required after the next local issue-ledger transition or closure-evidence
  update.

## Ledger refresh after Wave 1 Governance Task 3 - 2026-07-12

- The Task 3 checkpoint updated the authoritative local source checksum. The
  authorised apply run completed with exit 0 and refreshed managed GitHub
  bodies; local counts remain 77 open and 21 closed, matching mapped counts.
- The read-only dry run completed with exit 0; reconciliation passed with all
  98 local IDs unique, every mapping valid, states agreeing and no unresolved
  duplicates. No GitHub Issue was created, closed, reopened or deleted.
- `issues/github_issue_map.json` and `issues/github_issue_sync_report.json`
  bind the mirror read-back to source commit
  `5fde19639da9caa6cdb01eef852dc34698b53482`. The local issue ledger remains
  authoritative and no issue state changed.

## Ledger refresh after Wave 1 Governance Task 4 - 2026-07-12

- The Task 4 checkpoint updated the authoritative local source checksum. The
  authorised apply run completed with exit 0 and refreshed managed GitHub
  bodies; local counts remain 77 open and 21 closed, matching mapped counts.
- The read-only dry run completed with exit 0 and 98 unchanged actions;
  reconciliation passed with all local IDs unique, every mapping valid, states
  agreeing and no unresolved duplicates. No GitHub Issue was created, closed,
  reopened or deleted.
- `issues/github_issue_map.json` and `issues/github_issue_sync_report.json` bind
  the mirror read-back to source commit
  `f962072fe22797e29f64ae37e9696c7de0a4b56e`. The local issue ledger remains
  authoritative and no issue state changed.

## Ledger refresh after Wave 1 Governance Task 5 - 2026-07-12

- The Task 5 checkpoint updated the authoritative local source checksum. The
  authorised apply run completed successfully and refreshed managed GitHub
  bodies; local counts remain 77 open and 21 closed, matching mapped counts.
- The read-only reconciliation run completed with 98 unchanged actions;
  all local IDs are unique, every mapping is valid, states agree and there are
  no unresolved duplicates. No GitHub Issue was created, closed, reopened or
  deleted.
- `issues/github_issue_map.json` and `issues/github_issue_sync_report.json`
  now bind the mirror read-back to the Task 5 ledger refresh. The local issue
  ledger remains authoritative and no issue state changed.

## Ledger refresh after Wave 3 Task 7 - 2026-07-12

- The Task 7 checkpoint and source checksum were synchronised with the
  authenticated `Thor2709/etf_ai_cockpit` mirror. The authorised apply run
  exited 0 with 98 unchanged actions; no GitHub Issue was created, closed,
  reopened or deleted.
- Reconciliation passed: 98 unique local IDs, 77 open and 21 closed locally,
  matching 77/21 mapped GitHub states; all mappings are valid and unresolved
  duplicates are empty.
- `issues/github_issue_map.json` and `issues/github_issue_sync_report.json`
  bind the mirror read-back to source commit
  `d40f1d37ad886b23373af64967a1b8dabc246741`. The local issue ledger remains
  authoritative and `ISSUE-0011`, `ISSUE-0040` and `ISSUE-0039` remain open.

## Ledger refresh after Wave 3 Task 8 - 2026-07-12

- The Task 8 checkpoint and reopened/partial `UPDATEV2-0010` ledger state were
  synchronised with authenticated `Thor2709/etf_ai_cockpit` after PR 178 was
  merged. The authorised apply run exited 0 with 98 unchanged actions; no
  GitHub Issue was created, closed, reopened or deleted during this refresh.
- Reconciliation passed: 98 unique local IDs, 77 open and 21 closed locally,
  matching 77/21 mapped GitHub states; all mappings are valid and unresolved
  duplicates are empty.
- `issues/github_issue_map.json` and
  `issues/github_issue_sync_report.json` bind the mirror read-back to source
  commit `c80cb0d34d81f36f1a2729744c13d5350fae9243`. The local issue ledger
  remains authoritative; `UPDATEV2-0010` is open/partial pending its complete
  closure dossier.

## Ledger refresh after Wave 4 Task 9 - 2026-07-12

- Following the Task 9 merge and the durable local checkpoint commit
  `b48098e`, the authenticated apply run exited 0 with 98 unchanged actions;
  no GitHub Issue was created, closed, reopened or deleted.
- The read-only reconciliation run also exited 0 with 98 unchanged actions.

## Task 13 synchronisation - 2026-07-13

- Applied `python scripts/sync_github_issues.py --apply` after the Task 13
  integration checkpoint; the final run reported 98 canonical records, local
  open/closed counts 77/21, mapped counts 77/21, agreeing states and no
  unresolved duplicates.
- `UPDATEV2-0013` remains mapped to GitHub Issue #153, OPEN, with its local
  implementation-complete/closure-pending status and current source checksum.
- No issue was closed because strict package, audit/export, clean-first-run
  and browser/computer-use evidence remains outstanding. The local ledger and
  approved specification remain authoritative.
  It proves 98 unique local IDs, 77 open and 21 closed records locally,
  matching 77/21 mapped GitHub states; all mappings are valid, states agree,
  and unresolved duplicates are empty.
- `issues/github_issue_map.json` and
  `issues/github_issue_sync_report.json` bind the mirror read-back to source
  commit `b48098e`. The local ledger remains authoritative: `ISSUE-0011` and
  `ISSUE-0021` are open/partial pending their remaining closure gates, while
  `UPDATEV2-0022` remains closed and was not reopened.

## Ledger refresh after Wave 4 Task 12 - 2026-07-13

- After PR 182 merged Task 12 and the local checkpoint was committed, the
  authenticated `python scripts/sync_github_issues.py --apply` run exited 0.
  Five managed bodies were refreshed, with no duplicate actions, issue
  creation, deletion or state transition.
- Reconciliation passed: 98 unique local IDs, 77 open and 21 closed locally,
  matching 77/21 mapped GitHub states; all mappings have valid issue numbers
  and URLs, states agree and unresolved duplicates are empty.
- The synchronisation manifest and report bind the read-back to commit
  `1bf453cc3d6a3dc244b7a6cf9760cb195f1771dd`; the subsequent sync artefact
  commit is `b932dc879ec7822b1af14891dfadff337bb86d65`.
- `UPDATEV2-0012` remains open/implementation-complete pending package,
  browser, clean-first-run and configured live SEC-network evidence. The local
  issue ledger and approved specification remain authoritative.

## Ledger refresh after Wave 4 Task 14 - 2026-07-13

- After PR 184 merged Task 14 and the local implementation checkpoint was
  committed, the authenticated `python scripts/sync_github_issues.py --apply`
  run exited 0. It reported 98 canonical records, 77 local open and 21 local
  closed records, matching 77/21 mapped GitHub states; all IDs were unique,
  mappings valid, states agreed and unresolved duplicates were empty.
- `UPDATEV2-0015` remains mapped to GitHub Issue #155 OPEN and `UPDATEV2-0016`
  remains mapped to GitHub Issue #156 OPEN. Both bodies now mirror their local
  implementation-complete/closure-pending status; no issue was closed because
  strict package, audit/export, clean-first-run and browser/computer-use evidence
  remains outstanding.
- The updated `issues/github_issue_map.json` and
  `issues/github_issue_sync_report.json` are the deterministic mirror evidence;
  the committed local ledger and approved specification remain authoritative.

## Ledger refresh after Wave 4 Task 15 - 2026-07-13

- Authenticated `python scripts/sync_github_issues.py --apply` completed after
  the Task 15 ledger checkpoint. Reconciliation remains 98 canonical records,
  77 local open and 21 local closed records, with matching mapped GitHub
  states, unique local IDs, valid URLs and no unresolved duplicates.
- `UPDATEV2-0017` maps to GitHub Issue #157 OPEN and `UPDATEV2-0019` maps to
  GitHub Issue #159 OPEN. Their managed bodies now state implementation
  complete/closure pending; no issue was closed because strict release,
  audit/export, clean-first-run and browser/computer-use evidence remains
  outstanding.
- The committed local ledger and approved specification remain authoritative;
  GitHub Issues are synchronised project-management representations.

## Ledger refresh after Wave 4 Task 16 - 2026-07-13

- Authenticated `python scripts/sync_github_issues.py --apply` completed with
  exit 0 after the Task 16 checkpoint commit `4f765b4`. It reported 98 canonical
  records, 77 local open and 21 local closed records, matching 77/21 mapped
  GitHub states; all local IDs were unique, mappings valid, states agreed and
  no duplicate action was required.
- `ISSUE-0023` maps to GitHub Issue #27 OPEN, `ISSUE-0025` to #29 OPEN,
  `ISSUE-0054` to #113 OPEN and `ISSUE-0055` to #115 OPEN. Their managed
  bodies mirror the local implementation-complete/closure-pending status; no
  issue was closed because strict release, package, audit/export,
  clean-first-run and browser/computer-use evidence remains outstanding.
- `issues/github_issue_map.json` and `issues/github_issue_sync_report.json`
  are the deterministic mirror evidence. The report records the same known
  historical ledger contradictions for ISSUE-0067, ISSUE-0069, UPDATEV2-0010,
  UPDATEV2-0022 and UPDATEV2-0028; reconciliation still passes because the
  dated/latest-state resolver agrees with the mapped states. The committed
  local issue ledger and approved specification remain authoritative.

## Ledger refresh after Wave 4 Task 17 - 2026-07-13

- Authenticated `python scripts/sync_github_issues.py --apply` completed with
  exit 0 after PR 187 merged Task 17. The run reported 98 canonical records,
  77 local open and 21 local closed records, matching 77/21 mapped GitHub
  states; all local IDs were unique, mappings valid, states agreed and no
  duplicate action was required.
- `ISSUE-0067` maps to GitHub Issue #137, `ISSUE-0034` to #80 and
  `ISSUE-0047` to #99. Their managed bodies mirror the local
  implementation-complete/closure-pending status; no issue was closed because
  strict package/browser, audit/export and clean-first-run evidence remains
  outstanding.
- `issues/github_issue_map.json` and `issues/github_issue_sync_report.json`
  are the deterministic read-back evidence. The known historical contradiction
  for `ISSUE-0067` remains recorded by the resolver; reconciliation passes.
  The committed local issue ledger and approved specification remain
  authoritative.

## Ledger refresh after Wave 5 Task 18 - 2026-07-13

- Authenticated `python scripts/sync_github_issues.py --apply` completed with
  exit 0 after PR 188 merged Task 18. The run reported 98 canonical records,
  77 local open and 21 local closed records, matching 77/21 mapped GitHub
  states; all local IDs were unique, mappings valid, states agreed and no
  duplicate action was required. It applied 79 managed updates and left 19
  records unchanged.
- `ISSUE-0052` maps to GitHub Issue #109, `ISSUE-0059` to #123 and
  `ISSUE-0064` to #132. Their managed bodies now mirror the local
  implementation-complete/closure-pending status; none was closed because
  strict release/package, audit/export, browser/computer-use and clean-first-
  run evidence remains outstanding.
- `issues/github_issue_map.json` and `issues/github_issue_sync_report.json`
  are the deterministic read-back evidence. Reconciliation passes with no
  unresolved duplicates. The committed local issue ledger and approved
  specification remain authoritative.

## Ledger refresh after Wave 5 Task 19 - 2026-07-13

- Task 19 merged through PR 189 at `da271bc` with implementation head
  `89f4644`. `ISSUE-0019` remains open because strict release/package,
  audit/export, browser/computer-use, keyboard/focus/responsive and
  clean-first-run evidence is not yet fresh.
- The next synchronisation run is required after this durable ledger update;
  the local issue ledger remains authoritative and GitHub Issue #23 must stay
  open with the managed implementation checkpoint.

## Ledger refresh after Wave 5 Task 20 - 2026-07-14

- Task 20 merged through PR 190 to GitHub `main` at
  `61f6aa3144d5d1eb28d57052c09a88acb5529bcc` after final independent review.
  `ISSUE-0036`, `ISSUE-0041`, `ISSUE-0042` and `ISSUE-0044` remain open with
  implementation-complete/closure-pending status; none is eligible for closure
  until strict runtime, package, audit/export, browser/computer-use and
  clean-first-run gates are fresh.
- The normal local sync script cannot be rerun in this environment because the
  local Git credential helper fails with `SEC_E_NO_CREDENTIALS`; the
  authenticated GitHub connector was used for PR creation and merge. The prior
  mapping/report therefore remain the last complete local reconciliation, and a
  post-checkpoint issue-body refresh is pending credential restoration.
- The local ledger and approved specification remain authoritative. No issue
  state was silently changed and no GitHub issue was deleted.
