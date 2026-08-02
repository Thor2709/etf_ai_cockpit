# Active Codex goal — H-tier replay control-state binding repair

## Objective

Correct the bounded aggregate replay to read lifecycle history and acceptance
evidence from the existing authoritative `programme_control_state.json`, not
the generated registry projection that intentionally omits transition history.
Preserve the exact two-hop contract, legacy authority bytes,
`execution_allowed=false`, and all fail-closed safeguards.

The ISSUE-0177–0180 control-plane work is complete and frozen. Its complete
former active-goal record and chronology are archived in
`plans/archive/ATOMIC_FAST_PATH_ISSUE-0179-0180_2026-07-31.md`. Current delivery
mechanics are defined in `docs/product-completion/DELIVERY_WORKFLOW.md`.

## Current checkpoint

- Current UTC date: `2026-08-02`.
- Initial H-tier repair PR #634 merged exact reviewed head
  `676aaaeedadcf04c3a4644f4d10902a2c05bd311` as
  `ff10762e8c000b2f2c834073e27a664bc20de143`; run `30724545238` passed fresh
  Linux and Windows package gates and terminal summary.
- The first clean E recovery attempt failed closed before artifact creation:
  replay preparation found that generated `issue_registry.json` omits the
  authoritative transition history held in `programme_control_state.json`.
- Preserved E attempt:
  `C:\Users\thor2\AppData\Local\Temp\issue0101-e-recovery-blocked-20260802`;
  patch SHA-256
  `2A2C65B7B5864D2A95ED641C46D0874667DFE50B20A551082C03B76DF531A4E2`.
- Follow-up repair worktree:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_replay_control_state`;
  branch `codex/status-replay-control-state-20260802`; exact base and starting
  head `ff10762e8c000b2f2c834073e27a664bc20de143`.
- Current lane: bounded implementation and focused tests are complete;
  independent review and fresh H-tier package gates remain pending.
- Protected scope: canonical ISSUE-0101 status, generated projections,
  workflows/permissions, product code, external systems and authority policy
  remain unchanged.
- Preserved rejected evidence path/hash:
  `C:\Users\thor2\AppData\Local\Temp\issue0101-invalid-recovery-evidence-20260802-001`;
  patch SHA-256
  `32488742f363e50f14c566b6890992e37a1a9843d0ed9ca7031fc32fc56e168c`.
- Exact next action: review and validate the complete control-state binding
  diff, merge only the accepted exact H-tier head, then restart ISSUE-0101
  recovery from a new clean `origin/main` worktree.

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
