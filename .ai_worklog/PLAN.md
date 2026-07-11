# Plan

## Product Objective

Build and harden the local ETF AI Portfolio Cockpit described by `ETF_AI_Portfolio_Cockpit_Master_Spec.md`, with the newer audit-first addendum taking precedence where it is stricter. The app is a fully local Windows desktop-style decision-support cockpit, not a broker bot and not a financial adviser.

The cockpit must ingest local portfolio, price, ETF, factsheet, holdings, news/thesis and optional model data; validate it; calculate deterministic features and signals; run hard risk gates; optionally add local model evidence; and produce transparent manual-review outputs. Normal use must not require internet access or API keys.

## Core Behaviour Rules

- No automatic broker execution.
- No invented market, ETF, holdings, news, FX or model data.
- No silent forward-filling of important missing values.
- No LLM-calculated portfolio metrics or LLM-authorised trades.
- Hard validation and risk gates run before actionable signal ranking.
- Weak, stale, incomplete or conflicted evidence defaults to `no_trade` or `manual_review`.
- Every final action must include `blocked_by` and a human-readable `reason_full`.
- Unavailable TimesFM, Toto or local LLM models must produce null forecasts and zero direct score contribution.
- All actions are advisory. The newer addendum limits release-facing actions to `hold`, `no_trade`, `add_candidate`, `trim_candidate` and `manual_review`; older master-spec `buy`, `add`, `trim`, `sell` language may remain only where explicitly marked as legacy/internal compatibility.

## Target Architecture

1. Config
   - `configs/universe.yaml` defines ETF identity, ticker/ISIN, role, region, sector, currency and ETF caps.
   - `configs/portfolio_targets.yaml` defines target weights, cash target and bands.
   - `configs/risk_limits.yaml` defines concentration, turnover, drawdown, trade-size and edge-to-cost limits.
   - `configs/costs.yaml` defines commission, spread, FX, slippage and minimum useful trade assumptions.
   - `configs/model_settings.yaml` defines disabled/mock/live model modes.
   - `configs/data_providers.yaml` must define local/manual and optional HTTP/API provider settings without committed secrets.

2. Local Storage
   - Preferred layout:
     - `data/raw/broker/`
     - `data/raw/prices/`
     - `data/raw/fx/`
     - `data/raw/etf_factsheets/`
     - `data/raw/etf_holdings/`
     - `data/raw/manual_news/`
     - `data/raw/macro/`
     - `data/clean/prices.parquet`
     - `data/clean/fx.parquet`
     - `data/clean/holdings.parquet`
     - `data/clean/etf_metadata.parquet`
     - `data/derived/features.parquet`
     - `data/derived/signals.parquet`
     - `data/derived/risk.parquet`
     - `data/derived/forecasts.parquet`
     - `data/snapshots/`
     - `data/audit_packets/`
     - `data/reports/`
   - Existing `data/validated`, `data/features`, `data/backtests` and `data/chatgpt_exports` are compatibility locations until callers are migrated.
   - Raw imports are immutable and checksumed before clean data replaces the current snapshot.

3. Data Ingestion
   - Manual/local file provider supports CSV, XLSX, JSON and Parquet imports where installed dependencies permit.
   - Generic HTTP/API provider stub is configurable but safe when no provider/API key exists.
   - Required provider interface:
     - `fetch_prices(symbols, start_date, end_date)`
     - `fetch_fx(pairs, start_date, end_date)`
     - `fetch_etf_metadata(isins)`
     - `fetch_etf_holdings(isins)`
   - API keys are never logged, exported or committed.
   - `Renew data` workflow exposes:
     - import local files;
     - configured API provider;
     - dry-run validation of current local data.

4. Provenance And Freshness
   - Every ingested dataset needs metadata:
     - `source_name`
     - `source_type`
     - `as_of_date`
     - `ingested_at`
     - `currency`
     - `timezone`
     - `provider_or_manual_source`
     - `checksum`
     - `staleness_status`
   - Freshness tiers:
     - Daily prices: OK <= 3 trading days, warning 4-10, block > 10.
     - ETF factsheets: OK <= 45 calendar days, warning 46-120, block > 120.
     - ETF holdings: OK <= 60 calendar days, warning 61-180, block > 180.
     - Manual news/thesis notes: dated evidence only, never trade authority.

5. Deterministic Calculations
   - Daily log return: `ln(adjusted_close_t / adjusted_close_t-1)`.
   - Horizon log return/momentum: `ln(adjusted_close_t / adjusted_close_t-n)` for 20/60/120/180 trading days.
   - Trend: current adjusted close versus 50/100/200-day simple moving averages, plus 100/200-day slope.
   - Realised volatility: standard deviation of daily log returns over 20/60/120 windows annualised by `sqrt(252)`.
   - EWMA volatility: exponentially weighted daily log-return volatility annualised by `sqrt(252)`.
   - Drawdown: `price / cumulative_max(price) - 1`; max drawdown is the rolling or full-period minimum drawdown.
   - Drift: `current_weight - target_weight`; rebalance pressure is `(target_weight - current_weight) / hard_band`, clipped to [-1, 1].
   - Expected edge: deterministic blend of 60/120-day momentum and relative strength, converted to bps before comparing with costs.
   - Cost model: commission, bid/ask spread, FX cost, slippage and minimum useful trade value.
   - Edge-to-cost: `abs(expected_edge_bps) / estimated_cost_bps`; no trade unless ratio >= configured threshold and trade value >= minimum.

6. Risk-Gate Order
   - critical data quality;
   - stale data;
   - target-policy validity;
   - portfolio concentration;
   - currency/region/sector/theme exposure;
   - liquidity/cost gate;
   - deterministic signal;
   - model confirmation;
   - final advisory action.

7. Signal Table Fields
   - `raw_signal_score`
   - `short_term_alert_score`
   - `medium_term_signal_score`
   - `rebalance_signal`
   - `risk_signal`
   - `current_weight`
   - `target_weight`
   - `drift_eur`
   - `drift_percent`
   - `expected_edge_bps`
   - `estimated_cost_bps`
   - `edge_to_cost_ratio`
   - `min_edge_to_cost_ratio`
   - `trade_value_eur`
   - `min_trade_value_eur`
   - `blocked_by`
   - `final_action`
   - `reason_full`

8. Model Evidence
   - Baseline model is deterministic and available.
   - TimesFM/Toto are optional local adapters.
   - If `model_status != ok`, `expected_return`, `q10`, `q50`, `q90` must be null.
   - Unavailable models must have:
     - `model_allowed_in_score = false`
     - `is_fallback = false`
     - `fallback_model = baseline` where relevant
     - `reason_unavailable`
     - null OOS metrics unless measured
     - `calibration_status`
   - UI text:
     - `Model evidence: baseline only` when optional models are unavailable.
     - `Independent AI confirmation available` only when real validated output exists.

9. Backtesting
   - Use total-return/adjusted series where available.
   - Avoid look-ahead and same-bar execution.
   - Trade on next available period after signal.
   - Include transaction and FX costs, turnover, drawdown and benchmark comparison.
   - Add honest quality fields:
     - `n_walk_forward_periods`
     - `train_periods`
     - `validation_periods`
     - `test_periods`
     - `trade_count`
     - `average_trade_eur`
     - `median_holding_period_days`
     - `turnover_annualised`
     - `max_drawdown`
     - `worst_12m_return`
     - `probabilistic_sharpe`
     - `deflated_sharpe`
     - `pbo_probability_backtest_overfitting`
     - `parameter_sensitivity_status`
   - If these diagnostics are missing or weak, label quality `low`.

