# INT-19 — Macro fetchers, indicators and regime label

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `D`; estimated size `medium`
- Logical prerequisites: `INT-01`; source-file serialization: `-`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `data/fred_provider.py; data/ecb_provider.py; data/macro_warehouse.py; features/macro.py; features/regime.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Macro fetchers, indicators and regime label
- Gate G3 | Priority P2 | Size medium | Depends on: INT-01 | Features: F0004, F0026, F0070, F0071, F0072, F0073, F0074, F0075, F0076, F0209
- Note: INT-01 is needed for the regime label only (statsmodels); the fetch and indicator part can start before it.
- Upstream: `statsmodels` v0.15.0 `statsmodels/tsa/regime_switching/markov_regression.py` (`MarkovRegression`). Reference only: `mortada/fredapi` `fredapi/fred.py`; `khaeru/sdmx` `sdmx/sources.json`.
- Targets: `data/fred_provider.py` (`FredProvider:16`), `data/macro_warehouse.py` (`MacroObservation:57`, `_latest_vintages:762`, `ingest_curve:1122`, `curve_rate:1233`), `data/ecb_provider.py` (new), `features/macro.py`, `features/regime.py` (`:118-128`), `analysis/fund_analysis.py` (`:467-480`), `analysis/decision/etf.py` (`:744-773`).
- Steps:
  - FRED: fetch with `realtime_start` / `realtime_end` (ALFRED vintages); each vintage is one `MacroObservation` revision with `pit_grade = observed`. A default fetch returns today's vintage only: it is stored as `pit_grade = approximated` and barred from historical features.
  - ECB data API (CSV) for rates and reference FX. Units and series terms recorded per series.
  - Indicators: 10y-2y and 10y-3m slope, BAA-10y spread, high-yield OAS, Sahm rule, NFCI, VIX, equity risk premium, CAPE (Shiller file), market-cap-to-GDP; hedged share-class carry from the short-rate differential.
  - Regime label: two-state Markov-switching model, refitted on an expanding window that ends at each cut-off; the label uses **filtered** probabilities at the cut-off, never smoothed probabilities and never a fit that saw later data. Shadow column only.
- Acceptance: an as-of query before a revision returns the earlier vintage; a latest-only series cannot enter a historical feature; the regime probability at `t` is identical when later data are appended; with no API key every feature is `unavailable`.
