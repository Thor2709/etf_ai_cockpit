# Wave 1 Governance Task 4 - independent review

## Task completed

Reviewed committed range `7e9a0eceeef826dd373510e9e1c78269817a2a3d..f3e50910f2e27fe41b4af4e4bdb0624a240e087b` and relevant Task 3 authority, atomic-write, app-state and export paths. No production or test file was edited.

Specification/acceptance compliance verdict: **REJECT**.

Code quality/correctness verdict: **REJECT**.

**READY: NO.**

## Files and symbols examined

- `src/etf_cockpit/data/decision_journal.py`: `JournalEntry`, `DecisionJournal.create`, `get`, `list_entries`, `supersede`, `export_summary`, `_append_operation`.
- `src/etf_cockpit/portfolio/review_reports.py`: `create_portfolio_review_report`.
- `src/etf_cockpit/portfolio/proposals.py`: deprecated adapter, retained legacy implementation and proposal logger.
- `src/etf_cockpit/app/state.py`: `AppState.create_trade_proposal` caller.
- `src/etf_cockpit/core/atomic_io.py`: grouped commit, reader lock and recovery contracts.
- `src/etf_cockpit/core/types.py` and `signals/research_states.py`: `SignalResult.to_v2_dict`, `AuthorityDecision`, typed states and gates.
- Task 4 brief/report, governance plan Task 4, Task 3 report/contracts, focused tests and export evidence.

## Findings or changes

### Critical

None.

### Important

1. **Blocking - journal IDs permit path traversal outside the immutable entries directory.** `DecisionJournal._entry_path` interpolates an unvalidated caller ID into a path (lines 44-45); `create` only strips and checks non-empty text (lines 66-69). A fresh probe created ID `../outside` and persisted `decision_journal/outside.json`. This violates the user-owned journal boundary and allows collisions or replacement checks against paths outside `entries/`.

2. **Blocking - required fail-closed missing/malformed persistence diagnostics are not implemented consistently.** `get` raises raw `KeyError` for a missing payload (lines 96-98), while `list_entries` directly indexes `row["journal_entry_id"]` (line 116). Fresh probes produced `KeyError: 'entry-1'` after deleting an indexed payload and `KeyError: 'journal_entry_id'` for index row `{}`. These are not the explicit `JournalIntegrityError` diagnostics required for missing payloads and malformed rows.

3. **Blocking - create is not failure-atomic or idempotent at its public boundary.** The payload/index grouped commit completes before `_append_operation` (lines 86-92). If the append fails, `create` raises even though the entry is committed; retry then fails as a duplicate. Fresh fault injection produced `OSError: log unavailable`, confirmed the payload existed, then produced `ValueError: duplicate journal entry id`. The operation log is also a plain append outside the grouped recovery manifest (lines 148-157). This contradicts the required recovery/idempotence and atomic grouped persistence behaviour.

4. **Blocking - supersede identifiers are order-dependent rather than deterministic/idempotent.** `supersede` derives the replacement ID from total index length (lines 126-127), including unrelated records and prior retries. Repeating the same supersede request produced `entry-1-supersede-2` then `entry-1-supersede-3`, with two appended corrections. The required deterministic supersede contract is therefore not met.

5. **Blocking - the release-facing review report reintroduces the transaction-shaped vocabulary Task 4 is meant to replace.** `create_portfolio_review_report` emits `final_action` from the legacy action, `suggested_trade_value_eur` and a `proposals` collection (lines 36, 41 and 65). `SignalResult.to_v2_dict` explicitly documents that release serializers do not expose legacy action verbs. `AppState` also remains wired as `create_trade_proposal` through the deprecated adapter (state lines 368-373), and the adapter emits only a Python warning, not the required deprecation event. Literal execution denial is present, but the public report/caller migration acceptance criterion is incomplete.

6. **Blocking - journal read paths do not participate in the atomic grouped reader boundary.** `_read_index`, `get` and `list_entries` use independent direct file reads (lines 47-61 and 95-120), despite `core.atomic_io.read_atomic_group` being the contract that locks readers to one complete generation. Inference from the execution path: a concurrent reader can observe the payload/index activation gap and fail or return a mixed generation even though the writer uses `atomic_write_group`. No Task 4 test exercises interrupted group publication, recovery or concurrent generation reads.

7. **Blocking - required export contract metadata is incomplete.** Both `DecisionJournal.export_summary` (lines 140-146) and `evidence/governance/decision_journal_export_summary.json` contain a schema version but no policy version. The brief explicitly requires schema/policy version. Privacy is preserved in the inspected summary and operation record fields.

### Minor

1. `git diff --check` reports three trailing-whitespace lines in `evidence/governance/task4-full-suite.txt` and a new blank line at EOF in `tests/test_portfolio_review_reports.py`.

2. The committed tests cover payload checksum tampering and the hardened index checksum comparison, but not index-row schema, missing payload, traversal, grouped interruption/recovery, retry idempotence, operation-log failure, or deterministic repeated supersede. This allowed the blocking behaviours above to pass the focused suite.

## Evidence

- Observation: report and row outputs hard-code `execution_allowed=False` and `executable_authority=False`; report output also sets `broker_execution="not_supported"` and requires manual review.
- Observation: Task 3 typed state/gate metadata is read through `SignalResult.to_v2_dict`; however only the first signal's gate table is promoted to report-level metadata, while each row lacks its own gate table.
- Observation: index checksum tampering is now detected at `DecisionJournal.list_entries` lines 116-119 in head `f3e5091`.
- Observation: the committed file list contains no Task 5 UI, broker, order-routing or credential implementation.
- Observation: operational journal records contain only operation, ID, checksum and schema version; inspected export summaries contain no thesis or private notes.

## Commands or tests run

- Focused Task 4/proposal/atomic bundle: `pytest tests/test_portfolio_review_reports.py tests/test_decision_journal.py tests/test_trade_proposals.py tests/test_atomic_io.py -q --tb=short` - exit 0, **15 passed**, two expected deprecation warnings.
- Affected authority/migration/import-export/governance bundle: exit 0, **79 passed**.
- Fresh adversarial in-memory/temp-directory probe: reproduced missing-payload raw `KeyError`, malformed-index-row raw `KeyError`, non-deterministic repeated supersede IDs, path traversal persistence, and committed-create/log-failure retry non-idempotence.
- Scoped `compileall` - exit 0.
- Scoped Ruff - exit 0, `All checks passed!`.
- `git diff --check` - exit 2 with the four formatting findings above.
- Diff/symbol scope searches confirmed literal execution denial and no Task 5/broker/credential additions.

## Remaining uncertainty and risk

- No full-suite rerun was needed to establish rejection; the implementation report's full-suite capture is not used as proof for the uncovered persistence contracts.
- Concurrent activation/recovery risk is inferred from direct-read versus locked-reader code paths; a deterministic lifecycle-hook concurrency test should prove the corrected behaviour.
- Four generated schema-history files were already dirty outside the reviewed committed range and were not modified or attributed to Task 4.

## Recommended next action

Validate and contain journal IDs; convert all malformed/missing index and payload states to explicit integrity diagnostics; make the observable create/log operation failure-atomic and retry-idempotent; define content-derived deterministic supersede identity; read payload/index generations through the atomic grouped reader/recovery contract; remove transaction-shaped public report fields and migrate the app caller while retaining only the compatibility adapter; add policy-version export metadata and focused failure-injection tests; then rerun independent review.

**Verdict: reject with blocking findings.**
