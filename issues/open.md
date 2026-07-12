# Open Issues

This file tracks unresolved work for the AI Evidence Cockpit / ETF AI Portfolio Cockpit. It is synchronised with `plan.md` and `issues/closed.md`.

Closure update 2026-07-11: `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` passed the current source, tests, UI, export, rebuild and Chrome evidence gates and were moved to `issues/closed.md`. Their detailed sections below are retained as historical acceptance records and are no longer active open work.

Wave 0 Task 2 checkpoint 2026-07-11: the session-trace operational-authority regression was independently approved, including workflow single-trace persistence, recovery, redaction and Diagnostics visibility. No open tracker record changed state; `DATA-05` remains `still_open`, and the next implementation task is Wave 0 Task 3.

Wave 0 Task 3 checkpoint 2026-07-12: atomic transaction and deterministic recovery implementation plus five bounded fix passes were independently approved and merged through PR 1 at `046e3bbfe9cab41f6cfec59547f540bce85b2c44`. Post-merge focused tests, source smoke, Ruff and compileall passed. `ISSUE-0040` remains open because its Error/Recovery UI, package and browser gates are later work; Wave 0 Task 4 is the next implementation task.

Wave 0 Task 4 checkpoint 2026-07-12: the no-execution/rejection boundary, auditable rejection registry and future-only architecture records were independently approved and merged through PR 2 at `0f2b2cb`. A post-merge generated-package false-positive was reproduced with RED evidence, corrected by excluding top-level ignored `build/` and `dist/` roots, independently approved and merged through PR 3 at `5b732e4`. Final clean-main scope/release, release/operations, static-scan and source-smoke checks passed. No open issue changed state; `ISSUE-0040` and later tracker records remain open, and Wave 0 Task 5 is next.

Wave 0 Task 5 checkpoint 2026-07-12: deterministic read-only evidence
verification, source/environment binding, freshness/checksum gates, fail-closed
clean-environment/package/Chrome stages and deterministic package modes were
independently approved after a fix pass and merged through PR 4 at
`fc4d61cfc6e77da9a91aeb5afe0341b1d7658f55`. Focused Task 5/review-record
tests (31), release tests (26), operations tests (81), Ruff, compileall, pip
check, PowerShell AST parsing and source smoke passed post-merge. No open issue
changed state; `UPDATEV2-0029`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0045`,
`ISSUE-0040` and later tracker records remain open for their complete closure
gates. Wave 1 governance Task 1 is next.

GitHub mirror checkpoint 2026-07-12: the deterministic synchroniser mapped 98
selected local records (77 open and 21 closed) to canonical GitHub Issues and
reconciled the remote state successfully. Exact stable-ID duplicate records
were retained and closed as duplicates; no local issue changed state and no
GitHub issue was deleted. See `issues/github_issue_map.json`,
`issues/github_issue_sync_report.json` and
`.ai_worklog/github-issue-sync.md`.

## Tracker Rules

Every issue below is open until all close criteria pass. User-facing issues must be implemented in source, visible in the app UI, tested, included in audit/export where relevant, rebuilt, started from the rebuilt app and smoke-tested from the user's point of view. Backend-only fields do not close UI-facing issues.

Common close criteria for every issue:

- Implemented in source or explicitly documented as architecture/research-only.
- Visible in the app UI where user-facing.
- Relevant tests added or updated.
- Audit/export output updated where relevant.
- `plan.md`, `issues/open.md` and `issues/closed.md` updated.
- Package rebuilt with recorded command/result.
- Rebuilt app starts and local UI smoke test passes.
- Remaining limitations recorded.

Common sources:

- `C:\Users\thor2\Downloads\report.md`
- `C:\Users\thor2\.codex\attachments\e5a1e1cc-e4ed-40a6-a82c-64fc81a688cc\pasted-text.txt`
- https://engo.capital/#research
- https://www.reddit.com/r/ai_trading/comments/1uqeb5b/now_were_talking_10_return_in_9_days/
- https://www.reddit.com/r/ai_trading/comments/1up1nrb/where_can_i_find_data_for_futures/
- https://www.reddit.com/r/ai_trading/comments/1upo5hx/i_built_a_monthly_decision_making_model_includes/
- https://www.reddit.com/r/ai_trading/comments/1uoxagq/i_have_developed_a_swing_trading_algo/
- https://www.reddit.com/r/ai_trading/comments/1up500b/i_have_been_live_trading_with_my_own_ai_model_for/
- https://www.reddit.com/r/algorithmictrading/comments/1uo19kf/i_built_a_closebased_momentumquality_strategy/
- https://www.reddit.com/r/ai_trading/comments/1um6odg/im_an_ml_engineer_i_got_tired_of_ai_trading_bot/
- https://www.reddit.com/r/ai_trading/comments/1unl3hn/i_accidentally_built_the_ai_investing_tool_i/
- https://www.reddit.com/r/ai_trading/comments/1um5mwr/found_an_api_that_reads_financial_news_and_tells/
- https://www.reddit.com/r/ai_trading/comments/1ufhpg2/we_gave_frontier_llms_100k_to_manage_8_months_ago/
- https://www.reddit.com/r/algotrading/comments/1upwuy9/the_biggest_trading_study_ever_43m_trades/
- https://www.reddit.com/r/algotrading/comments/1naoem2/list_of_the_most_basic_algorithmic_trading/
- https://www.reddit.com/r/algotrading/comments/1q25jpe/2025_was_my_best_year_and_heres_what_i_did/
- https://www.reddit.com/r/algotrading/comments/1o0yych/after_6_years_its_finally_learning_something/
- https://ranaroussi.github.io/yfinance/
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://fred.stlouisfed.org/docs/api/fred/
- https://stooq.com/db/h/

## 2026-07-09 Report.md Open Coverage Index

This section exists to prove that every unresolved recommendation from `C:\Users\thor2\Downloads\report.md` has a live tracker entry. Closed or rejected report items are recorded in `issues/closed.md`; all remaining user-facing work stays open until implementation, UI visibility, tests, rebuild and smoke-test evidence are recorded.

| Report recommendation or theme | Open issue coverage |
|---|---|
| Non-executable news/macro contradiction panel | `ISSUE-0007`; broader dashboard/import/provider work in `ISSUE-0025`, timestamp safety in `ISSUE-0054`, optional providers in `ISSUE-0055`. |
| Strategy taxonomy and scope/rejection matrix | `ISSUE-0008`; visible roadmap/system map in `ISSUE-0015`, strategy templates in `ISSUE-0029`, unsupported-asset guardrails in `ISSUE-0056`, rejection tests in `ISSUE-0060`. |
| Non-executable LLM thesis diary | `ISSUE-0010`; linked to model/backtest contamination validity from closed `ISSUE-0006`. |
| Real paper/forward evidence beyond price-row maturity proxy | `ISSUE-0057`, with paper portfolio implementation in `ISSUE-0031` and decision journalling in `ISSUE-0030`. |
| Factor/sector/theme crowding and sector-relative attribution beyond broad benchmark beta | `ISSUE-0052`, `ISSUE-0059`, with cash/benchmark comparison in `ISSUE-0051`. |
| Worst-day, loss-cluster, tail-event and payoff-profile diagnostics beyond basic hit-rate/payoff fields | `ISSUE-0049`, `ISSUE-0065`. |
| Decision-price, next-open, arrival-price, spread proxy, VWAP/NBBO-style execution realism and no same-bar execution | `ISSUE-0050`, `ISSUE-0063`. |
| Friction-adjusted return estimate and edge-to-cost display per evidence score | `ISSUE-0064`. |
| Overfitting/complexity metadata, PBO/deflated-Sharpe hardening and purged-CV research guardrails | `ISSUE-0048`, `ISSUE-0062`. |
| Source credibility hardening for closed-source, promotional and screenshot-like claims | `ISSUE-0058`. |
| Optional free provider research/stubs: SEC EDGAR, FRED, Stooq, RSS and yfinance news | `ISSUE-0025`, `ISSUE-0055`. |
| Futures/intraday architecture remains research-only and unsupported assets must not be silently scored | `ISSUE-0056`, `ISSUE-0061`; rejected-now decision in `REJECTED-0005`. |
| Pair trading/cointegration and triple-barrier/purged-CV are research-only, not default scoring | `ISSUE-0061`, `ISSUE-0062`. |
| Monthly decision template and close-based quality-momentum next-open template | `ISSUE-0046`, `ISSUE-0063`. |
| Backtest/paper/live realism and future broker source-of-truth/reconciliation warnings | `ISSUE-0032`, `ISSUE-0031`, `ISSUE-0057`, `ISSUE-0066`. |
| Product UI reliability, visible progress, rebuild gates and user-perspective smoke tests | `ISSUE-0011`, `ISSUE-0012`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0045`. |
| Full manual stock/ETF research-suite shape requested after the report | `ISSUE-0015` through `ISSUE-0044`, with expanded report-derived items in `ISSUE-0046` through `ISSUE-0066`. |

## 2026-07-09 updatev2.md Open Coverage Index

`C:\Users\thor2\Downloads\updatev2.md` adds a second research/update set focused on provider integrity, official filings, ETF disclosures, evidence ledgers, candle context, UI workflow status and rebuild discipline. Its proposed issue numbers overlap existing tracker IDs, so this file preserves them as namespaced `UPDATEV2-xxxx` issues. These are open until the common close criteria pass. The original update issue number is recorded in each title.

Core preserved rules: advisory-only UI labels, no broker execution, no invented data, no silent forward-fill, no LLM/model/news/candle direct order authority, hard validation before scoring, unavailable providers/models return explicit unavailable/null states, and release-facing actions remain `hold`, `no_trade`, `add_candidate`, `trim_candidate`, `manual_review`.

### updatev2 Cross-Link Map

- `UPDATEV2-0010` underpins all provider, filing, ETF disclosure, candle and audit work.
- `UPDATEV2-0011`, `UPDATEV2-0021` and `UPDATEV2-0022` are integrity prerequisites before vendor/fallback sources are trusted.
- `UPDATEV2-0012`, `UPDATEV2-0013` and `UPDATEV2-0014` cover official stock filings and OAM discovery.
- `UPDATEV2-0015` through `UPDATEV2-0020` form the ETF disclosure stack.
- `UPDATEV2-0023` through `UPDATEV2-0025` are optional vendor enrichment providers.
- `UPDATEV2-0030` is the optional OHLCV fallback/discrepancy layer for Stooq, Twelve Data and Tiingo.
- `UPDATEV2-0026` is the low-authority candle context layer.
- `UPDATEV2-0027`, `UPDATEV2-0028` and `UPDATEV2-0029` cover UI workflow, audit export and finish-check discipline.
- Existing issues remain relevant: `ISSUE-0011`, `ISSUE-0012`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0036`, `ISSUE-0040`, `ISSUE-0045`, `ISSUE-0050`, `ISSUE-0055`, `ISSUE-0058`, `ISSUE-0060`, `ISSUE-0063`, `ISSUE-0064`.

## 2026-07-09 21 Trust-Critical Selected Release Issues

The user selected the following 21 issues for direct implementation as one staged release programme. They remain open until source, UI, tests, audit/export, docs, rebuild and browser/user-perspective smoke verification all pass. Cross-linked issues are not duplicates; their acceptance criteria are cumulative.

| Order | Issue | Priority | Selected implementation responsibility |
|---:|---|---|---|
| 1 | `ISSUE-0069` | P0 | **Closed 2026-07-11:** current package diagnostics, redaction, export, rebuild and Chrome evidence passed. |
| 2 | `UPDATEV2-0010` | P0 | Provider registry, capability probes, source authority and redacted Provider Status UI. |
| 3 | `UPDATEV2-0011` | P0 | Canonical identity resolver for ticker/ISIN/exchange/currency/share-class mapping. |
| 4 | `UPDATEV2-0021` | P0 | Conflict resolver so source disagreements are visible and never silently overwritten. |
| 5 | `UPDATEV2-0022` | P0 | **Closed 2026-07-11:** source IDs, authority policy, Evidence Ledger UI, tests, export and Chrome evidence passed. |
| 6 | `UPDATEV2-0012` | P0 | SEC EDGAR official statement importer and cached raw/clean statement inventory. |
| 7 | `UPDATEV2-0013` | P0/P1 | European ESEF/iXBRL local importer with source-verification confidence. |
| 8 | `UPDATEV2-0015` | P1 | ETF disclosure registry for factsheets, KIDs, prospectuses, reports and methodologies. |
| 9 | `UPDATEV2-0016` | P1 | ETF holdings normaliser with coverage and partial-data warnings. |
| 10 | `UPDATEV2-0017` | P1 | PRIIPs KID parser and cost/risk disclosure extraction where available. |
| 11 | `UPDATEV2-0019` | P1 | Index methodology importer and source mapping for ETF/index evidence. |
| 12 | `ISSUE-0025` | P1 | Free news and filings dashboard with context-only authority. |
| 13 | `ISSUE-0054` | P1/P2 | Point-in-time news validation and backtest rejection of ambiguous/current-only timestamps. |
| 14 | `ISSUE-0055` | P2 | Optional free provider stubs for SEC EDGAR, FRED, Stooq and RSS, disabled by default. |
| 15 | `ISSUE-0023` | P1 | Stock fundamentals hardening, missing-vs-bad distinction and source limitations. |
| 16 | `ISSUE-0067` | P0/P1 | Score history, metric history and expanded-row total-score mini charts. |
| 17 | `ISSUE-0047` | P1 | Feature-driver explanations for positive, negative, missing and low-authority evidence. |
| 18 | `ISSUE-0052` | P1 | Correlation clustering and factor/theme crowding warnings. |
| 19 | `ISSUE-0059` | P1/P2 | Broad and sector/theme-relative benchmark attribution. |
| 20 | `ISSUE-0064` | P1 | Friction-adjusted gross/net edge and edge-to-cost estimates. |
| 21 | `UPDATEV2-0028` | P0/P1 | **Closed 2026-07-11:** manifest, candle unavailable marker, conflicts, full holdings, export and Chrome evidence passed. |

Required durable stores:

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

Selected-issue close rule: none of these issues may be moved to `issues/closed.md` until the relevant source code is implemented, visible in the UI, covered by tests, included in audit/export where relevant, documented in `plan.md`, rebuilt with `.\scripts\build_windows.bat`, launched from the rebuilt app, smoke-tested at `http://127.0.0.1:8550/`, and limitations are recorded. Optional external data providers may close with explicit unavailable/null states only when the provider abstraction, UI status, tests and audit unavailable markers are implemented.

