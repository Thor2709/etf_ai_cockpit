# ETF AI Cockpit — Codex Rules

## Goal

Complete the canonical implementation plan correctly and efficiently.

The `gpt-5.6-sol` medium-reasoning main agent is the orchestrator and sole integration and GitHub authority. It plans, selects the narrowest configured agent roles, reviews and integrates.

Choose efficiently among the 12 configured named roles. Normal allocation is one child and no more than two children may be open concurrently.

Use one active code writer per overlapping file boundary. Parallelise only independent, non-overlapping work.

## Current ISSUE-0177–0180 delivery contract

Read `plans/ACTIVE_CODEX_GOAL.md` and
`docs/product-completion/DELIVERY_WORKFLOW.md` before work. The canonical
classifier selects E/O/H/C and unknown history or cadence fails upward. Exact
base/head, protected source/dependency/product/policy/environment/artifact and
`execution_allowed=false` identities must all match before evidence reuse.
Use one integration/CI lane and normally one implementation writer; a second
child is only independent read-only work or proven disjoint worktree work.
Normally make one product issue per product PR; batch only inseparable,
independent dependency edges. Lifecycle/status convergence is compact and
automatic. Update canonical control first and regenerate projections; never
hand-edit generated status/programme views. Atomic generation must be followed
by a second byte-clean check. `validation-summary` is the normal CI interface;
use at most one watcher and no repetitive polling. Raw artefacts are for
failure, inconsistency, sampled audit or final certification.

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
7. Request at most one focused correction from the implementation agent.
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

Only one agent may write within an overlapping production-code boundary. Review only a finished stable diff. Use `test_engineer` only when test design is independently substantial; the `implementer` owns ordinary focused tests.

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
