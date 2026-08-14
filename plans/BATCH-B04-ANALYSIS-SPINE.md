# B04 Analysis Spine

The durable active objective, protected boundaries and exact continuation
checkpoint are maintained in `plans/ACTIVE_CODEX_GOAL.md`; read it before
continuing this batch.

Current delivery mechanics are defined in
`docs/product-completion/DELIVERY_WORKFLOW.md`. Historical references below
to sole workers, Sol-low workers or old lifecycle PR chains describe past
execution and are not current operational instructions.

## Current ISSUE-0016 product lane

ISSUE-0015 product PR #669 and lifecycle PR #670 are merged through exact main
`6fe3b410395d14593f9a9b67fd5180e68e862e9a`. Exact-head review and run
`31380194815` passed Linux, Windows and terminal validation. Ordered writer
`31382654403` applied and verified the sole ISSUE-0015 status update with
`zero_action_readback=true`; generic convergence `31382654316` and a fresh
exact-main readback are zero action, and `execution_allowed=false` remains.

ISSUE-0016 is now selected as the next canonical implementation-order issue.
It is P1, dependency-ready and activation-ready with no blocking dependencies.
Clean branch `codex/issue0016-product-20260810` starts at exact main
`6fe3b410395d14593f9a9b67fd5180e68e862e9a`. Its bounded scope is the required
task-oriented frontend-v2 navigation across Home, Discover, Instrument,
Portfolio, Models, Backtest/Paper, Data Health, Audit and Settings, including
search and command palette. Current exact-main inspection and focused tests
confirm PR #371 already satisfies that product contract; independent read-only
criterion review found no reproducible gap, so no speculative product code is
added. The sole lifecycle transaction is `implemented_initially -> integrated`
with one-update plan
`3a45c6c3892f1a74d52fcad082ec65beeacf95d5cff73b50b5ead7a72023fdaf`,
candidate authority
`b34e62fd600f7baa7ed389a61af6803ac4cf0ad788721df508b011d1fb4ee433`
and append-only sequence-21 authority
`d8f48eb20e9b83a1e992ba8803199b65b39561c22221aaa73b2bd5a309c6207c`.
Generator/check mode, registry validation and status guard pass with
`execution_allowed=false`; freeze for both exact-head reviews and hosted
validation, then require writer acceptance and generic zero-action readback.

## Superseded ISSUE-0015 product lane

ISSUE-0014 lifecycle PR #668 merged exact reviewed head
`827225cb3b5f5f509dc024c713d9fa93efa35ad0` as exact main
`830a00a84eebdb26e1099f3cb003898e9b0ceab2`. Writer `31369949128` applied and
verified the sole aggregate two-hop replay with `zero_action_readback=true`;
generic convergence `31369949140` and the fresh exact-main plan are zero action,
reconciliation projects `integrated`, and `execution_allowed=false` remains.

ISSUE-0015 is the next canonical implementation-order, dependency-ready issue.
Clean branch `codex/issue0015-product-20260810` rebases the prepared product
checkpoint onto that exact main. Its four-file scope completes the existing
`/roadmap` page by requiring complete, consistent canonical registry,
readiness, dependency-edge and closure evidence, failing closed on malformed or
partial inputs, retaining separate implementation/release/data/model/paper/live
dimensions and preserving `execution_allowed=false`. Focused programme-map/UI
tests, Ruff, compile and diff hygiene pass. Complete exact-head classification,
lifecycle preparation, parallel whole-diff/risk review and required hosted CI
before merge; then require writer acceptance and generic zero-action readback
for the legal `implemented_initially -> integrated` completion.

First frozen head `05d73bb1ccef2eba3a6a378707dc1dd1f5a640cc` is rejected and
its hosted evidence is stale. After both verdicts were collected, the combined
finding set is: flipped/inconsistent implementation or activation edge evidence
can overstate readiness, and a whitespace canonical ID can escape fail-closed
loading through `StopIteration`. The single consolidated correction derives and
compares the complete readiness projection against canonical ledger and reviewed
edge evidence, rejects malformed IDs consistently, and adds focused regressions.
Run focused validation once, freeze one replacement head and repeat both reviews
plus tier-O hosted validation in parallel.
Both replacement reviewers rejected head
`cb6255ebfa1505fd3b793c2d7c80cd182feb313f` for one newly demonstrated
parity gap: reviewed edge dates were not constrained to canonical
`YYYY-MM-DD`. The sole follow-up adds that exact check and regression without
changing lifecycle, dependencies or authority.
Both reviewers then rejected `a90182bf7674c3409446f31f4a4eac0ac71fd76a`
for accepting IDs, unknown dependencies, local-only closure and missing edge
records that canonical validation rejects. The exact bounded closure enforces
the existing ID/reference/edge-coverage invariants and adds their fail-closed
regressions without changing workflow, lifecycle or execution authority.
Reviewers rejected `b0266a75add96621258f0cdb5a6d47c9a6bda63c` for the remaining
partial-record inputs: omitted authority fields, normalized/duplicate
references, impossible dates, required-input mismatch and absent status. The
single combined closure requires those existing raw fields and values exactly
and adds their fail-closed regressions; canonical state and authority remain
unchanged.
Reviewers rejected `2858b94e0fcf820ecbf8e91ac5c6500d8439520a` for the final
record/graph parity set: required typed metadata and phase/priority, strict
unresolved evidence, self/cycle rejection and generated reverse links. The
bounded closure mirrors only those existing canonical checks and adds focused
probes; lifecycle, workflow and authority are unchanged.
Whole-diff review approved `3296ebb707f82728bcd43efa34cc42e3b3d57bba`;
risk review found only unbound declared record counts and default JSON
last-key-wins parsing. The exact follow-up validates both existing count fields
and rejects duplicate keys at every JSON object depth, with focused probes.
Whole-diff review approved `7947d6fd65d5b0cb04b1385b90c1b9fc8fb127a0`;
risk review reproduced one final type gap where JSON `true` could satisfy the
count for a jointly truncated one-record registry. The consolidated correction
requires exact integer counts and adds boolean/fractional regressions. Focused
roadmap/UI tests, Ruff and diff hygiene pass; repeat both reviews and fresh
tier-O hosted validation on one replacement head.
Replacement head `406408c8c70f3938000499fbecf672d3faf48e76` passed 46 focused
tests, Ruff and diff hygiene, both exact-head reviews and tier-O run
`31378744478`; PR #669 merged it as exact main
`70cf36d6be6033c1ffa6ab9cfa71204fe68ca8c8`. Clean lifecycle branch
`codex/issue0015-lifecycle-20260810` records only the legal direct
`implemented_initially -> integrated` transition, mechanical projections,
single-update plan `80858ee7873d8b479280e635575e351b96c377a7eb9736249d16a778ab401c7b`,
status candidate and append-only sequence-20 authority. Run exact E-tier guards
and review before merge, then require writer and generic zero-action readback;
`execution_allowed=false` remains unchanged.

## ISSUE-0018 product lane — 2026-08-11

`VERIFIED` ISSUE-0017 lifecycle PR #673 merged reviewed head
`7e664542fdeea154cbca2c999334a3be565fb515` as
`9c3ac836587d3e2b494bca20e27b559978eb8c9b`. H-tier run `31453379949`,
status guard `31453379906`, writer `31455074038` and generic convergence
`31455074057` passed; the writer applied only GitHub issue #21 and both hosted
and independent exact-main readbacks returned zero actions.

`IN_PROGRESS` ISSUE-0018 is dependency-ready. Product lane
`codex/issue0018-product-20260811` starts from exact main
`9c3ac836587d3e2b494bca20e27b559978eb8c9b`; implementation checkpoint
`b80967bb956b083f7033aba4ae1c9ac6de3d228e` adds only local import parsing,
identity/classification evidence, immutable-source correction overlays,
versioned manifests, exclusions/horizons/quotas, cancel-safe chunk resume, the
Universe Manager wizard and focused tests. It performs no hidden provider,
analysis, workflow or broker action and keeps `execution_allowed=false`.

The focused import/store/manager/architecture suite, Ruff, compile and diff
hygiene pass. Freeze the fully documented head for parallel whole-diff and risk
review plus fresh H-tier Linux/Windows/terminal validation. Prepare every legal
lifecycle artifact before product merge; after the reviewed product commit is
merged, bind the single ISSUE-0018 `implemented_initially -> integrated`
transaction to that PR/commit and require writer success plus generic
zero-action readback.

`CONSOLIDATED_IMPORT_INTEGRITY_CORRECTION` both reviews rejected PR #674 head
`62d6103cd013dd325ad8bbdc794d6ea92f4f9baa`; hosted run `31455384153` also
failed the missing UI acceptance contracts and skipped package jobs. Commit
`5e89f7b15a8c1264518c36443772b1c5f53d6373` corrects explicit ISIN authority,
resume/report binding, normalized lifecycle flags, manifest-failure isolation,
duplicate input fields, bounded XLSX parsing, identity-only staging behavior,
completed-state cancellation, overlay bounds and excluded-row classification.
It also adds the six UI contracts and the narrow exact persistent-module H-tier
classifier rule. Focused tests pass with one expected capability skip;
preflight, UI inventory, Ruff, compile, diff hygiene and generator checks pass.
Freeze one replacement head and repeat both reviews plus fresh hosted H-tier
Linux, Windows and terminal validation. `execution_allowed=false` is unchanged.

`FINAL_IMPORT_FAIL_CLOSED_CORRECTION` both reviewers rejected replacement head
`e766016eccf6415323a06ff5cd3b364146a6b614` for newly reproduced malformed
boolean, normalized/persisted JSON collision, provider-transport, aggregate
XLSX-envelope and redirected manifest-path gaps. Run `31457631651` is cancelled
and stale. Commit `5bbd8204d04005ff4855f9f07674d0bcb05f4d8a` closes the
complete set in the import module and adds exact regressions. Import/store,
Ruff, compile, diff-hygiene and generator checks pass with one existing
platform-capability skip. Freeze one final replacement head for both reviews
and fresh H-tier Linux/Windows/terminal evidence; do not add adjacent hardening.

`BOOLEAN_ALIAS_CONFLICT_CORRECTION` risk review rejected exact head
`009610ecf3a5aff4bd9508e9dcaf225527f3e544` after reproducing contradictory
valid boolean aliases; run `31459084752` is cancelled and stale. Commit
`fcd44eb0eb103944bdff3bf8d8ae90c3b8dfb42b` rejects disagreement across all
six alias pairs. All 45 import regressions plus Ruff, compile and diff hygiene
pass. Freeze the documented replacement for both exact-head reviews and fresh
H-tier Linux/Windows/terminal evidence. `execution_allowed=false` is unchanged.

`MANIFEST_DESTINATION_GUARD_CORRECTION` risk review approved head
`61ea71394e6b2cc3725d6ee1aba210d394a24dbf`, but whole-diff review found the
manifest destination identity check was not repeated through the existing
atomic precondition under held group guards. Run `31460776868` is cancelled and
stale. Commit `33f31a3d3e9cd025da38c4fc94f5ea380ef51b7d` applies that
existing pattern with a deterministic redirect-race regression. All 46 import
regressions, Ruff, compile and diff hygiene pass. Freeze for both exact-head
reviews and fresh H-tier evidence; `execution_allowed=false` is unchanged.

`RAGGED_CSV_CORRECTION` whole-diff review approved head
`d74e32e6e655ff639587c9fe18f0ba211c7624fa`; risk review verified the guard
closure and reproduced one independent parser defect where ragged CSV rows
discarded trailing fields. Run `31461743133` is cancelled and stale. Commit
`7b899a71830e483f453cc254d5470fdac6a06755` requires exact header width for
every non-empty row. All 48 import regressions, Ruff, compile and diff hygiene
pass. Freeze for both exact-head reviews and fresh H-tier evidence.

## ISSUE-0017 lifecycle completion — 2026-08-11

Product PR #672 merged reviewed head `52cadf44abff48ff09cd23cf792acad64dbab94e`
as `3845aaa10a1e0718bc62e4a6698658ce6cd0326a` after H-tier run
`31450653397` passed the authoritative Linux, Windows and terminal gates and
both exact-head reviews approved. The dedicated lifecycle transaction permits
only ISSUE-0017 `implemented_initially -> integrated`. Live plan
`48d98a6e297123958fa4f8c1f87e5837023664bb477f5e560bad44eaf56dd4ce`
contains one programme-status update for GitHub #21 and no other action;
authority sequence 22 binds that plan to the exact product merge. After merge,
require ordered writer `applied_and_verified`, zero-action readback, generic
convergence and unchanged `execution_allowed=false`, then start ISSUE-0018.

## Superseded ISSUE-0014 validation repair

PR #665 remains frozen at independently approved exact head
`5ef8429547a36b6e127a142bb4e81b2e07f35fc6`. H-tier run `31345050975`
passed every authoritative package and platform pilot, but aggregation rejected
the intentional Linux-pass/Windows-skip outcome of the POSIX memory-limit
parser test because that exact contract was missing from its platform
allowlist. Isolated branch `codex/pilot-platform-outcome-repair-20260810`
starts at exact main `c8a7da624c97f1a04191fd3ad1b7880bca83feec` and adds only the
exact outcome/lane rule and fail-closed regression. Review and full H-tier
validation precede merge; PR #665 must then be rebased and revalidated once.
Canonical lifecycle and `execution_allowed=false` remain unchanged.
Both first-head verdicts were collected: risk review approved
`9495b4eb5b26c2eec894fdbcc1d4b1b9b2070da6`, while whole-diff review
rejected only its self-referential predicate test. Run `31349420262` was
cancelled and is stale. The consolidated correction hard-codes the exact test
and lanes, exercises complete aggregation, and proves rejection of an extra
lane, reversed outcomes and an unrelated test. Focused validation passes;
whole-diff re-review approved replacement head
`218b412804d128dac1b0cc5b0831da46a3738103`, but risk review demonstrated
that a partial subset of the required three-lane signature still passed. Run
`31349890546` is cancelled and stale. The final correction requires equality
with the complete observed lane set and adds one full-path regression per
omitted lane; freeze one final head for both reviews and H-tier validation.
Whole-diff review approved `4ce827bec114bf340be7b92b2a02829cfc30843f`,
but risk review reproduced a complete first repetition masking a partial second
repetition because lanes were unioned across samples. Run `31350158760` is
cancelled and stale. The exact correction enforces the complete lane signature
per affected repetition and adds that second-repetition omission regression;
both final reviewers approved exact head
`1af5bc4f9361e0100994fcfc0d5116a0d10768e2`. H-tier run `31350660155`
passed both packages, terminal validation, both repeated pilots and aggregation;
PR #666 merged it as main `784d10fe5e1d4c2a602e5a5cf5485379d50da924`.
PR #665 incorporates that exact main through commit
`599f5a4e81e453916e4cdcf3320d1929aded3449` with product and lifecycle state
unchanged. Run coupled checks, then freeze one replacement product head for
both reviews and fresh H-tier validation. `execution_allowed=false` remains.
Replacement head `aee786ec7d1bf127864d1a2b84346427844019e9` received whole-diff
approval, while risk review reproduced an unpinned yfinance reference-data
clock. Run `31354453616` is cancelled and stale. The one consolidated
correction pins the same fixed date for metadata and holdings and proves the
committed and audit-packet provenance dates; focused validation, both reviews
and fresh H-tier validation are required on one replacement head.

## Current ISSUE-0010 product lane

ISSUE-0104 completion PR #656 merged independently approved exact head
`2e183215d64ba7cdb3bf1dc649bfeca62eb9dad5` as
`43b7561b910758aafe7c5501803fbcbe86fd197b`. Exact-head release run
`31265876805` passed authoritative Linux, Windows and terminal validation and
guard `31265876806` passed. Writer `31267257715` applied the aggregate
`in_progress -> implemented_initially -> integrated` replay with one proposal
and receipt and zero-action readback; convergence `31267257761` and a fresh
generic readback are zero-action. Canonical state and GitHub issue #244 agree
on `integrated`; `execution_allowed=false` remains.

ISSUE-0010 is the next dependency-ready issue. Clean branch
`codex/issue0010-product-20260809-v3` starts at that exact main. The first
prepared head `ede07a26d6556e0caff79a78ecb10aa935f3fbcf` passed focused tests
but both parallel reviews rejected it for cross-process lost updates,
future-observation replay, inexact prompt provenance, stale lifecycle UI,
unsafe redaction export, missing behavioral financial non-interference proof
and incorrect non-H classification. Consolidated correction
`f535c0dec6285de2a31a4b515fd83f907b8eadc1` passed focused adversarial
validation and was transplanted once without conflict. Canonical inputs now
record only `planned -> in_progress`; generated projections are byte-clean.
The one-action live plan is
`e85ef463b0ec18b3b33ffdbf20c449fc26915d302bf66a6f0e8014aa80db782f`,
authority is
`52a917e9e678729a974545b08dc8ef74abe6079168af8270dd430d9b2e262e80`,
candidate ref is
`6741dbdac63e87a11dc6671e305bf04d623e72cd91b03fb45c23d9a78418e4ee`,
and `execution_allowed=false`. Focused adversarial tests, exact guard,
byte-clean generation, H-tier classification and exact one-action candidate
validation pass. Freeze this completed tree for parallel review and H-tier CI.

Frozen head `b3afaa2ab790e13af439e4db5f7fb883d9224cfb` was rejected by
both reviews for current-time future-event leakage, redaction disclosure,
partial multi-instrument writes and unbound exact provenance. H run
`31269127682` timed out preflight before packages because two changed broad
tests took 65 and 109 seconds. Consolidated correction
`d28da1de5c367a85077cfda333730c3b2d6a25c9` closes the full finding set,
restores those broad tests to base and moves only the new assertions into fast
ISSUE-0010 modules. The resulting exact Windows changed-test selection passes
in 42.3 seconds. Replacement head
`f1462202e8630cb6f41623a59ac4e0ed9575ea3d` passed exact guard/candidate and
focused validation, but both parallel reviewers rejected it after all verdicts
were collected: response availability was backdated to snapshot time and
immutable entry/packet validation did not independently recheck exact semantic
provenance. Release run `31270403242` is stale. One consolidated four-file
correction now binds stable generation availability to creation and decision
time, retains snapshot time separately, revalidates request/model/raw response
and parsed commentary at immutable boundaries, and adds focused replay,
mismatch and retry regressions. Head
`e8a122f00bba59712a3afb010edddcda84142744` passed 37 exact changed tests in
41.8 seconds and all control checks, but both parallel reviewers then found the
final bounded boundary set: mutable caller-context timestamp reuse, malformed
synthetic/redaction markers, and missing packet chronology/unique-event
validation. Release run `31271660658` is stale. The permitted final correction
keeps availability on the immutable response status and passes it through the
UI save path, requires strict provenance and fully scrubbed redaction shapes,
and reuses complete store event invariants for packet replay. Head
`d83b691c5cfd3d449a002726013296ce2969d917` passed 46 exact changed tests in
44.5 seconds and all control checks, but adversarial exact-head review then
demonstrated save-context/request-context mismatch, post-cutoff event leakage
from safe exports and future-dated evidence acceptance. Release run
`31273205539` is stale. The final bounded correction deep-copies and requires
the immutable generation context for every exact save, filters safe exports to
the effective cutoff while rebuilding chains/checksums, and rejects recognized
snapshot observations after decision time. Focused mutation/retry,
future-payload/readback and future-evidence regressions pass. Head
`3c702a546e85b0f03225885e5ef58fa42f3471de` passed exact validation, but
review then reproduced nested future metadata, a retroactively backdated expiry
payload and exact availability before the required snapshot date. The bounded
closure recursively checks recognized temporal fields in dictionaries/lists,
requires an ISO snapshot date for exact contexts and rejects expiry before its
event time. Focused regressions pass. Exact head
`79ec77ba659659dfee8fba54d764c6a93daa3af7` received both independent
approvals, but H run `31275348236` failed identically on both platforms because
the existing malformed-transition fixture still used obsolete ISSUE-0010
`in_progress -> ready`, masking its intended malformed-field checks. The
test-only correction derives the legal next hop before injecting each invalid
field; all seven cases pass. Replacement head
`6b5a00b34e6d5c992c5a182428b3df648a704489` received both independent
approvals and passed the exact guard, but H run `31276736844` timed out the
exact changed-test selection at 120 seconds on both its initial attempt and
single permitted retry; authority preflight and supply-chain checks passed.
The one bounded test-only correction retains all seven independent malformed
event checks and runs the generic generator/validator entrypoints once rather
than redundantly for every variant. The same exact local selection passes in
65.3 seconds. Head `8023867cd48c27f35a439e4f3fd9a8602de44a3e` received both
independent approvals and guard `31277808316` passed, but release run
`31277808312` reproduced the same 120-second changed-test timeout before
packages; authority and supply chain passed. The sole demonstrated harness
correction gives only changed-test execution a bounded 240-second ceiling,
retains every test and H-tier package/terminal requirement, and adds a direct
contract regression. Head `4670c084fcfec15342527652c90a9968205485af`
passed guard `31278463750` and hosted run `31278463749` passed authority,
supply chain and the complete changed-test preflight in 125.2 seconds. Its
package jobs became stale and were cancelled after whole-diff review found two
product defects; risk review approved. One consolidated correction now rejects
contradictory redaction state retaining raw content and reuses the existing
recursive temporal bound for nested outcome details, with direct regressions.
Replacement head `e10b9914f4806f0e3e549cd3f74edb1c4132455e` passed the exact
changed selection in 69.9 seconds and guard `31279691735`; H run `31279691720`
became stale and was cancelled after risk review found Windows case-insensitive
ID overwrite and tuple-nested PIT bypasses; whole-diff review approved. The
consolidated correction rejects normalized ID collisions inside existing
single/batch transaction boundaries, preserves the original entry and extends
the existing recursive temporal traversal to tuple arrays. Replacement head
`5d11f10d95931b3971b33e606920aed526a0b570` passed the exact changed suite
in 71.8 seconds and risk review approved; stale H run `31281223390` was
cancelled after whole-diff review required every malformed variant to exercise
both generic registry entrypoints and nested synthetic executable-authority
metadata to fail closed. The bounded correction restores those assertions and
recursively rejects the marker across dict/list/tuple metadata. Final reviewed
head `19bbee09aef0f4bb19faa72183510c0dc5975973` passed guard `31281965468`
and full H-tier run `31281965469`, then merged in PR #657 as
`dbb53c04a17327b8b97a73c8841c5368c2e82c9f`. Ordered writer `31284329688`
applied only `planned -> in_progress` with terminal verification and
zero-action readback; convergence `31284329681` passed and
`execution_allowed=false` remains. Clean completion branch
`codex/issue0010-completion-20260809` starts at that exact main and records
only the existing atomic `in_progress -> implemented_initially -> integrated`
replay, exact reviewed product/validation evidence, generated projections and
the required append-only authority transaction. No product or dependency-edge
change is in scope. Classification remains E-tier; because the unchanged
base-anchored reusable sidecar predates the ISSUE-0010 product diff, the hosted
package gate remains required and is not bypassed. Risk review approved frozen
head `cfbe45a129f0e0ce47341bde514f6f1ab99570a3`; whole-diff review rejected it
only because a generic negative fixture hard-coded `closed` as ISSUE-0010's
skip after that became its legal next hop. Stale run `31285303818` was
cancelled. The single consolidated test correction dynamically selects a
record with a legal two-step forward skip and the exact reproduction passes.
The replacement now classifies O-tier; cadence is known and not due, so its
hosted run requires preflight, supply-chain and terminal validation but not
Linux/Windows packages. Whole-diff re-review approved; risk re-review then
showed `planned -> in_progress` in the dynamic table was legal. The final
test-only closure changes that pair to `planned -> implemented_initially` and
asserts every chosen pair is absent from the canonical allowed-transition set.

Final head `4abb1d92830801d73045aa1499f4cec71caec8a4` received both
independent approvals, passed guard `31286274630` and O-tier run
`31286274627`, and merged in PR #658 as
`f6104403ab0f5e4e007700e5cbc1870429370f27`. Writer `31286431060` returned
`applied_and_verified` with one aggregate proposal/receipt and zero-action
readback; convergence `31286431065` passed. GitHub issue #14 projects
`integrated`; fresh generic plan
`51be8c545bc6f962076d2c310067748d72ab9a519378c09c18119040e768dafc`
has no actions and `execution_allowed=false` remains.

ISSUE-0011 is the next dependency-ready product issue. Clean branch
`codex/issue0011-product-20260809` starts at that exact main and implements
only the main-UI action reliability contract: deterministic inventory from
control/route/command metadata, unique stable IDs, command bindings, visible
failure states and research, training, paper, broker-read-only, recovery and
live-stage lane coverage with no execution authority. Rejected head
`eefdd8b613cd0bf34d2414d35fd624ded2e90bd8` and its evidence are stale. The
single consolidated uncommitted correction now validates 238 source/config
contracts, including post-construction paper-open, keyed input/change/select
bindings and file pickers, and generates 282 contracted actions (202 controls,
40 routes and 40 commands). Exact callback/signal contracts, fixed lane policy,
visible unknown/builder route failures, deterministic duplicate handling and
installed-wheel contract resolution are covered. The 43-test focused suite,
Ruff, compile, diff hygiene, byte-clean generation and an isolated installed
wheel run pass; the wheel generated the same 282 actions twice and every action
retained `execution_allowed=false`. Exact head
`aa1453f6eec7ad57e40b778ae86b9118d2334c53` was rejected for unresolved
action callbacks, a no-op synthetic action, false universe cancel metadata,
palette metadata/runtime divergence and failed replay returning success. The
final uncommitted correction makes every discovered callback resolvable,
regenerates the existing deterministic synthetic fixture with visible
success/failure state, gives universe dismissals exact callback names, binds
palette result controls directly to `select_palette_command`, and replays the
original completed/failed terminal result without reinvocation. Two disjoint
focused selections pass 100 tests; Ruff, compile, diff hygiene and byte-clean
generation pass. Classification is H because `pyproject.toml` and
`scripts/smoke_app.py` are changed package/protected surfaces; reuse is false,
the package gate is required, and fresh exact-head Linux and Windows hosted
gates are mandatory. Rejected head
`e52308309e4817447696f8a219556df67da6a5ba` was then reproduced bypassing
terminal replay on real result-button dispatch, collapsing palette change and
submit into one action, and silently omitting orphan configured inputs. The
final bounded uncommitted correction sends actual result `on_click` through
the generated `navigate_palette_command` contract, retains completed/failed
terminal results across duplicate dispatch, inventories distinct stable
`shell.command-palette.on-change` and `.on-submit` actions with exact runtime
callbacks, and rejects every unmatched actionable/input contract. Fourteen
passive fields falsely declared as input actions were removed from metadata;
their UI is unchanged. The 225 contracts now generate 283 non-executable
actions (203 controls, 40 routes and 40 commands), and two focused selections
pass 87 tests. H classification and fresh hosted Linux/Windows requirements
are unchanged. Exact head
`de14e2ea9f4dc366067ea6fc3e0bb0f03041c491` passed whole-diff review but
risk review found that direct dispatch did not return its preserved terminal
result. The final correction returns that existing result and directly asserts
completed/failed status, signal, message and replay state; its focused
regression, Ruff, compile and diff hygiene pass. Exact head
`962d3bca6ccffca5f4d4548640689b6d7d52415c` was then rejected for accepting
an undefined direct named event callback and declaring the terminal-result
palette handler as returning `None`. The bounded uncommitted correction
resolves direct source callback names against module imports/definitions and
enclosing parameters/local bindings while preserving nested, imported,
parameter, post-construction, attribute and lambda forms; the palette handler
now returns `UIInvocationResult | None` explicitly. The 29-test focused
selection, targeted two-file MyPy with return checking, Ruff, compile and diff
hygiene pass. The exact 225-contract/283-action non-executable inventory and H
classification remain unchanged. Exact head
`ceb1fd963f303cf1b68e528cbdfdda397196f39d` was then blocked by the full
targeted MyPy command on one un-narrowed route-metadata index and two installed
distribution `SimplePath` conversions, and by a lambda wrapper that could call
an undefined callback. The final bounded uncommitted correction narrows page
title metadata to a non-empty tuple, converts located package paths through
their string representation, and checks direct names called inside lambda
event wrappers against the existing available-symbol set. The exact two-file
MyPy command passes without error-code exclusions; the unavailable PyYAML stub
uses the repository's narrow import annotation. Thirty focused tests, Ruff,
compile and diff hygiene pass. The 225-contract/283-action non-executable inventory, package
mechanics and H classification remain unchanged. Exact head
`1944caa539d0f63ed0de52ccdd7e9cb6dfc3abec` received both independent
approvals. H-tier run `31293133592` passed Linux full tests, package build,
source/package parity and every policy check, but Linux package smoke failed
because the extracted sdist's partial `tests/` tree was mistaken for a
repository checkout. The bounded correction requires acceptance-test files
only when a `.git` checkout marker exists and adds the exact
package-versus-checkout regression; the runtime contract and 283-action
inventory are unchanged. Fresh exact-head H gates remain required. Because
canonical ISSUE-0011 is already `in_progress`, this product PR changes no status or dependency
edge; after exact reviewed merge, use the existing aggregate `in_progress ->
implemented_initially -> integrated` writer transaction and require zero-action
generic readback. Product PR #659 merged reviewed exact head
`b782a9f75d4e6653ddc6ee1dbd733e8e775c24cc` as
`18b93e91ed8c9152e509d70ae0548b57550606fa` after H-tier run
`31295173994` passed Linux, Windows, package smoke and terminal validation.
The clean completion lane reproduced one deterministic defect because the B00
canonical import predates ISSUE-0011 transition history. One bounded H repair
therefore recognizes only the exact bootstrap-empty `in_progress` origin in
all three replay validators; it does not change hops, dependencies, authority,
retry behavior or `execution_allowed=false`. Repair PR #660 merged exact
reviewed head `3ee6f811495149a4a526ea1335cd941a6012c766` as
`79ef677112f89c74b0ac652ede04a4411646b4d9` after H-tier run
`31299002822` passed Linux, Windows and terminal validation. The completion
lane is rebased onto that exact main; its one live action targets issue #15 at
plan SHA `5081667a34d01125c464d622c59a9fce715c9097d5d7f5cf08e67ba9e4317ea0`
and aggregate authority
`c417a1345e877422ea30dcaac81a23bf1cf72cf544edec2186a8f0a85a05572b`,
with one post-merge replay write and mandatory zero-action generic readback.

Completion PR #661 merged exact head
`0d789d0550a38c107b427bec40ac6bfff98ce5da` as
`a80aa32a3c6ffaeb5e7075d152c2d4cce9e888ea`. Writer `31301505274`
returned `applied_and_verified` with an acceptance receipt and
`zero_action_readback=true`; generic exact-main plan
`da8f7f0f36d1a9c9124b02634176b51b3e9e11cddbebcf39457cdeec9f615ef1`
has no actions. GitHub issue #15 resolves to `integrated` and
`execution_allowed=false` remains.

ISSUE-0012 product commit
`43fcbca8f5960af7f54f48bb94e0d08682f49c78` is rebased onto repaired
main and remains locally green. Exact-main lifecycle preparation reproduced
`ISSUE-0012: status replay transition history prefix must be a list`; its
isolated one-action plan SHA is
`8e3778a20cd1b1c64da5c69347238c017c932f56d1f16649bd7a2dd8847fe3aa`.
Repair PR #662 merged independently approved exact head
`f23e814127fc62db4c936e9b4788ff7b242d2288` as
`5718ed5a2cb961985a215a25277951c271c4571d` after H-tier run
`31303632447` passed Linux, Windows and terminal validation. Only complete
fixed ISSUE-0011 and ISSUE-0012 B00 records may use the empty prefix; every
other identity and malformed source fails closed. No lifecycle, dependency,
retry, external-write or execution authority changes.

