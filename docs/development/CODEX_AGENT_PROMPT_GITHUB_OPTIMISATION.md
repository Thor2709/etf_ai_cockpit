# Codex agent, prompt and GitHub optimisation for ETF AI Cockpit

**Status:** implementation guidance and research record, not current architecture or programme-state authority  
**Date:** 31 August 2026  
**Related issues:** #712, #713 and #714  
**Repository baseline audited:** `main@fffb8e00dd17b214654d19228601d5a623146970`

## 1. Purpose

This document translates the 31 August 2026 Codex/Git/GitHub audit into an operating design for faster and less expensive development of ETF AI Cockpit without weakening financial correctness, point-in-time behaviour, persistence safety, authority boundaries, review or release evidence.

The target is not “use the cheapest model everywhere” or “run as many agents as possible”. The target is to minimise **verified cost per independently accepted unit of product progress**:

```text
verified throughput =
  accepted issue value
  / (agent tokens + human wait + local compute + hosted CI + rework)
```

A faster first edit that causes more review cycles, stale CI heads or broad package reruns is not an optimisation.

## 2. Evidence reviewed

The audit used:

- the installed global Codex excerpt and all twelve configured agent roles from `etf_ai_cockpit_ai_instructions_2026-08-31.zip`;
- repository `AGENTS.md`, `plan.md`, active planning files, delivery policy, validation classifier and validation runner;
- recent ETF AI Cockpit pull requests and workflow logs;
- official OpenAI Codex documentation for AGENTS discovery, subagents, prompting, worktrees, code review and the Codex GitHub Action;
- official OpenAI model documentation for Sol, Terra and Luna;
- official Git documentation for worktrees and cherry-pick;
- official GitHub documentation for Actions concurrency, checkout, caching, reusable workflows and protected branches.

Primary references:

- OpenAI AGENTS guidance: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- OpenAI subagents: https://learn.chatgpt.com/docs/agent-configuration/subagents
- OpenAI prompting: https://learn.chatgpt.com/docs/prompting
- OpenAI Codex worktrees: https://learn.chatgpt.com/docs/environments/git-worktrees
- OpenAI code review: https://learn.chatgpt.com/docs/code-review
- OpenAI Codex GitHub Action: https://learn.chatgpt.com/docs/github-action
- OpenAI model catalogue: https://developers.openai.com/api/docs/models
- Git worktree: https://git-scm.com/docs/git-worktree.html
- Git cherry-pick: https://git-scm.com/docs/git-cherry-pick.html
- GitHub Actions concurrency: https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency
- `actions/checkout`: https://github.com/actions/checkout
- GitHub protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

## 3. Current-state diagnosis

### 3.1 Installed model effort is materially higher than the repository template

The archived installed global excerpt specifies:

```toml
model = "gpt-5.6-sol"
model_reasoning_effort = "ultra"
plan_mode_reasoning_effort = "high"

[agents]
max_concurrent_threads_per_session = 10
default_subagent_model = "gpt-5.6-luna"
default_subagent_reasoning_effort = "high"
```

The repository’s durable template instead specifies a Sol-medium root and a two-child ceiling. The twelve installed roles also use high or xhigh effort for most implementation, diagnosis, review, release and performance work.

This creates four costs:

1. ordinary orchestration pays exceptional reasoning effort before task complexity is known;
2. routine child work pays high effort even when the output is a bounded map, command result or documentation update;
3. a large hard concurrency limit encourages unnecessary fan-out and repeated context loading;
4. each child can independently rediscover requirements and read the same large programme files.

The correct response is an evaluated routing matrix, not a universal downgrade. OpenAI describes Sol as the flagship for complex work, Terra as the intelligence/cost balance and Luna as the cost-sensitive high-volume model. The default reasoning level documented for the GPT-5.6 family is medium. Higher effort should therefore be selected because a representative evaluation shows a material gain, not because the setting exists.

### 3.2 Context architecture is larger than the task architecture

