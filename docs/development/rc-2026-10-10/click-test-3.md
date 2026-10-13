# Click test 3 - ETF AI Evidence Cockpit (http://127.0.0.1:8597/)

Method and limits (read first):
- Built-in browser pane only (mcp__Claude_Browser__*), viewport emulated at 1100x800 (reset to desktop at the end). Read-only: no data edited, no server restart. One "Run forecasts" click (required by the brief) wrote forecast rows into the data copy (57 -> 172 rows).
- Flet canvas app: element text was read through the accessibility/innerText layer and screenshots. Timings are click to settled content, measured in the page, so they include screenshot-free load only.
- Pointer quirks: the first click at a new position, and the first click on a View/title menu, is often swallowed; a second click works. Not counted as a product defect, but a real user may notice it.
- Tickers: search is by instrument id (BA, RABO), not by Yahoo ticker (BA.L, RABO.AS).
- NOT verified (time): Programme Map reachability via search; MSFT in the Stock Research chip (chip lists only recently visited instruments); Portfolio Sandbox View segments and range chips; Settings General toggles and "Preview changes"; Sectors View menu (P/E P/B ROE, 1M-5Y, Sector/Country/Company); Universe enable switches (deliberately not toggled); Import "Choose and preview" (not clicked). Last attempt to search MSFT typed into the What Changed page filter, not global search.
- Cold-load of Home: first load about 27 s to content; reload after a crash about 65 s; last reload about 85-90 s of plain white screen with no loader.

