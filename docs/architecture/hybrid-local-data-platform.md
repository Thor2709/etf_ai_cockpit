# Hybrid local analytical and transactional platform

ISSUE-0072 provides the first usable platform boundary on top of the ISSUE-0038 storage foundation.

## Published data contract

`HybridPlatform.publish_generation()` accepts a local Pandas frame only when every row has a non-empty `stable_id` and `run_id`, and each pair is unique. The frame is written to an immutable Parquet path under `data/analytics/<dataset>/` and registered in SQLite only after validation. The SQLite catalogue stores the content hash, row count, schema columns, lineage counts and publication state. A generation with the same ID and different content is rejected.

DuckDB reads only catalogue-backed, checksum-verified generations. UI queries therefore see read-only snapshots rather than staging files or a partially written generation. The catalogue's generation-key table uses a foreign key with cascade cleanup so stable/run lineage cannot outlive its generation.

## Failure and recovery

- A failed publication leaves no published generation. A committed `publishing` row is recovered on the next platform open: a matching final file is promoted, otherwise the row is removed.
- SQLite uses WAL and is checkpointed before a backup archive is created, so the archive contains committed transactional pages rather than only the main database file.
- Compaction is preview-only by default. Deletion requires `confirm=True`, validates every candidate checksum, records a local operation and never deletes the newest generation.
- Retention is query-only until an explicit compaction is requested. No network, subscription or vendor quota is involved.

## Compatibility

`export_transactional_csv()` and `export_transactional_json()` preserve simple local interchange paths. Existing file-backed stores are not rewritten implicitly; later issues can migrate them into typed repositories using the stable IDs and run IDs recorded by this platform.
