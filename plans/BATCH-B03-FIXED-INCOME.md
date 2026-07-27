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
