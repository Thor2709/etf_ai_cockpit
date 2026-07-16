# ETF AI Cockpit — 83 New Issues Ready to Append to `issues/open.md`

**Proposed numbering:** `ISSUE-0070` through `ISSUE-0152`  
**Research date:** 15 July 2026  
**Use:** implementation-ready issue specifications. Add them to the canonical local ledger only after the scope ADR confirms the final two-function product.

## Epic summary

- **Attribution:** 1
- **Audit & reproducibility:** 1
- **Backtest & execution:** 2
- **Benchmarking:** 1
- **Broker integration:** 1
- **Data platform:** 2
- **Data programme:** 11
- **Documentation:** 1
- **ETF analysis:** 5
- **Execution:** 1
- **Execution analytics:** 1
- **Execution safety:** 2
- **Expected return:** 2
- **Extensibility:** 1
- **Final certification:** 1
- **Foundation & governance:** 2
- **Frontend & API:** 5
- **Governance:** 1
- **Model governance:** 1
- **Model research:** 8
- **Paper trading:** 1
- **Performance:** 1
- **Performance & release:** 1
- **Portfolio construction:** 2
- **Quality & release:** 3
- **Reproducibility:** 1
- **Risk & scenarios:** 1
- **Risk model:** 2
- **Scoring architecture:** 1
- **Security:** 1
- **Security & release:** 1
- **Security & resilience:** 1
- **Stock analysis:** 12
- **Supply-chain governance:** 1
- **Trading foundation:** 3
- **Workflow platform:** 1

## ISSUE-0070 — Freeze the final product scope, completion contract and staged execution authority

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Foundation & governance  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0008; ISSUE-0032; ISSUE-0060; ISSUE-0066

**Problem**  
The current authoritative plan defines an advisory-only cockpit, while the final requested product includes automatic trading.

**Why it matters**  
Without an explicit superseding contract, developers can either violate existing safety policy or implement incompatible meanings of “finished”.

**Proposed implementation**
- Write an Architecture Decision Record defining the two final product functions and supported horizons.
- Define authority stages: research, shadow proposal, paper, broker read-only, draft order, capped automatic and disabled.
- Define the mandatory no-subscription core and optional enrichment tier.
- Create one machine-readable capability, dependency and closure matrix.
- Preserve historical rejection records but identify this ADR as the superseding scope decision.

**Data, packages and external dependencies**
- Canonical issue ledger and plan.
- Risk, execution and data-source policies.
- No external runtime dependency.

**Acceptance criteria**
- Every route, dataset, model, strategy and broker capability has a declared authority stage.
- Live execution is disabled by default and cannot be enabled without all prerequisite evidence.
- The final completion checklist is finite, versioned and approved.
- No wording promises returns or claims equivalence with proprietary institutional platforms.

**Tests required**
- Policy schema tests.
- Authority transition and tampering tests.
- Issue-ledger reconciliation test.
- Static scan for undeclared execution paths.

**UI requirement**  
System Map, Settings and Audit show the active product contract and authority stage.

**Security and audit requirement**  
Append-only ADR checksum; every authority change is logged and included in audit exports.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0071 — Refactor into bounded domain, application, infrastructure and presentation modules

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Foundation & governance  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0070

**Problem**  
AppState, services and score modules combine UI state, orchestration, calculations, persistence and provider concerns.

**Why it matters**  
Training, bitemporal storage and execution will make the current modular monolith increasingly fragile and difficult to test.

**Proposed implementation**
- Define domain packages for instruments, data, fundamentals, funds, features, scores, forecasts, portfolio, risk, backtest, paper, execution and audit.
- Define application commands, queries and jobs that mediate every UI action.
- Move provider, database, model and broker implementations behind explicit ports.
- Split page/session state from durable workflow state.
- Add compatibility facades and migrate incrementally rather than performing a flag-day rewrite.
- Generate an import/dependency graph and enforce package boundaries in CI.

**Data, packages and external dependencies**
- Python protocols/ABCs and dependency-injection wiring.
- Existing tests retained as a characterisation suite.

**Acceptance criteria**
- No presentation module imports provider, database or broker implementations directly.
- Each canonical calculation has one implementation path.
- Mandatory workflows retain behaviour throughout migration.
- Circular-dependency and architectural-boundary checks pass.

**Tests required**
- Import-boundary tests.
- Characterisation and contract tests.
- Mutation tests for boundary violations.
- Source/package smoke after each migration wave.

**UI requirement**  
No new end-user page; Diagnostics exposes module and service health.

**Security and audit requirement**  
Sensitive provider/broker objects never enter serialised UI state; architecture report is included in audit evidence.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0072 — Implement the hybrid local analytical and transactional data platform

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data platform  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0038; ISSUE-0071

**Problem**  
Parquet files and in-memory DuckDB queries do not provide complete transactional state for jobs, experiments, journals, portfolios, orders and reconciliation.

**Why it matters**  
The final product needs scalable local analytics and ACID operational state without requiring a remote database service.

**Proposed implementation**
- Use immutable/versioned Parquet plus DuckDB for large analytical tables.
- Use SQLite in WAL mode for configuration, jobs, experiments, journals, portfolio and order ledgers.
- Create repository interfaces, migrations, foreign keys, integrity checks, compaction and retention.
- Publish derived analytical generations atomically and expose read-only snapshots to UI queries.
- Preserve CSV/JSON exports and migrate current files without losing lineage.

**Data, packages and external dependencies**
- DuckDB, SQLite and PyArrow.
- Polars only for benchmarked hot paths.
- Configurable local storage root.

**Acceptance criteria**
- Fresh and migrated installations return identical canonical queries.
- Interrupted writes cannot corrupt the last valid generation.
- Analytical and transactional records reconcile through stable IDs and run IDs.
- Backup, restore and supported rollback are documented and tested.

**Tests required**
- Migration fixtures.
- Crash-injection tests.
- Concurrent reader/writer tests.
- Integrity and performance tests.

**UI requirement**  
Data Health shows store versions, sizes, migrations, integrity and last compaction.

**Security and audit requirement**  
File/database permissions, path traversal prevention, hashes and encrypted-backup compatibility are required.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0073 — Implement a bitemporal point-in-time and data-vintage model

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data platform  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0072

**Problem**  
Datasets do not consistently distinguish economic period, publication time, availability time, ingestion time and later revisions.

**Why it matters**  
Long-term fundamental models and historical tests are invalid if restated or future-known information leaks into earlier decisions.

**Proposed implementation**
- Require effective/period start/end, published_at, available_at, observed_at, ingested_at, revised_at and revision number where applicable.
- Store raw observations append-only and derive as-of views by decision timestamp.
- Snapshot current-only public sources, such as Eurostat, on every ingest.
- Model amendments, restatements, corrections, retractions and supersession.
- Add timezone/precision confidence and fail closed when availability is ambiguous.

**Data, packages and external dependencies**
- ISSUE-0072 storage.
- Official filing timestamps and local import timestamps.
- Source metadata contracts.

**Acceptance criteria**
- Any historical query reproduces what the application could know at a specified instant.
- Revised facts never overwrite earlier vintages.
- Derived features and scores retain source-vintage hashes.
- Ambiguous availability is excluded from historical authority.

**Tests required**
- Synthetic revision fixtures.
- Look-ahead regression tests.
- Timezone/DST tests.
- As-of query property tests.

**UI requirement**  
Instrument History, Data Health and Audit expose vintages, amendments and corrections.

**Security and audit requirement**  
Append-only observation ledger, source checksums and immutable decision-time manifests.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0074 — Unify all scoring into a canonical score engine v3

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Scoring architecture  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0071; ISSUE-0073

**Problem**  
The rich simple-score path and legacy signal/scoring path use overlapping but different formulas, weights and missing-data rules.

**Why it matters**  
Formula drift makes rankings, explanations, backtests and future orders impossible to reconcile.

**Proposed implementation**
- Create one typed component contract for raw metric, transformation, peer group, score, authority, freshness, uncertainty and contribution.
- Separate attractiveness, expected return, risk/implementation and evidence confidence instead of compressing them into one number.
- Make stock, ETF, sector and horizon policies configuration-driven and versioned.
- Eliminate direct score-to-order logic; portfolio and order systems consume return distributions and risk.
- Provide migration adapters for old exports and historical score formulas.
- Generate explanations from the same calculation graph.

**Data, packages and external dependencies**
- ISSUE-0073 point-in-time views.
- Existing score fixtures and formula history.

**Acceptance criteria**
- One canonical result is used by UI, export, backtest, paper and proposal systems.
- Missing data reduce coverage/confidence rather than becoming neutral.
- Score and component contributions reconcile exactly.
- Legacy-versus-v3 differences are documented for migrated instruments.

**Tests required**
- Golden formula tests.
- Bounds/monotonicity property tests.
- Missing/conflict tests.
- Cross-surface reconciliation tests.

**UI requirement**  
Scores and Instrument workspaces show the separated outputs and formula version.

**Security and audit requirement**  
Signed formula registry and immutable score-run manifest; completed runs cannot be mutated by plugins.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0075 — Create formula, feature, dataset, model and policy version registries

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Reproducibility  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0072; ISSUE-0074

**Problem**  
Partial version fields exist, but there is no single lineage graph for every calculation and decision.

**Why it matters**  
Historical comparisons and model/order audits require exact reproducibility after code and data changes.

**Proposed implementation**
- Assign semantic versions and content hashes to schemas, formulas, features, datasets, models, optimisers, risk and execution policies.
- Record dependency graphs for every run.
- Add forward-only migrations and explicit invalidation rules.
- Prevent mutable aliases such as “latest” from being the sole historical reference.
- Expose compatibility, deprecation and required-rebuild metadata.

**Data, packages and external dependencies**
- ISSUE-0072 storage.
- Git commit, locked environment and package manifest.

**Acceptance criteria**
- Every score, forecast, target, proposal and order resolves to immutable versions.
- An upstream hash change invalidates dependent caches deterministically.
- Supported historical artefacts remain readable after migrations.
- What Changed identifies the exact version cause.

**Tests required**
- Lineage graph tests.
- Cache invalidation tests.
- Migration tests.
- Reproduction-from-manifest test.

**UI requirement**  
Audit, Diagnostics and What Changed expose lineage and compatibility.

**Security and audit requirement**  
Hash-chain lineage records; secrets and private notes are excluded from public manifests.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0076 — Define stable plugin contracts for providers, models, strategies and brokers

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Extensibility  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0071; ISSUE-0070

**Problem**  
New integrations currently risk spreading provider- or broker-specific assumptions throughout the application.

**Why it matters**  
A final product must add sources and brokers without changing core scoring, risk or UI logic.

**Proposed implementation**
- Define capability, configuration, health, fetch/import, schema, authority, licence, quota and audit contracts.
- Separate data providers, parsers, model challengers, strategies, optimisers and broker adapters.
- Require explicit unsupported, unavailable and degraded responses.
- Use entry-point/registry discovery only after allow-list validation.
- Provide conformance kits and sample plugins.

**Data, packages and external dependencies**
- Python packaging entry points or explicit local registry.
- Pydantic configuration schemas.

**Acceptance criteria**
- A plugin cannot write canonical stores directly or escalate authority.
- Every plugin declares licence, network, credential, quota and retention requirements.
- Conformance tests run without secrets.
- Disabling a plugin leaves mandatory workflows usable.

**Tests required**
- Contract tests.
- Malicious/invalid plugin tests.
- Version compatibility tests.
- Network-disabled tests.

**UI requirement**  
Provider, Model and Broker Status pages use one capability representation.

**Security and audit requirement**  
Plugin allow-list, path/network restrictions, secret isolation and SBOM inclusion.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0077 — Implement a durable resumable job DAG and workflow scheduler

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Workflow platform  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0072; ISSUE-0075

**Problem**  
Long-running imports, parsing, scoring, training and backtests are coordinated through UI-oriented activity state.

**Why it matters**  
Reliable completion requires idempotency, checkpoints, cancellation, dependency order and restart recovery.

**Proposed implementation**
- Represent work as typed jobs and dependency DAGs with immutable input hashes.
- Persist queued, running, succeeded, failed, cancelled and blocked states in SQLite.
- Add leases, heartbeats, checkpoints, bounded retries, cancellation and deduplication.
- Support CPU/GPU/memory declarations and concurrency limits.
- Emit one canonical event stream for UI and audit.

**Data, packages and external dependencies**
- ISSUE-0072 transactional store.
- Local worker process or bounded thread/process pool.

**Acceptance criteria**
- Application restart resumes or safely restarts eligible jobs.
- Duplicate button presses cannot duplicate committed outputs.
- Failed downstream jobs cannot publish partial generations.
- Every job reports inputs, outputs, timing and resource use.

**Tests required**
- Crash/restart tests.
- Idempotency tests.
- Cancellation tests.
- DAG failure-propagation tests.

**UI requirement**  
Global Jobs and Activity centre with dependency graph, logs and recovery actions.

**Security and audit requirement**  
Redacted logs, bounded outputs, safe subprocess environment and audit event hash chain.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0078 — Set performance, memory, storage and latency budgets with regression profiling

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Performance  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0077

**Problem**  
Optimisation work is qualitative and can regress as datasets and models grow.

**Why it matters**  
A local application must remain usable on declared hardware profiles and explain slow operations.

**Proposed implementation**
- Define budgets for startup, route render, common queries, refresh, 100/1,000/10,000-instrument screens, backtests and training.
- Add structured timing, memory and I/O telemetry.
- Profile hot paths and compare pandas, Polars, DuckDB SQL or vectorisation before replacing implementations.
- Add cache hit/invalidation metrics and storage-growth projections.
- Create benchmark baselines in CI.

**Data, packages and external dependencies**
- pytest-benchmark or equivalent.
- ISSUE-0151 hardware profiles.

**Acceptance criteria**
- Budgets and test datasets are versioned.
- Regressions above tolerance block release or require an approved waiver.
- UI remains responsive while work executes.
- Optimisations preserve numerical and lineage equivalence.

**Tests required**
- Microbenchmarks.
- End-to-end benchmarks.
- Memory-leak/soak tests.
- Numerical-equivalence tests.

**UI requirement**  
Diagnostics performance dashboard and per-job resource view.

**Security and audit requirement**  
Telemetry contains no secrets/private thesis content and remains local by default.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0079 — Establish open-source intake, licence, provenance and upstream-update governance

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Supply-chain governance  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0145; ISSUE-0149

