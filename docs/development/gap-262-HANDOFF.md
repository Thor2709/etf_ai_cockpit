# Gap #262 handoff: bounded parameter optimisation

DONE
- `validation/tuning_registry.py` + `configs/tuning_v1.yaml`: 16 knobs (ETF attractiveness 4, ETF expected-return 3, ensemble weights 9) with bounds/step from config; current value read live from `score_engine_v3.yaml` / `model_settings.yaml` (never written); group totals preserved; missing/out-of-bounds source value raises `TuningRegistryError` (-> unavailable).
- `optimisation.py` extended (no parallel engine): mid-trial median pruning via `context.report`, cooperative time limit at each report, seeded local refinement (`refine_after`), `patience` stop, injectable `clock`; additive `intermediate` key on trial records (no schema migration; old records byte-identical).
- `run_walk_forward_tuning`: reuses `build_walk_forward_splits` (tune window, purge, later evaluation window, reserved final tail never touched); min-sample, change-penalty, block-win and margin guards; candidate must beat current out of sample else `keep_current`; failures give `unavailable` with reason; pretraining-cutoff flags (`PRETRAINING_CUTOFFS`; unknown cutoff = flagged); synthetic data is `synthetic_machinery_only`, never promotion evidence.
- `scripts/run_tuning.py`: writes `tuning_proposal.json` + `tuning_report.md` only; refuses an output dir inside the settings directory.

CORRECTION PASS
- Retained trials carry a `search_fingerprint` bound to data dates, evaluator identity (mandatory for market/private data), registry, guards and penalty; mismatch -> unavailable. Failed/pruned baselines never supply a baseline score. Out-of-sample judging shares the run deadline (search uses 80%) and honours cancellation. Output dirs under `.owner-root`, `models`, `configs`, the settings dir or `Desktop/Trading App` are refused before any write. Registry/defaults validate fully (`TuningRegistryError`). Out-of-sample errors export the exception class only.

SAFE_POINT
- Real-data walk-forward is not wired (`--mode walk-forward` exits 2, unavailable): needs a point-in-time objective over real score/forecast history and owner-defined acceptance. "Then new data" stage not built.
- Hard resource limits (process isolation, native memory, restart limits) not built: limits are cooperative (checked between trials and at `report`); a hung objective that never reports cannot be interrupted. Owner decides hard vs cooperative.
- No config knob exists for the final-score group blend; add it to the source config first, then to the registry.

DEFAULTS (all in `configs/tuning_v1.yaml`)
- Bounds current +/-0.10 (clamped to [0,1]), step 0.05. 60 trials, 60 s, 256 MB, seed 42, refine after 8, patience 25, prune warmup 5.
- Guards: >=250 tuning samples, >=60 evaluation samples, 4 blocks, >=75% blocks must win, change penalty 0.02 per unit mean normalised move, extra margin 0. Split: eval 120, horizon 20, embargo 0, final tail 60.

OPEN
- Whether optional models with unpublished cutoffs (timesfm 2.5, toto 2.0) should block promotion evidence (current: flagged, not eligible unless the caller supplies a cutoff).
