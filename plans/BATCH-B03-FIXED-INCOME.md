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

`VERIFIED` PR #511 merged the ISSUE-0154→ISSUE-0153 readiness edge as
`bc2e8ad35ad4989056abe24528a04374dcf48c3c`. The full protected Linux and
Windows jobs passed every package, parity, smoke, policy and safety check; each
full suite retained only the exact existing simple-score baseline failure.
The reviewed head, changed-file allowlist and absence of comments or reviews
were unchanged at merge. ISSUE-0154 remains planned and
`execution_allowed=false`.

`IN_PROGRESS` the second ISSUE-0154 readiness review records only the
ISSUE-0154→ISSUE-0085 edge `unresolved -> complete` against the integrated
`market-calendar.v1` service. The contract supplies distinct settlement
calendar evidence, business-day and coupon/ex-date adjustment, declared
day-count conventions and point-in-time correction lineage. ISSUE-0154
remains planned and ISSUE-0088 remains unresolved. The regenerated 197-record
registry has SHA-256
`4dc9a08f949b1fca10577a8006ea3b1ac2f0413f412a0daedddd8dc0ee49739e`;
the GitHub projection is the zero-action plan
`66bec5f128c60b6158f0cca36aae0464f01cb12a092206c97945b66e0ee29c66`.
No product, pricing, dependency-list, scope, acceptance, safety, status or
authority change is authorised.

`VERIFIED` the edge review confirms the integrated calendar service supplies
the exact deterministic settlement, adjustment, day-count and correction
inputs required by ISSUE-0154. The control-plane readiness test now selects
the intended ISSUE-0153 edge by dependency ID instead of relying on edge
ordering as more edges become resolved. Guard, registry and generated-document
freshness pass; 143 focused control, programme, market-calendar and UI tests
pass in a fresh Python 3.12 dependency environment. Ruff and diff hygiene
pass. Because a test file changes, this PR requires the full protected Linux
and Windows release path rather than the evidence-only fast path.

`VERIFIED` PR #512 merged the ISSUE-0154→ISSUE-0085 readiness edge as
`575ec0ab7c7e86f066c763022ea2dfaf397dd53d`. Protected run `30235711228`
passed package build/artifacts, source-package parity, packaged smoke,
performance, source, cache, security, privacy, legal, SBOM and per-job
supply-chain checks on Linux and Windows. Each full suite retained only the
exact simple-score baseline failure; status guard `30235711192` and
supply-chain run `30235711169` passed. ISSUE-0154 remains planned and
`execution_allowed=false`.

`IN_PROGRESS` the final ISSUE-0154 readiness review records only the
ISSUE-0154→ISSUE-0088 edge `unresolved -> partial_interface`. The reviewed
contract supplies bitemporal, currency/unit-labelled risk-free and benchmark
observations, checksums, transformation versions and decision-time retrieval.
It does not claim a certified tenor, spot/par/forward curve or interpolation
contract; ISSUE-0154 must require explicit typed curve inputs and keep missing
or ambiguous curve evidence unavailable or quarantined. ISSUE-0154 remains
planned. The regenerated 197-record registry has SHA-256
`e254390f58be6fdd376d32e5ef9677088019fdda0fb0a1f3df4b23e7df789501`;
the GitHub projection is the zero-action plan
`66bec5f128c60b6158f0cca36aae0464f01cb12a092206c97945b66e0ee29c66`.
No product, dependency-list, scope, acceptance, safety, status or authority
change is authorised.

`VERIFIED` the partial-interface review found no curve-tenor or interpolation
claim in the existing source and therefore preserves that limitation
explicitly. Decision-time vintage selection excludes later revisions;
transformations retain source observation IDs and versions; missing
country/currency context is explicit; execution authority remains false.
Guard, registry and generated-document freshness pass, and 123 focused
control, programme, bitemporal, macro-warehouse and UI tests pass. Diff hygiene
passes. Because only deterministic dependency evidence and generated
programme artifacts change, this proposal qualifies for the evidence-only
fast path.

`VERIFIED` PR #513 merged the bounded ISSUE-0154→ISSUE-0088
`partial_interface` edge as
`75e30d4e7851e7fdb557a249e1d676fc7e72db37`. Status guard `30236950713`
and supply-chain run `30236950750` passed; redundant release run
`30236950689` was cancelled under the evidence-only policy. The reviewed
head, deterministic file allowlist, explicit curve limitations and
`execution_allowed=false` were unchanged at merge.

`IN_PROGRESS` the separately guarded ISSUE-0154 `planned -> ready` proposal
is supported by all three reviewed blocking interfaces. It preserves the
ISSUE-0088 partial-interface limitation and changes no dependency, scope,
acceptance criterion, safety rule, batch composition, status semantics,
product behaviour or authority. The 197-record registry has base SHA-256
`e254390f58be6fdd376d32e5ef9677088019fdda0fb0a1f3df4b23e7df789501`
and proposed SHA-256
`563b68f4b8785e1a0371c16e4a71406fc10a2d1c4fba979af9a928d37aedbfac`.
The reviewed GitHub plan contains exactly one managed Programme status update
for open remote #433, has semantic SHA-256
`5ef0d541a3d3998b5f37bcf5d05474fa29f444f1b670087acdb53394424aeaf3`,
and preserves `execution_allowed=false`.

`VERIFIED` the readiness transition and exact one-action GitHub projection
pass guard, registry and generated-document freshness checks. Control tests
now construct their own planned ISSUE-0154 fixture instead of inheriting live
canonical status. All 108 focused control, status, registry, completion,
programme and UI tests pass; Ruff and diff hygiene pass. Because a test file
changes, this transition requires the full protected Linux and Windows release
path before merge.

