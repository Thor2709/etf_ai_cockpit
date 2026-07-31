# Bind GitHub issue mutations to durable Git authority

**Status:** accepted

**Date:** 2026-07-31

## Context

The programme requires issue creation and lifecycle/status synchronisation to
fail closed when a GitHub projection is edited, deleted, duplicated, reordered
or only partly applied. GitHub comments can be edited or deleted, and the
relevant REST writes provide no documented server-side compare-and-swap.
Remote state alone therefore cannot prove that a now-missing write never
occurred.

This guarantee is stronger, and the resulting machinery is disproportionate,
for ordinary single-user application development. It is required here only by
the project's formal programme-control and reconciliation guarantees.

## Decision

Git is the sole canonical lifecycle authority. A narrow, append-only Git ledger
authorises only the repository-authored issue creation and lifecycle/status
projections that already exist. GitHub markers and comments are
content-preserving, hash-bound, tamper-evident projections; they are neither
immutable history nor compare-and-swap.

Every eligible write is reconciled against its reviewed Git authority and live
resource immediately before mutation. Ambiguous, cancelled, partially applied
or erased writes remain spent and unresolved. The system does not retry them or
repair history by inventing authority; an explicitly authorised compensating
record may document an anomaly without repeating or rewriting it.

The ledger is not a general GitHub database, issue tracker or event-sourcing
framework. It must not grow speculative support for pull requests, labels,
releases, tags, deployments or unrelated resources. After the bounded H-tier
repair and formal ISSUE-0180 integration, this infrastructure is frozen and
product development resumes with ISSUE-0101. Expansion requires explicit user
approval and a demonstrated safety need.

## Consequences

Complete projection loss remains detectable and automated writers fail closed
without claiming guarantees GitHub does not provide. The trade-off is reduced
availability: an indistinguishable cancelled or erased operation may require
human review and new explicit authority, and it is never retried automatically.

## Alternatives

Treating GitHub comments as immutable, relying on read-then-write as
compare-and-swap, retrying from marker absence, and building a general GitHub
event store were rejected.

## Evidence and links

`scripts/github_mutation_gateway.py`,
`scripts/sync_github_issues.py`,
`.github/workflows/programme-status-completion.yml`.
