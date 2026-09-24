# AI Evidence Cockpit Plan

> **Historical planning record.** Preserve this file for research and
> traceability; it is not current architecture or status authority. See the
> [current SDD](docs/architecture/SDD.md), [canonical registry](issues/issue_registry.json),
> [programme roadmap](docs/product-completion/programme/roadmap.md), and active
> [batch plans](plans/).

This root plan is synchronised with `issues/open.md` and `issues/closed.md`.

## Product Objective

Build a local-first ETF and stock evidence cockpit. The default workflow remains simple:

1. Refresh yfinance data.
2. Run algorithms.
3. Run forecasting models.
4. Show individual x/10 scores.
5. Show a final combined advisory decision.

The app is not a broker bot, not a financial adviser and not an autonomous LLM trading system. It should become a reliable manual stock/ETF research suite before paper trading, and paper trading must prove forward evidence before any future trade-ticket or broker-execution architecture is considered.

## Core Rules

- yfinance is the default market-data source.
- Normal startup must not require internet, API keys or paid services.
- Missing/stale data stays visible as `N/A`, warning, blocked or manual review.
- Do not invent prices, holdings, fundamentals, news, FX or model outputs.
- Do not silently forward-fill important missing values.
- Optional TimesFM/Toto/local model evidence is low-authority unless generated, validated and calibrated locally.
- LLMs may explain and audit only. They must not calculate metrics, change scores, bypass gates or alter final actions.
- News, sentiment and thesis notes are non-executable context only.
- Preserve the three-score model: Evidence Score, Evidence Quality and Risk/Friction.
- Every user-facing feature must be visible in the app UI, have status/progress where relevant and be verified from the user's point of view before its issue is closed.
- Live automatic buy/sell is not implemented now and remains disabled until a separate future approval.

## Current Implemented Baseline

- yfinance-backed configured ETF and candidate-instrument refresh.
- Simple expandable score list with x/10 component scores.
- Advisory-only action labels.
- Nullable optional model forecasts.
- Initial calibration, market regime, portfolio-fit and strategy-template artefacts.
- Evidence maturity and sanity-warning fields for simple score rows.
- Benchmark attribution fields for configured ETFs.
- Backtest payoff diagnostics paired with hit-rate display.
- Low/base/high cost stress diagnostics for generated signals.
- Explicit model/backtest validity and contamination-risk fields.
- Source-credibility metadata for manual research notes.
- Scoreboard parquet/CSV/JSON export.
- Audit packet expansion with derived artefacts.
- Existing tests for simple score conversion, thresholds, missing model forecasts, candidate scoring, calibration, regime and strategy templates.

## 2026-07-09 21 Trust-Critical Implementation Programme

This section is the active release programme for moving the cockpit from a simple yfinance scoring UI into a trust-critical local evidence cockpit. The selected issues are not closed until source, UI, tests, audit/export, rebuild and user-perspective smoke verification all pass.

### Release posture

- The app stays local-first, advisory-only and manual-review focused.
- No automatic broker execution is allowed.
- No invented prices, fundamentals, ETF holdings, filings, documents, news, forecasts, score components or source dates are allowed.
- No silent important forward-fill is allowed.
- LLM, model, news, candle and source-context evidence cannot directly change final actions.
- Weak, stale, incomplete or conflicted evidence defaults to `no_trade` or `manual_review`.
- Official filings, issuer documents and regulator sources outrank vendor/yfinance data when they are explicitly available and identity-matched.
- yfinance remains the default market-data backbone and must be marked as lower-authority vendor evidence.

### Selected issues and execution order

| Order | Issue | Scope | Required artefacts |
|---:|---|---|---|
| 1 | `ISSUE-0069` | Single-file session action logging and diagnostics trace | `logs/session.jsonl`, Diagnostics/Logs UI, audit export inclusion. |
| 2 | `UPDATEV2-0010` | Provider registry, capability probes and source authority | `data/clean/provider_probe_results.parquet`, Provider Status UI. |
| 3 | `UPDATEV2-0011` | Symbol/ISIN/exchange identity resolver | `data/clean/instrument_identity.parquet`, identity warnings. |
| 4 | `UPDATEV2-0021` | Source conflict resolver and canonical metric selector | `data/clean/source_conflicts.parquet`, conflict UI/export. |
| 5 | `UPDATEV2-0022` | Evidence ledger and score component audit trail | `data/derived/evidence_ledger.parquet`, `data/derived/score_components.parquet`. |
| 6 | `UPDATEV2-0012` | SEC EDGAR official statement importer | Raw SEC cache, statement-fact inventory, Filings UI. |
| 7 | `UPDATEV2-0013` | European ESEF/iXBRL importer | Local ESEF inventory, verified-source confidence, Filings UI. |
| 8 | `UPDATEV2-0015` | ETF disclosure registry | ETF disclosure inventory and Data Health integration. |
| 9 | `UPDATEV2-0016` | ETF holdings normaliser | Normalised holdings with coverage/confidence status. |
| 10 | `UPDATEV2-0017` | PRIIPs KID parser | KID document inventory and extracted risk/cost fields where available. |
| 11 | `UPDATEV2-0019` | Index methodology importer | Index methodology inventory and evidence-source mapping. |
| 12 | `ISSUE-0025` | Free news and filings dashboard | Raw/clean news storage, News & Context UI. |
| 13 | `ISSUE-0054` | Point-in-time news/sentiment validation | Timestamp confidence and backtest exclusion rules. |
| 14 | `ISSUE-0055` | Optional free providers/stubs | SEC EDGAR, FRED, Stooq and RSS status, disabled by default. |
| 15 | `ISSUE-0023` | Stock fundamentals hardening | Missing-vs-bad distinction, source limitations and quality sections. |
| 16 | `ISSUE-0067` | Local score history and mini charts | `data/derived/score_history.parquet`, `data/derived/score_metric_history.parquet`. |
| 17 | `ISSUE-0047` | Feature-driver explanations | `data/derived/feature_drivers.parquet`, expanded score drivers. |
| 18 | `ISSUE-0052` | Correlation clustering and crowding warnings | `data/derived/correlation_clusters.parquet`. |
| 19 | `ISSUE-0059` | Benchmark-relative sector/theme attribution | `data/derived/benchmark_attribution.parquet`. |
| 20 | `ISSUE-0064` | Friction-adjusted return estimate | Gross edge, cost, net edge and edge-to-cost fields. |
| 21 | `UPDATEV2-0028` | Expanded report/audit packet | `evidence_export_YYYY-MM-DD_HHMMSS/` ZIP with evidence, configs, issues, checksums and session log. |

### Required stores

The programme must create and maintain these stores, using empty schema-valid Parquet files when optional evidence is not yet available:

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

### UI surfaces

The selected issues must be visible in the app through:

- Diagnostics/Logs: current `session.jsonl`, action IDs, button clicks, workflow results, errors and export paths.
- Provider Status: provider capability probes, source authority, disabled/missing-key states and redacted settings.
- Data Health: identity, conflicts, provenance, freshness, source authority and missing optional evidence.
- Filings & Statements: SEC/ESEF/local filing inventories, imported facts and mapping warnings.
- ETF Disclosures: factsheets, holdings, PRIIPs KID, prospectus/report and index-methodology inventory.
- News & Context: free news/RSS/manual notes, timestamp confidence and context-only authority.
- Simple Scores expanded rows: score history, score mini chart, component source/authority/freshness/conflict status and feature drivers.
- Audit: expanded evidence export with all available stores plus unavailable markers where optional evidence is missing.

### Release gate

Before any selected issue is moved to `issues/closed.md`, run and record:

```text
.\.venv\Scripts\python.exe -m compileall src
.\.venv\Scripts\python.exe -m pytest
.\scripts\build_windows.bat
rebuilt app start
http://127.0.0.1:8550/ smoke check
user-facing UI smoke check for every affected page/button
```

### 2026-07-09 implementation status

The first implementation sweep starts with the documentation/tracker pass, then source work for `ISSUE-0069`, provider registry, identity, conflict resolution, evidence ledger, score history, UI diagnostics and expanded export. Optional official-source importers and news providers must return explicit unavailable/null states until a local file or configured free provider is used; missing evidence must not be invented.

## 2026-07-08 Issue Recovery Audit

### What was missing

- `issues/open.md` was effectively empty even though `report.md` and the product update require unresolved issues.
- `issues/closed.md` jumped from `ISSUE-0006` to `ISSUE-0009`.
- `ISSUE-0007`, `ISSUE-0008` and `ISSUE-0010` from `report.md` were missing from the active issue roadmap.
- Useful Reddit/report-derived follow-up issues beyond the first ten were not preserved.
- The previous plan described the app too narrowly as a simple scoring cockpit and did not encode the staged product direction.
- UI reliability, progress/status, rebuild gates, browser smoke testing and product-maturity pages were not tracked as open release blockers.

### What was wrongly closed or only partially completed