## ISSUE-0067 - Local score history and per-instrument score evolution mini charts

**Status:** Closed 2026-07-11; final evidence is recorded in `evidence/final/*-wave4.md`.  
**Type:** Scores / Storage / UI / Explainability  
**Priority:** P0/P1  
**Evidence grade:** High  
**Source URLs:** Latest user request; `plan.md`; related to `UPDATEV2-0022`, `ISSUE-0047` and `ISSUE-0034`.  
**Problem:** The app currently shows the latest ETF/stock scores, but the user also needs to see how metric scores, individual algorithm/model scores and total scores evolve over repeated runs. Without local score history, the app cannot show trend, deterioration, improvement, stability or "what changed" for scores.  
**Why it matters:** A single score snapshot is easy to overinterpret. Local score history makes the cockpit more useful for manual review and helps the user see whether evidence is strengthening or weakening.  
**Proposed implementation:** Persist every score run locally and add a compact score-evolution chart to each expanded ETF/stock row in the main Scores view.

Required storage:

```text
data/derived/score_history.parquet
data/derived/score_metric_history.parquet
```

Minimum `score_history` fields:

```text
run_id
run_started_at
run_completed_at
instrument_id
display_name
yahoo_ticker
asset_type
data_as_of_date
price_as_of_date
evidence_score_10
evidence_quality_10
risk_friction_10
final_combined_score_10
final_label
reason_short
reason_full
blocked_by
source_snapshot_hash
score_schema_version
```

Minimum `score_metric_history` fields:

```text
run_id
instrument_id
component_group
component_name
raw_metric_value
normalised_score_10
score_available
na_reason
source_dataset
as_of_date
freshness_status
authority_label
```

**Acceptance criteria:**  
- Each completed score-generation run appends a new local score snapshot for every scored ETF/stock.  
- Individual metric/component scores and total scores are persisted locally.  
- Re-running algorithms does not destroy previous score history.  
- Duplicate writes for the same `run_id` are prevented or idempotently replaced.  
- Expanded ETF/stock rows show a compact graph/sparkline of `final_combined_score_10` over time.  
- Expanded rows show latest score, previous score and delta when at least two snapshots exist.  
- If fewer than two snapshots exist, UI shows a clear "history will appear after another run" state.  
- Missing/invalid historical rows do not crash the Scores view.  
- Score history is informational only and cannot directly alter final actions.  
- Audit/export can include score history or a score-history summary where practical.  

**UI requirement:** Main Scores page expanded row for every ETF and stock must show a small total-score evolution chart, latest/previous/delta text and a short explanation that it tracks local historical score runs. The chart must fit inside the dropdown/expanded row without horizontal scrolling.  
**Tests required:**  
- Unit test for score history schema and append/idempotency.  
- Unit test for metric/component history records.  
- Integration test that a score run writes history for configured ETFs and candidate stocks.  
- UI/component test for no-history, one-snapshot and multi-snapshot states.  
- Regression test that score history cannot change current action labels.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep `Score History And Score Evolution Charts` section and current priority list updated.  
**Close criteria:** Common close criteria plus browser/user-perspective verification that each expanded instrument row displays the score-evolution mini chart.

## ISSUE-0069 - Single-file session action logging and diagnostics trace

**Status:** Closed 2026-07-11; final evidence is recorded in `evidence/final/*-wave4.md`.  
**Type:** Logging / Diagnostics / UI / Audit / Reliability  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** Latest 21 trust-critical implementation request; `plan.md`; linked to `ISSUE-0011`, `ISSUE-0012`, `UPDATEV2-0027`, `UPDATEV2-0028` and `ISSUE-0040`.  
**Problem:** The app has an activity log, but it does not yet provide one authoritative current-session trace that connects button clicks, action IDs, workflow steps, errors, generated files, exports and user-visible status. Without this trace, it is hard to prove whether a button really ran, diagnose failures, or include an auditable workflow trace in the evidence export.  
**Why it matters:** Trust-critical workflows need reproducible diagnostics. The user must be able to press a button, see progress, then inspect a durable trace showing what happened, which files were touched and whether any error was redacted safely.  
**Proposed implementation:** Add `logs/session.jsonl` as the single current-session log. Clear it only when a new app server process starts. Log `session_start` immediately. Use action IDs to connect button clicks, activity updates, backend service operations, exceptions, generated artefacts and audit exports. Redact secrets before writing. Logging failure must never crash the app.

Minimum event fields:

```text
timestamp_utc
timestamp_local
session_id
sequence_number
action_id
parent_action_id
event_type
severity
route
component
button_label
feature
operation
status
duration_ms
instrument_id
ticker
provider
model
input_summary
output_summary
row_counts
file_paths
checksums
warnings
blocked_by
user_message
exception_type
exception_message_redacted
traceback_fingerprint
schema_version
```

**Acceptance criteria:**  
- `logs/session.jsonl` is cleared when a new app server process starts and immediately records `session_start`.  
- Button clicks log before backend work begins.  
- Long-running actions log start, step updates, success/failure and output path.  
- Exceptions are logged with redacted messages and a traceback fingerprint, but no secrets.  
- API keys, tokens, passwords and `.env` values are never logged.  
- Diagnostics/Logs UI shows session ID, log path, recent events, warnings/errors and export path.  
- Audit/evidence export includes `session.jsonl` or an explicit unavailable marker.  
- Logging failures are swallowed and do not break app workflows.  

**UI requirement:** Diagnostics page must include a "Session log" or "Diagnostics trace" panel with current session ID, path, recent action rows, readable status and a clear note that secrets are redacted. Long-running buttons must continue to show visible progress in the shell and Activity Log.  
**Tests required:** Unit tests for session initialisation, clearing-on-start, append order, action ID propagation, redaction and logging-failure tolerance. Integration/UI smoke test that a button action writes at least start and success/failure events. Export test that `session.jsonl` is included or marked unavailable and contains no fake API key/token.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep the 21 trust-critical implementation programme and release gate current.  
**Close criteria:** Common close criteria plus browser/user-perspective verification that Diagnostics shows recent button/action events after a workflow button is pressed.

**2026-07-09 implementation note:** Core source/UI/export/test work is implemented: `logs/session.jsonl`, session start reset, redaction, Diagnostics session-log panel, navigation/activity logging and audit export inclusion. Rebuilt-app smoke verified Diagnostics recent events. Keep open until every main workflow button has complete action-ID coverage, generated-file trace coverage and browser smoke evidence under the common close criteria.

## UPDATEV2-0010 - Provider registry, capability probes and source authority model (original update ISSUE-0010)

**Status:** Closed 2026-07-11; final evidence is recorded in `evidence/final/*-wave4.md`.  
**Type:** Providers / Evidence Integrity  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `C:\Users\thor2\Downloads\updatev2.md`; yfinance, SEC EDGAR, ESEF, FMP, Alpha Vantage, Finnhub, Stooq, Twelve Data and Tiingo sources listed in `REPORT.md`.  
**Problem:** The app is moving from yfinance-only evidence into official filings, vendor APIs, ETF disclosures and candle evidence. Without a provider registry and source authority model, the app cannot safely decide whether a source is official, vendor-normalised, partial, stale, forbidden, rate-limited or context-only.  
**Why it matters:** Every later provider/importer/scoring feature depends on source identity, authority, limits and entitlement status.  
**Proposed implementation:** Extend `configs/data_providers.yaml`; add provider capability model; add `probe_capabilities()` to every provider; add `source_authority` enum; store `data/clean/provider_probe_results.parquet`; add Provider Status UI; include provider status in audit packet.  
**Acceptance criteria:** Missing API keys do not crash; disabled providers stay disabled; provider capability must be `ok` before scoring use; API keys are never logged/exported; UI shows provider state and last probe result; audit packet includes provider status.  
**UI requirement:** Provider Status page/panel with enabled/disabled state, API-key redaction, capabilities, probe result, quota/rate budget and last successful import.  
**Tests required:** Mock provider OK, forbidden, rate-limited, missing API key, config redaction and probe result storage.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve provider strategy and source authority ladder.  
**Close criteria:** Common close criteria plus audit packet provider manifest.

## UPDATEV2-0011 - Symbol/ISIN/exchange identity resolver (original update ISSUE-0011)

**Status:** Open  
**Type:** Data Integrity  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; `Thor2709/CrossCompatibleInvestmentApp` modules `exchange_support.py` and `yahoo_finance.py`.  
**Problem:** European stocks/ETFs often have multiple tickers, exchange suffixes, trading currencies and share classes.  
**Why it matters:** Multiple providers cannot be reconciled safely without canonical identity and warnings.  
**Proposed implementation:** Add `services/instrument_identity.py`; port/adapt old-app symbol/ISIN/exchange warning ideas; store canonical identity with `instrument_id`, ISIN, ticker, exchange, MIC, currency, name, issuer, asset type, share class, provider symbol map, confidence and warnings.  
**Acceptance criteria:** Ticker/ISIN mismatch triggers manual review; exchange/currency variants visible; provider-specific symbols stored; ETF share classes are not merged incorrectly; audit packet includes identity warnings.  
**UI requirement:** Instrument Detail and Data Health show identity confidence, mappings and warnings.  
**Tests required:** Yahoo suffix mapping, ISIN/ticker mismatch, ETF multi-listing, unknown exchange and manual override.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep identity resolver as Slice A integrity prerequisite.  
**Close criteria:** Common close criteria plus conflict display in UI.

## UPDATEV2-0012 - SEC EDGAR official statement importer (original update ISSUE-0012)

**Status:** Open  
**Type:** US Filings / Statements  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; https://www.sec.gov/search-filings/edgar-application-programming-interfaces  
**Problem:** US stock fundamentals need official statements; vendor fundamentals must not be highest authority.  
**Why it matters:** SEC EDGAR provides no-key official submissions and XBRL facts.  
**Proposed implementation:** Add `providers/sec_edgar_provider.py`, CIK resolver, raw JSON cache, statement fact normaliser, `data/clean/statement_facts.parquet` and Filings & Statements UI inventory.  
**Acceptance criteria:** Works without API key; raw JSON cached; taxonomy, concept, unit, dates, form and accession stored; SEC official facts outrank vendor facts; missing facts are not invented; audit packet includes SEC source IDs and mappings.  
**UI requirement:** Filings & Statements page showing SEC import status, filings, facts and mapping warnings.  
**Tests required:** Mock submissions JSON, companyfacts JSON, concept/unit/date mapping, duplicate facts and custom concepts stored but not auto-mapped.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve SEC as P0 official US source.  
**Close criteria:** Common close criteria plus offline cached import fixture.

## UPDATEV2-0013 - European ESEF/iXBRL filing importer (original update ISSUE-0013)

**Status:** Open  
**Type:** European Filings  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; https://www.esma.europa.eu/issuer-disclosure/electronic-reporting; https://www.xbrl.org/the-standard/what/ixbrl/  
**Problem:** European investing is core; ESEF/iXBRL is the European analogue to structured official filings.  
**Why it matters:** Vendor fundamentals cannot substitute for official European filings.  
**Proposed implementation:** Add `providers/eu_esef_provider.py`, manual ESEF ZIP/XHTML import, Arelle or equivalent parser evaluation, `services/ixbrl_parser.py`, `services/ifrs_statement_mapper.py`, raw storage under `data/raw/filings/eu_esef/`, facts in `data/clean/statement_facts.parquet` and parse warnings.  
**Acceptance criteria:** Manual ESEF import works offline; raw filing preserved with checksum; XHTML/iXBRL facts extracted where parseable; IFRS concepts map only when clear; extensions retained and warned; official ESEF facts outrank vendor data.  
**UI requirement:** Filings & Statements import flow and parse/mapping warning panel.  
**Tests required:** Minimal iXBRL fixture, missing taxonomy package, duplicate facts, extension concepts and canonical IFRS mapping.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve ESEF manual importer as P0/P1.  
**Close criteria:** Common close criteria plus audit export of ESEF source/facts.

## UPDATEV2-0014 - France DILA and Netherlands AFM OAM discovery adapters (original update ISSUE-0014)

