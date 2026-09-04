# Triple-barrier labels and purged validation: research-only scope (ISSUE-0062)

Status: bounded research specification. This document defines safety
requirements; it does not implement labels, a classifier, runtime scoring,
signals, portfolio decisions, paper trading, or execution.

`triple_barrier_research` remains `research_only` with `authority=none`,
`score_authority=false`, `paper_authority=false`, and
`execution_authority=none`. Triple-barrier labels are optional research
annotations and cannot replace the cockpit's declared return horizons or enter
the baseline score path. General leakage-safe validation is directed to
ISSUE-0120.

## Label definition and parameter contract

For an event observed at timestamp `t`, a future research implementation may
declare (before seeing outcomes):

1. an upper horizontal barrier (profit threshold),
2. a lower horizontal barrier (loss threshold), and
3. a vertical barrier at `t + H` (the maximum holding horizon).

The label records the first barrier touched, or the vertical-barrier outcome
when neither horizontal barrier is touched. The record must retain the event
timestamp, barrier parameters and source/as-of metadata. Prices, corporate
actions, calendars, costs, and the tie-breaking rule must be explicitly
versioned. Parameters may vary by declared asset class, horizon or regime only
when that segmentation is predeclared and independently validated; tuning them
after inspecting the test outcomes is leakage.

## Minimum samples and stability

There is no universally safe sample count. A future study must predeclare a
minimum number of non-missing events per asset/task/horizon/regime and per
class, plus a minimum number of independent validation folds. The report must
show the effective sample after overlapping labels are removed, class balance,
event coverage, missingness and confidence intervals. If any threshold is not
met, the result is `insufficient_sample`/`unstable` and is not promoted or
silently pooled with another horizon. Stability checks must cover time splits,
regimes, asset groups and barrier sensitivity; a label distribution that moves
materially across those slices requires abstention or an explicit limitation.

## Purging, embargo and leakage warnings

Forward labels overlap in time. A validation fold must therefore:

- purge every training event whose label window intersects the validation
  window, including an event at the boundary;
- apply an embargo after validation for at least the maximum declared label
  horizon (and record the exact bars/calendar interval); and
- keep feature availability, event timestamps, group membership and all
  parameter-selection decisions point-in-time and outside the validation fold.

The validation manifest must include train/validation/embargo intervals,
purged event identifiers, the label horizon, feature as-of cut-offs and a
leakage-canary result. It must fail closed for overlapping windows, missing
timestamps, future-derived features, duplicate events, unrecorded trials or a
parameter selected from the final test set. Random k-fold splitting, fitting a
classifier before the split, and using future volatility or membership to set a
barrier are explicit anti-patterns.

The canonical implementation and evidence for walk-forward, nested, purged and
embargoed validation belongs to ISSUE-0120. This issue does not duplicate that
runtime work and does not authorize any model-training dependency.

## System Map and rejection boundary

The System Map presents this topic under **Research-only strategy boundaries**
with the `triple_barrier_research` scope row. It must show `research_only`,
authority `none`, `score_authority=false`, `paper_authority=false`, and
`execution_authority=none`, together with the barrier, minimum-sample,
stability, transparent-parameter, purging, embargo and leakage-canary rules.

The following transitions are rejected by policy and tests:

1. labels becoming a default score, ranking feature, final action or trade
   signal;
2. an ML classifier or runtime model-training path being added under this
   research-only scope;
3. validation using ordinary random folds, overlapping label windows or an
   embargo shorter than the declared maximum horizon;
4. an insufficient or unstable sample being represented as a successful result;
   and
5. a label study granting paper, portfolio or execution authority.