- `ISSUE-0002` implemented price-row maturity warnings, but real paper/forward evidence tracking remains open as `ISSUE-0057`.
- `ISSUE-0003` implemented broad benchmark attribution, but factor/sector/theme crowding and sector-relative attribution remain open as `ISSUE-0052` and `ISSUE-0059`.
- `ISSUE-0004` implemented hit-rate/payoff diagnostics, but worst-day, loss-cluster and tail-event diagnostics remain open as `ISSUE-0049` and `ISSUE-0065`.
- `ISSUE-0005` implemented cost stress fields, but decision-price, next-open and arrival-price realism remain open as `ISSUE-0050` and `ISSUE-0064`.
- `ISSUE-0006` implemented model/backtest validity fields, but a persistent non-executable LLM thesis diary remains open as `ISSUE-0010`.
- `ISSUE-0009` implemented basic source credibility, but stronger closed-source/promotional-claim detection remains open as `ISSUE-0058`.

### What remains open

The corrected open roadmap is `ISSUE-0007`, `ISSUE-0008`, `ISSUE-0010` and `ISSUE-0011` through `ISSUE-0066`. These cover UI reliability, progress/run logs, rebuild gates, end-to-end tests, roadmap/navigation, watchlists, instrument detail, news/context, data health, paper trading, future execution architecture, strategy governance, risk/backtest depth and source-quality hardening.

### What must be visible in the app UI

All user-facing work must appear in the app, not only in backend files or exports. This includes Dashboard, Watchlists, Scores, Instrument Detail, Portfolio, Risk, News & Context, Forecasts, Backtests, Paper Trading, Decision Journal, Audit, Data & Models, Settings, Roadmap/System Map, Data Health, Import/Export, Activity Log/Run Log and Error/Recovery views where applicable.

### What must be rebuilt and smoke-tested

Before any implementation issue closes, the release gate must run relevant tests, full tests where needed, source app smoke, package rebuild, rebuilt-app start, local URL response check, main UI render check and workflow button visibility check. The command and result must be recorded in `issues/closed.md`.

## 2026-07-08 Corrected Issue Recovery And Product Roadmap

The previous report sweep was incomplete. `issues/open.md` was empty even though `report.md` recommended additional open issues, including `ISSUE-0007`, `ISSUE-0008` and `ISSUE-0010`.

The corrected issue roadmap now contains:

- `ISSUE-0001` to `ISSUE-0010`: original report-derived governance, safety, benchmark, friction, source and LLM diary issues.
- `ISSUE-0011` to `ISSUE-0045`: product reliability, UI, manual suite, watchlist, instrument detail, data health, paper-trading preparation and release/rebuild issues.
- `ISSUE-0046` to `ISSUE-0066`: additional Reddit/report-derived feature, research and guardrail issues.

The product direction is staged:

1. reliable manual evidence cockpit;
2. full manual stock/ETF research suite;
3. paper trading and forward evidence;
4. semi-automatic trade tickets;
5. optional automatic buy/sell only after extensive safety architecture and separate future approval.

Live automatic buy/sell is not implemented now.

## 2026-07-09 Report.md Coverage Matrix

`C:\Users\thor2\Downloads\report.md` has been reconciled into this plan, `issues/open.md` and `issues/closed.md`. The report is not treated as implementation proof; items stay open unless they are implemented, visible in the app where user-facing, tested, rebuilt and smoke-tested.

### Direct recommended issues

| Report item | Tracker status | Coverage |
|---|---|---|
| `ISSUE-0001` issue tracker and plan synchronisation | Closed | Completed in `issues/closed.md`; templates exist under `issues/templates/`. |
| `ISSUE-0002` young/noisy evidence and too-good-to-be-true warnings | Closed with follow-up | Completed for current simple-score rows; real paper/forward evidence remains open as `ISSUE-0057`. |
| `ISSUE-0003` benchmark alpha/beta/regime attribution | Closed with follow-ups | Broad benchmark fields completed; factor crowding and sector/theme-relative attribution remain open as `ISSUE-0052` and `ISSUE-0059`. |
| `ISSUE-0004` hit-rate, payoff-ratio and expected-value diagnostics | Closed with follow-ups | Basic payoff diagnostics completed; worst-day, loss-cluster, tail-event and payoff-profile classification remain open as `ISSUE-0049` and `ISSUE-0065`. |
| `ISSUE-0005` friction/cost/slippage stress engine | Closed with follow-ups | Low/base/high cost stress completed; operational next-open, decision-price, arrival-price and net-edge display remain open as `ISSUE-0050` and `ISSUE-0064`. |
| `ISSUE-0006` explicit model/backtest contamination validity status | Closed with follow-up | Backtest/model validity fields completed; persistent LLM thesis diary remains open as `ISSUE-0010`. |
| `ISSUE-0007` non-executable news/macro contradiction panel | Open | Tracked directly as `ISSUE-0007`, with broader news and timestamp validation in `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0055` and `ISSUE-0058`. |
| `ISSUE-0008` strategy taxonomy and scope matrix | Open | Tracked directly as `ISSUE-0008`, with roadmap/system map, templates, asset-scope guardrails and rejection tests in `ISSUE-0015`, `ISSUE-0029`, `ISSUE-0056` and `ISSUE-0060`. |
| `ISSUE-0009` source-credibility scoring for imported research notes | Closed with follow-up | Basic source credibility completed; stronger promotional/closed-source claim detection remains open as `ISSUE-0058`. |
| `ISSUE-0010` non-executable LLM thesis diary | Open | Tracked directly as `ISSUE-0010`; LLM outputs remain non-authoritative. |

### Report themes and expanded issues

| Report theme | Preserved in |
|---|---|
| Evidence-gating ladder, maturity states and forward/paper evidence | `ISSUE-0002`, `ISSUE-0057`, `ISSUE-0048`. |
| Short-sample return screenshots, annualised-return sanity, sample days/trades and Calmar/drawdown checks | `ISSUE-0002`, `ISSUE-0049`, `ISSUE-0058`; rejected as proof in `REJECTED-0007`. |
| Benchmark, SPY/cash comparison, alpha/beta/correlation, regime and sector/theme attribution | `ISSUE-0003`, `ISSUE-0051`, `ISSUE-0052`, `ISSUE-0059`. |
| Hit-rate, payoff ratio, expected value, skew and risk/reward asymmetry | `ISSUE-0004`, `ISSUE-0065`. |
| Cost, spread, slippage, FX, commission, edge-to-cost and stress scenarios | `ISSUE-0005`, `ISSUE-0064`. |
| Decision-price, next-open, arrival-price, VWAP/NBBO realism and no same-bar execution | `ISSUE-0050`, `ISSUE-0063`. |
| Backtest overfitting, PBO, deflated Sharpe, complexity metadata and data leakage | `ISSUE-0006`, `ISSUE-0048`, `ISSUE-0062`. |
| News, sentiment, macro context, contradiction detection and point-in-time validation | `ISSUE-0007`, `ISSUE-0025`, `ISSUE-0054`; sentiment has no score authority by rule. |
| Optional free providers: yfinance news, RSS, SEC EDGAR, FRED and Stooq | `ISSUE-0025`, `ISSUE-0055`. |
| LLM contamination, non-executable audit/thesis diary and forward-only validity | `ISSUE-0006`, `ISSUE-0010`, `REJECTED-0002`. |
| Strategy taxonomy, supported/context/research/rejected matrix and strategy-template governance | `ISSUE-0008`, `ISSUE-0029`, `ISSUE-0060`. |
| Futures, intraday, options, pair trading, triple-barrier/purged-CV and unsupported-asset guardrails | `ISSUE-0056`, `ISSUE-0061`, `ISSUE-0062`, `REJECTED-0005`, `REJECTED-0008`. |
| Paper/live realism, paper trading, forward evidence diary and future broker source-of-truth risks | `ISSUE-0031`, `ISSUE-0057`, `ISSUE-0032`, `ISSUE-0066`. |
| UI reliability, progress/status, rebuild gates and browser/user-perspective smoke tests | `ISSUE-0011`, `ISSUE-0012`, `ISSUE-0013`, `ISSUE-0014`, `ISSUE-0045`. |
| In-app explanations, source limitations, audit export and import/export workflow | `ISSUE-0036`, `ISSUE-0042`, `ISSUE-0043`, plus the direct report issues above. |

### Rejected or quarantined report ideas

`REJECTED-0001` through `REJECTED-0008` preserve the report's explicit rejected/dangerous items: autonomous broker execution now, direct LLM portfolio management, RL trading agents, martingale/grid systems, futures/intraday implementation now, news sentiment as direct score authority, short-sample return screenshots as evidence, and options/scalping/0DTE/binary/crypto bot experiments unless separately scoped.

## 2026-07-09 updatev2.md Coverage Matrix

`C:\Users\thor2\Downloads\updatev2.md` extends the roadmap from a price/model cockpit into a multi-source evidence cockpit. This update is implemented into this plan, `issues/open.md`, `issues/closed.md`, root `ISSUES.md` and `REPORT.md`. The update does not close implementation work. It adds open work and research-only records.

### Non-negotiable rules preserved

