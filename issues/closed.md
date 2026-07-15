# Closed Issues

Closed issues record completed, rejected and explicitly deferred work. An issue may be closed only when `plan.md` is updated and tests or rejection reasons are recorded.

## 2026-07-08 Recovery Note

The issue recovery pass preserves the completed records for `ISSUE-0001` through `ISSUE-0006` and `ISSUE-0009` only for the acceptance criteria already implemented and tested. These closed issues do not cover every broader recommendation from `report.md`.

Explicitly not closed:

- `ISSUE-0007` - non-executable news/macro contradiction panel. This remains open because contradiction detection is not visible across Dashboard, Instrument Detail, News & Context and Audit export, and has not been rebuilt/smoke-tested.
- `ISSUE-0008` - strategy taxonomy and scope/rejection matrix. This remains open because no first-class Strategy Scope/System Map UI page with authority/test/scope matrix exists yet.
- `ISSUE-0010` - non-executable LLM thesis diary. This remains open because current LLM commentary does not persist instrument-specific thesis snapshots and later outcomes in UI/export.

Partial gaps opened as follow-up issues:

- `ISSUE-0002` -> `ISSUE-0057` for real paper/forward evidence.
- `ISSUE-0003` -> `ISSUE-0052`, `ISSUE-0059` for factor/sector/theme crowding and sector-relative attribution.
- `ISSUE-0004` -> `ISSUE-0049`, `ISSUE-0065` for worst-day, loss-cluster, tail-event and payoff-profile diagnostics.
- `ISSUE-0005` -> `ISSUE-0050`, `ISSUE-0064` for next-open/decision-price realism and friction-adjusted edge per evidence score.
- `ISSUE-0006` -> `ISSUE-0010` for persistent non-executable LLM thesis diary.
- `ISSUE-0009` -> `ISSUE-0058` for stronger closed-source/promotional-claim detection.

Recovery verification:

- Open issue count after repair: 59 (`ISSUE-0007`, `ISSUE-0008`, `ISSUE-0010`, `ISSUE-0011` through `ISSUE-0066`).
- Completed issue count preserved: 7 (`ISSUE-0001` through `ISSUE-0006`, `ISSUE-0009`).
- Command: `.\.venv\Scripts\python.exe -m pytest tests -q`.
  - Result: passed.
- Rebuild command: `.\scripts\build_windows.bat`.
  - First attempt: blocked by stale packaged `ETF_AI_Cockpit.exe` process holding `build\flet_dist`.
  - Fix: stopped only the stale project packaged app process.
  - Rerun result: `Portable folder created at build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Smoke command: start `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` on port 8594 and request `http://127.0.0.1:8594/`.
  - Result: HTTP 200.
- Visual smoke: Playwright with system Chrome rendered the rebuilt dashboard screenshot showing sidebar navigation, workflow buttons and score list.
  - Limitation: Flet text was not exposed as normal DOM text, so semantic locator work remains open as `ISSUE-0045`.

## 2026-07-09 Report.md Closed And Rejected Coverage Index

This file preserves the parts of `C:\Users\thor2\Downloads\report.md` that are already completed or deliberately rejected. Anything user-facing that is not implemented, visible, tested, rebuilt and smoke-tested remains in `issues/open.md`.

### Completed report recommendations

| Report item | Closed record | Remaining linked open work |
|---|---|---|
| Durable issue tracker and plan synchronisation | `ISSUE-0001` | None for tracker creation; workflow compliance continues through all issues. |
| Young/noisy evidence and too-good-to-be-true warnings | `ISSUE-0002` | `ISSUE-0057` for real paper/forward evidence diary. |
| Benchmark alpha/beta/regime attribution | `ISSUE-0003` | `ISSUE-0052`, `ISSUE-0059`, `ISSUE-0051` for deeper factor, sector/theme and cash-relative context. |
| Hit-rate, payoff-ratio and expected-value diagnostics | `ISSUE-0004` | `ISSUE-0049`, `ISSUE-0065` for tail events, loss clusters and payoff-profile classification. |
| Friction/cost/slippage stress engine | `ISSUE-0005` | `ISSUE-0050`, `ISSUE-0064` for operational execution realism and per-score net edge. |
| Explicit model/backtest contamination validity status | `ISSUE-0006` | `ISSUE-0010`, `ISSUE-0048`, `ISSUE-0062` for LLM diary, complexity/PBO and purged-CV research controls. |
| Source-credibility scoring for imported research notes | `ISSUE-0009` | `ISSUE-0058` for stronger promotional/closed-source claim detection. |

### Report items intentionally not closed

- `ISSUE-0007` remains open because the news/macro contradiction panel is not yet visible across Dashboard, Instrument Detail, News & Context and Audit export.
- `ISSUE-0008` remains open because the strategy taxonomy/scope matrix is not yet a first-class UI page with authority, required-data and test columns.
- `ISSUE-0010` remains open because non-executable LLM thesis snapshots and later outcome checkpoints are not yet persisted and exposed in UI/export.

### Rejected report ideas preserved as closed decisions

- `REJECTED-0001` autonomous broker execution now.
- `REJECTED-0002` direct LLM portfolio management.
- `REJECTED-0003` reinforcement-learning trading agents.
- `REJECTED-0004` martingale and grid systems.
- `REJECTED-0005` futures or intraday implementation now.
- `REJECTED-0006` news sentiment as direct score authority.
- `REJECTED-0007` short-sample return screenshots as evidence.
- `REJECTED-0008` options, scalping, 0DTE, binary and crypto bot experiments unless separately scoped.

## Completed

### ISSUE-0001 - Create durable issue tracker and plan synchronisation

