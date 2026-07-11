# Domain Analytics and Transparent Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `DOMAIN-01` through `DOMAIN-04` and `SCORE-01` through `SCORE-05` through explicit template routing, point-in-time domain metrics, a frozen non-AI champion, explicit benchmark/factor/friction contracts and a six-part decision report.

**Architecture:** Preserve the source-aware deterministic score contribution rule in `signals/simple_scores.py`. Move authority/weights/benchmarks into versioned policies, keep model outputs excluded by default, and consume typed classification/evidence/portfolio interfaces rather than parsing source files inside the score engine.

**Tech Stack:** Python 3.13, Pydantic, NumPy, pandas, DuckDB/PyArrow, scikit-learn where explicitly installed, Flet, pytest and Hypothesis.

## Global Constraints

- No scope drift; do not create broker, order, credential or external-upload functionality.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service.
- The production champion is transparent and non-AI. A score never becomes a forecast, order or authority bypass.
- All domain metrics preserve source, period, unit, availability and N/A distinction.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- Visible Flet changes reuse the existing dark research-cockpit vocabulary and expose semantic, keyboard and state behaviour.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Create `src/etf_cockpit/domain/router.py`, `templates.py`, `metrics.py`, `facts.py`, `peer_sets.py`, `normalisation.py`, `general_equity.py`, `banks.py`, `sparebanken.py`, `etfs.py` | template-specific facts/metrics and explicit applicability |
| Create `src/etf_cockpit/scoring/score_policy.py`, `champion.py`, `benchmarks.py`, `factor_exposures.py`, `covariance.py`, `risk_contributions.py`, `friction.py`, `tail_risk.py`, `scenarios.py`, `decision_report.py` | authoritative score policy, benchmark/risk/friction and six-part report |
| Modify `signals/simple_scores.py:133-1989`, `signals/friction_edge.py`, `models/ensemble.py`, `features/benchmark_attribution.py`, score components/pages | adapters to new policy/report without breaking existing rows during migration |
| Create policies | `analytical_templates.yaml`, `metric_dictionary.yaml`, `peer_policies.yaml`, `score_policies.yaml`, `benchmark_policies.yaml`, `factor_registry.yaml`, `friction_policy.yaml`, `scenario_library.yaml` |

**Interfaces:**

```python
class TemplateResolution(BaseModel):
    instrument_id: str
    template_id: str | None
    status: str
    required_missing_fields: list[str]
    gate_results: list[str]

class BenchmarkAssignment(BaseModel):
    instrument_id: str
    purpose: str
    primary_benchmark_id: str
    currency_basis: str
    total_return_basis: str
    assignment_rule_id: str

class DecisionReport(BaseModel):
    report_id: str
    authority_decision: AuthorityDecision
    benchmark: BenchmarkAssignment
    sections: list[DecisionReportSection]
    champion_policy_checksum: str
```

### Task 1: Route every instrument to a supported domain template

**Files:**

- Create: `domain/router.py`, `domain/templates.py`, `tests/domain/test_router.py`, `tests/domain/test_templates.py`
- Modify: classification support matrix adapter and `signals/simple_scores.py:461-803`

**Consumes:** registry `ResolvedClassification` and governance gate interface.

**Produces:** template resolution that explicitly returns supported, manual-review or not-scoreable instead of stock fallback.

- [ ] **Step 1: Write RED routing tests**

```python
def test_unknown_structure_has_no_general_equity_fallback() -> None:
    result = resolve_template(unknown_classification, as_of=AS_OF)
    assert result.template_id is None
    assert result.status == "manual_review"

def test_equity_certificate_requires_bank_template() -> None:
    result = resolve_template(sparebanken_classification, as_of=AS_OF)
    assert result.template_id == "norwegian_savings_bank_equity_certificate"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\test_router.py tests\domain\test_templates.py tests\test_simple_scores.py -q`

Expected: FAIL because only ETF/stock-like branching exists.

- [ ] **Step 3: Implement versioned router and template definitions**

