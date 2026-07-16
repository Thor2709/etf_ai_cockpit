# ETF AI Cockpit — Final Completion Blueprint

**Repository:** `Thor2709/etf_ai_cockpit`  
**Research and issue-audit date:** 15 July 2026  
**Repository revision reviewed:** `e149db50945401fb014955f0f79794a909796a75`  
**Current canonical open issues audited:** 76  
**New implementation-ready issues proposed:** 83  
**Final combined completion programme:** 159 open work items, ending with `ISSUE-0152` final certification

## 1. Executive verdict

ETF AI Cockpit already contains unusually strong foundations for a personal research application: source authority, evidence provenance, explicit unavailable states, score histories, filing parsers, optional forecast adapters, backtest safeguards, audit packets and a broad local user interface. Its strongest capability is **evidence governance**, not yet the depth or validation of its investment algorithms.

Against the final target—long-term stock/ETF analysis plus a guarded automatic trading system—the principal missing systems are:

1. a canonical point-in-time data and revision model;
2. one unified scoring and expected-return engine instead of overlapping formula paths;
3. full financial-statement normalisation and sector-specific stock analysis;
4. complete fund/share-class, look-through and ETF structural analysis;
5. horizon-specific probabilistic total-return models rather than a score mapped to “edge”;
6. a transparent multi-factor risk model, robust covariance and portfolio optimiser suite;
7. leakage-safe model training, selection, calibration and monitoring;
8. an order-level event simulator, double-entry portfolio ledger and complete paper broker;
9. broker read-only reconciliation, independent controls and staged canary execution;
10. a typed application API, task-oriented frontend, hermetic CI, security and final certification.

The project should **not attempt to reproduce proprietary BlackRock, MSCI, Morningstar or bank models**. Their exact data, risk models, research processes and operational systems are closed, licensed and organisationally specific. The achievable goal is to reproduce the publicly understood institutional disciplines: one source of truth, point-in-time data, factor risk, robust optimisation, scenario analysis, independent controls, reproducibility and operational reconciliation.

## 2. The hard constraint: “fully free with no rate limits”

No internet market-data host or broker can honestly be guaranteed free, unlimited and permanently available. Remote systems have fair-access policies, bandwidth constraints, terms changes, account requirements, exchange entitlements or trading costs. The completion contract must therefore use this definition:

> The **mandatory core** must work without a subscription, API key or vendor call quota, using local data, official bulk files, cached public snapshots and user/broker exports. Network providers with quotas or keys are optional enrichments and can never be release blockers.

This produces four source classes:

| Tier | Source class | May be mandatory? | Examples | Required behaviour |
|---|---|---:|---|---|
| A | User-owned/local files | Yes | Broker CSV/OFX, issuer filings, price Parquet, ETF holdings | Validate, map, checksum, preview, commit atomically and replay offline |
| B | Official bulk downloads | Yes | SEC nightly ZIPs, N-PORT ZIPs, Companies House snapshots/accounts | Cache immutable raw files, resume downloads, respect fair access and parse locally |
| C | Official public endpoints/snapshots | Yes, only with cached replay | Eurostat, World Bank, ECB, national regulators | Snapshot every ingestion; failure must not destroy the last valid generation |
| D | Best-effort or vendor services | No | yfinance, Stooq, FMP, Alpha Vantage, Finnhub, Twelve Data, Tiingo | Optional, capability-probed, quota/licence-labelled and never silently authoritative |

The existing FMP, Alpha Vantage, Finnhub, Twelve Data and Tiingo issues must therefore be reclassified as **optional plugin work**, not mandatory product completion. yfinance remains useful for convenient personal research, but its own documentation frames it as an unaffiliated research/education tool and points users to Yahoo’s personal-use terms. It cannot be the sole source for a certified automated system.

Actual broker trading also cannot be guaranteed cost-free or unlimited: commissions, spreads, taxes, exchange subscriptions, account minimums and broker pacing limits are external facts. The software and mandatory research pipeline can remain free; the app must disclose external costs before live execution.

## 3. What institutional-grade capability actually means

The gap with large institutions is not mainly the absence of a secret “BlackRock algorithm.” It is the combination of the following systems:

### 3.1 Common, governed data

