# ISSUE-0035 source gate

Implementation commit: `34c2eaa` on `wave4/task10-data-health` (based on
`557e923`). Independent implementation review: `.ai_worklog/task10-migration-reviewer`;
implementation approved, closure pending.

`src/etf_cockpit/data/health.py` provides deterministic `DataHealthRow` and
`DataHealthReport` records, SHA-256 checksums and explicit healthy, stale,
missing, corrupt, schema-mismatch and unavailable states for the configured
stores, forecasts, backtests, macro content and migration state. Persisted
success/failure history is distinct from migration `as_of`.

Migration records are validated against expected version/name pairs; missing,
malformed or timezone-naive `applied_at` values fail closed, and mixed-offset
timestamps are ordered by UTC instant while preserving the original persisted
value. Macro invalid siblings remain visible beside valid files.

`src/etf_cockpit/app/pages/data_health.py` renders responsive per-dataset
evidence rows with Path, Rows, As of, Freshness, Provider, Checksum, Last
success, Last failure and Warnings fields, status/dataset/provider filters,
related local routes and visible-row CSV export. The existing dashboard summary
card remains unchanged. `execution_allowed` remains `false`.
