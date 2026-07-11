# Testing

## 2026-06-27

### Required New Regression Matrix

- Pass: normal app startup uses local sample/config data and does not need network.
- Pass: Renew data dry-run path works without an API key and shows a safe no-provider message.
- Pass: provider config loads and redacts secrets from logs/exports.
- Pass: local file provider can load CSV and the UI opens a file picker for CSV/XLSX/JSON/Parquet based on installed dependencies.
- Pass: validated price import writes raw copy, clean Parquet, compatibility Parquet and a previous-data snapshot on subsequent commits.
- Pass: price import rollback restores the latest previous clean price snapshot and snapshots the replaced current store.
- Pass: price rollback without any prior snapshot returns a safe no-snapshot message.
- Pass: packaged Renew Data rollback button is visible and displays the safe no-snapshot message when no prior price snapshot exists.
- Pass: unavailable TimesFM/Toto forecasts have null expected/quantile values and `model_allowed_in_score=false`.
- Pass: every generated final action in the current blocked sample snapshot is `manual_review` with block reasons; generic `no_trade` reason coverage remains implemented for non-blocked configs.
- Pass: `WORLD_CORE` 42% target versus 35% max single ETF cap triggers target-policy violation and manual review.
- Pass: `WORLD_CORE` 45.5% current weight versus 35% max single ETF cap triggers current concentration violation and manual review.
- Pass: holdings validation blocks residual cash below configured minimum.
- Pass: stale price data warning/block tiers match the addendum.
- Pass: cost model produces edge-to-cost ratio and blocks insufficient edge/minimum trade size.
- Pass: audit export ZIP includes validation and risk-gate reports.
- Pass: imported external audit is stored with `executable_authority=false` and cannot change trades.
- Pass: browser UI shows dashboard/manual-review state, Renew Data workflow, provider settings fields, provenance panel and expanded signal table.
- Pass: packaged Renew Data dialog opens with Flet 0.85 async FilePicker API; dry-run and no-provider API branches render expected results.
- Pass: Backtests page exposes walk-forward periods, trade count, average trade, annual turnover, worst 12-month return, quality label, not-run advanced diagnostics and recent signal/execution trade dates.
- Pass: Risk page route exists and exposes concentration/limit status, asset-class/region/currency/sector/theme exposure, adjusted-return correlation and drawdown contribution.
- Pass: manual thesis/news import commits validated dated notes to raw, clean and snapshot storage while forcing `executable_authority=false`.
- Pass: manual thesis/news import rejects files without a dated evidence column.
- Pass: audit export ZIP includes imported manual thesis/news notes with non-executable authority wording.
- Pass: Data & Models first viewport shows manual thesis/news status after the layout refactor.
- Pass: ETF factsheet/reference metadata import writes raw, clean, snapshot and metadata files with freshness status.
- Pass: ETF holdings import converts explicit `weight_percent` to decimal clean weights and snapshots previous clean data.
- Pass: ETF holdings import rejects plain decimal `weight` values above 1.0 instead of silently treating them as percentages.
- Pass: stale ETF factsheet metadata is labelled `block` by freshness rules.
- Pass: audit export ZIP includes `12_reference_data_inventory.json`.
- Pass: FX import writes raw, clean, snapshot and metadata files with dated pair/rate provenance.
- Pass: FX import rejects malformed currency pairs.
- Pass: audit export ZIP includes `13_fx_inventory.json`.
- Pass: Risk page underlying holdings exposure uses latest imported holdings rows and portfolio weights.
- Pass: Risk page packaged UI shows an explicit no-imported-ETF-holdings empty state.

- Pass: pytest suite, `.\.venv\Scripts\python.exe -m pytest tests -q` -> 18 passed.
- Pass: expanded pytest suite, `.\.venv\Scripts\python.exe -m pytest tests -q` -> 26 passed.
- Pass: service smoke check after release-hardening, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: direct runtime smoke inspection -> status `Blocked`, `trading_allowed=False`, target-policy issue present, all signals `manual_review`, provider API status returned the safe no-provider message.
- Pass: source UI browser check at `http://127.0.0.1:8551/` -> dashboard rendered, Renew Data dialog opened, no-provider branch showed safe message, dry-run branch showed validation result and target-policy block.
- Pass: Data & Models browser check -> provenance panel showed source, as-of date, staleness and checksum.
- Pass: Settings browser check -> provider fields rendered with API-key placeholders hidden.
- Pass: packaging rebuild after stopping the old locked packaged process, `cmd /c scripts\build_windows.bat` -> produced current `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Pass: packaged exe web check, launched rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_OPEN_BROWSER=0`; `curl` returned `200 3775` from `http://127.0.0.1:8550/`.
- Pass: packaged browser render check at `http://127.0.0.1:8550/` -> dashboard rendered after startup, Renew Data dialog opened, dry-run validation showed policy block.
- Pass: final packaged smoke check after file-picker change -> launched rebuilt exe hidden, `curl` returned `200 3775` from `http://127.0.0.1:8550/`, then stopped verification process.
- Pass: service smoke check, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: Flet UI construction smoke check -> `ui_controls_ok`.
- Pass: packaging script, `cmd /c scripts\build_windows.bat` completed and produced `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
- Pass: packaged folder check, `models\source_archives` is not bundled into `build\flet_dist\ETF_AI_Cockpit\_internal\models`; packaged folder size is about 301 MiB.
- Pass: executable launch check, `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` stayed running for 12 seconds and was stopped after verification.
- Pass: root batch launcher check, `ETF_AI_Cockpit.bat` exited with code 0, printed `Starting ETF AI Cockpit executable...`, launched `ETF_AI_Cockpit.exe`, and the launched exe was stopped after verification.
- Pass: LM Studio local check, `http://127.0.0.1:1234/v1/models` returned HTTP 200 with model IDs.
- Pass: direct packaged exe web check, launching `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_OPEN_BROWSER=0` returned `curl` result `200 3775` from `http://127.0.0.1:8550/`.
- Pass: direct packaged exe default check, launching `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with default browser-open behaviour returned `curl` result `200 3775` from `http://127.0.0.1:8550/`.
- Pass: root batch launcher web check, `cmd /c ETF_AI_Cockpit.bat` launched `ETF_AI_Cockpit.exe`; a follow-up `curl` returned `200 3775` from `http://127.0.0.1:8550/`.
- Pass: browser render check through Edge DevTools Protocol. Screenshot saved at `C:\Users\thor2\AppData\Local\Temp\etf_ai_cockpit_cdp.png` shows the dashboard, status cards, ranked ETF action table, risk flags and model status.
- Pass: backtest no same-bar regression, `.\.venv\Scripts\python.exe -m pytest tests\test_backtest_costs.py -q` -> 2 passed.
- Pass: release-hardening focused suite after holdings validation, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 10 passed.
- Pass: release-hardening focused suite after import commit pipeline, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 11 passed.
- Pass: full suite after import pipeline and UI updates, `.\.venv\Scripts\python.exe -m pytest tests -q` -> 30 passed.
- Pass: full suite after FilePicker regression fix, `.\.venv\Scripts\python.exe -m pytest tests -q` -> 31 passed.
- Pass: source smoke after FilePicker fix, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: release-hardening focused suite after rollback, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 13 passed.
- Pass: full suite after rollback, `.\.venv\Scripts\python.exe -m pytest tests -q` -> 33 passed.
- Pass: source smoke after rollback, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after rollback, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged executable check after rollback -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged browser visual check after rollback -> `Rollback last prices` rendered in the Renew Data dialog and returned `No previous clean price snapshot is available to roll back.`
- Pass: risk analytics focused suite, `.\.venv\Scripts\python.exe -m pytest tests\test_risk_analytics.py -q` -> 4 passed.
- Pass: full suite after Risk page, `.\.venv\Scripts\python.exe -m pytest tests -q` -> 37 passed.
- Pass: source smoke after Risk page, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after Risk page, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged executable check after Risk page -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged browser visual check after Risk page -> `/risk` rendered with limit-breach cards and Risk Limits table.
- Pass: packaging rebuild after FilePicker fix, `cmd /c scripts\build_windows.bat` -> produced rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Pass: packaged executable check after FilePicker fix -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged browser visual check after FilePicker fix -> Dashboard rendered; Backtests rendered with quality diagnostics; Renew Data dialog opened; dry-run showed blocked current data; API provider branch showed no-provider safe message.
- Pass: release-hardening focused suite after manual thesis/news import, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 16 passed.
- Pass: full suite after manual thesis/news import and Data page layout, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 40 collected tests passed.
- Pass: collection count after manual thesis/news import, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 40 tests collected.
- Pass: source smoke after manual thesis/news import, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after manual thesis/news import and Data page layout, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged executable check after manual thesis/news import -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged browser visual check after manual thesis/news import -> Dashboard rendered, Renew Data dialog showed `Import manual notes`, safe API branch showed the no-provider message, and Data & Models first viewport showed `Manual Thesis / News Notes`.
- Pass: packaged log check after manual thesis/news browser verification -> `stdout.log` and `stderr.log` empty; `startup.log` showed normal local web startup.
- Pass: release-hardening focused suite after ETF reference-data imports, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 20 passed.
- Pass: full suite after ETF reference-data imports, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 44 collected tests passed.
- Pass: collection count after ETF reference-data imports, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 44 tests collected.
- Pass: source smoke after ETF reference-data imports, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after ETF reference-data imports, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged executable check after ETF reference-data imports -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged browser visual check after ETF reference-data imports -> Renew Data dialog showed `Import ETF factsheets` and `Import ETF holdings`; Data & Models first viewport showed `ETF Reference Data` inventory.
- Pass: packaged log check after ETF reference-data browser verification -> `stdout.log` and `stderr.log` empty; `startup.log` showed normal local web startup.
- Pass: release-hardening focused suite after FX imports, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 22 passed.
- Pass: full suite after FX imports, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 46 collected tests passed.
- Pass: collection count after FX imports, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 46 tests collected.
- Pass: source smoke after FX imports, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after FX imports, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged executable check after FX imports -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged browser visual check after FX imports -> Renew Data dialog showed `Import FX rates`; Data & Models first viewport showed `fx: not imported`.
- Pass: packaged log check after FX browser verification -> `stdout.log` and `stderr.log` empty; `startup.log` showed normal local web startup.
- Pass: risk analytics focused suite after underlying holdings exposure, `.\.venv\Scripts\python.exe -m pytest tests\test_risk_analytics.py -q` -> 5 passed.
- Pass: full suite after underlying holdings exposure, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 47 collected tests passed.
- Pass: collection count after underlying holdings exposure, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 47 tests collected.
- Pass: source smoke after underlying holdings exposure, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after underlying holdings exposure, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged executable check after underlying holdings exposure -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged browser visual check after underlying holdings exposure -> Risk page rendered, lower panels were scrollable, and `Underlying Holdings Exposure` showed `No ETF holdings file has been imported yet.`
- Pass: packaged log check after underlying holdings exposure browser verification -> `stdout.log` and `stderr.log` empty; `startup.log` showed normal local web startup.
- Note: PyInstaller still reports optional SciPy hidden-import warnings such as `scipy.special._cdflib`; the packaged app startup and dashboard render passed despite those optional-analysis warnings.
- Note: Browser console API retained generic historical Flet WASM `Exception` entries for the localhost session. No corresponding packaged Python stdout/stderr errors were present, and visual interaction checks passed.

