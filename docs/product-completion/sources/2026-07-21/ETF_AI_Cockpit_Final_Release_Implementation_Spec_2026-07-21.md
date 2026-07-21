---
schema_version: "1.0"
document: "ETF_AI_Cockpit_Final_Release_Implementation_Spec_2026-07-21.md"
generated_on: "2026-07-21"
repository: "Thor2709/etf_ai_cockpit"
target_branch: "main"
audited_commit: "452d44034197cd5d837c1854603eea030e02acf6"
audited_commit_description: "merge of PR #429"
working_assumption: "Re-fetch origin/main and revalidate before the first write"
review_status: "implementation-ready owner specification"
model_target: "GPT-5.6 Sol, high reasoning, root orchestrator"
execution_allowed: false
live_order_activation_authorised: false
new_issue_range_provisional: "ISSUE-0153–ISSUE-0176"
source_open_record_count: 155
---

# ETF AI Cockpit — Final Release Implementation Specification

## 0. Operating instruction and authority

This file is the canonical implementation packet for the final pre-release programme. It combines the accepted Step 2 sequence, the GPT-5.6 orchestration standard, the complete product/issue specification, the current open-issue status audit and a live repository inspection at commit `452d44034197cd5d837c1854603eea030e02acf6`.

The root Codex agent MUST implement the programme, not rewrite this specification. It MUST perform only the minimum current-state verification needed to avoid stale or duplicate work. External research is limited to current official documentation for a dependency, protocol, legal/terms record or provider interface that the selected issue explicitly requires. Product behaviour, release priority, financial semantics and safety boundaries come from this file and the current repository evidence.

### 0.1 Source precedence

Apply this precedence whenever two sources differ:

1. The latest explicit product-owner decision in this file.
2. Binding safety, security, licence, legal, protocol and compatibility contracts.
3. The detailed issue contract and cross-cutting invariants in this file.
4. Approved ADRs, typed schemas and accepted behavioural tests at the freshly fetched base revision.
5. Current implementation behaviour.
6. Historical plans, comments and stale tracker prose.

Do not silently choose between two materially conflicting sources at levels 1–4. Mark only the affected lane `BLOCKED`, record the exact conflict in the batch plan, and continue independent ready work.

### 0.2 Evidence labels

Use `VERIFIED`, `INFERRED`, `PROPOSED`, `UNKNOWN` and `STALE` exactly. A merge, open/closed tracker state or green unit test is not by itself proof that an issue is release-complete. `NO_CHANGE` is a valid result only with explicit reproduction/current-state evidence and all acceptance criteria satisfied.

### 0.3 Source inventory

| Source ID | Input | SHA-256 | Role |
|---|---|---|---|
| S1 | `PLAN_step2(2).md` | `93d32bc63895f3c0ee91704ea0b5ec056e0b789e4e97d6b9571294cd2a6ddb90` | Accepted Step 2 integration sequence and working-tree policy |
| S2 | `GPT56_Codex_Finalplan_Research_and_Authoring_Spec_2026-07-21(1).md` | `52b713a6d6824baf806856b41a05a62b488e503ce1fe71edae276a499a33d391` | GPT-5.6/Codex authoring, orchestration and agent standard |
| S3 | `ETF_AI_Cockpit_Complete_Combined_Master_Issue_Specification_2026-07-21_Remaining_Gaps_Expanded(1).md` | `a6c70c02031019f24f121baa02f1340e12d9f37aa9762a3576f977e9312b67b9` | Consolidated product contract, amendments and proposed issues |
| S4 | `ETF_AI_Cockpit_Step2_Open_Issue_Status_2026-07-21(1).md` | `aa812fb1caf2b60eca329e19bc93f375d6f5d1d0a6e53a58ac044d0b9bd96222` | Current-state audit of all 155 open Step 2 records |
| R1 | Live repository `Thor2709/etf_ai_cockpit` | `452d44034197cd5d837c1854603eea030e02acf6` | Audited `main` head, merge of PR #429 |


### 0.4 Freshness gate

Before any edit:

1. Fetch remotes and record the full current `origin/main` SHA, branch protection state, open PRs and working-tree state.
2. Use a fresh isolated worktree. Do not touch an unrelated dirty checkout.
3. Re-read all applicable instruction files and record their precedence.
4. Re-run the issue-ID collision check. `ISSUE-0153`–`ISSUE-0176` were absent from the audited live tracker and local registry, but their IDs remain provisional until this gate passes.
5. Reconcile changes since `452d440…`; mark affected evidence `STALE` and update this plan/status before implementation.
6. Record model alias/snapshot where available, reasoning effort, Codex version, configuration hash, instruction hash and tool/permission set in `plans/BATCH-<id>.md`.

## 1. Executive state and target release

### 1.1 Verified state at the audited revision

The repository contains substantial integrated foundations: a typed in-process application API, durable jobs, a canonical score-engine foundation, local storage/versioning foundations, a static UI acceptance inventory, a protected Windows/Linux release workflow, a full-release gate script, source/package smoke paths, performance budgets, security/privacy/legal validators and managed GitHub issue synchronisation.

The programme is not complete. The attached status audit records 155 open Step 2 records: 59 `implemented_initially`, 48 `planned`, 32 `integrated`, 9 `in_progress`, 4 `hardening_required`, 2 `research_only` and 1 `blocked`. The tracker vocabulary deliberately distinguishes a first implementation or merge from evidenced release closure.

The latest merged PR reports a passing full pytest suite, focused tests, Ruff, compileall, registry freshness and offline smoke. Treat that as PR evidence rather than an independently repeated final certification. The GitHub connector returned no workflow-run/status evidence for the audited head; absence of returned checks MUST NOT be interpreted as a pass.

### 1.2 Target product

The release target is a private, local-first decision-support application with one canonical data/calculation spine. Release priority is:

- **P0 Core Research:** individual analysis and reproducible top-N screening for supported stocks, ETFs, ordinary mutual/index funds and supported bonds; exact horizons `1W`, `1M`, `3M`, `6M`, `9M`, `2Y`, `5Y`; user-selected output currency; peer-valid evidence; five editable risk profiles; Quick/Medium/High/Full analysis depth; uncertainty, costs, coverage and audit evidence.
- **P1 Read-only Portfolio Intelligence:** ledger-derived performance, holdings, exposure, what-if, income/events and risk. It has a separate certification lane and cannot hold a safe P0 research release hostage unless it owns a shared P0 contract.
- **P2 Paper/Broker Operations:** paper and read-only broker workflows, deterministic proposals, controls, reconciliation and operational evidence. Live execution remains disabled by default and is not activated by this programme.

### 1.3 Definition of the main release

The main release is achieved only when every accepted in-scope record is truthfully classified, all release-blocking acceptance criteria have executable evidence, every visible control and workflow behaves correctly in source and packaged modes, the performance and security gates pass, documentation and GitHub metadata converge, and an independent reviewer has no unresolved material finding.

A feature is not complete when only its backend, page shell, happy path or unit test exists. Completion includes data contracts, migration, application service, UI/view model, loading/empty/partial/error/retry/cancel/unavailable states, accessibility, audit/export, documentation, source/package behaviour, restart/replay where applicable and release evidence.

### 1.4 Non-negotiable safety boundary

`execution_allowed=false` remains the controlling default. Models and LLMs never submit orders, alter hard risk gates or grant themselves authority. Implementing canary interfaces, paper workflows or broker contracts does not activate live trading. Do not create a release tag, publish artefacts externally, deploy, or enable a live authority state without a separate explicit product-owner instruction after certification.

## 2. Mandatory programme corrections before feature fan-out

These corrections are Wave 0. They remove known control-plane drift and prevent the later agents from implementing against false readiness or stale documentation.

### 2.1 Dynamic registry and issue-family expansion

**Why:** the live registry/build scripts are hard-coded around 159 package records, phase ranges ending at `ISSUE-0152`, and status overrides created for the earlier bundle. Adding 24 accepted issue contracts without fixing those assumptions will produce invalid counts, stale phase documents and misleading readiness.

**Implement:**

- Extend the registry schema with stable typed fields for `blocking_dependencies`, `required_inputs`, `activation_dependencies`, generated `downstream_issues`, `related_issues`, provenance, verified commit/date, acceptance evidence, capability lane, release-blocking flag, write-conflict group and risk.
- Replace exact record-count and last-ID assertions with schema-/source-derived invariants. Retain strong checks for uniqueness, ID format, acyclic blocking graph, generated reverse links and source-to-canonical reconciliation.
- Add phases/ranges for `ISSUE-0153`–`ISSUE-0176` without forcing unrelated issues into one phase. Generate counts and phase coverage from records.
- Preserve existing IDs. Recheck the live tracker immediately before creation and renumber only colliding proposed IDs while preserving dependency semantics.
- Migrate registry/status/roadmap readers and UI projections in one compatible change.

**Acceptance:** a registry containing the current records plus the adopted new records validates without hard-coded total counts; removing, duplicating, cycling or mis-linking a record fails deterministically; all generated status/phase artefacts reproduce byte-for-byte from the registry.

### 2.2 Correct readiness semantics

**Why:** the audited `ready_records` logic treats `implemented_initially`, `integrated` and `hardening_required` blockers as satisfied. Those statuses explicitly do not prove acceptance or closure.

**Implement:**

- Readiness depends on resolved `blocking_dependencies`, not a status label alone.
- A dependency is resolved only when its required contract output is evidenced as complete for the consuming edge, or when an explicit, reviewed dependency-edge waiver/partial-interface contract exists.
- `required_inputs` inform implementation but do not block readiness.
- `activation_dependencies` may allow disabled scaffolding to be implemented while preventing capability activation.
- A hard-coded `ready` state cannot bypass unresolved blockers.
- Produce reason codes for every ready/not-ready decision and display them in programme/release-readiness views.

**Acceptance:** property tests prove no unresolved blocker can be bypassed by status mutation; edge-specific partial completion is explicit and reproducible; the ready list changes only when the registry evidence or dependency graph changes.

### 2.3 Canonical plan, README and ledger convergence

**Why:** the live README and `plan.md` still describe a narrower ETF/stock, 1-week-to-9-month v0.1 workflow. They are no longer accurate release documentation.

**Implement:**

- Replace the stale planning narrative with this programme, while preserving useful historical context in an archive/changelog rather than silently deleting it.
- Rewrite README purpose, supported assets, exact horizons, currencies, risk profiles, depth modes, local-first data limitations, install/run/test/package instructions, execution-disabled boundary and release maturity.
- Update `issues/open.md`, `issues/closed.md`, `issues/issue_registry.json`, `docs/product-completion/CURRENT_STATUS.json`, `PROGRESS.md`, roadmap, phase documents, System Map/Programme Map, feature registry, authority matrix, release-readiness UI and changelog.
- Generate documentation from canonical data where practical. Add drift tests for generated files, links and commands.
- Do not move an issue to closed merely to make counts look complete.

**Acceptance:** one registry change regenerates every derived artefact; documentation commands execute on a clean checkout; README claims match capability and certification states; all issue counts and IDs agree locally and on GitHub.

### 2.4 Managed GitHub issue synchronisation

**Why:** the repository has a checksum-gated, managed-block synchroniser; bypassing it would lose traceability or overwrite human content.

**Implement:**

1. Update the canonical local registry and ledgers first.
2. Generate a deterministic remote snapshot and sync plan with `scripts/sync_github_issues.py`.
3. Review creates/updates/closes/reopens, duplicate mapping and preserved human text.
4. Apply only the reviewed plan SHA-256.
5. Read back and require a convergent no-op plan.
6. Attach issue → acceptance criteria → files/tests → commit/PR evidence.
7. Close a GitHub issue only when the canonical ledger is closed and closure evidence is complete. Keep `implemented_initially`, `integrated`, `hardening_required` and blocked records open.

**Acceptance:** dry-run is deterministic; checksum mismatch blocks apply; managed blocks converge; human text outside managed markers is retained; a second sync produces zero actions.

### 2.5 Validation architecture: extend, do not duplicate

**Why:** `scripts/validate_app.py` already provides fast `quick`, `changed`, `issue` and `phase` dispatch, while `scripts/release_gate.py` and `.github/workflows/release-gate.yml` own full test/package/SBOM/signing evidence. A second validator framework would create drift.

**Implement:**

- Keep `validate_app.py` as the canonical developer dispatcher and stable validation-report schema under `artifacts/validation/latest/`.
- Add `--full`, `--offline`, `--packaged` and `--report-only` modes that delegate to existing canonical scripts rather than reimplement checks.
- Make `--full` invoke/compose the protected release gate and all release-blocking parity/UI/security/performance checks.
- Make `--offline` disable optional network providers and prove mandatory local paths.
- Make `--packaged` exercise the actual built artefact and compare source/package outputs.
- `--report-only` MUST NOT turn failures into success; it avoids mutation/promotion actions, records truthful status and exits non-zero when a mandatory check fails.
- Record command, exit code, duration, environment, Git state, logs, unavailable optional components and first causal failure.

**Acceptance:** every mandatory failure yields non-zero status in enforcing modes; reports are deterministic except declared timestamps/timings; existing release-gate functionality is reused; CI uploads the evidence.

### 2.6 Complete UI/control inventory and runtime proof

**Why:** the current AST inventory covers routes and many keyed click/file-picker controls, but source examples use `on_change`, `on_submit` and `on_select`; dialogs, menus, keyboard actions, dynamic controls and runtime audit linkage require broader proof.

**Implement:**

- Extend actionable-control discovery for all Flet state-changing/input event fields used by the application, helper factories, menus, dialog actions, file pickers, keyboard shortcuts, command-palette actions, dynamic rows and subwindows.
- Require a stable semantic key, route, label, callback/application command, success signal, controlled failure signal, permission/authority state, audit event and acceptance-test reference for every actionable control.
- Generate the inventory from source/typed command metadata where possible; preserve reviewed manual records only for constructs static analysis cannot resolve.
- Add runtime instrumentation proving control → typed command/query → durable workflow/audit event → visible terminal state.
- Test loading, empty, partial, unavailable, invalid input, duplicate click, cancellation, retry, restart, stale revision, permission denied and dependency failure.
- Run representative source and packaged journeys at supported viewport/scale settings with keyboard and screen-reader semantics.

**Acceptance:** deleting or adding an unregistered actionable control fails CI; every route opens; every control has a successful or deliberately blocked deterministic result; no click is a silent no-op; no unhandled exception, hidden modal, stuck progress indicator or orphaned workflow remains.

### 2.7 Performance and responsiveness

**Why:** the repository already has versioned budgets; the new bulk/depth/fund/bond workflows add much larger workloads.

**Implement:**

- Preserve current budgets unless measurement and review justify a versioned change: cold startup 5,000 ms; first durable event 2,000 ms; route render 1,000 ms; common query 500 ms; offline refresh 10,000 ms; scoring 30,000 ms; screens of 100/1,000/10,000 instruments at 1,000/3,000/10,000 ms; representative backtest 30,000 ms; optional training 120,000 ms; peak application memory 1,024 MiB; local evidence storage 10 GiB; default regression tolerance 10%.
- A long-running user action acknowledges visibly within 1 second and creates its durable workflow record within 2 seconds on the declared representative environment.
- Measure cold acquisition, warm refresh, feature calculation, inference, calibration, scenarios, ranking, export and training separately.
- Implement the `Quick`, `Medium`, `High`, `Full` profile SLOs from `ISSUE-0175` on the declared reference fixture. Store p50, p95, repetitions, cache state, hardware, provider wait and resource peaks.
- Profile first. Optimise only causal hot paths. Preserve numerical, lineage and safety equivalence.
- Use chunking, virtualisation, content-addressed reuse, bounded concurrency, cancellation and back-pressure. Never silently drop mandatory evidence to meet a timing target.

**Acceptance:** budget checks fail regressions beyond policy; bulk and UI remain responsive; CPU-only/older-device fallbacks preserve mandatory semantics; missed SLOs are reported as failed certification rather than fabricated estimates.

### 2.8 Final refactor and dead-path removal

**Why:** the final release must not retain multiple hidden calculation paths, presentation-layer finance logic or obsolete compatibility code that can diverge after launch.

**Implement in two stages:**

1. **Continuous boundary refactoring:** while each issue is implemented, move behaviour behind typed domain/application/provider interfaces, retain compatibility facades only with tests and prevent new debt.
2. **Dedicated final refactor wave:** after all functional contracts pass, remove proven dead/duplicate paths, collapse duplicate UI routes/components, retire legacy schemas through migrations, simplify state ownership, document architecture and rerun the complete parity/release ladder.

**Required architectural outcomes:**

- Presentation imports no provider, database or broker implementation directly.
- No page calculates canonical finance/model/portfolio values.
- One authoritative implementation exists per formula, score, forecast, risk, cost, ledger, proposal and authority transition.
- Durable workflow state is not duplicated in page/session stores.
- Generated artefacts are never hand-edited.
- Public/persisted compatibility changes have migrations and rollback/recovery evidence.
- Release-critical TODO/FIXME/temporary bypasses are removed or linked to an explicitly deferred non-release issue and surfaced as a limitation.
- Tests are not weakened to accommodate the refactor.

**Acceptance:** import-boundary and mutation tests kill alternate calculation/control paths; source/package golden outputs agree before/after; no unexplained dead code, duplicate route or unowned compatibility shim remains; performance does not regress beyond budget.

### 2.9 Capability-specific certification

Certify `CORE_ANALYSIS`, `BULK_SCREENING`, `FUND_ANALYSIS`, `FIXED_INCOME_ANALYSIS`, `PORTFOLIO_READ_ONLY`, `PAPER`, `BROKER_READ_ONLY` and disabled `LIVE_CANARY_SCAFFOLD` separately. A failed secondary lane does not falsely certify or unnecessarily disable an independent safe lane. No lane grants authority to another.

## 3. Product-wide implementation invariants

1. **One sealed analysis record:** detail, compare, bulk, screener, portfolio, backtest, paper and proposal paths reference the same versioned `AnalysisSnapshot`; presentation may format but not recalculate it.
2. **Point-in-time truth:** use only evidence available at the decision timestamp; preserve valid, publication, acceptance, retrieval, knowledge and revision times.
3. **No invented data:** missing, stale, conflicted, sparse or unsupported evidence is explicit and can block precision or authority. Never zero-fill an inapplicable metric or renormalise unknown holdings away.
4. **Financial semantics:** returns use adjusted/corporate-action-aware total-return data; currency conversion is point-in-time and multiplicative; fund NAV/dealing differs from ETF market trading; bond clean/dirty/accrued/yield conventions are explicit; external flows are not investment performance.
5. **Exact horizons:** only `1W`, `1M`, `3M`, `6M`, `9M`, `2Y`, `5Y` unless a later approved schema version adds one. Training wall time, historical label span, inference time and prospective maturity are distinct.
6. **Peer before opportunity:** raw facts and economically valid peer-normalised evidence are separate from common probabilistic outputs and VWCE/cash opportunity. Asset-specific raw scores are never pooled across asset classes.
7. **Risk profiles are projections:** Safe, Safe–Medium, Medium, Medium–Aggressive and Aggressive project one unchanged analysis through versioned policy. No profile overrides exclusions, evidence, liquidity or safety gates.
8. **Analysis depth is not hardware:** Quick/Medium/High/Full governs declared evidence/model breadth; low/standard/high hardware profiles govern resources. Shared mandatory results remain equivalent.
9. **Long-only boundary:** normal outputs are buy/add candidate, hold, avoid/no-trade, trim/sell candidate or manual review. Exclude leverage, shorting, derivatives, crypto, OTC/penny/very illiquid microcaps, leveraged/inverse products and complex structures from the normal path.
10. **Deterministic authority dominates models:** model and LLM outputs are evidence only. Proposal, controls, cash/settlement, reconciliation and operator authority are deterministic and auditable.
11. **Local-first mandatory path:** optional keyed/quota-limited providers and optional model packages fail visibly without breaking safe startup or the mandatory local workflow.
12. **Secrets remain secret:** credentials never enter YAML, Parquet, SQLite value fields, CLI arguments, logs, prompts, screenshots, crash reports, backups or audit packets.
13. **No backend-only closure:** every accepted user-visible capability includes typed API/view model, UI states, audit/export, documentation and source/package acceptance.
14. **No test laundering:** a test must fail for the intended pre-fix behaviour, assert observable outcomes and retain negative/edge/preserved cases. No lowered threshold, deleted assertion or broad skip without approved rationale.

## 4. Current completion baseline — all open Step 2 records

| Programme status | Open records | Required treatment |
|---|---:|---|
| `implemented_initially` | 59 | `AUDIT_AND_COMPLETE` |
| `planned` | 48 | `IMPLEMENT` |
| `integrated` | 32 | `AUDIT_AND_COMPLETE` |
| `in_progress` | 9 | `AUDIT_AND_COMPLETE` |
| `hardening_required` | 4 | `HARDEN_AND_CERTIFY` |
| `research_only` | 2 | `KEEP_RESEARCH_ONLY` |
| `blocked` | 1 | `BLOCKED_UNTIL_DEPENDENCIES` |
| **Total** | **155** | Every record is reconciled before release |

For every record below, the current canonical issue body remains in force. The “remaining implementation delta” is the minimum work still required at the audited revision; the detailed amendments in Annex A add or narrow requirements. Before editing, perform the no-change/current-state gate against the fresh base. Do not repeat already accepted implementation merely because the status is open.

### Current retained issues

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0007` — Add non-executable news/macro contradiction panel | `implemented_initially` | An initial non-executable contradiction/context panel exists. | Persist point-in-time typed contradictions with provenance, severity, confidence, expiry and resolution; link them to events/scenarios/exposures without score or order authority. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0008` — Add strategy taxonomy and scope/rejection matrix | `implemented_initially` | The initial strategy taxonomy and rejection boundaries exist. | Replace the blanket permanent broker ban with a per-strategy staged-authority matrix while keeping martingale, grid, LLM-only and sentiment-only authority rejected. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0010` — Add non-executable LLM thesis diary | `planned` | The scope, dependencies and safety boundary are registered; no implementation is recorded. | Build an immutable diary containing prompt/model/source/retrieval hashes, evidence snapshots, redaction, review, expiry and outcomes, excluded from scores and orders. | `IMPLEMENT` |
| `ISSUE-0011` — Full main-UI button reliability audit | `in_progress` | Some controls and representative workflows have been inventoried and tested. | Generate the complete action inventory from route/command metadata and test every control, stable ID, command contract and visible failure state in source and packaged builds. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0012` — Add visible progress/status indicators for long-running actions | `in_progress` | Immediate status/progress handling and partial persistent workflow records exist. | Move all long work to the durable job DAG with checkpoints, cancellation, resource metrics and one canonical event stream; remove parallel activity stores. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0013` — Rebuild package after every completed feature | `integrated` | Release/rebuild discipline and issue-level package evidence are integrated. | Enforce it in protected hermetic CI with pinned environments, full tests, package launch/smoke, SBOM, signing and machine-readable closure evidence. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0014` — Add end-to-end workflow test | `in_progress` | Partial browser and representative workflow evidence exists. | Add hermetic offline, best-effort online, migration, large-universe, training, paper-broker, recovery and packaged journeys as separate source/package/browser suites. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0015` — Add app-level feature map / roadmap page | `implemented_initially` | A feature/roadmap view exists. | Drive it entirely from the canonical registry and distinguish implementation, release, data, model, paper and live-authority readiness. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0016` — Full product navigation redesign | `implemented_initially` | A substantial navigation redesign has been implemented. | Finish the task-oriented Home/Discover/Instrument/Portfolio/Models/Backtest-Paper/Data Health/Audit/Settings structure, search and command palette. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0017` — First-run onboarding and setup wizard | `implemented_initially` | The initial onboarding wizard is implemented and marked closure-pending. | Add storage location, hardware profile, mandatory/optional providers, offline bootstrap, encryption/backup choices and explicit disabled execution defaults. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0018` — Watchlist and universe manager | `implemented_initially` | Watchlist/universe CRUD is implemented and marked closure-pending. | Connect edits to canonical identity/classification, dependency planning, point-in-time universes, delistings and cache invalidation without hidden analysis or orders. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0019` — Proper instrument detail page | `implemented_initially` | An evidence-rich instrument detail page is implemented. | Add full long-horizon and sector-specific research: return distributions, histories, peers, valuation/scenarios, factor risk, model cards and paper/order timelines. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0020` — Screener and filter system | `implemented_initially` | A functional screener/filter workflow exists. | Add reproducible as-of screens, sector adapters, factor percentiles, coverage/confidence filters, return distributions, portfolio impact and versioned saved queries. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0021` — Portfolio construction and allocation sandbox | `implemented_initially` | An initial portfolio sandbox exists. | Integrate factor risk, robust covariance, transparent optimisers, constraints, turnover/cost/tax lots, scenarios and attribution, always against simple baselines. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0022` — ETF overlap and look-through exposure engine | `implemented_initially` | Top-holdings overlap and initial exposure analysis exist. | Resolve complete/partial holdings to canonical entities; support nested funds, cash and derivatives, historical snapshots and uncertainty from unresolved weights. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0023` — Stock fundamentals quality module hardening | `implemented_initially` | The five-section yfinance-based fundamentals compatibility layer is implemented. | Use official point-in-time statements/restatements, sector adapters, accounting quality, capital efficiency and valuation scenarios; keep yfinance as compatibility context. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0024` — Earnings, dividends and event calendar | `implemented_initially` | An initial event calendar exists. | Unify earnings, dividends, splits, filings, guidance, rebalances, index changes and risk events in one availability-aware, timezone-precise canonical model. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0025` — Free news and filings dashboard | `implemented_initially` | A combined news/filings context workflow is implemented. | Separate durable official evidence from best-effort news; add archive, deduplication, entity mapping, terms controls and event/contradiction integration. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0026` — Macro regime dashboard | `implemented_initially` | An initial macro/regime dashboard exists. | Build a vintage-aware local macro/factor warehouse linked to countries, currencies and scenarios; keep regimes contextual unless prospectively validated. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0027` — Forecast lab page | `implemented_initially` | Forecast rows and basic calibration/model controls exist. | Add governed experiments, simple baselines, walk-forward splits, uncertainty/conformal calibration, drift, challenger status, resource use and promotion evidence. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0028` — Backtest lab upgrade | `implemented_initially` | A vectorised rebalance backtest and initial lab exist. | Add point-in-time universes/fundamentals, deterministic order events, nested walk-forward validation, trial disclosure, multiple-testing control, capacity, tax, actions and reproducibility. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0029` — Strategy template builder | `planned` | The template concept, dependencies and acceptance rules are registered. | Implement versioned compositions of approved features, scores, forecasts, portfolio/risk and execution policies, including complexity, trials and authority. | `IMPLEMENT` |
| `ISSUE-0030` — Decision journal | `implemented_initially` | An initial decision journal exists. | Store accepted/rejected/deferred choices, alternatives and invalidation rules with immutable links to evidence, model, proposal, order and later outcomes. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0031` — Paper trading module | `integrated` | Paper-trading functionality is merged and integrated. | Complete the realistic broker lifecycle: cash, fees, FX, actions, partial fills, cancellations, calendars, accounting, restart recovery and reconciliation. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0032` — Future broker-execution architecture document only | `planned` | The architecture requirement and staged safety boundary are documented in the registry. | After the scope ADR, document and gate broker read-only, draft-order and capped-live stages using official APIs, with submission disabled until prerequisites pass. | `IMPLEMENT` |
| `ISSUE-0033` — Alerts and review reminders | `planned` | The alert/reminder scope is registered. | Implement typed events, severity/confidence, deduplication, snooze/expiry, alert backtesting and portfolio/order/model incident escalation rules. | `IMPLEMENT` |
| `ISSUE-0034` — What changed since last run page | `implemented_initially` | A change-comparison page is implemented and marked closure-pending. | Explain changes through source revisions, corrections, classification, formula/model/policy versions, portfolio targets and paper/order state with causal dependency paths. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0036` — Import/export centre | `implemented_initially` | An import/export centre is implemented and marked closure-pending. | Add broker/exchange statements, bulk datasets, reusable mappings, dry-run diffs, resumable imports, rollback and encrypted portable backups. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0037` — Config editor UI | `planned` | The configuration-control requirements are registered. | Implement typed schemas and migrations, safe defaults, staged edits, validation, secret-vault integration and before/after policy-impact previews. | `IMPLEMENT` |
| `ISSUE-0038` — Local database / storage migration plan | `integrated` | Hybrid-storage foundations and migration planning are integrated. | Finish DuckDB/Parquet analytics plus SQLite transactional state, migrations, integrity, retention, compaction, concurrency and export compatibility. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0039` — Performance and caching audit | `in_progress` | Initial timings, caching work and performance instrumentation exist. | Define and enforce versioned budgets/regression gates for startup, queries, scoring, large universes, training, memory, package size and storage. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0040` — Error handling and recovery centre | `in_progress` | Partial controlled-error and recovery handling exists. | Cover databases, jobs, models, imports and broker divergence with resumability, quarantine, last-known-good generations and tested incident runbooks. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0041` — Accessibility, responsive layout and table usability | `implemented_initially` | Initial responsive/accessibility/table improvements are implemented. | Complete WCAG-oriented keyboard, focus, screen-reader, high-contrast, reduced-motion, zoom and virtualised-table testing across final workspaces. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0042` — Charts, tables and CSV export improvements | `implemented_initially` | Chart, table and CSV improvements are implemented. | Add linked charts, aligned currency/timezone/horizon controls, confidence/coverage overlays, virtualisation and exports containing exact query/filter/version context. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0043` — User manual, glossary and in-app explanations | `planned` | Documentation scope and dependencies are registered. | Document final methodology, operations, limitations, sector/ETF adapters, data licences, paper/live procedures, incidents and reproducibility. | `IMPLEMENT` |
| `ISSUE-0044` — Backup, restore, version and changelog | `implemented_initially` | An initial backup/restore/version workflow exists. | Add incremental encrypted database-aware backups, retention, consistency/signing, key recovery, clean-machine restore drills and schema compatibility. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0045` — UI semantic locators and visual smoke tests | `in_progress` | Partial browser/screenshot evidence and some UI test contracts exist. | Create deterministic page objects, accessibility locators, fixtures, visual baselines and cross-resolution/browser tests; replace coordinate actions where possible. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0046` — Monthly decision template: basket vs benchmark vs cash | `planned` | The decision-template specification is registered. | Drive it from versioned return distributions, constraints, costs, events, capacity and forward evidence, always including no-action, benchmark and cash alternatives. | `IMPLEMENT` |
| `ISSUE-0047` — Feature-driver explanations for every evidence component | `implemented_initially` | Initial component-driver explanations exist and are marked closure-pending. | Add peer percentiles, historical contribution, coverage, uncertainty, interactions and counterfactual sensitivity without causal overclaiming. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0048` — Strategy complexity and overfitting penalty metadata | `integrated` | Complexity/overfitting metadata foundations are integrated. | Retain every attempted trial, return series, feature, parameter and selection decision; calculate DSR/PBO/multiple-testing evidence and effective search burden. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0049` — Worst-day, loss-cluster and tail-event diagnostics | `implemented_initially` | Initial payoff and loss diagnostics exist. | Add worst windows, drawdown duration, expected shortfall, loss clustering, tail dependence, liquidity stress and factor/sector contributions with bootstrap uncertainty. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0050` — Operational evidence panel for next-open/decision-price realism | `implemented_initially` | An initial execution-timing evidence panel exists. | Use canonical sessions and orders to show decision, arrival, open/close, spread, auction, expiry and realised paper/live fill evidence. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0051` — Cash proxy and risk-free/defensive comparison everywhere relevant | `planned` | The comparison requirement is registered. | Use official currency- and horizon-matched curves/proxies, declared reinvestment, inflation context and explicit unavailable states. | `IMPLEMENT` |
| `ISSUE-0052` — Correlation clustering and factor-crowding warnings | `implemented_initially` | Initial clustering/crowding warnings exist and are marked closure-pending. | Connect them to canonical factor risk and historical look-through holdings; quantify stability, uncertainty and portfolio-risk contribution. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0053` — What matters today digest | `planned` | The digest scope is registered. | Generate a prioritised action queue from typed alerts, revisions, events, model drift, portfolio risk, proposals, incidents and recovery/export state. | `IMPLEMENT` |
| `ISSUE-0054` — Point-in-time news/sentiment validation rules | `implemented_initially` | Initial point-in-time news validation exists and is marked closure-pending. | Add article versions, corrections/retractions, timezone precision, archive availability, deduplication and mapping confidence; reject ambiguous historical availability. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0055` — Optional free provider research/stubs: SEC EDGAR, FRED, Stooq, RSS | `implemented_initially` | Initial provider research/stubs exist and are marked closure-pending. | Split sources by authority/quota/legal tier; make official bulk/local imports mandatory-capable and keep quota-limited or unofficial sources cached and optional. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0056` — Data-frequency suitability and unsupported-asset guardrails | `implemented_initially` | Initial suitability/unsupported-asset guardrails exist and are marked closure-pending. | Apply capability rules by instrument/listing, calendar, frequency, leverage, price state, horizon, model and order type at every stage. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0057` — Paper/forward evidence diary | `integrated` | A paper/forward evidence diary is integrated. | Freeze complete decision-time manifests, mature configurable outcomes and separate observation-only proposals from accepted paper orders. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0058` — Closed-source/promotional-claim detector for imported notes | `planned` | The evidence-review specification is registered. | Implement claim extraction and checks for source, licence, method, benchmark, drawdown, costs, sample, reproducibility and conflicts, with human override and measured error rates. | `IMPLEMENT` |
| `ISSUE-0059` — Benchmark-relative sector/theme attribution beyond single benchmark beta | `implemented_initially` | Initial instrument-level attribution exists and is marked closure-pending. | Add factor, sector, country, currency and residual decomposition, ETF look-through and reconciliation to portfolio returns. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0060` — Strategy rejection tests | `implemented_initially` | Unsafe strategy and blanket broker-execution rejection tests exist. | Retain unsafe-strategy rejection but replace the blanket broker ban with stage, limit and approval checks from the authority model. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0061` — Pair-trading/cointegration research-only module | `research_only` | It is explicitly retained as research-only and outside the long-only completion target. | No production implementation is required; any later work needs point-in-time pair selection, break detection, borrow, cost and multiple-testing controls. | `KEEP_RESEARCH_ONLY` |
| `ISSUE-0062` — Triple-barrier and purged-CV research-only module | `research_only` | Leakage-safe purged/embargoed validation is redirected to the main validation issue; triple-barrier remains optional research. | Only implement triple-barrier labels later under minimum-sample, stability and transparent-parameter rules. | `KEEP_RESEARCH_ONLY` |
| `ISSUE-0063` — Close-based quality-momentum next-open template hardening | `integrated` | The reference quality-momentum template is integrated. | Rebuild it on official point-in-time fundamentals, sector-neutral quality, canonical momentum, next-session simulation, costs, capacity and forward evidence versus simple baselines. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0064` — Friction-adjusted return estimate per evidence score | `integrated` | A friction/edge compatibility calculation is integrated. | Replace score-to-return mapping with horizon-specific return distributions and order-size cost models; retain old fields only for migration. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0065` — Payoff-profile classification and risk/reward asymmetry display | `implemented_initially` | Initial payoff-profile labels and summaries exist. | Use trade/period distributions, skew/tails, regime stability, confidence intervals and minimum samples; keep labels descriptive only. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0066` — Source-of-truth and reconciliation architecture for future execution | `planned` | The reconciliation architecture requirement is registered. | Implement canonical order/fill ledgers, broker read-only sync, idempotency, partial-fill/cancel handling, reconciliation and incident recovery before submission. | `IMPLEMENT` |
| `ISSUE-0068` — Two-tier universe manager and provider policy editor | `implemented_initially` | A two-tier universe/provider policy editor exists and is marked closure-pending. | Generalise it to capability-based data/analysis profiles with coverage, classification confidence and dependency plans while preserving compatibility. | `AUDIT_AND_COMPLETE` |

### Phase 1 — Governance, scope and completion contract

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0070` — Freeze the final product scope, completion contract and staged execution authority | `integrated` | The authority ADR, completion contract, capability matrix and disabled execution boundary are integrated. | Finish full policy/tamper/static-path acceptance, ensure every capability declares authority, and retain execution disabled until later certification. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0071` — Refactor into bounded domain, application, infrastructure and presentation modules | `integrated` | Initial domain/application/infrastructure/presentation boundaries and compatibility contracts are integrated. | Complete migration so presentation imports no provider/database/broker implementations, each calculation has one path, and architectural boundary checks cover the full codebase. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0072` — Implement the hybrid local analytical and transactional data platform | `integrated` | Core DuckDB/Parquet and SQLite storage foundations, repositories and migrations are integrated. | Complete migrated-install equivalence, atomic generation, crash/concurrency/integrity/performance tests, retention/compaction and tested backup/rollback. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0073` — Implement a bitemporal point-in-time and data-vintage model | `integrated` | Core bitemporal observation and as-of-query foundations are integrated. | Extend all relevant data to full availability/revision metadata and prove no look-ahead through revision, timezone/DST and as-of property tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0074` — Unify all scoring into a canonical score engine v3 | `integrated` | The canonical typed score engine and separated evidence outputs are integrated. | Finish stock/ETF/sector/horizon migration, exact cross-surface reconciliation, missing/conflict confidence behaviour, legacy-v3 differences and formula property tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0075` — Create formula, feature, dataset, model and policy version registries | `integrated` | Version/hash registries and lineage foundations are integrated. | Ensure every score, forecast, target, proposal and order resolves immutable versions; complete cache invalidation, migrations, historical readability and What Changed causality. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0076` — Define stable plugin contracts for providers, models, strategies and brokers | `integrated` | Initial plugin capability/configuration/health/authority contracts are integrated. | Migrate all adapters through them and complete conformance, malicious-plugin, compatibility, disabled-plugin and network-off tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0077` — Implement a durable resumable job DAG and workflow scheduler | `integrated` | A durable job/workflow scheduler foundation with persisted states is integrated. | Apply it to all long-running workflows and prove restart, idempotency, cancellation, failure propagation, no partial publication and resource reporting. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0078` — Set performance, memory, storage and latency budgets with regression profiling | `integrated` | Performance-budget and telemetry foundations are integrated. | Version representative datasets and enforce CI regression limits, responsive UI, soak/memory/storage tests and numerical/lineage equivalence on declared hardware. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0079` — Establish open-source intake, licence, provenance and upstream-update governance | `hardening_required` | An initial intake/provenance/licence governance process is present. | Complete SBOM and legal inputs, exact upstream/copy records, copyleft boundaries, notices, vulnerability/update policies and automated licence/attribution checks. | `HARDEN_AND_CERTIFY` |

### Phase 2 — Local-first data policy, identity and data platform

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0080` — Enforce a mandatory no-subscription, no-vendor-quota local-first data policy | `integrated` | The provider-tier and local-first mandatory/optional policy is integrated. | Prove the core with all optional providers disabled and no network; add quota/rate-limit/licence failure tests and complete UI disclosure of external costs. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0081` — Build a resumable bulk downloader, content-addressed cache and delta updater | `integrated` | A resumable downloader, content-addressed cache and staged update foundation are integrated. | Complete changed-server, interrupted-transfer, checksum, archive-bomb, idempotency, retention and atomic-promotion acceptance. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0082` — Create a global entity, instrument, fund, share-class and listing identity master | `planned` | The identity model, dependencies and acceptance criteria are fully specified. | Implement the entity/security/fund/share-class/listing graph, identifiers and historical aliases/events, deterministic matching, quarantine and human review. | `IMPLEMENT` |
| `ISSUE-0083` — Implement automatic asset, sector, industry and strategy classification with confidence | `planned` | The classification contract and public-taxonomy approach are specified. | Implement evidence-based classification, confidence/alternatives, special-structure handling, versioned overrides and measured accuracy on a labelled corpus. | `IMPLEMENT` |
| `ISSUE-0084` — Build corporate-action, total-return and currency-normalisation services | `planned` | The service scope and reconciliation rules are specified. | Implement raw prices/actions, adjusted and total-return series, full corporate actions, dated FX, provider reconciliation and provenance-preserving corrections. | `IMPLEMENT` |
| `ISSUE-0085` — Implement exchange calendars, sessions, holidays, auctions and market-state service | `planned` | The calendar-service design and audited-library requirement are specified. | Implement MIC/calendar/timezone mapping, holidays, early closes, DST, auctions, settlement and exceptional closures with unknown-calendar fail-closed behaviour. | `IMPLEMENT` |
| `ISSUE-0086` — Create user, broker and exchange historical price, position and transaction import pipelines | `planned` | Formats, security controls and reconciliation requirements are specified. | Implement idempotent imports, schema/mapping previews, canonical identity mapping, raw-file provenance, corrections/rollback and large/malformed-file tests. | `IMPLEMENT` |
| `ISSUE-0087` — Expand official filing discovery and ingestion across supported jurisdictions | `integrated` | A multi-jurisdiction official-filing ingestion foundation and coverage model are integrated. | Complete supported-country adapters, raw archives, timestamps, amendment/identity handling, terms conformance, manual fallback and coverage tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0088` — Build a versioned macro, factor, risk-free and benchmark data warehouse | `implemented_initially` | An initial versioned macro/factor/reference warehouse exists. | Complete Eurostat/World Bank/ECB/Treasury/public-factor coverage, decision-time vintages, units/frequencies, country/currency mapping, risk-free curves and revision tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0089` — Implement data anomaly detection, quarantine and cross-source reconciliation | `planned` | Quality states, tolerances and human-resolution requirements are specified. | Implement schema/range/continuity/unit/currency/action checks, pass-warn-quarantine-block states, candidate retention, arbitration, impact propagation and replay. | `IMPLEMENT` |
| `ISSUE-0090` — Create a data catalogue, lineage graph and reproducible dataset snapshots | `implemented_initially` | An initial catalogue, snapshot and lineage system exists. | Cover every raw/clean/derived dataset and upstream graph, generated dictionaries, impact/invalidation analysis, stale/orphan detection, licences and access classes. | `AUDIT_AND_COMPLETE` |

### Phase 3 — Stock statements, fundamentals, valuation and sectors

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0091` — Normalise multi-period financial statements, amendments and restatements | `integrated` | Canonical statement concepts, point-in-time histories and initial normalisation are integrated. | Expand the real-filing corpus and prove fiscal-calendar, unit, dimension, extension, restatement, identity-reconciliation and coverage behaviour. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0092` — Add profitability, margin durability, earnings quality and accrual analysis | `implemented_initially` | Initial profitability, margins and earnings-quality calculations and UI evidence exist. | Complete long histories, peer/sector normalisation, applicability, missing/negative treatment, accrual components and exact canonical-score reconciliation. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0093` — Add balance-sheet strength, liquidity, leverage and distress analysis | `implemented_initially` | Initial solvency, leverage and liquidity evidence exists. | Add debt maturities, leases/pensions/commitments, refinancing and operating stresses, sector-specific rules and confidence reduction for missing disclosures. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0094` — Add cash-flow quality, capital allocation, shareholder yield and dilution analysis | `planned` | The formulas, distinctions and acceptance tests are specified. | Implement cash conversion, capex proxies, FCF, acquisitions, dividends, buybacks, issuance, stock compensation, payout safety and aggregate-versus-per-share histories. | `IMPLEMENT` |
| `ISSUE-0095` — Add growth, revisions, guidance and earnings-surprise evidence with optional imports | `integrated` | Reported growth, reviewed guidance/optional consensus boundaries and supporting UI/tests are integrated. | Complete multi-period/base-effect/acquisition/restatement handling, optional-data-disabled and historical-leakage tests, source review and broader import coverage. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0096` — Implement relative valuation, intrinsic-value scenarios, reverse DCF and residual-income models | `implemented_initially` | Initial relative and intrinsic valuation scenarios are implemented. | Complete sector-applicable models, cash-flow/assumption reconciliation, reverse DCF/residual income, bull-base-bear distributions, sensitivity, fail-closed states and uncertainty. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0097` — Add capital efficiency, reinvestment, intangible investment and business-quality proxies | `implemented_initially` | Reported and optional adjusted capital-efficiency evidence, UI controls and issue-level tests are merged. | Expand history and sector-relative analysis; harden incremental denominators, outliers, intangible assumptions, disclosure-backed quality proxies and phase/package acceptance. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0098` — Create the stock sector-adapter and peer-cohort framework | `planned` | The adapter contract, cohort dimensions and fallback rules are specified. | Implement versioned adapter selection, as-of peer cohorts, minimum samples, robust ranks, broad-model fallback and confidence/override testing. | `IMPLEMENT` |
| `ISSUE-0099` — Implement bank, insurer and diversified-financial sector adapters | `planned` | The required regulatory, operating, valuation and stress metrics are specified. | Implement jurisdiction-aware bank/insurer/financial adapters using official evidence, exclude industrial metrics and test missing regulatory data and shocks. | `IMPLEMENT` |
| `ISSUE-0100` — Implement REIT, utility and infrastructure sector adapters | `planned` | Sector-specific FFO/AFFO, NAV/RAB, leverage and scenario requirements are specified. | Implement the adapters, explicit derivation/availability states, rate/inflation/refinancing stresses and payout/statement reconciliation. | `IMPLEMENT` |
| `ISSUE-0101` — Implement energy, materials and industrial cyclical-sector adapters | `planned` | Cycle, operational-driver and normalisation requirements are specified. | Implement multi-cycle margins, production/cost/reserve/backlog/utilisation evidence, commodity/input scenarios and insufficient-history confidence controls. | `IMPLEMENT` |
| `ISSUE-0102` — Implement software, semiconductor, healthcare and biotechnology adapters | `planned` | Recurring-economics, cycle, patent/pipeline and runway requirements are specified. | Implement official-evidence adapters, cash runway/dilution and event timing, concentration metrics, sector-specific valuation and explicit missing/binary-risk limits. | `IMPLEMENT` |

### Phase 4 — ETF economics, structure, exposure and context

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0103` — Implement ETF economics, fee, tracking and closure-quality analysis | `planned` | The fund/share-class economics and tracking requirements are specified. | Implement historical fees, tracking difference/error, assets/flows/age, distributions, benchmark reconciliation and transparently uncertain closure-risk proxies. | `IMPLEMENT` |
| `ISSUE-0104` — Implement ETF structural, legal, counterparty, lending and collateral risk analysis | `planned` | The document-derived structural-risk model is specified. | Implement versioned prospectus/report/KID extraction, replication/counterparty/collateral/lending/legal fields, conflicts, confidence caps and numeric stress where supported. | `IMPLEMENT` |
| `ISSUE-0105` — Build complete ETF look-through exposure, factor, valuation and quality analytics | `planned` | The complete/partial/nested look-through contract is specified. | Implement canonical holding resolution, nested/cycle handling, cash/derivatives/unresolved weights, historical snapshots and coverage-adjusted valuation/factor/quality aggregation. | `IMPLEMENT` |
| `ISSUE-0106` — Implement ETF liquidity, capacity, spread and premium-discount analysis | `implemented_initially` | Initial rolling liquidity, capacity and exact-identity context are implemented. | Add order-size/horizon-specific bid-ask, NAV/premium-discount and underlying/primary-market evidence, conservative stress estimates and liquidity-policy blocking. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0107` — Add ETF domicile, tax, distribution, currency and hedging context | `planned` | The contextual tax/currency/hedging boundaries are specified. | Implement document-backed domicile/structure/distribution/currency/hedge fields, optional generic tax drag and rate-differential hedge scenarios without personalised advice. | `IMPLEMENT` |

### Phase 5 — Expected return, risk and portfolio construction

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0108` — Implement horizon-aware probabilistic total-return distributions | `planned` | The horizon families, decompositions and uncertainty outputs are specified. | Implement separate week/month/1–3-year/3–10-year stock and ETF return models, net costs, quantiles, loss/shortfall probabilities and benchmark/cash-relative distributions. | `IMPLEMENT` |
| `ISSUE-0109` — Implement scenario, uncertainty, confidence and model-disagreement framework | `implemented_initially` | An initial scenario, confidence and model-disagreement framework exists. | Separate data/parameter/model/scenario/execution uncertainty fully, propagate it through portfolio/proposals and enforce conservative confidence caps and disagreement blocks. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0110` — Build a transparent multi-factor risk model for stocks, ETFs and portfolios | `integrated` | The transparent factor-risk model and initial UI/attribution integration are merged. | Complete factor/industry/country/currency coverage, standard errors, ETF look-through reconciliation, robust as-of estimation and out-of-sample validation against public/simple baselines. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0111` — Implement robust covariance, volatility, correlation and tail-risk estimation | `integrated` | Multiple covariance/risk estimators and diagnostics are integrated. | Complete conditioning/sample/uncertainty reporting, downside/tail/liquidity risk, bootstrap/regime comparison, PSD properties and out-of-sample estimator selection. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0112` — Create canonical benchmarks, peer sets, cash proxies and reference portfolios | `planned` | Benchmark, cash and no-trade reference requirements are specified. | Implement total-return, currency-consistent broad/region/country/sector/factor/cash references, versioned constituents/methods and explicit unavailable behaviour. | `IMPLEMENT` |
| `ISSUE-0113` — Implement a constrained portfolio-optimiser suite with robust baselines | `implemented_initially` | An initial optimiser suite, constraints and solver handling exist. | Complete the declared method set, robust/naive baselines, feasibility/fallbacks, binding constraints, perturbation diagnostics and out-of-sample comparison. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0114` — Implement turnover-, cost-, tax-lot- and cash-aware rebalancing | `implemented_initially` | Initial cost/cash-aware rebalance proposal logic exists. | Add integer/fractional lots, settlement, minimum orders, broker restrictions, optional jurisdiction-labelled tax lots and full/partial/deferred/no-trade alternatives with accounting tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0115` — Build historical, hypothetical and reverse stress-testing engine | `integrated` | Historical/hypothetical stress and initial reverse-stress functionality are integrated. | Complete stock/ETF look-through, factor, FX, rates, credit, commodity, liquidity and cost propagation; reconcile contributions and test reverse thresholds and coverage. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0116` — Implement performance, risk, factor and decision attribution | `implemented_initially` | Initial performance and attribution calculations exist. | Complete time/money-weighted, instrument/factor/currency/cost/cash and model-human-execution attribution with ledger reconciliation, multi-currency and partial-coverage handling. | `AUDIT_AND_COMPLETE` |

### Phase 6 — Training, validation and model governance

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0117` — Implement the local training centre, experiment tracker and model registry | `implemented_initially` | An initial local training centre, run tracking and model registry exist. | Complete immutable data/code/environment traceability, governed states, crash/cancel/no-partial-publish behaviour, safe artefacts, offline replay and full model cards. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0118` — Create synthetic and adversarial market, data-quality and execution generators | `implemented_initially` | Initial seeded synthetic/adversarial generators exist. | Cover declared regimes, actions, revisions, conflicts and execution failures; prove invariants and exact seeds, and exclude synthetic results from promotion evidence. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0119` — Build a leakage-safe feature store and target/label registry | `implemented_initially` | Initial feature/target registry and point-in-time materialisation exist. | Complete feature delays/dependencies/missing policies, train-live parity, horizon/excess/drawdown targets, overlap/embargo metadata and leakage property tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0120` — Implement walk-forward, nested, purged and embargoed validation with multiple-testing control | `implemented_initially` | Initial leakage-safe validation and trial-accounting components exist. | Complete nested walk-forward selection, purging/embargo, untouched final tests, all-trial retention, effective-trial/DSR/PBO/FDR evidence, block-bootstrap uncertainty and cost-adjusted baselines. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0121` — Create a baseline and challenger model zoo for return, risk and fundamentals | `implemented_initially` | Initial baseline/challenger adapters, including optional foundation-model paths, exist. | Complete naive/linear/econometric/tree/quantile task coverage, conformance/licence/resource metadata and finance-specific out-of-sample comparisons; unavailable optional models must remain N/A. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0122` — Implement bounded hyperparameter optimisation, pruning and compute governance | `implemented_initially` | Initial bounded search, trial tracking and compute-control functionality exists. | Complete nested-only optimisation, final-test isolation, failed/pruned trial accounting, restart/cancellation, deterministic seeds and CPU/GPU/RAM/time quotas. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0123` — Implement probabilistic and conformal forecast calibration | `planned` | Calibration metrics, chronology and fallback requirements are specified. | Implement rolling/split conformal or eligible calibration by model/horizon/class/regime, minimum samples, interval diagnostics, drift and conservative widening/fallback. | `IMPLEMENT` |
| `ISSUE-0124` — Implement model monitoring, drift, champion/challenger and retirement governance | `planned` | Monitoring and promotion-state requirements are specified. | Implement feature/target/calibration/error/cost/subgroup drift, typed alerts, shadow challengers, promotion/demotion/rollback/retirement and prohibited-use model cards. | `IMPLEMENT` |

### Phase 7 — Backtest, paper trading and staged execution

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0125` — Implement a deterministic event-driven, order-level backtest engine | `implemented_initially` | An initial event-driven order-level engine and common contracts exist. | Complete session-valid event ordering, market/limit lifecycle, partial fills/cancellations/expiry, immutable replay, unsupported-data fail-closed behaviour and deterministic ledger-hash tests. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0126` — Implement point-in-time universes, delistings and survivorship-bias controls | `planned` | Universe, delisting and leakage requirements are specified. | Implement dated membership/listing status, delistings/successors/terminal returns or quantified gaps, frozen historical universes and matching peer/factor snapshots. | `IMPLEMENT` |
| `ISSUE-0127` — Create the double-entry portfolio, cash, FX, fee, tax and corporate-action ledger | `planned` | The double-entry schema and accounting invariants are specified. | Implement decimal-safe accounts, lots, cash, settlement, fees, income, withholding, actions and FX; derive positions/P&L by replay and reconcile imported broker statements. | `IMPLEMENT` |
| `ISSUE-0128` — Implement spread, slippage, market-impact, capacity and execution-cost models | `implemented_initially` | Initial fixed/spread/volume/volatility cost and capacity primitives exist. | Complete order/listing/session-size calibration, uncertainty-aware conservative fallbacks, stress, realised-fill comparison and exact cross-module use in returns, optimiser and paper/backtest. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0129` — Implement the full paper broker, frozen proposal ledger and forward evidence service | `integrated` | The paper broker, frozen proposals and forward-evidence service are integrated. | Complete restart/replay accounting, accepted/rejected/deferred outcome maturation, network isolation, full lifecycle E2E and attribution of performance, costs and incidents. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0130` — Implement the target-to-proposal policy and authority engine | `integrated` | The deterministic target-to-proposal and staged-authority engine is integrated. | Complete every freshness/confidence/event/liquidity/cost/concentration/account gate, alternatives and expiry, plus boundary/determinism/unauthorised-escalation tests across workflows. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0131` — Implement broker adapter contracts, read-only synchronisation and reconciliation | `planned` | Official-API/read-only adapter and credential requirements are specified. | Implement account/cash/position/order/fill/fee methods, read-only sync, stable external IDs, divergence classification, disconnect/correction handling and credential-safe mocks. | `IMPLEMENT` |
| `ISSUE-0132` — Implement independent pre-trade controls, kill switches and operational limits | `planned` | Independent hard-limit and kill-switch requirements are specified. | Implement account/strategy/global exposure, turnover, cash, loss/drawdown, stale/conflict/event/duplicate/market-state blocks using reconciled broker state, with tamper and drill tests. | `IMPLEMENT` |
| `ISSUE-0133` — Implement staged canary live execution with explicit promotion gates | `planned` | The disabled-by-default canary design and promotion constraints are specified. | Only after certification, implement manually confirmed draft orders and separately approved capped automation, restricted by strategy/instrument/account/order/value/frequency/window with automatic demotion. | `IMPLEMENT` |
| `ISSUE-0134` — Implement post-trade transaction-cost, execution-quality and decision attribution | `planned` | TCA benchmarks, decomposition and chronology rules are specified. | Implement decision/arrival/open/close/benchmark/realised prices, spread/delay/impact/FX/commission/opportunity attribution and forward-only cost-model calibration. | `IMPLEMENT` |
| `ISSUE-0135` — Implement incident management, recovery, reconciliation and operational drills | `planned` | Incident classes, fail-closed recovery and drill requirements are specified. | Implement tested runbooks, fault simulation, frozen/degraded modes, broker-ledger reconciliation, post-mortems and recurring paper/canary drills. | `IMPLEMENT` |

### Phase 8 — Typed local API and task-oriented frontend

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0136` — Create a typed local application API and page-view-model layer | `integrated` | Typed commands, queries and initial immutable page view models are integrated. | Migrate all pages and state-changing actions, enforce pagination/load/idempotency/concurrency/error contracts, and harden any optional localhost API authentication. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0137` — Deliver frontend v2 design system and task-oriented information architecture | `implemented_initially` | An initial design system and task-oriented frontend structure are implemented. | Complete all component states and final workspaces, migrate rather than duplicate existing pages, measure the Flet-versus-alternative decision and add visual/responsive/accessibility journeys. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0138` — Build professional research, comparison, charting and screening workspaces | `implemented_initially` | Initial comparison/research workspace, canonical local score views and some saved/export paths exist. | Reach equal stock/ETF depth with aligned units/currencies/horizons, linked charts, cross-filtering, virtualisation, saved versions, uncertainty/coverage and numerical export reconciliation. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0139` — Build portfolio, training, paper and live operations workspaces | `implemented_initially` | Initial portfolio/training/paper operations views and command progress patterns exist. | Complete risk/optimiser/rebalance/attribution, trial/promotion, proposal/order/fill/limit/reconciliation/incident/TCA workflows, with paper/live separation and recovery E2E. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0140` — Complete accessibility, global search, command palette, localisation and unit formatting | `implemented_initially` | Initial central formatting, accessibility and navigation/search components exist. | Complete WCAG 2.2-oriented keyboard/focus/screen-reader/reduced-motion/high-contrast support, permission-aware global search/command palette and locale/unit tests. | `AUDIT_AND_COMPLETE` |

### Phase 9 — Quality, release, security and resilience

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0141` — Implement hermetic CI, multi-platform build and release automation | `integrated` | CI/build/release automation foundations and machine-readable validation evidence are integrated. | Complete locked Windows/Linux matrices, full/property/integration/migration/offline/package tests, signed reproducible artefacts, clean-profile tests and protected promotion. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0142` — Add property, metamorphic, golden, differential and mutation testing | `planned` | Critical invariant and testing-layer requirements are specified. | Implement Hypothesis properties, independent golden cases, old/new differential tests, mutation thresholds for scoring/risk/accounting/controls and deterministic tolerance policy. | `IMPLEMENT` |
| `ISSUE-0143` — Add visual E2E, load, soak, fault-injection and chaos test programmes | `hardening_required` | Some visual/browser E2E and failure evidence exists, but known harness/coverage gaps remain. | Complete deterministic page objects/baselines, source and packaged critical journeys, large-universe/load/soak tests, leak budgets and provider/parser/disk/clock/network/broker fault injection. | `HARDEN_AND_CERTIFY` |
| `ISSUE-0144` — Harden secrets, parsers, local APIs, files and network access | `integrated` | Initial threat controls, parser/file/network restrictions and secret handling are integrated. | Complete threat-model coverage and malicious archive/XML/CSV/model, redaction, local-API auth/CSRF and network allow-list tests across every plugin and package path. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0145` — Implement software supply-chain, SBOM, vulnerability, signing and secure-update controls | `integrated` | Supply-chain scanning/SBOM/signing/update-control foundations are integrated. | Complete source/package SBOM completeness, pinned hashes, secret/licence/vulnerability gates, tampered/offline update tests, third-party notices and protected signing. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0146` — Implement encryption, privacy controls, backup and disaster recovery | `integrated` | Encryption/privacy/backup/recovery foundations are integrated. | Complete clean-machine restore, incremental consistency/retention, key loss/corruption, redaction/deletion/export, database corruption and disaster-drill acceptance. | `AUDIT_AND_COMPLETE` |

### Phase 10 — Audit, reproducibility, documentation and governance

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0147` — Deliver audit packet v3 and one-command deterministic reproduction | `planned` | The v3 packet scope, manifest and reproduction requirements are specified. | Implement complete source/data/formula/model/job/score/proposal/order/fill manifests, redaction/unavailable states, one-command offline rebuild, tamper checks and hash/tolerance comparison. | `IMPLEMENT` |
| `ISSUE-0148` — Complete developer, plugin, methodology, operations and user documentation | `planned` | The documentation inventory and clean-onboarding acceptance are specified. | Write and generate current architecture/API/data/methodology/provider/plugin/sector/ETF/validation/portfolio/execution docs and tested tutorials for setup, research, training, paper, backup and incidents. | `IMPLEMENT` |
| `ISSUE-0149` — Complete legal, data/model licence, terms, disclaimer and jurisdiction review | `hardening_required` | An initial terms/licence registry and wording review exist. | Resolve every mandatory source and model/code licence, permitted caching/redistribution/export, Yahoo/broker/fair-access terms, jurisdiction wording and terms-change disablement with professional review where required. | `HARDEN_AND_CERTIFY` |
| `ISSUE-0150` — Audit geographic, sector, size, listing and data-coverage bias | `implemented_initially` | Initial coverage/subgroup reporting and bias-control foundations exist. | Complete geography/sector/size/currency/listing coverage, subgroup error/calibration/selection, MNAR/survivorship/provider-bias monitoring and authority thresholds that prevent aggregate masking. | `AUDIT_AND_COMPLETE` |
| `ISSUE-0151` — Define hardware profiles, compute budgets and graceful degradation | `hardening_required` | Initial hardware profiles, benchmark/resource reporting and graceful-degradation controls exist. | Complete minimum/recommended/high-profile cross-platform benchmarks, CPU-only equivalence, low-memory/disk tests, model/batch choices, quotas/cleanup and pre-job requirement estimates. | `HARDEN_AND_CERTIFY` |

### Phase 11 — Final certification

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `ISSUE-0152` — Run final release certification and close the completion programme | `blocked` | The certification contract and blocking relationship are registered; certification has not run. | After every accepted issue is resolved, freeze a candidate and run clean-install/migration/offline/data/stock/ETF/training/backtest/paper/recovery/security/legal/reproduction gates, independent review and signed release evidence. | `BLOCKED_UNTIL_DEPENDENCIES` |

### Open UPDATEV2 records

| ID | Status | Verified/recorded existing evidence | Remaining implementation delta | Required disposition |
|---|---|---|---|---|
| `UPDATEV2-0011` — Symbol/ISIN/exchange identity resolver (original update ISSUE-0011) | `in_progress` | Partial symbol/ISIN/exchange resolution exists. | Absorb it into the identity master with entity/security/fund/share-class/listing separation, CIK/LEI/ISIN/MIC/ticker histories, corporate events, confidence and review. | `AUDIT_AND_COMPLETE` |
| `UPDATEV2-0012` — SEC EDGAR official statement importer (original update ISSUE-0012) | `implemented_initially` | The SEC importer is implemented and marked closure-pending. | Prefer official submissions/companyfacts bulk snapshots, retain raw filings/amendments and availability times, support resumable increments, clean first-run and canonical-statement integration. | `AUDIT_AND_COMPLETE` |
| `UPDATEV2-0014` — France DILA and Netherlands AFM OAM discovery adapters (original update ISSUE-0014) | `implemented_initially` | Initial French and Dutch official filing-discovery adapters exist. | Generalise them into a country/regulator plugin framework with snapshots, coverage, terms, retries, manual fallback and no prohibited scraping. | `AUDIT_AND_COMPLETE` |
| `UPDATEV2-0018` — ETF prospectus, annual and half-year report parser (original update ISSUE-0018) | `planned` | The disclosure registry dependency and bounded-parser approach are specified. | Implement versioned language/template parsers with page-level provenance, human verification and structured legal/holdings/lending/collateral/cost/risk extraction. | `IMPLEMENT` |
| `UPDATEV2-0020` — SFDR disclosure parser (original update ISSUE-0020) | `planned` | The dated, context-only sustainability-disclosure model is specified. | Implement Article/PAI/methodology parsing with page provenance, version conflicts and greenwashing warnings, never using labels as expected-return evidence. | `IMPLEMENT` |
| `UPDATEV2-0021` — Source conflict resolver and canonical metric selector (original update ISSUE-0021) | `in_progress` | Partial source-conflict handling and canonical selection exist. | Implement deterministic period/unit/currency/restatement-aware arbitration with all candidates retained, authority/tolerances, quarantine, human resolution and downstream invalidation. | `AUDIT_AND_COMPLETE` |
| `UPDATEV2-0023` — FMP optional provider adapter (original update ISSUE-0023) | `planned` | Its optional-only policy, quota/licence metadata and exclusion from mandatory completion are specified. | Implement only as a cached enrichment/verification plugin with explicit unavailable/quota states and no mandatory score or release authority. | `IMPLEMENT` |
| `UPDATEV2-0024` — Alpha Vantage verification/fallback adapter (original update ISSUE-0024) | `planned` | Its limited selected-ticker verification role is specified. | Implement explicit daily-budget enforcement, cache replay and quota-exhausted behaviour; never use it as a broad mandatory source. | `IMPLEMENT` |
| `UPDATEV2-0025` — Finnhub experimental adapter with entitlement probes (original update ISSUE-0025) | `planned` | Its disabled experimental status and authority restrictions are specified. | Implement capability/entitlement probes, terms and secret controls, explicit unavailable states and continued exclusion from mandatory scoring/release. | `IMPLEMENT` |
| `UPDATEV2-0026` — Candle feature/context/backtest module (original update ISSUE-0026) | `planned` | The low-authority, context-only role and overfitting concerns are specified. | Implement continuous OHLCV/gap/range features, bar-quality and path-ambiguity checks, score caps and realistic event/cost backtests rather than named-pattern authority. | `IMPLEMENT` |
| `UPDATEV2-0027` — UI workflow/button reliability and progress indicators (original update ISSUE-0027) | `in_progress` | Partial button reliability, immediate acknowledgement and progress handling exist. | Merge this work into the generated action inventory, typed API/view models and durable job DAG; cover training, paper and operations controls end to end. | `AUDIT_AND_COMPLETE` |
| `UPDATEV2-0029` — Rebuild/test/update discipline automation (original update ISSUE-0029) | `integrated` | Finish-check/rebuild/test/update automation is integrated. | Elevate it to protected hermetic CI with locks, closure manifests, signed artefacts, SBOM, issue-state convergence and protected release promotion. | `AUDIT_AND_COMPLETE` |
| `UPDATEV2-0030` — Optional OHLCV fallback providers: Stooq, Twelve Data and Tiingo (original update ISSUE-0030) | `planned` | The source split and optional/local-first policy are specified. | Implement Stooq only as a cached best-effort fallback where permitted, Twelve Data/Tiingo as keyed optional plugins, and user/broker files as the quota-independent fallback with conflict handling. | `IMPLEMENT` |


## 5. Adopted issue amendments and proposed new records

### 5.1 Amendment rule

Amend the existing canonical owner before creating a duplicate. Preserve existing acceptance criteria unless this specification explicitly supersedes or narrows them. Where one outcome is too large, create child implementation slices or PRs under the same canonical issue rather than a competing umbrella issue.

### 5.2 Proposed new issue index

The following IDs were free in the audited live repository and registry. They remain provisional until the Wave 0 collision check. Their complete contracts are in Annex A.

| Provisional ID | Outcome | Priority | Owner | Phase | Blocking dependencies |
|---|---|---|---|---|---|
| `ISSUE-0153` | Fixed-income instrument, terms and cash-flow identity master | `P0` | `data-platform` | Phase 2 | 0082, 0083, 0085, provider registry |
| `ISSUE-0154` | Fixed-income cash-flow, clean/dirty pricing and yield/risk analytics | `P0` | `returns-and-risk` | Phase 5 | 0153, 0085, 0088 |
| `ISSUE-0155` | Fixed-income reference, curve, trade and liquidity data adapters | `P0/P1` | `data-platform` | Phase 2 | 0076, 0081, 0088, 0149, 0153 |
| `ISSUE-0156` | Fixed-income rate, curve, spread, credit, liquidity and optionality risk | `P0/P1` | `returns-and-risk` | Phase 5 | 0154, 0155, 0091, 0111 |
| `ISSUE-0157` | Fixed-income expected total-return distributions, peers and screener | `P0/P1` | `returns-and-risk` | Phase 5 | 0098, 0108, 0109, 0112, 0120, 0123, 0154–0156 |
| `ISSUE-0158` | Bond detail, portfolio maturity ladder and fixed-income income views | `P1` | `frontend-and-api` | Phase 8 | 0136–0140, 0153–0157, 0161, 0162 |
| `ISSUE-0159` | Daily portfolio valuation history and standards-aligned performance | `P0` | `returns-and-risk` | Phase 5 | 0084, 0085, 0127 |
| `ISSUE-0160` | Selectable portfolio value, selected-currency P&L and performance charts | `P0/P1` | `frontend-and-api` | Phase 8 | 0139, 0159 |
| `ISSUE-0161` | Portfolio holdings analysis table and cross-surface drill-down | `P0/P1` | `frontend-and-api` | Phase 8 | 0074, 0127, 0138, 0139, 0159 |
| `ISSUE-0162` | Coverage-aware portfolio exposure, look-through and concentration charts | `P1` | `returns-and-risk` | Phase 5 | 0022, 0083, 0105, 0127, 0153 |
| `ISSUE-0163` | Portfolio income, event, maturity and liquidity calendar | `P1` | `frontend-and-api` | Phase 8 | 0024, 0084, 0127, 0153, 0158, 0161 |
| `ISSUE-0164` | Portfolio goals, constraints, alerts and pre-trade what-if analysis | `P1` | `programme-governance` | Phase 5 | 0113–0116, 0127, 0161–0163 |
| `ISSUE-0165` | Canonical resumable bulk analysis-run orchestrator | `P0` | `application-platform` | Phase 8 | 0018, 0020, 0074, 0077, 0081, 0126 |
| `ISSUE-0166` | Cross-asset top-N selection and portfolio-fit ranking | `P0/P1` | `returns-and-risk` | Phase 5 | 0020, 0108–0112, 0113, 0128, 0157, 0165 |
| `ISSUE-0167` | Settlement, buying-power, cash reservation and deterministic order state | `P0 before broker writes` | `trading-safety` | Phase 7 | 0085, 0114, 0127, 0130, 0131 |
| `ISSUE-0168` | Portfolio forecast aggregation and expected gain/loss scenarios | `P1` | `returns-and-risk` | Phase 5 | 0108–0111, 0115, 0127, 0161 |
| `ISSUE-0169` | Canonical analysis parity and deterministic replay across workflows | `P0` | `quality-and-release` | Phase 9 | 0074, 0136, 0142, 0161, 0165, 0167 |
| `ISSUE-0170` | Ordinary-fund vehicle, sub-fund, share-class, dealing and lifecycle identity | `P0` | `data-platform` | Phase 2 | 0076, 0082, 0083, 0085, 0149 |
| `ISSUE-0171` | Lawful free global ordinary-fund NAV, disclosure, holdings and fee adapters | `P0` | `data-platform` | Phase 2 | 0076, 0080, 0081, 0149, 0170, 0176 |
| `ISSUE-0172` | Ordinary-fund analysis, peers, forecasts, recommendations and top-N | `P0` | `etf-and-fund-research` | Phase 4 | 0074, 0098, 0105, 0108–0109, 0112, 0120, 0123, 0128, 0170–0175 |
| `ISSUE-0173` | User-selected output currency and point-in-time FX across every workflow | `P0` | `returns-and-risk` | Phase 5 | 0076, 0084, 0088, 0089, 0149, 0176 |
| `ISSUE-0174` | Five preset-but-editable risk profiles anchored to a dynamic VWCE envelope | `P0` | `programme-governance` | Phase 5 | 0074, 0108–0112, 0123, 0128, 0173 |
| `ISSUE-0175` | Quick, Medium, High and Full analysis-depth profiles with measured SLOs | `P0` | `application-platform` | Phase 8 | 0039, 0077, 0078, 0121, 0151, 0165 |
| `ISSUE-0176` | Secure Data Providers & API Keys settings centre | `P0` | `security-and-release` | Phase 9 | 0037, 0076, 0080, 0144–0146, 0149 |

### 5.3 Required release overlays on existing owners

The detailed amendments in Annex A are normative. In particular, update owners for product scope/authority, settings, the canonical analysis snapshot, identity/classification, point-in-time actions/FX, peers, benchmarks, forecasts, uncertainty/calibration, model governance, bulk runs/top-N, funds, portfolio ledger/performance, UI, security, legal/coverage, parity and final certification. Do not create replacement issues for these amendments.

## 6. Dependency-aware implementation roadmap

### 6.1 Batch selection rule

Select the largest coherent, independently verifiable slice—not the largest ticket count. A batch must have dependency closure, a single observable outcome, frozen shared contracts, one writer per file/symbol/schema/contract at a time, an explicit validation boundary and an understandable rollback. Use 2–8 issues for normal slices; split high-risk migrations/security/concurrency into 1–3 issue slices. Large mechanical batches are allowed only with a uniform rule and deterministic validation.

### 6.2 Standard waves within every batch

- **Wave 0:** fresh snapshot, instruction load, readiness/no-change gate and batch plan.
- **Wave 1:** read-only mapping, reproduction and evidence collection.
- **Wave 2:** behavioural/contract tests and shared decisions.
- **Wave 3:** schemas, migrations, interfaces and providers.
- **Wave 4:** disjoint downstream implementation lanes.
- **Wave 5:** targeted integration and causal failure triage.
- **Wave 6:** central full validation and independent review.
- **Wave 7:** logical commits, traceability, local/remote status convergence and authorised merge.

### 6.3 Programme batches and release milestones

| Batch | Coherent outcome | Primary issues/work | Parallelism and exit gate |
|---|---|---|---|
| `B00-CONTROL` | Fresh, truthful programme control plane | Registry/readiness corrections; 0070; issue 0153–0176 intake; plan/README/ledgers; validator/report schema; GitHub dry-run | One contract owner; read-only audits may run in parallel. Exit: generated artefacts fresh, graph valid, remote plan convergent. |
| `B01-POLICY` | Core scope, settings, lawful provider access and secrets | 0008, 0037, 0080, 0149, 0176; authority/capability/certification lanes | Security/terms reviewed independently. Exit: no-key safe startup, credentials redacted, execution false. |
| `B02-DATA-IDENTITY` | Canonical identity, clocks, actions, FX and data-quality spine | 0082–0089, 0170, 0171, 0173; UPDATEV2 identity/source-conflict owners | Contract-first; provider children only after schemas. Exit: PIT identity/action/FX fixtures and coverage reports pass. |
| `B03-FIXED-INCOME` | Supported bond terms, deterministic analytics, data and risk | 0153–0156, associated 0110/0111 interfaces | Terms/pricing one critical writer; adapters disjoint after contract. Exit: differential/golden analytics and unsupported-structure blocks pass. |
| `B04-ANALYSIS-SPINE` | One multi-asset analysis/forecast/peer/benchmark/profile contract | 0074, 0098–0109 as applicable, 0112, 0123, 0157, 0172, 0174 | Freeze `AnalysisSnapshot`, metric, forecast and error contracts before consumers. Exit: stock/ETF/fund/bond golden analyses and profile invariance pass. |
| `B05-MODEL-EVIDENCE` | Leakage-safe, calibrated, governed model evidence | 0057, 0117, 0119–0124, 0150 | Training/validation lanes can parallelise by task after target/fold freeze. Exit: all-attempt ledger, outer-test isolation, calibration and rollback pass. |
| `B06-BULK-SELECTION` | Resumable 3,000+ instrument analysis and multidimensional top-N | 0018, 0020, 0081, 0126, 0165, 0166, 0175 | Ingestion/orchestration/selection lanes split by ownership. Exit: crash/resume, slice conservation, depth parity and measured SLO evidence pass. |
| `B07-RESEARCH-UX` | Primary Analyse/Compare/Screener/Bulk experience with complete control reliability | 0011–0017 as relevant, 0136–0140, 0169, UI inventory overlay | UI pages may be parallel by route after typed view models freeze. Exit: every route/control/state passes source and packaged journeys. |
| `B08-PORTFOLIO` | Ledger-derived read-only portfolio intelligence | 0021/0022, 0113–0116, 0127, 0158–0164, 0168 | Ledger/performance contracts serial first; UI/exposure/income lanes then parallel. Exit: balance, flow neutrality, reconciliation, charts and coverage pass. |
| `B09-PAPER-BROKER` | Deterministic paper/read-only broker lifecycle and independent controls | 0125, 0128–0132, 0167, 0134–0135 | Order/cash state one critical writer; adapters/review tests isolated. Exit: restart/replay, idempotency, reservation, controls, reconciliation and drills pass. |
| `B10-CANARY-SCAFFOLD` | Disabled, bounded live-canary contracts only | 0133 plus activation dependencies | Serial high-risk lane with independent Sol review. Exit: all bypass tests pass and live authority remains disabled. |
| `B11-QUALITY-DOCS` | Release-quality, security, recovery, documentation and audit packet | 0141–0148, 0150–0151, UPDATEV2-0029 | Security/docs/test agents can parallelise read-heavy work; root integrates. Exit: package, SBOM/signing, restore, legal, audit replay and docs drift pass. |
| `B12-REFACTOR` | One clean, bounded architecture with no hidden duplicate paths | 0071–0078 residual hardening plus cross-cutting cleanup | One architecture owner; subsystem writers disjoint. Exit: parity, boundary, mutation, performance and full regression pass. |
| `B13-CERTIFY` | Frozen release candidate and capability-specific signed evidence | 0152 and all T01–T55 gates | Central-only; independent reviewers read-only. Exit: all selected capabilities certified; zero unresolved P0/P1 defects or unexplained discrepancies. |

Do not run `B08`–`B10` ahead of shared P0 contracts merely to show activity. Conversely, a broker/legal blocker that is isolated from P0 MUST NOT prevent certification of a safe core-research lane.

## 7. Whole-application UI, error and workflow acceptance

### 7.1 Inventory scope

The acceptance inventory covers every registered route, navigation item, button, icon button, text/dropdown/select field that triggers behaviour, submit/change/select event, context/menu action, command-palette item, dynamic row action, expandable panel, file picker, dialog/subwindow action, keyboard shortcut, cancellation/retry control, export/download and authority-sensitive operation.

### 7.2 Required state matrix per control/workflow

Each applicable control must be tested in: initial/loading; empty; success; partial; unavailable optional dependency; invalid input; stale/conflicted data; permission/authority denied; duplicate invocation; cancellation; retry; restart/reopen; persistence conflict; provider/network failure; disk/resource pressure; and packaged mode. A deliberately disabled control must explain why and link to the blocking capability; it is not a broken control.

### 7.3 Runtime expectations

- Visible acknowledgement within 1 second and durable workflow creation within 2 seconds for long work.
- Exactly one active workflow for a deduplicated command unless parallelism is explicitly supported.
- Cancellation is cooperative, durable and visible; cancelled work cannot publish partial canonical results.
- Errors are typed, redacted, actionable and routed to Errors & Recovery/Diagnostics with a stable fingerprint.
- Page reload/restart reconstructs state from durable records, not transient widget memory.
- No modal/subwindow becomes unreachable, uncloseable, off-screen or keyboard-inaccessible.
- Source/package outputs and audit exports reconcile to the same IDs and values.

### 7.4 UI release evidence

Generate a machine-readable action report containing route, control key, command/query, fixture, state exercised, expected signal, actual signal, audit event, screenshots where meaningful, source/package result, duration and evidence path. The final report has zero untested visible actions and zero unexplained console/log errors.

## 8. Performance, resource and reliability protocol

### 8.1 Measurement method

For every budgeted path record environment, CPU/GPU/RAM/storage, OS, Python/build, data/fixture hash, cache state, warm-up, repetitions, p50, p95, peak memory, I/O, provider wait and correctness hash. Do not accept one anecdotal run. Use at least 20 measured repetitions for micro/interactive budgets where practical; use enough repeated end-to-end runs to estimate a stable p95 and document the count.

### 8.2 Regression policy

The existing 10% tolerance is a ceiling, not an automatic permission. Investigate a statistically or operationally meaningful regression even if inside tolerance. A performance improvement is rejected if it changes numerical results, ordering, evidence lineage, security, accessibility or failure semantics.

### 8.3 Reliability

Long jobs use checkpoints, idempotent stages, bounded retries, leases, cancellation and atomic publication. Test process kill, app restart, stale lease, partial file, provider 429/5xx, disk-full, corrupted cache, clock/timezone edge, optional model absence and package restart. Preserve last-known-good generations and explicit degraded state.

## 9. Refactoring and code-quality completion contract

Refactoring is release work only when it reduces a measured risk or removes a duplicate path while preserving behaviour. Do not perform aesthetic rewrites. The final refactor report must include:

- dependency/import graph before and after;
- canonical calculation and state-owner map;
- removed duplicate/dead paths and the tests proving they were unused or equivalent;
- schema/API migration and rollback notes;
- complexity/hotspot changes for materially affected modules;
- performance and memory comparison;
- full parity/regression results;
- residual technical debt, each linked to an explicitly non-release issue or accepted limitation.

## 10. Validation ladder and exact canonical commands

Workers run the narrowest meaningful checks. The root centralises expensive suites.

### Level 0 — snapshot, reproduction and no-change

```bash
git fetch --all --prune
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

### Level 1 — syntax, generated consistency and focused quality

```bash
python -m compileall -q src scripts
python -m ruff check <changed Python paths>
python scripts/validate_issue_registry.py
python scripts/update_programme_status.py --check
python scripts/validate_app.py --changed
```

### Level 2–4 — issue/module/integration

```bash
python -m pytest -q <focused test paths>
python scripts/validate_app.py --issue <ISSUE-ID>
python scripts/validate_app.py --phase <phase-id>
```

### Level 5 — complete source suite

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m compileall -q src scripts
python scripts/validate_app.py --full
python scripts/validate_app.py --offline
```

`--full` and `--offline` are required implementation outputs if not yet present at the fresh base.

### Level 6 — package, security, performance and release

```bash
python scripts/validate_app.py --packaged
python scripts/release_gate.py --root . --output artifacts/release/latest
```

Use the repository’s Windows package command and protected GitHub workflow. Do not substitute a source smoke for a packaged launch. The release gate must include tests, package build/smoke, performance, source policy, cache, security, privacy/backup, legal terms, SBOM and signature, plus the new parity/UI/capability gates.

### Level 7–8 — independent and prospective evidence

Independent Sol review is mandatory for financial calculations, migrations, concurrency, security/privacy, broker/order state, broad refactors and final certification. Analytical promotion additionally requires the issue-defined untouched/prospective evidence; a passing software test does not prove investment efficacy.

### Flake policy

Run once. Retry once only for a named, documented flake, preserving both results and environment/seed. A newly intermittent test is a failure finding. Never rerun until green without diagnosis.

## 11. Documentation, Git, PR and GitHub completion workflow

### 11.1 Branch/worktree policy

- Start every implementation slice from the latest merged `origin/main` in a fresh worktree/branch named `implementation/<batch>-<purpose>` or the repository’s established equivalent.
- One architectural purpose per PR; normally 2–8 coherent issues, fewer for high risk.
- Parallel writers use isolated worktrees and disjoint ownership. One writer owns a file/symbol/schema/contract at a time.
- Workers may commit locally when assigned; only the root integrates, rebases, pushes and merges.
- Commits are logical and reversible: tests/contracts → schema/interfaces → providers/core → consumers/UI → migrations → observability/docs/generated artefacts.

### 11.2 Per-PR evidence

PR body includes base SHA, issue and acceptance IDs, completed/remaining delta, changed files/symbols, migrations, exact commands/results, UI evidence, performance before/after, security/authority statement, docs/generated changes, rollback and residual risk. The root inspects production and test diffs and confirms no test weakening or unowned change.

### 11.3 Status convergence after each merge

1. Merge only after targeted/integration checks and independent review where required.
2. Fetch the new `origin/main`; run quick validation in a clean worktree.
3. Update issue status/evidence, registry, generated status/roadmap, plan, README/docs and traceability.
4. Generate/review/apply the managed GitHub sync plan and verify no-op readback.
5. Recompute the dependency graph and select the next batch.

Do not wait until the end to repair stale plans or issue bodies.

### 11.4 Final GitHub/release-page state

At certification, the GitHub repository must show an accurate README, current roadmap/status, open issues for genuine remaining/deferred/blocked work, closed issues with evidence, merged PR traceability, current changelog/release notes, and the signed capability certification artefacts. Publishing a GitHub Release or tag requires separate explicit authorisation; prepare the draft and evidence but do not publish automatically.

## 12. GPT-5.6 Codex orchestration contract

### 12.1 Root role

Use GPT-5.6 Sol at `high` reasoning as the continuous control plane. Escalate the root or a bounded critical worker to `xhigh`/`max` only for unresolved high-risk architecture, security, migration, concurrency, financial correctness or final synthesis. The root owns snapshot, readiness, batch selection, graph/conflict analysis, shared contracts, delegation, integration, full validation, review resolution, commits, GitHub synchronisation and final reporting.

### 12.2 Worker routing

- **Terra-medium:** read-only mapping, repository/evidence inventory and routine documentation checks.
- **Terra-high:** normal implementation, regression tests, reproduction and causal failure triage.
- **Sol-high/xhigh:** security, persistent migrations, concurrency, financial calculations, public contracts, hard integration failures and independent review.
- **Luna-high:** only exact repetitive low-risk transformations with a before/after rule, canonical example, enumerated write set and deterministic validation.

Use at most six open threads globally and normally two to four writers. This repository’s closer project `AGENTS.md` may impose a lower cap; obey it. Delegation depth is one. Children never delegate.

### 12.3 Ownership and contract freeze

Before write fan-out, freeze affected API/schema/state/error/migration contracts with typed definitions and contract tests. Build both the dependency/affinity graph and the write/resource-conflict graph. Parallelise read-heavy work freely; parallelise writes only with disjoint files/symbols/contracts and isolated worktrees.

### 12.4 Worker assignment

Every worker receives one observable objective, issue/AC IDs, fresh base/worktree, owned and forbidden paths/symbols, frozen inputs/contracts, exact validation, stop conditions and this report schema:

```yaml
status: PASS | NO_CHANGE | BLOCKED | REVISE
batch_id: <id>
issue_ids: [<ids>]
acceptance_criteria: [<ids>]
summary: <observable outcome>
verified_facts: [<fact and evidence>]
assumptions: [<assumption>]
files_changed: [<path/symbol and purpose>]
tests_added_or_changed: [<path and behaviour>]
commands_and_results:
  - command: <exact command>
    result: <pass/fail and evidence path>
acceptance_evidence:
  - criterion: <AC-ID>
    evidence: <test/result/path>
commit: <sha or none>
residual_risks: [<risk>]
blockers: [<blocker>]
confidence: low | medium | high
```

### 12.5 Repair-loop control

Classify each failure before editing: assigned defect, cross-lane contract mismatch, test/fixture defect, pre-existing failure, environment/flake, product ambiguity, integration order or high-risk security/concurrency/migration. Return one bounded correction to the owning lane. After two attempts without improved causal evidence, stop that lane, re-plan or escalate; do not churn unrelated code.

## 13. Final certification and closure

### 13.1 Freeze

Create a release-candidate branch/worktree from current `origin/main`. Freeze source, dependency locks, data fixtures/snapshots, formula/feature/model/policy versions, capability matrix, provider/terms state, supported universe and expected artefact hashes. No feature work enters the candidate after freeze except reviewed release-blocking fixes followed by complete revalidation.

### 13.2 Mandatory final gates

- All adopted open/partial issues attempted and truthfully classified; no non-blocked release record remains merely planned.
- All T01–T55 acceptance tests in Annex A pass with retained evidence.
- Full source suite, Ruff, compileall, offline, package, source/package differential, UI/action inventory, accessibility, performance, security, privacy/backup/restore, legal/terms, SBOM/signature, audit replay and deterministic reproduction pass.
- Representative stock, ETF, ordinary fund, bond, bulk/top-N, selected-currency, profile/depth, portfolio, backtest, paper and disabled-authority journeys pass.
- Zero unresolved P0/P1 defects, unexplained numerical discrepancies, secret leaks, unowned changes or material independent-review findings.
- README, plan, ledgers, issue registry/status/roadmap, docs, changelog, GitHub issues/PRs and release-readiness UI agree.
- `execution_allowed=false` and all live activation gates remain unchanged.

### 13.3 Closure evidence

Produce a signed capability matrix, validation report, parity report, UI action report, performance report, security/privacy/legal reports, SBOM, audit packet, source/package manifests, restore/recovery evidence, issue→AC→file/test→commit/PR traceability, accepted limitations and rollback package. An issue closes only when its complete contract is evidenced; a capability badge reflects certification, not implementation status.

## 14. Research/evidence limitations for implementation decisions

The orchestration recommendations are evidence-informed, not proven optimal for this repository. Official OpenAI documentation is high authority for current Codex/model behaviour but vendor-reported prompt-efficiency effects lack full public uncertainty and independent replication. Multi-agent/software-engineering studies in the supplied research are heterogeneous, often preprints, benchmark-dependent and not GPT-5.6/repository-specific. Therefore:

- use the proposed routing/concurrency as a prior;
- measure pass rate, elapsed time, tokens, conflicts and review findings on real batches;
- reduce agent count when coordination dominates;
- retain a single-agent path where delegation adds no independent value;
- record all attempts and failures rather than selecting only successful runs.

## 15. Root execution checklist

- [ ] Fresh base/worktree/instruction/source snapshot recorded.
- [ ] Registry/readiness/phase/count hard-coding corrected.
- [ ] Proposed IDs collision-checked and complete amendments/new records adopted.
- [ ] Batch plan created with graphs, contracts, ownership, tests and rollback.
- [ ] Behavioural tests fail for the intended reason before fixes where applicable.
- [ ] Implementation, UI, audit/export, docs and migrations delivered together.
- [ ] Worker reports ingested; all diffs and test changes reviewed.
- [ ] Targeted, integration, full, offline and packaged validation passed.
- [ ] UI action inventory has zero untested controls and no silent no-ops.
- [ ] Performance budgets and depth SLO evidence passed or truthfully failed certification.
- [ ] Final refactor removed duplicate/dead paths without semantic drift.
- [ ] Independent material findings resolved.
- [ ] Logical commits/PRs merged by root; post-merge validation passed.
- [ ] Local plans/README/ledgers/status/docs and GitHub issues converged.
- [ ] Capability-specific final certification signed; live execution remains disabled.

---

# Annex A — Complete consolidated product and issue contract

The following consolidated specification is incorporated as normative detail. Where its repository snapshot is older than the freshly fetched base, apply the current-state/no-change gate and the live reconciliation above. Where it conflicts with Sections 0–15, Sections 0–15 control because they contain the later repository audit and tightened release instructions. The source document’s duplicate Part XVI launch prompt is intentionally omitted; the separate `prompt.md` is the only launch prompt.


### Navigation

- [0. Use rules](#0-how-codex-and-programme-governance-must-use-this-document)
- [1. Product definition](#1-executive-product-definition)
- [2. Repository reconciliation](#2-repository-reconciliation-and-deduplication)
- [3. Calculation semantics](#3-product-wide-calculation-semantics)
- [4. Asset capability matrix](#4-supported-asset-capability-matrix)
- [5. Architecture and portfolio visualisation](#5-target-architecture)
- [6. Bulk workflow](#6-bulk-import-and-top-n-workflow)
- [7. Trading-bot model](#7-trading-bot-operating-model)
- [8. Research synthesis](#8-research-synthesis-and-evidence-quality)
- [9. User-priority decision contract and remaining gaps](#9-user-priority-decision-contract-and-remaining-gap-reconciliation)
- [Part VII — Existing-issue amendments](#part-vii--amend-existing-canonical-issues)
- [Part VIII — New issues](#part-viii--proposed-new-canonical-issues)
- [Part IX — Sequence](#part-ix--dependency-and-implementation-sequence)
- [Part X — Acceptance matrix](#part-x--shared-release-blocking-acceptance-matrix)
- [Part XI — Data contracts](#part-xi--core-data-contracts)
- [Part XII — Maturity grading](#part-xii--purpose-fit-grading-and-evidence-maturity)
- [Part XIII — Scrap/defer/quarantine](#part-xiii--explicit-scrap-defer-and-quarantine-list)
- [Part XIV — LLM audit boundary](#part-xiv--chatgpt-and-llm-audit-layer)
- [Part XV — Sources](#part-xv--primary-source-and-artefact-register)
- [Part XVI — Final Codex instruction](#part-xvi--final-codex-implementation-instruction)

> The application is primarily a private, local decision-support and screening system. It cannot promise an investment profit. Every expected gain or loss is a calibrated total-return distribution at one of the exact supported horizons, expressed in the user-selected output currency with uncertainty, evidence quality, FX, costs and limitations—not an exact future price. Portfolio and execution capabilities are separate, later certification lanes.

### 0. How Codex and programme governance must use this document

1. **Repository evidence overrides conversational memory.** Before editing, re-read the current issue registry, owning issue, dependencies, source, tests and latest merged state.
2. **Amend before duplicating.** Where an existing issue already owns a domain, apply the amendment in Part VII. Create a Part VIII issue only where the capability is genuinely absent.
3. **One issue, one coherent release slice.** A normal issue owns one domain contract, one workflow and its user-visible surface. Provider-by-provider work should be child issues, not one huge PR.
4. **No backend-only closure.** Every user-facing capability requires code, tests, UI, audit/export, documentation, rebuilt application and user-perspective smoke evidence.
5. **All numerical thresholds are versioned policy inputs.** Values in this document are provisional engineering defaults unless an authoritative standard defines them.
6. **No silent substitution or invented data.** Missing, stale, conflicted or unsupported evidence remains explicit as `N/A`, blocked or manual review.
7. **Execution remains disabled by default.** Planning or implementing the bot path does not itself authorise live orders.
8. **No proprietary or unverified leaked code.** Authenticated incidents may inform controls; grey-source claims cannot become an implementation dependency.
9. **Use the same canonical analysis everywhere.** Instrument detail, bulk runs, screener, portfolio, backtest, paper and proposals may format results differently but may not recalculate them through hidden alternative paths.
10. **Keep deterministic authority above models.** Models forecast; deterministic evidence, risk, portfolio, cost, compliance and execution gates decide whether an advisory action or order proposal can exist.

### 1. Executive product definition

The completed application contains four connected products using one canonical data, evidence and calculation spine. They do **not** have equal release priority.

#### 1.0 User-specific release priorities

1. **P0 — Individual analyser and top-*N* screening:** stocks, ETFs, ordinary mutual/index funds and supported bonds; exact horizons of 1 week, 1 month, 3 months, 6 months, 9 months, 2 years and 5 years; selected-currency output; peer-valid component scoring; five editable risk profiles; and Quick/Medium/High/Full analysis depth.
2. **P1 — Read-only portfolio intelligence:** useful context, holdings drill-down and what-if analysis, but it must not delay certification of a safe research/screening release.
3. **P2 — Paper and broker workflows:** only after the P0 foundation is complete, calibrated, replayable and prospectively monitored. Live authority stays disabled by default and is never part of the first core release.

Core research certification, portfolio certification and execution certification are independent. A blocked broker issue may not prevent a safe read-only analyser release; a successful analyser release may not imply any broker authority.

#### 1.1 Instrument analyser

For a selected stock, ETF, ordinary mutual/index fund, bond or other explicitly supported instrument, show:

- canonical identity, entity/fund/sub-fund/share-class/security/listing lineage and trading or dealing venue;
- asset type, sector/industry, fund category or fixed-income classification, country/regulatory context and all relevant currencies;
- source, point-in-time, freshness, conflict and coverage status;
- transparent factor, fundamental, structure, risk and friction components;
- the exact raw metric, applicability state, economically valid peer cohort, robust percentile, effective sample, fallback path and source lineage;
- a forecasted **total-return distribution** for exactly `1W`, `1M`, `3M`, `6M`, `9M`, `2Y` or `5Y`, when that asset and data frequency support the horizon;
- cumulative expected gain/loss in percentage and, when an amount is supplied, in the selected output currency; for `2Y` and `5Y`, also show annualised return ranges;
- probability of loss, probability of beating the matching cash return, probability of beating the asset-specific benchmark and probability of beating the canonical VWCE anchor where meaningful;
- local-asset return, FX contribution, selected-currency return and hedging state;
- low/base/high transaction-cost, FX and liquidity assumptions where relevant; tax calculation/advice is not a core capability;
- uncertainty decomposition, calibration, realised coverage, effective independent decisions and historical/prospective forecast outcomes;
- the selected `Quick`, `Medium`, `High` or `Full` analysis-depth profile and any omitted optional evidence;
- profile-specific eligibility and ranking for `Safe`, `Safe–Medium`, `Medium`, `Medium–Aggressive` and `Aggressive`, without changing the underlying raw analysis;
- feature drivers, contradictions, source citations and limitations;
- a long-only advisory result such as `buy_candidate`/`add_candidate`, `hold`, `avoid`/`no_trade`, `trim_candidate`/`sell_candidate` or `manual_review`.

The analyser must never replace a missing asset-specific metric with a superficially similar metric. A European bank’s P/E, for example, is assessed against an economically valid bank cohort—not against US technology companies. VWCE and cash are final opportunity benchmarks; they are not substitutes for peer normalisation. Unsupported funds, debt structures, derivatives or data states are rejected or research-only rather than passed into an equity fallback.

#### 1.2 Bulk universe analyser and top-*N* selector

The user can paste or import hundreds or thousands of identifiers, select a maintained universe, or combine both. A resumable run:

1. resolves identities and duplicates;
2. records unsupported and ambiguous rows;
3. freezes the universe, data cut-off, provider, feature, model and policy versions;
4. executes the **same analyser contract** used by a single-instrument page;
5. persists every eligible, blocked, unavailable and failed result;
6. ranks eligible instruments inside valid asset-specific peer groups;
7. applies the selected output currency, exact horizon, risk-profile policy and analysis-depth profile;
8. produces separate stock, ETF, ordinary-fund and bond rankings;
9. materialises configurable top-*N* views for the total asset class, sector, country, country×sector, risk profile and horizon, subject to minimum support;
10. optionally performs a cross-asset portfolio-fit selection through a declared risk/cost/constraint utility;
11. returns the exclusion funnel, confidence, rank/selection stability and a reproducible export.

Raw stock, ETF, fund and bond component scores must not be pooled into one opaque ranking. Cross-asset selection can compare only common probabilistic return, risk, liquidity, cost, evidence, FX and marginal-portfolio fields under a visible policy. Every grouped top-*N* view records its group definition, denominator, effective sample and fallback or unavailable state.

#### 1.3 Portfolio cockpit

The user can import or enter actual accounts, cash, transactions and positions. The portfolio workspace supplies:

- total market value in the user-selected output currency and local currency;
- net invested capital;
- realised and unrealised P&L;
- investment P&L in the selected output currency excluding external deposits and withdrawals;
- time-weighted return (TWR), neutralising the timing of external cash flows;
- money-weighted return (MWR/XIRR), showing the user’s capital-timing experience;
- benchmark and cash comparison;
- selectable-period line charts and quarterly/yearly bars;
- direct, look-through and combined exposure views with mapped coverage;
- holdings using the exact same analysis snapshot, score, forecast and advisory contracts as the analyser and screener;
- expected portfolio and holding gain/loss distributions;
- drawdown, volatility, factor, overlap, concentration, liquidity and scenario diagnostics;
- dividend, coupon, income, maturity and event projections;
- target allocation, drift, what-if and cost-aware rebalance proposals;
- multiple accounts/brokers, reconciliation state and source quality.

#### 1.4 Staged trading bot

The application exposes a governed mode ladder:

```text
OFF / research-only
→ PAPER
→ READ_ONLY_BROKER
→ DRAFT_ORDERS_WITH_APPROVAL
→ SUPERVISED_LIVE_CANARY
→ BOUNDED_AUTOMATIC
```

Each transition is certified independently by broker, account, asset class, strategy, venue and horizon. Models and LLMs never submit orders directly. The deterministic target-to-proposal policy, independent pre-trade controls, cash/settlement service, broker reconciliation, kill switches and explicit authority state decide whether an order can be submitted.

### 2. Repository reconciliation and deduplication

#### 2.1 Current programme status

The live status artefact reviewed on 21 July 2026 records:

| Programme state | Count |
|---|---:|
| Closed | 4 |
| Integrated | 32 |
| Implemented initially | 59 |
| In progress | 9 |
| Planned | 48 |
| Hardening required | 4 |
| Research only | 2 |
| Blocked | 1 |

It also records `execution_allowed: false`. The historical `issues/closed.md` index contains more completed/reconciled records because the programme distinguishes historical closure evidence, package records and current completion-programme states. Consequently, this specification never equates “merged”, “integrated” or “implemented initially” with canonical issue closure.

#### 2.2 Existing foundations that must be reused

The repository and supplied archive already contain or plan most of the following:

- local-first architecture and explicit unavailable/null states;
- provider registry, source authority and conflict handling;
- bitemporal/point-in-time data and historical-universe controls;
- identity, classification, peer, benchmark and sector-adapter programmes;
- ESEF/iXBRL, ETF documents, holdings, PRIIPs and index-methodology infrastructure;
- score history, feature drivers, evidence ledgers and audit packets;
- screener, portfolio sandbox, ETF overlap, optimiser, attribution and scenario scaffolds;
- Training Centre, feature/target store, nested validation, model zoo, HPO, calibration and monitoring scaffolds;
- event-driven backtest, execution-cost and paper-broker scaffolds;
- target-to-proposal policy, broker read-only reconciliation, independent controls, canary execution, TCA and incident issues;
- frontend/API, packaging, release, security, audit and final-certification programmes.

#### 2.3 Genuinely missing or insufficiently specified

The prior specification identified the fixed-income, portfolio, bulk and parity gaps. The user-priority reconciliation adds the following unresolved release blockers:

1. A canonical fixed-income instrument, pricing, risk, forecast and UI issue family.
2. First-class ordinary mutual/index-fund identity, NAV/dealing terms, documents, holdings, costs, peer analytics, forecast and screener support.
3. Exact portfolio performance semantics for external flows, TWR, MWR, selected-currency P&L and period bars.
4. A durable daily portfolio valuation/performance store derived from the double-entry ledger.
5. An enforceable parity contract proving detail, bulk, screener, portfolio and later execution workflows use the same sealed analysis snapshot.
6. A complete user-facing bulk-run orchestration contract for thousands of instruments.
7. Separate asset-class top-*N* plus total, sector, country, country×sector, risk-profile and horizon slices with minimum-support rules.
8. A cross-asset top-*N* policy that does not compare incomparable raw scores.
9. An explicit score-layer contract separating raw facts, metric applicability, peer-relative components, asset-specific evidence, common forecast outputs and VWCE/cash-relative opportunity.
10. The exact horizon ladder `1W`, `1M`, `3M`, `6M`, `9M`, `2Y`, `5Y`, including annualised and cumulative long-horizon outputs.
11. A long-horizon training/validation contract that distinguishes historical label construction, local training wall time and prospective calendar maturity.
12. Five preset-but-editable risk profiles, with `Medium` anchored to a versioned VWCE risk/upside envelope rather than a hard-coded regulatory label.
13. A user-selected output-currency and point-in-time FX service that covers analysis, ranking, forecasts, charts and exports.
14. Correct handling of fund base currency, share-class currency, trading/dealing currency, hedged share classes and economic currency exposure.
15. Separate `Quick`, `Medium`, `High` and `Full` analysis-depth profiles with measured runtime service-level objectives, identical safety gates and no silent downgrade.
16. Separation of cold data acquisition, warm-cache refresh, model inference, calibration and optional model training in timing evidence.
17. A secure provider/API-key centre with required/optional key state, bounded probes, rate limits, quota state, terms and secret redaction.
18. A lawful free-data coverage strategy that accepts explicit regional gaps instead of promising complete global fundamentals, fund holdings or bond trades.
19. Fund survivorship, merger, liquidation, incubation, share-class duplication and manager/strategy-change controls.
20. A complete recommendation-efficacy programme measuring calibration, ranking quality and net VWCE/cash outperformance on untouched and prospective data.
21. A private self-research/guest-analysis boundary that avoids unlicensed personal-suitability conclusions when the user checks an investment for somebody else.
22. Explicit long-only semantics and global exclusion of penny/OTC, highly illiquid microcaps, leveraged/inverse products, derivatives, leverage, shorting, crypto and complex structures from the normal path.
23. Removal of tax advice and tax optimisation from the core product; only imported/accounting tax amounts remain optional bookkeeping fields.
24. Capability-specific certification so portfolio or broker blockers do not hold back a safe analyser/screener release and analyser completion cannot enable trading.
25. Settlement, cash reservation and buying-power accounting between proposals and broker submission.
26. Complete portfolio income/maturity/event, goals/alerts and what-if workflows as a secondary lane.
27. Expanded live-execution acceptance criteria under the existing staged-authority issues.
28. Fixed-income data coverage and explicit rejection of unsupported debt structures.

#### 2.4 Duplicate handling decisions

- The previous 18 work packages are not recreated as new umbrella issues. Their requirements are mapped into current issue owners.
- Existing `ISSUE-0021`, `ISSUE-0113`–`ISSUE-0116`, `ISSUE-0127`–`ISSUE-0135`, `ISSUE-0138`–`ISSUE-0140` remain the owners of portfolio, optimisation, ledger, paper/live and UI work.
- Existing model and validation issues remain owners of Training Centre, features, folds, model families, calibration, efficacy and lifecycle governance.
- Existing `ISSUE-0037`, `ISSUE-0076`, `ISSUE-0080`, `ISSUE-0144`–`ISSUE-0146` and `ISSUE-0149` remain owners of settings, provider contracts, free-only policy, secret protection and terms/legal review.
- The fixed-income, exact portfolio performance, bulk, selection, reservation, portfolio-forecast and parity issues remain proposed as `ISSUE-0153`–`ISSUE-0169`.
- Seven genuinely absent user-priority release slices are proposed as `ISSUE-0170`–`ISSUE-0176`: fund identity, fund data, fund analytics, selected-currency/FX, risk profiles, analysis depth and provider credentials.
- Peer-score layering, multidimensional top-*N*, benchmark efficacy, personal-use boundaries and tax-scope reduction are amendments to existing owners rather than duplicate issues.
- Programme governance must re-check the canonical registry immediately before issue creation and renumber proposed IDs only if another issue has claimed them; dependency semantics must not change.


#### 2.5 Relevant live issue-state audit

The table below is an implementation-routing aid, not a substitute for re-reading the current registry immediately before work. “Initial” and “integrated” still mean open until complete closure evidence exists.

| Canonical issue/family | Observed programme position in this review | Master-spec action |
|---|---|---|
| `ISSUE-0070` | Integrated; execution remains disabled | Amend scope and authority matrix |
| `ISSUE-0008` | Implemented initially; open | Expand asset/strategy capability matrix |
| `ISSUE-0074` | Existing P0 score-engine owner | Amend with sealed `AnalysisSnapshot` |
| `ISSUE-0081` | Integrated; open | Harden bulk ingestion/resume |
| `ISSUE-0018` | Current open retained | Expand universe import/resolution |
| `ISSUE-0020` | Current open screener owner | Harden top-*N*, uncertainty and parity |
| `ISSUE-0082` | Planned/open data-platform owner | Extend identity to debt securities |
| `ISSUE-0083` | Planned/open classification owner | Extend fixed-income/context routing |
| `ISSUE-0084` | Planned/open | Add debt cash flows and FX semantics |
| `ISSUE-0085` | Planned/open | Add settlement/day-count clocks |
| `ISSUE-0086` | Planned/open | Add complete portfolio/bond imports |
| `ISSUE-0087` | Integrated; open | Reuse for global official filings |
| `ISSUE-0088` | Implemented initially; open | Extend curves, cash and benchmarks |
| `ISSUE-0089` | Planned/open | Extend anomaly rules to multi-asset data |
| `ISSUE-0098` | Planned/open P0 | Generalise peer service/adapter contract |
| `ISSUE-0099`–`0102` | Planned/open family | Complete sector-specific metric semantics |
| `ISSUE-0110` | Integrated; open | Add multi-asset factor interfaces |
| `ISSUE-0111` | Open risk-estimation owner | Add robust dependence/tail requirements |
| `ISSUE-0112` | Planned/open | Complete benchmark hierarchy |
| `ISSUE-0117` | Implemented initially; open | Govern three training lanes |
| `ISSUE-0119` | Implemented initially; open | Extend PIT features/targets |
| `ISSUE-0120` | Implemented initially; open | Harden validation/multiplicity |
| `ISSUE-0121` | Implemented initially; open | Complete task-separated model zoo |
| `ISSUE-0108` | Planned/open | Define calibrated total-return outputs |
| `ISSUE-0109` | Existing uncertainty owner | Add disagreement/clone/coverage evidence |
| `ISSUE-0123` | Planned/open | Implement calibration and fallback |
| `ISSUE-0124` | Planned/open | Implement lifecycle/rollback/drift |
| `ISSUE-0125` | Implemented initially; open | Harden event/order-level backtest |
| `ISSUE-0126` | Planned/open | Implement PIT universes/delistings/defaults |
| `ISSUE-0127` | Planned/open P0 | Complete double-entry ledger |
| `ISSUE-0128` | Implemented initially; open | Harden asset-specific costs |
| `ISSUE-0129` | Integrated; open | Complete paper broker/forward evidence |
| `ISSUE-0130` | Integrated; open | Harden deterministic proposal policy |
| `ISSUE-0131` | Planned/open | Implement broker read-only/reconciliation |
| `ISSUE-0132` | Planned/open | Implement independent controls |
| `ISSUE-0133` | Planned/open; blocked by controls/certification | Implement only narrow canary after gates |
| `ISSUE-0134`–`0135` | Planned/open | Implement TCA and recovery drills |
| `ISSUE-0136` | Integrated; open | Extend typed API/view models |
| `ISSUE-0137` | Implemented initially; open | Complete task-oriented design system |
| `ISSUE-0138`–`0139` | Implemented initially; open | Complete research/portfolio/operations UI |
| `ISSUE-0140` | Implemented initially; open | Complete accessibility/localisation |
| `ISSUE-0142` | Planned/open | Add advanced invariant/differential tests |
| `ISSUE-0143` | Hardening required | Add load/soak/fault/chaos evidence |
| `ISSUE-0144`–`0146` | Integrated; open | Complete security/supply-chain/recovery evidence |
| `ISSUE-0147` | Existing audit-package owner | Expand audit packet to v3 |
| `ISSUE-0149` | Hardening required | Complete legal/licence/terms review |
| `ISSUE-0150` | Implemented initially; open | Extend coverage/bias to fixed income |
| `ISSUE-0151` | Existing hardware-profile owner | Add graceful resource degradation |
| `ISSUE-0152` | Blocked | Expand and retain final certification gate |

#### 2.6 Closed and rejected evidence that remains authoritative

The historical closed ledger establishes completed foundations such as provider/source authority, evidence ledger, several ETF disclosure parsers, score/basic-risk diagnostics and audit-packet work. Those records must not be reopened merely to rename them. Broader gaps remain owned by linked open follow-ups.

The historical rejected decisions remain binding unless a separately approved scope change replaces them: immediate autonomous execution, direct LLM portfolio management, reinforcement-learning trading agents, martingale/grid systems, unsupported futures/intraday implementation, news sentiment as direct score authority, screenshot performance as evidence and unscoped high-risk products. The present staged-bot plan does not reverse those decisions; it creates deterministic paper/read-only/canary gates under current open execution issues.

### 3. Product-wide calculation semantics

#### 3.1 “Expected gain/loss” is a distribution

For every supported horizon, display at minimum:

```text
horizon ∈ {1W, 1M, 3M, 6M, 9M, 2Y, 5Y}
q05, q10, q25, q50, q75, q90, q95 cumulative total return
annualised q05–q95 and annualised expected/median return for 2Y and 5Y
expected/mean total return only when statistically stable
probability(total_return < 0)
probability(total_return > matching_cash_return)
probability(total_return > asset_benchmark_return)
probability(total_return > canonical_VWCE_return) where meaningful
expected amount gain/loss in the selected output currency
local-asset return, FX return and selected-currency return
calibration state, realised coverage and effective independent outcomes
aleatoric uncertainty
epistemic/model disagreement
data-quality and source-shift uncertainty
gross and net-of-cost values
risk_profile_eligibility and recommendation state
analysis_depth_profile and omitted_optional_evidence
```

Do not present an exact target price as certainty. If the horizon, asset, NAV frequency, FX state or evidence state is unsupported, return unavailable. `2Y` and `5Y` models may be trained immediately on point-in-time historical rolling labels, but they remain retrospectively supported until unseen outcomes mature; local compute time never substitutes for calendar maturity.

#### 3.2 Canonical `AnalysisSnapshot`

Create or extend one sealed record:

```text
analysis_run_id
analysis_schema_version
instrument_id
entity_id
asset_type
decision_time
data_as_of
price_as_of
universe_snapshot_id
source_snapshot_hash
feature_set_id
policy_version
peer_cohort_id
peer_fallback_path
benchmark_id
vwce_anchor_snapshot_id
cash_proxy_id
task
horizon
analysis_depth_profile_id
hardware_profile_id
local_currency
output_currency
fx_snapshot_id
fx_hedging_state
deterministic_scores
peer_normalised_components
asset_specific_evidence_score
model_outputs
calibrated_distribution
risk_and_costs
evidence_quality
risk_profile_results
blocked_by
advisory_label
reason_codes
created_at
```

Instrument detail, screener row, bulk result, portfolio holding, backtest decision, paper decision and trade proposal reference this record by ID. They may format it differently; they cannot recalculate it with hidden or newer inputs.

#### 3.3 Portfolio return definitions

A purchase or sale is an internal exchange between portfolio cash and a security. It is **not** an external flow. Deposits and withdrawals are external flows.

```text
net_external_flow = contributions - withdrawals

investment_pnl_output =
    ending_value_output
  - beginning_value_output
  - net_external_flow_output
```

For end-of-day dated external flows, a daily sub-period return may be calculated as:

```text
r_t = (ending_value_t - external_flow_t) / beginning_value_t - 1
TWR = Π(1 + r_t) - 1
```

If the system has beginning-of-day or intraday flow valuation, use that declared policy consistently. Do not mix conventions silently. MWR solves the dated-cash-flow internal rate of return. Modified Dietz is a labelled fallback only when true daily valuation is unavailable.

Dividends, bond coupons, fund distributions and cash interest are investment income and remain internal. Fees and taxes reduce investment performance; they are not withdrawals unless the user explicitly removes cash from the portfolio.

#### 3.4 Required portfolio labels

- **Portfolio value (selected currency):** period-end market value, including contributed capital.
- **Net invested capital (selected currency):** cumulative external contributions less withdrawals.
- **Investment P&L (selected currency):** investment gain/loss excluding external contributions and withdrawals.
- **TWR (%):** geometrically linked strategy/portfolio return neutralising external-flow timing.
- **MWR/XIRR (%):** investor-experience measure sensitive to contribution timing; annualisation must be explicit.
- **Net contributions (selected currency):** shown separately and never disguised as performance.

#### 3.5 User-selected output currency and FX

- Default output/base currency is EUR, but the user can select at least EUR, USD, GBP, CHF, CAD, AUD, NZD, JPY, CNY, HKD, SGD, KRW, INR, NOK, SEK, DKK, PLN and CZK when a validated point-in-time FX series exists.
- Preserve instrument local currency, reporting currency, fund base currency, share-class currency, trading/dealing currency, transaction currency and estimated economic currency exposure as distinct fields.
- Convert transactions at transaction-date FX, valuations at valuation-date FX and forecasts through a horizon-aligned FX distribution or declared deterministic scenario—not by silently applying today’s spot rate to every future outcome.
- Base-currency total return follows `1 + r_output = (1 + r_local) × (1 + r_fx)` before costs, with sign conventions and quote direction stored explicitly.
- Show local return, FX contribution, selected-currency return and, for hedged share classes, hedge policy/coverage separately.
- Central-bank reference rates are valuation/reference evidence, not executable dealing quotes. Stale, missing, suspended or conflicted FX blocks precise output-currency amounts.
- Dimensionless peer percentiles do not change merely because the display currency changes; currency-sensitive valuation, costs, forecasts and benchmark comparisons are recomputed through the sealed FX snapshot.

#### 3.6 Asset classes are not directly interchangeable

A stock quality score, ETF structure score and bond yield/risk score are not a common scale. The common cross-asset layer is limited to:

- calibrated total-return distribution;
- probability of loss and benchmark/cash outperformance;
- volatility, tail, liquidity and cost;
- evidence quality and uncertainty;
- portfolio marginal impact;
- explicit user constraints and utility policy.

#### 3.7 Peer-relative evidence versus benchmark-relative opportunity

The canonical score path has seven explicit layers:

1. **Raw fact/metric:** as-filed or derived value, unit, period, source and formula.
2. **Applicability gate:** whether the metric is economically meaningful for that asset and business model.
3. **Peer-normalised component:** robust percentile or residual inside a point-in-time economically valid cohort.
4. **Asset-specific evidence score:** transparent combination of applicable stock, ETF, fund or bond components.
5. **Common probabilistic output:** selected-currency total-return distribution, loss probability, risk, cost, liquidity and evidence quality.
6. **Risk-profile policy:** profile-specific filtering and utility weighting; it cannot alter the raw facts, peer percentiles or forecast distribution.
7. **Final opportunity comparison:** probability and magnitude of beating the relevant asset benchmark, matching cash proxy and, where useful, canonical VWCE.

A bank P/E and a technology P/E therefore never share a raw valuation percentile merely because both are called P/E. VWCE-relative opportunity can be shown after valid asset-specific analysis; it cannot repair an invalid peer cohort.

#### 3.8 Exact horizon contract

| Horizon | Primary use | Minimum output | Evidence caution |
|---|---|---|---|
| `1W` | short event/price-risk context | cumulative distribution and loss/benchmark probabilities | unavailable for funds without sufficiently frequent NAV/dealing data; costs and event timing dominate |
| `1M` | short tactical research | cumulative distribution | strong overlap and regime sensitivity |
| `3M` | quarterly decision cycle | cumulative distribution | filing/event timing and costs matter |
| `6M` | medium decision cycle | cumulative distribution | combines trend, valuation change and fundamentals |
| `9M` | current app’s longest original horizon | cumulative distribution | prospective evidence requires nine months |
| `2Y` | long-term appreciation/depreciation | cumulative and annualised distributions | overlapping labels sharply reduce independent sample size; initially lower evidence maturity |
| `5Y` | strategic long-term range | cumulative terminal-value and annualised distributions | historical training is possible now, but genuine prospective confirmation takes five years |

Production analysis uses frozen approved models. The Training Centre may run bounded research over hours, days, weeks or months, but a normal user analysis must not retrain the entire model zoo. A later model release creates new analysis snapshots; it never rewrites prior forecasts.

#### 3.9 Long-only recommendation semantics

Normal recommendations are limited to `buy_candidate`/`add_candidate`, `hold`, `avoid`/`no_trade`, `trim_candidate`/`sell_candidate` and `manual_review`. They assume an unleveraged long position. Shorting, leverage, margin, options, futures, inverse products, crypto and complex structured exposures remain rejected or research-only. A sell/trim label can apply to an existing holding; an unowned instrument with negative evidence is normally `avoid` or `no_trade`, not a short recommendation.

### 4. Supported-asset capability matrix

| Asset type | Analyse/screen | Portfolio | Paper | First live-canary eligibility | Notes |
|---|---|---|---|---|---|
| Listed common stocks | Yes | Yes | Yes | Liquid long-only subset | Existing stock programme; identity and point-in-time tests apply. |
| Plain physical ETFs/UCITS ETFs | Yes | Yes with look-through | Yes | Liquid long-only subset | Distinguish fund, share class, listing and economic exposure. |
| Cash and FX balances | Context/valuation | Yes | Yes | Conversion only under explicit policy | Cash is an asset and benchmark; FX attribution is separate. |
| Fixed-rate government/corporate bonds | New issue family | Yes | Yes after fixtures | Not in first live canary | Requires clean/dirty pricing, schedules, denomination and liquidity. |
| Zero-coupon bonds | New issue family | Yes | Yes after fixtures | Later certification | Full day-count/settlement rules still apply. |
| Floating-rate and inflation-linked bonds | Planned extension | Yes after analytics | Paper only initially | Not initially | Requires index fixings, reset/inflation-lag data. |
| Callable/amortising bonds | Terms and YTW first | Yes with warnings | Paper only initially | Not initially | Full option-adjusted valuation is a later research stage. |
| Bond ETFs | Existing ETF engine plus bond look-through | Yes | Yes | Per-ETF liquidity certification | Do not treat as a single bond. |
| Ordinary mutual/index funds and non-exchange UCITS share classes | Yes where identity, NAV, dealing terms, documents, fees and sufficient history are validated | Yes | No by default | No | First-class fund family; distinguish umbrella, sub-fund and share class. NAV/dealing, cut-off, settlement and redemption rules replace ETF intraday assumptions. Short horizons may be unavailable. |
| ETCs/certificates | Explicit capability entry required | Research/portfolio only | No by default | No | Legal structure and issuer risk need dedicated treatment. |
| Penny/OTC shares, highly illiquid microcaps, leveraged/inverse ETFs, derivatives, shorts, margin, options, futures, crypto products, complex structured funds/notes, ABS/MBS, convertibles and perpetuals | Unsupported or research-only until separate issues and explicit opt-in | Import-only where safe | No | No | Must be rejected explicitly, never passed through an equity/fund fallback or included in normal top-*N* lists. |

### 5. Target architecture

```text
Approved providers and user/broker imports
    ↓
Immutable raw/cache objects + terms/licence metadata
    ↓
Identity master + asset capability + point-in-time universe
    ↓
Corporate actions + cash-flow schedules + prices + FX + documents
    ↓
Source conflict, anomaly and coverage gates
    ↓
Canonical facts/features/targets
    ↓
Asset-specific transparent analysis
    ↓
Task/horizon-specific global models + supported local adapters
    ↓
Calibrated total-return/risk distributions
    ↓
Canonical AnalysisSnapshot
    ├── instrument detail
    ├── bulk analyser / screener
    ├── portfolio holdings and expected outcomes
    ├── backtest and paper
    └── deterministic proposal policy
             ↓
       independent execution controls
             ↓
       broker adapter + reconciliation
```

#### 5.1 Portfolio books of record

Maintain three linked books:

1. **Transaction/ledger book:** immutable double-entry cash, security, FX, fee, tax and corporate-action entries.
2. **Position/valuation book:** quantities, lots, accrued income, prices, FX, fair-value state and daily snapshots.
3. **Analysis/decision book:** sealed analysis snapshots, targets, proposals, orders, fills and outcomes.

#### 5.2 Portfolio visualisation contract

For any selected range and as-of snapshot:

- a line view toggles portfolio value, invested capital, investment P&L, TWR index, benchmark index and drawdown;
- quarterly/yearly bars toggle ending value, investment P&L, TWR (%), income, fees/tax, FX contribution and net contributions in the selected output currency;
- partial first/last periods are visibly marked;
- all figures reconcile to the ledger and selected valuation snapshot;
- pie/donut charts show asset class, sector, country, currency, issuer and, for bonds, rating/maturity/duration;
- direct, look-through and combined exposure are separate modes;
- every chart displays mapped coverage and an `Unknown/Unmapped` segment.

#### 5.3 Additional high-value portfolio features

- multiple accounts and brokers with consolidated and per-account views;
- target allocations, drift bands and estimated rebalance cost;
- benchmark and cash-relative performance;
- dividend/coupon/income and maturity ladder;
- tax lots and realised/unrealised P&L under a declared method;
- security/sector/country/FX/income/fee attribution;
- marginal and component risk;
- stress and reverse-stress tests;
- ETF overlap and direct/indirect ownership;
- liquidity and estimated liquidation time/cost;
- upcoming corporate, ETF and bond events;
- stale/conflicted-data and reconciliation alerts;
- what-if buy/sell/rebalance before a proposal;
- goals and user constraints without claiming regulated personal suitability;
- history of forecasts versus realised outcomes.

### 6. Bulk import and top-*N* workflow

```text
Upload/select universe
→ validate file/schema/size
→ resolve identity, fund share classes and duplicates
→ show unsupported/ambiguous rows
→ select exact horizon(s), output currency, risk profile(s) and Quick/Medium/High/Full depth
→ freeze universe/data/provider/FX/model/profile/policy snapshots
→ acquire/refresh lawful data through rate-limited, resumable shards
→ run the canonical analyser once per instrument/horizon
→ persist eligible, blocked, failed and unavailable records
→ asset-specific peer ranking and uncertainty
→ materialise total, sector, country, country×sector, profile and horizon top-N slices
→ optional cross-asset portfolio-fit selection
→ top-N results, exclusion funnel, timing stages and full audit export
```

Required properties:

- deterministic tie-breaking;
- checkpoint/restart without changing the frozen run;
- provider quotas and back-off;
- no duplicate download or analysis for identical content hashes;
- per-instrument error isolation;
- partial completion must state exact coverage;
- opening a result uses the stored `analysis_run_id`;
- a rerun creates a new version instead of overwriting history;
- cold acquisition, warm-cache refresh, feature calculation, inference, calibration and ranking durations are recorded separately;
- analysis-depth changes create a new run and may expand evidence/model breadth, but cannot silently change formulas, hard gates or source authority;
- grouped top-*N* views state their exact membership rule, denominator, `n`, effective `n`, fallback and unavailable reason;
- runtime targets are release-tested on a declared reference fixture and hardware profile rather than shown as fabricated per-run estimates.

### 7. Trading-bot operating model

#### 7.1 Authority ladder

| Mode | Data access | Proposal | Broker write | Human approval | Typical use |
|---|---|---|---|---|---|
| OFF | Local analysis | No | No | N/A | Research only |
| PAPER | Frozen data + simulated broker | Yes | Simulated | Configurable | Forward evidence |
| READ_ONLY_BROKER | Positions/cash/orders/fills | No write | No | N/A | Reconciliation |
| DRAFT_ORDERS_WITH_APPROVAL | Read-only plus previews | Draft only | Submit only after explicit approval | Every batch/order | Supervised execution |
| SUPERVISED_LIVE_CANARY | Certified narrow universe | Yes | Tiny bounded orders | Initially every order | Operational evidence |
| BOUNDED_AUTOMATIC | Certified strategy/account/asset | Yes | Bounded automatic | Policy plus emergency operator | Separate final promotion |

#### 7.2 First live-canary scope

- liquid long-only stocks and plain ETFs only;
- no leverage, shorting, derivatives or after-hours trading;
- marketable-limit or limit orders with price collars; market orders disabled by default;
- small maximum order and portfolio exposure;
- one broker/account initially;
- no automatic bond execution until a broker-specific bond capability, quote/RFQ workflow, denomination, accrued-interest and liquidity test pack is separately certified.

#### 7.3 Required independent controls

- global, strategy, instrument, broker-connection, stale-data, reconciliation, daily-loss, drawdown, duplicate-order and reject-rate kill switches;
- maximum order value, quantity, messages, turnover, position and sector/country exposure;
- price collars and spread/liquidity limits;
- market-state, auction, holiday and event-blackout checks;
- cash, settlement, FX and minimum-denomination reservation;
- idempotency and deterministic order state;
- cancel-all and orderly shutdown;
- real-time reconciliation of orders, fills, positions and cash;
- immutable logs and recovery drills;
- LLM and model outputs have no direct broker permission.

The ESMA/MiFID controls cited in the source register apply directly according to legal status and jurisdiction, not automatically to every private user. They are adopted here as a high-control engineering benchmark; the legal/terms issue must determine actual applicability.

### 8. Research synthesis and evidence quality

#### 8.1 Evidence hierarchy

This document uses a GRADE-like communication label, not a literal clinical GRADE assessment:

- **High:** authoritative legal/regulator/standards facts or mature statistical methods with strong replication.
- **Moderate–High:** peer-reviewed multi-market or multi-dataset evidence with relevant but manageable limitations.
- **Moderate:** peer-reviewed but setting-specific observational/backtest evidence.
- **Low–Moderate:** manager/vendor research or conference evidence with useful method content but incomplete independent validation.
- **Low/Very low:** product marketing, one-off claims or unauthenticated grey material.

Randomised controlled trials are generally not applicable to historical asset-pricing and software-control questions. Most financial ML research is not preregistered. The application compensates through frozen protocols, an all-attempt ledger, untouched outer tests, negative controls, locked final sets and forward/paper evidence.

#### 8.2 Institutional methods retained from public sources

The following table preserves every requested institution’s useful public lesson while separating it from proprietary claims.

##### Company-by-company matrix

The table below separates implementable public patterns from claims that must not be inferred.


| Company | Publicly supported pattern | Open/public artefact | Include in cockpit | Do not infer/copy | Source grade | Bias/limitations | Primary URL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Northfield Information Services | Bottom-up risk modelling; distinct short-, mid- and long-horizon risk; public description of textual-news-derived short-horizon risk scores. | Public research notes and product descriptions; no production model code identified. | Make horizon an explicit model dimension; separate risk from expected return; add news-driven risk context rather than a direct trade score. | Do not infer the proprietary covariance estimator, factor definitions or news model weights. | Low–Moderate | Strong commercial self-interest; no independent effect estimate on the cited page. | https://www.northinfo.com/aboutus.php |
| SimCorp Axioma | Trading-horizon factor model with a 20-day risk horizon, daily updates, short-interest/opinion-divergence/liquidity/downside factors, event risk and implementation trade-offs. | Public product and research descriptions; commercial APIs/platform, not open source. | Use horizon-specific risk models, event-aware residual risk, crowding/liquidity diagnostics and risk-versus-slippage views. | Do not clone factor formulae or claim equivalent coverage from public descriptions. | Low–Moderate | Product announcement; no independent validation or full methodology. | https://www.simcorp.com/about-us/news/2026/simcorp-launches-risk-model-to-support-short-horizon-trading |
| Man AHL | Public account of combining many weak, heterogeneous signals; warns that financial data are noisy and market rules change; reports ML components in trading programmes since 2014. | Public research; Man Group open repositories are handled separately below. | Use ensembles of weak, diverse signals, regime/drift monitoring and staged research-to-shadow-to-production promotion. | Do not treat marketing history as audited alpha evidence or copy inaccessible strategy logic. | Low–Moderate | Manager-authored; selective reporting and no full cost-adjusted replication. | https://www.man.com/insights/the-rise-of-machine-learning |
| Acadian Asset Management | Systematic process framed as economic intuition followed by empirical validation, systematic implementation and risk management. | Public research and methodology pages; no production code identified. | Require an economic hypothesis, frozen experiment protocol, empirical validation and implementation/cost review for every new feature. | Do not accept vendor case studies as investible performance without costs, survivorship and point-in-time checks. | Low–Moderate | Manager-authored marketing; external replication generally unavailable. | https://www.acadian-asset.com/au/about-us/our-systematic-edge |
| Robeco Quant | Residual momentum research aims to separate stock-specific momentum from common factor effects and reduce reversal exposure. | Public articles and papers; no production code identified. | Add residualised momentum, orthogonalisation and turnover-aware signal construction as challengers to raw momentum. | Do not assume a historic US result transfers unchanged to every market, sector or cap tier. | Low–Moderate | Manager-authored; source article is old and method details are incomplete. | https://www.robeco.com/en-int/insights/2013/10/robecos-residual-momentum-less-risky-and-more-sustainable |
| Research Affiliates | Public research separates structural return components from revaluation and publishes asset-allocation tools and long-horizon expected-return work. | Public papers and interactive tools; no production code identified. | Decompose recent performance into fundamentals/cash-flow, valuation change and currency effects; do not extrapolate revaluation mechanically. | Do not use manager forecasts as ground truth or hide large model uncertainty. | Low–Moderate | Intellectual-property licensor and sub-adviser; publication and product incentives. | https://www.researchaffiliates.com/insights/journal-papers/1097-revaluation-alpha |
| Dimensional Fund Advisors | Country-relative definitions of size, value, profitability and asset growth; explicit exclusions and local-universe comparisons. | Public methodology and index descriptions. | Use point-in-time country/region-relative ranks, explicit missing-data exclusions and profitability/investment dimensions. | Do not hard-code one global valuation threshold or assume country premia are stable. | Low–Moderate | Manager-authored; methodology examples are not an independent performance test. | https://www.dimensional.com/au-en/insights/a-wider-net-on-premiums |
| Scientific Beta | Transparent systematic index design, factor diversification and investable implementation are recurring public themes; acquired by STOXX on 8 July 2026. | Public index/research material; data access varies. | Make index/peer methodology versioned, transparent and reproducible; test factor intensity, unintended exposures and tracking error. | Do not assume all public factor claims replicate after fees or after the STOXX integration. | Low–Moderate | Index-provider commercial interest; acquisition may change product access and documentation. | https://www.scientificbeta.com/news-events/scientific-beta-begins-a-new-chapter-with-stoxx |
| TOBAM | Maximum-diversification framework explicitly avoids expected-return forecasts and instead maximises diversification across independent risk sources. | Public research and philosophy. | Include maximum-diversification/equal-risk anchors as robust portfolio baselines and model-risk checks. | Do not substitute diversification for expected-return validation, liquidity controls or concentration limits. | Low–Moderate | Manager-authored and tied to proprietary intellectual property. | https://www.tobam.fr/maximum-diversification/ |
| Quoniam | Public European small-cap material emphasises broad-universe systematic analysis, ML insight and cost-efficient implementation. | Public research and product material. | Create a separate small/mid-cap data-quality and liquidity tier; use broad candidate coverage but strict tradability and uncertainty gates. | Do not infer audited performance or universal small-cap capacity from a product announcement. | Low | Product announcement; no independent causal or cost-adjusted study. | https://www.quoniam.com/en/press-release/pr-european-small-caps/ |
| Ortec Finance | Consistent stochastic scenarios from one month to decades, worldwide risk drivers and user-adjustable views; explicitly describes what might, not will, happen. | Public product methodology. | Forecast distributions and scenarios, not single paths; keep horizon-consistent assumptions and allow controlled user views. | Do not treat a scenario generator as an alpha engine or copy proprietary frequency-domain methods. | Low–Moderate | Commercial product source; no independent forecast-skill estimate. | https://www.ortecfinance.com/en/insights/product/ofs |
| BlackRock / Aladdin | Whole-portfolio view, risk decomposition by factor/sector/security, stress testing, what-if analysis and optimisation on a common analytics spine. | Public platform descriptions and APIs; no open production risk engine. | Use one canonical positions/evidence store, common scenarios and drill-down from portfolio to factor to instrument. | Do not claim Aladdin-equivalent analytics or use allegations about internal tools as model evidence. | Low–Moderate | Commercial platform description; operational claims are not independent studies. | https://www.blackrock.com/aladdin/platforms/products/aladdin-risk |
| MSCI Barra | Transparent factor frameworks; style, sector and macro decomposition; country, regional and global models; long-term and trading horizons. | Public factor-model descriptions and index methodologies; proprietary data/model parameters. | Build transparent factor exposures, regional hierarchy, crowding/concentration flags and horizon-specific covariance models. | Do not reproduce proprietary Barra specifications or imply coverage parity. | Low–Moderate | Commercial analytics provider; methodology details and validation are selective. | https://www.msci.com/data-and-analytics/factor-investing/equity-factor-models |
| Bloomberg PORT | Integrated positions, performance, attribution and risk; API-oriented data integration; scenario and factor-risk workflows. | Public platform descriptions and SDK documentation; commercial data/terminal required for core use. | Add workflow orchestration, source validation, consistent position snapshots and scenario/attribution views. | Do not make Bloomberg data a silent dependency or redistribute licensed data. | Low–Moderate | Commercial platform source; no independent accuracy estimate. | https://professional.bloomberg.com/products/bloomberg-terminal/portfolio-analytics/ |
| State Street Alpha | Single-source-of-truth operating model, shared holdings/exposures/orders, public APIs and a partner ecosystem including multiple risk providers. | Public platform and API descriptions. | Use stable plug-in contracts, canonical books of record, reconciliation and provider interchangeability. | Do not couple the cockpit to one provider or treat workflow integration as investment evidence. | Low–Moderate | Commercial platform source. | https://www.statestreet.com/alpha |
| Two Sigma | Venn publishes a Lasso-based parsimonious factor-selection approach; SEC settlement provides a strong model-integrity and governance lesson. | Public methodology; selected open-source repositories exist, but production investment systems are proprietary. | Use sparse factor selection, prediction-diff monitoring, immutable artefacts, dual control, rollback and model-change audit trails. | Do not use or seek proprietary model code; an SEC incident is a controls lesson, not an alpha source. | Moderate for controls; Low for strategy inference | Venn is commercial; SEC record is high-authority but does not validate investment method. | https://help.venn.twosigma.com/en/articles/1393204-two-sigma-factor-selection-methodology |
| AQR | Public factor datasets and definitions, including quality based on profitability, growth, safety and payout; long US and global histories. | Downloadable public datasets and working papers. | Use transparent factor baselines and independent replication data; expose definitions and version dates. | Do not assume factor timing or marketing research survives costs, crowding and multiple testing. | Moderate as reproducible baseline; Low–Moderate for performance claims | Manager affiliation and product incentives; several papers disclose AQR ties. | https://www.aqr.com/insights/datasets/quality-minus-junk-six-portfolios-formed-on-size-and-quality-monthly |
| Man Group | Public engineering repositories include ArcticDB, D-Tale, notebooker and testing/reporting tools; ArcticDB has versioned/time-travel data concepts but current production licensing restrictions. | Source-available and open-source repositories with mixed licences. | Borrow immutable snapshots, time travel, reproducible notebook scheduling and test tooling; verify each licence before use. | Do not assume source-available means production-free; do not mix Man AHL marketing evidence with independent replication. | Moderate for software behaviour | Licensing and commercial-use restrictions apply to some projects. | https://github.com/man-group |
| Goldman Sachs | GS Quant is an Apache-2.0 Python toolkit for quantitative finance; some APIs require institutional credentials. | Open-source library plus restricted external services. | Reuse only licence-compatible abstractions, testing patterns and generic analytics; pin versions and isolate credentialed adapters. | Do not use historical copied proprietary code or assume API availability without credentials. | Moderate for software behaviour | Open library is real, but associated commercial services and datasets are restricted. | https://github.com/goldmansachs/gs-quant |

#### 8.3 Independent and primary research evidence

##### Study and incident evidence register


| ID | Source | Design/sample | Finding | Effect/statistics | COI | Preregistration | Replication/limits | GRADE | URL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E-001 | Gu, Kelly & Xiu — Empirical Asset Pricing via Machine Learning | Comparative ML study of US equity risk-premium prediction; multiple algorithms and out-of-sample testing. | Trees and neural networks benefited from nonlinear interactions; dominant signals included momentum, liquidity and volatility. | NBER abstract says some ML strategies doubled leading regression-strategy performance; no single universal CI or p-value is reported on the landing page. | Bryan Kelly disclosed >US$5,000 AQR consulting income. | No preregistration identified. | Widely cited and code/data variants exist, but replication is sensitive to universe, costs and timing. Multiple model search, publication bias, implementation costs and non-stationarity. | Moderate | https://www.nber.org/papers/w25398 |
| E-002 | Harvey, Liu & Zhu — … and the Cross-Section of Expected Returns | Multiple-testing framework for the factor literature. | Argues a newly discovered factor should clear a materially higher hurdle than t≈2. | Estimated hurdle t>3 in the paper’s framework. | No specific commercial tie identified on the cited landing page. | No preregistration identified. | Seminal methodological contribution; conclusions depend on estimated research-production process. Factor-publication selection and correlation among tests. | Moderate–High | https://www.nber.org/papers/w20592 |
| E-003 | DeMiguel, Garlappi & Uppal — Optimal Versus Naive Diversification | 14 allocation models across seven empirical datasets, evaluated out of sample. | No model was consistently better than 1/N on Sharpe ratio, certainty-equivalent return or turnover. | Analytical calibration suggested roughly 3,000 months for 25 assets and 6,000 months for 50 assets for sample mean-variance to beat 1/N. | No material tie identified in the abstract source. | No preregistration identified. | Seminal and independently cited; older data and allocation setting. Estimation error, dataset choice and changing market structure. | Moderate–High | https://ideas.repec.org/a/oup/rfinst/v22y2009i5p1915-1953.html |
| E-004 | Cakici et al. — Machine Learning Goes Global | 46 stock markets, 148 firm characteristics, multiple ML models. | Predictability concentrated in momentum, reversal, value and size; model combinations helped; performance varied with firm size, information availability, listed-firm count and idiosyncratic risk. | Abstract does not provide a single pooled CI/p-value for the implementation decision. | No commercial conflict identified from the abstract source. | No preregistration identified. | International scope is a strength; exact cost and data-vintage sensitivity still matter. Survivorship, cross-market data quality, transaction costs and model multiplicity. | Moderate | https://doi.org/10.1016/j.jedc.2023.104725 |
| E-005 | Cakici & Zaremba — The More, the Better? | Three decades, 45 markets; country, region, sector and industry local/global/soft-transfer training. | Global and local predictive performance were broadly comparable; global training helped mainly smaller, high-idiosyncratic-risk markets. | Abstract reports qualitative comparative results rather than one universal effect/CI. | No commercial conflict identified in the accessible abstract. | No preregistration identified. | Current peer-reviewed evidence directly relevant to model routing. Market definitions, costs, data vendor choices and regime dependence. | Moderate–High | https://doi.org/10.1016/j.jbankfin.2026.107658 |
| E-006 | Hellum, Pedersen & Rønn-Nielsen — How Global Is Predictability? | International return-prediction transfer-learning paper presented at EFA 2025. | Finds a global model stronger than local models and estimates predictive parameters as 94% global; adds a local component through GENet. | 94% global is the headline estimate; accessible page does not show CI/p-value. | AQR affiliation is explicit. | No preregistration identified. | Peer-reviewed conference paper, not yet as mature as a settled journal replication. Commercial affiliation, specification choices and conference-paper status. | Low–Moderate | https://research.cbs.dk/en/publications/how-global-is-predictability-the-power-of-financial-transfer-lear/ |
| E-007 | Loughran & McDonald — When Is a Liability Not a Liability? | Large sample of US 10-K filings, 1994–2008. | General-language sentiment dictionaries misclassified financial text; finance-specific lexicons improved measurement. | Almost three quarters of Harvard-negative words in the sample were not ordinarily negative in a financial context. | No commercial conflict identified in the accessible record. | No preregistration identified. | Seminal and widely replicated in financial text analysis. US filing language and period may not transfer to multilingual news. | Moderate–High | https://papers.ssrn.com/abstract=1331573 |
| E-008 | Coqueret — Stock-Specific Sentiment and Return Predictability | More than 1,000 large US stocks; daily predictive regressions. | Significant predictive t-statistics occurred for at most 7% of stocks; reverse feedback from returns to sentiment was stronger. | ≤7% significant stock-level tests; abstract does not report pooled CI. | Author reported no potential conflict. | No preregistration identified. | Contradicts broad claims that generic sentiment is a reliable direct alpha signal. Large-cap US focus, repeated testing and model specification. | Moderate | https://doi.org/10.1080/14697688.2020.1736314 |
| E-009 | Benjamini & Hochberg — False Discovery Rate | Formal multiple-testing method with proof under independence and simulation. | Controls expected false-discovery proportion while retaining more power than family-wise control in many settings. | Theoretical guarantee depends on assumptions; no finance-specific effect size. | Academic source. | No preregistration identified. | Seminal and extensively replicated/extended. Dependence structure requires suitable variants or resampling. | High for method | https://doi.org/10.1111/j.2517-6161.1995.tb02031.x |
| E-010 | Bailey et al. — Backtest Overfitting | Mathematical analysis of repeated strategy search and out-of-sample degradation. | More tried configurations increase the chance that the selected backtest is overfit; under memory, expected OOS return can become negative. | No single universal threshold; effect depends on trials and data structure. | One author has commercial model-selection interests; method remains independently discussable. | No preregistration identified. | Important caution; exact estimators are contested and implementation-dependent. Assumption sensitivity and misuse as a mechanical badge. | Moderate | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659 |
| E-011 | SEC — Two Sigma model-vulnerability settlement | Settled SEC enforcement record. | Known vulnerabilities remained unaddressed for years; unauthorised changes affected more than a dozen models. | US$165 million repaid; US$90 million civil penalties. | Official regulator record. | Not applicable. | High-authority for the settled facts, not for investment-method inference. Does not disclose proprietary strategy details and should not be used to reconstruct them. | High | https://www.sec.gov/newsroom/press-releases/2025-15 |
| E-012 | SEC — AXA Rosenberg coding-error case | Settled SEC enforcement record involving a quantitative model code error and concealment. | A code error disabled a key risk component and was not promptly disclosed or fixed. | US$217 million investor losses; US$217 million restitution plus US$25 million penalty. | Official regulator record. | Not applicable. | High-authority controls lesson. Historical analogue, not evidence about any current named company’s models. | High | https://www.sec.gov/news/press/2011/2011-37.htm |



| E-013 | Carhart — *On Persistence in Mutual Fund Performance* | Survivor-bias-free US diversified equity-fund panel, January 1962–December 1993; 1,892 funds and 16,109 fund-years. | Common factors, expenses and transaction costs explain almost all persistence; remaining persistence is concentrated in severe underperformance by the worst funds. | Expenses reduce performance at least one-for-one; trading reduces performance by about 0.95% of trade value; load funds underperform no-load funds by about 0.80 percentage points/year after controls. | Dimensional Fund Advisors Fellowship and other academic support disclosed. | No preregistration identified. | Seminal; excludes sector, international and balanced funds and predates current fund structures. Supports cost/survivorship controls, not a universal no-skill claim. | Moderate–High | https://doi.org/10.1111/j.1540-6261.1997.tb03808.x |
| E-014 | Wermers — *Mutual Fund Performance: An Empirical Decomposition…* | Holdings- and return-based decomposition of the US mutual-fund industry. | Fund holdings outperformed the market before costs, while investor net returns underperformed; costs and non-stock holdings explain the gap. | Stocks held outperformed by 1.3 percentage points/year; net fund returns underperformed by 1.0 point; 1.6 points of the 2.3-point gap came from expenses and transaction costs. | Academic source; no material commercial tie identified in the article record. | No preregistration identified. | Credible contradictory evidence to a simple “active management never adds value” claim; results are period-, database- and benchmark-dependent. | Moderate–High | https://doi.org/10.1111/0022-1082.00263 |
| E-015 | Evans — *Mutual Fund Incubation* | Study of privately incubated funds later opened or withheld by fund families. | Backfilled pre-public returns can be selected upward; apparent skill disappears after public launch. | Incubated funds outperformed non-incubated funds by 3.5% risk-adjusted before public opening; the outperformance disappeared post-incubation. | Academic source; no commercial tie identified in the accessible record. | No preregistration identified. | Directly supports public-history, ticker-creation and fund-age filters; fund-family practices may change over time. | Moderate–High | https://doi.org/10.1111/j.1540-6261.2010.01579.x |
| E-016 | Fama & French — *Luck versus Skill in the Cross-Section of Mutual Fund Returns* | Bootstrap analysis of actively managed US equity mutual funds, 1984–2006. | Aggregate active funds resemble the market before costs; high costs lower investor returns; few funds generate expected benchmark-adjusted returns sufficient to cover costs. | No single universal alpha/CI is reported in the abstract; non-zero true alpha is concentrated in extreme tails after adding back expenses. | Academic authors; no product-provider funding stated in the accessible record. | No preregistration identified. | Widely replicated/debated; inference depends on factor model, benchmark and bootstrap design. | Moderate–High | https://doi.org/10.1111/j.1540-6261.2010.01598.x |
| E-017 | Gneiting & Raftery — *Strictly Proper Scoring Rules, Prediction, and Estimation* | General statistical theory and examples for evaluating probabilistic forecasts. | Strictly proper scores encourage honest distribution forecasts and provide principled loss functions. | Theoretical result; no finance-specific effect size. | DoD MURI and US National Science Foundation funding disclosed. | No preregistration identified. | Seminal, broadly replicated method; scoring rule must match the forecast object and decision problem. | High for method | https://doi.org/10.1198/016214506000001437 |
| E-018 | Diebold & Mariano — *Comparing Predictive Accuracy* | Forecast-comparison theory allowing non-Gaussian, biased, serially and contemporaneously correlated errors and non-quadratic loss. | Tests whether two competing forecasts have equal accuracy under a chosen loss function. | Theoretical/asymptotic and finite-sample procedures; no universal effect size. | Academic/NBER source. | No preregistration identified. | Seminal; small-sample and nested-model cases require guarded variants. | High for method | https://doi.org/10.1080/07350015.1995.10524599 |
| E-019 | Clark & West — *Approximately Normal Tests for Equal Predictive Accuracy in Nested Models* | Theory and simulations for comparing a parsimonious model with a larger nested forecast model. | Adjusts mean-squared prediction-error differences for parameter-estimation noise in the larger model. | Simulation evidence supports the proposed adjustment; critical-value size is close to but slightly below nominal under stated conditions. | Kenneth West disclosed US National Science Foundation support; Federal Reserve disclaimer applies. | No preregistration identified. | Appropriate for nested challengers; not a substitute for economic utility, calibration or multiplicity control. | High for method | https://doi.org/10.1016/j.jeconom.2006.05.023 |
| E-020 | Welch & Goyal — *A Comprehensive Look at the Empirical Performance of Equity Premium Prediction* | Re-examination of published aggregate equity-premium predictors with real-time out-of-sample tests. | Most published predictors were unstable and failed to beat the historical-average forecast over long evaluation periods. | No single pooled CI; the paper reports broad failure across the reviewed predictor set. | Academic source; no commercial tie identified in the accessible record. | No preregistration identified. | Seminal sceptical benchmark; aggregate market timing differs from cross-sectional stock selection and later work finds limited exceptions. | Moderate–High | https://doi.org/10.1093/rfs/hhm014 |
| E-021 | Campbell & Thompson — *Predicting Excess Stock Returns Out of Sample* | Out-of-sample predictive regressions with weak sign and forecast restrictions. | Credible economic restrictions can improve performance over the historical-average forecast, although explanatory power is small. | Abstract reports small but economically meaningful out-of-sample gains; no universal CI. | Academic source; no commercial tie identified in the accessible record. | No preregistration identified. | Important contradictory evidence to E-020; benefits depend on restrictions, sample and investor utility. | Moderate–High | https://doi.org/10.1093/rfs/hhm055 |
| E-022 | Rapach, Strauss & Zhou — *Out-of-Sample Equity Premium Prediction: Combination Forecasts…* | Multiple-predictor forecast combinations evaluated out of sample. | Combination forecasts reduce model instability/volatility and can deliver statistically and economically significant gains over the historical average. | Abstract reports significant gains but no single pooled effect/CI. | Academic source; no commercial tie identified in the accessible record. | No preregistration identified. | Supports constrained ensembles, not unrestricted model averaging; aggregate-market evidence may not transfer to every asset/horizon. | Moderate–High | https://doi.org/10.1093/rfs/hhp063 |
| E-023 | Bhojraj & Lee — *Who Is My Peer?* | Valuation-theory-based comparable-firm selection tested for one- to three-year-ahead EV/sales and price/book ratios across general and “new economy” stocks. | Economically selected peers improve future multiple prediction relative to simpler peer-selection techniques. | Abstract reports “sharp improvements” but no universal CI/p-value. | Academic source; no commercial tie identified in the accessible record. | No preregistration identified. | Seminal peer-selection evidence; model-specific and older, with published methodological critique. | Moderate | https://doi.org/10.1111/1475-679X.00054 |
| E-024 | Newey & West — HAC covariance estimator | Formal method for heteroskedasticity- and autocorrelation-consistent covariance estimation. | Produces a positive semi-definite covariance estimate and is consistent under broad conditions. | Theoretical guarantee under stated assumptions; no finance-specific effect size. | Academic/NBER source. | No preregistration identified. | Seminal; bandwidth/kernel choices matter and do not solve all dependence. | High for method | https://doi.org/10.2307/1913610 |
| E-025 | Hansen & Hodrick — multi-step/overlapping-horizon inference | Econometric analysis of k-step-ahead forecasting with observations sampled more frequently than the forecast interval. | Demonstrates the dependence induced by overlapping forecast horizons and supplies a tractable inference framework. | Empirical tests reject the simple forward-rate efficiency hypothesis in the studied samples; method is the relevant application lesson. | Academic source. | No preregistration identified. | Seminal; later HAC/bootstrap methods may be preferable, but overlap cannot be ignored. | High for method | https://doi.org/10.1086/260910 |
| E-026 | SEC — Form N-PORT Data Sets | Official quarterly bulk datasets covering publicly disseminated structured filings from October 2019 through June 2026. | Provides as-filed monthly portfolio-holdings information for registered management funds/eligible ETFs; it is not a complete or accuracy-guaranteed global fund database. | 2026 Q2 bulk archive is about 420 MB; SEC explicitly disclaims guaranteed accuracy and completeness. | Official regulator source. | Not applicable. | High authority for filed US data; filing lags, public-field limits and extraction errors require source-document review. | High for as-filed data | https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets |
| E-027 | SEC/Investor.gov — mutual-fund versus ETF pricing | Official investor guidance and statutory-mechanics summary. | Ordinary mutual funds transact at the next calculated NAV, typically end-of-business-day; ETFs trade intraday at market prices that may differ from NAV. | Definition/mechanics, not a forecast effect. | Official regulator education source. | Not applicable. | US-specific legal mechanics but strongly supports separate NAV/dealing and ETF-market-price contracts. | High for mechanics | https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/characteristics-mutual-funds-exchange-traded-funds |
| E-028 | ECB — euro foreign-exchange reference rates | Official daily reference-rate publication, usually around 16:00 CET on working days. | Rates support valuation/statistical conversion but are published for information purposes and are not executable dealing quotes. | Definition/publication policy; no forecast effect. | Official central-bank source. | Not applicable. | High for reference valuation; intraday/executable spread and unavailable currencies need separate treatment. | High for published reference data | https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html |
| E-029 | AFM — finfluencing and personal advice | Current Dutch supervisory guidance distinguishing personal investment advice from general recommendations. | Tailoring advice to another person’s financial situation can require a licence; a disclaimer alone does not remove the substantive boundary. | Legal/supervisory interpretation, not an effect estimate. | Official regulator source. | Not applicable. | Applicability depends on actual conduct and legal review; supports a generic guest-analysis mode and no suitability claims. | High for supervisory guidance | https://www.afm.nl/en/sector/themas/digitalisering/finfluencing |
| E-030 | ESMA — investment recommendations on social media | EU supervisory summary of Market Abuse Regulation recommendation requirements. | Facts must be separated from estimates/opinions; sources, conflicts, methodology, horizon and risk warnings must be disclosed as applicable. | Legal/supervisory requirements, not an effect estimate. | Official EU regulator source. | Not applicable. | Exact obligations depend on role/distribution; supports exportable methodology, timestamp and conflict records. | High for supervisory guidance | https://www.esma.europa.eu/press-news/esma-news/requirements-when-posting-investments-recommendations-social-media |
| E-031 | Vanguard — FTSE All-World UCITS ETF accumulating share class | Current official product page for ISIN `IE00BK5BQT80`, with multiple listings/currencies and dated fund/benchmark/risk data. | Confirms that ticker is listing-specific while the economic share class is identified by ISIN; risk and tracking data are time-varying snapshots. | At 30 June 2026 the page reports risk indicator 6 and annualised tracking error of 0.07%, 0.07% and 0.08% over 1, 3 and 5 years. | Product-provider source; commercial self-interest. | Not applicable. | High for current product facts, low for claims of future performance. The profile anchor must refresh, not hard-code these values. | High for product facts | https://www.vanguard.co.uk/uk-fund-directory/product/etf/equity/9679/ftse-all-world-ucits |

##### Interpretation of contradictory model-topology evidence

The model-topology question does not have a single settled empirical answer:

- the 2025 transfer-learning conference paper estimates a very large global component;
- the 2026 *Journal of Banking & Finance* paper reports broadly comparable local and global performance and uneven gains from global training;
- a separate 2026 regional/hybrid asset-pricing paper reports that regional or hybrid models can outperform global models in incompletely integrated markets;
- the 2023 46-market study finds that performance varies with market size, information availability and idiosyncratic risk.

These results are compatible with a hierarchical system. They contradict both extremes: thousands of isolated local models and one context-free universal model.

##### Bias controls required in the application

1. **Publication/funnel bias:** record every attempted hypothesis, not just surviving models.
2. **Data snooping:** assign experiments to a research family and control false discovery.
3. **Vendor/manager conflict:** vendor claims can motivate a baseline or diagnostic, not close an issue.
4. **Survivorship and look-ahead:** bitemporal data, delistings and historical universes are release blockers.
5. **Market heterogeneity:** assess results by country, sector, cap, liquidity and regime, but shrink sparse estimates.
6. **Costs and capacity:** evaluate after bid–ask spread, market impact, turnover, taxes/FX and holding costs.
7. **Temporal drift:** use rolling monitoring and retirement, not indefinite model validity.
8. **Model complexity:** a complex challenger must beat a transparent baseline on untouched data and in shadow mode.


#### 8.4 Additional model, validation and engineering ideas consolidated from the ZIP

The supplied archive adds the following non-duplicative requirements to the live issue owners:

##### Task separation

- **Cross-sectional ranking:** deterministic factor score, elastic net/ridge, LambdaMART/LightGBM and CatBoost ranking challengers.
- **Total-return distribution:** robust/historical baseline, quantile/distributional trees, N-HiTS and carefully validated foundation-model scenarios.
- **Risk:** EWMA/GARCH-family baselines, factor covariance, residual risk, drawdown and tail models.
- **Fundamentals:** transparent sector formulae first, learned residual models second.
- **Documents/events:** finance-specific rules and supervised extraction; LLM structured extraction with exact citations.
- **Portfolio construction:** 1/N, capped risk budgeting and maximum-diversification baselines before constrained optimisation.
- **Execution:** deterministic proposal and control services, never a predictive model.

##### Model originality and ensemble controls

- Estimate effective independent model breadth rather than counting all models equally.
- Detect near-clones through prediction correlation, residual correlation, rank overlap and error coincidence.
- Constrain ensemble weights and preserve family-level caps.
- Use a Model Confidence Set or comparable predeclared comparison only as one diagnostic, not as an automatic promotion rule.
- Keep separate ensembles for return, risk, data quality and event context.
- Preserve raw and calibrated predictions and every attempted/failed/pruned model.

##### Backtest and validation

- Reconstruct historical data as known at each decision time, including filing acceptance, provider revisions, delistings, index membership, corporate actions and exchange calendars.
- Use one production decision kernel for current, backtest and paper proposals.
- Use nested walk-forward folds, purging, embargo, issuer/share-class grouping and regional hold-outs.
- Record transaction cost, spread, impact, turnover, tax/FX and capacity assumptions as versioned inputs.
- Count all attempts in a research family; apply predeclared false-discovery and backtest-overfitting controls.
- Include negative controls: shuffled targets, lagged/future-feature canaries, random features, wrong-universe and deliberately impossible strategies.
- Use synthetic/adversarial data for invariant, stress and failure testing—not as evidence of investment alpha.
- Require paper/shadow evidence over a predeclared minimum number of independent decisions and matured horizons.

##### Controlled self-improvement

The system may automatically:

- refresh approved data and features;
- train bounded challengers within a frozen experiment budget;
- recalibrate supported prediction intervals;
- monitor drift, coverage and realised outcomes;
- generate shadow comparisons and promotion recommendations.

It may not automatically:

- rewrite source code or policy;
- change targets, data cut-offs, final test sets, cost assumptions or hard risk limits;
- grant itself a new asset, broker or execution authority;
- promote a model without a signed/reviewed release record;
- turn news or LLM output into direct order authority.

##### Performance and stability monitoring

Use two levels:

1. **Always-on local telemetry:** workflow stage, duration, rows, cache hit, memory, CPU/GPU mode, provider latency, warnings, error class and result hash.
2. **Opt-in deep profiling:** profilers and detailed traces only for diagnosis, with no default third-party telemetry.

Create regression gates for runtime, memory, first-start, page render, bulk throughput, provider failures and package/source parity. Monitoring itself may not alter financial results or transmit portfolio data externally by default.

##### Task-oriented navigation and progressive disclosure

Recommended navigation groups:

- Home / Decisions
- Analyse / Compare / Screener / Bulk Runs
- Portfolio / Performance / Risk / Income & Events / Rebalance
- Data / Providers / Filings / News & Context
- Forecast Lab / Training Centre / Backtests / Paper
- Broker / Orders / Reconciliation / Controls (only when installed/authorised)
- Audit / Diagnostics / Roadmap / Settings

Every analytical page has a global as-of bar showing portfolio snapshot, data cut-off, analysis/model/policy version, coverage, conflicts and stale state. Summary first; drivers, source lineage, model details and raw records expand progressively.

#### 8.5 Portfolio principles retained from the ZIP

The portfolio must provide two distinct but linked views:

1. **Legal/instrument view:** the ETFs, shares, bonds, cash and funds actually owned.
2. **Economic look-through view:** underlying securities, sectors, countries, currencies, factors and risks obtained through dated holdings and classification data.

Look-through is never assumed complete. Unknown holdings remain an `Unknown/Unmapped` bucket and are not distributed proportionally over known constituents. Direct, indirect and combined ownership must be selectable. Each aggregate metric declares whether it is summed, market-value weighted, duration weighted, recomputed from cash flows, percentile aggregated or unavailable.

#### 8.6 Lawful global source strategy

There is no single lawful, free, unrestricted source for complete global prices, fundamentals, historical constituents, ETF holdings, filings, news and fixed-income trades. Use a provider registry and a stable canonical input contract:

```text
ProviderAdapter
  → RawSnapshot
  → Identity/Conflict Resolution
  → Canonical Price/Fact/Document/Curve Schema
  → Data Quality
  → Feature Store
  → Existing Algorithms/Models
```

Provider additions do not require every model to be rewritten, but material source or market-distribution changes require drift, source-shift and calibration tests.

| Region | Source | Data type | Access | Coverage | Interface | PIT quality | Small/mid cap | Limits | Adapter | Priority | URL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Global | GLEIF API | Identity/ownership | Official, free | LEI entities and relationships | REST | High for as-published identity; history available | Indirect | Respect terms and caching | identity_gleif | P0 | https://www.gleif.org/en/lei-data/gleif-api/ |
| Global | OpenFIGI | Identifier mapping | Free tier | FIGI/ticker/exchange mappings | REST | Mapping service, not full PIT master | Broad | Rate limits; API key improves capacity | identity_openfigi | P0 | https://www.openfigi.com/api/documentation |
| Global | ISO 10383 MIC list | Exchange identity | Official, free download | Market identifier codes | File | Versioned reference data | Broad | Licence/redistribution review | ref_mic | P0 | https://www.iso20022.org/market-identifier-codes |
| Global/EU | filings.xbrl.org | ESEF filing index/API | Public | European and other XBRL filings indexed by the project | REST | Good source metadata; coverage varies by jurisdiction | Broad | Verify retention and fair-use terms | filings_xbrl_org | P0/P1 | https://filings.xbrl.org/docs/api |
| United States | SEC EDGAR data.sec.gov | Filings/XBRL | Official, free, no API key | 10-K, 10-Q, 8-K, 20-F, 40-F, 6-K and XBRL facts | REST + nightly bulk | High with acceptance timestamps and amendments | Excellent | 10 requests/s fair-access policy; identify user agent | sec_edgar | P0 | https://www.sec.gov/search-filings/edgar-application-programming-interfaces |
| United Kingdom | Companies House API | Filings/company registry | Official, free key | UK companies and filing history | REST | High for registry/filing events | Excellent | Rate limits; accounts may be PDF/iXBRL | uk_companies_house | P0/P1 | https://developer.company-information.service.gov.uk/ |
| United Kingdom | FCA National Storage Mechanism | Regulated disclosures | Official/public | Issuer regulated information | Web/search | Use publication timestamp and document hash | Broad listed | No undocumented high-rate scraping | fca_nsm | P1 | https://data.fca.org.uk/#/nsm/nationalstoragemechanism |
| European Union | National OAM/ESEF sources | Regulated disclosures | Official/public | Annual reports and regulated information | Country-specific | Potentially high; interfaces heterogeneous | Good including smaller issuers | Build per-country lawful adapters | eu_oam | P0/P1 | https://www.esma.europa.eu/issuer-disclosure/electronic-reporting |
| Japan | EDINET | Filings/XBRL | Official/public | Japanese statutory filings | API/download | High when document and submission dates retained | Excellent | Japanese taxonomy/language support | jp_edinet | P0/P1 | https://disclosure2.edinet-fsa.go.jp/ |
| South Korea | OpenDART | Filings/XBRL/company facts | Official/free key | Korean listed and reporting companies | REST | High with receipt/amendment dates | Excellent | Korean labels/taxonomy; rate limits | kr_opendart | P0/P1 | https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001 |
| Taiwan | TWSE/MOPS XBRL and announcements | Filings/announcements | Official/public | Taiwan issuers | Files/web | Good but interface and bulk history vary | Excellent | Terms and Chinese-language parsing | tw_mops | P1 | https://emops.twse.com.tw/ |
| Hong Kong | HKEXnews | Announcements/reports | Official/public | HK-listed issuers | Web/search | High publication timestamps | Excellent | Rate limits/terms; PDFs common | hk_hkexnews | P1 | https://www.hkexnews.hk/ |
| Singapore | SGX company announcements | Announcements/reports | Official/public | SGX-listed issuers | Web/search | High event timestamps | Excellent | Terms; PDFs and issuer naming | sg_sgx | P1 | https://www.sgx.com/securities/company-announcements |
| India | NSE corporate filings | Announcements/results | Official/public | NSE issuers | Web/download | Good when exchange timestamp retained | Excellent | Anti-bot/terms; use permitted downloads | in_nse | P1 | https://www.nseindia.com/companies-listing/corporate-filings-announcements |
| India | BSE corporate announcements | Announcements/results | Official/public | BSE issuers | Web/download | Good when timestamp retained | Excellent | Terms and duplicate NSE/BSE listings | in_bse | P1 | https://www.bseindia.com/corporates/ann.html |
| China | CNINFO / SSE / SZSE | Filings/announcements | Official/public | Mainland listed issuers | Web/API varies | Potentially high; language/taxonomy complexity | Excellent | Terms, access controls and Chinese parsing | cn_disclosures | P1/P2 | https://www.cninfo.com.cn/new/index |
| Australia | ASX announcements | Announcements/reports | Official/public | ASX issuers | Web/search | High publication timestamps | Excellent | Terms and document retention | au_asx | P1 | https://www.asx.com.au/markets/trade-our-cash-market/announcements |
| New Zealand | NZX announcements | Announcements/reports | Official/public | NZX issuers | Web/search | High event timestamps | Good | Terms and small universe | nz_nzx | P2 | https://www.nzx.com/announcements |
| Canada | SEDAR+ | Filings/issuer documents | Official/public | Canadian reporting issuers | Web/search | High if filing timestamp retained | Excellent | No assumption of an unrestricted bulk API | ca_sedar | P1/P2 | https://www.sedarplus.ca/ |
| Brazil | CVM Open Data | Filings/fund/company data | Official/open data | Brazilian regulated entities and filings | Bulk/API | Good with publication/version metadata | Good | Portuguese taxonomy and schema changes | br_cvm | P1 | https://dados.cvm.gov.br/ |
| South Africa | JSE SENS | Announcements | Official/public | JSE issuers | Web/search | High event timestamps | Good | Terms and archive access | za_sens | P2 | https://www.jse.co.za/sens |
| Nordic/Baltic | Nasdaq issuer messages | Announcements | Exchange/public | Nasdaq Nordic and Baltic issuers | Web/RSS varies | Good | Good | Terms and issuer mapping | nasdaq_nordic | P1/P2 | https://view.news.eu.nasdaq.com/ |
| Norway | NewsWeb / Oslo Børs | Announcements/reports | Exchange/public | Norwegian issuers including savings banks | Web/search | High event timestamps | Excellent | Terms; Norwegian language/entity mapping | no_newsweb | P1 | https://newsweb.no/ |
| Europe | Euronext issuer press releases | Announcements | Exchange/public | Euronext-listed issuers | Web/search | Good | Broad | Terms; duplicates with OAM/issuer sites | euronext_news | P1/P2 | https://live.euronext.com/en/listview/company-press-release |
| Global | FRED | Macro/rates | Official/public | US and selected international series | REST | Vintage support available for some workflows via ALFRED | N/A | API key and terms | macro_fred | P1 | https://fred.stlouisfed.org/docs/api/fred/ |
| Euro area | ECB Data Portal | Macro/rates/FX | Official/public | ECB statistical datasets | SDMX REST | High; preserve observation and release/vintage metadata where available | N/A | Rate limits and series revisions | macro_ecb | P1 | https://data.ecb.europa.eu/help/api/overview |
| European Union | Eurostat API | Macro/industry | Official/public | EU economic and demographic statistics | REST/SDMX | Release/revision handling required | N/A | Large cubes and revisions | macro_eurostat | P1/P2 | https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access |
| Global | BIS Data Portal | Rates/credit/FX/banking | Official/public | BIS statistics | API/download | Good; preserve release dates | N/A | Series revisions and units | macro_bis | P2 | https://data.bis.org/ |
| Global | World Bank Indicators API | Macro/development | Official/public | Country indicators | REST | Low frequency; revisions possible | N/A | Not a trading-frequency feed | macro_worldbank | P2 | https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation |
| Global | Stooq historical database | Prices | Free/public download | Many equities/indices/FX; coverage varies | Bulk files | Not authoritative; PIT/delisting coverage must be tested | Potentially useful | Verify terms, symbols and corporate actions | prices_stooq | P2 fallback | https://stooq.com/db/h/ |
| Global | Yahoo Finance via yfinance | Prices/metadata/convenience | Unofficial wrapper | Broad current coverage | HTTP wrapper | Useful but lower authority; history and metadata can change | Broad | Terms, fragility and no guarantee | prices_yfinance | Current backbone | https://ranaroussi.github.io/yfinance/ |

Fixed-income additions include official ECB curves, ESMA FIRDS/FITRS reference and liquidity files, FINRA fixed-income/TRACE public services where terms permit, issuer/regulator documents, and user/broker-imported observations. Each adapter is separately reviewed for current terms, rate limits, retention and redistribution.

#### 8.7 Automated news, filings and reported results

Recommended history:

- 24 months of news/context, with 90- and 180-day fast views;
- at least eight quarterly/interim reports;
- at least five annual reports;
- longer immutable raw retention where lawful;
- backtests use only records knowable at the decision cut-off.

The pipeline preserves publication, exchange-release, filing-acceptance, retrieval and knowledge times; content hashes; entity/timestamp confidence; amendments/restatements; parser/model/prompt version; and exact source spans. XBRL/iXBRL precedes HTML and PDF fallback. As-filed GAAP/IFRS, issuer-adjusted and analyst-adjusted numbers are never silently blended.

News is useful for event risk, contradiction detection, score-change explanation and labelled extraction data. Generic sentiment remains low authority because finance-language and direct-return evidence are heterogeneous. A direct-alpha news feature is an isolated research family with its own point-in-time, cost and multiple-testing gates.

#### 8.8 Provenance, leaks and grey sources

##### Authenticated incidents and grey-source assessment


| Entity/material | Record | Class | Confirmed | Not confirmed/licensed | Allowed use | Prohibited use | Evidence | URL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Two Sigma | SEC settlement, 16 January 2025 | B — regulator-confirmed incident | Known vulnerabilities, delayed remediation, unauthorised changes to >12 models, repayment and penalties. | No lawful public dump of the affected production code or complete model specifications was identified. | Derive model-change controls, immutable artefacts, dual approval, prediction-diff alerts, rollback and whistleblower-safe governance. | Do not seek, ingest, reproduce or emulate proprietary production models. | High for settled facts | https://www.sec.gov/newsroom/press-releases/2025-15 |
| Goldman Sachs / Aleynikov | Court records concerning copied source code | B — authenticated court record with legally complex outcomes | Court records establish copying/upload or possession allegations/facts addressed in litigation; outcomes differed under federal and New York statutes. | The records do not authorise reuse and do not make the code a public or licensed implementation source. | Derive least privilege, egress controls, repository classification, audit logging and clean-room boundaries. | Never use copied proprietary code, snippets or reverse-engineered strategy logic. | High for court record; none for investment utility | https://law.justia.com/cases/new-york/court-of-appeals/2018/47.html |
| MSCI / Axioma litigation | MSCI Inc. v Jacob | C — litigation allegations and discovery record | A public court decision confirms litigation and source-code discovery disputes. | It does not establish a final technical equivalence finding or provide a lawful implementation artefact. | Use only as a reminder to document independent development and provenance. | Do not use disputed code or infer proprietary factor formulae. | Moderate for litigation existence; Very low for technical inference | https://www.nycourts.gov/reporter/3dseries/2014/2014_06239.htm |
| BlackRock | Trend Spotter whistleblower lawsuit reported in 2024 | C — allegation, disputed | A lawsuit and BlackRock’s denial are publicly reported. | Claims about internal capabilities are unadjudicated and disputed. | At most, add a provenance note and avoid overclaiming monitoring capability. | Do not turn allegations into product requirements or factual model descriptions. | Very low for model inference | https://www.reuters.com/legal/blackrock-whistleblower-alleges-cover-up-search-engine-spot-chinese-investments-2024-05-20/ |
| Unattributed mirrored manuals, anonymous repositories, screenshots and paste sites | Unverified online material | D — exclude | None independently authenticated. | Authorship, completeness, currency, legality and tampering are unknown. | May generate a generic research question only after stripping proprietary detail and finding independent public support. | No code ingestion, no credentials, no source reproduction, no dependency, no claim of authenticity. | Very low |  |
| AXA Rosenberg (analogue, not requested company) | SEC coding-error settlement | B — regulator-confirmed control failure | Code error, delayed remediation and inadequate compliance integration are confirmed in a settlement. | No reusable investment formula is supplied. | Use as an external benchmark for release controls, compliance involvement and incident disclosure. | Do not infer current practices of unrelated firms. | High for controls lesson | https://www.sec.gov/news/press/2011/2011-37.htm |


##### Controls derived from authenticated incidents

- signed, immutable model and feature artefacts;
- two-person approval for champion changes;
- no direct editing of deployed model objects;
- least-privilege repository and data access;
- prediction-distribution diffs before release;
- clone/correlation alerts across models;
- automatic rollback to the last approved hash;
- tamper-evident session and experiment logs;
- explicit incident classification and disclosure workflow;
- compliance/risk participation in model changes;
- separate research, shadow and approved environments.

The allowed provenance classes are:

- **A — official/open/licensed:** implement according to licence and terms.
- **B — regulator- or court-authenticated incident:** use for controls/governance; never as a source of proprietary alpha logic.
- **C — plausible but disputed/unverified:** may create a generic, de-proprietised research hypothesis only after independent public support is found.
- **D — anonymous, mirrored, credential-bearing or unverifiable:** exclude.

No proprietary source code, credentials, model weights, unreleased data or copied internal documents are included. The confirmed incidents support signed artefacts, dual control, immutable logs, least privilege, prediction-difference monitoring, rollback and clean-room development.

#### 8.9 Performance, fixed-income and execution standards evidence

| Evidence | What it supports | Quality | Important limitation |
|---|---|---|---|
| CFA Institute GIPS standards/handbooks | TWR neutralises external flows; daily flows and linked sub-period returns; MWR/IRR; transaction-cost treatment | High for methodology | This application does not claim formal GIPS compliance. |
| FINRA and Investor.gov bond guidance | Clean bond-risk taxonomy; YTM/YTC/YTW assumptions; call, liquidity, credit and rate risk | High for definitions | Investor education, not forecast-skill evidence. |
| OpenGamma Strata and QuantLib | Reference implementations for accrued interest, clean/dirty price, yield, duration and convexity | Moderate–High for software behaviour | Pin versions, review licences and use differential tests; conventions/data still matter. |
| ECB yield curves | Official euro-area spot, forward and par curves and methodology | High for published data | Not an issuer-specific credit curve. |
| ESMA FIRDS/FITRS/liquidity data | EU instrument-reference and regulatory-liquidity inputs | High for as-published data | Completeness and revisions are explicitly limited. |
| MiFID II Article 17 and RTS 6 | Resilience, thresholds, controls, monitoring, reconciliation and shutdown expectations | High as legal text | Actual applicability depends on legal status and jurisdiction. |
| Broker API documentation | Order IDs, callbacks, missing/duplicate status behaviour and broker-specific states | High for the documented broker API | Version- and broker-specific; recorded fixtures remain necessary. |

#### 8.10 Bias and uncertainty controls

- **Publication/funnel bias:** record all attempted hypotheses and models.
- **Data snooping:** research-family IDs, locked final sets and multiplicity controls.
- **Commercial conflict:** vendor/manager claims can motivate a baseline or diagnostic, never close an issue.
- **Survivorship/look-ahead:** bitemporal sources, historical universes, delistings/defaults and accepted-at times.
- **Heterogeneity:** report by country, sector, cap/liquidity, rating/duration, asset and regime; shrink sparse estimates.
- **Costs/capacity:** bid–ask, impact, turnover, tax/FX, holding and liquidation costs.
- **Drift:** rolling monitoring, shadow challengers and retirement.
- **Complexity:** every complex model must beat or be non-inferior to a transparent baseline on untouched data and then survive forward evidence.

### 9. User-priority decision contract and remaining-gap reconciliation

This section is normative. It reconciles the user’s stated use case with the repository and the prior master specification. Where it conflicts with a portfolio- or execution-first interpretation, this section controls the release order while preserving all safety boundaries.

#### 9.1 Product purpose and release lanes

The application is built primarily for one private user who wants to analyse an instrument and screen thousands of candidates. It may generate an instrument-level report when another person asks for a check, but it is not a client-management, suitability or regulated-advice platform.

| Lane | Scope | First acceptable release | Must not imply |
|---|---|---|---|
| **Core Research** | individual analyser, compare, bulk, screener, forecasts, risk profiles, funds/bonds, selected currency, audit | can certify independently once its own P0 gates pass | portfolio completeness or execution authority |
| **Portfolio** | holdings, performance, exposure, what-if and optional import | separate later certification | personal suitability or tax advice |
| **Execution** | paper, read-only broker, drafts, supervised canary | only after prospective and operational gates | autonomous or unrestricted trading |

The release programme must prevent scope inversion: a blocked broker adapter cannot keep the private analyser permanently unreleasable, while a polished analyser cannot bypass paper, controls, settlement or legal gates.

#### 9.2 Exact horizons, training wall time and evidence maturity

The supported horizon enum is fixed initially to:

```text
1W, 1M, 3M, 6M, 9M, 2Y, 5Y
```

Three clocks are separate:

1. **Research/training wall time:** local compute used to construct historical labels, tune challengers and calibrate models. Bounded research campaigns may run over days, weeks or months without blocking ordinary app use.
2. **Production analysis time:** seconds to hours for applying frozen approved models to current data. It must fit the selected analysis-depth budget.
3. **Prospective outcome maturity:** elapsed real time before a frozen forecast can be judged. No amount of GPU training can mature a `5Y` outcome earlier than five years.

Historical `2Y` and `5Y` rolling labels allow immediate model development. Because adjacent multi-year labels overlap, the validation store must record the effective number of independent decision dates and use purging, embargo, block bootstrap or heteroskedasticity/autocorrelation-consistent inference. Long-horizon recommendations remain lower authority until prospective outcomes accumulate.

#### 9.3 Horizon-specific evidence and model routing

The same model family is not presumed optimal for every horizon or asset. The following is a routing hypothesis to validate, not an authority shortcut:

| Horizon | Stocks | ETFs/funds | Bonds | Default model emphasis |
|---|---|---|---|---|
| `1W` | price trend/reversal, volatility, liquidity, scheduled events, market regime | ETF market price/liquidity; ordinary funds only if NAV/dealing frequency supports it | curve/spread move and liquidity; coupon carry is small | deterministic baseline, robust short-history/risk models, guarded short-sequence models |
| `1M` | momentum/reversal, revisions/events, factor and regime | market/NAV trend, premium/discount for ETFs, flows/holdings where lawful | carry, rates, spread and liquidity | rankers plus distributional trees/econometric risk baselines |
| `3M` | quarterly fundamentals, guidance, valuation, momentum, events | benchmark exposure, tracking, fees, holdings change | carry/roll, curve and credit | core ensemble with calibration |
| `6M` | earnings/fundamental path, valuation normalisation, quality and trend | strategy/benchmark fit, fees, tracking, factor and macro exposure | carry/roll, rates, spread, default and FX | broader ensemble and scenarios |
| `9M` | business/fundamental and valuation change plus trend/regime | structural fund/ETF evidence and exposure | full deterministic return decomposition plus calibrated residual | broader ensemble, paper/forward tracking |
| `2Y` | profitability, growth, valuation, balance-sheet quality, industry and macro scenarios | fees, tracking, strategy persistence, holdings/factor exposure, closure risk | carry, reinvestment, rates, spread/default, FX | transparent long-horizon baseline plus constrained challengers |
| `5Y` | cash-flow/valuation scenarios, quality, capital allocation, structural risks | long-run costs, benchmark design, manager/strategy stability and exposure | contractual cash flows, duration, credit migration/default and reinvestment | scenario distributions and simple baselines; strongest uncertainty haircut |

A model can be champion for only a declared asset×task×horizon×coverage tier. Short-history foundation models, tree models, linear models and deterministic baselines are challengers, not assumed improvements.

#### 9.4 Peer hierarchy and score-layer separation

##### 9.4.1 Stock peers

Default point-in-time fallback order:

1. same business model/industry leaf + economic country or closely integrated region + size/liquidity bucket;
2. same industry leaf + broader region + size/liquidity bucket;
3. same industry leaf globally with country/region controls;
4. parent industry/sector regionally;
5. parent industry/sector globally;
6. metric unavailable when none has sufficient effective support.

Country means economic/operating exposure for peer economics, not merely the exchange suffix. Listing venue, legal domicile, reporting currency and revenue geography remain separate.

##### 9.4.2 ETF and ordinary-fund peers

Fund peers require compatible vehicle and economic mandate: ETF versus ordinary fund, active versus passive/index, asset class, benchmark/objective, region/country exposure, sector/theme, currency-hedging state, distribution policy, duration/rating for bond funds, share-class fee tier and dealing/liquidity class. A low-fee institutional share class is not directly compared with a high-fee retail share class without explicit fee adjustment.

##### 9.4.3 Bond peers

Use issuer type, sector/country, currency, seniority, secured status, rating, coupon type, maturity/duration and liquidity. Yield alone never determines attractiveness.

##### 9.4.4 Metric rules

Every metric registry entry declares applicability, direction, unit, period, transformation, peer key, minimum `n`, minimum effective `n`, shrinkage, winsorisation and fallback. Inapplicable data remain `N/A`; they are not zero-filled. The UI shows the exact cohort and why a fallback occurred.

#### 9.5 Five preset-but-editable risk profiles

Risk profiles are versioned **selection policies**, not alternative analyses. They can filter candidates and reweight common opportunity fields, but cannot edit raw facts, peer scores, model predictions, calibration or hard data-quality gates.

| Profile | Default intent | Relative risk envelope | Evidence/liquidity posture | Typical recommendation behaviour |
|---|---|---|---|---|
| **Safe** | capital preservation relative to risk assets | materially below horizon-matched VWCE downside/risk | highest evidence, liquidity and coverage requirements | readily abstains; favours cash, high-quality bonds or lower-risk diversified funds where supported |
| **Safe–Medium** | cautious growth | below VWCE risk, with positive net opportunity | high evidence; limited tail and concentration tolerance | accepts moderate upside only when downside is controlled |
| **Medium** | user-defined VWCE-like safety/upside | approximately the same joint horizon-matched risk and upside envelope as canonical VWCE | standard high-quality evidence and liquidity | candidate should justify replacing/adding to VWCE after costs and uncertainty |
| **Medium–Aggressive** | greater upside with bounded extra risk | above VWCE risk within versioned caps | can accept more volatility/drawdown, never weak evidence or illiquidity by default | stronger upside required for extra downside |
| **Aggressive** | high-risk long-only opportunities | materially above VWCE risk | still obeys absolute liquidity, data, uncertainty and product exclusions | no leverage/shorting; high uncertainty can still force `no_trade` |

Provisional policy bands may use ratios to a sealed VWCE snapshot—for example downside, expected shortfall, volatility, drawdown and loss probability—but they must be empirically calibrated and editable. Profile classification is horizon- and output-currency-specific: an instrument can be Medium at `5Y` and Aggressive at `1W`.

#### 9.6 Canonical VWCE anchor

The anchor is the Vanguard FTSE All-World UCITS ETF (USD) Accumulating share class identified by ISIN `IE00BK5BQT80`, not a ticker string. The same share class has multiple listings and trading currencies, so identity resolution must map listings to one economic share class and then apply the user-selected output currency.

The anchor snapshot stores:

```text
fund/share-class identity and ISIN
benchmark and replication method
listing used for price observation
NAV/market-price source and as-of time
output currency and FX snapshot
horizon-matched return/risk distribution
fees, spread and tax-excluded cost assumptions
current official product risk indicator as versioned reference only
coverage and source hashes
```

`Medium` means “VWCE-like according to this application’s versioned horizon-matched risk/upside policy.” It does **not** mean that a regulator, Vanguard or a PRIIPs indicator labels VWCE “medium”, and the current official product risk indicator must never be hard-coded because product documents can change. If a candidate does not improve expected utility after costs and uncertainty, `hold VWCE`, `cash`, or `no_trade` is a valid result.

#### 9.7 Selected-currency and FX contract

All monetary outputs—prices, expected gain/loss, costs, income, portfolio values and chart amounts—use the selected output currency. Percentages show both local-asset and selected-currency returns when FX is material.

##### Source hierarchy

1. official central-bank/monetary-authority reference series with point-in-time metadata;
2. another approved official public source;
3. a lower-authority market-data fallback with explicit warning;
4. manual import;
5. unavailable.

The ECB publishes daily reference rates for a broad currency set but explicitly treats them as information/reference data rather than transaction prices. Therefore the app may use them for valuation and benchmark conversion, not as proof of an executable FX fill. Bank of Canada Valet and other official central-bank services can extend/reconcile coverage. Cross rates must be derived through a declared base and quote convention with triangular-consistency tests.

##### Forecast semantics

For a foreign-currency instrument, selected-currency return is a joint asset-and-FX outcome. The forecast layer must preserve dependence between local asset return and FX; a future asset distribution cannot simply be multiplied by today’s spot rate. Hedged share classes require hedge index, reset frequency, hedge ratio, cost and residual currency risk.

#### 9.8 Ordinary funds as a first-class asset family

##### 9.8.1 Why ETF logic is insufficient

Ordinary mutual/index funds generally transact at a net asset value calculated at the dealing point, often once per business day. ETFs trade intraday at market prices that may differ from NAV. Accordingly:

- ordinary funds have dealing cut-offs, forward-pricing/NAV timing, settlement and possible entry/exit/dilution fees rather than an exchange spread/order book;
- ETF premium/discount, intraday liquidity and exchange venue are inapplicable to an ordinary fund;
- a weekly, monthly or gated-dealing fund may not support `1W` forecasting or a normal liquidity recommendation;
- fund umbrella, compartment/sub-fund and share class must be separate identities;
- accumulating/distributing and hedged/unhedged share classes can have different cash flows, costs and return paths.

##### 9.8.2 Required fund evidence

At minimum, where available:

```text
vehicle / umbrella / sub-fund / share-class identity
ISIN and local identifiers
manager, management company, depositary and domicile
authorised/registered/closed/merged/liquidating state
active/passive/index mandate and benchmark
asset, region/country, sector/theme and currency exposure
base, share-class, dealing and hedging currencies
accumulation/distribution policy
NAV frequency, dealing frequency, cut-off, settlement, notice and minimums
ongoing charges, management fee, performance fee, entry/exit/dilution charges
prospectus, KID/product highlights, annual and half-yearly reports
holdings date, coverage, turnover and derivatives/leverage flags
fund size, flows where lawful, inception, manager/strategy changes
tracking difference/error for index funds
securities-lending/collateral evidence where disclosed
fund-of-funds/master-feeder links and stacked fees
```

##### 9.8.3 Free-data reality

There is no single free, lawful, unrestricted global NAV/holdings/fundamentals feed. The architecture therefore uses coverage tiers:

- **Tier A:** official structured/bulk data, such as SEC Form N-PORT/N-CEN for US registered funds;
- **Tier B:** official registers and disclosure documents, such as UCITS/ESMA/national OAM records, EDINET, SFC, MAS, ASIC, SEDAR+ and AMFI;
- **Tier C:** issuer/fund-manager documents and lawful downloads;
- **Tier D:** user imports;
- **Tier E:** convenience vendors such as yfinance, clearly lower authority and never assumed complete.

A fund with insufficient NAV history, documents, fees, benchmark or holdings is excluded or downgraded; the app does not manufacture a complete global fund database.

##### 9.8.4 Fund-specific bias controls

- include closed, merged and liquidated funds where historical evidence exists;
- distinguish backfilled/incubated pre-public returns from investable public history;
- deduplicate share classes without erasing class-specific costs/currencies;
- record manager, mandate and benchmark changes;
- compare active funds after fees and appropriate factor/benchmark exposures;
- do not infer persistent skill from recent ranking alone;
- require minimum public history and decision dates before recommendation authority.

#### 9.9 Top-*N* selection matrix

Each saved selection run can produce the following independent views:

| Dimension | Required views |
|---|---|
| Asset | stocks, ETFs, ordinary funds, bonds; optional common-metric cross-asset portfolio-fit |
| Scope | total eligible universe |
| Sector | every sufficiently supported sector/industry or fund sector mandate |
| Country | every sufficiently supported economic country/region or fund exposure mandate |
| Country×sector | every sufficiently supported intersection |
| Risk profile | Safe, Safe–Medium, Medium, Medium–Aggressive, Aggressive |
| Horizon | 1W, 1M, 3M, 6M, 9M, 2Y, 5Y |
| Analysis depth | Quick, Medium, High, Full run lineage; results are not mixed silently |

Rules:

- `N` is configurable globally and per view;
- hard eligibility precedes ranking;
- groups below minimum `n`/effective `n` show unavailable or a declared parent fallback, never a misleading “winner” from two names;
- stocks use economic/business context; diversified funds use declared mandate/benchmark and look-through thresholds, with `multi-country`/`multi-sector` categories where appropriate;
- a fund/ETF may appear in multiple discovery filters but has one declared peer cohort per metric;
- results include rank interval, selection probability, stability across seeds/bootstraps and why-selected/why-not;
- selection policies and group definitions are versioned and exported.

#### 9.10 Quick, Medium, High and Full analysis-depth profiles

Analysis depth is separate from the machine’s low/standard/high hardware profile. Hardware determines available resources; depth determines approved evidence/model breadth. A weaker machine can run every semantic mode through smaller batches, more time and CPU fallbacks, but safety gates and formulas remain identical.

##### Reference benchmark

Provisional service-level objectives are measured on a declared warm-cache fixture of **3,000 supported instruments** on the user’s reference machine: approximately 20 CPU cores, 32 GB RAM and an RTX 5070. Cold provider acquisition is timed separately because official rate limits and outages are outside local-compute control.

| Depth | Intended use | Mandatory content | Optional expansion | Provisional reference SLO |
|---|---|---|---|---|
| **Quick** | rapid shortlist / repeated exploration | cached identity/prices, critical data gates, basic asset-specific facts, peer statistics, deterministic/simple forecast baseline, core risk/cost, selected horizon | no broad document refresh; only already-cached optional models | ≤5 minutes for the reference fixture and one selected horizon |
| **Medium** | default decision-quality run | full core facts/documents already due, peer/benchmark evidence, core approved ensemble, calibration, uncertainty, profile ranking | bounded document/context refresh and core scenarios | ≤30 minutes for the reference fixture and one selected horizon |
| **High** | deeper due diligence | broader documents/features, approved model families, stronger bootstrap/stability/scenario checks, source reconciliation | additional seeds/challengers when supported | ≤60 minutes for the reference fixture and one selected horizon |
| **Full** | overnight research/certification | every approved lawful source, all supported horizons, all approved model families, repeated robustness, clone checks, calibration, coverage/bias and audit replay | no unapproved experimental model and no hidden source | ≤10 hours for the declared full reference fixture |

These are release targets, not fabricated promises. Certification stores measured p50/p95 time, cache state, instrument count, supported count, horizons, CPU/GPU use, memory, disk, provider waits and model omissions. If a target cannot be met without dropping mandatory evidence, the profile fails certification; it must not silently masquerade as a shallower mode.

Production runs use frozen champions. Training/HPO belongs to separately scheduled Training Centre jobs and may run beyond a single analysis SLO. An upgrade from Quick to Full creates a new immutable analysis run linked to the earlier run.

#### 9.11 Provider and API-key centre

Settings must expose a dedicated **Data Providers & API Keys** section. Each adapter declares:

```text
provider_id and authority
coverage and purpose
key_required / key_optional / no_key
signup/documentation link
secret storage reference, never plaintext value
last bounded probe and result
rate limit, request size and reset/quota state
terms/licence/retention approval
cache/bulk-download support
redacted error and fallback state
```

Examples include FRED (key required), EDINET (key required), OpenFIGI (optional key materially increases mapping throughput), Companies House (free key), OpenDART (authentication key), and SEC/Bank of Canada/ECB services that do not use a normal API key but still require fair-access policy and a compliant user agent where applicable.

On Windows, secrets should use an approved operating-system-protected store such as DPAPI/Credential Manager. They never appear in YAML, logs, screenshots, clipboard history, diagnostic bundles, audit packets or crash reports. “Test” performs one bounded non-financial capability probe. Missing keys disable only the relevant optional adapter; normal local startup remains safe.

#### 9.12 Private self-research and guest-analysis boundary

Default mode is `SELF_RESEARCH`. A limited `GUEST_INSTRUMENT_CHECK` may generate the same generic instrument evidence and risk-profile views, but it must not:

- collect or infer another person’s income, wealth, losses they can bear, objectives or personal risk tolerance;
- state that an instrument is suitable for that individual;
- create a client record, managed portfolio or personalised allocation;
- accept payment, advertise advisory services or publish a signal service without a separately approved legal/business scope;
- hide the user’s ownership or conflict where a recommendation is distributed publicly.

A disclaimer alone is not treated as sufficient if the actual workflow becomes personalised advice. Shared exports identify facts versus estimates/opinions, timestamp, horizon, methodology, source quality, conflicts and limitations. Legal review determines whether any future public distribution is an investment recommendation and which transparency rules apply.

#### 9.13 Success and benchmark-outperformance evidence

“Works” has four distinct meanings:

1. **Forecast quality:** quantile loss, continuous ranked probability score (CRPS), log score where appropriate, Brier score, calibration/coverage, interval width and tail loss.
2. **Ranking quality:** rank information coefficient, NDCG/precision@*N*, top-*N* overlap, turnover, stability and coverage.
3. **Decision outcome:** net total return, drawdown, expected shortfall, hit/payoff decomposition, probability of beating cash, asset benchmark and VWCE, and abstention performance.
4. **Operational quality:** reproducibility, runtime, resource use, provider failure recovery and source/package parity.

Comparisons use untouched point-in-time outer folds and prospective frozen decisions. Diebold–Mariano-type tests are suitable for non-nested forecast comparisons under declared loss functions; Clark–West-type adjustments can be used when a larger model nests a baseline. Multi-step overlapping outcomes require block/HAC inference and an effective-decision denominator. Statistical significance is never the sole gate: effect size, costs, capacity, calibration, heterogeneity and multiple-testing adjustment are reported.

The evidence literature is deliberately contradictory. Broad equity-premium predictors have often failed out of sample, while constrained models and forecast combinations sometimes report gains. Therefore the app retains historical-average, VWCE, cash, simple factor and prediction-free baselines and may conclude that no complex model has earned promotion.

#### 9.14 Tax scope

The user does not require tax advice. The core release therefore:

- does not optimise Dutch or other jurisdictional tax;
- does not estimate personal tax liability or claim after-tax suitability;
- may preserve imported tax, withholding or fee cash entries for accurate accounting;
- labels any optional generic tax field as user-supplied/estimate and keeps it outside recommendation authority;
- removes tax-lot optimisation from P0 analysis/screening dependencies unless separately re-approved.

#### 9.15 Remaining-gap routing matrix

| Gap | Severity for stated use | Owning action |
|---|---|---|
| Ordinary funds are import-only in the prior capability matrix | P0 blocker | new `ISSUE-0170`–`0172`; amend identity, ETF/fund and screener owners |
| Fund umbrella/sub-fund/share-class duplication | P0 blocker | `0170`, `0082`, `0083` |
| NAV/dealing rules are conflated with ETF market pricing | P0 blocker | `0170`, `0172`, `0085`, `0128` |
| Fund closure/merger/incubation history | P0 evidence blocker | `0170`–`0172`, `0126`, `0150` |
| Selected output currency is not product-wide | P0 blocker | new `0173`; amend `0084`, `0088`, `0108`, `0136`–`0140` |
| FX reference versus executable quote is unspecified | P0 truth blocker | `0173`, `0128`, `0149` |
| Hedged share-class semantics are missing | P0 fund/FX blocker | `0170`, `0172`, `0173` |
| Exact horizon enum is absent | P0 contract blocker | amend `0108`, `0119`, `0136`, `0165` |
| Training time is confused with forecast maturity | P0 trust blocker | amend `0117`, `0119`, `0120`, `0124` |
| Multi-year overlap/effective sample is not explicit | P0 validation blocker | amend `0120`, `0123`, `0150` |
| Risk-profile policies are absent | P0 UX/decision blocker | new `0174`; amend score/screener/UI owners |
| VWCE anchor may be ticker- or label-dependent | P0 identity blocker | `0174`, `0082`, `0112` |
| Peer metrics and final benchmark opportunity can be conflated | P0 semantic blocker | amend `0074`, `0098`, `0112` |
| Country/sector/country×sector top-*N* views are absent | P0 feature blocker | amend `0020`, `0166`, `0138` |
| Sparse-group top-*N* rules are incomplete | P0 statistical blocker | amend `0098`, `0120`, `0166` |
| Analysis depth is absent | P0 runtime/UX blocker | new `0175`; amend jobs/performance/hardware owners |
| Hardware and workload profile are conflated | P0 reliability blocker | `0175`, `0151` |
| Cold acquisition and warm analysis time are conflated | P0 measurement blocker | `0175`, `0081`, `0165` |
| API keys lack one secure settings centre | P0 data-access blocker | new `0176`; amend `0037`, `0144`–`0146` |
| Free global data completeness is implicitly overclaimed | P0 truth blocker | amend `0080`, `0150`, provider children |
| Core release can be held hostage by portfolio/trading scope | P0 programme blocker | amend `0070`, `0152` |
| Recommendation efficacy versus VWCE/cash is incomplete | P0 evidence blocker | amend `0057`, `0120`, `0129`, `0152` |
| Guest checks can drift into personal advice | P1 legal blocker | amend `0149`, `0138`, export/audit owners |
| Tax work is over-scoped relative to user need | P1 scope correction | amend `0114`, `0127`, `0159`; retain accounting only |
| Long-only rejection is not repeated across every path | P0 safety blocker | amend `0008`, `0070`, `0130`, `0166` |
| Profile/currency/depth parity is untested | P0 release blocker | amend `0169`, `0142`, `0152` |

#### 9.16 Primary-source checkpoints retained verbatim

The following short source phrases are retained to constrain implementation claims:

- SEC Form N-PORT: “monthly portfolio holdings”.
- Investor.gov on mutual funds: “NAV is typically calculated at the end of each business day”.
- ECB FX rates: “published for information purposes only”.
- AFM on unlicensed personal advice: “a disclaimer … is not enough”.

They support data/product/legal mechanics only; they do not prove forecast skill.

## Part VII — Amend existing canonical issues

These are issue-body deltas, not duplicate issues. Before implementation, Codex must read the full current owning issue and merge this delta with all existing acceptance criteria.

### A. Programme, common analysis and data platform

#### AMEND `ISSUE-0070` — Freeze final product scope, completion contract and staged execution authority

**Priority / size:** P0 / M  
**Why:** The product scope now explicitly includes fixed income, ledger-derived portfolio performance, bulk top-*N* and an eventual bot. Scope must expand without enabling execution.

**Required delta**

- Add the asset-capability matrix in Part 4 and the six execution modes in Part 7.
- Separate capability state from execution authority; store authority by broker, account, asset, strategy, venue and horizon.
- Make `AnalysisSnapshot` the required shared analytical contract.
- Define certification by capability rather than one global “complete” flag.
- Keep normal startup and default configuration execution-disabled.

**Deliverables:** versioned scope/authority policy; Roadmap/System Map UI; authority export.  
**Acceptance:** unsupported assets are rejected explicitly; “implemented” cannot be displayed as “authorised”; all forbidden state transitions fail.  
**Tests:** policy migration; table-driven authority transitions; UI/export parity.  
**Boundary:** do not implement broker writes in this issue.

#### AMEND `ISSUE-0008` — Strategy taxonomy and scope/rejection matrix

**Priority / size:** P1 / S  
**Why:** Every asset/strategy represented by “etc.” needs an explicit support state so no unknown type enters an equity fallback.

**Required delta**

- Add stocks, ETFs, bond ETFs, fixed/zero/floating/inflation-linked/callable bonds, cash/FX and non-exchange funds.
- Add analyse, portfolio, backtest, paper, draft-order, canary and bounded-automatic columns.
- Add required data, model, liquidity, broker and legal prerequisites for each cell.
- Preserve explicit rejection/research-only treatment for autonomous LLM trading, RL agents, martingale/grid, unsupported derivatives, leverage, shorts and grey-source methods.

**Deliverables:** machine-readable matrix, UI and deterministic reason codes.  
**Acceptance:** every imported instrument resolves to one capability state; unsupported types never reach a model/strategy silently.  
**Tests:** capability table fixtures; unknown CFI/asset rejection; audit-export coverage.

#### AMEND `ISSUE-0074` — Canonical score engine v3

**Priority / size:** P0 / M  
**Why:** The user’s central requirement is one data/calculation path across analyser, screener, bulk, portfolio and execution.

**Required delta**

- Implement or extend the Part 3.2 `AnalysisSnapshot` schema.
- Separate asset-specific evidence components from common probabilistic outputs.
- Forbid direct cross-asset comparison of raw component or x/10 scores.
- Persist gross/net forecast distributions, evidence quality, peer/benchmark, costs, blockers and action.
- Include formula, feature, model, calibration and policy versions plus source/universe hashes.
- Provide read APIs/projections; presentation layers cannot run scoring logic.

**Deliverables:** versioned store/API; schema migration; snapshot resolver.  
**Acceptance:** same `analysis_run_id` gives byte-equivalent canonical values in every workflow; history survives schema upgrades.  
**Tests:** golden snapshots; cross-surface parity; metamorphic formatting test.

#### AMEND `ISSUE-0081` — Resumable bulk downloader, content-addressed cache and delta updater

**Priority / size:** P0 / M  
**Why:** Thousands of instruments require durable rate-limited ingestion rather than a synchronous loop.

**Required delta**

- Add universe-run manifests, shard checkpoints and provider quota state.
- Freeze provider/data cut-off and content hashes at run start.
- Support cancel/resume/retry without changing completed artefacts.
- Persist provider status, latency, bytes, rows, error class and coverage per instrument.
- Add low/standard/high resource profiles and disk/cache budgets.

**Deliverables:** bulk-ingestion run store, progress/diagnostics UI and failure export.  
**Acceptance:** a killed 1,000-instrument fixture resumes without refetching complete objects; one provider failure does not discard other results.  
**Tests:** failure injection, throttle, hash dedupe, resume and resource-limit tests.

#### AMEND `ISSUE-0018` — Watchlist and universe manager

**Priority / size:** P0/P1 / M  
**Why:** The app needs a safe path from pasted identifiers or files to a frozen, auditable universe.

**Required delta**

- Add CSV, XLSX, paste and provider-universe imports with dry-run validation.
- Accept canonical ID, ISIN, ticker+MIC and provider symbol; ticker alone stays ambiguous where necessary.
- Show duplicates, secondary lines, unsupported assets, inactive/delisted names and mapping confidence.
- Save versioned universes, exclusions, requested horizons and per-asset quotas.
- Allow correction overlays without deleting source input.

**Deliverables:** import wizard, universe manifest and resolution report.  
**Acceptance:** ambiguous identities require resolution or exclusion; frozen universe is reproducible/exportable; large imports remain cancellable/resumable.  
**Tests:** encoding/file fixtures; duplicate/share-class ambiguity; UI cancel/resume.

#### AMEND `ISSUE-0020` — Screener and filter system

**Priority / size:** P0/P1 / M  
**Why:** The screener must be the canonical top-*N* surface, not an alternative scoring path.

**Required delta**

- Apply absolute identity/data/corporate-action/history/liquidity/conflict gates before percentiles.
- Persist eligible, rejected, unavailable and failed rows with reason codes.
- Add 90th/95th percentile views, CI95, selection probability, Kendall tau-b, top-*k* overlap and net edge.
- Add deterministic tie-breaking, asset-specific quotas and saved run/filter views.
- Link each row to the stored `AnalysisSnapshot`.

**Deliverables:** exclusion funnel, result table, run history and full export.  
**Acceptance:** high raw score cannot bypass a hard gate; reload reproduces top-*N*; filters do not recalculate model output.  
**Tests:** deterministic ranking; bootstrap stability; detail/bulk parity.

#### AMEND `ISSUE-0082` — Global entity, instrument, fund, share-class and listing identity master

**Priority / size:** P0 / M  
**Why:** Debt securities require issuer/series/security identity distinct from stock listings; portfolios need identity continuity through symbol changes and corporate actions.

**Required delta**

- Extend identity to debt issue/series, issuer and guarantor LEI, ISIN, CFI, currency, venue/quotation and settlement identifier.
- Distinguish issuer, guarantor, security, listing/quotation and broker contract.
- Support fund/share-class/listing and debt-security/quotation hierarchies in one master.
- Preserve valid time, knowledge time, source priority and conflicts.

**Deliverables:** identity-v2 store, lineage/conflict UI and migration.  
**Acceptance:** multiple securities from one issuer never collapse; historical ticker/ISIN/broker-contract changes replay; critical conflicts block routing.  
**Tests:** multi-listing stock, ETF share-class and multiple-bond-series fixtures.

#### AMEND `ISSUE-0083` — Automatic asset, sector, industry and strategy classification with confidence

**Priority / size:** P0 / M  
**Why:** Peer/model/portfolio routing must use economic context rather than suffix or one vendor field.

**Required delta**

- Add fixed-income type, issuer sector, sovereign/corporate, seniority, secured status, coupon type, rating bucket, maturity and duration bucket.
- Keep regulatory/operating country, listing country, asset/revenue geography and currencies separate.
- Use official/rule evidence first; ML/LLM assistance requires source citation/confidence.
- Store multi-label context, fallback path and version.

**Deliverables:** `InstrumentContext` v2 and confidence/fallback UI.  
**Acceptance:** low-confidence leaf classification falls back; bond ETF remains an ETF with bond look-through; classification is point-in-time.  
**Tests:** asset/sector route table; confidence thresholds; historical replay.

#### AMEND `ISSUE-0084` — Corporate actions, total return and currency-normalisation services

**Priority / size:** P0 / M  
**Why:** Portfolio returns and debt analytics fail without complete cash flows, actions and point-in-time FX.

**Required delta**

- Add bond coupons, accrued settlement, principal redemption, calls/puts, amortisation, tenders/exchanges, defaults and recoveries.
- Classify dividends, coupons, distributions and interest as investment income, not external flow.
- Add announced/effective/ex/payable/known-at timestamps and revision lineage.
- Add transaction-date and valuation-date FX with separate FX attribution.

**Deliverables:** corporate-action/cash-flow stores and reconciliation report.  
**Acceptance:** security cash flows reconcile to ledger and total return; corrections do not overwrite as-known history; FX and income can be separated from price return.  
**Tests:** split/dividend/coupon/redemption/call/default and FX fixtures.

#### AMEND `ISSUE-0085` — Exchange calendars, sessions, holidays, auctions and market-state service

**Priority / size:** P0/P1 / M  
**Why:** Forecast cut-offs, valuations, settlement and order eligibility require exact market clocks.

**Required delta**

- Add settlement calendars, coupon/ex dates, business-day adjustments and day-count registry.
- Distinguish valuation date, decision time, trade date, settlement date and knowledge cut-off.
- Supply market-state, auction and early-close flags to data and execution gates.
- Version timezone/calendar sources and corrections.

**Deliverables:** calendar/session/day-count API and diagnostics.  
**Acceptance:** no holiday price is silently fresh; bond schedules use declared convention; execution cannot submit outside certified state.  
**Tests:** cross-market holidays, DST/timezones, day-count/business-day golden fixtures.

#### AMEND `ISSUE-0086` — User, broker and exchange historical price, position and transaction imports

**Priority / size:** P0 / M  
**Why:** A trustworthy portfolio cannot begin from manually typed current quantities alone.

**Required delta**

- Import accounts, cash, transactions, transfers, fees, taxes, FX, lots, income and corporate actions.
- Support broker CSV and canonical CSV/XLSX templates with dry-run staging.
- Add bond face/notional, clean price, accrued interest and settlement cash.
- Detect duplicates/corrections by source ID and content hash.
- Map every row through the identity master and quarantine ambiguities.

**Deliverables:** staging store, mapping/reconciliation UI, rollback and canonical export.  
**Acceptance:** imports are idempotent; unbalanced/ambiguous rows remain quarantined; history rebuilds holdings/cash from zero.  
**Tests:** broker-format golden fixtures, duplicates/corrections, round-trip export/import.

#### AMEND `ISSUE-0088` — Versioned macro, factor, risk-free and benchmark data warehouse

**Priority / size:** P0/P1 / M  
**Why:** Expected returns, cash comparisons and debt risk need horizon-matched cash rates, curves, inflation and credit context.

**Required delta**

- Add official spot, par and forward yield-curve snapshots plus interpolation policy.
- Add risk-free/cash proxies by currency and horizon.
- Add sovereign, aggregate, corporate, high-yield and duration benchmark metadata where lawful.
- Preserve release/vintage time, units, revisions and methodology.
- Keep issuer-specific credit curves explicitly unavailable where unsupported.

**Deliverables:** curve/benchmark warehouse and coverage UI.  
**Acceptance:** historical runs see only then-known vintages; fallbacks are visible; benchmark changes create versions.  
**Tests:** curve interpolation, negative rates, vintage replay and mapping fixtures.

#### AMEND `ISSUE-0089` — Data anomaly detection, quarantine and cross-source reconciliation

**Priority / size:** P0 / M  
**Why:** Multi-asset support introduces unit, quotation, schedule and stale-price failure modes that models cannot repair.

**Required delta**

- Add clean/dirty price, par/percentage, accrued, coupon, notional, yield and day-count consistency rules.
- Define asset/liquidity-specific cross-source tolerances.
- Quarantine impossible schedules, unsupported negative quantities, stale matrix prices and unbalanced holdings.
- Monitor provider schema/coverage drift and preserve corrections as new evidence.

**Deliverables:** anomaly ledger, quarantine/remediation UI and quality-rule registry.  
**Acceptance:** critical anomalies block calculation/proposal; original evidence survives correction; every rule declares units/severity.  
**Tests:** unit-scaling properties, conflicts and stale/illiquid debt fixtures.

#### AMEND `ISSUE-0098` — Stock sector-adapter and peer-cohort framework

**Priority / size:** P0 / M  
**Why:** The peer service must be reusable by stocks, ETFs and bonds while preserving asset-specific metric semantics.

**Required delta**

- Implement point-in-time leaf-to-parent cohorts and effective sample size.
- Use median/MAD, weighted empirical CDF, versioned winsorisation and hierarchical shrinkage.
- Expose members, exclusions, support, coverage, fallback and bootstrap interval.
- Add a registration interface for fixed-income cohort keys.
- Keep regulatory/economic country and listing venue distinct.

**Deliverables:** peer cohort/metric stores and drill-down UI.  
**Acceptance:** sparse cohorts fall back deterministically; a frozen universe reproduces statistics; inapplicable metrics stay N/A.  
**Tests:** fallback fixtures, survivorship/share-class controls and seeded bootstrap replay.

#### AMEND `ISSUE-0099`–`ISSUE-0102` — Sector-specific stock adapters

**Priority / size:** P0/P1 / one M slice per child issue  
**Why:** Portfolio and screener comparison is credible only when metric meaning follows the business model.

**Required delta**

- Financials: capital, asset quality, funding, CET1/ROTE/NIM, insurer combined ratio/solvency and regulatory context.
- REIT/utilities/infrastructure: FFO/AFFO, NAV, LTV, occupancy, RAB and regulated-return context.
- Cyclicals: commodity/cost curve, reserves, inventory, capex and cycle context.
- Software/semis/healthcare/biotech: recurring revenue/retention, R&D/SBC, cash runway, trials and event risk.
- Each child defines units, direction, period, missing policy, country/business-model variants and parent fallback.

**Deliverables:** one adapter, formula registry, UI rationale and fixture pack per child issue.  
**Acceptance:** no semantically invalid generic P/E/leverage fallback; adapters cannot bypass global risk/evidence gates.  
**Tests:** golden companies, wrong-sector rejection, accounting-unit and missing-data tests.  
**Boundary:** do not implement all children in one PR.

#### AMEND `ISSUE-0112` — Canonical benchmarks, peer sets, cash proxies and reference portfolios

**Priority / size:** P0 / M  
**Why:** Every return, score and portfolio chart needs a defensible comparison object aligned by horizon and currency.

**Required delta**

- Add benchmark hierarchy by asset, exposure, country/region, sector, duration, rating and currency.
- Add cash/risk-free proxies and 1/N/maximum-diversification reference portfolios.
- Version benchmark constituents and methodology.
- Define deterministic fallback and no-benchmark states.

**Deliverables:** registry, mapping API and comparison UI.  
**Acceptance:** no arbitrary first instrument becomes benchmark; benchmark/cash use matching dates/FX; changes create versions.  
**Tests:** mapping/fallback, currency/horizon alignment and historical-constituent replay.

### B. Training, validation and forecasts

#### AMEND `ISSUE-0117` — Local Training Centre, experiment tracker and model registry

**Priority / size:** P0 / M  
**Why:** The Training Centre must govern separate tasks/horizons rather than expose one generic self-optimising button.

**Required delta**

- Separate deterministic policy, statistical/ML weights and calibration lanes.
- Record frozen hypothesis, economic rationale, data/universe/feature/target snapshots, folds, cost policy, HPO budget, attempts, seeds and hashes.
- Register asset, task, horizon, hardware mode and model/checkpoint licence.
- Add manual promotion, amendment, shadow, rollback and retirement records.
- Never permit the trainer to change targets, final tests, hard limits or execution authority.

**Deliverables:** experiment/model stores, run comparison UI and signed manifest.  
**Acceptance:** every promoted model is reproducible; failed/pruned trials remain counted; immutable fields cannot be mutated.  
**Tests:** experiment replay, forbidden-field tests, registry migration/rollback.

#### AMEND `ISSUE-0119` — Leakage-safe feature store and target/label registry

**Priority / size:** P0 / M  
**Why:** Stocks, ETFs and bonds have different information clocks and label maturity.

**Required delta**

- Define asset/task/horizon targets and matured/pending/invalid state.
- Add issuer/share-class/security grouping and debt cash-flow/curve features.
- Preserve as-published/as-restated facts, delistings, defaults and inactive names.
- Record source-shift, missingness and exact knowledge time.
- Prevent one asset’s inapplicable feature from being zero-filled as meaningful.

**Deliverables:** stores, hashes, lineage and leakage diagnostics.  
**Acceptance:** future facts/schedule corrections cannot alter prior snapshots; labels mature only after full horizon.  
**Tests:** future-fact injection, default/delisting and target-maturity fixtures.

#### AMEND `ISSUE-0120` — Walk-forward, nested, purged and embargoed validation with multiple-testing control

**Priority / size:** P0 / M  
**Why:** Large-universe, multi-market and multi-horizon research magnifies dependence, leakage and selection bias.

**Required delta**

- Add research-family ledger and all attempted, failed and pruned trials.
- Use outer point-in-time walk-forward folds, inner HPO, purging/embargo and issuer/share-class grouping.
- Add block-bootstrap CI, negative controls, leakage canaries, locked final set, DSR/PBO and predeclared FDR/Reality-Check/SPA-style diagnostics.
- Report by asset, country, sector, cap/liquidity, rating/duration and regime.
- Report abstention/coverage and minimum detectable improvement.

**Deliverables:** fold manifests, validation store, model cards and research-attempt ledger.  
**Acceptance:** outer test inaccessible to features/HPO; every trial counted; baseline/cost/calibration/multiplicity failure blocks promotion.  
**Tests:** adversarial leakage, fold-overlap assertions and seeded multiplicity/bootstrap fixtures.

#### AMEND `ISSUE-0121` — Baseline and challenger model zoo

**Priority / size:** P0/P1 / M  
**Why:** One model must not rank securities, forecast paths, estimate covariance and parse documents.

**Required delta**

- Preserve historical/linear/robust and prediction-free portfolio baselines.
- Use rankers for cross-section, distribution models for returns, econometric baselines for risk and classifiers for documents.
- Register LightGBM, CatBoost, TabM, TimesFM, Toto, N-HiTS and GARCH-family candidates only for declared tasks/horizons.
- Use a shared/global backbone with optional evidence-supported regional/sector/country/business-model residual adapters.
- Add licence, resource, support and fallback state per model.

**Deliverables:** model plug-ins, manifests, baseline scorecards and route registry.  
**Acceptance:** every complex challenger is compared on untouched data; missing packages/weights return null; no model has trade authority.  
**Tests:** adapter contract, unavailable-model, baseline and routing fixtures.

#### AMEND `ISSUE-0108` — Horizon-aware probabilistic total-return distributions

**Priority / size:** P0 / M  
**Why:** Requested gain/loss percentages must be total-return distributions, not raw scores or exact target prices.

**Required delta**

- Add q05/q10/q25/q50/q75/q90/q95, loss, beat-cash and beat-benchmark probabilities.
- Separate price, income, FX, fees and cost components; tax remains optional accounting metadata outside the core recommendation contract.
- Add expected holding gain/loss in the user-selected output currency from the selected position or proposed amount.
- For bonds, consume the fixed-income return decomposition; never treat YTM as a guaranteed forecast.
- Add target horizon, maturity state, calibration and data/model support.

**Deliverables:** prediction-distribution store, fan-chart contract and downloadable outcomes.  
**Acceptance:** unsupported horizons are unavailable; gross/net values visible; no certainty language.  
**Tests:** quantile monotonicity, currency/holding conversion and horizon-support tests.

#### AMEND `ISSUE-0109` — Forecast uncertainty, disagreement and confidence decomposition

**Priority / size:** P0/P1 / M  
**Why:** A median without evidence quality, disagreement and realised coverage encourages overconfidence.

**Required delta**

- Separate aleatoric, epistemic/model and data-quality uncertainty.
- Widen/downgrade forecasts under model disagreement, source shift, poor support or regime drift.
- Add uncertainty haircut/certainty-equivalent field and effective independent model breadth.
- Detect clones using prediction/residual correlation, rank overlap and coincident errors.
- Track realised interval coverage from frozen historical forecasts.

**Deliverables:** uncertainty/disagreement fields, UI and forecast track record.  
**Acceptance:** correlated clones do not count as independent confirmation; low confidence cannot produce high authority.  
**Tests:** clone fixtures, coverage reliability and uncertainty monotonicity.

#### AMEND `ISSUE-0123` — Probabilistic and conformal forecast calibration

**Priority / size:** P0/P1 / M  
**Why:** Raw scores, probabilities and quantiles differ by asset, horizon and regime and are not automatically calibrated.

**Required delta**

- Calibrate probability, quantile, volatility and drawdown outputs separately.
- Fit only on earlier out-of-fold predictions.
- Require minimum support with parent/global fallback.
- Track 90%/95% coverage, quantile crossing and segment/regime drift.
- Preserve raw and calibrated values and the calibration-data hash.

**Deliverables:** calibration registry, reliability/coverage UI and fallback reasons.  
**Acceptance:** no future-outcome leakage; unsupported local calibration falls back; tolerance is predeclared.  
**Tests:** temporal leakage, crossing repair, fallback and coverage tests.

#### AMEND `ISSUE-0124` — Model monitoring, drift, champion/challenger and retirement

**Priority / size:** P0/P1 / M  
**Why:** Initial implementation is not permanent validity, and model-integrity incidents show release controls are investment controls.

**Required delta**

- Monitor loss, calibration, features, providers, route coverage and prediction similarity.
- Use signed immutable artefacts, dual approval, prediction differences and exact rollback.
- Track research/shadow/paper/approved/retired state by asset, task and horizon.
- Add fallback to the last approved simple/global champion.
- Link control incidents and post-mortems without exposing proprietary data.

**Deliverables:** monitoring store/UI, signed release manifest, rollback drill and incident link.  
**Acceptance:** direct artefact mutation blocks scoring; champions restore exactly; drift launches warning/challenger, not auto-promotion.  
**Tests:** hash tamper, rollback, synthetic drift and state-machine tests.

#### AMEND `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0007` and `ISSUE-0047` — Documents, timestamps, contradictions and explanations

**Priority / size:** P0/P1 / one S–M slice per owning issue  
**Why:** News and reports are useful only when entity, timestamp, source and exact claim are traceable.

**Required delta by owner**

- `ISSUE-0025`: immutable document/event ledger; 24-month news/context and 8Q/5Y report backfill; resumable lawful providers.
- `ISSUE-0054`: published/exchange-released/accepted/retrieved/knowledge time; exclude ambiguous/current-only history.
- `ISSUE-0007`: contradiction panel across date, source, filing version and management claim; context/risk only.
- `ISSUE-0047`: exact source span, authority, missingness, conflict and contribution for every displayed driver.
- Prefer XBRL/iXBRL, preserve amendments/restatements and deduplicate syndicated copies without losing provenance.

**Deliverables:** stores, context/filings UI, cited summaries and audit records.  
**Acceptance:** every generated claim links to hash/span; ambiguous timestamp excluded from backtest; LLM/news cannot directly change action.  
**Tests:** entity/time/dedup fixtures, multilingual labelled extraction and authority-boundary tests.  
**Boundary:** keep four canonical owners; do not merge them into one issue.

### C. Portfolio, risk and execution

#### AMEND `ISSUE-0021` — Portfolio construction and allocation sandbox

**Priority / size:** P0/P1 / M  
**Why:** The portfolio sandbox must consume real ledger/analysis snapshots and support legal/economic views, not become another score engine.

**Required delta**

- Add account/portfolio snapshot selector and direct versus look-through holdings.
- Add current/target weights, constraints, marginal effect and why-not explanations.
- Add stocks, ETFs, supported bonds, cash and FX under the capability matrix.
- Feed what-if/target changes into existing optimiser/risk/cost services.
- Route accepted changes to `ISSUE-0130` only as a draft proposal.

**Deliverables:** sandbox result store, before/after UI and export.  
**Acceptance:** sandbox never mutates live ledger; results cite selected snapshots; inapplicable assets are explicit.  
**Tests:** isolation, constraint and mixed-asset fixtures.

#### AMEND `ISSUE-0022` — ETF overlap and look-through

**Priority / size:** P0/P1 / M  
**Why:** Sector/country/currency charts are misleading without dated holdings, direct/indirect ownership and unknown coverage.

**Required delta**

- Add direct, indirect and combined exposure plus contributing ETF links.
- Add security, issuer, sector, country, currency, factor, cap and index-family overlap.
- Preserve `Unknown/Unmapped`; never redistribute missing holdings.
- Record holdings date, source, coverage and staleness.

**Deliverables:** overlap graph, exposure cube inputs and coverage-aware UI.  
**Acceptance:** mapped+unknown totals conserve portfolio value; direct/indirect ownership is distinguishable.  
**Tests:** nested ETF, duplicate security, missing holdings and conservation properties.

#### AMEND `ISSUE-0113` — Robust constrained optimisation and risk budgeting

**Priority / size:** P0/P1 / M  
**Why:** Scores cannot become unconstrained weights; estimation error makes transparent anchors essential.

**Required delta**

- Add 1/N, capped risk budgeting and maximum-diversification anchors.
- Support asset, sector, country, currency, issuer, rating, duration and liquidity constraints.
- Use forecast uncertainty and scenario robustness.
- Explain binding constraints, infeasibility and deviations from the anchor.
- Do not make unconstrained expected-return optimisation the default.

**Deliverables:** optimiser results/diagnostics, baseline comparisons and what-if UI.  
**Acceptance:** after-trade constraints pass; infeasible requests return reasons without hidden relaxation.  
**Tests:** constraint properties, anchor fixtures and infeasibility cases.

#### AMEND `ISSUE-0114` — Turnover, cost, tax-lot, cash and discrete rebalancing

**Priority / size:** P0/P1 / M  
**Why:** Target weights are not executable quantities, especially with cash, taxes, lots and bond denominations.

**Required delta**

- Add no-trade bands, minimum trade, lot/face denomination, increment and partial adjustment.
- Reserve estimated cash/FX and include fees, tax, spread and impact.
- Support account constraints and a declared tax-lot method.
- Record skipped/no-trade/rejected adjustments.
- Generate proposals through `ISSUE-0130`, never directly through UI/model code.

**Deliverables:** discrete plan, cost/tax breakdown and rejection reasons.  
**Acceptance:** trades conserve cash/positions under rounding; bond increments respected; no-trade persisted.  
**Tests:** conservation, lot/denomination, tax-lot and band fixtures.

#### AMEND `ISSUE-0115` — Portfolio stress, reverse stress and scenario revaluation

**Priority / size:** P0/P1 / M  
**Why:** A portfolio forecast needs adverse rates, spreads, equity, FX, inflation and liquidity conditions.

**Required delta**

- Create one scenario contract across stocks, ETFs, bonds, cash and FX.
- Include curve, credit-spread, default/recovery, equity, FX, inflation, volatility and liquidity shocks.
- Show component/marginal loss, constraint breach, coverage and unknown contribution.
- Add reverse stress for user-defined loss, drawdown, cash or liquidity thresholds.
- Compare approximation and full repricing where relevant.

**Deliverables:** scenario registry, portfolio UI and export.  
**Acceptance:** uses selected portfolio snapshot; unsupported assets remain unknown; signs/units tested.  
**Tests:** invariance/sign, bond duration/convexity versus full reprice, coverage reconciliation.

#### AMEND `ISSUE-0116` — Performance, risk, factor and decision attribution

**Priority / size:** P0/P1 / M  
**Why:** This existing owner must consume—not duplicate—the proposed ledger-derived performance series.

**Required delta**

- Reconcile price, income, FX, fees, tax and external-flow-neutral investment P&L.
- Attribute by security, asset, sector, country, currency, factor and decision.
- Show benchmark/cash relative and gross/net performance.
- Preserve mapped coverage and residual/unexplained amount.
- Link every attribution period to daily portfolio/performance snapshot IDs.

**Deliverables:** attribution records, waterfall/table UI and export.  
**Acceptance:** contributions reconcile to investment P&L; external flows never appear as investment contribution; residual visible.  
**Tests:** conservation, FX/income/fee and benchmark alignment.

#### AMEND `ISSUE-0127` — Double-entry portfolio, cash, FX, fee, tax and corporate-action ledger

**Priority / size:** P0 / M  
**Why:** All portfolio values, performance and execution must reconcile to one immutable book of record.

**Required delta**

- Add account hierarchy, securities, cash by currency, lots, external transfers, fees, taxes, income and corporate actions.
- Add bond face/notional, accrued settlement and principal/coupon entries.
- Use append-only reversal/correction entries rather than destructive edits.
- Expose trial balance, balances/positions rebuild and source reconciliation.
- Distinguish trade/settlement, pending/settled and broker/local truth.

**Deliverables:** ledger schema/service, rebuild engine and reconciliation UI.  
**Acceptance:** every journal balances; positions/cash rebuild from inception; corrections are auditable.  
**Tests:** double-entry properties, full-history rebuild, multi-currency and corporate-action fixtures.

#### AMEND `ISSUE-0128` — Spread, slippage, impact, capacity and cost models

**Priority / size:** P0/P1 / M  
**Why:** Expected gain and top-*N* are misleading without entry/exit, liquidity and capacity costs.

**Required delta**

- Add asset-specific cost model and uncertainty interval.
- For bonds include bid/ask, observation age, minimum size, dealer/RFQ uncertainty and accrued settlement.
- Persist forecast versus realised cost for paper/live orders.
- Add low/base/high/stressed cost and estimated liquidation cost/time.
- Ensure net forecasts and proposals reference one cost-policy version.

**Deliverables:** cost records, assumptions UI and realised reconciliation.  
**Acceptance:** unknown/illiquid cost can block conviction/execution; actual fills never overwrite original estimate.  
**Tests:** monotonicity, sparse/illiquid fixtures and forecast-versus-fill reconciliation.

#### AMEND `ISSUE-0138` — Research, comparison, charting and screening workspaces

**Priority / size:** P0/P1 / M  
**Why:** Analyser, screener and fixed-income pages need one task-oriented progressive-disclosure experience.

**Required delta**

- Add asset-aware instrument page and compare table using `AnalysisSnapshot`.
- Add total-return fan chart, risk/cost/evidence panels and forecast-outcome coverage.
- Add fixed-income identity, cash-flow, yield, duration and risk components from the new issue family.
- Add bulk run, exclusion funnel, saved results and exact snapshot reopening.
- Include global as-of/version/coverage bar and semantic locators.

**Deliverables:** responsive research/screener pages and downloadable data.  
**Acceptance:** all values map to exported fields; inapplicable sections are hidden/N/A, not zero; horizons match across pages.  
**Tests:** UI semantics, responsive/accessibility visual smoke and cross-surface parity.

#### AMEND `ISSUE-0139` — Portfolio, training, paper and live operations workspaces

**Priority / size:** P0/P1 / M  
**Why:** The portfolio and bot must be operational workspaces, not disconnected charts.

**Required delta**

- Implement the Part 5.2 chart contract.
- Add legal/economic exposure, holdings analysis, income/events, goals/alerts and what-if tabs.
- Add account/broker reconciliation, authority, controls, proposals, orders/fills and kill-switch panels.
- Use a global portfolio/data/analysis as-of bar.
- Ensure every action invokes an application service and creates an audit event.

**Deliverables:** full portfolio and operations workspaces.  
**Acceptance:** date/aggregation applies consistently; execution mode/blockers always visible; UI cannot bypass authority.  
**Tests:** browser workflows, accessibility/locale and button-to-audit assertions.

#### AMEND `ISSUE-0130` — Target-to-proposal policy and authority engine

**Priority / size:** P0 / M  
**Why:** One deterministic kernel must transform certified targets into paper or live proposals; model output cannot become an order.

**Required delta**

- Require sealed analysis, portfolio/ledger and policy snapshots.
- Add asset/account/broker authority and order-capability checks.
- Persist accepted, rejected, abstained, expired and superseded proposals.
- Add manual approval, batch approval, expiry and reason codes.
- Revalidate stale data/portfolio state before submission.

**Deliverables:** proposal state store, preview UI and replayable kernel.  
**Acceptance:** backtest/current/paper share kernel; missing/stale/conflicted prerequisite rejects; approval cannot bypass controls.  
**Tests:** kernel parity, authority states and stale/superseded proposal cases.

#### AMEND `ISSUE-0131` — Broker adapter contracts, read-only synchronisation and reconciliation

**Priority / size:** P0/P1 / M  
**Why:** Brokers can disagree, omit callbacks and send duplicate events; the adapter must never be treated as a simple synchronous function.

**Required delta**

- Discover capabilities by account, asset, venue and order type.
- Start with read-only positions, cash, open orders, fills and account status.
- Use broker permanent IDs plus local idempotency keys and append-only events.
- Treat duplicate status callbacks as idempotent; reconcile fills separately.
- Add degraded/unknown state and never auto-resubmit it.
- Redact secrets from logs and exports.

**Deliverables:** adapter SDK, first read-only connector, fixtures and reconciliation UI.  
**Acceptance:** positions/cash/orders reconcile or break explicitly; disconnect cannot increase authority.  
**Tests:** recorded sessions, duplicates/missing callbacks, reconnect/reconciliation and secret scans.

#### AMEND `ISSUE-0132` — Independent pre-trade controls, kill switches and operational limits

**Priority / size:** P0 / M  
**Why:** The predictive/proposal layer must not own the controls that can stop it.

**Required delta**

- Implement all limits and kill switches in Part 7.3.
- Add price collars, max order value/volume/messages, throttles and event/market-state blocks.
- Check after-trade exposure, settled/available cash, settlement, FX, denomination and liquidity.
- Add durable, expiring operator overrides with maker/checker approval where required.
- Fail closed on control-service uncertainty.

**Deliverables:** independent control service, console, policy store and audit events.  
**Acceptance:** controls reject independently; kill switch blocks new orders and performs configured cancel; overrides cannot be silent/permanent.  
**Tests:** property/fuzz limits, kill-switch latency and service-failure modes.

#### AMEND `ISSUE-0133` — Staged canary live execution with explicit promotion gates

**Priority / size:** P0 / M  
**Why:** The requested bot belongs here, but not as an unrestricted switch.

**Required delta**

- Implement authority per broker/account/asset/strategy/venue/horizon.
- Use the narrow first-canary scope in Part 7.2.
- Require manual approval initially, tiny exposure, bounded frequency and immediate rollback.
- Define prospective operational/investment evidence for supervised→bounded promotion.
- Keep bonds, leverage, shorts, derivatives and after-hours execution excluded until separately certified.
- Require legal/terms, final certification, cash reservation and independent controls.

**Deliverables:** canary state machine, console, runbook and live-evidence ledger.  
**Acceptance:** no live submission before every dependency and explicit operator enablement; every order traces to snapshots/controls/approval.  
**Tests:** end-to-end simulated/sandbox certification, authority-bypass adversarial tests and emergency shutdown drill.

#### AMEND `ISSUE-0134` — Post-trade performance and transaction-cost attribution

**Priority / size:** P0/P1 / M  
**Why:** A bot is not controlled unless decision quality and realised execution costs are measured prospectively.

**Required delta**

- Record decision, arrival, submission, fill and closeout prices/times.
- Attribute spread, delay, impact, opportunity cost, fees, FX, rejection and partial fills.
- Compare original forecast cost with realised cost without rewriting it.
- Aggregate by broker, venue, strategy, asset, time and order type.

**Deliverables:** TCA store/dashboard and feedback report.  
**Acceptance:** every fill reconciles to proposal/order or is unexpected; TCA components reconcile to realised slippage.  
**Tests:** partial fill, reject, delay, price-source and cost-reconciliation fixtures.

#### AMEND `ISSUE-0135` — Incident, recovery, reconciliation and operational drills

**Priority / size:** P0 / M  
**Why:** Duplicate/unknown orders, outages and unexpected positions must be rehearsed before live authority.

**Required delta**

- Add scenarios for duplicate/unknown order, stale data, disconnect, unexpected position, cash break, reject storm, corrupted artefact and rollback.
- Define source of truth, recovery point, cancel strategy and operator sign-off.
- Preserve event history and post-mortem; unresolved breaks block related execution.
- Run scheduled drills in source and packaged modes.

**Deliverables:** incident journal, drill runner, runbooks and evidence.  
**Acceptance:** each drill has deterministic pass/fail; recovery does not duplicate orders or lose ledger events.  
**Tests:** recorded failure fixtures, replay and chaos/recovery tests.

### D. Legal, bias, audit and certification

#### AMEND `ISSUE-0149` — Legal, data/model licence, terms, disclaimer and jurisdiction review

**Priority / size:** P0 / M  
**Why:** Expanded providers, debt instruments and broker writes create terms, redistribution, tax and regulatory questions code cannot decide.

**Required delta**

- Add provider/broker terms, retention, redistribution and jurisdiction records.
- Add user-role matrix: private individual, adviser, investment firm, managed account.
- Assess algorithmic-trading, market-abuse, recordkeeping, best-execution and notification applicability.
- Review every model/checkpoint/software licence and commercial-use condition.
- Add accurate uncertainty, non-advice and tax-estimate disclosures.

**Deliverables:** signed review matrix and capability-disable policy.  
**Acceptance:** no provider/model/broker write without approval; uncertainty defaults disabled/manual review.  
**Tests:** expired/missing approval blocks, redaction audit and disclosure smoke.

#### AMEND `ISSUE-0150` — Geographic, sector, size, listing and data-coverage bias audit

**Priority / size:** P0/P1 / M  
**Why:** Bonds and global bulk universes amplify source, liquidity and survival bias.

**Required delta**

- Add asset, issuer type, rating, duration, currency and debt-liquidity coverage.
- Compare eligible/rejected/missing funnels by market/provider.
- Report forecast/shortlist performance by coverage tier and inclusion history.
- Prevent high scores from masking systematically sparse groups.

**Deliverables:** coverage/bias dashboard and audit export.  
**Acceptance:** every run reports denominators/exclusions; bias results feed model/peer promotion; unknown history remains visible.  
**Tests:** coverage-skew fixtures, denominator and replay tests.

#### AMEND `ISSUE-0147` — Sealed audit packet v3

**Priority / size:** P0 / M  
**Why:** The expanded product needs evidence for ledger, performance, debt, bulk, authority and broker workflows.

**Required delta**

- Export ledger trial balance, valuations/performance, analysis parity, bond analytics, bulk runs, authority/controls, reconciliation and licences.
- Include raw/derived manifests, checksums and exact versions.
- Include unavailable markers instead of omitting missing evidence.
- Provide a replay entry point and human-readable index.

**Deliverables:** sealed ZIP/manifest and verifier.  
**Acceptance:** reviewer reproduces displayed values from snapshots; no secret/licensed full text leaks.  
**Tests:** clean replay, checksum tamper, redaction and UI/export parity.

#### AMEND `ISSUE-0152` — Final release certification and completion programme closure

**Priority / size:** P0 / M  
**Why:** Certification must be capability-specific and include the new product boundary.

**Required delta**

- Certify separately: analysis, bulk, portfolio, fixed income, paper, read-only broker and canary.
- Require all adopted P0 new issues and the cross-workflow parity gate.
- Run clean-machine build, package/source differential, browser/UI, security, chaos, rollback, legal and audit replay.
- Do not let certification itself enable bounded automatic execution; require a separate explicit authority transition.

**Deliverables:** capability certification matrix and signed release record.  
**Acceptance:** failed capability remains uncertified while safe unrelated read-only capability can remain available.  
**Tests:** complete release gate and independent review.


#### AMEND `ISSUE-0110` — Transparent multi-factor risk model for stocks, ETFs and portfolios

**Priority / size:** P0 / M  
**Why:** The factor model must support whole-portfolio drill-down and interact coherently with the new debt/rates risk family without pretending to be a proprietary Barra clone.

**Required delta**

- Preserve transparent market, size, value, quality, momentum, sector/country, currency and liquidity factors.
- Add interfaces for duration, curve, spread/credit and inflation factors from `ISSUE-0156` rather than forcing bonds through equity factors.
- Calculate exposure coverage, systematic/specific risk, crowding and concentration.
- Use regional/global hierarchy and point-in-time factor definitions.
- Expose factor-source, mapping, confidence and residual/unexplained risk.

**Deliverables:** versioned factor registry, exposure/risk stores and drill-down UI.  
**Acceptance:** portfolio factor contributions reconcile to covered risk; unsupported debt factors remain unknown; definitions reproduce from frozen data.  
**Tests:** exposure aggregation, factor-sign/unit, missing coverage and historical-version fixtures.

#### AMEND `ISSUE-0111` — Robust covariance, volatility, correlation and tail-risk estimation

**Priority / size:** P0 / M  
**Why:** Portfolio forecast, optimisation, stress and top-*N* require a robust dependence model rather than sample covariance alone.

**Required delta**

- Add EWMA/shrinkage/factor covariance baselines and guarded nonlinear challengers.
- Estimate by horizon/regime with minimum support and positive-semidefinite repair.
- Add downside/tail dependence, drawdown and liquidity-stress diagnostics.
- Integrate debt duration/spread/credit/FX components and common scenario factors.
- Store estimation uncertainty, effective sample and fallback.

**Deliverables:** covariance/risk snapshots, diagnostics and versioned policy.  
**Acceptance:** matrices are valid and stable under perturbation; simple shrinkage baseline remains available; unsupported correlations are not zero-filled.  
**Tests:** PSD/symmetry properties, near-singular and sparse-history cases, regime/source perturbation and portfolio-risk reconciliation.

#### AMEND `ISSUE-0125` — Deterministic event-driven, order-level backtest engine

**Priority / size:** P0 / M  
**Why:** Historical validation must exercise the same decision/proposal/order semantics and avoid same-bar or current-data leakage.

**Required delta**

- Use the production `AnalysisSnapshot` and target-to-proposal kernel at historical decision times.
- Model decision, arrival/next-open, submission, partial fill, cancellation, rejection and closeout events.
- Apply exchange calendars, corporate actions, cash/FX, settlement, fees, spread, impact, denomination and liquidity.
- Support stocks, ETFs and paper-supported bonds only under explicit capability.
- Preserve all orders/fills/rejections, no-trade outcomes and data quality.

**Deliverables:** deterministic event stream, order/fill ledger and replay UI/export.  
**Acceptance:** no same-bar execution; cash/positions reconcile; repeated run from same hashes is identical; unsupported assets reject.  
**Tests:** next-open/arrival fixtures, partial/reject, corporate actions, settlement and current/backtest kernel parity.

#### AMEND `ISSUE-0126` — Point-in-time universes, delistings and survivorship-bias controls

**Priority / size:** P0 / M  
**Why:** Bulk ranking and model validation are invalid if they know current survivors, constituents or active debt before the decision date.

**Required delta**

- Store listed/active/inactive/delisted/defaulted state by valid and knowledge time.
- Preserve historical index/ETF constituents and user-universe membership where available.
- Add issue/maturity/call/default lifecycle for debt securities.
- Record coverage denominator, source, mapping and reason for missing historical membership.
- Prevent current-universe backfill from becoming historical proof.

**Deliverables:** universe snapshots, lifecycle store and coverage diagnostics.  
**Acceptance:** failed/delisted/defaulted instruments remain in outcomes; maturity/call removal occurs at correct date; historical top-*N* uses only then-eligible names.  
**Tests:** delisting/default/maturity fixtures, constituent change replay and future-membership canary.

#### AMEND `ISSUE-0129` — Full paper broker, frozen proposal ledger and forward-evidence service

**Priority / size:** P0 / M  
**Why:** Paper mode is the mandatory bridge between backtest and live authority and must use the same proposal, reservation and order lifecycle as live.

**Required delta**

- Consume frozen proposals and `ISSUE-0167` order states/reservations.
- Simulate latency, spread, partial fills, rejections, cancellations, market state and settlement.
- Post fills/cash/fees/income/actions into the double-entry ledger.
- Record 20/60/120-day and horizon-maturity outcomes, benchmark/cash comparison and forecast calibration.
- Separate simulation assumptions from observed paper-market data and preserve versions.
- Add supported stock/ETF and later validated debt paper capabilities.

**Deliverables:** paper broker, proposal/order/fill ledger, forward-evidence dashboard and export.  
**Acceptance:** paper/live contracts match; frozen proposal is immutable; paper evidence cannot be backfilled after outcomes; unresolved reconciliation blocks authority promotion.  
**Tests:** fill-model fixtures, restart/replay, ledger reconciliation, prospective timestamp and no-look-ahead tests.


#### AMEND `ISSUE-0039`, `ISSUE-0077`, `ISSUE-0078` and `ISSUE-0151` — Performance, jobs, budgets and graceful degradation

**Priority / size:** P0/P1 / one S–M slice per owner  
**Why:** Bulk analysis, model training and portfolio reconstruction can be correct but unusable if jobs block the UI, exhaust storage or fail without resumable evidence.

**Required delta by owner**

- `ISSUE-0039`: cache correctness, invalidation, cache-hit/age/source visibility and performance audit.
- `ISSUE-0077`: durable job DAG, stage/checkpoint state, cancellation, resume, retry policy and per-stage logs.
- `ISSUE-0078`: runtime, latency, memory, storage, startup, render and throughput budgets with regression profiling.
- `ISSUE-0151`: low/standard/high hardware profiles, optional-model degradation, disk budgets and user-visible resource policy.
- Add always-on local telemetry and opt-in deep profiling; no third-party telemetry by default.

**Deliverables:** job/telemetry stores, Diagnostics/Jobs UI, benchmark fixtures and budget policies.  
**Acceptance:** long jobs do not freeze the UI; resume is deterministic; budget regression fails release; low-resource mode remains safe and explicit.  
**Tests:** load/soak, cancellation/restart, cache invalidation, memory/disk thresholds and source/package profiling.  
**Boundary:** do not let telemetry or profiling change financial calculations.

#### AMEND `ISSUE-0136`, `ISSUE-0137` and `ISSUE-0140` — Typed API, task-oriented design, accessibility and localisation

**Priority / size:** P0/P1 / one M slice per owner  
**Why:** New portfolio, debt and execution surfaces require typed projections and coherent navigation, not page-local calculation logic.

**Required delta by owner**

- `ISSUE-0136`: typed view models for AnalysisSnapshot, bulk runs, portfolio performance/exposure, debt analytics, authority, controls and order lifecycle.
- `ISSUE-0137`: task-oriented navigation, progressive disclosure, global as-of bar and consistent evidence/authority semantics.
- `ISSUE-0140`: keyboard/screen-reader support, global search/command palette, British English, selected-currency/European-default number and date formatting, and unit labelling.
- Every action routes through an application service and produces a status/audit event.

**Deliverables:** typed local API, design-system components, navigation/search and localisation/accessibility evidence.  
**Acceptance:** no domain formula in UI; every chart/table has semantic labels and download; currency/percentage/date units are unambiguous.  
**Tests:** schema/view-model, keyboard/screen-reader, locale/format, responsive and source/package UI tests.

#### AMEND `ISSUE-0142` and `ISSUE-0143` — Advanced, E2E, load, soak, fault and chaos testing

**Priority / size:** P0/P1 / one M slice per owner  
**Why:** Accounting, debt pricing, bulk resume and order controls require more than example-based unit tests.

**Required delta**

- Add property/metamorphic tests for ledger balance, cash conservation, exposure totals, quantile order, PSD covariance and idempotency.
- Add golden/differential debt pricing and portfolio-performance fixtures.
- Add mutation tests for hidden second calculations, removed controls and altered time cut-offs.
- Add visual E2E for analyser, bulk, portfolio and operations workspaces.
- Add 1,000-instrument load/soak, provider failure, disk pressure, network loss, broker disconnect and kill-switch chaos programmes.

**Deliverables:** test catalogues, deterministic fixtures, release reports and retained baselines.  
**Acceptance:** critical mutants are killed; full workflows recover/reconcile; packaged and source modes pass.  
**Tests:** the issue itself owns the test harness and evidence; no feature closes with a waived P0 invariant.

#### AMEND `ISSUE-0144`, `ISSUE-0145` and `ISSUE-0146` — Security, supply chain, privacy, backup and recovery

**Priority / size:** P0/P1 / one M slice per owner  
**Why:** Portfolio data, broker credentials, imported documents and model artefacts materially expand the security boundary.

**Required delta by owner**

- `ISSUE-0144`: parser sandboxing, path traversal/ZIP bomb protection, local API auth/origin controls, secure file permissions, SSRF/URL allowlists and secret redaction.
- `ISSUE-0145`: pinned dependencies/checkpoints, SBOM, vulnerability/license scanning, artefact signing, reproducible builds and secure updates.
- `ISSUE-0146`: encrypted secret/backup stores, privacy/export/delete controls, tested backup/restore and disaster-recovery objectives.
- Broker secrets never enter model prompts, logs, screenshots or audit packets.

**Deliverables:** threat model, security tests, SBOM/signatures, backup/restore evidence and incident hooks.  
**Acceptance:** tampered release/model is rejected; malicious imports cannot escape quarantine; clean restore reproduces ledger/snapshot hashes.  
**Tests:** adversarial files/URLs, secret scanning, signature tamper, backup restore and permission checks.


### E. User-priority, funds, currency, profile and analysis-depth amendments

These are additional user-requirements deltas to the canonical owners already specified in Sections A–D, not duplicate issue definitions. They implement the user’s final product answers and have priority over portfolio convenience and execution work. Existing issue text remains in force unless this section explicitly narrows or clarifies it.

#### USER-REQUIREMENTS DELTA — `ISSUE-0070` and `ISSUE-0152` — Separate core research, portfolio and execution certification

**Priority / size:** P0 / M  
**Why:** The user’s primary product is individual analysis and top-*N* screening. Portfolio and broker dependencies must not hold the core research release hostage, and a successful analyser must not imply broker authority.

**Required delta**

- Define independent certification lanes: `CORE_ANALYSIS`, `BULK_SCREENING`, `FUND_ANALYSIS`, `FIXED_INCOME_ANALYSIS`, `PORTFOLIO_READ_ONLY`, `PAPER`, `BROKER_READ_ONLY`, `LIVE_CANARY`.
- Make `CORE_ANALYSIS` require selected-currency/FX, exact horizons, peer semantics, fund support, risk profiles, analysis depth, free-data/provider credentials, calibration and parity.
- Keep tax optimisation, portfolio ledger completion and all broker writes outside the core lane.
- Preserve `execution_allowed=false` across every core-analysis state.
- Add a machine-readable release-priority field and dependency rule that P1/P2 failures cannot block a safe P0 release unless they share a P0 contract.

**Deliverables:** certification-lane registry, dependency-policy migration, Roadmap/System Map presentation and lane-specific release records.  
**Acceptance:** a broker/control blocker leaves core analysis usable; a core-analysis failure cannot be hidden by portfolio or execution certification; no lane grants authority to another.  
**Tests:** dependency-cut tests, lane-state transitions, UI badge separation and audit/export parity.

#### USER-REQUIREMENTS DELTA — `ISSUE-0008` — Long-only multi-asset scope and explicit exclusions

**Priority / size:** P0 / S  
**Why:** The normal product path is buying, holding and selling ordinary long-only instruments—not shorts, leverage or exotic wrappers.

**Required delta**

- Add first-class ordinary mutual/index funds, including umbrella/sub-fund/share-class distinctions.
- Restrict normal recommendations to `buy/add`, `hold`, `avoid/no_trade`, `trim/sell` and `manual_review`.
- Exclude OTC/penny shares, very illiquid microcaps, leveraged/inverse products, crypto, derivatives, shorting, margin/leverage and complex structured funds by default.
- Make exclusion thresholds versioned and editable only inside safe policy bounds; no risk profile can override product-class exclusions.
- Add data-frequency/horizon capability per asset, including funds whose dealing frequency makes `1W` unsupported.

**Deliverables:** expanded capability/rejection matrix, reason-code registry and UI warning surfaces.  
**Acceptance:** every instrument resolves to one explicit support state; excluded products cannot enter a ranking/model through provider misclassification.  
**Tests:** CFI/security-type rejection, OTC/microcap/liquidity fixtures, leveraged-fund fixtures and long-only action enumeration.

#### USER-REQUIREMENTS DELTA — `ISSUE-0037` — Settings centre for currencies, horizons, profiles, depth and providers

**Priority / size:** P0 / M  
**Why:** The current onboarding accepts free-text EUR, only stock/ETF scope, three generic risk labels and short/medium/long horizons. The requested product needs validated, versioned controls.

**Required delta**

- Replace free-text currency with an ISO-4217 selector backed by validated FX coverage; default EUR.
- Replace asset scope with stocks, ETFs, ordinary funds, bonds and combinations.
- Replace `conservative/balanced/growth` with the five canonical risk profiles and an advanced editor.
- Replace `short/medium/long` with exact `1W/1M/3M/6M/9M/2Y/5Y` selections.
- Add `Quick/Medium/High/Full` analysis-depth selection and explain warm/cold timing.
- Add the secure Data Providers & API Keys centre from `ISSUE-0176`.
- Store settings versions and show which changes create a new analysis/selection run.

**Deliverables:** typed configuration schema, migration from existing onboarding values, validation UI and export.  
**Acceptance:** invalid currency/horizon/profile/depth is rejected; changing a semantic setting creates new versioned results; no secret appears in config export.  
**Tests:** migration, locale, validation, secret-redaction and settings-to-run-manifest parity.

#### USER-REQUIREMENTS DELTA — `ISSUE-0074` — Three-layer score and recommendation contract

**Priority / size:** P0 / M  
**Why:** Peer-relative metric quality, forecast opportunity and risk-profile suitability are different objects.

**Required delta**

- Formalise Layer A asset-specific raw facts and applicability, Layer B peer-relative evidence scores and Layer C benchmark-relative opportunity/recommendation.
- Persist exact metric registry, peer cohort, support, fallback, raw and transformed values.
- Forbid VWCE/cash from normalising P/E, leverage, margins or other business-model metrics.
- Apply risk profiles only after a sealed common analysis exists; preserve one profile-independent forecast/score snapshot.
- Include output currency, exact horizon and analysis-depth manifest in the snapshot.
- Add recommendation language and risk/downside display required for a general investment recommendation.

**Deliverables:** `AnalysisSnapshot` v4, score-layer registry and profile projections.  
**Acceptance:** a bank and technology company cannot share an invalid valuation cohort; profile changes never mutate raw facts/forecasts; all displayed scores trace to one layer.  
**Tests:** wrong-peer mutation test, profile invariance, byte-equivalent projections and benchmark-layer separation.

#### USER-REQUIREMENTS DELTA — `ISSUE-0080`, `ISSUE-0076` and `ISSUE-0081` — Free-only provider policy and bounded bulk acquisition

**Priority / size:** P0 / M  
**Why:** Global free coverage is fragmented and rate-limited; success requires orchestration and honest gaps, not a fictitious universal feed.

**Required delta**

- Enforce `subscription_cost=0` for the mandatory path; free registration/API keys are allowed.
- Register provider access state: `no_key`, `optional_key`, `required_key`, rate limits, bulk downloads, redistribution, retention, geographic/asset coverage and current terms review.
- Separate cold acquisition, warm refresh, local analysis and training timing.
- Prefer lawful bulk files for thousands of instruments where available; content-address and delta-update them.
- Add provider-specific adaptive concurrency, quota reservation, Retry-After handling, circuit breakers and exact coverage denominators.
- Never substitute a lower-authority provider silently when a required source is missing.

**Deliverables:** provider-policy v3, acquisition planner, quota ledger and cold/warm diagnostics.  
**Acceptance:** no paid provider is mandatory; a no-key startup remains safe; a 3,000-instrument run respects every provider limit and reports missing markets explicitly.  
**Tests:** key/no-key matrices, 429/retry fixtures, bulk-vs-row parity, cold/warm timing and provider-disable tests.

#### USER-REQUIREMENTS DELTA — `ISSUE-0018`, `ISSUE-0020`, `ISSUE-0165` and `ISSUE-0166` — Multidimensional top-*N* contract

**Priority / size:** P0 / M  
**Why:** The user requires total, sector, country and country×sector rankings for every asset, risk profile and horizon.

**Required delta**

- Add exact scope metadata: asset family, economic country/region, sector/industry or fund mandate, profile, horizon, depth and output currency.
- Produce separate stock, ETF, ordinary-fund and bond lists before any common-metric cross-asset view.
- Generate total, sector, country and country×sector slices only when minimum raw/effective sample support is met.
- Use economic country/business context for stocks and explicit mandate/look-through coverage for funds; diversified funds may use `multi-country`/`multi-sector` categories.
- Add configurable `N`, deterministic tie-breaks, rank interval, selection probability, stability and why-not reasons.
- Store one complete candidate table and derive all views without rerunning or changing analysis.
- Add run comparison across risk profiles/depths without pooling incompatible snapshots.

**Deliverables:** `SelectionSliceDefinition`, slice materialiser, UI matrix, run history and full export.  
**Acceptance:** every displayed list reconciles to the full candidate table; sparse country×sector groups cannot show false winners; filters never recalculate scores.  
**Tests:** slice conservation, sparse fallbacks, country/sector classification, profile/horizon/depth parity and 3,000-instrument load.

#### USER-REQUIREMENTS DELTA — `ISSUE-0082`, `ISSUE-0083`, `ISSUE-0105` and `ISSUE-0098` — Fund identity and peer semantics

**Priority / size:** P0 / M  
**Why:** A fund umbrella, sub-fund and share class are not interchangeable, and ETF market-price fields do not apply to ordinary funds.

**Required delta**

- Extend identity to legal vehicle, umbrella, compartment/sub-fund, share class, listing/dealing channel, master/feeder and fund-of-funds links.
- Record base, share-class, dealing, listing and hedging currency separately.
- Add active/passive/index, mandate, benchmark, asset/region/sector exposure, distribution policy, fee tier and dealing/liquidity class.
- Build ordinary-fund peer cohorts separately from ETFs, with class-cost adjustment and dated holdings/mandate coverage.
- Preserve share-class-specific fees and returns while allowing economic-strategy deduplication.
- Add fund closure, merger, liquidation, incubation/backfill, benchmark, manager and mandate-change histories.

**Deliverables:** fund identity/context v1, peer registration and lineage UI.  
**Acceptance:** one umbrella’s share classes do not inflate peer support; accumulating/distributing and hedged/unhedged classes remain distinct; ETF spread fields are N/A for ordinary funds.  
**Tests:** multi-class fund fixtures, merger/liquidation replay, hedge-currency and fee-tier tests.

#### USER-REQUIREMENTS DELTA — `ISSUE-0084`, `ISSUE-0088`, `ISSUE-0108` and `ISSUE-0128` — Product-wide FX and selected-currency semantics

**Priority / size:** P0 / M  
**Why:** A foreign asset’s selected-currency result is the joint asset-and-FX return, not local return translated once at today’s spot.

**Required delta**

- Store official point-in-time spot/reference FX observations, base/quote convention, source, availability, revision and reference/executable label.
- Use `1 + r_output = (1 + r_local) × (1 + r_fx)` for realised total returns and a joint dependence model for forecast distributions.
- Distinguish asset base/reporting/trading/dealing/share-class/hedging and user-output currencies.
- Add official-source hierarchy and cross-rate/triangular-consistency checks.
- Keep reference rates separate from estimated executable spread/fees.
- Convert every monetary UI/export field consistently while preserving local values and FX contribution.
- Reject precise output where required FX is missing/stale/conflicted.

**Deliverables:** FX store/service, selected-currency forecast adapter, cost integration and audit lineage.  
**Acceptance:** local and output returns reconcile exactly; a falling foreign currency can reverse a positive local return; reference FX cannot be labelled executable.  
**Tests:** cross-rate properties, triangular arbitrage tolerance, hedged/unhedged share classes, joint scenarios and missing-FX blocking.

#### USER-REQUIREMENTS DELTA — `ISSUE-0112` and `ISSUE-0174` dependency — Dynamic VWCE anchor and benchmark hierarchy

**Priority / size:** P0 / M  
**Why:** `Medium` is defined as VWCE-like, but VWCE has multiple listings/currencies and changing product/risk data.

**Required delta**

- Identify the anchor by ISIN `IE00BK5BQT80`, not ticker.
- Resolve one canonical share class to listing-specific observations and the selected output currency.
- Store dated official product facts, FTSE All-World benchmark, fees, tracking, risk distribution, currency and source hashes.
- Keep the regulatory/product risk indicator as a versioned source fact, not the profile definition.
- Provide cash and asset-specific benchmarks separately; VWCE is a final broad-equity opportunity anchor, not a peer for every metric/asset.

**Deliverables:** anchor registry, refresh job and benchmark mapping UI.  
**Acceptance:** all VWCE listings map to one share class; an unavailable/stale anchor prevents profile-relative claims but does not corrupt raw analysis.  
**Tests:** listing/ISIN fixtures, currency conversion, dated product snapshot and benchmark fallback.

#### USER-REQUIREMENTS DELTA — `ISSUE-0117`, `ISSUE-0119`, `ISSUE-0120`, `ISSUE-0121`, `ISSUE-0123` and `ISSUE-0124` — Exact horizons, overlap-safe validation and training separation

**Priority / size:** P0 / L across owners  
**Why:** Training may finish in hours, but 2Y/5Y prospective evidence takes years. Multi-period labels overlap and cannot be treated as independent observations.

**Required delta**

- Register exactly `1W`, `1M`, `3M`, `6M`, `9M`, `2Y`, `5Y` by asset/task/data frequency.
- Separate `training_wall_time`, `inference_wall_time`, `historical_label_span` and `prospective_maturity_date`.
- Use production frozen champions for normal runs; training/HPO is a separate scheduled job and never triggered implicitly by analysis depth.
- Build cumulative and annualised long-horizon labels with delisting/default/distribution/FX/cost treatment.
- Apply horizon-aware purging/embargo and group folds; use HAC/block/bootstrap inference for overlapping outcomes and report effective independent decisions.
- Evaluate distributions with proper scores, coverage and calibration; compare challengers with appropriate DM/Clark–West-style tests plus economic utility.
- Require horizon-specific champion/fallback/abstention and source/segment drift.
- Keep 2Y/5Y evidence `retrospective_only` or `forward_immature` until calendar outcomes mature.

**Deliverables:** horizon registry, label store, overlap report, evaluation suite and maturity UI.  
**Acceptance:** no long-horizon observation is counted as an independent weekly/monthly decision; training duration is never displayed as forecast evidence maturity.  
**Tests:** overlap canaries, effective-sample checks, cumulative/annualised identities, nested/non-nested comparison fixtures and maturity-state transitions.

#### USER-REQUIREMENTS DELTA — `ISSUE-0109`, `ISSUE-0057` and `ISSUE-0129` — Forecast track record and recommendation efficacy

**Priority / size:** P0 / M  
**Why:** Product quality and credible outperformance are both goals; a high score is insufficient without prospective calibration and decision results.

**Required delta**

- Freeze every displayed forecast/recommendation with horizon, profile, currency, depth and benchmark.
- Track quantile/probability calibration, CRPS/log/Brier/pinball metrics, rank IC/NDCG/top-*N* overlap and net benchmark/cash returns.
- Record abstentions, exclusions and all candidate denominators to prevent cherry-picking.
- Evaluate `buy/hold/avoid/trim/sell` outcomes at decision-price and next-tradable-price conventions with costs.
- Compare against VWCE, cash, asset-specific benchmark and transparent no-skill/simple baselines.
- Use statistical tests that account for serial dependence, overlap, model nesting and multiple testing; report effect, CI and p-value where valid.
- Keep investment efficacy separate from operational paper-broker realism.

**Deliverables:** forecast/recommendation outcome ledger, efficacy dashboard and capability-specific promotion policy.  
**Acceptance:** a model can be calibrated but not outperforming, or outperforming in one segment but unsupported elsewhere; the UI shows both.  
**Tests:** frozen-timestamp, no-backfill, benchmark alignment, overlap-aware inference and all-attempt denominator tests.

#### USER-REQUIREMENTS DELTA — `ISSUE-0174` plus `ISSUE-0074`, `ISSUE-0020`, `ISSUE-0138` — Five risk-profile projections

**Priority / size:** P0 / M  
**Why:** The five profiles must filter and reweight one common analysis rather than create five hidden models.

**Required delta**

- Implement Safe, Safe–Medium, Medium, Medium–Aggressive and Aggressive as versioned policies.
- Anchor Medium to the dated, horizon/currency-matched VWCE distribution; define other profiles relative to calibrated loss, expected shortfall, volatility, drawdown, liquidity and evidence envelopes.
- Make all thresholds/weights visible and editable within guardrails; retain original defaults and version history.
- Preserve absolute evidence, product, data and liquidity gates across all profiles.
- Generate profile-specific eligibility/rank/recommendation without changing raw forecasts.

**Deliverables:** policy editor, profile projections and comparison UI.  
**Acceptance:** switching profile changes only policy projection fields; Aggressive cannot admit prohibited/unsupported products or weak evidence.  
**Tests:** raw-analysis invariance, monotonic risk-envelope properties, VWCE-anchor refresh and policy-version replay.

#### USER-REQUIREMENTS DELTA — `ISSUE-0039`, `ISSUE-0077`, `ISSUE-0078`, `ISSUE-0151`, `ISSUE-0165` and `ISSUE-0175` — Workload depth and measured SLOs

**Priority / size:** P0 / L across owners  
**Why:** Existing hardware profiles govern capacity, not semantic analysis depth. The user wants Quick/Medium/High/Full with honest limits on both a strong and older device.

**Required delta**

- Define analysis-depth manifests separately from low/standard/high hardware profiles.
- Freeze mandatory/optional stages, model families, documents, seeds, horizons and robustness per depth.
- Preserve formulas and hard gates in every mode; only approved optional breadth may differ.
- Measure cold acquisition, warm refresh, inference, calibration, scenario, export and training separately.
- Benchmark provisional warm-cache SLOs on 3,000 supported instruments and the declared 20-core/32-GB/RTX-5070 reference machine: Quick ≤5 minutes, Medium ≤30 minutes, High ≤60 minutes, Full ≤10 hours.
- Publish p50/p95, resource use and omitted optional evidence; do not fabricate ETA.
- Support older machines with smaller shards, CPU fallbacks, pause/resume and explicit longer actual time without changing semantics.

**Deliverables:** depth registry/controller, scheduler integration, benchmark suite and run manifest.  
**Acceptance:** a profile that misses mandatory evidence fails rather than silently downgrading; repeated warm runs reuse identical hashes/results.  
**Tests:** stage-manifest parity, cold/warm separation, profile upgrade lineage, resource pressure and cross-hardware numerical equivalence.

#### USER-REQUIREMENTS DELTA — `ISSUE-0136`, `ISSUE-0137`, `ISSUE-0138`, `ISSUE-0139` and `ISSUE-0140` — User-priority research UI

**Priority / size:** P0 / L across owners  
**Why:** The research/screener workflow must be the primary navigation and make peer, currency, profile, horizon and depth explicit.

**Required delta**

- Put Analyse, Compare, Screener and Bulk Runs before Portfolio and Operations.
- Add exact horizon, selected currency, risk profile and analysis depth to the global as-of bar.
- Add fund-aware pages for NAV/dealing, documents, fees, benchmark, holdings, distributions and share-class lineage.
- Add total/sector/country/country×sector top-*N* matrix and saved-run comparison.
- Show raw metric/peer/fallback separately from VWCE/cash opportunity and profile recommendation.
- Use British English and user-selected locale/currency; all chart/download values include units and source snapshot.
- Add generic `Guest analysis` export mode with no personal financial inputs or suitability claim.

**Deliverables:** revised navigation, typed view models, responsive pages, exports and accessibility evidence.  
**Acceptance:** no hidden page-local calculation; every recommendation shows basis, horizon, risk, limitations, source time and conflicts.  
**Tests:** user workflows, keyboard/screen-reader, locale/currency, fund/stock/bond variants and cross-surface parity.

#### USER-REQUIREMENTS DELTA — `ISSUE-0114`, `ISSUE-0127` and `ISSUE-0159` — Reduce tax scope to optional bookkeeping

**Priority / size:** P1 / S  
**Why:** The user does not require tax advice or optimisation.

**Required delta**

- Remove jurisdiction-specific tax recommendation/optimisation from core release dependencies.
- Retain optional imported tax amounts and generic fee/tax cash entries for accounting reconciliation.
- Keep all tax estimates clearly user-supplied or informational and excluded from recommendation authority unless separately accepted later.

**Deliverables:** narrowed scope and migration of tax fields to optional accounting metadata.  
**Acceptance:** core analysis runs with tax state unavailable; no UI wording implies Dutch or other tax advice.  
**Tests:** no-tax startup, optional import and accounting conservation.

#### USER-REQUIREMENTS DELTA — `ISSUE-0144`, `ISSUE-0145`, `ISSUE-0146` and `ISSUE-0176` — Secure local provider credentials

**Priority / size:** P0 / M  
**Why:** Plain-text `api_key` fields are not an acceptable user-facing credential design.

**Required delta**

- Store secrets outside YAML/Parquet/logs using Windows Credential Manager/DPAPI current-user protection by default and a reviewed fallback for portable/non-Windows mode.
- Separate secret value from non-secret provider configuration and status.
- Show masked values, source, last successful probe, scopes, quota and delete/rotate/test actions.
- Never expose secrets in CLI arguments, subprocess environment dumps, model prompts, screenshots, crash reports or audit packets.
- Make backups omit secrets by default and document same-user/same-machine recovery limits.

**Deliverables:** credential-store abstraction, Settings UI, migration scanner, redaction tests and recovery documentation.  
**Acceptance:** repository/config scan finds no secret material; missing keys degrade only dependent providers; a wrong key cannot leak in error text.  
**Tests:** sentinel-secret scans, DPAPI/current-user round trip, backup/restore, process/log redaction and no-key provider matrix.

#### USER-REQUIREMENTS DELTA — `ISSUE-0149` — Private self-research and generic guest-analysis boundary

**Priority / size:** P0/P1 / M  
**Why:** The owner may occasionally check an investment for another person, which can cross from general recommendation into personal advice if tailored to that person’s finances.

**Required delta**

- Define `SELF_RESEARCH` and `GENERIC_GUEST_RESEARCH`; prohibit a guest suitability/risk-capacity questionnaire or personalised allocation recommendation without separate legal approval.
- In guest mode, analyse the instrument and generic profiles only; do not use the guest’s income, assets, liabilities, tax, age, objectives or loss capacity.
- For distributable recommendation exports, include producer identity, date/time, facts versus opinion, sources, methodology, horizon, risks, update policy and conflicts/holdings disclosure fields.
- Record that a disclaimer alone does not cure personalised conduct.
- Require new legal review before public signals, paid reports, managed accounts or adviser functionality.

**Deliverables:** role/mode policy, generic report template and legal review matrix.  
**Acceptance:** guest mode cannot store personal financial profiles or claim suitability; exports are clearly general research with balanced upside/downside.  
**Tests:** personal-field rejection, role transitions, conflict disclosure and export-content smoke.

#### USER-REQUIREMENTS DELTA — `ISSUE-0150` — Coverage, survivorship and regional free-data audit

**Priority / size:** P0 / M  
**Why:** Free global stock/fund/bond data are structurally uneven and can bias top-*N* results toward well-covered US/large-cap instruments.

**Required delta**

- Add fund vehicle/share-class, NAV history, documents, holdings, fees, closure/merger/incubation and dealing-frequency coverage.
- Add selected-currency/FX coverage by source/date and unsupported cross rates.
- Report eligible/missing/rejected denominators by asset, country, sector, country×sector, profile, horizon, depth and provider.
- Compare ranking/forecast performance by coverage tier, listing status, size/liquidity and history length.
- Prevent “global top-*N*” labels when coverage does not meet declared market/asset thresholds.

**Deliverables:** expanded bias dashboard, run-level coverage certificate and audit export.  
**Acceptance:** every top-*N* view states its actual covered universe; closed/merged/delisted instruments remain in historical denominators.  
**Tests:** US-heavy coverage skew, incubated fund, missing FX and sparse-region fixtures.

#### USER-REQUIREMENTS DELTA — `ISSUE-0169`, `ISSUE-0142` and `ISSUE-0152` — User-contract parity release gate

**Priority / size:** P0 / M  
**Why:** Selected currency, exact horizon, risk profile, analysis depth and fund semantics must be release-enforced across every surface.

**Required delta**

- Expand the golden scenario with ordinary fund share classes, ETF listings, a foreign-currency stock, a bond, VWCE anchor and excluded products.
- Test raw-analysis invariance across risk profiles; test expected allowed differences across depth profiles.
- Verify exact horizon, output currency, FX, peer cohort, selected profile, depth manifest and recommendation parity in detail/bulk/screener/export.
- Add mutations for bank-versus-tech peer pooling, current-spot future conversion, hard-coded VWCE risk, plain-text API key and silent depth downgrade.
- Make core-analysis certification depend on this gate independently of portfolio/execution parity.

**Deliverables:** parity report v2, mutation catalogue and capability-lane release status.  
**Acceptance:** every deliberate semantic violation fails at its first divergent contract; core release cannot pass with a portfolio/broker shortcut.  
**Tests:** deterministic multi-asset E2E, mutation, source/package and selected-currency/profile/depth replay.

## Part VIII — Proposed new canonical issues

The current public registry reviewed for the underlying specification ended at `ISSUE-0152`; this consolidated proposal extends the provisional sequence through `ISSUE-0176`. Re-check the live registry immediately before issue creation. If any provisional ID has been claimed, renumber the proposed issues without changing their dependency semantics or release-lane priority.

### Fixed-income issue family

#### `ISSUE-0153` — Create the fixed-income instrument, terms and cash-flow identity master

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `data-platform`
- Phase: `phase-02-data-policy-identity`
- Codex slice: `M`
- Blocking dependencies: `ISSUE-0082`, `ISSUE-0083`, `ISSUE-0085`, provider registry
- Downstream: `ISSUE-0154`–`ISSUE-0158`
- Execution allowed: `false`

**Problem**

The repository has no canonical debt-security issue. A bond cannot be represented safely as a stock with a maturity field; contractual terms determine cash flows, accrued interest, yield conventions, risk, peer grouping and tradability.

**Required outcome**

Create a point-in-time terms master for initially supported fixed-rate and zero-coupon government/corporate bonds, with extensible records for floating-rate, inflation-linked, callable and amortising securities.

**In scope**

- issuer, guarantor, security, quotation and broker-contract identity;
- ISIN, CFI, LEI, currency, country and venue;
- issue, settlement and maturity dates;
- coupon rate/type/frequency, day-count, business-day, ex-coupon and payment calendars;
- face/notional, minimum denomination and increment;
- seniority, secured/subordinated status and ranking;
- call/put/amortisation schedule metadata;
- as-published/as-corrected terms, source documents, knowledge time and conflicts.

**Out of scope**

- convertible valuation, ABS/MBS waterfalls, perpetuals and structured notes;
- inferring missing terms from price;
- proprietary reference-data redistribution.

**Contracts / stores**

```text
FixedIncomeSecurityTerms
CouponSchedule
RedemptionSchedule
OptionalitySchedule
SettlementConvention
fixed_income_terms.parquet
```

Every record includes schema/version, valid/knowledge/retrieved time, source ID/hash, confidence and conflict state.

**Implementation requirements**

1. Extend the shared identity/classification interfaces rather than creating a parallel resolver.
2. Validate dates, rates, frequency, currency, denomination, calendars and schedule consistency.
3. Generate contractual cash-flow dates from terms and declared market calendars.
4. Record unsupported optionality/structure flags that block downstream claims.
5. Route conflicts through the existing evidence/source-priority framework.
6. Provide correction overlays that preserve original evidence.

**UI requirements**

- debt identity/terms panel with exact source/as-of/retrieved/conflict;
- contractual cash-flow schedule;
- capability/unsupported-structure warning;
- human correction overlay and history.

**Acceptance criteria**

- [ ] Golden fixed-rate and zero-coupon terms reproduce contractual schedules.
- [ ] Multiple bonds from one issuer remain distinct securities.
- [ ] Invalid/conflicted critical terms block pricing, screening and proposals.
- [ ] Historical replay uses the terms version known at the decision time.
- [ ] Every displayed term is traceable to source or declared overlay.

**Tests**

- golden government/corporate term fixtures across currencies/conventions;
- property tests for monotonic dates and redemption conservation;
- correction/restatement point-in-time replay;
- malformed/conflicting-source quarantine;
- schema migration.

**Audit/export:** terms version, sources, conflicts, generated schedule, overlays and capability flags.  
**Roll-out:** read-only analysis. Start with fixed-rate and zero-coupon securities; other coupon/index structures remain explicit unsupported/research states.

#### `ISSUE-0154` — Implement fixed-income cash-flow, clean/dirty pricing and yield/risk analytics

**Canonical metadata:** P0; owner `returns-and-risk`; phase `phase-05-returns-risk-portfolio`; slice M; depends on `ISSUE-0153`, `ISSUE-0085`, `ISSUE-0088`; execution false.

**Problem**

Deterministic debt analytics are required before ML forecasts or rankings. Price, accrued interest, yield and rate sensitivity depend on settlement and market convention.

**Required outcome**

Create a transparent pricing/analytics service for supported bonds and a differential-validation harness against a pinned, licence-reviewed open-source reference implementation.

**In scope**

- contractual cash flows and accrued interest;
- clean/dirty price conversion and settlement cash;
- current yield, yield to maturity, yield to call and yield to worst where terms permit;
- Macaulay/modified duration, convexity, DV01/PV01;
- curve-discounted deterministic value and scenario repricing;
- observed-price versus model/curve value, with discrepancy.

**Out of scope:** treating YTM/YTW as guaranteed expected return; unvalidated OAS for complex options; executable dealer quotation.

**Contracts / stores**

```text
FixedIncomeValuationInput
FixedIncomeValuationResult
BondAnalyticsRecord
bond_analytics.parquet
```

Fields include settlement, convention, clean/dirty, accrued, yields, duration, convexity, DV01, curve/source, warnings and input hash.

**Implementation requirements**

1. Implement schedule-based present value and conversions with explicit units.
2. Declare compounding/yield conventions.
3. Calculate YTC for every valid call and choose YTW transparently.
4. Separate observed market-price analytics from curve/model valuation.
5. Pin QuantLib or OpenGamma Strata after licence review and use differential fixtures.
6. Quarantine material differential discrepancies.

**UI requirements:** price/accrued/settlement card; coupon/current yield/YTM/YTC/YTW; duration/convexity/DV01; observed-versus-model value; assumption/warning panel.

**Acceptance criteria**

- [ ] Clean→dirty→clean and price→yield→price round trips pass declared tolerance.
- [ ] Accrued interest handles boundaries, stubs, ex-coupon and settlement correctly.
- [ ] YTW selects the lowest valid maturity/call yield.
- [ ] Approved reference fixtures match within tolerance.
- [ ] Yield assumptions and limitations are visible.

**Tests:** golden reference bonds; leap year, ex-coupon, stub, negative-yield and near-maturity cases; price/yield properties; differential and mutation tests.  
**Audit/export:** full inputs, convention, curve/price source, reference version and discrepancy result.  
**Roll-out:** deterministic evidence only; no positive recommendation or live debt authority follows automatically.

#### `ISSUE-0155` — Add fixed-income reference, curve, trade and liquidity data adapters

**Canonical metadata:** P0/P1; owner `data-platform`; phase `phase-02-data-policy-identity`; core M plus S provider children; depends on `ISSUE-0076`, `ISSUE-0081`, `ISSUE-0088`, `ISSUE-0149`, `ISSUE-0153`; execution false.

**Problem**

There is no free complete global debt tape. Reference terms, curves, trades, liquidity and issuer filings come from distinct sources and licences.

**Required outcome**

Define a provider-neutral fixed-income observation contract and implement lawful official/public adapters as isolated children.

**Initial source scope**

- ECB euro-area curves and official macro/risk-free series;
- ESMA FIRDS/FITRS reference/liquidity files where terms permit;
- FINRA fixed-income/TRACE public services under their current agreement;
- official issuer/regulator offering documents and filings;
- user/broker-imported prices/trades with explicit authority.

**Contracts / stores**

```text
FixedIncomeMarketObservation
YieldCurveSnapshot
BondLiquidityObservation
fixed_income_provider_coverage.parquet
```

Required fields: security, observation type, clean/dirty/yield/spread, bid/ask/size, valid/knowledge/retrieved times, indicative/evaluated/executable label, source authority, licence/retention and quality.

**Implementation requirements**

1. Freeze canonical schemas before provider children.
2. Store immutable raw objects and content hashes.
3. Implement rate limits, resume, revisions and schema-drift detection.
4. Reconcile terms, prices, yields and liquidity across sources without overwrite.
5. Publish coverage by market, rating, currency, duration, size and history.
6. Never label evaluated/stale price executable.

**UI requirements:** provider health/coverage; source/age-labelled price/trade history; conflict and availability state.

**Acceptance criteria**

- [ ] No source silently overwrites another.
- [ ] Historical runs use only then-known observations.
- [ ] Provider failure does not corrupt other markets.
- [ ] Terms/licence/retention approval exists before enabling an adapter.
- [ ] Missing tape/quote prevents precise liquidity/execution claims.

**Tests:** recorded official-source fixtures, rate-limit/resume/failure injection, schema drift, conflicts and licence-disable state.  
**Audit/export:** provider, terms record, raw hash, retrieval, coverage, quality and conflict.  
**Roll-out:** enable each adapter independently; lawful low-authority contractual analysis can remain available when market observations are missing.

#### `ISSUE-0156` — Implement fixed-income rate, curve, spread, credit, liquidity and optionality risk

**Canonical metadata:** P0/P1; owner `returns-and-risk`; phase `phase-05-returns-risk-portfolio`; slice M; depends on `ISSUE-0154`, `ISSUE-0155`, `ISSUE-0091`, `ISSUE-0111`; execution false.

**Problem**

Duration alone does not represent credit, spread, call, reinvestment, liquidity, inflation and FX risks.

**Required outcome**

Produce a transparent fixed-income risk record and scenario decomposition integrated with common portfolio risk.

**In scope**

- parallel and key-rate curve shocks;
- duration/convexity approximation and full repricing;
- spread/credit scenarios, rating change, default/recovery and issuer concentration;
- liquidity/quote age/minimum size and estimated liquidation warning;
- call/reinvestment, inflation and FX flags;
- bond versus bond-ETF distinction.

**Contracts / stores**

```text
FixedIncomeRiskRecord
BondScenarioResult
```

Each component includes model/method, mapping, assumptions, support, coverage and unknown amount.

**Implementation requirements**

1. Map supported securities to curve, spread/credit proxy and scenarios.
2. Calculate key sensitivities and scenario P&L with declared units.
3. Add default/recovery distributions only where inputs are explicit.
4. Integrate component/marginal risk into portfolio records.
5. Record full-reprice versus approximation method and discrepancy.

**UI requirements:** rates/spread/credit/liquidity/call/inflation/FX risk ladder; scenario table; price-yield chart; portfolio duration/DV01/credit contribution.

**Acceptance criteria**

- [ ] Small-shock approximation agrees with full reprice within expected bounds.
- [ ] Unknown spread/default inputs are visible and cannot be silently zero.
- [ ] Scenario totals reconcile to portfolio stress.
- [ ] A low-duration security cannot be labelled low risk without other components.

**Tests:** parallel/non-parallel curve, default/recovery, callable warning, sign/unit and aggregation fixtures.  
**Audit/export:** mappings, shocks, assumptions, coverage and lineage.  
**Roll-out:** risk may block an action; it never authorises one.

#### `ISSUE-0157` — Build fixed-income expected total-return distributions, peers and screener

**Canonical metadata:** P0/P1; owner `returns-and-risk`; phase `phase-05-returns-risk-portfolio`; slice M; depends on `ISSUE-0098`, `ISSUE-0108`, `ISSUE-0109`, `ISSUE-0112`, `ISSUE-0120`, `ISSUE-0123`, `ISSUE-0154`–`ISSUE-0156`; execution false.

**Problem**

Yield is not a short-horizon total-return forecast. A debt screener must account for carry, pull-to-par/roll-down, rates, spread, default, FX, costs and uncertainty.

**Required outcome**

Create point-in-time debt peer cohorts, deterministic baselines and calibrated horizon-specific total-return distributions for supported securities.

**In scope**

- peer keys: sovereign/corporate, issuer sector/country, currency, seniority, rating, coupon type, maturity/duration and liquidity;
- return decomposition: coupon/accrual, pull-to-par/roll, rates, spread, default/recovery, FX and costs;
- q05–q95, loss, beat-cash and beat-benchmark probabilities;
- data/liquidity gates, robust percentile, rank stability and top-*N*;
- deterministic scenario baseline before learned residual challengers.

**Out of scope:** pooling raw stock and debt scores; treating yield/rating as sufficient; sparse local-model promotion.

**Contracts / stores:** `FixedIncomePeerCohort`, `FixedIncomeReturnDecomposition`, common `AnalysisSnapshot`, per-horizon calibration/outcome records.

**Implementation requirements**

1. Define leaf/parent peer hierarchy and support thresholds.
2. Build carry/roll/scenario baseline.
3. Add learned residual only through Training Centre/validation.
4. Calibrate by supported rating/duration/currency/liquidity segment.
5. Integrate screener gates, costs and portfolio fit.

**UI requirements:** debt screener with yield/YTW, duration, risk, distribution, liquidity, peer support, CI and blockers.

**Acceptance criteria**

- [ ] Baseline exists for each supported complete-terms security.
- [ ] A higher yield caused by higher risk cannot automatically improve recommendation.
- [ ] Forecast is calibrated or explicitly research-only/unavailable.
- [ ] Every rejected/unavailable row is persisted.
- [ ] Ranking is reproducible from frozen inputs/seeds.

**Tests:** carry/roll identities; peer fallback/bootstrap; cost/default/rate sensitivity; point-in-time validation.  
**Audit/export:** decomposition, peer, distribution, calibration and gates.  
**Roll-out:** advisory-only; learned models require forward evidence.

#### `ISSUE-0158` — Create bond detail, portfolio maturity ladder and fixed-income income views

**Canonical metadata:** P1; owner `frontend-and-api`; phase `phase-08-frontend-api`; slice M; depends on `ISSUE-0136`–`ISSUE-0140`, `ISSUE-0153`–`ISSUE-0157`, `ISSUE-0161`, `ISSUE-0162`; execution false.

**Problem**

Debt evidence is unusable if buried in generic stock fields. Portfolio users need contractual cash flows, maturity and rate/credit exposure.

**Required outcome**

Add asset-aware debt detail and portfolio fixed-income views using common analysis, ledger and exposure contracts.

**In scope**

- terms, clean/dirty price, accrued, yield, duration/convexity/DV01, risk and forecast;
- coupon/principal schedule, next payment, call dates and source documents;
- maturity/cash-flow ladder;
- duration, rating, issuer, sector, country and currency exposure;
- expected income/maturity proceeds with confidence.

**Implementation requirements**

1. Build reusable typed fixed-income components.
2. Aggregate maturity/cash-flow schedules with coverage.
3. Link each holding to the same `AnalysisSnapshot` as screener/detail.
4. Explain assumptions and unsupported optionality.

**Acceptance criteria**

- [ ] UI values reconcile to API/export.
- [ ] Coverage/source dates are visible.
- [ ] Unsupported structures are prominently warned.
- [ ] Cash-flow and maturity totals reconcile to positions/terms.

**Tests:** component, visual/responsive/accessibility, API/UI parity and empty state.  
**Audit/export:** all displayed tables and source links.  
**Roll-out:** read-only; paper/live debt trading remains separate and disabled.

### Portfolio performance and intelligence issues

#### `ISSUE-0159` — Implement daily portfolio valuation history and standards-aligned performance measurement

**Canonical metadata**

- Priority: `P0`
- Owner: `returns-and-risk`
- Phase: `phase-05-returns-risk-portfolio`
- Codex slice: `M`
- Blocking dependencies: `ISSUE-0084`, `ISSUE-0085`, `ISSUE-0127`
- Downstream: `ISSUE-0116`, `ISSUE-0160`–`ISSUE-0163`, `ISSUE-0168`
- Execution allowed: `false`

**Problem**

The requested absolute and relative performance charts cannot be calculated reliably from current holdings or by subtracting purchases. They require ledger-derived daily values and explicit external-flow classification.

**Required outcome**

Create immutable daily portfolio snapshots and calculate market value, invested capital, investment P&L, TWR, MWR/XIRR and a labelled Modified Dietz fallback in the user-selected output currency (EUR by default) and supported local currencies.

**In scope**

- daily/end-of-period positions, cash, accrued income, prices, FX, pending/settled state and valuation quality;
- contributions/withdrawals as external flows; buys/sells/income as internal;
- TWR under a declared flow-timing policy;
- MWR/XIRR and Modified Dietz fallback;
- gross/net, benchmark/cash and inception/period return;
- missing/stale valuation, partial periods and coverage.

**Contracts / stores**

```text
DailyPortfolioSnapshot
ExternalCashFlow
PortfolioPerformancePeriod
portfolio_valuations.parquet
portfolio_performance.parquet
```

Required formula/version metadata and snapshot hashes are stored with every result.

**Implementation requirements**

1. Rebuild daily positions/cash from the ledger.
2. Value assets/accrued income in local currency and the selected output currency, with EUR as the default.
3. Classify external flows explicitly.
4. Calculate sub-period returns and geometrically link TWR.
5. Solve dated MWR and label annualisation/de-annualisation.
6. Calculate investment P&L and reconciliation components.
7. Persist quality/coverage and never overwrite historical snapshots.

**UI requirements:** reconciliation/quality preview and calculation-method disclosure before visual charts consume the series.

**Acceptance criteria**

- [ ] A contribution changes value/invested capital but not same-instant TWR.
- [ ] A purchase funded from existing cash changes neither total value nor external flow.
- [ ] Dividends/coupons increase investment P&L and remain internal.
- [ ] Fees/tax reduce P&L without becoming withdrawals.
- [ ] Period and inception results reproduce from saved daily snapshots.
- [ ] Sub-year MWR is de-annualised or clearly labelled annualised.
- [ ] Stale/missing values cannot produce false precise performance.

**Tests**

- standards-style cash-flow examples;
- deposit, withdrawal, buy, sell, dividend, coupon, fee, tax and FX fixtures;
- property: TWR invariance to splitting same-time external contribution;
- MWR solver edge cases and Modified Dietz fallback;
- ledger-to-snapshot reconciliation;
- multi-account consolidation.

**Audit/export:** daily values, flow classification, formula version, quality, benchmark/cash and period results.  
**Roll-out:** user-facing only after ledger/valuation reconciliation; gaps remain partial and visible.

#### `ISSUE-0160` — Build selectable portfolio value, selected-currency P&L and percentage-performance charts

**Canonical metadata:** P0/P1; owner `frontend-and-api`; phase `phase-08-frontend-api`; slice M; depends on `ISSUE-0139`, `ISSUE-0159`; execution false.

**Problem**

The user requires adjustable absolute and relative graphs and quarterly/yearly bars. Ambiguous labels can confuse new contributions with investment gains.

**Required outcome**

Implement a portfolio visualisation suite with explicit metrics, date range, aggregation, benchmark and cash-flow overlays.

**In scope**

- line/toggle views for portfolio value, net invested capital, investment P&L, TWR index/% and drawdown in the selected output currency;
- quarterly/yearly bars for ending value, investment P&L, TWR (%), income, fees/tax, FX and net contributions in the selected output currency;
- inception, YTD, 1M/3M/6M/1Y/3Y/5Y and custom range;
- day/week/month/quarter/year aggregation;
- benchmark/cash, gross/net and per-account/consolidated modes;
- partial-period, stale/coverage and external-flow markers.

**Out of scope:** calculating returns in UI; unclear dual axes; presenting interpolated missing valuations as fact.

**Contracts:** typed chart series from saved daily/period performance records, including units, partial flag and source snapshot.

**Implementation requirements**

1. Aggregate in the application/service layer, not presentation code.
2. Return metric, unit, period boundary, partial flag and quality for each point.
3. Build accessible line/bar components with data download.
4. Persist local view preferences without changing calculations.
5. Tooltips reconcile value, flow, P&L and return.

**Acceptance criteria**

- [ ] Quarter/year bars reconcile to selected-period result.
- [ ] Changing view/range never alters stored returns.
- [ ] Contributions/withdrawals are visually separate from gain/loss.
- [ ] The selected currency and percentage formats use the chosen locale; EUR remains the default European presentation.
- [ ] Empty/partial/stale states are informative.

**Tests:** golden series; partial/no-flow/multiple-flow/negative periods; visual/accessibility/responsive; CSV parity.  
**Audit/export:** selected series and chart configuration, not only screenshots.  
**Roll-out:** TWR default; MWR optional secondary measure.

#### `ISSUE-0161` — Build the portfolio holdings analysis table and cross-surface drill-down

**Canonical metadata:** P0/P1; owner `frontend-and-api`; phase `phase-08-frontend-api`; slice M; depends on `ISSUE-0074`, `ISSUE-0127`, `ISSUE-0138`, `ISSUE-0139`, `ISSUE-0159`; execution false.

**Problem**

Portfolio holdings must display the same analysed data, scores and expected gain/loss as analyser/screener while adding position-specific values.

**Required outcome**

Create a sortable, filterable, expandable holdings table keyed to one selected portfolio and analysis snapshot.

**In scope**

- quantity/face, local/output-currency value, weight, cost basis, realised/unrealised P&L, income and fees;
- evidence/quality/risk scores, peer rank, action and blockers;
- expected return distribution and expected gain/loss in the user-selected output currency by exact horizon;
- data/model/policy as-of, stale/conflict and coverage;
- instrument detail, transactions/lots, event and portfolio-impact drill-down;
- stock/ETF/bond-aware columns.

**Contracts:** holding projection references portfolio snapshot, performance snapshot and exact `analysis_run_id`.

**Implementation requirements**

1. Join through canonical identity.
2. Calculate position-specific forecast impact in the selected output currency only from the stored distribution and FX scenario.
3. Prevent silent mixing of different analysis dates/policies.
4. Add refresh/select-run workflow and explicit missing analysis.
5. Support column presets and large-table virtualisation.

**Acceptance criteria**

- [ ] Analyser core values are identical for the same analysis ID.
- [ ] Horizon selection updates all forecast columns consistently.
- [ ] Old/missing analysis is explicit and cannot create a proposal.
- [ ] Portfolio values reconcile to the selected snapshot.

**Tests:** cross-surface parity; snapshot mismatch; mixed-asset, sorting/filtering and large-table tests.  
**Audit/export:** holding, portfolio/performance snapshot and linked analysis IDs.  
**Roll-out:** read-only; proposal action routes to `ISSUE-0130`.

#### `ISSUE-0162` — Implement coverage-aware portfolio exposure, look-through and concentration charts

**Canonical metadata:** P1; owner `returns-and-risk`; phase `phase-05-returns-risk-portfolio`; slice M; depends on `ISSUE-0022`, `ISSUE-0083`, `ISSUE-0105`, `ISSUE-0127`, `ISSUE-0153`; execution false.

**Problem**

Sector/country/currency pie charts can be materially false when ETF holdings or classifications are incomplete.

**Required outcome**

Create dated direct, indirect and combined exposure cubes with mapped coverage and unknown conservation.

**Dimensions**

- asset class;
- sector/industry;
- economic country/region and legal/listing country where useful;
- trading, reporting and estimated economic currency;
- issuer/entity;
- market-cap/liquidity;
- factor/systematic/specific risk where available;
- bond issuer type, rating, maturity, duration and seniority.

**Contracts / stores:** `PortfolioExposureCube` with portfolio/snapshot, dimension, view mode, amount, percentage, coverage, source and contributor links.

**Implementation requirements**

1. Aggregate legal holdings and dated look-through under a declared metric registry.
2. Conserve total value across mapped and unknown buckets.
3. Create top-*N*/Other presentation only after full calculation.
4. Preserve direct/indirect contributors and dated holdings source.
5. Expose stale/incomplete look-through and never proportional-fill unknowns.

**UI requirements:** pie/donut plus table; direct/look-through/combined selector; coverage badge; unknown segment; click-through to contributors.

**Acceptance criteria**

- [ ] Every percentage view totals 100% including unknown within tolerance.
- [ ] Coverage is never implied complete when it is not.
- [ ] Currency categories distinguish trading/reporting/economic meanings.
- [ ] Nested ETFs and direct duplicates are handled deterministically.

**Tests:** conservation properties, nested ETFs, missing holdings and mixed stock/bond/cash.  
**Audit/export:** complete exposure cube and aggregation policy.  
**Roll-out:** read-only; concentration blockers require separate versioned policy.

#### `ISSUE-0163` — Implement portfolio income, event, maturity and liquidity calendar

**Canonical metadata:** P1; owner `frontend-and-api`; phase `phase-08-frontend-api`; slice M; depends on `ISSUE-0024`, `ISSUE-0084`, `ISSUE-0127`, `ISSUE-0153`, `ISSUE-0158`, `ISSUE-0161`; execution false.

**Problem**

A portfolio user needs to know when cash, filings, dividends, coupons, maturities, distributions and calls may affect holdings and liquidity.

**Required outcome**

Create one chronological, source-ranked portfolio calendar and projected cash-flow view.

**In scope**

- stock results, filings, dividends and corporate actions;
- ETF distributions, holdings/methodology/report updates, rebalances and closure events;
- bond coupon, maturity, call/put/tender, reset and redemption;
- expected versus confirmed, source authority, timezone, confidence and affected exposure;
- projected monthly/quarterly income and maturity proceeds;
- event blackout hooks for proposal controls.

**Out of scope:** inventing dates; presenting pattern estimates as confirmed; tax advice.

**Contracts:** `PortfolioEvent`, `ProjectedCashFlow`, event versions and holding links.

**Implementation requirements**

1. Consume official documents/actions and contractual debt cash flows.
2. Deduplicate/supersede events without deleting versions.
3. Aggregate local and selected-output-currency cash flows with explicit FX source and coverage.
4. Classify confirmed, estimated, cancelled and revised.
5. Publish event-risk/blackout fields to controls.

**Acceptance criteria**

- [ ] Confirmed and estimated events are distinct.
- [ ] Projected cash flows reconcile to holdings/terms.
- [ ] Changed/cancelled events preserve history.
- [ ] Missing FX/terms produce coverage warning.

**Tests:** timezone/revision/dedup; dividend/coupon/maturity aggregation; missing-data fixtures.  
**Audit/export:** event versions, sources, cash flows, affected exposure.  
**Roll-out:** context/planning; an event may block a proposal but cannot create a signal.

#### `ISSUE-0164` — Add portfolio goals, constraints, alerts and pre-trade what-if analysis

**Canonical metadata:** P1; owner `programme-governance`; phase `phase-05-returns-risk-portfolio`; slice M; depends on `ISSUE-0113`–`ISSUE-0116`, `ISSUE-0127`, `ISSUE-0161`–`ISSUE-0163`; execution false.

**Problem**

A portfolio can contain individually attractive instruments while failing diversification, liquidity, income, currency or risk objectives.

**Required outcome**

Allow versioned non-advisory constraints and simulate changes before creating a proposal.

**In scope**

- target weights/bands, cash reserve and max position/sector/country/currency/issuer;
- duration/rating, income, maturity and liquidity constraints;
- alerts for drift, concentration, drawdown, stale data, events, maturities and forecast deterioration;
- add/remove/resize/rebalance what-if with after-trade value, return distribution, risk, cost and exposure;
- binding-constraint and rejected-candidate explanations.

**Out of scope:** regulated suitability judgement; guaranteed goals; direct order submission.

**Contracts:** `PortfolioPolicy`, `Alert`, `WhatIfScenario`, `ConstraintResult`, versions and acknowledgement history.

**Implementation requirements**

1. Build policy editor with validation/version history.
2. Run what-if through existing optimisation/risk/cost services.
3. Never mutate the ledger from a simulation.
4. Persist alert acknowledgement/snooze without deleting the condition.
5. Route accepted what-if to a new draft proposal only.

**Acceptance criteria**

- [ ] What-if leaves live portfolio unchanged.
- [ ] Constraints evaluate after-trade state.
- [ ] Alerts reproduce from their source snapshot.
- [ ] No constraint is silently relaxed.

**Tests:** constraint properties, simulation isolation, alert dedup/resolve/reopen.  
**Audit/export:** policy, scenario, result, alerts and acknowledgements.  
**Roll-out:** advisory only; explicit user action is required for a draft proposal.

### Bulk, execution-accounting and parity issues

#### `ISSUE-0165` — Implement a canonical resumable bulk analysis-run orchestrator

**Canonical metadata:** P0; owner `application-platform`; phase `phase-08-frontend-api`; slice M; depends on `ISSUE-0018`, `ISSUE-0020`, `ISSUE-0074`, `ISSUE-0077`, `ISSUE-0081`, `ISSUE-0126`; execution false.

**Problem**

A bulk downloader and screener UI do not guarantee that thousands of instruments are analysed under one sealed data/policy snapshot with durable status.

**Required outcome**

Create an application service that freezes, schedules, executes and persists canonical bulk analysis runs.

**In scope**

- run definition: universe, horizons, asset types, provider policy, data cut-off, model/policy versions and resource profile;
- shard state, progress, cancellation, resume, bounded retries and per-instrument isolation;
- canonical `AnalysisSnapshot` creation;
- exact state for eligible, blocked, unavailable and failed;
- new-version incremental rerun of changed instruments;
- saved-run comparison and audit export.

**Out of scope:** provider-specific download logic; a second score engine; orders from top-*N*.

**Contracts / stores**

```text
BulkAnalysisRun
BulkAnalysisTask
BulkAnalysisResult
bulk_run_manifest.json
```

Each task includes idempotency key, input/output hashes, stage, attempt, timestamps, error class and linked analysis ID.

**Implementation requirements**

1. Freeze all input snapshot IDs before scheduling.
2. Schedule bounded shards through existing task infrastructure.
3. Reuse content-addressed cache/intermediate artefacts.
4. Persist all outcomes and aggregate only after full or explicitly partial completion.
5. Support cancel/resume/retry without changing the frozen run.
6. Add run lineage and compare.

**UI requirements:** configuration, stage/progress, logs, cancellation, failure download, saved runs and comparison. Do not show a fabricated time estimate.

**Acceptance criteria**

- [ ] Resumed run preserves hashes and completed results.
- [ ] Individual analysis equals stored bulk result for same run.
- [ ] Partial completion states exact denominator/coverage.
- [ ] A new run never overwrites history.
- [ ] One failed instrument/provider does not abort unrelated tasks.

**Tests:** 1,000-instrument synthetic load/soak; crash/resume/idempotency; mixed failures; parity; resource limits.  
**Audit/export:** manifest, task statuses/results, logs, versions and checksums.  
**Roll-out:** read-only. Top-*N* consumes the store; no automatic proposal.

#### `ISSUE-0166` — Implement cross-asset top-*N* selection and portfolio-fit ranking

**Canonical metadata:** P0/P1; owner `returns-and-risk`; phase `phase-05-returns-risk-portfolio`; slice M; depends on `ISSUE-0020`, `ISSUE-0108`–`ISSUE-0112`, `ISSUE-0113`, `ISSUE-0128`, `ISSUE-0157`, `ISSUE-0165`; execution false.

**Problem**

Selecting stocks, ETFs and bonds together by raw score is mathematically and economically invalid.

**Required outcome**

Provide two explicit modes: asset-specific top-*N* and cross-asset portfolio-fit selection under a visible utility/constraint policy.

**In scope**

- hard eligibility and asset-specific peer ranking;
- net expected return distribution, risk, liquidity, cost, evidence and stability;
- user asset-allocation ranges and portfolio marginal impact;
- diversification-aware greedy/optimiser selection;
- top-*N* selection probability, rank stability and exclusion funnel;
- deterministic tie-breaking and why-selected/why-not.

**Out of scope:** one opaque universal score; unconstrained expected-return maximisation; automatic order creation.

**Contracts:** `SelectionPolicy`, `SelectionCandidate`, `SelectionRun`, selected/rejected reasons and source snapshots.

**Implementation requirements**

1. Build asset-specific candidate sets first.
2. Normalise only common probabilistic/risk/cost fields under a declared utility.
3. Apply portfolio constraints/marginal impact.
4. Bootstrap selection stability and persist probability.
5. Make all utility weights and constraints versioned/user-visible.

**UI requirements:** per-asset versus cross-asset mode, policy summary, top-*N*, confidence, marginal impact and exclusion funnel.

**Acceptance criteria**

- [ ] Raw asset-specific scores are never directly pooled.
- [ ] Hard-gate failures cannot be selected.
- [ ] Run reproduces from frozen inputs/seeds.
- [ ] Portfolio/constraint change creates a new run.
- [ ] Without a portfolio, cross-asset mode uses an explicit reference portfolio or remains unavailable.

**Tests:** synthetic cross-asset, constraints/diversification, bootstrap reproducibility and no-portfolio fallback.  
**Audit/export:** all candidates, common metrics, utility, constraints, selected/rejected reasons and hashes.  
**Roll-out:** advisory; explicit user action is needed to add to what-if/draft proposal.

#### `ISSUE-0167` — Implement settlement, buying-power, cash reservation and deterministic order-state accounting

**Canonical metadata:** P0 before broker writes; owner `trading-safety`; phase `phase-07-backtest-paper-execution`; slice M; depends on `ISSUE-0085`, `ISSUE-0114`, `ISSUE-0127`, `ISSUE-0130`, `ISSUE-0131`; downstream `ISSUE-0132`–`ISSUE-0135`; execution false until later authority.

**Problem**

A valid proposal can overspend or fail because cash, FX, settlement, accrued interest, open orders and broker buying power change between proposal and submission.

**Required outcome**

Create a deterministic reservation and order-lifecycle service shared by paper and live modes.

**In scope**

- available, settled, unsettled and reserved cash by currency/account;
- security quantity/face reservation and minimum denomination;
- fees, tax, accrued interest and FX reservation;
- local idempotency key plus broker/local/permanent IDs;
- append-only order lifecycle: draft, approved, reserved, submitting, acknowledged, partial, filled, cancel, rejected, unknown and reconciliation-required;
- expiry/release/reconciliation of reservations.

**Out of scope:** broker strategy logic; automatic resubmission of unknown/rejected orders; initial margin/leverage.

**Contracts / stores**

```text
CashAvailability
OrderReservation
OrderLifecycleEvent
OrderStateProjection
```

**Implementation requirements**

1. Calculate available resources from ledger, broker sync and open reservations.
2. Reserve atomically before submission.
3. Use stable idempotency keys and prevent duplicate broker intent.
4. Handle duplicate, missing and out-of-order callbacks.
5. Adjust reservation for partial fills/cancels/rejects.
6. Move uncertain state to `RECONCILIATION_REQUIRED` and block related orders.

**UI requirements:** preview with cash/quantity/settlement, lifecycle timeline and reconciliation break; operator controls subject to authority.

**Acceptance criteria**

- [ ] Concurrent proposals cannot spend the same resources.
- [ ] Duplicate submission produces one broker intent.
- [ ] Partial fills adjust reservations exactly.
- [ ] Unknown state is never automatically retried.
- [ ] Paper and live use the same lifecycle contract.

**Tests:** concurrent reservation properties; duplicate/out-of-order callbacks; partial/cancel/reject/reconnect; multi-currency and debt accrued settlement.  
**Audit/export:** every lifecycle event, reservation, ID, reconciliation and operator action.  
**Roll-out:** must close before broker-write modes; implementation begins in paper/read-only state.

#### `ISSUE-0168` — Add portfolio forecast aggregation and expected gain/loss scenario views

**Canonical metadata:** P1; owner `returns-and-risk`; phase `phase-05-returns-risk-portfolio`; slice M; depends on `ISSUE-0108`–`ISSUE-0111`, `ISSUE-0115`, `ISSUE-0127`, `ISSUE-0161`; execution false.

**Problem**

Holding forecasts cannot be added independently because returns are correlated and coverage/model uncertainty differs.

**Required outcome**

Aggregate supported holding distributions into portfolio expected gain/loss and risk scenarios with explicit covariance, coverage and uncertainty.

**In scope**

- current-holdings total-return distribution by selectable horizon;
- expected gain/loss in the selected output currency and percentage, q05–q95, loss/benchmark/cash probabilities;
- price, income, FX and cost contribution;
- covariance/correlation, tail dependence and model disagreement;
- current versus what-if/target comparison;
- unknown/unsupported exposure and confidence.

**Out of scope:** summing independent point forecasts; guaranteed target value.

**Contracts:** `PortfolioForecastSnapshot` keyed to portfolio and a compatible set of analysis/risk snapshots.

**Implementation requirements**

1. Resolve horizon-aligned holding distributions and risk model.
2. Aggregate through scenarios/simulation with saved seeds/configuration.
3. Treat unsupported assets as unknown/conservative policy, never zero risk.
4. Store components, covariance and reconciliation.
5. Show sensitivity to costs and correlation regime.

**UI requirements:** portfolio fan chart, expected selected-currency range, probability cards, contributors, coverage and assumptions.

**Acceptance criteria**

- [ ] One sealed portfolio and compatible analysis set is used.
- [ ] Unknown coverage affects confidence visibly.
- [ ] Nonlinear statistics are not falsely decomposed as additive.
- [ ] Scenario output is reproducible.

**Tests:** analytical correlated two-asset cases; missing coverage; FX/cost/income; seeded scenarios and stress.  
**Audit/export:** inputs, covariance/risk version, seeds/configuration, coverage and output.  
**Roll-out:** advisory; may inform optimiser/proposal but no authority.

#### `ISSUE-0169` — Implement canonical analysis parity and deterministic replay tests across workflows

**Canonical metadata:** P0; owner `quality-and-release`; phase `phase-09-quality-release-security`; slice M; depends on `ISSUE-0074`, `ISSUE-0136`, `ISSUE-0142`, `ISSUE-0161`, `ISSUE-0165`, `ISSUE-0167`; downstream `ISSUE-0152`; execution false.

**Problem**

The central requirement—one set of data and calculations everywhere—must be release-enforced, not assumed.

**Required outcome**

Create a release-blocking parity/replay harness spanning detail, bulk/screener, portfolio, backtest/paper and proposal/order workflows.

**In scope**

- frozen multi-asset golden scenario with stock, ETF, bond, cash, flows and events;
- `AnalysisSnapshot` hash/value parity across detail, bulk and holdings;
- shared decision-kernel parity across current, backtest and paper;
- ledger/performance/chart/export reconciliation;
- proposal/order trace to exact snapshots/policies;
- source versus packaged application differential.

**Out of scope:** pixel-perfect visual identity; tolerances that hide semantic differences.

**Contracts:** machine-readable parity report with dependency graph, first divergence, tolerances and release status.

**Implementation requirements**

1. Build deterministic fixtures with fixed clocks/provider responses.
2. Execute all workflows from one fixture.
3. Compare IDs/versions/sources/actions exactly and numerical values under declared tolerance.
4. Emit first divergent stage and dependency path.
5. Add to CI, package smoke and audit packet.
6. Add a mutation test introducing a second calculation path.

**UI requirements:** Diagnostics parity status and first mismatch; no completion badge when failed.

**Acceptance criteria**

- [ ] Canonical identifiers, versions, sources, actions and blockers agree.
- [ ] Deliberate alternative calculation fails.
- [ ] Packaged/source results agree.
- [ ] Ledger, performance charts and export reconcile.
- [ ] Every order proposal traces to the exact analysis/portfolio/policy snapshot.

**Tests:** golden end-to-end, mutation, source/package differential and audit replay.  
**Audit/export:** parity report, fixture hashes and divergence trace.  
**Roll-out:** release blocker for the expanded product and every execution authority.


### User-priority fund, currency, risk-profile, workload and provider issues

#### `ISSUE-0170` — Create the ordinary-fund vehicle, sub-fund, share-class, dealing and lifecycle identity master

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `data-platform`
- Phase: `phase-02-data-policy-identity`
- Codex slice: `M`
- Blocking dependencies: `ISSUE-0076`, `ISSUE-0082`, `ISSUE-0083`, `ISSUE-0085`, `ISSUE-0149`
- Downstream: `ISSUE-0171`, `ISSUE-0172`, `ISSUE-0165`, `ISSUE-0166`
- Execution allowed: `false`

**Problem**

The prior capability matrix treats non-exchange funds as import/valuation objects. A lawful fund analyser needs stable identity across legal vehicle, umbrella, compartment/sub-fund, share class, dealing channel and historical lifecycle. Treating an ordinary fund as an ETF without a listing creates false market-price, spread and liquidity claims.

**Required outcome**

Create a point-in-time ordinary-fund master that supports open-ended mutual/index funds and explicit rejection of unsupported structures. Preserve economic-strategy links without collapsing share-class-specific fees, currencies, distributions or returns.

**In scope**

- legal fund/vehicle, umbrella and compartment/sub-fund identity;
- share class, ISIN and national/provider identifiers;
- manager, management company, depositary/custodian, domicile and regulator/register references;
- active/passive/index, benchmark/objective and asset/region/sector mandate;
- accumulating/distributing, retail/institutional, clean/adviser and hedged/unhedged class fields;
- base, share-class, dealing, reporting and hedge currencies;
- NAV and dealing frequency, valuation/dealing point, cut-off, notice, settlement, minimum initial/additional investment and gates/suspensions;
- ongoing charges, management/performance fee, entry/exit/redemption/dilution fees and fee-effective dates;
- master/feeder, fund-of-funds and share-class/economic-strategy relationships;
- inception, public-launch/ticker-creation, closed, soft-closed, merged, converted, liquidating and terminated histories;
- manager, mandate, benchmark and fee changes with valid/knowledge time;
- source document/link/hash, authority, conflicts and manual correction overlays.

**Out of scope**

- guaranteed NAV or tradability;
- treating issuer marketing as complete holdings data;
- money-market, hedge/private-equity, closed-end, structured or insurance wrappers unless separately accepted;
- tax/suitability advice.

**Contracts / stores**

```text
FundVehicle
FundSubFund
FundShareClass
FundDealingTerms
FundFeeSchedule
FundLifecycleEvent
FundRelationship
fund_identity.parquet
fund_dealing_terms.parquet
fund_lifecycle.parquet
```

Every record includes schema, valid/knowledge/retrieved times, source/hash, authority, confidence and conflict state.

**Implementation requirements**

1. Extend the shared identity master and resolver; do not build a parallel ticker-only fund map.
2. Resolve ISIN and regulator/issuer identifiers before convenience symbols.
3. Validate hierarchy, currency, dates, dealing frequency, fees and lifecycle consistency.
4. Preserve class-specific return/cost histories while linking one economic mandate.
5. Flag backfilled/incubated pre-public history and prevent it from becoming automatically investable evidence.
6. Explicitly map ETF versus ordinary fund so incompatible metrics remain N/A.
7. Publish capability by share class and horizon.

**UI requirements**

- Fund Identity & Dealing panel;
- umbrella/sub-fund/share-class lineage;
- currencies/hedge state;
- fees and dealing timetable;
- lifecycle/manager/mandate history;
- source/conflict/manual-overlay view.

**Acceptance criteria**

- [ ] Multiple share classes of one sub-fund remain distinct but linked.
- [ ] ETF and ordinary-fund pricing/dealing paths cannot be confused.
- [ ] Closed/merged/liquidated funds remain replayable historically.
- [ ] Incubated/backfilled periods are labelled and excluded from normal prospective evidence by policy.
- [ ] Critical missing/conflicted dealing or fee terms block precise liquidity/cost recommendations.
- [ ] Every displayed term traces to a source or declared overlay.

**Tests**

- UCITS umbrella/sub-fund/multi-class fixtures;
- accumulating/distributing and hedged/unhedged classes;
- manager/benchmark/fee change replay;
- merger/liquidation/incubation history;
- malformed hierarchy/currency/fee quarantine;
- schema migration and resolver ambiguity.

**Audit/export:** complete identity hierarchy, terms, fees, lifecycle, sources, conflicts and capability.  
**Roll-out:** read-only identity/dealing evidence. No recommendation authority until `ISSUE-0171` and `ISSUE-0172` pass.

#### `ISSUE-0171` — Implement lawful free global ordinary-fund NAV, disclosure, holdings and fee adapters

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `data-platform`
- Phase: `phase-02-data-policy-identity`
- Codex slice: core `M` plus provider-child `S` issues
- Blocking dependencies: `ISSUE-0076`, `ISSUE-0080`, `ISSUE-0081`, `ISSUE-0149`, `ISSUE-0170`, `ISSUE-0176`
- Downstream: `ISSUE-0172`, `ISSUE-0150`, `ISSUE-0165`
- Execution allowed: `false`

**Problem**

No lawful free source provides complete global NAV, holdings, fees, benchmarks and lifecycle data for every ordinary fund. The application must combine official structured datasets, registers, issuer documents and imports while remaining honest about lag and coverage.

**Required outcome**

Define provider-neutral fund observation/document contracts and implement a staged free-source programme with bulk-first ingestion, source authority, point-in-time timestamps and coverage certificates.

**Initial source families**

- US SEC EDGAR and quarterly Form N-PORT/N-CEN bulk datasets;
- ESMA Registers A2A and national UCITS/OAM/register sources;
- issuer/management-company prospectus, KID, annual/half-year reports, factsheets and lawful holdings files;
- Canada SEDAR+, Japan EDINET, South Korea OpenDART, Hong Kong SFC, Singapore MAS OPERA, Australia ASIC, India AMFI and other official sources only after current terms/interface review;
- convenience price/NAV metadata providers such as yfinance as lower-authority fallbacks;
- user-provided canonical CSV/XLSX/document/NAV imports.

**Contracts / stores**

```text
FundNAVObservation
FundDistributionObservation
FundHoldingSnapshot
FundFeeObservation
FundDocumentRecord
FundProviderCoverage
FundSourceConflict
fund_nav.parquet
fund_holdings.parquet
fund_documents.parquet
fund_provider_coverage.parquet
```

Required fields include identity, observation/document type, value/unit/currency, valid/valuation/publication/accepted/retrieved/knowledge times, public/backfilled/revised state, source/hash/authority, licence/retention, completeness and conflict.

**Implementation requirements**

1. Freeze canonical schemas before provider children.
2. Prefer bulk files and immutable raw objects for thousands of instruments.
3. Preserve as-filed values and amendments; never overwrite with a parsed correction.
4. Distinguish NAV date, publication/retrieval time and next-dealing eligibility.
5. Reconcile issuer, regulator and convenience sources without silent substitution.
6. Track holdings coverage, derivatives/cash/unknown, lag and look-through conservation.
7. Track fee type, share class, period and effective date.
8. Implement adaptive quota/backoff/resume and provider-schema drift.
9. Publish market/asset/date/history coverage and exact unavailable reasons.
10. Require reviewed terms before enabling storage/redistribution.

**UI requirements**

- provider/API-key status and quota;
- regional fund coverage dashboard;
- NAV/distribution history with source/lag;
- document and holdings inventory;
- conflicts, stale state and manual import.

**Acceptance criteria**

- [ ] SEC N-PORT/N-CEN bulk ingestion is content-addressed, resumable and point-in-time.
- [ ] A provider failure or missing key does not corrupt other regions.
- [ ] NAV publication lag and dealing eligibility are never inferred from retrieval time.
- [ ] Holdings coverage and unknown amount are conserved and visible.
- [ ] Convenience data cannot silently outrank official/issuer evidence.
- [ ] Every run produces a coverage denominator by market, asset and evidence type.

**Tests**

- recorded official-source and bulk-file fixtures;
- API key/no-key, rate-limit, resume and schema-drift tests;
- document amendment and NAV correction replay;
- incomplete holdings conservation;
- cross-source conflict and terms-disable state;
- 3,000-instrument cold/warm acquisition benchmark.

**Audit/export:** raw hashes, source/terms, key-required state without secret, observations, documents, conflicts, coverage and quota events.  
**Roll-out:** provider children enabled independently. Missing global coverage remains explicit and cannot be marketed as complete.

#### `ISSUE-0172` — Build ordinary-fund analysis, peer cohorts, forecasts, recommendations and top-*N* screening

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `etf-and-fund-research`
- Phase: `phase-04-etf-research`
- Codex slice: `L` split into coherent child slices
- Blocking dependencies: `ISSUE-0074`, `ISSUE-0098`, `ISSUE-0105`, `ISSUE-0108`–`ISSUE-0109`, `ISSUE-0112`, `ISSUE-0120`, `ISSUE-0123`, `ISSUE-0128`, `ISSUE-0170`, `ISSUE-0171`, `ISSUE-0173`–`ISSUE-0175`
- Downstream: `ISSUE-0138`, `ISSUE-0165`, `ISSUE-0166`, `ISSUE-0169`
- Execution allowed: `false`

**Problem**

Ordinary funds cannot be analysed safely by reusing ETF intraday/spread logic. Their investable return depends on NAV/dealing timing, distributions, fees, mandate, benchmark, holdings lag, manager/strategy stability and class-specific terms.

**Required outcome**

Create a first-class ordinary-fund analyser and screener that shares common probabilistic outputs with stocks/ETFs/bonds while retaining fund-specific evidence, peers, costs, liquidity and lifecycle controls.

**In scope**

- identity/dealing/fee/document/holdings quality;
- active/passive/index mandate, benchmark and style consistency;
- NAV total return with distributions and class-specific fees;
- benchmark-relative return, tracking difference/error for index funds;
- factor/exposure/look-through, concentration, turnover, derivatives/leverage and unknown coverage;
- fund size/flows where lawful, manager/mandate/benchmark/fee changes and closure risk;
- fund-of-funds/master-feeder stacked fees and duplicated exposures;
- peer cohorts by vehicle, mandate, benchmark/objective, geography/sector, asset class, currency hedge, distribution, duration/rating, fee tier and dealing class;
- exact-horizon total-return distributions, selected-currency FX and risk-profile projection;
- total/sector/country/country×sector top-*N* fund views;
- abstention for unsupported history, dealing frequency, fees, benchmark or holdings.

**Metric principles**

- ETF market premium/discount and exchange spread are N/A for ordinary funds.
- Ordinary-fund execution cost uses entry/exit/redemption/dilution/ platform fees and dealing delay, where known.
- Recent fund ranking is never treated as persistent manager skill without factor/cost/survivorship/incubation controls.
- Share-class duplicates cannot dominate rankings; the economic mandate may be ranked once with user-accessible class projections.
- A fund’s own disclosure benchmark and broad-market opportunity anchors are separate comparison layers.

**Contracts / stores**

```text
FundAnalysisRecord
FundPeerCohort
FundReturnDecomposition
FundLifecycleRisk
FundRecommendationProjection
common AnalysisSnapshot
```

**Implementation requirements**

1. Define applicability and formulas before learned models.
2. Build transparent fee/benchmark/holdings/lifecycle baselines.
3. Apply point-in-time, closed/merged fund and incubation-safe validation.
4. Train learned residuals only through the governed Training Centre.
5. Calibrate by mandate/asset/horizon/coverage tier with parent fallback.
6. Project one sealed analysis through the five risk profiles.
7. Integrate selected-currency/FX, analysis-depth manifest and top-*N* slice contract.
8. Preserve fund/ETF differences in UI and export.

**UI requirements**

- fund summary/opinion and exact-horizon forecast;
- NAV/dealing/fees/documents/holdings/benchmark/lifecycle panels;
- active versus passive/index metrics;
- peer support and class/strategy deduplication;
- profile recommendations and why-not;
- fund screener/top-*N* matrix.

**Acceptance criteria**

- [ ] Ordinary funds receive no ETF-only metrics or execution claims.
- [ ] Fund return reconciles NAV, distributions, fees and FX.
- [ ] Closed/merged/incubated funds remain in retrospective outcomes.
- [ ] Share-class duplicates cannot inflate peer support or fill multiple economic top-*N* slots by default.
- [ ] Missing benchmark/fee/dealing/history evidence blocks precise recommendations.
- [ ] Same analysis ID produces identical core values in detail, bulk and screener.

**Tests**

- active/index, accumulating/distributing, hedged/unhedged and fund-of-funds fixtures;
- fee and total-return identities;
- NAV/dealing cut-off and unsupported `1W` cases;
- incubation/survivorship/manager-change validation;
- peer fallback and class-deduplication;
- cross-surface/profile/currency/depth parity.

**Audit/export:** all formulas, peer members, NAV/distribution/fee/benchmark/holdings/lifecycle evidence, forecast, calibration, profile projection and blockers.  
**Roll-out:** advisory-only. Ordinary funds remain unavailable until minimum identity, NAV, fee, benchmark and public-history requirements pass.

#### `ISSUE-0173` — Implement user-selected output currency and point-in-time FX across every workflow

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `returns-and-risk`
- Phase: `phase-05-returns-risk-portfolio`
- Codex slice: `M`
- Blocking dependencies: `ISSUE-0076`, `ISSUE-0084`, `ISSUE-0088`, `ISSUE-0089`, `ISSUE-0149`, `ISSUE-0176`
- Downstream: `ISSUE-0074`, `ISSUE-0108`, `ISSUE-0128`, `ISSUE-0136`–`ISSUE-0140`, `ISSUE-0165`–`ISSUE-0169`, `ISSUE-0172`, `ISSUE-0174`
- Execution allowed: `false`

**Problem**

The application defaults to EUR but does not yet enforce one product-wide selected-currency contract. Foreign-asset forecasts, rankings and recommendations can change materially after FX, and reference rates are not executable prices.

**Required outcome**

Create a point-in-time FX service and selected-currency projection used identically by detail, bulk, screener, forecasts, charts, exports, backtests and paper evidence.

**Initial output-currency set**

EUR, USD, GBP, CHF, CAD, AUD, NZD, JPY, CNY, HKD, SGD, KRW, INR, NOK, SEK, DKK, PLN and CZK, expanded only when a validated source/series exists.

**Source hierarchy**

- ECB daily reference and SDMX data for EUR crosses;
- Bank of Canada Valet and other approved official central-bank/statistical sources;
- BIS/official supplementary series;
- lower-authority market-data fallback with explicit warning;
- manual import;
- unavailable.

**Contracts / stores**

```text
FXRateSnapshot
FXCrossRate
FXReturnScenario
UserCurrencyPolicy
CurrencyProjection
fx_rates.parquet
fx_coverage.parquet
```

**Implementation requirements**

1. Store base/quote, value, valid/publication/retrieved/knowledge times, source, revision and reference/executable state.
2. Derive cross rates through declared paths and test reciprocal/triangular consistency.
3. Calculate realised output return multiplicatively and preserve local/FX/output components.
4. Forecast joint local-asset/FX distributions with horizon-aligned dependence; never use current spot as the future FX path.
5. Model hedged share classes with hedge ratio/reset/cost/residual risk where evidenced.
6. Apply stale/conflict/holiday policies and exact as-of alignment.
7. Project all money fields and downloads consistently; preserve canonical/local amounts.
8. Keep estimated executable spread/cost separate from official reference valuation.

**UI requirements**

- global selected-currency control and coverage state;
- local/FX/output return decomposition;
- FX source/as-of/reference warning;
- hedged/unhedged explanation;
- Settings source preference and manual import.

**Acceptance criteria**

- [ ] Every monetary field carries currency and source snapshot.
- [ ] Detail, bulk, screener and export agree for one analysis/currency.
- [ ] Cross-rate identities pass tolerance and no silent quote inversion occurs.
- [ ] Missing/stale FX blocks false precision.
- [ ] Reference-rate output is never presented as an executable conversion.
- [ ] Changing currency creates a new projection/version without mutating the raw local analysis.

**Tests**

- reciprocal/triangular/metamorphic FX properties;
- EUR/USD/JPY/GBP/CAD/AUD cross fixtures;
- joint positive/negative asset-FX scenarios;
- holidays/stale/revisions;
- hedged-class residual risk;
- selected-currency parity across workflows.

**Audit/export:** source series, path, timestamps, reference/executable state, joint-scenario policy, conversion and coverage.  
**Roll-out:** required for core analysis; unsupported currency returns unavailable rather than silently falling back to EUR.

#### `ISSUE-0174` — Implement five preset-but-editable risk profiles anchored to a dynamic VWCE envelope

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `programme-governance`
- Phase: `phase-05-returns-risk-portfolio`
- Codex slice: `M`
- Blocking dependencies: `ISSUE-0074`, `ISSUE-0108`–`ISSUE-0112`, `ISSUE-0123`, `ISSUE-0128`, `ISSUE-0173`
- Downstream: `ISSUE-0020`, `ISSUE-0138`, `ISSUE-0166`, `ISSUE-0169`, `ISSUE-0172`
- Execution allowed: `false`

**Problem**

The current app exposes only broad conservative/balanced/growth labels. The user requires five understandable profiles, with Medium targeting the same safety/upside profile as VWCE, while retaining editable policy transparency.

**Required outcome**

Implement five versioned selection/recommendation policies—Safe, Safe–Medium, Medium, Medium–Aggressive and Aggressive—projected from one profile-independent analysis.

**Canonical anchor**

Vanguard FTSE All-World UCITS ETF (USD) Accumulating, ISIN `IE00BK5BQT80`. Resolve its multiple listings to one share class and build a dated horizon/output-currency distribution. Do not hard-code ticker, product risk indicator or current performance.

**Policy dimensions**

- probability of loss and benchmark/cash underperformance;
- lower-tail quantiles, expected shortfall and drawdown;
- volatility, liquidity, spread/dealing cost and liquidation time;
- evidence quality, calibration, coverage and model disagreement;
- concentration, leverage/derivative/complexity flags and absolute exclusions;
- expected net return/upside and certainty-equivalent utility relative to VWCE/cash.

**Default semantics**

- Safe: materially lower downside/risk than the matching VWCE snapshot.
- Safe–Medium: below VWCE risk with positive net opportunity.
- Medium: approximately VWCE-like joint downside/upside after costs and uncertainty.
- Medium–Aggressive: higher risk allowed only for sufficient incremental upside.
- Aggressive: highest long-only risk envelope, still subject to absolute evidence/liquidity/product gates.

**Contracts / stores**

```text
RiskProfilePolicy
RiskProfileVersion
VWCEAnchorSnapshot
ProfileProjection
ProfileEligibilityResult
```

**Implementation requirements**

1. Keep raw data, peer scores, forecast distribution and calibration profile-independent.
2. Express defaults as versioned functions/ratios to a sealed VWCE/cash snapshot where appropriate.
3. Calibrate by exact horizon and selected output currency.
4. Permit editing weights/limits inside declared guardrails; preserve defaults/history.
5. Apply hard exclusions before profile scoring.
6. Explain which constraints/weights changed a recommendation or rank.
7. Abstain when the anchor or required risk evidence is unavailable.

**UI requirements**

- profile selector and concise intent;
- editable advanced policy panel with reset/version history;
- VWCE anchor date/currency/horizon/source;
- side-by-side profile eligibility/rank/recommendation;
- binding reasons and unchanged raw-analysis link.

**Acceptance criteria**

- [ ] Profile switch never changes raw facts, peers or forecast values.
- [ ] Medium refreshes from the current sealed VWCE envelope rather than a fixed label.
- [ ] Risk envelopes are ordered under declared metrics or any exception is explicit.
- [ ] Aggressive cannot admit prohibited, unsupported, critically illiquid or low-evidence instruments.
- [ ] Editing a profile creates a new version/run projection.

**Tests**

- raw-analysis invariance;
- monotonic/default-envelope properties;
- missing/stale VWCE anchor;
- multiple-listing/currency identity;
- policy version/replay and guardrail violations;
- profile-specific top-*N* parity.

**Audit/export:** full policy, VWCE/cash snapshots, projection inputs, weights, constraints, eligibility and recommendation reasons.  
**Roll-out:** required for core screener; profiles remain advisory and make no personal-suitability claim.

#### `ISSUE-0175` — Implement Quick, Medium, High and Full analysis-depth workload profiles with measured SLOs

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `application-platform`
- Phase: `phase-08-frontend-api`
- Codex slice: `M`
- Blocking dependencies: `ISSUE-0039`, `ISSUE-0077`, `ISSUE-0078`, `ISSUE-0121`, `ISSUE-0151`, `ISSUE-0165`
- Downstream: `ISSUE-0138`, `ISSUE-0169`, `ISSUE-0172`
- Execution allowed: `false`

**Problem**

Hardware profiles describe available CPU/memory/disk but not which evidence/models a user selected. Without a semantic workload profile, runtimes are unpredictable and “fast” modes may silently omit critical analysis.

**Required outcome**

Create four immutable analysis-depth profiles with declared mandatory/optional stages, model/source breadth, runtime evidence, safe degradation and upgrade lineage.

**Reference SLO fixture**

Warm-cache, 3,000 supported instruments, declared reference machine of approximately 20 CPU cores, 32 GB RAM and RTX 5070:

- Quick: ≤5 minutes, one selected horizon.
- Medium: ≤30 minutes, one selected horizon.
- High: ≤60 minutes, one selected horizon.
- Full: ≤10 hours, all supported horizons and declared robustness.

Cold provider acquisition and Training Centre jobs are timed/reported separately. SLOs are provisional engineering targets and require measured p50/p95 certification.

**Contracts / stores**

```text
AnalysisDepthProfile
AnalysisStageManifest
AnalysisResourcePlan
AnalysisTimingRecord
AnalysisUpgradeLink
analysis_depth_profiles.yaml
analysis_timings.parquet
```

**Profile rules**

- Quick: cached mandatory identity/prices/data gates, core asset facts/peers, deterministic/simple forecast baseline, core risk/cost.
- Medium: full core evidence due, approved core ensemble, calibration/uncertainty and core scenarios.
- High: broader documents/features/model families, stronger source reconciliation and bootstrap/stability/scenario checks.
- Full: all approved lawful sources, all supported horizons/models, repeated robustness, clone/calibration/coverage/bias/audit replay.

Every mode preserves formulas, critical data/evidence/liquidity gates, selected-currency semantics, recommendation authority and reproducibility. Optional stages may differ only according to the versioned manifest.

**Implementation requirements**

1. Keep workload depth separate from machine resource profile.
2. Freeze source/model/stage/horizon/seed manifests at run start.
3. Use content-addressed cache and incremental stage reuse.
4. Schedule CPU/GPU/IO with bounded concurrency, memory/disk reservation and cancellation/resume.
5. Record cold/warm state, p50/p95, stage time, provider wait, model omission and resource peaks.
6. Support weaker devices through smaller shards/CPU fallback and longer actual runtime, never changed semantics.
7. Fail explicitly when mandatory evidence cannot fit/complete; do not silently downgrade.
8. Upgrade to deeper analysis as a new linked run.

**UI requirements**

- depth selector with exact included/omitted stages;
- machine-profile compatibility and resource estimate;
- stage progress, cancellation/resume and measured history;
- warm/cold/training distinction;
- upgrade/compare results and omitted-evidence warning.

**Acceptance criteria**

- [ ] All four manifests are versioned and exportable.
- [ ] Quick/Medium/High/Full agree on shared deterministic fields for identical inputs.
- [ ] Allowed differences map exactly to declared optional stages/models/seeds.
- [ ] No mode bypasses hard gates or changes formulas.
- [ ] Reference SLO evidence is measured; missed SLO fails certification rather than falsifying completion.
- [ ] Older-device mode produces numerically equivalent mandatory results under the same hashes.

**Tests**

- manifest/stage mutation;
- warm/cold and training separation;
- crash/resume/cache reuse;
- CPU/GPU unavailable and memory/disk pressure;
- reference 3,000-instrument benchmark and low-resource benchmark;
- profile upgrade lineage and cross-depth parity.

**Audit/export:** profile/stage/resource manifest, timings, cache state, omissions, hashes and measured SLO result.  
**Roll-out:** required for core bulk UI. Runtime is measured evidence, not a guaranteed wall-clock promise on every provider/device.

#### `ISSUE-0176` — Build a secure Data Providers & API Keys settings centre

**Canonical metadata**

- Classification: `proposed_new`
- Ledger state: `open`
- Programme status: `planned`
- Priority: `P0`
- Owner: `security-and-release`
- Phase: `phase-09-quality-release-security`
- Codex slice: `M`
- Blocking dependencies: `ISSUE-0037`, `ISSUE-0076`, `ISSUE-0080`, `ISSUE-0144`–`ISSUE-0146`, `ISSUE-0149`
- Downstream: `ISSUE-0081`, `ISSUE-0155`, `ISSUE-0171`, `ISSUE-0173`
- Execution allowed: `false`

**Problem**

The repository has provider YAML fields and environment overlays but no complete user-facing secure credential centre. Some high-value free sources require a key; others work without one but improve throughput with a key. Plain-text keys, invisible quota state or leaked errors would undermine the local-first design.

**Required outcome**

Create one typed provider-access registry and secure local UI for entering, testing, rotating, deleting and diagnosing free-provider credentials without exposing secret values.

**Initial provider states**

- no key: SEC EDGAR (identified user agent), ECB, Bank of Canada Valet, many bulk/register sources;
- optional free key for higher limits: OpenFIGI;
- required free key/account: FRED, Companies House API, EDINET v2, OpenDART and other provider children after terms review;
- manual/local sources: no network credential;
- paid/subscription-only: disabled from the mandatory path.

**Contracts / stores**

```text
ProviderAccessDefinition
ProviderCredentialReference
ProviderCredentialState
ProviderProbeResult
ProviderQuotaState
ProviderTermsApproval
```

Secret bytes are never stored in YAML, Parquet, SQLite rows, logs or audit packets. On Windows, use a reviewed current-user Credential Manager/DPAPI-backed store; portable/non-Windows fallback must be explicit and security-reviewed.

**Implementation requirements**

1. Declare key requirement, sign-up/help URL, header/parameter placement, scopes, rate limits, quota headers and terms.
2. Provide masked entry, paste, test, rotate and delete actions.
3. Probe with bounded harmless requests; never print the key or request URL containing it.
4. Store only a credential reference/fingerprint and status in application data.
5. Redact secrets from exceptions, subprocesses, telemetry, screenshots, prompts, exports and crash reports.
6. Keep no-key startup functional and dependent capability explicitly unavailable/degraded.
7. Add quota/rate-limit/backoff status and last successful use.
8. Exclude secrets from normal backups; document DPAPI same-user/same-machine and password-reset recovery limits.
9. Scan repository/config/imports for likely secret material and quarantine accidental plaintext.
10. Require provider terms/licence approval independently of credential presence.

**UI requirements**

- Data Providers & API Keys settings page;
- provider purpose/coverage/key requirement/cost/terms status;
- masked credential state and test result;
- rate/quota/last-success/error class;
- cache/offline/manual fallback and disable switch;
- redacted export.

**Acceptance criteria**

- [ ] No secret appears in repository files, logs, reports, URLs, prompts or audit packets.
- [ ] Correct/wrong/missing key states are distinguishable without disclosure.
- [ ] Providers that need no key work without the credential store.
- [ ] Optional key improves only declared limits/capability.
- [ ] Delete/rotate invalidates the old reference and dependent probes.
- [ ] Backup/restore behaviour and unrecoverable-secret state are explicit.
- [ ] Credential presence cannot bypass terms or source-authority policy.

**Tests**

- sentinel secret through every error/log/export path;
- Windows current-user protect/unprotect and different-user/machine failure fixture;
- wrong/revoked/expired/quota-exhausted key;
- optional/no-key/required-key provider matrix;
- backup/restore and password-reset limitation simulation;
- repository/config secret scanning and malicious import.

**Audit/export:** provider definitions, non-secret status, probe/quota/terms events and secret-scan result only.  
**Roll-out:** required before enabling key-dependent provider children. No API key is ever mandatory for safe application startup.

## Part IX — Dependency and implementation sequence

The week ranges from the prior research are a sequencing aid, not a promise of investment validity. Slow-horizon models cannot be promoted until outcomes mature.


### User-priority critical path overlay

The milestone sequence below remains useful for shared foundations, but implementation priority for this private application is:

```text
P0 core research/screening lane
0070 / 0008 / 0037 / 0080 / 0149 / 0176
  ↓
0082 / 0083 / 0084 / 0088 / 0089 / 0170 / 0171 / 0173
  ↓
0074 / 0098 / 0105 / 0112 / 0108 / 0109 / 0123 / 0172 / 0174
  ↓
0117 / 0119 / 0120 / 0121 / 0124 + 0057
  ↓
0018 / 0020 / 0081 / 0165 / 0166 / 0175
  ↓
0136 / 0137 / 0138 / 0140 + 0150 + 0142 / 0143
  ↓
0169 + core-analysis lane of 0152

P1 read-only portfolio lane
0127 / 0159 / 0160 / 0161 / 0162 / 0163 / 0164 / 0168

P2 paper/broker/execution lane
0129 / 0130 / 0131 / 0167 / 0132 / 0134 / 0135 / 0133
```

Rules:

1. `P1` and `P2` issues do not block `CORE_ANALYSIS` or `BULK_SCREENING` certification unless a shared P0 contract is failing.
2. `CORE_ANALYSIS` does not grant paper or broker authority.
3. Ordinary-fund, selected-currency, exact-horizon, risk-profile, depth-profile and provider-credential gaps are P0 release blockers.
4. Tax optimisation is not on the critical path.
5. The first useful release may support a narrower set of markets/assets only when exact coverage and unavailable states are visible; it may not claim complete global coverage.
6. Full 2Y/5Y prospective maturity is not a precondition for read-only retrospective/research output, but its evidence state must remain explicit.

#### Core-release exit criteria

The analyser/screener core is releasable only when:

- stocks, ETFs, supported ordinary funds and supported bonds use explicit capability states;
- exact horizons, selected currency/FX, peer cohorts and five risk profiles are versioned and parity-tested;
- Quick/Medium/High/Full manifests and measured benchmark evidence exist;
- every recommendation is long-only, source-traceable, calibrated or explicitly uncalibrated/research-only;
- total/sector/country/country×sector top-*N* views state exact denominators and coverage;
- free-provider/API-key states are usable and secrets remain protected;
- `ISSUE-0169` core parity and the core lane of `ISSUE-0152` pass;
- execution remains disabled.

### Milestone M0 — Reconcile scope and authority

**Sequence:** programme start; approximately weeks 0–2.

1. Amend `ISSUE-0070`, `ISSUE-0008` and `ISSUE-0149`.
2. Register adopted proposed IDs and update the canonical dependency graph.
3. Keep `execution_allowed=false`.
4. Extend `ISSUE-0152` certification scope.
5. Record all retained/rejected/unsupported ideas so they cannot re-enter silently.

**Exit:** supported/unsupported assets and execution modes are machine-readable and visible; no grey-source dependency exists.

### Milestone M1 — Truth, identity, clocks and sources

**Sequence:** approximately weeks 2–8.

1. Complete/harden `ISSUE-0082`–`ISSUE-0089`.
2. Implement `ISSUE-0153` and core `ISSUE-0155` schemas/adapters.
3. Complete corporate actions, cash-flow schedules, FX, curves and point-in-time benchmarks.
4. Expand coverage/bias audit.
5. Establish cross-source anomaly/quarantine fixtures.

**Exit:** stock, ETF, bond and cash fixtures replay at a historical cut-off without future information.

### Milestone M2 — One analysis spine and scalable bulk workflow

**Sequence:** approximately weeks 4–12.

1. Amend `ISSUE-0074`, `ISSUE-0018`, `ISSUE-0020`, `ISSUE-0098`, `ISSUE-0112`.
2. Implement `ISSUE-0165`, then `ISSUE-0166`.
3. Begin `ISSUE-0169` with expected failing parity tests.
4. Close identity and universe gaps before trusting percentiles.

**Exit:** a 1,000-instrument synthetic run is resumable, fully denominated, and each row reopens with identical canonical analysis values.

### Milestone M3 — Fixed-income analytics

**Sequence:** approximately weeks 6–16.

1. Implement `ISSUE-0154` deterministic analytics.
2. Implement `ISSUE-0156` risk.
3. Implement `ISSUE-0157` peers/forecast/screener.
4. Implement `ISSUE-0158` user interface.
5. Retain unsupported structures as blocked/research-only.

**Exit:** supported fixed-rate/zero-coupon debt has validated terms, cash flows, clean/dirty price, yield, duration/convexity/DV01, risk, forecast, screener and portfolio views.

### Milestone M4 — Ledger, valuation and performance

**Sequence:** approximately weeks 6–16.

1. Complete `ISSUE-0086` and `ISSUE-0127`.
2. Implement `ISSUE-0159`.
3. Amend `ISSUE-0116`.
4. Implement `ISSUE-0160` and `ISSUE-0161`.
5. Add broker/user import reconciliation and trial balance.

**Exit:** a multi-account portfolio in the selected output currency (EUR default) rebuilds from inception, and every chart reconciles to ledger/performance exports.

### Milestone M5 — Portfolio intelligence

**Sequence:** approximately weeks 12–22.

1. Complete/harden `ISSUE-0021`, `ISSUE-0022`, `ISSUE-0113`–`ISSUE-0115`.
2. Implement `ISSUE-0162`–`ISSUE-0164`.
3. Implement `ISSUE-0168`.
4. Complete `ISSUE-0139` portfolio workspace.

**Exit:** exposures, income/events, goals/what-if, expected outcomes and rebalancing all use one selected portfolio snapshot and preserve unknown coverage.

### Milestone M6 — Model and forecast evidence

**Sequence:** approximately weeks 8–24, followed by outcome maturity.

1. Complete/harden `ISSUE-0117`, `ISSUE-0119`–`ISSUE-0124`, `ISSUE-0108`–`ISSUE-0109`.
2. Require transparent baselines, multiple-testing control, calibration, novelty/clone monitoring and signed releases.
3. Finish forward/paper evidence and forecast-outcome history.
4. Promote only per task/asset/horizon and preserve fallback.

**Exit:** every task/horizon has champion/fallback, calibration, support and maturity state; no unsupported model affects action.

### Milestone M7 — Paper, broker read-only and draft execution

**Sequence:** approximately weeks 18–30 plus prospective evidence.

1. Complete `ISSUE-0128`, `ISSUE-0130`, `ISSUE-0131`.
2. Implement `ISSUE-0167`.
3. Complete `ISSUE-0132`, `ISSUE-0134`, `ISSUE-0135`.
4. Run paper and read-only reconciliation for the certified universe.
5. Conduct duplicate/unknown order, disconnect, cash-break and kill-switch drills.

**Exit:** deterministic proposal/order lifecycle passes failure/recovery drills; live authority remains disabled.

### Milestone M8 — Certification and supervised live canary

**Sequence:** only after all evidence gates; no fixed calendar promise.

1. Close legal/licence/terms gaps.
2. Pass `ISSUE-0169`, audit, security, chaos, packaging and clean-machine gates.
3. Complete capability-specific `ISSUE-0152` certification.
4. Enable `ISSUE-0133` only for the narrow certified canary.
5. Accumulate prospective operational and investment evidence before bounded automatic promotion.

**Exit:** canary is explicit, tiny, reversible and separately authorised. Bounded automatic remains a later authority transition.

### Dependency graph

```text
0070 / 0008 / 0149
  ↓
0082–0089 + 0153 + 0155 + 0170 + 0171 + 0173 + 0176
  ↓
0074 + 0098 / 0105 / 0112 + 0154 / 0156 + 0172 + 0174
  ├── 0165 → 0166 ← 0175
  ├── 0157 → 0158
  └── 0117 / 0119 / 0120 / 0121 / 0108 / 0109 / 0123 / 0124
          ↓
0086 / 0127 → 0159 → 0160 / 0161 / 0116
                         ↓
                 0162 / 0163 / 0164 / 0168
                         ↓
0113 / 0114 / 0128 → 0130 → 0131 → 0167 → 0132
                                           ↓
                             paper / forward evidence
                                           ↓
                         0134 / 0135 + 0169 + 0152
                                           ↓
                                      0133 canary
```

## Part X — Shared release-blocking acceptance matrix

| ID | Test | Pass condition |
|---|---|---|
| T-01 | Point-in-time identity | Future identifier or terms corrections do not alter earlier snapshots. |
| T-02 | Survivorship/default | Delisted/defaulted instruments remain in historical universes/outcomes. |
| T-03 | Analysis parity | Detail, bulk, screener and portfolio use identical canonical fields for one analysis ID. |
| T-04 | Bulk resume | Interrupted 1,000-instrument run resumes without changing frozen inputs or duplicating results. |
| T-05 | Portfolio flow neutrality | Deposits/withdrawals affect value/invested capital but not same-instant TWR. |
| T-06 | Internal trade neutrality | Buy/sell funded from portfolio cash is not an external flow. |
| T-07 | Ledger balance | Every transaction/action balances and positions rebuild from inception. |
| T-08 | Performance reconciliation | Investment P&L and attribution reconcile to beginning/end value and external flows. |
| T-09 | Bond price/yield | Clean/dirty/accrued/yield/duration/convexity pass golden and differential fixtures. |
| T-10 | Fixed-income forecast | Return decomposition includes carry/roll/rates/spread/default/FX/cost and missing coverage. |
| T-11 | Peer fallback | Sparse cohort falls back and records support/reason. |
| T-12 | Validation isolation | HPO/feature selection cannot access outer test data. |
| T-13 | Multiple testing | Every attempted variant appears in its research family. |
| T-14 | Calibration | Nominal intervals meet predeclared coverage or remain unpromoted. |
| T-15 | Exposure conservation | Mapped plus unknown exposure equals total within tolerance. |
| T-16 | Portfolio forecast | Covariance/dependence is used; independent point estimates are not simply summed. |
| T-17 | Proposal parity | Backtest/current/paper use the same deterministic proposal kernel. |
| T-18 | Cash reservation | Concurrent proposals cannot reserve the same cash/position twice. |
| T-19 | Broker idempotency | Duplicate/missing/out-of-order callbacks cannot create duplicate orders. |
| T-20 | Kill switches | Independent controls block submissions and execute configured cancel/shutdown. |
| T-21 | Recovery | Unknown order/position state becomes reconciliation-required and blocks related execution. |
| T-22 | Legal/terms | Missing/expired provider/model/broker approval disables capability. |
| T-23 | UI/export parity | Every displayed value/warning exists in evidence export. |
| T-24 | Package parity | Source and packaged application reproduce the golden scenario. |
| T-25 | Live authority | No live order exists before per-capability certification and operator enablement. |
| T-26 | Model unavailability | Missing optional package/weight returns null without blocking safe startup. |
| T-27 | News authority | News/LLM cannot change action or order directly. |
| T-28 | Unknown coverage | Missing ETF/bond/exposure data remains unknown and is never redistributed. |
| T-29 | Price/FX quality | Stale/conflicted price or FX cannot produce false precise P&L/forecast. |
| T-30 | Release rollback | Last approved data/model/policy/application release restores exactly. |


| T-31 | Fund hierarchy identity | Vehicle, umbrella, sub-fund and share classes remain distinct, linked and point-in-time replayable. |
| T-32 | Fund NAV/dealing semantics | Ordinary funds use next-NAV/dealing terms; ETF market-price/spread fields remain inapplicable. |
| T-33 | Fund survival/incubation | Closed, merged, liquidated and incubated/backfilled funds remain in historical denominators with investable-history flags. |
| T-34 | Share-class deduplication | Multiple classes do not inflate economic peer support or fill multiple top-*N* slots by default; class-specific costs remain visible. |
| T-35 | Peer semantic validity | A bank valuation metric cannot be normalised against technology companies or an economically invalid cohort. |
| T-36 | Exact horizon enum | Only `1W`, `1M`, `3M`, `6M`, `9M`, `2Y` and `5Y` are canonical; unsupported asset×horizon pairs are unavailable. |
| T-37 | Long-horizon dependence | Overlapping 2Y/5Y outcomes use overlap-aware folds/inference and report effective independent decisions. |
| T-38 | Training versus maturity | Training/inference wall time never substitutes for prospective horizon maturity or evidence state. |
| T-39 | Selected-currency identity | Local, FX and output-currency returns reconcile multiplicatively and preserve currency/source metadata. |
| T-40 | Joint FX forecast | Future selected-currency distribution uses joint asset/FX scenarios; current spot is not used as a fixed future conversion. |
| T-41 | FX reference authority | Official reference rates are labelled valuation/reference data and never executable fills. |
| T-42 | VWCE anchor | All relevant listings resolve to ISIN `IE00BK5BQT80`; Medium uses a dated horizon/currency distribution, not hard-coded ticker/risk. |
| T-43 | Profile invariance | Switching Safe→Aggressive changes only policy projection, not raw facts, peers, forecasts or calibration. |
| T-44 | Profile hard gates | No profile can admit prohibited products, critical data conflicts, unsupported horizons or absolute liquidity failures. |
| T-45 | Multidimensional top-*N* | Total, sector, country and country×sector lists reconcile to one full candidate table and exact coverage denominator. |
| T-46 | Sparse selection groups | Groups below minimum raw/effective support fall back or remain unavailable; no false winner is displayed. |
| T-47 | Analysis-depth manifest | Quick/Medium/High/Full differ only by declared optional stages/model breadth; formulas and hard gates are identical. |
| T-48 | Analysis SLO evidence | Warm/cold/training stages are separately timed; p50/p95 benchmark evidence exists for the declared 3,000-instrument fixture. |
| T-49 | No silent depth downgrade | Resource/provider failure cannot silently run a shallower profile under a deeper label. |
| T-50 | Cross-hardware equivalence | Mandatory results reproduce on reference and lower-resource profiles from the same hashes within declared numerical tolerance. |
| T-51 | Credential secrecy | Sentinel API keys never appear in repository, config, logs, URLs, prompts, screenshots, crash reports, backups or audit exports. |
| T-52 | Provider key matrix | No-key, optional-key and required-key providers degrade exactly as declared without blocking safe startup. |
| T-53 | Core release isolation | Portfolio/broker failures cannot block a passing core-analysis lane; core certification cannot enable execution. |
| T-54 | Recommendation efficacy | Frozen recommendations report calibration, ranking and net VWCE/cash/asset-benchmark outcomes with valid dependence/multiplicity treatment. |
| T-55 | Personal-use boundary | Generic guest analysis rejects personal-financial/suitability inputs and exports balanced, source- and conflict-disclosed general research. |

### Common definition of done for every issue

An issue is not complete merely because code or a backend file exists. Closure requires:

- all acceptance criteria and negative/error paths;
- focused tests plus invalidated wider suites;
- property/metamorphic/golden/differential tests where relevant;
- UI and semantic locators for user-facing behaviour;
- audit/export parity and unavailable markers;
- updated canonical registry, plan, open/closed ledgers and dependency map;
- documentation, limitations, source/licence and authority state;
- rebuilt Windows application and source/package smoke;
- user-perspective browser test;
- independent review for P0 safety, accounting, model or execution work;
- no critical unresolved data, reconciliation, security or authority warning.

## Part XI — Core data contracts

### `InstrumentContext`

```text
instrument_id, entity_id, share_class_id, listing_or_quotation_id
asset_type, sector_code, industry_code, business_model_tags
legal_domicile, regulatory_country, primary_listing_country
revenue_region_weights, asset_region_weights
accounting_standard, reporting_currency, trading_currency
market_cap_eur, cap_bucket_version, liquidity_bucket
bond_type, issuer_type, seniority, coupon_type
rating_bucket, maturity_bucket, duration_bucket
classification_confidence, source_ids
valid_from, valid_to, knowledge_time, schema_version
```

### `PeerCohortDefinition`

```text
cohort_id, version, asset_type
ordered inclusion rules, exclusions, weighting
leaf_parent_id, fallback_order
minimum_n, minimum_effective_n
normalisation, winsorisation, shrinkage policy
benchmark_ids, valid_from, valid_to
```

### `ModelRouteDecision`

```text
run_id, instrument_id, task, horizon
global_model_id, adapter_ids, calibration_id
context_snapshot_hash, peer_cohort_id
support_n, support_n_eff, route_confidence
fallback_path, reason_codes, policy_version
```

### `ExperimentRecord`

```text
experiment_id, hypothesis, economic_rationale
frozen_protocol_hash, amendment_history
dataset_snapshot_ids, universe_snapshot_id
feature_set_id, target_id, outer_folds, inner_folds
cost_policy_id, HPO_budget, random_seeds
research_family_id, attempted_variant_count
metrics, CI, multiplicity_results, promotion_decision
artefact_hashes, approvers, created_at
```

### `DocumentRecord` / `FactRecord`

```text
DocumentRecord:
document_id, entity_id, instrument_ids, source_id, source_url
document_type, language, content_hash, source_document_id
published_at, exchange_released_at, accepted_at, retrieved_at
timestamp_confidence, entity_match_confidence
licence_retention_rule, parser_id, supersedes_id

FactRecord:
document_id, taxonomy, concept, label, period_start, period_end
instant_date, unit, scale, dimensions, value
as_filed_value, normalised_value, adjustment_type
restatement_status, source_span, mapping_confidence
```

### `DailyPortfolioSnapshot`

```text
portfolio_id, account_id, valuation_time, selected_output_currency
position_values_local, position_values_output
cash_by_currency, accrued_income_by_currency
total_value_output, net_invested_capital_output
external_flow_output, income_output, fees_output, tax_output
price_pnl_output, fx_pnl_output, total_investment_pnl_output
benchmark_value_output, valuation_coverage
stale_or_conflicted_value_output, fx_snapshot_ids
snapshot_hash, currency_policy_id, policy_version
```

### `PortfolioPerformancePeriod`

```text
portfolio_id, start_time, end_time, aggregation
selected_output_currency, beginning_value_output, ending_value_output
contributions_output, withdrawals_output, net_external_flow_output
investment_pnl_output, income_output, fees_output, tax_output, fx_pnl_output
twr, mwr, modified_dietz_fallback
benchmark_return, cash_return, excess_return
fx_snapshot_ids, partial_period, coverage
currency_policy_id, calculation_policy_version
```

### `PortfolioExposureCube`

```text
portfolio_id, snapshot_id, dimension, view_mode
selected_output_currency, dimension_key, display_label
amount_output, percentage
mapped_coverage, stale_coverage, fx_snapshot_ids
source_snapshot_ids, contributor_instrument_ids
currency_policy_id, aggregation_policy_version
```

### `BulkAnalysisRun`

```text
bulk_run_id, parent_run_id, universe_snapshot_id
decision_time, data_cutoff, requested_horizons
provider_policy_version, feature_set_id, model_set_id
score_policy_version, resource_profile
total_count, eligible_count, blocked_count
unavailable_count, failed_count, completed_count
state, manifest_hash, created_at, completed_at
```

### `OrderLifecycle`

```text
order_intent_id, proposal_id, account_id, broker_id
idempotency_key, instrument_id, side, quantity_or_face
order_type, limit_price, time_in_force
estimated_cash, reserved_cash, reserved_position
local_order_id, broker_order_id, permanent_id
state, event_time, source, sequence
filled_quantity, average_fill_price, fees
reconciliation_state, blocked_by
```


### `FundVehicle` / `FundSubFund` / `FundShareClass`

```text
FundVehicle:
fund_vehicle_id, legal_name, legal_form, domicile, regulator_ids
management_company_id, depositary_id, umbrella_id
valid_from, valid_to, knowledge_time, source_ids, conflict_state

FundSubFund:
subfund_id, fund_vehicle_id, name, mandate_id, benchmark_ids
active_passive_index, asset_class, region_sector_mandates
inception_date, public_launch_date, lifecycle_state
manager_history_ids, mandate_history_ids, benchmark_history_ids
valid_from, valid_to, knowledge_time, source_ids

FundShareClass:
share_class_id, subfund_id, isin, local_ids, listing_ids
retail_institutional, clean_adviser, accumulation_distribution
base_currency, share_class_currency, dealing_currency
hedged, hedge_index, hedge_ratio, hedge_reset_frequency
fee_schedule_id, dealing_terms_id, availability_jurisdictions
valid_from, valid_to, knowledge_time, source_ids, conflict_state
```

### `FundDealingTerms` / `FundFeeSchedule`

```text
FundDealingTerms:
share_class_id, nav_frequency, dealing_frequency
valuation_point, dealing_cutoff, timezone, notice_period
settlement_days, redemption_payment_limit, gates_or_suspensions
minimum_initial, minimum_additional, amount_currency
valid_from, valid_to, knowledge_time, source_id

FundFeeSchedule:
share_class_id, ongoing_charges, management_fee
performance_fee_formula, entry_fee, exit_fee, redemption_fee
dilution_levy_or_swing_policy, platform_fee_excluded
period_start, period_end, valid_from, knowledge_time, source_id
```

### `FundMarketObservation` / `FundHoldingSnapshot`

```text
FundMarketObservation:
share_class_id, observation_type
nav, distribution, total_return_index, assets_under_management
value_currency, valuation_time, publication_time, retrieved_at, knowledge_time
public_history_state, backfilled_or_incubated
source_id, source_hash, authority, quality, conflict_state

FundHoldingSnapshot:
subfund_id, share_class_id, holdings_date, publication_time
security_or_exposure_id, amount, weight, currency
mapped_coverage, unknown_weight, derivatives_or_cash_flag
source_id, source_hash, authority, stale_state
```

### `FXRateSnapshot` / `FXReturnScenario`

```text
FXRateSnapshot:
fx_snapshot_id, base_currency, quote_currency, rate
valid_time, publication_time, retrieved_at, knowledge_time
source_id, source_hash, revision_id
reference_or_executable, stale_state, conflict_state
cross_path, policy_version

FXReturnScenario:
scenario_set_id, horizon, local_asset_return
fx_return, output_currency_return
asset_fx_dependence_method, seed, support, coverage
spot_snapshot_id, model_id, calibration_id, policy_version
```

Realised return identity:

```text
1 + output_currency_return
    = (1 + local_asset_total_return)
    × (1 + fx_return_asset_currency_to_output_currency)
```

### `UserCurrencyPolicy`

```text
currency_policy_id, selected_output_currency
allowed_currencies, source_priority, stale_tolerance
reference_rate_usage, executable_cost_policy
cross_rate_policy, missing_fx_action, version, created_at
```

### `RiskProfilePolicy` / `VWCEAnchorSnapshot`

```text
RiskProfilePolicy:
profile_id, display_name, version, exact_horizon
anchor_type, anchor_snapshot_id
loss_probability_limit, lower_quantile_limit
expected_shortfall_limit, volatility_limit, drawdown_limit
liquidity_and_cost_limits, evidence_and_coverage_minimums
expected_return_or_utility_weights, absolute_exclusions
editable_fields, guardrails, created_at

VWCEAnchorSnapshot:
anchor_snapshot_id, fund_vehicle_id, subfund_id, share_class_id
isin, price_listing_id, benchmark_id
horizon, output_currency, data_as_of
return_distribution, risk_metrics, fees_and_costs
official_product_fields, source_ids, snapshot_hash
```

### `AnalysisDepthProfile` / `AnalysisStageManifest`

```text
AnalysisDepthProfile:
depth_id, version, mandatory_stage_ids, optional_stage_ids
allowed_source_tiers, model_family_ids, supported_horizons
seed_and_bootstrap_policy, document_refresh_policy
reference_fixture_id, warm_slo_seconds, certification_state

AnalysisStageManifest:
analysis_run_id, depth_id, stage_id, required
input_hashes, output_hashes, cache_state
started_at, completed_at, duration_ms
cpu_seconds, gpu_seconds, peak_memory_mb, disk_bytes
provider_wait_ms, omitted_reason, status
```

### `SelectionSliceDefinition`

```text
selection_slice_id, selection_run_id
asset_type, scope_type, sector_id, economic_country_or_region
country_sector_intersection_id, risk_profile_id
horizon, analysis_depth, output_currency
minimum_n, minimum_effective_n, fallback_slice_id
requested_n, candidate_count, selected_count
policy_version, source_snapshot_ids
```

### `ProviderAccessDefinition` / `ProviderCredentialState`

```text
ProviderAccessDefinition:
provider_id, capability_ids, access_mode
key_requirement, free_or_paid, signup_or_help_url
secret_placement, rate_limits, quota_headers
bulk_available, terms_record_id, source_authority

ProviderCredentialState:
provider_id, credential_reference, masked_hint, fingerprint
state, created_at, rotated_at, last_probe_at, last_success_at
quota_state_id, error_class, secret_exported=false
```

### Expanded `AnalysisSnapshot` and `BulkAnalysisRun` requirements

```text
AnalysisSnapshot additional fields:
selected_output_currency, currency_policy_id, fx_snapshot_ids
risk_profile_independent=true, available_profile_projection_ids
analysis_depth_id, analysis_stage_manifest_hash
exact_horizon, horizon_evidence_state
fund_vehicle_id, subfund_id, share_class_id where applicable
metric_registry_version, peer_fallback_path

BulkAnalysisRun additional fields:
analysis_depth_id, selected_output_currency, currency_policy_id
risk_profile_ids, selection_slice_definition_ids
cold_or_warm_state, acquisition_run_ids
stage_manifest_hash, timing_summary_id
```

## Part XII — Purpose-fit grading and evidence maturity

The supplied three-state grading report makes a crucial distinction:

```text
code or contract exists
≠ integrated workflow
≠ accepted release
≠ statistically valid
≠ prospectively useful
≠ benchmark-beating
```

Its 19 July assessment placed the then-current merged app at approximately **5.4/10**, a hypothetical state with every current issue genuinely completed at approximately **8.3/10**, and the programme plus retained research additions at approximately **9.0/10** for product/methodology fitness. Those numbers are judgemental and dated, not current performance measurements. Their lasting use is the maturity separation:

| Maturity dimension | Required state |
|---|---|
| Product safety | Explicit authority, no invented data, fail-closed controls |
| Data truth | Point-in-time identity, universes, actions, terms, prices and documents |
| Model method | Baselines, nested validation, multiplicity, calibration and lifecycle |
| Portfolio/accounting | Reconciled ledger, valuations, cash flows, costs and performance |
| Operational reliability | Resume, idempotency, monitoring, package parity and recovery |
| Prospective efficacy | Frozen paper/live-canary outcomes over matured horizons |

Completing this specification can improve the first five dimensions. It cannot manufacture the sixth. A nine-month model needs elapsed unseen outcomes; issue closure cannot substitute for calendar time and independent decisions.


### User-priority maturity and separate core-release scorecard

The P0 analyser/screener lane should expose its own maturity dimensions:

| Core dimension | Minimum certified state |
|---|---|
| Asset support | Stock, ETF, supported ordinary fund and supported bond have explicit capability/abstention states |
| Semantic truth | Exact horizon, peer cohort, selected currency/FX, costs and benchmark layers are sealed |
| Recommendation policy | Five profiles project one immutable analysis; Medium uses a dated VWCE envelope |
| Runtime usability | Quick/Medium/High/Full manifests and measured p50/p95 evidence exist on reference and lower-resource fixtures |
| Global free-data honesty | Every run reports market/asset/evidence coverage and required/optional API-key state |
| Forecast validity | Proper-score calibration, dependence-aware comparison, all-attempt records and segment coverage are available |
| Prospective efficacy | Frozen outcomes mature by horizon; `2Y`/`5Y` remain explicitly immature until calendar time passes |
| Legal presentation | Self/guest mode, facts/opinions, source, horizon, risk and conflicts are explicit |

Core certification can therefore improve product/methodological fitness before 2Y/5Y prospective outcomes mature, but it cannot label those horizons prospectively proven. Portfolio and execution maturity remain separate scorecards.

### Three-state presentation required in the app

Every significant capability should expose:

1. **Implementation state:** absent, planned, initial, integrated, hardened, certified.
2. **Evidence state:** unavailable, retrospective only, paper/forward immature, mature, degraded.
3. **Authority state:** research, advisory, paper, read-only broker, draft approval, supervised canary, bounded automatic.

These three states must never be collapsed into one green badge.

## Part XIII — Explicit scrap, defer and quarantine list

### Scrap from the current implementation path

- guaranteed-return wording or exact future-price claims;
- one opaque universal AI score;
- one full model for every sparse country×sector×capitalisation intersection;
- raw cross-asset score pooling;
- direct news/LLM action authority;
- autonomous source-code/policy rewriting;
- direct model-to-broker calls;
- automatic retry of unknown/rejected orders;
- silent important forward-fill;
- silent provider substitution;
- proportional redistribution of unknown ETF holdings;
- default external telemetry containing portfolio/model data;
- closure based only on a merged PR or passing unit tests;
- any implementation sourced from leaked proprietary code, credentials or unverifiable documents;
- treating an ordinary fund NAV as an intraday ETF market price;
- comparing business-model-specific metrics through a universal cross-sector percentile;
- converting a future foreign-asset distribution at one fixed current spot rate;
- hard-coding a ticker or current PRIIPs/product risk label as the VWCE Medium profile;
- silently downgrading Full/High/Medium to a shallower analysis;
- triggering model training/HPO as an undeclared normal analysis stage;
- storing provider API keys in YAML, Parquet, logs, URLs, prompts or audit packets;
- personal suitability or allocation advice for a guest under a disclaimer-only approach;
- tax optimisation/advice in the core research release.

### Defer until a separate accepted issue and evidence pack

- floating-rate and inflation-linked bond forecasting beyond deterministic contractual support;
- option-adjusted spread for callable debt;
- convertibles, perpetuals, ABS/MBS and structured notes;
- shorting, margin, leverage and derivatives;
- futures/intraday/high-frequency operation;
- multi-broker live routing and smart-order-routing;
- unrestricted market orders or after-hours trading;
- reinforcement-learning execution or portfolio agents;
- public signal service, managed-account or adviser functionality;
- live bond automation before broker-specific quote/RFQ, liquidity and settlement certification;
- public/paid recommendation distribution, adviser or managed-account functionality;
- jurisdiction-specific tax optimisation;
- unsupported ordinary-fund structures such as hedge/private-equity funds, insurance wrappers and complex structured funds;
- claiming 2Y/5Y prospective efficacy before those frozen outcomes mature.

### Quarantine as research-only

- unverified institutional leaks or anonymous screenshots;
- performance screenshots without data/strategy provenance;
- alternative data with unclear licence/point-in-time history;
- news sentiment as direct alpha before independent incremental validation;
- synthetic-data “performance” evidence;
- factors/models discovered after viewing the locked final test;
- local adapters with insufficient effective sample and independent decision dates;
- fund histories that omit closed/merged/liquidated funds or contain unidentified incubation/backfill;
- unofficial global fund/NAV/holdings datasets with unclear terms or point-in-time lineage;
- selected-currency forecasts without a validated joint FX scenario;
- sparse country×sector top-*N* results below minimum effective support;
- risk profiles whose default ordering or VWCE anchor has not been calibrated and versioned.

## Part XIV — ChatGPT and LLM audit layer

### Allowed

- explain sealed calculations and source conflicts;
- summarise supplied filings/news with exact citation spans;
- identify missing evidence, contradictions and limitations;
- compare model cards, experiment protocols and outcome records;
- inspect an exported audit packet and return schema-validated commentary;
- generate a draft research hypothesis that still enters the governed experiment system.

### Forbidden

- calculate authoritative portfolio/accounting metrics from prose;
- fabricate a missing fact, price, holding, cash flow or forecast;
- modify scores, targets, limits, model authority or execution authority;
- approve or submit an order;
- access broker secrets;
- use current news in a historical decision without point-in-time validation;
- claim a proprietary leaked method is authentic or reusable.

Every LLM output stores model/prompt/schema version, input document IDs/hashes, exact citations and an authority label. It is reproducible commentary and never a hidden calculation dependency.

## Part XV — Primary source and artefact register

### Repository and supplied artefacts

- Live `docs/product-completion/CURRENT_STATUS.json`, reviewed 21 July 2026.
- Live `issues/issue_registry.json`, `issues/open.md`, `issues/closed.md` and `plan.md`.
- `Updates to app(1).zip`, including the extensive app-idea/issue audit, three-state grading and four institutional research reports.
- `ETF_AI_Cockpit_Institutional_Research_and_Integration_Blueprint_2026-07-21(1).md`.
- `ETF_AI_Cockpit_Issue_Ready_Backlog_2026-07-21(1).md`.
- `ETF_AI_Cockpit_Implementation_Workbook_2026-07-21(1).xlsx`.

### Performance measurement

- CFA Institute, *GIPS Standards Handbook for Firms*: https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/
- CFA Institute, *GIPS Standards Handbook for Asset Owners*: https://www.gipsstandards.org/standards/gips-standards-for-asset-owners/gips-standards-handbook-for-asset-owners/

These sources support time-weighted returns, external-flow treatment, geometrically linked sub-period returns, daily dated cash flows for MWR and transaction-cost treatment. This app does not claim formal GIPS compliance.

### Fixed income

- FINRA, bond concepts and risks: https://www.finra.org/investors/investing/investment-products/bonds
- FINRA, understanding bond yield and return: https://www.finra.org/investors/insights/bond-yield-return
- FINRA accrued-interest calculator/rule material: https://accruedinterest.nga.finra.org/calculator/
- Investor.gov, bonds/fixed-income FAQs: https://www.investor.gov/introduction-investing/investing-basics/investment-products/bonds-or-fixed-income-products/bonds
- OpenGamma Strata fixed-coupon bond pricer API: https://strata.opengamma.io/apidocs/com/opengamma/strata/pricer/bond/DiscountingFixedCouponBondProductPricer.html
- QuantLib official documentation/licence: https://www.quantlib.org/
- ECB euro-area yield-curve methodology: https://data.ecb.europa.eu/methodology/yield-curves
- ESMA non-equity transparency/liquidity publications: https://www.esma.europa.eu/press-news/esma-news/esma-publishes-annual-transparency-calculations-non-equity-instruments-and-0
- FINRA fixed-income/TRACE data: https://www.finra.org/finra-data/fixed-income


### Ordinary funds, NAV/dealing and public fund data

- Investor.gov, Net Asset Value and mutual-fund/ETF pricing mechanics: https://www.investor.gov/introduction-investing/investing-basics/glossary/net-asset-value
- Investor.gov, *Characteristics of Mutual Funds and ETFs*: https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/characteristics-mutual-funds-exchange-traded-funds
- SEC Form N-PORT bulk data sets, October 2019–June 2026: https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets
- SEC Data Library, including Form N-CEN: https://www.sec.gov/data-research/sec-markets-data
- ESMA Registers A2A help and UCITS/AIF cross-border schemas: https://registers.esma.europa.eu/publication/helpApp
- AMFI India NAV download/history: https://www.amfiindia.com/net-asset-value/nav-download
- FINRA Fund Analyzer context via Investor.gov: https://www.investor.gov/financial-tools-calculators/financial-tools/mutual-fund-analyzer

These sources establish NAV/dealing and disclosure mechanics and free-data availability. They do not establish complete global coverage or forecast skill. SEC bulk data are as-filed and explicitly not guaranteed accurate or complete; issuer/regulator documents remain the controlling evidence for investment decisions.

### Mutual-fund performance, cost and survivorship evidence

- Carhart, *On Persistence in Mutual Fund Performance*: https://doi.org/10.1111/j.1540-6261.1997.tb03808.x
- Wermers, *Mutual Fund Performance: An Empirical Decomposition…*: https://doi.org/10.1111/0022-1082.00263
- Evans, *Mutual Fund Incubation*: https://doi.org/10.1111/j.1540-6261.2010.01579.x
- Fama and French, *Luck versus Skill in the Cross-Section of Mutual Fund Returns*: https://doi.org/10.1111/j.1540-6261.2010.01598.x

Carhart and Fama/French emphasise costs and limited persistent net alpha; Wermers provides credible contradictory evidence that underlying stock selection can add gross value and that some high-turnover funds beat a Vanguard index net in the studied period. The cockpit must therefore measure costs, factors, holdings, survivorship and prospective outcomes rather than encode either conclusion as a fixed rule.

### Forecast-distribution and predictive-comparison methodology

- Gneiting and Raftery, proper scoring rules: https://doi.org/10.1198/016214506000001437
- Diebold and Mariano, forecast accuracy comparison: https://doi.org/10.1080/07350015.1995.10524599
- Clark and West, nested-model forecast tests: https://doi.org/10.1016/j.jeconom.2006.05.023
- Newey and West, HAC covariance: https://doi.org/10.2307/1913610
- Hansen and Hodrick, overlapping multi-step forecasts: https://doi.org/10.1086/260910
- Welch and Goyal, equity-premium prediction scepticism: https://doi.org/10.1093/rfs/hhm014
- Campbell and Thompson, restricted predictive regressions: https://doi.org/10.1093/rfs/hhm055
- Rapach, Strauss and Zhou, forecast combinations: https://doi.org/10.1093/rfs/hhp063
- Bhojraj and Lee, comparable-firm selection: https://doi.org/10.1111/1475-679X.00054

The contradictory equity-premium literature supports transparent historical-average/simple baselines, constrained economic priors, combinations only when validated, and no universal promise of predictability. Overlapping 2Y/5Y labels require dependence-aware inference and effective-decision reporting.

### FX reference data and selected-currency semantics

- ECB euro foreign-exchange reference rates: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
- ECB exchange-rate explanation: https://www.ecb.europa.eu/ecb-and-you/explainers/tell-me-more/html/role_of_exchange_rates.en.html
- Bank of Canada Valet API: https://www.bankofcanada.ca/valet-api-how-to/
- BIS Data Portal: https://data.bis.org/

ECB reference rates are normally updated around 16:00 CET and are published for information purposes; transaction use is discouraged. The application uses them for dated valuation/analysis, not as executable FX fills. Bank of Canada Valet requires no registration or access key and has no API cost as of this review.

### Free API access, quotas and local secret protection

- OpenFIGI API documentation and key-dependent rate limits: https://www.openfigi.com/api/documentation
- FRED API key requirements: https://fred.stlouisfed.org/docs/api/api_key.html
- Companies House developer rate limits: https://developer.company-information.service.gov.uk/developer-guidelines/
- Microsoft `CryptProtectData`: https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- Microsoft `CryptUnprotectData`: https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata
- Microsoft Credential Manager user documentation: https://support.microsoft.com/en-us/windows/security/credential-manager-in-windows

OpenFIGI is free and permits lower unauthenticated throughput and higher key-authenticated throughput. FRED requires an API key for all web-service requests. Companies House currently documents 600 requests per five-minute window. Windows DPAPI normally binds decryption to the same user and computer and therefore requires explicit backup/password-reset limitation documentation.

### VWCE anchor and recommendation presentation

- Vanguard FTSE All-World UCITS ETF accumulating share class, ISIN `IE00BK5BQT80`: https://www.vanguard.co.uk/uk-fund-directory/product/etf/equity/9679/ftse-all-world-ucits
- AFM finfluencing/personal-advice guidance: https://www.afm.nl/en/sector/themas/digitalisering/finfluencing
- AFM investment-recommendation transparency: https://www.afm.nl/en/sector/themas/marktmisbruik/beleggingsaanbevelingen
- ESMA requirements for investment recommendations on social media: https://www.esma.europa.eu/press-news/esma-news/requirements-when-posting-investments-recommendations-social-media
- Commission Delegated Regulation (EU) 2016/958: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0958

The Vanguard page confirms one accumulating share class has multiple listing tickers/currencies and dated product/risk/tracking facts; use the ISIN and a sealed snapshot. AFM guidance states that a disclaimer is not enough if conduct is personalised in practice. General recommendation outputs therefore require objective presentation, source/conflict disclosure, horizon and risk, while guest mode remains non-personalised.

### Algorithmic execution and broker controls

- ESMA, MiFID II Article 17: https://www.esma.europa.eu/publications-and-data/interactive-single-rulebook/mifid-ii/article-17-algorithmic-trading
- Commission Delegated Regulation (EU) 2017/589 (RTS 6): https://eur-lex.europa.eu/eli/reg_del/2017/589/oj/eng
- ESMA algorithmic-trading supervisory briefing, 26 February 2026: https://www.esma.europa.eu/press-news/esma-news/esma-issues-supervisory-briefing-algorithmic-trading
- Interactive Brokers TWS API order-state documentation: https://interactivebrokers.github.io/tws-api/order_submission.html

### Statistical/model evidence retained from the prior researched package

- Gu, Kelly and Xiu, *Empirical Asset Pricing via Machine Learning*: https://www.nber.org/papers/w25398
- Harvey, Liu and Zhu, *… and the Cross-Section of Expected Returns*: https://www.nber.org/papers/w20592
- DeMiguel, Garlappi and Uppal, *Optimal Versus Naive Diversification*: https://ideas.repec.org/a/oup/rfinst/v22y2009i5p1915-1953.html
- Cakici et al., *Machine Learning Goes Global*: https://doi.org/10.1016/j.jedc.2023.104725
- Cakici and Zaremba, *The More, the Better?*: https://doi.org/10.1016/j.jbankfin.2026.107658
- Hellum, Pedersen and Rønn-Nielsen, *How Global Is Predictability?*: https://research.cbs.dk/en/publications/how-global-is-predictability-the-power-of-financial-transfer-lear/
- Loughran and McDonald, financial-language sentiment research: https://papers.ssrn.com/abstract=1331573
- Coqueret, stock-specific sentiment and return predictability: https://doi.org/10.1080/14697688.2020.1736314
- Benjamini and Hochberg, false discovery rate: https://doi.org/10.1111/j.2517-6161.1995.tb02031.x
- Bailey et al., backtest overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659

### Institutional public methods/software

The full company-by-company mapping and URLs are preserved in Part 8.2. They include Northfield, SimCorp Axioma, Man AHL, Acadian, Robeco Quant, Research Affiliates, Dimensional, Scientific Beta, TOBAM, Quoniam, Ortec Finance, BlackRock/Aladdin, MSCI Barra, Bloomberg PORT, State Street Alpha, Two Sigma, AQR, Man Group and Goldman Sachs/GS Quant.

### Authenticated model-control incidents

- SEC, Two Sigma settlement, 16 January 2025: https://www.sec.gov/newsroom/press-releases/2025-15
- SEC, AXA Rosenberg coding-error settlement: https://www.sec.gov/news/press/2011/2011-37.htm
- Goldman/Aleynikov New York Court of Appeals record: https://law.justia.com/cases/new-york/court-of-appeals/2018/47.html
- MSCI/Axioma litigation record: https://www.nycourts.gov/reporter/3dseries/2014/2014_06239.htm

These records support controls and clean-room development only. They do not authorise use of proprietary models or code.

### Conflict, replication and uncertainty notes

- Manager/vendor publications have commercial conflicts and can motivate patterns, not prove independent alpha.
- Model studies are generally observational/backtest studies, often not preregistered, and exposed to data mining, costs, survivorship, regime and publication bias.
- Standards, regulator, central-bank and broker documents are primary for definitions, legal text, published data or API behaviour—not forecast skill.
- Open-source pricing libraries reduce implementation risk but require pinned versions, licence review, golden/differential tests and independent formulas.
- Regulatory algorithmic-trading rules apply according to legal status/jurisdiction; the legal issue determines actual applicability.
- No backtest establishes production reliability. Forward evidence and operational drills remain mandatory.
