# Hybrid local analytical and transactional persistence

**Status:** accepted

**Date:** 2026-07-27

## Context

Columnar analytical history and mutable transactional state have different
consistency and query needs.

## Decision

Use immutable Parquet generations and DuckDB for analytical reads, with
catalogue/checksum publication; use SQLite/JSONL and atomic files for
transactional, job and event state according to their existing contracts.
Publication and recovery fail closed.

## Consequences

Backups checkpoint transactional stores and verify referenced generations.
Schemas and migrations remain versioned; compatibility stores are not rewritten
implicitly.

## Alternatives

The legacy DuckDB-only description and a remote database were rejected as
inaccurate or contrary to local-first operation.

## Evidence and links

[Hybrid platform](../hybrid-local-data-platform.md),
`src/etf_cockpit/data/hybrid_platform.py`, `tests/test_hybrid_platform.py`.
