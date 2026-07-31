# Git workflow

- Base: `2337f6959719a9a4ae1b8ec9efb3927ade2acc7d` (`origin/main`).
- Keep the primary checkout and its unrelated untracked files untouched.
- Review `git diff`, run targeted checks, commit the focused change, then use capability-based GitHub checks before any push or issue apply.
- Do not commit the supplied ZIP; commit the archived extracted members, manifest, registry, documents, scripts and tests.
- GitHub Issue apply is permitted only with an approved plan SHA-256 and must read back the resulting state.
- After merge, the guarded fresh-main workflow regenerates canonical evidence atomically and requires a read-only zero-action GitHub readback. Stale bases, nonzero or unreviewed actions and inconsistent projections fail closed; ordinary merges do not require a separate manual convergence commit.
