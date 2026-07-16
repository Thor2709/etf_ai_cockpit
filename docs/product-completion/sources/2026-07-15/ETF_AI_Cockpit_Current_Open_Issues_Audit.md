# ETF AI Cockpit — Audit of All 76 Canonical Current Open Issues

**Audit date:** 15 July 2026  
**Purpose:** preserve every current issue while specifying the additional work needed for the frozen final product scope.  
**Policy:** no current issue is silently deleted. Issues implemented but awaiting release evidence remain open until their complete closure criteria pass.

## Status summary

- **Implementation complete; closure pending:** 23
- **Open:** 42
- **Open, partial:** 9
- **Open, research-only:** 2

## ISSUE-0007 — Add non-executable news/macro contradiction panel

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Contradictions are not yet a complete, point-in-time workflow across research and portfolio views.

**Required change**  
Persist typed contradiction records with source, decision-time availability, severity, confidence, expiry and resolution. Link them to events, scenarios and affected exposures while keeping them outside direct score/order authority.

**Why it matters**  
Conflicts between strong price/fundamental evidence and adverse news or macro conditions are useful review signals, but opaque sentiment must not become an order generator.

**Dependencies / cross-links**  
ISSUE-0054; ISSUE-0024; ISSUE-0026; ISSUE-0073; ISSUE-0115

**Required completion evidence**  
Historical replay reproduces each contradiction; UI and audit show it; regression tests prove it cannot directly change a score, target or order.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0008 — Add strategy taxonomy and scope/rejection matrix

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The existing taxonomy assumes no broker execution forever, which conflicts with the new staged end state.

**Required change**  
Replace the blanket boundary with a per-strategy authority matrix for research, shadow, paper, draft-order and capped-live stages. Keep martingale, grid, LLM-only and sentiment-only authority rejected.

**Why it matters**  
Without explicit stage-specific authority, future code can either violate the present policy or accidentally grant unsafe execution rights.

**Dependencies / cross-links**  
ISSUE-0070; ISSUE-0060; ISSUE-0130; ISSUE-0133

**Required completion evidence**  
Static and behavioural tests reject unauthorised stage escalation; every strategy declares data, validation, risk and execution prerequisites.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0010 — Add non-executable LLM thesis diary

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
LLM commentary is not yet fully immutable, reproducible and evaluated forward-only.

**Required change**  
Store prompt, model, source and retrieval hashes; evidence snapshots; redaction state; human review; expiry; and later outcomes. Keep LLM output excluded from scores, optimisers and orders.

**Why it matters**  
A diary can aid review and learning, but LLM text is not deterministic financial evidence and can contain hallucinations or historically contaminated claims.

**Dependencies / cross-links**  
ISSUE-0030; ISSUE-0057; ISSUE-0147

**Required completion evidence**  
Every thesis reproduces from an audit packet and zero-authority regression tests pass.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0011 — Full main-UI button reliability audit

**Current status:** Open, partial  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Current and future actions are not covered by one generated inventory and repeatable packaged E2E suite.

**Required change**  
Generate the action inventory from route/command metadata; cover research, training, paper, broker-read-only, recovery and live-stage controls; require stable IDs, command contracts and visible failure states.

**Why it matters**  
A financial application cannot be considered complete while controls may be silent, duplicated, disconnected or only manually verified.

**Dependencies / cross-links**  
ISSUE-0014; ISSUE-0045; ISSUE-0136; ISSUE-0143

**Required completion evidence**  
Every action has a stable locator, callback contract, success/failure evidence and packaged browser test.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0012 — Add visible progress/status indicators for long-running actions

**Current status:** Open, partial  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Progress is still partly UI state rather than a durable resumable workflow record.

**Required change**  
Back all progress with the persistent job DAG, checkpoints, cancellation, resource metrics and one canonical event stream. Remove parallel activity stores.

**Why it matters**  
Imports, parsers, training and backtests may run for long periods and must survive restart without duplicating publication.

**Dependencies / cross-links**  
ISSUE-0077; ISSUE-0117; ISSUE-0139

**Required completion evidence**  
Every long-running command emits durable typed events that survive restart and reconcile with audit exports.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0013 — Rebuild package after every completed feature

**Current status:** Open  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The release discipline exists mainly as a policy and local evidence process.

**Required change**  
Implement it in protected CI: pinned environments, full tests, package build, launch, smoke, SBOM, signing and machine-readable closure evidence.

**Why it matters**  
Handwritten “tests passed” records do not guarantee reproducible release artefacts.

**Dependencies / cross-links**  
UPDATEV2-0029; ISSUE-0141; ISSUE-0145; ISSUE-0152

**Required completion evidence**  
No issue can close unless the closure evaluator verifies current source, test, UI, export, build and browser evidence.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0014 — Add end-to-end workflow test

**Current status:** Open, partial  
**Priority:** P0/P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The main workflow has partial browser evidence but no complete hermetic suite.

**Required change**  
Add clean offline, best-effort online, migration, large-universe, training, paper-broker, recovery and package journeys. Separate source, packaged and browser suites.

**Why it matters**  
Unit tests do not prove that a clean installation can complete the real user workflow.

**Dependencies / cross-links**  
ISSUE-0045; ISSUE-0143; ISSUE-0152

**Required completion evidence**  
One documented command completes the mandatory workflow with deterministic fixtures on a clean machine.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0015 — Add app-level feature map / roadmap page

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Route existence can be mistaken for feature readiness.

**Required change**  
Drive the page from the canonical dependency and closure registry; show implementation, release, data, model, paper and live authority separately.

**Why it matters**  
Users and developers need a truthful map of complete, partial, research-only, optional and rejected capabilities.

**Dependencies / cross-links**  
ISSUE-0070; ISSUE-0075; ISSUE-0152

**Required completion evidence**  
Status is generated from verified evidence and cannot be manually overstated.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0016 — Full product navigation redesign

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The application has many routes but no final task-oriented information architecture.

