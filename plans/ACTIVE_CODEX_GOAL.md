# Active Codex goal — ISSUE-0101 cyclical-sector adapters

## Objective

Continue the dependency-ready ISSUE-0101 product slice with one bounded local
typed adapter family for energy, materials/mining and non-infrastructure
industrial evidence, deterministic scenarios and read-only Instrument Detail
rationale. Preserve every financial, point-in-time, safety, audit and
cross-platform invariant.

The ISSUE-0177–0180 control-plane work is complete and frozen. Its complete
former active-goal record and chronology are archived in
`plans/archive/ATOMIC_FAST_PATH_ISSUE-0179-0180_2026-07-31.md`. Current delivery
mechanics are defined in `docs/product-completion/DELIVERY_WORKFLOW.md`.

## Current checkpoint

- Current UTC timestamp: `2026-07-31T21:08:12Z`.
- Active product worktree:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0101`;
  branch `codex/issue0101-cyclical-adapters-20260731`; exact base
  `8a0d1d9a7437770aa0567d9ae6787e3881832f27`.
- Exact durable handoff content commit:
  `a7525e302add1685a4d457be79478a35e8045d24`. The current local branch
  head is a descendant identity note at
  `64b5c5947e6a6b79bdd19146ef899ccb368956e1`; verify it before continuing.
- Current issue: dependency-ready ISSUE-0101, programme status `in_progress`.
- Bounded outcome: one local typed adapter family for energy,
  materials/mining and non-infrastructure industrial evidence, deterministic
  scenarios and read-only Instrument Detail rationale.
- Product checkpoint: the bounded implementation and one focused correction
  are intentionally uncommitted. Forty-six adapter/architecture tests and 94
  broader Instrument Detail/application tests pass, with Ruff, compile,
  boundary and diff checks green.
- Independent review is not clean: self-rehashed projections can still forge
  source/cycle/formula/routing semantics, and three related
  limitation/replay inconsistencies remain.
- Blocker: the same semantic-replay validator approach remains incomplete
  after the implementation and its one permitted focused correction. Do not
  commit, push or open a PR from this product diff.
- Exact next action: preserve this explicitly uncommitted checkpoint and
  redesign the cyclical projection verifier so it validates one canonical
  source-bearing payload rather than attempting a second partial semantic
  reconstruction. Start that as a fresh bounded implementation only after
  reviewing this failure fingerprint; do not broaden into persistence,
  providers or shared routing.
- Product stop condition: stop if industrial versus infrastructure routing
  requires a shared classification/registry redesign, persisted contracts,
  external data authority or any broader sector or ISSUE-0115 scope.
- Required checks for the continuation: focused adapter, application,
  selector, page and architecture tests first, then the validation tier and
  broader gates required by the finished diff.

The intentionally uncommitted files are:

- `configs/ui_acceptance.yaml`
- `src/etf_cockpit/app/pages/instrument_detail.py`
- `src/etf_cockpit/app/selectors/instrument_detail.py`
- `src/etf_cockpit/app/state.py`
- `src/etf_cockpit/application/ui_facade.py`
- `src/etf_cockpit/analysis/cyclical_sector_adapters.py`
- `tests/test_cyclical_sector_adapters.py`

## Frozen delivery evidence and boundaries

- Final fast-path evidence PR #631 merged exact reviewed head
  `11da5e4a880a4e06526147bd30527c24d186804d` as
  `8a0d1d9a7437770aa0567d9ae6787e3881832f27`.
- H-tier run `30659377591` passed classifier, preflight, supply-chain,
  Linux and Windows package gates, both repeated parallel pilots,
  cross-platform aggregation and terminal validation.
- Post-merge convergence `30663879745` passed from exact main with zero
  create, update, close, reopen or blocked actions.
- Frozen compact-control evidence: execution p50/p95
  `0.4000/1.2500 min`; queue p50/p95 `0.0500/1.8833 min`; correct E
  package skipping `5/5`; cache reuse `10/46` (`21.74%`). No polling
  reduction is claimed.
- GitHub authority repair is complete and frozen to repository-authored issue
  creation and lifecycle/status projections already used by the programme.
  It is not a general GitHub database or event-sourcing framework.
- Git remains canonical. Broker/provider/release/deployment authority is
  unchanged and `execution_allowed=false`.
- Do not add speculative GitHub support, compensation or retry of ambiguous,
  cancelled, partially applied or erased writes without explicit user
  approval and a demonstrated safety need.

## Current orchestration

- The Sol-medium root owns requirements, shared state, Git, GitHub,
  integration and release decisions.
- Normally use one named child; maximum two children excluding the root;
  delegation depth one.
- A second child is limited to independent read-only work or a proven disjoint
  worktree. Normally one workspace-writing child is active.
- Product work may overlap immutable CI only through a disjoint worktree and
  must not touch the frozen PR head, canonical/generated control files or
  external state.
- Current named-agent routing supersedes historical Sol/Terra/Luna routing.
- Normally deliver one product issue per product PR. Independent dependency
  evidence may be batched when safe; lifecycle convergence is compact and
  automatic.
- The four-worker safe/unsafe pytest pilot remains report-only. Serial Linux
  and Windows packaged validation remains authoritative.

## Durable memory and compaction survival

Before product, CI or programme-control changes, read:

1. global and project `AGENTS.md`;
2. `docs/product-completion/DELIVERY_WORKFLOW.md`;
3. this active goal and `plans/BATCH-B04-ANALYSIS-SPINE.md`;
4. `PLAN_step2.md`, the relevant issue records, source and tests.

After compaction, a worktree/thread switch, merge, base change or uncertain
handoff, re-read those files and verify `origin/main`, branch, base/head,
upstream, dirty files, blocker and next action. Update this checkpoint before
handoff.

## Completion and stop conditions

Do not abandon reviewed checkpoints, alter PR #560, merge stale PR #562,
close issue #241, publish a release, create a tag, deploy, enable execution or
add broker writes.

After two attempts with the same root cause and no materially improved
evidence, preserve the checkpoint, record the failure fingerprint and
attempts, identify the missing decision or authority, and stop that approach.
A newly evidenced independent cause may receive one bounded repair.

A safe handoff reports goal, worktree, branch, base/head/upstream, dirty files,
issue and status, completed work, tests, protected boundaries, blocker, exact
next action and whether the requested outcome is actually complete.
