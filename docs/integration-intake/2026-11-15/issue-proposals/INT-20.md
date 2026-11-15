# INT-20 — EODHD dataset adapter

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G3`; lane `D`; estimated size `large`
- Logical prerequisites: `INT-03`; source-file serialization: `-`
- Readiness: `BLOCKED_BY_DATA (dump not delivered)`
- Intended files: `data/eodhd_import.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

EODHD dataset adapter (owner data)
- Gate G3 | Priority P1 | Size large | Depends on: INT-03 | Features: F0001, F0007, F0008, F0030
- Readiness: blocked by data (the dump is not delivered). Use mode: private, non-commercial (U2).
- Targets: `data/eodhd_import.py` (new), `data/stock_fundamentals.py`, `data/identity_master.py`, `data/universe_membership.py` (`closure_events:326`), `data/legal_terms.py`, `configs/data_source_policy.yaml`.
- Steps, each a gate:
  1. Entitlement: record the owner's plan and its terms in the legal-terms registry. EODHD states that business use needs a commercial licence; the import is admitted for private, non-commercial use only (U2).
  2. Staging manifest without a full copy: file list, sizes, schema samples, date ranges, equity coverage; streaming validation; storage plan.
  3. Per-dataset admission with a PIT grade: a dataset with true publication or update timestamps is `observed`; fundamentals with only a period end are `approximated` (period end plus lag is an assumption) and are excluded from training and revision features; present-day estimate history gives no historical revisions.
  4. Import the admitted datasets one at a time: delisted lists to closure events, symbol and ISIN lists to identity hints, fundamentals to `Period` rows. Official SEC / ESEF facts are never overwritten.
- Acceptance: no import runs without steps 1-3 recorded; each row has provenance, `available_at` and `pit_grade`; a conflict with an official fact is recorded, not selected.
