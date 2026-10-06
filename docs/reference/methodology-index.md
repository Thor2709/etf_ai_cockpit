# Methodology and contract index

Release version: `1.1.0b1` (display: `1.1.0-beta.1`).

One entry point to every architecture, methodology and contract page. Start with
the [architecture README](../architecture/README.md) for reading order and
authority. Generated references are listed in the
[reference index](README.md). `tests/test_user_documentation.py` fails when a
page under `docs/architecture/` or `docs/sdd/` is missing from this index.

## Architecture and scope

- [Software Design Description](../architecture/SDD.md) - current architecture, boundaries and runtime flows.
- [Traceability](../architecture/TRACEABILITY.md) - architecture families mapped to code, configuration and tests.
- [ADR-0070 product scope and authority](../architecture/ADR-0070-product-scope-and-authority.md) - local-first scope and staged authority.
- [Architecture decisions](../architecture/decisions/README.md) - accepted decision records.
- [Hybrid local data platform](../architecture/hybrid-local-data-platform.md) - analytical and transactional stores.
- [Source-of-truth reconciliation](../architecture/source-of-truth-reconciliation.md) - which store owns which fact.
- [Versioned lineage registry](../architecture/versioned-lineage-registry.md) - provenance and version identity.
- [Local application API](../architecture/application-api.md) - the typed boundary between pages and services.
- [Frontend v2 foundation](../architecture/frontend-v2.md) and [UI design system](../sdd/ui-design-system.md) - presentation layer rules.
- [Command palette](../architecture/command-palette.md), [accessibility](../architecture/accessibility.md) and [dashboard typed commands](../sdd/dashboard-typed-commands.md).
- [Programme map](../architecture/programme-map.md) - implementation status and dependencies.

## Schemas, storage and migrations

- [Application API JSON schema](../architecture/application-api-schema.json) and the [data dictionary](data-dictionary.md) - generated from code.
- [Local storage migration plan](../architecture/local-storage-migration-plan.md) - migrations and rollback.
- [Bitemporal point-in-time and vintage model](../architecture/bitemporal-vintage-model.md) - known-at and effective dates.
- [Leakage-safe feature store](../architecture/feature-store.md), [bulk cache](../architecture/bulk-cache.md) and [data catalogue](../architecture/data-catalogue.md).
- [Versioned settings bundle](../architecture/settings-bundle.md), [durable job scheduler](../architecture/durable-job-scheduler.md) and [privacy, backup and recovery](../architecture/privacy-backup-recovery.md).
- [Macro and Factors warehouse](../architecture/macro-warehouse.md) and [local OAM imports](../architecture/oam-local-import.md).

## Providers and data sources

- [Local-first data source policy](../architecture/data-source-policy.md) and [legal terms and disclaimers](../architecture/legal-terms-and-disclaimers.md).
- SEC pipeline: [bulk acquisition](../architecture/sec-bulk-acquisition.md), [companyfacts import](../architecture/sec-bulk-import.md), [companyfacts workflow](../architecture/sec-bulk-workflow.md), [submissions import](../architecture/sec-submissions-import.md), [submissions parser](../architecture/sec-submissions-parser.md) and [ingestion provenance](../architecture/sec-ingestion-provenance.md).
- [Canonical statement normalisation](../architecture/statement-normalisation.md).
- [Security policy](../architecture/security-policy.md), [supply-chain controls](../architecture/supply-chain.md) and [supply-chain intake](../architecture/supply-chain-intake.md).

## Plugins

- [Local plugin contracts](../architecture/plugin-contracts.md) - manifest, allow-list, health and authority rules; see the [developer guide](../development/DEVELOPER_GUIDE.md) for how to add one.

## Scoring formulas and decisions

- [Canonical score engine v3](../architecture/canonical-score-engine-v3.md) - the score groups and their formulas.
- [Decision architecture v1](../architecture/decision-architecture-v1.md) - how evidence, gates and states combine.
- [Execution-cost model](../architecture/execution-cost-model.md), [factor risk](../architecture/factor-risk.md), [robust risk](../architecture/robust-risk.md) and [performance attribution](../architecture/performance-attribution.md).
- [Analysis depth scheduling](../sdd/analysis-depth-scheduling.md).

## Sector, stock and ETF models

- [Stock fundamentals](../architecture/stock-fundamentals.md) and [stock research](../architecture/stock-research.md) evidence.
- [ETF economics](../architecture/etf-economics.md), [ETF report evidence](../architecture/etf-report-evidence.md) and [direct ETF overlap](../architecture/direct-etf-overlap.md).
- Ordinary funds: [screener](../sdd/fund-screener.md), [peer cohorts](../sdd/fund-peer-cohorts.md) and [exact-horizon forecasts](../sdd/fund-forecasts.md).
- [Native Sparebank EC analysis](../architecture/sparebank-ec-analysis.md) and [book-to-code manifest](../architecture/sparebank-book-manifest.md).
- [Event calendar](../architecture/event-calendar.md), [macro regime dashboard](../architecture/macro-regime-dashboard.md) and [local screener boundary](../architecture/screener.md).

## Validation and quality

- [Leakage-safe validation protocol](../architecture/validation-protocol.md), [Forecast Lab](../architecture/forecast-lab.md) and [Training Centre](../architecture/training-centre.md).
- [Deterministic event-driven backtest](../architecture/event-driven-backtest.md) and [synthetic scenarios](../architecture/synthetic-scenarios.md).
- [Quality programme](../architecture/quality-programme.md), [protected release gate](../architecture/release-gate.md) and [release certification](../architecture/release-certification.md).
- [Performance and caching policy](../architecture/performance-policy.md) and [performance budgets](../architecture/performance-budgets.md).

## Portfolio methods

- [Portfolio sandbox boundary](../architecture/portfolio-sandbox.md), [optimiser](../architecture/portfolio-optimiser.md) and [rebalancing review](../architecture/portfolio-rebalancing.md).
- [Alerts and reminders](../architecture/alerts-and-reminders.md) and [decision journal](../architecture/decision-journal.md).

## Execution states and authority

- [Proposal policy and authority boundary](../architecture/proposal-policy.md) - what a proposal may and may not do.
- [Local paper trading](../architecture/paper-trading.md) - the append-only paper ledger; operational incidents are in the [incident runbooks](../operations/INCIDENT_RUNBOOKS.md).
- Future broker designs under `docs/architecture/future/` are target designs, not current authority; `execution_allowed=false`.

## Audiences

- Users: [user guide](../user/USER_GUIDE.md), [workspaces](../user/WORKSPACES.md), [tutorials](../user/TUTORIALS.md), [limitations](../user/LIMITATIONS.md).
- Operators: [operator runbook](../operations/OPERATOR_RUNBOOK.md) and [incident runbooks](../operations/INCIDENT_RUNBOOKS.md).
- Developers: [developer guide](../development/DEVELOPER_GUIDE.md) and [CONTRIBUTING](../../CONTRIBUTING.md).
