# Task 22 Step 1 - verification report

## Verification boundary

Ran the approved static, schema, secret, dependency, focused-regression and
full-suite checks available through the fixed `cmd.exe` plus cached CPython
3.12 route. The canonical evidence manifest is
[evidence/final/verification-manifest.json](../evidence/final/verification-manifest.json).
`execution_allowed=false` and `executable_authority=false` are preserved.
Task 22 remains open and blocked; this report does not claim release or issue
closure.

## Files and symbols examined

- `docs/superpowers/plans/2026-07-10-all-41-issues-closure-plan.md` - Task 22 Step 1 command list and manifest contract.
- `scripts/verify_clean_environment.ps1` - existing repository verification conventions (not executed; cmd-only route enforced after repeated host faults).
- `src/etf_cockpit/data/backup_restore.py` - the only high-confidence scan match, which is detector code rather than a credential.
- `evidence/final/verification-manifest.json` - refreshed post-fix command/evidence record.
- `tests/test_backup_restore.py` and `configs/closure_matrix.yaml` - bounded
  Task 22 defect fixes.

## Findings or changes

- Ruff exits 1 with 37 existing E402/F841 findings in scripts; no source fix was authorised or required by this step.
- Mypy, repository-venv compileall and focused official-fixture/data-contract/schema-migration pytest are blocked: the repository venv Python child process is denied by Windows (exit 101). The cached CPython route now supplies pytest and its focused/full-suite results are recorded separately in the manifest.
- The local high-confidence secret scan exits 0 with no credential-value match. The scan found only an implementation detector string in `backup_restore.py`; `logs`, `exports`, `portable` and `package` roots are absent and recorded as unavailable.
- The earlier repository PowerShell clean-environment/secret scan could not run: the
  host crashed before script execution with Windows exception `0xe0434352`
  and `System.UnauthorizedAccessException` resolving the worktree directory.
  The exact evidence is retained in `evidence/final/verification/powershell-crash.txt`.
- A Windows build attempt was also blocked before compilation because the
  batch script could not find `py`/`python` and could not create `.venv`; no
  package artefact was produced. Output is retained in
  `evidence/final/verification/windows-build.txt`.
- Source smoke was attempted with the bundled Python runtime but failed before
  readiness because `flet` is not installed; the complete traceback is in
  `evidence/final/verification/smoke-source.txt`.
- `git diff --check` exits 0.
- The cached CPython 3.12 runtime plus its compatible package archive was used
  for focused and full pytest runs; the full suite is a genuine 20-failure
  result, not a missing-pytest claim.
- The backup metadata regression was reproduced with a genuine RED failure and
  fixed; 10 focused backup/restore tests now pass.
- Five unsupported closure statuses were normalised to `still_open`; the
  closure/release bundle now passes 27 tests without closing any issue.
- The order-control scanner now distinguishes a generic dialog `Cancel` from
  an order-specific `order_cancel_button`; the scope-boundary suite passes 25
  tests, including both regressions. The fresh full suite runs with cached
  dependencies but exits 1 with 20 failures. The exact output is retained in
  `evidence/final/verification/full-suite-final.txt`; package inventory now
  passes, while UI control attachment, missing secondary-universe/data
  fixtures, instrument-detail malformed-input checks and DATA-05 identity
  coverage remain open.

## Evidence

All output digests, exact commands, exit codes, timestamps, linked final-gate criteria and unavailable dependencies are recorded in `evidence/final/verification-manifest.json`.

## Commands or tests run

