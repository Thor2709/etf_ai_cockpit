# ETF AI Cockpit Programme Index

> **Execution mode:** Subagent-Driven is mandatory. The repository now has a real Git baseline on `main`; Wave 0 Tasks 1-5, Wave 1 Governance Tasks 1-6, Wave 3 Tasks 7-9 and Wave 4 Tasks 10-21 are independently approved, merged and post-merge verified. Task 10 is closed locally and synchronised to GitHub Issue #81; Tasks 11-21 are implementation-complete with their owning issues still closure-pending strict release/package/audit/export/browser/clean-first-run evidence. Wave 5 Task 22 is under semantic reconciliation review on `wave5/task22-reconciliation`; Task 23 is deferred until the reconciled Task 22 base is approved and committed.

**Binding inputs:**

- Repository state: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit`.
- Authorised outcomes: `C:\Users\thor2\Downloads\ETF_AI_Cockpit_All_Other_Issues_and_General_Information_2026-07-11_Prompt-Optimised_Superpowers-Aligned_EU-Tech-Expanded.md`.
- Historical state: `issues/`, `configs/closure_matrix.yaml`, `.ai_worklog/`, `RUN_STATE.json`, `RUN_LOG.md`, `HANDOFF.md`, and existing evidence artefacts.

**Baseline recorded on 2026-07-11:**

| Check | Command | Result | Classification |
|---|---|---|---|
| Repository detection | `git rev-parse --is-inside-work-tree` | exit 128; no usable Git repository | Environment limitation, not a product failure |
| Full source tests | `.\.venv\Scripts\python.exe -m pytest tests -q` | exit 0; quiet output suppressed the numerical summary | Fresh broad regression baseline |
| Lint | `.\.venv\Scripts\python.exe -m ruff check src tests` | `All checks passed!` | Fresh broad lint baseline |
| Compilation | `.\.venv\Scripts\python.exe -m compileall -q src` | exit 0 | Fresh broad compilation baseline |
| Source snapshot | `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` | `snapshot_ok as_of=2026-07-09 signals=16 backtests=5` | Fresh source smoke baseline |
| Existing type check | recorded `mypy_scope` in `RUN_STATE.json` | exit 1 from missing third-party stubs and existing typing debt | Pre-existing baseline failure; no new work may claim to fix it without focused evidence |

The repository-recorded 262-pass run, package smoke and Chrome evidence remain historical broad evidence. They are not closure evidence for any new implementation task. The closure evaluator currently records four ready items (`ISSUE-0035`, `ISSUE-0069`, `UPDATEV2-0022`, `UPDATEV2-0028`) and 36 tracker records remain open. This programme adds DATA-05 as a distinct record without rewriting the historic 41-record baseline.

## Programme-wide constraints copied into every plan

1. No scope drift: implement only authorised outcomes and DATA-05 coverage; do not add adjacent capabilities.
2. No authority inflation: evidence, analysis, experimental models, research states, portfolio-review states and user decisions remain distinct; `execution_allowed` is always `false`.
3. Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and responsive Flet shell.
4. Extend through narrow migrations and compatibility adapters. Do not conduct unrelated repository-wide refactoring.
5. Never rewrite history, delete user data, use credentials, purchase services or bypass review/check gates. Git branch, commit, push, pull-request and GitHub Issue actions are permitted only where the current user authorisation and applicable integration gates explicitly allow them.
6. Retrieve current primary/official evidence where correctness depends on an external identifier, API, package, venue, issuer or standard. Empty, stale or conflicting evidence is explicit unavailable, conflicted or blocked state.
7. Test observable behaviour, invariants and failure paths. A mock-call assertion alone is insufficient.
8. Each substantive task follows RED - GREEN - REFACTOR, receives a fresh implementer and a separate fresh task reviewer, and records test/review evidence before completion.
9. Visible Flet changes reuse the current dark evidence-cockpit tokens/components and include applicable default, focus, disabled, loading, success, partial, stale, unavailable, empty and error states; text, icon and semantics communicate status in addition to colour.
10. No completion claim is valid without fresh applicable source, migration, tests, type/lint/compile, source/package/browser, audit/export, independent-review and tracker/worklog evidence.
11. DATA-05 changes monitored coverage only. It does not alter score weights, model authority, portfolio targets, research thresholds or execution scope.
12. Preserve all closed dossiers. New work must not re-open a ready record unless a reproducible regression requires a separately recorded reopening event.

## Scope boundary

This programme owns Issue Groups A, C through N in the supplied specification. The companion performance document owns `PERF-01` through `PERF-06` and `UI-06`; this programme consumes their existing workflow/performance interfaces but does not redesign those companion issues.

## Dependency order and plan ownership

| Wave | Plan | Specification epics owned exactly once | Primary repository seam | Prerequisites | Completion interface for next wave |
|---:|---|---|---|---|---|
| 0 | [foundation, operations and boundary plan](2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md) | `REL-01`, `REL-02`, `REL-03`, `REL-04`, `FUTURE-01`, `FUTURE-03` | `core/atomic_io.py`, `core/session_log.py`, `core/closure.py`, `core/migrations.py`, scripts and release paths | Tasks 1-5 complete and merged | Versioned `VerificationRun`, `ClosureEvidenceRecord`, recovery transaction contract, static execution/rejection report and deterministic evidence automation |
| 1 | [governance plan](2026-07-11-etf-ai-cockpit-governance-plan.md) | `GOV-01`, `GOV-02`, `GOV-03`, `GOV-04` | `core/types.py`, `signals/actions.py`, `signals/gates.py`, `signals/simple_scores.py`, `portfolio/proposals.py`, `app/router.py` | Wave 0 evidence interfaces | Typed research/portfolio authority decision, governance config checksums, immutable journal and non-execution boundary |
| 2 | [registry and universe plan](2026-07-11-etf-ai-cockpit-registry-universe-plan.md) | `DATA-01`, `DATA-02`, `DATA-03`, `DATA-04` | `data/universe_store.py`, `core/config.py`, `data/instrument_identity.py`, `data/trade_candidate_analysis.py`, Universe page | Waves 0-1 | Canonical registry generation, listing-scoped provider mapping, classification/support resolution and collection membership service |
| 3 | [DATA-05 verified coverage plan](2026-07-11-etf-ai-cockpit-data05-plan.md) | `DATA-05` | canonical registry/compatibility universe migration, instrument detail, Data Health and audit manifest | Wave 2 registry contract; Wave 1 authority contracts | Atomic all-or-nothing 39-exposure seed revision, verification manifest, EU-tech subarea resolver and 8/9/8 audit manifest |
| 4 | [storage and evidence plan](2026-07-11-etf-ai-cockpit-storage-evidence-plan.md) | `STORE-01`, `STORE-02`, `STORE-03`, `STORE-04`, `EVID-01`, `EVID-02`, `EVID-03`, `EVID-04`, `EVID-05` | `data/duckdb_store.py`, `data/contracts.py`, evidence providers/parsers, Data Health/evidence pages | Waves 0-3 stable IDs and transaction primitive | Persistent catalogue/current-as-of views, source objects/lineage, document/fact/event registry and constrained retrieval/export services |
| 5 | [domain and scoring plan](2026-07-11-etf-ai-cockpit-domain-scoring-plan.md) | `DOMAIN-01`, `DOMAIN-02`, `DOMAIN-03`, `DOMAIN-04`, `SCORE-01`, `SCORE-02`, `SCORE-03`, `SCORE-04`, `SCORE-05` | `signals/simple_scores.py`, `features/`, `portfolio/risk_analytics.py`, source facts and score UI | Waves 1, 2 and 4 | Template resolution, explicit benchmark assignment, non-AI champion policy, factor/risk/friction records and `DecisionReport` |
| 6 | [AI and validation plan](2026-07-11-etf-ai-cockpit-ai-validation-plan.md) | `AI-01`, `AI-02`, `AI-03`, `AI-04`, `AI-05`, `VALID-01`, `VALID-02`, `VALID-03`, `VALID-04`, `VALID-05`, `VALID-06`, `FUTURE-02` | `models/`, `backtest/`, local LLM bridge and optional research namespace | Waves 0-5 | Zero-authority forecast/result lifecycle, cited LLM output, trial/fold registry, prospective diary and isolated research outputs |
| 7 | [portfolio plan](2026-07-11-etf-ai-cockpit-portfolio-plan.md) | `PORT-01`, `PORT-02`, `PORT-03`, `PORT-04`, `PORT-05` | `portfolio/`, existing holdings/allocation/rebalancing pages | Waves 1, 2, 4 and 5 | Immutable ledger-derived portfolio snapshots, valuation/performance records, scenarios and portfolio-review resolver |
| 8 | [workspace and workflow plan](2026-07-11-etf-ai-cockpit-workspaces-workflow-plan.md) | `UI-01`, `UI-02`, `UI-03`, `UI-04`, `UI-05`, `WORK-01`, `WORK-02`, `WORK-03`, `WORK-04` | `app/router.py`, `app/flet_app.py`, `app/pages/`, `app/components/`, `core/workflow.py`, `core/scheduler.py` | Waves 0-7 committed view models | Workflow workspace registry, semantic navigation, job centre, queue/calendar/brief/scheduler and source/package parity evidence |
| 9 | programme-wide release closure | No new product epic; closes applicable wave evidence in its owning plan | closure matrix, audit export, release scripts, `.ai_worklog` | Waves 0-8 | Fresh, independent, issue-specific evidence records and an honest release manifest |

## One-to-one existing tracker ownership

Each active tracker item below has exactly one owning plan. Cross-plan consumers may depend on its public interface, but must not claim ownership or close it.

| Open tracker record | Owning plan/wave | Reason for primary ownership |
|---|---|---|
| `UPDATEV2-0029`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0045` | Wave 0 foundation | Release verification, clean-environment harness and semantic/browser evidence |
| `UPDATEV2-0027`, `ISSUE-0011`, `ISSUE-0012`, `ISSUE-0039`, `ISSUE-0040`, `ISSUE-0044` | Wave 0 foundation | Workflow trace, reliability, recovery, package and evidence discipline |
| `ISSUE-0008`, `ISSUE-0010`, `ISSUE-0030`, `ISSUE-0043`, `ISSUE-0060`, `ISSUE-0066` | Wave 1 governance | Product scope, user decision separation and no-execution boundary |
| `UPDATEV2-0011`, `ISSUE-0017`, `ISSUE-0018`, `ISSUE-0056`, `ISSUE-0068` | Wave 2 registry/universe | Identity, collections, first-run migration and unsupported-asset routing |
| `DATA-05` | Wave 3 DATA-05 | New separately traceable 39-exposure coverage requirement |
| `UPDATEV2-0010`, `UPDATEV2-0021`, `UPDATEV2-0012`, `UPDATEV2-0013`, `UPDATEV2-0015`, `UPDATEV2-0016`, `UPDATEV2-0017`, `UPDATEV2-0019`, `ISSUE-0023`, `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0055` | Wave 4 storage/evidence | Provider authority, official documents, point-in-time facts and source-linked events |
| `ISSUE-0046`, `ISSUE-0047`, `ISSUE-0049`, `ISSUE-0051`, `ISSUE-0052`, `ISSUE-0059`, `ISSUE-0064`, `ISSUE-0065`, `ISSUE-0067` | Wave 5 domain/scoring | Template-specific analysis, benchmark/risk/friction and transparent decision reports |
| `ISSUE-0027`, `ISSUE-0048`, `ISSUE-0057`, `ISSUE-0061`, `ISSUE-0062` | Wave 6 AI/validation | Model challenger governance, calibration, overfitting and research isolation |
| `ISSUE-0026`, `ISSUE-0029`, `ISSUE-0031`, `ISSUE-0033`, `ISSUE-0037` | Wave 7 portfolio | Ledger, valuation, performance, scenarios and portfolio fit |
| `ISSUE-0015`, `ISSUE-0016`, `ISSUE-0019`, `ISSUE-0034`, `ISSUE-0036`, `ISSUE-0041`, `ISSUE-0042` | Wave 8 workspaces/workflow | Information architecture, entity workspaces, queue/calendar and accessible rendering |

