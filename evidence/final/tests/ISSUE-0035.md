# ISSUE-0035 tests gate

- `pytest tests/test_data_health.py -q -rA`: 3 passed after the responsive-row correction.
- Focused cross-feature run over Data Health, Simple Scores, Flet startup and workflow navigation: 39 passed.
- `pytest -q -rA`: 244 passed, exit code 0; the final output is in `evidence/wave4/full-pytest-responsive-final.txt`.
- `compileall -q scripts src tests`: exit code 0.
- Scoped Ruff over the changed health, page, dashboard and test files: exit code 0.

The tests cover healthy, stale, missing and corrupt stores, forecast/backtest/macro inventory, CSV export and Flet control-tree labels for the visible provenance and failure fields.
