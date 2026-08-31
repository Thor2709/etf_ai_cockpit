# Sparebank Stochastic Intelligence Engine × ETF AI Cockpit integration

**Status:** architecture and implementation handoff  
**Date:** 31 August 2026  
**Programme:** #715–#720  
**Initial milestone:** local, immutable and paper-only; `execution_allowed=false`

## 1. Correct perspective

The Sparebank Stochastic Intelligence Engine is the friend’s future greenfield application. ETF AI Cockpit is the existing application.

The intended relationship is:

```text
independent specialist model provider
        ↓ immutable versioned result artefact
generic Cockpit validation, portfolio, policy, paper and audit layer
```

It is not:

```text
friend engine imported as an internal Cockpit module
Cockpit database read directly by the friend engine
one shared mutable data model
specialist stochastic science reimplemented in Cockpit
model target treated as an order
```

## 2. Responsibility boundary

### Friend’s Sparebank engine

Owns:

- official Norwegian-bank evidence needed to reproduce its science;
- source authority, checksums, publication/knowledge time, revisions and restatements;
- canonical Sparebank/issuer/listing identity for its model universe;
- bank-state reconstruction;
- savings-bank and equity-certificate/EKB ownership-capital mechanics;
- hierarchical/Bayesian inference;
- deposit/NIM, credit-stage/loss and macro transmission;
- stochastic future bank-state simulation;
- specialist residual-income/EKB/corporate-event valuation;
- posterior/scenario diagnostics and calibrated return/downside distributions;
- scientific backtests, out-of-sample ranking, sensitivity and ablation;
- model target/preference and model-side limits;
- deterministic immutable external result artefacts.

Does not own:

- authoritative cross-asset portfolio holdings/cash;
- generic optimiser/rebalancing;
- tax-lot/fee/FX accounting;
- broker sessions/reconciliation;
- order state, partial fills and retries;
- generic pre-trade portfolio limits/kill switches;
- live execution authority;
- the operator’s generic portfolio UI.

### ETF AI Cockpit

Owns:

- canonical Cockpit entity/instrument/listing identity;
- bitemporal/PIT validation and immutable import provenance;
- generic deterministic stock/ETF/bank research;
- generic time-series/market forecasting;
- authoritative portfolio state as its planned ledger matures;
- optimiser, target reconciliation and cost-aware rebalancing;
- deterministic model-validity, data-quality, portfolio, risk and authority policy;
- whole-system event replay;
- paper proposal/order/fill simulation;
- UI, audit and explanation;
- later broker read-only and separately certified execution.

Does not own:

- specialist Bayesian Sparebank inference;
- stochastic bank balance-sheet evolution;
- specialist EKB ownership-capital attribution;
- internal reproduction of the friend engine’s scientific state.

## 3. Contract and transport

### First transport

Use an atomically published immutable JSON file:

```text
friend engine:
  write run_id.tmp
  fsync/close
  rename to run_id.sparebank-model-result.v1.json

Cockpit:
  observe complete final name
  read once into bytes
  validate canonical content/hash/schema/time/identity
  store original bytes and accepted projection immutably
```

A later loopback API may deliver the same bytes/schema. The contract, not the transport, is the boundary.

### Minimum v1 shape

```json
{
  "schema_version": "sparebank-model-result.v1",
  "producer": {
    "name": "sparebank_stochastic_engine",
    "model_version": "0.1.0",
    "code_revision": "..."
  },
  "run_id": "spb_2027Q4_003",
  "as_of": "2027-02-14T07:42:00+01:00",
  "known_at_cutoff": "2027-02-14T07:42:00+01:00",
  "status": "VALID",
  "critical_missing_inputs": [],
  "universe": ["NO0000000001"],
  "assets": {
    "NO0000000001": {
      "identity": {
        "isin": "NO0000000001",
        "ticker": "ROMER",
        "orgnr": "..."
      },
      "horizon": "3Y",
      "expected_cagr": 0.213,
      "median_cagr": 0.198,
      "p_loss": 0.081,
      "expected_shortfall_5pct": -0.194,
      "p_outperform_benchmark": 0.764,
      "target_weight": 0.32,
      "max_model_weight": 0.40,
      "confidence": 0.82,
      "validity_flags": []
    }
  },
  "portfolio_constraints": {
    "max_total_sparebank_weight": 0.80
  },
  "provenance": {
    "bundle_id": "...",
    "simulation_run_id": "...",
    "sha256": "..."
  },
  "execution_allowed": false
}
```