ISSUE-0012 remains the next product issue. Clean branch
`codex/issue0012-product-20260809` starts at exact main
`5718ed5a2cb961985a215a25277951c271c4571d`. Its bounded scope extends the
existing persistent activity/run-log and visible progress contract across all
declared long-running workflows, preserving local-first operation and all
execution and external-write boundaries.

Fresh repaired exact-main lifecycle proof produced one ISSUE-0012 action at
plan SHA
`8e3778a20cd1b1c64da5c69347238c017c932f56d1f16649bd7a2dd8847fe3aa`
and aggregate authority
`e1b1ea5d819d666f8a1b8b2d27ce683772ad35dd1f59de8e6458e5ff102004f1`.
The guard correctly rejects combining it with the product PR because product
commit `43fcbca8f5960af7f54f48bb94e0d08682f49c78` is not yet an ancestor
of the reviewed generation base. Keep the product PR product-only, then
regenerate this compact completion transaction from its exact reviewed merge
and require the ordered writer plus zero-action generic readback.

Product PR #663 head `b1023cf53a4634c8fc4c7263660677ffc10364a3`
was rejected by both exact-head reviewers. All persistence, cancellation,
runtime-binding, terminal-status, redaction and visible-timestamp findings
were consolidated into correction commit `3303ac2f`. The correction retains
restart history, enforces action-ID publication ownership and cancellation,
marks normal-return unavailable results as failures, reports real forecast
stage boundaries, makes macro/news refresh reachable, redacts cache failures
and renders start/output/error evidence. Focused lifecycle, startup, workflow,
resource, UI, import/report, forecast and event-log evidence passed alongside
Ruff, compileall and diff checks. Exact classification keeps the replacement
product head O-tier with no packaged gate due; it requires parallel whole-diff
review, risk review and exact-head hosted release validation before merge.

Replacement head `f82ddaf8748787bf9ea51fdbf37eff933ecdd511`
passed hosted run `31306934161`, but both reviewers rejected its cancellation
publication boundary, making that CI evidence stale. The whole-diff review
also found non-atomic concurrent starts, raw UI exceptions, ESEF unavailable
success and stale non-dashboard progress rendering. Final consolidated
correction commit `eff4ba5c` makes starts atomic, reserves cancelled ownership
until callback exit and holds the shared activity lock across each single
verified durable publication. Cancellation now wins before a write or waits
for it and rejects every later publication. UI failures are redacted, ESEF
unavailability fails and terminal non-dashboard handlers rebuild the shell.
Focused evidence passed 24 ISSUE-0012 tests and 201 coupled tests plus Ruff,
compileall and diff checks. The next exact head must repeat whole-diff review,
risk review and hosted O-tier validation together.

Exact head `aadea38329f051523c18e235b67040c1852d5150` was then
rejected by both reviewers for five newly demonstrated terminal-integrity
defects: an update/cancel mutation race, non-atomic session-log compaction,
unguarded snapshot-derived writes, disclosure unavailability shown as success
and remaining raw job/provider errors. Consolidated correction commit
`9e77291d` linearizes updates with the controller transition, atomically stages
and validates compacted history, scopes feature/backtest publications,
re-raises cancellation, fails unavailable disclosure terminals and removes
raw exception text. Focused evidence passed 33 ISSUE-0012, 143 directly
affected and 41 yfinance/release-hardening tests plus Ruff, compileall and
diff checks. The final checkpointed head requires both reviews and hosted
O-tier validation afresh; rejected-head evidence is not reusable.

Exact head `61fdc2ac636946d7bf1d69201881faf01e96fecf` was rejected
after both reviewers confirmed unguarded sample/API-status/rollback writes;
risk review also found restart recovery depended on secondary activity events
instead of canonical workflow events. Correction commit `fb0916fc` recovers
start/step/finish/cancel from the existing locked `workflow_*` events when
richer activity events are absent, and threads the lock-held publication scope
through sample inputs, clean prices, rollback, API/yfinance status and snapshot
initialization. Provider failures are redacted and unavailable status fails.
Focused evidence passed 40 ISSUE-0012, 51 rollback/yfinance and 23 workflow/
startup tests plus directly coupled release/trust regressions, Ruff, compileall
and diff checks. Protected clean-price-store coverage makes the new head
H-tier; repeat both exact-head reviews and hosted Linux, Windows and terminal
validation. All prior hosted runs are stale.

Exact head `2edf3a41a078e3db4a7f2033bf318cb2c4283c39` whole-diff
review found the remaining in-scope gap: SEC/OAM/ESEF/manual filing controls
bypassed the shared lifecycle. Correction commit `116c80c1` routes all seven
controls through canonical activity ownership, guarded publication,
unavailable/redacted terminals and shell refresh, and adds catalog entries.
Focused evidence passed 49 ISSUE-0012 and 156 filing/trust/UI tests,
deterministic SEC cancellation publication evidence, Ruff, compileall and diff
checks. Risk review separately reproduced cross-process session-log contention
and pre-existing crash-atomicity gaps in broad financial/audit writers; retain
them as later persistence-hardening evidence and do not expand this product
issue into a new locking or generation framework. Repeat scoped whole-diff and
risk review plus the full H-tier hosted gate on the final head.

Exact head `39a7016ee9742979d6e0eff237672b4556af1e72` was rejected
for four scoped recovery gaps: truncated-tail startup append failure,
synchronous filing work without a reachable cancel control, disclosure
losing-start cleanup and retries bypassing canonical activity ownership.
Correction commit `d8dd2344` applies existing bounded tail recovery before
append/compaction, runs official filing work in the existing background pattern
with a persistent-shell cancel control, handles atomic-start losers safely and
makes retries re-enter the decorated lifecycle wrapper. Focused ISSUE-0012,
startup, error-recovery, trust and button evidence passed with Ruff, compileall
and diff checks. Re-run both scoped reviews and the full H-tier Linux/Windows/
terminal gate on the final checkpointed head.

Exact head `5336501786e19bdb6102b7dd5517fb032f2d6cb1` was rejected
after both scoped reviewers completed. The consolidated defects were
worker-lifetime handling of byte-backed browser uploads, stale success text
after cancellation, absent official-filing retry re-entry, synchronous
document/report/holdings/KID/methodology imports, ESEF discovery publishing
after cancellation and path-only picker handling. Correction commit
`8bb8bfcdf38e9b1ce23595bf789f29c96e3da343` uses the existing background
lifecycle for every affected import, keeps path/byte uploads readable for the
worker lifetime, restores canonical cancellation text, binds ESEF publication
to the owning action and makes retry callbacks re-enter the lifecycle. Focused
ISSUE-0012 and coupled trust/button/error-recovery/startup evidence passed with
Ruff, compileall and diff checks. Freeze one checkpoint head after this
chronology update, then run both scoped reviews and fresh H-tier Linux,
Windows and terminal validation against that exact head.

Exact head `de06050914635a3bb736f504e39c3bf73021cbbc` was rejected
after both parallel reviewers completed. The complete finding set is late
success text surviving canonical cancellation in generic helpers, synchronous
cache rebuild without safe retry, and synchronous notes/news import without
reachable cancellation or retry. Hosted H-tier run `31317068279` passed
generation, smoke and supply-chain controls but timed out its six-module
changed-test selection at 240 seconds before package jobs. Correction commit
`633e64607c070c05e6306aab3de6a0a1b17f4a3d` restores canonical cancelled
messages in affected finalizers, moves both actions onto the existing
background lifecycle, guards cache deletion and preserves retry. Five lightly
edited broad test modules are restored to base while their unchanged full-suite
assertions pass; the actual changed-test set is ISSUE-0012 plus Flet startup
and passes locally below the hosted window. Focused ISSUE-0012 and correction
regressions, Ruff, compileall and diff checks pass. Freeze one new exact head
after this checkpoint and repeat both reviews plus fresh H-tier Linux, Windows
and terminal validation; rejected-head evidence is stale.

Exact head `fb9ebd6dff118dfa19a784245f09d4534b88c33d` was rejected
after both parallel reviewers completed. The newly demonstrated final gap was
cancellation reachability: validation, renew imports and cache cleanup did not
rerender the persistent shell when starting, and the accepted ChatGPT and
Import/Export audit controls remained synchronous with incomplete retry
ownership. Hosted run `31319351588` passed corrected preflight but was
cancelled/disregarded during Linux/Windows packaging once review rejected the
head. Correction commit `e3df8c194fd3b85077dfa532f9b564ce72207d12`
immediately exposes the shell cancel control for every affected start, routes
all three registered audit exports through background owned lifecycles,
restores cancellation and retries each complete operation including ChatGPT
archive validation. The action-control catalog now enumerates every registered
control. Focused ISSUE-0012 passes 71 tests; the exact changed-test set passes
in 115.5 seconds without warnings, with Ruff, compileall and diff checks green.
Freeze one final exact head after this checkpoint and repeat both reviews plus
fresh H-tier Linux, Windows and terminal validation.

Exact head `2a91dd466be9a70d868a82c53956181f7b10b738` was rejected
after both parallel reviewers completed. All runtime lifecycle findings were
accepted; the residual set was two missing Dashboard holdings/factsheet keys
in reverse action-control coverage and an empty file-picker terminal that
cleared activity before the final shell rerender. Hosted run `31320604306`
passed corrected preflight but was cancelled/disregarded during Linux/Windows
packaging after rejection. Correction commit
`72792c1c3533e4d4c25b05fd10ef270f1555c7e2` adds exact and reverse catalog
coverage, records both accepted Dashboard controls and always rerenders the
picker terminal. Focused ISSUE-0012, Ruff, compileall and diff checks pass.
Freeze the replacement exact head after this checkpoint and repeat both
reviews plus fresh H-tier Linux, Windows and terminal validation.

Final product head `043c14f8f88aa79911e378a390477521584d4da3`
received independent whole-diff and risk approval. H-tier run `31326072782`
passed preflight, supply chain, Linux, Windows and terminal validation after
one documented retry of a native pandas C-parser crash. PR #663 merged that
exact head as `c9efd6b351db76290e3371314d67c986406168f5`. Clean lifecycle branch
`codex/issue0012-lifecycle-20260810` starts at that exact main and carries only
the canonical ordered two-hop completion, mechanical projections and
append-only authority. Its live plan SHA is
`8e3778a20cd1b1c64da5c69347238c017c932f56d1f16649bd7a2dd8847fe3aa` and
aggregate authority is
`60d2ce9cc6057817850dcb42ca1ed7e51c5ddbb96d9415280d557e134bcc7206`.
Both exact-head reviews approved after fresh lifecycle run `31328999996`
passed Linux, Windows and terminal validation and guard `31328999997` passed.
PR #664 merged exact head `30be81ef0c73059331cbe9b2268e66f9f02314c6`
as `c8a7da624c97f1a04191fd3ad1b7880bca83feec`. Writer `31330290295`
returned `applied_and_verified`, one aggregate proposal and receipt, and
`zero_action_readback=true`; generic live readback is zero-action at plan SHA
`999f68c57c2ec349c21280aa94b751a6dac5130a9d03981d2d63a72bdf743f7c`.
GitHub issue #16 now projects `integrated`; `execution_allowed=false` remains.

ISSUE-0014 remains next and dependency-ready by canonical blocking
dependencies. Both independent reviewers rejected exact head
`a66c66ad6c2f941b6640d81320988b0b8af9e129`; this consolidated correction
replaces simulated package/browser evidence with the real sdist artifact,
registered routes and loopback HTTP startup, and adds canonical local
refresh/algorithm/forecast/scoreboard/audit APIs, managed migration backup,
valid interrupted-write recovery, runner-wide socket denial, provider-
transport failure and application-API paper restart/rejection regressions.
Hosted run `31330623071` is stale evidence because preflight failed before the
Linux and Windows package jobs. Canonical issue status and authority remain
unchanged pending corrected exact-head review and required H-tier validation.
Whole-diff review approved first replacement head
`396e366c4bfe2617d0b0353d14e89b9ffe18f2b7`; risk review rejected it for
incomplete DNS/datagram denial, an unpinned workflow date and checksum-
ambiguous proposal negatives. Its run `31332248276` is stale after changed-
test preflight exceeded 240 seconds. One bounded correction covered all four
findings. Both reviews approved exact head
`f25e006a506d2c141b42544ad3dca64e7fe4c831`, but fresh run `31333048454`
deterministically reproduced the Linux changed-test timeout. The final bounded
correction removes only duplicate initial snapshot and route rendering; all 16
journeys retain their assertions and pass locally in 140 seconds. Both reviews
approved exact head `b3696a504f26dfedad3a5948030cfa8bfab19429`; run
`31333531773` completed changed tests in 183 seconds and exposed the independent
preflight absence of the configured setuptools backend. Keep real sdist
execution when the backend exists, assert the exact isolated-build command
everywhere, and leave authoritative package execution mandatory in the H-tier
package job. Freeze one final replacement head for both reviews and fresh
validation. Both reviews approved exact head
`48682c5ea4510cec950a01b3316060563f66d70c`. H-tier run `31334147828`
passed preflight, supply chain, both release packages and terminal validation,
but its repeated report-only pilots demonstrated that the new all-routes
browser probe exceeded its 120-second subprocess limit only in the four-worker
safe lane; both serial repetitions passed. Classify that resource-heavy Flet
probe into the existing serial/flet lane without changing product, workflow or
validation authority, then freeze one final replacement head for both reviews
and fresh validation. Both reviewers rejected replacement head
`b353740b67b0528fb42d51de13bb2c5fb807b7a1` after jointly demonstrating that
its purported all-routes probe still named only `/` and `/training-centre`
while production registers every route in `PAGES`; run `31339056458` was
cancelled and discarded as stale. The single consolidated correction derives
and exercises the complete production route registry while retaining the
existing serial/flet partition. Both reviewers approved exact head
`3e80a31b7d31245076625dbec9292bb3c5e95754`. H-tier run `31339637212` passed
preflight, supply chain, both authoritative release packages, terminal
validation and the Linux parallel pilot, but its second Windows serial
repetition crossed UTC midnight and exposed one unpinned host-date path in the
test probe. The single bounded correction binds candidate analysis to the
probe's existing fixed date and asserts that every download uses that date;
production, authority and workflow code stay unchanged.

Final exact head `576b5837e0ee096f9762c38122a7b439193001d4` received both
independent approvals. H-tier run `31355486697` passed preflight, supply chain,
Linux and Windows packages, terminal validation, both repeated pilots and
cross-platform aggregation; PR #665 merged it as exact main
`0f45b6e7ece668c0cad9e34e6022b2cbaf53d619`. Canonical two-hop lifecycle
preparation then reproduced one exact control defect: ISSUE-0014 has the same
audited B00 history-free `in_progress` source shape as ISSUE-0012 but was not
in the fixed bootstrap allowlist. Clean H-tier branch
`codex/issue0014-bootstrap-replay-repair-20260810` adds only ISSUE-0014's exact
fixed identity plus fail-closed regression and durable workflow wording.
After full review and validation, resume the preserved lifecycle transaction;
`execution_allowed=false` remains.

Both reviewers approved repair head
`5e2a4358e825168b27194582bd30a69b47c5a7ca`. H-tier run `31364891591`
passed preflight, supply chain, Linux, Windows and terminal validation; PR #667
merged it as exact main `35007496ae5052ef5ac41ede746ed76f1a48ab87`.
The preserved lifecycle branch fast-forwarded to that exact base and now
contains only the legal ISSUE-0014 two-hop canonical completion, mechanical
projections and append-only sequence-19 authority. Fresh live plan
`956b10f1cc6b1501c3246aa6ee009b3478c8fe58ee965ec12de995ac690c7b5c`
binds candidate ref
`474bf56be46ae61e756103e4c90570db9879984cfed2b3f0f346ec7da7763387`
and authority
`fa4fb0c9731d6ec134362d9ca08b583db0ea715609650ea934fa500805e71bcf`
to product PR #665 merge `0f45b6e7ece668c0cad9e34e6022b2cbaf53d619`;
`execution_allowed=false`. Complete exact-head E-tier review/validation,
merge, writer and zero-action readback, then transplant the prepared
dependency-ready ISSUE-0015 product lane.

## ISSUE-0104 product chronology

Readiness PR #654 merged independently approved exact head
`92523800cbbb83a307b9250867b495e722b5196c` as
`fca004a529cccc3b0d4251fc600a897035298014`. Writer `30776243636` applied and
verified the sole `planned -> ready` projection with zero-action readback;
fresh generic convergence is zero action at
`f60115aa8e2cf9655974050b590864231261317ad82250a89563a1e6bf27571e`.

Clean branch `codex/issue0104-product-20260803` now implements the bounded
structural/legal/counterparty/lending/collateral analysis contract and ETF
Structure & Documents panel from exact main. Every structural field retains
document/date/page/confidence; unknowns and cross-document conflicts remain
explicit, numeric stress requires numeric evidence, stock credit metrics and
legal/sustainability alpha are prohibited, and `execution_allowed=false`.

Product evidence commit `8a69a94919bf93d584778659ee01be030c020ce7`
passes the 87-test affected suite with one expected skip. The byte-clean
canonical projection now includes only `ISSUE-0104: ready -> in_progress`.
Live status-only plan
`6f0f011be2cfca6b24865e05fba0bd7356c083e6824ca570975ffe8d3c4b5d7d`
is bound to issue #244, exact parent `fca004a529cccc3b0d4251fc600a897035298014`,
append-only authority
`3410411c01d92c04b7a47a456d1b17c50da1645dc5d08a72459f1020697902fe`
and `execution_allowed=false`. Freeze the completed product/lifecycle head,
run whole-diff review, financial/point-in-time risk review and H-tier hosted
validation in parallel, then require the ordered writer and generic
zero-action readback after merge.

First frozen head `b4d5e8ad59df2ee35b63a43258b0c05041320623` and replacement
head `68b5b5e2a436183c9a9c89c1b9a2fe1096325a3a` are rejected; their review
and CI evidence is stale. The replacement reviewers jointly required
point-in-time review-history replay, reachable typed numeric stress with input
status validation, strict legacy-fingerprint scope and reviewed-row migration,
negation-safe disclosure classification, and independent report-family
binding. Release run `30781501084` also reproduced the 120-second changed-test
timeout before Linux or Windows packaging began.

Bounded follow-up commit `df215ae1810ffea55a50f96747305d9dccba52ca`
covers every collected finding and moves the two new
regressions out of the slow broad test modules. The final six-file affected
selection passes 107 tests with one expected skip in 87.9 seconds; Ruff,
compile and diff hygiene pass. Canonical/lifecycle authority and
`execution_allowed=false` are unchanged. Freeze one checkpoint head, then
repeat both independent reviews and fresh H-tier hosted validation in
parallel.

Replacement exact head `db8dfe4560912ccc885d2f3ec355af4984ece77a` is also
rejected after both parallel reviewers completed. The complete finding set is
persisted reviewed numeric-evidence binding, equal-time append-order replay,
duplicate registry identity rejection, standard local factsheet/holdings
reachability, and yfinance signal/backtest structural-evidence propagation.
Release run `30783547607` timed out the broad affected suite at 120 seconds
before package jobs began, so its evidence is stale.

Final bounded correction commit `8ed78afef51893f50809d44db03da845c482dca5`
covers all five findings and relocates the
remaining Instrument Detail assertions into a dedicated focused module while
restoring the broad module exactly to base. The final changed-test selection
passes 94 tests with one expected skip in 68.3 seconds; the direct 26-test
correction suite passes in 17.9 seconds including command overhead. Ruff,
compile and diff hygiene pass. Freeze a new
checkpoint head, then repeat both independent reviews and fresh H-tier hosted
validation in parallel.

Exact head `43b7c168718245fad0549db0464705ccaf102c9b` is rejected after
both reviewers completed. The complete findings are real backtest and
service/cache holdings propagation, supplemental non-usable status
preservation, duplicate rejection at the canonical registry reader, and exact
numeric instrument binding. Stale release run `30785676406` passed its
96-case affected selection in 99.45 seconds but failed the protected
presentation boundary because the selector directly imported an implementation
constant; package jobs did not start.

Bounded follow-up commit `004c8218d84fbbfb000a8efd85452594afb8611c`
covers the full set, exports the structural-field
contract through the existing application facade, and replaces the
88.69-second hosted full-snapshot test with focused section-routing evidence.
Direct correction, architecture and document suites pass 57 tests; the final
108-case affected selection passes with one expected skip in 76.3 seconds
locally. Ruff, compile and diff hygiene pass. Freeze the next exact review
head.

Exact head `c50647a809ccbe84649b05e43fb0025c8354d9f3` is rejected after
both reviewers completed. The complete defects are an incorrect real-backtest
checksum keyword, omitted factsheet evidence in shared score/backtest/cache
loading, duplicate persisted report identities, and multi-row pre-2.1
migration losing untouched-row fingerprint context. Release run `30787415201`
passed preflight and reached both H-tier package jobs; Linux and Windows both
failed the deterministic real-backtest defect, so that evidence is stale.

Final narrow correction commit `853ade3f6ee042ad579201d5797f32ed06b81ad0`
covers all four reproduced defects. It includes a
real 260-session structural-holdings backtest, shared factsheet/holdings
score/service/cache/yfinance loading, duplicate report-reader rejection and
reviewed/unreviewed multi-row migration. The 111-case affected selection
passes 110 tests with one expected skip in 35.7 seconds; architecture, Ruff,
compile and diff hygiene pass. Freeze the replacement exact head.

Replacement exact head `e9a672994541918b2a974e30a8d164c2cfd83314` is
rejected after both parallel reviewers completed. The complete findings are
fail-closed malformed canonical factsheet/holdings handling, preservation of
real writer structural provenance, and stable cross-kind `legal_form`
conflicts. Stale release run `30789907061` reached both H-tier package jobs;
Linux and Windows failed, so none of its evidence is reusable.

Consolidated correction commit
`6e31cc5ae050b953066ad5374d3c5d4f6efdadf9` closes all three findings. It uses
real factsheet-document/reference and holdings-document writers in the
regression, proves their exact bindings survive the shared projection and
backtest, and retains `execution_allowed=false`. Four direct adversarial cases
pass; the combined affected structure, scoring, parser, document, holdings,
release-hardening and architecture suite reaches 100% with one expected skip
and no failures. Ruff, compile and diff hygiene pass. Freeze one checkpoint
head, then repeat both reviews and fresh H-tier hosted validation in parallel.

Exact head `ab8b7c0a79a52749eae68cf78165247f63893b7f` is rejected after
both parallel reviewers completed. The full collected set is cross-kind legal
conflicts projected as resolved, numeric stress unreachable through a real
canonical parse/review/readback path, and inconsistent current review
eligibility accepted through older verified history. Status guard
`30792984804` passed. Stale release run `30792984780` passed preflight and
Windows; it was cancelled after rejection while Linux was running, so Linux
and terminal results are not reusable.

The sole next pass corrects those three demonstrated defects and adds their
focused regressions without changing lifecycle, authority, dependencies,
providers or `execution_allowed=false`. Freeze one replacement head after the
focused suite, then repeat both reviews and fresh H-tier hosted validation.

Consolidated correction commit
`fd0e6cb8957351427c0066c769ce4c820c973bf2` preserves valid point-in-time
review replay while rejecting inconsistent current state, keeps cross-kind
stable conflicts unresolved, and carries four typed fraction inputs through
real PDF parse, reviewed persistence, readback and structural stress. The
focused parser/disclosure/structure/correction suite reaches 100% with one
expected skip; the direct review-history follow-up passes 20 tests. Ruff,
compile and diff hygiene pass. Freeze the replacement checkpoint head.

Exact head `6bdb98a489bd046175432d833626751cf73900ec` is rejected after
both reviewers completed. The complete newly demonstrated set is partial-token
acceptance of percentage/suffixed numeric stress values and malformed or
metadata-inconsistent review history falling back to trusted top-level
verification fields. Status guard `30795502020` passed. Release run
`30795502035` was cancelled after rejection, so package and terminal evidence
is stale.

Make one narrow parser/review-state correction with real-path regressions,
preserve valid historical replay and every prior fix, then freeze one exact
head for both reviews and fresh H-tier gates.

Narrow correction commit
`be211955a1a4dde05723e03388c65b4c471d9ca2` requires complete bare-decimal
stress tokens, rejects percent/suffix/backtracking cases through the real
reviewed path, and fails closed on malformed or current-metadata-inconsistent
review history. Valid verified-before-rejection replay remains covered. The
focused correction/structure/parser suite passes 71 tests with one expected
skip; Ruff, compile and diff hygiene pass. Freeze the checkpoint head.

Exact head `86f6ba03e19cfe948ff852d9eb6ca84e3beef8b1` is rejected after
both reviewers completed. The complete finding set is canonical readback
accepting an empty reviewer/unsupported review decision, supplied projection
accepting missing or empty verified history, and numeric stress combining a
quartet across unrelated report revisions. Status guard `30797521767` passed;
release run `30797521771` was cancelled after rejection and is stale.

Correct those three exact authority/provenance cases only: verified evidence
requires one semantically valid history, and every stress input must share one
exact reviewed report revision. Preserve valid historical replay and all prior
strict-token behavior, then freeze one replacement head.

Consolidated correction commit
`044375c91d9e56334266f7860c738609fc3508fe` enforces semantically complete
review history in canonical and supplied readback and binds each numeric stress
quartet to one report revision while preserving valid historical replay. The
attributable focused suite passes 117 tests with one expected skip; Ruff,
compile and diff hygiene pass. Freeze one exact replacement head for parallel
whole-diff review, risk review and fresh H-tier hosted gates.

Exact head `387d7de921dcc189a8479da2c11af155d2e22965` was rejected after
both reviewers completed. The consolidated finding set is one supplied-frame
trust-boundary gap: extraction content was not recomputed against its stored
fingerprint, malformed score/execution flags were accepted, and duplicate
report identities bypassed canonical readback validation. Release run
`30799282419` was cancelled after rejection and is stale.

Correction commit `1c53cea7a03dc40afea1c1f0742e7d294ab52843` routes supplied
report frames through schema-aware fingerprint, review-authority and unique
identity validation before structural or numeric use. Facade-level mutation,
authority-flag and duplicate-ID regressions pass within a 112-test focused
suite; Ruff, compile and diff hygiene pass. Freeze one replacement head and
repeat both exact-head reviews plus fresh H-tier hosted gates.

Exact head `750ee1be352f3b7c8852d2d779ec4abf352997b1` was rejected after
both reviewers completed. Newly reproduced parity gaps covered canonical
review/manual/verifiability semantics, original-container schema identity,
non-mapping members, exact document-kind/source-authority binding, bare decimal
grammar and global registry source identity. Release run `30801792515` was
cancelled after rejection and is stale.

Final parity correction commit
`673f30f073427e03d181f6a5bcad4e908a4d01ee` applies those exact
canonical rules to every supplied projection, cap and cache path without
changing lifecycle or execution authority. The complete focused parity suite
passes 124 tests; Ruff, compile and diff hygiene pass. Freeze one replacement
head and repeat both reviews plus fresh H-tier gates.

Exact head `1bcf863e6402e9cb7d883d319bd0e09b4210bc2f` was rejected after
both reviewers completed. The complete new finding set is strict stored boolean
handling for `parse_success`, numeric document-family binding,
duplicate-registry cache identity and explicit derivative/synthetic negation.
Release run `30803686888` was cancelled and is stale.

Residual correction commit `875b893fd87d386475cdc3d0815acbe1d24d6c66`
covers those four reproduced cases only. The focused suite passes 130 tests;
Ruff, compile and diff hygiene pass, and `execution_allowed=false` is unchanged.
Freeze the replacement head for both exact-head reviews and fresh H-tier hosted
gates.

Exact head `52cae8cf7f87da46f95e53c643061acc7d394e54` was rejected after
both reviewers completed. The complete finding set is field-local negation,
unconditional `parse_success` schema typing and stale-cache prevention when
structural storage is corrupt or unreadable. Release run `30805501748` was
cancelled and is stale.

Correction commit `3fa69aaef0757aba3013598497cb74ae98fdfd6d` covers only those
reproduced paths. The focused suite passes 153 tests; Ruff, compile and diff
hygiene pass, and execution/lifecycle authority is unchanged. Freeze the
replacement head for both exact-head reviews and fresh H-tier hosted gates.

Exact head `ea5a7863876a7bff8ce32812de115a74590ed120` was rejected after
both reviewers completed. The consolidated acceptance gaps are supported report
schemas, one-revision numeric quartets, strict typed input channels and cache
identity, clause-aware contradiction handling, and per-decision backtest
structural provenance. Release run `30807318004` was cancelled and is stale.

Complete provenance correction commit
`e858f5a8c0d57690ed7456baf7132d0a47ccc434` covers those reproduced
paths without lifecycle or authority changes. Four attributable focused suites
pass 182 tests total; Ruff, compile and diff hygiene pass. Freeze the replacement
head for both exact-head reviews and fresh H-tier hosted gates.

Exact head `a7862cb70e33afd6c12f4db2656abb88e7ac8ae5` was rejected after
both reviewers completed. The complete finding set is point-in-time conflict
eligibility, same-clause contradiction safety, structural identity-alias
agreement and typed-channel type/kind agreement. Release run `30811214008` was
cancelled and is stale.

Point-in-time correction commit
`55582bf9169db7da3a2a293c76e6a8b8f48b8939` covers only those
reproduced paths. Four focused suites pass 202 tests total; Ruff, compile and
diff hygiene pass. Freeze the replacement head for both exact-head reviews and
fresh H-tier hosted gates.

Replacement exact head `10607cf4fa0563a958821391c7735491bfac2416` is
rejected after both parallel reviewers completed. The complete finding set is
decision-time replay of cross-report review authority, contradictory
`instrument_id`/`etf_id` rejection, mandatory cached signal provenance and
architecture wording consistent with point-in-time conflict scoring. Release
run `30814812246` was cancelled after rejection and is stale.

Consolidated correction commit
`f82797a7fb854fdeb8ae2f70a68582835334df4c` covers those exact findings. It
replays conflict eligibility from the review event visible at each decision,
preserves earlier verified intervals before a later rejection, rejects
contradictory instrument aliases before projection or hashing, and invalidates
cached backtests without complete per-decision structural provenance. The four
attributable focused suites, Ruff, compile and diff hygiene pass; the
runtime-dated real-import fixture now uses an explicit post-import decision.
Lifecycle authority, dependencies and `execution_allowed=false` are unchanged.
Freeze one replacement head after this checkpoint and repeat both reviews plus
fresh H-tier hosted gates in parallel.

Exact head `6440440df1892a74c1734f935f52d1a437ed6ba8` is rejected after
both reviewers completed. The full finding set is false cross-period conflicts
for time-varying structure, omitted UI conflict-candidate provenance and cache
acceptance without exact per-decision cap/hash recomputation. H-tier run
`31246422546` additionally failed the vulnerability scan on
`cryptography==49.0.0` / `CVE-2026-69247`; status guard, preflight and lifecycle
candidate validation passed, but no package evidence was produced.

