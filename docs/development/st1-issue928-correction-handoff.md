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
