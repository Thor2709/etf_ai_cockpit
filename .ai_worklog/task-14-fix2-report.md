# Task 14 - final holdings identity and write fail-closed fix

## Scope and acceptance criteria

Keep Task 14 holdings evidence local and review-only (`execution_allowed=false`). Every
name-only identity, including canonical `security`, must remain manual-review/context-only
unless every row has a non-empty `isin`, `ticker`, `holding_id` or `security_id`. Invalid,
empty or ineligible normalisation results must not replace an existing canonical holdings
store.

## RED evidence

Command:

```text
python -m pytest -q tests/test_fund_holdings.py --disable-warnings --maxfail=20
```

Exit status: 1 (expected behavioural RED). The new canonical-`security` regression was
score-eligible, and the invalid/empty/partial write regressions did not raise `ValueError`.

## Changes and GREEN evidence

- `src/etf_cockpit/data/fund_holdings.py`
  - Applies explicit identity gating per row for `isin`, `ticker`, `holding_id` and
    `security_id`; all accepted name aliases, including `security`, stay context-only when
    any row lacks an explicit identifier and retain the existing manual-review warning.
  - Preserves `holding_id`/`security_id` aliases in the normalised frame and supports them as
    identity columns without changing the existing source/provenance contract.
  - Validates frame, completeness, freshness, issuer authority and `score_eligible` before
    staging any parquet/CSV atomic write; rejects with a clear `ValueError` and therefore
    leaves an existing canonical store untouched.
- `tests/test_fund_holdings.py`
  - Added canonical/name alias and mixed-row identity regressions, explicit-ID eligibility
    coverage, and invalid/empty/ineligible write-preservation checks (parquet and CSV bytes
    plus readback data). Existing persistence fixtures now carry explicit tickers honestly.

Focused GREEN command:

```text
python -m pytest -q tests/test_fund_holdings.py --disable-warnings --maxfail=20
```

Result: exit 0, 31 passed.

Affected GREEN command:

```text
python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_risk_analytics.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=2
```

Result: exit 0, 50 passed.

Quality checks:

- `python -m ruff check src/etf_cockpit/data/fund_holdings.py tests/test_fund_holdings.py` - exit 0.
- `python -m compileall -q src tests` - exit 0.
- `git diff --check` - exit 0 (only normal LF/CRLF conversion warnings).

## Remaining uncertainty and risk

Full package/browser/clean-first-run and unrelated trust baseline gates were not run because
this pass is limited to holdings identity and persistence. No execution, broker or external
write paths were changed.