Codex assembles applicable AGENTS files from global scope and from repository root down to the current working directory. Closer files override broader guidance, and the default combined project-document allowance is 32 KiB. That makes concise layered instructions more effective than repeating the same programme rules in a global file, root file, active plan, prompt and agent role.

The present repository also contains very large historical plans, canonical registries and generated programme views. Those files are valuable authorities or evidence, but they should not be normal conversational context. A task should query the selected issue, dependency neighbourhood and affected boundaries instead of loading the complete backlog.

### 3.3 Parallelism is being treated as a capacity question rather than an ownership question

OpenAI’s subagent guidance recommends parallelism particularly for independent read-heavy work and cautions that subagents consume more tokens. Multiple writers create an additional constraint: they can be correct individually and still produce a conflicting combined design.

The useful question is not “How many agents can run?” It is:

```text
How many assignments have:
- independent information needs;
- non-overlapping write ownership;
- isolated runtime state;
- a deterministic integration order;
- enough saved critical-path time to exceed added coordination cost?
```

For this repository the normal answer is one writer, two or three read-only specialists and, only for proven-disjoint ordinary work, a second writer in a separate worktree.

### 3.4 Test selection does not yet express production impact precisely enough

The current changed-validation path can select directly edited test files, while the classifier has broad path and token rules. This is safe in the direction of over-testing, but it is expensive and poorly attributable:

- editing a large test module can select hundreds of tests;
- changing production code without editing its tests may not express the complete affected-node set;
- lexical finance/portfolio/pricing tokens can escalate changes without a contract-level reason;
- one long preflight step can hide which cheap check failed and can be cancelled before producing useful partial evidence.

Issue #714 therefore requires production-module and symbol impact, explicit dynamic-boundary mappings, node-level pytest selection and transparent escalation reasons.

### 3.5 One issue currently pays too much fixed administration

The repository has improved E/O/H/C classification, exact-head evidence, cancellation, generation and lifecycle convergence. The remaining inefficiency is the unit of certification. A single issue may pay for:

- environment setup;
- broad changed tests;
- paired reviews;
- Linux and Windows package gates;
- terminal summary;
- product PR administration;
- lifecycle/control work.

If three to five compatible ordinary issues have atomic commits and one frozen combined head, they can share the fixed certification cost while preserving independent reviewability and rollback. The unit becomes a **certification train**, not an undifferentiated mega-PR.

## 4. Recommended model and reasoning routing

This matrix is a starting candidate for the evaluation in #712. It must be accepted only after representative repository tasks demonstrate no material quality regression.

| Role/task | Candidate model | Default effort | Escalate when |
|---|---|---:|---|
| Root orchestration and integration | Sol | medium | high for cross-cutting architecture, ambiguous H-tier failures or a rejected first plan |
| Plan-only consequential architecture | Sol | medium | high for migration/authority/security/PIT decisions |
| Fast repository map and dependency/test ownership | Terra | medium | high only when static/dynamic boundaries remain ambiguous |
| Ordinary bounded implementation | Terra | medium | Sol medium/high for canonical finance, PIT, persistence, security or authority code |
| Routine documentation/generated-file maintenance | Luna | medium | Terra medium when meaning depends on several subsystems |
| Primary-source documentation lookup | Terra | medium | high only for contradictory/version-specific sources |
| Tests-only ordinary work | Terra | medium | high for concurrency, persistence, adversarial finance/PIT or property-based design |
| Whole-diff ordinary review | Terra | high | Sol high for high-consequence cross-subsystem review |
| Specialist financial/PIT/security/authority review | Sol | high | xhigh only after a measured hard case, not by default |
| Release-summary and exact-identity verification | Luna | medium | Terra high for inconsistent or failed evidence |
| Benchmark execution/reporting | Luna | medium | Terra high for difficult measurement design |
| Performance implementation | Terra | high | Sol high for algorithmic/concurrency changes |
| Known mechanical maintenance | Luna | low or medium | medium when any interpretation is required |

Do not keep `ultra`/`max` as a standing root setting. Use it as an explicit exception for a task whose expected cost of a missed defect materially exceeds the added latency/tokens and whose representative evaluation demonstrates benefit.

