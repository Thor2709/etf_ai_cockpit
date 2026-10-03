# Limitations, unsupported cases and update cadence

Release version: `0.1.0rc1`.

This page states what the application does not do. It describes this release
candidate, not completion of the full programme; current issue status is in
[`CURRENT_STATUS.json`](../product-completion/CURRENT_STATUS.json) and the
[current SDD](../architecture/SDD.md). The application is a local research and
decision-support tool, not a financial adviser. `execution_allowed=false`.

## Authority and scope

- No live trading. There is no broker connection, no credential handling for a
  broker, no order submission and no broker write. Paper trading is a local
  simulation; its fills, fees and prices are not brokerage outcomes. Broker
  read-only, draft-order and capped-automatic stages are disabled
  contracts, not features.
- No tax advice and no personalised suitability advice.
- Normal paths exclude shorting, leverage, derivatives, crypto and unsupported
  complex products. Leveraged and inverse instruments are flagged for manual
  review.
- Risk and data-quality gates override scores, forecasts, models and UI
  actions. A model, an LLM comment or an approval in Training Centre cannot
  grant authority.

## Data

- Sources are local files, cached official evidence and optional free or public
  providers, each with coverage, freshness and licensing limits. No paid
  provider is required. The terms registry is a governance record, not legal
  advice or permission to redistribute data.
- Returns use adjusted, corporate-action-aware prices; the bulk price check
  rejects a file without an adjusted-close column. Missing, stale, conflicted or unsupported data stays visible
  and is excluded; it is never zero-filled, forward-filled or inferred.
- The `sample` bootstrap contains an identity-only universe and no prices. The
  `bulk` bootstrap validates your local price file but writes no price files in
  this release; prices are imported through Simple Scores or Import & Export.
- Optional providers (for example yfinance) need network access and can fail or
  hit quotas. Failures are shown and are non-blocking; nothing refreshes
  silently.
- Fund holdings are point-in-time evidence and a partial file does not prove an
  exposure is absent. Historical fund look-through and arbitrary retrospective
  universe replay are unsupported.
- Sector-aware stock metrics apply only where classification and source evidence
  support them; otherwise the result is unavailable or not applicable. Metrics
  from different sectors, peer sets or horizons are not interchangeable.
- Macro series show vintage dates. Later revisions are not treated as known at
  an earlier decision date.

## Models and analysis

- The deterministic baseline is the core path. TimesFM, Toto and other
  challengers are optional and show as unavailable without their packages or
  weights; model licences differ and are shown on the model cards.
- Forecasts are scored only after their horizons mature. Backtests are
  historical simulations with the displayed costs and assumptions; they are not
  prospective evidence and PBO or deflated-Sharpe diagnostics do not predict
  future returns.
- Training Centre records experiments, runs, metrics and approvals. A full
  automated training pipeline, optional experiment-tracking backends and
  champion selection are not part of this release.
- Scenarios (Stress Lab, what-if, valuation scenarios) use your explicit
  assumptions; they are not forecasts.

## Platform and operations

- Windows-first local deployment, Python 3.11 or newer. The app listens on the
  loopback interface only. The Flet desktop renderer can show a blank window on
  some Windows systems, so browser mode is the default.
- Updates are local-only and verified offline before staging. No upload
  happens silently.
- Encrypted backups can be created and validated in Settings and are checked by
  the recovery drill; a lost recovery key cannot be recovered. Restore of plain
  archives goes through the validated preview on Import & Export.
- Optional parser dependencies (filings, PDF, RSS) are not required for the
  baseline workflow.

## Update cadence

- Documentation is versioned with the release: each page here carries the
  release version from `pyproject.toml`, and a test fails when they differ.
  Bump the stamp only after reviewing the page against the code.
- Generated reference files (the data dictionary and the application API
  documents) are regenerated with every contract change; drift checks fail on a
  stale file. See [Reference documentation](../reference/README.md).
- Methodology and architecture pages follow the rule in the
  [architecture README](../architecture/README.md): update them in the same
  change that alters a boundary, schema, contract or canonical calculation.
- Workspace and tutorial pages are checked against the registered routes and
  on-screen labels; changing either requires updating these pages.
- Data refresh is started by you through the workflows in the
  [tutorials](TUTORIALS.md); optional remote refreshes are never silent.
