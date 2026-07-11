# Decisions

## 2026-06-27

- Keep the sample `WORLD_CORE` 42% target unchanged, but block trading and require manual review because it violates the configured 35% max single-ETF policy. This makes the risk gate visible instead of silently weakening the sample config.
- Keep legacy internal `buy/add/trim/sell` candidate logic for scoring/backtest sizing compatibility, but map release-facing final actions to advisory `add_candidate` and `trim_candidate`.
- Keep API providers as safe stubs until credentials and endpoint mappings are explicitly configured. No network call is made from normal startup or the no-provider workflow.
- Use read-only provider fields in Settings for this pass. Real secret persistence can be added later, but secrets are already kept out of logs/exports and hidden in the UI.
- Label advanced backtest diagnostics as low/not-run rather than inventing probabilistic Sharpe, deflated Sharpe or PBO values.
- Preserve the existing old data folders for compatibility while adding the requested `clean`, `derived`, `snapshots`, `audit_packets` and `reports` layout.
- Keep `ETF_AI_Cockpit.bat` as the normal user entry point because it is the obvious filename and the one the user opened.
- Keep a Python fallback in the same launcher so the project remains runnable if the packaged executable is missing.
- Keep Toto and TimesFM optional and local. Archive extraction and inspection should not make app startup depend on external model packages.
- Do not package extracted model source archives into the Flet runtime folder. They are reference material and add size without improving launch behaviour.
- Use Flet browser mode as the default on Windows because native Flet desktop rendering opened a blank shell on this machine even for a minimal Flet app.
- Let `ETF_AI_Cockpit.bat` own readiness and browser opening for the normal user path. The packaged app serves the local web UI; the batch waits for HTTP success and then opens `http://127.0.0.1:8550/`.
- Keep lightweight startup logs for packaged launches because windowed PyInstaller otherwise hides import, logging and web-server errors.
- Treat current portfolio concentration and residual cash breaches as hard validation blocks, not merely display warnings, because risk gates must run before signal ranking.
- In the daily adjusted-close backtest, generate signals from data through the signal date and apply the trade on the next available price row. This avoids same-bar execution while staying compatible with the available daily data.
- Commit local price imports only after price validation passes. Store the source copy first, snapshot the prior clean store, then write the new clean/compatibility Parquet files so a manual rollback remains possible.
- Use Flet 0.85's async `FilePicker.pick_files()` return value instead of the removed `on_result` callback. In browser mode, accept file bytes and stage them locally before running the same validation/commit pipeline.
- Roll back prices only to timestamped previous clean snapshots created by the import pipeline. Preserve the currently active store before restoring so rollback itself remains reversible by manual file recovery.
- Treat manual thesis/news imports as dated audit evidence only. Even if a source file claims `executable_authority=true`, the clean store and audit packet force `executable_authority=false`.
- Keep manual thesis/news validation simple and strict for this pass: require a dated column and a text/note column, preserve optional title/source/ETF/confidence fields, and warn rather than block when notes reference unknown ETF IDs because notes cannot authorise trades.
- Place manual-note status in the Data & Models first viewport on desktop because the packaged Flet canvas renderer provides weak DOM/scroll semantics; critical provenance should not depend on hard-to-reach lower-page scrolling.
- Treat `etf_metadata`, `etf_factsheet` and `etf_factsheets` as aliases for the same clean factsheet/reference-metadata dataset because the provider config uses `etf_metadata` while the addendum uses ETF factsheet terminology.
- Require explicit `weight_percent` or `weight_pct` for percentage ETF-holdings weights. Plain `weight` must already be decimal so imports do not silently reinterpret units.
- Warn on partial ETF holdings totals below 50% because provider files may contain top holdings only, but block totals above 102% because that is internally inconsistent.
- Treat FX as optional for normal startup while every imported FX rate must be explicit and dated. All current sample ETFs are EUR, so missing FX data should not block the sample app.
- Normalise common FX pair formats by stripping separators only when the remaining code is exactly six letters. Reject malformed pairs instead of guessing currencies.
- For underlying ETF holdings exposure, use only the latest holdings date per ETF and multiply constituent weights by current/target ETF portfolio weights. This keeps imported holdings informational and deterministic without changing signal authority.

