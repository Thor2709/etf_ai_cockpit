# Task 16 Fix 7 - Mixed-Direction Headline Ambiguity

## Scope and dependency

This bounded follow-up stays within Task 16, Fundamentals, News, Point-in-Time
Validation and Free Providers. The implementation base is the merged Phase 2
commit `57f23ef2e01518f2f49a32730ad73f0646a4b8cd` on
`wave4/task16-post-phase2`. The existing Task 16 source, provider, UI and audit
contracts are preserved. No custom locking or process-liveness mechanism is
introduced; release verification uses the Phase 2 workflow.

## RED

Added `test_mixed_direction_headline_is_unavailable_for_contradiction_checks`
to `tests/test_news_context.py`.

Command:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests/test_news_context.py::test_mixed_direction_headline_is_unavailable_for_contradiction_checks -q
```

Result: failed as expected because the positive-first classifier emitted a
contradiction row for a headline containing both positive and negative terms.

## GREEN

The classifier now assigns `unknown` unless exactly one direction vocabulary is
present. Unsupported headlines remain unavailable and are omitted from
contradiction evidence; unambiguous `up` and `down` behaviour is unchanged.

Focused results:

```text
tests/test_fundamentals.py tests/test_news_context.py tests/test_optional_providers.py tests/test_news_ui.py tests/ui/test_screener_ui.py tests/test_yfinance_provider.py
38 passed

tests/test_complete_audit_packet.py tests/test_release_hardening.py -k "manual_news or audit_export or provider"
11 passed

ruff check src/etf_cockpit/data/news_context.py tests/test_news_context.py
All checks passed

py_compile src/etf_cockpit/data/news_context.py tests/test_news_context.py
exit 0

git diff --check
exit 0
```

## Closure boundary

`ISSUE-0023`, `ISSUE-0025`, `ISSUE-0054` and `ISSUE-0055` remain
implementation-complete and closure-pending. This follow-up does not close
issues or begin Task 17. A fresh read-only independent reviewer approved the
follow-up with no Critical or Important findings. One non-blocking
recommendation remains to add a dedicated negative-direction regression; a
direct negative-direction probe passed and the implementation is unchanged.
Normal pull-request integration and post-merge verification remain the next
actions.
