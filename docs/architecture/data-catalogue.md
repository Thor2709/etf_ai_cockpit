# Data Catalogue and lineage

The local `DataCatalogue` registers raw, clean and derived dataset metadata and
content-addressed snapshots. Dataset definitions include schema, owner, source,
licence, update schedule, partitions, quality, retention and PII classification.
The catalogue stores metadata and hashes only; it does not copy data or call
remote providers.

Snapshot IDs are derived from canonicalised rows and schema metadata. Repeating
the same inputs therefore resolves to the same immutable ID. A snapshot can
reference upstream snapshot IDs, which generate explicit `derived_from` edges.
Validation reports missing upstreams, cycles, stale snapshots and schema
incompatibilities. Impact analysis walks downstream edges, while the instrument
provenance query walks from covered snapshots back through their upstreams.

The first slice provides a local JSON catalogue, a read-only Data Catalogue
workspace and redacted audit summary. Retention execution, provider scheduling,
job/model-run integrations and large-scale catalogue storage remain later work.