- No automatic broker execution.
- No invented market, ETF, holdings, news, FX, filing, statement, candle, forecast or model data.
- No silent forward-filling of important missing values.
- No LLM-calculated portfolio metrics and no LLM-authorised trades.
- Hard validation and risk gates run before actionable signal ranking.
- Weak, stale, incomplete or conflicted evidence defaults to `no_trade` or `manual_review`.
- Every final action must include `blocked_by` and `reason_full`.
- Unavailable TimesFM, Toto, API provider, filing provider or local LLM must produce explicit unavailable/null outputs and zero direct score contribution.
- Release-facing actions remain limited to `hold`, `no_trade`, `add_candidate`, `trim_candidate` and `manual_review`.
- `buy`, `sell`, `strong buy` and `strong sell` wording remains internal/legacy only and must not appear in release-facing UI.

Required evidence flow:

```text
Hard data/freshness/provenance gates
-> provider identity resolution
-> immutable raw evidence import
-> clean canonical dataset
-> deterministic features
-> source authority + conflict resolution
-> evidence score / evidence quality / risk-friction
-> optional low-authority model/candle/news confirmation
-> audit packet
-> advisory label only
```

Forbidden shortcuts:

```text
API says X -> trust X blindly
LLM says buy -> buy
candle pattern appears -> trade
vendor statement says revenue -> override official filing
ETF factsheet missing -> infer holdings
```

### Existing plan extension

The update preserves the current local-first yfinance workflow, three-score model, optional low-authority TimesFM/Toto/local LLM evidence, audit packet, manual review posture and advisory-only labels. It extends the app with provider registry, source authority, official filings, ETF disclosure documents, evidence ledger, candle features, provider fallback/discrepancy checks and stricter UI/rebuild discipline.

### CrossCompatibleInvestmentApp reuse guidance

The reference app `Thor2709/CrossCompatibleInvestmentApp` is not a direct replacement. Useful ideas to inspect and port selectively:

```text
investment_desk/yahoo_finance.py
investment_desk/exchange_support.py
investment_desk/analysis_confidence.py
investment_desk/storage.py
investment_desk/portfolio_imports.py
investment_desk/fx_cache.py
investment_desk/macro_data.py
investment_desk/sec_financial_statements.py
investment_desk/bank_data_sources.py
investment_desk/watchlist_export.py
tests/test_yahoo_finance.py
tests/test_portfolio_imports.py
tests/test_analysis_engine.py
```

Do not port the old UI shell wholesale, old buy/sell wording, simple price-only recommendation logic, generated runtime data, fragile background auto-refresh without visible status/locking or anything implying automatic trading.

### Provider registry and source authority

Provider strategy:

| Provider | Default role | Authority | Rules |
|---|---|---|---|
| yfinance | Default prices, FX, partial profile/ETF metadata/holdings | `vendor_unofficial` | Free/unofficial; cache required; coverage inconsistent. |
| SEC EDGAR | US official submissions and XBRL facts | `official_regulator` | No API key; user agent required; P0 for US stocks. |
| EU ESEF manual | European official filing import and iXBRL parsing | `official_filing_if_source_verified` | P0/P1 for European stocks; offline manual import first. |
| France DILA | France OAM discovery | `official_oam` | Optional; disabled by default; cache required. |
| Netherlands AFM | Dutch OAM discovery | `official_oam` | Optional; disabled by default; CSV/XML exports. |
| FMP | Optional enrichment/reference/statements | `vendor_normalised` | Disabled by default; API key; free budget defaults to 250/day; cannot override official facts. |
| Alpha Vantage | Small-volume OHLCV verification/fallback | `vendor_normalised` | Disabled by default; API key; default free budget 25/day; not broad universe backbone. |
| Finnhub | Experimental candles/profile/financials/news | `vendor_normalised` | Disabled by default; API key; live entitlement probes required. |
| Stooq | Optional OHLCV fallback/check | `vendor_normalised` | No-key where coverage works; disabled unless configured. |
| Twelve Data | Optional OHLCV fallback/check | `vendor_normalised` | API key; disabled unless configured; rate limits enforced. |
| Tiingo | Optional OHLCV fallback/check | `vendor_normalised` | API key; disabled unless configured; rate limits enforced. |

Every provider must return a `ProviderProbeResult` with provider name, checked time, capability, status (`ok`, `forbidden`, `rate_limited`, `empty`, `not_configured`, `error`), message, calls used and `usable_for_scoring`. No provider capability is score-eligible until the probe is `ok`.

Source authority ladder:

```text
official_regulator
official_oam
official_filing
issuer_document
index_provider
exchange_listing
vendor_normalised
vendor_unofficial
manual_upload
community_forum
llm_audit
```

Hard source ranking:

```text
US statements:
  SEC EDGAR > issuer annual report > FMP/Alpha/Finnhub/yfinance > manual note > LLM

EU statements:
  ESEF/iXBRL official filing > national OAM filing package > issuer annual report > FMP/Alpha/Finnhub/yfinance > manual note > LLM

ETFs:
  issuer official prospectus/KID/report/holdings > regulator/fund register > index provider methodology > exchange listing > vendor/yfinance/FMP > manual note > LLM
```

### Evidence ledger and conflict resolver

New clean/derived tables required:

```text
data/clean/provider_probe_results.parquet
data/clean/evidence_sources.parquet
data/clean/filing_documents.parquet
data/clean/statement_facts.parquet
data/clean/fund_documents.parquet
data/clean/fund_holdings.parquet
data/clean/index_methodology.parquet
data/derived/evidence_ledger.parquet
data/derived/score_components.parquet
data/derived/source_conflicts.parquet
data/derived/filing_quality_scores.parquet
```

Every source record must include provider/source authority, document type, URL/path, as-of/published/ingested dates, checksum, language, currency, timezone, licence/rate-limit notes, quality label and staleness. Every score component must reference source/provenance, freshness, authority and conflict status. Missing source means not score-eligible.

Conflict resolver output must record selected value/source, authority, conflicting values, conflict severity (`none`, `minor`, `material`, `blocking`), resolution rule and whether manual review is required. Official sources win over vendor sources. Material conflicts lower evidence quality or force manual review. Silent overwrite is forbidden.

### Filing and statement importers

- SEC EDGAR is P0 for US stocks: no-key REST JSON APIs, submissions history, XBRL company facts, 10-Q, 10-K, 8-K, 20-F, 40-F, 6-K variants and nightly bulk ZIP support. Raw JSON must be cached and canonical facts must retain taxonomy, concept, unit, dates, form and accession.
- European ESEF/iXBRL is P0/P1 for European stocks: manual ESEF ZIP/XHTML import first, iXBRL facts extracted where parseable, IFRS concepts mapped only when clear, extensions retained with warnings and raw packages preserved.
- ESAP is future discovery only; do not wait for it.
- National OAMs start with France DILA and Netherlands AFM discovery, optional and disabled by default, with official OAM authority and cached metadata/documents.
- Vendor statement providers FMP, Alpha Vantage and Finnhub are optional, rate-limited and never outrank SEC/ESEF/issuer documents.

### ETF disclosure pipeline

ETF evidence is a disclosure stack, not price-only evidence:

```text
prospectus
PRIIPs KID
annual report
half-yearly report
factsheet
full holdings file
index methodology
SFDR pre-contractual/website/periodic disclosures
securities lending/collateral disclosure
distribution/tax/share-class documents
```

ETF document registry schema must include fund/share-class identity, issuer, domicile, UCITS flag, document type/title/language, URL/local path, document/effective/as-of dates, ingested time, checksum, source authority, staleness and manual-review flag.

ETF holdings normaliser must support CSV, XLSX, JSON, Parquet and PDF-table fallback only when no structured source exists. Weights must be numeric and non-negative. Full holdings 95-105% are OK, under 95% is partial warning, under 80% caps evidence quality and over 105% is conflict/manual review. Top-holdings-only sources are always partial. Do not infer missing weights.

ETF parsers required: PRIIPs KID parser, prospectus/annual/half-year report parser, index methodology importer/parser and SFDR parser. Missing KID for retail UCITS ETF, stale holdings, unknown replication method, missing index methodology or conflicts on TER/AUM/holdings/replication/SFDR cap evidence quality or force manual review.

ETF-specific score components required:

```text
etf_cost_score_10
etf_holdings_completeness_score_10
etf_diversification_score_10
etf_liquidity_fund_size_score_10
etf_structure_replication_score_10
etf_index_methodology_fit_score_10
etf_tracking_quality_score_10
etf_currency_distribution_tax_context_score_10
etf_securities_lending_collateral_score_10
etf_sfdr_disclosure_quality_score_10
etf_overlap_with_portfolio_score_10
```

### Candle/OHLCV feature layer

Candles are useful as low-authority context and manual audit, not as direct trading logic. Candles can confirm, warn, contextualise or demote. They cannot rescue weak deterministic evidence, override hard gates or trigger actions directly.

Required files:

```text
services/candle_features.py
services/candle_templates.py
services/candle_backtest_safety.py
tests/test_candle_features.py
tests/test_candle_templates.py
tests/test_candle_backtest_safety.py
data/derived/candle_features.parquet
```

Input requirements: open, high, low, close, adjusted close, volume, corporate actions if available, timezone, source and as-of date.

Required features include body/range/wick proportions, close location value, gaps, true range, range ATR z-score, volume/body z-scores, large-range/long-body/doji/rejection/gap/inside/outside flags and optional named patterns (`hammer`, `shooting_star`, `engulfing`, `morning_star`, `evening_star`, `doji`). Use TA-Lib if available; otherwise internal simple definitions must be labelled `template_not_talib`.

