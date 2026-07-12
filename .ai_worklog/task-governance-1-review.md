# Wave 1 Governance Task 1 independent review

**Review scope:** `3922afc48fb21ab22465ad890733caa5e0717afc`..`b24a46debf191d13332345b79808691ca35e9150` on `wave1/governance-task1`.

**Reviewed inputs:** `.ai_worklog/task-governance-1-brief.md`, `.ai_worklog/task-governance-1-report.md`, `.ai_worklog/task-governance-1-review-package.md`, `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-governance-plan.md` Task 1, and the approved Group A governance specification (A.4.4/A.4.5 and GOV-01.4-GOV-01.7).

## Verdict

The implementation has a useful immutable/no-execution foundation, but it is not ready for acceptance. A metadata-only or otherwise incomplete policy is reported as a valid policy, several required governance fields/inventory entries are absent, and gate/checksum evidence can be misleading.

`SPECIFICATION: CHANGES_REQUIRED`

`CODE QUALITY: CHANGES_REQUIRED`

## What passed review

- `Lifecycle`, `Authority`, and `GateSeverity` literals contain the required vocabularies in `src/etf_cockpit/governance/models.py:18-35`.
- Policy models are frozen, assignment-validating and extra-forbidden (`models.py:38-46`). The product, feature, strategy and gate objects carry literal `False` execution fields.
- The focused command independently passed: `18 passed`.
- Route coverage is exact for the current router: 22 `PAGES` routes and 22 registry routes, with no missing or extra route.
- The five manifest SHA-256 values match the current YAML bytes, and the changed deliverables contain no positive execution/credential/upload authority values or secrets.
- Missing files, parse failures and ordinary malformed payloads return diagnostic `manual_review`/`not_scoreable` results in the exercised paths. Explicit positive `order_transmission` authority is rejected.

## Findings

### Critical

**C1 - incomplete policy files fail open as valid (`product_scope.py:167-203`; `models.py:71-106,151-164,204-214,237-269`).**

`_load_policy()` checks only `schema_version`, `policy_id` and `policy_version`. All substantive model sections have defaults (`ProductGovernancePolicy.product`/`authority`, and empty registry tuples), so a YAML mapping containing only those three headers loads with `diagnostic_mode=False`, `valid=True` and a non-`None` policy for all five loaders. I reproduced this with a temporary metadata-only file: product, feature, strategy, gate and glossary loaders all returned non-diagnostic results (the registries had zero entries). This contradicts A.4.4's fail-closed rule and the implementation report's claim that incomplete policies become diagnostic. An empty gate policy or empty route/strategy registry can let later consumers proceed without the required controls.

Make substantive sections required and validate them before returning a successful result: require the canonical product and authority blocks, non-empty/complete feature and strategy entries, the ordered gate set, and the required glossary terms. Unknown/incomplete schema must return the emergency diagnostic result (`manual_review`, `not_scoreable`, no promotion/review), with regression tests for metadata-only and each missing nested block.

### Important

**I1 - feature registry does not implement the approved registry contract (`configs/feature_registry.yaml:7-28`; `models.py:119-164`).**

The approved GOV-01.5 example requires `name`, `category`, `routes`, `data_dependencies`, `issue_ids`, `tests`, `export_contracts`, and `package_gate` per user-visible subsystem. The new entry model only has a singular `route`, `title`, `required_data`, `tests` and `visible`; issue traceability, export/package gates and the multi-route contract are silently absent. The test only checks `set(PAGES).issubset(...)`, so the 22-route count can pass while required governance metadata is missing. Add the required typed fields (or an explicitly documented compatibility-equivalent), validate each route against the registry, and test all mandatory metadata and title/route consistency.

**I2 - strategy inventory is incomplete and not schema-complete (`configs/strategy_scope.yaml:7-31`; `models.py:167-201`).**

GOV-01.5 requires entries for transparent baseline strategies, TimesFM/Toto/future ML challengers, LLM assistance, provider news/context, paper portfolios, pair/cointegration, triple-barrier research, future broker architecture and all rejected strategies. The file has no experimental strategy at all and omits the TimesFM/Toto/future-ML, paper-portfolio and triple-barrier entries. The model has no explicit `intended_use` or `execution_authority` field (it uses `execution_allowed` instead), and many entries rely on defaults rather than recording each required authority field. Add the required entries and typed fields, make omission of required authority metadata invalid, and add inventory coverage tests.

**I3 - strategy contradiction checks do not cover all authority dimensions (`models.py:187-201`).**

