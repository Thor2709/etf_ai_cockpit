# Wave 1 Governance Task 3 review package

- Base: `2a26619bdbf26f11e8a77dbdefc3ab22d93d213b`
- Head: `221ad99` (`docs: finalise task 3 review range`)
- Branch: `wave1/governance-task3`
- Scope: severity-aware authority resolution, ordered typed gate evidence,
  production release-path propagation and permanent `trading_allowed=False`
  compatibility boundary.

Read the complete Git range from the base to the head above together with:

- `.ai_worklog/task-governance-3-brief.md`
- `.ai_worklog/task-governance-3-report.md`
- `.ai_worklog/task-governance-3-review-rereview.md`
- `src/etf_cockpit/governance/gate_policy.py`
- `src/etf_cockpit/core/types.py`
- `src/etf_cockpit/signals/research_states.py`
- `src/etf_cockpit/signals/signal_pipeline.py`
- `src/etf_cockpit/signals/simple_scores.py`
- `tests/test_authority_resolution.py`
- `evidence/governance/gate_resolution_samples/`
- `evidence/governance/task3-full-suite-integration.txt`

Required independent verdicts are separate specification compliance and code
quality/correctness assessments. The reviewer must actively try to disprove
readiness, including blocker monotonicity, warning downgrade, notice
visibility, malformed/unknown policy input, portfolio-context separation,
policy checksum metadata, production signal/simple-score release propagation,
ordered nine-gate table serialisation, `execution_allowed=False`,
policy-authoritative severity, complete required gate sets, portfolio evidence
completeness and no Task 4/5 scope.

Verification commands already recorded by the implementer/controller:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_authority_resolution.py tests\\test_signal_gates.py tests\\test_release_hardening.py -q --tb=short
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_research_state_migration.py tests\\test_score_history.py tests\\test_chatgpt_import.py tests\\test_trade_proposals.py tests\\test_product_governance.py tests\\test_feature_registry.py tests\\test_strategy_scope.py tests\\test_gate_policy.py tests\\test_governance_review_regressions.py tests\\test_signal_gates.py tests\\test_import_export.py -q --tb=short
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests\\test_simple_scores.py tests\\test_trust_critical_artifacts.py -q --tb=short
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m compileall -q src tests
& '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\ruff.exe' check src/etf_cockpit/core/types.py src/etf_cockpit/signals/research_states.py src/etf_cockpit/signals/signal_pipeline.py src/etf_cockpit/signals/simple_scores.py tests/test_authority_resolution.py
git diff --check 2a26619bdbf26f11e8a77dbdefc3ab22d93d213b..221ad994b7b9f2dfe9dc1e38f268502c960944e5
```
