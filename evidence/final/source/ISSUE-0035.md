# ISSUE-0035 source gate

`src/etf_cockpit/data/health.py` now defines deterministic `DataHealthRow` and `DataHealthReport` records, SHA-256 checksums and explicit statuses for the configured clean/derived stores plus forecast CSVs, backtest cache and macro directory state. Missing, stale, corrupt, schema-mismatch and unavailable evidence remains explicit and cannot be inferred as healthy.

`src/etf_cockpit/app/pages/data_health.py` renders responsive per-dataset evidence rows with visible `Path`, `Rows`, `As of`, `Freshness`, `Provider`, `Checksum`, `Last success`, `Last failure` and `Warnings` fields. `src/etf_cockpit/app/pages/dashboard.py` exposes the `Data health` summary card.
