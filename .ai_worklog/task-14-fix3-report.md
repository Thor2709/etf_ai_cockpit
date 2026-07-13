# Task 14 - mutable holdings frame validation fix

## Review finding and acceptance criteria

The review found that `write_holdings_records` checked only the immutable
`HoldingsNormalisationResult` summary fields. Because `result.frame` remains a
mutable `pandas.DataFrame`, a caller could change weights or row provenance and
replace an existing valid canonical Parquet and CSV pair. The writer must
validate the actual frame and its consistency with the result summary before
staging either file, while retaining valid explicit-ID issuer/full/fresh writes
and the existing compatibility aliases.

## RED

Added `test_write_rejects_mutated_frame_without_replacing_store` to mutate a
previously valid result frame after its first write, then require a `ValueError`
and byte-for-byte preservation of both canonical files.

Command:

```text
python -m pytest -q tests/test_fund_holdings.py::test_write_rejects_mutated_frame_without_replacing_store --disable-warnings
```

Result: exit 1 as expected. The test failed with `Failed: DID NOT RAISE
ValueError`, demonstrating that the old writer accepted the mutated 0.2 weight
and would have staged a replacement.

## GREEN

- `src/etf_cockpit/data/fund_holdings.py`
  - Validates required frame columns, non-empty security/provenance values,
    explicit identity on every row, finite decimal weights and full weight
    coverage.
  - Checks row source/completeness/freshness/authority/score eligibility,
    confidence, dates (including future dates), compatibility aliases and the
    deterministic `source_id` hash against `HoldingsNormalisationResult`.
  - Performs all checks before schema insertion, payload construction or the
    existing atomic Parquet+CSV transaction.
- `tests/test_fund_holdings.py`
  - Added the mutable-frame regression and canonical-file preservation checks.

## Validation evidence

- `python -m pytest -q tests/test_fund_holdings.py --disable-warnings --maxfail=20` -> 32 passed, exit 0.
- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_risk_analytics.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=2` -> 51 passed, exit 0.
- `python -m ruff check src/etf_cockpit/data/fund_holdings.py tests/test_fund_holdings.py` -> passed, exit 0.
- `python -m compileall -q src tests` -> passed, exit 0.
- `git diff --check` -> passed, exit 0 (only normal LF/CRLF conversion warnings).

## Files and limitations

Changed only `src/etf_cockpit/data/fund_holdings.py`,
`tests/test_fund_holdings.py` and this report. Full package rebuild, browser
smoke, clean-first-run and unrelated trust baseline checks were not run because
they are outside this focused writer-validation fix. No execution, broker or
external-write paths were changed.