10. LLM Audit
   - Export audit packet ZIP with portfolio summary, signal table, ETF metrics, model forecasts, backtest summary, validation report, risk-gate report, manual thesis/news notes, external audit questions and response schema.
   - Import external audit response as a dated non-executable note:
     - `source`
     - `imported_at`
     - `as_of_date`
     - `confidence`
     - `executable_authority = false`
   - External audit never directly changes signal actions.

## UI Target

- Dashboard: total portfolio value, snapshot date, freshness banner, risk-gate status, model status, final mode and ranked signals.
- Signals: full signal table with reason text and blocked gates.
- Risk: concentration, asset-class, region, currency, sector/theme exposure, correlation and drawdown contribution.
- Models/Data: imported datasets, source, as-of date, staleness, checksum, model availability and model scoring eligibility.
- Renew data: visible workflow with local import, API placeholder and dry-run validation.
- Backtests: benchmark comparison, walk-forward periods, costs, turnover, drawdown and overfitting diagnostics.
- Audit: validation report, export audit packet and import external audit response.
- Settings: target weights, risk limits, cost assumptions, API provider fields and secret placeholders.

## Current Implementation Status

- Implemented: `configs/data_providers.yaml`, `.env.example` provider placeholders and secret redaction.
- Implemented: provider abstraction for prices, FX, ETF metadata and ETF holdings, with a working manual/local file provider and safe generic HTTP/API placeholder.
- Implemented: optional yfinance price provider for EUR Yahoo symbols. It normalises Yahoo OHLCV/adjusted-close data into the cockpit price schema, supports configured `symbols_map`, and stays out of the main price store unless the configured-provider workflow validates and commits it.
- Implemented: Settings UI can save provider name/base URL and local API keys. API keys are loaded from `.env`, redacted in config views and kept out of YAML/logs/exports.
- Implemented: visible `Renew data` workflow with local file picker, no-provider API branch and dry-run validation branch.
- Implemented: validated price imports store a raw copy, snapshot the previous clean prices, write `data/clean/prices.parquet`, update the compatibility price store and refresh the snapshot.
- Implemented: `Renew data` can roll back to the latest previous clean price snapshot and snapshots the replaced current store before restoring.
- Implemented: preferred `data/raw`, `data/clean`, `data/derived`, `data/snapshots`, `data/audit_packets` and `data/reports` directories while preserving legacy compatibility folders.
- Implemented: dataset metadata model, checksums, price provenance display and price freshness tiers.
- Implemented: portfolio-holdings provenance, holdings/cash reconciliation, current concentration gate and holdings freshness tiering.
- Implemented: target-policy validation. The sample `WORLD_CORE` 42% target and current 45.5% weight both block trading against the 35% cap.
- Implemented: critical validation failures force `trading_allowed=false` and final `manual_review` actions.
- Implemented: release-facing advisory actions (`add_candidate`, `trim_candidate`, `hold`, `no_trade`, `manual_review`) while preserving legacy internal compatibility.
- Implemented: expanded signal table fields, reason text, `blocked_by`, edge/cost and drift metrics.
- Implemented: unavailable TimesFM/Toto forecasts expose null return/quantile outputs and zero score eligibility.
- Implemented: backtest no-silent-forward-fill, next-period execution scheduling, signal/execution dates, deterministic local estimates for probabilistic Sharpe/deflated Sharpe/PBO/parameter sensitivity, and honest low/medium quality labels.
- Implemented: audit export validation/risk-gate reports and non-executable external audit import notes.
- Implemented: dedicated Risk page with exposure limit report, asset-class/region/currency/sector/theme exposure, adjusted-return correlation matrix and drawdown contribution table.
- Implemented: manual thesis/news local import path with strict date/text validation, immutable raw copy, clean Parquet store, previous snapshots, checksums and forced `executable_authority=false`.
- Implemented: ETF factsheet/reference metadata and underlying ETF holdings local import path with date/identifier/weight validation, immutable raw copy, clean Parquet store, previous snapshots, checksums and freshness status.
- Implemented: FX local import path with explicit dated currency pairs, positive rates, immutable raw copy, clean Parquet store, previous snapshots, checksums and freshness status.
- Implemented: non-base-currency portfolio holdings require a dated FX rate into the configured base currency before `market_value_eur` can reconcile; missing or stale FX blocks trading.
- Implemented: `Renew data` now separates `Import prices`, `Import manual notes`, `Import ETF factsheets`, `Import ETF holdings` and `Import FX rates`.
- Implemented: audit export now includes imported manual thesis/news notes, ETF reference-data inventory and FX inventory instead of placeholders, with explicit non-executable authority wording.
- Implemented: new audit exports default to `data/audit_packets/audit_packet_YYYY-MM-DD.zip`; older ChatGPT-named scripts/methods remain compatibility aliases.
- Implemented: optional LM Studio local LLM audit commentary layer configured by `configs/local_llm.yaml`; it is invoked only from the Audit page, schema-validates output, saves commentary under `data/reports`, and cannot alter signals or risk gates. Current live probe reaches `http://localhost:1234/v1` and auto-selects `qwen3.6-27b` when no explicit model is configured.
- Implemented: non-executable manual trade proposal reports. Dashboard action writes an advisory JSON report only when risk gates allow candidate rows; blocked states produce a blocked report with human-readable reasons and no broker execution.
- Implemented: separate yfinance trade-candidate analysis workflow for user-supplied Yahoo tickers outside the configured ETF universe. Reports are written under `data/reports` and are price-only, non-executable evidence.
- Implemented: Data & Models page now shows model status, dataset provenance, ETF reference-data/FX inventory, manual thesis/news status and validation issues in the first desktop viewport.
- Implemented: Risk page uses imported ETF holdings, when present, to show portfolio-weighted underlying sector/region/currency exposure; otherwise it shows an explicit no-holdings-imported state.
- Implemented: packaged Windows local web launch through `ETF_AI_Cockpit.bat`, avoiding the blank native Flet renderer on this machine.
- Implemented: packaged direct routes/deep links preserve the initial route instead of redirecting to `/`, so pages such as `/backtests` render correctly on refresh or direct browser entry.
- Implemented: launchers set `ETF_COCKPIT_ROOT`, and the app now prefers that root or the launcher working directory over bundled `_internal` configs so reports, logs and imported data resolve to the visible app folder.
- Implemented: duplicate launch protection. If the local web server is already running on the configured port, the launcher/app reuses it instead of starting a second process and generating port-binding tracebacks.

## Remaining Confirmed Gaps

- Main local data import workflows now exist for prices, FX, ETF factsheets/reference metadata, underlying ETF holdings and manual thesis/news notes. Imported ETF holdings feed Risk page underlying exposure, and imported FX is enforced for cross-currency portfolio-holdings reconciliation.
- Manual thesis/news import is implemented for dated local evidence notes; it is intentionally non-executable and not part of signal authority.
- The Audit page displays neutral `Export audit packet` and `Import external audit response` controls plus strict-validation notes, but not every audit packet file is exposed as a full dedicated table.
- Local LLM audit commentary is implemented and disabled-safe/offline-safe; current live probe shows LM Studio is not running on `localhost:1234`, which is handled as optional unavailable status.
- Advanced backtest diagnostics are now estimated locally and displayed, but they remain lightweight deterministic diagnostics rather than institutional-grade proof of out-of-sample robustness.
- TimesFM and Toto source archives are extracted and the original ZIPs are copied into `models/source_archives` with checksums documented in `MODEL_ARCHIVE_MANIFEST.md`. Live model inference is not enabled because the supplied archives contain source/reference material, not checkpoint/weight files.
- Implemented: optional live TimesFM 2.5 adapter path based on the Hugging Face Transformers docs for `TimesFm2_5ModelForPrediction` and the `google/timesfm-2.5-200m-transformers` checkpoint. The adapter converts forecast price levels into log-return evidence and only reports available when a compatible package and local weight files exist.
- Implemented: optional live Toto 2.0 adapter path based on the Datadog Toto 2.0 Hugging Face collection/model cards. The adapter supports all five repo IDs (`4m`, `22m`, `313m`, `1B`, `2.5B`), calls `Toto2Model.from_pretrained(...)`, converts quantile return paths into horizon log returns and only reports available when a compatible package and local weight files exist.

