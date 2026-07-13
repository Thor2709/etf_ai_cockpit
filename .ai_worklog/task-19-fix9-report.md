# Wave 5 Task 19 fix 9 - candidate date and risk date validation

## Findings fixed

- Candidate score-row prices now validate scalar latest dates before reporting a candidate price panel available; malformed candidate dates are manual-review/unavailable with unavailable freshness.
- Risk as-of dates now use scalar-only parsing; list, dict and array values fail closed without exceptions.
- `execution_allowed` remains false.

## RED evidence

The focused candidate-date and container-risk tests failed before implementation: malformed candidate dates were reported available, and container-valued risk dates were either accepted or raised a pandas `ValueError`.

## GREEN and regression evidence

- Candidate-date and container-risk focused tests: passed.
- Task 19, Instrument Detail/Task 18/UI, button, E2E and startup bundle: passed.
- Scoped Ruff, compileall and `git diff --check`: passed.

Full release/package/browser, keyboard/responsive, audit-export and clean-first-run gates remain closure-pending.