## 2026-06-28

- Pass: backtest diagnostics focused suite after advanced diagnostic estimates, `.\.venv\Scripts\python.exe -m pytest tests\test_backtest_costs.py -q` -> 3 passed.
- Pass: focused startup/backtest suite after direct-route fix, `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_backtest_costs.py -q` -> 6 passed.
- Pass: full suite after backtest diagnostics and routing fix, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 49 collected tests passed.
- Pass: collection count after this pass, `.\.venv\Scripts\python.exe -m pytest --collect-only | Select-Object -Last 1` -> 49 tests collected.
- Pass: source smoke after this pass, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after this pass, `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Pass: packaged executable check after this pass -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged direct-route visual check -> direct `http://127.0.0.1:8550/backtests` rendered the Backtests page instead of a blank shell.
- Pass: packaged Backtests visual check -> displayed quality `Medium`, probabilistic Sharpe `0.74`, deflated Sharpe `-0.19`, PBO probability `0.33` and parameter sensitivity `mixed`.
- Pass: packaged root visual check -> dashboard rendered normally with the expected blocked/manual-review sample state.
- Pass: packaged log check after this browser verification -> `stdout.log` and `stderr.log` empty; `startup.log` showed normal local web startup.
- Note: PyInstaller still reports the optional `scipy.special._cdflib` hidden-import warning; no packaged runtime error accompanied it.
- Pass: focused audit/risk suite after audit-packet path and label changes, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py tests\test_risk_analytics.py -q` -> 28 passed.
- Pass: focused startup/audit/risk suite after footer text fix, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py tests\test_risk_analytics.py tests\test_flet_startup.py -q` -> 31 passed.
- Pass: stale visible label search after audit wording update -> no matches for old `ChatGPT Audit`, `Export ChatGPT pack`, `Export Review Pack`, `Import Review JSON`, `Validate and Import`, `chatgpt_review_` or old footer text in source/tests/README files.
- Pass: full suite after audit-packet path and label changes, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 50 collected tests passed.
- Pass: collection count after audit-packet changes, `.\.venv\Scripts\python.exe -m pytest --collect-only | Select-Object -Last 1` -> 50 tests collected.
- Pass: source smoke after audit-packet changes, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after audit-packet changes, `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Pass: packaged executable check after audit-packet changes -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged dashboard visual check after audit-packet changes -> Dashboard showed `Export audit packet` and `Open audit`.
- Pass: packaged Audit page visual check -> direct `/chatgpt` rendered `Audit`, `Export audit packet`, `Import external audit response`, `Validate and import`, and footer `External audit is commentary only`.
- Pass: packaged log check after audit-packet browser verification -> `stdout.log` and `stderr.log` empty; `startup.log` showed normal local web startup.
- Pass: focused local LLM/audit/risk suite after adding optional LM Studio audit layer, `.\.venv\Scripts\python.exe -m pytest tests\test_local_llm_audit.py tests\test_release_hardening.py tests\test_risk_analytics.py -q` -> 33 passed.
- Pass: focused local LLM/audit/risk suite after safe unavailable-message cleanup, `.\.venv\Scripts\python.exe -m pytest tests\test_local_llm_audit.py tests\test_release_hardening.py tests\test_risk_analytics.py -q` -> 34 passed.
- Pass: full suite after local LLM audit layer, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 56 collected tests passed.
- Pass: collection count after local LLM audit layer, `.\.venv\Scripts\python.exe -m pytest --collect-only | Select-Object -Last 1` -> 56 tests collected.
- Pass: source smoke after local LLM audit layer, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: live LM Studio status probe through the new client -> `unavailable||Local LLM endpoint unavailable. Start the LM Studio local server or leave this optional workflow unused.`
- Pass: packaging rebuild after local LLM audit layer, `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Pass: packaged executable check after local LLM audit layer -> launched `ETF_AI_Cockpit.exe`, `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: packaged Audit page visual check after local LLM audit layer -> local LLM panel rendered with `Check local LLM` and `Generate local commentary`.
- Pass: packaged Local LLM unavailable-path check -> clicking `Check local LLM` showed the concise optional-unavailable message when LM Studio was offline.
- Pass: packaged log check after local LLM browser verification -> `stdout.log` and `stderr.log` empty; `startup.log` showed normal local web startup.
- Pass: trade-proposal focused suite, `.\.venv\Scripts\python.exe -m pytest tests\test_trade_proposals.py tests\test_flet_startup.py tests\test_release_hardening.py -q` -> passed.
- Pass: full suite after trade-proposal workflow, `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 58 collected tests passed.
- Pass: source smoke after trade-proposal workflow, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: packaging rebuild after trade-proposal workflow, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged Dashboard visual/interactivity check after trade-proposal workflow -> clicking `Create trade proposal` produced the expected blocked/manual-review message for the sample risk-gated dataset.
- Pass: packaged trade-proposal report inspection -> JSON report had status `blocked`, no proposals, `executable_authority=false`, `broker_execution=not_supported`, and blocked summaries for all sample ETFs.
- Pass: path/proposal/startup/release focused suite after package-root fix, `.\.venv\Scripts\python.exe -m pytest tests\test_paths.py tests\test_trade_proposals.py tests\test_flet_startup.py tests\test_release_hardening.py -q` -> passed.
- Pass: full suite after package-root fix, `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Fail then pass: source smoke command initially used nonexistent `snapshot.backtests`; corrected to `snapshot.backtest.results` and passed with visible project root/data/log paths.
- Pass: packaging rebuild after package-root fix, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged executable check after package-root fix -> launched with `ETF_COCKPIT_ROOT` set to the visible project folder; `http://127.0.0.1:8550/` returned `HTTP 200 3775`.
- Pass: in-app browser Dashboard visual check -> page title `ETF AI Portfolio Cockpit`, first viewport rendered the Dashboard, and browser error/warn logs were empty.
- Pass: packaged trade-proposal interaction after package-root fix -> clicking `Create trade proposal` produced a blocked non-executable report under visible `data\reports`, not `_internal\data\reports`.
- Pass: generated report inspection -> `status=blocked`, `executable_authority=false`, `broker_execution=not_supported`, zero proposals and seven blocked/manual-review summaries.
- Pass with note: packaged log check -> current startup recorded in `logs\startup.log`; `logs\stderr.log` had only stale 2026-06-27 content and was not modified by this run.
- Pass: release-hardening suite after cross-currency holdings validation, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> passed.
- Pass: full suite after cross-currency holdings validation, `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Pass: source smoke after cross-currency holdings validation -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5 trading_allowed=False issues=2`.
- Fail then pass: packaging rebuild after cross-currency holdings validation first failed because stale PID `90928` locked `build\flet_dist`; stopped it, confirmed port 8550 was free, and reran the build successfully.
- Pass: packaged executable check after cross-currency holdings validation -> rebuilt exe timestamp updated, launched with visible `ETF_COCKPIT_ROOT`, HTTP returned `200 3775`, and browser screenshot showed the Dashboard.
- Pass: browser console health after cross-currency package verification -> no error/warn entries for the current run.
- Pass: focused startup/release suite after duplicate-server guard, `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_release_hardening.py -q` -> passed.
- Pass: full suite after duplicate-server guard, `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Pass: source smoke after duplicate-server guard -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5 trading_allowed=False issues=2`.
- Pass: packaging rebuild after duplicate-server guard, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: repeated packaged launch test -> first process served `HTTP 200 3775`; second process exited and reused the existing server without changing `logs\stderr.log`.
- Pass: final packaged browser visual check -> Dashboard rendered with expected manual-review sample state and no browser error/warn logs.
- Pass: process cleanup -> stopped the packaged process and confirmed port 8550 was free.
- Pass: focused provider/settings/startup suite, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py tests\test_flet_startup.py -q` -> passed.
- Pass: full suite after provider Settings persistence, `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Pass: source smoke after provider Settings persistence -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5 trading_allowed=False issues=2`.
- Pass: packaging rebuild after provider Settings persistence, `cmd /c scripts\build_windows.bat` -> rebuilt executable and portable folder.
- Pass: packaged Settings visual check -> `/settings` rendered editable provider/base URL/API key fields with Save buttons and secret-handling note.
- Pass: packaged log check after Settings visual check -> browser error/warn logs empty; stale `stderr.log` timestamp did not change; port 8550 was free after cleanup.
- Pass: collection count after latest hardening work, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 69 tests collected.

## 2026-06-30

- Pass: LM Studio endpoint probe, `Invoke-RestMethod http://localhost:1234/v1/models` -> reachable and returned seven model IDs.
- Pass: app local LLM status probe, `check_local_llm_status()` -> `status=ok`, `base_url=http://localhost:1234/v1`, `model=qwen3.6-27b`.
- Pass: model archive inspection, `tar -tf ... | rg` checkpoint-like search -> `checkpoint_like_count=0` for both TimesFM and Toto ZIPs.
- Pass: copied archive hash check -> root ZIP hashes match `models\source_archives` copies.
- Pass: app model availability probe -> `{'baseline': True, 'timesfm': False, 'toto': False}`.
- Pass: focused model/LLM tests, `.\.venv\Scripts\python.exe -m pytest tests\test_local_llm_audit.py tests\test_model_shapes.py -q` -> 9 passed.
- Pass: source smoke, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: full regression suite, `.\.venv\Scripts\python.exe -m pytest -q` -> passed, exit code 0.
- Pass: collection count, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 69 tests collected.

## 2026-06-30

