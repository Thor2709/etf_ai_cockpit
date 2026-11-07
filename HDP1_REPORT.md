# HDP1 report: point-in-time fundamentals history for the historical replay

Branch `data/pit-history-20261021` (cut from `score/int-20261013` cce5ba56), workspace `C:/dev/etf-PITF`. `execution_allowed=false`;
reads only (SEC EDGAR, filings.xbrl.org, GLEIF); no provider writes, no new dependencies. The replay folder, the owner repo,
`C:/dev/etf-SI` and `data/clean/fx.parquet` (owned by CB1) were not touched.

## 0. HDP2 update (ESEF source, certificate hook, parser, ISINs, decision time)

**0.1 ESEF -> `stock_fundamentals` source (approved).** `configs/stock_fundamentals_v1.yaml`: `sources.chain: [sec_edgar, esef, yfinance]`, new `esef_concepts` (field -> ordered ifrs-full concepts) and `esef_rules`.
`stock_sources.parse_esef_statement_facts` (pure) and `fetch_esef` read the imported `data/clean/statement_facts.parquet` (no network); `refresh_stock_fundamentals(..., esef_fetch=...)` appends the rows with `source = "esef"`, `reporting_standard = ifrs`, `known_at` = registry `date_added` of the earliest filing that reported each value (a restated comparative never replaces it; a row is visible at the latest `known_at` of its values).
Annual (FY) periods only; consolidated, undimensioned facts; a field nobody tagged stays absent (never 0); two different values in one filing -> not used. Mapped: revenue, gross profit, EBIT (ProfitLossFromOperatingActivities), pretax, tax, interest expense, D&A, parent income (ProfitLossAttributableToOwnersOfParent), CFO/CFI/CFF/FX effect, PP&E and intangible capex, dividends paid, parent equity, **NCI (NoncontrollingInterests, else the equity-axis NCI member)**, total debt (Borrowings, else long-term + current when both tagged, one side alone = `partial`), leases, cash, assets, liabilities, shares. Payments are stored as positive outflows (as in the SEC path). Share counts are accepted only when every filing that reports the date agrees within 1 percent (SU reports 567 069 000 and 567 069 for the same date in different filings): otherwise `conflicted`, never picked.
Result: 86 `esef` rows for 17 stocks; `stock_fundamentals.parquet` has 271 rows (185 SEC + 86 ESEF). Tagging is uneven: HO.PA and KOG tag their primary statements with issuer extensions (little maps), LR's FY2025 income statement is extension-tagged, only 3 of 15 issuers tag a share count.
**Guard exception (accepted by Opus, conditional):** the `observed` marker applies only because `net_income_parent` maps exclusively from `ifrs-full:ProfitLossAttributableToOwnersOfParent`; the code filters the configured concepts to that one (`ESEF_PARENT_INCOME_CONCEPTS`), so total ProfitLoss can never fill it (test `test_parent_income_never_comes_from_total_profit_loss`). `stock_fundamentals._merged_view` dropped `net_income_parent` whenever non-controlling interest > 0 (an ownership-scope guard written for SEC `NetIncomeLoss`). That removed parent income for every ESEF stock with NCI. The ESEF row now carries an explicit `observed` state on `net_income_parent` (ProfitLossAttributableToOwnersOfParent is parent-only by definition) and the store keeps the value only in that case; SEC and yfinance rows behave exactly as before (test `test_positive_nci_keeps_only_explicitly_parent_attributed_income`). The ROIC guard (consolidated NOPAT vs parent-only capital with NCI) is unchanged, so ROIC stays unavailable for stocks with NCI.

**0.2 Pillar input coverage (inputs that produce a score: stock_value of 5, stock_quality of 6; a pillar needs 2).** Measured with `build_universe_evidence` at the dates shown (probe output: `data/pit_history/pillar_input_coverage.txt`).

