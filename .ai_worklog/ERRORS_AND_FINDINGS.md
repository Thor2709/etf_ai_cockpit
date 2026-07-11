# Errors And Findings

## 2026-06-27

- Spec gap: `configs\data_providers.yaml` is missing, so the requested provider abstraction is not configurable yet.
- Spec gap: `.env.example` only contains two API key names and does not document provider/base URL placeholders or secret-handling expectations.
- Spec gap: the dashboard `Update data` button currently calls `refresh_sample_data()` and regenerates sample files instead of opening a local import/API/dry-run workflow.
- Spec gap: `src\etf_cockpit\data\providers.py` only defines a price provider with `fetch_daily_prices()` and `validate_symbol()`, while the addendum requires prices, FX, ETF metadata and ETF holdings provider methods.
- Spec gap: EODHD and Alpha Vantage provider classes raise `NotImplementedError`; safe API-placeholder behaviour should return a clear unavailable result instead of crashing.
- Spec gap: required dataset provenance fields (`source_name`, `source_type`, `as_of_date`, `ingested_at`, `currency`, `timezone`, `provider_or_manual_source`, `checksum`, `staleness_status`) are not yet represented.
- Spec gap: storage currently has `data\raw`, `data\validated`, `data\features`, `data\backtests` and `data\chatgpt_exports`, but not the requested `data\clean`, `data\derived`, `data\snapshots`, `data\audit_packets` and `data\reports` layout.
- Spec gap: price freshness currently blocks after two business days instead of using OK <= 3, warning 4-10 and block > 10 trading days.
- Risk finding: `configs\portfolio_targets.yaml` sets `WORLD_CORE` target weight to 42% while `configs\risk_limits.yaml` caps a single ETF at 35%; current config validation allows this instead of requiring an override/manual review.
- Spec gap: `SignalResult.action` and UI still use older `buy` and `sell` terms; the addendum requires release-facing advisory actions only.
- Spec gap: critical validation failures can result in `no_trade`; the addendum requires `trading_allowed=false` and `manual_review`.
- Spec gap: signal support metrics are missing required fields such as edge-to-cost ratio, minimum trade value, reason classifications and final action aliases.
- Spec gap: `_price_pivot()` in the backtest engine uses `.ffill().dropna()`, which conflicts with the no-silent-forward-fill rule unless it is explicitly controlled and reported.
- Spec gap: backtest output lacks the requested quality diagnostics and honest quality label.
- UI bug found and fixed: Flet 0.85.3 did not display the Renew Data dialog when using old `page.dialog = dialog; dialog.open = True`; switching to `page.show_dialog()` made the dialog visible in source and packaged builds.
- Packaging finding: the first rebuild could not overwrite `build\flet_dist\ETF_AI_Cockpit` because the old packaged `ETF_AI_Cockpit.exe` process was still running on port 8550 and locking DLLs. Confirmed the path, stopped that project process, and rebuilt successfully.
- Verification note: browser console retained old error entries from the prior source-server session on port 8551, but fresh screenshots after reload showed the packaged app rendered correctly and the Renew Data dialog worked.
- User-visible launcher issue: `ETF_AI_Cockpit.bat` was not the best file to open after packaging because it ran dependency installation and the development app path instead of the packaged executable.
- Packaging finding from prior build loop: Flet packaging required PyInstaller and a non-interactive `-y` flag to avoid a build prompt.
- Packaging status before this pass: `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` existed and had previously stayed running during a timed launch check.
- Model adapter finding: the Toto 2.0 docs use `from toto2 import Toto2Model`; the project adapter previously checked/imported `toto`, which is the legacy Toto 1.0 package path.
- Render finding: Flet opened the desktop shell with title and background, but no content, because startup depended on `page.go("/")` firing the first route-change event. If Flet was already at `/`, no route-change render occurred.
- Flet runtime finding: a minimal Flet desktop app also opened as a blank white shell, proving the remaining blank screen was caused by the installed Flet/Flutter desktop client on this Windows system, not by the cockpit dashboard code.
- Browser validation finding: the direct-controls workaround briefly caused `views list is empty`; shell rendering now keeps a root `View` and replaces it atomically.
- Packaging finding: PyInstaller/Flet marks the app as embedded, so the packaged exe still selected the desktop socket renderer unless `FLET_FORCE_WEB_SERVER=true` was set explicitly.
- Packaging finding: the first web-mode package did not include `flet_web`, FastAPI/Starlette/Uvicorn hidden imports or Flet web assets, so the exe stayed running without a usable browser UI.
- Packaged web-server finding: windowed PyInstaller sets `sys.stderr` to `None`; Uvicorn's logging formatter crashed with `AttributeError: 'NoneType' object has no attribute 'isatty'` until stdout/stderr were attached to log files.
- Launcher finding: `timeout /t` prints `Input redirection is not supported` in non-interactive launches. The batch wait loop now uses `curl.exe` plus PowerShell `Start-Sleep`.
- Launcher finding: the custom in-app browser-open watcher could hold the first HTTP request open. The batch launcher now opens the browser after its own successful readiness check; direct exe launch uses Flet's normal browser opening.
- Backtest correctness finding: the rebalance loop generated signals and assigned new weights before applying the same row's return, creating a same-bar execution risk. Fixed by scheduling new weights and transaction costs for the next available price row and recording both signal and execution dates.
- Validation finding: current portfolio holdings concentration and residual cash were not part of the hard data-quality report. Fixed by adding holdings validation and wiring it into snapshots, signal generation and dry-run validation.
- Risk finding now enforced: sample `WORLD_CORE` has current weight 45.5% and target weight 42%, both above the configured 35% cap. Current data is correctly blocked and final actions are `manual_review`.
- Packaged UI runtime bug found by browser verification: clicking `Renew data` raised `FilePicker.__init__() got an unexpected keyword argument 'on_result'` in Flet 0.85. Fixed by using the current async `FilePicker.pick_files()` API and handling web-mode uploaded file bytes when no filesystem path is exposed.
- Data lifecycle finding: price imports created previous snapshots, but no user-facing rollback existed. Fixed with a rollback action that restores the latest previous clean price snapshot and preserves the replaced current price store.
- Rollback correctness finding: snapshot files are copied with preserved modification times, so mtime sorting can select the wrong rollback candidate. Fixed by sorting timestamped snapshot filenames.
- UI/spec gap: the addendum requested a dedicated Risk page with concentration, exposures, correlation and drawdown contribution. The app only exposed partial risk context through the Portfolio page. Fixed by adding `/risk` with deterministic exposure-limit, correlation and drawdown contribution tables.
- Spec gap: audit export still wrote `No live news provider is configured in the MVP` and there was no persisted manual thesis/news import path. Fixed with validated local manual-news imports, clean Parquet storage, snapshots and audit export inclusion.
- Safety finding: imported manual notes could include an `executable_authority` field from an external file. The importer now ignores any truthy source value and forces `executable_authority=false`, with a warning recorded in commit metadata.
- UI finding: the first Data & Models manual-note panel was added below existing panels and was hard to reach in the packaged Flet canvas renderer. Fixed by moving model availability, provenance, manual notes and validation issues into a first-viewport right-side evidence stack.
- Browser verification note: the Browser console API continued reporting generic historic Flet `main.dart.wasm` `Exception` entries for the localhost session, but packaged Python `stdout.log` and `stderr.log` were empty and screenshots confirmed the dashboard, Renew Data dialog and Data & Models page rendered correctly.
- Spec gap: ETF factsheet/reference metadata and underlying ETF holdings had provider methods but no validated clean import workflow. Fixed with local import, strict date/identifier validation, staleness classification, raw/clean/snapshot storage and Data page visibility.
- Validation finding: ETF holdings files often use percentage weights, but silently treating a `weight=60` column as 60% would be ambiguous. The importer now only converts explicitly named `weight_percent`/`weight_pct`; plain `weight` must be decimal in [0, 1].
- Spec gap: FX had provider config and an interface method but no local clean import workflow. Fixed with dated pair/rate validation, raw/clean/snapshot storage, Data page visibility and audit inventory export.
- Validation finding: FX imports can encode pairs as `USD/EUR`, `USDEUR`, `USD-EUR` or as base/quote currency columns. The importer normalises valid three-letter pairs and rejects malformed values rather than guessing.
- Spec gap: imported ETF holdings were visible as inventory but not yet used by the Risk page. Fixed by adding portfolio-weighted underlying sector/region/currency exposure, with an explicit empty state when no holdings file is imported.

