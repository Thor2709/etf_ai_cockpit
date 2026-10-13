# Leakage-safe validation protocol

`etf_cockpit.validation.protocol` owns temporal validation boundaries, not
model training. Callers provide per-observation trial scores and receive an
immutable, fingerprinted report containing the split definition, folds,
retained trial records, uncertainty, regime/subgroup summaries and promotion
decision.

Development folds are rolling or expanding walk-forward windows. Labels are
purged by the configured forecast horizon and a separate embargo keeps future
observations out of the training window. A final tail is reserved before any
trial is selected; `final_test_used_for_selection` is structurally false and
discarded trials remain in the report.

The local application facade exposes a read-only preview in Training Centre
and Backtests. It proves the protocol from adjusted-price returns without
training or promoting a model. Real trial scores, model registries and
champion/challenger promotion remain separate issues.


## Issue 928 inference and durable authority

The application `evaluate_registered_trials(root, run_id, scores, ...)` binds
validation to an existing local experiment run. `evaluate_trials` without a
registry remains a development preview: caller-supplied history and holdout
booleans grant no inference or holdout authority. Existing final-score callers
must declare a frozen candidate, distinct comparators and a holdout ID through
the registered application boundary. Their candidate and baseline final-score
fields retain their meanings; undeclared alternatives receive no final score.

Before inference, the registry atomically retains every submitted series in
existing immutable `validation.trial` payloads, with an evaluation manifest,
run/data identity, spec fingerprint and full observation alignment. All prior
runs in that experiment, including rejected alternatives and repeated runs,
join the family. A retained report referencing the submission is a view, not
an extra trial. Missing run/member records, tombstones, mutable trial evidence,
or incompatible data/spec/date alignment make family statistics unavailable
with a reason and prevent promotion. Legacy reports without alignment evidence
are unavailable; no storage schema migration or reconstruction is attempted.
The complete retained count is used conservatively without a correlation
reduction. Completeness is relative to the declared durable experiment; an
unrecorded external experiment is never claimed to be verified.

An append-only `validation.holdout_use` payload is committed in the same existing
SQLite transaction before scoring. It binds run lineage, candidate/comparator
identities and series fingerprints, holdout identity and evaluation ID. History,
not flags, determines reuse. Conservative consumption is dataset-wide, so
renaming or resizing a holdout cannot restore independence. A crash after the
commit consumes the holdout. Later evaluations include the formerly sealed
tail in development folds, expose `development_reuse`, and have no final score.
Unverified families cannot authorize a first holdout read. Direct audit
registration only consumes authority; audit rows cannot be replayed as tokens.

Inference groups complete date clusters in chronological order, then uses
only walk-forward validation dates. Cross-sectional scores receive equal
within-date weight; mixed subgroup labels are omitted rather than attributed
to a date-level score. Paired moving-block bootstrap resamples candidate minus
baseline, uses a centered-null one-sided test with the finite-resample +1
correction, and caps block length at half the available dates (minimum one).
Fewer than two paired dates are unavailable. Seeds/repetitions retain the spec.

DSR follows Bailey and Lopez de Prado (2014), *The Deflated Sharpe Ratio*,
equations (1), (3), (4): the expected maximum uses the across-trial sample
variance of periodic Sharpes; the selected estimator variance uses periodic
Sharpe, population standardized skew and Pearson kurtosis. The probability is
frequency-invariant, but frequency must be explicitly declared. Fewer than
three observations, fewer than two trials, or undefined trial Sharpes give
unavailable. CSCV follows Bailey et al. (2017), *The Probability of Backtest
Overfitting*: at most ten even chronological blocks, all complementary half
splits, development mean-score selection, and out-of-sample midrank logits;
non-positive logits count as overfitting. It requires at least four dates and
two trials. FDR is the minimum Benjamini-Yekutieli (2001) step-up adjusted
q-value over the complete non-baseline family, including retained alternatives;
missing paired evidence never shrinks that family. Numeric regression oracles
cover DSR's two-trial expected maximum, all six four-date CSCV splits, and BY's
four-hypothesis harmonic correction.
