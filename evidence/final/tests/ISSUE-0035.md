# ISSUE-0035 tests gate

- RED before the Task 10 implementation: Data Health focused run reported 5
  genuine missing-behaviour failures.
- Migration review-fix RED: the three new migration timestamp/name/provenance
  tests failed before implementation.
- `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py`: **12 passed**.
- Affected UI/start-up/navigation bundle over six test files: **39 passed**, one
  existing GluonTS warning.
- `...python.exe -m compileall -q src tests`: exit 0.
- Scoped Ruff over `health.py`, `data_health.py` and `test_data_health.py`:
  `All checks passed!`.
- Full authoritative `...python.exe -m pytest -q --maxfail=8`: exit 1 with 8
  pre-existing failures in Decision Journal path setup, generated candidate/
  secondary fixtures and trust-identity fixture cardinality; no Data Health
  failure occurred.

The focused tests cover healthy, stale, missing, corrupt, schema-mismatch and
unavailable stores; persisted provenance; mixed-offset migration ordering;
wrong migration names; missing `applied_at`; macro invalid siblings; filters;
UI links; and compatible CSV export columns.
