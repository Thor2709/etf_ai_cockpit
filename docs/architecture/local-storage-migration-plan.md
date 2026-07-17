# Local storage migration plan

Status: implementation foundation integrated for ISSUE-0038; domain migrations remain owned by the downstream data-platform issues.

## Contract

The application uses two local stores with separate responsibilities:

- SQLite at `data/storage/cockpit.sqlite3` holds small, user-owned transactional records. It runs with WAL, foreign-key enforcement, an explicit migration ledger and ACID write transactions.
- DuckDB reads Parquet under `data/analytics` for large histories and analytical snapshots. Analytical exports never become the transactional source of truth.

The machine-readable contract is [configs/storage_policy.yaml](../../configs/storage_policy.yaml). The implementation entry point is `etf_cockpit.data.local_storage.TransactionalStore`.

## Migration and recovery rules

1. Storage directories are created locally and idempotently.
2. Unknown SQLite schema versions fail closed before application data is touched.
3. Every migration is recorded in `schema_migrations` with a UTC timestamp.
4. SQLite integrity and foreign-key checks are available before an export is published.
5. Transactional records are soft-deleted by default. Automatic retention deletion and compaction are disabled until a later issue defines an explicit, reviewable operation.
6. Parquet exports are written atomically and validated before replacement, preserving compatibility with the existing DuckDB analytics path.

## Compatibility boundary

Existing file-backed datasets remain readable during this migration. ISSUE-0072 will add the canonical analytical catalog and domain repositories; ISSUE-0073 will add bitemporal and vintage columns. This foundation deliberately does not silently rewrite existing user data.
