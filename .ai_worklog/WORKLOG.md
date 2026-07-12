# Worklog

## 2026-06-27

- Read the active Codex goal objective file at `C:\Users\thor2\.codex\attachments\18b76f6d-6445-4164-adab-cceec5fd5bf1\goal-objective.md` before continuing.
- Read the newer attached addendum request at `C:\Users\thor2\.codex\attachments\706ed3ec-394e-43b0-b7b1-5c263fe1b00b\pasted-text.txt`.
- Re-read `ETF_AI_Portfolio_Cockpit_Master_Spec.md` headings and inspected the current repository against the master spec and addendum.
- Inspected config, services, providers, storage, validation, feature pipeline, signal scoring, risk gates, action mapping, model adapters, backtest engine, UI pages and existing tests.
- Expanded `.ai_worklog\PLAN.md` into a durable product plan, gap map, calculation definition document, UI target and ticket list.
- Added provider configuration, provider redaction, a manual local-file provider, a generic safe HTTP/API provider stub and a visible `Renew data` workflow.
- Added dataset provenance metadata and price freshness tiers with source, as-of date, staleness and checksum shown in the Data & Models page.
- Added target-policy validation. The current sample `WORLD_CORE` 42% target now blocks trading because it exceeds the 35% single-ETF cap.
- Hardened final signal actions so release-facing outputs are advisory `manual_review`, `no_trade`, `hold`, `add_candidate` or `trim_candidate`.
- Expanded signal support metrics with drift, expected edge, estimated cost, edge-to-cost ratio, minimum trade value, final action and full reason text.
- Added model-unavailable metadata so TimesFM/Toto unavailable forecasts have null expected/quantile values and `model_allowed_in_score=false`.
- Added backtest quality diagnostics and removed silent forward-fill from the backtest price pivot.
- Added audit export validation/risk-gate reports and imported external audit notes with `executable_authority=false`.
- Fixed the Flet 0.85 dialog API path from old `page.dialog` assignment to `page.show_dialog()`/`page.pop_dialog()`.
- Added release-hardening regression tests and grew the test suite from 18 to 26 tests.
- Verified the source UI through the in-app browser on port 8551, including Renew Data no-provider and dry-run branches.
- Rebuilt the packaged app after stopping the old packaged process that was locking the prior build output.
- Verified the rebuilt packaged executable renders at `http://127.0.0.1:8550/` and the packaged Renew Data dry-run dialog works.
- Upgraded the Renew Data local-import option from explanatory text to a real file picker for CSV, XLSX, JSON and Parquet files; selected price files are validated through the provider/service layer before any replacement.
- Rebuilt the package again after the file-picker change and confirmed the packaged exe returned HTTP 200.
- Read the Codex goal objective file and confirmed the target remains a local Windows ETF AI Portfolio Cockpit with conservative signal logic, optional AI adapters, packaging and tests.
- Read project `AGENTS.md`, README files, requirements and launcher scripts.
- Found that `ETF_AI_Cockpit.bat` was a Python development bootstrapper that installed dependencies every run. That made it a confusing double-click target after packaging.
- Updated `ETF_AI_Cockpit.bat` so it starts `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` when present, with a clear Python fallback when the exe is absent.
- Extracted the supplied TimesFM and Toto archives to `models\source_archives`.
- Inspected the extracted docs and found that Toto 2.0 uses the `toto2` runtime package, while the existing adapter checked the legacy `toto` module.
- Updated the Toto adapter to check/import `toto2` and added a regression test for that runtime name.
- Confirmed LM Studio is reachable at `http://127.0.0.1:1234/v1/models`, but left the app independent of it.
- Reproduced the user's blank packaged launch and confirmed the native Flet desktop renderer can open a blank shell even for a minimal Flet app on this Windows setup.
- Moved the default launcher to Flet web mode on `127.0.0.1:8550`, while keeping `ETF_COCKPIT_VIEW=desktop` available as an opt-in.
- Fixed initial route rendering so the dashboard is built immediately instead of waiting for a route-change event that may not fire.
- Updated shell rendering to keep a root `View` and replace it atomically, avoiding the earlier `views list is empty` browser error.
- Updated `scripts\build_windows.bat` to bundle `flet_web` runtime assets and hidden imports required by the packaged local web server.
- Added packaged startup logging under `logs\startup.log`, `logs\stdout.log` and `logs\stderr.log`.
- Fixed the windowed PyInstaller/Uvicorn crash where `sys.stderr` was `None` and Uvicorn logging called `isatty()`.
- Removed the custom in-app browser polling thread after it caused the packaged web server to accept sockets without returning content. The batch launcher now waits with `curl.exe` and opens the browser only after HTTP responds.
- Rebuilt and verified `ETF_AI_Cockpit.bat` starts the packaged exe, serves `http://127.0.0.1:8550/`, and renders the dashboard in Edge via a DevTools screenshot.
- Fixed the backtest rebalance loop so signals schedule trades for the next available price row instead of applying new weights on the same signal row.
- Added `signal_date` and `execution_date` to backtest trade logs, with `date` preserved as the execution date for compatibility.
- Added a regression test proving all backtest trade execution dates are strictly after signal dates.
- Added portfolio-holdings validation for required columns, numeric values, duplicate/unknown ETFs, units-price-value reconciliation, current ETF concentration, residual cash and stale holdings snapshots.
- Wired holdings validation into normal snapshots, signal generation and the Renew Data dry-run path.
- Confirmed the sample portfolio now blocks on both target-policy violation and current concentration violation, forcing `manual_review`.
- Added a validated local price import commit pipeline: source copy to `data\raw\prices`, previous clean-price snapshot under `data\snapshots\prices`, clean write to `data\clean\prices.parquet`, and compatibility write to `data\validated\prices\prices_daily.parquet`.
- Wired the Renew Data local file picker to commit only after validation succeeds, then refresh the app snapshot.
- Expanded the Backtests page to display walk-forward periods, trade counts, average trade size, annualised turnover, worst 12-month return, quality label, diagnostic notes and recent signal/execution trade dates.
- Replaced deprecated Flet `ElevatedButton` usage on the Dashboard and Audit pages with `ft.Button`.
- Browser verification of the rebuilt packaged app found the Renew Data dialog crashed with `FilePicker.__init__() got an unexpected keyword argument 'on_result'`.
- Fixed the Renew Data file picker for Flet 0.85 by using async `pick_files()` and adding support for browser-mode uploaded file bytes.
- Rebuilt the package again after the FilePicker fix.
- Re-tested the packaged app visually: Dashboard rendered, Backtests rendered, Renew Data dialog opened, dry-run branch displayed blocked validation status and no-provider API branch displayed the safe provider message.
- Added price-import rollback support. The data layer restores the newest timestamped `previous` price snapshot, snapshots the currently active price store before replacement, writes both clean and compatibility price Parquet files, and records rollback metadata.
- Added `Rollback last prices` to the Renew Data dialog and wired it through app state with a snapshot refresh after successful rollback.
- Fixed rollback candidate selection to sort timestamped snapshot filenames instead of copied-file modification times.
- Rebuilt the packaged app after adding the rollback UI.
- Launched the rebuilt packaged executable, confirmed `http://127.0.0.1:8550/` returned HTTP 200, and visually verified the Renew Data dialog shows `Rollback last prices`.
- Pressed `Rollback last prices` in the packaged UI with no price snapshots present and confirmed it displayed the safe message: `No previous clean price snapshot is available to roll back.`
- Added `portfolio\risk_analytics.py` with deterministic exposure-limit reporting, adjusted-return correlation matrix calculation and drawdown contribution calculation.
- Added `asset_class` to allocation rows so the Risk page can display asset-class exposure.
- Added a dedicated `/risk` route and Risk page showing risk-gate status, limit breaches, asset-class/region/currency/sector/theme exposure, correlation matrix and drawdown contribution.
- Added `tests\test_risk_analytics.py` covering route registration, WORLD_CORE concentration breach, correlation matrix shape/diagonal and drawdown contribution risk-share accounting.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_backtest_costs.py -q` -> 2 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 10 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 11 passed after adding the import commit regression.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 13 passed after adding rollback regressions.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 30 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 31 passed after the FilePicker regression check.
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 33 passed after rollback.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Ran package verification:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
  - Packaged HTTP check -> `HTTP 200 3775`.
  - Packaged browser check -> rollback action visible and safe no-snapshot message rendered.
- Ran Risk page source verification:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_risk_analytics.py -q` -> 4 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 37 passed.
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app after adding the Risk page.
- Launched the rebuilt executable, confirmed `http://127.0.0.1:8550/` returned HTTP 200, opened `/risk` in the browser, and visually verified the Risk page rendered with limit breaches and the Risk Limits table.
- Added `src\etf_cockpit\data\manual_notes.py` for manual thesis/news ingestion. It validates dated note text, normalises note fields, forces `executable_authority=false`, stores immutable raw copies, writes `data\clean\manual_news.parquet`, snapshots prior clean notes and writes import metadata.
- Wired manual news imports through `DataService.import_local_file(..., dataset_type="manual_news")`, including validation errors for missing dated evidence and success messages that state non-executable authority.
- Updated the Renew Data dialog to expose separate `Import prices` and `Import manual notes` actions.
- Updated Data & Models to show manual thesis/news status in a first-viewport right-side evidence stack with model availability, provenance and validation issues.
- Updated ChatGPT audit export so `06_recent_news_events.md` and `combined_review_packet.md` include imported manual thesis/news notes instead of a placeholder.
- Added regression tests for manual-news import commit, forced non-executable authority, invalid missing-date rejection and audit ZIP inclusion.
- Found during packaged visual QA that the first Data & Models layout placed the manual-note panel below a Flet scroll area that was difficult to reach in the packaged canvas renderer. Refactored the page to a two-column layout so the manual-note panel is visible without scrolling on desktop.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 16 passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 40 tests passed.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 40 tests collected.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app after manual-news and Data page changes:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified the rebuilt packaged UI: dashboard rendered, Renew Data dialog showed `Import manual notes`, safe API branch displayed no-provider text, and Data & Models showed Manual Thesis / News Notes in the first viewport.
- Checked packaged logs after the browser pass. `stdout.log` and `stderr.log` were empty; `startup.log` recorded normal local web startup.
- Stopped the temporary packaged verification process after testing.
- Added a non-executable manual trade proposal report workflow in `src\etf_cockpit\portfolio\proposals.py`.
- Wired the Dashboard `Create trade proposal` button through `AppState.create_trade_proposal()` so it writes a dated JSON report instead of attempting broker execution.
- The report blocks proposal creation when data quality or risk gates require manual review, preserves `executable_authority=false`, records `broker_execution=not_supported`, and summarises blocked/no-trade rows.
- Added regression tests for blocked data-quality reports and filtering of surviving advisory candidate signals.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_trade_proposals.py tests\test_flet_startup.py tests\test_release_hardening.py -q` -> passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 58 collected tests passed.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app after the trade-proposal workflow:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Browser-verified the packaged Dashboard trade-proposal button. With the sample risk gates blocking trading, the UI reported that no manual trade proposal was created and wrote a blocked advisory report.
- Inspected the generated report and proposal log. The report was `blocked`, contained no proposals, set `executable_authority=false`, set `broker_execution=not_supported`, and included blocked summaries for all seven sample ETFs.
- Found a packaging-root issue during proposal verification: direct packaged runs resolved the project root inside `build\flet_dist\ETF_AI_Cockpit\_internal`, so reports/logs could be written under `_internal` instead of the visible project `data` and `logs` folders.
- Updated `src\etf_cockpit\core\paths.py` so a valid `ETF_COCKPIT_ROOT` environment variable wins first, then a valid current working directory, then bundled file-parent discovery.
- Updated `ETF_AI_Cockpit.bat`, `Run_ETF_AI_Cockpit_EXE.bat` and the generated portable launcher in `scripts\build_windows.bat` to set `ETF_COCKPIT_ROOT` to the launcher folder.
- Added `tests\test_paths.py` to prove visible project roots win over bundled `_internal` configs and invalid environment roots are ignored.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_paths.py tests\test_trade_proposals.py tests\test_flet_startup.py tests\test_release_hardening.py -q` -> passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Source smoke first failed because the ad hoc verification command used `snapshot.backtests` instead of the actual `snapshot.backtest` attribute. Reran the corrected command successfully.
- Corrected source smoke:
  - `.\.venv\Scripts\python.exe -c "from etf_cockpit.services import build_snapshot; ..."` -> root/data/logs resolved to the visible project folder and `snapshot_ok as_of=2026-06-26 signals=7 backtests=5 trading_allowed=False`.
