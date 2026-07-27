# Current-state diff and implementation inventory

Baseline: `d149defcce3398c3cc463bc0d1cdbdf9a1e7cb4b`. This inventory is evidence for sequencing, not a claim that product features were implemented by this task.

## Application entry points and packaging

- The existing desktop/local application remains the launch surface. Keep startup baseline-safe and do not require optional provider or model packages.
- The repository retains its existing scripts and packaging conventions. New programme tooling is standard-library Python and writes only visible, deterministic artefacts.

## Navigation and workflow state

`src/etf_cockpit/app/router.py` currently registers **40** routes: `/`, `/portfolio`, `/portfolio-optimiser`, `/signals`, `/screener`, `/comparison`, `/stock-research`, `/risk`, `/stress-lab`, `/etf`, `/backtests`, `/chatgpt`, `/providers`, `/evidence`, `/filings`, `/etf-disclosures`, `/news-context`, `/data-models`, `/forecasts`, `/training-centre`, `/feature-catalogue`, `/catalogue`, `/macro`, `/settings`, `/diagnostics`, `/errors`, `/data-health`, `/universe`, `/onboarding`, `/what-changed`, `/instrument`, `/import-export`, `/system-map`, `/help`, `/decision-journal`, `/forward-evidence`, `/jobs`, `/operations`, `/release-readiness`, `/roadmap`. The count is higher than the plan's earlier estimate; this reconciliation records the source-of-truth count without altering routing.

The existing app state, onboarding, diagnostics, data-health, evidence and decision-journal surfaces should remain separate from feature calculations and provider/model bridges. Any later implementation must preserve default, loading, empty, partial, error, disabled and permission-denied states.

## Persistence, schemas and price policy

Existing persistence and configuration boundaries are retained. New user data belongs under `data/`, configs under `configs/`, logs under `logs/` and model files under `models/`. Return, signal and backtest work must use adjusted prices consistently and identify the price basis in evidence.

## Providers, evidence, scores and models

Provider results, filings, ETF disclosures, news context and model outputs are evidence inputs rather than authority. Toto and TimesFM remain optional. Baseline signals must still run without model packages or weights, and conflict/provenance handling must remain visible.

## Backtests, portfolio and authority

Backtests and portfolio analysis remain advisory. Risk gates override forecasts, audits and UI actions. Automatic trading is staged, disabled and non-default; this task adds no broker integration or execution path.

## Known limitations to carry into later implementation

- Point-in-time data completeness, holdings/transaction-cost fidelity and provider quotas require explicit evidence before certification.
- Static source inspection confirms the route inventory, but this documentation task does not claim runtime visual or performance certification.
- Performance work must measure refresh, cache, backtest and model operations with representative data; no training or inference target is invented here.
