# Wave 5 Task 19 fix 8 - price and risk evidence fail-closed

## Findings fixed

- Price panels now require a validated date column and drop unparseable observations before selecting the latest row. Missing or malformed dated evidence is unavailable rather than fresh.
- Risk panels now require a valid as-of date and at least one usable risk dimension; empty or malformed feature rows are unavailable/manual-review.
- `execution_allowed` remains false.

## RED evidence

`python -m pytest tests/test_task19_instrument_detail.py::test_price_panel_rejects_missing_or_malformed_latest_dates tests/test_task19_instrument_detail.py::test_price_panel_drops_malformed_rows_before_selecting_latest tests/test_task19_instrument_detail.py::test_risk_panel_rejects_empty_or_malformed_feature_rows -q --tb=short`

Result before implementation: 3 failures. Missing/invalid dates were reported available or selected as latest, and an all-invalid risk row was reported available.

## GREEN and regression evidence

- The same focused command: 3 passed.
- Task 19, affected Instrument Detail/Task 18/UI, button, E2E and startup bundle: passed.
- Scoped Ruff: passed.
- `python -m compileall -q src tests/test_task19_instrument_detail.py`: passed.
- `git diff --check`: passed.

Full release/package/browser, keyboard/responsive, audit-export and clean-first-run gates remain closure-pending.