- Stable entity, security, fund, share-class and listing identities.
- Point-in-time facts, amendments, restatements and data vintages.
- Corporate actions, total returns, FX and exchange calendars.
- Complete lineage from raw source to feature, score, forecast, target and order.
- Automated anomaly detection, quarantine and reconciliation.
- Explicit coverage, staleness, uncertainty and source authority.

### 3.2 Research depth

- Multi-period statements rather than current ratios.
- Profitability, cash flow, capital efficiency, capital allocation and balance-sheet strength.
- Sector-specific metrics for banks, insurers, REITs, utilities, cyclicals and innovation sectors.
- ETF economics, tracking, legal structure, counterparty exposure, holdings and look-through factors.
- Horizon-specific expected-return distributions, not merely a technical rank.
- Credible simple baselines before complex machine learning.

### 3.3 Portfolio and risk systems

- Factor, country, sector, currency and specific-risk decomposition.
- Robust covariance estimation and uncertainty diagnostics.
- Stress testing, reverse stress and tail-risk analysis.
- Multiple constrained allocation methods with equal-weight/no-trade baselines.
- Turnover, capacity, transaction-cost, cash and tax-lot awareness.
- Performance, risk, decision and transaction-cost attribution.

### 3.4 Validation and model governance

- Point-in-time universes and delisting controls.
- Walk-forward and nested validation.
- Purging and embargo where outcomes overlap.
- Recording all tested variants, not only winners.
- Multiple-testing controls, DSR/PBO-style diagnostics and block-bootstrap uncertainty.
- Champion/challenger promotion, drift, demotion and retirement.
- Immutable experiment, dataset, formula and model versions.

### 3.5 Operational safety

- Signals do not directly become orders.
- Targets, proposals, risk gates and orders are separate states.
- Double-entry accounting and deterministic replay.
- Broker read-only reconciliation before submission authority.
- Independent pre-trade limits and kill switches.
- Incident response, recovery drills and tamper-evident audit trails.

## 4. Target system architecture

```text
Official bulk / cached public / user imports / optional providers
                              │
                              ▼
                  Raw content-addressed evidence
                              │
                              ▼
   Identity + bitemporal facts + data-quality quarantine + lineage
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
  Stock/ETF feature & score engine      Training/forecast laboratory
              │                                │
              └───────────────┬────────────────┘
                              ▼
              Horizon-specific return distributions
                              │
                              ▼
           Factor risk + scenarios + constrained optimiser
                              │
                              ▼
                 Target-to-proposal policy engine
                              │
       ┌──────────────────────┼───────────────────────┐
       ▼                      ▼                       ▼
  Research only          Paper broker          Broker read-only
                                                   │
                                                   ▼
                                      Draft order / capped canary
```

The analytical lake should use versioned Parquet and DuckDB. Transactional state—jobs, experiments, journals, accounts, ledger entries, orders and incidents—should use SQLite in WAL mode. Both stores must share stable IDs and immutable run/version records.

## 5. Required data programme

### 5.1 Identity and reference data

Required fields include legal entity, instrument, share class/fund, listing, ISIN, LEI, CIK/national ID, ticker, MIC, currency, valid-from/to, successor/predecessor and confidence. ISO MIC, SEC submissions, Companies House, issuer documents and user mappings can build the free core. Proprietary taxonomies such as GICS or ICB must not be copied without rights; the app should maintain an open internal taxonomy mapped to public SIC/NACE-style codes.

### 5.2 Prices and corporate actions

The app must retain raw OHLCV separately from splits, dividends, capital gains, rights, spin-offs, mergers and currency changes. It should construct declared adjusted and total-return series locally. User/broker/exchange history is the only genuinely quota-independent universal fallback; yfinance and Stooq can remain best-effort enrichments.

### 5.3 Company fundamentals

The mandatory route should use official filings and local import:

- SEC EDGAR nightly submissions/company-facts bulk archives for the United States;
- ESEF/iXBRL and national OAM/regulator sources in Europe;
- Companies House monthly company and daily/monthly accounts products for the United Kingdom;
- manual official filing import for unsupported jurisdictions.

The application must preserve amendments and build both “latest restated” and “known at the historical date” statement views.

### 5.4 ETF data

The fund programme requires issuer document registry, PRIIPs KID, prospectus, annual/half-year reports, index methodology and full/partial holdings. SEC N-PORT gives a valuable official bulk route for US registered funds. European ETF coverage will often require issuer files or user downloads because no single free universal database exists.