Candle fields:

```text
candle_context_score_10
candle_quality_score_10
candle_template_label
candle_confirming_evidence
candle_warning
candle_authority_label
```

Authority cap:

```text
candle_context_score contribution <= 5% of Evidence Score by default
named pattern contribution <= 3% and only with context filter
candle evidence cannot override hard gates
candle evidence cannot rescue weak deterministic evidence
```

Backtest rules: signal at close of bar `t`, execute at next available bar `t+1`, no same-bar execution, ambiguous stop/target same candle flagged, conservative gap fill assumptions, costs/slippage included and trade/pattern counts reported. Pattern counts below 30 are exploratory only, 30-99 low confidence, 100-299 usable but regime-sensitive and 300+ still requires walk-forward/regime validation.

### UI and workflow additions

Every button must have visible label, enabled/disabled state, tooltip/explanation, start timestamp, running status, progress/status text, success/failure result, link to generated file/table, readable error without traceback unless debug mode and audit log entry.

Buttons to verify or add:

```text
Refresh yfinance data
Run algorithms
Run forecasting models
Show scores
Renew data
Import prices
Import ETF factsheets
Import ETF holdings
Import FX
Import manual notes
Import SEC filings
Import ESEF filing package
Import ETF documents
Run provider entitlement probes
Export audit packet
Import external audit response
Open Data & Models
Open Risk
Open Backtests
Open Instrument Detail
Open Settings
```

New pages/panels:

```text
Provider Status
Filings & Statements
ETF Disclosures
Candle Evidence
Evidence Ledger
Issue/QA Status
```

Progress wording examples must be implemented for yfinance refresh, provider probes, ESEF import, ETF holdings normalisation, forecasting and audit packet export.

### Backtesting and validation additions

Add fields:

```text
signal_family
signal_variant
feature_set_id
provider_set_id
training_window
validation_window
test_window
walk_forward_split_id
n_walk_forward_periods
parameter_count
effective_trials_estimate
trade_count
median_holding_period_days
turnover_annualised
cost_scenario
slippage_scenario
max_drawdown
worst_12m_return
probabilistic_sharpe
deflated_sharpe
pbo_probability_backtest_overfitting
ambiguous_ohlc_path_count
ambiguous_ohlc_path_rate
data_coverage_pct
```

Backtest reporting must separate:

```text
price_only_baseline
price_plus_candle
price_plus_fundamentals
price_plus_filings
price_plus_etf_disclosures
price_plus_model_confirmation
```

Do not present combined score improvement as meaningful until out-of-sample/walk-forward evidence exists.

### REPORT.md update requirements

`REPORT.md` must include a new top-level section:

```markdown
## 2026-07-09 Research Update - Provider, Filings, ETF Disclosure and Candle Evidence Expansion
```

It must cover: source authority model, provider strategy, European filings strategy, ETF filings-equivalent strategy, candle evidence strategy, CrossCompatibleInvestmentApp reuse notes and testing/rebuild rules.

### updatev2 open issues

The update issue numbers conflict with the existing tracker, so they are namespaced in `issues/open.md` as `UPDATEV2-0010` through `UPDATEV2-0030`. These map one-to-one to the requested update issues:

| Update ID | Namespaced tracker ID | Title |
|---|---|---|
| `ISSUE-0010` | `UPDATEV2-0010` | Provider registry, capability probes and source authority model |
| `ISSUE-0011` | `UPDATEV2-0011` | Symbol/ISIN/exchange identity resolver |
| `ISSUE-0012` | `UPDATEV2-0012` | SEC EDGAR official statement importer |
| `ISSUE-0013` | `UPDATEV2-0013` | European ESEF/iXBRL filing importer |
| `ISSUE-0014` | `UPDATEV2-0014` | France DILA and Netherlands AFM OAM discovery adapters |
| `ISSUE-0015` | `UPDATEV2-0015` | ETF disclosure registry |
| `ISSUE-0016` | `UPDATEV2-0016` | ETF holdings normaliser |
| `ISSUE-0017` | `UPDATEV2-0017` | PRIIPs KID parser |
| `ISSUE-0018` | `UPDATEV2-0018` | ETF prospectus, annual and half-year report parser |
| `ISSUE-0019` | `UPDATEV2-0019` | Index methodology importer |
| `ISSUE-0020` | `UPDATEV2-0020` | SFDR disclosure parser |
| `ISSUE-0021` | `UPDATEV2-0021` | Source conflict resolver and canonical metric selector |
| `ISSUE-0022` | `UPDATEV2-0022` | Evidence ledger and score component audit trail |
| `ISSUE-0023` | `UPDATEV2-0023` | FMP optional provider adapter |
| `ISSUE-0024` | `UPDATEV2-0024` | Alpha Vantage verification/fallback adapter |
| `ISSUE-0025` | `UPDATEV2-0025` | Finnhub experimental adapter with entitlement probes |
| `ISSUE-0026` | `UPDATEV2-0026` | Candle feature/context/backtest module |
| `ISSUE-0027` | `UPDATEV2-0027` | UI workflow/button reliability and progress indicators |
| `ISSUE-0028` | `UPDATEV2-0028` | Report/audit packet expansion for providers, filings, ETF docs and candles |
| `ISSUE-0029` | `UPDATEV2-0029` | Rebuild/test/update discipline automation |
| `ISSUE-0030` | `UPDATEV2-0030` | Optional OHLCV fallback providers: Stooq, Twelve Data and Tiingo |

### updatev2 research closures

Research-only closures are recorded in `issues/closed.md` as `CLOSED-RESEARCH-001` through `CLOSED-RESEARCH-006` for candle research, CrossCompatibleInvestmentApp review, provider API research, US filings research, European filings research and ETF disclosure research. These close research only; implementation remains open.

### updatev2 implementation order

1. Slice A - Integrity foundation: provider registry, identity resolver, source conflict resolver and evidence ledger.
2. Slice B - Official statements: SEC EDGAR, ESEF manual importer, `statement_facts.parquet` and common metric mapping.
3. Slice C - ETF disclosure stack: document registry, holdings normaliser, KID parser, fund report parser, index methodology importer and SFDR parser.
4. Slice D - Optional vendors/OHLCV fallback: FMP, Alpha Vantage, Finnhub, Stooq, Twelve Data and Tiingo.
5. Slice E - Candle layer: candle feature/context/backtest module.
6. Slice F - UI, audit and rebuild discipline: workflow reliability, audit packet expansion and finish-check discipline.

## Product Stages

### Stage 1 - Reliable local manual evidence cockpit

Current/near-term goal. The app must provide local-first stock and ETF analysis with yfinance as the default data backbone, Evidence Score, Evidence Quality and Risk/Friction. It must not invent data, silently forward-fill important missing values, give LLMs authority or perform automatic trading. Every button must work, every workflow must show progress, every user-facing feature must appear in UI and every result must show provenance, freshness and limitations.

### Stage 2 - Full manual stock/ETF research suite

Near-term/medium-term goal. Add watchlists, candidate management, instrument detail pages, screener, portfolio construction sandbox, ETF overlap, stock fundamentals, news/context, macro/regime dashboard, forecast lab, backtest lab, decision journal, data health centre, import/export centre, config editor and a "What changed since last run?" panel.

### Stage 3 - Paper trading and forward evidence

Before any live execution. Add a local paper portfolio, paper trade proposals, manual accept/reject, entry/exit journal, PnL tracking, benchmark/cash comparison and forward evidence diary. No broker execution.

### Stage 4 - Semi-automatic trade tickets

Future only. Generate proposed trade tickets with user confirmation required, risk gates required, stale data blocks, news/event conflicts shown and no automatic live order placement.

### Stage 5 - Optional automatic buy/sell system

Future architecture only for now. It may be considered only after Stages 1 to 3 are reliable, paper trading has enough forward evidence, rebuild/smoke/release gates pass, broker abstraction exists, kill switch exists, max order size exists, max daily turnover exists, max daily loss exists, max drawdown stop exists, audit log exists, order preview exists, user confirmation mode exists, no LLM/model-only trading is possible and emergency disable exists.

## Long-Term Automation Roadmap: Advisory-First, Automation-Gated

This section records the future long-horizon automation direction from the 2026-07-09 automation research skeleton. It does not change the current product rule: live broker execution is not implemented now and remains disabled until separate future approval. The near-term role remains evidence scoring, audit, UI reliability and manual research. The long-term target is a deterministic, constrained portfolio system that can place trades only after strict readiness gates, paper evidence, canary evidence, broker reconciliation and compliance review are complete.

The required evolution path is:

```text
AI Evidence Cockpit
-> evidence-scored portfolio engine
-> supervised trade tickets
-> paper-trading robot
-> live-canary robot
-> constrained long-horizon automated portfolio trader
```

Core automation principle:

> The automated system may execute only deterministic, pre-approved strategy templates. LLMs, TimesFM, Toto, news sentiment, manual notes or raw model forecasts may never directly authorise orders.

### Automation modes and authority

