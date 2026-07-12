# Wave 1 Governance Task 3 implementation report

Date: 2026-07-12T18:34:16.3229100+10:00 (report timestamp)
Status: **DONE_WITH_CONCERNS** (implementation and focused gates complete; the authoritative full suite was not rerun to completion in this handoff)

## Task completed

Implemented the central, fail-closed severity-aware authority resolver and
neutralised the deprecated `DataQualityReport.trading_allowed` property. The
resolver returns immutable typed `AuthorityDecision` and policy-ordered
`GateResult` records, carries policy version/checksum metadata, keeps portfolio
review separate from research state, and hard-codes `execution_allowed=False`.

No issue status, plan/ledger, Task 4 journal/review-report, Task 5 UI, broker,
credential, upload or external-write scope was changed. No commit was created;
the controller owns independent review and integration bookkeeping.

## Files and symbols examined

- `src/etf_cockpit/governance/gate_policy.py`: `PortfolioContext`,
  `resolve_authority`, policy metadata and diagnostic helpers.
- `src/etf_cockpit/signals/research_states.py`: `GateResult`,
  `AuthorityDecision` metadata/diagnostics fields and compatibility aliases.
- `src/etf_cockpit/core/types.py`: `DataQualityReport.analysis_allowed` and
  deprecated `trading_allowed` property.
- `src/etf_cockpit/signals/gates.py`, `src/etf_cockpit/services.py`,
  `src/etf_cockpit/portfolio/proposals.py`: migrated internal data-block checks
  to `analysis_allowed`.
- `src/etf_cockpit/audit/local_llm.py`,
  `src/etf_cockpit/chatgpt_bridge/export_pack.py`: release/diagnostic payloads
  now emit literal `trading_allowed: false` without invoking the deprecated
  property.
- `tests/test_authority_resolution.py`: focused resolver contract tests.
- `tests/test_release_hardening.py`: existing data-analysis assertions now use
  `analysis_allowed` rather than the permanently false compatibility property.
- `evidence/governance/gate_resolution_samples/representative_gate_table.json`
  and `policy_checksum.json`: representative typed table and SHA-256 evidence.

## Findings or changes

- Gate results are normalised and sorted by the configured identity,
  data-quality, evidence, model-validity, risk, valuation, signal, portfolio-fit
  and cost order.
- Failed blockers are monotonic and force `not_scoreable` with both promotion
  dimensions false. Failed `authority_warning` gates downgrade a positive
  research candidate to `manual_review`; notices remain visible without
  increasing authority.
- Unknown/duplicate/malformed/empty gate input, invalid portfolio context or an
  unavailable/invalid gate policy returns a diagnostic `manual_review` decision
  with explicit `unavailable` policy metadata.
- A validated `PortfolioContext` can set a separate portfolio review state and
  review flag; it never grants execution and is suppressed by failed blocker or
  warning gates.
- `trading_allowed` emits `DeprecationWarning` and always returns `False`.
  Internal release paths use `analysis_allowed` for data-quality analysis
  gating, so deprecation warnings do not leak into normal operations.

## Evidence

The checked-out `configs/gate_policy.yaml` bytes resolve to policy version
`2026-07-12` and SHA-256
`9b06166c05c60cf1dec7214c2aaa2b9b7e59804bdcfcf0b19195c2a09470d6bb`.
The representative sample records five passing blockers followed by a failed
valuation warning, producing `manual_review`, partial analysis and both
promotion dimensions false. All gate rows and the decision carry the same
version/checksum; execution remains false.

## RED / GREEN / REFACTOR commands and results

### RED (2026-07-12; exact required command; run timestamp recorded in this report at 18:34 AEST)

```powershell
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py -q --tb=short
```

Exit code: **2** during collection. Expected failure: the new test module could
not import the absent `etf_cockpit.governance.gate_policy` module:

```text
ModuleNotFoundError: No module named 'etf_cockpit.governance.gate_policy'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
EXIT_CODE=2
```

### GREEN (2026-07-12)

```powershell
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py -q --tb=short
```

Exit code: **0**; **43 passed**.

### Affected governance/Task 2/proposal/export regressions

```powershell
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_research_state_migration.py tests\test_score_history.py tests\test_chatgpt_import.py tests\test_trade_proposals.py tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py tests\test_governance_review_regressions.py tests\test_signal_gates.py tests\test_import_export.py -q --tb=short
```

Exit code: **0**; **82 passed**. Two pre-existing pandas `FutureWarning`s were
reported by `tests/test_score_history.py`; no failure was introduced.

### Compile and lint

```powershell
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src\etf_cockpit\governance src\etf_cockpit\signals\gates.py src\etf_cockpit\signals\research_states.py src\etf_cockpit\core\types.py src\etf_cockpit\services.py src\etf_cockpit\portfolio\proposals.py src\etf_cockpit\audit\local_llm.py src\etf_cockpit\chatgpt_bridge\export_pack.py tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py
$env:PYTHONPATH='src'; & '..\..\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src\etf_cockpit\governance src\etf_cockpit\signals\gates.py src\etf_cockpit\signals\research_states.py src\etf_cockpit\core\types.py src\etf_cockpit\services.py src\etf_cockpit\portfolio\proposals.py src\etf_cockpit\audit\local_llm.py src\etf_cockpit\chatgpt_bridge\export_pack.py tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py
```

Both exited **0**; Ruff output was `All checks passed!`.

## Full-suite classification

The authoritative `pytest -q --tb=short` run was not rerun to completion in
this handoff because it remained a long-running generated-data workload. The
authoritative Task 2 baseline remains seven pre-existing failures, documented
in `evidence/governance/task2-full-suite-final.txt` and
`.ai_worklog/task-governance-2-report.md`: six generated-data/identity fixture
rows in `tests/test_simple_scores.py` plus the static trust-artifact
identity-count row in `tests/test_trust_critical_artifacts.py`. The focused
Task 3 and affected regression bundles above are green; those seven baseline
failures are not attributed to this change.

## Remaining uncertainty and risk

- Independent review and the controller's final full-suite rerun remain
  outstanding. Working-copy LF/CRLF notices on existing files are environment
  line-ending warnings, not content failures.
- The existing Task 2 checksum manifest records the normalised repository
  bytes; the evidence fixture records the SHA-256 of the checked-out bytes used
  by this resolver (`9b0616…d6bb`). No policy file was modified.

## Self-review status

Focused tests cover blocker monotonicity, warning downgrade, notice visibility,
validated/unvalidated portfolio context, deterministic ordering and metadata,
malformed/unknown input, execution denial and deprecated compatibility
behaviour. `git diff --check` reported no whitespace errors. No unrelated
production refactor or issue bookkeeping was performed.

## Controller full-suite verification (2026-07-12)

The controller reran the authoritative suite after the implementation handoff:

```powershell
$env:PYTHONPATH='src'; & '..\\..\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest tests -q --tb=short
```

The run exited `1` at 100% with exactly seven known pre-existing failures:
six generated-data/identity fixture rows in `tests/test_simple_scores.py` and
the static trust-artifact identity-count row in
`tests/test_trust_critical_artifacts.py`. The full output is preserved at
`evidence/governance/task3-full-suite.txt`; no Task 3 authority, gate,
proposal, serializer or migration regression failed.

The implementation remains ready for fresh independent review. Any issue
closure, plan update and integration bookkeeping are controller-owned and
remain pending until that review passes.
