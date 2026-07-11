# Changes

## 2026-06-27

- Added `configs\data_providers.yaml` and expanded `.env.example` with provider/base URL/API-key placeholders.
- Added data provider config models with secret redaction.
- Added `ManualLocalFileProvider`, `GenericHTTPProvider`, `ProviderResult` and kept the legacy one-symbol price-provider interface compatible.
- Changed EODHD and Alpha Vantage placeholder providers to return safe empty frames instead of raising `NotImplementedError`.
- Added preferred storage directories for `data\clean`, `data\derived`, `data\snapshots`, `data\audit_packets`, `data\reports` and the requested raw subfolders.
- Added `DatasetMetadata` and provenance helpers for checksums and staleness classification.
- Updated price validation to use OK/warning/block stale-price tiers and attach dataset metadata.
- Added target-policy validation for configured target weights versus risk caps.
- Added strict portfolio validation blocking in risk gates; current sample policy violation forces `manual_review`.
- Added advisory `add_candidate` and `trim_candidate` action support and mapped internal buy/add/trim/sell candidates to release-facing advisory actions.
- Expanded signal metrics, table columns and explanations with drift, edge/cost, minimum trade and full reason data.
- Added TimesFM/Toto unavailable-model metadata fields and tests.
- Updated the backtest output with requested quality fields and labelled advanced diagnostics as `low`/not-run where they are not yet estimated.
- Removed silent forward-fill from the backtest price pivot.
- Added validation and risk-gate JSON reports to the ChatGPT audit export ZIP.
- Changed ChatGPT audit imports to save a dated note with `executable_authority=false`.
- Added provider fields and hidden API-key placeholders on the Settings page.
- Added data provenance display on the Data & Models page.
- Added a visible Renew Data workflow with file-picker local import, configured API and dry-run validation options.
- Fixed the Renew Data dialog display for Flet 0.85.3 by using `page.show_dialog()`.
- Added `tests\test_release_hardening.py`.
- `ETF_AI_Cockpit.bat` now prefers the packaged executable and only uses the Python development launcher as a fallback.
- `README.md` now names `ETF_AI_Cockpit.bat` as the normal post-build launcher.
- `README_FIRST_RUN.md` now distinguishes the normal launcher, direct exe launcher and Python fallback.
- Extracted TimesFM and Toto archives under `models\source_archives`.
- Added `models\source_archives\README.md` and clarified the model-folder README files.
- Updated `TotoAdapter` to use the Toto 2.0 `toto2` runtime import.
- Added a regression test for the Toto 2.0 import name.
- Updated `scripts\build_windows.bat` so Flet packaging includes only runtime model folders, not `models\source_archives`.
- Updated Flet startup to render the initial route immediately instead of relying on `page.go("/")`.
- Added a startup regression test that verifies the default route adds a visible view without a route-change event.
- Updated shell rendering to replace the root Flet view atomically, avoiding both missed initial-route rendering and an empty `page.views` list.
- Switched normal app launch to local Flet browser mode on `127.0.0.1:8550`; native desktop mode remains available with `ETF_COCKPIT_VIEW=desktop`.
- Updated `scripts\build_windows.bat` to bundle the `flet_web` web runtime assets and required hidden imports for FastAPI, Starlette and Uvicorn.
- Added packaged startup diagnostics under `logs\startup.log`, `logs\stdout.log` and `logs\stderr.log`.
- Attached stdout/stderr file handles in the windowed packaged app so Uvicorn logging works under PyInstaller.
- Cleared Flet's embedded platform marker for web mode so the packaged executable runs a normal local web server instead of the blank desktop/socket path.
- Updated `ETF_AI_Cockpit.bat` to wait for `http://127.0.0.1:8550/` with `curl.exe`, then open the browser only after the server returns content.
- Changed the backtest rebalance loop to schedule next-row execution and record both `signal_date` and `execution_date`.
- Added holdings validation for required fields, value reconciliation, residual cash, current concentration limits, unknown/duplicate ETFs and stale holdings snapshots.
- Wired holdings validation into app snapshot creation, signal generation and Renew Data dry-run validation.
- Added release-hardening tests for current concentration violations and cash minimum breaches.
- Added a backtest regression test for no same-bar execution.
- Added `data.import_pipeline.commit_price_import()` to store validated price imports through raw, snapshot, clean and compatibility layers.
- Updated the Renew Data local import workflow to commit validated price files and refresh the app snapshot.
- Expanded the Backtests page with walk-forward, turnover, trade-log and honest quality diagnostics.
- Replaced deprecated Flet `ElevatedButton` controls with `ft.Button` on edited pages.
- Updated the Renew Data file picker to the Flet 0.85 async `pick_files()` API and added a web-mode bytes upload path.
- Added rollback support for the latest previous clean price snapshot, including metadata and a snapshot of the store being replaced.
- Added a `Rollback last prices` action to the Renew Data workflow.
- Added rollback regression tests for successful restore and the safe no-snapshot message.
- Added deterministic risk analytics helpers for exposure limits, adjusted-return correlations and drawdown contribution.
- Added a dedicated Risk page and sidebar route.
- Added risk analytics regression tests.
- Added manual thesis/news ingestion with validation, normalisation, immutable raw storage, clean Parquet output, previous snapshots and metadata.
- Updated `DataService` and app state paths so `manual_news` imports can be validated and committed through the same Renew Data workflow as prices.
- Changed Renew Data actions from one generic local import button to separate `Import prices` and `Import manual notes` buttons.
- Updated ChatGPT audit export to include imported manual thesis/news notes in `06_recent_news_events.md` and the combined review packet.
- Updated Data & Models to show a first-viewport evidence stack containing model availability, provenance, manual thesis/news status and validation issues.
- Added release-hardening tests for manual-news commit, missing-date rejection and audit ZIP inclusion.
- Added ETF factsheet/reference metadata and underlying ETF holdings import pipelines with validation, normalisation, immutable raw storage, clean Parquet output, snapshots and metadata.
- Updated Renew Data with `Import ETF factsheets` and `Import ETF holdings` actions.
- Added `ETF Reference Data` inventory to Data & Models.
- Added `12_reference_data_inventory.json` to ChatGPT audit export and included it in the combined review packet.
- Added release-hardening tests for ETF factsheet staleness, holdings percentage-weight normalisation, invalid decimal-weight rejection and audit inventory inclusion.
- Added dated FX import pipeline with explicit pair/base/quote validation, positive rates, raw storage, clean Parquet output, snapshots and metadata.
- Updated Renew Data with `Import FX rates`.
- Added FX inventory to Data & Models and ChatGPT audit export as `13_fx_inventory.json`.
- Added release-hardening tests for FX commit/snapshot metadata, invalid pair rejection and audit FX inventory inclusion.
- Added portfolio-weighted underlying ETF holdings exposure analytics.
- Updated the Risk page to show underlying sector/region/currency exposure when imported ETF holdings exist, or an explicit no-import empty state otherwise.
- Added a risk analytics regression test for latest-date underlying holdings exposure.