The validator checks score/research/portfolio flags, but it permits positive paper authority on rejected/future-only strategies and permits mismatched combinations such as `StrategyScopeEntry(strategy_id="x", lifecycle="rejected", authority="none", paper_authority=True)` or `authority="none", score_authority=True`. These cases currently construct successfully despite the approved parser rules requiring rejected/future-only scopes to carry no authority and requiring permitted authority to agree with the lifecycle. Reject every positive authority flag for rejected/future-only entries, enforce coherent `authority`/flag combinations, and add adversarial tests for all six lifecycle values (including experimental promotion/weight evidence).

**I4 - gate severity can be configured to grant authority (`models.py:217-234`; `configs/gate_policy.yaml:8-15`).**

Only `blocker` gates reject positive `research_promotion_allowed`/`portfolio_review_allowed`. `authority_warning` and `notice` entries with either flag set validate successfully. The approved semantics are that blockers block, authority warnings downgrade and notices remain visible without increasing authority (plan Task 3, and A.4.2's separation of promotion/review dimensions). A malformed policy can therefore encode a warning/notice that grants authority to a later resolver. Reject positive promotion/review flags for warning/notice entries, or model pass/fail effects explicitly so no severity can increase authority, and test each severity's monotonic behaviour.

**I5 - required glossary coverage is missing (`configs/glossary.yaml:7-18`; `models.py:255-269`).**

GOV-01.7 requires at least evidence authority, freshness, research state, portfolio-review state, blocker/authority-warning/notice, volatility, liquidity/spread proxy, confidence interval/quantile, walk-forward, purging/embargo, model promotion, forecast-error measures, N/A versus zero and source conflict (in addition to alpha/beta/drawdown/calibration/PBO/DSR/MASE/slippage/edge-to-cost). The file contains only 12 terms and omits most of that required set. Add the complete term set with app-specific authority/use definitions and validate required terms in the loader.

**I6 - checksum provenance points at a revision that cannot contain the policies (`evidence/governance/policy_checksums.json:5`).**

The manifest's `source_commit` is the review base `3922afc...`; `git cat-file` confirms all five `configs/*.yaml` policy paths are absent from that revision. The hashes match today's bytes, but the recorded checkpoint cannot prove those bytes came from the named source revision. Record the implementation/head revision (or a real content-addressed tree containing the policies), and add a deterministic provenance test that the named revision contains each path and the recorded digest.

**I7 - policy checksums are not included in audit exports (`configs/audit_manifest.yaml:1-5`; `src/etf_cockpit/chatgpt_bridge/export_pack.py:282-316`).**

A.4.4 requires every governance file's checksum in every run/export that uses it and inclusion in the audit packet. The existing export manifest has no `policy_checksums.json`/governance-policy requirement, and `_write_audit_manifest()` does not add or serialise the governance policy set. Add the policy manifest and policy version/checksums to the required audit entries and export tests; ensure unavailable/invalid governance is represented by the diagnostic marker rather than silently omitted.

### Minor

**M1 - unsupported schema versions are accepted (`models.py:74-76`; `product_scope.py:167-180`).**

`schema_version` is an unconstrained non-empty `str`; a feature policy with `schema_version: "9.9"` loads as valid. Versioned policy loading should reject unknown versions or route them to diagnostic mode, rather than silently accepting a schema future consumers may not understand.

**M2 - contradiction classification relies on error-message substring matching (`product_scope.py:125-145`).**

`_validation_is_explicitly_contradictory()` scans `str(ValidationError)` for broad markers such as `"authority"`. A benign unknown field containing that substring can be re-raised instead of becoming the documented diagnostic result, and behaviour depends on Pydantic wording. Inspect `ValidationError.errors()` locations/types and classify only explicit authority fields; add malformed/unknown-field regression cases.

## Verification evidence

Commands run independently in the review worktree:

```text
python -m pytest tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py -q
18 passed

python -m pytest -q
323 collected; 316 passed; 7 failed

python -m ruff check src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py
All checks passed

python -m compileall -q src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py
exit 0

python -m pip check
No broken requirements found.
```

The seven full-suite failures are the reported pre-existing generated-data/identity failures: missing `yahoo_trade_candidates_*.csv`, absent secondary-tier rows, missing AURG/MSFT fixture rows and the 16-versus-45 identity fixture assertion. None is in the changed governance files and the focused governance suite passes. The base revision also contains neither the new governance tests nor the new governance modules, supporting the recorded RED collection failure.

No production code or tests were modified during this review; only this review report was added.