### Recommended candidate core configuration

```toml
model = "gpt-5.6-sol"
model_reasoning_effort = "medium"
plan_mode_reasoning_effort = "high"
model_verbosity = "low"
approval_policy = "never"
sandbox_mode = "workspace-write"

[agents]
enabled = true
max_concurrent_threads_per_session = 4
max_depth = 1
default_subagent_model = "gpt-5.6-terra"
default_subagent_reasoning_effort = "medium"
interrupt_message = true
```

The value `4` is a hard safety ceiling, not a desired allocation. Normal active shape:

```text
root/orchestrator
├─ scout or impact analyst          read-only
├─ implementation writer           one bounded worktree
└─ reviewer/diagnostician           read-only, only when useful
```

A second writer is admitted only by #713 overlap and runtime-isolation checks.

## 5. Agent design

### 5.1 An agent is an ownership contract, not a personality

Each agent definition should answer:

1. What one outcome does this role own?
2. What may it read?
3. What may it write?
4. What must it never change?
5. What exact evidence must it return?
6. When must it stop rather than broaden?
7. Which model/effort is justified by its task distribution?

A useful child response is compact:

```text
STATUS: complete | blocked | defect-found
OWNERSHIP: paths/symbols actually inspected or changed
FINDINGS: exact evidence, ordered by consequence
EVIDENCE: commands/tests and result identities
UNCERTAINTY: bounded unresolved questions
NEXT: one recommended action
```

Raw logs, repeated status messages and repository-wide summaries should remain outside the root context unless a failure requires them.

### 5.2 Recommended roles

Keep fewer roles with distinct boundaries. A practical set:

- `scout`: targeted symbol/call/test/ownership map; no diagnosis or edits;
- `diagnostician`: reproduce one unknown failure and return the smallest evidenced cause; read-only;
- `implementer`: one approved bounded change and ordinary focused tests;
- `test_engineer`: tests/fixtures only when test design is independently substantial;
- `reviewer`: stable whole-diff correctness review;
- `risk_reviewer`: one named financial/PIT/security/persistence/authority risk;
- `release_verifier`: exact-head/terminal evidence, no repair;
- `documentation_maintainer`: approved documentation/generated-state update;
- `benchmark_guard`: objective baseline/repeat measurement, no production edit;
- `performance_refactorer`: one measured optimisation.

Avoid simultaneously dispatching scout, planner, diagnostician and three reviewers to answer the same question. The root should choose the narrowest role whose expected result changes the next decision.

### 5.3 Delegation decision rule

Delegate only when:

```text
expected critical-path saving
+ expected context-quality gain
>
child setup/context tokens
+ coordination/review cost
+ stale-result risk
```

Good parallel assignments:

- map production call path while another child maps tests;
- inspect current issue dependencies while a documentation researcher checks a version-specific API;
- whole-diff review and specialist risk review of the same frozen head;
- prepare the next issue read-only while immutable CI runs.

Poor parallel assignments:

- two children redesigning the same interface;
- multiple writers touching `services.py`, shared fixtures or canonical programme state;
- several reviewers before the head is frozen;
- children loading the whole backlog independently;
- a high-effort child for a deterministic command or file lookup.

## 6. Instruction architecture

### 6.1 Root AGENTS content

Root instructions should contain only durable repository-wide invariants:

- product authority and `execution_allowed=false`;
- local-first/no silent external writes;
- canonical financial/PIT/missingness rules;
- Git/GitHub authority;
- one-writer/overlap rule;
- validation-tier and evidence principles;
- concise reporting and stop-loop policy;
- pointers to the current active-goal/query commands.

Do not put issue-specific history, current SHA/run IDs or long delivery chronology in root AGENTS.

### 6.2 Nested AGENTS content

Use narrow nested files for boundaries such as:

```text
.github/AGENTS.md
issues/AGENTS.md
scripts/AGENTS.md
src/etf_cockpit/data/AGENTS.md
src/etf_cockpit/backtest/AGENTS.md
src/etf_cockpit/portfolio/AGENTS.md
tests/AGENTS.md
docs/AGENTS.md
```

