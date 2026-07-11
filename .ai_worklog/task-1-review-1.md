# Wave 0 Task 1 Independent Review - Round 1

## Spec compliance

- **Result:** Needs fixes.
- **Verified:** schema version 2, historic baseline count 41, 42 active records, separate `DATA-05` record with `still_open` status and the seven required gates.
- **Cannot verify from the review package:** the durable checkpoint updates. The controller must check that `RUN_STATE.json`, `.ai_worklog/PLAN.md`, `.ai_worklog/TESTING.md` and the progress ledger record the command, exit code, current source checksums, schema version 2, no issue closure and the independent-review state.

## Strengths

- `ClosureMatrix` preserves iteration, length, indexing and explicit lookup while exposing schema metadata.
- The configuration leaves historic records unchanged and appends `DATA-05` separately.
- The migrated regression distinguishes the historic 41-ID set from the 42 active records.
- Tests exercise Pydantic validation and matrix contents rather than mock calls.
- No execution-enabling functionality was added.

## Findings

### Important - must fix

- `src/etf_cockpit/operations/models.py:31`: approved evidence does not require non-empty actor identifiers or normalise surrounding whitespace before comparing `builder` and `independent_reviewer`. An approved record can represent the same actor with whitespace variation, or lack a reviewer entirely. Require non-empty normalised actor IDs, compare normalised values, and add real validation tests for blank and whitespace-equivalent reviewer IDs.

### Minor - record for final triage

- `src/etf_cockpit/core/closure.py:107`: schema metadata currently accepts unsupported versions and impossible historic-baseline counts. Consider supported-version and baseline-bound validation with focused failure tests during final triage or a directly related follow-up task.

## Assessment

**Task quality:** Needs fixes. The central independent-review boundary is bypassable until the Important finding is resolved and independently re-reviewed.
