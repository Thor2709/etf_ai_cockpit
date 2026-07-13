# Task 16 Fix 4 - Fundamentals Screener evidence surface

## RED

Added `tests/ui/test_screener_ui.py` first. The focused test failed against
the pre-fix route map because `/screener` was not registered (`2 failed`).

## GREEN

- Added a read-only `/screener` route titled **Fundamentals Screener**.
- The page reads canonical `FUNDAMENTAL_CLEAN_PATH` via
  `load_fundamental_evidence` and renders every canonical row with valuation,
  profitability, leverage, growth and shareholder return.
- Each row also exposes eligibility, source, as-of date, missing fields,
  warnings, limitations, sector-relative status and
  `executable_authority=false`.
- Missing metrics render as `N/A`; an empty or malformed clean store renders
  an explicit unavailable/no-data message. No score weights or action authority
  are changed.
- Registered the route in the UI acceptance inventory and feature registry.
- Added the missing `dashboard.open-news-context` acceptance contract exposed by
  the prior Task 16 news surface so the interaction inventory remains closed.

## Evidence

```text
pytest -q tests/ui/test_screener_ui.py tests/test_fundamentals.py tests/test_instrument_detail.py tests/test_news_ui.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_feature_registry.py tests/test_governance_review_regressions.py tests/test_flet_startup.py tests/test_e2e_workflow.py
all selected tests passed

ruff check src/etf_cockpit/app/pages/screener.py src/etf_cockpit/app/router.py tests/ui/test_screener_ui.py tests/test_button_contracts.py
All checks passed!

python -m compileall -q src tests
exit 0

git diff --check
exit 0 (line-ending warnings only)
```

The full repository/package/browser matrix was not run in this focused fix.
