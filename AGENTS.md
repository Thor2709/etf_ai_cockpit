# ETF AI Cockpit — Codex Rules

## Goal

Complete the canonical implementation plan correctly and efficiently.

The `gpt-6-astra` low-reasoning main agent is the orchestrator and sole integration and GitHub authority. It plans, selects the narrowest configured agent roles, reviews and integrates.

Choose efficiently among the 12 configured named roles through the V2 framework. The live runtime normally permits at most two child agents concurrently for cost and latency control. Ten is only the framework/project ceiling and must not be treated as the default. Select concurrent product lanes from the dependency and exclusive-ownership map in the active batch plan; additional agents are not a reason to invent work.

Use one active code writer per overlapping file boundary. Parallelise only independent, non-overlapping work.

## Current ISSUE-0177–0180 delivery contract

Read `plans/ACTIVE_CODEX_GOAL.md` and
`docs/product-completion/DELIVERY_WORKFLOW.md` before work. The canonical
classifier selects E/O/H/C and unknown history or cadence fails upward. Exact
base/head, protected source/dependency/product/policy/environment/artifact and
`execution_allowed=false` identities must all match before evidence reuse.
Use immutable integration/CI heads and isolated implementation worktrees.
Concurrent writers require proven disjoint file and runtime ownership plus
dependency readiness; root alone serializes merges and canonical/GitHub writes.
Maximise safe, complete issue-level parallelism without a fixed issue/writer
quota; retain review capacity within the ten-child V2 resource ceiling.
Normally make one product issue per product PR; batch only inseparable,
independent dependency edges. Lifecycle/status convergence is compact and
automatic. Update canonical control first and regenerate projections; never
hand-edit generated status/programme views. Atomic generation must be followed
by a second byte-clean check. `validation-summary` is the normal CI interface;
use at most one watcher and no repetitive polling. Raw artefacts are for
failure, inconsistency, sampled audit or final certification.

Bounded convergence defects receive at most one demonstrated repair cycle in
the owning lane. The exact reviewed head, live-plan checksum and focused
fail-closed guards remain required. Existing schema-v2 status authority may
append exactly one legal status-only forward projection to `ready`,
`in_progress` or `integrated`; the unchanged completion authority remains
`in_progress -> implemented_initially -> integrated`. No retry, compensation,
ambiguous-write recovery or broader mutation authority is added. The exact
active-goal and current `plans/BATCH-B04-ANALYSIS-SPINE.md` checkpoint
chronology files are evidence-only and do not inflate an otherwise E control
transaction; invented or other plan paths fail upward. Genuine H changes still
require the complete serial Linux/Windows packaged gates.
Where the contract permits, product lifecycle work uses atomic/automatic
completion rather than serial administrative PRs.
Generic live convergence must execute the synchroniser from the mechanically
staged repository import root and must finish with a zero-action readback.

The four-worker safe/unsafe pytest pilot is report-only and serial packaged
Linux/Windows validation remains authoritative. `main` remains green. Read and
update the relevant SDD/ADR for architecture or contract changes. Preflight
must cover UI acceptance, application-facade imports, environment, temporary
roots, ports and CRLF/LF. Product work remains local-first with
`execution_allowed=false`.

## Start

Before changing code:

1. Fetch and verify the latest `origin/main`.
2. Leave unrelated dirty checkouts untouched.
3. Use a fresh isolated worktree.
4. Read this file, the active batch plan, the selected issue and only the relevant source and tests.
5. Confirm that the issue is dependency-ready.
6. Record the current issue, blocker and next action briefly in the active batch plan.

Do not reload the whole backlog or repeatedly remap the repository.

## Orchestrator

For each substantive task, the main agent must:

1. Define one clear outcome.
2. State the relevant issue and acceptance criteria.
3. Identify relevant files and tests.
4. State what must not change.
5. Select the narrowest suitable configured agent and delegate when doing so is efficient.
6. Review the worker's complete diff and tests.
7. Request at most one consolidated correction pass from the implementation agent when review identifies valid findings.
8. Integrate and run the necessary broader checks.
9. Update the batch plan, status and GitHub only after the implementation is evidenced.

The main agent should not write substantial product code. Small integration and generated-file corrections are allowed.

## Agents

Configured agents:

- are selected by role and task shape;
- own one bounded assignment;
- read only relevant context;
- make the smallest correct change when assigned write ownership;
- add and run focused tests when relevant;
- do not change unrelated files;
- do not spawn agents;
- do not push, merge or update programme status.

For a task matching a named role, that named role is mandatory. Do not substitute a generic worker or the default fallback merely because it is available. Use the default fallback only when no configured role fits, and record that exception in the hand-off. Before accepting child work, verify the child metadata reports the requested role, model and reasoning effort; otherwise fail closed and retry once with the exact role.

Only one agent may write within an overlapping production-code boundary. Review only a finished stable diff. Use `test_engineer` only when test design is independently substantial; the `implementer` owns ordinary focused tests.

## Stable-head throughput

Complete product documentation, checkpoints, lifecycle metadata and generated
files before freezing a locally green, clean head. Against that same exact
head, start whole-diff review, risk review and required hosted CI in parallel;
also permit read-only next-issue preparation and disjoint-worktree
implementation when dependency-safe. Do not overlap writers on shared files
or canonical programme state. If review rejects the head, cancel or disregard
its stale CI evidence.