## 2026-06-28

- Added deterministic advanced backtest diagnostics in `src\etf_cockpit\backtest\engine.py`: probabilistic Sharpe, deflated Sharpe, PBO probability proxy and parameter sensitivity status.
- Updated backtest quality labelling so populated diagnostics can lift the sample backtest from low to medium when the required fields are present while still preserving conservative quality notes.
- Updated the Backtests UI footer to explain that advanced diagnostics are local deterministic estimates, not proof of future performance.
- Added a regression test for populated advanced backtest diagnostics.
- Removed the non-default initial-route redirect in `src\etf_cockpit\app\flet_app.py` so direct route startup and browser refresh preserve pages such as `/backtests`.
- Added a Flet startup regression test for initial non-default route preservation.
- Changed audit packet exports to default to `data\audit_packets\audit_packet_YYYY-MM-DD.zip`, with the legacy `CHATGPT_EXPORTS_DIR` name retained as a compatibility alias.
- Added `AppState.export_audit_packet()` and kept `export_chatgpt_pack()` as a compatibility wrapper.
- Updated Dashboard, Audit page, route title and shared footer to use neutral external-audit wording.
- Updated README files to describe audit packets and non-executable external audit commentary.
- Added tests for audit packet output location/naming and the neutral `Audit` route label.
- Added optional LM Studio local LLM audit configuration in `configs\local_llm.yaml`.
- Added `src\etf_cockpit\audit\local_llm.py` for local LLM status checks, deterministic audit context, schema-validated commentary parsing, OpenAI-compatible chat-completions calls and report saving.
- Added a Local LLM audit commentary panel on the Audit page with safe offline handling.
- Added README documentation for the optional local LLM workflow.
- Added local LLM audit tests covering no-network disabled status, model discovery, safe unavailable status, schema rejection and deterministic context generation.
- Added a non-executable manual trade proposal report workflow and Dashboard wiring. Reports are advisory-only JSON files with explicit block summaries, no broker execution and `executable_authority=false`.
- Added trade-proposal tests for blocked data-quality states and candidate filtering.
- Updated project-root resolution to prefer a valid `ETF_COCKPIT_ROOT` or launcher working directory before bundled `_internal` configs.
- Updated Windows launchers to set `ETF_COCKPIT_ROOT` so packaged reports, logs and user data resolve to the visible project or portable folder.
- Added project-root regression tests covering environment root, current working directory and invalid environment fallback.
- Added currency-aware holdings validation. Non-base-currency holdings now need a dated FX rate into the configured base currency; missing or stale FX blocks trading rather than silently trusting `market_value_eur`.
- Wired clean FX rates into the app's holdings validation path.
- Added release-hardening regression tests for missing, valid and stale FX conversion evidence.
- Added duplicate-server startup protection in Flet web mode. If the local server is already running, a new launch reuses it instead of attempting another bind on port 8550.
- Updated Windows launchers to check `http://127.0.0.1:8550/` before starting another executable or Python process.
- Added startup regression tests for existing-server reuse and busy-port protection.
- Added provider settings persistence. Provider/base URL are saved to `configs\data_providers.yaml`; API keys are saved only to local `.env`.
- Updated Settings UI provider rows from read-only placeholders to editable fields with Save buttons.
- Added tests for `.env` provider overrides, secret redaction and API-key exclusion from YAML.

## 2026-06-30

- Copied `timesfm-2.0.1.zip` and `toto-toto-models-v1.0.0.zip` into `models\source_archives` for local provenance while preserving the root originals.
- Added `models\source_archives\MODEL_ARCHIVE_MANIFEST.md` with archive checksums, extracted folder references and runtime-status notes.
- Updated `models\source_archives\README.md` to clarify that ZIPs and extracted folders are source/reference material and not imported by the app at startup.
- Verified LM Studio model discovery through the configured OpenAI-compatible endpoint.
- No runtime model configuration was changed: TimesFM and Toto remain unavailable until real checkpoint folders and compatible runtime packages are installed.

## 2026-06-30

- Extended model runtime config with backend, Hugging Face repo IDs, local-file flags, decode block size and compile options.
- Updated `configs\model_settings.yaml` with TimesFM 2.5 Transformers and all Datadog Toto 2.0 repo IDs while preserving disabled/local-first defaults.
- Implemented an optional TimesFM 2.5 live path using `TimesFm2_5ModelForPrediction.from_pretrained(...)`, with a secondary official TimesFM PyTorch backend.
- Implemented an optional Toto 2.0 live path using `Toto2Model.from_pretrained(...)` and the Datadog model-card input/output shapes.
- Added strict local checkpoint gating so README-only folders and source archives cannot make models appear available.
- Added forecast-output conversion helpers and regression tests for TimesFM price-level forecasts and Toto quantile return paths.
- Updated model READMEs and archive manifest with the exact Hugging Face references and expected local checkpoint folders.
- Rebuilt the packaged Windows app so `ETF_AI_Cockpit.bat` and the packaged executable include the new adapter/config changes.

## 2026-06-30

- Added `yfinance>=1.5` to runtime dependencies.
- Added `YFinanceProvider` for Yahoo Finance daily price retrieval and cockpit schema normalisation.
- Wired configured yfinance price updates into `DataService.api_update_status()` with validation-before-commit behaviour.
- Added a user-supplied trade candidate CSV under `data\raw\trade_candidates`.
- Added `scripts\analyze_yfinance_candidates.py` for separate non-executable candidate analysis reports.
- Added a yfinance provider regression test.
- Updated the Windows build script to include yfinance-related hidden imports.
- Generated yfinance candidate-analysis reports under `data\reports`.
- Rebuilt and smoke-tested the packaged executable.

## 2026-06-30