Examples:

- `.github`: exact-SHA, permission, untrusted cache, terminal-summary and no authority-broadening rules;
- `issues`: canonical-source-first, generated views never hand-edited, GitHub projection rules;
- `data`: bitemporal identity, explicit missingness, no silent fill, immutable provenance;
- `portfolio`: one canonical calculation path, target is not an order, deterministic gates;
- `tests`: isolated roots/ports/databases, no assertion weakening, safe/unsafe parallel grouping;
- `docs`: source versus generated outputs, claims require evidence.

### 6.3 Context budget

The root should provide commands that return compact task packets:

```text
python scripts/query_programme.py issue ISSUE-XXXX --with-dependencies
python scripts/query_programme.py next --release fundamental
python scripts/query_ownership.py --paths ...
python scripts/select_impacted_tests.py --base <sha> --head <sha>
```

The child receives the result, not the full registry. Large files remain available for targeted reads when a claim cannot be resolved from the packet.

## 7. Prompt design

OpenAI’s prompting guidance emphasises the desired result, relevant context, output shape and boundaries. For this repository, every substantive task packet should use the following stable structure.

### 7.1 Compact task packet

```markdown
# Outcome
One observable result, written as a completed state.

# Identity
- Issue/train:
- Exact base SHA:
- Working branch/worktree:
- Validation tier expected:

# Read first
Only:
1. applicable AGENTS chain;
2. selected issue/acceptance criteria;
3. relevant source and focused tests;
4. named SDD/ADR if the contract changes.

# Ownership
- May write:
- May read:
- Must not change:
- Other active lanes:

# Hard invariants
Only the task-specific subset not already stated by AGENTS.

# Done when
Concrete product behaviour, evidence, documentation and exact output.

# Verification
Focused commands first; broader evidence selected by the classifier/impact tool.

# Stop conditions
Ambiguous requirement, ownership overlap, unexpected architecture, two non-improving attempts, or protected authority outside scope.

# Return
Status, complete diff summary, tests/evidence, uncertainty and next action.
```

### 7.2 Prompt anti-patterns

Avoid:

- “Read everything and finish the app.”
- repeating all repository rules in every prompt;
- prescribing a long implementation algorithm before the agent inspects current code;
- combining diagnosis, architecture, implementation, review, GitHub mutation and release into one child assignment;
- asking for “maximum reasoning” on every deterministic task;
- acceptance criteria expressed only as “all tests pass”;
- asking the agent to continue indefinitely across unrelated issues.

### 7.3 Plan writing

A useful plan resolves decisions before coding:

- current observed behaviour and reproduced gap;
- exact owned interfaces/files;
- compatibility and migration shape;
- failure/rollback path;
- tests and acceptance evidence;
- integration order and worktree boundaries;
- what will not be changed.

Plans should be short enough to remain live. Historical logs belong in archived evidence, not appended endlessly to the active plan.

## 8. GitHub operating model

### 8.1 Branch and PR unit

Use one PR per compatible certification train, not one unreviewable mega-PR and not necessarily one PR per tiny issue.

Each issue remains:

- one atomic commit;
- independently attributable;
- independently revertible;
- linked to its issue and acceptance evidence;
- focused-tested before integration.

The train receives:

- train-level impact analysis;
- one frozen exact head;
- parallel whole-diff/specialist reviews;
- one required hosted certification;
- one compact canonical/lifecycle transaction where permitted.

### 8.2 Push discipline

Do not repeatedly push moving heads that trigger expensive hosted gates. Before the first certification push:

1. integrate atomic commits locally;
2. run cheap admission checks;
3. compute classifier/impact report and expected duration;
4. ensure reviewable documentation/control evidence is complete;
5. freeze the head;
6. launch required reviews and hosted CI against that exact head.

A correction invalidates stale review/CI evidence. Consolidate all valid findings into one bounded correction pass where possible.

### 8.3 GitHub Actions

