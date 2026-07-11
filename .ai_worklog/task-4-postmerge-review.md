# Wave 0 Task 4 post-merge independent review

Date: 2026-07-12 (Australia/Sydney)
Worktree: `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task4-postmerge-hardening`
Base: `0f2b2cb`
Review scope: the post-merge scanner hardening only; no source, test, issue or plan authorship.

## Materials and change boundary

- Task 4 plan: `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md`, Task 4.
- Prior implementation/fix evidence: `.ai_worklog/task-4-report.md` and `.ai_worklog/task-4-postmerge-fix-report.md`.
- Working-tree source/test diff is exactly 15 insertions in two files:
  - `src/etf_cockpit/governance/static_checks.py`: top-level `build` and `dist` added to `_EXCLUDED_ROOT_DIRECTORIES` (lines 46 and 48).
  - `tests/scope_boundary/test_package_inventory.py`: `test_ignored_generated_package_roots_are_not_scanned` creates `build/vendor/bad.py` with `place_order` and requires a passing report (lines 36-47).
- `.gitignore` contains `build/` (line 7) and `dist/` (line 8); `git check-ignore --no-index` matched both paths.
- The four `data/.schema_versions/*.json` entries are status-marked but have no content diff (index and worktree hashes match). The supplied fix report and `.codex/` infrastructure files were not edited.

## Specification verification

### Scope and generated roots

- `python -m pytest tests/scope_boundary/test_package_inventory.py -q -rA`: **4 passed**, exit 0.
- `uv` temporary probe with prohibited symbols in `src/etf_cockpit/data/bad.py` and `src/etf_cockpit/models/bad.py`, plus identical files under top-level `build/` and `dist/`: report **fail**, with `PROHIBITED_ORDER_SYMBOL` for both source paths, and no violations under either generated root. This confirms production package subtrees remain scanned while top-level generated roots are excluded.
- Current production scan, run twice with `PYTHONPATH=src`, returned the same deterministic fields on both runs:

```text
schema_version=1.0
result=pass
scanned_files=357
violations=[]
policy_checksum=89680ebfdca87827728919e687f50f30cebe014741ce35eb4b3c32daa83452f1
execution_allowed=False
executable_authority=False
```

Only `generated_at` differed, as expected.

### Task 4/release and authority regressions

- `pytest tests/scope_boundary tests/test_release_hardening.py -rA --tb=short`: **54 passed**, exit 0 (1,280 existing pandas deprecation warnings; no failures).
- `pytest tests/release tests/operations -rA --tb=short`: **75 passed**, exit 0.
- Registry probe: `validate_rejection_registry()` returned no errors; top-level and all three records have `execution_allowed=False` and `executable_authority=False`.
- All three `docs/architecture/future/*.md` files retain the `# Future-only / no-authority` banner. The focused suite also passed the future/test allow-list and executable/config rejection regressions.
- `ruff check src/etf_cockpit/governance tests/scope_boundary`: **All checks passed**, exit 0.
- `python -m compileall -q src tests/scope_boundary`: exit 0.
- `python -m pip check`: **No broken requirements found**, exit 0.
- `git diff --check` and `git diff --check HEAD`: exit 0 (Git emitted only existing LF/CRLF conversion warnings for tracked files).

The historical report stated 74 release/operations passes; this fresh run collected 75, with no failure. The local `.venv` referenced by historical reports was absent, so tests were run in a temporary `uv run --no-project` environment with the declared runtime/test packages; this did not modify repository source, tests, issues or plans.

## Findings by severity

### Critical

None.

### Important

None. The change is limited to generated package roots, and the adversarial source-subtree probe confirms `src/etf_cockpit/data` and `src/etf_cockpit/models` remain in scope.

### Minor

None. The regression is intentionally scoped to `build/`, matching the requested behavioural proof; implementation covers both `build/` and `dist/`.

## Verdicts

**SPECIFICATION: APPROVED**
The Task 4 plan’s package-inventory boundary is met: ignored top-level generated output is not scanned, production source subtrees are scanned, future/test allow-lists and false authority invariants remain intact, and no scope drift is present in the source/test diff.

**CODE-QUALITY: APPROVED**
The two-line policy change reuses the existing top-level-root exclusion mechanism, preserves deterministic scanning/checksums, and has focused behavioural coverage with no unrelated implementation changes.

## FINAL: APPROVED
