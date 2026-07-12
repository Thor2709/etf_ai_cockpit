# Wave 1 Governance Task 1 - fix review package

Base: 3922afc48fb21ab22465ad890733caa5e0717afc
Head: fb509a176b2a71f965041465dd61b006cd8ac227

## Task definition
# Governance, Research-State and No-Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `GOV-01` through `GOV-04` by replacing release-facing transaction vocabulary with versioned research and portfolio-review states, typed fail-closed gates, a decision journal and a mechanically enforced no-broker boundary.

**Architecture:** The new governance package owns policy parsing, authority resolution and compatibility migration. Existing score, portfolio, export and Flet modules consume resolved typed results; they never recreate authority from strings or model output.

**Tech Stack:** Python 3.13, Pydantic, PyYAML, PyArrow/Parquet, DuckDB, Flet, pytest, Hypothesis and existing session/audit utilities.

## Global Constraints

- No scope drift; do not add broker, order, credential or external-upload functionality.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service.
- Tests must prove observable behaviour and failure paths; one mock-call assertion is insufficient.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- Visible Flet changes reuse the existing dark research-cockpit vocabulary and expose semantic, keyboard and state behaviour.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.
- Store task reports in the progress ledger, `RUN_STATE.json`, `.ai_worklog` and the closure matrix only after evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Create `src/etf_cockpit/governance/models.py` | research, portfolio review, internal intent, gate and authority models |
| Create `src/etf_cockpit/governance/product_scope.py`, `feature_registry.py`, `strategy_scope.py`, `gate_policy.py`, `migrations.py` | validated config, checksum and v1-to-v2 compatibility |
| Create `src/etf_cockpit/signals/research_states.py` | converts supported analytical output and gate decisions into public research state |
| Create `src/etf_cockpit/portfolio/review_reports.py` | non-executable portfolio-review report replacement |
| Create `src/etf_cockpit/data/decision_journal.py` | append-only journal/outcome store using atomic grouped writes |
| Modify `src/etf_cockpit/core/types.py:1-131`, `signals/actions.py:1-52`, `signals/gates.py:1-46`, `signals/simple_scores.py:133-1989`, `portfolio/proposals.py:1-99`, `app/state.py:1-358` | migrate legacy vocabulary and authority paths |
| Modify `chatgpt_bridge/`, `audit/local_llm.py`, `data/trust_artifacts.py:1-943`, config/export schemas | serialise only v2 public authority fields |
| Create Flet pages/components | System Map, Help & Glossary, Decision Journal, authority badge and gate drawer |

**Interfaces:**

```python
class ResearchState(StrEnum):
    RESEARCH_CANDIDATE = "research_candidate"
    WATCHLIST = "watchlist"
    HOLD_REVIEW = "hold_review"
    AVOID = "avoid"
    NEEDS_EVIDENCE = "needs_evidence"
    MANUAL_REVIEW = "manual_review"
    NOT_SCOREABLE = "not_scoreable"

class AuthorityDecision(BaseModel):
    analysis_status: Literal["complete", "partial", "unavailable"]
    research_state: ResearchState
    portfolio_review_state: PortfolioReviewState
    research_promotion_allowed: bool
    portfolio_review_allowed: bool
    execution_allowed: Literal[False] = False
    gates: list[GateResult]

def resolve_authority(base_state: ResearchState, gates: list[GateResult], portfolio_context: PortfolioContext | None) -> AuthorityDecision: ...
```

### Task 1: Define and load governance policies fail closed

**Files:**

- Create: `configs/product_governance.yaml`, `configs/feature_registry.yaml`, `configs/strategy_scope.yaml`, `configs/gate_policy.yaml`, `configs/glossary.yaml`, `src/etf_cockpit/governance/models.py`, `src/etf_cockpit/governance/product_scope.py`
- Test: `tests/test_product_governance.py`, `tests/test_feature_registry.py`, `tests/test_strategy_scope.py`, `tests/test_gate_policy.py`

**Consumes:** foundation wave checksum/evidence facilities.

**Produces:** validated, checksum-bearing policy objects and diagnostic fail-closed loading mode.

- [ ] **Step 1: Create failing policy tests**

```python
def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})
    with pytest.raises(ValidationError, match="order_transmission"):
        load_product_governance(path)

def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
    with pytest.raises(ValidationError, match="score_authority"):
        StrategyScopeEntry(lifecycle="experimental", score_authority=True)
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`

Expected: FAIL because governance policy models and files are absent.

- [ ] **Step 3: Implement immutable policy models and checksum loading**

All loaders return a Pydantic object, schema version and SHA-256 checksum. An invalid or absent policy yields `GovernanceLoadResult(diagnostic_mode=True)` with `manual_review`/`not_scoreable`, no research promotion and no portfolio review.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`

Expected: PASS; every production route and user-visible subsystem has one feature registry entry, and prohibited authority combinations fail validation.

- [ ] **Step 5: Checkpoint policy provenance**

Generate `evidence/governance/policy_checksums.json` with no secret values and attach it to the wave ledger.

### Task 2: Split public research state from internal signal intent and migrate historical records

**Files:**

- Create: `src/etf_cockpit/signals/research_states.py`, `src/etf_cockpit/governance/migrations.py`, `tests/test_research_state_migration.py`
- Modify: `src/etf_cockpit/core/types.py:1-131`, `src/etf_cockpit/signals/actions.py:1-52`, `src/etf_cockpit/signals/simple_scores.py:133-1989`, `data/score_history.py`, export schemas

**Consumes:** Task 1 policy checksums.

**Produces:** v2 serialisation with `research_state`, `portfolio_review_state`, explicit authority fields and traceable `legacy_action`.

- [ ] **Step 1: Create failing migration and public-type tests**

```python
def test_v1_trim_migrates_lossily_and_preserves_original_value() -> None:
    migrated = migrate_legacy_action({"action": "trim", "schema_version": "1.0"})
    assert migrated.research_state is ResearchState.HOLD_REVIEW
    assert migrated.legacy_action == "trim"
    assert migrated.migration_semantics == "lossy"

def test_no_public_authority_model_accepts_buy_or_sell() -> None:
    assert "buy" not in ResearchState._value2member_map_
    assert "sell" not in PortfolioReviewState._value2member_map_
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_research_state_migration.py tests\test_simple_scores.py tests\test_trade_proposals.py -q`

Expected: FAIL because public models still expose legacy `Action` values.

- [ ] **Step 3: Implement v1-to-v2 migration and score-output adapter**

```python
def migrate_legacy_action(record: Mapping[str, object]) -> ResearchStateMigration: ...
def resolve_research_state(components: Sequence[ScoreComponent], decision: AuthorityDecision) -> ResearchState: ...
```

The migration maps unknown legacy action values to `manual_review`, preserves original text, is idempotent and writes a new versioned dataset before any catalogue pointer changes.

- [ ] **Step 4: Run GREEN and property tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_research_state_migration.py tests\test_simple_scores.py tests\test_score_history.py -q`

Expected: PASS; repeat migration is semantically byte-equivalent and an experimental model cannot create a positive public research state.

- [ ] **Step 5: Record migration report**

Write row counts, mapped/unmapped values, old/new checksums and a compatibility-window note to `evidence/governance/research_state_migration_report.json`.

### Task 3: Centralise severity-aware gates and permanently neutralise `trading_allowed`

**Files:**

- Create: `src/etf_cockpit/governance/gate_policy.py`, `tests/test_authority_resolution.py`
- Modify: `src/etf_cockpit/signals/gates.py:1-46`, `src/etf_cockpit/core/types.py:1-131`, `src/etf_cockpit/services.py:1-end`, `portfolio/proposals.py:1-99`, exports

**Consumes:** Tasks 1-2 types/policy.

**Produces:** deterministic `AuthorityDecision` and typed `GateResult` tables consumed by all release paths.

- [ ] **Step 1: Write RED monotonicity tests**

```python
def test_failed_blocker_cannot_be_erased_by_later_pass() -> None:
    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, [identity_blocker, later_signal_pass], None)
    assert decision.research_state is ResearchState.NOT_SCOREABLE
    assert decision.execution_allowed is False

def test_deprecated_trading_allowed_warns_and_returns_false() -> None:
    with pytest.deprecated_call():
        assert DataQualityReport(findings=[]).trading_allowed is False
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py -q`

Expected: FAIL because warning-compatible `trading_allowed` remains permissive and no typed resolver exists.

- [ ] **Step 3: Implement policy-driven resolver**

`resolve_authority()` processes identity, data, evidence, model validity, risk, valuation, signal, portfolio fit and cost in that order. A blocker always blocks both promotion dimensions; authority warnings downgrade positive state; notices remain visible without increasing authority.

- [ ] **Step 4: Run GREEN and Hypothesis invariants**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py -q`

Expected: PASS; adding a failed blocker or authority warning never increases authority and all decisions carry policy checksum/version.

- [ ] **Step 5: Publish gate audit evidence**

Export a representative typed gate table and policy checksum in `evidence/governance/gate_resolution_samples/`.

### Task 4: Replace portfolio proposals with non-executable review reports and create the Decision Journal

**Files:**

- Create: `src/etf_cockpit/portfolio/review_reports.py`, `src/etf_cockpit/data/decision_journal.py`, `tests/test_portfolio_review_reports.py`, `tests/test_decision_journal.py`
- Modify: `src/etf_cockpit/portfolio/proposals.py:1-99`, `src/etf_cockpit/app/state.py:352-358`, `data/trust_artifacts.py:1-943`, audit/export modules

**Consumes:** Tasks 2-3 public states and atomic write transaction contract.

**Produces:** non-executable review report and immutable user-owned journal/outcome records.

- [ ] **Step 1: Write RED persistence and authority tests**

```python
def test_portfolio_review_report_is_never_executable() -> None:
    report = create_portfolio_review_report(signal, portfolio_context=None)
    assert report.execution_allowed is False
    assert report.portfolio_review_state is PortfolioReviewState.NOT_APPLICABLE

def test_journal_correction_appends_without_mutating_original(tmp_path: Path) -> None:
    original = journal.create(entry, root=tmp_path)
    corrected = journal.supersede(original.journal_entry_id, entry.model_copy(update={"thesis": "revised"}), root=tmp_path)
    assert journal.get(original.journal_entry_id, root=tmp_path).thesis == entry.thesis
    assert corrected.supersedes_entry_id == original.journal_entry_id
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_review_reports.py tests\test_decision_journal.py tests\test_trade_proposals.py -q`

Expected: FAIL because transaction-shaped proposal output and mutable/no journal store remain.

- [ ] **Step 3: Implement compatibility alias and atomic append-only journal**

The deprecated `create_trade_proposal()` delegates to `create_portfolio_review_report()`, emits a deprecation event and is absent from Flet controls. Journal entries and outcomes use atomic grouped JSON/Parquet index commits; logs keep IDs/checksums but never raw thesis or notes.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_review_reports.py tests\test_decision_journal.py tests\test_atomic_io.py -q`

Expected: PASS, including interrupted-index-write, duplicate-ID and private-log fixtures.

- [ ] **Step 5: Record artifact contracts**

Include an opt-in journal export sample with no raw private notes in `evidence/governance/decision_journal_export_summary.json`.

### Task 5: Deliver governance surfaces and static release boundary

**Files:**

- Create: `src/etf_cockpit/app/pages/system_map.py`, `src/etf_cockpit/app/pages/help_glossary.py`, `src/etf_cockpit/app/pages/decision_journal.py`, `src/etf_cockpit/app/components/governance_badges.py`, `tests/ui/test_system_map_ui.py`, `tests/ui/test_help_glossary_ui.py`, `tests/ui/test_decision_journal_ui.py`, `tests/ui/test_authority_gate_ui.py`
- Modify: `src/etf_cockpit/app/router.py:1-182`, `app/flet_app.py`, score/portfolio/instrument pages, `pyproject.toml`, README and audit templates

**Consumes:** Tasks 1-4 and Wave 0 static boundary checker.

**Produces:** explicit lifecycle/authority/help/journal UI and no broker/action controls in source/package resources.

- [ ] **Step 1: Write RED UI and wording tests**

```python
def test_system_map_shows_future_execution_as_non_interactive() -> None:
    view = build_system_map(state)
    assert text_of(view).contains("Not installed")
    assert "Enable trading" not in text_of(view)

def test_gate_drawer_is_keyboard_addressable() -> None:
    assert semantics_of(build_gate_summary(authority_decision)).button("View all gates").focusable
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_system_map_ui.py tests\ui\test_help_glossary_ui.py tests\ui\test_decision_journal_ui.py tests\ui\test_authority_gate_ui.py -q`

Expected: FAIL because routes, page builders and semantic controls do not exist.

- [ ] **Step 3: Implement reusable Flet components and routes**

Use semantic labels, text and icon for lifecycle/severity. System Map cards show lifecycle, authority, data/validation status, direct route and limitation. Help links from gates/scores resolve glossary anchors. Decision Journal forms present a single clear primary action and state user ownership/no execution.

- [ ] **Step 4: Run GREEN and boundary report**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_system_map_ui.py tests\ui\test_help_glossary_ui.py tests\ui\test_decision_journal_ui.py tests\ui\test_authority_gate_ui.py tests\scope_boundary -q`

Expected: PASS. Then run ` .\.venv\Scripts\python.exe -m etf_cockpit.governance.static_checks --root . --output evidence\governance\execution_boundary_report.json` and expect `result=pass`.

- [ ] **Step 5: Conduct task review and wave evidence capture**

Render source and packaged builds at 1366×768, 1920×1080 and 150% zoom; verify focus, unavailable, partial, error and future-only states. A separate reviewer must check specification compliance and code quality before any governance tracker record changes.


## Initial review
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


## Fix report
# Wave 1 Governance Task 1 - review fix report

## Scope

This fix pass addresses the independent review of Task 1 (`.ai_worklog/task-governance-1-review.md`). It remains limited to the approved fail-closed governance policy contract and audit-manifest visibility. No product authority, scoring weights, execution boundary or coverage scope changed.

## RED evidence

- Date: 2026-07-12 (Australia/Sydney)
- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_governance_review_regressions.py -q`
- Result before the fix: exit status 1, 21 failures and 2 passes.
- The failures reproduced the review gaps: metadata-only and empty policies were accepted, unsupported schema versions were accepted, lifecycle/authority combinations were not fully rejected, feature and strategy metadata inventories were incomplete, the glossary was incomplete, the checksum source revision was not real, and audit exports did not expose governance checksums and diagnostics.
- The RED test file was `tests/test_governance_review_regressions.py`; its SHA-256 is recorded by the implementation commit and the review package.

## GREEN implementation

- `src/etf_cockpit/governance/models.py` now uses an explicit supported schema version, complete typed feature and strategy metadata, lifecycle/authority compatibility checks, and non-granting gate severities while preserving `execution_allowed = false`.
- `src/etf_cockpit/governance/product_scope.py` rejects metadata-only, empty, unsupported and incomplete policy documents with deterministic diagnostic-mode results; contradictory authority input remains a validation error.
- All five policy YAML files contain the required substantive inventories, route coverage, strategy scope entries, gate order and glossary terms.
- `src/etf_cockpit/chatgpt_bridge/export_pack.py` copies the policy checksum manifest into the audit packet and records schema version, five policy checksums and an explicit valid/diagnostic marker.
- `configs/audit_manifest.yaml` declares the governance checksum artefact and diagnostic contract.

