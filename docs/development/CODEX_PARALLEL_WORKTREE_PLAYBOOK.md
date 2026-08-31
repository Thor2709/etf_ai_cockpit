# Codex parallel worktree and certification-train playbook

**Status:** proposed operating playbook for #713
**Date:** 31 August 2026
**Applies after:** #712 routing and #714 impact/admission are available

## 1. Decision

Multiple worktrees are a good option for ETF AI Cockpit **only when they isolate independent work**. They are not a safe way to make one shared change faster by letting many writers edit overlapping code.

Git worktrees provide separate working directories, indexes and HEADs while sharing the repository object database and references. Codex worktree chats use the same underlying mechanism and normally begin from a selected branch or detached commit. Git prevents the same branch from being checked out in two worktrees, which is a useful safeguard but not a complete concurrency system: applications, tests, databases, caches and ports can still collide unless they are separately namespaced.

## 2. Recommended topology

```text
repository object database / origin
│
├─ wt/train-T042-integration       root-owned writer
│   └─ branch codex/train-T042
│
├─ wt/train-T042-ISSUE-0716        writer A
│   └─ branch codex/T042/ISSUE-0716
│
├─ wt/train-T042-ISSUE-0717        writer B, only if disjoint
│   └─ branch codex/T042/ISSUE-0717
│
├─ wt/train-T042-review            read-only frozen-head review
│
└─ wt/next-issue-preparation       read-only only
```

### Root-owned integration worktree

Only this lane may:

- combine issue commits;
- resolve train-level integration decisions;
- write canonical programme state or generated projections;
- push the train branch;
- open/update/merge the pull request;
- perform GitHub lifecycle/status writes.

It must remain clean except for the train being integrated.

### Implementation worktree

Each lane owns one bounded issue and one atomic commit. It may write only paths and symbols declared in its lane manifest. It does not push, merge, edit canonical programme state or mutate GitHub.

### Review worktree

A stable exact train head is checked out read-only. Whole-diff and specialist review inspect this identity. The review result becomes stale as soon as the head changes.

## 3. Lane admission

Create a second writer only if all conditions pass:

1. both issues are dependency-ready at the same exact base;
2. their production path sets are disjoint;
3. their direct and dynamically mapped test/fixture sets are disjoint or safely read-only;
4. neither writes canonical programme/generated state;
5. neither changes a shared schema/API that the other consumes;
6. neither is H-tier finance, PIT, persistence, concurrency, security, authority, workflow, release or migration work;
7. runtime state can be fully isolated;
8. the expected critical-path saving exceeds coordination cost.

Otherwise use one writer sequentially and parallelise read-only preparation.

## 4. Lane manifest

Every worktree receives a versioned machine-readable manifest.

```yaml
schema_version: codex-worktree-lane.v1
train_id: T042
lane_id: T042-ISSUE-0716
issue_ids: [ISSUE-0716]
base_sha: fffb8e00dd17b214654d19228601d5a623146970
branch: codex/T042/ISSUE-0716
mode: writer            # writer | read_only | integration
dependencies: []
expected_tier: O
owned_paths:
  - src/etf_cockpit/models/sparebank_adapter.py
  - tests/test_sparebank_adapter.py
owned_symbols: []
forbidden_paths:
  - issues/
  - docs/product-completion/
  - .github/
  - plans/ACTIVE_CODEX_GOAL.md
shared_read_only_paths:
  - src/etf_cockpit/models/contracts.py
runtime:
  namespace: T042_ISSUE_0716
  temp_root: .lane/T042-ISSUE-0716/tmp
  user_data_root: .lane/T042-ISSUE-0716/user-data
  pytest_base_temp: .lane/T042-ISSUE-0716/pytest
  artifact_root: .lane/T042-ISSUE-0716/artifacts
  log_root: .lane/T042-ISSUE-0716/logs
  port_range: [18600, 18649]
verification:
  focused_nodes:
    - tests/test_sparebank_adapter.py
  required_contracts:
    - execution_allowed_false
handoff:
  commit_sha: null
  evidence_manifest: null
```

The validator rejects:

- missing exact base;
- overlapping writer ownership;
- shared writable runtime roots;
- duplicate branch/worktree identity;
- unbounded path globs;
- writer access to canonical state without integration role;
- an H-tier second writer;
- a stale base not explicitly rebased/reapproved.

