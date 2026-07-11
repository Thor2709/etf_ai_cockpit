# ETF AI Cockpit Programme Index

> **Execution mode:** Subagent-Driven is mandatory. The project has no usable Git repository, so no branch, worktree, commit, push, pull request or Git initialisation is permitted. Checkpoints are durable files rather than commits.

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

The repository-recorded 262-pass run, package smoke and Chrome evidence remain historical broad evidence. They are not closure evidence for any new implementation task. The closure evaluator currently records four ready items (`ISSUE-0035`, `ISSUE-0069`, `UPDATEV2-0022`, `UPDATEV2-0028`) and 37 open records. This programme adds DATA-05 as a distinct record without rewriting the historic 41-record baseline.

## Programme-wide constraints copied into every plan

1. No scope drift: implement only authorised outcomes and DATA-05 coverage; do not add adjacent capabilities.
2. No authority inflation: evidence, analysis, experimental models, research states, portfolio-review states and user decisions remain distinct; `execution_allowed` is always `false`.
3. Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and responsive Flet shell.
4. Extend through narrow migrations and compatibility adapters. Do not conduct unrelated repository-wide refactoring.
5. Never initialise Git, rewrite history, delete user data, use credentials, purchase services, modify a remote repository, push, or open a pull request.
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
| 0 | [foundation, operations and boundary plan](2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md) | `REL-01`, `REL-02`, `REL-03`, `REL-04`, `FUTURE-01`, `FUTURE-03` | `core/atomic_io.py`, `core/session_log.py`, `core/closure.py`, `core/migrations.py`, scripts and release paths | Baseline only | Versioned `VerificationRun`, `ClosureEvidenceRecord`, recovery transaction contract, static execution/rejection report |
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
5. The lack of Git was not a blocker during planning. All implementation tasks use `RUN_STATE.json`, this index, the progress ledger and `.ai_worklog` as checkpoints; after independently approved Wave 0 Task 2, the user has separately authorised only the local baseline Git setup and optional private GitHub push, with no Task 3 implementation in that handoff.

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
- No blocking contradiction remains after applying the approved precedence rules. Wave 0, Tasks 1 and 2 are independently reviewed complete. Wave 0, Task 3 is the next incomplete implementation task, but it is explicitly deferred while the authorised Git baseline is established.