Already-ready records are preserved and excluded from active ownership: `ISSUE-0035`, `ISSUE-0069`, `UPDATEV2-0022`, and `UPDATEV2-0028`.

## Requirement-to-repository map

| Requirement family | Existing component or contract extended | Migration seam | Evidence required |
|---|---|---|---|
| Governance/action taxonomy | `core/types.py:7-151`, `signals/actions.py`, `signals/gates.py`, `portfolio/proposals.py`, `chatgpt_bridge/` | Versioned legacy action import with preserved `legacy_action`; release-facing v2 schema | RED migration/gate tests, static boundary report, journal/audit export and source/package route evidence |
| Canonical identity/universe | `data/universe_store.py`, `core/config.py`, `data/instrument_identity.py`, `app/pages/universe_manager.py` | Flat `UniverseRecord`/`ETFConfig` compatibility view over canonical issuer-security-listing generation | ID validators, row-count/crosswalk, revision/rollback, UI CRUD/impact and source/package journeys |
| DATA-05 | existing revision-protected `save_universe(..., expected_revision=...)` path and instrument-detail/router state | schema-versioned compatibility fields until full registry is authoritative | live official/provider verification manifest, all-39/25/8-9-8 validators, successor test, deep links, audit checksum |
| Storage/recovery | `core/atomic_io.py`, `data/duckdb_store.py`, `data/health.py`, audit export | existing Parquet paths become catalogue generations; existing atomic primitive is the only commit primitive | crash/fault/restore, current/as-of views, lineage and constrained query/export evidence |
| Official evidence | `data/provider_registry.py`, `trust_artifacts.py`, `sec_edgar_provider.py`, `esef_provider.py`, parser modules and evidence pages | existing provider/evidence rows become versioned field-level assertions/documents/events | fixture and live-informational separation, exact citation locator, failure security tests, coverage/audit/package evidence |
| Domain/scoring | `signals/simple_scores.py`, `features/`, `models/ensemble.py`, `backtest/benchmarks.py` | score rows adapt to typed template, gate, benchmark and report contracts | policy replay, no-AI/no-first-benchmark/no-score-edge mutations, risk/friction and report browser evidence |
| AI/validation | `models/timesfm_adapter.py`, `models/toto_adapter.py`, `models/calibration.py`, `backtest/walk_forward.py`, `backtest/overfitting.py` | v1 forecast/cache migration and quarantine; engine remains low-level simulator | state transition, no-lookahead, citations/injection, fold/trial, prospective immutability and package-optional evidence |
| Portfolio | `portfolio/holdings.py`, `allocation.py`, `rebalancing.py`, `risk_analytics.py` | sample holdings importer becomes explicitly labelled opening-balance/demo migration | replay/FX/performance reconciliation, scenario gate, privacy export and portfolio UI evidence |
| Flet/workflow | `app/router.py`, `app/flet_app.py`, `app/pages/`, `app/components/`, `core/workflow.py`, `core/scheduler.py` | old flat routes receive aliases and typed workspace metadata | semantic locator, focus/keyboard, viewport/zoom, no-compute-on-render, job and package/deep-link evidence |