Combined correction commit
`9aea82a16bc2b1e71fbcf71c79068c02f9a83f25` shares one stable/varying conflict
policy, selects the latest reporting period for varying fields while retaining
same-period and stable-field conflicts, renders every conflict provenance
field, and recomputes each cached signal cap/hash from canonical decision-time
evidence. The directly coupled release and GitHub-writer runtime now pins fixed
`cryptography==50.0.0` with reviewed Linux wheel hash
`06a32a980526a6ab9a4b9bf8f7385800791e2bb960903cb6b530e4817509a3b7`.
Four product suites and five supply-chain/authority suites pass; Ruff, compile,
diff hygiene, binary hash-lock download and `pip-audit` pass with no known
vulnerabilities. Lifecycle state and `execution_allowed=false` are unchanged.
Freeze this checkpoint and repeat both reviews plus fresh H-tier gates in
parallel.

Exact head `e8001fe01a54878a89b1778137156cb265cb63c4` received risk
approval after 361 passing tests and one expected skip, but whole-diff review
reproduced one new defect: an absent optional holdings file was converted to an
empty frame and then misclassified as a malformed canonical store, suppressing
otherwise valid report/factsheet evidence. Run `31248171632` passed status
guard, supply chain, locked-writer candidate validation and preflight, then was
cancelled as stale while package and pilot jobs ran.

Narrow correction commit
`6781a488ab4fe68f77246ae4af6c340b91d693c6` validates holdings schema only
when the canonical file exists; existing corrupt and schema-malformed stores
still fail closed. An exact-registry-bound factsheet regression proves valid
evidence remains resolved when optional holdings are absent. The correction
suite, Ruff, compile and diff hygiene pass; `execution_allowed=false` and all
lifecycle/authority state remain unchanged. Freeze the replacement head and
repeat both reviews plus fresh H-tier gates in parallel.

Replacement exact head `f81a16c0fe349450e889a22c6780aa1a85bad1ad` was
rejected after both parallel reviewers completed. The complete finding set is
review evidence predating the exact report `known_at` and an identity-bearing
holdings store with an unrelated schema being silently skipped. Run
`31249002466` passed status and supply-chain checks, then was cancelled as
stale immediately after rejection.

Consolidated correction commit
`2bb6f818ddceeb1fcdea66727e59c0c446c8e243` enforces review/ingestion
chronology in canonical, supplied and defensive structural paths and requires
the writer's required schema on every existing canonical holdings store. The five
directly coupled test modules, Ruff, compile and diff hygiene pass; lifecycle
authority and `execution_allowed=false` are unchanged. Freeze one replacement
head for both reviews and fresh H-tier gates in parallel.

Exact head `bb72a93ba3c874e061c9b9668cc4950e90324a33` was rejected after
both reviewers completed. The valid consolidated set is malformed existing
holdings retained by merge, concurrent holdings lost updates, a review writer
publishing before exact `known_at`, and a cache regression that returned before
the structural loader. Release run `31250191446` passed classifier,
supply-chain, candidate validation and preflight, then was cancelled as stale
while package and pilot jobs ran. The claimed `issues/open.md` manifest
mismatch is expected `programme-generation.v1` LF-canonical hashing; two
mechanical generations and check mode were byte-clean.

Combined correction commit
`4630445c0380b9ad5dae56fb0fd588d241f8fb8a` fully validates canonical
holdings at load, merge and publication, gives all holdings writers one
complete-transaction guard with registry-first lock order, rejects and
pre-validates future-bound reviews, and reaches the structural loader in the
cache corruption test. The six directly coupled test modules pass at 100%;
Ruff, compile, generator check and diff hygiene pass. Lifecycle authority and
`execution_allowed=false` remain unchanged. Freeze one replacement head for
both reviews and fresh H-tier gates in parallel.

Exact head `8c48b7199705396d42bb137f72a65c46b3258241` was rejected after
both reviewers completed. The newly reproduced defects are an empty existing
Parquet bypassing schema validation and the document-coupled writer publishing
its post-binding holdings frame without staged semantic validation. Run
`31252092595` passed classifier, preflight, supply-chain, candidate validation
and lint/type gates; Linux and Windows each timed out in the unchanged
1,800-second full-test stage, terminal validation failed, and the pilots were
cancelled as stale.

Narrow follow-up commit
`8a94de3613f02f58c10de8571895c86c05e0342d` validates schema before any
empty-frame return and validates the complete post-binding frame before and
from staged Parquet publication. Direct load, merge and no-write rollback
regressions pass with the full holdings and ISSUE-0104 correction modules;
Ruff, compile and diff hygiene pass. Lifecycle and `execution_allowed=false`
remain unchanged. Freeze one replacement head for both reviews and fresh
H-tier gates in parallel.

Exact head `3581a1b2195890d08baa3fffb1ae04d8b3f118fe` received an
independent risk approval but was rejected by the whole-diff review after both
verdicts completed. Registry ordering could choose a different annual or
half-year source for the document matrix and change the structure provenance
hash. Release run `31254041778` passed classifier, supply chain, candidate
validation and preflight, then was cancelled and discarded as stale.

Bounded correction commit `17194503a000de86b723e5e12207495a201db604`
selects the latest chosen family revision deterministically by document date,
known-at time and source identity. The annual/half-year order-invariance
regression, all 86 structure tests, Ruff and diff hygiene pass. Lifecycle
authority and `execution_allowed=false` remain unchanged. Freeze one new
exact head and repeat both reviews plus fresh H-tier gates in parallel.

Replacement head `aab53ce37e58384ed4c2ae0c79217194a6b4fd97` received
whole-diff and risk approvals; its only review note was a non-blocking
report-row ordering follow-up. Fresh run `31255297689` passed classifier,
supply chain, candidate validation and preflight, but both serial package
suites timed out at exactly 1,800 seconds and terminal validation failed.
Diagnosis reproduced a valid backtest cache read taking about 20 seconds
because structural evidence was replayed once per signal row.

Single blocker correction commit `0993e85a0093103884bc5ba413f95a14fd9a335c`
batches cache readback by decision date/instrument and vectorizes the canonical
no-evidence case while retaining exact cap/hash comparison. Cache readback
falls from about 20.2 to 0.8 seconds and snapshot construction from about 26.1
to 4.8 seconds. Direct cache/tamper regressions and the complete 69-test
backtest/correction modules pass; Ruff and diff hygiene pass. Freeze one final
exact head for both reviews and fresh H-tier packages/pilots; lifecycle and
`execution_allowed=false` remain unchanged.

Exact head `cc7f5748ebed06031f80f4c040e166e599a147fe` received risk
approval but was rejected after both parallel verdicts completed. The
whole-diff review demonstrated that null/sentinel instrument identities could
pass the empty-evidence cache path and that the batching regression did not
exercise non-empty evidence across multiple dates. Release run `31258800287`
passed classifier, supply chain, candidate validation and preflight, then was
cancelled and discarded as stale.

Consolidated correction commit `3c6eac38be61677e1fcd4a1a6e785cc96e8129bb`
rejects malformed cache identities before normalization and proves non-empty
structural replay is batched once per unique decision date while exact cap/hash
tamper rejection remains intact. The complete 77-test backtest/correction
modules, Ruff and diff hygiene pass. Freeze one new exact head for both reviews
and fresh H-tier packages/pilots; lifecycle authority and
`execution_allowed=false` remain unchanged.

Exact head `df97611e8fcfa5d9b1e8db00e31c882214ead1fe` was rejected after
both parallel reviews completed. Both reviewers accepted the cache correction;
their newly demonstrated findings were union-schema expansion changing
retained holdings provenance and stale/ineligible holdings claims resolving as
structural confidence evidence. Release run `31259494785` was cancelled and
discarded as stale.

Combined correction commit `811c094ae5f408f35f2f8fb569929c9eb2a5fc2a`
uses one fixed canonical optional-identity schema for holdings provenance,
covers sequential and concurrent ticker/ISIN merges, and rejects stale, aged,
incomplete, non-issuer and non-score-eligible holdings claims at structural
consumption. The 229-test backtest, holdings, structure and correction suite,
Ruff and diff hygiene pass. Freeze one replacement head for both reviews and
fresh H-tier packages/pilots; lifecycle and `execution_allowed=false` remain
unchanged.

Exact head `91cbf92e70afe339b8a835edf7f99b11eb319c5b` received a
whole-diff approval with one non-blocking concurrent source-ID assertion, but
risk review demonstrated a future-dated holdings claim could produce negative
age and evade the stale check. Release run `31260389662` was cancelled and
discarded as stale after both verdicts completed.

Narrow follow-up commit `2efad098e514f4722f21e53fa771f452aeb5bb3b`
rejects holdings dated after the effective decision, proves those claims stay
unresolved with zero confidence and invalidate a forged cached replay, and
asserts concurrent mixed-schema imports retain both expected source IDs. The
231-test backtest, holdings, structure and correction suite, Ruff and diff
hygiene pass. Freeze one replacement head for both reviews and fresh H-tier
packages/pilots; lifecycle and `execution_allowed=false` remain unchanged.

Exact head `52d2eb31096b141c23850fcc60ccbc89c445e9a3` received risk
approval but was rejected by the whole-diff review after both verdicts
completed because an arbitrary non-empty signal ID outside the configured
universe could pass the empty-evidence cache path. Release run `31261532414`
was cancelled and discarded as stale.

Minimal correction commit `13e0b378e3686dffe9a5e5bdd9901d9f2b858d50`
binds every cached signal ID to `config.universe.enabled_ids` before either
cache-validation path and adds the unconfigured-ID regression. The complete
79-test backtest/correction modules, Ruff and diff hygiene pass. Freeze the
final head for both reviews and fresh H-tier packages/pilots; lifecycle and
`execution_allowed=false` remain unchanged.

## Completed UPDATEV2-0018 parser lane

ISSUE-0103 completion PR #648 merged exact reviewed head
`80647cd7b62bd5a9ce047747e6b0af6e9b44a064` as
`745dfd9f747f95aa6cb0e3cbc6f25c4ac5a2de0c`. Writer `30761603662`
accepted the exact two-hop aggregate with zero-action readback and
`execution_allowed=false`; a fresh generic live reconciliation also returned
zero actions at plan SHA
`35324f6f663a8455b0501dd7f627b24807c72987dda19f532afb91e71dd20692`.

Canonical order now selects ready no-dependency `UPDATEV2-0018`, which supplies
the bounded report-extraction dependency for planned ISSUE-0104. The first
uncommitted implementation was rejected on reproduced integrity defects and
is preserved at
`C:\Users\thor2\AppData\Local\Temp\updatev2-0018-rejected-attempt-20260802-001`;
it is not an integration candidate.

The clean v2 lane
`C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_updatev2_0018_v2` on
`codex/updatev2-0018-product-20260802-v2` is rebased onto exact main
`772d297264c071f83bb668d2190723e969b12cde`. Its H-tier product scope is
three explicit local ETF report kinds, page provenance, hard child-process
resource bounds, immutable source identity, serialized atomic persistence,
advisory fingerprint-bound review, bounded report-conflict visibility and the
Trust Evidence surface. ISSUE-0104 scoring, providers, OCR, generative
extraction, external writes and execution remain protected. Root focused
validation at `60430fdd29b37ac3e700a368417e07674ce36c7f` passes all 112
focused cases with one platform-specific skip plus Ruff, compile, byte-clean
generation and diff hygiene. The product transaction includes only the legal
`ready -> in_progress` canonical hop and schema-v2 candidate/append-only
authority for reviewed semantic plan
`be182dd37470ce7ae8804f8ffc704e5f3bfdb7a1640d5a1afe883ef2ba28134a`;
`score_eligible=false` and `execution_allowed=false` remain. Independent
exact-head review and fresh Linux/Windows H gates are next, followed by
ordered-writer and generic zero-action readback before compact two-hop
completion.

Whole-diff review rejected `3b67dc43...` after reproducing erased review
history on parser/template revision. Corrected checkpoint
`b14b5f272a69f9d2c8824fbb161316d3b5382caa` makes each parser/plugin
revision a separate extraction identity, retains the prior reviewed row and
fails closed on same-revision fingerprint drift. The focused product suite now
passes 113 cases with one expected Windows skip; repeat exact-head review
before the H gates.

Risk re-review reproduced same-revision fingerprint drift when either the
report or registry counterpart was replaced by a valid store lacking the v2
identity. Corrected checkpoint
`d95c28a89e24b22123f72d9ded63327b3445982f` now requires equal single-row
identity cardinality across both stores before re-import and preserves all
bytes on failure; both divergence directions have regressions.

Both exact-head reviewer verdicts were collected before correction. The
remaining reproduced cases were a physical duplicate registry identity hidden
by normalization and an orphaned prior revision bypassed by importing a new
parser/template identity. Consolidated correction
`84587edd346d06bfa469b9a1600a8789ff59b323` rejects raw duplicates and
requires complete v2 report/registry identity-set equality before processing
any incoming revision; same- and changed-revision divergence tests preserve
all bytes on rejection.

PR #651 run `30771627783` passed classifier, status guard and supply chain but
protected preflight found the three new report-control keys missing from the
UI acceptance inventory. The bounded product correction adds exactly those
import/verify/reject contracts and explicit button-inventory coverage before a
replacement exact head is frozen.

PR #651 then merged independently approved exact head
`ccff5d7421d01df7bdcbfde3f3158893f5c449f2` as
`7bffd0c57a992f599008a658425fc23575b9aef8`. H-tier run `30772069784`
passed Linux, Windows and terminal validation and status guard `30772069791`
passed. Writer `30773099083` applied only `ready -> in_progress` with
zero-action readback; generic convergence `30773099086` produced no patch and
`execution_allowed=false` remains unchanged. The clean
`codex/updatev2-0018-completion-20260803` lane starts at that exact merge and
records only `in_progress -> implemented_initially -> integrated`, bound to
the reviewed PR #651 product evidence. Exact live plan
`ce935663ef8c49098b5b53f24fa0827b33370cc7f134cb1d946de6eddf9d56d7`,
replay authority `6d5f03adc998d774a53d517bcb110d7d02da442ce8dbf8a42a5457238719749a`
and candidate ref
`bc7b8e36f23681298376e15fe631b463001b2ffeaf253038383395aa849800b3`
bind the aggregate transaction and preserve `execution_allowed=false`.
Exact H-reviewed range `772d2972...ccff5d74` refreshes the reusable-evidence
sidecar for subsequent eligible control-only transactions. The sidecar changes
in this PR, so reuse is intentionally withheld and the classifier requires
fresh package gates rather than accepting self-authorised evidence.

## Completed ISSUE-0102 and current bounded readback repair

Bounded repair PR #640 merged independently reviewed exact head
`049cc5fac353b380090694f059412ec877df6cc1` as
`874c9ef277350547ca3eca28d5d5c808d7dea7bb`. H-tier run `30743061770`
passed both authoritative package platforms and terminal validation. Ordered
writer run `30743990686` projected ISSUE-0102 `planned -> ready` and proved a
zero-action post-write readback; generic convergence run `30743990684` passed
and `execution_allowed=false` remains unchanged.

Product PR #641 merged independently approved exact head
`671ebac2ec5c0fbdd4afc6d9d0f1c953a1ffaa6b` as
`4a0b87a0a7e18633ffde1fa69e59baa40ce5e03e`. Tier-O run `30744924925`
and status guard `30744924900` passed. Ordered writer `30745092252`
projected ISSUE-0102 `ready -> in_progress` with zero-action readback; generic
convergence `30745092242` passed and `execution_allowed=false` remains false.

Completion PR #642 merged exact approved head
`b9cf650af3b38e69e183b34b569fced99022fd3c` as
`0848d93edbae6ecd228d0d1e1620dbd99722092c` after run `30745452805`
passed both package platforms and terminal validation. Writer `30746368016`
applied the two-hop aggregate, proved `zero_action_readback=true` and retained
`execution_allowed=false`.

`THROUGHPUT_CONTINUATION` reader repair PR #676 merged reviewed head
`aad1635b2ae1f1a61e2b78cc8c8e376a2ba98408` as exact main
`4e601b44a8f0373f37813da4391121aebee4a67a` after H-tier run
`31498834325` passed. Sequence 23 remains unprojected with zero transport
writes and no legal fresh-run retrigger; the explicitly prohibited recovery
expansion is recorded separately and not reopened. Exact-main ISSUE-0019
criterion audit found no product gap. Select dependency-ready ISSUE-0021 for
the next bounded product lane, preserving local-only analysis, immutable live
ledger state and `execution_allowed=false`.

`ISSUE_0021_PRODUCT_READY_FOR_FREEZE` implements the final portfolio-sandbox
delta on exact base `4e601b44a8f0373f37813da4391121aebee4a67a`:
snapshot/view lineage, canonical mixed-asset capability outcomes, existing
optimiser/risk/cost composition, structured constraints and why-not evidence,
atomic candidate/result persistence, deterministic before/after export and a
checksum-bound pre-ISSUE-0130 draft-only hand-off. No live ledger, proposal or
execution write exists. The 96-test affected suite plus Ruff, compile,
generated-state and diff checks pass; classification is H, so freeze one head
for parallel exact-head review and full hosted Linux/Windows/terminal gates.

`ISSUE_0021_REVIEW_CORRECTION` invalidates head
`62cb487212b5cee98a05464887c5c799d761af9d` and run `31506000586`. The two
parallel reviews found seven deterministic snapshot, capability, persistence,
constraint, hand-off-integrity and mixed-asset UI defects; hosted preflight
found the missing export/draft acceptance contracts. One consolidated bounded
correction now has line-level classifier/source binding, deterministic
fail-closed duplicate aggregation, target-only canonical resolution, atomic
cross-bound reads, complete hand-off checksums, aggregate constraint rejection,
mixed-asset controls and both UI contracts. The complete 185-test affected
suite and offline smoke pass with all local static/generated checks. Freeze one
replacement head for the repeated parallel reviews and fresh H-tier gates.

`ISSUE_0021_POINT_IN_TIME_CORRECTION` invalidates replacement head
`a531e63e219fa469e395516889096b35a846a0f3` and run `31509217777`. Both
repeated reviewers demonstrated that an as-of/source-identity-only change was
not reported stale and that recomputed-checksum derived payload tampering was
not compared with canonical analysis. The final bounded correction includes
as-of and selected source identity in stale reporting and requires exact
canonical result equality before surfacing stored evidence. Focused sandbox/UI,
Ruff, compile and diff checks pass; repeat final exact-head review and H gates.

`ISSUE_0021_DATA_SHAPE_CORRECTION` invalidates head
`5a81d4866388fa18ff81e9cbbf4799eaff80fb31` and run `31510633704`. Final
review reproduced sparse lineage NaN drift inversion, incomplete duplicate
capability ordering and an unfiltered/unbound rebalance preview. The bounded
fix uses strict optional boolean lineage, total deterministic capability order
and selected-view/source-bound preview evidence, with exact focused regressions
passing. Freeze and repeat final exact-head review plus fresh H-tier gates.

`ISSUE_0021_PROVENANCE_PREVIEW_CORRECTION` invalidates head
`0b57ede3c30214fa6261a84f11fbd9b032ef930e` and run `31512179961`.
Production holdings vintage/provider changes are now line-bound and cited in
the selected snapshot, suppressing stale results, while mixed-asset targets
receive an explicit source-bound inapplicable result from the ETF-only discrete
rebalance preview. Exact regressions and focused checks pass; freeze for final
review and fresh H-tier evidence.

`ISSUE_0021_ZERO_TARGET_PREVIEW_CORRECTION` invalidates head
`bc08cf83f974befb00ca99692ef26bd9afc9c867` and run `31513745409`. A held
mixed asset with a zero target could bypass the positive-target guard and reach
the ETF-only preview as a false sell. Every selected or targeted mixed asset is
now explicitly inapplicable regardless of target weight, with the exact AAPL
zero-exit regression passing. Freeze for final approval and H-tier evidence.

Generic-readback repair PR #643 merged independently approved exact head
`f8f28c94ae8f4a6f8f15dd8a5ad187cd35dafd2c` as
`bbe8a789d05a7df688661eb8e2370bb26583dc8f` after H-tier run
`30746716333` passed both package platforms and terminal validation. Automatic
convergence `30747829943` passed exact main with zero actions; the sole repair
cycle is closed.

Dependency PR #644 merged corrected and independently approved exact head
`8ff50cfc2ef0b1c6d291b57944082b5fde00877f` as
`4324ee6af1321cf7ea60a6f03b381c1f1979edb0`; run `30748705677`, guard
`30748705679` and exact-main convergence `30749425839` passed.

Readiness PR #645 merged independently approved exact head
`5b5edb44307244e231582e268e227fcf63c211a1` as
`2428af72525474d306cf9c04e6c9ecdaef213caa`; run `30749699624` passed both
package platforms and terminal validation. Writer `30750550860` applied only
ISSUE-0103 `planned -> ready` with zero-action readback; convergence
`30750550864` passed. A fresh generic exact-main live reconciliation then
returned zero actions at plan SHA
`4b5797a809179b80f1f964cd4080bff436411e23544b7abb4e5cb0ead42df71f`.

The clean `codex/issue0103-product-20260802` lane starts at exact merge
`2428af72525474d306cf9c04e6c9ecdaef213caa` with an empty diff. Its bounded
scope is ISSUE-0103 ETF economics, fee, tracking and closure-quality analysis,
focused tests and the ETF Economics panel. Existing ISSUE-0106 liquidity,
permissions, authority boundaries and `execution_allowed=false` must remain
unchanged.

The finished product diff uses typed local total-return evidence, explicit
identity/currency/convention/checksum and known-at replay, declared
business-daily tracking coverage, explicit fee and currency-amount units, and
a versioned provenance-bound closure proxy policy. Normal snapshot loading
feeds the ETF Economics panel; absent or inconsistent evidence fails closed.
Root validation passed 120 focused/relevant tests and the final 30-test
economics suite, Ruff, compile, architecture and diff checks. Independent
whole-diff and financial/point-in-time reviews approved the corrected stable
diff; ISSUE-0106 liquidity is byte-identical and `execution_allowed=false`.
Exact reviewed product evidence commit
`1d3e7515c78d73cbd5d767d4ede2f82f838b0077` is immutable after 187 affected
economics, market-adjustment and UI tests plus independent whole-diff and
financial/PIT approval. The narrowly corrected classifier treats the canonical
`market_adjustments.py` calculation/authority surface as H while preserving
ordinary product and E-tier checkpoint classification. Product PR #646 merged
independently approved exact head `31e12c1ee0a9390d13c91a5014e3f32915da4bf8`
as `f245a3f1cf26f074acde50cb9f3e4e1b891bd60a` after H-tier run
`30758046593` and guard `30758046561` passed. Writer `30759189744` applied
only ISSUE-0103 `ready -> in_progress` with zero-action readback; convergence
`30759189762` passed and `execution_allowed=false` remains false.

Completion preparation first failed closed before authority creation on the
unchanged unresolved `UPDATEV2-0015` placeholder. Bounded repair PR #647
merged independently approved head `a7d70bc11a91e88ba2f3258da34b697fa02ef058`
as `124a3f0279850ea034a93c9cb750a382bcfc35c9` after H-tier run
`30759893469` passed. The fresh `codex/issue0103-completion-20260802-v2`
lane starts at that exact main and records only
`in_progress -> implemented_initially -> integrated`, bound to PR #646 and
its merged product commit. Replay authority
`b8487fad9581689407475c071bb164db6ebe47db1c7391209e24721ee5771226`
preserves dependencies and `execution_allowed=false`; focused E-tier guards,
exact-head review, merge and writer/readback verification remain.

## Prior convergence repair checkpoint (superseded)

PR #639 merged as `26a3b5e7902b1c77df00d15f8e4ece472828f744`; its read-only
Programme convergence run `30739727616` failed closed with exactly one
status-only update at live-plan checksum
`4754b3f8b395c3c3d6595a4756a6c9c4a2b20bd2303516745212227f94a823cc`.
The bounded repair lane is branch
`codex/pending-status-convergence-20260802` in
`C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_pending_status_convergence`,
based on exact SHA `26a3b5e7902b1c77df00d15f8e4ece472828f744`; it remains
uncommitted and no new PR or merge is claimed here.

The permitted repair cycle is one fail-closed append through the existing sole
writer: schema-v2 status authority accepts exactly one legal status-only hop to
`ready`, `in_progress` or `integrated`, bound to the exact issue/remote
identity, parent/head, candidate, plan, ledger and workflow attestation.
Downgrades, skipped transitions, terminal/unrelated statuses, create/close/
reopen/blocked actions, non-status deltas and malformed projections remain
rejected. The accepted comment projection is authoritative when the raw body
anchor lags. The unchanged completion authority remains exactly
`in_progress -> implemented_initially -> integrated`. The classifier
correction is limited to exact active-goal and established
active-goal and current B04 chronology paths as E; invented or other plan paths
and all protected workflow, script, policy, security, authority, persistence,
financial and release surfaces remain H. The abandoned deferral-only attempt failed closed and was
restored. A fresh live read reproduced exactly one ISSUE-0102 status-only
update at plan checksum
`4754b3f8b395c3c3d6595a4756a6c9c4a2b20bd2303516745212227f94a823cc`;
repository-only preparation produced authority
`1e9de93977b28d6fc60f9992c6bad5f0fe4fc3f1a50a777376e6300810509ab1`
and candidate SHA-256
`25f4a2477a68702a584aae59e2a21be4cc9527aa6bc1642b163757f7c3bb9f21`
for `planned -> ready`, preserving `execution_allowed=false`. The focused
authority/classifier/summary suite passed 286 tests and the root four-suite
rerun passed 225; Mypy, targeted Ruff, compile, workflow parsing, diff hygiene,
atomic generation and byte-clean check mode passed. H-tier CI and independent
review/risk review remain pending; no PR or merge is claimed.

`IN_PROGRESS/READINESS` ISSUE-0102 dependency PR #638 merged exact reviewed
head `871ea037c594844a0de9e72e7dbabd3405244b76` as
`179e16c71328c43a9475dce60743a2d1aeda5aa7`. Release run `30737461361`
passed classifier, preflight, supply chain, authoritative Linux/Windows package
gates and terminal validation; guard `30737461338` passed. Convergence run
`30738361187` was zero action at checksum
`da979ae3fef7344ff4e492bd4468f8a3653e329f6121cb13ba9f2e2a003c1b8f`.

The clean `codex/issue0102-ready-20260802` lane starts at that exact merge and
advances only ISSUE-0102 `planned -> ready`. Acceptance evidence is bound to
the reviewed complete ISSUE-0098 edge while all software, semiconductor,
healthcare and biotechnology implementation scope remains pending. Product
code, dependencies, GitHub authority and `execution_allowed=false` are
unchanged. Mechanical generation/check, classifier-selected H-tier validation
for the checkpoint-plan changes, exact-head review, merge and convergence are
next.

`IN_PROGRESS` ISSUE-0101 is converged and ISSUE-0102 is the next
implementation-order product record. Recovery PR #636 merged as
`07da10ee0403033da30071eab5cfb5205c0af147`; bounded recognition repair PR
#637 merged as `2e3d69541dccc5f71e868e4c55e85bef623cfbd3`; automatic run
`30737053331` verified zero-action GitHub convergence for #241 at checksum
`da979ae3fef7344ff4e492bd4468f8a3653e329f6121cb13ba9f2e2a003c1b8f`.

The clean ISSUE-0102 evidence lane starts at exact main
`2e3d69541dccc5f71e868e4c55e85bef623cfbd3` on
`codex/issue0102-dependency-0098-20260802`. It records only the sole
ISSUE-0102→ISSUE-0098 edge as complete against merged `peer-cohort.v1`
commit `fc734201b138d3f24fa68d8c07422322506d6fc5`. ISSUE-0102 remains planned
and retains all software, semiconductor, healthcare and biotechnology
formulas, event/runway/dilution logic and UI scope. The generated programme is
byte-clean; E-tier validation, exact-head review, merge and zero-action
convergence are next. Product code, GitHub authority and
`execution_allowed=false` remain unchanged.

## Active fast-path checkpoint

`COMPLETE/FROZEN` the bounded atomic-delivery repair is formally proven.
Plan-order repair PR #629 merged as
`b113ac8c205887c5f84d841445d2e52ca5101c04`; H run `30652483166` passed
Linux and Windows at 2,452 tests per platform. Formal ISSUE-0180 status PR
#630 merged as `45564c306643f8fbe97fe460979a04e25e6f41b9`. Its exact status guard
passed in `30656428462`; tier-E run `30656428457` correctly required and
passed the full 2,452-test Linux and Windows package gates.

Ordered writer `30658275241` appended one reviewed proposal and receipt for
authority `d7f3468a`, projected ISSUE-0180 as `integrated`, preserved unrelated
issue content and completed zero-action readback. Convergence `30658275236`
then succeeded by deferring to that proof. Git remains canonical; the
unchanged body status is the tamper-detectable bootstrap anchor and the
accepted comment chain is the effective GitHub projection.

The frozen 11-run compact-control sample reports execution p50/p95
`0.4000/1.2500 min` and queue p50/p95 `0.0500/1.8833 min`. E package skipping
was correct in `5/5` transactions, cache reuse was `10/46` (`21.74%`), and no
polling reduction is claimed. The issue-creation/status authority
infrastructure is frozen; expansion requires explicit user approval and a
demonstrated safety need. `execution_allowed=false`; broker, provider,
release and deployment authority are unchanged. The exact next product lane
is dependency-valid ISSUE-0101.

`ACTIVE` ISSUE-0101 now runs from fresh main
`8a0d1d9a7437770aa0567d9ae6787e3881832f27` in
`codex/issue0101-cyclical-adapters-20260731`. Its sole blocking edge is
complete. The bounded implementation owns local typed energy,
materials/mining and non-infrastructure industrial evidence, deterministic
cycle scenarios and read-only Instrument Detail projection only. Stop if the
industrial/infrastructure distinction requires shared routing redesign,
persistence, external authority, another sector child or ISSUE-0115 scope.
Programme-control, GitHub authority, providers, forecasts, recommendations,
optimisation, orders, broker authority and `execution_allowed=false` remain
unchanged.

`STOPPED AT REVIEW` the first ISSUE-0101 implementation and its one focused
correction pass 46 adapter/architecture tests and 94 broader Instrument
Detail/application tests, plus Ruff, compile, architecture-boundary and diff
checks. They are intentionally uncommitted because independent review proved
that the replay verifier still accepts self-rehashed source, cycle, formula
and routing forgeries; it also found three limitation/replay consistency
defects. Preserve the checkpoint and failure fingerprint. The next attempt
must use one canonical source-bearing validation path, not extend the partial
duplicate verifier. Do not push or broaden into persistence, providers,
shared classification or GitHub authority.

`IN_PROGRESS/H-TIER REPAIR` the dedicated clean worktree
`C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_status_replay` is at
base/head `0680429aa5c30477dc854ef80367a3cc5ff4010e` on
`codex/status-replay-two-hop-20260802`. The bounded scope is the additive
single-issue, exactly-two-hop `status_replay` authority/projection repair and
its focused adversarial tests plus durable policy/ADR/checkpoint text. The
prior rejected ISSUE-0101 evidence remains preserved outside the repository at
`C:\Users\thor2\AppData\Local\Temp\issue0101-invalid-recovery-evidence-20260802-001`
with patch SHA-256
`32488742f363e50f14c566b6890992e37a1a9843d0ed9ca7031fc32fc56e168c`; it is
not transplanted. Focused H-tier validation is pending; no result is claimed
here yet. Canonical ISSUE-0101 files, generated projections, workflow
permissions, external systems and authority/retry policy remain protected.

The entries below retain the chronological implementation and repair history.