**Required change**  
Fold this into frontend v2: Home, Discover, Instrument, Portfolio, Models, Backtest/Paper, Data Health, Audit and Settings, with search and command palette.

**Why it matters**  
Institutional-style workflows require coherent journeys rather than an ever-growing sidebar of technical pages.

**Dependencies / cross-links**  
ISSUE-0137; ISSUE-0138; ISSUE-0139; ISSUE-0140

**Required completion evidence**  
All final functions are reachable, understandable, responsive and E2E-tested through the new workspaces.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0017 — First-run onboarding and setup wizard

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The current wizard lacks the final offline data bootstrap, hardware profile and privacy/security choices.

**Required change**  
Add storage location, hardware profile, mandatory versus optional providers, offline sample/bulk bootstrap, encryption/backup preferences and explicit staged-execution defaults.

**Why it matters**  
A complete local-first product must work on an empty machine without a key or network and must not accidentally enable trading.

**Dependencies / cross-links**  
ISSUE-0080; ISSUE-0151; ISSUE-0146

**Required completion evidence**  
Clean first-run passes offline and online enrichment remains optional.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0018 — Watchlist and universe manager

**Current status:** Implementation complete; closure pending  
**Priority:** P0/P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
CRUD exists, but identity, classification, backfill and delisting propagation are incomplete.

**Required change**  
Connect edits to the canonical identity master, classification service, data-dependency plan, point-in-time universe and cache invalidation. Never trigger orders or hidden analysis on save.

**Why it matters**  
Every user-added stock or ETF must appear consistently in all relevant calculations and screens.

**Dependencies / cross-links**  
UPDATEV2-0011; ISSUE-0082; ISSUE-0083; ISSUE-0126

**Required completion evidence**  
Browser CRUD, identity resolution, classification, backfill and downstream propagation pass for representative stock and ETF cases.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0019 — Proper instrument detail page

**Current status:** Implementation complete; closure pending  
**Priority:** P0/P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The page is evidence-rich but lacks the complete long-horizon, sector-specific and operational workspaces.

**Required change**  
Add expected-return distributions, sector adapters, full metric histories, peer comparison, valuation/scenario labs, factor risk, model cards and paper/order timelines.

**Why it matters**  
The instrument page is the primary research hub and must explain every output and limitation.

**Dependencies / cross-links**  
ISSUE-0091–ISSUE-0116; ISSUE-0138

**Required completion evidence**  
Complete stock and ETF journeys, unavailable states, exports, accessibility and packaged browser tests pass.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0020 — Screener and filter system

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Current screening is not yet point-in-time, peer-normalised or portfolio-aware.

**Required change**  
Support reproducible as-of screens, sector adapters, factor percentiles, coverage/confidence filters, expected-return distributions, portfolio impact and saved query versions.

**Why it matters**  
Discovery must not compare inapplicable raw metrics or silently favour instruments with richer data.

**Dependencies / cross-links**  
ISSUE-0073; ISSUE-0074; ISSUE-0098; ISSUE-0138

**Required completion evidence**  
Saved screens reproduce exactly from the same dataset/formula versions and exports include filter lineage.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0021 — Portfolio construction and allocation sandbox

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The portfolio page is context rather than a complete construction and risk laboratory.

**Required change**  
Integrate factor risk, robust covariance, multiple transparent optimisers, constraints, turnover/cost/tax lots, scenarios and attribution, always compared with simple baselines.

**Why it matters**  
A stock/ETF score is not a portfolio weight; diversification, uncertainty and implementation costs must be modelled separately.

**Dependencies / cross-links**  
ISSUE-0110–ISSUE-0116; ISSUE-0130

**Required completion evidence**  
Every proposed allocation shows feasibility, binding constraints, uncertainty, no-trade baseline, turnover and net-of-cost effects.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0022 — ETF overlap and look-through exposure engine

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Top-holdings overlap is insufficient for complete fund exposure and risk.

**Required change**  
Resolve full/partial holdings to canonical entities, support nested funds, cash and derivatives, preserve history and propagate unresolved coverage into factor/valuation/risk outputs.

**Why it matters**  
ETFs can conceal duplicate issuers, sectors, countries, currencies and factors across apparently different products.

**Dependencies / cross-links**  
UPDATEV2-0016; ISSUE-0082; ISSUE-0105

**Required completion evidence**  
Every look-through output reports source, as-of date, hierarchy depth, resolved weight and unresolved weight.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0023 — Stock fundamentals quality module hardening

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The implemented five-section yfinance layer remains shallow and uses incomplete vendor fields.

**Required change**  
Retain it as a compatibility layer but replace fixed universal thresholds with official point-in-time statements, restatements, sector adapters, accounting quality, capital efficiency and valuation scenarios.

**Why it matters**  
Professional long-term stock analysis depends on multi-period, comparable and sector-appropriate fundamentals.

**Dependencies / cross-links**  
ISSUE-0091–ISSUE-0102

**Required completion evidence**  
Representative companies in every supported sector use the new stack with complete source, coverage and release evidence.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0024 — Earnings, dividends and event calendar

**Current status:** Open  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Events are not represented in one canonical availability-aware model.

**Required change**  
Add earnings, dividends, splits, filings, guidance, fund rebalances, index changes, review dates and risk events with timezone, source, precision and decision-time availability.

**Why it matters**  
Event timing affects interpretation, model validity and order risk, but must not leak into earlier backtests.

**Dependencies / cross-links**  
ISSUE-0073; ISSUE-0084; ISSUE-0085; ISSUE-0130

**Required completion evidence**  
Historical event queries are point-in-time correct and event-based order blocks are policy-driven and audited.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0025 — Free news and filings dashboard

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Official filings and ephemeral news are still combined in a broad context workflow.

**Required change**  
Separate durable official evidence from best-effort news; add archive/deduplication/entity mapping/terms controls and integrate with contradictions and events.

**Why it matters**  
Filings can support fundamentals, while news is incomplete, biased and often unavailable without paid licences.

