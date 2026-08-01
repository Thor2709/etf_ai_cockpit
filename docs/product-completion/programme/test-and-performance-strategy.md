# Test and performance strategy

## Current validation contract

- The canonical classifier selects E/O/H/C. Validation is proportional to risk; H and C fail upward to the complete serial Linux and Windows package gates.
- ISSUE-0177 observability records JUnit, slow tests, stage timings, environment and cache evidence, with early preflight before expensive gates.
- Exact-tree evidence is reusable only when every protected identity matches. Do not weaken tests or repeat unchanged passing validation.
- Safe and unsafe four-worker pytest execution is report-only evidence. The serial packaged gate remains authoritative; the pilot is required only for the documented drift triggers in the delivery workflow.
- The terminal `validation-summary` is the normal CI interface. Raw artefacts are inspected only for failure, inconsistency, sampled audit or final certification.

## Required test layers

- Deterministic unit tests for calculations, parsers, schema joins, adjusted-price handling and risk gates.
- Failure-path tests for missing data, provider conflicts, unavailable optional models, malformed imports, stale evidence and authority-denied actions.
- Focused registry/package/synchronisation tests for byte freshness, stable IDs, DAG validity, dry-run safety, duplicate markers and managed-body preservation.
- Targeted application tests for each changed module, followed by the repository's proportionate lint, compile and smoke checks.

## Performance evidence

Measure representative local startup, cache read/write, refresh, screening, backtest and model operations. Record dataset shape, provider mode, cache state and machine context. Do not claim latency or throughput targets without a measurement.

## Release gates

Run deterministic tests and safety gates before user-visible claims. Optional Toto and TimesFM paths must not be required for launch. Keep execution disabled unless a later explicitly authorised milestone changes that policy with independent safety evidence.
