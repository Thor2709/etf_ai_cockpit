# Decision journal

The Decision Journal is a user-owned, local-only record of research decisions. It
does not create orders, grant execution authority or send private notes to
external services.

Each entry is immutable after publication and carries a checksum. Corrections
append a superseding entry; they do not rewrite the original. Schema 1.0
entries remain readable, while new entries use schema 2.0.

The v2 contract records:

- decision state: pending, accepted, rejected or deferred;
- evidence references and alternatives considered;
- confidence, invalidation rules and a review date;
- portfolio and instrument context;
- immutable model-run, proposal and order identifiers.

The export summary contains counts and checksums only. Private thesis text and
private notes are excluded from operational logs and summary exports. Any
future proposal or order identifier is a lineage link, not permission to
transmit or execute it.
