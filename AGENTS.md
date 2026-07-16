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

## Verification finalisation workflow

- Separate implementation verification from release certification. A passing implementation/test record is not a release certification and cannot be reused across source or executable changes without a matching shared-record key.
- Reusable release records are keyed by the implementation/source commit represented by the executable, executable hash, environment hash and the exact command. Evidence-only commits retain that implementation commit in the record key, so a passing full suite or build/package command executes once per unchanged implementation key and may be referenced by multiple owning issues. Persist the record and issue/reviewer references durably; never duplicate the run merely to satisfy another issue.
- `executable_hash` is the SHA-256 of the packaged executable bytes only. `evidence_hash` is the checksum of captured evidence content/paths. They are different fields with different trust boundaries; documentation, plans, worklogs, issue ledgers and manifests must not alter executable verification.
- Generate evidence under a per-run temporary or `evidence/staging/<generation>/` directory. Staged evidence is not closure evidence. Promote one immutable generation atomically only after all gates pass; never write tests or diagnostics directly to `evidence/final/`, canonical audit packets, release builds, manifests, issue ledgers or `RUN_STATE.json`.
- Before dispatching any task, load the committed programme ledger/run-state checkpoint. A committed checkpoint is authoritative for resume and must not redispatch a completed gate, review or implementation task. Record the exact next action when a run stops.
- Bound review and verification cycles according to `docs/superpowers/verification-finalisation-policy.md`: no duplicate processes, no interactive commands, no repeated passing gates, and targeted root-cause analysis after repeated failures.