## 2026-06-28

- Spec gap: advanced backtest diagnostics were present in the result schema but remained effectively unestimated (`None`/`not_run`) and the Backtests page described them as not-run. Fixed by adding deterministic local estimates for probabilistic Sharpe, deflated Sharpe, a CSCV-style PBO proxy and parameter sensitivity.
- Release-quality caveat: the new advanced diagnostics are lightweight local estimates from the available sample series and realised trade logs. They are useful for honesty and regression visibility, but they are not institutional-grade validation or proof of future performance.
- Packaged UI finding: direct browser startup at `http://127.0.0.1:8550/backtests` rendered a blank Flet shell while opening `/` and clicking Backtests rendered correctly. Root cause was startup code redirecting any non-default initial route back to `/`. Fixed by preserving the initial route and adding a regression test.
- Packaging note: PyInstaller still reports the optional hidden import warning `scipy.special._cdflib` during build. The rebuilt package starts, renders root and `/backtests`, and has empty packaged stdout/stderr logs, so this remains a build-analysis warning rather than a runtime failure.
- Spec/UI wording gap: the export workflow was still labelled as a `ChatGPT pack`/`Review Pack` and wrote new ZIPs under the legacy `data\chatgpt_exports` directory. Fixed by switching default exports to `data\audit_packets\audit_packet_YYYY-MM-DD.zip` and changing visible wording to neutral external audit terminology.
- Stale UI text finding: after renaming the Audit page, the shared footer still said `ChatGPT audit is commentary only`. Fixed to `External audit is commentary only` and verified in the packaged browser screenshot.
- Spec gap: there was no optional local LLM audit layer for LM Studio commentary. Fixed with a manual Audit page workflow, local status checks, schema validation and non-executable report saving.
- Local LLM probe finding: LM Studio was not listening on `localhost:1234` during verification. The app now reports this as optional `unavailable` status without affecting startup or deterministic signals.
- Verification-command finding: two ad hoc Python probes failed before the real local LLM status check, first from shell quoting and then from missing `PYTHONPATH=src`. Reran with the correct project import path and logged the actual optional-unavailable result.
- Safety gap: the Dashboard `Create trade proposal` action had no durable report workflow. Fixed with a non-executable JSON report that only proposes manual review candidates when all data-quality gates allow it and otherwise records the block reasons.
- Packaging-root finding: packaged executable runs could resolve `ROOT` to `build\flet_dist\ETF_AI_Cockpit\_internal` because the resolver searched from `__file__` before considering the launcher folder. Fixed by preferring a valid `ETF_COCKPIT_ROOT` and valid current working directory, and by setting `ETF_COCKPIT_ROOT` in launchers.
- Verification-command finding: one source smoke command referenced `CockpitSnapshot.backtests`, which does not exist. The app snapshot uses `CockpitSnapshot.backtest`; reran with the correct attribute and the smoke passed.
- Log hygiene finding: `logs\stderr.log` still contains a stale 2026-06-27 port-binding traceback from an earlier overlapping launch. The file was not modified by the current 2026-06-28 packaged verification, and the current browser/HTTP/startup checks passed.
- Spec gap: FX imports existed, but portfolio holdings validation did not require or use FX rates when a holding currency differed from the portfolio base currency. Fixed by requiring dated base-currency conversion evidence for non-EUR/non-base holdings before reconciliation.
- Packaging failure: a rebuild after the FX validation change failed during PyInstaller `COLLECT` because a stale packaged process on port 8550 locked files in `build\flet_dist`. Stopped PID `90928` and rebuilt successfully.
- Release-hardening finding: repeated launches could start a second packaged process while the first server was already running, causing a hidden port-binding traceback in `logs\stderr.log`. Fixed with preflight reuse checks in Python and batch launchers.
- Spec gap: Settings displayed provider/API fields but they were read-only, so API details could not be added through the UI. Fixed with editable provider/base URL/API key fields and local persistence that keeps API keys out of YAML, logs and exports.

## 2026-06-30