**Problem**  
The roadmap proposes copying mature projects, but licence, security and maintenance review are not formalised.

**Why it matters**  
Casual copying can create legal obligations, vulnerabilities, incompatible architecture and unmaintainable forks.

**Proposed implementation**
- Record repository, exact commit/tag, licence, maintainers, release cadence, tests, security policy, dependencies and copied files.
- Classify permissive, weak-copyleft and strong-copyleft integration boundaries.
- Require NOTICE/attribution, local conformance tests and an upstream-diff/update policy.
- Prefer dependencies or adapters over copied cores.
- Review model-weight and dataset licences separately from source code.

**Data, packages and external dependencies**
- SBOM tooling under ISSUE-0145.
- Legal/terms review under ISSUE-0149.

**Acceptance criteria**
- No third-party code enters main without an approved intake record.
- Copied/modified code is traceable to exact upstream content.
- AGPL/LGPL components have approved process/linking boundaries.
- Abandoned or vulnerable dependencies have replacement plans.

**Tests required**
- Licence-policy tests.
- SBOM diff tests.
- Upstream compatibility tests.
- Attribution packaging tests.

**UI requirement**  
Settings/About shows third-party notices; System Map shows external components.

**Security and audit requirement**  
Signed intake records and automated licence/vulnerability scans.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0080 — Enforce a mandatory no-subscription, no-vendor-quota local-first data policy

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0070; ISSUE-0076

**Problem**  
The requirement for a free unrestricted core conflicts with keyed or commercially limited providers.

**Why it matters**  
Completion must be possible without recurring fees, API keys or per-call vendor quotas, while acknowledging lawful fair-use and broker limits.

**Proposed implementation**
- Define source tiers: local/user import, official bulk, official open API cached snapshot, best-effort unofficial and optional commercial.
- Permit only the first three tiers to be mandatory.
- Require offline replay from immutable cache for release tests.
- Document fair-use schedules; never claim that remote hosts have no throttling.
- Make broker/exchange costs and limits explicit external exceptions.

**Data, packages and external dependencies**
- SEC/Companies House bulk, Eurostat, World Bank, ISO MIC, official filings and user/broker imports.

**Acceptance criteria**
- Core analysis works with all optional providers disabled.
- Every metric declares minimum source tier and fallback.
- Quota exhaustion cannot corrupt or silently reduce authority.
- UI distinguishes free software from external trading/data costs.

**Tests required**
- No-network release test.
- All-optional-disabled test.
- Rate-limit/quota failure tests.
- Licence-policy tests.

**UI requirement**  
Provider Status and onboarding show source tier, cache status and optionality.

**Security and audit requirement**  
Terms/licence snapshots, polite access controls and redacted credentials.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0081 — Build a resumable bulk downloader, content-addressed cache and delta updater

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0072; ISSUE-0077; ISSUE-0080

**Problem**  
Large official datasets require robust acquisition rather than repeated row-level API calls.

**Why it matters**  
Bulk snapshots reduce quota dependence and make data reproducible, but partial or changed downloads can corrupt analysis.

**Proposed implementation**
- Support HTTP range/resume, ETag/Last-Modified, checksums, manifests, mirrors and retry backoff.
- Store raw files content-addressed and never mutate them.
- Parse into staged generations, validate, then atomically promote.
- Support full snapshots plus deltas and retention/compaction.
- Record source terms, retrieval time and expected update schedule.

**Data, packages and external dependencies**
- requests/httpx and standard ZIP/TAR parsers.
- ISSUE-0077 jobs and ISSUE-0072 storage.

**Acceptance criteria**
- Interrupted downloads resume or restart safely.
- Identical content is deduplicated.
- Changed remote content creates a new version and downstream invalidation.
- No partial parse is promoted.

**Tests required**
- Truncated/changed-server fixtures.
- Checksum mismatch tests.
- Resume/idempotency tests.
- Archive-bomb tests.

**UI requirement**  
Import Centre and Data Health show download, stage, validation and promotion.

**Security and audit requirement**  
Size/decompression limits, path traversal protection, allow-listed hosts and content-type validation.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0082 — Create a global entity, instrument, fund, share-class and listing identity master

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** UPDATEV2-0011; ISSUE-0073

**Problem**  
Ticker-centric identity cannot safely reconcile companies, funds, share classes, exchanges, currencies and corporate events.

**Why it matters**  
Every analytical and trading record must refer to a stable object even when tickers or listings change.

**Proposed implementation**
- Model legal entity, security/instrument, fund, share class and listing separately.
- Store ISIN, LEI, CIK, national IDs, ticker, MIC and lawfully available aliases.
- Track valid-from/to, successor/predecessor, mergers, delistings and confidence.
- Use deterministic matching plus a human-review queue.
- Import ISO MIC and public identity sources; never invent identifiers.

**Data, packages and external dependencies**
- ISO 10383 MIC list.
- SEC submissions.
- GLEIF/local LEI files where terms permit.
- User mappings.

**Acceptance criteria**
- All provider rows resolve or remain explicitly unresolved.
- Duplicate/conflicting identities are quarantined.
- Historical listings remain queryable after ticker changes.
- Orders reference a listing while research references canonical instrument/entity.

**Tests required**
- Identity fixture corpus.
- Fuzzy-match false-positive tests.
- Corporate-event migration tests.
- Duplicate/concurrency tests.

**UI requirement**  
Universe and Instrument pages show the identity graph, confidence and overrides.

**Security and audit requirement**  
Manual overrides are signed/audited; identifier sources and licences retained.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0083 — Implement automatic asset, sector, industry and strategy classification with confidence

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0082

**Problem**  
User-added instruments are not fully assigned to the correct stock sector, ETF strategy or sub-area.

**Why it matters**  
Sector-specific algorithms and peer comparisons depend on accurate, explainable classification.

**Proposed implementation**
- Use hierarchical rules from official filing codes, issuer descriptions, fund documents, benchmark names and holdings.
- Maintain an open internal taxonomy mapped to public SIC/NACE/NAICS-like codes; do not redistribute proprietary GICS/ICB content without rights.
- Produce candidate classifications, confidence, evidence and alternatives.
- Support human override with valid-from/to history.
- Classify special structures such as banks, insurers, REITs, BDCs, SPACs, ETFs, leveraged/inverse and funds-of-funds.

**Data, packages and external dependencies**
- ISSUE-0082 identity.
- SEC/Companies House industry codes, NACE and issuer documents.

**Acceptance criteria**
- Every enabled instrument has a supported class or explicit unresolved state.
- A sector adapter is not used below its confidence threshold.
- Overrides invalidate dependent scores and are historically versioned.
- Accuracy is measured on a labelled fixture set.

**Tests required**
- Labelled classification corpus.
- Ambiguous-entity tests.
- Override/history tests.
- Proprietary-taxonomy scan.

**UI requirement**  
Universe editor and Instrument header show evidence and override controls.

**Security and audit requirement**  
No opaque generative classifier may change authority without human review; private descriptions remain local.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0084 — Build corporate-action, total-return and currency-normalisation services

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0073; ISSUE-0082

**Problem**  
Price series can be wrong across splits, dividends, spin-offs, rights, mergers and currency changes.

**Why it matters**  
Fundamental returns, backtests and portfolio accounting require consistent raw and total-return views.

**Proposed implementation**
- Store raw OHLCV and corporate actions separately.
- Build adjusted-price and total-return series from explicit actions with provider reconciliation.
- Handle splits, cash/stock dividends, capital gains, rights, spin-offs, mergers, symbol/currency changes and declared withholding assumptions.
- Create base/local currency return views using point-in-time FX.
- Expose adjustment provenance and never overwrite raw prices.

**Data, packages and external dependencies**
- Official issuer/exchange/broker imports, yfinance best-effort actions and ECB/local FX sources.
- ISSUE-0082 identity.

**Acceptance criteria**
- Adjustment factors reconcile to actions.
- Backtests/accounting use declared total-return conventions.
- Provider discrepancies are visible and quarantined above tolerance.
- Currency conversions use dated source-linked rates.

**Tests required**
- Synthetic corporate-action cases.
- Cross-provider discrepancy tests.
- Dividend/FX accounting tests.
- Round-trip adjustment tests.

**UI requirement**  
Price chart can switch raw, adjusted, total return and local/base currency.

**Security and audit requirement**  
Corrections are append-only; source documents and broker statements are retained.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0085 — Implement exchange calendars, sessions, holidays, auctions and market-state service

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0082; ISSUE-0079

**Problem**  
Generic weekday logic causes stale-data, horizon and execution errors across global markets.

**Why it matters**  
Correct availability and next-session execution require listing-specific sessions and timezones.

**Proposed implementation**
- Use an audited calendar library such as exchange_calendars behind an internal service.
- Map listings to MIC, calendar and timezone.
- Model holidays, early closes, DST, auctions, settlement days and exceptional closures.
- Version manual corrections and provide unknown-calendar fail-closed state.
- Expose next valid decision and execution timestamps.

**Data, packages and external dependencies**
- ISO MIC.
- exchange_calendars or equivalent permissive library after intake.

**Acceptance criteria**
- Business-day horizons use the correct listing calendar.
- Orders never execute outside supported sessions.
- Staleness is measured in expected sessions, not generic weekdays.
- Historical calendar corrections are reproducible.

**Tests required**
- DST/early-close fixtures.
- Cross-market holiday tests.
- Unknown-MIC tests.
- Next-open integration tests.

**UI requirement**  
Instrument and order views show market state, timezone and next session.

**Security and audit requirement**  
Calendar overrides are audited and cannot retroactively alter completed decisions.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0086 — Create user, broker and exchange historical price, position and transaction import pipelines

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0036; ISSUE-0082

**Problem**  
There is no globally complete lawful free-unlimited market-data feed.

**Why it matters**  
Quota-independent operation therefore requires robust local import as a first-class source.

**Proposed implementation**
- Support CSV, Parquet, OFX/QIF where suitable and broker-specific statement templates through plugins.
- Map symbols, listings and currencies to canonical IDs.
- Preview schema, units, dates, duplicates, gaps and corporate actions before commit.
- Store raw files, mapping decisions and checksums.
- Allow incremental append, correction and rollback.

**Data, packages and external dependencies**
- ISSUE-0082 identity.
- User-owned or lawfully exported broker/exchange files.

**Acceptance criteria**
- Imports are idempotent and reconcile balances/row counts.
- Unknown fields or instruments enter review rather than guessed mappings.
- Imported data can satisfy mandatory price/accounting requirements.
- Template versions are tracked.

**Tests required**
- Golden broker fixtures.
- Malformed/duplicate/locale tests.
- Round-trip tests.
- Large-file tests.

**UI requirement**  
Import Centre offers a mapping wizard, preview diff and reconciliation report.

**Security and audit requirement**  
Spreadsheet-injection protection, archive/path limits, PII redaction and encrypted-backup support.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0087 — Expand official filing discovery and ingestion across supported jurisdictions

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** UPDATEV2-0012; UPDATEV2-0014; ISSUE-0081

**Problem**  
US and selected European filing support do not cover the intended stock universe.

**Why it matters**  
Long-term company analysis needs official statements and publication times wherever available.

**Proposed implementation**
- Create jurisdiction adapters using ESEF/OAM/national bulk sources.
- Prioritise UK Companies House company/accounts products, Nordic/EU OAMs and filings.xbrl.org-compatible records.
- Store raw filing packages, amendments and source terms.
- Define supported-jurisdiction coverage and manual-import fallback.
- Do not scrape inaccessible or prohibited sources.

**Data, packages and external dependencies**
- SEC EDGAR bulk.
- Companies House monthly/daily bulk.
- ESEF/OAM sources.
- ISSUE-0081.

**Acceptance criteria**
- Every supported jurisdiction has tested discovery, raw archive, identity mapping and unavailable states.
- Publication/availability times are captured.
- Coverage metrics are visible by country and instrument.
- Manual official filing import provides a no-quota fallback.

**Tests required**
- Real official fixtures.
- Jurisdiction conformance tests.
- Terms/robots tests.
- Amendment/identity tests.

**UI requirement**  
Filings workspace includes jurisdiction coverage and a manual acquisition queue.

**Security and audit requirement**  
Host allow-list, fair-access scheduler, parser sandbox and immutable raw evidence.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0088 — Build a versioned macro, factor, risk-free and benchmark data warehouse

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0080; ISSUE-0081; ISSUE-0073

**Problem**  
Macro context and factor benchmarks are fragmented and often current-only.

**Why it matters**  
Expected-return, risk, regime and attribution calculations require consistent dated reference series.

**Proposed implementation**
- Ingest and snapshot Eurostat, World Bank, ECB, US Treasury and selected public central-bank/statistical data.
- Ingest Kenneth French and AQR research-factor files with methodology and revision history.
- Create canonical units, frequency, country, currency, release/vintage and transformation metadata.
- Build risk-free curves/proxies by currency and horizon.
- Never use current revised values in historical tests.

**Data, packages and external dependencies**
- Official public datasets and downloadable research-factor files.
- ISSUE-0081; ISSUE-0073.

**Acceptance criteria**
- Datasets are locally replayable and independently updateable.
- Historical regimes and excess returns use decision-time vintages.
- Transformations are versioned and reversible.
- Missing country/currency series yield explicit unavailable states.

**Tests required**
- Source-parser fixtures.
- Vintage leakage tests.
- Unit/frequency conversion tests.
- Revision-diff tests.

**UI requirement**  
Macro/Factors workspace, Data Health and benchmark selectors.

**Security and audit requirement**  
Terms/licence metadata and content hashes; no redistribution beyond permitted terms.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0089 — Implement data anomaly detection, quarantine and cross-source reconciliation

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** UPDATEV2-0021; ISSUE-0073

**Problem**  
Invalid spikes, stale rows, unit errors, identity mistakes and provider disagreements can contaminate every calculation.

**Why it matters**  
Institutional discipline requires bad data to be stopped before scoring or orders.

**Proposed implementation**
- Define schema, range, continuity, OHLC, volume, unit, currency, duplicate, action and cross-source checks.
- Assign pass, warn, quarantine and block states with metric-specific tolerances.
- Maintain candidate values and deterministic source-selection rules.
- Create human review and resolution records.
- Propagate quality and uncertainty into features and authority.