**Status:** Completed
**Implementation date:** 2026-07-08
**Type:** Project workflow
**Priority:** P0
**Evidence grade:** High
**Files changed:**
- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `issues/templates/feature_request.md`
- `issues/templates/bug.md`
- `issues/templates/research_task.md`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`

**Tests and checks run:**
- `Get-ChildItem -Recurse -File issues`
- `Test-Path plan.md`
- `Select-String -Path issues\open.md -Pattern '^## ISSUE'`
- `.\.venv\Scripts\python.exe -m pytest tests -q`

**Acceptance criteria:** Passed.
**Remaining limitations:** The issue workflow is Markdown-based rather than a GitHub API integration.
**Plan.md update:** Complete.

### ISSUE-0002 - Add young/noisy evidence and too-good-to-be-true warnings

**Status:** Completed
**Implementation date:** 2026-07-08
**Type:** Safety / Backtest
**Priority:** P0
**Evidence grade:** High
**Files changed:**
- `src/etf_cockpit/signals/simple_scores.py`
- `src/etf_cockpit/app/components/simple_scores.py`
- `tests/test_simple_scores.py`
- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`
- `.ai_worklog/ERRORS_AND_FINDINGS.md`

**What changed:**
- Added `evidence_sample_days`, `evidence_maturity_state`, `evidence_maturity_label`, `too_good_to_be_true_warning`, `evidence_sanity_warnings` and `evidence_warning_count` to simple score rows.
- Added conservative warning logic for unknown/short samples, high scores with weak evidence quality/risk support and large recent returns with unusually small current drawdown.
- Added visible Maturity, Sample, Sanity and Evidence warnings chips to expanded score rows.
- Added the new fields to scoreboard parquet/CSV/JSON. Audit export includes the updated scoreboard CSV/JSON.

**Tests and checks run:**
- `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py -q` - passed.
- `.\.venv\Scripts\python.exe -m pytest tests -q` - passed.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state._write_current_scoreboard(); state.export_audit_packet(); ..."` - passed; generated scoreboard contains the new maturity/sanity columns and the audit ZIP contains `14_scoreboard.csv` and `14_scoreboard.json`.

**Acceptance criteria:** Passed.
**Remaining limitations:** The maturity sample is a price-row proxy, not a live/paper trade diary.
**Plan.md update:** Complete.

### ISSUE-0003 - Add benchmark alpha/beta/regime attribution

**Status:** Completed
**Implementation date:** 2026-07-08
**Type:** Backtest / Risk
**Priority:** P0/P1
**Evidence grade:** High
**Files changed:**
- `src/etf_cockpit/features/regime.py`
- `src/etf_cockpit/signals/simple_scores.py`
- `src/etf_cockpit/app/components/simple_scores.py`
- `tests/test_evidence_derivatives.py`
- `tests/test_simple_scores.py`
- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`

**What changed:**
- Added `build_benchmark_attribution_lookup(...)` using overlapping yfinance adjusted-price returns.
- Added explicit benchmark selection from the configured first ETF, avoiding accidental pivot-column ordering.
- Added benchmark return, instrument return, beta, correlation, alpha proxy and alpha t-stat fields.
- Added sector/theme warning text from local configured metadata.
- Added benchmark, beta, correlation, alpha proxy and sector/theme chips to expanded score rows.
- Added attribution fields to scoreboard parquet/CSV/JSON and therefore to the audit packet scoreboard files.

**Tests and checks run:**
- `.\.venv\Scripts\python.exe -m pytest tests\test_evidence_derivatives.py tests\test_simple_scores.py -q` - passed.
- `.\.venv\Scripts\python.exe -m pytest tests -q` - passed.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state._write_current_scoreboard(); state.export_audit_packet(); ..."` - passed; configured ETF rows include benchmark attribution and sector/theme warning fields.

**Acceptance criteria:** Passed.
**Remaining limitations:** Attribution is descriptive only and does not prove causality. Candidate attribution remains pending until candidate histories are promoted into the clean yfinance price panel.
**Plan.md update:** Complete.

### ISSUE-0004 - Add hit-rate, payoff-ratio and expected-value diagnostics

**Status:** Completed
**Implementation date:** 2026-07-08
**Type:** Backtest / UI
**Priority:** P0/P1
**Evidence grade:** High
**Files changed:**
- `src/etf_cockpit/backtest/metrics.py`
- `src/etf_cockpit/app/pages/backtests.py`
- `src/etf_cockpit/services.py`
- `tests/test_backtest_costs.py`
- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`
- `.ai_worklog/ERRORS_AND_FINDINGS.md`

**What changed:**
- Added return-distribution payoff diagnostics: `return_hit_rate`, `average_win_return`, `average_loss_return`, `payoff_ratio`, `expected_value_per_period` and `payoff_asymmetry_warning`.
- Added Backtests UI columns and diagnostics text so hit rate is displayed with payoff and expected-value context.
- Updated cached backtest loading to reject old CSV results that do not contain required payoff columns, forcing safe regeneration.
- Audit export includes the fields through `05_backtest_summary.json`.

**Tests and checks run:**
- `.\.venv\Scripts\python.exe -m pytest tests\test_backtest_costs.py tests\test_flet_startup.py -q` - passed.
- `.\.venv\Scripts\python.exe -m pytest tests -q` - passed.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state.export_audit_packet(); ..."` - passed; snapshot backtest and audit JSON included all payoff fields.

**Acceptance criteria:** Passed.
**Remaining limitations:** Diagnostics are return-period payoff diagnostics, not per-trade PnL, because the current backtest trade log records rebalance turnover/costs rather than closed trade PnL.
**Plan.md update:** Complete.

### ISSUE-0005 - Add friction/cost/slippage stress engine