## Pre-flight contradiction record

No blocking authorised-requirement contradiction was found. The following precedence decisions are binding:

1. Current repository foundations supersede older absence claims; the full target remains open until fresh issue-specific evidence exists.
2. `execution_allowed=false` and the no-broker boundary outrank all legacy action/proposal/ensemble wording.
3. The canonical registry is the preferred DATA-05 path; the schema-versioned `UniverseRecord` compatibility migration is permitted only while it remains revision-protected and auditable.
4. DATA-05 requires real-time official/source verification. The specification seeds are expected values, not facts to copy without a discrepancy manifest.
5. The local baseline Git setup is complete at `445dd44b5382160d4e93e4cada018beb4ab0f5b5`. Wave 0 Task 3's five fix passes and fresh independent approval are recorded through `201ee9e`; PR 1 merged it into `main` at `046e3bbfe9cab41f6cfec59547f540bce85b2c44`, with post-merge focused/source verification passed. `ISSUE-0040` is still open for its later UI/package/browser gates.
6. Wave 3 Task 7 was independently re-reviewed after source-linked UI inventory and rendered-route evidence fixes. PR 177 merged it into `main` at `f6e0c9ca2105af2e4f176d4c0253339161fbe235`; focused/affected tests, compileall, Ruff, source smoke, Windows build, native/portable/launcher smoke and Errors/Diagnostics browser evidence are recorded in `.ai_worklog/task7-report.md`. `ISSUE-0011`, `ISSUE-0040` and `ISSUE-0039` remain open for complete closure dossiers.