### 5.5 Macro, factors and benchmarks

Use locally cached official data such as Eurostat, World Bank, ECB, US Treasury and selected central-bank/statistical releases. Use Kenneth French and AQR downloadable research data for validation/reference, not as hidden proprietary risk models. Every series needs units, frequency, country, currency, release/vintage and transformation metadata.

### 5.6 News and events

News can remain optional context. The app must not promise unlimited comprehensive news. Mandatory event support should come from official filings, corporate actions, issuer calendars and user imports. RSS may provide best-effort context, but unavailable news must never block the core analysis.

## 6. Final algorithm architecture

### 6.1 Four distinct outputs

The final headline should not collapse everything into one unexplained number. Each instrument should expose:

1. **Underlying quality/exposure** — business economics for stocks; fund/exposure quality for ETFs.
2. **Expected-return distribution** — horizon-specific gross and net return quantiles.
3. **Risk and implementation** — volatility, drawdown, tail, liquidity, concentration and costs.
4. **Evidence confidence** — coverage, freshness, authority, conflict, stability and validation.

A user-friendly 0–10 summary may remain, but it must be a presentation over these separate outputs.

### 6.2 Stock analysis

The common stock model requires:

- profitability and margin durability;
- earnings quality and accruals;
- balance-sheet liquidity, leverage and refinancing;
- cash conversion and free cash flow;
- capital allocation, dividends, buybacks and dilution;
- growth, revisions and guidance where point-in-time evidence exists;
- ROIC, incremental ROIC, reinvestment and economic profit;
- relative valuation, DCF/FCFE, reverse DCF and residual income;
- shareholder yield, FX and scenario risk;
- peer-relative and own-history normalisation.

Sector adapters must then replace inapplicable metrics. Banks require capital, asset-quality and funding evidence; insurers require underwriting/reserves/solvency; REITs require FFO/AFFO/NAV/occupancy/LTV; utilities require regulated assets and funding; cyclicals require normalised margins, costs and reserves/backlog; software/semiconductors/healthcare require intangible, dilution, concentration, product/pipeline and event risks.

### 6.3 ETF analysis

ETF scoring must focus on:

- TER/OCF, tracking difference and tracking error;
- assets, age, flows/closure proxies and share-class structure;
- holdings coverage, concentration, nested funds and look-through factors;
- benchmark methodology and expected turnover;
- replication, derivatives, collateral, counterparty and lending;
- liquidity, spread, premium/discount, order-size capacity and underlying liquidity;
- domicile, distribution, currency and hedge context;
- momentum, volatility, drawdown and portfolio fit.

Stock ratios must not be applied directly to an ETF. Valuation and quality must be aggregated through holdings or benchmark exposure with unresolved-weight disclosure.

### 6.4 Expected return

For a stock, the long-horizon structural estimate should approximately decompose into:

```text
normalised earnings/cash-flow growth
+ dividend yield
+ net buyback yield
- dilution
+ valuation-multiple change
+ FX effect
- implementation cost
```

For an ETF:

```text
look-through exposure return
+ distributions/income
- TER and tracking drag
+ FX/hedging effect
- implementation cost
```

Outputs should include median, 10th/25th/75th/90th percentiles, probability of loss, expected shortfall, benchmark/cash-relative return, bull/base/bear scenarios and uncertainty decomposition. Daily TimesFM/Toto paths must not simply be extrapolated for five or ten years.

### 6.5 Factor risk and portfolio construction

The transparent local risk model should include market, size, value, momentum, profitability/quality, investment, low-volatility, industry, country and currency exposures, plus specific risk. Covariance estimators should include simple sample/diagonal, EWMA, shrinkage, robust and factor approaches. Every advanced optimiser must compete with equal weight, inverse volatility, no-trade and other simple baselines.

Candidate optimisers include minimum variance, equal risk contribution, HRP/HERC, maximum diversification, CVaR, Black–Litterman and robust mean-risk. Riskfolio-Lib, skfolio, PyPortfolioOpt and CVXPY provide useful permissive implementations, but they must sit behind internal contracts and pass independent tests.

### 6.6 Machine learning

TimesFM and Toto are useful challengers for time-series and uncertainty tasks, but their main papers are developer-authored and primarily evaluate general/observability datasets rather than long-term equity alpha. They should remain low authority until finance-specific, point-in-time, net-of-cost and forward validation passes.

