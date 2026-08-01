# ETF AI Cockpit Initial Integration Programme

The detailed active fast-path objective and current handoff are maintained in
`plans/ACTIVE_CODEX_GOAL.md`; read it before continuing this programme.

## Current operational amendment

B00–B13 are programme groupings, not permission for large multi-issue PRs.
Normal product delivery is one issue/one product PR; a multi-issue product PR
requires inseparable contracts and explicit root justification. Independent
dependency edges may be batched. Lifecycle transitions use compact automatic
convergence; do not create a manual `in_progress` / `implemented_initially` /
`integrated` PR chain. Product work may overlap immutable CI only through a
disjoint worktree. Current named-agent routing supersedes old Sol/Terra/Luna
routing. The proven four-worker pytest run is report-only and is not a new
pilot to start from scratch. The P0 throughput remediation is complete and
frozen; see `docs/product-completion/DELIVERY_WORKFLOW.md` for detail.

## Summary

Implement the accepted completion programme from fresh `origin/main` in small,
dependency-valid pull requests. Start with the bounded throughput remediation,
then resume the exact interrupted programme sequence and deliver the remaining
11 phases incrementally without constructing speculative infrastructure.

The throughput programme began after PR #576 merged and converged through PR
#577 at `4eaed9c8d15212d2c9dc69bad0301eecc03e0c74`. The primary checkout is
dirty and historically behind `origin/main`; it remains untouched. All
implementation occurs in fresh isolated worktrees.

## Interfaces and Programme Semantics

- Extend the issue registry with:
  - `blocking_dependencies`: completed work required before implementation.
  - `required_inputs`: existing policy or evidence that must be considered but does not block readiness.
  - `activation_dependencies`: prerequisites for enabling a capability, distinct from implementing disabled scaffolding.
  - `downstream_issues`: generated reverse links.
  - `related_issues`: non-sequencing context.
- Make readiness depend on unresolved `blocking_dependencies`; a hard-coded `ready` status must never bypass blockers.
- For `ISSUE-0070`, move `ISSUE-0008`, `ISSUE-0032`, `ISSUE-0060` and `ISSUE-0066` to `required_inputs`. Make their remaining scope-dependent work downstream of `ISSUE-0070`.
- Add `integrated`, `hardening_required` and `rejected` to the programme status model. Keep `implemented_initially` for incomplete integration and reserve `closed` for fully evidenced acceptance.
- Introduce a stable validation-report schema under `artifacts/validation/latest/`, recording checks, commands, exit codes, timings, failures, unavailable optional components, environment, Git state and log paths.
- Extend the existing workflow event model with the required timestamps, command/input deduplication key, cancellation state, progress, outputs and error fingerprint. Bootstrap storage uses the existing append-only session trace; later job-DAG work migrates records compatibly to SQLite.
- Preserve `execution_allowed=false`. `ISSUE-0133` may expose disabled sandbox contracts, but final certification remains an activation dependency and no real-money order path is enabled.

## P0 development-throughput remediation and durable fast path

### Objective

Reduce median and p95 development lead time without reducing application
quality, financial correctness, point-in-time integrity, immutable replay,
concurrency safety, security, UI acceptance, packaging, Linux/Windows coverage
or `execution_allowed=false`.

This remediation is a bounded prerequisite. It finishes the frozen checkpoint
first, implements the immediate P0 delivery fixes, records measured evidence,
and then resumes the dependency-valid programme. It must not become a
permanent planning detour.

### Entry checkpoint

1. Reverify and exact-head merge PR #576 only when it remains open, mergeable,
   unchanged at `bdf759761e9e8aee33ee57197b888a9af1fb2e1d`, with the supplied
   Linux/Windows/status/supply-chain checks green and no reviews/comments.
2. Perform deterministic post-merge convergence from fresh `origin/main` and
   require a zero-action GitHub readback.
3. Preserve PR #560, PR #562, issue #241, the dirty primary checkout and
   unrelated worktrees.
4. Keep `ISSUE-0127` planned, `ISSUE-0127 → ISSUE-0084` complete,
   `ISSUE-0127 → ISSUE-0072` unresolved, and `execution_allowed=false` until
   separately evidenced changes occur.

PR #576 and its deterministic convergence are complete through PR #577. The
remaining steps below begin from that verified checkpoint.

### Root causes addressed

The immediate wave targets the measured multipliers:

- 14–20 minute full release gates applied too broadly;
- two complete suites and three supply-chain scans per ordinary PR;
- no obsolete-run cancellation;
- retained red/flaky baseline requiring manual fingerprint comparison;
- quiet serial pytest without duration history;
- late UI-acceptance, architecture-boundary, generated-freshness, environment,
  path, port and line-ending failures;
