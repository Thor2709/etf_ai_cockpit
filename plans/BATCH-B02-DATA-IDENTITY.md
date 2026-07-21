# BATCH-B02-DATA-IDENTITY

## Objective and authority

Deliver the smallest dependency-valid B02 foundation: a point-in-time identity resolver and a context-aware canonical metric conflict resolver. The observable outcome is that historical identity and metric claims are selected deterministically from evidence available at the decision time, while ambiguity, conflicts and later revisions remain explicit and auditable.

Selected records:

- `UPDATEV2-0011` — Symbol/ISIN/exchange identity resolver.
- `UPDATEV2-0021` — Source conflict resolver and canonical metric selector.

`ISSUE-0082` and `ISSUE-0088` are mapped but not selected. Their canonical dependency-edge evidence is unresolved; an upstream `programme_status` is not substituted for edge evidence. The remaining B02 records are likewise outside this slice until their exact blocking edges are resolved.

No live execution, broker write, cloud upload, paid mandatory provider, dependency upgrade, registry/status transition or GitHub mutation is part of implementation. `execution_allowed=false` remains invariant.

## Start-of-run evidence

- Repository: `Thor2709/etf_ai_cockpit`.
- Verified base: `origin/main` = `b1bddeecd0d8d4897f717932b10155f761d561cc` after PR `#463`; no open PRs.
- Worktree: `.worktrees/b02-data-identity-20260722`; branch `codex/b02-data-identity-20260722`; clean at selection.
- The primary checkout is user-dirty and remains untouched.
- `PLAN_step2.md` and `PLAN_step3.md` are absent from the clean base. The untracked primary-checkout `PLAN_step2.md` references old base `16ed8bf` and is `STALE`; it is not imported or reconstructed.
- Applicable repository instructions: `AGENTS.md`, SHA-256 `bd899b98a9769c02201261442d3b778bb6c6383f18beac6eeaff8ff6eb50efd9`; no nearer instruction applies to owned paths.
- Final implementation specification SHA-256: `7a1d122e0bdbcb68dcd2b202a6f628f33718b2b9ae81cc2305649a7016d95810`.
- Goal-objective SHA-256: `ac5263116a3f5bd7f933cf21cbcc4ff7ceaa4a2534e6b250eff9d156b5116904`.
- Codex config SHA-256: `1e86165b29c7b9ef1708a7832f1105478b0a3a6eb99adb7b9eadfc42234544e7`; routing is `gpt-5.6-sol`, high reasoning, medium verbosity, max 10 threads/depth 2. The Windows app denied direct `codex --version` execution; the installed package path identifies build `26.715.8383.0`. This environment fact does not affect repository validation.
- Locked Python: `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-release-3262a46\Scripts\python.exe`, Python 3.12.10.
- Canonical current status: 197 records; `UPDATEV2-0011` and `UPDATEV2-0021` are `in_progress`, release-blocking, and ready with no blocking edges; `execution_allowed=false`.

## Current-state and NO_CHANGE gate

`NO_CHANGE` is not claimed.

- `VERIFIED` `instrument_identity.py` deterministically orders claims by authority, retains conflicting values and supports flat MIC/share-class/listing/provider symbols. It does not model valid/availability/revision time, historical aliases/events, stable object kinds/relationships, point-in-time replay or a typed quarantine/review result.
- `VERIFIED` `source_conflicts.py` retains claims and orders by authority/source/value, but ignores period, unit, currency, restatement, availability, freshness and confidence during arbitration. It has no tolerance policy, fail-closed context validation, point-in-time revision selection or typed downstream invalidation identity.
- `VERIFIED` the initial narrow suite passes 11 tests across identity, conflict and macro warehouse. Existing green tests establish compatibility, not completion.
- `VERIFIED` `ISSUE-0088` has an initial bitemporal local warehouse, but amended curve/benchmark work is blocked by unresolved canonical edges. `ISSUE-0082` remains blocked by `ISSUE-0073` and `UPDATEV2-0011` edge evidence.

## Acceptance criteria

### UPDATEV2-0011