`IN_PROGRESS/H-TIER FOLLOW-UP` initial repair PR #634 merged exact head
`676aaaeedadcf04c3a4644f4d10902a2c05bd311` as
`ff10762e8c000b2f2c834073e27a664bc20de143` after run `30724545238` passed
both package gates. The first E recovery then failed closed before producing a
candidate because replay preparation read lifecycle history from the generated
registry rather than authoritative programme control state. Its uncommitted
evidence is preserved at
`C:\Users\thor2\AppData\Local\Temp\issue0101-e-recovery-blocked-20260802`
with patch SHA-256
`2A2C65B7B5864D2A95ED641C46D0874667DFE50B20A551082C03B76DF531A4E2`.
The clean follow-up lane
`C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_replay_control_state`
on `codex/status-replay-control-state-20260802` binds preparation, apply and
terminal validation to `issues/programme_control_state.json` without changing
canonical ISSUE-0101, generated schema, workflows, product code or authority.

`IN_PROGRESS/H-TIER RECOVERY` follow-up repair PR #635 merged independently
approved exact head `91aea56ec60d9dfb92968c30428c0a02a35b5652` as
`a4aadf36cc6c0f8cbb356fff96b572919cf5857f`. H-tier run `30728917010`
passed classifier, preflight, supply chain, both package gates and terminal
summary; post-merge convergence run `30729715977` passed zero action. The new
clean recovery lane
`C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0101_replay_v2`
on `codex/issue0101-two-hop-recovery-20260802-v2` starts at that exact merge.
Canonical input records only ISSUE-0101
`in_progress -> implemented_initially -> integrated`, with both hops bound to
PR #633, product commit `0680429aa5c30477dc854ef80367a3cc5ff4010e`,
recorded independent review and tier-O product validation evidence. Product code, dependency
edges, unrelated issue state, workflows, authority and
`execution_allowed=false` remain unchanged. Mechanical generation/check,
bounded proposal/receipt preparation, H-tier review and full package gates, merge and GitHub #241
convergence are pending.

Recovery run `30731278862` passed the standalone guard and supply chain but
failed closed in authority preflight before package jobs: an unconditional
depth-one local base fetch converted the full exact-head checkout to shallow
history, hiding the reviewed product commit from the ancestry check. The
bounded correction skips that fetch when the trusted base commit is already
present and retains the existing fail-closed fetch/check fallback otherwise.

The corrected preflight then passed, as did supply chain and both authoritative
Linux/Windows package gates. Terminal validation still failed closed because
the validation-mode status-replay evidence omitted `replay_hops` and
`reviewed_product_commit`, although both had already been validated against the
candidate and ledger. The bounded follow-up projects exactly those two
identities for the existing terminal verifier; replay and mutation authority
remain unchanged.

`MERGED/CONVERGENCE REPAIR` ISSUE-0101 recovery PR #636 merged exact reviewed
head `10db96f6a3e877196352f28c11428b7ac9d4859b` as
`07da10ee0403033da30071eab5cfb5205c0af147`. H run `30733297748` passed
authoritative Linux/Windows package gates at 2,581 tests per platform and the
terminal summary; guard `30733297750` passed. Writer `30735911761` appended the
single aggregate proposal and receipt with `execution_allowed=false`, but
settled readback blocks because generic create-acceptance validation treats the
new replay markers as unknown despite ledger reconciliation projecting
ISSUE-0101 `integrated`. The clean H repair lane
`codex/status-replay-comment-recognition-20260802` starts at the merge and only
recognises valid replay markers as known managed comments; it adds no retry,
compensation or authority.

`MERGED` immutable dependency-only PR #608 from exact head
`937ec382dfab7acc74ad16e7e706b795c88e63a2` as
`b11b1d6783438df03847d7a1b45c3a4d7c1f2385`. Its single documented
unchanged-head retry passed Linux and Windows at 2,122 tests with zero
failures, errors or skips, and fresh-main GitHub readback is zero action at
checksum `23cff2eee691649a17d83f0e8ff5c2833c7b19303f57a2a182f1e75db354d143`.
ISSUE-0090 remains `implemented_initially`, both blocking edges are complete
and readiness is true. `IN_PROGRESS` ISSUE-0090 product work is paused while
the sole authorised worker implements ISSUE-0179 from fresh main.
`execution_allowed=false`, source/broker authority, PR #560, stale unmerged
PR #562 and open issue #241 remain unchanged.

ISSUE-0179's sole declared prerequisite, ISSUE-0178, is integrated at
`90106943ea4e7cd41909ca45eab185216bb8f45f`. The sole ISSUE-0179 worker and
its one focused correction are accepted at local commits `be6422e8` and
`286e3799`. Orchestrator integration atomically records the independently
verified ISSUE-0179→ISSUE-0178 edge as `complete`, leaves programme status
`planned`, and preserves `execution_allowed=false`. One command now publishes
the 39-file closed canonical projection and the second run is byte-clean; the
schema-1.3 guard passes while historical generation provenance remains
reachable and no new reconciliation tree is created. The exact next action is
the durable integration commit, exact-head H classification, draft PR and
complete Linux/Windows packaged gate.

`CORRECTED` draft PR #609 run `30416010061` passed classifier, schema-1.3
status guard and supply-chain but failed preflight before packages because the
new generation manifest hashed raw Windows CRLF bytes and was stale on Linux
LF checkout. The bounded correction at `877f39b4` normalises UTF-8 text line
endings while retaining exact binary bytes; an adversarial CRLF/LF fixture and
the complete 124-test affected suite pass. The failed run is not retried. The
next exact run `30416340531` passed classifier, schema-1.3 status guard,
preflight, supply-chain and both complete packaged platforms, but its terminal
summary could not attribute the flattened Linux and Windows artifact names.
The bounded correction at `ab188759` preserves artifact-name directories and
runs terminal-evidence construction under `always()` so a failed terminal
state remains auditable. The focused 126-test control suite, Ruff, MyPy,
compile, YAML, atomic freshness and exact schema-1.3 guard pass. Run
`30417788249` then passed both packaged platforms at 2,144 tests each but
exposed that pytest's JUnit count is nested below a `<testsuites>` root. Its
failed terminal summary was retained as intended. The bounded correction
recursively counts suites and propagates the immutable PR head rather than the
synthetic merge SHA; replay against the actual retained artifacts validates at
Linux/Windows `2144/2144`. Run `30419312173` passed all required jobs, but an
audit found its nominally green summary had added the 126-test preflight JUnit
to Linux, reporting `2270/2144`. The bounded correction counts only XML under
explicitly named Linux/Windows release artifacts; replay against the full
retained artifact set now validates truthfully at `2144/2144`. Prior runs are
not retried. Final run `30420622584` passed the complete H tier and truthful
terminal summary at `2144/2144`; PR #609 merged exact head `d72c07d1` as
`cfcf6e78`. Automatic convergence run `30421830231` passed its fresh-main
guard and atomic generation but live GitHub readback exited 4 because the
read-only workflow did not export its granted token to `gh`. The fresh-main
repair changes only token wiring plus its workflow assertion; permissions
remain read-only. The next action is focused validation and a protected H-tier
repair release, followed by automatic zero-action convergence evidence.

`MERGED/PROVEN` PR #610 passed complete H-tier run `30421980682` at truthful
Linux/Windows `2144/2144` and merged exact head `44c9ce5f` as `0573d489`.
Automatic convergence run `30444182563` passed exact main with a zero-byte
patch and zero GitHub actions at checksum `23cff2ee`.

`FOUND/REPAIRED LOCALLY` the first live E lifecycle projection exposed that
the committed reuse sidecar had been required to contain its own future
commit SHA. Sole worker commit `a6ee2a18` replaces that impossible contract
with immutable prior-H ancestry plus exact protected identities and
base-anchored, head-identical sidecar bytes. Its sole correction `136c6eb3`
completes the closed deterministic projection allowlist across all phases
without allowing arbitrary programme or plan files. The accepted head passes
136 affected tests, Ruff, protected MyPy, compile, atomic freshness and exact
H classification. Next is an immutable H repair PR head, followed by one
sidecar-only bootstrap commit bound to that reviewed head and a final H run.

`IN_FLIGHT/SECOND PREREQUISITE` draft PR #611 first passed immutable H head
`db52ec14` in run `30445604844` at truthful Linux/Windows `2154/2154`. The
reviewed identities are now anchored in the base-visible sidecar at exact
final head `7c7f9367`; run `30447413859` is the pending final H gate. A live
classifier-authorised E projection then exposed that the status guard assumed
exactly one appended acceptance record and could not validate ISSUE-0179's
required three distinct lifecycle events. The sole bounded worker repair at
`9dbda8e6` replays every appended record through the canonical transition
validator and rejects malformed, reordered, forged, extra or dependency-edge
mixed replays. Independent review passes 109 focused tests, Ruff, protected
MyPy, compile, diff hygiene and exact H classification; the real three-event
ISSUE-0179 projection passes with zero guard errors under status-only schema
1.2. Next is PR #611's exact-head merge, then transplant this protected-source
repair to fresh main and repeat the reviewed-head sidecar bootstrap before the
single live E lifecycle transaction.

`VERIFIED` PR #612 merged the protected multi-event guard repair after exact
H runs `30449330177` and `30451275797`; final Linux/Windows counts were
`2161/2161`. PR #613 then proved the complete ISSUE-0179 lifecycle at tier E:
reuse was authorised by exact identities, status guard and preflight passed,
and both package jobs were skipped in run `30453340819`. Exact head
`b005da9a` merged as `0e9195a2`. Checksum-approved plan `d468f6b4` applied
only ISSUE-0179/#581's managed status update to `integrated`; fresh readback
`673223ef` is zero action and preserves the open issue and
`execution_allowed=false`.

`IN_PROGRESS` ISSUE-0180's reviewed checkpoint transplanted cleanly to fresh
main as `6ed0dd3a`. A two-line integration correction at `567682d9` narrows
release requirement evidence for protected MyPy. The 29 focused tests, Ruff,
MyPy, compile and diff hygiene pass; exact classification is H. Next is the
remaining affected validation, immutable draft PR, and complete truthful
Linux/Windows packaged gate.

`MERGED/VERIFIED` ISSUE-0180 PR #614 passed H run `30453850014` at truthful
Linux/Windows `2169/2169` and merged exact head `ed314167` as
`1d4b390935bf050625d8a704ae31a87487fb7bb9`.

`REVIEWED/LOCAL PREREQUISITE` automatic convergence runs `30453521074` and
`30455673946` each generated a legitimate fresh zero-action plan but failed
because the committed reviewed sidecar necessarily described the earlier
remote inventory. Sole-worker commit `fc648623` moves checksum comparison
after mandatory zero-action, no-authority, schema and inventory validation;
nonzero actions remain rejected. Its single focused correction `3873d889`
makes the optional reviewed completion candidate one-shot by using it only
when the current main commit changed its exact path. The workflow retains
read-only contents/issues permissions and cannot apply, push or mutate GitHub.
Independent review passes 145 affected tests, Ruff, protected MyPy, compile
and diff hygiene. Next is the durable plan/metrics commit, exact H
classification, immutable draft PR, full Linux/Windows package gate, exact-head
merge and automatic fresh-main zero-action proof. ISSUE-0090 remains paused.

`MERGED/PROVEN` fast-path completion PR #615 passed H run `30456636457` at
truthful Linux/Windows `2171/2171` and merged exact head `c5befb5a` as
`97d1e364b46364baef7c23b5ba46af74a8a53e5a`. Automatic exact-main
convergence run `30458709210` passed in 25 seconds with every managed action
count zero. No manual convergence PR was required.

`IN_PROGRESS` normal product continuation resumes with ISSUE-0090 from fresh
main `97d1e364`. It remains `implemented_initially`; ISSUE-0072 and ISSUE-0075
are complete, readiness is true and `execution_allowed=false`. The first
bounded slice adds a deterministic fail-closed complete upstream snapshot
graph and dataset/source impact projection to the existing local catalogue.
It does not fetch providers, delete or compact data, change canonical status,
touch PR #560/PR #562/issue #241, or grant execution/broker authority.
Sole-worker commits `9ad7912d` and focused correction `f238130d` now expose
deterministically sorted transitive upstream nodes/edges, missing/stale/schema
and cycle state, plus dataset/source downstream impact including same-dataset
descendants. Independent validation passes 10 catalogue/UI tests, 40
audit/export tests, Ruff, compile, diff hygiene and issue-scoped
registry/compile/source smoke. The exact branch classifies H because the
required durable plans/SDD fail upward; next is an immutable draft PR and the
complete Linux/Windows gate.

`MERGED/VERIFIED` ISSUE-0090 continuation PR #616 passed H run `30460043778`
at truthful Linux/Windows `2177/2177` and merged exact head `0c99f3f8` as
`ba0c5850432bf20e40d8a660923ac126c834bf4e`. Automatic convergence run
`30461814321` passed exact main in 27 seconds with every managed action count
zero. Normal dependency-valid product work has therefore resumed and
integrated under the new workflow.

`AUDIT GAP` the optional post-merge completion candidate is staged but cannot
complete a genuine status transition: the convergence validator rejects every
nonzero plan and its workflow token has `issues: read`. The remaining bounded
prerequisite is an exact-main, committed-checksum-controlled, status-only apply
path that keeps ordinary convergence read-only, rejects any unreviewed or
non-status action, performs an idempotent zero-action readback and retains
`execution_allowed=false`. No broader GitHub write authority is accepted.

`REVIEWED/LOCAL PREREQUISITE` sole-worker commits `c8a6c645` and focused
correction `1cbe5d74` implement that bounded path. Ordinary convergence now
defers only the merge that changes the canonical candidate and retains
`contents: read`/`issues: read`; a separate path-scoped main-push workflow has
`contents: read`/`issues: write` and no contents authority. Premerge validation
binds the canonical candidate bytes to the exact reviewed PR head, expected
base, live remote inventory and semantic plan. Postmerge apply requires exact
fresh main and a direct parent, permits exactly one status-only canonical
transition to `integrated`, uses the existing approved-plan checksum guard and
requires an idempotent zero-action readback. Success and failure evidence omit
remote bodies. Independent validation passes 195 affected tests, Ruff,
protected MyPy, YAML parsing, compile and diff hygiene. No product, financial,
provider, broker or execution authority changed; `execution_allowed=false`.
Next is the durable metrics/checkpoint commit, exact H classification,
immutable draft PR, complete Linux/Windows gate, expected-head merge and
automatic exact-main convergence proof.

## Authority and outcome

Base revision: `b8eb6b4967d5655ed4e528ee9cb222690a424d57`
(`origin/main`). `PLAN_step3.md` is absent from both the working tree and
`origin/main`; it is not reconstructed. B03 is complete through integrated
ISSUE-0156. This batch follows the final-release specification and canonical
registry for ISSUE-0074, ISSUE-0098–ISSUE-0109 as applicable, ISSUE-0112,
ISSUE-0123, ISSUE-0157, ISSUE-0172 and ISSUE-0174.

The batch outcome is one local-first, point-in-time multi-asset analysis,
forecast, peer, benchmark and risk-profile contract. Shared schemas are frozen
before downstream consumers. Missing, stale, conflicted or unsupported
evidence remains explicit. Adjusted/total-return prices are required for
returns, risk gates remain authoritative and `execution_allowed=false`.

## Sequence

1. Review and record ISSUE-0098's existing ISSUE-0074 score and ISSUE-0083
   classification interfaces without overstating incomplete contracts.
2. Advance ISSUE-0098 through separate guarded readiness and implementation
   transitions.
3. Implement the smallest usable point-in-time peer-cohort and sector-adapter
   framework with deterministic fallback, support, exclusions, versioning,
   read-only UI lineage and tests.
4. Recompute the canonical graph after ISSUE-0098 integration and select the
   next dependency-valid B04 issue. Do not pull blocked downstream work
   forward.

## Active prerequisite

`IN_PROGRESS` review only ISSUE-0098→ISSUE-0074. The merged canonical score-v3
interface supplies typed asset-specific components, configured weights,
coverage/conflict handling, deterministic formula/source hashes and separated
score outputs. It does not yet supply ISSUE-0098's point-in-time peer membership,
effective sample size, robust statistics, hierarchical fallback, bootstrap
intervals or reusable peer stores. Record the edge as `partial_interface`;
leave ISSUE-0098 planned and ISSUE-0083 unresolved.

This step changes no product code, status, dependency list, acceptance
criterion, policy or authority. It requires the exact dependency-edge guard,
registry/status/document freshness, focused canonical-score and control tests,
supply-chain validation, diff hygiene and a zero-action GitHub projection.

The proposed 197-record registry has SHA-256
`ecc1b95ae86fcf89b21c8b67b3c64135dc1e597f5f6ec77826c8d3a11be37aa2`.
The live GitHub projection is the zero-action semantic plan
`f51ed48ed324a3d4fbe89da65cacb8285ebd5fb59bc222efe542f4c8f8cb7dec`.

`VERIFIED` PR #538 merged the first edge checkpoint as
`4e5540b982fc370a2312d64f78a454ef652ce940` from reviewed head
`aff8a4b947d9033eb1151a7d06ce0c039b6fdde8`. Status guard run
`30262850204` and supply-chain run `30262850140` passed; the redundant
evidence-only release run was cancelled. The post-merge GitHub readback
remained the zero-action plan
`f51ed48ed324a3d4fbe89da65cacb8285ebd5fb59bc222efe542f4c8f8cb7dec`.

`IN_PROGRESS` the second readiness review records only
ISSUE-0098→ISSUE-0083 as `complete`. The merged classification contract
provides point-in-time sector, industry, business-model and country/currency
context; confidence, alternatives and deterministic fallback; version and
score-invalidation tokens; immutable replay; and fail-closed sector-adapter
routing. ISSUE-0098 still owns cohort membership and peer statistics.

ISSUE-0098 remains planned with all declared dependency interfaces now
reviewed. The proposed registry SHA-256 is
`4935b3dc3ad8645251a31c0629eeaa9afa528607a669c610cccfba687cc7246b`;
the live GitHub projection remains the zero-action plan
`f51ed48ed324a3d4fbe89da65cacb8285ebd5fb59bc222efe542f4c8f8cb7dec`.

`VERIFIED` PR #539 merged the classification edge checkpoint as
`ec721a5576c3ce3a26690d906b256d94106d5db0` from reviewed head
`05831cba6b617ac4dd50936d647807422640d81e`. Status guard run
`30263254026` and supply-chain run `30263254064` passed; the redundant
evidence-only release run was cancelled. Post-merge GitHub readback remained
zero action.

`IN_PROGRESS` the separate guarded transition advances only ISSUE-0098
`planned -> ready`. Both declared dependency interfaces are resolved while
the score interface's limitations remain explicit. The 197-record registry
has proposed SHA-256
`8d21b82252ad512ec05b1135b18e5e281bb8a4f2e4dffdcccf3964a3ede2d494`.
The reviewed GitHub plan contains exactly one Programme-status update for
open issue #238 with semantic SHA-256
`68cef5b7a35b34bda5043b84ba2c3782d218a5b8a9b52b8e7f1b40b7cab4aaf2`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #540 merged ISSUE-0098 as ready in
`b3dd4decbef105ef8eff44abc5a97820507ea64a` from reviewed head
`5dcfddff00b74b70998759e790d1a8334018d60a`. Status guard run
`30263595362` and supply-chain run `30263595352` passed; the redundant release
run was cancelled. Checksum-approved GitHub plan
`68cef5b7a35b34bda5043b84ba2c3782d218a5b8a9b52b8e7f1b40b7cab4aaf2`
applied only #238 and zero-action readback
`df90dd12bae8df17922cc4b913e26669ac3524548f6057c52dba5338d0349456`
verified convergence.

`IN_PROGRESS` the separate implementation hand-off advances only ISSUE-0098
`ready -> in_progress`. The smallest usable product is a versioned local
peer-cohort/metric contract using frozen point-in-time classification and
universe evidence: deterministic leaf-to-parent fallback, effective sample
size, median/MAD, weighted empirical CDF, winsorisation, hierarchical
shrinkage, seeded bootstrap intervals, explicit members/exclusions/support,
sector-adapter routing and read-only Instrument Detail lineage.

Excluded: downstream sector-family implementations, forecasts, expected
returns, recommendations, optimiser/order work, remote providers and live
execution. The proposed registry SHA-256 is
`6f7fc25da846cec6c6ee23c131bf77f918d36f17b27e0ee0f24751699394178c`;
the reviewed one-update GitHub plan is
`af636dec29f5aa00750f1a09bb1d30c46a3a2f08cd71cfec37b98eafb6a7426a`.

`BLOCKED REVIEW CHECKPOINT` the initial ISSUE-0098 implementation and its one
authorised focused correction were not accepted or committed. On unchanged
base `3beeb75071d5c063d870c42e7f07a66a9860b7b1`, a historical cohort admitted a
`PeerObservation` whose `InstrumentContextV2.decision_time` was in the future
because eligibility checked only the observation timestamps. A second
reproduction showed `PeerCohortStore.append` accepting an arbitrary
`result_hash` that did not authenticate the canonical projection payload.
These are point-in-time and immutable-audit contract failures. The branch
remains unmerged; `execution_allowed=false`. Any later authorised attempt must
first add failing tests for both reproductions and must not reuse the rejected
implementation wholesale.

`AUTHORIZED REPAIR` on 2026-07-27 the user explicitly authorised one new
bounded repair attempt in this existing worktree, retaining the reviewed
ISSUE-0098 implementation. The only product blockers in scope are exact-cutoff
ISSUE-0083 classification resolution/validation and canonical peer-result
hash verification before write and on replay. One Sol-low worker may implement
the repair and receive at most one focused correction. No other issue or
downstream analysis work is authorised; `execution_allowed=false`.

`REVIEWED REPAIR CHECKPOINT` the worker implementation plus its one focused
correction are accepted for release validation. The data boundary now resolves
target and candidate ISSUE-0083 contexts at exact UTC cut-offs; analysis
excludes invalid candidate lineage and fails closed for an invalid target.
Canonical schema, frozen-universe, formula, hierarchy, statistical, warning
and authority fields participate in the result hash. The store validates
before creation and independently reconstructs and recalculates replay.
Orchestrator reproductions passed for future-context exclusion, historical
revision invariance, forged-hash rejection without storage residue and
rehashed SQLite tamper rejection. Focused evidence is 52 peer/classification/
architecture tests, 85 Instrument Detail tests and 9 architecture/document
tests, plus Ruff, compileall and diff hygiene. Protected Linux and Windows
release gates and supply-chain validation remain required before merge.

`IN_PROGRESS` product PR #542 merged the reviewed ISSUE-0098 peer-cohort tree
as `fc734201b138d3f24fa68d8c07422322506d6fc5`. Protected Linux and Windows
evidence passed package build, artefacts, source/package parity, packaged
smoke, performance and policy checks. A deterministic generation-base refresh
left only the documented B03 simple-score baseline on both platforms; no
ISSUE-0098 or changed-path test failed. Supply-chain validation passed and
`execution_allowed=false`.

The separate guarded convergence advances only ISSUE-0098
`in_progress -> implemented_initially`. The proposed 197-record registry has
SHA-256 `c77d4b5e306f6d50425be783751cfd6ecf361d40bd42da31dd5a4f6e9aa11f76`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #238 with semantic SHA-256
`e9d4d3eee2d726a2614d775c8ac2f7cc4240fa36b9be82906bc6472f290b51be`.
No dependency, scope, acceptance, policy or authority change is included.

`VERIFIED` product PR #548 merged ISSUE-0099 as
`55c41b57cc222ce365b27adcf9dadbb0742aeca3` from exact reviewed head
`a8e07c3a2c20239b8b11fa8c65e6313efcf29e2a`. The financial-institution
adapter now preserves typed bank, insurer and diversified-financial metrics,
units, direction, period, reporting standard, jurisdiction, source authority,
point-in-time classification lineage, deterministic stresses and explicit
missing-data authority caps. Instrument Detail exposes verified read-only
evidence and `execution_allowed=false`.

Protected release run `30314202998` passed Linux and Windows package build,
artefact, source/package parity, packaged smoke, performance, policy,
security, privacy, legal and SBOM checks. Both full suites retained only the
exact authorised B03 simple-score invalidation node and fingerprint; no
ISSUE-0099 or changed-path test failed. Final-head status guard
`30315386005` and supply-chain run `30315386015` passed; redundant
manifest-only release run `30315386073` was cancelled.

`IN_PROGRESS` the separate guarded convergence advances only ISSUE-0099
`in_progress -> implemented_initially`. The proposed 197-record registry has
SHA-256 `fe2ea7354395c6246853131a6dfb2f2abc97d729b43fe6f22fb743520f7609f8`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`64f05b2fc8b4d6fe319fabe16871a0289add24c9eff9197e93a7f7aecea7c9a6`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` implemented-initially PR #549 merged ISSUE-0099 as
`b41a43dccf28512eaee19618341db4b3f34c6d5c` from reviewed head
`6f6c9950ddc0ed6f69c607bc731b84873817f094`. Status guard run
`30315660329` and supply-chain run `30315660332` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`64f05b2fc8b4d6fe319fabe16871a0289add24c9eff9197e93a7f7aecea7c9a6`
applied only #239, and zero-action readback
`3fc8ff2c316b28e94671bb0521b3eed4310955d0c856b3edaede3fd625113227`
verified convergence.

`IN_PROGRESS` the final separate convergence advances only ISSUE-0099
`implemented_initially -> integrated`. The proposed 197-record registry has
SHA-256 `9cfe0e13df83f6fc65ac539721378d5efaa47d74a266fb3cec5a3bf6166a9766`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`f9e546349595ee9df28e47585e027f790dd0b5b4bf9f3ad1fb13e1eddcaee978`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` integrated PR #550 merged ISSUE-0099 as
`ecbcfbf8b5706b19996d720a1aeaf945608e7dc9` from reviewed head
`88a4084987c334060bdbd1ccdcc40d6d958a51e1`. Status guard run
`30316036205` and supply-chain run `30316036204` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`f9e546349595ee9df28e47585e027f790dd0b5b4bf9f3ad1fb13e1eddcaee978`
applied only #239, and zero-action readback
`79c8c3ca0be0675b4718247c8f16767a85ccc7a744a6899a4c456350b2a14fc6`
verified final ISSUE-0099 convergence.

`IN_PROGRESS` the next dependency-valid B04 prerequisite reviews only
ISSUE-0100→ISSUE-0098. The integrated `peer-cohort.v1` contract supplies
versioned sector-adapter registration and metric-applicability lineage,
classification-gated stock-only routing, exact-cutoff leaf-to-parent cohorts,
explicit exclusions/support, robust peer statistics and verified replay.
ISSUE-0100 retains all REIT, utility and infrastructure formulas, source
evidence, rate/inflation/refinancing stresses and Real Assets UI rationale.

Record the edge as `complete` while ISSUE-0100 remains planned. The proposed
197-record registry has SHA-256
`fd09ae9dab75686c6a44b4d2b87364ad03a2140b0309df0dd5b517888473becf`;
the live GitHub projection remains the zero-action semantic plan
`79c8c3ca0be0675b4718247c8f16767a85ccc7a744a6899a4c456350b2a14fc6`.
No product, status, dependency-list, scope, acceptance, policy or authority
change is included; `execution_allowed=false`.

`VERIFIED` peer-framework edge PR #551 merged as
`65d35e21c397aaca77483cacc88babebdffd0014` from reviewed head
`27b82c5c714861d8a03165c8560ab15f08e0b653`. Status guard run
`30316338360` and supply-chain run `30316338359` passed; the redundant
evidence-only release run was cancelled. The live GitHub projection remained
the zero-action plan
`79c8c3ca0be0675b4718247c8f16767a85ccc7a744a6899a4c456350b2a14fc6`.

`IN_PROGRESS` the separate guarded readiness transition advances only
ISSUE-0100 `planned -> ready`. Its sole blocking dependency interface is
reviewed complete while all REIT, utility and infrastructure formulas, source
evidence, rate/inflation/refinancing stresses and Real Assets UI rationale
remain unimplemented ISSUE-0100 scope. The proposed 197-record registry has
SHA-256 `e0b645c78be13d62ab62fe2f5a4093835bc288895a28f7513fe7fd761929bebd`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`d826061bf3c605d2d282fdafcfb623c9fa06a788845f079c22d0da78cbda792e`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #552 merged as
`1c0a4d8a027bbce144dddaafc12c2c329a857675` from reviewed head
`560dbf6d0af199eba1688e39fe514691ec0a9f91`. Status guard run
`30316550340` and supply-chain run `30316550327` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`d826061bf3c605d2d282fdafcfb623c9fa06a788845f079c22d0da78cbda792e`
applied only #240, and zero-action readback
`e9853f722be8f15bad77559ad8c770e858c98b7433e67305c94c97ab59d3c539`
verified convergence.

`IN_PROGRESS` the bounded ISSUE-0100 implementation handoff advances only
`ready -> in_progress`. The smallest usable outcome is a typed local
real-assets adapter integrated through the existing peer-cohort registry and
Instrument Detail facade. It covers REIT FFO/AFFO, occupancy, lease maturity,
LTV, interest cover and explicit NAV sensitivity; utility/infrastructure RAB,
allowed returns, capex funding, sector-specific leverage/coverage and
tariff/regulatory exposure. Maintenance and expansion capex assumptions,
statement reconciliation, country/business variants, parent fallback, source
lineage and deterministic rate/inflation/refinancing stresses must stay
explicit. Missing reliable NAV or RAB inputs remain unavailable.

The implementation excludes remote providers, paid dependencies, generic P/E
or industrial leverage/FCF fallbacks, other sector children, forecasts,
expected returns, recommendations, optimisation, order transmission and
broker writes. The proposed 197-record registry has SHA-256
`515c155d4c3eb480d756bc50887fce53dddffce9f97cf6d4871306088145c543`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`a9067520a0e16a78bd7b62ea3dfb1dee22976bdc2aace45da921e8f236c76d59`.
No dependency, scope, acceptance, policy or authority change is included;
`execution_allowed=false`.

`VERIFIED` implementation-handoff PR #553 merged as
`d5851534bb41f85d31ddc6e6bba15b7d2798e73c` from reviewed head
`380b47ede525959b36832ada09dcac21ad3d437e`. Status guard run
`30316774523` and supply-chain run `30316774480` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`a9067520a0e16a78bd7b62ea3dfb1dee22976bdc2aace45da921e8f236c76d59`
applied only #240, and zero-action readback
`e8deabbf128bbe36a24da63f2d21f24be74a95e9594aceac014074eddeb1701d`
verified convergence.

`REVIEWED PRODUCT CHECKPOINT` the bounded ISSUE-0100 implementation and its
one focused correction are accepted for release validation. The typed
real-assets adapter preserves sector-specific units, directions, definitions,
period, reporting standard, jurisdiction, source authority, country/business
variant, parent fallback and point-in-time lineage. REIT FFO/AFFO derivation
and reconciliation keep maintenance and expansion capex distinct; occupancy,
lease maturity, LTV, NAV, regulated-asset-base, allowed-return, capex-funding
and tariff/regulatory evidence remain explicit. Missing or unreliable NAV/RAB
is unavailable and status-limiting. Rate, inflation, refinancing and NAV
sensitivity stresses are deterministic, and forged projections fail closed.
Instrument Detail exposes only verified read-only evidence with
`execution_allowed=false`.

Independent integration evidence passed 106 domain, classification, peer,
financial-adapter, statement, fundamentals and architecture checks; 119 stock
research and Instrument Detail checks; and 6 accessibility/button contract
checks, plus Ruff, compileall and diff hygiene. Protected Linux and Windows
release gates and supply-chain validation remain required before merge.

