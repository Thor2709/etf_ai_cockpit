# Task 14 fix 6 - retain registered ETF document identities

## Scope

When rebuilding the canonical ETF document inventory, both import paths now use
the union of supplied configured IDs, every non-empty instrument ID already in
the registry, and the imported instrument. Existing source-linked rows remain
eligible for inventory output and each union member receives explicit missing
rows for document types without an available version.

## RED evidence

Command:

```text
python -m pytest -q tests/test_fund_documents.py::test_document_import_preserves_registry_instrument_omitted_from_configured_ids tests/test_fund_holdings.py::test_combined_holdings_import_preserves_registry_instrument_omitted_from_configured_ids --disable-warnings
```

Result: exit 1 with two expected assertion failures. With a non-empty supplied
ID list, each import rebuilt the registry for only the configured/imported ID
and dropped the prior document for the omitted registry instrument.

## Changes

- `fund_documents.import_etf_document` now trims configured IDs, unions them
  with non-empty IDs read from the existing registry, and includes the imported
  instrument before calling `build_document_inventory`.
- `fund_holdings.import_etf_holdings_with_document` applies the same union while
  retaining its existing atomic holdings-plus-registry write path.
- Added regressions that seed an omitted registry instrument, import a second
  document/holdings source, and verify the prior source-linked row and explicit
  inventory identity are retained.

## GREEN and quality evidence

Regression command:

```text
python -m pytest -q tests/test_fund_documents.py::test_document_import_preserves_registry_instrument_omitted_from_configured_ids tests/test_fund_holdings.py::test_combined_holdings_import_preserves_registry_instrument_omitted_from_configured_ids --disable-warnings
```

Result: both tests passed.

Focused acceptance command:

```text
python -m pytest -q tests/test_fund_documents.py tests/test_fund_holdings.py tests/test_button_contracts.py tests/test_instrument_detail.py tests/test_risk_analytics.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=5
```

Result: 67 tests passed.

Quality commands:

```text
python -m ruff check src/etf_cockpit/data/fund_documents.py src/etf_cockpit/data/fund_holdings.py tests/test_fund_documents.py tests/test_fund_holdings.py
python -m compileall -q src tests
git diff --check
```

Result: Ruff passed, compileall passed and diff-check passed. Git emitted only
the normal LF/CRLF conversion warnings.

## Limitations and skipped checks

No full package rebuild, browser/computer-use visual smoke, clean-first-run
reset, network/provider probe, broker/execution path or external write was run;
these are outside this local registry-inventory fix. The focused acceptance set
does not include the broader startup/e2e suite. A follow-up run of the complete
`tests/test_trust_critical_artifacts.py` file produced 77 passes and one
environment-sensitive baseline failure: `test_static_trust_artifacts_cover_providers_and_identity`
observed 16 identity rows instead of its fixture threshold of 45; this is
unrelated to document inventory identity retention.