- Pass: Hugging Face source inspection -> TimesFM 2.5 docs showed `TimesFm2_5ModelForPrediction.from_pretrained(...)`, `past_values`, `mean_predictions` and `full_predictions`; Datadog Toto model card showed `Toto2Model.from_pretrained(...)`, target tensor shape `(batch, n_variates, time_steps)` and quantiles shape `(9, batch, n_variates, horizon)`.
- Pass: Toto collection API inspection -> confirmed all five Datadog Toto 2.0 repo IDs.
- Pass: focused model tests after live-adapter implementation, `.\.venv\Scripts\python.exe -m pytest tests\test_model_shapes.py -q` -> 6 passed.
- Pass: focused model/unavailable safety tests, `.\.venv\Scripts\python.exe -m pytest tests\test_model_shapes.py tests\test_release_hardening.py::test_unavailable_models_are_not_allowed_in_score -q` -> 7 passed.
- Pass: expanded model config load check -> TimesFM and Toto runtime configs include HF repo IDs, local-first flags and backend settings.
- Pass: model availability check after implementation -> `{'baseline': True, 'timesfm': False, 'toto': False}` because no real local checkpoint weights are installed.
- Pass: source smoke, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: full regression suite, `.\.venv\Scripts\python.exe -m pytest -q` -> passed, exit code 0.
- Pass: collection count, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 72 tests collected.
- Fail then pass: packaging rebuild after adapter/config changes first failed in PyInstaller `COLLECT` because old packaged PID `91120` locked `build\flet_dist\ETF_AI_Cockpit`; stopped the project process and reran successfully.
- Pass: packaged executable check after rebuild -> launched with `ETF_COCKPIT_OPEN_BROWSER=0`, `http://127.0.0.1:8550/` returned `HTTP 200 length=3775`.
- Pass: packaged build timestamp check -> `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` last write `2026-06-30 13:12:27`.
- Pass with note: packaged log check -> current `startup.log` updated, `stdout.log` empty, and `stderr.log` was not modified by this run; remaining stderr content is stale from 2026-06-28.
- Pass: process cleanup -> stopped the temporary packaged process and port 8550 was free.

## 2026-06-30

- Pass: yfinance installation check -> `yfinance.__version__` reported `1.5.1`.
- Pass: focused yfinance provider tests, `.\.venv\Scripts\python.exe -m pytest tests\test_yfinance_provider.py tests\test_release_hardening.py::test_no_provider_api_update_returns_safe_message -q` -> 2 passed.
- Pass: live yfinance candidate analysis, `.\.venv\Scripts\python.exe scripts\analyze_yfinance_candidates.py` -> downloaded 15,311 rows for 12 instruments and wrote CSV/JSON/Markdown reports.
- Pass: source smoke after yfinance changes, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: full regression suite after yfinance changes, `.\.venv\Scripts\python.exe -m pytest -q` -> passed, exit code 0.
- Pass: collection count after yfinance changes, `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 73 tests collected.
- Pass: packaging rebuild after yfinance changes, `cmd /c scripts\build_windows.bat` -> completed and refreshed `build\flet_dist`.
- Pass with note: PyInstaller emitted optional hidden-import warnings for `pycparser.lextab`, `pycparser.yacctab` and `scipy.special._cdflib`; package startup smoke passed.
- Pass: packaged executable check after yfinance rebuild -> `http://127.0.0.1:8550/` returned `HTTP 200 length=3775`.
- Pass: packaged log/process cleanup -> `startup.log` updated, `stdout.log` empty, stale `stderr.log` timestamp unchanged, and port 8550 was free after stopping the temporary process.

## 2026-06-30

- Pass: full regression suite after safetensor/model-runtime integration, `.\.venv\Scripts\python.exe -m pytest tests -q` -> passed, with only the known GluonTS JSON-speed warning.
- Pass: source smoke, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: local model inventory probe with `PYTHONPATH=src`:
  - TimesFM 2.5 -> `live_ready`, 0.93 GB, 272 tensors.
  - Toto 2.0 4M -> `live_ready`, 0.02 GB, 48 tensors.
  - Toto 2.0 1B -> weights present, 4.16 GB, 336 tensors, not enabled.
- Pass: local model live smoke:
  - TimesFM 2.5 -> `status=ok`, 5-day expected return `0.00011880255786761681`.
  - Toto 2.0 4M -> `status=ok`, 5-day expected return `0.0018576413276605308`.
- Pass: model file placement check -> no project-root `.safetensors` files remain.
- Pass: package safety check -> no safetensors exist under `build\flet_dist` or `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Fail then pass: first packaged EXE HTTP readiness after model runtime install failed because `flet_web` was missing; after installing `flet-web` and restoring Flet web build inclusions, rebuild passed.
- Pass: rebuild, `.\scripts\build_windows.bat` -> build completed and refreshed `build\flet_dist` plus `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Pass: packaged EXE readiness, launching `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_PORT=8560` and `ETF_COCKPIT_OPEN_BROWSER=0` -> `exe_http_ready`.
- Pass: in-app browser QA at `http://127.0.0.1:8561/`:
  - Page title changed from initial shell to `ETF AI Portfolio Cockpit`.
  - Dashboard rendered with status cards, buttons and ranked ETF action table.
  - Browser error/warn logs were empty.
  - Clicking `Data & Models` changed route to `/data-models` and showed `Local Model Files` with TimesFM/Toto readiness.
  - Clicking `Renew data` opened the modal.
  - Clicking `Use configured API` showed `No API provider configured. Add provider details in Settings or import local files.` without console errors.
- Pass: process cleanup -> stopped the temporary Flet test server on port 8561 and confirmed the terminal session ended.
- Pass: post-documentation source smoke, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.

## 2026-06-30

- Pass: `nvidia-smi` -> RTX 5070 Laptop GPU visible, 8151 MiB VRAM.
- Pass: CUDA Torch check -> `torch 2.12.1+cu130`, CUDA `13.0`, `torch.cuda.is_available() == True`, GPU `NVIDIA GeForce RTX 5070 Laptop GPU`.
- Pass: `pip check` -> `No broken requirements found`.
- Pass: model availability check -> `{'baseline': True, 'timesfm': True, 'toto': True}` with Toto config `1b`.
- Pass: Toto 1B CUDA smoke -> `status=ok`, model version `toto_2_0_1b`, around 4180 MB allocated and 4334 MB reserved VRAM.
- Pass: focused model tests after service/Toto fixes, `.\.venv\Scripts\python.exe -m pytest tests\test_model_shapes.py -q` -> passed.
- Pass: forecast-service regression, `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py::test_forecast_service_runs_optional_model_rows_when_enabled -q` -> passed.
- Pass: full regression suite, `.\.venv\Scripts\python.exe -m pytest tests -q` -> passed, with only the known GluonTS JSON-speed warning.
- Pass: source smoke, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: ETF signal run, `.\.venv\Scripts\python.exe scripts\run_signals.py --date latest` -> 7 manual-review rows because current sample data is still risk-gated by portfolio validation/concentration policy.
- Pass: ETF backtest run, `.\.venv\Scripts\python.exe scripts\run_backtest.py` -> wrote refreshed backtest outputs and printed 5 strategy rows.
- Pass: ETF model forecast run, `.\.venv\Scripts\python.exe scripts\run_forecasts.py --date latest`:
  - baseline ok 35
  - TimesFM ok 28
  - TimesFM skipped 7
  - Toto 1B ok 35
  - output `data\forecasts\forecast_results_20260626.csv`
- Pass: yfinance candidate technical analysis, `.\.venv\Scripts\python.exe scripts\analyze_yfinance_candidates.py` -> wrote fresh CSV/JSON/Markdown reports under `data\reports`.
- Fail then pass: first yfinance candidate model forecast had Toto failures due patch-size mismatch after all-NaN row removal. After fixing the adapter, `.\.venv\Scripts\python.exe scripts\run_yfinance_candidate_forecasts.py` passed:
  - baseline ok 60
  - TimesFM ok 48
  - TimesFM skipped 12
  - Toto 1B ok 60
  - output `data\forecasts\yfinance_candidate_forecasts_20260629.csv`

## 2026-06-30

- Pass: compile check after UI/scoring changes, `.\.venv\Scripts\python.exe -m compileall src\etf_cockpit`.
- Pass: focused tests, `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_signal_gates.py tests\test_release_hardening.py -q`.
- Pass: full regression suite, `.\.venv\Scripts\python.exe -m pytest tests -q`, with only the known GluonTS JSON-speed warning.
- Pass: source smoke, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Pass: signal CLI, `.\.venv\Scripts\python.exe scripts\run_signals.py --date latest` -> 7 scored rows, all `no_trade` due inside-deadband rather than portfolio-policy manual-review blocks.
- Pass: forecast-score snapshot probe -> `data_status Warning`, `trading_allowed True`, forecast source `data\forecasts\forecast_results_20260626.csv`, non-zero baseline/Toto/TimesFM components visible on scored rows.
- Browser QA:
  - URL: `http://127.0.0.1:8551/`.
  - Browser path: in-app Browser plugin.
  - Desktop Overview: rendered AI Evidence Cockpit with nonblank cards, model evidence chips and compact ranked instrument table.
  - Scores route: `/signals` rendered configured universe scores and candidate stock/ETF evidence; after fix, tables did not overlap at 1280 px width.
  - Renew data: dialog opened; `Validate current data` showed dry-run validation output and did not crash.
  - Mobile viewport: 390 x 844 rendered top navigation and stacked Overview cards after responsive shell fix.
  - Console health: no browser error/warn logs during final Overview, Scores, Renew dialog or mobile checks.
- Screenshot evidence saved outside the repo:
  - `C:\Users\thor2\AppData\Local\Temp\etf-cockpit-ui-qa\desktop-overview.png`
  - `C:\Users\thor2\AppData\Local\Temp\etf-cockpit-ui-qa\desktop-scores.png`
  - `C:\Users\thor2\AppData\Local\Temp\etf-cockpit-ui-qa\renew-dialog.png`
  - `C:\Users\thor2\AppData\Local\Temp\etf-cockpit-ui-qa\mobile-overview.png`

## 2026-06-30

- Fail then pass: `cmd /c scripts\build_windows.bat` initially failed during PyInstaller `COLLECT` because stale packaged PID `52492` locked `build\flet_dist\ETF_AI_Cockpit`; stopped that exact project process and reran.
- Pass: patched build script, `cmd /c scripts\build_windows.bat` -> completed with fresh `build\flet_dist` and `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Pass: portable source smoke against rebuilt portable folder:
  - command: set `ETF_COCKPIT_ROOT=build\ETF_AI_Cockpit_Portable_v0.1.0`, set `PYTHONPATH=build\ETF_AI_Cockpit_Portable_v0.1.0\app\src`, then run `.\.venv\Scripts\python.exe build\ETF_AI_Cockpit_Portable_v0.1.0\scripts\run_app.py --smoke`
  - result: `snapshot_ok as_of=2026-06-30 signals=7 backtests=5`
- Pass: native executable readiness:
  - launched `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`
  - env: `ETF_COCKPIT_ROOT=build\ETF_AI_Cockpit_Portable_v0.1.0`, `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_PORT=8562`, `ETF_COCKPIT_OPEN_BROWSER=0`
  - result: `http://127.0.0.1:8562/` returned HTTP 200; process stopped afterwards.

## 2026-07-01