**Dependencies / cross-links**  
ISSUE-0007; ISSUE-0054; ISSUE-0087; ISSUE-0149

**Required completion evidence**  
Core analysis works with no news feed; all displayed items carry source, availability and context-only authority.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0026 — Macro regime dashboard

**Current status:** Open  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Macro series and regime labels are not yet vintage-aware or connected to portfolio scenarios.

**Required change**  
Build a local macro/factor warehouse with release/vintage metadata, transformations, country/currency mapping, uncertainty and scenario links. Keep macro as conditioning/context unless validated.

**Why it matters**  
Current revised macro data can cause look-ahead and a regime label alone is not a return forecast.

**Dependencies / cross-links**  
ISSUE-0073; ISSUE-0088; ISSUE-0115

**Required completion evidence**  
Historical regimes use decision-time vintages and every series exposes source, transformation and revision history.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0027 — Forecast lab page

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Forecast rows and basic calibration do not constitute a complete model research workflow.

**Required change**  
Expand to experiments, baselines, walk-forward splits, uncertainty, conformal calibration, drift, challenger status, resource use and governed promotion.

**Why it matters**  
TimesFM/Toto and other models must demonstrate finance-specific, net-of-cost, forward value rather than general benchmark performance.

**Dependencies / cross-links**  
ISSUE-0117–ISSUE-0124; ISSUE-0139

**Required completion evidence**  
No model gains authority without adequate matured observations, baseline comparison and immutable validation evidence.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0028 — Backtest lab upgrade

**Current status:** Open  
**Priority:** P0/P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The existing vectorised rebalance backtest is not an order-level, point-in-time institutional validation system.

**Required change**  
Add point-in-time universes/fundamentals, deterministic order events, nested walk-forward validation, trial disclosure, multiple-testing correction, capacity, taxes, actions and reproducibility.

**Why it matters**  
Plausible historical equity curves can be produced by leakage, survivorship bias and unrealistic fills.

**Dependencies / cross-links**  
ISSUE-0120; ISSUE-0125–ISSUE-0128

**Required completion evidence**  
Backtests fail closed on leakage or missing execution evidence and reproduce from an immutable audit packet.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0029 — Strategy template builder

**Current status:** Open  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Templates are not fully tied to canonical data, model, optimiser, risk and authority versions.

**Required change**  
Make templates versioned compositions of approved features, scores, forecasts, portfolio/risk and execution policies. Record complexity, trials and stage authority.

**Why it matters**  
A user-configurable blend can otherwise bypass validation or hide an overfit strategy.

**Dependencies / cross-links**  
ISSUE-0074; ISSUE-0075; ISSUE-0130

**Required completion evidence**  
Every template is reproducible, benchmarked, validated and explicitly authorised per stage.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0030 — Decision journal

**Current status:** Open  
**Priority:** P0/P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The journal is not yet connected to alternatives, proposals, models, orders and later attribution.

**Required change**  
Store accepted/rejected/deferred decisions, evidence, alternatives, confidence, invalidation rules, review dates, portfolio context and immutable links to model/proposal/order IDs.

**Why it matters**  
Long-term improvement requires learning from both actions and decisions not taken.

**Dependencies / cross-links**  
ISSUE-0010; ISSUE-0057; ISSUE-0129; ISSUE-0147

**Required completion evidence**  
Append-only history, checksum protection, privacy controls and outcome linkage pass.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0031 — Paper trading module

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The issue currently describes a local PnL tracker, not a realistic paper broker.

**Required change**  
Implement order/fill lifecycle, cash, fees, FX, corporate actions, partial fills, cancellations, calendars, accounting, restart recovery and reconciliation.

**Why it matters**  
Forward evidence must test the complete decision and operational chain before capital is at risk.

**Dependencies / cross-links**  
ISSUE-0125; ISSUE-0127–ISSUE-0130

**Required completion evidence**  
Accounting invariants, deterministic replay, no-network isolation and full paper E2E tests pass.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0032 — Future broker-execution architecture document only

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
It is limited to documentation and assumes no live execution, while the requested end state has staged automation.

**Required change**  
After the scope ADR, document and gate broker read-only, draft-order and capped-live stages using official APIs; keep order submission disabled until prerequisites pass.

**Why it matters**  
Execution must be introduced through explicit, reviewable stages rather than a hidden scope change.

**Dependencies / cross-links**  
ISSUE-0070; ISSUE-0131–ISSUE-0135

**Required completion evidence**  
The architecture is approved, no unauthorised live path exists and every stage has separate prerequisites and controls.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0033 — Alerts and review reminders

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Alerts lack a unified typed event and escalation system.

**Required change**  
Add severity, confidence, deduplication, snooze/expiry, alert backtesting and portfolio/order/model incident rules. Only explicit policies may turn an alert into a block.

**Why it matters**  
Unbounded alerts create noise; hidden alerts create risk.

**Dependencies / cross-links**  
ISSUE-0024; ISSUE-0077; ISSUE-0132; ISSUE-0135

**Required completion evidence**  
Deterministic generation, persistence, deduplication and escalation tests pass without alert storms.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0034 — What changed since last run page

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The page does not yet explain all upstream reasons for a changed result.

**Required change**  
Add source revisions, corrections, classification, formula/model/policy versions, portfolio targets, paper/order state and causal dependency paths.

**Why it matters**  
Users must distinguish a market change from a data correction or formula change.

**Dependencies / cross-links**  
ISSUE-0075; ISSUE-0090; ISSUE-0116; ISSUE-0134

**Required completion evidence**  
Every change links to an exact upstream cause and affected downstream artefacts.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0036 — Import/export centre

**Current status:** Implementation complete; closure pending  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The centre lacks the final breadth of broker, bulk, schema-mapping and encrypted portability workflows.

**Required change**  
Add broker/exchange statements, bulk datasets, reusable mapping templates, dry-run diffs, resumable imports, rollback and privacy-aware portable backups.

**Why it matters**  
Local imports are the only globally viable quota-independent route for prices, positions and licensed user data.

