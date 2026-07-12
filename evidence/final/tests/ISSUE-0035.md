# ISSUE-0035 tests gate

- RED before the Task 10 implementation: Data Health focused run reported 5
  genuine missing-behaviour failures.
- Migration review-fix RED: the three new migration timestamp/name/provenance
  tests failed before implementation.
- Status-precedence RED: `python -m pytest tests/test_data_health.py::test_failed_completion_event_is_failure_not_success -q` exited 1 because the failed completion was recorded as `last_success`.
- Status-precedence GREEN: the same focused regression exited 0 after failure status was given precedence.
- `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py`: **16 passed**.
- Affected UI/start-up/navigation bundle over six test files: **40 passed**, one
  existing GluonTS warning.
- `...python.exe -m compileall -q src tests`: exit 0.
- Scoped Ruff over `health.py`, `data_health.py` and `test_data_health.py`:
  `All checks passed!`.
- Full authoritative `...python.exe -m pytest -q`: exit 0 at 100%, warnings only;
  no Data Health failure occurred after the atomic staging fix.

The focused tests cover healthy, stale, missing, corrupt, schema-mismatch and
unavailable stores; persisted provenance; mixed-offset migration ordering;
wrong migration names; missing `applied_at`; macro invalid siblings; filters;
UI links; and compatible CSV export columns.

Package-smoke, semantic accessibility and final integration/synchronisation
gates remain pending; this record does not claim those gates.
