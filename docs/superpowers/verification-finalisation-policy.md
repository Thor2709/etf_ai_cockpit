# Verification Finalisation Policy

This policy is binding for every finalisation, closure, release and evidence run in the ETF AI Cockpit programme. It supplements the approved specification, programme index and owning closure plan; it does not alter product scope, authority boundaries or acceptance criteria.

## Evidence isolation

- Tests, fixtures and diagnostic exports write only to per-test or per-run temporary directories.
- They must never mutate `evidence/final/`, canonical audit packets, verification manifests, release or final-evidence builds, issue ledgers, programme ledgers, `RUN_STATE.json` or other durable closure records.
- Canonical evidence is generated only after source, tests and packaging inputs are frozen, and is then checksum-verified.
- Evidence is first written to a per-run temporary directory or `evidence/staging/<generation>/`. A staged generation is explicitly non-final and cannot satisfy closure. Promotion to `evidence/final/<generation>/` is one atomic operation after validation; the promoted generation is immutable.

## Shared release certification

- Implementation verification and release certification are separate records. A release record is reusable only when its key matches the exact implementation/source commit represented by the executable, packaged executable SHA-256, environment hash and command text. Evidence-only commits retain that implementation commit in the record key and therefore do not invalidate executable certification.
- `executable_hash` covers executable bytes only. `evidence_hash` covers captured evidence paths and content only. Edits to plans, manifests, worklogs, issue ledgers or other evidence metadata never change executable verification.
- A passing full suite, build/package command, browser pass or review is executed once for an unchanged key and may be referenced by multiple owning issues. The durable record must retain the shared record ID and all issue/reviewer references.
- A relevant source, test, configuration or packaging change invalidates only the affected keys; a documentation/evidence-only edit does not invalidate executable certification.

## Resume and review accounting

- Resume from the last committed programme ledger/run-state checkpoint. A committed checkpoint is authoritative and must not redispatch work already recorded as complete.
- Independent review is a reusable shared record when it covers the same change set and requirements; multiple owning issues reference that approval rather than dispatching duplicate reviews.
- Review, re-review and finalisation attempts are bounded. Once a gate passes for an unchanged key it is never repeated; after two failures of one approach, perform targeted root-cause analysis before any materially different attempt.

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