- Fail then pass: focused yfinance provider tests initially failed because missing optional action columns used scalar defaults; fixed with a zero-filled series helper.
- Pass: `.\.venv\Scripts\python.exe -m pytest tests\test_yfinance_provider.py -q` -> 5 passed.
- Pass: live configured Yahoo symbol probe:
  - `IWDA.DE` returned no data, while `IWDA.AS` returned rows; `WORLD_CORE` is mapped to `IWDA.AS`.
  - `XDEQ.DE`, `SXRV.DE`, `EXX1.DE`, `SXRJ.DE`, `EUNA.DE` and `4GLD.DE` returned recent rows.
- Pass: live yfinance full analysis, `PYTHONPATH=src; .\.venv\Scripts\python.exe scripts\run_yfinance_analysis.py --years 5`:
  - downloaded 8,903 Yahoo Finance price rows for 7 instruments;
  - yfinance as-of 2026-06-29;
  - validation status Warning;
  - baseline ok 35, TimesFM ok 28/skipped 7, Toto ok 35;
  - backtest quality medium;
  - report `data\reports\yfinance_full_analysis_20260701T012624Z.json`.
- Pass: clean-store probe -> all 8,903 clean price rows have `source=yfinance` and provider symbols match the configured Yahoo map.
- Pass: compile check, `.\.venv\Scripts\python.exe -m compileall src\etf_cockpit scripts`.
- Pass: full regression suite, `.\.venv\Scripts\python.exe -m pytest tests -q`, with only the known GluonTS JSON-speed warning.
- Pass: yfinance full analysis rerun after warning fix, `scripts\run_yfinance_analysis.py --years 5 --no-commit --skip-reference`:
  - downloaded 8,903 rows;
  - baseline ok 35, TimesFM ok 28/skipped 7, Toto ok 35;
  - report `data\reports\yfinance_full_analysis_20260701T012952Z.json`.
- Pass: app smoke, `PYTHONPATH=src; .\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-29 signals=7 backtests=5`.
- Pass: signal CLI, `PYTHONPATH=src; .\.venv\Scripts\python.exe scripts\run_signals.py --date latest` -> 7 ranked yfinance-backed `no_trade` rows due inside-deadband, with non-zero Toto/TimesFM score components.
- Pass: package rebuild, `cmd /c scripts\build_windows.bat` -> completed and refreshed `build\flet_dist` plus `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Pass: rebuilt native executable readiness:
  - launched `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`
  - env: `ETF_COCKPIT_ROOT=build\ETF_AI_Cockpit_Portable_v0.1.0`, `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_PORT=8563`, `ETF_COCKPIT_OPEN_BROWSER=0`
  - result: `http://127.0.0.1:8563/` returned HTTP 200; process stopped afterwards.

## 2026-07-01 Simple Scoring Verification

- Pass: compile check, `.\.venv\Scripts\python.exe -m compileall src\etf_cockpit`.
- Pass: simple-score unit/UI tests, `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py -q` -> 6 passed.
- Pass: focused UI startup tests after responsive fixes, `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_flet_startup.py -q` -> 12 passed.
- Pass: full regression suite after simple scoring implementation, `.\.venv\Scripts\python.exe -m pytest tests -q` -> passed.
- Pass: source app smoke, `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-29 signals=7 backtests=5`.
- Pass: live workflow command through `AppState`:
  - `refresh_yfinance_data()` committed 8,903 yfinance price rows, 7 metadata rows and 50 top-holdings rows;
  - `run_algorithm_scores()` wrote 12 candidate report rows as-of 2026-06-29;
  - `run_forecasting_models()` wrote configured forecasts with baseline ok 35, TimesFM ok 28/skipped 7, Toto ok 35;
  - candidate forecasts wrote baseline ok 60, TimesFM ok 48/skipped 12, Toto ok 60.
- Pass: simple score probe after workflow -> 19 rows, 7 configured ETFs, 12 candidates, top row `PRY 8.6 Strong Buy Candidate`, 0 `N/A` components after model refresh.
- Fail then pass: browser QA on source Overview initially showed blank grey main content. Root cause was Flet web layout trouble with wrapped rows containing expanded cards. Removed `wrap=True` from expanded card rows.
- Fail then pass: browser QA on Scores route initially showed the same blank grey main content. Applied the same card-row layout fix.
- Fail then pass: mobile browser QA initially showed truncated summary-card labels. Added narrow-width stacked summary cards on Overview and Scores.
- Pass: browser QA source app on port 8570:
  - Overview visible with 19 instruments, workflow buttons and score legend;
  - expanded top row shows Momentum/Trend/Risk/Relative strength details;
  - further scroll shows Baseline, TimesFM and Toto details;
  - Scores route visible with x/10 rows;
  - mobile viewport visible with stacked cards and vertical workflow buttons;
  - browser warning/error logs empty.
- Pass: final package rebuild, `cmd /c scripts\build_windows.bat` -> completed and refreshed `build\flet_dist` plus `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Pass: portable data-copy verification -> portable folder includes yfinance clean prices, forecasts, candidate reports and `data\raw\trade_candidates\yahoo_trade_candidates_2026-06-30.csv`.
- Pass: final native executable readiness:
  - launched `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`;
  - env: `ETF_COCKPIT_ROOT=build\ETF_AI_Cockpit_Portable_v0.1.0`, `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_PORT=8571`, `ETF_COCKPIT_OPEN_BROWSER=0`;
  - result: `http://127.0.0.1:8571/` returned HTTP 200;
  - browser screenshot showed 19 instruments, PRY 8.6/10 top score and model rows 21;
  - browser warning/error logs empty;
  - process stopped afterwards.
## 2026-07-01 Chrome QA and Build Verification

- Pass: instrument universe probe:
  - `build_simple_instrument_scores(...)` returned 19 rows.
  - 7 configured ETFs and 12 candidate stocks/ETFs were present.
  - Top rows included `PRY 8.6/10`, `SPYK 8.6/10`, `EXX1 8.2/10`.
- Pass: startup timing before/after:
  - Before fixes: `scripts/run_app.py --smoke` took 34.64 seconds.
  - After lightweight model checks and cached backtest load: 1.83-1.93 seconds.
- Pass: targeted tests after startup/cache/UI fixes:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_model_shapes.py tests\test_release_hardening.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_simple_scores.py -q`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_local_llm_audit.py tests\test_flet_startup.py tests\test_simple_scores.py -q`
- Pass: full regression suite:
  - `.\.venv\Scripts\python.exe -m pytest tests -q`
  - result: all tests passed.
- Pass: Chrome user-flow QA on source app:
  - Main page rendered on `http://127.0.0.1:8572/`.
  - Score row expanded and showed algorithm/model x/10 breakdown.
  - Scores page route `/signals` rendered and expandable rows worked.
  - Refresh yfinance button committed 8,910 Yahoo Finance price rows and updated data date to 2026-06-30.
  - Run algorithms button refreshed 12 candidate rows as of 2026-06-30.
  - Run forecasting models button completed via current-date cache reuse and displayed configured/candidate forecast summaries.
  - Renew/import dialog opened; dry-run validation worked and scrolled internally after fix.
  - Audit packet button exported `data/audit_packets/audit_packet_2026-06-30.zip`.
  - LM Studio check reported endpoint ok with model `qwen3.6-27b`.
  - Sidebar pages rendered: Portfolio Context, Risk Evidence, Instrument Detail, Backtests, Audit Notes, Data & Models, Settings, Diagnostics.
- Pass: build:
  - `.\scripts\build_windows.bat`
  - result: completed; refreshed `build\flet_dist` and `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Pass: rebuilt exe smoke:
  - launched `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_PORT=8573`.
  - `http://127.0.0.1:8573/` returned HTTP readiness.
  - Chrome rendered the Simple Scores main page with 19 instruments and 57 model rows.

## 2026-07-04 UI Startup and Package Verification

- Pass: focused startup tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py -q`
  - result: 7 passed.
- Pass: tmp-heavy regression subset:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_model_shapes.py tests\test_release_hardening.py tests\test_trade_proposals.py -q`
  - result: all selected tests passed.
- Pass: full regression suite:
  - `.\.venv\Scripts\python.exe -m pytest tests -q`
  - result: all tests passed.
- Pass: source web readiness after Flet temp patch:
  - launched `scripts\run_app.py` with `ETF_COCKPIT_PORT=8587`, `ETF_COCKPIT_OPEN_BROWSER=0`;
  - `http://127.0.0.1:8587/` returned HTTP 200;
  - stderr log was empty;
  - startup log showed patched Flet static temp path.
- Pass: package rebuild:
  - `.\scripts\build_windows.bat`
  - result: completed and recreated `build\flet_dist` and `build\ETF_AI_Cockpit_Portable_v0.1.0`.
  - non-fatal warnings: pip could not delete some `AppData\Local\Temp` scratch folders; PyInstaller reported optional torch/scipy hidden-import warnings.
- Pass: rebuilt exe HTTP smoke:
  - launched `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_PORT=8588`;
  - `http://127.0.0.1:8588/` returned HTTP 200;
  - packaged startup log showed `frozen=True` and patched Flet static temp path.
- Blocked: fresh Chrome visual QA in this turn.
  - Chrome extension backend was unavailable (`Browser is not available: extension` after retry).
  - Browser policy also rejected the in-app browser localhost navigation attempt, so no fallback screenshot was captured.
  - Previous Chrome QA from 2026-07-01 remains the latest full visual/button pass.

## 2026-07-04 Chrome Localhost Retest

- Pass: Chrome extension backend available on retry.
- Pass: source localhost readiness:
  - launched `scripts\run_app.py` with `ETF_COCKPIT_PORT=8589`;
  - `http://127.0.0.1:8589/` returned HTTP 200.
- Pass: Chrome page identity:
  - URL: `http://127.0.0.1:8589/`;
  - title: `ETF AI Evidence Cockpit`.
- Pass: first viewport visual check:
  - Simple Scores dashboard visible;
  - 19 instruments visible;
  - 57 model rows visible;
  - score legend, workflow buttons and top candidate rows visible.
- Pass: workflow button checks through Chrome:
  - Refresh yfinance data: committed 8,910 price rows and updated data date to 2026-07-02.
  - Run algorithms: refreshed 12 candidate rows as of 2026-07-03.
  - Run forecasting models: generated configured ETF forecasts as of 2026-07-02 and candidate forecasts as of 2026-07-03.
  - Show scores: routed to `/signals`.
- Pass: score-row expansion:
  - expanded top row on `/signals`;
  - verified visible Momentum, Trend, Risk/volatility and Relative strength x/10 cards.
- Pass: secondary pages:
  - `Data & Models` rendered current data/model inventory and forecast/candidate artefacts.
  - `Diagnostics` rendered package checks and GPU/model readiness.
- Console note:
  - Initial route produced Chrome extension message-channel noise after navigation, not visible app failure.
  - Later Diagnostics route reported zero console warn/error entries.

## 2026-07-04 Button Hit-Target Regression

