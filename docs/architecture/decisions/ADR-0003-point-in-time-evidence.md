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

ISSUE-0182 builds the research panel from explicit local observations or the
captured membership ledger at each decision time. Feature groups retain their
availability times. Adjusted EUR forward labels use the Xetra session calendar
for VWCE and use only outcome evidence known by the next session open. A
missing benchmark bar leaves the excess label unavailable. Validation keeps each
decision date together and excludes training
labels unavailable at the first validation decision.

### Per-bar price stamps (amendment 2026-11-20)

Every daily price bar carries `ingested_at`, `known_at`, `available_at` and
`actions_evidenced` (contract C1 of the
[forward paper path](../forward-paper-path.md), [ADR-0009](ADR-0009-forward-paper-path.md)).
One function, `stamp_price_availability` in `data/import_pipeline.py`, sets
them for both writers (`commit_price_import`, `universe_fetch.promote_staging`)
and for `rollback_latest_price_import`. A new or revised bar gets the
retrieval time, never an earlier time; a new bar is available at
min(session 23:59:59 UTC, retrieval time). An unchanged bar keeps its stamps; a
uniform `adjusted_close` re-base is not a revision. A legacy bar with
`ingested_at` and no `known_at` gets `known_at := ingested_at`; a bar without
stamps stays unstamped and is unavailable to every stamped reader.

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
