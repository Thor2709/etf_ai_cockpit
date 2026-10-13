# ST1 issue 928 — correction pass 1 handoff

Scope: the three supplied numbered BLOCKING findings, in the existing worktree.
Correction base: `6c06d84406179310b9499b02eec76b00fb7e2b1c`.
The checkout was initially clean; origin's configured URL was verified as
`https://github.com/Thor2709/etf_ai_cockpit.git`. No fetch, network, package install,
branch change, commit, canonical programme write or external action was performed.
This is a local correction handoff, not product/lifecycle/release acceptance.

## Per-entry outcomes

| Supplied finding | Outcome | Evidence |
| --- | --- | --- |
| BLOCKING 1 — promotion with unavailable statistics | FIXED | `test_promotion_requires_available_statistical_evidence[None]` and `[12]`: the complete first registered family has three folds, positive paired lower bound and an audited passing final score, but DSR is unavailable. Both failed on the correction base (`True` eligibility) and pass with eligibility `False`; frequency/undefined-Sharpe reasons remain explicit. Promotion now requires available DSR, PBO and FDR. |
| BLOCKING 2 — PBO excludes counted optimiser alternatives | FIXED | Extended `test_optimiser_search_trials_count_in_the_validation_family`, retaining all previous assertions. Base reported six trials but PBO `0.5634920634920635`; corrected PBO is `None` with `trial_family_series_unavailable: 4 ledger trial(s) lack aligned series`. All four attributable statuses remain counted; the unrelated run remains excluded. |
| BLOCKING 3 — consolidated acceptance handoff/reference evidence | DEFERRED (partially addressed) | This document supplies commands, base/failing-first evidence, caller/default/file audit, numerical limitations and an independent SciPy BY comparison. The original bughunt register and independent DSR/CSCV reference fixtures were not supplied or found locally; their acceptance cannot be fabricated. Requests for those inputs remain pending. |

Original register coverage is **unverifiable**: the register itself is absent.
The following are observed existing test labels, not invented register entries.
For this correction base they are REJECTED as requiring an additional fix
(test already passed on the base); this preserves, rather than rejects, the
earlier implementation. This cannot attest to omitted register entries.

| Observed test label | Correction-base outcome | Checked test |
| --- | --- | --- |
| `issue928_1` | REJECTED (test already passed on the base) | `test_issue928_1_chronological_clusters_and_paired_block_reference` |
| `issue928_2` | REJECTED (test already passed on the base); reference acceptance remains limited | `test_issue928_2_published_method_numeric_references` |
| `issue928_3` | REJECTED (test already passed on the base) | `test_issue928_3_incomplete_or_misaligned_durable_family_fails_closed` |
| `issue928_4` | REJECTED (test already passed on the base) | `test_issue928_4_caller_flags_cannot_authorize_or_reset_holdout` |
| `issue928_8` | REJECTED (test already passed on the base) | `test_issue928_8_single_trial_and_too_small_inference_guards` |

## Evidence and exact commands

Every test command set `ETF_COCKPIT_OPEN_BROWSER=0`; pytest cache was disabled.

1. Before any production edit, after adding the regressions and initial reference
   comparison:
   `python -m pytest tests/test_bug_issue928.py -q --tb=line -p no:cacheprovider`.
   Result: 24 passed, 3 failed. Failures were precisely the two promotion
   parameters and the extended search-ledger PBO assertion. The independent BY
   comparison already passed on the base, so it is evidence, not a numerical fix.
2. After production edits:
   `python -m pytest tests/test_bug_issue928.py tests/test_validation_protocol.py tests/test_validation_application.py tests/test_training_centre.py tests/test_optimisation.py -o addopts= -q --tb=line -p no:cacheprovider`.
   Result: 47 passed, 0 failed, 13.06 s. Original assertions were retained.
3. Exact-base replay of the original issue file: a fresh Python process inserted
   this checkout's `src` into `sys.path`, imported the protocol, then executed
   `git show HEAD:src/etf_cockpit/validation/protocol.py` into that module. It wrote
   `git show HEAD:tests/test_bug_issue928.py` byte-for-byte into a temporary
   `st1-928-base-*` directory and invoked
   `pytest.main([test_path, '-o', 'addopts=', '-q', '--tb=line', '-p', 'no:cacheprovider'])`.
   Result: all 24 original tests passed in 5.07 s. Remaining source was the base
   source (the training-centre correction is only a comment). Temporary files
   were removed by `TemporaryDirectory`; no tracked file was reverted.
4. Static checks:
   `python -m ruff check --no-cache src/etf_cockpit/validation/protocol.py src/etf_cockpit/features/training_centre.py tests/test_bug_issue928.py`
   and `git diff --check`: passed.