- full serialisation of the one-orchestrator/one-worker workflow;
- exact-SHA programme evidence and manually repeated convergence transactions.

Provider/API batching remains a separate runtime-performance issue; network
waiting is not the main protected-CI bottleneck.

### P0-A — delivery observability and green baseline

#### Work

- Emit slowest-test, JUnit, per-stage timing, environment fingerprint, cache,
  retry and platform evidence for affected and full validation.
- Persist full machine output as untracked local/GitHub Actions artefacts;
  commit only compact summaries and policies.
- Reproduce and eliminate all retained baseline failures and documented flakes
  without weakening assertions.
- Make clocks, ports, temporary roots, line-ending hashes, generated artefacts
  and optional dependencies deterministic.
- Create one authoritative local/worker/CI environment verification command.

#### Acceptance

- `main` passes the complete Linux and Windows suites with zero accepted
  baseline failures in at least two successive exact-tree protected runs, or
  the repository's stronger existing release requirement.
- `--durations=100`, `--durations-min=0.25` and JUnit output exist for full
  gates.
- The top 100 tests include setup/call/teardown, platform and historical
  p50/p95 where sufficient samples exist.
- Test-created runtime files do not leave a dirty worktree.
- Missing Flet, exchange-calendars, Hypothesis, MyPy, parser or release tooling
  is detected before tests begin.

### P0-B — validation classifier and CI orchestration

#### Validation tiers

| Tier | Scope | Required validation |
|---|---|---|
| `E` | Evidence, status, dependency-edge, generated docs only | exact guard, generators/check mode, registry/status, diff hygiene, source/supply policy; no full package matrix unless protected tooling changed |
| `O` | Ordinary product work | focused and affected tests, UI/architecture/static checks, source smoke; central full gate after two or three completed ordinary issues |
| `H` | Persistence, migrations, concurrency, canonical finance, security/credentials, package/CI/release tooling, programme-control machinery, broker/order authority | immediate full Linux and Windows package gate plus every preflight |
| `C` | B13/final certification | complete cross-platform certification, package/parity/smoke, performance, security/privacy/legal, SBOM/signature and final evidence |

#### Work

- Add one always-running classifier/preflight job and one terminal
  `validation-summary` check.
- Classify changed paths and semantic risk deterministically; emit a JSON
  report and explanation.
- Add workflow-level concurrency cancellation for obsolete PR heads.
- Run equivalent source supply-chain scanning once per exact tree; retain only
  genuinely platform-specific package checks in platform jobs.
- Check new routes/buttons against UI acceptance metadata before the expensive
  gate.
- Check presentation imports against the application-facade boundary before
  the expensive gate.
- Reuse exact-head passing evidence when files and relevant policy are
  unchanged; do not rerun unchanged passing tests.

#### Acceptance

- An evidence-only fixture PR proves Linux/Windows package jobs are correctly
  skipped while the final summary passes.
- An ordinary fixture PR proves focused/affected/UI/static/smoke run and full
  matrix is selected only by cadence/policy.
- High-risk persistence/control fixtures prove both platform package gates are
  mandatory.
- Pushing a newer PR head cancels the obsolete workflow run.
- Exactly one canonical source supply-chain scan runs per tree.
- The terminal summary fails when any tier-required job fails and succeeds
  when optional jobs are correctly skipped.
- No branch-protection check is left permanently pending due to workflow path
  filtering.

### P0-C — 1+1 utilisation

The orchestrator may own one immutable release lane while the single worker
prepares one next dependency-ready, non-overlapping product lane in another
worktree.

The worker may not touch:

- the frozen PR's files;
- canonical registry/status/generated/control files;
- GitHub state;
- merges or shared release evidence.

The worker checkpoint must be reviewed and transplanted onto fresh `main`
after the earlier merge. There remains only one active implementation writer
and one integrator.

### P1 follow-ups

Create but do not let these block the immediate current continuation unless
their acceptance is required by a discovered P0 defect:

- atomic programme generation and automated post-merge convergence;
- reproducible environment and safe pytest parallelism after profiling;
- yfinance/provider batching, caching, resume and latency metrics.

### Metrics and provisional targets

Measure before and after. Exclude external GitHub runner queue time when
assessing job execution, but report queue time separately.