**Data, packages and external dependencies**
- UPDATEV2-0021 conflict resolver.
- ISSUE-0073; ISSUE-0082; ISSUE-0084.

**Acceptance criteria**
- Quarantined data never enter canonical views.
- Resolved conflicts retain original candidates and decision evidence.
- Quality changes invalidate downstream artefacts.
- Data Health reports coverage, anomalies and unresolved impact.

**Tests required**
- Fault-injection/property tests.
- Unit/currency mix-up fixtures.
- Provider disagreement tests.
- Resolution replay tests.

**UI requirement**  
Data Health triage queue with diffs, sources and affected-result views.

**Security and audit requirement**  
Resolution permissions, append-only audit and safe raw-file handling.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0090 — Create a data catalogue, lineage graph and reproducible dataset snapshots

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Data programme  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0072; ISSUE-0075

**Problem**  
Users and models cannot inspect the complete path from raw source to derived result.

**Why it matters**  
Trust, cache invalidation and reproducibility require dataset-level lineage and quality contracts.

**Proposed implementation**
- Register every raw/clean/derived table with schema, owner, source, licence, update schedule, partitions, row counts and quality.
- Create immutable dataset snapshot IDs and dependency edges.
- Generate data dictionaries and impact analysis.
- Expose retention, compaction and stale/orphan artefacts.
- Integrate lineage with jobs and model runs.

**Data, packages and external dependencies**
- ISSUE-0072; ISSUE-0075; ISSUE-0089.

**Acceptance criteria**
- Every result links to a complete upstream snapshot graph.
- Impact analysis identifies artefacts affected by a source or formula change.
- The catalogue is generated rather than manually duplicated.
- Orphaned or incompatible datasets are flagged.

**Tests required**
- Lineage completeness tests.
- Schema-drift tests.
- Impact/invalidation tests.
- Catalogue/export tests.

**UI requirement**  
Data Catalogue and per-instrument provenance explorer.

**Security and audit requirement**  
Licence/PII classifications, access controls and redacted public exports.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0091 — Normalise multi-period financial statements, amendments and restatements

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** UPDATEV2-0012; ISSUE-0073

**Problem**  
Raw XBRL concepts and yfinance fields are not a stable cross-company statement model.

**Why it matters**  
All deeper stock metrics depend on comparable, point-in-time income, balance-sheet and cash-flow histories.

**Proposed implementation**
- Create canonical statement concepts with taxonomy/source mappings while retaining extensions.
- Handle fiscal calendars, durations, instant facts, dimensions, units, currencies and duplicate contexts.
- Build reported, latest-restated and as-known-at-date views.
- Store mapping confidence and manual review.
- Reconcile statement and cash-flow identities within declared tolerances.

**Data, packages and external dependencies**
- SEC, ESEF and Companies House official facts.
- Arelle.
- ISSUE-0073; ISSUE-0087.

**Acceptance criteria**
- At least five annual and twelve quarterly periods are assembled where filings permit.
- Restatements never overwrite prior as-known facts.
- Statement identities and mapping coverage are reported.
- Unsupported concepts remain visible and excluded.

**Tests required**
- Real filing corpus.
- Fiscal-calendar/unit/dimension tests.
- Restatement leakage tests.
- Reconciliation tests.

**UI requirement**  
Fundamentals shows reported versus restated histories and mapping coverage.

**Security and audit requirement**  
Raw filings remain immutable; parser version and concept/source evidence are retained.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0092 — Add profitability, margin durability, earnings quality and accrual analysis

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0091; ISSUE-0074

**Problem**  
Current stock quality uses a few point-in-time ratios and fixed thresholds.

**Why it matters**  
Long-term investors need persistent profitability and the quality of reported earnings, not only headline margins.

**Proposed implementation**
- Calculate gross, operating and net margins; ROA, ROE and ROIC; cash conversion; accruals; exceptional-item dependence; and margin stability.
- Use trailing and multi-year distributions, sector-relative percentiles and company-history robust scores.
- Distinguish negative, missing and structurally inapplicable metrics.
- Implement Piotroski-style and accrual-quality evidence as transparent components rather than branded black boxes.
- Delegate financial institutions and other special sectors to adapters.

**Data, packages and external dependencies**
- ISSUE-0091 statements.
- ISSUE-0098 peer cohorts.

**Acceptance criteria**
- Every component exposes formula, period, peer group, coverage and uncertainty.
- No universal threshold is used where sector economics differ.
- Restated and as-known variants are reproducible.
- Component contributions reconcile to the canonical score.

**Tests required**
- Formula/golden tests.
- Sector-applicability tests.
- Missing/negative tests.
- Monotonicity tests.

**UI requirement**  
Profitability and Earnings Quality panels with histories and peer percentiles.

**Security and audit requirement**  
No metric is inferred from unavailable line items; source lineage is mandatory.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0093 — Add balance-sheet strength, liquidity, leverage and distress analysis

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0091

**Problem**  
Debt/equity alone is insufficient and inapplicable across several sectors.

**Why it matters**  
Capital structure, maturity and liquidity determine survival and downside risk over long horizons.

**Proposed implementation**
- Calculate net debt, debt maturity buckets, interest/fixed-charge cover, current/quick ratios, working capital and covenant proxies.
- Add transparent Altman/Ohlson-like distress evidence only for applicable sectors.
- Track leases, pension deficits, guarantees and off-balance-sheet commitments where disclosed.
- Stress refinancing rates, revenue/margin shocks and FX debt.
- Use separate rules for banks, insurers and utilities.

**Data, packages and external dependencies**
- ISSUE-0091; ISSUE-0098; ISSUE-0115.

**Acceptance criteria**
- Metrics are sector-applicable and source-linked.
- Stress results show assumptions and confidence.
- Unavailable maturities/commitments reduce confidence rather than becoming zero.
- Distress labels remain probabilistic/contextual.

**Tests required**
- Formula/applicability tests.
- Stress tests.
- Unit/currency tests.
- Missing-commitment tests.

**UI requirement**  
Balance Sheet and Solvency panels with maturity timeline and scenarios.

**Security and audit requirement**  
Sensitive imported debt schedules stay local; no unsupported credit-rating claim is made.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0094 — Add cash-flow quality, capital allocation, shareholder yield and dilution analysis

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0091; ISSUE-0084

**Problem**  
Current analysis does not fully separate operating cash generation from financing, acquisitions or dilution.

**Why it matters**  
Long-term returns depend on how management converts earnings and deploys capital.

**Proposed implementation**
- Calculate operating cash conversion, maintenance/growth capex proxies, free cash flow, acquisition spend, dividends, buybacks, issuance and stock compensation.
- Compute net shareholder yield and per-share versus aggregate growth.
- Track payout safety, buyback timing/valuation and serial dilution.
- Separate recurring and one-off financing flows.
- Use rolling history and sector applicability.

**Data, packages and external dependencies**
- ISSUE-0091; ISSUE-0084.

**Acceptance criteria**
- Per-share and total-company measures are both visible.
- Share-count and corporate-action history reconcile.
- Cash-flow gaps reduce confidence.
- Capital-allocation components are decomposable and peer-relative.

**Tests required**
- Cash-flow identity tests.
- Split/share-count tests.
- Dilution/buyback fixtures.
- Missing-capex tests.

**UI requirement**  
Cash Flow and Capital Allocation panels with waterfall and history.

**Security and audit requirement**  
Maintenance-capex estimates are labelled as estimates, never reported facts.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0095 — Add growth, revisions, guidance and earnings-surprise evidence with optional imports

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P1  
**Evidence grade:** Moderate/Low  
**Dependencies:** ISSUE-0091

**Problem**  
Revenue/EPS growth and estimate revisions are weakly covered, while free global point-in-time analyst consensus is unavailable.

**Why it matters**  
Long- and medium-horizon analysis benefit from separating realised growth, management guidance and external expectations.

**Proposed implementation**
- Calculate reported revenue, operating profit, EPS, free-cash-flow and per-share growth with base-effect and acquisition flags.
- Parse official guidance only when structured or human-reviewed.
- Support user/broker-licensed consensus and estimate imports as optional data.
- Record revision dispersion, surprise and staleness where lawful history exists.
- Never use current Yahoo analyst fields in historical tests without point-in-time records.

**Data, packages and external dependencies**
- ISSUE-0091; ISSUE-0086; ISSUE-0073.

**Acceptance criteria**
- Core growth analysis works without analyst data.
- Consensus/revision fields remain N/A unless point-in-time imports exist.
- Organic/inorganic and per-share/aggregate distinctions are visible.
- Guidance extraction has source and review status.

**Tests required**
- Growth formula tests.
- Base-effect/restatement tests.
- Optional-data-disabled tests.
- Historical leakage tests.

**UI requirement**  
Growth & Expectations panel with separate reported, guidance and optional consensus sections.

**Security and audit requirement**  
Analyst-data licences and user ownership are recorded; restricted services are not scraped.

**Mandatory free/no-quota policy**  
Core reported-growth functionality is quota-independent. Analyst consensus is optional user-supplied evidence only.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0096 — Implement relative valuation, intrinsic-value scenarios, reverse DCF and residual-income models

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0091; ISSUE-0088

**Problem**  
Simple P/E and price/book thresholds cannot estimate long-term return or accommodate different business models.

**Why it matters**  
Valuation must show the assumptions required to justify the market price and the range of plausible outcomes.

**Proposed implementation**
- Implement sector-applicable EV/sales, EV/EBITDA, earnings, cash-flow, book and dividend measures.
- Build multi-stage DCF/FCFE, reverse DCF and residual-income models with explicit inputs.
- Use normalised margins/growth, capital needs, dilution, terminal assumptions and currency/risk-free inputs.
- Generate bull/base/bear and Monte Carlo or deterministic sensitivity grids.
- Separate reported facts, derived assumptions and user overrides.

**Data, packages and external dependencies**
- ISSUE-0091–ISSUE-0095; ISSUE-0088; ISSUE-0108.

**Acceptance criteria**
- Models fail closed when essential inputs are unavailable.
- Every output reconciles to displayed assumptions and cash flows.
- Sensitivity and model disagreement are visible.
- No single fair-value point is presented without a range and confidence.

**Tests required**
- Valuation identity tests.
- Known-model fixtures.
- Sensitivity monotonicity tests.
- Sector-applicability tests.

**UI requirement**  
Valuation Lab with assumptions, reverse-implied expectations and distributions.

**Security and audit requirement**  
Overrides/model versions are audited; no guaranteed fair-value language.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0097 — Add capital efficiency, reinvestment, intangible investment and business-quality proxies

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0091; ISSUE-0092

**Problem**  
ROE can be inflated by leverage and accounting treatment; intangible-intensive firms are poorly represented by book assets.

**Why it matters**  
Long-term compounding depends on incremental returns and durable reinvestment opportunities.

**Proposed implementation**
- Calculate ROIC, incremental ROIC, reinvestment rate, sales-to-capital, asset turns and economic-profit spreads.
- Provide optional transparent capitalisation of selected R&D/advertising costs with sensitivity.
- Track customer/supplier concentration and recurring revenue only from reliable disclosures.
- Estimate moat proxies through persistence rather than unsupported qualitative labels.
- Use multi-year and sector-relative analysis.

**Data, packages and external dependencies**
- ISSUE-0091; ISSUE-0092; ISSUE-0098.

**Acceptance criteria**
- Reported and adjusted metrics are always separate.
- Incremental measures enforce minimum history and stable denominators.
- Business-quality proxies expose data coverage and cannot override valuation/risk alone.
- Assumption sensitivity is exportable.

**Tests required**
- Formula/history tests.
- Intangible-adjustment tests.
- Outlier/denominator tests.
- Sector tests.

**UI requirement**  
Capital Efficiency panel with reported/adjusted toggle and persistence charts.

**Security and audit requirement**  
Derived qualitative proxies require source evidence and cannot be stated as facts.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0098 — Create the stock sector-adapter and peer-cohort framework

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0083; ISSUE-0074

**Problem**  
One formula set cannot treat banks, REITs, software and miners correctly.

**Why it matters**  
Institutional-style analysis uses common foundations plus sector-specific economics and peer comparisons.

**Proposed implementation**
- Define an adapter contract for metrics, exclusions, transformations, weights, risk checks and valuation methods.
- Build peer cohorts by country, currency, size, sector and business subtype with minimum samples.
- Use robust ranks/winsorisation and record peer membership as-of date.
- Support fallback to a broad stock model with reduced confidence.
- Version adapters and peer rules.

**Data, packages and external dependencies**
- ISSUE-0083 classification.
- ISSUE-0074 score engine.
- ISSUE-0091 statements.

**Acceptance criteria**
- Every stock selects exactly one primary adapter or explicit fallback.
- Peer cohort and sample size are visible and historically reproducible.
- Adapter changes invalidate dependent scores.
- No sector-inapplicable metric contributes.

**Tests required**
- Adapter conformance tests.
- Peer stability tests.
- Small-cohort tests.
- Historical-membership tests.

**UI requirement**  
Instrument page shows adapter, peer cohort and excluded metrics.

**Security and audit requirement**  
Manual adapter overrides are audited; proprietary taxonomy content is not required.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0099 — Implement bank, insurer and diversified-financial sector adapters

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0098

**Problem**  
Financial institutions have leverage, liquidity and accounting structures that make industrial-company ratios misleading.

**Why it matters**  
Banks and insurers require solvency, asset quality, underwriting and funding metrics.

**Proposed implementation**
- Banks: CET1/total capital where disclosed, tangible book, NIM, cost/income, loan growth, deposits, NPLs, provisions and liquidity.
- Insurers: combined/loss/expense ratios, solvency capital, reserves, premium growth, investment yield and reinsurance exposure.
- Diversified financials: funding, credit losses, capital and fee/interest mix.
- Use regulatory filings or manual official imports where available.
- Create financial-sector valuation and stress models.

**Data, packages and external dependencies**
- ISSUE-0098; official filings; optional national regulatory imports.

**Acceptance criteria**
- Industrial leverage/FCF rules are excluded.
- Regulatory metrics show source and reporting standard.
- Stress tests cover credit loss, funding and market shocks.
- Missing regulatory data lowers confidence and blocks high-authority labels.

**Tests required**
- Sector fixture tests.
- Accounting/unit tests.
- Stress tests.
- Cross-jurisdiction availability tests.