## Passing evidence

- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py tests\test_governance_review_regressions.py -q -k 'not policy_checksum_manifest_names_real_revision_with_all_policy_files'`
- Result: exit status 0; 42 tests passed.
- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_governance_review_regressions.py::test_audit_manifest_includes_governance_checksums_version_and_diagnostic_marker -q`
- Result: exit status 0; audit-manifest governance visibility passed.

- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q`
- Result: exit status 1 with 316 passed and 7 pre-existing failures, matching the recorded baseline. The seven failures are the generated-data/identity gaps in `tests/test_simple_scores.py` and `tests/test_trust_critical_artifacts.py`; no new failure was introduced by this task.
- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src/etf_cockpit/governance src/etf_cockpit/chatgpt_bridge/export_pack.py tests/test_governance_review_regressions.py; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src/etf_cockpit/governance src/etf_cockpit/chatgpt_bridge/export_pack.py`
- Result: exit status 0; Ruff and compilation checks passed after the lint-only correction.

The checksum-source-revision check is intentionally pending the fix commit: the manifest must name the real commit that contains the final policy YAML files and their final hashes. It will be updated and verified immediately after the implementation commit.

## Review status

The initial independent review identified one Critical and seven Important findings. This report records the implementation fix pass; a fresh independent re-review is required before integration. No issue is closed by this task; the owning governance issues remain open for their later migration, resolver, journal and UI tasks.