**Status:** Open  
**Type:** European Filings / Discovery  
**Priority:** P1  
**Evidence grade:** Moderate/High  
**Source URLs:** `updatev2.md`; https://www.data.gouv.fr/fr/dataservices/api-info-financiere/; https://www.afm.nl/en/sector/registers/meldingenregisters/financiele-verslaggeving  
**Problem:** Before ESAP is mature, European filing discovery requires national OAM/regulator portals.  
**Why it matters:** France and Netherlands are practical first discovery targets.  
**Proposed implementation:** Add `providers/oam_france_dila_provider.py` and `providers/oam_netherlands_afm_provider.py`; support search by issuer, ISIN, date and document type; cache metadata/raw documents; mark source authority as `official_oam`.  
**Acceptance criteria:** Providers optional and disabled by default; discovery can run without breaking offline use; found documents added to filing registry; download/import path connects to ESEF parser where possible; UI shows document source and status.  
**UI requirement:** Filings & Statements provider discovery controls/status.  
**Tests required:** Mock France API response, AFM CSV/XML export, missing document and ambiguous issuer.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep ESAP as future, OAMs as current optional discovery.  
**Close criteria:** Common close criteria plus cached mocked discovery.

## UPDATEV2-0015 - ETF disclosure registry (original update ISSUE-0015)

**Status:** Open  
**Type:** ETF Evidence  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; UCITS, PRIIPs, SFDR sources listed in `REPORT.md`.  
**Problem:** ETF filings are a document stack: prospectus, KID, reports, factsheet, holdings, methodology, SFDR and lending/collateral documents.  
**Why it matters:** ETF evidence cannot be price-only.  
**Proposed implementation:** Add `services/etf_document_registry.py`, `data/clean/fund_documents.parquet`, ETF Disclosures UI panel and document import controls.  
**Acceptance criteria:** Every ETF row shows document inventory; missing KID/factsheet/holdings/index docs visible; stale holdings cap evidence quality; document checksums/dates stored; audit packet includes inventory.  
**UI requirement:** ETF Disclosures page and Instrument Detail ETF document panel.  
**Tests required:** Complete docs, missing KID, stale holdings, duplicate document versions and bad date/checksum.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve ETF disclosure stack.  
**Close criteria:** Common close criteria plus audit inventory export.

## UPDATEV2-0016 - ETF holdings normaliser (original update ISSUE-0016)

**Status:** Open  
**Type:** ETF Evidence / Holdings  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; UCITS/ETF disclosure sources.  
**Problem:** yfinance top holdings are partial and inconsistent; issuer holdings should be preferred.  
**Why it matters:** ETF exposure quality depends on actual holdings.  
**Proposed implementation:** Add `services/fund_holdings_normalizer.py`; extend ETF holdings import; add sum-of-weights validation, partial/full holdings label and holdings confidence score.  
**Acceptance criteria:** Full holdings around 100% OK; partial top holdings labelled partial; stale holdings cap evidence quality; invalid weights block current exposure scoring; holdings feed Risk page underlying exposure.  
**UI requirement:** ETF Disclosures and Risk pages show holdings completeness/freshness/confidence.  
**Tests required:** CSV/XLSX fixture, partial top holdings, weight sum under 80%, weight sum over 105%, missing ISIN/ticker.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve holdings validation thresholds.  
**Close criteria:** Common close criteria plus source-backed exposure output.

## UPDATEV2-0017 - PRIIPs KID parser (original update ISSUE-0017)

**Status:** Open  
**Type:** ETF Evidence / Retail Product Disclosure  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R1286  
**Problem:** European retail ETFs have KIDs with standardised risk/cost/product evidence.  
**Why it matters:** KID is core disclosure evidence, but not holdings evidence.  
**Proposed implementation:** Add `services/priips_kid_parser.py`; extract product name, ISIN, manufacturer, SRI, costs, recommended holding period, scenarios and document date; store confidence/warnings.  
**Acceptance criteria:** KID fields appear in ETF Disclosures; missing KID for retail ETF triggers manual review; KID does not substitute for holdings/prospectus; KID feeds cost/risk evidence.  
**UI requirement:** ETF Disclosures KID section.  
**Tests required:** Text/PDF fixture, missing SRI, multiple languages and bad/unknown document date.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep KID as mandatory retail-product evidence.  
**Close criteria:** Common close criteria plus parsed KID audit fields.

## UPDATEV2-0018 - ETF prospectus, annual and half-year report parser (original update ISSUE-0018)

**Status:** Open  
**Type:** ETF Evidence / Fund Reports  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; https://eur-lex.europa.eu/eli/dir/2009/65/oj/eng  
**Problem:** UCITS prospectus and periodic reports are the closest ETF equivalents to stock filings.  
**Why it matters:** They contain legal structure, risk, portfolio, cost and fund-operation evidence.  
**Proposed implementation:** Add `services/fund_report_parser.py`; extract legal structure, domicile, depositary, auditor, share classes, replication, derivatives/lending/collateral, NAV, costs and breakdowns.  
**Acceptance criteria:** Annual/half-year report inventory visible; prospectus fields feed structure/risk scoring; annual report does not substitute for current holdings; conflicts with factsheet/KID flagged.  
**UI requirement:** ETF Disclosures report/prospectus section.  
**Tests required:** Simple PDF/text fixture, missing replication method, conflicting TER and multiple share classes.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve fund report parser scope.  
**Close criteria:** Common close criteria plus conflict reporting.

## UPDATEV2-0019 - Index methodology importer (original update ISSUE-0019)

**Status:** Open  
**Type:** ETF Evidence / Benchmark Methodology  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; index-provider methodology docs as imported by user/provider.  
**Problem:** ETF quality depends on index rules, not only current holdings.  
**Why it matters:** Methodology explains how the ETF should evolve.  
**Proposed implementation:** Add `providers/index_methodology_provider.py` and `services/index_methodology_parser.py`; store methodology provider, version/date, eligibility, weighting, rebalance/review frequency and cap/rule fields.  
**Acceptance criteria:** ETF row links to methodology; version/date tracked; missing methodology caps evidence quality; methodology-vs-holdings conflicts visible.  
**UI requirement:** ETF Disclosures methodology panel.  
**Tests required:** Methodology text fixture, missing date/version, unknown provider and conflicting index name.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve methodology as high-authority for target index rules.  
**Close criteria:** Common close criteria plus audit methodology record.

## UPDATEV2-0020 - SFDR disclosure parser (original update ISSUE-0020)

**Status:** Open  
**Type:** ETF Evidence / Sustainability Disclosure  
**Priority:** P1  
**Evidence grade:** Moderate/High  
**Source URLs:** `updatev2.md`; https://eur-lex.europa.eu/eli/reg/2019/2088/oj/eng  
**Problem:** SFDR Article 8/9 claims affect ETF mandate and risk.  
**Why it matters:** ESG/sustainability claims must be disclosed and checked for conflicts, but never treated as return alpha.  
**Proposed implementation:** Add `services/sfdr_parser.py`; add SFDR fields to `fund_documents` and ETF score components; add greenwashing/conflict warning.  
**Acceptance criteria:** SFDR status appears in ETF Disclosures; Article 8/9 without methodology/data-source disclosure warns; conflicting status triggers manual review; SFDR is not return alpha.  
**UI requirement:** ETF Disclosures SFDR panel and warning badges.  
**Tests required:** Article 8 fixture, Article 9 fixture, conflicting factsheet/prospectus status and missing periodic report.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve SFDR as mandate/disclosure evidence only.  
**Close criteria:** Common close criteria plus audit export.

## UPDATEV2-0021 - Source conflict resolver and canonical metric selector (original update ISSUE-0021)

**Status:** Open  
**Type:** Evidence Integrity  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`.  
**Problem:** Multiple providers will disagree.  
**Why it matters:** The app needs deterministic rules for official fact selection and conflict flags.  
**Proposed implementation:** Add `services/source_conflict_resolver.py`; add conflict rules by metric family; store `data/derived/source_conflicts.parquet`; add UI conflict badges; include conflict report in audit packet.  
**Acceptance criteria:** Official source wins over vendor source; material conflicts lower evidence quality or force manual review; conflict reason human-readable; no silent overwriting.  
**UI requirement:** Evidence Ledger, Filings & Statements, ETF Disclosures and Instrument Detail conflict badges.  
**Tests required:** SEC vs FMP revenue conflict, ESEF vs vendor net income conflict, ETF TER conflict, holdings sum conflict and duplicate facts.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve conflict severity and source ranking.  
**Close criteria:** Common close criteria plus conflict report export.

## UPDATEV2-0022 - Evidence ledger and score component audit trail (original update ISSUE-0022)

**Status:** Open  
**Type:** Audit / Scoring  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; CrossCompatibleInvestmentApp score snapshot patterns.  
**Problem:** The app needs to explain every score component with source, freshness, confidence, authority and conflict status.  
**Why it matters:** Score transparency is central to a trustworthy evidence cockpit.  
**Proposed implementation:** Add `services/evidence_ledger.py`; store `evidence_ledger.parquet` and `score_components.parquet`; require every score component to reference `source_id`; show source-backed UI breakdown; include ledger in audit packet.  
**Acceptance criteria:** Every Score UI component has source/provenance; missing source means not score-eligible; LLM audit has no executable authority; candle/news/community evidence visibly low-authority.  
**UI requirement:** Evidence Ledger page and expandable score-row source details.  
**Tests required:** Component with official source, component with missing source, low-authority component cap and audit export contains ledger.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve ledger schema.  
**Close criteria:** Common close criteria plus audit evidence ledger.

## UPDATEV2-0023 - FMP optional provider adapter (original update ISSUE-0023)

**Status:** Open  
**Type:** Vendor Providers  
**Priority:** P1  
**Evidence grade:** Moderate  
**Source URLs:** `updatev2.md`; https://site.financialmodelingprep.com/pricing-plans; https://site.financialmodelingprep.com/developer/docs  
**Problem:** FMP is useful for statement/reference fallback and coverage, but must be optional, rate-limited and vendor-normalised.  
**Why it matters:** Vendor enrichment is useful only when authority and conflict rules are enforced.  
**Proposed implementation:** Add `providers/fmp_provider.py`, endpoint budget tracking, `.env.example` placeholder, provider probe/UI status and `vendor_normalised` outputs.  
**Acceptance criteria:** Disabled without key; free budget respected; FMP cannot override SEC/ESEF/issuer official docs; licensing/data-display warning visible; raw JSON cached.  
**UI requirement:** Provider Status with FMP capability/quota/licence warning.  
**Tests required:** Mock statement, rate limit, missing key and conflict with SEC fact.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve FMP as optional vendor enrichment.  
**Close criteria:** Common close criteria plus no secret leakage.

## UPDATEV2-0024 - Alpha Vantage verification/fallback adapter (original update ISSUE-0024)

**Status:** Open  
**Type:** Vendor Providers  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** `updatev2.md`; https://www.alphavantage.co/support/  
**Problem:** Alpha Vantage can verify adjusted OHLCV but free limits are too small for broad refresh.  
**Why it matters:** It should be used only as selected-ticker fallback/discrepancy check.  
**Proposed implementation:** Add `providers/alpha_vantage_provider.py`; default call budget 25/day; selected ticker/discrepancy use only; mark as `verification_fallback`.  
**Acceptance criteria:** Disabled without key; cannot broad-refresh 19-row universe by default on free tier; adjusted/raw method displayed; does not override yfinance unless configured and validated.  
**UI requirement:** Provider Status with Alpha Vantage quota/method.  
**Tests required:** Mock adjusted time series, call budget exhausted, missing key and discrepancy report.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve Alpha Vantage as fallback only.  
**Close criteria:** Common close criteria plus rate-limit enforcement.

## UPDATEV2-0025 - Finnhub experimental adapter with entitlement probes (original update ISSUE-0025)

**Status:** Open  
**Type:** Vendor Providers  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** `updatev2.md`; https://finnhub.io/docs/api/stock-candles; https://finnhub.io/docs/api/company-profile2; https://finnhub.io/docs/api/financials-reported; https://finnhub.io/pricing  
**Problem:** Finnhub may be useful, but free entitlement cannot be assumed.  
**Why it matters:** Every capability must be probed before use.  
**Proposed implementation:** Add `providers/finnhub_provider.py`; probe stock candle, profile, reported financials and news endpoints; store capability status; enable scoring only for `ok` capabilities.  
**Acceptance criteria:** Forbidden candles disable price capability; news context only; missing/forbidden endpoints do not crash; UI shows probe status.  
**UI requirement:** Provider Status with per-endpoint Finnhub probes.  
**Tests required:** Mock forbidden candle, OK profile, rate limit and missing key.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve Finnhub as experimental probe-required.  
**Close criteria:** Common close criteria plus unavailable-status handling.

## UPDATEV2-0026 - Candle feature/context/backtest module (original update ISSUE-0026)

**Status:** Open  
**Type:** Technical Analysis / OHLCV Features  
**Priority:** P1  
**Evidence grade:** Moderate  
**Source URLs:** `updatev2.md`; candle/backtest sources listed in `REPORT.md`.  
**Problem:** Candles are useful for OHLCV context and manual audit, but should be low authority.  
**Why it matters:** Named candle patterns have weak/mixed standalone evidence and OHLC backtests can be ambiguous.  
**Proposed implementation:** Add `services/candle_features.py`, `services/candle_templates.py`, `services/candle_backtest_safety.py`, `data/derived/candle_features.parquet` and Instrument Detail candle panel.  
**Acceptance criteria:** Candle features require valid OHLCV; candle contribution capped; named patterns do not directly trigger actions; backtests use next-bar execution; ambiguous OHLC paths reported.  
**UI requirement:** Instrument Detail Candle Evidence panel with latest candle summary, template, context filter status, confirms/warns/no-useful-signal, score cap, backtest count and ambiguity warning.  
**Tests required:** Valid OHLCV fixture, invalid high/low/open/close, gap/rejection templates, ambiguous stop/target same bar and score cap enforcement.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve candle low-authority cap.  
**Close criteria:** Common close criteria plus candle audit export.

## UPDATEV2-0027 - UI workflow/button reliability and progress indicators (original update ISSUE-0027)

**Status:** Open  
**Type:** UI / QA  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; latest user button reliability requests.  
**Problem:** Every important workflow must be visible, clickable and responsive.  
**Why it matters:** User trust depends on knowing whether a button is running, succeeded or failed.  
**Proposed implementation:** Add central workflow state model; wrap each button in start/running/success/error states; add progress messages; audit log entry for each run; UI smoke tests.  
**Acceptance criteria:** Refresh yfinance, Run algorithms, Run forecasting models, Show scores, Renew data and Export audit packet work or show clear error; new provider/filing/ETF imports show progress/result; no silent button clicks.  
**UI requirement:** Button contracts for Refresh yfinance data, Run algorithms, Run forecasting models, Show scores, Renew data, Import prices/factsheets/holdings/FX/manual notes/SEC/ESEF/ETF docs, Run provider probes, Export audit packet, Import external audit response and navigation buttons.  
**Tests required:** Workflow state unit tests, button smoke test, failure path test and audit log output.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep process-button progress wording examples.  
**Close criteria:** Common close criteria plus user-perspective Chrome/browser verification.

## UPDATEV2-0028 - Report/audit packet expansion for providers, filings, ETF docs and candles (original update ISSUE-0028)

**Status:** Open  
**Type:** Audit / Export  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`.  
**Problem:** External review is not reproducible unless the audit packet includes new evidence sources.  
**Why it matters:** Provider status, filings, ETF docs, conflicts and candle evidence must be exported.  
**Proposed implementation:** Extend audit packet builder; add manifest entries; include checksums/source authority; include human-readable Markdown summary.  
**Acceptance criteria:** Audit ZIP contains provider status, filing inventory, ETF document inventory, conflicts and candle evidence; external audit import remains non-executable.  
**UI requirement:** Audit page/export status shows included artefacts and output path.  
**Tests required:** Audit manifest, missing optional providers, conflict report export and large holdings export.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep REPORT/audit expansion requirements.  
**Close criteria:** Common close criteria plus inspected ZIP contents.