- Model archive finding: `timesfm-2.0.1.zip` and `toto-toto-models-v1.0.0.zip` contain source/reference package material but no obvious runtime checkpoint or weight files. They must stay under `models\source_archives`; they are not sufficient to enable live TimesFM/Toto scoring.
- Model safety finding: app model availability correctly remains `baseline=True`, `timesfm=False`, `toto=False` after archive placement. This prevents duplicate baseline forecasts from being misrepresented as unavailable model output.
- Local LLM finding: LM Studio is now reachable at `http://localhost:1234/v1`; the app status check auto-selects `qwen3.6-27b` because `configs\local_llm.yaml` leaves `model` blank.
- Verification-command finding: two first Python smoke probes used Bash heredoc syntax in PowerShell and failed before app code ran. Re-ran the same checks with PowerShell-safe `python -c` commands and the checks passed.
- Repository finding: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit` is not a Git repository, so local file changes were verified by direct file inspection and tests rather than `git status`.

## 2026-06-30

- Model implementation gap: the previous TimesFM/Toto adapters only checked imports and then returned deterministic mock-style forecasts; they did not implement the documented Hugging Face live inference paths. Fixed by adding optional live adapter paths for `TimesFm2_5ModelForPrediction` and `Toto2Model`.
- Availability correctness finding: the previous Toto availability regression allowed an empty runtime folder to count as live. Fixed by requiring weight-like files in the local checkpoint folder before TimesFM/Toto can report available.
- Local-first safety finding: Hugging Face repo IDs are now configured, but `local_files_only=true` and `allow_remote_download=false` remain the defaults, so normal startup and availability checks do not download models.
- Forecast semantics finding: TimesFM produces future time-series levels, while Toto 2.0 model-card output is probabilistic return/path evidence when fed adjusted log returns. The adapters now convert those outputs into horizon log-return fields used by the cockpit audit model.
- Packaging retry finding: the first rebuild after model-adapter changes failed in PyInstaller `COLLECT` because old packaged PID `91120` held files under `build\flet_dist\ETF_AI_Cockpit`. Stopped that project process and reran the build successfully.
- Log hygiene note: `logs\stderr.log` still contains stale 2026-06-28 port-bind output, but its timestamp did not change during the 2026-06-30 package smoke.

## 2026-06-30

- Data modelling finding: the user-supplied Yahoo list mixes ETFs and individual stocks and includes a ticker collision risk around `SXRJ`. The analysis workflow is therefore separate from the app's configured ETF universe and does not replace the main clean price store.
- Provider finding: yfinance data can vary by Yahoo listing and is not a guaranteed institutional feed. The provider records `source=yfinance`, uses adjusted close when present and still runs through cockpit validation before any configured-provider commit.
- Candidate-analysis finding: Veolia share count is ambiguous (`8 or 7` in the user note). The generated analysis uses 8 shares and flags `share_count_ambiguous_8_or_7`.
- Candidate-analysis finding: Saint-Gobain screened as `no_trade` on price-only evidence because it was below SMA200 and had negative 6m/12m evidence in the fetched Yahoo series.
- Packaging note: adding yfinance increased the packaged exe size and PyInstaller emitted optional hidden-import warnings for generated parser tables and SciPy. Startup smoke still passed.

## 2026-06-30

- Environment finding: the existing `.venv` was broken because it was a Python 3.12 environment loading incompatible compiled wheels. Preserved it under `backups\venv_broken_20260630_160456` and recreated a Python 3.13 environment.
- Model-layout finding: uploaded safetensors at the project root are ambiguous and easy to bundle accidentally. Moved them into explicit `models\timesfm` and `models\toto` checkpoint folders, and verified no root-level safetensors remain.
- TimesFM checkpoint finding: the uploaded TimesFM safetensor used `mlp.ff0`/`mlp.ff1` state-dict names that do not load into the installed Transformers `TimesFm2_5ModelForPrediction`. Preserved the original and converted the runtime copy to `mlp.fc1`/`mlp.fc2`.
- Toto input-shape finding: Toto failed on the available price panel when context length was not divisible by the checkpoint patch size. Fixed by trimming to the latest complete patch window.
- Package-runtime finding: after optional model runtime installation, the first packaged EXE readiness test failed with `ModuleNotFoundError: No module named 'flet_web'`. Installed `flet-web`, restored `flet_web` add-data/hidden imports in the build script and rebuilt successfully.
- Packaging-size finding: bundling model safetensors into the EXE/package would make the app very large and blur writable model/data boundaries. The build now excludes safetensors and keeps them external under `models\`.
- Verification-command note: one direct Python diagnostics probe failed with `ModuleNotFoundError: No module named 'etf_cockpit'` because it omitted `PYTHONPATH=src`; reran with the launcher-equivalent source path and diagnostics passed.
- Browser-render finding: Flet's DOM snapshot remains minimal until accessibility is enabled, but screenshots and route changes confirmed the dashboard and Data & Models page render correctly with no browser error/warn logs.

## 2026-06-30

- GPU runtime finding: Windows/NVIDIA exposed the RTX 5070 Laptop GPU, but the project `.venv` had CPU-only `torch 2.12.1+cpu`. Replaced it with `torch 2.12.1+cu130`.
- Dependency finding: installing CUDA Torch initially created a metadata conflict (`flet-cli` wanted `packaging>=25`, Lightning 2.4 wanted `packaging<25`). Upgrading `lightning` and `pytorch-lightning` to 2.6.5 resolved `pip check`.
- Forecast-service gap: the project had live TimesFM/Toto adapters, but the central `ForecastService` returned baseline forecasts only. Fixed and added a regression test.
- TimesFM horizon finding: local TimesFM 2.5 Transformers checkpoint is capped at 128 forecast steps, so configured 180-day TimesFM rows cannot be generated. These rows now show `skipped`, null forecast values, no score contribution and `unsupported_horizon` calibration status.
- Toto candidate-model finding: yfinance candidate panel produced a 1279-row tensor after post-trim all-NaN row removal, causing an `EinopsError` because 1279 is not divisible by patch size 32. Fixed by dropping all-missing rows before patch trimming.
- Test-output hygiene finding: the new forecast-service regression test initially overwrote `data\forecasts\forecast_results_20260626.csv` with one-ETF mock rows. Fixed by writing the test output to `tmp_path`.
- Packaging note: bundled internal package config remains from the previous build, but both root launchers set `ETF_COCKPIT_ROOT` to the visible project folder. The normal supported launcher is `ETF_AI_Cockpit.bat`, which uses the Python CUDA runtime first.

## 2026-06-30

- UX finding: the previous UI still presented the app as an ETF portfolio/rebalance cockpit, with old text such as `AI scores remain zero` and `Forecast panel ... disabled/mock-safe`. Fixed by rewriting the UI around evidence scoring, local models and advisory analysis.
- Scoring finding: ForecastService generated Toto/TimesFM CSVs, but the score table did not read those outputs back into component scores. Fixed with `forecast_scores.py` and signal-service integration.
- Product-fit finding: target-policy and concentration findings forced every sample signal into `manual_review`, hiding the algorithm/model ranking the user wanted. Fixed by making those items warnings/context while preserving hard data-quality blocks.
- Rendered UI finding: the first updated desktop tables overlapped headers (`Model components`, `Analysis rating`, `Explanation`) at 1280 px width. Fixed by reducing wide tables to compact evidence columns.
- Rendered mobile finding: fixed 220 px sidebar left the mobile viewport with unusably narrow content. Fixed by adding a narrow-shell top navigation layout and stacking Overview cards.
- Browser-validation finding: port 8550 was serving stale old UI from an existing local server. Used port 8551 for QA to verify current source changes.
- Flet DOM finding: browser DOM snapshot still exposes only the accessibility shell for the canvas-rendered app. Used screenshots plus route URL/title/console checks as the reliable rendered evidence.

## 2026-06-30

- Packaging finding: the first native rebuild after the Evidence Cockpit UI work failed during PyInstaller `COLLECT` because an old `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` process held files in the old build folder.
- Packaging fix: stopped only the stale project-specific `ETF_AI_Cockpit.exe` process, then patched `scripts\build_windows.bat` so a locked or failed native pack exits with an error instead of silently creating a portable folder from stale state.
- Packaging improvement: successful native builds are now copied into `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit`, with `Run_ETF_AI_Cockpit_EXE.bat` added beside the normal Python launcher.
- Packaging verification: rebuilt successfully; native exe `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` responded with HTTP 200 on temporary port 8562.

## 2026-07-01

- YFinance symbol finding: `WORLD_CORE` could not use `IWDA.DE`; live Yahoo probe returned no rows. `IWDA.AS` returned recent EUR rows and is now the configured Yahoo symbol.
- YFinance reference-data finding: Yahoo fund metadata/top-holdings are uneven. Equity ETFs returned usable metadata/top-holdings, while some instruments expose partial or no fund data. The provider now commits available rows and reports partial/unavailable datasets explicitly.
- Validation finding: yfinance data currently produces warnings for missing expected business days, zero volume and some robust return outliers. These are warnings, not hard blocks, and are recorded in the yfinance report.
- Test finding: optional Yahoo action columns may be absent; the first yfinance provider test run caught scalar default handling for missing `Capital Gains`. Fixed by zero-filling missing optional columns as full-length series.
- Forecast warning finding: the yfinance model run exposed a pandas `pct_change` implicit fill warning in benchmark returns. Fixed with `pct_change(fill_method=None)` to avoid implicit forward-fill.

## 2026-07-01

- UI regression finding: after replacing Overview with the simple score list, browser QA showed the shell/sidebar but a blank grey main content area. There was no browser console error and no Python traceback. Root cause was Flet web layout instability from `Row(..., wrap=True)` containing expanded metric cards. Fixed by removing wrapping from expanded card rows.
- UI regression finding: the dedicated Scores route had the same blank grey content area for the same reason. Fixed by removing the wrapped expanded-card row there too.
- Mobile finding: the first mobile viewport check showed summary card labels split/truncated (`Instru ment s`, `Model rows`, `Final mode`). Fixed by stacking summary cards vertically when page width is below 760 px.
- Test harness finding: `test_main_page_exposes_simple_workflow_buttons` initially failed because Flet `Button` labels are stored in `_values["content"]`, not the public `value`/`text` fields used by the test text extractor. Fixed the test helper to read that Flet field.
- Command finding: a direct import probe failed with `ModuleNotFoundError: No module named 'etf_cockpit'` because it omitted `PYTHONPATH=src`. Reran with `PYTHONPATH=src` and the score probe passed.
- Runtime observation: full `run_forecasting_models()` with Toto 1B used nearly all 8 GB RTX 5070 Laptop VRAM and took several minutes for configured ETFs plus candidates. It completed successfully; the UI keeps this as an explicit workflow step, not startup work.
- Packaging-data finding: the first rebuilt portable native package rendered correctly but showed only 7 configured instruments, 0 candidate rows and 0 model rows because the portable folder was not copying current yfinance clean data/reports/forecasts. Fixed `scripts\build_windows.bat` to copy `data\clean`, `data\forecasts`, `data\reports` and `data\raw\trade_candidates` into the portable folder.
- Final package verification: after rebuilding with data-copy rules, packaged native UI rendered 19 instruments, 7 configured and 12 candidates, with model rows loaded and no browser warnings/errors.
## 2026-07-01 Chrome QA Findings

- Finding: Chrome initially showed a blank Flet page for roughly 30 seconds, even though the app eventually rendered.
  - Evidence: first Chrome screenshot was blank; after waiting, the Simple Scores page appeared.
  - Cause: initial snapshot imported/checks live model runtimes and recomputed backtests before rendering.
  - Fix: lightweight model availability checks and cached backtest loading.
  - Verification: smoke startup improved from 34.64 seconds to 1.83-1.93 seconds.
- Finding: Foreground `Run forecasting models` button was too heavy when rerunning current-date 1B Toto/TimesFM candidate forecasts.
  - Evidence: the process consumed GPU/CPU for several minutes after writing configured ETF forecasts, with no UI progress and no fresh candidate output during the wait.
  - Fix: UI workflow now uses the 60-trading-day scoring horizon and reuses current-date forecast CSVs when present.
  - Verification: button completed through Chrome and reported cached configured/candidate forecast summaries.
- Finding: Renew dialog dry-run validation text overlapped action buttons.
  - Fix: dialog content area now has fixed height and internal scrolling.
  - Verification: Chrome dry-run output scrolled inside the dialog and action buttons stayed visible.
- Finding: Instrument Detail still showed raw `+0.xx` scores.
  - Fix: converted cards, model table and analysis summary to x/10 score language.
  - Verification: Chrome screenshot showed Evidence 6.2/10, Toto 8.0/10, TimesFM 7.1/10 and x/10 explanation text.
- Finding: Diagnostics reported `toto` missing while actual runtime is `toto2`.
  - Fix: Diagnostics now checks `toto2`.
  - Verification: Chrome Diagnostics showed `toto2: ok`.
- Finding: Local LLM generation timed out at 12 seconds for reachable `qwen3.6-27b`.
  - Fix: default and project `configs/local_llm.yaml` timeout raised to 60 seconds.
  - Residual note: local generation remains optional and schema-validated; timeout errors are still shown without changing scores.

## 2026-07-04 UI Startup Findings

- Finding: Source Flet web startup could return HTTP 500 before any UI content rendered.
  - Evidence: local request to `http://127.0.0.1:8584/` and `8585/` returned 500.
  - Error: `PermissionError: [Errno 13] Permission denied` while `flet_web.fastapi.flet_static_files` copied `index.html`.
  - Cause: Flet used `tempfile.mkdtemp()` for patched static web files, and Windows created inaccessible temp subdirectories in this environment.
  - Fix: patch Flet's static temp creation in `src/etf_cockpit/app/flet_app.py` to use a deterministic project-local writable folder.
  - Verification: source app returned HTTP 200 on port 8587 with empty stderr; packaged exe returned HTTP 200 on port 8588.
