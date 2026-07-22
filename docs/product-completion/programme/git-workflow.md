# Git workflow

- Base: `7229e4628c8a60d1f6cc9a3239e99da8aa3044a6` (`origin/main`).
- Keep the primary checkout and its unrelated untracked files untouched.
- Review `git diff`, run targeted checks, commit the focused change, then use capability-based GitHub checks before any push or issue apply.
- Do not commit the supplied ZIP; commit the archived extracted members, manifest, registry, documents, scripts and tests.
- GitHub Issue apply is permitted only with an approved plan SHA-256 and must read back the resulting state.
- After merge, fetch the new `origin/main`, run `python scripts/update_programme_control.py --refresh-base --baseline <full-origin-main-sha>`, regenerate all canonical evidence, and commit that convergence separately; stale-base checks fail closed until this is done.