## UPDATEV2-0029 - Rebuild/test/update discipline automation (original update ISSUE-0029)

**Status:** Open  
**Type:** Dev Workflow  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** `updatev2.md`; user release-readiness requests.  
**Problem:** The user wants app rebuilds and issue updates every time implementation is finished.  
**Why it matters:** Issues cannot close without tests/rebuild evidence.  
**Proposed implementation:** Add `scripts/finish_patch.py` or `scripts/dev_finish_check.py`; run unit tests, smoke tests, UI route/button smoke where possible, rebuild package if app code changed and check report/open/closed issue updates.  
**Acceptance criteria:** Script reports pass/fail; rebuild attempted when needed; failure explicit; `REPORT.md`, `issues/open.md`, `issues/closed.md` instructions enforced; no issue closed without tests/rebuild evidence.  
**UI requirement:** Issue/QA Status page should show last test, last rebuild and last UI button pass when implemented.  
**Tests required:** Script dry-run, missing build dependency and failing unit test prevents close recommendation.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve finish-check discipline.  
**Close criteria:** Common close criteria plus finish-check output.

## UPDATEV2-0030 - Optional OHLCV fallback providers: Stooq, Twelve Data and Tiingo (original update ISSUE-0030)

**Status:** Open  
**Type:** Market Data Providers / OHLCV Fallback  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** `updatev2.md`; Stooq, Twelve Data and Tiingo provider documentation when configured.  
**Problem:** The app should not depend only on yfinance for OHLCV.  
**Why it matters:** Fallback providers improve resilience, cross-provider validation and candle-feature reliability when ticker resolution, split adjustment, volume, currency or missing bars differ.  
**Proposed implementation:** Add `providers/stooq_provider.py`, `providers/twelvedata_provider.py`, `providers/tiingo_provider.py` and tests; register in `configs/data_providers.yaml`; add capabilities for daily/intraday/adjusted OHLCV, API-key requirements, rate limits, source quality and free-tier viability; normalise to canonical OHLCV schema; store raw responses under `data/raw/providers/...`; write `data/clean/ohlcv_provider_comparison.parquet` and `data/derived/provider_discrepancy_report.parquet`.  
**Acceptance criteria:** yfinance remains default; manual CSV/Parquet remains first-class; Stooq can be used without API key where coverage works; Twelve Data/Tiingo disabled unless configured; keys never logged/exported/committed; rate limits enforced; provider outputs cannot silently overwrite higher-confidence data; discrepancies visible in UI, `REPORT.md` and audit packet; candle quality capped when providers disagree; missing/disabled providers return unavailable status.  
**UI requirement:** Provider Status shows enabled/disabled, latest probe, quota remaining where known, last successful refresh and discrepancy warnings.  
**Tests required:** Mock Stooq OHLCV, Twelve Data quota/rate limit, Tiingo missing key, canonical OHLCV normalisation, split mismatch, missing bars, discrepancy report and candle quality cap from disagreement.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Preserve fallback/discrepancy role, not official authority.  
**Close criteria:** Common close criteria plus audit discrepancy export.

## Cross-Link Map

- `ISSUE-0002` partial gap -> `ISSUE-0057`.
- `ISSUE-0003` partial gap -> `ISSUE-0052`, `ISSUE-0059`.
- `ISSUE-0004` partial gap -> `ISSUE-0049`, `ISSUE-0065`.
- `ISSUE-0005` partial gap -> `ISSUE-0050`, `ISSUE-0064`.
- `ISSUE-0006` partial gap -> `ISSUE-0010`.
- `ISSUE-0007` overlaps `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0055`, `ISSUE-0058`.
- `ISSUE-0008` overlaps `ISSUE-0015`, `ISSUE-0029`, `ISSUE-0056`, `ISSUE-0060`.
- `ISSUE-0009` partial gap -> `ISSUE-0058`.
- `ISSUE-0018` covers watchlists and candidate management.
- `ISSUE-0019` is the instrument-detail integration point for scores, news, forecasts, backtests, paper trading and journal data.
- `ISSUE-0028` overlaps `ISSUE-0049`, `ISSUE-0050`, `ISSUE-0065`.
- `ISSUE-0031` overlaps `ISSUE-0057`.
- `ISSUE-0032` overlaps `ISSUE-0066`.
- `ISSUE-0046` overlaps `ISSUE-0051`, `ISSUE-0063`.

## ISSUE-0007 - Add non-executable news/macro contradiction panel

**Status:** Open  
**Type:** News / Macro / Manual Notes / UI / Audit  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** `report.md`, Reddit AI investing tool/news API posts, common sources above.  
**Problem:** Manual notes and source credibility are not enough unless contradictions are visible in the app UI.  
**Why it matters:** News/macro context can reveal conflicts, but must never become trading authority.  
**Proposed implementation:** Add a contradiction engine and panels on Dashboard, Instrument Detail, News & Context and Audit export.  
**Acceptance criteria:** Show source, URL, provider, published date, ingested date, mapped instrument, credibility and promotional risk; flag positive trend with negative news, positive news with weak fundamentals, macro risk against exposure, source disagreement, bullish sentiment with deteriorating score and strong score with missing/stale news; enforce `executable_authority=false`; prove news cannot alter scores/actions.  
**UI requirement:** Dashboard, Instrument Detail, News & Context page and Audit export.  
**Tests required:** Unit tests for contradiction classification; regression tests proving news cannot change final score/action/risk gate/model authority; UI smoke for import/update status.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep cross-links to `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0055`, `ISSUE-0058`.  
**Close criteria:** Common close criteria plus browser verification of all contradiction views.

## ISSUE-0008 - Add strategy taxonomy and scope/rejection matrix

**Status:** Open  
**Type:** Strategy Governance / UI / Docs  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** `report.md`, basic algorithmic trading strategies post, RL warning post, common sources above.  
**Problem:** Future agents need explicit strategy boundaries to avoid risky or irrelevant strategy families.  
**Why it matters:** Prevents martingale/grid/RL/LLM-only/model-only trading from being reintroduced as supported behaviour.  
**Proposed implementation:** Add a Strategy Scope/System Map matrix with supported now, context-only, research-only and rejected categories.  
**Acceptance criteria:** Matrix classifies ETF trend/momentum, defensive rotation/watchlist, stock quality/momentum, stock value/momentum, long-only ranking, manual review, news/sentiment, LLM summaries, macro notes, manual notes, pair trading, futures, intraday, options, shorting, event-driven filings, alternative data, martingale, grid, RL agents, LLM-only management, model-only trading, screenshots and unvalidated sentiment. Each row shows reason, required data, tests, authority, UI visibility and score/paper/live authority.  
**UI requirement:** Strategy Scope or System Map page.  
**Tests required:** Strategy rejection tests and UI route smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep cross-links to `ISSUE-0015`, `ISSUE-0029`, `ISSUE-0056`, `ISSUE-0060`.  
**Close criteria:** Common close criteria plus tests proving rejected strategies cannot become supported.

## ISSUE-0010 - Add non-executable LLM thesis diary

**Status:** Open  
**Type:** LLM Audit / Decision Journal / Model Governance  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** `report.md`, frontier LLM paper portfolio post, common sources above.  
**Problem:** Existing LLM audit commentary does not persist instrument-specific thesis snapshots and later outcomes.  
**Why it matters:** LLM output must be auditable, non-executable and evaluated forward-only.  
**Proposed implementation:** Persist dated LLM thesis entries with prompt hash, model, sources, snapshots, summaries, score snapshot and later outcomes.  
**Acceptance criteria:** Record date/time, instrument, prompt hash, model name, input sources, source snapshot, thesis/risk/contradiction summaries, uncertainty, human review status, Evidence Score, Evidence Quality, Risk/Friction, final advisory label and 20/60/120 trading-day outcomes when available; enforce `executable_authority=false`; invalidate/unknown historical backtests using LLM output unless strictly forward-only.  
**UI requirement:** Instrument Detail and Audit pages.  
**Tests required:** Persistence tests; tests proving diary output cannot affect scores/actions/risk gates/trade proposals; audit export tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link from `ISSUE-0006` and `ISSUE-0030`.  
**Close criteria:** Common close criteria plus audit export of diary records.

## ISSUE-0011 - Full main-UI button reliability audit

**Status:** Open  
**Type:** UI / QA / Reliability  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; current source inspection.  
**Problem:** Main buttons may be dead, disconnected, silently failing or not updating the UI.  
**Why it matters:** The app cannot be release-ready if user-visible actions are unverified.  
**Proposed implementation:** Inventory every clickable action and test/fix each callback, visible response, output and error path.  
**Acceptance criteria:** Document page, label, intended function, callback, expected output, visible UI response, error handling and test coverage for Refresh yfinance data, Run algorithms, Run forecasting models, Show scores, Renew data, Export audit packet, Import external audit response, Settings save, navigation, expanded score rows, model/data refresh, News/Context, Watchlist and Paper Trading buttons where present. Fix dead/disconnected/blocked/silent/crashing/no-refresh buttons.  
**UI requirement:** All current and new pages.  
**Tests required:** Unit/callback tests, Flet startup tests and browser smoke tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record button inventory location and status.  
**2026-07-08 progress:** Main workflow buttons, sidebar navigation, Scores row expansion and Audit export were fixed and visually smoke-tested in system Chrome. Source audit found no remaining direct `page.go()` callbacks outside the navigation helper. Keep open because Settings save, Renew/import modal file-picker flows, import-audit invalid/valid cases and future roadmap pages still need repeatable exhaustive button inventory coverage.  
**Close criteria:** Common close criteria plus rebuilt app smoke proves main UI buttons visible and working.

## ISSUE-0012 - Add visible progress/status indicators for long-running actions

**Status:** Open  
**Type:** UI / UX / Reliability  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; current source inspection.  
**Problem:** Process buttons need visible step-level progress and persistent run logs.  
**Why it matters:** Users currently cannot reliably see whether a long operation is running, stuck, failed or completed.  
**Proposed implementation:** Add shared workflow status service, Activity Log/Run Log panel and persistent recent run log storage.  
**Acceptance criteria:** Every long-running action shows started state, current step, spinner/progress, success/failure, timestamp, output path and readable error; cover yfinance fetch, validation, algorithms, baseline, TimesFM, Toto, forecasts, scoreboard write, audit export, cache rebuild, notes/news imports, holdings/factsheet imports and macro/news refresh.  
**UI requirement:** Dashboard and a persistent Activity Log/Run Log panel.  
**Tests required:** Callback tests proving status fields update and persist; UI smoke for progress display.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record progress rule as release policy.  
**2026-07-08 progress:** Added persistent `ActivityEntry` state, dashboard Activity log, global progress strip, local `logs/activity_log.jsonl`, background dashboard workers, and progress/status messages for dashboard workflows, audit actions and settings save. Browser verified progress for refresh, algorithms and forecasts. Keep open until every future long-running workflow and import/news/macro/cache action has the same repeatable coverage.  
**Close criteria:** Common close criteria plus browser-observed progress for representative workflows.

