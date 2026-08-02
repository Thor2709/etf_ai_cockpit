# Active Codex goal — complete the canonical programme through Phase 11

## Objective

Complete the canonical implementation programme issue by issue through
integration, GitHub convergence and Phase 11 certification. Select work only
from canonical readiness and implementation order, preserve
`execution_allowed=false`, and retain all financial, point-in-time, security,
privacy and audit safeguards.

The ISSUE-0177–0180 control-plane work is complete and frozen. Its complete
former active-goal record and chronology are archived in
`plans/archive/ATOMIC_FAST_PATH_ISSUE-0179-0180_2026-07-31.md`. Current delivery
mechanics are defined in `docs/product-completion/DELIVERY_WORKFLOW.md`.

## Current convergence repair checkpoint

- PR #639 merged as `26a3b5e7902b1c77df00d15f8e4ece472828f744`. Its
  read-only Programme convergence run `30739727616` failed closed with exactly
  one status-only update for the live plan at checksum
  `4754b3f8b395c3c3d6595a4756a6c9c4a2b20bd2303516745212227f94a823cc`.
- The bounded repair lane is
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_pending_status_convergence`
  on branch `codex/pending-status-convergence-20260802`, based on exact SHA
  `26a3b5e7902b1c77df00d15f8e4ece472828f744`. It remains an uncommitted local
  repair lane; no new PR or merge is claimed here.
- Scope is the single bounded authority repair: generalize the existing
  schema-v2 status candidate and sole writer to one legal status-only hop to
  `ready`, `in_progress` or `integrated`, while preserving the exact two-hop
  `in_progress -> implemented_initially -> integrated` completion path. The
  accepted comment projection is authoritative when the legacy body lags;
  canonical ISSUE-0102 remains unchanged and `execution_allowed=false` is
  preserved.
- The abandoned read-only deferral attempt failed closed because live GitHub
  #242 required an automatic pending projection. Its workflow, deferral script
  and deferral-only tests were restored to base. The refreshed live plan still
  contains exactly one status-only ISSUE-0102 update at checksum
  `4754b3f8b395c3c3d6595a4756a6c9c4a2b20bd2303516745212227f94a823cc`.
  Repository-only preparation produced status authority
  `1e9de93977b28d6fc60f9992c6bad5f0fe4fc3f1a50a777376e6300810509ab1`
  and candidate SHA-256
  `25f4a2477a68702a584aae59e2a21be4cc9527aa6bc1642b163757f7c3bb9f21`
  for `planned -> ready`, with `execution_allowed=false`.
- Current local evidence: 286 focused authority/classifier/summary tests passed;
  the root rerun of the four directly coupled suites passed 225 tests; Mypy,
  targeted Ruff, compile, workflow YAML parsing, diff hygiene, atomic
  generation and the second byte-clean generator check passed. H-tier CI and
  independent reviewer/risk-reviewer approval remain pending; no PR or merge
  is claimed.

## Current checkpoint

- ISSUE-0102 dependency PR #638 merged exact reviewed head
  `871ea037c594844a0de9e72e7dbabd3405244b76` as
  `179e16c71328c43a9475dce60743a2d1aeda5aa7`. Run `30737461361` passed
  classifier, preflight, supply chain, authoritative Linux/Windows package
  gates and terminal validation; guard `30737461338` passed. Post-merge
  convergence `30738361187` was zero action at checksum
  `da979ae3fef7344ff4e492bd4468f8a3653e329f6121cb13ba9f2e2a003c1b8f`.
- Clean readiness lane:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0102_ready`;
  branch `codex/issue0102-ready-20260802`; exact base and starting head
  `179e16c71328c43a9475dce60743a2d1aeda5aa7`, initially empty.
- Current scope advances only ISSUE-0102 `planned -> ready`, binds acceptance
  evidence to PR #638 and its exact validation, and preserves all product code,
  dependency edges, external authority and `execution_allowed=false`.
- Exact next action: complete the authority repair, run canonical generation
  followed by byte-clean check mode and the required focused/H evidence, then
  obtain independent reviewer and risk-reviewer approval before any later
  integration or automatic convergence. Do not change canonical ISSUE-0102 in
  this lane.

### Prior dependency-edge checkpoint (superseded)

- Current UTC date: `2026-08-02`.
- ISSUE-0101 recovery PR #636 merged as
  `07da10ee0403033da30071eab5cfb5205c0af147`; bounded recognition repair PR
  #637 merged exact reviewed head
  `0ca952b170420ceb6d85dbfedffa7f106a66d5d8` as
  `2e3d69541dccc5f71e868e4c55e85bef623cfbd3` after H-tier run
  `30736184903` passed. Automatic convergence run `30737053331` produced zero
  actions at checksum
  `da979ae3fef7344ff4e492bd4468f8a3653e329f6121cb13ba9f2e2a003c1b8f`;
  GitHub #241 projects canonical `integrated` and `execution_allowed=false`.
