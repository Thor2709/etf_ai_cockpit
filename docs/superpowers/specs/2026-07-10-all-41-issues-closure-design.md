# All 41 Open Issues Closure Programme Design

**Date:** 2026-07-10  
**Repository root:** `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit`  
**Status:** Approved design for implementation planning  
**Git status:** The directory is not a Git repository. No commit is possible unless a real `.git` directory appears; execution must not run `git init` without explicit user approval.

## Purpose

This specification defines a dependency-ordered programme for taking the 41 reviewed open issues through implementation, verification and evidence-strict closure. It is designed for one hands-off execution request that may continue across multiple automatic continuation turns and several hours. Each active turn must maximise useful progress, write durable state before expensive transitions and resume from the first unpassed gate after usage limits recover.

The target is all 41 issues Closed. The target does not relax any existing close rule. An issue cannot be closed because code exists, because a test passes in isolation or because a tracker was edited. It closes only when every applicable source, schema, test, UI, audit/export, package and browser/computer-use gate is supported by fresh evidence.

## Authorised Scope

The user explicitly authorises the implementation run to:

- download and retain official public SEC EDGAR, European ESEF/iXBRL, PRIIPs KID and index-methodology fixtures;
- add vetted local parser and testing dependencies, including Arelle or equivalent XBRL tooling and PDF parsing libraries where justified;
- record source URLs, licences or usage terms where applicable, retrieval timestamps and SHA-256 checksums for downloaded fixtures;
- perform controlled restructuring, add focused service modules and UI routes and run versioned data-schema migrations;
- create backups before migrations and preserve existing user data;
- use unit, integration, property-based, fuzz, failure-injection, migration, performance, security, browser and packaged tests;
- use Playwright, Chrome, screenshots, visual comparison and Windows computer use for verification;
- continue across automatic continuation turns while durable progress is recorded.

The implementation must still ask before destructive deletion, remote publication/upload, broker or trading-authority changes, secret exposure or any action outside this local application and its public fixture sources.

## Non-Negotiable Safety Rules

- No broker execution or order placement.
- No financial-advice wording.
- No invented prices, identifiers, filings, fundamentals, holdings, news, foreign-exchange data, forecasts or provider results.
- Missing, stale, conflicted or unverifiable evidence remains unavailable, `manual_review`, `no_trade` or another explicit non-authoritative state.
- Models, LLMs, news and candles cannot override deterministic evidence, provenance or risk gates.
- API keys, tokens, passwords, `.env` values and other secrets cannot appear in logs, screenshots, fixtures, exports, reports or packages.
- Official facts outrank vendor-normalised facts when identity and period mapping are valid.
- Parser extensions and ambiguous concepts are retained with warnings rather than guessed into canonical facts.
- SEC, ESEF/iXBRL, PRIIPs and methodology issues require real official fixtures, parser tests, UI import workflow, export/audit proof and packaged browser verification.

## Architectural Approach

The programme uses a dependency-ordered closure train. Shared infrastructure is completed before product surfaces and official parsers that depend on it. Expensive package builds occur at integration gates, not after every small edit, while focused test-first cycles run continuously.

The design preserves the current `src/etf_cockpit` structure and extracts focused modules only where existing files have accumulated unrelated responsibilities. `AppState` remains the UI coordinator but delegates workflows, providers, parsing, migrations, persistence, analytics and export to services with typed interfaces.

### Wave 1: Baseline and Closure Ledger

Re-audit all current code, data stores, tests, UI pages and existing evidence against each issue's acceptance criteria. Create a machine-readable closure matrix recording every criterion, required evidence, current implementation state, test name, UI route, export artefact and package/browser gate.

This wave prevents duplicate work. Existing foundations such as `session.jsonl`, provider probes, instrument identity, conflicts, evidence ledger, score history, feature drivers, correlation clusters, benchmark attribution and friction fields must be tested and extended where necessary rather than rewritten solely because their tracker remains open.

### Wave 2: Release and Verification Harness

Close:

- `UPDATEV2-0029` - rebuild/test/update discipline automation;
- `ISSUE-0013` - rebuild package after every completed feature;
- `ISSUE-0014` - end-to-end workflow test;
- `ISSUE-0045` - UI semantic locators and visual smoke tests.

