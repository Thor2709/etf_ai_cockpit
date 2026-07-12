# Wave 1 Governance Task 2 brief

Read this brief before editing. This is the dependency-ordered Wave 1 Governance Task 2 implementation on branch `wave1/governance-task2`, based on `origin/main` at `7735afd46b96c4d327754709c8040f98f7bd88fa`.

## Required outcome

Split public instrument research state from internal analytical intent and migrate legacy signal/score records from import schema 1.x to governance schema 2.0. The current release must never serialise legacy action verbs as public authority. `execution_allowed` remains the fixed invariant `false`; no broker, order, credential, scoring-weight, model-authority, portfolio-target, research-threshold or coverage change is allowed.

## Binding values

Implement separate enums with exactly these values:

- `ResearchState`: `research_candidate`, `watchlist`, `hold_review`, `avoid`, `needs_evidence`, `manual_review`, `not_scoreable`.
- `PortfolioReviewState`: `not_applicable`, `maintain_review`, `increase_exposure_review`, `reduce_exposure_review`, `exit_thesis_review`, `constraints_blocked`.
- `InternalSignalIntent`: `increase`, `maintain`, `decrease`, `exit`, `none` (analytical/backtest namespace only).
- `GateSeverity`: `blocker`, `authority_warning`, `notice`.

No public state enum may contain `buy`, `sell`, `trade`, `order` or `execute`. Compatibility import code may recognise legacy values but must not export them as current values.

Legacy mapping:

`buy`/`add`/`add_candidate` -> `research_candidate`; `hold`/`trim`/`trim_candidate` -> `hold_review`; `sell` -> `avoid`; `no_trade` -> `needs_evidence`; `manual_review` -> `manual_review`; unknown/missing legacy values -> `manual_review` and never a positive state. Preserve the original value as `legacy_action`. Mark `migration_semantics: lossy` for `trim` and `sell` (and document any consistent safe choice for other converted legacy rows). Portfolio review is `not_applicable` unless a contemporaneous portfolio snapshot is explicitly present.

## Interfaces and files

Create `src/etf_cockpit/signals/research_states.py`, `src/etf_cockpit/governance/migrations.py`, `tests/test_research_state_migration.py`, and `evidence/governance/research_state_migration_report.json`.

Modify `src/etf_cockpit/core/types.py`, `src/etf_cockpit/signals/actions.py`, `src/etf_cockpit/signals/simple_scores.py`, `src/etf_cockpit/data/score_history.py`, and the ChatGPT/export schemas as required. Preserve one-release compatibility for existing internal callers/tests while ensuring v2 release-facing serialisation contains only: `research_state`, `portfolio_review_state`, `analysis_status` (`complete|partial|unavailable`), `research_promotion_allowed`, `portfolio_review_allowed`, `execution_allowed=false`, `legacy_action`, `migration_version`, `gate_policy_version`, `gate_policy_checksum`, `schema_version=2.0`. Existing legacy `action`/`final_action` may be accepted only at compatibility import seams and must not appear in new public v2 exports.

Expose:

```python
def migrate_legacy_action(record: Mapping[str, object]) -> ResearchStateMigration: ...
def resolve_research_state(components: Sequence[ScoreComponent], decision: AuthorityDecision) -> ResearchState: ...
```

Migration must be idempotent and semantically byte-equivalent on repeated application, preserve old records until a validated versioned output exists, and support deterministic checksums/row-count/mapped-unmapped evidence. Add migration/research-state operational events where the existing event interface supports them. Do not implement Task 3's central gate resolver or Task 4's journal/review-report replacement.

## TDD and review contract

Write/run a real RED test before production behaviour, then GREEN and REFACTOR. Required initial command:

```powershell
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_trade_proposals.py -q
```

Expected RED is a behavioural failure because the public v2 types/migration do not yet exist, not a syntax/import error. Required GREEN command:

```powershell
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_research_state_migration.py tests\\test_simple_scores.py tests\\test_score_history.py -q
```

Also run focused trade-proposal compatibility tests, scoped Ruff, compileall and the full authoritative suite. Record the seven known generated-data/identity failures separately if they reproduce; Task 2 must add no new failures. Produce `.ai_worklog/task-governance-2-report.md` with RED/GREEN/REFACTOR evidence, changed files, migration report checksum, compatibility notes, full results and unresolved gates. Do not close any issue unless its complete issue-level closure dossier passes; this task is a foundation for the Wave 1 governance issue family (`ISSUE-0008`, `ISSUE-0010`, `ISSUE-0030`, `ISSUE-0043`, `ISSUE-0060`, `ISSUE-0066`) and later tasks still own UI, authority, journal and complete closure evidence.

## Global constraints

- Preserve current local-first architecture, revision-protected persistence, atomic I/O, Data Health, provider/evidence contracts, session tracing and audit manifests.
- `execution_allowed` is always `false`; no authority inflation or execution capability.
- No invented data, credentials, external uploads, destructive actions or unrelated refactor.
- Use repository patterns, deterministic tests and explicit unavailable/blocked states.