- known baseline failures: target `0`;
- architecture/UI-contract failures first discovered in full CI: target `0`;
- environment mismatch failures: target `0`;
- generated-freshness omissions: target `0`;
- evidence-only validation p50 execution: provisional target `≤3 min`, p95
  `≤6 min`;
- ordinary actionable preflight p50: provisional target `≤5 min`, p95
  `≤10 min`;
- obsolete CI minutes after a newer head: target near `0` after cancellation
  latency;
- product-code PR share: increase from measured baseline;
- PRs per integrated product issue: target `≤3` where the guard model permits;
- worker idle time during safe CI overlap: materially reduced;
- full-gate p50/p95: measured and improved only after profiling, without losing
  coverage.

Refine provisional time targets after ten representative runs; do not claim
success from one favourable run.

### Verified atomic fast-path checkpoint

ISSUE-0179 remains integrated through PR #613. PR #614 is retained as the
historical ISSUE-0180 environment-product integration. Formal ISSUE-0180
programme integration completed through PR #630 as
`45564c306643f8fbe97fe460979a04e25e6f41b9` after the bounded GitHub
authority repairs through PR #629.

PR #630's status guard passed in run `30656428462`. Tier-E run `30656428457`
correctly required the full package gate because evidence reuse was not
authorised; Linux and Windows each ran 2,452 tests and terminal validation
passed. Ordered writer run `30658275241` appended the reviewed proposal and
receipt, projected ISSUE-0180 as `integrated`, preserved unrelated issue
content and completed zero-action readback. Convergence run `30658275236`
then succeeded by deferring to the ordered writer.

The representative fixtures cover E reuse/package skipping, batched
independent edges, ordinary O selection, mandatory two-platform H selection,
consecutive fresh main heads and live staged status completion. All five
audited E transactions selected package skipping correctly. In the frozen
11-run compact-control sample, execution p50/p95 was `0.4000/1.2500 min` and
separately measured queue p50/p95 was `0.0500/1.8833 min`; cache reuse was
`10/46` (`21.74%`). No polling reduction is claimed. Detailed evidence is in
`plans/ATOMIC_FAST_PATH_METRICS.md`.

The GitHub authority infrastructure is now frozen to existing
repository-authored issue creation and lifecycle/status projection. Any
expansion requires explicit user approval and a demonstrated safety need.
Normal dependency-valid product work resumes with ISSUE-0101 under the new
validation policy.

### Required continuation after P0 merge

1. Review and release only `ISSUE-0127 → ISSUE-0072 = partial_interface` from
   fresh main.
2. Rebuild `ISSUE-0068` from fresh main; do not merge stale PR #562.
3. Leave PR #560 unchanged.
4. Continue all remaining dependency-valid `PLAN_step2.md` work under the new
   validation policy.

### Rollback

The CI change must be reversible through one workflow/config revert. If tier
classification is uncertain, fail upward to `H`, never downward. If the
terminal summary or branch protection behaves unexpectedly, restore the
previous full-gate workflow while preserving telemetry and green-baseline
fixes, then correct the classifier in a separate guarded change.

## Implementation Sequence

1. **Responsiveness bootstrap**
   - Add the minimum `--quick`, `--changed`, `--issue` and `--phase` validator paths, quick source smoke, structured JSON/Markdown reports and non-zero mandatory-failure exits.
   - Instrument yfinance, algorithm and forecast controls from click through completion.
   - Create and persist the workflow record before starting background work; show status immediately; reject duplicate active commands; add cancellation and prompt failure reporting.
   - Meet ≤1 second visible acknowledgement and ≤2 seconds durable workflow creation on representative local tests.
   - Treat this as partial progress on `ISSUE-0012`, `ISSUE-0014`, `ISSUE-0039`, `ISSUE-0040`, `UPDATEV2-0027` and `UPDATEV2-0029`, not automatic closure.

2. **Dependency-semantics correction**
   - Implement the registry fields above, correct `ISSUE-0070`, regenerate all programme artefacts and document the reconciliation decision.
   - Keep valid forward dependencies explicit: pull `ISSUE-0038` ahead of `ISSUE-0072`; deliver shared `ISSUE-0128` cost primitives before ETF liquidity; defer `ISSUE-0079` until its legal/supply-chain inputs exist.
   - Classify `ISSUE-0152` as an activation dependency for live-execution promotion rather than permission to activate it now.
   - Synchronise GitHub metadata only after a reviewed no-op/convergent dry run.