- ISSUE-0102 is the next implementation-order record. Its sole ISSUE-0098
  dependency is integrated, but the edge requires evidence review before the
  issue is ready.
- Clean evidence-only lane:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0102_edge`;
  branch `codex/issue0102-dependency-0098-20260802`; exact base and starting
  head `2e3d69541dccc5f71e868e4c55e85bef623cfbd3`, initially empty.
- Current scope records only ISSUE-0102→ISSUE-0098 as `complete` against merged
  `peer-cohort.v1` commit `fc734201b138d3f24fa68d8c07422322506d6fc5`.
  ISSUE-0102 remains `planned`; product code, dependency lists, GitHub state,
  external authority and execution policy are unchanged. The programme
  projection is generated and byte-clean in check mode.
- Exact next action: run E-tier guards, independently review and merge the
  exact dependency head, verify zero-action convergence, then advance
  ISSUE-0102 through readiness and bounded product implementation.

## Prior ISSUE-0101 recovery checkpoint (superseded)

- Current UTC date: `2026-08-02`.
- ISSUE-0101 recovery PR #636 merged exact reviewed head
  `10db96f6a3e877196352f28c11428b7ac9d4859b` as
  `07da10ee0403033da30071eab5cfb5205c0af147`. Run `30733297748` passed the
  authoritative H-tier classifier, preflight, supply-chain, Linux/Windows
  package gates and terminal summary at 2,581 tests per platform; guard run
  `30733297750` passed. The Windows four-worker pilot recorded one report-only
  ESEF parser divergence while the authoritative serial gate passed.
- Automatic writer run `30735911761` appended the one aggregate replay proposal
  and receipt to GitHub #241 with `execution_allowed=false`, then failed its
  immediate zero-action readback. Settled authority reconciliation projects
  `integrated`; generic sync blocks only because create-acceptance scanning does
  not yet recognise the two replay markers as known managed comments.
- Clean bounded H repair lane:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0101_postmerge`;
  branch `codex/status-replay-comment-recognition-20260802`; exact base and
  starting head `07da10ee0403033da30071eab5cfb5205c0af147`, initially empty.
- Current repair scope: recognise only valid replay proposal/receipt markers in
  generic managed-comment validation, retaining replay parsing, ledger
  reconciliation, fail-closed malformed-marker handling and all authorities.
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
- Follow-up H-tier repair PR #635 merged independently approved exact head
  `91aea56ec60d9dfb92968c30428c0a02a35b5652` as
  `a4aadf36cc6c0f8cbb356fff96b572919cf5857f`. Run `30728917010` passed
  classifier, preflight, supply-chain, Linux and Windows package gates and the
  terminal summary; post-merge convergence run `30729715977` passed zero action.
- Clean recovery worktree:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0101_replay_v2`;
  branch `codex/issue0101-two-hop-recovery-20260802-v2`; exact base and starting
  head `a4aadf36cc6c0f8cbb356fff96b572919cf5857f` with an initially empty diff.
- Canonical input records only ISSUE-0101
  `in_progress -> implemented_initially -> integrated`; both hops share PR #633
  recorded independent review and tier-O validation evidence and verified product commit
  `0680429aa5c30477dc854ef80367a3cc5ff4010e`.
- Current lane: mechanical projection generation/check, H-tier guards,
  exact-head review, merge and GitHub #241 convergence remain pending.
- Exact-head run `30731278862` failed closed before package validation because
  an unconditional depth-one local base fetch marked the already complete
  authority checkout shallow and hid the reviewed product commit from the
  ancestry check. The bounded CI correction preserves full history when the
  trusted base commit is already present and keeps the existing fail-closed
  fallback when it is absent.
- The next exact-head run passed authority preflight, supply chain and both
  Linux/Windows package gates, then terminal validation failed closed because
  validation-mode replay evidence omitted the already-validated replay hops
  and reviewed product commit required by `validation_summary.py`. The bounded
  evidence-projection correction adds only those two identities.
- Protected scope: ISSUE-0101 product code, dependency edges,
  workflows/permissions, external systems and all execution/authority policy
  remain unchanged.
- Preserved rejected evidence path/hash:
  `C:\Users\thor2\AppData\Local\Temp\issue0101-invalid-recovery-evidence-20260802-001`;
  patch SHA-256
  `32488742f363e50f14c566b6890992e37a1a9843d0ed9ca7031fc32fc56e168c`.
- Exact next action: generate all projections atomically, require byte-clean
  check mode, prepare the bounded aggregate proposal/receipt, validate and
  review the exact H-tier head, then merge and verify GitHub #241 reaches
  canonical `integrated` without unrelated writes.

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