```yaml
automation_mode:
  - disabled
  - supervised_ticket_only
  - paper_trading
  - live_canary
  - live_constrained

automation_authority:
  - deterministic_strategy_template_only

never_allowed:
  - llm_direct_trade_authority
  - model_forecast_direct_trade_authority
  - news_sentiment_direct_trade_authority
  - unvalidated_data_execution
  - same_bar_execution
  - unrestricted_position_sizing
  - unrestricted_order_retry
```

### Automation score stack

The current three-score model is still the base, but automation requires additional layers.

| Score | Meaning | Used for automation |
|---|---|---|
| Evidence Score /10 | How positive the signal stack is. | Yes, but never alone. |
| Evidence Quality /10 | How trustworthy the data and validation are. | Yes, hard minimum. |
| Risk/Friction /10 | Liquidity, volatility, drawdown, cost, FX and concentration. | Yes, hard minimum. |
| Execution Readiness /10 | Whether an order can be placed safely now. | Yes, final gate. |
| Portfolio Fit /10 | Diversification, overlap, correlation, beta and role. | Yes, sizing input. |
| Model Confirmation /10 | Baseline, TimesFM and Toto confirmation. | Soft cap only. |
| Automation Confidence /10 | Composite after all gates. | Yes, but only in live modes. |

Required future scoreboard columns:

```text
evidence_score_10
evidence_quality_10
risk_friction_10
execution_readiness_10
portfolio_fit_10
model_confirmation_10
automation_confidence_10
automation_eligible
automation_blocked_by
automation_reason_full
automation_mode_required
human_approval_required
paper_trading_required
live_canary_required
```

### Automation-grade data layer

yfinance remains acceptable as the default research backbone. It is not sufficient as the sole unattended-trading source because its own documentation describes it as unaffiliated with Yahoo, intended for research/education and subject to Yahoo's personal-use terms. Any automation-grade data point must record:

```text
source_name
source_type
licence_status
as_of_date
ingested_at
exchange_timezone
currency
adjustment_method
corporate_action_status
checksum
cross_source_validated
staleness_status
automation_allowed
```

Automation-grade data requirements:

| Data type | Research/default source | Automation-grade requirement |
|---|---|---|
| Prices | yfinance | Cross-check with broker market data or paid EOD provider. |
| Corporate actions | yfinance | Split/dividend adjustment validation. |
| ETF metadata | yfinance/manual | Issuer factsheet, KID and holdings ingestion. |
| ETF holdings | yfinance top holdings/manual | Full issuer holdings where available. |
| Stock fundamentals | yfinance info | SEC EDGAR/XBRL for US stocks and official filings where possible. |
| Macro | optional | FRED, ECB, Eurostat or equivalent optional context. |
| FX | yfinance/manual | Broker FX or ECB reference rates. |
| Broker positions | local/manual | Direct broker read-only reconciliation. |
| Orders/fills | not present | Immutable broker execution logs. |

### ETF due-diligence engine

ETFs require a product-quality module separate from price momentum because the investable object is a fund wrapper with exposure, structure, tracking, liquidity, tax and trading-cost characteristics. ETFs should be the first asset class considered for any future automation because they are usually diversified, liquid and easier to fit into a portfolio allocation framework than single stocks.

Future ETF data model:

```text
instrument_id
isin
ticker
exchange
mic
currency
base_currency
fund_currency
ucits_status
issuer
fund_name
benchmark_index
asset_class
region
sector
theme
replication_method
physical_or_synthetic
sampling_or_full_replication
securities_lending_allowed
securities_lending_revenue_split
ter_bps
ongoing_charges_bps
aum_eur
fund_inception_date
distribution_policy
domicile
tax_notes
kid_url
factsheet_url
holdings_url
nav_date
premium_discount_pct
tracking_difference_1y
tracking_difference_3y
tracking_error_1y
bid_ask_spread_bps
average_daily_value_eur
creation_redemption_notes
leveraged_or_inverse_flag
complex_product_flag
```

Future ETF modules:

| Module | Metrics | Reason |
|---|---|---|
| Exposure Fit | Benchmark, region, sector, currency, duration, credit. | Avoid duplicate or unintended exposure. |
| Cost/TCO | TER, spread, premium/discount, tracking mismatch, impact. | Long horizon makes TER and tracking matter. |
| Liquidity | ADV EUR, spread, exchange, volume, underlying liquidity. | Prevent poor fills and trapped positions. |
| Tracking Quality | Tracking difference/error versus benchmark. | ETF may lag its own index. |
| Structure Safety | UCITS, physical/synthetic, securities lending, collateral. | Wrapper risk matters. |
| Holdings Quality | Concentration, top-10 %, country/sector weights. | Avoid hidden concentration. |
| Portfolio Overlap | Overlap with existing ETFs/stocks. | Prevent owning the same exposure twice. |
| Trend/Momentum | 3/6/9/12-month momentum, SMA filters. | Long-horizon tactical timing. |
| Risk | Volatility, drawdown, beta, downside risk. | Avoid unstable exposure. |
| Automation Eligibility | Data freshness, liquidity, spread, KID/factsheet status. | Final execution gate. |

ETF scoring skeleton:

```text
ETF_Evidence_Score =
  25% medium_term_momentum
  15% trend
  15% relative_strength_vs_role_benchmark
  10% holdings_quality
  10% tracking_quality
  10% regime_fit
  10% model_confirmation_capped
  5% manual_research_context_quality

ETF_Quality_Score =
  25% price_data_quality
  20% issuer_metadata_completeness
  15% holdings_freshness
  15% tracking_data_availability
  10% history_length
  10% source_reliability
  5% audit_completeness

ETF_Risk_Friction_Score =
  20% low_volatility
  20% drawdown_control
  15% liquidity
  15% spread_cost
  10% premium_discount_stability
  10% concentration_control
  10% fx_and_tax_cleanliness
```

### Stock point-in-time fundamentals engine

Stocks need a separate module from ETFs. Price-only scoring is too weak for long-horizon investing. The stock engine should combine momentum, quality, value, profitability, growth, financial strength, revisions, risk, liquidity and portfolio fit. Automation must not treat Yahoo-style current `info` fields as if they were point-in-time historical data; backtests need the data that would have been known on each decision date, including filing and announcement lags.

Future stock data model:

```text
instrument_id
ticker
exchange
mic
isin
figi
currency
country
sector
industry
market_cap_eur
shares_outstanding
free_float
average_daily_value_eur
adjusted_ohlcv
corporate_actions
dividends
splits
earnings_dates
filing_dates
financial_statement_period
revenue
gross_profit
operating_income
net_income
free_cash_flow
total_assets
total_liabilities
net_debt
shareholders_equity
capex
rd_expense
buybacks
dividends_paid
analyst_estimates
estimate_revision_date
recommendation_mean
insider_or_institutional_context_optional
```

Future stock modules: momentum, trend, quality, profitability, value, growth, balance sheet, capital discipline, revisions, risk, liquidity, portfolio fit, event risk and automation readiness.

Stock scoring skeleton:

```text
Stock_Evidence_Score =
  20% momentum
  15% trend
  15% quality
  10% profitability
  10% value
  10% growth
  5% revisions
  5% portfolio_fit
  5% regime_fit
  5% model_confirmation_capped

Stock_Quality_Score =
  20% price_data_quality
  20% fundamental_data_freshness
  15% point_in_time_integrity
  15% history_length
  10% corporate_action_cleanliness
  10% source_reliability
  10% missing_component_penalty

Stock_Risk_Friction_Score =
  20% volatility
  20% drawdown
  15% liquidity
  15% balance_sheet_risk
  10% beta_concentration
  10% event_risk
  10% FX/currency_risk
```

### Constrained portfolio construction

Automation must not use "highest score = biggest trade". The allocator should be constrained and slow-moving.

Recommended allocation hierarchy:

```text
Phase 1: fixed target ETF allocation + rebalance bands
Phase 2: score-tilted target weights within caps
Phase 3: risk-budgeted ETF allocation
Phase 4: ETF + stock satellite sleeve
Phase 5: constrained HRP / risk-parity support
Phase 6: never unconstrained mean-variance based on raw forecast returns
```

Required future constraints:

```text
max_single_etf_weight
max_single_stock_weight
max_sector_weight
max_country_weight
max_currency_weight
max_theme_weight
max_issuer_weight
max_etf_overlap
max_portfolio_beta
max_portfolio_volatility
max_expected_drawdown
min_cash_weight
max_turnover_monthly
max_turnover_annual
min_trade_value_eur
max_trade_value_eur
max_daily_order_value_eur
max_live_canary_value_eur
```

Position sizing skeleton:

```text
base_target_weight = role_weight_or_strategy_template_weight
score_tilt = clamp((automation_confidence_10 - 5) / 5, -1, +1)
proposed_target_weight = base_target_weight + score_tilt * max_score_tilt
final_target_weight = apply_caps_and_risk_budget(proposed_target_weight)
trade_value_eur = final_target_weight * portfolio_value_eur - current_value_eur
```

Automation can only trade if all of these are true:

```text
automation_eligible == true
evidence_quality_10 >= 7
risk_friction_10 >= 6
execution_readiness_10 >= 8
portfolio_constraints_pass == true
edge_to_cost_ratio >= threshold
trade_value_eur >= min_trade_value_eur
not in blackout_window
not already_ordered_today
```

### Automation-grade backtesting and validation

