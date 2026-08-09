# Current delivery workflow

This is the detailed current project delivery contract. It is protected
policy: changes invalidate reusable evidence and are at least H-tier.

## Precedence

1. Product scope and acceptance criteria come from the immutable final-release
   specification and the current canonical registry.
2. Current issue identity, dependency and status come from
   `issues/issue_registry.json` and `issues/programme_control_state.json`.
3. Current delivery mechanics come from the global/project `AGENTS.md`, the
   effective `config.toml`, this contract, `PLAN_step2.md` and the active goal.
4. The active task is defined by `plans/ACTIVE_CODEX_GOAL.md` and the current
   batch plan.
5. Historical plans and immutable source mechanics are evidence only when they
   conflict with newer operational instructions.

Historical instructions prescribing a Sol-high root, Terra workers, Sol-low or
`sol_worker`, six children, two-to-four writers, two-to-eight issue PRs,
Luna-only repetitive work or manual lifecycle convergence are superseded.

## Delivery shape

Read the active goal and this workflow before changing code. Verify the exact
current `origin/main`, dependency readiness, worktree and ownership. Normally
deliver one bounded product issue in one product PR. Batch independent
dependency edges only when their contracts are genuinely inseparable and the
root records the reason. Product work may overlap an immutable CI lane only in
a proven disjoint worktree. There is normally one workspace-writing child; a
second child is limited to independent read-only work or a proven disjoint
worktree. Delegation depth is one and the maximum is two children.

Review a stable exact-head diff. Merge only the reviewed head after required
gates. Update the canonical control source first; never hand-edit generated
status or programme projections. Run the atomic generator, then run it again
in check mode and require a byte-clean result. Compact programme/status
convergence is automatic; there is no manual `in_progress` /
`implemented_initially` / `integrated` PR chain and no duplicate post-merge
release package matrix. Use at most one watcher and no repetitive polling.

A bounded convergence defect receives at most one demonstrated repair cycle in
its owning lane. The exact reviewed head, live-plan checksum, focused guards
and reusable-evidence identities remain mandatory. Existing schema-v2 status
authority may append exactly one status-only legal forward hop whose target is
`ready`, `in_progress` or `integrated`, bound to the same issue/remote
identity, exact parent/head, candidate, plan, ledger and workflow attestation.
The unchanged completion authority remains exactly two hops,
`in_progress -> implemented_initially -> integrated`. No retry, compensation,
ambiguous-write recovery or broader mutation authority is permitted.
The exact audited B00 source for ISSUE-0011, which began canonically
`in_progress` before transition history existed, may use an empty replay
prefix only when its complete fixed source record validates. The appended path
remains the same exact two hops; every other issue, unknown source field,
malformed value or inconsistent prefix fails closed.
The exact active-goal and current `plans/BATCH-B04-ANALYSIS-SPINE.md`
checkpoint chronology files are evidence-only and do not inflate an otherwise
E control transaction; invented or other plan paths fail upward. Genuine H
changes still run the complete serial Linux/Windows packaged gates.
Where the contract permits, product lifecycle completion is atomic/automatic
rather than a serial chain of administrative PRs.
Generic live convergence executes the synchroniser as a module from the
mechanically staged repository root, so its imports and generated inputs are
the reviewed staged tree. Acceptance still requires a zero-action readback.

## Stable-head throughput

Before freezing a product head, complete required documentation, checkpoint,
canonical transition, transition manifest, candidate, append-only authority
record and mechanically generated projections. Validate the exact live dry-run
plan plus the expected post-merge ordered writer and zero-action readback. Do
not open or merge a product/readiness PR with known missing lifecycle
authority, and do not combine dependency-edge and lifecycle changes when the
guard prohibits that shape.

Once the head is locally green and clean, launch whole-diff review, risk review
and required exact-head hosted CI concurrently. Read-only preparation for the
next canonical dependency-ready issue and implementation in a proven disjoint
worktree may also proceed while immutable CI runs. Shared files and canonical
programme state retain one writer. A review rejection invalidates or cancels
the stale head's CI evidence.

All required reviewers evaluate the same exact head and all verdicts are
collected before correction. Valid findings are handled in one consolidated,
bounded pass, followed by the smallest affected focused suite and one
replacement exact-head review cycle. Another correction cycle requires a
newly demonstrated defect that could not reasonably have been included in the
consolidated pass.

Do not rerun unchanged passing evidence because time elapsed or a read-only
review completed. Broader local evidence is required only when the changed
surface, a concrete reviewer risk, the classifier or this contract requires
it; H-tier and other protected gates are never weakened. Frozen heads are not
changed for cosmetic wording or chronology. Use one watcher per CI run and
report only concrete failures/findings, exact heads, approvals, terminal
gates, merges, writer/readback outcomes and next-issue selection.

A convergence repair requires a fresh deterministic failure against current
exact main. It reproduces that failure in one regression, makes the smallest
repo-local correction without adjacent generalisation, completes once and
returns immediately to product delivery. ISSUE-0177–0180 optimisation remains
closed.