| stock | 2023-06-30 value / quality (score) | 2024-06-28 value / quality (score) | 2025-09-30 value / quality (score) | 2026-10-05 value / quality (score) |
|---|---|---|---|---|
| MSFT | 1/5 / 3/6 (6.25) | 1/5 / 4/6 (7.42) | 1/5 / 4/6 (7.17) | 1/5 / 4/6 (6.83) |
| SU | 1/5 / 3/6 (5.17) | 1/5 / 4/6 (5.79) | 1/5 / 4/6 (5.17) | 1/5 / 4/6 (5.0) |
| LR | 0/5 / 2/6 (7.75) | 0/5 / 3/6 (5.61) | 0/5 / 3/6 (5.56) | 0/5 / 0/6 (-) |
| PRY | 0/5 / 3/6 (5.67) | 0/5 / 0/6 (-) | 0/5 / 4/6 (5.33) | 0/5 / 0/6 (-) |
| AIR | 0/5 / 1/6 (-) | 0/5 / 2/6 (4.83) | 0/5 / 2/6 (9.0) | 0/5 / 2/6 (5.0) |
| IDR | 0/5 / 3/6 (7.78) | 0/5 / 4/6 (5.62) | 0/5 / 3/6 (5.76) | 0/5 / 0/6 (-) |
| KOG | 0/5 / 0/6 (-) | 0/5 / 4/6 (6.58) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) |
| LDO | 0/5 / 1/6 (-) | 0/5 / 2/6 (1.0) | 0/5 / 2/6 (2.0) | 0/5 / 0/6 (-) |
| RR | 0/5 / 2/6 (2.5) | 0/5 / 3/6 (3.33) | 0/5 / 0/6 (-) | 0/5 / 4/6 (7.67) |
| SAAB_B | 0/5 / 3/6 (4.33) | 0/5 / 4/6 (3.83) | 0/5 / 4/6 (4.33) | 0/5 / 0/6 (-) |
| BA.L | 0/5 / 2/6 (5.0) | 0/5 / 3/6 (3.67) | 0/5 / 3/6 (5.66) | 0/5 / 3/6 (3.33) |
| CBUK | 0/5 / 2/6 (7.0) | 0/5 / 3/6 (8.33) | 0/5 / 3/6 (7.24) | 0/5 / 3/6 (5.11) |
| SEC0 | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 3/6 (0.67) |
| NEX | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) |
| SGO | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) |
| VIE | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) |
| ENX | 0/0 / 0/0 (-) | 0/0 / 0/0 (-) | 0/0 / 0/0 (-) | 0/0 / 0/0 (-) |
| HO.PA | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) | 0/5 / 0/6 (-) |

* **stock_quality** is now scored for MSFT (4 of 6 from 2024; it was 0-2 of 6 in HDP1 because peers were missing) and for SU, LR, PRY, AIR, IDR, KOG (2024), LDO, RR, SAAB_B, BA.L, CBUK and SEC0 wherever a fresh FY is known. Inputs that score: ROE, EBIT margin, FCF conversion, revenue CAGR (each needs a 3-peer cohort that reports it). Blocked: ROIC (NCI ownership-scope guard), net debt/EBITDA (D&A is tagged by 3 of 15 issuers), and every input when the latest FY is more than 400 days old (for example IDR FY2025 was added to the registry on 2026-10-20, after 2026-10-05).
* **stock_value** stays unavailable for MSFT and every ESEF stock (never 2 inputs). Reasons: no point-in-time share count (tagged by SU and VIE only; the provider count in `stock_snapshots` is fetch-dated, so market cap and every yield/P/E input is unavailable), EV/EBIT needs a complete debt leg, and where a share count exists (SU, MSFT) the peer-relative inputs (earnings yield, FCF yield, P/E vs peers) report `needs 3 peers ... best cohort has 1`. **These are blocked only by the >=3 peer-cohort rule**: SU earnings yield, FCF yield and P/E vs peers; MSFT FCF yield. The rule is unchanged. The share count is not derived from EPS or weighted-average shares. **Decision (Opus): `stock_value` is accepted as unavailable in the replay** (3-peer rule unchanged, no derived share counts); replay stock scores are built from the remaining pillars.
* ENX has no stock evidence at all (non-bank financial sector route, by design); NEX/SGO/VIE are limited by rejected filings (0.4).

**0.3 Per-date certificate rescore hook.** `from scripts.sparebank_refresh import rescore_sparebanks_at`, then `rescore_sparebanks_at(root, decision_day, universe_root=None, only_ids=None)`: no network, no summary file written, no directory created, one score-history run per certificate with `data_as_of_date` = the decision day. `decision_day` is a date (end of that UTC day, 23:59:59), an ISO date, or a timezone-aware datetime; anything else raises. It is `refresh_sparebanks(root, fetch=False, decision_time=D, write_summary=False)` plus that conversion (new `write_summary` flag, default unchanged). Each row: `id, composite, coverage, reason`; a certificate with no filing known at D is `unavailable` with the reason. HB1's `scripts/backfill_score_history.py` was not edited. Smoke test on MING: 6.03 (2022-10-17), 8.09 (2024-06-28), 8.56 (2026-10-05).

**0.4 Parser caps.** `parsers/esef_ixbrl.py`: PDF, images, fonts, scripts, stylesheets, text and HTML pages outside `reports/` (viewers) are skipped before the size check (never read); the 100 MB member cap and the 250 MB total cap stay on every XBRL/iXBRL member; `.exe` etc. are still `unsupported_member`; an `.html` report under `reports/` is accepted in the catalog layout (it caused every `unsupported_package` rejection). Re-import of NEX, UCG, ENX, SGO, VIE, KOG, AIR: 10 filings imported (AIR FY2022; KOG FY2021 and FY2023; NEX FY2022, FY2023, FY2024; UCG 4), the `unsupported_package` rejections are gone. **17 filings are still rejected as `archive_too_large`** (ENX FY2024, FY2025; KOG FY2022; NEX FY2021, FY2025; SGO FY2022, FY2023, FY2025; UCG 6; VIE FY2022, FY2023, FY2024): none of them contains a sizeable non-XBRL member; the single iXBRL report is 106-203 MB. Decision (Opus): the cap is not raised. The registry `json_url` (xBRL-JSON) was assessed: no reader for it exists in the repo (no OIM JSON fact parser, no download path, the import workflow is package-bound), so using it is well over 150 lines plus tests; the 17 filings stay a documented gap (affected: ENX FY2024-25, KOG FY2022, NEX FY2021 and FY2025, SGO FY2022/23/25, UCG 6, VIE FY2022-24).

