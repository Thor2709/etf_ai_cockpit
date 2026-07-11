# Transaction-Ledger Portfolio and Portfolio-Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `PORT-01` through `PORT-05` by replacing static/sample holdings with a local immutable transaction ledger, historical multi-currency valuation, sound performance measures, constrained non-executable scenarios and portfolio-review gates.

**Architecture:** Existing holdings/allocation/rebalancing/risk modules become derived adapters over a ledger replay service. Real, paper, model and scenario portfolios remain structurally separate; no broker connection, credential, order ticket or auto-execution path is introduced.

**Tech Stack:** Python 3.13, Decimal, Pydantic, DuckDB/PyArrow, NumPy/SciPy/CVXPY only when explicitly packaged, Flet and pytest.

## Global Constraints

- No scope drift; do not create broker, order, credential or external-upload functionality.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service.
- No sample/static holdings may silently become real portfolio data; real, paper, model and scenario data remain separate.
- Monetary values and quantities use `Decimal`; corrections supersede immutable events rather than edit history.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- Visible Flet changes reuse the existing dark research-cockpit vocabulary and expose semantic, keyboard and state behaviour.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Create `portfolio/models.py`, `ledger.py`, `imports.py`, `mappings.py`, `replay.py`, `cash.py`, `lots.py`, `corporate_actions.py`, `reconciliation.py` | immutable accounting event source and derived positions/cash/lots |
| Create `portfolio/valuation.py`, `fx.py`, `performance.py`, `attribution.py` | point-in-time valuations, FX, TWR/Dietz/XIRR and reconciliation |
| Create `portfolio/construction.py`, `constraints.py`, `fit.py`, `scenarios.py`, `review_reports.py` | hypothetical construction and typed portfolio review |
| Modify `portfolio/holdings.py`, `allocation.py`, `rebalancing.py`, `risk_analytics.py`, existing portfolio pages | compatibility derived views only |
| Create tests under `tests/portfolio/` and Flet journey tests under `tests/ui/` | ledger, valuation, performance, construction and UI behaviour |

**Interfaces:**

```python
class LedgerEvent(BaseModel):
    event_id: str
    portfolio_id: str
    account_id: str
    event_type: LedgerEventType
    event_at: datetime
    security_id: str | None
    listing_id: str | None
    quantity: Decimal | None
    cash_currency: str
    cash_amount: Decimal
    supersedes_event_id: str | None

def replay_ledger(events: Sequence[LedgerEvent], *, as_of: datetime) -> PortfolioSnapshot: ...
def calculate_twr(points: Sequence[PerformanceSeriesPoint]) -> PerformanceResult: ...
def resolve_portfolio_review(instrument_id: str, snapshot: PortfolioSnapshot, authority: AuthorityDecision) -> PortfolioReviewReport: ...
```

### Task 1: Establish immutable portfolio/account/ledger schema and safe sample migration

**Files:**

- Create: `portfolio/models.py`, `ledger.py`, `imports.py`, `mappings.py`, `tests/portfolio/test_models.py`, `test_ledger.py`, `test_imports.py`
- Modify: `portfolio/holdings.py`, legacy sample holding import path, onboarding/portfolio setup surface

**Consumes:** canonical registry IDs and Wave 0 atomic transaction contract.

**Produces:** append-only `LedgerEvent` records, account/portfolio types and sample/opening-balance migration choice.

- [ ] **Step 1: Write RED immutability/import tests**

```python
def test_sample_holdings_require_explicit_demo_or_opening_balance_choice() -> None:
    result = migrate_sample_holdings(sample_csv, decision=None)
    assert result.status == "awaiting_user_choice"
    assert result.created_events == []

def test_correction_supersedes_event_without_mutating_original() -> None:
    corrected = ledger.supersede(original.event_id, replacement)
    assert ledger.get(original.event_id).cash_amount == original.cash_amount
    assert corrected.supersedes_event_id == original.event_id
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_models.py tests\portfolio\test_ledger.py tests\portfolio\test_imports.py -q`

Expected: FAIL because positions are currently loaded from static summary data and no immutable ledger exists.

- [ ] **Step 3: Implement ledger storage and import preview**

Use `Decimal`, source/import identity, valid canonical listing/security IDs, trade/settlement dates, explicit fees/taxes/FX links and atomic grouped commits. CSV import previews mapping/duplicates/rejected rows before commit. The previous sample file remains a test/demo fixture only.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_models.py tests\portfolio\test_ledger.py tests\portfolio\test_imports.py tests\test_import_export.py -q`

Expected: PASS; duplicate imports, malformed rows and non-reconciled opening balance remain explicit.

- [ ] **Step 5: Capture migration and privacy evidence**

Write import mapping, row-count, source checksum and redaction manifest to `evidence/portfolio/ledger_migration/`.

### Task 2: Derive replayed positions, cash, lots and corporate-action history

**Files:**

- Create: `portfolio/replay.py`, `cash.py`, `lots.py`, `corporate_actions.py`, `reconciliation.py`, `tests/portfolio/test_replay.py`, `test_cash.py`, `test_lots.py`, `test_corporate_actions.py`, `test_reconciliation.py`
- Modify: current holdings/allocation/risk service adapters

**Consumes:** Task 1 immutable ledger and registry listing/corporate event relationships.

**Produces:** deterministic positions/cash/lots/reconciliation snapshots.

- [ ] **Step 1: Write RED replay/corporate-action tests**

```python
def test_same_ledger_replays_to_same_checksum_despite_input_order() -> None:
    assert replay_ledger(events, as_of=AS_OF).checksum == replay_ledger(list(reversed(events)), as_of=AS_OF).checksum