## 5. Creation commands

Illustrative manual Git workflow:

```bash
git fetch --no-tags origin main
BASE="$(git rev-parse origin/main)"

git worktree add \
  -b codex/train-T042 \
  ../etf_ai_cockpit_wt_T042_integration \
  "$BASE"

git worktree add \
  -b codex/T042/ISSUE-0716 \
  ../etf_ai_cockpit_wt_T042_0716 \
  "$BASE"

git worktree add \
  -b codex/T042/ISSUE-0717 \
  ../etf_ai_cockpit_wt_T042_0717 \
  "$BASE"
```

Never use one branch in two worktrees. Codex-managed disposable worktrees may be detached; before preserving work, create a uniquely named branch or use Codex handoff. Record the exact starting SHA in the lane manifest.

## 6. Runtime isolation

Git isolation is insufficient. Each lane must isolate all mutable application state.

At minimum:

```text
TMP/TEMP
pytest --basetemp
ETF cockpit project/user-data root
SQLite database and sidecars
DuckDB/Parquet output roots
atomic-write staging directories
logs
validation and benchmark artefacts
ports
HTTP/Flet profile state
test caches
coverage files
Hypothesis database
model/download caches if mutable
```

Recommended environment pattern:

```bash
export ETF_COCKPIT_LANE_ID="T042-ISSUE-0716"
export ETF_COCKPIT_HOME="$PWD/.lane/$ETF_COCKPIT_LANE_ID/user-data"
export TMPDIR="$PWD/.lane/$ETF_COCKPIT_LANE_ID/tmp"
export PYTEST_ADDOPTS="--basetemp=$PWD/.lane/$ETF_COCKPIT_LANE_ID/pytest"
export HYPOTHESIS_STORAGE_DIRECTORY="$PWD/.lane/$ETF_COCKPIT_LANE_ID/hypothesis"
export COVERAGE_FILE="$PWD/.lane/$ETF_COCKPIT_LANE_ID/.coverage"
```

A dependency/wheel download cache may be shared by content hash if treated as untrusted/rebuildable. Do not share a writable application database or `artifacts/.../latest` directory.

For an immutable shared virtual environment:

- install once from a locked dependency hash;
- do not install/upgrade during lane work;
- disable bytecode writes where necessary;
- keep all test/application state outside the environment;
- rebuild on validation failure.

A lane-local environment is safer; an immutable content-addressed train environment is faster. Select through measurement.

## 7. Writer workflow

Each writer:

1. verifies exact base and clean worktree;
2. reads the applicable AGENTS chain, issue packet and owned source/tests only;
3. reproduces the gap;
4. implements the smallest complete issue;
5. runs focused tests in the lane namespace;
6. reviews its own complete diff for ownership violations;
7. creates one atomic commit;
8. writes evidence into the lane manifest;
9. stops.

Example:

```bash
git status --short
git diff --check "$BASE" HEAD --
python -m pytest -q <focused-node-ids>
git add <owned-paths>
git commit -m "Implement ISSUE-0716 Sparebank model adapter"
```

No writer appends chronology after freeze, hand-edits generated programme views or commits unrelated cleanup.

## 8. Integration workflow

The integration root validates lane outputs before applying them:

1. manifest valid;
2. lane base is the approved train base or has an explicit rebase record;
3. commit contains only owned paths;
4. focused evidence exists and matches the commit tree;
5. no undeclared dependency/contract change;
6. commit is atomic.

Integrate in dependency order with origin traceability:

```bash
git cherry-pick -x <lane-commit-sha>
```

`-x` records the source commit. Cherry-pick produces a new SHA; retain both source and integrated SHAs in the train manifest.

Why cherry-pick rather than merge every lane:

- train history remains one ordered sequence of issue commits;
- dependencies are explicit;
- a stale/discarded lane does not leave a branch merge;
- each issue is independently revertible;
- conflicts are resolved in the integration lane only.

Use a merge when preserving a genuinely collaborative branch history is itself important. Do not use uncontrolled octopus merges.

After each cherry-pick:

```bash
python scripts/select_impacted_tests.py \
  --base <previous-integrated-sha> \
  --head HEAD

python -m pytest -q <commit-attributable-node-ids>
```