- Rebuilt the packaged app after the package-root fix:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and `build\ETF_AI_Cockpit_Portable_v0.1.0`.
  - PyInstaller still emitted the known optional `scipy.special._cdflib` hidden-import warning.
- Launched the rebuilt executable from the visible project root with `ETF_COCKPIT_ROOT` set to the project folder and `ETF_COCKPIT_OPEN_BROWSER=0`.
- HTTP readiness check passed: `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified the packaged Dashboard with the in-app browser: first viewport rendered, console error/warn log was empty, and `Create trade proposal` was visible.
- Clicked `Create trade proposal` in the packaged UI. The visible confirmation message reported the project-root path `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\data\reports\trade_proposal_20260628T011529Z.json`.
- Inspected the generated JSON report. It had `status=blocked`, `executable_authority=false`, `broker_execution=not_supported`, no proposals, and blocked/manual-review summaries for all seven sample ETFs.
- Confirmed no new `_internal\data\reports` trade-proposal reports were created after the root fix.
- Confirmed `logs\trade_proposals.jsonl` recorded the visible project report path, and `logs\startup.log` recorded the current packaged startup from the visible project folder.
- Checked `logs\stderr.log`; it contains a stale 2026-06-27 port-binding traceback from an earlier overlapping launch, but its timestamp did not change during this verification. The current 2026-06-28 packaged run had clean browser console output and a successful startup log.
- Stopped the temporary packaged process `27028`; port 8550 was free afterwards.
- Verified the regenerated portable launcher `build\ETF_AI_Cockpit_Portable_v0.1.0\ETF_AI_Cockpit.bat` also sets `ETF_COCKPIT_ROOT=%CD%`.
- Added explicit cross-currency holdings validation in `src\etf_cockpit\data\validation.py`.
- Non-base-currency holdings now require a dated FX rate into the configured base currency before market values can reconcile. Missing rates block trading with `missing_fx_rate`; stale rates block with `stale_fx_rate`; warning-tier rates produce `stale_fx_rate_warning`.
- Updated the service validation flow to pass the clean FX store from `data\clean\fx.parquet` into holdings validation.
- Added release-hardening tests for a USD holding with no FX, a USD holding reconciled by a dated USD/EUR rate, and a stale USD/EUR rate.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe -c "from etf_cockpit.services import build_snapshot; ..."` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5 trading_allowed=False issues=2`.
- Rebuilt the package after provider Settings persistence:
  - `cmd /c scripts\build_windows.bat` -> success; rebuilt executable and portable folder.
  - PyInstaller still emitted the known optional `scipy.special._cdflib` hidden-import warning.
- Launched the rebuilt package; HTTP readiness returned `HTTP 200` with content length `3775`.
- Browser-verified `/settings`: first viewport rendered, then the Data Providers section rendered editable Provider/Base URL/API key fields with Save buttons and the note that API keys are saved only in local `.env`.
- Packaged browser console logs were empty. `logs\stderr.log` timestamp remained the stale 11:19 value and did not change during this verification.
- Stopped the package process and confirmed port 8550 was free.
- Rebuilt the package after the duplicate-launch guard:
  - `cmd /c scripts\build_windows.bat` -> success; rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
  - PyInstaller still emitted the known optional `scipy.special._cdflib` hidden-import warning.
- Verified the rebuilt executable timestamp was current (`2026-06-28 11:32:33`) and size changed, indicating the new startup guard was packaged.
- Launched the rebuilt package from the visible project root. Readiness returned `HTTP 200` with content length `3775`.
- Launched a second packaged process while the first was running. The second process exited within the test timeout, `startup.log` recorded `existing local web server detected ... reusing it`, and `logs\stderr.log` timestamp did not change.
- Browser-verified the final running package: Dashboard rendered normally and browser error/warn logs were empty.
- Stopped the remaining packaged process and confirmed port 8550 was free.
- Added editable provider settings support. `load_config()` now applies `.env` overrides for provider name, base URL and API key; `save_provider_settings()` writes provider/base URL to `configs\data_providers.yaml` and writes non-empty API keys only to ignored local `.env`.
- Updated `AppState.save_provider_settings()` and the Settings page so each provider row has editable Provider, Base URL and API key fields plus a Save button. Saved API key fields are cleared from the UI after writing.
- Added tests proving provider environment overrides load and redact secrets, and that saving provider settings keeps API keys out of YAML while writing them to `.env`.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py tests\test_flet_startup.py -q` -> passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe -c "from etf_cockpit.services import build_snapshot; ..."` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5 trading_allowed=False issues=2`.
- First package rebuild after the FX validation change failed inside PyInstaller `COLLECT` because a stale packaged `ETF_AI_Cockpit.exe` process still owned port 8550 and locked files under `build\flet_dist\ETF_AI_Cockpit\_internal`.
- Identified the stale process with `Get-NetTCPConnection -LocalPort 8550` and `Get-Process -Name ETF_AI_Cockpit`; stopped PID `90928`, confirmed port 8550 was free, and rebuilt again.
- Second package rebuild after stopping the stale process completed successfully and produced a current executable timestamp.
- Launched the rebuilt package with `ETF_COCKPIT_ROOT` set to the visible project folder; HTTP readiness returned `HTTP 200` and the in-app browser rendered the Dashboard with no console warnings/errors.
- Checked packaged logs. `logs\stderr.log` contained only the earlier duplicate-port traceback from 11:19; the successful 11:25 run appended to `startup.log` and did not modify stderr.
- Added duplicate-server protection to `src\etf_cockpit\app\flet_app.py`. Web-mode startup now checks whether `127.0.0.1:<port>` is already listening and HTTP-ready; if so, it reuses the existing server and optionally opens the browser instead of trying to bind the port again.
- Updated `ETF_AI_Cockpit.bat`, `Run_ETF_AI_Cockpit_EXE.bat` and the generated portable launcher template to check the local URL before starting a second process.
- Added startup regression tests for reusing a ready local server, allowing startup when the port is free, and blocking a duplicate bind when the port is busy but not HTTP-ready.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_release_hardening.py -q` -> passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> passed.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe -c "from etf_cockpit.services import build_snapshot; ..."` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5 trading_allowed=False issues=2`.

### Local LLM Audit Commentary

- Added `configs\local_llm.yaml` with the optional LM Studio base URL `http://localhost:1234/v1`, timeout and token settings.
- Added `src\etf_cockpit\audit\local_llm.py` with local LLM status checks, deterministic audit-context construction, strict commentary schema validation, OpenAI-compatible chat-completions call, and report saving under `data\reports`.
- Added an Audit page `Local LLM audit commentary` panel with `Check local LLM` and `Generate local commentary` buttons. The workflow is manual only and cannot alter signals, scores or gates.
- Added tests for disabled no-network behaviour, model discovery, safe unavailable messages, schema rejection of `executable_authority=true`, valid commentary parsing and deterministic snapshot context construction.
- The first ad hoc local LLM status probe failed due shell quoting, and the second failed because raw Python was run without `PYTHONPATH=src`; reran with `PYTHONPATH=src` and confirmed the client returned safe `unavailable` status because LM Studio was not listening on `localhost:1234`.
- Shortened the unavailable local LLM UI message so it no longer displays raw Requests connection details.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_local_llm_audit.py tests\test_release_hardening.py tests\test_risk_analytics.py -q` -> 33 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_local_llm_audit.py tests\test_release_hardening.py tests\test_risk_analytics.py -q` -> 34 passed after the safe-message regression.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 56 collected tests passed.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only | Select-Object -Last 1` -> 56 tests collected.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Ran local LM Studio status probe:
  - `PYTHONPATH=src; .\.venv\Scripts\python.exe -c "...check_local_llm_status..."` -> `unavailable||Local LLM endpoint unavailable. Start the LM Studio local server or leave this optional workflow unused.`
- Rebuilt the packaged app after local LLM changes:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified direct `http://127.0.0.1:8550/chatgpt` renders the local LLM audit panel.
- Browser-clicked `Check local LLM` in the packaged UI and confirmed it displays the concise optional-unavailable message when LM Studio is offline.
- Checked packaged logs after the local LLM browser pass. `stdout.log` and `stderr.log` were empty; `startup.log` recorded normal local web startup.
- Stopped the temporary packaged verification process after testing.
- Changed audit export defaults from the legacy `data\chatgpt_exports\chatgpt_review_YYYY-MM-DD.zip` naming to `data\audit_packets\audit_packet_YYYY-MM-DD.zip`, while keeping the old `CHATGPT_EXPORTS_DIR` variable as a compatibility alias for older scripts/tests.
- Added `AppState.export_audit_packet()` and kept `export_chatgpt_pack()` as a compatibility wrapper.
- Updated visible dashboard and Audit page labels to `Export audit packet`, `Open audit`, `Import external audit response` and `External audit is commentary only`.
- Renamed the `/chatgpt` route title to `Audit` while preserving the URL for compatibility.
- Updated `README.md` and `README_FIRST_RUN.md` to describe external audit packets and non-executable imported commentary.
- Added tests proving audit exports go to `data\audit_packets`, the ZIP is named `audit_packet_*`, and the route label is `Audit`.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py tests\test_risk_analytics.py -q` -> 28 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py tests\test_risk_analytics.py tests\test_flet_startup.py -q` -> 31 passed after the footer text fix.
- Confirmed stale visible label search returned no matches for old `ChatGPT Audit`, `Export ChatGPT pack`, `Export Review Pack`, `Import Review JSON`, `Validate and Import`, `chatgpt_review_` or old footer text in `src`, tests and first-run docs.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 50 collected tests passed.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only | Select-Object -Last 1` -> 50 tests collected.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app after audit-packet UI/path changes:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified the packaged dashboard shows `Export audit packet` and `Open audit`.
- Browser-verified direct `http://127.0.0.1:8550/chatgpt` renders the `Audit` page with `Export audit packet`, `Import external audit response`, `Validate and import`, and footer `External audit is commentary only`.
- Checked packaged logs after the audit browser pass. `stdout.log` and `stderr.log` were empty; `startup.log` recorded normal local web startup.
- Stopped the temporary packaged verification process after testing.
- Added `src\etf_cockpit\data\reference_data.py` for ETF factsheet/reference metadata and underlying ETF holdings imports. It validates dated reference rows, maps ETF IDs from `etf_id`, ISIN or ticker, normalises `weight_percent` holdings to decimal weights, stores immutable raw copies, writes clean Parquet files, snapshots prior clean stores and writes import metadata.
- Wired `DataService.import_local_file()` for `etf_metadata`, `etf_factsheet`, `etf_factsheets` and `etf_holdings` dataset types.
- Updated Renew Data to expose `Import ETF factsheets` and `Import ETF holdings` alongside price and manual-note import actions.
- Updated Data & Models with an `ETF Reference Data` panel showing imported/not-imported state, rows, as-of date, staleness and checksum.
- Updated audit export to include `12_reference_data_inventory.json` and embed the inventory in the combined review packet.
- Added regression tests for ETF factsheet commit/staleness, ETF holdings percent-weight normalisation and snapshots, holdings decimal-weight rejection and stale factsheet block status.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 20 passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 44 tests passed.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 44 tests collected.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app after ETF reference-data import changes:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified the rebuilt packaged UI: Renew Data dialog showed `Import ETF factsheets` and `Import ETF holdings`, and Data & Models showed `ETF Reference Data` with both datasets marked not imported.
- Checked packaged logs after the reference-data browser pass. `stdout.log` and `stderr.log` were empty; `startup.log` recorded normal local web startup.
- Stopped the temporary packaged verification process after testing.
- Added `src\etf_cockpit\data\fx_data.py` for dated FX rate imports. It validates explicit currency pairs or base/quote currency columns, positive numeric rates, duplicate date/pair rows, and daily-freshness status.
- Wired `DataService.import_local_file(..., dataset_type="fx")` to validate and commit FX imports through raw, clean, snapshot and metadata layers.
- Updated Renew Data with `Import FX rates`.
- Updated Data & Models so the `ETF Reference Data` inventory panel also shows FX presence, pairs, as-of date, staleness and checksum.
- Updated audit export to include `13_fx_inventory.json` and embed it in the combined review packet.
- Added regression tests for FX commit/snapshots/metadata, invalid currency-pair rejection and audit ZIP inclusion.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` -> 22 passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 46 tests passed.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 46 tests collected.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app after FX import changes:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified the rebuilt packaged UI: Renew Data dialog showed `Import FX rates`, and Data & Models showed `fx: not imported` in the first-viewport inventory panel.
- Checked packaged logs after the FX browser pass. `stdout.log` and `stderr.log` were empty; `startup.log` recorded normal local web startup.
- Stopped the temporary packaged verification process after testing.
- Added `underlying_holdings_exposure()` to `portfolio\risk_analytics.py`. It uses the latest imported ETF holdings date per ETF and multiplies constituent weights by current/target ETF portfolio weights.
- Updated the Risk page with an `Underlying Holdings Exposure` section. When no ETF holdings file is imported it shows a clear empty state; when holdings exist it shows portfolio-weighted sector, region and currency exposure from imported holdings.
- Added a regression test proving underlying exposure uses latest holdings rows and portfolio weights.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_risk_analytics.py -q` -> 5 passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> 47 tests passed.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 47 tests collected.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app after Risk page underlying-exposure changes:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified the rebuilt packaged Risk page. The first viewport rendered normally, lower exposure tables were reachable via scroll, and `Underlying Holdings Exposure` showed `No ETF holdings file has been imported yet.` when no clean ETF holdings file exists.
- Checked packaged logs after the Risk page browser pass. `stdout.log` and `stderr.log` were empty; `startup.log` recorded normal local web startup.
- Stopped the temporary packaged verification process after testing.