- Fail then pass: Chrome QA showed workflow buttons were easier to trigger from the icon/left side than from some right-side label coordinates.
- Fix: replaced workflow buttons with fixed-size clickable containers in `src\etf_cockpit\app\pages\dashboard.py`.
- Pass: focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_simple_scores.py -q`
  - result: all selected tests passed.
- Pass: full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q`
  - result: all tests passed.
- Pass: restarted source app on `http://127.0.0.1:8589/`; HTTP 200 readiness.

## 2026-07-05 Report-Driven Scoreboard Verification

- Pass: score unit tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py -q`;
  - result: passed.
- Pass: yfinance provider plus score tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_yfinance_provider.py tests\test_simple_scores.py -q`;
  - result: passed.
- Pass: live yfinance candidate algorithm refresh:
  - command: `DataService(load_config()).run_yfinance_candidate_analysis()`;
  - result: 12 candidate instruments refreshed as of 2026-07-03;
  - report: `data\reports\yfinance_trade_candidate_analysis_20260705T000600Z.csv`.
- Pass: yfinance-derived stock evidence fields:
  - inspected report output;
  - stock candidates contained yfinance-derived `value_score_10`, `quality_score_10` and `analyst_revision_score_10` where available;
  - ETF candidates correctly left stock-fundamental-only fields as `N/A`.
- Pass: scoreboard generation:
  - command: built app snapshot and called `write_simple_scoreboard(...)`;
  - result: `data\derived\scoreboard.parquet` written with 19 rows.
- Pass: source app readiness:
  - launched source app on `http://127.0.0.1:8590/`;
  - HTTP readiness returned 200.
- Pass: Chrome visual/user-flow QA:
  - first viewport rendered the Simple Scores dashboard;
  - visible counts: 19 instruments and 57 model rows;
  - top score visible: SPYK 8.9/10;
  - expanded top row showed quality score, risk/friction score, component valid count, warnings, model authority and backtest trust;
  - expanded component rows showed authority and role chips;
  - `/signals` route rendered evidence categories and the 19-row score list;
  - `2. Run algorithms` completed from the UI and displayed a concise success message.
- Pass: full regression suite after final implementation and build:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: package build:
  - command: `.\scripts\build_windows.bat`;
  - result: completed after clearing a stale packaged-exe file lock.
- Pass: packaged executable smoke:
  - executable: `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`;
  - environment: `ETF_COCKPIT_ROOT=build\ETF_AI_Cockpit_Portable_v0.1.0`, `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_PORT=8591`, `ETF_COCKPIT_OPEN_BROWSER=0`;
  - result: `http://127.0.0.1:8591/` returned HTTP 200;
  - temporary process was stopped after the smoke test.
- Residual test gap:
  - Flet canvas still limits semantic locator coverage in Chrome; visual screenshot-guided QA was used instead.
  - Per-instrument backtest trust, model calibration metrics and regime modules remain planned rather than complete.

## 2026-07-05 Extended Sweep Verification

- Pass: new deterministic derivative tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_evidence_derivatives.py tests\test_simple_scores.py -q`;
  - result: passed.
- Pass: focused UI/startup tests after fixing Data & Models:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_evidence_derivatives.py tests\test_simple_scores.py tests\test_flet_startup.py -q`;
  - result: passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: real derived artefact generation:
  - command: `AppState.load(); state._write_current_scoreboard(); state.export_audit_packet()`;
  - result: scoreboard, calibration, regime and strategy-template files written under `data\derived`.
- Pass: audit packet contents:
  - verified ZIP contains `14_scoreboard.csv`, `14_scoreboard.json`, `15_model_calibration.csv`, `16_market_regime.json`, `17_strategy_templates.csv`, `18_derived_manifest.json` and per-instrument JSON files under `instrument_evidence/`.
- Pass: Chrome visual QA on `http://127.0.0.1:8592/`:
  - dashboard rendered the Regime card and 19 instrument list;
  - expanded row showed calibration, backtest, regime, portfolio-fit and strategy-template chips;
  - Data & Models page rendered derived artefacts, market regime and forecast calibration panels after the bug fix.
- Pass: package build:
  - command: `.\scripts\build_windows.bat`;
  - result: portable folder refreshed at `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Pass: packaged executable smoke:
  - launched native executable with `ETF_COCKPIT_PORT=8593`;
  - `http://127.0.0.1:8593/` returned HTTP 200;
  - temporary process stopped.
- Pass: portable derived-data presence:
  - checked `build\ETF_AI_Cockpit_Portable_v0.1.0\data\derived`;
  - confirmed scoreboard, calibration, market regime and strategy-template files are present after patching the build script.
- Console note:
  - Chrome showed repeated extension message-channel errors previously seen in this environment; no app traceback appeared and Flet screens rendered.
- Current honest calibration status:
  - current forecast files have no matured 60-day rows yet, so model calibration is correctly pending rather than scored.

## 2026-07-08 Report Issue Workflow And Evidence-Maturity Verification

- Pass: focused simple-score tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py -q`;
  - result: 11 tests passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: generated artefact check:
  - command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state._write_current_scoreboard(); state.export_audit_packet(); ..."`;
  - result: `data\derived\scoreboard.parquet` had 19 rows and included `evidence_sample_days`, `evidence_maturity_state`, `evidence_maturity_label`, `evidence_sanity_warnings`, `evidence_warning_count` and `too_good_to_be_true_warning`;
  - audit ZIP contained `14_scoreboard.csv` and `14_scoreboard.json`.
- Pass: issue-file location check:
  - command: `Get-ChildItem -Recurse -File issues`;
  - result: open/closed issue files and all three templates exist under `etf_ai_cockpit\issues`.
- Residual open items:
- source-credibility scoring was still open at this checkpoint and was closed in the later source-credibility pass.

## 2026-07-11 Final Verification

- Full pytest: 262 passed, exit 0 (`evidence\wave4\full-pytest-final-trust-policy.txt`).
- Compileall: exit 0 (`evidence\wave4\compileall-final-trust-policy.txt`).
- Scoped Ruff: exit 0, all checks passed (`evidence\wave4\ruff-final-trust-policy-scoped.txt`).
- Build and source/native/portable smoke: all exit 0; launcher start/reuse and package-cwd fallback tests: all exit 0.
- Chrome route matrix: all eight routes passed; rendered screenshots cover grouped rows, expansion, Sparebanken, Diagnostics, Evidence Ledger and audit export.
- Audit validation: valid, no checksum errors, no secret findings, 16 unique holdings, required unavailable markers and model advisory provenance present.
- Computer Use: failed/stopped at URL-confidence policy; not counted as a pass. In-app browser refusal remains a fallback limitation.

## 2026-07-10 Packaged Browser Matrix

- PASS: Windows Computer Use main-page render, grouped score sections, row expansion and lower-group scrolling.
- PASS: Windows Computer Use Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures, News & Context, Diagnostics and Errors & Recovery route renders.
- PASS: Windows Computer Use Data Health status rendering and Export health CSV success message.
- PASS: Windows Computer Use Universe tier/asset/ISIN status rendering, including Sparebanken `needs_verification` rows.
- PASS: First-run Setup, What Changed, Instrument Detail and Import & Export route renders.
- LIMITATION: direct packaged reload needed about five seconds after HTTP readiness before Flet content appeared; semantic DOM assertions are not reliable for this canvas UI.
- LIMITATION: in-app browser connection refusal remains recorded in `evidence/wave2/browser/in-app-browser-failure.txt`; no browser-smoke-required issue is closed on that basis.

## 2026-07-10 Task 23 Closure Gate

- PASS: focused session/ledger/audit bundle, 25 tests, exit code 0 with `-rA`.
- PASS: closure evaluator verified all required paths for `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` after SHA-256 sidecars were created.
- RESULT: 3/41 issues ready; 38/41 remain open with missing-gate report in `evidence/final/closure-report.json`.

## 2026-07-10 Source Foundation Gate

- Passed: `ruff check` on current feature files; no findings after the targeted cleanup.
- Passed: `pytest tests\\test_esef_provider.py -q` (1 test) after enforcing DataFrame-shaped discovery output.
- Passed: `pytest tests\\test_data_health.py tests\\test_fund_documents.py tests\\test_esef_provider.py tests\\test_esef_ixbrl_parser.py -q` (7 tests).
- Passed: import check for `FilingsXbrlOrgProvider` with `PYTHONPATH=src`.
- Non-passing baseline: repository-wide Ruff reports 53 findings; scoped mypy reports 11 errors including missing `types-PyYAML`/`types-defusedxml` and existing project typing debt.
- Closure checker: 41 records, 0 ready, exit code 1 as expected with no final evidence dossiers.

## 2026-07-10 Reviewer Findings Integration

- Passed: focused reviewer regression bundle (46 tests) covering launcher, yfinance, health, trust artefacts, session logs, route navigation, instrument detail, universe persistence and release hardening.
- Passed: scoped Ruff across all files touched in this cycle.
- Passed: compileall for the source tree after the atomic-import changes.
- Passed: source, native and portable-native smoke on ports 8580, 8581 and 8582 after fixing selected output manifest resolution.
- Failed then fixed: the first native smoke used stale build\flet_dist; the root cause was manifest selection in launcher_core._default_native_exe. A regression test now covers both native and portable manifests.
- Pending: fresh full pytest, fresh build, launcher batch smoke, final browser/Chrome/computer-use matrix and final audit/export verification after the latest source changes.

## 2026-07-10 All-41 Task 1 Baseline

- Pass: ` .\.venv\Scripts\python.exe -m pytest tests\test_closure_matrix.py -q` - 7 passed.
- Pass: ` .\.venv\Scripts\python.exe -m pytest --collect-only -q` - 138 collected.
- Pass: ` .\.venv\Scripts\python.exe -m pytest -q` - 138 passed.
- Pass: ` .\.venv\Scripts\python.exe -m compileall -q scripts src tests`.
- Pass: ` .\.venv\Scripts\python.exe scripts\run_app.py --smoke` - snapshot OK.
- Expected non-pass: `git status --short` - exit 128 because this is not a Git repository.
- Expected non-pass: closure status - 0/41 ready because no final evidence has been assigned.

## 2026-07-10 All-41 Task 2

- Pass: parser dependency install and development dependency install.
- Pass: dependency import command printed dependency_import_ok.
- Pass: focused official fixture suite - 2 passed.
- Pass: combined Tasks 1-2 focused suite - 9 passed.
- Recorded non-pass: Ruff check - 49 findings; details in evidence/wave1/dependencies/ruff.txt.

## 2026-07-10 All-41 Task 3

- Pass: atomic I/O, migrations, release hardening and trust-artifact focused suite - 42 passed.
- Pass: compileall over src and tests.
- Pass after corrected import path: persistent migration applied versions 1-4 and backup verification returned true.
- Recorded failure: first persistent migration evidence command lacked PYTHONPATH and failed before project import or data mutation.