**Dependencies / cross-links**  
ISSUE-0081; ISSUE-0086; ISSUE-0127; ISSUE-0146

**Required completion evidence**  
All imports are previewed, atomic, idempotent, reversible and reconciled.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0037 — Config editor UI

**Current status:** Open  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Direct YAML concepts remain and configuration can potentially change authority without a complete policy preview.

**Required change**  
Use typed schemas, migrations, safe defaults, staged edits, validation, secret-vault integration and before/after policy impact previews.

**Why it matters**  
Configuration is executable policy in a finance system and must be controlled like code.

**Dependencies / cross-links**  
ISSUE-0075; ISSUE-0076; ISSUE-0144

**Required completion evidence**  
Invalid, incompatible or authority-expanding changes cannot be committed without required approval.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0038 — Local database / storage migration plan

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
It is only a plan; file stores do not meet the final transactional and bitemporal requirements.

**Required change**  
Convert it to an implementation epic for DuckDB/Parquet analytics plus SQLite transactional state, migrations, integrity, retention, compaction and export compatibility.

**Why it matters**  
Journals, experiments, portfolios, orders and reconciliation need ACID state while large histories need columnar analytics.

**Dependencies / cross-links**  
ISSUE-0072; ISSUE-0073; ISSUE-0090

**Required completion evidence**  
Production data is migrated, verified, recoverable, benchmarked and used by every final workflow.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0039 — Performance and caching audit

**Current status:** Open, partial  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
There are no comprehensive quantitative performance budgets or regression gates.

**Required change**  
Define startup, query, scoring, large-universe, training, memory, package-size and storage budgets; profile before choosing pandas/Polars/DuckDB optimisations; track cache lineage.

**Why it matters**  
Optimisation without measured budgets can trade correctness for speed or move bottlenecks.

**Dependencies / cross-links**  
ISSUE-0077; ISSUE-0078; ISSUE-0151

**Required completion evidence**  
Repeatable benchmarks pass on declared minimum/recommended hardware and numerical equivalence is preserved.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0040 — Error handling and recovery centre

**Current status:** Open, partial  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Recovery coverage is incomplete for databases, jobs, models, imports and broker divergence.

**Required change**  
Add resumable jobs, corrupt-store quarantine, last-known-good generations, model/subprocess failure, provider outage, broker mismatch and incident runbooks.

**Why it matters**  
A readable error is not enough if the prior valid state can be lost or the system retries into unknown state.

**Dependencies / cross-links**  
ISSUE-0077; ISSUE-0089; ISSUE-0135; ISSUE-0146

**Required completion evidence**  
Fault-injection tests prove state preservation and safe recovery for each critical workflow.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0041 — Accessibility, responsive layout and table usability

**Current status:** Implementation complete; closure pending  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Final workspaces and high-density tables are not yet covered by a complete accessibility standard.

**Required change**  
Complete WCAG-oriented keyboard, focus, screen-reader, high-contrast, reduced-motion, zoom and virtualised-table testing under frontend v2.

**Why it matters**  
A dense analytical application must be usable without relying on colour, precise pointing or a wide display.

**Dependencies / cross-links**  
ISSUE-0137; ISSUE-0140; ISSUE-0143

**Required completion evidence**  
Documented accessibility checks pass across all final workspaces and package modes.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0042 — Charts, tables and CSV export improvements

**Current status:** Implementation complete; closure pending  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Charts are not yet a consistent uncertainty-, lineage- and high-volume-capable analytical system.

**Required change**  
Add linked charts, aligned currency/timezone/horizon controls, confidence bands, coverage overlays, virtualisation and exports that include exact query/filter/version context.

**Why it matters**  
Visuals and exports must be numerically identical and cannot hide missing evidence.

**Dependencies / cross-links**  
ISSUE-0138; ISSUE-0090; ISSUE-0147

**Required completion evidence**  
Representative charts/tables/export round trips reconcile and pass large-universe and accessibility tests.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0043 — User manual, glossary and in-app explanations

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Current help does not cover the final methodology, operations, limitations and staged trading system.

**Required change**  
Add task-based user guidance, score/valuation/risk methodology, model cards, sector/ETF adapters, data licences, paper/live operations, incidents and reproducibility tutorials.

**Why it matters**  
Advanced calculations are unsafe if users cannot distinguish evidence, assumptions, uncertainty and authority.

**Dependencies / cross-links**  
ISSUE-0148; ISSUE-0149

**Required completion evidence**  
Every final feature has current user, developer, methodology and limitation documentation.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0044 — Backup, restore, version and changelog

**Current status:** Implementation complete; closure pending  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The existing backup workflow is not yet the final encrypted, database-aware disaster-recovery system.

**Required change**  
Add incremental encrypted backups, retention, consistency checks, signed metadata, key recovery, clean-machine restore drills and schema-version compatibility.

**Why it matters**  
Local research, journals and account records are valuable and sensitive; backup success must be proven rather than assumed.

**Dependencies / cross-links**  
ISSUE-0145; ISSUE-0146

**Required completion evidence**  
A clean machine restores a verified supported-version backup and all canonical stores reconcile.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0045 — UI semantic locators and visual smoke tests

**Current status:** Open, partial  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Flet canvas/DOM limitations still force some coordinate and screenshot-only verification.

**Required change**  
Create page-object contracts, accessibility locators, deterministic fixtures, visual baselines and cross-resolution/browser tests; replace coordinate actions wherever possible.

**Why it matters**  
UI claims require repeatable user-point-of-view proof, especially for order and recovery actions.

**Dependencies / cross-links**  
ISSUE-0136; ISSUE-0143

**Required completion evidence**  
All critical journeys run repeatably with stable locators or a documented, tested visual fallback.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0046 — Monthly decision template: basket vs benchmark vs cash

**Current status:** Open  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The template is not connected to expected-return distributions, portfolio risk and paper evidence.