**UI requirement**  
Financial Institutions section with solvency and asset-quality history.

**Security and audit requirement**  
No inferred regulatory ratio is represented as filed; jurisdiction limitations are disclosed.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0100 — Implement REIT, utility and infrastructure sector adapters

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0098

**Problem**  
Conventional earnings and free-cash-flow metrics can misrepresent property and regulated/infrastructure businesses.

**Why it matters**  
Long-duration assets require asset value, contractual cash flow, leverage and regulatory analysis.

**Proposed implementation**
- REITs: FFO/AFFO where reported or safely derivable, NAV sensitivity, occupancy, lease maturity, LTV and interest cover.
- Utilities/infrastructure: regulated asset base, allowed returns, capex funding, leverage, coverage and tariff/regulatory exposure.
- Model inflation, rate and refinancing scenarios.
- Separate maintenance and expansion capital assumptions.
- Provide sector-specific valuation and payout tests.

**Data, packages and external dependencies**
- ISSUE-0098; ISSUE-0091; ISSUE-0115.

**Acceptance criteria**
- Sector-specific cash-flow definitions and assumptions are explicit.
- NAV/RAB remains unavailable without reliable inputs.
- Rate/inflation stress effects are visible.
- Payout and leverage checks reconcile to statements.

**Tests required**
- Sector formula fixtures.
- Scenario tests.
- Missing-NAV/RAB tests.
- Payout reconciliation tests.

**UI requirement**  
Real Assets panels with lease/regulatory and rate sensitivity.

**Security and audit requirement**  
Derived FFO/AFFO/NAV values are labelled and source-linked.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0101 — Implement energy, materials and industrial cyclical-sector adapters

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0098

**Problem**  
Point-in-time margins and valuation can be misleading near commodity and industrial cycle peaks or troughs.

**Why it matters**  
Long-term analysis must normalise through cycles and connect operational drivers to balance-sheet resilience.

**Proposed implementation**
- Energy/mining: production, unit costs, reserves/resource life, realised prices, hedges, sustaining capex and decommissioning.
- Industrials: order book, book-to-bill, backlog quality, aftermarket mix, utilisation and working capital.
- Use multi-cycle normalised margins and commodity/input scenarios.
- Track customer/project concentration and capital intensity where disclosed.
- Add cycle-sensitive valuation and distress checks.

**Data, packages and external dependencies**
- ISSUE-0098; ISSUE-0115; official commodity/macro series where available.

**Acceptance criteria**
- Normalised and spot-cycle metrics are separate.
- Operational metrics are N/A unless source-linked.
- Commodity/rate scenarios show portfolio impact.
- Adapters require adequate cycle history or reduce confidence.

**Tests required**
- Cycle fixtures.
- Unit/commodity mapping tests.
- Scenario tests.
- Insufficient-history tests.

**UI requirement**  
Cyclicals panel with drivers, cost and scenario history.

**Security and audit requirement**  
No reserve/resource or backlog claim without official issuer evidence.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0102 — Implement software, semiconductor, healthcare and biotechnology adapters

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Stock analysis  
**Priority:** P1  
**Evidence grade:** Moderate/Low  
**Dependencies:** ISSUE-0098

**Problem**  
Innovation and regulated sectors rely on intangibles, product cycles, concentration and binary risks not captured by generic ratios.

**Why it matters**  
Long-term quality and downside depend on recurring economics, R&D productivity, patents, pipeline and funding.

**Proposed implementation**
- Software: recurring revenue, retention when disclosed, gross margin, FCF, stock compensation and dilution.
- Semiconductors: inventory, utilisation, capex, gross margin, customer/end-market concentration and cycle.
- Healthcare/pharma: product concentration, patent/exclusivity, R&D and reimbursement.
- Biotech: cash runway, pipeline stage, trial/regulatory milestones and dilution; keep outcome probabilities low authority.
- Use only official filings/registries/manual evidence and explicit missing states.

**Data, packages and external dependencies**
- ISSUE-0098; ISSUE-0024 event model; ISSUE-0094 dilution.

**Acceptance criteria**
- Binary-event risk is not converted into precise probabilities without validated data.
- Cash runway and dilution reconcile.
- Recurring/pipeline metrics carry source and date.
- Generic valuation is replaced or confidence-capped where inapplicable.

**Tests required**
- Sector fixtures.
- Runway/dilution tests.
- Event-timing tests.
- Missing-disclosure tests.

**UI requirement**  
Innovation/Healthcare panels with milestone and concentration timelines.

**Security and audit requirement**  
Medical/regulatory content is contextual, source-linked and not clinical advice.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0103 — Implement ETF economics, fee, tracking and closure-quality analysis

**Status:** Proposed — add to `issues/open.md`  
**Epic:** ETF analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** UPDATEV2-0015; ISSUE-0084

**Problem**  
ETF analysis lacks complete fund-level economics and persistence measures.

**Why it matters**  
Long-term ETF outcomes depend on realised tracking, fees, scale, age and operational viability.

**Proposed implementation**
- Store TER/OCF, tracking difference/error, assets, flows where available, fund age, share-class structure, distributions and benchmark.
- Calculate realised tracking from point-in-time benchmark and total-return series.
- Model closure/merger risk from transparent proxies such as age, assets and flows, with uncertainty.
- Separate fund-level and share-class metrics.
- Track fee and document changes over time.

**Data, packages and external dependencies**
- UPDATEV2-0015/0017/0019.
- ISSUE-0084 total returns.
- Issuer/user imports.

**Acceptance criteria**
- Tracking metrics state benchmark, currency, horizon and coverage.
- Fee changes and share-class differences are historical.
- Closure risk is labelled as a proxy/model rather than a fact.
- Missing AUM/flow data do not become zero.

**Tests required**
- Tracking reconciliation tests.
- Share-class tests.
- Fee-version tests.
- Missing-benchmark tests.

**UI requirement**  
ETF Economics panel with cost and tracking history.

**Security and audit requirement**  
Issuer documents and model assumptions are retained; no commercial AUM feed is mandatory.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0104 — Implement ETF structural, legal, counterparty, lending and collateral risk analysis

**Status:** Proposed — add to `issues/open.md`  
**Epic:** ETF analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** UPDATEV2-0015; UPDATEV2-0018

**Problem**  
Physical/synthetic replication, derivatives, securities lending and collateral risks are not fully represented.

**Why it matters**  
Two ETFs with similar exposure can have materially different structural risks.

**Proposed implementation**
- Parse replication method, derivatives, counterparties, collateral, lending policy/revenue split, domicile, legal form and concentration limits.
- Build transparent risk flags and document conflicts.
- Track prospectus/report/KID/SFDR versions.
- Stress counterparty and collateral concentration when numeric data exist.
- Do not create alpha from sustainability or legal labels.

**Data, packages and external dependencies**
- UPDATEV2-0015; UPDATEV2-0017/0018/0020.

**Acceptance criteria**
- Every structural field has document, date, page and confidence.
- Unknown structure is explicit and confidence-caps the ETF score.
- Conflicts between factsheet, prospectus and holdings are visible.
- Synthetic/counterparty risk does not inherit stock credit metrics without evidence.

**Tests required**
- Parser fixtures.
- Conflict tests.
- Unknown-state tests.
- Stress calculation tests.

**UI requirement**  
ETF Structure & Documents panel.

**Security and audit requirement**  
Document parser sandbox, licence metadata and no hidden generative extraction.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0105 — Build complete ETF look-through exposure, factor, valuation and quality analytics

**Status:** Proposed — add to `issues/open.md`  
**Epic:** ETF analysis  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** UPDATEV2-0016; ISSUE-0082

**Problem**  
Top-holdings summaries do not support institutional portfolio exposure analysis.

**Why it matters**  
ETF selection and portfolio risk require coverage-adjusted look-through to issuers, sectors, countries, currencies and factors.

**Proposed implementation**
- Resolve holdings to canonical instruments/entities and aggregate nested funds.
- Calculate coverage-adjusted concentration, valuation, profitability, growth, factor and sustainability context where lawful data exist.
- Separate direct, derivative, cash and unresolved exposure.
- Create historical holdings snapshots and methodology-based expected turnover.
- Propagate uncertainty instead of renormalising away unknown weights.

**Data, packages and external dependencies**
- UPDATEV2-0016; ISSUE-0082; ISSUE-0090; ISSUE-0110.

**Acceptance criteria**
- Weights reconcile to disclosed totals within tolerance.
- Every aggregate reports resolved, unresolved and stale coverage.
- Nested-fund cycles are detected.
- Look-through exposures reconcile from ETF to portfolio.

**Tests required**
- Holdings reconciliation tests.
- Nested/cycle tests.
- Coverage-propagation tests.
- Factor aggregation tests.

**UI requirement**  
Interactive exposure tree, overlap, factor and valuation views.

**Security and audit requirement**  
Unsupported entity matches are prohibited and manual resolutions are audited.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0106 — Implement ETF liquidity, capacity, spread and premium-discount analysis

**Status:** Proposed — add to `issues/open.md`  
**Epic:** ETF analysis  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0128

**Problem**  
Volume and high-low proxies do not fully represent fund tradability or order capacity.

**Why it matters**  
ETF execution depends on exchange liquidity, underlying liquidity, spread, NAV dislocation and order size.

**Proposed implementation**
- Calculate rolling turnover, spread proxies, zero-volume days, gap risk and size-to-volume.
- Support imported bid/ask, indicative NAV/premium-discount and underlying-liquidity evidence when available.
- Model order-size slippage with conservative fallbacks.
- Separate primary-market capacity context from exchange volume.
- Flag stale and off-hours quotes.

**Data, packages and external dependencies**
- ISSUE-0085; ISSUE-0128; user/broker quote imports.

**Acceptance criteria**
- Capacity is order-size and horizon specific.
- Unavailable bid/ask/NAV evidence is explicit.
- Cost estimates widen under uncertainty and stress.
- ETF orders can be blocked by liquidity policy.

**Tests required**
- Synthetic order-size tests.
- Stale/off-hours tests.
- Spread/NAV missing tests.
- Stress tests.

**UI requirement**  
ETF Liquidity panel and order-preview capacity meter.

**Security and audit requirement**  
Imported quote licences are honoured; delayed data are not represented as real-time depth.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0107 — Add ETF domicile, tax, distribution, currency and hedging context

**Status:** Proposed — add to `issues/open.md`  
**Epic:** ETF analysis  
**Priority:** P1/P2  
**Evidence grade:** Moderate/Low  
**Dependencies:** ISSUE-0104; ISSUE-0088

**Problem**  
Domicile, withholding, accumulating/distributing structure and hedging can materially affect investor outcomes.

**Why it matters**  
Portfolio fit and net-return estimates need transparent jurisdiction and currency context without becoming personal tax advice.

**Proposed implementation**
- Store domicile, legal structure, distribution policy, base/trading/underlying currencies and hedge methodology.
- Model generic documented fund-level withholding or tax drag only when reliable.
- Keep user-configurable informational tax assumptions separate from the core score.
- Calculate hedge-cost/benefit scenarios from rate differentials and realised hedge behaviour.
- Display tax and legal limitations prominently.

**Data, packages and external dependencies**
- ETF issuer documents.
- ISSUE-0088 rates.
- ISSUE-0149 legal wording.

**Acceptance criteria**
- Core ETF quality does not assume the user’s tax residence.
- Tax/hedge assumptions are explicit, versioned and optional.
- Trading currency is not confused with economic currency exposure.
- Net-return scenarios show included/excluded tax effects.

**Tests required**
- Currency-mapping tests.
- Hedge-scenario tests.
- Tax-assumption-disabled tests.
- Document-provenance tests.

**UI requirement**  
ETF Tax & Currency context and portfolio exposure view.

**Security and audit requirement**  
Informational only; no personalised tax recommendation or hidden jurisdiction assumptions.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0108 — Implement horizon-aware probabilistic total-return distributions

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Expected return  
**Priority:** P0  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0074; ISSUE-0096; ISSUE-0105

**Problem**  
The application ranks evidence but does not provide a defensible long-term gain/loss distribution.

**Why it matters**  
Both final product functions require expected net return, downside and uncertainty for selectable horizons.

**Proposed implementation**
- Define horizon families: weeks, months, one-to-three years and three-to-ten years.
- Stocks: combine normalised earnings/cash-flow growth, shareholder yield, dilution, valuation change, FX and scenario assumptions.
- ETFs: combine look-through exposure return, income, fees, tracking, FX and implementation cost.
- Blend structural/fundamental, factor and calibrated forecast evidence through transparent ensembles.
- Output quantiles, probability of loss, expected shortfall and benchmark/cash-relative distributions.

**Data, packages and external dependencies**
- ISSUE-0091–ISSUE-0107; ISSUE-0088; ISSUE-0123.

**Acceptance criteria**
- Every horizon has a separate target, model and validation.
- Long-term estimates are not extrapolated daily TimesFM/Toto paths.
- Gross and net distributions reconcile with costs.
- Low coverage widens uncertainty or yields unavailable.

**Tests required**
- Decomposition tests.
- Scenario/quantile tests.
- Cost reconciliation tests.
- Horizon leakage tests.

**UI requirement**  
Expected Return panel with horizon selector, fan chart, scenarios and decomposition.

**Security and audit requirement**  
Model/assumption versions and uncertainty are mandatory; no guaranteed-return language.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0109 — Implement scenario, uncertainty, confidence and model-disagreement framework

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Expected return  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0108

**Problem**  
A point estimate or headline score hides data, parameter, model, scenario and execution uncertainty.

**Why it matters**  
Portfolio and execution decisions must know when estimates are too uncertain to use.

**Proposed implementation**
- Represent data, parameter, model, scenario and execution uncertainty separately.
- Create bull/base/bear plus historical and adversarial scenario sets.
- Calculate ensemble dispersion, confidence intervals and disagreement flags.
- Define confidence caps from coverage, staleness, conflicts and validation.
- Propagate uncertainty through return, risk, optimiser and proposal calculations.

**Data, packages and external dependencies**
- ISSUE-0108; ISSUE-0089; ISSUE-0123.

**Acceptance criteria**
- Every return output includes uncertainty decomposition.
- High disagreement cannot be averaged away silently.
- Configured confidence thresholds block promotion or ordering.
- Scenario assumptions are reproducible.

