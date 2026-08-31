## 2026-08-31 Codex throughput and Sparebank integration addendum

> **Informational overlay.** This section records newly accepted GitHub work
> packages and delivery guidance. It does not replace the SDD, canonical issue
> registry, programme-control state, generated roadmap or active batch plan.
> The new issues remain open overlays until implemented and reconciled through
> the existing canonical workflow.

### Codex development-throughput programme

The next throughput step is not to weaken E/O/H/C or package gates. It is to
reduce unnecessary reasoning, context duplication, overlapping writers,
repeated environment starts, broad unattributable tests and one-issue-per-gate
administration.

| Issue | Work package | Required result |
|---|---|---|
| #712 | Codex model, reasoning, agent and instruction routing | measured Sol/Terra/Luna routing; concise nested AGENTS; compact prompts; no standing Ultra/Max default |
| #713 | safe parallel worktrees and certification trains | one root integration lane, at most two proven-disjoint ordinary writers, atomic issue commits and deterministic integration |
| #714 | precise impact/CI/evidence pipeline | production-symbol-to-pytest-node selection, exact-SHA admission, cheap failures before package gates and validated evidence reuse |

Durable operating direction:

1. Use Sol medium as the candidate ordinary orchestrator and plan mode high.
   Select high/xhigh/max only when a representative task demonstrates material
   benefit.
2. Use Terra for ordinary mapping, implementation and review where evaluation
   proves sufficient; use Luna for clear repeatable high-volume work.
3. Treat the configured agent count as a ceiling. Normal allocation is one
   writer plus two or three independent read-only specialists.
4. Keep root instructions short and durable. Put boundary-specific rules in
   nested `AGENTS.md` files and query compact issue/ownership/impact packets
   instead of loading the entire registry or historical programme.
5. Every task packet states outcome, exact base, owned boundary, invariants,
   acceptance evidence and stop conditions. Do not duplicate all repository
   rules in every prompt.
6. A second writer starts only after path/symbol/test/runtime overlap admission.
   H-tier finance, PIT, persistence, concurrency, security, authority, workflow,
   migration and release work normally retain one writer.
7. Each issue remains one atomic, independently revertible commit. Compatible
   issues may share one certification train and frozen PR head.
8. Run focused evidence per issue, train-level impacted evidence after
   integration and the complete required hosted gate once on the reviewed
   exact head.
9. Preserve one root-owned Git/GitHub/canonical-state lane, exact-head reviews,
   Linux/Windows authority when required, byte-clean generation and zero-action
   readback.

Detailed guidance:

- [`docs/development/CODEX_AGENT_PROMPT_GITHUB_OPTIMISATION.md`](docs/development/CODEX_AGENT_PROMPT_GITHUB_OPTIMISATION.md)
- [`docs/development/CODEX_PARALLEL_WORKTREE_PLAYBOOK.md`](docs/development/CODEX_PARALLEL_WORKTREE_PLAYBOOK.md)
- [`docs/development/templates/CODEX_TASK_PACKET.md`](docs/development/templates/CODEX_TASK_PACKET.md)
- [`docs/development/templates/codex-worktree-lane.v1.yaml`](docs/development/templates/codex-worktree-lane.v1.yaml)
- [`docs/codex-config/config-throughput-candidate.toml`](docs/codex-config/config-throughput-candidate.toml)

### Sparebank Stochastic Intelligence Engine integration

The friend’s not-yet-built application remains an independent specialist model
provider. ETF AI Cockpit remains the generic local-first research, portfolio,
risk, replay, paper and authority environment. Integration uses immutable,
versioned model-result artefacts; neither codebase imports the other’s
internals or reaches into the other’s database.

Responsibility boundary:

- **Friend engine:** official Norwegian-bank evidence needed for its science,
  bank-state reconstruction, equity-certificate/EKB mechanics,
  hierarchical/Bayesian inference, bank-specific macro/credit modelling,
  stochastic simulation, specialist valuation, scientific calibration,
  ranking and model target/preference.
- **Cockpit:** canonical identity/PIT validation, generic deterministic
  bank/stock/ETF evidence, portfolio truth, optimiser/reconciliation,
  deterministic gates, whole-system replay, paper ledger, UI/audit and later
  separately certified broker integration.
- **Initial milestone:** immutable local file contract and paper-only workflow.
  `execution_allowed=false` throughout.

| Issue | Cockpit integration work package | Depends/reuses |
|---|---|---|
| #715 | programme epic, architecture boundary and first paper milestone | all child issues |
| #716 | freeze `sparebank-model-result.v1`, implement `SparebankModelAdapter` and immutable run store | #213, #216 |
| #717 | canonical PIT identity mapping and idempotent `MODEL_UPDATE_AVAILABLE` event | #716, #213, #217 |
| #718 | translate model target/validity into optimiser, reconciliation and fail-closed proposal gates | #716–#717, #253, #268, #270 |
| #719 | provenance, independent-evidence comparison and operator audit UI | #716–#718 |
| #720 | deterministic whole-chain paper, restart and historical replay certification | #716–#719, #265, #269 |

The generic Fundamental Analysis release remains valid and separate. Issues
#699–#705 own transparent deterministic Norwegian-bank filing, ratios,
capital/funding/credit/distribution, valuation and equity-certificate context.
The friend engine owns specialist hierarchical/stochastic/EKB science. Both
sources remain separately labelled; disagreement is preserved and inspectable,
not silently reconciled by an LLM.

Later milestones must reuse rather than duplicate:

- #267 authoritative real portfolio/account ledger;
- #271 broker read-only reconciliation;
- #272 independent pre-trade controls;
- #273 separately certified disabled live-canary lane.

Those issues are not blockers for the first mock/local paper proof and cannot
be promoted by successful Sparebank import or replay.

The friend’s project should progress independently through: domain/contract
freeze; official evidence/provenance; deterministic bank state and EKB;
transparent baseline valuation/ranking; hierarchical/Bayesian macro-credit
model; stochastic distributions; model target/limits; immutable historical
result artefacts.

First joint acceptance requires one checksummed three-bank artefact, exact
Cockpit validation/storage, PIT identity mapping, deterministic target versus
frozen-paper-portfolio reconciliation, fail-closed gates, one manual paper
proposal/fill path, restart idempotency, no future information in replay and a
visible causal change when one model/input hash changes.

Full handoff:

- [`docs/integrations/SPAREBANK_EXTERNAL_MODEL_BRIDGE.md`](docs/integrations/SPAREBANK_EXTERNAL_MODEL_BRIDGE.md)

### Shared safety and quality constraints

Neither throughput work nor the Sparebank bridge may:

- weaken canonical financial/PIT, identity, provenance, missingness,
  persistence, concurrency, security or authority safeguards;
- skip a required H/C Linux or Windows package gate;
- let multiple writers edit overlapping production, test, generated or
  canonical-state boundaries;
- treat a cache, model target, LLM explanation or UI action as authority;
- add broker/provider/release/deployment writes or live execution;
- change `execution_allowed=false` without a separate explicit future
  programme and certification.
