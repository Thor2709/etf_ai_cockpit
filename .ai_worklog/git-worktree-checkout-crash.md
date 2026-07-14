# Git worktree checkout crash and safe workaround

Date: 2026-07-14

The Windows Git executable at `C:\Program Files\Git\cmd\git.exe` (version
2.54.0.windows.1) displayed a native application error during the Task 21
worktree checkout: an instruction referenced unreadable memory at address
`0x0000000000000000`. The operation was reproducible at the `git worktree add`
checkout phase. Git created the branch and linked-worktree metadata, but the
target directory contained only its `.git` pointer; `git status` reported every
tracked file as deleted while `git ls-tree HEAD` still showed the complete
commit. The main worktree and existing commits were unaffected.

`git worktree repair` did not populate the directory. The safe workaround was
to avoid the crashing checkout path: extract the verified base commit with
`git archive --format=tar c495ee0 | tar -xf - -C .worktrees\\TASK21~1`, then
refresh only the new worktree index with `git -C .worktrees\\TASK21~1 reset
--mixed c495ee0`. The worktree is now clean on `wave5/task21-audit` and remains
isolated from `main`. No tracked or user data was deleted or reset.

The crash is therefore classified as a Windows Git checkout-process failure,
not a repository corruption or missing-object failure. Continue Task 21 in the
archive-populated worktree; avoid invoking `git worktree add` checkout again in
this environment unless Git is repaired or upgraded.