Launch all required reviewers together and wait for every verdict. Consolidate
all valid findings into one bounded correction pass, run only the affected
focused evidence, freeze one replacement head and repeat both reviews in
parallel. A further correction cycle requires a newly demonstrated defect
that could not reasonably have been included in the consolidated pass.

Before opening a product PR, locally validate every legally includable
lifecycle component: canonical transition, guard manifest, candidate,
append-only authority record, generated projections, exact live dry-run plan,
post-merge writer expectation and zero-action readback expectation. Never
merge while required authority metadata is known to be absent, and never
combine dependency-edge and lifecycle transactions where the guard forbids
it.

Run the smallest attributable local suite that proves changed product and
authority boundaries. Broaden or rerun only when the diff, a reviewer finding,
the classifier or repository contract requires it. Do not change a frozen
head for cosmetic chronology or wording. Open a convergence repair only for a
fresh deterministic failure on current exact main; add its exact regression,
make one narrow correction and return to product work. Use one CI watcher and
report only findings, exact heads, approvals, terminal gates, merges,
writer/readback results and next-issue selection.

## Routing

```text
Ordinary feature:
implementer → reviewer → main integration → release verifier when required

Unknown defect:
diagnostician → implementer → reviewer

High-risk change:
optional planner → implementer → reviewer + risk reviewer

Performance work:
benchmark guard → performance refactorer → benchmark guard → reviewer
```

## Product rules

- Keep the application local-first.
- Keep `execution_allowed=false`.
- Risk and data-quality gates override forecasts, model output, audits and UI actions.
- TimesFM, Toto and other model integrations remain optional and disabled-safe; the application must retain deterministic baseline behaviour without model packages or weights.
- Do not grant broker, provider or other external write authority unless explicitly approved.
- Do not enable live orders or broker writes.
- Do not add cloud uploads or silent external network activity.
- Use adjusted, corporate-action-aware data for returns.
- Preserve point-in-time, revision and replay semantics.
- Never introduce look-ahead or survivorship leakage.
- Missing, stale, conflicted and unsupported data must remain explicit.
- Do not invent or silently zero-fill data.
- Keep UI logic separate from financial and domain logic.
- Keep one canonical path for every financial calculation.
- Do not weaken tests or safety gates to obtain a pass.
- Do not add production dependencies without explicit authority.

## Autonomous bounded execution

Standing owner authorization applies to bounded repo-local decisions: do not
ask permission questions for ordinary in-scope edits, focused tests,
canonical or generated-file work, CI/check work, or narrowly bounded internal
authority repairs. Product and control-plane work may proceed autonomously at
tiers E, O, H and C within the delegated files and safety rules; H-tier work
requires full independent review and validation before handoff. When internal
process instructions conflict, resolve the conflict with the smallest safe
forward-progress change that preserves the stronger safety invariant. A
bounded internal control repair is not owner-blocked merely because it is
internal; protected external actions still require their existing authority.

## Testing

The assigned implementation or test agent runs focused tests.

The main agent reviews the diff and runs affected integration, UI, lint, type and compile checks according to the change's risk tier.

Run the complete Linux and Windows packaged gate immediately for persistence, migrations, concurrency, canonical financial calculations, security, release tooling, programme-control machinery or broker authority.

For ordinary work, run the full packaged gate centrally after every two or three completed issues and at final certification.

Do not rerun unchanged passing tests.

A documented flake may be retried once.

## Stop loops

After two failed attempts on the same approach without materially improved evidence, stop.

Record:

- the failing test or evidence;
- the likely cause;
- what was attempted;
- what decision or authority is needed.

Do not continue editing unrelated code.

## Git and GitHub

Only the main agent may commit, push, open or merge pull requests, update canonical status or synchronise GitHub issues.

Use isolated branches and expected-head merge protection.

Reuse valid evidence when the source, dependency, policy, environment and validation identity are unchanged. Do not rerun an unchanged passing gate merely because a commit or status event occurred.

Apply GitHub issue changes only from the existing reviewed checksum-controlled process.

Require a zero-action readback after synchronisation.

Never force-push, publish a release or tag, deploy or enable execution without explicit approval.

## GitHub mutation safety scope

GitHub mutation safety infrastructure is limited to repository-authored issue
creation and lifecycle/status projections currently used by the programme.
Git remains canonical; GitHub events are tamper-evident projections, not
immutable records or server-side compare-and-swap.

Do not turn the authority ledger into a general GitHub database, issue tracker
or event-sourcing framework. Do not add speculative support for pull requests,
labels, releases, tags, deployments or unrelated GitHub resources. Ambiguous,
cancelled, partially applied or erased writes fail closed; retries, recovery
and compensation must not invent authority or rewrite history.

After the bounded H-tier repair and formal ISSUE-0180 integration, freeze this
infrastructure and resume product work with ISSUE-0101. Any later expansion
requires explicit user approval and a demonstrated safety need, not optional
hardening.

## Progress

Do not repeatedly report that a process is still running.

Report only:

- verified start;
- concrete finding;
- worker completion;
- failed test;
- review result;
- terminal CI result;
- merge;
- blocker.