**Tests required**
- Uncertainty-propagation tests.
- Disagreement tests.
- Coverage-monotonicity tests.
- Scenario replay tests.

**UI requirement**  
Uncertainty and scenario comparison views across Instrument, Portfolio and Order Preview.

**Security and audit requirement**  
Confidence rules are policy-controlled and audit logged.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0110 — Build a transparent multi-factor risk model for stocks, ETFs and portfolios

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Risk model  
**Priority:** P0  
**Evidence grade:** Moderate/High  
**Dependencies:** ISSUE-0052; ISSUE-0059

**Problem**  
Correlation clusters and benchmark beta do not provide a complete institutional-style risk decomposition.

**Why it matters**  
Portfolio construction needs common factor, industry, country, currency and specific-risk estimates.

**Proposed implementation**
- Define market, size, value, momentum, quality/profitability, investment, low-volatility, industry, country and currency factors.
- Estimate exposures from transparent descriptors and ETF look-through.
- Estimate factor returns with robust cross-sectional methods and residual/specific risk.
- Use public reference factors for validation, not as a black-box replacement.
- Version universes, standardisation, winsorisation and constraints.

**Data, packages and external dependencies**
- ISSUE-0088 factors.
- ISSUE-0098 peers.
- ISSUE-0105 look-through.
- ISSUE-0073.

**Acceptance criteria**
- Instrument and portfolio risk decompose into factors and specific risk.
- Exposure coverage and standard errors are visible.
- ETF exposure reconciles with holdings coverage.
- The model is validated against public factor series and simple beta baselines.

**Tests required**
- Exposure/return fixtures.
- Cross-sectional robustness tests.
- Coverage reconciliation tests.
- Out-of-sample stability tests.

**UI requirement**  
Risk workspace with exposure, contribution and historical factor charts.

**Security and audit requirement**  
No proprietary Barra/Axioma data or formulas are copied; methodology and limitations are documented.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0111 — Implement robust covariance, volatility, correlation and tail-risk estimation

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Risk model  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0110

**Problem**  
Sample covariance is unstable and current risk metrics are limited.

**Why it matters**  
Optimisers and stress tests can become dangerously concentrated when risk estimates are noisy.

**Proposed implementation**
- Implement sample, EWMA, shrinkage, robust and factor-model covariance estimators.
- Report conditioning, effective sample, eigenvalue and stability diagnostics.
- Estimate downside volatility, VaR/expected shortfall, drawdown, tail dependence and liquidity-adjusted risk.
- Use block/bootstrap uncertainty and regime comparisons.
- Select estimators through out-of-sample validation rather than in-sample fit.

**Data, packages and external dependencies**
- NumPy/SciPy/scikit-learn covariance tools.
- ISSUE-0110 factor model.

**Acceptance criteria**
- Equal-weight and simple diagonal-risk baselines are always available.
- Ill-conditioned matrices are rejected or visibly regularised.
- Risk estimates include uncertainty and sample sufficiency.
- Portfolio risk reconciles to component contributions.

**Tests required**
- Positive-semidefinite/property tests.
- Ill-conditioned fixtures.
- Bootstrap tests.
- Out-of-sample estimator tests.

**UI requirement**  
Risk Model diagnostics and estimator comparison.

**Security and audit requirement**  
Estimator selection, parameters and failures are versioned and audited.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0112 — Create canonical benchmarks, peer sets, cash proxies and reference portfolios

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Benchmarking  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0051; ISSUE-0059

**Problem**  
A single broad benchmark cannot evaluate sector, currency, strategy or portfolio objectives.

**Why it matters**  
Professional evaluation requires appropriate alternatives and reference portfolios.

**Proposed implementation**
- Define broad, regional, country, sector/theme, factor, cash/risk-free and defensive references.
- Support a user-selected benchmark plus policy-suggested alternatives.
- Create equal-weight, cap-weight, current-portfolio and no-trade reference portfolios.
- Use total-return and currency-consistent series.
- Version constituent/methodology evidence where available.

**Data, packages and external dependencies**
- ISSUE-0088; UPDATEV2-0019; ISSUE-0084.

**Acceptance criteria**
- Every analysis declares its benchmark and cash alternative.
- Missing benchmark produces N/A rather than a hidden substitute.
- Attribution and validation share the same definitions.
- No-trade baseline is included in rebalance evaluation.

**Tests required**
- Currency/return reconciliation tests.
- Missing-benchmark tests.
- Benchmark-version tests.
- Reference-portfolio tests.

**UI requirement**  
Benchmark selector and comparison panels everywhere relevant.

**Security and audit requirement**  
Benchmark data terms and methodology sources are retained.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0113 — Implement a constrained portfolio-optimiser suite with robust baselines

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Portfolio construction  
**Priority:** P0  
**Evidence grade:** Moderate/High  
**Dependencies:** ISSUE-0021; ISSUE-0110; ISSUE-0111

**Problem**  
Target weights and simple allocation context are insufficient for portfolio decisions.

**Why it matters**  
Different objectives and uncertain inputs require multiple transparent methods and strong constraints.

**Proposed implementation**
- Provide equal weight, inverse volatility, minimum variance, equal risk contribution, HRP/HERC, maximum diversification, CVaR and Black–Litterman/robust mean-risk methods.
- Use CVXPY, Riskfolio-Lib or PyPortfolioOpt behind internal contracts after licence/security review.
- Support long-only, min/max weight, turnover, sector, factor, country, currency, liquidity and cash constraints.
- Compare optimisers out of sample and always show simple baselines.
- Expose binding constraints and sensitivity to inputs.

**Data, packages and external dependencies**
- ISSUE-0108 return distributions.
- ISSUE-0110/0111 risk.
- Riskfolio-Lib/CVXPY/PyPortfolioOpt.

**Acceptance criteria**
- Every solution is feasible, reproducible and reconciles weights.
- Solver failure falls back visibly instead of producing arbitrary weights.
- Naive baselines cannot be hidden.
- Input perturbation and concentration diagnostics are reported.

**Tests required**
- Constraint/property tests.
- Solver-failure tests.
- Perturbation tests.
- Baseline out-of-sample tests.

**UI requirement**  
Portfolio Optimiser Lab with frontier, allocations, constraints and comparisons.

**Security and audit requirement**  
Solver versions/parameters are audited; no target gains order authority without policy approval.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0114 — Implement turnover-, cost-, tax-lot- and cash-aware rebalancing

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Portfolio construction  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0113

**Problem**  
Ideal target weights can be uneconomic or impossible to trade.

**Why it matters**  
Long-term portfolio performance depends on controlling turnover, costs, cash, lots and minimum order constraints.

**Proposed implementation**
- Translate targets into integer or permitted fractional-lot proposals.
- Optimise the trade-off between target tracking and transaction/tax costs.
- Support configurable tax-lot accounting and informational tax models.
- Model cash buffers, settlement, minimum trade, broker fractions and restricted positions.
- Compare full, partial, deferred and no-trade alternatives.

**Data, packages and external dependencies**
- ISSUE-0113; ISSUE-0127 accounting; ISSUE-0128 cost models.

**Acceptance criteria**
- Proposals balance cash and positions within tolerance.
- All cost and lot assumptions are visible.
- No-trade and deferred alternatives are evaluated.
- Tax logic is optional and jurisdiction-labelled.

**Tests required**
- Accounting/integer tests.
- Cash/settlement tests.
- Minimum-order tests.
- Tax-lot scenario tests.

**UI requirement**  
Rebalance workspace with trade list, alternatives and drift after cost.

**Security and audit requirement**  
Personal tax assumptions are informational and broker constraints are validated before submission.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0115 — Build historical, hypothetical and reverse stress-testing engine

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Risk & scenarios  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0109; ISSUE-0110

**Problem**  
Regime labels and tail metrics do not quantify portfolio sensitivity to severe but plausible shocks.

**Why it matters**  
Institutional risk workflows test exposures before capital is allocated.

**Proposed implementation**
- Create historical replay, factor, rates, FX, equity, credit, commodity and liquidity-widening shocks.
- Build reverse stress to identify shocks that breach loss or risk limits.
- Propagate shocks through stock fundamentals, ETF look-through, FX, factor risk and costs.
- Support validated user-defined scenarios.
- Store scenario versions and assumptions.

**Data, packages and external dependencies**
- ISSUE-0109; ISSUE-0110/0111; ISSUE-0105.

**Acceptance criteria**
- Scenario PnL reconciles to instrument and factor contributions.
- Coverage gaps and nonlinear limitations are visible.
- Reverse stress identifies threshold and binding exposure.
- Scenarios are not represented as probability forecasts.

**Tests required**
- Known-shock fixtures.
- Contribution reconciliation tests.
- Reverse-stress solver tests.
- Coverage tests.

**UI requirement**  
Stress Lab and portfolio scenario comparison.

**Security and audit requirement**  
Scenario edits are audited; unauthorised scenarios cannot alter live limits.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0116 — Implement performance, risk, factor and decision attribution

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Attribution  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0021; ISSUE-0059

**Problem**  
Current benchmark fields do not explain where portfolio outcomes came from.

**Why it matters**  
Research and trading improvement require decomposition of return, risk, costs and decisions over time.

**Proposed implementation**
- Implement time- and money-weighted performance, allocation/selection attribution where applicable, factor attribution and currency effects.
- Attribute risk contribution, transaction costs, slippage, tax and cash drag.
- Compare model target, approved target, orders and fills.
- Link outcomes to decision journal and model versions.
- Handle partial coverage and residual/unexplained return.

**Data, packages and external dependencies**
- ISSUE-0110–ISSUE-0115; ISSUE-0127; ISSUE-0134.

**Acceptance criteria**
- Instrument contributions sum to portfolio return within tolerance.
- Factor and residual attribution show coverage and uncertainty.
- Costs reconcile to the ledger.
- Decision attribution separates model, human and execution effects.

**Tests required**
- Attribution identity tests.
- Multi-currency tests.
- Partial-coverage tests.
- Ledger reconciliation tests.

**UI requirement**  
Portfolio Performance & Attribution workspace.

**Security and audit requirement**  
Immutable period-close snapshots and audit links to source/model/order records.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0117 — Implement the local training centre, experiment tracker and model registry

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0027; ISSUE-0075

**Problem**  
Forecast runs exist, but there is no complete experiment lifecycle or governed promotion workflow.

**Why it matters**  
Trustworthy improvement requires reproducible datasets, trials, comparisons, artefacts and champion/challenger records.

**Proposed implementation**
- Create experiments, runs, parameters, metrics, artefacts, datasets, models and promotion states.
- Integrate MLflow locally or provide a compatible lightweight registry behind an adapter.
- Use ISSUE-0077 jobs for training, evaluation, cancellation and restart.
- Store code, environment, data and feature hashes plus final model cards.
- Provide live progress and completion reports.

**Data, packages and external dependencies**
- MLflow optional local service/library after intake.
- ISSUE-0075; ISSUE-0077.

**Acceptance criteria**
- Every model is traceable to data, code, parameters and evaluation.
- Only approved models can become challengers or champions.
- Failed/cancelled runs cannot publish model aliases.
- Experiments can be replayed offline.

**Tests required**
- Registry lifecycle tests.
- Crash/cancel tests.
- Artefact-integrity tests.
- Offline replay tests.

**UI requirement**  
Training Centre with run list, live metrics, comparisons and final report.

**Security and audit requirement**  
Model artefacts are verified, unsafe deserialisation is blocked and secrets are excluded.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0118 — Create synthetic and adversarial market, data-quality and execution generators

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0117

**Problem**  
Synthetic data is requested, but naive generated markets can teach artefacts and create false confidence.

**Why it matters**  
Synthetic scenarios are valuable for invariants, rare failures and robustness—not proof of alpha.

**Proposed implementation**
- Generate configurable regimes, correlations, jumps, volatility clusters, missingness, restatements, actions and provider conflicts.
- Generate order, fill, latency, partial-fill and reconciliation failures.
- Separate deterministic test fixtures from stochastic research simulations.
- Record generator parameters and seeds.
- Prohibit synthetic-only evidence from model or strategy promotion.

**Data, packages and external dependencies**
- NumPy/SciPy and optional reviewed stochastic-process libraries.
- ISSUE-0075.

**Acceptance criteria**
- All generated datasets are labelled synthetic.
- Seeds reproduce exact outputs.
- Generators cover declared edge cases and validate invariants.
- Promotion reports exclude synthetic performance from forward-evidence counts.

**Tests required**
- Distribution/property tests.
- Seed reproducibility tests.
- Accounting/failure fixtures.
- Authority-boundary tests.

**UI requirement**  
Training Centre synthetic scenario builder and robustness summary.

**Security and audit requirement**  
Synthetic data are never merged with real raw data or mislabelled in exports.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0119 — Build a leakage-safe feature store and target/label registry

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0073; ISSUE-0117

**Problem**  
Features and forecast targets are calculated in multiple paths without a central availability and horizon contract.

**Why it matters**  
Leakage-safe training requires immutable as-of features and precisely defined outcomes.

**Proposed implementation**
- Register feature definitions, lookbacks, availability delay, dependencies, units and missing policy.
- Materialise point-in-time feature matrices by decision timestamp.
- Define simple horizon returns, excess returns, drawdown/tail and optional event labels.
- Prevent overlapping-target leakage and record embargo requirements.
- Support offline and paper/live inference parity.

**Data, packages and external dependencies**
- ISSUE-0073; ISSUE-0074; ISSUE-0075.

**Acceptance criteria**
- Training and live inference use the same feature definitions.
- Every feature value is reproducible as-of time.
- Targets never enter features or preprocessing fit.
- Feature drift and coverage are measurable.

**Tests required**
- Look-ahead tests.
- Train/live parity tests.
- Missing/preprocessing tests.
- Target-overlap tests.

**UI requirement**  
Feature Catalogue and Training data preview.

**Security and audit requirement**  
Feature provenance and licences are retained; sensitive imported data are access-controlled.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0120 — Implement walk-forward, nested, purged and embargoed validation with multiple-testing control

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0119

**Problem**  
Current calibration and backtest diagnostics do not provide a complete leakage-safe selection protocol.

**Why it matters**  
Financial models are unusually vulnerable to serial dependence, repeated trials and regime selection.