- Moved installed TimesFM and Toto safetensors into dedicated runtime checkpoint folders under `models\timesfm` and `models\toto`.
- Added local checkpoint `config.json` files for TimesFM 2.5 Transformers, Toto 2.0 4M and Toto 2.0 1B.
- Converted the runtime TimesFM safetensor from legacy `ff0`/`ff1` MLP keys to Transformers-compatible `fc1`/`fc2` keys while preserving the original file.
- Added `requirements-models.txt` for optional local model runtime dependencies.
- Recreated the local `.venv` and installed base, dev and model runtime dependencies.
- Updated `configs\model_settings.yaml` so TimesFM and Toto 4M are enabled in live local mode by default.
- Added local safetensor/model inventory diagnostics in `src\etf_cockpit\models\local_weights.py`.
- Wired model inventory into `src\etf_cockpit\models\registry.py`, `src\etf_cockpit\services.py` and `src\etf_cockpit\app\pages\data_models.py`.
- Hardened `TimesFMAdapter` and `TotoAdapter` for local checkpoint compatibility, CPU loading and patch-aligned context windows.
- Updated model-shape and release-hardening tests for safetensor header inspection, Toto config requirements and patch trimming.
- Updated `.gitignore` to ignore large model weights while keeping model config files.
- Updated `requirements.txt`, `pyproject.toml`, README files and model README files for `flet-web`, optional model runtimes and live local checkpoint layout.
- Updated `ETF_AI_Cockpit.bat` to prefer the Python launcher and use the packaged executable only as a fallback.
- Updated `scripts\build_windows.bat` to repair broken venvs, include Flet web runtime assets and avoid copying safetensors into the package.
- Rebuilt the packaged executable and portable folder after the Flet web runtime fix.

## 2026-06-30

- Changed Toto active configuration from 4M to 1B in `configs\model_settings.yaml`.
- Installed CUDA Torch `2.12.1+cu130` and upgraded Lightning runtime packages.
- Updated `requirements-models.txt` to recreate the CUDA 13.0 model runtime.
- Updated README and model docs to state Toto 1B is active and 4M is retained as a fallback checkpoint.
- Updated `ForecastService` to run baseline, TimesFM and Toto forecasts and persist forecast CSVs.
- Added `scripts\run_forecasts.py`.
- Added `scripts\run_yfinance_candidate_forecasts.py`.
- Made ForecastService benchmark selection robust for non-universe candidate panels.
- Changed TimesFM/Toto unsupported horizon conversion to `skipped` rows instead of hard failures.
- Fixed Toto patch-aligned input construction by dropping all-missing return rows before context trimming.
- Added/updated tests for full optional-model forecast rows and Toto patch trimming.

## 2026-06-30

- UI:
  - Renamed the app surface to AI Evidence Cockpit.
  - Reworked navigation labels to Overview, Scores, Risk Evidence, Instrument Detail and Audit Notes.
  - Rewrote dashboard, dialogs and page copy to focus on analysis/evidence rather than trade execution or allocation policing.
  - Improved theme colours, metric cards, section headers, evidence chips and score meters.
  - Added responsive top navigation for narrow/mobile browser widths.
- Scoring:
  - Added forecast CSV score loading from valid baseline, Toto and TimesFM rows.
  - Toto/TimesFM component scores are now non-zero when valid local forecast rows exist.
  - Removed the concentration penalty from total score.
  - Preserved strict data-quality blocking while making target/concentration/cash-policy issues warnings.
- Scores page:
  - Added compact configured-universe score table.
  - Added model score input table.
  - Added latest yfinance stock/ETF candidate evidence table.
- Data and diagnostics:
  - Data & Models now lists forecast artefacts and candidate reports.
  - Diagnostics now reports Torch CUDA/GPU status.
- Tests:
  - Updated release-hardening tests for allocation-context warnings.
  - Added forecast-score regression coverage.
  - Updated navigation-label assertions.

## 2026-06-30

- Packaging:
  - Hardened `scripts\build_windows.bat` so native pack failures and locked build folders fail loudly instead of leaving stale output behind.
  - Added native onedir copy into `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit`.
  - Added `Run_ETF_AI_Cockpit_EXE.bat` in the portable folder.
  - Updated native-exe helper launchers to set the visible project/portable root and wait for the local web UI before opening the browser.
  - Rebuilt the refreshed portable distribution after the UI and scoring changes.

## 2026-07-01

- Data providers:
  - Made yfinance the default configured provider for prices, FX, ETF metadata and ETF holdings.
  - Added explicit Yahoo ticker mapping for the configured ETF universe.
  - Extended `YFinanceProvider` to fetch adjusted price data with action columns, FX pairs, Yahoo metadata and top-holdings where available.
- Services:
  - Added `DataService.refresh_yfinance_data()` and wired `api_update_status()` to yfinance refresh/validate/commit behaviour.
  - Removed the implicit forward-fill warning in forecast benchmark return calculation by using `pct_change(fill_method=None)`.
- Scripts:
  - Added `scripts\run_yfinance_analysis.py` for a full yfinance-backed algorithm/model/backtest run.
- Tests:
  - Added yfinance provider tests for metadata, holdings, FX and symbol mapping.
- Documentation:
  - Updated README and implementation notes to document yfinance as the market-data backbone and sample data as fallback/testing only.
- Packaging:
  - Rebuilt the portable package after yfinance changes and verified the rebuilt native exe responds on a temporary local port.

## 2026-07-01 Simple YFinance Scoring UI

- Feature:
  - Added simple `0/10` to `10/10` scoring dataclasses and builders in `src\etf_cockpit\signals\simple_scores.py`.
  - Added merged score universe: configured ETFs plus candidate stocks/ETFs from the yfinance candidate CSV.
  - Added final decision labels and score legend matching the user plan.
  - Added candidate yfinance algorithm analysis package code in `src\etf_cockpit\data\trade_candidate_analysis.py`.
- Services:
  - Added app-state workflow methods for refresh data, run algorithms and run forecasting models.
  - Added data-service methods for yfinance candidate analysis and configured/candidate forecasts.
- UI:
  - Replaced Overview with the four-step workflow and expandable score rows.
  - Replaced Scores with the same plain x/10 score rows.
  - Added per-component explanations for Momentum, Trend, Risk/volatility, Relative strength, Baseline, TimesFM and Toto.
  - Fixed desktop blank-rendering layout by removing wrapped expanded-card rows.
  - Fixed mobile summary-card truncation by stacking cards on narrow screens.
- Tests:
  - Added `tests\test_simple_scores.py`.
  - Added coverage for score conversion, thresholds, missing model reweighting, candidate scoring and workflow button presence.
- Packaging:
  - Updated `scripts\build_windows.bat` to copy clean yfinance data, forecasts, reports and trade-candidate CSVs into the portable folder.
  - Rebuilt and verified the final native package with the full 19-instrument score set.
## 2026-07-01 Chrome QA Fixes

### Startup

- `src/etf_cockpit/models/registry.py`
  - Replaced live adapter availability imports with lightweight model inventory checks.
- `src/etf_cockpit/services.py`
  - Added cached backtest loading for current-date startup snapshots.

### Forecast Workflow

- `src/etf_cockpit/services.py`
  - Added optional forecast horizon override.
  - Added current-date configured/candidate forecast cache reuse.
  - Added dataframe-based forecast status summaries for cached rows.
- `src/etf_cockpit/app/state.py`
  - Main UI model action now uses the 60-trading-day scoring horizon.