`IN_PROGRESS` ISSUE-0154 product implementation starts from fresh merged
`main` at `570eb3fc22d1a9595ed601fe56460c54e9850d8e`; canonical and GitHub
issue #433 are both `in_progress`. The bounded outcome is one deterministic
fixed-rate/zero-coupon analytics path with explicit settlement, yield and
curve conventions, read-only application/API/Instrument Detail projection,
and audit lineage. The ISSUE-0088 curve edge remains partial: missing or
ambiguous tenor, curve type, interpolation, units, source, checksum or as-of
evidence must be unavailable or quarantined. No new dependency, provider
adapter, portfolio risk, recommendation, order authority, unvalidated OAS,
dealer quotation, broker write or live execution is in scope.

Next action: one `sol_worker` implements and focused-tests the smallest usable
ISSUE-0154 slice; root then reviews the complete diff for financial,
point-in-time, authority and UI-boundary correctness before the protected
Linux/Windows release gate.

`BLOCKED` root review rejected the uncommitted ISSUE-0154 product diff after
the single permitted worker correction. The corrected financial calculations,
curve chronology and outer authority checks pass 65 focused tests, Ruff,
compile and diff hygiene. Three contract failures remain: the application
persist operation rewrites `bond_analytics.parquet` with one record and loses
all prior instruments/history; a result changed after calculation is accepted
because replay does not bind or recompute the result payload; and a valuation
with no typed curve evidence reports overall `available` while curve/model
value is absent and no curve-unavailable limitation is emitted. Direct
terms-adapter/API replay and multi-call exact-YTW tests also remain absent.
No product commit, PR, merge, status transition or GitHub update is made.
Canonical ISSUE-0154 and GitHub #433 remain `in_progress`;
`execution_allowed=false`.

`IN_PROGRESS` a fresh bounded repair resumes from the same isolated
`570eb3fc22d1a9595ed601fe56460c54e9850d8e` worktree. It owns only the
review-proven blockers: append-safe/concurrent analytics history, result-payload
integrity and deterministic replay, explicit partial/unavailable curve state,
terms-adapter/API persistence coverage, and exact multi-call YTW coverage.
No formula, provider, portfolio, recommendation, execution or issue-scope
expansion is authorised. Next action: one `sol_worker` completes those repairs
and focused tests; root then reviews the entire accumulated ISSUE-0154 diff.

`VERIFIED` the bounded ISSUE-0154 product diff now supplies one canonical
fixed-rate/zero-coupon calculation path, explicit yield and curve conventions,
certified point-in-time terms adaptation, append-safe transactional history,
checksum-bound deterministic replay, read-only application/API projection and
Instrument Detail evidence. Root review reproduced and closed contradictory
price/yield input, invalid coupon, schedule-tampering, curve-basis, chronology,
projection-divergence and historical-selection failures. Missing typed curve
evidence remains explicit `partial`; the local differential harness preserves
the stated external-library limitation. Fresh local evidence is 185 focused
analytics, terms, calendar, application, UI and architecture tests passing,
with Ruff, compile and diff hygiene passing. No provider, portfolio,
recommendation, broker-write or execution authority was added, and
`execution_allowed=false`.

Next action: checkpoint the reviewed branch, open its feature PR and require
the full protected Linux and Windows packaged gate before merge or status
transition.

`VERIFIED` product PR #516 preserved reviewed head
`eb16e2b354166bfd83a620ca601406ad33287191` and merged as
`571366c8d75fbf3afad17e6d9b0549d299c92e49`. Supply-chain run
`30240413112` passed. Protected run `30240413171` completed every Linux and
Windows package, parity, smoke, performance, safety and policy check. Its 19
full-suite failures were reproduced exactly from an isolated worktree at base
`570eb3fc22d1a9595ed601fe56460c54e9850d8e`: 18 stale-generation failures
and the retained simple-score invalidation failure. No ISSUE-0154 test or
changed-path gate failed.

`IN_PROGRESS` the separate evidence-only convergence advances only ISSUE-0154
`in_progress -> implemented_initially`. The 197-record registry has proposed
SHA-256 `368db17a6a229e64ffa3c7d79a59caa83ef671187689e4af00591ae75102d27e`.
The reviewed GitHub plan contains exactly one Programme status update for open
#433 with semantic SHA-256
`20ee9feb3f2d032da4287ea4a577c7657d2b6f09c4360bdee2bc12caf8f5c004`.
No product, dependency, scope, acceptance, policy, safety or authority change
is included, and `execution_allowed=false`.

`VERIFIED` deterministic convergence review found no unrelated issue,
dependency, edge-evidence, policy or authority mutation. The status guard,
registry validation and all generation/freshness checks pass; 108 focused
control, registry, tracker, programme-map and UI tests pass. The committed
privacy-safe GitHub evidence identifies only ISSUE-0154's Programme status.

`VERIFIED` evidence-only PR #517 merged the implemented-initially convergence
as `637af409155c805dd0644f8640b4ea2590be6277`. Status guard run
`30242029782` and supply-chain run `30242029786` passed; redundant release run
`30242029818` was cancelled under programme policy. Checksum-approved GitHub
plan `20ee9feb3f2d032da4287ea4a577c7657d2b6f09c4360bdee2bc12caf8f5c004`
applied and verified #433 open/implemented_initially with
`execution_allowed=false`; final readback plan
`f07ac667e4a91a2e387f6a54826b9e97c97d0bf9c17ad363b161ee9f0ff35529`
contained zero actions.

`IN_PROGRESS` final convergence advances only ISSUE-0154
`implemented_initially -> integrated`. The regenerated 197-record registry has
SHA-256 `2e655d40f2e6326ddc956880af164472e443778da291d7ae146f3edae40290f8`;
the reviewed GitHub plan contains exactly one Programme status update for open
#433 with semantic SHA-256
`a569ba47ab96b35aa0fa4b3e2247612e49280523e0f86f9f89012dc24631f8b6`.
No product, test, dependency, workflow, scope, acceptance, safety or authority
change is included.

