# Bitemporal point-in-time and data-vintage model

The local bitemporal ledger records each source observation as an immutable row. The economic validity interval is represented by `valid_from` and `valid_to`; the application's knowledge timeline is represented by `published_at`, `available_at`, `observed_at`, `ingested_at` and `revised_at`. `revision`, `status`, `source_id` and `source_checksum` preserve the provenance of amendments, restatements, corrections, retractions and supersession.

`BitemporalStore.as_of(dataset_id, decision_time)` returns the latest active revision that was available by the decision timestamp. It excludes observations with unknown timezone confidence and rejects missing or ambiguous availability. Later vintages therefore cannot leak into earlier decisions. Each derived frame can be stamped with the selected decision timestamp and a deterministic `source_vintage_hash`; the audit export includes the corresponding metadata-only vintage manifest.

The `value_json` field is the local snapshot of the raw observation. This is required for current-only public sources: every ingest appends the response snapshot and its checksum rather than relying on a later request to reproduce the source. Retractions and supersessions append marker observations; they never update or delete the original row. SQLite triggers enforce the append-only boundary.

Instrument History renders the vintage and correction metadata, Data Health reports ledger and retraction counts alongside storage integrity, and Audit includes the immutable decision-time manifest. The model is local-first and does not authorise broker execution or external uploads.
