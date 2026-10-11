# work-X handoff (Forecast Lab D/E/P/R + CI items)

CHANGES
- D: Lab MASE = mean of |err| / models.calibration._mase_scale(price series, horizon) per instrument+horizon (row-order stable, promotion definition, read-only import). New `mase_method` column; `mae` stays the unscaled MAE. Old `_naive_scale` removed.
- E: rows carry `evidence_basis` = `retrospective_date_grouped` (else `ungrouped`); `out_of_fold` removed from outcome output. Frame still gets the legacy `out_of_fold` bool only because models/calibration.py reads it (not editable here). `normalise_evidence_basis()` maps old artifacts. Notes/UI text no longer claim out-of-sample.
- P: page shows forecast values via expm1 (`_simple_return_text`); log 0.10 -> +10.52%.
- R: insight reworded ("showed lower observed MAE ... limited sample ... not statistically tested").
- CI: test_work_h_toto torch-free (importorskip on the one real-torch test, fake torch in loader test); programme manifest regenerated.

TESTS: tests/test_work_x_forecast_lab.py (4). Validation list + forecast_lab/calibration tests pass.

CI ITEMS: toto torch import fixed; test_flet_startup passes at this head (no change); data-dictionary already up to date; generation-manifest regenerated (--check clean); config.models AttributeError: stale SimpleNamespace fixtures in test_trust_critical_artifacts gained models.shadow_optional_models=False (fixture only).

OPEN
- models/calibration.py should read `evidence_basis` and then drop the legacy `out_of_fold` bool (other train).
- Page "Promotion" note still describes the policy; promotion provenance (C/F01) is another train.
