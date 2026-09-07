---
name: antigravity-flash
description: Use restricted external Flash workers for fast repository or call-path mapping, candidate test and ownership mapping, omission preflights, supplied local log triage, next-issue preparation during immutable waits, or explicitly bounded mechanical edits. Excludes architecture, formal review, difficult diagnosis, substantial test design, financial/PIT/replay, persistence, security, authority and release decisions.
---

# Antigravity Flash

Codex remains the planner, validator and integrator. Flash is an external AGY
worker, never a V2 role or formal gate. Use only when the expected saving
exceeds the cost of independently checking its answer. Scout and editor each
have independent disabled/shadow/enabled states. Scout is enabled for proven
read-only assignments using the passed fresh-project route with an absolute added workspace;
editor remains disabled pending staged-promotion smoke validation. Root owns acceptance and any live installation or
synchronization. Promote only proven scout task classes.

Read [routing.md](references/routing.md) to select scout versus editor, then
[task-packet.md](references/task-packet.md) before every assignment. Read
[failure-handling.md](references/failure-handling.md) on rejection, timeout,
correction or fallback. Do not invoke raw agy; the only approved entry point is
the repository's `docs/codex-config/agy_delegate.py`.

Locate the repository from the active task, not from this user-installed
skill. The editor adapter creates a disposable worktree from the packet's exact
base and gives AGY only that absolute added workspace. Codex retains exclusive
ownership of the authoritative worktree for the entire transaction. The
complete candidate is rejected if any changed path is unowned or forbidden;
only a wholly valid candidate is promoted. One AGY editor normally; all editors count as writers.
Read-only scouts may overlap only for independently useful assignments.

Invoke with an absolute existing worktree and a local packet file:

```text
python docs/codex-config/agy_delegate.py --cwd <absolute-worktree> --agent codex-flash-scout --packet <packet-file> --timeout 180
```

The adapter contains CLI/version/model consistency checks and pins 3.8 Flash
Medium and rejects unsafe or ambiguous machine output. High requires root's
explicit justification via --high-reason. Never substitute older models,
alter provider/auth/credit settings or bypass permission checks.
Scout uses plan/sandbox mode, `--new-project` and absolute `--add-dir`. Its Git
root must be clean, with no concurrent writer. The adapter compares Git and
filesystem evidence before/after every run, including failure paths.
The staged editor uses accept-edits/sandbox, with the independently evidenced
outside-workspace permission boundary as prerequisite. Hooks are diagnostic.
Promotion checks every tracked, untracked, ignored, deleted and renamed file;
there is no partial filtering. Git metadata, hidden paths, harness controls
and credential/secret paths cannot be owned. Symlinks and reparse points fail
closed. The authoritative base and filesystem must remain unchanged before
promotion; afterward Codex independently reviews every byte and runs focused
validation. Failure never implies rollback. The adapter removes its temporary
Git worktree and the new UUID project record identified by AGY's init event.
If no valid init identity is emitted, report that project cleanup is unverified;
never guess or delete unrelated AGY records.

After every run, Codex checks real Git status/diff and ownership, independently
verifies material claims against source, derives actual tests from canonical
acceptance criteria, determines the existing E/O/H/C tier and runs evidence.
Flash candidate tests are suggestions only. Existing V2 reviewers/risk/release
gates remain mandatory where required. A successful assignment is not issue
completion. At most one root-directed correction pass, then V2 fallback.

Record locally/untracked only task class, exact model, duration, accepted or
rejected, correction/fallback and approximate time saved; no conversations or
credentials. Reviewed source stays in docs/codex-config/codex-skills; live
Codex USER installation is ~/.agents/skills/antigravity-flash. Never install
this skill in repository .agents/skills, where AGY would discover it too.