- `src/etf_cockpit/app/pages/dashboard.py`
  - Workflow actions show a running message before backend work starts.
  - Model count card now includes candidate forecasts.

### UI

- `src/etf_cockpit/app/pages/dashboard.py`
  - Renew dialog content now scrolls internally for long validation reports.
- `src/etf_cockpit/app/pages/etf_detail.py`
  - Converted legacy raw scores to x/10 evidence/model cards and x/10 summary copy.
- `src/etf_cockpit/app/pages/diagnostics.py`
  - Corrected Toto runtime diagnostic from `toto` to `toto2`.

### Local LLM

- `src/etf_cockpit/audit/local_llm.py`
- `configs/local_llm.yaml`
  - Raised LM Studio commentary timeout from 12 seconds to 60 seconds.

### Packaging

- Rebuilt `build\flet_dist` and `build\ETF_AI_Cockpit_Portable_v0.1.0` with the latest source and config.

## 2026-07-04 Startup, Tests and Package

### Startup

- `src/etf_cockpit/core/runtime.py`
  - Added runtime environment helper for project-local Flet/cache folders.
- `src/etf_cockpit/app/flet_app.py`
  - Added a scoped Flet static temp patch so web assets are copied into a deterministic writable folder.
- `scripts/run_app.py`
- `src/etf_cockpit/main.py`
  - Configure runtime folders before app startup.

### Tests

- `tests/test_flet_startup.py`
  - Added regression test proving the patched Flet static temp directory is writable.
- `tests/conftest.py`
  - Added compact project-local `tmp_path` fixture for Windows sessions with locked user temp folders.
- `pyproject.toml`
  - Disabled pytest cache provider to avoid inaccessible cache/temp writes.
- `.gitignore`
  - Ignored generated runtime and test temp folders.

### Packaging

- Rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
- Rebuilt `build\ETF_AI_Cockpit_Portable_v0.1.0`.

## 2026-07-04 Chrome QA Follow-Up

- `src/etf_cockpit/app/pages/dashboard.py`
  - Replaced the four workflow `ft.Button` controls with fixed-width clickable containers so the visible pill is the click target.
  - Kept the same button labels, icons and workflow behaviour.

- Test/config:
  - Full regression suite passed after the workflow hit-target change.

## 2026-07-05 Report-Driven Evidence Scoring

### Planning

- `.ai_worklog\PLAN.md`
  - Added an extensive implementation plan based on `AI_Evidence_Cockpit_Extensive_Feature_Implementation_Report.md`.
  - Added the three-score model, authority layers, yfinance data modules, model-calibration roadmap, backtest-trust roadmap and test matrix.

### Scoring

- `src\etf_cockpit\signals\simple_scores.py`
  - Added evidence quality and risk/friction scores.
  - Added data-quality, liquidity/cost, ETF exposure, stock value, stock quality and analyst/revision components.
  - Added component `authority` and `score_role` metadata.
  - Added model-authority and backtest-trust labels.
  - Added scoreboard dataframe/export helpers for `data\derived\scoreboard.parquet`.
  - Updated final labels to evidence language rather than direct trading language.

### YFinance Candidate Evidence

- `src\etf_cockpit\data\trade_candidate_analysis.py`
  - Added yfinance `Ticker.info` based profile/fundamental extraction.
  - Added stock proxy scores for value, quality and analyst/revision evidence.
  - Added asset-type and high-low spread proxy fields.
  - Kept missing fundamentals as explicit `N/A` evidence, not invented values.

### UI

- `src\etf_cockpit\app\components\simple_scores.py`
  - Expanded rows now show quality, risk/friction, model authority, backtest trust, component counts, warnings and authority/role chips.
- `src\etf_cockpit\app\pages\signals.py`
  - Updated summary cards and text from buy/sell language to evidence categories.
- `src\etf_cockpit\app\pages\dashboard.py`
  - Updated explanatory text to focus on evidence quality, risk/friction and low-authority AI confirmation.
- `src\etf_cockpit\app\state.py`
  - Workflow actions now refresh `data\derived\scoreboard.parquet`.
  - Long algorithm workflow messages were shortened for cleaner UI display.

### Build

- Rebuilt `build\flet_dist` and `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Verified the packaged native executable starts on a separate local port.

## 2026-07-05 Extended Sweep

### Forecast Calibration

- `src\etf_cockpit\models\calibration.py`
  - Replaced the previous placeholder with local forecast-history loading, matured-horizon evaluation, OOS MASE, directional accuracy, interval coverage and derived artefact writing.

### Regime And Portfolio Fit

- `src\etf_cockpit\features\regime.py`
  - Added yfinance-only market regime scoring.
  - Added configured-instrument portfolio-fit lookup using benchmark correlation and beta.

### Strategy Templates

- `src\etf_cockpit\signals\strategy_templates.py`
  - Added deterministic strategy-template assignments and descriptions.

### Scoreboard

- `src\etf_cockpit\signals\simple_scores.py`
  - Added calibration, regime, portfolio-fit, strategy-template and backtest-trust fields.
  - Scoreboard now writes parquet, CSV and JSON.
  - Strategy-template CSV is written beside the scoreboard.

### App State And UI

- `src\etf_cockpit\app\state.py`
  - Score refresh and audit export now refresh derived artefacts.
- `src\etf_cockpit\app\components\simple_scores.py`
  - Expanded rows now show calibration, backtest, regime, portfolio fit and strategy-template chips.
- `src\etf_cockpit\app\pages\dashboard.py`
  - Added Regime summary card.
- `src\etf_cockpit\app\pages\data_models.py`
  - Added panels for derived artefacts, market regime, forecast calibration and strategy templates.
  - Fixed a return-placement regression that made this page blank.

### Audit Export

- `src\etf_cockpit\chatgpt_bridge\export_pack.py`
  - Includes scoreboard CSV/JSON, calibration CSV, market regime JSON, strategy-template CSV, per-instrument evidence JSON and a derived manifest.
  - ZIP creation now walks nested directories.

### Tests

- `tests\test_evidence_derivatives.py`
  - Added regression tests for calibration, regime, portfolio fit and strategy-template logic.
- `tests\test_simple_scores.py`
  - Added assertions for new scoreboard columns.

### Package

- Rebuilt `build\flet_dist` and `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Packaged executable smoke-tested successfully on port 8593.
- `scripts\build_windows.bat`
  - Now copies `data\derived` into the portable folder so scoreboard, calibration, regime and strategy-template artefacts ship with the app.

## 2026-07-08 Report Issue Workflow And Evidence-Maturity Sweep

### Governance