- Finding: Pytest cache/tmp fixtures failed when using locked Windows temp folders.
  - Evidence: full test run errored on `PermissionError` for `AppData\Local\Temp\pytest-of-thor2`, then for project folders created through pytest's numbered-temp helper.
  - Fix: disable pytest cache provider and override `tmp_path` with a compact project-local fixture that creates short writable folders.
  - Verification: tmp-heavy subset and full test suite passed.
- Finding: Chrome extension automation was unavailable in this turn.
  - Evidence: Chrome backend discovery returned `Browser is not available: extension` after retry.
  - Impact: no fresh Chrome visual screenshot could be captured in this turn. Previous Chrome QA remains documented; this turn verified source/package web readiness and tests instead.

## 2026-07-04 Chrome Retest Findings

- Finding resolved: Chrome extension automation became available on retry.
  - Evidence: Chrome opened `http://127.0.0.1:8589/`, captured screenshots, clicked UI controls and read page title/URL.
- Finding: Flet canvas UI does not expose text controls to Chrome text locators.
  - Evidence: `getByText(...)` counts were zero for visible labels.
  - Workaround used for QA: screenshot-guided coordinate clicks.
  - Impact: visual/manual-style Chrome QA works; semantic browser locator testing remains limited until the UI exposes stronger accessibility/test hooks.