## Durable checkpoint protocol

At the end of every reviewed task, update:

1. the task checkbox in its owning plan;
2. `2026-07-11-etf-ai-cockpit-progress-ledger.md`;
3. `RUN_STATE.json`, `RUN_LOG.md` and applicable `.ai_worklog/*` record;
4. the corresponding `configs/closure_matrix.yaml` evidence paths only after the required evidence exists.

The next agent must reread this index, the active plan, the progress ledger, the attached specification and the latest test/review evidence before continuing.

## 2026-07-11 plan pre-flight evidence

- The separate plan set contains nine dependency-ordered implementation plans, each with an `Implementation Plan` header, global constraints, exact task files, public interfaces and RED-GREEN-REFACTOR commands.
- The full programme index and plans cover all 60 authorised epics (`GOV`, `DATA`, `STORE`, `EVID`, `DOMAIN`, `SCORE`, `AI`, `VALID`, `PORT`, `UI`, `WORK`, `REL` and `FUTURE`) with no missing identifier.
- The one-to-one ownership table covers all 37 current `still_open` closure-matrix records exactly once; the four ready records remain explicitly excluded; DATA-05 is represented as the new separately owned record.
- Placeholder scan over all nine implementation plans found no `TBD`, `TODO`, `add tests`, `handle errors`, `similar to above` or `implement later` placeholder.
- The documentation-only pre-flight change corrected the final plan heading. No implementation code, configuration, tracker status or user data has changed.
- Fresh baseline evidence recorded before implementation: pytest exit 0, Ruff clean, compileall exit 0, source snapshot smoke exit 0, source/native/portable smoke exit 0, and a rendered in-app-browser inspection of the source Simple Scores route.
- No blocking product contradiction remains after applying the approved precedence rules. Wave 0, Tasks 1 and 2 are independently reviewed complete. Wave 0, Task 3 is independently approved, merged and post-merge verified with no Critical, Important or Minor findings. Wave 0, Task 4 and its generated-package correction are independently approved, merged through PRs 2 and 3, and post-merge verified. Wave 0, Task 5, Wave 1 governance Tasks 1-6 and Wave 3 Task 7 are independently approved, merged and post-merge verified; Wave 3 Task 7 has no Critical or Important findings and two non-blocking Minor recommendations; Wave 3 Task 8 is next.