- Added root `plan.md`.
- Added Markdown issue tracker under `issues\`.
- Added feature, bug and research task templates.
- Added report-derived open issues and rejected/deferred decisions.
- Closed ISSUE-0001 and ISSUE-0002 with tests and limitations recorded.

### Scoring

- `src\etf_cockpit\signals\simple_scores.py`
  - Added evidence maturity and sanity-warning fields to `SimpleInstrumentScore`.
  - Added `_evidence_maturity` helper.
  - Added maturity/sanity columns to scoreboard export.

### UI

- `src\etf_cockpit\app\components\simple_scores.py`
  - Added Maturity, Sample, Sanity and Evidence warnings chips to expanded instrument rows.
  - Added visible warning text when evidence sanity warnings exist.

### Tests

- `tests\test_simple_scores.py`
  - Added maturity threshold tests.
  - Added unknown-sample test.
  - Added export column assertions.
  - Added UI text assertions for Maturity and Sanity.

### Benchmark Attribution

- `src\etf_cockpit\features\regime.py`
  - Added `build_benchmark_attribution_lookup(...)`.
  - Added explicit benchmark selection support.
  - Added descriptive alpha/beta/correlation attribution labels with no-causality wording.
- `src\etf_cockpit\signals\simple_scores.py`
  - Added benchmark attribution and sector/theme warning fields to score rows and scoreboard export.
- `src\etf_cockpit\app\components\simple_scores.py`
  - Added Benchmark, Beta, Corr, Alpha proxy and Sector/theme chips.
- `tests\test_evidence_derivatives.py`
  - Added benchmark attribution and short-history pending tests.
- `tests\test_simple_scores.py`
  - Added scoreboard/UI assertions for benchmark attribution fields.

### Backtest Payoff Diagnostics

- `src\etf_cockpit\backtest\metrics.py`
  - Added return hit rate, average win/loss return, payoff ratio, expected value and payoff warning fields.
- `src\etf_cockpit\app\pages\backtests.py`
  - Added Hit rate, Payoff, EV/period and Payoff warning columns.
  - Added payoff diagnostics to the Backtest quality text panel.
- `src\etf_cockpit\services.py`
  - Cached backtest results missing required payoff columns are now regenerated.
- `tests\test_backtest_costs.py`
  - Added regression coverage that hit rate is paired with payoff diagnostics.

### Cost Stress Diagnostics

- `src\etf_cockpit\signals\signal_pipeline.py`
  - Added low/base/high cost stress metrics and warnings to signal supporting metrics.
- `src\etf_cockpit\chatgpt_bridge\export_pack.py`
  - Added cost stress fields to audit signal table export.
- `src\etf_cockpit\app\components\tables.py`
  - Signal table context now includes cost stress warning.
- `tests\test_signal_gates.py`
  - Added direct stress metric test.
- `tests\test_release_hardening.py`
  - Added audit signal-table column assertions.

### Model And Backtest Validity

- `src\etf_cockpit\signals\simple_scores.py`
  - Added backtest validity, model contamination risk, model authority reason and calibration-required fields.
  - Added helper for conservative model/backtest authority labelling.
- `src\etf_cockpit\app\components\simple_scores.py`
  - Added Backtest validity, Model contamination and Calibration required chips.
- `tests\test_simple_scores.py`
  - Added validity-label tests and regression coverage that optional model scores cannot rescue weak deterministic evidence.

### Manual Note Source Credibility

- `src\etf_cockpit\data\manual_notes.py`
  - Added source URL, source type category, evidence grade, source credibility, promotional risk, reproducibility and claim-quality fields.
  - Added conservative rule-based credibility labels.
  - Audit markdown now prints credibility metadata.
- `tests\test_release_hardening.py`
  - Added source-credibility classification tests.
  - Added audit markdown assertions for credibility metadata.

## 2026-07-08 Corrected Roadmap And Issue Tracker Repair

### Documentation / Issue Tracker

- `plan.md`
  - Replaced the stale narrow plan with the corrected issue recovery audit, staged product roadmap, missing-feature maturity roadmap, implementation phases, closure rule, rebuild/smoke policy and cross-linked follow-ups.
- `issues\open.md`
  - Rebuilt the open tracker from empty to 59 unresolved issues: `ISSUE-0007`, `ISSUE-0008`, `ISSUE-0010` and `ISSUE-0011` through `ISSUE-0066`.
  - Added per-issue status, type, priority, evidence grade, source links, problem, why it matters, proposed implementation, acceptance criteria, UI requirement, tests, rebuild requirement, plan update requirement and close criteria.
- `issues\closed.md`
  - Added recovery notes preserving completed `ISSUE-0001` to `ISSUE-0006` and `ISSUE-0009` only for their implemented scope.
  - Explicitly recorded that `ISSUE-0007`, `ISSUE-0008` and `ISSUE-0010` are not closed.
  - Added `REJECTED-0008` for options/scalping/0DTE/binary/crypto bot experiments unless separately scoped.

### Code

- No application code was changed in this tracker repair pass.

## 2026-07-09 report.md Tracker Coverage Repair

### Documentation / Roadmap

- `plan.md`
  - Added `2026-07-09 Report.md Coverage Matrix`.
  - Mapped every direct `report.md` recommended issue (`ISSUE-0001` through `ISSUE-0010`) to its closed/open status.
  - Mapped report-derived themes to expanded open issues, including evidence maturity, paper/forward evidence, benchmark/cash/factor attribution, payoff diagnostics, friction, execution realism, overfitting/PBO, news/macro context, optional providers, LLM diary, strategy taxonomy, unsupported assets and future broker-source-of-truth risks.
  - Preserved the rejected/quarantined ideas as `REJECTED-0001` through `REJECTED-0008`.

- `issues\open.md`
  - Added `2026-07-09 Report.md Open Coverage Index`.
  - Cross-linked every unresolved report recommendation to open issues.
  - Made clear that user-facing items remain open until they are implemented, visible in the UI, tested, rebuilt and smoke-tested.

- `issues\closed.md`
  - Added `2026-07-09 Report.md Closed And Rejected Coverage Index`.
  - Explicitly documented which report items are completed, which linked follow-ups remain open, and which report ideas are rejected.

### Code

- No application code was changed.

## 2026-07-09 Long-Term Automation Roadmap Plan Addition

### Documentation / Roadmap

- `plan.md`
  - Added `Long-Term Automation Roadmap: Advisory-First, Automation-Gated`.
  - Added future automation modes: disabled, supervised ticket only, paper trading, live canary and live constrained.
  - Added explicit deterministic-only automation authority and forbidden direct authority for LLMs, model forecasts, news sentiment, unvalidated data, same-bar execution, unrestricted sizing and unrestricted retries.
  - Added future score stack and scoreboard fields for execution readiness, portfolio fit, model confirmation and automation confidence.
  - Added future ETF due-diligence, stock fundamentals, constrained portfolio allocation, validation, model-governance, execution, kill-switch, compliance and Automation Control Centre UI requirements.
  - Added future automation issue skeletons from `AUTO-0001` through `COMPLIANCE-0001`.

### Code

- No application code was changed.

## 2026-07-09 updatev2.md Roadmap And Tracker Transfer

### Documentation / Roadmap

- `plan.md`
  - Added `2026-07-09 updatev2.md Coverage Matrix`.
  - Preserved non-negotiable advisory-only rules.
  - Added provider registry/source authority, evidence ledger, official filing, ETF disclosure, candle, UI workflow, backtesting and `REPORT.md` update requirements.
  - Added updatev2 implementation order slices A through F.

- `issues\open.md`
  - Added `2026-07-09 updatev2.md Open Coverage Index`.
  - Added namespaced open implementation issues `UPDATEV2-0010` through `UPDATEV2-0030`.
  - Used namespaced IDs because updatev2's proposed `ISSUE-0010` through `ISSUE-0030` conflict with existing tracker IDs.

- `issues\closed.md`
  - Added `updatev2.md Research Closures`.
  - Added research-only closures `CLOSED-RESEARCH-001` through `CLOSED-RESEARCH-006`.

- `REPORT.md`
  - Created the project report file required by updatev2.
  - Added source links and the required 2026-07-09 research update structure.

- `ISSUES.md`
  - Created root index pointing to `issues\open.md`.
  - Added updatev2 issue checklist and close rule.

- `CLOSED.md`
  - Created root index pointing to `issues\closed.md`.
  - Added updatev2 research closure checklist.

- `.ai_worklog\PLAN.md`
  - Added compact updatev2 roadmap summary for future agents.

### Code

- No app/runtime code was changed.

## 2026-07-09 Score History And Mini Chart Roadmap Addition

### Documentation / Roadmap

- `plan.md`
  - Added score-history storage and mini chart requirements.
  - Promoted `ISSUE-0067` into Current Open Priorities and Phase B implementation order.
  - Added `Score History And Score Evolution Charts` with `score_history.parquet` and `score_metric_history.parquet` schemas.

- `issues\open.md`
  - Added `ISSUE-0067 - Local score history and per-instrument score evolution mini charts`.
  - Included acceptance criteria for local score snapshots, metric/component score history, idempotent run writes, expanded-row chart UI and tests.

- `ISSUES.md`
  - Added `ISSUE-0067` under high-priority user additions.

- `.ai_worklog\PLAN.md`
  - Added compact roadmap note for score history.

### Code

- No app/runtime code was changed.

## 2026-07-09 Simple Scores Grey Panel UI Fix

### UI

- `src\etf_cockpit\app\components\simple_scores.py`
  - Replaced the Flet `ExpansionTile` score rows with custom dark themed expandable rows.
  - Added an explicit score-details expander button.
  - Preserved x/10 score display, decision labels, component details and explanation rows.

- `src\etf_cockpit\app\pages\dashboard.py`
  - Moved the score legend and score list above the Activity log so scores are visible in the first viewport.
  - Simplified the Activity log rendering and removed selectable/over-expanding text patterns.

- `src\etf_cockpit\app\pages\signals.py`
  - Removed nested scrolling from the score panel to prevent blank/grey render areas.

### Tests

- Focused score/startup tests pass.
- Full pytest suite passes.
- Rendered source UI was checked in Chrome at `http://127.0.0.1:8562/`.