- Finding: Some workflow button hit areas are more reliable from the icon/left side than the label/right side in the Flet canvas.
  - Evidence: Run algorithms and Run forecasting models did not fire from all label/right-side coordinates, but succeeded from the icon/left hit area.
  - Fix: replaced the four workflow buttons with fixed-width clickable containers, keeping the same labels/icons/actions.
  - Residual: adding explicit semantic/test hooks would still improve automated locator-based testing.

## 2026-07-05 Report-Driven Implementation Findings

- Finding: the report's proposed scoring model was not fully represented in the simple UI.
  - Evidence: prior rows mainly exposed one final score and individual component scores, without separate evidence quality or risk/friction.
  - Fix: added `evidence_score_10`, `evidence_quality_10` and `risk_friction_10`.
  - Verification: Chrome expanded-row QA showed quality and risk/friction values; `data\derived\scoreboard.parquet` contains the new fields.
- Finding: stock candidates lacked yfinance-derived stock-specific evidence.
  - Evidence: candidate rows were mostly price-only, while the research report recommended valuation, quality and revision modules for stocks.
  - Fix: added yfinance `Ticker.info` extraction and stock proxy scores.
  - Verification: live report showed stock candidates with value, quality and analyst/revision scores where Yahoo exposed fields.
- Finding: model components needed clearer authority labelling.
  - Evidence: a user could see a TimesFM/Toto score without an immediate indication of whether it was independent validated evidence or fallback/partial evidence.
  - Fix: added model-authority labels and component authority/role metadata.
  - Verification: Chrome expanded-row QA showed `Independent AI confirmation available` and authority/role chips.
- Finding: workflow output messages could overflow the main dashboard after algorithm refresh.
  - Evidence: Chrome QA after `Run algorithms` showed long report-path text in the visible status region.
  - Fix: shortened UI action messages while preserving detailed artefacts in logs/reports.
  - Verification: Chrome QA showed the concise success message after the refreshed algorithm run.
- Finding: the first package rebuild attempt was blocked by a stale executable handle.
  - Evidence: `.\scripts\build_windows.bat` reported access denied while refreshing `build\flet_dist`.
  - Cause: old project-specific `ETF_AI_Cockpit.exe` process still running from a previous build.
  - Fix: stopped only the stale `build\flet_dist` executable process, then reran the build.
  - Verification: rebuild completed and the packaged executable returned HTTP 200 on port 8591.
- Residual finding: per-instrument backtest trust and model calibration remain planned.
  - Impact: the UI reports backtest/model authority honestly, but does not yet compute full per-instrument walk-forward trust or OOS calibration badges.
  - Planned fix: implement the calibration and backtest-trust phases documented in `.ai_worklog\PLAN.md`.

## 2026-07-05 Extended Sweep Findings

- Finding resolved: Data & Models page went blank after adding derived-evidence panels.
  - Evidence: Chrome screenshot showed the `Data & Models` title/sidebar but no page content.
  - Cause: `data_models_page()` built `latest_status_panel` and `evidence_panels` but the `return ft.Row(...)` was accidentally left after helper functions, making the page return `None`.
  - Fix: moved the return into `data_models_page()` and removed the unreachable nested return.
  - Verification: focused tests passed and Chrome screenshot showed derived artefacts, Market regime and Forecast calibration panels.
- Finding: current local forecast calibration is correctly pending.
  - Evidence: `data\derived\model_calibration.csv` shows `pending_no_matured_forecasts` for current baseline/TimesFM/Toto rows.
  - Cause: the available forecast artefacts are current 60-day forecasts and the local price panel has not advanced by 60 trading days yet.
  - Decision: do not fake OOS calibration; keep model authority low/pending until real later yfinance prices mature the forecast horizons.
- Finding: candidate portfolio fit is pending.
  - Evidence: candidate expanded rows show `Candidate portfolio fit pending`.
  - Cause: ad-hoc candidate price histories are not yet promoted into a clean candidate history store compatible with portfolio-fit beta/correlation calculation.
  - Planned fix: add a clean candidate price panel if candidate portfolio-fit evidence becomes required.
- Observation: Chrome console still contains extension message-channel noise.
  - Evidence: repeated `A listener indicated an asynchronous response...` entries.
  - Impact: no app-visible failure; no Python traceback; Flet UI rendered and interacted normally.