**Required change**  
Drive it from versioned expected returns, optimiser constraints, costs, events, capacity and forward evidence; always show no-action, benchmark and cash alternatives.

**Why it matters**  
Monthly long-horizon decisions require portfolio context, not a simple ranked basket.

**Dependencies / cross-links**  
ISSUE-0108; ISSUE-0112–ISSUE-0115; ISSUE-0130

**Required completion evidence**  
The template shows gross/net distributions, assumptions, constraints and later paper outcomes.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0047 — Feature-driver explanations for every evidence component

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Current driver text lacks full peer, history, uncertainty and sensitivity context.

**Required change**  
Add peer percentile, historical contribution, coverage, uncertainty, interaction and counterfactual sensitivity while avoiding causal claims.

**Why it matters**  
A score is trustworthy only when every contribution reconciles to the exact canonical formula.

**Dependencies / cross-links**  
ISSUE-0074; ISSUE-0098; ISSUE-0138

**Required completion evidence**  
Displayed explanations and exported component contributions reconcile exactly to the canonical engine.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0048 — Strategy complexity and overfitting penalty metadata

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Metadata does not yet retain every attempted trial and effective search burden.

**Required change**  
Store all trial return series, features, parameters, thresholds, variants, selection method, code/data hashes, DSR/PBO/multiple-testing results and researcher decisions.

**Why it matters**  
A selected strategy can look strong only because many discarded alternatives were hidden.

**Dependencies / cross-links**  
ISSUE-0120; ISSUE-0122; ISSUE-0147

**Required completion evidence**  
No strategy can be promoted without complete trial disclosure and validated complexity/overfit diagnostics.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0049 — Worst-day, loss-cluster and tail-event diagnostics

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Current payoff diagnostics do not cover expected shortfall, tail dependence and portfolio/factor contribution.

**Required change**  
Add worst windows, drawdown duration, expected shortfall, loss clustering, tail dependence, liquidity stress and factor/sector contribution with bootstrap uncertainty.

**Why it matters**  
Long-term strategies can be dominated by a few crisis periods even when average metrics look acceptable.

**Dependencies / cross-links**  
ISSUE-0111; ISSUE-0115; ISSUE-0128

**Required completion evidence**  
Instrument, strategy and portfolio diagnostics enforce minimum samples and show confidence intervals.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0050 — Operational evidence panel for next-open/decision-price realism

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The panel is not connected to real calendars, order types, spreads, gaps or realised fills.

**Required change**  
Use the canonical session service and order engine; show decision, arrival, next-open/close, spread, auction, expiry and realised paper/live fill evidence.

**Why it matters**  
Same-bar or stale-price assumptions can invalidate otherwise sound analysis.

**Dependencies / cross-links**  
ISSUE-0085; ISSUE-0125; ISSUE-0128; ISSUE-0134

**Required completion evidence**  
Simulation and real execution share one timing contract and no fill can precede its valid order/session.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0051 — Cash proxy and risk-free/defensive comparison everywhere relevant

**Current status:** Open  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Cash comparisons are not yet currency-, horizon- and vintage-matched.

**Required change**  
Use official currency-specific risk-free curves/proxies, declared reinvestment, inflation context and explicit unavailable states.

**Why it matters**  
An investment should be compared with realistic alternatives, not only a risky broad benchmark.

**Dependencies / cross-links**  
ISSUE-0088; ISSUE-0112

**Required completion evidence**  
Every comparison is point-in-time, total-return and currency consistent.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0052 — Correlation clustering and factor-crowding warnings

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Clustering is not fully integrated with look-through holdings, factor risk, scenarios and optimiser constraints.

**Required change**  
Connect clusters to the canonical risk model and historical holdings; quantify uncertainty, stability and portfolio risk contribution.

**Why it matters**  
Apparently diversified high-ranked instruments may represent one underlying theme or factor bet.

**Dependencies / cross-links**  
ISSUE-0105; ISSUE-0110; ISSUE-0113; ISSUE-0115

**Required completion evidence**  
Warnings reconcile with holdings/factor exposures and report sample period, coverage and uncertainty.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0053 — What matters today digest

**Current status:** Open  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The digest is not yet a complete prioritised action queue across research and operations.

**Required change**  
Generate it from typed alerts, source revisions, events, model drift, portfolio risk, proposal state, paper/live incidents and recent recovery/export status.

**Why it matters**  
Users need a concise start point without losing the evidence behind urgency.

**Dependencies / cross-links**  
ISSUE-0033; ISSUE-0034; ISSUE-0139

**Required completion evidence**  
Every digest item links to evidence and remains non-promotional and non-executable unless an explicit control policy applies.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0054 — Point-in-time news/sentiment validation rules

**Current status:** Implementation complete; closure pending  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Correction, retraction, archive and timestamp-precision states remain incomplete.

**Required change**  
Add article versions, corrections, retractions, timezone precision, archive availability, deduplication and mapping confidence. Reject ambiguous historical availability.

**Why it matters**  
News leakage and silent revisions can make backtests appear predictive.

**Dependencies / cross-links**  
ISSUE-0073; ISSUE-0025; ISSUE-0149

**Required completion evidence**  
Chronology tests prove no item is visible before actual availability and all revisions remain recoverable.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0055 — Optional free provider research/stubs: SEC EDGAR, FRED, Stooq, RSS

**Current status:** Implementation complete; closure pending  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The issue groups sources with very different quota, authority and legal characteristics.

**Required change**  
Split source tiers. SEC bulk and user/local files are mandatory-capable; FRED API, Stooq and RSS are optional/best-effort unless cached snapshots are supplied. Use World Bank, Eurostat, ECB and official bulk where appropriate.

**Why it matters**  
“Free” does not mean unrestricted or suitable as a mandatory dependency.

**Dependencies / cross-links**  
ISSUE-0080; ISSUE-0081; ISSUE-0087; ISSUE-0088

**Required completion evidence**  
Every provider exposes tier, licence, quota, cache and fallback status and the mandatory core works with it disabled.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0056 — Data-frequency suitability and unsupported-asset guardrails

