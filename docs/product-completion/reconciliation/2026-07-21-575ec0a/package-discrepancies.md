# Package reconciliation discrepancies

The supplied package is immutable evidence. It is archived under `docs/product-completion/sources/2026-07-15/` and is not committed as a binary ZIP. Its external SHA-256 is `39e30adc22c34a2f80640fa895caa21473457cea5bd0de872927051f8f99839b`; the member hashes are recorded in `SOURCE_MANIFEST.sha256`.

## Snapshot and ledger differences

- Package reviewed commit: `e149db50945401fb014955f0f79794a909796a75`.
- Reconciliation baseline: `575ec0ab7c7e86f066c763022ea2dfaf397dd53d` (`origin/main`).
- Package current records: `76`; latest canonical open headings: `97`.
- Current package records now closed by the canonical closed index: `UPDATEV2-0015`, `UPDATEV2-0016`, `UPDATEV2-0017`, `UPDATEV2-0019`.
- Local-only current/closed records are listed in `current-only-records.csv`; no identifiers were renumbered.
- Stale open sections for `ISSUE-0069`, `UPDATEV2-0010` and `UPDATEV2-0022` were removed. `ISSUE-0067` remains open. The full `UPDATEV2-0010` record is preserved in `issues/closed.md`.

## Dependency and structure differences

- Raw package candidate graph cycles: `543`. The canonical blocking graph contains zero cycles; converted candidates and reasons are recorded in `dependency-reconciliation.csv`.
- External or historical dependency references are retained as related context; `UPDATEV2-0028` is the known package reference outside the package snapshot.
- The current router exposes `40` registered routes. This is recorded as source evidence because the supplied plan's earlier route estimate was lower; no routes were removed in this documentation task.

## Scope boundary

This change implements package validation, archival, reconciliation, canonical registry/roadmap documents and safe synchronisation tooling only. It does not implement product features, broker automation, external uploads or cloud services.