**Status:** Completed
**Implementation date:** 2026-07-08
**Type:** Scoring / Backtest
**Priority:** P1
**Evidence grade:** High
**Files changed:**
- `src/etf_cockpit/signals/signal_pipeline.py`
- `src/etf_cockpit/chatgpt_bridge/export_pack.py`
- `src/etf_cockpit/app/components/tables.py`
- `tests/test_signal_gates.py`
- `tests/test_release_hardening.py`
- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`

**What changed:**
- Added low/base/high cost bps scenarios to each generated signal.
- Added low/base/high edge-to-cost ratios.
- Added cost stress warning labels and assumption text.
- Included cost stress fields in the audit signal table.
- Exposed the cost stress warning in the visible signal table context.

**Tests and checks run:**
- `.\.venv\Scripts\python.exe -m pytest tests\test_signal_gates.py tests\test_release_hardening.py -q` - passed.
- `.\.venv\Scripts\python.exe -m pytest tests -q` - passed.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state.export_audit_packet(); ..."` - passed; `02_signal_table.csv` includes low/base/high cost and edge-to-cost stress fields with values.

**Acceptance criteria:** Passed.
**Remaining limitations:** Commission is converted to bps only when a trade value exists; otherwise stress uses configured spread, slippage and FX assumptions.
**Plan.md update:** Complete.

### ISSUE-0006 - Add explicit model/backtest contamination validity status

**Status:** Completed
**Implementation date:** 2026-07-08
**Type:** Model governance
**Priority:** P0/P1
**Evidence grade:** High
**Files changed:**
- `src/etf_cockpit/signals/simple_scores.py`
- `src/etf_cockpit/app/components/simple_scores.py`
- `tests/test_simple_scores.py`
- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`

**What changed:**
- Added `backtest_validity`, `model_contamination_risk`, `model_authority_reason` and `calibration_required` to simple score rows and scoreboard export.
- Added visible Backtest validity, Model contamination and Calibration required chips.
- Marked uncalibrated TimesFM/Toto evidence as low-authority and unverified for model-history overlap.
- Added tests proving high optional model scores cannot rescue low-quality deterministic evidence.

**Tests and checks run:**
- `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py -q` - passed.
- `.\.venv\Scripts\python.exe -m pytest tests -q` - passed.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state._write_current_scoreboard(); state.export_audit_packet(); ..."` - passed; scoreboard and audit scoreboard JSON include the validity fields.

**Acceptance criteria:** Passed.
**Remaining limitations:** The field marks model-history overlap risk conservatively; it does not inspect proprietary model training corpora.
**Plan.md update:** Complete.

### ISSUE-0009 - Add source-credibility scoring for imported research notes

**Status:** Completed
**Implementation date:** 2026-07-08
**Type:** Audit / Manual notes
**Priority:** P1/P2
**Evidence grade:** Moderate
**Files changed:**
- `src/etf_cockpit/data/manual_notes.py`
- `tests/test_release_hardening.py`
- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`

**What changed:**
- Added source URL, source type category, evidence grade, source credibility, promotional risk, reproducibility and claim quality fields to manual note validation/import.
- Added conservative labels for Reddit/community anecdotes, performance screenshots/claims, official/provider sources and research/documentation sources.
- Updated manual-news audit markdown to include credibility metadata.
- Preserved `executable_authority=false`; credibility labels do not affect scores or final actions.

**Tests and checks run:**
- `.\.venv\Scripts\python.exe -m pytest tests\test_release_hardening.py -q` - passed.
- `.\.venv\Scripts\python.exe -m pytest tests -q` - passed.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -c "... AppState.load(); state.export_audit_packet(); ..."` - passed; current local audit correctly reports no manual notes, while fixture tests verify exported credibility metadata when notes exist.

**Acceptance criteria:** Passed.
**Remaining limitations:** Credibility classification is rule-based and conservative; it does not verify external sources online.
**Plan.md update:** Complete.

## Rejected / Deferred

### REJECTED-0001 - Autonomous broker execution

**Status:** Rejected
**Date:** 2026-07-08
**Reason:** Violates the local evidence cockpit objective. No broker order placement or automated execution may be added.
**Source URLs:** `C:\Users\thor2\Downloads\report.md`, https://engo.capital/#research
**Plan.md update requirement:** Recorded in `plan.md`.

### REJECTED-0002 - Direct LLM portfolio management

**Status:** Rejected
**Date:** 2026-07-08
**Reason:** LLMs can hallucinate, be historically contaminated and have no deterministic authority in this app.
**Source URLs:** https://www.reddit.com/r/ai_trading/comments/1ufhpg2/we_gave_frontier_llms_100k_to_manage_8_months_ago/
**Plan.md update requirement:** Recorded in `plan.md`.

### REJECTED-0003 - Reinforcement-learning trading agents

**Status:** Rejected for current scope
**Date:** 2026-07-08
**Reason:** Reward hacking, simulator exploitation and overfitting risk are too high for the yfinance-first manual evidence cockpit.
**Source URLs:** https://www.reddit.com/r/algotrading/comments/1o0yych/after_6_years_its_finally_learning_something/
**Plan.md update requirement:** Recorded in `plan.md`.

### REJECTED-0004 - Martingale and grid systems

**Status:** Rejected for current scope
**Date:** 2026-07-08
**Reason:** Hidden tail risk and blow-up risk conflict with conservative evidence scoring.
**Source URLs:** https://www.reddit.com/r/algotrading/comments/1naoem2/list_of_the_most_basic_algorithmic_trading/
**Plan.md update requirement:** Recorded in `plan.md`.

### REJECTED-0005 - Futures or intraday implementation now

**Status:** Deferred / research only
**Date:** 2026-07-08
**Reason:** Requires specialist sessions, rolls, margin, storage, slippage and provider design outside the current yfinance ETF/stock scope.
**Source URLs:** https://www.reddit.com/r/ai_trading/comments/1up1nrb/where_can_i_find_data_for_futures/
**Plan.md update requirement:** Recorded in `plan.md`.

### REJECTED-0006 - News sentiment as direct score authority

