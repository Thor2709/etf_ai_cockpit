# Development control plane

## Fresh root: two reads, one derived view

Read `AGENTS.md` and this page once. Fetch and verify
`Thor2709/etf_ai_cockpit`/`origin/main`; use a clean exact-main checkout. Run:

```text
python scripts/programme_execution.py --check
python scripts/programme_execution.py --issue ISSUE-0019
```

Replace the example ID with the report's NOW candidate. `--json` exposes every
ready/excluded/blocked record, graph metrics, conditional dependency waves,
existing work locators, source routing and evidence-reuse diagnostics. No command
above fetches, launches agents, installs a Skill, mutates state or grants execution.
A dirty/non-main checkout is explicitly a preview, not a fresh-root admission.

The command checks canonical registry/ledger regeneration. `--check` additionally
runs the existing full atomic programme freshness check. It reads only current
canonical sources; old checkpoint archives are not part of normal startup.
The issue card includes the complete canonical record, source ledger section,
all normative amendments, edge evidence and historical implementation locators.
Do not infer completion from an absent standalone acceptance field or from the
legacy `package_status` label.

## Authority map

| Fact | Semantic authority | Legal edit source | Generator / projection | Consumer |
| --- | --- | --- | --- | --- |
| Product scope and acceptance | Immutable July source packages, original issue clauses, normative amendments; reviewed canonical extensions | Original sources stay immutable; extensions follow existing reviewed control authority | `issue_registry_core.py` → registry and issue cards | Implementer and formal reviewers |
| Lifecycle, phase, dependencies and edge evidence | Reviewed canonical control state and its transition/evidence contracts | `issues/programme_control_state.json` through existing guarded transactions | `generate_programme.py` stages component generators → registry, readiness, phase/status views | Planner, validation, GitHub synchroniser |
| Delivery policy | Reviewed root instructions and delivery contract | `AGENTS.md`, `DELIVERY_WORKFLOW.md`, durable configuration/role sources | Delivery is a **pass-through protected input**, included in the generation manifest, not rendered from a hidden template | Root, classifier, reviewers, CI |
| Model/role and capacity identity | Durable `config-core.toml`, role TOMLs, existing routing validator | Reviewed files under `docs/codex-config/` | On-demand harness view; explicit local routing audit | Codex root; actual child metadata still required |
| AGY capabilities and containment | Reviewed adapter, custom agents and Skill source | `agy_delegate.py`, two `.agents/agents` definitions, reviewed Skill | On-demand view reads `CAPABILITY_STATES`; offline tests check the harness | Root-controlled Scout/staged Editor adapter |
| Current main | Fetched Git ref / fresh GitHub read | Git integration by root only | On-demand exact SHA; never embedded as a moving policy constant | Root, planner, guards |
| Active ownership | Root's complete local writer census and exact observed lane state | Untracked common-Git-directory lane manifest | Read-only `active_work.py` validation against main/programme/Git/PR identities | Root admission, not automatic dispatch |
| Prior work and evidence | Original commits, tests, review metadata, artifacts and canonical acceptance references | Preserve original evidence; add locators, not invented verdicts | `work-index.json` is a historical locator; classifier computes reuse/invalidation | Root and named reviewers |
| GitHub issue state | Git-canonical programme plus existing checksum/append-only mutation authority | Existing reviewed gateway and sole writer only | Hash-bound status comments and zero-action readback | Synchroniser and issue viewers |

**Manifest membership does not by itself establish edit authority.** Control state
is canonicalised and included in atomic output; the delivery contract is copied
through. The registry, readiness and generated status/phase documents must not be
hand-edited. `issues/open.md` also contains historical editable clauses outside
its generated final-release block; preserve that distinction. Generated entry
wording is edited in `scripts/generate_completion_documents.py`.

Use `python scripts/generate_programme.py --root .`, then repeat with `--check`.
Keep grouped atomic publication and byte-clean verification. The historical
`generation_base_commit` identifies imported reconciliation evidence; it is not
current main and should not be churned after every merge.

## NOW, NEXT and future work

The selector intersects canonical dependency readiness with unfinished/open
lifecycle eligibility. Research-only, rejected, deferred, closed, integrated and
explicitly blocked records cannot become implementation work merely because
blocking edges are empty. Activation dependencies remain separate; even a ready
activation projection cannot override `execution_allowed=false`.

Ordering is deterministic: canonical phase precedence, verification of known
merged products awaiting lifecycle, inspection of preserved candidates, priority,
remaining downstream reach, graph depth, then canonical ID. This preference
reduces duplicate implementation without relaxing acceptance. A work locator
proves neither feature completeness nor fresh review: verify source changes and
actual artifacts. A missing Git object is explicit, not silently accepted.

Phase membership is preserved. Phase 01 is historically broader than its title;
its owner/write-conflict labels are not path ownership. Later-phase work may be
prepared when dependency-ready and independently owned; root retains phase
precedence for primary work and serial integration. Graph depth is a count of
blocking edges, not a time estimate. `conditional_dependency_waves` show topology,
not safe concurrency; each unresolved edge still needs the required reviewed
interface/completion evidence. An integrated parent alone does not waive its edge.
Evidence-only blockers are shown separately from incomplete product parents.

Every candidate still needs contract/source/test feasibility preflight. In
particular, an absent blocking edge does not license invented model outputs,
unavailable historical data or a UI stub that fails acceptance. Missing producer
contracts found during preflight require an evidenced issue-specific correction
through existing authority, not arbitrary new dependencies or silent waivers.