Automation requires a stricter validation ladder than the manual evidence cockpit.

```text
research_only
backtest_validated
walk_forward_validated
paper_observer_young
paper_observer_mature
live_canary_young
live_canary_mature
automation_allowed
automation_suspended
retired_or_rejected
```

Backtest rules:

```text
No same-bar execution.
No look-ahead fundamentals.
No silent forward filling of critical fields.
Use adjusted total-return prices where available.
Use realistic commissions, FX, spread, slippage and market impact.
Trade at next open/next close depending on strategy definition.
Record decision timestamp and execution timestamp.
Store rejected trades, not only accepted trades.
Benchmark against relevant ETF/stock benchmark and cash.
Include taxes only as a separate optional scenario unless user-specific tax data exists.
```

Required diagnostics:

```text
sample_days
sample_trades
walk_forward_periods
train_start
train_end
test_start
test_end
hit_rate
average_win
average_loss
payoff_ratio
expected_value_per_trade
max_drawdown
worst_12m_return
turnover_annualised
average_holding_period_days
median_holding_period_days
benchmark_beta
benchmark_alpha_proxy
alpha_t_stat
information_ratio
probabilistic_sharpe
deflated_sharpe
pbo_probability
parameter_sensitivity_status
cost_stress_break_even_bps
```

Because long-horizon monthly strategies often have low sample counts, the app must show calendar maturity, trade-count maturity and regime maturity separately.

### Forecast model governance

TimesFM and Toto remain low-authority forecast evidence. They must not become order engines. Model outputs are capped unless locally calibrated and must never rescue weak deterministic evidence.

Required model governance fields:

```text
model_name
model_version
checkpoint_hash
input_window
forecast_horizon_days
forecast_generated_at
forecast_target
forecast_status
model_allowed_in_score
model_authority_level
calibration_status
oos_mase
directional_accuracy
coverage_q10_q90
forecast_age_days
contamination_risk
training_cutoff_known
model_score_cap
```

Hard model score cap rule:

```text
if calibration_status in ["missing", "pending", "poor"]:
    model_confirmation_weight <= 5%
    model_cannot_upgrade_final_label = true

if deterministic_evidence_score < 5:
    model_confirmation_score cannot raise automation_eligible
```

### Future automation implementation stages

Stage A - supervised trade-ticket generator:

```text
trade_ticket_id
created_at
instrument
side
target_weight
current_weight
trade_value_eur
estimated_shares
estimated_cost_bps
reason_full
blocked_by
approval_status
expires_at
```

Stage B - broker read-only reconciliation:

```text
cash
positions
market_value
currency_balances
open_orders
executions
account_base_currency
margin_status
```

Stage C - paper-trading robot:

```text
paper_order
paper_fill
paper_slippage_model
paper_position
paper_cash
paper_reconciliation
paper_performance
```

Stage D - live canary mode:

```text
max_canary_portfolio_pct = 1%
max_single_canary_order_eur = configurable
max_orders_per_day = 1
max_orders_per_week = configurable
human_approval_required = true initially
```

Stage E - constrained live automation:

```text
allowed_assets = approved ETF/stock universe
allowed_order_types = limit / marketable_limit only
allowed_frequency = daily or weekly check
allowed_horizon = weeks_to_years
leverage_allowed = false by default
shorting_allowed = false by default
options_allowed = false
futures_allowed = false
crypto_allowed = false unless separate architecture
```

### Execution architecture and order policy

Future broker automation, if separately approved, should prefer brokers with documented APIs and terms that allow API trading. DEGIRO must not be used for automation unless its terms change, because the attached research states it does not allow automated trading bots. IBKR is the likely future research candidate, but any implementation requires separate approval and compliance review.

Future services:

```text
BrokerConnector:
  read_account()
  read_positions()
  read_cash()
  read_open_orders()
  read_executions()
  resolve_contract()
  preview_order()
  place_order()
  cancel_order()
  cancel_all_app_orders()

OrderManager:
  create_intent()
  validate_intent()
  reserve_cash()
  generate_order()
  submit_order()
  track_order()
  reconcile_fill()
  handle_partial_fill()
  handle_cancel()
  handle_reject()

RiskEngine:
  pre_trade_checks()
  post_trade_checks()
  daily_loss_check()
  max_position_check()
  max_order_value_check()
  duplicate_order_check()
  stale_data_check()
  kill_switch_check()

AuditLedger:
  append_decision()
  append_order()
  append_fill()
  append_cancel()
  append_error()
  append_reconciliation()
```

Order policy:

```text
default_order_type = marketable_limit
limit_price =
  buy: min(last_price * (1 + max_slippage_pct), ask_or_mid_adjusted)
  sell: max(last_price * (1 - max_slippage_pct), bid_or_mid_adjusted)
time_in_force = DAY
extended_hours = false by default
max_order_age_minutes = configurable
retry_policy = no automatic retry unless reason is safe and bounded
```

Mandatory kill switches:

```text
global_kill_switch
strategy_kill_switch
instrument_kill_switch
broker_connection_kill_switch
daily_loss_kill_switch
stale_data_kill_switch
reconciliation_failure_kill_switch
unexpected_position_kill_switch
order_reject_rate_kill_switch
duplicate_order_kill_switch
```

### Compliance research skeleton

Live automation requires proper legal review before implementation. The future compliance issue must cover at least:

```text
jurisdiction
user_type = private_individual / investment_firm / adviser / managed_accounts
broker_terms_allow_api_trading
algorithmic_trading_notification_required
investment_advice_boundary
market_abuse_controls
best_execution_policy
record_retention_policy
incident_response_policy
business_continuity_plan
cybersecurity_controls
api_key_storage_policy
personal_data_policy
```

Design boundary:

```text
The app must not become:
  client money manager
  copy trading platform
  public recommendation engine
  paid signal service
  financial adviser
  broker-routing service for others
without a much larger regulatory architecture.
```

### Automation Control Centre UI

Future UI page:

```text
Automation Status:
  mode
  allowed universe
  broker connection
  kill switch status
  last reconciliation
  next decision time
  pending approvals
  blocked reasons

Trade Queue:
  proposed trades
  approved trades
  submitted orders
  open orders
  filled orders
  cancelled/rejected orders

Risk Console:
  exposure after proposed trades
  cash after proposed trades
  cost estimate
  order limits
  daily/weekly turnover
  stale data warnings

Evidence Drilldown:
  evidence score
  quality score
  risk/friction score
  execution readiness
  portfolio fit
  model confirmation
  final reason

Audit Journal:
  what changed since last run
  why the app wants to trade
  what data it used
  what gates passed/failed
  what happened after previous signals
```

### Future automation issue skeletons

These are roadmap skeletons and should be converted into `issues/open.md` entries only when the current manual-suite issue repair phase permits new automation work.

| ID | Title | Priority | Acceptance summary |
|---|---|---|---|
| `AUTO-0001` | Add long-term automation roadmap | P0 | Plan distinguishes advisory, supervised, paper, live-canary and live modes; no model/LLM/news direct order authority; automation requires deterministic template and hard gates. |
| `AUTO-0002` | Add Execution Readiness Score | P0 | Scoreboard includes `execution_readiness_10`; stale data, spread, liquidity, FX, corporate action, blackout and broker mismatch block orders. |
| `ETF-0001` | Build ETF due-diligence module | P0/P1 | ETF score includes exposure, structure, domicile/tax, tracking, liquidity, TCO, holdings freshness and overlap. |
| `STOCK-0001` | Build point-in-time stock fundamentals module | P0/P1 | Stocks score quality, profitability, value, growth, momentum, revisions, risk and liquidity; backtests use filing-date-aware data only. |
| `PORT-0001` | Add constrained target-weight engine | P0 | Scores convert into target weights only through caps, bands and risk budgets; no unconstrained optimiser; after-trade state passes exposure limits. |
| `BT-0001` | Automation-grade walk-forward validation | P0 | Every strategy has maturity state; walk-forward, costs, alpha/beta, payoff, DSR/PBO and sensitivity status shown; no automation until thresholds pass. |
| `EXEC-0001` | Broker read-only connector | P0 | Reads positions, cash, orders and fills; no order permission; reconciles broker and local state. |
| `EXEC-0002` | Paper-trading order manager | P0/P1 | Uses same decision/order path as live but paper broker; records simulated fills, slippage, rejects and reconciliation. |
| `EXEC-0003` | Live canary trading mode | P1 | Tiny max exposure, human approval initially required, kill switch and duplicate-order protection tested. |
| `COMPLIANCE-0001` | EU/NL automation compliance review | P0 before live trading | Broker terms, AFM/MiFID II implications, recordkeeping, incident response, kill switches and business-continuity requirements mapped. |

### Recommended automation build order

1. Preserve the advisory safety layer and finish the manual research suite.
2. Add Execution Readiness Score and automation-specific blockers.
3. Build the ETF due-diligence module.
4. Build point-in-time stock fundamentals before any stock automation.
5. Build constrained portfolio target-weight generation.
6. Upgrade backtesting to automation-grade walk-forward validation.
7. Add broker read-only reconciliation.
8. Add paper-trading engine using the same order pipeline as live.
9. Run paper mode for months, not days.
10. Add live canary mode with very small size and human approval.
11. Only then consider constrained live automation after separate approval.