## 2026-07-10 Post-Review Final Verification

- Pass: `.\.venv\Scripts\python.exe -m pytest tests\test_launcher_workflow.py tests\test_flet_startup.py tests\test_simple_scores.py tests\test_yfinance_provider.py tests\test_trust_critical_artifacts.py -q` -> 51 tests passed.
- Pass: `.\.venv\Scripts\python.exe -m pytest -q` -> exit 0; `--collect-only -q` confirms 131 tests.
- Pass: `.\.venv\Scripts\python.exe -m compileall -q scripts src tests` -> exit 0.
- Pass: `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-07-08 signals=16 backtests=5`.
- Pass: `cmd /c "set ETF_COCKPIT_PORT=8568&& Launch_Latest_ETF_AI_Cockpit.bat"` while default native and portable output folders were locked.
- Build selected `build\flet_dist_20260710_082721` and `build\ETF_AI_Cockpit_Portable_v0.1.0_20260710_083014`.
- Packaged PID 32160 ran from the selected portable folder, returned HTTP 200 on port 8568, reached readiness after 6.1 seconds and requested browser open.
- Browser pass: in-app browser title `ETF AI Evidence Cockpit`; rendered Simple Scores/workflow/Primary tier UI captured in `browser-final-launch-latest-locked-folders.png`.
- Cleanup pass: no repo-local packaged process or listener on ports 8567/8568 remained.
- Expected limitation: Flet still exposes only the `Enable accessibility` button in the semantic DOM snapshot, so `ISSUE-0045` remains open.

## 2026-07-09 Launcher, Sparebanken And Reliability Verification

- Baseline pass:
  - `git status --short` from the app root failed as expected because the folder is not a Git repository.
  - `.\.venv\Scripts\python.exe --version` -> Python 3.13.14.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_paths.py tests/test_flet_startup.py tests/test_release_hardening.py tests/test_simple_scores.py` -> 60 passed.
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-07-09 signals=0 backtests=0`.
- Focused pass:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_simple_scores.py tests/test_yfinance_provider.py tests/test_trust_critical_artifacts.py` -> 30 passed.
  - First launcher/startup focused run found a failure in `Launch_Latest_ETF_AI_Cockpit.bat` helper fallback; fixed and reran.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_launcher_workflow.py tests/test_flet_startup.py` -> 19 passed after adding output-folder path-file handling.
  - `.\.venv\Scripts\python.exe -m compileall -q scripts src tests` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_launcher_workflow.py tests/test_flet_startup.py tests/test_release_hardening.py tests/test_simple_scores.py tests/test_yfinance_provider.py tests/test_trust_critical_artifacts.py` -> 78 passed.
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-07-09 signals=0 backtests=0`.
- Source smoke:
  - First `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8550` failed because the app fell back to a free port while the smoke check polled the requested busy port.
  - Fixed smoke port selection to use `choose_launch_port`.
  - Rerun `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8550` -> passed with selected port 8552.
- Full suite:
  - `.\.venv\Scripts\python.exe -m pytest` -> 129 passed in 17.19s.
- Build:
  - First build attempt proved the old portable folder was locked by `logs\app.log`; the helper gave a clear lock error.
  - Added alternate output folder support and path-file handling for paths with spaces.
  - Final `.\scripts\build_windows.bat` -> passed.
  - Native exe exists at `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
  - Portable output created at `build\ETF_AI_Cockpit_Portable_v0.1.0_20260709_205522`.
- Launcher/package smoke:
  - Root BAT: `cmd /c "set ETF_COCKPIT_PORT=8560&& ETF_AI_Cockpit.bat"` -> passed, printed readiness and browser-open evidence.
  - Native smoke: `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode native --port 8563` -> passed.
  - Portable runner: `cmd /c "set ETF_COCKPIT_PORT=8564&& Run_ETF_AI_Cockpit_EXE.bat"` from the portable folder -> passed.
  - Portable readiness: `.\.venv\Scripts\python.exe scripts\launcher_core.py wait-ready --host 127.0.0.1 --port 8564 --timeout 10` -> passed.
  - Helper launcher smoke: `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode launcher --port 8565` -> passed.
- Browser/Playwright evidence:
  - Playwright loaded the source app and reported page title `ETF AI Evidence Cockpit`.
  - `browser-main-top.png` verifies the shell, workflow buttons and primary ETF section.
  - `browser-main-tall.png` verifies primary ETF, primary stock/equity-certificate and secondary ETF sections.
  - `browser-main-very-tall.png` verifies all requested group headings and Sparebanken rows with `needs_verification` where required.
  - `browser-row-expand-attempt.png` verifies score-row expansion.
  - Direct route screenshots verify Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures, News & Context and Diagnostics render.
- Limitation:
  - Flet web renders most visible text in a canvas; normal DOM `innerText` and semantic locators are not reliable. Screenshot-based and route-readiness evidence was used, and `ISSUE-0045` remains open for semantic locator/accessibility hooks.

## 2026-07-08 Button Reliability And Progress Verification

- Pass: focused startup/progress tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py -q`;
  - result: 11 tests passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: local source app smoke:
  - command: start `scripts\run_app.py` with `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_PORT=8595`, `ETF_COCKPIT_OPEN_BROWSER=0`;
  - result: `http://127.0.0.1:8595/` returned HTTP 200.
- Pass: browser visual verification:
  - dashboard loaded in system Chrome with no clean-session console errors;
  - `Refresh yfinance data` displayed global and dashboard progress, then success text;
  - `Run algorithms` displayed progress, then success text and updated top-score state;
  - `Run forecasting models` displayed progress, then success text without launching uncached long optional models;
  - `Show scores` rendered the Scores page;
  - score row expansion displayed evidence chips, component explanations and x/10 scores;
  - sidebar navigation rendered Settings and Audit Notes;
  - Audit Notes `Export audit packet` produced a visible ZIP path.
- Pass: package rebuild:
  - command: `.\scripts\build_windows.bat`;
  - first result: failed because `build\flet_dist` was locked by a stale `ETF_AI_Cockpit.exe`;
  - recovery: stopped that packaged app process only;
  - second result: success, `Portable folder created at build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Pass: packaged app smoke:
  - command: start `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_PORT=8596`, `ETF_COCKPIT_OPEN_BROWSER=0`;
  - result: `http://127.0.0.1:8596/` returned HTTP 200;
  - browser result: dashboard rendered after Flet web assets loaded; clean packaged browser run had no console errors.
- Pass: source button audit:
  - command: `rg -n "on_click=.*page\.go|page\.go\(" src\etf_cockpit\app`;
  - result: no remaining direct route callbacks outside the `navigate_to()` helper.
- Residual open item:
  - not all future roadmap/product buttons exist yet; complete exhaustive UI locator coverage remains tracked by `ISSUE-0011`, `ISSUE-0014` and `ISSUE-0045`.

## 2026-07-08 Corrected Tracker Integrity Checks

- Pass: open issue numbering:
  - command: `Select-String -Path issues\open.md -Pattern '^## ISSUE-(\d{4})'`;
  - result: 59 open issue headings: `0007`, `0008`, `0010` and `0011` through `0066`.
- Pass: completed issue preservation:
  - command: `Select-String -Path issues\closed.md -Pattern '^### ISSUE-(\d{4})'`;
  - result: 7 completed issue headings: `0001`, `0002`, `0003`, `0004`, `0005`, `0006`, `0009`.
- Pass: expected open id diff:
  - command: PowerShell expected-id comparison against `0007`, `0008`, `0010` and `0011..0066`;
  - result: no missing expected open ids and no unexpected open ids.
- Pending in this entry:
  - full pytest suite;
  - package rebuild;
  - rebuilt app startup;
  - local URL/UI smoke check.

## 2026-07-08 Corrected Tracker Repair Release Checks

- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Initial rebuild attempt blocked:
  - command: `.\scripts\build_windows.bat`;
  - result: build folder was locked by a stale `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` process.
  - resolution: stopped only the stale project packaged app process.
- Pass: rebuild after clearing stale process:
  - command: `.\scripts\build_windows.bat`;
  - result: `Portable folder created at build\ETF_AI_Cockpit_Portable_v0.1.0`.
  - non-fatal warnings: optional PyInstaller warnings for TensorBoard/Triton/pycparser/scipy hook collection.
- Pass: rebuilt app source smoke:
  - command: start `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_PORT=8594`, `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_OPEN_BROWSER=0`;
  - result: process started as PID 18260.
- Pass: local URL readiness:
  - command: `Invoke-WebRequest http://127.0.0.1:8594/ -UseBasicParsing`;
  - result: HTTP 200, HTML shell length 3775 bytes.
- Pass: Chrome visual smoke:
  - command: Playwright against system Chrome at `C:\Program Files\Google\Chrome\Application\chrome.exe`;
  - result: screenshot showed the rebuilt app rendered the `Simple Scores` dashboard with sidebar navigation, workflow buttons and score list.
  - limitation: Flet rendered text was not exposed as normal DOM `innerText`, so semantic text assertions remain an open `ISSUE-0045` task.
- Cleanup:
  - command: stopped PID 18260;
  - result: packaged smoke process stopped.

## 2026-07-08 Source Credibility Verification

- Pass: focused release-hardening tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q`;
  - result: 30 tests passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: generated audit check:
  - command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state.export_audit_packet(); ..."`;
  - result: current local audit correctly reports no manual notes; fixture tests verify exported credibility metadata when manual notes exist.
- Residual open items:
  - no report-derived P0/P1 implementation issue remains open.

## 2026-07-08 Benchmark Attribution Verification

- Pass: focused attribution and score tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_evidence_derivatives.py tests\test_simple_scores.py -q`;
  - result: 16 tests passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: generated artefact check:
  - command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state._write_current_scoreboard(); state.export_audit_packet(); ..."`;
  - result: scoreboard had 19 rows and included `benchmark_id`, `benchmark_period_days`, `benchmark_return`, `instrument_period_return`, `benchmark_beta`, `benchmark_correlation`, `alpha_proxy`, `alpha_t_stat`, `benchmark_attribution_label` and `sector_theme_warning`;
  - configured ETF row `US_TECH` showed benchmark `WORLD_CORE`, beta `1.2960`, correlation `0.8448`, alpha proxy `0.0446` and sector/theme warning text;
  - audit ZIP contained updated scoreboard CSV/JSON.
- Residual open items:
  - source-credibility scoring was still open at this checkpoint and was closed in the later source-credibility pass.

## 2026-07-11 Approved Programme Baseline

