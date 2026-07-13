# Task 16 Fix 3 - News refresh, contradiction matching and validation counts

## RED

Added regressions for canonical news refresh preservation, token-boundary
headline direction matching, per-status rejection counts, and missing-status
fallback. Before the implementation changes, the three primary regressions
failed as expected: `Group reports results` was treated as up, rejection
statuses had no counts, and refresh dropped `headline`, `credibility`,
`instrument_mapping_method`, `timestamp_status` and `backtest_eligible`.
The missing-status regression also failed until the `unknown=1` fallback was
added.

## GREEN

- Trust refresh now returns all canonical clean news columns, adds only
  missing evidence defaults and `path`/`raw_path` aliases, and forces news to
  remain context-only and non-executable.
- Contradiction detection recognises explicit direction words at token
  boundaries, avoiding substring matches such as `up` in `Group` while still
  detecting `rise`.
- Backtests derives deterministic `status=count` summaries from rejected rows
  only, including `unknown` when status metadata is absent.

Evidence:

```text
python -m pytest -q tests/test_news_context.py tests/test_news_ui.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py -k "not static_trust_artifacts_cover_providers_and_identity"
all selected tests passed

ruff check src/etf_cockpit/app/pages/backtests.py src/etf_cockpit/data/news_context.py src/etf_cockpit/data/trust_artifacts.py tests/test_news_context.py tests/test_news_ui.py tests/test_trust_critical_artifacts.py
All checks passed!

python -m compileall -q src tests
exit 0

git diff --check
exit 0
```

Including the full `tests/test_trust_critical_artifacts.py` file leaves one
pre-existing fixture failure in `test_static_trust_artifacts_cover_providers_and_identity`
(`identity.shape[0]` is 16 rather than the existing 45-row fixture minimum).
