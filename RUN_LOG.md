# Run Log - 2026-07-09 Launcher, Sparebanken, Reliability Execution

## Scope

Executing the approved plan at `docs/superpowers/plans/2026-07-09-launcher-sparebanken-reliability-plan.md`.

## Constraints

- No Git repository is present at the app root; do not initialise Git.
- No remote publishing, broker execution, secret exposure, new dependency, or large reorganisation.
- Unknown Sparebanken ISINs stay `needs_verification`.
- Hard parser/provider issues stay open unless their full evidence gates are met.

## Progress

- Started execution and loaded Superpowers execution, verification, subagent, and review skill instructions.
- Confirmed subagent tooling is available, but direct execution remains the main path because the work is tightly coupled and the user requested efficient usage.
- Baseline command evidence:
  - `git status --short`: failed as expected, not a Git repository.
  - `.\.venv\Scripts\python.exe --version`: Python 3.13.14.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_paths.py tests/test_flet_startup.py tests/test_release_hardening.py tests/test_simple_scores.py`: 60 passed.
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke`: `snapshot_ok as_of=2026-07-09 signals=0 backtests=0`.
- Implemented shared launcher helper, updated Windows launchers/build script, corrected Flet busy-port fallback, added Sparebanken grouping/data/tests, and carried group/ISIN status into score/trust artefacts.
- Focused command evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_simple_scores.py tests/test_yfinance_provider.py tests/test_trust_critical_artifacts.py`: 30 passed.
  - First `.\.venv\Scripts\python.exe -m pytest tests/test_launcher_workflow.py tests/test_flet_startup.py`: 17 passed, 1 failed because `Launch_Latest_ETF_AI_Cockpit.bat` did not expose a direct helper fallback.
  - After adding direct helper fallback: `.\.venv\Scripts\python.exe -m pytest tests/test_launcher_workflow.py tests/test_flet_startup.py`: 18 passed.
  - `.\.venv\Scripts\python.exe -m compileall -q scripts src tests`: passed.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_launcher_workflow.py tests/test_flet_startup.py tests/test_release_hardening.py tests/test_simple_scores.py tests/test_yfinance_provider.py tests/test_trust_critical_artifacts.py`: 78 passed.
  - `.\.venv\Scripts\python.exe scripts\run_app.py --smoke`: `snapshot_ok as_of=2026-07-09 signals=0 backtests=0`.
  - First `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8550`: failed because port 8550 was busy and the app fell back to 8551 while the smoke checker still polled 8550.
  - After fixing smoke port selection: `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8550`: passed with `smoke_port requested=8550 selected=8552 reason=port 8550 is busy but not HTTP-ready` and `smoke_ok mode=source url=http://127.0.0.1:8552/`.
  - Cleaned up repo-local orphan Python listener left by the failed smoke run on port 8551.

## Final Verification

- Tool status:
  - filesystem MCP: available.
  - fetch MCP: available.
  - context7 MCP: available.
  - Playwright MCP: available.
  - Node REPL MCP: available.
  - Flet MCP: not available; Flet was verified through source tests, HTTP readiness and browser screenshots.
  - Git MCP: not available; Git CLI exists, but the app root is not a Git repository.
- App-root Git status:
  - `git status --short`: failed with `fatal: not a git repository`, as expected from the approved plan.
- Full test gate:
  - `.\.venv\Scripts\python.exe -m pytest`: 129 passed in 17.19s.
- Build/package gate:
  - `.\scripts\build_windows.bat`: passed after implementing alternate portable output for locked existing portable folders.
  - Native output: `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
  - Portable output: `build\ETF_AI_Cockpit_Portable_v0.1.0_20260709_205522`.
  - `build\portable_outdir.txt` records the selected portable output path.
- Launcher and app smoke:
  - `cmd /c "set ETF_COCKPIT_PORT=8560&& ETF_AI_Cockpit.bat"`: passed, started source PID 63380, reached `http://127.0.0.1:8560/`, opened browser after readiness.
  - `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode native --port 8563`: passed, started native PID 76260, reached readiness and group checks.
  - `cmd /c "set ETF_COCKPIT_PORT=8564&& Run_ETF_AI_Cockpit_EXE.bat"` from the portable folder: passed, started portable native PID 91816, reached readiness and opened browser.
  - `.\.venv\Scripts\python.exe scripts\launcher_core.py wait-ready --host 127.0.0.1 --port 8564 --timeout 10`: passed.
  - `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode launcher --port 8565`: passed, started source PID 33344, reached readiness and group checks.
  - Verification processes 63380, 76260, 91816 and 33344 were stopped after checks.
