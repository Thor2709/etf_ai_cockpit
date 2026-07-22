# B02-DATA-SPINE-CONTINUATION

## Run identity and authority

- `VERIFIED` repository: `Thor2709/etf_ai_cockpit`; exact initial base/main: `2eda82168314d582b94d0fbfc066e75327243fd2`.
- `VERIFIED` first control branch/worktree: `codex/b02-issue0082-ready-20260722` / `.worktrees/b02-issue0082-ready-20260722`.
- `VERIFIED` final-release specification SHA-256: `7a1d122e0bdbcb68dcd2b202a6f628f33718b2b9ae81cc2305649a7016d95810`.
- `VERIFIED` locked Python: `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-release-3262a46\Scripts\python.exe` (3.12.10).
- Root retains shared-contract, control-state, integration, commit, GitHub and merge authority. The scout is read-only. No live execution, release/tag publication or authority escalation is authorised; `execution_allowed=false` remains invariant.

## Dependency-closed outcome

`B03-FIXED-INCOME` remains blocked by ISSUE-0082/0083/0085. This continuation first establishes reviewed dependency interfaces, then implements ISSUE-0082's durable point-in-time global identity master. Historical `integrated` labels alone are not edge evidence.

The programme-control contract permits one authoritative transition for a record per base diff. Therefore readiness is deliberately serial:

1. `ISSUE-0082 planned -> ready` with `UPDATEV2-0011=partial_interface`.
2. On the freshly merged base, `ISSUE-0082 ready -> in_progress` with `ISSUE-0073=partial_interface`.

`partial_interface` is intentional: the existing resolver and bitemporal store satisfy the consumer contracts needed to implement ISSUE-0082 without falsely closing their broader upstream issues.

## ISSUE-0082 acceptance contract

- `B02-0082-AC1`: every provider/user row resolves deterministically or remains explicitly unresolved; identifiers are never invented.
- `B02-0082-AC2`: duplicates and critical conflicts remain quarantined with retained candidates, confidence, stable review identity and audit evidence.
- `B02-0082-AC3`: entity, issuer/guarantor, instrument/security/debt series, legal vehicle/umbrella/sub-fund, fund share class, listing/quotation/dealing channel and broker contract remain distinct typed objects.
- `B02-0082-AC4`: valid time, knowledge time, source priority and historical ticker/ISIN/broker/venue/lifecycle changes replay at the decision cut-off.
- `B02-0082-AC5`: multiple securities per issuer and multiple accumulating/distributing or hedged/unhedged share classes never collapse; share-class fees/currencies/returns remain distinct.
- `B02-0082-AC6`: persistence is local-first, append-only/atomic and concurrency-safe; migration preserves existing projections and fails closed on corruption or unsupported schema.
- `B02-0082-AC7`: the application facade and relevant Universe/Instrument surface expose graph, confidence, conflict, lineage and review state without presentation arbitration.
- `B02-0082-AC8`: identity remains research/read-only evidence; listings/broker contracts are explicit and `execution_allowed=false`.

## Ownership, frozen contracts and exclusions

Root owns ISSUE-0082. Initial product boundary: `src/etf_cockpit/data/instrument_identity.py`, one identity-master repository/storage module under `src/etf_cockpit/data/`, existing local storage/migration integration only where required, `src/etf_cockpit/data/trust_artifacts.py`, application facade/selector, smallest relevant UI exposure, and focused tests.

Freeze and reuse `BitemporalStore`, `IdentityClaim`, `IdentityObject`, `IdentityConflict` and resolver decision identity. Add durable schemas behind those contracts; do not create a second resolver.

Forbidden without re-plan: product writes during control prerequisites; control/status/generated programme files during feature implementation; unrelated scoring/model/portfolio/provider/broker code; provider network enablement; paid dependencies/cloud services; live authority; unrelated refactors; weakened unavailable/quarantine/test gates.

## Validation and evidence log

Control prerequisites require exact transition/edge guard, deterministic registry/status/completion freshness, registry validation, control tests, semantic diff, independent review, protected evidence-only PR and checksum-gated GitHub readback.

Product work follows regression-first contract tests, durable repository/migration, projection/facade/UI integration, corruption/concurrency/replay/adversarial fixtures, focused and affected regressions, architecture/authority checks, Ruff/compile/diff hygiene, independent full-diff review, protected full release and two-stage status convergence.