**Status:** Rejected
**Date:** 2026-07-08
**Reason:** Sentiment has latency, source bias, look-ahead and validation risks. It may be context only.
**Source URLs:** https://www.reddit.com/r/ai_trading/comments/1um5mwr/found_an_api_that_reads_financial_news_and_tells/
**Plan.md update requirement:** Recorded in `plan.md`.

### REJECTED-0007 - Short-sample return screenshots as evidence

**Status:** Rejected
**Date:** 2026-07-08
**Reason:** Screenshots and tiny windows are not reproducible and have high selection bias.
**Source URLs:** https://www.reddit.com/r/ai_trading/comments/1uqeb5b/now_were_talking_10_return_in_9_days/
**Plan.md update requirement:** Recorded in `plan.md`.

### REJECTED-0008 - Options, scalping, 0DTE, binary and crypto bot experiments unless separately scoped

**Status:** Rejected for current scope
**Date:** 2026-07-08
**Reason:** These strategies require specialist data, latency, execution, leverage, option-chain, exchange, margin and risk architecture outside the current yfinance-first stock/ETF manual evidence cockpit. They may only be reconsidered through a separate future scope decision and must not be scored as normal instruments now.
**Source URLs:** `C:\Users\thor2\Downloads\report.md`, `C:\Users\thor2\.codex\attachments\e5a1e1cc-e4ed-40a6-a82c-64fc81a688cc\pasted-text.txt`
**Plan.md update requirement:** Recorded in `plan.md`.

## Already Implemented Or Duplicated

### IMPLEMENTED-0001 - No broker execution

**Status:** Implemented core rule
**Date recorded:** 2026-07-08
**Files:** `.ai_worklog/PLAN.md`, UI/scoring action labels.
**Tests:** Existing advisory action tests in `tests/test_simple_scores.py`.
**Remaining limitations:** Continue guarding wording in future UI changes.

### IMPLEMENTED-0002 - yfinance default data backbone

**Status:** Implemented
**Date recorded:** 2026-07-08
**Files:** `src/etf_cockpit/data/yfinance_provider.py`, `src/etf_cockpit/data/trade_candidate_analysis.py`.
**Tests:** Existing yfinance/simple score tests recorded in `.ai_worklog/TESTING.md`.
**Remaining limitations:** Optional providers remain secondary.

### IMPLEMENTED-0003 - Three-score simple evidence model

**Status:** Implemented
**Date recorded:** 2026-07-08
**Files:** `src/etf_cockpit/signals/simple_scores.py`, `src/etf_cockpit/app/components/simple_scores.py`.
**Tests:** `tests/test_simple_scores.py`.
**Remaining limitations:** New maturity and attribution diagnostics are open issues.

### IMPLEMENTED-0004 - Optional forecasts are nullable and low-authority

**Status:** Implemented baseline
**Date recorded:** 2026-07-08
**Files:** `src/etf_cockpit/models/*`, `src/etf_cockpit/signals/simple_scores.py`.
**Tests:** `tests/test_simple_scores.py::test_unavailable_model_forecast_is_na_and_excluded`.
**Remaining limitations:** Contamination/backtest validity remains ISSUE-0006.

## Research Only

### RESEARCH-0001 - Futures and intraday architecture

**Status:** Research only
**Priority:** P3
**Reason:** Outside current yfinance ETF/stock scope.

### RESEARCH-0002 - Triple-barrier and purged-CV ML labels

**Status:** Research only
**Priority:** P3
**Reason:** No classifier module is justified for the simple scoring workflow yet.

### RESEARCH-0003 - Pair-trading or cointegration module

**Status:** Research only
**Priority:** P3
**Reason:** Non-default strategy family outside the current main UI.

### RESEARCH-0004 - Optional SEC EDGAR, FRED and Stooq provider stubs

**Status:** Deferred research
**Priority:** P2
**Reason:** Useful optional enrichment, but lower priority than P0/P1 evidence-validity work.

## updatev2.md Research Closures

These records come from `C:\Users\thor2\Downloads\updatev2.md`. They close research/analysis only. They do not close implementation issues. Implementation remains open as the `UPDATEV2-xxxx` issues in `issues/open.md`.

### CLOSED-RESEARCH-001 - Candle evidence research complete

**Status:** Closed  
**Type:** Research  
**Source:** `C:\Users\thor2\Downloads\updatev2.md`  
**Summary:** Candle research concluded that candles should be added as low-authority OHLCV/context features, not direct pattern-trading logic.  
**Outcome:** Open implementation issue `UPDATEV2-0026`.  
**Closure rule:** Research complete only; implementation pending.

### CLOSED-RESEARCH-002 - CrossCompatibleInvestmentApp review complete

**Status:** Closed  
**Type:** Research  
**Source:** `C:\Users\thor2\Downloads\updatev2.md`; `Thor2709/CrossCompatibleInvestmentApp`  
**Summary:** Reviewed useful patterns from the reference app: Yahoo import, identity warnings, score snapshots, portfolio parser, FX/macro cache, SEC/EDINET/EBA scaffolding, confidence scoring, export/archive and tests.  
**Outcome:** Reuse guidance captured in `PLAN.md` and `REPORT.md`; implementation issues opened for provider registry, identity resolver, evidence ledger and filings.  
**Closure rule:** Research complete only; no code port implied.

### CLOSED-RESEARCH-003 - Provider API research complete

**Status:** Closed  
**Type:** Research  
**Source:** `C:\Users\thor2\Downloads\updatev2.md`; yfinance, FMP, Alpha Vantage and Finnhub sources listed in `REPORT.md`.  
**Summary:** Compared yfinance, FMP, Alpha Vantage and Finnhub. FMP is best optional vendor enrichment provider; Alpha Vantage is small-volume fallback/verification; Finnhub requires entitlement probes; yfinance remains the default free/unofficial market-data backbone.  
**Outcome:** Open implementation issues `UPDATEV2-0010`, `UPDATEV2-0023`, `UPDATEV2-0024` and `UPDATEV2-0025`.  
**Closure rule:** Research complete only; implementation pending.

