# Task 14 fix 5 - preserve holdings context and atomic ETF imports

## Scope and review blockers

This pass keeps ETF evidence local and review-only (`execution_allowed=false`) while
closing the holdings-context, cross-store atomicity and UI-contract gaps from the
independent review. Existing issuer/full/fresh eligibility gates remain unchanged;
vendor, partial, stale and legacy evidence remain context-only.

## RED evidence

Command:

```text
python -m pytest -q tests/test_fund_holdings.py::test_holdings_import_merges_one_instrument_without_dropping_other_canonical_rows tests/test_fund_holdings.py::test_risk_holdings_loader_keeps_legacy_vendor_context_when_canonical_exists tests/test_fund_holdings.py::test_combined_holdings_import_leaves_holdings_and_registry_unchanged_when_registry_stage_fails --disable-warnings
```

Result: exit 1 with three expected failures. The import replaced the canonical
store, Risk returned canonical rows without the separate legacy/vendor context, and
the combined transaction helper did not yet exist.

## Changes

- `fund_holdings.import_etf_holdings` now reads the existing canonical parquet,
  replaces only the imported instrument and publishes the merged parquet/CSV pair;
  invalid or ineligible incoming data still fails closed without mutation.
- `fund_holdings.import_etf_holdings_with_document` stages merged holdings plus the
  document registry parquet/CSV mirrors in one `atomic_write_group` transaction.
  Registry-source rows retain prior inventory, checksums and missing states.
- `risk._load_holdings_evidence` combines canonical holdings with the separate
  legacy/reference path instead of hiding vendor/partial context when canonical data
  exists. Eligibility filtering remains issuer/full/fresh and `score_eligible=True`.
- `fund_documents._as_document` accepts persisted registry `checksum` aliases when
  rebuilding an inventory.
- `trust_evidence._disclosure_import_controls` uses the combined local import helper;
  KID and index-methodology parser controls remain unchanged.
- Added `etf-disclosures.import-document` and `etf-disclosures.import-holdings` UI
  acceptance keys without removing existing controls.

## GREEN and quality evidence

Focused command:

```text
python -m pytest -q tests/test_fund_holdings.py tests/test_fund_documents.py tests/test_button_contracts.py tests/test_instrument_detail.py tests/test_risk_analytics.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered --disable-warnings --maxfail=5
```

Result: all collected tests passed.

UI/startup regression command:

```text
python -m pytest -q tests/test_flet_startup.py tests/test_e2e_workflow.py --disable-warnings --maxfail=5
```

Result: all 14 tests passed.

Quality commands:

```text
python -m ruff check src/etf_cockpit/data/fund_holdings.py src/etf_cockpit/data/fund_documents.py src/etf_cockpit/app/pages/risk.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_fund_holdings.py
python -m compileall -q src tests
git diff --check
```

Result: Ruff passed, compileall passed and diff-check passed (only normal Git
LF/CRLF conversion warnings were emitted).

## Files changed

`configs/ui_acceptance.yaml`, `src/etf_cockpit/data/fund_holdings.py`,
`src/etf_cockpit/data/fund_documents.py`, `src/etf_cockpit/app/pages/risk.py`,
`src/etf_cockpit/app/pages/trust_evidence.py`, `tests/test_fund_holdings.py`, and
this report.

## Limitations and skipped checks

No full package rebuild, browser/computer-use visual smoke, clean-first-run reset,
network/provider probe, broker/execution path or external write was run. These are
outside this local persistence/UI-contract fix. The atomic regression injects a
registry parquet validation failure and verifies all four canonical/mirror files
retain their exact prior bytes; interruption recovery remains covered by the
existing atomic-I/O test suite.