def test_split_preserves_economic_value_and_updates_quantity() -> None:
    snapshot = replay_ledger([buy_event, two_for_one_split], as_of=AS_OF)
    assert snapshot.position(listing_id).quantity == Decimal("20")
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_replay.py tests\portfolio\test_cash.py tests\portfolio\test_lots.py tests\portfolio\test_corporate_actions.py -q`

Expected: FAIL because existing holdings are not event-derived.

- [ ] **Step 3: Implement deterministic event ordering/replay**

Order by economic timestamp, settlement/effective policy, event priority and ID. Derive settled/unsettled cash, positions, lots, income, fees, tax and reconciliation exceptions. Corporate actions preserve predecessor/successor linkage; no event is deleted.

- [ ] **Step 4: Run GREEN and legacy adapter regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_replay.py tests\portfolio\test_cash.py tests\portfolio\test_lots.py tests\portfolio\test_corporate_actions.py tests\portfolio\test_reconciliation.py tests\test_rebalancing.py -q`

Expected: PASS; current allocation/risk views receive ledger-derived snapshots.

- [ ] **Step 5: Store reconciliation evidence**

Save replay checksum, reconciliation identity, unmatched statement exception and corporate-action test extracts.

### Task 3: Build historical valuation, FX and correct performance measures

**Files:**

- Create: `portfolio/valuation.py`, `fx.py`, `performance.py`, `attribution.py`, `tests/portfolio/test_valuation.py`, `test_fx.py`, `test_twr.py`, `test_dietz.py`, `test_xirr.py`, `test_attribution.py`
- Modify: portfolio/risk visual data selectors

**Consumes:** Task 2 snapshots, storage point-in-time prices/FX and benchmark policy.

**Produces:** local/base valuation points, TWR, Modified Dietz, XIRR and explicit performance-quality/reconciliation state.

- [ ] **Step 1: Write RED cash-flow/FX tests**

```python
def test_twr_does_not_treat_deposit_as_investment_return() -> None:
    result = calculate_twr(points_with_mid_period_deposit)
    assert result.cumulative_return == pytest.approx(0.0)

def test_actual_transaction_fx_precedes_reference_rate() -> None:
    value = value_event(event_with_actual_fx, reference_rates)
    assert value.fx_source_id == "transaction"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_valuation.py tests\portfolio\test_fx.py tests\portfolio\test_twr.py tests\portfolio\test_xirr.py -q`

Expected: FAIL because no historical ledger valuation/performance engine exists.

- [ ] **Step 3: Implement dated listing/FX valuation and performance reconciliation**

Use actual transaction FX first, then statement, official reference, provider and unavailable. Preserve stale/missing status, no silent forward fill beyond policy. Compute TWR between external flows, Dietz only when declared appropriate, XIRR with convergence/multiple-root status, and the required ending-value reconciliation identity.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_valuation.py tests\portfolio\test_fx.py tests\portfolio\test_twr.py tests\portfolio\test_dietz.py tests\portfolio\test_xirr.py tests\portfolio\test_attribution.py -q`

Expected: PASS, including EUR/AUD/USD/GBP, holidays, delisting, missing price and invalid XIRR fixtures.

- [ ] **Step 5: Save methodology and valuation coverage**

Export performance methodology, FX source summary, valuation coverage and reconciliation output without private account identifiers.

### Task 4: Create constrained hypothetical construction and fail-closed portfolio review

**Files:**

- Create: `portfolio/construction.py`, `constraints.py`, `fit.py`, `scenarios.py`, `review_reports.py`, `tests/portfolio/test_construction.py`, `test_constraints.py`, `test_fit.py`
- Modify: `portfolio/proposals.py` compatibility alias and instrument/portfolio view models

**Consumes:** Task 3 real/model snapshot, domain/risk/friction inputs and governance `AuthorityDecision`.

**Produces:** non-executable scenarios and `PortfolioReviewState` only after reconciled context/gates.

- [ ] **Step 1: Write RED scenario/review tests**

```python
def test_infeasible_constraints_return_diagnostic_not_order() -> None:
    result = solve_scenario(infeasible_profile)
    assert result.solver_status == "infeasible"
    assert result.execution_allowed is False

def test_positive_research_state_without_selected_reconciled_portfolio_is_not_applicable() -> None:
    review = resolve_portfolio_review("ASML", snapshot=None, authority=positive_authority)
    assert review.portfolio_review_state is PortfolioReviewState.NOT_APPLICABLE
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_construction.py tests\portfolio\test_constraints.py tests\portfolio\test_fit.py -q`

Expected: FAIL because legacy proposal/rebalancing code lacks real ledger context and scenario contracts.

- [ ] **Step 3: Implement constraints/scenarios/review resolver**

Apply identity/evidence/champion gates, current direct/look-through exposure, risk/currency/sector/capacity/cost/cash/tax/turnover constraints and solver diagnostics. Scenarios are saved separately and never change the ledger. Output contains no quantities/orders and always `execution_allowed=false`.

- [ ] **Step 4: Run GREEN plus proposal migration regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\portfolio\test_construction.py tests\portfolio\test_constraints.py tests\portfolio\test_fit.py tests\test_trade_proposals.py -q`

Expected: PASS; compatibility calls create non-executable review reports only.

- [ ] **Step 5: Submit portfolio evidence for review**

Provide ledger replay, performance reconciliation, multi-currency valuation, infeasible scenario, blocked review and privacy export artefacts to a fresh reviewer.
