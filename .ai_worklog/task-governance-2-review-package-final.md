# Wave 1 Governance Task 2 - final review package

## Review range

- Base: `7735afd46b96c4d327754709c8040f98f7bd88fa`
- Head: `939adbe` (`feat: migrate legacy signals to governed research states`)
- Branch: `wave1/governance-task2`
- Scope: public research-state taxonomy, legacy v1.x to v2.0 migration, score-history and ChatGPT/export compatibility seams.

The authoritative diff is the complete Git range from the base to the head above. The historical package in `task-governance-2-review-package.md` records the initial implementation review; this package is the post-fix review manifest.

## Acceptance and evidence bundle

- Task brief: `.ai_worklog/task-governance-2-brief.md`
- Implementation report, RED/GREEN/refactor and verification: `.ai_worklog/task-governance-2-report.md`
- Initial independent review: `.ai_worklog/task-governance-2-review.md`
- First residual re-review: `.ai_worklog/task-governance-2-review-rereview.md`
- Final independent review: `.ai_worklog/task-governance-2-review-final.md`
- Final re-review approval: `.ai_worklog/task-governance-2-review-rereview-final.md`
- Migration evidence: `evidence/governance/research_state_migration_report.json`
- Full-suite evidence: `evidence/governance/task2-full-suite-final.txt`

## Final review verdict

The final fresh re-review reports `SPECIFICATION: PASS`, `CODE QUALITY: PASS`,
and `READY: YES`, with no Critical, Important or Minor findings. The fixed
v2.0 model metadata contract rejects non-2.0 direct construction while the
focused compatibility suite remains green. The full suite has seven recorded
pre-existing generated-data/identity fixture failures; no Task 2 regression
was introduced.

## Reproduction commands

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_research_state_migration.py tests\\test_score_history.py tests\\test_chatgpt_import.py tests\\test_trade_proposals.py tests\\test_product_governance.py tests\\test_feature_registry.py tests\\test_strategy_scope.py tests\\test_gate_policy.py tests\\test_governance_review_regressions.py tests\\test_signal_gates.py tests\\test_import_export.py -q --tb=short
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m compileall -q src
& '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\ruff.exe' check src tests\\test_research_state_migration.py tests\\test_score_history.py
git diff --check 7735afd46b96c4d327754709c8040f98f7bd88fa..939adbe
```