`IN_PROGRESS` product PR #554 merged ISSUE-0100 as
`887b08dce427cadf05e34cccac02111c08b82495` from exact reviewed head
`96f6101c7f15f7d7382e64332e439f5b4bbc497e`. Protected release run
`30318189597` passed Linux and Windows package build, artefact,
source/package parity, packaged smoke, performance, policy, security, privacy,
legal and SBOM checks. Both full suites retained only the exact authorised
B03 simple-score invalidation node and `pd.notna(None)` fingerprint from
protected run `30314202998`; no ISSUE-0100 or changed-path test failed.
Status guard run `30318189573` and supply-chain run `30318189600` passed;
`execution_allowed=false`.

The separate guarded convergence advances only ISSUE-0100
`in_progress -> implemented_initially`. The proposed 197-record registry has
SHA-256 `491c791a1abda7d43d55c05ddf3b6f86e08629da188aeb05682e5d14d12e6e6a`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`f920f83ebc49cbd50126b42d67c536263357c4c5f627178f24b42fbfc3d34d57`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` implemented-initially PR #555 merged ISSUE-0100 as
`918a4995084c79cbc41b5c8b363625ef6a7db0eb` from reviewed head
`9ac1e5c3baa4da3127e6d1d3f3f0dc2f7a709094`. Status guard run
`30319740434` and supply-chain run `30319740471` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`f920f83ebc49cbd50126b42d67c536263357c4c5f627178f24b42fbfc3d34d57`
applied only #240, and zero-action readback
`0146929cb4be49f4de90fa6545ad294f0eda858a369c61ba5e4d788fc7b0263f`
verified convergence.

`IN_PROGRESS` the final separate convergence advances only ISSUE-0100
`implemented_initially -> integrated`. The proposed 197-record registry has
SHA-256 `ba2827fa2a21ebb7cf76d735878dd1700708399921048ab254f9607677e3bee2`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`55a9b16f22035841235d6de82556e85f157625d6164a00874de2b83c4c418dfc`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` integrated PR #556 merged ISSUE-0100 as
`e7fd1621ac857797264ab95667b5f09a690b7a34` from reviewed head
`7e09a9e33dc1a6bcb3db7375fae79defcac9ec42`. Status guard run
`30319962532` and supply-chain run `30319962505` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`55a9b16f22035841235d6de82556e85f157625d6164a00874de2b83c4c418dfc`
applied only #240, and zero-action readback
`39f9947bc1e6a43934ab0ae69e748a13c85b63fbfaa0b33571b0b0144f104475`
verified final ISSUE-0100 convergence.

`IN_PROGRESS` the next dependency-valid B04 prerequisite reviews only
ISSUE-0101→ISSUE-0098. The integrated `peer-cohort.v1` contract supplies
versioned sector-adapter registration and metric-applicability lineage,
classification-gated stock-only routing, exact-cutoff leaf-to-parent cohorts,
explicit exclusions/support, robust peer statistics and verified replay.
ISSUE-0101 retains all energy, materials and industrial formulas, cycle
history, commodity/input scenarios, operational source evidence and Cyclicals
UI rationale.

Record the edge as `complete` while ISSUE-0101 remains planned. The proposed
197-record registry has SHA-256
`b3b4102430547c0f3cd6b0a4baf18f4c26d2fabe8ac77a2850ed30e95a624b31`;
the live GitHub projection remains the zero-action semantic plan
`39f9947bc1e6a43934ab0ae69e748a13c85b63fbfaa0b33571b0b0144f104475`.
No product, status, dependency-list, scope, acceptance, policy or authority
change is included; `execution_allowed=false`.

`VERIFIED` peer-framework edge PR #557 merged as
`4469b423e18cfb04a7150d38286645d06ea0af67` from reviewed head
`f4b7d74b8df3e2f461d533ca45db651ce16f7fea`. Status guard run
`30320222055` and supply-chain run `30320222112` passed; the redundant
evidence-only release run was cancelled. The live GitHub projection remained
the zero-action plan
`39f9947bc1e6a43934ab0ae69e748a13c85b63fbfaa0b33571b0b0144f104475`.

`IN_PROGRESS` the separate guarded readiness transition advances only
ISSUE-0101 `planned -> ready`. Its sole blocking dependency interface is
reviewed complete while energy, materials and industrial formulas,
operational source evidence, cycle-history requirements, commodity/input
scenarios and Cyclicals UI rationale remain unimplemented ISSUE-0101 scope.
The proposed 197-record registry has SHA-256
`f747b8bc045a1eafc41f59fef4bc402a3a3b0b0c4ad3639224b965b7747c3f57`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #241 with semantic SHA-256
`5ef2917c04a5a7568052d1a3a00585f2f2353d9f4609d7018db1830ae7a5078f`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #558 merged ISSUE-0101 as
`a5acc69cc6ac0eb9cb7ec86509b98eec330e6537` from reviewed head
`c5d00b5c4c61983020ee48c84f7031f1d1a3418d`. Status guard run
`30320441635` and supply-chain run `30320441736` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`5ef2917c04a5a7568052d1a3a00585f2f2353d9f4609d7018db1830ae7a5078f`
applied only #241, and zero-action readback
`f8bf6a6a6bed3ef04cd8731ab920d8c04bd87192661dbe579ad6211dd8de239f`
verified convergence.

`IN_PROGRESS` the bounded ISSUE-0101 implementation handoff advances only
`ready -> in_progress`. The smallest usable outcome is one local typed
cyclical adapter family for energy, materials/mining and
non-infrastructure industrials, integrated through the existing peer-cohort
registry and Instrument Detail facade. It keeps spot and normalised margins
separate; requires source-linked production, cost, reserve/resource,
sustaining-capex, decommissioning, backlog, book-to-bill, utilisation,
working-capital and concentration evidence where applicable; reduces
confidence when distinct-cycle history is inadequate; and exposes
deterministic commodity-price, input-cost and demand/rate scenarios.

The implementation excludes persistence, remote commodity providers,
ISSUE-0115 stress-lab work, infrastructure routing, other sector children,
forecasts, expected returns, recommendations, optimisation, order
transmission and broker writes. The proposed 197-record registry has SHA-256
`3bd5be5e907352ea0d52b6b20404fca748ffcc1fa271e3c93b4305d03451af9e`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #241 with semantic SHA-256
`9ced52643254b6df3aa223bebc70db6514d8df9c220d139f95f2418d2c686635`.
No dependency, scope, acceptance, policy or authority change is included;
`execution_allowed=false`.

`VERIFIED` implemented-initially PR #543 merged as
`a01c663cd10bc13057175bd128456108bfceb0c4` from reviewed head
`01f95db5f1211ffc436e01458f78d8d0e63d123c`. Status guard run
`30276147784` and supply-chain run `30276148150` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`e9d4d3eee2d726a2614d775c8ac2f7cc4240fa36b9be82906bc6472f290b51be`
applied only #238, and zero-action readback
`bb68cd2ac53599bb3a26b7c619f35174b492cf707ed2d21376e32604c504ba0a`
verified convergence.

`IN_PROGRESS` the final separate convergence advances only ISSUE-0098
`implemented_initially -> integrated`. The proposed 197-record registry has
SHA-256 `3c484a44ce57f2b5b9a04e8011a5691e67e90c5e31b8d8b768873a5d1b1e7e10`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #238 with semantic SHA-256
`04c08b15461989be76539fc401ea00c99c199ab79a5c1ea2a6379eceebb05b74`.
No dependency, scope, acceptance, policy or authority change is included;
`execution_allowed=false`.

`VERIFIED` integrated PR #544 merged ISSUE-0098 as
`389278a6a30e5fc96ce96d2c796de2f075bb3b60` from reviewed head
`0d44615bc0cf7a95e24d3228ad9782b0a3947db6`. Status guard run
`30276601498` and supply-chain run `30276601199` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`04c08b15461989be76539fc401ea00c99c199ab79a5c1ea2a6379eceebb05b74`
applied only #238, and zero-action readback
`e9e91f058561411005a408eae8f1e1508d02c24c8b2427cfc08b5bc4ed6b6c4a`
verified final ISSUE-0098 convergence.

`IN_PROGRESS` the next dependency-valid B04 prerequisite reviews only
ISSUE-0099→ISSUE-0098. The integrated `peer-cohort.v1` contract supplies
versioned sector-adapter registration and applicability lineage,
classification-gated routing, exact-cutoff leaf-to-parent cohorts, explicit
exclusions/support, robust peer statistics and verified deterministic replay.
ISSUE-0099 retains all bank, insurer and diversified-financial formulas,
regulatory evidence, stress models, country variants and UI rationale.

Record the edge as `complete` while ISSUE-0099 remains planned. The proposed
197-record registry has SHA-256
`1a65285002021849652bd57a8c89d2e5e0285bbaa8717e6279b21ce2df627a79`;
the live GitHub projection remains the zero-action semantic plan
`e9e91f058561411005a408eae8f1e1508d02c24c8b2427cfc08b5bc4ed6b6c4a`.
No product, status, dependency-list, scope, acceptance, policy or authority
change is included; `execution_allowed=false`.

`VERIFIED` peer-framework edge PR #545 merged as
`d149defcce3398c3cc463bc0d1cdbdf9a1e7cb4b` from reviewed head
`9e2a59e5178f1634500519b82e59cfb0b004ecdd`. Status guard run
`30310958193` and supply-chain run `30310958226` passed; the redundant
evidence-only release run was cancelled. The live GitHub projection remained
the zero-action plan
`e9e91f058561411005a408eae8f1e1508d02c24c8b2427cfc08b5bc4ed6b6c4a`.

`IN_PROGRESS` the separate guarded readiness transition advances only
ISSUE-0099 `planned -> ready`. Its sole blocking dependency interface is
reviewed complete while financial formulas, regulatory evidence, stress
models, country variants and UI rationale remain unimplemented ISSUE-0099
scope. The proposed 197-record registry has SHA-256
`971a2df0cbe9d1d49b189d9fe19ec1afb7768f989f1f588016d1ad2b6e132ea0`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`d66bd2acc35adf35bb4b0b33678d2dda5ba31106df7d1d8f83c588c672b4c2bd`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #546 merged as
`b1f2c065b4556b7b5200b70e05ef0aa2940bb60e` from reviewed head
`12cfd39eb22c415a488692d8d18b15e1e870cf61`. Status guard run
`30311207538` and supply-chain run `30311207583` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`d66bd2acc35adf35bb4b0b33678d2dda5ba31106df7d1d8f83c588c672b4c2bd`
applied only #239, and zero-action readback
`86cb76eb492a78ba911634f94271ef4005f012e15ce14743676437e67ffa114d`
verified convergence.

`IN_PROGRESS` the bounded ISSUE-0099 implementation handoff advances only
`ready -> in_progress`. The smallest usable outcome is a typed
financial-institution adapter framework integrated through the existing
peer-cohort registry and Instrument Detail facade. It covers bank capital,
funding, asset-quality and profitability evidence; insurer underwriting,
solvency, reserve and investment evidence; and diversified-financial funding,
credit-loss, capital and revenue-mix evidence. Every metric preserves unit,
direction, period, reporting standard, jurisdiction, source and point-in-time
lineage. Missing evidence remains explicit, lowers confidence and prevents
high-authority labels. Deterministic credit-loss, funding and market shocks
remain read-only and `execution_allowed=false`.

The implementation excludes remote providers, paid dependencies, semantically
invalid generic valuation or industrial leverage fallbacks, other sector
children, forecasts, expected returns, recommendations, optimisation, order
transmission and broker writes. The proposed 197-record registry has SHA-256
`814aafe0626e0f1e52c82be7a8702e4797156a5eda50bad98d51e498207da3ba`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`8f64d4225a23e54723f129c5a0d68893da9ebc8b7ad3e0e6c06c1285e61f0749`.
No dependency, scope, acceptance, policy or authority change is included.

`IN_PROGRESS` the next dependency-valid B04 prerequisite review updates only
ISSUE-0106→ISSUE-0128 from `unresolved` to `complete`. The consumer-specific
contract is the immutable `CostEstimate` and deterministic
`estimate_execution_cost` primitive with monotonic size/ADV impact, wider
uncertainty when microstructure evidence is missing, explicit stress/capacity
status, `execution_allowed=false`, and non-mutating realised-fill comparison.
Focused cost-model tests cover finite components, order/listing/session inputs,
size monotonicity and capacity, missing-data widening, fill immutability and
shared-model use.

ISSUE-0106 remains `implemented_initially`; status, acceptance, dependency
lists, policy and authority are unchanged. ISSUE-0128 retains its unresolved
ISSUE-0064 edge and broader low/base/high interval, liquidation, persistence,
FX, cross-module and paper/backtest scope.

`REVIEWED` shared release prerequisite for the preserved checkpoint queue:
the ISSUE-0083 classification-invalidation regression uses fixed market date
`2026-07-10`, which crossed the canonical ten-business-day freshness boundary
and now fails before exercising override invalidation. No durable waiver
authorises retention. The bounded worker changed only the fixture date to the
current local date, preserving every classification-invalidation assertion,
the production stale-data gate and `execution_allowed=false`. The exact
regression and 74 focused simple-score/classification tests pass with Ruff and
diff hygiene. Next action is a protected baseline-correction release before
serial ISSUE-0039, ISSUE-0026, ISSUE-0022 and ISSUE-0059 checkpoint release.

`VERIFIED` shared-prerequisite PR #563 merged as
`b906b405dab83cea623178014b090f0c0217b6c4` from exact reviewed head
`9275ba23e85e136e20d40ec77e0cfd1956dfd7e1`. Status guard, supply-chain,
and full Linux and Windows packaged release gates passed. The post-merge
classification-invalidation regression passes; production freshness policy,
canonical programme status and GitHub issue #223 remain unchanged, with
`execution_allowed=false`. `IN_PROGRESS` the separate deterministic
convergence refreshes only the generation base to the merge commit before
ISSUE-0039 release.

`MERGED` ISSUE-0039 release from fresh main
`b80bf9bda85559b5d82e74c7db0ef458bec544bd`. The independently approved
checkpoint `2c72ac3b2ad394dec9509e3d2f0fe9f7c8253252` changes only timing-tail
reading and focused performance-contract tests; benchmark evidence showed
approximately 1,182x p50 improvement. The transplanted product patch has the
same stable patch id, `166500812524cc02bf3f076a1b2897abb79a8ac1`, as the
approved checkpoint. Root adversarial review found no scope expansion; all 6
focused performance-contract tests pass with Ruff and diff hygiene. PR #565
passed status guard, supply-chain and full Linux and Windows packaged release
gates, then merged from exact head
`8fa82c29d13e8b70d3865b7c060fe600a2e8662b` as
`db554b1b1502224801a28677550b7ff7c7920657`. `IN_PROGRESS` the separate
deterministic convergence refreshes only the generation base to the merge
commit before ISSUE-0026 release. No status, dependency, financial
calculation, broker authority or `execution_allowed=false` change is
authorised.

`VERIFIED` ISSUE-0039 post-merge convergence PR #566 passed status guard and
supply-chain validation, then merged from exact head
`4f5e8865fa75d05f817bfc1bb199b4710c5ebf02` as
`3b790eaeb95345ce70d9d9f6b21f28a1acd8c88e`; the redundant packaged release
run was cancelled after the product head had passed both packaged platforms.

`MERGED` ISSUE-0026 release from fresh main
`3b790eaeb95345ce70d9d9f6b21f28a1acd8c88e`. The dependency-ready canonical
record has no blocking dependencies and remains `implemented_initially`.
The two-file macro-scenario transplant has checkpoint-identical blobs and the
same stable patch id, `3b6da12fa44db5172726c590013e33dcd51941d9`, as the
complete `43fbcfa..203d678` diff. Root adversarial review found period-first
vintage selection, explicit UTC availability cutoffs, same-revision
fail-closed handling, strict rehashed-payload verification and context-only
authority preserved without scope expansion. All 17 focused tests pass with
Ruff and diff hygiene. PR #567 passed status guard, supply-chain and full
Linux and Windows packaged release gates, then merged from exact head
`7d7593cb310b2c4b29e5cf6277d1e719deaedf6a` as
`5b7a0150b3b01f3ec6685c7c14e62ae3dac1b050`. `IN_PROGRESS` the separate
deterministic convergence refreshes only the generation base to the merge
commit before ISSUE-0022 review. No status, dependency, financial
calculation, broker authority or `execution_allowed=false` change is
authorised.

`VERIFIED` ISSUE-0026 post-merge convergence PR #568 passed status guard and
supply-chain validation, then merged from exact head
`c906b599e3af40c824aff156159e6dd9bcba2db1` as
`a3ce6a04e3d023024b3c420c02b824401b21909b`; the redundant packaged release
run was cancelled after the product head had passed both packaged platforms.

`REVIEWED` ISSUE-0022 checkpoint
`df6181deae3815f4e8af6a55c1689d1f9222c57c` changes only five overlap
domain, application, UI and test files. Root adversarial review found
point-in-time holdings selection, explicit stale/missing/cycle/depth
fail-closed states, mapped-plus-unknown conservation, typed direct and
indirect contributors, canonical report hashing and
`execution_allowed=false` preserved. The transplanted patch has the same
stable patch id, `618d1383baa80e8ce514f70e9a54328fec4da858`, as the approved
checkpoint. All 27 focused and 188 affected tests passed with Ruff and diff
hygiene.

`REVISE` protected ISSUE-0022 PR #569 passed status guard, supply-chain and
the full Linux packaged gate, but the Windows full suite exposed an unrelated
non-deterministic baseline test boundary:
`test_real_esef_package_extracts_facts_and_retains_extensions` invoked the
optional bounded Arelle child validator while asserting the local extraction
contract. The failing result retained 285 parsed records but reported
`success=false`; the same fixture passed locally and on Linux. No durable
flake waiver authorises retention or an automatic retry. The bounded worker
changed only that test to make Arelle unavailable for its local-extraction
contract; extraction assertions and all dedicated Arelle diagnostic,
conformance, timeout and worker tests remain unchanged. The focused node
passed five consecutive runs and the full ESEF parser file passed 20/20 in
the worker environment with Ruff and diff hygiene. Root review approved the
one-test correction. Next action is a separate protected baseline-correction
release from fresh main before rebuilding ISSUE-0022; PR #569 remains
unmerged at exact head `7f2f0bf2dd004aff28566ae8946bc23957af32ee`.

`VERIFIED` shared ESEF test-isolation prerequisite PR #570 passed status
guard, supply-chain and full Linux and Windows packaged release gates, then
merged from exact reviewed head
`53e56f15750ab171b444acd2b7135f79c38cb7b8` as
`0c3a086d504d19751e8b1ab87784623c98d7f715`. The protected Windows run
verified the previously failing real-package local-extraction test. Dedicated
Arelle diagnostic, conformance, timeout and worker coverage remains intact.
`IN_PROGRESS` the separate deterministic convergence refreshes only the
generation base to the merge commit before ISSUE-0022 is rebuilt from fresh
main. PR #569 remains unchanged and unmerged.

`VERIFIED` the ESEF prerequisite post-merge convergence PR #571 passed status
guard and supply-chain validation, then merged from exact head
`b87b393232226c1c598bf74382bd2bac2fb6f71b` as
`f37115cae93a2892835a5aaba5da20fbe5a3c785`; the redundant packaged release
run was cancelled after PR #570 had passed both packaged platforms.

`REVIEWED` ISSUE-0022 was rebuilt from fresh main
`f37115cae93a2892835a5aaba5da20fbe5a3c785`. Exactly the five approved
overlap files are checkpoint-identical to
`df6181deae3815f4e8af6a55c1689d1f9222c57c`, and the stable patch id remains
`618d1383baa80e8ce514f70e9a54328fec4da858`. All 27 focused and 188 affected
tests pass with Ruff and diff hygiene. The rebuilt release includes the
merged deterministic ESEF baseline correction and does not modify ESEF,
status, dependency, financial calculation, broker authority or
`execution_allowed=false` semantics. Next action is the protected ISSUE-0022
release from this fresh base.

`MERGED` rebuilt ISSUE-0022 replacement PR #572 passed status guard,
supply-chain and full Linux and Windows packaged release gates, then merged
from exact head `80a6df8204c16d916d9ccc22663272d5709f02ae` as
`92dbc823129ae69ad2facdbf17309379e3f8cb43`. The Windows run verified the
previously failing ESEF regression and all packaged checks. The five-file
product patch retained stable patch id
`618d1383baa80e8ce514f70e9a54328fec4da858`. `IN_PROGRESS` the separate
deterministic convergence refreshes only the generation base to the merge
commit before ISSUE-0059 review. The failed first-attempt PR #569 remains
unchanged at exact head `7f2f0bf2dd004aff28566ae8946bc23957af32ee`
pending supersession cleanup.

`VERIFIED` ISSUE-0022 post-merge convergence PR #573 passed status guard and
supply-chain validation, then merged from exact head
`a131c5b6c891fe97a97c41a16d973e3a1f78c8df` as
`d4ce7a0e7f4467ab7b9f6ad65ee210e8dfb74c5f`; the duplicate packaged run was
cancelled after PR #572 had passed both packaged platforms. Superseded PR
#569 was closed with its exact head unchanged.

`REVISE` root adversarial review rejected preserved ISSUE-0059 checkpoint
`ff44de01814a6f29bd2abcf7521daea5c3901b2f` as submitted. Its chronology
validator permits `effective_at` before the return period ends and
`known_at` before `effective_at`, allowing point-in-time-invalid evidence.
It also subtracts portfolio and benchmark returns expressed in different
measurement currencies whenever an FX attribution row exists, although that
row cannot convert either top-level return. The bounded correction must
require `start_at < end_at <= effective_at <= known_at`, require matching
top-level return currencies, retain currency/FX contribution attribution in
the common reporting currency, and add adversarial tests. No wider redesign,
status/dependency change or execution authority is authorised.

`REVIEWED` the single bounded ISSUE-0059 correction cycle changed only the
checkpoint source and test files. The corrected model now fails closed unless
`start_at < end_at <= effective_at <= known_at` and unless portfolio and
benchmark returns share one measurement currency; currency/FX contribution
attribution remains available inside that common reporting currency. Direct
tests cover effective-before-end, known-before-effective and mixed currencies
even with FX evidence. The full corrected suite passes 22/22 with Ruff,
compile and diff hygiene. Root review found the correction complete without
scope expansion; corrected stable patch id is
`a77c528f936d319a8d2606a08812d10f629fda85`. Next action is a protected
ISSUE-0059 release from fresh main
`d4ce7a0e7f4467ab7b9f6ad65ee210e8dfb74c5f`; programme status remains
`implemented_initially` and `execution_allowed=false`.

`MERGED` corrected ISSUE-0059 PR #574 passed status guard, supply-chain and
full Linux and Windows packaged release gates, then merged from exact head
`37ef3fc9e18c682408ecc079fc65e85426ccee7e` as
`80c63200e733fada6ae2d76ac67feb776f281c38`. The protected gates verified
the corrected point-in-time chronology and common measurement-currency
contracts. `IN_PROGRESS` the separate deterministic convergence refreshes
only the generation base to the merge commit before the prepared ISSUE-0127
dependency-edge transitions. No status, dependency, broker authority or
`execution_allowed=false` change is included in this convergence.

`VERIFIED` ISSUE-0059 post-merge convergence PR #575 passed status guard and
supply-chain validation, then merged from exact head
`c5c3f4ba9a9990b37737fbd9b46093514f369ddb` as
`2ca0c37113da423c06e1fcda15110b028fef74dd`; the duplicate packaged run was
cancelled after PR #574 passed both packaged platforms.

`IN_PROGRESS` the first prepared ISSUE-0127 prerequisite review updates only
ISSUE-0127→ISSUE-0084 from `unresolved` to `complete`. The integrated
corporate-action and FX contract supplies append-only point-in-time action,
coverage and dated-FX stores; explicit action/cash-flow classifications;
source and revision lineage; replay without overwriting as-known history;
transaction/valuation FX attribution; discrepancy quarantine; and explicit
missing, stale and conflicted states. PR #482 passed the protected Linux and
Windows release gate, and its post-merge 50-test product/UI suite passed.

ISSUE-0127 remains `planned`; its separate ISSUE-0072 edge remains unresolved.
No product, status, dependency-list, scope, acceptance, policy, broker or
execution-authority change is included. There is no implementation blocker;
the next action is the single-edge guarded control refresh, deterministic
freshness validation, zero-action GitHub projection, and protected release
from fresh main with `execution_allowed=false`.

`VERIFIED` ISSUE-0127 dependency-edge PR #576 remained unchanged at reviewed
head `bdf759761e9e8aee33ee57197b888a9af1fb2e1d`, with base
`2ca0c37113da423c06e1fcda15110b028fef74dd`, no reviews or comments, and
successful status-guard, supply-chain, Linux and Windows protected checks. It
merged with expected-head protection as
`86502a99f9428c0f1c916bfea3974d41f7c3f2a1`.

`IN_PROGRESS` the current shared prerequisite is deterministic post-merge
convergence from that exact `main` SHA, followed by the bounded throughput
control and P0 remediation programme. ISSUE-0127 remains `planned`; its
ISSUE-0072 edge is the explicit unresolved product blocker. The next action is
to refresh only the canonical generation base, regenerate and prove
byte-fresh projections, require a zero-action GitHub readback, then install the
reviewed throughput controls without changing product scope, authority or
`execution_allowed=false`.

`VERIFIED` post-merge convergence PR #577 passed the exact status guard and
supply-chain scan, reused PR #576's unchanged-tree protected Linux/Windows
evidence, and merged from reviewed head
`b66722f33c308565a28c7fc0ab197b1c41da8b80` as
`4eaed9c8d15212d2c9dc69bad0301eecc03e0c74`. The fresh GitHub readback
remained zero action with semantic checksum
`6130b9437583b7a1ae9932b5c61667b9a4d9c7b9b5d9df7a91e8948b270e654c`.

`IN_PROGRESS` the bounded throughput control transaction allocates unused
ISSUE-0177–ISSUE-0181 as planned records and installs the reviewed plan and
delivery policy. Live generator review found the canonical control schema
rejects every new issue ID even when the status-guard migration manifest
authorises it. This shared programme-control prerequisite must first add
strict manifest-gated canonical extension support; it may not modify existing
records, statuses, dependencies, policies, authority or generated outputs.
The next action is one Sol-worker implementation with focused adversarial
tests, followed by orchestrator-owned record insertion, deterministic
generation and zero-action provider readback. ISSUE-0127 remains `planned`,
ISSUE-0072 remains unresolved and `execution_allowed=false`.

`REVIEWED` the manifest-gated canonical extension prerequisite and five-record
intake are complete in the control worktree. Unused ISSUE-0177–ISSUE-0181 are
allocated as `planned`; their package-defined dependencies, validation tiers,
scope, exclusions, acceptance criteria and rollback contracts are preserved.
All pre-existing 197 record identities, statuses, dependency evidence and
policies are unchanged. The reviewed GitHub dry run has semantic checksum
`c5b0ec62c214b864a45486de4342d8ad09bb115b164bacf67c8711fc3cd52f6c`
and contains exactly five creates plus seven derived downstream-link-only
updates. The next action is exact migration guard, focused generator/control
tests, deterministic second-pass proof and H-tier protected release because
programme-control generator code changed. No provider write occurs before the
control PR merges and its checksum is reverified.

`FAILED` PR #578 head `338996336761da1064366ee1fdc525bdd43fb9d7`
completed the Linux full suite with one freshness failure:
`github-inventory.json` had been rewritten by the final read-only GitHub dry
run after the last completion-document check. The protected test correctly
detected that the safe sync inventory shape was not the canonical
generator-owned inventory shape. No product or policy assertion failed. The
bounded correction is to regenerate that one canonical inventory, rerun its
offline freshness test and publish a new exact head; the obsolete head must
not merge.

`MERGED` corrected PR #578 at `a0e31fcfe84b343462931967571e6138117109e5`
after exact-head status, supply-chain and complete Linux/Windows release gates
passed. The reviewed GitHub plan checksum
`c5b0ec62c214b864a45486de4342d8ad09bb115b164bacf67c8711fc3cd52f6c`
was applied and verified, creating ISSUE-0177–ISSUE-0181 as issues #579–#583;
fresh readback is zero action at checksum
`f3813a75fab0a13ee936fe0e77c6350f78d8377c7f450b4983b9c1e9d8633883`.
`IN_PROGRESS` this evidence-only convergence refreshes the canonical
generation base and remote summary from fresh `origin/main` without changing
any issue semantics, status, dependency evidence, policy or product file.
The next action is exact guards and deterministic check mode, then merge the
small convergence transaction before ISSUE-0177 implementation begins.

`REVIEWED` convergence found that the initial extension generator required
the intake manifest to re-authorise already-canonical control extensions on
every later generation. That made the first zero-addition post-merge
convergence fail closed. The bounded fix distinguishes persisted extensions
in the checked-in registry from genuinely new IDs, while authoritative
control comparison still rejects removals and the migration manifest still
must exactly authorise every new ID. A post-intake adversarial test now proves
unrelated later manifests retain ISSUE-0177–ISSUE-0181 without
re-authorisation. Because programme-control code changed, the convergence
transaction is validation tier H and requires fresh Linux and Windows gates.

`MERGED` convergence PR #584 at
`ed3a7d0813aa930590398d93fc5fa0130f82ec19` after exact-head status,
supply-chain and complete Linux/Windows release gates passed. The registry
retains all 202 canonical records and the GitHub projection remains zero
action at checksum
`f3813a75fab0a13ee936fe0e77c6350f78d8377c7f450b4983b9c1e9d8633883`.

`IN_PROGRESS` ISSUE-0177 now owns the bounded validation-observability slice.
One Sol worker prepared the disjoint checkpoint; orchestrator review required
one correction so an isolated `report_root` cannot leak JUnit output into the
source worktree. The fresh-main transplant adds protected and affected JUnit,
slowest-100 setup/call/teardown durations, deterministic environment/cache/
retry fingerprints, stage and evidence paths, an authoritative pre-test
environment verifier and ignored runtime release artefacts. Focused
orchestrator validation passed 29 tests plus Ruff, MyPy, compileall and diff
hygiene. The canonical status advances only `planned → in_progress`; the
reviewed GitHub dry-run checksum
`db8fd5368dd3665d76a8310be7da0714aadb8c7d3b0c147d302b32852537ab3d`
contains exactly the corresponding ISSUE-0177 status update. A persisted
extension lifecycle defect discovered by this first transition is fixed with
a regression test: only genuinely new extension IDs are forced to begin
`planned`. The next action is exact guards, affected validation and complete
H-tier Linux/Windows evidence; no provider write occurs before merge.

`MERGED` ISSUE-0177 product PR #585 at
`f22abc22f5fee8f97b9ad5dc201374d0a434bfa8` after the exact-head status,
supply-chain and complete Linux/Windows release gates passed. Both platform
jobs reported 2,081 tests with zero failures or errors and retained JUnit,
slowest-100 timings, environment fingerprints, cache/retry and per-stage
evidence. The reviewed GitHub status plan was applied and verified; fresh
readback is zero action at checksum
`187dd923cdb7251e85f14b1d1ef43ff3903537b2572f5268982b182d74f692e8`.
`IN_PROGRESS` this evidence-only transaction advances only ISSUE-0177 from
`in_progress` to `implemented`, reusing the exact-tree protected evidence.
The next action is deterministic generation, exact E-tier guards and an
audited one-field GitHub status update; product code and
`execution_allowed=false` remain unchanged.