## GitHub issue synchronisation checkpoint - 2026-07-12

The local issue ledgers were inventoried and synchronised to the authenticated
`Thor2709/etf_ai_cockpit` mirror. The deterministic map contains 98 unique
records (77 selected open and 21 selected closed), with stable markers,
canonical numbers, source checksums and read-back state. The final apply and
idempotence dry run passed; no unresolved duplicate remains. Exact-marker
duplicates were retained and closed as duplicates, without deleting any GitHub
Issue or changing local issue state. The durable map, report and evidence are
`issues/github_issue_map.json`, `issues/github_issue_sync_report.json` and
`.ai_worklog/github-issue-sync.md`.

## Wave 1 Governance Task 1 integration checkpoint - 2026-07-12

Task 1 is complete at the task boundary and integrated into `origin/main`.
PR 171 (`https://github.com/Thor2709/etf_ai_cockpit/pull/171`) merged at
`a54aed9c8157ff361eb7782252a88a471b835499`. The independent re-review passed
specification compliance and code quality with no findings. Focused governance
verification passed 43 tests; the full suite reproduced 316 passes and seven
pre-existing generated-data/identity fixture failures; scoped Ruff and
compileall passed. No owning issue is closed by this foundation task. The next
dependency-valid task is Wave 1 Governance Task 2, research-state migration.

## Wave 1 Governance Task 2 integration checkpoint - 2026-07-12

Task 2 is complete at the task boundary and integrated into `origin/main`.
PR 172 (`https://github.com/Thor2709/etf_ai_cockpit/pull/172`) merged at
`ab4772c36701507da444ebd73243ff827b5403af`. The v1.x-to-v2.0 migration now
separates research state, portfolio review state and internal analytical
intent, preserves `legacy_action`, validates snapshot checksums and rejects
forged authority markers. Direct v2 models reject non-2.0 metadata and cannot
mint positive authority; release serializers omit legacy `action` fields and
keep `execution_allowed=false`. The final fresh independent review and
re-review passed specification compliance and code quality with no findings.
The post-merge focused bundle passed 82 tests, compileall, scoped Ruff and
source smoke passed. The full suite still has the seven documented
pre-existing generated-data/identity fixture failures. No owning issue is
closed by this foundation task. The next dependency-valid task is Wave 1
Governance Task 3, the central severity-aware authority resolver.

Wave 1 Governance Task 3 is now independently approved and integrated through
PR 173 (`https://github.com/Thor2709/etf_ai_cockpit/pull/173`) at merge commit
`5fde19639da9caa6cdb01eef852dc34698b53482`. The resolver is consumed by both
signal and simple-score release paths; ordered nine-gate tables, policy
metadata and diagnostics are serialised, incomplete evidence fails closed and
`execution_allowed` remains `false`. Post-merge focused authority tests (48),
affected governance/migration/proposal/export tests (88), compileall, Ruff,
source import smoke, diff checks and the full suite (exit 0) passed. No issue
state changed. Wave 1 Governance Task 4 is the next dependency-valid task.

Wave 1 Governance Task 4 is independently approved and integrated through PR
174 (`https://github.com/Thor2709/etf_ai_cockpit/pull/174`) at merge commit
`c61531841a753ce1e3f862f8beb498c629b9cbb5`. It adds neutral non-executable
review reports, a checksum-protected append-only Decision Journal with grouped
atomic publication/reads, deterministic bounded supersedes and owner-token
filesystem locking. Focused Task 4 tests (23), affected authority/release/
atomic/transaction tests, compileall, Ruff, source smoke and the post-merge
full suite passed. No issue state changed; Wave 1 Governance Task 5 is the next
dependency-valid task.