- Browser evidence:
  - Playwright loaded `http://127.0.0.1:8560/` and reported page title `ETF AI Evidence Cockpit`.
  - Flet canvas text was not exposed through normal DOM `innerText`, so semantic text assertions remain limited.
  - Screenshot `browser-main-top.png` shows app shell, workflow buttons and `Primary tier - ETFs`.
  - Screenshot `browser-main-tall.png` shows `Primary tier - ETFs`, `Primary tier - stocks/equity certificates` and `Secondary tier - ETFs`.
  - Screenshot `browser-main-very-tall.png` shows all five group headings, including `Secondary tier - stocks/equity certificates` and `Sparebanken - Norwegian savings-bank equity-certificate issuers`; unknown Sparebanken ISINs render as `needs_verification`.
  - Screenshot `browser-row-expand-attempt.png` shows a score row expanded with evidence/detail chips.
  - Direct route screenshots saved for Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures, News & Context and Diagnostics.
  - `browser-direct-providers.png` shows Provider Status with provider probes and unavailable parser/provider states.
  - `browser-direct-diagnostics.png` shows runtime diagnostics and session-log entries.
- Cleanup:
  - No live listeners remained on ports 8560, 8563, 8564 or 8565 after stopping verification processes. Closed `FinWait2` socket entries from the stopped portable process were observed briefly and are not live listeners.

## Issue Outcomes

- Closed run-specific launcher evidence record: Windows launcher/build/start/browser-open workflow passed source, native and portable checks.
- Closed run-specific Sparebanken data record: all 15 requested Sparebanken rows are present, `NONG` moved out of ordinary secondary candidates, `SBNOR` left as ordinary secondary, and unknown ISINs remain `needs_verification`.
- Closed run-specific Sparebanken UI record: main page renders all five requested sections and browser evidence shows Sparebanken as a distinct group.
- Selected 20 broad reliability/trust issues remain open unless already completed by earlier work. This run adds evidence and partial implementation for launcher/build discipline, grouped UI clarity, smoke automation, yfinance symbol validation and unavailable-state handling, but it does not complete broad centres such as onboarding, universe manager, data health, import/export, backup/restore, semantic accessibility or first-run setup.
- Previous 21 trust-critical issues remain open where they require full issue-specific close gates. SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows remain open because this run did not add real parser fixtures, parser tests, UI workflow, export proof and browser smoke verification for those parsers/providers.

## Post-Review Launcher Correction - 2026-07-10

- Review found that `Launch_Latest_ETF_AI_Cockpit.bat` ignored `build\portable_outdir.txt` and could therefore launch a stale or incomplete fixed output directory after a locked-folder build selected a timestamped package.
- Added a regression test before the production change; it failed because the path file was not referenced.
- Updated the launcher to read the selected portable path, with the fixed versioned folder retained only as a compatibility fallback.
- Focused verification checkpoint: `.\.venv\Scripts\python.exe -m pytest tests\test_launcher_workflow.py -q` passed with 8 tests.
- Rebuild and real `Launch_Latest_ETF_AI_Cockpit.bat` verification remain in progress at this checkpoint.
- First post-review end-to-end run failed cleanly because PID 16872 held `build\flet_dist\ETF_AI_Cockpit\logs\stderr.log`; this exposed that native staging lacked the portable output's alternate-directory fallback.
- Added a native-staging regression test and reused `prepare-output-dir --allow-alternate`; the next run selected `build\flet_dist_20260710_081606` but PyInstaller still received `build\flet_dist` because `%NATIVE_OUT_ROOT%` was expanded before `set /p` inside a parenthesised batch block.
- Added delayed variable expansion for the selected native staging root. Focused checkpoint after the correction: 9 launcher tests passed.
- Flet removes the `build` work root during packaging, so the native path manifest is now rewritten after a successful pack. The selected executable check also uses delayed expansion.
- Final stress verification deliberately kept the default native and portable folders locked. `Launch_Latest_ETF_AI_Cockpit.bat` selected `build\flet_dist_20260710_082721` and `build\ETF_AI_Cockpit_Portable_v0.1.0_20260710_083014`, started PID 32160 from the selected portable package on port 8568, reached readiness after 6.1 seconds and requested the browser open.
- In-app browser verification loaded `http://127.0.0.1:8568/`, title `ETF AI Evidence Cockpit`, and saved `browser-final-launch-latest-locked-folders.png` after the rendered Flet UI appeared.
- Fresh focused gate: 51 tests passed. Fresh full gate: 131 tests collected and full pytest exited 0. Compileall and source snapshot smoke also exited 0.
- The focused gate exposed a data-dependent pending-state test. The test now isolates persisted candidate report/forecast loaders, preserving application reload behaviour while making the no-refresh contract deterministic.
- Verification PIDs 16872, 3648 and 32160 were stopped; no repo-local `ETF_AI_Cockpit.exe` process or listener on ports 8567/8568 remained.