`MERGED` ISSUE-0177 implemented-status PR #586 at
`af666cf015c686a59f8fade3e3e07338a7a1b05c`; its exact status guard and
supply-chain scan passed, and the reviewed one-field GitHub plan was applied.
Fresh readback is zero action at checksum
`c352c885b330cf314285c61b427bd9b284c9860942cc6c5a219276c8ffb7d454`.
`IN_PROGRESS` this evidence-only transaction advances only ISSUE-0177 from
`implemented` to `integrated`, using the already successful PR #585
Linux/Windows protected evidence and the audited PR #586 status transaction.
The next action is deterministic generation, exact E-tier guards and the
corresponding one-field GitHub status update.

`MERGED` ISSUE-0177 integrated-status PR #587 at
`4d5f30e6ac19650030a61bec0e22a4eeb2fd57d9`; its exact status guard and
supply-chain scan passed, and the reviewed one-field GitHub plan was applied.
Fresh readback is zero action at checksum
`865d2c698dde37c3ca3731b4297b8b7d5556c045c42f893218ac79e8700c7087`.
`IN_PROGRESS` this evidence-only transaction updates exactly the
ISSUE-0178 → ISSUE-0177 dependency edge from `unresolved` to `complete`, using
the integrated ISSUE-0177 contract and exact protected evidence. The next
action is deterministic generation, schema-1.3 edge guard, E-tier checks and
an audited GitHub projection; the current dry run is already zero action
because dependency-edge evidence is canonical-only metadata.

`MERGED` ISSUE-0178 dependency-edge PR #588 at
`0bf098841fe14c513c6b01286973f3aa2d4d0db7`; the schema-1.3 edge guard and
supply-chain scan passed, the obsolete full matrix cancelled, and post-merge
GitHub readback remains zero action at checksum
`865d2c698dde37c3ca3731b4297b8b7d5556c045c42f893218ac79e8700c7087`.
`IN_PROGRESS` ISSUE-0178 is now dependency-ready with status `planned` and
`execution_allowed=false`. Exactly one Sol worker owns the bounded classifier
and CI-orchestration implementation; canonical control/status/generated files
remain orchestrator-owned. The next action is worker implementation plus
focused workflow/classifier tests, followed by orchestrator diff review and
fresh-main integration.

`REVIEWED` the single ISSUE-0178 worker checkpoint is transplanted onto fresh
main at `cb6ba3323ca398bc260faa378c8dcd82b6e78da5`. It adds deterministic
E/O/H/C classification, exact base/head preflight, obsolete-head
cancellation, one automatic source scan, conditional Linux/Windows gates and
an unconditional terminal summary. The one permitted correction made clean
CI changed-test discovery and diff hygiene use exact refs and added the
missing evidence-tier generator checks. Orchestrator verification passed 29
focused tests plus Ruff, MyPy, compileall, workflow YAML parsing, H-tier
self-classification and diff hygiene. `IN_PROGRESS` the canonical status now
advances only `planned → in_progress`; the next action is deterministic
generation, exact guards and the complete H-tier Linux/Windows package gate.

`MERGED` shared baseline prerequisite PR #590 at
`c4be7fde98574c2a22d33d9ba21b0a3d40532c8e` after its exact schema-1.1
guard, supply-chain scan and complete Linux/Windows packaged gates passed.
Both platforms reported 2,081 tests with zero failures, errors or skips; the
previously failing minimal local ESEF extraction node is now isolated from
optional Arelle validation while dedicated validator coverage remains.
`IN_PROGRESS` PR #589 now includes that exact prerequisite and refreshes its
canonical generation base to merged main without changing the reviewed
ISSUE-0178 product checkpoint. The audited GitHub plan checksum remains
`35a3e744a36a3b3a3534c0a4471992821687c602b3d26ce64ea3c7405df4d822`
and contains exactly the ISSUE-0178 `planned → in_progress` update. The next
action is exact schema-1.2 guard, deterministic generator checks and a fresh
H-tier Linux/Windows run on the new PR head; no provider write occurs before
merge.

`MERGED` ISSUE-0178 product PR #589 at
`0c452da6b27cb5ada9e545517605a7f355485564`. Exact classifier, preflight,
status protection, the single canonical supply-chain scan, Linux and Windows
package gates and terminal `validation-summary` passed. Both platforms
reported 2,089 tests with zero failures, errors or skips. The reviewed GitHub
plan `35a3e744a36a3b3a3534c0a4471992821687c602b3d26ce64ea3c7405df4d822`
was applied and verified; fresh readback is zero action at checksum
`9c0a69053ad330c875b37cafe7c2b1d50c3a8fc16ac9a9a9ddfcec5864e34af3`.
`IN_PROGRESS` this evidence-only transaction advances only ISSUE-0178 from
`in_progress` to `implemented`, using the exact protected product evidence.
The next action is deterministic generation, exact classifier and
schema-1.2 guards, then the audited one-field GitHub status update;
`execution_allowed=false` and all product files remain unchanged.

`MERGED` shared baseline prerequisite PR #592 at
`dc8947e8af3049e322de1b52b9d0383864695753` after exact schema-1.1 status
protection, classifier, supply-chain, preflight and complete Linux/Windows
package gates passed. Both platforms reported 2,089 tests with zero failures,
errors or skips; the Windows-only state-persistence fixture no longer follows
optional Arelle discovery, while dedicated validator coverage is unchanged.
`IN_PROGRESS` PR #591 now includes that exact prerequisite and refreshes its
generation base to merged main without changing the reviewed ISSUE-0178
status payload. Its audited one-field GitHub plan remains
`15e0cf38d9efb275948d5ba082ba7fb3a5aa7014e1bc8ee59f4b40779ed219cd`.
The next action is exact schema-1.2 guard, deterministic generator checks and
fresh H-tier Linux/Windows evidence on the new head before merge or provider
write.

`MERGED` ISSUE-0178 implemented-status PR #591 at
`e27209aee137804f883440053ec2a5b5f59c5da2`. Its exact schema-1.2 guard,
classifier, preflight, canonical supply-chain scan, Linux and Windows package
gates and terminal summary passed at 2,089 tests per platform with zero
failures, errors or skips. The reviewed one-field GitHub plan
`15e0cf38d9efb275948d5ba082ba7fb3a5aa7014e1bc8ee59f4b40779ed219cd`
was applied and verified; fresh readback is zero action at checksum
`396429b23ed664e996aad1186c57fb5cea63dfb187ed82c8db0fb5a21dbf6055`.
`IN_PROGRESS` this evidence-only transaction advances only ISSUE-0178 from
`implemented` to `integrated`; its audited GitHub plan checksum is
`a978b9ee85ab05846d53fd82f0f29439171cdb13570e00c69564120703e884af`.
The next action is exact schema-1.2 guard, deterministic generation and fresh
H-tier validation before the final one-field provider update. Product code,
broker authority and `execution_allowed=false` remain unchanged.

`MERGED` ISSUE-0178 integrated-status PR #593 at
`90106943ea4e7cd41909ca45eab185216bb8f45f`; both packaged platforms passed
2,089 tests with zero failures, errors or skips. The reviewed GitHub plan was
applied and fresh readback is zero action at checksum
`9709ce3b499692119f301f45338ad6033b8328cfd24b13b9078ef7be83cf3fbe`.
`IN_PROGRESS` the continuation sequence now reviews only the ISSUE-0127 →
ISSUE-0072 dependency edge. ISSUE-0072 supplies a generic durable
transactional-storage interface, but double-entry accounting, Decimal journal
semantics, trial balance, inception rebuild and broker/local truth separation
remain ISSUE-0127-owned scope. The next action is a checksum-controlled
`unresolved → partial_interface` edge update, deterministic generation and
exact protected validation; no product or provider write is part of this
transaction.

`MERGED` ISSUE-0127 dependency-edge PR #594 at
`f6460719ee854f5875d25428560e2dab508f3a85`; the exact status guard,
classifier, preflight, supply-chain scan and terminal validation summary
passed. The complete Linux and Windows package gates each reported 2,089 tests
with zero failures, errors or skips after the single documented native-parser
flake retry. Fresh post-merge GitHub readback is zero action at checksum
`9709ce3b499692119f301f45338ad6033b8328cfd24b13b9078ef7be83cf3fbe`.
`IN_PROGRESS` ISSUE-0068 remains `implemented_initially`; stale PR #562 is the
explicit rebuild source, not a merge candidate. The current blocker is proof
that its independently reviewed five-file product intent remains compatible
with fresh main, point-in-time rules, policy-envelope migrations and focused
tests. The next action is one Sol worker rebuilding only those five product
files from `f6460719ee854f5875d25428560e2dab508f3a85`, with control/generated
files, PR #560, PR #562, issue #241 and `execution_allowed=false` unchanged.

`REVIEWED` the single ISSUE-0068 worker rebuilt the five-file product intent
from fresh main without merging stale PR #562. The product tree matches its
independently reviewed checkpoint except for one type-safe numeric parse that
does not change valid serialised values. Schema-v3 policy profiles remain
checksum-protected, point-in-time labelled, migration-explicit and unable to
grant execution authority; legacy schema-v0/v2 edits do not silently backfill.
The orchestrator passed all 51 affected universe, UI, guardrail and onboarding
tests plus Ruff, compile and diff hygiene. The next action is an exact-scope
commit, classifier/preflight review and the complete protected Linux/Windows
package gate required for persistence and migration changes.

`IN_PROGRESS` persistence-path classifier prerequisite PR #595 merged at
`2174e2b203731bb9decb1f87c0f1605fa197cde2`; both packaged platforms passed
2,090 tests with zero failures, errors or skips, and fresh GitHub readback is
zero action at checksum
`9709ce3b499692119f301f45338ad6033b8328cfd24b13b9078ef7be83cf3fbe`.
ISSUE-0068 is refreshed onto that exact main head with deterministic programme
evidence and no canonical status change. The integrated tree passes all 165
affected product, classifier and control-plane tests plus Ruff, compile,
freshness, status-guard and diff checks. The next action is the exact-head
ISSUE-0068 PR and mandatory H-tier Linux/Windows package gate; stale PR #562,
broker authority and `execution_allowed=false` remain unchanged.

`MERGED` ISSUE-0068 product PR #597 at
`4119de77e0bbc9d30939855945247223443c8e19`; the exact status guard,
classifier, preflight, supply-chain and terminal summary passed, and Linux and
Windows each reported 2,104 tests with zero failures, errors or skips. Fresh
post-merge GitHub readback remains zero action at checksum
`9709ce3b499692119f301f45338ad6033b8328cfd24b13b9078ef7be83cf3fbe`.
`IN_PROGRESS` the evidence-only integration transaction advances only
ISSUE-0068 from `implemented_initially` to `integrated`. Its reviewed GitHub
plan contains one update for canonical issue #140 at checksum
`96e6426266e23802fecb93b4423a79869a1929aa88341546594bdef0976b369f`.
The next action is exact schema-1.2 validation, deterministic generation and
H-tier packaged acceptance before the one-field provider apply/readback;
stale PR #562, broker authority and `execution_allowed=false` remain
unchanged.

`MERGED` ISSUE-0068 integrated-status PR #598 at
`66566a267bd1edef6dc2bf0c34d7921d35ee2c8c`; both packaged platforms passed
2,104 tests with zero failures, errors or skips. The reviewed provider plan
updated only canonical issue #140, and fresh readback is zero action at
checksum `c19e0862839545591f4ac0a7a24ce88aab70a40e4572b9591d12515a9d3eb8bd`.
`REVIEWED` ISSUE-0088 is the next dependency-valid Phase 2 item. Its sole
worker added the bounded local curve/benchmark acceptance slice: latest
then-known spot/par/forward snapshots, bounded declared interpolation,
explicit currency/horizon proxy fallbacks, versioned lawful benchmark
metadata, coverage UI and unsupported issuer-credit state. The orchestrator's
focused correction made all new authority fields structurally
`execution_allowed=false`; 35 affected tests plus Ruff, compile and diff
hygiene pass. The next action is an exact-scope commit and classified
validation; no network/provider/broker write or canonical status transition
is part of this product checkpoint.

`MERGED` ISSUE-0088 product PR #599 at
`889844076e4493f55eb6330ae8a5455fa7373647`; the exact classifier,
status guard, preflight, supply-chain and terminal summary passed. Linux and
Windows each reported 2,115 tests with zero failures, errors or skips, and the
PR had no comments, reviews or unresolved threads. Fresh post-merge GitHub
readback remains zero action at checksum
`c19e0862839545591f4ac0a7a24ce88aab70a40e4572b9591d12515a9d3eb8bd`.
`IN_PROGRESS` the evidence-only integration transaction advances only
ISSUE-0088 from `implemented_initially` to `integrated`. Its reviewed GitHub
plan contains one update for canonical issue #228 at checksum
`f31e03bd4496f24f45fecfe4572a3f79ee04397e59c2b81a55f5467b8b22f783`.
The next action is exact schema-1.2 validation, deterministic generation and
H-tier packaged acceptance before the one-field provider apply/readback;
stale PR #562, broker authority and `execution_allowed=false` remain
unchanged.

`MERGED` ISSUE-0088 integrated-status PR #600 at
`606b1a245b22393aa79a673329b968fc77537278`; Linux and Windows each
reported 2,115 tests with zero failures, errors or skips. The approved
checksum updated only canonical issue #228, and fresh readback is zero action
at checksum `b394835bb4856ff3df524eeac6cdbffa8355539286cbc6602148379337455b4e`.
`BLOCKED` ISSUE-0089 is the next Phase 2 candidate until its two declared
dependency edges are reviewed. Targeted inspection confirms ISSUE-0073
provides append-only decision-time vintages and UPDATEV2-0021 provides
candidate retention, deterministic conflict selection, quarantine/block
states, audited review and downstream invalidation identity; their 23 focused
tests pass. Repository control requires each dependency decision to advance
and merge independently. The current evidence-only transaction changes only
ISSUE-0089→ISSUE-0073 from `unresolved` to `complete`; after protected merge,
a second transaction will review ISSUE-0089→UPDATEV2-0021. No product status,
provider state, broker authority or `execution_allowed=false` changes in
either dependency transaction.

`MERGED` first ISSUE-0089 dependency PR #601 at
`d9b0189db909dca4286432bb6e4eef311d2b2830`; Linux and Windows each
reported 2,115 tests with zero failures, errors or skips, and post-merge
GitHub projection remains zero action at checksum
`b394835bb4856ff3df524eeac6cdbffa8355539286cbc6602148379337455b4e`.
`IN_PROGRESS` the second evidence-only transaction changes only
ISSUE-0089→UPDATEV2-0021 from `unresolved` to `complete`, based on the
integrated point-in-time candidate-retention, deterministic conflict
selection, quarantine/block, audited-review and invalidation-token contract.
The next action is deterministic generation and protected validation; no
programme status, provider state, broker authority or
`execution_allowed=false` changes in this transaction.

`MERGED` second ISSUE-0089 dependency PR #602 at
`894451ee4c62822cb593b31b275d8bb92d785aa1`; Linux and Windows each
reported 2,115 tests with zero failures, errors or skips, and post-merge
GitHub projection remains zero action at checksum
`b394835bb4856ff3df524eeac6cdbffa8355539286cbc6602148379337455b4e`.
ISSUE-0089 is now `READY_BLOCKING_EDGES_RESOLVED`.
`REVIEWED` the sole worker's bounded ISSUE-0089 implementation adds the
versioned local quality-rule registry, scoped anomaly evaluation,
append-only bitemporal findings and corrections, source-conflict projection,
downstream eligibility/invalidation evidence and Data Health coverage. The
focused correction closes cross-asset applicability, review-only resolution,
malformed-input and unavailable-ledger bypasses; the orchestrator's small
integration correction makes source/asset context, finite supplied values
and ISO schedule evidence fail closed. The 196-test affected persistence,
conflict, fixed-income, market-adjustment, portfolio-import and UI suite
passes, together with Ruff, compile and diff hygiene. The next action is an
exact-scope product commit and classified H-tier validation; no provider,
broker, network, programme-status or `execution_allowed=false` change is
part of this checkpoint.

`MERGED` ISSUE-0089 product PR #603 at
`d69113a69c3d454ce51b4122cb07cf8fabc29537`; classifier, status guard,
preflight, supply-chain and terminal validation summary passed. Linux and
Windows each reported 2,122 tests with zero failures, errors or skips, and
the PR had no comments, reviews, review requests or review threads. Fresh
post-merge GitHub projection remains zero action at checksum
`b394835bb4856ff3df524eeac6cdbffa8355539286cbc6602148379337455b4e`.
`IN_PROGRESS` the first evidence-only ISSUE-0089 status transaction advances
only `planned` to `in_progress` from the protected product and cross-platform
acceptance evidence; the canonical validator requires
`in_progress` before `implemented_initially`. The next action is exact schema-1.2
validation, deterministic generation and H-tier packaged acceptance before
the one-field provider apply/readback; dependencies, stale PR #562, broker
authority and `execution_allowed=false` remain unchanged.

`MERGED` ISSUE-0089 in-progress status PR #604 at
`694e9619cf42d251b43e2b7f92c55419a273b4a9`; Linux and Windows each
reported 2,122 tests with zero failures, errors or skips, and the PR had no
comments, reviews, review requests or review threads. The approved provider
plan updated only the managed Programme status field on canonical issue #229
at checksum `a4f72a02410bcda9ce2da2922019ccb60b347095d93eedacf02eae2bc1723978`;
fresh readback is zero action at checksum
`ea2799e62aebd9a8fe8883abf54298f22721ff67b5ceef5461e2f98e4664fb59`.
`IN_PROGRESS` the next evidence-only transaction advances only ISSUE-0089
from `in_progress` to `implemented_initially`. The next action is exact
schema-1.2 validation, deterministic generation and H-tier packaged
acceptance before the one-field provider apply/readback; dependencies, stale
PR #562, broker authority and `execution_allowed=false` remain unchanged.

`MERGED` ISSUE-0089 implemented-initially status PR #605 at
`19258f531d29090e8f574f990954feec5a966638`; Linux and Windows each
reported 2,122 tests with zero failures, errors or skips, and the PR had no
comments, reviews, review requests or review threads. The approved provider
plan updated only the managed Programme status field on canonical issue #229
at checksum `9a2ac652356dfc12284e6e1fec0c34ee209cd1be39851e4d49d3ea4e444b607f`;
fresh readback is zero action at checksum
`06ab2ec48cf7190b38dfb88fa33917ad22ba50eec90ab52e663ed26842609728`.
`IN_PROGRESS` the final evidence-only transaction advances only ISSUE-0089
from `implemented_initially` to `integrated`. Its reviewed GitHub plan contains
one update for canonical issue #229 at checksum
`8b5eb38970a1fc125958eaf1e18fb70d41da2030ceb9625828a139a5852be634`.
The next action is exact schema-1.2 validation, deterministic generation and
H-tier packaged acceptance before the one-field provider apply/readback;
dependencies, stale PR #562, broker authority and `execution_allowed=false`
remain unchanged.

`MERGED` ISSUE-0089 integrated-status PR #606 at
`2e63a813f8c835a2e488cb88f91bfeaab8ae665a`; Linux and Windows each
reported 2,122 tests with zero failures, errors or skips, and the PR had no
comments, reviews, review requests or review threads. The approved provider
plan updated only the managed Programme status field on canonical issue #229
at checksum `8b5eb38970a1fc125958eaf1e18fb70d41da2030ceb9625828a139a5852be634`;
fresh readback is zero action at checksum
`23cff2eee691649a17d83f0e8ff5c2833c7b19303f57a2a182f1e75db354d143`.
`BLOCKED` ISSUE-0090 is the next Phase 2 record until its two declared
dependency edges are reviewed. The current evidence-only transaction reviews
only ISSUE-0090→ISSUE-0072 against the integrated hybrid local-platform,
immutable analytical-generation, transactional migration, integrity,
backup/restore and recovery contract. After protected merge, a second
transaction will review ISSUE-0090→ISSUE-0075. No product status, provider
state, broker authority or `execution_allowed=false` changes in either
dependency transaction.

`MERGED` first ISSUE-0090 dependency PR #607 at
`2337f6959719a9a4ae1b8ec9efb3927ade2acc7d`; Linux and Windows each
reported 2,122 tests with zero failures, errors or skips, and post-merge
GitHub projection remains zero action at checksum
`23cff2eee691649a17d83f0e8ff5c2833c7b19303f57a2a182f1e75db354d143`.
`IN_PROGRESS` the second evidence-only transaction reviews only
ISSUE-0090→ISSUE-0075 against the integrated immutable formula, feature,
dataset, model and policy version registry, dependency-manifest, compatibility,
migration and deterministic invalidation contract. No product status,
provider state, broker authority or `execution_allowed=false` changes in this
transaction.

## UPDATEV2-0018 readiness and product checkpoint — 2026-08-02

`REPAIR` readiness PR #649 merged as
`efda3f3f8d9fbb075a902af37102b0752e5aba27` after full cross-platform
validation, but automatic convergence `30767687270` failed closed because the
PR omitted the existing one-hop candidate/ledger append. The sole bounded
repair lane adds only UPDATEV2-0018/#158 `planned -> ready` authority bound to
exact parent `efda3f3f8d9fbb075a902af37102b0752e5aba27` and reviewed semantic
plan `6bda2fed8424495b569499cb3ea1bfae11db7d2f78c192c924c4d43f2f97e1f8`.
No generic convergence design, product code, dependency, external authority or
`execution_allowed=false` state changes.

`IN_PROGRESS` exact `origin/main`
`745dfd9f747f95aa6cb0e3cbc6f25c4ac5a2de0c` selects UPDATEV2-0018 as the
next implementation-order record, with deterministic readiness true and no
blocking dependencies. Clean lane `codex/updatev2-0018-ready-20260802`
records only `planned -> ready`, the allowlisted active/B04 chronology, and
mechanically generated projections; `execution_allowed=false` remains
unchanged. The isolated product implementation is stable at
`6f41972a735b8dd8e98eac4c894685f027e06f99` pending independent exact-head
review. After readiness converges, rebase that product head onto the new exact
main and run fresh H-tier review and authoritative Linux/Windows package gates
before merge and automatic lifecycle completion.

`CORRECTION` UPDATEV2-0018 exact head
`0216f820eb7c111cd95c0bc287d50e05e6b526c0` received whole-diff approval
and one risk-review blocker: four accepted disclosure-import buttons were
missing from reverse-complete long-running control coverage. One bounded pass
adds those existing controls and an acceptance-derived reverse regression.
Rejected-head CI is stale; focused checks, both exact-head reviews and fresh
H-tier Linux, Windows and terminal gates are required on the replacement head.

`FINAL_CORRECTION` UPDATEV2-0018 exact head
`a5144b49ed996af95f4a1706d8bc5f87d97b9742` received risk approval and
one newly demonstrated whole-diff rejection: byte-backed document/holdings
imports persisted temporary paths, and reverse coverage derived only five of
seven accepted controls from configuration. The bounded final pass retains
those sources under existing checksum-addressed raw evidence before registry
writes and derives the exact seven-control set from UI acceptance. Rejected-
head CI is stale; focused checks, both exact-head reviews and fresh H-tier
Linux, Windows and terminal gates remain required.

`TRUTHFUL_AUTHORITY_CORRECTION` exact head
`daa23b34a6c54faf5b0c0d85920cbc442a94e65f` passed the complete focused
review surface but masked the real holdings callback by rewriting
`manual_unverified` as `issuer` in its durability test. The narrow correction
allows only structurally valid non-score manual context through the existing
atomic holdings/document group, preserves unknown authority and false score
eligibility, binds truthful manual evidence and removes the rewrite. Fresh
exact-head reviews and H-tier Linux, Windows and terminal gates are required.

`GATE_CORRECTION` exact head
`a1e1f756343453850991c7eb3ade23f443d1c78c` received both reviewer
approvals, but Linux H-tier run `31324672892` exposed one stale legacy test
that expected immediate cancellation-slot release. The reviewed contract
reserves cancelled ownership until callback exit to reject late publication.
The test-only correction asserts reservation, explicit owner release and the
durable cancellation event. Runtime behavior and authority remain unchanged;
fresh exact-head reviews and H-tier Linux/Windows/terminal gates are required.

## ISSUE-0017 product checkpoint — 2026-08-10

`MERGED` ISSUE-0016 PR #671 at exact reviewed head
`89fb083f9c0244e376b39d85ccea5d96379377b1` as exact main
`9d3550589f8aacbe6686a1e07711007e50bef9cf`; Linux, Windows and terminal
validation passed. Writer run `31387114454` applied and verified only
ISSUE-0016 `implemented_initially -> integrated` with zero-action readback,
generic convergence `31387113274` passed, and a fresh exact-main readback is
also zero-action with authority reconciliation accepted. GitHub issue #20
projects the canonical integrated state without unrelated writes.

`IN_PROGRESS` ISSUE-0017 is the next canonical implementation-order record.
It is dependency-ready and activation-ready with no blocking dependencies.
Clean lane `codex/issue0017-product-20260810` starts with an empty diff at exact
main `9d3550589f8aacbe6686a1e07711007e50bef9cf`. Inspect and prove the existing
first-run onboarding implementation against its storage, hardware, provider,
offline bootstrap, encryption/backup and staged-execution acceptance contract;
make only a reproduced bounded correction. Product and lifecycle preparation
must preserve all authority boundaries and `execution_allowed=false`.

`CORRECTED` initial product commit
`cb2149963d497f2235edc5cb1d35cc9af2fe82ee` was rejected after independent
criterion review reproduced unused selected storage, metadata-only bootstrap
and absent quota-to-UI propagation. One consolidated correction produced exact
product commit `f6fd24678be4c13730d2c821f9d3ed2d9bc9edce`; independent re-review approved
all criteria and the focused onboarding, import/export and atomic-I/O suites.
Same-PR lifecycle preparation then failed closed because the existing guard
requires the reviewed product commit to be an ancestor of the PR base. The
invalid authority lane remains unpublished. The clean product-only lane now
freezes for H-tier review and validation; after merge, one automatic lifecycle
transaction will bind the real merged product commit and require writer plus
zero-action generic readback. `execution_allowed=false` remains unchanged.

`REVIEW_CORRECTION` both exact-head reviewers rejected frozen head
`f01a673a284c6c7aaf1d0f3699371bef4dfdde70`; run `31391040254` is cancelled
and stale. One consolidated correction at
`45e5e9aa4f350df3f464e3a536ccbcbe24556d8d` closes their complete finding set:
bulk is explicit unavailable with zero price writes; onboarding-owned outputs
publish as one revision-guarded local group after path/volume/symlink preflight;
selected storage and hardware propagate without replacing active risk/cost
configuration; empty-machine policy fallback and valid-scope persistence are
covered; unsupported plaintext backup claims fail before writes. Focused and
Windows changed validation pass. Freeze the documented replacement head, then
repeat both reviews and fresh H-tier Linux/Windows/terminal validation.

`FINAL_BOUNDED_CORRECTION` re-review rejected
`d6abc257d27a657e3286915551265da5b08ac008` for a reproduced junction swap and
for selected root/profile not governing restart and the durable scheduler; run
`31394272704` is cancelled and stale. Commit
`437c935ae9416c6723dd04880ccc45a21c3fd5f1` narrows storage truthfully to the
existing canonical project-local runtime root, rejects custom roots before any
write, removes CWD authority, applies persisted hardware limits to the actual
scheduler and revalidates destination identity inside grouped publication.
The focused 148-test surface has 147 passes and one platform-capability skip;
static checks pass. Freeze one final documented head and repeat both exact-head
reviews plus fresh H-tier Linux/Windows/terminal validation.

`CONSOLIDATED_PERSISTENCE_CORRECTION` exact head
`9e5d097565739ef9e4d2259e4f2f9877766c4b4c` was rejected only after both
parallel reviewers completed. They reproduced duplicate-policy loss and a
post-precondition canonical universe save being overwritten; stale hosted run
`31397877895` separately exposed the new junction regression invoking Windows
`cmd` on Linux. Commit `279e61541bdd8b87c72cec5b51e06839842543e0`
preserves the existing policy, shares the grouped guard and in-guard CAS across
canonical and onboarding universe writers, adds both deterministic regressions,
and capability-skips the Windows-only test. Focused affected tests, Ruff,
compile and diff hygiene pass. Freeze one documented replacement head for both
exact-head reviews and fresh Linux/Windows/terminal validation.

`FINAL_PRODUCT_CORRECTION` risk review approved exact head
`4842e62dec7349cc793f9e3a5ddafc2926a198e7`, but whole-diff review reproduced
cross-tier record collapse despite the preserved policy and acceptance of an
unsupported persisted encrypted-backup claim. Run `31401913671` is cancelled
and stale. Commit `9ae2fceab6a39643c33acc2f25bb88e9ea23495c` preserves
records under the existing canonical duplicate semantics and makes unsupported
persisted backup metadata fail closed. Both regressions and the affected
focused/static checks pass. Freeze the documented replacement for final
parallel exact-head review and fresh H-tier Linux/Windows/terminal gates.

`CANONICAL_IDENTITY_CORRECTION` risk review approved exact head
`8c125409f1b388e696620205035fa2a553d696cf`, while whole-diff review reproduced
an onboarding merge mismatch for same-ID cross-tier records and verified ISIN
collisions. Run `31403933793` is cancelled and stale. Commit
`9304f1386047da4f6773e1901dbd44e5ba1c10b1` applies the existing canonical
instrument-ID, ticker and verified-ISIN same-tier/cross-tier semantics, with
focused regressions for each identity. Onboarding, universe and presentation
boundary checks plus Ruff, compile and diff hygiene pass. Freeze one documented
replacement head for final exact-head review and H-tier gates.

`IDENTITY_ROUND_TRIP_CORRECTION` both reviewers rejected exact head
`3059a24623a60a4a0ab0e98964e1602aeff79403` after reproducing canonical
validation/decoder disagreement, incomplete per-tier identity tracking and an
ambiguous onboarding replacement that collapsed two records. Run
`31405719378` is cancelled and stale. Commit
`2023d1c7faebf18742a744e92d8f2c4aa89639a8` tracks complete tier sets for
ID/ticker/verified ISIN, preserves legal schema-v3 cross-tier round trips,
rejects repeated same-tier identities and makes ambiguous onboarding matches
fail before writes. Complete focused identity, persistence, application and
presentation-boundary checks pass. Freeze the documented head for final review
and H-tier Linux/Windows/terminal gates.

`CONSOLIDATED_INTEGRITY_CORRECTION` final review rejected exact head
`8abbce95706a5b18b71514615d2395a9aa00c46f` for five reproduced gaps: active
config bypassed canonical universe integrity, onboarding settings lacked CAS,
backup durability was overstated, malformed ISIN authority was accepted, and
disabled unresolved tickers were re-enabled on resave. Run `31407286024` is
cancelled and stale. Commit `b959929168417b3642e42d6edf0464a2b83cbb8c`
uses the canonical decoder at the application boundary, checksum-binds the
onboarding CAS, records backup unavailable/not enabled, validates verified
ISIN shape/status and preserves unresolved disabled state. The complete focused
integrity/concurrency/application/architecture surface passes. Freeze the
documented head for final review and H-tier Linux/Windows/terminal gates.

