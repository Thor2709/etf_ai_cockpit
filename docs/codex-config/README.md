# Codex configuration snapshot

This directory preserves the latest reviewed personal Codex orchestration configuration used for ETF AI Cockpit development.

- `global-AGENTS.md` mirrors the global `C:\\Users\\thor2\\.codex\\AGENTS.md`.
- `config.toml` mirrors the current desktop Codex configuration as volatile
  archival evidence. Machine paths, plugin state and runtime identifiers are
  not project authority.
- `agents/` mirrors the 12 configured named-agent role files.
- `config-core.toml` is the sanitised durable model, agent-limit, sandbox
  and Windows template; it intentionally omits machine-specific paths and
  runtime/plugin state.
- The durable V2 routing matrix is cost-optimised for clean first-pass work:
  Astra-low is the root, implementer, reviewer and performance refactorer;
  Astra-medium is the diagnostician and risk reviewer; Sol-medium is the
  planner, test engineer and release verifier; Luna-high is the benchmark
  guard, scout, documentation roles and default fallback. Plan mode is
  medium, and every Luna role uses high reasoning.
- `config.toml` keeps `multi_agent_v2 = true`; the snapshot's V2 feature flag
  must remain enabled when synchronising the durable settings.
- The current Codex 0.153.4 bundled catalog contains Astra. The `models-v1.*`
  files are retained only as historical/manual V1 compatibility material;
  they are not the active V2 routing path. Do not infer current model
  availability or active settings from them.
- The canonical snapshot keeps `max_concurrent_threads_per_session = 6` as a
  hard child-capacity ceiling that leaves room for mandatory review when V2
  retains completed threads. It is not an allocation target: use one child
  normally, no more than two useful children concurrently in ordinary work,
  and a third only for already-required dependency-ready disjoint work whose
  result will definitely be consumed. Workspace-writing remains
  ownership-controlled.
- The repository-root `AGENTS.md` remains the authoritative project-specific instruction file.
- Trust uses verified exact project paths. No supported wildcard or
  parent-directory inheritance was proven; register and validate each future
  isolated worktree explicitly.
- The effective parent workspace currently has network access. Native
  implementer evidence showed that a child role's requested network denial is
  not enforced when the parent grants access, so this snapshot does not claim
  child-level network isolation.
- A parent spawn response exposes only agent ID and nickname. Model, effort,
  sandbox and permission proof must come from child runtime metadata; the
  selected role TOML remains the routing authority.
- These files are a versioned snapshot, not an automatically loaded project configuration. Machine-specific paths, installed plugins and desktop runtime identifiers may require adjustment on another machine.
- A credential-pattern scan found no token, password, API-key, credential or private-key assignments before publication. Do not add credentials to this directory.

## Routing enforcement

Run `enforce-agent-routing.ps1` without switches for a read-only audit of the live root model, concurrency ceiling, V2 feature flag, Luna/high fallback, all 12 live role TOMLs and registered worktrees. Both checked-in configuration templates receive the same configuration checks. Python 3.11 or newer is required for the standard-library `tomllib` parser; no third-party dependency is installed. If necessary, select the interpreter with `-PythonExecutable C:\path\to\python.exe`.

The audit validates TOML structure and exact table scope: root model settings, `[agents]` capacity and fallback, and `[features]` V2 enablement. Malformed TOML, duplicate keys or tables, misplaced controls and the legacy `max_threads` alias fail closed before any override writes.

To update policies, explicitly select only worktrees you own:

```powershell
.\docs\codex-config\enforce-agent-routing.ps1 -ApplyWorktreeOverrides -OwnedWorktree C:\dev\my-owned-worktree
```

`-OwnedWorktree` accepts an array of exact registered worktree paths. Selection is an ownership assertion by the caller; never select Antigravity or another task's worktree without authority. There is no apply-to-all default. Every selected target is preflighted before writes: existing overrides must begin with this script's generated marker, and symlink overrides are refused. Unselected worktrees remain untouched. Generated overrides are written only where `AGENTS.md` differs from canonical policy. No overrides are deleted, no Git exclusion files are edited, and no worktree metadata is pruned. Generated files may appear as untracked files; keep them out of commits. An override in a worktree whose policy has become canonical is retained for its owner to inspect separately.

Run the focused fixture regressions with:

```powershell
python -B -m unittest discover -s docs/codex-config -p test_agent_routing.py -v
```

All test writes use temporary fixtures; the tests do not change live configuration or real worktree overrides.

The canonical product programme remains in `PLAN_step2.md`, `issues/issue_registry.json`, `issues/programme_control_state.json`, and `docs/product-completion/`.
