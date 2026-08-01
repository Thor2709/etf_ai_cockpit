# Atomic delivery fast-path metrics

## Current ISSUE-0180 pilot policy

The exact ISSUE-0180 four-worker measurements are frozen in the fast-path
evidence below. Run `30659377591` used two repetitions and four workers; all
lanes collected and returned the same `2,452` tests and the cross-platform
aggregate passed.

| Platform | Full serial samples (s) | Serial p50/p95 (s) | Four-worker combined samples (s) | Candidate p50/p95 (s) | p50 saving |
|---|---|---:|---|---:|---:|
| Linux | `1110.085`, `1121.291` | `1115.688/1120.731` | `619.380`, `640.006` | `629.693/638.975` | `485.995 s` (`43.56%`) |
| Windows | `1240.438`, `1268.553` | `1254.495/1267.147` | `734.835`, `683.629` | `709.232/732.275` | `545.263 s` (`43.46%`) |

These are report-only development-throughput measurements, not release-gate
authority or application-performance claims. The serial Linux/Windows package
gates remain authoritative. Ongoing samples are selected only by pilot
mechanics, pytest partition/collection, environment/lock, concurrency,
persistence, Windows-sharing, atomic-write or isolation changes, tier C, or
an explicit default-branch `repository_dispatch` or scheduled drift sample.
Arbitrary-ref `workflow_dispatch` is not exposed and drift samples receive no
release-signing material. The new policy measures saved
runner minutes before and after each eligible sample; no saving is claimed
without a recorded comparison. Historical bootstrap PR counts are not
steady-state results.

## Baseline snapshot

Captured from the GitHub pull-request and Actions APIs on
`2026-07-29T01:15Z`, before ISSUE-0179 implementation. The sample is the ten
consecutive merged transactions PR #599–#608. Percentiles use the nearest-rank
method except p50, which is the mean of the two central observations.

| PR | Purpose | Lead time (min) | Files | Additions | Deletions |
|---:|---|---:|---:|---:|---:|
| 599 | ISSUE-0088 product | 24.02 | 37 | 16,257 | 37 |
| 600 | ISSUE-0088 integrated evidence | 25.05 | 35 | 15,519 | 43 |
| 601 | ISSUE-0089 dependency evidence | 27.10 | 33 | 15,507 | 55 |
| 602 | ISSUE-0089 dependency evidence | 28.10 | 34 | 15,503 | 54 |
| 603 | ISSUE-0089 product | 28.05 | 38 | 16,421 | 32 |
| 604 | ISSUE-0089 in-progress evidence | 24.77 | 35 | 15,514 | 41 |
| 605 | ISSUE-0089 implemented evidence | 27.05 | 35 | 15,499 | 37 |
| 606 | ISSUE-0089 integrated evidence | 25.18 | 35 | 15,503 | 38 |
| 607 | ISSUE-0090 dependency evidence | 26.18 | 33 | 15,507 | 55 |
| 608 | ISSUE-0090 dependency evidence | 65.25 | 34 | 15,502 | 54 |

Baseline aggregates:

- PR lead-time p50: `26.62 min`; p95 nearest-rank: `65.25 min`.
- Successful Release Gate duration p50: `24.74 min`; p95 nearest-rank:
  `26.90 min`. PR #608 required one authorised unchanged-head retry after the
  UTC-midnight fixture race, so its PR lead time retains that failure cost.
- Median changed files: `35`; median additions: `15,507`.
- Total diff churn: `156,732` additions and `446` deletions.
- Product PRs: `2/10` (`20%`); control/evidence-only PRs: `8/10` (`80%`).
- ISSUE-0089 required six sequential transactions: two dependency edges, one
  product PR and three lifecycle PRs. The historical orchestration log
  recorded `197` explicit polling commands and about `179 min` of foreground
  waiting for that delivery sequence.

## Measurement contract

After the fast path is integrated, record at least ten representative
transactions where available, separating runner execution from GitHub queue
time. Track:

- worker-completion-to-actionable-result and total PR lead time;
- PRs per integrated issue and product-code PR share;
- E/O/H/C classification and required/skipped validation;
- exact runner duration, obsolete-run minutes and queue duration;
- generated file/line churn;
- synchronous polling commands and foreground waiting;
- environment mismatch and stale-generation failures;
- exact retained financial, point-in-time, revision, security, broker and
  `execution_allowed=false` invariants.

Do not declare the performance target met from one favourable run.

## Fast-path implementation and proof wave

Captured on `2026-07-29` for PRs #609–#616. This is a repair/bootstrap wave,
not a normal steady-state sample.

| PR | Purpose | Lead time (min) | Files | Additions | Deletions |
|---:|---|---:|---:|---:|---:|
| 609 | Atomic generation/control implementation | 128.55 | 27 | 2,487 | 174 |
| 610 | Convergence token wiring | 374.30 | 4 | 22 | 13 |
| 611 | Exact-tree E reuse repair | 54.90 | 5 | 412 | 30 |
| 612 | Multi-event status guard | 51.17 | 5 | 170 | 59 |
| 613 | ISSUE-0179 compact E lifecycle | 5.98 | 10 | 178 | 39 |
| 614 | ISSUE-0180 environment product work | 24.35 | 8 | 325 | 15 |
| 615 | Convergence fixture repairs | 25.82 | 7 | 220 | 16 |
| 616 | ISSUE-0090 catalogue product continuation | 21.33 | 7 | 391 | 22 |
| 617 | Reviewed status-completion automation | 26.58 | 9 | 717 | 49 |