## ISSUE-0013 - Rebuild package after every completed feature

**Status:** Open  
**Type:** Release / Packaging  
**Priority:** P0  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; `scripts/build_windows.bat`.  
**Problem:** Completed work is not release-ready unless the packaged app rebuilds and starts.  
**Why it matters:** The user opens launchers/packages, not only source tests.  
**Proposed implementation:** Add documented release gate and issue closure policy.  
**Acceptance criteria:** For every closed implementation issue, run relevant tests, full tests where needed, source smoke, rebuild package, start rebuilt app, verify local URL, verify main UI renders, verify workflow buttons exist and record command/result in `closed.md`.  
**UI requirement:** None beyond smoke evidence.  
**Tests required:** Build script smoke and local URL check.  
**Rebuild requirement:** This issue defines the rebuild requirement.  
**Plan.md update requirement:** Release gate policy recorded.  
**Close criteria:** Common close criteria plus one successful full rebuild after the gate is implemented.

## ISSUE-0014 - Add end-to-end workflow test

**Status:** Open  
**Type:** Testing / QA  
**Priority:** P0/P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** The core workflow lacks an end-to-end user-facing test.  
**Why it matters:** Unit tests do not prove the app starts, renders and workflows update visible state.  
**Proposed implementation:** Add scripted source and packaged smoke tests.  
**Acceptance criteria:** Verify app starts, main UI loads, refresh yfinance works or fails visibly, algorithms work, forecasting works or shows unavailable status, scores show, scoreboard writes, audit packet exports, pages navigate and rebuilt app starts after packaging.  
**UI requirement:** Main app routes and workflow controls.  
**Tests required:** E2E/smoke test script plus test-suite integration where feasible.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record command and expected pass/fail evidence.  
**2026-07-08 progress:** Manual browser smoke covered app load, refresh, algorithms, forecasts, scores navigation, row expansion and audit export; callback/unit coverage was added in `tests\test_flet_startup.py`. Keep open until this is converted into a repeatable scripted E2E command and packaged-app smoke.  
**Close criteria:** Common close criteria plus repeatable E2E command.

## ISSUE-0015 - Add app-level feature map / roadmap page

**Status:** Open  
**Type:** UI / Product  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Users and future agents need a visible map of implemented, partial, planned, research-only and rejected modules.  
**Why it matters:** Prevents confusion between backend artefacts, planned features and release-ready UI.  
**Proposed implementation:** Add Roadmap/System Map route backed by issue metadata.  
**Acceptance criteria:** Show Data, Watchlists, Scores, Instrument Detail, News & Context, Forecasts, Backtests, Portfolio/Risk, Audit, Paper Trading, Decision Journal and Future Broker Execution with status, safety authority and linked issues.  
**UI requirement:** Roadmap/System Map page.  
**Tests required:** Route render test and smoke test.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep module map in roadmap.  
**Close criteria:** Common close criteria plus visible route in navigation.

## ISSUE-0016 - Full product navigation redesign

**Status:** Open  
**Type:** UI / Product  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Current navigation lacks several required product sections.  
**Why it matters:** Important features must not exist only as scripts or backend diagnostics.  
**Proposed implementation:** Redesign navigation around Dashboard, Watchlists, Scores, Instrument Detail, Portfolio, Risk, News & Context, Forecasts, Backtests, Paper Trading, Decision Journal, Audit, Data & Models, Settings and Roadmap/System Map.  
**Acceptance criteria:** Clear navigation, clear "what to do first", each page explains what it does, each relevant page shows source/freshness/status and no important feature is backend-only.  
**UI requirement:** Main navigation/sidebar/mobile navigation.  
**Tests required:** Navigation smoke and responsive layout tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Update product sections list.  
**Close criteria:** Common close criteria plus browser walkthrough of every route.

## ISSUE-0017 - First-run onboarding and setup wizard

**Status:** Open  
**Type:** UX / Data  
**Priority:** P1  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt.  
**Problem:** The app should not crash or feel empty when no data/config exists.  
**Why it matters:** First-run setup should create valid local configuration without hidden assumptions.  
**Proposed implementation:** Add local setup wizard.  
**Acceptance criteria:** Ask base currency, region preference, ETF/stock/both, risk profile, target horizon and initial tickers; validate yfinance tickers; explain local-only storage and evidence vs financial advice; create starter configs if missing; no crash with no data.  
**UI requirement:** First-run wizard or Settings setup flow.  
**Tests required:** Empty-config startup tests and ticker validation tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record onboarding flow.  
**Close criteria:** Common close criteria plus clean first-run smoke.

## ISSUE-0018 - Watchlist and universe manager

**Status:** Open  
**Type:** Core Product / Data  
**Priority:** P0/P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; yfinance docs.  
**Problem:** Users need to manage the stocks/ETFs analysed by the app without editing files manually.  
**Why it matters:** Watchlists are the backbone for refresh, scores, forecasts and reports.  
**Proposed implementation:** Add local watchlist/universe CRUD with yfinance validation.  
**Acceptance criteria:** Add/remove/disable ticker; add notes, sector/theme/region, asset type and groups; validate ticker; show unresolved/invalid tickers; save locally; feed watchlists into refresh, scores, forecasts and reports.  
**UI requirement:** Watchlists page and Settings integration.  
**Tests required:** Persistence, validation, invalid ticker, scoring integration and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Link candidate management to watchlists.  
**Close criteria:** Common close criteria plus browser CRUD smoke.

## ISSUE-0019 - Proper instrument detail page

**Status:** Open  
**Type:** UI / Analysis  
**Priority:** P0/P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** The detail page does not yet serve as the full research hub for each instrument.  
**Why it matters:** Users need a clear drill-down from summary score to underlying evidence.  
**Proposed implementation:** Build a comprehensive instrument detail route with selected instrument state and evidence panels.  
**Acceptance criteria:** Show price history, latest price/date, Evidence Score, Evidence Quality, Risk/Friction, final label, reason, blocked gates, freshness, momentum, trend, relative strength, volatility, drawdown, liquidity/cost, alpha/beta/correlation, fundamentals, ETF holdings/exposure, news/context, forecast evidence, backtest trust, paper-trade history, decision journal entries and what changed since last run.  
**UI requirement:** Instrument Detail page linked from score rows.  
**Tests required:** Data assembly tests and UI smoke for at least one ETF and one stock.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record detail page as integration point.  
**Close criteria:** Common close criteria plus row-to-detail browser flow.

## ISSUE-0020 - Screener and filter system

**Status:** Open  
**Type:** Analysis / UI  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Users cannot quickly filter/sort the analysis universe by evidence dimensions.  
**Why it matters:** A research suite needs discovery tools, not only a static score list.  
**Proposed implementation:** Add screener over score/fundamental/risk/news/model/backtest fields.  
**Acceptance criteria:** Filter/sort by evidence score, quality, risk/friction, asset type, region, sector/theme, momentum, trend, volatility, drawdown, valuation, quality, liquidity, news conflict, freshness, model availability and backtest trust; saved filters; CSV export.  
**UI requirement:** Screener page or Scores page mode.  
**Tests required:** Filter logic, saved filter persistence, CSV export and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add to manual-suite roadmap.  
**Close criteria:** Common close criteria plus browser filter/export smoke.

## ISSUE-0021 - Portfolio construction and allocation sandbox

**Status:** Open  
**Type:** Portfolio / Risk  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Portfolio construction is still mostly context, not a sandbox.  
**Why it matters:** Users need manual allocation analysis without broker execution.  
**Proposed implementation:** Add local portfolio sandbox with target weights and risk views.  
**Acceptance criteria:** Create candidate portfolio, set targets, compare current vs target, show drift, sector/region/currency exposure, ETF overlap, estimated rebalance cost, risk contribution, correlation matrix and concentration warnings; no broker execution.  
**UI requirement:** Portfolio page sandbox mode.  
**Tests required:** Allocation math, validation, persistence and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Clarify no execution.  
**Close criteria:** Common close criteria plus sandbox create/edit smoke.

## ISSUE-0022 - ETF overlap and look-through exposure engine

**Status:** Open  
**Type:** ETF Analysis  
**Priority:** P1  
**Evidence grade:** Moderate/High  
**Source URLs:** Latest user prompt; yfinance docs.  
**Problem:** ETF overlap and partial holdings coverage are not fully visible.  
**Why it matters:** Users can unknowingly duplicate concentrated exposures across ETFs.  
**Proposed implementation:** Build overlap calculations from yfinance/manual holdings with coverage labels.  
**Acceptance criteria:** Use yfinance holdings when available and manual imports when available; detect overlapping holdings; show top overlapping companies; show issuer/company/sector/country/currency concentration; mark coverage full/partial/missing; never pretend partial holdings are complete.  
**UI requirement:** Risk, Portfolio and Instrument Detail.  
**Tests required:** Overlap math, partial coverage handling and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0021` and `ISSUE-0052`.  
**Close criteria:** Common close criteria plus overlap panel visible.

## ISSUE-0023 - Stock fundamentals quality module hardening

**Status:** Open  
**Type:** Stock Analysis  
**Priority:** P1  
**Evidence grade:** Moderate/High  
**Source URLs:** Latest user prompt; yfinance docs.  
**Problem:** yfinance fundamentals are partial and must not be treated as complete or fresh without checks.  
**Why it matters:** Missing fundamentals must be distinct from bad fundamentals.  
**Proposed implementation:** Harden fundamentals extraction, scoring eligibility and limitations.  
**Acceptance criteria:** Add valuation, profitability, leverage, growth and shareholder-return sections; sector-relative comparison where possible; stale/missing warnings; "do not score" if key data absent; show source and limitations.  
**UI requirement:** Instrument Detail and Screener.  
**Tests required:** Missing vs bad classification, yfinance fixture tests and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add to manual-suite roadmap.  
**Close criteria:** Common close criteria plus stock example visible.

## ISSUE-0024 - Earnings, dividends and event calendar

**Status:** Open  
**Type:** Context / Risk  
**Priority:** P1/P2  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt; yfinance docs.  
**Problem:** Upcoming events are not shown as context/risk.  
**Why it matters:** Users need to know when earnings, dividends or splits may affect interpretation.  
**Proposed implementation:** Add yfinance-backed event calendar where available.  
**Acceptance criteria:** Show upcoming earnings, ex-dividend/dividend dates, splits/actions and high-risk event warnings; do not use event data as direct score authority unless later validated; include in Instrument Detail.  
**UI requirement:** Instrument Detail and News & Context.  
**Tests required:** Event parsing, missing event handling and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record context-only authority.  
**Close criteria:** Common close criteria plus visible events or unavailable state.

## ISSUE-0025 - Free news and filings dashboard

**Status:** Open  
**Type:** News / Context  
**Priority:** P1  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt; yfinance docs; SEC EDGAR docs; FRED docs; Stooq; RSS sources.  
**Problem:** Free news/context is missing as a first-class dashboard.  
**Why it matters:** Users asked for free context without paid API dependency or score authority.  
**Proposed implementation:** Add yfinance news, RSS/manual import, optional SEC EDGAR/FRED/Stooq stubs and local storage.  
**Acceptance criteria:** Store raw and clean news locally; show source URL, timestamp, provider and credibility; news remains `executable_authority=false`; show contradiction panel; show news unavailable clearly if no source works.  
**UI requirement:** News & Context page, Dashboard digest and Instrument Detail.  
**Tests required:** Provider disabled state, manual/RSS import, provenance, non-authority regression and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0007`, `ISSUE-0054`, `ISSUE-0055`, `ISSUE-0058`.  
**Close criteria:** Common close criteria plus free-news workflow smoke.

## ISSUE-0026 - Macro regime dashboard

**Status:** Open  
**Type:** Macro / Risk  
**Priority:** P1/P2  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt; FRED docs; Stooq.  
**Problem:** Macro/regime context is not a complete dashboard with freshness/provenance.  
**Why it matters:** Market context helps interpretation but must remain low-authority/contextual.  
**Proposed implementation:** Add macro/regime page from yfinance proxies and optional FRED.  
**Acceptance criteria:** Show equity trend, bond/cash proxy trend, gold/defensive proxy trend, breadth, volatility proxy, optional FRED macro, inflation/rates context and regime label risk-on/neutral/defensive/stressed/unknown; every series shows source/freshness.  
**UI requirement:** Macro/Regime dashboard or Risk page section.  
**Tests required:** Proxy calculations, missing provider state and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record source/freshness policy.  
**Close criteria:** Common close criteria plus visible dashboard.

## ISSUE-0027 - Forecast lab page

**Status:** Open  
**Type:** Models / Forecasts  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; TimesFM/Toto docs.  
**Problem:** Forecast status and calibration are spread across diagnostics, not a usable lab.  
**Why it matters:** Forecasting models are low-authority and need transparent availability/performance display.  
**Proposed implementation:** Add Forecast Lab route with rerun/progress and model details.  
**Acceptance criteria:** Show model availability, horizon support, skipped horizons, latest forecast by model, calibration status, matured forecast performance, directional accuracy, MASE, coverage, why forecasts are low-authority, models cannot rescue weak deterministic evidence and rerun button with progress status.  
**UI requirement:** Forecasts page.  
**Tests required:** Availability, skipped model, calibration, non-rescue regression and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record low-authority model policy.  
**Close criteria:** Common close criteria plus forecast rerun smoke.

