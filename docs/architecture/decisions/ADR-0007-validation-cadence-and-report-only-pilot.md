# Derive validation cadence and keep the parallel pilot report-only

**Status:** accepted

**Date:** 2026-08-01

## Context

Ordinary product changes need periodic full Linux and Windows package evidence,
but the previous workflow accepted a manually maintained counter and defaulted
a missing value to zero. No authoritative writer maintained that value. The
parallel validation pilot also ran for changes unrelated to its mechanics,
which consumed runner time without improving the authoritative release result.

## Decision

The `validation-classifier.v1` interface remains backward-compatible and
derives ordinary cadence from the exact pull-request base's first-parent
`origin/main` history. It ignores E-only merges, counts O product merges after
the nearest verifiable H/C reset, and requires the serial package gate for the
second O issue. A merged H/C change resets the count because that change
requires its own full gate. Shallow history, stale or malformed identity,
ambiguous ancestry, classifier failure, missing reset evidence, and malformed
overrides set `known=false` and fail O upward to the package gate. This adds no
GitHub-variable writer and grants no mutation authority.

The classifier separately emits whether the report-only parallel pilot is
required, its repetition count (zero, one, or two), and its reason. Pilot
mechanics, test partition, release environment or dependency lock,
concurrency, persistence, Windows sharing, atomic write, isolation, tier-C,
and explicit full-sample changes use two repetitions. Ordinary scheduled or
manual drift samples use one. Unrelated H documentation, plans, role
instructions, and ordinary product changes skip the pilot.

Pilot jobs depend on successful classifier, preflight, and supply-chain jobs.
They and their aggregation remain `continue-on-error`, always produce
diagnostic artifacts when run, and have no terminal release authority. The
serial Linux and Windows package jobs and `validation-summary` remain
authoritative. A skipped pilot therefore cannot leave branch protection
pending.

## Consequences

Cadence is reproducible from reviewed Git history and unknown state selects
more validation rather than less. Pilot cost is limited to relevant changes
and explicit samples, while authoritative release semantics remain serial.
Bootstrap measurements must remain separate from steady-state samples.

## Alternatives

A mutable GitHub variable, a missing-value default of zero, making pilot jobs
authoritative, and running the pilot on every H-tier change were rejected.

## Evidence and links

`scripts/classify_validation.py`, `.github/workflows/release-gate.yml`,
`tests/test_issue_0178_validation_classifier.py`,
`tests/test_issue_0180_parallel_pilot.py`,
`plans/ATOMIC_FAST_PATH_METRICS.md`, and
`docs/product-completion/DELIVERY_WORKFLOW.md`.