### CLOSED-RESEARCH-004 - US filings research complete

**Status:** Closed  
**Type:** Research  
**Source:** `C:\Users\thor2\Downloads\updatev2.md`; SEC EDGAR API documentation.  
**Summary:** SEC EDGAR APIs provide no-key REST JSON access to submissions and XBRL company facts for official US statement import.  
**Outcome:** Open implementation issue `UPDATEV2-0012`.  
**Closure rule:** Research complete only; implementation pending.

### CLOSED-RESEARCH-005 - European filings research complete

**Status:** Closed  
**Type:** Research  
**Source:** `C:\Users\thor2\Downloads\updatev2.md`; ESMA ESEF, national OAM and ESAP sources listed in `REPORT.md`.  
**Summary:** European issuer filings should use ESEF/iXBRL annual financial reports, national OAM/regulator discovery and future ESAP support.  
**Outcome:** Open implementation issues `UPDATEV2-0013` and `UPDATEV2-0014`.  
**Closure rule:** Research complete only; implementation pending.

### CLOSED-RESEARCH-006 - ETF disclosure research complete

**Status:** Closed  
**Type:** Research  
**Source:** `C:\Users\thor2\Downloads\updatev2.md`; UCITS, PRIIPs and SFDR sources listed in `REPORT.md`.  
**Summary:** ETF filing equivalents are prospectus, PRIIPs KID, annual/half-year reports, factsheets, full holdings, index methodology, SFDR and securities-lending/collateral disclosures.  
**Outcome:** Open implementation issues `UPDATEV2-0015` through `UPDATEV2-0020`.  
**Closure rule:** Research complete only; implementation pending.

## 2026-07-09 Launcher, Sparebanken And Reliability Run Closures

These are narrow execution records for the approved launcher/Sparebanken plan. They do not close broad product issues that remain open in `issues/open.md`.

### RUN-CLOSED-2026-07-09-LAUNCHER - Windows launcher/build/start/browser-open workflow

**Status:** Closed for the approved run scope.

**Implemented evidence:**

- Added `scripts\launcher_core.py`.
- Updated `ETF_AI_Cockpit.bat`, `Run_ETF_AI_Cockpit_EXE.bat`, `Launch_Latest_ETF_AI_Cockpit.bat` and `scripts\build_windows.bat`.
- Handles repo/app root resolution, port reuse, non-HTTP busy ports, readiness waiting, browser opening after readiness, locked build folders, alternate portable output folders and clear errors.

**Verification:**

- `.\.venv\Scripts\python.exe -m pytest` -> 129 passed.
- `.\scripts\build_windows.bat` -> passed.
- `cmd /c "set ETF_COCKPIT_PORT=8560&& ETF_AI_Cockpit.bat"` -> passed and opened the browser after readiness.
- `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode native --port 8563` -> passed.
- Portable `Run_ETF_AI_Cockpit_EXE.bat` from `build\ETF_AI_Cockpit_Portable_v0.1.0_20260709_205522` on port 8564 -> passed and opened the browser.
- `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode launcher --port 8565` -> passed.

**Limitations:** Broad rebuild/test discipline issues remain open for future features.

**Post-review correction and verification (2026-07-10):**

- Fixed latest-launcher selection of timestamped portable outputs through `build\portable_outdir.txt`.
- Added timestamped native staging fallback and `build\native_outdir.txt`; fixed batch delayed expansion so PyInstaller receives the selected path.
- Final stress run kept both default native and portable folders locked, selected alternate folders, launched PID 32160 from `build\ETF_AI_Cockpit_Portable_v0.1.0_20260710_083014`, reached HTTP readiness on port 8568 and rendered in the in-app browser.
- Fresh verification: 51 focused tests passed; full 131-test suite exited 0; compileall and source snapshot smoke passed.
- Evidence: `browser-final-launch-latest-locked-folders.png`.

### RUN-CLOSED-2026-07-09-SPAREBANKEN-DATA - Sparebanken universe data group

**Status:** Closed for the approved run scope.

**Implemented evidence:**

- Added the 15 requested Sparebanken issuers as `analysis_tier=sparebanken` rows in `data\raw\trade_candidates\yahoo_trade_candidates_2026-07-09.csv`.
- Moved `NONG` into the Sparebanken group.
- Left `SBNOR` as ordinary secondary because it was not requested for the Sparebanken group.
- Preserved missing ISINs as `needs_verification`.

**Verification:**

- `.\.venv\Scripts\python.exe -m pytest tests/test_simple_scores.py tests/test_yfinance_provider.py tests/test_trust_critical_artifacts.py` -> 30 passed.
- `.\.venv\Scripts\python.exe -m pytest` -> 129 passed.
- `.\.venv\Scripts\python.exe scripts\smoke_app.py --mode source --port 8550` -> passed after port selection fix.

**Limitations:** Real ISIN verification for AURG, SOGN, MELG, SADG and SKUE remains a future data-verification task; no ISIN was invented.

### RUN-CLOSED-2026-07-09-SPAREBANKEN-UI - Main page Sparebanken grouping

**Status:** Closed for the approved run scope.

**Implemented evidence:**

- Simple Scores/main page now groups rows into:
  - Primary tier - ETFs
  - Primary tier - stocks/equity certificates
  - Secondary tier - ETFs
  - Secondary tier - stocks/equity certificates
  - Sparebanken - Norwegian savings-bank equity-certificate issuers
- Dashboard and Scores page use the grouped sections.
- Settings copy names the group structure.

**Verification:**

- `browser-main-top.png` shows workflow buttons and the primary ETF group.
- `browser-main-tall.png` shows primary ETF, primary stock/equity-certificate and secondary ETF groups.
- `browser-main-very-tall.png` shows all five groups and Sparebanken rows with `needs_verification` ISINs where applicable.
- `browser-row-expand-attempt.png` shows row expansion still works.

