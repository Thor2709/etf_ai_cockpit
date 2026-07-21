# Versioned settings bundle

`src/etf_cockpit/application/settings.py` is the sole application boundary for
the ISSUE-0037 settings centre. Presentation code stages a complete
`settings_bundle.v1`, requests a before/after preview, and saves only the exact
previewed revision. It does not calculate policy effects or write individual
configuration files.

The bundle identifies the existing universe/watchlist, target, risk, cost,
model and provider definitions and adds canonical controls for output currency,
long-only asset scope, risk profile, horizon, analysis depth, news/RSS/macro
definitions and local paper settings. Currency conversion, risk-profile
projection and depth-dependent analysis remain explicitly unavailable under
ISSUE-0173, ISSUE-0174 and ISSUE-0175. Selecting a value does not pretend that
the downstream calculation is implemented.

## Persistence and concurrency

`configs/settings.yaml` stores the schema, semantic version, monotonic settings
version, content revision and non-secret controls. Existing configuration files
remain canonical for their detailed values. A save validates the complete
bundle, acquires the shared atomic-write locks, rechecks the expected revision
inside that lock boundary, and publishes all changed configuration plus an
immutable `data/derived/settings_versions/<version>-<hash>.json` snapshot as one
group. A stale editor receives `SETTINGS_REVISION_CONFLICT`; no partial save is
accepted.

Version-zero defaults project compatible legacy onboarding values in memory.
The mappings are deterministic: `conservative/balanced/growth` become
`safe/medium/aggressive`, `short/medium/long` become `1M/3M/9M`, and the legacy
`both` scope becomes `stock+ETF`. Unknown values produce explicit migration
issues and retain safe defaults. Startup never writes a migration.
The application loader returns those diagnostics with the projected bundle and
the Settings centre displays their stable reason codes for manual review.

## Secrets and authority

Secret-shaped field names are normalised across common separator/case variants
and rejected recursively. Provider metadata uses a typed, extra-forbidden,
credential-free projection; populated secret fields in companion provider YAML
also fail explicitly. Secrets are absent from settings YAML, immutable
snapshots, audit export and run identity. Existing environment
overlay reads remain compatible, but the Settings UI no longer calls the
legacy plaintext `.env` writer. Credential CRUD is disabled with
`CREDENTIAL_CRUD_UNAVAILABLE_ISSUE_0176` until the vault, provider and legal
dependencies are integrated.

Every new run manifest includes the exact settings schema, version, revision
and snapshot identity. Verified schema-1.0 manifests remain readable immutable
historical evidence; new schema-1.1 manifests enforce exact settings parity.
Feature, forecast and backtest runs capture one settings identity, bind its
revision into the run ID, reserve the immutable manifest before publishing
outputs, and reuse that same captured revision for cache metadata. Forecast and
backtest cache reads capture one expected revision per operation, so a settings
change cannot mix evidence from two settings eras in one result.
All settings, paper and run-manifest records assert `execution_allowed=false`.