- `..\\..\\.venv\\Scripts\\ruff.exe check src tests scripts` - exit 1, digest `a9e0c8baedca3fed84b2380984956160b6951c484d1b187322e7672995838124`.
- `..\\..\\.venv\\Scripts\\mypy.exe src\\etf_cockpit\\core src\\etf_cockpit\\parsers src\\etf_cockpit\\data\\contracts.py` - blocked, exit 101, digest `b62cbb87aa1f06aa448083de7643be88ae515c8c488effd5fdd22a353882d8a1`.
- `..\\..\\.venv\\Scripts\\python.exe -m compileall -q scripts src tests` - blocked, exit 101, digest `c6fcc02cc8fc9ee02f79b0ea24c823a897d928812707b93efee5551d808ceacd`.
- `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_official_fixture_manifest.py tests\\test_data_contracts.py tests\\test_schema_migrations.py -q` - blocked, exit 101, digest `163d2576364ddbc30943a0c8c4e7b494cc8946557dc545d1de1120a77bfb2c93`.
- Local `rg` high-confidence secret scan over `src`, `configs` and `evidence` - exit 0, digest `c2ec18837a7f6b9ea4b49c67e3d058dad6b5d6cce57cba983a676aa6bfb847f4`.
- `git diff --check` - exit 0, empty-output digest `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- Bundled compileall - exit 0, empty-output digest
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- Bundled cached `python -m pytest tests/test_backup_restore.py -q` - exit 0,
  10 passed, digest `3a7595f1ed0b8ce91ff11c8a9ea43bcec9d3221574c06e918523636cb091325a`.
- Bundled cached release/closure bundle - exit 0, 27 passed, digest
  `18395083f2cb1e70edeb9bfc9b39da059cb217359d0fe9eaea01cc89e8d751d4`.
- Bundled cached scope-boundary suite - exit 0, 25 passed, digest
  `0861033bdc2d6203bd8178972703a811b101e61fc065ed32dfd1a4824ab482f0`.
- Bundled cached full suite - exit 1, 20 failures, digest
  `84d52e4396e3942b9e2b9cde109e8871b10bb6375fcc349df0beed45487d2c89`.

## Remaining uncertainty and risk

Native runtime, package, browser and type gates remain unavailable. Ruff
findings remain pre-existing and are not silently reclassified as passed.
Secret scanning did not cover absent generated/package roots. DATA-05 remains
open with the separately recorded 16-row identity artefact versus its required
coverage baseline. The backup helper's metadata allow-list is keyed by archive
basename; canonical callers must select the approved metadata roots. This is a
minor non-blocking collision risk recorded for later hardening.

## Independent review status

The first fresh independent review rejected the pre-fix evidence package
because the canonical manifest and report were stale and contradicted the
newly observed checks. The second review also required an adversarial
plain-`Cancel` order-control regression. Both findings are now addressed in
the successor commit and refreshed manifest; a fresh re-review is still
required before integration. No approval is claimed yet.

An in-workspace pip bootstrap for pytest/Ruff/mypy was attempted without
modifying tracked dependencies. The download/install attempt timed out and
produced no artefact, so the missing-runtime blocker remains.

## Recommended next action

Parent agent should continue with Task 22 Steps 3-7 and Task 23 only after
the remaining release blockers are addressed. Do not treat this boundary
report as final issue-closure evidence.

## Reconciliation addendum - 2026-07-14

The Task 22 reconciliation branch was rebuilt from `origin/main` at
`6e6406d58db89ae19398e2abf15d0670e3350560`. The obsolete Task 20 series and
the already-integrated Task 21 implementation were not replayed. The scoped
Task 22 source/configuration changes were transferred file-by-file, preserving
the newer Task 21 complete-audit implementation.

Current staged Task 22 changes:

- `src/etf_cockpit/data/backup_restore.py`: retain explicitly approved
  metadata files under transient backup ancestors.
- `configs/closure_matrix.yaml`: keep five implementation-complete but
  unevidenced records as `still_open`.
- `scripts/build_windows.bat` and `tests/release/test_build_windows.py`:
  cmd-only Windows build path and generated-launcher contract.
- `src/etf_cockpit/governance/static_checks.py` and its boundary tests:
  distinguish generic dialog Cancel from order-specific cancellation.
- `configs/universe.yaml` and `src/etf_cockpit/signals/simple_scores.py`:
  preserve the approved configured secondary/sparebanken coverage and source
  fallback semantics.
- `src/etf_cockpit/core/atomic_io.py`: do not read a live writer journal while
  it is being atomically replaced on Windows.
- `src/etf_cockpit/chatgpt_bridge/export_pack.py`: include every enabled
  configured instrument in the audit allocation and preserve the established
  candle-context unavailable marker.

Fresh focused evidence on the reconciled branch:

- 20 repeated Windows concurrent-writer recovery runs: all passed.
- Operations, trust-critical export, backup/restore, release build contract,
  scope-boundary and simple-score bundle: passed.
- Cached CPython 3.12 `compileall`: passed.
- Cached CPython Ruff invocation: unavailable because the runtime has no Ruff
  module; no substitute result is claimed.
- The pre-existing Task 23 instrument-identity regression remains deferred to
  Task 23 and is not included in this Task 22 boundary.

The branch is not yet integrated or remotely pushed. The independent
reconciliation review is pending. Native/package/browser gates and the fresh
full-suite evidence manifest remain open; no issue is closed and no stale
evidence is treated as current.

## Reconciliation review-fix addendum - 2026-07-14

The first independent reconciliation review identified two Important defects:

1. `configs/universe.yaml` contained five Sparebanken identity/name or ticker
   values that differed from the canonical `SPAREBANKEN_ROWS` fallback. The
   no-candidate and candidate-file loader paths therefore exposed different
   identities.
2. The static boundary scanner excluded `Cancel` from the short order-control
   label rule, so `order_control('Cancel')` was not rejected even though a
   generic dialog `Cancel` must remain permitted.

Tests were added before the production fixes and observed genuine RED failures.
The five YAML identities/ticker values now match the canonical fallback, and
explicit order/trade control calls reject plain `Cancel` while generic dialog
cancel actions pass. The parity and adversarial boundary tests pass, as does
the affected regression bundle. A fresh independent re-review is pending; no
integration or issue closure is claimed.

## Reconciliation review-fix 2 - 2026-07-14

The second fresh independent reviewer found one Important audit completeness
defect: `_audit_portfolio_holdings` used score-eligible `enabled_ids`, omitting
enabled manual-review/research-only instruments from the supposedly complete
audit allocation. A test-first adversarial enabled-manual-review fixture
observed RED. The exporter now iterates the existing
`configured_enabled_ids` interface, preserving explicit zero-weight rows for
all enabled configured instruments. The new regression and existing audit
export test pass. Fresh independent re-review is required before commit.
The existing audit-export assertion was also corrected to derive its expected
population from `configured_enabled_ids`, so the regression cannot share the
score-eligibility filter it is meant to guard.

The third independent review found an Important fidelity defect: an enabled
manual/research-only instrument that was genuinely held but absent from target
positions would be emitted with zero current weight. A test-first non-zero
holding regression observed RED. `_audit_portfolio_holdings` now receives the
canonical holdings frame, preserves the untargeted holding's current weight and
derives its drift against a zero target; `export_review_pack` passes the frame
through. The regression and audit archive tests pass. A fresh independent
re-review is required before commit.

## Reconciliation review-fix 4 - 2026-07-14

The fresh re-review found that the service path filtered holdings to the
score-eligible `enabled_ids` before the audit exporter received them. A
service-level RED test reproduced loss of a non-zero configured manual holding.
`_build_snapshot` now retains holdings using `configured_enabled_ids` while
prices and scoring remain bounded by `enabled_ids`; the service-path regression
passes.

The same review found that canonical Sparebanken verified ISINs were absent
from the YAML identity rows and the parity test did not compare ISINs. The
verified canonical ISINs were added to `configs/universe.yaml`, the candidate
loader now preserves the established `needs_verification` marker for unknown
ISINs, and parity compares name, ticker and ISIN across both loader paths.
The parity test and existing score/UI marker regressions pass. A fresh
independent post-fix review is pending.

## Verification environment note - 2026-07-14

The ambiguous-news atomic group regression passes in the original short-path
Task 22 worktree but fails in this long-named reconciliation worktree with
Windows `WinError 3` during `Path.replace` under the pytest temporary root.
The failure is path-length/environment-specific and is not changed by the
Task 22 atomic recovery diff. It remains an explicitly unverified check for
this worktree and is not used as closure evidence.

## Reconciliation review-fix 5 - 2026-07-14

The post-fix reviewer identified that retaining the literal
`needs_verification` marker in `ETFConfig.isin` made it a false shared
identity in `DataService._reference_context`, collapsing unresolved records
onto one map entry and risking document validation against a placeholder.
The YAML and candidate loader paths now represent unresolved ISINs as
`None` while preserving `isin_status="needs_verification"`; pending score
rows render the established marker for users. A RED reference-context test
and the loader/score regressions passed after the fix. Fresh independent review
is required before commit.

## Independent post-fix review - 2026-07-14

A fresh independent reviewer approved the staged reconciliation checkpoint
for specification compliance and code quality with no Critical or Important
findings. The reviewer confirmed that configured manual holdings survive the
real snapshot path, untargeted non-zero weights reach the audit packet,
Sparebanken loader identity is equal across candidate/no-candidate paths,
unresolved ISINs are not reference identities, atomic live-owner recovery is
safe, and execution authority remains disabled. Readiness is approved for an
explicitly incomplete Task 22 checkpoint only; package, browser, full-suite
and environment gates remain open and no issue closure is claimed.

The reviewer used the available high-capability fallback context after the
preferred independent-review model was capacity-limited. No Git writes were
performed by the reviewer.

## Full-suite verification - 2026-07-14

Fresh cached-Python full-suite command: `python -m pytest -q --tb=short`.
Result: 11 failures, all recorded as pre-existing or environment/deferred
outside Task 22: the accessible Flet table test fails before page attachment;
the ambiguous-news group write fails with the long-worktree Windows path
`WinError 3` (the same test passes in the original short-path worktree); and
the remaining nine failures are Task 19 instrument-detail fixtures/behaviour
not owned by this reconciliation. The Task 22 focused bundle remains green;
no Task 22 regression is attributed from this full-suite result.