`VERIFIED` final convergence review confirms only ISSUE-0154's status and
supporting deterministic evidence change. The status guard, registry
validation, generation/freshness checks, diff hygiene and the same 108 focused
control, registry, tracker, programme-map and UI tests pass. The GitHub plan is
one open Programme status update and preserves `execution_allowed=false`.

`VERIFIED` final evidence-only PR #518 merged ISSUE-0154 as integrated in
`12f844f0610764c3974dc79fd15a315853025d3f`. Status guard run
`30242561041` and supply-chain run `30242561098` passed; redundant release run
`30242561052` was cancelled under programme policy. GitHub plan
`a569ba47ab96b35aa0fa4b3e2247612e49280523e0f86f9f89012dc24631f8b6`
applied and verified #433 open/integrated with `execution_allowed=false`;
final readback plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`
contained zero actions.

`IN_PROGRESS` the first ISSUE-0155 readiness review records only the
ISSUE-0155→ISSUE-0076 edge `unresolved -> complete`. The frozen
`plugin-contract.v1` interface supplies strict provider capabilities, licence,
network, credential, quota, retention, health and authority fields; allow-list
and version checks contain failures and prohibit canonical-store writes or
execution authority. ISSUE-0155 remains planned, and its ISSUE-0081,
ISSUE-0088, ISSUE-0149 and ISSUE-0153 edges remain unresolved. The regenerated
197-record registry has SHA-256
`85833d1ece0be4507a1abaa3ad2001cf3f076908731b4b351595c470e92edddf`;
the GitHub projection is the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.
No product, provider, dependency-list, scope, acceptance, status, safety or
authority change is authorised.

`VERIFIED` edge review confirms the provider-neutral contract is sufficient
for later fixed-income adapter children without granting persistence or
execution authority. Seventeen focused plugin/provider/UI tests and Ruff pass;
the status guard, registry validation, generation/freshness checks, 108
control/programme/UI tests and diff hygiene pass. Provider data semantics,
bulk transport and legal approval remain explicitly owned by the unresolved
edges.

`VERIFIED` evidence-only PR #519 merged the ISSUE-0155→ISSUE-0076 provider
edge as `c76f54f82d8101f6d1ce3bb0f0282ac68f3a4043`. Status guard run
`30243047028` and supply-chain run `30243047057` passed; redundant release run
`30243047026` was cancelled under programme policy. The GitHub projection
remained the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.

`IN_PROGRESS` the second ISSUE-0155 readiness review records only the
ISSUE-0155→ISSUE-0081 edge `unresolved -> complete`. The reviewed
`bulk-cache.v1` interface supplies bounded resumable downloads, immutable
content-addressed raw objects, checksum and size verification, revision
manifests, local licence/update metadata, validation-before-promotion and safe
archive handling. ISSUE-0155 remains planned; ISSUE-0088, ISSUE-0149 and
ISSUE-0153 remain unresolved. The regenerated registry has SHA-256
`1a9be068d6df377269ac9257df6b3fc422a8dd8dde54d7f3ce3c293454d031a8`;
the GitHub projection remains the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.
No product, provider, dependency-list, scope, acceptance, status, safety or
authority change is authorised.

`VERIFIED` edge review confirms the bulk cache provides ISSUE-0155's shared
transport and immutable raw-object prerequisite without claiming
provider-specific schemas or legal enablement. Seven focused bulk-cache tests
and Ruff pass; the status guard, registry validation, generation/freshness
checks, 108 control/programme/UI tests and diff hygiene pass.

`VERIFIED` evidence-only PR #520 merged the ISSUE-0155→ISSUE-0081 bulk-cache
edge as `06a77a2539a8b414944d380d0c39b18b29cfad7f`. Status guard run
`30243477788` and supply-chain run `30243477858` passed; redundant release run
`30243477813` was cancelled under programme policy. The GitHub projection
remained the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.

`IN_PROGRESS` the third ISSUE-0155 readiness review records only the
ISSUE-0155→ISSUE-0088 edge `unresolved -> partial_interface`. The existing
macro warehouse supplies append-only bitemporal risk-free and benchmark
observations with source terms/checksums, currency, units, frequency,
revisions, transformations and decision-time selection. It does not supply a
fixed-income security observation, typed curve tenor/interpolation, bid/ask,
trade, spread, liquidity, evaluated/executable label or provider-coverage
contract; ISSUE-0155 must define these and keep absent evidence unavailable.
ISSUE-0155 remains planned, while ISSUE-0149 and ISSUE-0153 remain unresolved.
The regenerated registry has SHA-256
`28ef7b9e64ad1319b02c41e050bd049e133d2a341c059a07e8d2e9c42455725b`;
the GitHub projection remains the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.
No product, provider, dependency-list, scope, acceptance, status, safety or
authority change is authorised.

`VERIFIED` partial-interface review preserves every absent fixed-income
market-data field rather than overstating the macro warehouse. Nine focused
macro/bitemporal tests and Ruff pass; the status guard, registry validation,
generation/freshness checks, 108 control/programme/UI tests and diff hygiene
pass.

`VERIFIED` evidence-only PR #521 merged the ISSUE-0155→ISSUE-0088 partial
macro-data edge as `6ac65c216e39a89a93222adb349398f13fba894b`. Status guard
run `30243901856` and supply-chain run `30243901887` passed; redundant release
run `30243901806` was cancelled under programme policy. The GitHub projection
remained the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.

`IN_PROGRESS` the fourth ISSUE-0155 readiness review records only the
ISSUE-0155→ISSUE-0149 edge `unresolved -> partial_interface`. The existing
`legal-terms.v1` registry supplies fail-closed cache, redistribution and audit
export decisions, terms-change review and professional-review visibility.
ECB, ESMA FIRDS/FITRS and FINRA/TRACE have no source-specific approved terms
records, while ISSUE-0149 remains `hardening_required`; ISSUE-0155 may define
disabled adapters but must not enable those sources before reviewed records
exist. ISSUE-0155 remains planned and ISSUE-0153 remains unresolved. The
regenerated registry has SHA-256
`555a2019c37d669b12c94d52bbbf4f77e6235e65d3bdf106247b3054d49832cd`;
the GitHub projection remains the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.
No product, provider, dependency-list, scope, acceptance, status, safety or
authority change is authorised.

`VERIFIED` partial-interface review confirms the generic legal gate fails
closed and does not imply approval for any named fixed-income source. Eight
focused legal/UI tests and Ruff pass; the status guard, registry validation,
generation/freshness checks, 108 control/programme/UI tests and diff hygiene
pass.

`VERIFIED` evidence-only PR #522 merged the ISSUE-0155→ISSUE-0149 partial
legal-terms edge as `2e5aea8339589763f46a3b23416e5ec194d938f7`. Status guard
run `30244387504` and supply-chain run `30244387520` passed; redundant release
run `30244387516` was cancelled under programme policy. The GitHub projection
remained the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.

`IN_PROGRESS` the final ISSUE-0155 readiness review records only the
ISSUE-0155→ISSUE-0153 edge `unresolved -> complete`. The integrated
`fixed-income-terms-v1` contract supplies immutable security identity,
versioned terms, certified coupon and redemption schedules, source checksums,
known/retrieved chronology, point-in-time selection, conflict handling and
unsupported-structure quarantine. All five dependency edges are now resolved:
ISSUE-0076, ISSUE-0081 and ISSUE-0153 are complete; ISSUE-0088 and ISSUE-0149
remain partial interfaces with their limitations explicit. ISSUE-0155 remains
planned pending a separate readiness transition. The regenerated registry has
SHA-256
`7f90e71ec7d80d0e050c58ca12f8aacf097ea83a9691b4cd1c197444735ef1c7`;
the GitHub projection remains the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.
No product, provider, dependency-list, scope, acceptance, status, safety or
authority change is authorised.

`VERIFIED` the terms dependency review is bounded to the existing contract.
Twenty-seven focused fixed-income terms/UI tests and Ruff pass; the status
guard, registry validation, generation/freshness checks, 108
control/programme/UI tests and diff hygiene pass.

`VERIFIED` evidence-only PR #523 merged the ISSUE-0155→ISSUE-0153 terms edge
as `d2947d32740a475e3fb0b41795d1e52d41841961`. Status guard run
`30244912786` and supply-chain run `30244912771` passed; redundant release run
`30244912765` was cancelled under programme policy. The GitHub projection
remained the zero-action plan
`17a2d232ab37285969da9250114747ba30a607d5c8bb9d8c9b9e2c02e50582d8`.

`IN_PROGRESS` the separately guarded ISSUE-0155 `planned -> ready` proposal is
supported by all five reviewed blocking interfaces. It preserves the
ISSUE-0088 macro-data and ISSUE-0149 legal-terms partial-interface limitations:
ECB, ESMA and FINRA adapters remain disabled until source-specific legal
approval, and absent market evidence remains unavailable rather than inferred.
The 197-record registry has base SHA-256
`7f90e71ec7d80d0e050c58ca12f8aacf097ea83a9691b4cd1c197444735ef1c7`
and proposed SHA-256
`08dd7a615af1a75c597442dd15ce5a4cb663db8911f63a86c595b1068738a697`.
The reviewed GitHub plan contains exactly one Programme status update for open
remote #434, has semantic SHA-256
`a6f4b964f8fdddcf9f4d2b247c37110a5d69f82f2a743eff0ca6c0b531c8d448`,
and preserves `execution_allowed=false`. No product, dependency, scope,
acceptance, safety, batch or authority change is authorised.

`VERIFIED` the readiness transition, exact one-action GitHub projection,
status guard, registry validation and deterministic generation/freshness
checks pass. All 108 focused control, status, registry, completion, programme
and UI tests pass; diff hygiene passes. The change is restricted to generated
control/evidence artifacts and qualifies for the evidence-only fast path.

`VERIFIED` readiness PR #524 merged ISSUE-0155 `planned -> ready` as
`d1a6a451284fb52e81d1f7bb3773ec8c3faa2847`. Status guard run
`30245425161` and supply-chain run `30245425173` passed; redundant release run
`30245425126` was cancelled under programme policy. Checksum-approved GitHub
plan `a6f4b964f8fdddcf9f4d2b247c37110a5d69f82f2a743eff0ca6c0b531c8d448`
applied and verified #434 open/ready with `execution_allowed=false`; final
readback plan
`373fec787836cf6bbe007039228bc647594608dda6139646ee15dd10a5ef6353`
contained zero actions.

`IN_PROGRESS` the separately guarded ISSUE-0155 `ready -> in_progress`
handoff changes only that canonical status. The bounded implementation outcome
is provider-neutral fixed-income market, curve and liquidity schemas;
immutable point-in-time storage; lawful local/manual import; disabled
source-specific adapter definitions; coverage and health projection; and
explicit conflict, stale, unavailable and non-executable states. ECB, ESMA and
FINRA remain disabled until source-specific legal approval. The registry has
base SHA-256
`08dd7a615af1a75c597442dd15ce5a4cb663db8911f63a86c595b1068738a697`
and proposed SHA-256
`dc207bec5b66c3ee02779dad5824f883ef772bcc3c1130e98647e0b2d07aaba3`.
The reviewed GitHub plan contains exactly one open Programme status update for
#434 with semantic SHA-256
`0de1dcfe0b9e4b2f91d32f8fe38c2bb361f0b85bb109ac7ada3d142a50fd80b2`.
No product, dependency, scope, acceptance, safety, provider authority or
execution change is authorised.

`VERIFIED` the implementation handoff, exact one-action GitHub projection,
status guard, registry validation and deterministic generation/freshness
checks pass. All 108 focused control, status, registry, completion, programme
and UI tests pass; diff hygiene passes. This remains an evidence-only
transition and `execution_allowed=false`.

`IN_PROGRESS` ISSUE-0155 product implementation starts from fresh merged
`main` at `e7de20f4aaf690a1bf754c88d07bb06d00faa707`; canonical and GitHub
issue #434 are both `in_progress`. One `sol_worker` owns the smallest usable
slice: frozen provider-neutral market/curve/liquidity observation contracts,
append-safe point-in-time local storage and manual import, disabled
ECB/ESMA/FINRA provider definitions, coverage/health projection and read-only
application/Instrument Detail exposure. Source-specific network acquisition,
legal approval, analytics/risk/portfolio changes, recommendations, broker
writes and live execution are excluded. Missing, stale, conflicted or
non-executable evidence must remain explicit and `execution_allowed=false`.

`VERIFIED` the worker implementation and its single focused correction pass
now satisfy the bounded contract. Root reviewed the complete diff for
point-in-time leakage, immutable retry identity, cross-provider overwrite,
transaction rollback, concurrent append loss, legal/retention bypass, schema
drift, false liquidity precision and disabled-provider authority. A small
integration hardening constrains source authority to the shared enum and
cross-validates coverage status against its numerator/denominator values.
Fresh local evidence is 159 affected fixed-income, legal, plugin, application
and Instrument Detail tests passing, plus the security-policy check (4 tests,
1 skipped), architecture boundary, Ruff, compile, scoped MyPy and diff hygiene.
Changed validation passed its source smoke and changed tests; its only failure
is the unchanged retained control fingerprint: generation base
`d1a6a451284fb52e81d1f7bb3773ec8c3faa2847` versus current `origin/main`
`e7de20f4aaf690a1bf754c88d07bb06d00faa707`. No provider network acquisition,
analytics/risk/portfolio change or execution authority is included.

Next action: checkpoint this reviewed branch, open the ISSUE-0155 product PR
and require the complete protected Linux and Windows packaged gate before any
merge or status transition.

`IN_PROGRESS` draft product PR #526 preserved reviewed checkpoint
`34a09ae32b8929418bba4559ae374d23ad88000a`. Protected run `30248410578`
passed package builds, source/package parity, packaged smoke, performance,
source policy, bulk cache, privacy, legal and SBOM checks on Linux and Windows.
Its 19 full-suite failures on each platform exactly match the retained
`e7de20f4` baseline. One current-feature security check failed because the
manifest-only disabled provider rows declared network access. The bounded
correction keeps ECB, ESMA and FINRA stubs both disabled and network-disabled;
it does not weaken the security gate or add acquisition code. Fresh fixed-income,
plugin and security tests pass (25 passed, 1 skipped), as do the release
security checker, Ruff, compile and diff hygiene. Next action is to commit the
correction and require a fresh complete protected gate.

`VERIFIED` product PR #526 preserved corrected head
`fefbf72d7a1fc36596807b5954c153ba96def4ba` and merged as
`5cdf8de38abe6d809edce43b791eea7dd71e53e8`. Supply-chain run
`30249924072` passed. Protected run `30249924156` completed Linux and Windows
package builds, parity, packaged smoke, performance, source policy, bulk cache,
security, privacy, legal and SBOM checks. The security correction passed on
both platforms; the only full-suite failures were the exact retained 19-node
`e7de20f4` baseline. No ISSUE-0155 test or current-feature gate failed.

`IN_PROGRESS` the separate evidence-only convergence advances only ISSUE-0155
`in_progress -> implemented_initially`. The regenerated 197-record registry
has SHA-256
`2d78c97db98964eb39a0e26e0444b1d692846be4ebd7911766f07a06a2102ef5`.
The reviewed GitHub plan contains exactly one Programme status update for open
#434 with semantic SHA-256
`e07946063d4e27cad6ea7fdd789f86616463a0d2420fa96dc811a1a1e0fb8243`.
No product, dependency, scope, acceptance, policy, safety, provider or
execution authority change is included, and `execution_allowed=false`.

`VERIFIED` deterministic convergence review found no unrelated issue,
dependency, edge-evidence, policy, provider or authority mutation. The status
guard, registry validation, registry/status/document generation and freshness
checks pass; all 119 focused control, registry, completion, tracker,
programme-map and UI tests pass. The committed privacy-safe GitHub evidence
identifies only ISSUE-0155's Programme status.

`VERIFIED` evidence-only PR #527 merged ISSUE-0155 as
`implemented_initially` in
`75c6f2902d44d59d03ac4b49ed5a88cb31b24d05`. Status-transition guard run
`30251869405` and supply-chain run `30251869466` passed; redundant release run
`30251869420` was cancelled under programme policy. Checksum-approved GitHub
plan `e07946063d4e27cad6ea7fdd789f86616463a0d2420fa96dc811a1a1e0fb8243`
applied and verified #434 open/implemented_initially with
`execution_allowed=false`; final readback
`95b2550d18b8ceaabc5c06c215ebb4eb336923c88d2fbb9c7825393b3c4b610f`
contained zero actions.

`IN_PROGRESS` final convergence advances only ISSUE-0155
`implemented_initially -> integrated`. The regenerated 197-record registry has
SHA-256 `772496e7646f579259103dabaa399f09918e1b1d6b7acb083f8b6f7f1c30aaa7`;
the reviewed GitHub plan contains exactly one Programme status update for open
#434 with semantic SHA-256
`ebc7b7d74e2d1ddadae16260b1b75d590e933029c03854a7a7d4fd8a03bf33dc`.
No product, dependency, scope, acceptance, policy, provider, safety or
execution authority change is included.

`VERIFIED` final deterministic review found no unrelated issue, dependency,
edge-evidence, policy, provider or authority mutation. Status guard, registry
validation, all generation/freshness checks and diff hygiene pass; all 119
focused control, registry, completion, tracker, programme-map and UI tests
pass. The privacy-safe GitHub evidence identifies only ISSUE-0155's Programme
status and `execution_allowed=false` remains binding.

`VERIFIED` final evidence-only PR #528 merged ISSUE-0155 as integrated in
`0d810c3c1c5f59916ae58cef222ea6b6e9321c5b`. Status-transition guard run
`30252372304` and supply-chain run `30252371206` passed; redundant release run
`30252371133` was cancelled. GitHub plan
`ebc7b7d74e2d1ddadae16260b1b75d590e933029c03854a7a7d4fd8a03bf33dc`
applied and verified #434 open/integrated with `execution_allowed=false`;
readback `5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`
contained zero actions.

`IN_PROGRESS` ISSUE-0156 remains planned while its first dependency edge,
ISSUE-0091, is recorded as `partial_interface`. PR #318 supplies retained
reported/latest-restated/as-known statement histories, period coverage,
reconciliation and explicit unsupported concepts. It does not supply
bond-to-issuer mapping or rating/default/recovery inputs; ISSUE-0156 must keep
those unknown rather than infer or zero-fill them. The registry moves from
SHA-256 `772496e7646f579259103dabaa399f09918e1b1d6b7acb083f8b6f7f1c30aaa7`
to `609a74cf57e12ddff4cc23a82fbe41dbd62a68262b1d9b07ac0f314c96e63c80`.
The GitHub projection remains zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`;
the other three ISSUE-0156 edges remain unresolved and
`execution_allowed=false`.