- Finding resolved: portable package did not include `data\derived`.
  - Evidence: build script copied backtests, clean, features, forecasts and reports but not derived evidence.
  - Fix: patched `scripts\build_windows.bat` and synced `data\derived` into the current portable output.
  - Impact: portable launch now has the same precomputed scoreboard/calibration/regime artefacts as the source app.

## 2026-07-08 Report Issue Workflow Findings

- Finding resolved: initial `python -c` artefact verification could not import `etf_cockpit`.
  - Evidence: command failed with `ModuleNotFoundError: No module named 'etf_cockpit'`.
  - Cause: direct `python -c` does not automatically add `src` to `PYTHONPATH`; pytest does.
  - Fix: reran with `$env:PYTHONPATH='src'`.
  - Verification: scoreboard and audit export generation completed, and the new maturity/sanity columns were present.
- Finding resolved: issue tracker files were briefly created one directory above the project.
  - Evidence: files appeared under `C:\Users\thor2\Desktop\Trading App\issues` while `etf_ai_cockpit\issues` was empty.
  - Cause: `apply_patch` resolved paths relative to the parent workspace, not the project subfolder, during the interrupted pass.
  - Fix: moved the issue files into `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\issues`, moved `plan.md` into the project folder and removed only the empty accidental parent directory.
  - Verification: `Get-ChildItem -Recurse -File issues` shows the issue files under `etf_ai_cockpit\issues`; parent-level `issues` and `plan.md` no longer exist.
- Finding resolved: ISSUE-0006 model/backtest contamination validity was missing.
  - Impact: before this pass, model authority text existed, but score rows did not expose explicit contamination-risk and backtest-validity fields.
  - Fix: added validity fields, UI chips, scoreboard export and regression tests.
  - Residual: resolved in the subsequent ISSUE-0009 pass.

## 2026-07-08 Source Credibility Findings

- Finding resolved: imported manual notes lacked source-credibility metadata.
  - Impact: Reddit anecdotes, screenshots, official docs and research sources could appear too similar in audit notes.
  - Fix: added source type, evidence grade, credibility, promotional risk, reproducibility and claim-quality fields.
  - Verification: focused release-hardening tests and full regression suite passed.
- Limitation: classification is rule-based and conservative.
  - Impact: it labels source quality for audit review but does not verify source contents online and cannot change scores/actions.

## 2026-07-08 Benchmark Attribution Findings

- Finding resolved: benchmark attribution initially depended on pivot-column ordering.
  - Evidence: focused test expected `BENCH` but calculated benchmark was `ALT`.
  - Cause: pandas pivot column ordering was alphabetical, not business-rule aware.
  - Fix: added explicit `benchmark_id` parameter and passed the configured first ETF from the score builder.
  - Verification: focused attribution tests and full test suite passed.
- Residual finding: candidate benchmark attribution is pending.
  - Cause: candidate histories are not yet normalised into the clean yfinance price panel used for configured ETF attribution.
  - Impact: candidate rows explicitly show pending attribution instead of fake beta/alpha fields.

## 2026-07-08 Backtest Payoff Findings

- Finding resolved: cached backtest results lacked new payoff columns.
  - Evidence: snapshot/audit check raised `KeyError` for `return_hit_rate`, `average_win_return`, `average_loss_return`, `payoff_ratio`, `expected_value_per_period` and `payoff_asymmetry_warning`.
  - Cause: `data\backtests\backtest_results.csv` was generated on 2026-07-04 before the payoff diagnostics existed.
  - Fix: `BacktestService._load_cached_backtest()` now rejects cached results missing required payoff columns, causing local regeneration.
  - Verification: snapshot and audit export check passed after cache invalidation.
- Limitation: payoff diagnostics are return-period diagnostics, not per-closed-trade diagnostics.
  - Cause: the current trade log records rebalance turnover and costs, not entry/exit closed-trade PnL.
  - Impact: UI and logs avoid claiming per-trade win/loss statistics.

## 2026-07-08 Corrected Tracker Recovery Findings

- Finding: the previous issue tracker was incomplete.
  - Evidence: `issues\open.md` contained no `## ISSUE-` headings; `issues\closed.md` had completed `ISSUE-0001` to `ISSUE-0006` and `ISSUE-0009`, but no open `ISSUE-0007`, `ISSUE-0008` or `ISSUE-0010`.
  - Fix: rebuilt `issues\open.md` with 59 open issue headings and updated `plan.md`/`issues\closed.md`.
  - Verification: PowerShell issue-id check reported no missing expected open ids and no unexpected open ids.
- Finding: current app navigation does not yet match the full staged product.
  - Evidence: current Flet `PAGES` includes Dashboard/Simple Scores, Portfolio, Scores, Risk, Instrument Detail, Backtests, Audit Notes, Data & Models, Settings and Diagnostics.
  - Missing first-class routes include Watchlists, News & Context, Paper Trading, Decision Journal, Roadmap/System Map, Data Health Centre, Import/Export Centre, Screener and What Changed.
  - Fix status: tracked as open issues `ISSUE-0015`, `ISSUE-0016`, `ISSUE-0018`, `ISSUE-0019`, `ISSUE-0020`, `ISSUE-0030`, `ISSUE-0031`, `ISSUE-0034`, `ISSUE-0035`, `ISSUE-0036`.
- Finding: main workflow buttons are wired by code inspection but not fully verified from the user's point of view.
  - Evidence: Dashboard callbacks exist for Refresh yfinance data, Run algorithms, Run forecasting models, Show scores, Renew/import local files and Audit packet; Audit and Settings page callbacks also exist.
  - Gap: not every current button has browser-level proof, long-running actions use a single `last_message` instead of persisted step-level Activity Log/Run Log, and new product pages/buttons do not exist yet.
  - Fix status: tracked as open issues `ISSUE-0011`, `ISSUE-0012`, `ISSUE-0014`, `ISSUE-0045`.

## 2026-07-08 Button Reliability Findings

- Finding resolved: long-running dashboard buttons gave no reliable visible running state.
  - Evidence: browser click on `Refresh yfinance data` previously showed only button ripple/blank waiting state until completion.
  - Cause: long actions ran synchronously inside the Flet callback.
  - Fix: added activity state, global progress strip, Activity log panel and background workers for dashboard workflows.
  - Verification: browser screenshots showed progress for refresh, algorithm and forecast workflows; full tests passed.