## 2026-07-09 Two-Tier Universe Implementation

### Config / Data

- `configs\universe.yaml`
  - Replaced old configured instruments with the requested primary tier.
  - Added `analysis_tier`, `data_policy` and `instrument_type` metadata.
- `configs\data_providers.yaml`
  - Updated primary yfinance symbol map to exact requested Yahoo tickers.
- `configs\portfolio_targets.yaml`
  - Switched to analysis-only zero instrument targets with 100% cash target.
- `configs\costs.yaml`
  - Removed stale deleted IDs and added primary tier overrides.
- `data\raw\trade_candidates\yahoo_trade_candidates_2026-07-09.csv`
  - Added requested secondary tier yfinance-only instruments.

### UI / Scoring

- `src\etf_cockpit\signals\simple_scores.py`
  - Added tier metadata to simple score rows.
  - Added pending primary rows when no current signal exists.
  - Added pending secondary rows from the latest candidate CSV.
  - Made latest secondary CSV authoritative over stale candidate reports.
- `src\etf_cockpit\app\components\simple_scores.py`
  - Row subtitle now shows tier, yfinance ticker, ISIN and instrument type.
- `src\etf_cockpit\app\pages\dashboard.py`
  - Summary count now shows primary/secondary counts.
- `src\etf_cockpit\app\pages\signals.py` and `settings.py`
  - Updated copy from configured/candidate wording to tier wording.

### Tests / Docs

- Added simple-score tests for the two-tier universe, duplicate checks and pending visibility.
- Added `ISSUE-0068` and updated plan/worklog documentation.

### Follow-up Hardening / Packaging

- `configs\ui_settings.yaml` and `src\etf_cockpit\core\config.py`
  - Updated the default ETF from deleted `WORLD_CORE` to `VWCE`.
- `src\etf_cockpit\services.py`
  - Filtered startup snapshot prices/holdings to the active configured universe.
  - Added an explicit empty-backtest report for the no-refresh pending state.
- `src\etf_cockpit\features\feature_pipeline.py`
  - Made empty feature/latest-feature frames safe.
- `src\etf_cockpit\app\pages\backtests.py`
  - Added a pending/unavailable backtest state when no current-universe price data exists.
- `src\etf_cockpit\audit\local_llm.py` and `src\etf_cockpit\chatgpt_bridge\export_pack.py`
  - Hardened local audit/export paths for empty signal/backtest data.
- `Launch_Latest_ETF_AI_Cockpit.bat`
  - Added root launcher that builds and launches the latest portable app.
- `scripts\create_desktop_shortcut.ps1`
  - Added/fixed desktop shortcut creation for the launcher.
- `tests\test_release_hardening.py`, `tests\test_risk_analytics.py`, `tests\test_yfinance_provider.py`
  - Updated active-universe fixtures to the new `VWCE`/`EXX1` primary universe.

## 2026-07-08 Button Reliability And Progress Sweep

### UI / Workflow

- `src\etf_cockpit\app\state.py`
  - Added `ActivityEntry`, persistent activity log writing and recent activity loading.
  - Added `begin_activity`, `update_activity`, `finish_activity` and `fail_activity`.
- `src\etf_cockpit\app\router.py`
  - Added a global progress strip for active workflows.
  - Added direct `navigate_to()` rendering so sidebar/custom navigation visibly changes pages.