## 2026-07-10 All-41 Closure Train - Task 1

- Began approved hybrid subagent-driven execution of `docs\superpowers\plans\2026-07-10-all-41-issues-closure-plan.md`.
- Confirmed the app root remains outside Git; no repository was initialised and checkpoints use durable files.
- Added the typed closure matrix loader/evaluator, CLI status report and a 41-record matrix with 160 issue-specific criteria plus separate common gates.
- Focused closure tests passed: 7 tests.
- Fresh baseline passed: Python 3.13.14, 138 tests collected/passed, compileall passed and source snapshot smoke passed.
- `git status --short` exited 128 as expected because the folder is not a Git repository.
- Closure readiness is intentionally 0/41 until real criterion evidence files are recorded.

## 2026-07-10 All-41 Closure Train - Task 2

- Installed the authorised parser and development dependencies; all required imports passed.
- Downloaded and checksummed six official fixture classes from SEC, filings.xbrl.org, Vanguard and LSEG/FTSE Russell.
- Selected ESEF package: 7245003GZ2696Y0W1X57-2026-03-31-ESEF-NL-0; retained package size is 18,065,040 bytes.
- Official fixture footprint is 23,825,057 bytes and focused fixture tests passed.
- Ruff baseline returned 49 findings. The result is recorded as a non-passing quality baseline, not misreported as a pass.

## 2026-07-10 All-41 Closure Train - Task 3

- Added validated atomic byte/JSON replacement, checksum-verified backup manifests and four idempotent migration versions.
- Routed price imports, rollback writes and trust-artifact Parquet/CSV pairs through failure-preserving atomic commits.
- Failure injection verifies validator rejection, locked replacement, failed second price-store write and failed trust CSV write preserve prior clean data.
- Focused integration result: 42 tests passed; compileall passed.
- Persistent migration evidence applied versions 1-4 and verified its backup manifest.
- The first evidence-only migration command failed due missing PYTHONPATH before importing project code; the corrected retry passed.

## 2026-07-10 All-41 Closure Train - Source Foundation Gate

- Durable checkpoint: 47% plan progress; Tasks 1-5 are final-gated, Tasks 6-21 have source/test foundations, and no issue is closed.
- Focused new-file Ruff check passed after removing unused imports; repository-wide Ruff remains a recorded 53-finding baseline.
- Mypy scope returned 11 errors from missing third-party stubs and pre-existing typing debt; this is recorded as a quality limitation, not a pass.
- Added and passed an ESEF provider contract regression: successful discovery results now expose `ProviderResult.data` as a pandas DataFrame.
- Closure status regenerated cleanly: 41 issues, 0 ready, exit code 1 because evidence dossiers/gates are intentionally not complete.
- Next phase is a fresh Windows rebuild, then source/native/portable launcher smoke and final browser/computer-use evidence.

## 2026-07-10 Reviewer Findings Integration