`VERIFIED` the one-edge diff preserves ISSUE-0156's planned status, scope,
acceptance criteria, remaining edges and authority. The schema-1.3 dependency
guard, registry validation, all generation/freshness checks and diff hygiene
pass; all 126 focused statement-history, control, registry, completion,
tracker, programme-map and UI tests pass.

`VERIFIED` dependency-edge PR #529 merged as
`8b2508c800b63ea779af709a56b7bc619278f80b` from reviewed head
`ccf4d7e22123421835925f8fd82ee34de47c267f`. Status-transition guard run
`30252982106` and supply-chain run `30252982330` passed; redundant release run
`30252982121` was cancelled under the evidence-only policy. The GitHub
projection remained the zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`.

`IN_PROGRESS` the second ISSUE-0156 dependency review covers only ISSUE-0111.
PR #322 supplies a versioned common-risk interface with sample, EWMA,
shrinkage, winsorised, diagonal and optional factor covariance, visible PSD
repair and conditioning, held-out estimator selection, reconciled component
variance, bootstrap uncertainty, regime comparison and tail/liquidity
evidence. The edge is `partial_interface`: it has no debt-specific
duration/spread/credit/FX component ingestion or common fixed-income scenario
reconciliation, which ISSUE-0156 must implement without zero-filling unknown
inputs. The registry moves from SHA-256
`609a74cf57e12ddff4cc23a82fbe41dbd62a68262b1d9b07ac0f314c96e63c80`
to `91733b64f830af90bcff4e3ba8087ef0b3de0bf0a7fd42c17929f885a22c18f6`;
the GitHub projection remains zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`.
Thirteen focused robust-risk and factor-risk tests pass under the system
Python environment; the stale repository virtual environment remains missing
`exchange_calendars`. ISSUE-0156 stays planned, its ISSUE-0154 and ISSUE-0155
edges remain unresolved, and `execution_allowed=false`.

