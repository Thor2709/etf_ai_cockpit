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
- `trust_artifacts.write_provider_probe_results` now publishes one atomic
  canonical-plus-legacy union frame during startup refresh, retaining the
  canonical capability fields alongside legacy manifest aliases for existing
  Data Health, exports and Provider Status consumers.
- Independent review and package/browser evidence remain pending parent-level
  release verification.  The affected bundle retains the pre-existing
  identity-fixture limitation above.

## Recommended next action

Parent should review the scoped diff, run the full release/package/browser
gates, and retain the documented identity-fixture limitation before any
issue-state change.

## Independent review fix pass

The first fresh independent review rejected commit `4324b05` with one Critical
and one Important finding and recorded one Minor closure-criteria gap:

- a bearer header left the token suffix visible after redaction;
- startup refresh overwrote the canonical registry columns while adding legacy
  aliases; and
- the provider matrix lacked an explicit `forbidden` state test.

RED evidence was the reviewer’s direct probe against `4324b05`: bearer output
was `***redacted*** super-secret-token`, and the startup Parquet was missing
`authority`, `configured`, `entitlement`, `rate_limit_note`,
`last_success_at`, `error_fingerprint` and `score_eligible`. The newly added
regressions were then run before the fix and failed on these behaviours.

The fix pass now redacts complete `Authorization`/`Proxy-Authorization` and
Bearer values, preserves the canonical and legacy provider columns in one
versioned startup artefact, recognises `forbidden` as non-score-eligible and
non-executable, and covers the final Parquet/CSV output. GREEN verification:

```text
..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest -q tests/test_data_contracts.py tests/test_provider_registry.py
14 passed

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m compileall -q src tests
exit 0

..\..\etf_ai_cockpit\.venv\Scripts\python.exe -m ruff check src/etf_cockpit/data/contracts.py src/etf_cockpit/data/provider_registry.py src/etf_cockpit/data/providers.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_provider_registry.py tests/test_data_contracts.py
All checks passed!

..\..\etf_ai_cockpit\.venv\Scripts\python.exe scripts\run_app.py --smoke
snapshot_ok as_of=2026-07-13 signals=16 backtests=5
```

The affected regression bundle remains 42 passed and one pre-existing identity
fixture failure (`identity.shape[0] == 16`, expected `>=45`) in the isolated
worktree. No Task 8 provider or trust-artifact failure remains in the affected
tests. Package/browser evidence and the final independent re-review remain
parent-level gates.

## Final independent review

Fresh re-review of `4324b05` plus `44f9dab` against `ebc7927` passed
specification compliance and code quality with no Critical or Important
findings; READY_FOR_INTEGRATION was yes. The reviewer’s only Minor observation
was the historical `UPDATEV2-0010` status text disagreeing with the open
closure-matrix record. The issue record is now explicitly `Open, partial` and
the historical evidence is labelled as a rejected/partial checkpoint; no false
closure is claimed. Package rebuild and rendered browser evidence remain
parent-level closure gates.

## Parent package and rendered verification

Fresh package verification was run after the fix-pass review:

```text
cmd /c "scripts\build_windows.bat"
EXIT=0
Portable folder created at build\ETF_AI_Cockpit_Portable_v0.1.0_20260713_012732
```

PyInstaller was not installed in the runner, so the native Flet executable was
not produced; native and portable-native executable smoke are explicitly
not_applicable for this environment. The portable source launcher was started
from the generated folder and served HTTP 200:

```text
python build\...\scripts\launcher_core.py launch --mode source --root build\... --preferred-port 8574 --open-browser 0 --timeout 60
ready url=http://127.0.0.1:8574/
HTTP=200
portable_launch=0
```

Source smoke passed when pointed at the verified repository data root:

```text
python scripts\smoke_app.py --mode source --port 8573 --timeout 90
smoke_ok mode=source url=http://127.0.0.1:8573/
```

The isolated worktree source smoke also reached the app but retained the
known generated identity fixture limitation (`AURG`/16 rows versus the
fixture's >=45 assertion); this is the same pre-existing limitation recorded
by the affected regression bundle and is not a provider-registry failure.

Rendered browser verification used the source app at `http://127.0.0.1:8575/`:

- Provider Status route opened as `/providers` and visibly rendered the
  capability registry, disabled/unavailable states, source authority,
  entitlement, rate-limit state, score-eligibility context, and the explicit
  API-key redaction statement.
- Default viewport screenshot:
  `evidence/task8-provider-status.png`
  SHA-256 `84B81F9774A3DBA208DD0E73B6F4443A4EAE69EC39D0AC9490DC4ED2D3B39D98`
  (88,309 bytes).
- Narrow 390x844 viewport screenshot:
  `evidence/task8-provider-status-mobile.png`
  SHA-256 `49FD7480D63DA8877ACC61FFBDD0E2AEB799E4453C18473DC5DB1EDFCAA4DBB6`
  (36,245 bytes). The page remained readable with the existing responsive
  shell and retained semantic text states; keyboard focus was exercised with
  a Tab keypress and no credentials were displayed.

The screenshot and package evidence are supplementary release evidence; the
known identity fixture failure remains the only affected-suite failure.
