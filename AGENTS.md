# ETF AI Cockpit — Codex Rules

Before selecting or continuing work, read the durable active objective and
checkpoint in `plans/ACTIVE_CODEX_GOAL.md`.

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

The orchestrator may own one reviewed, immutable release lane while the single
worker prepares one dependency-ready, non-overlapping product lane in a
separate worktree. The orchestrator remains the sole integration authority.

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

Classify every change under the validation tiers below before broad testing.
Reuse exact-head passing evidence only when relevant files, dependencies,
policy and environment are unchanged.

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

## GitHub mutation safety scope

GitHub mutation safety infrastructure is limited to repository-authored issue
creation and lifecycle/status projections currently used by the programme.
Git remains canonical; GitHub events are tamper-evident projections, not
immutable records or server-side compare-and-swap.

Do not turn the authority ledger into a general GitHub database, issue tracker
or event-sourcing framework. Do not add speculative support for pull requests,
labels, releases, tags, deployments or unrelated GitHub resources. Ambiguous,
cancelled, partially applied or erased writes fail closed; retries, recovery
and compensation must not invent authority or rewrite history. This repair
implements no compensation or recovery mechanism. Any future explicit
compensating-record mechanism requires user approval and must not repeat or
rewrite history.

After the bounded H-tier repair and formal ISSUE-0180 integration, freeze this
infrastructure and resume product work with ISSUE-0101. Any later expansion
requires explicit user approval and a demonstrated safety need, not optional
hardening.

## Throughput and validation tiers

Classify every change before broad validation. When uncertain, select the higher-risk tier.

- `E — evidence only`: canonical status, dependency-edge evidence, deterministic generated documents or documentation. Require exact guards, generators/check mode, registry/status validation, diff hygiene and the canonical source/supply policy. Do not run the Linux/Windows package matrix unless protected tooling changed.
- `O — ordinary product`: require worker focused tests, orchestrator affected integration/UI/architecture/static checks and source smoke. Run the central full package gate after every two or three completed ordinary issues and before a release milestone.
- `H — high risk`: persistence, schema/migration, concurrency, canonical financial calculations, security/credentials, packaging/CI/release tooling, programme-control/status-transition machinery, or broker/order authority. Require the immediate complete Linux and Windows package gate.
- `C — certification`: B13/final release candidate. Require complete cross-platform tests, packaging, parity, smoke, performance, security, privacy, legal, SBOM/signature and final evidence.

Do not use a retained red baseline. `main` must remain green. A documented flake may receive one exact unchanged-head retry only when its node and fingerprint match the approved flake record.

## Frozen release lane and active worker lane

“Work sequentially” means one implementation writer and one integration authority, not idle time during CI.

- The orchestrator may own one reviewed, immutable release lane while the single worker prepares one next dependency-ready product lane in a separate worktree.
- The worker lane must have a disjoint file boundary and may not edit `issues/`, `plans/`, generated programme documents, workflow files or the frozen PR's files.
- The worker may not push, merge or update GitHub. After the prior merge, the orchestrator reviews and transplants/rebases the checkpoint onto fresh `origin/main` before integration.
- Do not start an overlapping or dependency-invalid lane merely to create activity.

## CI and observability

- Every workflow run must emit a deterministic validation-tier report, per-stage timings, environment fingerprint and JUnit/slow-test artefacts where tests run.
- Full/affected pytest runs must report the slowest 100 setup/call/teardown durations with a minimum threshold of 0.25 seconds.
- Use workflow concurrency cancellation for obsolete PR heads. Retain final-certification runs only when policy explicitly requires every attempt.
- Use one terminal `validation-summary` check. Conditional jobs may skip only when the classifier authorises it; the summary must fail if any tier-required job fails.
- Run the equivalent repository/source supply-chain scan once per exact tree. Keep platform-specific package checks only where platform behaviour differs.
- Release tests are local/offline. Do not contact Yahoo Finance or other providers in protected tests.
- Keep full logs, JUnit, timing, screenshots, SBOM and repeated per-run reconciliation as workflow artefacts. Commit compact current state and milestone evidence only.

## Mandatory preflight contracts

Before an expensive full gate:

- added or changed routes and controls must have `configs/ui_acceptance.yaml` coverage;
- presentation modules must consume domain/data functionality through the application facade;
- generated registry, status, completion, readiness, reconciliation and transition-manifest outputs must be fresh;
- semantic text hashes must be independent of CRLF/LF checkout conversion;
- smoke tests must use ephemeral ports;
- tests must use isolated temporary roots and leave no SQLite, package or runtime artefacts in the worktree;
- the selected Python environment must match the pinned validation profile and contain tier-required dependencies.

## Programme generation

- Update the canonical control source first and regenerate public projections; do not hand-edit `CURRENT_STATUS.json` or other generated status documents.
- Prefer one atomic generate-and-check command covering remote summary, registry, status, completion, reconciliation, GitHub plan and transition manifest.
- A second check-mode run must produce zero diff.
- Apply GitHub changes only from the reviewed checksum-controlled plan and require a fresh zero-action readback.
- Preserve issue identity, status semantics, dependency evidence, policies and `execution_allowed=false`.

## Performance optimisation

- Profile before parallelising pytest. Start any xdist pilot at four workers, use explicit groups for SQLite, Flet, ports, package, environment and concurrency tests, and retain a serial lane where required.
- Track worker-completion-to-actionable-result, PR lead time, product-code PR share, PRs per integrated issue, obsolete CI minutes, full-gate p50/p95, slow tests and worker idle time.
- Provider batching/caching is a separate runtime issue. It must preserve source policy, legal terms, adjusted-price, provenance, partial-result and fail-closed canonical-commit rules.

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