## Implementation Tickets

1. Worklog and spec alignment
   - Status: in progress.
   - Expand durable plan, testing matrix, findings and decisions.

2. Provider and storage foundation
   - Add provider config models and example YAML.
   - Add manual/local file provider and generic HTTP provider stub.
   - Add secret redaction and no-provider-safe workflow results.
   - Add preferred storage directories while preserving old paths.

3. Provenance and validation
   - Add dataset metadata/freshness structures.
   - Add checksums for local datasets.
   - Apply price freshness tiers and dataset summary.
   - Add target-policy validation and block/report policy conflicts.
   - Add portfolio-holdings validation for current concentration, cash residual, stale snapshots and value/weight reconciliation.
   - Status: implemented for prices, current portfolio holdings, target policy, manual thesis/news, ETF factsheet/reference metadata, ETF holdings and FX imports.

4. Signal/risk/action hardening
   - Add signal support metrics and no-trade reason fields.
   - Convert release-facing buy/sell to advisory candidates.
   - Enforce manual review for critical validation or target-policy violations.
   - Add cost/edge/min-trade gates and tests.

5. Model metadata
   - Add unavailable-model metadata and tests.
   - Ensure unavailable quantiles remain null and excluded from score.
   - Add optional live TimesFM 2.5 and Toto 2.0 Hugging Face runtime paths that remain local-first and disabled-safe.
   - Status: implemented for disabled/mock/live mode boundaries, local checkpoint gating and forecast-output conversion tests.

6. Backtest quality
   - Remove silent forward-fill risk or make it controlled/reported.
   - Add next-period execution evidence and quality fields.
   - Add backtest quality label and tests.
   - Status: implemented for no silent forward-fill, next-period execution, quality labelling and deterministic local advanced diagnostics.

7. Audit export/import
   - Add validation report, risk-gate report and external-audit import metadata.
   - Ensure imported audit has `executable_authority=false`.
   - Status: implemented for validation/risk-gate reports, imported external audits and imported manual thesis/news notes.

8. UI upgrades
   - Add freshness banner.
   - Add Renew data dialog.
   - Add provider settings fields.
   - Add expanded data/signals/backtest evidence.

9. Verification
   - Run unit/integration tests after each patch.
   - Run source smoke test.
   - Rebuild package if source changes affect packaged app.
   - Validate with browser UI interaction and screenshot.

## Acceptance Criteria

- App starts locally without internet.
- Existing local/sample data loads.
- Renew/Update Data button exists and works for dry-run/no-provider path without crashing.
- Provider abstraction exists and can be configured later.
- Local file import path is implemented and validates before replacement.
- API provider placeholder is safe without API keys.
- Critical validation failure sets `trading_allowed=false` and `manual_review`.
- Unavailable AI models produce null forecasts and no score contribution.
- Risk limits are enforced before actionable candidate signals.
- Every final action has `blocked_by` and `reason_full`.
- Backtest quality is labelled honestly.
- Audit packet ZIP shows data age, validation status, model status, risk violations and final actions.
- Unit tests, smoke tests and browser UI checks pass or remaining external blockers are explicitly logged.

## 2026-06-30 Safetensor Checkpoint Implementation

- Implemented: uploaded model weights are installed under explicit runtime folders:
  - `models/timesfm/timesfm-2.5-200m-transformers/model.safetensors`
  - `models/toto/Toto-2.0-4m/model.safetensors`
  - `models/toto/Toto-2.0-1B/model.safetensors`
- Implemented: root-level safetensors were removed; model weights are ignored by `.gitignore` and are not bundled into `build\flet_dist` or the portable app folder.
- Implemented: TimesFM 2.5 uses the Transformers backend with local `config.json`. The uploaded checkpoint used legacy `mlp.ff0`/`mlp.ff1` tensor names, so the runtime copy was converted to `mlp.fc1`/`mlp.fc2`; the original is preserved as `model.original_ff_keys.safetensors`.
- Implemented: Toto 2.0 defaults to the 4M checkpoint for practical local CPU smoke tests. The 1B checkpoint is installed and visible in diagnostics but not enabled by default.
- Implemented: optional model runtime dependencies are captured in `requirements-models.txt` and installed in the current `.venv`.
- Implemented: `Data & Models` shows local model file inventory, config presence, tensor counts, runtime-package availability and live-readiness.
- Implemented: `ETF_AI_Cockpit.bat` prefers the Python launcher so the current `.venv` and external model folders are used; the packaged executable remains a fallback.
- Verified: TimesFM 2.5 and Toto 2.0 4M both produced local live smoke forecasts from the installed safetensors.
- Verified: packaged EXE starts a local web app successfully, and browser QA shows a rendered dashboard, Data & Models model inventory and Renew data safe API-placeholder workflow.

## 2026-06-30 Toto 1B GPU Runtime Update

- Implemented: Toto active model changed from `Toto-2.0-4m` to `Toto-2.0-1B` in `configs/model_settings.yaml`.
- Implemented: CUDA PyTorch runtime installed for the RTX 5070 Laptop GPU:
  - `torch 2.12.1+cu130`
  - CUDA runtime `13.0`
  - `torch.cuda.is_available() == true`
- Implemented: Lightning runtime upgraded to `lightning 2.6.5` and `pytorch-lightning 2.6.5` to keep `pip check` clean with modern packaging metadata.
- Implemented: `ForecastService` now runs baseline, TimesFM and Toto forecasts instead of baseline-only outputs.
- Implemented: `scripts/run_forecasts.py` for configured ETF universe forecasts.
- Implemented: `scripts/run_yfinance_candidate_forecasts.py` for baseline, TimesFM and Toto forecasts over the yfinance stock/ETF candidate list.
- Implemented: Toto input panel fix so all-missing first return rows are dropped before patch-size trimming.
- Implemented: TimesFM unsupported horizons are recorded as explicit `skipped` rows with null outputs and no score contribution. The local TimesFM 2.5 checkpoint is capped at 128 steps, so 180-day TimesFM rows are skipped while baseline/Toto still produce 180-day rows.
- Verified: ETF universe model run wrote `data/forecasts/forecast_results_20260626.csv` with 105 rows:
  - baseline ok 35
  - TimesFM ok 28, skipped 7
  - Toto 1B ok 35
- Verified: yfinance candidate model run wrote `data/forecasts/yfinance_candidate_forecasts_20260629.csv` with 180 rows:
  - baseline ok 60
  - TimesFM ok 48, skipped 12
  - Toto 1B ok 60

## 2026-06-30 Evidence Cockpit UI Direction

- Product direction updated: the app now prioritises analysing stocks, ETFs and candidate portfolios by local evidence score rather than treating allocation caps as the main conclusion.
- Acceptance change: target-weight, concentration and cash-minimum policy findings remain visible warnings/context, but no longer force every otherwise valid instrument signal into `manual_review`.
- Strict data failures still block analysis: missing/stale prices, missing adjusted close, invalid OHLC, missing FX for non-base-currency holdings and internally inconsistent holdings remain hard validation failures.
- Forecast integration target: latest valid forecast CSV rows feed Toto, TimesFM and baseline component scores. Rows with `status != ok` or `model_allowed_in_score=false` contribute zero.
- UI target:
  - Main shell title: AI Evidence Cockpit.
  - Overview focuses on analysis mode, top-ranked instrument, model evidence, data date and backtest context.
  - Scores page shows configured ETF universe plus latest yfinance stock/ETF candidate evidence.
  - Instrument Detail shows deterministic metrics and model forecast evidence.
  - Portfolio/Risk pages show context and guardrails, not execution authority.
  - Renew data dialog keeps safe local import/API-placeholder/dry-run workflows.
