# Work-H handoff
TOTO STATUS: toto-2 2.0.0 (toto2.Toto2Model) wired as shadow model; run_forecasts 2026-10-09: 80 ok, 1 unavailable (RABO.AS: no finite adjusted log-return history); 60-day horizon, model toto_2_0_1b.
DISABLED-SAFE: missing toto2 / weights -> unavailable with reason; Toto 1 (toto-ts) only -> unavailable "Toto 1 architecture"; loader errors fail once (no non-local retry); nonfinite output rejected.
FIXES: per-instrument finite-history + min-observation checks; non-positive/inf prices masked; loader no longer retries without local_files_only; quantile shape must be exactly 9.
GPU/RUNTIME: RTX 5070 Laptop GPU, device=auto -> cuda; real 1B inference cuda ok (34.6s incl. cold load) and cpu ok (16.9s); same expected_return to 1e-6. Full run 88s for all models.
SHADOW: 80 toto rows model_allowed_in_score=false, contamination_status=possibly_leaked, promotion_evidence_allowed=false, execution_allowed=false.
SHADOW PROOF: scoreboard (8 score axes) and signals (score/action/research/portfolio states) for 81 instruments exactly equal before/after (.owner-root/work-h-evidence/{scoreboard,signals}-{before,after}.csv, scoreboard_compare.py).
TESTS: 5 new tests in tests/test_work_h_toto.py + work-G tests pass; all tests selected by -k "toto or timesfm" pass unchanged.
EVIDENCE: .owner-root/work-h-evidence/ (owner-run.log, device-proof.json, before/after CSVs).
NEEDS_OPUS_DECISION: Toto horizon q10/q90 sum per-step marginal quantiles (pinned by tests/test_model_shapes.py::test_toto_quantiles_convert_daily_return_paths_to_horizon_returns), so 60-day bands are ~10x too wide (q10 -0.5..-2.9, median forecast_vol 1.9 vs ~0.17 for TimesFM). Not changed (test must stay unchanged); harmless while shadow-only, but fix (root-sum-of-squares of step deviations) before Toto is ever scored.