## 2026-06-28

- Replace the prior `not_run` advanced backtest placeholders with deterministic local estimates, but label and display them conservatively. This satisfies the spec's need for populated diagnostics without implying that sample-data estimates are proof of future performance.
- Use a CSCV-style PBO proxy and cost-stress parameter sensitivity rather than adding heavy optimisation/backtest libraries. The project stays local, deterministic and easy to test while exposing the required risk-of-overfitting signals.
- Preserve initial Flet routes during startup instead of redirecting to `/`. The normal launcher still opens the dashboard, but direct URLs and browser refreshes should render the requested page in packaged web mode.
- Keep old ChatGPT-named scripts, paths and method wrappers where they are compatibility surfaces, but make the release UI and new default export location neutral: external audit packets under `data\audit_packets`, imported commentary only, no trade authority.
- Keep LM Studio integration optional and manually invoked from the Audit page. Normal startup, signal generation and risk gates must not depend on a local LLM being available; local LLM output is schema-validated commentary only and saved separately under `data\reports`.
- Implement `Create trade proposal` as a non-executable advisory report rather than any broker-facing action. This preserves the manual-review cockpit boundary while giving the user an auditable next-step document.
- Prefer a launcher-provided `ETF_COCKPIT_ROOT` and valid current working directory over bundled `_internal` configs. This keeps packaged runs writing user data to the visible project or portable folder while direct exe launches still have a bundled fallback.
- Treat non-base-currency holdings as invalid for signal generation unless a dated FX rate is available. A stored `market_value_eur` alone is not sufficient evidence because the conversion rate and date must be auditable.
- Reuse an already-running local web server instead of treating a repeated app launch as a fatal startup. The cockpit is local and single-port by design; opening the existing URL is safer than spawning another hidden server process.
- Persist provider names and base URLs in YAML but persist API keys only in ignored local `.env`. This makes the Settings UI useful while keeping secrets out of committed config, logs and audit exports.

## 2026-06-30

- Keep the supplied TimesFM and Toto ZIPs in `models\source_archives` instead of copying their contents into `models\timesfm` or `models\toto`. The archives do not contain runtime checkpoints, and placing source folders under runtime model paths could make future availability checks misleading.
- Leave `configs\model_settings.yaml` in disabled mode for TimesFM and Toto. A real live-model enablement step should require both a compatible Python package and a concrete checkpoint folder.
- Leave `configs\local_llm.yaml` with an empty `model` field for now. The app can safely auto-select the first LM Studio model returned by `/v1/models`, which currently resolves to `qwen3.6-27b`, without hardcoding a model that might be unloaded later.

## 2026-06-30

- Use the Hugging Face Transformers TimesFM 2.5 checkpoint as the default TimesFM live backend because the user supplied that documentation link directly and it exposes `TimesFm2_5ModelForPrediction` with explicit mean and quantile outputs.
- Keep a secondary TimesFM official PyTorch backend because the Google model card documents `timesfm.TimesFM_2p5_200M_torch`, and some local installs may prefer that runtime.
- Feed Toto 2.0 adjusted log returns instead of price levels. The portfolio cockpit needs return evidence, and Toto's documented multivariate tensor plus missing-value mask can represent ETF return panels without silently forward-filling prices.
- Do not add or install heavy model dependencies in this pass. The adapters are optional and import packages only inside live paths; local-first startup and tests must continue without `transformers`, `torch`, `timesfm` or `toto-models` being installed.
- Treat a Hugging Face repo ID as configuration metadata, not availability. A live model is available only when a local checkpoint folder contains weight-like files, unless the user explicitly flips both `allow_remote_download=true` and `local_files_only=false`.

## 2026-06-30