- Checkpoint: 56% of the all-41 plan. Reviewer Newton returned 14 concrete reliability findings; no issue status was changed.
- Fixed and regression-tested selected native/portable output manifest resolution in launcher_core.py; source-root native and portable smoke now use the paths recorded by the build.
- Fixed yfinance targeted subsets and partial refreshes: incomplete provider results now return error/unavailable state and cannot be committed as successful full refreshes.
- Fixed provider probe artefact contradiction, missing/stale Data Health failure semantics, nested-secret session logging, browser route history, fresh audit manifest timing and strict unlisted-file checksum detection.
- Fixed empty legacy instrument detail state, canonical persisted universe loading and atomic clean/metadata commits for reference, FX and manual-note imports.
- Focused regression bundle and scoped Ruff pass; a fresh full regression and rebuild are still required because these fixes landed after the previous build.

## 2026-07-10 Final Source/Package/Browser Matrix Checkpoint

- Fresh source gate: `.\.venv\Scripts\python.exe -m pytest -q` exited 0 with 242 tests passed.
- Fresh compile gate: `.\.venv\Scripts\python.exe -m compileall -q scripts src tests` exited 0.
- Fresh scoped Ruff gate over touched files exited 0; repository-wide Ruff and mypy remain non-passing baselines and are recorded as such.
- Fresh `cmd /c scripts\build_windows.bat ...` exited 0 and selected `build\flet_dist` plus `build\ETF_AI_Cockpit_Portable_v0.1.0`; executable and runner checks passed.
- Fresh source/native/portable smoke on ports 8580/8581/8582 exited 0 after the final build.
- `Run_ETF_AI_Cockpit_EXE.bat` first exposed a double-prefix path error under the selected manifest; the root launcher was corrected to pass the absolute executable path, then the rerun on port 8583 reached readiness and requested browser open.
- Windows Computer Use displayed the packaged app and verified the five score groups, row expansion, trust pages, Data Health export success, Universe ISIN states, unavailable provider states and controlled error/recovery pages. Evidence: `evidence/wave3/browser/computer-use-matrix.txt`.
- Direct packaged reload was visibly blank/loading for roughly five seconds before Flet rendered; this is recorded as a startup timing limitation. Flet semantic locators remain weak, and the in-app browser refusal remains a fallback limitation rather than a pass.
- Closure status remains intentionally `0/41 ready`; no broad issue was paper-closed from code-only or screenshot-only evidence.

## 2026-07-10 Task 23 Partial Closure Checkpoint

- Created checksum-backed dossiers under `evidence/final/issues/` for `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028`.
- Updated the closure matrix and canonical trackers only for those three records. `scripts/closure_status.py --evidence-root evidence/final` returned 41 records, 3 ready and 38 not ready; exit code 1 is expected while any issue remains open.
- Re-ran the focused 25-test session/ledger/audit bundle with `-rA`: exit code 0 and every listed test passed.
- The source BAT path, port reuse and same-session Audit Notes -> Diagnostics export trace were verified before updating the dossiers.

## 2026-07-10 Data Health Responsive UI Checkpoint

- Focused Data Health tests passed: `3 passed` in `tests/test_data_health.py`.
- The initial fallback screenshot showed the wide 11-column table clipped after `As of`; the UI was corrected to responsive per-dataset evidence rows exposing path, rows, freshness, provider, checksum, last success, last failure and warnings.
- Full regression after the first Data Health implementation passed `244` tests; compileall and scoped Ruff passed. A fresh rebuild is required after the responsive UI correction.
- Computer Use was retried for the rebuilt browser flow but stopped because the helper could not determine Chrome's current URL with enough confidence. This is recorded as a failed Computer Use gate; Playwright/local HTTP remain fallback evidence only.

## 2026-07-10 ISSUE-0035 Closure Checkpoint

- Final responsive Data Health package built successfully: native `build\\flet_dist_20260711_001333`, portable `build\\ETF_AI_Cockpit_Portable_v0.1.0`.
- Final full regression: 244 passed; focused cross-feature gate: 39 passed; compileall and scoped Ruff passed.
- Final source/native/portable smoke passed on ports 8590/8591/8592; packaged native launch on 8593 reached readiness in 4.0 seconds.
- Playwright captured `/data-health` at desktop and 1040px widths and `/` Dashboard summary with zero console errors. Data Health export validation wrote 11 rows with the required full header.
- Closure evaluator reports 4/41 ready and 37 still open. `ISSUE-0035` is now closed; Computer Use URL-confidence failure is recorded and not counted as a pass.

## 2026-07-11 Trust Policy Review-Fix Checkpoint