- Responsive target: desktop layout uses sidebar navigation; narrow/mobile layout switches to top navigation and stacked overview cards.

## 2026-06-30 Packaging Follow-Through

- Implemented: `scripts\build_windows.bat` now treats locked native build folders and failed Flet/PyInstaller pack steps as hard failures.
- Implemented: the portable build now contains:
  - primary launcher: `build\ETF_AI_Cockpit_Portable_v0.1.0\ETF_AI_Cockpit.bat`
  - native executable: `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`
  - native helper: `build\ETF_AI_Cockpit_Portable_v0.1.0\Run_ETF_AI_Cockpit_EXE.bat`
- Verified: rebuilt portable source path and native executable both start successfully.

## 2026-07-01 YFinance-Only Data Backbone

- Product direction updated: yfinance is now the default market-data backbone for configured ETF analysis.
- Implemented:
  - `configs\data_providers.yaml` sets prices, FX, ETF metadata and ETF holdings to `yfinance` by default.
  - Explicit Yahoo symbol map for the configured universe:
    - `WORLD_CORE=IWDA.AS`
    - `EUROPE_QUALITY=XDEQ.DE`
    - `US_TECH=SXRV.DE`
    - `EU_BANKS=EXX1.DE`
    - `JAPAN_EQUITY=SXRJ.DE`
    - `GLOBAL_BONDS=EUNA.DE`
    - `GOLD_HEDGE=4GLD.DE`
  - `YFinanceProvider` now fetches adjusted OHLCV/action columns, FX pairs, available Yahoo metadata and available top-holdings.
  - `DataService.api_update_status()` now refreshes yfinance prices plus available metadata/top-holdings and commits only after validation.
  - `scripts\run_yfinance_analysis.py` performs the full yfinance pipeline: fetch, validate, optional commit, feature/signal generation, TimesFM/Toto/baseline forecasts, backtest and JSON report.
- Verified live:
  - 8,903 yfinance price rows for 7 configured instruments.
  - Clean price store source is `yfinance` for all rows.
  - Yahoo metadata committed: 7 rows.
  - Yahoo top-holdings committed: 50 rows, with explicit partial-holdings warnings where Yahoo exposes only top positions.
  - Forecast statuses from yfinance data: baseline ok 35, TimesFM ok 28/skipped 7, Toto ok 35.

## 2026-07-01 Simple YFinance Scoring Experience

- Product direction updated again: the default user experience is now a simple four-step workflow:
  - `1. Refresh yfinance data`
  - `2. Run algorithms`
  - `3. Run forecasting models`
  - `4. Show scores`
- Main screen target:
  - list every configured ETF plus every row from `data/raw/trade_candidates/yahoo_trade_candidates_2026-06-30.csv`;
  - show final `0/10` to `10/10` score, decision label and short reason without horizontal scrolling;
  - expand each row to show Momentum, Trend, Risk/volatility, Relative strength, Baseline forecast, TimesFM forecast and Toto forecast;
  - show short plain-English text for what each algorithm/model means, what a good score means and why the instrument got its score.
- Implemented scoring rules:
  - internal `-1..+1` component scores convert with `(score + 1) * 5`;
  - `None` or invalid model rows show `N/A`;
  - final score reweights only available valid components;
  - thresholds: `8.0-10 Strong Buy Candidate`, `6.5-7.9 Buy Candidate`, `5.0-6.4 Watch`, `4.0-4.9 Hold`, `<4 Avoid/Review`.
- Service workflow:
  - yfinance refresh is exposed through `AppState.refresh_yfinance_data()`;
  - candidate algorithm report refresh is exposed through `AppState.run_algorithm_scores()`;
  - configured ETF and candidate forecast refresh is exposed through `AppState.run_forecasting_models()`.
- Packaging target:
  - portable builds must include current clean yfinance prices, forecasts, reports and the candidate CSV so the native executable opens with the same 19-row score universe as the source app.

## 2026-07-01 Chrome QA Follow-Up

- Current implemented analysis universe:
  - 7 configured ETFs from `configs/universe.yaml`.
  - 12 candidate stocks/ETFs from `data/raw/trade_candidates/yahoo_trade_candidates_2026-06-30.csv`.
  - 19 total rows appear on the main Simple Scores screen.
- Current default workflow remains:
  - Refresh yfinance data.
  - Run algorithms.
  - Run forecasting models.
  - Show scores.
- Main forecast button policy:
  - The UI scoring workflow uses the 60-trading-day horizon, matching the score cards.
  - Current-date forecast files are reused from cache instead of rerunning heavy 1B Toto/TimesFM candidate inference unnecessarily.
  - Full heavy diagnostic forecast scripts remain available for forced/offline reruns.
- UI quality targets added after Chrome QA:
  - No blank-looking startup: initial snapshot should stay around 2 seconds by avoiding heavy model-runtime imports and cached backtest recomputation.
  - All score-facing primary/detail views should show x/10 scores instead of raw `-1..+1` values.
  - Renew dialog long validation output must scroll internally and must not overlap action buttons.
  - Diagnostics must report the actual Toto 2.0 runtime package as `toto2`.

## 2026-07-04 UI QA Follow-Up Plan

- Current priority: make the app reliably visible in the browser/web launcher and avoid the blank/500 Flet static-file startup failure.
- Acceptance updates:
  - Flet web startup must use a writable static asset temp folder and return HTTP 200.
  - The source launcher and rebuilt exe must both start on a clean temporary port without stderr tracebacks.
  - Tests must run without relying on locked Windows user temp folders.
  - Chrome-specific automation should be used when available; if the Chrome extension backend is unavailable, record that limitation and use non-browser readiness/tests without claiming a fresh Chrome visual pass.
- Follow-up UI validation target when Chrome extension access is restored:
  - Open `ETF_AI_Cockpit.bat` or the local URL.
  - Confirm first viewport shows the simple score workflow, 19 instruments, model count, score legend and four workflow buttons.
  - Click/verify Refresh yfinance data, Run algorithms, Run forecasting models, Show scores, Renew data, Export audit packet and secondary page navigation.

## 2026-07-05 Extensive Feature Implementation Plan From Research Report

### Source Brief

- Primary source: `C:\Users\thor2\Downloads\AI_Evidence_Cockpit_Extensive_Feature_Implementation_Report.md`.
- Market-data rule: yfinance remains the only required default market-data provider.
- App role: local evidence cockpit for stocks, ETFs and candidate portfolios; no broker execution, no automatic trading, no financial-advice wording.
- Optional future free providers are allowed only as opt-in extensions: SEC EDGAR for US filings, FRED for macro, Stooq for backup OHLCV, Alpha Vantage only if API-key friction is accepted.

### External Research Notes

- yfinance official docs expose historical download, ticker APIs, Ticker/Tickers, screen/query, WebSocket and FundsData APIs. For this app, use historical prices, Ticker metadata and FundsData; do not use WebSocket/HFT paths.
- yfinance FundsData exposes top holdings, equity holdings, bond holdings, bond ratings, asset classes, sector weightings, fund overview and fund operations where Yahoo exposes them. Coverage is inconsistent, so ETF exposure scores must be optional and labelled partial.
- Hugging Face TimesFM 2.5 docs describe a pretrained decoder-only foundation model for time-series forecasting with continuous quantile prediction. It is useful as forecast evidence, not deterministic authority.
- Datadog Toto 2.0 docs describe zero-shot, probabilistic, multivariate forecasting; Toto 2.0 fine-tuning and exogenous-variable support are not the current default. It stays low-authority until the app has local walk-forward proof.

