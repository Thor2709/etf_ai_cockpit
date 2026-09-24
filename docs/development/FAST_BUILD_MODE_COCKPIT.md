# FAST BUILD MODE COCKPIT

**Active development mode for ETF AI Cockpit.** This mode adapts the
PCVR_BASE/Alberta Lake FAST BUILD MODE to a local-first financial application.
It prioritises completed, user-visible issue outcomes over auxiliary-tool
perfection while preserving the canonical programme, exact-head evidence and
all financial, persistence, security and execution-authority gates.

This page is an execution discipline, not a second control plane. `AGENTS.md`
and `docs/development/CONTROL_PLANE.md` remain authoritative. If a faster route
would weaken either contract, it is not FAST BUILD MODE COCKPIT.

## 1. Priority

Complete dependency-ready product outcomes first; improve supporting machinery
only when it is necessary for correctness, safety or repeatable delivery.

Prefer a coherent end-to-end issue slice that a user can exercise over isolated
infrastructure polish. Existing reviewed infrastructure is adequate by default.
Do not expand programme-control or GitHub-authority machinery without the
explicit approval and demonstrated safety need required by repository policy.

## 2. Start gate

For a fresh root, perform the minimum safe admission once:

1. Read `AGENTS.md`, `docs/development/CONTROL_PLANE.md` and this page.
2. Fetch and verify `origin/main`; leave unrelated dirty checkouts untouched.
3. Use a fresh isolated exact-main worktree.
4. Run `python scripts/programme_execution.py --check` and inspect the derived
   NOW issue with `python scripts/programme_execution.py --issue <ISSUE-ID>`.
5. Reconcile active writers, dependencies, the latest handoff and reusable
   evidence before opening a write lane.
6. Record the issue, blocker and next action in the canonical active plan only
   when that plan requires an update.

Do not remap the full repository or reread the whole backlog when the derived
issue card and directly relevant source/tests are sufficient.

## 3. Work order

Use this order unless the issue's risk or acceptance contract requires more:

1. Canonical issue card, dependencies and preserved implementation locators.
2. Direct source and focused tests.
3. Repository scripts and deterministic command-line checks.
4. The narrowest configured V2 role required by the task shape.
5. Browser verification only for acceptance that requires rendered or keyboard
   behaviour.
6. Auxiliary integrations only when they materially unblock the issue.

Use one production-code writer for an overlapping boundary. A second writer is
allowed only in a separate worktree with proven disjoint ownership. Root keeps
Git, GitHub, canonical programme state, integration and release authority.

## 4. Coherent issue batches

Batch related implementation through the canonical domain boundary rather than
making repeated one-line handoffs. An ordinary feature batch should include:

- the smallest complete product path;
- ordinary focused tests owned by the implementer;
- explicit unavailable, stale, conflicted and unsupported states;
- necessary UI wiring without duplicating financial logic;
- one stable whole diff for formal review.

Do not batch unrelated issues, overlapping writers or incompatible lifecycle
transactions. Product integration and lifecycle completion remain separate.
Canonical mutations and merges stay serial even when independent read-only work
or disjoint implementation preparation runs concurrently.

## 5. Validation cadence

Run the smallest check that can inform the next decision, then validate at
meaningful milestones:

1. Contract/source/test feasibility.
2. Focused implementation tests.
3. Stable whole-diff reviewer gate.
4. Selective risk review for consequential boundaries.
5. Required integration, UI, lint, type and compile checks.
6. Exact-head CI and release verification when the delivery contract requires
   them.
7. Post-merge lifecycle/status readback before claiming completion.

Do not rerun an unchanged passing check merely because time passed or a status
event occurred. Reuse evidence only when source, tests, dependencies, policy,
environment and artifact identity are unchanged and verifiable.

The existing E/O/H/C classifier remains authoritative. Persistence, migrations,
concurrency, canonical financial calculations, security, release tooling,
programme-control machinery and broker authority still require the complete
Linux and Windows packaged gate. Ordinary work still receives the central full
gate on every second completed O-tier issue and at final certification.

## 6. Auxiliary failures and fallback

For a non-essential tool, integration or convenience feature, make at most two
recovery attempts with materially improved evidence. Then record the failure
briefly, use an adequate safe fallback and continue product work.

Fallback is forbidden when it would obscure missing data, bypass a required
named role, weaken exact-head provenance, alter canonical calculations, reduce
test coverage, or broaden execution/external-write authority. A required review,
release gate or financial safety check is never auxiliary.

## 7. Checkpoints

Keep meaningful, reviewable checkpoints:

- one exact-main base before implementation;
- one stable implementation head before formal review;
- one frozen exact head while mandatory evidence runs;
- one post-merge readback before lifecycle completion;
- one clean checkpoint before any genuinely risky or destructive operation.

Do not checkpoint trivial edits. Rebase, transplant or cherry-pick reviewed work
instead of recreating it. Never edit a frozen head while its required evidence is
running.

## 8. Logging and reporting

Report only material state changes: verified start, concrete finding, completed
implementation, failed check, review result, terminal CI, merge or blocker.
Update handoffs and canonical status when meaningful state changes, not on a
timer and not to repeat unchanged facts.

Label outcomes precisely:

- **IMPLEMENTED** — code exists at the stated exact head.
- **TESTED** — named evidence passed for that exact identity.
- **PRODUCT MERGED** — the exact product head is on main.
- **LIFECYCLE COMPLETE** — the guarded canonical transition and required
  zero-action readback succeeded.
- **PLANNED ONLY** — no implementation claim.
- **BLOCKED** — a concrete required dependency, decision, authority or gate is
  unavailable.

Do not collapse these states into “done.”

## 9. Safety invariants

Throughput never outranks these invariants:

- `execution_allowed=false` remains enforced.
- No live orders, broker writes, cloud uploads or silent external network
  activity are introduced.
- Risk and data-quality gates override forecasts, models, audits and UI actions.
- Returns use adjusted, corporate-action-aware data.
- Point-in-time, revision and replay semantics are preserved.
- Look-ahead and survivorship leakage remain prohibited.
- Missing or unsupported values remain explicit; they are never invented or
  silently zero-filled.
- UI code does not become an alternate financial-calculation authority.
- Optional models remain disabled-safe with deterministic baseline behaviour.

## 10. Issue loop

For each NOW issue:

1. Confirm dependency readiness and acceptance evidence.
2. Reuse valid prior work by exact identity; do not infer completeness from a
   locator or green status alone.
3. Implement the smallest complete issue slice in an isolated lane.
4. Run focused checks and freeze the stable diff.
5. Obtain required configured-agent reviews and runtime attestations.
6. Run only the broader gates selected by risk and delivery policy.
7. Integrate with expected-head protection.
8. Complete the single legal lifecycle transaction and verify external readback.
9. Re-run the programme selector and advance to the newly proven NOW issue.

Stop after two failed attempts with the same root cause and no materially better
evidence. Preserve the checkpoint and identify the missing decision or authority;
do not drift into unrelated edits.

## 11. Throughput measure

Measure FAST BUILD MODE COCKPIT by accepted product progress:

- dependency-ready issues delivered end to end;
- user-visible paths exercised where acceptance requires them;
- valid evidence reused instead of repeated;
- fewer handoffs and repeated reads;
- no regression in financial correctness, provenance or authority boundaries.

The target is not maximum change volume. It is the fastest defensible path from
canonical NOW issue to verified product and lifecycle completion.
