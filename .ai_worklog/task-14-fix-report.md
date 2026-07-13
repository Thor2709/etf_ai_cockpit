# Task 14 - rejected-diff fix pass

## Scope

Addressed the review findings for the ETF document registry and holdings evidence only. `execution_allowed=false` and the package/browser gates remain unchanged.

## RED evidence

- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py --disable-warnings --maxfail=1`
  - Exit 1 as expected.
  - Failure: canonical-registry regression could not find `trust_artifacts.FUND_DOCUMENTS_PATH`; the trust inventory was not connected to the registry.
- `python -m pytest -q tests/test_fund_holdings.py::test_name_only_holdings_without_isin_or_ticker_are_context_only --disable-warnings`
  - Exit 1 as expected.
  - Failure: name-only `holding_name` evidence was marked `score_eligible=True` instead of remaining context-only/manual review.

## GREEN changes and evidence

- `src/etf_cockpit/data/fund_documents.py`
  - Added safe canonical registry loading with absent/corrupt-registry compatibility.
  - Blank registry source IDs are deterministically backfilled from instrument/type/checksum/date provenance.
- `src/etf_cockpit/data/trust_artifacts.py`
  - ETF disclosure inventory now prefers `FUND_DOCUMENTS_PATH`, preserves registered `source_id`, URL, date and checksum, emits stable `document_id` compatibility aliases, and adds explicit missing rows for every configured instrument/document type.
  - Raw-directory inventory remains the fallback when the registry is absent.
- `src/etf_cockpit/app/pages/trust_evidence.py`
  - ETF Disclosures preview includes source ID and source URL alongside date/checksum/missing status.
- `src/etf_cockpit/app/pages/risk.py`
  - Look-through exposure fails closed if score eligibility, authority, freshness or completeness metadata is absent or not issuer/full/fresh; future-dated rows are excluded.
- `src/etf_cockpit/data/fund_holdings.py`
  - Future holdings are invalid/unavailable and never score eligible.
  - Name-only `holding_name`/`security_name`/`name` rows without a non-empty ISIN/ticker/holding ID receive `missing_isin_or_ticker_manual_review` and remain context-only; the existing explicit `security` name compatibility remains intact.
- `tests/test_fund_documents.py`, `tests/test_fund_holdings.py`
  - Added regressions for registry provenance/fallback, missing Risk metadata, future dates and identity boundary.

## Focused validation

- `python -m pytest -q tests/test_fund_documents.py::test_document_registry_backfills_blank_source_id_from_provenance --disable-warnings` -> passed, exit 0.
- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py --disable-warnings --maxfail=1` -> 27 passed, exit 0.
- `python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_risk_analytics.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=1` -> 37 passed, exit 0.
- `python -m ruff check src/etf_cockpit/data/fund_documents.py src/etf_cockpit/data/fund_holdings.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/app/pages/risk.py tests/test_fund_documents.py tests/test_fund_holdings.py` -> passed, exit 0.
- `python -m compileall -q src tests` -> passed, exit 0.
- `git diff --check` -> passed, exit 0 (Git emitted only normal LF/CRLF conversion warnings).

## Remaining known baseline

- `python -m pytest -q tests/test_trust_critical_artifacts.py --disable-warnings --maxfail=2` -> 1 failure, 11 passed, exit 1. The pre-existing `identity.shape[0] >= 45` fixture assertion remains at 16 rows; this fix pass does not alter identity generation.
- Full package rebuild, audit/export archive, browser/computer-use smoke, clean-first-run, issue synchronisation and closure-matrix gates were not run, per task scope.