### Design Rule

The app must never let a model forecast rescue bad deterministic evidence. Final display is:

```text
Hard data/risk gates
-> deterministic evidence features
-> ETF/stock-specific modules
-> optional baseline/TimesFM/Toto confirmation
-> evidence quality and risk/friction badges
-> advisory evidence label
```

### Three-Score Model

Replace a single overconfident score with:

- `Evidence Score /10`: how positive the available signal stack is.
- `Evidence Quality /10`: how trustworthy the data, completeness, model availability and validation evidence are.
- `Risk/Friction /10`: how clean, liquid and low-friction the instrument looks.

The legacy UI field `final_score_10` remains as the main evidence score for compatibility, but user-facing text must describe it as evidence, not a buy/sell command.

### Authority Layers

| Layer | Authority | Score role | Can block |
| --- | --- | --- | --- |
| Data validation/freshness | Hard | Evidence quality | Yes |
| Price momentum/trend/relative strength | High | Evidence score | No, except data failures |
| Volatility/drawdown/liquidity/cost | High | Risk/friction | Can demote/block |
| ETF exposure/holdings | Medium | Evidence/risk | Can demote if concentration severe |
| Stock value/quality | Medium | Evidence | No, unless data contradiction is severe |
| Analyst/revisions/news | Low | Context only | No |
| Baseline/TimesFM/Toto | Low until calibrated | Confirmation | No |
| LLM audit | No executable authority | Explanation/audit only | No |
| Backtest trust | Medium | Evidence quality | Can demote |

### Final Labels

- `strong_evidence_candidate`: evidence >= 8, quality >= 7, risk/friction >= 6.
- `positive_evidence_candidate`: evidence >= 6.5, quality >= 6, risk/friction >= 5.
- `watchlist`: evidence mixed but usable.
- `hold_context`: existing holding context or mixed evidence with no hard block.
- `weak_evidence_review`: low evidence.
- `low_quality_manual_review`: high score but weak trust.
- `blocked_data_quality`: stale/missing/invalid data.

Avoid `Strong Buy`, `Buy`, `Sell` wording in release-facing UI.

### Phase 1 - Score Safety And yfinance Schema Hardening

Status: partially implemented on 2026-07-05.

- Add yfinance research-grade source-quality badge.
- Add data-quality component per instrument:
  - latest price date;
  - business-day age;
  - adjusted-close availability;
  - history length;
  - blocking flags.
- Split one score into evidence, quality and risk/friction.
- Add final evidence labels and final advisory actions.
- Write `data/derived/scoreboard.parquet` with the same fields shown in the UI.
- Keep missing components as `N/A`; reweight available valid components only.

### Phase 2 - Deterministic Evidence Engine

Status: already present for price features; expanded on 2026-07-05.

Required modules:

- Momentum:
  - ETF: 3m/6m/9m/12m medium-horizon blend.
  - Stock: 3m/6m/12m now; later add 12-1 and 6-1 momentum when candidate report stores skip-month returns.
- Trend:
  - price above SMA50/SMA200;
  - future: SMA100/SMA200 slopes and 10-month/SMA210 proxy.
- Relative strength:
  - current: candidate/universe relative return median.
  - future: benchmark-relative by asset class and sector.
- Risk:
  - current: volatility and drawdown.
  - future: downside volatility, ATR%, worst 20d/60d return.
- Liquidity/cost:
  - current: traded-value proxy and high-low spread proxy.
  - future: bid/ask where reliable, commission bps, slippage bps, edge-to-cost ratio.

### Phase 3 - ETF-Specific Modules

Status: partial.

- Use yfinance `funds_data.top_holdings` where available.
- Compute ETF exposure score:
  - available top-holding count;
  - top available holdings weight;
  - largest holding weight;
  - partial-coverage warning.
- Future:
  - sector-weight concentration;
  - asset-class weights;
  - bond ratings/credit quality;
  - duration/rate-risk proxy;
  - ETF overlap between configured and candidate ETFs.

### Phase 4 - Stock-Specific Modules

Status: initial implementation on 2026-07-05.

- Candidate analysis now attempts yfinance profile/fundamental extraction:
  - quote type;
  - market cap;
  - trailing/forward PE;
  - price-to-book;
  - earnings yield;
  - free-cash-flow yield;
  - ROE;
  - operating/profit margin;
  - debt-to-equity;
  - recommendation mean.
- Derived components:
  - `stock_value_score_10`;
  - `stock_quality_score_10`;
  - `analyst_revision_score_10`.
- Missing fundamentals do not block the app; they show `N/A` and reduce evidence quality for stock rows.
- Future:
  - statement-derived ratios instead of `info` fields where possible;
  - sector-relative scoring;
  - earnings/event-risk warnings;
  - insider/institutional holder context where Yahoo exposes it.

### Phase 5 - Forecasts And Calibration

Status: baseline, TimesFM and Toto already run; authority labels added on 2026-07-05.

- Keep baseline/TimesFM/Toto scores low-authority confirmation.
- Show `Model evidence: baseline only`, `Partial AI forecast evidence`, or `Independent AI confirmation available`.
- Required next:
  - local walk-forward forecast calibration;
  - OOS MASE/directional accuracy per model;
  - calibration status in scoreboard and model page;
  - model score cap when calibration is poor or missing.

### Phase 6 - Backtest Trust

Status: app has backtest engine and quality labels, but per-instrument trust is pending.

- Add per-instrument or per-template trust badge.
- Use next-period execution only.
- Include costs and turnover.
- Store:
  - OOS periods;
  - trade count;
  - annualised turnover;
  - max drawdown;
  - worst 12m return;
  - parameter sensitivity;
  - overfitting diagnostics where feasible.

### Phase 7 - Market Regime And Portfolio Fit

Status: planned.

- yfinance-only regime proxies:
  - global equity benchmark trend;
  - bond/cash proxy trend;
  - gold/defensive proxy behaviour;
  - percentage of configured/candidate instruments above SMA200.
- Portfolio fit:
  - rolling correlation;
  - beta to benchmark;
  - diversification contribution;
  - duplicate ETF exposure warning.

### Phase 8 - Strategy Template Library

Status: planned after deterministic modules stabilise.

- `dual_momentum_etf`:
  - rank configured ETFs by 120/252-day momentum;
  - require positive trend;
  - identify risk-on/risk-off candidates.
- `quality_momentum_stock`:
  - require stock quality >= median or configured floor;
  - rank by momentum and relative strength.
- `value_momentum_stock`:
  - combine value and momentum;
  - require quality floor.
- `defensive_rebalance`:
  - portfolio context only;
  - no trade unless cost/friction and hard gates pass.

### Phase 9 - UI And Export

Status: partial.

- Main row should show:
  - instrument;
  - asset type;
  - evidence score;
  - quality score;
  - risk/friction score;
  - model authority;
  - backtest trust;
  - final label/action;
  - short reason.
- Expanded row should show:
  - data quality;
  - momentum;
  - trend;
  - relative strength;
  - risk;
  - liquidity/cost;
  - ETF exposure or stock value/quality/analyst;
  - baseline/TimesFM/Toto.
- `data/derived/scoreboard.parquet` should be kept current after workflow refreshes.
- Future audit export should include the scoreboard parquet/CSV and per-instrument JSON evidence reports.

### Test Matrix For This Plan

- Unit:
  - score conversion and reweighting;
  - evidence label thresholds;
  - high evidence but low quality demotes to manual review;
  - missing model/fundamental components are `N/A`;
  - candidate stock rows can score without portfolio fields;
  - scoreboard frame contains quality/risk/model authority columns.
