# Wave 4 Task 9 implementation report

Date: 2026-07-12
Branch: `wave4/task9-identity-evidence`
Base: `2bb2e6e4c16b4df93410ba263b11356d12ee15df`
Owning active issues: `UPDATEV2-0011`, `UPDATEV2-0021`.
`UPDATEV2-0022` is preserved as an already-closed local dossier; no reopening
was performed.

## RED

Focused behavioural tests were added before implementation and run against the
existing partial resolver/ledger contracts:

```text
..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_instrument_identity.py tests/test_source_conflicts.py tests/test_evidence_ledger.py
```

Observed RED: exit 1 with five genuine behavioural failures. The existing
identity type lacked MIC/share-class/listing fields and mismatch warnings; the
metric claim lacked unit/period/as-of provenance; the evidence source lacked
confidence/quality/provider metadata; and the typed ledger adapter signature
was absent. This was not an import or syntax failure.

## GREEN and refactor

Implemented deterministic, authority-ranked identity claims with stable
conflict IDs, source IDs, manual-review reasons, unknown-ISIN state, provider
symbol maps, exchange/MIC/currency/listing/share-class/issuer/CIK fields and
compatibility positional constructors. Implemented deterministic metric
conflict selection retaining every claim, authority-aware human-readable
reasons, evidence-quality reduction and manual-review classification.

Extended typed evidence sources/ledger entries with source ID, authority,
authority rank, as-of date, freshness, confidence, quality, provider,
checksum/conflict linkage and fail-closed eligibility. Added a compatibility
adapter for both historical `(instrument_id, component, value, source)` calls
and typed score-component calls.

Integrated provenance fields into `SimpleScoreComponent` and its eligibility
predicate without changing score weights or authority. Updated trust-artifact
writers to resolve identity through the typed resolver and publish MIC,
share-class, listing, issuer, CIK, identity source/status, conflict reason and
ledger provenance columns atomically. Updated Evidence Ledger, Provider
Status, Filings & Statements and ETF Disclosures tables to display canonical
identity and conflict/provenance details.

## Verification

```text
..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_instrument_identity.py tests/test_source_conflicts.py tests/test_evidence_ledger.py
10 passed

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m compileall -q src tests
exit 0

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m ruff check src/etf_cockpit/data/instrument_identity.py src/etf_cockpit/data/source_conflicts.py src/etf_cockpit/data/evidence_ledger.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_instrument_identity.py tests/test_source_conflicts.py tests/test_evidence_ledger.py
All checks passed!

..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\run_app.py --smoke
snapshot_ok as_of=2026-07-13 signals=16 backtests=5

PYTHONPATH=src python -c "refresh_static_trust_artifacts(load_config())"
paths 7; identity columns 28; identity rows 16; conflict columns 15; ledger columns 22; executable_authority false

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_atomic_io.py tests/test_source_conflicts.py tests/test_evidence_ledger.py tests/test_data_health.py tests/test_optional_providers.py tests/test_strategy_scope.py tests/scope_boundary/test_execution_boundary.py --disable-warnings
35 passed
```

The complete Task 9 plan bundle also includes existing generated-data fixture
failures in `tests/test_simple_scores.py` and
`tests/test_trust_critical_artifacts.py` (missing generated candidate/secondary
fixtures, missing AURG row and 16 identity rows versus the fixture's `>=45`
assertion). These failures reproduce independently of the Task 9 focused
changes and are retained as pre-existing limitations; no new Task 9 failure
was observed in the affected persistence, evidence, provider or scope tests.

## Compatibility and safety

- Existing trust-artifact wrapper names remain stable.
- Existing positional constructors remain compatible through defaulted fields.
- Identity and conflict outputs are atomically written through the current
  `_write_dual` path and retain `executable_authority=false`.
- Missing, stale, unavailable, model, community/manual-context or conflicted
  evidence is not score-eligible.
- `execution_allowed` remains `false`; no broker, credentials, scope, scoring
  weights, model authority, portfolio target or research-threshold changes.

## Review status

Implementation is ready for the parent controller's fresh independent
specification/code-quality review. Package, rendered browser and issue-level
closure evidence are intentionally parent-level gates and no local issue
transition is claimed in this branch.
