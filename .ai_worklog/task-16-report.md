# Task 16 - Fundamentals, News, Point-in-Time Validation and Free Providers

## RED baseline

Command:

```text
pytest -q tests/test_fundamentals.py tests/test_news_context.py tests/test_optional_providers.py
```

Result: expected failure (7 failed, 4 passed). The failures prove the missing contracts: strict five-section eligibility/staleness/source fields, canonical raw/clean persistence, strict NewsItem point-in-time metadata and current-only rejection, and Task 8 capability probes for optional adapters.

Implementation and GREEN evidence will be appended after the focused checks.

## GREEN and focused integration evidence

Commands and results:

```text
pytest -q tests/test_fundamentals.py tests/test_news_context.py tests/test_optional_providers.py
13 passed

pytest -q tests/test_provider_registry.py tests/test_instrument_detail.py
15 passed

pytest -q tests/test_release_hardening.py
31 passed

pytest -q tests/test_evidence_ledger.py tests/test_e2e_workflow.py
5 passed

pytest -q tests/test_release_hardening.py -k "audit_export"
2 passed

ruff check src/etf_cockpit/data/fundamentals.py src/etf_cockpit/data/news_context.py src/etf_cockpit/data/fred_provider.py src/etf_cockpit/data/rss_provider.py src/etf_cockpit/data/stooq_provider.py src/etf_cockpit/data/sec_edgar_provider.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/chatgpt_bridge/export_pack.py src/etf_cockpit/app/pages/etf_detail.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/app/selectors/instrument_detail.py tests/test_fundamentals.py tests/test_news_context.py tests/test_optional_providers.py
All checks passed

python -m compileall -q src
exit 0
```

The implementation keeps yfinance as the default, forces context/news and
fundamentals to `executable_authority=false`, rejects missing/ambiguous/current-only
news from point-in-time backtests, and persists immutable raw plus idempotent
clean/audit rows through atomic writes. Optional FRED, RSS, Stooq and SEC probes
are visible through the Task 8 registry and make no network calls by default.

Remaining closure gates: full release/package/browser/computer-use matrix and
parent-owned issue/closure records. Four `data/.schema_versions/*.json` files
may show metadata-only CRLF/stat changes after pytest; they are unrelated to
Task 16 and should be cleaned before integration.

The repository-wide `pytest -q --tb=short` run completed with eight existing
fixture/package/universe failures outside Task 16: `tests/scope_boundary/test_package_inventory.py::test_current_production_package_inventory_passes`, six
`tests/test_simple_scores.py` tests, and
`tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity`.
Task 16 focused tests remained green; this is not a full-suite pass.

## Fix 3 follow-up

The news refresh, contradiction and Backtests validation regressions are
covered by `.ai_worklog/task-16-fix3-report.md`. The affected bundle remains
green when the pre-existing static identity fixture failure is excluded; no
new full-suite failure was introduced.

## Independent review and UI fix checkpoint

The first fresh reviewer approved the storage/provider paths but rejected the
task for four missing user-facing requirements: Dashboard digest, evidence-
driven contradiction panel, complete News & Context provenance and Backtests
point-in-time warnings. Those paths were implemented in the parent fix pass;
the focused UI/news/instrument bundle and the full affected Task 16 bundle
passed, with Ruff, compileall and diff checks clean. Details and added tests
are in `.ai_worklog/task-16-fix2-report.md`. Independent re-review of this
surface fix is required before integration.