## 2026-06-28

- Upgraded `src\etf_cockpit\backtest\engine.py` so advanced diagnostics are computed as deterministic local estimates instead of remaining `None`/`not_run` placeholders.
- Added local estimates for probabilistic Sharpe, deflated Sharpe, a CSCV-style PBO proxy and parameter sensitivity based on period stability plus a 2x transaction-cost stress.
- Updated `src\etf_cockpit\app\pages\backtests.py` so the Backtests page states that advanced diagnostics are local deterministic estimates, not proof of future performance.
- Added `test_backtest_advanced_diagnostics_are_estimated()` to prove the advanced diagnostics are populated and bounded.
- Found that direct packaged startup at `/backtests` could render a blank Flet shell even though in-app navigation worked.
- Removed the startup redirect from non-default routes back to `/` in `src\etf_cockpit\app\flet_app.py` so refresh/deep-link startup preserves the requested page.
- Added a Flet startup regression test proving an initial `/backtests` route renders and does not call `page.go("/")`.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_backtest_costs.py -q` -> 3 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_backtest_costs.py -q` -> 6 passed.
- Ran full tests:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` -> all 49 collected tests passed.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only | Select-Object -Last 1` -> 49 tests collected.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Rebuilt the packaged app:
  - `cmd /c scripts\build_windows.bat` -> rebuilt `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and portable folder.
  - PyInstaller still emitted the known optional `scipy.special._cdflib` hidden-import warning.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200` with content length `3775`.
- Browser-verified the rebuilt package with system Chrome/Playwright:
  - Direct `http://127.0.0.1:8550/backtests` rendered the Backtests page rather than a blank shell.
  - Backtest diagnostics displayed quality `Medium`, probabilistic Sharpe `0.74`, deflated Sharpe `-0.19`, PBO probability `0.33` and parameter sensitivity `mixed`.
  - Root dashboard rendered normally and showed the blocked/manual-review sample state.
- Checked packaged logs after the browser pass. `stdout.log` and `stderr.log` were empty; `startup.log` recorded normal local web startup.
- Stopped the temporary packaged verification process after testing.

## 2026-06-30

- Re-read the active Codex goal objective file and confirmed the project-specific `AGENTS.md` rules before changing model files.
- Inspected root model ZIPs:
  - `timesfm-2.0.1.zip`, SHA256 `F7B3D68FA48FF675CD9384623EFC8DBED75E41A2C3C1A46B0398E964E3A94DB9`.
  - `toto-toto-models-v1.0.0.zip`, SHA256 `C06EA169D7A9A05A2685D4A0570A887C5472A2D2AB6C34E2A7BCC9BB4F7237B5`.
- Checked both ZIP file lists for checkpoint-like files (`safetensors`, `.bin`, `.pt`, `.pth`, `.ckpt`, checkpoint/weights/model config names). Both counts were zero, so these archives are source/reference material, not installed model weights.
- Probed LM Studio at `http://localhost:1234/v1/models`; endpoint returned seven model IDs: `qwen3.6-27b`, `qwen3.6-35b-a3b`, `qwen3.6-35b-a3b-text@q5_k_s`, `qwen3.6-35b-a3b-text@q4_k_s`, `qwen3.6-27b-text`, `qwen3.5-4b` and `text-embedding-nomic-embed-text-v1.5`.
- Copied the original ZIP files into `models\source_archives` while leaving the root originals in place.
- Added `models\source_archives\MODEL_ARCHIVE_MANIFEST.md` and updated `models\source_archives\README.md` to document checksums, extracted folders and the fact that no runtime checkpoints were found.
- Verified copied archive hashes match the root originals.
- Verified app-level local LLM status through `check_local_llm_status()`:
  - `status=ok`
  - `base_url=http://localhost:1234/v1`
  - `model=qwen3.6-27b`
- Verified app-level model availability stays conservative:
  - `baseline=True`
  - `timesfm=False`
  - `toto=False`
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_local_llm_audit.py tests\test_model_shapes.py -q` -> 9 passed.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Ran full regression tests:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> passed, exit code 0.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 69 tests collected.

## 2026-06-30

- Used the Hugging Face TimesFM 2.5 Transformers documentation and model cards as implementation references:
  - `https://huggingface.co/docs/transformers/model_doc/timesfm2_5`
  - `https://huggingface.co/google/timesfm-2.5-200m-transformers`
  - `https://huggingface.co/google/timesfm-2.5-200m-pytorch`
- Used the Datadog Toto 2.0 Hugging Face collection and `Toto-2.0-313m` model card as implementation references:
  - `https://huggingface.co/collections/Datadog/toto-20`
  - `https://huggingface.co/Datadog/Toto-2.0-313m`
- Confirmed Toto 2.0 collection repo IDs from the Hugging Face collection API: `Datadog/Toto-2.0-4m`, `Datadog/Toto-2.0-22m`, `Datadog/Toto-2.0-313m`, `Datadog/Toto-2.0-1B`, `Datadog/Toto-2.0-2.5B`.
- Extended `ModelRuntimeConfig` with Hugging Face runtime fields: `backend`, `hf_repo_id`, `hf_repo_ids`, `local_files_only`, `allow_remote_download`, `decode_block_size` and `torch_compile`.
- Updated `configs\model_settings.yaml`:
  - TimesFM defaults to backend `transformers`, repo `google/timesfm-2.5-200m-transformers`, local path `models/timesfm/timesfm-2.5-200m-transformers`, `local_files_only=true` and `allow_remote_download=false`.
  - Toto defaults to backend `toto2`, size `313m`, repo `Datadog/Toto-2.0-313m`, all five Datadog repo IDs, `local_files_only=true` and `allow_remote_download=false`.
- Reworked `TimesFMAdapter`:
  - Supports Hugging Face Transformers `TimesFm2_5ModelForPrediction.from_pretrained(...)`.
  - Supports the official TimesFM PyTorch package backend as a secondary path.
  - Requires local weight-like files before live availability is true unless explicit remote download is enabled.
  - Converts TimesFM forecast levels into log-return forecasts versus the latest adjusted price.
  - Returns null forecasts and score-disallowed metadata on unavailable/failed model states.
- Reworked `TotoAdapter`:
  - Uses `from toto2 import Toto2Model` runtime semantics from the Datadog model card.
  - Builds a multivariate adjusted-log-return tensor with explicit missing-value masks, rather than forward-filling.
  - Calls `model.forecast(...)` with `target`, `target_mask`, `series_ids`, `horizon`, `decode_block_size` and `has_missing_values`.
  - Converts output quantiles shaped `(9, batch, n_variates, horizon)` into cumulative horizon log-return evidence.
  - Requires local weight-like files before live availability is true unless explicit remote download is enabled.
- Updated model folder READMEs and archive manifest with exact Hugging Face repo references and runtime-folder expectations.
- Added model regression tests for:
  - Toto availability requiring both runtime package symbol and weight-like files.
  - Empty runtime folder rejection.
  - TimesFM level-to-log-return conversion.
  - Toto daily-return-quantile accumulation.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_model_shapes.py -q` -> 6 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_model_shapes.py tests\test_release_hardening.py::test_unavailable_models_are_not_allowed_in_score -q` -> 7 passed.
- Verified config/model status:
  - `load_config().models.runtime(...)` loads the expanded TimesFM/Toto fields.
  - `model_availability(load_config())` -> `{'baseline': True, 'timesfm': False, 'toto': False}` because no real local checkpoint weights are installed.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Ran full regression tests:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> passed, exit code 0.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 72 tests collected.
- Rebuilt the packaged app after adapter/config changes:
  - First `cmd /c scripts\build_windows.bat` run hit locked files in `build\flet_dist\ETF_AI_Cockpit` because old packaged PID `91120` was still running on port 8550.
  - Stopped only the project packaged process `ETF_AI_Cockpit.exe` PID `91120`; port 8550 became free.
  - Reran `cmd /c scripts\build_windows.bat` -> build completed and portable folder was refreshed.
  - PyInstaller still emitted the known optional hidden import warning for `scipy.special._cdflib`.
- Launched the rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0` and `ETF_COCKPIT_ROOT` set to the project folder; `http://127.0.0.1:8550/` returned `HTTP 200 length=3775`.
- Verified rebuilt executable timestamp: `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` last write `2026-06-30 13:12:27`, size `21585824`.
- Checked packaged logs after verification: `startup.log` updated for the current launch, `stdout.log` remained empty, `stderr.log` last write stayed `2026-06-28 11:19:08` and therefore only contains stale historical output.
- Stopped the temporary packaged verification process and confirmed port 8550 was free.

## 2026-06-30

- Read the user-supplied Yahoo ticker note for Tradegate/DEGIRO candidates. The candidate list includes ETFs and individual EUR-denominated European stocks, so it should not be blindly committed into the existing ETF-only universe.
- Installed `yfinance==1.5.1` into the project virtual environment and added `yfinance>=1.5` to `requirements.txt` and `pyproject.toml`.
- Added `src\etf_cockpit\data\yfinance_provider.py`:
  - Fetches Yahoo Finance daily OHLCV rows with `auto_adjust=false`.
  - Uses Yahoo `Adj Close` as `adjusted_close` when present.
  - Normalises output to the cockpit price schema with EUR currency metadata.
  - Supports `ProviderSection.symbols_map` for mapping cockpit IDs to Yahoo tickers.
  - Leaves FX/factsheet/ETF-holdings workflows to ECB/manual issuer imports.
- Updated `DataService.api_update_status()` so configured `prices.active_provider=yfinance` fetches, validates and commits configured symbols only when a `symbols_map` is present.
- Added `data\raw\trade_candidates\yahoo_trade_candidates_2026-06-30.csv` with the user-supplied trade candidates and Yahoo tickers. Veolia is recorded with 8 shares and an ambiguity note for `8 or 7`.
- Added `scripts\analyze_yfinance_candidates.py`:
  - Fetches 5 years of Yahoo data for the candidate list.
  - Computes price-only technical evidence: 1w/1m/3m/6m/12m returns, 20d/60d annualised volatility, current/12m drawdown, 52-week distance, SMA50/SMA200 flags, volume/turnover and trade value.
  - Writes CSV, JSON and Markdown reports under `data\reports`.
  - Produces only advisory statuses (`add_candidate`, `watchlist`, `no_trade`, `manual_review`) and explicitly does not authorise trades.
- Added `tests\test_yfinance_provider.py` for yfinance schema normalisation and adjusted-close handling.
- Ran focused tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_yfinance_provider.py tests\test_release_hardening.py::test_no_provider_api_update_returns_safe_message -q` -> 2 passed.
- Ran live yfinance candidate analysis:
  - `.\.venv\Scripts\python.exe scripts\analyze_yfinance_candidates.py` -> downloaded 15,311 rows for 12 instruments and wrote:
    - `data\reports\yfinance_trade_candidate_analysis_20260630T053445Z.csv`
    - `data\reports\yfinance_trade_candidate_analysis_20260630T053445Z.json`
    - `data\reports\yfinance_trade_candidate_analysis_20260630T053445Z.md`
- Candidate analysis output:
  - `add_candidate`: ENX, EXX1, LR, NEX, PRY, SPYK, SU, SXRJ, UCG, VIE.
  - `watchlist`: DB1.
  - `no_trade`: SGO.
  - Important flags include below-SMA50 for ENX/LR/NEX/SXRJ/DB1, high 60d volatility for PRY, ambiguous Veolia share count and below-SMA200/negative 6m/12m evidence for SGO.
- Ran source smoke:
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke` -> `snapshot_ok as_of=2026-06-26 signals=7 backtests=5`.
- Ran full regression tests:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> passed, exit code 0.
  - `.\.venv\Scripts\python.exe -m pytest --collect-only` -> 73 tests collected.