Wave 1 Governance Task 5 is independently approved and integrated through PR
175 (`https://github.com/Thor2709/etf_ai_cockpit/pull/175`) at merge commit
`6689e8c9c6a52a1b1ef1300c3c2356b006c449fa`. System Map, Help/Glossary and
user-owned Decision Journal surfaces, per-dependency readiness, hash-targeted
glossary navigation and keyboard-operable navigation are now integrated.
Focused post-merge tests (50), static boundary, source smoke and rendered
browser evidence passed; no issue moved to closed. Wave 1 Governance Task 6
is independently approved and integrated through PR 176
(`https://github.com/Thor2709/etf_ai_cockpit/pull/176`) at merge commit
`16205d259380421d7041ffb46d61acce84ec1993`. The existing typed workflow and
session-trace runtime remains authoritative; the four primary dashboard
workflow controls are now genuine keyboard-operable outlined buttons with
stable keys, tooltips and callbacks. Focused/post-merge tests (29),
compileall, scoped Ruff, source snapshot smoke, native package rebuild/direct
HTTP readiness and rendered dashboard evidence passed. The generated-data
fixture smoke limitation is explicitly recorded in `.ai_worklog/task6-report.md`;
no issue moved to closed. Wave 3 Task 7 (Button Audit, Error/Recovery Centre
and Performance Evidence) is the next dependency-valid task.

Wave 3 Task 7 was then independently re-reviewed and integrated through PR
177 at merge commit `f6e0c9ca2105af2e4f176d4c0253339161fbe235`; its source-linked
inventory, recovery states, timing/cache diagnostics and rendered evidence are
recorded in `.ai_worklog/task7-report.md`. No issue moved to closed. Wave 3
Task 8 (Canonical Data Contracts and Provider Registry) is independently
approved and integrated through PR 178 at merge commit
`4c4eb00175237ad49b113adad8be3f8dcbfed618`. Focused tests passed 14; the
affected provider/trust/execution bundle passed 42 with the documented
unrelated identity fixture failure; compileall, scoped Ruff and source smoke
passed. The portable package build and launcher HTTP readiness passed, and
default plus 390x844 Provider Status screenshots are checksum-recorded in
`.ai_worklog/task8-report.md`. Native executable smoke is not_applicable
because PyInstaller is unavailable. `UPDATEV2-0010` remains open/partial
pending complete issue-level closure evidence. The next dependency-valid task
is Wave 4 Task 9, Instrument Identity, Source Conflicts and Evidence Ledger.

Wave 4 Task 9 was independently re-reviewed after the fail-closed provenance
and candidate-score compatibility fixes. Current head `262946e` received
SPECIFICATION, CODE-QUALITY and READY_FOR_INTEGRATION approval with zero
Critical, Important or Minor findings. PR 179
(`https://github.com/Thor2709/etf_ai_cockpit/pull/179`) merged into `main` at
`ec5d166ee32235367f58d31f3835854a14e11ba8`; post-merge main is clean and
matches origin. Focused Task 9 tests passed 13, candidate regressions passed 3,
affected persistence/evidence/scope tests passed 35, and the report records
bytecode-disabled compilation, forced compileall, Ruff, source smoke, portable
launcher readiness and Provider Status screenshots. `UPDATEV2-0011` and
`UPDATEV2-0021` remain open/partial pending complete issue-level gates;
`UPDATEV2-0022` remains closed. Task 10 Data Health Centre is closed and
post-merge verified through PR 180; the next dependency-valid task is Task 11,
Universe Store, Watchlists, Onboarding and Asset Guardrails.

Wave 4 Task 10 implementation is complete and merged through PR 180 at
`3eab7a414a54c74553b09ebc4085902af0ffc33e`. Bounded atomic staging and
failed-completion provenance fixes were independently re-reviewed with SPEC
PASS and CODE PASS. The authoritative full suite, native/portable package
smoke, semantic Data Health focus, export, source/package browser and
post-merge checks pass. `ISSUE-0035` is closed in the local canonical ledger;
GitHub Issue #81 was read back as closed before Task 11 starts. The 98-record
reconciliation reports 77 open and 21 closed mappings, matching states and no
unresolved duplicates.