## Bounded repo-local autonomy and lifecycle recovery

The standing owner authorization covers bounded repo-local product, test,
canonical, generator, CI/check and narrow authority work without a permission
question. It does not authorize protected external actions such as GitHub
writes outside the existing gateway, permission changes, releases,
deployments, broker/provider writes or execution. H-tier changes still require
the full review and validation tier before acceptance.

When a reviewed canonical lifecycle change omitted its GitHub projection, the
existing sole writer may recover only one omitted managed status hop from the
exact reviewed head and live target snapshot. The accepted comment projection
is authoritative even when the legacy body status still carries its anchor.
Recovery remains fail-closed and append-only; it must not invent history,
retry an ambiguous write, compensate, or rewrite canonical state.

The bounded `status-replay-candidate/3.0` contract supports one issue and
exactly two ordered forward hops: `in_progress` to
`implemented_initially`, then `implemented_initially` to `integrated`. Each
hop is independently checked by the canonical lifecycle validator. One
aggregate proposal and one receipt bind both hops to the same issue, reviewed
product commit, candidate/authority, canonical transition-history and
acceptance-evidence prefixes, and exactly two appended entries. The aggregate
is semantically atomic in the local replay and readback model, while GitHub
still transports two ordinary append requests without server-side CAS. A
partial, erased, cancelled or ambiguous request remains unresolved and is
never retried or compensated. This is a bounded status-completion repair, not
a general replay or event-sourcing framework.

## Validation tiers

The additive `validation-classifier.v1` selects one tier from E/O/H/C and fails
upward when history, classification or cadence is unknown.

- E: allowlisted evidence/status/dependency/generated projections only. Run
  exact guards, atomic generation/check mode, registry/status, diff hygiene
  and source/supply policy. Package gates may be skipped only with exact-tree
  evidence reuse.
- O: ordinary product work. Run focused and affected tests, UI/architecture
  and static checks, source smoke and the central cadence policy.
- H: CI, generator, classifier, policy, persistence, concurrency, canonical
  finance, point-in-time, security, release, programme-control or authority
  changes. Run the complete serial Linux and Windows packaged gates immediately.
- C: final certification. Run the complete cross-platform certification and
  all package, parity, performance, security, privacy, legal, SBOM and
  signature evidence.

Unknown or malformed base/head, shallow or stale history, missing classifier
inputs, malformed cadence, classifier errors and failed preflight require the
full gate. `main` remains green. The terminal `validation-summary` is the
normal CI interface; inspect raw artefacts only for failure, inconsistency,
sampled audit or final certification.

## Evidence reuse and cadence

Reuse is authorised only when base/head, source, dependency, product-tree,
policy, environment, artifact-manifest and `execution_allowed=false`
identities match exactly. The O cadence is derived from the exact PR base
first-parent `origin/main` history using the current classifier. E commits are
ignored; O commits are counted from the nearest H/C reset; the second O is due
for a full gate. Unknown cadence is never treated as zero. No GitHub variable
is a cadence authority.

## Parallel pilot policy

The four-worker pytest pilot and cross-platform aggregate are report-only,
`continue-on-error`, evidence-producing jobs outside terminal release
authority. The serial packaged gates remain authoritative. The classifier
emits `parallel_pilot_required`, `parallel_pilot_repetitions` and
`parallel_pilot_reason`.

The pilot is selected only for pilot mechanics or ISSUE-0180 pilot tests,
pytest/conftest/collection or grouping changes, release/test dependency or
Python-environment changes, concurrency/persistence/Windows-sharing/
atomic-write/isolation changes, tier C, or an explicit manual/scheduled drift
sample. It uses one repetition for an ordinary explicit drift sample and two
for mechanics, environment/partition, tier C or explicit full sampling.
Unrelated documentation, plans, roles and product H changes skip it. A pilot
starts only after classifier, preflight and the single source supply-chain job
succeed. Scheduled samples and explicit `repository_dispatch` samples execute
the default-branch workflow and never receive release-signing material;
arbitrary-ref `workflow_dispatch` is intentionally unavailable. Skipped pilot
jobs do not create a pending check. The repository currently has no GitHub
branch-protection rule or ruleset, so `validation-summary` is authoritative by
reviewed process policy and workflow contract, not server-enforced protection.

## Preflight and implementation safeguards

Preflight runs before expensive validation and includes UI acceptance metadata
for new routes/buttons, the application-facade boundary for presentation
imports, environment verification, temporary-root and port isolation, and
CRLF/LF and generated-freshness checks. Use isolated temporary roots, ports,
caches, databases and logs. Do not weaken assertions, thresholds, financial,
point-in-time, security, cross-platform or authority safeguards.

Architecture or contract changes require reading and updating the relevant
SDD/ADR in the same PR. Keep the application local-first,
`execution_allowed=false`, optional models disabled-safe, and broker/provider,
release, deployment and external-write authority unchanged.
