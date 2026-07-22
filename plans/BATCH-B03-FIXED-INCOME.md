# B03 Fixed Income

## Authority and fixed composition

Base revision: `040447418c401112c6d6c74c3e2527d62054654f` (`origin/main`). The clean worktree contains no `PLAN_step2.md` or `PLAN_step3.md`; they are not reconstructed. Authority remains the applicable instructions, canonical 2026-07-21 implementation specification, registry, current status, merged evidence and accepted contracts.

Batch composition is unchanged: ISSUE-0153, ISSUE-0154, ISSUE-0155 and ISSUE-0156, with the associated ISSUE-0110/ISSUE-0111 interfaces. `execution_allowed=false` throughout. Unsupported structures, missing terms, unknown risk and unavailable provider evidence remain explicit and blocking.

## Sequencing and ownership

ISSUE-0153 is the only dependency-ready product lane after its three already-merged dependency interfaces are reviewed. Its terms, schedule and persistence contract is the initial critical writer. ISSUE-0154 remains serial behind the frozen ISSUE-0153 contract and existing ISSUE-0088 interface. ISSUE-0155 adapters remain read-only mapping until the shared observation contract and all licence/provider edges are reviewed. ISSUE-0156 remains behind 0154/0155 and the existing 0091/0111 risk interfaces.

Root owns programme control, frozen shared contracts, integration, generated evidence, PRs, merges and GitHub sync. One primary product owner will own ISSUE-0153 in an isolated worktree after readiness converges. A shared read-only mapper/reviewer may map all four issues and associated risk interfaces; downstream adapters and risk writers begin only when their dependencies and file ownership are disjoint.

## Validation cadence amendment

Every lane receives focused tests, Ruff, scoped type/compile checks, affected integration/UI checks, registry/status guards and independent review. Evidence-only edge/readiness/status PRs use deterministic guards and supply-chain checks and reuse the latest protected full-gate evidence. ISSUE-0153 product work will trigger an immediate complete Linux/Windows gate because it introduces shared terms/schedule contracts, persistence and canonical financial cash-flow calculations. Final batch acceptance and B13 certification remain unchanged.

## Wave 0 evidence

`VERIFIED` ISSUE-0082, ISSUE-0083 and ISSUE-0085 are integrated. ISSUE-0153 remains `planned`; its three registry edges were imported as unresolved, so each must be reviewed and merged separately before `planned -> ready` and `ready -> in_progress`.

`IN_PROGRESS` the first edge-only proposal records ISSUE-0153→ISSUE-0082 `unresolved -> complete` against the merged point-in-time identity master. ISSUE-0153 remains planned; ISSUE-0083 and ISSUE-0085 remain unresolved. Registry stays at 197 records with SHA-256 `1dfe1737e64aa9093500a73124cf0affdd1ef62fb0e7e6b0ee3888e37bb9ac59`; GitHub projection is the zero-action plan `6fa4e9740d6c7673cc8cf29ffd5a771ba25b40a4de204c074cdc3112cea5cfe8`. No scope, batch, dependency, acceptance, status, safety, product or authority change is authorised.

`VERIFIED` shared read-only mapping freezes the existing contract paths: `IdentityMasterStore` and `resolve_identity`; `InstrumentContextV2`/`ClassificationStore`; `MarketCalendarService` settlement, business-day and day-count evidence; `BitemporalStore` point-in-time revisions; `SourceAuthority`/source-conflict resolution; application facade/API and Instrument Detail selectors. No fixed-income terms, pricing, provider or risk module currently exists. ISSUE-0153 owns the first frozen terms/schedule contract; 0154 analytics, 0155 adapters and 0156 common-risk integration remain staged and disjoint. QuantLib/Strata or any other production dependency requires separate licence/security authority and is not introduced by this control step.

`VERIFIED` independent edge review passed with no material finding. The cited ISSUE-0082 merge and exact identity/PIT/persistence evidence exist; only the reviewed edge changes, with 197 records, ISSUE-0153 status/scope/criteria/dependencies, remaining edges and `execution_allowed=false` preserved. Manifest and zero-action hashes recompute exactly, and guard, 77 focused tests, freshness, supply-chain and diff checks pass.
