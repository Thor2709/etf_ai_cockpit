# AI Evidence Cockpit Report

This report is synchronised with `plan.md`, `issues/open.md`, `issues/closed.md` and `ISSUES.md`. It records research-derived product requirements and source references. It is not implementation proof.

## 2026-07-09 Research Update - Provider, Filings, ETF Disclosure and Candle Evidence Expansion

The app remains local-first and advisory-only. The next major upgrade should be source-authority and evidence-ledger infrastructure. Adding more APIs is useful only if providers are optional, capability-probed, cached, source-ranked, rate-limited and unavailable-safe. Official filings and ETF disclosure stacks are more important than adding another price API. European investing requires ESEF/iXBRL and ETF-disclosure support. Candle evidence is useful as low-authority context only.

The required evidence flow is:

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

Never:

```text
API says X -> trust X blindly
LLM says buy -> buy
candle pattern appears -> trade
vendor statement says revenue -> override official filing
ETF factsheet missing -> infer holdings
```

## New Source Authority Model

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

Hard ranking:

```text
US statements:
  SEC EDGAR > issuer annual report > FMP/Alpha/Finnhub/yfinance > manual note > LLM

EU statements:
  ESEF/iXBRL official filing > national OAM filing package > issuer annual report > FMP/Alpha/Finnhub/yfinance > manual note > LLM

ETFs:
  issuer official prospectus/KID/report/holdings > regulator/fund register > index provider methodology > exchange listing > vendor/yfinance/FMP > manual note > LLM
```

Conflicts must be explicit, source-ranked and exported. Silent overwriting is forbidden.

## Provider Strategy

Provider priorities:

```text
P0: yfinance default, SEC EDGAR, manual/local, ESEF manual import
P1: France DILA, Netherlands AFM, FMP, Stooq/manual CSV
P2: Alpha Vantage fallback, Finnhub experimental, Tiingo/Twelve Data optional
P3: broad news/forum/reddit context only
```

Stooq, Twelve Data and Tiingo belong to the OHLCV resilience layer, not the official-filing layer. They should be used for fallback and discrepancy checks, with candle-quality caps when providers disagree.

Every provider needs capability probes, unavailable-safe behaviour, quota/rate-limit awareness, API-key redaction and immutable raw response caching.

## European Filings Strategy

ESEF is the mandated electronic reporting format for EU regulated-market issuers. Annual reports are XHTML and IFRS consolidated statements are tagged with Inline XBRL. Build manual ESEF import first, then France DILA and Netherlands AFM discovery, then ESAP discovery later when practical.

European filing facts should outrank vendor-normalised data. Unmapped extension concepts should be retained and warned, not invented or forced into unsuitable metrics.

## ETF Filings-Equivalent Strategy

The ETF equivalent of stock filings is:

```text
prospectus
PRIIPs KID
annual report
half-yearly report
factsheet
full holdings file
index methodology
SFDR pre-contractual / website / periodic disclosures
securities lending and collateral disclosure
distribution / tax / share-class documents
```

Holdings freshness and completeness must cap evidence quality. ETF analysis should include exposure, structure, domicile/tax, tracking, liquidity, total cost of ownership, securities lending/collateral, SFDR disclosure consistency and portfolio overlap.

## Candle Evidence Strategy

Candles are useful as OHLCV context and manual audit, but they are low-authority.

Rules:

- Candle features require valid OHLCV.
- Candle contribution is capped.
- Named patterns do not directly trigger actions.
- Candle evidence cannot rescue weak deterministic evidence.
- Candle evidence cannot override hard gates.
- Backtests use next-bar execution.
- Ambiguous OHLC stop/target paths are reported.

## CrossCompatibleInvestmentApp Reuse Notes

Useful reference modules from `Thor2709/CrossCompatibleInvestmentApp`:

```text
investment_desk/yahoo_finance.py
investment_desk/exchange_support.py
investment_desk/storage.py
investment_desk/analysis_confidence.py
investment_desk/sec_financial_statements.py
investment_desk/bank_data_sources.py
investment_desk/fx_cache.py
investment_desk/macro_data.py
investment_desk/watchlist_export.py
investment_desk/portfolio_imports.py
```

Port ideas, not the old app shell. Do not port old buy/sell wording, simple price-only recommendation logic, generated runtime data or fragile background auto-refresh without visible status and locking.

## Testing And Rebuild Rule

Before marking any implementation issue closed:

```text
[ ] Code implemented.
[ ] Unit tests added/updated.
[ ] Mock provider tests added where applicable.
[ ] Existing tests still pass.
[ ] App starts locally.
[ ] Relevant UI button/page works or shows explicit unavailable/error state.
[ ] No API key or secret committed/logged/exported.
[ ] Raw data cached immutably with checksum.
[ ] Clean data written only after validation.
[ ] Source authority and staleness recorded.
[ ] Conflicts are visible.
[ ] Evidence score cannot be rescued by low-authority source.
[ ] Audit packet includes the new evidence.
[ ] REPORT.md updated.
[ ] issues/open.md updated.
[ ] issues/closed.md updated only after tests/rebuild evidence.
[ ] Windows package rebuilt if app/runtime code changed.
```

## updatev2.md Issue Mapping

The proposed update issue numbers conflicted with existing tracker IDs, so they are preserved in `issues/open.md` as namespaced `UPDATEV2-xxxx` IDs:

```text
UPDATEV2-0010 provider registry, capability probes and source authority
UPDATEV2-0011 identity resolver
UPDATEV2-0012 SEC EDGAR importer
UPDATEV2-0013 European ESEF/iXBRL importer
UPDATEV2-0014 France DILA and Netherlands AFM adapters
UPDATEV2-0015 ETF disclosure registry
UPDATEV2-0016 ETF holdings normaliser
UPDATEV2-0017 PRIIPs KID parser
UPDATEV2-0018 ETF prospectus / annual / half-year parser
UPDATEV2-0019 index methodology importer
UPDATEV2-0020 SFDR parser
UPDATEV2-0021 source conflict resolver
UPDATEV2-0022 evidence ledger
UPDATEV2-0023 FMP adapter
UPDATEV2-0024 Alpha Vantage adapter
UPDATEV2-0025 Finnhub adapter
UPDATEV2-0026 candle feature/context/backtest module
UPDATEV2-0027 workflow/button reliability
UPDATEV2-0028 audit packet expansion
UPDATEV2-0029 rebuild/test/update discipline
UPDATEV2-0030 Stooq/Twelve Data/Tiingo OHLCV fallback providers
```

Research-only closures are recorded in `issues/closed.md` as `CLOSED-RESEARCH-001` through `CLOSED-RESEARCH-006`.

## 2026-07-09 Launcher And Sparebanken Execution Evidence

This implementation pass closed only the narrow launcher and Sparebanken run records. It did not close broad product issues or hard parser/provider issues without full evidence.

Implemented:

- shared launcher helper for Windows source/native/portable startup;
- clear readiness and browser-open behaviour;
- fallback port handling when the preferred port is busy but not HTTP-ready;
- locked build-folder handling and alternate portable output folder creation;
- five Simple Scores main-page groups;
- distinct Sparebanken group with honest `needs_verification` ISIN states;
- score/trust artefact propagation for group and ISIN status.

Verification evidence:

- full pytest suite: 129 passed;
- Windows build completed;
- root BAT launcher passed and opened the browser after readiness;
- native packaged smoke passed;
- portable generated runner passed and opened the browser;
- browser screenshots prove grouped main page, row expansion and provider/diagnostics pages render.

Still open:

- semantic locator/accessibility hooks for Flet web;
- full universe manager/provider policy editor;
- data health centre, import/export centre, backup/restore and first-run onboarding;
- SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index methodology and provider-backed workflows until real fixtures, parser tests, UI workflow, audit/export proof and browser smoke verification exist.

## Source Links

Current app / local plan:

- `plan.md`
- `issues/open.md`
- `issues/closed.md`
- `C:\Users\thor2\Downloads\updatev2.md`
- GitHub reference app: `Thor2709/CrossCompatibleInvestmentApp`

SEC / US filings:

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

ESEF / European filings:

- ESMA Electronic Reporting / ESEF: https://www.esma.europa.eu/issuer-disclosure/electronic-reporting
- XBRL International iXBRL overview: https://www.xbrl.org/the-standard/what/ixbrl/
- Arelle: https://arelle.org/
- IFRS Taxonomy: https://www.ifrs.org/issued-standards/ifrs-taxonomy/

ESAP:

- Regulation (EU) 2023/2859: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R2859

UCITS ETF/fund documents:

- UCITS Directive 2009/65/EC: https://eur-lex.europa.eu/eli/dir/2009/65/oj/eng

PRIIPs KID:

- PRIIPs Regulation (EU) No 1286/2014: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R1286

SFDR:

- SFDR Regulation (EU) 2019/2088: https://eur-lex.europa.eu/eli/reg/2019/2088/oj/eng

France OAM / DILA:

- API info-financiere: https://www.data.gouv.fr/fr/dataservices/api-info-financiere/

Netherlands AFM:

- AFM Register of financial reporting: https://www.afm.nl/en/sector/registers/meldingenregisters/financiele-verslaggeving

FMP:

- FMP pricing: https://site.financialmodelingprep.com/pricing-plans
- FMP docs: https://site.financialmodelingprep.com/developer/docs

Alpha Vantage:

- Alpha Vantage support: https://www.alphavantage.co/support/

Finnhub:

- Finnhub stock candles docs: https://finnhub.io/docs/api/stock-candles
- Finnhub profile docs: https://finnhub.io/docs/api/company-profile2
- Finnhub reported financials docs: https://finnhub.io/docs/api/financials-reported
- Finnhub pricing: https://finnhub.io/pricing

XBRL/iXBRL tooling and research context:

- FinReporting paper: https://arxiv.org/abs/2604.05966
- AUDITFLOW paper: https://arxiv.org/abs/2606.03031
- LEDGER benchmark: https://arxiv.org/abs/2606.13100

Candle/backtest context:

- Marshall, Young & Rose candlestick evidence: https://doi.org/10.1016/j.jbankfin.2005.08.007
- Lu and Chen candlestick evidence: https://doi.org/10.1016/j.pacfin.2011.03.001
- Bailey et al. backtest overfitting / PBO: https://doi.org/10.1090/noti1293
- TA-Lib pattern recognition docs: https://ta-lib.github.io/ta-lib-python/func_groups/pattern_recognition.html
- QuantConnect candlestick patterns docs: https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/candlestick-patterns
- Maier-Paape and Platen OHLC ambiguity: https://arxiv.org/abs/2301.07267
- Tepelyan OHLC timing features: https://arxiv.org/abs/2501.01829

## 2026-07-10 Post-Review Launcher Verification

- Corrected latest-launcher use of the build-selected portable path and added alternate native staging for locked folders.
- Final stress build selected `build\flet_dist_20260710_082721` and `build\ETF_AI_Cockpit_Portable_v0.1.0_20260710_083014` while both default outputs were locked.
- The selected packaged executable reached HTTP readiness on port 8568 and rendered the Simple Scores page in the in-app browser.
- Final automated evidence: 51 focused tests passed, the full 131-test suite exited 0, compileall passed and source snapshot smoke passed.
- No broad selected-20 issue or previous-21 trust-critical issue was newly closed; strict parser/provider gates remain enforced.
# 2026-07-10 All-41 Closure Train

## Dependency And Official Fixture Foundation

- Installed and import-verified arelle-release 2.41.7, pdfplumber 0.11.10, defusedxml 0.7.1, feedparser 6.0.12, hypothesis 6.156.4, ruff 0.15.21, mypy 1.20.2 and pytest-timeout 2.4.0.
- Retained six immutable official fixture classes under tests/fixtures/official/: Microsoft SEC company facts and submissions, the filings.xbrl.org Netherlands ESEF index response and selected ESEF report package, a Vanguard PRIIPs KID and the FTSE GEIS ground rules.
- Every fixture records its exact official source URL, UTC retrieval time, SHA-256, document class, authority, entity/period and licence/use note in tests/fixtures/official/manifest.json.
- Total fixture footprint is 23,825,057 bytes. Downloaded bytes are never edited; future malformed fixtures belong only under tests/fixtures/malformed/ and must be labelled synthetic.
- Checksum and provenance tests passed. This foundation does not close parser/provider issues: those still require parser tests, UI workflow, audit/export proof, rebuild and packaged browser verification.

## 2026-07-10 Evidence-Backed Closures

- Earlier checkpoint dossiers for `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` were reopened after independent review found substantive gaps; their implementation evidence remains retained for the next fix cycle.
- Closure evaluator result after the independent review correction: 41 records reviewed, 1 ready (`ISSUE-0035`) and 40 still open. The three earlier checkpoint closures were reopened because their substantive evidence gates were not met. SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows remain open under the strict rule.

## 2026-07-11 Follow-Up Evidence Closures

- `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` were re-evaluated after the trust-policy fixes, final rebuild and fresh Chrome/package evidence.
- Closure evaluator result: 41 records reviewed, 4 ready (`ISSUE-0035`, `ISSUE-0069`, `UPDATEV2-0022`, `UPDATEV2-0028`) and 37 still open.
- The follow-up evidence includes JSON-style secret redaction, unknown source-prefix exclusion, `model_advisory` authority, candle/conflict manifest requirements, exact full-holdings assertions, packaged diagnostics, Evidence Ledger UI, audit export validation and corrected portable launcher execution.
- SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows remain open because the strict fixture/parser/UI/export/browser gates are not all satisfied.

## 2026-07-10 Data Health Closure

- `ISSUE-0035` is closed after responsive Data Health source/UI work, focused and full tests, CSV export validation, final Windows rebuild, source/native/portable smoke and Playwright desktop/1040px browser evidence.
- The final report contains 11 dataset rows with checksum, provenance, freshness, success/failure and warning columns. Computer Use was unavailable for this retry because Chrome URL confidence failed; the limitation is recorded and no Computer Use pass is claimed.