5. After extending only the independent reference test with SciPy's documented
   TAPS inputs:
   `python -m pytest tests/test_bug_issue928.py::test_issue928_fdr_matches_independent_scipy_reference -o addopts= -q --tb=line -p no:cacheprovider`.
   Result: 1 passed, 0 failed, 1.86 s. Ruff and whitespace checks also passed
   again for that test change; unaffected passing tests were not rerun.

The reported prior full-suite result of 1,742 passing tests is user-supplied
evidence; its exact command/artifacts were not supplied and it was not rerun.
No Linux/Windows packaged gate, independent formal review or final product
acceptance is claimed for this uncommitted correction.

## Independent reference and numerical limitations

`test_issue928_fdr_matches_independent_scipy_reference` compares the existing
minimum BY adjusted q-value against
`min(scipy.stats.false_discovery_control(p_values, method="by"))`.
Installed reference: SciPy **1.18.0**, `scipy.stats._morestats`, source
`C:/Users/thor2/AppData/Local/Programs/Python/Python312/Lib/site-packages/scipy/stats/_morestats.py`.
Its local docstring identifies Benjamini and Yekutieli (2001), *The control of
the false discovery rate in multiple testing under dependency*, pp. 1165–1188.
No dependency was added: SciPy was already installed.

The comparison covers unsorted inputs, boundary values, ties and one hypothesis.
It also uses the 15 published TAPS p-values reproduced in SciPy's example,
attributed there to Neuhaus et al. (1992), *Improved thrombolysis in acute
myocardial infarction with front-loaded administration of alteplase*.
For those inputs, the independent BY minimum is `0.004977343489843491`.
SciPy displays a BH adjustment in that example; this test deliberately requests
BY to match this project's existing method. No numerical assertion was deleted.

The DSR value `0.10148500228858098`, CSCV value `2/3` and original BY value `1/12`
in `test_issue928_2_published_method_numeric_references` are **hand-derived**
oracles. Naming published methods does not turn these into published worked
examples or independent reference-implementation comparisons. DSR/CSCV parity
acceptance remains open pending an identified, inspectable reference/fixture;
no claim of independent confirmation is made. The no-network constraint was
honoured. There was no golden/parity fixture edit or new statistical engine.

## Split caller audit and defaults

Search: `rg -n 'build_walk_forward_splits' src tests -g '*.py'`.

| Caller/export inspected | Existing contract retained |
| --- | --- |
| `validation.protocol._evaluate_trials` | Explicit `strict_label_purge=True`; reused holdouts use `reserve_final_test=False`. |
| `features.training_centre.LocalTrainingRegistry.evaluate_validation_trials` | Explicit strict pre-check over date groups before retaining/scoring. |
| `validation.optimisation` tuning proposal | Explicit `strict_label_purge=False`; legacy tuning/evaluation windows retained. |
| `validation.__init__` | Re-export of the same protocol helper; no additional calculation. |
| `tests/test_validation_protocol.py` | Omitted flag uses legacy default; minimum-sample and window assertions passed. |
| `tests/test_bug_issue928.py` | Strict inference boundary tests and explicit/default legacy compatibility assertions passed on the correction base. |
| `features.forecast_lab` internal evaluation and `tests/test_forecast_lab.py`, `tests/test_forecast_calibration.py` | Separate existing date-based helper, minimum training dates 3/test dates 1; not the protocol helper, unchanged. |
| `analysis.decision.rank_validation` | Imports the forecast-lab date helper with explicit 3/1 date settings, unchanged. |

No new numerical default was chosen. Existing conservative defaults remain:
`periods_per_year=None` (DSR unavailable until explicitly declared), no trial
correlation discount, unknown family evidence unavailable, unpaired external
alternatives counted, `strict_label_purge=False` for the public split helper and
strict purge only at inference callers. Label convention remains t+1..t+horizon;
bootstrap block remains `min(max(block_size, horizon), max(1, n // 2))`.
`ValidationSpec` retains 5 splits, test/final sizes 20, horizon 1, embargo 0,
expanding training, no fixed train size, 200 repetitions, block size 5, seed 42.
The existing result types/status literals, score weights and thresholds remain.

## File and authority audit

Changed: `src/etf_cockpit/validation/protocol.py` (two fail-closed predicates),
`src/etf_cockpit/features/training_centre.py` (PBO/FDR explanatory comment),
`tests/test_bug_issue928.py` (promotion regression, ledger regression extension,
independent reference regression and oracle limitation comment),
`docs/architecture/validation-protocol.md` (contract clarification), and this
handoff. The two documentation files are the extra acceptance files.
No earlier work, assertions, fixtures, weights, gate thresholds, schema or
production dependencies were removed or changed. Execution remains disabled;
no broker/provider writes, forbidden directories or named ports were used.