- `VERIFIED` UPDATEV2-0011/0021 feature PR `#465` and convergence PRs `#466`/`#467` merged; protected release and checksum-gated GitHub readbacks converged.
- `VERIFIED` mapping identified `BitemporalStore` and the point-in-time identity resolver as partial consumer interfaces, and confirmed ISSUE-0082 still lacks durable graph/storage/import/migration, complete object hierarchy, lifecycle persistence, adversarial fixture coverage and graph/override UI.
- `REVISE` a combined two-transition control attempt was rejected before generation/commit because authoritative control permits only one next transition per base diff. It remains isolated and unpushed.
- `IN_PROGRESS` first exact control step: planned-to-ready plus the UPDATEV2-0011 partial-interface edge only.
- `VERIFIED` the first generated control diff contains exactly ISSUE-0082 `planned -> ready` plus `UPDATEV2-0011=partial_interface`; all other records, edges, policies and execution authority remain unchanged. The fresh GitHub projection contains one open-issue status update for `ISSUE-0082` / `#222`, semantic SHA `0f8e216b0c3f27a6887f6d908bb3c30451dda82c41f689850d13c2dbef158c6a`.
- `REVISE` deep review found that the first edge-aware guard limited changes per issue but did not reject one reviewed edge change on each of multiple allowlisted issues. The current single-issue proposal did not exploit this, but the shared guard remained unsafe; a proposal-wide adversarial regression and maximum-one-edge gate are required before approval.
- `VERIFIED` the proposal-wide repair accumulates edge mutations across all allowlisted issues and rejects more than one. The reproduced two-issue bypass is now a passing adversarial regression; re-review passed with no new finding.
- `VERIFIED` the post-repair full control/completion set passes 111 tests; the real ISSUE-0082 guard, registry/status/completion freshness, registry validation, Ruff, compileall and `git diff --check` all pass. Structural comparison retains 197 records, changes only ISSUE-0082 and its one reviewed edge, and preserves `execution_allowed=false`.
- `VERIFIED` PR `#468` completed status guard `29875987254`, supply chain `29875987283` and full Linux/Windows release run `29875987270`, then merged as `5f7fc80e36cf685689cbea64cce16d9f1f8690a1`. The checksum-approved one-action GitHub plan `0f8e216b0c3f27a6887f6d908bb3c30451dda82c41f689850d13c2dbef158c6a` applied and readback `f839838e0701f7ab85eb1f5baca8d5aa06e29c608bede1d4e176820fe3e4d215` contained zero actions.
- `IN_PROGRESS` second serialized control step: ISSUE-0082 `ready -> in_progress` plus only `ISSUE-0073=partial_interface`. The fresh GitHub projection contains one open-issue status update for `ISSUE-0082` / `#222`, semantic SHA `9569934d90bb0d44ddb0d75a8f6d38d5c3fc33f5e012d1bf305b5e594e8f037e`; no other edge, status, dependency, policy or authority change is authorised.
- `VERIFIED` the second step passes the real edge-aware guard, deterministic generators, registry validation, 74 focused control tests, semantic comparison and `git diff --check`. Deep re-review passed with no finding: only ISSUE-0082 changes, both partial interfaces are explicit, readiness is `READY_BLOCKING_EDGES_RESOLVED`, and execution remains false.
- `VERIFIED` ISSUE-0082 now has a durable local identity master with exact point-in-time resolution, explicit unresolved/quarantine/review states, distinct typed entity/instrument/fund/share-class/listing/dealing/broker objects, immutable atomic persistence, migration/corruption/concurrency gates and read-only facade/UI projections. The reviewed checkpoint is `a7453703da83b0993490c587e3ac9eac532c8294` on base `f3c5521b8d7a78915c813e748917be3eb496fe4c`.
- `VERIFIED` focused and affected validation passes 93 tests; Ruff, scoped MyPy, compileall and `git diff --check` pass. Independent re-review found no remaining AC1-AC8 issue. Real Flet/browser evidence shows the Universe tier table, Secondary filter and VWCE Identity modal with resolved/high confidence, lineage fields and `execution_allowed=False`.
- `REVISE` PR `#470` supply-chain, package, smoke, performance, security, privacy and legal checks passed, but the first protected Linux/Windows release run `29879731066` correctly stopped on two integration gaps: the new Identity controls were absent from `configs/ui_acceptance.yaml`, and canonical generation metadata still referenced pre-merge base `5f7fc80e...` instead of current `origin/main` `f3c5521b...`.
- `VERIFIED` the Identity/Close acceptance metadata is now explicit and the focused button/accessibility/Universe suite passes 14 tests. The established no-transition control refresh now targets `f3c5521b...`; it retains all 197 records and statuses, projects zero GitHub actions with plan SHA-256 `7cc09799770bc7ceaa47ce5b1f1ae429164af08b322a0a7f8907e3b925882105`, and preserves `execution_allowed=false`.
- `VERIFIED` the refreshed real guard, registry validator and deterministic registry/status/completion checks pass. The combined product, storage, UI, architecture, authority and prior-failure regression set passes 154 tests; independent review found no issue, status, dependency, edge, policy, GitHub-action or authority drift.
- `IN_PROGRESS` a repair checkpoint and the updated protected PR `#470` release remain before merge. Canonical ISSUE-0082 status remains `in_progress` until post-merge two-stage convergence.
- `VERIFIED` repaired PR `#470` passed release run `29881056993` on Linux and Windows, status-transition guard and supply-chain, then merged exact reviewed head `21d8adb0c0e97abffaf271eaf022aa1ea53da187` as `d590c8fef1f645614e7ed326e60b31d823d54113`. Post-merge focused identity/instrument/Universe validation passes 42 tests.
- `IN_PROGRESS` first post-merge convergence advances only ISSUE-0082 `in_progress -> implemented_initially`. The generated GitHub projection contains one Programme-status update for open issue `#222`, semantic SHA-256 `86ca707fe74b67b8f6a62adaf2686b1a97034e336f529ad97f80b1c7548309de`; no other issue, dependency, policy, closure or execution-authority mutation is authorised.