## ISSUE-0028 - Backtest lab upgrade

**Status:** Open  
**Type:** Backtest  
**Priority:** P0/P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; PBO/DSR research.  
**Problem:** Backtests need a release-grade lab with execution realism and trust diagnostics.  
**Why it matters:** Backtests can mislead without no-lookahead, cost, turnover, drawdown and overfitting warnings.  
**Proposed implementation:** Upgrade Backtests page and engine outputs.  
**Acceptance criteria:** Show strategy, benchmark, date range, trades/signals, equity curve/table, drawdown, costs, turnover, hit rate/payoff, sensitivity, overfitting warning, walk-forward periods, not-enough-data, no same-bar execution, no look-ahead and no silent forward-fill.  
**UI requirement:** Backtests page.  
**Tests required:** No-lookahead, no same-bar, cost inclusion, missing data and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0049`, `ISSUE-0050`, `ISSUE-0065`.  
**Close criteria:** Common close criteria plus backtest lab browser smoke.

## ISSUE-0029 - Strategy template builder

**Status:** Open  
**Type:** Strategy / UI  
**Priority:** P1/P2  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt; algorithmic strategy posts.  
**Problem:** Strategy templates exist as artefacts but not as a user-configurable builder.  
**Why it matters:** Users need transparent templates, not hidden blends.  
**Proposed implementation:** Add strategy template builder with safe long-only/context-only templates.  
**Acceptance criteria:** Templates for ETF dual momentum, trend-following, defensive rotation, stock quality momentum, stock value momentum, low-volatility watchlist, dividend/quality watchlist, news/context watchlist only and manual custom score blend; user can enable/disable templates and see matches.  
**UI requirement:** Strategy builder or Roadmap/System Map integration.  
**Tests required:** Template metadata, rejection boundaries, enable/disable persistence and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0008`.  
**Close criteria:** Common close criteria plus no rejected strategy support.

## ISSUE-0030 - Decision journal

**Status:** Open  
**Type:** Manual Workflow  
**Priority:** P0/P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; report evidence diary recommendations.  
**Problem:** Manual decisions are not persistently recorded with evidence snapshots.  
**Why it matters:** A manual research suite needs later review and learning.  
**Proposed implementation:** Add decision journal storage and UI.  
**Acceptance criteria:** Record date, instrument, decision type, thesis, evidence snapshot, score snapshot, risk snapshot, news snapshot, horizon, planned review date, invalidation criteria, manual notes and later outcome; visible in UI.  
**UI requirement:** Decision Journal page and Instrument Detail.  
**Tests required:** Persistence, snapshot immutability, outcome update and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Link to paper/LLM diary.  
**Close criteria:** Common close criteria plus create/view journal browser smoke.

## ISSUE-0031 - Paper trading module

**Status:** Open  
**Type:** Simulation  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; Engo/research evidence ladder.  
**Problem:** The app has no local paper portfolio or forward evidence tracking.  
**Why it matters:** Paper evidence must precede any future execution architecture.  
**Proposed implementation:** Add local paper-trading module with manual accept/reject only.  
**Acceptance criteria:** Create local paper portfolio; accept/reject proposals manually; record entry, size, price, thesis and evidence snapshot; track PnL, benchmark-relative result, drawdown, hit rate/payoff, open/closed paper positions; no real broker execution.  
**UI requirement:** Paper Trading page and Instrument Detail history.  
**Tests required:** Paper ledger, PnL, benchmark comparison, no broker calls and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0057`.  
**Close criteria:** Common close criteria plus local paper trade smoke.

## ISSUE-0032 - Future broker-execution architecture document only

**Status:** Open  
**Type:** Architecture / Safety  
**Priority:** P2  
**Evidence grade:** High  
**Source URLs:** Latest user prompt; community execution risk scans.  
**Problem:** Future execution safety needs documented architecture, but no live trading now.  
**Why it matters:** Prevents accidental implementation of unsafe broker automation.  
**Proposed implementation:** Add architecture document and Roadmap/System Map section, not execution code.  
**Acceptance criteria:** Document broker abstraction, paper mode first, order preview, explicit confirmation, max order value/position size/daily turnover/daily loss/drawdown kill switch, cooldowns, market-hours checks, stale-data block, news/event block, audit log, emergency disable, no LLM authority and no model-only authority.  
**UI requirement:** Roadmap/System Map future-only section.  
**Tests required:** Strategy rejection/static tests proving live broker execution is absent.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0066`.  
**Close criteria:** Common close criteria plus no live execution code path.

## ISSUE-0033 - Alerts and review reminders

**Status:** Open  
**Type:** UX  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt.  
**Problem:** Users lack local reminders for important review events.  
**Why it matters:** Manual review workflows need timely attention without external notifications.  
**Proposed implementation:** Add local UI alerts and review reminder state.  
**Acceptance criteria:** Alert for material score change, rank change, news conflict, stale data, model forecast failure, review date arrived, risk limit breached and target drift exceeded; no external notification unless later implemented.  
**UI requirement:** Dashboard digest, Activity Log and Instrument Detail.  
**Tests required:** Alert generation, dismissal/persistence and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add to UX roadmap.  
**Close criteria:** Common close criteria plus visible local alerts.

## ISSUE-0034 - What changed since last run page

**Status:** Open  
**Type:** UX / Analysis  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Users cannot quickly see what changed between runs.  
**Why it matters:** Change awareness is central to a manual evidence cockpit.  
**Proposed implementation:** Persist run snapshots and compare latest vs previous.  
**Acceptance criteria:** Compare score changes, rank changes, new/removed warnings, freshness changes, model availability changes, forecast changes, news changes, backtest trust changes and portfolio risk changes; show plain-English summary.  
**UI requirement:** What Changed page/panel and Dashboard digest.  
**Tests required:** Snapshot diff tests and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add to manual-suite roadmap.  
**Close criteria:** Common close criteria plus diff visible after two runs.

## ISSUE-0035 - Data health centre

**Status:** Closed 2026-07-10; see `evidence/final/issues/ISSUE-0035.json` and `issues/closed.md`.  
**Type:** Data Quality / UI  
**Priority:** P0/P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Data status is scattered and not a central health centre.  
**Why it matters:** Scores are only trustworthy if provenance, freshness and failures are visible.  
**Proposed implementation:** Add Data Health route aggregating all dataset/status inventories.  
**Acceptance criteria:** Show price, FX, ETF holdings, fundamentals, news, macro, forecast and backtest cache status; checksum/provenance; stale/missing warnings; last successful run and last failed run.  
**UI requirement:** Data Health Centre page and Dashboard summary.  
**Tests required:** Inventory aggregation, missing/stale states and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record as Phase C priority.  
**Close criteria:** Common close criteria plus data health browser smoke.

## ISSUE-0036 - Import/export centre

**Status:** Open  
**Type:** Data / UX  
**Priority:** P1/P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Latest user prompt.  
**Problem:** Imports/exports are split across dialogs/scripts.  
**Why it matters:** Users need a safe central workflow with validation before commit.  
**Proposed implementation:** Add Import/Export Centre route.  
**Acceptance criteria:** Import broker CSV, candidate CSV, manual notes, ETF holdings, news CSV/RSS list; export scoreboard, audit packet, watchlist, paper-trade journal, decision journal and plan/issues snapshot; all imports validate before commit.  
**UI requirement:** Import/Export Centre page.  
**Tests required:** Import validation, export path display, failure handling and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add to manual-suite roadmap.  
**Close criteria:** Common close criteria plus import/export browser smoke.

## ISSUE-0037 - Config editor UI

**Status:** Open  
**Type:** Settings  
**Priority:** P1/P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Latest user prompt.  
**Problem:** Important configuration still requires direct YAML editing.  
**Why it matters:** Safe local configuration needs validation and redacted secrets.  
**Proposed implementation:** Add config editor panels with validation before save.  
**Acceptance criteria:** Edit universe, watchlists, target weights, risk limits, costs/slippage, model settings, data providers, news/RSS sources, macro providers and paper settings; secrets redacted; validation required.  
**UI requirement:** Settings page or Config Editor page.  
**Tests required:** Validation, secret redaction, save/reload and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add to manual-suite roadmap.  
**Close criteria:** Common close criteria plus settings save smoke.

## ISSUE-0038 - Local database / storage migration plan

**Status:** Open  
**Type:** Architecture  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt.  
**Problem:** File-based storage may not scale to journals, paper trades and audit logs.  
**Why it matters:** Migration must be planned without breaking existing parquet/CSV exports.  
**Proposed implementation:** Write SQLite or DuckDB migration plan and schema.  
**Acceptance criteria:** Plan schema for instruments, prices, fundamentals, ETF holdings, news, forecasts, scores, decisions, paper trades and audit logs; preserve Parquet/CSV exports; do not break existing files.  
**UI requirement:** Roadmap/System Map architecture section.  
**Tests required:** Architecture validation/static checks if schemas are added.  
**Rebuild requirement:** Full release gate if UI/doc route changes.  
**Plan.md update requirement:** Record migration strategy.  
**Close criteria:** Common close criteria plus documented non-breaking migration plan.

## ISSUE-0039 - Performance and caching audit

**Status:** Open  
**Type:** Performance  
**Priority:** P1/P2  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Long workflows and model imports can freeze or slow the UI.  
**Why it matters:** A usable local app must remain responsive and explain slow steps.  
**Proposed implementation:** Add timing logs, lazy imports and safe cache invalidation review.  
**Acceptance criteria:** Startup remains fast; heavy model imports lazy; cache invalidation safe; long workflows do not freeze UI; progress updates during runs; timing logs exist; slow steps visible.  
**UI requirement:** Activity Log/Data Health diagnostics.  
**Tests required:** Startup timing smoke, lazy import/static test and cache invalidation tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add performance policy.  
**Close criteria:** Common close criteria plus recorded timing evidence.

## ISSUE-0040 - Error handling and recovery centre

**Status:** Open  
**Type:** Reliability  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Errors need readable UI recovery paths.  
**Why it matters:** Silent failures and raw stack traces make the app unreleasable.  
**Proposed implementation:** Add error service and Last Errors/Recovery panel.  
**Acceptance criteria:** Every failure shows readable error; last errors page/panel; stack traces only in developer mode; retry failed workflow; atomic data commits; failed import/model run cannot corrupt previous clean data/forecasts.  
**UI requirement:** Error/Recovery panel and Activity Log.  
**Tests required:** Failure injection tests and UI smoke for error display.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add recovery policy.  
**Close criteria:** Common close criteria plus representative failure smoke.

## ISSUE-0041 - Accessibility, responsive layout and table usability

**Status:** Open  
**Type:** UI Quality  
**Priority:** P1/P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Latest user prompt.  
**Problem:** The UI needs responsive and accessible table/navigation behaviour.  
**Why it matters:** Dense financial UI must remain readable and navigable.  
**Proposed implementation:** Audit and improve layouts, labels, search/sort and keyboard support where feasible.  
**Acceptance criteria:** Desktop and narrow/mobile layout work; tables sort/search where appropriate; readable light/dark mode; controls have labels/tooltips; keyboard navigation where feasible; UI does not rely only on colour.  
**UI requirement:** All pages.  
**Tests required:** Responsive smoke, visual checklist and locator tests where possible.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Record UI quality gate.  
**Close criteria:** Common close criteria plus visual smoke evidence.

## ISSUE-0042 - Charts, tables and CSV export improvements

**Status:** Open  
**Type:** UI / Export  
**Priority:** P1/P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Latest user prompt.  
**Problem:** Major analytical tables need better charts and export paths.  
**Why it matters:** Users need inspectable local evidence and portable outputs.  
**Proposed implementation:** Add charts/tables and CSV export actions across major pages.  
**Acceptance criteria:** Price chart or recent price table per instrument; equity curve/drawdown chart or table in Backtests; CSV export from every major table; export paths shown; export failures visible.  
**UI requirement:** Instrument Detail, Backtests, Scores, Data Health and portfolio/risk tables.  
**Tests required:** Export tests and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add export UX policy.  
**Close criteria:** Common close criteria plus representative CSV export smoke.

## ISSUE-0043 - User manual, glossary and in-app explanations

**Status:** Open  
**Type:** Documentation / UX  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt.  
**Problem:** Users need clear explanations of scores, authority and limitations.  
**Why it matters:** The app must be simple and transparent despite advanced metrics.  
**Proposed implementation:** Add in-app help/glossary content.  
**Acceptance criteria:** Explain every score, authority level and `N/A`; glossary for alpha, beta, drawdown, PBO, deflated Sharpe, MASE, calibration, slippage and edge-to-cost; in-app help text on each page.  
**UI requirement:** Help/glossary panel and page-level help.  
**Tests required:** Help route render and content smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add documentation strategy.  
**Close criteria:** Common close criteria plus visible glossary.

## ISSUE-0044 - Backup, restore, version and changelog

