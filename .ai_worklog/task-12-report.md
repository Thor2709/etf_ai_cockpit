# Task 12 - SEC EDGAR provider and official statement facts

## Scope and acceptance evidence

Implemented the no-key SEC EDGAR acquisition and local statement-facts workflow for `UPDATEV2-0012`. Raw submissions/companyfacts responses are identity-checked against the requested CIK, cached under `data/raw/sec_edgar`, checksum-recorded with sidecar provenance, written atomically, rate-bounded and conditionally revalidated with ETag/Last-Modified when supplied by the transport. Network failure is controlled as unavailable and does not start scoring or broker workflows.

`parse_companyfacts` now retains taxonomy, concept, unit, value, periods, filed/form/accession/fiscal metadata and deterministic SEC source IDs. Explicit US-GAAP mappings are limited to the configured table; duplicate facts are deduplicated with warnings, ambiguous units fail closed, malformed/wrong-identity input produces no records, and custom taxonomies remain retained but unmapped. Clean facts and filing inventory are atomically persisted as parquet with source IDs and official authority.

The Filings & Statements view exposes CIK fetch and local fixture import controls, explicit unavailable/progress messages, statement-facts columns and mapping warnings. AppState routes both paths through the parser and persistence helpers without invoking refresh, model or execution workflows.

## RED-GREEN-REFACTOR

- RED: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py` - failed at collection because `write_statement_facts` was absent (expected).
- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py` - 16 passed.
- Refactor checks: scoped Ruff and compileall passed; generated `data/.schema_versions/*` churn from startup tests was restored and is not part of this checkpoint.

## Files changed

- `src/etf_cockpit/data/sec_edgar_provider.py`
- `src/etf_cockpit/parsers/sec_facts.py`
- `src/etf_cockpit/app/state.py`
- `src/etf_cockpit/app/pages/trust_evidence.py`
- `src/etf_cockpit/core/paths.py`
- `tests/test_sec_edgar_provider.py`
- `tests/test_sec_facts_parser.py`

## Validation and remaining gates

Scoped commands run:

```text
python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py  # 16 passed
python -m pytest -q tests/test_trust_critical_artifacts.py tests/test_e2e_workflow.py tests/test_flet_startup.py tests/test_data_health.py tests/test_paths.py  # 43 passed, 1 existing identity-row assertion failed (16 < 45)
python -m ruff check src/etf_cockpit/data/sec_edgar_provider.py src/etf_cockpit/parsers/sec_facts.py src/etf_cockpit/app/state.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/core/paths.py tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py  # passed
python -m compileall -q src/etf_cockpit/data/sec_edgar_provider.py src/etf_cockpit/parsers/sec_facts.py src/etf_cockpit/app/state.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/core/paths.py  # passed
```

Package rebuild, packaged/browser/computer-use evidence, audit ZIP readback and clean-first-run gates were not run in this implementation worktree and remain pending. No live network evidence is claimed; tests use injected transport and the retained Microsoft official fixture.
