# Active Codex goal — atomic delivery fast path

## Current checkpoint

- Current UTC timestamp: `2026-07-29T02:14:13Z`
- Current `origin/main`: `b11b1d6783438df03847d7a1b45c3a4d7c1f2385`
- Active worktree: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.worktrees\atomic-fast-path-20260729`
- Active branch: `codex/atomic-fast-path-20260729`
- Exact base SHA: `b11b1d6783438df03847d7a1b45c3a4d7c1f2385`
- Exact last committed control head before this checkpoint update: `877f39b4c68b013d90214efb8b781369c32f4161`
- Current PR and state: draft PR #609 run `30416010061` failed only Product and protected preflight because `generation-manifest.json` hashed raw Windows CRLF bytes and was stale on Linux LF checkout. Classifier, schema-1.3 status guard and supply-chain passed; the package matrix was correctly skipped after preflight failure. The bounded correction is committed at `877f39b4c68b013d90214efb8b781369c32f4161`.
- Current issue: ISSUE-0179 is the primary implementation lane; ISSUE-0090 product work is paused until the atomic fast path is proven.
- Completed work: PR #608 is merged and converged. The sole ISSUE-0179 worker and correction are accepted. Atomic publication, interruption recovery, closed mandatory output manifest, append-only events, independent multi-edge validation, reachable generation provenance, exact E reuse identities, terminal evidence validation and read-only exact-head convergence are implemented. ISSUE-0179→ISSUE-0178 is complete while status remains `planned`; `execution_allowed=false`. The CRLF/LF defect now uses semantic UTF-8 line-ending-normalised hashes while binary bytes remain exact; the adversarial test and complete 124-test affected suite pass with atomic second-run freshness, Ruff, MyPy and diff hygiene.
- Required checks: push the corrected exact head; require fresh classifier, schema-1.3 guard, preflight, supply-chain, complete Linux and Windows packaged H-tier gate and terminal summary before merge.
- Blocker: none. The previous UTC-midnight fixture failure is documented as run `30409555828` attempt 1 and resolved only by the permitted exact unchanged-head retry.
- Exact next action: commit this failure/correction checkpoint, push the new exact PR #609 head, and use one watcher for the fresh H-tier run; do not retry failed run `30416010061`.

## Objective

Replace transaction-heavy ETF AI Cockpit delivery with an atomic,
evidence-reusing Codex/GitHub workflow, while safely completing the current PR
and preserving every financial, safety, audit and cross-platform invariant.

Complete PR #608, stop before further product implementation, implement and
integrate ISSUE-0179, prepare ISSUE-0180 only when safely disjoint, prove the
redesigned workflow, and only then resume dependency-valid product work.

Reduce end-to-end issue delivery time without weakening financial correctness,
point-in-time and revision integrity, immutable replay, Linux and Windows
protection, security and supply-chain controls, auditability,
checksum-controlled GitHub synchronisation, exact-head merge protection or
`execution_allowed=false`.

The replacement global and project `AGENTS.md` files are authoritative.

## Durable memory and compaction survival

Do not rely on chat context as durable truth. Before product, CI or
programme-control changes, read the global and project `AGENTS.md`,
`PLAN_step2.md`, this file, `plans/BATCH-B04-ANALYSIS-SPINE.md`, the relevant
issue records, source and tests.

Maintain the `Current checkpoint` above with current UTC time, `origin/main`,
worktree, branch, exact base/head/upstream, PR state, issue, completed work,
required checks, blocker and exact next action. Reread this file after
compaction, thread/worktree switches, every merge, every base change, before
selecting another issue, before handoff and whenever the action is uncertain.

The first action after compaction is to reread project `AGENTS.md`, this file
and the active B04 batch plan. Update this checkpoint before every handoff.

## Verified incoming handoff

The incoming immutable PR worktree is
`C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.worktrees\issue0090-version-dependency-20260728`
on `codex/issue-0090-version-dependency-20260728`. Its committed local and
upstream head is
`937ec382dfab7acc74ad16e7e706b795c88e63a2`, and it is clean.

Draft PR #608, “Review ISSUE-0090 version-registry dependency”, records only
`ISSUE-0090 → ISSUE-0075: unresolved → complete`. It must not change
ISSUE-0090 programme status, acceptance criteria, product behaviour,
execution authority or broker authority.

ISSUE-0089 is fully integrated. PR #607 merged as
`2337f6959719a9a4ae1b8ec9efb3927ade2acc7d`. The ISSUE-0090 → ISSUE-0072
dependency evidence is complete. ISSUE-0090 remains
`implemented_initially`. Provider projection was zero action at checksum
`23cff2eee691649a17d83f0e8ff5c2833c7b19303f57a2a182f1e75db354d143`.
`execution_allowed=false`; broker authority is unchanged.

Local evidence already passed: 50 version/manifest/invalidation tests, 141
programme-control tests, schema-1.3 dependency-edge guard, registry
validation, generated-document freshness, classifier, preflight and
supply-chain checks.

## Immediate continuation

1. Complete PR #608 under the currently merged workflow. Preserve its exact
   dependency-only scope and head unless a verified failure makes that
   impossible. Use terminal validation as primary evidence. Parse raw
   Linux/Windows artifacts only for failure, inconsistency, missing exact
   counts, final certification or an explicit existing rule. Require clean
   review/comment/thread surfaces, mark ready only when all conditions pass,
   and merge with expected-head protection.
2. Fetch fresh main after merge, confirm the merge SHA, run independent GitHub
   synchronisation dry-run and require zero actions.
3. Verify ISSUE-0090 remains `implemented_initially`, both blocking edges are
   complete, it is dependency-ready, `execution_allowed=false`, broker
   authority unchanged, PR #560 unchanged, stale PR #562 unmerged and issue
   #241 open and unchanged.
4. Pause ISSUE-0090 product implementation and go directly to ISSUE-0179.

## Measured control-plane defect

ISSUE-0089 required six sequential PRs: two dependency edges, one product PR
and three lifecycle PRs. Delivery took about 3h27m while implementation and
local review took about 25m. Status/dependency-only transactions regenerated
roughly 33–35 files and 15,500 lines, classified H and reran unchanged Linux
and Windows packages. The prior log contained 197 explicit polling commands
and about 179 minutes of foreground waiting. ISSUE-0090 began repeating this
through PRs #607–608. This is a control-plane defect, not permission to remove
product safeguards.

## Required execution order

1. Complete and verify PR #608.
2. Persist its exact checkpoint here.
3. Pause ISSUE-0090 product work.
4. Implement and integrate ISSUE-0179 as the primary lane.
5. While ISSUE-0179 has an immutable PR in CI, permit the sole worker to
   prepare ISSUE-0180 only in disjoint files with no shared generated or
   canonical state and no GitHub mutation.
6. Prove the E/O/H/C workflow with the representative fixtures below.
7. Update this file, `PLAN_step2.md`, the B04 plan and accepted workflow docs.
8. Resume ISSUE-0090 or the next dependency-valid issue only after proof.

Do not abandon reviewed checkpoints, alter PR #560, merge stale PR #562,
close issue #241, publish a release, create a tag, deploy, enable execution or
add broker writes.

## Primary lane — ISSUE-0179

Implement “Make programme generation atomic and automate post-merge
convergence”. ISSUE-0178 is integrated. Solve the observed causes rather than
documenting the old workflow.

Acceptance:

- One command produces every canonical generated file; a second check run is
  byte-clean.
- Tests make it impossible to omit current status, progress, reconciliation,
  remote summary or transition manifest.
- Post-merge convergence is one guarded automated transaction with exact-head
  and zero-action readback evidence.
- Median programme transactions fall to at most three per integrated issue
  where dependency semantics allow.
- All existing identities, dependencies, policies and execution authority
  survive migration.

## Secondary lane — ISSUE-0180

Implement “Standardise local, worker and CI environments and isolate tests for
safe parallelism” only under one-writer/disjoint-lane rules. It may remain a
local reviewed checkpoint until ISSUE-0179 merges. It must not touch shared
canonical/generated state, mutate GitHub or create another integration path.

Provide one authoritative environment-verification command for local, worker
and CI use. Isolate temp roots, SQLite/database paths, ports, mutable caches,
logs, artifacts, optional-provider state, clocks and time zones. Optional
dependency discovery must not silently change contracts.

Profile pytest parallelism in report-only/shadow mode first. If xdist is
already available or authorised, start capped at four, group expensive/shared
fixtures, mark unsafe serial groups, compare collected IDs/results with the
serial baseline and require repeated Linux/Windows parity. Affected-test
selection remains report-only until false-negative monitoring proves safety
and never replaces H/C gates.

## Required workflow architecture

### One product issue, normally one product PR

Include independently verifiable dependency evidence, product/migration/UI
changes, focused and affected tests, compact canonical evidence and the final
intended lifecycle outcome when required checks can prove it. Do not create a
manual full-gate PR solely for `in_progress`; represent operational work by
branch, PR, issue metadata or append-only non-release event.

After an exact-head green product merge, automatically create final canonical
integration evidence. If a repository commit is mandatory, create at most one
automatic E-tier evidence PR containing no product change, reusing exact-tree
evidence, running compact validation, auto-merging after guards and skipping
unchanged platform packages.

### Atomic dependency evidence

Batch independent integrated dependency edges when each is evidenced against
the same immutable base and no edge depends on another new edge. Keep
sequential transactions only for real contract dependencies. Prove at least
two independent integrated dependencies in one fixture.

### Canonical events and projections

Adopt compact append-only events for dependency decisions, lifecycle
transitions, acceptance evidence, reviewed product-tree identities, CI
artifact identities and GitHub checksums. Do not rewrite tens of thousands of
lines for one field.

Views, completion docs, indexes and reports must be reproducible, emitted as
CI artifacts where practical, committed only when useful, updated atomically
and excluded from behavioural risk classification when generator/schema/event
format are unchanged. Preserve deterministic byte verification.

### No stale-by-construction generation base

Replace a blocking committed `generation_base` with runtime-derived base,
exact-run artifact metadata, non-blocking information or automatic
post-merge evidence. Consecutive successful merges must not require manual
convergence or make unrelated PRs fail.

### Real E tier

E is allowed only when product/source, lockfiles, workflows, classifier,
generator, guards, schema and protected policy are unchanged; paths are
allowlisted events/projections; exact product-tree evidence and artifact and
policy hashes match; and execution/broker authority are unchanged.

E runs exact status/dependency guard, event validation, deterministic
generation, registry/status consistency, source/supply policy, diff hygiene,
exact evidence-reference validation and terminal summary. It skips the
Linux/Windows package matrix.

Classifier, workflow, guard, generator implementation, schema or protected
policy changes remain H.

### Preserve H and C

Require complete Linux and Windows packages for persistence/migrations,
concurrency, canonical finance, point-in-time/revision semantics,
security/credentials, supply chain, execution, broker authority,
release/package tooling, CI, programme-control implementation/schema and
final certification. Never reuse evidence when relevant source,
dependencies, protected policy, environment or validation changed.

### Authoritative terminal summary

Report exact base/head, tier/reason, required/skipped jobs, platform JUnit
counts when required, artifact presence/hashes, environment fingerprints,
source/dependency hashes, product-tree identity, guards, freshness, evidence
reuse and auto-merge authority. Report review/comment/thread state where
permissions permit. A consistent green summary avoids routine manual artifact
downloads except failure, inconsistency, final certification or sampled audit.

### Stop synchronous polling

Enable repository auto-merge when available. After exact reviewed head push,
enable it, use at most one watcher, avoid repeated sleeps/check loops, work a
safe disjoint lane while CI runs and report only terminal results or concrete
fingerprints. Key concurrency by workflow plus PR/ref and cancel obsolete
heads. Do not configure an ineligible merge queue.

### Agents by task shape

The Sol-high main agent owns issue/risk/architecture decisions, shared state,
final review, push, PR, merge and external synchronisation. Exactly one
Sol-low worker writes a bounded substantive task in an isolated worktree,
runs focused tests and may checkpoint locally, but cannot push, merge, mutate
programme state, write externally or spawn writers. Small low-risk direct
corrections are limited to tightly coupled files and about 50 lines with no
financial, persistence, security or execution semantics. Read-only agents may
support independent exploration, logs, impact, security and test-gap review.

### Safe caches

Measure hit rates. Key by OS, Python, lockfile and build-tool version. Never
cache secrets, credentials, provider tokens, mutable programme authority or
broker authority.

## Acceptance fixtures

1. Evidence fixture: one compact status/evidence event selects E, skips
   packages, passes terminal summary and reuses exact product evidence.
2. Multi-edge fixture: at least two independent integrated edges in one PR,
   no product/execution change.
3. Ordinary product fixture: focused/affected/UI/architecture/static/source
   checks, with central full gate only by cadence.
4. High-risk fixture: persistence or canonical-finance change selects H and
   requires both platforms.
5. Consecutive-merge fixture: two sequential merges with no stale base and no
   manual convergence PR.
6. Status-completion fixture: one product PR automatically reaches integrated
   evidence without the manual lifecycle PR chain.

## Measured completion criteria

Record before/after across at least ten representative transactions where
possible. Targets: one–two normal issue PRs; evidence p50 ≤3m and p95 ≤6m;
queue time separate; obsolete time near zero; no environment mismatch; no
freshness failure caused only by an earlier merge; no routine artifact
download for ordinary green runs; non-product PR share below 30%; unchanged
test strength; zero accepted baseline failures; `execution_allowed=false`.
Do not claim success from one run.

## Stop conditions

After two attempts with the same root cause and no materially new evidence,
preserve the clean checkpoint, record the node/fingerprint and attempts,
identify the missing authority/decision and stop that approach. A newly
evidenced independent cause gets one bounded prerequisite repair.

Never weaken guards/assertions, skip genuine H, force-push, use broad conflict
strategies, alter unrelated branches, fabricate evidence or claim speed
without measurement.

## Handoff and completion

At every safe stop, commit intended changes, push only when authorised/ready,
leave a clean worktree or enumerate files, update this checkpoint and report
goal, worktree, branch, base/head/upstream, PR/CI, completed work, protected
boundaries, blocker, next actions and whether the overarching goal is complete.

Final output must contain merged PRs/SHAs, old/new workflow diagram, fixtures,
measured PR/wall/runner/polling reductions, retained invariants, remaining
risks and the exact next dependency-valid product issue.

The overarching goal is complete only when the representative fast path is
proven, durable instructions/checkpoint and measured evidence are tracked, and
normal feature continuation has resumed under the new workflow. Merging
ISSUE-0179 or ISSUE-0180 alone is not completion.