Recommended controls:

```yaml
concurrency:
  group: validation-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
```

Checkout exact identities rather than all branches and tags:

```yaml
- uses: actions/checkout@<pinned-sha>
  with:
    ref: ${{ github.event.pull_request.head.sha }}
    fetch-depth: 1
    persist-credentials: false
```

Fetch the PR base separately. If cadence genuinely requires first-parent main history, fetch only the required main ref/history; do not use `fetch-depth: 0` as a reflex, because `actions/checkout` documents that it fetches all history for all branches and tags.

Split preflight into observable jobs:

1. identity/classifier;
2. generated-state/registry/diff hygiene;
3. static/architecture/UI-contract checks;
4. source/offline smoke;
5. impacted tests;
6. only then required package/platform gates;
7. terminal `validation-summary`.

### 8.4 Cache and artefact policy

- Cache dependencies and rebuildable intermediates by OS, Python and lockfile hash.
- Treat PR-restored caches as untrusted input.
- Validate cache contents or regenerate/fall back.
- Use artefacts for reviewable evidence and caches only for speed.
- Do not reuse a package gate because a cache exists; reuse only validated evidence whose source/dependency/product/policy/environment/artefact identities match.
- Never use mutable `latest` paths as final exact-head authority.

### 8.5 Repository protection

At the audit baseline, `main` was not protected. Recommended ruleset:

- pull request required;
- force push and deletion disabled;
- required unique terminal `validation-summary`;
- required conversation resolution;
- linear history if compatible with the selected merge policy;
- optional auto-merge only after required exact-head checks;
- merge queue when more than one train is routinely ready.

A sole maintainer may choose not to require a separate human approval, but the independent code/risk review must still be represented by required evidence.

## 9. Evaluation and adoption

Do not switch the complete operating system on assertion alone.

### 9.1 Frozen evaluation set

Select representative past tasks:

1. ordinary UI/application binding;
2. ordinary data adapter;
3. financial/PIT calculation;
4. persistence/concurrency defect;
5. documentation/generated-state update;
6. whole-diff review;
7. CI/release verification;
8. measured performance repair.

Run candidate agent/model/prompt profiles on the same base and acceptance packet.

### 9.2 Metrics

Record:

- accepted first-pass rate;
- blocking review findings;
- correction cycles;
- escaped seeded defects;
- wall-clock implementation time;
- root and child input/output tokens;
- child count and context loaded;
- local test minutes;
- hosted Linux/Windows minutes;
- PR/commit count;
- stale/cancelled CI runs;
- merge conflict/rebase time;
- time from issue selection to integrated evidence.

### 9.3 Adoption gates

Recommended staged rollout:

1. shadow read-only routing/evaluation;
2. ordinary E/O documentation or UI tasks;
3. one two-issue disjoint worktree pilot;
4. one three-to-five-issue ordinary certification train;
5. one tightly related H-tier two-issue train;
6. broader use only after no material quality regression.

Rollback is immediate: restore the previous config/agent files, stop train admission and return to one issue/one writer/one frozen head.

## 10. Priority implementation order

1. #712: compact instructions, prompt contract, model/effort evaluation and agent-role rewrite.
2. #714: production-impact manifest, node-level tests, exact-SHA local/hosted admission and evidence identities.
3. #713: worktree lane manifest, runtime isolation, deterministic cherry-pick integration and certification trains.
4. Add branch protection/ruleset once `validation-summary` is stable and unique.
5. Pilot the Sparebank integration issues #716–#720 as a possible train only after the throughput controls prove ownership and test isolation.

## 11. Non-negotiable invariants

The optimisation is invalid if it reduces any of the following:

- financial/PIT correctness;
- source/provenance/identity validation;
- explicit missing/stale/conflicted states;
- persistence and concurrency safety;
- independent risk review for protected changes;
- authoritative Linux/Windows package gates when required;
- exact-head evidence;
- canonical programme generation and status authority;
- `execution_allowed=false`;
- absence of broker/provider/release/deployment writes without explicit authority.