**Current status:** Implementation complete; closure pending  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Guardrails do not yet cover all session, horizon, corporate-action and order-policy combinations.

**Required change**  
Add capability rules by instrument/listing, calendar, data frequency, leverage, price state, forecast horizon, model and order type.

**Why it matters**  
Unsupported products must fail closed consistently at import, analysis, backtest and order stages.

**Dependencies / cross-links**  
ISSUE-0076; ISSUE-0085; ISSUE-0130

**Required completion evidence**  
A shared capability service blocks or warns every unsupported combination across all surfaces.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0057 — Paper/forward evidence diary

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The diary is not yet built on immutable decision-time manifests or the complete paper broker.

**Required change**  
Freeze data, formula, model, portfolio, policy and proposal hashes; mature configurable outcomes; separate observation-only proposals from accepted paper orders.

**Why it matters**  
Historical backtests are not forward evidence, and accepted trades alone create selection bias.

**Dependencies / cross-links**  
ISSUE-0075; ISSUE-0129; ISSUE-0147

**Required completion evidence**  
All proposals, including rejected/deferred ones, retain immutable snapshots and deterministic matured outcomes.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0058 — Closed-source/promotional-claim detector for imported notes

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The rule set is not a complete structured evidence review and can generate false confidence.

**Required change**  
Extract claims and check source, licence, method, benchmark, drawdown, costs, sample, reproducibility and conflicts; require human override and measured false-positive/negative performance.

**Why it matters**  
Marketing claims and screenshots are common but are not reproducible evidence.

**Dependencies / cross-links**  
ISSUE-0010; ISSUE-0149

**Required completion evidence**  
A labelled test corpus, human-review audit and zero direct authority are demonstrated.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0059 — Benchmark-relative sector/theme attribution beyond single benchmark beta

**Current status:** Implementation complete; closure pending  
**Priority:** P1/P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Attribution remains instrument-level and is not a complete factor/currency/portfolio decomposition.

**Required change**  
Migrate to the multi-factor risk and attribution model, include ETF look-through and reconcile instrument, sector, factor, currency and residual contributions.

**Why it matters**  
Apparent alpha may be compensation for sector, currency or style exposure.

**Dependencies / cross-links**  
ISSUE-0105; ISSUE-0110; ISSUE-0116

**Required completion evidence**  
Attribution reconciles to portfolio return and reports residual and coverage.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0060 — Strategy rejection tests

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Tests currently assume all broker execution is forbidden.

**Required change**  
Keep unsafe strategies and LLM/news-only authority rejected; replace blanket broker-code rejection with stage/limit/approval checks from the new authority model.

**Why it matters**  
The final system needs controlled execution without permitting silent authority escalation.

**Dependencies / cross-links**  
ISSUE-0008; ISSUE-0070; ISSUE-0132; ISSUE-0133

**Required completion evidence**  
No plugin, model, strategy or configuration can bypass the staged authority state machine.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0061 — Pair-trading/cointegration research-only module

**Current status:** Open, research-only  
**Priority:** P3  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
It remains outside the long-only stock/ETF objective and would require shorting/borrow data.

**Required change**  
Keep research-only; if implemented later, require point-in-time pair selection, stationarity breaks, borrow, costs and multiple-testing controls.

**Why it matters**  
Cointegration can be unstable and is not needed to finish the stated long-term product.

**Dependencies / cross-links**  
ISSUE-0120; ISSUE-0128

**Required completion evidence**  
Completion means a bounded specification and enforced exclusion from default scoring/order authority.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0062 — Triple-barrier and purged-CV research-only module

**Current status:** Open, research-only  
**Priority:** P3  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Purged/embargoed validation is useful generally, while triple-barrier labels remain optional and potentially overcomplicated.

**Required change**  
Promote leakage-safe validation into ISSUE-0120; keep triple-barrier labels optional with minimum sample, stability and transparent parameter rules.

**Why it matters**  
Complex labels can create hidden trials and overlap leakage without improving long-horizon return forecasts.

**Dependencies / cross-links**  
ISSUE-0119; ISSUE-0120

**Required completion evidence**  
General validation is production-ready and optional labels cannot silently replace declared horizon targets.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0063 — Close-based quality-momentum next-open template hardening

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The template is not yet based on canonical point-in-time quality factors and full execution/capacity evidence.

**Required change**  
Rebuild it on official fundamentals, sector-neutral quality, canonical momentum, next-session order simulation, costs, capacity and forward paper evidence.

**Why it matters**  
It is a useful transparent reference strategy, but must beat quality-only, momentum-only and equal-weight baselines after costs.

**Dependencies / cross-links**  
ISSUE-0092; ISSUE-0098; ISSUE-0125; ISSUE-0129

**Required completion evidence**  
Untouched-test and forward-paper gates pass with complete assumptions and trial history.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0064 — Friction-adjusted return estimate per evidence score

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Current expected edge is partly derived from score/technical terms rather than a horizon-specific return model.

**Required change**  
Replace score-to-edge mapping with the expected-return distribution and order-size cost model; preserve the old fields only as migration output.

**Why it matters**  
A 0–10 evidence score is ordinal support, not a calibrated percentage return.

**Dependencies / cross-links**  
ISSUE-0108; ISSUE-0128

**Required completion evidence**  
Displayed and optimiser-used gross/net returns share one calculation, uncertainty and cost lineage.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0065 — Payoff-profile classification and risk/reward asymmetry display

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Current labels rely on limited period-return summaries.

**Required change**  
Use trade and period distributions, skew/tails, regime stability, confidence intervals and minimum samples. Keep labels descriptive only.

**Why it matters**  
Hit rate and payoff mean different things for trend, value and rebalance strategies.

**Dependencies / cross-links**  
ISSUE-0049; ISSUE-0111; ISSUE-0125