**Status:** Open  
**Type:** Reliability / Release  
**Priority:** P1/P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Latest user prompt.  
**Problem:** Users need local backup/restore and release metadata.  
**Why it matters:** Local data/configs are valuable and must be recoverable.  
**Proposed implementation:** Add backup/restore workflow and version/changelog display.  
**Acceptance criteria:** Backup local data/configs; restore local data/configs; show app version, changelog, last rebuild timestamp and current data folder; add packaged-app update workflow plan.  
**UI requirement:** Settings or Data Health/Import Export page.  
**Tests required:** Backup/restore dry-run tests and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add release metadata policy.  
**Close criteria:** Common close criteria plus backup/restore smoke.

## ISSUE-0045 - UI semantic locators and visual smoke tests

**Status:** Open  
**Type:** Testing / Flet UI  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Latest user prompt.  
**Problem:** Browser automation is limited without stable locators and visual smoke coverage.  
**Why it matters:** UI claims need user-point-of-view verification.  
**Proposed implementation:** Add stable keys/semantic labels where Flet allows and a visual smoke checklist/test.  
**Acceptance criteria:** Test dashboard loads, navigation, main workflow buttons, expanded score rows and export buttons; record limitation if Flet canvas prevents semantic locators.  
**UI requirement:** All main pages.  
**Tests required:** Flet startup, browser/local URL smoke and screenshot/visual checklist.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add UI smoke gate.  
**2026-07-08 progress:** Visual screenshot smoke was performed with system Chrome and the in-app browser. Flet web exposes minimal semantic DOM for this canvas-style UI, so coordinate/screenshot verification remains necessary until explicit semantic locator support is added where feasible.  
**Close criteria:** Common close criteria plus repeatable smoke result.

## ISSUE-0046 - Monthly decision template: basket vs benchmark vs cash

**Status:** Open  
**Type:** Strategy Template / Portfolio Context  
**Priority:** P1/P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Monthly decision Reddit post; common sources above.  
**Problem:** Monthly basket decision workflows are not formalised.  
**Why it matters:** Users need benchmark/cash context and operational assumptions.  
**Proposed implementation:** Add monthly decision template as advisory context.  
**Acceptance criteria:** Monthly rebalance cadence, basket vs benchmark vs cash proxy, next-session execution assumption, sector/theme concentration, young/noisy live/paper warning, benchmark-relative and cash-relative return and no direct buy/sell wording.  
**UI requirement:** Strategy templates, Portfolio and Backtests.  
**Tests required:** Template output, benchmark/cash comparison and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0051`, `ISSUE-0063`.  
**Close criteria:** Common close criteria plus visible monthly template.

## ISSUE-0047 - Feature-driver explanations for every evidence component

**Status:** Open  
**Type:** Explainability / UI  
**Priority:** P1  
**Evidence grade:** Moderate  
**Source URLs:** Report and user simplicity requests.  
**Problem:** Scores need machine-readable and human-readable drivers.  
**Why it matters:** Users need to know why an instrument received each score.  
**Proposed implementation:** Create component driver table and UI sections.  
**Acceptance criteria:** Table fields `instrument`, `component`, `raw_metric`, `normalised_score`, `direction`, `authority`, `driver_text`, `source_dataset`, `as_of_date`, `freshness_status`; show top positive, top negative, missing/N/A, low-authority and stale/partial drivers.  
**UI requirement:** Scores and Instrument Detail.  
**Tests required:** Driver generation, missing/stale classification and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Add explainability policy.  
**Close criteria:** Common close criteria plus driver display per component.

## ISSUE-0048 - Strategy complexity and overfitting penalty metadata

**Status:** Open  
**Type:** Backtest / Strategy Governance / Safety  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** PBO/DSR research; report.  
**Problem:** Complex strategies can overfit if complexity is hidden.  
**Why it matters:** Complex unvalidated templates should be demoted or warned.  
**Proposed implementation:** Add complexity metadata to every strategy template.  
**Acceptance criteria:** Store `n_features`, `n_parameters`, `n_thresholds`, `n_training_trials`, `n_selected_variants`, `lookback_windows_tested`, `selection_method`, `complexity_penalty_status`, `overfit_risk_label`; warn/demote complex unvalidated strategies.  
**UI requirement:** Strategy Scope, Backtests and Strategy Builder.  
**Tests required:** Metadata presence, penalty labels and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Link to backtest trust.  
**Close criteria:** Common close criteria plus visible complexity warning.

## ISSUE-0049 - Worst-day, loss-cluster and tail-event diagnostics

**Status:** Open  
**Type:** Backtest / Risk  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Report; execution/backtest critique sources.  
**Problem:** Hit rate/payoff diagnostics do not expose tail-event concentration.  
**Why it matters:** A few bad days can dominate strategy risk.  
**Proposed implementation:** Add tail/loss-cluster diagnostics to backtest outputs.  
**Acceptance criteria:** Show worst 1-day, 5-day, 10-day returns, worst drawdown window, loss clustering, largest negative contribution periods, whether losses occur during high-volatility/regime-stress periods and whether a few days explain most performance.  
**UI requirement:** Backtests and Instrument Detail.  
**Tests required:** Tail metric calculations and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0004`, `ISSUE-0028`, `ISSUE-0065`.  
**Close criteria:** Common close criteria plus visible tail diagnostics.

## ISSUE-0050 - Operational evidence panel for next-open/decision-price realism

**Status:** Open  
**Type:** Execution Realism / Backtest / UI  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** 10% in 9 days Reddit post; report.  
**Problem:** Cost stress exists, but decision-price and next-open realism are not shown.  
**Why it matters:** Same-bar or unrealistic execution assumptions can invalidate evidence.  
**Proposed implementation:** Add operational evidence panel and no same-bar enforcement display.  
**Acceptance criteria:** Show signal timestamp, decision price, next-open reference price, close-to-next-open gap, arrival price assumption, high/low spread proxy, open gap warning, execution delay assumption and same-bar execution avoided; same-bar execution forbidden.  
**UI requirement:** Backtests, Signals and Instrument Detail.  
**Tests required:** No same-bar tests, next-open reference calculations and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0005`, `ISSUE-0028`.  
**Close criteria:** Common close criteria plus operational panel visible.

## ISSUE-0051 - Cash proxy and risk-free/defensive comparison everywhere relevant

**Status:** Open  
**Type:** Benchmark / Portfolio / Backtest  
**Priority:** P1/P2  
**Evidence grade:** Moderate  
**Source URLs:** Report; Engo/basket comparison sources.  
**Problem:** Benchmark comparisons should also include cash/defensive context.  
**Why it matters:** Instruments should be compared to realistic alternatives, not only risky benchmarks.  
**Proposed implementation:** Add configurable cash and optional defensive proxies.  
**Acceptance criteria:** Show instrument return, benchmark return, cash proxy return, excess over benchmark, excess over cash and drawdown versus cash/benchmark; missing cash proxy shows `N/A`.  
**UI requirement:** Dashboard, Scores, Backtests, Portfolio and Instrument Detail.  
**Tests required:** Proxy config, missing proxy and calculation tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0046`.  
**Close criteria:** Common close criteria plus visible cash comparison.

## ISSUE-0052 - Correlation clustering and factor-crowding warnings

**Status:** Open  
**Type:** Portfolio / Risk / Diversification  
**Priority:** P1  
**Evidence grade:** Moderate/High  
**Source URLs:** Report; benchmark/regime critique sources.  
**Problem:** High-ranked instruments may all represent the same factor/theme bet.  
**Why it matters:** Apparent diversification can hide AI/semi/mega-cap tech crowding.  
**Proposed implementation:** Add rolling correlation clusters and factor/theme crowding warnings.  
**Acceptance criteria:** Compute rolling clusters where enough data exists; detect if top-ranked instruments are mostly one factor bet; detect AI/semi/mega-cap tech concentration; show cluster contribution to risk; add labels to Scores, Portfolio/Risk and Instrument Detail.  
**UI requirement:** Scores, Portfolio/Risk and Instrument Detail.  
**Tests required:** Cluster calculations, insufficient data handling and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0003`, `ISSUE-0059`.  
**Close criteria:** Common close criteria plus visible crowding label.

## ISSUE-0053 - What matters today digest

**Status:** Open  
**Type:** Dashboard / News / Workflow  
**Priority:** P1/P2  
**Evidence grade:** Moderate  
**Source URLs:** Latest user prompt; report.  
**Problem:** Dashboard lacks a concise daily digest of important changes and warnings.  
**Why it matters:** Users need a practical start point.  
**Proposed implementation:** Add context-only digest panel.  
**Acceptance criteria:** Summarise biggest score/rank changes, new/removed warnings, model failures, news/macro contradictions, instruments needing manual review, upcoming events, stale data and recent audit/export status; context only, no orders.  
**UI requirement:** Dashboard.  
**Tests required:** Digest generation and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0034`.  
**Close criteria:** Common close criteria plus dashboard digest visible.

## ISSUE-0054 - Point-in-time news/sentiment validation rules

**Status:** Open  
**Type:** News / Backtest Safety  
**Priority:** P1/P2  
**Evidence grade:** High  
**Source URLs:** News API Reddit post; report.  
**Problem:** News/sentiment without point-in-time metadata can create look-ahead bias.  
**Why it matters:** Context must be auditable and rejected from backtests if timestamps are invalid.  
**Proposed implementation:** Add strict news metadata validation.  
**Acceptance criteria:** Every item has `published_at`, `ingested_at`, `source_url`, `provider_name`, `instrument_mapping_method`, `available_at_decision_time`; backtests reject news/sentiment if published time missing, available time after decision time, timestamp ambiguous or provider gives current-only revised sentiment.  
**UI requirement:** News & Context, Audit and Backtests warnings.  
**Tests required:** Timestamp validation and backtest rejection tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0007`, `ISSUE-0025`.  
**Close criteria:** Common close criteria plus invalid news rejected visibly.

## ISSUE-0055 - Optional free provider research/stubs: SEC EDGAR, FRED, Stooq, RSS

**Status:** Open  
**Type:** Data Provider / Research / Optional Context  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** SEC EDGAR docs; FRED docs; Stooq; RSS; yfinance docs.  
**Problem:** yfinance remains default, but optional free context providers need a safe shape.  
**Why it matters:** Optional context should not become a required dependency or invented data.  
**Proposed implementation:** Add disabled-by-default provider stubs/status for EDGAR, FRED, Stooq and RSS.  
**Acceptance criteria:** yfinance remains default; no paid API required; optional providers disabled by default; provider status visible in UI; missing provider data shows unavailable, not invented.  
**UI requirement:** Data & Models, Settings, News & Context and Data Health.  
**Tests required:** Disabled provider state, config load and missing-data display.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0025`.  
**Close criteria:** Common close criteria plus provider status visible.

## ISSUE-0056 - Data-frequency suitability and unsupported-asset guardrails

**Status:** Open  
**Type:** Data Quality / Scope Governance  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** Futures data Reddit post; report.  
**Problem:** Unsupported assets/frequencies must not be silently scored as normal daily ETF/stock evidence.  
**Why it matters:** Futures, options, intraday and leveraged/inverse products require different risk/data handling.  
**Proposed implementation:** Add support matrix and guardrails.  
**Acceptance criteria:** Daily ETF/stock supported; intraday unsupported unless enabled later; futures/options research-only; crypto unsupported unless configured as proxy; leveraged/inverse ETFs high-risk; unsupported assets/frequencies not silently scored.  
**UI requirement:** Strategy Scope, Data Health and Instrument Detail warnings.  
**Tests required:** Unsupported asset rejection tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0008`, `ISSUE-0060`.  
**Close criteria:** Common close criteria plus unsupported examples blocked/warned.

## ISSUE-0057 - Paper/forward evidence diary

**Status:** Open  
**Type:** Evidence Tracking / Paper Trading Preparation  
**Priority:** P1  
**Evidence grade:** Moderate/High  
**Source URLs:** Engo research; report.  
**Problem:** Price-row maturity is not real forward/paper evidence.  
**Why it matters:** Backtests and model claims need out-of-sample observation labels.  
**Proposed implementation:** Record every generated proposal/signal snapshot and later outcomes.  
**Acceptance criteria:** Record date, instrument, template, score, evidence quality, risk/friction, model status, news context, proposed horizon, 20/60/120-day outcome, benchmark/cash comparison and thesis invalidation; UI states backtest-only, paper-observed young, paper-observed mature, manually accepted paper trade and later outcome.  
**UI requirement:** Paper Trading, Decision Journal, Instrument Detail and Scores.  
**Tests required:** Snapshot/outcome tests and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0002`, `ISSUE-0031`.  
**Close criteria:** Common close criteria plus forward diary visible.

## ISSUE-0058 - Closed-source/promotional-claim detector for imported notes

**Status:** Open  
**Type:** Manual Research / Source Credibility  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** Report; promotional/return screenshot Reddit sources.  
**Problem:** Current source credibility is basic and needs stronger promotional claim detection.  
**Why it matters:** Imported notes can include non-reproducible marketing claims.  
**Proposed implementation:** Extend manual note classifier and UI/audit badges.  
**Acceptance criteria:** Detect performance screenshot without methodology, DM/funnel language, closed-source claim, no benchmark, no drawdown, no cost/slippage, no sample size, no reproducible method and too-good-to-be-true return claim; visible in UI and audit export.  
**UI requirement:** News & Context, Data & Models, Audit and Instrument Detail.  
**Tests required:** Classifier tests, audit export tests and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0009`, `ISSUE-0007`.  
**Close criteria:** Common close criteria plus visible promotional labels.

## ISSUE-0059 - Benchmark-relative sector/theme attribution beyond single benchmark beta

**Status:** Open  
**Type:** Benchmark / Attribution / Risk  
**Priority:** P1/P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Report; benchmark/regime sources.  
**Problem:** Single broad benchmark beta is not enough for sector/theme-heavy instruments.  
**Why it matters:** Apparent alpha may be sector/theme beta.  
**Proposed implementation:** Add sector/theme benchmark mapping and attribution where configured.  
**Acceptance criteria:** Compare to broad benchmark and sector/theme benchmark; show broad alpha proxy and sector-relative alpha proxy; warn when top-ranked instruments are one theme; missing sector benchmark shows `N/A`.  
**UI requirement:** Scores, Risk and Instrument Detail.  
**Tests required:** Mapping, missing benchmark and attribution tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0003`, `ISSUE-0052`.  
**Close criteria:** Common close criteria plus sector-relative attribution visible.