- Finding resolved: recent Activity log could show generic `Workflow action`.
  - Evidence: algorithm run completed on disk as `Run algorithms`, but UI recent chip could show `Workflow action`.
  - Cause: completion fallback did not preserve the original button label if current activity was temporarily unavailable.
  - Fix: `finish_activity()` accepts a label fallback; dashboard worker passes the original label.
  - Verification: browser screenshot showed recent activity `success Run algorithms`.
- Finding resolved: main `Run forecasting models` could remain running for too long while uncached optional Toto/TimesFM model work executed.
  - Evidence: browser progress stayed running; process log showed Toto weights loading and Torch warnings; no candidate forecast output was written during the observed window.
  - Cause: dashboard workflow launched full optional local model forecasting when candidate cache was missing.
  - Fix: dashboard forecast action uses bounded yfinance forecasts with cached optional rows or baseline/unavailable rows; uncached live TimesFM/Toto no longer block the simple workflow.
  - Verification: browser screenshot showed forecast progress followed by success within seconds.
- Finding resolved: `Show scores`/sidebar navigation could change route state inconsistently.
  - Evidence: browser click on `Show scores` changed URL/render state inconsistently and could fall back to dashboard.
  - Cause: custom Flet containers used `page.go()` and relied on asynchronous route repaint.
  - Fix: added direct rendered navigation helper.
  - Verification: `Show scores` rendered the Scores page, and score rows expanded correctly in system Chrome.
- Residual limitation: Flet web exposes very little semantic DOM for these controls.
  - Impact: visual smoke tests use screenshots/coordinates more than stable DOM locators until `ISSUE-0045` adds semantic locator support.

## 2026-07-09 Trust-Critical Sweep Findings

- Finding: the selected 21-issue release programme was not yet represented as a single execution section.
  - Evidence: `plan.md` and `issues/open.md` contained most underlying issues, but there was no active selected-issue programme and `ISSUE-0069` was missing.
  - Fix: added the 21-issue programme to `plan.md`, added the selected-issue index to `issues/open.md`, added full `ISSUE-0069`, and updated `ISSUES.md`.
  - Residual: the implementation issues remain open until source, UI, tests, audit/export, rebuild and smoke verification pass.
- Finding: current app activity logging is useful but not sufficient for audit traceability.
  - Evidence: `logs/activity_log.jsonl` stores recent high-level actions only; it does not consistently connect button clicks, action IDs, step updates, exceptions, artefact writes and audit exports.
  - Fix status: implementation starts with `logs/session.jsonl`, redaction, Diagnostics UI and audit export inclusion.

## 2026-07-09 Trust-Critical Verification Findings

- Finding resolved: Simple Scores list rendered as a large grey blank panel.
  - Evidence: packaged-app browser screenshot showed summary cards and workflow buttons, but the `Simple yfinance scores` list area was blank/grey.
  - Cause: `_score_tile()` created the details container but never returned a tile. The intended tile-return block had been accidentally indented inside `_score_history_panel()` after a `return`, making it unreachable.
  - Fix: moved the tile toggle/button/container return block back into `_score_tile()` and removed the unreachable block from `_score_history_panel()`.
  - Regression test: `test_simple_score_tiles_render_instrument_rows` asserts representative primary/secondary row text appears in the returned Flet control tree.
  - Verification: full tests passed, package rebuilt, and real Chrome/Windows capture showed visible score rows and expandable details.
- Finding: one-shot headless Chrome is not reliable for Flet web readiness.
  - Evidence: Chrome `--headless --screenshot` captured only the Flet loading logo despite the app being reachable on `http://127.0.0.1:8550/`.
  - Cause: the one-shot screenshot captured before the websocket-rendered Flet app settled.
  - Mitigation: used real Chrome window capture through Windows Computer Use for visual smoke verification.
- Finding: Chrome extension and Playwright MCP transports were unstable during final verification.
  - Evidence: Chrome extension calls timed out during `goto`/screenshot; Playwright MCP transport closed after app restart.
  - Mitigation: verified HTTP readiness with `Invoke-WebRequest`, then used Windows Computer Use to refresh the visible Chrome app tab, expand rows and navigate trust pages.
- Residual limitation: optional official-source importers are not yet full parsers.
  - Evidence: Filings, ETF Disclosures and News & Context pages show explicit missing/unavailable inventories when no local files/provider are configured.
  - Impact: the app does not invent missing official evidence, but full SEC/ESEF/PRIIPs/index-methodology extraction remains open under the corresponding issues.

## 2026-07-09 Launcher, Sparebanken And Reliability Findings

- Finding resolved: root launcher/build/native/portable startup logic was fragmented across batch files.
  - Evidence: the prior workflow could confuse source/native roots, open a browser before readiness, fail on busy ports and abort on locked build folders.
  - Fix: added `scripts\launcher_core.py` and rewired the batch files to use the same readiness, root, browser-open and lock-handling behaviour.
  - Verification: root BAT, native smoke, portable runner and helper launcher smoke all passed.
- Finding resolved: a busy non-HTTP port could be treated as successful app reuse.
  - Evidence: initial smoke on requested port 8550 found the port busy but not HTTP-ready; the app fell back while the smoke checker still polled the requested port.
  - Fix: app startup and smoke checks now choose and report the actual launch port.
  - Verification: source smoke selected port 8552 and passed.
- Finding resolved: existing portable build folders can be locked by old app logs or processes.
  - Evidence: build initially failed on the old portable folder's `logs\app.log`.
  - Fix: the build helper now gives a clear locked-folder error and can create an alternate timestamped portable output folder.
  - Verification: final build wrote `build\portable_outdir.txt` and created `build\ETF_AI_Cockpit_Portable_v0.1.0_20260709_205522`.
- Finding resolved: Sparebanken equity certificates were not a distinct group.
  - Fix: added the `sparebanken` analysis group and separate UI grouping.
  - Verification: tests and `browser-main-very-tall.png` show the separate Sparebanken section.
- Data integrity finding: several requested Sparebanken ISINs were unknown.
  - Decision/fix: kept them as literal `needs_verification` values and displayed them that way. No ISIN was invented.
- Browser automation limitation: Flet canvas text remains weak for semantic locators.
  - Evidence: Playwright title and screenshots worked, but DOM `innerText` was empty/minimal for visible Flet text.
  - Impact: browser smoke passed visually, but `ISSUE-0045` remains open for stronger semantic/accessibility hooks.