Wave 4 Task 11 implementation is complete and merged through PR 181 at
`2eae5dea8dd1d789dd000383901e591ee4645d83`. The fresh independent review
approved specification compliance and code quality with no Critical or
Important findings. The focused universe/onboarding/guardrail/UI bundle passed
57 tests; compileall, scoped Ruff, the governance static boundary check and
source smoke passed. `ISSUE-0068`, `ISSUE-0018`, `ISSUE-0017` and `ISSUE-0056`
remain in the local open ledger because their issue records still require
fresh full-release/package/browser/clean-first-run evidence and closure-matrix
evaluation. `execution_allowed=false` remains unchanged. Task 12, SEC EDGAR
Provider and Official Statement Facts, is implemented and merged through PR 182
at `dc9765ff97f14cc29e9dd7a4f02d669ce0e5ee7f`; `UPDATEV2-0012` remains open
pending package/browser, clean-first-run and configured live SEC-network
evidence. Continue with Task 13, ESEF/iXBRL Provider and IFRS Mapping, in the
active closure plan.

Wave 4 Task 13, ESEF/iXBRL Provider and IFRS Mapping, is implemented and
independently approved through PR 183 at
`231f5be1055121e878d614b353a919d0d61d102e` (implementation commit `44db2c2`).
The bounded filings.xbrl.org provider, safe package parser, pinned Arelle
adapter, explicit IFRS mapping, checksum-addressed raw retention, atomic
statement-facts/inventory publication, manual-review provenance boundary and
Filings-page controls are present. Focused tests, worker-level Arelle
serialisation coverage, Ruff, compileall and diff checks pass. `UPDATEV2-0013`
remains open as implementation-complete/closure-pending because strict release,
audit/export, clean-first-run and browser/computer-use evidence is not yet
fresh.

Wave 4 Task 14, ETF Document Registry and Holdings Normaliser, is implemented
and independently approved through PR 184 at merge commit
`49abaf4907f81ab2798a394d11cf2ddaf5d3b031` (head `a7cb185`). The versioned
document registry, explicit missing inventory, fail-closed issuer/vendor
holdings eligibility, atomic four-file imports, ETF Disclosures/Risk panels,
Instrument Detail disclosure panel and UI acceptance contracts are present.
Focused Task 14/Risk/Instrument Detail/trust registration/button tests, Ruff,
compileall and diff checks pass; the known unrelated trust identity fixture
threshold remains documented. `UPDATEV2-0015` and `UPDATEV2-0016` remain open
until strict release, audit/export, clean-first-run and browser/computer-use
evidence is fresh. Continue with Task 15, PRIIPs KID and Index Methodology
Parsers.

Wave 4 Task 15, PRIIPs KID and Index Methodology Parsers, is implemented and
independently approved through PR 185 at merge commit
`9139e515bda9e149dde52e9074990cbc5c781e84` (implementation head `fb98b16c`).
Bounded official PDF parsing, manual-review states, holdings/methodology
conflict handling, source-aware KID cost/risk evidence, atomic parsed-document
publication, Trust Evidence/Instrument Detail panels and audit export are
present. Focused parser/persistence/UI/audit/score tests, official fixture
checksums, Ruff, compileall and diff checks pass. `UPDATEV2-0017` and
`UPDATEV2-0019` remain open as implementation-complete/closure-pending because
strict release/package, clean-first-run, audit-export and browser/computer-use
evidence is not yet fresh. Continue with Task 16, Fundamentals, News,
Point-in-Time Validation and Free Providers.

Wave 4 Task 16, Fundamentals, News, Point-in-Time Validation and Free
Providers, is implemented and independently approved through PR 186 at merge
commit `3143678` (implementation head `cd7aea5`). Strict five-section
fundamentals, point-in-time news validation, optional-provider capability
states, Dashboard/News & Context/Instrument Detail/Screener surfaces,
chronological evidence selection and audit-export ordering are present. Six
bounded fix/review cycles ended with fresh SPEC and CODE approval and no
Critical or Important findings. `ISSUE-0023`, `ISSUE-0025`, `ISSUE-0054` and
`ISSUE-0055` remain open as implementation-complete/closure-pending because
full release/package, audit/export, clean-first-run and browser/computer-use
evidence is not yet fresh. Continue with Task 17, Score History, Run
Comparison and Feature Drivers.

Wave 4 Task 17, Score History, Run Comparison and Feature Drivers, is
implemented and independently approved through PR 187 at merge commit
`265b798` (implementation head `e83edfc`). Canonical score and metric history,
complete-run replacement, legacy compatibility, deterministic run comparison,
feature-driver classifications and the Scores/Dashboard/What Changed/
Instrument Detail consumers are present. Four bounded fix/review cycles ended
with fresh SPEC and CODE approval and no Critical or Important findings;
focused verification passed 38 tests with Ruff, compileall and diff checks.
`ISSUE-0067`, `ISSUE-0034` and `ISSUE-0047` remain open as
implementation-complete/closure-pending because strict package/browser,
audit/export and clean-first-run evidence is not yet fresh. Continue with
Task 18, Crowding, Sector/Theme Attribution and Friction-Adjusted Edge.

