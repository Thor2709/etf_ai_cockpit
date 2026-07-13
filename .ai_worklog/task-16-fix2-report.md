# Task 16 Fix 2 - News evidence surfaces

## RED

The independent re-review identified four missing observable paths: no
Dashboard news digest, no evidence-driven contradiction panel, incomplete
News & Context provenance columns, and no Backtests warning for rejected
point-in-time news. The added dashboard, contradiction, news validation and
backtest control assertions fail against the pre-fix surface because those
controls and data paths do not exist.

## GREEN

- `build_news_contradiction_rows` compares only explicit headline direction
  with the next dated deterministic close and returns no rows when evidence is
  unavailable; it never infers sentiment or changes authority.
- Dashboard now shows canonical local-news headline/provider/time digest,
  explicit unavailable state and a `/news-context` action, with
  `context_only=true` and `executable_authority=false`.
- News & Context inventory exposes source URL, published/ingested times,
  provider, credibility, mapping, decision-time availability, timestamp,
  context and authority columns. Its contradiction panel is driven by the
  canonical news and price frames and has explicit empty/unavailable states.
- Backtests shows invalid/current-only/ambiguous/late news counts and reasons;
  rejected context remains excluded and cannot alter deterministic results.

Evidence:

```text
pytest -q tests/test_news_context.py tests/test_news_ui.py tests/test_instrument_detail.py
16 passed

pytest -q tests/test_fundamentals.py tests/test_news_context.py tests/test_news_ui.py tests/test_optional_providers.py tests/test_provider_registry.py tests/test_instrument_detail.py tests/test_release_hardening.py tests/test_evidence_ledger.py tests/test_e2e_workflow.py
focused affected bundle passed

ruff check ...
All checks passed

python -m compileall -q src tests
exit 0

git diff --check
exit 0
```

The full repository suite remains non-green only for the previously recorded
package-inventory, secondary-universe/simple-score and trust-fixture baseline
failures; no Task 16 news-surface failure remains in the focused bundle.