- Updated `scripts\build_windows.bat` to include yfinance-related hidden imports for the packaged executable.
- Rebuilt the packaged app:
  - `cmd /c scripts\build_windows.bat` -> build completed, with known optional hidden-import warnings for `pycparser.lextab`, `pycparser.yacctab` and `scipy.special._cdflib`.
- Launched rebuilt packaged executable with `ETF_COCKPIT_OPEN_BROWSER=0`; `http://127.0.0.1:8550/` returned `HTTP 200 length=3775`.
- Verified package timestamp: `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` last write `2026-06-30 15:37:31`, size `22981747`.
- Checked logs after packaged smoke: `startup.log` updated, `stdout.log` empty, `stderr.log` last write stayed `2026-06-28 11:19:08`.
- Stopped the temporary packaged verification process and confirmed port 8550 was free.

## 2026-06-30

- Located the uploaded safetensors and moved them into runtime checkpoint folders instead of leaving them at the app root:
  - TimesFM 2.5: `models\timesfm\timesfm-2.5-200m-transformers\model.safetensors`
  - Toto 2.0 4M: `models\toto\Toto-2.0-4m\model.safetensors`
  - Toto 2.0 1B: `models\toto\Toto-2.0-1B\model.safetensors`
- Added minimal local `config.json` files beside the model weights and updated `configs\model_settings.yaml` so TimesFM uses backend `transformers` and Toto uses the 4M checkpoint by default.
- Repaired the broken `.venv`: the existing environment was preserved under `backups\venv_broken_20260630_160456`, then a clean Python 3.13 environment was created.
- Installed base, dev and optional model dependencies, including `torch`, `safetensors`, `transformers`, local editable `timesfm`, local editable `toto2` and `flet-web`.
- Added `requirements-models.txt` and updated runtime/package metadata so the optional model environment can be recreated.
- Found the uploaded TimesFM checkpoint used legacy `model.layers.*.mlp.ff0/ff1` tensor names while the installed Transformers TimesFM class expected `fc1/fc2` names.
- Preserved the original TimesFM checkpoint as `model.original_ff_keys.safetensors` and wrote the converted runtime `model.safetensors`; conversion renamed 40 tensors across 272 total tensors.
- Added `src\etf_cockpit\models\local_weights.py` to inspect local safetensors headers, count tensors, detect config presence and report local model readiness without loading heavy models.
- Wired local model diagnostics into the model registry, app snapshot service and Data & Models UI.
- Hardened Toto live input handling by trimming context rows to a complete configured patch size instead of failing on non-divisible histories.
- Hardened TimesFM live input handling by trimming context to complete patches and avoiding `device_map='auto'` on CPU unless `accelerate` is installed.
- Updated model README files and main first-run docs to describe installed safetensors, the live-ready 4M default and the Python-first launcher path.
- Updated `.gitignore` so large model weights stay out of source control while model folder configs remain visible.
- Updated `scripts\build_windows.bat` so safetensors are not bundled into the PyInstaller/Flet package, while `flet_web` assets and hidden imports are included.
- First packaged EXE readiness check after the model runtime build failed because `flet_web` was missing from the packaged/runtime environment. Installed `flet-web`, restored the add-data/hidden-import entries and rebuilt.
- Final rebuild completed and refreshed `build\flet_dist` plus `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Verified no root-level `.safetensors` files remain and no safetensors were copied into `build\flet_dist` or the portable build folder.
- Verified local model inventory:
  - TimesFM 2.5: `live_ready`, 1 runtime weight file, 0.93 GB, 272 tensors.
  - Toto 2.0 4M: `live_ready`, 1 runtime weight file, 0.02 GB, 48 tensors.
  - Toto 2.0 1B: installed, 4.16 GB, 336 tensors, not enabled by default.
- Ran live local model smoke checks:
  - TimesFM 2.5 returned `status=ok` for a 5-day forecast.
  - Toto 2.0 4M returned `status=ok` for a 5-day forecast.
- Ran full regression tests, source smoke, packaged EXE HTTP readiness and in-app browser visual QA.
- Browser QA confirmed the dashboard is not blank, Data & Models shows `Local Model Files`, the Renew data modal opens, and the no-provider API branch displays the safe message.
- Stopped the temporary test server and confirmed the test process ended.
- Read back the edited README/first-run/model docs and reran source smoke after documentation updates.

## 2026-06-30

- Switched active Toto config from 4M to 1B:
  - `model_size: 1b`
  - `hf_repo_id: Datadog/Toto-2.0-1B`
  - `model_path: models/toto/Toto-2.0-1B`
- Verified model inventory now reports Toto 1B as `live_ready`; Toto 4M remains installed but not enabled.
- Found the current Python runtime had CPU-only Torch despite the system exposing an RTX 5070 Laptop GPU through `nvidia-smi`.
- Installed CUDA PyTorch `torch==2.12.1+cu130` from the PyTorch CUDA 13.0 wheel index.
- Resolved dependency metadata conflicts by upgrading `lightning` and `pytorch-lightning` to `2.6.5`.
- Updated `requirements-models.txt` so future model-runtime installs use the CUDA 13.0 Torch wheel and compatible Lightning versions.
- Verified `torch.cuda.is_available()` is true and Python sees `NVIDIA GeForce RTX 5070 Laptop GPU`.
- Ran Toto 1B GPU smoke:
  - status `ok`
  - model version `toto_2_0_1b`
  - VRAM during smoke around 4180 MB allocated and 4334 MB reserved.
- Found `ForecastService` was still baseline-only despite live adapters being available. Fixed it to run baseline, TimesFM and Toto rows and write forecast CSV outputs.
- Added `scripts\run_forecasts.py` for full ETF-universe forecasts.
- Added `scripts\run_yfinance_candidate_forecasts.py` for full model forecasts on the yfinance stock/ETF candidate list.
- Found TimesFM 2.5 Transformers returns only 128 steps because the checkpoint config has `horizon_length: 128`. Changed over-limit horizons to explicit `skipped` rows rather than hard failures.
- Found Toto candidate forecasts failed on a 1279-row panel because an all-NaN first return row was dropped after patch trimming. Fixed by dropping all-missing return rows before patch trimming.
- Reran yfinance technical candidate analysis and wrote fresh reports under `data\reports`.
- Reran full ETF forecasts and yfinance candidate forecasts on CUDA runtime.
- Ensured the forecast-service regression test writes to a temp path so it no longer overwrites real forecast artefacts.
- Final checks passed: full pytest suite, source app smoke, `pip check`, CUDA visibility, model availability and forecast output counts.

## 2026-06-30

- Updated the product emphasis from a portfolio-rebalance cockpit to a local evidence cockpit for analysing ETFs, stocks and candidate instruments.
- Added `src\etf_cockpit\models\forecast_scores.py` to load latest forecast CSVs and convert valid baseline, Toto and TimesFM expected-return rows into bounded score inputs.
- Wired forecast component maps into `SignalService`, `build_snapshot()` and `generate_signals()`.
- Changed target-policy, current-concentration and cash-minimum findings from hard blocks to warnings/context. Data-quality failures remain hard blockers.
- Removed concentration penalty from the instrument score so an intentionally large holding does not suppress model/algorithm evidence.
- Rewrote visible Flet UI text across the shell, Overview, Scores, Instrument Detail, Portfolio Context, Risk Evidence, Data & Models, Settings, Backtests, Audit Notes and Diagnostics pages.
- Added compact evidence tables and score-derived wording so the UI shows algorithm/model components instead of hiding everything behind `manual_review`.
- Added latest yfinance candidate stocks/ETFs to the Scores page, including technical rating plus baseline/Toto/TimesFM model components.
- Added CUDA/GPU visibility to Diagnostics.
- Added a responsive shell: mobile/narrow view uses top navigation and stacked Overview cards instead of a fixed sidebar.
- Fixed rendered table overlap found in browser QA by reducing wide table columns into compact `Score`, `Models`, `Explanation` and `Context` columns.
- Fixed missing candidate flags showing as `nan`; empty flags now show `-`.
- Browser QA on `http://127.0.0.1:8551/` verified:
  - Overview renders updated AI Evidence Cockpit UI.
  - Scores page renders configured universe and candidate evidence.
  - Renew local data dialog opens and dry-run validation reports `Analysis hard block: False`.
  - Mobile viewport uses top navigation and stacked cards.
  - Browser error/warn logs were empty.
- Saved QA screenshots outside the repo under `C:\Users\thor2\AppData\Local\Temp\etf-cockpit-ui-qa`.

## 2026-06-30

- Rebuilt the Windows package after the UI/scoring changes.
- The first rebuild failed because stale PID `52492` (`build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`) locked the previous build output.
- Stopped only that project-specific packaged process and confirmed no other cockpit process remained.
- Updated `scripts\build_windows.bat`:
  - exits when `build\flet_dist` cannot be removed;
  - exits when Flet/PyInstaller native pack fails;
  - copies successful native onedir output into the portable folder under `native\ETF_AI_Cockpit`;
  - creates `Run_ETF_AI_Cockpit_EXE.bat` for the native exe path.