**Proposed implementation**
- Provide rolling/expanding walk-forward and nested model/parameter selection.
- Purge overlapping labels and apply horizon-based embargo.
- Record every trial and estimate the effective independent trial count.
- Calculate DSR, PBO/CSCV and false-discovery controls where assumptions permit.
- Use block-bootstrap confidence intervals and untouched final tests.
- Require simple baselines and cost-adjusted outcomes.

**Data, packages and external dependencies**
- ISSUE-0119; ISSUE-0048; ISSUE-0122.

**Acceptance criteria**
- No final-test data influence model, feature or hyperparameter selection.
- All discarded trials are retained.
- Validation produces uncertainty and regime/subgroup results.
- Promotion fails when evidence is insufficient or unstable.

**Tests required**
- Synthetic leakage tests.
- Fold/embargo property tests.
- Trial-count tests.
- Known-noise false-positive tests.

**UI requirement**  
Validation designer and report in Training and Backtest Labs.

**Security and audit requirement**  
Split definitions and results are immutable and included in audit packets.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0121 — Create a baseline and challenger model zoo for return, risk and fundamentals

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0117; ISSUE-0120

**Problem**  
TimesFM and Toto are prominent, but no model should be judged without diverse simple and domain-specific challengers.

**Why it matters**  
Professional research promotes complexity only when it adds stable net value.

**Proposed implementation**
- Implement naive drift/mean, historical median, linear/ridge/elastic-net, tree boosting, robust regression, state-space and econometric baselines.
- Integrate Darts/statistical models where useful.
- Retain TimesFM/Toto as optional challengers and test finance-specific fine-tuning only under validation.
- Separate return, volatility, quantile and fundamental forecasting tasks.
- Standardise forecast distributions plus resource/latency metadata.

**Data, packages and external dependencies**
- statsmodels, scikit-learn and Darts.
- Optional LightGBM/XGBoost after intake.
- Existing TimesFM/Toto adapters.

**Acceptance criteria**
- Every complex model is compared with naive and linear baselines.
- Capability, horizon, data needs and licence are registered.
- Unavailable optional weights/packages yield N/A.
- No model is selected solely on in-sample accuracy.

**Tests required**
- Adapter/conformance tests.
- Baseline fixtures.
- Optional-dependency tests.
- Latency/resource tests.

**UI requirement**  
Forecast Lab model comparison and model cards.

**Security and audit requirement**  
Safe weight loading, offline mode, model licence/size/checksum and no remote-code execution.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0122 — Implement bounded hyperparameter optimisation, pruning and compute governance

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0120

**Problem**  
Unbounded search can be slow, overfit validation data and hide the number of attempts.

**Why it matters**  
Efficient training requires pruning, while statistical honesty requires recording every trial.

**Proposed implementation**
- Integrate Optuna or equivalent through an adapter.
- Define constrained search spaces, budgets, seeds, pruning, parallelism and cancellation.
- Run optimisation only inside nested validation.
- Record failed, pruned and completed trials and effective trial count.
- Apply CPU/GPU/memory/time quotas by hardware profile.

**Data, packages and external dependencies**
- Optuna after intake.
- ISSUE-0077; ISSUE-0120; ISSUE-0151.

**Acceptance criteria**
- Search never accesses final-test metrics.
- Every trial is persisted and contributes to multiple-testing metadata.
- Resource limits are enforced.
- A no-optimisation baseline remains available.

**Tests required**
- Nested-isolation tests.
- Pruning/restart tests.
- Resource-quota tests.
- Trial-ledger integrity tests.

**UI requirement**  
Training Centre optimisation history, parameter importance and resource view.

**Security and audit requirement**  
No arbitrary user code in objectives outside explicit developer/sandbox mode; artefacts are redacted.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0123 — Implement probabilistic and conformal forecast calibration

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0108; ISSUE-0120

**Problem**  
Current quantiles and calibration thresholds can appear authoritative after very few matured observations.

**Why it matters**  
Return distributions need empirically checked coverage and adaptation to model misspecification.

**Proposed implementation**
- Evaluate pinball loss/CRPS, interval coverage/width, PIT/rank diagnostics, direction and scaled error.
- Add split/conformal or rolling calibration for eligible forecasts.
- Calibrate by model, horizon, asset class and regime with conservative minimum samples.
- Track calibration drift and fallback/widening policies.
- Never infer strong confidence from only a handful of observations.

**Data, packages and external dependencies**
- Darts conformal components or a reviewed local implementation.
- ISSUE-0120; ISSUE-0108.

**Acceptance criteria**
- Evidence thresholds are configurable and conservative.
- Coverage and uncertainty are reported with confidence intervals.
- Poor calibration reduces authority or widens intervals.
- Calibration uses only prior matured outcomes.

**Tests required**
- Coverage simulation tests.
- Chronology tests.
- Small-sample tests.
- Fallback/widening tests.

**UI requirement**  
Forecast calibration dashboard and reliability diagrams.

**Security and audit requirement**  
Calibration state/version is linked to every forecast and proposal.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0124 — Implement model monitoring, drift, champion/challenger and retirement governance

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model research  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0117; ISSUE-0123

**Problem**  
A trained model can decay or encounter unsupported regimes after promotion.

**Why it matters**  
Paper and live authority require continuous performance, data and operational monitoring.

**Proposed implementation**
- Monitor feature/target distributions, coverage, calibration, error, turnover, costs and subgroup performance.
- Define warning, demotion, retirement and rollback policies.
- Run challengers shadow-only until evidence matures.
- Detect stale model, data and formula versions.
- Create model cards with intended use, limitations and prohibited use.

**Data, packages and external dependencies**
- ISSUE-0117; ISSUE-0123; ISSUE-0129.

**Acceptance criteria**
- Drift thresholds trigger typed alerts and cannot auto-promote challengers.
- Champion rollback is tested and preserves audit history.
- Performance is assessed net of costs and against baselines.
- Retired models cannot create new proposals.

**Tests required**
- Drift simulation tests.
- Promotion/demotion state tests.
- Rollback tests.
- Subgroup-monitoring tests.

**UI requirement**  
Model Operations page and What Matters digest.

**Security and audit requirement**  
Role/authority controls, immutable promotion records and signed model artefacts.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0125 — Implement a deterministic event-driven, order-level backtest engine

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Backtest & execution  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0028; ISSUE-0050

**Problem**  
The current vectorised rebalance simulator does not model order lifecycle or research-to-paper parity.

**Why it matters**  
Trustworthy paper/live preparation requires the same timing and accounting semantics in historical simulation.

**Proposed implementation**
- Model market clock, data events, signals, targets, proposals, orders, acknowledgements, partial fills, cancellations and expiry.
- Use listing calendars and explicit decision, arrival and fill timestamps.
- Support the market and limit orders needed for long-horizon stocks/ETFs.
- Replay immutable historical events and policies.
- Consider LEAN or NautilusTrader as a separate engine only after an integration proof and licence review.

**Data, packages and external dependencies**
- ISSUE-0085; ISSUE-0127; ISSUE-0128; ISSUE-0079.

**Acceptance criteria**
- No fill precedes an order or valid market session.
- Backtest, paper and proposal contracts are identical.
- Deterministic replay produces identical ledger hashes.
- Unsupported execution data fail closed.

**Tests required**
- Event-ordering property tests.
- Partial/cancel tests.
- Session tests.
- Replay-determinism tests.

**UI requirement**  
Backtest event timeline, orders, fills and state inspection.

**Security and audit requirement**  
Strategy code cannot bypass risk/order policy; any external engine is isolated and version-pinned.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0126 — Implement point-in-time universes, delistings and survivorship-bias controls

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Backtest & execution  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0082; ISSUE-0073

**Problem**  
Current configured/candidate universes do not constitute historical investable universes.

**Why it matters**  
Survivorship and selection bias can materially overstate long-term strategy performance.

**Proposed implementation**
- Store universe membership, listing status, availability and delisting/successor events by date.
- Use point-in-time membership for screens, peers and backtests.
- Import delisted securities and terminal returns where lawful data are available; otherwise quantify gaps.
- Freeze user-created historical universe snapshots.
- Prevent current classifications and constituents from leaking backwards.

**Data, packages and external dependencies**
- ISSUE-0082; ISSUE-0073; user/broker/public historical imports.

**Acceptance criteria**
- Historical runs contain only then-known eligible instruments.
- Delistings are not silently dropped.
- Coverage and survivorship limitations are reported.
- Peer and factor universes use matching snapshots.

**Tests required**
- Synthetic delisting tests.
- Constituent-leakage tests.
- Missing-terminal-return tests.
- Universe replay tests.

**UI requirement**  
Backtest Universe and Coverage panels.

**Security and audit requirement**  
Source/licence and unresolved delisting data are visible; no terminal return is invented.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0127 — Create the double-entry portfolio, cash, FX, fee, tax and corporate-action ledger

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Trading foundation  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0072; ISSUE-0084

**Problem**  
Paper/live PnL cannot be trusted without a canonical accounting ledger.

**Why it matters**  
Orders and fills must reconcile positions, cash, income, fees, FX and corporate actions across restarts.

**Proposed implementation**
- Implement double-entry journal entries with decimal quantities and money.
- Model accounts, subaccounts, positions, lots, cash, settlements, fees, dividends, withholding, splits, mergers and FX.
- Generate positions and PnL as projections from ledger entries.
- Support imported broker statements and reconciliation adjustments without deleting history.
- Define base/local currency valuation and period-close snapshots.

**Data, packages and external dependencies**
- ISSUE-0072 SQLite.
- ISSUE-0084; ISSUE-0086.

**Acceptance criteria**
- The ledger balances for every transaction.
- Positions/cash can be rebuilt from zero by replay.
- Corrections use reversing entries.
- Broker and paper ledgers share schema but separate authority.

**Tests required**
- Accounting property tests.
- Corporate-action tests.
- Multi-currency/settlement tests.
- Replay/reconciliation tests.

**UI requirement**  
Portfolio ledger, cash, lots and reconciliation views.

**Security and audit requirement**  
Encrypted sensitive account data, append-only audit and decimal-safe serialisation.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0128 — Implement spread, slippage, market-impact, capacity and execution-cost models

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Trading foundation  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0064; ISSUE-0106

**Problem**  
Static basis-point assumptions cannot reflect order size, liquidity or stressed conditions.

**Why it matters**  
Expected net return, optimiser turnover and execution decisions require consistent cost models.

**Proposed implementation**
- Provide fixed, spread, volatility/volume and square-root-style impact models with conservative fallbacks.
- Estimate costs by instrument, listing, order type, size and session.
- Calibrate from imported historical quotes/fills when available.
- Stress spreads, gaps, FX and commissions.
- Separate research estimates from realised transaction-cost analysis.

**Data, packages and external dependencies**
- ISSUE-0106; ISSUE-0086; ISSUE-0125.

**Acceptance criteria**
- Cost estimates are finite, monotonic with size and uncertainty-aware.
- Missing microstructure data widen estimates.
- The same model feeds return netting, optimiser and paper backtest.
- Realised fills do not rewrite prior estimates.

**Tests required**
- Monotonic/property tests.
- Known-fill calibration tests.
- Missing/stress tests.
- Cross-module reconciliation tests.

**UI requirement**  
Cost/Capacity panel and order preview.

**Security and audit requirement**  
Imported broker fills remain private; cost-model changes are versioned.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0129 — Implement the full paper broker, frozen proposal ledger and forward evidence service

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Paper trading  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0031; ISSUE-0057

**Problem**  
The current paper issue describes a PnL tracker rather than an operational simulation.

**Why it matters**  
Forward evidence must test signals, portfolio decisions, orders, accounting and monitoring before capital is at risk.

**Proposed implementation**
- Create isolated paper accounts using the canonical ledger and event engine.
- Freeze every proposal with data, formula, model, portfolio and policy hashes.
- Support accept, reject, defer and auto-paper modes; orders, fills, fees, actions and daily marks.
- Mature configurable outcomes and benchmark/cash comparisons.
- Track operational errors separately from investment performance.

**Data, packages and external dependencies**
- ISSUE-0125; ISSUE-0127; ISSUE-0128; ISSUE-0057.

**Acceptance criteria**
- Paper accounts survive restart and replay exactly.
- No broker network call is possible in paper mode.
- Accepted, rejected and deferred proposals retain outcomes.
- Performance, risk, costs and incidents are attributable.

**Tests required**
- Paper lifecycle E2E.
- No-network/static broker tests.
- Restart/replay tests.
- Forward-maturation tests.

**UI requirement**  
Paper Trading operations workspace and per-instrument history.

**Security and audit requirement**  
Hard network isolation, separate configuration and immutable evidence ledger.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0130 — Implement the target-to-proposal policy and authority engine

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Trading foundation  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0070; ISSUE-0114

**Problem**  
A score or forecast must not directly become an order.

**Why it matters**  
Portfolio constraints, confidence, events, liquidity and authority must mediate every action.

**Proposed implementation**
- Transform expected returns and risk into target portfolios through an approved optimiser policy.
- Diff current and target state into proposals with rationale, size, timing and expiry.
- Apply data/model freshness, confidence, event, liquidity, cost, concentration and account constraints.
- Represent no-trade, defer, reduce and manual-review outcomes.
- Use the staged authority state machine from ISSUE-0070.

**Data, packages and external dependencies**
- ISSUE-0108–ISSUE-0115; ISSUE-0127/0128.

**Acceptance criteria**
- No proposal can be created from a headline score alone.
- Every proposal lists passed/failed gates and alternatives.
- Output is deterministic for immutable inputs.
- Proposal authority cannot exceed strategy/model/account stage.

**Tests required**
- Gate-ordering tests.
- Boundary/threshold tests.
- Determinism tests.
- Unauthorised-escalation tests.

**UI requirement**  
Proposal Review and Order Preview with gate evidence.

**Security and audit requirement**  
Policy versions are signed/audited; overrides require reason, scope and limits.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0131 — Implement broker adapter contracts, read-only synchronisation and reconciliation

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Broker integration  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0066; ISSUE-0127

**Problem**  
Future execution cannot rely on local projections or websocket state as truth.

**Why it matters**  
Read-only account reconciliation is the prerequisite for safe order submission.

**Proposed implementation**
- Define official broker-adapter methods for accounts, cash, positions, orders, fills, fees and market status.
- Start with read-only sync and imported statements.
- Use idempotent external/client IDs and reconcile snapshots/events to the local ledger.
- Handle partial fills, cancellations, corrections, disconnects and clock skew.
- Evaluate an official SDK or isolated LEAN/Nautilus adapter; never scrape broker UI.