Deliver a finish-check command that decides which focused tests, full tests and package gates are required from changed paths. It must validate tracker/worklog updates, launch source and packaged modes, capture HTTP and browser evidence and refuse issue closure when required evidence is absent. Stable Flet semantic labels should be added where the framework supports them; screenshot and computer-use verification remains mandatory where canvas semantics are insufficient.

### Wave 3: Workflow Runtime and Recovery

Close:

- `ISSUE-0069` - single-file session action logging and diagnostics trace;
- `UPDATEV2-0027` - workflow/button reliability and progress;
- `ISSUE-0011` - full main-UI button reliability audit;
- `ISSUE-0012` - long-action progress/status indicators;
- `ISSUE-0040` - error handling and recovery centre;
- `ISSUE-0039` - performance and caching audit.

Introduce one structured workflow contract for action IDs, steps, progress, timing, generated paths, controlled errors and retry eligibility. Every long-running button must log before work begins, emit visible step progress, preserve previous valid data on failure and finish in success, unavailable, manual-review or failed state. Timing and cache events must be observable without freezing the Flet UI.

### Wave 4: Canonical Data and Provenance

Close:

- `UPDATEV2-0010` - provider registry, probes and authority;
- `UPDATEV2-0011` - canonical ticker/ISIN/exchange identity;
- `UPDATEV2-0021` - source conflict resolution;
- `UPDATEV2-0022` - evidence ledger and score-component audit trail;
- `ISSUE-0035` - Data Health Centre.

Version the shared provider, identity, provenance, conflict and evidence schemas. Provider-specific symbols, MIC, exchange, currency, share class and confidence must remain visible. No evidence is score-eligible without a valid source reference, authority, as-of date, freshness state and conflict state. Data Health aggregates all store inventories and last success/failure results.

### Wave 5: Universe and First-Run Operations

Close:

- `ISSUE-0068` - two-tier universe and provider-policy editor;
- `ISSUE-0018` - watchlist and universe manager;
- `ISSUE-0017` - first-run onboarding and setup wizard;
- `ISSUE-0056` - data-frequency and unsupported-asset guardrails.

Add backed-up, atomic universe/watchlist persistence with primary, secondary and Sparebanken groups. Support add, edit, disable and remove with ticker/ISIN duplication checks and provider-policy validation. Editing configuration must invalidate affected caches but must not silently start downloads, scoring or forecasts. The first-run path must work with no existing data and create valid starter configuration. Unsupported assets and frequencies remain visibly non-scoreable.

### Wave 6: Official Sources and Disclosures

Close:

- `UPDATEV2-0012` - SEC EDGAR importer;
- `UPDATEV2-0013` - European ESEF/iXBRL importer;
- `UPDATEV2-0015` - ETF disclosure registry;
- `UPDATEV2-0016` - ETF holdings normaliser;
- `UPDATEV2-0017` - PRIIPs KID parser;
- `UPDATEV2-0019` - index-methodology importer;
- `ISSUE-0023` - stock fundamentals hardening;
- `ISSUE-0025` - free news and filings dashboard;
- `ISSUE-0054` - point-in-time news validation;
- `ISSUE-0055` - optional EDGAR, FRED, Stooq and RSS providers.

Providers acquire immutable raw material and provenance. Parsers consume local files and never hide network operations. Normalisers validate identity, units, periods, timestamps, completeness and authority before committing clean stores. Each strict parser receives at least one representative successful official fixture plus malformed, unsupported-extension and missing-field cases. UI flows must import local files, display parsing warnings and show explicit unavailable states when sources or credentials are absent.

### Wave 7: Analytics, History and Operational UI

Close:

- `ISSUE-0067` - score history and mini charts;
- `ISSUE-0047` - component feature-driver explanations;
- `ISSUE-0052` - correlation clustering and crowding;
- `ISSUE-0059` - sector/theme benchmark attribution;
- `ISSUE-0064` - friction-adjusted expected edge;
- `ISSUE-0034` - what changed since last run;
- `ISSUE-0019` - comprehensive Instrument Detail;
- `ISSUE-0036` - Import/Export Centre;
- `ISSUE-0042` - charts, tables and CSV export;
- `ISSUE-0044` - backup, restore, version and changelog;
- `ISSUE-0041` - accessibility, responsive layout and table usability.

