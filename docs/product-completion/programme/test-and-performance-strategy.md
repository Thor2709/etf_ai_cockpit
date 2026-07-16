# Test and performance strategy

## Required test layers

- Deterministic unit tests for calculations, parsers, schema joins, adjusted-price handling and risk gates.
- Failure-path tests for missing data, provider conflicts, unavailable optional models, malformed imports, stale evidence and authority-denied actions.
- Focused registry/package/synchronisation tests for byte freshness, stable IDs, DAG validity, dry-run safety, duplicate markers and managed-body preservation.
- Targeted application tests for each changed module, followed by the repository's proportionate lint, compile and smoke checks.

## Performance evidence

Measure representative local startup, cache read/write, refresh, screening, backtest and model operations. Record dataset shape, provider mode, cache state and machine context. Do not claim latency or throughput targets without a measurement.

## Release gates

Run deterministic tests and safety gates before user-visible claims. Optional Toto and TimesFM paths must not be required for launch. Keep execution disabled unless a later explicitly authorised milestone changes that policy with independent safety evidence.