- Integration:
  - yfinance candidate refresh writes fundamentals where available;
  - scoreboard parquet writes 19 current rows;
  - app snapshot builds with configured ETFs plus candidate CSV;
  - model unavailable rows remain excluded.
- UI:
  - first viewport renders;
  - workflow buttons work;
  - expanded row shows authority/role chips;
  - labels use evidence language, not buy/sell language.
- Release:
  - full pytest suite;
  - local HTTP smoke;
  - Chrome visual pass when browser control is available;
  - rebuilt package after source changes if release executable is expected to include them.

### 2026-07-05 Execution Status

Implemented in this pass:

- The main scoring layer now exposes the report-recommended three-score model:
  - `evidence_score_10`;
  - `evidence_quality_10`;
  - `risk_friction_10`.
- The score layer now separates high-authority deterministic evidence from low-authority model confirmation.
- Final labels were renamed from direct buy/sell language to evidence language:
  - `Strong Evidence Candidate`;
  - `Positive Evidence Candidate`;
  - `Watchlist`;
  - `Hold Context`;
  - `Weak Evidence Review`;
  - `Manual Review`.
- Added yfinance-derived component modules:
  - data quality;
  - liquidity/cost;
  - ETF exposure;
  - stock value;
  - stock quality;
  - analyst/revision proxy.
- Added authority and role metadata to each expanded score component.
- Added model-authority labels:
  - `Independent AI confirmation available`;
  - `Partial AI forecast evidence`;
  - `Model evidence: baseline only`;
  - `Model evidence unavailable`.
- Added scoreboard persistence to `data/derived/scoreboard.parquet` after refresh, algorithm and forecast workflows.
- Updated the main dashboard and Scores page text to explain evidence quality, risk/friction and model authority in simpler language.
- Rebuilt the portable package after implementation and smoke-tested the native executable.

Still planned:

- Per-instrument backtest trust badges with walk-forward diagnostics.
- Full calibration metrics for TimesFM/Toto per instrument and horizon.
- yfinance-only regime module.
- Strategy template library.
- Scoreboard CSV/JSON inclusion in the audit export.
- Stronger semantic accessibility hooks for automated UI locators in Flet web.

### 2026-07-05 Extended Implementation Sweep Status

Implemented in this pass:

- Forecast calibration evaluator:
  - reads local forecast CSV history from `data/forecasts`;
  - compares only matured forecast rows against later local yfinance adjusted prices;
  - computes OOS MASE, directional accuracy and optional q10/q90 coverage;
  - writes `data/derived/model_calibration.parquet` and `data/derived/model_calibration.csv`;
  - marks current not-yet-matured TimesFM/Toto/baseline rows as pending instead of pretending calibration exists.
- Yfinance-only market regime:
  - computes benchmark SMA200 status;
  - percentage of configured/candidate instruments above SMA200;
  - benchmark 60d/120d returns;
  - median volatility/drawdown;
  - average 60d correlation;
  - writes `data/derived/market_regime.json` and `data/derived/market_regime.csv`.
- Portfolio-fit evidence:
  - computes configured ETF correlation and beta to the benchmark;
  - displays portfolio-fit text in expanded rows;
  - candidate rows explicitly show fit as pending because they are not in the clean portfolio price panel.
- Strategy-template library:
  - `dual_momentum_etf`;
  - `quality_momentum_stock`;
  - `value_momentum_stock`;
  - `defensive_watch`;
  - `no_template`;
  - writes `data/derived/strategy_templates.csv`.
- Backtest trust labels:
  - read cached `data/backtests/backtest_results.csv` and signal logs;
  - combine quality, walk-forward count, PBO proxy, sensitivity and per-instrument signal count;
  - candidate rows are honestly labelled not backtested.
- Scoreboard export expansion:
  - `scoreboard.parquet`, `scoreboard.csv`, `scoreboard.json`;
  - columns now include calibration, regime, portfolio fit, backtest trust and strategy templates.
- Audit packet expansion:
  - includes scoreboard CSV/JSON;
  - includes calibration CSV, regime JSON and strategy-template CSV;
  - includes `instrument_evidence/*.json` per score row;
  - includes derived evidence manifest.
- UI updates:
  - Dashboard summary card now shows market regime;
  - expanded score rows now show calibration, backtest, regime, portfolio fit and strategy-template chips;
  - Data & Models page now shows derived artefacts, regime, calibration and strategy-template panels.

Remaining planned:

- Historical calibration can only become non-pending after enough forecast horizons mature against later yfinance prices.
- Candidate portfolio-fit remains pending until candidate history is promoted into a clean local candidate price panel.
- Semantic browser locators are still limited by Flet canvas rendering; visual Chrome QA remains the practical route.

### 2026-07-08 Report Issue Workflow And Evidence-Maturity Sweep

Implemented:

- Created root `plan.md` as the issue-synchronised plan for the report-driven workflow.
- Created Markdown issue tracker:
  - `issues/open.md`;
  - `issues/closed.md`;
  - `issues/templates/feature_request.md`;
  - `issues/templates/bug.md`;
  - `issues/templates/research_task.md`.
- Extracted P0/P1 open issues from `C:\Users\thor2\Downloads\report.md`.
- Recorded rejected/deferred ideas:
  - autonomous broker execution;
  - direct LLM portfolio management;
  - RL trading agents;
  - martingale/grid systems;
  - futures/intraday implementation now;
  - news sentiment as direct score authority;
  - short-sample screenshots as evidence.
- Closed ISSUE-0001 after file checks and tests.
- Closed ISSUE-0002 after implementing evidence maturity and sanity warnings.
- Added simple-score maturity/sanity fields:
  - `evidence_sample_days`;
  - `evidence_maturity_state`;
  - `evidence_maturity_label`;
  - `too_good_to_be_true_warning`;
  - `evidence_sanity_warnings`;
  - `evidence_warning_count`.
- Expanded score rows now show Maturity, Sample, Sanity and Evidence warnings chips.
- Scoreboard parquet/CSV/JSON now includes the new maturity/sanity fields.
- Audit packet includes the updated scoreboard CSV/JSON.
- Closed ISSUE-0003 after adding yfinance benchmark attribution:
  - configured first ETF is the explicit benchmark;
  - 120 trading-day instrument/benchmark returns;
  - beta and correlation from overlapping daily returns;
  - alpha proxy and t-stat where valid;
  - no-causality label;
  - sector/theme warning from local metadata.
- Closed ISSUE-0004 after adding backtest payoff diagnostics:
  - return hit rate;
  - average win/loss return;
  - payoff ratio;
  - expected value per period;
  - payoff asymmetry warning;
  - Backtests UI columns and diagnostics text;
  - audit export via backtest summary JSON;
  - old-cache invalidation when payoff columns are missing.
- Closed ISSUE-0005 after adding signal-level cost stress diagnostics:
  - low/base/high cost bps;
  - edge-to-cost ratio under each stress scenario;
  - warning label;
  - assumptions text;
  - signal table context;
  - audit signal table export.
- Closed ISSUE-0006 after adding model/backtest validity fields:
  - `backtest_validity`;
  - `model_contamination_risk`;
  - `model_authority_reason`;
  - `calibration_required`;
  - UI chips and explanatory text;
  - tests that optional model score cannot rescue weak deterministic evidence.
- Closed ISSUE-0009 after adding manual-note source credibility:
  - `source_url`;
  - `source_type_category`;
  - `evidence_grade`;
  - `source_credibility`;
  - `promotional_risk`;
  - `reproducibility`;
  - `claim_quality`;
  - audit markdown metadata.

Still open from the report:

- No P0/P1 report-derived implementation issues remain open in `issues/open.md`.

