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

- [x] **Step 1: Create failing policy tests**

```python
def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})
    with pytest.raises(ValidationError, match="order_transmission"):
        load_product_governance(path)

def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
    with pytest.raises(ValidationError, match="score_authority"):
        StrategyScopeEntry(lifecycle="experimental", score_authority=True)
```

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`

Expected: FAIL because governance policy models and files are absent.

- [x] **Step 3: Implement immutable policy models and checksum loading**

All loaders return a Pydantic object, schema version and SHA-256 checksum. An invalid or absent policy yields `GovernanceLoadResult(diagnostic_mode=True)` with `manual_review`/`not_scoreable`, no research promotion and no portfolio review.

- [x] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`

Expected: PASS; every production route and user-visible subsystem has one feature registry entry, and prohibited authority combinations fail validation.

- [x] **Step 5: Checkpoint policy provenance**

Generate `evidence/governance/policy_checksums.json` with no secret values and attach it to the wave ledger.

**Task 1 completion checkpoint (2026-07-12):** The policy contract and loader
were implemented, fixed after the independent review, and merged through PR
171 at `a54aed9c8157ff361eb7782252a88a471b835499`. The focused governance
bundle passed 43 tests; the full suite reproduced 316 passes and seven
pre-existing generated-data/identity failures; scoped Ruff and compileall
passed. Fresh independent re-review approved specification compliance and code
quality with no Critical, Important or Minor findings. Task 1 does not close
the owning issues: Task 2 owns research-state migration, and later tasks own
authority resolution, the journal and governance UI. `execution_allowed`
remains `false`.

### Task 2: Split public research state from internal signal intent and migrate historical records

**Files:**

- Create: `src/etf_cockpit/signals/research_states.py`, `src/etf_cockpit/governance/migrations.py`, `tests/test_research_state_migration.py`
- Modify: `src/etf_cockpit/core/types.py:1-131`, `src/etf_cockpit/signals/actions.py:1-52`, `src/etf_cockpit/signals/simple_scores.py:133-1989`, `data/score_history.py`, export schemas

**Consumes:** Task 1 policy checksums.

**Produces:** v2 serialisation with `research_state`, `portfolio_review_state`, explicit authority fields and traceable `legacy_action`.

- [x] **Step 1: Create failing migration and public-type tests**

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

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_research_state_migration.py tests\test_simple_scores.py tests\test_trade_proposals.py -q`

Expected: FAIL because public models still expose legacy `Action` values.

- [x] **Step 3: Implement v1-to-v2 migration and score-output adapter**

```python
def migrate_legacy_action(record: Mapping[str, object]) -> ResearchStateMigration: ...
def resolve_research_state(components: Sequence[ScoreComponent], decision: AuthorityDecision) -> ResearchState: ...
```

The migration maps unknown legacy action values to `manual_review`, preserves original text, is idempotent and writes a new versioned dataset before any catalogue pointer changes.

- [x] **Step 4: Run GREEN and property tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_research_state_migration.py tests\test_simple_scores.py tests\test_score_history.py -q`

Expected: PASS; repeat migration is semantically byte-equivalent and an experimental model cannot create a positive public research state.

- [x] **Step 5: Record migration report**

Write row counts, mapped/unmapped values, old/new checksums and a compatibility-window note to `evidence/governance/research_state_migration_report.json`.

**Task 2 completion checkpoint (2026-07-12):** v1.x legacy actions now map to
the separate v2 research and portfolio-review states with preserved
`legacy_action`, deterministic snapshot checksums, idempotent migration and
fail-closed authority. Score history, signal serializers and ChatGPT/export
schemas use the v2 field set while compatibility imports remain supported.
Direct v2 construction cannot mint positive authority or non-2.0 version
metadata; `execution_allowed` remains `false`. RED/GREEN evidence and the
seven pre-existing full-suite fixture/identity failures are recorded in
`.ai_worklog/task-governance-2-report.md` and
`evidence/governance/task2-full-suite-final.txt`. Final fresh independent
review and re-review passed specification compliance and code quality with no
findings (`.ai_worklog/task-governance-2-review-rereview-final.md`). The
implementation was merged through PR 172 at
`ab4772c36701507da444ebd73243ff827b5403af`; no issue moved between local
ledgers. Wave 1 Governance Task 3 is next.

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