- Reran `cmd /c scripts\build_windows.bat`; build completed and refreshed `build\flet_dist` plus `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Verified portable source smoke with the rebuilt portable folder: `snapshot_ok as_of=2026-06-30 signals=7 backtests=5`.
- Verified native package smoke by launching `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` on port 8562 with browser opening disabled; HTTP readiness returned 200 and the process was stopped.
- Updated the root and portable native-exe helper batch files so direct exe launches set `ETF_COCKPIT_ROOT`, browser/web mode and readiness checks explicitly.

## 2026-07-01

- Extended `src\etf_cockpit\data\yfinance_provider.py` so yfinance can provide:
  - adjusted OHLCV prices;
  - dividends, stock splits and capital-gains action columns when Yahoo exposes them;
  - FX pairs through Yahoo `=X` tickers;
  - ETF/fund metadata through `Ticker.info`, `fast_info` and `funds_data`;
  - top holdings through `Ticker.funds_data.top_holdings` when available.
- Updated `configs\data_providers.yaml` so yfinance is the default provider for prices, FX, ETF metadata and ETF holdings.
- Added explicit Yahoo symbols for the configured ETF universe. Live probe showed `IWDA.DE` fails while `IWDA.AS` and `EUNL.DE` return data, so `WORLD_CORE` is mapped to `IWDA.AS`.
- Updated `DataService.api_update_status()` to run the yfinance refresh/validate/commit path and commit available Yahoo reference datasets.
- Added `scripts\run_yfinance_analysis.py` as the reproducible full yfinance run: fetch, validate, commit, algorithms, TimesFM/Toto/baseline forecasts, backtest and JSON report.
- Added yfinance provider regression tests for action columns, configured symbol mapping, metadata extraction, top-holdings extraction and FX pair extraction.
- Live yfinance run committed:
  - prices: 8,903 rows, 7 instruments, as-of 2026-06-29;
  - metadata: 7 rows;
  - top holdings: 50 rows.
- Live yfinance model run wrote `data\forecasts\forecast_results_yfinance_20260629.csv` and report `data\reports\yfinance_full_analysis_20260701T012624Z.json`.
- Reran yfinance model analysis after fixing an implicit `pct_change` fill warning; report written to `data\reports\yfinance_full_analysis_20260701T012952Z.json`.
- Verified snapshot now reads yfinance prices and yfinance forecast scores.
- Rebuilt the Windows portable package after the yfinance provider/config/script changes.
- Verified rebuilt native exe on temporary port 8563; HTTP readiness returned 200 and the temporary process was stopped.

## 2026-07-01

- Implemented the Simple YFinance Scoring App plan.
- Added `src\etf_cockpit\signals\simple_scores.py`:
  - converts raw `-1..+1` scores into `0..10`;
  - maps final scores to `Strong Buy Candidate`, `Buy Candidate`, `Watch`, `Hold` and `Avoid/Review`;
  - builds merged score rows for configured ETFs and yfinance candidate stocks/ETFs;
  - treats unavailable/invalid model rows as `N/A` and reweights only valid components.
- Added `src\etf_cockpit\data\trade_candidate_analysis.py`:
  - loads `data\raw\trade_candidates\yahoo_trade_candidates_2026-06-30.csv`;
  - fetches candidate yfinance prices;
  - calculates candidate momentum, SMA trend, volatility/drawdown and technical report rows;
  - writes CSV/JSON/Markdown reports under `data\reports`.
- Added app service methods:
  - `AppState.refresh_yfinance_data()`;
  - `AppState.run_algorithm_scores()`;
  - `AppState.run_forecasting_models()`;
  - matching `DataService` methods for candidate analysis and configured/candidate forecasts.
- Replaced the Overview page with the four-step workflow and expandable simple score list.
- Replaced the Scores page with the same `x/10` expandable list and summary cards.
- Updated navigation copy from generic Overview to `Simple Scores`.
- Added `tests\test_simple_scores.py` covering score conversion, decision thresholds, missing model reweighting, candidate scoring without portfolio fields, unavailable model `N/A`, and workflow button visibility.
- Ran live app workflow through `AppState`:
  - refreshed 8,903 yfinance price rows and committed metadata/top-holdings;
  - refreshed 12 candidate algorithm rows, report `data\reports\yfinance_trade_candidate_analysis_20260701T020044Z.csv`;
  - refreshed configured forecasts: baseline ok 35, TimesFM ok 28/skipped 7, Toto ok 35;
  - refreshed candidate forecasts: baseline ok 60, TimesFM ok 48/skipped 12, Toto ok 60.
- Browser QA findings/fixes:
  - first Overview render showed a blank grey content area; fixed Flet `Row(..., wrap=True)` with expanded cards;
  - Scores route showed the same blank grey area; applied the same layout fix;
  - mobile summary cards initially truncated labels; fixed by stacking cards on narrow screens.
- Browser QA verified:
  - Overview renders 19 instruments, 7 configured and 12 candidates;
  - four workflow buttons are visible;
  - top row expands;
  - deterministic component cards render;
  - Baseline, TimesFM and Toto component cards render;
  - Scores route renders;
  - mobile layout renders readable cards/buttons/legend;
  - browser warning/error logs were empty.
- Updated `scripts\build_windows.bat` so portable builds copy current data folders:
  - `data\clean`;
  - `data\forecasts`;
  - `data\reports`;
  - `data\raw\trade_candidates`;
  - plus existing backtest/features/portfolio/validated data.
- Rebuilt the Windows package after the simple scoring UI and data-copy updates.
- Verified final native executable `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` on temporary port 8571:
  - HTTP 200 readiness;
  - rendered 19 instruments and model rows in browser;
  - browser warning/error logs were empty.
## 2026-07-01 Chrome QA and Release Follow-Up

- Verified the configured ETF universe plus candidate CSV resolves to 19 scored instruments:
  - 7 configured ETFs.
  - 12 candidates: SPYK, SXRJ, EXX1, UCG, SU, LR, PRY, NEX, DB1, ENX, VIE, SGO.
- Reproduced the user-visible blank startup in Chrome:
  - Chrome initially loaded the Flutter shell but showed a blank page while the backend built the first snapshot.
  - Cold `scripts/run_app.py --smoke` before optimisation took 34.64 seconds and imported model runtime packages during startup.
- Implemented startup fixes:
  - Changed `models.registry.model_availability()` to use lightweight local inventory/package checks instead of importing live TimesFM/Toto runtimes.
  - Added cached backtest loading in `BacktestService.load_or_run_backtest()`.
  - Startup smoke improved to 1.83-1.93 seconds.
- Ran Chrome user-flow verification:
  - Main screen rendered 19 instruments and 57 valid model/instrument pairs.
  - Expanded score rows showed Momentum, Trend, Risk/volatility, Relative strength, Baseline, TimesFM and Toto x/10 scores and explanations.
  - `1. Refresh yfinance data` refreshed to data date 2026-06-30 and committed 8,910 Yahoo Finance price rows, 7 metadata rows and 50 holdings rows.
  - `2. Run algorithms` refreshed 12 candidate algorithm rows as of 2026-06-30.
  - Initial `3. Run forecasting models` foreground run was too heavy when rerunning current-date candidate forecasts.
  - Added current-date forecast cache reuse and 60-trading-day UI forecast horizon.
  - Rechecked `3. Run forecasting models`: configured and candidate forecasts were reused from current-date cache with visible success message.
  - `4. Show scores` routed to `/signals` and rendered the score list.
- Fixed UI issues found during Chrome QA:
  - Dashboard model count now includes candidate forecasts as well as configured ETF forecasts.
  - Renew/import dialog validation output now scrolls internally.
  - Instrument Detail now uses x/10 evidence/model scores and x/10 summary text.
  - Diagnostics now checks `toto2` instead of legacy `toto`.
  - Local LLM timeout was raised from 12 seconds to 60 seconds for larger LM Studio models.
- Verified secondary pages in Chrome:
  - Portfolio Context, Risk Evidence, Instrument Detail, Backtests, Audit Notes, Data & Models, Settings and Diagnostics all rendered.
  - Audit packet export produced `data/audit_packets/audit_packet_2026-06-30.zip`.
  - LM Studio check button reported reachable local model `qwen3.6-27b`.
  - Generate commentary button previously timed out gracefully at 12 seconds; config/code now allow 60 seconds.
- Rebuilt Windows package with `scripts/build_windows.bat`.
- Smoke-tested rebuilt exe `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` on port 8573; Chrome rendered the 19-row Simple Scores app.

## 2026-07-04 UI Startup QA and Packaging

- Read the project goal objective attachment and confirmed the task remains scoped to the local ETF cockpit.
- Loaded Chrome/browser frontend QA instructions.
- Attempted Chrome extension automation; `agent.browsers.get("extension")` returned `Browser is not available: extension` after the required retry. Chrome-specific visual automation could not be performed in this turn.
- Started the source app on temporary ports and reproduced a web-startup failure:
  - HTTP returned 500.
  - stderr showed `PermissionError: [Errno 13] Permission denied` while Flet copied `index.html` into a temp web directory.
- Added runtime startup hardening:
  - `src/etf_cockpit/core/runtime.py` creates project-local runtime cache/temp folders.
  - `src/etf_cockpit/app/flet_app.py` patches Flet static web temp creation to a deterministic writable project folder.
  - `scripts/run_app.py` and `src/etf_cockpit/main.py` configure the runtime environment before Flet starts.
- Added regression coverage:
  - `tests/test_flet_startup.py::test_flet_static_temp_dir_is_writable`.
- Fixed local test infrastructure for locked Windows temp folders:
  - disabled pytest cache provider in `pyproject.toml`;
  - added a compact project-local `tmp_path` fixture in `tests/conftest.py`;
  - ignored generated runtime/test temp folders in `.gitignore`.
- Verified source app startup after fix:
  - source app on port 8587 returned HTTP 200;
  - stderr was empty;
  - `logs/startup.log` confirmed the patched Flet static temp path.
- Ran full regression suite:
  - `.\.venv\Scripts\python.exe -m pytest tests -q` passed.
- Rebuilt package:
  - `.\scripts\build_windows.bat` completed and refreshed `build\flet_dist` plus `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Smoke-tested rebuilt exe:
  - launched `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_PORT=8588`;
  - `http://127.0.0.1:8588/` returned HTTP 200;
  - packaged startup log confirmed `frozen=True` and patched Flet static temp path.
- Stopped temporary source/exe QA processes after verification.

## 2026-07-04 Chrome Localhost Retest

- Retried Chrome extension control after the user asked to try Chrome/localhost again.
- Chrome extension backend was available in this run.
- Started source app on `http://127.0.0.1:8589/`; local HTTP readiness returned 200.
- Opened the app in Chrome:
  - title: `ETF AI Evidence Cockpit`;
  - first viewport rendered the Simple Scores dashboard;
  - visible data: 19 instruments, 57 model rows, top score 8.6/10.
- Verified visible workflow controls by clicking through Chrome:
  - `1. Refresh yfinance data` completed and updated the data date to 2026-07-02, with 8,910 yfinance rows committed.
  - `2. Run algorithms` completed and refreshed 12 candidate instruments as of 2026-07-03.
  - `3. Run forecasting models` completed from the icon/left hit area and produced configured/candidate forecast outputs for 2026-07-02/2026-07-03.
  - `4. Show scores` routed to `/signals` and rendered the Scores page.
  - Expanded the top score row and verified x/10 algorithm explanations.
- Verified secondary pages:
  - `Data & Models` rendered local price dates, model availability, forecast artefacts, candidate reports and provenance.
  - `Diagnostics` rendered runtime/package/GPU checks with `timesfm: ok` and `toto2: ok`.
- Observation: Flet's canvas text is not exposed to Chrome text locators, so control testing used screenshot-guided coordinate clicks. The app UI itself rendered cleanly.

## 2026-07-04 Workflow Button Hit-Target Fix

- Follow-up from Chrome coordinate QA: the workflow buttons worked, but two controls fired more reliably from their icon/left side than from the right side of the visible label area.
- Replaced the four workflow `ft.Button` controls in `src/etf_cockpit/app/pages/dashboard.py` with fixed-width clickable containers.
- Rationale: the entire visible workflow pill should be the click target in Flet's canvas UI, which is friendlier for users and more stable for visual/browser automation.
- Tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py tests\test_simple_scores.py -q` passed.
  - `.\.venv\Scripts\python.exe -m pytest tests -q` passed.
- Restarted the source app on `http://127.0.0.1:8589/`; HTTP readiness returned 200.
- Note: Chrome control had already been released before this follow-up fix, so the kept Chrome tab may need a manual reload to pick up the updated button hit targets.

## 2026-07-05 Research Report Implementation Pass

- Read the required goal objective attachment at `C:\Users\thor2\.codex\attachments\18b76f6d-6445-4164-adab-cceec5fd5bf1\goal-objective.md`.
- Read and analysed `C:\Users\thor2\Downloads\AI_Evidence_Cockpit_Extensive_Feature_Implementation_Report.md`.
- Researched implementation-relevant primary sources:
  - yfinance official API reference;
  - yfinance `FundsData` reference;
  - Hugging Face TimesFM 2.5 documentation;
  - Datadog Toto 2.0 Hugging Face and GitHub documentation.
- Updated `.ai_worklog\PLAN.md` with the report-driven implementation plan:
  - hard gates before scoring;
  - deterministic algorithms before forecasts;
  - ETF/stock-specific evidence modules;
  - three-score model;
  - low-authority model confirmation;
  - backtest trust and calibration roadmap.
- Implemented the first high-value slice of that plan:
  - expanded `src\etf_cockpit\signals\simple_scores.py` with evidence quality, risk/friction, data quality, liquidity/cost, ETF exposure, stock value, stock quality and analyst proxy components;
  - added component authority and role metadata;
  - added model-authority and backtest-trust labels;
  - added `data\derived\scoreboard.parquet` persistence;
  - extended `src\etf_cockpit\data\trade_candidate_analysis.py` to fetch yfinance fundamentals/profiles for stock candidates;
  - updated `src\etf_cockpit\app\components\simple_scores.py`, `src\etf_cockpit\app\pages\signals.py`, `src\etf_cockpit\app\pages\dashboard.py` and `src\etf_cockpit\app\state.py` for the simpler evidence UI and workflow.
- Ran live yfinance candidate refresh through `DataService.run_yfinance_candidate_analysis()`:
  - output: `data\reports\yfinance_trade_candidate_analysis_20260705T000600Z.csv`;
  - 12 candidate rows refreshed as of 2026-07-03;
  - stock rows included value, quality and analyst/revision proxy scores where yfinance exposed data.
- Built and wrote the scoreboard:
  - `data\derived\scoreboard.parquet`;
  - 19 rows;
  - top rows included SPYK, UCG, EXX1, VIE and ENX with evidence scores from 8.0/10 to 8.9/10.
- Ran source app on `http://127.0.0.1:8590/`; HTTP readiness returned 200.
- Used Chrome visual QA before the browser session was finalised:
  - main page rendered 19 instruments, 57 model rows, top score 8.9/10 and Caution mode;
  - expanded the top row and verified quality, risk/friction, model authority, backtest trust and component authority/role chips;
  - `/signals` rendered the updated evidence categories;
  - `2. Run algorithms` completed from the UI and showed the shorter non-overflowing success message.
- Rebuilt the Windows package with `.\scripts\build_windows.bat`.
- First rebuild attempt found a stale packaged executable lock in `build\flet_dist`; stopped only the old project-specific `ETF_AI_Cockpit.exe` process and reran the build.
- Final package build completed:
  - `build\flet_dist`;
  - `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Smoke-tested the packaged executable:
  - launched `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` with `ETF_COCKPIT_PORT=8591`;
  - `http://127.0.0.1:8591/` returned HTTP 200;
  - stopped the temporary packaged smoke process afterwards.