Open: supply the original complete bughunt register and independently identified
DSR/CSCV examples or reference implementation to close BLOCKING 3 and attest to
every original entry. This correction pass stops here with that gap explicit.

## Correction pass 2 — current handoff

The preceding pass-1 record is retained as historical evidence. This section
is the current audit. Exact base/unchanged HEAD:
`a399d1082ff7bc48306d96c87341921b51ffb67e`; the worktree was clean at entry.
The configured remote is `Thor2709/etf_ai_cockpit`. The owner's explicit
in-worktree, no-network, no-commit/no-branch instructions override fresh-main
fetch/worktree admission for this bounded correction. No programme, lifecycle,
PR, merge, release or packaged acceptance is claimed.

### Complete register for the four supplied pass-2 findings

| ID | Outcome | Base evidence and current evidence |
| --- | --- | --- |
| BLOCKING 1 | FIXED | `test_issue928_pass2_holdout_dates_survive_cross_experiment_dataset_revisions` failed on the exact base: the revised dataset in a different experiment scored the same final dates as sealed. It now passes: canonical date fingerprints match despite different dataset hashes, renamed holdouts, reversed observations and datetime serialization; every final score is absent on reuse. Missing calendar labels, numeric offsets and legacy audit bindings return unavailable with explicit reasons. |
| BLOCKING 2 | FIXED | `test_issue928_pass2_public_development_evaluation_accepts_41_observations` failed on the exact base with a 44-observation minimum. It now passes: the public development call uses exactly the legacy folds at 41 observations; inference and final scores remain unavailable. The registered call still rejects 41 observations with its strict 44-observation minimum. |
| BLOCKING 3 | DEFERRED | Independently sourced DSR/PBO numerical evidence is unavailable locally; existing hand-derived assertions remain intact and passing. A runtime-attested read-only documentation researcher confirmed only citations and hand-derived cases, with no installed independent DSR/PBO implementation. No expected value or provenance was invented. A local published fixture or independently maintained implementation is required. |
| BLOCKING 4 | DEFERRED (original register coverage); FIXED (supplied register/caller/default/final handoff) | `test_issue928_pass2_handoff_records_outcomes_base_evidence_and_checked_callers` failed before this section existed (`IndexError`). The supplied four findings now have explicit outcomes, failing-first evidence, checked callers and defaults. The original complete bughunt register is still absent; absent IDs cannot be reconstructed from test names or certified as rejected. |

### Observed original labels and preserved assertions

These are every explicit numbered issue928 label present in the existing test
file, not a reconstruction of an unavailable original register. REJECTED means
the existing test already passed on this correction base, not that earlier work
is rejected or that a broader unseen finding has been disproved.

| Observed ID | Outcome on this correction base | Base test evidence |
| --- | --- | --- |
| issue928_1 | REJECTED (test already passed on the base) | `test_issue928_1_chronological_clusters_and_paired_block_reference` |
| issue928_2 | REJECTED (test already passed on the base); independent numerical acceptance DEFERRED | `test_issue928_2_published_method_numeric_references`; all DSR/PBO/BY assertions retained |
| issue928_3 | REJECTED (test already passed on the base) | `test_issue928_3_incomplete_or_misaligned_durable_family_fails_closed` |
| issue928_4 | REJECTED (test already passed on the base); cross-version omission separately FIXED under BLOCKING 1 | `test_issue928_4_caller_flags_cannot_authorize_or_reset_holdout` |
| issue928_8 | REJECTED (test already passed on the base) | `test_issue928_8_single_trial_and_too_small_inference_guards` |

### Commands and evidence

All pytest runs set `ETF_COCKPIT_OPEN_BROWSER=0`, used `-o addopts= -q
--tb=line -p no:cacheprovider`, and ran locally without network or installs.

- Before any production edits, the existing issue file plus the two new runtime
  regressions: `python -m pytest tests/test_bug_issue928.py ...` ->
  **27 passed, 2 failed**, 6.34 s. The original 27 cases (including both promotion
  parameters and SciPy BY) passed. The only failures were BLOCKING 1 and 2.
  Existing sealed-scoring fixtures were given actual calendar dates; assertions
  were preserved. Production modules remained byte-identical to HEAD.
- Before production edits: `python -m pytest tests/test_validation_protocol.py
  tests/test_validation_application.py tests/test_training_centre.py
  tests/test_optimisation.py ...` -> **20 passed**, 4.22 s.
- After the two runtime corrections: those four files plus the issue file ->
  **49 passed**, 12.74 s.
- After extending the same holdout regression to legacy-history unavailability
  and updating affected caller fixtures: those five files plus
  `tests/test_bugfix_t-pit.py tests/test_forecast_lab.py
  tests/test_forecast_calibration.py` -> **104 passed**, 20.42 s.
