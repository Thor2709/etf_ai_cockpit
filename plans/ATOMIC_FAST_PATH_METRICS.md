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