- Final full regression suite:
  - `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - passed.

## 2026-07-05 Extended Implementation Sweep

- Per the user request, continued the report-driven implementation plan rather than stopping at the prior Phase 1 slice.
- Research basis used:
  - yfinance official API and `FundsData` references for local Yahoo price/profile/fund metadata limits;
  - scikit-learn TimeSeriesSplit/walk-forward guidance for no-lookahead validation design;
  - Hugging Face TimesFM 2.5 documentation for probabilistic time-series model expectations;
  - Datadog Toto 2.0 Hugging Face/GitHub documentation for zero-shot probabilistic forecasting and calibration caveats.
- Added `src\etf_cockpit\models\calibration.py`:
  - loads local forecast history;
  - evaluates only matured forecast rows against later adjusted-close prices;
  - computes OOS MASE, directional accuracy and interval coverage;
  - writes model calibration parquet/CSV.
- Added `src\etf_cockpit\features\regime.py`:
  - yfinance-only market regime score;
  - benchmark/SMA200 context;
  - universe breadth;
  - volatility/drawdown/correlation context;
  - portfolio-fit lookup by correlation and beta.
- Added `src\etf_cockpit\signals\strategy_templates.py`:
  - deterministic strategy-template labels and descriptions;
  - CSV writer for template assignments.
- Updated `src\etf_cockpit\signals\simple_scores.py`:
  - score rows now include calibration, market regime, portfolio fit, strategy templates and backtest trust;
  - scoreboard export now writes parquet, CSV and JSON plus strategy-template CSV.
- Updated `src\etf_cockpit\app\state.py`:
  - workflow score refresh writes calibration and regime artefacts before the scoreboard;
  - audit export refreshes derived artefacts first.
- Updated UI:
  - dashboard adds a Regime card;
  - expanded score rows add Calibration, Backtest, Regime, Portfolio fit and Strategy template chips;
  - Data & Models adds derived artefact, regime, calibration and strategy-template panels.
- Updated `src\etf_cockpit\chatgpt_bridge\export_pack.py`:
  - audit packet now includes scoreboard CSV/JSON, calibration CSV, regime JSON, strategy templates, per-instrument evidence JSON and a derived manifest;
  - ZIP writing is recursive so instrument evidence files are included.
- Added `tests\test_evidence_derivatives.py` and expanded `tests\test_simple_scores.py`.
- Generated current derived artefacts:
  - `data\derived\scoreboard.parquet`;
  - `data\derived\scoreboard.csv`;
  - `data\derived\scoreboard.json`;
  - `data\derived\model_calibration.parquet`;
  - `data\derived\model_calibration.csv`;
  - `data\derived\market_regime.json`;
  - `data\derived\market_regime.csv`;
  - `data\derived\strategy_templates.csv`.
- Exported audit packet:
  - `data\audit_packets\audit_packet_2026-07-02.zip`;
  - verified ZIP entries include `14_scoreboard.csv`, `14_scoreboard.json`, `15_model_calibration.csv`, `16_market_regime.json`, `17_strategy_templates.csv`, `18_derived_manifest.json` and `instrument_evidence/*.json`.
- Chrome QA on source app `http://127.0.0.1:8592/`:
  - dashboard rendered 19 instruments, top score 8.9/10, 57 model rows and Regime `Supportive`;
  - expanded SPYK row showed Calibration, Backtest, Regime, Portfolio fit and Strategy template chips;
  - Data & Models initially rendered blank after the new panels;
  - fixed the `data_models_page` return placement bug;
  - reran Chrome QA and confirmed Data & Models renders derived artefacts, Market regime and Forecast calibration panels.
- Rebuilt package with `.\scripts\build_windows.bat`.
- Smoke-tested rebuilt native executable:
  - `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`;
  - `http://127.0.0.1:8593/` returned HTTP 200;
  - temporary packaged process stopped.
- Packaging follow-up:
  - found `scripts\build_windows.bat` did not copy `data\derived`;
  - patched the script to copy `data\derived`;
  - synced the generated derived files into `build\ETF_AI_Cockpit_Portable_v0.1.0\data\derived`.

## 2026-07-08 Report Issue Workflow And P0 Evidence-Maturity Sweep

- Re-read the active goal objective at `C:\Users\thor2\.codex\attachments\ea817c18-9738-4762-84ba-5bfe59b6c7bf\goal-objective.md`.
- Read and used `C:\Users\thor2\Downloads\report.md`.
- Confirmed the project had `.ai_worklog\PLAN.md` but no root `plan.md`.
- Created root `plan.md` with issue workflow, current open priorities, completed items, rejected scope and evidence limits.
- Created:
  - `issues\open.md`;
  - `issues\closed.md`;
  - `issues\templates\feature_request.md`;
  - `issues\templates\bug.md`;
  - `issues\templates\research_task.md`.
- Populated open issues with the report's P0/P1 items:
  - benchmark attribution;
  - payoff/expected-value diagnostics;
  - friction stress;
  - model/backtest contamination validity;
  - source-credibility scoring.
- Moved completed ISSUE-0001 and ISSUE-0002 to `issues\closed.md`.
- Recorded rejected/deferred ideas in `issues\closed.md`.
- Implemented ISSUE-0002 in `src\etf_cockpit\signals\simple_scores.py`:
  - evidence sample proxy;
  - maturity state/label;
  - too-good-to-be-true warning;
  - full sanity-warning list;
  - warning count.
- Updated `src\etf_cockpit\app\components\simple_scores.py` to show Maturity, Sample, Sanity and Evidence warnings chips.
- Updated `tests\test_simple_scores.py` with unit/export/UI assertions.
- Generated real scoreboard/audit artefacts and verified the new columns are present in `data\derived\scoreboard.parquet` and exported through audit scoreboard files.
- Continued into ISSUE-0003.
- Added `build_benchmark_attribution_lookup(...)` in `src\etf_cockpit\features\regime.py`.
- Added explicit benchmark selection from the configured first ETF to avoid pivot-column ordering.
- Added benchmark attribution fields to `SimpleInstrumentScore` and scoreboard export.
- Added UI chips for Benchmark, Beta, Corr, Alpha proxy and Sector/theme.
- Added unit tests for benchmark attribution and short-history pending labels.
- Regenerated scoreboard/audit artefacts and verified configured ETF rows contain benchmark return, instrument return, beta, correlation, alpha proxy, t-stat and sector/theme warning.
- Moved ISSUE-0003 from `issues\open.md` to `issues\closed.md`.
- Continued into ISSUE-0004.
- Added return-distribution payoff diagnostics to `src\etf_cockpit\backtest\metrics.py`:
  - return hit rate;
  - average win return;
  - average loss return;
  - payoff ratio;
  - expected value per period;
  - payoff asymmetry warning.
- Updated `src\etf_cockpit\app\pages\backtests.py` so hit rate appears beside payoff ratio, expected value and warning text.
- Updated `src\etf_cockpit\services.py` to reject cached backtest CSVs missing the new payoff columns and regenerate them.
- Added `tests\test_backtest_costs.py::test_backtest_hit_rate_is_paired_with_payoff_diagnostics`.
- Verified snapshot backtest results and audit export contain the payoff fields.
- Moved ISSUE-0004 from `issues\open.md` to `issues\closed.md`.
- Continued into ISSUE-0005.
- Added `_cost_stress_metrics(...)` to `src\etf_cockpit\signals\signal_pipeline.py`.
- Added signal supporting metrics for low/base/high cost bps, edge-to-cost ratios, warning labels and assumptions.
- Added cost stress fields to audit export `02_signal_table.csv`.
- Updated visible signal table context to include cost stress warning.
- Added focused tests in `tests\test_signal_gates.py` and `tests\test_release_hardening.py`.
- Verified generated audit signal table includes low/base/high stress fields and values.
- Moved ISSUE-0005 from `issues\open.md` to `issues\closed.md`.
- Continued into ISSUE-0006.
- Added `backtest_validity`, `model_contamination_risk`, `model_authority_reason` and `calibration_required` fields to `SimpleInstrumentScore`.
- Added visible Backtest validity, Model contamination and Calibration required chips.
- Added low-authority model validity helper that marks uncalibrated TimesFM/Toto evidence as unverified for model-history overlap.
- Added regression tests proving optional model scores cannot rescue weak deterministic evidence.
- Verified generated scoreboard and audit scoreboard JSON include the validity fields.
- Moved ISSUE-0006 from `issues\open.md` to `issues\closed.md`.
- Continued into ISSUE-0009.
- Added source credibility metadata to manual-news validation/import in `src\etf_cockpit\data\manual_notes.py`.
- Added rule-based labels for Reddit/community anecdotes, performance screenshots/claims, official/provider sources and research/documentation sources.
- Updated manual news audit markdown to include evidence grade, credibility, promotional risk and reproducibility.
- Added release-hardening tests for credibility labels and audit markdown.
- Verified current audit export handles the no-manual-notes state; fixture tests verify credibility metadata when notes exist.
- Moved ISSUE-0009 from `issues\open.md` to `issues\closed.md`.

## 2026-07-08 Corrected Issue Recovery And Product Roadmap Repair

- Re-inspected `plan.md`, `issues\open.md`, `issues\closed.md`, current Flet routes, current UI buttons, tests and build scripts after the user reported the tracker was incomplete.
- Confirmed `issues\open.md` was effectively empty and `issues\closed.md` contained completed `ISSUE-0001` to `ISSUE-0006` and `ISSUE-0009`, but no open `ISSUE-0007`, `ISSUE-0008` or `ISSUE-0010`.
- Confirmed current app routes are Dashboard/Simple Scores, Portfolio, Scores, Risk, Instrument Detail, Backtests, Audit Notes, Data & Models, Settings and Diagnostics; required Stage 2 routes such as Watchlists, News & Context, Paper Trading, Decision Journal, Roadmap/System Map and Data Health are not first-class pages yet.
- Replaced root `plan.md` with the corrected issue recovery audit, staged product roadmap, missing-feature maturity roadmap, closure rule, rebuild/smoke policy, implementation order and cross-linked follow-ups.
- Rebuilt `issues\open.md` with 59 open issue headings:
  - restored `ISSUE-0007`, `ISSUE-0008` and `ISSUE-0010`;
  - added every unresolved `ISSUE-0011` through `ISSUE-0066`;
  - added source links, problem, why it matters, implementation direction, acceptance criteria, UI requirements, tests, rebuild requirement, plan update requirement and close criteria.
- Updated `issues\closed.md` with a recovery note explaining why `ISSUE-0007`, `ISSUE-0008` and `ISSUE-0010` are not closed.
- Preserved completed issues `ISSUE-0001` to `ISSUE-0006` and `ISSUE-0009` only for their already-tested acceptance criteria.
- Added partial-gap cross-links:
  - `ISSUE-0002` -> `ISSUE-0057`;
  - `ISSUE-0003` -> `ISSUE-0052`, `ISSUE-0059`;
  - `ISSUE-0004` -> `ISSUE-0049`, `ISSUE-0065`;
  - `ISSUE-0005` -> `ISSUE-0050`, `ISSUE-0064`;
  - `ISSUE-0006` -> `ISSUE-0010`;
  - `ISSUE-0009` -> `ISSUE-0058`.
- Added `REJECTED-0008` for options/scalping/0DTE/binary/crypto bot experiments unless separately scoped.
- Verified issue numbering:
  - open issue count: 59;
  - open ids: `0007`, `0008`, `0010` to `0066`;
  - completed issue count: 7;
  - all expected open ids present and no unexpected open ids.
- Ran full regression suite:
  - command: `.\.venv\Scripts\python.exe -m pytest tests -q`;
  - result: all tests passed.
- Ran package rebuild:
  - first attempt found `build\flet_dist` locked by a stale packaged `ETF_AI_Cockpit.exe`;
  - stopped only that stale project packaged app process;
  - reran `.\scripts\build_windows.bat`;
  - result: `Portable folder created at build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Started rebuilt packaged app on port 8594 with browser opening disabled.
- Verified `http://127.0.0.1:8594/` returned HTTP 200.
- Used Playwright with system Chrome to visually smoke-test the rebuilt UI:
  - dashboard rendered;
  - sidebar navigation visible;
  - workflow buttons visible;
  - score list visible.
- Stopped the packaged smoke-test process.

## 2026-07-08 Button Reliability And Progress Sweep

- Inspected current Flet button callbacks and route handling in `src\etf_cockpit\app`.
- Added persistent activity state and local run logging in `logs\activity_log.jsonl`.
- Added visible progress UI:
  - global progress strip below the page header;
  - dashboard Activity log panel;
  - status text for Settings and Audit workflows.
- Wired dashboard process buttons to start immediately, show progress, run in a background worker and write success/failure entries:
  - `1. Refresh yfinance data`;
  - `2. Run algorithms`;
  - `3. Run forecasting models`;
  - Renew/import dialog actions;
  - dashboard audit export.
- Found that live optional model forecasting could run for minutes and leave the main workflow spinning while Toto weights loaded.
- Changed the main dashboard forecast workflow to a bounded path:
  - reuses current cached TimesFM/Toto rows when available;
  - generates baseline forecast rows for the yfinance universe/candidates;
  - writes unavailable optional-model rows instead of launching uncached live TimesFM/Toto from the simple workflow.
- Found and fixed a route bug:
  - `Show scores` changed the browser URL but did not reliably repaint the Scores page;
  - sidebar/custom navigation now sets the route and renders the target view directly.
- Browser/system Chrome verification:
  - dashboard rendered without console errors in a clean system Chrome run;
  - refresh button showed progress and completed with committed yfinance rows;
  - algorithms button showed progress and completed with updated scoreboard;
  - forecasting button showed progress and completed quickly with cached/baseline forecast status;
  - `Show scores` rendered the Scores page;
  - score rows expanded and showed evidence/component explanations;
  - sidebar navigation to Settings and Audit Notes rendered correctly;
  - Audit Notes `Export audit packet` showed a visible exported ZIP path.
- Ran tests:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_flet_startup.py -q` passed.
  - `.\.venv\Scripts\python.exe -m pytest tests -q` passed.
- Rebuilt package:
  - first rebuild attempt failed because a stale `ETF_AI_Cockpit.exe` process locked `build\flet_dist`;
  - stopped only that packaged app process and reran `.\scripts\build_windows.bat`;
  - result: `Portable folder created at build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Packaged smoke:
  - started `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` on port 8596;
  - `http://127.0.0.1:8596/` returned HTTP 200;
  - system Chrome screenshot showed the dashboard after Flet web assets loaded;
  - clean packaged browser run reported no console errors.

## 2026-07-09 report.md Tracker Coverage Repair

- Read the mandatory goal objective file at `C:\Users\thor2\.codex\attachments\18b76f6d-6445-4164-adab-cceec5fd5bf1\goal-objective.md`.
- Audited `C:\Users\thor2\Downloads\report.md` against:
  - `plan.md`;
  - `issues\open.md`;
  - `issues\closed.md`;
  - `issues\templates\feature_request.md`;
  - `issues\templates\bug.md`;
  - `issues\templates\research_task.md`.
- Confirmed `issues\open.md` already contains 59 open issue headings:
  - `ISSUE-0007`, `ISSUE-0008`, `ISSUE-0010`;
  - `ISSUE-0011` through `ISSUE-0066`.
- Confirmed `issues\closed.md` contains 7 completed issue headings:
  - `ISSUE-0001` through `ISSUE-0006`;
  - `ISSUE-0009`.
- Confirmed `issues\closed.md` contains 8 rejected decisions:
  - `REJECTED-0001` through `REJECTED-0008`.
- Added explicit report coverage traceability sections:
  - `plan.md`: `2026-07-09 Report.md Coverage Matrix`;
  - `issues\open.md`: `2026-07-09 Report.md Open Coverage Index`;
  - `issues\closed.md`: `2026-07-09 Report.md Closed And Rejected Coverage Index`.
- Verification command:
  - PowerShell loaded `plan.md`, `issues\open.md` and `issues\closed.md`;
  - checked all expected open IDs, closed IDs, rejected IDs, issue templates and report-derived keywords.
- Verification result:
  - open issue headings: 59;
  - closed issue headings: 7;
  - rejected headings: 8;
  - template count: 3;
  - missing open IDs: none;
  - missing closed IDs: none;
  - missing rejected IDs: none;
  - missing report keywords: none.

## 2026-07-09 Long-Term Automation Roadmap Plan Addition

- Read `C:\Users\thor2\.codex\attachments\b4a0a777-75c9-4807-a5c4-e078c6adba29\pasted-text.txt`.
- Added a future-facing `Long-Term Automation Roadmap: Advisory-First, Automation-Gated` section to `plan.md`.
- Preserved the current safety boundary: live broker execution is not implemented now and still needs separate future approval.
- Added future roadmap details for:
  - automation modes and deterministic-only authority;
  - `Execution Readiness /10`, `Portfolio Fit /10`, `Model Confirmation /10` and `Automation Confidence /10`;
  - automation-grade data provenance and cross-source validation;
  - ETF due-diligence data model, modules and scoring skeleton;
  - stock point-in-time fundamentals data model, modules and scoring skeleton;
  - constrained portfolio target-weight generation;
  - automation-grade validation ladder and diagnostics;
  - TimesFM/Toto model authority caps;
  - supervised tickets, read-only broker reconciliation, paper trading, live canary and constrained live automation stages;
  - future execution services, order policy and kill switches;
  - EU/NL compliance research skeleton;
  - Automation Control Centre UI;
  - future issue skeletons `AUTO-0001`, `AUTO-0002`, `ETF-0001`, `STOCK-0001`, `PORT-0001`, `BT-0001`, `EXEC-0001`, `EXEC-0002`, `EXEC-0003` and `COMPLIANCE-0001`.

## 2026-07-09 updatev2.md Roadmap And Tracker Transfer

- Read `C:\Users\thor2\Downloads\updatev2.md`.
- Confirmed the repository uses `issues\open.md` and `issues\closed.md` rather than root `ISSUES.md` / `CLOSED.md`.
- Added root index files so the prompt filenames exist:
  - `ISSUES.md`;
  - `CLOSED.md`.
- Created `REPORT.md` with the update's required research section:
  - provider/source authority model;
  - provider strategy;
  - European filings strategy;
  - ETF filings-equivalent strategy;
  - candle evidence strategy;
  - CrossCompatibleInvestmentApp reuse notes;
  - testing and rebuild rule;
  - source links.
- Updated `plan.md` with `2026-07-09 updatev2.md Coverage Matrix`.
- Added 21 namespaced open implementation issues to `issues\open.md`:
  - `UPDATEV2-0010` through `UPDATEV2-0030`.
- Added six research-only closures to `issues\closed.md`:
  - `CLOSED-RESEARCH-001` through `CLOSED-RESEARCH-006`.
- Updated `.ai_worklog\PLAN.md`, `.ai_worklog\CHANGES.md` and `.ai_worklog\TESTING.md`.
- No app/runtime code was changed in this pass.

## 2026-07-09 Score History And Mini Chart Roadmap Addition

- Added high-priority `ISSUE-0067` for local score history and per-instrument score evolution mini charts.
- Updated `plan.md`:
  - added score-history storage and charting to Biggest gaps;
  - promoted `ISSUE-0067` to third item in Current Open Priorities;
  - added it to Phase B implementation order;
  - added a dedicated `Score History And Score Evolution Charts` section with required storage schemas.
- Updated `issues\open.md` with detailed acceptance criteria, UI requirement and tests.
- Updated `ISSUES.md` and `.ai_worklog\PLAN.md`.
- No app/runtime code was changed.

## 2026-07-09 Simple Scores Grey Panel UI Fix

- Reproduced the reported Simple Scores visual problem through the rendered Flet web UI.
- Confirmed the large grey area was caused by score content being pushed below a problematic Activity log layout and by the previous expansion-table approach rendering poorly in Flet web.
- Updated the Simple Scores UI so the first viewport now shows the score list directly after the workflow buttons.
- Replaced the previous `ExpansionTile` score rows with dark themed custom score rows to avoid Flet's grey fallback panel.
- Made score-row details use an explicit expander button and kept the row header as a secondary click target.
- Removed nested score-panel scroll usage that could create oversized/blank grey regions in the dashboard/signals views.
- Visual verification:
  - source app served at `http://127.0.0.1:8562/`;
  - first viewport shows summary cards, workflow buttons, score legend and visible score rows;
  - direct Chrome capture reported no page errors and only the expected `Flutter app loaded` console log.
- Automated verification:
  - `.\.venv\Scripts\python.exe -m compileall src`;
  - `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_flet_startup.py -q`;
  - `.\.venv\Scripts\python.exe -m pytest tests -q`.
- Rebuilt the Windows package:
  - command: `.\scripts\build_windows.bat`;
  - result: portable folder refreshed at `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Smoke-tested the rebuilt executable:
  - launched `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`;
  - URL `http://127.0.0.1:8550/` responded with HTTP 200;
  - rendered Chrome screenshot showed the fixed Simple Scores layout from the packaged app.

## 2026-07-09 Two-Tier Universe Implementation

- Replaced the old configured universe with the requested 16 primary tier stocks/ETFs.
- Removed `JAPAN_EQUITY`, `GLOBAL_BONDS` and `GOLD_HEDGE`.
- Added latest secondary yfinance-only candidate file:
  - `data\raw\trade_candidates\yahoo_trade_candidates_2026-07-09.csv`.
- Updated provider symbol mapping to exact yfinance tickers for primary tier.
- Set portfolio context to analysis-only:
  - all primary target weights are zero;
  - cash target is 100%;
  - this keeps config validation valid without implying allocation targets.
- Updated Simple Scores logic:
  - primary rows use `Primary tier`;
  - secondary rows use `Secondary tier`;
  - deleted stale configured IDs are filtered out;
  - latest secondary CSV is authoritative;
  - missing data appears as `Pending Refresh` / `N/A`, not fake scores.
- Added `ISSUE-0068` for future UI-based tier management.
- Explicitly skipped:
  - yfinance refresh;
  - deterministic algorithm run;
  - TimesFM/Toto/model forecast run.

## 2026-07-09 Two-Tier Universe Verification And Rebuild

- Fixed no-refresh startup behaviour after the universe replacement:
  - filtered snapshot prices and holdings to current configured IDs;
  - skipped feature, signal and backtest generation when no clean prices exist for the current universe;
  - kept the Simple Scores list in honest pending/N/A mode.
- Hardened empty-backtest handling:
  - backtest page now shows a pending message instead of indexing an empty row;
  - local LLM context and audit export tolerate empty backtest/signal tables;
  - audit export writes signal-table headers even when no signals exist yet.
- Updated tests to use the new `VWCE`/`EXX1` primary universe where active-config expectations were involved.
- Ran and passed:
  - `.\.venv\Scripts\python.exe -m compileall src`;
  - focused simple-score/startup tests;
  - static two-tier config/data check;
  - full `pytest`;
  - `.\scripts\build_windows.bat`;
  - rebuilt executable HTTP smoke test on `http://127.0.0.1:8550/`.
- Created/updated desktop shortcut:
  - `C:\Users\thor2\Desktop\ETF AI Evidence Cockpit.lnk`.
- Rendered Browser smoke:
  - verified 45 total rows, primary/secondary counts, pending rows, row expansion and lower-list primary/secondary rows;
  - console warnings/errors: none.
- Explicitly did not run yfinance refresh, algorithms or TimesFM/Toto forecasting.

## 2026-07-09 Trust-Critical Implementation Sweep Started

- Read the active 21 trust-critical implementation request.
- Inspected current app state, router, diagnostics, Data & Models, Simple Scores, provider interfaces, yfinance provider and audit export code.
- Confirmed existing app has:
  - central `AppState` activity lifecycle;
  - shell progress strip;
  - dashboard activity panel;
  - provider interface and yfinance/manual/generic provider adapters;
  - central audit export path.
- Updated `plan.md` with the 21 selected issues, execution order, required stores, UI surfaces and release gate.
- Updated `issues/open.md` with the selected-issue programme and added full `ISSUE-0069`.
- Updated root `ISSUES.md` with `ISSUE-0069` and the 21 selected issues.
- Next source work:
  - add `logs/session.jsonl` current-session trace;
  - add provider/identity/conflict/evidence/score-history stores;
  - wire Diagnostics/Data UI and expanded audit export.

## 2026-07-09 Trust-Critical Implementation Sweep Verification

- Implemented `logs/session.jsonl` current-session trace:
  - clears on new app server process start;
  - writes `session_start`;
  - logs navigation/button/workflow activity with action IDs where available;
  - redacts secret-like fields before writing;
  - exposes the trace in Diagnostics.
- Implemented trust-critical Parquet stores:
  - `data\clean\provider_probe_results.parquet`;
  - `data\clean\instrument_identity.parquet`;
  - `data\clean\source_conflicts.parquet`;
  - `data\derived\evidence_ledger.parquet`;
  - `data\derived\score_components.parquet`;
  - `data\derived\score_history.parquet`;
  - `data\derived\score_metric_history.parquet`;
  - `data\derived\feature_drivers.parquet`;
  - `data\derived\correlation_clusters.parquet`;
  - `data\derived\benchmark_attribution.parquet`.
- Added visible UI routes:
  - Provider Status;
  - Evidence Ledger;
  - Filings & Statements;
  - ETF Disclosures;
  - News & Context;
  - Diagnostics session-log panel.
- Expanded the audit/evidence export:
  - includes trust stores as CSV/JSON;
  - includes redacted config and plan/open-issue snapshots;
  - includes checksums;
  - includes `session.jsonl` or an unavailable marker.
- Fixed the Simple Scores grey-panel bug:
  - cause: `_score_tile()` had no reachable return, because its tile-return block was accidentally indented under `_score_history_panel()` after a prior return;
  - fix: restored the tile-return block inside `_score_tile()` and added a regression test proving representative score rows render.
- Ran and passed:
  - `.\.venv\Scripts\python.exe -m compileall src`;
  - `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_trust_critical_artifacts.py -q`;
  - `.\.venv\Scripts\python.exe -m pytest -q`.
- Rebuilt package:
  - command: `.\scripts\build_windows.bat`;
  - result: `build\ETF_AI_Cockpit_Portable_v0.1.0` refreshed successfully.
- Packaged app smoke:
  - launched `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`;
  - `http://127.0.0.1:8550/` responded on port 8550;
  - real Chrome/Windows capture showed score rows instead of the grey panel;
  - expanded the first score row and saw detailed pending/N/A evidence chips;
  - navigated Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures, News & Context and Diagnostics.
- Limitation:
  - optional official-source importers currently expose local inventories and unavailable/null states when no files/provider are configured; full SEC/ESEF/KID/methodology extraction remains open under the related issues until real parsers/import workflows, UI tests and source-specific fixtures are complete.

## 2026-07-09 Launcher, Sparebanken And Reliability Execution

- Executed the approved Superpowers plan `docs\superpowers\plans\2026-07-09-launcher-sparebanken-reliability-plan.md`.
- Confirmed the app root is still not a Git repository; no Git initialisation or commit was performed.
- Added a shared launcher helper in `scripts\launcher_core.py` and updated `ETF_AI_Cockpit.bat`, `Run_ETF_AI_Cockpit_EXE.bat`, `Launch_Latest_ETF_AI_Cockpit.bat` and `scripts\build_windows.bat` to use consistent root resolution, port selection, HTTP readiness checks, browser-open timing, locked-folder handling and clear error messages.
- Added `scripts\smoke_app.py` for source/native/launcher smoke checks with group validation.
- Fixed source web startup so a busy non-HTTP port is not treated as a successful app reuse; startup can fall back to the next free local port.
- Added the requested Sparebanken rows as a distinct `sparebanken` analysis group in `data\raw\trade_candidates\yahoo_trade_candidates_2026-07-09.csv`.
- Preserved unknown Sparebanken ISINs as `needs_verification`; no missing ISIN was invented.
- Moved `NONG` into the Sparebanken group and left `SBNOR` in ordinary secondary candidates.
- Restructured Simple Scores grouping into primary ETF, primary stock/equity-certificate, secondary ETF, secondary stock/equity-certificate and Sparebanken sections.
- Carried `source_group`, `analysis_tier`, `instrument_type`, `data_policy` and `isin_status` into score/trust artefacts where relevant.
- Added yfinance symbol-shape validation and kept invalid/missing provider evidence in unavailable/manual-review states.
- Verified source, native and portable launcher paths after rebuild.
- Browser evidence saved screenshots proving the main page groups, row expansion and trust/diagnostics pages render.
- Updated tracker/worklog files with closure notes for the narrow launcher and Sparebanken execution records while keeping broad selected issues open where their full product scope was not completed.

## 2026-07-10 Post-Review Launcher Completion

- Verified and fixed the review finding that the latest-build launcher ignored the selected timestamped portable output.
- Added native staging fallback for a locked `build\flet_dist`, fixed Windows batch parse-time expansion, and persisted native/portable output manifests.
- Ran the final launcher with both default output folders deliberately locked; it built and launched from timestamped alternate folders on port 8568.
- Re-ran browser, focused, full-suite, compile and snapshot smoke checks, then stopped all verification processes.
- Corrected the pending-state test to isolate persisted report/forecast inputs discovered during the fresh focused gate.

## 2026-07-10 All-41 Closure Train

- Created the machine-readable 41-issue closure matrix and typed evidence-gate evaluator.
- Added the closure status CLI and strict validation for duplicate IDs, unknown gates, unsafe paths and invalid waves.
- Recorded a fresh pre-feature baseline and a no-Git durable execution ledger.
- Task 1 complete; Task 2 official dependency and fixture work is in progress.

## 2026-07-10 Source Foundation Gate

- Resumed from the durable 45% checkpoint and verified `RUN_STATE.json`, plan, handoff and worklog state.
- Focused lint passed for the current feature files after removing unused imports from Data Health and fund-document modules.
- Added the ESEF provider DataFrame contract assertion and normalised API discovery rows to a pandas DataFrame; targeted provider tests and import checks pass.
- Full regression remains 233 passing from the pre-build source gate; fresh packaging and final browser evidence remain pending.

## 2026-07-10 Reviewer Findings Integration

- Integrated the independent checkpoint review without reverting unrelated work.
- Fixed the code-level defects covered by the current regression cycle: selected build manifests, targeted/partial yfinance safety, provider status consistency, Data Health failures, nested secret redaction, route history, audit checksum completeness, empty instrument detail, persisted universe loading and atomic reference/FX/manual-note imports.
- Source/native/portable smoke passed after the launcher manifest fix. The package must be rebuilt again after the later source edits.

## 2026-07-10 Packaged Browser Matrix

- Fresh source tests, compileall, scoped Ruff, final Windows build and source/native/portable HTTP smoke passed; exact command evidence is under `evidence/wave3/`.
- Root native BAT smoke on port 8583 passed after correcting the absolute executable argument. Source BAT smoke and port-reuse checks remain the next verification step.
- Computer Use displayed the packaged main page, primary/secondary/Sparebanken grouping, expanded VWCE detail, trust pages, Data Health export, Universe verification states and controlled unavailable/error states.
- No issue tracker status changed. The browser evidence is sufficient to document implementation state but not to close broad issues whose criteria require complete workflows, export proof or semantic locator coverage.

## 2026-07-10 Task 23 Partial Closure

- Closed only `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` after the evaluator returned ready for all their criteria.
- Added per-issue JSON dossiers plus gate-specific Markdown evidence and SHA-256 sidecars under `evidence/final/`.
- Kept 38 issues open, including all parser/provider workflows and incomplete onboarding, universe, import/export, data-health, accessibility and workflow-reliability scopes.

## 2026-07-10 Data Health Responsive UI

- Added forecast, backtest and macro inventory rows with explicit missing/unavailable states and checksums in `src/etf_cockpit/data/health.py`.
- Replaced the clipped Data Health table with responsive per-dataset evidence rows in `src/etf_cockpit/app/pages/data_health.py`.
- Added Flet control-tree coverage for cache/provenance/failure labels in `tests/test_data_health.py`.
- Focused Data Health result: 3 passed. Full 244-test result was recorded before the final responsive UI correction; rebuild and final full regression remain pending.

## 2026-07-10 ISSUE-0035 Closure

- Final responsive package and selected output manifests passed build and source/native/portable smoke.
- Final regression passed 244 tests; closure-matrix tests passed 9 tests; Data Health export wrote 11 rows with checksum/provenance/freshness/success/failure/warnings fields.
- `ISSUE-0035` moved to closed only after the evaluator reported ready with checksum-backed source, tests, UI, export, build and browser gates. The remaining issue count is 37.

## 2026-07-11 Trust Policy Review Fixes

- Added test-first coverage for env/API/bearer secret redaction, explicit unavailable markers, source-less/non-OK/model score exclusion and audit conflict/full-holdings export.
- Implemented the corresponding source fixes in session logging, audit validation, score aggregation, trust artefact eligibility and audit manifest generation.
- Focused trust bundle passed 49 tests; full suite passed 259 tests. No issue was closed because the rebuilt package/browser gate is still pending.

## 2026-07-11 Follow-Up Review Fixes

- Added JSON-string secret tests for session and workflow logs, unknown source-prefix score exclusion, explicit model authority and exact holdings/required audit-manifest assertions.
- Fixed the shared text redactor, workflow redaction reuse, score source allow-list and audit required artefacts.
- Full regression passed 262 tests; no issue status changed pending the second fresh package/browser gate.

## 2026-07-11 Final Execution Result

- Completed the fresh source-to-package verification after the follow-up trust-policy fixes.
- Recorded final package build, source/native/portable smoke, root launcher start/reuse, package-cwd launcher start, busy-port fallback and package reuse evidence under `evidence\wave4`.
- Recorded fresh Chrome route and rendered UI evidence, audit export validation and controlled diagnostic redaction evidence.
- Evaluator-backed closure state is 4/41 ready and 37 still open. Closed only `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` in this final checkpoint; the pre-existing `ISSUE-0035` remains closed.
- No Git repository exists, no commit was created and `git init` was not run.

## 2026-07-11 Approved Programme Planning Pre-flight

- Read the approved specification and current repository state, then created the programme index, separate dependency-ordered plans and continuation ledger.
- Confirmed no usable Git repository, so no worktree, branch or commit action is available or attempted.
- Fresh baseline passed pytest, Ruff, compileall, source snapshot smoke and source/native/portable startup smoke; a rendered source route was inspected in the in-app browser.
- No issue status has changed. Wave 0 Task 1 is ready for delegated test-first implementation.

## 2026-07-11 Wave 0 Task 1 Complete

- Completed the typed verification and closure-evidence foundation with a historic-41/active-42 closure-matrix migration and separate open DATA-05 record.
- Independent review found and the team fixed actor normalisation and durable-checkpoint evidence defects; final independent task review approved the result.
- Task-level focused tests, scoped Ruff, compilation and source smoke passed after review. No issue status changed and no execution authority changed.

## 2026-07-11 Wave 0 Task 2 Complete

- Extended the existing session JSONL trace with typed operational-event loading/projection, legacy-row compatibility, incomplete-tail quarantine and contextual complete-row integrity failures.
- Added event IDs, prior hashes and canonical hashes for new writes, preserving recursive secret redaction and best-effort logging failure behaviour.
- Added Diagnostics recovery/integrity visibility and AppState trace-derived activity projection.
- Independent review found and a fresh fix implementer resolved the default `logs/workflow.jsonl` secondary writer and stale `logs/activity_log.jsonl` dashboard wording. Explicit workflow `log_path` remains a compatibility/test adapter only.
- Final fresh re-review approved Task 2. Focused 28-test review bundle, full `tests`, Ruff and compilation passed; no issue status changed, no execution authority changed and Task 3 was not started.

## 2026-07-11 Version-Control Baseline

- Confirmed the repository had no `.git` directory, then ran `git init -b main` only after the independently approved Task 2 boundary.
- Strengthened `.gitignore` for credentials, `.env` variants, virtual environments, caches, generated market data, Parquet/DuckDB/database files, model weights, temporary logs, packaged binaries and machine artefacts while preserving source, tests, specifications, plans, issues, evidence and `.ai_worklog`.
- Staged-file checks covered 1,051 paths: no high-confidence secret matches; no staged credentials; no generated build/log/data/model artefacts. The sole file over 10 MB is the intentionally required official ESEF parser fixture `tests/fixtures/official/esef_report_package/7245003GZ2696Y0W1X57-2026-03-31.xbri` (17.23 MB).
- Created the first local commit with `chore: establish version-controlled implementation baseline` on `main`. No remote was configured because `gh` is not installed; no push or GitHub repository creation was attempted.

## 2026-07-12 Wave 1 Governance Task 3 Complete

- Implemented and integrated the deterministic severity-aware authority resolver and permanently fail-closed `trading_allowed` compatibility property.
- Added production propagation for typed authority decisions, ordered nine-gate tables, policy version/checksum metadata and diagnostics in signal and simple-score release paths.
- RED/GREEN evidence, failure-path coverage, independent approval and full-suite capture are recorded in `.ai_worklog/task-governance-3-report.md`, `.ai_worklog/task-governance-3-review-final.md` and `evidence/governance/`.
- PR 173 was independently approved and merged at `5fde19639da9caa6cdb01eef852dc34698b53482`; post-merge focused/affected/full verification passed, `execution_allowed` remains `false`, and no issue state changed. Governance Task 4 is next.

## 2026-07-12 Wave 1 Governance Task 4 Complete

- Implemented and reviewed neutral portfolio review reports and the atomic,
  checksum-protected Decision Journal.
- Fixed reviewer findings across path containment, fail-closed persistence,
  grouped reads, operation semantics, identity/schema checks, deterministic
  supersedes, policy provenance, and owner-token journal locking.
- Fresh independent review approved specification compliance and code quality
  with READY YES and no Critical/Important/Minor findings.
- PR 174 merged at `c61531841a753ce1e3f862f8beb498c629b9cbb5`; focused 23,
  affected and full post-merge tests passed; no issue state changed and
  `execution_allowed` remains `false`. Governance Task 5 is next.
