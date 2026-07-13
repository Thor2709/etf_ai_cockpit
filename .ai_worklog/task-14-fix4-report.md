# Task 14 fix 4 - ETF import and detail evidence path

## Scope and review blockers

This fix closes the approved UPDATEV2-0015/0016 review blockers: canonical
integer holdings schema validation, UTC-future document-date rejection, local
ETF document/holdings import through the registry and normaliser contracts, and
an Instrument Detail ETF disclosure evidence panel. Execution remains disabled;
imports are local-only and fail closed.

## RED evidence

Command:

```text
python -m pytest -q tests/test_fund_documents.py::test_document_registry_rejects_future_dates_fail_closed tests/test_fund_holdings.py::test_write_rejects_mutated_schema_version_without_replacing_store --disable-warnings
```

Result: exit 1 (4 failures as expected). `register_document` accepted future
datetime/date/string values and `write_holdings_records` accepted a mutated
`schema_version="corrupt"` frame; both tests failed with `DID NOT RAISE`.

## Implementation

- `fund_documents._normalise_date` now parses date and ISO datetime inputs,
  normalises timezone-aware values to UTC, rejects dates after the current UTC
  date, and retains valid historical and undated behaviour.
- `fund_documents.import_etf_document` registers a readable local disclosure,
  merges it with the existing registry, builds a complete configured ETF
  inventory and persists the parquet/CSV registry atomically.
- `fund_holdings._holdings_write_reasons` rejects any supplied schema-version
  column value other than the canonical integer `1` before staging either file.
- `fund_holdings.import_etf_holdings` reads CSV/XLS/XLSX, normalises holdings,
  rejects invalid/ineligible results without writing, and writes only eligible
  issuer/full/fresh records.
- ETF Disclosures retains PRIIPs KID and index-methodology parser buttons and
  adds local document registration and holdings import controls with explicit
  cancellation, missing, invalid and preserved-store status messages.
- Instrument Detail now exposes a reusable ETF disclosure model and panel with
  document type/status/date/source/checksum plus holdings completeness,
  freshness, confidence, authority, source and score eligibility; unavailable
  values remain explicit.

## GREEN and quality evidence

- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_instrument_detail.py tests/test_risk_analytics.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=5` -> 59 passed, exit 0.
- `python -m ruff check src/etf_cockpit/data/fund_documents.py src/etf_cockpit/data/fund_holdings.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_instrument_detail.py` -> passed, exit 0.
- `python -m pytest -q tests/test_flet_startup.py tests/test_e2e_workflow.py --disable-warnings --maxfail=3` -> 14 passed, exit 0.
- `python -m compileall -q src tests` and `git diff --check` -> passed, exit 0 (Git emitted normal LF/CRLF conversion warnings only).
- Direct Flet construction checks created the ETF Disclosures controls and
  Instrument Detail route (`Container` and `Column` outputs) without a live
  browser or network.

## Files changed and limitations

Changed: `src/etf_cockpit/data/fund_documents.py`,
`src/etf_cockpit/data/fund_holdings.py`,
`src/etf_cockpit/app/pages/trust_evidence.py`,
`src/etf_cockpit/app/selectors/instrument_detail.py`,
`src/etf_cockpit/app/selectors/__init__.py`,
`src/etf_cockpit/app/pages/instrument_detail.py`,
`tests/test_fund_documents.py`, `tests/test_fund_holdings.py`,
`tests/test_instrument_detail.py`, and this report.

Full package rebuild, browser/computer-use smoke, clean-first-run and external
tracker synchronisation were not run; no network, broker, execution or
external-write path was added. Existing parser controls remain parser-only;
Task 15 parser extraction details are intentionally out of scope.

The affected `tests/test_trust_critical_artifacts.py` module has one known
baseline failure in `test_static_trust_artifacts_cover_providers_and_identity`
(`identity.shape[0]` is 16 while the pre-existing assertion expects at least
45); the focused trust-route test and all changed-module checks pass.
