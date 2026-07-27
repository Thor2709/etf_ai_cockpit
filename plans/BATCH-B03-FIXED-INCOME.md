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

`VERIFIED` the ISSUE-0153→ISSUE-0082 edge-only PR #499 merged as `55e08b4ce116dd0ca71a9e5971bbae1877b417a6` from reviewed head `614d5659926b048d914186377950c40ebf470dc3`. Status guard run `29937238593` and supply-chain run `29937238509` passed; redundant evidence-only release run `29937238534` was cancelled under the cadence amendment. The GitHub plan remained the zero-action hash `6fa4e9740d6c7673cc8cf29ffd5a771ba25b40a4de204c074cdc3112cea5cfe8`.

`IN_PROGRESS` the second edge-only proposal records ISSUE-0153→ISSUE-0083 `unresolved -> complete` against the merged point-in-time `InstrumentContextV2`/`ClassificationStore` interface. ISSUE-0153 remains planned and ISSUE-0085 remains unresolved. Registry stays at 197 records with proposed SHA-256 `b4f316d512b3afe19ede6f730ccbebfeb9cf792285d4de792017cf4a4a690708`; its base registry SHA-256 is `1dfe1737e64aa9093500a73124cf0affdd1ef62fb0e7e6b0ee3888e37bb9ac59`. The cited product merge is `7aab4f2775e35b0af248c61f8b95930d6c50b781` and final convergence is `ad783e517be68882934300df73106891ae6e3c05`. GitHub projection remains the zero-action plan `6fa4e9740d6c7673cc8cf29ffd5a771ba25b40a4de204c074cdc3112cea5cfe8`. No scope, batch, dependency, acceptance, status, safety, product or authority change is authorised.

`VERIFIED` the ISSUE-0153→ISSUE-0083 edge-only PR #500 merged as `3ad445524eaea4945d305f8a5e39034fcd3e2b8e` from reviewed head `a3ff7201c5dae76148eadd040aa7632ea93638f7`. Status guard run `29937830034` and supply-chain run `29937826677` passed; redundant evidence-only release run `29937826447` was cancelled under the cadence amendment. Independent review found no material issue and the GitHub plan remained the zero-action hash `6fa4e9740d6c7673cc8cf29ffd5a771ba25b40a4de204c074cdc3112cea5cfe8`.

`IN_PROGRESS` the third edge-only proposal records ISSUE-0153→ISSUE-0085 `unresolved -> complete` against the certified market-calendar and schedule interface. ISSUE-0153 remains planned, now with all three blocking edges complete; its status will transition only in a later separately guarded step. Registry stays at 197 records with proposed SHA-256 `b564ff57dd8f35923befe365f82f7add0879ec122a2ac779d36fafc6c4875346`; its base registry SHA-256 is `b4f316d512b3afe19ede6f730ccbebfeb9cf792285d4de792017cf4a4a690708`. The cited product merge is `d7adefcb119bde9b8e4e8110e257d615b662873d` and final convergence is `aafc249121ff1e284979d384821ea8d84ba0bddf`. GitHub projection remains the zero-action plan `6fa4e9740d6c7673cc8cf29ffd5a771ba25b40a4de204c074cdc3112cea5cfe8`. No scope, batch, dependency, acceptance, status, safety, product or authority change is authorised.

`VERIFIED` the ISSUE-0153→ISSUE-0085 edge-only PR #501 merged as `7ce4fa53b1c5b8b6718b23766913cd9afd1bc2f9` from reviewed head `1ad0e3b2e39088c5e1a318ebe4ca091c585281cc`. Status guard run `29938381057` and supply-chain run `29938380714` passed; redundant evidence-only release run `29938380715` was cancelled under the cadence amendment. Independent review found no material issue and the GitHub plan remained the zero-action hash `6fa4e9740d6c7673cc8cf29ffd5a771ba25b40a4de204c074cdc3112cea5cfe8`.

`IN_PROGRESS` the separately guarded ISSUE-0153 `planned -> ready` proposal is now supported by all three reviewed blocking interfaces. It changes no dependency, scope, acceptance criterion, safety rule, batch composition, status semantics, product behaviour or authority. Registry remains 197 records with base SHA-256 `b564ff57dd8f35923befe365f82f7add0879ec122a2ac779d36fafc6c4875346` and proposed SHA-256 `1887ba4a3a49ca9bfc72de2ff2dc5f8f91a0da8592b80a9ae4462d34655caf4e`. The reviewed GitHub plan contains exactly one managed-field update for ISSUE-0153 remote #432, has semantic SHA-256 `b1bca95d822019f7db568900fd61f49a46ad5a9617ecbeadba8e9274b823f8f8`, keeps the issue open and preserves `execution_allowed=false`.