**Limitations:** Full semantic locator/accessibility hooks remain open under `ISSUE-0045`; the full universe manager/provider policy editor remains open under `ISSUE-0068`.

## 2026-07-10 Evidence-Backed Implementation Closures

These records were moved only after the criterion-level closure evaluator reported `ready=true` with checksum-verified source, tests, UI, export, build and browser evidence where required.

### ISSUE-0069 - Single-file session action logging and diagnostics trace

**Status:** Reopened 2026-07-10 after independent review; retained as a rejected closure checkpoint.  
**Dossier:** `evidence/final/issues/ISSUE-0069.json`  
**Evidence:** `evidence/final/source/ISSUE-0069.md`, `tests/ISSUE-0069.md`, `ui/ISSUE-0069.md`, `export/ISSUE-0069.md`, `build/ISSUE-0069.md`, `browser/ISSUE-0069.md`.

The implementation remains present, but the earlier closure was rejected because direct `log_exception` assertions for `traceback_fingerprint` and `exception_message_redacted`, plus a rendered failure-path check, were not evidenced. Keep the canonical issue open until those gates pass.

### UPDATEV2-0022 - Evidence ledger and score component audit trail

**Status:** Reopened 2026-07-10 after independent review; retained as a rejected closure checkpoint.  
**Dossier:** `evidence/final/issues/UPDATEV2-0022.json`  
**Evidence:** `evidence/final/source/UPDATEV2-0022.md`, `tests/UPDATEV2-0022.md`, `ui/UPDATEV2-0022.md`, `export/UPDATEV2-0022.md`, `build/UPDATEV2-0022.md`, `browser/UPDATEV2-0022.md`.

The ledger evidence remains useful, but the earlier closure was rejected because persisted `score_components` rows lack a direct `source_id`/provenance field and the expanded component UI does not expose it. Keep the canonical issue open until source IDs are carried through source, UI, tests and export.

### Historical rejected checkpoint - UPDATEV2-0028 - Report/audit packet expansion for providers, filings, ETF docs and candles

**Status:** Reopened 2026-07-10 after independent review; retained as a rejected closure checkpoint.  
**Dossier:** `evidence/final/issues/UPDATEV2-0028.json`  
**Evidence:** `evidence/final/source/UPDATEV2-0028.md`, `tests/UPDATEV2-0028.md`, `ui/UPDATEV2-0028.md`, `export/UPDATEV2-0028.md`, `build/UPDATEV2-0028.md`, `browser/UPDATEV2-0028.md`.

The audit packet includes the expanded canonical and unavailable artefacts, validates checksums and rejects unlisted members, but the earlier closure was rejected because the ZIP contained neither candle evidence nor an explicit candle-unavailable marker. Keep the issue open until that artefact and its regression/UI/export proof exist.

### ISSUE-0035 - Data health centre

**Status:** Reopened 2026-07-13 after independent review; retained as a rejected closure checkpoint.
**Dossier:** `evidence/final/issues/ISSUE-0035.json`  
**Evidence:** `evidence/final/source/ISSUE-0035.md`, `tests/ISSUE-0035.md`, `ui/ISSUE-0035.md`, `export/ISSUE-0035.md`, `build/ISSUE-0035.md`, `browser/ISSUE-0035.md`.

The historical closure was not accepted for the current Task 10 contract. The
implementation now inventories the required stores and migration/provenance
states; the authoritative full suite, native/portable package smoke and
semantic Data Health controls pass after the current fix cycle. This rejected
checkpoint remains historical only; do not treat it as the canonical closed
record while final integration and local/GitHub synchronisation are pending.

## 2026-07-11 Final Follow-Up Closures

### UPDATEV2-0013 - European ESEF/iXBRL filing importer

