# Git workflow

- Base: `4d5f30e6ac19650030a61bec0e22a4eeb2fd57d9` (`origin/main`).
- Keep the primary checkout and its unrelated untracked files untouched.
- Review `git diff`, run targeted checks, commit the focused change, then use capability-based GitHub checks before any push or issue apply.
- Do not commit the supplied ZIP; commit the archived extracted members, manifest, registry, documents, scripts and tests.
- GitHub Issue apply is permitted only with an approved plan SHA-256 and must read back the resulting state.
- After merge, fetch the new `origin/main`, run `python scripts/update_programme_control.py --refresh-base --baseline <full-origin-main-sha>`, regenerate all canonical evidence, and commit that convergence separately; stale-base checks fail closed until this is done.