| # | page | element | action | expected | actual | verdict | evidence |
|---|---|---|---|---|---|---|---|
| 1 | Home | cold load | reload / | content in a few s | white screen 27 s (first), 65 s and 85-90 s (reloads) with no loader | SLOW | timings in method note |
| 2 | Home | scores list | read | numeric scores | NONG 8.6, RING 8.3, MING 8.3, XAIX 8.0, KMAR 7.8, SEC0 7.8, VWCE 7.8, DB1 7.7, MSFT 7.6 | OK | list rows |
| 3 | Home | Biggest score and rank changes | read | no "0 places" claim | card says "No rank changes"; fixed here. Still in What Changed: "SPOG rose most (0); SPOG fell most (0)" | OK | Home card (What Changed see #46) |
| 4 | Home | Evidence state card vs footer | read | consistent data quality | card Data quality 0% vs footer "Review (3 blocked)" vs Data Health "6 of 14 healthy" | WRONG-OUTPUT | card and footer |
| 5 | Home | tier chips Primary / Secondary / Sparebanken | click | filter | work in 1-3 s; Primary 43, Secondary only RABO ("No scores"), Sparebanken 14 numeric rows (NONG 8.6 ...) | OK | chip views |
| 6 | Home | View menu highlight | open after Sparebanken | highlight follows | highlight stays on "All" | VISUAL | menu |
| 7 | Home | sort Rank / Change | click | sorts | works, about 3 s | OK | list |
| 8 | Home | What changed button | click | opens page | What Changed opens in 6.1 s | SLOW | timing |
| 9 | Home | alert history | read | friendly text | raw "RuntimeError: yfinance is not installed. Run `pip install yfinance`" | WRONG-OUTPUT | alert tail |
| 10 | Home | row click | click NONG row | detail | opens Stock Research NONG, ring 8.6 = list | OK | ring |
| 11 | Home | via dock | click | content | 8-10.5 s | SLOW | timing |
| 12 | All pages | footer Data quality + Forecast | read on Home, Research, Detail, Help, Settings | consistent | "Data quality Review (3 blocked)" everywhere, no Forecast item; fixed vs test 2 | OK | footer |
| 13 | Search | VWCE, NONG, BA, RABO | type, Enter/suggestion | opens detail | VWCE about 11 s, NONG about 12.8 s, BA 8.6 s, RABO 5.1 s | SLOW | timings |
| 14 | Search | BA.L, RABO.AS | type | opens BA / RABO | "No matching page, instrument or term"; only ids BA / RABO work | WRONG-OUTPUT | search result |
| 15 | Search | Enter on page names | type, Enter | opens page | no match; suggestion click needed | WRONG-OUTPUT | search |
| 16 | Instrument Detail VWCE | score ring | read | = list 7.8 | ring 7.8 = list; but Evidence confidence 0.0 beside it | WRONG-OUTPUT | ring and card |
| 17 | Instrument Detail VWCE | Price basis | read | consistent | "adjusted" but page says "Showing raw close" | WRONG-OUTPUT | card |
| 18 | Instrument Detail VWCE | Fund view | read | TER, AUM, distribution, holdings, splits | TER 0.14%, AUM 85.3bn, Accumulating, 10-row holdings table, country split (US 59.77, Japan 5.97 ...); fixed | OK | Fund view 1.3 s |
| 19 | Instrument Detail VWCE Fund | details | read | clean text | tracking difference reason is raw field names; AUM "(currency unavailable)"; raw URLs and ISO timestamps; holdings rows country/sector "Other/unclassified" | WRONG-OUTPUT | Fund view |
| 20 | Instrument Detail VWCE Fund | sector split | read | named sectors | Energy 4.2% + Other 95.8%; chart x labels "1","2" | WRONG-OUTPUT | sector chart |
| 21 | Instrument Detail VWCE | Risk & forecasts | read | reasons users understand | reasons shown, but jargon ("Factor-risk binding unavailable: complete unambiguous snapshot frames are required") and placeholders "Evidence details are available in the local result." | WRONG-OUTPUT | 1.2 s |
| 22 | Instrument Detail VWCE | History | click | readable history | 3.7 s; raw "rows 102: run_id=score_2026..., na_reason=Run Refresh yfinance data..." dump | WRONG-OUTPUT | History |
| 23 | Instrument Detail | segment switches | click each | fast | 1.2-3.7 s (was 8-75 s) | OK | timing |
| 24 | Instrument Detail NONG | ring | read | = list 8.6 | ring 8.6 = list; "Sparebank scorecard 8.6/10 from 77% of axis evidence" | OK | ring |
| 25 | Instrument Detail NONG | Market clock | read | plain text | "identity projection is unavailable or conflicted" | WRONG-OUTPUT | card |
| 26 | Instrument Detail NONG Fundamentals | Sparebank workspace | read | axes, peers, Pillar 3 queue | axes table (9 rows), peers and Pillar 3 queue present but empty: "No peers scored yet" and "Nothing proposed" both point at scripts/ (sparebank_refresh.py, extract_pillar3.py) | WRONG-OUTPUT | workspace |
| 27 | Instrument Detail NONG Fundamentals | axes header | read | matches table | "Axes without evidence: owner claim integrity, credit concentration, capital liquidity resilience..." but those axes show ratings 5.0 / 9.7 / 7.3; 3 unrated axes not explained | WRONG-OUTPUT | header vs table |
| 28 | Instrument Detail NONG | early crash | switch to Fundamentals | page | one full-screen red "Frozen controls cannot be updated"; reload recovered, not reproduced | BROKEN | seen once |
| 29 | Instrument Detail BA | stock value | read | sane valuation | Market cap 538.50m GBP (~100x too low), P/E 0.3x, P/B 0.0x, FCF yield 432.5%, earnings yield 382.9%; Stock value 10.0/10 inflates score; same on RR.L, CRN.L (CBUK ranks 15th at 7.3); Size says "EUR 64.3bn" | WRONG-OUTPUT | pence/pound unit error |
| 30 | Instrument Detail BA | ring | read | = list | 5.6 = Stock Research 5.6, but "7 of 11 components" vs Home "9 valid components" | WRONG-OUTPUT | card |
| 31 | Instrument Detail RABO | score | read | number or friendly reason | ring "-"; "financial-institution projection failed (financial_decision_time_unavailable)" and "No complete local price series" | WRONG-OUTPUT | jargon reason |
| 32 | Scores | page | open | numeric rows, panel | 2.0 s; "57 of 58 scored"; Sparebanken rows numeric (NONG 8.6) but Quality/Risk/Components/Warnings all "n/a"; side panel ring 8.6; row click updates panel 2.6 s | OK | page |
| 33 | Scores | RABO.AS | read | not labelled Sparebank | RABO in Secondary tier, not Sparebank | OK | tier |
| 34 | Scores | header | read | readable | header labels overlap; only about 2 table rows visible at 1100x800 | VISUAL | header |
| 35 | Scores | side panel | read | matches workspace | same wrong "Axes without evidence" text as #27 | WRONG-OUTPUT | panel |
| 36 | Scores | cross-page values | compare | same numbers | Quality: XAIX 5.2 (Home/Scores) vs 5.9 (Screener); VWCE 4.9 vs 5.7; MSFT 5.8 (Home/Screener) vs 5.1 (Scores). Quality constant 5.8 across stocks. Evidence confidence 1.7 for MSFT, 0.0 VWCE beside high scores | WRONG-OUTPUT | three pages |
| 37 | Stock Research | open via dock | click | content | 3.8 s | OK | timing |
| 38 | Stock Research | instrument chip | click | switches | chip lists recent instruments (NONG, RABO, BA, VWCE); BA click switches (ring 5.6); fixed. MSFT not in list until visited | OK | chip |
| 39 | Stock Research NONG / MING | verdict | read | consistent with 8.6 | "Pending", "Fails 5 of 9 gates", "Source-linked score evidence is unavailable" despite 8.6 and 8.3 | WRONG-OUTPUT | verdict card |
| 40 | Stock Research | radar | read | readable labels | Value/Size/Momentum/Quality/Low vol/Yield readable; fixed | OK | radar |
| 41 | Stock Research | fundamentals tables | read | full labels | truncated ("Return ...", "Net inc...") | VISUAL | tables |
| 42 | Stock Research BA | return attribution | read | dividends | Dividends +0.0 while dividend yield is 2.0% | WRONG-OUTPUT | chart |
| 43 | Stock Research | gate text | read | clear | "Signal - Not met: No score warnings" confusing | WRONG-OUTPUT | gates |
| 44 | Sectors & Countries | open | click | look-through or empty state | 5.1 s; 75.9% Unknown/Unmapped, Norway 24%, no ETF look-through though VWCE split exists | WRONG-OUTPUT | page |
| 45 | Sectors & Countries | views Globe/Map/Bars, Treemap/Sunburst/Bars, benchmark chips | click | toggle | all work (render lag about 3 s); sunburst labels overlap, one bar row has no label, duplicate buckets "financials" 25.9% and "Financials" 1.7%; benchmark panel clear empty state | VISUAL | charts |
| 46 | What Changed | list | read | real changes | SPOG with delta 0 under "Changed only"; opens in 4.2-6.1 s | WRONG-OUTPUT | list |
| 47 | Macro and Factors | open + Regime / Rates / Scenarios, 3M / 5Y | click | content | loads 1.6 s (was never); all Unavailable with reason "no local macro/factor snapshots have been ingested"; Regime shows "Unavailable" with an "Available" chip | WRONG-OUTPUT | chip |
| 48 | Forecast Lab | open, toggles | click | works | 4.1 s | OK | page |
| 49 | Forecast Lab | Run forecasts | click | friendly message | progress banner, about 25 s, toast "Configured ETF forecasts refreshed as of 2026-10-08: baseline ok 57, timesfm unavailable 5.." (clipped); friendly, fixed | OK | toast |
| 50 | Forecast Lab | status after run | read | updated | "Forecast run status: not run in this session" stays stale; table shows TimesFM 57 / Toto 58 "Shadow" while governance says "Unavailable" and Settings says Enabled/Live/Configured | WRONG-OUTPUT | contradiction |
| 51 | Forecast Lab | Open governance | click | jumps | scrolls to Governance in 1.1 s (second click needed); fixed | OK | page |
| 52 | Data & Models | page, cards | click | card jumps | 1.9 s; "reasons: Available - Model status is unavailable"; card/chip clicks do not navigate, only details toggle | BROKEN | card click |
| 53 | Settings | General / Data & models / Privacy / About | click | content | 1.1-1.9 s each; Privacy grey box gone | OK | tabs |
| 54 | Settings | chips | read | full text | "Medium-Aggress...", "Enab..." clipped | VISUAL | chips |
| 55 | Settings | Terms acknowledgement | read | ok | "Hardening Required" | WRONG-OUTPUT | General |
| 56 | Help and Glossary | open + menu | click | page, 58 terms | 1.9 s OK; menu lacks Programme Map listed in the dock tooltip (9 items) | WRONG-OUTPUT | menu |
| 57 | Errors & Recovery | list | read | friendly text | header says "Technical detail is hidden outside developer mode" yet raw "RuntimeError: yfinance is not installed" for about 20 instruments and "Yahoo Finance returned no usable price rows" chip "unknown" | WRONG-OUTPUT | list |
| 58 | Diagnostics | page | open | content | "Preparing local evidence" 2 s, content 4 s; forecast_models slowest 26.6 s, 27 steps over budget; model runtime Unavailable | OK | page |
| 59 | Release Readiness | page | open | clear status | "Certification: Blocked", Canonical Issue Registry failed, Quality programme Not Run, Legal terms Hardening Required; title truncated "Release Readine..." | VISUAL | page |
| 60 | System Map / Audit Notes | page | open | titles | 1-2 s; truncated "Resea..." and column headers | VISUAL | tables |
| 61 | Universe | page | open | content | 2.3 s (59 candidates, 58 enabled); switches not toggled | OK | page |
| 62 | Data Health / Provider Status / Data Catalogue / Filings / ETF Disclosures / News | pages | open | content | 1.4-2.4 s each; Provider chips overlap; Catalogue "No datasets registered locally"; ETF Disclosures prefills "ETF instrument ID" with BA (a stock) | VISUAL | chips, prefill |
| 63 | Portfolio Sandbox / Risk Evidence / Optimiser Lab / Stress / Journal / Diary / Operations | pages | open | content | 2.0-3.2 s; Optimiser says "No held-out method results" above a populated table; raw "portfolio_snapshot_not_sealed_or_reconciled"; input fields dark on dark | VISUAL | inputs |
| 64 | Backtests / Training / Feature Catalogue / Evidence Ledger | pages | open | content | 1.9-6 s; reasons clear; Feature Catalogue text (sma_200 lowest) contradicts chart; Ledger axis labels truncated | WRONG-OUTPUT | chart |
| 65 | Strategy Builder / Screener / Comparison | pages | open | content | about 4 s; all templates Matches 0 and "Description unavailable"; Comparison NONG vs RING shows NOK prices labelled EUR | WRONG-OUTPUT | tables |
| 66 | Dock | tooltips | hover/click | disappears | tooltip sticks over content on Lab, Map, Research | VISUAL | tooltip |
| 67 | First-run Setup | open | click | content | 5.2 s | SLOW | timing |
| 68 | Run forecasts | side effect | read | n/a | wrote 115 forecast rows to the data copy; Home manual-review count 28 to 27 | OK | note |

## Click-test-2 re-verification
Fixed: "0 places" on Home; footer Data quality/Forecast consistent; Sparebanken numeric; Stock Research chip; Fund view (TER, AUM, holdings, country split); Macro loads; Run forecasts friendly toast; governance jump; Settings Privacy grey box; radar label; Scores and segment speed.
Not fixed: sector split and sectors page empty-ish; Home cold load (worse); Sparebank detail text/axes; contradicting forecast statuses; stuck dock tooltip; clipped tiles; raw errors.

## Summary counts
OK 25, SLOW 5, WRONG-OUTPUT 29, BROKEN 2, VISUAL 7 (68 rows, some rows cover several elements).

## Top defects by user impact
1. UK stocks (BA.L, RR.L, CRN.L) pence/pound x100 error: market cap, P/E 0.3x, FCF yield 432%, Stock value 10/10 inflate scores and ranks.
2. Home cold load is 27-90 s of blank white screen with no loader.
3. Score inconsistencies across pages (Quality XAIX 5.2/5.9, VWCE 4.9/5.7, MSFT 5.8/5.1; 9 vs 7 components; confidence 0.0 beside high scores).
4. Raw errors shown to users (yfinance RuntimeError for about 20 instruments in Errors & Recovery and Home alerts) despite "technical detail hidden".
5. Search fails on tickers BA.L and RABO.AS; Enter does not open pages; slow to open detail (5-13 s).
6. Sparebank workspace wrong/empty: "Axes without evidence" lists rated axes; peers and Pillar 3 queue empty pointing at scripts; Stock Research shows "Pending / fails 5 of 9" for 8.6 scores.
7. RABO score unavailable with jargon reason and no price series.
8. Forecast status contradictions (Lab stale "not run", TimesFM 57 rows vs Unavailable vs Settings Live).
9. Sectors & Countries 75.9% Unknown with no ETF look-through; sector split Energy 4.2 + Other 95.8.
10. Visual/clip issues: Scores header overlap, clipped chips, invisible input fields, stuck dock tooltip, Data & Models cards not clickable.