**Status:** Closed 2026-07-15
**Closure evidence:** `evidence/final/UPDATEV2-0013/verification_manifest.json` (verification status `pass`; source hash `51fa32b5f63fd2f28572caed241db1dc6bde56e8a8e82afd452486f8471b4e1d`; environment hash `92d7950f655410515a5c3d8b0d89a50c20c620a3da5c8f130fd8fedfeca085db`).
**Principal files:** `src/etf_cockpit/parsers/esef_ixbrl.py`, `src/etf_cockpit/data/esef_provider.py`, `tests/test_esef_ixbrl_parser.py`, `tests/test_esef_provider.py`, `ETF_AI_Cockpit.spec`, `scripts/build_windows.bat`, `configs/closure_matrix.yaml`.
**Implementation:** Offline manual ESEF import preserves raw filing checksums, extracts parseable facts, retains extension concepts with warnings, maps only clear IFRS concepts, and keeps official ESEF authority separate from vendor evidence. Arelle package-loader diagnostics are downgraded only when correlated with the same-run offline loader limitation; explicit conformance failures remain blocking.
**Migration/compatibility:** Existing parser/provider contracts and unavailable states remain compatible; no score, model-authority, portfolio-target or execution-scope changes were made.
**Verification:** `python -m pytest tests -q --tb=short` passed; focused ESEF/provider/release tests passed; `python -m ruff check src tests` passed; `python -m compileall -q src tests` passed; `cmd.exe /d /c scripts\\build_windows.bat` passed; source smoke passed; native onedir and extracted portable ZIP smoke passed; Filings & Statements source/browser render evidence is recorded; audit/export trust tests passed.
**Failure/recovery evidence:** Arelle loader failures, missing taxonomy/package diagnostics, duplicate facts, extension concepts and explicit conformance errors are covered by parser tests; no execution authority is introduced.
**Independent review:** Fresh `/root/task13_review` review approved specification compliance and code quality after two fix passes; no Critical or Important findings remained. Closure evaluator `scripts/verify_issue.py UPDATEV2-0013 --evidence-root evidence\\final --matrix-path configs\\closure_matrix.yaml` returned `status: pass`, with no missing gates.
**Integration:** Verification branch `wave5/task23-final-records`; PR [#197](https://github.com/Thor2709/etf_ai_cockpit/pull/197) merged into `origin/main` at `d3f365daf0413d7e57160df3a40c0bc2f77878c5`. GitHub Issue #153 is closed and synchronised. `execution_allowed=false` remains unchanged.

These records supersede the rejected 2026-07-10 checkpoints above. They were moved only after the closure matrix reported `ready=true` with checksum-verified current source, tests, UI, export, build and browser evidence.

### ISSUE-0069 - Single-file session action logging and diagnostics trace

**Status:** Closed 2026-07-11  
**Dossier:** `evidence/final/issues/ISSUE-0069.json`  
**Current evidence:** `evidence/final/source/ISSUE-0069-wave4.md`, `tests/ISSUE-0069-wave4.md`, `ui/ISSUE-0069-wave4.md`, `export/ISSUE-0069-wave4.md`, `build/ISSUE-0069-wave4.md`, `browser/ISSUE-0069-wave4.md`.

The follow-up added shared redaction for JSON-style secret strings and verified the packaged failure path, fingerprinted diagnostics, export event and audit packet. The local trace remains diagnostic only and does not grant trading authority.

**2026-07-11 Wave 0 Task 2 regression extension:** The existing closed implementation was extended without reopening or changing its status. Typed operational-event loading, incomplete-tail quarantine, contextual integrity errors, event IDs/hash chaining and AppState/Diagnostics trace projection are covered by `.ai_worklog/task-2-review-2.md`. The default workflow controller now persists lifecycle events only through `logs/session.jsonl`; no new execution authority or issue closure was introduced.

### UPDATEV2-0022 - Evidence ledger and score component audit trail

**Status:** Closed 2026-07-11  
**Dossier:** `evidence/final/issues/UPDATEV2-0022.json`  
**Current evidence:** `evidence/final/source/UPDATEV2-0022-wave4.md`, `tests/UPDATEV2-0022-wave4.md`, `ui/UPDATEV2-0022-wave4.md`, `export/UPDATEV2-0022-wave4.md`, `build/UPDATEV2-0022-wave4.md`, `browser/UPDATEV2-0022-wave4.md`.

The follow-up excludes unknown source prefixes from score eligibility and records model evidence as `model_advisory`. Packaged Evidence Ledger and expanded rows visibly expose source, authority, freshness and eligibility boundaries; the archive contains the corresponding exports.

### UPDATEV2-0028 - Report/audit packet expansion for providers, filings, ETF docs and candles

**Status:** Closed 2026-07-15
**Dossier:** `evidence/final/UPDATEV2-0028/verification_manifest.json`
**Current evidence:** `evidence/final/source/UPDATEV2-0028.md`, `tests/UPDATEV2-0028.md`, `ui/UPDATEV2-0028.md`, `export/UPDATEV2-0028.md`, `build/UPDATEV2-0028.md`, `browser/UPDATEV2-0028.md`.

The follow-up made candle/conflict artefacts explicit in the manifest, required a complete holdings summary, and verified non-executable audit import plus secret/checksum validation. Fresh evidence inspected the 156-member ZIP (`64010cb1f6cc33bfbe250c925a129e065dbfd07053313e0adbe5f9caf84badb6`), including explicit candle-unavailable markers. Missing optional evidence remains explicitly unavailable rather than invented. The closure evaluator passed after independent review; integration and GitHub synchronisation are recorded in the follow-up checkpoint.

### ISSUE-0035 - Data health centre

**Status:** Closed 2026-07-13  
**Dossier:** `evidence/final/issues/ISSUE-0035.json`  
**Current evidence:** `evidence/final/source/ISSUE-0035.md`, `evidence/final/tests/ISSUE-0035.md`, `evidence/final/ui/ISSUE-0035.md`, `evidence/final/export/ISSUE-0035.md`, `evidence/final/build/ISSUE-0035.md`, `evidence/final/browser/ISSUE-0035.md`.

Task 10 delivered the deterministic Data Health inventory, persisted
provenance and migration validation, explicit failure-status precedence,
status/dataset/provider filters, stable route actions and compatible CSV
export. The bounded atomic staging fix removed the Windows overlong-prefix
failure while preserving legacy recovery validation. The branch was reviewed
independently with SPEC PASS and CODE PASS, merged by PR 180
(`https://github.com/Thor2709/etf_ai_cockpit/pull/180`) at merge commit
`3eab7a414a54c74553b09ebc4085902af0ffc33e`, and verified on `main`.

Fresh evidence includes 16 focused Data Health tests, 40 affected tests, the
authoritative full suite at 100% with warnings only, compileall and scoped Ruff,
source smoke, portable build, native/portable-native package smoke, source and
packaged browser renders, semantic Data Health controls with Tab focus
traversal, and the 12-row export checksum
`bd89f6e01ea42e90d05a09675d881143f4584c3055e5dfcd7d9a7f7d124b4996`.
The native smoke used the existing native output because the isolated rebuild
venv did not contain PyInstaller; generated market candidate fixtures used for
the score-group smoke remain excluded from Git. `execution_allowed=false` and
all authority and scope boundaries remain unchanged.

The strict parser/provider rule remains in force: SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows remain open without real fixtures, parser tests, UI workflow, export proof and browser smoke evidence.

### UPDATEV2-0015 - ETF disclosure registry (original update ISSUE-0015)

**Status:** Closed 2026-07-15
**Closure evidence:** `evidence/final/UPDATEV2-0015/verification_manifest.json` (`status=pass`, `missing_gates=[]`, `limitations=[]`; source hash `ea01911bb89ad4761cbc68d29a6100a870780b9902a7bfd28436c0f64bcfc113`; environment hash `92d7950f655410515a5c3d8b0d89a50c20c620a3da5c8f130fd8fedfeca085db`).
**Implementation:** Canonical ETF document registry and explicit missing inventory expose factsheet, KID, prospectus/report, holdings and methodology coverage with dated, checksum-addressed provenance. ETF Disclosures and Instrument Detail surfaces show document state and preserve unavailable/manual-review boundaries; audit export includes the inventory and holdings/document artefacts. Tests now isolate ordinary exports from canonical audit packets and missing-registry tests from generated stores.
**Principal files:** `src/etf_cockpit/data/fund_documents.py`, `src/etf_cockpit/data/trust_artifacts.py`, `src/etf_cockpit/app/pages/trust_evidence.py`, `src/etf_cockpit/app/selectors/instrument_detail.py`, `src/etf_cockpit/chatgpt_bridge/export_pack.py`, `tests/test_fund_documents.py`, `tests/test_release_hardening.py`, `tests/test_task19_instrument_detail.py`, `configs/closure_matrix.yaml`.
**Migration/compatibility:** Existing registry, provider/evidence and atomic persistence contracts remain compatible; absent or corrupt optional stores remain explicit unavailable/manual-review states. No scoring weights, model authority, portfolio target or execution scope changed; `execution_allowed=false` remains enforced.
**Verification:** Focused Task 14, Risk, Instrument Detail, trust and UI tests passed; final authoritative suite, Ruff, compileall and Windows build evidence are retained in the manifest; final clean packaged routes `/etf-disclosures`, `/risk` and `/instrument` reached `readyState=complete`; `scripts/verify_issue.py UPDATEV2-0015 --evidence-root evidence/final` returned `status=pass`.
**Audit/export:** `data/audit_packets/audit_packet_2026-07-15.zip` is valid (`ZipFile.testzip() == None`, 158 entries) with required fund document/holdings CSV and JSON members; final SHA-256 `5fb4d1f05cc2446d59ffec9cbdeca6f6b71a50f517e75dc3bd70cf7fbe36f994`. ETF Disclosures screenshot `evidence/final/browser/UPDATEV2-0015-0016-etf-disclosures-packaged-retry.png` SHA-256 `f08a65a8fcc892d63590224fb3eefcbda3829cd0583a1b19cb347f153f857543`.
**Review/closure:** Fresh independent reviewer `/root/task14_review_final` approved specification compliance and code quality with no Critical, Important or Minor findings. The closure evaluator passed all named gates.
**Integration:** Branch `wave5/task23-final-records`; implementation and closure transition are committed in the Task 14 integration sequence and will be merged through the reviewed pull request. GitHub Issue #155 is synchronised to this closed local record after merge.
**Limitations:** Live providers and broker execution remain unavailable by design; no execution authority was introduced.

### UPDATEV2-0016 - ETF holdings normaliser (original update ISSUE-0016)

**Status:** Closed 2026-07-15
**Closure evidence:** `evidence/final/UPDATEV2-0016/verification_manifest.json` (`status=pass`, `missing_gates=[]`, `limitations=[]`; source hash `ea01911bb89ad4761cbc68d29a6100a870780b9902a7bfd28436c0f64bcfc113`; environment hash `92d7950f655410515a5c3d8b0d89a50c20c620a3da5c8f130fd8fedfeca085db`).
**Implementation:** Issuer holdings normalisation validates weights, completeness, freshness, confidence and authority; partial holdings are context-only and invalid/stale values fail closed for current exposure scoring. Risk and ETF Disclosures surfaces expose the holdings-quality row, including `VWCE` `as_of=2026-05-31`, `partial`, `fresh`, confidence `0.55`, issuer authority and `score_eligible=False`. CSV mirror fallback remains compatible when parquet is unavailable.
**Principal files:** `src/etf_cockpit/data/fund_holdings.py`, `src/etf_cockpit/app/pages/risk.py`, `src/etf_cockpit/app/pages/trust_evidence.py`, `src/etf_cockpit/app/selectors/instrument_detail.py`, `tests/test_fund_holdings.py`, `tests/test_task19_instrument_detail.py`, `tests/test_task18_ui.py`, `tests/test_trust_critical_artifacts.py`, `configs/closure_matrix.yaml`.
**Migration/compatibility:** Existing holdings schemas and CSV/parquet compatibility paths are preserved; malformed dates, invalid weights and unavailable files produce explicit invalid/unavailable states without granting authority. `execution_allowed=false` remains enforced.
**Verification:** Focused holdings/Risk/Instrument Detail/trust/UI tests passed; final suite, Ruff, compileall and Windows build evidence are retained in the manifest; clean packaged `/risk` route rendered the holdings-quality row; `scripts/verify_issue.py UPDATEV2-0016 --evidence-root evidence/final` returned `status=pass`.
**Audit/export:** The final audit archive is checksum-verified and contains `fund_documents.csv/.json` and `fund_holdings.csv/.json`; SHA-256 `5fb4d1f05cc2446d59ffec9cbdeca6f6b71a50f517e75dc3bd70cf7fbe36f994`. Risk screenshot `evidence/final/browser/UPDATEV2-0015-0016-risk-holdings-panel-final.png` SHA-256 `a7570e519063971b88e99835dd7837b93cf58ba028f8760a7e4dd0de0433cb47`.
**Review/closure:** Fresh independent reviewer `/root/task14_review_final` approved specification compliance and code quality with no Critical, Important or Minor findings. The closure evaluator passed all named gates.
**Integration:** Branch `wave5/task23-final-records`; implementation and closure transition are committed in the Task 14 integration sequence and will be merged through the reviewed pull request. GitHub Issue #156 is synchronised to this closed local record after merge.
**Limitations:** Holdings remain context-only when incomplete, stale, invalid or provider-unavailable; no live provider or broker execution was introduced.