After all issue commits:

```bash
python scripts/train_admission.py \
  --base "$BASE" \
  --head HEAD \
  --manifest plans/trains/T042.yaml
```

## 9. Conflict handling

A conflict is evidence that the assumed independence was incomplete.

Procedure:

1. abort the cherry-pick unless the resolution is purely mechanical and covered by the lane contract;
2. record overlapping paths/symbols and invalidate the stale lane admission;
3. decide which issue owns the interface;
4. rebase/rebuild the downstream lane on the integrated prerequisite;
5. rerun its focused evidence;
6. integrate the replacement atomic commit.

Commands:

```bash
git cherry-pick --abort
git worktree remove <stale-worktree>   # only after evidence is preserved
git worktree prune
```

Git `rerere` may propose a previously recorded resolution, but the integration root must inspect and test it before staging. Never let an agent silently accept a semantic conflict.

## 10. Certification-train admission

### Ordinary train

Normally 3–5 issues when:

- same release objective/component neighbourhood;
- independent atomic commits;
- no ownership overlap;
- total diff remains reviewable;
- no issue requires an incompatible environment/gate;
- train failure can be attributed quickly.

### High-risk train

Normally 1 issue. Permit 2–3 only when they are inseparable or share one protected contract and the combined validation is more meaningful than separate validation. One writer remains the default.

Do not mix unrelated UI, finance, persistence, CI and authority changes to fill a train.

### Train manifest

```yaml
schema_version: codex-certification-train.v1
train_id: T042
objective: Sparebank external-model B0-B1 foundation
base_sha: ...
issues:
  - id: ISSUE-0716
    source_commit: ...
    integrated_commit: ...
    dependencies: []
  - id: ISSUE-0717
    source_commit: ...
    integrated_commit: ...
    dependencies: [ISSUE-0716]
head_sha: ...
tier: H
tier_reason: external-model immutable store and workflow contract
review:
  whole_diff: pending
  specialist: pending
validation:
  local_admission: pending
  hosted_run: null
rollback:
  per_issue_revert_order: [ISSUE-0717, ISSUE-0716]
```

## 11. Frozen-head review and CI

Once all required local evidence passes:

1. complete canonical documentation/control preparation;
2. commit and freeze the train head;
3. launch whole-diff review and required specialist review against that SHA;
4. launch hosted CI against the same SHA after #714 admission;
5. collect all verdicts before correction;
6. perform one consolidated correction pass if possible;
7. freeze a replacement head and repeat only invalidated evidence.

A new commit invalidates exact-head review and CI. Read-only analysis of the same head does not.

## 12. GitHub PR design

PR body must list:

- train objective;
- exact base/head;
- issue-to-commit map;
- dependency order;
- ownership/manifests;
- tier and reason;
- focused evidence per issue;
- train-level impact evidence;
- review verdicts;
- terminal hosted result;
- rollback order;
- explicit unchanged authority.

Use one draft PR only if workflow configuration prevents expensive gates on every moving draft push. Otherwise perform local integration and open/push once the head is admitted.

## 13. Cleanup

After merge and lifecycle convergence:

```bash
git worktree list --porcelain
git worktree remove ../etf_ai_cockpit_wt_T042_0716
git branch -d codex/T042/ISSUE-0716
git worktree prune
```

Do not remove a lane until its commit/evidence has been integrated or explicitly abandoned and preserved.

## 14. Worktree anti-patterns

- ten writable worktrees;
- worktrees on the same branch;
- shared SQLite/DuckDB/output directory;
- overlapping `services.py`, global fixtures or canonical state;
- merging all lane branches and resolving conflicts at the end;
- one child per file rather than one owner per behaviour;
- running full gates independently in every lane;
- pushing each intermediate lane head to trigger hosted CI;
- accepting a stale lane because its focused tests once passed;
- deleting worktrees before recording source/integrated SHAs.

## 15. Recommended first pilots

1. Two disjoint ordinary documentation/UI issues with no shared source or test fixture.
2. A three-issue ordinary fundamental-analysis train after #714 node selection.
3. Sparebank #716 and #717 only if interface ownership is sequential rather than simultaneous; likely one writer, with #719 read-only UI planning in parallel.
4. A protected two-issue train only after ordinary pilots show no increase in review findings or rework.