### 2026-07-09 updatev2.md Roadmap Additions

The update file `C:\Users\thor2\Downloads\updatev2.md` has been transferred into the project roadmap without weakening the advisory-only architecture.

Key additions now tracked:

- Provider registry, capability probes, source authority ladder and provider-status UI.
- Symbol/ISIN/exchange identity resolver.
- SEC EDGAR official statement importer.
- European ESEF/iXBRL manual filing importer.
- France DILA and Netherlands AFM OAM discovery adapters.
- ETF disclosure registry for prospectus, PRIIPs KID, annual/half-year reports, factsheets, holdings, index methodology, SFDR and securities-lending/collateral documents.
- ETF holdings normaliser with full/partial/stale/conflict handling.
- PRIIPs KID parser.
- ETF prospectus/report parser.
- Index methodology importer.
- SFDR disclosure parser.
- Source conflict resolver and canonical metric selector.
- Evidence ledger and score component audit trail.
- Optional FMP, Alpha Vantage and Finnhub provider adapters.
- Optional OHLCV fallback/discrepancy providers: Stooq, Twelve Data and Tiingo.
- Low-authority candle feature/context/backtest module.
- UI workflow/button reliability and progress contracts for new import/probe/export workflows.
- Audit packet expansion for providers, filings, ETF documents, conflicts and candles.
- Rebuild/test/update discipline automation.

Because the update's proposed `ISSUE-0010` to `ISSUE-0030` IDs conflict with existing tracker IDs, the open implementation work is namespaced as `UPDATEV2-0010` through `UPDATEV2-0030` in `issues/open.md`. Research-only conclusions are recorded in `issues/closed.md` as `CLOSED-RESEARCH-001` through `CLOSED-RESEARCH-006`.

New root index files:

- `REPORT.md`
- `ISSUES.md`
- `CLOSED.md`

Implementation order:

1. Integrity foundation: provider registry, identity resolver, source conflict resolver and evidence ledger.
2. Official statements: SEC EDGAR, ESEF manual importer, statement facts and common metric mapping.
3. ETF disclosure stack: document registry, holdings normaliser, KID parser, report parser, methodology importer and SFDR parser.
4. Optional vendors/OHLCV fallback: FMP, Alpha Vantage, Finnhub, Stooq, Twelve Data and Tiingo.
5. Candle layer.
6. UI, audit and rebuild discipline.

### 2026-07-09 Score History Roadmap Addition

User requested local persistence of score history and a compact graph in each ETF/stock dropdown/expanded row.

Tracked as high-priority `ISSUE-0067`:

- persist every generated score run locally;
- store both total scores and individual metric/component scores;
- write `data/derived/score_history.parquet`;
- write `data/derived/score_metric_history.parquet`;
- show a small total-score evolution chart in every expanded ETF/stock score row;
- show latest score, previous score and delta when enough history exists;
- show a clear "history will appear after another run" state when history is insufficient;
- ensure score history is informational only and cannot directly alter final actions.

### 2026-07-09 Two-Tier Universe Update

The active universe is now split into:

- Primary tier: `configs/universe.yaml`, yfinance now and future multi-provider enrichment later.
- Secondary tier: latest `data/raw/trade_candidates/yahoo_trade_candidates_*.csv`, yfinance-only.

Primary tier IDs: `VWCE`, `LYP6`, `SPYK`, `SXRJ_EMU_SMALL`, `EXX1`, `UCG`, `SU`, `LR`, `PRY`, `NEX`, `DB1`, `ENX`, `VIE`, `SGO`, `FLXI`, `H4ZT`.

Secondary tier IDs: `AIR`, `BA`, `BRK_B`, `AM`, `IDR`, `KOG`, `KMAR`, `LDO`, `MSFT`, `RR`, `SAAB_B`, `SPCX`, `NONG`, `SBNOR`, `HO`, `TKA`, `TKMS`, `EUNK`, `CBUK`, `SEC0`, `SXRV_NASDAQ100`, `JEDI`, `VFEM`, `VUSA`, `EUDF`, `XAIX`, `EXUS`, `XDWU`, `RABO`.

Removed: `JAPAN_EQUITY`, `GLOBAL_BONDS`, `GOLD_HEDGE`.

Do not automatically run yfinance refresh, algorithms or TimesFM/Toto forecasting after universe edits. The Simple Scores UI must show all tier entries as pending when no refreshed evidence exists.

### 2026-07-09 Two-Tier Implementation Status

Completed:

- active primary tier in `configs/universe.yaml`;
- secondary tier in latest yfinance candidate CSV;
- provider symbol mapping and analysis-only portfolio targets;
- Simple Scores pending rows for both tiers;
- no-refresh startup path without stale deleted-ID signals;
- package rebuild and rebuilt executable smoke test;
- desktop shortcut creation helper.

Verified:

- 16 primary + 29 secondary instruments;
- no duplicate ISIN or yfinance ticker across tiers;
- full pytest suite passes;
- rebuilt app responds on `http://127.0.0.1:8550/`;
- rendered UI shows tier counts, pending rows and expandable row details.

Still intentionally pending until the user runs the workflow:

- yfinance refresh;
- deterministic algorithms;
- TimesFM/Toto/AI forecasting.

### 2026-07-09 21 Trust-Critical Implementation Programme

Active request: implement the selected 21 trust-critical issues as one staged release programme. The first pass must update `plan.md`, `issues/open.md`, `ISSUES.md` and worklog files, then implement the source/UI/test/export/rebuild work.

Selected issues:

1. `ISSUE-0069` single-file session action logging and diagnostics trace.
2. `UPDATEV2-0010` provider registry, capability probes and source authority model.
3. `UPDATEV2-0011` symbol/ISIN/exchange identity resolver.
4. `UPDATEV2-0021` source conflict resolver and canonical metric selector.
5. `UPDATEV2-0022` evidence ledger and score component audit trail.
6. `UPDATEV2-0012` SEC EDGAR official statement importer.
7. `UPDATEV2-0013` European ESEF/iXBRL filing importer.
8. `UPDATEV2-0015` ETF disclosure registry.
9. `UPDATEV2-0016` ETF holdings normaliser.
10. `UPDATEV2-0017` PRIIPs KID parser.
11. `UPDATEV2-0019` index methodology importer.
12. `ISSUE-0025` free news and filings dashboard.
13. `ISSUE-0054` point-in-time news/sentiment validation.
14. `ISSUE-0055` optional free provider stubs for SEC EDGAR, FRED, Stooq and RSS.
15. `ISSUE-0023` stock fundamentals hardening.
16. `ISSUE-0067` score history and mini charts.
17. `ISSUE-0047` feature-driver explanations.
18. `ISSUE-0052` correlation clustering and crowding warnings.
19. `ISSUE-0059` benchmark-relative sector/theme attribution.
20. `ISSUE-0064` friction-adjusted edge/cost estimates.
21. `UPDATEV2-0028` expanded report/audit packet.

Foundation order:

1. Add `logs/session.jsonl` current-session logging, clearing only on new app server process start.
2. Write provider, identity, conflict, evidence-ledger and score-component stores.
3. Add visible Diagnostics/Logs, Provider Status, Evidence Ledger, Filings/Statements, ETF Disclosures and News/Context UI surfaces.
4. Persist score history and score component history, then show mini score-evolution charts in expanded rows.
5. Expand evidence export so it includes stores, configs, plan/open issues snapshots, checksums and the session log or unavailable markers.

Required stores:

```text
logs/session.jsonl
data/clean/provider_probe_results.parquet
data/clean/instrument_identity.parquet
data/clean/source_conflicts.parquet
data/derived/evidence_ledger.parquet
data/derived/score_components.parquet
data/derived/score_history.parquet
data/derived/score_metric_history.parquet
data/derived/feature_drivers.parquet
data/derived/correlation_clusters.parquet
data/derived/benchmark_attribution.parquet
```