**0.5 ISINs (GLEIF, sandbox only; `scripts/pit_verify_isins.py`).** A candidate ISIN is verified only if the reverse lookup `filter[isin]` returns exactly one ISSUED record whose legal name matches AND `/lei-records/<LEI>/isins` lists the ISIN. Checked 2026-10-21 (UTC): **CBUK** Cairn Homes plc `IE00BWY4ZF18` -> LEI `635400DPX6WP2KKDOA83` (Cairn Homes Public Limited Company) verified, 5 filings FY2021-FY2025 imported; **SEC0** SECO SpA `IT0005438046` -> LEI `8156008C44408AB6D716` (SECO S.P.A.) verified (GLEIF lists three ISINs for the LEI; the ordinary-share one is taken from the public listing), 2 filings (FY2021, FY2025) imported; **HO** Hochtief AG `DE0006070006` -> LEI `529900Y25S8NZIYTT924` verified, but the registry holds no filing; **KMAR** Kempower Oyj: GLEIF lists no ISIN for LEI `743700EIG9TDB5QNZS09` (the name-only match), so it stays unverified and nothing was imported. The candidates came from public listings and count only after GLEIF confirmed them. Written to `data/pit_history/isin_verification.json` and the sandbox-only `data/pit_history/universe_isin_overrides.json` (read by `pit_history_backfill.py --isin-overrides`); the owner's universe store is untouched. Note the owner store names (Hochtief, Kempower, Cairn Homes, SECO SpA) differ from `configs/universe.yaml` (Thales, Kongsberg Maritime, an iShares ETF) for HO/KMAR/SEC0.

**0.6 Decision time.** The weekly grid stays 2022-10-17 .. 2026-10-05 (208 dates; 2026-10-12 is past the data end 2026-10-09). `LIVE_GRACE_DAYS = 5`: a date within 5 days of the run's "now" gets decision time = now (it would see fetch-dated rows such as the 2026-10-21 snapshots). The new check `check_decision_window` flags such a date: at the actual run time (2026-10-21) the last date 2026-10-05 is outside the window, so it is kept; a run whose clock is before 2026-10-11 must drop it (test `test_replay_dates_inside_the_live_grace_window_are_flagged`). Every row visible at every date satisfies `known_at <= D`: PIT audit **PASS**, 0 violations, including that each `esef` stock row is known at a registry `date_added` instant.

## 1. Result in one paragraph

Two US stocks (SEC) and 19 of 26 other stocks (ESEF; CBUK and SEC0 added in HDP2) plus 14 of 28 Norwegian equity certificates now have as-originally-filed history with real
knowledge times (`known_at` = SEC filing date / filings.xbrl.org `date_added`); 19 ETFs are snapshot-only; the rest have no free PIT source (reason per row in section 4).
**HDP2 update (section 0):** an ESEF source now feeds `stock_fundamentals` (stock_quality scores for most ESEF stocks; stock_value stays blocked by share counts and the 3-peer cohort rule) and `rescore_sparebanks_at` is the per-date certificate hook.
**Important:** the certificate scorecard needs one rescore per decision date (F2). The PIT audit result is **PASS**: 0 violations over 208 weekly decision dates.

## 2. Inventory: what the live scoring / paper-bot path reads

Entry: `portfolio.paper_bots_replay.run_historical_replay` reads only the *stored score history* (`data/derived/score_history.parquet`) plus the price book; every
score row is produced by `signals.simple_scores.build_simple_instrument_scores` (`configs/score_engine_v3.yaml`). Class: **PIT** = PIT-history-available,
**BACKFILL** = needs-backfill (done here where a source exists), **SNAP** = snapshot-only (no free history), **UNUSED** = unused-by-score (label, informational or empty).