Next action: record only ISSUE-0156→ISSUE-0111 as `partial_interface`,
regenerate deterministic evidence, and run the evidence-only protected
control gates before merge.

`VERIFIED` the one-edge diff preserves ISSUE-0156's planned status, scope,
acceptance criteria, ISSUE-0154/ISSUE-0155 edges and authority. The schema-1.3
dependency guard, registry validation, all generation/freshness checks and
diff hygiene pass; all 134 focused robust-risk, factor-risk, control,
registry, completion, tracker, programme-map and UI tests pass.

`VERIFIED` dependency-edge PR #530 merged as
`7946829d29c58f0bbe06d399581e9865f7307a08` from reviewed head
`4aff27211d54b10ecc7666b891d2ff0f8eb98dee`. Status-transition guard run
`30253745818` and supply-chain run `30253745835` passed; redundant release run
`30253748149` was cancelled under the evidence-only policy. The GitHub
projection remained the zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`.

`IN_PROGRESS` the third ISSUE-0156 dependency review covers only ISSUE-0154.
PR #516 supplies the complete deterministic fixed-income valuation interface:
certified contractual cash flows, clean/dirty and accrued conversions,
price/yield round trips, exact YTC/YTW, duration, convexity, DV01/PV01, typed
point-in-time curves, full parallel-shock repricing, observed-versus-model
separation, differential quarantine and immutable audited replay. Twenty-four
fresh analytics tests pass, including sign/unit, curve chronology, scenario,
round-trip, persistence, corruption, concurrency and point-in-time cases.
Key-rate, spread, credit, liquidity, optionality and portfolio scenario
decomposition remain ISSUE-0156 work rather than gaps in this prerequisite.
The registry moves from SHA-256
`91733b64f830af90bcff4e3ba8087ef0b3de0bf0a7fd42c17929f885a22c18f6`
to `854c103709b18a6a806dd842646c3b64a5951d0cc4116e076f9da67de3f65fe9`;
the GitHub projection remains zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`.
ISSUE-0156 stays planned, its ISSUE-0155 edge remains unresolved, and
`execution_allowed=false`.

