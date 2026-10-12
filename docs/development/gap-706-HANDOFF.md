# Issue #706 safe-point handoff

## Completed at the synthetic-fixture safe point

- Fund-scope fee observations no longer populate instrument/share-class fields without an explicit class match. Exact class observations retain their scope, class ID, currency, benchmark, and source dates.
- Tracking is blocked when the exact class record disagrees with fund-scope currency, benchmark, or benchmark currency. The panel reports those identities separately and marks the absent listing mapping unavailable.
- The existing Instrument Detail summary now shows fee and OCF origin, tracking sources and calculation methods, benchmark/currency, period, frequency, sample count, coverage, effective/known dates, and freshness state. It also shows fund-scope AUM/flows and the bounded closure proxy with factor coverage and missing factors.

## Conservative defaults

- A class-to-fund mapping is usable only when the class ID is exact and its currency, benchmark ID, and benchmark currency all match known fund-scope values.
- Fee and tracking freshness remain `not_assessed` where no freshness limit exists. AUM keeps the existing closure-policy age limit; no threshold was added.
- Tracking error retains the existing sample standard deviation of matched active daily returns, annualised by `sqrt(252)`.

## Validation

- `python -m pytest tests/test_gap_706.py -q --tb=line -p no:cacheprovider` — 6 passed.
- `python -m pytest tests/test_gap_706.py tests/test_decision_etf.py tests/test_etf_completion.py tests/test_etf_economics_production.py tests/test_etf_live_fetch.py tests/test_gap_243.py tests/test_architecture_boundaries.py -q --tb=line -p no:cacheprovider -o 'addopts='` — 69 passed, 7 warnings.
- `tests/test_etf_economics.py` could not collect: its temporary `data/storage` path disappeared under `logs/pytest_system_tmp`, followed by Windows `PermissionError` while removing the parent. The same failure reproduced on one retry; no tests from that module ran.

## Remaining release evidence

The fixture path remains synthetic. Official persisted disclosure/market input, distinct listing identity mapping, real-instrument panel acceptance, and package/release gates are still required before release acceptance. No issue lifecycle, owner setting, score weight, execution control, or persistent schema changed.