The model zoo must begin with naive, historical-median, linear/regularised, state-space, volatility and tree baselines. Complexity is promoted only when it improves untouched walk-forward results, calibration and economic outcomes after costs. Synthetic data is for invariants, rare failures and robustness—not evidence that a strategy is profitable.

## 7. Comparable systems and what to reuse

| System | What it demonstrates | Appropriate reuse | Important boundary |
|---|---|---|---|
| BlackRock Aladdin / MSCI BarraOne | Common data, risk, stress, portfolio and operational integration | Product capabilities and control architecture | Proprietary data/models cannot be copied or claimed equivalent |
| Morningstar Direct | Central research, screening, portfolio and reporting workflow | Information architecture and comparison workflow | Commercial data and ratings are not free |
| SimCorp One | Source of truth, positions/cash/risk/compliance and audit | Operational data model and reconciliation principles | Closed source; use as comparator only |
| Qlib | Data/model/workflow/backtest research platform | Selective architecture and experiment patterns | Do not replace the app wholesale or inherit market assumptions blindly |
| OpenBB | Provider abstraction and data integrations | Provider contracts and optional separate service | AGPL obligations require explicit review |
| Riskfolio-Lib / skfolio / PyPortfolioOpt | Optimisers, risk measures and modular portfolio construction | Direct dependency behind internal interfaces after intake | Inputs remain estimation-sensitive; always retain naive baselines |
| Darts / MLflow / Optuna | Forecasting, experiment lineage and bounded optimisation | Training centre components | HPO must run inside nested validation |
| Ghostfolio / Portfolio Performance | Portfolio accounting, imports, self-hosting and user workflows | UX/accounting/import patterns | Licences and architecture differ; do not copy casually |
| LEAN / NautilusTrader | Event-driven backtest/live parity and order semantics | One isolated future execution engine or reference implementation | Choose one after proof-of-concept; do not duplicate both cores |

All third-party adoption must pass `ISSUE-0079`: exact version/commit, code/data/model licence, activity, tests, security, copied files, notices, conformance suite and upstream update policy.

## 8. Validation and evidence controls

Financial-factor evidence is observational, heterogeneous and exposed to publication/data-mining bias. Harvey, Liu and Zhu argue for a materially higher hurdle in a factor “zoo”; Chen provides a credible contradictory reassessment suggesting many findings may still be real. McLean and Pontiff find out-of-sample and post-publication decay. The correct engineering response is not to reject factors or accept them wholesale, but to require:

- a priori economic mechanism and formula registration;
- all tested variants and trial counts;
- robust peer/universe construction;
- untouched walk-forward tests;
- purging/embargo for overlapping outcomes;
- multiple-testing and selection-bias diagnostics;
- costs, turnover, capacity and liquidity;
- subgroup/regime/period stability;
- confidence intervals and simple baselines;
- paper-forward evidence before execution authority.

Portfolio methods also require humility. DeMiguel, Garlappi and Uppal show how estimation error can make naive 1/N difficult to beat. Ledoit–Wolf shrinkage, factor models and robust optimisation improve inputs, but none removes expected-return uncertainty. Every optimiser result must therefore expose sensitivity and compare with no-trade/equal-weight alternatives.

## 9. Staged trading system

The execution ladder is:

| Stage | Capability | Required evidence |
|---|---|---|
| 0 | Research scores and return distributions | Point-in-time data, formula lineage and validation |
| 1 | Shadow/frozen proposals | Portfolio/risk policy, no broker access, later outcomes |
| 2 | Full paper orders and fills | Event engine, double-entry ledger, costs/actions and replay |
| 3 | Broker read-only | Official API/statement sync and stable reconciliation |
| 4 | Draft orders | Independent limits, preview and explicit confirmation |
| 5 | Capped automatic canary | Final certification, small approved account/strategy/instruments and auto-demotion |
| 6 | Broader automatic use | Separate approval based on sustained forward and operational evidence |

A score can never directly call a broker. The chain is evidence → features → return distribution → optimiser → target → proposal → independent controls → order → broker fill → reconciliation. Unknown broker state, stale data, model expiry, unresolved conflicts or a breached limit must fail closed.

## 10. Issue programme

### 10.1 Existing backlog

