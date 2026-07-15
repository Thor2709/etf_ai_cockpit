# UPDATEV2-0015 tests gate

Focused command (Python 3.12):

`C:\Users\thor2\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_risk_analytics.py tests/test_instrument_detail.py tests/test_task19_instrument_detail.py tests/test_trust_critical_artifacts.py tests/test_button_contracts.py -q --tb=short`

Result: 100% completion with no failure output. The two independently rerun subsets also passed: `tests/test_fund_documents.py tests/test_fund_holdings.py` (52 tests, exit 0) and the remaining Task 14 files (100% completion). The authoritative full suite was rerun under the same Python 3.12 environment and completed at 100% with exit 0; its retained output is `evidence/final/tests/UPDATEV2-0028-full-suite.txt`.

Coverage includes complete and missing document states, stale holdings, duplicate versions, invalid dates/checksums, export registration, CSV/parquet compatibility, audit evidence fallback and the UI contracts. The full suite completed at 100% with exit 0 under Python 3.12; two deprecation warnings in existing trade-proposal tests are non-blocking and unrelated.