**Required completion evidence**  
Insufficient samples remain unavailable and classifications are stable/reproducible.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0066 — Source-of-truth and reconciliation architecture for future execution

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The architecture is documented but not implemented and assumes future-only execution.

**Required change**  
After the scope ADR, implement canonical order/fill ledgers, broker read-only sync, idempotency, partial-fill/cancel handling, reconciliation and incident recovery before submission.

**Why it matters**  
Paper, local and broker states inevitably diverge; the broker account must remain operational truth.

**Dependencies / cross-links**  
ISSUE-0070; ISSUE-0127; ISSUE-0131; ISSUE-0135

**Required completion evidence**  
Read-only reconciliation is proven and no order can be sent while state is unknown or divergent.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## ISSUE-0068 — Two-tier universe manager and provider policy editor

**Current status:** Implementation complete; closure pending  
**Priority:** P0/P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Rigid primary/secondary tiers do not express final capability, coverage and authority policies.

**Required change**  
Generalise to data/analysis policy profiles with coverage, classification confidence and dependency plans while keeping compatibility with current tiers.

**Why it matters**  
Instruments need different provider, document, model and order capabilities, not merely two importance classes.

**Dependencies / cross-links**  
ISSUE-0076; ISSUE-0080; ISSUE-0082; ISSUE-0083

**Required completion evidence**  
Saving changes creates an explicit backfill/invalidation plan and never implicitly analyses or trades.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0011 — Symbol/ISIN/exchange identity resolver

**Current status:** Open, partial  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Listing identity is incomplete for entities, funds, share classes, historical aliases and corporate events.

**Required change**  
Absorb into the identity master: entity/security/fund/share-class/listing separation, CIK/LEI/ISIN/MIC/ticker mappings, valid dates, confidence and review.

**Why it matters**  
Ticker-only joins cause provider conflicts, incorrect histories and potentially wrong orders.

**Dependencies / cross-links**  
ISSUE-0082; ISSUE-0083

**Required completion evidence**  
All source rows resolve or remain explicitly quarantined; historical identifiers remain reproducible.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0012 — SEC EDGAR official statement importer

**Current status:** Implementation complete; closure pending  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The importer needs final live/bulk, clean-first-run and normalised-statement integration evidence.

**Required change**  
Prefer nightly submissions/companyfacts bulk ZIPs, retain raw filings/amendments and availability time, support resumable increments and connect to canonical statements.

**Why it matters**  
SEC is an official no-key source, but fair-access and point-in-time correctness still matter.

**Dependencies / cross-links**  
ISSUE-0081; ISSUE-0073; ISSUE-0091

**Required completion evidence**  
Real bulk/parser/identity/audit/package evidence passes under SEC access policy.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0014 — France DILA and Netherlands AFM OAM discovery adapters

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Two bespoke adapters will not scale across supported European jurisdictions.

**Required change**  
Create a country/regulator adapter framework with source snapshots, coverage, terms, retries, manual fallback and no prohibited scraping.

**Why it matters**  
Official European filing discovery is fragmented before a complete single access point.

**Dependencies / cross-links**  
ISSUE-0087; ISSUE-0076

**Required completion evidence**  
Each adapter has real fixtures, declared coverage, legal status and explicit unavailable behaviour.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0015 — ETF disclosure registry

**Current status:** Implementation complete; closure pending  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The registry is not yet the canonical, versioned source for all fund/share-class documents.

**Required change**  
Store document type, fund/share class, effective/publication date, source, checksum, supersession, extraction state and parser version.

**Why it matters**  
Every ETF-derived structural or cost metric needs a durable document source.

**Dependencies / cross-links**  
ISSUE-0103; ISSUE-0104; ISSUE-0090

**Required completion evidence**  
No document-derived value exists without registry provenance and release evidence.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0016 — ETF holdings normaliser

**Current status:** Implementation complete; closure pending  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Normalisation does not yet cover nested funds, derivatives, cash, shorts, currencies and historical snapshots completely.

**Required change**  
Resolve holdings to canonical IDs; retain unresolved weights; handle nested/cyclic structures, cash/derivatives and history.

**Why it matters**  
Look-through risk and valuation are invalid if unknown weights are silently renormalised away.

**Dependencies / cross-links**  
ISSUE-0082; ISSUE-0105

**Required completion evidence**  
Holdings reconcile within tolerance with resolved/unresolved coverage and dated source evidence.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0017 — PRIIPs KID parser

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Parser coverage across languages/templates and table confidence remains incomplete.

**Required change**  
Add versioned template/language plugins, page-level evidence, risk/scenario/cost/holding-period fields and human-review queues without inventing values.

**Why it matters**  
KIDs contain useful retail product evidence but PDF extraction is brittle.

**Dependencies / cross-links**  
ISSUE-0103; ISSUE-0104

**Required completion evidence**  
Real issuer fixtures, mutation tests, source pages and strict unavailable states pass.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0018 — ETF prospectus, annual and half-year report parser

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The final fund-report extraction workflow is absent.

**Required change**  
Use the disclosure registry, bounded parsers, page-level provenance, language/template plugins and human verification; prioritise structured fields over broad generative extraction.

**Why it matters**  
These reports contain legal structure, holdings, lending, collateral, costs and operational risks unavailable from price feeds.

**Dependencies / cross-links**  
UPDATEV2-0015; ISSUE-0104

**Required completion evidence**  
Every extracted field has source page, date, confidence and explicit unavailable state.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0019 — Index methodology importer

**Current status:** Implementation complete; closure pending  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Imported documents are not fully converted into versioned benchmark rule evidence.

**Required change**  
Extract eligibility, universe, weighting, caps, rebalance, corporate-action and governance rules; simulate only complete methodologies.

**Why it matters**  
ETF behaviour and turnover depend on benchmark construction, not only current holdings.

**Dependencies / cross-links**  
ISSUE-0105; ISSUE-0112

**Required completion evidence**  
Methodology evidence links to holdings/exposure and incomplete rules cannot be simulated as facts.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0020 — SFDR disclosure parser

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Sustainability disclosures are not yet parsed and conflicted over time.