- Independent review found four substantive trust gaps: bearer/env secret redaction, score aggregation accepting source-less components, inconsistent model score authority, and permissive unavailable markers. It also required direct conflict and full configured holdings export regression coverage.
- Tests were added before implementation and initially failed as expected. The fixes then passed the focused trust bundle (`49 passed`) and the full suite (`259 passed`, exit code 0).
- `compileall` and scoped Ruff passed. Repository-wide Ruff remains non-zero only for pre-existing unrelated script E402/F841 findings.
- No closure status changed. `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` remain open until the fresh package rebuild and Chrome/browser evidence after these source changes.

## 2026-07-11 Follow-Up Review Fix Checkpoint

- Follow-up review found JSON-string redaction leaks in session/workflow logs, unknown source-prefix scoring, ambiguous model authority, missing candle required-manifest declaration and weak holdings assertions.
- Added tests first, then fixed the shared redactor, workflow reuse, score source allow-list, `model_advisory` authority and required audit artefact manifest.
- Final source regression: 262 tests passed; compileall and scoped Ruff passed. A second rebuild is required because these fixes landed after the prior package.

## 2026-07-11 Final Package, Launcher and Closure Checkpoint

- Fresh final build passed and produced `build\ETF_AI_Cockpit_Portable_v0.1.0` plus `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
- Source, native and portable smoke passed on ports 8630, 8631 and 8632. Root launcher start/reuse passed on 8633. The corrected portable launcher test ran from the package directory, passed on 8634, selected fallback 8635 for a non-HTTP busy port, and then passed package reuse on 8634.
- Fresh Chrome rendered the grouped Simple Scores page, row expansion, component details, Sparebanken ISIN verification states, Diagnostics, Evidence Ledger and Audit Notes/export. Route smoke passed for `/`, `/providers`, `/evidence`, `/filings`, `/etf-disclosures`, `/news-context`, `/diagnostics` and `/chatgpt`.
- Fresh audit ZIP validation passed: valid archive, zero checksum errors, zero secret findings, explicit candle/conflict handling, 16 unique holdings with required fields, and `model_advisory` provenance.
- Closure evaluator returned 4 ready and 37 still open. Only `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` changed from reopened to closed in this checkpoint; `ISSUE-0035` was already closed. Strict parser/provider records remain open.
- Computer Use did not pass because the Windows URL-confidence policy stopped the attempt; this is recorded as a limitation, not a browser pass.

## 2026-07-11 Wave 0 Task 3 Review-Capability Checkpoint

- Task 3 implementation and fix commits are on `wave0/task3-atomic-recovery` from `445dd44b5382160d4e93e4cada018beb4ab0f5b5`; no push, pull request, merge or GitHub Issue mutation has occurred.
- The focused transaction/recovery bundle passed 55 tests; the adversarial bundle passed 17 tests; scoped Ruff, compileall and diff checks passed.
- The fresh full suite collected 323 tests, passed 316 and retained the same seven isolated-worktree generated-artefact baseline failures. No Task 3 test failed.
- Durable Task 3 artefact and fault-matrix checks report zero checksum mismatches. `execution_allowed` remains `false`; `ISSUE-0040` and DATA-05 remain open.
- A parent-side stale-lock containment gap was found through a RED test and fixed locally; the containment fix and review artefacts are recorded in checkpoint commit `d7fdac5`.
- The mandatory fresh independent re-review is pending because no permitted, verifiable GPT-5.6 Luna/Max custom role is available and the attempted dispatch returned a usage-limit error. Task 4 must not start until that review and integration gate pass.

## 2026-07-12 Wave 0 Task 3 Independent Approval and Integration Handoff

- Five bounded fix passes addressed stale-lock scope, rollback-failure durability, owned artefact validation, unreadable evidence, malformed states and null-backup safety. Final implementation commit: `201ee9e`.
- Final focused Task 3 bundle passed 71 tests; scoped Ruff, compileall and full-range `git diff --check` passed. Fresh independent review ran an 11-test adversarial slice and approved specification compliance and code quality with no Critical, Important or Minor findings (`.ai_worklog/task-3-review-final2.md`).
- Task 3 is approved for branch integration. `ISSUE-0040` remains open because the later Error/Recovery UI, package and browser gates are not owned by Task 3. `execution_allowed` remains `false`; DATA-05 remains open; Task 4 has not started.