`GLOBAL_ROW_IDENTITY_CORRECTION` parallel review rejected exact head
`b702dc288257226b875ea4326464b0038da13c47` because active config rejected
supported schema-v2 snapshots and duplicate cross-tier instrument IDs were
incompatible with global application/UI/CRUD row identity. Run `31410039718`
is cancelled and stale. Commit `a7347395ffb006e3bf8721555e07d89388e7a038`
restores canonical schema-v2 loading, enforces global case-insensitive IDs,
retains cross-tier ticker/verified-ISIN override and makes onboarding replace
same-ID rows deterministically. The complete focused persistence, application,
UI and architecture surface passes. Freeze the documented head for final review
and H-tier Linux/Windows/terminal gates.

`COMPATIBILITY_TRUTH_CORRECTION` parallel review rejected exact head
`a5efafe7eb1fc80f582500e1aee3bf3cdd3b035d` for dotted/underscore ticker ID
aliasing, non-boolean legacy policy, boolean row evidence, stale unresolved
metadata, overstated sample counts and an inaccurate override label. Run
`31413658110` is cancelled and stale. Commit
`14d50990583d583f9cbd88fd3977eebb7622aa23` preserves exact ticker IDs, strictly
validates evidence and legacy policy, recomputes unresolved equality, reports
only new sample rows and states the override boundary accurately. Complete
focused product, persistence, UI and architecture checks pass. Freeze the
documented head for final review and H-tier Linux/Windows/terminal gates.

`SCHEMA_V2_INTEGRITY_CORRECTION` whole-diff review approved product behavior at
`fdc74518806b33b987138cefa04fc344e11d637e`, while risk review reproduced one
application-written schema-v2 checksum gap. Run `31416908410` is cancelled and
stale. Commit `f244709db135847508732cfd6398508928d8a3b3` verifies hash-shaped
schema-v2 revisions during canonical load and onboarding's in-guard CAS,
preserving non-hash legacy compatibility. Canonical/active-config tamper
rejection and backup preservation regressions pass. Freeze the documented head
for final review and H-tier Linux/Windows/terminal gates.

`LEGACY_LAUNDERING_CORRECTION` both reviews rejected exact head
`82cebca3f749a11733de3d670ee1981a51715827` because schema-v2 tamper or revision
downgrade could be republished and backed up through canonical save. Run
`31418506968` is cancelled and stale. Commit
`fb548c4467274a70a5c58277334c15db5aa07a8e` requires explicit migration before
legacy active use/save, validates before backup and inside the held guard, and
blocks manager saves from integrity-invalid snapshots. Laundering, downgrade,
no-backup and UI-block regressions pass. Freeze the documented head for final
review and H-tier Linux/Windows/terminal gates.

`GUARDED_V2_MIGRATION_CORRECTION` both final reviewers rejected exact head
`1245881daf1a60a5a229789329bf5d31d11db6e4` for two reproduced persistence
gaps despite passing H-tier run `31420199673`: the explicit migration path
could not publish any schema-v2 store, and rejected guarded races could leave
backup artifacts. Commit `916ee1aa3a8228f1bab46ae4546c3b523d23c12c`
provides one explicit checksum/CAS-guarded v2-to-v3 migration, requires
acknowledgement for unverifiable non-hash legacy data, preserves records and
duplicate policy, verifies successful backups and leaves no backup artifacts
after stale or tampered rejection. The complete universe, onboarding and
manager surface passes with one expected capability skip; Ruff, compile, diff
hygiene and generated-state checks pass. Freeze one replacement exact head for
parallel whole-diff/risk review and fresh H-tier Linux/Windows/terminal gates.
`execution_allowed=false` remains unchanged.

`OWNED_DESTINATION_AND_BACKUP_CORRECTION` re-review rejected exact head
`5289d1206b0a88e990a9bc57538b4d9706c0435d` for a junction swap before
atomic destination resolution and stale cleanup deleting a following writer's
verified backup. Run `31449729020` is cancelled and stale. Commit
`3a6ffe1bcf2e48fa055b6e7db8323e451e2b60b4` revalidates destination identity
before atomic resolution and under the held guard, deletes only the rejecting
writer's owned backup checkpoint and makes backup creation exception-safe.
Both exact regressions and the complete affected persistence/application suite
pass. Freeze one replacement exact head for parallel final review and fresh
H-tier Linux/Windows/terminal evidence. `execution_allowed=false` remains
unchanged.

`FINAL_GUARDED_STORE_CORRECTION` parallel review rejected exact head
`5aa6c9bcb4af6f33e5347938d6731f76a6d9233f` for four reproduced cases:
caller-bypassable legacy migration, post-commit backup ambiguity, symlinked
canonical-store escape and orphaned policy profiles after legal same-tier
onboarding replacement. Run `31448286398` is cancelled and stale. Commit
`c2397dc20500b534ba17ccdb4a048831721ddabd` binds migration authority to the
exact source digest and acknowledgement decision, completes verification and
backup retention under the held group guard, rejects symlinked canonical
destinations and filters profiles to retained records. All four regressions and
the complete universe/onboarding/manager suite pass with two capability skips;
Ruff, compile and diff hygiene pass. Freeze one final documented head for both
exact-head reviews and fresh H-tier Linux/Windows/terminal evidence.
`execution_allowed=false` remains unchanged.

## ISSUE-0018 lifecycle completion — 2026-08-11

Product PR #674 merged reviewed head `5b2bd54347fc8b2b683bc44b9a415702a7a778b2`
as `94e6376e1a81cdd11bc6c64adc1ebd6499c26bac` after exact-head H-tier run
`31462859675` passed classifier, preflight, supply chain, Linux, Windows and
terminal validation and both independent reviews approved. The dedicated
lifecycle transaction permits only ISSUE-0018
`implemented_initially -> integrated`. Live plan
`ed62f5135396abb107b07b808aafe77733a2b3856e45cbb11ddb179458c9b0d7`
contains one programme-status update for GitHub #22 and no other action;
authority sequence 23 binds that plan to the exact product merge. After merge,
require writer `applied_and_verified`, generic zero-action readback and
unchanged `execution_allowed=false`, then select the next canonical
dependency-ready issue.

`WRITER_READ_REPAIR` lifecycle PR #675 merged reviewed head
`d1333017f86d1b1dc6c5bbe79dbc975257baaaf6` as
`f4f6707d19e4de0d26144971f6c254750e44aaa2` after status guard
`31493345117` and H-tier run `31493345148` passed. Writer run `31497001531`
failed closed with zero transport writes: its first authenticated Actions-run
read succeeded, while the required fresh reread hit a transient CLI/API
failure. The one bounded H-tier repair adds only explicit transient handling to
the read path and exact regressions; it does not retry writes, cache caller
proof, broaden authority or change `execution_allowed=false`.

## ISSUE-0021 final applicability and point-in-time correction — 2026-08-12

Exact head `db62cdccfd5a7327d7a4923f1ade6f40b778c6d0` and hosted run
`31514947591` are invalidated. Both reviewers reproduced the configured-stock
zero-exit path into the ETF-only rebalance preview; risk review additionally
reproduced future-known overlap evidence selected after the sandbox as-of. One
consolidated correction uses the existing canonical capability decision for
every held or positive-target preview instrument and passes a timezone-aware
snapshot cutoff into the existing overlap service. Exact configured-`UCG` and
future-known overlap regressions pass. No execution, proposal, ledger or broker
authority changes; `execution_allowed=false` remains unchanged.

`SOURCE_IDENTITY_AND_RELOAD_CORRECTION` invalidates exact head
`55f3185500d36b18e9839727fcf380973d9b7dfd` and run `31516901901`. Parallel
review reproduced four bounded defects: overlap could read beyond its emitted
binding as-of, adjusted-price changes were absent from result source identity,
a supplied candidate checksum needed only valid length, and a saved mixed-asset
target became unreadable after leaving current holdings. The correction uses
one as-of for binding and overlap, binds price revision/checksum, requires exact
candidate checksum equality and reconstructs persisted intent independently
before current-snapshot recomputation. Exact regressions pass and
`execution_allowed=false` remains unchanged.

`CANONICAL_ASOF_AND_SELECTOR_IDENTITY_CORRECTION` invalidates exact head
`f96ba9d3ddaa3f21d1d360e1204352c2b673bcc7` and run `31518687496`. Whole-diff
review reproduced candidate/result as-of divergence; risk review reproduced
snapshot relabelling through UI selectors. Candidate, result and overlap now
share one report decision as-of, persisted as-of identities are cross-checked,
and requested account/portfolio/snapshot values must exactly match the supplied
immutable snapshot. Distinct A/B binding and fail-closed UI/application
regressions pass; `execution_allowed=false` remains unchanged.

## ISSUE-0024 product lane — 2026-08-12

ISSUE-0021 PR #677 merged reviewed head
`42b8dce8ab34441c78c4e4e82ac7d1d9cf894ad1` as exact main
`6784b054d13b36c0ca4cd6434ab1bec85cc8131f`; H-tier run `31520049790`
passed Linux, Windows and terminal validation. ISSUE-0024 is now the earliest
canonical dependency-ready phase-01 product issue. Clean branch
`codex/issue0024-product-20260812` starts from that exact main.

The exact-main audit found the event schema, required event vocabulary,
local-first atomic persistence, availability cutoff and both required UI
surfaces already present. Implement only the reproduced boundary gaps:
validate timezone metadata, expose explicit decision-time availability in
normal event readback and add focused all-type plus quota/unavailable evidence.
No provider/network, score, proposal, broker or execution authority is added;
`execution_allowed=false` remains unchanged.

The completed bounded delta validates IANA timezone metadata, rejects ambiguous
datetime cutoffs, applies the existing availability/ingestion filter to both UI
surfaces and exposes exact decision-time provenance only for rows known at that
cutoff. Missing cutoffs suppress event rows. The focused 73-test event/import,
source-policy, quota non-destruction, UI and architecture set plus Ruff,
compile, programme check and diff hygiene pass. Freeze one classified exact
head for parallel review and required hosted validation.

`CONSOLIDATED_EVENT_INTEGRITY_CORRECTION` invalidates exact head
`527c9062c2c73d94898d98aa403e4803dddfb6b1` and run `31525671258` after
both parallel verdicts were collected. The demonstrated defects were a lost
concurrent append, malformed-ledger disclosure, populated event time under date
precision and lost public-route coverage. The single closure serializes the
append transaction, rejects incomplete, tampered or authority-inconsistent
canonical rows on load and append, enforces precision and restores the public
News/Context route test. Synchronized two-writer, malformed-ledger no-write,
both UI and complete affected focused suites plus Ruff, compile, generator
check and diff hygiene pass. Freeze one replacement exact head for both reviews
and fresh H-tier gates; do not add retry or adjacent persistence architecture.

`EVENT_TRIAD_AND_CONFLICT_CORRECTION` invalidates replacement head
`87422b3d99222a5b6e30b1c9153b22accad9660d` and run `31527781649` after
both repeated reviews completed. The sole bounded follow-up binds clean rows
to exact contained raw JSON and audit row/frame checksums, requires lexical
`YYYY-MM-DD`, and rejects conflicting valid observations on load/disclosure.
Add exact no-write and both-surface regressions only; do not broaden the event
store, add recovery, or reopen infrastructure work.

The bounded follow-up closes the exact set: clean rows bind to canonical raw
paths/payloads and audit row/frame identity; orphan, missing, extra, escaped or
tampered evidence fails before writes; dates are lexical; duplicate/conflicting
observations fail load and both UI surfaces. The complete affected suites and
static/generator checks pass. Freeze this final replacement for both reviews
and fresh H-tier validation without adjacent generalisation.

`FINAL_EVENT_BUNDLE_CLOSURE` invalidates `cba1b3e8090445a119bbc9e9213a919f9c093f0d`
and run `31529996742`. Both final verdicts identified only audit-entry content
binding and nested raw JSON enumeration. Derive the complete audit validation
list from canonical rows and reject nested/linked raw entries, with exact
no-write regressions. This is the terminal bounded closure; do not add another
event-store hardening cycle.

`RAW_INVENTORY_PREFLIGHT_CORRECTION` invalidates
`243949f8dc03f4f8328fa6bbf427d55e6004c58b` and run `31531221048` after the
complete parallel verdict set reproduced the same bounded inventory gap in
fresh and existing bundles. A missing clean ledger now rejects every existing
raw entry; a complete bundle accepts only its exact canonical raw JSON files
and the atomic writer's named durable guard. Nested fresh evidence and extra
non-JSON existing evidence fail before any clean, audit or raw write. Add no
retry, recovery or adjacent persistence redesign; freeze one replacement head
for both reviews and fresh H-tier validation.

## ISSUE-0024 completion and ISSUE-0033 lane — 2026-08-12

ISSUE-0024 PR #678 merged reviewed head
`89634f179eb947d4f0af8685cf4ef025685dd618` as exact main
`4f7082d06d1695158d8998563dc083e86fe5e364` after H-tier run `31533062736`
passed Linux, Windows and terminal validation. Exact-main evidence confirms
ISSUE-0026 and ISSUE-0027 product implementations already remain present and
focused green; do not repeat them. ISSUE-0033 is the next dependency-ready
phase-01 issue. Its clean product lane starts at the exact main above and is
bounded to local typed alerts/reminders, lifecycle persistence, explicit block
policy and accepted UI readback. External notifications, order mutation and
execution authority remain prohibited; `execution_allowed=false` is unchanged.

The bounded ISSUE-0033 implementation now turns strict typed observations into
the eight accepted local alert classes with explicit thresholds and evidence,
CAS-backed dedupe/lifecycle persistence, point-in-time snooze/dismiss/expiry
evaluation and explicit portfolio/order/model incident rules. Only active
alerts matching a supplied policy can block; the default remains
informational. Dashboard, Activity Log and Instrument Detail expose safe local
readback, with Dashboard dismiss/one-day-snooze actions and explicit corrupt
store unavailability. Focused alert, UI, storage and architecture tests plus
changed-app smoke and static/programme checks pass. Freeze one classified head
for both independent reviews and hosted evidence; no external notification or
execution path is added.

## ISSUE-0033 completion and ISSUE-0053 lane — 2026-08-12

ISSUE-0033 PR #679 merged reviewed head
`2e51ad9301930b2cfcc2a20d70dd52152719801f` as exact main
`6df628966908ba15b5359762e1efe99c0199618f`; H-tier run `31545092924`
passed Linux, Windows and terminal validation. Exact-main audits show no
remaining ISSUE-0034 or ISSUE-0036 product delta. ISSUE-0053 is the next
dependency-ready phase-01 product issue and its clean branch
`codex/issue0053-product-20260812` starts from that exact main.

Implement a concise, deterministic, context-only Dashboard digest covering
score/rank changes, warning changes, model failures, news/macro conflicts,
manual-review needs, upcoming events, stale data and recent audit/export
status. Use current canonical application/data seams and treat the old
unmerged ISSUE-0053 branch only as reference evidence; do not transplant its
stale repository state. No order, provider, network or execution authority is
added and `execution_allowed=false` remains unchanged.

The bounded implementation now builds a stable, severity-ordered and capped
nine-source digest from existing local evidence. One validated snapshot cutoff
governs timestamp-attributable score runs, the complete active alert population,
news/adjusted-price evidence and upcoming events. Canonical news metadata and
finite positive, instrument-matched prices fail closed; score and rank truth
remain separate; missing evidence is not reported as zero change; interrupted
exports and both decision fields reach manual review. Conflicting same-date
adjusted closes fail closed and warning no-change is emitted only when both runs
provide comparable evidence. Macro contradiction comparison remains explicitly
manual-review because no canonical comparison seam exists. The Dashboard
evidence control is context-only with visible provenance/as-of and
`execution_allowed=false`. The final review correction passes 34 focused digest
and 6 run-change tests plus Ruff, compile, programme freshness and diff hygiene.
Freeze one exact replacement head for both reviews and fresh hosted validation.

## ISSUE-0053 completion and ISSUE-0058 lane — 2026-08-12

ISSUE-0053 PR #680 merged exact independently approved head
`a5bd22b0906c55ad789e261e8bfceedb029787b0` as exact main
`542862895dbdc7f29b1dd4c9b686ac526ae8ab94`; O-tier run `31551246756`
passed classifier, preflight, supply chain and terminal validation. ISSUE-0058
is the next dependency-ready P2 product gap and its clean branch
`codex/issue0058-product-20260812` starts from that exact main.

Extend only the existing manual-note credibility classifier and current
UI/audit consumers with structured flags for promotional funnels, closed-source
and screenshot claims, implausible return claims and missing methodology,
benchmark, drawdown, costs/slippage, sample size or reproducibility evidence.
Keep all notes local, context-only and `execution_allowed=false`; add no
provider, network, score or execution authority.

The bounded implementation persists nine deterministic reason codes and
per-code states, validates their internal consistency and leaves legacy rows
explicitly unknown/unavailable. News & Context, Data & Models, Audit
Notes/export and Instrument Detail consume the same local evidence; corrupt
stores fail visibly closed. The consolidated review correction excludes source
metadata from claim semantics, handles explicit "no missing" evidence lists,
checks persisted states against canonical reclassification and restores the
presentation/application boundary. Fourteen focused tests and architecture
checks pass; the 204-test affected run had one unrelated cache-lifecycle timing
failure that passed its single allowed exact retry. Ruff, compile, programme
freshness and diff hygiene pass. Freeze one replacement O-tier exact head for
both independent reviews and fresh cadence-required hosted package validation;
preserve
`execution_allowed=false` and `executable_authority=false`.

## ISSUE-0058 completion and ISSUE-0051 lane — 2026-08-12

ISSUE-0058 PR #681 merged reviewed head
`c37e7452c1ef7abf2568854094d636bc21362935` as exact main
`5d584e860ade7a7b0ecbbaaaa5efb3161c47c2b9`; run `31555021894` passed
Linux, Windows and terminal validation. The next dependency-valid product issue
is ISSUE-0051. ISSUE-0046 remains downstream of the unresolved ISSUE-0108 and
ISSUE-0112 financial contracts and must not invent their semantics.

The clean `codex/issue0051-product-20260812` lane starts from that exact main.
Build only the official-evidence, point-in-time cash comparison contract:
currency, exact horizon, vintage, total-return convention, reinvestment,
freshness, inflation context and explicit unavailable states. Preserve local
and user-owned import operation, existing score/action behavior and
`execution_allowed=false`; do not implement benchmark hierarchy or expand
provider, broker or execution authority. Treat the change as H-tier.

The bounded result now converts only complete, then-known official spot-curve
evidence into exact-period cash total return under declared compounding,
day-count, reinvestment and freshness semantics. Currency, horizon and the UTC
period-start knowledge cutoff are exact; later vintages and malformed,
partial, stale, conflicted or unsupported evidence remain unavailable.
Inflation is context only. A validated caller result traverses score,
scoreboard, attribution projection and both comparison/detail readbacks, while
missing or malformed input cannot change score, action, gate or authority.
The focused seven-suite regression passes 183 tests and the final ISSUE-0051
suite passes 24, plus static, compile, programme-freshness and diff checks.
Freeze one H-tier exact head for paired review and full hosted evidence.

Final root review reproduced two remaining fail-closed gaps before publication.
Direct benchmark attribution now validates cash evidence against the declared
instrument currency, and the normal local path excludes adjusted endpoints
whose conservative next-UTC-day availability time is still in the future.
The final ISSUE-0051 suite passes 35 tests; Ruff, compile, programme freshness
and diff hygiene remain clean. Freeze one replacement H-tier exact head for
both independent reviews and fresh Linux, Windows and terminal validation.

Paired review of that head reproduced five further bounded defects: official
provenance and explicit curve timestamps were not positive contracts, tenor
selection assumed ACT/365F, valid cash was lost when broad attribution lacked
observations, inverted effective/available times survived and missing currency
could bypass generic attribution/persistence binding. One consolidated
correction closes all five with explicit official-source authority,
timezone-aware timestamps, day-count-coupled lookup, preserved descriptive
cash, bitemporal ordering and mandatory currency. The ISSUE-0051 suite passes
45 tests and directly affected warehouse, attribution, score and trust suites
pass; Ruff, compile, programme freshness and diff hygiene are clean. Cancelled
run `31563287001` is invalid; freeze one replacement H-tier head for paired
review and fresh Linux, Windows and terminal validation.

Paired review rejected `8f37a76abe2742985f48c7074a7c7a5fd05f37b0`
after reproducing malformed adjusted-price rows being discarded, partial
multi-point curve writes, nullable curve revisions widened in mixed-row
persistence, and non-risk-free rows accepted as cash curves. Exact-head run
`31601620259` is cancelled and invalid. Consolidated product commit
`695acd192656107059e77361d33d2efe3f775012` strictly validates every adjusted-price row in both calculation
paths, commits each curve snapshot atomically, preserves nullable integer
revision identity through persistence, and requires `risk_free` curve kind
throughout ingest and readback. Exact adversarial regressions and the full
affected 247-test focused surface plus static and programme checks pass.
Freeze one replacement H-tier head for paired final review and fresh Linux,
Windows and terminal validation.

Paired review rejected `b78373eb8759c02b5ced04ad0872bae38f8fab6e`
because cash unit/kind/input-authority identity was not preserved, curve
history validation was outside the serialized append boundary and poisoned
earlier decision-time prefixes, and manifest failure left a committed batch
that could not be resubmitted. Exact-head run `31605516797` is cancelled and
invalid. Consolidated product commit `24c02406819052da86c297fcf9d5f5ca5b3f88d9` carries and validates decimal
risk-free evidence and disabled authority through every projection/readback,
serializes prospective history validation with all snapshot points, limits
readback validation to eligible history, and rolls database changes back when
manifest projection fails. Exact unit/authority, concurrent-conflict,
chronology-prefix and manifest rollback regressions plus the complete affected
focused, static and programme checks pass. Freeze one replacement H-tier head
for paired final review and fresh Linux, Windows and terminal validation.

Paired review rejected `fd112929181768b6d065b45da97f9e5929bc0357`
because generic curve ingestion bypassed serialized admission, future
malformed rows poisoned earlier decision-time reads, the JSON manifest could
diverge from a failed SQLite commit, direct attribution omitted unit/kind, and
non-string status could escape fail-closed validation. Exact-head run
`31609238072` is cancelled and invalid. Consolidated product commit
`4ed063c0b7411a0e70e95d76a5b84e0d5b618333` rejects generic curve rows,
filters raw history before decoding, stores the authoritative immutable
manifest with points in SQLite while treating JSON as projection, and
preserves cash identity with strict malformed-status handling. Exact
regressions and the complete affected focused, static and programme checks
pass. Freeze one replacement H-tier head for paired final review and fresh
Linux, Windows and terminal validation.

Paired review rejected `302fb671ab25c23cff9a2c45bbe405f836562b10`
for inverted persisted chronology, blank curve lineage, direct-score cash
bypass, stale-primary fallback suppression, future malformed generic history
poisoning, and duplicate-key proxy configuration. Exact-head run
`31613846758` is cancelled and invalid. Consolidated product commit
`db7d17166875324c3c5802bdd6f11a13e78df7a3` closes those six exact
boundaries with fail-closed chronology/lineage/config validation, cutoff-first
decoding, fresh fallback selection, and canonical score cash sanitization.
Exact regressions and the complete affected focused, static and programme
checks pass. Freeze one replacement H-tier head for paired final review and
fresh Linux, Windows and terminal validation.

Paired review rejected `c559e0cd0c0663d58eefdff81836aed26cde96dc`
because unavailable direct scores retained injected cash fields and a primary
with missing freshness suppressed a valid fresh fallback. Exact-head run
`31617207389` is cancelled and invalid. Consolidated product commit
`3840fd5fe5fb3c9c91d74fd366ded6b92a34930b` clears all unavailable cash
projection fields and requires both freshness declarations to be explicitly
fresh before selection. Exact regressions and the complete affected focused,
static and programme checks pass. Freeze one replacement H-tier head for
paired final review and fresh Linux, Windows and terminal validation.

Paired review rejected `5f7f4144529f923c6499498ee29db98ef97c48e8`
because the exported return helper accepted non-positive periods and cash
comparison evidence lacked immutable instrument identity. Exact-head run
`31624964263` is cancelled and invalid. Product commit
`56f3d13f17fc723478d4a853ba59be908abc8c43` rejects same-day/inverted
periods and binds instrument identity through calculation, validation, score,
attribution, persistence and selector readback. Same-currency swap and period
regressions plus the complete affected focused, static and programme checks
pass. Freeze one replacement H-tier head after the attributable packaged gate
reaches a terminal result.

Paired review rejected `5d8f7203648442928fcbad55ab3d02385a0df820`
on one malformed-input escape: `pd.NA` cash currency was normalized before
the guarded boundary. Exact-head run `31619460965` is cancelled and invalid.
Product commit `77e0b932e2cb97f7c920e44a3daa3bfbdeb3f6e2` strictly types evidence
currency inside the fail-closed block; the exact regression and complete
ISSUE-0051 suite pass with static and diff checks. Freeze one replacement
H-tier head for paired final review and fresh Linux, Windows and terminal
validation.

Paired review rejected `91881c4bc6d30c0f22fd469d4f854064ecdda7ed`
because fallback provenance could contradict the selected curve. Exact-head
run `31623845675` is cancelled and invalid. Product commit
`d21ec796e9aa52eb9ef89f8a33cfc7e1c0031eba` requires primary evidence to
omit `fallback_from` and fallback evidence to name a distinct nonblank primary
in construction and serialized readback. Exact regressions and the affected
focused, static and programme checks pass. Freeze one replacement H-tier head
for paired final review and fresh Linux, Windows and terminal validation.

Paired review rejected `4547bb9effb5cc281153453fcd51c660cb244df3`
because `pd.NA` direct-score status and instrument currency could escape as
ambiguous-boolean exceptions. Exact-head run `31620960088` is cancelled and
invalid. Product commit `2933fc2df7c52d06df579b835fa6b54cfdc9ccbb`
strictly normalizes those two scalar boundaries to unavailable; exact
regressions and the affected focused, static and programme checks pass. Freeze
one replacement H-tier head for paired final review and fresh Linux, Windows
and terminal validation.

Paired review rejected `1ed00119a5978ae656380064bdfbf0a96f61da2f`
because offset-bearing adjusted-price timestamps were reduced to local dates
before UTC availability and direct-score `pd.NA` instrument currency could
raise. Exact-head run `31622330986` is cancelled and invalid. Product commit
`45ea6cf56d343ab5e7d6cbe8c3944a7aeceee1e5` enforces date-only/UTC-midnight
price endpoints and strictly types direct-score currency. Exact regressions
and affected focused, static and programme checks pass. Freeze one replacement
H-tier head for paired final review and fresh Linux, Windows and terminal
validation.

Paired review rejected `7245e76ac27606f9542fd71dd354d178fcdcd5b1`
for partial snapshot visibility, inferred availability accepted as exact and
persisted cash accepted without currency. Run `31593071919` is cancelled and
invalid. Consolidated product commit
`e6a2b209a05a0ed4d51370a72e6a58f03a56f6ad` requires complete declared
point count, exact availability/timezone confidence and currency-bound
persisted readback. Exact regressions and the complete affected financial,
persistence and UI suites plus static/programme checks pass. Freeze one
replacement H-tier head for paired review and fresh hosted validation.

Paired review rejected `ea1f13105a22f7824a1870be14600f0f1d4b6435`
for missing/duplicate direct tenor identity and unsupported reinvestment. Run
`31594650274` is cancelled and invalid. Consolidated product commit
`a418e341941bd4d1ac7fa25527d73ab700ff4e6a` makes malformed direct rows
explicitly unavailable, requires unique complete tenors and restricts cash to
the supported reinvested-income convention through every boundary. Exact
regressions, complete cash/macro/bitemporal suites and static/programme checks
pass. Freeze one replacement H-tier head for paired review and fresh gates.

Final paired review then reproduced one direct-ingest timezone bypass and two
strict-decoding gaps: blank lineage and fractional/boolean revision identities.
The bounded follow-up requires explicit timezone-aware timestamps on every
curve-bearing warehouse row, nonblank construction/readback lineage and
positive integral non-boolean revisions. The combined ISSUE-0051 and
macro-warehouse run passes 67 tests; Ruff, compile, programme freshness and
diff hygiene pass. Cancelled run `31564924105` is invalid; publish only the
new exact H-tier head.

Paired review of `bb98f3151d05501272754b0f26f681f282621233` next
reproduced coercive revision decoding at both curve model boundaries and
impossible total returns at serialized and continuous-compounding boundaries.
The bounded correction requires strict positive integer revisions with no
boolean/float/string coercion and requires every instrument/cash total return
to remain finite and greater than -100%. The combined ISSUE-0051 and
macro-warehouse suites, Ruff, compile, programme freshness and diff hygiene
pass. Run `31565656403` passed but is invalid because its exact head was
review-rejected; publish one replacement H-tier head for fresh paired review
and Linux, Windows and terminal gates.

Paired review of `a6833a337b1e31572b6cb082bbf01bd07555a95d`
then reproduced three remaining boundary bypasses: ledger/readback revision
coercion, adjusted-price division underflow to an impossible -100% return and
whitespace-only fallback lineage. The consolidated correction validates
revision identity before bitemporal append and at bitemporal/macro readback,
rejects underflowed adjusted returns during construction and requires nonblank
conditional fallback lineage. All 156 affected bitemporal, macro, cash,
attribution, score and Instrument Detail tests pass; Ruff, compile, programme
freshness and diff hygiene pass. Run `31581729559` is invalid/cancelled;
freeze one replacement H-tier head for fresh paired review and Linux, Windows
and terminal gates.

Paired review of `a6a185930517b8668298a0b687aad660a6ffe7be`
then reproduced only coercive/non-finite curve points, marker and CSV revision
coercion, and dropped valid scoreboard cash during attribution fallback. Run
`31584468586` is cancelled and invalid. Consolidated product commit
`90bde0e18934662c1aafe9e27b9c70c371f3d40a` closes those exact paths with
strict curve evidence, strict stored/import revision identity and validated
scoreboard-cash fallback. The complete affected financial, persistence and UI
suites plus Ruff, compile, programme freshness and diff hygiene pass. Freeze
one documented replacement H-tier head for parallel final review and fresh
Linux, Windows and terminal gates; do not widen the repair.

Both reviews rejected `3e9049d329d7ed455b43885f345928ecaa5d22c4`
for coercive cash numerics; risk review also reproduced a direct curve row
whose declared ID disagreed with its storage dataset. Invalid run
`31587875943` timed out only because the affected selector included the
otherwise unchanged slow Instrument Detail test file. Consolidated product
commit `f0cded147c0eeaec0cc48ab4b724e6bb4b16c9a6` strictly validates every
cash numeric before conversion, binds direct curve dataset identity on ingest
and readback, and retains the fallback regression in the focused ISSUE-0051
suite. The exact regressions, complete cash/macro suites, bitemporal coverage
and static/programme checks pass. Freeze one replacement H-tier head for
parallel review and fresh Linux, Windows and terminal gates.

Paired review rejected `df9f7115f7df5992828798fe6e36f56ef765d63f`
for future publication evidence accepted as then-known and scoreboard cash
accepted without declared instrument currency. Run `31589943093` is cancelled
and invalid. Consolidated product commit
`e7b5bec9b74fe3ed0fc46541abbbb58c43102d48` binds publication chronology
from curve ingest/readback through every cash projection and requires currency
before selector fallback. Exact regressions, complete cash/macro suites,
coupled attribution/score/detail suites and static/programme checks pass.
Freeze one replacement H-tier head for paired review and fresh hosted gates.