`VERIFIED` the ISSUE-0153 `planned -> ready` PR #502 merged as `5a6766c3a7520299cc2c058455ddcd7b2993dc8e` from reviewed head `86f22d45974b113ef5f3fbb94505528ba10f3772`. Status guard run `29938857585` and supply-chain run `29938857397` passed; redundant evidence-only release run `29938857842` was cancelled. GitHub plan `b1bca95d822019f7db568900fd61f49a46ad5a9617ecbeadba8e9274b823f8f8` applied and verified #432 open/ready with `execution_allowed=false`; final readback plan `1d4df855195795e3e7f467ab113019b643bd0e7da65da2e06e6e5a6ec9023f43` had zero actions.

`IN_PROGRESS` the separately guarded ISSUE-0153 `ready -> in_progress` hand-off proposal changes only that canonical status. Registry remains 197 records with base SHA-256 `1887ba4a3a49ca9bfc72de2ff2dc5f8f91a0da8592b80a9ae4462d34655caf4e` and proposed SHA-256 `150e7fc892876c27c779ca7e0cea6405375c19c2e842ed03a5ac75e3a131546b`. The reviewed GitHub plan contains exactly one open managed-field update for #432 with semantic SHA-256 `7017bd659ed789ed9438068077c9b9bcf13728b1369661b1258f535faa949f6b`; no product, dependency, scope, acceptance, safety, batch or authority change is authorised, and `execution_allowed=false` remains binding.

`VERIFIED` the ISSUE-0153 `ready -> in_progress` PR #503 merged as `95e3fadd4dc773214881a0e7f2a5b3eeaf28d9da` from reviewed head `8fa01f752ce79a7e79865c22620b34d6fdbbd480`. Status guard run `29939369685` and supply-chain run `29939369793` passed; redundant evidence-only release run `29939369772` was cancelled. GitHub plan `7017bd659ed789ed9438068077c9b9bcf13728b1369661b1258f535faa949f6b` applied and verified #432 open/in_progress with `execution_allowed=false`; final readback plan `217cd7f3ec152ac0c337ee390ab42d26aa5c8bd398f93b6e575ac082b563d2d4` had zero actions.

`BLOCKED` the ISSUE-0153 implementation lane stopped after the repository's two-repair limit. Initial checkpoint `30bf0ab6283656a8543f4179451e856903e851bc`, first repair `febaaaa0f358c35f31a8ace88d6b7a0a600bb4a7` and second/final repair `937d5b9de156ab29f3cc559834099f49496cccd2` were never pushed or merged. The decisive independent re-review reproduced two protected identity-contract blockers: `IdentityMasterStore.append_claims` discards retrieval chronology and accepts changed retrieval timestamps as idempotent, causing point-in-time look-ahead; and identity decision hashes changed while still declaring schema version 1, risking incompatible audit comparisons. No third repair, product PR or protected Linux/Windows release gate is authorised in this run. Reviewer-created SQLite artifacts were removed exactly and the product worktree is clean. Canonical ISSUE-0153 remains `in_progress` because the existing status machine permits only `implemented` or `implemented_initially` from that state; no status-semantic change or unauthorised downgrade is made. ISSUE-0154 through ISSUE-0156 remain dependency-blocked, batch composition is unchanged, and `execution_allowed=false` remains binding.

## 2026-07-27 restart

`VERIFIED` the separate identity-contract prerequisite merged through PR #507 as
`e3fbf152165a0686bd42429c4cd90a3ca982974a`. Retrieval observations are now
immutable and point-in-time filtered, exact duplicate appends remain
idempotent, legacy decision-hash v1 replay is golden-tested, and retrieval-aware
decisions use schema v2. The protected Linux/Windows package builds, parity,
packaged smoke and safety checks passed; the only full-suite failures exactly
matched the retained `main` baseline.

`IN_PROGRESS` ISSUE-0153 restarts from that merged SHA in a fresh worktree.
The smallest usable outcome remains fixed-rate and zero-coupon terms, validated
contractual schedules, point-in-time corrections/conflicts, read-only
application/UI projection and audit lineage. Unsupported structures fail
closed. Fixed-income pricing, expected returns, provider adapters, risk models,
portfolio analytics, broker writes and live orders remain excluded.

`VERIFIED` one `sol_worker` implemented the bounded terms-master contract and
root reviewed the complete diff. Historical projections expose only versions
known and retrieved by the requested cutoff; persisted classification
disagreements, source conflicts, unsupported structures and uncertified
calendars quarantine schedules; immutable concurrent versions and exact
duplicate retries are retained deterministically. Fresh local evidence is 223
targeted identity, classification, fixed-income, application, Instrument
Detail, calendar/property and UI-contract tests passing. Ruff, compile, diff
checks and scoped MyPy for the new contract pass. No pricing, provider, risk,
portfolio or execution scope is included and `execution_allowed=false`.

