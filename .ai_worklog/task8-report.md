# Wave 3 Task 8 report

## Task completed

Implemented the canonical provider contracts and local-first registry for
`UPDATEV2-0010`.  The registry covers all nine approved provider IDs, keeps
disabled and incomplete providers explicitly unavailable without invoking
probes, normalises `ok`/rate-limited/timeout/malformed outcomes, gates scoring
to configured `ok` capabilities, redacts provider text/configuration and
publishes versioned probe results through the existing atomic write group.
Provider Status now exposes enabled/configured state, authority, entitlement,
rate/limit note, last success, score eligibility and redacted configuration.
`execution_allowed` remains false.

## RED-GREEN-REFACTOR evidence

RED command (before production edits):

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/test_provider_registry.py tests/test_data_contracts.py
...FFFF.F.F [100%]
6 failed, 5 passed
Failures: missing REQUIRED_PROVIDER_IDS/preferred_authority, timeout normalisation,
persist_probe_results, adapter probe contract and configured score eligibility.
```

GREEN command:

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/test_provider_registry.py tests/test_data_contracts.py
........... [100%]
11 passed
```

Persistence integration RED command (before wiring startup refresh):

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/test_provider_registry.py::test_startup_probe_writer_persists_versioned_registry_rows_and_legacy_columns
F [100%]
KeyError: 'schema_version'
```

Persistence integration GREEN command (after wiring
`trust_artifacts.write_provider_probe_results` through the registry):

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/test_provider_registry.py::test_startup_probe_writer_persists_versioned_registry_rows_and_legacy_columns
. [100%]
EXIT:0
```

The refactor retained the existing `ProviderRegistry.register_probe` seam and
`SourceAuthority.MANUAL` compatibility member used by identity/manual-note
consumers.  No network request is made by adapter capability probes.
The startup trust-artifact writer now calls `ProviderRegistry.persist_probe_results`
and enriches that canonical frame with the legacy manifest aliases, retaining
`provider_name`, `source_authority`, `requires_api_key`, `has_api_key`,
`executable_authority` and related existing consumers.  The version is present
as both a `schema_version` column and Parquet metadata.

## Files and symbols examined

- `src/etf_cockpit/data/contracts.py`: `SourceAuthority`, `ProviderCapability`.
- `src/etf_cockpit/data/provider_registry.py`: `ProviderRegistry`, canonical IDs,
  result normalisation and atomic persistence.
- `src/etf_cockpit/data/providers.py`: `DataProvider`, local and generic adapters.
- `src/etf_cockpit/app/pages/trust_evidence.py`: `provider_status_page`.
- `configs/data_providers.yaml`, `core.config`, `data.trust_artifacts`, source
  conflict/evidence ledger consumers and provider tests.

## Verification

```text
ruff check src/etf_cockpit/data/contracts.py src/etf_cockpit/data/provider_registry.py src/etf_cockpit/data/providers.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_provider_registry.py tests/test_data_contracts.py
All checks passed!

python -m compileall -q src
EXIT:0

provider registry source smoke (load config, canonical IDs, authority precedence,
temporary atomic parquet+CSV persistence): provider_registry_source_smoke=ok 13

Provider Status source/render smoke (sample snapshot, required state labels):
provider_status_ui_source_smoke=ok

Provider/trust integration focused bundle:
55 provider/config/adapter/release-hardening tests passed (EXIT:0).
The trust static-artifact test retains the baseline fixture limitation below
(16 identity rows observed versus the fixture's >=45 assertion).

Temporary persistence checksums:
parquet_sha256=c8aa481c5c2a14332cec6df049b2d573e6f486572f919d45897f9703093adbc2
csv_sha256=dbf8da6f296f62c18667e0492fe2bdc6fa165691cac57980d229c7065cf3238a

Final startup-refresh store checksums (after legacy-column enrichment):
provider_probe_results.parquet=d5c1a78afd5698f95cb5ed44022b527dbf7d35e57b2dd17bfd2261c2752b967f
provider_probe_results.csv=26e98434d845090f540687324895d42af16f3a59c6b7b6cf33c2bac7f1c55ec5
```

Affected bundle command:

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/test_atomic_io.py tests/test_source_conflicts.py tests/test_evidence_ledger.py tests/test_data_health.py tests/test_strategy_scope.py tests/scope_boundary/test_execution_boundary.py
31 passed (EXIT:0)

$env:PYTHONPATH='src'; python -m pytest -q tests/test_trust_critical_artifacts.py
10 passed, 1 failed (EXIT:1)
Existing baseline failure: test_static_trust_artifacts_cover_providers_and_identity
assert identity.shape[0] >= 45 (observed 16 in this isolated checkout).
```

The generated `.schema_versions` files were touched by the existing startup
migration fixture but have identical Git object hashes and no content diff.

## Compatibility and risk

- Existing dataset-scoped settings (`prices`, `fx`, `etf_metadata` and
  `etf_holdings`) continue to resolve to their active provider; canonical
  provider IDs are additive YAML entries disabled by default.
- API keys are represented only as boolean presence metadata in capabilities;
  values are not included in parquet/CSV rows, status text or redacted config.
- `trust_artifacts.write_provider_probe_results` now calls
  `ProviderRegistry.persist_probe_results` during startup refresh, then
  atomically republishes the canonical rows with legacy manifest aliases for
  existing Data Health, exports and Provider Status consumers.
- Independent review and package/browser evidence remain pending parent-level
  release verification.  The affected bundle retains the pre-existing
  identity-fixture limitation above.

## Recommended next action

Parent should review the scoped diff, run the full release/package/browser
gates, and retain the documented identity-fixture limitation before any
issue-state change.
