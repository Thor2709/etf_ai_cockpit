# Task completed

Fresh independent review of `2a26619bdbf26f11e8a77dbdefc3ab22d93d213b..df40f10`, including the supplied brief, implementation report, review package, actual committed diff, relevant authority/data/export paths and focused tests.

Specification verdict: **REJECT**.
Code quality/correctness verdict: **REJECT**.
**READY: NO**.

# Files and symbols examined

- `src/etf_cockpit/governance/gate_policy.py`: `PortfolioContext.usable`, `_coerce_gate`, `_policy_metadata`, `resolve_authority`.
- `src/etf_cockpit/signals/research_states.py`: `GateSeverity`, `GateResult`, `AuthorityDecision`.
- `src/etf_cockpit/core/types.py`: `DataQualityReport.analysis_allowed`, `DataQualityReport.trading_allowed`.
- Release/data seams in `signals/gates.py`, `services.py`, `portfolio/proposals.py`, `audit/local_llm.py` and `chatgpt_bridge/export_pack.py`.
- `configs/gate_policy.yaml`, focused tests and committed evidence under `evidence/governance/gate_resolution_samples/`.
- Complete base-to-HEAD file list for Task 4 journal/review-report, Task 5 UI and unrelated scope drift.

# Findings or changes

1. **BLOCKING - caller-controlled severity bypasses binding policy severity.** `resolve_authority` copies only policy order/version/checksum at lines 130-137 and retains `GateResult.severity` supplied by the caller. A failed `identity` gate labelled `notice` therefore returns `research_candidate`, `research_promotion_allowed=True` and `analysis_status=complete`. This violates binding blocker monotonicity and permits positive authority after a failed identity gate.

2. **BLOCKING - missing required gates are treated as a complete positive decision.** Lines 118-120 reject only an entirely empty sequence; lines 121-139 never require the nine policy gate IDs. A single passing `cost` notice produces `research_candidate`, `research_promotion_allowed=True` and `analysis_status=complete`, despite identity, data, evidence, model validity, risk, valuation, signal and portfolio-fit evidence being absent. This violates ordered gate semantics and the fail-closed requirement for missing/unavailable policy input.

3. **BLOCKING - portfolio context validation is only a caller assertion.** `PortfolioContext.usable` at lines 36-38 requires only `validated=True` and a non-default review state. `as_of_date` may remain `None`, `holdings_checksum` may remain `"unavailable"`, and arbitrary extra fields are accepted (`extra="allow"` at line 29). Such a context grants `portfolio_review_allowed=True`. This does not establish validated portfolio context and can promote portfolio review from unauthenticated/incomplete context.

4. **NON-BLOCKING observation - compatibility and denial boundaries are correctly narrow.** `DataQualityReport.trading_allowed` warns with `DeprecationWarning` and returns literal `False`; internal analysis paths use `analysis_allowed`; export/audit payloads emit literal false; `AuthorityDecision.execution_allowed` is `Literal[False]` and resolver branches set false.

5. **NON-BLOCKING observation - no forbidden Task 4/5 implementation or production scope drift was found.** The only review/report additions are Task 3 worklog files; no UI/Flet, broker, journal replacement or review-report implementation file changed. Four generated schema-version files were dirty in the working tree but are outside the reviewed committed range and were not modified by this review.

# Evidence

- Observation: `gate_policy.py:125-137` validates gate IDs and applies policy order/metadata but never compares or replaces caller severity with `policy_entries[gate.gate_id].severity`.
- Observation: `gate_policy.py:119-120` checks only `not typed_gates`; there is no equality check between `seen` and the configured gate-ID set.
- Observation: `gate_policy.py:36-38` makes portfolio usability independent of date/checksum evidence.
- Adversarial output: `failed_identity_spoofed_notice research_candidate True False complete [('identity', 'notice', False)]`.
- Adversarial output: `only_cost_notice research_candidate True False complete [('cost', 'notice', True)]`.
- Adversarial output: `validated_without_evidence research_candidate True True complete [('identity', 'notice', True)]`.
- Existing focused tests use caller severities matching expected outcomes and commonly pass partial gate sets, so they do not disprove these bypasses.
- Policy version/checksum propagation is deterministic for accepted rows, and malformed/unknown/empty inputs covered by existing tests return unavailable diagnostic decisions. The blockers concern missing required rows, severity mismatch and unsupported portfolio validation claims.

# Commands or tests run

- `git status --short`, `git log --oneline --decorate -6`, `git diff --stat`, `git diff --name-status`, complete scoped `git diff`, `git diff --check` and targeted `rg` inspection against the requested range. `git diff --check` produced no errors.
- Focused authority/release suite: `pytest tests/test_authority_resolution.py tests/test_signal_gates.py tests/test_release_hardening.py -q --tb=short` - exit 0, **43 passed**.
- Affected governance/migration/proposal/export suite from the package - exit 0, **88 passed**, with two pre-existing pandas `FutureWarning`s.
- Inline adversarial Python probe - exit 0; reproduced all three fail-open outputs quoted above.
- The committed controller full-suite evidence records exactly seven known baseline failures and no Task 3-labelled regression; the broad full suite was not redundantly rerun.

# Remaining uncertainty and risk

The exact business validation criteria for portfolio context are not fully specified, but accepting the default unavailable checksum and absent date as validated is demonstrably weaker than the brief's “requires validated portfolio context” boundary. Correcting the three blockers may change existing partial-gate tests, so regression tests should explicitly cover severity spoofing, every missing gate, and portfolio evidence completeness.

# Recommended next action

Bind severity to the loaded policy (reject any mismatch or overwrite it deterministically), require exactly the configured nine unique gate IDs before any complete/promoting decision, and make portfolio usability depend on validated date/checksum evidence. Add focused adversarial regressions, rerun the two focused bundles, then request a new independent review.

Verdict: reject with blocking findings.
