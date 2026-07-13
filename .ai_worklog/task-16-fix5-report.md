# Task 16 Fix 5 - temporal evidence selection and sector comparison

## Task completed

Fixed the independent-review blockers for deterministic fundamentals/news evidence
selection and observable sector-relative comparison evidence. The change keeps
fundamentals and news context-only (`executable_authority=false`) and does not
alter score or action authority.

## RED

Added regressions before the production changes and ran:

```text
python -m pytest -q tests/test_instrument_detail.py::test_instrument_detail_selects_latest_fundamentals_by_as_of_not_checksum tests/test_instrument_detail.py::test_instrument_detail_news_is_sorted_by_published_then_ingested_time tests/test_fundamentals.py::test_sector_relative_comparison_preserves_peer_benchmark_delta_and_limitation tests/ui/test_screener_ui.py::test_screener_renders_sector_relative_comparison_values_and_limitation
```

Expected failure: 4 failed. Fundamentals selected `2026-07-11` instead of
`2026-07-12`; news remained in input order (`newer`, `older`); the canonical
evidence object had no sector comparison fields; and the screener omitted the
peer/benchmark/delta/limitation values.

## GREEN

- Added chronological, stable sort/select helpers for fundamentals (`as_of_date`)
  and news (`published_at`, `ingested_at`, news ID/checksum tie-breakers).
- Persistence and clean-store readers now use those helpers; instrument detail,
  ETF detail, dashboard, screener and trust previews no longer depend on checksum
  or insertion order for the evidence shown.
- Screener keeps one latest fundamental row per instrument and renders sector
  value, peer, benchmark, delta and limitation fields.
- Extended `FundamentalEvidence` and its clean/audit payload with sector-relative
  comparison fields. Missing comparisons retain an explicit unavailable
  limitation. Schema version is `fundamental_evidence.v3`.

## Evidence

Focused GREEN tests:

```text
python -m pytest -q tests/test_fundamentals.py tests/test_news_context.py tests/test_instrument_detail.py tests/ui/test_screener_ui.py tests/test_news_ui.py
.................................. [100%]
```

Relevant trust regressions passed:

```text
python -m pytest -q tests/test_trust_critical_artifacts.py -k "news or fundamental or context"
. [100%]
```

The complete `tests/test_trust_critical_artifacts.py` file was also attempted;
its unrelated static identity fixture currently has 16 rows while the existing
test requires at least 45 (`test_static_trust_artifacts_cover_providers_and_identity`).

## Checks

```text
ruff check <affected source and test files>   # All checks passed
python -m compileall -q src tests              # exit 0
git diff --check                               # exit 0; only CRLF conversion warnings
```

## Files changed

- `src/etf_cockpit/data/fundamentals.py`
- `src/etf_cockpit/data/news_context.py`
- `src/etf_cockpit/app/selectors/instrument_detail.py`
- `src/etf_cockpit/app/pages/dashboard.py`
- `src/etf_cockpit/app/pages/etf_detail.py`
- `src/etf_cockpit/app/pages/screener.py`
- `src/etf_cockpit/app/pages/trust_evidence.py`
- `tests/test_fundamentals.py`
- `tests/test_news_context.py`
- `tests/test_instrument_detail.py`
- `tests/ui/test_screener_ui.py`

No issue or plan closure documents were edited.