## ISSUE-0060 - Strategy rejection tests

**Status:** Open  
**Type:** Test / Safety  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Report; rejected strategy sources.  
**Problem:** Rejected/risky strategy families need automated guardrails.  
**Why it matters:** Future changes must fail tests if they enable unsafe strategies.  
**Proposed implementation:** Add static/behavioural strategy rejection tests.  
**Acceptance criteria:** Tests fail if martingale/grid appears supported, RL execution agents are enabled, LLM-only trading can alter scores/actions, news sentiment directly alters final action, unsupported futures/options are scored as normal instruments or broker execution appears outside disabled future architecture.  
**UI requirement:** Strategy Scope shows rejected/research-only status.  
**Tests required:** This issue is primarily tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0008`, `ISSUE-0056`.  
**Close criteria:** Common close criteria plus rejection tests pass.

## ISSUE-0061 - Pair-trading/cointegration research-only module

**Status:** Open  
**Type:** Research  
**Priority:** P3  
**Evidence grade:** Low/Moderate  
**Source URLs:** Report; algorithmic trading strategy sources.  
**Problem:** Pair trading is sometimes useful but outside default long-only scoring.  
**Why it matters:** It requires stationarity, shorting/borrow/cost and regime instability handling.  
**Proposed implementation:** Document research-only module and keep it out of default scores.  
**Acceptance criteria:** Research only; document cointegration/stationarity requirements, borrow/shorting needs, costs and regime instability; no default score or trade signal.  
**UI requirement:** Strategy Scope research-only section.  
**Tests required:** Strategy rejection/scope tests.  
**Rebuild requirement:** Full release gate if UI docs change.  
**Plan.md update requirement:** Keep research-only status.  
**Close criteria:** Common close criteria plus no scoring integration.

## ISSUE-0062 - Triple-barrier and purged-CV research-only module

**Status:** Open  
**Type:** Research / ML Safety  
**Priority:** P3  
**Evidence grade:** Moderate  
**Source URLs:** Report; ML/backtest safety research.  
**Problem:** ML labelling techniques are useful but premature without enough data and classifier design.  
**Why it matters:** Avoid adding complex ML that looks scientific but leaks/overfits.  
**Proposed implementation:** Document requirements and keep research-only.  
**Acceptance criteria:** Document triple-barrier labels, purged cross-validation and embargo; do not implement ML classifier until enough data exists; add minimum sample requirements and leakage warnings.  
**UI requirement:** Strategy Scope research-only section.  
**Tests required:** Scope/rejection tests.  
**Rebuild requirement:** Full release gate if UI docs change.  
**Plan.md update requirement:** Keep research-only status.  
**Close criteria:** Common close criteria plus no classifier added.

## ISSUE-0063 - Close-based quality-momentum next-open template hardening

**Status:** Open  
**Type:** Strategy / Backtest / UI  
**Priority:** P1  
**Evidence grade:** Moderate/High  
**Source URLs:** Close-based quality momentum Reddit post; report.  
**Problem:** Quality-momentum templates need operational next-open assumptions.  
**Why it matters:** Close-based signals cannot use same-bar execution.  
**Proposed implementation:** Harden template metadata, scoring and audit assumptions.  
**Acceptance criteria:** Template uses close-based data only; execution assumption is next-open/next-period; costs/slippage configurable and stress-tested; quality and momentum sub-scores visible; forward/paper results labelled operational, not proof; audit export includes assumptions.  
**UI requirement:** Strategy Builder, Backtests and Instrument Detail.  
**Tests required:** No-lookahead, cost stress and template UI tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0046`, `ISSUE-0050`.  
**Close criteria:** Common close criteria plus template visible with assumptions.

## ISSUE-0064 - Friction-adjusted return estimate per evidence score

**Status:** Open  
**Type:** Scoring / Cost Realism  
**Priority:** P1  
**Evidence grade:** High  
**Source URLs:** Report; execution/friction sources.  
**Problem:** Cost stress exists but should be tied directly to each evidence score as gross/net edge.  
**Why it matters:** Users need cost-adjusted evidence, not only raw score.  
**Proposed implementation:** Add gross/net edge fields to score rows and UI.  
**Acceptance criteria:** Add `gross_expected_edge_bps`, `estimated_total_cost_bps`, `net_expected_edge_bps`, `edge_to_cost_ratio`, `cost_stress_scenario`; show cost-adjusted edge in UI.  
**UI requirement:** Scores, Instrument Detail and Audit export.  
**Tests required:** Cost-adjusted edge calculations and UI/export tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0005`, `ISSUE-0050`.  
**Close criteria:** Common close criteria plus visible net edge.

## ISSUE-0065 - Payoff-profile classification and risk/reward asymmetry display

**Status:** Open  
**Type:** Backtest / UI  
**Priority:** P2  
**Evidence grade:** Moderate  
**Source URLs:** Report; payoff diagnostics sources.  
**Problem:** Payoff metrics exist but need profile classification and clearer asymmetry display.  
**Why it matters:** Hit rate and payoff mean different things for trend and mean-reversion styles.  
**Proposed implementation:** Add payoff profile labels.  
**Acceptance criteria:** Display hit rate, payoff ratio and skew; label profile as trend-like, mean-reversion-like, mixed or insufficient data; warn where losses dominate wins; no recommendation purely from payoff profile.  
**UI requirement:** Backtests and Instrument Detail.  
**Tests required:** Classification tests and UI smoke.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Cross-link to `ISSUE-0004`, `ISSUE-0049`.  
**Close criteria:** Common close criteria plus payoff profile visible.

## ISSUE-0066 - Source-of-truth and reconciliation architecture for future execution

**Status:** Open  
**Type:** Architecture / Future Execution Safety  
**Priority:** P2  
**Evidence grade:** Moderate/High  
**Source URLs:** Community scan; report.  
**Problem:** Future execution architecture must account for broker state drift and partial fills before any live trading is considered.  
**Why it matters:** Paper/backtest/live states can diverge; websockets are not a source of truth.  
**Proposed implementation:** Document broker-state/reconciliation architecture only, no live broker execution now.  
**Acceptance criteria:** Document idempotent order IDs, broker reconciliation loop, partial-fill handling, cancellation handling, no retry storm, decimal money/quantity handling, source-of-truth state and audit log; no live broker execution now.  
**UI requirement:** Roadmap/System Map future-only section.  
**Tests required:** Static tests proving no broker execution path is enabled.  
**Rebuild requirement:** Full release gate if UI/docs change.  
**Plan.md update requirement:** Cross-link to `ISSUE-0032`.  
**Close criteria:** Common close criteria plus future-only architecture visible and no execution code enabled.

## ISSUE-0068 - Two-tier universe manager and provider policy editor

**Status:** Open  
**Type:** Universe / Data Providers / UI  
**Priority:** P0/P1  
**Evidence grade:** User requested  
**Source URLs:** User supplied 2026-07-09 two-tier stock/ETF universe request; `plan.md` two-tier universe policy.  
**Problem:** The two-tier universe is now config/CSV-driven, but future editing still requires manual file changes.  
**Why it matters:** The app should let the user manage primary multi-provider candidates separately from secondary yfinance-only candidates without breaking IDs, duplicates or provider policy.  
**Proposed implementation:** Add a Universe Manager UI that edits primary and secondary instruments with validation before saving.  
**Acceptance criteria:** Add/remove/disable instruments; edit name, ISIN, yfinance ticker, type, tier, data policy, currency, region, sector and theme; reject duplicate ISIN/ticker across tiers unless explicitly overridden; show pending-refresh status; never trigger refresh/algorithms/forecasts just because a config was edited.  
**UI requirement:** Add or extend Settings/Data & Models page with Primary tier and Secondary tier tables plus validation status.  
**Tests required:** Config load, duplicate rejection, pending row visibility, no automatic yfinance/model calls on save, and UI smoke tests.  
**Rebuild requirement:** Full release gate before close.  
**Plan.md update requirement:** Keep the two-tier universe policy current.  
**Close criteria:** Common close criteria plus visible tier editor and validated save workflow.

## 2026-07-09 Launcher, Sparebanken And Reliability Execution Status

This section records the hands-off run against `docs\superpowers\plans\2026-07-09-launcher-sparebanken-reliability-plan.md`. It does not close broad product issues unless their full close criteria are met.

### Selected 20 Non-Previous-21 Issues

| Issue | Status after run | Evidence / reason |
| --- | --- | --- |
| `UPDATEV2-0027` | Still open, partial | Launcher and workflow browser smoke improved, but full UI workflow reliability coverage is broader than this run. |
| `UPDATEV2-0029` | Still open, partial | Rebuild/test/update discipline was followed and helper smoke added, but durable cross-feature automation remains open. |
| `ISSUE-0011` | Still open, partial | Main workflow buttons are visible in browser evidence; not every current and future main-UI button has full browser proof. |
| `ISSUE-0012` | Still open, partial | Existing progress/status surfaces remain; launcher errors/readiness are clearer. Full long-action progress scope remains broader. |
| `ISSUE-0013` | Still open, run gate passed | This run rebuilt and smoke-tested successfully; the issue remains as a continuing release discipline requirement. |
| `ISSUE-0014` | Still open, partial | Added launcher/source/native smoke helpers; full end-to-end workflow test across data refresh, algorithms, forecasts and export remains open. |
| `ISSUE-0045` | Still open, partial | Browser screenshots passed. Flet semantic DOM locators remain weak and need dedicated accessibility/test hooks. |
| `ISSUE-0068` | Still open, partial | Grouping and settings copy now distinguish primary/secondary/Sparebanken, but the full universe manager/provider policy editor is not built. |
| `ISSUE-0018` | Still open, deferred | No watchlist/universe manager UI was implemented beyond grouped display. |
| `ISSUE-0035` | Closed 2026-07-10 | Data Health inventory, responsive UI, Dashboard summary, CSV export, final rebuild and Playwright visual/browser evidence passed; Computer Use limitation recorded. |
| `ISSUE-0040` | Still open, partial | Launcher errors are clearer, but a full error handling and recovery centre was not implemented. |
| `ISSUE-0039` | Still open, partial | Port/cache/rebuild reliability improved; no full performance and caching audit was completed. |
| `ISSUE-0036` | Still open, deferred | Import/export centre was not implemented in this run. |
| `ISSUE-0044` | Still open, partial | Versioned alternate portable output helps rebuild reproducibility; backup/restore/changelog UI remains open. |
| `ISSUE-0041` | Still open, partial | Visual layout was browser-checked; semantic accessibility and responsive table work remain open. |
| `ISSUE-0017` | Still open, deferred | First-run onboarding/setup wizard was not implemented. |
| `ISSUE-0019` | Still open, partial | Row expansion works; proper instrument detail page scope remains open. |
| `ISSUE-0042` | Still open, deferred | Charts/tables/CSV export improvements were not implemented. |
| `ISSUE-0056` | Still open, partial | yfinance symbol validation and unsupported/unknown states improved; full data-frequency guardrail scope remains open. |
| `ISSUE-0034` | Still open, deferred | What-changed-since-last-run page was not implemented. |

### Previous 21 Trust-Critical Issues

Four non-parser records currently meet their full evidence gates: `ISSUE-0035`, `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028`. Parser/provider-backed issues stay open unless the strict gates are met.

Keep open under the strict rule:

- `UPDATEV2-0012` SEC EDGAR official statement importer.
- `UPDATEV2-0013` European ESEF/iXBRL filing importer.
- `UPDATEV2-0015` ETF disclosure registry where real issuer-document workflows are still incomplete.
- `UPDATEV2-0017` PRIIPs KID parser.
- `UPDATEV2-0019` Index methodology importer.
- Any provider-backed workflow without real fixtures, parser tests, UI workflow, export/audit proof and browser smoke verification.

### Run-Specific Closures

Narrow run-specific closure records were added to `issues\closed.md` for:

- `RUN-CLOSED-2026-07-09-LAUNCHER`
- `RUN-CLOSED-2026-07-09-SPAREBANKEN-DATA`
- `RUN-CLOSED-2026-07-09-SPAREBANKEN-UI`

Post-review launcher evidence was completed on 2026-07-10. The narrow launcher record remains closed after a dual-lock stress rebuild and packaged browser smoke. Four issue-specific records were also closed with checksum-backed dossiers under `evidence\\final\\issues\\`; all remaining selected and parser/provider records retain the statuses above.

### Verified Implementation Closures - 2026-07-10

The following canonical issue sections are superseded by the evidence-backed closure records in `issues\\closed.md`:

- `ISSUE-0035` - data health centre and Dashboard summary.
