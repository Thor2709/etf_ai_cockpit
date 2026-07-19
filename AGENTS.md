# Project Codex Rules

This project follows the workspace instructions plus these durable rules:

- Keep the app local-first. Do not add broker automation, external uploads, or cloud services unless explicitly requested.
- Risk gates override model forecasts, ChatGPT audits, and UI actions.
- Toto and TimesFM integrations must be optional. The app must launch and produce baseline signals without model packages or weights.
- Use adjusted prices for return calculations. Never silently mix raw close and adjusted close for signals or backtests.
- Keep UI logic separate from feature, signal, model, backtest and ChatGPT bridge logic.
- New user data should live under `data/`, configs under `configs/`, logs under `logs/` and model files under `models/`.
- Tests must cover deterministic calculations and safety gates before claiming changes are working.
- Issue workflow: document the issue, assign priority and dependencies, implement on a normal branch, run targeted tests, review, merge, then include the change in later consolidated milestone and release testing.

## Native Codex agents and tools

- Native Codex subagents are allowed, up to four concurrent threads; this supersedes earlier prohibitions on native subagents. Use them only for genuinely independent, bounded work.
- The root agent owns integration and shared state, including routers, schemas, migrations, public interfaces, canonical registries, generated programme evidence, commits, pull requests, merges and GitHub issue synchronisation.
- Subagents are read-only by default. An isolated writer may use a separate Git worktree and branch for an explicitly disjoint file boundary, run focused tests and return a local commit; it must not push, merge or update canonical or GitHub issue state.
- Ordinary non-Superpowers plugins, MCP servers and tools are allowed. Only Superpowers skills, workflows, controllers and related content are prohibited; do not invoke, read or follow them.
- After context compaction, continuation, resumption or hand-off, reread the applicable `AGENTS.md` files, `PLAN_step2.md`, `issues/issue_registry.json` and `docs/product-completion/CURRENT_STATUS.json` before acting.

## Canonical programme-status safeguards

- Fetch and verify the latest `origin/main` before generating programme status or reconciliation evidence.
- Compare every proposed `programme_status` against that exact base and the recorded last-good map; only explicitly handed-off issue IDs may transition.
- Validate every status transition, expected count, checksum and generated-document freshness before release. Freshness alone is not evidence of correctness.
- Stop release on any unexpected downgrade, stale-base generation, changed head, unexpected file or ambiguous status diff; preserve the exact evidence for root review.