- `B02-0011-AC1`: every identity claim has a stable object/identifier namespace, source identity, valid interval, availability/knowledge timestamp and revision; ambiguous availability is rejected for point-in-time use.
- `B02-0011-AC2`: resolution at an explicit decision time is deterministic and excludes future-known claims and superseded revisions while retaining every candidate for audit.
- `B02-0011-AC3`: ticker, ISIN, MIC, exchange and provider-symbol changes replay historically without collapsing issuer, instrument, fund/share-class or listing identities; unsupported/ambiguous matches return quarantined/manual-review states.
- `B02-0011-AC4`: conflicts and manual resolutions have stable IDs, typed reason codes and immutable lineage. A manual decision cannot silently erase candidates or acquire execution authority.
- `B02-0011-AC5`: the application-facing identity/trust projection exposes resolution state, decision time, lineage/conflict IDs and historical identifiers without presentation-layer arbitration. Existing callers remain compatible through an explicit legacy adapter/default decision-time path that cannot be used for historical analysis.
- `B02-0011-AC6`: multi-listing, non-collapse, future-knowledge exclusion, ticker/ISIN history, corporate-event lineage, ambiguity, deterministic ordering and existing compatibility tests pass.

### UPDATEV2-0021

- `B02-0021-AC1`: metric claim identity includes instrument, canonical field, period, unit, currency, restatement/revision, valid/as-of time, availability time and source identity. Missing comparison context is explicit and cannot be treated as agreement.
- `B02-0021-AC2`: a versioned metric policy defines authority and absolute/relative materiality tolerances. Only comparable candidates are arbitrated; incompatible period/unit/currency contexts are retained and quarantined, never pooled or zero-filled.
- `B02-0021-AC3`: point-in-time selection excludes future-known revisions, respects restatements and freshness policy, retains all candidates, and produces stable decision/conflict/policy IDs plus explicit pass/warn/quarantine/block state.
- `B02-0021-AC4`: reviewed manual resolution is typed, versioned and auditable; it cannot delete source evidence or bypass a block. Changed canonical selection produces a deterministic downstream invalidation token.
- `B02-0021-AC5`: the application/trust projection exposes selected source, candidate coverage, context, tolerance, conflict state/reason and decision identity while remaining advisory with `execution_allowed=false`.
- `B02-0021-AC6`: period/unit/currency separation, tolerance boundary, future revision, restatement, stale/conflicted/missing context, manual review, deterministic ordering, compatibility and audit projection tests pass.

## Frozen contracts and sequencing

1. Freeze identity/metric claim timestamps, identifiers, enums, stable hashes and error semantics in tests.
2. Extend `instrument_identity.py` first. Existing flat `CanonicalIdentity` construction stays source-compatible; historical resolution is explicit and typed.
3. Extend `source_conflicts.py` against the frozen identity/time contract. Do not duplicate `BitemporalStore`; reuse its timestamp/decision-time semantics where persistence is required.
4. Add application/trust projections only after domain contracts pass. Presentation reads a facade/projection and never selects evidence locally.
5. Run affected integration and independent review before checkpoint. Registry/control/generated evidence changes occur only after merged executable evidence in a separate convergence step.

The slice is serial because both records share the `data-and-evidence` write group and their time/identity contracts interact. Root is the sole writer. The shared scout is read-only and is closed after hand-off; a shared test or diagnosis role is staged only for a concrete independent boundary or unexplained failure.

## Ownership and conflicts

Initial owned paths/symbols:

- `src/etf_cockpit/data/instrument_identity.py`
- `src/etf_cockpit/data/source_conflicts.py`
- `src/etf_cockpit/data/fundamentals.py` only to replace its duplicate metric-level authority selection with the frozen canonical conflict resolver
- narrowly required application/trust projection symbols in `src/etf_cockpit/data/trust_artifacts.py` and an application facade/selector if acceptance needs them
- `src/etf_cockpit/application/ui_facade.py` and `src/etf_cockpit/app/selectors/instrument_detail.py` only for a read-only identity evidence projection; presentation may not arbitrate claims
- `tests/test_instrument_identity.py`, `tests/test_source_conflicts.py`, and new narrowly named contract/projection tests where clearer
- this batch plan

Forbidden during implementation: `issues/issue_registry.json`, `issues/programme_control_state.json`, generated completion/status/reconciliation files, GitHub issues, broker/order/live authority, B02 downstream provider/warehouse implementation and unrelated refactors. Shared storage schemas/migrations require a separate reviewed decision before editing.