The exact optional metrics can evolve. Stable requirements are:

- explicit schema, producer, model and code versions;
- immutable run ID;
- timezone-aware `as_of` and knowledge cutoff;
- canonical identity evidence with safe aliases;
- explicit VALID/DEGRADED/INVALID and critical missingness;
- uncertainty/downside, not only a point estimate;
- target/preference and model-side limits;
- provenance references/hashes;
- no order instruction, broker credential or execution authority.

## 4. Cockpit fail-closed import

Reject or quarantine when:

- schema/producer/model contract unsupported;
- malformed or non-canonical content;
- invalid/missing checksum or provenance;
- same run ID conflicts with accepted bytes;
- non-idempotent import;
- identity unresolved or ambiguous;
- invalid, stale or critical-missing model status;
- timestamps use future knowledge for the decision/replay;
- numeric values are non-finite or impossible;
- targets/constraints conflict;
- required provenance is absent;
- artefact contains broker credentials or attempts to grant authority.

A quarantined run remains inspectable but cannot become optimiser/policy input.

## 5. End-to-end flow

```text
official disclosure
       ↓
friend engine evidence/revision store
       ↓
bank-state + EKB mechanics
       ↓
Bayesian/stochastic model and specialist valuation
       ↓
immutable model-result artefact
       ↓
Cockpit #716 contract/adapter/run store
       ↓
Cockpit #717 PIT identity + MODEL_UPDATE_AVAILABLE
       ↓
Cockpit #718 target translation + optimiser + gates
       ↓
Cockpit #719 UI/audit/independent-evidence comparison
       ↓
Cockpit existing paper proposal/order/fill ledger
       ↓
Cockpit #720 restart and historical replay certification
```

## 6. ETF AI Cockpit issue map

| Issue | Purpose | Reuses | Exit criterion |
|---|---|---|---|
| #715 | Integration epic and boundary | programme-wide | both projects, phases and paper milestone are explicit |
| #716 | v1 schema, adapter and immutable run store | #213, #216 | valid fixture accepted exactly; invalid/conflicting fixture fails closed |
| #717 | PIT identity and idempotent model-update event | #213, #217 | exact assets resolved/quarantined and one resumable event emitted |
| #718 | target/validity to optimiser and proposal gates | #253, #268, #270 | frozen current-versus-target transition or explicit block |
| #719 | UI, provenance and disagreement surface | audit/Instrument Detail/paper records | operator can reconstruct causal decision without LLM narrative |
| #720 | paper/restart/PIT replay certification | #265, #269 | same proposal/paper digest after restart/replay, no future data or duplicates |

Already implemented/integrated issues are referenced rather than modified into new hidden scope. New overlay issues are used because collaboration-specific acceptance was not part of their completed contracts.

## 7. Existing fundamental-analysis overlap

Cockpit should continue generic deterministic Norwegian-bank research:

- official filing path: #699;
- profitability/earnings quality: #700;
- balance-sheet/capital/funding/liquidity: #701;
- distributions/capital allocation: #702;
- generic bank valuation: #703;
- business quality/applicability: #704;
- bank/equity-certificate adapter: #705.

These are not duplicates of the friend engine if labels and provenance remain separate.

