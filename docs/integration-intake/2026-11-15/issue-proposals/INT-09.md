# INT-09 — Forecast-to-opportunity bridge

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G1`; lane `B`; estimated size `medium`
- Logical prerequisites: `-`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `application/absolute_merit.py; analysis/decision/shadow_run.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Forecast-to-opportunity bridge
- Gate G1 | Priority P1 | Size medium | Depends on: none | Features: F0153, F0107
- Finding: `analysis/decision/opportunity.py:394 _absolute_opportunity_decision` reads `candidate["absolute_merit_evidence"]`; nothing in `src/` builds it. The only caller chain is `analysis/decision/shadow_run.py:114` (`build_opportunity_results`).
- Targets: `application/absolute_merit.py` (new), `analysis/decision/shadow_run.py` (`run_decision_shadow:62`, call at `:114`), `models/forecast_scores.py` (`forecast_return_distributions:447`), `models/calibration.py` (`calibrate_forecast_distribution:101`, `horizon_calibration_scores:1057`), `models/coverage_audit.py`, `portfolio/benchmark_reference.py`, `portfolio/costs.py` (`estimate_execution_cost:195`), `analysis/decision/contracts.py` (`ScoreAuthorityFlags:146`).
- Exact payload the consumer checks (`analysis/decision/opportunity.py:431-660`). Every nested mapping must have `execution_allowed` false or absent (`_execution_disabled:734`). "Source record" = `execution_allowed: False`, `source_hash` (64 lower-case hex), `effective_at`, `known_at` (both not after the decision time), age within `policy.maximum_evidence_age_days` (`_valid_source_record:719`).

| Block | Required fields |
|---|---|
| `benchmark_reference` | source record; `status="available"`; `instrument_id == policy.benchmark_instrument_id`; `benchmark_id`, `benchmark_version`, `benchmark_digest` equal to the VWCE anchor (`vwce_anchor.digest()`); `source_hash` in `vwce_anchor.source_hashes`; `currency == policy.base_currency`; `total_return > -1`; `horizon` in the policy horizons and inside the anchor's horizon bounds; `unit="decimal_fraction"` |
| `forecast` | source record; `status="available"`; `horizon` equal to the benchmark horizon; `expected_total_return > -1`; `unit="decimal_fraction"`; `currency` (ISO code); `calibration_status="calibrated"`; `uncertainty_margin` in `[0, 1)` |
| `cost_model` | source record; `status="available"`; `currency == policy.base_currency`; `horizon`; `unit="decimal_fraction"`; `candidate_acquisition_cost` and `benchmark_acquisition_cost` in `[0, 1)` |
| `fx_conversion` (only when the forecast currency is not the base currency) | source record; `status="available"`; `from_currency`, `to_currency`; `return_convention="eur_value_per_candidate_currency"`; `horizon`; `unit="decimal_fraction"`; `return > -1` |
| `previous_decision` (optional) | source record; `status`, `instrument_id`, `horizon`, `config_hash == policy.checksum`, `state` |
| `position` (optional) | `held` and the fields read at `analysis/decision/opportunity.py:647-660`; read them there before coding |

  The candidate (or its assessment) must also carry `score_authority: ScoreAuthorityFlags` with `forecast_calibrated=True`; otherwise the result is `RETURN_NOT_CALIBRATED`.
- Definitions:
  - `expected_total_return`: mean of the calibrated distribution over the horizon, after conversion of log-return quantiles to simple returns (`exp(q) - 1`); crossing quantiles are sorted and flagged; the conversion method is stored in the record.
  - `uncertainty_margin`: not an interval half-width. It is the empirical quantile (level in `configs/decision_opportunity_v1.yaml`) of `|realised - expected|` from matured out-of-sample forecasts of the same model, horizon and asset class. Fewer matured residuals than the configured minimum gives `status="unavailable"`.
  - `forecast_calibrated` is set to true only when the out-of-sample coverage check for that model and horizon passes (`models/coverage_audit.py`); the bridge never sets it from in-sample data.
  - Horizons: `20_sessions`, `60_sessions`. Unit, horizon and currency are explicit in every block.
- Acceptance (through `run_decision_shadow`, not only the builder): `CANDIDATE_BUY` above the hurdle; `POSITIVE_BUT_INSUFFICIENT_MARGIN` below it; `RETURN_NOT_CALIBRATED` when `forecast_calibrated` is false; `ECONOMIC_RISK_VETO` when a gate reason exists; `HOLD_NO_TRADE` when `previous_decision.state` is `HOLD_NO_TRADE`, `position.held` is true and the net excess is inside the hysteresis band (`analysis/decision/opportunity.py:645-651`); a non-EUR forecast without `fx_conversion` gives `FX_CONVERSION_UNAVAILABLE`.

## Gate G2 - dependency intake and solver contract
