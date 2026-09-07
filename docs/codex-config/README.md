# Codex configuration snapshot

This directory preserves the latest reviewed personal Codex orchestration configuration used for ETF AI Cockpit development.

## Restricted external Antigravity Flash workers

The twelve Codex V2 roles and their model/effort mappings remain unchanged.
`codex-flash-scout` and `codex-flash-editor` are external AGY workers, not V2
children. They consume no V2 slot; editors count as writers under the same
ownership rules. They cannot satisfy formal reviewer/risk/release gates,
decide test sufficiency or write Git/GitHub/canonical programme state. Codex
independently inspects actual changes, selects the existing validation tier
and runs tests. Scout and editor each have independent disabled/shadow/enabled
states. Both currently remain disabled; use normal V2 fallback.

Reviewed Codex skill source: `codex-skills/antigravity-flash/`. After framework
acceptance, root synchronizes these reviewed files to the live Codex USER
scope `~/.agents/skills/antigravity-flash/`, resolving the home directory live,
preflighting existing content and verifying hashes. Never overwrite unexpected
user drift. The skill must not appear in repository `.agents/skills`, which
AGY also discovers. No live user installation is implied by this source tree.
If discovery does not refresh, use one new Codex session without changing
unrelated configuration. The root owns any user-home synchronization/fallback.

AGY custom agents live at `.agents/agents/codex-flash-scout/agent.md` and
`.agents/agents/codex-flash-editor/agent.md`. Both disable shell execution,
subagent invocation and inherited customizations, with empty MCP/skills/plugins.
Scout requests only `view_file`, `grep_search`, `find_by_name`, `list_dir`;
editor adds `write_to_file`, `replace_file_content`, `multi_replace_file_content`.
Bodies contain authority constraints directly. Interactive scout marker
evidence confirmed custom-body visibility and exclusion of root AGENTS, ambient
rules and skills. This does not prove fresh headless custom-agent selection.

Only `agy_delegate.py` invokes official AGY. It resolves PATH, then on Windows
the official per-user `LOCALAPPDATA/agy/bin/agy.exe` location, checks >=1.1.27,
queries models/agents in the exact workspace and requires the discovered
`gemini-3.8-flash-medium` slug. CLI 1.1.27 omits main-agent-only definitions
from the non-interactive agents listing. Byte-identical definitions and
`init.agent` are consistency checks, not proof of selection: the direct
headless run echoed the requested name while logging fallback to default.
High requires an explicit root justification;
other model generations are rejected. Workspace definitions must match the
reviewed source. No credentials, provider configuration, private APIs, MCP
bridges or permission bypass are part of this integration. Existing provider
override environment variables cause rejection rather than configuration edits.

```text
python docs/codex-config/agy_delegate.py --cwd <absolute-owned-worktree> --agent codex-flash-scout --packet <utf8-task-packet> --timeout 180
python -m pytest docs/codex-config/test_agy_delegate.py docs/codex-config/test_agent_routing.py -q
python docs/codex-config/agent_routing.py
python <skill-creator>/scripts/quick_validate.py docs/codex-config/codex-skills/antigravity-flash
git diff --check
```

The wrapper uses `-p`, `--output-format stream-json`, exact `--model`/`--agent`,
`--print-timeout`, `--sandbox` and `--json-schema`, plus `--mode plan` for scout.
It captures both streams, records the primary `init.tools` registry without
requiring it to be a subset of the agent tool list, and validates identity,
permission metadata and a single successful result. Forbidden tool/subagent
activity is a capability containment failure. Denial metadata without forbidden
activity degrades only that assignment; malformed or uncorrelated tool errors
remain rejected without claiming safe containment.
Captured diagnostics are not echoed because they may contain local sensitive
data. Rejection is not rollback: Codex still inspects status/diff after editor
failure. The sandbox flag concerns terminal restrictions; file ownership is
also enforced through the restricted agent contract and independent real-diff
inspection, not an asserted per-file OS sandbox.

Protocol sources checked 2026-09-07:
[headless event/schema/flag documentation](https://www.antigravity.google/docs/cli/headless/),
[custom-agent schema](https://www.antigravity.google/docs/subagents/) and
[terminal sandbox](https://www.antigravity.google/docs/cli/sandbox/).
Deterministic tests use mocked documented streams, not personal Google access.
The completed AGY 1.1.27 matrix used the existing Google AI Pro account and
exact `gemini-3.8-flash-medium` model:

| Route | Observed containment | Automation decision |
| --- | --- | --- |
| Fresh headless `--agent`, plan, sandbox | Echoed scout identity, but logged fallback to default and zero hooks. `invoke_subagent`, `define_subagent`, and `manage_subagents` succeeded; shell/read attempts were separately denied. | Scout disabled; editor disabled. |
| Interactive custom scout | Actual schema restricted; workspace hook loaded. A broad canary agent's forbidden shell, write, web, task, scheduling, permission, messaging and collaboration calls were hard-denied by the strict hook. | Effective when loaded; not fresh task automation proof. |
| Resume interactive scout | Retained scout behavior and hooks, but lacked `init.agent` and required persistent conversation/bootstrap. | Not an accepted automation route. |

The documented subagent `tools` list is not a primary-registry contract;
interactive restrictions and fresh headless selection must be verified
separately. `CAPABILITY_STATES` keeps both capabilities disabled. Even changing
either state to shadow/enabled cannot launch: `require_fresh_containment`
rejects until a reviewed implementation proves positive fresh-headless agent
selection and required hook identity and activation from an adapter-owned
artifact. Absence of fallback, a nonzero hook count or an echoed name is
insufficient. Negative log fixtures cover observed fallback and zero-hook
messages; they do not establish a positive log protocol. No AGY process is
launched by this disabled adapter. Do not sync or install the Skill. Outcome C
is preserved; activation requires capability-specific containment and ownership
evidence.

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
