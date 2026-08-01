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
succeed. Skipped pilot jobs are excluded from branch-protection authority.

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
