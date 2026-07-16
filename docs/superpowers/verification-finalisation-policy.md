# Verification Finalisation Policy

This policy is binding for every finalisation, closure, release and evidence run in the ETF AI Cockpit programme. It supplements the approved specification, programme index and owning closure plan; it does not alter product scope, authority boundaries or acceptance criteria.

## Evidence isolation

- Tests, fixtures and diagnostic exports write only to per-test or per-run temporary directories.
- They must never mutate `evidence/final/`, canonical audit packets, verification manifests, release or final-evidence builds, issue ledgers, programme ledgers, `RUN_STATE.json` or other durable closure records.
- Canonical evidence is generated only after source, tests and packaging inputs are frozen, and is then checksum-verified.

## Unchanged-source gate budget

- For each unchanged source hash, run at most one authoritative full suite, one build, one browser pass, one independent review and one independent re-review.
- Never repeat a passing gate or any gate whose inputs and source hash are unchanged.
- A source or test change invalidates only the gates whose inputs it can affect; record the new source hash and the exact invalidated gates before rerunning them.

## Failure and blocker discipline

- After two failed attempts using the same approach, stop repeating that approach and perform targeted repository and, where relevant, official-source research and root-cause analysis.
- Allow at most five materially different attempts per blocker. Thereafter stop only for a genuine external blocker, preserving the worktree and reporting the exact failing command, root cause, attempts and safest next action.
- Never start duplicate processes, interactive commands or a second copy of a running command. Long-running commands require explicit bounded timeouts; use condition-based waits instead of repeated polling.

## Completion transition

- When all applicable gates pass, immediately commit the reviewed changes, push the branch, create or update the pull request, merge through the approved process, synchronise local and GitHub Issues, verify the merged state and continue to the next dependency-valid task.

## Durable accounting

Record source hashes, gate budgets, commands, exit codes, output paths and checksums, review verdicts, failures, attempts, blockers and limitations in the owning task report, worklog, plan, progress ledger, run state, closure matrix and issue records.
