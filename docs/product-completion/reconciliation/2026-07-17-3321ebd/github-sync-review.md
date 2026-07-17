# GitHub synchronisation review and convergence

The synchroniser was run against `Thor2709/etf_ai_cockpit` with dry-run as the default. GitHub writes were permitted only through an approved plan checksum:

```text
python scripts/sync_github_issues.py --apply --approved-plan-sha256 <reviewed-plan-sha256>
```

## Capability checks

- GraphQL viewer: `Thor2709`
- Repository permission: `ADMIN`
- `git fetch --prune origin`: passed
- `git push --dry-run origin HEAD:refs/heads/codex-auth-test`: passed
- `gh issue list`: passed
- `gh pr list`: passed
- Specific Issue read before apply: Issue `#137`, passed

No REST `/user` authentication check was used as a gate.

## Reviewed duplicate mapping

The generated `github-issue-map.json` contains 60 duplicate legacy-marker groups. For each group, the newest remote record was selected because the older duplicate was already closed; all older duplicate Issue numbers were retained closed and were not deleted or edited. The map records every remote number, selected number and selection basis. Ambiguous groups remain blocked by the synchroniser.

## Approved action sets

| Plan | SHA-256 | Create | Update | Close | Reopen | Blocked |
|---|---|---:|---:|---:|---:|---:|
| Initial approved plan | `729cc2c18862316f26983172b4f596bae65d3ed873333e4d54da6dbe9cf5c382` | 83 | 90 | 0 | 1 | 0 |
| Corrective managed-body plan | `1ecc616f896c2ac6fb6b49a3f8c39002eabe3679d5d87e3572e55b52d6f93bee` | 0 | 83 | 0 | 0 | 0 |

The initial plan created the 83 proposed issues, updated the 90 selected existing records and reopened only `ISSUE-0067` on remote Issue `#137`. The corrective plan filled the complete canonical managed fields into the newly created bodies. No close action was required.

The first immediate read-back exposed GitHub eventual-consistency lag. The verifier now retries only the read-back with bounded backoff. The final approved no-op plan is `0a8d37c38cabcbff725b6fb3d657bc5431954c498b2b8681d16844e4f95d6fcc`, reporting zero actions and `APPLIED_AND_VERIFIED`.

The generated convergence record is `github-convergence.json`. It records both approved plans, the final no-op plan, the 60-group map and the aggregate applied totals: 83 creates, 173 updates, 0 closes and 1 reopen.