These features consume canonical stores rather than recalculating conflicting values in UI modules. Historical data is idempotent by run ID. Changes compare latest and previous complete runs. Analytical warnings remain informational and cannot increase authority. Backup/restore is checksum-verified and cannot overwrite current data before validation. All major tables offer controlled CSV export with visible paths and errors.

### Wave 8: Audit Expansion and Final Closure

Close:

- `UPDATEV2-0028` - complete audit packet expansion.

The audit ZIP must contain provider states, identities, official filing inventories and parsed facts, ETF documents and holdings, news validation, conflicts, evidence ledger, score components and history, feature drivers, clustering, benchmark attribution, edge/cost fields, workflow/session trace, configuration snapshots, issue dossiers and checksums. External audit imports remain non-executable and cannot alter scores or action labels.

Run the complete source, native, portable, browser and computer-use acceptance matrix. Move an issue to `issues/closed.md` only after its dossier passes every applicable criterion.

## Component Boundaries

### Workflow Layer

A focused workflow module owns action IDs, step transitions, progress, cancellation-safe completion, timing and structured results. `core/session_log.py` remains the authoritative redacted trace. UI callbacks initiate workflows and render state; they do not implement provider, parser or persistence logic.

### Data Contracts and Storage

Typed, versioned contracts cover provider probes, identities, filing facts, fund documents, holdings, news, conflicts, evidence ledger, score history, run comparisons and export manifests. Parquet is canonical for clean and derived tabular stores. CSV and JSON are inspectable/export formats. All clean writes use temporary output, validation and atomic replacement.

Before a schema migration, affected files receive a timestamped backup and manifest. Migrations are idempotent, accept empty stores, preserve unknown fields where required and fail without replacing current valid data.

### Provider and Parser Boundary

Providers return raw bytes/JSON plus provenance, status and redacted diagnostics. Parsers accept local immutable paths and return typed records and warnings. Normalisers reconcile units, dates, periods and identities. Conflict resolution selects canonical values using deterministic authority rules and records both selected and rejected evidence.

Official fixture manifests include source URL, retrieved-at time, checksum, document type, issuer/entity, licence/terms note and expected parser result. Test fixtures cannot contain secrets or fabricated official claims.

### Canonical Evidence Flow

```text
Provider or import UI
  -> immutable raw document and provenance record
  -> parser and normaliser
  -> schema, identity, unit and period validation
  -> atomic clean store
  -> source conflict resolver
  -> evidence ledger and score eligibility
  -> score components and final deterministic gates
  -> score/history/change stores
  -> UI pages and audit/export artefacts
```

### UI Composition

Dedicated routes cover Provider Status, Data Health, Universe/Watchlists, Import/Export, Error/Recovery and What Changed. Instrument Detail composes shared selectors for price, score, freshness, drivers, filings, ETF disclosures, forecasts, backtests, news, journals and changes. Shared components own status banners, progress panels, sortable/searchable tables, export controls and evidence badges.

## Error Handling

Every workflow returns a structured result with action ID, timestamps, completed/current steps, status, redacted user message, error fingerprint, output paths, provider/parser/schema versions and retry guidance.

Transient network failures use bounded retry with backoff. Authentication, entitlement, invalid identity, malformed documents, schema mismatches and unsupported concepts fail immediately into readable states. A failure never removes the previous valid clean store. Stack traces stay in developer diagnostics and are represented to users by redacted fingerprints.

Logging failure is swallowed and surfaced as a secondary warning; it cannot crash the primary workflow. Import and restore operations validate fully before commit. Interrupted migrations and partial files must be recoverable from the recorded backup manifest.

## Testing and Bug-Finding Matrix

### Static, Dependency and Schema Checks

- Python compile and import checks for source and packaged entry points.
- Ruff/static checks and targeted type checking for new contracts and parser interfaces.
- Dependency version, licence and vulnerability review for added packages.
- Secret scanning across source, logs, fixtures, exports and built packages.
- Schema-contract tests for every Parquet, CSV, JSON, YAML, XML/XHTML and manifest format.

### Unit, Property and Parser Tests