## Validation

Test-first focused checks:

```text
python -m pytest -q tests/test_instrument_identity.py tests/test_source_conflicts.py
python -m pytest -q <new point-in-time identity/conflict/projection tests>
python -m pytest -q tests/test_trust_artifacts.py tests/test_instrument_detail.py tests/test_task19_instrument_detail.py
python -m ruff check <changed Python paths>
python -m compileall -q src scripts
python scripts/validate_issue_registry.py
python scripts/generate_issue_registry.py --check
python scripts/update_programme_status.py --check
python scripts/generate_completion_documents.py --check
git diff --check
```

After focused integration, run affected data/bitemporal/parser/application/authority tests and one proportionate broader gate. A failing check is run once; only a named documented flake may be retried once. Test assertions, thresholds, authority gates and unavailable states are not weakened.

## Rollback and stop conditions

Rollback is one logical checkpoint per selected issue; no migration is activated until compatibility and recovery are proven. Stop the affected lane for changed `origin/main`, an unowned shared-schema need, a material source conflict, look-ahead, identity collapse, silent unit/currency/period coercion, candidate loss, invented identifier, unknown evidence treated as agreement, execution-authority expansion, mandatory network/key dependency, secret exposure, generated hand edit, or two non-improving repairs. Record the exact blocker and continue only independent ready work.

## Progress