| input | path | reader | consumer pillar (headline weight) | class |
|---|---|---|---|---|
| prices (OHLCV, adjusted close) | `data/clean/prices.parquet` | `_latest_price_lookup`, `_price_quality_lookup`, `_price_liquidity_lookup`, `stock_universe.market_inputs`, `PriceBook` | momentum, trend, risk, liquidity_cost, data_quality (ETF 0.165/0.135/0.408/0.292; stock 0.174/0.126/0.162/0.135); stock price multiples; bot execution | PIT 2021-10-11..2026-10-09 (adjusted_close is back-adjusted by later dividends/splits as of the fetch: correct for returns) |
| FX | `data/clean/fx.parquet` | `fx_data.load_fx_rates`, liquidity EUR turnover | liquidity_cost, bot valuation | PIT (CB1 rewrites `available_at`; not edited here) |
| stock statements | `data/clean/stock_fundamentals.parquet` | `stock_fundamentals.periods_for` -> `stock_universe.build_universe_evidence` | stock_value 0.1615, stock_quality 0.175 | BACKFILL: SEC done for MSFT, BRK_B only (F1); no other canonical free PIT source is wired |
| stock profile / provider cap / shares fallback | `data/clean/stock_snapshots.parquet` | `latest_snapshot` | peer profile, cap fallback | SNAP (fetch-dated; the SEC snapshot rows are stamped 2026-10-21, invisible before) |
| analyst estimate revisions | ANALYST rows of `stock_fundamentals.parquet` (yfinance) | `latest_analyst` | analyst_revision 0.0674 (stocks) | SNAP, no free history |
| statement FX for reporting-currency conversion | `data/clean/stock_fx.parquet` | `stock_fundamentals.fx_rate` | stock multiples when reporting currency != quote currency | SNAP (yfinance ~20-day window); not needed for the two USD SEC names |
| bank scorecard evidence | `evidence/norway/<id>-history/*` (+ classification rows in `data/storage/cockpit.sqlite3`) | `financial_institution_views._build_financial_projection_from_evidence`; stored result read by `score_history.latest_sparebank_scores` | native Sparebank scorecard (equity certificates) | BACKFILL done: 14 of 28 certificates (the registry is empty for the rest) |
| statement facts / filings inventory | `data/clean/statement_facts.parquet`, `filings_statements.parquet` | `analysis.decision.shadow_run`, `valuation_views`, instrument detail | decision shadow run, valuation views; **not** the stock pillars | BACKFILL done via ESEF for 15 stocks |
| quality-momentum / look-through fundamentals | `data/clean/fundamentals.parquet` (absent) | `signals.quality_momentum`, `analysis.look_through`, export pack | backtest strategy and shadow only | UNUSED by the score |
| ETF holdings | `data/clean/etf_holdings.parquet` (209 rows, one vintage 2026-10-11, yfinance top holdings) | `_etf_exposure_lookup` | etf_exposure (headline 0.0 since FPQ; risk-role in the action composite) | SNAP; the engine already fails closed when the vintage is after the decision date |
| ETF metadata (TER, AUM) | `data/clean/etf_metadata.parquet` (2026-10-11); `ter` is empty in `configs/universe.yaml` | `_etf_product_quality_lookup` | etf_product_quality (headline weight 0.0) | SNAP; same fail-closed vintage rule |
| PRIIPs KID costs | `data/clean/priips_kid_records.parquet` (empty) | `_kid_record_lookup` | etf_product_quality only | UNUSED (empty) |
| news | `data/clean/news_context.parquet` (empty) | `_news_inventory_lookup` | count shown, no score | UNUSED |
| macro / risk-free proxies | `data/raw/macro` (empty), `configs/risk_free_proxies.json` (no mappings) | `MacroWarehouse`, `_build_local_cash_comparison_lookup` | cash-comparison fields, no score component | UNUSED (empty, informational) |
| forecasts | `data/forecasts/forecast_results_20261009.csv` (single run; history only from 2026-06) | `load_latest_forecasts`, `forecast_component_maps` | baseline/timesfm/toto (headline 0.0, action composite 0.07/0.14/0.21) | SNAP (section 8) |
| backtest trust label | `data/backtests/backtest_results.csv` | `_backtest_trust_lookup` | label only; validity never blocks | UNUSED, full-sample: do not surface in a replay |
| classification | `data/storage/cockpit.sqlite3` (`classification_evidence_v2`) | `classification_score_state`, `read_instrument_context` | warning `classification_unavailable`; bank routing | PIT-capable (available_at); banks gain first-filing-dated rows from the history import |
| universe, static attributes | `configs/universe_store.json`, `configs/universe.yaml` | `config.universe`, `universe_store` | sector, region, currency, isin, lifecycle | static (the owner's fixed list defines membership) |
| cyclical sector adapters | statement facts | `cyclical_sector_adapters` | nothing passes `cyclical_projections` in the score path | UNUSED |

## 3. What was backfilled and how (existing canonical paths, extended minimally)

* **SEC EDGAR** (US names MSFT, BRK_B): `scripts/refresh_stock_fundamentals.py --ids MSFT,BRK_B --sources sec_edgar` (new `--sources` option restricts the configured chain, so restated fetch-dated yfinance rows are never written). 185 rows, as originally filed, `known_at` = filing date. The SEC user agent came from the environment and is in no committed file.
* **ESEF, Norwegian certificates**: `scripts/sparebank_refresh.py --history [--ids ...]` (new): every filings.xbrl.org filing per LEI (GLEIF ISIN lookup, exactly one record), oldest first, into one `evidence/norway/<id>-history` directory, `known_at` = registry `date_added` (fixed-width microsecond UTC), no rescore. Also fixed: ids with an exchange suffix (`ROGS.OL`, `SNOR.OL`, `TRSB.OL`, `VVL.OL`) were rejected by `import_official_filing` ("issuer is not in the configured universe"); both sides are now normalised and the facts are keyed by the configured id.
* **ESEF, every other issuer**: `scripts/pit_history_backfill.py` drives `filing_ingestion_workflows.import_esef_package` (new optional `known_at`) into `data/clean/statement_facts.parquet` / `filings_statements.parquet`. Identities that cannot be verified fail closed (ISIN not verified -> no LEI). 142 registry filings were found for the 56 non-ETF issuers; 3.7 GB were downloaded sequentially (1 s pause, abandon after 5 consecutive errors).
* **ETF holdings/metadata**: SEC N-PORT covers US-registered funds only and the E1 adapters fetch current pages; no adapter takes a dated request, so ETFs stay snapshot-only.
* **yfinance fundamentals**: not backdated and not present in the history stores (the PIT audit fails if a yfinance source appears).
* **PIT-correctness fix in the reader** (`financial_institution_views`): `identity.json` is one file rewritten by every import and pinned the reporting period of every decision to the newest filing, so a decision before that filing returned `financial_evidence_invalid`. It is now ignored when its own `known_at` is after the decision time. Live behaviour is unchanged (known_at <= now).
* Parser limits (HDP2): non-XBRL members are skipped before the size check and an `.html` report is accepted in the catalog layout; 17 filings are still rejected because the single iXBRL report member itself exceeds the 100 MB cap (section 0.4).

## 4. Per-instrument coverage (75 replay instruments; the 6 EXCLUDED rows are omitted)

Columns: fiscal years = period-end years of imported annual filings; first known_at = earliest knowledge time of any imported fact; first weekly decision = first Monday on or after it (2022-10-17 = already known when the replay starts).
Registry `date_added` for Norwegian filings is the time the filing was added to filings.xbrl.org (some are batch dates, e.g. FY2022 on 2023-05-09); that is the conservative, later time.
Full text of the gaps is in `data/pit_history/coverage.csv`.

| id | type | ccy | route | filings reg/imp | fiscal years (period-end year) | first known_at | first weekly decision | gaps + reason |
|---|---|---|---|---|---|---|---|---|
| AASB.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| AIR | stock | EUR | ESEF-facts | 5/5 | 2021,2022,2023,2024,2025 | 2022-03-16 | 2022-10-17 | no FY2020 (not filed/published in the registry, or rejected above) |
| AM.PA | stock | EUR | ESEF-facts | 0/0 | - | - | - | no_filing_in_filings_xbrl_org_registry |
| AURG | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-05-03 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| BA.L | stock | GBP | ESEF-facts | 5/5 | 2021,2022,2023,2024,2025 | 2022-03-30 | 2022-10-17 | no FY2020 (not filed/published in the registry, or rejected above) |
| BIEN.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| BRK_B | stock | USD | SEC | 0/6 | 2020,2021,2022,2023,2024,2025 | 2021-03-01 | 2022-10-17 | - |
| CBUK | stock | GBP | ESEF-facts | 5/5 | 2021,2022,2023,2024,2025 | 2022-04-07 | 2022-10-17 | no FY2020 (not filed/published in the registry, or rejected above) |
| CTEC.AS | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| DB1 | stock | EUR | ESEF-facts | 0/0 | - | - | - | no_filing_in_filings_xbrl_org_registry |
| ENX | stock | EUR | ESEF-facts | 5/3 | 2021,2022,2023 | 2022-04-05 | 2022-10-17 | 2 filing(s) rejected by the ESEF parser: archive_too_large; no FY2020/2024/2025 (not filed/published in the registry, or rejected above) |
| EUDF | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| EUNK | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| EXUS | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| EXX1 | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| FFSB.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| FLXI | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| GRONG.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| H4ZT | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| HELG | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-04-05 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| HGSB.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| HO | stock | EUR | ESEF-facts | 0/0 | - | - | - | no_filing_in_filings_xbrl_org_registry |
| HO.PA | stock | EUR | ESEF-facts | 4/4 | 2021,2022,2024,2025 | 2022-04-07 | 2022-10-17 | no FY2020/2023 (not filed/published in the registry, or rejected above) |
| HSPG | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| IDR | stock | EUR | ESEF-facts | 6/6 | 2020,2021,2022,2023,2024,2025 | 2021-05-19 | 2022-10-17 | - |
| IMAE.AS | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| JAEREN | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| JEDI.DE | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| KMAR | stock | EUR | ESEF-facts | 0/0 | - | - | - | lei_unresolved: universe ISIN is not verified (NEEDS_VERIFICATION) |
| KMAR.OL | stock | NOK | ESEF-facts | 0/0 | - | - | - | no_filing_in_filings_xbrl_org_registry |
| KOG | stock | NOK | ESEF-facts | 4/3 | 2021,2023,2024 | 2022-03-29 | 2022-10-17 | 1 filing(s) rejected by the ESEF parser: archive_too_large; no FY2020/2022/2025 (not filed/published in the registry, or rejected above) |
| LDO | stock | EUR | ESEF-facts | 8/8 | 2021,2022,2023,2024 | 2023-05-30 | 2023-06-05 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| LR | stock | EUR | ESEF-facts | 6/6 | 2021,2022,2023,2024,2025 | 2022-04-07 | 2022-10-17 | no FY2020 (not filed/published in the registry, or rejected above) |
| LYP6 | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| MELG | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| MING | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-03-17 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| MORG | equity_certificate | NOK | ESEF-NO | 6/6 | 2021,2022,2023,2024 | 2022-03-17 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| MSFT | stock | USD | SEC | 0/7 | 2020,2021,2022,2023,2024,2025,2026 | 2020-07-30 | 2022-10-17 | - |
| NEX | stock | EUR | ESEF-facts | 5/3 | 2022,2023,2024 | 2023-03-21 | 2023-03-27 | 2 filing(s) rejected by the ESEF parser: archive_too_large; no FY2020/2021/2025 (not filed/published in the registry, or rejected above) |
| NISB.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| NONG | equity_certificate | NOK | ESEF-NO | 4/3 | 2022,2023,2024 | 2023-05-09 | 2023-05-15 | 2021: ValueError: ESEF package rejected: ESEF package exceeds the uncompressed size li; no FY2020/2021/2025 (not filed/published in the registry, or ... |
| PRY | stock | EUR | ESEF-facts | 4/4 | 2022,2024 | 2023-05-30 | 2023-06-05 | no FY2020/2021/2023/2025 (not filed/published in the registry, or rejected above) |
| RING | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-04-05 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| ROGS.OL | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-03-29 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| ROMER.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| RR | stock | GBP | ESEF-facts | 6/6 | 2021,2022,2023,2024,2025 | 2022-04-28 | 2022-10-17 | no FY2020 (not filed/published in the registry, or rejected above) |
| SAAB_B | stock | SEK | ESEF-facts | 4/4 | 2021,2022,2023,2024 | 2022-03-22 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| SB1NO.OL | stock | NOK | ESEF-facts | 4/4 | 2021,2022,2023,2024 | 2022-04-14 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| SB68.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| SBNOR | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-04-19 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| SEC0 | stock | EUR | ESEF-facts | 2/2 | 2021,2025 | 2023-05-30 | 2023-06-05 | no FY2020/2022/2023/2024 (not filed/published in the registry, or rejected above) |
| SEC0.DE | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| SGO | stock | EUR | ESEF-facts | 4/1 | 2021 | 2022-03-23 | 2022-10-17 | 3 filing(s) rejected by the ESEF parser: archive_too_large; no FY2020/2022/2023/2024/2025 (not filed/published in the registry, or rejected above) |
| SKUE | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| SNOR.OL | equity_certificate | NOK | ESEF-NO | 2/2 | 2021,2022 | 2022-03-29 | 2022-10-17 | no FY2020/2023/2024/2025 (not filed/published in the registry, or rejected above) |
| SOAG | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-03-17 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| SOGN | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| SPOG | equity_certificate | NOK | ESEF-NO | 4/4 | 2021,2022,2023,2024 | 2022-03-17 | 2022-10-17 | no FY2020/2025 (not filed/published in the registry, or rejected above) |
| SPOL | equity_certificate | NOK | ESEF-NO | 3/3 | 2022,2023,2024 | 2023-05-09 | 2023-05-15 | no FY2020/2021/2025 (not filed/published in the registry, or rejected above) |
| SPYK | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| SU | stock | EUR | ESEF-facts | 6/6 | 2020,2021,2022,2023,2024,2025 | 2021-05-18 | 2022-10-17 | - |
| SXRJ_EMU_SMALL | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| SXRV_NASDAQ100 | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| TINDE.OL | equity_certificate | NOK | ESEF-NO | 0/0 | - | - | - | no_filing_found |
| TKA | stock | EUR | ESEF-facts | 0/0 | - | - | - | no_filing_in_filings_xbrl_org_registry |
| TKMS | stock | EUR | ESEF-facts | 0/0 | - | - | - | no_filing_in_filings_xbrl_org_registry |
| TRSB.OL | equity_certificate | NOK | ESEF-NO | 1/1 | 2024 | 2025-05-08 | 2025-05-12 | no FY2020/2021/2022/2023/2025 (not filed/published in the registry, or rejected above) |
| UCG | stock | EUR | ESEF-facts | 10/4 | 2021,2023 | 2023-05-30 | 2023-06-05 | 6 filing(s) rejected by the ESEF parser: archive_too_large; no FY2020/2022/2024/2025 (not filed/published in the registry, or rejected above) |
| VFEM.AS | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| VIE | stock | EUR | ESEF-facts | 5/2 | 2020,2021 | 2022-03-23 | 2022-10-17 | 3 filing(s) rejected by the ESEF parser: archive_too_large; no FY2022/2023/2024/2025 (not filed/published in the registry, or rejected above) |
| VUSA.AS | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| VVL.OL | equity_certificate | NOK | ESEF-NO | 3/3 | 2022,2023,2024 | 2023-05-09 | 2023-05-15 | no FY2020/2021/2025 (not filed/published in the registry, or rejected above) |
| VWCE | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| XAIX | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |
| XDWU | etf | EUR | snapshot-only | 0/0 | - | - | - | no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot |

Counts: equity certificates 14/28 with history (14 have an empty registry entry); stocks 2 SEC + 15 ESEF-facts of 26 non-US (5 with an empty registry entry, 4 with an unverified ISIN, 2 with every filing rejected by the parser); ETFs 0/19 (snapshot-only).

## 5. Findings the replay owner needs

* **F1 - resolved in part by HDP2** (section 0.2): stock_quality is scored for most ESEF stocks; stock_value stays unavailable (no PIT share count; peer cohort of 3).
* **F2 - certificate scores need one rescore per decision date.** The score engine reads a *stored* native score (`latest_sparebank_scores`). HDP2 exposes `scripts.sparebank_refresh.rescore_sparebanks_at(root, decision_day)` (section 0.3). PIT composites from the imported history, for example MING 6.03 at 2022-10-17, 8.09 at 2024-06-28, 8.56 at 2026-10-05 (coverage 0.396, partial); a certificate without a filing known at the date is `unavailable`.
* **F3 - mixed timestamp shapes** (`...T00:00:00+00:00` next to `...T11:02:16.151649+00:00`) cannot be parsed in one vectorised `pd.to_datetime`; rows silently became NaT (24 748 of 31 552 here). Both import paths now write fixed-width microsecond stamps and the PIT audit flags a mixed column.
* **F4 - classification evidence lives in `data/storage/cockpit.sqlite3`**, not in files. Without the bank rows the scorecard returns `financial_classification_unavailable`. Use `scripts/pit_history_merge_classification.py` (insert-only, idempotent).
* **F5 - `research_promotion_allowed` does not depend on fundamentals**: the blocker gates are identity, data_quality, evidence (a price source suffices), model_validity (never `not_evaluated`) and risk; valuation is an `authority_warning`. ETFs are therefore unaffected by missing holdings.
* **F6 - decision-time convention**: `live_decision_time` returns *now* when the data are within the live grace of today; a replay date must be older than that or it sees fetch-dated rows. All checks here use the end of the UTC decision day.

## 6. PIT check (committed: `scripts/pit_history_check.py`)

`python scripts/pit_history_check.py --root C:/dev/etf-PITF --coverage-csv data/pit_history/coverage.csv --universe-csv <audit.csv> --json data/pit_history/pit_check.json`

For every weekly decision date 2022-10-17 .. 2026-10-05 (208 dates; the 2026-10-09 end falls inside the last week) it asks the canonical selectors what is visible and fails on any fact with `known_at` after the decision time. It also checks that `known_at` parses, is not before the period it describes, equals a registry `date_added` of an own filing (never an import time), that `available_at == known_at`, and that no fetch-dated source (yfinance) is in the history store.
Result: **PASS** - stock_fundamentals 271 rows (sources ['esef', 'sec_edgar']), statement_facts 41003 rows (first known 2021-05-18, last 2026-10-20), 14 bank history directories, 0 violations. Facts known after 2026-10-09 (for example IDR FY2025 added 2026-10-20) are present and invisible to every decision date.
Same-day rule: a filing is visible from the end of its filing day, as in the live code; a one-day lag would be stricter.

## 7. Snapshot-only policy proposal (not implemented)

| input | proposal for the replay |
|---|---|
| ETF holdings (weights, top-10, count) | time-varying: pillar unavailable before the first snapshot (2026-10-11); already enforced by `_etf_exposure_component`; headline weight is 0, so scores are unchanged |
| ETF AUM | time-varying: unavailable before the snapshot; unused by the headline |
| ETF TER, replication/structure, domicile, accumulation, UCITS | static attributes: allow with the documented assumption "constant over the window", flagged in the row; they only feed `etf_product_quality` (headline weight 0), so no score effect; a TER change is the only risk |
| ETF premium/discount, tracking difference | time-varying: unavailable (no history) |
| analyst revisions (yfinance) | unavailable before the first snapshot; the stock headline renormalises over the remaining pillars (`analyst_revision` 0.0674) |
| stock profile (sector, industry, country), provider market cap | sector/region from `configs/universe.yaml` (static, allowed); provider market cap unavailable (recompute from price x PIT shares where shares are filed) |
| backtest trust label, full-sample backtest | do not surface in a replay (look-ahead); the label stays `unverified` |
| forecasts | section 8 |
| macro / news | empty; no component depends on them |
| yfinance statements | never as history (restated, fetch-dated) |

## 8. Forecast models

The score carries TimesFM 2.5 (`models/timesfm/timesfm-2.5-200m-transformers`) and Toto 2.0 (1B) as optional `model_confirmation` components (headline weight 0.0, action composite 0.14 / 0.21); TimesFM 3.0 is not wired. The 2022-2025 windows predate or overlap pretraining (TimesFM 3.0 declared cutoff 2023-11-30 for some corpora; 2.5 and Toto 2.0 unpublished, treated as unknown) and only one forecast run (2026-10-09) exists. **Proposal: deterministic baseline only (`momentum_shrunk_v1`) in the replay; optional models off, and any weight left unavailable, never moved to momentum/trend.** Nothing was wired.

## 9. Decisions (closed by Opus after HDP2) and open items

1. Closed: NCI `observed` exception accepted (parent-only concept, section 0.1). Closed: the 100 MB iXBRL cap stays; the 17 oversized filings are a documented gap (section 0.4). Closed: `stock_value` is unavailable in the replay (section 0.2).
2. Open: KMAR (Kempower) ISIN cannot be verified (GLEIF lists no ISIN for LEI 743700EIG9TDB5QNZS09); HO (Hochtief) is verified but has no registry filing.
3. Open: DB1, TKA, TKMS (Germany), 14 small certificates (empty registry), AM.PA and KMAR.OL have no filings.xbrl.org source; an Oslo/OAM adapter would be separate work.
4. The replay's decision-time convention (F6) and the last replay date 2026-10-05 (section 0.6).

## 10. Files to swap into the sandbox (do not overwrite fx.parquet)

Copy from `C:/dev/etf-PITF` to the replay root (same relative paths):
1. `data/clean/stock_fundamentals.parquet`, `data/clean/stock_snapshots.parquet`
2. `data/clean/statement_facts.parquet`, `data/clean/filings_statements.parquet` (replaces the empty one; delete or regenerate the stale `filings_statements.csv` mirror)
3. `evidence/norway/*-history/` (14 directories: AURG, HELG, MING, MORG, NONG, RING, ROGS.OL, SBNOR, SNOR.OL, SOAG, SPOG, SPOL, TRSB.OL, VVL.OL) and `evidence/norway/sparebank_history_summary.json` (the history run no longer touches the live `sparebank_refresh_summary.json`)
4. classification rows: `python scripts/pit_history_merge_classification.py --source-root C:/dev/etf-PITF --target-root <replay root>` (do not copy the sqlite file)
5. code (this branch): `scripts/sparebank_refresh.py`, `scripts/import_official_filing.py`, `scripts/refresh_stock_fundamentals.py`, `src/etf_cockpit/application/stock_service.py`, `src/etf_cockpit/application/filing_ingestion_workflows.py`, `src/etf_cockpit/application/financial_institution_views.py`, plus the new scripts; the reader fix is required for any PIT bank score before the newest filing.
6. HDP2 (new): `data/pit_history/universe_isin_overrides.json` (sandbox-only verified ISINs; do not copy into the owner's store), `data/pit_history/isin_verification.json`; `data/clean/stock_fundamentals.parquet` now also holds the `esef` rows (swap item 1 covers it); the code list in item 5 gains `configs/stock_fundamentals_v1.yaml`, `src/etf_cockpit/data/stock_sources.py`, `src/etf_cockpit/data/stock_fundamentals.py`, `src/etf_cockpit/analysis/stock_universe.py`, `src/etf_cockpit/parsers/esef_ixbrl.py`, `scripts/pit_history_backfill.py`, `scripts/pit_history_check.py`, `scripts/pit_verify_isins.py`.
7. Optional provenance: `data/pit_history/` (`esef_manifest.json`, `esef_generic_import_log.jsonl`, `coverage.csv`, `pit_check.json`); raw packages are in `data/raw/esef/immutable` and `data/raw/filings/eu_esef` (3.7 GB, not needed to score).

## 11. Defaults chosen

HDP2: ESEF annual periods only; share count needs agreement within 1 percent across filings; payments stored as positive outflows; D&A, interest expense and the debt legs map only from the exact IFRS concepts (no FinanceCosts, no EPS-derived shares); a lone debt or lease leg is `partial`/unavailable; GLEIF ISIN checks need reverse and forward agreement plus a name match; non-XBRL members are skipped before the size check, the iXBRL caps are unchanged. HDP1: SEC chain restricted to `sec_edgar`; decision time = end of the UTC day; known_at = registry `date_added` (later batch dates kept); weekly Monday grid 2022-10-17..2026-10-05; 1 s pause between requests, abandon after 5 consecutive errors; an ISIN must be verified for a LEI; one evidence directory per bank (`<id>-history`); failed filings are recorded and not retried.

## 12. Tests

HDP1: `tests/test_pit_history_backfill.py` (7 tests). HDP2: `tests/test_pit_history_esef_adapter.py` (9 tests: ESEF rows as originally reported, conflicting share counts, explicit parent income under NCI, refresh without network, rescore hook, GLEIF verification, ISIN overrides, grace window) and 2 parser tests in `tests/test_esef_ixbrl_parser.py`. Run from the repo root: the 39-file set plus `tests/test_paper_bots_execution.py`, the new adapter file, `test_bugfix_t-pit.py`, `test_fund_p0_semantics.py`, `test_fund_p1_consistency.py` and `test_fundamentals.py` (45 files): 649 passed, 0 failed (exit 0; also tests/test_stock_store.py, test_stock_sources.py, test_sparebank_sb2.py).
