# Task 14 - ETF document registry and holdings normaliser

## Scope and acceptance criteria

- Preserve the existing reference-data, trust-artifact, Flet and authority foundations.
- Keep a checksum/date/type inventory for every configured ETF and the factsheet, KID,
  prospectus/report, holdings and methodology document types, including explicit missing rows.
- Persist versioned `fund_documents.parquet` and holdings records atomically with stable source IDs.
- Normalise full holdings at 99-101%, label partial top holdings, reject invalid values,
  cap stale evidence and prevent stale/invalid/vendor partial data from current exposure scoring.
- Surface document/source/date/checksum/missing and holdings completeness/freshness/confidence/exposure
  in ETF Disclosures and Risk while retaining `execution_allowed=false`.

## RED evidence

- Command: `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py --disable-warnings --maxfail=1`
- Exit: 1 (expected RED).
- Failure: test collection raised `ImportError: cannot import name 'DOCUMENT_TYPES'` from
  `etf_cockpit.data.fund_documents`; the new registry/persistence and holdings provenance
  contracts are not implemented yet.

## Changes

- `src/etf_cockpit/data/fund_documents.py`
  - Added canonical five-type registry with aliases for existing PRIIPs/report/methodology names,
    ISO date and optional expected-checksum validation, stable checksum-based source IDs,
    explicit missing inventory rows, exact duplicate suppression and atomic parquet/CSV persistence.
- `src/etf_cockpit/data/fund_holdings.py`
  - Added deterministic holdings normalisation with 99-101% full tolerance, partial vendor/yfinance
    handling, duplicate suppression, invalid weight/identity rejection, freshness/stale confidence cap,
    issuer/vendor authority and current-exposure eligibility, plus atomic provenance persistence.
- `src/etf_cockpit/data/trust_artifacts.py`
  - ETF disclosure inventory now derives from the registry and emits five explicit rows per configured
    instrument when local issuer documents are absent; execution authority remains false.
- `src/etf_cockpit/app/pages/trust_evidence.py`
  - ETF Disclosures previews document source/date/checksum/missing status and normalised holdings
    completeness/freshness/confidence/authority/eligibility.
- `src/etf_cockpit/app/pages/risk.py`
  - Risk now shows holdings quality and only uses `score_eligible` normalised holdings for look-through
    exposure; stale/invalid/vendor-partial rows remain context-only.
- Focused tests cover the above contracts and atomic store schemas.

## GREEN and quality evidence

- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py --disable-warnings --maxfail=1` -> 17 passed, exit 0.
- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_risk_analytics.py --disable-warnings --maxfail=1` -> 21 passed, exit 0.
- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_risk_analytics.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=1` -> 27 passed, exit 0.
- `python -m ruff check src/etf_cockpit/data/fund_documents.py src/etf_cockpit/data/fund_holdings.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/app/pages/risk.py tests/test_fund_documents.py tests/test_fund_holdings.py` -> passed, exit 0.
- `python -m compileall -q src tests` -> passed, exit 0.
- `git diff --check` -> passed, exit 0 (Git emitted only normal LF/CRLF conversion warnings).
- `python -m pytest -q tests/test_trust_critical_artifacts.py --disable-warnings --maxfail=2` -> 11 passed, 1 known baseline failure (identity fixture row-count assertion).
- An attempted `tests/test_reference_data.py`/`tests/test_trust_artifacts.py` command was not run because those paths do not exist in this checkout; no implementation check was skipped where an equivalent existing test was available.

## Known baseline failure

- `tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity` still fails on the pre-existing fixture assertion `identity.shape[0] >= 45` (current baseline has 16); this task did not change identity generation.

## Closure gates pending later

The full package rebuild, audit/export archive, browser/computer-use smoke, clean-first-run,
issue tracker synchronisation and closure-matrix gates remain outside this focused implementation.
