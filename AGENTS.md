# ETF AI Cockpit — Codex Rules

## Goal

Complete the canonical implementation plan correctly and efficiently.

The Sol-high main agent plans, delegates, reviews and integrates.

Exactly one Sol-low `sol_worker` performs each substantive implementation task.

Work sequentially on one issue or one necessary shared prerequisite at a time.

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
5. Spawn one `sol_worker`.
6. Review the worker's complete diff and tests.
7. Request at most one focused worker correction.
8. Integrate and run the necessary broader checks.
9. Update the batch plan, status and GitHub only after the implementation is evidenced.

The main agent should not write substantial product code. Small integration and generated-file corrections are allowed.

## Worker

The `sol_worker`:

- performs the actual coding;
- owns one bounded task;
- reads only relevant context;
- makes the smallest correct change;
- adds and runs focused tests;
- does not change unrelated files;
- does not spawn agents;
- does not push, merge or update programme status.

## Product rules

Architecture-affecting work must read `docs/architecture/SDD.md` and relevant
ADRs; architecture or contract changes must update the SDD/ADR in the same PR.

- Keep the application local-first.
- Keep `execution_allowed=false`.
- Do not enable live orders or broker writes.
- Use adjusted, corporate-action-aware data for returns.
- Preserve point-in-time and revision semantics.
- Never introduce look-ahead or survivorship leakage.
- Missing, stale, conflicted and unsupported data must remain explicit.
- Do not invent or silently zero-fill data.
- Keep UI logic separate from financial and domain logic.
- Keep one canonical path for every financial calculation.
- Do not weaken tests or safety gates to obtain a pass.
- Do not add production dependencies without explicit authority.

## Testing

The worker runs focused tests.

The main agent reviews the diff and runs affected integration, UI, lint, type and compile checks as relevant.

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

Apply GitHub issue changes only from the existing reviewed checksum-controlled process.

Require a zero-action readback after synchronisation.

Never force-push, publish a release or tag, deploy or enable execution without explicit approval.

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
