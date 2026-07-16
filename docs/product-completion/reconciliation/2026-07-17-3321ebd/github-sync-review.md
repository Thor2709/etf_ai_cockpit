# GitHub synchronisation dry-run review

The default synchronisation command was run read-only against `Thor2709/etf_ai_cockpit`:

```text
python scripts/sync_github_issues.py
```

The deterministic action plan is `github-sync-plan.json` with SHA-256:

`ec5f8756d03c7201e3ba2a0f037d4a355d30e8f2f4037ccffef2f9cf85fd46b1`

## Capability checks

- GraphQL viewer: `Thor2709`
- Repository permission: `ADMIN`
- `git fetch --prune origin`: passed
- `git push --dry-run origin HEAD:refs/heads/codex-auth-test`: passed
- `gh issue list`: passed
- `gh pr list`: passed

No REST `/user` authentication check was used as a gate.

## Plan summary

| Action | Count | Treatment |
|---|---:|---|
| Create proposed issues | 83 | Safe to review; no write was performed |
| Update uniquely mapped legacy records | 30 | Managed block only; unmanaged body text is preserved |
| Close | 0 | No automatic close action in this snapshot |
| Reopen | 0 | No reviewed reopen action in this snapshot |
| Blocked duplicate mappings | 60 | Human reconciliation required; no arbitrary remote issue is selected |

The 60 blocked records correspond to duplicate legacy stable markers on remote issues. Applying the plan is intentionally refused while any blocked action remains. The plan can be regenerated after the duplicate mapping is resolved, then applied only with `--apply --approved-plan-sha256 <reviewed-plan-sha256>` and read-back verification.

The dry run did not create, edit, close or reopen a GitHub Issue.