All 76 canonical current open issues remain relevant, but many must be expanded or reclassified. In particular:

- `ISSUE-0038` must become a storage implementation epic rather than only a migration plan.
- `ISSUE-0023` must become the integration point for the full stock-analysis stack.
- `ISSUE-0031` must become a complete paper broker rather than a PnL list.
- `ISSUE-0032`, `ISSUE-0060` and `ISSUE-0066` must be reconciled with the new staged-execution ADR.
- `ISSUE-0064` must stop deriving expected edge directly from a score once the return-distribution engine exists.
- `UPDATEV2-0023/0024/0025/0030` vendor integrations become optional plugins and cannot block final completion.

The full issue-by-issue audit is provided in `ETF_AI_Cockpit_Current_Open_Issues_Audit.md` and CSV form.

### 10.2 New backlog

The 83 proposed issues are distributed as follows:

- **Attribution:** 1
- **Audit & reproducibility:** 1
- **Backtest & execution:** 2
- **Benchmarking:** 1
- **Broker integration:** 1
- **Data platform:** 2
- **Data programme:** 11
- **Documentation:** 1
- **ETF analysis:** 5
- **Execution:** 1
- **Execution analytics:** 1
- **Execution safety:** 2
- **Expected return:** 2
- **Extensibility:** 1
- **Final certification:** 1
- **Foundation & governance:** 2
- **Frontend & API:** 5
- **Governance:** 1
- **Model governance:** 1
- **Model research:** 8
- **Paper trading:** 1
- **Performance:** 1
- **Performance & release:** 1
- **Portfolio construction:** 2
- **Quality & release:** 3
- **Reproducibility:** 1
- **Risk & scenarios:** 1
- **Risk model:** 2
- **Scoring architecture:** 1
- **Security:** 1
- **Security & release:** 1
- **Security & resilience:** 1
- **Stock analysis:** 12
- **Supply-chain governance:** 1
- **Trading foundation:** 3
- **Workflow platform:** 1

The exact append-ready specifications are in `ETF_AI_Cockpit_New_Issues_Ready_To_Append.md`. The final issue, `ISSUE-0152`, is deliberately a finite certification gate: the application is not “fully done” until all prerequisite records, clean installations, offline core, analyses, training, backtests, paper operations, authorised broker stage, security, legal, reproducibility and recovery evidence pass.

## 11. Dependency-ordered implementation sequence

### Wave A — scope and foundations

`ISSUE-0070` through `ISSUE-0079`: freeze scope; refactor boundaries; implement storage, bitemporal data, one score engine, versioning, plugins, durable jobs, performance budgets and OSS governance.

### Wave B — data and identity

`ISSUE-0080` through `ISSUE-0090`: mandatory no-quota policy, bulk cache, identity, classification, actions, calendars, imports, official filing coverage, macro/factor warehouse, data quarantine and catalogue.

### Wave C — complete stock and ETF research

`ISSUE-0091` through `ISSUE-0107`: statements, stock fundamentals/valuation/sector adapters, ETF economics/structure/look-through/liquidity/tax-currency context.

### Wave D — expected return, risk and portfolio

`ISSUE-0108` through `ISSUE-0116`: return distributions, uncertainty, factor/covariance risk, benchmarks, optimiser, rebalancing, stress and attribution.

### Wave E — training and model governance

`ISSUE-0117` through `ISSUE-0124`: experiment registry, synthetic robustness, leakage-safe features, validation, model zoo, HPO, calibration and monitoring.

### Wave F — event backtest, paper and staged execution

`ISSUE-0125` through `ISSUE-0135`: order-level simulation, survivorship, accounting, costs, paper broker, proposal policy, broker read-only, hard controls, canary, TCA and incidents.

### Wave G — final frontend, security and certification

`ISSUE-0136` through `ISSUE-0152`: typed API, frontend v2, workspaces, accessibility, CI, advanced tests, security, SBOM/signing, privacy, audit reproduction, docs/legal/bias/hardware and final certification.

Dependencies must be respected. In particular, a modern frontend cannot make unstable domain contracts safe, and a broker adapter cannot compensate for a missing accounting ledger or reconciliation model.

## 12. Definition of “fully done”

The certified application is complete only when all of the following are true.

### Analysis function