**Data, packages and external dependencies**
- ISSUE-0076; ISSUE-0127; ISSUE-0066.

**Acceptance criteria**
- Read-only reconciliation detects and classifies every divergence.
- Broker state cannot be overwritten by local assumptions.
- Adapter failure leaves research/paper usable and blocks order authority.
- Credentials are never logged or exported.

**Tests required**
- Mock broker conformance suite.
- Disconnect/duplicate/out-of-order tests.
- Statement reconciliation tests.
- Credential-redaction tests.

**UI requirement**  
Broker Status, Reconciliation and read-only account views.

**Security and audit requirement**  
OS credential store/encrypted vault, least privilege, official API terms and network allow-list.

**Mandatory free/no-quota policy**  
Adapter software is free/open, but broker accounts, commissions, market-data subscriptions and broker pacing limits are unavoidable external constraints.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0132 — Implement independent pre-trade controls, kill switches and operational limits

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Execution safety  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0131

**Problem**  
Model and strategy code must not control its own safety limits.

**Why it matters**  
Automatic or manual order submission requires independent hard controls.

**Proposed implementation**
- Implement maximum order/position/gross/net/sector/factor/currency exposure, turnover, cash, daily loss and drawdown limits.
- Block stale/conflicted data, expired models, closed markets, duplicate orders and configured high-risk events.
- Add per-strategy/account and global disable, cooldown and emergency cancel.
- Evaluate limits against reconciled broker state.
- Require strong confirmation for sensitive stage changes.

**Data, packages and external dependencies**
- ISSUE-0130; ISSUE-0131; ISSUE-0070.

**Acceptance criteria**
- Hard limits cannot be overridden by model code.
- Kill switches are tested in paper and broker sandbox/read-only-compatible paths.
- Every block/override is audited.
- Unknown broker/account state blocks new orders.

**Tests required**
- Limit-boundary/property tests.
- Race/duplicate tests.
- Kill-switch drills.
- Configuration-tamper tests.

**UI requirement**  
Risk Controls console with current headroom and kill switch.

**Security and audit requirement**  
Separate permissions, secure confirmation, append-only incidents and fail-closed defaults.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0133 — Implement staged canary live execution with explicit promotion gates

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Execution  
**Priority:** P0  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0132; ISSUE-0152

**Problem**  
The target product includes automation, but immediate broad live trading would bypass paper and operational evidence.

**Why it matters**  
A canary stage limits financial and operational harm while validating the complete system.

**Proposed implementation**
- Permit live submission only after final certification of research, paper, read-only and draft-order stages.
- Restrict approved strategy, instruments, account, order types, value, frequency and trading window.
- Require dry-run/order preview and broker acknowledgement.
- Start with manually confirmed draft orders, then separately approve capped automatic mode.
- Auto-demote on incidents, drift, reconciliation or loss-limit breach.

**Data, packages and external dependencies**
- ISSUE-0070; ISSUE-0129; ISSUE-0131; ISSUE-0132; ISSUE-0152.

**Acceptance criteria**
- Live mode is opt-in, disabled on fresh install and visually distinct.
- Capped authority cannot expand through configuration alone.
- Every order traces to immutable proposal/control evidence.
- Rollback, demotion and emergency shutdown are proven.

**Tests required**
- Broker-sandbox tests where available.
- Permission/config tests.
- Canary-limit tests.
- Incident/demotion tests.

**UI requirement**  
Live Operations workspace with unmistakable stage, limits and confirmations.

**Security and audit requirement**  
Independent controls, encrypted secrets, tamper-evident audit, incident runbooks and external-cost disclosure.

**Mandatory free/no-quota policy**  
The app software can remain free/open; real trading is inherently subject to broker, exchange, tax, commission and market-data terms and costs.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0134 — Implement post-trade transaction-cost, execution-quality and decision attribution

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Execution analytics  
**Priority:** P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0131; ISSUE-0116

**Problem**  
Backtest assumptions and realised fills are not systematically compared.

**Why it matters**  
Execution improvement and strategy evaluation require separating alpha, timing, costs and operational slippage.

**Proposed implementation**
- Calculate decision, arrival, open/close, benchmark and realised prices.
- Attribute spread, delay, impact, FX, commission and opportunity cost.
- Compare forecast and realised cost by model and venue.
- Feed calibration diagnostics without rewriting past estimates.
- Link to portfolio and decision attribution.

**Data, packages and external dependencies**
- ISSUE-0128; ISSUE-0131; ISSUE-0116.

**Acceptance criteria**
- Fill costs reconcile to the ledger.
- TCA separates estimate and realisation.
- Calibration uses only completed fills.
- Coverage and benchmark limitations are visible.

**Tests required**
- Known-fill fixtures.
- Ledger-reconciliation tests.
- Benchmark-timing tests.
- Calibration-chronology tests.

**UI requirement**  
TCA dashboard and per-order drill-down.

**Security and audit requirement**  
Private order/fill data are protected and aggregated exports support redaction.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0135 — Implement incident management, recovery, reconciliation and operational drills

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Execution safety  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0131; ISSUE-0132

**Problem**  
Execution systems fail through networks, providers, clocks, processes, storage and human error.

**Why it matters**  
Safety depends on rehearsed recovery, not only code-path unit tests.

**Proposed implementation**
- Define incident severities, runbooks, ownership, evidence capture and post-mortems.
- Simulate partitions, stale data, duplicate/out-of-order events, broker mismatch, database corruption and clock drift.
- Add safe degraded modes, order freeze and reconciliation recovery.
- Schedule periodic paper/canary drills.
- Track corrective actions and recurrence.

**Data, packages and external dependencies**
- ISSUE-0040; ISSUE-0077; ISSUE-0131/0132.

**Acceptance criteria**
- Every critical failure has a tested runbook.
- Unknown state causes freeze rather than speculative retry.
- Recovery reconciles broker and ledger before re-enabling.
- Post-mortems and evidence are immutable.

**Tests required**
- Chaos/fault-injection tests.
- Recovery drills.
- Retry-storm tests.
- Clock/database-corruption tests.

**UI requirement**  
Incidents & Recovery operations centre.

**Security and audit requirement**  
Restricted incident data, redacted export and tamper-evident logs.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0136 — Create a typed local application API and page-view-model layer

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Frontend & API  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0071

**Problem**  
Flet pages call domain calculations and mutable application state directly.

**Why it matters**  
A stable API/view-model boundary is needed for performance, testing, future frontend options and safe commands.

**Proposed implementation**
- Define typed query and command contracts for universe, instruments, scores, forecasts, portfolios, jobs, paper and operations.
- Return immutable paginated view models.
- Use local in-process transport first; optionally expose an authenticated localhost FastAPI service.
- Add optimistic concurrency and idempotency keys for commands.
- Generate client and schema documentation.

**Data, packages and external dependencies**
- ISSUE-0071; ISSUE-0077; Pydantic; optional FastAPI.

**Acceptance criteria**
- Pages do not execute heavy calculations during render.
- Commands and queries have stable contracts and errors.
- Large tables are paginated or virtualised.
- A second frontend can consume the same API without importing domain internals.

**Tests required**
- Contract tests.
- Concurrency/idempotency tests.
- Pagination/load tests.
- Local-API authentication tests.

**UI requirement**  
All final workspaces consume view models.

**Security and audit requirement**  
Local binding by default, CSRF/authentication if HTTP, no secrets in responses and command authorisation.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0137 — Deliver frontend v2 design system and task-oriented information architecture

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Frontend & API  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0136

**Problem**  
The existing UI is broad but dense, text-heavy and route-centric.

**Why it matters**  
Professional research requires clear hierarchy, consistent interaction and separation of research, portfolio and operations tasks.

**Proposed implementation**
- Create design tokens, typography, spacing, states, charts, tables, forms, dialogs and notification patterns.
- Organise top-level workspaces as Home, Discover, Instrument, Portfolio, Models, Backtest/Paper, Data Health, Audit and Settings.
- Provide compact, default and advanced evidence modes.
- Stabilise Flet first; decide on React/Tauri only through a measured proof of concept and ADR.
- Create visual specifications and a component catalogue.

**Data, packages and external dependencies**
- ISSUE-0136; current Flet stack.
- Optional React/Tauri proof only after intake/ADR.

**Acceptance criteria**
- Every final feature has consistent empty, loading, success, warning and error states.
- No important function remains backend-only.
- Visual hierarchy separates decision, uncertainty, evidence and diagnostics.
- Frontend technology decision is documented with measured costs.

**Tests required**
- Component tests.
- Visual regression tests.
- Responsive/accessibility tests.
- User-journey tests.

**UI requirement**  
Application-wide redesign.

**Security and audit requirement**  
No remote telemetry by default; new web dependencies receive supply-chain review.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0138 — Build professional research, comparison, charting and screening workspaces

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Frontend & API  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0137

**Problem**  
Existing tables and detail panels do not yet provide an integrated analyst workflow.

**Why it matters**  
Users need to move from discovery to evidence, comparison, scenarios and decision efficiently.

**Proposed implementation**
- Create multi-instrument comparison with aligned units, currencies and horizons.
- Add linked price, fundamentals, factor, score, return-distribution, scenario and holdings charts.
- Create saved screens, notes, evidence bookmarks and exportable research packets.
- Use virtualised tables, cross-filtering and drill-down.
- Show coverage and uncertainty in every visual.

**Data, packages and external dependencies**
- ISSUE-0136/0137; ISSUE-0074; ISSUE-0090; ISSUE-0108.

**Acceptance criteria**
- Stock and ETF workflows have equal depth and test coverage.
- Displayed and exported values reconcile to canonical queries.
- Partial evidence is visually distinct without colour-only communication.
- Saved workspaces reproduce filters and versions.

**Tests required**
- Numerical chart/table tests.
- Large-universe performance tests.
- Visual/accessibility tests.
- Saved-workspace tests.

**UI requirement**  
Discover, Instrument and Comparison workspaces.

**Security and audit requirement**  
Private notes remain local/encrypted and research-packet exports support redaction.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0139 — Build portfolio, training, paper and live operations workspaces

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Frontend & API  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0136; ISSUE-0137

**Problem**  
Operational workflows are absent or distributed across diagnostics pages.

**Why it matters**  
Portfolio optimisation, experiments, paper accounts and staged live operation require clear states and controls.

**Proposed implementation**
- Portfolio: holdings, risk, scenarios, optimiser, rebalance and attribution.
- Training: jobs, trials, validation, model cards and promotion.
- Paper/live: account, proposals, orders, fills, limits, reconciliation, incidents and TCA.
- Use unmistakable authority-stage and environment banners.
- Provide command preview, confirmation, progress, cancellation and recovery.

**Data, packages and external dependencies**
- ISSUE-0113–ISSUE-0135; ISSUE-0136/0137.

**Acceptance criteria**
- Every state-changing action has preview, authority, result and audit link.
- Paper and live are visually and technically separated.
- Unknown or reconciling state blocks submission.
- Keyboard and narrow-window workflows remain usable.

**Tests required**
- State-machine UI tests.
- Paper/live separation tests.
- Failure/recovery E2E.
- Visual/accessibility tests.

**UI requirement**  
Portfolio, Training Centre and Operations.

**Security and audit requirement**  
Role/confirmation controls, no credential display and secure session handling.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0140 — Complete accessibility, global search, command palette, localisation and unit formatting

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Frontend & API  
**Priority:** P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0137

**Problem**  
A dense finance application is difficult to navigate and can mislead through inconsistent formats.

**Why it matters**  
Completion requires accessible operation and clear British/European formats across every workspace.

**Proposed implementation**
- Target WCAG 2.2 AA where technically feasible.
- Add keyboard-first command palette and global instrument/evidence search.
- Centralise date, timezone, currency, percentage, basis-point and number formatting.
- Support a localisation architecture with British English as default.
- Add reduced motion, high contrast, focus and screen-reader labels.

**Data, packages and external dependencies**
- ISSUE-0137; ISSUE-0136.

**Acceptance criteria**
- All critical journeys are keyboard-operable.
- No status depends only on colour.
- Dates, currencies and units are unambiguous.
- Search results respect authority and permissions.

**Tests required**
- Automated accessibility scans plus manual review.
- Keyboard/focus tests.
- Locale/unit tests.
- Search-permission tests.

**UI requirement**  
Application-wide.

**Security and audit requirement**  
Search indexes exclude secrets/private notes unless explicitly authorised.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0141 — Implement hermetic CI, multi-platform build and release automation

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Quality & release  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0075; ISSUE-0145

**Problem**  
Current release evidence is largely local and issue-specific.

**Why it matters**  
A final application needs reproducible gates on every change and release.

**Proposed implementation**
- Create locked Python environments and Windows/Linux test matrices.
- Run lint, typing, unit, property, integration, migration, offline E2E, package and smoke tests.
- Build signed/versioned native and portable artefacts.
- Generate machine-readable test/build/evidence manifests.
- Protect release branches and require passing gates.

**Data, packages and external dependencies**
- GitHub Actions or equivalent.
- ISSUE-0013; UPDATEV2-0029.

**Acceptance criteria**
- One release workflow creates all supported artefacts and evidence.
- Clean checkout and clean user profile pass.
- Failures cannot update issue closure or release aliases.
- Environment and toolchain versions are pinned.

**Tests required**
- CI self-tests.
- Reproducible-build comparison.
- Clean-install tests.
- Failure/permission tests.

**UI requirement**  
Release status in Settings and Data Health.

**Security and audit requirement**  
Least-privilege CI tokens, protected environments and signed artefacts.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0142 — Add property, metamorphic, golden, differential and mutation testing

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Quality & release  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0074; ISSUE-0127; ISSUE-0132

**Problem**  
Example-based tests do not fully protect financial formulas, accounting and authority invariants.

**Why it matters**  
Small numerical or control-flow regressions can produce plausible but dangerous outputs.

**Proposed implementation**
- Use Hypothesis for bounds, monotonicity, conservation, chronology and idempotency.
- Create golden reference cases with independent spreadsheet or hand calculations.
- Differentially compare old and new implementations during migration.
- Run mutation testing on scoring, risk, accounting and controls.
- Define numerical tolerance and deterministic seed policy.