- Pass: `..\\.venv\\Scripts\\python.exe -m pytest tests -q` exited 0.
- Pass: `..\\.venv\\Scripts\\python.exe -m ruff check src tests` reported `All checks passed!`.
- Pass: `..\\.venv\\Scripts\\python.exe -m compileall -q src` exited 0.
- Pass: `..\\.venv\\Scripts\\python.exe scripts\\run_app.py --smoke` reported `snapshot_ok`.
- Pass: `..\\.venv\\Scripts\\python.exe scripts\\smoke_app.py --mode source|native|portable-native` each exited 0 on ports 8660-8662.
- Pass: a temporary source run on port 8663 rendered the Simple Scores route in the in-app browser; the process was then stopped.
- The historic mypy non-zero state remains pre-existing and is not attributed to the new programme.

## 2026-07-11 Trust Policy Review-Fix Verification

- Pass: focused trust policy bundle: `\\.venv\\Scripts\\python.exe -m pytest -q tests\\test_simple_scores.py tests\\test_complete_audit_packet.py tests\\test_trust_critical_artifacts.py tests\\test_data_contracts.py tests\\test_provider_registry.py`; 49 passed.
- Pass: full regression: `\\.venv\\Scripts\\python.exe -m pytest -q -rA`; 259 passed, exit code 0.
- Pass: compile check: `\\.venv\\Scripts\\python.exe -m compileall -q src scripts tests`.
- Pass: scoped Ruff on touched source/tests. Full Ruff remains a recorded baseline failure in unrelated scripts.
- Pending: rebuild, source/native/portable launcher smoke and fresh browser evidence after the latest source changes.

## 2026-07-11 Follow-Up Review Verification

- Pass: focused follow-up trust tests covering session/workflow JSON-string redaction, unknown source prefix, model authority, exact holdings and manifest requirements.
- Pass: full regression `pytest -q -rA`; 262 passed, exit code 0.
- Pass: compileall and scoped Ruff after the follow-up fixes.
- Pending: second rebuild and fresh packaged source/native/portable/browser/archive evidence.

## 2026-07-10 ISSUE-0035 Final Gate

- Pass: final `pytest -q -rA` -> 244 passed, exit code 0 (`evidence/wave4/full-pytest-responsive-final.txt`).
- Pass: focused Data Health/Simple Scores/Flet/e2e run -> 39 passed (`evidence/wave4/focused-data-health-responsive-final.txt`).
- Pass: closure-matrix tests -> 9 passed (`evidence/wave4/closure-matrix-tests-after-issue-0035.txt`).
- Pass: final build -> exit code 0 (`evidence/wave4/build-responsive-data-health.txt`).
- Pass: source/native/portable smoke -> ports 8590/8591/8592 all exit code 0; long-running native launch on 8593 reached readiness.
- Pass: Data Health export -> 11 rows and required full header (`evidence/wave4/data-health-export-responsive-final.txt`).
- Pass: Playwright desktop/1040px Data Health and Dashboard screenshots; zero console errors. Computer Use is explicitly a failed fallback attempt, not a pass.

## 2026-07-10 Data Health Responsive UI

- Pass: `\.venv\Scripts\python.exe -m pytest tests\test_data_health.py -q -rA` -> 3 passed after the responsive UI correction.
- Pass: `\.venv\Scripts\python.exe -m pytest -q -rA` -> 244 passed before the final responsive-row styling/header correction; rerun after rebuild is required.
- Pass: `\.venv\Scripts\python.exe -m compileall -q scripts src tests` and scoped Ruff over the four touched Data Health/dashboard/test files before the final responsive-row correction.
- Pass: `cmd /c scripts\build_windows.bat` and source/native/portable smoke on ports 8590/8591/8592 for the first Data Health implementation; those package artefacts are stale relative to the final responsive-row correction.
- Fallback browser: Playwright loaded packaged `http://127.0.0.1:8593/data-health`, HTTP/readiness and console error checks passed; the screenshot exposed the clipping defect. Computer Use stopped with URL-confidence error and is not counted as pass.

## 2026-07-08 Model/Backtest Validity Verification

- Pass: focused simple-score tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py -q`;
  - result: 13 tests passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: generated scoreboard/audit check:
  - command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state._write_current_scoreboard(); state.export_audit_packet(); ..."`;
  - result: scoreboard and audit scoreboard JSON include `backtest_validity`, `model_contamination_risk`, `model_authority_reason` and `calibration_required`.
- Residual open items:
  - source-credibility scoring was still open at this checkpoint and was closed in the later source-credibility pass.

## 2026-07-08 Cost Stress Verification

- Pass: focused cost-stress/audit tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_signal_gates.py tests\test_release_hardening.py -q`;
  - result: 32 tests passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: generated audit signal table check:
  - command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state.export_audit_packet(); ..."`;
  - result: `02_signal_table.csv` includes `cost_low_bps`, `cost_base_bps`, `cost_high_bps`, `edge_to_cost_low`, `edge_to_cost_base`, `edge_to_cost_high`, `cost_stress_warning` and `cost_stress_assumptions`.
- Residual open items:
  - source-credibility scoring was still open at this checkpoint and was closed in the later source-credibility pass.

## 2026-07-09 report.md Tracker Coverage Verification

- Pass: roadmap/tracker coverage check.
- Command:

```powershell
$open = Get-Content -Raw issues\open.md
$closed = Get-Content -Raw issues\closed.md
$plan = Get-Content -Raw plan.md
$all = $open + "`n" + $closed + "`n" + $plan
$expectedOpen = @('ISSUE-0007','ISSUE-0008','ISSUE-0010') + (11..66 | ForEach-Object { 'ISSUE-{0:D4}' -f $_ })
$expectedClosed = (1..6 | ForEach-Object { 'ISSUE-{0:D4}' -f $_ }) + 'ISSUE-0009'
$expectedRejected = 1..8 | ForEach-Object { 'REJECTED-{0:D4}' -f $_ }
```

- Result:
  - open issue headings: 59;
  - closed issue headings: 7;
  - rejected headings: 8;
  - issue template count: 3;
  - missing expected open issue IDs: none;
  - missing expected closed issue IDs: none;
  - missing expected rejected IDs: none;
  - missing report-derived keywords checked: none.
- Notes:
  - This was a documentation/tracker consistency task, so no app rebuild or UI smoke was required.
  - The project folder does not contain a `.git` directory, so `git diff` is not available from this path; verification used direct file and content checks.

## 2026-07-09 updatev2.md Roadmap Transfer Verification

- Pass: roadmap/tracker/report coverage check.
- Expected coverage:
  - 21 namespaced updatev2 open implementation issues: `UPDATEV2-0010` through `UPDATEV2-0030`;
  - 6 research-only closures: `CLOSED-RESEARCH-001` through `CLOSED-RESEARCH-006`;
  - root index files: `REPORT.md`, `ISSUES.md`, `CLOSED.md`;
  - key roadmap terms: provider registry, source authority, evidence ledger, SEC EDGAR, ESEF/iXBRL, ETF disclosures, PRIIPs KID, SFDR, Stooq, Twelve Data, Tiingo, candle evidence, audit packet expansion and rebuild/test/update discipline.
- Command:

```powershell
$files = @('plan.md','issues\open.md','issues\closed.md','REPORT.md','ISSUES.md','CLOSED.md','.ai_worklog\PLAN.md','.ai_worklog\WORKLOG.md','.ai_worklog\CHANGES.md','.ai_worklog\TESTING.md')
$expectedUpdateIssues = 10..30 | ForEach-Object { 'UPDATEV2-{0:D4}' -f $_ }
$expectedClosures = 1..6 | ForEach-Object { 'CLOSED-RESEARCH-{0:D3}' -f $_ }
```

- Result:
  - files checked: 10;
  - missing files: none;
  - updatev2 open issue headings: 21;
  - missing updatev2 open IDs: none;
  - research closure headings: 6;
  - missing research closures: none;
  - missing checked roadmap keywords: none.
- Notes:
  - This is documentation/tracker transfer work only; no app rebuild or UI smoke is required unless app/runtime code changes.

## 2026-07-09 Score History Roadmap Verification

- Pass: roadmap/tracker coverage check.
- Command checked `plan.md`, `issues\open.md`, `ISSUES.md`, `.ai_worklog\PLAN.md`, `.ai_worklog\WORKLOG.md` and `.ai_worklog\CHANGES.md` for:
  - `ISSUE-0067`;
  - `score_history.parquet`;
  - `score_metric_history.parquet`;
  - `final_combined_score_10`;
  - `normalised_score_10`;
  - total-score evolution chart wording;
  - expanded ETF/stock row wording;
  - Current Open Priorities and Phase B placement.
- Result:
  - `ISSUE-0067` open issue heading present: 1;
  - `ISSUE-0067` priority placement in `plan.md`: 2 references;
  - missing checked terms: none.
- Notes:
  - This was documentation/tracker work only; no app rebuild or UI smoke was required.

## 2026-07-09 Simple Scores Grey Panel Fix Verification

- Pass: Python compile check.
  - Command: `.\.venv\Scripts\python.exe -m compileall src`.
  - Result: source package compiled successfully.
- Pass: focused UI/startup tests.
  - Command: `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_flet_startup.py -q`.
  - Result: 24 tests passed.
- Pass: full regression suite.
  - Command: `.\.venv\Scripts\python.exe -m pytest tests -q`.
  - Result: all tests passed.
- Pass: rendered source UI smoke check.
  - URL: `http://127.0.0.1:8562/`.
  - Viewport: 1920 x 1200.
  - Result: Simple Scores page rendered score rows in the first viewport; the reported grey panel was not present.
  - Console: direct Chrome capture showed no page errors and only the expected `Flutter app loaded` console log.
- Pass: Windows package rebuild.
  - Command: `.\scripts\build_windows.bat`.
  - Result: `build\ETF_AI_Cockpit_Portable_v0.1.0` refreshed successfully.
- Pass: rebuilt executable smoke test.
  - Executable: `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
  - URL: `http://127.0.0.1:8550/`.
  - Result: HTTP 200; Chrome screenshot showed visible score rows and no grey panel.
  - Console: direct Chrome capture showed no page errors and only the expected `Flutter app loaded` console log.
- Note:
  - Browser automation can visually press the Flutter canvas controls but did not reliably trigger Flet callbacks in headless mode; rendered layout and console health were verified by screenshot and source tests.

## 2026-07-09 Two-Tier Universe Verification Plan

- Required checks for this implementation:
  - `load_config()` succeeds.
  - Removed IDs are absent: `JAPAN_EQUITY`, `GLOBAL_BONDS`, `GOLD_HEDGE`.
  - All 16 primary tier IDs are present once.
  - All 29 secondary tier IDs are present once.
  - No ISIN or yfinance ticker duplicates cross primary/secondary tiers.
  - Simple Scores can build pending `Primary tier` and `Secondary tier` rows without running yfinance refresh, algorithms or forecasts.
  - Rebuilt app opens and displays tiered rows.
- Explicitly skipped by user request:
  - yfinance refresh;
  - Run algorithms;
  - TimesFM/Toto/AI forecasting.