- `src\etf_cockpit\app\pages\dashboard.py`
  - Added dashboard Activity log panel.
  - Converted long dashboard actions to background workers with progress and visible completion/failure text.
  - Added progress logging for Renew/import dialog actions and audit export.
  - Switched route buttons to direct rendered navigation.
- `src\etf_cockpit\app\pages\chatgpt_audit.py`
  - Added activity status updates for audit export/import, LM Studio check and commentary generation.
- `src\etf_cockpit\app\pages\settings.py`
  - Added visible settings save status and activity logging.

### Forecast Workflow

- `src\etf_cockpit\services.py`
  - Added `live_optional_models` switch for yfinance forecast runs.
  - Added helper to disable only TimesFM/Toto for bounded dashboard runs while preserving baseline forecasts.
- `src\etf_cockpit\app\state.py`
  - Dashboard forecasting now uses the bounded path and reports that uncached live TimesFM/Toto are not allowed to block the main workflow.

### Tests

- `tests\test_flet_startup.py`
  - Added activity-log persistence coverage.
  - Added background workflow progress coverage.
  - Added regression test that main forecasting disables uncached optional models.
  - Added navigation regression coverage for direct rendered routes.

## 2026-07-09 Trust-Critical Tracker Pass

### Documentation / Tracker

- `plan.md`
  - Added the 21 trust-critical implementation programme, execution order, required stores, UI surfaces and release gate.
- `issues\open.md`
  - Added the 21 selected release-issue index.
  - Added `ISSUE-0069 - Single-file session action logging and diagnostics trace`.
- `ISSUES.md`
  - Added `ISSUE-0069` and the selected 21-issue checklist.
- `.ai_worklog\PLAN.md`
  - Added the active programme, selected issue list, required stores and sweep rules.
- `.ai_worklog\WORKLOG.md`
  - Logged the start of the implementation sweep and current code-surface inspection.

## 2026-07-09 Trust-Critical Source/UI/Export Pass

### Source

- `src\etf_cockpit\core\session_log.py`
  - Added current-session JSONL logging with redaction and non-fatal write behaviour.
- `src\etf_cockpit\app\flet_app.py`
  - Initialises `logs/session.jsonl` on new app server start.
- `src\etf_cockpit\app\state.py`
  - Connected activity lifecycle events to session logging.
- `src\etf_cockpit\app\router.py`
  - Added navigation routes for Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures and News & Context.
  - Logs navigation button clicks.
- `src\etf_cockpit\data\trust_artifacts.py`
  - Added provider probe, identity, source conflict, evidence ledger, score component, score history, feature driver, correlation cluster and benchmark attribution artefact writers/loaders.
- `src\etf_cockpit\core\paths.py`
  - Added local raw evidence folders for filings, SEC EDGAR, ESEF, PRIIPs KIDs, ETF reports, index methodology and RSS.
- `src\etf_cockpit\signals\simple_scores.py`
  - Added friction-adjusted edge/cost fields.
  - Emits score rows suitable for evidence ledger/history and audit export.
- `src\etf_cockpit\data\trade_candidate_analysis.py`
  - Hardened yfinance fundamentals handling so missing fields are explicit rather than scored as bad evidence.
- `src\etf_cockpit\chatgpt_bridge\export_pack.py`
  - Expanded audit export with trust evidence stores, checksums, redacted config/docs snapshots and session log.

### UI

- `src\etf_cockpit\app\pages\trust_evidence.py`
  - Added Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures and News & Context pages.
- `src\etf_cockpit\app\pages\diagnostics.py`
  - Added session-log diagnostics panel.
- `src\etf_cockpit\app\components\simple_scores.py`
  - Added score history display in expanded rows.
  - Fixed the grey-panel bug by restoring the missing `_score_tile()` return path.

### Tests

- `tests\test_trust_critical_artifacts.py`
  - Added tests for session log reset/redaction, trust artefact stores, route registration and audit export inclusion.
- `tests\test_simple_scores.py`
  - Added regression check that the Simple Scores tile list contains real instrument row controls.

### Packaging / Smoke

- Rebuilt with `.\scripts\build_windows.bat`.
- Verified packaged app on `http://127.0.0.1:8550/`.
- Verified real Chrome/Windows screenshots for main scores, row expansion and new trust pages.

## 2026-07-09 Launcher, Sparebanken And Reliability Execution

### Added

- `scripts\launcher_core.py`
  - Shared launcher/build helper with root resolution, Python resolution, port probing, readiness waiting, browser opening, project process discovery and locked build/output folder handling.
- `scripts\smoke_app.py`
  - Local smoke helper for source/native/launcher modes with HTTP readiness and Simple Scores group validation.
- `tests\test_launcher_workflow.py`
  - Regression coverage for launcher helper interfaces, generated batch script expectations and locked-folder handling.
- `HANDOFF.md`
  - Durable resume summary and exact continuation prompt.

### Changed

- `ETF_AI_Cockpit.bat`
  - Starts source reliably through the shared launcher helper, waits for readiness and opens the browser only after the local web app responds.
- `Run_ETF_AI_Cockpit_EXE.bat`
  - Uses the shared helper for native/portable startup, with a controlled batch fallback if Python is unavailable.
- `Launch_Latest_ETF_AI_Cockpit.bat`
  - Builds then launches the latest portable runner, with direct helper fallback.
- `scripts\build_windows.bat`
  - Uses launcher helper cleanup for `build\flet_dist`.
  - Creates an alternate timestamped portable output folder when the existing portable folder is locked.
  - Writes the selected portable output to `build\portable_outdir.txt`.
- `src\etf_cockpit\app\flet_app.py`
  - Treats a busy non-HTTP port as unavailable instead of successful reuse.
  - Falls back to a free local port when needed.
- `data\raw\trade_candidates\yahoo_trade_candidates_2026-07-09.csv`
  - Added 15 distinct Sparebanken equity-certificate rows.
  - Unknown ISINs remain `needs_verification`.
- `src\etf_cockpit\signals\simple_scores.py`
  - Added grouped score sections and source-group handling.
  - Added `isin_status` and equity-certificate handling.
- `src\etf_cockpit\app\components\simple_scores.py`
  - Added grouped Simple Scores section rendering.
- `src\etf_cockpit\app\pages\dashboard.py`
  - Main page now renders grouped Simple Scores sections and counts Sparebanken rows separately.
- `src\etf_cockpit\app\pages\signals.py`
  - Scores page uses the same grouped sections.
- `src\etf_cockpit\app\pages\settings.py`
  - Settings copy names the primary, secondary and Sparebanken groups honestly.
