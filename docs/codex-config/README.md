# Codex configuration snapshot

This directory preserves the latest reviewed personal Codex orchestration configuration used for ETF AI Cockpit development.

- `global-AGENTS.md` mirrors the global `C:\\Users\\thor2\\.codex\\AGENTS.md`.
- `config.toml` mirrors the current desktop Codex configuration as volatile
  archival evidence. Machine paths, plugin state and runtime identifiers are
  not project authority.
- `agents/` mirrors the 12 configured named-agent role files.
- `config-core.toml` is the sanitised durable model, V1, agent-limit, sandbox
  and Windows template; it intentionally omits machine-specific paths and
  runtime/plugin state.
- `models-v1.metadata.json` and `refresh-models-v1.ps1` document the safe V1
  catalogue refresh. Refresh the installed catalogue only with an isolated
  `CODEX_HOME`, restart Codex after refresh, and patch only Sol V2 → V1 and
  Terra V2 → V1; Luna remains V1.
- The repository-root `AGENTS.md` remains the authoritative project-specific instruction file.
- Trust uses verified exact project paths. No supported wildcard or
  parent-directory inheritance was proven; register and validate each future
  isolated worktree explicitly.
- The effective parent workspace currently has network access. Native
  implementer evidence showed that a child role's requested network denial is
  not enforced when the parent grants access, so this snapshot does not claim
  child-level network isolation.
- A parent spawn response exposes only agent ID and nickname. Model, effort,
  sandbox and permission proof must come from child runtime metadata.
- These files are a versioned snapshot, not an automatically loaded project configuration. Machine-specific paths, installed plugins and desktop runtime identifiers may require adjustment on another machine.
- A credential-pattern scan found no token, password, API-key, credential or private-key assignments before publication. Do not add credentials to this directory.

The canonical product programme remains in `PLAN_step2.md`, `issues/issue_registry.json`, `issues/programme_control_state.json`, and `docs/product-completion/`.
