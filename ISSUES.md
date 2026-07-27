# Issues Index

> **Compatibility issue history.** Use the
> [canonical registry](issues/issue_registry.json) for current identity,
> dependencies and status. Architecture is in the
> [SDD](docs/architecture/SDD.md); sequencing is in the
> [roadmap](docs/product-completion/programme/roadmap.md) and active
> [batch plans](plans/).

Canonical open issue tracker: `issues/open.md`.

This root file exists because some research/update prompts refer to `ISSUES.md`. Keep detailed issue records in `issues/open.md`; this file is a navigational index and coverage checklist.

## updatev2.md Additions

`C:\Users\thor2\Downloads\updatev2.md` has been transferred into the tracker as namespaced open issues because its proposed issue numbers conflict with the existing issue tracker.

## High-Priority User Additions

```text
ISSUE-0067 Local score history and per-instrument score evolution mini charts
ISSUE-0068 Two-tier universe manager and provider policy editor
ISSUE-0069 Single-file session action logging and diagnostics trace
```

`ISSUE-0067` requires local persistence of individual metric scores, component scores and total scores for every ETF/stock run, plus a compact total-score evolution graph in each expanded ETF/stock score row.

`ISSUE-0068` requires a UI-based manager for primary tier multi-provider candidates and secondary tier yfinance-only candidates, with duplicate validation and no automatic refresh/model execution on save.

`ISSUE-0069` requires `logs/session.jsonl` as the single current-session trace for button clicks, workflow steps, errors, generated files and exports, with redaction and Diagnostics UI visibility.

## 21 Trust-Critical Selected Release Issues

The active implementation sweep selected these 21 issues for source, UI, tests, audit/export, rebuild and smoke verification before closure:

2026-07-09 implementation status: foundation pass implemented session logging, provider/identity/conflict/evidence/score-history stores, trust evidence UI pages, expanded audit export and the Simple Scores grey-panel fix. Issues remain open until full issue-specific close criteria are satisfied.

```text
1. ISSUE-0069 Single-file session action logging and diagnostics trace
2. UPDATEV2-0010 Provider registry, capability probes and source authority model
3. UPDATEV2-0011 Symbol/ISIN/exchange identity resolver
4. UPDATEV2-0021 Source conflict resolver and canonical metric selector
5. UPDATEV2-0022 Evidence ledger and score component audit trail
6. UPDATEV2-0012 SEC EDGAR official statement importer
7. UPDATEV2-0013 European ESEF/iXBRL filing importer
8. UPDATEV2-0015 ETF disclosure registry
9. UPDATEV2-0016 ETF holdings normaliser
10. UPDATEV2-0017 PRIIPs KID parser
11. UPDATEV2-0019 Index methodology importer
12. ISSUE-0025 Free news and filings dashboard
13. ISSUE-0054 Point-in-time news/sentiment validation rules
14. ISSUE-0055 Optional free provider research/stubs: SEC EDGAR, FRED, Stooq, RSS
15. ISSUE-0023 Stock fundamentals quality module hardening
16. ISSUE-0067 Local score history and per-instrument score evolution mini charts
17. ISSUE-0047 Feature-driver explanations for every evidence component
18. ISSUE-0052 Correlation clustering and factor-crowding warnings
19. ISSUE-0059 Benchmark-relative sector/theme attribution beyond single benchmark beta
20. ISSUE-0064 Friction-adjusted return estimate per evidence score
21. UPDATEV2-0028 Report/audit packet expansion for providers, filings, ETF docs and candles
```

Primary artefacts:

```text
logs/session.jsonl
data/clean/provider_probe_results.parquet
data/clean/instrument_identity.parquet
data/clean/source_conflicts.parquet
data/derived/evidence_ledger.parquet
data/derived/score_components.parquet
data/derived/score_history.parquet
data/derived/score_metric_history.parquet
data/derived/feature_drivers.parquet
data/derived/correlation_clusters.parquet
data/derived/benchmark_attribution.parquet
```

Open updatev2 implementation issues:

```text
UPDATEV2-0010 Provider registry, capability probes and source authority model
UPDATEV2-0011 Symbol/ISIN/exchange identity resolver
UPDATEV2-0012 SEC EDGAR official statement importer
UPDATEV2-0013 European ESEF/iXBRL filing importer
UPDATEV2-0014 France DILA and Netherlands AFM OAM discovery adapters
UPDATEV2-0015 ETF disclosure registry
UPDATEV2-0016 ETF holdings normaliser
UPDATEV2-0017 PRIIPs KID parser
UPDATEV2-0018 ETF prospectus, annual and half-year report parser
UPDATEV2-0019 Index methodology importer
UPDATEV2-0020 SFDR disclosure parser
UPDATEV2-0021 Source conflict resolver and canonical metric selector
UPDATEV2-0022 Evidence ledger and score component audit trail
UPDATEV2-0023 FMP optional provider adapter
UPDATEV2-0024 Alpha Vantage verification/fallback adapter
UPDATEV2-0025 Finnhub experimental adapter with entitlement probes
UPDATEV2-0026 Candle feature/context/backtest module
UPDATEV2-0027 UI workflow/button reliability and progress indicators
UPDATEV2-0028 Report/audit packet expansion for providers, filings, ETF docs and candles
UPDATEV2-0029 Rebuild/test/update discipline automation
UPDATEV2-0030 Optional OHLCV fallback providers: Stooq, Twelve Data and Tiingo
```

## Current Close Rule

Do not close any open implementation issue unless:

- code is implemented;
- tests are added or updated;
- existing tests pass;
- app starts locally;
- relevant UI workflow works or shows explicit unavailable/error state;
- no API keys or secrets are logged/exported/committed;
- raw data is cached immutably where relevant;
- clean data is written only after validation;
- source authority, staleness and conflicts are visible where relevant;
- audit packet includes the new evidence where relevant;
- `REPORT.md`, `plan.md`, `issues/open.md` and `issues/closed.md` are updated;
- Windows package is rebuilt if app/runtime code changed.

## 2026-07-09 Launcher, Sparebanken And Reliability Run Status

Closed narrow run records are in `issues/closed.md`:

```text
RUN-CLOSED-2026-07-09-LAUNCHER
RUN-CLOSED-2026-07-09-SPAREBANKEN-DATA
RUN-CLOSED-2026-07-09-SPAREBANKEN-UI
```

The selected 20 broad non-previous-21 issues remain open with partial/deferred notes in `issues/open.md`. The previous 21 trust-critical issues remain open where their parser/provider/UI/export/browser evidence gates are not fully satisfied.

Post-review verification on 2026-07-10 corrected timestamped output selection and native lock handling. On 2026-07-11, `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` passed the current evaluator-backed source, tests, UI, export, rebuild and Chrome evidence gates and are closed. All parser/provider and incomplete product records remain open.

See `issues/closed.md` for the current completed-issue record.
