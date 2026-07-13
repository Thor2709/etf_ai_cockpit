# Task 16 Fix 6 - chronological audit export evidence

## Task completed

Fixed the Task 16 audit export ordering blocker. Canonical news and fundamentals
now pass through their existing temporal load/sort helpers before the export
selects the latest 20 rows. Schemas and legacy paths remain unchanged, and the
export continues to render `executable_authority=false`.

## Files and symbols examined

- `src/etf_cockpit/chatgpt_bridge/export_pack.py`: `export_review_pack`
- `src/etf_cockpit/data/news_context.py`: `load_news_items`, `sort_news_items`
- `src/etf_cockpit/data/fundamentals.py`: `load_fundamental_evidence`, `sort_fundamental_evidence`
- `tests/test_release_hardening.py`: audit export regressions

## Findings or changes

- The export previously read raw Parquet with `_safe_optional_frame` and then
  applied `tail(20)`, so unordered canonical stores could omit the newest
  evidence.
- Replaced those reads with `load_news_items(NEWS_CONTEXT_PATH)` and
  `load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)`. Both loaders retain
  their existing missing/corrupt-store behaviour and canonical temporal sort.
- Added an adversarial regression with 21 unordered rows in each canonical
  store; the newest rows must be present and the oldest news row must be
  excluded by the 20-row limit.

## Evidence

RED test before the production change:

```text
tests/test_release_hardening.py::test_audit_export_orders_unordered_canonical_news_and_fundamentals_before_tail
FAILED: newest canonical news row was absent from the export
```

GREEN test after the change:

```text
tests/test_release_hardening.py::test_audit_export_orders_unordered_canonical_news_and_fundamentals_before_tail
1 passed
```

## Commands or tests run

- `python -m pytest -q tests/test_release_hardening.py::test_audit_export_orders_unordered_canonical_news_and_fundamentals_before_tail` - passed.
- `python -m pytest -q tests/test_release_hardening.py tests/test_news_context.py tests/test_fundamentals.py` - passed.
- `python -m ruff check src/etf_cockpit/chatgpt_bridge/export_pack.py tests/test_release_hardening.py` - passed.
- `python -m compileall -q src/etf_cockpit/chatgpt_bridge/export_pack.py tests/test_release_hardening.py` - passed.
- `git diff --check` - passed; Git emitted only expected LF-to-CRLF working-copy warnings.

## Remaining uncertainty and risk

The complete repository suite and packaged executable smoke were not rerun;
this fix is limited to the export loader seam and its focused regressions.

## Recommended next action

Review the committed diff and continue the parent Task 16 closure workflow.