- `VERIFIED` B01 completed and converged: PR `#463` merged as `b1bddeecd0d8d4897f717932b10155f761d561cc`; managed GitHub readback is zero actions; ISSUE-0008 and ISSUE-0037 are integrated.
- `VERIFIED` B02 start gate, canonical readiness correction, source/spec intake and shared read-only map are complete.
- `IN_PROGRESS` UPDATEV2-0011 contract/reproduction tests are next.
- `PENDING` UPDATEV2-0021 follows the frozen identity/time contract.
- `BLOCKED` ISSUE-0082, ISSUE-0088 and remaining B02 records retain their canonical unresolved dependency edges.
- `VERIFIED` regression-first contracts failed at collection before implementation because point-in-time identity and context-aware metric types did not exist. The final focused identity/conflict/fundamentals set passes 44 tests.
- `VERIFIED` the canonical conflict resolver now owns real fundamentals arbitration; period/unit/currency contexts do not pool, future restatements remain excluded until known, stale/low-confidence/model-only facts fail closed, manual choices retain candidates, and deterministic invalidation identity changes with evidence.
- `VERIFIED` atomic trust artifacts and the application facade expose identity decision, object/history, policy, conflict and no-execution evidence. The affected UI/architecture/authority set passes 116 tests; SEC/parser compatibility passes 28; trust artifacts pass 24; macro/bitemporal compatibility passes 9.
- `VERIFIED` Ruff on every changed Python path, compileall and `git diff --check` pass. Generated decision-journal test output was moved outside the worktree to `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-b02-generated-decision-journal-20260722`.
- `VERIFIED` the no-transition base-refresh prerequisite passed independent review and evidence-only protected gates, then merged through PR `#464` as `6c369800e04b3e7d8ce3adda792cc4a82c91b7e9`; its fresh GitHub readback contained zero actions.
- `REVISE` independent product review rejected the first implementation checkpoint with five reproduced blockers: future review knowledge changed historical identity/metric decisions; a review could promote a stale metric candidate; point-in-time metric comparison omitted valid/as-of/restatement context; fundamentals discarded incompatible candidates through first-source anchoring; identity decision/projection omitted reviewed selection and conflict IDs.
- `VERIFIED` ten regression assertions covering the five review findings failed before repair. After one bounded repair, identity and metric reviews are knowledge-time filtered, review selection participates in decision identity, quality-ineligible candidates cannot be promoted, comparison/audit identity includes as-of/validity/restatement lineage, fundamentals retain all valid source contexts without a first-source anchor, and application projections expose identity conflict IDs.
- `VERIFIED` repaired focused groups pass: source-conflict/fundamentals 39; identity/detail/trust artifacts 49; UI/architecture/authority/execution boundary 116; SEC/parser 28; macro/bitemporal 9. Ruff, compileall and `git diff --check` pass. The first macro command used a stale nonexistent test filename after the SEC group passed; the corrected canonical test path ran once and passed.
- `IN_PROGRESS` independent re-review of the repaired complete diff is next. No other product or control scope is authorised.
- `REVISE` the first re-review confirmed all five original blockers repaired but reproduced three further bounded gaps: divergent equal-revision reviews were input-order-dependent, fundamentals invented generic source IDs and collapsed unidentified candidates, and trust artifacts counted unique sources instead of candidate claims.
- `VERIFIED` the four new regression nodes failed before the second repair and pass afterward. Divergent equal revisions now fail closed in either order, unidentified source claims remain distinct and block canonical use, and each metric conflict carries its actual candidate count into persisted trust evidence. The complete identity/conflict/fundamentals/trust set passes 78 tests; Ruff, compileall and `git diff --check` remain green.
- `IN_PROGRESS` final independent re-review of the complete repaired diff is next. The product worktree remains frozen during review.
- `VERIFIED` final independent re-review passed with no finding and mapped all UPDATEV2-0011/0021 acceptance criteria green.
- `VERIFIED` reviewed checkpoint `c379e6ee88e940383cc8732f27556f23ddcbb342` was transplanted without conflict onto fresh `origin/main` `6c369800e04b3e7d8ce3adda792cc4a82c91b7e9` as integration commit `e5e89d4145f97c47e020fe32960f26194fec8732` on branch `codex/b02-data-identity-pr-20260722`.
- `IN_PROGRESS` root is regenerating no-transition canonical control/reconciliation evidence against the fresh base before post-transplant validation and protected PR release.
- `VERIFIED` post-transplant validation on the final branch passes: product/domain/application/trust 92 tests, control/registry/completion 100, and UI/architecture/authority/execution boundary 116. Canonical generation, registry validation, status/completion freshness and the exact no-transition guard pass against base `6c369800e04b3e7d8ce3adda792cc4a82c91b7e9`; all 197 records, statuses, dependencies and policies are unchanged and the fresh GitHub plan has zero actions with semantic SHA `54fa6c686ade3c20e100e5d9e9c74f1ae3dc034b14e5d7081aee20b41f2cbb9d`.
- `IN_PROGRESS` final static checks, mechanical evidence commit and protected PR gates remain before merge; no status transition or GitHub issue mutation is included in the feature PR.
- `VERIFIED` PR `#465` passed the status guard, supply-chain scan and full protected release gate on Linux and Windows, then merged the exact reviewed head as `1e9efbcd3ea67fec638d95905a66af063952dd8c`.
- `IN_PROGRESS` the first post-merge convergence advances only UPDATEV2-0011 and UPDATEV2-0021 from `in_progress` to `implemented_initially` with verified merge/review/release evidence. Registry count remains 197; the fresh GitHub projection contains exactly two Programme-status updates for issues `#151` and `#161`, semantic SHA `9133bbd109c1b2da871e19b5079b41f1b61d9acd057ac9f859dc99fa48bef221`. No addition, removal, closure, dependency, policy or execution-authority change is authorised.
- `VERIFIED` PR `#466` passed status-transition guard `29874356182` and supply-chain run `29874356193`, then merged the exact reviewed 35-file evidence head as `3f3aa361bb09d44edcd65d3184f835d06e996682`. The checksum-approved two-action GitHub plan `9133bbd109c1b2da871e19b5079b41f1b61d9acd057ac9f859dc99fa48bef221` applied and fresh readback `1419344b2f8eb58bc73c3e116ff6584ff0a0b9a54a197d990b51b5db64e85481` contained zero actions.
- `IN_PROGRESS` the final B02 convergence advances only UPDATEV2-0011 and UPDATEV2-0021 from `implemented_initially` to `integrated`. Registry count remains 197; the fresh GitHub projection contains exactly two Programme-status updates for issues `#151` and `#161`, semantic SHA `1896f861d0a409cc6e7e995a5f82dcdc2d15eba437418e5d8fa6bede0a672b13`. No closure, dependency, policy or execution-authority change is authorised.
- `VERIFIED` final-convergence validation passes: exact status guard, registry validation, registry/status/completion freshness, `git diff --check`, 108 control/completion tests and structural comparison of all 197 records. Independent read-only review passed with no blocking finding; it noted only inherited generated wording that labels the generic sync review as B00 evidence, while the machine-readable B02 scope, checksums and actions are correct.