The router consumes classification as-of version, support matrix and identity state; it returns missing requirements, reasons and gate codes. It has no network access and emits semantic invalidation only for domain/final score output.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\test_router.py tests\domain\test_templates.py tests\test_asset_guardrails.py -q`

Expected: PASS; unsupported structures cannot enter general-equity scoring.

- [ ] **Step 5: Store template coverage evidence**

Export current-universe template/support coverage with unresolved count and policy checksum.

### Task 2: Build source-linked metric/peer engines for operating companies, banks and ETFs

**Files:**

- Create: `domain/metrics.py`, `facts.py`, `peer_sets.py`, `normalisation.py`, `general_equity.py`, `banks.py`, `sparebanken.py`, `etfs.py`
- Test: `tests/domain/test_metric_dictionary.py`, `test_fact_mapping.py`, `test_general_equity.py`, `test_banks.py`, `test_sparebanken.py`, `test_etfs.py`, `test_reconciliation.py`

**Consumes:** Task 1 template and storage/evidence point-in-time facts/documents.

**Produces:** `MetricResult` values with `available`, `not_applicable`, `missing_required`, `conflicted` and `low_authority` status.

- [ ] **Step 1: Write RED metric status/reconciliation tests**

```python
def test_negative_earnings_are_not_neutral_pe_score() -> None:
    result = calculate_metric("earnings_yield", negative_earnings_facts, template="general_operating_company")
    assert result.status == "not_applicable"
    assert result.normalised_score is None

def test_bank_missing_cet1_blocks_bank_domain_component() -> None:
    component = build_bank_component(facts_without_cet1)
    assert component.status == "missing_required"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\test_general_equity.py tests\domain\test_banks.py tests\domain\test_etfs.py tests\domain\test_reconciliation.py -q`

Expected: FAIL because provider ratios and generic stock calculations do not retain complete source/period/applicability contracts.

- [ ] **Step 3: Implement metric dictionary, raw-fact reconciliation and robust peers**

Each metric declares numerator/denominator fact IDs, period/unit/sign policy, source authority minimum, valid range and explanation. Banks use capital/funding/asset-quality/certificate fields; ETFs preserve disclosed coverage/cash/derivatives/residual and never normalise partial holdings to 100%.

- [ ] **Step 4: Run GREEN and point-in-time regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain tests\test_fundamentals.py tests\test_fund_holdings.py tests\test_no_lookahead.py -q`

Expected: PASS; peer sample insufficiency, restatements, N/A and low-authority provider fallback remain visible.

- [ ] **Step 5: Produce fact/metric audit extracts**

Store metric dictionary checksum, reconciliation summary, peer-set version and representative source locators.

### Task 3: Freeze the non-AI champion and explicit benchmark assignment

**Files:**

- Create: `scoring/score_policy.py`, `champion.py`, `benchmarks.py`, `tests/scoring/test_score_policy.py`, `test_champion.py`, `test_benchmarks.py`, `test_component_correlation.py`
- Modify: `signals/simple_scores.py:317-590`, `models/ensemble.py`, `signals/scoring.py`, `backtest/benchmarks.py`, config files

**Consumes:** Tasks 1-2 domain components and governance authority.

**Produces:** frozen champion policy/checksum and purpose-based benchmark assignment.

- [ ] **Step 1: Write RED authority/order tests**

```python
def test_shuffling_enabled_universe_does_not_change_benchmark() -> None:
    assert assign_benchmark(universe_a, instrument_id="DB1") == assign_benchmark(universe_b_reordered, instrument_id="DB1")

def test_model_component_cannot_change_champion_score() -> None:
    assert champion_score(with_model_value=0.0) == champion_score(with_model_value=10.0)
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scoring\test_score_policy.py tests\scoring\test_champion.py tests\scoring\test_benchmarks.py tests\test_simple_scores.py -q`

Expected: FAIL because first-enabled benchmark and legacy ensemble weights remain reachable.

- [ ] **Step 3: Implement policy-only champion/benchmark resolver**

The champion policy validates weight families, required/optional component handling, no experimental/model component and policy checksum. Benchmark assignment selects canonical index/rate/security by template/region/purpose, return/currency/hedging basis and explicit unavailable gate; it never uses configuration order.