```text
Cockpit:
  transparent ratios, source facts, deterministic calculations,
  generic residual-income/P-TBV/P-B context

Friend engine:
  hierarchical/stochastic inference, EKB-specific mechanics,
  calibrated distributions, specialist ranking and model targets
```

If they disagree, preserve both. A versioned Cockpit policy may use the disagreement as a gate or review signal, but an LLM must not silently reconcile or overwrite either source.

## 8. Later milestones

### B5: real account read-only

Requires:

- #267 authoritative portfolio/cash/FX/fee/tax/corporate-action ledger;
- #271 broker read-only sync/reconciliation.

This is not required for the first local paper milestone.

### B6: separately certified execution

Requires:

- #272 independent pre-trade operational controls;
- #273 disabled staged canary;
- existing release/certification dependencies;
- explicit future authority.

Successful model import or paper replay cannot promote this lane.

## 9. Friend project suggested backlog

### A0 — domain and contract freeze

- supported bank/universe and identity rules;
- source authority;
- time/revision semantics;
- VALUE/UNCERTAIN/MISSING;
- scientific reproducibility;
- proposed `sparebank-model-result.v1`.

Exit: written specification and fixtures before model coding.

### A1 — official evidence and provenance

- one real listed Sparebanken;
- annual/interim/Pillar 3 as required;
- publication and retrieval time;
- checksum, source and revision history;
- issuer/listing/ISIN/LEI/org-number linkage.

Exit: one bank reconstructable from official evidence without Cockpit.

### A2 — deterministic bank state and EKB

- balance sheet, capital, funding, credit quality and distributions;
- equity-certificate ownership/economics;
- historical revision reconciliation;
- explicit missing regulatory facts.

Exit: deterministic bank state reconciles over periods.

### A3 — transparent baseline valuation/ranking

- deterministic non-Bayesian comparator;
- specialist residual-income/EKB treatment;
- documented target variable and horizon.

Exit: future stochastic value can be measured against a simple baseline.

### A4 — hierarchical/Bayesian macro-credit model

- priors, pooling and likelihoods;
- deposit/NIM and credit-loss mechanisms;
- macro transmission;
- posterior predictive checks;
- calibration diagnostics.

Exit: versioned model and diagnostics.

### A5 — stochastic simulation and distributions

- reproducible future states;
- capital headroom and downside/tail metrics;
- ranking/outperformance probability;
- sensitivity/ablation and out-of-sample tests.

Exit: scientifically defensible result distribution.

### A6 — model preference/limits

Separate forecast from allocation preference. Define target/preference and model-side maximums without creating an order.

### A7 — external artefacts and historical snapshots

- atomically published v1 result;
- original evidence/simulation references;
- deterministic historical rerun;
- no Cockpit dependency.

Exit: Cockpit can consume the public contract, and the friend engine can reproduce the result alone.

## 10. First joint acceptance

1. Three-bank v1 artefact produced atomically.
2. Cockpit accepts and stores exact original bytes/hash.
3. Canonical PIT identities resolved; unresolved weight explicit.
4. Frozen paper portfolio translated deterministically.
5. Model validity, freshness, cost, concentration and authority gates execute.
6. Failed gate creates no proposal.
7. Passing case creates one manually accepted paper proposal and simulated fills through the existing ledger.
8. Restart creates no duplicate event/proposal/order/fill.
9. Historical replay uses only information known at the saved time and reproduces the same state.
10. One changed model/input hash creates a new visible causal chain without mutating history.

## 11. Acceptance invariants

- Each codebase builds/tests/releases independently.
- No internal imports or shared mutable database.
- Every accepted run is immutable and PIT-replayable.
- Restatements create new knowledge states.
- Model target is not an order.
- Cockpit deterministic gates outrank model/LLM persuasion.
- Generic and specialist bank evidence remain separately labelled.
- Duplicate events and restart races cannot create duplicate effects.
- Initial milestone remains paper only.
- `execution_allowed=false`.