## Missing Features And Product Maturity Roadmap

### Current maturity

The app can load local/yfinance-backed data, build simple x/10 evidence scores, display expandable score rows, run baseline/optional forecast adapters, export audit packets, show several diagnostics and run a passing automated test suite. It is not yet a complete manual research suite because many features are backend-only, diagnostic-only or missing from navigation.

### Biggest gaps

- Browser-proven button reliability and visible progress/status for long-running workflows.
- Persistent Activity Log/Run Log and error recovery UI.
- First-class Watchlists, News & Context, Paper Trading, Decision Journal, Roadmap/System Map, Data Health, Import/Export and Screener pages.
- Stronger instrument detail views with price history, fundamentals, news/context, forecast evidence, backtest trust and journal/paper history.
- Local score-history storage and a compact total-score evolution graph in every expanded ETF/stock score row.
- Better UI semantic locators, visual smoke tests and rebuild gate evidence.
- Point-in-time news validation, optional free context providers and contradiction detection.
- Forward evidence and paper-trading records.

### Manual-suite roadmap

Implement in this order: UI reliability and progress, Roadmap/System Map, navigation redesign, watchlist/universe manager, instrument detail, data health centre, news/context, screener, portfolio sandbox, ETF overlap, stock fundamentals, event calendar, macro regime, forecast lab, backtest lab, strategy builder, import/export centre and config editor.

### Paper-trading roadmap

Implement only after the manual suite is reliable: decision journal, local paper portfolio, manual accept/reject paper proposals, entry/exit records, PnL, benchmark/cash comparison, drawdown, hit rate/payoff, forward evidence diary and outcome checkpoints after 20/60/120 trading days.

### Future automatic-execution roadmap

Keep as architecture documentation only until separately approved. Required prerequisites are paper mode first, broker abstraction, order preview, explicit confirmation, max order value, max position size, max daily turnover, max daily loss, max drawdown kill switch, cooldown periods, market-hours checks, stale-data blocks, news/event-risk blocks, audit log, emergency disable, no LLM trade authority and no model-only trade authority.

### Rejected or delayed features

Rejected or delayed features include autonomous broker execution now, direct LLM portfolio management, RL trading agents, martingale/grid systems, futures/intraday implementation now, news sentiment as direct score authority, short-sample return screenshots as evidence, options/scalping/0DTE/binary/crypto bot experiments unless separately scoped, pair-trading/cointegration as default scoring and triple-barrier/purged-CV ML until enough data and a justified classifier exist.

## Issue Workflow

Issue files:

- `issues/open.md`
- `issues/closed.md`
- `issues/templates/feature_request.md`
- `issues/templates/bug.md`
- `issues/templates/research_task.md`

Every issue opened, implemented, rejected or closed must update this file. Do not close an issue unless acceptance criteria, tests, UI visibility where user-facing, audit/export updates where relevant, `plan.md` updates, `issues/open.md` updates, `issues/closed.md` updates, rebuild, rebuilt app start, workflow smoke test and remaining limitation records are complete. Rejected and research-only ideas must be recorded so they are not repeatedly reintroduced.

## Current Open Priorities

P0/P1 current priorities:

1. `ISSUE-0011` - Full main-UI button reliability audit.
2. `ISSUE-0012` - Visible progress/status indicators and Activity Log/Run Log.
3. `ISSUE-0067` - Local score history and per-instrument total-score evolution mini charts.
4. `ISSUE-0013` - Rebuild package after every completed feature.
5. `ISSUE-0014` - End-to-end workflow test.
6. `ISSUE-0045` - UI semantic locators and visual smoke tests.

## Implementation Order

### Phase A - tracker and plan repair

1. Restore missing issues.
2. Add `ISSUE-0011` to `ISSUE-0066`.
3. Update `plan.md`.
4. Cross-link duplicates.
5. Verify issue numbering.

### Phase B - UI reliability before new features

1. `ISSUE-0011` button reliability audit.
2. `ISSUE-0012` progress/status indicators.
3. `ISSUE-0067` local score history and total-score evolution mini charts.
4. `ISSUE-0013` rebuild gate.
5. `ISSUE-0014` end-to-end workflow test.
6. `ISSUE-0045` UI semantic/visual smoke tests.

### Phase C - app shape

1. `ISSUE-0015` roadmap page.
2. `ISSUE-0016` navigation redesign.
3. `ISSUE-0018` watchlist/universe manager.
4. `ISSUE-0019` instrument detail page.
5. `ISSUE-0035` data health centre.

`ISSUE-0035` was closed on 2026-07-10 after the responsive Data Health inventory, Dashboard summary, CSV export, final rebuild and application smoke checks passed. See `issues/closed.md` for the recorded issue entry.

### Phase D - news/context

1. `ISSUE-0007` contradiction panel.
2. `ISSUE-0025` free news and filings dashboard.
3. `ISSUE-0054` point-in-time validation.
4. `ISSUE-0055` optional free providers.
5. `ISSUE-0058` promotional-claim detector.

### Phase E - research-suite depth

1. `ISSUE-0020` screener.
2. `ISSUE-0021` portfolio sandbox.
3. `ISSUE-0022` ETF overlap.
4. `ISSUE-0023` stock fundamentals.
5. `ISSUE-0024` event calendar.
6. `ISSUE-0026` macro regime.
7. `ISSUE-0027` forecast lab.
8. `ISSUE-0028` backtest lab.
9. `ISSUE-0029` strategy builder.

### Phase F - paper trading and future execution architecture

1. `ISSUE-0030` decision journal.
2. `ISSUE-0031` paper trading.
3. `ISSUE-0057` forward evidence diary.
4. `ISSUE-0032` future broker architecture.
5. `ISSUE-0066` reconciliation/source-of-truth architecture.

## Completed Issue Work

- `ISSUE-0001` - Created Markdown issue tracker, templates and root plan synchronisation.
- `ISSUE-0002` - Added price-row maturity proxy, young/noisy labels, high-score sanity warnings, UI chips, scoreboard columns and tests.
- `ISSUE-0003` - Added yfinance benchmark return, instrument return, beta, correlation, alpha proxy, t-stat, no-causality label and sector/theme warning fields for configured ETFs.
- `ISSUE-0004` - Added backtest return hit rate, average win/loss return, payoff ratio, expected value per period, payoff warning, UI columns, audit export fields and stale-cache invalidation.
- `ISSUE-0005` - Added signal-level low/base/high cost bps, edge-to-cost stress ratios, warning labels, assumption text, signal-table visibility and audit export fields.
- `ISSUE-0006` - Added backtest validity, model contamination risk, model authority reason and calibration-required fields with UI chips, scoreboard export and tests that optional model scores cannot rescue weak deterministic evidence.
- `ISSUE-0009` - Added source URL, source type category, evidence grade, credibility, promotional risk, reproducibility and claim-quality metadata to manual notes and audit markdown.

These completed issues remain closed only for their implemented acceptance criteria. Broader report findings are reopened as follow-up issues in `issues/open.md`.

## Cross-Linked Follow-Ups

- `ISSUE-0002` -> `ISSUE-0057` for real paper/forward evidence.
- `ISSUE-0003` -> `ISSUE-0052`, `ISSUE-0059` for crowding and sector/theme attribution.
- `ISSUE-0004` -> `ISSUE-0049`, `ISSUE-0065` for tail/payoff diagnostics.
- `ISSUE-0005` -> `ISSUE-0050`, `ISSUE-0064` for execution realism and net edge.
- `ISSUE-0006` -> `ISSUE-0010` for the LLM thesis diary.
- `ISSUE-0007` -> `ISSUE-0025`, `ISSUE-0054`, `ISSUE-0055`, `ISSUE-0058`.
- `ISSUE-0008` -> `ISSUE-0015`, `ISSUE-0029`, `ISSUE-0056`, `ISSUE-0060`.
- `ISSUE-0009` -> `ISSUE-0058`.
- `ISSUE-0018` -> candidate management and watchlists.
- `ISSUE-0019` -> detail requirements from news, forecasts, backtests, paper trading and decision journal.
- `ISSUE-0028` -> `ISSUE-0049`, `ISSUE-0050`, `ISSUE-0065`.
- `ISSUE-0031` -> `ISSUE-0057`.
- `ISSUE-0032` -> `ISSUE-0066`.
- `ISSUE-0046` -> `ISSUE-0051`, `ISSUE-0063`.
- `ISSUE-0067` -> `UPDATEV2-0022`, `ISSUE-0047`, `ISSUE-0034` for score component audit trail, feature-driver explanations and "what changed since last run" comparisons.

## Rejected Or Research-Only Scope

- Autonomous broker execution now.
- Direct LLM portfolio management.
- Reinforcement-learning trading agents.
- Martingale and grid systems.
- Futures or intraday implementation now.
- News sentiment as direct score authority.
- Short-sample return screenshots as evidence.
- Options/scalping/0DTE/binary/crypto bot experiments unless separately scoped.
- Triple-barrier/purged-CV ML labels until a classifier is justified.
- Pair-trading/cointegration as a default module.

## Evidence Maturity And Sanity Warnings

