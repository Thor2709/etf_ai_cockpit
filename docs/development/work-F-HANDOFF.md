DIAGNOSIS: Genuine Yahoo OHLC inconsistencies; validator unchanged. Baseline refresh exited 1, rejecting all rows.
93125 downloaded rows: 494 invalid across 35 instruments; no duplicate instrument/date pairs or NaN volumes.
Unadjusted OHLC (auto_adjust=False) are compared together; adjusted_close is separate. Minimum breach ~0.00009966, not float epsilon.
Examples: AASB.OL 2021-11-30 O/H/L=130.849670 C=129.915039; CTEC.AS 2023-05-16 O/H/L=3.4959 C=3.5071.
Example: AURG.OL 2024-03-20 O=228 H=232 L=228 C=218. Samples per affected instrument printed and saved in .owner-root/data/work-F-rejected-samples.csv.
FIX: src/etf_cockpit/data/price_quarantine.py:9 shares existing row quarantine and recomputes clean checksum; no values repaired.
src/etf_cockpit/application/data_service.py:61 retains its existing helper interface using the shared implementation.
scripts/run_yfinance_analysis.py:66 quarantines before validation/commit; :73 preserves unavailable status for fully quarantined instruments.
scripts/run_yfinance_analysis.py:92 persists excluded rows with invalid_ohlc reason; :123 carries history blocks into signal quality.
Partial provider failures still abort; all other validation blocks still abort. The 252-row signal threshold is unchanged.
FIX: scripts/run_yfinance_analysis.py:157 reports BacktestDataUnavailableError as unavailable; preserves the 260-session gate and emits no performance values.
TESTS: 5 new tests; focused + first 8 matching existing files + existing quarantine suite: 173 passed; final CLI correction: all 5 focused tests passed.
TESTS: ruff and staged git diff --check passed; existing tests unchanged.
REFRESH: Price stores verified: 92631 valid rows, max date 2026-10-09, JEDI.DE 1093 rows; 494 rows in data/quality/price_quarantine_2026-10-11.parquet.
REFRESH: Exact requested owner-root command completed with exit 0; report data/reports/yfinance_full_analysis_20261011T044322Z.json.
REMAINING: KMAR.OL (119), RABO.AS (1), SPACEX (83), TKMS (246) remain below 252 rows and blocked for signals; backtest unavailable (1 complete shared session; 260 required, 1292 missing observations), execution_allowed=false.