Paired review rejected `8e13454f837383f91ba57a76b63c9fbd88b99210`
for synthesized snapshot publication, coercive proxy horizon bounds and a
missing non-execution field in projection round-trip. Run `31591207680` is
cancelled and invalid. Consolidated product commit
`ef02901442c360e494cca8999aaf80d04f24acb3` makes publication explicit and
independent, strictly validates finite bounds, and preserves
`execution_allowed=false` through canonical projection/readback. Exact
regressions and the complete cash/macro/bitemporal surface plus static and
programme checks pass. Freeze one replacement H-tier head for paired final
review and fresh Linux, Windows and terminal validation.

Paired review rejected `b311951978c8a29d704b03bb084c277c9365a4fa`
because malformed persisted curve rows could escape readback and a missing
reinvestment convention remained available. Exact-head run `31596482736` is
cancelled and invalid. Consolidated product commit
`0f873715766c48815ceea8f471eb01d39c512183` places persisted-row decoding
inside the fail-closed curve boundary and requires `reinvested_income` at
snapshot and readback boundaries. Exact corrupt-ledger and
missing-reinvestment regressions plus complete cash/macro/bitemporal, static
and programme checks pass. Freeze one replacement H-tier head for paired final
review and fresh Linux, Windows and terminal validation.

Paired review rejected `4bfd2203b8c4f9891600608b0fde7411100a0f72`
with six reproduced evidence-boundary defects: subsecond timestamp loss,
duplicate or regressing curve revisions, coercive authority booleans,
ambiguous financial dates, a builder/readback cutoff mismatch, and direct
curves lacking official lineage suppressing valid fallback. Exact-head run
`31598259140` is cancelled and invalid. Consolidated product commit
`16aa063435d95cea57f5d71204336bc8c5dc3000` preserves subsecond chronology,
validates persisted revision history, strictly types policy/authority data,
requires canonical dates and cutoffs, and fails closed on unofficial curve
lineage. Exact adversarial regressions and complete affected focused, static
and programme checks pass. Freeze one replacement H-tier head for paired final
review and fresh Linux, Windows and terminal validation.

Final paired review of `366407d644fffd0e6276b41e1292a73f05a7a771`
produced one approval and one exact identity finding: persisted scoreboard cash
could be reaccepted against its self-declared currency instead of the canonical
configured currency. Run `31631451728` is cancelled and invalid. The single
bounded correction passes canonical instrument ID and currency into the
existing attribution validator, so stale USD evidence remains unavailable for
a configured EUR instrument. The complete ISSUE-0051 suite and static,
programme and diff checks pass. Freeze one replacement H-tier head for paired
review and fresh hosted Linux, Windows and terminal validation; preserve
`execution_allowed=false`.

Paired review of `70eae22148fc3b32779991cd44d73b0c4759df13`
approved canonical attribution binding but reproduced non-scalar currency
raising during attribution persistence and malformed persisted curve
`ingested_at` reading as available. Run `31635448229` is cancelled and invalid.
The combined correction strictly types persistence currency and validates
timezone-aware ingestion lineage at curve-history readback. Exact regressions,
the complete ISSUE-0051 and macro-warehouse suites, and static/programme checks
pass. Freeze one replacement H-tier head for paired review and fresh Linux,
Windows and terminal validation; preserve `execution_allowed=false`.

Whole-diff review approved `dac31303204db8b7a6c0dc39a11bb6ff3e6d576c`,
while risk review reproduced curve ingestion preceding declared availability.
Run `31637457785` is cancelled and invalid. The bounded follow-up requires
`ingested_at >= available_at` at admission and persisted-history readback, with
exact rejection/no-write regressions. The macro-warehouse suite and static
checks pass. Freeze one replacement H-tier head for paired review and fresh
Linux, Windows and terminal evidence; preserve `execution_allowed=false`.

ISSUE-0051 PR #682 merged exact reviewed head
`83c2843632e2e88a39fe3fcefa21858b436aada4` as exact main
`6b9a79d86e4d17656619c1f969b5f44a2d47c4d9` after H-tier run
`31638791406` passed Linux, Windows and terminal evidence. Post-merge
convergence run `31642819307` then failed closed because the existing latest
ISSUE-0018 authority sequence 23 has no GitHub projection. The original writer
attempt recorded zero transport writes before caller-proof failure and its
rerun remained ineligible; live readback confirms issue #22 has no comments and
all other durable authority projections match. The sole bounded repair uses a
fresh first-attempt OIDC-attested invocation but remains hard-bound to that
exact ISSUE-0018 authority, source/head, candidate, ledger and remote identity.
It rejects any existing, partial, non-latest or ambiguous projection and must
finish with full authority reconciliation and generic zero-action readback.
No product, canonical status, permissions, retry, compensation or execution
authority changes are permitted. Require paired exact-head review and fresh
Linux/Windows/terminal H-tier evidence before merge and one-time recovery.

`RECOVERED` repair PR #683 merged exact reviewed head
`9d2a08800d09bb71313ebe3addc2e2ee2ec78b37` as
`84f0353573f8ff7d49af1934d3149271009fc22c` after H-tier run
`31645482556` passed Linux, the permitted Windows timeout retry and terminal
validation. Recovery run `31650363325` then appended exactly the absent
ISSUE-0018 proposal and receipt and completed with full reconciliation and
zero-action readback; an independent generic live plan is also zero action and
`execution_allowed=false` remains unchanged.

`IN_PROGRESS` clean branch `codex/issue0051-lifecycle-start-20260813` starts
from exact main `84f0353573f8ff7d49af1934d3149271009fc22c`. Advance only ISSUE-0051
from `planned` to `in_progress` using PR #682 merge
`6b9a79d86e4d17656619c1f969b5f44a2d47c4d9`, H-tier run `31638791406`
and its exact product reviews. This is the required legal prefix for the
separate aggregate `in_progress -> implemented_initially -> integrated`
completion; no product, dependency edge, permissions or execution authority
changes are included.

`MERGED` ISSUE-0051 initial lifecycle PR #684 preserved exact reviewed head
`342316801ffdb4efc62cdccd160067f2047ef62b` as
`c546f1dd4b2c01356c7164fafa18bab065efa2d1`. Tier-O run `31651266717`,
the standalone guard and both independent reviews passed. Ordered writer run
`31651750441` applied only `planned -> in_progress`, completed full authority
reconciliation and zero-action readback, and preserved `execution_allowed=false`.

`IN_PROGRESS` clean branch `codex/issue0051-completion-20260813` starts from
exact main `c546f1dd4b2c01356c7164fafa18bab065efa2d1`. Record only the aggregate
ISSUE-0051 replay `in_progress -> implemented_initially -> integrated` against
product PR #682 with two independently legal hops, identical product/review
evidence, one proposal/receipt and no dependency-edge or product change.

`INTEGRATED` ISSUE-0051 completion PR #685 merged exact reviewed head
`381c7d013c4e8e326eb3ee68ac5f39adef60bcc3` as
`e5c70f7f08665f5b041e4a20614061ee9f8a85b8`. Cadence run `31652457420`
attempt 2 passed Linux, Windows and terminal validation. Writer run
`31666997864` applied exactly the two ordered hops with one aggregate proposal
and receipt, two writes, complete reconciliation and zero-action readback;
`execution_allowed=false` remains unchanged.

`IN_PROGRESS` clean branch `codex/issue0059-integration-20260813` starts from
exact main `e5c70f7f08665f5b041e4a20614061ee9f8a85b8`. Integrate only ISSUE-0059
using reviewed product PR #574 head `37ef3fc9e18c682408ecc079fc65e85426ccee7e`,
merge `80c63200e733fada6ae2d76ac67feb776f281c38` and exact protected evidence
from release run `30338519123`, status guard `30338519047` and supply-chain run
`30338519237`. Do not change product code or dependency edges. Require focused
E-tier validation, exact-head review, ordered writer and generic zero-action
readback before the separate ISSUE-0112 dependency-edge transaction.

`INTEGRATED` ISSUE-0059 integration PR #686 merged exact reviewed head
`560e68511eb228d831f9c31e0babdafa26c0a57e` as
`87b05852121ff6ecdd1c9b1b8ae5ed423875523c`. Cadence run `31668262647`
passed Linux, the single documented Windows timeout retry and terminal
validation. Writer run `31672396480` applied the one authorized status event
with one proposal and receipt, two writes and zero-action readback;
`execution_allowed=false` remains unchanged.

`IN_PROGRESS` clean branch `codex/issue0112-dependencies-20260813` starts from
exact main `87b05852121ff6ecdd1c9b1b8ae5ed423875523c`. Record only the two
independent ISSUE-0112 dependency edges to integrated ISSUE-0051 and
ISSUE-0059 in the existing atomic same-consumer edge transaction. Do not
change ISSUE-0112 lifecycle status or product code. Require generated
projections, focused E-tier guards and exact-head review before the separate
ISSUE-0112 product lane.

`MERGED` ISSUE-0112 dependency PR #687 preserved exact reviewed head
`9816f420a650f64c6c0fbc24f2b7f9720fe8b124` as
`79d4110f39a0aa903a0df361316befcaaff782eb`. Run `31673015385` passed Linux,
Windows, terminal validation and the status guard. ISSUE-0112 is dependency-
ready, remains `planned`, generic reconciliation is zero action and
`execution_allowed=false` remains unchanged.

`IN_PROGRESS` clean product branch `codex/issue0112-product-review-20260813`
starts from exact main `79d4110f39a0aa903a0df361316befcaaff782eb`. Product commit
`5e8a82153a095c70a2dc3457c60e3891092c6226` implements the bounded canonical
benchmark hierarchy, cash proxy, peer set, equal-weight/maximum-diversification/
no-trade reference portfolios and ISIN-bound VWCE anchor with explicit PIT,
version, source-hash, unavailable and UI projection semantics. Focused and
adjacent evidence reports 166 passing tests with Ruff, mypy, compile, programme
check and diff hygiene green. A read-only live lifecycle preparation reproduced
the existing guard requirement that the reviewed product commit must be an
ancestor of the PR base; the rejected candidate remains isolated and will not
be published. Freeze this product-only lane for paired exact-head review and
fresh H-tier Linux/Windows/terminal evidence. After merge, execute the legal
one-hop start and aggregate two-hop completion with ordered-writer and generic
zero-action readback, without changing product code or execution authority.

`CORRECTED` PR #688 initial head
`76d061ae0452ddfe358829adecd5a91241dbaf03` is rejected by both independent
reviewers and run `31677268341` is cancelled/stale. Consolidated commit
`e927fe25914ec33193cfc74c8b3496c4ef7e4b21` binds VWCE fact, effective,
knowledge, currency, horizon and conversion evidence; seals all nested inputs
and the registry; reconstructs serialized records semantically; enforces the
canonical share class; aligns reference portfolios; and connects the contract
to the portfolio-analysis facade with raw-analysis invariance. All 229 focused
ISSUE-0112, sandbox, cash, attribution, peer and optimiser tests pass with Ruff,
contract mypy, compile, programme byte-clean and diff hygiene evidence. Freeze
one documented replacement head for both independent reviews and fresh H-tier
Linux/Windows/terminal validation; no canonical lifecycle, provider/broker,
release or execution authority changed.

`CORRECTED` replacement head `df974a6a5f16ddeeae4e7e1db63c130aed78693c`
is rejected and run `31679353881` is cancelled/stale. The complete final verdict
identified contradictory registry/anchor availability, invalid listing status,
missing conversion/resolution provenance, invalid horizons, SemVer ordering,
listing/anchor chronology, nested execution evidence and duplicate reference
requests. Consolidated commit `cb3e513d34dfdaf441905ee905f0dc768d4cc11c`
closes exactly those defects and adds canonical digest-bound profile evidence.
All 241 focused and adjacent tests pass with Ruff, contract mypy, compile and
diff hygiene. Freeze one final replacement head for paired exact-head review and
fresh H-tier Linux/Windows/terminal validation; preserve all lifecycle,
provider/broker/release and `execution_allowed=false` boundaries.

`CORRECTED` head `80226ff2737c2963b9f9efb65fda90117e0d43f9` is rejected
and run `31681320326` is cancelled/stale. Commit
`c247b4698c5773b707f41a142ca344d1af7c6f99` prevents a newer stale PIT
definition from silently falling back to an older available version, strictly
types opportunity-anchor flags, and requires complete canonical provenance
before profile-relative claims. All 246 affected tests pass with Ruff, contract
mypy, compile and diff hygiene. Freeze one replacement head for paired final
review and fresh H-tier Linux/Windows/terminal evidence.

`CORRECTED` head `f269c592c28b60f79205f4bbec1a1c2da996d6ff` received one
approval, while risk review reproduced that the shipped builder was
unavailable-only and available selected identities were absent from UI. Run
`31690695124` is cancelled/stale. Commit
`82371502a356ef62231ee39647d2c88da9a57cf8` adds a packaged, validated,
duplicate-key-safe local registry through the existing contract, derives
deterministic real-snapshot PIT inputs, renders selected IDs/versions/digests and
proves rebuilt-snapshot save/load readback. All 320 affected tests plus Ruff,
targeted mypy, compile, packaging assertion, programme freshness and diff hygiene
pass. Freeze one replacement exact head for paired final review and fresh H-tier
Linux/Windows/terminal evidence; no network, provider or execution path changed.

`CORRECTED` head `ccc64e372ed0034a548dd68a4383493cb7874083` is rejected;
run `31692775935` completed but is stale. Paired review reproduced false
placeholder availability, raw-count PIT history rejection, nested execution
export, hidden selected VWCE identity, hard-coded no-trade holdings and JSON EOF
hygiene. Commit `9dccd8d11802eabce3f36dfac59bd22feb370d3c` makes packaged
identity-only records explicitly unavailable with no fabricated hashes, selects
anchor/listing histories by effective and knowledge cutoffs, rejects nested
execution at export, removes hard-coded no-trade and renders selected VWCE
identity/cutoffs. The source-backed available rebuild/save/load path remains
covered. All 324 affected tests plus Ruff, targeted mypy, compile, programme
freshness and diff hygiene pass. Freeze one replacement exact head for paired
final review and fresh H-tier Linux/Windows/terminal evidence.

`CORRECTED` head `4bb842a53d181abcfb309e50740ec22a25648279` is rejected
and run `31682292726` is cancelled/stale. Commit
`2b1cd0d9a9fa422b2fdba002f1cc65b54d8efcfd` makes the newest PIT VWCE
listing authoritative, rejects coercive risk/resolution authority, binds claims
to exact anchor and conversion evidence, and routes snapshot-attached canonical
evidence through ordinary portfolio analysis, save/load and existing UI service
evidence. All 269 affected tests pass with Ruff, contract mypy, compile and diff
hygiene. Freeze one final replacement head for paired review and fresh H-tier
Linux/Windows/terminal validation; preserve `execution_allowed=false`.

`CORRECTED` head `19a19d170edb1df2057e4be1a31b6d4eb076a863` is rejected
and run `31683739150` is cancelled/stale. The complete paired verdict reproduced
four remaining product-delivery defects: no explicit canonical evidence on real
snapshots, no benchmark/profile UI surface, projections not bound to registry
and selected-record digests, and no deterministic replay of available VWCE
resolutions against the actual listing, horizon, conversion and point-in-time
cutoffs. Consolidated commit `db39adbed19a76dca23c0a3764fcd4ddf6a46977`
closes exactly those paths with real production wiring, explicit unavailable
evidence, visible provenance, stale-load rejection and forged-resolution
regressions. The 278 affected contract, sandbox, UI, cash, attribution, peer and
optimiser tests plus Ruff, targeted contract mypy, compile, programme freshness
and diff hygiene pass. Freeze one replacement head for paired final review and
fresh H-tier Linux/Windows/terminal evidence; preserve `execution_allowed=false`.

`CORRECTED` head `d7bb08462ad033ee9537f834ffa89f0ab5fd6e4f` is rejected
and run `31685879923` is cancelled/stale. The paired review reproduced five
strict provenance/input defects: a standalone anchor not bound to the supplied
registry, mixed bound/unbound authoritative listing ties, explicit-empty
override laundering, duplicate reference requests and non-string source-hash
coercion. Consolidated commit `006abd94ec4380407484b1227ba1ae35106d6ea6`
closes exactly those paths with canonical anchor membership/provenance, complete
tied-source validation and strict input handling. All 286 affected tests plus
Ruff, targeted contract mypy, compile, programme freshness and diff hygiene pass.
Freeze one replacement exact head for paired final review and fresh H-tier Linux,
Windows and terminal evidence; preserve `execution_allowed=false`.

`CORRECTED` head `4aa2ef11f72b33775dd6a7cd031c7473a3dff2c7` is rejected
and run `31687764826` is cancelled/stale. Paired review reproduced only four
fail-closed product boundaries: fallback to an older aligned reference version,
standalone anchors outside the canonical registry, string-like listing hashes
and nested execution authority. Commit `858ea6310369dbcb7a765aac128e11307e7b47b6`
selects authoritative references before alignment, requires unique registry
anchor membership and strictly rejects malformed hash and execution evidence.
All 292 affected tests plus Ruff, targeted contract mypy, compile, programme
freshness and diff hygiene pass. Freeze one replacement exact head for paired
final review and fresh H-tier Linux/Windows/terminal evidence.

`CORRECTED` head `e9bab1eeaae710c056e7dff18bb365395587d6c2` is rejected
and run `31689397297` is cancelled/stale. Paired review reproduced a non-string
mapping-key canonical digest collision and forged/non-member projected records.
Commit `0511bb7e5a7984d1fa24899db13c584e22b90b81` rejects non-string
keys recursively and requires each projected available selection/reference to
match exactly one registry record by canonical identity, version and digest.
All 298 affected tests plus Ruff, targeted contract mypy, compile, programme
freshness and diff hygiene pass. Freeze one replacement head for final paired
review and fresh H-tier Linux/Windows/terminal evidence.

`CORRECTED` head `3020c4b811179fb7c77158a9fd1a0eb4ac98bc7d` is rejected and
run `31694667839` is cancelled/stale. Whole-diff review found no additional
code defect; risk review reproduced unbound semantic selection/reference slots
and a wheel registry path that the installed application could not resolve.
The consolidated correction independently revalidates declaration, slot and
reference identity at projection readback, packages the byte-identical registry
as an importable resource and proves loading from an isolated wheel install.
All 163 focused contract/UI/sandbox/package tests and 152 adjacent financial/PIT
tests pass with Ruff, targeted mypy, compile, programme freshness, diff hygiene
and byte-identical relocation evidence. Freeze one replacement exact head for
paired final review and fresh H-tier Linux/Windows/terminal validation; preserve
all lifecycle, provider/broker/release and `execution_allowed=false` boundaries.

`CORRECTED` head `7d0ca499a43fd63b43ced5c6de97a1ffaf24b16e` is rejected by
both independent reviews and run `31696193800` is cancelled/stale. Both reviews
reproduced exactly one omission: the declared peer-set identity was not bound to
the selected available peer or `None` for unavailable peer evidence. Add only
that invariant and available/unavailable forged-readback regressions, then freeze
one replacement exact head for final paired review and fresh H-tier validation.

`CORRECTED` head `4374015cdfc814a30d43c9cc9465f3cfbc3fc49d` received one
approval and one demonstrated acceptance rejection; run `31697195555` is
cancelled/stale. The generic no-trade contract is present, but the production
snapshot requests only equal-weight and maximum-diversification, omitting the
required current-portfolio/no-trade baseline from real analysis and readback.
The bounded correction derives that baseline from exact holdings plus implied
cash, binds it to checksum and PIT evidence, projects weights/provenance through
UI and save-load, and fails closed on malformed inputs. All 170 affected, 152
adjacent financial/PIT and 11 targeted adversarial tests pass with static,
programme and diff checks. Freeze one final replacement exact head for paired
review and fresh H-tier validation.

`CORRECTED` head `97597ab5af3c830ad9e31d2b2d386f01a1f2ce84` is rejected by
both reviews and run `31700680310` is cancelled/stale. The production builder
filtered holdings before no-trade derivation, allowing excluded exposure to be
relabelled as cash and checksum-bound as truth; negative market values were also
accepted. The consolidated correction preserves the complete pre-filter holdings
source for derivation/checksum, rejects excluded holdings and negative/non-finite
values, and proves the production path directly. All 176 affected tests plus
Ruff, targeted mypy, compile, programme freshness, package and diff checks pass.
Freeze one replacement exact head for paired review and fresh H-tier validation.

`CORRECTED` head `5907e23ff1d57a9d6646e0d768b2eea4b10b84f5` is rejected and
run `31702055238` failed preflight with downstream gates skipped. Invalid current
holdings could retain a stale registry no-trade record; source knowledge time was
synthesized and omitted from the holdings checksum; and the isolated-wheel test
called an unavailable backend directly. Always strip stale no-trade, require and
checksum actual non-future knowledge provenance, persist its timestamp, and use
the pinned build frontend without weakening isolated install/load proof. The
consolidated correction passes 180 focused contract/sandbox/UI tests, static and
programme checks, and the actual pinned-frontend isolated wheel build/install/
load proof. Freeze one replacement exact head for paired final review and fresh
H-tier evidence.

`CORRECTED` head `035494598fab594f3cbde7babccc76444c5c3008` is rejected and
run `31707789636` is cancelled/stale. Remaining source/authority/publication/time
metadata aliases counted as VWCE facts and invalid-input fallback omitted explicit
N/A benchmark/cash declarations. Both paths are closed; 200 affected tests and
static/programme/diff checks pass. Freeze one replacement review/gate head.

`CORRECTED` head `1bd954ecbe4381a43089cef551ae52c0163983f2` is rejected by
both reviews and run `31704018549` is cancelled/stale. No-trade weights were not
reconciled to market values, timezone-naive knowledge was silently interpreted
as UTC, and an outer available VWCE anchor could carry unavailable nested fees,
tracking or risk facts. Correct exactly those three fail-closed validations and
add focused regressions. All 199 affected contract/sandbox/UI tests plus the
pinned-frontend isolated wheel proof, Ruff, targeted mypy, compile, programme
freshness and diff hygiene pass. Freeze one replacement review/gate head.

`CORRECTED` head `008ee66f0e161da1d66532a5893731c5c9d8a5ea` is rejected and
run `31706356179` is cancelled/stale. Authority/status/version-only nested VWCE
mappings counted as financial facts. The correction excludes metadata keys and
requires substantive fees, tracking and risk evidence; 200 affected tests and
Ruff pass. Freeze one replacement exact head for paired review and H evidence.

`CORRECTED` head `25677bcbf96ec4f111ce47e9c732401a3df8cf6f` is rejected and
run `31709228880` is cancelled/stale. The final paired verdict reproduced that
`content_hash` still counted as a nested financial fact and that production
attribution, validation, feature and forecast callers could omit the canonical
benchmark/cash declaration or use the first enabled instrument. One consolidated
correction adds the exact metadata regression and a shared fail-closed application
adapter, derives relative outputs only from the canonical mapped price identity,
blocks raw benchmark-return bypass and retains explicit N/A otherwise. The
affected 232-test collection, architecture boundaries, Ruff, targeted mypy,
compile, imports, byte-clean programme generation and diff hygiene pass. Freeze
one replacement exact head for paired review and fresh H-tier Linux, Windows,
terminal and packaged evidence; preserve `execution_allowed=false`.

`CORRECTED` head `0880f0cfc3d7cc1d8ad62886bdf579e3ea65e77f` is rejected by
both reviewers and run `31713061927` is cancelled/stale. The complete verdict
reproduced first-column benchmark use in backtest/regime/score paths, Training
Centre context loss, mutable forged declarations, inconsistent N/A schemas,
unbound forecast/backtest/feature cache reuse and optional forecasts labelling
raw returns as excess. One consolidated production integration correction now
uses the canonical mapped series or explicit N/A everywhere, reconstructs and
recursively validates projections, binds cache writes and all relative-output
readers to exact canonical identity, routes snapshot and UI callers, and
uniformly derives or nulls every model's benchmark-relative fields. Freeze one
replacement head after the affected tests, static/programme/package checks pass,
then repeat paired review and fresh H-tier evidence; no adjacent architecture or
authority work is included and `execution_allowed=false` remains unchanged.

`CORRECTED` head `8c5dc03ba1d939a8c4fad28fc8f246741825b77a` is rejected by
both exact-head reviewers and run `31717953477` is cancelled/stale. The final
bounded finding set covers exact calculation-window identity, canonical peer
membership, recursive execution-authority validation, Training Centre argument
binding, universe/settings/reference feature-cache readback, signal resolution
ordering, complete N/A schemas, the remaining macro caller and restored sparse
benchmark correlation. One consolidated correction addresses only those
reproduced defects. Its 328 affected product/UI tests, 99 macro/regime tests,
five packaged workflow tests, Ruff, targeted mypy, compile, byte-clean programme
generation and diff hygiene pass. Freeze one replacement exact head for paired
review and fresh H-tier Linux, Windows and terminal validation; do not reopen
adjacent convergence or infrastructure work and preserve `execution_allowed=false`.

`CORRECTED` head `713c2a837fc7244cc01e07947fb3e80629446bd7` is rejected by
both exact-head reviewers; run `31722219785` failed the attributable changed-test
preflight and skipped the downstream H gates. The consolidated reproductions are
strict decision-time calculation windows across validation/backtest/attribution,
canonical benchmark/cash and peer binding for every relative path, minimum sample
overlap, immutable retained instrument inputs, supplied-feature sanitisation,
complete N/A schemas, macro routing and the SignalService fixture that triggered
publication without registered prices. One bounded correction closes exactly
these paths. The complete affected suite and exact hosted changed-test command,
including all five packaged workflows, pass with Ruff, targeted mypy, compile,
byte-clean generation and diff hygiene. Freeze one replacement head for paired
review and fresh H-tier Linux, Windows, terminal and parallel-pilot evidence.

`CORRECTED` head `660acbc93444d255341ed337ad3e6cf5fd11894a` is rejected by
both reviewers and run `31726428231` is cancelled/stale. The consolidated newly
reproduced set is same-date-window benchmark attribution, candidate breadth PIT
cutoffs, exact intraday clipping, normal-path official cash evidence, the updated
BacktestService seam and cache structural-validation ordering. One bounded pass
corrects only those six defects and adds direct regressions. The prior full-suite
failures, adversarial ISSUE-0112 set, broad affected tests, changed validation,
Ruff, targeted mypy, compile, generator freshness and diff hygiene pass. Freeze
one final head for paired exact review and fresh authoritative H-tier evidence.

`CORRECTED` head `79fc7445aa2b053baba49fd7b8f7fb36055d8ff9` is rejected and
run `31731679751` is cancelled/stale. Backtest still normalized an exact intraday
cutoff and admitted that date's close, while two blank CRLF lines failed the
whole-diff whitespace gate. Scope all backtest prices through the shared exact
decision-window helper, add the noon-cutoff regression and remove only those
whitespace defects. Focused and exact changed-test/package evidence plus static,
programme and diff checks pass; freeze one replacement head for final review/H.

`PILOT REPAIR` frozen product head `ecff814fd07ae187196b5bc5e22f0e310dbb0a28`
passed both independent reviews and every platform/release/terminal job in run
`31733243156`; only cross-platform aggregation failed. Its report contained the
three tests that explicitly require Windows directory junctions as Linux skipped
and Windows passed. Add only those exact node IDs to the existing platform
outcome contract and cover their actual lanes. Focused tests and replay of the
successful hosted pilot artifacts pass with zero differences. Product behavior,
authority and `execution_allowed=false` remain unchanged; require one corrected
exact head, paired review and fresh H-tier evidence.

`LINUX GATE REPAIR` corrected head `3ec216f679bf3ec4d602985e0a9bca0549231c8c`
is independently approved and run `31755008546` proves Windows release, both
pilots and cross-platform aggregation. Linux release twice terminated in the
same pandas native CSV parser callback during different parsed-disclosure tests.
Replace only the six identical discarded-result CSV post-write validators in
`parsed_disclosures.py` with strict UTF-8 standard-library parsing; retain quoted
multiline fields and reject malformed quoting or inconsistent widths. The full
parsed-disclosure rollback/concurrency suite and Ruff pass. Freeze one replacement
head for paired review and fresh H-tier evidence; do not alter workflows, pins,
atomic I/O, canonical financial behavior, authority or `execution_allowed=false`.

`CACHE BINDING CORRECTION` head `2f67ca378feb2d148c92ff686728ab460dfa7df1`
is rejected and run `31770710533` is cancelled/stale. Whole-diff review approved;
risk review reproduced feature and forecast payload substitution beneath a valid
reference sidecar. Publish only those two payload/identity pairs through the
existing recoverable atomic group, include and verify the payload SHA-256, and
read each pair under one guard. Bound malformed, substituted, interrupted or
interleaved pairs fail closed while valid and explicitly unbound legacy reads
retain compatibility. Fifty-eight focused and adjacent tests plus Ruff, compile
and diff hygiene pass. Freeze one replacement head for paired review and fresh
H-tier evidence; do not alter generic atomic I/O, workflows, product calculations,
authority or `execution_allowed=false`.

`FORECAST TOCTOU CORRECTION` head `59caeac64d422e39e06ec57b8032eaebcd00eb72`
is rejected by both final reviewers and run `31774026353` is cancelled/stale.
They reproduced the same cross-identity race between forecast selection and its
second guarded read. Reuse one complete snapshot validator at both boundaries so
the final snapshot must match the requested universe, settings, reference identity,
identity hash and payload checksum. Add the deterministic identity-A to identity-B
interleaving regression and make no adjacent cache, persistence, workflow,
authority or execution change.

`SETTINGS SELECTOR CORRECTION` head `69cdce6e47d3c3883daab2859fd5b3f32f195ac1`
passed risk review but is rejected by whole-diff review; run `31774945960` is
stale. Filter forecast candidates whenever universe, settings or reference
identity is requested so a newer settings-stale file cannot mask the older valid
cache; add the exact regression. Make the directly changed backtest rollback test
self-contained by stubbing unrelated run-manifest reservation after hosted
preflight exposed its order dependency. Do not change production backtest,
workflow, authority or execution behavior.

`MALFORMED SIDECAR CORRECTION` head `20d619fb996038970f81e655697adfcf5c15cc73`
is rejected and run `31777912307` is stale. Fail closed on the demonstrated
recursive JSON decode and type-forged `false`/`0` identity cases. Recompute the
stored identity's canonical hash and require it to match both the claimed and
requested hashes at every bound feature/forecast/service reader; add direct
regressions. Do not alter generic JSON, atomic I/O, financial calculations,
authority or execution behavior.

`REMAINING CONSUMER CORRECTION` head `8b4ef8d722a84e246489d2eb1cc5eed50f807f96`
is rejected and run `31778851004` is cancelled/stale. Route supplied feature
attrs and cached backtest metadata through the same recomputed identity-hash
verification, persist the backtest identity hash, and activate forecast row
filtering for settings-only requests. Add the exact signal, backtest-tamper and
mixed-source regressions; change no adjacent financial, persistence, workflow,
authority or execution behavior.

`FINAL SNAPSHOT CORRECTION` head `3e7f5677e72de7f2f5ca8a2ebe67e66899afd267`
is rejected and run `31780004420` is cancelled/stale. Publish all backtest
payloads, sidecars and metadata in one existing atomic group and parse one
guarded complete read snapshot; fail closed on a checksum-valid feature parquet
without `date`; and map recursive malformed canonical registry/application input
to the existing error contracts. Add only the exact interleaving, missing-schema
and 10k-depth regressions. Do not change atomic I/O, workflows, financial logic,
authority or execution behavior.