- Unit tests for calculations, authority rules, conflict rules, state transitions and unavailable states.
- Property-based and fuzz tests for identifiers, dates, units, malformed CSV/JSON/XML/XHTML/PDF and parser boundaries.
- Golden tests using checksummed official fixtures.
- Regression tests written before each bug fix.
- Mutation-style checks for critical no-authority, no-trade and missing-source gates where practical.

### Integration and Failure Injection

- Provider states: live success where allowed, disabled, no credential, offline, timeout, rate limit and malformed response.
- Raw-to-parser-to-clean-to-conflict-to-ledger-to-score-to-export integration.
- Permission errors, locked files, interrupted writes, corrupted caches, duplicate run IDs and concurrent actions.
- Cache invalidation after universe, provider-policy, schema and source-document changes.
- Backup/restore round trips with checksum and schema comparison.

### UI, Browser and Computer Use

- Flet component and callback tests for every route and interactive control.
- Playwright tests for source and packaged builds.
- Chrome verification using stable semantic locators where available.
- Screenshots and pixel-level visual checks at desktop, narrow desktop and mobile-sized viewports.
- Windows computer-use verification of BAT launchers, browser opening, file pickers, imports, exports, progress, errors, retry, navigation and row expansion.
- Keyboard navigation, focus, labels, tooltips, colour-independent status, clipping, overlap and readable light/dark presentation.
- Browser console, application log and `session.jsonl` inspection after major workflows.

### Release and Operational Tests

- Source, native and portable launch/readiness checks.
- Paths containing spaces, busy/reused ports, locked outputs, stale processes and clean first-run state.
- Startup timing, lazy heavy imports, long-action responsiveness and bounded soak checks.
- Audit ZIP extraction, checksums, required-entry matrix and non-executable external-audit import.
- Independent code review and acceptance-criteria review at major wave gates.

Every defect follows the same loop: reproduce, capture evidence, isolate the boundary, write a failing regression test, implement the smallest fix, rerun focused tests and rerun all affected integration, browser and package gates.

## Closure Dossiers

Each issue has a dossier generated from the closure matrix containing:

1. Every acceptance criterion and its implementation evidence.
2. Exact source files, interfaces and schema versions.
3. Focused test names and fresh results.
4. Relevant UI workflow and browser/computer-use evidence.
5. Audit/export entries and checksums where applicable.
6. Source/native/portable build evidence where applicable.
7. Limitations that do not contradict acceptance criteria.
8. Tracker, report and worklog updates.

Valid states are:

- **Closed:** every mandatory gate passes.
- **Blocked:** implementation is complete but a named external condition prevents mandatory evidence.
- **Still open:** implementation or verification is incomplete.
- **Deferred:** the user explicitly removed the issue from scope.

The run targets Closed for all 41. External outages may be retried and recorded, but never converted into a false pass.

## Efficiency and Interruption Recovery

Fast focused tests run after each bounded change. Related integration tests run at task-group completion. Full package builds run after waves 3, 5, 6, 7 and 8, plus any change that directly affects packaged startup. Documentation-only edits do not trigger redundant builds.

Independent subagents may handle bounded fixture research, isolated parser/test work and independent review. Shared schemas, `AppState`, router integration, audit export and closure decisions remain under the main agent to reduce conflicts in a non-Git workspace.

A new `RUN_STATE.json` records current wave/task/criterion, commands and results, fixture/artefact checksums, defects and retries, evidence paths, closure readiness and the exact next command. Human-readable state is mirrored to `RUN_LOG.md`, `HANDOFF.md` and all required `.ai_worklog` files.

Checkpoints are mandatory before dependency installation, migration, parser integration, major UI integration, package build and final tracker closure. Official fixtures are downloaded once and reused by checksum. A usage-limit interruption resumes from the recorded first unpassed gate rather than restarting analysis.

## Completion Definition

The programme is complete only when:

- all 41 issue dossiers pass their criteria;
- all required focused, full, integration, parser, failure-injection and migration tests pass;
- native and portable packages rebuild successfully;
- source and packaged UIs pass Playwright, Chrome and Windows computer-use verification;
- required screenshots and logs are present and inspectable;
- audit ZIP manifests and checksums validate;
- no secret or invented evidence is present;
- the 41 issues are moved from open to closed with exact evidence;
- broad remaining work, if any, is represented by new accurately scoped issues rather than hidden limitations;
- no Git commit is claimed while the workspace remains outside a Git repository.