**Data, packages and external dependencies**
- Hypothesis is already present.
- Select mutation tooling through ISSUE-0079.

**Acceptance criteria**
- Critical invariants have property tests.
- Mutation-score thresholds are set for safety-critical packages.
- Golden cases are versioned and independently reviewed.
- Numerical changes require explicit approval.

**Tests required**
- This issue defines the testing layers.
- Tolerance/platform tests.
- Mutation and differential suites.

**UI requirement**  
Quality dashboard shows invariant/domain coverage, not only line coverage.

**Security and audit requirement**  
Fixtures contain no credentials or restricted data.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0143 — Add visual E2E, load, soak, fault-injection and chaos test programmes

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Quality & release  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0141

**Problem**  
Unit and screenshot spot checks do not prove long-running workflows or recovery under stress.

**Why it matters**  
The final application must remain correct across large data, restarts and degraded dependencies.

**Proposed implementation**
- Use Playwright or the most reliable supported Flet browser harness.
- Create deterministic page objects and visual baselines.
- Load-test queries, large universes, imports and event streams.
- Soak-test jobs, memory, database and paper accounts.
- Inject provider, parser, disk, clock, network and broker faults.

**Data, packages and external dependencies**
- ISSUE-0136/0137; ISSUE-0078; ISSUE-0135.

**Acceptance criteria**
- All critical journeys pass source and packaged builds.
- No memory/file-descriptor growth exceeds budget.
- Recovery preserves the last valid state.
- Visual differences require reviewed baselines.

**Tests required**
- This issue defines E2E, load, soak and chaos suites.

**UI requirement**  
Test reports and visual diffs are linked from release evidence.

**Security and audit requirement**  
Tests use sandbox/mock broker and network allow-lists; no live orders.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0144 — Harden secrets, parsers, local APIs, files and network access

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Security  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0076; ISSUE-0145

**Problem**  
The app processes untrusted archives, XML/XBRL/PDF/CSV, model weights and future broker credentials.

**Why it matters**  
A local application can still suffer code execution, data theft, parser denial-of-service or credential leakage.

**Proposed implementation**
- Threat-model data, model, plugin, local API and broker surfaces.
- Sandbox or bound parsers/subprocesses; enforce archive, XML entity, PDF and CSV limits.
- Use host allow-lists, timeouts, TLS validation and no remote code execution.
- Store secrets in the OS credential store or an encrypted vault.
- Add secure localhost authentication and CSRF protection if HTTP is exposed.

**Data, packages and external dependencies**
- defusedxml is present.
- Bandit/Semgrep/pip-audit candidates.
- ISSUE-0079.

**Acceptance criteria**
- Secrets never enter logs, exports or crash reports.
- Malicious fixtures cannot escape paths, exhaust resources beyond limits or execute code.
- Network access is declared per plugin and can be disabled.
- Security findings block release according to severity policy.

**Tests required**
- Malicious archive/XML/CSV/model fixtures.
- Secret-redaction tests.
- API-auth tests.
- Network allow-list tests.

**UI requirement**  
Security status and credential configuration without revealing values.

**Security and audit requirement**  
Threat model, vulnerability response and audit events.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0145 — Implement software supply-chain, SBOM, vulnerability, signing and secure-update controls

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Security & release  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0079; ISSUE-0141

**Problem**  
Many optional finance/ML packages and copied components increase supply-chain risk.

**Why it matters**  
Users need verifiable packages and a controlled update path.

**Proposed implementation**
- Generate CycloneDX/SPDX SBOMs for source and packaged artefacts.
- Pin dependencies and hashes; scan Python and any introduced Rust/Node/.NET components.
- Run secret, licence and vulnerability scans.
- Sign release manifests/artefacts and verify before update.
- Define dependency cooldown, emergency patch and end-of-life policy.

**Data, packages and external dependencies**
- pip-audit, Gitleaks, Syft/Grype or equivalents after intake.
- ISSUE-0079.

**Acceptance criteria**
- Every release has SBOM, provenance, signatures and scan results.
- Known critical vulnerabilities block release unless an approved mitigation exists.
- Updater rejects unsigned or tampered artefacts.
- Third-party notices are packaged.

**Tests required**
- Tampered-update tests.
- SBOM-completeness tests.
- Vulnerability-policy tests.
- Offline-update tests.

**UI requirement**  
About/Update page shows verified version and notices.

**Security and audit requirement**  
Offline update option, least-privilege signing keys and reproducible manifests.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0146 — Implement encryption, privacy controls, backup and disaster recovery

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Security & resilience  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0044; ISSUE-0144

**Problem**  
Future journals, broker data and credentials contain sensitive financial and personal information.

**Why it matters**  
Local-first privacy requires controlled storage, backup, export and deletion.

**Proposed implementation**
- Encrypt secrets and optionally sensitive databases/backups using user-managed recovery keys.
- Classify data and provide export redaction and private-note exclusion.
- Implement incremental checksum-backed backups, retention and restore validation.
- Add corruption recovery and disaster drills.
- Document local deletion and portability.

**Data, packages and external dependencies**
- ISSUE-0044; ISSUE-0072; OS keychain/cryptography library after review.

**Acceptance criteria**
- A clean machine restores a validated backup.
- Loss of a remote service does not lose local research history.
- Private fields stay out of standard audit packets by default.
- Encryption/recovery failure modes are documented and tested.

**Tests required**
- Backup/restore drills.
- Wrong/corrupt-key tests.
- Redaction tests.
- Deletion/export tests.

**UI requirement**  
Privacy, Backup and Recovery settings.

**Security and audit requirement**  
Strong standard cryptography and key handling; no home-grown cryptographic scheme.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0147 — Deliver audit packet v3 and one-command deterministic reproduction

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Audit & reproducibility  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** UPDATEV2-0028; ISSUE-0075

**Problem**  
Existing audit packets do not yet capture the final data, model, portfolio and order lineage.

**Why it matters**  
A developer or reviewer must reproduce any analysis or decision without trusting screenshots.

**Proposed implementation**
- Export source snapshots, schemas, formulas, features, models, environment, jobs, scores, forecasts, targets, proposals, orders and fills.
- Include checksums, unavailable markers, issue/build evidence and redaction policy.
- Provide a reproduction command that verifies inputs and rebuilds selected artefacts offline.
- Compare reproduced hashes and declared numerical tolerances.
- Support instrument-, run- and order-scoped packets.

**Data, packages and external dependencies**
- ISSUE-0075; ISSUE-0090; ISSUE-0117; ISSUE-0127.

**Acceptance criteria**
- A selected result reproduces in a clean environment where licences permit.
- Missing/private/restricted artefacts are explicit.
- The manifest rejects unlisted or tampered content.
- No secret is exported.

**Tests required**
- Reproduction E2E.
- Tamper tests.
- Redaction tests.
- Backward-compatibility tests.

**UI requirement**  
Audit workspace with packet scope, privacy and verification result.

**Security and audit requirement**  
Signed checksums, allow-listed archive members and private-data controls.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0148 — Complete developer, plugin, methodology, operations and user documentation

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Documentation  
**Priority:** P0/P1  
**Evidence grade:** Moderate  
**Dependencies:** ISSUE-0043

**Problem**  
A complex investment and trading system cannot be maintained safely through labels alone.

**Why it matters**  
Completion requires reproducible developer onboarding and understandable user and operations procedures.

**Proposed implementation**
- Document architecture, schemas, migrations, providers, plugins, formulas, sector/ETF models, validation, portfolio methods and execution states.
- Create tutorials for data bootstrap, adding instruments, research, training, paper, backup and incidents.
- Generate API and data dictionaries from code.
- Document limitations, unsupported cases and update cadence.
- Add contribution and review checklists.

**Data, packages and external dependencies**
- All programme issues; ISSUE-0043.

**Acceptance criteria**
- A new developer builds/tests from a clean checkout.
- A user completes the offline core workflow without external help.
- Every public contract and methodology has current documentation.
- Documentation version matches release.

**Tests required**
- Documentation link/command tests.
- Clean onboarding walkthrough.
- Generated-doc drift tests.

**UI requirement**  
Help centre and context-sensitive links.

**Security and audit requirement**  
Examples contain no secrets, private data or unlicensed datasets.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0149 — Complete legal, data/model licence, terms, disclaimer and jurisdiction review

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Governance  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** ISSUE-0079; ISSUE-0080

**Problem**  
Free availability does not imply unrestricted reuse, redistribution, scraping or trading use.

**Why it matters**  
Data, model weights, copied code, tax content and automated trading carry different obligations.

**Proposed implementation**
- Maintain a source, code, model and data licence/terms registry.
- Review official fair access, Yahoo personal-use limits, issuer documents, factor datasets, broker APIs and copied libraries.
- Define permitted cache, redistribution and audit-export behaviour.
- Review financial-advice, tax, privacy and automated-order wording for supported jurisdictions.
- Add acknowledgement where necessary.

**Data, packages and external dependencies**
- ISSUE-0079; ISSUE-0080; professional legal review for release jurisdictions.

**Acceptance criteria**
- No mandatory source has unresolved terms.
- Restricted data are excluded or user-supplied under clear responsibility.
- UI/export disclaimers match actual functionality.
- Terms changes trigger review and possible provider disablement.

**Tests required**
- Licence-registry completeness tests.
- Restricted-export tests.
- Terms-change workflow tests.
- UI-wording tests.

**UI requirement**  
About, Provider Status, onboarding and live-stage confirmation.

**Security and audit requirement**  
This issue is the legal/security gate; records are versioned and auditable.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0150 — Audit geographic, sector, size, listing and data-coverage bias

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Model governance  
**Priority:** P0/P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0090; ISSUE-0120

**Problem**  
Free official data are uneven across countries, sectors and company sizes.

**Why it matters**  
A model can appear accurate while serving only liquid US large caps and failing elsewhere.

**Proposed implementation**
- Measure instrument, history, filing, holdings, factor, label and outcome coverage by geography, sector, size, currency and listing.
- Evaluate model error, calibration and screen selection by subgroup.
- Detect survivorship, missing-not-at-random and provider-availability biases.
- Define supported coverage thresholds and unsupported zones.
- Prevent aggregate metrics from hiding subgroup failures.

**Data, packages and external dependencies**
- ISSUE-0087; ISSUE-0090; ISSUE-0120; ISSUE-0124.

**Acceptance criteria**
- Coverage dashboards and model cards show subgroup results.
- Low-coverage groups cannot inherit high authority from aggregate performance.
- The supported universe is explicit.
- Bias and coverage are monitored over time.

**Tests required**
- Subgroup-metric tests.
- Synthetic-missingness tests.
- Threshold/authority tests.
- Coverage-regression tests.

**UI requirement**  
Data Coverage and Model Monitoring dashboards.

**Security and audit requirement**  
No protected or personal attribute inference; geographic data terms are honoured.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0151 — Define hardware profiles, compute budgets and graceful degradation

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Performance & release  
**Priority:** P1  
**Evidence grade:** High  
**Dependencies:** ISSUE-0078

**Problem**  
Heavy models and bulk data may make the app unusable on ordinary local hardware.

**Why it matters**  
A free local product must declare realistic requirements and remain functional without a GPU.

**Proposed implementation**
- Define minimum, recommended and high-performance CPU/RAM/storage/GPU profiles.
- Benchmark data sizes, startup, scoring, backtest and training.
- Provide CPU-only baselines, model-size selection, batch/chunk controls and low-resource mode.
- Enforce storage/resource quotas and cleanup.
- Show estimated requirements before jobs.

**Data, packages and external dependencies**
- ISSUE-0078; ISSUE-0077; ISSUE-0122.

**Acceptance criteria**
- Mandatory analysis works on the minimum profile without foundation models.
- Jobs cannot exhaust disk or memory without limits and warning.
- Results are numerically consistent across supported profiles within tolerance.
- Hardware-specific limitations are visible.

**Tests required**
- Cross-profile benchmarks.
- Low-disk/memory tests.
- CPU/GPU equivalence tests.
- Cleanup tests.

**UI requirement**  
Onboarding hardware check and Job resource estimates.

**Security and audit requirement**  
No undisclosed remote compute or telemetry; resource logs remain local.

**Mandatory free/no-quota policy**  
Mandatory implementation is local-first and must not depend on a paid plan, API key or per-call vendor quota.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.


## ISSUE-0152 — Run final release certification and close the completion programme

**Status:** Proposed — add to `issues/open.md`  
**Epic:** Final certification  
**Priority:** P0  
**Evidence grade:** High  
**Dependencies:** All issues

**Problem**  
Feature presence does not prove that the two final product functions work coherently and safely.

**Why it matters**  
A finite certification issue is required so “done” means release-complete against a frozen specification rather than an endless backlog.

**Proposed implementation**
- Freeze the release candidate, source/data/model/policy versions and supported universe.
- Run every closure matrix, clean install, migration, offline core, official-bulk refresh, stock/ETF journey, training, backtest, paper, recovery and security test.
- Certify live capability only at the authorised stage; capped automation requires separate canary evidence.
- Reconcile every canonical open issue and document accepted limitations.
- Produce signed releases, SBOM, audit packet, user/developer docs and rollback package.

**Data, packages and external dependencies**
- All current 76 issues and ISSUE-0070–ISSUE-0151.

**Acceptance criteria**
- Zero unresolved P0/P1 defects or unexplained numerical discrepancies.
- Analysis and paper/authorised-trading journeys pass from a clean install.
- No paid, keyed or quota-limited provider is required for mandatory completion.
- Safety, recovery, reproducibility and legal gates pass.
- Remaining limitations are explicit, bounded and consistent with the frozen scope.

**Tests required**
- Full authoritative suite.
- Independent review.
- Clean-machine certification.
- Disaster/kill-switch drills.
- Reproduction/security verification.

**UI requirement**  
Release Readiness dashboard with signed evidence and accepted limitations.

**Security and audit requirement**  
Independent reviewers, signed manifests, protected promotion and no live order during certification except an explicitly approved sandbox/canary test.

**Mandatory free/no-quota policy**  
Mandatory release software and core datasets are quota-independent; real broker trading remains subject to unavoidable broker, exchange, tax and market-data terms/costs.

**Close criteria**  
All acceptance criteria, tests, security/audit requirements, relevant migrations, source and packaged application checks, audit/export evidence and user-perspective browser verification must pass. The issue must not be closed merely because source files exist.
