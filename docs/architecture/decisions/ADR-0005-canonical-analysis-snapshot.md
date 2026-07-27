# One canonical analysis snapshot across surfaces

**Status:** accepted

**Date:** 2026-07-27

## Context

Detail, screener, export and audit surfaces must not calculate contradictory
scores or silently use different evidence.

## Decision

Canonical typed analysis/scoring contracts carry snapshot, configuration,
formula/model/policy versions, provenance and disabled authority. Presentation
projects those results; it does not recompute them.

## Consequences

Cross-surface parity and deterministic replay are testable. Contract evolution
requires explicit compatibility and migration.

## Alternatives

Page-local calculations and independent export formulas were rejected.

## Evidence and links

[Canonical score engine](../canonical-score-engine-v3.md),
`src/etf_cockpit/core/types.py`, `src/etf_cockpit/signals/canonical_scoring.py`.