Next action: record only ISSUE-0156→ISSUE-0154 as `complete`, regenerate
deterministic evidence, and run the evidence-only protected control gates
before merge.

`VERIFIED` the one-edge diff preserves ISSUE-0156's planned status, scope,
acceptance criteria, prior edges, unresolved ISSUE-0155 edge and authority.
The schema-1.3 dependency guard, registry validation, all
generation/freshness checks and diff hygiene pass; all 145 focused analytics,
control, registry, completion, tracker, programme-map and UI tests pass.

`VERIFIED` dependency-edge PR #531 merged as
`5c02f8c3bd4bfdceb34a06abbe4b3b177987c1bf` from reviewed head
`69de8caf9125378ab95bd6ec68f30fb69ece72f6`. Status-transition guard run
`30254353156` and supply-chain run `30254353117` passed; redundant release run
`30254353166` was cancelled under the evidence-only policy. The GitHub
projection remained the zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`.

`IN_PROGRESS` the final ISSUE-0156 dependency review covers only ISSUE-0155.
PR #526 supplies the complete provider-neutral fixed-income market-evidence
interface: immutable point-in-time price/yield/spread, typed curve-tenor and
liquidity observations, source separation/conflict state, explicit
indicative/evaluated/executable labels, legal/retention gates, coverage
lineage, atomic provider isolation and read-only application projection.
Fifteen fresh market-data tests pass for chronology, retrieval identity,
concurrency, conflicts, curve typing, manual legal gates, disabled providers,
liquidity precision, coverage, API/UI parity and execution denial. Remote
ECB/ESMA/FINRA acquisition remains intentionally disabled pending
source-specific approval; missing evidence stays unavailable and does not
make the interface incomplete. The registry moves from SHA-256
`854c103709b18a6a806dd842646c3b64a5951d0cc4116e076f9da67de3f65fe9`
to `1c775f07efc78aa3bdcbfdffdaa6951d6018befd6985cf544c2fcbd328b7dbc9`;
the GitHub projection remains zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`.
ISSUE-0156 stays planned until a later separate readiness transition, and
`execution_allowed=false`.