## 2026-07-09 Two-Tier Universe Verification Results

- Pass: compile check.
  - Command: `.\.venv\Scripts\python.exe -m compileall src`.
  - Result: source package compiled successfully.
- Pass: focused startup/simple-score tests.
  - Command: `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_flet_startup.py -q`.
  - Result: 26 tests passed.
- Pass: static two-tier config/data check.
  - Command: inline `load_config()` / candidate CSV check.
  - Result: `primary=16 secondary=29 candidate_file=yahoo_trade_candidates_2026-07-09.csv`; deleted IDs absent; no duplicate ISIN or yfinance ticker across tiers.
- Pass: full regression suite.
  - Command: `.\.venv\Scripts\python.exe -m pytest -q`.
  - Result: all tests passed.
- Pass: no-refresh score snapshot check.
  - Command: inline `build_snapshot()` / `build_simple_instrument_scores()` check.
  - Result: 45 rows, 16 primary and 29 secondary; `VWCE`, `MSFT` and `RABO` appear as pending/N/A without invented scores.
- Pass: Windows package rebuild.
  - Command: `.\scripts\build_windows.bat`.
  - Result: `build\ETF_AI_Cockpit_Portable_v0.1.0` refreshed successfully.
- Pass: rebuilt executable smoke test.
  - Command: launch `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_VIEW=web`, `ETF_COCKPIT_PORT=8550`, `ETF_COCKPIT_OPEN_BROWSER=0`.
  - Result: `http://127.0.0.1:8550/` returned HTTP 200.
- Pass: rendered Browser smoke check.
  - Result: first viewport showed 45 instruments, `16 primary, 29 secondary`, workflow buttons and pending score rows.
  - Interaction: expanded the `AIR` row; detail chips and component rows became visible.
  - Scroll checks: later list positions showed mixed primary/secondary rows including `LR`, `LYP6`, `MSFT`, `NEX`, `VIE` and `VWCE`.
  - Console: no browser warnings or errors during checked interactions.
  - Note: Browser DOM snapshot API failed with `incrementalAriaSnapshot is not a function`; screenshots, console logs and visual interaction checks were used instead.
- Pass: desktop shortcut helper.
  - Command: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\create_desktop_shortcut.ps1`.
  - Result: `C:\Users\thor2\Desktop\ETF AI Evidence Cockpit.lnk` created/updated.
- Explicitly skipped:
  - yfinance refresh;
  - Run algorithms;
  - TimesFM/Toto/AI forecasting.

## 2026-07-09 Trust-Critical Sweep Test Plan

Required checks for the current implementation sweep:

- `logs/session.jsonl` clears on new app server start and records `session_start`.
- Button/workflow actions write start, step and success/failure events with a stable action ID.
- Secret-like values are redacted from session logs and audit exports.
- Provider probes write `data/clean/provider_probe_results.parquet` without requiring API keys.
- Identity resolver writes `data/clean/instrument_identity.parquet` for primary and secondary instruments.
- Source conflict resolver writes schema-valid `data/clean/source_conflicts.parquet`, even when no conflicts are found.
- Evidence ledger and score component audit trail write schema-valid Parquet stores.
- Score history and metric history append score snapshots without changing current actions.
- Expanded score rows show score history or an honest insufficient-history state.
- Diagnostics/Data UI surfaces render provider, identity, conflict, evidence and session-log state.
- Audit/evidence export includes new stores, configs, plan/open issue snapshots, checksums and `session.jsonl` or unavailable markers.
- Optional official filing, ETF document and news providers show unavailable/null states when no source is configured or imported.
- Full release gate after implementation:
  - `.\.venv\Scripts\python.exe -m compileall src`
  - `.\.venv\Scripts\python.exe -m pytest`
  - `.\scripts\build_windows.bat`
  - rebuilt app HTTP smoke on `http://127.0.0.1:8550/`
  - browser/user-perspective UI smoke.

## 2026-07-09 Trust-Critical Sweep Test Results

- Pass: compile check.
  - Command: `.\.venv\Scripts\python.exe -m compileall src`.
  - Result: source compiled successfully.
- Pass: focused trust-critical and Simple Scores regression tests.
  - Command: `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_trust_critical_artifacts.py -q`.
  - Result: 21 tests passed.
  - Added regression: `simple_score_tiles()` must contain visible `VWCE` and `MSFT` row text, preventing the grey blank-list bug from returning.
- Pass: full regression suite.
  - Command: `.\.venv\Scripts\python.exe -m pytest -q`.
  - Result: all tests passed.
- Pass: package rebuild.
  - Command: `.\scripts\build_windows.bat`.
  - Result: `build\ETF_AI_Cockpit_Portable_v0.1.0` refreshed successfully.
  - Note: PyInstaller emitted optional Torch/TensorFlow/scipy hook warnings during dependency discovery; build completed successfully.
- Pass: packaged executable startup.
  - Executable: `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
  - URL: `http://127.0.0.1:8550/`.
  - Result: port 8550 live; app wrote `session_start` to packaged `logs\session.jsonl`.
- Pass: real Chrome/Windows visual smoke.
  - Main Simple Scores page showed 45 instruments, `16 primary, 29 secondary`, workflow buttons, score legend and visible pending rows.
  - Grey-panel bug was gone after the `_score_tile()` return fix.
  - Expanded first score row and verified detailed evidence chips, model/backtest pending status, cost/edge N/A, and no fake score.
  - Navigated and visually verified:
    - Provider Status;
    - Evidence Ledger;
    - Filings & Statements;
    - ETF Disclosures;
    - News & Context;
    - Diagnostics.
  - Diagnostics showed runtime diagnostics plus `logs/session.jsonl` status and recent route/button events.
- Limitations:
  - Chrome extension and Playwright MCP transports became unreliable during the long rebuilt-app smoke; Windows Computer Use capture was used for the final user-perspective visual verification.
  - One-shot headless Chrome screenshots captured only the Flet loader, so they were not used as pass/fail evidence.
  - Optional SEC/ESEF/KID/methodology/news sources are currently represented as explicit missing/unavailable inventories when no local files or provider are configured.

## 2026-07-08 Backtest Payoff Verification

- Pass: focused backtest/UI startup tests:
  - command: `.\.venv\Scripts\python.exe -m pytest tests\test_backtest_costs.py tests\test_flet_startup.py -q`;
  - result: 11 tests passed.
- Pass: full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Pass: snapshot/audit export check:
  - command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state.export_audit_packet(); ..."`;
  - result: snapshot backtest results and `05_backtest_summary.json` contain `return_hit_rate`, `average_win_return`, `average_loss_return`, `payoff_ratio`, `expected_value_per_period` and `payoff_asymmetry_warning`.
- Residual open items:
  - source-credibility scoring was still open at this checkpoint and was closed in the later source-credibility pass.

## 2026-07-11 Wave 0 Task 1 Verification

- RED: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py -q` - exit 1 during collection with expected `ModuleNotFoundError: No module named 'etf_cockpit.operations'` before behavioural code existed.
- GREEN and focused regression: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q` - exit 0, 15 passed.
- Full regression: `.\.venv\Scripts\python.exe -m pytest tests -q` - exit 0; warnings were pre-existing GluonTS JSON performance, pandas mixed-dtype and pandas concatenation deprecation warnings.
- Scoped lint: `.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\operations src\etf_cockpit\core\closure.py tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py` - exit 0, `All checks passed!`.
- Compilation: `.\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit\operations src\etf_cockpit\core\closure.py` - exit 0.
- Direct matrix probe - exit 0: programme schema 2, historic baseline 41, 42 active records, DATA-05 `still_open`, gates `audit/browser/package/schema/source/tests/ui`.
- SHA-256: operations init `8c8ee081d0a4fdc3e72a543702ccca1d863413fdf79ba51ff8f7f29681740e48`; operations models `e648ff729aa29beb2754a44911d8293ec0fcd142941fbb4c52e466f8487275f8`; closure parser `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595`.

## 2026-07-11 Wave 0 Task 1 Important Reviewer-Finding Fix Verification

- RED: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py -q` - exit 1. New real-Pydantic tests failed because approved evidence accepted a blank reviewer and a whitespace-equivalent reviewer; the added normalised-storage test also failed because surrounding whitespace remained stored.
- GREEN and scoped regression: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q` - exit 0, 18 passed.
- Scoped lint: `.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\operations\models.py tests\operations\test_verification_records.py` - exit 0, `All checks passed!`.
- Compilation: `.\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit\operations` - exit 0.
- SHA-256: operations init `8c8ee081d0a4fdc3e72a543702ccca1d863413fdf79ba51ff8f7f29681740e48`; operations models `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`; closure parser `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595`.
- Status: the Round-1 independent review reported an Important finding. This local fix has not yet had the required fresh independent re-review; no issue or closure-matrix status changed.

## 2026-07-11 Wave 0 Task 1 Final Covering Verification

- Pass: `./.venv/Scripts/python.exe -m pytest tests/operations/test_verification_records.py tests/release/test_issue_evidence.py tests/test_closure_matrix.py -q` - 18 passed.
- Pass: scoped Ruff over the operations, closure and Task 1 regression files - `All checks passed!`.
- Pass: compilation of the operations and closure modules - exit 0.
- Pass: `./.venv/Scripts/python.exe scripts/run_app.py --smoke` - `snapshot_ok as_of=2026-07-09 signals=16 backtests=5`.
- Final independent task review approved; no issue status changed.

## 2026-07-11 Wave 0 Task 2 Verification

- RED: `.\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_event_store.py -q` - exit 1 for the schema-invalid complete-row contextual-integrity assertion.
- GREEN: the same command - exit 0, 6 passed.
- First review bundle: `.\\.venv\\Scripts\\python.exe -m pytest tests\\operations\\test_operational_events.py tests\\operations\\test_event_store.py tests\\operations\\test_redaction.py tests\\test_trust_critical_artifacts.py -q` - exit 0, 21 passed.
- Authority-fix RED: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_workflow_runtime.py -q` - exit 1, 2 failures and 5 passes for the secondary workflow log and stale dashboard path.
- Authority-fix GREEN: same command - exit 0, 7 passed.
- Final focused review bundle: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_workflow_runtime.py tests\\operations\\test_operational_events.py tests\\operations\\test_event_store.py tests\\operations\\test_redaction.py tests\\test_trust_critical_artifacts.py -q` - exit 0, 28 passed.
- Full regression: `.\\.venv\\Scripts\\python.exe -m pytest tests -q` - exit 0. Existing warnings were GluonTS JSON performance, pandas mixed-dtype loading and pandas concatenation deprecation.
- Scoped Ruff over all Task 2 implementation and regression files - exit 0, `All checks passed!`.
- Scoped compilation over all Task 2 implementation and regression files - exit 0.
- Fresh independent review 2 approved with no findings. No issue status changed and Task 3 was not started.
