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
record is not implemented by this repair. Any future compensating-record
mechanism requires explicit user approval and must document an anomaly without
repeating or rewriting history.

The H-tier status-completion repair adds one separate `status_replay` authority
and `status-replay-candidate/3.0` contract. It is deliberately bounded to one
issue and exactly two ordered legal forward transitions,
`in_progress -> implemented_initially -> integrated`. The two canonical
transition-history entries and two acceptance-evidence entries must preserve
their declared prefixes, match exactly, share one reviewed product commit and
review evidence, and pass the existing lifecycle validator independently.
Both hops are carried by one aggregate proposal and one receipt bound to one
authority, candidate, issue identity and reviewed head. Existing ISSUE-0180
`status` authority, event and receipt bytes remain unchanged.

Generic managed-comment validation recognises the replay proposal and replay
acceptance markers as known authority comments. Their semantic validity still
comes exclusively from the replay parser and ledger reconciliation; this
recognition does not grant them create authority or tolerate malformed markers.

The aggregate is semantically atomic: local validation replays both hops in
memory and projection accepts the final status only when the proposal and its
single receipt form a complete pair. This does not make GitHub transport
atomic or provide server-side compare-and-swap; the transport still performs
one proposal append followed by one receipt append. Partial, cancelled,
erased or ambiguous writes remain spent and fail closed. The existing
no-retry, no-compensation and no-ambiguous-write-recovery policy is unchanged.
This contract is not a general replay framework or event store.

The sole mutation workflow also obtains a fresh GitHub Actions OIDC token at
startup and immediately before every possible issue POST. Its custom audience
is the SHA-256 digest of the exact issue credential presented to the transport.
The local verifier requires GitHub's documented `alg`, `kid`, and `typ` JOSE
header contract and accepts a syntactically valid `x5t` only as optional
corroboration when present on both the header and selected JWK. The thumbprint
never selects or substitutes
for a key and never replaces RSA signature verification over the selected
`kid` key's `n` and `e`. The verifier also binds the fixed issuer and
the signed repository, push/main ref, commit, workflow, first run, GitHub-hosted
runner and job check-run claims to live in-progress run and check objects. This
provides process-local freshness and correlation; it does not prove credential
provenance and is neither a native token `cnf` claim nor server-side
compare-and-swap. A forged context outside the active job, even with a PAT and
borrowed live-run metadata, cannot obtain an accepted proof and cannot POST.
A holder of the live `ACTIONS_ID_TOKEN_REQUEST_TOKEN`, however, can request a
fresh proof whose audience adaptively binds a replacement credential. That is
an excluded active-runner compromise. The final check-status-to-POST race is
reduced but cannot be eliminated by the documented GitHub APIs. The created
issue's actor is not treated as provenance; only canonical managed comments
and receipts pinned to the GitHub Actions bot and app are accepted.

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
`scripts/prepare_github_mutation_authority.py`,
`.github/workflows/programme-status-completion.yml`, and GitHub's
[OIDC token example](https://docs.github.com/actions/reference/security/oidc#example-oidc-token).