- A supported stock or ETF can be added and correctly resolved/classified with confidence and manual override.
- Mandatory data can be bootstrapped without subscriptions, keys or vendor quotas.
- All historical evidence is point-in-time and versioned.
- Stocks and ETFs use separate, appropriate analysis stacks and have equal product/test depth.
- Sector adapters exclude inapplicable metrics.
- Every material metric, score, forecast and assumption has historical charts, source and coverage.
- Selectable horizons return probabilistic gross/net outcomes, downside and benchmark/cash comparisons.
- Complex models remain challengers unless they beat simple baselines under leakage-safe, net-of-cost validation.
- Portfolio targets use risk, constraints, uncertainty and costs rather than headline scores.

### Paper and authorised trading function

- Frozen proposals reference immutable data, formula, model, portfolio and policy versions.
- The event engine models order lifecycle, sessions, spreads/costs and corporate actions.
- Double-entry accounting can rebuild all cash, positions, lots and PnL by replay.
- Broker read-only reconciliation is stable before submission rights exist.
- Independent controls and kill switches cannot be bypassed by model code.
- Live mode is disabled on fresh install and restricted to the certified stage.
- Every order/fill/incident is attributable and recoverable.

### Product and release

- Clean offline and online-enrichment first-run journeys pass.
- All migrations, backup/restore, recovery, security and supply-chain gates pass.
- Every critical UI journey is accessible, responsive and packaged-app tested.
- Audit packet v3 can reproduce selected results from immutable inputs.
- No unresolved P0/P1 defects or unexplained numerical discrepancies remain.
- Legal/terms records and limitations match actual behaviour.

“Fully done” means complete against this frozen versioned scope and certification matrix. It cannot mean that markets, laws, broker APIs or research will never change; maintenance and recertification remain necessary after relevant changes.

## 13. Evidence assessment and uncertainty

| Evidence area | Adapted GRADE | Basis | Main limitations / bias controls |
|---|---|---|---|
| Official bulk/public data availability | High | Primary regulator/statistical documentation and downloadable files | Remote fair-use/terms and jurisdiction coverage still apply; snapshots and local replay required |
| Point-in-time, lineage, accounting and reconciliation mechanisms | High for engineering necessity | Deterministic integrity and operational control principles | Product-specific implementation still needs fault injection and independent review |
| Factor and accounting signals | Moderate | Multiple peer-reviewed long-sample studies and international extensions | Observational, not preregistered/RCT; publication bias, heterogeneity, costs and post-publication decay |
| Valuation and long-term return decomposition | Moderate | Accounting identities and established valuation methods | Assumption-sensitive; wide scenarios and reverse-implied expectations required |
| Portfolio optimisation | High for mathematical methods; Moderate for realised superiority | Convex optimisation/risk methods plus extensive empirical literature | Expected returns/covariance are estimated; naive baselines often competitive |
| TimesFM/Toto for equity return prediction | Low / indirect | Strong general time-series developer evaluations | Finance-specific alpha evidence, independence, preregistration and long forward samples are lacking |
| Closed-source institutional product comparison | Low / indirect | Vendor descriptions and public product material | Cannot verify proprietary algorithms, data quality or claimed outcomes; use only for capability architecture |
| Automated live trading safety | Moderate before canary | Strong engineering mechanisms and broker/accounting principles | Real reliability requires broker-specific sandbox/canary operation, incidents and ongoing monitoring |

No RCT is applicable to most software architecture or historical asset-pricing questions. Most finance studies are observational and not preregistered. Funding and conflicts should be recorded per model/data source: foundation-model papers are written by their developers; vendor product pages are marketing material; academic factor studies can have publication and researcher-selection bias. The programme therefore requires independent baselines, full trial histories, out-of-sample tests and forward paper evidence rather than accepting any single paper or company claim.

## 14. Final recommendation

Do not start with more model weights, a visual redesign or a live broker button. The highest-leverage order is:

1. scope/authority ADR;
2. architecture, storage, bitemporal data and one score engine;
3. identity and official/local data pipeline;
4. complete stock and ETF domain models;
5. return distributions, risk, optimiser and stress;
6. training/validation governance;
7. event-driven paper accounting;
8. broker read-only and independent controls;
9. frontend v2 and final certification;
10. only then, capped automatic canary execution.

That sequence is what turns the existing evidence cockpit into a defensible long-term investment and trading platform rather than a larger collection of indicators.