Next action: record only ISSUE-0156→ISSUE-0155 as `complete`, regenerate
deterministic evidence, and run the evidence-only protected control gates
before merge.

`VERIFIED` the one-edge diff preserves ISSUE-0156's planned status, scope,
acceptance criteria, prior edges and authority while completing its final
declared dependency review. The schema-1.3 dependency guard, registry
validation, all generation/freshness checks and diff hygiene pass; all 136
focused market-data, control, registry, completion, tracker, programme-map
and UI tests pass.

`VERIFIED` final dependency-edge PR #532 merged as
`8d8ce4f38e657dde6c282ef1d7191f4427134a07` from reviewed head
`2b6ca0629fa75b528e803c4d037ddcb408a7c032`. Status-transition guard run
`30254863284` and supply-chain run `30254863195` passed; redundant release run
`30254863139` was cancelled under the evidence-only policy. The GitHub
projection remained the zero-action plan
`5e2de0865c00e34090849f765a065ae44ecd4ab9368463bf50dedb7fa6e92602`.

`IN_PROGRESS` the separately guarded ISSUE-0156 `planned -> ready` proposal is
supported by all four reviewed blocking interfaces. Two partial interfaces
remain explicit: statement history does not supply bond-to-issuer or
rating/default/recovery data, and common robust risk does not yet ingest debt
components or reconcile fixed-income scenarios. Those gaps are ISSUE-0156's
bounded work and must remain unknown or unavailable until explicit evidence
exists. The transition changes no dependency, scope, acceptance criterion,
safety rule, product behaviour or authority. The registry moves from SHA-256
`1c775f07efc78aa3bdcbfdffdaa6951d6018befd6985cf544c2fcbd328b7dbc9`
to `8b991273f8e725c7f2af7b445dbf6292ea693d8b2993508e0ba6956200204b66`.
The reviewed GitHub plan contains exactly one Programme status update for
open issue #435 with semantic SHA-256
`024c5d1a21fa3157c17d975cbbd66c1c083780bf2b65d8d1d97d5f4d9d40bf0f`;
`execution_allowed=false`.

Next action: generate and review the single-status readiness transition,
apply its checksum-controlled GitHub update only after merge, and require a
zero-action readback.

`VERIFIED` deterministic readiness review found no unrelated issue,
dependency, edge-evidence, scope, acceptance, policy or authority mutation.
The status guard, registry validation, all generation/freshness checks and
diff hygiene pass; all 121 focused control, registry, completion, tracker,
programme-map and UI tests pass. The committed privacy-safe GitHub evidence
identifies only ISSUE-0156's Programme status.

`VERIFIED` readiness PR #533 merged as
`57262943fa3fb538216a97f6b595fbbfc23024fc` from reviewed head
`9c68a98898e5a2bca65bfd8c9fa907282d87acb5`. Status-transition guard run
`30255341598` and supply-chain run `30255341482` passed; redundant release run
`30255342372` was cancelled. Checksum-approved GitHub plan
`024c5d1a21fa3157c17d975cbbd66c1c083780bf2b65d8d1d97d5f4d9d40bf0f`
applied and verified #435 open/ready with `execution_allowed=false`; readback
`afedeb316e7c192285edb6501cc0390a9bbef95e2623c91b54ab944a3194e3d9`
contained zero actions.