PR #610 includes an intentional laptop-unplugged pause and is not treated as
runner or active-work time. Six of these nine PRs were control/evidence
repair transactions, so the observed non-product share is `66.7%`; the target
below `30%` is not met by this bootstrap wave. ISSUE-0179 required five PRs
(#609–#613), also above the normal issue target. These facts are retained
rather than presenting the repair wave as steady-state improvement.

### Representative workflow transactions

Run-level queue time was observed as `0 min` for the earlier rows below.
Run `30461814321` records its separately observable `0.15 min` queue before
the `0.45 min` job execution. Dependency waits inside a workflow are included
in duration and are not reclassified as queue time.

| Run | Result/tier | Duration (min) | Exact evidence |
|---:|---|---:|---|
| 30420622584 | success H | 25.72 | Linux/Windows `2144/2144` |
| 30421830231 | failed convergence | 0.38 | missing `GH_TOKEN` wiring |
| 30421980682 | success H | 24.38 | Linux/Windows `2144/2144` |
| 30444182563 | success convergence | 0.48 | exact-main zero action |
| 30445604844 | success H | 25.85 | first reviewed PR #611 head |
| 30447413859 | success H | 26.48 | Linux/Windows `2154/2154` |
| 30449179032 | success convergence | 0.35 | exact-main zero action |
| 30449330177 | success H | 26.08 | first reviewed PR #612 head |
| 30451275797 | success H | 22.17 | Linux/Windows `2161/2161` |
| 30452879033 | success convergence | 0.43 | exact-main zero action |
| 30453070300 | failed E | 2.18 | stale generation manifest; packages skipped |
| 30453340819 | success E | 1.73 | reuse authorised; packages skipped |
| 30453521074 | failed convergence | 0.43 | zero-action sidecar rotation gap |
| 30453850014 | success H | 23.65 | Linux/Windows `2169/2169` |
| 30455673946 | failed convergence | 0.47 | zero-action sidecar rotation gap |
| 30456636457 | success H | 24.62 | Linux/Windows `2171/2171` |
| 30458709210 | success convergence | 0.48 | exact-main zero action after sidecar rotation |
| 30460043778 | success H | 20.32 | Linux/Windows `2177/2177` |
| 30461814321 | success convergence | 0.45 | exact-main zero action; `0.15 min` queue |
| 30463554978 | success H | 25.53 | Linux/Windows `2191/2191` |
| 30465742045 | success convergence | 0.35 | exact-main zero action; `0.05 min` queue |

### Frozen compact-control sample

The final sample includes every push-triggered `Programme convergence
evidence` and `Programme status completion` run on `main` from PR #618's
merge through PR #628's merge, inclusive. It includes eligible failures,
excludes PR/full Release Gate runs and freezes the cutoff before PR #629 so
the result cannot drift with later runs.

| Run | Queue (min) | Execution (min) |
|---:|---:|---:|
| 30496885950 | 0.0333 | 0.3333 |
| 30499499975 | 0.0500 | 0.4167 |
| 30500052132 | 0.0500 | 0.4167 |
| 30500490803 | 1.8833 | 0.3667 |
| 30607173205 | 0.1500 | 0.3500 |
| 30613949318 | 0.0500 | 0.4000 |
| 30619723960 | 0.1500 | 0.4000 |
| 30645015084 | 0.0500 | 0.4667 |
| 30645015094 | 0.5667 | 0.2833 |
| 30647061104 | 0.0500 | 0.9500 |
| 30650771847 | 0.1500 | 1.2500 |

Queue time is workflow creation to job start; execution is job start to
completion. For `n=11`, nearest-rank percentiles use `ceil(p*n)`: p50 selects
observation 6 and p95 observation 11. Execution p50/p95 is therefore
`0.4000/1.2500 min`; separately measured queue p50/p95 is
`0.0500/1.8833 min`. This is workflow execution evidence, not end-to-end
issue throughput. Successful H runs remain approximately `20–26 min`, with
the full Linux/Windows coverage unchanged.

### Fixture and invariant evidence

- E: run `30453340819` passed terminal summary, reused exact product evidence
  and skipped Linux/Windows packages.
- Across the audited E sample, package skipping was selected correctly in all
  five eligible transactions (`5/5`).
- Cache reuse occurred in `10/46` observed opportunities (`21.74%`).
- Independent dependency edges: the schema-1.3 status guard fixture validates
  two unrelated integrated edges in one transaction.
- O: classifier fixtures require focused/affected/UI/architecture/static/source
  checks and apply the central full-gate cadence separately.
- H: persistence and canonical-finance fixtures require both packaged
  platforms.
- Consecutive merges: exact-head fixtures cover two fresh main advances; PR
  #615 then merged on the immediately prior PR #614 main and automatic
  convergence passed without a stale base or manual convergence PR.
- Status completion: the earlier read-only staging design was found incapable
  of applying a genuine nonzero status update. The bounded authority repair
  culminated in formal ISSUE-0180 PR #630. Ordered writer `30658275241`
  appended one reviewed proposal and receipt, projected `integrated`,
  preserved unrelated issue content and completed zero-action readback;
  convergence `30658275236` then deferred successfully. Git remains canonical
  and the body status remains the deliberate bootstrap anchor.

### Post-merge release-gate defect found by completion audit

The completion audit found that each ordinary H-reviewed merge also launched
the full signed Release Gate on `push` to `main`. The release gate correctly
requires `RELEASE_SIGNING_KEY` outside pull-request evidence, but an ordinary
merge is not a release and the key is intentionally absent. Seven post-merge
runs through `30465742029` therefore reran the complete Linux/Windows package
matrix and failed only at signature after all tests and other mandatory checks
passed.

The fourteen duplicate platform jobs consumed `291.90` runner-minutes:
`135.45` Linux and `156.45` Windows. The final pair each passed `2191/2191`
tests before failing at the missing signature. This is accepted neither as a
baseline failure nor as necessary release evidence; the active repair removes
ordinary `main` pushes from the signed Release Gate while retaining the exact
pull-request H matrix and fail-closed signing behavior for an explicitly
invoked release.

No accepted baseline failures or environment mismatches were introduced.
Financial, point-in-time, revision, security, supply-chain, broker/provider and
package authority are unchanged; `execution_allowed=false`. Foreground waiting
and polling reduction were not instrumented accurately enough in this wave, so
no reduction is claimed. Detached watchers reduced the need to hold a local
watcher open, but that observation is not a measured result.