`contract_diagnostics` exposes demonstrated source/parser disagreements while
still enforcing the existing canonical edges. The observed compact-metadata
parser incorrectly absorbs downstream consumers as blockers for ISSUE-0167 and
ISSUE-0169 (including certification ISSUE-0152). Their guarded semantic migration
is unresolved: do not infer that an acyclic graph proves semantic correctness,
waive those edges, or issue final certification before this defect is repaired.

## Active work and parallel admission

The root reconciles **all active writers** first. Store observations in the common
Git directory's `etf-control/active-work.json`, or supply `--lanes <file>`.
Use `git rev-parse --git-common-dir` to find the shared location across worktrees.
This is a local observation file, not a second canonical programme or a distributed
lock. A second root must not assume it owns the first root's active writers.

`docs/development/templates/active-work.example.json` is a schema example, not
an active reservation. It adapts the useful bounded-lane idea preserved in PR #721
without installing that PR's obsolete routing or certification-train proposals.
The manifest binds observed main, generated programme hash, root session, complete
writer census and occupied/reviewer child counts. Each worker lane records one issue,
branch/worktree/base/head/PR, writer route, exact source/tests, runtime roots,
ports/shared resources, state, blocker and next action. A `codex-root` lane may use `issue: null` for owner-requested control-plane
work without inventing a canonical issue. At most one root integration lane is
admitted; only root lanes may own canonical/policy files. Root lanes consume no
child slot. A root lifecycle lane for a product still identifies that canonical issue.

Paths are exact files or directory boundaries, never globs or symbol-only claims.
Declare every mutable test store/cache/temp/profile/database and GPU/resource
conflict, not just source files. Worker lanes cannot own canonical policy/status
writes; root prepares those serially outside worker assignments. Use separate
namespaced runtime roots. Role/group labels and separate worktrees alone are
insufficient. AGY entries mean root-owned **staged** assignments, never independent
issue owners. The adapter still requires an exact-file Editor packet and performs
its own complete-candidate checks.

For PR-backed lanes, supply `--pulls <fresh-observation.json>` with
`observed_main` and `pulls`, mapping each PR number string to its exact `head`,
`branch`, `base`, `base_branch` and `state`. The base must be the observed main
SHA and the target branch must be `main`. Obtain these values from a fresh GitHub read; copying the
lane's claimed values is not readback. The validator detects a changed head,
closed PR, stale main/programme/base, wrong local branch/head/repository, committed or working changes outside ownership, already
integrated/non-ready issue, overlapping source/tests/runtime/ports/resources and
insufficient reserved reviewer capacity. Stale bases require root revalidation
and a fresh exact-base lane before admission, not deletion of the old candidate.

`parallel_waves` contains only the proposed current admitted group against the
supplied local observations; `conditional_waves` requires released reservations,
new observations and new capacity checks. Missing observations mean **no proved
parallel admission**. Nothing launches automatically. Root must still verify real
worker/runtime metadata, contract independence and mutable resources not visible
to Git. Root alone serialises canonical mutation and every merge.

## Validation and evidence

The existing E/O/H/C classifier remains authoritative. Deleted paths and both
rename endpoints now participate in risk selection. Working changes cannot mask
a committed base/head diff. Deleted tests affect risk even when they are no
longer runnable pytest paths. Unknown classification/history fails upward.

`validation_identity.py` supplies identical protected identity groups to classifier
reuse and terminal evidence. Source identity includes tests; policy includes the
durable V2/AGY harness and delivery contract; environment includes relevant locks.
A changed binding invalidates old sidecars instead of minting replacement evidence.
The planner's reuse diagnosis calls the existing validator and checks the
base-anchored sidecar; it is an index, not an approval or substitute for artifacts.

Formal whole-diff, risk and release reviews still require actual configured role,
model, effort and exact-head evidence. Self-review, a PR description or a generic
bot cannot satisfy these gates. The standard packaged pytest collection now also
executes the existing offline harness tests without personal AGY installation.

CI source checkouts use and verify the exact reported head. PR heads must include
the exact freshly fetched main base; this preserves integration coverage rather
than testing an old branch alone. Trusted authority/base validation remains
separate. Linux/Windows serial packaged gates, report-only pilot rules, preflight,
supply-chain and terminal-summary requirements are unchanged. Do not accept an
old run after a source, test, dependency, policy, environment or artifact change.

Product integration and lifecycle completion are distinct. When the ancestry
guard requires the product on main, complete product gates first, merge that
exact head, then prepare the single legal existing lifecycle transaction. Never
fabricate pre-merge ancestry or weaken the guard to combine incompatible phases.
Finish ordered writer acceptance and independent zero-action readback before
claiming the issue integrated. Verify server branch protection through fresh GitHub reads;
the audit observed none. Root/process enforcement is not a server guarantee.

## Historical material and local reconciliation

The exact former AGENTS/active goal/B04/initial blueprint/root plan/configuration
README are retained under `plans/archive/2026-09-08-control-plane/` with original
paths, Git blobs and byte hashes. Existing reconciliation directories and evidence
stay at their referenced locations. Current policies point into history only when
needed. Do not append chronology to operational entry points.

`docs/development/audits/2026-09-08/` records the one-time findings, canonical/DAG
inventory, PR/branch classifications and local-path references. It is explicitly
an observation at the recorded base, not live status. Historical AGY branches
may contain useful code; none confers active ownership. Inspect unique commits,
tracked/untracked work and evidence before any local deletion. Do not delete
uncertain work, unrelated repositories or required validation evidence.

Local Skill installation and actual loaded V2 configuration remain machine facts.
`--live-skill <absolute-directory>` compares source/live bytes without writing;
`agent_routing.py` audits actual local configuration. Preserve unexpected drift
and synchronise only a reviewed accepted source. No file here proves that a user's
current desktop loaded the configuration or that its outside-workspace canary
still matches the approved runtime identity.