Next action: checkpoint the reviewed branch, open its feature PR and require
the full protected Linux and Windows packaged gate before merge or status
transition.

`VERIFIED` product PR #508 preserved reviewed head
`33f4eb01a20fbeba6019b3aef974df7f0a003d8f` and merged as
`4e1d2d819e0c99d5f9f109f1494db7352365916e`. Protected run `30232472307`
completed the Linux and Windows package, parity, packaged smoke, performance,
source, cache, security, privacy, legal and SBOM checks; supply-chain run
`30232472248` passed. The 19 full-suite failures on each platform exactly
matched protected `main` baseline run `30229667416`: 18 stale-generation
control/registry failures and the unchanged classification-score invalidation
assertion. No ISSUE-0153 test or current-feature gate failed.

`IN_PROGRESS` the separate evidence-only convergence advances only ISSUE-0153
`in_progress -> implemented_initially` against the merged product and protected
evidence. The registry remains 197 records with proposed SHA-256
`0e6c851624d3375fd6e9d41301dca6348fb5496099eca6989e379d2773a9484d`.
The reviewed GitHub plan contains exactly one managed update for open issue
#432 with semantic SHA-256
`62d1eb324239be687583c4bd375b362fb9987867dc0c341d76dc3697c7590f49`;
`execution_allowed=false`, scope, dependencies, acceptance criteria and batch
composition remain unchanged.

`VERIFIED` the deterministic convergence review found no unrelated status,
scope, dependency, edge-evidence or authority mutation. The status guard,
registry validation and all generation/freshness checks pass; 60 focused
control, registry, tracker, programme-map and UI tests pass; the committed
safe GitHub evidence identifies only ISSUE-0153's Programme status field.

`VERIFIED` evidence-only PR #509 merged the implemented-initially convergence
as `b54d8a3d7a76c3154d4e0a06eaf75e88cf45223a`. Status guard run
`30233674450` and supply-chain run `30233674446` passed; redundant release run
`30233674447` was cancelled under the evidence-only policy. Checksum-approved
GitHub plan `62d1eb324239be687583c4bd375b362fb9987867dc0c341d76dc3697c7590f49`
applied and verified #432 open/implemented_initially with
`execution_allowed=false`; final readback plan
`7a0a444289d8c8a5e4eb355b961c01a42432b6ec1d649af2a899d73330c23f65`
contained zero actions.

`IN_PROGRESS` final convergence advances only ISSUE-0153
`implemented_initially -> integrated`. The regenerated 197-record registry has
SHA-256 `c10fd8a55673f2553abfb400e587a18923936200d013d6d5b133651407a6ab95`;
the reviewed GitHub plan contains exactly one Programme status update for open
#432 with semantic SHA-256
`775d533889453d59f415010a23731adcac8cbdc4ac8b8265a28571b8ce6f0f70`.
No product, test, dependency, workflow, scope, acceptance, safety or authority
change is included.

`VERIFIED` final evidence-only PR #510 merged ISSUE-0153 as integrated in
`fb0f21a36a805b4c45053bc7eab42329522f91cf`. Its status guard and
supply-chain checks passed; the checksum-approved GitHub update applied and
read back with zero actions. ISSUE-0153 and remote #432 are integrated and
`execution_allowed=false`.

`IN_PROGRESS` the first ISSUE-0154 readiness review records only the
ISSUE-0154→ISSUE-0153 edge `unresolved -> complete` against the integrated
`fixed-income-terms.v1` contract. ISSUE-0154 remains planned; ISSUE-0085 and
ISSUE-0088 remain unresolved. The regenerated 197-record registry has SHA-256
`709fb35513e9968e570a0c520e9bc60c3446525e4cc8529cc2468c5f57473fb3`;
the GitHub projection is the zero-action plan
`66bec5f128c60b6158f0cca36aae0464f01cb12a092206c97945b66e0ee29c66`.
No product, pricing, dependency-list, scope, acceptance, safety, status or
authority change is authorised.

`VERIFIED` edge review confirmed the integrated terms contract supplies the
schedule, point-in-time, lineage and quarantine inputs required by ISSUE-0154
without granting valuation or execution authority. The control helper test now
constructs its own unresolved edge precondition instead of depending on live
canonical state. Guard, freshness, registry validation, 60 focused tests, Ruff
and diff hygiene pass. Because a test file changes, this PR follows the full
protected release path rather than the evidence-only fast path.