3. **Phase 1 - Governance and platform**
   - Deliver `ISSUE-0070` first, including the versioned authority ADR, capability matrix and UI/audit representation.
   - Add bounded application/domain/provider boundaries and plugin contracts incrementally (`ISSUE-0071`, `ISSUE-0076`).
   - Implement the hybrid stores, point-in-time model, canonical scoring and version registries (`ISSUE-0038`, `ISSUE-0072`–`0075`).
   - Grow bootstrap workflows into the used portions of the resumable DAG and performance budgets (`ISSUE-0077`, `ISSUE-0078`).
   - Integrate the remaining phase-owned decision-support, operational evidence, optional adapter and existing initially implemented records in bounded dependency-valid slices under the one-issue/one-product-PR rule.
   - Leave `ISSUE-0079` open until Phases 9–10 provide its required inputs.

4. **Phases 2–7 - Analytical and transactional capabilities**
   - **Phase 2:** local-first policy/cache, identity/classification, corporate actions/calendars/imports, filing ingestion, macro/reference warehouse, anomaly reconciliation, catalogue and lineage.
   - **Phase 3:** canonical statements; profitability, solvency, cash flow, growth and valuation; peer cohorts; four sector-adapter families.
   - **Phase 4:** ETF economics and structure, complete/partial look-through, nested funds, liquidity/capacity and domicile/distribution/hedging context. Never renormalise unresolved holdings away.
   - **Phase 5:** probabilistic returns/scenarios, factor and covariance risk, benchmarks, optimiser/rebalancing, stress and attribution. Scores never become orders or expected returns directly.
   - **Phase 6:** feature/target registry, experiments/model registry, baselines and challengers, leakage-safe validation, calibration, drift and champion/challenger governance. TimesFM and Toto remain lazy optional challengers.
   - **Phase 7:** event-driven backtesting, point-in-time universes, double-entry ledger, cost models, paper broker, frozen proposals, restart/replay, read-only broker reconciliation, draft previews, independent controls and incidents. Live canary interfaces remain disabled test/sandbox scaffolding.

5. **Phases 8–11 - Product integration and release evidence**
   - **Phase 8:** introduce typed commands, queries and page view models; complete the design system and all required workspaces; migrate existing pages rather than duplicating them. No accepted user-facing capability remains backend-only.
   - **Phase 9:** expand the validator to `--full`, `--offline`, `--packaged` and `--report-only`; add CI, package/E2E/property/fault tests, parser/local-API hardening, SBOM and recovery/privacy controls.
   - **Phase 10:** audit packet v3, deterministic reproduction, user/developer/methodology documentation, legal/licence registry, bias reporting and hardware degradation profiles. Complete `ISSUE-0079` here.
   - **Phase 11:** run the initial whole-app integration gate. Keep `ISSUE-0152` as `integrated` or `hardening_required`; do not close it or activate execution before Prompt 3.

Each slice uses a fresh `implementation/...` branch from the newly merged `origin/main`, contains one architectural purpose, updates source/UI/migrations/tests together, and ends with review, push, PR, merge, post-merge quick validation and canonical/GitHub status convergence.

## Test and Acceptance Plan

- Per slice: regression-first tests where applicable, targeted issue checks, `--changed`, Ruff on changed Python, compileall, diff review and one representative UI workflow.
- Cover success, missing/unavailable data, invalid input, persistence/restart, authority boundaries, cancellation, duplicate clicks and audit/export representation.
- Per phase: affected integration tests, phase validation, source smoke, representative stock/ETF or operational workflow, unavailable-state verification and full suite when shared foundations changed.
- Final gate:
  - `python -m pytest -q`
  - `python -m ruff check src tests scripts`
  - `python -m compileall -q src scripts`
  - `scripts/validate_app.py --full`
  - `scripts/validate_app.py --offline`
  - source and packaged launches, stock/ETF workflows, optional-model unavailable path, backtest, paper proposal/ledger, audit export and validator launcher.
- Record cold/warm timings for acknowledgement, job creation, yfinance, algorithms, scoring, TimesFM, Toto, common queries and source/packaged startup.
- Completion requires every accepted record to be attempted and truthfully classified; no non-blocked record remains merely `planned`. Tests are not weakened, optional failures remain visible, adjusted-price rules remain enforced and no real-money order is submitted.

## Assumptions

- The selected incremental bootstrap supersedes a foundation-first validator or scheduler build.
- Existing initially implemented work is inspected and extended, not rewritten automatically.
- Existing dependencies are preferred; any unavoidable new production dependency requires explicit approval.
- Ordinary repository branches, tests, reviews and pull requests are used; no autonomous controller or replacement workflow framework is added.
- Exhaustive hardening, live-execution promotion and final certification belong to Prompt 3.
