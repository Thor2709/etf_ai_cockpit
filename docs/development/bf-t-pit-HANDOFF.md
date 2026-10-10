# T-PIT handoff

TASK_ID: T-PIT
MODEL/EFFORT: model=gpt-6-luna effort=xhigh
STATUS: partial; 17 IDs fixed and P07-N011 needs a page-renderer decision. No commit was made because validation is not green.

## Per-ID status

- CHAT-P03-N002: fixed; FX quote date and knowledge cutoff are separate.
- CHAT-P08-N005: fixed; promotion compares final scores with the baseline final score.
- P01-N005: fixed; future-dated FX quotes are rejected.
- P03-N001: fixed; ETF price history is bounded by `as_of`.
- P03-N002: fixed; quotes after the cutoff are excluded.
- P03-N003: fixed; untyped non-EUR quote values remain unavailable with `quote_currency_not_eur`.
- P03-N004: fixed; equal-known-time periods use a deterministic source rank/source/reference key.
- P03-N008: fixed; the second universe pass uses each instrument's stored analyst row.
- P03-N009: fixed; cache keys include price-frame content and full record representations; unhashable inputs bypass caching.
- P03-N010: fixed; statement availability compares UTC timestamps and treats date-only cutoffs as end of day.
- P03-N011: fixed; no-data reasons use only snapshots known by the decision time.
- P04-N001: fixed; availability and intraday decision timestamps retain their time.
- P04-N002: fixed; benchmark selection uses the last row in `(start, end]`.
- P04-N003: fixed; unknown embargo timestamps count as overlaps with `embargo_unknown`.
- P04-N010: fixed; missing or over-age forecasts add `forecast_stale`.
- P04-N012: fixed; signal rows receive per-instrument price freshness and missing report data stays unknown.
- P04-N014: fixed; calibration and forecast counts share the as-of-bounded forecast frame.
- P07-N011: partial/escalated; vintage selection, target dates, close anchoring and `forecast_note` are implemented. The stock research page must render `view.forecast_note`; `src/etf_cockpit/app/pages/stock_research.py` is outside the write set. Proposed change: show that note in the empty forecast panel.

## Tests and validation

- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-pit.py`: 18 passed.
- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-pit.py tests/ui/test_page_stock_research.py`: 25 passed after the P07 vintage assertions were added.
- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_issue_0112_product_review_correction.py`: 101 passed.
- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-pit.py tests/test_fx.py tests/test_fund_analysis.py tests/test_stock_metrics.py tests/test_stock_evidence.py tests/test_stock_store.py tests/test_statement_normalisation.py tests/test_feature_store.py tests/test_forecast_uncertainty.py tests/test_canonical_scoring.py tests/test_coverage_audit.py tests/test_validation_protocol.py`: 117 passed, 1 failed. Existing failure: `test_fundamentals_surface_exposes_reported_and_restated_statement_history` expects `statement_history` in `_render_evidence_section`; that UI source is unchanged and outside this packet's bug rows/write set.
- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_etf_economics.py`: collection failed on two attempts. The parametrized fixture's temporary-store cleanup hit `FileNotFoundError` under `logs/pytest_system_tmp` followed by `PermissionError`; 0 tests ran. The same failure fingerprint repeated, so this test path was not retried again.
- The required module bundle also stopped at that `test_etf_economics.py` collection error. A broader follow-up exceeded the command session and ended with exit `-1`; it supplied no validation result.

The existing assertions updated were `tests/test_canonical_scoring.py` (missing freshness now leaves the legacy score unavailable) and `tests/ui/test_page_stock_research.py` (undated forecasts remain unavailable). Both changes strengthen the new fail-closed behavior.

## Files changed

- `src/etf_cockpit/analysis/fund_analysis.py`
- `src/etf_cockpit/analysis/stock_metrics.py`
- `src/etf_cockpit/analysis/stock_universe.py`
- `src/etf_cockpit/application/signal_service.py`
- `src/etf_cockpit/application/ui_views/stock_research.py`
- `src/etf_cockpit/data/fx_data.py`
- `src/etf_cockpit/data/statement_normalisation.py`
- `src/etf_cockpit/data/stock_fundamentals.py`
- `src/etf_cockpit/features/etf_economics.py`
- `src/etf_cockpit/features/feature_store.py`
- `src/etf_cockpit/models/coverage_audit.py`
- `src/etf_cockpit/models/uncertainty.py`
- `src/etf_cockpit/signals/canonical_scoring.py`
- `src/etf_cockpit/validation/protocol.py`
- `tests/test_bugfix_t-pit.py`
- `tests/test_canonical_scoring.py`
- `tests/ui/test_page_stock_research.py`
- `docs/development/bf-t-pit-HANDOFF.md`

NEEDS_OPUS_DECISION: P07-N011 page rendering in `src/etf_cockpit/app/pages/stock_research.py` is outside the write set. Validation is also blocked by the existing statement UI assertion and repeatable temporary-directory cleanup failure described above.

## Correction pass

Cause (both tests): P04-N012 (`canonical_scoring.py`) no longer derives `price_freshness="ok"` from a non-empty decision date; the adapter reads `row["price_freshness"]` and defaults to `unknown` (ineligible, composite `None`). Both tests supplied only a decision date, so they pinned exactly the bug the plan row fixes.

Fix: source code unchanged (the planned fix stays). Each test now asserts both halves with equally strict checks: a row without freshness gives `legacy_composite_raw is None`; the same row with `price_freshness="ok"` keeps the original expected value.
- `tests/bughunt/test_repro_s3.py::test_s3_07_baseline_ensemble_weight_is_preserved`: fresh row -> 0.5 (baseline weight preserved), unknown -> None.
- `tests/test_scoring_pit_and_policy_fixes.py::test_baseline_weight_is_redistributed_from_unavailable_models`: fresh row -> 0.375 (timesfm 0.25 split 50/50), unknown -> None.

Result: both tests and `tests/test_bugfix_t-pit.py` pass (20 passed). No goldens touched.
