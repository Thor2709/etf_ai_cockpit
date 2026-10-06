# Workspaces and navigation

Release version: `1.1.0b1` (display: `1.1.0-beta.1`).

This guide lists every page the application registers in
`src/etf_cockpit/core/navigation.py` (bound to page renderers by
`src/etf_cockpit/app/router.py`) and the workspace that groups it. The
[user guide](USER_GUIDE.md) explains how to read scores and evidence; the
[tutorials](TUTORIALS.md) walk through complete tasks. Every page ends with a
help panel; the `/help` page holds the glossary. Nothing in the application can
place a live order: `execution_allowed=false`.

## The shell

Every page is shown inside the same shell.

- The safety rail (top): `Execution locked`, data quality, as-of time, price
  basis (`adjusted`), forecast source and `execution_allowed=false`. A value the
  current snapshot cannot supply is shown as `Unavailable` with the reason in
  its tooltip.
- **Command palette**: type part of a page title, route or workspace name and
  pick a result; Enter opens the first match. It lists up to eight matches.
- **Evidence mode**: `Compact - decision summary`, `Default - evidence and
  uncertainty` or `Advanced - evidence and diagnostics`. It is a display
  preference held in the session (it is saved with a Comparison workspace and
  shown in the dashboard details); it never changes a score.
- **What changed**: opens the What Changed page.
- Context pills below the title show the data as-of date, price basis, horizon
  and currency, or `Unavailable` when no value is set.
- Page buttons for the active workspace sit under the header; **All pages**
  expands every other workspace.
- The workspace dock on the left switches workspace; Help is pinned at the
  bottom. Below a window width of 1100 px the shell switches to a stacked
  layout without the sidebar.
- A running action shows a progress strip with a **Cancel** button.

## Workspace map

Routes marked `/instrument/<ID>` open the Instrument Detail page for that
instrument ID.

### Home

| Route | Page | Use it to |
| --- | --- | --- |
| `/` | Simple Scores | Compare configured instruments on shared score evidence; run the refresh, algorithms and forecast workflow; read the run-changes and news digests. |
| `/onboarding` | First-run Setup | Save local preferences, a watchlist and the offline bootstrap choice. |

### Research

| Route | Page | Use it to |
| --- | --- | --- |
| `/stock-research` | Stock Research | Inspect statement-derived profitability, balance-sheet, valuation and sector evidence. |
| `/etf` | Instrument Detail | Inspect one instrument's identity, holdings, scores, events and limitations. |
| `/instrument` | Instrument Detail | Same page; `/instrument/<ID>` selects the instrument. |
| `/signals` | Scores | Read canonical score components, evidence gates and signal-state reasons. |
| `/screener` | Fundamentals Screener | Filter loaded fundamentals; run, save and export a screen. |
| `/strategy-builder` | Strategy Builder | Enable or disable benchmarked, research-only strategy templates. |

### Compare

| Route | Page | Use it to |
| --- | --- | --- |
| `/comparison` | Comparison | Compare two instruments' aligned scores, prices and evidence; export or save the workspace. |

### Map

| Route | Page | Use it to |
| --- | --- | --- |
| `/macro` | Macro and Factors | Read macro observations with their release and vintage dates. |

### Universe

| Route | Page | Use it to |
| --- | --- | --- |
| `/universe` | Universe | Add, edit, import and remove validated instruments and watchlists. |
| `/catalogue` | Data Catalogue | Check dataset coverage, dates, source and licence notes. |
| `/providers` | Provider Status | Check provider capability, cache, freshness, terms and failures. |
| `/filings` | Filings & Statements | Review filing identity, period, publication and retrieval details. |
| `/etf-disclosures` | ETF Disclosures | Inspect fund disclosures and their dates. |
| `/news-context` | News & Context | Read dated news as context only. |
| `/data-health` | Data Health | Check freshness, coverage and corruption state of every configured store. |

### Portfolio

| Route | Page | Use it to |
| --- | --- | --- |
| `/portfolio` | Portfolio Sandbox | Explore holdings, what-if candidates and rebalance previews; nothing is submitted. |
| `/portfolio-optimiser` | Portfolio Optimiser Lab | Test candidate weights against the displayed constraints. |
| `/risk` | Risk Evidence | Review exposure, factor risk, volatility, drawdown, liquidity and cost evidence. |
| `/stress-lab` | Stress Lab | Replay history or apply explicit shocks; save versioned scenarios. |
| `/decision-journal` | Decision Journal | Record your own decision and rationale beside the evidence snapshot. |
| `/forward-evidence` | Forward Evidence Diary | Record observations and update outcomes once their horizons mature. |
| `/operations` | Operations Centre | Review proposals and the local paper account and ledger. |

### Lab

| Route | Page | Use it to |
| --- | --- | --- |
| `/forecasts` | Forecast Lab | Review forecasts, matured outcomes, error measures and model cards. |
| `/training-centre` | Training Centre | Inspect recorded experiments, runs, metrics, model registry and approval state. |
| `/feature-catalogue` | Feature Catalogue | Read each feature's meaning, source and supported use. |
| `/data-models` | Data & Models | Compare model tasks, availability, versions and licences. |
| `/backtests` | Backtests | Read historical results with their universe, benchmark and cost assumptions. |

### Changes

| Route | Page | Use it to |
| --- | --- | --- |
| `/what-changed` | What Changed | Compare dated evidence, source revisions and policy changes between runs. |
| `/jobs` | Jobs & Activity | Check durable job status, progress, recorded errors and recovery actions. |

### Help

| Route | Page | Use it to |
| --- | --- | --- |
| `/help` | Help & Glossary | Look up score, data and authority terms. |
| `/settings` | Settings | Review preferences, release metadata, backups, credentials and legal terms. |
| `/diagnostics` | Diagnostics | Inspect runtime, packages, security policy and the session log. |
| `/errors` | Errors & Recovery | Read recent controlled failures and the recovery policy. |
| `/import-export` | Import & Export | Preview and commit imports; export evidence; create and restore backups. |
| `/system-map` | System Map | See which policy and evidence gates control a capability. |
| `/chatgpt` | Audit Notes | Review local audit commentary; it is advisory only. |
| `/evidence` | Evidence Ledger | Trace displayed facts to source, observation date and authority. |
| `/release-readiness` | Release Readiness | Read gate results and their evidence scope. |
| `/roadmap` | Programme Map | See implementation status and dependencies of planned work. |

An unregistered route shows `Route unavailable`; return to a workspace from the
dock or the command palette.