Rules for this sweep:

- Missing optional data remains missing and must be shown as unavailable/null, not inferred.
- yfinance remains default but lower-authority than official filings and issuer documents.
- News, LLM, optional model and candle context cannot directly alter actions.
- No issue can be closed until source, UI, tests, audit/export, docs, rebuild and smoke verification pass.

### 2026-07-09 Trust-Critical Implementation Status

Completed this pass:

- current-session trace at `logs/session.jsonl`;
- Diagnostics session-log panel;
- provider status/source authority store;
- active-universe identity resolver store;
- source conflict store;
- evidence ledger and score component audit trail;
- score history, metric history and expanded-row history state;
- feature-driver, correlation/crowding and benchmark-attribution stores;
- Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures and News & Context pages;
- expanded audit/evidence export with trust stores, redacted config snapshots, plan/open issue snapshots, checksums and session log;
- Simple Scores grey-panel regression fix and test.

Verified:

- compile check passed;
- focused trust-critical/simple-score tests passed;
- full pytest passed;
- Windows package rebuilt;
- rebuilt executable served `http://127.0.0.1:8550/`;
- real Chrome/Windows capture verified score rows, row expansion and new trust pages.

Still open by close-rule:

- full source-specific SEC EDGAR parsing;
- full ESEF/iXBRL parsing;
- full PRIIPs KID parsing;
- full ETF disclosure/index-methodology ingestion workflows;
- real provider-backed news/filing refresh workflows beyond explicit unavailable/local-inventory states.

## 2026-07-11 Approved Programme Planning Pre-flight

- Created the dependency-ordered programme index, nine implementation plans and durable progress ledger under `docs/superpowers/plans/`.
- Mapped all 37 current open closure-matrix records exactly once; DATA-05 is separately owned by the verified-coverage plan.
- The next task is Wave 0, Task 1: typed verification and closure-evidence records. It requires a fresh implementer, RED evidence and a fresh reviewer before it may be marked complete.
- No implementation code or closure status has changed during planning.

## 2026-07-11 Wave 0 Task 1 Checkpoint

- Added typed `VerificationRun` and `ClosureEvidenceRecord` contracts; approved closure evidence rejects a builder acting as the required independent reviewer.
- Migrated the closure matrix to programme schema 2 with `historic_baseline_count: 41` and 42 honestly iterable active records.
- Added DATA-05 separately with `still_open` status and source, schema, tests, UI, audit, package and browser gates; no historic identity or status was rewritten.
- Focused GREEN command exited 0 with 15 tests passing; the complete test suite, scoped Ruff and compilation also exited 0.
- Source SHA-256 values: operations models `e648ff729aa29beb2754a44911d8293ec0fcd142941fbb4c52e466f8487275f8`; closure parser `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595`.
- Task 1 remains pending fresh independent review; no issue was closed.

## 2026-07-11 Wave 0 Task 1 Checkpoint-Evidence Correction (Round-2 Important Finding)

- Deterministic checkpoint verification first reproduced the stale model hash in the prior checkpoint and malformed command prefixes in the reviewer-finding-fix TESTING block; the pre-fix check exited 1 as expected.
- Corrected checkpoint evidence records the independently computed `src/etf_cockpit/operations/models.py` SHA-256 as `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`.
- The four reviewer-finding-fix commands were subsequently restated with unambiguous slash-form commands in the Round-3 checkpoint below.
- Matrix state remains programme schema 2, historic baseline 41, 42 active records, and DATA-05 `still_open`; no issue or closure status changed.
- Fresh independent re-review remains pending; this checkpoint is not a passed or closed review.

## 2026-07-11 Wave 0 Task 1 Checkpoint-Evidence Correction (Round-3 Important Finding)

- RED: `./.venv/Scripts/python.exe -m pytest tests/operations/test_verification_records.py -q` - exit 1.
- GREEN: `./.venv/Scripts/python.exe -m pytest tests/operations/test_verification_records.py tests/release/test_issue_evidence.py tests/test_closure_matrix.py -q` - exit 0, 18 passed.
- Ruff: `./.venv/Scripts/python.exe -m ruff check src/etf_cockpit/operations/models.py tests/operations/test_verification_records.py` - exit 0.
- Compile: `./.venv/Scripts/python.exe -m compileall -q src/etf_cockpit/operations` - exit 0.
- Current `src/etf_cockpit/operations/models.py` SHA-256 is `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`.
- Matrix state remains programme schema 2, historic baseline 41, 42 active records, and DATA-05 `still_open`; no issue was closed.
- Fresh independent re-review remains pending; this is a documentation correction checkpoint, not a closure decision.

## 2026-07-11 Wave 0 Task 1 Independent Review Approval

- Final fresh task review approved the typed verification and closure-evidence foundation after resolving the actor-normalisation and durable-checkpoint findings.
- Post-review covering verification passed: 18 focused tests, scoped Ruff, compilation and source snapshot smoke.
- The metadata-validation Minor remains logged for broad final triage. No issue, including DATA-05, was closed.
- Task 2 is the next eligible foundation task.

## 2026-07-11 Wave 0 Task 2 Checkpoint

- Audited the interrupted Task 2 session-trace implementation against `.ai_worklog/task-2-brief.md` and the Task 2 base snapshot; no issue status or execution authority changed.
- Added one TDD regression: a schema-invalid complete JSONL row now surfaces the loader's contextual `Malformed complete JSONL row` integrity error rather than raw Pydantic detail. RED exited 1; GREEN exited 0 with 6 event-store tests passing.
- Focused operational/diagnostics regression exited 0 with 21 tests passing; scoped Ruff and compilation exited 0; the full `tests` suite exited 0. Existing GluonTS/pandas warnings remain outside this task's scope.
- Fixture SHA-256: `tests/operations/fixtures/session_incomplete_tail.jsonl` is `ef7a5209f51a197b239b83e1ae117d6676817883d016325c7704dad1c80d806b`.
- Review package range is `.ai_worklog/task-2-base/` to the current ten-file Task 2 scope documented in `.ai_worklog/task-2-report.md`; no Git repository is available.
- Diagnostics screenshot and semantic-capture plan, current source hashes, self-review, and residual concerns are recorded in `.ai_worklog/task-2-report.md`.
- Task 2 awaits fresh independent review; no issue is closed.

## 2026-07-11 Wave 0 Task 2 Complete

- Completed the session-trace operational-event authority seam with typed `OperationalEvent`, one canonical `logs/session.jsonl` event stream, tail/integrity recovery, event IDs and hash chaining for new writes, and nested secret redaction before hashing.
- Added AppState event-derived activity projection and Diagnostics tail-recovery/integrity visibility. Legacy valid rows remain readable; malformed complete rows are explicit integrity errors.
- Fresh review 1 found two Important findings: default workflow persistence to `logs/workflow.jsonl` and stale dashboard `activity_log.jsonl` copy. A fresh fix implementer resolved both with RED/GREEN evidence; fresh review 2 approved Task 2 with no findings.
- Focused final review bundle passed 28 tests, full `tests` passed, scoped Ruff and compilation passed. Full-suite warnings remained pre-existing GluonTS/pandas warnings.
- Evidence: `.ai_worklog/task-2-report.md`, `.ai_worklog/task-2-authority-fix-report.md`, `.ai_worklog/task-2-review-1.md`, `.ai_worklog/task-2-review-2.md`, `.ai_worklog/task-2-review-package-final.md`.
- No issue status changed, DATA-05 remains `still_open`, `execution_allowed` remains `false`, and Task 3 is the next incomplete task but was not started.