- The new handoff regression alone failed before documentation edits; its
  subsequent result is recorded in the final response. This is a document
  completeness guard, not invented numerical acceptance evidence.
- Ruff over both changed production modules and the three changed test files,
  and `git diff --check`: passed. No unchanged full-suite or hosted gate was
  rerun. The user's reported prior 1745-pass full suite is supplied evidence,
  not current-diff independently verified acceptance.

### Complete checked-caller list

Searches: `rg -n 'build_walk_forward_splits|evaluate_trials\(' src tests -g
'*.py'` and `rg -n 'evaluate_registered_trials|evaluate_validation_trials|
holdout_id=' tests -g '*.py'`. All discovered call sites below were inspected.

| Checked caller/export | Verified contract |
| --- | --- |
| `validation.protocol._evaluate_trials` | Public unregistered development uses the legacy default; internal registry evaluation ID selects strict splits. Reused windows use `reserve_final_test=False`. Public underscore evidence options remain rejected. |
| `features.training_centre.LocalTrainingRegistry.evaluate_validation_trials` | Strict pre-check before immutable submission; canonical calendar identity and all-experiment reuse audit in the same transaction before scoring. |
| `validation.optimisation.run_walk_forward_tuning` | Explicit `strict_label_purge=False`, existing tuning windows unchanged. |
| `application.validation.evaluate_registered_trials` | Routes only through the registry with an existing run; registered strict behavior retained. |
| `application.validation.build_validation_preview` | Uses the public development-only evaluator; legacy split contract restored. |
| `validation.__init__` | Re-exports the existing helper and public evaluator; no alternate calculation. |
| `tests/test_validation_protocol.py` | Default split assertions retained; registered final-score fixture now declares actual dates. |
| `tests/test_bug_issue928.py` | All strict boundary/default legacy assertions retained; one cross-experiment regression and one 41-observation regression added; sealed-scoring fixtures declare dates. |
| `tests/test_training_centre.py` | Development-only public report at 20 observations, complete retained trial assertions unchanged. |
| `tests/test_bugfix_t-pit.py` | Public missing-baseline call unchanged; registered final-score fixture now declares actual dates, all assertions retained. |
| `features.forecast_lab.build_forecast_lab_report` | Uses the separate existing date-based helper with default three training dates/one test date; unchanged. |
| `analysis.decision.rank_validation.evaluate_rank_validation` | Uses forecast-lab's helper with explicit three/one settings; unchanged. |
| `tests/test_forecast_lab.py` | Separate forecast-lab helper default/chronological assertions unchanged and passing. |
| `tests/test_forecast_calibration.py` | Separate forecast-lab helper and out-of-fold provenance assertions unchanged and passing. |

### Independent numerical-source audit

The named `documentation_researcher` ran with attested `gpt-5.6-luna`, high
reasoning, this worktree, and a read-only assignment. Runtime attestation reported
`V2_RUNTIME_ATTESTATION_PROVEN`. Inspected references: the issue test file,
`docs/architecture/validation-protocol.md`, the pass-1 handoff and `REPORT.md`.
The root independently confirmed the original cases' hand-derived qualification
and the absence of independent fixture locators in the scoped source/documents.
Installed SciPy 1.18.0 supplies independent BY evidence only;
`mlfinlab`, `quantstats`, `empyrical`, and `vectorbt` are not installed.
SciPy `_morestats.py` source SHA-256:
`cd9e4918f2b63299bcaa439496dfc1111478640f0310d64832cfa38d42c2d305`.
No paper citation alone was counted as numerical evidence. A local source and
the original register were requested asynchronously; neither was supplied at
the time this record was written. No network fallback was attempted.

### DEFAULTS and OPEN

DEFAULTS: holdout date overlap consumes authority conservatively across the
entire local registry, even across datasets/instruments/experiments. Row offsets
are insufficient for sealed identity. No dates or unverifiable historical
bindings yield unavailable with a reason. Dataset-wide/declared-ID consumption
is retained as an additional conservative check. Calendar identity is verified
from supplied observations' canonical date groups; no external provenance
attestation is inferred. Legacy audit rows are retained without migration.
Strict splits remain registered-only; public split/evaluation development
defaults retain `horizon - 1`, the old sample minimum and reserved tail.
No score weights, thresholds, statistical defaults or dependencies changed;
`execution_allowed=false` remains enforced. No earlier assertions were deleted.

OPEN: independently sourced DSR/PBO inputs/expected values with inspectable
provenance, and the complete original bughunt register. Consequently BLOCKING 3
and the original-register part of BLOCKING 4 remain deferred. Linux/Windows
packaged gates and full formal product acceptance are outside this offline,
uncommitted correction handoff; this pass does not claim the train complete.
