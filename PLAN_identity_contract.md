# Historical plan — identity contract prerequisite

This completed checkpoint preserves historical implementation evidence. Its
`sol_worker` routing is superseded by
`docs/product-completion/DELIVERY_WORKFLOW.md` and current named-agent policy.

- Base: `origin/main` at `4e2876eda47daa7da5fa7a82bc7a1adddccbbdc8`.
- Programme state: `ISSUE-0153` remains `in_progress`; GitHub issue `#432` is open; `execution_allowed=false`.
- Blocker: identity claims do not persist retrieval chronology, so a later retrieval can collapse onto an earlier claim identity; adding retrieval to the decision-hash payload also requires an explicit compatible schema/version transition.
- Outcome: preserve every distinct retrieval observation, keep exact duplicate appends idempotent, enforce point-in-time eligibility without look-ahead, and provide deterministic legacy-v1 plus new-version decision hashing.
- Scope: `instrument_identity.py`, `identity_master.py`, directly affected identity consumers, focused tests, and the matching SDD contract note.
- Excluded: all fixed-income terms, schedules, pricing, UI, provider adapters, broker writes, live orders, and unrelated refactors.
- Acceptance: legacy records remain readable and replay identically; changed retrieval timestamps are not false-idempotent; concurrency loses no claims; corrupt/future versions fail closed; audit projections expose a versioned deterministic decision identity.
- Checks: focused identity, point-in-time, persistence/migration, concurrency, portfolio-import/instrument-detail audit tests; Ruff/compile; then the protected Linux and Windows packaged release gate before merge.
- Checkpoint: implemented by one `sol_worker`; full-diff review found no remaining chronology, leakage, claim-loss, concurrency, migration, or hash-compatibility defect. The one focused correction pinned the verified pre-change v1 decision hash.
- Local evidence: 104 affected tests passed; changed-file Ruff, MyPy, compileall, and `git diff --check` passed.
- Next action: commit and open the prerequisite PR, require the protected Linux and Windows packaged release gate, merge only at the reviewed head, then restart ISSUE-0153 from fresh `main`.
