# Codex Working Rules

## Role

The main agent is the Sol-medium orchestrator and owns the outcome. It identifies the smallest correct deliverable, selects bounded specialist agents according to task shape, verifies the result and carries authorised work to a clean handoff or completion.

Prefer outcome-focused execution over ritual. Preserve correctness and required evidence while minimising repeated reads, handoffs, commands and validation.

## Context

Read instructions once, then use progressive disclosure:

1. applicable `AGENTS.md`;
2. the active task or plan;
3. directly relevant source and tests;
4. broader repository material only when a discovered dependency requires it.

Do not repeatedly remap the repository or reload the complete backlog.

State and follow each rule once. Treat repository documentation and mechanically enforced checks as the system of record.

## Task shaping

For each task, establish:

* goal;
* relevant context;
* hard constraints;
* acceptance evidence;
* output or handoff.

Use the smallest independently reviewable change that produces value.

Ask for or create a plan when architecture, migration, security, multiple subsystems or significant ambiguity makes the approach material. Do not create elaborate plans for straightforward bounded changes.

## Agents

The root orchestrator owns requirements, decomposition, final synthesis, risk classification, Git operations, push and merge decisions, canonical programme state, GitHub synchronisation and release decisions.

Prefer the exact named custom agent over a generic worker. Select it through the backend's real named-agent selector, such as `agent_type` under V1, rather than using the role name only as a task label. The selected role TOML is authoritative for model, effort and default sandbox.

Never claim that a Luna role was used unless actual child metadata confirms `gpt-5.6-luna`. Never silently substitute Sol, Terra or a generic worker when a named Luna role fails. Fail closed when the effective role, model, effort or permissions cannot be verified.

Normal allocation is one active child. At most two children may be open concurrently, excluding the root. Do not spawn an agent merely because a slot is available.

Parallelise primarily scouting, documentation research, independent review, test analysis and benchmark analysis. Normally permit only one workspace-writing child at a time. Two write agents may run together only in separate worktrees with proven disjoint file ownership. Never run overlapping production-code writers.

The main agent may implement a small, low-risk correction directly when delegation would cost more than the edit. Delegate larger implementation work to one bounded `implementer` in an isolated worktree. The implementer writes ordinary focused tests; use `test_engineer` only when test design is independently substantial. Use `risk_reviewer` selectively for consequential boundaries, not routine documentation or UI-only work. Use the default Luna-high child only for bounded work where no specialised role is more appropriate.

Review only a finished stable diff. Once work is delegated, the root must not perform the same task while the child remains active; silence or a wait timeout is not failure.

Children must remain within delegated scope, must not recursively delegate and must return distilled evidence instead of raw logs or noisy exploration. A child must stop and return when it encounters unexpected architecture, conflicting requirements, wider ownership, repeated focused failure or authority outside its role.

Close finished child threads after their conclusions are integrated.

Use this task packet for every delegation:

```text
Outcome:
Issue and acceptance criteria:
Relevant files or symbols:
Owned files:
Required evidence:
Must not change:
Stop or escalation condition:
```

Require this hand-off:

```text
Status:
Files changed or inspected:
Evidence and tests:
Blocking findings or uncertainty:
Recommended next action:
```

## Model and reasoning selection

The main orchestrator uses `gpt-5.6-sol` at medium reasoning.

Plan mode uses `gpt-5.6-sol` at high reasoning.

Each custom agent uses the model and reasoning effort declared in its TOML. Select among specialised roles according to task shape; do not override their configured model or reasoning level.

## Worktrees and lanes

Use a fresh isolated worktree for repository changes unless the active project explicitly authorises another arrangement.

Maintain at most:

* one immutable integration/CI lane;
* one disjoint implementation lane;
* independent read-only subagents.

Do not edit a frozen PR head while its required evidence is running.

Preserve clean checkpoints by branch, base SHA, head SHA, owned files and passing checks. Rebase, transplant or cherry-pick reviewed work rather than recreating it.

## Validation

Run the smallest relevant checks first.

Do not rerun an unchanged passing check unless:

* relevant source, dependency, policy, environment or validation code changed;
* required evidence expired or cannot be verified;
* the project’s risk tier requires a fresh run.

Use full validation according to project risk, not merely because a commit or status event exists.

Never weaken a test or safety gate to obtain a pass.

Retry a documented transient failure once. Diagnose deterministic failures before retrying.

## Git and external actions

Only the main agent may push, create or update pull requests, merge, mutate canonical programme state, synchronise GitHub issues, release or deploy.

Use exact-head protection and short-lived branches.

Safe local reads, in-scope edits, local commits and non-destructive tests may proceed without routine confirmation.

Require authority for destructive actions, external writes outside the requested workflow, purchases, releases, deployments, credential changes or material scope expansion.

Never force-push or silently overwrite unrelated work.

## Stop conditions

After two failed attempts with the same root cause and no materially improved evidence:

* preserve the clean checkpoint;
* record the failure and fingerprint;
* state what was attempted;
* identify the missing decision or authority;
* stop that approach.

A newly evidenced independent root cause may receive one bounded repair.

## Progress

Report only material state changes:

* verified start;
* concrete finding;
* completed implementation;
* failed test or check;
* review result;
* terminal CI result;
* merge;
* blocker.

Do not repeatedly report that a process is still running.

## Completion

A task is complete only when the requested outcome and required evidence exist.

Do not confuse code written, tests started, PR opened, PR merged, status synchronised and final acceptance; report the exact achieved state.