- [ ] **Step 4: Run GREEN and mutation regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scoring\test_score_policy.py tests\scoring\test_champion.py tests\scoring\test_benchmarks.py tests\test_release_hardening.py -q`

Expected: PASS; injected TimesFM weight or first-column benchmark causes a test failure.

- [ ] **Step 5: Write champion manifest**

Export policy, component-correlation report, benchmark assignments and current limitations.

### Task 4: Establish factor/risk/friction/tail services without fabricated edge

**Files:**

- Create: `scoring/factor_exposures.py`, `covariance.py`, `risk_contributions.py`, `friction.py`, `liquidity.py`, `tail_risk.py`, `scenarios.py`
- Test: `tests/scoring/test_factor_exposures.py`, `test_covariance.py`, `test_risk_contributions.py`, `test_friction.py`, `test_tail_risk.py`, `test_scenarios.py`
- Modify: `signals/friction_edge.py`, risk/portfolio view models

**Consumes:** Task 3 benchmark/champion and storage returns/cost sources.

**Produces:** descriptive risk/factor/friction results with source/assumption/uncertainty fields.

- [ ] **Step 1: Write RED no-score-edge and reconciliation tests**

```python
def test_score_is_not_converted_to_expected_return_or_edge() -> None:
    estimate = estimate_friction(listing, score_10=9.9, expected_return=None)
    assert estimate.net_edge is None
    assert estimate.total_estimated_cost is not None

def test_risk_contributions_sum_to_portfolio_variance() -> None:
    result = calculate_risk_contributions(weights, covariance)
    assert result.percentage_contributions.sum() == pytest.approx(1.0)
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scoring\test_friction.py tests\scoring\test_covariance.py tests\scoring\test_risk_contributions.py tests\test_friction_edge.py -q`

Expected: FAIL because fixed score-derived edge and insufficiently typed risk/cost paths remain.

- [ ] **Step 3: Implement source-based friction/tail/factor services**

Separate commission, FX, levy, observed/proxy half-spread, slippage and impact stress. Factor/risk output declares source/window/observation count/standard error/R² and calls itself Cockpit factor/risk, never Barra. Tail diagnostics return unavailable for insufficient sample rather than invented values.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scoring\test_friction.py tests\scoring\test_tail_risk.py tests\scoring\test_factor_exposures.py tests\scoring\test_covariance.py -q`

Expected: PASS, including singular covariance, missing spread and no expected-return input.

- [ ] **Step 5: Store scenario/factor evidence**

Write factor registry, covariance/risk summary, friction fixture output and tail scenario results.

### Task 5: Serialise a six-part decision report and authority-first score UI

**Files:**

- Create: `scoring/decision_report.py`, `tests/scoring/test_decision_report.py`, `tests/scoring/test_change_attribution.py`, `tests/ui/test_score_report_ui.py`, `tests/ui/test_factor_risk_ui.py`, `tests/ui/test_friction_tail_ui.py`
- Modify: score components/pages, instrument detail selector, CSV/JSON/audit exporters

**Consumes:** Tasks 1-4 and governance `AuthorityDecision`.

**Produces:** a versioned shared `DecisionReport` used identically by UI, export and audit.

- [ ] **Step 1: Write RED report/gate tests**

```python
def test_high_component_score_with_failed_gate_is_not_presented_as_positive_authority() -> None:
    report = build_decision_report(high_score_inputs, authority_decision=failed_identity_gate)
    assert report.authority_decision.research_state is ResearchState.NOT_SCOREABLE
    assert report.section("Experimental models/context").authority == "none"

def test_policy_change_is_not_described_as_market_change() -> None:
    delta = explain_report_change(previous_policy_report, changed_policy_report)
    assert "policy" in delta.changed_inputs
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scoring\test_decision_report.py tests\scoring\test_change_attribution.py tests\ui\test_score_report_ui.py -q`

Expected: FAIL because total score rows and exports do not share a six-section contract.

- [ ] **Step 3: Implement report builder and Flet progressive disclosure**

Expose evidence, domain/product, momentum/signals, risk/friction, portfolio fit and experimental/context sections. Every section carries raw metrics, N/A/missing/conflicts, source authority, policy version and linkable evidence. Gate summary appears before total score; compact rows use semantic status and side-sheet/full workspace disclosures.

- [ ] **Step 4: Run GREEN and browser matrix**

Run: `.\.venv\Scripts\python.exe -m pytest tests\scoring\test_decision_report.py tests\scoring\test_change_attribution.py tests\ui\test_score_report_ui.py tests\ui\test_factor_risk_ui.py tests\ui\test_friction_tail_ui.py -q`

Expected: PASS. Render at 1366×768, 1920×1080 and 150% zoom; keyboard focus reaches the gate drawer and full report.

- [ ] **Step 5: Submit scoring wave for review**

Provide champion manifest, no-AI mutation result, benchmark order-independence result, source/package screenshots and decision-report audit samples to a fresh reviewer.
