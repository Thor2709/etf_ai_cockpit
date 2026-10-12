# Issue #243 safe-point handoff

The economics engine already calculates canonical tracking error and preserves its point-in-time evidence. The production panel now projects it into `e1.tracking_error` with status, reason, source, dates, window, unit, and evidence label. Missing evidence and samples with fewer than two active daily returns produce an unavailable field with no value.

The safe point remains synthetic fixtures. Full fee and closure-quality breadth, real-instrument acceptance, and owner-defined parent criteria remain open. No economics thresholds, score weights, owner settings, or execution controls changed.

Defaults: no calculation parameters changed. Tracking error keeps the existing sample-standard-deviation and business-day annualisation calculation; fewer than two active returns remain unavailable.

Validation:

- `python -m pytest tests/test_gap_243.py -q --tb=line -p no:cacheprovider` — 3 passed.
- `python -m pytest tests/test_etf_economics_production.py -q --tb=line -p no:cacheprovider` — 13 passed.
- `python -m pytest tests/test_architecture_boundaries.py -q --tb=line -p no:cacheprovider` — 3 passed.
- `python -m pytest tests/test_etf_economics.py -q --tb=line -p no:cacheprovider` — blocked during collection by `PermissionError` under `logs/pytest_system_tmp`; 0 tests ran. The combined requested invocation hit the same collection error.

Fixture acceptance does not establish real-data acceptance.
