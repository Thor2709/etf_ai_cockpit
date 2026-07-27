# Point-in-time evidence and explicit source conflicts

**Status:** accepted

**Date:** 2026-07-27

## Context

Research and replay are invalid if later revisions, publication knowledge or
conflicting sources leak into an earlier decision.

## Decision

Identity is stable across listings and revisions. Evidence retains valid,
publication/acceptance, retrieval and knowledge chronology, provenance and
revision identity. Conflicts and missing chronology remain explicit and fail
closed; they are never silently merged or zero-filled.

## Consequences

As-of queries and replay require versioned evidence. ISSUE-0153 must resolve
the outstanding chronology/hash contract before dependent work treats it as
complete.

## Alternatives

Latest-value overwrites and provider-priority without conflict evidence were
rejected because they create look-ahead and irreproducible results.

## Evidence and links

[Bitemporal model](../bitemporal-vintage-model.md),
`src/etf_cockpit/data/bitemporal.py`, `tests/test_no_lookahead.py`.