The simple score model now records `evidence_sample_days`, `evidence_maturity_state`, `evidence_maturity_label`, `too_good_to_be_true_warning`, `evidence_sanity_warnings` and `evidence_warning_count`. Warnings are conservative and cannot improve final score. Unknown sample length is not treated as mature.

## Score History And Score Evolution Charts

The app must persist every generated score run locally so the user can see whether an ETF or stock is improving, deteriorating or staying stable. This is tracked as high-priority `ISSUE-0067`.

Required local storage:

```text
data/derived/score_history.parquet
data/derived/score_metric_history.parquet
```

Minimum score history fields:

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

Minimum metric history fields:

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

UI requirement: every expanded ETF/stock row in the main Scores view must include a compact line/sparkline chart of `final_combined_score_10` over time. The chart must show at least the latest score, previous score and delta when available. If fewer than two score snapshots exist, show a clear "history will appear after another run" state instead of a blank chart. The chart is informational only and cannot alter actions.

## Benchmark Attribution

Configured ETF score rows now record benchmark id, attribution window, benchmark return, instrument return, beta, correlation, alpha proxy, alpha t-stat, descriptive attribution label and sector/theme warning. Candidate rows keep attribution pending until candidate price history is promoted into the clean yfinance price panel.

## Backtest Payoff Diagnostics

Backtest results now record return hit rate, average win/loss return, payoff ratio, expected value per period and payoff asymmetry warning. The Backtests page displays hit rate only alongside payoff ratio, expected value and warning text.

## Cost Stress Diagnostics

Generated signals now record low/base/high cost bps, low/base/high edge-to-cost ratios, cost stress warning and assumption text. The signal table displays the cost stress warning, and audit export `02_signal_table.csv` includes all stress fields.

## Model And Backtest Validity

Simple score rows now record backtest validity, model contamination risk, model authority reason and calibration-required status. Optional model components cannot override low evidence quality or weak deterministic/risk support.

## Manual Note Source Credibility

Manual research/news notes now record source URL, source type category, evidence grade, source credibility, promotional risk, reproducibility and claim quality. These fields are audit context only and cannot alter scores or final actions.

## Evidence Limits

The Reddit/community research in `report.md` is prioritisation evidence, not proof that any trading method works. App claims must be supported by local data, deterministic calculations, tests or explicit `N/A`/limitation labels.

## 2026-07-09 Two-Tier Stock/ETF Universe

The app now separates the analysis universe into two visible tiers:

- **Primary tier**: first-class configured stocks and ETFs in `configs/universe.yaml`. These use yfinance now and are eligible for future multi-provider enrichment through the provider roadmap already tracked in this plan.
- **Secondary tier**: yfinance-only stocks, ETFs and listed certificates in `data/raw/trade_candidates/yahoo_trade_candidates_2026-07-09.csv`.

Removed primary entries:

- `JAPAN_EQUITY`
- `GLOBAL_BONDS`
- `GOLD_HEDGE`

Primary tier IDs and yfinance symbols:

```text
VWCE -> VWCE.DE
LYP6 -> LYP6.DE
SPYK -> SPYK.DE
SXRJ_EMU_SMALL -> SXRJ.DE
EXX1 -> EXX1.DE
UCG -> UCG.MI
SU -> SU.PA
LR -> LR.PA
PRY -> PRY.MI
NEX -> NEX.PA
DB1 -> DB1.DE
ENX -> ENX.PA
VIE -> VIE.PA
SGO -> SGO.PA
FLXI -> FLXI.DE
H4ZT -> H4ZT.DE
```

Secondary tier IDs and yfinance symbols:

```text
AIR -> AIR.PA
BA -> BA.L
BRK_B -> BRK-B
AM -> AM.PA
IDR -> IDR.MC
KOG -> KOG.OL
KMAR -> KMAR.OL
LDO -> LDO.MI
MSFT -> MSFT
RR -> RR.L
SAAB_B -> SAAB-B.ST
SPCX -> SPCX
NONG -> NONG.OL
SBNOR -> SBNOR.OL
HO -> HO.PA
TKA -> TKA.DE
TKMS -> TKMS.DE
EUNK -> EUNK.DE
CBUK -> CBUK.DE
SEC0 -> SEC0.DE
SXRV_NASDAQ100 -> SXRV.DE
JEDI -> JEDI.DE
VFEM -> VFEM.DE
VUSA -> VUSA.AS
EUDF -> EUDF.DE
XAIX -> XAIX.DE
EXUS -> EXUS.DE
XDWU -> XDWU.DE
RABO -> RABO.AS
```

Duplicate rule: the same ISIN or yfinance symbol must not appear in both tiers unless a future issue explicitly documents the reason and UI treatment.

Visibility rule: the Simple Scores main page must show all primary and secondary entries even before fresh yfinance data, algorithms or forecasts have been run. Missing evidence is displayed as `N/A` / `Pending Refresh`; the app must not invent scores or reuse stale removed instruments.

Execution rule for this update: do not automatically run yfinance refresh, deterministic algorithms, TimesFM, Toto or other forecasts after editing the universe. The user will run those workflows manually.

Implementation status on 2026-07-09:

- Complete: primary tier config, secondary tier candidate CSV, provider symbol map, analysis-only portfolio targets, tier labels, pending rows, stale deleted-ID filtering, empty no-refresh startup handling, launcher and desktop shortcut helper.
- Verified: 45 Simple Scores rows build without refresh, split as 16 primary and 29 secondary.
- Verified: `VWCE` appears as `Primary tier`, `MSFT` appears as `Secondary tier`, and `RABO` appears as `Certificate`.
- Verified: full pytest suite passes and Windows package rebuild succeeds.
- Verified: rebuilt app responds on `http://127.0.0.1:8550/` and rendered Browser screenshots show the tiered pending rows and row expansion working.
- Still intentionally not run: yfinance refresh, deterministic algorithms, TimesFM, Toto and other forecasting workflows.

## 2026-07-09 Trust-Critical Implementation Status

Implemented in the current release pass:

- `ISSUE-0069` foundation: `logs/session.jsonl`, session start reset, redaction, action/navigation/workflow logging and Diagnostics UI.
- Provider registry/source authority artefacts: `data/clean/provider_probe_results.parquet` with yfinance enabled and optional SEC EDGAR, FRED, Stooq, RSS, local ESEF, ETF disclosure, PRIIPs KID and methodology sources shown as unavailable until configured/imported.
- Identity resolver artefact: `data/clean/instrument_identity.parquet` for all active primary and secondary instruments.
- Source conflict artefact: `data/clean/source_conflicts.parquet`, schema-valid even when no conflicts are present.
- Evidence ledger and score component audit trail: `data/derived/evidence_ledger.parquet` and `data/derived/score_components.parquet`.
- Score history and metric history: `data/derived/score_history.parquet` and `data/derived/score_metric_history.parquet`.
- Feature drivers, correlation/crowding and benchmark-attribution stores: `data/derived/feature_drivers.parquet`, `data/derived/correlation_clusters.parquet`, `data/derived/benchmark_attribution.parquet`.
- UI surfaces: Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures, News & Context and Diagnostics session-log panel.
- Expanded audit/evidence export: trust stores, redacted configs, plan/open issue snapshots, checksums and `session.jsonl` or unavailable markers.
- Simple Scores expanded rows: local score-history state, feature-driver context, source authority, freshness, N/A reasons and friction-adjusted edge/cost fields.

Verified:

- `.\.venv\Scripts\python.exe -m compileall src` passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_simple_scores.py tests\test_trust_critical_artifacts.py -q` passed.
- `.\.venv\Scripts\python.exe -m pytest -q` passed.
- `.\scripts\build_windows.bat` rebuilt `build\ETF_AI_Cockpit_Portable_v0.1.0`.
- Rebuilt executable started on `http://127.0.0.1:8550/`.
- Real Chrome/Windows smoke verified visible score rows, row expansion, Provider Status, Evidence Ledger, Filings & Statements, ETF Disclosures, News & Context and Diagnostics.

Important limitation:

- Official-source importers are currently safe local inventory/unavailable-state implementations unless local files or provider configuration exist. Full SEC EDGAR, ESEF/iXBRL, PRIIPs KID, ETF disclosure and index-methodology parsing remains open under the related issues until source-specific parsers, fixtures and UI workflows are completed.
- The selected 21 issues remain open unless their full close criteria are met: source, UI, tests, audit/export, docs, rebuild and user-perspective smoke verification.

## 2026-07-10 Closure Checkpoint

`ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` are recorded as completed in `issues/closed.md`; the remaining selected issues and strict parser/provider workflows remain open with their limitations recorded in the issue files.

## 2026-07-11 Final Verification Checkpoint

- Final source fixes were rebuilt and verified with source/native/portable smoke, root and package-cwd launcher tests, Chrome route/workflow checks and audit ZIP validation.
- Closure evaluator state is 4/41 ready and 37 still open. Only `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` were newly closed in this checkpoint; `ISSUE-0035` was already closed.
- SEC EDGAR, ESEF/iXBRL, PRIIPs KID, ETF/index methodology and provider-backed workflows remain open until their strict fixture/parser/UI/export/rebuild/browser gates pass.
- No Git repository exists, no commit was created and `git init` was not run.
