# Project Codex Rules

This project follows the workspace instructions plus these durable rules:

- Keep the app local-first. Do not add broker automation, external uploads, or cloud services unless explicitly requested.
- Risk gates override model forecasts, ChatGPT audits, and UI actions.
- Toto and TimesFM integrations must be optional. The app must launch and produce baseline signals without model packages or weights.
- Use adjusted prices for return calculations. Never silently mix raw close and adjusted close for signals or backtests.
- Keep UI logic separate from feature, signal, model, backtest, and ChatGPT bridge logic.
- New user data should live under `data/`, configs under `configs/`, logs under `logs/`, and model files under `models/`.
- Tests must cover deterministic calculations and safety gates before claiming changes are working.

## Bounded verification and evidence rules

- Tests and diagnostic exports must use per-test temporary directories. They must never write to `evidence/final/`, the canonical `data/audit_packets/` path, release ZIPs, verification manifests, issue ledgers, `RUN_STATE.json`, or build outputs used as final evidence.
- Do not repeat the full suite, Ruff, compileall, Windows build, package launch, or independent review unless relevant source, test, configuration, documentation, or packaging files changed or the prior evidence was invalidated.
- Generate final audit packets, screenshots, checksums, and verification manifests only after tests and builds are complete. Treat hashed final evidence as immutable thereafter.
- Use non-interactive commands with explicit timeouts: five minutes for focused tests and diagnostics, 20 minutes for the full suite and Windows builds, and five minutes for network or download operations. Never start a duplicate while one is running.
- Complete and integrate the current approved task before starting a dependency-valid later task. Preserve `execution_allowed=false`, local-first behaviour, fail-closed safety gates, and all authority boundaries.