Wave 5 Task 18, Crowding, Sector/Theme Attribution and Friction-Adjusted Edge,
is implemented and independently approved through PR 188 at merge commit
`3e3b02e` (implementation head `0a5e0a6`). Six bounded fix/review cycles ended
with fresh SPEC and CODE approval and no Critical or Important findings;
focused verification passed 53 tests with Ruff, compileall and diff checks.
`ISSUE-0052`, `ISSUE-0059` and `ISSUE-0064` remain open as
implementation-complete/closure-pending because strict release/package,
audit/export, browser and clean-first-run evidence is not yet fresh. Task 19,
Comprehensive Instrument Detail, is now merged via PR 189 at `da271bc` with
implementation head `89f4644`; `ISSUE-0019` remains implementation-complete
and closure-pending the same strict gates. Continue with Task 20,
Import/Export, Backup/Restore, Charts and Accessible Tables.

### Wave 5 Task 22 semantic reconciliation checkpoint - 2026-07-14

The clean reconciliation branch `wave5/task22-reconciliation` is based on
`origin/main` `6e6406d`. Patch-equivalent and obsolete Task 20/21 commits were
excluded; only genuine Task 22 source, configuration, tests and evidence were
transferred. The first independent review identified and blocked on five
Sparebanken identity mismatches in the canonical YAML and a plain `Cancel`
gap for explicit order-control calls. Test-first regressions now pass after
correcting the five YAML identities/ticker and extending the fail-closed
boundary scan. A fresh independent re-review is pending. Task 23 remains
deferred until Task 22 is approved and committed; no issue ledger transition
has been made.

### Wave 5 Task 22 reconciliation review approval checkpoint - 2026-07-14

The semantic reconciliation checkpoint remains based on `origin/main`
`6e6406d`; obsolete Task 20/21 commits were not replayed. Review-fix cycles
now cover configured manual-holding retention through the real snapshot path,
non-zero untargeted audit weights, canonical Sparebanken name/ticker/ISIN
parity, and exclusion of unresolved ISIN placeholders from reference identity
maps while pending score output retains the visible marker. Focused tests, 20
repeated atomic recovery runs, compileall and staged diff checks pass. A fresh
independent reviewer approved specification compliance and code quality with
no Critical or Important findings. The cached full suite still records 11
pre-existing/environment/deferred failures; Ruff, package/native/browser and
clean-first-run evidence remain pending. Task 22 is not closed, no issue
ledger transition has been made, and Task 23 remains deferred until the
reconciled checkpoint is integrated and its remaining closure gates pass.

### Wave 5 Task 22 reconciliation local commit checkpoint - 2026-07-14

The independently approved reconciliation was committed locally as
`59d2393dcdaa9b19d436fcb5890ee0da15666196` on
`wave5/task22-reconciliation`, one normal commit ahead of the verified
`origin/main` base `6e6406d58db89ae19398e2abf15d0670e3350560`. The commit contains
only the reviewed Task 22 reconciliation and durable evidence; no Task 20/21
obsolete commit was replayed, and the original Task 22 worktree remains
recoverable. System GitHub authentication inside Codex still fails with
`SEC_E_NO_CREDENTIALS`; branch push, pull request integration and GitHub issue
synchronisation are therefore pending authenticated PowerShell execution.
The fresh full suite recorded 11 baseline/environment-specific failures and no
Task 22-specific failure. Task 22 remains open and Task 23 has not started.

### Wave 5 Task 23 bounded release-candidate checkpoint - 2026-07-15

Task 23 resumed on `wave5/task23-working` from the reconciled Task 22
checkpoint. The bounded table/identity/fixture fixes and the reproducible
`0.1.0rc1` PyInstaller packaging path have fresh independent approval. The
focused and authoritative full test suites, compileall, scoped Ruff and diff
checks passed. A reviewed native onedir build and complete portable ZIP were
extracted outside the repository and the packaged launcher returned HTTP 200.
The canonical batch build remains unverified because the repository virtual
environment is inaccessible under the current Windows ACL/ensurepip state.
Full issue dossiers/evaluator, rendered browser/computer-use, clean-first-run,
remote integration and issue transitions remain pending; Task 23 is
implementation-complete but closure-pending.