## Diff
diff --git a/.ai_worklog/task-governance-1-brief.md b/.ai_worklog/task-governance-1-brief.md
new file mode 100644
index 0000000..262aa81
--- /dev/null
+++ b/.ai_worklog/task-governance-1-brief.md
@@ -0,0 +1,43 @@
+### Task 1: Define and load governance policies fail closed
+
+**Files:**
+
+- Create: `configs/product_governance.yaml`, `configs/feature_registry.yaml`, `configs/strategy_scope.yaml`, `configs/gate_policy.yaml`, `configs/glossary.yaml`, `src/etf_cockpit/governance/models.py`, `src/etf_cockpit/governance/product_scope.py`
+- Test: `tests/test_product_governance.py`, `tests/test_feature_registry.py`, `tests/test_strategy_scope.py`, `tests/test_gate_policy.py`
+
+**Consumes:** foundation wave checksum/evidence facilities.
+
+**Produces:** validated, checksum-bearing policy objects and diagnostic fail-closed loading mode.
+
+- [ ] **Step 1: Create failing policy tests**
+
+```python
+def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})
+    with pytest.raises(ValidationError, match="order_transmission"):
+        load_product_governance(path)
+
+def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
+    with pytest.raises(ValidationError, match="score_authority"):
+        StrategyScopeEntry(lifecycle="experimental", score_authority=True)
+```
+
+- [ ] **Step 2: Run RED**
+
+Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`
+
+Expected: FAIL because governance policy models and files are absent.
+
+- [ ] **Step 3: Implement immutable policy models and checksum loading**
+
+All loaders return a Pydantic object, schema version and SHA-256 checksum. An invalid or absent policy yields `GovernanceLoadResult(diagnostic_mode=True)` with `manual_review`/`not_scoreable`, no research promotion and no portfolio review.
+
+- [ ] **Step 4: Run GREEN**
+
+Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`
+
+Expected: PASS; every production route and user-visible subsystem has one feature registry entry, and prohibited authority combinations fail validation.
+
+- [ ] **Step 5: Checkpoint policy provenance**
+
+Generate `evidence/governance/policy_checksums.json` with no secret values and attach it to the wave ledger.
diff --git a/.ai_worklog/task-governance-1-fix-report.md b/.ai_worklog/task-governance-1-fix-report.md
new file mode 100644
index 0000000..8504238
--- /dev/null
+++ b/.ai_worklog/task-governance-1-fix-report.md
@@ -0,0 +1,39 @@
+# Wave 1 Governance Task 1 - review fix report
+
+## Scope
+
+This fix pass addresses the independent review of Task 1 (`.ai_worklog/task-governance-1-review.md`). It remains limited to the approved fail-closed governance policy contract and audit-manifest visibility. No product authority, scoring weights, execution boundary or coverage scope changed.
+
+## RED evidence
+
+- Date: 2026-07-12 (Australia/Sydney)
+- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_governance_review_regressions.py -q`
+- Result before the fix: exit status 1, 21 failures and 2 passes.
+- The failures reproduced the review gaps: metadata-only and empty policies were accepted, unsupported schema versions were accepted, lifecycle/authority combinations were not fully rejected, feature and strategy metadata inventories were incomplete, the glossary was incomplete, the checksum source revision was not real, and audit exports did not expose governance checksums and diagnostics.
+- The RED test file was `tests/test_governance_review_regressions.py`; its SHA-256 is recorded by the implementation commit and the review package.
+
+## GREEN implementation
+
+- `src/etf_cockpit/governance/models.py` now uses an explicit supported schema version, complete typed feature and strategy metadata, lifecycle/authority compatibility checks, and non-granting gate severities while preserving `execution_allowed = false`.
+- `src/etf_cockpit/governance/product_scope.py` rejects metadata-only, empty, unsupported and incomplete policy documents with deterministic diagnostic-mode results; contradictory authority input remains a validation error.
+- All five policy YAML files contain the required substantive inventories, route coverage, strategy scope entries, gate order and glossary terms.
+- `src/etf_cockpit/chatgpt_bridge/export_pack.py` copies the policy checksum manifest into the audit packet and records schema version, five policy checksums and an explicit valid/diagnostic marker.
+- `configs/audit_manifest.yaml` declares the governance checksum artefact and diagnostic contract.
+
+## Passing evidence
+
+- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py tests\test_governance_review_regressions.py -q -k 'not policy_checksum_manifest_names_real_revision_with_all_policy_files'`
+- Result: exit status 0; 42 tests passed.
+- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_governance_review_regressions.py::test_audit_manifest_includes_governance_checksums_version_and_diagnostic_marker -q`
+- Result: exit status 0; audit-manifest governance visibility passed.
+
+- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q`
+- Result: exit status 1 with 316 passed and 7 pre-existing failures, matching the recorded baseline. The seven failures are the generated-data/identity gaps in `tests/test_simple_scores.py` and `tests/test_trust_critical_artifacts.py`; no new failure was introduced by this task.
+- Command: `$env:PYTHONPATH='src'; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src/etf_cockpit/governance src/etf_cockpit/chatgpt_bridge/export_pack.py tests/test_governance_review_regressions.py; & 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src/etf_cockpit/governance src/etf_cockpit/chatgpt_bridge/export_pack.py`
+- Result: exit status 0; Ruff and compilation checks passed after the lint-only correction.
+
+The checksum-source-revision check is intentionally pending the fix commit: the manifest must name the real commit that contains the final policy YAML files and their final hashes. It will be updated and verified immediately after the implementation commit.
+
+## Review status
+
+The initial independent review identified one Critical and seven Important findings. This report records the implementation fix pass; a fresh independent re-review is required before integration. No issue is closed by this task; the owning governance issues remain open for their later migration, resolver, journal and UI tasks.
diff --git a/.ai_worklog/task-governance-1-report.md b/.ai_worklog/task-governance-1-report.md
new file mode 100644
index 0000000..e3325c8
--- /dev/null
+++ b/.ai_worklog/task-governance-1-report.md
@@ -0,0 +1,108 @@
+# Wave 1 Governance Task 1 implementation report
+
+## Boundary and ownership
+
+Task: Wave 1 Governance Task 1 - define and load governance policies fail
+closed. Branch: `wave1/governance-task1`. Base: `3922afc48fb21ab22465ad890733caa5e0717afc`.
+Implementation commit: `9081909c9c2e5b679fcf11b8f7203560d17e3d51`.
+This task establishes policy contracts only. It does not migrate legacy action
+types, add the governance routes, create the Decision Journal, change issue
+ledgers or close `ISSUE-0008`, `ISSUE-0015`, `ISSUE-0030`, `ISSUE-0043` or
+`ISSUE-0047`; those requirements remain open for their later governance tasks
+and complete source/UI/package/browser evidence.
+
+The product boundary is preserved: every policy and load result carries
+`execution_allowed: false`; no broker, order, credential or external-upload
+capability was added.
+
+## RED - observed before policy implementation
+
+Command:
+
+```powershell
+& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q
+```
+
+Result: exit 1 during collection with four genuine missing-module failures:
+`etf_cockpit.governance.models` and `etf_cockpit.governance.product_scope` did
+not exist. The tests were not syntactically invalid and did not pass before
+the implementation.
+
+## GREEN and refactor evidence
+
+- Focused policy suite after implementation and contract hardening: exit 0,
+  18 passed.
+- Wider affected regression:
+  `tests/test_product_governance.py tests/test_feature_registry.py
+  tests/test_strategy_scope.py tests/test_gate_policy.py
+  tests/test_closure_matrix.py tests/test_release_hardening.py
+  tests/operations/test_verification_records.py`: exit 0, 64 passed.
+- Ruff:
+  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py`
+  -> exit 0.
+- Compilation:
+  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py`
+  -> exit 0.
+- Dependency check:
+  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pip check`
+  -> `No broken requirements found.`
+- Policy provenance validator: five YAML SHA-256 values in
+  `evidence/governance/policy_checksums.json` matched their source bytes and
+  the manifest authority field is false.
+
+The full authoritative suite was rerun for regression comparison: 323 tests
+were collected, 316 passed and the same seven generated-data/identity failures
+as the clean baseline remained. They are unrelated to this policy task:
+missing generated trade-candidate CSV, absent secondary-tier rows, missing
+AURG/MSFT fixture rows and the 16-row identity fixture versus its historical
+45-row assertion. No new failure was introduced.
+
+## Delivered contract
+
+- `src/etf_cockpit/governance/models.py` contains frozen, extra-forbidden
+  Pydantic policy models, exact lifecycle/authority/severity vocabularies,
+  literal-false execution fields, uniqueness/order checks and contradiction
+  validators.
+- `src/etf_cockpit/governance/product_scope.py` loads all five local policies,
+  records source SHA-256 checksums and returns a diagnostic fail-closed result
+  for missing, malformed or incomplete files. Explicit positive authority
+  requests remain validation errors.
+- `configs/product_governance.yaml` is the canonical product statement and
+  authority boundary; feature, strategy, gate and glossary registries are
+  versioned and include the route/strategy/lifecycle evidence needed by later
+  governance tasks.
+- `evidence/governance/policy_checksums.json` records the five policy paths,
+  SHA-256 values, source checkpoint and `execution_allowed: false` without
+  secrets.
+- Four focused test modules exercise valid loading, checksums, immutability,
+  missing/invalid diagnostic mode, duplicate routes/IDs/orders, lifecycle and
+  authority contradictions and production-route coverage.
+
+## Compatibility and limitations
+
+The loader accepts the repository plan's `features`, `strategies`, `gates` and
+`glossary` YAML collection keys while normalising them to typed `entries`.
+Invalid or absent policies never become supported defaults: they return
+`manual_review`/`not_scoreable`, no research promotion and no portfolio review.
+Legacy action migration, central authority resolution, Decision Journal
+persistence, visible governance pages and package/browser evidence are
+explicitly deferred to Governance Tasks 2-5; they were not silently treated as
+complete here.
+
+## Source checksums at review handoff
+
+| Path | SHA-256 |
+|---|---|
+| `src/etf_cockpit/governance/models.py` | `d2558d4afa42a4379acc98c255b53c5526569f09fac624790fdc5009f37912be` |
+| `src/etf_cockpit/governance/product_scope.py` | `345f4f7c60c637eb521c592fe9659cf586bf735adeba22afc331b6ee7a886f8c` |
+| `tests/test_product_governance.py` | `7b717db7c7902a02a18db76a929cdc6df363ebafdb765ed29b30f17b77fab2d2` |
+| `tests/test_feature_registry.py` | `0898a8f9264105945a5eb8f433ba06288c94c1da9e8bfc89d2c3d2d1d31aa732` |
+| `tests/test_strategy_scope.py` | `de3af7455a57236189aac7cd7c567f005e9328e48fc1870510555af7477044cc` |
+| `tests/test_gate_policy.py` | `002eaa30f22edcff53caa18d0377b6c6cb7f076f8c96140415e8bfa60eb598d7` |
+
+## Review handoff
+
+The branch is ready for a fresh independent review of specification
+compliance and code quality. The reviewer must check the exact lifecycle and
+authority vocabularies, fail-closed behaviour, policy checksums, route
+coverage, no-authority invariant and the stated seven-test baseline.
diff --git a/.ai_worklog/task-governance-1-review.md b/.ai_worklog/task-governance-1-review.md
new file mode 100644
index 0000000..66b6258
--- /dev/null
+++ b/.ai_worklog/task-governance-1-review.md
@@ -0,0 +1,97 @@
+# Wave 1 Governance Task 1 independent review
+
+**Review scope:** `3922afc48fb21ab22465ad890733caa5e0717afc`..`b24a46debf191d13332345b79808691ca35e9150` on `wave1/governance-task1`.
+
+**Reviewed inputs:** `.ai_worklog/task-governance-1-brief.md`, `.ai_worklog/task-governance-1-report.md`, `.ai_worklog/task-governance-1-review-package.md`, `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-governance-plan.md` Task 1, and the approved Group A governance specification (A.4.4/A.4.5 and GOV-01.4-GOV-01.7).
+
+## Verdict
+
+The implementation has a useful immutable/no-execution foundation, but it is not ready for acceptance. A metadata-only or otherwise incomplete policy is reported as a valid policy, several required governance fields/inventory entries are absent, and gate/checksum evidence can be misleading.
+
+`SPECIFICATION: CHANGES_REQUIRED`
+
+`CODE QUALITY: CHANGES_REQUIRED`
+
+## What passed review
+
+- `Lifecycle`, `Authority`, and `GateSeverity` literals contain the required vocabularies in `src/etf_cockpit/governance/models.py:18-35`.
+- Policy models are frozen, assignment-validating and extra-forbidden (`models.py:38-46`). The product, feature, strategy and gate objects carry literal `False` execution fields.
+- The focused command independently passed: `18 passed`.
+- Route coverage is exact for the current router: 22 `PAGES` routes and 22 registry routes, with no missing or extra route.
+- The five manifest SHA-256 values match the current YAML bytes, and the changed deliverables contain no positive execution/credential/upload authority values or secrets.
+- Missing files, parse failures and ordinary malformed payloads return diagnostic `manual_review`/`not_scoreable` results in the exercised paths. Explicit positive `order_transmission` authority is rejected.
+
+## Findings
+
+### Critical
+
+**C1 - incomplete policy files fail open as valid (`product_scope.py:167-203`; `models.py:71-106,151-164,204-214,237-269`).**
+
+`_load_policy()` checks only `schema_version`, `policy_id` and `policy_version`. All substantive model sections have defaults (`ProductGovernancePolicy.product`/`authority`, and empty registry tuples), so a YAML mapping containing only those three headers loads with `diagnostic_mode=False`, `valid=True` and a non-`None` policy for all five loaders. I reproduced this with a temporary metadata-only file: product, feature, strategy, gate and glossary loaders all returned non-diagnostic results (the registries had zero entries). This contradicts A.4.4's fail-closed rule and the implementation report's claim that incomplete policies become diagnostic. An empty gate policy or empty route/strategy registry can let later consumers proceed without the required controls.
+
+Make substantive sections required and validate them before returning a successful result: require the canonical product and authority blocks, non-empty/complete feature and strategy entries, the ordered gate set, and the required glossary terms. Unknown/incomplete schema must return the emergency diagnostic result (`manual_review`, `not_scoreable`, no promotion/review), with regression tests for metadata-only and each missing nested block.
+
+### Important
+
+**I1 - feature registry does not implement the approved registry contract (`configs/feature_registry.yaml:7-28`; `models.py:119-164`).**
+
+The approved GOV-01.5 example requires `name`, `category`, `routes`, `data_dependencies`, `issue_ids`, `tests`, `export_contracts`, and `package_gate` per user-visible subsystem. The new entry model only has a singular `route`, `title`, `required_data`, `tests` and `visible`; issue traceability, export/package gates and the multi-route contract are silently absent. The test only checks `set(PAGES).issubset(...)`, so the 22-route count can pass while required governance metadata is missing. Add the required typed fields (or an explicitly documented compatibility-equivalent), validate each route against the registry, and test all mandatory metadata and title/route consistency.
+
+**I2 - strategy inventory is incomplete and not schema-complete (`configs/strategy_scope.yaml:7-31`; `models.py:167-201`).**
+
+GOV-01.5 requires entries for transparent baseline strategies, TimesFM/Toto/future ML challengers, LLM assistance, provider news/context, paper portfolios, pair/cointegration, triple-barrier research, future broker architecture and all rejected strategies. The file has no experimental strategy at all and omits the TimesFM/Toto/future-ML, paper-portfolio and triple-barrier entries. The model has no explicit `intended_use` or `execution_authority` field (it uses `execution_allowed` instead), and many entries rely on defaults rather than recording each required authority field. Add the required entries and typed fields, make omission of required authority metadata invalid, and add inventory coverage tests.
+
+**I3 - strategy contradiction checks do not cover all authority dimensions (`models.py:187-201`).**
+
+The validator checks score/research/portfolio flags, but it permits positive paper authority on rejected/future-only strategies and permits mismatched combinations such as `StrategyScopeEntry(strategy_id="x", lifecycle="rejected", authority="none", paper_authority=True)` or `authority="none", score_authority=True`. These cases currently construct successfully despite the approved parser rules requiring rejected/future-only scopes to carry no authority and requiring permitted authority to agree with the lifecycle. Reject every positive authority flag for rejected/future-only entries, enforce coherent `authority`/flag combinations, and add adversarial tests for all six lifecycle values (including experimental promotion/weight evidence).
+
+**I4 - gate severity can be configured to grant authority (`models.py:217-234`; `configs/gate_policy.yaml:8-15`).**
+
+Only `blocker` gates reject positive `research_promotion_allowed`/`portfolio_review_allowed`. `authority_warning` and `notice` entries with either flag set validate successfully. The approved semantics are that blockers block, authority warnings downgrade and notices remain visible without increasing authority (plan Task 3, and A.4.2's separation of promotion/review dimensions). A malformed policy can therefore encode a warning/notice that grants authority to a later resolver. Reject positive promotion/review flags for warning/notice entries, or model pass/fail effects explicitly so no severity can increase authority, and test each severity's monotonic behaviour.
+
+**I5 - required glossary coverage is missing (`configs/glossary.yaml:7-18`; `models.py:255-269`).**
+
+GOV-01.7 requires at least evidence authority, freshness, research state, portfolio-review state, blocker/authority-warning/notice, volatility, liquidity/spread proxy, confidence interval/quantile, walk-forward, purging/embargo, model promotion, forecast-error measures, N/A versus zero and source conflict (in addition to alpha/beta/drawdown/calibration/PBO/DSR/MASE/slippage/edge-to-cost). The file contains only 12 terms and omits most of that required set. Add the complete term set with app-specific authority/use definitions and validate required terms in the loader.
+
+**I6 - checksum provenance points at a revision that cannot contain the policies (`evidence/governance/policy_checksums.json:5`).**
+
+The manifest's `source_commit` is the review base `3922afc...`; `git cat-file` confirms all five `configs/*.yaml` policy paths are absent from that revision. The hashes match today's bytes, but the recorded checkpoint cannot prove those bytes came from the named source revision. Record the implementation/head revision (or a real content-addressed tree containing the policies), and add a deterministic provenance test that the named revision contains each path and the recorded digest.
+
+**I7 - policy checksums are not included in audit exports (`configs/audit_manifest.yaml:1-5`; `src/etf_cockpit/chatgpt_bridge/export_pack.py:282-316`).**
+
+A.4.4 requires every governance file's checksum in every run/export that uses it and inclusion in the audit packet. The existing export manifest has no `policy_checksums.json`/governance-policy requirement, and `_write_audit_manifest()` does not add or serialise the governance policy set. Add the policy manifest and policy version/checksums to the required audit entries and export tests; ensure unavailable/invalid governance is represented by the diagnostic marker rather than silently omitted.
+
+### Minor
+
+**M1 - unsupported schema versions are accepted (`models.py:74-76`; `product_scope.py:167-180`).**
+
+`schema_version` is an unconstrained non-empty `str`; a feature policy with `schema_version: "9.9"` loads as valid. Versioned policy loading should reject unknown versions or route them to diagnostic mode, rather than silently accepting a schema future consumers may not understand.
+
+**M2 - contradiction classification relies on error-message substring matching (`product_scope.py:125-145`).**
+
+`_validation_is_explicitly_contradictory()` scans `str(ValidationError)` for broad markers such as `"authority"`. A benign unknown field containing that substring can be re-raised instead of becoming the documented diagnostic result, and behaviour depends on Pydantic wording. Inspect `ValidationError.errors()` locations/types and classify only explicit authority fields; add malformed/unknown-field regression cases.
+
+## Verification evidence
+
+Commands run independently in the review worktree:
+
+```text
+python -m pytest tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py -q
+18 passed
+
+python -m pytest -q
+323 collected; 316 passed; 7 failed
+
+python -m ruff check src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py
+All checks passed
+
+python -m compileall -q src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py
+exit 0
+
+python -m pip check
+No broken requirements found.
+```
+
+The seven full-suite failures are the reported pre-existing generated-data/identity failures: missing `yahoo_trade_candidates_*.csv`, absent secondary-tier rows, missing AURG/MSFT fixture rows and the 16-versus-45 identity fixture assertion. None is in the changed governance files and the focused governance suite passes. The base revision also contains neither the new governance tests nor the new governance modules, supporting the recorded RED collection failure.
+
+No production code or tests were modified during this review; only this review report was added.
diff --git a/configs/audit_manifest.yaml b/configs/audit_manifest.yaml
index 10fa56e..e9e916c 100644
--- a/configs/audit_manifest.yaml
+++ b/configs/audit_manifest.yaml
@@ -4,3 +4,9 @@ required:
   - {path: evidence_export/trust_critical_manifest.json, allow_unavailable: true}
   - {path: configs/data_providers_redacted.json, allow_unavailable: false}
   - {path: project_docs/issues/open.md, allow_unavailable: false}
+  - {path: evidence_export/governance/policy_checksums.json, allow_unavailable: false}
+governance:
+  schema_version: "1.0"
+  policy_checksum_manifest: evidence/governance/policy_checksums.json
+  diagnostic_marker: governance_valid
+  diagnostic_mode: false
diff --git a/configs/feature_registry.yaml b/configs/feature_registry.yaml
new file mode 100644
index 0000000..a91ad73
--- /dev/null
+++ b/configs/feature_registry.yaml
@@ -0,0 +1,28 @@
+schema_version: "1.0"
+policy_id: feature-registry
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+features:
+  - {feature_id: dashboard, name: Simple Scores, title: Simple Scores, category: scoring, route: "/", routes: ["/"], lifecycle: supported, authority: research_state, data_dependencies: [prices, evidence], required_data: [prices, evidence], issue_ids: [ISSUE-0008, ISSUE-0015], tests: [test_simple_scores], export_contracts: [scoreboard, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: portfolio, name: Portfolio Context, title: Portfolio Context, category: portfolio-research, route: "/portfolio", routes: ["/portfolio"], lifecycle: supported, authority: portfolio_review, data_dependencies: [universe, prices], required_data: [universe, prices], issue_ids: [ISSUE-0008, ISSUE-0047], tests: [test_rebalancing], export_contracts: [portfolio_summary, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: signals, name: Scores, title: Scores, category: scoring, route: "/signals", routes: ["/signals"], lifecycle: supported, authority: research_state, data_dependencies: [prices, evidence], required_data: [prices, evidence], issue_ids: [ISSUE-0015], tests: [test_simple_scores], export_contracts: [scoreboard, signal_table], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: risk, name: Risk Evidence, title: Risk Evidence, category: risk, route: "/risk", routes: ["/risk"], lifecycle: supported, authority: evidence_only, data_dependencies: [prices, risk], required_data: [prices, risk], issue_ids: [ISSUE-0030], tests: [test_risk_analytics], export_contracts: [risk_summary, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: etf_detail, name: Instrument Detail, title: Instrument Detail, category: identity, route: "/etf", routes: ["/etf"], lifecycle: supported, authority: evidence_only, data_dependencies: [prices, filings], required_data: [prices, filings], issue_ids: [ISSUE-0008, ISSUE-0052], tests: [test_instrument_detail], export_contracts: [identity_manifest, evidence_ledger], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: backtests, name: Backtests, title: Backtests, category: model-validity, route: "/backtests", routes: ["/backtests"], lifecycle: supported_with_limitations, authority: evidence_only, data_dependencies: [prices, costs], required_data: [prices, costs], issue_ids: [ISSUE-0030], tests: [test_backtest_costs], export_contracts: [backtest_report, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: chatgpt_audit, name: Audit Notes, title: Audit Notes, category: audit, route: "/chatgpt", routes: ["/chatgpt"], lifecycle: supported_with_limitations, authority: context_only, data_dependencies: [evidence], required_data: [evidence], issue_ids: [ISSUE-0010, ISSUE-0060], tests: [test_chatgpt_import], export_contracts: [review_packet, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: providers, name: Provider Status, title: Provider Status, category: providers, route: "/providers", routes: ["/providers"], lifecycle: supported, authority: evidence_only, data_dependencies: [provider_status], required_data: [provider_status], issue_ids: [ISSUE-0043], tests: [test_provider_registry], export_contracts: [provider_manifest, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: evidence, name: Evidence Ledger, title: Evidence Ledger, category: evidence, route: "/evidence", routes: ["/evidence"], lifecycle: supported, authority: evidence_only, data_dependencies: [evidence], required_data: [evidence], issue_ids: [ISSUE-0043], tests: [test_evidence_ledger], export_contracts: [evidence_ledger, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: filings, name: Filings and Statements, title: Filings and Statements, category: evidence, route: "/filings", routes: ["/filings"], lifecycle: supported_with_limitations, authority: evidence_only, data_dependencies: [filings], required_data: [filings], issue_ids: [ISSUE-0043], tests: [test_sec_facts_parser], export_contracts: [filings_statements, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: etf_disclosures, name: ETF Disclosures, title: ETF Disclosures, category: evidence, route: "/etf-disclosures", routes: ["/etf-disclosures"], lifecycle: supported_with_limitations, authority: evidence_only, data_dependencies: [etf_documents], required_data: [etf_documents], issue_ids: [ISSUE-0043], tests: [test_fund_documents], export_contracts: [etf_disclosures, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: news_context, name: News and Context, title: News and Context, category: context, route: "/news-context", routes: ["/news-context"], lifecycle: supported_with_limitations, authority: context_only, data_dependencies: [news], required_data: [news], issue_ids: [ISSUE-0043], tests: [test_news_context], export_contracts: [news_context, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: data_models, name: Data and Models, title: Data and Models, category: data-models, route: "/data-models", routes: ["/data-models"], lifecycle: supported_with_limitations, authority: evidence_only, data_dependencies: [models], required_data: [models], issue_ids: [ISSUE-0015, ISSUE-0030], tests: [test_model_shapes], export_contracts: [model_calibration, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: settings, name: Settings, title: Settings, category: configuration, route: "/settings", routes: ["/settings"], lifecycle: supported, authority: user_record, data_dependencies: [configuration], required_data: [configuration], issue_ids: [ISSUE-0066], tests: [test_release_hardening], export_contracts: [configuration_manifest, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: diagnostics, name: Diagnostics, title: Diagnostics, category: operations, route: "/diagnostics", routes: ["/diagnostics"], lifecycle: supported, authority: evidence_only, data_dependencies: [logs], required_data: [logs], issue_ids: [ISSUE-0030, ISSUE-0043], tests: [test_workflow_runtime], export_contracts: [session_log, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: errors, name: Errors and Recovery, title: Errors and Recovery, category: recovery, route: "/errors", routes: ["/errors"], lifecycle: supported, authority: evidence_only, data_dependencies: [logs, recovery_state], required_data: [logs, recovery_state], issue_ids: [ISSUE-0047], tests: [test_error_recovery], export_contracts: [recovery_manifest, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: data_health, name: Data Health, title: Data Health, category: data-quality, route: "/data-health", routes: ["/data-health"], lifecycle: supported, authority: evidence_only, data_dependencies: [data_health], required_data: [data_health], issue_ids: [ISSUE-0043, ISSUE-0052], tests: [test_data_health], export_contracts: [data_health_report, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: universe, name: Universe, title: Universe, category: identity, route: "/universe", routes: ["/universe"], lifecycle: supported_with_limitations, authority: evidence_only, data_dependencies: [universe, identity], required_data: [universe, identity], issue_ids: [ISSUE-0052, DATA-05], tests: [test_universe_store], export_contracts: [identity_manifest, universe_snapshot], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: onboarding, name: First-run Setup, title: First-run Setup, category: configuration, route: "/onboarding", routes: ["/onboarding"], lifecycle: supported, authority: user_record, data_dependencies: [configuration], required_data: [configuration], issue_ids: [ISSUE-0066], tests: [test_onboarding], export_contracts: [configuration_manifest, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: what_changed, name: What Changed, title: What Changed, category: audit, route: "/what-changed", routes: ["/what-changed"], lifecycle: supported_with_limitations, authority: evidence_only, data_dependencies: [score_history], required_data: [score_history], issue_ids: [ISSUE-0047], tests: [test_run_changes], export_contracts: [score_history, audit_manifest], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: instrument, name: Instrument Detail, title: Instrument Detail, category: identity, route: "/instrument", routes: ["/instrument"], lifecycle: supported, authority: evidence_only, data_dependencies: [prices, evidence], required_data: [prices, evidence], issue_ids: [ISSUE-0052], tests: [test_instrument_detail], export_contracts: [identity_manifest, evidence_ledger], package_gate: source-and-packaged-smoke, visible: true}
+  - {feature_id: import_export, name: Import and Export, title: Import and Export, category: audit, route: "/import-export", routes: ["/import-export"], lifecycle: supported_with_limitations, authority: evidence_only, data_dependencies: [evidence, audit_manifest], required_data: [evidence, audit_manifest], issue_ids: [ISSUE-0010, ISSUE-0060], tests: [test_import_export], export_contracts: [audit_manifest, review_packet], package_gate: source-and-packaged-smoke, visible: true}
diff --git a/configs/gate_policy.yaml b/configs/gate_policy.yaml
new file mode 100644
index 0000000..4cd4727
--- /dev/null
+++ b/configs/gate_policy.yaml
@@ -0,0 +1,15 @@
+schema_version: "1.0"
+policy_id: gate-policy
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+gates:
+  - {gate_id: identity, order: 1, severity: blocker, description: Instrument identity and source identity must be resolved}
+  - {gate_id: data_quality, order: 2, severity: blocker, description: "Data must be present, valid and fresh enough"}
+  - {gate_id: evidence, order: 3, severity: blocker, description: Required evidence must be source-linked and conflict-aware}
+  - {gate_id: model_validity, order: 4, severity: blocker, description: Model and backtest validity must be explicit}
+  - {gate_id: risk, order: 5, severity: blocker, description: Risk limits and unsupported asset controls must pass}
+  - {gate_id: valuation, order: 6, severity: authority_warning, description: Valuation context is advisory and may downgrade confidence}
+  - {gate_id: signal, order: 7, severity: authority_warning, description: Signal confirmation and data quality warnings remain visible}
+  - {gate_id: portfolio_fit, order: 8, severity: authority_warning, description: Portfolio context may require manual review}
+  - {gate_id: cost, order: 9, severity: authority_warning, description: Friction and edge-to-cost context is advisory}
diff --git a/configs/glossary.yaml b/configs/glossary.yaml
new file mode 100644
index 0000000..faab6c5
--- /dev/null
+++ b/configs/glossary.yaml
@@ -0,0 +1,87 @@
+schema_version: "1.0"
+policy_id: governance-glossary
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+glossary:
+  - term: alpha
+    definition: "Return relative to a selected benchmark over a stated period"
+    authority_note: "Context only; it does not bypass gates"
+  - term: beta
+    definition: "Sensitivity of returns to a benchmark"
+    authority_note: "Context only"
+  - term: drawdown
+    definition: "Decline from a prior peak in a value series"
+    authority_note: "Risk evidence"
+  - term: calibration
+    definition: "Agreement between predicted probabilities and observed outcomes"
+    authority_note: "Model-validity evidence"
+  - term: pbo
+    definition: "Probability of backtest overfitting"
+    authority_note: "Model-validity evidence"
+  - term: dsr
+    definition: "Deflated Sharpe ratio adjusted for multiple testing and non-normality"
+    authority_note: "Model-validity evidence"
+  - term: mase
+    definition: "Mean absolute scaled error for forecast evaluation"
+    authority_note: "Forecast context"
+  - term: slippage
+    definition: "Difference between an assumed decision price and an observed fill proxy"
+    authority_note: "Cost context only"
+  - term: edge-to-cost
+    definition: "Estimated gross edge divided by estimated friction"
+    authority_note: "Cost gate context"
+  - term: evidence authority
+    definition: "The authority granted to source-linked evidence"
+    authority_note: "Evidence never becomes an executable order"
+  - term: freshness
+    definition: "How recently a source was retrieved relative to the required observation date"
+    authority_note: "Stale evidence can block promotion"
+  - term: research state
+    definition: "A state describing whether evidence is eligible for research use"
+    authority_note: "Research state is not execution authority"
+  - term: portfolio-review state
+    definition: "A human-reviewed state for portfolio context"
+    authority_note: "User decision remains authoritative"
+  - term: blocker
+    definition: "A failed gate that prevents the next authority transition"
+    authority_note: "Blockers fail closed"
+  - term: authority-warning
+    definition: "A visible warning that may require manual review"
+    authority_note: "Warnings never grant authority"
+  - term: notice
+    definition: "A non-blocking informational gate result"
+    authority_note: "Notices never grant authority"
+  - term: volatility
+    definition: "Dispersion of returns over a stated observation window"
+    authority_note: "Risk context"
+  - term: liquidity/spread proxy
+    definition: "A documented proxy for trading liquidity and spread friction"
+    authority_note: "Cost and risk context"
+  - term: confidence interval/quantile
+    definition: "An uncertainty interval or distribution quantile around an estimate"
+    authority_note: "Uncertainty must remain visible"
+  - term: walk-forward
+    definition: "Time-ordered train and evaluation procedure"
+    authority_note: "Required for credible model evidence"
+  - term: purging/embargo
+    definition: "Separation controls preventing label leakage across validation folds"
+    authority_note: "Required where labels overlap"
+  - term: model promotion
+    definition: "The controlled transition of a model from research to a permitted state"
+    authority_note: "Promotion requires all applicable gates"
+  - term: forecast-error measures
+    definition: "Metrics used to evaluate forecast errors"
+    authority_note: "Forecast metrics do not create score authority"
+  - term: n/a versus zero
+    definition: "N/A denotes unavailable or inapplicable data whereas zero is an observed numeric value"
+    authority_note: "They must not be conflated"
+  - term: source conflict
+    definition: "A disagreement between source observations for the same fact"
+    authority_note: "Conflicts remain visible and can block authority"
+  - term: manual_review
+    definition: "A human must inspect evidence before any research promotion or portfolio review"
+    authority_note: "Non-executable state"
+  - term: not_scoreable
+    definition: "Required evidence or policy is unavailable, so no score is authoritative"
+    authority_note: "Fail-closed state"
diff --git a/configs/product_governance.yaml b/configs/product_governance.yaml
new file mode 100644
index 0000000..6d91692
--- /dev/null
+++ b/configs/product_governance.yaml
@@ -0,0 +1,33 @@
+schema_version: "1.0"
+policy_id: product-governance
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+product:
+  canonical_name: "ETF AI Cockpit"
+  category: "local investment evidence and portfolio-research cockpit"
+  intended_user: "human private investor"
+  default_horizon: "long_horizon"
+  decision_owner: "user"
+authority:
+  maximum_operational_authority: "manual_research"
+  broker_execution: "forbidden"
+  execution_allowed: false
+  executable_authority: false
+  order_transmission: false
+  external_upload: false
+  credential_access: false
+  autonomous_portfolio_management: false
+  unvalidated_ai_score_authority: false
+default_research_state: research_candidate
+default_portfolio_review_state: not_applicable
+prohibited_claims:
+  - "guaranteed return"
+  - "autonomous financial adviser"
+  - "AI trading bot"
+  - "proven alpha"
+  - "broker execution enabled"
+required_disclosures:
+  - "Outputs are research evidence, not executable orders."
+  - "The user owns the final decision."
+  - "Unavailable or weak evidence can restrict authority."
diff --git a/configs/strategy_scope.yaml b/configs/strategy_scope.yaml
new file mode 100644
index 0000000..96655f7
--- /dev/null
+++ b/configs/strategy_scope.yaml
@@ -0,0 +1,33 @@
+schema_version: "1.0"
+policy_id: strategy-scope
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+strategies:
+  - {strategy_id: baseline_simple_scores, name: Baseline simple scores, lifecycle: supported, asset_scope: mixed, authority: research_state, permitted_authority: research_state, execution_authority: none, intended_use: Deterministic evidence-backed ranking for research state, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: false, paper_authority: false, required_data: [daily_prices, evidence], limitations: [Not an executable signal, requires current evidence], linked_issues: [ISSUE-0008, ISSUE-0015], promotion_conditions: [identity and data-quality gates pass], tests: [test_simple_scores]}
+  - {strategy_id: etf_trend_momentum, name: ETF trend and momentum, lifecycle: supported, asset_scope: etf, authority: portfolio_review, permitted_authority: portfolio_review, execution_authority: none, intended_use: Research ranking for long-horizon ETF review, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, paper_authority: false, required_data: [daily_prices, adjusted_returns], limitations: [Long-only research context, no order transmission], linked_issues: [ISSUE-0008, ISSUE-0015], promotion_conditions: [evidence and risk gates pass, user reviews output], tests: [test_simple_scores, test_rebalancing]}
+  - {strategy_id: defensive_rotation, name: Defensive rotation and watchlist, lifecycle: supported, asset_scope: etf, authority: portfolio_review, permitted_authority: portfolio_review, execution_authority: none, intended_use: Compare defensive ETF research candidates, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, paper_authority: false, required_data: [daily_prices, risk_metrics], limitations: [No autonomous rebalancing], linked_issues: [ISSUE-0047], promotion_conditions: [risk and data-quality gates pass], tests: [test_rebalancing]}
+  - {strategy_id: stock_quality_momentum, name: Stock quality and momentum, lifecycle: supported, asset_scope: stock, authority: portfolio_review, permitted_authority: portfolio_review, execution_authority: none, intended_use: Research comparison of equity candidates, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, paper_authority: false, required_data: [daily_prices, fundamentals], limitations: [Coverage depends on verified issuer evidence], linked_issues: [DATA-05], promotion_conditions: [identity and evidence gates pass], tests: [test_fundamentals]}
+  - {strategy_id: stock_value_momentum, name: Stock value and momentum, lifecycle: supported, asset_scope: stock, authority: portfolio_review, permitted_authority: portfolio_review, execution_authority: none, intended_use: Research comparison of equity candidates, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, paper_authority: false, required_data: [daily_prices, fundamentals], limitations: [Coverage depends on verified issuer evidence], linked_issues: [DATA-05], promotion_conditions: [identity and evidence gates pass], tests: [test_fundamentals]}
+  - {strategy_id: long_only_ranking, name: Long-only ranking, lifecycle: supported, asset_scope: mixed, authority: research_state, permitted_authority: research_state, execution_authority: none, intended_use: Rank evidence-backed research candidates, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: false, paper_authority: false, required_data: [evidence, scores], limitations: [Ranking is not a trade instruction], linked_issues: [ISSUE-0015], promotion_conditions: [required gates pass], tests: [test_simple_scores]}
+  - {strategy_id: timesfm_challenger, name: TimesFM challenger, lifecycle: experimental, asset_scope: mixed, authority: none, permitted_authority: none, execution_authority: none, intended_use: Compare forecast research against the deterministic baseline, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [daily_prices, forecast_errors], limitations: [Experimental model with no product authority], linked_issues: [ISSUE-0015], promotion_conditions: [fresh benchmark, walk-forward and model-validity evidence], tests: [test_model_shapes]}
+  - {strategy_id: toto_challenger, name: Toto challenger, lifecycle: experimental, asset_scope: mixed, authority: none, permitted_authority: none, execution_authority: none, intended_use: Compare forecast research against the deterministic baseline, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [daily_prices, forecast_errors], limitations: [Experimental model with no product authority], linked_issues: [ISSUE-0015], promotion_conditions: [fresh benchmark, walk-forward and model-validity evidence], tests: [test_model_shapes]}
+  - {strategy_id: future_ml_challenger, name: Future ML challenger, lifecycle: future_only, asset_scope: mixed, authority: none, permitted_authority: none, execution_authority: none, intended_use: Reserved for a separately approved future model programme, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [daily_prices, labelled_outcomes], limitations: [Not implemented or scoreable in this release], linked_issues: [ISSUE-0015], promotion_conditions: [separate approval and promotion evidence], tests: [test_model_shapes]}
+  - {strategy_id: llm_assistance, name: LLM assistance, lifecycle: supported_with_limitations, asset_scope: general, authority: context_only, permitted_authority: context_only, execution_authority: none, intended_use: Summarise evidence and surface questions for a human reviewer, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [evidence, prompt_trace], limitations: [Non-authoritative context; no score or order control], linked_issues: [ISSUE-0010, ISSUE-0060], promotion_conditions: [source-linked context and audit trace], tests: [test_local_llm_audit]}
+  - {strategy_id: provider_news_context, name: Provider news context, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, permitted_authority: context_only, execution_authority: none, intended_use: Present source-linked provider news as context, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [news, provider_status], limitations: [Conflicting or stale sources remain visible], linked_issues: [ISSUE-0043], promotion_conditions: [provider and freshness evidence], tests: [test_news_context]}
+  - {strategy_id: paper_portfolio, name: Paper portfolio research, lifecycle: research_only, asset_scope: mixed, authority: none, permitted_authority: none, execution_authority: none, intended_use: Simulate portfolio decisions without broker or order authority, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: true, required_data: [prices, costs, portfolio_snapshot], limitations: [Simulation only; no external execution or upload], linked_issues: [ISSUE-0047], promotion_conditions: [reproducible snapshot, costs and audit manifest], tests: [test_rebalancing]}
+  - {strategy_id: pair_trading, name: Pair trading research, lifecycle: research_only, asset_scope: stock, authority: none, permitted_authority: none, execution_authority: none, intended_use: Explore pair relationships as non-authoritative research, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [daily_prices, cointegration], limitations: [Research-only and outside baseline score authority], linked_issues: [ISSUE-0030], promotion_conditions: [independent validation and user review], tests: [test_asset_guardrails]}
+  - {strategy_id: triple_barrier_research, name: Triple-barrier research, lifecycle: research_only, asset_scope: mixed, authority: none, permitted_authority: none, execution_authority: none, intended_use: Evaluate labelled research outcomes without promotion authority, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [daily_prices, labelled_outcomes], limitations: [Research-only and requires purging and embargo], linked_issues: [ISSUE-0030], promotion_conditions: [walk-forward, purging and embargo evidence], tests: [test_backtest_costs]}
+  - {strategy_id: manual_review, name: Manual review, lifecycle: supported_with_limitations, asset_scope: general, authority: context_only, permitted_authority: context_only, execution_authority: none, intended_use: Record a human review state and decision, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [evidence], limitations: [Requires an identified user decision], linked_issues: [ISSUE-0047], promotion_conditions: [evidence packet is available], tests: [test_trade_proposals]}
+  - {strategy_id: news_sentiment, name: News and sentiment context, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, permitted_authority: context_only, execution_authority: none, intended_use: Display sentiment as context only, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [news], limitations: [Sentiment cannot directly alter score authority], linked_issues: [ISSUE-0043], promotion_conditions: [source and freshness evidence], tests: [test_news_context]}
+  - {strategy_id: llm_summaries, name: LLM summaries, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, permitted_authority: context_only, execution_authority: none, intended_use: Summarise source-linked research notes, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [evidence], limitations: [Context only and fully auditable], linked_issues: [ISSUE-0010], promotion_conditions: [prompt and source trace retained], tests: [test_local_llm_audit]}
+  - {strategy_id: macro_notes, name: Macro notes, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, permitted_authority: context_only, execution_authority: none, intended_use: Present macro context for human review, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [macro], limitations: [Not a score input without approved evidence mapping], linked_issues: [ISSUE-0043], promotion_conditions: [source-linked note], tests: [test_news_context]}
+  - {strategy_id: manual_notes, name: Manual notes, lifecycle: supported_with_limitations, asset_scope: general, authority: user_record, permitted_authority: user_record, execution_authority: none, intended_use: Store user-authored research context, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [user_notes], limitations: [User record is not provider evidence], linked_issues: [ISSUE-0066], promotion_conditions: [user identity and timestamp retained], tests: [test_chatgpt_import]}
+  - {strategy_id: future_broker_architecture, name: Future broker architecture, lifecycle: future_only, asset_scope: general, authority: none, permitted_authority: none, execution_authority: none, intended_use: Reserve an interface boundary for a separately approved future programme, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [future_contracts], limitations: [No broker integration, credentials or order transmission], linked_issues: [ISSUE-0047], promotion_conditions: [separate approval and security review], tests: [test_release_hardening]}
+  - {strategy_id: martingale, name: Martingale, lifecycle: rejected, asset_scope: general, authority: none, permitted_authority: none, execution_authority: none, intended_use: Rejected strategy record for scope transparency, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [none], limitations: [Unbounded loss and no approved evidence basis], linked_issues: [ISSUE-0030], promotion_conditions: [Not eligible for promotion], tests: [test_asset_guardrails], rejection_reason: Unbounded loss and no approved evidence basis}
+  - {strategy_id: grid, name: Grid, lifecycle: rejected, asset_scope: general, authority: none, permitted_authority: none, execution_authority: none, intended_use: Rejected strategy record for scope transparency, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [none], limitations: [Unsupported execution and risk assumptions], linked_issues: [ISSUE-0030], promotion_conditions: [Not eligible for promotion], tests: [test_asset_guardrails], rejection_reason: Unsupported execution and risk assumptions}
+  - {strategy_id: rl_agents, name: Reinforcement-learning agents, lifecycle: rejected, asset_scope: general, authority: none, permitted_authority: none, execution_authority: none, intended_use: Rejected strategy record for scope transparency, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [none], limitations: [No approved autonomous authority], linked_issues: [ISSUE-0030], promotion_conditions: [Not eligible for promotion], tests: [test_asset_guardrails], rejection_reason: No approved autonomous authority}
+  - {strategy_id: llm_only_management, name: LLM-only management, lifecycle: rejected, asset_scope: general, authority: none, permitted_authority: none, execution_authority: none, intended_use: Rejected strategy record for scope transparency, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [none], limitations: [LLM output is non-authoritative context], linked_issues: [ISSUE-0010], promotion_conditions: [Not eligible for promotion], tests: [test_local_llm_audit], rejection_reason: LLM output is non-authoritative context}
+  - {strategy_id: model_only_trading, name: Model-only trading, lifecycle: rejected, asset_scope: general, authority: none, permitted_authority: none, execution_authority: none, intended_use: Rejected strategy record for scope transparency, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [none], limitations: [Model output cannot replace evidence and gates], linked_issues: [ISSUE-0015], promotion_conditions: [Not eligible for promotion], tests: [test_model_shapes], rejection_reason: Model output cannot replace evidence and gates}
+  - {strategy_id: return_screenshots, name: Return screenshots as evidence, lifecycle: rejected, asset_scope: general, authority: none, permitted_authority: none, execution_authority: none, intended_use: Rejected evidence shortcut record for scope transparency, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [none], limitations: [Screenshots are not reproducible evidence], linked_issues: [ISSUE-0043], promotion_conditions: [Not eligible for promotion], tests: [test_data_contracts], rejection_reason: Screenshots are not reproducible evidence}
+  - {strategy_id: unvalidated_sentiment, name: Unvalidated sentiment, lifecycle: rejected, asset_scope: mixed, authority: none, permitted_authority: none, execution_authority: none, intended_use: Rejected strategy record for scope transparency, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: false, required_data: [none], limitations: [Sentiment cannot directly alter score authority], linked_issues: [ISSUE-0043], promotion_conditions: [Not eligible for promotion], tests: [test_news_context], rejection_reason: Sentiment cannot directly alter score authority}
diff --git a/evidence/governance/policy_checksums.json b/evidence/governance/policy_checksums.json
new file mode 100644
index 0000000..86545f5
--- /dev/null
+++ b/evidence/governance/policy_checksums.json
@@ -0,0 +1,28 @@
+{
+  "schema_version": "1.0",
+  "generated_at_utc": "2026-07-12T01:11:39Z",
+  "source_commit": "31448c3f96781a7a8c66ba1dc69a3f40577be1b0",
+  "execution_allowed": false,
+  "policies": {
+    "product_governance": {
+      "path": "configs/product_governance.yaml",
+      "sha256": "2b904e26fe3f23dc2179b73d1a525b060587ba76535b4fd344dc295cbf7e4f22"
+    },
+    "feature_registry": {
+      "path": "configs/feature_registry.yaml",
+      "sha256": "df832b1d53a5524a5c47dc48f6beb9dd5fc21f8a924cf02468d92be9bbc0bd2c"
+    },
+    "strategy_scope": {
+      "path": "configs/strategy_scope.yaml",
+      "sha256": "14c58c3d28a0f6ee08429caa45f64b75410534068e8ef1c536653f989f9ed174"
+    },
+    "gate_policy": {
+      "path": "configs/gate_policy.yaml",
+      "sha256": "08417a30155b2e42b540d125f1c12d719a1bec2ac99c703ed5d969d17f619adc"
+    },
+    "glossary": {
+      "path": "configs/glossary.yaml",
+      "sha256": "d8738c75a0d3e95df69528f53f80b42e71828880eb471ef434f9f398652a41ce"
+    }
+  }
+}
diff --git a/src/etf_cockpit/chatgpt_bridge/export_pack.py b/src/etf_cockpit/chatgpt_bridge/export_pack.py
index 8017e53..b08ca2c 100644
--- a/src/etf_cockpit/chatgpt_bridge/export_pack.py
+++ b/src/etf_cockpit/chatgpt_bridge/export_pack.py
@@ -35,12 +35,20 @@ from etf_cockpit.data.trust_artifacts import (
     SCORE_METRIC_HISTORY_PATH,
     SOURCE_CONFLICTS_PATH,
 )
+from etf_cockpit.governance.product_scope import (
+    load_feature_registry,
+    load_gate_policy,
+    load_glossary,
+    load_product_governance,
+    load_strategy_scope,
+)
 from etf_cockpit.portfolio.allocation import allocation_frame
 
 
 # Backwards-compatible name for older scripts/tests; new exports default to data/audit_packets.
 CHATGPT_EXPORTS_DIR = AUDIT_PACKETS_DIR
 CANDLE_CONTEXT_PATH = DERIVED_DIR / "candle_context.parquet"
+GOVERNANCE_CHECKSUMS_PATH = ROOT / "evidence" / "governance" / "policy_checksums.json"
 
 SIGNAL_TABLE_COLUMNS = [
     "etf_id",
@@ -280,6 +288,41 @@ def export_review_pack(
 
 
 def _write_audit_manifest(export_dir: Path, derived_manifest: dict[str, object], evidence_manifest: dict[str, object]) -> None:
+    governance_path = export_dir / "evidence_export" / "governance" / "policy_checksums.json"
+    governance_path.parent.mkdir(parents=True, exist_ok=True)
+    governance_payload: dict[str, object] = {}
+    diagnostic_mode = False
+    try:
+        governance_payload = json.loads(GOVERNANCE_CHECKSUMS_PATH.read_text(encoding="utf-8"))
+    except (OSError, ValueError):
+        diagnostic_mode = True
+
+    policy_loaders = {
+        "product_governance": load_product_governance,
+        "feature_registry": load_feature_registry,
+        "strategy_scope": load_strategy_scope,
+        "gate_policy": load_gate_policy,
+        "glossary": load_glossary,
+    }
+    policy_checksums: dict[str, str] = {}
+    for policy_name, loader in policy_loaders.items():
+        result = loader()
+        diagnostic_mode = diagnostic_mode or result.diagnostic_mode or result.policy is None
+        if result.checksum != "unavailable":
+            policy_checksums[policy_name] = result.checksum
+    manifest_records = governance_payload.get("policies")
+    if isinstance(manifest_records, dict):
+        for policy_name, record in manifest_records.items():
+            if isinstance(record, dict) and isinstance(record.get("sha256"), str):
+                policy_checksums.setdefault(policy_name, record["sha256"])
+    if len(policy_checksums) != 5:
+        diagnostic_mode = True
+    governance_payload.setdefault("schema_version", "1.0")
+    governance_payload["diagnostic_mode"] = diagnostic_mode
+    governance_payload["diagnostic_marker"] = "governance_diagnostic" if diagnostic_mode else "governance_valid"
+    governance_payload["policy_checksums"] = policy_checksums
+    governance_path.write_text(json.dumps(governance_payload, indent=2, sort_keys=True), encoding="utf-8")
+
     required = [
         {
             "path": "evidence_export/session.jsonl",
@@ -304,6 +347,7 @@ def _write_audit_manifest(export_dir: Path, derived_manifest: dict[str, object],
             "unavailable_marker": "evidence_export/source_conflicts_unavailable.txt",
         },
         {"path": "01_portfolio_summary.json", "allow_unavailable": False},
+        {"path": "evidence_export/governance/policy_checksums.json", "allow_unavailable": False},
     ]
     checksums: dict[str, str] = {}
     for path in export_dir.rglob("*"):
@@ -311,7 +355,23 @@ def _write_audit_manifest(export_dir: Path, derived_manifest: dict[str, object],
             digest = hashlib.sha256(path.read_bytes()).hexdigest()
             checksums[str(path.relative_to(export_dir)).replace("\\", "/")] = digest
     (export_dir / "audit_manifest.json").write_text(
-        json.dumps({"schema_version": 1, "required": required, "checksums": checksums, "derived": derived_manifest, "evidence": evidence_manifest}, indent=2, sort_keys=True),
+        json.dumps(
+            {
+                "schema_version": 1,
+                "required": required,
+                "checksums": checksums,
+                "derived": derived_manifest,
+                "evidence": evidence_manifest,
+                "governance": {
+                    "schema_version": str(governance_payload.get("schema_version", "1.0")),
+                    "diagnostic_mode": diagnostic_mode,
+                    "diagnostic_marker": governance_payload["diagnostic_marker"],
+                    "policy_checksums": policy_checksums,
+                },
+            },
+            indent=2,
+            sort_keys=True,
+        ),
         encoding="utf-8",
     )
 
diff --git a/src/etf_cockpit/governance/models.py b/src/etf_cockpit/governance/models.py
new file mode 100644
index 0000000..e385a0d
--- /dev/null
+++ b/src/etf_cockpit/governance/models.py
@@ -0,0 +1,431 @@
+"""Immutable, checksum-bearing governance policy contracts.
+
+The governance files are deliberately represented by small, strict Pydantic
+models.  A policy can describe advisory research and review authority, but the
+execution boundary is encoded as ``Literal[False]`` in every model so a YAML
+value cannot opt the application into an executable mode.
+"""
+
+from __future__ import annotations
+
+from typing import Generic, Literal, TypeVar
+
+from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator
+
+
+SCHEMA_VERSION = "1.0"
+SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})
+Checksum = str
+Lifecycle = Literal[
+    "supported",
+    "supported_with_limitations",
+    "experimental",
+    "research_only",
+    "future_only",
+    "rejected",
+]
+Authority = Literal[
+    "evidence_only",
+    "context_only",
+    "research_state",
+    "portfolio_review",
+    "user_record",
+    "none",
+]
+ResearchState = Literal["research_candidate", "manual_review", "not_scoreable"]
+GateSeverity = Literal["blocker", "authority_warning", "notice"]
+
+# These are the policy terms and gate identifiers required by GOV-01.4-GOV-01.7.
+# Keeping the lists in the typed contract makes completeness checks deterministic
+# and gives loaders a single source of truth.
+REQUIRED_GATE_IDS = (
+    "identity",
+    "data_quality",
+    "evidence",
+    "model_validity",
+    "risk",
+    "valuation",
+    "signal",
+    "portfolio_fit",
+    "cost",
+)
+REQUIRED_GLOSSARY_TERMS = frozenset(
+    {
+        "alpha",
+        "beta",
+        "drawdown",
+        "calibration",
+        "pbo",
+        "dsr",
+        "mase",
+        "slippage",
+        "edge-to-cost",
+        "evidence authority",
+        "freshness",
+        "research state",
+        "portfolio-review state",
+        "blocker",
+        "authority-warning",
+        "notice",
+        "volatility",
+        "liquidity/spread proxy",
+        "confidence interval/quantile",
+        "walk-forward",
+        "purging/embargo",
+        "model promotion",
+        "forecast-error measures",
+        "n/a versus zero",
+        "source conflict",
+    }
+)
+
+
+class ImmutableModel(BaseModel):
+    """Base contract for policy data loaded from local YAML."""
+
+    model_config = ConfigDict(
+        extra="forbid",
+        frozen=True,
+        str_strip_whitespace=True,
+        validate_assignment=True,
+    )
+
+
+class AuthorityPolicy(ImmutableModel):
+    """The non-executable authority boundary shared by governance policies."""
+
+    execution_allowed: Literal[False] = False
+    executable_authority: Literal[False] = False
+    order_transmission: Literal[False] = False
+    external_upload: Literal[False] = False
+    credential_access: Literal[False] = False
+    maximum_operational_authority: Literal["manual_research"] = "manual_research"
+    broker_execution: Literal["forbidden"] = "forbidden"
+    autonomous_portfolio_management: Literal[False] = False
+    unvalidated_ai_score_authority: Literal[False] = False
+
+
+class ProductDefinition(ImmutableModel):
+    canonical_name: str = Field(min_length=1)
+    category: str = Field(min_length=1)
+    intended_user: str = Field(min_length=1)
+    default_horizon: str = Field(min_length=1)
+    decision_owner: Literal["user"] = "user"
+
+
+class PolicyModel(ImmutableModel):
+    """Common metadata and immutable execution boundary for a policy."""
+
+    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
+    policy_id: str = Field(min_length=1)
+    policy_version: str = Field(min_length=1)
+    execution_allowed: Literal[False] = False
+    executable_authority: Literal[False] = False
+    checksum: str = "unavailable"
+
+    @field_validator("checksum")
+    @classmethod
+    def validate_checksum(cls, value: str) -> str:
+        if value == "unavailable":
+            return value
+        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
+            raise ValueError("checksum must be a SHA-256 hexadecimal digest")
+        return value.lower()
+
+
+class ProductGovernancePolicy(PolicyModel):
+    """Top-level product authority and fail-closed defaults."""
+
+    product: ProductDefinition
+    authority: AuthorityPolicy
+    prohibited_claims: tuple[str, ...] = ()
+    required_disclosures: tuple[str, ...] = ()
+    default_research_state: str = "research_candidate"
+    default_portfolio_review_state: str = "not_applicable"
+
+    @model_validator(mode="after")
+    def validate_authority_boundary(self) -> ProductGovernancePolicy:
+        for field_name in (
+            "execution_allowed",
+            "executable_authority",
+        ):
+            if getattr(self, field_name) is not False or getattr(self.authority, field_name) is not False:
+                raise ValueError(f"{field_name} must remain false")
+        return self
+
+
+class FeatureRegistryEntry(ImmutableModel):
+    """One user-visible feature or production route."""
+
+    feature_id: str = Field(default="unnamed", min_length=1)
+    # ``route``/``required_data``/``title`` are retained as typed compatibility
+    # aliases for the first Task 1 implementation. New policy files use the
+    # plural/more explicit contract fields below.
+    route: str = ""
+    routes: tuple[str, ...] = ()
+    name: str = ""
+    category: str = ""
+    title: str = ""
+    lifecycle: Lifecycle = "supported"
+    authority: Authority = "none"
+    data_dependencies: tuple[str, ...] = ()
+    required_data: tuple[str, ...] = ()
+    issue_ids: tuple[str, ...] = ()
+    tests: tuple[str, ...] = ()
+    export_contracts: tuple[str, ...] = ()
+    package_gate: str = ""
+    visible: bool = True
+    score_authority: bool = False
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+
+    @field_validator("route")
+    @classmethod
+    def validate_route(cls, value: str) -> str:
+        if value and not value.startswith("/"):
+            raise ValueError("route must start with '/'")
+        return value
+
+    @field_validator("routes")
+    @classmethod
+    def validate_routes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
+        if any(not route.startswith("/") for route in value):
+            raise ValueError("routes must start with '/'")
+        return value
+
+    @property
+    def canonical_routes(self) -> tuple[str, ...]:
+        """Return routes using the plural contract with legacy fallback."""
+
+        return self.routes or ((self.route,) if self.route else ())
+
+    @model_validator(mode="after")
+    def validate_lifecycle_authority(self) -> FeatureRegistryEntry:
+        if self.lifecycle in {"experimental", "research_only", "future_only", "rejected"} and (
+            self.score_authority or self.research_promotion_allowed or self.portfolio_review_allowed
+        ):
+            raise ValueError("lifecycle does not permit positive authority")
+        if self.authority == "none" and (
+            self.score_authority or self.research_promotion_allowed or self.portfolio_review_allowed
+        ):
+            raise ValueError("authority 'none' cannot carry positive authority flags")
+        if self.portfolio_review_allowed and self.authority != "portfolio_review":
+            raise ValueError("portfolio_review authority is required for portfolio_review_allowed")
+        if (self.score_authority or self.research_promotion_allowed) and self.authority not in {
+            "research_state",
+            "portfolio_review",
+        }:
+            raise ValueError("research_state or portfolio_review authority is required for score/promotion flags")
+        if self.route and self.routes and self.route not in self.routes:
+            raise ValueError("route must be present in routes")
+        return self
+
+
+class FeatureRegistryPolicy(PolicyModel):
+    """Registry of routes and visible product subsystems."""
+
+    entries: tuple[FeatureRegistryEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_features_and_routes(self) -> FeatureRegistryPolicy:
+        feature_ids = [entry.feature_id for entry in self.entries]
+        routes = [route for entry in self.entries for route in entry.canonical_routes]
+        if len(feature_ids) != len(set(feature_ids)):
+            raise ValueError("feature_id values must be unique")
+        if len(routes) != len(set(routes)):
+            raise ValueError("route values must be unique")
+        return self
+
+
+class StrategyScopeEntry(ImmutableModel):
+    """Strategy lifecycle and the authority that strategy may contribute."""
+
+    strategy_id: str = Field(default="unnamed", min_length=1)
+    name: str = ""
+    lifecycle: Lifecycle = "supported"
+    asset_scope: Literal["etf", "stock", "mixed", "general"] = "general"
+    authority: Authority = "none"
+    intended_use: str = ""
+    permitted_authority: Authority | None = None
+    execution_authority: Literal["none"] = "none"
+    score_authority: bool = False
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    paper_authority: bool = False
+    required_data: tuple[str, ...] = ()
+    limitations: tuple[str, ...] = ()
+    linked_issues: tuple[str, ...] = ()
+    promotion_conditions: tuple[str, ...] = ()
+    rejection_reason: str = ""
+    tests: tuple[str, ...] = ()
+    execution_allowed: Literal[False] = False
+
+    @model_validator(mode="after")
+    def validate_strategy_authority(self) -> StrategyScopeEntry:
+        if self.permitted_authority is not None and self.authority != "none" and self.authority != self.permitted_authority:
+            raise ValueError("authority and permitted_authority must agree")
+        effective_authority = self.permitted_authority or self.authority
+        if self.lifecycle in {"rejected", "future_only"}:
+            lifecycle_label = "rejected" if self.lifecycle == "rejected" else "future-only"
+            if self.paper_authority:
+                raise ValueError(f"{lifecycle_label} strategies cannot have paper_authority")
+            if self.score_authority:
+                detail = "score_authority or authority" if self.lifecycle == "rejected" else "score_authority"
+                raise ValueError(f"{lifecycle_label} strategies cannot have {detail}")
+            if self.research_promotion_allowed:
+                detail = "research_promotion_allowed or authority" if self.lifecycle == "rejected" else "research_promotion_allowed"
+                raise ValueError(f"{lifecycle_label} strategies cannot have {detail}")
+            if self.portfolio_review_allowed:
+                detail = "portfolio_review_allowed or authority" if self.lifecycle == "rejected" else "portfolio_review_allowed"
+                raise ValueError(f"{lifecycle_label} strategies cannot have {detail}")
+            if effective_authority != "none":
+                raise ValueError(f"{lifecycle_label} strategies cannot have authority")
+        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.score_authority:
+            raise ValueError("score_authority is not permitted for this lifecycle")
+        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.research_promotion_allowed:
+            raise ValueError("research_promotion_allowed is not permitted for this lifecycle")
+        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.portfolio_review_allowed:
+            raise ValueError("portfolio_review_allowed is not permitted for this lifecycle")
+        if self.authority == "none" and self.permitted_authority not in {None, "none"}:
+            raise ValueError("authority 'none' cannot disagree with permitted_authority")
+        if self.portfolio_review_allowed and effective_authority != "portfolio_review":
+            raise ValueError("portfolio_review authority is required for portfolio_review_allowed")
+        if (self.score_authority or self.research_promotion_allowed) and effective_authority not in {
+            "research_state",
+            "portfolio_review",
+        }:
+            raise ValueError("research_state or portfolio_review authority is required for score/promotion flags")
+        if self.execution_authority != "none":
+            raise ValueError("execution_authority must remain none")
+        return self
+
+
+class StrategyScopePolicy(PolicyModel):
+    """Supported, context-only, research-only and rejected strategy families."""
+
+    entries: tuple[StrategyScopeEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_strategies(self) -> StrategyScopePolicy:
+        identifiers = [entry.strategy_id for entry in self.entries]
+        if len(identifiers) != len(set(identifiers)):
+            raise ValueError("strategy_id values must be unique")
+        return self
+
+
+class GatePolicyEntry(ImmutableModel):
+    """One ordered gate in the authority ladder."""
+
+    gate_id: str = Field(min_length=1)
+    order: PositiveInt = 1
+    severity: GateSeverity = "notice"
+    description: str = ""
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+
+    @model_validator(mode="after")
+    def validate_gate_authority(self) -> GatePolicyEntry:
+        if self.severity in {"blocker", "authority_warning", "notice"} and (
+            self.research_promotion_allowed or self.portfolio_review_allowed
+        ):
+            raise ValueError("gate severity cannot allow research_promotion_allowed or portfolio_review_allowed")
+        return self
+
+
+class GatePolicy(PolicyModel):
+    """Ordered, monotonic gate policy."""
+
+    gates: tuple[GatePolicyEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_gate_order(self) -> GatePolicy:
+        identifiers = [gate.gate_id for gate in self.gates]
+        orders = [gate.order for gate in self.gates]
+        if len(identifiers) != len(set(identifiers)):
+            raise ValueError("gate_id values must be unique")
+        if len(orders) != len(set(orders)):
+            raise ValueError("order values must be unique")
+        if orders and orders != sorted(orders):
+            raise ValueError("gates must be ordered by order")
+        return self
+
+
+class GlossaryEntry(ImmutableModel):
+    term: str = Field(min_length=1)
+    definition: str = Field(min_length=1)
+    authority_note: str = ""
+
+
+class GlossaryPolicy(PolicyModel):
+    entries: tuple[GlossaryEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_terms(self) -> GlossaryPolicy:
+        terms = [entry.term.casefold() for entry in self.entries]
+        if len(terms) != len(set(terms)):
+            raise ValueError("glossary terms must be unique")
+        return self
+
+
+PolicyT = TypeVar("PolicyT", bound=PolicyModel)
+
+
+class GovernanceLoadResult(ImmutableModel, Generic[PolicyT]):
+    """Result of loading one policy, including fail-closed diagnostics."""
+
+    policy: PolicyT | None = None
+    schema_version: str = "unknown"
+    checksum: str = "unavailable"
+    diagnostic_mode: bool = False
+    diagnostics: tuple[str, ...] = ()
+    research_state: ResearchState = "manual_review"
+    score_state: Literal["not_scoreable"] = "not_scoreable"
+    research_promotion_allowed: Literal[False] = False
+    portfolio_review_allowed: Literal[False] = False
+    execution_allowed: Literal[False] = False
+    executable_authority: Literal[False] = False
+
+    @property
+    def value(self) -> PolicyT | None:
+        """Compatibility alias for callers that call the payload ``value``."""
+
+        return self.policy
+
+    @property
+    def model(self) -> PolicyT | None:
+        """Compatibility alias for callers that call the payload ``model``."""
+
+        return self.policy
+
+    @property
+    def valid(self) -> bool:
+        return not self.diagnostic_mode and self.policy is not None
+
+    @property
+    def scoreable(self) -> bool:
+        return self.score_state != "not_scoreable"
+
+
+__all__ = [
+    "SCHEMA_VERSION",
+    "SUPPORTED_SCHEMA_VERSIONS",
+    "REQUIRED_GATE_IDS",
+    "REQUIRED_GLOSSARY_TERMS",
+    "AuthorityPolicy",
+    "FeatureRegistryEntry",
+    "FeatureRegistryPolicy",
+    "GatePolicy",
+    "GatePolicyEntry",
+    "GlossaryEntry",
+    "GlossaryPolicy",
+    "GovernanceLoadResult",
+    "ImmutableModel",
+    "Authority",
+    "ProductDefinition",
+    "PolicyModel",
+    "ProductGovernancePolicy",
+    "StrategyScopeEntry",
+    "StrategyScopePolicy",
+]
diff --git a/src/etf_cockpit/governance/product_scope.py b/src/etf_cockpit/governance/product_scope.py
new file mode 100644
index 0000000..e0ac236
--- /dev/null
+++ b/src/etf_cockpit/governance/product_scope.py
@@ -0,0 +1,470 @@
+"""Fail-closed loaders for the local governance policy set."""
+
+from __future__ import annotations
+
+import hashlib
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Any, Mapping, TypeVar
+
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.core.paths import CONFIG_DIR
+from etf_cockpit.governance.models import (
+    AuthorityPolicy,
+    FeatureRegistryPolicy,
+    GatePolicy,
+    GlossaryPolicy,
+    GovernanceLoadResult,
+    PolicyModel,
+    ProductGovernancePolicy,
+    REQUIRED_GATE_IDS,
+    REQUIRED_GLOSSARY_TERMS,
+    StrategyScopePolicy,
+    SUPPORTED_SCHEMA_VERSIONS,
+)
+
+
+@dataclass(frozen=True)
+class PolicyPaths:
+    product: Path
+    feature_registry: Path
+    strategy_scope: Path
+    gate_policy: Path
+    glossary: Path
+
+
+DEFAULT_POLICY_PATHS = PolicyPaths(
+    product=CONFIG_DIR / "product_governance.yaml",
+    feature_registry=CONFIG_DIR / "feature_registry.yaml",
+    strategy_scope=CONFIG_DIR / "strategy_scope.yaml",
+    gate_policy=CONFIG_DIR / "gate_policy.yaml",
+    glossary=CONFIG_DIR / "glossary.yaml",
+)
+
+PRODUCT_GOVERNANCE_PATH = DEFAULT_POLICY_PATHS.product
+FEATURE_REGISTRY_PATH = DEFAULT_POLICY_PATHS.feature_registry
+STRATEGY_SCOPE_PATH = DEFAULT_POLICY_PATHS.strategy_scope
+GATE_POLICY_PATH = DEFAULT_POLICY_PATHS.gate_policy
+GLOSSARY_PATH = DEFAULT_POLICY_PATHS.glossary
+
+PolicyClassT = TypeVar("PolicyClassT", bound=PolicyModel)
+
+
+def _sha256_bytes(payload: bytes) -> str:
+    return hashlib.sha256(payload).hexdigest()
+
+
+def _diagnostic(
+    *,
+    schema_version: str,
+    checksum: str,
+    message: str,
+) -> GovernanceLoadResult[PolicyModel]:
+    return GovernanceLoadResult(
+        policy=None,
+        schema_version=schema_version,
+        checksum=checksum,
+        diagnostic_mode=True,
+        diagnostics=(message,),
+        research_state="manual_review",
+        score_state="not_scoreable",
+        research_promotion_allowed=False,
+        portfolio_review_allowed=False,
+        execution_allowed=False,
+        executable_authority=False,
+    )
+
+
+def _truthy(value: object) -> bool:
+    if isinstance(value, bool):
+        return value
+    if isinstance(value, (int, float)):
+        return value != 0
+    if isinstance(value, str):
+        return value.strip().casefold() in {"true", "yes", "on", "1"}
+    return False
+
+
+def _has_positive_authority(value: object) -> bool:
+    if isinstance(value, Mapping):
+        for key, item in value.items():
+            if str(key) in {
+                "execution_allowed",
+                "executable_authority",
+                "order_transmission",
+                "external_upload",
+                "credential_access",
+            } and _truthy(item):
+                return True
+            if _has_positive_authority(item):
+                return True
+    elif isinstance(value, list):
+        return any(_has_positive_authority(item) for item in value)
+    return False
+
+
+def _normalise_payload(model_class: type[PolicyClassT], raw: Mapping[str, Any]) -> dict[str, Any]:
+    payload = dict(raw)
+    if model_class is ProductGovernancePolicy:
+        authority = payload.get("authority")
+        if isinstance(authority, Mapping):
+            authority_payload = dict(authority)
+            payload["authority"] = authority_payload
+            for key in ("execution_allowed", "executable_authority"):
+                if key not in payload and key in authority_payload:
+                    payload[key] = authority_payload[key]
+    elif model_class is FeatureRegistryPolicy:
+        entries = payload.pop("features", payload.get("entries", ()))
+        normalised_entries = []
+        for raw_entry in entries or ():
+            if not isinstance(raw_entry, Mapping):
+                normalised_entries.append(raw_entry)
+                continue
+            entry = dict(raw_entry)
+            if "routes" not in entry and entry.get("route"):
+                entry["routes"] = (entry["route"],)
+            if "route" not in entry and entry.get("routes"):
+                entry["route"] = entry["routes"][0]
+            if "name" not in entry and entry.get("title"):
+                entry["name"] = entry["title"]
+            if "data_dependencies" not in entry and "required_data" in entry:
+                entry["data_dependencies"] = entry["required_data"]
+            if "required_data" not in entry and "data_dependencies" in entry:
+                entry["required_data"] = entry["data_dependencies"]
+            normalised_entries.append(entry)
+        payload["entries"] = normalised_entries
+    elif model_class is StrategyScopePolicy:
+        entries = payload.pop("strategies", payload.get("entries", ()))
+        normalised_entries = []
+        for raw_entry in entries or ():
+            if not isinstance(raw_entry, Mapping):
+                normalised_entries.append(raw_entry)
+                continue
+            entry = dict(raw_entry)
+            if "permitted_authority" not in entry and "authority" in entry:
+                entry["permitted_authority"] = entry["authority"]
+            if "authority" not in entry and "permitted_authority" in entry:
+                entry["authority"] = entry["permitted_authority"]
+            normalised_entries.append(entry)
+        payload["entries"] = normalised_entries
+    elif model_class is GatePolicy and "gates" not in payload:
+        payload["gates"] = payload.pop("entries", ())
+    elif model_class is GlossaryPolicy and "entries" not in payload:
+        payload["entries"] = payload.pop("glossary", payload.pop("terms", ()))
+    return payload
+
+
+def _validation_is_explicitly_contradictory(error: ValidationError) -> bool:
+    explicit_fields = {
+        "execution_allowed",
+        "executable_authority",
+        "order_transmission",
+        "external_upload",
+        "credential_access",
+        "score_authority",
+        "research_promotion_allowed",
+        "portfolio_review_allowed",
+        "paper_authority",
+        "execution_authority",
+        "permitted_authority",
+    }
+    duplicate_messages = {
+        "route values must be unique",
+        "order values must be unique",
+        "feature_id values must be unique",
+        "strategy_id values must be unique",
+        "glossary terms must be unique",
+        "gate_id values must be unique",
+    }
+    for detail in error.errors():
+        locations = {str(part) for part in detail.get("loc", ())}
+        if locations & explicit_fields:
+            return True
+        message = str(detail.get("msg", "")).casefold()
+        if any(marker in message for marker in duplicate_messages):
+            return True
+        if any(
+            marker in message
+            for marker in (
+                "positive authority",
+                "authority and permitted_authority must agree",
+                "authority 'none' cannot",
+                "execution_authority must remain none",
+                "gate severity cannot allow",
+                "strategies cannot have score_authority",
+                "strategies cannot have research_promotion_allowed",
+                "strategies cannot have portfolio_review_allowed",
+                "strategies cannot have paper_authority",
+                "strategies cannot have authority",
+                "score_authority is not permitted",
+                "research_promotion_allowed is not permitted",
+                "portfolio_review_allowed is not permitted",
+            )
+        ):
+            return True
+    return False
+
+
+def _substantive_section_error(model_class: type[PolicyClassT], payload: Mapping[str, Any]) -> str | None:
+    """Reject metadata-only and empty policy payloads before model defaults apply."""
+
+    if model_class is ProductGovernancePolicy:
+        if not isinstance(payload.get("product"), Mapping):
+            return "product governance policy requires a product block"
+        if not isinstance(payload.get("authority"), Mapping):
+            return "product governance policy requires an authority block"
+        return None
+    collection_key = "gates" if model_class is GatePolicy else "entries"
+    entries = payload.get(collection_key)
+    if not isinstance(entries, (list, tuple)) or not entries:
+        return f"{model_class.__name__} policy requires a non-empty {collection_key} collection"
+    return None
+
+
+def _contract_error(model_class: type[PolicyClassT], payload: Mapping[str, Any], policy: PolicyClassT) -> str | None:
+    """Validate required Group A metadata after strict Pydantic parsing."""
+
+    if model_class is ProductGovernancePolicy:
+        product = payload.get("product")
+        authority = payload.get("authority")
+        required_product = {"canonical_name", "category", "intended_user", "default_horizon", "decision_owner"}
+        required_authority = {
+            "maximum_operational_authority",
+            "broker_execution",
+            "execution_allowed",
+            "executable_authority",
+            "order_transmission",
+            "external_upload",
+            "credential_access",
+            "autonomous_portfolio_management",
+            "unvalidated_ai_score_authority",
+        }
+        if not isinstance(product, Mapping) or not required_product <= set(product):
+            return "product governance policy has an incomplete product block"
+        if not isinstance(authority, Mapping) or not required_authority <= set(authority):
+            return "product governance policy has an incomplete authority block"
+        if not payload.get("prohibited_claims") or not payload.get("required_disclosures"):
+            return "product governance policy requires prohibited_claims and required_disclosures"
+        return None
+
+    if model_class is FeatureRegistryPolicy:
+        entries = payload.get("entries", ())
+        required = {
+            "feature_id",
+            "name",
+            "category",
+            "routes",
+            "data_dependencies",
+            "issue_ids",
+            "tests",
+            "export_contracts",
+            "package_gate",
+            "lifecycle",
+            "authority",
+        }
+        for index, entry in enumerate(entries):
+            if not isinstance(entry, Mapping) or not required <= set(entry):
+                return f"feature registry entry {index} is missing required governance metadata"
+            if any(not entry.get(key) for key in ("name", "category", "routes", "data_dependencies", "issue_ids", "tests", "export_contracts", "package_gate")):
+                return f"feature registry entry {index} has empty required governance metadata"
+        try:
+            from etf_cockpit.app.router import PAGES
+
+            expected_routes = set(PAGES)
+            actual_routes = {route for item in policy.entries for route in item.canonical_routes}
+            if actual_routes != expected_routes:
+                return "feature registry routes must exactly match production routes"
+        except (ImportError, AttributeError):
+            return "feature registry route registry is unavailable"
+        return None
+
+    if model_class is StrategyScopePolicy:
+        required = {
+            "strategy_id",
+            "name",
+            "lifecycle",
+            "intended_use",
+            "permitted_authority",
+            "execution_authority",
+            "paper_authority",
+            "limitations",
+            "linked_issues",
+            "promotion_conditions",
+            "tests",
+        }
+        for index, entry in enumerate(payload.get("entries", ())):
+            if not isinstance(entry, Mapping) or not required <= set(entry):
+                return f"strategy scope entry {index} is missing required governance metadata"
+            if any(not entry.get(key) for key in ("name", "intended_use", "limitations", "linked_issues", "promotion_conditions", "tests")):
+                return f"strategy scope entry {index} has empty required governance metadata"
+        strategy_ids = {entry.strategy_id for entry in policy.entries}
+        required_inventory = {
+            "baseline_simple_scores",
+            "timesfm_challenger",
+            "toto_challenger",
+            "future_ml_challenger",
+            "llm_assistance",
+            "provider_news_context",
+            "paper_portfolio",
+            "pair_trading",
+            "triple_barrier_research",
+            "future_broker_architecture",
+            "martingale",
+            "grid",
+            "rl_agents",
+            "llm_only_management",
+            "model_only_trading",
+            "return_screenshots",
+            "unvalidated_sentiment",
+        }
+        if not required_inventory <= strategy_ids:
+            return "strategy scope inventory is missing required baseline, challenger, paper or rejected entries"
+        return None
+
+    if model_class is GatePolicy:
+        identifiers = tuple(gate.gate_id for gate in policy.gates)
+        orders = tuple(gate.order for gate in policy.gates)
+        if identifiers != REQUIRED_GATE_IDS or orders != tuple(range(1, len(REQUIRED_GATE_IDS) + 1)):
+            return "gate policy must contain the complete ordered gate set"
+        if any(gate.research_promotion_allowed or gate.portfolio_review_allowed for gate in policy.gates):
+            return "gate policy cannot grant promotion or portfolio review authority"
+        return None
+
+    if model_class is GlossaryPolicy:
+        terms = {entry.term.casefold() for entry in policy.entries}
+        missing = REQUIRED_GLOSSARY_TERMS - terms
+        if missing:
+            return f"glossary is missing required terms: {', '.join(sorted(missing))}"
+    return None
+
+
+def _load_policy(
+    path: Path,
+    model_class: type[PolicyClassT],
+    *,
+    policy_name: str,
+) -> GovernanceLoadResult[PolicyClassT]:
+    source = Path(path)
+    try:
+        raw_bytes = source.read_bytes()
+    except OSError as exc:
+        return _diagnostic(schema_version="unknown", checksum="unavailable", message=f"{policy_name} policy unavailable: {exc}")  # type: ignore[return-value]
+
+    checksum = _sha256_bytes(raw_bytes)
+    try:
+        loaded = yaml.safe_load(raw_bytes.decode("utf-8"))
+    except (UnicodeDecodeError, yaml.YAMLError) as exc:
+        return _diagnostic(schema_version="unknown", checksum=checksum, message=f"{policy_name} policy could not be parsed: {exc}")  # type: ignore[return-value]
+    if not isinstance(loaded, Mapping):
+        return _diagnostic(schema_version="unknown", checksum=checksum, message=f"{policy_name} policy must be a mapping")  # type: ignore[return-value]
+
+    schema_version = str(loaded.get("schema_version") or "unknown")
+    required_headers = {"schema_version", "policy_id", "policy_version"}
+    has_headers = required_headers.issubset(loaded)
+    positive_authority = _has_positive_authority(loaded)
+    payload = _normalise_payload(model_class, loaded)
+    if model_class is ProductGovernancePolicy and positive_authority:
+        authority_payload = payload.get("authority")
+        if isinstance(authority_payload, Mapping):
+            # Validate the authority block independently so a forbidden true
+            # value cannot be hidden by unrelated missing product metadata.
+            AuthorityPolicy.model_validate(authority_payload)
+    if "schema_version" not in loaded and not positive_authority:
+        return _diagnostic(
+            schema_version=schema_version,
+            checksum=checksum,
+            message=f"{policy_name} policy is missing required metadata",
+        )  # type: ignore[return-value]
+    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
+        return _diagnostic(
+            schema_version=schema_version,
+            checksum=checksum,
+            message=f"{policy_name} policy uses unsupported schema version {schema_version}",
+        )  # type: ignore[return-value]
+    if not has_headers and not positive_authority:
+        return _diagnostic(
+            schema_version=schema_version,
+            checksum=checksum,
+            message=f"{policy_name} policy is missing required metadata",
+        )  # type: ignore[return-value]
+    section_error = _substantive_section_error(model_class, payload)
+    if section_error and not positive_authority:
+        return _diagnostic(schema_version=schema_version, checksum=checksum, message=section_error)  # type: ignore[return-value]
+
+    try:
+        policy = model_class.model_validate(payload)
+        policy = policy.model_copy(update={"checksum": checksum})
+    except ValidationError as exc:
+        if _validation_is_explicitly_contradictory(exc):
+            raise
+        return _diagnostic(
+            schema_version=schema_version,
+            checksum=checksum,
+            message=f"{policy_name} policy failed validation: {exc}",
+        )  # type: ignore[return-value]
+
+    contract_error = _contract_error(model_class, payload, policy)
+    if contract_error:
+        return _diagnostic(schema_version=schema_version, checksum=checksum, message=contract_error)  # type: ignore[return-value]
+
+    return GovernanceLoadResult(
+        policy=policy,
+        schema_version=policy.schema_version,
+        checksum=checksum,
+        diagnostic_mode=False,
+        diagnostics=(),
+        research_state="manual_review",
+        score_state="not_scoreable",
+        research_promotion_allowed=False,
+        portfolio_review_allowed=False,
+        execution_allowed=False,
+        executable_authority=False,
+    )
+
+
+def load_product_governance(path: Path | None = None) -> GovernanceLoadResult[ProductGovernancePolicy]:
+    """Load product authority policy, remaining diagnostic-only on absence."""
+
+    return _load_policy(Path(path or PRODUCT_GOVERNANCE_PATH), ProductGovernancePolicy, policy_name="product governance")
+
+
+def load_feature_registry(path: Path | None = None) -> GovernanceLoadResult[FeatureRegistryPolicy]:
+    """Load the route/feature registry."""
+
+    return _load_policy(Path(path or FEATURE_REGISTRY_PATH), FeatureRegistryPolicy, policy_name="feature registry")
+
+
+def load_strategy_scope(path: Path | None = None) -> GovernanceLoadResult[StrategyScopePolicy]:
+    """Load strategy lifecycle and authority scope."""
+
+    return _load_policy(Path(path or STRATEGY_SCOPE_PATH), StrategyScopePolicy, policy_name="strategy scope")
+
+
+def load_gate_policy(path: Path | None = None) -> GovernanceLoadResult[GatePolicy]:
+    """Load the ordered fail-closed gate policy."""
+
+    return _load_policy(Path(path or GATE_POLICY_PATH), GatePolicy, policy_name="gate policy")
+
+
+def load_glossary(path: Path | None = None) -> GovernanceLoadResult[GlossaryPolicy]:
+    """Load explanatory glossary terms used by later governance surfaces."""
+
+    return _load_policy(Path(path or GLOSSARY_PATH), GlossaryPolicy, policy_name="glossary")
+
+
+__all__ = [
+    "DEFAULT_POLICY_PATHS",
+    "FEATURE_REGISTRY_PATH",
+    "GATE_POLICY_PATH",
+    "GLOSSARY_PATH",
+    "PRODUCT_GOVERNANCE_PATH",
+    "PolicyPaths",
+    "STRATEGY_SCOPE_PATH",
+    "load_feature_registry",
+    "load_gate_policy",
+    "load_glossary",
+    "load_product_governance",
+    "load_strategy_scope",
+]
diff --git a/tests/test_feature_registry.py b/tests/test_feature_registry.py
new file mode 100644
index 0000000..fccbd63
--- /dev/null
+++ b/tests/test_feature_registry.py
@@ -0,0 +1,76 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.app.router import PAGES
+from etf_cockpit.governance.models import FeatureRegistryEntry
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    load_feature_registry,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "feature_registry.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_feature_registry_covers_every_production_route() -> None:
+    result = load_feature_registry(DEFAULT_POLICY_PATHS.feature_registry)
+
+    assert result.diagnostic_mode is False
+    assert result.policy is not None
+    entries = result.policy.entries
+    assert len({entry.feature_id for entry in entries}) == len(entries)
+    assert len({entry.route for entry in entries}) == len(entries)
+    assert set(PAGES).issubset({entry.route for entry in entries})
+    assert all(entry.visible is True for entry in entries)
+    assert all(entry.execution_allowed is False for entry in entries)
+
+
+def test_feature_registry_rejects_duplicate_routes(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "features",
+            "policy_version": "1",
+            "execution_allowed": False,
+            "features": [
+                {"feature_id": "one", "route": "/", "lifecycle": "supported"},
+                {"feature_id": "two", "route": "/", "lifecycle": "supported"},
+            ],
+        },
+    )
+
+    with pytest.raises(ValidationError, match="route"):
+        load_feature_registry(path)
+
+
+def test_invalid_feature_registry_fails_closed(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"features": [{"feature_id": "missing-route"}]})
+
+    result = load_feature_registry(path)
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.research_promotion_allowed is False
+    assert result.portfolio_review_allowed is False
+    assert result.execution_allowed is False
+
+
+def test_experimental_feature_cannot_gain_positive_score_authority() -> None:
+    with pytest.raises(ValidationError, match="positive authority"):
+        FeatureRegistryEntry(
+            feature_id="experimental",
+            route="/experimental",
+            lifecycle="experimental",
+            score_authority=True,
+        )
diff --git a/tests/test_gate_policy.py b/tests/test_gate_policy.py
new file mode 100644
index 0000000..c7250bd
--- /dev/null
+++ b/tests/test_gate_policy.py
@@ -0,0 +1,85 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.governance.models import GatePolicyEntry
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    load_gate_policy,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "gate_policy.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_default_gate_policy_is_ordered_and_fail_closed() -> None:
+    result = load_gate_policy(DEFAULT_POLICY_PATHS.gate_policy)
+
+    assert result.diagnostic_mode is False
+    assert result.policy is not None
+    names = [gate.gate_id for gate in result.policy.gates]
+    assert names == [
+        "identity",
+        "data_quality",
+        "evidence",
+        "model_validity",
+        "risk",
+        "valuation",
+        "signal",
+        "portfolio_fit",
+        "cost",
+    ]
+    assert all(gate.execution_allowed is False for gate in result.policy.gates)
+    assert result.policy.execution_allowed is False
+    assert {gate.severity for gate in result.policy.gates} == {"blocker", "authority_warning"}
+
+
+def test_blocking_gate_cannot_allow_research_promotion() -> None:
+    with pytest.raises(ValidationError, match="research_promotion_allowed"):
+        GatePolicyEntry(
+            gate_id="identity",
+            order=1,
+            severity="blocker",
+            research_promotion_allowed=True,
+            portfolio_review_allowed=False,
+        )
+
+
+def test_gate_policy_rejects_duplicate_order(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "gates",
+            "policy_version": "1",
+            "execution_allowed": False,
+            "gates": [
+                {"gate_id": "first", "order": 1, "severity": "blocker"},
+                {"gate_id": "second", "order": 1, "severity": "notice"},
+            ],
+        },
+    )
+
+    with pytest.raises(ValidationError, match="order"):
+        load_gate_policy(path)
+
+
+def test_invalid_gate_policy_fails_closed(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"gates": [{"gate_id": "unknown", "severity": "bad"}]})
+
+    result = load_gate_policy(path)
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.research_promotion_allowed is False
+    assert result.portfolio_review_allowed is False
+    assert result.execution_allowed is False
diff --git a/tests/test_governance_review_regressions.py b/tests/test_governance_review_regressions.py
new file mode 100644
index 0000000..d93a1ab
--- /dev/null
+++ b/tests/test_governance_review_regressions.py
@@ -0,0 +1,254 @@
+from __future__ import annotations
+
+import hashlib
+import json
+import subprocess
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.app.router import PAGES
+from etf_cockpit.chatgpt_bridge import export_pack
+from etf_cockpit.governance.models import (
+    FeatureRegistryEntry,
+    GatePolicyEntry,
+    StrategyScopeEntry,
+)
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    load_feature_registry,
+    load_gate_policy,
+    load_glossary,
+    load_product_governance,
+    load_strategy_scope,
+)
+
+
+REQUIRED_GLOSSARY_TERMS = {
+    "alpha",
+    "beta",
+    "drawdown",
+    "calibration",
+    "pbo",
+    "dsr",
+    "mase",
+    "slippage",
+    "edge-to-cost",
+    "evidence authority",
+    "freshness",
+    "research state",
+    "portfolio-review state",
+    "blocker",
+    "authority-warning",
+    "notice",
+    "volatility",
+    "liquidity/spread proxy",
+    "confidence interval/quantile",
+    "walk-forward",
+    "purging/embargo",
+    "model promotion",
+    "forecast-error measures",
+    "n/a versus zero",
+    "source conflict",
+}
+
+REQUIRED_STRATEGY_IDS = {
+    "baseline_simple_scores",
+    "timesfm_challenger",
+    "toto_challenger",
+    "future_ml_challenger",
+    "llm_assistance",
+    "provider_news_context",
+    "paper_portfolio",
+    "pair_trading",
+    "triple_barrier_research",
+    "future_broker_architecture",
+    "martingale",
+    "grid",
+    "rl_agents",
+    "llm_only_management",
+    "model_only_trading",
+    "return_screenshots",
+    "unvalidated_sentiment",
+}
+
+
+def write_yaml(root: Path, payload: object, name: str = "policy.yaml") -> Path:
+    path = root / name
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+@pytest.mark.parametrize(
+    ("loader", "section"),
+    [
+        (load_product_governance, "product"),
+        (load_feature_registry, "entries"),
+        (load_strategy_scope, "entries"),
+        (load_gate_policy, "gates"),
+        (load_glossary, "entries"),
+    ],
+)
+def test_metadata_only_policy_fails_closed(tmp_path: Path, loader, section: str) -> None:
+    path = write_yaml(
+        tmp_path,
+        {"schema_version": "1.0", "policy_id": "metadata-only", "policy_version": "1"},
+    )
+
+    result = loader(path)
+
+    assert result.diagnostic_mode is True, section
+    assert result.policy is None
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.research_promotion_allowed is False
+    assert result.portfolio_review_allowed is False
+
+
+@pytest.mark.parametrize(
+    ("loader", "payload"),
+    [
+        (load_product_governance, {"authority": {}}),
+        (load_feature_registry, {"features": []}),
+        (load_strategy_scope, {"strategies": []}),
+        (load_gate_policy, {"gates": []}),
+        (load_glossary, {"glossary": []}),
+    ],
+)
+def test_empty_nested_policy_section_fails_closed(tmp_path: Path, loader, payload: dict[str, object]) -> None:
+    payload = {
+        "schema_version": "1.0",
+        "policy_id": "incomplete",
+        "policy_version": "1",
+        **payload,
+    }
+
+    result = loader(write_yaml(tmp_path, payload))
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+
+
+def test_unknown_schema_version_fails_closed(tmp_path: Path) -> None:
+    payload = yaml.safe_load(DEFAULT_POLICY_PATHS.product.read_text(encoding="utf-8"))
+    payload["schema_version"] = "9.9"
+
+    result = load_product_governance(write_yaml(tmp_path, payload))
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+    assert any("schema" in message.casefold() for message in result.diagnostics)
+
+
+@pytest.mark.parametrize(
+    ("kwargs", "message"),
+    [
+        ({"lifecycle": "rejected", "paper_authority": True}, "paper_authority"),
+        ({"lifecycle": "future_only", "paper_authority": True}, "paper_authority"),
+        ({"lifecycle": "rejected", "authority": "research_state"}, "authority"),
+        ({"lifecycle": "future_only", "portfolio_review_allowed": True}, "portfolio_review_allowed"),
+        ({"lifecycle": "supported", "authority": "none", "score_authority": True}, "authority"),
+    ],
+)
+def test_strategy_authority_and_lifecycle_mismatches_are_rejected(kwargs: dict[str, object], message: str) -> None:
+    with pytest.raises(ValidationError, match=message):
+        StrategyScopeEntry(strategy_id="mismatch", name="Mismatch", **kwargs)
+
+
+def test_feature_authority_and_lifecycle_mismatch_is_rejected() -> None:
+    with pytest.raises(ValidationError, match="authority"):
+        FeatureRegistryEntry(
+            feature_id="mismatch",
+            route="/mismatch",
+            lifecycle="supported",
+            authority="none",
+            score_authority=True,
+        )
+
+
+@pytest.mark.parametrize("severity", ["blocker", "authority_warning", "notice"])
+def test_no_gate_severity_can_grant_promotion_or_review(severity: str) -> None:
+    with pytest.raises(ValidationError, match="research_promotion_allowed"):
+        GatePolicyEntry(
+            gate_id="unsafe",
+            order=1,
+            severity=severity,
+            research_promotion_allowed=True,
+        )
+
+
+def test_feature_registry_has_complete_metadata_and_route_coverage() -> None:
+    result = load_feature_registry(DEFAULT_POLICY_PATHS.feature_registry)
+    assert result.policy is not None
+    assert result.diagnostic_mode is False
+    assert {route for entry in result.policy.entries for route in entry.routes} == set(PAGES)
+    for entry in result.policy.entries:
+        assert entry.name
+        assert entry.category
+        assert entry.routes
+        assert entry.data_dependencies
+        assert entry.issue_ids
+        assert entry.tests
+        assert entry.export_contracts
+        assert entry.package_gate
+
+
+def test_strategy_inventory_and_typed_metadata_are_complete() -> None:
+    result = load_strategy_scope(DEFAULT_POLICY_PATHS.strategy_scope)
+    assert result.policy is not None
+    entries = {entry.strategy_id: entry for entry in result.policy.entries}
+    assert REQUIRED_STRATEGY_IDS <= entries.keys()
+    for entry in result.policy.entries:
+        assert entry.intended_use
+        assert entry.permitted_authority in {
+            "evidence_only",
+            "context_only",
+            "research_state",
+            "portfolio_review",
+            "user_record",
+            "none",
+        }
+        assert entry.execution_authority == "none"
+        assert entry.limitations
+        assert entry.linked_issues
+        assert entry.promotion_conditions
+
+
+def test_glossary_covers_required_governance_terms() -> None:
+    result = load_glossary(DEFAULT_POLICY_PATHS.glossary)
+    assert result.policy is not None
+    terms = {entry.term.casefold() for entry in result.policy.entries}
+    assert REQUIRED_GLOSSARY_TERMS <= terms
+
+
+def test_policy_checksum_manifest_names_real_revision_with_all_policy_files() -> None:
+    manifest_path = Path("evidence/governance/policy_checksums.json")
+    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
+    source_commit = manifest["source_commit"]
+    paths = set(
+        subprocess.check_output(
+            ["git", "ls-tree", "-r", "--name-only", source_commit, "--", "configs"],
+            text=True,
+        ).splitlines()
+    )
+    for record in manifest["policies"].values():
+        relative_path = record["path"]
+        assert relative_path in paths
+        content = subprocess.check_output(["git", "show", f"{source_commit}:{relative_path}"])
+        assert hashlib.sha256(content).hexdigest() == record["sha256"]
+
+
+def test_audit_manifest_includes_governance_checksums_version_and_diagnostic_marker(tmp_path: Path) -> None:
+    export_pack._write_audit_manifest(tmp_path, {}, {})
+
+    manifest = json.loads((tmp_path / "audit_manifest.json").read_text(encoding="utf-8"))
+    required = {item["path"] for item in manifest["required"]}
+    governance = manifest["governance"]
+    assert "evidence_export/governance/policy_checksums.json" in required
+    assert "evidence_export/governance/policy_checksums.json" in manifest["checksums"]
+    assert governance["schema_version"] == "1.0"
+    assert governance["diagnostic_mode"] is False
+    assert len(governance["policy_checksums"]) == 5
+    assert governance["diagnostic_marker"] == "governance_valid"
diff --git a/tests/test_product_governance.py b/tests/test_product_governance.py
new file mode 100644
index 0000000..d571451
--- /dev/null
+++ b/tests/test_product_governance.py
@@ -0,0 +1,91 @@
+from __future__ import annotations
+
+import hashlib
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.governance.models import ProductGovernancePolicy
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    GovernanceLoadResult,
+    load_product_governance,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "policy.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})
+
+    with pytest.raises(ValidationError, match="order_transmission"):
+        load_product_governance(path)
+
+
+def test_product_policy_is_immutable_and_checksum_bearing() -> None:
+    result = load_product_governance(DEFAULT_POLICY_PATHS.product)
+
+    assert isinstance(result, GovernanceLoadResult)
+    assert result.policy is not None
+    assert result.schema_version == result.policy.schema_version == "1.0"
+    assert result.checksum == result.policy.checksum
+    assert result.checksum == hashlib.sha256(DEFAULT_POLICY_PATHS.product.read_bytes()).hexdigest()
+    assert result.execution_allowed is False
+    assert result.policy.product.canonical_name == "ETF AI Cockpit"
+    assert result.policy.authority.maximum_operational_authority == "manual_research"
+    assert result.policy.authority.broker_execution == "forbidden"
+    with pytest.raises(ValidationError):
+        result.policy.policy_version = "tampered"
+
+
+def test_missing_product_policy_fails_closed_to_diagnostic_mode(tmp_path: Path) -> None:
+    result = load_product_governance(tmp_path / "missing.yaml")
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.research_promotion_allowed is False
+    assert result.portfolio_review_allowed is False
+    assert result.execution_allowed is False
+    assert result.checksum == "unavailable"
+
+
+def test_product_policy_rejects_any_positive_authority_flag(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "test",
+            "policy_version": "1",
+            "authority": {
+                "execution_allowed": True,
+                "executable_authority": False,
+                "order_transmission": False,
+            },
+        },
+    )
+
+    with pytest.raises(ValidationError, match="execution_allowed"):
+        load_product_governance(path)
+
+
+def test_product_model_rejects_extra_fields() -> None:
+    with pytest.raises(ValidationError):
+        ProductGovernancePolicy(
+            schema_version="1.0",
+            policy_id="test",
+            policy_version="1",
+            authority={
+                "execution_allowed": False,
+                "executable_authority": False,
+                "order_transmission": False,
+            },
+            unexpected="not permitted",
+        )
diff --git a/tests/test_strategy_scope.py b/tests/test_strategy_scope.py
new file mode 100644
index 0000000..a90da92
--- /dev/null
+++ b/tests/test_strategy_scope.py
@@ -0,0 +1,72 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.governance.models import StrategyScopeEntry
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    load_strategy_scope,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "strategy_scope.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
+    with pytest.raises(ValidationError, match="score_authority"):
+        StrategyScopeEntry(lifecycle="experimental", score_authority=True)
+
+
+def test_rejected_strategy_cannot_have_any_authority() -> None:
+    with pytest.raises(ValidationError, match="authority"):
+        StrategyScopeEntry(
+            strategy_id="martingale",
+            lifecycle="rejected",
+            score_authority=False,
+            research_promotion_allowed=True,
+        )
+
+
+def test_default_strategy_scope_contains_supported_and_rejected_families() -> None:
+    result = load_strategy_scope(DEFAULT_POLICY_PATHS.strategy_scope)
+
+    assert result.diagnostic_mode is False
+    assert result.policy is not None
+    by_id = {entry.strategy_id: entry for entry in result.policy.entries}
+    assert by_id["etf_trend_momentum"].lifecycle == "supported"
+    assert by_id["pair_trading"].lifecycle == "research_only"
+    assert by_id["martingale"].lifecycle == "rejected"
+    assert by_id["llm_only_management"].score_authority is False
+    assert all(entry.execution_allowed is False for entry in result.policy.entries)
+
+
+def test_invalid_strategy_scope_fails_closed(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "strategies",
+            "policy_version": "1",
+            "execution_allowed": False,
+            "strategies": [{"strategy_id": "bad", "lifecycle": "experimental", "score_authority": True}],
+        },
+    )
+
+    with pytest.raises(ValidationError, match="score_authority"):
+        load_strategy_scope(path)
+
+
+def test_missing_strategy_scope_fails_closed(tmp_path: Path) -> None:
+    result = load_strategy_scope(tmp_path / "missing.yaml")
+
+    assert result.diagnostic_mode is True
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.execution_allowed is False