## 2026-07-10 Post-Review Findings

- Resolved: `Launch_Latest_ETF_AI_Cockpit.bat` launched the fixed portable folder instead of the path selected by the build.
- Resolved: locked native staging aborted rebuilds; native staging now uses a timestamped alternate directory.
- Resolved: `%NATIVE_OUT_ROOT%` expanded before `set /p` inside a batch block; delayed expansion now passes the selected path to PyInstaller and executable checks.
- Resolved: Flet packaging deleted the temporary native output manifest; the build rewrites it after successful packaging.
- Resolved test reliability finding: the no-refresh pending-state test depended on persisted candidate report data and now isolates those loaders explicitly.
- Remaining limitation: Flet canvas semantics are still insufficient for text locators even after activating its accessibility control; visual/browser evidence is valid, but semantic accessibility work remains open.

## 2026-07-10 Source Foundation Gate

- Repository-wide Ruff is not clean: 53 findings remain, mostly established dynamic `sys.path` import-order warnings and unrelated unused symbols. The current feature files are clean.
- Mypy is not clean: 11 findings remain from missing third-party stubs and existing annotations in atomic I/O/migrations/workflow; no type claim is made.
- Before this checkpoint, ESEF discovery could violate the `ProviderResult.data` DataFrame contract. The code now normalises API rows and the regression test passes.
- Strict parser/provider closure remains blocked by missing final issue-specific UI/export/package/browser evidence, even though official fixture parser tests pass.

## 2026-07-10 Reviewer Findings Integration

- Reviewer found 14 reliability defects. The selected-output launcher defect caused the first fresh native smoke to fail; it was fixed at the manifest-resolution source and covered by native/portable tests.
- Provider partial-result safety is now conservative: successful rows are retained for diagnostics, but the result status is error so refresh services do not commit incomplete data.
- Full issue closure remains gated by fresh package/browser/export evidence. Code-level fixes alone do not close tracker records.

## 2026-07-10 Packaged Browser Findings

- Root BAT smoke initially passed a double-prefixed absolute executable path when reading `build\native_outdir.txt`; the launcher was corrected and rerun successfully.
- Direct packaged browser reload briefly showed a blank/loading viewport before Flet websocket rendering. HTTP readiness succeeded earlier, so the smoke harness must distinguish transport readiness from rendered readiness.
- Chrome extension screenshot binding tracked a different tab during part of the Computer Use run; displayed Windows capture is the authoritative visual evidence for this checkpoint.
- Backup and Restore remained a visible control without a misleading success message; the full interactive workflow remains open.

## 2026-07-10 Task 23 Closure Findings

- The closure evaluator correctly rejected all issues without final gate evidence; no existence-only closure was used.
- The evaluator accepted exactly three records after source/test/UI/export/build/browser dossiers and sidecars were present.
- The remaining 38 issue records still have genuine product or strict parser/provider gaps; they were not moved to closed to make the count look complete.
# 2026-07-10 All-41 Execution Findings

- Task 1 review found acceptance bullets collapsed by the first matrix generator. The matrix was regenerated at bullet/requirement granularity and now contains 594 criteria across exactly 41 issues.
- Task 1 review found existence-only closure evidence unsafe. Closure evidence now requires a matching SHA-256 sidecar and resolved containment within the evidence root; symlinked evidence is rejected.
- Task 2 review found ESEF package selection was demonstrated only by tests. The manifest loader now enforces URL, entity, checksum and ESEF marker linkage to exactly one retained API response record.
- Native parser packaging proof remains pending for the Wave 1 build gate and is not claimed complete.
- Task 3's first persistent evidence command omitted PYTHONPATH and failed before import; corrected retry passed.

## 2026-07-10 Data Health UI Finding

- Fallback browser visual inspection found the 11-column DataTable clipped provenance and run-history fields at 1040px and 1920px viewport widths. The table was replaced with responsive per-dataset evidence rows; closure remains pending a fresh build, full regression and browser evidence.
- The Computer Use retry failed before app input with: `Computer Use has been stopped for this turn because it could not determine the current browser URL on Windows with enough confidence to enforce policy.`

## 2026-07-10 ISSUE-0035 Closure Finding

- Closure evaluator initially rejected `ISSUE-0035` because its `C-LIMITS` criterion had no evidence paths. The criterion was corrected, the matrix tests passed and the evaluator then reported 4/41 ready.
- The final Data Health browser visual check found no clipping after the responsive-row correction. The Flet semantic snapshot and Computer Use transport remain limited and are recorded as such.

## 2026-07-11 Independent Review Findings And Fixes

- Review found that `Authorization: Bearer secret` could be partially redacted while leaving the bearer token, and that env-prefixed/API/access/client secret forms were not all detected by the archive validator. Fixed and covered by tests.
- Review found source-less and model components could still influence weighted scores or be persisted as eligible. Fixed by requiring non-empty source, `OK` status and non-model dataset for deterministic score eligibility; model evidence remains advisory and visible.
- Review found `allow_unavailable` accepted a missing required file without a marker. The manifest now names and validates an explicit marker.
- Review required direct conflict and complete holdings export regression assertions; both are now covered.
- Fresh package/browser evidence remains required; no issue closure was inferred from source/tests alone.

## 2026-07-11 Follow-Up Review Findings And Fixes

- JSON-style values such as `{"authorization":"Bearer raw"}` bypassed the assignment redactor in both session and workflow traces; the shared redactor now handles quoted JSON keys and bearer schemes.
- An explicitly unknown score source prefix could influence the deterministic score; aggregation now accepts only the known component source IDs.
- Model source authority is now explicitly `model_advisory` rather than ambiguous `unknown`.
- Candle evidence was present in the ZIP but not declared as a required manifest item; the manifest now requires the CSV or its named unavailable marker.
- Holdings export tests now assert exact configured IDs, uniqueness and required fields.

## 2026-07-11 Final Findings

- HTTP readiness occurs before the Flet page is visually settled; Chrome evidence used a 12-second settle wait and does not claim instantaneous UI readiness.
- The first package launcher harness invocation did not change working directory and therefore exercised the root launcher; it was rejected as package evidence. The corrected package-cwd rerun passed and is the only package launcher result counted.
- The closure evaluator intentionally exits 1 while 37 records remain open. This is an expected incomplete-closure result, not a test failure.
- Windows Computer Use remained unavailable because URL confidence could not be established. No Computer Use pass is claimed.
