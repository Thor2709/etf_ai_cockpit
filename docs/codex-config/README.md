# Codex configuration snapshot

This directory preserves the latest reviewed personal Codex orchestration configuration used for ETF AI Cockpit development.

## Source authority and local verification

The twelve role files in `agents/` and sanitised `config-core.toml` define the
reviewed routing template. `agent_routing.py` validates both checked-in templates
and can audit actual local configuration. Do not mistake this directory or a
historical PR description for proof of a live runtime.

Current Scout/Editor capability states are read directly from
`agy_delegate.py:CAPABILITY_STATES`; run
`python scripts/programme_execution.py --json` from the repository for the derived
view. The reviewed Scout route is read-only, fresh-project, absolute-workspace.
The only Editor route is disposable exact-base staging and whole-candidate
promotion. Flash never directly edits an authoritative issue worktree. Any
unowned/forbidden staged change rejects the entire candidate; Codex independently
inspects promoted bytes and determines tests. Outside-workspace preventive
containment remains required. Hooks are diagnostic only. Normal V2 supplies
fallback and formal reviewer/risk/release authority; AGY is not a thirteenth role.
AGY editors count as writers, but do not consume V2 child slots.

Only `agy_delegate.py` invokes official AGY. It pins the reviewed CLI/model,
rejects provider/auth overrides and unsafe streams, checks exact Git/filesystem
identity, and removes only its own disposable worktree/project record. Never
bypass permissions, invoke hidden APIs, add credentials, or treat failure as
rollback. Legacy independent AGY issue worktrees are historical candidate work,
not programme ownership. The one-time dispositions are in the control-plane
audit and `docs/development/work-index.json`.

Reviewed Skill source: `codex-skills/antigravity-flash/`. Live installation is
Codex USER scope `~/.agents/skills/antigravity-flash/`, never repository
`.agents/skills`. Repository state cannot prove installation on the current
machine. Root verifies exact source/live hashes, preserves unexpected drift, and
synchronises only an accepted reviewed source. `programme_execution.py --live-skill
<absolute-live-directory> --json` is read-only hash comparison, not installation
or proof that the runtime loaded the Skill. Use a fresh session once if discovery
has not refreshed. Preserve existing local smoke/containment evidence and verify
its exact CLI/model/instruction/environment identity before reuse.

The former experiment matrix and installation checkpoints remain exact historical
evidence in `plans/archive/2026-09-08-control-plane/docs/codex-config/README.md` and
PR #734. They do not override present capability code or fresh local observation.

```text
python docs/codex-config/agy_delegate.py --cwd <absolute-owned-worktree> --agent codex-flash-scout --packet <utf8-task-packet> --timeout 180
python -B -m unittest discover -s docs/codex-config -p 'test_*.py' -v
python docs/codex-config/agent_routing.py
```

The offline harness tests are also exercised by the normal packaged pytest
collection through `tests/test_development_harness.py`; no personal AGY
installation or credentials are required for those tests.

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

The semantic/edit/generator/projection/consumer map and fresh-session commands are in `docs/development/CONTROL_PLANE.md`.
