# INT-22 — FinanceDatabase reference import

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P3`; gate `G4`; lane `D`; estimated size `small`
- Logical prerequisites: `-`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `scripts/import_financedatabase.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

FinanceDatabase reference import
- Gate G4 | Priority P3 | Size small | Depends on: none | Features: F0001, F0179
- Upstream: `JerBouma/FinanceDatabase` 2.5.1 (`91c22642`, MIT): `database/equities/<EXCHANGE>.csv`, `database/etfs/<EXCHANGE>.csv`. The package is not installed.
- Targets: `scripts/import_financedatabase.py` (new), `data/identity_master.py` (`IdentityMasterStore:139`), `data/universe_import.py`.
- Steps: import a user-downloaded copy, with the file hash, as **current** low-authority hints (`source="financedatabase"`). No historical membership or delisting date is inferred from it.
- Acceptance: a hint never overrides an official identity; the import works offline.
