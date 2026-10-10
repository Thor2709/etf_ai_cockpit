# T-NUM implementation handoff

## Per-ID result

- CHAT-P03-N007 — fixed: reject non-finite and negative peer market caps.
- CHAT-P05-N003 — fixed: sort event sequences numerically.
- CHAT-P05-N004 — fixed: conflicting duplicate historical returns become unavailable with a warning.
- CHAT-P05-N005 — fixed: XIRR without a root is unavailable.
- CHAT-P05-N006 — fixed: reject non-finite liquidity volume.
- P01-N001 — fixed: reject non-finite market-adjustment closes.
- P01-N002 — fixed: quarantine unmatched action dates with their action ID.
- P01-N003 — fixed: coerce invalid provider and validation dates to NaT.
- P01-N004 — fixed: share leap-day-safe year subtraction across all six call sites.
- P02-N005 — fixed: reject non-finite evidence scores.
- P02-N006 — fixed: restrict freshness and quality values to producer-backed allowlists.
- P03-N005 — fixed: reject missing or non-positive order-book prices.
- P04-N004 — fixed: return no baseline forecast with fewer than 20 finite log returns.
- P04-N005 — fixed: calculate benchmark returns with the daily log-return helper.
- P04-N006 — fixed: choose the latest forecast row by date and run ID.
- P04-N007 — fixed: preserve explicit zero forecasts and fall back for NaN.
- P04-N008 — fixed: reject non-finite canonical score weights.
- P04-N009 — fixed: ignore duplicate components and report a warning.
- P04-N011 — fixed: keep trend indicators unavailable until their SMA exists.
- P04-N015 — fixed: count distinct coverage dates.
- P04-N016 — fixed: normalize quality-momentum evidence after filtering to requested IDs.
- P05-N001 — fixed: consume shared event liquidity capacity in deterministic order.
- P05-N002 — fixed: reject invalid backtest prices with instrument and date.
- P05-N004 — fixed: block sells exceeding holdings after open sell orders.
- P05-N005 — fixed: validate transaction costs at backtest entry.
- P05-N006 — fixed: validate rebalance frequency and initial portfolio value at entry.
- P05-N007 — fixed: reject zero-price market events.
- P06-N011 — fixed: display non-finite score-bar values as unavailable.

## Tests and validation

- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-num.py` — 28 passed, 0 failed.
- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_forecast_distributions.py tests/test_forecast_uncertainty.py` — 17 passed, 0 failed.
- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_event_backtest.py tests/test_pre_trade_controls.py` — 17 passed, 0 failed.
- `python -m pytest -q --tb=line -p no:cacheprovider tests/test_backtest_costs.py tests/test_backtest_holdings_accounting.py` — 6 passed, 0 failed.
- Existing module tests were run in focused groups. Failures remain:
  - `python -m pytest -q --tb=line -p no:cacheprovider tests/test_backtest_lab.py` — 4 failures: `test_backtest_service_reuses_quality_momentum_cache_after_persistence`, `test_backtest_service_reuses_mixed_availability_integer_diagnostics`, `test_backtest_service_round_trips_genuinely_unavailable_operational_rows`, and `test_backtest_cache_reader_uses_one_complete_snapshot_under_interleaving`.
  - `python -m pytest -q --tb=line -p no:cacheprovider tests/test_forecast_distributions.py tests/test_forecast_uncertainty.py tests/test_settings_run_publication.py` — 1 failure: `test_feature_service_does_not_use_first_enabled_instrument_as_benchmark`.
  - `python -m pytest -q --tb=line -p no:cacheprovider tests/test_stress_testing.py tests/test_attribution.py tests/test_robust_risk.py` — 1 failure: `test_risk_workspace_surfaces_robust_risk_evidence`.
  - `python -m pytest -q --tb=line -p no:cacheprovider tests/test_frontend_design_system.py tests/test_accessibility_contracts.py tests/test_ui_performance_caches.py` — 38 passed, 2 failed: `test_shell_command_palette_filters_and_navigates` and `test_dashboard_summary_cards_are_inherently_responsive`.
- The attempted broad module-linked test run could not complete: one test attempted to write under `logs/pytest_system_tmp` and received `PermissionError`; the rerun without that file exited `-1` without a pytest summary.
- No commit was made because the required validation is not green.

## Files changed

- `src/etf_cockpit/analysis/sparebank/valuation.py`
- `src/etf_cockpit/analysis/stock_peers.py`
- `src/etf_cockpit/app/components/kit/data.py`
- `src/etf_cockpit/application/data_service.py`
- `src/etf_cockpit/application/forecast_service.py`
- `src/etf_cockpit/backtest/engine.py`
- `src/etf_cockpit/backtest/event_engine.py`
- `src/etf_cockpit/core/values.py`
- `src/etf_cockpit/data/evidence_ledger.py`
- `src/etf_cockpit/data/market_adjustments.py`
- `src/etf_cockpit/data/providers.py`
- `src/etf_cockpit/data/stooq_provider.py`
- `src/etf_cockpit/data/tiingo_provider.py`
- `src/etf_cockpit/data/trade_candidate_analysis.py`
- `src/etf_cockpit/data/twelvedata_provider.py`
- `src/etf_cockpit/data/validation.py`
- `src/etf_cockpit/data/yfinance_provider.py`
- `src/etf_cockpit/features/feature_pipeline.py`
- `src/etf_cockpit/models/baseline_models.py`
- `src/etf_cockpit/models/coverage_audit.py`
- `src/etf_cockpit/models/forecast_scores.py`
- `src/etf_cockpit/portfolio/attribution.py`
- `src/etf_cockpit/portfolio/robust_risk.py`
- `src/etf_cockpit/portfolio/stress_testing.py`
- `src/etf_cockpit/signals/canonical_scoring.py`
- `src/etf_cockpit/signals/quality_momentum.py`
- `src/etf_cockpit/signals/scoring.py`
- `src/etf_cockpit/trading/pre_trade_controls.py`
- `tests/test_bugfix_t-num.py`
- `tests/test_settings_run_publication.py` (updated the assertion for the requested log-return behavior)
- `docs/development/bf-t-num-HANDOFF.md`

## NEEDS_OPUS_DECISION

- None.

## Correction pass

| Test | Cause | Fix | Result |
|---|---|---|---|
| `test_friction_edge::test_forecast_return_distribution_aggregates_allowed_model_quantiles` | P04-N006 `_latest_row` sorted by `forecast_date` unconditionally; frames without that column raised `KeyError` | `_latest_row` sorts by whichever of `forecast_date`/`run_id` exist, else keeps row order (`iloc[-1]`); sorted selection for P04-N006 unchanged | pass |
| `test_release_hardening::test_valid_forecast_rows_become_model_score_inputs` | same `KeyError` via `_choose_horizon_row` | same `_latest_row` fix | pass |
| `test_etf_economics::test_non_finite_total_return_values_fail_closed` | pinned exactly P01-N001: built evidence from an `inf` close via `apply_total_return_adjustments`, which the old gate let through; it now raises at construction. Tampered payloads are rejected earlier still (checksum / bound-artifact checks), so the old "invalid observations" message is unreachable | Assertion updated: `inf`, `-inf` and `NaN` each raise `MarketAdjustmentError` (`non-finite`) when building evidence (equally strict, now also covers `-inf`/`NaN`) | pass |
| `test_issue_0112_...simple_score_disk_reader` | passed on re-run before changes (no failure reproduced) | none | pass |
| `refactor_parity/test_optional_models_golden::test_optional_models_match_golden` | P04-N004 (`< MIN_BASELINE_OBSERVATIONS` finite returns -> `[]`): `baseline_forecast` on an empty series now returns 0 rows instead of 4 zero-edge `ok` rows | NOT fixed here (golden may not be regenerated). Only difference: `$.baseline_forecast.empty_series: length 4 != 0` | still fails; **record for final integration: regenerate `optional_models` golden, expecting `empty_series == []`** |