**Required change**  
Store dated Article/PAI/methodology claims, source pages, conflicts and greenwashing warnings; keep all sustainability labels context-only for expected return.

**Why it matters**  
Disclosure categories describe mandate and reporting, not proven alpha.

**Dependencies / cross-links**  
UPDATEV2-0015; ISSUE-0104; ISSUE-0149

**Required completion evidence**  
Every claim is dated/source-linked and cannot directly change an order or expected-return model.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0021 — Source conflict resolver and canonical metric selector

**Current status:** Open, partial  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Conflict selection is not yet complete for period, unit, currency, restatement and metric-specific authority.

**Required change**  
Implement deterministic arbitration with candidate retention, authority, date/context matching, tolerances, quarantine and human resolution.

**Why it matters**  
Multiple providers and filings will disagree; silently choosing the latest or non-null value is unsafe.

**Dependencies / cross-links**  
ISSUE-0073; ISSUE-0089; ISSUE-0090

**Required completion evidence**  
Every canonical value retains all candidates, decision rule, conflict state and reproducible resolution.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0023 — FMP optional provider adapter

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
It is a keyed vendor and conflicts with the mandatory no-quota requirement.

**Required change**  
Keep as an optional enrichment/verification plugin with licence, quota, cache and authority metadata. Exclude it from release completion and mandatory scoring.

**Why it matters**  
Vendor fundamentals can improve coverage but cannot be assumed free, unlimited or official.

**Dependencies / cross-links**  
ISSUE-0076; ISSUE-0080

**Required completion evidence**  
Core outputs remain usable when absent; vendor values never silently override official evidence.

**Mandatory free/no-quota policy**  
Optional only; no paid/keyed FMP capability may be required by tests, scoring or release certification.


## UPDATEV2-0024 — Alpha Vantage verification/fallback adapter

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The small keyed call budget is unsuitable for broad mandatory refresh.

**Required change**  
Keep selected-ticker verification only, with explicit daily budget, cache replay and quota-exhausted state.

**Why it matters**  
A limited vendor source may catch discrepancies but cannot provide an unrestricted universe backbone.

**Dependencies / cross-links**  
ISSUE-0076; ISSUE-0080

**Required completion evidence**  
Absence or quota exhaustion affects only optional verification and never corrupts canonical data.

**Mandatory free/no-quota policy**  
Optional only; the mandatory app must work with no Alpha Vantage key or calls.


## UPDATEV2-0025 — Finnhub experimental adapter with entitlement probes

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Entitlement and historical availability cannot be assumed.

**Required change**  
Keep disabled experimental plugin, probe every capability, preserve terms/secret controls and exclude it from score/release authority.

**Why it matters**  
Current-only or inaccessible vendor data can create historical leakage and brittle dependencies.

**Dependencies / cross-links**  
ISSUE-0076; ISSUE-0080

**Required completion evidence**  
No data enter historical analysis without proven entitlement, time coverage and point-in-time metadata.

**Mandatory free/no-quota policy**  
Optional experimental only; it is never a release blocker or mandatory source.


## UPDATEV2-0026 — Candle feature/context/backtest module

**Current status:** Open  
**Priority:** P1  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Named candle-pattern logic risks overfitting and ambiguous OHLC execution paths.

**Required change**  
Prefer continuous OHLCV/gap/range features with bar-quality validation and low authority; retain score caps and explicit path ambiguity.

**Why it matters**  
Candles can aid context and execution analysis but have weak standalone evidence for long-term decisions.

**Dependencies / cross-links**  
ISSUE-0084; ISSUE-0125; ISSUE-0128

**Required completion evidence**  
Candle evidence remains capped, source-linked and incapable of directly generating an order.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0027 — UI workflow/button reliability and progress indicators

**Current status:** Open, partial  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
It duplicates foundation issues and is not backed by final typed commands/jobs.

**Required change**  
Merge implementation with the action inventory, API/view models and durable job system; cover training, paper and operations controls.

**Why it matters**  
Reliability must come from command contracts and persisted state, not page-specific callbacks.

**Dependencies / cross-links**  
ISSUE-0011; ISSUE-0012; ISSUE-0077; ISSUE-0136

**Required completion evidence**  
Generated inventory, command tests, idempotency and packaged E2E evidence pass.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0029 — Rebuild/test/update discipline automation

**Current status:** Open  
**Priority:** P0  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
Finish-check automation does not yet constitute a protected, hermetic release pipeline.

**Required change**  
Implement CI, environment locks, closure manifests, signed artefacts, SBOM, issue-state reconciliation and protected promotion.

**Why it matters**  
Release discipline must be machine-enforced across all features.

**Dependencies / cross-links**  
ISSUE-0141; ISSUE-0145; ISSUE-0152

**Required completion evidence**  
Closure recommendation is produced only by passing machine-verifiable gates.

**Mandatory free/no-quota policy**  
The mandatory path must work from local cache, official bulk/public files or user-owned imports. Remote quota failure must be visible, non-destructive and non-blocking.


## UPDATEV2-0030 — Optional OHLCV fallback providers: Stooq, Twelve Data and Tiingo

**Current status:** Open  
**Priority:** P2  
**Recommended treatment:** Expand or complete within the final programme

**Current gap**  
The grouped issue mixes a best-effort public source with keyed commercial services.

**Required change**  
Split policy: Stooq best-effort cached fallback where terms/coverage permit; Twelve Data/Tiingo optional keyed plugins; user/broker files are the quota-independent fallback.

**Why it matters**  
No remote market source can be guaranteed unlimited, and fallback disagreements must not overwrite authority.

**Dependencies / cross-links**  
ISSUE-0080; ISSUE-0086; ISSUE-0089

**Required completion evidence**  
All outputs are normalised, discrepancy-audited and optional-provider absence does not block core completion.

**Mandatory free/no-quota policy**  
Only local/user-owned files are guaranteed quota-independent; all remote sources are cached and optional by policy.
