# Autonomous controller run guardrails

This file is the durable controller checkpoint for the ETF AI Cockpit programme. It supplements the repository-root `AGENTS.md` and must be read before any later task worktree or subagent acts.

## Authority and isolation

- `main` is coordination-only. Task implementation, correction, test edits and task commits belong in a fresh dedicated worktree created from the current verified `origin/main`.
- Before editing, explicitly verify the exact absolute worktree path, current branch, HEAD, relationship to `origin/main`, and clean or deliberately preserved status. Work only inside that verified worktree.
- Reviewers must be explicitly bound to that same absolute path, branch, HEAD, intended diff and bounded scope. A review performed in another worktree, branch or stale commit is invalid.
- Preserve unrelated modified and untracked files. Never stage or commit `.tmp_open_headings.txt`.

## Command and session safety

- All commands run synchronously. Never start the same command twice, interrupt a running command, background it, start a replacement while it may still be active, or redispatch a command with unknown completion status.
- If a command appears stalled, poll or inspect the same terminal/process, read its existing output, confirm that exact process has ended, and only then decide the next action.
- Do not create custom verification locks, PID-liveness systems, subprocess-coordination frameworks, process-killing/probing mechanisms, schedulers, exactly-once ledgers or test-result reuse databases. Use the existing Phase 2 verification-record mechanism.
- Do not add POSIX-style `os.kill(pid, 0)` process probes to Windows verification orchestration. Reuse an existing reviewed repository primitive or an established accepted cross-platform library; if neither exists, stop for architectural review.
- Missing tool output, callbacks, rollouts or session metadata, repeated app-server termination, or session-state corruption is a safe-stop condition. Preserve repository/worktree state, record the last confirmed command and result, do not restore corrupted Codex state or repeatedly redispatch in the damaged session, and resume only from a fresh conversation with verified filesystem state.

## Verification discipline

- Before the first test command for each bounded unit, freeze the exact RED, GREEN, smallest affected regression, static and required acceptance gates, including the inputs that would invalidate each result.
- Record each command, relevant source/executable/environment/command key, whether it started, final exit code, result and later invalidating changes.
- Do not rerun previously passing tests or gates when their relevant inputs are unchanged. Documentation-only, worklog, checkpoint, commit or elapsed-time changes do not invalidate a passing result.
- After the predefined required gates are green and the correctly scoped independent review is approved, stop testing. No optional “one more test run for confidence” is permitted.
- Full-suite, package, browser, export, audit and clean-first-run gates run at most once per exact valid input key unless a relevant change invalidates the result or the first invocation did not actually execute.
- Use the existing Phase 2 verification-record workflow and fail closed when evidence is stale, ambiguous, staged-only, incomplete or associated with the wrong issue or reviewer.

## Git and completion safety

- Destructive Git operations are prohibited: never use `git reset --hard`, `git clean`, destructive checkout/restore, force-push, forced worktree removal or broad recursive deletion.
- Before commit, inspect the exact staged file list and include only the intended bounded unit. After merge, verify the merge on `origin/main`; retire a worktree only when it is clean, has no unique unmerged commits and contains no preserved local files.
- Reconcile programme index, closure plan, progress ledger, `RUN_STATE.json`, closure matrix, issue records and evidence records before selecting the next dependency-valid unit. Do not reimplement an implementation-complete task merely because its issue remains open; complete only missing authoritative evidence and closure gates.

## Governance-unit verification plan

- RED/GREEN application tests: not applicable. This bounded unit changes only governance documentation and `RUN_STATE.json`; the application test suite must not run.
- Required static/format check: `git diff --check` from the exact governance worktree.
- Required syntax check: parse `RUN_STATE.json` with the repository-available JSON parser and confirm the three intended files exist.
- Required scope check: inspect the exact diff and staged file list; only `AGENTS.md`, this guardrail file and `RUN_STATE.json` may be changed.
- No full-suite, package, browser, export, audit, clean-first-run or build gate is required for this documentation-only unit. Any change to application, test, packaging or evidence inputs would invalidate this plan and require a new bounded unit.
