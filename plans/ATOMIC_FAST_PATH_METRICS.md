# Atomic delivery fast-path metrics

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

PR #610 includes an intentional laptop-unplugged pause and is not treated as
runner or active-work time. Five of these eight PRs were control/evidence
repair transactions, so the observed non-product share is `62.5%`; the target
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

The ten E/convergence transactions have execution p50 `0.46 min` and p95
nearest-rank `2.18 min`, inside the timing target across the required sample
size. This measures workflow execution, not end-to-end issue throughput.
Successful H runs remain approximately `20–26 min`, with the full
Linux/Windows coverage unchanged.

### Fixture and invariant evidence

- E: run `30453340819` passed terminal summary, reused exact product evidence
  and skipped Linux/Windows packages.
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
  of applying a genuine nonzero status update. The bounded status-only apply
  repair is locally implemented and validated with exact checksum, inventory,
  PR-head, fresh-main, canonical-transition and zero-readback fixtures; its
  protected H integration and post-merge proof remain outstanding.

No accepted baseline failures or environment mismatches were introduced.
Financial, point-in-time, revision, security, supply-chain, broker/provider and
package authority are unchanged; `execution_allowed=false`. Foreground waiting
and polling reduction were not instrumented accurately enough in this wave, so
no reduction is claimed. Detached watchers reduced the need to hold a local
watcher open, but that observation is not a measured result.