`IN_PROGRESS` the separately guarded ISSUE-0156 `ready -> in_progress`
hand-off changes only that canonical status. The implementation contract is
the smallest usable fixed-income risk record and scenario decomposition:
parallel/key-rate curve risk with approximation-versus-full-reprice evidence,
explicit spread/credit/default/recovery and issuer-concentration support,
liquidity/quote-age/minimum-size warnings, callable/reinvestment,
inflation/FX and bond-versus-bond-ETF distinctions, portfolio reconciliation,
read-only application/UI/audit exposure and `execution_allowed=false`.
Unsupported or missing evidence must remain unavailable or unknown. Provider
acquisition, recommendations, optimiser changes, broker writes and live
orders are excluded. The registry moves from SHA-256
`8b991273f8e725c7f2af7b445dbf6292ea693d8b2993508e0ba6956200204b66`
to `75bb70f6db764a88789cf58e52cd827a1819106d6bbcd9f19ebfe77fc179c611`.
The reviewed GitHub plan contains exactly one Programme status update for
open issue #435 with semantic SHA-256
`0add5677998d354a9d19e92534cb945179776dcfcb71832b3ba95ad99ce2eb95`;
`execution_allowed=false`.

Next action: generate and review the single-status implementation hand-off,
apply its checksum-controlled GitHub update only after merge, and require a
zero-action readback before product work starts from fresh main.

`VERIFIED` deterministic hand-off review found no unrelated issue,
dependency, edge-evidence, scope, acceptance, policy or authority mutation.
The status guard, registry validation, all generation/freshness checks and
diff hygiene pass; all 121 focused control, registry, completion, tracker,
programme-map and UI tests pass. The committed privacy-safe GitHub evidence
identifies only ISSUE-0156's Programme status.

`VERIFIED` implementation hand-off PR #534 merged as
`e9847c910080892af6fda7f420ccdb194b73e0ef` from reviewed head
`3799f3080f0f22c895bfa3ce71760bf5368bdbcc`. Status-transition guard run
`30255879394` and supply-chain run `30255879362` passed; redundant release run
`30255879367` was cancelled. Checksum-approved GitHub plan
`0add5677998d354a9d19e92534cb945179776dcfcb71832b3ba95ad99ce2eb95`
applied and verified #435 open/in_progress with `execution_allowed=false`;
readback `0d4164705d284745b80c1836fcc4c7695e3ce3e0273713957784deae297404e5`
contained zero actions.

`IN_PROGRESS` one `sol_worker` owns the bounded ISSUE-0156 product slice from
fresh main. The smallest usable outcome is a canonical local
`fixed-income-risk.v1` calculation and replay contract for supported bonds,
with parallel/key-rate full repricing and approximation discrepancy,
spread/default/recovery only from explicit inputs, issuer and portfolio
scenario reconciliation, liquidity/quote-age/minimum-size warnings,
call/reinvestment, inflation/FX and bond-versus-bond-ETF flags, read-only
application/Instrument Detail projection, audit lineage and
`execution_allowed=false`. Missing inputs must remain unknown and low duration
must never suppress other risk components.

Excluded: remote provider acquisition, new dependencies, recommendations,
optimiser changes, proposal/order workflows, broker writes, live execution,
unvalidated OAS and unrelated refactors. Required evidence is focused
parallel/non-parallel, approximation/full-reprice, default/recovery, callable,
sign/unit, aggregation/reconciliation, unknown-input, persistence/replay,
application/UI and architecture tests.

`VERIFIED` the bounded implementation and its single focused correction now
provide canonical versioned risk/scenario records, explicit parallel and
key-rate shocks, position-scaled DV01, full-reprice discrepancy, explicit
unknown spread/default/liquidity evidence, callable and other material-risk
guards, immutable verified replay, concurrent-writer reconciliation and common
portfolio component/marginal/scenario integration. Instrument Detail consumes
the read-only application projection and `execution_allowed=false` remains
fixed.

Root review corrected three final integration details: shock values are present
in the scenario output, non-zero credit/liquidity losses prevent a low-risk
label, and missing holding scenarios remain unreconciled rather than being
silently omitted. Fresh evidence is 60 fixed-income risk, analytics,
market-data, terms-UI and robust-risk tests plus 12 architecture/application
API tests; the earlier 103 architecture/documentation/application/Instrument
Detail checks also passed. Ruff, compileall, scoped MyPy for both new modules
and diff hygiene pass. Repository-wide transitive MyPy remains an existing
baseline with missing third-party stubs and unrelated historical errors.

`VERIFIED` product PR #535 merged the exact 13-file reviewed product tree as
`379bb8a73a76c3e43d2fcfaaad3ef9927306228c`. Protected runs
`30257803363` and `30259488969` completed Linux and Windows package build,
artefacts, source/package parity, packaged smoke, performance, source, cache,
security, privacy, legal and SBOM checks. The diagnostic control refresh
reduced full-suite failures to only the previously authorised B03
classification-score invalidation assertion; no ISSUE-0156 or changed-path
test failed. Current-head supply-chain run `30260932938` passed and
`execution_allowed=false` remained fixed.

`IN_PROGRESS` the evidence-only convergence advances only ISSUE-0156
`in_progress -> implemented_initially` with verified product commit
`379bb8a73a76c3e43d2fcfaaad3ef9927306228c`. The canonical registry retains
197 records and proposed SHA-256
`ebe2a113b1fa86b212c11642aa2e2bf06e0462ead74271fd35c428fd53602f0c`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #435 with semantic SHA-256
`554ea6e37cdd22da85bf56a68cbe4f0b58280386fc4a00358194f59bc6e0001a`.
No product, dependency, scope, acceptance, policy or authority change is
included.
