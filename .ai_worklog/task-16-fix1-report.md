# Task 16 Fix 1 - Review Finding Closure

## RED baseline

The independent review identified three Important contract gaps:

- A two-of-five fundamentals row containing a negative value still returned
  `eligible_negative_evidence` and `score_eligible=true`.
- `persist_fundamental_evidence` and `persist_news_items` wrote new raw JSON
  before the clean/audit atomic group, allowing an injected failure to leave an
  orphan raw generation.
- Instrument Detail news output did not render the complete source, timing,
  provider, credibility, mapping, availability and authority provenance for
  every row.

The RED contract conditions were captured in new assertions in
`tests/test_fundamentals.py`, `tests/test_news_context.py` and
`tests/test_instrument_detail.py`; the stale two-field expectation and
pre-fix write ordering represented the review failures.

## GREEN evidence

Focused contract and UI checks:

```text
python -m pytest -q tests/test_fundamentals.py tests/test_news_context.py tests/test_instrument_detail.py
19 passed

python -m pytest -q tests/test_fundamentals.py tests/test_news_context.py tests/test_optional_providers.py tests/test_provider_registry.py tests/test_release_hardening.py tests/test_instrument_detail.py tests/test_evidence_ledger.py tests/test_e2e_workflow.py
67 passed
```

The strict fundamentals test now proves two-of-five negative evidence is
`not_score_eligible`/`score_eligible=false`, while a complete five-section
negative row remains `eligible_negative_evidence`. Both persistence failure
tests inject a failure at atomic-group commit and prove prior clean/audit bytes
and raw bytes are unchanged with no new orphan raw file. The Instrument Detail
control-tree test observes source URL, published/ingested timestamps, provider,
credibility, mapping, decision-time availability, timestamp status and
`context_only=true`/`executable_authority=false`.

Additional checks:

```text
ruff check src/etf_cockpit/data/fundamentals.py src/etf_cockpit/data/news_context.py src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py src/etf_cockpit/app/pages/etf_detail.py tests/test_fundamentals.py tests/test_news_context.py tests/test_instrument_detail.py
All checks passed

python -m compileall -q src
exit 0

git diff --check
exit 0

python -m pytest -q --tb=short
exit 1 (8 existing fixture/package/universe failures outside Task 16; see task-16-report.md)
```

## Changes

- `build_fundamental_evidence` now requires all five sections for any score
  eligibility; missing metrics remain unavailable rather than negative.
- New raw fundamentals/news payloads are `AtomicWriteRequest`s in the same
  clean/CSV/audit `atomic_write_group`; existing raw generations remain
  immutable and idempotent.
- Both Instrument Detail routes render complete news provenance and explicit
  non-executable authority flags.