- `src\etf_cockpit\data\trade_candidate_analysis.py`
  - Preserves candidate tier/policy/type metadata and treats equity certificates as stock-like evidence.
- `src\etf_cockpit\data\yfinance_provider.py`
  - Added a public Yahoo symbol-shape validator.
- `src\etf_cockpit\data\trust_artifacts.py`
  - Carries group/ISIN status into trust artefacts and updates score schema version.
- Tests updated:
  - `tests\test_flet_startup.py`
  - `tests\test_simple_scores.py`
  - `tests\test_yfinance_provider.py`

### Generated Verification Artefacts

- `build\portable_outdir.txt`
- `browser-mcp-main-sparebanken-groups.png`
- `browser-main-top.png`
- `browser-main-tall.png`
- `browser-main-very-tall.png`
- `browser-row-expand-attempt.png`
- `browser-direct-providers.png`
- `browser-direct-evidence.png`
- `browser-direct-filings.png`
- `browser-direct-etf-disclosures.png`
- `browser-direct-news-context.png`
- `browser-direct-diagnostics.png`

### Checkpoint Status

- No Git commit was created because the app root is not a Git repository.

## 2026-07-11 Wave 0 Task 2 Changes

- Added typed operational-event models and event-store loading/projection over the existing `logs/session.jsonl` trace.
- Added redaction-before-hashing, event IDs, prior/current hashes, legacy-row support, incomplete-tail quarantine and contextual complete-row integrity errors.
- Added Diagnostics recovery/integrity status and trace-derived AppState activity projection.
- Removed the default `WorkflowController` secondary `logs/workflow.jsonl` writer while retaining explicit adapter-path compatibility for tests; corrected dashboard copy to `logs/session.jsonl`.
- Added observable workflow-authority and dashboard-path regressions. Final independent re-review approved Task 2; no issue closure, Task 3 work or execution-authority change.

## 2026-07-11 Final Package Evidence

- Rebuilt the package after all follow-up trust-policy source changes.
- Verified the launcher against the selected package from its own working directory, including port reuse and non-HTTP busy-port fallback.
- Added current wave4 closure evidence and SHA-256 sidecars for the three final evaluator-ready dossiers.
- Updated canonical issue trackers, report, closure matrix, plan state, run state and handoff to the honest 4/41 ready, 37 open result.

## 2026-07-11 Trust Policy Review Fixes

- Session logging now redacts env-prefixed API keys, access tokens, client secrets and `Authorization: Bearer` values end-to-end.
- Audit archive validation now rejects those raw secret forms and requires an explicit unavailable marker when an allowed required artefact is absent.
- Deterministic score aggregation and persisted ledger/component rows now exclude source-less, non-OK and `model:*` components; model rows remain visible as advisory confirmation.
- Audit export regression coverage now asserts conflict CSV/JSON artefacts and complete configured-universe holdings export.

## 2026-07-11 Follow-Up Review Fixes

- Centralised robust text redaction for assignment and JSON-style secret values and reused it in workflow logs.
- Restricted simple-score aggregation to the known component source IDs and labelled model rows `model_advisory` with zero authority rank.
- Declared candle context, conflict CSV and full portfolio summary as audit manifest requirements with explicit unavailable markers where applicable.

## 2026-07-10 ISSUE-0035 Closure

- Added checksum-backed `ISSUE-0035` dossier and six gate records under `evidence/final/`.
- Updated the closure matrix, open/closed trackers, report, plan and handoff state to reflect 4/41 evaluator-ready records.
- Preserved Playwright desktop/1040px/dashboard screenshots and the zero-error console log under `evidence/final/browser/`.

## 2026-07-10 Data Health Responsive UI

- `src/etf_cockpit/data/health.py`: inventory now covers forecast CSVs, backtest cache and macro directory state with checksum/provenance and explicit failure states.
- `src/etf_cockpit/app/pages/data_health.py`: metadata is rendered in responsive evidence rows instead of a horizontally clipped 11-column table.
- `tests/test_data_health.py`: added mixed-state and UI label coverage; the Flet traversal handles list and singular child properties.

## 2026-07-10 Packaged Browser Matrix

- Added `evidence/wave3/browser/computer-use-matrix.txt` with route-by-route visual observations and limitations.
- Confirmed the packaged UI displays `needs_verification` for unknown Sparebanken ISINs and `N/A`/Manual Review for unavailable score inputs.
- Confirmed Data Health CSV export gives a visible success message and a concrete local output path.
- Kept strict parser/provider and broad product issue records open pending full evidence dossiers.

## 2026-07-10 Task 23 Partial Closure

- Added evaluator-ready evidence dossiers for `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028`.
- Updated `configs/closure_matrix.yaml`, `issues/open.md`, `issues/closed.md`, `ISSUES.md`, `CLOSED.md`, `REPORT.md`, `plan.md` and the approved closure plan with the three verified closures.
- Left all other issue records unchanged in `still_open` state.

## 2026-07-10 Source Foundation Gate

- Normalised `FilingsXbrlOrgProvider.list_filings()` to return a DataFrame in `ProviderResult.data` and added a regression test.
- Removed two unused imports found by the scoped Ruff gate.
- Updated durable execution state and worklogs before the package gate.

## 2026-07-10 Reviewer Findings Integration

- Added selected native/portable build-manifest resolution to the launcher helper and smoke path.
- Made yfinance targeted requests honour their requested subset and reject partial refreshes.
- Made provider probe artefacts conservative until an actual bounded probe or refresh succeeds.
- Added missing/stale health failure signalling, nested secret-safe session redaction and route-history updates.
- Moved audit manifest generation after the combined packet and reject unlisted archive members.
- Added empty-state handling for legacy instrument detail and canonical loading of revision-protected universe records.
- Routed reference, FX and manual-note clean/metadata writes through atomic groups.
- Run-specific launcher and Sparebanken records are closed with tests, rebuild and browser evidence.
- Broad product issues remain open unless their full close criteria were already met by earlier work.

## 2026-07-10 Post-Review Changes

- `Launch_Latest_ETF_AI_Cockpit.bat`: reads `build\portable_outdir.txt`, validates and launches the selected portable runner, retaining the fixed versioned path only as fallback.
- `scripts\build_windows.bat`: selects alternate native staging when locked, uses delayed expansion for values read inside batch blocks, checks the selected executable, and rewrites `build\native_outdir.txt` after Flet packaging.
- `tests\test_launcher_workflow.py`: added regression coverage for selected portable output, locked native staging, delayed expansion and path-manifest persistence.
- `tests\test_simple_scores.py`: isolated persisted candidate loaders in the no-refresh pending-state test.
- Added final browser evidence `browser-final-launch-latest.png` and `browser-final-launch-latest-locked-folders.png`.
- No Git commit was created because the app root is not a Git repository.