- Use yfinance as an optional convenience data source for Yahoo symbols because the user explicitly requested it. It is still treated as a non-institutional source and must pass local validation before replacing clean app prices.
- Keep the user-supplied Yahoo candidate list outside the main ETF universe. It includes single stocks and a potential ticker/identity conflict, so committing it into ETF signals would blur portfolio-policy boundaries.
- Analyse trade candidates with deterministic price-only evidence rather than fundamental valuation or LLM judgement. The output can mark candidates/watchlist/no-trade, but it cannot authorise broker execution.
- Assume EUR currency for the supplied Yahoo candidates as requested, but keep currency metadata explicit in the generated price frame and reports.

## 2026-06-30

- Keep large safetensor files external to the packaged executable and ignored by source control. The app should discover and use local weights from `models\`, while builds remain portable and avoid embedding multi-GB model files.
- Prefer the Python launcher in `ETF_AI_Cockpit.bat` now that live local model runtimes are installed in `.venv`. The packaged executable remains useful as a fallback, but the Python path is the most accurate local model runtime on this machine.
- Default Toto to the 4M checkpoint because it is small enough for local CPU smoke tests. Keep the 1B checkpoint installed but disabled until RAM/VRAM headroom is explicitly checked for longer inference runs.
- Use the Transformers TimesFM backend for the installed TimesFM safetensor because the uploaded keys match the Transformers architecture after the `ff0`/`ff1` to `fc1`/`fc2` conversion. Preserve the original checkpoint so the conversion remains auditable and reversible.
- Treat model inventory as diagnostic evidence, not trading authority. Even live-ready TimesFM/Toto outputs stay forecast evidence only; deterministic validation and risk gates still control final advisory actions.

## 2026-06-30

- Make Toto 1B the active model because the user confirmed the machine has an 8 GB RTX 5070 Laptop GPU and requested the 1B checkpoint instead of 4M.
- Keep Toto 4M installed as a small fallback/smoke-test checkpoint, but not the active model.
- Use CUDA 13.0 PyTorch (`torch==2.12.1+cu130`) because the NVIDIA driver exposes CUDA UMD 13.3 and the cu130 wheel is available for the current Python/Torch version.
- Upgrade Lightning rather than pinning old `packaging<25`; this keeps both the Toto stack and Flet CLI metadata compatible and makes `pip check` clean.
- Treat TimesFM 180-day output as unsupported rather than failed because the local checkpoint's own config caps output at 128 steps. The audit output must show skipped/null model evidence rather than pretending a 180-day TimesFM forecast exists.
- Keep `ETF_AI_Cockpit.bat` as the supported launcher. It uses the Python CUDA runtime first, which is the only verified path for live Toto 1B GPU inference.

## 2026-06-30

- Reframe allocation target/concentration/cash-minimum issues as portfolio context warnings, not hard analysis blockers. Reason: the user explicitly wants stock/ETF evidence scoring and does not want the app dominated by "too much/too little allocation" decisions.
- Keep strict data-quality hard blockers. Reason: model/algorithm scores are not meaningful if price, FX or holdings data is stale, malformed or internally inconsistent.
- Use latest local forecast CSVs as score inputs rather than running Toto/TimesFM during normal UI startup. Reason: live Toto 1B can be several seconds per run and should remain an explicit refresh step; startup should stay local and responsive.
- Use bounded transformed expected returns for model component scores. Reason: it makes horizons comparable and prevents any one model forecast from overwhelming deterministic evidence.
- Show yfinance candidates on the Scores page rather than merging them into the configured ETF universe. Reason: the list includes individual stocks and ad hoc candidates, so it should be analysis evidence without changing the portfolio configuration.
- Add mobile top navigation instead of trying to compress the desktop sidebar. Reason: the Flet canvas layout otherwise leaves too little width for content at phone-sized viewports.

## 2026-06-30

- Make `ETF_AI_Cockpit.bat` remain the primary supported launcher because it uses the Python CUDA runtime and external model folders most accurately on this machine.
- Also include the native `.exe` onedir output inside the portable folder because the user asked for an executable path and PyInstaller can now build it reliably when stale processes are not locking the output.
- Fail package builds loudly when native packing fails. Reason: a stale executable is worse than no executable because it can reopen the old blank UI and make the user think the fix did not apply.
- Set `ETF_COCKPIT_ROOT` in direct native-exe helper launchers. Reason: direct exe starts should still read and write config/data/logs under the visible project or portable folder, not an internal bundled path.

## 2026-07-01

- Make yfinance the default data backbone because the user explicitly wants the app to run on yfinance. Sample data remains only for fallback/testing.
- Use explicit Yahoo symbol mapping rather than deriving all symbols from exchange/ticker. Reason: Yahoo venue suffixes are not always intuitive, and `IWDA.DE` failed while `IWDA.AS` worked for the configured world-core exposure.
- Treat Yahoo metadata/top holdings as useful but partial evidence, not issuer-grade factsheet authority. Reason: yfinance exposes fund data unevenly and does not consistently provide source dates or complete holdings.
- Run TimesFM/Toto on validated yfinance adjusted-close panels and persist forecast CSVs. Reason: the app score pipeline consumes forecast artefacts, so the reproducible yfinance model run should write the same format used by the UI.

## 2026-07-01

- Use a simple x/10 score layer instead of exposing raw `-1..+1` values. Reason: the user explicitly asked for clear, comparable scores and short explanations.
- Keep the old deterministic signal/risk/backtest systems as diagnostics behind the simplified UI. Reason: the existing auditability is still useful, but it should not dominate the normal workflow.
- Reweight final scores across valid components only. Reason: missing or failed model evidence must show `N/A` and must not drag a score up or down as if the model had produced real evidence.
- Keep candidate instruments under stable `candidate:<ticker>` keys while configured ETFs use `configured:<id>`. Reason: instruments such as `SXRJ` and `EXX1` can exist both as configured ETF exposures and as candidate CSV rows, and those should remain visually distinct.
- Run live Toto/TimesFM only through an explicit workflow button or script, not on UI startup. Reason: Toto 1B can use most available VRAM and take several minutes across the full candidate set.
- Prefer stacked metric cards on narrow/mobile widths. Reason: Flet web truncated labels when several expanded cards were compressed into one row.
- Copy current clean yfinance data, candidate CSV, forecasts and reports into the portable folder. Reason: the native executable should open with the same ready-to-use evidence universe as the source app instead of falling back to sample-only state.
## 2026-07-01 Chrome QA Decisions

- Use lightweight startup checks for model availability.
  - Reason: the first screen must not look blank while optional model packages initialise.
  - Trade-off: detailed live model failures still surface during explicit forecast runs and diagnostics, not during startup.
- Reuse current-date forecast files from the main UI button.
  - Reason: rerunning 1B Toto/TimesFM candidate forecasts in the foreground is too slow for a simple app workflow when valid same-date files already exist.
  - Trade-off: users who need forced full reruns should use diagnostic scripts or delete/replace forecast files; the main screen prioritises responsiveness.
- Use 60 trading days as the UI forecast horizon.
  - Reason: the simple score cards use the 60-day forecast component as primary evidence, so running all horizons from the main button wastes time.
- Keep portfolio concentration/target issues as context.
  - Reason: the user explicitly wants stock/ETF analysis scores rather than an allocation-policy app. Data-quality failures still matter, but allocation caps should not suppress standalone instrument evidence.
- Increase local LLM timeout to 60 seconds.
  - Reason: `qwen3.6-27b` is reachable in LM Studio but may not answer within 12 seconds. The longer timeout is still bounded and local-only.

## 2026-07-04 Startup and QA Decisions

- Patch Flet static temp creation directly instead of globally overriding `TEMP`/`TMP`.
  - Reason: the failure was in Flet's `tempfile.mkdtemp()` path; overriding global temp variables caused pytest and other Python temp users to hit the same inaccessible-directory behaviour.
- Keep runtime temp/cache folders under `logs/`.
  - Reason: they are generated runtime artefacts, local to the app, and safe to ignore.
- Override test `tmp_path` locally rather than relying on pytest's numbered temp helper.
  - Reason: pytest-created numbered temp roots were inaccessible in this Windows session, while normal short `Path.mkdir` folders under the project were writable.
- Do not claim a fresh Chrome visual pass when Chrome extension control is unavailable.
  - Reason: the user requested Chrome validation, but the automation backend was not exposed in this turn. Source/package HTTP readiness and automated tests were still completed.

## 2026-07-05 Report-Driven Scoring Decisions

- Use three visible scores instead of one overloaded score.
  - Reason: the research report correctly separates strength of evidence, quality of evidence and implementation friction/risk. One total score hides those differences.
- Keep direct trading words out of final labels.
  - Reason: the app is an advisory evidence cockpit. Labels such as `Strong Evidence Candidate` and `Positive Evidence Candidate` are clearer and safer than sounding like broker orders.
- Treat TimesFM and Toto as low-authority confirmation until calibrated on this app's yfinance universe.
  - Reason: the model documentation supports zero-shot forecasting, but zero-shot output is not the same as validated edge for these instruments and horizons.
- Use yfinance `Ticker.info` stock fields opportunistically.
  - Reason: it gives free value, quality and analyst proxy evidence for many stocks, but coverage is inconsistent. Missing fields must show as `N/A`, not as fake neutral evidence.
- Persist a derived scoreboard parquet after workflow actions.
  - Reason: a concrete scoreboard artefact makes the UI state auditable and gives future exports/backtests a stable input.
- Leave per-instrument backtest trust and model calibration as explicit follow-up phases.
  - Reason: those require additional walk-forward design and should not be faked by renaming existing aggregate backtest results.

## 2026-07-05 Extended Sweep Decisions

- Evaluate calibration only from matured forecast artefacts.
  - Reason: forecast models should not gain authority from current-date forecasts that have not had time to resolve.
- Use MASE plus directional accuracy as the first calibration layer.
  - Reason: MASE compares forecast error against a local naive scale, while direction accuracy captures the simple up/down usefulness the user expects.
- Keep current TimesFM/Toto calibration pending when no matured forecast rows exist.
  - Reason: zero-shot model availability is not the same as local evidence that the forecast adds value.
- Use one yfinance-only market regime score rather than another external macro provider.
  - Reason: the user explicitly wants the app centred on yfinance, and breadth/trend/volatility/drawdown can be calculated from the same local price data.
- Add strategy templates as labels, not separate trade engines.
  - Reason: the app should remain a simple evidence cockpit; templates explain which common style the evidence resembles without creating automatic trading behaviour.
- Include derived artefacts in audit exports.
  - Reason: external review should see exactly the same scoreboard, calibration, regime and template evidence the UI shows.

## 2026-07-09 Trust-Critical Evidence Decisions

- Use `logs/session.jsonl` as the current app-server session trace, separate from the older append-only `logs/activity_log.jsonl`.
  - Reason: the user needs one file that proves what happened in the current run. Activity history remains useful for recent UI summaries, but the trust-critical trace must connect button clicks, action IDs, workflow steps, exceptions and export artefacts.
- Clear `logs/session.jsonl` only when a new app server process starts.
  - Reason: a fresh process should start with a fresh diagnostics trace, while a running session should preserve all actions for audit/export.
- Write schema-valid empty Parquet stores for optional evidence that is not configured or imported.
  - Reason: downstream UI and export code can be deterministic without inventing missing filings, ETF documents, news or provider data.
- Treat yfinance as the default vendor source, not the highest authority.
  - Reason: yfinance is free and practical for prices and many metadata fields, but official filings, issuer disclosures and regulator sources outrank it when identity-matched.
- Keep optional SEC/ESEF/PRIIPs/index-methodology/news evidence as explicit missing/unavailable inventories until a local file or provider is configured.
  - Reason: the trust-critical rule is to avoid invented evidence. A visible unavailable state is more honest than a parser that pretends coverage without source files.
- Use real Chrome/Windows capture for final Flet visual verification when headless/browser-control transports are unreliable.
  - Reason: Flet web is canvas-heavy and one-shot headless Chrome can capture only the loading logo. Windows capture verified the same visible Chrome window a user sees.

## 2026-07-09 Launcher, Sparebanken And Reliability Decisions

- Centralise Windows launcher behaviour in `scripts\launcher_core.py`.
  - Reason: duplicating port probing, readiness waiting, browser opening and root handling in several batch files had already produced inconsistent behaviour.
- Prefer source launch from `ETF_AI_Cockpit.bat`, with native/package checks preserved.
  - Reason: the local Python environment is the most complete development/runtime path on this machine, while the rebuilt native and portable packages are still verified release artefacts.
- Treat a busy non-HTTP local port as unavailable, not as a reusable cockpit instance.
  - Reason: reusing an arbitrary process on the preferred port can hide startup failure and open the wrong browser target.
- Create a timestamped alternate portable output folder when the old portable folder is locked.
  - Reason: locked build artefacts should not force destructive cleanup or block a clean rebuild; the exact selected folder is recorded in `build\portable_outdir.txt`.
- Keep the Sparebanken issuers in a distinct `sparebanken` group instead of ordinary secondary candidates.
  - Reason: the user explicitly requested Norwegian savings-bank equity-certificate issuers as a separate group, and several rows need honest ISIN-verification state.
- Do not close broad product-scope issues based only on narrow launcher/grouping work.
  - Reason: issues such as onboarding, data health, import/export centre, accessibility and universe manager require full UI/product implementation and evidence, not only partial infrastructure.

## 2026-07-10 Post-Review Launcher Decisions

- Use timestamped alternate directories for locked native staging as well as locked portable output.
  - Reason: a running packaged executable can lock either layer, and a hands-off rebuild must not require manual process cleanup.
- Use delayed expansion only for batch values assigned and consumed inside the same parenthesised block.
  - Reason: normal `%VAR%` expansion occurs when the block is parsed and can silently pass stale paths.
- Persist both selected output paths after packaging.
  - Reason: `build\native_outdir.txt` and `build\portable_outdir.txt` provide auditable release manifests and let the latest launcher select the actual rebuilt package.
- Keep broad reliability and strict parser/provider issues open.
  - Reason: this correction completes the narrow launcher record but does not satisfy unrelated product or parser close gates.
# 2026-07-10 Official Fixture And Dependency Decisions

- Parser dependencies are isolated in requirements-parsers.txt and copied into portable builds; development-only tools remain in requirements-dev.txt.
- Selected Arelle's ESEF extra for standards-aware ESEF validation rather than implementing taxonomy processing from scratch.
- Selected the newest Netherlands filing returned by the documented filings.xbrl.org API query that identified itself as ESEF and exposed a package URL: 7245003GZ2696Y0W1X57-2026-03-31-ESEF-NL-0.
- SEC requests use a descriptive contact-bearing user agent. The first two ESEF attempts failed locally due PowerShell user-agent parsing and transferred no fixture bytes; the corrected request succeeded.
- Official downloads are immutable test evidence. Derived malformed samples must be separate and explicitly synthetic.
- Ruff was introduced as planned and reported 49 repository findings. These are recorded in evidence/wave1/dependencies/ruff.txt; only task-related findings are fixed during each bounded task to avoid unrelated churn.

## 2026-07-10 Source Foundation Gate Decisions

- Keep full Ruff and mypy baseline findings visible rather than applying unrelated repository-wide churn during the closure run.
- Enforce `ProviderResult.data` as a DataFrame at the ESEF provider boundary so UI, export and downstream validation have one predictable table contract.
- Keep all 41 issue records open until final evidence files, checksums, rebuild and rendered browser/computer-use gates are evaluated.

## 2026-07-10 Reviewer Findings Integration Decisions

- Treat the build output manifests as the single source of truth for source-root native and portable smoke; fixed-folder fallback remains compatibility only.
- Reject partial provider refreshes at the provider boundary so downstream commit code cannot mistake incomplete data for a successful full refresh.
- Make persisted universe_store.json canonical when present, with explicit ConfigError on malformed persisted records rather than silently reverting to stale YAML.
- Keep parser/provider records open despite fixture/parser tests until their UI persistence, audit export and packaged browser gates are evidenced.

## 2026-07-10 Packaged Browser Decisions

- Treat Computer Use visual capture as valid packaged Flet evidence when semantic DOM locators and the in-app browser are unavailable, while keeping locator/accessibility issues open.
- Record rendered-readiness delay separately from HTTP readiness; do not hide the roughly five-second direct reload delay.
- Keep the 41-record closure matrix at `still_open` until each issue has its own checksum-backed dossier and all required source/test/UI/export/build/browser gates.

## 2026-07-10 Task 23 Closure Decisions

- Close `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` because every criterion has fresh, checksum-verified evidence and the rendered workflows were directly inspected.
- Keep all other records open. In particular, fixture/parser tests alone do not close SEC, ESEF, PRIIPs, index methodology or provider-backed workflows without their complete UI and export proof.

## 2026-07-10 Data Health Responsive UI Decision

- Do not close `ISSUE-0035` from the first table implementation: the fallback screenshot showed required fields outside the visible viewport. Require evidence from the responsive-row build instead.
- Count the failed Computer Use retry as a browser/computer-use limitation, not as a pass; use Playwright and local HTTP only as clearly labelled fallback evidence.

## 2026-07-10 ISSUE-0035 Closure Decision

- Close `ISSUE-0035` because all matrix criteria have verified source/test/UI/export/build/browser evidence, including the revised responsive UI and final package; retain the Computer Use limitation in the dossier rather than overstating coverage.
- Keep the remaining 37 issues open until each has its own evidence-backed dossier. Do not infer closure from the shared 244-test or package gate alone.

## 2026-07-11 Trust Policy Decisions

- Treat only `OK`, source-backed, non-model components as deterministic evidence. Keep model rows as visible low-authority confirmation, but exclude them from score eligibility and deterministic aggregation.
- Require a named unavailable marker for every required audit artefact that is allowed to be absent; a permissive boolean alone is insufficient evidence.
- Keep `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` open until this source change is rebuilt and the packaged UI plus ZIP are freshly inspected.

## 2026-07-11 Follow-Up Review Decisions

- Use one shared redaction implementation for session and workflow text to avoid policy drift.
- Treat unknown source prefixes as unavailable rather than allowing non-empty strings to imply provenance.
- Require candle evidence or its explicit marker in the audit manifest, not merely in the ZIP member list.

## 2026-07-11 Final Decisions

- Close only the three reopened records whose current evaluator dossiers now contain fresh source, tests, UI, export, build and Chrome evidence: `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028`.
- Keep every other non-ready record open, including all strict parser/provider workflows; do not infer closure from shared tests or screenshots.
- Treat Chrome rendered evidence as the browser gate for this checkpoint and record Computer Use as a failed fallback limitation.
- Preserve the no-Git constraint: durable checkpoint files and worklogs are the recovery mechanism.

## 2026-07-11 Approved Programme Planning Decisions

- The approved specification is the outcome authority and the current repository is the implementation authority; no new product design or scope expansion is permitted.
- The absence of a usable Git repository is not a blocker. The programme uses the plan index, progress ledger, `RUN_STATE.json` and `.ai_worklog` as durable checkpoints and creates no worktree or commit.
- The implementation sequence begins with the operational closure/evidence foundation before governance, registry and DATA-05, so no user-facing coverage record can bypass revision protection, recovery or independent evidence requirements.
- The current planning pre-flight identified no unresolved authorised-requirement contradiction. Legacy action/proposal/model seams remain planned governance migration work, not a reason to relax the non-execution boundary.
